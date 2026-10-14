"""Tests for `P428-17`: Fracture and reassessment without resetting budgets (`fracture_runtime_428.py`, `workflow_428.py`)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cochem_pipeline.attempt_runtime_428 import AttemptAccountingRuntime
from cochem_pipeline.fracture_runtime_428 import FractureRuntime
from cochem_pipeline.task_routing import digest


ROOT = Path(__file__).resolve().parents[1]


def _load_catalog() -> dict:
    return json.loads((ROOT / "docs" / "4.2.8" / "routing-candidate.json").read_text(encoding="utf-8"))


def _three_channel_research() -> dict:
    return {
        kind: {
            "query": f"Fracture root cause {kind}",
            "status": "found",
            "receipt_sha256": digest(f"frac-rcpt-{kind}"),
            "sources": [{"id": f"src-{kind}", "sha256": digest(f"body-{kind}")}],
        }
        for kind in ("internet", "wiki_rag", "papers")
    }


def _charge_failures(
    acct: AttemptAccountingRuntime,
    lineage_root: str,
    member_id: str,
    *,
    start_idx: int,
    count: int,
    model_family: str,
    complexity: int,
) -> None:
    for idx in range(start_idx, start_idx + count):
        acct.start_board_attempt(
            f"job-{member_id}-{idx}",
            f"att-{member_id}-{idx}",
            idx,
            lineage_root=lineage_root,
            member_id=member_id,
            model_family=model_family,
            complexity=complexity,
        )
        acct.record_board_outcome(
            f"job-{member_id}-{idx}",
            f"att-{member_id}-{idx}",
            idx,
            category="tests_failed",
            evidence_sha256=digest(f"{lineage_root}-{member_id}-ev-{idx}"),
        )


def test_inherited_counts_10_20_29_lower_fragment_elevated_assembly_and_obsolete_closure(tmp_path: Path) -> None:
    catalog = _load_catalog()
    db_path = tmp_path / "fracture_10_20_29.db"
    acct = AttemptAccountingRuntime(db_path)
    frac_rt = FractureRuntime(acct.ledger, catalog)
    root = "task-frac-root"
    acct.ensure_lineage(root, complexity=5)

    # 1. Fail 10 times on root -> boundary 10 fracture
    _charge_failures(acct, root, root, start_idx=1, count=10, model_family="gpt-6.1-sol", complexity=5)
    frac_rt.dossier_store.record_dossier(
        root,
        10,
        research_channels=_three_channel_research(),
        root_cause_synthesis="Monolithic parser and serializer coupled",
        hypotheses=["Split into parser fragment and serializer fragment with elevated assembly"],
    )

    # Assembly below escalated floor (6) is rejected
    with pytest.raises(ValueError, match="escalated floor"):
        frac_rt.execute_fracture(
            root,
            failed_scope={
                "scope_id": root,
                "requirement_ids": ["R1", "R2"],
                "deliverables": ["parser.py", "serializer.py"],
            },
            children=[
                {
                    "id": "frag-parse",
                    "role": "implementation",
                    "complexity": 3,
                    "task_types": ["COD-TERM"],
                    "rationale": "Narrow parser fragment",
                    "requirement_ids": ["R1"],
                    "deliverables": ["parser.py"],
                    "release_criteria": ["Parser tests pass"],
                    "depends_on": [],
                },
                {
                    "id": "frag-serial",
                    "role": "implementation",
                    "complexity": 3,
                    "task_types": ["COD-TERM"],
                    "rationale": "Narrow serializer fragment",
                    "requirement_ids": ["R2"],
                    "deliverables": ["serializer.py"],
                    "release_criteria": ["Serializer tests pass"],
                    "depends_on": [],
                },
                {
                    "id": "frag-asm",
                    "role": "assembly",
                    "complexity": 5,  # below escalated floor 6!
                    "task_types": ["COD-TERM"],
                    "rationale": "Too low assembly tier",
                    "requirement_ids": ["R1", "R2"],
                    "deliverables": ["parser.py", "serializer.py"],
                    "release_criteria": ["Integrated tests pass"],
                    "depends_on": ["frag-parse", "frag-serial"],
                },
            ],
            review={
                "reviewer_model": "claude-opus-5-5",
                "reviewer_tier": 6,
                "effort": "high",
                "accepted": True,
                "review_sha256": digest("rev-10"),
            },
        )

    # Valid fracture at 10: small fragments keep complexity=3, assembly has elevated complexity=6
    f10 = frac_rt.execute_fracture(
        root,
        failed_scope={
            "scope_id": root,
            "requirement_ids": ["R1", "R2"],
            "deliverables": ["parser.py", "serializer.py"],
        },
        children=[
            {
                "id": "frag-parse",
                "role": "implementation",
                "complexity": 3,
                "task_types": ["COD-TERM"],
                "rationale": "Narrow parser fragment",
                "requirement_ids": ["R1"],
                "deliverables": ["parser.py"],
                "release_criteria": ["Parser tests pass"],
                "depends_on": [],
            },
            {
                "id": "frag-serial",
                "role": "implementation",
                "complexity": 3,
                "task_types": ["COD-TERM"],
                "rationale": "Narrow serializer fragment",
                "requirement_ids": ["R2"],
                "deliverables": ["serializer.py"],
                "release_criteria": ["Serializer tests pass"],
                "depends_on": [],
            },
            {
                "id": "frag-asm",
                "role": "assembly",
                "complexity": 6,
                "task_types": ["COD-TERM"],
                "rationale": "Elevated assembly",
                "requirement_ids": ["R1", "R2"],
                "deliverables": ["parser.py", "serializer.py"],
                "release_criteria": ["Integrated tests pass"],
                "depends_on": ["frag-parse", "frag-serial"],
            },
        ],
        review={
            "reviewer_model": "claude-opus-5-5",
            "reviewer_tier": 6,
            "effort": "high",
            "accepted": True,
            "review_sha256": digest("rev-10"),
        },
    )
    assert f10["inherited_failures"] == 10
    assert f10["escalated_floor"] == 6
    assert frac_rt.is_scope_obsolete(root) is True

    c_parse = frac_rt.get_fracture_child("frag-parse")
    c_asm = frac_rt.get_fracture_child("frag-asm")
    assert c_parse["complexity"] == 3
    assert c_parse["escalated_scope"] is False
    assert c_parse["status"] == "READY"
    assert c_parse["inherited_failures"] == 10
    assert c_asm["complexity"] == 6
    assert c_asm["escalated_scope"] is True
    assert c_asm["selected_model_family"] != "gpt-6.1-sol"
    assert c_asm["status"] == "BLOCKED_DAG"

    # Duplicate child ID in another fracture is rejected
    # First charge 10 more failures on frag-parse to reach boundary 20
    _charge_failures(
        acct,
        root,
        "frag-parse",
        start_idx=11,
        count=10,
        model_family=c_parse["selected_model_family"],
        complexity=3,
    )
    frac_rt.dossier_store.record_dossier(
        root,
        20,
        research_channels=_three_channel_research(),
        root_cause_synthesis="frag-parse needs lexer/ast split at 20 failures",
        hypotheses=["Split frag-parse into lexer and ast"],
    )

    with pytest.raises(ValueError, match="already belongs to a lineage"):
        frac_rt.execute_fracture(
            root,
            failed_scope={
                "scope_id": "frag-parse",
                "requirement_ids": ["R1"],
                "deliverables": ["lexer.py", "ast.py"],
            },
            children=[
                {
                    "id": "frag-serial",  # duplicate!
                    "role": "implementation",
                    "complexity": 2,
                    "task_types": ["COD-TERM"],
                    "rationale": "Duplicate ID",
                    "requirement_ids": ["R1"],
                    "deliverables": ["lexer.py"],
                    "release_criteria": ["Lexer ok"],
                    "depends_on": [],
                },
                {
                    "id": "frag-ast",
                    "role": "implementation",
                    "complexity": 2,
                    "task_types": ["COD-TERM"],
                    "rationale": "AST",
                    "requirement_ids": ["R1"],
                    "deliverables": ["ast.py"],
                    "release_criteria": ["AST ok"],
                    "depends_on": [],
                },
                {
                    "id": "frag-parse-asm",
                    "role": "assembly",
                    "complexity": 7,
                    "task_types": ["COD-TERM"],
                    "rationale": "Assemble parser",
                    "requirement_ids": ["R1"],
                    "deliverables": ["lexer.py", "ast.py"],
                    "release_criteria": ["Parser ok"],
                    "depends_on": ["frag-serial", "frag-ast"],
                },
            ],
            review={
                "reviewer_model": "gpt-6-astra",
                "reviewer_tier": 7,
                "effort": "high",
                "accepted": True,
                "review_sha256": digest("rev-20-dup"),
            },
        )

    # 2. Valid boundary-20 fracture of frag-parse -> inherits 20 failures and closes frag-parse as FRACTURED_OBSOLETE
    f20 = frac_rt.execute_fracture(
        root,
        failed_scope={
            "scope_id": "frag-parse",
            "requirement_ids": ["R1"],
            "deliverables": ["lexer.py", "ast.py"],
        },
        children=[
            {
                "id": "frag-lexer",
                "role": "implementation",
                "complexity": 2,
                "task_types": ["COD-TERM"],
                "rationale": "Lexer sub-fragment",
                "requirement_ids": ["R1"],
                "deliverables": ["lexer.py"],
                "release_criteria": ["Lexer ok"],
                "depends_on": [],
            },
            {
                "id": "frag-ast",
                "role": "implementation",
                "complexity": 3,
                "task_types": ["COD-TERM"],
                "rationale": "AST sub-fragment",
                "requirement_ids": ["R1"],
                "deliverables": ["ast.py"],
                "release_criteria": ["AST ok"],
                "depends_on": [],
            },
            {
                "id": "frag-parse-asm",
                "role": "assembly",
                "complexity": 7,
                "task_types": ["COD-TERM"],
                "rationale": "Assemble parser at tier 7",
                "requirement_ids": ["R1"],
                "deliverables": ["lexer.py", "ast.py"],
                "release_criteria": ["Parser ok"],
                "depends_on": ["frag-lexer", "frag-ast"],
            },
        ],
        review={
            "reviewer_model": "gpt-6-astra",
            "reviewer_tier": 7,
            "effort": "high",
            "accepted": True,
            "review_sha256": digest("rev-20-ok"),
        },
    )
    assert f20["inherited_failures"] == 20
    assert f20["escalated_floor"] == 7
    assert frac_rt.get_fracture_child("frag-parse")["status"] == "FRACTURED_OBSOLETE"
    assert frac_rt.get_fracture_child("frag-lexer")["inherited_failures"] == 20

    # 3. Fail 9 times on frag-lexer (21..29) and fracture at 29 -> inherits 29 across restart!
    c_lexer = frac_rt.get_fracture_child("frag-lexer")
    _charge_failures(
        acct,
        root,
        "frag-lexer",
        start_idx=21,
        count=9,
        model_family=c_lexer["selected_model_family"],
        complexity=2,
    )
    reopened_acct = AttemptAccountingRuntime(db_path)
    reopened_frac = FractureRuntime(reopened_acct.ledger, catalog)

    f29 = reopened_frac.execute_fracture(
        root,
        failed_scope={
            "scope_id": "frag-lexer",
            "requirement_ids": ["R1"],
            "deliverables": ["tokens.py", "scanner.py"],
        },
        children=[
            {
                "id": "frag-tokens",
                "role": "implementation",
                "complexity": 2,
                "task_types": ["COD-TERM"],
                "rationale": "Token definitions",
                "requirement_ids": ["R1"],
                "deliverables": ["tokens.py"],
                "release_criteria": ["Tokens ok"],
                "depends_on": [],
            },
            {
                "id": "frag-scanner",
                "role": "implementation",
                "complexity": 2,
                "task_types": ["COD-TERM"],
                "rationale": "Scanner loop",
                "requirement_ids": ["R1"],
                "deliverables": ["scanner.py"],
                "release_criteria": ["Scanner ok"],
                "depends_on": [],
            },
            {
                "id": "frag-lexer-asm",
                "role": "assembly",
                "complexity": 8,
                "task_types": ["COD-TERM"],
                "rationale": "Assemble lexer at tier 8",
                "requirement_ids": ["R1"],
                "deliverables": ["tokens.py", "scanner.py"],
                "release_criteria": ["Lexer assembled"],
                "depends_on": ["frag-tokens", "frag-scanner"],
            },
        ],
        review={
            "reviewer_model": "claude-opus-5-5",
            "reviewer_tier": 8,
            "effort": "max",
            "accepted": True,
            "review_sha256": digest("rev-29-ok"),
        },
    )
    assert f29["inherited_failures"] == 29
    assert f29["escalated_floor"] == 8
    assert reopened_frac.get_fracture_child("frag-tokens")["inherited_failures"] == 29


def test_high_tier_child_approval_and_atomic_partial_fracture_recovery(tmp_path: Path) -> None:
    catalog = _load_catalog()
    db_path = tmp_path / "fracture_recovery.db"
    acct = AttemptAccountingRuntime(db_path)
    frac_rt = FractureRuntime(acct.ledger, catalog)
    root = "task-frac-recover"
    acct.ensure_lineage(root, complexity=7)

    _charge_failures(acct, root, root, start_idx=1, count=10, model_family="gpt-6.1-sol", complexity=7)
    frac_rt.dossier_store.record_dossier(
        root,
        10,
        research_channels=_three_channel_research(),
        root_cause_synthesis="Crash recovery and tier-8 approval test",
        hypotheses=["Decompose and recover atomically"],
    )

    # Inject crash after ledger fracture commit before node materialization
    with pytest.raises(RuntimeError, match="Simulated crash after ledger fracture commit"):
        frac_rt.execute_fracture(
            root,
            failed_scope={
                "scope_id": root,
                "requirement_ids": ["R1", "R2"],
                "deliverables": ["mod_a.py", "mod_b.py"],
            },
            children=[
                {
                    "id": "child-mod-a",
                    "role": "implementation",
                    "complexity": 8,  # High-tier child requires owner approval!
                    "task_types": ["COD-TERM"],
                    "rationale": "High-tier implementation fragment",
                    "requirement_ids": ["R1"],
                    "deliverables": ["mod_a.py"],
                    "release_criteria": ["mod_a verified"],
                    "depends_on": [],
                },
                {
                    "id": "child-mod-b",
                    "role": "implementation",
                    "complexity": 4,
                    "task_types": ["COD-TERM"],
                    "rationale": "Low-tier implementation fragment",
                    "requirement_ids": ["R2"],
                    "deliverables": ["mod_b.py"],
                    "release_criteria": ["mod_b verified"],
                    "depends_on": [],
                },
                {
                    "id": "child-asm-8",
                    "role": "assembly",
                    "complexity": 8,
                    "task_types": ["COD-TERM"],
                    "rationale": "Tier-8 assembly",
                    "requirement_ids": ["R1", "R2"],
                    "deliverables": ["mod_a.py", "mod_b.py"],
                    "release_criteria": ["Assembly verified"],
                    "depends_on": ["child-mod-a", "child-mod-b"],
                },
            ],
            review={
                "reviewer_model": "claude-opus-5-5",
                "reviewer_tier": 8,
                "effort": "high",
                "accepted": True,
                "review_sha256": digest("rev-crash"),
            },
            crash_after_ledger_commit_for_test=True,
        )

    # Reinstantiate FractureRuntime -> reconciles partial fracture atomically without resetting budgets!
    recovered_rt = FractureRuntime(AttemptAccountingRuntime(db_path).ledger, catalog)
    assert recovered_rt.is_scope_obsolete(root) is True
    children = {c["child_id"]: c for c in recovered_rt.list_fracture_children(root)}
    assert set(children) == {"child-mod-a", "child-mod-b", "child-asm-8"}
    assert children["child-mod-a"]["inherited_failures"] == 10
    assert children["child-mod-a"]["status"] == "HOLD_OWNER_APPROVAL"
    assert children["child-mod-b"]["status"] == "READY"
    assert children["child-asm-8"]["status"] == "HOLD_OWNER_APPROVAL"

    # Approve child-mod-a -> transitions to READY
    approved_a = recovered_rt.approve_fracture_child(root, "child-mod-a", "owner-rcpt-mod-a")
    assert approved_a["status"] == "READY"
    assert approved_a["needs_owner_approval"] is False

    # Complete child-mod-a and child-mod-b -> child-asm-8 remains in HOLD_OWNER_APPROVAL until approved!
    recovered_rt.complete_fracture_child(root, "child-mod-a", digest("art-a"))
    recovered_rt.complete_fracture_child(root, "child-mod-b", digest("art-b"))
    assert recovered_rt.get_fracture_child("child-asm-8")["status"] == "HOLD_OWNER_APPROVAL"

    # Approve child-asm-8 -> transitions to READY now that prerequisites are COMPLETED
    approved_asm = recovered_rt.approve_fracture_child(root, "child-asm-8", "owner-rcpt-asm-8")
    assert approved_asm["status"] == "READY"
