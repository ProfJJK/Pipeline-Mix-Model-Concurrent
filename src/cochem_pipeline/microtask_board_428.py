"""Materialize and execute the reassessed microtask dependency graph (`P428-12`).

Guarantees:
- Immutable parent/WBS/requirement-linked microtask nodes with individual
  `(task_types, complexity)` routing classification (`WBS_CHILD` lineage).
- Strict DAG readiness: no missing/cyclic dependencies, and dependent nodes
  (including `assembly` and `final_test`) are never submitted to `JobStore`
  until every prerequisite in `depends_on` is `COMPLETED` with verified native cleanup.
- Independent fragments materialize concurrently so up to the shared 4-slot pool
  can execute them in parallel.
- Newly high-tier (`8..10`) reassessed microtask children hold in
  `HOLD_OWNER_APPROVAL` until a verified human-owner receipt is recorded.
- Any change to classification, WBS, or SRS invalidates prior generation nodes
  (`SUPERSEDED`) and cancels uncompleted stale board jobs instead of preserving
  stale routes.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import time
from typing import Any

from . import routing_store as routes
from .task_routing import digest, five_model_options
from .workflow_428 import (
    _id,
    _sha,
    _stage,
    _text,
    approve_microtask,
    compile_reassessed_microtask_plan,
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_microtask_execution_output(
    node: dict[str, Any],
    output: dict[str, Any],
) -> dict[str, Any]:
    """Validate a microtask node's execution output against its deliverables, requirement links, and release criteria."""
    expected_keys = {
        "artifact_text",
        "deliverables",
        "requirement_evidence",
        "release_criteria_results",
    }
    if not isinstance(output, dict) or set(output) != expected_keys:
        raise ValueError(
            "Microtask execution output requires artifact_text, deliverables, "
            "requirement_evidence, and release_criteria_results"
        )
    artifact_text = _text(output["artifact_text"], "Microtask artifact text", 200000)

    raw_deliverables = output["deliverables"]
    if not isinstance(raw_deliverables, list) or not 1 <= len(raw_deliverables) <= 50:
        raise ValueError("Microtask execution requires 1..50 concrete deliverables")

    deliverables_by_name: dict[str, dict[str, str]] = {}
    normalized_deliverables: list[dict[str, str]] = []
    for item in raw_deliverables:
        if not isinstance(item, dict) or set(item) != {"name", "content", "sha256"}:
            raise ValueError("Each microtask deliverable requires name, content, and sha256")
        name = _text(item["name"], "Deliverable name", 256)
        if name in deliverables_by_name:
            raise ValueError(f"Duplicate microtask deliverable: {name}")
        content = _text(item["content"], "Deliverable content", 200000)
        sha = _sha(item["sha256"])
        if _sha256_text(content) != sha:
            raise ValueError(f"Microtask deliverable {name} sha256 does not match its content")
        entry = {"name": name, "content": content, "sha256": sha}
        deliverables_by_name[name] = entry
        normalized_deliverables.append(entry)

    expected_deliverables = set(node.get("deliverables") or [])
    if expected_deliverables - deliverables_by_name.keys():
        raise ValueError("Microtask output omits required declared deliverables")

    expected_reqs = set(node.get("requirement_ids") or [])
    raw_req_ev = output["requirement_evidence"]
    if not isinstance(raw_req_ev, list) or not 1 <= len(raw_req_ev) <= 200:
        raise ValueError("Microtask execution requires bounded requirement_evidence")

    covered_reqs: set[str] = set()
    normalized_req_ev: list[dict[str, str]] = []
    for item in raw_req_ev:
        if not isinstance(item, dict) or set(item) != {
            "requirement_id",
            "deliverable_name",
            "verification_evidence",
        }:
            raise ValueError("Invalid microtask requirement_evidence entry")
        req_id = _id(item["requirement_id"])
        if req_id not in expected_reqs or req_id in covered_reqs:
            raise ValueError(f"Unknown or duplicate microtask requirement_id: {req_id}")
        deliv_name = _text(item["deliverable_name"], "Deliverable reference", 256)
        if deliv_name not in deliverables_by_name:
            raise ValueError(f"Requirement {req_id} references missing deliverable: {deliv_name}")
        ev_text = _text(item["verification_evidence"], "Verification evidence", 4000)
        covered_reqs.add(req_id)
        normalized_req_ev.append(
            {
                "requirement_id": req_id,
                "deliverable_name": deliv_name,
                "verification_evidence": ev_text,
            }
        )
    if covered_reqs != expected_reqs:
        raise ValueError("Microtask output does not cover all linked SRS requirements")

    expected_criteria = list(node.get("release_criteria") or [])
    raw_criteria = output["release_criteria_results"]
    if not isinstance(raw_criteria, list) or len(raw_criteria) != len(expected_criteria):
        raise ValueError("Microtask output must report every release criterion")

    seen_criteria: set[str] = set()
    normalized_criteria: list[dict[str, Any]] = []
    for item in raw_criteria:
        if not isinstance(item, dict) or set(item) != {"criterion", "passed", "evidence"}:
            raise ValueError("Invalid microtask release_criteria_results entry")
        crit = _text(item["criterion"], "Release criterion", 4000)
        if crit not in expected_criteria or crit in seen_criteria:
            raise ValueError(f"Unknown or duplicate microtask release criterion: {crit}")
        if item["passed"] is not True:
            raise ValueError(f"Microtask release criterion not satisfied: {crit}")
        ev = _text(item["evidence"], "Release criterion evidence", 4000)
        seen_criteria.add(crit)
        normalized_criteria.append({"criterion": crit, "passed": True, "evidence": ev})

    return {
        "artifact_text": artifact_text,
        "artifact_sha256": _sha256_text(artifact_text),
        "deliverables": normalized_deliverables,
        "requirement_evidence": normalized_req_ev,
        "release_criteria_results": normalized_criteria,
    }


class MicrotaskBoardRuntime:
    """Materializes and coordinates reassessed WBS microtask DAGs on `JobStore` (`P428-12`)."""

    def __init__(self, journal, store, *, owner_broker=None, clock=time.time):
        self.journal = journal
        self.store = store
        self.owner_broker = owner_broker
        self.clock = clock
        with self.journal._write() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS microtask428_nodes(
                    node_key TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    microtask_id TEXT NOT NULL,
                    plan_generation_sha256 TEXT NOT NULL,
                    lineage_kind TEXT NOT NULL,
                    attempt_lineage_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    complexity INTEGER NOT NULL,
                    task_types_json TEXT NOT NULL,
                    wbs_ids_json TEXT NOT NULL,
                    section_ids_json TEXT NOT NULL,
                    requirement_ids_json TEXT NOT NULL,
                    deliverables_json TEXT NOT NULL,
                    audit_metrics_json TEXT NOT NULL,
                    release_criteria_json TEXT NOT NULL,
                    depends_on_json TEXT NOT NULL,
                    candidate_profiles_json TEXT NOT NULL,
                    node_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    job_id TEXT,
                    output_json TEXT,
                    artifact_sha256 TEXT,
                    updated_at REAL NOT NULL
                );
                """
            )

    @staticmethod
    def _plan_generation_sha256(state: dict[str, Any], catalog: dict[str, Any]) -> str:
        stripped_microtasks = [
            {k: v for k, v in row.items() if k != "owner_approval"}
            for row in (state.get("microtasks") or [])
        ]
        return digest(
            {
                "task_id": state["task_id"],
                "srs_sha256": state["srs_sha256"],
                "wbs_sha256": state["wbs_sha256"],
                "microtasks": stripped_microtasks,
                "catalog_sha256": digest(catalog),
            }
        )

    def _compile(self, task_id: str) -> tuple[str, list[dict[str, Any]], dict[str, Any], dict[str, Any], int | None]:
        _id(task_id)
        with self.journal._write() as conn:
            row = self.journal._read(conn, task_id)
            state = json.loads(row["state_json"])
            catalog = json.loads(row["catalog_json"])
            limit = row["flash_context_limit"]
        nodes = compile_reassessed_microtask_plan(state)
        gen_sha = self._plan_generation_sha256(state, catalog)
        return gen_sha, nodes, state, catalog, limit

    def _cancel_stale_board_job(self, job_id: str | None) -> None:
        if not job_id:
            return
        with self.store._write() as conn:
            row = conn.execute(
                "SELECT workflow_id, status FROM pipeline_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
            if row and row["status"] not in ("COMPLETED", "FAILED"):
                conn.execute(
                    "UPDATE pipeline_jobs SET status='FAILED',lease_owner=NULL,lease_expires_at=NULL WHERE workflow_id=?",
                    (row["workflow_id"],),
                )
                routes.release(conn, job_id, "cancelled", "FAILED")

    def _submit_board_job_for_node(
        self,
        task_id: str,
        gen_sha: str,
        node: dict[str, Any],
        state: dict[str, Any],
        catalog: dict[str, Any],
        limit: int | None,
        candidates: list[str],
        predecessor_outputs: dict[str, Any],
    ) -> dict[str, Any]:
        from .planning_gateway import prompt_contract, scoped_policy

        intent = {
            "schema": "cochem-planning-intent/4.2.8",
            "action": "model_stage",
            "stage": "MICROTASK_EXECUTION",
            "task_id": task_id,
            "microtask_id": node["microtask_id"],
            "plan_generation_sha256": gen_sha,
            "version": state.get("journal_version", 0),
            "state_sha256": digest(state),
            "catalog_sha256": digest(catalog),
            "srs_sha256": state["srs_sha256"],
            "complexity": node["complexity"],
            "task_types": node["task_types"],
            "candidate_profiles": candidates,
            "task": state,
            "execution_authorized": True,
        }
        policy = scoped_policy(self.store.routing_policy, intent, catalog)
        identity = digest({"gen": gen_sha, "microtask_id": node["microtask_id"], "candidates": candidates})
        root_id = "mt428-" + identity[:40]
        job_id = "mt428-node-" + identity[:40]
        payload = {
            "workflow_type": "planning428",
            "execution_role": f"microtask_{node['role']}",
            "planning_intent": intent,
            "microtask_node": node,
            "predecessor_outputs": predecessor_outputs,
            "task_catalog": catalog,
            "flash_context_limit": limit,
        }
        prompt_contract(payload)
        with self.store._write() as conn:
            existing = conn.execute(
                "SELECT job_id FROM pipeline_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
            if existing:
                prior = self.store._get(conn, job_id)
                if prior["payload"] != payload:
                    raise ValueError("Existing microtask execution job has different immutable input")
                return prior
            self.store._insert(
                conn,
                root_id,
                root_id,
                None,
                "MACRO_PLANNING_REQUEST",
                "IN_PROGRESS",
                {
                    "workflow_type": "planning428",
                    "execution_role": f"microtask_{node['role']}",
                    "intent_sha256": identity,
                },
            )
            routes.capture_workflow(conn, root_id, policy)
            self.store._insert(
                conn,
                job_id,
                root_id,
                root_id,
                "TASK_PLAN",
                "PENDING",
                payload,
                max_attempts=10,
            )
            self.store._event(
                conn,
                self.store._get(conn, root_id),
                "MICROTASK_EXECUTION_SUBMITTED",
                task_id=task_id,
                microtask_id=node["microtask_id"],
                intent_sha256=identity,
            )
            return self.store._get(conn, job_id)

    def _check_board_completion(self, job_id: str, node: dict[str, Any]) -> dict[str, Any] | None:
        from .planning_gateway import validate_stage_output

        with self.store._connection() as conn:
            job = self.store._get(conn, job_id)
            if job["status"] != "COMPLETED":
                return None
            cleanup = conn.execute(
                "SELECT cleared_at FROM pipeline_execution_cleanup "
                "WHERE job_id=? AND attempt_id=? AND fencing_token=?",
                (job_id, job["attempt_id"], job["fencing_token"]),
            ).fetchone()
            if cleanup is None or cleanup["cleared_at"] is None:
                return None
            profile_id = validate_stage_output(job["payload"], job["output"], job["route"])
            validated = validate_microtask_execution_output(node, job["output"])
            return {"profile_id": profile_id, "validated": validated}

    def materialize(self, task_id: str) -> dict[str, Any]:
        """Compile, reconcile, and dispatch ready microtask nodes for `task_id`."""
        gen_sha, compiled_nodes, state, catalog, limit = self._compile(task_id)
        now = float(self.clock())

        # 1. Supersede any nodes from an older generation (changed classification/WBS/SRS)
        stale_job_ids: list[str] = []
        with self.journal._write() as conn:
            stale_rows = conn.execute(
                "SELECT node_key, job_id FROM microtask428_nodes "
                "WHERE task_id=? AND plan_generation_sha256<>? AND status<>'SUPERSEDED'",
                (task_id, gen_sha),
            ).fetchall()
            for srow in stale_rows:
                if srow["job_id"]:
                    stale_job_ids.append(srow["job_id"])
                conn.execute(
                    "UPDATE microtask428_nodes SET status='SUPERSEDED',updated_at=? WHERE node_key=?",
                    (now, srow["node_key"]),
                )
        for stale_jid in stale_job_ids:
            self._cancel_stale_board_job(stale_jid)

        # 2. Ensure current generation rows exist and sync completed board jobs
        completed_by_id: dict[str, dict[str, Any]] = {}
        for node in compiled_nodes:
            mt_id = node["microtask_id"]
            node_key = f"{gen_sha[:32]}::{mt_id}"
            options = five_model_options(catalog, node["task_types"], node["complexity"])
            candidates = [opt["model_id"] for opt in options if opt["meets_floor"]]
            if not candidates:
                raise ValueError(f"No eligible profiles meet the floor for microtask {mt_id}")

            with self.journal._write() as conn:
                existing = conn.execute(
                    "SELECT * FROM microtask428_nodes WHERE node_key=?",
                    (node_key,),
                ).fetchone()

            if existing is not None and existing["status"] == "COMPLETED":
                completed_by_id[mt_id] = json.loads(existing["output_json"])
                continue

            if existing is not None and existing["job_id"]:
                done = self._check_board_completion(existing["job_id"], node)
                if done is not None:
                    val = done["validated"]
                    with self.journal._write() as conn:
                        conn.execute(
                            "UPDATE microtask428_nodes SET status='COMPLETED',output_json=?,artifact_sha256=?,updated_at=? "
                            "WHERE node_key=?",
                            (
                                json.dumps(val, sort_keys=True),
                                val["artifact_sha256"],
                                now,
                                node_key,
                            ),
                        )
                    completed_by_id[mt_id] = val
                    continue

        # 3. Evaluate dependency readiness and child owner approval for remaining nodes
        for node in compiled_nodes:
            mt_id = node["microtask_id"]
            if mt_id in completed_by_id:
                continue
            node_key = f"{gen_sha[:32]}::{mt_id}"
            options = five_model_options(catalog, node["task_types"], node["complexity"])
            candidates = [opt["model_id"] for opt in options if opt["meets_floor"]]

            deps_ready = all(dep in completed_by_id for dep in node["depends_on"])
            if node["needs_owner_approval"]:
                desired_status = "HOLD_OWNER_APPROVAL"
                job_id = None
            elif not deps_ready:
                desired_status = "WAITING_ON_DEPENDENCIES"
                job_id = None
            else:
                pred_outputs = {dep: completed_by_id[dep] for dep in node["depends_on"]}
                board_job = self._submit_board_job_for_node(
                    task_id,
                    gen_sha,
                    node,
                    state,
                    catalog,
                    limit,
                    candidates,
                    pred_outputs,
                )
                job_id = board_job["job_id"]
                if board_job["status"] in ("FAILED", "BLOCKED"):
                    desired_status = "HELD"
                elif board_job["status"] == "COMPLETED":
                    done = self._check_board_completion(job_id, node)
                    if done is not None:
                        val = done["validated"]
                        with self.journal._write() as conn:
                            conn.execute(
                                "INSERT INTO microtask428_nodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                                "ON CONFLICT(node_key) DO UPDATE SET status='COMPLETED',job_id=excluded.job_id,"
                                "output_json=excluded.output_json,artifact_sha256=excluded.artifact_sha256,updated_at=excluded.updated_at",
                                (
                                    node_key,
                                    task_id,
                                    mt_id,
                                    gen_sha,
                                    node["lineage_kind"],
                                    node["attempt_lineage_id"],
                                    node["role"],
                                    node["complexity"],
                                    json.dumps(node["task_types"]),
                                    json.dumps(node["wbs_ids"]),
                                    json.dumps(node["section_ids"]),
                                    json.dumps(node["requirement_ids"]),
                                    json.dumps(node["deliverables"]),
                                    json.dumps(node["audit_metrics"]),
                                    json.dumps(node["release_criteria"]),
                                    json.dumps(node["depends_on"]),
                                    json.dumps(candidates),
                                    json.dumps(node, sort_keys=True),
                                    "COMPLETED",
                                    job_id,
                                    json.dumps(val, sort_keys=True),
                                    val["artifact_sha256"],
                                    now,
                                ),
                            )
                        completed_by_id[mt_id] = val
                        continue
                    desired_status = "WAITING_FOR_NATIVE_CLEANUP"
                else:
                    desired_status = "DISPATCHED"

            with self.journal._write() as conn:
                conn.execute(
                    "INSERT INTO microtask428_nodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(node_key) DO UPDATE SET status=excluded.status,job_id=excluded.job_id,"
                    "node_json=excluded.node_json,updated_at=excluded.updated_at",
                    (
                        node_key,
                        task_id,
                        mt_id,
                        gen_sha,
                        node["lineage_kind"],
                        node["attempt_lineage_id"],
                        node["role"],
                        node["complexity"],
                        json.dumps(node["task_types"]),
                        json.dumps(node["wbs_ids"]),
                        json.dumps(node["section_ids"]),
                        json.dumps(node["requirement_ids"]),
                        json.dumps(node["deliverables"]),
                        json.dumps(node["audit_metrics"]),
                        json.dumps(node["release_criteria"]),
                        json.dumps(node["depends_on"]),
                        json.dumps(candidates),
                        json.dumps(node, sort_keys=True),
                        desired_status,
                        job_id,
                        None,
                        None,
                        now,
                    ),
                )

        return self.board_status(task_id)

    def approve_child_microtask(
        self,
        task_id: str,
        microtask_id: str,
        *,
        owner_token: str,
        notes: str = "",
    ) -> dict[str, Any]:
        """Authenticate the human owner and approve a newly high-tier (8..10) child microtask."""
        if self.owner_broker is None:
            raise ValueError("OwnerApprovalBroker is required to approve high-tier microtasks")
        self.owner_broker._authenticate_owner_token(owner_token)
        state = self.journal.status(task_id)
        expected_version = state["journal_version"]
        receipt_id = "mtownercpt428-" + digest(
            {
                "task_id": task_id,
                "microtask_id": microtask_id,
                "microtasks_sha256": state["microtasks_sha256"],
                "notes": notes,
            }
        )[:40]
        evidence = {
            "receipt_id": receipt_id,
            "task_id": task_id,
            "microtask_id": microtask_id,
            "microtasks_sha256": state["microtasks_sha256"],
            "actor_kind": "human_owner",
            "notes": notes,
        }

        def transition(row):
            cur = json.loads(row["state_json"])
            return approve_microtask(cur, microtask_id, cur["microtasks_sha256"], receipt_id)

        self.journal._transition(
            task_id,
            expected_version,
            f"mtowner.{microtask_id}.{receipt_id}",
            evidence,
            transition,
        )
        return self.materialize(task_id)

    def board_status(self, task_id: str) -> dict[str, Any]:
        _id(task_id)
        with self.journal._write() as conn:
            row = self.journal._read(conn, task_id)
            state = json.loads(row["state_json"])
            catalog = json.loads(row["catalog_json"])
            gen_sha = self._plan_generation_sha256(state, catalog)
            rows = conn.execute(
                "SELECT * FROM microtask428_nodes WHERE task_id=? AND plan_generation_sha256=? ORDER BY microtask_id",
                (task_id, gen_sha),
            ).fetchall()
            superseded_count = conn.execute(
                "SELECT count(*) FROM microtask428_nodes WHERE task_id=? AND status='SUPERSEDED'",
                (task_id,),
            ).fetchone()[0]

        nodes = []
        for r in rows:
            nodes.append(
                {
                    "microtask_id": r["microtask_id"],
                    "lineage_kind": r["lineage_kind"],
                    "attempt_lineage_id": r["attempt_lineage_id"],
                    "role": r["role"],
                    "complexity": r["complexity"],
                    "task_types": json.loads(r["task_types_json"]),
                    "wbs_ids": json.loads(r["wbs_ids_json"]),
                    "section_ids": json.loads(r["section_ids_json"]),
                    "requirement_ids": json.loads(r["requirement_ids_json"]),
                    "deliverables": json.loads(r["deliverables_json"]),
                    "audit_metrics": json.loads(r["audit_metrics_json"]),
                    "release_criteria": json.loads(r["release_criteria_json"]),
                    "depends_on": json.loads(r["depends_on_json"]),
                    "candidate_profiles": json.loads(r["candidate_profiles_json"]),
                    "status": r["status"],
                    "job_id": r["job_id"],
                    "artifact_sha256": r["artifact_sha256"],
                    "output": json.loads(r["output_json"]) if r["output_json"] else None,
                }
            )
        return {
            "schema": "cochem-microtask-board/4.2.8",
            "task_id": task_id,
            "plan_generation_sha256": gen_sha,
            "nodes": nodes,
            "superseded_nodes": superseded_count,
            "all_completed": bool(nodes) and all(n["status"] == "COMPLETED" for n in nodes),
        }
