"""Researched failure dossier and higher-model pivot runtime (`P428-16`).

Guarantees:
- No 11th or 21st attempt can bypass the 10-failure boundary dossier (`10`, `20`).
- Unavailable research channels hold in `PIVOT_RESEARCH_HOLD`.
- Re-evaluation drives `task_types` and `complexity` with a sticky upward floor
  (`effective_tier = max(proposed_complexity, min(10, old_floor + 1))`).
- Repeating the same underlying model family (including effort-only changes on
  the same model) is rejected.
- Tier 10 remains tier 10 at maximum effort (`max`, or `high` for Gemini).
- If no different underlying model in the accepted catalog meets the escalated
  tier floor, the task holds in `CAPABILITY_HOLD` instead of downgrading.
"""
from __future__ import annotations

from copy import deepcopy
import json
import time
from typing import Any

from .failure_dossier_428 import FailureDossierStore
from .task_routing import digest, five_model_options, select_candidates, validate_task_tags
from .workflow_428 import AttemptLedger, _id, _sha, _text, assessment


class PivotHoldError(ValueError):
    """Raised when a pivot cannot proceed due to incomplete research or missing capability."""

    def __init__(self, hold_status: str, message: str):
        super().__init__(message)
        self.hold_status = hold_status


def select_pivot_candidates(
    catalog: dict[str, Any],
    task_types: list[str],
    effective_tier: int,
    *,
    last_failed_model: str,
) -> list[dict[str, Any]]:
    """Return catalog options meeting `effective_tier` on a different underlying model family."""
    tags = validate_task_tags(task_types)
    if type(effective_tier) is not int or not 1 <= effective_tier <= 10:
        raise ValueError("effective_tier must be an integer in 1..10")
    _id(last_failed_model)

    models = catalog.get("models") or {}
    try:
        five_ids = [
            opt["model_id"]
            for opt in five_model_options(catalog, tags, effective_tier)
            if opt.get("meets_floor")
        ]
    except (ValueError, KeyError):
        five_ids = []
    try:
        cand_ids = select_candidates(
            catalog,
            tags,
            effective_tier,
            exclude_families=(last_failed_model,),
        )
    except (ValueError, KeyError):
        cand_ids = []
    ordered = [
        pid
        for pid in dict.fromkeys(five_ids + cand_ids + list(models.keys()))
        if pid in models
    ]

    tier_str = str(effective_tier)
    eligible: list[dict[str, Any]] = []
    for prof_id in ordered:
        spec = models.get(prof_id) or {}
        family = spec.get("family", "")
        effort = spec.get("effort", "")
        provider = spec.get("provider", "")
        scores = spec.get("scores") or {}
        if family == last_failed_model:
            continue
        if effective_tier == 10:
            required_max = "high" if provider == "gemini" or family.startswith("gemini-") else "max"
            if effort != required_max:
                continue
        if not all(
            scores.get(tag) is not None
            and scores[tag] >= catalog["task_types"][tag]["tiers"][tier_str]["floor"]
            for tag in tags
        ):
            continue
        eligible.append(
            {
                "profile_id": prof_id,
                "family": family,
                "effort": effort,
                "scores": {tag: scores[tag] for tag in tags},
                "meets_floor": True,
            }
        )
    return eligible


class PivotRuntime:
    """Enforces researched 10-failure boundary dossiers and sticky higher-tier model pivots (`P428-16`)."""

    def __init__(
        self,
        ledger: AttemptLedger,
        catalog: dict[str, Any],
        *,
        dossier_store: FailureDossierStore | None = None,
        clock=time.time,
    ):
        self.ledger = ledger
        self.catalog = deepcopy(catalog)
        self.dossier_store = dossier_store or FailureDossierStore(ledger, clock=clock)
        self.clock = clock
        with self.ledger._write() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS task428_pivots(
                    pivot_key TEXT PRIMARY KEY,
                    lineage_root TEXT NOT NULL,
                    boundary INTEGER NOT NULL,
                    dossier_id TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    effective_tier INTEGER NOT NULL,
                    task_types_json TEXT NOT NULL,
                    selected_profile_id TEXT NOT NULL,
                    selected_model_family TEXT NOT NULL,
                    selected_effort TEXT NOT NULL,
                    children_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    def evaluate_pivot(
        self,
        lineage_root: str,
        *,
        strategy: str = "pivot",
        task_types: list[str],
        proposed_complexity: int,
        rationale: str,
        selected_profile_id: str | None = None,
        children: list[str] | None = None,
    ) -> dict[str, Any]:
        """Validate the boundary dossier, sticky upward floor, and different underlying model, then execute the pivot."""
        _id(lineage_root)
        state = self.ledger.status(lineage_root)
        boundary = state["failures"]
        if boundary not in (10, 20, 30) or state["stage"] not in ("PIVOT_RESEARCH", "LOCKED") or not state["research_due"]:
            raise ValueError(f"Lineage '{lineage_root}' is not at a pending 10-failure pivot boundary")

        dossier = self.dossier_store.get_dossier(lineage_root, boundary)
        if dossier is None:
            raise PivotHoldError(
                "MISSING_FAILURE_DOSSIER",
                f"Boundary-{boundary} failure dossier must be compiled before any pivot or resumed attempt",
            )
        if not dossier.get("research_complete"):
            raise PivotHoldError(
                "PIVOT_RESEARCH_HOLD",
                f"Boundary-{boundary} research has unavailable channels; holding in PIVOT_RESEARCH_HOLD",
            )

        check = assessment(
            {
                "complexity": proposed_complexity,
                "task_types": task_types,
                "rationale": rationale,
            }
        )
        effective_tier = max(check["complexity"], min(10, int(state["floor"]) + 1))
        last_model = state["last_model"] or dossier["last_failed_model"]

        # If caller explicitly requested a profile_id, check model/effort repeat rules first
        models = self.catalog.get("models") or {}
        if selected_profile_id is not None:
            _id(selected_profile_id)
            if selected_profile_id not in models:
                raise ValueError(f"Unknown catalog profile_id: {selected_profile_id}")
            req_spec = models[selected_profile_id]
            if req_spec.get("family") == last_model:
                raise ValueError(
                    "Pivot cannot repeat the same underlying model or change only reasoning effort"
                )
            if effective_tier == 10:
                req_max = "high" if req_spec.get("family", "").startswith("gemini-") else "max"
                if req_spec.get("effort") != req_max:
                    raise ValueError("Tier 10 pivot requires maximum-effort profile")

        candidates = select_pivot_candidates(
            self.catalog,
            check["task_types"],
            effective_tier,
            last_failed_model=last_model,
        )
        if not candidates:
            raise PivotHoldError(
                "CAPABILITY_HOLD",
                f"No eligible different model in catalog meets escalated tier {effective_tier} for {check['task_types']}",
            )

        if selected_profile_id is not None:
            chosen = next((c for c in candidates if c["profile_id"] == selected_profile_id), None)
            if chosen is None:
                raise PivotHoldError(
                    "CAPABILITY_HOLD",
                    f"Requested profile '{selected_profile_id}' does not meet escalated tier {effective_tier} floor",
                )
        else:
            chosen = candidates[0]

        children_list = list(children or [])
        ledger_proposal = {
            "strategy": strategy,
            "task_types": check["task_types"],
            "complexity": effective_tier,
            "rationale": check["rationale"],
            "next_model": chosen["family"],
            "selected_profile_id": chosen["profile_id"],
            "children": children_list,
        }
        updated_state = self.ledger.pivot(
            lineage_root,
            dossier["research"],
            ledger_proposal,
            dossier["dossier_sha256"],
        )

        pkey = f"{lineage_root}::{boundary}"
        now = float(self.clock())
        with self.ledger._write() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO task428_pivots VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    pkey,
                    lineage_root,
                    boundary,
                    dossier["dossier_id"],
                    strategy,
                    effective_tier,
                    json.dumps(check["task_types"]),
                    chosen["profile_id"],
                    chosen["family"],
                    chosen["effort"],
                    json.dumps(children_list),
                    now,
                ),
            )
        return {
            "lineage_root": lineage_root,
            "boundary": boundary,
            "dossier_id": dossier["dossier_id"],
            "strategy": strategy,
            "effective_tier": effective_tier,
            "task_types": check["task_types"],
            "selected_profile_id": chosen["profile_id"],
            "selected_model_family": chosen["family"],
            "selected_effort": chosen["effort"],
            "children": children_list,
            "lineage_state": updated_state,
        }

    def recover_pivot_record(self, lineage_root: str, boundary: int) -> dict[str, Any]:
        """Repair only the projection after the ledger's authoritative pivot commit."""
        state = self.ledger.status(lineage_root)
        committed = next((p for p in state['pivots'] if p['after_failures'] == boundary), None)
        dossier = self.dossier_store.get_dossier(lineage_root, boundary)
        if not committed or not dossier or committed['evidence_sha256'] != dossier['dossier_sha256']:
            raise ValueError('Pivot recovery lacks its exact committed dossier')
        proposal = committed['proposal']
        selected = proposal.get('selected_profile_id')
        candidates = select_pivot_candidates(self.catalog, proposal['task_types'], proposal['complexity'],
                                            last_failed_model=dossier['last_failed_model'])
        chosen = next((c for c in candidates if c['profile_id'] == selected
                       and c['family'] == proposal['next_model']), None)
        if chosen is None:
            raise ValueError('Pivot recovery lacks the exact accepted profile commitment')
        with self.ledger._write() as conn:
            conn.execute('INSERT OR IGNORE INTO task428_pivots VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (f'{lineage_root}::{boundary}', lineage_root, boundary, dossier['dossier_id'], proposal['strategy'],
                 proposal['complexity'], json.dumps(proposal['task_types']), selected, chosen['family'], chosen['effort'],
                 json.dumps(proposal['children']), float(self.clock())))
        return self.get_pivot_record(lineage_root, boundary)

    def get_pivot_record(self, lineage_root: str, boundary: int) -> dict[str, Any] | None:
        _id(lineage_root)
        pkey = f"{lineage_root}::{boundary}"
        with self.ledger._write() as conn:
            row = conn.execute(
                "SELECT * FROM task428_pivots WHERE pivot_key=?",
                (pkey,),
            ).fetchone()
        if row is None:
            return None
        return {
            "lineage_root": row["lineage_root"],
            "boundary": row["boundary"],
            "dossier_id": row["dossier_id"],
            "strategy": row["strategy"],
            "effective_tier": row["effective_tier"],
            "task_types": json.loads(row["task_types_json"]),
            "selected_profile_id": row["selected_profile_id"],
            "selected_model_family": row["selected_model_family"],
            "selected_effort": row["selected_effort"],
            "children": json.loads(row["children_json"]),
        }
