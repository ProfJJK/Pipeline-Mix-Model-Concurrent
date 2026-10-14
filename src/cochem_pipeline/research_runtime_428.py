"""Nonblocking three-channel research runtime and wiki RAG adapter (`P428-08`).

Connects `ResearchEvidenceStore` (`P428-06`), `ResearchSearchClient` (`P428-07`),
and the registered `KnowledgeService` / `KnowledgeAuthority` (`wiki_rag` channel)
to `PlanningController` without performing network or long DB waits on the
scheduler or health-check threads:
- `enqueue(intent)` is a fast local SQLite registration called by `PlanningController`.
- `step_worker(limit)` runs out-of-band to execute pending/backoff research jobs,
  verifying wiki generation stability across queries, handling outages with
  bounded exponential backoff, honoring cancellation before publication, and
  persisting verified source excerpts into `ResearchEvidenceStore`.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any

from .knowledge import KnowledgeError, KnowledgeFileChanged
from .research_evidence_428 import (
    MAX_CHANNEL_BYTES,
    MAX_EXCERPT_BYTES,
    MAX_SOURCES_PER_CHANNEL,
    REQUIRED_CHANNELS,
    ResearchEvidenceStore,
    research_id_for_intent,
)
from .research_search_428 import ResearchSearchClient, _truncate_utf8
from .workflow_428 import _id, _text


class ResearchRuntime:
    """Out-of-band three-channel research coordinator with bounded backoff and wiki verification."""

    def __init__(
        self,
        evidence_store: ResearchEvidenceStore,
        search_client: ResearchSearchClient,
        *,
        knowledge_service: Any = None,
        knowledge_authority: Any = None,
        clock=time.time,
        base_backoff_seconds: float = 15.0,
        max_backoff_seconds: float = 300.0,
    ):
        self.evidence_store = evidence_store
        self.search_client = search_client
        self.knowledge_service = knowledge_service
        self.knowledge_authority = knowledge_authority
        self.clock = clock
        self.base_backoff_seconds = float(base_backoff_seconds)
        self.max_backoff_seconds = float(max_backoff_seconds)
        self._worker_lock = threading.Lock()
        with self._write() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS research428_queue(
                    research_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    srs_sha256 TEXT NOT NULL,
                    intent_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    next_run_at REAL NOT NULL,
                    cancelled INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    updated_at REAL NOT NULL
                );
                """
            )

    @contextmanager
    def _write(self):
        conn = sqlite3.connect(self.evidence_store.path, timeout=5)
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

    def enqueue(self, intent: dict[str, Any]) -> dict[str, Any]:
        """Nonblocking registration of a `controller_research` planning intent."""
        req = self.evidence_store.register_request(intent, clock=self.clock)
        research_id = req["research_id"]
        now = float(self.clock())
        intent_json = json.dumps(intent, sort_keys=True, allow_nan=False)
        with self._write() as conn:
            # Cancel any older pending queue items for the same task_id with a different srs_sha256
            conn.execute(
                "UPDATE research428_queue SET cancelled=1, status='CANCELLED', updated_at=? "
                "WHERE task_id=? AND srs_sha256!=? AND status IN ('PENDING', 'BACKOFF')",
                (now, req["task_id"], req["srs_sha256"]),
            )
            existing = conn.execute(
                "SELECT * FROM research428_queue WHERE research_id=?",
                (research_id,),
            ).fetchone()
            if existing is not None:
                return dict(existing)
            conn.execute(
                "INSERT INTO research428_queue VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    research_id,
                    req["task_id"],
                    req["srs_sha256"],
                    intent_json,
                    "PENDING",
                    0,
                    now,
                    0,
                    None,
                    now,
                ),
            )
            return dict(
                conn.execute(
                    "SELECT * FROM research428_queue WHERE research_id=?",
                    (research_id,),
                ).fetchone()
            )

    def cancel(self, research_id: str) -> bool:
        """Mark a queued research request as cancelled so it cannot publish."""
        _id(research_id)
        now = float(self.clock())
        with self._write() as conn:
            cur = conn.execute(
                "UPDATE research428_queue SET cancelled=1, status='CANCELLED', updated_at=? "
                "WHERE research_id=? AND status!='PUBLISHED'",
                (now, research_id),
            )
            return cur.rowcount > 0

    def queue_status(self, research_id: str) -> dict[str, Any] | None:
        _id(research_id)
        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM research428_queue WHERE research_id=?",
                (research_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def backoff_delay(self, research_id: str, default: float = 30.0) -> float:
        row = self.queue_status(research_id)
        if row is None:
            return default
        now = float(self.clock())
        remaining = float(row["next_run_at"]) - now
        return max(1.0, remaining) if remaining > 0 else default

    def has_due_work(self) -> bool:
        """Return True if at least one non-cancelled research request is due for collection."""
        now = float(self.clock())
        with self._write() as conn:
            row = conn.execute(
                "SELECT 1 FROM research428_queue "
                "WHERE cancelled=0 AND status IN ('PENDING', 'BACKOFF') AND next_run_at<=? "
                "LIMIT 1",
                (now,),
            ).fetchone()
            return row is not None

    def collect_wiki_rag(self, query: str) -> dict[str, Any]:
        """Collect bounded verified excerpts from the local registered KnowledgeService."""
        query_text = _text(query, "Research query", 2000)
        if self.knowledge_service is None:
            return {
                "channel": "wiki_rag",
                "query": query_text,
                "status": "unavailable",
                "sources": [],
                "error_code": "KNOWLEDGE_SERVICE_UNCONFIGURED",
            }
        try:
            if self.knowledge_authority is not None:
                auth_status = self.knowledge_authority.status()
                if auth_status.get("authority_matches_capture") is not True:
                    return {
                        "channel": "wiki_rag",
                        "query": query_text,
                        "status": "unavailable",
                        "sources": [],
                        "error_code": "KNOWLEDGE_AUTHORITY_MISMATCH",
                    }
            status_before = self.knowledge_service.status()
            if status_before.get("ready") is not True:
                return {
                    "channel": "wiki_rag",
                    "query": query_text,
                    "status": "unavailable",
                    "sources": [],
                    "error_code": "KNOWLEDGE_INDEX_NOT_READY",
                }
            generation_before = status_before.get("generation")
            manifest_before = status_before.get("manifest_sha256")
            if not isinstance(generation_before, str) or not generation_before:
                return {
                    "channel": "wiki_rag",
                    "query": query_text,
                    "status": "unavailable",
                    "sources": [],
                    "error_code": "KNOWLEDGE_GENERATION_MISSING",
                }

            words = [w for w in re.findall(r"\w+", query_text, re.UNICODE) if len(w) >= 2][:8]
            search_expr = " ".join(words) if words else query_text[:128]
            hits = self.knowledge_service.search(search_expr, limit=5)

            status_after = self.knowledge_service.status()
            if (
                status_after.get("ready") is not True
                or status_after.get("generation") != generation_before
                or status_after.get("manifest_sha256") != manifest_before
            ):
                return {
                    "channel": "wiki_rag",
                    "query": query_text,
                    "status": "unavailable",
                    "sources": [],
                    "error_code": "WIKI_GENERATION_DRIFT",
                }

            sources: list[dict[str, Any]] = []
            total_bytes = 0
            seen_ids: set[str] = set()
            for idx, hit in enumerate(hits[:MAX_SOURCES_PER_CHANNEL]):
                if not isinstance(hit, dict):
                    continue
                if hit.get("generation") != generation_before:
                    return {
                        "channel": "wiki_rag",
                        "query": query_text,
                        "status": "unavailable",
                        "sources": [],
                        "error_code": "WIKI_GENERATION_DRIFT",
                    }
                doc_path = str(hit.get("doc_path") or "").strip()
                section_title = str(hit.get("section_title") or "section").strip()
                snippet = str(hit.get("snippet") or "").strip()
                if not doc_path:
                    continue
                # Read verified document if available to confirm sha256 and generation parity
                doc_body = snippet
                if hasattr(self.knowledge_service, "read"):
                    doc_record = self.knowledge_service.read(doc_path)
                    if doc_record.get("generation") != generation_before:
                        return {
                            "channel": "wiki_rag",
                            "query": query_text,
                            "status": "unavailable",
                            "sources": [],
                            "error_code": "WIKI_GENERATION_DRIFT",
                        }
                    if not doc_body and isinstance(doc_record.get("text"), str):
                        doc_body = doc_record["text"].strip()
                if not doc_body:
                    continue
                source_id = f"wiki://{generation_before}/{doc_path}#{section_title or idx}"[:2048]
                if source_id in seen_ids:
                    continue
                seen_ids.add(source_id)
                title = f"{doc_path} ({section_title})"[:512]
                excerpt = _truncate_utf8(f"{title}: {doc_body}", MAX_EXCERPT_BYTES)
                encoded = excerpt.encode("utf-8")
                if not encoded or total_bytes + len(encoded) > MAX_CHANNEL_BYTES:
                    break
                total_bytes += len(encoded)
                sources.append(
                    {
                        "id": source_id,
                        "title": title,
                        "content": excerpt,
                        "sha256": hashlib.sha256(encoded).hexdigest(),
                    }
                )

            return {
                "channel": "wiki_rag",
                "query": query_text,
                "status": "found" if sources else "no_results",
                "sources": sources,
            }
        except (KnowledgeFileChanged, KnowledgeError):
            return {
                "channel": "wiki_rag",
                "query": query_text,
                "status": "unavailable",
                "sources": [],
                "error_code": "WIKI_GENERATION_OR_READ_ERROR",
            }
        except Exception:
            return {
                "channel": "wiki_rag",
                "query": query_text,
                "status": "unavailable",
                "sources": [],
                "error_code": "WIKI_UNEXPECTED_ERROR",
            }

    def _is_cancelled(self, research_id: str) -> bool:
        with self._write() as conn:
            row = conn.execute(
                "SELECT cancelled, status FROM research428_queue WHERE research_id=?",
                (research_id,),
            ).fetchone()
            return row is None or bool(row["cancelled"]) or row["status"] == "CANCELLED"

    def _existing_channel(self, research_id: str, channel: str) -> dict[str, Any] | None:
        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM research428_channel_receipts WHERE research_id=? AND channel=?",
                (research_id, channel),
            ).fetchone()
            return dict(row) if row is not None else None

    def step_worker(self, limit: int = 4) -> int:
        """Execute up to `limit` queued research requests outside the scheduler lock."""
        if type(limit) is not int or not 1 <= limit <= 16:
            raise ValueError("Research worker step limit must be in 1..16")
        if not self._worker_lock.acquire(blocking=False):
            return 0
        try:
            now = float(self.clock())
            with self._write() as conn:
                due_rows = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM research428_queue "
                        "WHERE cancelled=0 AND status IN ('PENDING', 'BACKOFF') AND next_run_at<=? "
                        "ORDER BY next_run_at ASC, research_id ASC LIMIT ?",
                        (now, limit),
                    ).fetchall()
                ]
            processed = 0
            for qrow in due_rows:
                research_id = qrow["research_id"]
                if self._is_cancelled(research_id):
                    continue
                intent = json.loads(qrow["intent_json"])
                query = intent["query"]
                attempts = int(qrow["attempts"]) + 1
                channel_outcomes: dict[str, dict[str, Any]] = {}
                cancelled_mid_flight = False

                for channel in REQUIRED_CHANNELS:
                    if self._is_cancelled(research_id):
                        cancelled_mid_flight = True
                        break
                    prior = self._existing_channel(research_id, channel)
                    if prior is not None and prior["status"] in ("found", "no_results"):
                        channel_outcomes[channel] = prior
                        continue
                    if channel == "internet":
                        outcome = self.search_client.search_internet(query)
                    elif channel == "wiki_rag":
                        outcome = self.collect_wiki_rag(query)
                    else:
                        outcome = self.search_client.search_papers(query)
                    channel_outcomes[channel] = outcome

                if cancelled_mid_flight or self._is_cancelled(research_id):
                    continue

                # Record all channels in ResearchEvidenceStore and publish
                for channel in REQUIRED_CHANNELS:
                    if self._existing_channel(research_id, channel) is None:
                        out = channel_outcomes[channel]
                        self.evidence_store.record_channel(
                            research_id,
                            channel,
                            query=query,
                            status=out["status"],
                            sources=out.get("sources", []),
                            observed_at=float(self.clock()),
                        )

                self.evidence_store.publish(research_id, clock=self.clock)
                any_unavailable = any(
                    channel_outcomes[ch]["status"] == "unavailable" for ch in REQUIRED_CHANNELS
                )
                delay = min(
                    self.max_backoff_seconds,
                    self.base_backoff_seconds * (2 ** max(0, attempts - 1)),
                )
                now_done = float(self.clock())
                with self._write() as conn:
                    conn.execute(
                        "UPDATE research428_queue SET status=?, attempts=?, next_run_at=?, "
                        "last_error=?, updated_at=? WHERE research_id=?",
                        (
                            "PUBLISHED_WITH_UNAVAILABLE" if any_unavailable else "PUBLISHED",
                            attempts,
                            now_done + (delay if any_unavailable else 0.0),
                            "CHANNEL_UNAVAILABLE" if any_unavailable else None,
                            now_done,
                            research_id,
                        ),
                    )
                processed += 1
            return processed
        finally:
            self._worker_lock.release()
