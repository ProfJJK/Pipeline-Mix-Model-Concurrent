"""Durable controller-owned research request, receipt, and bounded content store (`P428-06`).

Implements `cochem-research-request/4.2.8` and `cochem-research-receipt/4.2.8`
from `docs/4.2.8/INTEGRATION_CONTRACTS.md`:
- Genuine empty search (`no_results`, `sources == []`) is strictly distinct from
  provider/network outage (`unavailable`).
- Interrupted collection (fewer than all three required channels recorded or not
  explicitly published) never exposes partial evidence to `PlanningJournal`.
- Every source excerpt is bounded to <= 32 KiB (32,768 bytes) and <= 256 KiB
  (262,144 bytes) per channel across at most 30 sources.
- Content digests are verified on write, publish, and readback so tampered or
  substituted content under an existing digest is rejected.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from .task_routing import digest
from .workflow_428 import _id, _sha, _text, validate_research


REQUIRED_CHANNELS: tuple[str, ...] = ("internet", "wiki_rag", "papers")
MAX_EXCERPT_BYTES = 32 * 1024
MAX_CHANNEL_BYTES = 256 * 1024
MAX_SOURCES_PER_CHANNEL = 30


def research_id_for_intent(intent: dict[str, Any]) -> str:
    """Deterministic research request identifier for a planning intent."""
    if (
        not isinstance(intent, dict)
        or intent.get("schema") != "cochem-planning-intent/4.2.8"
        or intent.get("action") != "controller_research"
    ):
        raise ValueError("Research ID requires a valid controller_research planning intent")
    _sha(intent.get("srs_sha256"))
    return "research428-" + digest(intent)[:40]


def validate_research_excerpts(
    channels: dict[str, Any],
    excerpts: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Validate that bounded source excerpts match the channel source digests byte-for-byte."""
    validate_research(channels)
    if not isinstance(excerpts, dict) or set(excerpts) != set(REQUIRED_CHANNELS):
        raise ValueError("Research excerpts must cover internet, wiki_rag, and papers")
    normalized: dict[str, list[dict[str, Any]]] = {}
    for channel in REQUIRED_CHANNELS:
        expected_sources = channels[channel]["sources"]
        channel_excerpts = excerpts[channel]
        if not isinstance(channel_excerpts, list) or len(channel_excerpts) != len(expected_sources):
            raise ValueError(f"Research excerpts count mismatch for channel {channel}")
        total_bytes = 0
        rows: list[dict[str, Any]] = []
        for expected, item in zip(expected_sources, channel_excerpts, strict=True):
            if not isinstance(item, dict) or set(item) != {"id", "title", "sha256", "content"}:
                raise ValueError("Research excerpt requires id, title, sha256, and content")
            source_id = _text(item["id"], "Research source identifier", 2048)
            title = _text(item["title"], "Research source title", 512)
            sha = _sha(item["sha256"])
            content = item["content"]
            if not isinstance(content, str) or not content or "\x00" in content:
                raise ValueError("Research excerpt content must be nonempty text without NUL bytes")
            raw = content.encode("utf-8")
            if not 1 <= len(raw) <= MAX_EXCERPT_BYTES:
                raise ValueError("Research excerpt exceeds 32 KiB source bound")
            total_bytes += len(raw)
            if total_bytes > MAX_CHANNEL_BYTES:
                raise ValueError("Research channel excerpts exceed 256 KiB channel bound")
            if hashlib.sha256(raw).hexdigest() != sha:
                raise ValueError("Research excerpt content digest mismatch")
            if source_id != expected["id"] or sha != expected["sha256"]:
                raise ValueError("Research excerpt does not match channel source receipt")
            rows.append(
                {
                    "id": source_id,
                    "title": title,
                    "sha256": sha,
                    "content": content,
                }
            )
        normalized[channel] = rows
    return normalized


class ResearchEvidenceStore:
    """Durable SQLite store for controller-executed research requests, receipts, and excerpts."""

    def __init__(self, path: str | Path):
        if str(path) == ":memory:":
            raise ValueError("Research evidence requires a durable SQLite file")
        self.path = Path(path)
        with self._write() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS research428_requests(
                    research_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    intent_sha256 TEXT NOT NULL,
                    srs_sha256 TEXT NOT NULL,
                    query TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research428_channel_receipts(
                    research_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    query TEXT NOT NULL,
                    status TEXT NOT NULL,
                    observed_at REAL NOT NULL,
                    receipt_sha256 TEXT NOT NULL,
                    sources_json TEXT NOT NULL,
                    PRIMARY KEY(research_id, channel)
                );
                CREATE TABLE IF NOT EXISTS research428_sources(
                    research_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    source_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    content_text TEXT NOT NULL,
                    byte_length INTEGER NOT NULL,
                    PRIMARY KEY(research_id, channel, position)
                );
                CREATE TABLE IF NOT EXISTS research428_published(
                    research_id TEXT PRIMARY KEY,
                    intent_sha256 TEXT NOT NULL,
                    srs_sha256 TEXT NOT NULL,
                    channels_json TEXT NOT NULL,
                    published_at REAL NOT NULL
                );
                """
            )

    @contextmanager
    def _write(self):
        conn = sqlite3.connect(self.path, timeout=5)
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

    def register_request(
        self,
        intent: dict[str, Any],
        *,
        clock=time.time,
    ) -> dict[str, Any]:
        """Idempotently register a controller_research planning intent."""
        research_id = research_id_for_intent(intent)
        task_id = _id(intent.get("task_id"))
        srs_sha256 = _sha(intent.get("srs_sha256"))
        query = _text(intent.get("query"), "Research query", 2000)
        channels = intent.get("channels")
        if channels != list(REQUIRED_CHANNELS):
            raise ValueError("Research intent must request internet, wiki_rag, and papers")
        intent_sha256 = digest(intent)
        request_doc = {
            "schema": "cochem-research-request/4.2.8",
            "research_id": research_id,
            "task_id": task_id,
            "intent_sha256": intent_sha256,
            "srs_sha256": srs_sha256,
            "query": query,
            "channels": list(REQUIRED_CHANNELS),
        }
        canonical_json = json.dumps(request_doc, sort_keys=True, allow_nan=False)
        now = float(clock())
        with self._write() as conn:
            existing = conn.execute(
                "SELECT request_json FROM research428_requests WHERE research_id=?",
                (research_id,),
            ).fetchone()
            if existing is not None:
                if existing["request_json"] != canonical_json:
                    raise ValueError("Research request ID is already bound to a different intent")
                return json.loads(existing["request_json"])
            conn.execute(
                "INSERT INTO research428_requests VALUES(?,?,?,?,?,?,?)",
                (research_id, task_id, intent_sha256, srs_sha256, query, canonical_json, now),
            )
        return request_doc

    def record_channel(
        self,
        research_id: str,
        channel: str,
        *,
        query: str,
        status: str,
        sources: list[dict[str, Any]],
        observed_at: float | None = None,
    ) -> dict[str, Any]:
        """Record one channel's search outcome and bounded source excerpts without publishing."""
        _id(research_id)
        if channel not in REQUIRED_CHANNELS:
            raise ValueError(f"Unsupported research channel: {channel}")
        query_text = _text(query, "Research query", 2000)
        if status not in ("found", "no_results", "unavailable"):
            raise ValueError(f"Unknown research status: {status}")
        if not isinstance(sources, list) or len(sources) > MAX_SOURCES_PER_CHANNEL:
            raise ValueError("Research channel sources must be a list of at most 30 items")
        if bool(sources) != (status == "found"):
            raise ValueError("Research sources presence must match 'found' vs 'no_results'/'unavailable'")

        ts = float(time.time() if observed_at is None else observed_at)
        normalized_sources: list[dict[str, str]] = []
        source_rows: list[tuple[int, str, str, str, str, int]] = []
        total_bytes = 0
        seen_ids: set[str] = set()

        for idx, src in enumerate(sources):
            if not isinstance(src, dict):
                raise ValueError("Research source entry must be an object")
            source_id = _text(src.get("id"), "Research source identifier", 2048)
            if source_id in seen_ids:
                raise ValueError("Duplicate source identifier in research channel")
            seen_ids.add(source_id)
            title = _text(src.get("title", source_id[:512]), "Research source title", 512)
            raw_content = src.get("content")
            if isinstance(raw_content, (bytes, bytearray)):
                try:
                    content_text = bytes(raw_content).decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError("Research source bytes must be valid UTF-8 text") from exc
            elif isinstance(raw_content, str):
                content_text = raw_content
            else:
                raise ValueError("Research source requires actual UTF-8 content or bytes")
            if not content_text.strip() or "\x00" in content_text:
                raise ValueError("Research source content must be nonempty text without NUL bytes")
            encoded = content_text.encode("utf-8")
            if not 1 <= len(encoded) <= MAX_EXCERPT_BYTES:
                raise ValueError("Research source content exceeds 32 KiB limit")
            total_bytes += len(encoded)
            if total_bytes > MAX_CHANNEL_BYTES:
                raise ValueError("Research channel content exceeds 256 KiB limit")
            content_sha = hashlib.sha256(encoded).hexdigest()
            if "sha256" in src and src["sha256"] != content_sha:
                raise ValueError("Caller-supplied source digest does not match actual content bytes")
            normalized_sources.append({"id": source_id, "sha256": content_sha})
            source_rows.append((idx, source_id, title, content_sha, content_text, len(encoded)))

        receipt_envelope = {
            "schema": "cochem-research-channel-receipt/4.2.8",
            "research_id": research_id,
            "channel": channel,
            "query": query_text,
            "status": status,
            "sources": normalized_sources,
        }
        receipt_sha256 = digest(receipt_envelope)
        sources_json = json.dumps(normalized_sources, sort_keys=True, allow_nan=False)

        with self._write() as conn:
            req = conn.execute(
                "SELECT * FROM research428_requests WHERE research_id=?",
                (research_id,),
            ).fetchone()
            if req is None:
                raise ValueError("Cannot record channel for unregistered research_id")
            pub = conn.execute(
                "SELECT 1 FROM research428_published WHERE research_id=?",
                (research_id,),
            ).fetchone()
            existing = conn.execute(
                "SELECT * FROM research428_channel_receipts WHERE research_id=? AND channel=?",
                (research_id, channel),
            ).fetchone()
            if existing is not None:
                if (
                    existing["query"] != query_text
                    or existing["status"] != status
                    or existing["receipt_sha256"] != receipt_sha256
                    or existing["sources_json"] != sources_json
                ):
                    raise ValueError("Recorded research channel receipt is immutable; create a new intent for retry")
                return {
                    "query": existing["query"],
                    "status": existing["status"],
                    "receipt_sha256": existing["receipt_sha256"],
                    "sources": json.loads(existing["sources_json"]),
                }
            if pub is not None:
                raise ValueError("Published research receipt is immutable")

            conn.execute(
                "INSERT INTO research428_channel_receipts VALUES(?,?,?,?,?,?,?)",
                (research_id, channel, query_text, status, ts, receipt_sha256, sources_json),
            )
            for idx, source_id, title, content_sha, content_text, byte_len in source_rows:
                conn.execute(
                    "INSERT INTO research428_sources VALUES(?,?,?,?,?,?,?,?)",
                    (research_id, channel, idx, source_id, title, content_sha, content_text, byte_len),
                )

        return {
            "query": query_text,
            "status": status,
            "receipt_sha256": receipt_sha256,
            "sources": normalized_sources,
        }

    def _assemble_verified(self, conn: sqlite3.Connection, research_id: str) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
        channel_rows = {
            row["channel"]: dict(row)
            for row in conn.execute(
                "SELECT * FROM research428_channel_receipts WHERE research_id=?",
                (research_id,),
            ).fetchall()
        }
        if set(channel_rows) != set(REQUIRED_CHANNELS):
            raise ValueError("Incomplete research collection; all three channels are required before publication")

        channels: dict[str, Any] = {}
        excerpts: dict[str, list[dict[str, Any]]] = {}
        for channel in REQUIRED_CHANNELS:
            crow = channel_rows[channel]
            expected_sources = json.loads(crow["sources_json"])
            srows = conn.execute(
                "SELECT * FROM research428_sources WHERE research_id=? AND channel=? ORDER BY position ASC",
                (research_id, channel),
            ).fetchall()
            if len(srows) != len(expected_sources):
                raise ValueError("Stored source excerpt count differs from channel receipt")
            channel_excerpts: list[dict[str, Any]] = []
            for expected, srow in zip(expected_sources, srows, strict=True):
                content_text = srow["content_text"]
                if not isinstance(content_text, str):
                    raise ValueError("Stored source content is corrupted")
                encoded = content_text.encode("utf-8")
                actual_sha = hashlib.sha256(encoded).hexdigest()
                if (
                    srow["source_id"] != expected["id"]
                    or srow["content_sha256"] != expected["sha256"]
                    or actual_sha != expected["sha256"]
                    or len(encoded) != srow["byte_length"]
                ):
                    raise ValueError("Stored research source content failed SHA256 integrity verification")
                channel_excerpts.append(
                    {
                        "id": srow["source_id"],
                        "title": srow["title"],
                        "sha256": actual_sha,
                        "content": content_text,
                    }
                )
            channels[channel] = {
                "query": crow["query"],
                "status": crow["status"],
                "receipt_sha256": crow["receipt_sha256"],
                "sources": expected_sources,
            }
            excerpts[channel] = channel_excerpts

        validate_research(channels)
        validate_research_excerpts(channels, excerpts)
        return channels, excerpts

    def publish(self, research_id: str, *, clock=time.time) -> dict[str, Any]:
        """Atomically publish completed three-channel research evidence for `PlanningJournal`."""
        _id(research_id)
        now = float(clock())
        with self._write() as conn:
            req = conn.execute(
                "SELECT * FROM research428_requests WHERE research_id=?",
                (research_id,),
            ).fetchone()
            if req is None:
                raise ValueError("Unknown research_id")
            channels, excerpts = self._assemble_verified(conn, research_id)
            channels_json = json.dumps(channels, sort_keys=True, allow_nan=False)
            existing = conn.execute(
                "SELECT * FROM research428_published WHERE research_id=?",
                (research_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["intent_sha256"] != req["intent_sha256"]
                    or existing["srs_sha256"] != req["srs_sha256"]
                    or existing["channels_json"] != channels_json
                ):
                    raise ValueError("Published research receipt cannot be rewritten")
            else:
                conn.execute(
                    "INSERT INTO research428_published VALUES(?,?,?,?,?)",
                    (research_id, req["intent_sha256"], req["srs_sha256"], channels_json, now),
                )
            return {
                "intent_sha256": req["intent_sha256"],
                "channels": channels,
                "excerpts": excerpts,
            }

    def load_for_journal(self, research_id: str) -> dict[str, Any] | None:
        """Trusted `search_result` port callable for `PlanningJournal`."""
        _id(research_id)
        with self._write() as conn:
            pub = conn.execute(
                "SELECT * FROM research428_published WHERE research_id=?",
                (research_id,),
            ).fetchone()
            if pub is None:
                return None
            channels, excerpts = self._assemble_verified(conn, research_id)
            if json.dumps(channels, sort_keys=True, allow_nan=False) != pub["channels_json"]:
                raise ValueError("Published research channels differ from verified channel receipts")
            return {
                "intent_sha256": pub["intent_sha256"],
                "channels": channels,
                "excerpts": excerpts,
            }
