"""Tests for `P428-20`: Independent repair admission and supervisor recovery (`repair_admission_428.py`, `repair_queue_428.py`)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cochem_pipeline.task_routing import digest
from cochem_supervisor.repair_admission_428 import (
    RepairPriorityHoldError,
    SupervisorRepairAdmission428,
)


ROOT = Path(__file__).resolve().parents[1]


def _load_catalog() -> dict:
    return json.loads((ROOT / "docs" / "4.2.8" / "routing-candidate.json").read_text(encoding="utf-8"))


def test_broken_board_tier10_acceptance_quota_exhaustion_and_competing_ordinary_claims(tmp_path: Path) -> None:
    catalog = _load_catalog()
    # Write a corrupted SQLite file to simulate a broken normal job board
    broken_board = tmp_path / "broken_normal_board.sqlite"
    broken_board.write_bytes(b"NOT A VALID SQLITE DATABASE HEADER - CORRUPTED")

    sup_db = tmp_path / "supervisor_repair.sqlite"
    sup = SupervisorRepairAdmission428(
        sup_db,
        catalog,
        accepted_native_models={"astra-max", "opus-max", "argon-high"},
        normal_board_path=broken_board,
    )
    assert sup.probe_normal_board_health()["healthy"] is False

    # 1. Acquire 1 live ordinary lease before any repair is queued
    live_ord = sup.acquire_ordinary_slot(
        "worker-1",
        profile_id="slot1",
        model_id="luna-low",
        quota_pool="openai",
    )
    assert live_ord["slot"] == 0
    assert live_ord["active"] is True

    # 2. Report a repair incident while normal board is broken
    req = sup.repair_queue.report(
        "inc-broken-board-1",
        "Normal job board corrupted; controller heartbeat lost",
        digest("ev-broken-board"),
        source_kind="controller_fault",
        task_types=["GEN-DEFAULT"],
    )
    assert req["complexity"] == 10

    # 3. Competing ordinary claim in a pool needed by the pending repair is blocked!
    with pytest.raises(RepairPriorityHoldError, match="Pending tier-10 repair has priority"):
        sup.acquire_ordinary_slot(
            "worker-2",
            profile_id="slot2",
            model_id="sonnet-med",
            quota_pool="anthropic",
        )
    # Meanwhile the already-live ordinary lease on slot 0 is NEVER stolen or preempted!
    assert sup.verify_reservation(live_ord["reservation_id"])["active"] is True

    # 4. Non-max-effort or unaccepted native model is rejected for repair admission
    with pytest.raises(ValueError, match="maximum-effort"):
        sup.admit_next_repair(
            "supervisor-alpha",
            incident_id="inc-broken-board-1",
            requested_model_id="astra-high",
        )
    with pytest.raises(ValueError, match="lacks native host acceptance"):
        sup.admit_next_repair(
            "supervisor-alpha",
            incident_id="inc-broken-board-1",
            requested_model_id="fable-max",
        )

    # 5. Exhausted tier-10 quota -> transitions to WAITING_QUOTA without downgrading tier
    for pool in ("openai", "anthropic", "google"):
        sup.set_quota_pool_availability(pool, False, reason="tier10_quota_exhausted")
    wait_res = sup.admit_next_repair("supervisor-alpha", incident_id="inc-broken-board-1")
    assert wait_res["status"] == "WAITING_QUOTA"
    assert wait_res["normal_board_health"]["healthy"] is False
    assert sup.repair_queue.get_incident("inc-broken-board-1")["state"] == "WAITING_QUOTA"

    # Restore quota -> admits on slot 1 (preserving live ordinary slot 0!)
    for pool in ("openai", "anthropic", "google"):
        sup.set_quota_pool_availability(pool, True, reason="quota_replenished")
    admitted = sup.admit_next_repair("supervisor-alpha", incident_id="inc-broken-board-1")
    assert admitted["status"] == "ADMITTED"
    assert admitted["slot"] == 1
    assert admitted["normal_board_health"]["healthy"] is False


def test_two_supervisors_four_slot_limit_stale_lease_unverified_cleanup_and_unknown_ownership(tmp_path: Path) -> None:
    catalog = _load_catalog()
    sup_db = tmp_path / "sup_recovery.sqlite"
    accepted = {"astra-max", "opus-max", "argon-high"}

    sup1 = SupervisorRepairAdmission428(sup_db, catalog, accepted_native_models=accepted)
    sup2 = SupervisorRepairAdmission428(sup_db, catalog, accepted_native_models=accepted)

    # Occupy slots 0, 1, 2 with live ordinary leases and fence slot 3 with UNKNOWN ownership
    ord0 = sup1.acquire_ordinary_slot("w0", profile_id="slot1", model_id="luna-low", quota_pool="openai")
    ord1 = sup1.acquire_ordinary_slot("w1", profile_id="slot2", model_id="luna-low", quota_pool="openai")
    ord2 = sup1.acquire_ordinary_slot("w2", profile_id="slot3", model_id="luna-low", quota_pool="openai")
    unk3 = sup1.record_unknown_slot_ownership(3, observed_detail="orphan_pid_9999")
    assert unk3["state"] == "HOLD_UNKNOWN_OWNERSHIP"
    assert unk3["active"] is False

    sup1.repair_queue.report(
        "inc-slot-full",
        "Fault while 3 live slots + 1 unknown slot occupy all 4 slots",
        digest("ev-slot-full"),
        source_kind="invariant_failure",
        task_types=["GEN-DEFAULT"],
    )
    sup1.repair_queue.report(
        "inc-second",
        "Second queued repair incident",
        digest("ev-second"),
        source_kind="native_fault",
        task_types=["GEN-DEFAULT"],
    )

    # All 4 slots are occupied (3 live + 1 unknown) -> repair waits for host slot without stealing live leases!
    wait_slot = sup1.admit_next_repair("sup-1", incident_id="inc-slot-full")
    assert wait_slot["status"] == "WAITING_HOST_SLOT"

    # Releasing unknown slot 3 WITHOUT verified cleanup is refused!
    with pytest.raises(ValueError, match="verified native cleanup"):
        sup1.release_slot(
            unk3["reservation_id"],
            cleanup_verified=False,
            cleanup_receipt_sha256=digest("unverified"),
        )

    # Verify cleanup of unknown slot 3 -> frees slot 3
    sup1.release_slot(
        unk3["reservation_id"],
        cleanup_verified=True,
        cleanup_receipt_sha256=digest("cleaned-slot-3"),
    )

    # Now sup1 admits inc-slot-full on slot 3
    adm1 = sup1.admit_next_repair("sup-1", incident_id="inc-slot-full")
    assert adm1["status"] == "ADMITTED"
    assert adm1["slot"] == 3

    # Free ordinary slot 2 so a slot is open, then verify sup2 STILL cannot admit a second concurrent repair!
    sup1.release_slot(ord2["reservation_id"], cleanup_verified=True, cleanup_receipt_sha256=digest("ord2-clean"))
    with pytest.raises(ValueError, match="Another repair"):
        sup2.admit_next_repair("sup-2", incident_id="inc-second")

    # Simulate sup1 crash / stale lease on slot 3 -> survives restart of both controller and supervisor
    sup1.mark_slot_stale(adm1["reservation_id"])
    restarted_sup = SupervisorRepairAdmission428(sup_db, catalog, accepted_native_models=accepted)
    stale_check = restarted_sup.verify_reservation(adm1["reservation_id"])
    assert stale_check["state"] == "STALE_UNVERIFIED_CLEANUP"
    assert stale_check["active"] is False

    # Unverified cleanup cannot release the stale repair lease
    with pytest.raises(ValueError, match="verified native cleanup"):
        restarted_sup.release_slot(
            adm1["reservation_id"],
            cleanup_verified=False,
            cleanup_receipt_sha256=digest("bad"),
        )

    # Verified cleanup releases slot 3 and returns inc-slot-full to QUEUED so restarted_sup can admit it cleanly
    rel = restarted_sup.release_slot(
        adm1["reservation_id"],
        cleanup_verified=True,
        cleanup_receipt_sha256=digest("verified-stale-cleanup"),
    )
    assert rel["released_slot"] == 3
    assert rel["requeued_incident"]["state"] == "QUEUED"

    adm_recovered = restarted_sup.admit_next_repair("sup-restarted", incident_id="inc-slot-full")
    assert adm_recovered["status"] == "ADMITTED"
    assert adm_recovered["slot"] in (2, 3)
