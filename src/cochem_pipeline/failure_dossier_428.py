"""Compile and verify 10-failure boundary dossiers (`P428-16`).

Guarantees:
- At each 10-failure boundary (`10`, `20`, `30`), a failure dossier binds the
  exact 10 committed quality-failure records from the ledger/outbox window
  (`1..10`, `11..20`, or `21..30`), concrete causes and hypotheses, and
  three-channel research (`internet`, `wiki_rag`, `papers`).
- Fabricated or incomplete failure lists that do not match committed ledger
  attempts are rejected.
- If any of the three research channels is `unavailable`, the dossier is
  recorded with `research_complete=False` (`PIVOT_RESEARCH_HOLD`) and cannot
  authorize a pivot or 11th/21st attempt.
"""
from __future__ import annotations

from copy import deepcopy
import json
import time
from typing import Any

from .task_routing import digest
from .workflow_428 import AttemptLedger, _id, _sha, _text, validate_research


VALID_FAILURE_BOUNDARIES = (10, 20, 30)


def compile_failure_dossier(
    lineage_root: str,
    boundary: int,
    failure_records: list[dict[str, Any]],
    research_channels: dict[str, Any],
    *,
    root_cause_synthesis: str,
    hypotheses: list[str],
) -> dict[str, Any]:
    """Validate and compile a canonical 10-failure boundary dossier."""
    _id(lineage_root)
    if type(boundary) is not int or boundary not in VALID_FAILURE_BOUNDARIES:
        raise ValueError("Failure dossier boundary must be 10, 20, or 30")
    if not isinstance(failure_records, list) or len(failure_records) != 10:
        raise ValueError(f"Boundary {boundary} dossier requires exactly 10 failure records from the window")

    expected_numbers = list(range(boundary - 9, boundary + 1))
    normalized_failures: list[dict[str, Any]] = []
    seen_numbers: list[int] = []

    for item in failure_records:
        if not isinstance(item, dict) or not {
            "attempt_number",
            "lease_id",
            "member_id",
            "model_family",
            "evidence_sha256",
            "cause_summary",
            "hypothesis",
        } <= set(item):
            raise ValueError(
                "Each dossier failure record requires attempt_number, lease_id, member_id, "
                "model_family, evidence_sha256, cause_summary, and hypothesis"
            )
        num = item["attempt_number"]
        if type(num) is not int:
            raise ValueError("attempt_number must be an integer")
        seen_numbers.append(num)
        normalized_failures.append(
            {
                "attempt_number": num,
                "lease_id": _id(item["lease_id"]),
                "member_id": _id(item["member_id"]),
                "model_family": _id(item["model_family"]),
                "evidence_sha256": _sha(item["evidence_sha256"]),
                "cause_summary": _text(item["cause_summary"], "Failure cause summary", 2000),
                "hypothesis": _text(item["hypothesis"], "Failure hypothesis", 2000),
            }
        )

    normalized_failures.sort(key=lambda r: r["attempt_number"])
    if [r["attempt_number"] for r in normalized_failures] != expected_numbers:
        raise ValueError(
            f"Dossier failure records must cover exact attempt numbers {expected_numbers[0]}..{expected_numbers[-1]}"
        )

    validated_research = validate_research(research_channels)
    research_complete = not any(
        ch["status"] == "unavailable" for ch in validated_research.values()
    )
    synthesis_text = _text(root_cause_synthesis, "Root cause synthesis", 8000)
    if not isinstance(hypotheses, list) or not 1 <= len(hypotheses) <= 20:
        raise ValueError("Dossier requires 1..20 bounded hypotheses")
    clean_hypotheses = [_text(h, "Dossier hypothesis", 2000) for h in hypotheses]

    body = {
        "schema": "cochem-failure-dossier/4.2.8",
        "lineage_root": lineage_root,
        "boundary": boundary,
        "window_start": expected_numbers[0],
        "window_end": expected_numbers[-1],
        "failure_records": normalized_failures,
        "last_failed_model": normalized_failures[-1]["model_family"],
        "root_cause_synthesis": synthesis_text,
        "hypotheses": clean_hypotheses,
        "research": validated_research,
        "research_complete": research_complete,
    }
    dossier_sha256 = digest(body)
    return {
        **body,
        "dossier_id": f"dossier428-{lineage_root[:32]}-{boundary}-{dossier_sha256[:16]}",
        "dossier_sha256": dossier_sha256,
    }


class FailureDossierStore:
    """Durable store that verifies dossier provenance against committed `AttemptLedger` rows."""

    def __init__(self, ledger: AttemptLedger, *, clock=time.time):
        self.ledger = ledger
        self.clock = clock
        with self.ledger._write() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS task428_dossiers(
                    dossier_key TEXT PRIMARY KEY,
                    dossier_id TEXT NOT NULL UNIQUE,
                    lineage_root TEXT NOT NULL,
                    boundary INTEGER NOT NULL,
                    research_complete INTEGER NOT NULL,
                    dossier_sha256 TEXT NOT NULL,
                    dossier_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    def _committed_quality_failures(self, lineage_root: str) -> list[dict[str, Any]]:
        _id(lineage_root)
        with self.ledger._write() as conn:
            rows = conn.execute(
                "SELECT lease, task_id, model, result_json FROM task428_attempts "
                "WHERE root=? AND result_json IS NOT NULL ORDER BY rowid",
                (lineage_root,),
            ).fetchall()
        quality_failures: list[dict[str, Any]] = []
        for r in rows:
            res = json.loads(r["result_json"])
            if res.get("outcome") == "quality_failure":
                quality_failures.append(
                    {
                        "attempt_number": len(quality_failures) + 1,
                        "lease_id": r["lease"],
                        "member_id": r["task_id"],
                        "model_family": r["model"],
                        "evidence_sha256": res["evidence_sha256"],
                    }
                )
        return quality_failures

    def record_dossier(
        self,
        lineage_root: str,
        boundary: int,
        *,
        causes_by_attempt: list[dict[str, str]] | None = None,
        research_channels: dict[str, Any],
        root_cause_synthesis: str,
        hypotheses: list[str],
    ) -> dict[str, Any]:
        """Compile and persist a provenance-verified dossier for `(lineage_root, boundary)`."""
        state = self.ledger.status(lineage_root)
        if state["failures"] != boundary:
            raise ValueError(
                f"Cannot compile boundary-{boundary} dossier when lineage has {state['failures']} failures"
            )
        committed = self._committed_quality_failures(lineage_root)
        if len(committed) != boundary:
            raise ValueError("Committed quality-failure rows do not match lineage failure count")

        window_rows = committed[boundary - 10 : boundary]
        causes_map: dict[int, dict[str, str]] = {}
        if causes_by_attempt is not None:
            for item in causes_by_attempt:
                if not isinstance(item, dict) or not {"attempt_number", "cause_summary", "hypothesis"} <= set(item):
                    raise ValueError("Each cause entry requires attempt_number, cause_summary, and hypothesis")
                num = item["attempt_number"]
                if type(num) is not int or num in causes_map:
                    raise ValueError(f"Invalid or duplicate cause attempt_number: {num}")
                if "evidence_sha256" in item:
                    expected_ev = next(
                        (w["evidence_sha256"] for w in window_rows if w["attempt_number"] == num),
                        None,
                    )
                    if item["evidence_sha256"] != expected_ev:
                        raise ValueError(f"Dossier cause entry for attempt {num} has tampered evidence_sha256")
                causes_map[num] = {
                    "cause_summary": item["cause_summary"],
                    "hypothesis": item["hypothesis"],
                }

        enriched_records: list[dict[str, Any]] = []
        for w in window_rows:
            num = w["attempt_number"]
            info = causes_map.get(
                num,
                {
                    "cause_summary": f"Attempt {num} on {w['model_family']} failed quality verification ({w['evidence_sha256'][:12]})",
                    "hypothesis": hypotheses[0] if hypotheses else "Escalate model capability or decompose scope",
                },
            )
            enriched_records.append(
                {
                    **w,
                    "cause_summary": info["cause_summary"],
                    "hypothesis": info["hypothesis"],
                }
            )

        dossier = compile_failure_dossier(
            lineage_root,
            boundary,
            enriched_records,
            research_channels,
            root_cause_synthesis=root_cause_synthesis,
            hypotheses=hypotheses,
        )
        dkey = f"{lineage_root}::{boundary}"
        now = float(self.clock())
        with self.ledger._write() as conn:
            conn.execute(
                "INSERT INTO task428_dossiers VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(dossier_key) DO UPDATE SET dossier_id=excluded.dossier_id,"
                "research_complete=excluded.research_complete,dossier_sha256=excluded.dossier_sha256,"
                "dossier_json=excluded.dossier_json,created_at=excluded.created_at",
                (
                    dkey,
                    dossier["dossier_id"],
                    lineage_root,
                    boundary,
                    1 if dossier["research_complete"] else 0,
                    dossier["dossier_sha256"],
                    json.dumps(dossier, sort_keys=True),
                    now,
                ),
            )
        return dossier

    def get_dossier(self, lineage_root: str, boundary: int) -> dict[str, Any] | None:
        _id(lineage_root)
        if type(boundary) is not int or boundary not in VALID_FAILURE_BOUNDARIES:
            raise ValueError("Invalid boundary")
        dkey = f"{lineage_root}::{boundary}"
        with self.ledger._write() as conn:
            row = conn.execute(
                "SELECT dossier_json FROM task428_dossiers WHERE dossier_key=?",
                (dkey,),
            ).fetchone()
        return json.loads(row["dossier_json"]) if row is not None else None
