"""Tests for wiki research and nonblocking planner evidence consumption (`P428-08`)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cochem_pipeline.planning_gateway import prompt_contract
from cochem_pipeline.planning_journal import PlanningJournal
from cochem_pipeline.planning_runtime import PlanningController
from cochem_pipeline.research_evidence_428 import ResearchEvidenceStore
from cochem_pipeline.research_runtime_428 import ResearchRuntime
from cochem_pipeline.research_search_428 import HttpResponseFixture, ResearchSearchClient
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.store import JobStore
from cochem_pipeline.worker import node_prompt
from pipeline_tests.test_planning_gateway_428 import accepted_receipt
from pipeline_tests.test_workflow_428 import document


class _FakeKnowledgeService:
    def __init__(self, *, generation: str = "g-" + "1" * 32, drift_on_read: bool = False):
        self.generation = generation
        self.manifest_sha256 = "2" * 64
        self.drift_on_read = drift_on_read
        self.search_calls = 0

    def status(self):
        return {
            "ready": True,
            "generation": self.generation,
            "manifest_sha256": self.manifest_sha256,
        }

    def search(self, query: str, limit: int = 5):
        self.search_calls += 1
        return [
            {
                "doc_path": "wiki/architecture/wal.md",
                "section_title": "Write-Ahead Logging",
                "snippet": "Verified wiki section excerpt on WAL isolation.",
                "generation": self.generation,
            }
        ]

    def read(self, doc_path: str):
        gen = ("g-" + "9" * 32) if self.drift_on_read else self.generation
        if self.drift_on_read:
            self.generation = gen
        return {
            "path": doc_path,
            "sha256": "3" * 64,
            "text": "Full document body for WAL isolation.",
            "generation": gen,
        }


class _FakeKnowledgeAuthority:
    def __init__(self, matches: bool = True):
        self.matches = matches

    def status(self, *, force: bool = False):
        return {"authority_matches_capture": self.matches}


def _make_stack(
    tmp_path: Path,
    *,
    flash_limit: int = 100000,
    drift_on_read: bool = False,
    fail_internet_first: bool = False,
):
    catalog = json.loads(
        (Path(__file__).parents[1] / "docs/4.2.8/routing-candidate.json").read_text(encoding="utf-8")
    )
    clock = [1000.0]
    ev_store = ResearchEvidenceStore(tmp_path / "research.db")
    calls = {"internet": 0, "papers": 0}

    def transport(url: str, headers: dict, timeout: float, max_bytes: int) -> HttpResponseFixture:
        if "en.wikipedia.org" in url:
            calls["internet"] += 1
            if fail_internet_first and calls["internet"] == 1:
                return HttpResponseFixture(status_code=503, body=b"Unavailable", url=url)
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
        calls["papers"] += 1
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

    search_client = ResearchSearchClient(
        transport=transport,
        resolver=lambda _host: ["93.184.216.34"],
    )
    knowledge = _FakeKnowledgeService(drift_on_read=drift_on_read)
    authority = _FakeKnowledgeAuthority(matches=True)
    res_runtime = ResearchRuntime(
        ev_store,
        search_client,
        knowledge_service=knowledge,
        knowledge_authority=authority,
        clock=lambda: clock[0],
    )
    journal = PlanningJournal(
        tmp_path / "planning.db",
        catalog,
        flash_context_limit=flash_limit,
    )
    store = JobStore(tmp_path / "jobs.db", routing_policy=load_routing_policy({"policy_version": 3}))
    controller = PlanningController(
        journal,
        store,
        clock=lambda: clock[0],
        research_runtime=res_runtime,
    )
    return controller, res_runtime, knowledge, calls, clock


def _advance_srs(controller: PlanningController, clock: list[float], complexity: int = 5):
    controller.submit("Implement concurrent state machine with WAL", "task-1")
    clock[0] += 2
    controller.step()
    job = controller.store.claim("test", worker_slot="slot1", allowed_kinds=["TASK_PLAN"], requires_cleanup=True)
    assert job is not None
    out = document(complexity)
    controller.store.clear_execution_quarantine(job["job_id"], job["attempt_id"], job["fencing_token"])
    controller.store.complete(job["job_id"], job["attempt_id"], job["fencing_token"], out, accepted_receipt(job, out))
    clock[0] += 2
    controller.step()
    assert controller.journal.status("task-1")["stage"] == "RESEARCH"


def test_three_channel_success_hydrates_review_prompt_without_blocking_scheduler(tmp_path):
    controller, res_runtime, knowledge, calls, clock = _make_stack(tmp_path)
    try:
        _advance_srs(controller, clock, complexity=5)

        # Scheduler step enqueues research without calling transport or knowledge_service
        clock[0] += 2
        controller.step()
        status = controller.task_status("task-1")
        assert status["controller"]["status"] == "WAITING_FOR_RESEARCH"
        assert calls == {"internet": 0, "papers": 0}
        assert knowledge.search_calls == 0

        # Out-of-band worker executes the queued research once
        assert res_runtime.step_worker() == 1
        assert calls == {"internet": 1, "papers": 1}
        assert knowledge.search_calls == 1
        # Second worker step has no due work (no duplicate queries)
        assert res_runtime.step_worker() == 0
        assert calls == {"internet": 1, "papers": 1}

        # Next scheduler poll imports completed research and advances to PLAN_REVIEW
        clock[0] += 35
        controller.step()
        task_state = controller.journal.status("task-1")
        assert task_state["stage"] == "PLAN_REVIEW"
        assert "research_excerpts" in task_state
        assert len(task_state["research_excerpts"]["wiki_rag"]) == 1

        # Next scheduler poll submits the PLAN_REVIEW job with hydrated research excerpts
        clock[0] += 2
        controller.step()
        review_job = controller.store.claim(
            "test", worker_slot="slot1", allowed_kinds=["TASK_PLAN"], requires_cleanup=True
        )
        assert review_job is not None
        rendered_prompt = node_prompt(review_job, "")
        assert "Optimistic and pessimistic concurrency control." in rendered_prompt
        assert "Verified wiki section excerpt on WAL isolation." in rendered_prompt
        assert "Formal verification of bounded state machines." in rendered_prompt
    finally:
        controller.store.close()


def test_wiki_generation_drift_and_outage_hold_and_recover_after_restart(tmp_path):
    # 1. Wiki generation drift mid-query produces RESEARCH_HOLD
    controller, res_runtime, knowledge, calls, clock = _make_stack(tmp_path, drift_on_read=True)
    try:
        _advance_srs(controller, clock, complexity=5)
        clock[0] += 2
        controller.step()
        assert res_runtime.step_worker() == 1
        clock[0] += 35
        controller.step()
        state = controller.journal.status("task-1")
        assert state["stage"] == "RESEARCH_HOLD"
        assert state["research_attempt"]["wiki_rag"]["status"] == "unavailable"

        # Fix drift and restart ResearchRuntime + PlanningController on same DBs
        knowledge.drift_on_read = False
        reopened_ev = ResearchEvidenceStore(res_runtime.evidence_store.path)
        reopened_res = ResearchRuntime(
            reopened_ev,
            res_runtime.search_client,
            knowledge_service=knowledge,
            knowledge_authority=res_runtime.knowledge_authority,
            clock=lambda: clock[0],
        )
        reopened_journal = PlanningJournal(
            controller.journal.path,
            controller.journal.catalog,
            flash_context_limit=100000,
        )
        reopened_ctrl = PlanningController(
            reopened_journal,
            controller.store,
            clock=lambda: clock[0],
            research_runtime=reopened_res,
        )
        clock[0] += 2
        reopened_ctrl.step()
        assert reopened_res.step_worker() == 1
        clock[0] += 35
        reopened_ctrl.step()
        assert reopened_ctrl.journal.status("task-1")["stage"] == "PLAN_REVIEW"
    finally:
        controller.store.close()


def test_cancellation_and_context_budget_overflow_and_stale_srs_rejected(tmp_path):
    controller, res_runtime, _, calls, clock = _make_stack(tmp_path, flash_limit=6000)
    try:
        _advance_srs(controller, clock, complexity=5)
        clock[0] += 2
        controller.step()
        res_id = controller.task_status("task-1")["controller"]["research_id"]

        # Cancel before worker runs -> worker skips it and does not query or publish
        assert res_runtime.cancel(res_id) is True
        assert res_runtime.step_worker() == 0
        assert calls == {"internet": 0, "papers": 0}
        assert res_runtime.evidence_store.load_for_journal(res_id) is None

        # Test prompt_contract rejection on stale srs_sha256 and context overflow
        intent = controller.journal.intent("task-1")
        current_task = controller.journal.status("task-1")
        fake_task = dict(
            current_task,
            stage="PLAN_REVIEW",
            research={
                "srs_sha256": "f" * 64,
                "channels": {
                    "internet": {"query": "q", "status": "no_results", "receipt_sha256": "a" * 64, "sources": []},
                    "wiki_rag": {"query": "q", "status": "no_results", "receipt_sha256": "b" * 64, "sources": []},
                    "papers": {"query": "q", "status": "no_results", "receipt_sha256": "c" * 64, "sources": []},
                },
            },
        )
        bad_payload = {
            "planning_intent": dict(intent, stage="PLAN_REVIEW", task=fake_task),
            "flash_context_limit": 100000,
        }
        with pytest.raises(ValueError, match="stale SRS revision"):
            prompt_contract(bad_payload)

        # Valid srs_sha256 but tight flash_context_limit overflows when excerpts are included
        import hashlib
        big_text = "z" * 4000
        big_sha = hashlib.sha256(big_text.encode("utf-8")).hexdigest()
        overflow_task = dict(
            current_task,
            stage="PLAN_REVIEW",
            research={
                "srs_sha256": current_task["srs_sha256"],
                "channels": {
                    "internet": {
                        "query": "q",
                        "status": "found",
                        "receipt_sha256": "a" * 64,
                        "sources": [{"id": "https://en.wikipedia.org/1", "sha256": big_sha}],
                    },
                    "wiki_rag": {"query": "q", "status": "no_results", "receipt_sha256": "b" * 64, "sources": []},
                    "papers": {"query": "q", "status": "no_results", "receipt_sha256": "c" * 64, "sources": []},
                },
            },
            research_excerpts={
                "internet": [
                    {
                        "id": "https://en.wikipedia.org/1",
                        "title": "Doc",
                        "sha256": big_sha,
                        "content": big_text,
                    }
                ],
                "wiki_rag": [],
                "papers": [],
            },
        )
        overflow_payload = {
            "planning_intent": dict(intent, stage="PLAN_REVIEW", task=overflow_task),
            "flash_context_limit": 8000,
        }
        with pytest.raises(ValueError, match="context budget"):
            prompt_contract(overflow_payload)
    finally:
        controller.store.close()
