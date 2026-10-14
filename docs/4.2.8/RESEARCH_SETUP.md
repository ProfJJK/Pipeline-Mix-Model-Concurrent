# Pipeline 4.2.8 Runtime Research Setup (`P428-07`)

## Overview

Pipeline 4.2.8 executes controller-owned three-channel research (`internet`,
`wiki_rag`, `papers`) for tasks with complexity `4..10` and at `10/20/30`
quality-failure dossier boundaries. The runtime never relies on tools available
only inside an interactive developer chat session.

## Supported Runtime Channels & Default Endpoints

1. **`internet` Channel (`ResearchSearchClient.search_internet`)**
   - Default endpoint: `https://en.wikipedia.org/w/api.php` (MediaWiki JSON search API)
   - Paid API key required: **No**
   - Optional configuration: Operator may configure an alternate HTTPS JSON search
     endpoint via `ResearchSearchConfig(internet_endpoint=..., allowed_hosts=...)`.

2. **`papers` Channel (`ResearchSearchClient.search_papers`)**
   - Default endpoint: `https://api.openalex.org/works` (OpenAlex Works REST API)
   - Paid API key required: **No**
   - Optional polite pool parameter: `polite_mailto` in `ResearchSearchConfig`.
   - Reconstructs full text abstracts from `abstract_inverted_index` (or `abstract`)
     and records DOI or canonical OpenAlex Work URLs as source identifiers.

3. **`wiki_rag` Channel (`ResearchRuntime.collect_wiki_rag` in `research_runtime_428.py`)**
   - Uses the local `KnowledgeService` and `KnowledgeAuthority` (`cochem_pipeline.knowledge`)
     bound to the verified `v4.1.2_manifest.json` generation.
   - Performs no external network requests.

## Security, SSRF, Redirect, and Size Bounds

- **HTTPS Only:** Non-HTTPS schemes (`http://`, `file://`, `ftp://`) and URLs with
  embedded credentials (`user:pass@host`) are rejected before any socket opens.
- **Host Allowlist:** Only hosts listed in `ResearchSearchConfig.allowed_hosts`
  (`en.wikipedia.org`, `www.wikidata.org`, `api.openalex.org`, `export.arxiv.org`,
  `api.crossref.org` by default) are permitted.
- **Public IP Verification (SSRF Protection):** Every target host is resolved and
  checked via `ipaddress.ip_address`. Loopback (`127.0.0.0/8`, `::1`), private
  (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `fc00::/7`), link-local
  (`169.254.0.0/16`, `fe80::/10`), multicast, unspecified, and reserved addresses
  are blocked on both initial requests and any HTTP redirects.
- **Redirect Cap:** At most `2` HTTPS redirects (`301`, `302`, `303`, `307`, `308`)
  are followed, and every redirect hop re-validates the destination against
  `allowed_hosts` and public IP rules.
- **Response & Excerpt Bounds:**
  - Raw HTTP response body: `<= 512 KiB` (`524,288` bytes)
  - Per-source UTF-8 excerpt: `<= 32 KiB` (`32,768` bytes)
  - Per-channel total excerpts: `<= 256 KiB` (`262,144` bytes) across at most `30` sources
- **Non-Interactive Failure Semantics:**
  - HTTP `429`, `5xx`, timeouts, TLS errors, malformed JSON, oversize responses,
    or blocked redirects return `status='unavailable'` with `sources=[]` and never
    prompt or masquerade as `no_results`.
  - Genuine empty search results (`HTTP 200` with zero matching entries) return
    `status='no_results'` with `sources=[]`.
