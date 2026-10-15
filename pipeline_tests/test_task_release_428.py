"""Tests for `P428-14`: Assembly, final testing and truthful root completion (`task_release_428.py`)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cochem_pipeline.planning_runtime import PlanningController
from cochem_pipeline.task_release_428 import TaskReleaseRuntime
from pipeline_tests.test_microtask_board_428 import (
    _advance_task_to_reassessed_ready,
    _complete_claimed_job_for_node,
    _make_store_and_journal,
    _sha256_text,
)
from pipeline_tests.test_planning_gateway_428 import accepted_receipt


def _claim_and_complete_all_ready(store, board, task_id: str) -> dict:
    snap = board.materialize(task_id)
    pending_nodes = [n for n in snap["nodes"] if n["status"] == "DISPATCHED" and n["job_id"]]
    by_jid = {n["job_id"]: n for n in pending_nodes}
    for idx, _ in enumerate(pending_nodes, start=1):
        claimed = store.claim(
            f"worker-{idx}",
            worker_slot=f"slot{(idx - 1) % 4 + 1}",
            max_workers=4,
            allowed_kinds=["TASK_PLAN"],
            requires_cleanup=True,
        )
        assert claimed is not None
        _complete_claimed_job_for_node(store, claimed, by_jid[claimed["job_id"]])
    return board.materialize(task_id)


def test_unfinished_or_failed_assembly_prevents_parent_completion(tmp_path: Path) -> None:
    store, journal, broker = _make_store_and_journal(tmp_path)
    _advance_task_to_reassessed_ready(journal, task_id="task428-rel-unfinished")
    release_rt = TaskReleaseRuntime(journal, store, owner_broker=broker)
    controller = PlanningController(journal, store, release_runtime=release_rt)

    # Poll 1: mt-1 and mt-2 are dispatched; parent task is not completed
    controller.step()
    st1 = controller.task_status("task428-rel-unfinished")
    assert st1["deliverable_completed"] is False
    assert st1["controller"]["status"] == "WAITING_FOR_MICROTASK_BOARD"

    # Complete mt-1 and mt-2 -> mt-3 (assembly) is dispatched
    snap = _claim_and_complete_all_ready(store, release_rt.board, "task428-rel-unfinished")
    by_id = {n["microtask_id"]: n for n in snap["nodes"]}
    assert by_id["mt-3"]["status"] == "DISPATCHED"

    # Fail mt-3 (assembly) permanently on the board -> parent holds in MICROTASK_JOB_HELD
    asm_jid = by_id["mt-3"]["job_id"]
    with store._write() as conn:
        conn.execute("UPDATE pipeline_jobs SET status='FAILED' WHERE job_id=?", (asm_jid,))
    res = release_rt.step_microtask_task("task428-rel-unfinished")
    assert res["status"] == "MICROTASK_JOB_HELD"
    assert res["blocking_microtask_id"] == "mt-3"
    assert controller.task_status("task428-rel-unfinished")["deliverable_completed"] is False


def test_model_assertions_alone_cannot_close_task_and_interrupted_or_failed_tests_hold(
    tmp_path: Path,
) -> None:
    store, journal, broker = _make_store_and_journal(tmp_path)
    _advance_task_to_reassessed_ready(journal, task_id="task428-rel-gates")
    release_rt = TaskReleaseRuntime(journal, store, owner_broker=broker)
    controller = PlanningController(journal, store, release_runtime=release_rt)

    # Complete mt-1 & mt-2, then mt-3 (assembly), then mt-4 (final_test)
    _claim_and_complete_all_ready(store, release_rt.board, "task428-rel-gates")
    _claim_and_complete_all_ready(store, release_rt.board, "task428-rel-gates")
    snap = _claim_and_complete_all_ready(store, release_rt.board, "task428-rel-gates")
    assert snap["all_completed"] is True

    # Even though all 4 microtask board jobs completed with model JSON claiming passed=True,
    # no controller test execution receipt exists yet!
    res_no_rcpt = release_rt.step_microtask_task("task428-rel-gates")
    assert res_no_rcpt["status"] == "WAITING_FOR_CONTROLLER_TEST_VERIFICATION"
    assert controller.task_status("task428-rel-gates")["deliverable_completed"] is False

    # Interrupted final test (or cleanup_verified=False) holds and refuses completion
    release_rt.record_controller_test_receipt(
        "task428-rel-gates",
        "mt-4",
        passed=True,
        exit_code=0,
        cleanup_verified=False,
        status="INTERRUPTED",
        verified_requirements=["req-1", "req-2", "req-3"],
        summary="Container test interrupted before cleanup",
    )
    res_interrupted = release_rt.step_microtask_task("task428-rel-gates")
    assert res_interrupted["status"] == "FINAL_TEST_INTERRUPTED_CLEANUP_PENDING"
    assert controller.task_status("task428-rel-gates")["deliverable_completed"] is False

    # Failed final test (passed=False, exit_code=1) holds in FINAL_TEST_FAILED
    release_rt.record_controller_test_receipt(
        "task428-rel-gates",
        "mt-4",
        passed=False,
        exit_code=1,
        cleanup_verified=True,
        status="FAILED",
        verified_requirements=["req-1", "req-2", "req-3"],
        summary="1 integration test failed",
    )
    res_failed = release_rt.step_microtask_task("task428-rel-gates")
    assert res_failed["status"] == "FINAL_TEST_FAILED"
    assert controller.task_status("task428-rel-gates")["deliverable_completed"] is False

    # Passing test that omits req-3 holds in MISSING_REQUIREMENT_OR_TEST_COVERAGE
    release_rt.record_controller_test_receipt(
        "task428-rel-gates",
        "mt-4",
        passed=True,
        exit_code=0,
        cleanup_verified=True,
        status="COMPLETED",
        verified_requirements=["req-1", "req-2"],
        summary="Partial requirement verification",
    )
    res_partial = release_rt.step_microtask_task("task428-rel-gates")
    assert res_partial["status"] == "MISSING_REQUIREMENT_OR_TEST_COVERAGE"
    assert controller.task_status("task428-rel-gates")["deliverable_completed"] is False

    # Full controller-verified test receipt closes the task and retains independent plan review evidence
    release_rt.record_controller_test_receipt(
        "task428-rel-gates",
        "mt-4",
        passed=True,
        exit_code=0,
        cleanup_verified=True,
        status="COMPLETED",
        verified_requirements=["req-1", "req-2", "req-3"],
        summary="All 3 SRS requirements verified by controller test suite",
    )
    res_ok = release_rt.step_microtask_task("task428-rel-gates")
    assert res_ok["status"] == "EXECUTION_COMPLETED"

    final_status = controller.task_status("task428-rel-gates")
    assert final_status["deliverable_completed"] is True
    assert final_status["task"]["stage"] == "COMPLETED"
    rel_manifest = final_status["release"]
    assert rel_manifest is not None
    assert rel_manifest["independent_plan_review"]["model"] == "claude-opus-5-5"
    assert rel_manifest["independent_plan_review"]["tier"] == 9
    assert rel_manifest["verified_requirements"] == ["req-1", "req-2", "req-3"]


def test_fragment_revision_invalidates_stale_assembly_and_test_evidence(tmp_path: Path) -> None:
    store, journal, broker = _make_store_and_journal(tmp_path)
    _advance_task_to_reassessed_ready(journal, task_id="task428-rel-stale")
    release_rt = TaskReleaseRuntime(journal, store, owner_broker=broker)

    # Complete mt-1 & mt-2, then mt-3 (assembly), then mt-4 (final_test)
    _claim_and_complete_all_ready(store, release_rt.board, "task428-rel-stale")
    _claim_and_complete_all_ready(store, release_rt.board, "task428-rel-stale")
    snap_before = _claim_and_complete_all_ready(store, release_rt.board, "task428-rel-stale")
    assert snap_before["all_completed"] is True
    old_by_id = {n["microtask_id"]: n for n in snap_before["nodes"]}

    # Record a passing controller test receipt for the initial assembly + final_test
    release_rt.record_controller_test_receipt(
        "task428-rel-stale",
        "mt-4",
        passed=True,
        exit_code=0,
        cleanup_verified=True,
        status="COMPLETED",
        verified_requirements=["req-1", "req-2", "req-3"],
    )

    # Now simulate revising fragment mt-1's output (new deliverable content & new artifact_sha256)
    revised_out = dict(old_by_id["mt-1"]["output"])
    revised_text = "Completed mt-1 (revised v2)"
    revised_sha = _sha256_text(revised_text)
    revised_out["artifact_text"] = revised_text
    revised_out["artifact_sha256"] = revised_sha
    with journal._write() as conn:
        conn.execute(
            "UPDATE microtask428_nodes SET output_json=?, artifact_sha256=? WHERE task_id=? AND microtask_id='mt-1'",
            (json.dumps(revised_out, sort_keys=True), revised_sha, "task428-rel-stale"),
        )

    # Retry/restart must NOT reuse the stale mt-3 assembly or mt-4 final_test evidence!
    restarted_release_rt = TaskReleaseRuntime(journal, store, owner_broker=broker)
    check_after_revision = restarted_release_rt.verify_release_readiness("task428-rel-stale")
    assert check_after_revision["ready"] is False
    assert check_after_revision["status"] == "WAITING_FOR_MICROTASK_BOARD"

    snap_after = restarted_release_rt.board.board_status("task428-rel-stale")
    after_by_id = {n["microtask_id"]: n for n in snap_after["nodes"]}
    # mt-3 (assembly) was re-dispatched with a new job_id bound to mt-1's new artifact_sha256,
    # and mt-4 (final_test) returned to WAITING_ON_DEPENDENCIES!
    assert after_by_id["mt-1"]["status"] == "COMPLETED"
    assert after_by_id["mt-3"]["status"] == "DISPATCHED"
    assert after_by_id["mt-3"]["job_id"] != old_by_id["mt-3"]["job_id"]
    assert after_by_id["mt-4"]["status"] == "WAITING_ON_DEPENDENCIES"


@pytest.mark.parametrize('original_present', [False, True])
def test_inner_fracture_final_proof_cannot_replace_original_release_scope(tmp_path, monkeypatch, original_present):
    from copy import deepcopy
    store, journal, broker = _make_store_and_journal(tmp_path)
    task_id = 'task428-inner-final'
    _advance_task_to_reassessed_ready(journal, task_id=task_id)
    release = TaskReleaseRuntime(journal, store, owner_broker=broker)
    for _ in range(3):
        snap = _claim_and_complete_all_ready(store, release.board, task_id)
    assert snap['all_completed']
    original = next(n for n in snap['nodes'] if n['role'] == 'final_test')
    inner = deepcopy(original)
    inner.update(microtask_id='fracture-inner-final', lineage_kind='FAILURE_FRACTURE')
    snap['nodes'].append(inner)
    if not original_present:
        snap['nodes'] = [n for n in snap['nodes'] if n['microtask_id'] != original['microtask_id']]
    monkeypatch.setattr(release.board, 'materialize', lambda _: deepcopy(snap))
    monkeypatch.setattr(release.board, 'board_status', lambda _: deepcopy(snap))
    # An inner scope has a successful controller test receipt; it is not the
    # original final scope authorized by the durable SRS microtask plan.
    for final in ([inner, original] if original_present else [inner]):
        release.record_controller_test_receipt(task_id, final['microtask_id'], passed=True,
            exit_code=0, cleanup_verified=True, verified_requirements=['req-1', 'req-2', 'req-3'])
    if original_present:
        # No inner final receipt should be needed for parent publication. Its
        # internal proof is independently checked by the fracture join.
        with journal._write() as conn:
            conn.execute('DELETE FROM task428_test_receipts WHERE microtask_id=?', (inner['microtask_id'],))
    result = release.verify_release_readiness(task_id)
    assert result['ready'] is original_present
    if original_present:
        assert [r['microtask_id'] for r in result['release_manifest']['controller_test_receipts']] == [original['microtask_id']]
    else:
        assert result['status'] == 'MISSING_ORIGINAL_FINAL_SCOPE'
