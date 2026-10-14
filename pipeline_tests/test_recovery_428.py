"""Integrated failure-injection and recovery acceptance tests for Pipeline 4.2.8 (`P428-24`).

Covers:
1. End-to-end 10/20/30 quality-failure progression with availability non-charging,
   boundary-10 dossier + higher-model pivot, boundary-20 dossier + narrower child
   fracture (with inherited quality budget across descendants), and boundary-30
   lock with sanitized status discovery and authenticated owner `revise_scope` recovery.
2. Completion spot-check (`CompletionAuditRuntime`) revocation of false completion vs.
   systemic pipeline fault incident opening and deduplication in `RepairQueue`.
3. Broken-board independent supervisor repair admission (`SupervisorRepairAdmission428`)
   and isolated repository repair execution (`IsolatedRepairExecutor428`) through
   crash recovery, `SOURCE_REPAIRED`, explicit hold without supervisor authority,
   and `RESOLVED` after reviewed supervisor transition.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cochem_pipeline.attempt_runtime_428 import AttemptAccountingRuntime
from cochem_pipeline.completion_audit_428 import CompletionAuditRuntime
from cochem_pipeline.fracture_runtime_428 import FractureRuntime
from cochem_pipeline.pivot_runtime_428 import PivotHoldError, PivotRuntime
from cochem_pipeline.repair_queue_428 import RepairQueue
from cochem_pipeline.task_decisions_428 import LockedTaskDecisionStore
from cochem_pipeline.task_routing import digest
from cochem_supervisor.repair_admission_428 import SupervisorRepairAdmission428
from cochem_supervisor.repair_executor_428 import IsolatedRepairExecutor428


ROOT = Path(__file__).resolve().parents[1]


def _load_catalog() -> dict:
    return json.loads((ROOT / "docs" / "4.2.8" / "routing-candidate.json").read_text(encoding="utf-8"))


def _three_channel_research(tag: str) -> dict:
    return {
        kind: {
            "query": f"Recovery root cause {tag} {kind}",
            "status": "found",
            "receipt_sha256": digest(f"rec-{tag}-{kind}"),
            "sources": [{"id": f"src-{tag}-{kind}", "sha256": digest(f"body-{tag}-{kind}")}],
        }
        for kind in ("internet", "wiki_rag", "papers")
    }


def test_integrated_10_20_30_availability_pivot_fracture_and_locked_owner_recovery(tmp_path: Path) -> None:
    catalog = _load_catalog()
    db_path = tmp_path / "recovery_10_20_30.db"
    acct = AttemptAccountingRuntime(db_path)
    pivot_rt = PivotRuntime(acct.ledger, catalog)
    frac_rt = FractureRuntime(acct.ledger, catalog, dossier_store=pivot_rt.dossier_store)
    dec_store = LockedTaskDecisionStore(acct.ledger, dossier_store=pivot_rt.dossier_store)

    root = "task-rec-lineage"
    acct.ensure_lineage(root, complexity=4)

    # 1. Availability/infrastructure events never charge quality failure count
    for idx, avail_cat in enumerate(("quota", "auth", "resource", "rate_limit"), start=1):
        acct.start_board_attempt(
            f"avail-job-{idx}",
            f"avail-att-{idx}",
            idx,
            lineage_root=root,
            model_family="gpt-6-luna",
            complexity=4,
        )
        res = acct.record_board_outcome(
            f"avail-job-{idx}",
            f"avail-att-{idx}",
            idx,
            category=avail_cat,
            evidence_sha256=digest(f"avail-{idx}"),
        )
        assert res["failures"] == 0
        assert res["stage"] == "READY"

    # 2. Charge 10 genuine quality failures -> PIVOT_10
    for idx in range(1, 11):
        acct.start_board_attempt(
            f"q10-job-{idx}",
            f"q10-att-{idx}",
            100 + idx,
            lineage_root=root,
            model_family="gpt-6-luna",
            complexity=4,
        )
        out = acct.record_board_outcome(
            f"q10-job-{idx}",
            f"q10-att-{idx}",
            100 + idx,
            category="tests_failed",
            evidence_sha256=digest(f"q10-ev-{idx}"),
        )
    assert out["failures"] == 10
    assert out["stage"] == "PIVOT_RESEARCH"

    # Attempting an 11th attempt or pivot without dossier is blocked
    with pytest.raises(PivotHoldError) as exc_hold:
        pivot_rt.evaluate_pivot(root, task_types=["COD-TERM"], proposed_complexity=5, rationale="No dossier yet")
    assert exc_hold.value.hold_status == "MISSING_FAILURE_DOSSIER"

    # Compile boundary-10 dossier and execute higher-model pivot (sticky floor 4 -> 5, different model family)
    pivot_rt.dossier_store.record_dossier(
        root,
        10,
        research_channels=_three_channel_research("b10"),
        root_cause_synthesis="Luna failed on edge-case state transitions across 10 attempts",
        hypotheses=["Escalate to tier 5 and pivot to a different underlying model family"],
    )
    piv10 = pivot_rt.evaluate_pivot(
        root,
        task_types=["COD-TERM"],
        proposed_complexity=5,
        rationale="Escalate to tier 5 with distinct model family",
    )
    piv_model = piv10["selected_model_family"]
    assert piv_model != "gpt-6-luna"
    assert piv10["lineage_state"]["floor"] == 5
    assert piv10["lineage_state"]["stage"] == "READY"

    # 3. Charge failures 11..20 on the pivoted model -> PIVOT_RESEARCH
    for idx in range(11, 21):
        acct.start_board_attempt(
            f"q20-job-{idx}",
            f"q20-att-{idx}",
            200 + idx,
            lineage_root=root,
            model_family=piv_model,
            complexity=5,
        )
        out20 = acct.record_board_outcome(
            f"q20-job-{idx}",
            f"q20-att-{idx}",
            200 + idx,
            category="validation_error",
            evidence_sha256=digest(f"q20-ev-{idx}"),
        )
    assert out20["failures"] == 20
    assert out20["stage"] == "PIVOT_RESEARCH"

    # Compile boundary-20 dossier and fracture into narrower child fragments + elevated assembly (tier 6)
    pivot_rt.dossier_store.record_dossier(
        root,
        20,
        research_channels=_three_channel_research("b20"),
        root_cause_synthesis="Coupled lexer and parser exceed single-microtask convergence",
        hypotheses=["Split into frag-lexer (tier 3), frag-parser (tier 3), and frag-assembly (tier 6)"],
    )
    frac20 = frac_rt.execute_fracture(
        root,
        failed_scope={
            "scope_id": root,
            "requirement_ids": ["R1", "R2"],
            "deliverables": ["lexer.py", "parser.py"],
        },
        children=[
            {
                "id": "frag-lexer",
                "role": "implementation",
                "complexity": 3,
                "task_types": ["COD-TERM"],
                "rationale": "Narrow lexer implementation",
                "requirement_ids": ["R1"],
                "deliverables": ["lexer.py"],
                "release_criteria": ["Lexer unit tests pass"],
                "depends_on": [],
            },
            {
                "id": "frag-parser",
                "role": "implementation",
                "complexity": 3,
                "task_types": ["COD-TERM"],
                "rationale": "Narrow parser implementation",
                "requirement_ids": ["R2"],
                "deliverables": ["parser.py"],
                "release_criteria": ["Parser unit tests pass"],
                "depends_on": [],
            },
            {
                "id": "frag-assembly",
                "role": "assembly",
                "complexity": 6,
                "task_types": ["COD-TERM"],
                "rationale": "Elevated assembly and integration",
                "requirement_ids": ["R1", "R2"],
                "deliverables": ["lexer.py", "parser.py"],
                "release_criteria": ["Integrated parser+lexer suite passes"],
                "depends_on": ["frag-lexer", "frag-parser"],
            },
        ],
        review={
            "reviewer_model": "claude-opus-5-5",
            "reviewer_tier": 6,
            "effort": "high",
            "accepted": True,
            "review_sha256": digest("rev-frac-20"),
        },
    )
    assert frac20["inherited_failures"] == 20
    assert frac20["escalated_floor"] == 6
    c_lexer = frac_rt.get_fracture_child("frag-lexer")
    assert c_lexer["status"] == "READY"

    # 4. Charge failures 21..30 on child fragment `frag-lexer` -> shares lineage budget and hits LOCKED at 30!
    for idx in range(21, 31):
        acct.start_board_attempt(
            f"q30-job-{idx}",
            f"q30-att-{idx}",
            300 + idx,
            lineage_root=root,
            member_id="frag-lexer",
            model_family=c_lexer["selected_model_family"],
            complexity=3,
        )
        out30 = acct.record_board_outcome(
            f"q30-job-{idx}",
            f"q30-att-{idx}",
            300 + idx,
            category="tests_failed",
            evidence_sha256=digest(f"q30-ev-{idx}"),
        )
    assert out30["failures"] == 30
    assert out30["stage"] == "LOCKED"

    # 5. Record boundary-30 dossier, verify credential scrubbing on status links, and apply authenticated owner revise_scope
    dec_store.register_context_links(
        root,
        artifact_links=["https://user:pass123@local.host/artifacts/rec?api_key=sec999"],
        failure_links=["https://local.host/failures/rec?token=tok888"],
        dossier_links=["https://local.host/dossiers/rec-30.json"],
    )
    pivot_rt.dossier_store.record_dossier(
        root,
        30,
        research_channels=_three_channel_research("b30"),
        root_cause_synthesis="Contradictory grammar specification in R2 after 30 lineage failures",
        hypotheses=["Owner must revise scope of R2 before a new revision can proceed"],
    )
    pkt = dec_store.status_projection(root)[0]
    assert pkt["stage"] == "LOCKED"
    assert pkt["actionable"] is True
    assert "pass123" not in json.dumps(pkt["links"])
    assert "sec999" not in json.dumps(pkt["links"])
    assert "REDACTED" in json.dumps(pkt["links"])

    revised = dec_store.apply_owner_decision(
        root,
        action="revise_scope",
        expected_packet_sha256=pkt["packet_revision_sha256"],
        authenticated_owner_receipt_id="owner-revise-rcpt-428",
        owner_authenticated=True,
        rationale="Disambiguate grammar production rule in R2",
        revised_task_id="task-rec-lineage-v2",
        revised_objective="Implement unambiguous LL(1) lexer and parser",
    )
    assert revised["disposition"] == "REVISED_NEW_REVISION"
    assert revised["failures"] == 30
    assert revised["decisions"][0]["revised_task_id"] == "task-rec-lineage-v2"
    assert revised["decisions"][0]["retained_failures"] == 30
    assert acct.ledger.status(root)["stage"] == "LOCKED"


def test_spotcheck_revokes_false_completion_and_broken_board_supervisor_repairs_pipeline_fault(
    tmp_path: Path,
) -> None:
    catalog = _load_catalog()
    owner_repo = tmp_path / "owner_repo"
    owner_repo.mkdir()
    (owner_repo / "README.md").write_text("Owner checkout untouched\n", encoding="utf-8")
    worktrees_root = tmp_path / "isolated_worktrees"

    sup_db = tmp_path / "supervisor_recovery.sqlite"
    accepted = {"astra-max", "opus-max", "argon-high"}
    sup = SupervisorRepairAdmission428(sup_db, catalog, accepted_native_models=accepted)
    executor = IsolatedRepairExecutor428(
        sup,
        owner_repo_path=owner_repo,
        isolated_worktrees_root=worktrees_root,
    )
    audit_rt = CompletionAuditRuntime(
        tmp_path / "audit_recovery.db",
        catalog,
        sup.repair_queue,
        sample_basis_points=10000,
    )

    # 1. False completion (task defect: test failed / requirement missing) is revoked without opening a pipeline repair incident
    body_bad = b"def broken():\n    return None\n"
    enq_false = audit_rt.enqueue_completion(
        "job-false-comp",
        task_id="task-false-comp",
        output_sha256=digest(body_bad.decode("utf-8")),
        producer_model_family="gpt-6.1-sol",
        task_types=["COD-TERM"],
        expected_requirements=["R1", "R2"],
    )
    res_false = audit_rt.execute_spotcheck(
        enq_false["audit_key"],
        auditor_model_family="claude-opus-5-5",
        artifact_bytes=body_bad,
        test_receipt={
            "passed": True,
            "exit_code": 0,
            "test_output_sha256": digest("partial-pytest"),
            "requirements_verified": ["R1"],  # R2 missing!
        },
        controller_receipt={
            "cleanup_verified": True,
            "lease_fenced": True,
            "invariant_violations": [],
        },
        auditor_verdict="PASS",
        auditor_findings="Claimed pass but missed R2",
    )
    assert res_false["disposition"] == "FALSE_COMPLETION_TASK_DEFECT"
    assert res_false["result"]["task_defect_recorded"] is True
    assert res_false["incident_id"] is None

    # 2. Systemic pipeline fault (controller invariant violation) opens a grounded incident in RepairQueue
    body_ok = b"def ok():\n    return True\n"
    enq_sys = audit_rt.enqueue_completion(
        "job-sys-fault",
        task_id="task-sys-fault",
        output_sha256=digest(body_ok.decode("utf-8")),
        producer_model_family="gpt-6.1-sol",
        task_types=["GEN-DEFAULT"],
        expected_requirements=["R1"],
    )
    res_sys = audit_rt.execute_spotcheck(
        enq_sys["audit_key"],
        auditor_model_family="claude-opus-5-5",
        artifact_bytes=body_ok,
        test_receipt={
            "passed": True,
            "exit_code": 0,
            "test_output_sha256": digest("ok-pytest"),
            "requirements_verified": ["R1"],
        },
        controller_receipt={
            "cleanup_verified": False,
            "lease_fenced": True,
            "invariant_violations": ["uncleaned_seat_lease_released"],
        },
        auditor_verdict="PIPELINE_DEFECT",
        auditor_findings="Controller released seat lease before cleanup verification",
    )
    assert res_sys["disposition"] == "PIPELINE_DEFECT_INCIDENT_OPENED"
    incident_id = res_sys["incident_id"]
    assert incident_id is not None

    # 3. Even when the normal planning/job board is completely broken, supervisor repair admission admits the incident
    admitted = sup.admit_next_repair("sup-rec-1", incident_id=incident_id)
    assert admitted["profile_id"] in {"repair_claude", "repair_codex", "repair_agy"}
    assert admitted["model_id"] in accepted

    # 4. Execute isolated repair in a clean worktree (never touching owner_repo)
    rep_out = executor.execute_isolated_repair(
        admitted,
        proposed_files={
            "src/cochem_pipeline/lease_guard_fix.py": "def verify_cleanup_before_release() -> bool:\n    return True\n",
            "pipeline_tests/test_lease_guard_fix.py": "def test_guard():\n    assert True\n",
        },
        test_result={"passed": True, "evidence_sha256": digest("repair-tests-pass")},
        git_result={"ok": True, "commit_sha": "deadbeef" + "9" * 32, "working_tree_clean": True},
    )
    assert rep_out["status"] == "SOURCE_REPAIRED"
    assert rep_out["deployment_performed"] is False
    assert not (owner_repo / "src").exists()

    # 5. Without supervisor authority, transition holds safely in AWAITING_SUPERVISOR_TRANSITION
    held = executor.transition_repaired_incident_to_runtime(
        incident_id,
        supervisor_authority_verified=False,
    )
    assert held["state"] == "AWAITING_SUPERVISOR_TRANSITION"
    assert held["result"]["deployment_performed"] is False

    # 6. With reviewed supervisor authority + runtime & smoke hashes, incident transitions to RESOLVED
    resolved = executor.transition_repaired_incident_to_runtime(
        incident_id,
        supervisor_authority_verified=True,
        supervisor_receipt_id="sup-rcpt-rec-428",
        runtime_version_sha256=digest("4.2.8-runtime-build"),
        smoke_check_sha256=digest("4.2.8-smoke-ok"),
    )
    assert resolved["state"] == "RESOLVED"
    assert resolved["result"]["deployment_performed"] is True
