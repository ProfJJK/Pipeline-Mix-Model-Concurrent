"""Tests for `P428-21`: Isolated direct repository repair execution (`repair_executor_428.py`, `repair_queue_428.py`)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cochem_pipeline.task_routing import digest
from cochem_supervisor.repair_admission_428 import SupervisorRepairAdmission428
from cochem_supervisor.repair_executor_428 import IsolatedRepairExecutor428


ROOT = Path(__file__).resolve().parents[1]


def _load_catalog() -> dict:
    return json.loads((ROOT / "docs" / "4.2.8" / "routing-candidate.json").read_text(encoding="utf-8"))


def test_wrong_profile_forbidden_path_and_dirty_owner_worktree_rejected(tmp_path: Path) -> None:
    catalog = _load_catalog()
    owner_repo = tmp_path / "owner_repo"
    owner_repo.mkdir()
    dirty_marker = owner_repo / "UNCOMMITTED_OWNER_EDIT.txt"
    dirty_marker.write_text("do not touch", encoding="utf-8")
    worktrees_root = tmp_path / "isolated_worktrees"

    sup = SupervisorRepairAdmission428(
        tmp_path / "sup_exec1.sqlite",
        catalog,
        accepted_native_models={"astra-max", "opus-max", "argon-high"},
    )
    executor = IsolatedRepairExecutor428(
        sup,
        owner_repo_path=owner_repo,
        isolated_worktrees_root=worktrees_root,
    )

    sup.repair_queue.report(
        "inc-guard-1",
        "Controller invariant failure",
        digest("ev-guard-1"),
        source_kind="invariant_failure",
        task_types=["GEN-DEFAULT"],
    )
    admitted = sup.admit_next_repair("sup-1", incident_id="inc-guard-1")

    # 1. Wrong profile (normal worker profile) is rejected
    bad_profile_adm = {**admitted, "profile_id": "slot1"}
    with pytest.raises(ValueError, match="dedicated repair identity"):
        executor.execute_isolated_repair(
            bad_profile_adm,
            proposed_files={"src/cochem_pipeline/fix.py": "x = 1\n"},
            test_result={"passed": True, "evidence_sha256": digest("t1")},
            git_result={"ok": True, "commit_sha": "a" * 40, "working_tree_clean": True},
        )

    # 2. Executing directly inside the owner's repository worktree (or a dirty owner worktree) is rejected!
    with pytest.raises(ValueError, match="owner_repo_path"):
        executor.execute_isolated_repair(
            admitted,
            target_worktree_path=owner_repo,
            owner_worktree_dirty=True,
            proposed_files={"src/cochem_pipeline/fix.py": "x = 1\n"},
            test_result={"passed": True, "evidence_sha256": digest("t1")},
            git_result={"ok": True, "commit_sha": "a" * 40, "working_tree_clean": True},
        )
    assert dirty_marker.read_text(encoding="utf-8") == "do not touch"

    # 3. Forbidden paths (AGENTS.md, credentials, .claude, outside scope) are rejected before writing
    for bad_path in (
        "AGENTS.md",
        "src/cochem_pipeline/credentials/token.json",
        ".claude/settings.json",
        "../outside.py",
    ):
        with pytest.raises(ValueError):
            executor.execute_isolated_repair(
                admitted,
                proposed_files={bad_path: "forbidden\n"},
                test_result={"passed": True, "evidence_sha256": digest("t1")},
                git_result={"ok": True, "commit_sha": "a" * 40, "working_tree_clean": True},
            )


def test_test_failure_git_failure_crash_restart_and_reviewed_supervisor_transition(tmp_path: Path) -> None:
    catalog = _load_catalog()
    owner_repo = tmp_path / "owner_repo"
    owner_repo.mkdir()
    worktrees_root = tmp_path / "isolated_worktrees"
    sup_db = tmp_path / "sup_exec2.sqlite"
    accepted = {"astra-max", "opus-max", "argon-high"}

    sup = SupervisorRepairAdmission428(sup_db, catalog, accepted_native_models=accepted)
    executor = IsolatedRepairExecutor428(
        sup,
        owner_repo_path=owner_repo,
        isolated_worktrees_root=worktrees_root,
    )

    sup.repair_queue.report(
        "inc-flow-1",
        "Native cleanup fault in worker release",
        digest("ev-flow-1"),
        source_kind="native_fault",
        task_types=["GEN-DEFAULT"],
    )

    # 1. Attempt 1: Code change with test failure -> preserves isolated branch and returns incident to QUEUED
    adm1 = sup.admit_next_repair("sup-1", incident_id="inc-flow-1")
    fail_test_res = executor.execute_isolated_repair(
        adm1,
        proposed_files={
            "src/cochem_pipeline/worker_fix.py": "def fix():\n    return False\n",
            "pipeline_tests/test_worker_fix.py": "def test_fix():\n    assert False\n",
        },
        test_result={"passed": False, "summary": "1 failed in test_worker_fix.py", "evidence_sha256": digest("tf-1")},
        git_result={"ok": True, "commit_sha": "1" * 40, "working_tree_clean": True},
    )
    assert fail_test_res["status"] == "TESTS_FAILED_BRANCH_PRESERVED"
    assert fail_test_res["branch_preserved"] is True
    assert (Path(fail_test_res["worktree_path"]) / "src/cochem_pipeline/worker_fix.py").is_file()
    assert fail_test_res["incident_state"] == "QUEUED"

    # 2. Attempt 2: Tests pass, but Git commit fails -> preserves isolated branch and returns incident to QUEUED
    adm2 = sup.admit_next_repair("sup-1", incident_id="inc-flow-1")
    fail_git_res = executor.execute_isolated_repair(
        adm2,
        proposed_files={"src/cochem_pipeline/worker_fix.py": "def fix():\n    return True\n"},
        test_result={"passed": True, "evidence_sha256": digest("tp-2")},
        git_result={"ok": False, "error": "index.lock contention", "commit_sha": None},
    )
    assert fail_git_res["status"] == "GIT_FAILED_BRANCH_PRESERVED"
    assert fail_git_res["branch_preserved"] is True
    assert fail_git_res["incident_state"] == "QUEUED"

    # 3. Attempt 3: Crash mid-execution before commit -> restart recovers branch, history, and incident
    adm3 = sup.admit_next_repair("sup-1", incident_id="inc-flow-1")
    with pytest.raises(RuntimeError, match="Simulated crash"):
        executor.execute_isolated_repair(
            adm3,
            proposed_files={"src/cochem_pipeline/worker_fix.py": "def fix():\n    return True\n"},
            test_result={"passed": True, "evidence_sha256": digest("tp-3")},
            git_result={"ok": True, "commit_sha": "3" * 40, "working_tree_clean": True},
            simulate_crash_before_commit=True,
        )

    restarted_sup = SupervisorRepairAdmission428(sup_db, catalog, accepted_native_models=accepted)
    restarted_exec = IsolatedRepairExecutor428(
        restarted_sup,
        owner_repo_path=owner_repo,
        isolated_worktrees_root=worktrees_root,
    )
    recovered = restarted_exec.recover_interrupted_attempts(
        cleanup_verified=True,
        cleanup_receipt_sha256=digest("crash-cleanup-3"),
    )
    assert len(recovered) == 1
    assert recovered[0]["branch_preserved"] is True
    assert recovered[0]["incident_state"] == "QUEUED"
    assert len(restarted_exec.list_execution_attempts("inc-flow-1")) == 3

    # 4. Attempt 4: Valid isolated repair -> commits source changes -> state is SOURCE_REPAIRED (NOT RESOLVED!)
    adm4 = restarted_sup.admit_next_repair("sup-restarted", incident_id="inc-flow-1")
    commit_sha = "c0ffee" + "4" * 34
    repaired_res = restarted_exec.execute_isolated_repair(
        adm4,
        proposed_files={
            "src/cochem_pipeline/worker_fix.py": "def fix():\n    return True\n",
            "pipeline_tests/test_worker_fix.py": "def test_fix():\n    assert True\n",
        },
        test_result={"passed": True, "evidence_sha256": digest("tp-4")},
        git_result={"ok": True, "commit_sha": commit_sha, "working_tree_clean": True},
    )
    assert repaired_res["status"] == "SOURCE_REPAIRED"
    assert repaired_res["deployment_performed"] is False
    assert repaired_res["incident_state"] == "SOURCE_REPAIRED"

    # 5. Absent supervisor authority holds explicitly in AWAITING_SUPERVISOR_TRANSITION (never elevates repair agent!)
    held_trans = restarted_exec.transition_repaired_incident_to_runtime(
        "inc-flow-1",
        supervisor_authority_verified=False,
    )
    assert held_trans["state"] == "AWAITING_SUPERVISOR_TRANSITION"
    assert held_trans["result"]["deployment_performed"] is False
    assert held_trans["result"]["supervisor_transition_status"] == "HELD_AWAITING_SUPERVISOR_AUTHORITY"

    # 6. Reviewed supervisor authority transitions the repaired incident to RESOLVED
    resolved_trans = restarted_exec.transition_repaired_incident_to_runtime(
        "inc-flow-1",
        supervisor_authority_verified=True,
        supervisor_receipt_id="sup-transition-rcpt-01",
        runtime_version_sha256=digest("runtime-4.2.8-repaired"),
        smoke_check_sha256=digest("smoke-pass-01"),
    )
    assert resolved_trans["state"] == "RESOLVED"
    assert resolved_trans["result"]["deployment_performed"] is True
    assert resolved_trans["result"]["supervisor_receipt_id"] == "sup-transition-rcpt-01"
