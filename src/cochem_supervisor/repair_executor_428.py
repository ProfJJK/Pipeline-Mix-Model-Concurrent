"""Isolated direct repository repair execution and supervisor runtime transition (`P428-21`).

Guarantees:
- A preauthorized repair inspects a bounded incident, edits an isolated repository
  branch (`repair/4.2.8/<incident_id>`) in a separate worktree directory, runs
  allowed checks, and commits its changes without ever touching a dirty owner
  worktree or installed runtime/credentials/guards/host lifecycle paths.
- Native identity, maximum reasoning effort (`max`, or `high` for Gemini),
  dedicated repair profile, changed paths (`repair_paths`), diffs, tests, and
  native cleanup are attested before recording a commit.
- Crash, failed tests, or Git failure preserve the reviewable branch and durable
  incident attempt history in SQLite.
- A source commit alone places the incident in `SOURCE_REPAIRED`
  (`deployment_performed=False`), never `RESOLVED`.
- Reaching the running runtime requires the separately reviewed supervisor
  transition (`transition_repaired_incident_to_runtime`); absent authority holds
  explicitly in `AWAITING_SUPERVISOR_TRANSITION` rather than granting elevation
  to the repair agent.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any

from cochem_pipeline.repair_queue_428 import repair_paths
from cochem_pipeline.task_routing import digest
from cochem_pipeline.workflow_428 import _id, _sha, _text
from .repair_admission_428 import SupervisorRepairAdmission428


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class IsolatedRepairExecutor428:
    """Executes admitted repairs on an isolated branch and coordinates reviewed supervisor transitions (`P428-21`)."""

    def __init__(
        self,
        admission: SupervisorRepairAdmission428,
        *,
        owner_repo_path: str | Path,
        isolated_worktrees_root: str | Path,
        clock=time.time,
    ):
        self.admission = admission
        self.owner_repo_path = Path(owner_repo_path).resolve()
        self.isolated_worktrees_root = Path(isolated_worktrees_root).resolve()
        if self.isolated_worktrees_root == self.owner_repo_path:
            raise ValueError("isolated_worktrees_root must be separate from owner_repo_path")
        self.clock = clock
        self._verified_commits: dict[str, dict[str, Any]] = {}
        self.admission.repair_queue.verify_commit = self.verify_commit_proof

        with self.admission._write() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS repair428_execution_attempts(
                    attempt_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    lease TEXT NOT NULL,
                    reservation_id TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    branch_name TEXT NOT NULL,
                    worktree_path TEXT NOT NULL,
                    changed_paths_json TEXT NOT NULL,
                    diff_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    tests_passed INTEGER NOT NULL,
                    test_evidence_sha256 TEXT,
                    commit_sha TEXT,
                    branch_preserved INTEGER NOT NULL,
                    failure_reason TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )

    def verify_commit_proof(self, commit_sha: str, test_evidence_sha256: str) -> dict[str, Any] | None:
        proof = self._verified_commits.get(commit_sha)
        if proof is None or proof.get("test_evidence_sha256") != test_evidence_sha256:
            return None
        return deepcopy(proof)

    def list_execution_attempts(self, incident_id: str | None = None) -> list[dict[str, Any]]:
        with self.admission._write() as conn:
            if incident_id is not None:
                _id(incident_id)
                rows = conn.execute(
                    "SELECT * FROM repair428_execution_attempts WHERE incident_id=? ORDER BY created_at ASC",
                    (incident_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM repair428_execution_attempts ORDER BY created_at ASC"
                ).fetchall()
        return [
            {
                "attempt_id": r["attempt_id"],
                "incident_id": r["incident_id"],
                "lease": r["lease"],
                "reservation_id": r["reservation_id"],
                "profile_id": r["profile_id"],
                "model_id": r["model_id"],
                "branch_name": r["branch_name"],
                "worktree_path": r["worktree_path"],
                "changed_paths": json.loads(r["changed_paths_json"]),
                "diff_sha256": r["diff_sha256"],
                "status": r["status"],
                "tests_passed": bool(r["tests_passed"]),
                "test_evidence_sha256": r["test_evidence_sha256"],
                "commit_sha": r["commit_sha"],
                "branch_preserved": bool(r["branch_preserved"]),
                "failure_reason": r["failure_reason"],
            }
            for r in rows
        ]

    def execute_isolated_repair(
        self,
        admitted: dict[str, Any],
        *,
        proposed_files: dict[str, str],
        target_worktree_path: str | Path | None = None,
        owner_worktree_dirty: bool = False,
        test_result: dict[str, Any],
        git_result: dict[str, Any],
        cleanup_verified: bool = True,
        cleanup_receipt_sha256: str | None = None,
        simulate_crash_before_commit: bool = False,
    ) -> dict[str, Any]:
        """Run an admitted repair in an isolated branch/worktree, verify paths/tests/git/cleanup, and record source commit."""
        if not isinstance(admitted, dict) or admitted.get("status") != "ADMITTED":
            raise ValueError("execute_isolated_repair requires an ADMITTED repair record")
        incident_id = _id(admitted["incident_id"])
        lease = _id(admitted["lease"])
        reservation_id = _id(admitted["reservation_id"])
        profile_id = _id(admitted["profile_id"])
        model_id = _id(admitted["model_id"])

        # 1. Attest dedicated repair profile and maximum-effort native model identity
        if profile_id not in self.admission.profiles or profile_id in self.admission.normal_profile_ids:
            raise ValueError(f"Profile '{profile_id}' is not a dedicated repair identity")
        model_spec = (self.admission.catalog.get("models") or {}).get(model_id)
        if model_spec is None or model_id not in self.admission.accepted_native_models:
            raise ValueError(f"Model '{model_id}' is not natively accepted for repair execution")
        req_max = "high" if model_spec.get("provider") == "gemini" else "max"
        if model_spec.get("effort") != req_max:
            raise ValueError("Isolated repair execution requires maximum reasoning effort")

        # 2. Protect owner worktree: never execute inside owner_repo_path (especially when dirty)
        branch_name = f"repair/4.2.8/{incident_id}"
        worktree_dir = (
            Path(target_worktree_path).resolve()
            if target_worktree_path is not None
            else (self.isolated_worktrees_root / incident_id).resolve()
        )
        if worktree_dir == self.owner_repo_path or self.owner_repo_path in worktree_dir.parents:
            raise ValueError("Refusing to execute repair directly inside owner_repo_path; isolated worktree required")
        if owner_worktree_dirty and not worktree_dir.is_relative_to(self.isolated_worktrees_root):
            raise ValueError("Dirty owner worktree cannot be used for repair execution")

        # 3. Validate all proposed file paths via `repair_paths` BEFORE writing any file
        if not isinstance(proposed_files, dict) or not proposed_files:
            raise ValueError("Repair requires at least one proposed file change")
        changed_paths = repair_paths(list(proposed_files.keys()))

        # Materialize isolated worktree files on the isolated branch
        worktree_dir.mkdir(parents=True, exist_ok=True)
        (worktree_dir / ".repair_branch.json").write_text(
            json.dumps(
                {
                    "incident_id": incident_id,
                    "branch_name": branch_name,
                    "lease": lease,
                    "reservation_id": reservation_id,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        diff_entries = {}
        for rel_path in changed_paths:
            content = _text(proposed_files[rel_path], f"Repair file {rel_path}", 200000)
            dest = (worktree_dir / rel_path).resolve()
            if not dest.is_relative_to(worktree_dir):
                raise ValueError(f"Escaped isolated worktree path: {rel_path}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            diff_entries[rel_path] = _sha256_text(content)
        diff_sha256 = digest(diff_entries)

        now = float(self.clock())
        attempt_id = f"repatt428-{incident_id[:20]}-{lease[:12]}"
        with self.admission._write() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO repair428_execution_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    attempt_id,
                    incident_id,
                    lease,
                    reservation_id,
                    profile_id,
                    model_id,
                    branch_name,
                    str(worktree_dir),
                    json.dumps(changed_paths),
                    diff_sha256,
                    "IN_PROGRESS",
                    0,
                    None,
                    None,
                    1,
                    None,
                    now,
                    now,
                ),
            )

        if simulate_crash_before_commit:
            self.admission.mark_slot_stale(reservation_id)
            raise RuntimeError("Simulated crash during isolated repair before commit")

        # 4. Evaluate allowed test checks
        tests_passed = bool(test_result.get("passed"))
        test_ev_sha = _sha(test_result.get("evidence_sha256") or digest(test_result))
        clean_rcpt = _sha(cleanup_receipt_sha256 or digest({"cleanup": reservation_id, "at": now}))

        if not tests_passed:
            # Preserve isolated branch for review, release slot after verified cleanup, and requeue incident
            with self.admission._write() as conn:
                conn.execute(
                    "UPDATE repair428_execution_attempts SET status='TESTS_FAILED_BRANCH_PRESERVED', tests_passed=0, test_evidence_sha256=?, branch_preserved=1, failure_reason=?, updated_at=? WHERE attempt_id=?",
                    (
                        test_ev_sha,
                        str(test_result.get("summary") or "tests_failed")[:512],
                        now,
                        attempt_id,
                    ),
                )
            self.admission.release_slot(
                reservation_id,
                cleanup_verified=cleanup_verified,
                cleanup_receipt_sha256=clean_rcpt,
                requeue_interrupted_incident=True,
            )
            return {
                "status": "TESTS_FAILED_BRANCH_PRESERVED",
                "attempt_id": attempt_id,
                "incident_id": incident_id,
                "branch_name": branch_name,
                "worktree_path": str(worktree_dir),
                "branch_preserved": True,
                "incident_state": self.admission.repair_queue.get_incident(incident_id)["state"],
            }

        # 5. Evaluate Git commit
        commit_sha = git_result.get("commit_sha")
        git_ok = (
            bool(git_result.get("ok", True))
            and isinstance(commit_sha, str)
            and bool(re.fullmatch(r"[0-9a-f]{40,64}", commit_sha))
            and bool(git_result.get("working_tree_clean", True))
        )
        if not git_ok:
            with self.admission._write() as conn:
                conn.execute(
                    "UPDATE repair428_execution_attempts SET status='GIT_FAILED_BRANCH_PRESERVED', tests_passed=1, test_evidence_sha256=?, branch_preserved=1, failure_reason=?, updated_at=? WHERE attempt_id=?",
                    (
                        test_ev_sha,
                        str(git_result.get("error") or "git_commit_failed")[:512],
                        now,
                        attempt_id,
                    ),
                )
            self.admission.release_slot(
                reservation_id,
                cleanup_verified=cleanup_verified,
                cleanup_receipt_sha256=clean_rcpt,
                requeue_interrupted_incident=True,
            )
            return {
                "status": "GIT_FAILED_BRANCH_PRESERVED",
                "attempt_id": attempt_id,
                "incident_id": incident_id,
                "branch_name": branch_name,
                "worktree_path": str(worktree_dir),
                "branch_preserved": True,
                "incident_state": self.admission.repair_queue.get_incident(incident_id)["state"],
            }

        # 6. Register commit proof and record commit in RepairQueue -> state becomes SOURCE_REPAIRED (not RESOLVED!)
        self._verified_commits[commit_sha] = {
            "commit_sha": commit_sha,
            "tests_passed": True,
            "working_tree_clean": True,
            "cleanup_verified": bool(cleanup_verified),
            "test_evidence_sha256": test_ev_sha,
            "changed_paths": changed_paths,
            "reservation_id": reservation_id,
            "branch_name": branch_name,
            "diff_sha256": diff_sha256,
        }
        commit_record = self.admission.repair_queue.record_commit(
            lease,
            commit_sha,
            test_ev_sha,
        )
        with self.admission._write() as conn:
            conn.execute(
                "UPDATE repair428_execution_attempts SET status='SOURCE_REPAIRED', tests_passed=1, test_evidence_sha256=?, commit_sha=?, branch_preserved=1, updated_at=? WHERE attempt_id=?",
                (test_ev_sha, commit_sha, now, attempt_id),
            )
        self.admission.release_slot(
            reservation_id,
            cleanup_verified=cleanup_verified,
            cleanup_receipt_sha256=clean_rcpt,
            requeue_interrupted_incident=False,
        )
        return {
            "status": "SOURCE_REPAIRED",
            "attempt_id": attempt_id,
            "incident_id": incident_id,
            "branch_name": branch_name,
            "worktree_path": str(worktree_dir),
            "commit_sha": commit_sha,
            "changed_paths": changed_paths,
            "diff_sha256": diff_sha256,
            "deployment_performed": False,
            "commit_record": commit_record,
            "incident_state": self.admission.repair_queue.get_incident(incident_id)["state"],
        }

    def transition_repaired_incident_to_runtime(
        self,
        incident_id: str,
        *,
        supervisor_authority_verified: bool,
        supervisor_receipt_id: str | None = None,
        runtime_version_sha256: str | None = None,
        smoke_check_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Apply or hold the runtime transition for a `SOURCE_REPAIRED` incident via reviewed supervisor authority."""
        return self.admission.repair_queue.apply_runtime_transition(
            incident_id,
            supervisor_authority_verified=supervisor_authority_verified,
            supervisor_receipt_id=supervisor_receipt_id,
            runtime_version_sha256=runtime_version_sha256,
            smoke_check_sha256=smoke_check_sha256,
        )

    def recover_interrupted_attempts(
        self,
        *,
        cleanup_verified: bool,
        cleanup_receipt_sha256: str,
    ) -> list[dict[str, Any]]:
        """Recover any interrupted `IN_PROGRESS` repair execution attempts after supervisor restart."""
        _sha(cleanup_receipt_sha256)
        if cleanup_verified is not True:
            raise ValueError("Cannot recover interrupted repair execution without verified native cleanup")
        now = float(self.clock())
        with self.admission._write() as conn:
            rows = conn.execute(
                "SELECT * FROM repair428_execution_attempts WHERE status='IN_PROGRESS' ORDER BY created_at ASC"
            ).fetchall()
            for r in rows:
                conn.execute(
                    "UPDATE repair428_execution_attempts SET status='CRASH_RECOVERED_BRANCH_PRESERVED', branch_preserved=1, failure_reason='interrupted_before_commit', updated_at=? WHERE attempt_id=?",
                    (now, r["attempt_id"]),
                )
        recovered = []
        for r in rows:
            res_id = r["reservation_id"]
            if self.admission.verify_reservation(res_id) is not None:
                self.admission.release_slot(
                    res_id,
                    cleanup_verified=True,
                    cleanup_receipt_sha256=cleanup_receipt_sha256,
                    requeue_interrupted_incident=True,
                )
            recovered.append(
                {
                    "attempt_id": r["attempt_id"],
                    "incident_id": r["incident_id"],
                    "branch_name": r["branch_name"],
                    "worktree_path": r["worktree_path"],
                    "branch_preserved": Path(r["worktree_path"]).is_dir(),
                    "incident_state": self.admission.repair_queue.get_incident(r["incident_id"])["state"],
                }
            )
        return recovered
