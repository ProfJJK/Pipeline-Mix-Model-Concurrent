"""Tests for Two-Staged Concurrency, Conflict-Colored Provider Batching, and Intra-Slot Agent Swarm (`P428-SWARM`)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from cochem_pipeline.inference_policy import (
    claude_swarm_arguments,
    codex_swarm_overrides,
    gemini_swarm_arguments,
)
from cochem_pipeline.microtask_board_428 import MicrotaskBoardRuntime
from cochem_pipeline.owner_approval_428 import OwnerApprovalBroker
from cochem_pipeline.planning_journal import PlanningJournal
from cochem_pipeline.resource_limits import ResourceLimits
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.store import JobStore
from cochem_pipeline.swarm_batch_428 import (
    PROVIDER_SWARM_PROFILES,
    SwarmBatchRuntime,
    extract_microtask_files,
    get_provider_swarm_profile,
    normalize_file_target,
    pack_conflict_colored_wave,
    resolve_microtask_route_tier,
)
from cochem_pipeline.task_routing import digest
from cochem_pipeline.worker import node_prompt
from cochem_pipeline.workflow_428 import (
    AttemptLedger,
    accept_microtasks,
    accept_research,
    accept_review,
    accept_srs,
    accept_wbs,
    approve_srs,
)


ROOT = Path(__file__).resolve().parents[1]
OWNER_SECRET = "owner-secret-key-with-at-least-32-chars-428"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_catalog() -> dict[str, Any]:
    return json.loads((ROOT / "docs" / "4.2.8" / "routing-candidate.json").read_text(encoding="utf-8"))


def _make_env(tmp_path: Path):
    catalog = _load_catalog()
    journal = PlanningJournal(tmp_path / "planning428.db", catalog, flash_context_limit=100000)
    store = JobStore(tmp_path / "board.db", routing_policy=load_routing_policy({"policy_version": 3}))
    broker = OwnerApprovalBroker(tmp_path / "owner428.db", owner_secret=OWNER_SECRET)
    ledger = AttemptLedger(tmp_path / "attempts428.db")
    return catalog, store, journal, broker, ledger


def _make_synthetic_node(
    mt_id: str,
    *,
    complexity: int,
    task_types: list[str],
    deliverables: list[str],
    file_targets: list[str] | None = None,
    shared_files: list[str] | None = None,
    role: str = "implementation",
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "microtask_id": mt_id,
        "id": mt_id,
        "task_id": "task428-synth",
        "lineage_kind": "WBS_CHILD",
        "attempt_lineage_id": f"task428-synth.mt.{mt_id}",
        "wbs_ids": ["wbs-1"],
        "section_ids": ["sec-1"],
        "requirement_ids": ["req-1"],
        "role": role,
        "complexity": complexity,
        "task_types": list(task_types),
        "rationale": f"Synthetic microtask {mt_id}",
        "deliverables": list(deliverables),
        "audit_metrics": ["unit test passes"],
        "release_criteria": [f"{mt_id} verified"],
        "depends_on": list(depends_on or []),
        "ancestors": list(depends_on or []),
        "prompt": f"Execute {mt_id}",
        "needs_owner_approval": False,
        "owner_approval": None,
    }
    if file_targets is not None:
        node["file_targets"] = list(file_targets)
    if shared_files is not None:
        node["shared_files"] = list(shared_files)
    return node


def _valid_microtask_output(node: dict[str, Any]) -> dict[str, Any]:
    deliverables = [
        {
            "name": d,
            "content": f"# Deliverable {d} for {node['microtask_id']}\n",
            "sha256": _sha256_text(f"# Deliverable {d} for {node['microtask_id']}\n"),
        }
        for d in node["deliverables"]
    ]
    first_deliv = deliverables[0]["name"]
    return {
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


def _advance_journal_with_custom_microtasks(
    journal: PlanningJournal,
    *,
    task_id: str,
    mt_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    journal.create(task_id, "Two-staged concurrency and conflict-colored swarm test")
    v = journal.status(task_id)["journal_version"]

    def _transition(row):
        state = json.loads(row["state_json"])
        limit = row["flash_context_limit"]
        srs_doc = {
            "plan": "Swarm batching architecture verification",
            "architecture": "Layer-2 4 OS slots x Layer-1 intra-slot subagent swarm",
            "srs": [
                {"id": "sec-1", "requirement_ids": ["req-1"], "text": "Primary module implementation"},
                {"id": "sec-2", "requirement_ids": ["req-2"], "text": "Integration and assembly"},
                {"id": "sec-3", "requirement_ids": ["req-3"], "text": "End-to-end verification"},
            ],
            "requirements": [
                {"id": "req-1", "text": "Implement core worker modules"},
                {"id": "req-2", "text": "Assemble modules cleanly"},
                {"id": "req-3", "text": "Verify end-to-end suite"},
            ],
            "assessment": {
                "complexity": 8,
                "task_types": ["COD-TERM", "AGT-PROJ"],
                "rationale": "Multi-agent swarm execution test",
            },
            "release_criteria": ["All requirements verified"],
            "srs_tokens": 400,
            "evidence_and_instruction_tokens": 400,
            "output_reserve_tokens": 400,
        }
        state = accept_srs(state, srs_doc, planner_model="gpt-6.1-sol", flash_context_limit=limit)
        state["planner_profile"] = "gpt-6.1-sol-high"
        state = approve_srs(state, state["srs_sha256"], "owner-rcpt-swarm")
        res_channels = {
            kind: {
                "query": "Conflict-colored provider batching",
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
            review_sha256=digest("review-swarm-ok"),
        )
        all_delivs = sorted({d for m in mt_rows for d in m["deliverables"]})
        impl_delivs = [d for d in all_delivs if d not in ("assembly.py", "final_test.py")]
        wbs_rows = [
            {
                "id": "wbs-impl",
                "section_ids": ["sec-1"],
                "requirement_ids": ["req-1"],
                "deliverables": impl_delivs or ["module_1.py"],
                "audit_metrics": ["unit test passes"],
                "release_criteria": ["req-1 proven"],
                "depends_on": [],
            },
            {
                "id": "wbs-asm",
                "section_ids": ["sec-2"],
                "requirement_ids": ["req-2"],
                "deliverables": ["assembly.py"],
                "audit_metrics": ["clean imports"],
                "release_criteria": ["req-2 proven"],
                "depends_on": ["wbs-impl"],
            },
            {
                "id": "wbs-test",
                "section_ids": ["sec-3"],
                "requirement_ids": ["req-3"],
                "deliverables": ["final_test.py"],
                "audit_metrics": ["100% coverage"],
                "release_criteria": ["req-3 proven"],
                "depends_on": ["wbs-impl", "wbs-asm"],
            },
        ]
        state = accept_wbs(state, wbs_rows)
        state = accept_microtasks(state, mt_rows)
        assessments = [
            {
                "id": m["id"],
                "complexity": m["complexity"],
                "task_types": m["task_types"],
                "rationale": f"Reassessed {m['id']}",
            }
            for m in mt_rows
        ]
        return PlanningJournal._accept_micro_assessments(state, {"assessments": assessments})

    journal._transition(task_id, v, f"test.swarm_ready.{task_id}", {}, _transition)
    return journal.status(task_id)


def test_case_b_disjoint_files_provider_packing_and_overflow() -> None:
    """Case B: Disjoint files pack by provider family (20 Claude/d3, 20 Codex/d2, 64 Agy/d2) with overflow and exact per-subagent route tiers."""
    catalog = _load_catalog()

    assert PROVIDER_SWARM_PROFILES["claude"]["max_agents_per_slot"] == 20
    assert PROVIDER_SWARM_PROFILES["claude"]["max_nesting_depth"] == 3
    assert PROVIDER_SWARM_PROFILES["codex"]["max_agents_per_slot"] == 20
    assert PROVIDER_SWARM_PROFILES["codex"]["max_nesting_depth"] == 2
    assert PROVIDER_SWARM_PROFILES["gemini"]["max_agents_per_slot"] == 64
    assert PROVIDER_SWARM_PROFILES["gemini"]["max_nesting_depth"] == 2
    assert get_provider_swarm_profile("agy")["provider"] == "gemini"

    # Discover task_types + complexity combinations in catalog that route to Claude, Codex, and Gemini/Agy
    # - ["AGT-PROJ"] at complexity 3 routes primary to haiku-med (claude), complexity 5 -> haiku-max (claude), complexity 8 -> sonnet-max (claude)
    # - ["COD-TERM"] at complexity 3 routes primary to sol-low (codex), complexity 4 -> sol-med (codex)
    # - ["AGT-AUTO"] at complexity 8 routes primary to argon-high (gemini), or explicit routed_profile_id="flash38-low" -> flash38-low (gemini)
    claude_tier_3 = resolve_microtask_route_tier(
        _make_synthetic_node("c-probe-3", complexity=3, task_types=["AGT-PROJ"], deliverables=["c3.py"]),
        catalog,
    )
    claude_tier_5 = resolve_microtask_route_tier(
        _make_synthetic_node("c-probe-5", complexity=5, task_types=["AGT-PROJ"], deliverables=["c5.py"]),
        catalog,
    )
    codex_tier_3 = resolve_microtask_route_tier(
        _make_synthetic_node("x-probe-3", complexity=3, task_types=["COD-TERM"], deliverables=["x3.py"]),
        catalog,
    )
    codex_tier_4 = resolve_microtask_route_tier(
        _make_synthetic_node("x-probe-4", complexity=4, task_types=["COD-TERM"], deliverables=["x4.py"]),
        catalog,
    )
    agy_tier_8 = resolve_microtask_route_tier(
        _make_synthetic_node("g-probe-8", complexity=8, task_types=["AGT-AUTO"], deliverables=["g8.py"]),
        catalog,
    )
    agy_tier_flash = resolve_microtask_route_tier(
        {
            **_make_synthetic_node("g-probe-1", complexity=1, task_types=["AGT-AUTO"], deliverables=["g1.py"]),
            "routed_profile_id": "flash38-low",
        },
        catalog,
    )

    assert claude_tier_3["provider_family"] == "claude"
    assert claude_tier_5["provider_family"] == "claude"
    assert claude_tier_3["routed_profile_id"] != claude_tier_5["routed_profile_id"]
    assert codex_tier_3["provider_family"] == "codex"
    assert codex_tier_4["provider_family"] == "codex"
    assert codex_tier_3["routed_profile_id"] != codex_tier_4["routed_profile_id"]
    assert agy_tier_8["provider_family"] == "gemini"
    assert agy_tier_flash["provider_family"] == "gemini"
    assert agy_tier_8["routed_profile_id"] != agy_tier_flash["routed_profile_id"]

    # 1. Exact single-slot capacity test: 20 Claude + 20 Codex + 64 Agy (104 disjoint microtasks)
    exact_nodes: list[dict[str, Any]] = []
    for i in range(1, 21):
        exact_nodes.append(
            _make_synthetic_node(
                f"claude-mt-{i:02d}",
                complexity=3 if i % 2 == 1 else 5,
                task_types=["AGT-PROJ"],
                deliverables=[f"src/claude_mod_{i:02d}.py"],
            )
        )
    for i in range(1, 21):
        exact_nodes.append(
            _make_synthetic_node(
                f"codex-mt-{i:02d}",
                complexity=3 if i % 2 == 1 else 4,
                task_types=["COD-TERM"],
                deliverables=[f"src/codex_mod_{i:02d}.py"],
            )
        )
    for i in range(1, 65):
        node_g = _make_synthetic_node(
            f"agy-mt-{i:02d}",
            complexity=8 if i % 2 == 1 else 1,
            task_types=["AGT-AUTO"],
            deliverables=[f"src/agy_mod_{i:02d}.py"],
        )
        if i % 2 == 0:
            node_g["routed_profile_id"] = "flash38-low"
        exact_nodes.append(node_g)

    wave = pack_conflict_colored_wave(exact_nodes, catalog, task_id="task428-case-b")
    assert len(wave["waiting_on_lock_nodes"]) == 0
    assert len(wave["admitted_nodes"]) == 104
    assert len(wave["batches"]) == 3

    batches_by_prov = {b["provider_family"]: b for b in wave["batches"]}
    assert len(batches_by_prov["claude"]["microtask_ids"]) == 20
    assert batches_by_prov["claude"]["max_agents_per_slot"] == 20
    assert batches_by_prov["claude"]["max_nesting_depth"] == 3

    assert len(batches_by_prov["codex"]["microtask_ids"]) == 20
    assert batches_by_prov["codex"]["max_agents_per_slot"] == 20
    assert batches_by_prov["codex"]["max_nesting_depth"] == 2

    assert len(batches_by_prov["gemini"]["microtask_ids"]) == 64
    assert batches_by_prov["gemini"]["max_agents_per_slot"] == 64
    assert batches_by_prov["gemini"]["max_nesting_depth"] == 2

    # Verify each subagent inside a mixed-tier provider batch preserves its own routed (model, reasoning_effort)
    claude_subagents = batches_by_prov["claude"]["subagents"]
    assert claude_subagents[0]["routed_profile_id"] == claude_tier_3["routed_profile_id"]
    assert claude_subagents[0]["model"] == claude_tier_3["model"]
    assert claude_subagents[0]["reasoning_effort"] == claude_tier_3["reasoning_effort"]
    assert claude_subagents[1]["routed_profile_id"] == claude_tier_5["routed_profile_id"]
    assert claude_subagents[1]["model"] == claude_tier_5["model"]
    assert claude_subagents[1]["reasoning_effort"] == claude_tier_5["reasoning_effort"]

    # 2. Overflow test: 25 Claude + 23 Codex + 70 Agy -> 2 Claude batches (20+5), 2 Codex batches (20+3), 2 Agy batches (64+6)
    overflow_nodes: list[dict[str, Any]] = []
    for i in range(1, 26):
        overflow_nodes.append(
            _make_synthetic_node(
                f"ov-claude-{i:02d}",
                complexity=3,
                task_types=["AGT-PROJ"],
                deliverables=[f"src/ov_claude_{i:02d}.py"],
            )
        )
    for i in range(1, 24):
        overflow_nodes.append(
            _make_synthetic_node(
                f"ov-codex-{i:02d}",
                complexity=4,
                task_types=["COD-TERM"],
                deliverables=[f"src/ov_codex_{i:02d}.py"],
            )
        )
    for i in range(1, 71):
        overflow_nodes.append(
            _make_synthetic_node(
                f"ov-agy-{i:02d}",
                complexity=8,
                task_types=["AGT-AUTO"],
                deliverables=[f"src/ov_agy_{i:02d}.py"],
            )
        )

    ov_wave = pack_conflict_colored_wave(overflow_nodes, catalog, task_id="task428-overflow")
    assert len(ov_wave["batches"]) == 6
    claude_batches = [b for b in ov_wave["batches"] if b["provider_family"] == "claude"]
    codex_batches = [b for b in ov_wave["batches"] if b["provider_family"] == "codex"]
    agy_batches = [b for b in ov_wave["batches"] if b["provider_family"] == "gemini"]
    assert [len(b["microtask_ids"]) for b in claude_batches] == [20, 5]
    assert [len(b["microtask_ids"]) for b in codex_batches] == [20, 3]
    assert [len(b["microtask_ids"]) for b in agy_batches] == [64, 6]


def test_case_c_shared_file_lock_across_slots_and_promotion(tmp_path: Path) -> None:
    """Case C: 5 ready microtasks touching shared_solver.py admit only 1 representative and hold 4 in WAITING_ON_FILE_LOCK."""
    catalog, store, journal, broker, ledger = _make_env(tmp_path)

    # Create 5 independent implementation microtasks that all touch src/cochem_pipeline/shared_solver.py
    # across different providers (Codex, Claude, Gemini)
    mt_rows: list[dict[str, Any]] = [
        {
            "id": "mt-shared-1",
            "wbs_ids": ["wbs-impl"],
            "role": "implementation",
            "complexity": 4,
            "task_types": ["COD-TERM"],
            "deliverables": ["mod_s1.py"],
            "shared_files": ["src/cochem_pipeline/shared_solver.py"],
            "audit_metrics": ["unit test passes"],
            "release_criteria": ["mt-shared-1 verified"],
            "depends_on": [],
            "prompt": "Update shared_solver.py part 1",
        },
        {
            "id": "mt-shared-2",
            "wbs_ids": ["wbs-impl"],
            "role": "implementation",
            "complexity": 5,
            "task_types": ["AGT-PROJ"],
            "deliverables": ["mod_s2.py"],
            "file_targets": ["./src//cochem_pipeline\\shared_solver.py"],
            "audit_metrics": ["unit test passes"],
            "release_criteria": ["mt-shared-2 verified"],
            "depends_on": [],
            "prompt": "Update shared_solver.py part 2",
        },
        {
            "id": "mt-shared-3",
            "wbs_ids": ["wbs-impl"],
            "role": "implementation",
            "complexity": 1,
            "task_types": ["GEN-DEFAULT"],
            "deliverables": ["mod_s3.py"],
            "shared_files": ["src/cochem_pipeline/shared_solver.py"],
            "audit_metrics": ["unit test passes"],
            "release_criteria": ["mt-shared-3 verified"],
            "depends_on": [],
            "prompt": "Update shared_solver.py part 3",
        },
        {
            "id": "mt-shared-4",
            "wbs_ids": ["wbs-impl"],
            "role": "implementation",
            "complexity": 6,
            "task_types": ["COD-TERM"],
            "deliverables": ["mod_s4.py"],
            "shared_files": ["src/cochem_pipeline/shared_solver.py"],
            "audit_metrics": ["unit test passes"],
            "release_criteria": ["mt-shared-4 verified"],
            "depends_on": [],
            "prompt": "Update shared_solver.py part 4",
        },
        {
            "id": "mt-shared-5",
            "wbs_ids": ["wbs-impl"],
            "role": "implementation",
            "complexity": 3,
            "task_types": ["GEN-DEFAULT"],
            "deliverables": ["mod_s5.py"],
            "shared_files": ["src/cochem_pipeline/shared_solver.py"],
            "audit_metrics": ["unit test passes"],
            "release_criteria": ["mt-shared-5 verified"],
            "depends_on": [],
            "prompt": "Update shared_solver.py part 5",
        },
        {
            "id": "mt-asm",
            "wbs_ids": ["wbs-asm"],
            "role": "assembly",
            "complexity": 5,
            "task_types": ["AGT-PROJ"],
            "deliverables": ["assembly.py"],
            "audit_metrics": ["clean imports"],
            "release_criteria": ["assembly verified"],
            "depends_on": ["mt-shared-1", "mt-shared-2", "mt-shared-3", "mt-shared-4", "mt-shared-5"],
            "prompt": "Assemble shared solver",
        },
        {
            "id": "mt-test",
            "wbs_ids": ["wbs-test"],
            "role": "final_test",
            "complexity": 5,
            "task_types": ["COD-SCI"],
            "deliverables": ["final_test.py"],
            "audit_metrics": ["100% coverage"],
            "release_criteria": ["final test verified"],
            "depends_on": [
                "mt-shared-1",
                "mt-shared-2",
                "mt-shared-3",
                "mt-shared-4",
                "mt-shared-5",
                "mt-asm",
            ],
            "prompt": "Verify shared solver",
        },
    ]
    _advance_journal_with_custom_microtasks(journal, task_id="task428-case-c", mt_rows=mt_rows)

    runtime = SwarmBatchRuntime(journal, store, owner_broker=broker, attempt_ledger=ledger)
    snap1 = runtime.dispatch_batches("task428-case-c")
    by_id1 = {n["microtask_id"]: n for n in snap1["nodes"]}

    # Only mt-shared-1 is admitted; mt-shared-2..5 are held in WAITING_ON_FILE_LOCK with job_id=None
    assert by_id1["mt-shared-1"]["status"] == "DISPATCHED"
    assert by_id1["mt-shared-1"]["job_id"] is not None
    for idx in range(2, 6):
        held = by_id1[f"mt-shared-{idx}"]
        assert held["status"] == "WAITING_ON_FILE_LOCK"
        assert held["job_id"] is None
        assert "src/cochem_pipeline/shared_solver.py" in held["blocking_files"]
        assert held["blocking_microtask_ids"] == ["mt-shared-1"]

    # Verify durable file lock in microtask428_file_locks
    locks1 = runtime.active_file_locks("task428-case-c")
    locked_paths1 = {row["file_path"]: row["microtask_id"] for row in locks1}
    assert locked_paths1["src/cochem_pipeline/shared_solver.py"] == "mt-shared-1"
    assert locked_paths1["mod_s1.py"] == "mt-shared-1"

    # Complete mt-shared-1's batch -> lock on shared_solver.py is released and mt-shared-2 is promoted to DISPATCHED
    batch1_id = by_id1["mt-shared-1"]["batch_id"]
    assert batch1_id is not None
    snap2 = runtime.complete_batch(
        "task428-case-c",
        batch1_id,
        {"mt-shared-1": _valid_microtask_output(by_id1["mt-shared-1"])},
    )
    by_id2 = {n["microtask_id"]: n for n in snap2["nodes"]}
    assert by_id2["mt-shared-1"]["status"] == "COMPLETED"
    assert by_id2["mt-shared-2"]["status"] == "DISPATCHED"
    assert by_id2["mt-shared-2"]["job_id"] is not None
    for idx in range(3, 6):
        assert by_id2[f"mt-shared-{idx}"]["status"] == "WAITING_ON_FILE_LOCK"
        assert by_id2[f"mt-shared-{idx}"]["job_id"] is None

    locks2 = runtime.active_file_locks("task428-case-c")
    locked_paths2 = {row["file_path"]: row["microtask_id"] for row in locks2}
    assert locked_paths2["src/cochem_pipeline/shared_solver.py"] == "mt-shared-2"
    assert "mod_s1.py" not in locked_paths2


def test_per_slot_resource_limits_and_swarm_cli_policies() -> None:
    """Verify Per-Slot OS Job Object Resource Envelope (6 GiB RAM, 4096 MiB V8 heap, 96 processes) and CLI swarm policies."""
    # Default ResourceLimits remains unchanged for legacy non-swarm tests
    default_limits = ResourceLimits()
    assert default_limits.memory_limit_mb == 2048
    assert default_limits.node_heap_mb == 512
    assert default_limits.max_processes == 16
    assert default_limits.swarm_mode is False
    assert "swarm_mode" not in default_limits.as_dict()

    # Swarm default enforces the 4-slot x intra-slot swarm envelope (4 x 6 GiB = 24 GiB <= 63.7 GiB host RAM)
    swarm_limits = ResourceLimits.swarm_default()
    assert swarm_limits.memory_limit_mb == 6144
    assert swarm_limits.node_heap_mb == 4096
    assert swarm_limits.max_processes == 96
    assert swarm_limits.swarm_mode is True
    assert swarm_limits.creation_flags == 0x08000200
    assert swarm_limits.node_options == "--max-old-space-size=4096"
    assert swarm_limits.as_dict()["swarm_mode"] is True

    # Layer-1 Swarm CLI / Config helpers
    claude_args = claude_swarm_arguments(max_agents=20, max_nesting_depth=3)
    assert "--tools" in claude_args and "Task" in claude_args
    assert "--strict-mcp-config" in claude_args
    assert '"maxSubagents":20' in claude_args[-1]
    assert '"maxNestingDepth":3' in claude_args[-1]
    assert '"nodeHeapMb":4096' in claude_args[-1]
    with pytest.raises(ValueError, match="max_agents"):
        claude_swarm_arguments(max_agents=21)
    with pytest.raises(ValueError, match="max_nesting_depth"):
        claude_swarm_arguments(max_nesting_depth=4)

    codex_args = codex_swarm_overrides(["brightdata"], max_agents=20, max_nesting_depth=2)
    assert "features.multi_agent=true" in codex_args
    assert "agents.enabled=true" in codex_args
    assert "agents.max_concurrency=20" in codex_args
    assert "agents.max_depth=2" in codex_args
    assert 'mcp_servers={"brightdata"={enabled=false}}' in codex_args
    with pytest.raises(ValueError, match="max_agents"):
        codex_swarm_overrides(max_agents=25)
    with pytest.raises(ValueError, match="max_nesting_depth"):
        codex_swarm_overrides(max_nesting_depth=3)

    agy_spec = {
        "inference_only": {
            "arguments": ["--non-interactive"],
            "version_arguments": ["--version"],
            "executable_sha256": "a" * 64,
            "version": "1.0.0",
            "capability_reference": "agy-swarm-v1",
            "disables_tools": True,
            "disables_mcp": True,
            "disables_hooks": True,
            "disables_subagents": True,
            "disables_model_fallback": True,
        }
    }
    gemini_args = gemini_swarm_arguments(agy_spec, max_agents=64, max_nesting_depth=2)
    assert gemini_args == [
        "--non-interactive",
        "--subagents",
        "enabled",
        "--max-subagents",
        "64",
        "--max-subagent-depth",
        "2",
    ]
    with pytest.raises(ValueError, match="max_agents"):
        gemini_swarm_arguments(agy_spec, max_agents=65)
    with pytest.raises(ValueError, match="max_nesting_depth"):
        gemini_swarm_arguments(agy_spec, max_nesting_depth=3)


def test_partial_batch_commit_and_attempt_ledger_failure_isolation(tmp_path: Path) -> None:
    """A slot batch of 4 microtasks where 3 succeed and 1 fails commits the 3 valid tasks and isolates failure to the 1 failed task."""
    catalog, store, journal, broker, ledger = _make_env(tmp_path)

    mt_rows: list[dict[str, Any]] = [
        {
            "id": f"mt-b-{i}",
            "wbs_ids": ["wbs-impl"],
            "role": "implementation",
            "complexity": 4,
            "task_types": ["COD-TERM"],
            "deliverables": [f"mod_b_{i}.py"],
            "audit_metrics": ["unit test passes"],
            "release_criteria": [f"mt-b-{i} verified"],
            "depends_on": [],
            "prompt": f"Implement mod_b_{i}.py",
        }
        for i in range(1, 5)
    ] + [
        {
            "id": "mt-downstream-123",
            "wbs_ids": ["wbs-impl"],
            "role": "implementation",
            "complexity": 4,
            "task_types": ["COD-TERM"],
            "deliverables": ["mod_downstream_123.py"],
            "audit_metrics": ["unit test passes"],
            "release_criteria": ["mt-downstream-123 verified"],
            "depends_on": ["mt-b-1", "mt-b-2", "mt-b-3"],
            "prompt": "Implement downstream module depending only on mt-b-1..3",
        },
        {
            "id": "mt-asm",
            "wbs_ids": ["wbs-asm"],
            "role": "assembly",
            "complexity": 5,
            "task_types": ["AGT-PROJ"],
            "deliverables": ["assembly.py"],
            "audit_metrics": ["clean imports"],
            "release_criteria": ["assembly verified"],
            "depends_on": ["mt-b-1", "mt-b-2", "mt-b-3", "mt-b-4", "mt-downstream-123"],
            "prompt": "Assemble all modules",
        },
        {
            "id": "mt-test",
            "wbs_ids": ["wbs-test"],
            "role": "final_test",
            "complexity": 5,
            "task_types": ["COD-SCI"],
            "deliverables": ["final_test.py"],
            "audit_metrics": ["100% coverage"],
            "release_criteria": ["final test verified"],
            "depends_on": ["mt-b-1", "mt-b-2", "mt-b-3", "mt-b-4", "mt-downstream-123", "mt-asm"],
            "prompt": "Verify assembled modules",
        },
    ]
    _advance_journal_with_custom_microtasks(journal, task_id="task428-partial", mt_rows=mt_rows)

    runtime = SwarmBatchRuntime(journal, store, owner_broker=broker, attempt_ledger=ledger)
    snap1 = runtime.dispatch_batches("task428-partial")
    by_id1 = {n["microtask_id"]: n for n in snap1["nodes"]}

    # All 4 ready Codex microtasks (mt-b-1..4) are packed into 1 Codex slot batch
    dispatched_batches = [b for b in snap1["batches"] if b["status"] == "DISPATCHED"]
    assert len(dispatched_batches) == 1
    batch = dispatched_batches[0]
    assert batch["provider_family"] == "codex"
    assert batch["microtask_ids"] == ["mt-b-1", "mt-b-2", "mt-b-3", "mt-b-4"]
    assert by_id1["mt-downstream-123"]["status"] == "WAITING_ON_DEPENDENCIES"

    # Verify worker prompt for the MICROTASK_SWARM_BATCH board job contains intra-slot swarm delegation instructions
    with store._connection() as conn:
        batch_job = store._get(conn, batch["job_id"])
    prompt_text = node_prompt(batch_job)
    assert "STAGE: MICROTASK_SWARM_BATCH" in prompt_text
    assert "max_agents_per_slot=20" in prompt_text
    assert "max_nesting_depth=2" in prompt_text
    assert "subagent_outputs" in prompt_text

    # Submit batch output where mt-b-1, mt-b-2, mt-b-3 succeed and mt-b-4 fails validation (corrupted sha256)
    bad_mt4_out = _valid_microtask_output(by_id1["mt-b-4"])
    bad_mt4_out["deliverables"][0]["sha256"] = "0" * 64

    snap2 = runtime.complete_batch(
        "task428-partial",
        batch["batch_id"],
        {
            "mt-b-1": _valid_microtask_output(by_id1["mt-b-1"]),
            "mt-b-2": _valid_microtask_output(by_id1["mt-b-2"]),
            "mt-b-3": _valid_microtask_output(by_id1["mt-b-3"]),
            "mt-b-4": bad_mt4_out,
        },
    )
    by_id2 = {n["microtask_id"]: n for n in snap2["nodes"]}

    # 1. The 3 valid microtasks committed to COMPLETED immediately
    assert by_id2["mt-b-1"]["status"] == "COMPLETED"
    assert by_id2["mt-b-2"]["status"] == "COMPLETED"
    assert by_id2["mt-b-3"]["status"] == "COMPLETED"

    # 2. Their downstream dependent (mt-downstream-123) is immediately unlocked and DISPATCHED!
    assert by_id2["mt-downstream-123"]["status"] == "DISPATCHED"

    # 3. Only mt-b-4 transitioned to PENDING_RETRY and recorded 1 quality failure in AttemptLedger
    assert by_id2["mt-b-4"]["status"] == "PENDING_RETRY"
    assert by_id2["mt-b-4"]["job_id"] is None
    assert snap2["last_completed_batch"]["status"] == "PARTIAL_COMPLETED"
    assert snap2["last_completed_batch"]["completed_microtask_ids"] == ["mt-b-1", "mt-b-2", "mt-b-3"]
    assert snap2["last_completed_batch"]["failed_microtask_ids"] == ["mt-b-4"]

    for ok_id in ("mt-b-1", "mt-b-2", "mt-b-3"):
        lstate_ok = ledger.status(f"task428-partial.mt.{ok_id}")
        assert lstate_ok["failures"] == 0
    lstate_fail = ledger.status("task428-partial.mt.mt-b-4")
    assert lstate_fail["failures"] == 1
    assert lstate_fail["stage"] == "READY"

    # 4. File locks for mt-b-1..4 were all released; only mt-downstream-123 holds its lock now
    active_locks = {r["file_path"]: r["microtask_id"] for r in runtime.active_file_locks("task428-partial")}
    assert active_locks == {"mod_downstream_123.py": "mt-downstream-123"}

    # 5. Next dispatch wave re-dispatches mt-b-4 alongside mt-downstream-123 without touching mt-b-1..3
    snap3 = runtime.dispatch_batches("task428-partial")
    by_id3 = {n["microtask_id"]: n for n in snap3["nodes"]}
    assert by_id3["mt-b-1"]["status"] == "COMPLETED"
    assert by_id3["mt-b-2"]["status"] == "COMPLETED"
    assert by_id3["mt-b-3"]["status"] == "COMPLETED"
    assert by_id3["mt-b-4"]["status"] == "DISPATCHED"
    assert by_id3["mt-downstream-123"]["status"] == "DISPATCHED"


def test_file_target_normalization_and_traversal_rejection() -> None:
    assert normalize_file_target("./src\\cochem_pipeline//worker.py") == "src/cochem_pipeline/worker.py"
    with pytest.raises(ValueError, match="Invalid microtask file target"):
        normalize_file_target("../outside/secret.py")
    with pytest.raises(ValueError, match="Invalid microtask file target"):
        normalize_file_target("src/../../secret.py")
    node = _make_synthetic_node(
        "mt-norm",
        complexity=3,
        task_types=["COD-TERM"],
        deliverables=["./a\\b.py"],
        file_targets=["a/b.py", "c/d.py"],
    )
    assert extract_microtask_files(node) == ["a/b.py", "c/d.py"]


def test_cross_task_file_lock_and_10_failure_pivot_hold(tmp_path: Path) -> None:
    """Verify cross-task file locking across two root tasks and HELD transition on the 10th quality failure."""
    catalog, store, journal, broker, ledger = _make_env(tmp_path)

    mt_rows_a = [
        {
            "id": "mt-a1",
            "wbs_ids": ["wbs-impl"],
            "role": "implementation",
            "complexity": 4,
            "task_types": ["COD-TERM"],
            "deliverables": ["mod_a1.py"],
            "shared_files": ["src/cochem_pipeline/cross_task_shared.py"],
            "audit_metrics": ["unit test passes"],
            "release_criteria": ["mt-a1 verified"],
            "depends_on": [],
            "prompt": "Task A implementation touching cross_task_shared.py",
        },
        {
            "id": "mt-asm",
            "wbs_ids": ["wbs-asm"],
            "role": "assembly",
            "complexity": 5,
            "task_types": ["AGT-PROJ"],
            "deliverables": ["assembly.py"],
            "audit_metrics": ["clean imports"],
            "release_criteria": ["assembly verified"],
            "depends_on": ["mt-a1"],
            "prompt": "Assemble Task A",
        },
        {
            "id": "mt-test",
            "wbs_ids": ["wbs-test"],
            "role": "final_test",
            "complexity": 5,
            "task_types": ["COD-SCI"],
            "deliverables": ["final_test.py"],
            "audit_metrics": ["100% coverage"],
            "release_criteria": ["final test verified"],
            "depends_on": ["mt-a1", "mt-asm"],
            "prompt": "Verify Task A",
        },
    ]
    mt_rows_b = [
        {
            "id": "mt-b1",
            "wbs_ids": ["wbs-impl"],
            "role": "implementation",
            "complexity": 4,
            "task_types": ["COD-TERM"],
            "deliverables": ["mod_b1.py"],
            "shared_files": ["src/cochem_pipeline/cross_task_shared.py"],
            "audit_metrics": ["unit test passes"],
            "release_criteria": ["mt-b1 verified"],
            "depends_on": [],
            "prompt": "Task B implementation touching cross_task_shared.py",
        },
        {
            "id": "mt-asm",
            "wbs_ids": ["wbs-asm"],
            "role": "assembly",
            "complexity": 5,
            "task_types": ["AGT-PROJ"],
            "deliverables": ["assembly.py"],
            "audit_metrics": ["clean imports"],
            "release_criteria": ["assembly verified"],
            "depends_on": ["mt-b1"],
            "prompt": "Assemble Task B",
        },
        {
            "id": "mt-test",
            "wbs_ids": ["wbs-test"],
            "role": "final_test",
            "complexity": 5,
            "task_types": ["COD-SCI"],
            "deliverables": ["final_test.py"],
            "audit_metrics": ["100% coverage"],
            "release_criteria": ["final test verified"],
            "depends_on": ["mt-b1", "mt-asm"],
            "prompt": "Verify Task B",
        },
    ]

    _advance_journal_with_custom_microtasks(journal, task_id="task428-lock-a", mt_rows=mt_rows_a)
    _advance_journal_with_custom_microtasks(journal, task_id="task428-lock-b", mt_rows=mt_rows_b)

    runtime = SwarmBatchRuntime(journal, store, owner_broker=broker, attempt_ledger=ledger)
    snap_a = runtime.dispatch_batches("task428-lock-a")
    node_a1 = {n["microtask_id"]: n for n in snap_a["nodes"]}["mt-a1"]
    assert node_a1["status"] == "DISPATCHED"

    # Task B tries to dispatch mt-b1 touching the same file -> held in WAITING_ON_FILE_LOCK
    snap_b = runtime.dispatch_batches("task428-lock-b")
    node_b1 = {n["microtask_id"]: n for n in snap_b["nodes"]}["mt-b1"]
    assert node_b1["status"] == "WAITING_ON_FILE_LOCK"
    assert node_b1["job_id"] is None
    assert "src/cochem_pipeline/cross_task_shared.py" in node_b1["blocking_files"]

    # Pre-charge 9 quality failures on Task A's mt-a1 lineage, then fail the 10th attempt via complete_batch
    lineage_a1 = "task428-lock-a.mt.mt-a1"
    for i in range(9):
        lease = ledger.start(lineage_a1, lineage_a1, "gpt-6.1-sol")
        ledger.finish(lease, "quality_failure", digest(f"pre-fail-{i}"))
    assert ledger.status(lineage_a1)["failures"] == 9

    bad_out = _valid_microtask_output(node_a1)
    bad_out["deliverables"][0]["sha256"] = "f" * 64
    snap_a_fail10 = runtime.complete_batch(
        "task428-lock-a",
        node_a1["batch_id"],
        {"mt-a1": bad_out},
    )
    node_a1_after = {n["microtask_id"]: n for n in snap_a_fail10["nodes"]}["mt-a1"]
    assert node_a1_after["status"] == "HELD"
    assert ledger.status(lineage_a1)["failures"] == 10
    assert ledger.status(lineage_a1)["stage"] == "PIVOT_RESEARCH"

    # Because mt-a1 released its file lock when transitioning to HELD, Task B's mt-b1 can now be dispatched!
    snap_b2 = runtime.dispatch_batches("task428-lock-b")
    node_b1_after = {n["microtask_id"]: n for n in snap_b2["nodes"]}["mt-b1"]
    assert node_b1_after["status"] == "DISPATCHED"
    assert node_b1_after["job_id"] is not None

