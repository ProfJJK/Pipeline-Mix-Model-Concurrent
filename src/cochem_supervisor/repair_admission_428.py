"""Independent repair admission and supervisor recovery (`P428-20`).

Guarantees:
- Dedicated repair identities (`repair_claude`, `repair_codex`, `repair_agy`) and a
  separate supervisor SQLite journal remain usable even when the normal pipeline
  jobboard database is missing, locked, or corrupted.
- Only accepted (`native_accepted=True`), maximum-effort (`max`, or `high` for Gemini)
  tier-10 profiles can reserve repair work; exhausted tier-10 quota waits in
  `WAITING_QUOTA` and never downgrades to a lower tier or lower effort.
- Pending repair work has priority over new competing ordinary quota claims without
  ever preempting or stealing live ordinary leases.
- Cross-process 4-slot ownership (`0..3`) and native cleanup verification survive
  controller and supervisor restarts; stale leases cannot be released or reused
  without verified cleanup, and unknown slot ownership holds safely in
  `HOLD_UNKNOWN_OWNERSHIP`.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import time
from typing import Any
import uuid

from cochem_pipeline.repair_queue_428 import RepairQueue
from cochem_pipeline.task_routing import digest
from cochem_pipeline.workflow_428 import _id, _sha, _text


DEFAULT_REPAIR_PROFILES = {
    "repair_claude": {"provider": "claude", "quota_pool": "anthropic"},
    "repair_codex": {"provider": "codex", "quota_pool": "openai"},
    "repair_agy": {"provider": "gemini", "quota_pool": "google"},
}
DEFAULT_NORMAL_PROFILES = {"slot1", "slot2", "slot3", "slot4", "slot5", "slot6"}


class RepairPriorityHoldError(ValueError):
    """Raised when a new ordinary claim is blocked by a pending tier-10 repair in the same quota pool."""


class SupervisorRepairAdmission428:
    """Coordinates cross-process 4-slot ownership, quota priority, and independent repair admission (`P428-20`)."""

    def __init__(
        self,
        db_path: str | Path,
        catalog: dict[str, Any],
        *,
        profiles: dict[str, dict[str, str]] | None = None,
        normal_profile_ids: set[str] | None = None,
        accepted_native_models: set[str] | None = None,
        normal_board_path: str | Path | None = None,
        verify_commit=None,
        clock=time.time,
    ):
        if str(db_path) == ":memory:":
            raise ValueError("Supervisor repair admission requires a durable SQLite database")
        self.db_path = Path(db_path)
        self.catalog = deepcopy(catalog)
        self.profiles = deepcopy(profiles or DEFAULT_REPAIR_PROFILES)
        self.normal_profile_ids = set(normal_profile_ids or DEFAULT_NORMAL_PROFILES)
        self.accepted_native_models = set(
            accepted_native_models
            if accepted_native_models is not None
            else {
                mid
                for mid, spec in (self.catalog.get("models") or {}).items()
                if spec.get("native_acceptance") == "ACCEPTED"
            }
        )
        self.normal_board_path = Path(normal_board_path) if normal_board_path is not None else None
        self.clock = clock

        with self._write() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS repair428_shared_slots(
                    slot INTEGER PRIMARY KEY CHECK (slot >= 0 AND slot < 4),
                    reservation_id TEXT UNIQUE NOT NULL,
                    owner_kind TEXT NOT NULL,
                    owner_instance_id TEXT NOT NULL,
                    dedicated_profile TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    quota_pool TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    native_accepted INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    cleanup_verified INTEGER NOT NULL,
                    cleanup_receipt_sha256 TEXT,
                    acquired_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS repair428_quota_pools(
                    quota_pool TEXT PRIMARY KEY,
                    available INTEGER NOT NULL,
                    reason TEXT,
                    updated_at REAL NOT NULL
                );
                """
            )

        self.repair_queue = RepairQueue(
            self.db_path,
            self.catalog,
            profiles=self.profiles,
            normal_profile_ids=self.normal_profile_ids,
            verify_reservation=self.verify_reservation,
            verify_commit=verify_commit,
        )

    @contextmanager
    def _write(self):
        conn = sqlite3.connect(self.db_path, timeout=5)
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

    def probe_normal_board_health(self) -> dict[str, Any]:
        """Inspect normal board health without making it a prerequisite for repair admission."""
        if self.normal_board_path is None:
            return {"healthy": False, "reason": "not_configured"}
        if not self.normal_board_path.exists():
            return {"healthy": False, "reason": "missing_file"}
        try:
            conn = sqlite3.connect(self.normal_board_path, timeout=1)
            try:
                conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
            finally:
                conn.close()
            return {"healthy": True, "reason": "ok"}
        except sqlite3.Error as exc:
            return {"healthy": False, "reason": f"corrupt_or_unreadable: {type(exc).__name__}"}

    def set_quota_pool_availability(
        self,
        quota_pool: str,
        available: bool,
        *,
        reason: str = "",
    ) -> dict[str, Any]:
        _id(quota_pool)
        now = float(self.clock())
        with self._write() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO repair428_quota_pools VALUES(?,?,?,?)",
                (quota_pool, int(bool(available)), reason or None, now),
            )
        return {"quota_pool": quota_pool, "available": bool(available), "reason": reason}

    def is_quota_pool_available(self, quota_pool: str) -> bool:
        _id(quota_pool)
        with self._write() as conn:
            row = conn.execute(
                "SELECT available FROM repair428_quota_pools WHERE quota_pool=?",
                (quota_pool,),
            ).fetchone()
        if row is None:
            return True
        return bool(row["available"])

    def verify_reservation(self, reservation_id: str) -> dict[str, Any] | None:
        """Verifier callback passed into `RepairQueue` to attest shared 4-slot ownership."""
        _id(reservation_id)
        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM repair428_shared_slots WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "reservation_id": row["reservation_id"],
            "active": row["state"] == "ACTIVE",
            "dedicated_profile": row["dedicated_profile"],
            "model_id": row["model_id"],
            "quota_pool": row["quota_pool"],
            "purpose": row["purpose"],
            "shared_capacity": 4,
            "slot": int(row["slot"]),
            "native_accepted": bool(row["native_accepted"]),
            "state": row["state"],
            "owner_instance_id": row["owner_instance_id"],
        }

    def list_shared_slots(self) -> list[dict[str, Any]]:
        with self._write() as conn:
            rows = conn.execute("SELECT * FROM repair428_shared_slots ORDER BY slot ASC").fetchall()
        return [
            {
                "slot": int(r["slot"]),
                "reservation_id": r["reservation_id"],
                "owner_kind": r["owner_kind"],
                "owner_instance_id": r["owner_instance_id"],
                "dedicated_profile": r["dedicated_profile"],
                "model_id": r["model_id"],
                "quota_pool": r["quota_pool"],
                "purpose": r["purpose"],
                "native_accepted": bool(r["native_accepted"]),
                "state": r["state"],
                "cleanup_verified": bool(r["cleanup_verified"]),
                "cleanup_receipt_sha256": r["cleanup_receipt_sha256"],
            }
            for r in rows
        ]

    def acquire_ordinary_slot(
        self,
        worker_instance_id: str,
        *,
        profile_id: str,
        model_id: str,
        quota_pool: str,
    ) -> dict[str, Any]:
        """Acquire a shared host slot (`0..3`) for ordinary pipeline work, yielding priority to pending repairs."""
        _id(worker_instance_id)
        _id(profile_id)
        _id(model_id)
        _id(quota_pool)
        if profile_id in self.profiles or profile_id not in self.normal_profile_ids:
            raise ValueError("Ordinary work must use a normal worker profile, never a dedicated repair profile")

        if self.repair_queue.priority_waiting(quota_pool):
            raise RepairPriorityHoldError(
                f"Pending tier-10 repair has priority for competing quota_pool '{quota_pool}'; new ordinary claim held"
            )
        if not self.is_quota_pool_available(quota_pool):
            raise ValueError(f"Quota pool '{quota_pool}' is currently exhausted")

        now = float(self.clock())
        with self._write() as conn:
            occupied = {
                int(r["slot"])
                for r in conn.execute("SELECT slot FROM repair428_shared_slots").fetchall()
            }
            free_slots = [s for s in range(4) if s not in occupied]
            if not free_slots:
                raise ValueError("All 4 shared host execution slots are occupied or awaiting cleanup verification")
            chosen_slot = free_slots[0]
            res_id = f"res428-ord-{chosen_slot}-{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO repair428_shared_slots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    chosen_slot,
                    res_id,
                    "ordinary_worker",
                    worker_instance_id,
                    profile_id,
                    model_id,
                    quota_pool,
                    "ordinary_work",
                    1,
                    "ACTIVE",
                    0,
                    None,
                    now,
                    now,
                ),
            )
        return self.verify_reservation(res_id)

    def admit_next_repair(
        self,
        supervisor_id: str,
        *,
        incident_id: str | None = None,
        requested_model_id: str | None = None,
    ) -> dict[str, Any]:
        """Admit a queued repair using only accepted max-effort tier-10 profiles within the 4-slot pool."""
        _id(supervisor_id)
        board_health = self.probe_normal_board_health()

        incidents = (
            [self.repair_queue.get_incident(incident_id)]
            if incident_id is not None
            else self.repair_queue.list_incidents()
        )
        candidates_inc = [
            inc for inc in incidents if inc is not None and inc["state"] in ("QUEUED", "WAITING_QUOTA")
        ]
        if not candidates_inc:
            raise ValueError("No queued or quota-waiting repair incident is available to admit")
        inc = candidates_inc[0]
        inc_id = inc["incident_id"]
        target_profiles = list(inc["request"]["target_profiles"])

        models = self.catalog.get("models") or {}
        if requested_model_id is not None:
            _id(requested_model_id)
            if requested_model_id not in models:
                raise ValueError(f"Unknown model_id: {requested_model_id}")
            req_spec = models[requested_model_id]
            req_max = "high" if req_spec.get("provider") == "gemini" else "max"
            if req_spec.get("effort") != req_max:
                raise ValueError("Only tier-10 maximum-effort profiles can reserve repair work")
            if requested_model_id not in self.accepted_native_models:
                raise ValueError(f"Model '{requested_model_id}' lacks native host acceptance for repair")
            if requested_model_id not in target_profiles:
                raise ValueError("Only tier-10 maximum-effort profiles meeting the floor can reserve repair work")
            ordered_models = [requested_model_id]
        else:
            ordered_models = [
                mid
                for mid in target_profiles
                if mid in models
                and models[mid].get("effort") == ("high" if models[mid].get("provider") == "gemini" else "max")
                and mid in self.accepted_native_models
            ]

        if not ordered_models:
            raise ValueError(f"Incident '{inc_id}' has no natively accepted maximum-effort tier-10 profile")

        # Pair each eligible tier-10 max-effort model with its dedicated repair profile and check quota
        ready_pairs: list[tuple[str, str, str]] = []
        for mid in ordered_models:
            prov = models[mid]["provider"]
            for prof_id, prof_spec in self.profiles.items():
                if prof_spec["provider"] == prov:
                    qpool = prof_spec["quota_pool"]
                    if self.is_quota_pool_available(qpool):
                        ready_pairs.append((prof_id, mid, qpool))

        if not ready_pairs:
            # Never downgrade to a lower tier or lower effort when tier-10 quota is exhausted!
            self.repair_queue.mark_waiting_quota(inc_id)
            return {
                "status": "WAITING_QUOTA",
                "incident_id": inc_id,
                "normal_board_health": board_health,
                "reason": "All accepted maximum-effort tier-10 repair profiles are waiting on quota",
            }

        chosen_profile_id, chosen_model_id, chosen_pool = ready_pairs[0]
        now = float(self.clock())

        with self._write() as conn:
            # Enforce at most 1 active repair reservation across supervisors
            existing_repair = conn.execute(
                "SELECT reservation_id, owner_instance_id FROM repair428_shared_slots WHERE purpose='pipeline_repair'"
            ).fetchone()
            if existing_repair is not None:
                raise ValueError(
                    f"Another repair slot reservation '{existing_repair['reservation_id']}' is already held by '{existing_repair['owner_instance_id']}'"
                )

            occupied = {
                int(r["slot"])
                for r in conn.execute("SELECT slot FROM repair428_shared_slots").fetchall()
            }
            free_slots = [s for s in range(4) if s not in occupied]
            if not free_slots:
                # Never preempt or steal live ordinary leases!
                return {
                    "status": "WAITING_HOST_SLOT",
                    "incident_id": inc_id,
                    "normal_board_health": board_health,
                    "reason": "All 4 shared host slots are occupied or awaiting verified cleanup; live leases are never stolen",
                }
            chosen_slot = free_slots[0]
            res_id = f"res428-rep-{chosen_slot}-{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO repair428_shared_slots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    chosen_slot,
                    res_id,
                    "pipeline_repair",
                    supervisor_id,
                    chosen_profile_id,
                    chosen_model_id,
                    chosen_pool,
                    "pipeline_repair",
                    1,
                    "ACTIVE",
                    0,
                    None,
                    now,
                    now,
                ),
            )

        try:
            claimed = self.repair_queue.claim(inc_id, chosen_profile_id, chosen_model_id, res_id)
        except BaseException:
            with self._write() as conn:
                conn.execute("DELETE FROM repair428_shared_slots WHERE reservation_id=?", (res_id,))
            raise

        return {
            "status": "ADMITTED",
            "incident_id": inc_id,
            "supervisor_id": supervisor_id,
            "slot": chosen_slot,
            "reservation_id": res_id,
            "profile_id": chosen_profile_id,
            "model_id": chosen_model_id,
            "quota_pool": chosen_pool,
            "lease": claimed["lease"],
            "normal_board_health": board_health,
            "claimed": claimed,
        }

    def mark_slot_stale(self, reservation_id: str) -> dict[str, Any]:
        """Mark an active slot lease as stale (`STALE_UNVERIFIED_CLEANUP`); it cannot be reused until cleanup is proven."""
        _id(reservation_id)
        now = float(self.clock())
        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM repair428_shared_slots WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown reservation_id: {reservation_id}")
            conn.execute(
                "UPDATE repair428_shared_slots SET state='STALE_UNVERIFIED_CLEANUP', cleanup_verified=0, updated_at=? WHERE reservation_id=?",
                (now, reservation_id),
            )
        return self.verify_reservation(reservation_id)

    def record_unknown_slot_ownership(self, slot: int, *, observed_detail: str = "unrecognized_process") -> dict[str, Any]:
        """Fence a slot with unknown ownership in `HOLD_UNKNOWN_OWNERSHIP` rather than assuming it is free."""
        if type(slot) is not int or not 0 <= slot < 4:
            raise ValueError("slot must be an integer in 0..3")
        _text(observed_detail, "Observed unknown slot detail", 512)
        now = float(self.clock())
        res_id = f"res428-unknown-slot-{slot}"
        with self._write() as conn:
            existing = conn.execute(
                "SELECT * FROM repair428_shared_slots WHERE slot=?",
                (slot,),
            ).fetchone()
            if existing is not None:
                conn.execute(
                    "UPDATE repair428_shared_slots SET owner_kind='unknown', state='HOLD_UNKNOWN_OWNERSHIP', cleanup_verified=0, updated_at=? WHERE slot=?",
                    (now, slot),
                )
                res_id = existing["reservation_id"]
            else:
                conn.execute(
                    "INSERT INTO repair428_shared_slots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        slot,
                        res_id,
                        "unknown",
                        observed_detail,
                        "unknown",
                        "unknown",
                        "unknown",
                        "unknown",
                        0,
                        "HOLD_UNKNOWN_OWNERSHIP",
                        0,
                        None,
                        now,
                        now,
                    ),
                )
        return self.verify_reservation(res_id)

    def release_slot(
        self,
        reservation_id: str,
        *,
        cleanup_verified: bool,
        cleanup_receipt_sha256: str,
        requeue_interrupted_incident: bool = True,
    ) -> dict[str, Any]:
        """Release a shared slot ONLY when native process/container cleanup is verified with a receipt digest."""
        _id(reservation_id)
        _sha(cleanup_receipt_sha256)
        if cleanup_verified is not True:
            raise ValueError("Cannot release or reuse a shared host slot without verified native cleanup")

        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM repair428_shared_slots WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown reservation_id: {reservation_id}")
            slot_num = int(row["slot"])
            purpose = row["purpose"]
            conn.execute(
                "DELETE FROM repair428_shared_slots WHERE reservation_id=?",
                (reservation_id,),
            )

        requeued_incident = None
        if purpose == "pipeline_repair" and requeue_interrupted_incident:
            for inc in self.repair_queue.list_incidents(state="ACTIVE"):
                exec_info = inc.get("execution") or {}
                if exec_info.get("reservation_id") == reservation_id and inc.get("lease"):
                    requeued_incident = self.repair_queue.recover_stale_lease(
                        inc["lease"],
                        cleanup_verified=True,
                        cleanup_receipt_sha256=cleanup_receipt_sha256,
                    )
        return {
            "released_slot": slot_num,
            "reservation_id": reservation_id,
            "cleanup_verified": True,
            "cleanup_receipt_sha256": cleanup_receipt_sha256,
            "requeued_incident": requeued_incident,
        }
