"""Bind actual scheduler outcomes to quality attempt accounting (`P428-15`).

Guarantees:
- Exact scheduler attempts `(job_id, attempt_id, fencing_token)` charge the
  correct task lineage (`AttemptLedger`) at most once.
- Independent WBS microtasks receive independent lineage roots
  (`{task_id}.mt.{microtask_id}`), whereas fractured descendants share their
  failing parent's lineage root and accumulated failure count (`10`/`20`/`30`).
- Availability waits (`auth`, `quota`, `resource`, `rate_limit`, `capacity`,
  `availability`) release the active attempt lease with zero quality failures
  charged.
- Durable outbox staging (`attempt428_outbox`) reconciles crash windows between
  board completion/failure and `AttemptLedger.finish()` without double-charging
  or losing failure counts across restarts.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import time
from typing import Any

from .task_routing import digest
from .workflow_428 import AttemptLedger, _id, _sha


AVAILABILITY_CATEGORIES = frozenset(
    {
        "availability",
        "auth",
        "quota",
        "resource",
        "rate_limit",
        "capacity",
        "busy", "backlog", "provider", "context", "compatibility",
    }
)

QUALITY_FAILURE_CATEGORIES = frozenset(
    {
        "quality_failure",
        "validation_error",
        "tests_failed",
        "timeout",
        "oom",
        "output_limit",
        "execution_error",
        "code", "protocol",
    }
)


def classify_attempt_outcome(category: str) -> str:
    """Map a scheduler or worker outcome category to an `AttemptLedger` outcome."""
    if not isinstance(category, str):
        raise ValueError("Attempt outcome category must be a string")
    norm = category.strip().lower()
    if norm == "success":
        return "success"
    if norm in AVAILABILITY_CATEGORIES:
        return "availability"
    if norm in QUALITY_FAILURE_CATEGORIES:
        return "quality_failure"
    raise ValueError(f"Unsupported attempt outcome category: {category}")


class AttemptAccountingRuntime:
    """Fenced board-to-ledger attempt accounting with crash-window outbox reconciliation (`P428-15`)."""

    def __init__(self, ledger: AttemptLedger | Path | str, *, store=None, clock=time.time):
        self.ledger = ledger if isinstance(ledger, AttemptLedger) else AttemptLedger(ledger)
        self.store = store
        self.clock = clock
        with self.ledger._write() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS attempt428_outbox(
                    fence_key TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    lineage_root TEXT NOT NULL,
                    member_id TEXT NOT NULL,
                    model_family TEXT NOT NULL,
                    lease_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    staged_outcome TEXT,
                    evidence_sha256 TEXT,
                    result_state_json TEXT,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS attempt428_outbox_status
                    ON attempt428_outbox(status);
                """
            )

    @staticmethod
    def _fence_key(job_id: str, attempt_id: str, fencing_token: int) -> str:
        _id(job_id)
        _id(attempt_id)
        if type(fencing_token) is not int or fencing_token < 1:
            raise ValueError("fencing_token must be a positive integer")
        return f"{job_id}::{attempt_id}::{fencing_token}"

    @staticmethod
    def wbs_microtask_lineage_root(task_id: str, microtask_id: str) -> str:
        _id(task_id)
        _id(microtask_id)
        return _id(f"{task_id}.mt.{microtask_id}")

    def ensure_lineage(self, root: str, complexity: int = 1) -> dict[str, Any]:
        """Ensure a lineage root exists without resetting any existing budget."""
        _id(root)
        with self.ledger._write() as conn:
            existing = conn.execute(
                "SELECT root FROM task428_members WHERE task_id=?",
                (root,),
            ).fetchone()
            if existing is not None:
                return self.ledger._read(conn, root)
        return self.ledger.create(root, complexity=complexity)

    def ensure_wbs_microtask_lineage(
        self,
        task_id: str,
        microtask_id: str,
        complexity: int = 1,
    ) -> dict[str, Any]:
        """Create or return an independent quality budget lineage for a WBS microtask."""
        root = self.wbs_microtask_lineage_root(task_id, microtask_id)
        return self.ensure_lineage(root, complexity=complexity)

    def start_board_attempt(
        self,
        job_id: str,
        attempt_id: str,
        fencing_token: int,
        *,
        lineage_root: str,
        member_id: str | None = None,
        model_family: str,
        complexity: int = 1,
    ) -> dict[str, Any]:
        """Acquire a fenced quality-attempt lease for a board claim, idempotently per fence."""
        fkey = self._fence_key(job_id, attempt_id, fencing_token)
        _id(lineage_root)
        actual_member = _id(member_id if member_id is not None else lineage_root)
        _id(model_family)

        self.ensure_lineage(lineage_root, complexity=complexity)
        now = float(self.clock())

        with self.ledger._write() as conn:
            existing = conn.execute(
                "SELECT * FROM attempt428_outbox WHERE fence_key=?",
                (fkey,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["lineage_root"] != lineage_root
                    or existing["member_id"] != actual_member
                    or existing["model_family"] != model_family
                ):
                    raise ValueError("Fence key is already bound to different attempt parameters")
                return {
                    "fence_key": fkey,
                    "lease_id": existing["lease_id"],
                    "lineage_root": lineage_root,
                    "member_id": actual_member,
                    "model_family": model_family,
                    "status": existing["status"],
                }

            # Reject stale/competing attempt for the same job if an older fence is still active
            active_for_job = conn.execute(
                "SELECT fence_key, fencing_token FROM attempt428_outbox "
                "WHERE job_id=? AND status IN ('ACTIVE', 'OUTCOME_STAGED')",
                (job_id,),
            ).fetchall()
            for row in active_for_job:
                if int(row["fencing_token"]) >= fencing_token:
                    raise ValueError("Stale or duplicate fencing token for board job")

        # A crash after ledger.start but before outbox insertion must recover
        # the same lease, never leave an orphan that blocks the lineage forever.
        lease_id = self.ledger.start(lineage_root, actual_member, model_family,
                                    lease_id='board428-' + digest({'fence_key': fkey})[:40])
        with self.ledger._write() as conn:
            conn.execute(
                "INSERT INTO attempt428_outbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    fkey,
                    job_id,
                    attempt_id,
                    fencing_token,
                    lineage_root,
                    actual_member,
                    model_family,
                    lease_id,
                    "ACTIVE",
                    None,
                    None,
                    None,
                    now,
                ),
            )
        return {
            "fence_key": fkey,
            "lease_id": lease_id,
            "lineage_root": lineage_root,
            "member_id": actual_member,
            "model_family": model_family,
            "status": "ACTIVE",
        }

    def stage_board_outcome(
        self,
        job_id: str,
        attempt_id: str,
        fencing_token: int,
        *,
        category: str,
        evidence_sha256: str,
    ) -> dict[str, Any]:
        """Stage a fenced outcome in the durable outbox before applying it to `AttemptLedger`.

        Used both during normal completion and to test crash recovery between
        outbox staging and ledger commitment.
        """
        fkey = self._fence_key(job_id, attempt_id, fencing_token)
        outcome = classify_attempt_outcome(category)
        _sha(evidence_sha256)
        now = float(self.clock())

        with self.ledger._write() as conn:
            row = conn.execute(
                "SELECT * FROM attempt428_outbox WHERE fence_key=?",
                (fkey,),
            ).fetchone()
            if row is None:
                raise ValueError("Unknown or stale attempt fence")
            if row["staged_outcome"] is not None:
                if row["staged_outcome"] != outcome or row["evidence_sha256"] != evidence_sha256:
                    raise ValueError("Completed or staged attempt outcome is immutable")
                return dict(row)

            conn.execute(
                "UPDATE attempt428_outbox SET status='OUTCOME_STAGED',staged_outcome=?,evidence_sha256=?,updated_at=? "
                "WHERE fence_key=?",
                (outcome, evidence_sha256, now, fkey),
            )
            return dict(
                conn.execute("SELECT * FROM attempt428_outbox WHERE fence_key=?", (fkey,)).fetchone()
            )

    def reconcile_outbox(self) -> list[dict[str, Any]]:
        """Apply all `OUTCOME_STAGED` outbox records to `AttemptLedger` idempotently."""
        with self.ledger._write() as conn:
            staged_rows = conn.execute(
                "SELECT * FROM attempt428_outbox WHERE status='OUTCOME_STAGED' ORDER BY updated_at, fence_key"
            ).fetchall()

        reconciled: list[dict[str, Any]] = []
        now = float(self.clock())
        for row in staged_rows:
            state = self.ledger.finish(
                row["lease_id"],
                row["staged_outcome"],
                row["evidence_sha256"],
            )
            with self.ledger._write() as conn:
                conn.execute(
                    "UPDATE attempt428_outbox SET status='RECONCILED',result_state_json=?,updated_at=? "
                    "WHERE fence_key=?",
                    (json.dumps(state, sort_keys=True), now, row["fence_key"]),
                )
            reconciled.append(state)
        return reconciled

    def record_board_outcome(
        self,
        job_id: str,
        attempt_id: str,
        fencing_token: int,
        *,
        category: str,
        evidence_sha256: str,
    ) -> dict[str, Any]:
        """Stage and reconcile a fenced board attempt outcome in one call, idempotently."""
        fkey = self._fence_key(job_id, attempt_id, fencing_token)
        staged = self.stage_board_outcome(
            job_id,
            attempt_id,
            fencing_token,
            category=category,
            evidence_sha256=evidence_sha256,
        )
        if staged["status"] == "RECONCILED" and staged.get("result_state_json"):
            return json.loads(staged["result_state_json"])
        self.reconcile_outbox()
        with self.ledger._write() as conn:
            row = conn.execute(
                "SELECT result_state_json FROM attempt428_outbox WHERE fence_key=?",
                (fkey,),
            ).fetchone()
        return json.loads(row["result_state_json"])
