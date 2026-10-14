"""Real internet and scholarly search adapters with strict SSRF/size/timeout bounds (`P428-07`).

Provides controller-owned runtime search clients for the `internet` and `papers`
channels without depending on interactive chat tools or paid API keys by default:
- `internet` channel: HTTPS JSON search adapter (defaults to MediaWiki/Wikipedia
  API `en.wikipedia.org`, or operator-configured HTTPS search endpoint).
- `papers` channel: HTTPS OpenAlex Works API (`api.openalex.org`) with inverted-index
  abstract reconstruction and DOI/OpenAlex URL citation identifiers.
- Enforces HTTPS-only, allowed-host pinning, public-IP resolution (rejecting
  loopback, private, link-local, multicast, and unspecified addresses), bounded
  redirects (`<= 2`), bounded response size (`<= 512 KiB`), and per-source (`<= 32 KiB`)
  and per-channel (`<= 256 KiB`) excerpt budgets.
- Timeouts, HTTP 429/5xx, TLS errors, oversize payloads, malformed JSON, and
  blocked redirects produce durable `status='unavailable'` outcomes with no prompt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import html
import ipaddress
import json
import re
import socket
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request

from .research_evidence_428 import (
    MAX_CHANNEL_BYTES,
    MAX_EXCERPT_BYTES,
    MAX_SOURCES_PER_CHANNEL,
)
from .workflow_428 import _text


DEFAULT_INTERNET_ENDPOINT = "https://en.wikipedia.org/w/api.php"
DEFAULT_PAPERS_ENDPOINT = "https://api.openalex.org/works"
DEFAULT_ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "en.wikipedia.org",
        "www.wikidata.org",
        "api.openalex.org",
        "export.arxiv.org",
        "api.crossref.org",
    }
)
MAX_HTTP_RESPONSE_BYTES = 512 * 1024
MAX_REDIRECTS = 2
_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class HttpResponseFixture:
    status_code: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
    url: str = ""


@dataclass(frozen=True)
class ResearchSearchConfig:
    internet_endpoint: str = DEFAULT_INTERNET_ENDPOINT
    papers_endpoint: str = DEFAULT_PAPERS_ENDPOINT
    allowed_hosts: frozenset[str] = DEFAULT_ALLOWED_HOSTS
    timeout_seconds: float = 10.0
    max_results_per_channel: int = 5
    max_response_bytes: int = MAX_HTTP_RESPONSE_BYTES
    max_redirects: int = MAX_REDIRECTS
    user_agent: str = "CoChemPipeline/4.2.8 (https://github.com/ProfJJK/Pipeline-Mix-Model-Concurrent)"
    polite_mailto: str | None = None

    def __post_init__(self):
        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            raise ValueError("Research search timeout_seconds must be in (0, 60]")
        if not 1 <= self.max_results_per_channel <= MAX_SOURCES_PER_CHANNEL:
            raise ValueError("max_results_per_channel must be in 1..30")
        if not 1024 <= self.max_response_bytes <= 2 * 1024 * 1024:
            raise ValueError("max_response_bytes must be between 1 KiB and 2 MiB")
        if not 0 <= self.max_redirects <= 5:
            raise ValueError("max_redirects must be in 0..5")


def _default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    addrs: list[str] = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr and isinstance(sockaddr[0], str):
            addrs.append(sockaddr[0])
    return addrs


def validate_public_https_url(
    url: str,
    *,
    allowed_hosts: frozenset[str] = DEFAULT_ALLOWED_HOSTS,
    resolver: Callable[[str], list[str]] = _default_resolver,
) -> urllib.parse.ParseResult:
    """Ensure `url` is HTTPS, in `allowed_hosts`, and resolves strictly to global public IPs."""
    if not isinstance(url, str) or not url.strip() or "\x00" in url or len(url) > 2048:
        raise ValueError("Invalid research URL")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Research URL must use https scheme")
    if parsed.username or parsed.password:
        raise ValueError("Research URL must not embed credentials")
    host = (parsed.hostname or "").strip().lower()
    if not host or host not in allowed_hosts:
        raise ValueError(f"Research host {host!r} is not in allowed_hosts")

    # Check if hostname is already an IP literal
    try:
        ip_literal = ipaddress.ip_address(host)
    except ValueError:
        ip_literal = None

    if ip_literal is not None:
        ips = [ip_literal]
    else:
        resolved = resolver(host)
        if not resolved:
            raise ValueError(f"Research host {host!r} resolved to no addresses")
        ips = [ipaddress.ip_address(addr) for addr in resolved]

    for ip_obj in ips:
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
            or ip_obj.is_reserved
        ):
            raise ValueError(f"Research host {host!r} resolved to non-public address {ip_obj}")
    return parsed


def _strip_html(raw: str) -> str:
    cleaned = html.unescape(_HTML_TAG_RE.sub(" ", raw))
    return re.sub(r"\s+", " ", cleaned).strip()


def _reconstruct_openalex_abstract(inverted_index: Any) -> str:
    if not isinstance(inverted_index, dict) or not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    total_tokens = 0
    for word, indices in inverted_index.items():
        if not isinstance(word, str) or not isinstance(indices, list):
            continue
        for pos in indices:
            if type(pos) is int and 0 <= pos <= 10000:
                positions.append((pos, word))
                total_tokens += 1
                if total_tokens > 4000:
                    break
        if total_tokens > 4000:
            break
    if not positions:
        return ""
    positions.sort(key=lambda item: item[0])
    return " ".join(word for _, word in positions).strip()


def _truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    clipped = encoded[:max_bytes].decode("utf-8", errors="ignore").strip()
    return clipped


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_http_transport(url: str, headers: dict[str, str], timeout: float, max_bytes: int) -> HttpResponseFixture:
    opener = urllib.request.build_opener(_NoRedirectHandler)
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read(max_bytes + 1)
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            return HttpResponseFixture(
                status_code=int(resp.status),
                body=raw,
                headers=resp_headers,
                url=url,
            )
    except urllib.error.HTTPError as exc:
        resp_headers = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
        body = exc.read(4096) if exc.fp is not None else b""
        return HttpResponseFixture(
            status_code=int(exc.code),
            body=body,
            headers=resp_headers,
            url=url,
        )


class ResearchSearchClient:
    """Controller-owned HTTPS search client for `internet` and `papers` channels."""

    def __init__(
        self,
        config: ResearchSearchConfig | None = None,
        *,
        transport: Callable[[str, dict[str, str], float, int], HttpResponseFixture] | None = None,
        resolver: Callable[[str], list[str]] | None = None,
    ):
        self.config = config or ResearchSearchConfig()
        self._transport = transport or _default_http_transport
        self._resolver = resolver or _default_resolver

    def _fetch_json(self, initial_url: str) -> tuple[dict[str, Any] | None, str | None]:
        current_url = initial_url
        headers = {
            "Accept": "application/json",
            "User-Agent": self.config.user_agent,
        }
        for hop in range(self.config.max_redirects + 1):
            try:
                validate_public_https_url(
                    current_url,
                    allowed_hosts=self.config.allowed_hosts,
                    resolver=self._resolver,
                )
            except Exception:
                return None, "BLOCKED_OR_INVALID_DESTINATION"

            try:
                resp = self._transport(
                    current_url,
                    headers,
                    self.config.timeout_seconds,
                    self.config.max_response_bytes,
                )
            except (TimeoutError, socket.timeout):
                return None, "TIMEOUT"
            except Exception:
                return None, "TRANSPORT_ERROR"

            if resp.status_code in (301, 302, 303, 307, 308):
                if hop >= self.config.max_redirects:
                    return None, "TOO_MANY_REDIRECTS"
                location = resp.headers.get("location") or resp.headers.get("Location")
                if not location:
                    return None, "REDIRECT_MISSING_LOCATION"
                current_url = urllib.parse.urljoin(current_url, location)
                continue

            if resp.status_code == 429:
                return None, "HTTP_429_RATE_LIMITED"
            if resp.status_code != 200:
                return None, f"HTTP_{resp.status_code}"

            if len(resp.body) > self.config.max_response_bytes:
                return None, "RESPONSE_OVERSIZE"

            try:
                decoded = json.loads(resp.body.decode("utf-8"))
            except Exception:
                return None, "MALFORMED_JSON"
            if not isinstance(decoded, dict):
                return None, "JSON_NOT_OBJECT"
            return decoded, None

        return None, "TOO_MANY_REDIRECTS"

    def search_internet(self, query: str) -> dict[str, Any]:
        """Execute bounded internet documentation/reference search."""
        query_text = _text(query, "Research query", 2000)
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query_text,
            "srlimit": str(self.config.max_results_per_channel),
            "utf8": "1",
            "format": "json",
        }
        url = f"{self.config.internet_endpoint}?{urllib.parse.urlencode(params)}"
        payload, err = self._fetch_json(url)
        if err is not None or payload is None:
            return {
                "channel": "internet",
                "query": query_text,
                "status": "unavailable",
                "sources": [],
                "error_code": err or "UNAVAILABLE",
            }

        # Support MediaWiki query.search or generic results list
        raw_items: Any = None
        if isinstance(payload.get("query"), dict) and isinstance(payload["query"].get("search"), list):
            raw_items = payload["query"]["search"]
        elif isinstance(payload.get("results"), list):
            raw_items = payload["results"]
        if not isinstance(raw_items, list):
            return {
                "channel": "internet",
                "query": query_text,
                "status": "unavailable",
                "sources": [],
                "error_code": "UNRECOGNIZED_SEARCH_SCHEMA",
            }

        sources: list[dict[str, Any]] = []
        total_bytes = 0
        seen_ids: set[str] = set()
        for item in raw_items[: self.config.max_results_per_channel]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            snippet_raw = str(item.get("snippet") or item.get("content") or item.get("text") or "").strip()
            snippet = _strip_html(snippet_raw)
            if not title or not snippet:
                continue
            if isinstance(item.get("url"), str) and item["url"].startswith("https://"):
                source_id = item["url"][:2048]
            elif item.get("pageid") is not None:
                source_id = f"https://en.wikipedia.org/?curid={item['pageid']}"
            else:
                slug = urllib.parse.quote(title.replace(" ", "_"))
                source_id = f"https://en.wikipedia.org/wiki/{slug}"[:2048]
            if source_id in seen_ids:
                continue
            seen_ids.add(source_id)

            excerpt_text = _truncate_utf8(f"{title}: {snippet}", MAX_EXCERPT_BYTES)
            encoded = excerpt_text.encode("utf-8")
            if not encoded or total_bytes + len(encoded) > MAX_CHANNEL_BYTES:
                break
            total_bytes += len(encoded)
            sources.append(
                {
                    "id": source_id,
                    "title": title[:512],
                    "content": excerpt_text,
                    "sha256": hashlib.sha256(encoded).hexdigest(),
                }
            )

        return {
            "channel": "internet",
            "query": query_text,
            "status": "found" if sources else "no_results",
            "sources": sources,
        }

    def search_papers(self, query: str) -> dict[str, Any]:
        """Execute bounded scholarly literature search via OpenAlex Works API."""
        query_text = _text(query, "Research query", 2000)
        params: dict[str, str] = {
            "search": query_text,
            "per-page": str(self.config.max_results_per_channel),
        }
        if self.config.polite_mailto:
            params["mailto"] = self.config.polite_mailto
        url = f"{self.config.papers_endpoint}?{urllib.parse.urlencode(params)}"
        payload, err = self._fetch_json(url)
        if err is not None or payload is None:
            return {
                "channel": "papers",
                "query": query_text,
                "status": "unavailable",
                "sources": [],
                "error_code": err or "UNAVAILABLE",
            }

        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            return {
                "channel": "papers",
                "query": query_text,
                "status": "unavailable",
                "sources": [],
                "error_code": "UNRECOGNIZED_PAPERS_SCHEMA",
            }

        sources: list[dict[str, Any]] = []
        total_bytes = 0
        seen_ids: set[str] = set()
        for item in raw_results[: self.config.max_results_per_channel]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("display_name") or "").strip()
            source_id = str(item.get("doi") or item.get("id") or "").strip()
            if not title or not source_id:
                continue
            source_id = source_id[:2048]
            if source_id in seen_ids:
                continue
            seen_ids.add(source_id)

            abstract = ""
            if isinstance(item.get("abstract"), str) and item["abstract"].strip():
                abstract = item["abstract"].strip()
            elif "abstract_inverted_index" in item:
                abstract = _reconstruct_openalex_abstract(item.get("abstract_inverted_index"))
            pub_year = item.get("publication_year")
            header = f"{title} ({pub_year})" if pub_year else title
            body = f"{header}: {abstract}" if abstract else header
            excerpt_text = _truncate_utf8(body, MAX_EXCERPT_BYTES)
            encoded = excerpt_text.encode("utf-8")
            if not encoded or total_bytes + len(encoded) > MAX_CHANNEL_BYTES:
                break
            total_bytes += len(encoded)
            sources.append(
                {
                    "id": source_id,
                    "title": title[:512],
                    "content": excerpt_text,
                    "sha256": hashlib.sha256(encoded).hexdigest(),
                }
            )

        return {
            "channel": "papers",
            "query": query_text,
            "status": "found" if sources else "no_results",
            "sources": sources,
        }
