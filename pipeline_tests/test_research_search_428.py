"""Tests for real internet and scholarly search adapters (`P428-07`)."""
from __future__ import annotations

import hashlib
import json

import pytest

from cochem_pipeline.research_evidence_428 import ResearchEvidenceStore
from cochem_pipeline.research_search_428 import (
    HttpResponseFixture,
    ResearchSearchClient,
    ResearchSearchConfig,
    validate_public_https_url,
)


def _public_resolver(host: str) -> list[str]:
    mapping = {
        "en.wikipedia.org": ["208.80.154.224"],
        "api.openalex.org": ["104.18.8.12"],
        "export.arxiv.org": ["128.84.21.203"],
    }
    return mapping.get(host, ["93.184.216.34"])


def test_internet_and_papers_valid_responses_produce_verified_evidence(tmp_path):
    def transport(url: str, headers: dict[str, str], timeout: float, max_bytes: int) -> HttpResponseFixture:
        if "en.wikipedia.org" in url:
            body = json.dumps(
                {
                    "query": {
                        "search": [
                            {
                                "pageid": 12345,
                                "title": "Write-ahead logging",
                                "snippet": 'In computer science, <span class="searchmatch">write-ahead logging</span> (WAL) provides atomicity and durability.',
                            }
                        ]
                    }
                }
            ).encode("utf-8")
            return HttpResponseFixture(status_code=200, body=body, url=url)
        if "api.openalex.org" in url:
            body = json.dumps(
                {
                    "results": [
                        {
                            "id": "https://openalex.org/W2741809807",
                            "doi": "https://doi.org/10.1145/123456.7890",
                            "title": "ARIES: A Transaction Recovery Method",
                            "publication_year": 1992,
                            "abstract_inverted_index": {
                                "Concurrent": [0],
                                "recovery": [1],
                                "using": [2],
                                "write-ahead": [3],
                                "logging.": [4],
                            },
                        }
                    ]
                }
            ).encode("utf-8")
            return HttpResponseFixture(status_code=200, body=body, url=url)
        raise AssertionError(f"Unexpected URL {url}")

    client = ResearchSearchClient(
        ResearchSearchConfig(polite_mailto="test@example.org"),
        transport=transport,
        resolver=_public_resolver,
    )
    web = client.search_internet("write-ahead logging")
    assert web["status"] == "found"
    assert len(web["sources"]) == 1
    assert web["sources"][0]["id"] == "https://en.wikipedia.org/?curid=12345"
    assert "<span" not in web["sources"][0]["content"]
    assert (
        hashlib.sha256(web["sources"][0]["content"].encode("utf-8")).hexdigest()
        == web["sources"][0]["sha256"]
    )

    papers = client.search_papers("write-ahead logging")
    assert papers["status"] == "found"
    assert len(papers["sources"]) == 1
    assert papers["sources"][0]["id"] == "https://doi.org/10.1145/123456.7890"
    assert "Concurrent recovery using write-ahead logging." in papers["sources"][0]["content"]
    assert (
        hashlib.sha256(papers["sources"][0]["content"].encode("utf-8")).hexdigest()
        == papers["sources"][0]["sha256"]
    )

    # Verify compatibility with ResearchEvidenceStore
    store = ResearchEvidenceStore(tmp_path / "research.sqlite")
    intent = {
        "schema": "cochem-planning-intent/4.2.8",
        "task_id": "t1",
        "version": 1,
        "stage": "RESEARCH",
        "state_sha256": "a" * 64,
        "catalog_sha256": "b" * 64,
        "srs_sha256": "c" * 64,
        "execution_authorized": False,
        "action": "controller_research",
        "channels": ["internet", "wiki_rag", "papers"],
        "query": "write-ahead logging",
    }
    req = store.register_request(intent)
    res_id = req["research_id"]
    store.record_channel(res_id, "internet", query=web["query"], status=web["status"], sources=web["sources"])
    store.record_channel(res_id, "wiki_rag", query=web["query"], status="no_results", sources=[])
    store.record_channel(res_id, "papers", query=papers["query"], status=papers["status"], sources=papers["sources"])
    published = store.publish(res_id)
    assert published["channels"]["internet"]["status"] == "found"
    assert published["channels"]["papers"]["status"] == "found"


def test_empty_results_return_no_results_distinct_from_unavailable():
    def transport(url: str, headers: dict[str, str], timeout: float, max_bytes: int) -> HttpResponseFixture:
        if "en.wikipedia.org" in url:
            return HttpResponseFixture(status_code=200, body=b'{"query": {"search": []}}', url=url)
        return HttpResponseFixture(status_code=200, body=b'{"results": []}', url=url)

    client = ResearchSearchClient(transport=transport, resolver=_public_resolver)
    web = client.search_internet("nonexistent_token_xyz_987")
    papers = client.search_papers("nonexistent_token_xyz_987")
    assert web["status"] == "no_results" and web["sources"] == []
    assert papers["status"] == "no_results" and papers["sources"] == []


@pytest.mark.parametrize(
    "failure_mode",
    ["http_429", "http_503", "timeout", "malformed_json", "oversize"],
)
def test_429_5xx_timeout_malformed_and_oversize_become_unavailable(failure_mode):
    def transport(url: str, headers: dict[str, str], timeout: float, max_bytes: int) -> HttpResponseFixture:
        if failure_mode == "http_429":
            return HttpResponseFixture(status_code=429, body=b'{"error": "rate limit"}', url=url)
        if failure_mode == "http_503":
            return HttpResponseFixture(status_code=503, body=b"Service Unavailable", url=url)
        if failure_mode == "timeout":
            raise TimeoutError("Read timed out")
        if failure_mode == "malformed_json":
            return HttpResponseFixture(status_code=200, body=b"{not-valid-json", url=url)
        if failure_mode == "oversize":
            return HttpResponseFixture(status_code=200, body=b"x" * (max_bytes + 10), url=url)
        raise AssertionError(failure_mode)

    client = ResearchSearchClient(
        ResearchSearchConfig(max_response_bytes=2048),
        transport=transport,
        resolver=_public_resolver,
    )
    res_web = client.search_internet("test query")
    res_papers = client.search_papers("test query")
    assert res_web["status"] == "unavailable" and res_web["sources"] == []
    assert res_papers["status"] == "unavailable" and res_papers["sources"] == []


def test_redirects_and_private_destinations_enforced():
    # 1. Valid 1-hop HTTPS redirect to allowed host succeeds
    def transport_ok_redirect(url: str, headers: dict[str, str], timeout: float, max_bytes: int) -> HttpResponseFixture:
        if "hop=1" not in url:
            return HttpResponseFixture(
                status_code=302,
                body=b"",
                headers={"location": "https://api.openalex.org/works?search=test&hop=1"},
                url=url,
            )
        return HttpResponseFixture(status_code=200, body=b'{"results": []}', url=url)

    client_ok = ResearchSearchClient(transport=transport_ok_redirect, resolver=_public_resolver)
    assert client_ok.search_papers("test")["status"] == "no_results"

    # 2. Redirect to unallowed or non-HTTPS or private destination is blocked
    for bad_location in (
        "http://api.openalex.org/works",
        "https://127.0.0.1/admin",
        "https://169.254.169.254/latest/meta-data/",
        "https://untrusted.example.com/works",
    ):
        def transport_bad(url: str, headers: dict[str, str], timeout: float, max_bytes: int) -> HttpResponseFixture:
            return HttpResponseFixture(
                status_code=302,
                body=b"",
                headers={"location": bad_location},
                url=url,
            )

        client_bad = ResearchSearchClient(transport=transport_bad, resolver=_public_resolver)
        res = client_bad.search_papers("test")
        assert res["status"] == "unavailable"
        assert res["error_code"] == "BLOCKED_OR_INVALID_DESTINATION"

    # 3. DNS resolution returning private/loopback IP is rejected
    for private_ip in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1"):
        with pytest.raises(ValueError, match="non-public"):
            validate_public_https_url(
                "https://api.openalex.org/works",
                resolver=lambda _host: [private_ip],
            )
