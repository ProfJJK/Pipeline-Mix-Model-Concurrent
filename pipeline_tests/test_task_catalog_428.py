"""Tests for 4.2.8 task-catalog binding to protected live catalog authority (`P428-03`)."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import pytest

from cochem_pipeline.catalog_activation import compile_task_catalog_change
from cochem_pipeline.catalog_journal import (
    active_policy,
    active_task_catalog,
    initialize,
    initialize_task_catalog,
    publish_task_catalog,
)
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.store import JobStore
from cochem_pipeline.task_catalog_428 import (
    active_accepted_target_set,
    activate_task_catalog,
    check_task_target_admission,
    classify_target_status,
    compile_task_catalog_plan,
)
from cochem_pipeline.task_routing import compile_matrix, with_five_model_rows


ROOT = Path(__file__).resolve().parents[1] / "docs" / "4.2.8"


@pytest.fixture(scope="module")
def raw_task_catalog():
    owner = json.loads((ROOT / "references" / "owner-model-matrix.json").read_text(encoding="utf-8-sig"))
    obs = json.loads((ROOT / "benchmark-observations.json").read_text(encoding="utf-8"))
    return with_five_model_rows(compile_matrix(owner, obs))


@pytest.fixture
def binary_bindings():
    return {
        "codex": {
            "executable": r"C:\Program Files\CoChem\cli\codex.exe",
            "sha256": "1" * 64,
            "version": "codex-cli 0.42.0",
        },
        "claude": {
            "executable": r"C:\Program Files\CoChem\cli\claude.exe",
            "sha256": "2" * 64,
            "version": "claude-code 1.2.8",
        },
        "gemini": {
            "executable": r"C:\Program Files\CoChem\cli\agy.exe",
            "sha256": "3" * 64,
            "version": "agy 0.19.4",
        },
    }


def _make_receipts(plan, request_id: str) -> list[dict]:
    targets = sorted(set(plan.required_targets) | {plan.control_target})
    receipts = []
    for idx, (provider, model, effort) in enumerate(targets, start=1):
        receipts.append({
            "provider": provider,
            "model": model,
            "reasoning_effort": effort,
            "binary_sha256": plan.binary_bindings[provider]["sha256"],
            "status": "NATIVE_SELECTOR_ACCEPTED",
            "cleanup_verified": True,
            "plan_digest": plan.digest,
            "request_id": request_id,
            "reservation_id": f"res-{idx:04d}",
            "fencing_token": idx,
        })
    return receipts


def _open_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=FULL")
    return conn


def test_new_task_matrix_targets_admitted_and_unaccepted_or_missing_score_targets_rejected(
    tmp_path, raw_task_catalog, binary_bindings
):
    baseline = load_routing_policy({"policy_version": 3})
    for missing_pid in ("argon-low", "argon-med", "flash38-low"):
        with pytest.raises(ValueError, match="lacks complete verified publisher benchmark scores"):
            compile_task_catalog_plan(
                baseline,
                raw_task_catalog,
                binary_bindings,
                expected_policy_digest=baseline.digest,
                candidate_profile_ids=[missing_pid],
            )

    selected = ["argon-high", "sonnet-max", "opus-max", "sol-max", "luna-med"]
    plan = compile_task_catalog_change(
        baseline,
        raw_task_catalog,
        binary_bindings,
        expected_policy_digest=baseline.digest,
        candidate_profile_ids=selected,
    )
    req_id = "a" * 32
    receipts = _make_receipts(plan, req_id)
    activated, proofs = activate_task_catalog(
        plan,
        receipts,
        request_id=req_id,
        pointer_sha256="b" * 64,
        proposal_sha256="c" * 64,
    )
    assert activated["host_accepted"] is True
    assert set(activated["accepted_profile_ids"]) == set(selected)
    assert proofs

    accepted_set = active_accepted_target_set(baseline, activated)
    assert ("gemini", "gemini-4-argon", "high") in accepted_set
    assert ("claude", "claude-sonnet-5-5", "max") in accepted_set
    assert ("gemini", "gemini-4-argon", "low") not in accepted_set
    assert ("claude", "claude-fable-5-1", "max") not in accepted_set

    assert classify_target_status(
        {"provider": "gemini", "model": "gemini-4-argon", "reasoning_effort": "high"},
        baseline,
        activated,
    ) is None
    assert classify_target_status(
        {"provider": "claude", "model": "claude-fable-5-1", "reasoning_effort": "max"},
        baseline,
        activated,
    ) == "unaccepted_target"
    assert classify_target_status(
        {"provider": "gemini", "model": "gemini-4-argon", "reasoning_effort": "low"},
        baseline,
        activated,
    ) == "unaccepted_target"
    assert classify_target_status(
        {"provider": "gemini", "model": "gemini-3.1-pro", "reasoning_effort": "high"},
        baseline,
        activated,
    ) == "retired_target"


def test_receipt_binding_rejects_wrong_binary_hash_uncleaned_or_mismatched_plan(
    raw_task_catalog, binary_bindings
):
    baseline = load_routing_policy({"policy_version": 3})
    plan = compile_task_catalog_plan(
        baseline,
        raw_task_catalog,
        binary_bindings,
        expected_policy_digest=baseline.digest,
        candidate_profile_ids=["argon-high", "opus-max"],
    )
    req_id = "1" * 32
    base_receipts = _make_receipts(plan, req_id)

    bad_bin = deepcopy(base_receipts)
    bad_bin[0]["binary_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="binary_sha256"):
        activate_task_catalog(
            plan, bad_bin, request_id=req_id, pointer_sha256="2" * 64, proposal_sha256="3" * 64
        )

    bad_clean = deepcopy(base_receipts)
    bad_clean[0]["cleanup_verified"] = False
    with pytest.raises(ValueError, match="cleanup"):
        activate_task_catalog(
            plan, bad_clean, request_id=req_id, pointer_sha256="2" * 64, proposal_sha256="3" * 64
        )

    bad_plan = deepcopy(base_receipts)
    bad_plan[0]["plan_digest"] = "9" * 64
    with pytest.raises(ValueError, match="binding differs"):
        activate_task_catalog(
            plan, bad_plan, request_id=req_id, pointer_sha256="2" * 64, proposal_sha256="3" * 64
        )


def test_atomic_publication_retirement_replay_and_preserved_old_jobs_across_restart(
    tmp_path, raw_task_catalog, binary_bindings
):
    db_path = tmp_path / "board.db"
    raw_policy = load_routing_policy({"policy_version": 3}).as_dict()
    first_key = (
        f"{raw_policy['tiers']['1'][0]['provider']}:"
        f"{raw_policy['tiers']['1'][0]['model']}:"
        f"{raw_policy['tiers']['1'][0]['reasoning_effort']}"
    )
    raw_policy["model_limits"][first_key] = 2
    baseline = load_routing_policy(raw_policy)

    store = JobStore(db_path, routing_policy=baseline)
    store.submit("Existing workflow before catalog activation", ["REQ-OLD"], 1, workflow_id="wf-old")
    store.close()

    with _open_conn(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        initialize(conn, baseline)
        conn.commit()

    store = JobStore(db_path, routing_policy=baseline, catalog_enabled=True)
    with store._connection() as conn:
        old_capture = json.loads(
            conn.execute(
                "SELECT policy_json FROM pipeline_routing_workflows WHERE workflow_id='wf-old'"
            ).fetchone()[0]
        )

    plan1 = compile_task_catalog_plan(
        baseline,
        raw_task_catalog,
        binary_bindings,
        expected_policy_digest=baseline.digest,
        candidate_profile_ids=["argon-high", "sonnet-max", "opus-max"],
        model_limits={"gemini:gemini-4-argon:high": 1},
    )
    assert plan1.model_limits[first_key] == 2
    assert plan1.model_limits["gemini:gemini-4-argon:high"] == 1

    req1 = "a" * 32
    receipts1 = _make_receipts(plan1, req1)
    with store._write() as conn:
        pub1 = publish_task_catalog(
            conn,
            plan1,
            receipts1,
            request_id=req1,
            pointer_sha256="b" * 64,
            proposal_sha256="c" * 64,
        )
        assert pub1["status"] == "PUBLISHED_IN_CALLER_TRANSACTION"
        active1 = active_task_catalog(conn)
        assert active1["host_accepted"] is True

    # Replay of the exact request is idempotent; altered evidence is rejected.
    with store._write() as conn:
        replay = publish_task_catalog(
            conn,
            plan1,
            receipts1,
            request_id=req1,
            pointer_sha256="b" * 64,
            proposal_sha256="c" * 64,
        )
        assert replay["status"] == "ALREADY_PUBLISHED"
        with pytest.raises(ValueError, match="reused with different evidence"):
            publish_task_catalog(
                conn,
                plan1,
                receipts1,
                request_id=req1,
                pointer_sha256="d" * 64,
                proposal_sha256="c" * 64,
            )

    # Second generation retires sonnet-max from accepted task profiles.
    next_raw_catalog = deepcopy(raw_task_catalog)
    next_raw_catalog["generation"] = "4.2.8-five-options-20261013-v2"
    plan2 = compile_task_catalog_plan(
        baseline,
        next_raw_catalog,
        binary_bindings,
        expected_policy_digest=baseline.digest,
        previous_task_catalog=active1,
        candidate_profile_ids=["argon-high", "opus-max"],
        retired_profile_ids=["sonnet-max"],
        model_limits={"gemini:gemini-4-argon:high": 1},
    )
    req2 = "e" * 32
    receipts2 = _make_receipts(plan2, req2)
    with store._write() as conn:
        pub2 = publish_task_catalog(
            conn,
            plan2,
            receipts2,
            request_id=req2,
            pointer_sha256="f" * 64,
            proposal_sha256="0" * 64,
        )
        assert pub2["status"] == "PUBLISHED_IN_CALLER_TRANSACTION"
        active2 = active_task_catalog(conn)
        assert classify_target_status(
            {"provider": "claude", "model": "claude-sonnet-5-5", "reasoning_effort": "max"},
            baseline,
            active2,
        ) == "retired_target"
        assert classify_target_status(
            {"provider": "gemini", "model": "gemini-4-argon", "reasoning_effort": "high"},
            baseline,
            active2,
        ) is None

    # Stale plan referencing active1 cannot rebase over active2.
    stale_plan = compile_task_catalog_plan(
        baseline,
        next_raw_catalog,
        binary_bindings,
        expected_policy_digest=baseline.digest,
        previous_task_catalog=active1,
        candidate_profile_ids=["argon-high"],
    )
    with pytest.raises(ValueError, match="no implicit rebase"):
        with store._write() as conn:
            publish_task_catalog(
                conn,
                stale_plan,
                _make_receipts(stale_plan, "9" * 32),
                request_id="9" * 32,
                pointer_sha256="1" * 64,
                proposal_sha256="2" * 64,
            )

    store.close()

    # Reopen store and verify old job capture and active task catalog survive restart.
    reopened = JobStore(db_path, routing_policy=baseline, catalog_enabled=True)
    with reopened._connection() as conn:
        reopened_active = active_task_catalog(conn)
        assert reopened_active == active2
        preserved_capture = json.loads(
            conn.execute(
                "SELECT policy_json FROM pipeline_routing_workflows WHERE workflow_id='wf-old'"
            ).fetchone()[0]
        )
        assert preserved_capture == old_capture
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM pipeline_task_catalog_generations")

    # Verify check_task_target_admission enforces new target admission, model_limits, and retirement.
    node = reopened.claim("worker-slot-1", requires_cleanup=False, allowed_kinds=("MANIFEST_GENERATOR",))
    with reopened._write() as conn:
        job = reopened._get(conn, node["job_id"])
        state = job["routing"]
        argon_target = {
            "key": "gemini:gemini-4-argon:high",
            "provider": "gemini",
            "model": "gemini-4-argon",
            "reasoning_effort": "high",
            "quota_pool": "gemini",
        }
        assert check_task_target_admission(
            conn, job, state, argon_target, baseline, task_catalog=reopened_active
        ) is None

        sonnet_target = {
            "key": "claude:claude-sonnet-5-5:max",
            "provider": "claude",
            "model": "claude-sonnet-5-5",
            "reasoning_effort": "max",
            "quota_pool": "claude",
        }
        assert check_task_target_admission(
            conn, job, state, sonnet_target, baseline, task_catalog=reopened_active
        ) == "retired_target"

        # Occupy the 1-slot cap for gemini:gemini-4-argon:high and verify admission reports busy.
        from cochem_pipeline import routing_store as routes
        routes.release(conn, job["job_id"], "test_rebind")
        conn.execute(
            "UPDATE pipeline_jobs SET attempt_id='attempt-argon-1', fencing_token=fencing_token+1 WHERE job_id=?",
            (job["job_id"],),
        )
        job = reopened._get(conn, node["job_id"])
        routes.reserve(
            conn,
            job,
            {**argon_target, "candidate_index": 0, "cycle": 0},
            "slot1",
        )
        assert check_task_target_admission(
            conn, job, state, argon_target, baseline, task_catalog=reopened_active
        ) == "busy"
    reopened.close()
