"""Tests for `P428-19`: Execute completion spot checks and open grounded incidents (`completion_audit_428.py`, `repair_queue_428.py`)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cochem_pipeline.completion_audit_428 import CompletionAuditRuntime
from cochem_pipeline.repair_queue_428 import RepairQueue
from cochem_pipeline.task_routing import digest


ROOT = Path(__file__).resolve().parents[1]


def _load_catalog() -> dict:
    return json.loads((ROOT / "docs" / "4.2.8" / "routing-candidate.json").read_text(encoding="utf-8"))


def _make_repair_queue(tmp_path: Path, catalog: dict) -> RepairQueue:
    profiles = {
        "repair_claude": {"provider": "claude", "quota_pool": "anthropic"},
        "repair_codex": {"provider": "codex", "quota_pool": "openai"},
        "repair_agy": {"provider": "gemini", "quota_pool": "google"},
    }
    return RepairQueue(
        tmp_path / "repair_incidents.db",
        catalog,
        profiles=profiles,
        normal_profile_ids={"slot1", "slot2", "slot3", "slot4"},
        verify_reservation=lambda _: None,
        verify_commit=lambda c, t: None,
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_legitimate_false_completion_missing_artifact_and_systemic_fault(tmp_path: Path) -> None:
    catalog = _load_catalog()
    rq = _make_repair_queue(tmp_path, catalog)
    audit_rt = CompletionAuditRuntime(
        tmp_path / "audit428.db",
        catalog,
        rq,
        sample_basis_points=10000,  # 100% sample in test
    )

    # 1. Legitimate completion -> VERIFIED_PASS, no repair incident
    good_bytes = b"def solve():\n    return 42\n"
    good_sha = _sha256_bytes(good_bytes)
    enq_ok = audit_rt.enqueue_completion(
        "job-legit-1",
        task_id="task-1",
        output_sha256=good_sha,
        producer_model_family="gpt-6.1-sol",
        task_types=["COD-TERM"],
        expected_requirements=["R1", "R2"],
    )
    assert enq_ok["sampled"] is True
    assert enq_ok["status"] == "QUEUED"

    # Producer model cannot audit its own completion
    with pytest.raises(ValueError, match="different model family"):
        audit_rt.execute_spotcheck(
            enq_ok["audit_key"],
            auditor_model_family="gpt-6.1-sol",
            artifact_bytes=good_bytes,
            test_receipt={
                "passed": True,
                "exit_code": 0,
                "test_output_sha256": digest("test-ok"),
                "requirements_verified": ["R1", "R2"],
            },
            controller_receipt={
                "cleanup_verified": True,
                "lease_fenced": True,
                "invariant_violations": [],
            },
            auditor_verdict="PASS",
            auditor_findings="All requirements and tests verified",
        )

    res_ok = audit_rt.execute_spotcheck(
        enq_ok["audit_key"],
        auditor_model_family="claude-opus-5-5",
        artifact_bytes=good_bytes,
        test_receipt={
            "passed": True,
            "exit_code": 0,
            "test_output_sha256": digest("test-ok"),
            "requirements_verified": ["R1", "R2"],
        },
        controller_receipt={
            "cleanup_verified": True,
            "lease_fenced": True,
            "invariant_violations": [],
        },
        auditor_verdict="PASS",
        auditor_findings="All requirements and tests verified",
    )
    assert res_ok["disposition"] == "VERIFIED_PASS"
    assert res_ok["incident_id"] is None
    assert rq.list_incidents() == []

    # 2. False completion (valid SHA-256 hash on stubbed code, or missing requirement verification)
    # -> TASK_DEFECT, revokes completion without flooding RepairQueue!
    stub_bytes = b"# TODO: stubbed implementation\npass\n"
    stub_sha = _sha256_bytes(stub_bytes)
    enq_false = audit_rt.enqueue_completion(
        "job-false-1",
        task_id="task-2",
        output_sha256=stub_sha,
        producer_model_family="gpt-6.1-sol",
        task_types=["COD-TERM"],
        expected_requirements=["R1", "R2"],
    )
    res_false = audit_rt.execute_spotcheck(
        enq_false["audit_key"],
        auditor_model_family="claude-opus-5-5",
        artifact_bytes=stub_bytes,
        test_receipt={
            "passed": True,
            "exit_code": 0,
            "test_output_sha256": digest("test-stub"),
            "requirements_verified": ["R1", "R2"],
        },
        controller_receipt={
            "cleanup_verified": True,
            "lease_fenced": True,
            "invariant_violations": [],
        },
        auditor_verdict="TASK_DEFECT",
        auditor_findings="Output hash matched but artifact is a no-op stub",
    )
    assert res_false["disposition"] == "FALSE_COMPLETION_TASK_DEFECT"
    assert res_false["result"]["task_defect_recorded"] is True
    assert res_false["incident_id"] is None
    assert rq.list_incidents() == []

    # 3. Missing artifact -> FALSE_COMPLETION_TASK_DEFECT
    enq_missing = audit_rt.enqueue_completion(
        "job-missing-1",
        task_id="task-3",
        output_sha256=digest("expected-missing"),
        producer_model_family="gpt-6.1-sol",
        task_types=["COD-TERM"],
        expected_requirements=["R1"],
    )
    res_missing = audit_rt.execute_spotcheck(
        enq_missing["audit_key"],
        auditor_model_family="claude-opus-5-5",
        artifact_path=tmp_path / "does_not_exist.py",
        test_receipt={
            "passed": True,
            "exit_code": 0,
            "test_output_sha256": digest("test-m"),
            "requirements_verified": ["R1"],
        },
        controller_receipt={
            "cleanup_verified": True,
            "lease_fenced": True,
            "invariant_violations": [],
        },
        auditor_verdict="PASS",
        auditor_findings="Checked missing path",
    )
    assert res_missing["disposition"] == "FALSE_COMPLETION_TASK_DEFECT"
    assert res_missing["result"]["artifact_missing"] is True
    assert rq.list_incidents() == []

    # 4. Systemic / controller fault -> PIPELINE_DEFECT_INCIDENT_OPENED in RepairQueue
    enq_sys = audit_rt.enqueue_completion(
        "job-sysfault-1",
        task_id="task-4",
        output_sha256=good_sha,
        producer_model_family="gpt-6.1-sol",
        task_types=["COD-TERM"],
        expected_requirements=["R1"],
    )
    res_sys = audit_rt.execute_spotcheck(
        enq_sys["audit_key"],
        auditor_model_family="claude-opus-5-5",
        artifact_bytes=good_bytes,
        test_receipt={
            "passed": True,
            "exit_code": 0,
            "test_output_sha256": digest("test-sys"),
            "requirements_verified": ["R1"],
        },
        controller_receipt={
            "cleanup_verified": False,
            "lease_fenced": True,
            "invariant_violations": ["orphan_process_tree_survived_release"],
        },
        auditor_verdict="PIPELINE_DEFECT",
        auditor_findings="Controller released job without native process tree cleanup",
    )
    assert res_sys["disposition"] == "PIPELINE_DEFECT_INCIDENT_OPENED"
    assert res_sys["incident_id"] is not None
    incidents = rq.list_incidents()
    assert len(incidents) == 1
    assert incidents[0]["incident_id"] == res_sys["incident_id"]
    assert incidents[0]["state"] == "QUEUED"


def test_deduplication_restart_availability_uncertainty_and_bounded_capacity(tmp_path: Path) -> None:
    catalog = _load_catalog()
    rq = _make_repair_queue(tmp_path, catalog)
    db_path = tmp_path / "audit_bounds.db"
    audit_rt = CompletionAuditRuntime(
        db_path,
        catalog,
        rq,
        sample_basis_points=10000,
        max_pending_audits=2,
        max_active_audits=1,
    )

    # 1. Enqueue 2 audits (filling max_pending_audits=2)
    body_b1 = b"valid code"
    sha_b1 = _sha256_bytes(body_b1)
    a1 = audit_rt.enqueue_completion(
        "job-b1",
        task_id="t1",
        output_sha256=sha_b1,
        producer_model_family="gpt-6-luna",
        task_types=["COD-TERM"],
        expected_requirements=["R1"],
    )
    # Duplicate enqueue of the exact same (job_id, output_sha256) deduplicates!
    a1_dup = audit_rt.enqueue_completion(
        "job-b1",
        task_id="t1",
        output_sha256=sha_b1,
        producer_model_family="gpt-6-luna",
        task_types=["COD-TERM"],
        expected_requirements=["R1"],
    )
    assert a1_dup["deduplicated"] is True
    assert a1_dup["audit_key"] == a1["audit_key"]

    a2 = audit_rt.enqueue_completion(
        "job-b2",
        task_id="t2",
        output_sha256=digest("o2"),
        producer_model_family="gpt-6-luna",
        task_types=["COD-TERM"],
        expected_requirements=["R1"],
    )
    assert a2["status"] == "QUEUED"

    # 3rd pending audit exceeds max_pending_audits=2 -> bounded as SKIPPED_AUDIT_CAPACITY
    a3 = audit_rt.enqueue_completion(
        "job-b3",
        task_id="t3",
        output_sha256=digest("o3"),
        producer_model_family="gpt-6-luna",
        task_types=["COD-TERM"],
        expected_requirements=["R1"],
    )
    assert a3["status"] == "SKIPPED_AUDIT_CAPACITY"

    # 2. Quota wait -> transitions to WAITING_QUOTA without opening an incident
    w1 = audit_rt.start_audit(
        a1["audit_key"],
        auditor_model_family="claude-opus-5-5",
        availability_status="quota_exhausted",
    )
    assert w1["status"] == "WAITING_QUOTA"
    assert rq.list_incidents() == []

    # 3. Start a1 when ready -> IN_PROGRESS; starting a2 concurrently exceeds max_active_audits=1!
    in_prog = audit_rt.start_audit(
        a1["audit_key"],
        auditor_model_family="claude-opus-5-5",
        availability_status="ready",
    )
    assert in_prog["status"] == "IN_PROGRESS"
    with pytest.raises(ValueError, match="max_active_audits"):
        audit_rt.start_audit(
            a2["audit_key"],
            auditor_model_family="claude-opus-5-5",
            availability_status="ready",
        )

    # 4. Simulate restart while a1 is IN_PROGRESS -> recovers to QUEUED
    restarted_rt = CompletionAuditRuntime(
        db_path,
        catalog,
        rq,
        sample_basis_points=10000,
        max_pending_audits=2,
        max_active_audits=1,
    )
    assert restarted_rt.get_spotcheck(a1["audit_key"])["status"] == "QUEUED"

    # 5. Model uncertainty (UNCERTAIN) -> INCONCLUSIVE_HOLD, never opens a repair incident
    body_b1 = b"valid code"
    res_uncertain = restarted_rt.execute_spotcheck(
        a1["audit_key"],
        auditor_model_family="claude-opus-5-5",
        artifact_bytes=body_b1,
        test_receipt={
            "passed": True,
            "exit_code": 0,
            "test_output_sha256": digest("t-b1"),
            "requirements_verified": ["R1"],
        },
        controller_receipt={
            "cleanup_verified": True,
            "lease_fenced": True,
            "invariant_violations": [],
        },
        auditor_verdict="UNCERTAIN",
        auditor_findings="Ambiguous edge-case behavior; inconclusive",
    )
    assert res_uncertain["disposition"] == "INCONCLUSIVE_HOLD"
    assert res_uncertain["incident_id"] is None
    assert rq.list_incidents() == []
