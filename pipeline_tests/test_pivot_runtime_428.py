"""Tests for `P428-16`: Researched failure dossier and higher-model pivot (`failure_dossier_428.py`, `pivot_runtime_428.py`)."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from cochem_pipeline.attempt_runtime_428 import AttemptAccountingRuntime
from cochem_pipeline.failure_dossier_428 import FailureDossierStore, compile_failure_dossier
from cochem_pipeline.pivot_runtime_428 import PivotHoldError, PivotRuntime
from cochem_pipeline.task_routing import digest


ROOT = Path(__file__).resolve().parents[1]


def _load_catalog() -> dict:
    return json.loads((ROOT / "docs" / "4.2.8" / "routing-candidate.json").read_text(encoding="utf-8"))


def _three_channel_research(*, papers_status: str = "found") -> dict:
    res = {
        kind: {
            "query": f"Root cause analysis for {kind}",
            "status": "found",
            "receipt_sha256": digest(f"rcpt-{kind}"),
            "sources": [{"id": f"src-{kind}", "sha256": digest(f"body-{kind}")}],
        }
        for kind in ("internet", "wiki_rag", "papers")
    }
    if papers_status != "found":
        res["papers"]["status"] = papers_status
        res["papers"]["sources"] = []
    return res


def _charge_ten_failures(
    acct: AttemptAccountingRuntime,
    lineage_root: str,
    *,
    start_idx: int = 1,
    model_family: str = "gpt-6.1-sol",
    complexity: int = 5,
) -> None:
    for idx in range(start_idx, start_idx + 10):
        acct.start_board_attempt(
            f"job-{idx}",
            f"att-{idx}",
            idx,
            lineage_root=lineage_root,
            model_family=model_family,
            complexity=complexity,
        )
        acct.record_board_outcome(
            f"job-{idx}",
            f"att-{idx}",
            idx,
            category="tests_failed",
            evidence_sha256=digest(f"{lineage_root}-ev-{idx}"),
        )


def test_dossier_provenance_unavailable_research_and_effort_repeat_rejected(tmp_path: Path) -> None:
    catalog = _load_catalog()
    acct = AttemptAccountingRuntime(tmp_path / "pivot428.db")
    pivot_rt = PivotRuntime(acct.ledger, catalog)
    root = "task-pivot-01"
    acct.ensure_lineage(root, complexity=5)

    # Cannot compile boundary-10 dossier before 10 failures occur
    with pytest.raises(ValueError, match="Cannot compile boundary-10 dossier"):
        pivot_rt.dossier_store.record_dossier(
            root,
            10,
            research_channels=_three_channel_research(),
            root_cause_synthesis="Premature dossier",
            hypotheses=["H1"],
        )

    _charge_ten_failures(acct, root, start_idx=1, model_family="gpt-6.1-sol", complexity=5)

    # No 11th attempt or pivot can bypass the dossier
    with pytest.raises(PivotHoldError) as exc_info:
        pivot_rt.evaluate_pivot(
            root,
            task_types=["COD-TERM"],
            proposed_complexity=6,
            rationale="Attempt pivot without dossier",
        )
    assert exc_info.value.hold_status == "MISSING_FAILURE_DOSSIER"

    # Tampered evidence_sha256 in causes_by_attempt is rejected
    with pytest.raises(ValueError, match="tampered evidence_sha256"):
        pivot_rt.dossier_store.record_dossier(
            root,
            10,
            causes_by_attempt=[
                {
                    "attempt_number": 1,
                    "evidence_sha256": "f" * 64,
                    "cause_summary": "Forged hash",
                    "hypothesis": "Bad",
                }
            ],
            research_channels=_three_channel_research(),
            root_cause_synthesis="Tampered",
            hypotheses=["H1"],
        )

    # Unavailable research channel records dossier with research_complete=False and holds in PIVOT_RESEARCH_HOLD
    dossier_unavail = pivot_rt.dossier_store.record_dossier(
        root,
        10,
        research_channels=_three_channel_research(papers_status="unavailable"),
        root_cause_synthesis="Numerical instability in Davidson preconditioner",
        hypotheses=["Switch preconditioner to Jacobi-Davidson"],
    )
    assert dossier_unavail["research_complete"] is False
    with pytest.raises(PivotHoldError) as exc_hold:
        pivot_rt.evaluate_pivot(
            root,
            task_types=["COD-TERM"],
            proposed_complexity=6,
            rationale="Try pivot with unavailable papers channel",
        )
    assert exc_hold.value.hold_status == "PIVOT_RESEARCH_HOLD"

    # Record complete 3-channel research dossier
    dossier_ok = pivot_rt.dossier_store.record_dossier(
        root,
        10,
        research_channels=_three_channel_research(papers_status="found"),
        root_cause_synthesis="Numerical instability in Davidson preconditioner",
        hypotheses=["Switch preconditioner to Jacobi-Davidson"],
    )
    assert dossier_ok["research_complete"] is True

    # Repeating the same underlying model family (even at higher effort sol-max) is rejected!
    with pytest.raises(ValueError, match="cannot repeat the same underlying model"):
        pivot_rt.evaluate_pivot(
            root,
            task_types=["COD-TERM"],
            proposed_complexity=6,
            rationale="Only bump effort on sol",
            selected_profile_id="sol-max",
        )


def test_classified_pivot_sticky_upward_floor_and_resumed_attempt(tmp_path: Path) -> None:
    catalog = _load_catalog()
    acct = AttemptAccountingRuntime(tmp_path / "pivot_sticky.db")
    pivot_rt = PivotRuntime(acct.ledger, catalog)
    root = "task-pivot-sticky"
    acct.ensure_lineage(root, complexity=5)
    _charge_ten_failures(acct, root, start_idx=1, model_family="gpt-6.1-sol", complexity=5)

    pivot_rt.dossier_store.record_dossier(
        root,
        10,
        research_channels=_three_channel_research(),
        root_cause_synthesis="Requires formal reasoning and higher tier",
        hypotheses=["Escalate to higher model with SCI-FORMAL"],
    )

    # Propose complexity=4 when old_floor=5 -> sticky upward floor forces effective_tier=6!
    piv = pivot_rt.evaluate_pivot(
        root,
        task_types=["COD-TERM", "SCI-FORMAL"],
        proposed_complexity=4,
        rationale="Reclassified with formal verification",
    )
    assert piv["effective_tier"] == 6
    assert piv["selected_model_family"] != "gpt-6.1-sol"
    assert piv["lineage_state"]["stage"] == "READY"
    assert piv["lineage_state"]["floor"] == 6

    # Attempt 11 CANNOT start on the old model or an unselected model
    with pytest.raises(ValueError, match="requires its pivot model"):
        acct.start_board_attempt(
            "job-11-wrong",
            "att-11",
            11,
            lineage_root=root,
            model_family="gpt-6.1-sol",
            complexity=6,
        )

    # Attempt 11 succeeds on the selected pivot model!
    att11 = acct.start_board_attempt(
        "job-11-ok",
        "att-11",
        11,
        lineage_root=root,
        model_family=piv["selected_model_family"],
        complexity=piv["effective_tier"],
    )
    assert att11["status"] == "ACTIVE"
    final_st = acct.record_board_outcome(
        "job-11-ok",
        "att-11",
        11,
        category="success",
        evidence_sha256=digest("ok-11"),
    )
    assert final_st["failures"] == 10
    assert final_st["next_model"] is None


def test_tier_10_maximum_effort_and_missing_eligible_model_capability_hold(tmp_path: Path) -> None:
    from cochem_pipeline.task_routing import independent_review_calibration

    catalog = independent_review_calibration(_load_catalog())
    acct = AttemptAccountingRuntime(tmp_path / "pivot_tier10.db")
    pivot_rt = PivotRuntime(acct.ledger, catalog)
    root = "task-pivot-10"
    acct.ensure_lineage(root, complexity=10)
    _charge_ten_failures(acct, root, start_idx=1, model_family="gpt-6-astra", complexity=10)

    pivot_rt.dossier_store.record_dossier(
        root,
        10,
        research_channels=_three_channel_research(),
        root_cause_synthesis="Tier 10 boundary reached",
        hypotheses=["Switch to another tier-10 maximum-effort model"],
    )

    # Selecting a non-max-effort profile at tier 10 is rejected
    with pytest.raises(ValueError, match="maximum-effort"):
        pivot_rt.evaluate_pivot(
            root,
            task_types=["COD-TERM"],
            proposed_complexity=10,
            rationale="Try medium effort at tier 10",
            selected_profile_id="opus-med",
        )

    # Valid tier-10 pivot selects a different model at maximum effort
    piv10 = pivot_rt.evaluate_pivot(
        root,
        task_types=["COD-TERM"],
        proposed_complexity=10,
        rationale="Use maximum-effort alternative model at tier 10",
    )
    assert piv10["effective_tier"] == 10
    assert piv10["selected_model_family"] != "gpt-6-astra"
    assert piv10["selected_effort"] in ("max", "high")

    # If catalog has no alternative model meeting the floor, evaluate_pivot raises CAPABILITY_HOLD
    stripped_catalog = deepcopy(catalog)
    for prof_id, spec in list(stripped_catalog["models"].items()):
        if spec.get("family") != "gpt-6-astra":
            del stripped_catalog["models"][prof_id]
    acct_hold = AttemptAccountingRuntime(tmp_path / "pivot_caphold.db")
    pivot_hold_rt = PivotRuntime(acct_hold.ledger, stripped_catalog)
    acct_hold.ensure_lineage("task-cap-hold", complexity=8)
    _charge_ten_failures(acct_hold, "task-cap-hold", start_idx=1, model_family="gpt-6-astra", complexity=8)
    pivot_hold_rt.dossier_store.record_dossier(
        "task-cap-hold",
        10,
        research_channels=_three_channel_research(),
        root_cause_synthesis="Only astra in stripped catalog",
        hypotheses=["Hold for capability"],
    )
    with pytest.raises(PivotHoldError) as exc_cap:
        pivot_hold_rt.evaluate_pivot(
            "task-cap-hold",
            task_types=["COD-TERM"],
            proposed_complexity=9,
            rationale="No alternative model available",
        )
    assert exc_cap.value.hold_status == "CAPABILITY_HOLD"
