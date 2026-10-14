"""Tests for human SRS approval authority and revision-bound receipt broker (`P428-09`)."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import pytest

from cochem_pipeline.owner_approval_428 import (
    OwnerApprovalBroker,
    apply_owner_decision_to_state,
)
from cochem_pipeline.planning_journal import PlanningJournal
from cochem_pipeline.task_routing import digest
from cochem_pipeline.workflow_428 import accept_srs, new_task
from pipeline_tests.test_workflow_428 import document


ROOT = Path(__file__).resolve().parents[1]
OWNER_SECRET = "owner-dedicated-secret-428-9f8e7d6c5b4a3210-high-entropy"
SHARED_AGENT_TOKEN = "shared-agent-bearer-token-428-do-not-trust-for-owner"


def _catalog() -> dict:
    return json.loads((ROOT / "docs" / "4.2.8" / "routing-candidate.json").read_text(encoding="utf-8"))


def _doc(complexity: int = 9, summary: str = "Complete formal SRS document") -> dict:
    doc = deepcopy(document(complexity))
    doc["plan"] = "Step-by-step formal implementation plan: " + summary
    return doc


def test_shared_agent_token_and_model_json_cannot_grant_owner_approval(tmp_path: Path):
    with pytest.raises(ValueError, match="must never equal a shared agent bearer token"):
        OwnerApprovalBroker(
            tmp_path / "bad_broker.db",
            owner_secret=SHARED_AGENT_TOKEN,
            shared_agent_tokens={SHARED_AGENT_TOKEN},
        )

    broker = OwnerApprovalBroker(
        tmp_path / "owner_broker.db",
        owner_secret=OWNER_SECRET,
        shared_agent_tokens={SHARED_AGENT_TOKEN},
    )
    catalog = _catalog()
    results: dict[str, dict] = {}
    journal = PlanningJournal(
        tmp_path / "planning.db",
        catalog,
        model_result=results.get,
        owner_receipt=broker.load_for_journal,
        flash_context_limit=100000,
    )
    journal.create("task-sec-01", "Design high-complexity concurrency kernel")
    intent = journal.intent("task-sec-01")

    # Model attempts to smuggle approval fields inside SRS output -> rejected by schema
    forged_doc = _doc(9) | {"approved": True, "actor_kind": "human_owner"}
    results["job-forged"] = {
        "job_id": "job-forged",
        "intent_sha256": digest(intent),
        "profile_id": intent["candidate_profiles"][0],
        "status": "COMPLETED",
        "cleanup_verified": True,
        "output": forged_doc,
    }
    with pytest.raises(ValueError):
        journal.apply_model_result("task-sec-01", 0, "job-forged")

    # Legitimate SRS puts task into OWNER_APPROVAL
    results["job-srs"] = {
        "job_id": "job-srs",
        "intent_sha256": digest(intent),
        "profile_id": intent["candidate_profiles"][0],
        "status": "COMPLETED",
        "cleanup_verified": True,
        "output": _doc(9),
    }
    state = journal.apply_model_result("task-sec-01", 0, "job-srs")
    assert state["stage"] == "OWNER_APPROVAL"

    req = broker.create_request(state)
    with pytest.raises(PermissionError, match="Shared agent bearer token"):
        broker.record_decision(
            req["request_id"],
            decision="approved",
            owner_token=SHARED_AGENT_TOKEN,
        )
    with pytest.raises(PermissionError, match="Invalid human owner"):
        broker.record_decision(
            req["request_id"],
            decision="approved",
            owner_token="wrong-secret-token-0000000000000000000000",
        )


def test_only_complexity_8_to_10_requires_owner_approval(tmp_path: Path):
    broker = OwnerApprovalBroker(
        tmp_path / "owner_broker.db",
        owner_secret=OWNER_SECRET,
        shared_agent_tokens={SHARED_AGENT_TOKEN},
    )
    low_task = new_task("task-low", "Routine tier 6 task")
    low_srs = accept_srs(low_task, _doc(6), planner_model="gpt", flash_context_limit=100000)
    assert low_srs["stage"] == "RESEARCH"
    with pytest.raises(ValueError, match="Only complexity 8..10"):
        broker.create_request(low_srs)


def test_approved_revision_requested_and_rejected_transitions_and_invalidation(tmp_path: Path):
    broker = OwnerApprovalBroker(
        tmp_path / "owner_broker.db",
        owner_secret=OWNER_SECRET,
        shared_agent_tokens={SHARED_AGENT_TOKEN},
    )
    catalog = _catalog()
    results: dict[str, dict] = {}
    journal = PlanningJournal(
        tmp_path / "planning.db",
        catalog,
        model_result=results.get,
        owner_receipt=broker.load_for_journal,
        flash_context_limit=100000,
    )
    journal.create("task-lifecycle", "Architect tier-9 consensus engine")
    intent0 = journal.intent("task-lifecycle")
    results["job-1"] = {
        "job_id": "job-1",
        "intent_sha256": digest(intent0),
        "profile_id": intent0["candidate_profiles"][0],
        "status": "COMPLETED",
        "cleanup_verified": True,
        "output": _doc(9, "Draft 1 SRS"),
    }
    state1 = journal.apply_model_result("task-lifecycle", 0, "job-1")
    assert state1["stage"] == "OWNER_APPROVAL"

    # 1. Human owner requests revision -> moves to REVISING_SRS
    req1 = broker.create_request(state1)
    rcpt_rev = broker.record_decision(
        req1["request_id"],
        decision="revision_requested",
        owner_token=OWNER_SECRET,
        notes="Clarify quorum recovery invariants",
    )
    state_rev = journal.apply_owner_approval(
        "task-lifecycle",
        state1["journal_version"],
        rcpt_rev["receipt_id"],
    )
    assert state_rev["stage"] == "REVISING_SRS"
    assert state_rev["owner_feedback"]["decision"] == "revision_requested"
    assert "quorum recovery" in state_rev["owner_feedback"]["notes"]

    # 2. Planner produces Draft 2 SRS -> moves back to OWNER_APPROVAL at revision 2
    intent2 = journal.intent("task-lifecycle")
    results["job-2"] = {
        "job_id": "job-2",
        "intent_sha256": digest(intent2),
        "profile_id": intent2["candidate_profiles"][0],
        "status": "COMPLETED",
        "cleanup_verified": True,
        "output": _doc(9, "Draft 2 SRS with quorum recovery"),
    }
    state2 = journal.apply_model_result("task-lifecycle", state_rev["journal_version"], "job-2")
    assert state2["stage"] == "OWNER_APPROVAL"
    assert state2["revision"] == 2

    # Stale receipt from revision 1 cannot approve revision 2
    approved_req1 = broker.record_decision(
        req1["request_id"],
        decision="approved",
        owner_token=OWNER_SECRET,
        notes="Old draft approval",
    )
    with pytest.raises(ValueError):
        journal.apply_owner_approval(
            "task-lifecycle",
            state2["journal_version"],
            approved_req1["receipt_id"],
        )

    # Approve revision 2 -> moves to RESEARCH
    req2 = broker.create_request(state2)
    rcpt_ok = broker.record_decision(
        req2["request_id"],
        decision="approved",
        owner_token=OWNER_SECRET,
        notes="Approved revision 2",
    )
    state_ok = journal.apply_owner_approval(
        "task-lifecycle",
        state2["journal_version"],
        rcpt_ok["receipt_id"],
    )
    assert state_ok["stage"] == "RESEARCH"
    assert state_ok["approval"]["receipt_id"] == rcpt_ok["receipt_id"]

    # Reusable approval check: identical state matches, any edit to objective/plan/architecture/SRS invalidates
    assert broker.find_reusable_approval(state2)["receipt_id"] == rcpt_ok["receipt_id"]
    edited_obj = deepcopy(state2)
    edited_obj["objective"] = "Changed objective text"
    assert broker.find_reusable_approval(edited_obj) is None

    edited_doc = deepcopy(state2)
    edited_doc["document"]["architecture"] = "Modified architecture"
    edited_doc["srs_sha256"] = digest(edited_doc["document"])
    assert broker.find_reusable_approval(edited_doc) is None

    # 3. Direct rejection transition check
    rej_state = apply_owner_decision_to_state(
        state2,
        expected_srs_sha256=state2["srs_sha256"],
        receipt_id="ownercpt428-rejected",
        decision="rejected",
        notes="Scope cancelled by owner",
    )
    assert rej_state["stage"] == "OWNER_REJECTED"
    assert rej_state["approval"] is None


def test_tampered_sqlite_receipt_row_fails_hmac_verification(tmp_path: Path):
    db_path = tmp_path / "owner_broker.db"
    broker = OwnerApprovalBroker(db_path, owner_secret=OWNER_SECRET)
    task = accept_srs(new_task("task-hmac", "Secure kernel design"), _doc(9), planner_model="gpt", flash_context_limit=100000)
    req = broker.create_request(task)
    rcpt = broker.record_decision(
        req["request_id"],
        decision="rejected",
        owner_token=OWNER_SECRET,
        notes="Do not proceed",
    )
    # Tamper with the SQLite row to flip 'rejected' -> 'approved' without the HMAC secret
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE owner428_receipts SET decision='approved' WHERE receipt_id=?",
            (rcpt["receipt_id"],),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError, match="HMAC authentication failed"):
        broker.load_for_journal(rcpt["receipt_id"])
