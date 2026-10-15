"""Simple approved-for-dispatch task execution and artifact validation (`P428-11`).

A `READY` simple task (single task type, complexity 1..3, fits context budget)
materializes into a single Chapter 06 board execution job without going through
legacy fixed chapter scatter. Completion requires:
1. Exact native route matching the task's captured `(task_types, complexity)`
   5-option candidate policy.
2. Verified native execution cleanup (`pipeline_execution_cleanup.cleared_at IS NOT NULL`)
   matching the job's winning `(attempt_id, fencing_token)`.
3. Validated deliverables (each with verified SHA-256 over content), 100% SRS
   requirement coverage, and 100% release criteria verification — never model prose alone.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import time
from typing import Any

from . import routing_store as routes
from .task_routing import digest, five_model_options
from .workflow_428 import _id, _sha, _stage, _text


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_simple_execution_output(
    state: dict[str, Any],
    output: dict[str, Any],
) -> dict[str, Any]:
    """Validate simple-task execution output against SRS requirements, deliverables, and release criteria."""
    _stage(state, "READY")
    if state.get("needs_wbs") is not False:
        raise ValueError("Task requires WBS decomposition and cannot use simple execution")

    expected_keys = {
        "artifact_text",
        "deliverables",
        "requirement_evidence",
        "release_criteria_results",
    }
    if not isinstance(output, dict) or set(output) != expected_keys:
        raise ValueError(
            "Simple execution output requires artifact_text, deliverables, "
            "requirement_evidence, and release_criteria_results"
        )

    artifact_text = _text(output["artifact_text"], "Artifact text", 200000)

    raw_deliverables = output["deliverables"]
    if not isinstance(raw_deliverables, list) or not 1 <= len(raw_deliverables) <= 50:
        raise ValueError("Simple execution requires 1..50 concrete deliverables")

    deliverables_by_name: dict[str, dict[str, str]] = {}
    normalized_deliverables: list[dict[str, str]] = []
    for item in raw_deliverables:
        if not isinstance(item, dict) or set(item) != {"name", "content", "sha256"}:
            raise ValueError("Each deliverable requires name, content, and sha256")
        name = _text(item["name"], "Deliverable name", 256)
        if name in deliverables_by_name:
            raise ValueError(f"Duplicate deliverable name: {name}")
        content = _text(item["content"], "Deliverable content", 200000)
        sha = _sha(item["sha256"])
        if _sha256_text(content) != sha:
            raise ValueError(f"Deliverable {name} sha256 does not match its content")
        entry = {"name": name, "content": content, "sha256": sha}
        deliverables_by_name[name] = entry
        normalized_deliverables.append(entry)

    doc = state.get("document") or {}
    srs_requirements = doc.get("requirements") or []
    expected_req_ids = {req["id"] for req in srs_requirements}
    if not expected_req_ids:
        raise ValueError("Task SRS has no requirements to verify")

    raw_req_ev = output["requirement_evidence"]
    if not isinstance(raw_req_ev, list) or not 1 <= len(raw_req_ev) <= 200:
        raise ValueError("Simple execution requires bounded requirement_evidence")

    covered_reqs: set[str] = set()
    normalized_req_ev: list[dict[str, str]] = []
    for item in raw_req_ev:
        if not isinstance(item, dict) or set(item) != {
            "requirement_id",
            "deliverable_name",
            "verification_evidence",
        }:
            raise ValueError(
                "Each requirement_evidence item requires requirement_id, "
                "deliverable_name, and verification_evidence"
            )
        req_id = _id(item["requirement_id"])
        if req_id not in expected_req_ids or req_id in covered_reqs:
            raise ValueError(f"Unknown or duplicate requirement_id in evidence: {req_id}")
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

    if covered_reqs != expected_req_ids:
        raise ValueError("Simple execution output does not cover every SRS requirement")

    expected_criteria = list(doc.get("release_criteria") or [])
    raw_criteria = output["release_criteria_results"]
    if not isinstance(raw_criteria, list) or len(raw_criteria) != len(expected_criteria):
        raise ValueError("Simple execution must report every SRS release criterion")

    seen_criteria: set[str] = set()
    normalized_criteria: list[dict[str, Any]] = []
    for item in raw_criteria:
        if not isinstance(item, dict) or set(item) != {"criterion", "passed", "evidence"}:
            raise ValueError("Each release_criteria_results item requires criterion, passed, and evidence")
        crit = _text(item["criterion"], "Release criterion", 4000)
        if crit not in expected_criteria or crit in seen_criteria:
            raise ValueError(f"Unknown or duplicate release criterion: {crit}")
        if item["passed"] is not True:
            raise ValueError(f"Release criterion not satisfied: {crit}")
        ev = _text(item["evidence"], "Release criterion evidence", 4000)
        seen_criteria.add(crit)
        normalized_criteria.append({"criterion": crit, "passed": True, "evidence": ev})

    if seen_criteria != set(expected_criteria):
        raise ValueError("Simple execution output omits required release criteria")

    return {
        "artifact_text": artifact_text,
        "artifact_sha256": _sha256_text(artifact_text),
        "deliverables": normalized_deliverables,
        "requirement_evidence": normalized_req_ev,
        "release_criteria_results": normalized_criteria,
    }


class ExecutionRetryHold(ValueError):
    def __init__(self, status):
        super().__init__(status)
        self.status = status


class SimpleTaskExecutionRuntime:
    """Materializes and imports single-node executions for `READY` simple 4.2.8 tasks."""

    def __init__(self, journal, store, *, clock=time.time, artifact_runtime=None, attempt_accounting=None,
                 delivery_runtime=None):
        self.journal = journal
        self.store = store
        self.clock = clock
        self.artifact_runtime = artifact_runtime
        self.attempt_accounting = attempt_accounting
        self.delivery_runtime = delivery_runtime
        with self.journal._write() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS task428_artifacts(
                    artifact_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL UNIQUE,
                    job_id TEXT NOT NULL UNIQUE,
                    profile_id TEXT NOT NULL,
                    srs_sha256 TEXT NOT NULL,
                    artifact_sha256 TEXT NOT NULL,
                    artifact_text TEXT NOT NULL,
                    deliverables_json TEXT NOT NULL,
                    requirement_evidence_json TEXT NOT NULL,
                    release_criteria_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    def build_execution_intent(self, task_id: str) -> tuple[dict[str, Any], dict[str, Any], int | None]:
        _id(task_id)
        with self.journal._write() as conn:
            row = self.journal._read(conn, task_id)
            state = json.loads(row["state_json"])
            catalog = json.loads(row["catalog_json"])
            limit = row["flash_context_limit"]

        _stage(state, "READY")
        if state.get("needs_wbs") is not False:
            raise ValueError("Task requires WBS decomposition and cannot use simple execution")
        classification = state["assessment"]
        tier = classification["complexity"]
        tags = classification["task_types"]
        if type(tier) is not int or not 1 <= tier <= 3 or len(tags) != 1:
            raise ValueError("Simple task execution is restricted to single-type complexity 1..3 tasks")

        options = five_model_options(catalog, tags, tier)
        candidates = [opt["model_id"] for opt in options if opt["meets_floor"]]
        if not candidates:
            raise ValueError("No eligible execution profiles meet the task floor")
        pivot = state.get('execution_pivot')
        if pivot:
            if (pivot['complexity'] != tier or pivot['task_types'] != tags
                    or pivot['selected_profile_id'] not in candidates):
                raise ValueError('Simple execution pivot does not meet its captured reasoning floor')
            candidates = [pivot['selected_profile_id']]

        intent = {
            "schema": "cochem-planning-intent/4.2.8",
            "action": "model_stage",
            "stage": "SIMPLE_EXECUTION",
            "task_id": task_id,
            "version": row["version"],
            "state_sha256": digest(state),
            "catalog_sha256": digest(catalog),
            "srs_sha256": state["srs_sha256"],
            "complexity": tier,
            "task_types": tags,
            "candidate_profiles": candidates,
            "task": state,
            "execution_authorized": True,
            "prompt_rule": (
                "Execute the approved simple task and return verified deliverables, "
                "requirement_evidence, and release_criteria_results."
            ),
        }
        if pivot:
            intent['attempt_lineage_id'] = pivot['lineage_root']
        feedback = self.artifact_runtime.retry_feedback(task_id) if self.artifact_runtime else None
        if feedback:
            if self.attempt_accounting is None:
                raise ExecutionRetryHold('WAITING_FOR_FAILURE_ACCOUNTING')
            prior = self.store.get(feedback['producer_job_id'])
            with self.attempt_accounting.ledger._write() as conn:
                accounted = conn.execute('SELECT status,staged_outcome FROM attempt428_outbox '
                    'WHERE job_id=? AND attempt_id=? AND fencing_token=?',
                    (prior['job_id'], prior['attempt_id'], prior['fencing_token'])).fetchone()
            if (accounted is None or accounted['status'] != 'RECONCILED'
                    or accounted['staged_outcome'] != 'quality_failure'):
                raise ExecutionRetryHold('WAITING_FOR_FAILURE_ACCOUNTING')
            lineage = self.attempt_accounting.ledger.status(feedback['lineage_root'])
            if lineage['stage'] != 'READY' or lineage['research_due'] or lineage['failures'] >= 30:
                raise ExecutionRetryHold('EXECUTION_LINEAGE_' + lineage['stage'])
            intent['physical_retry'] = deepcopy(feedback)
        return intent, catalog, limit

    def materialize(self, task_id: str) -> dict[str, Any]:
        """Atomically create or return the single board execution job for a `READY` simple task."""
        from .planning_gateway import prompt_contract, scoped_policy

        intent, catalog, limit = self.build_execution_intent(task_id)
        policy = scoped_policy(self.store.routing_policy, intent, catalog)
        identity = digest(intent)
        root_id = "exec428-" + identity[:40]
        job_id = "exec428-node-" + identity[:40]
        payload = {
            "workflow_type": "planning428",
            "execution_role": "simple_execution",
            "planning_intent": intent,
            "task_catalog": catalog,
            "flash_context_limit": limit,
        }
        if self.artifact_runtime is not None:
            payload['execution_context'] = self.artifact_runtime.execution_context(payload)
        prompt_contract(payload)
        if self.attempt_accounting is not None:
            from .planning_outcomes_428 import PlanningOutcomeRuntime
            self.attempt_accounting.ensure_lineage(PlanningOutcomeRuntime.lineage_for_job(task_id, payload),
                                                   complexity=intent['complexity'])
        with self.store._write() as conn:
            existing = conn.execute(
                "SELECT job_id FROM pipeline_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
            if existing:
                prior = self.store._get(conn, job_id)
                if prior["payload"] != payload:
                    raise ValueError("Existing simple execution job has different immutable input")
                return prior
            from .planning_budgets_428 import capture_lineage_budget
            budget = (capture_lineage_budget(conn, job_id, payload, policy,
                attempt_ledger=self.attempt_accounting) if self.attempt_accounting is not None else None)
            self.store._insert(
                conn,
                root_id,
                root_id,
                None,
                "MACRO_PLANNING_REQUEST",
                "IN_PROGRESS",
                {"workflow_type": "planning428", "execution_role": "simple_execution", "intent_sha256": identity},
            )
            routes.capture_workflow(conn, root_id, policy, max_dispatches=budget.max_dispatches if budget else None)
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
                "SIMPLE_EXECUTION_SUBMITTED",
                task_id=task_id,
                intent_sha256=identity,
            )
            return self.store._get(conn, job_id)

    def get_artifact(self, task_id: str) -> dict[str, Any] | None:
        _id(task_id)
        with self.journal._write() as conn:
            row = conn.execute(
                "SELECT * FROM task428_artifacts WHERE task_id=?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        with self.journal._write() as conn:
            state = json.loads(self.journal._read(conn, task_id)['state_json'])
        physical = (state.get('execution_artifact') or {}).get('physical_verification')
        delivery = (state.get('execution_artifact') or {}).get('delivery')
        return {
            "schema": "cochem-task-artifact-manifest/4.2.8",
            "artifact_id": row["artifact_id"],
            "task_id": row["task_id"],
            "job_id": row["job_id"],
            "profile_id": row["profile_id"],
            "srs_sha256": row["srs_sha256"],
            "artifact_sha256": row["artifact_sha256"],
            "artifact_text": row["artifact_text"],
            "deliverables": json.loads(row["deliverables_json"]),
            "requirement_evidence": json.loads(row["requirement_evidence_json"]),
            "release_criteria_results": json.loads(row["release_criteria_json"]),
            "verification_status": "verified",
            "physical_verification": physical,
            "delivery": delivery,
            "verification_scope": ('executed_requirement_tests' if physical and
                physical['output']['verification_kind'] == 'coding_green' else 'content_integrity'),
            "external_actions_verified": False,
            "original_repository_integration": delivery.get('original_repository_integration') if delivery
                else physical.get('integration_status') if physical else 'NOT_VERIFIED',
        }

    def _import_completed_execution(self, task_id: str, job: dict[str, Any], physical=None, delivery=None) -> dict[str, Any] | None:
        from .planning_gateway import validate_stage_output

        job_id = job["job_id"]
        with self.store._connection() as conn:
            fresh = self.store._get(conn, job_id)
            if fresh["status"] != "COMPLETED":
                return None
            cleanup = conn.execute(
                "SELECT cleared_at FROM pipeline_execution_cleanup "
                "WHERE job_id=? AND attempt_id=? AND fencing_token=?",
                (job_id, fresh["attempt_id"], fresh["fencing_token"]),
            ).fetchone()
            if cleanup is None or cleanup["cleared_at"] is None:
                return None
            profile_id = validate_stage_output(fresh["payload"], fresh["output"], fresh["route"])
            validated = validate_simple_execution_output(
                fresh["payload"]["planning_intent"]["task"],
                fresh["output"],
            )

        intent = fresh["payload"]["planning_intent"]
        expected_version = intent["version"]
        artifact_id = "art428-" + digest({"task_id": task_id, "job_id": job_id, "sha256": validated["artifact_sha256"]})[:40]
        now = float(self.clock())

        evidence = {
            "artifact_id": artifact_id,
            "job_id": job_id,
            "intent_sha256": digest(intent),
            "profile_id": profile_id,
            "artifact_sha256": validated["artifact_sha256"],
            "deliverables": validated["deliverables"],
            "requirement_evidence": validated["requirement_evidence"],
            "release_criteria_results": validated["release_criteria_results"],
            "physical_verification": physical,
            "delivery": delivery,
        }

        def transition(row):
            state = json.loads(row["state_json"])
            _stage(state, "READY")
            if state.get("srs_sha256") != intent["srs_sha256"]:
                raise ValueError("Simple execution result belongs to a stale SRS revision")
            updated = deepcopy(state)
            updated["stage"] = "COMPLETED"
            updated["execution_artifact"] = {
                "artifact_id": artifact_id,
                "job_id": job_id,
                "profile_id": profile_id,
                "artifact_sha256": validated["artifact_sha256"],
                "deliverables": validated["deliverables"],
                "requirement_evidence": validated["requirement_evidence"],
                "release_criteria_results": validated["release_criteria_results"],
                "physical_verification": physical,
                "delivery": delivery,
                "verification_scope": ('executed_requirement_tests' if physical and
                    physical['output']['verification_kind'] == 'coding_green' else 'content_integrity'),
                "external_actions_verified": False,
            }
            return updated

        with self.journal._write() as jconn:
            jconn.execute(
                "INSERT OR IGNORE INTO task428_artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    artifact_id,
                    task_id,
                    job_id,
                    profile_id,
                    intent["srs_sha256"],
                    validated["artifact_sha256"],
                    validated["artifact_text"],
                    json.dumps(validated["deliverables"], sort_keys=True),
                    json.dumps(validated["requirement_evidence"], sort_keys=True),
                    json.dumps(validated["release_criteria_results"], sort_keys=True),
                    now,
                ),
            )
        self.journal._transition(task_id, expected_version, "exec." + job_id, evidence, transition)
        return self.get_artifact(task_id)

    def step_ready_task(self, task_id: str) -> dict[str, Any]:
        """Advance a `READY` simple task on the board and import its verified artifact."""
        try:
            job = self.materialize(task_id)
        except ExecutionRetryHold as exc:
            return dict(status=exc.status, delay=1)
        job_id = job["job_id"]
        if job["status"] == "COMPLETED":
            check = None
            delivery = None
            if self.artifact_runtime is not None:
                check = self.artifact_runtime.ensure_verification(job,
                    [r['id'] for r in job['payload']['planning_intent']['task']['document']['requirements']])
                if check['status'] != 'VERIFIED':
                    return {**check, 'delay': 1}
                if self.delivery_runtime is not None:
                    delivery = self.delivery_runtime.enqueue(job_id)
                    if delivery['status'] not in ('NOT_APPLICABLE','EXPORTED_FOR_REVIEW','INTEGRATED_ISOLATED_REPOSITORY'):
                        return {**delivery, 'delay': 1}
            artifact = self._import_completed_execution(task_id, job, check, delivery)
            if artifact is None:
                return {"status": "WAITING_FOR_NATIVE_CLEANUP", "job_id": job_id, "delay": 1}
            return {
                "status": "EXECUTION_COMPLETED",
                "job_id": job_id,
                "artifact_id": artifact["artifact_id"],
                "delay": 0,
            }
        if job["status"] in ("FAILED", "BLOCKED"):
            return {"status": "EXECUTION_JOB_HELD", "job_id": job_id, "delay": 60}
        return {"status": "WAITING_FOR_EXECUTION_BOARD", "job_id": job_id, "delay": 1}
