"""30-failure locked-task decision packets and authenticated owner actions (`P428-18`).

Guarantees:
- A 30-failure locked lineage never retries or unlocks automatically.
- Ordinary status queries (`status_projection`) are read-only and deterministic across
  repeat reads, surfacing sanitized artifact/failure/dossier links (with credentials
  scrubbed), root-cause context, and concrete `defer` / `revise_scope` options with
  pros, cons, and risks.
- If the boundary-30 dossier is missing or incomplete, the packet surfaces
  `MISSING_FINAL_DOSSIER` / `PIVOT_RESEARCH_HOLD` and refuses premature decisions.
- Any owner decision requires authenticated human-owner authority, binds the exact
  `packet_revision_sha256` (rejecting stale actions), is durably audited, and never
  resets historical failure counts (`30`) or restores stale execution on the locked lineage.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re
import time
from typing import Any

from .failure_dossier_428 import FailureDossierStore
from .task_routing import digest
from .workflow_428 import AttemptLedger, _id, _sha, _text


_SECRET_QUERY_RE = re.compile(
    r"([?&](?:token|access_token|api_key|key|secret|password|sig|signature|auth)=)[^&#\s]+",
    re.IGNORECASE,
)
_USERINFO_RE = re.compile(r"(https?://)[^/@\s]+@", re.IGNORECASE)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)


def sanitize_status_link(link: str) -> str:
    """Scrub credentials, userinfo, and secret query parameters from a status link."""
    text = _text(link, "Status link", 2048).strip()
    text = _USERINFO_RE.sub(r"\1", text)
    text = _SECRET_QUERY_RE.sub(r"\1REDACTED", text)
    text = _BEARER_RE.sub("Bearer REDACTED", text)
    return text


class LockedTaskDecisionStore:
    """Read-only status projection and audited owner decision handler for 30-failure locks (`P428-18`)."""

    def __init__(
        self,
        ledger: AttemptLedger,
        *,
        dossier_store: FailureDossierStore | None = None,
        clock=time.time,
    ):
        self.ledger = ledger
        self.dossier_store = dossier_store or FailureDossierStore(ledger, clock=clock)
        self.clock = clock
        with self.ledger._write() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS task428_locked_links(
                    lineage_root TEXT PRIMARY KEY,
                    artifact_links_json TEXT NOT NULL,
                    failure_links_json TEXT NOT NULL,
                    dossier_links_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task428_locked_decisions(
                    decision_id TEXT PRIMARY KEY,
                    lineage_root TEXT NOT NULL,
                    action TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    authenticated_owner_receipt_id TEXT NOT NULL,
                    packet_revision_sha256 TEXT NOT NULL,
                    final_dossier_sha256 TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    revised_task_id TEXT,
                    revised_objective TEXT,
                    retained_failures INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    def register_context_links(
        self,
        lineage_root: str,
        *,
        artifact_links: list[str] | None = None,
        failure_links: list[str] | None = None,
        dossier_links: list[str] | None = None,
    ) -> dict[str, list[str]]:
        """Attach sanitized artifact, failure, and dossier links for status projection."""
        _id(lineage_root)
        clean_artifacts = [sanitize_status_link(x) for x in (artifact_links or [])]
        clean_failures = [sanitize_status_link(x) for x in (failure_links or [])]
        clean_dossiers = [sanitize_status_link(x) for x in (dossier_links or [])]
        now = float(self.clock())
        with self.ledger._write() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO task428_locked_links VALUES(?,?,?,?,?)",
                (
                    lineage_root,
                    json.dumps(clean_artifacts),
                    json.dumps(clean_failures),
                    json.dumps(clean_dossiers),
                    now,
                ),
            )
        return {
            "artifact_links": clean_artifacts,
            "failure_links": clean_failures,
            "dossier_links": clean_dossiers,
        }

    def _build_packet_for_root(self, conn, state: dict[str, Any]) -> dict[str, Any]:
        root = state["root"]
        dossiers = []
        for b in (10, 20, 30):
            row = conn.execute(
                "SELECT dossier_json FROM task428_dossiers WHERE dossier_key=?",
                (f"{root}::{b}",),
            ).fetchone()
            if row is not None:
                dossiers.append(json.loads(row[0]))

        dossier_30 = next((d for d in dossiers if d["boundary"] == 30), None)
        if dossier_30 is None:
            dossier_state = "MISSING_FINAL_DOSSIER"
            actionable = False
        elif not dossier_30.get("research_complete"):
            dossier_state = "PIVOT_RESEARCH_HOLD"
            actionable = False
        else:
            dossier_state = "READY"
            actionable = True

        link_row = conn.execute(
            "SELECT * FROM task428_locked_links WHERE lineage_root=?",
            (root,),
        ).fetchone()
        if link_row is not None:
            artifact_links = json.loads(link_row["artifact_links_json"])
            failure_links = json.loads(link_row["failure_links_json"])
            dossier_links = json.loads(link_row["dossier_links_json"])
        else:
            artifact_links = [f"artifacts/{root}/summary.json"]
            failure_links = [f"journal/{root}/failures-1-30.json"]
            dossier_links = [f"dossiers/{d['dossier_id']}.json" for d in dossiers]

        decisions_rows = conn.execute(
            "SELECT * FROM task428_locked_decisions WHERE lineage_root=? ORDER BY created_at ASC",
            (root,),
        ).fetchall()
        recorded_decisions = [
            {
                "decision_id": r["decision_id"],
                "action": r["action"],
                "disposition": r["disposition"],
                "authenticated_owner_receipt_id": r["authenticated_owner_receipt_id"],
                "packet_revision_sha256": r["packet_revision_sha256"],
                "final_dossier_sha256": r["final_dossier_sha256"],
                "rationale": r["rationale"],
                "revised_task_id": r["revised_task_id"],
                "revised_objective": r["revised_objective"],
                "retained_failures": int(r["retained_failures"]),
                "created_at": float(r["created_at"]),
            }
            for r in decisions_rows
        ]
        current_disposition = (
            recorded_decisions[-1]["disposition"]
            if recorded_decisions
            else "LOCKED_AWAITING_OWNER"
        )

        options = [
            {
                "action": "revise_scope",
                "title": "Create a revised task scope with preserved 30-failure history",
                "pros": [
                    "Narrows or clarifies requirements based on the 30-failure root-cause synthesis",
                    "Preserves all 30 failure receipts and dossiers for audit traceability",
                ],
                "cons": [
                    "Changes the originally requested scope and requires a fresh planning cycle",
                ],
                "risks": [
                    "May omit secondary capabilities from the original objective",
                    "Does not reset historical 30-failure spend on the locked lineage",
                ],
            },
            {
                "action": "defer",
                "title": "Defer the locked task and preserve all evidence",
                "pros": [
                    "Halts further model/compute spend immediately while retaining all dossiers and artifacts",
                ],
                "cons": [
                    "Task lineage remains unfinished in DEFERRED disposition",
                ],
                "risks": [
                    "Downstream workflows depending on this task remain blocked",
                ],
            },
        ]

        revision_seed = {
            "lineage_root": root,
            "failures": int(state["failures"]),
            "stage": state["stage"],
            "dossier_state": dossier_state,
            "final_dossier_sha256": dossier_30["dossier_sha256"] if dossier_30 else None,
            "decision_count": len(recorded_decisions),
            "last_decision_id": recorded_decisions[-1]["decision_id"] if recorded_decisions else None,
        }
        packet_revision_sha256 = digest(revision_seed)

        return {
            "schema": "cochem-locked-task-decision/4.2.8",
            "lineage_root": root,
            "failures": int(state["failures"]),
            "stage": "LOCKED",
            "disposition": current_disposition,
            "dossier_state": dossier_state,
            "actionable": actionable and current_disposition == "LOCKED_AWAITING_OWNER",
            "packet_revision_sha256": packet_revision_sha256,
            "last_failed_model": state.get("last_model"),
            "final_dossier_id": dossier_30["dossier_id"] if dossier_30 else None,
            "final_dossier_sha256": dossier_30["dossier_sha256"] if dossier_30 else None,
            "root_cause_synthesis": dossier_30["root_cause_synthesis"] if dossier_30 else None,
            "hypotheses": dossier_30["hypotheses"] if dossier_30 else [],
            "dossiers_summary": [
                {
                    "boundary": d["boundary"],
                    "dossier_id": d["dossier_id"],
                    "dossier_sha256": d["dossier_sha256"],
                    "research_complete": bool(d["research_complete"]),
                    "last_failed_model": d["last_failed_model"],
                }
                for d in dossiers
            ],
            "links": {
                "artifact_links": artifact_links,
                "failure_links": failure_links,
                "dossier_links": dossier_links,
            },
            "options": options,
            "decisions": recorded_decisions,
        }

    def status_projection(self, lineage_root: str | None = None) -> list[dict[str, Any]]:
        """Read-only projection of locked tasks for ordinary pipeline status requests."""
        if lineage_root is not None:
            _id(lineage_root)
        with self.ledger._write() as conn:
            rows = conn.execute("SELECT root, state_json FROM task428_lineages ORDER BY root ASC").fetchall()
            packets = []
            for row in rows:
                state = json.loads(row["state_json"])
                if state.get("stage") != "LOCKED":
                    continue
                if lineage_root is not None and state.get("root") != lineage_root:
                    continue
                packets.append(self._build_packet_for_root(conn, state))
            return packets

    def apply_owner_decision(
        self,
        lineage_root: str,
        *,
        action: str,
        expected_packet_sha256: str,
        authenticated_owner_receipt_id: str | None,
        owner_authenticated: bool = False,
        rationale: str,
        revised_task_id: str | None = None,
        revised_objective: str | None = None,
    ) -> dict[str, Any]:
        """Record an explicit, authenticated owner decision (`defer` or `revise_scope`) without resetting budgets."""
        _id(lineage_root)
        _sha(expected_packet_sha256)
        if not owner_authenticated or not authenticated_owner_receipt_id:
            raise PermissionError("Unauthenticated owner decision or unlock is refused")
        _id(authenticated_owner_receipt_id)
        if action not in ("defer", "revise_scope"):
            raise ValueError("Locked task only admits 'defer' or 'revise_scope'; raw unlock or budget reset is forbidden")
        clean_rationale = _text(rationale, "Owner decision rationale", 4000)

        with self.ledger._write() as conn:
            state = self.ledger._read(conn, lineage_root)
            if state["root"] != lineage_root or state["stage"] != "LOCKED" or int(state["failures"]) != 30:
                raise ValueError(f"Lineage '{lineage_root}' is not in 30-failure LOCKED state")

            packet = self._build_packet_for_root(conn, state)
            if packet["dossier_state"] != "READY":
                raise ValueError(
                    f"Cannot apply owner decision while boundary-30 dossier is in state '{packet['dossier_state']}'"
                )
            if packet["packet_revision_sha256"] != expected_packet_sha256:
                raise ValueError("Stale owner decision: expected_packet_sha256 does not match current locked packet")
            if packet["disposition"] != "LOCKED_AWAITING_OWNER":
                raise ValueError(f"Locked lineage '{lineage_root}' already has terminal decision '{packet['disposition']}'")

            if action == "revise_scope":
                if not revised_task_id or not revised_objective:
                    raise ValueError("revise_scope requires a new revised_task_id and revised_objective")
                _id(revised_task_id)
                if revised_task_id == lineage_root:
                    raise ValueError("revised_task_id must be a distinct new task identifier; locked lineage cannot be reused")
                if conn.execute("SELECT 1 FROM task428_members WHERE task_id=?", (revised_task_id,)).fetchone():
                    raise ValueError(f"revised_task_id '{revised_task_id}' already exists")
                clean_obj = _text(revised_objective, "Revised objective", 16000)
                disposition = "REVISED_NEW_REVISION"
            else:
                if revised_task_id is not None or revised_objective is not None:
                    raise ValueError("defer action does not accept revised_task_id or revised_objective")
                clean_obj = None
                disposition = "DEFERRED"

            now = float(self.clock())
            decision_id = f"dec428-{lineage_root[:24]}-{expected_packet_sha256[:12]}"
            conn.execute(
                "INSERT INTO task428_locked_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    decision_id,
                    lineage_root,
                    action,
                    disposition,
                    authenticated_owner_receipt_id,
                    expected_packet_sha256,
                    packet["final_dossier_sha256"],
                    clean_rationale,
                    revised_task_id,
                    clean_obj,
                    int(state["failures"]),
                    now,
                ),
            )
            # Keep failures==30 and stage=='LOCKED' permanently on the locked lineage!
            state.setdefault("decisions", []).append(
                {
                    "decision_id": decision_id,
                    "action": action,
                    "disposition": disposition,
                    "authenticated_owner_receipt_id": authenticated_owner_receipt_id,
                    "packet_revision_sha256": expected_packet_sha256,
                    "final_dossier_sha256": packet["final_dossier_sha256"],
                    "rationale": clean_rationale,
                    "revised_task_id": revised_task_id,
                    "retained_failures": 30,
                }
            )
            state["research_due"] = False
            self.ledger._save(conn, state)
            return self._build_packet_for_root(conn, state)
