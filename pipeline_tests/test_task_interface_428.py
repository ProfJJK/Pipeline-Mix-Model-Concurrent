"""Tests for 4.2.8 user-facing intake, approval, and progress interfaces (`P428-10`)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import MethodType

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from cochem_pipeline.owner_approval_428 import OwnerApprovalBroker
from cochem_pipeline.owner_ui_428 import OwnerReviewUI
from cochem_pipeline.planning_journal import PlanningJournal
from cochem_pipeline.planning_runtime import PlanningController
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.runtime import Runtime
from cochem_pipeline.server import create_server
from cochem_pipeline.store import JobStore
from pipeline_tests.test_planning_gateway_428 import accepted_receipt
from pipeline_tests.test_service import endpoint, request
from pipeline_tests.test_workflow_428 import document


ROOT = Path(__file__).resolve().parents[1]
OWNER_SECRET = "owner-dedicated-secret-428-9f8e7d6c5b4a3210-high-entropy"


@pytest.fixture
def task_endpoint(endpoint, tmp_path: Path):
    """Connect 4.2.8 PlanningController and OwnerApprovalBroker to the loopback HTTP endpoint."""
    catalog = json.loads((ROOT / "docs" / "4.2.8" / "routing-candidate.json").read_text(encoding="utf-8"))
    store = JobStore(tmp_path / "jobs428.db", routing_policy=load_routing_policy({"policy_version": 3}))
    broker = OwnerApprovalBroker(
        tmp_path / "owner_broker.db",
        owner_secret=OWNER_SECRET,
        shared_agent_tokens={endpoint.token},
    )
    journal = PlanningJournal(
        tmp_path / "planning428.db",
        catalog,
        owner_receipt=broker.load_for_journal,
        flash_context_limit=100000,
    )
    clock = [100.0]
    planner = PlanningController(journal, store, clock=lambda: clock[0])
    planner.test_clock = clock

    controller = endpoint.controller
    # Record one legacy workflow in controller.store before enabling 4.2.8 task_planning
    controller.store.submit("Legacy six-chapter workflow", ["REQ-LEG-1"], 2, "legacy-wf-01")
    controller.config.coding_projects = {"registered-proj": {"repository": "private"}}
    controller.task_planning = planner
    controller.owner_approval_broker = broker
    controller.submit_task = MethodType(Runtime.submit_task, controller)
    controller.task_status = MethodType(Runtime.task_status, controller)
    try:
        yield endpoint
    finally:
        store.close()


def _advance_srs(planner: PlanningController, task_id: str, complexity: int = 9):
    planner.test_clock[0] += 2
    planner.step()
    job = planner.store.claim("inert-worker", worker_slot="slot1", allowed_kinds=["TASK_PLAN"], requires_cleanup=True)
    assert job is not None
    out = document(complexity)
    planner.store.clear_execution_quarantine(job["job_id"], job["attempt_id"], job["fencing_token"])
    planner.store.complete(job["job_id"], job["attempt_id"], job["fencing_token"], out, accepted_receipt(job, out))
    planner.test_clock[0] += 2
    planner.step()
    return job


def test_mcp_submit_routes_to_428_planner_and_retains_legacy_workflow_status(task_endpoint):
    async def scenario():
        async with create_connected_server_and_client_session(create_server(task_endpoint.client)) as client:
            # 1. Legacy workflow status remains accessible through pipeline_status
            legacy_res = await client.call_tool("pipeline_status", {"workflow_id": "legacy-wf-01"})
            assert not legacy_res.isError
            assert legacy_res.structuredContent["workflow_id"] == "legacy-wf-01"
            assert {j["kind"] for j in legacy_res.structuredContent["jobs"]} == {
                "MACRO_PLANNING_REQUEST",
                "MANIFEST_GENERATOR",
                "SYNTHESIS",
            }

            # 2. Normal pipeline_submit does NOT bypass the 4.2.8 planner
            sub_res = await client.call_tool(
                "pipeline_submit",
                {
                    "objective": "Design and verify tier-9 distributed state machine",
                    "task_id": "task-mcp-01",
                    "project_id": "registered-proj",
                },
            )
            assert not sub_res.isError
            view = sub_res.structuredContent
            assert view["task_id"] == "task-mcp-01"
            assert view["workflow_id"] == "task-mcp-01"
            assert view["task"]["stage"] == "SRS"
            assert view["task"]["project_id"] == "registered-proj"
            assert view["status"] == "IN_PROGRESS"

            # 3. Idempotent duplicate submit returns the same task; conflicting objective fails
            dup_res = await client.call_tool(
                "pipeline_submit",
                {
                    "objective": "Design and verify tier-9 distributed state machine",
                    "task_id": "task-mcp-01",
                    "project_id": "registered-proj",
                },
            )
            assert not dup_res.isError
            assert dup_res.structuredContent["task_id"] == "task-mcp-01"

            conflict_res = await client.call_tool(
                "pipeline_submit",
                {
                    "objective": "Different conflicting objective",
                    "task_id": "task-mcp-01",
                    "project_id": "registered-proj",
                },
            )
            assert conflict_res.isError

            # Unregistered project_id is rejected
            bad_proj = await client.call_tool(
                "pipeline_submit",
                {
                    "objective": "Some objective",
                    "task_id": "task-bad-proj",
                    "project_id": "unregistered-proj",
                },
            )
            assert bad_proj.isError

    asyncio.run(scenario())


def test_high_tier_task_surfaces_actual_plan_srs_and_owner_ui_flow_without_secret_leaks(task_endpoint):
    planner: PlanningController = task_endpoint.controller.task_planning
    broker: OwnerApprovalBroker = task_endpoint.controller.owner_approval_broker
    ui = OwnerReviewUI(planner, broker)

    auth = "Bearer " + task_endpoint.token
    code, sub = request(
        task_endpoint,
        "POST",
        "/tasks/submit",
        {"objective": "Build tier-9 formal verification engine", "task_id": "task-high-01"},
        authorization=auth,
    )
    assert code == 202
    job = _advance_srs(planner, "task-high-01", complexity=9)

    # Normal client polls status via GET /workflow/task-high-01 or GET /tasks/status/task-high-01
    code_wf, wf_view = request(task_endpoint, "GET", "/workflow/task-high-01", authorization=auth)
    code_ts, ts_view = request(task_endpoint, "GET", "/tasks/status/task-high-01", authorization=auth)
    assert code_wf == 200 and code_ts == 200
    assert wf_view == ts_view
    assert wf_view["task"]["stage"] == "OWNER_APPROVAL"
    assert wf_view["current_artifacts"]["srs_document"]["revision"] == 1
    assert wf_view["current_artifacts"]["srs_document"]["plan"] == document(9)["plan"]

    decisions = wf_view["actionable_decisions"]
    assert len(decisions) == 1
    decision_item = decisions[0]
    assert decision_item["decision_kind"] == "owner_srs_approval"
    assert decision_item["revision"] == 1
    assert decision_item["plan"] == document(9)["plan"]
    assert decision_item["architecture"] == document(9)["architecture"]
    assert decision_item["srs"] == document(9)["srs"]
    assert decision_item["allowed_decisions"] == ["approved", "revision_requested", "rejected"]

    # Verify zero leak of private tokens, leases, reservations, or challenge nonces
    serialized = json.dumps(wf_view)
    for forbidden in (
        job["attempt_id"],
        job["route"]["reservation_id"],
        OWNER_SECRET,
        "fencing_token",
        "lease_owner",
        "challenge_nonce",
        "hmac_sha256",
    ):
        assert forbidden not in serialized

    # Shared agent bearer token cannot approve via HTTP or OwnerReviewUI
    assert request(task_endpoint, "POST", "/tasks/approve", {"task_id": "task-high-01"}, authorization=auth)[0] == 404
    with pytest.raises(PermissionError, match="Shared agent bearer token"):
        ui.decide("task-high-01", decision="approved", owner_token=task_endpoint.token)

    # Human owner inspects pending approvals and Markdown summary, then approves with dedicated OWNER_SECRET
    pending = ui.list_pending_approvals()
    assert len(pending) == 1 and pending[0]["task_id"] == "task-high-01"
    md = ui.render_review_markdown("task-high-01")
    assert "task-high-01" in md and document(9)["plan"] in md

    updated_view = ui.decide(
        "task-high-01",
        decision="approved",
        owner_token=OWNER_SECRET,
        notes="Reviewed and approved revision 1",
    )
    assert updated_view["task"]["stage"] == "RESEARCH"
    assert updated_view["actionable_decisions"] == []

    # Cancel via /cancel works on 4.2.8 tasks
    code_cancel, cancelled_view = request(
        task_endpoint,
        "POST",
        "/cancel",
        {"workflow_id": "task-high-01"},
        authorization=auth,
    )
    assert code_cancel == 200
    assert cancelled_view["status"] == "FAILED"
    assert cancelled_view["task"]["stage"] == "CANCELLED"
