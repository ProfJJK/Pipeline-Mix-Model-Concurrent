"""Assembly, final testing and truthful root completion (`P428-14`).

Guarantees:
- Unfinished, held, or rejected child microtasks prevent parent completion.
- Model assertions in `final_test` JSON alone cannot close the root task:
  completion requires a controller-verifiable test execution receipt bound to
  the exact `plan_generation_sha256`, upstream `assembly` artifact hashes, and
  `final_test` artifact hash, with `passed=True`, `exit_code=0`, and
  `cleanup_verified=True`.
- Retry or restart after a fragment revision cannot reuse stale `assembly` or
  `final_test` evidence because predecessor artifact digests are cryptographically
  bound into downstream node completion and test receipts.
- Independent planning-review evidence (`state['review']` and
  `state['accepted_planning_jobs']`) is verified and retained in the completed
  task state and release manifest.
"""
from __future__ import annotations

from copy import deepcopy
import json
import time
from typing import Any

from .microtask_board_428 import MicrotaskBoardRuntime
from .task_routing import digest
from .workflow_428 import _id, _sha, _stage, _text


class TaskReleaseRuntime:
    """Coordinates microtask DAG execution, assembly provenance, controller test receipts, and root completion (`P428-14`)."""

    def __init__(
        self,
        journal,
        store,
        *,
        board: MicrotaskBoardRuntime | None = None,
        owner_broker=None,
        clock=time.time,
        artifact_runtime=None,
    ):
        self.journal = journal
        self.store = store
        self.clock = clock
        self.artifact_runtime = artifact_runtime
        self.board = board or MicrotaskBoardRuntime(
            journal,
            store,
            owner_broker=owner_broker,
            clock=clock,
            artifact_runtime=artifact_runtime,
        )
        with self.journal._write() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS task428_test_receipts(
                    receipt_key TEXT PRIMARY KEY,
                    receipt_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL,
                    microtask_id TEXT NOT NULL,
                    plan_generation_sha256 TEXT NOT NULL,
                    assembly_hashes_json TEXT NOT NULL,
                    final_test_artifact_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    exit_code INTEGER NOT NULL,
                    cleanup_verified INTEGER NOT NULL,
                    verified_requirements_json TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    recorded_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task428_releases(
                    task_id TEXT PRIMARY KEY,
                    release_id TEXT NOT NULL UNIQUE,
                    plan_generation_sha256 TEXT NOT NULL,
                    srs_sha256 TEXT NOT NULL,
                    wbs_sha256 TEXT NOT NULL,
                    microtasks_sha256 TEXT NOT NULL,
                    review_json TEXT NOT NULL,
                    release_manifest_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    @staticmethod
    def _receipt_key(
        task_id: str,
        microtask_id: str,
        plan_generation_sha256: str,
        assembly_hashes: dict[str, str],
        final_test_artifact_sha256: str,
    ) -> str:
        return digest(
            {
                "task_id": task_id,
                "microtask_id": microtask_id,
                "plan_generation_sha256": plan_generation_sha256,
                "assembly_hashes": assembly_hashes,
                "final_test_artifact_sha256": final_test_artifact_sha256,
            }
        )

    def record_controller_test_receipt(
        self,
        task_id: str,
        microtask_id: str,
        *,
        passed: bool,
        exit_code: int,
        cleanup_verified: bool,
        verified_requirements: list[str],
        status: str = "COMPLETED",
        summary: str = "Controller-verified final test execution",
        plan_generation_sha256: str | None = None,
        assembly_hashes: dict[str, str] | None = None,
        final_test_artifact_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Record a controller-observed final-test execution receipt."""
        _id(task_id)
        _id(microtask_id)
        if type(passed) is not bool or type(cleanup_verified) is not bool or type(exit_code) is not int:
            raise ValueError("Controller test receipt requires boolean passed/cleanup_verified and integer exit_code")
        if status not in ("COMPLETED", "FAILED", "INTERRUPTED"):
            raise ValueError(f"Unsupported controller test receipt status: {status}")
        summary_text = _text(summary, "Controller test summary", 4000)
        if not isinstance(verified_requirements, list) or any(not isinstance(r, str) for r in verified_requirements):
            raise ValueError("verified_requirements must be a list of requirement IDs")
        clean_reqs = sorted({_id(r) for r in verified_requirements})

        snap = self.board.board_status(task_id)
        gen_sha = _sha(plan_generation_sha256 or snap["plan_generation_sha256"])
        nodes_by_id = {n["microtask_id"]: n for n in snap["nodes"]}
        if microtask_id not in nodes_by_id:
            raise ValueError(f"Unknown microtask_id for test receipt: {microtask_id}")
        ft_node = nodes_by_id[microtask_id]
        if ft_node["role"] != "final_test":
            raise ValueError("Controller test receipts must bind to a final_test microtask node")

        if assembly_hashes is None:
            assembly_hashes = {
                n["microtask_id"]: n["artifact_sha256"]
                for n in snap["nodes"]
                if n["role"] == "assembly" and n.get("artifact_sha256")
            }
        if not assembly_hashes or any(not _sha(v) for v in assembly_hashes.values()):
            raise ValueError("Controller test receipt requires completed assembly artifact hashes")

        ft_art_sha = _sha(final_test_artifact_sha256 or ft_node.get("artifact_sha256"))
        rkey = self._receipt_key(task_id, microtask_id, gen_sha, assembly_hashes, ft_art_sha)
        receipt_id = "testrcpt428-" + rkey[:40]
        now = float(self.clock())

        with self.journal._write() as conn:
            conn.execute(
                "INSERT INTO task428_test_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(receipt_key) DO UPDATE SET status=excluded.status,passed=excluded.passed,"
                "exit_code=excluded.exit_code,cleanup_verified=excluded.cleanup_verified,"
                "verified_requirements_json=excluded.verified_requirements_json,"
                "summary=excluded.summary,recorded_at=excluded.recorded_at",
                (
                    rkey,
                    receipt_id,
                    task_id,
                    microtask_id,
                    gen_sha,
                    json.dumps(assembly_hashes, sort_keys=True),
                    ft_art_sha,
                    status,
                    1 if passed else 0,
                    exit_code,
                    1 if cleanup_verified else 0,
                    json.dumps(clean_reqs),
                    summary_text,
                    now,
                ),
            )
        return {
            "receipt_id": receipt_id,
            "receipt_key": rkey,
            "task_id": task_id,
            "microtask_id": microtask_id,
            "plan_generation_sha256": gen_sha,
            "assembly_hashes": assembly_hashes,
            "final_test_artifact_sha256": ft_art_sha,
            "status": status,
            "passed": passed,
            "exit_code": exit_code,
            "cleanup_verified": cleanup_verified,
            "verified_requirements": clean_reqs,
        }

    def get_release(self, task_id: str) -> dict[str, Any] | None:
        _id(task_id)
        with self.journal._write() as conn:
            row = conn.execute(
                "SELECT release_manifest_json FROM task428_releases WHERE task_id=?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["release_manifest_json"])

    def verify_release_readiness(self, task_id: str) -> dict[str, Any]:
        """Materialize the microtask board and verify all assembly, test, requirement, and review gates."""
        _id(task_id)
        with self.journal._write() as conn:
            row = self.journal._read(conn, task_id)
            state = json.loads(row["state_json"])
        if state.get("stage") == "COMPLETED":
            rel = self.get_release(task_id)
            return {
                "ready": True,
                "status": "EXECUTION_COMPLETED",
                "release": rel,
            }
        _stage(state, "MICROTASKS_READY")

        snap = self.board.materialize(task_id)
        gen_sha = snap["plan_generation_sha256"]
        nodes = snap["nodes"]
        if not nodes:
            return {"ready": False, "status": "MICROTASK_GRAPH_EMPTY"}

        # 1. Check unfinished / held / owner-approval children
        for n in nodes:
            if n["status"] == "HOLD_OWNER_APPROVAL":
                return {
                    "ready": False,
                    "status": "HOLD_OWNER_APPROVAL",
                    "blocking_microtask_id": n["microtask_id"],
                }
            if n["status"] == "HELD":
                return {
                    "ready": False,
                    "status": "MICROTASK_JOB_HELD",
                    "blocking_microtask_id": n["microtask_id"],
                    "job_id": n.get("job_id"),
                }
            if n["status"] != "COMPLETED":
                return {
                    "ready": False,
                    "status": "WAITING_FOR_MICROTASK_BOARD",
                    "blocking_microtask_id": n["microtask_id"],
                    "job_id": n.get("job_id"),
                }

        # 2. Verify independent planning-review evidence was retained and matches current SRS
        review = state.get("review")
        if (
            not isinstance(review, dict)
            or review.get("srs_sha256") != state.get("srs_sha256")
            or review.get("model") == state.get("planner_model")
            or review.get("tier") != state.get("review_tier")
        ):
            return {
                "ready": False,
                "status": "MISSING_INDEPENDENT_PLAN_REVIEW_EVIDENCE",
            }

        # 3. Verify role presence and cryptographic predecessor provenance (rejects stale assembly/test)
        nodes_by_id = {n["microtask_id"]: n for n in nodes}
        impl_nodes = [n for n in nodes if n["role"] == "implementation"]
        asm_nodes = [n for n in nodes if n["role"] == "assembly"]
        ft_nodes = [n for n in nodes if n["role"] == "final_test"]
        if not impl_nodes or not asm_nodes or not ft_nodes:
            return {"ready": False, "status": "MISSING_REQUIRED_ROLES"}

        for n in nodes:
            out = n.get("output") or {}
            recorded_preds = out.get("predecessor_artifact_hashes") or {}
            actual_preds = {
                dep: nodes_by_id[dep]["artifact_sha256"]
                for dep in sorted(n["depends_on"])
            }
            if recorded_preds != actual_preds:
                return {
                    "ready": False,
                    "status": "STALE_ASSEMBLY_OR_TEST_EVIDENCE",
                    "blocking_microtask_id": n["microtask_id"],
                }

        # Materialize physical checks on the existing admission pool. A native
        # final-test response cannot manufacture a controller test receipt.
        if self.artifact_runtime is not None:
            for ft in ft_nodes:
                check = self.artifact_runtime.ensure_verification(self.store.get(ft['job_id']), ft['requirement_ids'])
                if check['status'] != 'VERIFIED':
                    return {'ready': False, **check, 'blocking_microtask_id': ft['microtask_id']}
                if check['output']['verification_kind'] != 'coding_green':
                    return {'ready': False, 'status': 'WAITING_FOR_INDEPENDENT_CONTENT_VERIFICATION',
                            'blocking_microtask_id': ft['microtask_id']}
                self.record_controller_test_receipt(task_id, ft['microtask_id'], passed=True,
                    exit_code=0, cleanup_verified=True, verified_requirements=check['output']['verified_requirements'],
                    summary='Sealed requirement tests executed RED then GREEN by the protected offline runner',
                    plan_generation_sha256=gen_sha,
                    assembly_hashes={n['microtask_id']: n['artifact_sha256'] for n in asm_nodes},
                    final_test_artifact_sha256=ft['artifact_sha256'])

        # 4. Verify controller-owned final-test receipts for every final_test node
        assembly_hashes = {n["microtask_id"]: n["artifact_sha256"] for n in asm_nodes}
        controller_verified_reqs: set[str] = set()
        verified_test_receipts: list[dict[str, Any]] = []

        with self.journal._write() as conn:
            for ft in ft_nodes:
                rkey = self._receipt_key(
                    task_id,
                    ft["microtask_id"],
                    gen_sha,
                    assembly_hashes,
                    ft["artifact_sha256"],
                )
                rrow = conn.execute(
                    "SELECT * FROM task428_test_receipts WHERE receipt_key=?",
                    (rkey,),
                ).fetchone()
                if rrow is None:
                    return {
                        "ready": False,
                        "status": "WAITING_FOR_CONTROLLER_TEST_VERIFICATION",
                        "blocking_microtask_id": ft["microtask_id"],
                    }
                if rrow["status"] == "INTERRUPTED" or not bool(rrow["cleanup_verified"]):
                    return {
                        "ready": False,
                        "status": "FINAL_TEST_INTERRUPTED_CLEANUP_PENDING",
                        "blocking_microtask_id": ft["microtask_id"],
                    }
                if rrow["status"] != "COMPLETED" or not bool(rrow["passed"]) or int(rrow["exit_code"]) != 0:
                    return {
                        "ready": False,
                        "status": "FINAL_TEST_FAILED",
                        "blocking_microtask_id": ft["microtask_id"],
                    }
                reqs = json.loads(rrow["verified_requirements_json"])
                controller_verified_reqs.update(reqs)
                verified_test_receipts.append(
                    {
                        "receipt_id": rrow["receipt_id"],
                        "microtask_id": ft["microtask_id"],
                        "assembly_hashes": json.loads(rrow["assembly_hashes_json"]),
                        "final_test_artifact_sha256": rrow["final_test_artifact_sha256"],
                        "passed": True,
                        "exit_code": 0,
                        "cleanup_verified": True,
                        "verified_requirements": reqs,
                    }
                )

        # 5. Verify full SRS requirement coverage, WBS deliverables, and release criteria
        all_srs_reqs = {r["id"] for r in state["document"]["requirements"]}
        node_covered_reqs: set[str] = set()
        produced_deliverables: dict[str, dict[str, str]] = {}
        satisfied_criteria: list[dict[str, Any]] = []

        for n in nodes:
            out = n["output"]
            for ev in out.get("requirement_evidence") or []:
                node_covered_reqs.add(ev["requirement_id"])
            for d in out.get("deliverables") or []:
                produced_deliverables[d["name"]] = d
            for c in out.get("release_criteria_results") or []:
                if c.get("passed") is True:
                    satisfied_criteria.append(
                        {
                            "microtask_id": n["microtask_id"],
                            "criterion": c["criterion"],
                            "evidence": c["evidence"],
                        }
                    )

        if node_covered_reqs != all_srs_reqs or controller_verified_reqs != all_srs_reqs:
            return {
                "ready": False,
                "status": "MISSING_REQUIREMENT_OR_TEST_COVERAGE",
                "uncovered_by_nodes": sorted(all_srs_reqs - node_covered_reqs),
                "uncovered_by_controller_tests": sorted(all_srs_reqs - controller_verified_reqs),
            }

        required_wbs_deliverables = {
            d for w in (state.get("wbs") or []) for d in (w.get("deliverables") or [])
        }
        if required_wbs_deliverables - produced_deliverables.keys():
            return {
                "ready": False,
                "status": "MISSING_WBS_DELIVERABLES",
                "missing_deliverables": sorted(required_wbs_deliverables - produced_deliverables.keys()),
            }

        release_id = "rel428-" + digest(
            {
                "task_id": task_id,
                "plan_generation_sha256": gen_sha,
                "assembly_hashes": assembly_hashes,
                "test_receipts": [r["receipt_id"] for r in verified_test_receipts],
            }
        )[:40]

        manifest_payload = {
            "schema": "cochem-task-release-manifest/4.2.8",
            "release_id": release_id,
            "task_id": task_id,
            "plan_generation_sha256": gen_sha,
            "srs_sha256": state["srs_sha256"],
            "wbs_sha256": state["wbs_sha256"],
            "microtasks_sha256": state["microtasks_sha256"],
            "independent_plan_review": deepcopy(review),
            "accepted_planning_jobs": deepcopy(state.get("accepted_planning_jobs") or []),
            "assembly_hashes": assembly_hashes,
            "controller_test_receipts": verified_test_receipts,
            "deliverables": [produced_deliverables[k] for k in sorted(produced_deliverables)],
            "verified_requirements": sorted(all_srs_reqs),
            "release_criteria_results": satisfied_criteria,
            "verification_status": "verified",
        }
        return {
            "ready": True,
            "status": "READY_TO_CLOSE",
            "release_manifest": manifest_payload,
        }

    def step_microtask_task(self, task_id: str) -> dict[str, Any]:
        """Advance a `MICROTASKS_READY` task and close the root task only when all gates pass."""
        check = self.verify_release_readiness(task_id)
        if not check["ready"]:
            return {
                "status": check["status"],
                "job_id": check.get("job_id"),
                "blocking_microtask_id": check.get("blocking_microtask_id"),
                "delay": 1,
            }
        if check["status"] == "EXECUTION_COMPLETED":
            return {
                "status": "EXECUTION_COMPLETED",
                "release_id": (check.get("release") or {}).get("release_id"),
                "delay": 3600,
            }

        manifest_payload = check["release_manifest"]
        release_id = manifest_payload["release_id"]
        now = float(self.clock())
        expected_version = self.journal.status(task_id)["journal_version"]

        with self.journal._write() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO task428_releases VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    release_id,
                    manifest_payload["plan_generation_sha256"],
                    manifest_payload["srs_sha256"],
                    manifest_payload["wbs_sha256"],
                    manifest_payload["microtasks_sha256"],
                    json.dumps(manifest_payload["independent_plan_review"], sort_keys=True),
                    json.dumps(manifest_payload, sort_keys=True),
                    now,
                ),
            )

        def transition(row):
            cur = json.loads(row["state_json"])
            _stage(cur, "MICROTASKS_READY")
            if cur.get("srs_sha256") != manifest_payload["srs_sha256"]:
                raise ValueError("Release manifest belongs to a stale SRS revision")
            updated = deepcopy(cur)
            updated["stage"] = "COMPLETED"
            updated["release_manifest"] = manifest_payload
            return updated

        self.journal._transition(
            task_id,
            expected_version,
            "release." + release_id,
            manifest_payload,
            transition,
        )
        return {
            "status": "EXECUTION_COMPLETED",
            "release_id": release_id,
            "delay": 0,
        }
