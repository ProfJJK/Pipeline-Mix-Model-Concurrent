"""Tests for simple approved-for-dispatch task execution and artifact validation (`P428-11`)."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from cochem_pipeline.planning_journal import PlanningJournal
from cochem_pipeline.planning_runtime import PlanningController
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.store import JobStore
from cochem_pipeline.task_execution_428 import (
    SimpleTaskExecutionRuntime,
    validate_simple_execution_output,
)
from pipeline_tests.test_planning_gateway_428 import accepted_receipt
from pipeline_tests.test_workflow_428 import document


ROOT = Path(__file__).resolve().parents[1]


def _valid_execution_output(srs_doc: dict) -> dict:
    content = "def compute_check(x: int) -> int:\n    return x + 1\n"
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return {
        "artifact_text": "Implemented and verified compute_check deliverable.",
        "deliverables": [
            {
                "name": "compute_check.py",
                "content": content,
                "sha256": sha,
            }
        ],
        "requirement_evidence": [
            {
                "requirement_id": req["id"],
                "deliverable_name": "compute_check.py",
                "verification_evidence": f"Verified {req['id']} against compute_check.py",
            }
            for req in srs_doc["requirements"]
        ],
        "release_criteria_results": [
            {
                "criterion": crit,
                "passed": True,
                "evidence": f"Criterion '{crit}' verified with exit code 0",
            }
            for crit in srs_doc["release_criteria"]
        ],
    }


@pytest.fixture
def simple_env(tmp_path: Path):
    catalog = json.loads((ROOT / "docs" / "4.2.8" / "routing-candidate.json").read_text(encoding="utf-8"))
    journal = PlanningJournal(tmp_path / "planning428.db", catalog, flash_context_limit=100000)
    store = JobStore(tmp_path / "jobs428.db", routing_policy=load_routing_policy({"policy_version": 3}))
    clock = [100.0]
    exec_runtime = SimpleTaskExecutionRuntime(journal, store, clock=lambda: clock[0])
    controller = PlanningController(
        journal,
        store,
        clock=lambda: clock[0],
        execution_runtime=exec_runtime,
    )
    controller.test_clock = clock
    try:
        yield controller, exec_runtime, journal, store
    finally:
        store.close()


def _advance_to_ready(controller: PlanningController, task_id: str = "task-simple-01", tier: int = 2) -> dict:
    controller.submit("Implement simple bounded check", task_id)
    controller.test_clock[0] += 2
    controller.step()
    plan_job = controller.store.claim(
        "inert-worker",
        worker_slot="slot1",
        allowed_kinds=["TASK_PLAN"],
        requires_cleanup=True,
    )
    assert plan_job is not None
    srs_out = document(tier)
    controller.store.clear_execution_quarantine(plan_job["job_id"], plan_job["attempt_id"], plan_job["fencing_token"])
    controller.store.complete(
        plan_job["job_id"],
        plan_job["attempt_id"],
        plan_job["fencing_token"],
        srs_out,
        accepted_receipt(plan_job, srs_out),
    )
    controller.test_clock[0] += 2
    controller.step()
    assert controller.journal.status(task_id)["stage"] == "READY"
    return srs_out


def test_intake_srs_claim_native_result_artifact_completed_without_chapter_expansion(simple_env):
    controller, exec_runtime, journal, store = simple_env
    assert controller.status()["execution_materialization"] == "CONNECTED"
    srs_doc = _advance_to_ready(controller, "task-simple-01", tier=2)

    # Next step materializes exactly one execution job (no CHAPTER_DRAFT or MANIFEST_GENERATOR)
    controller.test_clock[0] += 2
    controller.step()
    status_mid = controller.task_status("task-simple-01")
    assert status_mid["controller"]["status"] == "WAITING_FOR_EXECUTION_BOARD"
    assert status_mid["deliverable_completed"] is False

    # Repeated step/materialize is atomic and idempotent
    exec_job_1 = exec_runtime.materialize("task-simple-01")
    exec_job_2 = exec_runtime.materialize("task-simple-01")
    assert exec_job_1["job_id"] == exec_job_2["job_id"]
    with store._connection() as conn:
        kinds = [r[0] for r in conn.execute("SELECT kind FROM pipeline_jobs").fetchall()]
        assert "CHAPTER_DRAFT" not in kinds
        assert "MANIFEST_GENERATOR" not in kinds

    # Claim execution job honoring 4-slot ceiling and native allowlists
    claimed = store.claim(
        "inert-worker",
        worker_slot="slot2",
        max_workers=4,
        allowed_kinds=["TASK_PLAN"],
        requires_cleanup=True,
    )
    assert claimed is not None
    assert claimed["job_id"] == exec_job_1["job_id"]
    assert claimed["routing"]["score_details"]["score"] == 2

    exec_out = _valid_execution_output(srs_doc)

    # Completing without clearing execution quarantine keeps task in READY / WAITING_FOR_NATIVE_CLEANUP
    store.complete(
        claimed["job_id"],
        claimed["attempt_id"],
        claimed["fencing_token"],
        exec_out,
        accepted_receipt(claimed, exec_out),
    )
    controller.test_clock[0] += 2
    controller.step()
    pre_cleanup = controller.task_status("task-simple-01")
    assert pre_cleanup["controller"]["status"] == "WAITING_FOR_NATIVE_CLEANUP"
    assert pre_cleanup["task"]["stage"] == "READY"
    assert pre_cleanup["deliverable_completed"] is False

    # Clear execution quarantine and reopen controller to verify restart durability
    store.clear_execution_quarantine(claimed["job_id"], claimed["attempt_id"], claimed["fencing_token"])
    reopened_journal = PlanningJournal(journal.path, journal.catalog, flash_context_limit=100000)
    reopened_exec = SimpleTaskExecutionRuntime(reopened_journal, store, clock=lambda: 300.0)
    reopened_controller = PlanningController(
        reopened_journal,
        store,
        clock=lambda: 300.0,
        execution_runtime=reopened_exec,
    )
    reopened_controller.step()

    final_status = reopened_controller.task_status("task-simple-01")
    assert final_status["task"]["stage"] == "COMPLETED"
    assert final_status["deliverable_completed"] is True
    assert final_status["execution"]["verification_status"] == "verified"
    assert final_status["execution"]["deliverables"][0]["name"] == "compute_check.py"


def test_invalid_output_and_stale_claim_are_rejected(simple_env):
    controller, _, _, store = simple_env
    srs_doc = _advance_to_ready(controller, "task-invalid-01", tier=2)
    controller.test_clock[0] += 2
    controller.step()

    claimed = store.claim(
        "inert-worker",
        worker_slot="slot1",
        max_workers=4,
        allowed_kinds=["TASK_PLAN"],
        requires_cleanup=True,
    )
    assert claimed is not None
    valid_out = _valid_execution_output(srs_doc)

    # 1. Model prose alone is rejected
    prose_only = {"artifact_text": "I completed everything successfully."}
    with pytest.raises(ValueError, match="Simple execution output requires"):
        store.complete(
            claimed["job_id"],
            claimed["attempt_id"],
            claimed["fencing_token"],
            prose_only,
            accepted_receipt(claimed, prose_only),
        )

    # 2. Tampered deliverable sha256 is rejected
    bad_hash = deepcopy(valid_out)
    bad_hash["deliverables"][0]["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="sha256 does not match"):
        store.complete(
            claimed["job_id"],
            claimed["attempt_id"],
            claimed["fencing_token"],
            bad_hash,
            accepted_receipt(claimed, bad_hash),
        )

    # 3. Missing requirement coverage is rejected
    missing_req = deepcopy(valid_out)
    missing_req["requirement_evidence"] = []
    with pytest.raises(ValueError, match="requirement_evidence"):
        store.complete(
            claimed["job_id"],
            claimed["attempt_id"],
            claimed["fencing_token"],
            missing_req,
            accepted_receipt(claimed, missing_req),
        )

    # 4. Unsatisfied release criterion is rejected
    failed_crit = deepcopy(valid_out)
    failed_crit["release_criteria_results"][0]["passed"] = False
    with pytest.raises(ValueError, match="Release criterion not satisfied"):
        store.complete(
            claimed["job_id"],
            claimed["attempt_id"],
            claimed["fencing_token"],
            failed_crit,
            accepted_receipt(claimed, failed_crit),
        )

    # 5. Stale fencing token cannot complete the job
    with pytest.raises(ValueError):
        store.complete(
            claimed["job_id"],
            claimed["attempt_id"],
            claimed["fencing_token"] + 99,
            valid_out,
            accepted_receipt(claimed, valid_out),
        )

    assert controller.task_status("task-invalid-01")["deliverable_completed"] is False
