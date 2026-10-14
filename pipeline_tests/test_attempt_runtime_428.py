"""Tests for `P428-15`: Bind actual outcomes to quality attempt accounting (`attempt_runtime_428.py`)."""
from __future__ import annotations

from pathlib import Path

import pytest

from cochem_pipeline.attempt_runtime_428 import (
    AttemptAccountingRuntime,
    classify_attempt_outcome,
)
from cochem_pipeline.task_routing import digest


def _research_fixture() -> dict:
    return {
        kind: {
            "query": "Failure root cause and pivot options",
            "status": "found",
            "receipt_sha256": digest(f"rcpt-{kind}"),
            "sources": [{"id": f"src-{kind}", "sha256": digest(f"body-{kind}")}],
        }
        for kind in ("internet", "wiki_rag", "papers")
    }


def test_wbs_microtasks_have_independent_budgets_and_can_run_simultaneously(tmp_path: Path) -> None:
    rt = AttemptAccountingRuntime(tmp_path / "attempts428.db")
    root_m1 = rt.wbs_microtask_lineage_root("task-wbs", "m1")
    root_m2 = rt.wbs_microtask_lineage_root("task-wbs", "m2")

    # Both independent WBS microtasks can start active attempts simultaneously
    att1 = rt.start_board_attempt(
        "job-m1",
        "att-1",
        1,
        lineage_root=root_m1,
        model_family="gpt-6.1-sol",
        complexity=3,
    )
    att2 = rt.start_board_attempt(
        "job-m2",
        "att-1",
        1,
        lineage_root=root_m2,
        model_family="gpt-6.1-sol",
        complexity=4,
    )
    assert att1["status"] == "ACTIVE"
    assert att2["status"] == "ACTIVE"

    # Quality failure on m1 charges m1 (failures=1) while m2 stays at 0 failures
    st1 = rt.record_board_outcome(
        "job-m1",
        "att-1",
        1,
        category="tests_failed",
        evidence_sha256=digest("m1-fail-1"),
    )
    st2 = rt.record_board_outcome(
        "job-m2",
        "att-1",
        1,
        category="success",
        evidence_sha256=digest("m2-ok-1"),
    )
    assert st1["failures"] == 1
    assert st2["failures"] == 0


def test_fenced_outcomes_at_9_10_19_20_29_30_and_fractured_shared_history(tmp_path: Path) -> None:
    db_path = tmp_path / "attempts_boundaries.db"
    rt = AttemptAccountingRuntime(db_path)
    root = "task-lineage-root"
    rt.ensure_lineage(root, complexity=4)

    # Attempts 1..9: 9th failure leaves stage READY with failures == 9
    for idx in range(1, 10):
        rt.start_board_attempt(
            f"job-{idx}",
            f"att-{idx}",
            idx,
            lineage_root=root,
            model_family="gpt-6.1-sol",
            complexity=4,
        )
        state = rt.record_board_outcome(
            f"job-{idx}",
            f"att-{idx}",
            idx,
            category="quality_failure",
            evidence_sha256=digest(f"fail-{idx}"),
        )
    assert state["failures"] == 9
    assert state["stage"] == "READY"

    # At 9 failures, start attempt 10; a simultaneous second claim on the same lineage is rejected!
    rt.start_board_attempt(
        "job-10",
        "att-10",
        10,
        lineage_root=root,
        model_family="gpt-6.1-sol",
        complexity=4,
    )
    with pytest.raises(ValueError, match="active quality cycle"):
        rt.start_board_attempt(
            "job-10-race",
            "att-10-race",
            1,
            lineage_root=root,
            model_family="gpt-6.1-sol",
            complexity=4,
        )

    # 10th failure triggers PIVOT_RESEARCH and blocks any 11th claim before pivot
    state_10 = rt.record_board_outcome(
        "job-10",
        "att-10",
        10,
        category="validation_error",
        evidence_sha256=digest("fail-10"),
    )
    assert state_10["failures"] == 10
    assert state_10["stage"] == "PIVOT_RESEARCH"
    with pytest.raises(ValueError, match="held, locked or requires its pivot model"):
        rt.start_board_attempt(
            "job-11-blocked",
            "att-11",
            11,
            lineage_root=root,
            model_family="claude-opus-5-5",
            complexity=5,
        )

    # Pivot with fracture into frac-a and frac-b: descendants share the 10-failure history
    rt.ledger.pivot(
        root,
        _research_fixture(),
        {
            "strategy": "fracture",
            "task_types": ["COD-TERM"],
            "complexity": 5,
            "rationale": "Split parser and validator after 10 failures",
            "next_model": "claude-opus-5-5",
            "children": ["frac-a", "frac-b"],
        },
        digest("pivot-10"),
    )
    assert rt.ledger.status("frac-a")["failures"] == 10
    assert rt.ledger.status("frac-b")["failures"] == 10

    # Attempts 11..19 across fractured descendants frac-a and frac-b
    for idx in range(11, 20):
        member = "frac-a" if idx % 2 == 1 else "frac-b"
        rt.start_board_attempt(
            f"job-{idx}",
            f"att-{idx}",
            idx,
            lineage_root=root,
            member_id=member,
            model_family="claude-opus-5-5",
            complexity=5,
        )
        state = rt.record_board_outcome(
            f"job-{idx}",
            f"att-{idx}",
            idx,
            category="tests_failed",
            evidence_sha256=digest(f"fail-{idx}"),
        )
    assert state["failures"] == 19
    assert state["stage"] == "READY"

    # 20th failure triggers second PIVOT_RESEARCH
    rt.start_board_attempt(
        "job-20",
        "att-20",
        20,
        lineage_root=root,
        member_id="frac-a",
        model_family="claude-opus-5-5",
        complexity=5,
    )
    state_20 = rt.record_board_outcome(
        "job-20",
        "att-20",
        20,
        category="timeout",
        evidence_sha256=digest("fail-20"),
    )
    assert state_20["failures"] == 20
    assert state_20["stage"] == "PIVOT_RESEARCH"

    # Second pivot at 20 failures to gpt-6-astra
    rt.ledger.pivot(
        root,
        _research_fixture(),
        {
            "strategy": "pivot",
            "task_types": ["COD-TERM"],
            "complexity": 7,
            "rationale": "Escalate to higher model after 20 failures",
            "next_model": "gpt-6-astra",
            "children": [],
        },
        digest("pivot-20"),
    )

    # Attempts 21..29: 29th failure leaves stage READY with failures == 29
    for idx in range(21, 30):
        rt.start_board_attempt(
            f"job-{idx}",
            f"att-{idx}",
            idx,
            lineage_root=root,
            member_id="frac-b",
            model_family="gpt-6-astra",
            complexity=7,
        )
        state = rt.record_board_outcome(
            f"job-{idx}",
            f"att-{idx}",
            idx,
            category="oom",
            evidence_sha256=digest(f"fail-{idx}"),
        )
    assert state["failures"] == 29
    assert state["stage"] == "READY"

    # 30th failure locks the entire lineage permanently (both frac-a and frac-b)
    rt.start_board_attempt(
        "job-30",
        "att-30",
        30,
        lineage_root=root,
        member_id="frac-a",
        model_family="gpt-6-astra",
        complexity=7,
    )
    state_30 = rt.record_board_outcome(
        "job-30",
        "att-30",
        30,
        category="quality_failure",
        evidence_sha256=digest("fail-30"),
    )
    assert state_30["failures"] == 30
    assert state_30["stage"] == "LOCKED"
    assert rt.ledger.status("frac-b")["stage"] == "LOCKED"


def test_availability_waits_and_crash_outbox_reconciliation_never_double_charge(tmp_path: Path) -> None:
    db_path = tmp_path / "attempts_outbox.db"
    rt = AttemptAccountingRuntime(db_path)
    root = "task-outbox-root"

    # 1. Availability waits (auth, quota, resource, rate_limit, capacity) never charge failures
    for idx, cat in enumerate(["auth", "quota", "resource", "rate_limit", "capacity"], start=1):
        assert classify_attempt_outcome(cat) == "availability"
        rt.start_board_attempt(
            "job-avail",
            f"att-avail-{idx}",
            idx,
            lineage_root=root,
            model_family="gpt-6.1-sol",
            complexity=3,
        )
        st = rt.record_board_outcome(
            "job-avail",
            f"att-avail-{idx}",
            idx,
            category=cat,
            evidence_sha256=digest(f"avail-{idx}"),
        )
        assert st["failures"] == 0
        assert st["stage"] == "READY"

    # 2. Simulate crash window: stage outcome in outbox before reconciling to AttemptLedger
    rt.start_board_attempt(
        "job-crash",
        "att-crash-1",
        10,
        lineage_root=root,
        model_family="gpt-6.1-sol",
        complexity=3,
    )
    staged = rt.stage_board_outcome(
        "job-crash",
        "att-crash-1",
        10,
        category="quality_failure",
        evidence_sha256=digest("crash-ev-1"),
    )
    assert staged["status"] == "OUTCOME_STAGED"
    # Before reconciliation, ledger still has 0 committed failures and an active lease
    assert rt.ledger.status(root)["failures"] == 0

    # Restart runtime and reconcile outbox -> charges exactly once (failures == 1)
    rt_restarted = AttemptAccountingRuntime(db_path)
    reconciled = rt_restarted.reconcile_outbox()
    assert len(reconciled) == 1
    assert reconciled[0]["failures"] == 1

    # Duplicate reconciliation or duplicate record_board_outcome call is a no-op (still failures == 1)
    assert rt_restarted.reconcile_outbox() == []
    dup_state = rt_restarted.record_board_outcome(
        "job-crash",
        "att-crash-1",
        10,
        category="quality_failure",
        evidence_sha256=digest("crash-ev-1"),
    )
    assert dup_state["failures"] == 1

    # Attempting to mutate a finished attempt's outcome or use an unknown fence raises ValueError
    with pytest.raises(ValueError, match="immutable"):
        rt_restarted.record_board_outcome(
            "job-crash",
            "att-crash-1",
            10,
            category="success",
            evidence_sha256=digest("different-ev"),
        )
    with pytest.raises(ValueError, match="Unknown or stale attempt fence"):
        rt_restarted.record_board_outcome(
            "job-crash",
            "att-stale-99",
            99,
            category="quality_failure",
            evidence_sha256=digest("stale"),
        )
