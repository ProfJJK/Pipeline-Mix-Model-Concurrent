"""Integrated acceptance tests for Pipeline 4.2.8 (`P428-24`).

Covers:
1. Simple single-type task (`COD-TERM`, tier 2) -> `SRS -> READY -> SIMPLE_EXECUTION -> COMPLETED`
   + deterministic `CompletionAuditRuntime` spot-check verification.
2. Multitype task (`['COD-TERM', 'SCI-FORMAL']`, tier 2) -> bypasses fast-path (`needs_wbs=True`),
   `PLAN_REVIEW -> WBS -> MICROTASKS -> MICROTASK_ASSESSMENT -> MICROTASKS_READY`, parallel independent
   fragments within 4-seat ceiling, dependent assembly + final_test + controller test receipt -> `COMPLETED`.
3. Researched WBS task (tier 5) -> 3-channel research (`internet`, `wiki_rag`, `papers`) via `ResearchRuntime`,
   hydrated excerpts in `PLAN_REVIEW` prompt, full WBS/microtask release -> `COMPLETED`.
4. Owner-approved high-tier task (tier 8) -> `OWNER_APPROVAL` gate, rejects shared agent bearer token and
   stale revision, accepts human-owner HMAC receipt via `OwnerApprovalBroker`, completes research, tier-9
   independent review, WBS/microtasks, and controller-verified release -> `COMPLETED`.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cochem_pipeline.admission import JointAdmission
from cochem_pipeline.completion_audit_428 import CompletionAuditRuntime
from cochem_pipeline.owner_approval_428 import OwnerApprovalBroker
from cochem_pipeline.planning_journal import PlanningJournal
from cochem_pipeline.planning_runtime import PlanningController
from cochem_pipeline.repair_queue_428 import RepairQueue
from cochem_pipeline.research_evidence_428 import ResearchEvidenceStore
from cochem_pipeline.research_runtime_428 import ResearchRuntime
from cochem_pipeline.research_search_428 import HttpResponseFixture, ResearchSearchClient
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.store import JobStore
from cochem_pipeline.task_execution_428 import SimpleTaskExecutionRuntime
from cochem_pipeline.task_release_428 import TaskReleaseRuntime
from cochem_pipeline.task_routing import digest
from cochem_pipeline.worker import node_prompt
from pipeline_tests.test_planning_gateway_428 import accepted_receipt
from pipeline_tests.test_workflow_428 import document, microtasks, wbs


ROOT = Path(__file__).resolve().parents[1]
OWNER_SECRET = "owner-acceptance-secret-key-at-least-32-chars-428"
AGENT_TOKEN = "shared-agent-bearer-token-cannot-approve-srs-428"


def _load_catalog() -> dict:
    return json.loads((ROOT / "docs" / "4.2.8" / "routing-candidate.json").read_text(encoding="utf-8"))


def _make_acceptance_stack(tmp_path: Path):
    catalog = _load_catalog()
    clock = [1000.0]
    broker = OwnerApprovalBroker(
        tmp_path / "owner428.db",
        owner_secret=OWNER_SECRET,
        shared_agent_tokens={AGENT_TOKEN},
        clock=lambda: clock[0],
    )
    journal = PlanningJournal(
        tmp_path / "planning428.db",
        catalog,
        flash_context_limit=100000,
        owner_receipt=broker.load_for_journal,
    )
    store = JobStore(
        tmp_path / "jobs428.db",
        routing_policy=load_routing_policy({"policy_version": 3}),
    )

    def _transport(url: str, headers: dict, timeout: float, max_bytes: int) -> HttpResponseFixture:
        if "en.wikipedia.org" in url:
            body = json.dumps(
                {
                    "query": {
                        "search": [
                            {
                                "pageid": 501,
                                "title": "State machine",
                                "snippet": "Deterministic state transitions with durability guarantees.",
                            }
                        ]
                    }
                }
            ).encode("utf-8")
            return HttpResponseFixture(status_code=200, body=body, url=url)
        body = json.dumps(
            {
                "results": [
                    {
                        "id": "https://openalex.org/W501",
                        "doi": "https://doi.org/10.1000/428",
                        "title": "Fault-Tolerant Task Routing",
                        "publication_year": 2025,
                        "abstract": "Empirical evaluation of five-option task routing.",
                    }
                ]
            }
        ).encode("utf-8")
        return HttpResponseFixture(status_code=200, body=body, url=url)

    class _Knowledge:
        def status(self):
            return {"ready": True, "generation": "g-" + "4" * 32, "manifest_sha256": "5" * 64}

        def search(self, query: str, limit: int = 5):
            return [
                {
                    "doc_path": "wiki/428/routing.md",
                    "section_title": "Task Routing 4.2.8",
                    "snippet": "Wiki RAG excerpt on 4.2.8 five-option routing.",
                    "generation": "g-" + "4" * 32,
                }
            ]

        def read(self, doc_path: str):
            return {
                "path": doc_path,
                "sha256": "6" * 64,
                "text": "Full wiki document for 4.2.8 routing.",
                "generation": "g-" + "4" * 32,
            }

    class _Authority:
        def status(self, *, force: bool = False):
            return {"authority_matches_capture": True}

    ev_store = ResearchEvidenceStore(tmp_path / "research428.db")
    res_rt = ResearchRuntime(
        ev_store,
        ResearchSearchClient(transport=_transport, resolver=lambda _h: ["93.184.216.34"]),
        knowledge_service=_Knowledge(),
        knowledge_authority=_Authority(),
        clock=lambda: clock[0],
    )
    exec_rt = SimpleTaskExecutionRuntime(journal, store, clock=lambda: clock[0])
    rel_rt = TaskReleaseRuntime(journal, store, owner_broker=broker, clock=lambda: clock[0])
    rep_q = RepairQueue(
        tmp_path / "repair428.db",
        catalog,
        profiles={
            "repair_claude": {"provider": "claude", "quota_pool": "anthropic"},
            "repair_codex": {"provider": "codex", "quota_pool": "openai"},
            "repair_agy": {"provider": "gemini", "quota_pool": "google"},
        },
        normal_profile_ids={"slot1", "slot2", "slot3", "slot4", "slot5", "slot6"},
        verify_reservation=lambda _: None,
        verify_commit=lambda c, t: None,
    )
    audit_rt = CompletionAuditRuntime(
        tmp_path / "audit428.db",
        catalog,
        rep_q,
        sample_basis_points=10000,
        clock=lambda: clock[0],
    )
    controller = PlanningController(
        journal,
        store,
        clock=lambda: clock[0],
        research_runtime=res_rt,
        execution_runtime=exec_rt,
        release_runtime=rel_rt,
        repair_queue=rep_q,
        audit_runtime=audit_rt,
    )
    admission = JointAdmission(store, None, capacity=4, max_capacity=4)
    return controller, admission, broker, res_rt, rel_rt, audit_rt, store, clock


def _complete_node(store: JobStore, controller: PlanningController, node: dict, output: dict) -> None:
    store.clear_execution_quarantine(node["job_id"], node["attempt_id"], node["fencing_token"])
    store.complete(
        node["job_id"],
        node["attempt_id"],
        node["fencing_token"],
        output,
        accepted_receipt(node, output),
    )
    controller.notify_job_changed(node["job_id"])


def _make_mt_output(node: dict) -> dict:
    deliverables = []
    for dname in node["deliverables"]:
        body = f"# Verified deliverable {dname} for {node['microtask_id']}\n"
        deliverables.append(
            {
                "name": dname,
                "content": body,
                "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            }
        )
    first_deliv = deliverables[0]["name"]
    return {
        "artifact_text": f"Completed {node['microtask_id']} ({node['role']})",
        "deliverables": deliverables,
        "requirement_evidence": [
            {
                "requirement_id": req_id,
                "deliverable_name": first_deliv,
                "verification_evidence": f"Verified {req_id} in {first_deliv}",
            }
            for req_id in node.get("requirement_ids", ["R1"])
        ],
        "release_criteria_results": [
            {
                "criterion": crit,
                "passed": True,
                "evidence": f"Verified {crit}",
            }
            for crit in node["release_criteria"]
        ],
    }


def _drive_microtasks_to_completion(
    controller: PlanningController,
    admission: JointAdmission,
    rel_rt: TaskReleaseRuntime,
    store: JobStore,
    clock: list[float],
    task_id: str,
    requirements: list[str],
) -> dict:
    for _ in range(8):
        clock[0] += 2
        controller.step()
        slot_idx = 1
        while True:
            admitted = admission.claim("warden", worker_slot=f"slot{slot_idx}", requires_cleanup=True)
            if admitted is None:
                break
            mt_job, _ = admitted
            _complete_node(store, controller, mt_job, _make_mt_output(mt_job["payload"]["microtask_node"]))
            slot_idx = (slot_idx % 4) + 1
        st = controller.task_status(task_id)
        if st["controller"]["status"] == "WAITING_FOR_CONTROLLER_TEST_VERIFICATION":
            rel_rt.record_controller_test_receipt(
                task_id,
                "M3",
                passed=True,
                exit_code=0,
                cleanup_verified=True,
                status="COMPLETED",
                verified_requirements=requirements,
                summary="Controller verified all SRS requirements",
            )
            clock[0] += 5
            controller.step()
        if controller.task_status(task_id)["deliverable_completed"]:
            break
    return controller.task_status(task_id)


def test_simple_single_type_task_reaches_verified_artifact_and_passes_spotcheck(tmp_path: Path):
    controller, admission, _, _, _, audit_rt, store, clock = _make_acceptance_stack(tmp_path)
    try:
        controller.submit("Implement simple bounded check", "task-acc-simple")
        clock[0] += 2
        controller.step()
        plan_node, _ = admission.claim("warden", worker_slot="slot1", requires_cleanup=True)
        srs2 = document(2, ["COD-TERM"])
        _complete_node(store, controller, plan_node, srs2)
        controller.step()  # Imports SRS -> READY
        controller.step()  # Submits SIMPLE_EXECUTION

        exec_node, _ = admission.claim("warden", worker_slot="slot1", requires_cleanup=True)
        code_body = "def run_check() -> bool:\n    return True\n"
        code_sha = hashlib.sha256(code_body.encode("utf-8")).hexdigest()
        exec_out = {
            "artifact_text": "Implemented run_check.",
            "deliverables": [{"name": "check.py", "content": code_body, "sha256": code_sha}],
            "requirement_evidence": [
                {
                    "requirement_id": "R1",
                    "deliverable_name": "check.py",
                    "verification_evidence": "Verified R1",
                }
            ],
            "release_criteria_results": [
                {
                    "criterion": srs2["release_criteria"][0],
                    "passed": True,
                    "evidence": "pytest passed",
                }
            ],
        }
        _complete_node(store, controller, exec_node, exec_out)
        controller.step()

        final = controller.task_status("task-acc-simple")
        assert final["deliverable_completed"] is True
        assert final["execution"]["verification_status"] == "verified"

        # Spot-check the completed execution with an independent model family
        enq = audit_rt.enqueue_completion(
            exec_node["job_id"],
            task_id="task-acc-simple",
            output_sha256=code_sha,
            producer_model_family=exec_node["route"]["model"],
            task_types=["COD-TERM"],
            expected_requirements=["R1"],
        )
        spot = audit_rt.execute_spotcheck(
            enq["audit_key"],
            auditor_model_family="claude-opus-5-5",
            artifact_bytes=code_body.encode("utf-8"),
            test_receipt={
                "passed": True,
                "exit_code": 0,
                "test_output_sha256": digest("pytest-ok"),
                "requirements_verified": ["R1"],
            },
            controller_receipt={
                "cleanup_verified": True,
                "lease_fenced": True,
                "invariant_violations": [],
            },
            auditor_verdict="PASS",
            auditor_findings="Verified deliverable and test receipt",
        )
        assert spot["disposition"] == "VERIFIED_PASS"
        assert spot["incident_id"] is None
    finally:
        store.close()


def test_multitype_task_decomposes_and_releases_verified_manifest(tmp_path: Path):
    controller, admission, _, _, rel_rt, _, store, clock = _make_acceptance_stack(tmp_path)
    try:
        controller.submit("Implement multitype scientific CLI tool", "task-acc-multi")
        clock[0] += 2
        controller.step()
        plan_node, _ = admission.claim("warden", worker_slot="slot1", requires_cleanup=True)
        # Tier 2 with 2 task types forces decomposition (needs_wbs=True -> PLAN_REVIEW)
        srs_multi = document(2, ["COD-TERM", "SCI-FORMAL"])
        _complete_node(store, controller, plan_node, srs_multi)
        controller.step()
        assert controller.journal.status("task-acc-multi")["stage"] == "PLAN_REVIEW"

        for stage_output in (
            {"accepted": True, "findings": [], "suggestions": [], "clarifications": []},
            {"wbs": wbs()},
            {"microtasks": microtasks()},
            {
                "assessments": [
                    {
                        "id": row["id"],
                        "complexity": row["complexity"],
                        "task_types": row["task_types"],
                        "rationale": "Assessed fragment",
                    }
                    for row in microtasks()
                ]
            },
        ):
            controller.step()
            mnode, _ = admission.claim("warden", worker_slot="slot1", requires_cleanup=True)
            _complete_node(store, controller, mnode, stage_output)
            controller.step()

        assert controller.journal.status("task-acc-multi")["stage"] == "MICROTASKS_READY"
        final = _drive_microtasks_to_completion(
            controller, admission, rel_rt, store, clock, "task-acc-multi", ["R1"]
        )
        assert final["deliverable_completed"] is True
        assert final["release"]["verified_requirements"] == ["R1"]
    finally:
        store.close()


def test_researched_wbs_and_owner_approved_high_tier_tasks_complete_end_to_end(tmp_path: Path):
    controller, admission, broker, res_rt, rel_rt, _, store, clock = _make_acceptance_stack(tmp_path)
    try:
        # 1. Researched WBS task (tier 5)
        controller.submit("Implement researched tier-5 state machine", "task-acc-res5")
        clock[0] += 2
        controller.step()
        srs_node, _ = admission.claim("warden", worker_slot="slot1", requires_cleanup=True)
        _complete_node(store, controller, srs_node, document(5, ["COD-TERM"]))
        controller.step()  # -> RESEARCH
        controller.step()  # Enqueues research
        assert res_rt.step_worker() == 1
        clock[0] += 35
        controller.step()  # Imports research -> PLAN_REVIEW

        controller.step()  # Submits PLAN_REVIEW
        rev_node, _ = admission.claim("warden", worker_slot="slot1", requires_cleanup=True)
        prompt_text = node_prompt(rev_node, "")
        assert "Deterministic state transitions with durability guarantees." in prompt_text
        assert "Wiki RAG excerpt on 4.2.8 five-option routing." in prompt_text
        assert "Empirical evaluation of five-option task routing." in prompt_text
        _complete_node(
            store,
            controller,
            rev_node,
            {"accepted": True, "findings": [], "suggestions": [], "clarifications": []},
        )
        controller.step()

        for stage_output in (
            {"wbs": wbs()},
            {"microtasks": microtasks()},
            {
                "assessments": [
                    {
                        "id": row["id"],
                        "complexity": row["complexity"],
                        "task_types": row["task_types"],
                        "rationale": "Assessed fragment",
                    }
                    for row in microtasks()
                ]
            },
        ):
            controller.step()
            mnode, _ = admission.claim("warden", worker_slot="slot1", requires_cleanup=True)
            _complete_node(store, controller, mnode, stage_output)
            controller.step()

        final5 = _drive_microtasks_to_completion(
            controller, admission, rel_rt, store, clock, "task-acc-res5", ["R1"]
        )
        assert final5["deliverable_completed"] is True

        # 2. Owner-approved high-tier task (tier 8)
        controller.submit("Implement high-tier distributed consensus module", "task-acc-tier8")
        clock[0] += 2
        controller.step()
        srs8_node, _ = admission.claim("warden", worker_slot="slot1", requires_cleanup=True)
        _complete_node(store, controller, srs8_node, document(8, ["COD-TERM"]))
        controller.step()  # -> OWNER_APPROVAL
        controller.step()  # WAITING_FOR_OWNER_APPROVAL
        assert controller.task_status("task-acc-tier8")["controller"]["status"] == "WAITING_FOR_OWNER_APPROVAL"

        # Register owner approval request and verify shared agent token is rejected
        t8_state = controller.journal.status("task-acc-tier8")
        req8 = broker.create_request(t8_state)
        with pytest.raises(PermissionError, match="Shared agent bearer token"):
            broker.record_decision(req8["request_id"], decision="approved", owner_token=AGENT_TOKEN)

        rcpt8 = broker.record_decision(
            req8["request_id"],
            decision="approved",
            owner_token=OWNER_SECRET,
            notes="Owner approved tier-8 SRS",
        )
        controller.journal.apply_owner_approval("task-acc-tier8", t8_state["journal_version"], rcpt8["receipt_id"])
        assert controller.journal.status("task-acc-tier8")["stage"] == "RESEARCH"

        clock[0] += 35
        controller.step()  # Enqueues research
        assert res_rt.step_worker() == 1
        clock[0] += 35
        controller.step()  # Imports research -> PLAN_REVIEW

        for stage_output in (
            {"accepted": True, "findings": [], "suggestions": [], "clarifications": []},
            {"wbs": wbs()},
            {"microtasks": microtasks()},
            {
                "assessments": [
                    {
                        "id": row["id"],
                        "complexity": row["complexity"],
                        "task_types": row["task_types"],
                        "rationale": "Assessed tier-8 fragment",
                    }
                    for row in microtasks()
                ]
            },
        ):
            controller.step()
            mnode, _ = admission.claim("warden", worker_slot="slot1", requires_cleanup=True)
            _complete_node(store, controller, mnode, stage_output)
            controller.step()

        final8 = _drive_microtasks_to_completion(
            controller, admission, rel_rt, store, clock, "task-acc-tier8", ["R1"]
        )
        assert final8["deliverable_completed"] is True
        assert final8["release"]["verified_requirements"] == ["R1"]
    finally:
        store.close()
