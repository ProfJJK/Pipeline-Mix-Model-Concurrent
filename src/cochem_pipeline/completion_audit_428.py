"""Completion spot-check audit runtime and grounded repair incident creation (`P428-19`).

Guarantees:
- Deterministic sampling (`sample_completion`) drives independent audits of
  completed outputs, test receipts, and controller receipts; failures and
  invariant violations are always audited.
- An output hash alone is never accepted as proof of quality: missing/empty/
  corrupted artifacts, failed/incomplete test receipts, or independent auditor
  findings revoke false completions.
- Distinguishes `TASK_DEFECT` (false completion / bad task artifact, which
  revokes completion without opening a pipeline repair incident) from
  `PIPELINE_DEFECT` (controller, invariant, or native execution fault, which
  opens a grounded incident in `RepairQueue`).
- Duplicate audits, model uncertainty (`UNCERTAIN`), and quota/availability
  waits (`WAITING_QUOTA`) never recursively flood `RepairQueue`.
- Audit queue depth (`max_pending_audits`) and concurrent active audits
  (`max_active_audits`) are strictly bounded.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from .repair_queue_428 import RepairQueue, sample_completion
from .task_routing import digest, validate_task_tags
from .workflow_428 import _id, _sha, _text


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class CompletionAuditRuntime:
    """Executes deterministic completion spot checks and opens grounded incidents (`P428-19`)."""

    def __init__(
        self,
        db_path: str | Path,
        catalog: dict[str, Any],
        repair_queue: RepairQueue,
        *,
        sample_basis_points: int = 1000,
        max_pending_audits: int = 32,
        max_active_audits: int = 2,
        clock=time.time,
    ):
        if str(db_path) == ":memory:":
            raise ValueError("Completion audit runtime requires a durable SQLite database")
        if type(sample_basis_points) is not int or not 0 <= sample_basis_points <= 10000:
            raise ValueError("sample_basis_points must be an integer in 0..10000")
        if type(max_pending_audits) is not int or not 1 <= max_pending_audits <= 256:
            raise ValueError("max_pending_audits must be an integer in 1..256")
        if type(max_active_audits) is not int or not 1 <= max_active_audits <= 4:
            raise ValueError("max_active_audits must be an integer in 1..4")
        self.db_path = Path(db_path)
        self.catalog = deepcopy(catalog)
        self.repair_queue = repair_queue
        self.sample_basis_points = sample_basis_points
        self.max_pending_audits = max_pending_audits
        self.max_active_audits = max_active_audits
        self.clock = clock
        with self._write() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit428_spotchecks(
                    audit_key TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    output_sha256 TEXT NOT NULL,
                    producer_model_family TEXT NOT NULL,
                    task_types_json TEXT NOT NULL,
                    expected_requirements_json TEXT NOT NULL,
                    forced INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    disposition TEXT,
                    auditor_model_family TEXT,
                    incident_id TEXT,
                    result_json TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )
        self.recover_interrupted_audits()

    @contextmanager
    def _write(self):
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def recover_interrupted_audits(self) -> int:
        """Reset any interrupted `IN_PROGRESS` spotcheck back to `QUEUED` after restart."""
        now = float(self.clock())
        with self._write() as conn:
            cur = conn.execute(
                "UPDATE audit428_spotchecks SET status='QUEUED', updated_at=? WHERE status='IN_PROGRESS'",
                (now,),
            )
            return int(cur.rowcount or 0)

    def enqueue_completion(
        self,
        job_id: str,
        *,
        task_id: str,
        output_sha256: str,
        producer_model_family: str,
        task_types: list[str],
        expected_requirements: list[str],
        force_audit: bool = False,
    ) -> dict[str, Any]:
        """Deterministically sample a completion (or force-audit an anomaly) with strict deduplication and capacity bounds."""
        _id(job_id)
        _id(task_id)
        _sha(output_sha256)
        _id(producer_model_family)
        tags = validate_task_tags(task_types)
        reqs = [_id(r) for r in expected_requirements]
        if not reqs:
            raise ValueError("Completion audit requires at least one expected requirement ID")

        audit_key = f"{job_id}::{output_sha256}"
        sampled = bool(force_audit) or sample_completion(
            job_id,
            output_sha256,
            sample_basis_points=self.sample_basis_points,
        )
        if not sampled:
            return {
                "audit_key": audit_key,
                "sampled": False,
                "deduplicated": False,
                "status": "NOT_SAMPLED",
            }

        now = float(self.clock())
        with self._write() as conn:
            existing = conn.execute(
                "SELECT * FROM audit428_spotchecks WHERE audit_key=?",
                (audit_key,),
            ).fetchone()
            if existing is not None:
                return {
                    **self._row_to_dict(existing),
                    "sampled": True,
                    "deduplicated": True,
                }

            pending_count = conn.execute(
                "SELECT count(*) FROM audit428_spotchecks WHERE status IN ('QUEUED','WAITING_QUOTA','IN_PROGRESS')"
            ).fetchone()[0]
            if pending_count >= self.max_pending_audits:
                return {
                    "audit_key": audit_key,
                    "job_id": job_id,
                    "task_id": task_id,
                    "output_sha256": output_sha256,
                    "sampled": True,
                    "deduplicated": False,
                    "status": "SKIPPED_AUDIT_CAPACITY",
                    "disposition": "CAPACITY_BOUNDED",
                }

            conn.execute(
                "INSERT INTO audit428_spotchecks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    audit_key,
                    job_id,
                    task_id,
                    output_sha256,
                    producer_model_family,
                    json.dumps(tags),
                    json.dumps(reqs),
                    int(bool(force_audit)),
                    "QUEUED",
                    None,
                    None,
                    None,
                    None,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM audit428_spotchecks WHERE audit_key=?",
                (audit_key,),
            ).fetchone()
        return {
            **self._row_to_dict(row),
            "sampled": True,
            "deduplicated": False,
        }

    def start_audit(self, audit_key: str, *, auditor_model_family: str, availability_status: str = "ready") -> dict[str, Any]:
        """Claim a queued spotcheck within `max_active_audits` using an independent auditor model."""
        _id(auditor_model_family)
        if availability_status not in ("ready", "quota_exhausted", "provider_unavailable"):
            raise ValueError(f"Unknown availability_status: {availability_status}")

        now = float(self.clock())
        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM audit428_spotchecks WHERE audit_key=?",
                (audit_key,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown audit_key: {audit_key}")
            if row["status"] == "COMPLETED":
                return self._row_to_dict(row)
            if auditor_model_family == row["producer_model_family"]:
                raise ValueError("Completion spotcheck requires a different model family than the producer")

            if availability_status != "ready":
                conn.execute(
                    "UPDATE audit428_spotchecks SET status='WAITING_QUOTA', auditor_model_family=?, updated_at=? WHERE audit_key=?",
                    (auditor_model_family, now, audit_key),
                )
                return self._row_to_dict(
                    conn.execute("SELECT * FROM audit428_spotchecks WHERE audit_key=?", (audit_key,)).fetchone()
                )

            active_count = conn.execute(
                "SELECT count(*) FROM audit428_spotchecks WHERE status='IN_PROGRESS' AND audit_key!=?",
                (audit_key,),
            ).fetchone()[0]
            if active_count >= self.max_active_audits:
                raise ValueError("Concurrent active completion audits reached max_active_audits bound")

            conn.execute(
                "UPDATE audit428_spotchecks SET status='IN_PROGRESS', auditor_model_family=?, updated_at=? WHERE audit_key=?",
                (auditor_model_family, now, audit_key),
            )
            return self._row_to_dict(
                conn.execute("SELECT * FROM audit428_spotchecks WHERE audit_key=?", (audit_key,)).fetchone()
            )

    def execute_spotcheck(
        self,
        audit_key: str,
        *,
        auditor_model_family: str,
        artifact_path: str | Path | None = None,
        artifact_bytes: bytes | None = None,
        test_receipt: dict[str, Any],
        controller_receipt: dict[str, Any],
        auditor_verdict: str,
        auditor_findings: str,
        source_kind: str = "completion_spotcheck",
    ) -> dict[str, Any]:
        """Verify physical artifact bytes, test receipts, controller invariants, and independent auditor verdict."""
        _id(auditor_model_family)
        if auditor_verdict not in ("PASS", "TASK_DEFECT", "PIPELINE_DEFECT", "UNCERTAIN"):
            raise ValueError("auditor_verdict must be PASS, TASK_DEFECT, PIPELINE_DEFECT, or UNCERTAIN")
        clean_findings = _text(auditor_findings, "Auditor findings", 8000)

        # Ensure audit is claimed or claim it now
        claimed = self.start_audit(audit_key, auditor_model_family=auditor_model_family, availability_status="ready")
        if claimed["status"] == "COMPLETED":
            return claimed

        expected_sha = claimed["output_sha256"]
        expected_reqs = set(claimed["expected_requirements"])

        # 1. Inspect physical artifact bytes (an output hash alone is NOT proof of quality!)
        observed_bytes: bytes | None = None
        if artifact_path is not None:
            p = Path(artifact_path)
            if p.is_file():
                observed_bytes = p.read_bytes()
        elif artifact_bytes is not None:
            observed_bytes = artifact_bytes

        artifact_missing = observed_bytes is None or len(observed_bytes.strip()) == 0
        observed_sha = _sha256_bytes(observed_bytes) if observed_bytes is not None else None
        artifact_hash_matches = (not artifact_missing) and (observed_sha == expected_sha)

        # 2. Inspect test receipt
        if not isinstance(test_receipt, dict) or not {
            "passed",
            "exit_code",
            "test_output_sha256",
            "requirements_verified",
        } <= set(test_receipt):
            raise ValueError("test_receipt requires passed, exit_code, test_output_sha256, and requirements_verified")
        _sha(test_receipt["test_output_sha256"])
        verified_reqs = set(test_receipt.get("requirements_verified") or [])
        tests_valid = (
            test_receipt.get("passed") is True
            and test_receipt.get("exit_code") == 0
            and expected_reqs <= verified_reqs
        )

        # 3. Inspect controller receipt for systemic/pipeline faults
        if not isinstance(controller_receipt, dict) or not {
            "cleanup_verified",
            "lease_fenced",
            "invariant_violations",
        } <= set(controller_receipt):
            raise ValueError("controller_receipt requires cleanup_verified, lease_fenced, and invariant_violations")
        violations = list(controller_receipt.get("invariant_violations") or [])
        systemic_fault = (
            controller_receipt.get("cleanup_verified") is not True
            or controller_receipt.get("lease_fenced") is not True
            or bool(violations)
            or auditor_verdict == "PIPELINE_DEFECT"
        )

        incident_id: str | None = None
        incident_record: dict[str, Any] | None = None
        task_defect_recorded = False

        if systemic_fault:
            disposition = "PIPELINE_DEFECT_INCIDENT_OPENED"
            evidence_payload = {
                "audit_key": audit_key,
                "job_id": claimed["job_id"],
                "task_id": claimed["task_id"],
                "output_sha256": expected_sha,
                "observed_artifact_sha256": observed_sha,
                "cleanup_verified": bool(controller_receipt.get("cleanup_verified")),
                "lease_fenced": bool(controller_receipt.get("lease_fenced")),
                "invariant_violations": violations,
                "auditor_verdict": auditor_verdict,
                "auditor_findings": clean_findings,
            }
            ev_sha = digest(evidence_payload)
            incident_id = f"inc428-{claimed['job_id'][:24]}-{ev_sha[:12]}"
            incident_record = self.repair_queue.report(
                incident_id,
                f"Pipeline fault during {claimed['job_id']}: {clean_findings}",
                ev_sha,
                source_kind=source_kind,
                task_types=claimed["task_types"],
            )
        elif artifact_missing or not artifact_hash_matches or not tests_valid or auditor_verdict == "TASK_DEFECT":
            # Task defect (false completion): revoke task completion & charge task quality, never flood RepairQueue!
            disposition = "FALSE_COMPLETION_TASK_DEFECT"
            task_defect_recorded = True
        elif auditor_verdict == "UNCERTAIN":
            # Model uncertainty: hold inconclusive without opening a repair incident
            disposition = "INCONCLUSIVE_HOLD"
        else:
            disposition = "VERIFIED_PASS"

        result_payload = {
            "audit_key": audit_key,
            "job_id": claimed["job_id"],
            "task_id": claimed["task_id"],
            "disposition": disposition,
            "auditor_model_family": auditor_model_family,
            "auditor_verdict": auditor_verdict,
            "auditor_findings": clean_findings,
            "artifact_missing": artifact_missing,
            "artifact_hash_matches": artifact_hash_matches,
            "tests_valid": tests_valid,
            "systemic_fault": systemic_fault,
            "task_defect_recorded": task_defect_recorded,
            "incident_id": incident_id,
            "incident_request": incident_record,
        }
        now = float(self.clock())
        with self._write() as conn:
            conn.execute(
                "UPDATE audit428_spotchecks SET status='COMPLETED', disposition=?, auditor_model_family=?, incident_id=?, result_json=?, updated_at=? WHERE audit_key=?",
                (
                    disposition,
                    auditor_model_family,
                    incident_id,
                    json.dumps(result_payload, sort_keys=True),
                    now,
                    audit_key,
                ),
            )
            row = conn.execute(
                "SELECT * FROM audit428_spotchecks WHERE audit_key=?",
                (audit_key,),
            ).fetchone()
        return self._row_to_dict(row)

    def get_spotcheck(self, audit_key: str) -> dict[str, Any] | None:
        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM audit428_spotchecks WHERE audit_key=?",
                (audit_key,),
            ).fetchone()
        return self._row_to_dict(row) if row is not None else None

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        return {
            "audit_key": row["audit_key"],
            "job_id": row["job_id"],
            "task_id": row["task_id"],
            "output_sha256": row["output_sha256"],
            "producer_model_family": row["producer_model_family"],
            "task_types": json.loads(row["task_types_json"]),
            "expected_requirements": json.loads(row["expected_requirements_json"]),
            "forced": bool(row["forced"]),
            "status": row["status"],
            "disposition": row["disposition"],
            "auditor_model_family": row["auditor_model_family"],
            "incident_id": row["incident_id"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }
