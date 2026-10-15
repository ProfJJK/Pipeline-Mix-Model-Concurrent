"""Shared controller, routing, admission, and repair integration tests (`P428-23`)."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from cochem_pipeline.admission import JointAdmission, _NATIVE_KINDS
from cochem_pipeline.attempt_runtime_428 import AttemptAccountingRuntime
from cochem_pipeline.catalog_journal import (
    active_task_catalog,
    initialize,
    initialize_task_catalog,
    publish_task_catalog,
)
from cochem_pipeline.completion_audit_428 import CompletionAuditRuntime
from cochem_pipeline.failure_dossier_428 import FailureDossierStore
from cochem_pipeline.fracture_runtime_428 import FractureRuntime
from cochem_pipeline.owner_approval_428 import OwnerApprovalBroker
from cochem_pipeline.pivot_runtime_428 import PivotRuntime
from cochem_pipeline.planning_journal import PlanningJournal
from cochem_pipeline.planning_runtime import PlanningConfig, PlanningController
from cochem_pipeline.repair_queue_428 import RepairQueue
from cochem_pipeline.research_evidence_428 import ResearchEvidenceStore
from cochem_pipeline.research_runtime_428 import ResearchRuntime
from cochem_pipeline.research_search_428 import ResearchSearchClient
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.runtime import Runtime
from cochem_pipeline.store import JobStore
from cochem_pipeline.task_catalog_428 import compile_task_catalog_plan
from cochem_pipeline.task_decisions_428 import LockedTaskDecisionStore
from cochem_pipeline.task_execution_428 import SimpleTaskExecutionRuntime
from cochem_pipeline.task_release_428 import TaskReleaseRuntime
from cochem_pipeline.task_routing import digest
from cochem_pipeline.worker import NativeRunner
from cochem_pipeline.workflow_428 import AttemptLedger
from cochem_supervisor.repair_admission_428 import SupervisorRepairAdmission428
from pipeline_tests.test_planning_gateway_428 import accepted_receipt
from pipeline_tests.test_workflow_428 import document, microtasks, research, wbs
from pipeline_tests.task_catalog_fixtures import accepted_planning_store


ROOT = Path(__file__).resolve().parents[1]


def _load_catalog() -> dict:
    return json.loads((ROOT / "docs" / "4.2.8" / "routing-candidate.json").read_text(encoding="utf-8"))


def _make_simple_exec_output(srs_doc: dict) -> dict:
    content = "def verify_solution(x: int) -> int:\n    return x * 2\n"
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return {
        "artifact_text": "Verified simple task deliverable.",
        "deliverables": [{"name": "solution.py", "content": content, "sha256": sha}],
        "requirement_evidence": [
            {
                "requirement_id": r["id"],
                "deliverable_name": "solution.py",
                "verification_evidence": f"Requirement {r['id']} verified",
            }
            for r in srs_doc["requirements"]
        ],
        "release_criteria_results": [
            {
                "criterion": c,
                "passed": True,
                "evidence": f"Criterion '{c}' passed",
            }
            for c in srs_doc["release_criteria"]
        ],
    }


def _make_microtask_node_output(node: dict) -> dict:
    deliverables = []
    for dname in node["deliverables"]:
        body = f"# Deliverable {dname} for {node['microtask_id']}\n"
        deliverables.append(
            {
                "name": dname,
                "content": body,
                "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            }
        )
    first_deliv = deliverables[0]["name"]
    return {
        "artifact_text": f"Completed microtask {node['microtask_id']} ({node['role']})",
        "deliverables": deliverables,
        "requirement_evidence": [
            {
                "requirement_id": req_id,
                "deliverable_name": first_deliv,
                "verification_evidence": f"Verified {req_id} in {first_deliv}",
            }
            for req_id in node.get("requirement_ids", ["R1"])
        ],
        "release_criteria_results": [
            {
                "criterion": crit,
                "passed": True,
                "evidence": f"Verified {crit}",
            }
            for crit in node["release_criteria"]
        ],
    }


def _build_controller_env(tmp_path: Path):
    store, catalog = accepted_planning_store(tmp_path / "jobs.db")
    clock = [1000.0]
    approval_store = OwnerApprovalBroker(
        tmp_path / "approvals428.db",
        owner_secret="o" * 48,
        clock=lambda: clock[0],
    )
    journal = PlanningJournal(
        tmp_path / "planning428.db",
        catalog,
        flash_context_limit=100000,
        owner_receipt=approval_store.load_for_journal,
    )
    def _transport(url: str, headers: dict, timeout: float, max_bytes: int):
        from cochem_pipeline.research_search_428 import HttpResponseFixture
        if "en.wikipedia.org" in url:
            body = json.dumps(
                {
                    "query": {
                        "search": [
                            {
                                "pageid": 101,
                                "title": "Concurrency control",
                                "snippet": "Optimistic and pessimistic concurrency control.",
                            }
                        ]
                    }
                }
            ).encode("utf-8")
            return HttpResponseFixture(status_code=200, body=body, url=url)
        body = json.dumps(
            {
                "results": [
                    {
                        "id": "https://openalex.org/W100",
                        "doi": "https://doi.org/10.1000/wal",
                        "title": "Bounded State Machines",
                        "publication_year": 2024,
                        "abstract": "Formal verification of bounded state machines.",
                    }
                ]
            }
        ).encode("utf-8")
        return HttpResponseFixture(status_code=200, body=body, url=url)

    class _FakeKnowledge:
        def status(self):
            return {"ready": True, "generation": "g-" + "1" * 32, "manifest_sha256": "2" * 64}

        def search(self, query: str, limit: int = 5):
            return [
                {
                    "doc_path": "wiki/architecture/wal.md",
                    "section_title": "Write-Ahead Logging",
                    "snippet": "Verified wiki section excerpt on WAL isolation.",
                    "generation": "g-" + "1" * 32,
                }
            ]

        def read(self, doc_path: str):
            return {
                "path": doc_path,
                "sha256": "3" * 64,
                "text": "Full document body for WAL isolation.",
                "generation": "g-" + "1" * 32,
            }

    class _FakeAuth:
        def status(self, *, force: bool = False):
            return {"authority_matches_capture": True}

    ev_store = ResearchEvidenceStore(tmp_path / "research428.db")
    res_runtime = ResearchRuntime(
        ev_store,
        ResearchSearchClient(transport=_transport, resolver=lambda _h: ["93.184.216.34"]),
        knowledge_service=_FakeKnowledge(),
        knowledge_authority=_FakeAuth(),
        clock=lambda: clock[0],
    )
    exec_runtime = SimpleTaskExecutionRuntime(journal, store, clock=lambda: clock[0])
    rel_runtime = TaskReleaseRuntime(journal, store, clock=lambda: clock[0])
    ledger = AttemptLedger(tmp_path / "attempts428.db")
    att_runtime = AttemptAccountingRuntime(ledger, store=store, clock=lambda: clock[0])
    dos_store = FailureDossierStore(ledger, clock=lambda: clock[0])
    piv_runtime = PivotRuntime(ledger, catalog, dossier_store=dos_store, clock=lambda: clock[0])
    frac_runtime = FractureRuntime(
        ledger, catalog, dossier_store=dos_store, job_store=store, clock=lambda: clock[0]
    )
    dec_store = LockedTaskDecisionStore(ledger, dossier_store=dos_store, clock=lambda: clock[0])
    rep_queue = RepairQueue(
        tmp_path / "repair428.db",
        catalog,
        profiles={
            "repair_claude": {"provider": "claude", "quota_pool": "anthropic"},
            "repair_codex": {"provider": "codex", "quota_pool": "openai"},
            "repair_agy": {"provider": "gemini", "quota_pool": "google"},
        },
        normal_profile_ids={"slot1", "slot2", "slot3", "slot4", "slot5", "slot6"},
        verify_reservation=lambda _: None,
        verify_commit=lambda c, t: None,
    )
    aud_runtime = CompletionAuditRuntime(
        tmp_path / "audit428.db", catalog, rep_queue, clock=lambda: clock[0]
    )
    controller = PlanningController(
        journal,
        store,
        clock=lambda: clock[0],
        research_runtime=res_runtime,
        execution_runtime=exec_runtime,
        release_runtime=rel_runtime,
        attempt_ledger=ledger,
        attempt_runtime=att_runtime,
        dossier_store=dos_store,
        pivot_runtime=piv_runtime,
        fracture_runtime=frac_runtime,
        decision_store=dec_store,
        repair_queue=rep_queue,
        audit_runtime=aud_runtime,
    )
    admission = JointAdmission(store, None, capacity=4, max_capacity=4)
    return SimpleNamespace(
        catalog=catalog,
        clock=clock,
        approval_store=approval_store,
        journal=journal,
        store=store,
        ev_store=ev_store,
        res_runtime=res_runtime,
        exec_runtime=exec_runtime,
        rel_runtime=rel_runtime,
        ledger=ledger,
        att_runtime=att_runtime,
        dos_store=dos_store,
        piv_runtime=piv_runtime,
        frac_runtime=frac_runtime,
        dec_store=dec_store,
        rep_queue=rep_queue,
        aud_runtime=aud_runtime,
        controller=controller,
        admission=admission,
    )


def test_joint_admission_claims_task_plan_and_respects_four_seat_ceiling_and_repair_occupancy(tmp_path: Path):
    assert "TASK_PLAN" in _NATIVE_KINDS
    env = _build_controller_env(tmp_path)
    try:
        # Submit 5 tasks and step them onto the board
        for i in range(5):
            env.controller.submit(f"Task objective {i}", f"task-{i}")
        env.clock[0] += 2
        env.controller.step(limit=8)

        # Claim 4 seats via JointAdmission; 5th must be refused at the 4-seat ceiling
        claimed = []
        for idx in range(1, 5):
            res = env.admission.claim(
                "warden-test",
                worker_slot=f"slot{idx}",
                requires_cleanup=True,
            )
            assert res is not None
            node, reservation = res
            assert reservation is None
            assert node["kind"] == "TASK_PLAN"
            claimed.append(node)

        assert env.admission.claim("warden-test", worker_slot="slot5", requires_cleanup=True) is None

        # Finish 1 job and verify cleanup
        first = claimed[0]
        out = document(2)
        env.store.clear_execution_quarantine(first["job_id"], first["attempt_id"], first["fencing_token"])
        env.store.complete(
            first["job_id"],
            first["attempt_id"],
            first["fencing_token"],
            out,
            accepted_receipt(first, out),
        )

        # Now reserve 1 repair slot in repair428.db via SupervisorRepairAdmission428
        sup_adm = SupervisorRepairAdmission428(
            tmp_path / "repair428.db",
            env.catalog,
            accepted_native_models={"astra-max", "opus-max", "argon-high"},
            normal_board_path=tmp_path / "jobs.db",
            clock=lambda: env.clock[0],
        )
        inc = sup_adm.repair_queue.report(
            "inc-cap-01",
            "Pipeline defect requiring tier-10 repair",
            "a" * 64,
            source_kind="completion_spotcheck",
            task_types=["GEN-DEFAULT"],
        )
        assert inc["complexity"] == 10
        # Pending tier-10 repair in repair428.db holds competing quota pool claims
        admitted_rep = sup_adm.admit_next_repair("sup-instance-1")
        assert admitted_rep["status"] == "ADMITTED"

        # With 3 active board jobs + 1 active repair slot in repair428.db = 4 occupied seats!
        assert env.admission._native_active() == 4
        assert env.admission.claim("warden-test", worker_slot="slot1", requires_cleanup=True) is None
    finally:
        env.store.close()


def test_routing_store_and_native_runner_accept_428_task_catalog_profiles_and_block_retired(tmp_path: Path):
    import sqlite3

    def _open_durable(path: Path) -> sqlite3.Connection:
        c = sqlite3.connect(path, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA synchronous=FULL")
        c.execute("BEGIN IMMEDIATE")
        return c

    catalog = _load_catalog()
    cat_file = tmp_path / "accepted_catalog.json"
    cat_bytes = json.dumps(catalog, sort_keys=True).encode("utf-8")
    cat_file.write_bytes(cat_bytes)
    cat_sha = hashlib.sha256(cat_bytes).hexdigest()

    binaries = {
        "codex": {"executable": "C:/codex.exe", "sha256": "1" * 64, "version": "1.0"},
        "claude": {"executable": "C:/claude.exe", "sha256": "2" * 64, "version": "1.0"},
        "gemini": {"executable": "C:/agy.cmd", "sha256": "3" * 64, "version": "1.0"},
    }
    baseline = load_routing_policy({"policy_version": 3})
    db_path = tmp_path / "jobs_cat.db"
    store = JobStore(db_path, routing_policy=baseline)
    store.close()
    conn = _open_durable(db_path)
    try:
        initialize(conn, baseline)
        initialize_task_catalog(conn)
        plan1 = compile_task_catalog_plan(
            baseline,
            catalog,
            binaries,
            expected_policy_digest=baseline.digest,
        )
        req1 = "1" * 32
        receipts1 = [
            {
                "provider": p,
                "model": m,
                "reasoning_effort": e,
                "binary_sha256": binaries[p]["sha256"],
                "status": "NATIVE_SELECTOR_ACCEPTED",
                "cleanup_verified": True,
                "plan_digest": plan1.digest,
                "request_id": req1,
                "reservation_id": f"res1-{idx}",
                "fencing_token": idx + 1,
            }
            for idx, (p, m, e) in enumerate(sorted(set(plan1.required_targets) | {plan1.control_target}))
        ]
        publish_task_catalog(
            conn,
            plan1,
            receipts1,
            request_id=req1,
            pointer_sha256="2" * 64,
            proposal_sha256="3" * 64,
        )
        catalog = active_task_catalog(conn)
        conn.commit()
    finally:
        conn.close()

    store = JobStore(db_path, routing_policy=baseline, catalog_enabled=True)
    try:
        journal = PlanningJournal(tmp_path / "planning.db", catalog, flash_context_limit=100000)
        controller = PlanningController(journal, store, clock=lambda: 100.0)
        controller.submit("Simple task routed to luna-low", "task-luna")
        controller.step()

        # First candidate for SRS (tier 4, AGT-PROJ + GEN-DOC) in 4.2.8 catalog is luna-max
        job = store.claim("warden", worker_slot="slot1", allowed_kinds=["TASK_PLAN"], requires_cleanup=True)
        assert job is not None
        assert job["route"]["model"] == "gpt-6-luna"
        assert job["route"]["reasoning_effort"] == "max"

        # NativeRunner.route accepts the 4.2.8 task catalog target when pinned
        runner_cfg = SimpleNamespace(
            routing=baseline,
            catalog_activation=True, job_db=db_path,
            task_planning=PlanningConfig(cat_file, cat_sha, 100000),
        )
        runner = NativeRunner(runner_cfg)
        routed = runner.route(job)
        assert routed["model"] == "gpt-6-luna"
        assert routed["reasoning_effort"] == "max"

        # Retiring luna-max in a new published task catalog generation causes subsequent claims to skip it
        next_cat = deepcopy(catalog)
        next_cat["generation"] = "4.2.8-retired-luna-max"
        conn2 = _open_durable(db_path)
        try:
            active1 = active_task_catalog(conn2)
            plan = compile_task_catalog_plan(
                baseline,
                next_cat,
                binaries,
                expected_policy_digest=baseline.digest,
                previous_task_catalog=active1,
                retired_profile_ids=["luna-max"],
            )
            req_id = "a" * 32
            receipts = [
                {
                    "provider": p,
                    "model": m,
                    "reasoning_effort": e,
                    "binary_sha256": binaries[p]["sha256"],
                    "status": "NATIVE_SELECTOR_ACCEPTED",
                    "cleanup_verified": True,
                    "plan_digest": plan.digest,
                    "request_id": req_id,
                    "reservation_id": f"res-{idx}",
                    "fencing_token": idx + 1,
                }
                for idx, (p, m, e) in enumerate(sorted(set(plan.required_targets) | {plan.control_target}))
            ]
            publish_task_catalog(
                conn2,
                plan,
                receipts,
                request_id=req_id,
                pointer_sha256="b" * 64,
                proposal_sha256="c" * 64,
            )
            conn2.commit()
        finally:
            conn2.close()

        controller.submit("Second task after luna-max retirement", "task-after-retire")
        controller.step()
        job2 = store.claim("warden", worker_slot="slot2", allowed_kinds=["TASK_PLAN"], requires_cleanup=True)
        assert job2 is not None
        assert (job2["route"]["model"], job2["route"]["reasoning_effort"]) != ("gpt-6-luna", "max")
    finally:
        store.close()


def test_full_controller_inert_simple_and_researched_wbs_flows_to_completion(tmp_path: Path):
    env = _build_controller_env(tmp_path)
    try:
        # 1. Simple task flow: SRS (tier 2) -> READY -> SIMPLE_EXECUTION -> COMPLETED
        env.controller.submit("Implement simple check", "task-simple")
        env.clock[0] += 2
        env.controller.step()
        node, _ = env.admission.claim("warden", worker_slot="slot1", requires_cleanup=True)
        assert node is not None and node["kind"] == "TASK_PLAN"
        srs_simple = document(2)
        env.store.clear_execution_quarantine(node["job_id"], node["attempt_id"], node["fencing_token"])
        env.store.complete(
            node["job_id"], node["attempt_id"], node["fencing_token"], srs_simple, accepted_receipt(node, srs_simple)
        )
        env.controller.notify_job_changed(node["job_id"])
        env.controller.step()  # Imports SRS -> READY
        env.controller.step()  # Submits SIMPLE_EXECUTION job
        exec_node, _ = env.admission.claim("warden", worker_slot="slot1", requires_cleanup=True)
        assert exec_node is not None
        exec_out = _make_simple_exec_output(srs_simple)
        env.store.clear_execution_quarantine(exec_node["job_id"], exec_node["attempt_id"], exec_node["fencing_token"])
        env.store.complete(
            exec_node["job_id"],
            exec_node["attempt_id"],
            exec_node["fencing_token"],
            exec_out,
            accepted_receipt(exec_node, exec_out),
        )
        env.controller.notify_job_changed(exec_node["job_id"])
        env.controller.step()  # Imports execution -> COMPLETED
        st_simple = env.controller.task_status("task-simple")
        assert st_simple["deliverable_completed"] is True
        assert st_simple["execution"]["verification_status"] == "verified"

        # 2. Researched WBS/microtask flow: SRS (tier 4) -> RESEARCH -> PLAN_REVIEW -> WBS -> MICROTASKS -> MICROTASK_ASSESSMENT -> MICROTASKS_READY -> execution -> COMPLETED
        env.controller.submit("Implement multi-step researched workflow", "task-wbs")
        env.clock[0] += 2
        env.controller.step()
        srs_node, _ = env.admission.claim("warden", worker_slot="slot1", requires_cleanup=True)
        srs_wbs = document(4)
        env.store.clear_execution_quarantine(srs_node["job_id"], srs_node["attempt_id"], srs_node["fencing_token"])
        env.store.complete(
            srs_node["job_id"], srs_node["attempt_id"], srs_node["fencing_token"], srs_wbs, accepted_receipt(srs_node, srs_wbs)
        )
        env.controller.notify_job_changed(srs_node["job_id"])
        env.controller.step()  # Imports SRS -> RESEARCH
        env.controller.step()  # Enqueues research

        # Execute out-of-band 3-channel research worker
        assert env.res_runtime.step_worker() == 1
        env.clock[0] += 35
        env.controller.step()  # Imports research -> PLAN_REVIEW

        for stage_output in (
            {"accepted": True, "findings": [], "suggestions": [], "clarifications": []},
            {"wbs": wbs()},
            {"microtasks": microtasks()},
            {
                "assessments": [
                    {
                        "id": row["id"],
                        "complexity": row["complexity"],
                        "task_types": row["task_types"],
                        "rationale": "Assessed fragment",
                    }
                    for row in microtasks()
                ]
            },
        ):
            env.controller.step()
            mnode, _ = env.admission.claim("warden", worker_slot="slot1", requires_cleanup=True)
            assert mnode is not None
            env.store.clear_execution_quarantine(mnode["job_id"], mnode["attempt_id"], mnode["fencing_token"])
            env.store.complete(
                mnode["job_id"],
                mnode["attempt_id"],
                mnode["fencing_token"],
                stage_output,
                accepted_receipt(mnode, stage_output),
            )
            env.controller.notify_job_changed(mnode["job_id"])
            env.controller.step()

        assert env.journal.status("task-wbs")["stage"] == "MICROTASKS_READY"

        # Execute M1, M2, M3 through TaskReleaseRuntime
        for _ in range(6):
            env.clock[0] += 2
            env.controller.step()
            while True:
                admitted = env.admission.claim("warden", worker_slot="slot1", requires_cleanup=True)
                if admitted is None:
                    break
                mt_job, _ = admitted
                mt_out = _make_microtask_node_output(mt_job["payload"]["microtask_node"])
                env.store.clear_execution_quarantine(mt_job["job_id"], mt_job["attempt_id"], mt_job["fencing_token"])
                env.store.complete(
                    mt_job["job_id"],
                    mt_job["attempt_id"],
                    mt_job["fencing_token"],
                    mt_out,
                    accepted_receipt(mt_job, mt_out),
                )
                env.controller.notify_job_changed(mt_job["job_id"])
            if env.controller.task_status("task-wbs")["controller"]["status"] == "WAITING_FOR_CONTROLLER_TEST_VERIFICATION":
                env.rel_runtime.record_controller_test_receipt(
                    "task-wbs",
                    "M3",
                    passed=True,
                    exit_code=0,
                    cleanup_verified=True,
                    status="COMPLETED",
                    verified_requirements=[r["id"] for r in srs_wbs["requirements"]],
                    summary="Controller verified all SRS requirements",
                )
                env.clock[0] += 10
                env.controller.step()
            if env.controller.task_status("task-wbs")["deliverable_completed"]:
                break

        st_wbs = env.controller.task_status("task-wbs")
        assert st_wbs["deliverable_completed"] is True
        assert st_wbs["release"]["verified_requirements"] == [r["id"] for r in srs_wbs["requirements"]]
    finally:
        env.store.close()


def test_owner_approval_gate_cancellation_shutdown_restart_and_locked_decision_projection(tmp_path: Path):
    env = _build_controller_env(tmp_path)
    try:
        # High-tier (8) task requires owner approval immediately after SRS before research/WBS
        env.controller.submit("High tier architecture task", "task-tier8")
        env.clock[0] += 2
        env.controller.step()
        node, _ = env.admission.claim("warden", worker_slot="slot1", requires_cleanup=True)
        srs8 = document(8)
        env.store.clear_execution_quarantine(node["job_id"], node["attempt_id"], node["fencing_token"])
        env.store.complete(node["job_id"], node["attempt_id"], node["fencing_token"], srs8, accepted_receipt(node, srs8))
        env.controller.notify_job_changed(node["job_id"])
        env.controller.step()  # Imports SRS -> OWNER_APPROVAL
        env.controller.step()  # Records WAITING_FOR_OWNER_APPROVAL
        assert env.controller.task_status("task-tier8")["controller"]["status"] == "WAITING_FOR_OWNER_APPROVAL"

        # Simulate restart: reopen controller on same SQLite files
        reopened = PlanningController(
            PlanningJournal(
                tmp_path / "planning428.db",
                env.catalog,
                flash_context_limit=100000,
                owner_receipt=env.approval_store.load_for_journal,
            ),
            env.store,
            clock=lambda: env.clock[0],
            decision_store=env.dec_store,
            attempt_ledger=env.ledger,
        )
        env.clock[0] += 60
        reopened.step()
        assert reopened.task_status("task-tier8")["controller"]["status"] == "WAITING_FOR_OWNER_APPROVAL"

        # Cancel a running task via Runtime.cancel
        reopened.submit("Task to cancel", "task-cancel")
        env.clock[0] += 2
        reopened.step()
        cancel_job_id = reopened.task_status("task-cancel")["controller"]["job_id"]
        assert cancel_job_id is not None

        rt = Runtime.__new__(Runtime)
        rt.task_planning = reopened
        rt.store = env.store
        rt.lock = threading.RLock()
        rt.active = {}
        rt.runner = SimpleNamespace(terminate=lambda jid: None)
        rt.cancel("task-cancel")
        assert reopened.task_status("task-cancel")["task"]["stage"] == "CANCELLED"
        assert env.store.get(cancel_job_id)["status"] == "FAILED"

        # 30-failure locked lineage surfaces locked_decision on task_status
        reopened.submit("Task that locks at 30 failures", "task-locked-30")
        env.ledger.create("task-locked-30")
        for idx in range(1, 31):
            m = "gpt-6-luna" if idx <= 10 else ("gpt-6.1-sol" if idx <= 20 else "claude-opus-5-5")
            lease = env.ledger.start("task-locked-30", "task-locked-30", m)
            env.ledger.finish(lease, "quality_failure", f"{idx:064x}")
            if idx == 10:
                env.ledger.pivot(
                    "task-locked-30",
                    research(),
                    {
                        "strategy": "pivot",
                        "task_types": ["COD-TERM"],
                        "complexity": 5,
                        "rationale": "Pivot after 10 failures",
                        "next_model": "gpt-6.1-sol",
                        "children": [],
                    },
                    digest("pivot1"),
                )
            elif idx == 20:
                env.ledger.pivot(
                    "task-locked-30",
                    research(),
                    {
                        "strategy": "pivot",
                        "task_types": ["COD-TERM"],
                        "complexity": 6,
                        "rationale": "Pivot after 20 failures",
                        "next_model": "claude-opus-5-5",
                        "children": [],
                    },
                    digest("pivot2"),
                )
        st_locked = reopened.task_status("task-locked-30")
        assert "locked_decision" in st_locked
        assert st_locked["locked_decision"]["stage"] == "LOCKED"
        assert st_locked["locked_decision"]["failures"] == 30
    finally:
        env.store.close()


def test_planning_controller_from_runtime_wires_owner_broker_and_out_of_band_research_worker(
    tmp_path: Path,
):
    catalog = _load_catalog()
    store = JobStore(
        tmp_path / "jobs.db",
        routing_policy=load_routing_policy({"policy_version": 3}),
    )
    try:
        private_root = tmp_path / "private"
        private_root.mkdir(parents=True)
        token_file = tmp_path / "controller.token"
        token_file.write_text("controller-bearer-token\n", encoding="utf-8")
        rt = SimpleNamespace(
            config=SimpleNamespace(
                private_root=private_root,
                token_file=token_file,
                task_planning=SimpleNamespace(
                    enabled=True,
                    flash_context_limit=100000,
                    read_catalog=lambda: catalog,
                ),
            ),
            store=store,
        )
        controller = PlanningController.from_runtime(rt)
        try:
            assert getattr(rt, "owner_approval_broker", None) is not None
            assert controller.release_runtime is not None
            assert controller.release_runtime.board.owner_broker is rt.owner_approval_broker
            assert controller.journal.owner_receipt is not None
            assert (private_root / "owner_approval.secret").read_text(
                encoding="utf-8"
            ).strip() != "controller-bearer-token"

            # Verify out-of-band research worker runs via kick_research_worker()
            assert controller.research_runtime is not None
            controller.research_runtime.enqueue(
                {
                    "schema": "cochem-planning-intent/4.2.8",
                    "action": "controller_research",
                    "task_id": "task-oob",
                    "srs_sha256": "a" * 64,
                    "query": "Out of band research test",
                    "channels": ["internet", "wiki_rag", "papers"],
                }
            )
            assert controller.research_runtime.has_due_work() is True
            called = threading.Event()

            def _fake_step_worker(*, limit: int = 4) -> int:
                called.set()
                return 1

            controller.research_runtime.step_worker = _fake_step_worker  # type: ignore[method-assign]
            assert controller.kick_research_worker() is True
            assert called.wait(timeout=5.0) is True
        finally:
            controller.close()
    finally:
        store.close()
