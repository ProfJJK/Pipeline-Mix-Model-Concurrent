"""Trusted human SRS approval authority and revision-bound receipt broker (`P428-09`).

Threat model & guarantees:
- Shared controller/agent bearer tokens and model JSON outputs cannot grant
  owner approval. The broker requires a dedicated high-entropy owner secret
  (strictly disjoint from any agent token) and verifies an HMAC-SHA256 binding
  over `(request_id, task_id, revision, objective_sha256, srs_sha256, challenge_nonce, decision, notes)`.
- Approval covers the complete SRS document (`plan`, `architecture`, `srs`,
  `requirements`, `assessment`, `release_criteria`) via `srs_sha256` and the
  task's `objective_sha256`. Any edit to the objective, plan, architecture, or
  SRS invalidates prior approvals.
- Only complexity 8–10 tasks (or newly high-complexity 8–10 microtask children)
  require owner approval; complexity 1–7 tasks are never gated by this broker.
- Supports `approved`, `revision_requested`, and `rejected` human decisions, plus
  reuse of an existing valid `approved` receipt when the exact `(task_id, objective_sha256, srs_sha256)`
  is unchanged.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Any

from .task_routing import digest
from .workflow_428 import _id, _sha, _stage, _text


VALID_OWNER_DECISIONS: tuple[str, ...] = ("approved", "revision_requested", "rejected")


def apply_owner_decision_to_state(
    state: dict[str, Any],
    *,
    expected_srs_sha256: str,
    receipt_id: str,
    decision: str,
    notes: str = "",
    objective_sha256: str | None = None,
) -> dict[str, Any]:
    """Apply a verified human owner decision (`approved`, `revision_requested`, `rejected`) to workflow state."""
    _stage(state, "OWNER_APPROVAL")
    _id(receipt_id)
    if _sha(expected_srs_sha256) != state.get("srs_sha256"):
        raise ValueError("Approval belongs to a different SRS revision")
    if objective_sha256 is not None and _sha(objective_sha256) != digest(state.get("objective", "")):
        raise ValueError("Approval belongs to a different task objective")
    if decision not in VALID_OWNER_DECISIONS:
        raise ValueError(f"Unsupported owner decision: {decision}")

    if decision == "approved":
        from .workflow_428 import approve_srs
        return approve_srs(state, expected_srs_sha256, receipt_id)

    feedback_notes = _text(notes, "Owner decision notes", 4000) if notes else ""
    result = deepcopy(state)
    result["approval"] = None
    result["owner_feedback"] = {
        "receipt_id": receipt_id,
        "srs_sha256": expected_srs_sha256,
        "decision": decision,
        "notes": feedback_notes,
    }
    result["stage"] = "REVISING_SRS" if decision == "revision_requested" else "OWNER_REJECTED"
    return result


class OwnerApprovalBroker:
    """Durable SQLite broker for human-owner SRS review requests and HMAC-bound receipts."""

    def __init__(
        self,
        path: str | Path,
        *,
        owner_secret: str | bytes,
        shared_agent_tokens: set[str] | list[str] | tuple[str, ...] = (),
        clock=time.time,
    ):
        if str(path) == ":memory:":
            raise ValueError("Owner approval broker requires a durable SQLite database")
        self.path = Path(path)
        self.clock = clock

        if isinstance(owner_secret, (bytes, bytearray)):
            secret_str = bytes(owner_secret).decode("utf-8")
        elif isinstance(owner_secret, str):
            secret_str = owner_secret
        else:
            raise ValueError("Owner secret must be a string or UTF-8 bytes")
        if len(secret_str.strip()) < 32 or "\x00" in secret_str:
            raise ValueError("Owner secret requires at least 32 non-whitespace characters")

        forbidden = {str(tok) for tok in shared_agent_tokens if tok}
        if secret_str in forbidden:
            raise ValueError("Owner approval secret must never equal a shared agent bearer token")

        self._owner_secret = secret_str.encode("utf-8")
        self._forbidden_tokens = forbidden

        with self._write() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS owner428_requests(
                    request_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    complexity INTEGER NOT NULL,
                    objective_sha256 TEXT NOT NULL,
                    srs_sha256 TEXT NOT NULL,
                    document_json TEXT NOT NULL,
                    challenge_nonce TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS owner428_receipts(
                    receipt_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    objective_sha256 TEXT NOT NULL,
                    srs_sha256 TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    actor_kind TEXT NOT NULL,
                    hmac_sha256 TEXT NOT NULL,
                    decided_at REAL NOT NULL
                );
                """
            )

    @contextmanager
    def _write(self):
        conn = sqlite3.connect(self.path, timeout=5)
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

    def _compute_hmac(
        self,
        *,
        receipt_id: str,
        request_id: str,
        task_id: str,
        revision: int,
        objective_sha256: str,
        srs_sha256: str,
        challenge_nonce: str,
        decision: str,
        notes: str,
    ) -> str:
        payload = json.dumps(
            {
                "schema": "cochem-owner-approval-hmac/4.2.8",
                "receipt_id": receipt_id,
                "request_id": request_id,
                "task_id": task_id,
                "revision": revision,
                "objective_sha256": objective_sha256,
                "srs_sha256": srs_sha256,
                "challenge_nonce": challenge_nonce,
                "decision": decision,
                "notes": notes,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hmac.new(self._owner_secret, payload, hashlib.sha256).hexdigest()

    def _authenticate_owner_token(self, owner_token: str) -> None:
        if not isinstance(owner_token, str) or not owner_token:
            raise PermissionError("Missing human owner authentication credential")
        if any(hmac.compare_digest(owner_token.encode("utf-8"), bad.encode("utf-8")) for bad in self._forbidden_tokens):
            raise PermissionError("Shared agent bearer token cannot authorize human owner approval")
        if not hmac.compare_digest(owner_token.encode("utf-8"), self._owner_secret):
            raise PermissionError("Invalid human owner authentication credential")

    def create_request(self, task_state: dict[str, Any]) -> dict[str, Any]:
        """Register an exact-revision owner approval request for complexity 8..10."""
        if not isinstance(task_state, dict) or task_state.get("schema") != "cochem-task-workflow/4.2.8":
            raise ValueError("Owner approval request requires a valid 4.2.8 task state")
        task_id = _id(task_state.get("task_id"))
        revision = task_state.get("revision")
        if type(revision) is not int or revision < 1:
            raise ValueError("Owner approval request requires a positive SRS revision")
        assessment = task_state.get("assessment") or {}
        complexity = assessment.get("complexity")
        if type(complexity) is not int or not 8 <= complexity <= 10:
            raise ValueError("Only complexity 8..10 work requires human owner SRS approval")
        document = task_state.get("document")
        if not isinstance(document, dict) or not {"plan", "architecture", "srs", "requirements"} <= set(document):
            raise ValueError("Owner approval request requires complete plan, architecture, and SRS")
        srs_sha256 = _sha(task_state.get("srs_sha256"))
        if digest(document) != srs_sha256:
            raise ValueError("Task state srs_sha256 does not match its document")
        objective_sha256 = digest(_text(task_state.get("objective"), "Objective"))

        request_id = "ownerreq428-" + digest(
            {
                "task_id": task_id,
                "revision": revision,
                "objective_sha256": objective_sha256,
                "srs_sha256": srs_sha256,
            }
        )[:40]
        doc_json = json.dumps(document, sort_keys=True, allow_nan=False)
        now = float(self.clock())

        with self._write() as conn:
            existing = conn.execute(
                "SELECT * FROM owner428_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if existing is not None:
                return {
                    "schema": "cochem-owner-approval-request/4.2.8",
                    "request_id": existing["request_id"],
                    "task_id": existing["task_id"],
                    "revision": existing["revision"],
                    "complexity": existing["complexity"],
                    "objective_sha256": existing["objective_sha256"],
                    "srs_sha256": existing["srs_sha256"],
                    "document": json.loads(existing["document_json"]),
                    "status": existing["status"],
                }
            nonce = secrets.token_hex(16)
            conn.execute(
                "INSERT INTO owner428_requests VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    request_id,
                    task_id,
                    revision,
                    complexity,
                    objective_sha256,
                    srs_sha256,
                    doc_json,
                    nonce,
                    "PENDING",
                    now,
                ),
            )
            return {
                "schema": "cochem-owner-approval-request/4.2.8",
                "request_id": request_id,
                "task_id": task_id,
                "revision": revision,
                "complexity": complexity,
                "objective_sha256": objective_sha256,
                "srs_sha256": srs_sha256,
                "document": deepcopy(document),
                "status": "PENDING",
            }

    def record_decision(
        self,
        request_id: str,
        *,
        decision: str,
        owner_token: str,
        notes: str = "",
    ) -> dict[str, Any]:
        """Authenticate the human owner and record a revision-bound decision receipt."""
        _id(request_id)
        self._authenticate_owner_token(owner_token)
        if decision not in VALID_OWNER_DECISIONS:
            raise ValueError(f"Invalid owner decision: {decision}")
        clean_notes = _text(notes, "Owner decision notes", 4000) if notes else ""
        now = float(self.clock())

        with self._write() as conn:
            req = conn.execute(
                "SELECT * FROM owner428_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if req is None:
                raise ValueError("Unknown owner approval request_id")
            receipt_id = "ownercpt428-" + digest(
                {
                    "request_id": request_id,
                    "decision": decision,
                    "notes": clean_notes,
                    "srs_sha256": req["srs_sha256"],
                }
            )[:40]
            expected_hmac = self._compute_hmac(
                receipt_id=receipt_id,
                request_id=request_id,
                task_id=req["task_id"],
                revision=int(req["revision"]),
                objective_sha256=req["objective_sha256"],
                srs_sha256=req["srs_sha256"],
                challenge_nonce=req["challenge_nonce"],
                decision=decision,
                notes=clean_notes,
            )
            existing = conn.execute(
                "SELECT * FROM owner428_receipts WHERE receipt_id=?",
                (receipt_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO owner428_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        receipt_id,
                        request_id,
                        req["task_id"],
                        int(req["revision"]),
                        req["objective_sha256"],
                        req["srs_sha256"],
                        decision,
                        clean_notes,
                        "human_owner",
                        expected_hmac,
                        now,
                    ),
                )
                conn.execute(
                    "UPDATE owner428_requests SET status=? WHERE request_id=?",
                    (decision.upper(), request_id),
                )
        return self.load_for_journal(receipt_id)

    def find_reusable_approval(self, task_state: dict[str, Any]) -> dict[str, Any] | None:
        """Return an existing verified `approved` receipt if exact `(task_id, objective_sha256, srs_sha256)` matches."""
        if not isinstance(task_state, dict):
            return None
        task_id = task_state.get("task_id")
        srs_sha256 = task_state.get("srs_sha256")
        objective = task_state.get("objective")
        document = task_state.get("document")
        if not isinstance(task_id, str) or not isinstance(srs_sha256, str) or not isinstance(objective, str):
            return None
        if not isinstance(document, dict) or digest(document) != srs_sha256:
            return None
        objective_sha256 = digest(objective)
        with self._write() as conn:
            row = conn.execute(
                "SELECT receipt_id FROM owner428_receipts "
                "WHERE task_id=? AND objective_sha256=? AND srs_sha256=? AND decision='approved' "
                "ORDER BY decided_at DESC LIMIT 1",
                (task_id, objective_sha256, srs_sha256),
            ).fetchone()
        if row is None:
            return None
        return self.load_for_journal(row["receipt_id"])

    def load_for_journal(self, receipt_id: str) -> dict[str, Any] | None:
        """Trusted `owner_receipt` port callable for `PlanningJournal`.

        Verifies the stored HMAC-SHA256 against the request's challenge nonce and
        document digest before returning the receipt. Tampered DB rows fail closed.
        """
        _id(receipt_id)
        with self._write() as conn:
            rcpt = conn.execute(
                "SELECT * FROM owner428_receipts WHERE receipt_id=?",
                (receipt_id,),
            ).fetchone()
            if rcpt is None:
                return None
            req = conn.execute(
                "SELECT * FROM owner428_requests WHERE request_id=?",
                (rcpt["request_id"],),
            ).fetchone()
            if req is None:
                raise ValueError("Owner receipt references a missing approval request")
            doc = json.loads(req["document_json"])
            if digest(doc) != req["srs_sha256"] or rcpt["srs_sha256"] != req["srs_sha256"]:
                raise ValueError("Owner receipt SRS digest integrity failed")
            expected_hmac = self._compute_hmac(
                receipt_id=rcpt["receipt_id"],
                request_id=rcpt["request_id"],
                task_id=rcpt["task_id"],
                revision=int(rcpt["revision"]),
                objective_sha256=rcpt["objective_sha256"],
                srs_sha256=rcpt["srs_sha256"],
                challenge_nonce=req["challenge_nonce"],
                decision=rcpt["decision"],
                notes=rcpt["notes"],
            )
            if (
                rcpt["actor_kind"] != "human_owner"
                or not hmac.compare_digest(rcpt["hmac_sha256"], expected_hmac)
            ):
                raise ValueError("Owner receipt HMAC authentication failed; possible forgery or tampering")
            return {
                "receipt_id": rcpt["receipt_id"],
                "request_id": rcpt["request_id"],
                "task_id": rcpt["task_id"],
                "revision": int(rcpt["revision"]),
                "objective_sha256": rcpt["objective_sha256"],
                "srs_sha256": rcpt["srs_sha256"],
                "decision": rcpt["decision"],
                "notes": rcpt["notes"],
                "actor_kind": "human_owner",
                "hmac_sha256": rcpt["hmac_sha256"],
                "broker_verified": True,
            }
