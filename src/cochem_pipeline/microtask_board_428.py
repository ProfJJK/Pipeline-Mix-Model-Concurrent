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
from typing import Any, Mapping

from . import routing_store as routes
from .attempt_runtime_428 import AttemptAccountingRuntime
from .planning_budgets_428 import LineageBudgetHold, capture_lineage_budget
from .swarm_batch_428 import (
    extract_microtask_files,
    pack_conflict_colored_wave,
    resolve_microtask_route_tier,
    validate_swarm_batch_stage_output,
)
from .task_routing import digest, five_model_options
from .workflow_428 import (
    AttemptLedger,
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
    """Materializes and coordinates reassessed WBS microtask DAGs on `JobStore` (`P428-12`, `P428-SWARM`)."""

    def __init__(
        self,
        journal,
        store,
        *,
        owner_broker=None,
        attempt_ledger: AttemptLedger | AttemptAccountingRuntime | None = None,
        clock=time.time,
        swarm_batch_mode: bool = False,
        artifact_runtime=None,
    ):
        self.journal = journal
        self.store = store
        self.owner_broker = owner_broker
        self.clock = clock
        self.swarm_batch_mode = bool(swarm_batch_mode)
        self.artifact_runtime = artifact_runtime
        self.fracture_runtime = None
        self.fracture_planning = None
        if isinstance(attempt_ledger, AttemptAccountingRuntime):
            self.attempt_accounting: AttemptAccountingRuntime | None = attempt_ledger
            self.attempt_ledger: AttemptLedger | None = attempt_ledger.ledger
        elif isinstance(attempt_ledger, AttemptLedger):
            self.attempt_accounting = AttemptAccountingRuntime(
                attempt_ledger,
                store=store,
                clock=clock,
            )
            self.attempt_ledger = attempt_ledger
        else:
            self.attempt_accounting = None
            self.attempt_ledger = None

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
                CREATE TABLE IF NOT EXISTS microtask428_file_locks(
                    file_path TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    microtask_id TEXT NOT NULL,
                    node_key TEXT NOT NULL,
                    plan_generation_sha256 TEXT NOT NULL,
                    batch_id TEXT,
                    slot_id TEXT,
                    provider_family TEXT,
                    acquired_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS microtask428_batches(
                    batch_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    plan_generation_sha256 TEXT NOT NULL,
                    provider_family TEXT NOT NULL,
                    slot_index INTEGER NOT NULL,
                    slot_id TEXT NOT NULL,
                    max_agents_per_slot INTEGER NOT NULL,
                    max_nesting_depth INTEGER NOT NULL,
                    microtask_ids_json TEXT NOT NULL,
                    subagents_json TEXT NOT NULL,
                    locked_files_json TEXT NOT NULL,
                    batch_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    job_id TEXT,
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
        if self.fracture_planning is not None:
            nodes = self._overlay_fractures(nodes, self.fracture_planning.records_for_task(task_id, gen_sha))
        return gen_sha, nodes, state, catalog, limit

    def _overlay_fractures(self, nodes, records):
        """Project registered children without changing the original SRS/WBS generation."""
        by_id = {node['microtask_id']: deepcopy(node) for node in nodes}
        for record in records:
            failed_id = record['failed_scope_id']
            if failed_id not in by_id:
                raise ValueError('Registered fracture scope is absent from this task generation')
            failed = by_id[failed_id]
            source = record['source_job']['payload']
            if source['microtask_node']['microtask_id'] != failed_id:
                raise ValueError('Fracture source microtask differs from its scope')
            current = {row['child_id']: row for row in record['children']}
            finals = [child for child in record['graph']['children'] if child['role'] == 'final_test']
            if len(finals) != 1:
                raise ValueError('Accepted fracture requires exactly one terminal verification child')
            context = dict(fracture_id=record['fracture_id'], graph_sha256=record['graph_sha256'],
                dossier_sha256=record['dossier_sha256'], lineage_root=record['lineage_root'],
                failed_microtask_id=failed_id)
            for child in record['graph']['children']:
                cid = child['id']
                if cid in by_id:
                    raise ValueError('Fracture child collides with a task scope')
                projection = current[cid]
                by_id[cid] = dict(failed, **{key: deepcopy(value) for key, value in child.items()
                    if key not in ('id', 'lineage_root', 'failed_scope_id')})
                by_id[cid].update(microtask_id=cid, lineage_kind='FAILURE_FRACTURE', attempt_lineage_id=cid,
                    fracture_context=context, needs_owner_approval=projection['needs_owner_approval'],
                    owner_approval=projection['owner_approval'],
                    fracture_external_predecessors=deepcopy(source.get('predecessor_outputs') or {}),
                    # The physical snapshot still inherits the original, exact
                    # external dependency capture, without rewriting graph deps.
                    ancestors=sorted(set(child['ancestors']) | set(failed['ancestors'])))
                for key in ('physical_retry', 'pivot_context', 'effective_complexity', 'pivot_model', 'fracture_join'):
                    by_id[cid].pop(key, None)
            failed['fracture_join'] = dict(record, failed_node=dict(deepcopy(source['microtask_node']),
                plan_generation_sha256=source['planning_intent']['plan_generation_sha256']))
            failed['depends_on'] = [finals[0]['id']]
        return list(by_id.values())

    @staticmethod
    def _predecessors(node, completed):
        return {**deepcopy(node.get('fracture_external_predecessors') or {}),
                **{dep: completed[dep] for dep in node['depends_on']}}

    def _sync_fracture_completion(self, node, output):
        if not node.get('fracture_context') or node.get('fracture_join'):
            return
        if self.fracture_runtime is None:
            raise ValueError('Compiled fracture cannot complete without its controller journal')
        current = self.fracture_runtime.get_fracture_child(node['microtask_id'])
        if current['status'] == 'COMPLETED':
            if current['artifact_sha256'] != output['artifact_sha256']:
                raise ValueError('Fracture completion cannot be rebound to different bytes')
            return
        # Inputs here come only from _check_board_completion, never a model's
        # self-attested graph state. Physical final proof remains a join gate.
        self.fracture_runtime.complete_fracture_child(current['lineage_root'],
            node['microtask_id'], output['artifact_sha256'])

    def _materialize_fracture_join(self, task_id, gen_sha, node, completed, now):
        record = node['fracture_join']
        children = [dict(microtask_id=child['id'], role=child['role'],
                    status='COMPLETED', output=completed[child['id']],
                    artifact_sha256=completed[child['id']]['artifact_sha256'],
                    job_id=completed[child['id']]['producer_job_id'])
                    for child in record['graph']['children'] if child['id'] in completed]
        result = dict(status='WAITING_FOR_FRACTURE_CHILDREN')
        if len(children) == len(record['graph']['children']):
            if self.artifact_runtime is None or not hasattr(self.artifact_runtime, 'fracture_join'):
                result = dict(status='WAITING_FOR_FRACTURE_PHYSICAL_JOIN')
            else:
                result = self.artifact_runtime.fracture_join(task_id, record['failed_node'], record, children)
        output = result.get('output') if result['status'] == 'COMPLETED' else None
        if output is not None:
            # Native final-test output and physical alias verification remain
            # authoritative; the board does not manufacture a native completion.
            if not output.get('fracture_join_id') or not result.get('job_id'):
                raise ValueError('Completed fracture join requires concrete verified producer identity')
            expected = {dep: completed[dep] for dep in node['depends_on']}
            if output.get('predecessor_artifact_hashes') != {dep: value['artifact_sha256']
                    for dep, value in sorted(expected.items())}:
                raise ValueError('Fracture join must bind its exact terminal predecessor')
            from .fracture_recovery_428 import complete_nested_alias
            complete_nested_alias(self, task_id, gen_sha, node, output)
        with self.journal._write() as conn:
            key = f'{gen_sha[:32]}::{node["microtask_id"]}'
            self._release_node_file_locks(conn, key)
            self._upsert_node_row(conn, node_key=key, task_id=task_id, mt_id=node['microtask_id'],
                gen_sha=gen_sha, node=node, candidates=[], status=result['status'],
                job_id=result.get('job_id'), output_obj=output,
                artifact_sha256=output['artifact_sha256'] if output else None, now=now)
            # This row is a projection of the immutable alias, not a rewrite of
            # the failed native job. Its dependency is now the verified inner
            # terminal; retain the original contract in the alias binding.
            conn.execute('UPDATE microtask428_nodes SET depends_on_json=? WHERE node_key=?',
                         (json.dumps(node['depends_on']), key))
        return output

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

    @staticmethod
    def _topological_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id = {n["microtask_id"]: n for n in nodes}
        remaining = set(by_id)
        ordered: list[dict[str, Any]] = []
        while remaining:
            ready = sorted(k for k in remaining if not (set(by_id[k]["depends_on"]) & remaining))
            if not ready:
                raise ValueError("Dependency cycle in compiled microtask nodes")
            for k in ready:
                ordered.append(by_id[k])
                remaining.remove(k)
        return ordered

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

        pred_hashes = {
            dep: out["artifact_sha256"]
            for dep, out in sorted(predecessor_outputs.items())
        }
        intent = {
            "schema": "cochem-planning-intent/4.2.8",
            "action": "model_stage",
            "stage": "MICROTASK_EXECUTION",
            "task_id": task_id,
            "microtask_id": node["microtask_id"],
            "plan_generation_sha256": gen_sha,
            "predecessor_artifact_hashes": pred_hashes,
            "version": state.get("journal_version", 0),
            "state_sha256": digest(state),
            "catalog_sha256": digest(catalog),
            "srs_sha256": state["srs_sha256"],
            "complexity": node.get("effective_complexity", node["complexity"]),
            "task_types": node["task_types"],
            "candidate_profiles": candidates,
            "task": state,
            "execution_authorized": True,
        }
        policy = scoped_policy(self.store.routing_policy, intent, catalog)
        identity = digest(
            {
                "gen": gen_sha,
                "microtask_id": node["microtask_id"],
                "candidates": candidates,
                "pred_hashes": pred_hashes,
                "pivot_context": node.get("pivot_context"),
                "physical_retry": node.get("physical_retry"),
            }
        )
        root_id = "mt428-" + identity[:40]
        job_id = "mt428-node-" + identity[:40]
        payload = {
            "workflow_type": "planning428",
            "execution_role": f"microtask_{node['role']}",
            "planning_intent": intent,
            "microtask_node": node,
            "predecessor_outputs": predecessor_outputs,
            "predecessor_artifact_hashes": pred_hashes,
            "task_catalog": catalog,
            "flash_context_limit": limit,
        }
        if self.artifact_runtime is not None:
            payload['execution_context'] = self.artifact_runtime.execution_context(payload)
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
            budget = (capture_lineage_budget(conn, job_id, payload, policy,
                attempt_ledger=self.attempt_ledger) if self.attempt_ledger is not None else None)
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
            routes.capture_workflow(conn, root_id, policy,
                                    max_dispatches=budget.max_dispatches if budget else None)
            self.store._insert(
                conn,
                job_id,
                root_id,
                root_id,
                "TASK_PLAN",
                "PENDING",
                payload,
                max_attempts=budget.max_attempts if budget else 10,
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

    def _submit_board_job_for_swarm_batch(
        self,
        task_id: str,
        gen_sha: str,
        batch: dict[str, Any],
        state: dict[str, Any],
        catalog: dict[str, Any],
        limit: int | None,
        predecessor_outputs_by_mt: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        from .planning_gateway import prompt_contract, scoped_policy

        pred_hashes_by_mt = {
            mt_id: {
                dep: out["artifact_sha256"]
                for dep, out in sorted(pred_map.items())
            }
            for mt_id, pred_map in sorted(predecessor_outputs_by_mt.items())
        }
        candidates = list(batch["candidate_profiles"])
        intent = {
            "schema": "cochem-planning-intent/4.2.8",
            "action": "model_stage",
            "stage": "MICROTASK_SWARM_BATCH",
            "task_id": task_id,
            "batch_id": batch["batch_id"],
            "provider_family": batch["provider_family"],
            "slot_id": batch["slot_id"],
            "microtask_ids": list(batch["microtask_ids"]),
            "plan_generation_sha256": gen_sha,
            "predecessor_artifact_hashes_by_microtask": pred_hashes_by_mt,
            "version": state.get("journal_version", 0),
            "state_sha256": digest(state),
            "catalog_sha256": digest(catalog),
            "srs_sha256": state["srs_sha256"],
            "complexity": int(batch["complexity"]),
            "task_types": list(batch["task_types"]),
            "candidate_profiles": candidates,
            "task": state,
            "execution_authorized": True,
        }
        policy = scoped_policy(self.store.routing_policy, intent, catalog)
        identity = digest(
            {
                "gen": gen_sha,
                "batch_id": batch["batch_id"],
                "microtask_ids": batch["microtask_ids"],
                "candidates": candidates,
                "pred_hashes_by_mt": pred_hashes_by_mt,
            }
        )
        root_id = "mtswb428-" + identity[:38]
        job_id = "mt428-batch-" + identity[:38]
        payload = {
            "workflow_type": "planning428",
            "execution_role": f"swarm_batch_{batch['provider_family']}",
            "planning_intent": intent,
            "swarm_batch": batch,
            "predecessor_outputs_by_microtask": predecessor_outputs_by_mt,
            "predecessor_artifact_hashes_by_microtask": pred_hashes_by_mt,
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
                    raise ValueError("Existing swarm batch job has different immutable input")
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
                    "execution_role": f"swarm_batch_{batch['provider_family']}",
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
                "MICROTASK_SWARM_BATCH_SUBMITTED",
                task_id=task_id,
                batch_id=batch["batch_id"],
                provider_family=batch["provider_family"],
                slot_id=batch["slot_id"],
                microtask_ids=list(batch["microtask_ids"]),
                intent_sha256=identity,
            )
            return self.store._get(conn, job_id)

    def _check_board_completion(self, job_id: str, node: dict[str, Any]) -> dict[str, Any] | None:
        from .planning_gateway import validate_stage_output

        with self.store._connection() as conn:
            job = self.store._get(conn, job_id)
            if job["status"] != "COMPLETED":
                return None
            if (job["payload"].get("planning_intent") or {}).get("stage") == "MICROTASK_SWARM_BATCH":
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
            validated["profile_id"] = profile_id
            # These references belong to the committed controller receipt, never
            # to model output. Dependency snapshots remain unambiguous after a
            # repaired producer completes in the same plan generation.
            validated["producer_job_id"] = job["job_id"]
            validated["producer_attempt_id"] = job["attempt_id"]
            validated["producer_fencing_token"] = job["fencing_token"]
            validated["predecessor_artifact_hashes"] = dict(
                job["payload"].get("predecessor_artifact_hashes") or {}
            )
            return {"profile_id": profile_id, "validated": validated}

    def _release_node_file_locks(self, conn, node_key: str) -> None:
        conn.execute("DELETE FROM microtask428_file_locks WHERE node_key=?", (node_key,))

    def _acquire_node_file_locks(
        self,
        conn,
        *,
        task_id: str,
        microtask_id: str,
        node_key: str,
        gen_sha: str,
        batch_id: str | None,
        slot_id: str | None,
        provider_family: str | None,
        locked_files: list[str],
        now: float,
    ) -> None:
        self._release_node_file_locks(conn, node_key)
        for fpath in locked_files:
            conn.execute(
                "INSERT INTO microtask428_file_locks VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(file_path) DO UPDATE SET "
                "task_id=excluded.task_id,microtask_id=excluded.microtask_id,node_key=excluded.node_key,"
                "plan_generation_sha256=excluded.plan_generation_sha256,batch_id=excluded.batch_id,"
                "slot_id=excluded.slot_id,provider_family=excluded.provider_family,acquired_at=excluded.acquired_at",
                (
                    fpath,
                    task_id,
                    microtask_id,
                    node_key,
                    gen_sha,
                    batch_id,
                    slot_id,
                    provider_family,
                    now,
                ),
            )

    def _upsert_node_row(
        self,
        conn,
        *,
        node_key: str,
        task_id: str,
        mt_id: str,
        gen_sha: str,
        node: dict[str, Any],
        candidates: list[str],
        status: str,
        job_id: str | None,
        output_obj: dict[str, Any] | None,
        artifact_sha256: str | None,
        now: float,
    ) -> None:
        conn.execute(
            "INSERT INTO microtask428_nodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(node_key) DO UPDATE SET status=excluded.status,job_id=excluded.job_id,"
            "output_json=excluded.output_json,artifact_sha256=excluded.artifact_sha256,"
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
                status,
                job_id,
                json.dumps(output_obj, sort_keys=True) if output_obj is not None else None,
                artifact_sha256,
                now,
            ),
        )

    def _physical_recovery_contexts(self, task_id, nodes):
        """Derive recovery generations from accounted, committed verifier failures."""
        if self.artifact_runtime is None or self.attempt_accounting is None:
            return {}
        contexts = {}
        for final in (n for n in nodes if n['role'] == 'final_test'):
            feedback = self.artifact_runtime.retry_feedback(task_id, final['microtask_id'])
            if feedback is None:
                continue
            producer = self.store.get(feedback['producer_job_id'])
            with self.attempt_accounting.ledger._write() as conn:
                accounted = conn.execute("SELECT lineage_root FROM attempt428_outbox WHERE job_id=? "
                    "AND attempt_id=? AND fencing_token=? AND status='RECONCILED' AND staged_outcome='quality_failure'",
                    (producer['job_id'], producer['attempt_id'], producer['fencing_token'])).fetchone()
            if accounted is None or accounted['lineage_root'] != self.attempt_accounting.ledger.status(feedback['lineage_root'])['root']:
                continue
            if self.attempt_accounting.ledger.status(accounted['lineage_root'])['stage'] != 'READY':
                continue
            code_repair = feedback['failure'].get('test_phase') != 'red'
            affected = {final['microtask_id']}
            if code_repair:
                assembly = {n['microtask_id'] for n in nodes if n['role'] == 'assembly'
                            and n['microtask_id'] in final['ancestors']
                            and (not final.get('fracture_context') or
                                 n.get('fracture_context', {}).get('fracture_id') == final['fracture_context']['fracture_id'])}
                if not assembly:
                    raise ValueError('Failed final verification has no assigned assembly ancestor')
                affected |= assembly
                affected |= {n['microtask_id'] for n in nodes if set(n['ancestors']) & assembly}
            for node in nodes:
                if node['microtask_id'] not in affected:
                    continue
                context = contexts.setdefault(node['microtask_id'], dict(
                    schema='cochem-microtask-physical-recovery/4.2.8', failed_checks=[], sealed_test_producer_ids=[]))
                context['failed_checks'].append(deepcopy(feedback))
                if code_repair:
                    context['sealed_test_producer_ids'].append(producer['job_id'])
        for context in contexts.values():
            context['failed_checks'].sort(key=lambda f: (f['lineage_root'], f['retry_generation'], f['verification_job_id']))
            context['sealed_test_producer_ids'] = sorted(set(context['sealed_test_producer_ids']))
        return contexts

    def _materialize_internal(
        self,
        task_id: str,
        *,
        use_swarm_batches: bool,
        preserve_pending_retry_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        gen_sha, compiled_nodes, state, catalog, limit = self._compile(task_id)
        # Registered fracture members require individual native fences and exact
        # captured profiles; they do not enter aggregate swarm accounting.
        if any(node.get('fracture_context') or node.get('fracture_join') for node in compiled_nodes):
            use_swarm_batches = False
        ordered_nodes = self._topological_nodes(compiled_nodes)
        recovery = self._physical_recovery_contexts(task_id, ordered_nodes)
        from .fracture_recovery_428 import reopen_physical_children
        reopen_physical_children(self, ordered_nodes, recovery)
        for node in ordered_nodes:
            context = recovery.get(node['microtask_id'])
            if context is not None:
                node['physical_retry'] = context
                if node['role'] == 'assembly' and not node.get('fracture_context'):
                    # Assembly can repair its assigned implementation fragments;
                    # test ownership stays with final_test and sealed tests persist.
                    node['deliverables'] = sorted(set(node['deliverables']).union(*(
                        set(prior['deliverables']) for prior in ordered_nodes
                        if prior['role'] == 'implementation' and prior['microtask_id'] in node['ancestors'])))
        now = float(self.clock())
        preserved_ids = set(preserve_pending_retry_ids or ())

        # 1. Supersede any nodes and batches from an older generation (changed classification/WBS/SRS)
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
            stale_batches = conn.execute(
                "SELECT batch_id, job_id FROM microtask428_batches "
                "WHERE task_id=? AND plan_generation_sha256<>? AND status<>'SUPERSEDED'",
                (task_id, gen_sha),
            ).fetchall()
            for sb in stale_batches:
                if sb["job_id"]:
                    stale_job_ids.append(sb["job_id"])
                conn.execute(
                    "UPDATE microtask428_batches SET status='SUPERSEDED',updated_at=? WHERE batch_id=?",
                    (now, sb["batch_id"]),
                )
            conn.execute(
                "DELETE FROM microtask428_file_locks WHERE task_id=? AND plan_generation_sha256<>?",
                (task_id, gen_sha),
            )
        for stale_jid in dict.fromkeys(stale_job_ids):
            self._cancel_stale_board_job(stale_jid)

        # 1b. Auto-commit any DISPATCHED swarm batch whose board job completed on JobStore with verified cleanup
        with self.journal._write() as conn:
            gen_batch_rows = conn.execute(
                "SELECT * FROM microtask428_batches WHERE task_id=? AND plan_generation_sha256=?",
                (task_id, gen_sha),
            ).fetchall()
        existing_batches_by_id = {r["batch_id"]: dict(r) for r in gen_batch_rows}
        for ab_row in gen_batch_rows:
            if ab_row["status"] != "DISPATCHED" or not ab_row["job_id"]:
                continue
            b_jid = ab_row["job_id"]
            batch_board_output = None
            with self.store._connection() as sconn:
                bjob = self.store._get(sconn, b_jid)
                if bjob["status"] == "COMPLETED":
                    cleanup = sconn.execute(
                        "SELECT cleared_at FROM pipeline_execution_cleanup "
                        "WHERE job_id=? AND attempt_id=? AND fencing_token=?",
                        (b_jid, bjob["attempt_id"], bjob["fencing_token"]),
                    ).fetchone()
                    if cleanup is not None and cleanup["cleared_at"] is not None:
                        batch_board_output = bjob["output"]
            if isinstance(batch_board_output, (Mapping, list)):
                return self.complete_swarm_batch(task_id, ab_row["batch_id"], batch_board_output)

        # 2. Ensure current generation rows exist and sync completed board jobs in topological order
        completed_by_id: dict[str, dict[str, Any]] = {}
        existing_by_id: dict[str, dict[str, Any]] = {}
        for node in ordered_nodes:
            mt_id = node["microtask_id"]
            node_key = f"{gen_sha[:32]}::{mt_id}"
            if node.get('fracture_join'):
                joined = self._materialize_fracture_join(task_id, gen_sha, node, completed_by_id, now)
                if joined is not None:
                    completed_by_id[mt_id] = joined
                continue
            options = five_model_options(catalog, node["task_types"], node["complexity"])
            candidates = [opt["model_id"] for opt in options if opt["meets_floor"]]
            if not candidates:
                raise ValueError(f"No eligible profiles meet the floor for microtask {mt_id}")
            if self.attempt_accounting is not None:
                self.attempt_accounting.ensure_lineage(
                    node["attempt_lineage_id"],
                    complexity=int(node["complexity"]),
                )

            with self.journal._write() as conn:
                existing = conn.execute(
                    "SELECT * FROM microtask428_nodes WHERE node_key=?",
                    (node_key,),
                ).fetchone()
            if existing is not None:
                prior_context = json.loads(existing['node_json']).get('physical_retry')
                if node.get('physical_retry') is not None and prior_context != node['physical_retry']:
                    prior_job = self.store.get(existing['job_id']) if existing['job_id'] else None
                    if prior_job is None or prior_job['status'] in ('COMPLETED', 'FAILED', 'BLOCKED'):
                        # Replace the projection only; immutable jobs, outputs,
                        # verifier receipts and lineage counters are preserved.
                        existing = None
            if existing is not None:
                existing_by_id[mt_id] = dict(existing)

            expected_pred_hashes = (
                {dep: output['artifact_sha256'] for dep, output in sorted(self._predecessors(node, completed_by_id).items())}
                if all(dep in completed_by_id for dep in node["depends_on"])
                else None
            )

            if existing is not None and existing["status"] == "COMPLETED" and existing["output_json"]:
                existing_out = json.loads(existing["output_json"])
                if (
                    expected_pred_hashes is not None
                    and existing_out.get("predecessor_artifact_hashes", {}) == expected_pred_hashes
                ):
                    with self.journal._write() as conn:
                        self._release_node_file_locks(conn, node_key)
                    completed_by_id[mt_id] = existing_out
                    self._sync_fracture_completion(node, existing_out)
                    continue

            if existing is not None and existing["job_id"]:
                done = self._check_board_completion(existing["job_id"], node)
                if (
                    done is not None
                    and expected_pred_hashes is not None
                    and done["validated"].get("predecessor_artifact_hashes", {}) == expected_pred_hashes
                ):
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
                        self._release_node_file_locks(conn, node_key)
                    completed_by_id[mt_id] = val
                    self._sync_fracture_completion(node, val)
                    continue

        # 3. Partition remaining nodes into held/waiting vs already-dispatched vs dependency-ready
        ready_nodes: list[dict[str, Any]] = []
        candidates_by_mt: dict[str, list[str]] = {}
        for node in ordered_nodes:
            mt_id = node["microtask_id"]
            if mt_id in completed_by_id or node.get('fracture_join'):
                continue
            node_key = f"{gen_sha[:32]}::{mt_id}"
            lstate = None
            node_for_route = dict(node)
            pending_approval = (state.get('microtask_pivot_approvals') or {}).get(node['attempt_lineage_id'])
            if pending_approval and not pending_approval.get('owner_approval'):
                node_for_route['needs_owner_approval'] = True
                node_for_route['pending_pivot_approval'] = pending_approval
            if self.attempt_accounting is not None:
                lstate = self.attempt_accounting.ensure_lineage(
                    node["attempt_lineage_id"],
                    complexity=int(node["complexity"]),
                )
                eff_complexity = (int(node['complexity']) if node.get('fracture_context') else
                                  max(int(node["complexity"]), int(lstate.get("floor") or node["complexity"])))
                child_models = lstate.get("fracture_child_models") or {}
                pivot_model = child_models.get(node["attempt_lineage_id"], lstate.get("next_model"))
                if not pivot_model and lstate.get("pivots"):
                    last_prop = lstate["pivots"][-1].get("proposal") or {}
                    pivot_model = last_prop.get("next_model")
                if lstate.get("pivots") and not node.get('fracture_context'):
                    node_for_route["task_types"] = lstate["pivots"][-1]["proposal"]["task_types"]
                    proposal = lstate["pivots"][-1]["proposal"]
                    if proposal.get("selected_profile_id"):
                        pivot_model = proposal["selected_profile_id"]
                    context_provider = getattr(self, "pivot_context_provider", None)
                    if context_provider is not None:
                        context = context_provider(lstate["root"])
                        if context is not None:
                            node_for_route["pivot_context"] = context
                node_for_route["effective_complexity"] = eff_complexity
                if node.get('fracture_context'):
                    # Exact profile was selected and accepted with this graph.
                    # capture_lineage_budget rechecks all compiled-row bindings.
                    pivot_model = node['selected_profile_id']
                if pivot_model:
                    node_for_route["pivot_model"] = pivot_model

            route_info = resolve_microtask_route_tier(node_for_route, catalog)
            candidates = route_info["candidate_profiles"]
            candidates_by_mt[mt_id] = candidates
            enriched_node = {
                **node_for_route,
                "provider_family": route_info["provider_family"],
                "routed_profile_id": route_info["routed_profile_id"],
                "routed_model": route_info["model"],
                "routed_effort": route_info["reasoning_effort"],
                "swarm_profile": route_info["swarm_profile"],
                "file_footprint": extract_microtask_files(node),
            }

            if mt_id in preserved_ids and mt_id in existing_by_id:
                continue

            deps_ready = all(dep in completed_by_id for dep in node["depends_on"])
            if enriched_node["needs_owner_approval"]:
                with self.journal._write() as conn:
                    self._release_node_file_locks(conn, node_key)
                    self._upsert_node_row(
                        conn,
                        node_key=node_key,
                        task_id=task_id,
                        mt_id=mt_id,
                        gen_sha=gen_sha,
                        node=enriched_node,
                        candidates=candidates,
                        status="HOLD_OWNER_APPROVAL",
                        job_id=None,
                        output_obj=None,
                        artifact_sha256=None,
                        now=now,
                    )
                continue

            if not deps_ready:
                with self.journal._write() as conn:
                    self._release_node_file_locks(conn, node_key)
                    self._upsert_node_row(
                        conn,
                        node_key=node_key,
                        task_id=task_id,
                        mt_id=mt_id,
                        gen_sha=gen_sha,
                        node=enriched_node,
                        candidates=candidates,
                        status="WAITING_ON_DEPENDENCIES",
                        job_id=None,
                        output_obj=None,
                        artifact_sha256=None,
                        now=now,
                    )
                continue

            if lstate is not None and lstate["stage"] in ("PIVOT_RESEARCH", "LOCKED"):
                with self.journal._write() as conn:
                    self._release_node_file_locks(conn, node_key)
                    self._upsert_node_row(
                        conn,
                        node_key=node_key,
                        task_id=task_id,
                        mt_id=mt_id,
                        gen_sha=gen_sha,
                        node=enriched_node,
                        candidates=candidates,
                        status="HELD",
                        job_id=None,
                        output_obj=None,
                        artifact_sha256=None,
                        now=now,
                    )
                continue

            existing = existing_by_id.get(mt_id)
            if (
                existing is not None
                and existing["status"] in ("DISPATCHED", "WAITING_FOR_NATIVE_CLEANUP")
                and existing["job_id"]
            ):
                existing_meta = json.loads(existing["node_json"]) if existing["node_json"] else {}
                existing_batch_id = existing_meta.get("batch_id")
                existing_batch_row = (
                    existing_batches_by_id.get(existing_batch_id) if existing_batch_id else None
                )
                with self.store._connection() as sconn:
                    board_job = self.store._get(sconn, existing["job_id"])
                if board_job["status"] in ("FAILED", "BLOCKED"):
                    with self.journal._write() as conn:
                        self._release_node_file_locks(conn, node_key)
                        self._upsert_node_row(
                            conn,
                            node_key=node_key,
                            task_id=task_id,
                            mt_id=mt_id,
                            gen_sha=gen_sha,
                            node=existing_meta or enriched_node,
                            candidates=candidates,
                            status="HELD",
                            job_id=existing["job_id"],
                            output_obj=None,
                            artifact_sha256=None,
                            now=now,
                        )
                    continue
                if not use_swarm_batches and board_job["status"] == "COMPLETED":
                    with self.journal._write() as conn:
                        self._acquire_node_file_locks(
                            conn,
                            task_id=task_id,
                            microtask_id=mt_id,
                            node_key=node_key,
                            gen_sha=gen_sha,
                            batch_id=existing_batch_id,
                            slot_id=existing_meta.get("slot_id"),
                            provider_family=existing_meta.get("provider_family"),
                            locked_files=existing_meta.get("locked_files")
                            or enriched_node["file_footprint"],
                            now=now,
                        )
                        self._upsert_node_row(
                            conn,
                            node_key=node_key,
                            task_id=task_id,
                            mt_id=mt_id,
                            gen_sha=gen_sha,
                            node=existing_meta or enriched_node,
                            candidates=candidates,
                            status="WAITING_FOR_NATIVE_CLEANUP",
                            job_id=existing["job_id"],
                            output_obj=None,
                            artifact_sha256=None,
                            now=now,
                        )
                    continue
                if use_swarm_batches:
                    if (
                        existing_batch_row is not None
                        and existing_batch_row["status"] == "DISPATCHED"
                        and existing_batch_row["job_id"] == existing["job_id"]
                    ):
                        with self.journal._write() as conn:
                            self._acquire_node_file_locks(
                                conn,
                                task_id=task_id,
                                microtask_id=mt_id,
                                node_key=node_key,
                                gen_sha=gen_sha,
                                batch_id=existing_batch_id,
                                slot_id=existing_meta.get("slot_id"),
                                provider_family=existing_meta.get("provider_family"),
                                locked_files=existing_meta.get("locked_files")
                                or enriched_node["file_footprint"],
                                now=now,
                            )
                        continue
                else:
                    if existing_batch_row is None or existing_batch_row["job_id"] is None:
                        with self.journal._write() as conn:
                            self._acquire_node_file_locks(
                                conn,
                                task_id=task_id,
                                microtask_id=mt_id,
                                node_key=node_key,
                                gen_sha=gen_sha,
                                batch_id=existing_batch_id,
                                slot_id=existing_meta.get("slot_id"),
                                provider_family=existing_meta.get("provider_family"),
                                locked_files=existing_meta.get("locked_files")
                                or enriched_node["file_footprint"],
                                now=now,
                            )
                        continue

            with self.journal._write() as conn:
                self._release_node_file_locks(conn, node_key)
            ready_nodes.append(enriched_node)

        # 4. Pack conflict-colored provider wave (Case B disjoint batching vs Case C cross-slot file locking)
        with self.journal._write() as conn:
            active_lock_rows = conn.execute(
                "SELECT file_path, microtask_id FROM microtask428_file_locks"
            ).fetchall()
        active_locks = {r["file_path"]: r["microtask_id"] for r in active_lock_rows}

        wave = pack_conflict_colored_wave(
            ready_nodes,
            catalog,
            active_locked_files=active_locks,
            task_id=task_id,
            plan_generation_sha256=gen_sha,
            batch_seq_offset=len(existing_batches_by_id),
        )

        # 5. Record Case C nodes held in WAITING_ON_FILE_LOCK (job_id=None)
        for held_node in wave["waiting_on_lock_nodes"]:
            mt_id = held_node["microtask_id"]
            node_key = f"{gen_sha[:32]}::{mt_id}"
            with self.journal._write() as conn:
                self._release_node_file_locks(conn, node_key)
                self._upsert_node_row(
                    conn,
                    node_key=node_key,
                    task_id=task_id,
                    mt_id=mt_id,
                    gen_sha=gen_sha,
                    node=held_node,
                    candidates=held_node["candidate_profiles"],
                    status="WAITING_ON_FILE_LOCK",
                    job_id=None,
                    output_obj=None,
                    artifact_sha256=None,
                    now=now,
                )

        # 6. Dispatch admitted wave (either as slot-level MICROTASK_SWARM_BATCH jobs or per-node jobs)
        admitted_by_id = {n["microtask_id"]: n for n in wave["admitted_nodes"]}
        batch_job_by_batch_id: dict[str, dict[str, Any]] = {}

        if use_swarm_batches:
            for batch in wave["batches"]:
                pred_by_mt = {
                    mt_id: {
                        dep: completed_by_id[dep]
                        for dep in admitted_by_id[mt_id]["depends_on"]
                    }
                    for mt_id in batch["microtask_ids"]
                }
                bjob = self._submit_board_job_for_swarm_batch(
                    task_id,
                    gen_sha,
                    batch,
                    state,
                    catalog,
                    limit,
                    pred_by_mt,
                )
                batch_job_by_batch_id[batch["batch_id"]] = bjob
                with self.journal._write() as conn:
                    conn.execute(
                        "INSERT INTO microtask428_batches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(batch_id) DO UPDATE SET status=excluded.status,job_id=excluded.job_id,"
                        "microtask_ids_json=excluded.microtask_ids_json,subagents_json=excluded.subagents_json,"
                        "locked_files_json=excluded.locked_files_json,batch_json=excluded.batch_json,"
                        "updated_at=excluded.updated_at",
                        (
                            batch["batch_id"],
                            task_id,
                            gen_sha,
                            batch["provider_family"],
                            batch["slot_index"],
                            batch["slot_id"],
                            batch["max_agents_per_slot"],
                            batch["max_nesting_depth"],
                            json.dumps(batch["microtask_ids"]),
                            json.dumps(batch["subagents"], sort_keys=True),
                            json.dumps(batch["locked_files"]),
                            json.dumps(batch, sort_keys=True),
                            "DISPATCHED",
                            bjob["job_id"],
                            now,
                        ),
                    )
        else:
            for batch in wave["batches"]:
                with self.journal._write() as conn:
                    conn.execute(
                        "INSERT INTO microtask428_batches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(batch_id) DO UPDATE SET status=excluded.status,"
                        "microtask_ids_json=excluded.microtask_ids_json,subagents_json=excluded.subagents_json,"
                        "locked_files_json=excluded.locked_files_json,batch_json=excluded.batch_json,"
                        "updated_at=excluded.updated_at",
                        (
                            batch["batch_id"],
                            task_id,
                            gen_sha,
                            batch["provider_family"],
                            batch["slot_index"],
                            batch["slot_id"],
                            batch["max_agents_per_slot"],
                            batch["max_nesting_depth"],
                            json.dumps(batch["microtask_ids"]),
                            json.dumps(batch["subagents"], sort_keys=True),
                            json.dumps(batch["locked_files"]),
                            json.dumps(batch, sort_keys=True),
                            "DISPATCHED",
                            None,
                            now,
                        ),
                    )

        compiled_by_id = {n["microtask_id"]: n for n in ordered_nodes}
        for admitted_node in wave["admitted_nodes"]:
            mt_id = admitted_node["microtask_id"]
            node_key = f"{gen_sha[:32]}::{mt_id}"
            candidates = admitted_node["candidate_profiles"]
            pred_outputs = self._predecessors(admitted_node, completed_by_id)

            if use_swarm_batches:
                bjob = batch_job_by_batch_id[admitted_node["batch_id"]]
                job_id = bjob["job_id"]
                desired_status = "HELD" if bjob["status"] in ("FAILED", "BLOCKED") else "DISPATCHED"
                with self.journal._write() as conn:
                    if desired_status == "DISPATCHED":
                        self._acquire_node_file_locks(
                            conn,
                            task_id=task_id,
                            microtask_id=mt_id,
                            node_key=node_key,
                            gen_sha=gen_sha,
                            batch_id=admitted_node["batch_id"],
                            slot_id=admitted_node["slot_id"],
                            provider_family=admitted_node["provider_family"],
                            locked_files=admitted_node["locked_files"],
                            now=now,
                        )
                    else:
                        self._release_node_file_locks(conn, node_key)
                    self._upsert_node_row(
                        conn,
                        node_key=node_key,
                        task_id=task_id,
                        mt_id=mt_id,
                        gen_sha=gen_sha,
                        node=admitted_node,
                        candidates=candidates,
                        status=desired_status,
                        job_id=job_id,
                        output_obj=None,
                        artifact_sha256=None,
                        now=now,
                    )
            else:
                execution_node = dict(compiled_by_id[mt_id])
                for key in ('effective_complexity', 'task_types', 'pivot_model', 'pivot_context', 'physical_retry'):
                    if key in admitted_node:
                        execution_node[key] = deepcopy(admitted_node[key])
                try:
                    board_job = self._submit_board_job_for_node(
                        task_id, gen_sha, execution_node, state, catalog, limit, candidates, pred_outputs)
                except LineageBudgetHold as hold:
                    with self.journal._write() as conn:
                        self._release_node_file_locks(conn, node_key)
                        self._upsert_node_row(conn, node_key=node_key, task_id=task_id, mt_id=mt_id,
                            gen_sha=gen_sha, node=dict(admitted_node, budget_hold_reason=hold.reason),
                            candidates=candidates, status='HELD_BUDGET', job_id=None, output_obj=None,
                            artifact_sha256=None, now=now)
                    continue
                job_id = board_job["job_id"]
                if board_job["status"] in ("FAILED", "BLOCKED"):
                    desired_status = "HELD"
                elif board_job["status"] == "COMPLETED":
                    done = self._check_board_completion(job_id, compiled_by_id[mt_id])
                    if done is not None:
                        val = done["validated"]
                        with self.journal._write() as conn:
                            self._release_node_file_locks(conn, node_key)
                            self._upsert_node_row(
                                conn,
                                node_key=node_key,
                                task_id=task_id,
                                mt_id=mt_id,
                                gen_sha=gen_sha,
                                node=admitted_node,
                                candidates=candidates,
                                status="COMPLETED",
                                job_id=job_id,
                                output_obj=val,
                                artifact_sha256=val["artifact_sha256"],
                                now=now,
                            )
                        completed_by_id[mt_id] = val
                        self._sync_fracture_completion(compiled_by_id[mt_id], val)
                        continue
                    desired_status = "WAITING_FOR_NATIVE_CLEANUP"
                else:
                    desired_status = "DISPATCHED"

                with self.journal._write() as conn:
                    if desired_status in ("DISPATCHED", "WAITING_FOR_NATIVE_CLEANUP"):
                        self._acquire_node_file_locks(
                            conn,
                            task_id=task_id,
                            microtask_id=mt_id,
                            node_key=node_key,
                            gen_sha=gen_sha,
                            batch_id=admitted_node["batch_id"],
                            slot_id=admitted_node["slot_id"],
                            provider_family=admitted_node["provider_family"],
                            locked_files=admitted_node["locked_files"],
                            now=now,
                        )
                    else:
                        self._release_node_file_locks(conn, node_key)
                    self._upsert_node_row(
                        conn,
                        node_key=node_key,
                        task_id=task_id,
                        mt_id=mt_id,
                        gen_sha=gen_sha,
                        node=admitted_node,
                        candidates=candidates,
                        status=desired_status,
                        job_id=job_id,
                        output_obj=None,
                        artifact_sha256=None,
                        now=now,
                    )

        return self.board_status(task_id)

    def materialize(self, task_id: str) -> dict[str, Any]:
        """Compile, reconcile, and dispatch ready microtask nodes for `task_id`."""
        return self._materialize_internal(task_id, use_swarm_batches=self.swarm_batch_mode)

    def dispatch_swarm_batches(self, task_id: str) -> dict[str, Any]:
        """Compile, pack conflict-colored provider waves, and dispatch slot-level `MICROTASK_SWARM_BATCH` jobs."""
        return self._materialize_internal(task_id, use_swarm_batches=True)

    def complete_swarm_batch(
        self,
        task_id: str,
        batch_id: str,
        subagent_outputs: Mapping[str, Any] | list[Any],
    ) -> dict[str, Any]:
        """Commit a completed intra-slot swarm batch with per-microtask validation and failure isolation.

        In a batch of `N` microtasks where `k` succeed and `N - k` fail validation:
        - The `k` valid microtasks transition immediately to `COMPLETED`, release their file locks in
          `microtask428_file_locks`, and unlock their downstream dependents and waiting Case C tasks.
        - The `N - k` failed microtasks record individual `AttemptLedger` quality failures (10/20/30 accounting),
          release their file locks, and transition to `PENDING_RETRY` (or `HELD` at 10/20/30 boundaries)
          without rolling back or invalidating the `k` completed siblings.
        """
        _id(task_id)
        _id(batch_id)

        now = float(self.clock())
        with self.journal._write() as conn:
            row = self.journal._read(conn, task_id)
            state = json.loads(row["state_json"])
            catalog = json.loads(row["catalog_json"])
            gen_sha = self._plan_generation_sha256(state, catalog)
            batch_row = conn.execute(
                "SELECT * FROM microtask428_batches WHERE batch_id=? AND task_id=? AND plan_generation_sha256=?",
                (batch_id, task_id, gen_sha),
            ).fetchone()
            if batch_row is None:
                raise ValueError(f"Unknown or superseded swarm batch: {batch_id}")
            if batch_row["status"] != "DISPATCHED":
                raise ValueError(
                    f"Swarm batch {batch_id} is not in DISPATCHED state (current: {batch_row['status']})"
                )
            batch_desc = json.loads(batch_row["batch_json"])
            node_rows = conn.execute(
                "SELECT * FROM microtask428_nodes WHERE task_id=? AND plan_generation_sha256=?",
                (task_id, gen_sha),
            ).fetchall()

        validated_batch = validate_swarm_batch_stage_output(
            batch_desc,
            subagent_outputs,
            allow_partial_failures=True,
        )
        raw_map = validated_batch["subagent_outputs"]
        nodes_by_id = {r["microtask_id"]: dict(r) for r in node_rows}
        completed_hashes_by_id = {
            r["microtask_id"]: r["artifact_sha256"]
            for r in node_rows
            if r["status"] == "COMPLETED" and r["artifact_sha256"]
        }

        succeeded_ids: list[str] = []
        failed_ids: set[str] = set()
        failure_errors: dict[str, str] = {}

        for sub in batch_desc["subagents"]:
            mt_id = sub["microtask_id"]
            if mt_id not in nodes_by_id:
                raise ValueError(f"Batch microtask {mt_id} not found in board nodes")
            nrow = nodes_by_id[mt_id]
            node_key = nrow["node_key"]
            node_obj = json.loads(nrow["node_json"])
            lineage_root = nrow["attempt_lineage_id"]
            candidate_model_id = str(
                sub.get("pivot_model")
                or sub.get("model")
                or node_obj.get("routed_model")
                or sub["routed_profile_id"]
            )
            if self.attempt_accounting is not None:
                lstate_cur = self.attempt_accounting.ensure_lineage(
                    lineage_root,
                    complexity=int(node_obj["complexity"]),
                )
                expected_m = (lstate_cur.get("fracture_child_models") or {}).get(
                    lineage_root,
                    lstate_cur.get("next_model"),
                )
                if expected_m and expected_m in {
                    sub.get("pivot_model"),
                    sub.get("model"),
                    sub.get("family"),
                    sub.get("routed_profile_id"),
                    node_obj.get("routed_model"),
                    node_obj.get("routed_profile_id"),
                }:
                    candidate_model_id = str(expected_m)
            model_family = _id(candidate_model_id)
            mt_out = raw_map.get(mt_id)
            if isinstance(mt_out, Mapping) and not isinstance(mt_out, dict):
                mt_out = dict(mt_out)

            fence_digest = digest({"batch_id": batch_id, "microtask_id": mt_id})[:40]
            fence_job_id = _id(f"swbfj-{fence_digest}")
            fence_attempt_id = _id(f"swbfa-{fence_digest}")

            try:
                if not isinstance(mt_out, dict):
                    raise ValueError(f"Missing or non-object subagent output for microtask {mt_id}")
                validated = validate_microtask_execution_output(node_obj, mt_out)
                validated["profile_id"] = sub["routed_profile_id"]
                validated["routed_model"] = sub["model"]
                validated["routed_effort"] = sub["reasoning_effort"]
                validated["predecessor_artifact_hashes"] = {
                    dep: completed_hashes_by_id[dep]
                    for dep in sorted(node_obj["depends_on"])
                    if dep in completed_hashes_by_id
                }
                if self.attempt_accounting is not None:
                    self.attempt_accounting.start_board_attempt(
                        fence_job_id,
                        fence_attempt_id,
                        1,
                        lineage_root=lineage_root,
                        member_id=lineage_root,
                        model_family=model_family,
                        complexity=int(node_obj["complexity"]),
                    )
                    self.attempt_accounting.record_board_outcome(
                        fence_job_id,
                        fence_attempt_id,
                        1,
                        category="success",
                        evidence_sha256=validated["artifact_sha256"],
                    )
                with self.journal._write() as conn:
                    self._release_node_file_locks(conn, node_key)
                    conn.execute(
                        "UPDATE microtask428_nodes SET status='COMPLETED',output_json=?,artifact_sha256=?,updated_at=? "
                        "WHERE node_key=?",
                        (
                            json.dumps(validated, sort_keys=True),
                            validated["artifact_sha256"],
                            now,
                            node_key,
                        ),
                    )
                completed_hashes_by_id[mt_id] = validated["artifact_sha256"]
                succeeded_ids.append(mt_id)
            except ValueError as exc:
                failed_ids.add(mt_id)
                failure_errors[mt_id] = str(exc)
                err_sha = digest(
                    {
                        "batch_id": batch_id,
                        "microtask_id": mt_id,
                        "error": str(exc),
                        "raw_output": mt_out,
                    }
                )
                failed_status = "PENDING_RETRY"
                if self.attempt_accounting is not None:
                    self.attempt_accounting.start_board_attempt(
                        fence_job_id,
                        fence_attempt_id,
                        1,
                        lineage_root=lineage_root,
                        member_id=lineage_root,
                        model_family=model_family,
                        complexity=int(node_obj["complexity"]),
                    )
                    lstate = self.attempt_accounting.record_board_outcome(
                        fence_job_id,
                        fence_attempt_id,
                        1,
                        category="quality_failure",
                        evidence_sha256=err_sha,
                    )
                    if lstate["stage"] in ("PIVOT_RESEARCH", "LOCKED"):
                        failed_status = "HELD"
                with self.journal._write() as conn:
                    self._release_node_file_locks(conn, node_key)
                    conn.execute(
                        "UPDATE microtask428_nodes SET status=?,job_id=NULL,output_json=NULL,artifact_sha256=NULL,updated_at=? "
                        "WHERE node_key=?",
                        (failed_status, now, node_key),
                    )

        if not failed_ids:
            batch_status = "COMPLETED"
        elif succeeded_ids:
            batch_status = "PARTIAL_COMPLETED"
        else:
            batch_status = "FAILED"

        with self.journal._write() as conn:
            conn.execute(
                "UPDATE microtask428_batches SET status=?,updated_at=? WHERE batch_id=?",
                (batch_status, now, batch_id),
            )
        self._cancel_stale_board_job(batch_row["job_id"])

        snap = self._materialize_internal(
            task_id,
            use_swarm_batches=True,
            preserve_pending_retry_ids=failed_ids,
        )
        snap["last_completed_batch"] = {
            "batch_id": batch_id,
            "status": batch_status,
            "completed_microtask_ids": succeeded_ids,
            "failed_microtask_ids": sorted(failed_ids),
            "failure_errors": failure_errors,
        }
        return snap

    def active_file_locks(self, task_id: str | None = None) -> list[dict[str, Any]]:
        """Return currently held cross-slot file locks from `microtask428_file_locks`."""
        with self.journal._write() as conn:
            if task_id is not None:
                _id(task_id)
                rows = conn.execute(
                    "SELECT * FROM microtask428_file_locks WHERE task_id=? ORDER BY file_path",
                    (task_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM microtask428_file_locks ORDER BY file_path"
                ).fetchall()
        return [
            {
                "file_path": r["file_path"],
                "task_id": r["task_id"],
                "microtask_id": r["microtask_id"],
                "node_key": r["node_key"],
                "plan_generation_sha256": r["plan_generation_sha256"],
                "batch_id": r["batch_id"],
                "slot_id": r["slot_id"],
                "provider_family": r["provider_family"],
                "acquired_at": r["acquired_at"],
            }
            for r in rows
        ]

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
        if self.fracture_planning is not None:
            generation, nodes, _, _, _ = self._compile(task_id)
            matches = [node for node in nodes if node['microtask_id'] == microtask_id and node.get('fracture_context')]
            if matches:
                node = matches[0]
                _text(notes, 'Owner notes', 8000) if notes else None
                context = node['fracture_context']
                receipt_id = 'fractureowner428-' + digest(dict(task_id=task_id, microtask_id=microtask_id,
                    generation=generation, graph_sha256=context['graph_sha256'], notes=notes))[:40]
                self.fracture_runtime.approve_fracture_child(context['lineage_root'], microtask_id, receipt_id)
                return self.materialize(task_id)
        expected_version = state["journal_version"]
        lineage = f'{task_id}.mt.{microtask_id}'
        pending = (state.get('microtask_pivot_approvals') or {}).get(lineage)
        if pending is not None and pending.get('owner_approval'):
            return self.materialize(task_id)
        if pending is not None and not pending.get('owner_approval'):
            _text(notes, 'Owner notes', 8000) if notes else None
            receipt = dict(receipt_id='mtpivotowner428-' + digest(dict(
                request_sha256=pending['request_sha256'], notes=notes))[:40],
                request_sha256=pending['request_sha256'], actor_kind='human_owner', notes=notes)
            def approve_pivot(row):
                current = json.loads(row['state_json'])
                entry = current.get('microtask_pivot_approvals', {}).get(lineage)
                if (current['stage'] != 'MICROTASKS_READY' or entry is None
                        or entry['request_sha256'] != pending['request_sha256']
                        or entry['srs_sha256'] != current['srs_sha256']
                        or entry['microtasks_sha256'] != current['microtasks_sha256']):
                    raise ValueError('Child pivot approval belongs to a stale scope')
                entry['owner_approval'] = receipt
                return current
            self.journal._transition(task_id, expected_version, receipt['receipt_id'], receipt, approve_pivot)
            return self.materialize(task_id)
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
            batch_rows = conn.execute(
                "SELECT * FROM microtask428_batches WHERE task_id=? AND plan_generation_sha256=? ORDER BY slot_index, batch_id",
                (task_id, gen_sha),
            ).fetchall()
            lock_rows = conn.execute(
                "SELECT * FROM microtask428_file_locks WHERE task_id=? AND plan_generation_sha256=? ORDER BY file_path",
                (task_id, gen_sha),
            ).fetchall()
            superseded_count = conn.execute(
                "SELECT count(*) FROM microtask428_nodes WHERE task_id=? AND status='SUPERSEDED'",
                (task_id,),
            ).fetchone()[0]

        nodes = []
        for r in rows:
            node_meta = json.loads(r["node_json"]) if r["node_json"] else {}
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
                    "pending_pivot_approval": node_meta.get("pending_pivot_approval"),
                    "budget_hold_reason": node_meta.get("budget_hold_reason"),
                    "status": r["status"],
                    "job_id": r["job_id"],
                    "batch_id": node_meta.get("batch_id"),
                    "slot_id": node_meta.get("slot_id"),
                    "provider_family": node_meta.get("provider_family"),
                    "subagent_index": node_meta.get("subagent_index"),
                    "routed_profile_id": node_meta.get("routed_profile_id"),
                    "routed_model": node_meta.get("routed_model"),
                    "routed_effort": node_meta.get("routed_effort"),
                    "swarm_profile": node_meta.get("swarm_profile"),
                    "file_footprint": node_meta.get("file_footprint"),
                    "locked_files": node_meta.get("locked_files", []),
                    "blocking_files": node_meta.get("blocking_files", []),
                    "blocking_microtask_ids": node_meta.get("blocking_microtask_ids", []),
                    "artifact_sha256": r["artifact_sha256"],
                    "output": json.loads(r["output_json"]) if r["output_json"] else None,
                }
            )
        batches = [
            {
                "batch_id": br["batch_id"],
                "provider_family": br["provider_family"],
                "slot_index": br["slot_index"],
                "slot_id": br["slot_id"],
                "max_agents_per_slot": br["max_agents_per_slot"],
                "max_nesting_depth": br["max_nesting_depth"],
                "microtask_ids": json.loads(br["microtask_ids_json"]),
                "subagents": json.loads(br["subagents_json"]),
                "locked_files": json.loads(br["locked_files_json"]),
                "status": br["status"],
                "job_id": br["job_id"],
            }
            for br in batch_rows
        ]
        active_locks = [
            {
                "file_path": lr["file_path"],
                "microtask_id": lr["microtask_id"],
                "batch_id": lr["batch_id"],
                "slot_id": lr["slot_id"],
                "provider_family": lr["provider_family"],
            }
            for lr in lock_rows
        ]
        return {
            "schema": "cochem-microtask-board/4.2.8",
            "task_id": task_id,
            "plan_generation_sha256": gen_sha,
            "nodes": nodes,
            "batches": batches,
            "active_file_locks": active_locks,
            "superseded_nodes": superseded_count,
            "all_completed": bool(nodes) and all(n["status"] == "COMPLETED" for n in nodes),
        }
