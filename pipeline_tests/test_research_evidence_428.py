"""Tests for durable research request, receipt, and bounded content store (`P428-06`)."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from cochem_pipeline.planning_journal import PlanningJournal
from cochem_pipeline.research_evidence_428 import (
    MAX_CHANNEL_BYTES,
    MAX_EXCERPT_BYTES,
    ResearchEvidenceStore,
    research_id_for_intent,
)
from pipeline_tests.test_workflow_428 import document


def _setup_board_at_research(tmp_path: Path):
    catalog = json.loads(
        (Path(__file__).parents[1] / "docs/4.2.8/routing-candidate.json").read_text(encoding="utf-8")
    )
    evidence_store = ResearchEvidenceStore(tmp_path / "research.sqlite")
    results: dict[str, dict] = {}
    journal = PlanningJournal(
        tmp_path / "planning.sqlite",
        catalog,
        model_result=results.get,
        search_result=evidence_store.load_for_journal,
        flash_context_limit=100000,
    )
    journal.create("task-res", "Design and verify a concurrent state machine")
    intent0 = journal.intent("task-res")
    from cochem_pipeline.task_routing import digest

    results["job0"] = {
        "job_id": "job0",
        "intent_sha256": digest(intent0),
        "profile_id": intent0["candidate_profiles"][0],
        "status": "COMPLETED",
        "cleanup_verified": True,
        "output": document(5),
    }
    state = journal.apply_model_result("task-res", 0, "job0")
    assert state["stage"] == "RESEARCH"
    return journal, evidence_store


def test_research_store_persists_reopens_and_hydrates_journal_excerpts(tmp_path):
    journal, store = _setup_board_at_research(tmp_path)
    intent = journal.intent("task-res")
    assert intent["action"] == "controller_research"
    req = store.register_request(intent)
    res_id = req["research_id"]
    assert res_id == research_id_for_intent(intent)

    # Record three channels: internet (found), wiki_rag (found), papers (no_results)
    store.record_channel(
        res_id,
        "internet",
        query=intent["query"],
        status="found",
        sources=[
            {
                "id": "https://sqlite.org/wal.html",
                "title": "SQLite Write-Ahead Logging",
                "content": "WAL provides concurrency where readers do not block writers.",
            }
        ],
    )
    store.record_channel(
        res_id,
        "wiki_rag",
        query=intent["query"],
        status="found",
        sources=[
            {
                "id": "wiki://architecture/wal-428",
                "title": "Pipeline 4.2.8 WAL Architecture",
                "content": "Single-writer immediate transactions prevent deadlocks.",
            }
        ],
    )
    store.record_channel(
        res_id,
        "papers",
        query=intent["query"],
        status="no_results",
        sources=[],
    )

    # Before publish, load_for_journal returns None
    assert store.load_for_journal(res_id) is None

    published = store.publish(res_id)
    assert published["channels"]["papers"]["status"] == "no_results"
    assert len(published["excerpts"]["internet"]) == 1

    # Reopen store from disk and apply to PlanningJournal
    reopened_store = ResearchEvidenceStore(store.path)
    journal.search_result = reopened_store.load_for_journal
    updated = journal.apply_research("task-res", intent["version"], res_id)
    assert updated["stage"] == "PLAN_REVIEW"
    assert (
        updated["research_excerpts"]["internet"][0]["content"]
        == "WAL provides concurrency where readers do not block writers."
    )
    assert updated["research_excerpts"]["papers"] == []

    # Idempotent replay
    assert journal.apply_research("task-res", intent["version"], res_id) == updated


def test_interrupted_partial_collection_cannot_publish_or_advance_journal(tmp_path):
    journal, store = _setup_board_at_research(tmp_path)
    intent = journal.intent("task-res")
    req = store.register_request(intent)
    res_id = req["research_id"]

    store.record_channel(
        res_id,
        "internet",
        query=intent["query"],
        status="found",
        sources=[{"id": "https://example.org/doc", "title": "Doc", "content": "Verified excerpt"}],
    )
    store.record_channel(
        res_id,
        "wiki_rag",
        query=intent["query"],
        status="no_results",
        sources=[],
    )
    # Missing 'papers' channel!
    with pytest.raises(ValueError, match="all three channels"):
        store.publish(res_id)
    assert store.load_for_journal(res_id) is None
    with pytest.raises(ValueError, match="unavailable"):
        journal.apply_research("task-res", intent["version"], res_id)


def test_unavailable_channel_transitions_to_research_hold_not_no_results(tmp_path):
    journal, store = _setup_board_at_research(tmp_path)
    intent = journal.intent("task-res")
    req = store.register_request(intent)
    res_id = req["research_id"]

    store.record_channel(res_id, "internet", query=intent["query"], status="unavailable", sources=[])
    store.record_channel(res_id, "wiki_rag", query=intent["query"], status="no_results", sources=[])
    store.record_channel(res_id, "papers", query=intent["query"], status="no_results", sources=[])
    store.publish(res_id)

    updated = journal.apply_research("task-res", intent["version"], res_id)
    assert updated["stage"] == "RESEARCH_HOLD"
    assert updated.get("research") is None
    assert "research_excerpts" not in updated


def test_tampered_content_and_digest_mismatch_are_rejected(tmp_path):
    journal, store = _setup_board_at_research(tmp_path)
    intent = journal.intent("task-res")
    req = store.register_request(intent)
    res_id = req["research_id"]

    # 1. Caller passes wrong sha256 for source content
    with pytest.raises(ValueError, match="digest does not match"):
        store.record_channel(
            res_id,
            "internet",
            query=intent["query"],
            status="found",
            sources=[
                {
                    "id": "https://example.org/1",
                    "title": "Doc",
                    "content": "Real text",
                    "sha256": "a" * 64,
                }
            ],
        )

    # 2. Record valid channels and publish, then tamper with SQLite content_text on disk
    store.record_channel(
        res_id,
        "internet",
        query=intent["query"],
        status="found",
        sources=[{"id": "https://example.org/1", "title": "Doc", "content": "Authentic bytes"}],
    )
    store.record_channel(res_id, "wiki_rag", query=intent["query"], status="no_results", sources=[])
    store.record_channel(res_id, "papers", query=intent["query"], status="no_results", sources=[])
    store.publish(res_id)

    conn = sqlite3.connect(store.path)
    try:
        conn.execute(
            "UPDATE research428_sources SET content_text='Tampered bytes!' WHERE research_id=?",
            (res_id,),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError, match="SHA256 integrity"):
        store.load_for_journal(res_id)
    with pytest.raises(ValueError, match="SHA256 integrity"):
        journal.apply_research("task-res", intent["version"], res_id)


def test_size_bounds_enforced_per_excerpt_and_per_channel(tmp_path):
    journal, store = _setup_board_at_research(tmp_path)
    intent = journal.intent("task-res")
    req = store.register_request(intent)
    res_id = req["research_id"]

    # Oversize single excerpt (> 32 KiB)
    with pytest.raises(ValueError, match="32 KiB"):
        store.record_channel(
            res_id,
            "internet",
            query=intent["query"],
            status="found",
            sources=[
                {
                    "id": "https://example.org/huge",
                    "title": "Huge",
                    "content": "x" * (MAX_EXCERPT_BYTES + 1),
                }
            ],
        )

    # Oversize channel total (> 256 KiB across 9 x 30 KiB sources)
    chunk = "y" * (30 * 1024)
    many_sources = [
        {"id": f"https://example.org/{i}", "title": f"Doc {i}", "content": chunk}
        for i in range(9)
    ]
    assert sum(len(s["content"]) for s in many_sources) > MAX_CHANNEL_BYTES
    with pytest.raises(ValueError, match="256 KiB"):
        store.record_channel(
            res_id,
            "internet",
            query=intent["query"],
            status="found",
            sources=many_sources,
        )
