"""Tests for `P428-12`: Reassessed microtask dependency graph materialization (`microtask_board_428.py`)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cochem_pipeline.microtask_board_428 import (
    MicrotaskBoardRuntime,
    validate_microtask_execution_output,
)
from cochem_pipeline.owner_approval_428 import OwnerApprovalBroker
from cochem_pipeline.planning_journal import PlanningJournal
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.store import JobStore
from cochem_pipeline.task_routing import digest
from cochem_pipeline.workflow_428 import (
    accept_microtasks,
    accept_research,
    accept_review,
    accept_srs,
    accept_wbs,
    approve_srs,
    compile_reassessed_microtask_plan,
)


from pipeline_tests.test_planning_gateway_428 import accepted_receipt
from pipeline_tests.task_catalog_fixtures import accepted_planning_store


ROOT = Path(__file__).resolve().parents[1]
OWNER_SECRET = "owner-secret-key-with-at-least-32-chars-428"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_store_and_journal(tmp_path: Path):
    store, catalog = accepted_planning_store(tmp_path / "board.db")
    journal = PlanningJournal(tmp_path / "planning428.db", catalog, flash_context_limit=100000)
    broker = OwnerApprovalBroker(tmp_path / "owner428.db", owner_secret=OWNER_SECRET)
    return store, journal, broker


def _advance_task_to_reassessed_ready(
    journal: PlanningJournal,
    *,
    task_id: str,
    child_mt3_complexity: int = 5,
    include_second_independent_fragment: bool = True,
) -> dict:
    journal.create(task_id, "Build multi-module quantum chemistry solver and validation suite")
    v = journal.status(task_id)["journal_version"]
    journal._transition(
        task_id,
        v,
        "test.ready_mt",
        {},
        lambda row: _transition_to_ready_state(
            row,
            child_mt3_complexity=child_mt3_complexity,
            include_second_independent_fragment=include_second_independent_fragment,
        ),
    )
    return journal.status(task_id)


def _transition_to_ready_state(
    row,
    *,
    child_mt3_complexity: int,
    include_second_independent_fragment: bool,
) -> dict:
    state = json.loads(row["state_json"])
    limit = row["flash_context_limit"]
    srs_doc = {
        "plan": "Multi-module quantum solver architecture",
        "architecture": "Three bounded modules with integration harness",
        "srs": [
            {"id": "sec-core", "requirement_ids": ["req-1"], "text": "Core Hamiltonian module"},
            {"id": "sec-num", "requirement_ids": ["req-2"], "text": "Numerical Davidson kernel"},
            {"id": "sec-int", "requirement_ids": ["req-3"], "text": "Integration and verification"},
        ],
        "requirements": [
            {"id": "req-1", "text": "Implement Hamiltonian parser"},
            {"id": "req-2", "text": "Implement Davidson eigensolver"},
            {"id": "req-3", "text": "Assemble and validate full solver pipeline"},
        ],
        "assessment": {
            "complexity": 8,
            "task_types": ["AGT-PROJ", "SCI-FORMAL"],
            "rationale": "Multi-module numerical and architectural design",
        },
        "release_criteria": ["All 3 requirements verified end-to-end"],
        "srs_tokens": 500,
        "evidence_and_instruction_tokens": 500,
        "output_reserve_tokens": 500,
    }
    state = accept_srs(state, srs_doc, planner_model="gpt-6.1-sol", flash_context_limit=limit)
    state["planner_profile"] = "gpt-6.1-sol-high"
    state = approve_srs(state, state["srs_sha256"], "owner-rcpt-001")
    res_channels = {
        kind: {
            "query": "Davidson eigensolver convergence",
            "status": "found",
            "receipt_sha256": digest(kind),
            "sources": [{"id": f"{kind}-src", "sha256": digest(f"{kind}-body")}],
        }
        for kind in ("internet", "wiki_rag", "papers")
    }
    state = accept_research(state, res_channels)
    state = accept_review(
        state,
        reviewer_model="claude-opus-5-5",
        reviewer_tier=9,
        effort="max",
        accepted=True,
        review_sha256=digest("review-ok"),
    )
    wbs_rows = [
        {
            "id": "wbs-1",
            "section_ids": ["sec-core"],
            "requirement_ids": ["req-1"],
            "deliverables": ["hamiltonian.py"],
            "audit_metrics": ["unit test passes"],
            "release_criteria": ["req-1 proven"],
            "depends_on": [],
        },
        {
            "id": "wbs-2",
            "section_ids": ["sec-num"],
            "requirement_ids": ["req-2"],
            "deliverables": ["davidson.py"],
            "audit_metrics": ["residual < 1e-8"],
            "release_criteria": ["req-2 proven"],
            "depends_on": [],
        },
        {
            "id": "wbs-3",
            "section_ids": ["sec-int"],
            "requirement_ids": ["req-3"],
            "deliverables": ["solver.py", "test_solver.py"],
            "audit_metrics": ["integration test passes"],
            "release_criteria": ["req-3 proven"],
            "depends_on": ["wbs-1", "wbs-2"],
        },
    ]
    state = accept_wbs(state, wbs_rows)
    mt_rows = [
        {
            "id": "mt-1",
            "wbs_ids": ["wbs-1"],
            "role": "implementation",
            "complexity": 4,
            "task_types": ["COD-TERM"],
            "deliverables": ["hamiltonian.py"],
            "audit_metrics": ["zero lint errors"],
            "release_criteria": ["Hamiltonian unit tests pass"],
            "depends_on": [],
            "prompt": "Implement Hamiltonian parser",
        },
        {
            "id": "mt-2",
            "wbs_ids": ["wbs-2"],
            "role": "implementation",
            "complexity": 6,
            "task_types": ["COD-TERM", "SCI-FORMAL"],
            "deliverables": ["davidson.py"],
            "audit_metrics": ["residual < 1e-8"],
            "release_criteria": ["Davidson convergence tests pass"],
            "depends_on": [] if include_second_independent_fragment else ["mt-1"],
            "prompt": "Implement Davidson eigensolver",
        },
        {
            "id": "mt-3",
            "wbs_ids": ["wbs-3"],
            "role": "assembly",
            "complexity": child_mt3_complexity,
            "task_types": ["AGT-PROJ"],
            "deliverables": ["solver.py"],
            "audit_metrics": ["clean imports"],
            "release_criteria": ["Assembly smoke test passes"],
            "depends_on": ["mt-1", "mt-2"],
            "prompt": "Assemble solver package",
        },
        {
            "id": "mt-4",
            "wbs_ids": ["wbs-3"],
            "role": "final_test",
            "complexity": 5,
            "task_types": ["COD-SCI"],
            "deliverables": ["test_solver.py"],
            "audit_metrics": ["100% requirement coverage"],
            "release_criteria": ["End-to-end solver verification passes"],
            "depends_on": ["mt-1", "mt-2", "mt-3"],
            "prompt": "Verify assembled solver package",
        },
    ]
    state = accept_microtasks(state, mt_rows)
    assessments = [
        {
            "id": row["id"],
            "complexity": row["complexity"],
            "task_types": row["task_types"],
            "rationale": f"Reassessed {row['id']}",
        }
        for row in mt_rows
    ]
    return PlanningJournal._accept_micro_assessments(state, {"assessments": assessments})


def _complete_claimed_job_for_node(store: JobStore, claimed: dict, node: dict) -> None:
    deliverables = [
        {
            "name": d,
            "content": f"# Deliverable {d} for {node['microtask_id']}\n",
            "sha256": _sha256_text(f"# Deliverable {d} for {node['microtask_id']}\n"),
        }
        for d in node["deliverables"]
    ]
    first_deliv = deliverables[0]["name"]
    output = {
        "artifact_text": f"Completed {node['microtask_id']} ({node['role']})",
        "deliverables": deliverables,
        "requirement_evidence": [
            {
                "requirement_id": req_id,
                "deliverable_name": first_deliv,
                "verification_evidence": f"Verified {req_id} via {first_deliv}",
            }
            for req_id in node["requirement_ids"]
        ],
        "release_criteria_results": [
            {
                "criterion": crit,
                "passed": True,
                "evidence": f"Satisfied {crit}",
            }
            for crit in node["release_criteria"]
        ],
    }
    store.clear_execution_quarantine(claimed["job_id"], claimed["attempt_id"], claimed["fencing_token"])
    store.complete(
        claimed["job_id"],
        claimed["attempt_id"],
        claimed["fencing_token"],
        output,
        accepted_receipt(claimed, output),
    )


def _complete_board_job_for_node(store: JobStore, job_id: str, node: dict, slot: str = "slot1") -> None:
    claimed = store.claim(
        "worker-mt",
        worker_slot=slot,
        max_workers=4,
        allowed_kinds=["TASK_PLAN"],
        requires_cleanup=True,
    )
    assert claimed is not None and claimed["job_id"] == job_id
    _complete_claimed_job_for_node(store, claimed, node)


def test_multitype_wbs_mixed_tiers_and_parallel_fragment_claims(tmp_path: Path) -> None:
    store, journal, broker = _make_store_and_journal(tmp_path)
    _advance_task_to_reassessed_ready(
        journal,
        task_id="task428-mt-dag",
        child_mt3_complexity=5,
        include_second_independent_fragment=True,
    )
    with journal._write() as conn:
        raw_state = json.loads(journal._read(conn, "task428-mt-dag")["state_json"])
    compiled = compile_reassessed_microtask_plan(raw_state)
    assert [n["microtask_id"] for n in compiled] == ["mt-1", "mt-2", "mt-3", "mt-4"]
    assert compiled[0]["lineage_kind"] == "WBS_CHILD"
    assert compiled[0]["section_ids"] == ["sec-core"]
    assert compiled[1]["task_types"] == ["COD-TERM", "SCI-FORMAL"]

    board = MicrotaskBoardRuntime(journal, store, owner_broker=broker)
    snap = board.materialize("task428-mt-dag")
    by_id = {n["microtask_id"]: n for n in snap["nodes"]}

    # Independent fragments mt-1 and mt-2 are DISPATCHED concurrently;
    # dependent assembly (mt-3) and final_test (mt-4) remain WAITING_ON_DEPENDENCIES without board jobs!
    assert by_id["mt-1"]["status"] == "DISPATCHED"
    assert by_id["mt-1"]["job_id"] is not None
    assert by_id["mt-2"]["status"] == "DISPATCHED"
    assert by_id["mt-2"]["job_id"] is not None
    assert by_id["mt-3"]["status"] == "WAITING_ON_DEPENDENCIES"
    assert by_id["mt-3"]["job_id"] is None
    assert by_id["mt-4"]["status"] == "WAITING_ON_DEPENDENCIES"
    assert by_id["mt-4"]["job_id"] is None

    # Both independent fragments can be claimed in parallel on the 4-slot pool
    claim1 = store.claim(
        "worker-1",
        worker_slot="slot1",
        max_workers=4,
        allowed_kinds=["TASK_PLAN"],
        requires_cleanup=True,
    )
    claim2 = store.claim(
        "worker-2",
        worker_slot="slot2",
        max_workers=4,
        allowed_kinds=["TASK_PLAN"],
        requires_cleanup=True,
    )
    assert claim1 is not None and claim2 is not None
    claimed_by_jid = {claim1["job_id"]: claim1, claim2["job_id"]: claim2}
    assert set(claimed_by_jid) == {by_id["mt-1"]["job_id"], by_id["mt-2"]["job_id"]}

    # Complete mt-1 only; mt-3 still waits on mt-2
    _complete_claimed_job_for_node(store, claimed_by_jid[by_id["mt-1"]["job_id"]], by_id["mt-1"])

    snap2 = board.materialize("task428-mt-dag")
    by_id2 = {n["microtask_id"]: n for n in snap2["nodes"]}
    assert by_id2["mt-1"]["status"] == "COMPLETED"
    assert by_id2["mt-3"]["status"] == "WAITING_ON_DEPENDENCIES"
    assert by_id2["mt-3"]["job_id"] is None

    # Complete mt-2; now mt-3 (assembly) becomes DISPATCHED while mt-4 (final_test) still waits
    _complete_claimed_job_for_node(store, claimed_by_jid[by_id["mt-2"]["job_id"]], by_id["mt-2"])

    snap3 = board.materialize("task428-mt-dag")
    by_id3 = {n["microtask_id"]: n for n in snap3["nodes"]}
    assert by_id3["mt-2"]["status"] == "COMPLETED"
    assert by_id3["mt-3"]["status"] == "DISPATCHED"
    assert by_id3["mt-3"]["job_id"] is not None
    assert by_id3["mt-4"]["status"] == "WAITING_ON_DEPENDENCIES"

    # Complete mt-3 (assembly) and then mt-4 (final_test)
    _complete_board_job_for_node(store, by_id3["mt-3"]["job_id"], by_id3["mt-3"])
    snap4 = board.materialize("task428-mt-dag")
    by_id4 = {n["microtask_id"]: n for n in snap4["nodes"]}
    assert by_id4["mt-3"]["status"] == "COMPLETED"
    assert by_id4["mt-4"]["status"] == "DISPATCHED"

    _complete_board_job_for_node(store, by_id4["mt-4"]["job_id"], by_id4["mt-4"])
    snap5 = board.materialize("task428-mt-dag")
    assert snap5["all_completed"] is True


def test_newly_high_tier_child_holds_for_owner_approval(tmp_path: Path) -> None:
    store, journal, broker = _make_store_and_journal(tmp_path)
    _advance_task_to_reassessed_ready(
        journal,
        task_id="task428-mt-highchild",
        child_mt3_complexity=9,
    )
    board = MicrotaskBoardRuntime(journal, store, owner_broker=broker)
    snap = board.materialize("task428-mt-highchild")
    by_id = {n["microtask_id"]: n for n in snap["nodes"]}

    # Complete mt-1 and mt-2
    by_job_id = {n["job_id"]: n for n in snap["nodes"] if n["job_id"]}
    for slot in ("slot1", "slot2"):
        claimed = store.claim(
            "worker-mt",
            worker_slot=slot,
            max_workers=4,
            allowed_kinds=["TASK_PLAN"],
            requires_cleanup=True,
        )
        assert claimed is not None
        _complete_claimed_job_for_node(store, claimed, by_job_id[claimed["job_id"]])

    # Even though mt-1 and mt-2 are completed, mt-3 has complexity 9 and holds for owner approval!
    snap2 = board.materialize("task428-mt-highchild")
    by_id2 = {n["microtask_id"]: n for n in snap2["nodes"]}
    assert by_id2["mt-3"]["status"] == "HOLD_OWNER_APPROVAL"
    assert by_id2["mt-3"]["job_id"] is None

    # Wrong owner token is rejected
    with pytest.raises(PermissionError):
        board.approve_child_microtask(
            "task428-mt-highchild",
            "mt-3",
            owner_token="wrong-token",
        )

    # Valid owner token approves mt-3 and dispatches it immediately
    snap3 = board.approve_child_microtask(
        "task428-mt-highchild",
        "mt-3",
        owner_token=OWNER_SECRET,
        notes="Approved high-tier child assembly",
    )
    by_id3 = {n["microtask_id"]: n for n in snap3["nodes"]}
    assert by_id3["mt-3"]["status"] == "DISPATCHED"
    assert by_id3["mt-3"]["job_id"] is not None


def test_changed_classification_invalidates_stale_routes_and_restarts_cleanly(tmp_path: Path) -> None:
    store, journal, broker = _make_store_and_journal(tmp_path)
    _advance_task_to_reassessed_ready(
        journal,
        task_id="task428-mt-reclass",
        child_mt3_complexity=5,
    )
    board = MicrotaskBoardRuntime(journal, store, owner_broker=broker)
    snap1 = board.materialize("task428-mt-reclass")
    old_mt1_job_id = {n["microtask_id"]: n for n in snap1["nodes"]}["mt-1"]["job_id"]
    assert old_mt1_job_id is not None

    # Change mt-1 classification in the journal (e.g., after reassessment/fracture)
    v = journal.status("task428-mt-reclass")["journal_version"]

    def _reclassify(row):
        state = json.loads(row["state_json"])
        assessments = [
            {
                "id": m["id"],
                "complexity": 6 if m["id"] == "mt-1" else m["complexity"],
                "task_types": ["AGT-PROJ"] if m["id"] == "mt-1" else m["task_types"],
                "rationale": f"Reclassified {m['id']}",
            }
            for m in state["microtasks"]
        ]
        return PlanningJournal._accept_micro_assessments(state, {"assessments": assessments})

    journal._transition("task428-mt-reclass", v, "test.reclassify", {}, _reclassify)

    snap2 = board.materialize("task428-mt-reclass")
    assert snap2["superseded_nodes"] == 4
    new_mt1 = {n["microtask_id"]: n for n in snap2["nodes"]}["mt-1"]
    assert new_mt1["job_id"] != old_mt1_job_id
    assert new_mt1["complexity"] == 6

    # Old board job was cancelled
    with store._connection() as conn:
        old_job = store._get(conn, old_mt1_job_id)
        assert old_job["status"] == "FAILED"

    # Duplicate materialization and restart preserve the DAG and job IDs
    snap_dup = board.materialize("task428-mt-reclass")
    assert {n["microtask_id"]: n["job_id"] for n in snap_dup["nodes"]} == {
        n["microtask_id"]: n["job_id"] for n in snap2["nodes"]
    }
    board_restarted = MicrotaskBoardRuntime(journal, store, owner_broker=broker)
    snap_restart = board_restarted.board_status("task428-mt-reclass")
    assert snap_restart["plan_generation_sha256"] == snap2["plan_generation_sha256"]
    assert len(snap_restart["nodes"]) == 4


def test_cycle_missing_coverage_and_output_validation_rejected(tmp_path: Path) -> None:
    store, journal, broker = _make_store_and_journal(tmp_path)
    _advance_task_to_reassessed_ready(
        journal,
        task_id="task428-mt-edges",
        child_mt3_complexity=5,
    )
    with journal._write() as conn:
        raw_state = json.loads(journal._read(conn, "task428-mt-edges")["state_json"])
    compiled = compile_reassessed_microtask_plan(raw_state)
    node_mt1 = compiled[0]

    # Output with mismatched sha256 or missing deliverable is rejected
    with pytest.raises(ValueError, match="sha256 does not match"):
        validate_microtask_execution_output(
            node_mt1,
            {
                "artifact_text": "art",
                "deliverables": [{"name": "hamiltonian.py", "content": "abc", "sha256": "b" * 64}],
                "requirement_evidence": [
                    {
                        "requirement_id": "req-1",
                        "deliverable_name": "hamiltonian.py",
                        "verification_evidence": "ok",
                    }
                ],
                "release_criteria_results": [
                    {"criterion": "Hamiltonian unit tests pass", "passed": True, "evidence": "ok"}
                ],
            },
        )

    # Dependency cycle in microtask list is rejected by compile_reassessed_microtask_plan
    cyclic_state = dict(raw_state)
    cyclic_mts = [dict(m) for m in raw_state["microtasks"]]
    cyclic_mts[0]["depends_on"] = ["mt-3"]
    cyclic_state["microtasks"] = cyclic_mts
    with pytest.raises(ValueError, match="Dependency cycle"):
        compile_reassessed_microtask_plan(cyclic_state)

    # Missing SRS requirement coverage is rejected
    uncovered_state = dict(raw_state)
    uncovered_mts = [dict(m) for m in raw_state["microtasks"] if m["id"] != "mt-1"]
    uncovered_mts[1] = dict(uncovered_mts[1], depends_on=["mt-2"])
    uncovered_mts[2] = dict(uncovered_mts[2], depends_on=["mt-2", "mt-3"])
    uncovered_state["microtasks"] = uncovered_mts
    with pytest.raises(ValueError, match="cover every SRS requirement"):
        compile_reassessed_microtask_plan(uncovered_state)
