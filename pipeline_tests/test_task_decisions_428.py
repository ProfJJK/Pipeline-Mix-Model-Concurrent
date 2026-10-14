"""Tests for `P428-18`: Locked-task decisions on the next status request (`task_decisions_428.py`, `operator_views.py`)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cochem_pipeline.attempt_runtime_428 import AttemptAccountingRuntime
from cochem_pipeline.pivot_runtime_428 import PivotRuntime
from cochem_pipeline.task_decisions_428 import LockedTaskDecisionStore, sanitize_status_link
from cochem_pipeline.task_routing import digest


ROOT = Path(__file__).resolve().parents[1]


def _load_catalog() -> dict:
    return json.loads((ROOT / "docs" / "4.2.8" / "routing-candidate.json").read_text(encoding="utf-8"))


def _three_channel_research(*, papers_status: str = "found") -> dict:
    res = {
        kind: {
            "query": f"Locked root cause {kind}",
            "status": "found",
            "receipt_sha256": digest(f"lock-rcpt-{kind}"),
            "sources": [{"id": f"src-{kind}", "sha256": digest(f"body-{kind}")}],
        }
        for kind in ("internet", "wiki_rag", "papers")
    }
    if papers_status != "found":
        res["papers"]["status"] = papers_status
        res["papers"]["sources"] = []
    return res


def _drive_lineage_to_30_failures(
    acct: AttemptAccountingRuntime,
    pivot_rt: PivotRuntime,
    root: str,
) -> None:
    acct.ensure_lineage(root, complexity=4)
    # 1..10
    for idx in range(1, 11):
        acct.start_board_attempt(f"j-{root}-{idx}", f"a-{idx}", idx, lineage_root=root, model_family="gpt-6-luna", complexity=4)
        acct.record_board_outcome(f"j-{root}-{idx}", f"a-{idx}", idx, category="tests_failed", evidence_sha256=digest(f"{root}-{idx}"))
    pivot_rt.dossier_store.record_dossier(
        root, 10, research_channels=_three_channel_research(), root_cause_synthesis="Boundary 10", hypotheses=["H10"]
    )
    piv10 = pivot_rt.evaluate_pivot(root, task_types=["COD-TERM"], proposed_complexity=5, rationale="Escalate at 10")
    m10 = piv10["selected_model_family"]

    # 11..20
    for idx in range(11, 21):
        acct.start_board_attempt(f"j-{root}-{idx}", f"a-{idx}", idx, lineage_root=root, model_family=m10, complexity=5)
        acct.record_board_outcome(f"j-{root}-{idx}", f"a-{idx}", idx, category="tests_failed", evidence_sha256=digest(f"{root}-{idx}"))
    pivot_rt.dossier_store.record_dossier(
        root, 20, research_channels=_three_channel_research(), root_cause_synthesis="Boundary 20", hypotheses=["H20"]
    )
    piv20 = pivot_rt.evaluate_pivot(root, task_types=["COD-TERM"], proposed_complexity=6, rationale="Escalate at 20")
    m20 = piv20["selected_model_family"]

    # 21..30 -> LOCKED
    for idx in range(21, 31):
        acct.start_board_attempt(f"j-{root}-{idx}", f"a-{idx}", idx, lineage_root=root, model_family=m20, complexity=6)
        acct.record_board_outcome(f"j-{root}-{idx}", f"a-{idx}", idx, category="tests_failed", evidence_sha256=digest(f"{root}-{idx}"))


def test_status_discovery_repeat_reads_missing_final_dossier_and_credential_scrubbing(tmp_path: Path) -> None:
    catalog = _load_catalog()
    acct = AttemptAccountingRuntime(tmp_path / "decisions428.db")
    pivot_rt = PivotRuntime(acct.ledger, catalog)
    dec_store = LockedTaskDecisionStore(acct.ledger, dossier_store=pivot_rt.dossier_store)

    root = "task-locked-01"
    _drive_lineage_to_30_failures(acct, pivot_rt, root)

    # Register links containing embedded credentials -> must be scrubbed in status output!
    dec_store.register_context_links(
        root,
        artifact_links=["https://owner:s3cr3t@local.host/artifacts/task-locked-01?token=abc123secret&view=1"],
        failure_links=["https://local.host/journal/failures?api_key=xyz987"],
        dossier_links=["Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.secret.sig /dossiers/30.json"],
    )

    # 1. Before boundary-30 dossier is recorded: status reports MISSING_FINAL_DOSSIER and actionable=False
    packets_missing = dec_store.status_projection(root)
    assert len(packets_missing) == 1
    pkt0 = packets_missing[0]
    assert pkt0["stage"] == "LOCKED"
    assert pkt0["failures"] == 30
    assert pkt0["dossier_state"] == "MISSING_FINAL_DOSSIER"
    assert pkt0["actionable"] is False

    # Credentials must be scrubbed from all status links
    links_blob = json.dumps(pkt0["links"])
    assert "s3cr3t" not in links_blob
    assert "abc123secret" not in links_blob
    assert "xyz987" not in links_blob
    assert "eyJhbGciOiJIUzI1NiJ9" not in links_blob
    assert "REDACTED" in links_blob

    # Repeat reads are 100% deterministic and never unlock or mutate state
    assert dec_store.status_projection(root) == packets_missing

    # Owner decision while boundary-30 dossier is missing is rejected
    with pytest.raises(ValueError, match="MISSING_FINAL_DOSSIER"):
        dec_store.apply_owner_decision(
            root,
            action="defer",
            expected_packet_sha256=pkt0["packet_revision_sha256"],
            authenticated_owner_receipt_id="owner-rcpt-01",
            owner_authenticated=True,
            rationale="Try defer before final dossier",
        )

    # 2. Record boundary-30 dossier -> status becomes READY and actionable=True
    pivot_rt.dossier_store.record_dossier(
        root,
        30,
        research_channels=_three_channel_research(),
        root_cause_synthesis="Irreconcilable upstream schema contradiction across 30 attempts",
        hypotheses=["Revise SRS requirement R3 or defer task"],
    )
    pkt_ready = dec_store.status_projection(root)[0]
    assert pkt_ready["dossier_state"] == "READY"
    assert pkt_ready["actionable"] is True
    assert pkt_ready["root_cause_synthesis"].startswith("Irreconcilable upstream")
    assert {opt["action"] for opt in pkt_ready["options"]} == {"revise_scope", "defer"}
    for opt in pkt_ready["options"]:
        assert opt["pros"] and opt["cons"] and opt["risks"]


def test_refusal_of_unauthenticated_unlock_stale_action_and_audited_defer_and_revise(tmp_path: Path) -> None:
    catalog = _load_catalog()
    acct = AttemptAccountingRuntime(tmp_path / "decisions_actions.db")
    pivot_rt = PivotRuntime(acct.ledger, catalog)
    dec_store = LockedTaskDecisionStore(acct.ledger, dossier_store=pivot_rt.dossier_store)

    root_defer = "task-locked-defer"
    _drive_lineage_to_30_failures(acct, pivot_rt, root_defer)
    pivot_rt.dossier_store.record_dossier(
        root_defer,
        30,
        research_channels=_three_channel_research(),
        root_cause_synthesis="Final synthesis for defer",
        hypotheses=["Defer until upstream library fixes bug"],
    )
    pkt = dec_store.status_projection(root_defer)[0]

    # 1. Refusal of unauthenticated decision/unlock
    with pytest.raises(PermissionError, match="Unauthenticated"):
        dec_store.apply_owner_decision(
            root_defer,
            action="defer",
            expected_packet_sha256=pkt["packet_revision_sha256"],
            authenticated_owner_receipt_id="forged-rcpt",
            owner_authenticated=False,
            rationale="Model trying to self-defer",
        )

    # 2. Refusal of raw unlock or budget reset action even when authenticated
    with pytest.raises(ValueError, match="raw unlock or budget reset is forbidden"):
        dec_store.apply_owner_decision(
            root_defer,
            action="unlock",
            expected_packet_sha256=pkt["packet_revision_sha256"],
            authenticated_owner_receipt_id="owner-rcpt-unlock",
            owner_authenticated=True,
            rationale="Try to unlock directly",
        )

    # 3. Stale packet hash is rejected
    with pytest.raises(ValueError, match="Stale owner decision"):
        dec_store.apply_owner_decision(
            root_defer,
            action="defer",
            expected_packet_sha256="0" * 64,
            authenticated_owner_receipt_id="owner-rcpt-stale",
            owner_authenticated=True,
            rationale="Stale hash",
        )

    # 4. Valid authenticated defer decision
    deferred_pkt = dec_store.apply_owner_decision(
        root_defer,
        action="defer",
        expected_packet_sha256=pkt["packet_revision_sha256"],
        authenticated_owner_receipt_id="owner-rcpt-defer-1",
        owner_authenticated=True,
        rationale="Deferring task while preserving all 30 failure receipts",
    )
    assert deferred_pkt["disposition"] == "DEFERRED"
    assert deferred_pkt["actionable"] is False
    assert deferred_pkt["failures"] == 30
    assert len(deferred_pkt["decisions"]) == 1

    # Replaying the old packet hash after defer is rejected as stale
    with pytest.raises(ValueError, match="Stale owner decision"):
        dec_store.apply_owner_decision(
            root_defer,
            action="defer",
            expected_packet_sha256=pkt["packet_revision_sha256"],
            authenticated_owner_receipt_id="owner-rcpt-defer-2",
            owner_authenticated=True,
            rationale="Replay",
        )

    # No hidden retry after lock or decision: starting a 31st attempt is still refused!
    with pytest.raises(ValueError, match="locked"):
        acct.start_board_attempt(
            "j-31-illegal", "a-31", 31, lineage_root=root_defer, model_family="gpt-6-astra", complexity=7
        )

    # 5. Valid authenticated revise_scope decision on a second locked lineage
    root_rev = "task-locked-revise"
    _drive_lineage_to_30_failures(acct, pivot_rt, root_rev)
    pivot_rt.dossier_store.record_dossier(
        root_rev,
        30,
        research_channels=_three_channel_research(),
        root_cause_synthesis="Final synthesis for revise_scope",
        hypotheses=["Split out optional streaming requirement"],
    )
    pkt_rev = dec_store.status_projection(root_rev)[0]

    # Reusing the same locked task ID as revised_task_id is rejected
    with pytest.raises(ValueError, match="distinct new task identifier"):
        dec_store.apply_owner_decision(
            root_rev,
            action="revise_scope",
            expected_packet_sha256=pkt_rev["packet_revision_sha256"],
            authenticated_owner_receipt_id="owner-rcpt-rev-bad",
            owner_authenticated=True,
            rationale="Try to overwrite locked lineage ID",
            revised_task_id=root_rev,
            revised_objective="Same ID",
        )

    revised_pkt = dec_store.apply_owner_decision(
        root_rev,
        action="revise_scope",
        expected_packet_sha256=pkt_rev["packet_revision_sha256"],
        authenticated_owner_receipt_id="owner-rcpt-rev-ok",
        owner_authenticated=True,
        rationale="Create narrowed v2 task while preserving v1 30-failure audit history",
        revised_task_id="task-locked-revise-v2",
        revised_objective="Deliver synchronous batch parser only",
    )
    assert revised_pkt["disposition"] == "REVISED_NEW_REVISION"
    assert revised_pkt["failures"] == 30
    assert revised_pkt["decisions"][0]["revised_task_id"] == "task-locked-revise-v2"
    assert revised_pkt["decisions"][0]["retained_failures"] == 30
    assert acct.ledger.status(root_rev)["failures"] == 30
    assert acct.ledger.status(root_rev)["stage"] == "LOCKED"
