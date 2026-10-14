# Pipeline 4.2.8 Integration Contracts and Shared-File Ownership

**Baseline Commit:** `b11e1ad` (following `7815b9aa30ffed9ca700f2119736160f3b7ee923`)
**Scope:** Freeze cross-lane interfaces, request/result schemas, lineage semantics, trust/size/idempotency/recovery rules, and shared-file ownership for `P428-01` through `P428-27`.

---

## 1. Cross-Boundary Principles

1. **Canonical Digests & Serialization**
   - Every cross-boundary payload is hashed with `sha256` over UTF-8 canonical JSON (`json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`).
   - Digests use lowercase hex (`64` ASCII hex chars) or `sha256:<64-hex>` where prefixed by existing journal conventions.
2. **Trust & Origin Separation**
   - **Untrusted Agent / Model Output:** May propose draft content, WBS child structures, or code diffs, and may invoke agent-accessible status/intake endpoints, but can **never** mint a `ResearchEvidenceReceipt`, `OwnerApprovalReceipt`, `CatalogActivationReceipt`, `ExecutionArtifactReceipt`, or `CompletionAuditReceipt`.
   - **Trusted Controller / Supervisor Ports:** Only controller-internal adapters that verify physical receipts (HTTP response bytes, SQLite catalog authority, human approval token/broker, or process/workspace execution artifacts) may publish to trusted journal ports.
   - **Trusted Human Broker (`owner_approval_428.py`):** Uses a distinct human decision secret/challenge bound to `(task_id, srs_version, plan_digest, architecture_digest, srs_digest)`. The shared controller bearer token (`COCHEM_API_KEY`) is **rejected** as sole proof of human approval.
3. **No Cross-DB Best-Effort Double Writes**
   - Every transition across `PlanningJournal`, `JobStore`, `RoutingStore`, `AttemptLedger`, and `RepairQueue` uses an explicit SQLite `BEGIN IMMEDIATE` transaction on the owning database plus a durable idempotent outbox/reconciliation key (`idempotency_key` / `transition_id`) so any crash between two SQLite files is deterministically replayed on the next pump tick without duplicate job creation or double attempt charging.
4. **Preserve Chapter 06 Execution Authority**
   - All native executions flow through the existing four-slot pool, RAM-disk workspace isolation, immutable policy captures, and cleanup proof. New 4.2.8 modules materialize jobs into `JobStore` and reconcile outcomes; they do not spawn side-channel worker pools.

---

## 2. Ordinary WBS Parentage vs. Fracture Lineage

Pipeline 4.2.8 distinguishes two parent-child relationships that must never be conflated:

| Dimension | Ordinary WBS Decomposition (`P428-12`) | Failure Fracture Decomposition (`P428-17`) |
| --- | --- | --- |
| **Relationship Kind** | `WBS_CHILD` | `FRACTURE_CHILD` |
| **Parent Field** | `wbs_parent_task_id` | `fracture_parent_task_id` |
| **Lineage Root Field** | `attempt_lineage_id = child_task_id` (own independent budget) | `attempt_lineage_id = parent.attempt_lineage_id` (inherits failing lineage) |
| **Quality Failure Counter** | Starts at `0/30` for each WBS child independently | Shares the failing task's cumulative counter (`10..29` of `30`) |
| **Concurrency** | Up to 4 independent WBS children may run concurrently across the 4 shared slots | Fracture children of a single `attempt_lineage_id` share the lineage budget; concurrent fracture fragments use fenced attempt reservations so cumulative failures never exceed 30 or reset |
| **Routing / Pivot Floor** | Classified individually (`task_type`, `complexity_tier` 1–10); uses standard tier floor | Lower-complexity helper fragments (`complexity_tier < parent.complexity_tier`) may use their tier route, **except** the core failed scope and fracture assembly/integration node MUST retain the escalated pivot model/effort floor and distinct-model constraint |
| **Owner Approval Rule** | Required before dispatch if `child.complexity_tier >= 8` and not covered by an existing valid approval for the exact scope/revision | Required before dispatch if any fracture child is assessed at `complexity_tier >= 8` or widens scope beyond the approved parent SRS |

---

## 3. Concrete Schemas & Boundary Contracts

### 3.1 Research Request, Receipt, and Bounded Content (`Lane Q`: `P428-06`..`P428-08`)

- **Schema: `ResearchRequestRecord`**
  - `request_id`: `str` (`req-<task_id>-r<srs_revision>-<channel>`)
  - `task_id`: `str`
  - `srs_revision`: `int` (>= 1)
  - `intent_digest`: `str` (64-hex SHA-256 of canonical `(task_id, srs_revision, channel, normalized_query, scope_digest)`)
  - `channel`: `Literal["internet", "papers", "wiki"]`
  - `query_text`: `str` (1..512 chars)
  - `created_at_utc`: `str` (ISO-8601 UTC)
- **Schema: `ResearchSourceExcerpt`**
  - `source_id`: `str` (stable URI, DOI/OpenAlex/Crossref ID, or `wiki:<doc_id>@<generation_id>`)
  - `title`: `str` (max 300 chars)
  - `locator`: `str` (URL, DOI URL, or wiki path)
  - `published_or_version`: `str` (max 64 chars)
  - `raw_bytes_sha256`: `str` (64-hex SHA-256 of exact fetched payload bytes)
  - `excerpt_text`: `str` (1..2048 UTF-8 chars, sanitized, exact substring/normalized extraction from `raw_bytes`)
  - `excerpt_sha256`: `str` (64-hex SHA-256 of UTF-8 `excerpt_text`)
- **Schema: `ResearchReceiptRecord`**
  - `receipt_id`: `str`
  - `request_id`: `str`
  - `task_id`: `str`
  - `srs_revision`: `int`
  - `channel`: `Literal["internet", "papers", "wiki"]`
  - `intent_digest`: `str`
  - `status`: `Literal["ok", "no_results", "unavailable"]`
  - `excerpts`: `tuple[ResearchSourceExcerpt, ...]` (max 8 excerpts per channel; total excerpt text per channel <= 8,192 bytes; total prompt research bundle across 3 channels <= 16,384 bytes)
  - `bundle_sha256`: `str` (64-hex SHA-256 over canonical excerpts list)
  - `error_code`: `str | None` (populated when `status == "unavailable"`, e.g. `"HTTP_429"`, `"TIMEOUT"`, `"TLS_ERROR"`, `"WIKI_DRIFT"`)
  - `collected_at_utc`: `str`
- **Rules:**
  - **Origin/Trust:** Written only by `ResearchEvidenceStore` (`research_evidence_428.py`) from verified adapter responses (`research_search_428.py`, `research_runtime_428.py`).
  - **Size Bounds:** Max raw HTTP response read per source = `262,144` bytes (256 KiB); max stored excerpt per item = `2,048` bytes; max per-channel bundle = `8,192` bytes.
  - **Idempotency & Recovery:** Keyed by `(task_id, srs_revision, channel, intent_digest)`. Interrupted collection writes to a staging row/file and never publishes `status="ok"` or `status="no_results"` until raw bytes + excerpts + digests are fsynced/committed. Outages (`timeout`, `429`, `5xx`, DNS/TLS failure) record `status="unavailable"` with `backoff_until_utc` and never masquerade as `no_results`.

### 3.2 Human SRS Approval Request and Receipt (`Lane H`: `P428-09`..`P428-10`)

- **Schema: `OwnerApprovalChallenge`**
  - `challenge_id`: `str` (`appr-<task_id>-v<srs_version>`)
  - `task_id`: `str`
  - `complexity_tier`: `int` (8..10, or newly assessed high-tier child)
  - `srs_version`: `int`
  - `plan_digest`: `str` (64-hex)
  - `architecture_digest`: `str` (64-hex)
  - `srs_digest`: `str` (64-hex)
  - `combined_scope_digest`: `str` (64-hex over `(task_id, srs_version, plan_digest, architecture_digest, srs_digest)`)
  - `issued_at_utc`: `str`
  - `expires_at_utc`: `str`
- **Schema: `OwnerApprovalReceipt`**
  - `receipt_id`: `str`
  - `challenge_id`: `str`
  - `task_id`: `str`
  - `srs_version`: `int`
  - `combined_scope_digest`: `str`
  - `decision`: `Literal["approved", "rejected", "revision_requested"]`
  - `owner_identity`: `str` (non-empty human operator identifier)
  - `verification_method`: `Literal["human_broker_hmac", "local_owner_console_token"]`
  - `signature_hmac`: `str` (64-hex HMAC-SHA256 using owner broker secret distinct from `COCHEM_API_KEY`)
  - `notes`: `str` (max 4,096 chars)
  - `decided_at_utc`: `str`
- **Rules:**
  - **Origin/Trust:** `OwnerApprovalBroker` verifies the HMAC/token over `combined_scope_digest` before calling `PlanningJournal.apply_owner_approval()`. Requests carrying only `Authorization: Bearer <COCHEM_API_KEY>` or model output JSON are rejected with `OwnerApprovalAuthError`.
  - **Invalidation:** Any change to `srs_version`, `plan_digest`, `architecture_digest`, or `srs_digest` invalidates prior approvals for new dispatches; identical `(task_id, srs_version, combined_scope_digest)` reuses the existing valid approval idempotently.

### 3.3 Catalog Binding & Task Execution Node (`Lanes R & E`: `P428-02`..`P428-03`, `P428-11`..`P428-14`)

- **Schema: `AcceptedTaskProfileBinding`**
  - `generation_id`: `str`
  - `profile_id`: `str` (e.g. `"agy-argon-high"`, `"codex-gpt-5.4-xhigh"`)
  - `provider_family`: `str`
  - `cli_binary_path`: `str`
  - `cli_binary_sha256`: `str`
  - `model_slug`: `str`
  - `native_effort`: `str`
  - `host_accepted`: `bool` (true **only** when backed by a verified `CatalogActivationReceipt` / native acceptance receipt matching binary SHA-256 + model + effort)
  - `shared_pool_id`: `str`
- **Schema: `TaskExecutionNode`**
  - `node_id`: `str` (`node-<task_id>` for simple tasks, or `node-<parent_task_id>-<wbs_code>` for WBS microtasks)
  - `task_id`: `str`
  - `root_task_id`: `str`
  - `wbs_parent_task_id`: `str | None`
  - `fracture_parent_task_id`: `str | None`
  - `attempt_lineage_id`: `str`
  - `node_role`: `Literal["simple_execution", "wbs_fragment", "fracture_fragment", "assembly", "final_test"]`
  - `task_type`: `str` (one of the 11 canonical task types)
  - `complexity_tier`: `int` (1..10)
  - `srs_version`: `int`
  - `srs_digest`: `str`
  - `requirement_ids`: `tuple[str, ...]` (non-empty)
  - `deliverable_specs`: `tuple[str, ...]` (non-empty)
  - `audit_metrics`: `dict[str, str | int | float]`
  - `release_criteria`: `tuple[str, ...]` (non-empty)
  - `depends_on_node_ids`: `tuple[str, ...]` (DAG-validated, acyclic)
  - `selected_profile_id`: `str`
  - `idempotency_key`: `str` (`exec-<node_id>-v<srs_version>-a<attempt_no>`)
- **Schema: `TaskArtifactManifest`**
  - `artifact_id`: `str`
  - `node_id`: `str`
  - `task_id`: `str`
  - `job_id`: `str`
  - `attempt_no`: `int`
  - `project_id`: `str | None`
  - `files`: `tuple[ArtifactFileEntry, ...]` (`relative_path`, `sha256`, `size_bytes`, `kind`)
  - `manifest_sha256`: `str`
  - `verification_status`: `Literal["verified", "rejected"]`
  - `created_at_utc`: `str`
- **Rules:**
  - **Size Bounds:** Max files per manifest = `256`; max single staged non-code artifact = `1,048,576` bytes (1 MiB); path traversal (`..`, absolute paths, drive letters, Windows reparse points/symlinks) is strictly rejected.
  - **Completion Rule:** A simple task reaches `COMPLETED` only when its `JobStore` job succeeds AND `TaskArtifactManifest.verification_status == "verified"`. A decomposed root task reaches `COMPLETED` only when all `wbs_fragment`/`fracture_fragment` nodes, the explicit `assembly` node, and the explicit `final_test` node have verified manifests covering 100% of `requirement_ids` and `release_criteria`.

### 3.4 Attempt Outcome, Failure Dossier, Pivot, Fracture, and Locked Decisions (`Lane F`: `P428-15`..`P428-18`)

- **Schema: `FencedAttemptOutcome`**
  - `outcome_id`: `str` (`out-<job_id>-<lease_epoch>`)
  - `attempt_lineage_id`: `str`
  - `task_id`: `str`
  - `node_id`: `str`
  - `job_id`: `str`
  - `lease_epoch`: `int`
  - `profile_id`: `str`
  - `complexity_tier`: `int`
  - `outcome_class`: `Literal["success", "quality_failure", "availability_wait"]`
  - `failure_code`: `str | None`
  - `evidence_digest`: `str`
- **Schema: `FailureDossierRecord`**
  - `dossier_id`: `str` (`dossier-<attempt_lineage_id>-f<failure_count>`)
  - `attempt_lineage_id`: `str`
  - `task_id`: `str`
  - `failure_count`: `int` (`10`, `20`, or `30`)
  - `failed_profile_ids`: `tuple[str, ...]`
  - `error_signatures`: `tuple[str, ...]`
  - `research_receipt_ids`: `tuple[str, ...]` (bound to 3-channel research on the failure)
  - `recommended_action`: `Literal["higher_model_pivot", "task_fracture", "lock_for_owner"]`
  - `dossier_sha256`: `str`
- **Schema: `LockedTaskOwnerDecision`**
  - `decision_id`: `str`
  - `task_id`: `str`
  - `attempt_lineage_id`: `str`
  - `failure_count`: `int` (must be `30`)
  - `action`: `Literal["reapprove_plan", "narrow_scope", "assign_profile", "abort_task"]`
  - `assigned_profile_id`: `str | None`
  - `updated_scope_text`: `str | None`
  - `owner_receipt_id`: `str` (verified via `OwnerApprovalBroker`)
- **Rules:**
  - `availability_wait` (quota exhaustion, HTTP 429, auth hold, host RAM/slot deferral) **never** increments `AttemptLedger` quality failure count.
  - `quality_failure` increments `AttemptLedger` at most once per `(job_id, lease_epoch)`.
  - At `failure_count == 10`: freeze new standard dispatches for the lineage, collect 3-channel failure research, emit `FailureDossierRecord`, and pivot to a higher/different accepted model (`pivot_runtime_428.py`).
  - At `failure_count == 20` (or when already at the highest eligible model at 10): fracture into `FRACTURE_CHILD` nodes sharing `attempt_lineage_id` while keeping the core/assembly scope on the escalated model floor (`fracture_runtime_428.py`).
  - At `failure_count == 30`: transition lineage to `LOCKED`; no automatic retries or fractures can clear `LOCKED` without a verified `LockedTaskOwnerDecision`.

### 3.5 Completion Audit & Independent Tier-10 Repair (`Lanes A & O`: `P428-19`..`P428-21`)

- **Schema: `CompletionAuditReceipt`**
  - `audit_id`: `str` (`audit-<task_id>-<srs_version>`)
  - `task_id`: `str`
  - `sampled`: `bool`
  - `sampling_seed_digest`: `str` (deterministic SHA-256 over `(task_id, srs_digest, release_manifest_sha256)`)
  - `verdict`: `Literal["passed", "failed_defect", "not_sampled"]`
  - `checked_requirements`: `tuple[str, ...]`
  - `defect_codes`: `tuple[str, ...]`
  - `incident_id`: `str | None`
- **Schema: `RepairReservationRecord`**
  - `incident_id`: `str`
  - `fingerprint`: `str`
  - `repair_tier`: `int` (always `10`)
  - `selected_profile_id`: `str` (tier-10 maximum effort route)
  - `reserved_slot_id`: `int` (from the shared 4-slot pool via `C:\Users\ansac\CoChem427\heavy-run.lock` / shared slot table)
  - `target_worktree_path`: `str`
  - `status`: `Literal["queued", "reserved", "testing", "committed", "installation_hold", "failed"]`
  - `repair_commit_sha`: `str | None`
  - `verification_report_sha256`: `str | None`
- **Rules:**
  - `CompletionAuditor` (`completion_audit_428.py`) inspects physical artifact manifests, requirement links, and test exit codes — never self-reported prose.
  - When a defect or pipeline failure is detected, `RepairQueue` opens/deduplicates a tier-10 incident.
  - `cochem_supervisor` (`repair_admission_428.py`, `repair_executor_428.py`) arbitrates slot/quota ownership against the main controller, applies/tests repairs in an isolated git worktree under `scripts/run_source_tests_428.py`, and transitions to `installation_hold` when live service replacement requires elevated administrator authority.

### 3.6 Release & Owner Launch Manifest (`Lane D`: `P428-22`, `P428-25`..`P428-27`)

- **Schema: `ReleaseBundleManifest428`**
  - `version`: `"4.2.8"`
  - `source_commit`: `str` (40-hex git SHA)
  - `wheel_filename`: `str`
  - `wheel_sha256`: `str`
  - `dependency_wheels`: `tuple[dict[str, str], ...]`
  - `routing_policy_sha256`: `str`
  - `prior_native_replay_spec_sha256`: `str`
  - `argon_acceptance_spec_sha256`: `str`
  - `migration_schema_version`: `str`
  - `rollback_package_root`: `str`

---

## 4. Walkthrough Verification of Sample Flows Against Schemas

1. **Simple Flow (`complexity_tier` 1–3, e.g., `CODE-SMALL` tier 2):**
   - Intake creates task -> model drafts & distinct-model reviews SRS -> `PlanningController` emits `TaskExecutionNode(node_role="simple_execution", attempt_lineage_id=task_id)` -> `task_execution_428.py` admits against `AcceptedTaskProfileBinding` -> `JobStore` executes -> `TaskArtifactManifest(verification_status="verified")` closes task -> deterministic `CompletionAuditReceipt` runs spot check.
2. **Researched Flow (`complexity_tier` 4–7):**
   - `PlanningController` enters `controller_research` -> `research_runtime_428.py` dispatches `ResearchRequestRecord` across `"internet"`, `"papers"`, and `"wiki"` -> `ResearchEvidenceStore` persists `ResearchReceiptRecord` with bounded `ResearchSourceExcerpt` items -> `planning_gateway.py` hydrates reviewer/reviser prompts with actual verified excerpts bound to `srs_revision` -> distinct-model review passes -> materializes WBS (`WBS_CHILD` nodes with independent `attempt_lineage_id`).
3. **High-Tier Flow (`complexity_tier` 8–10):**
   - After 3-channel research and multi-model SRS review, `PlanningController` enters `owner_review` -> `OwnerApprovalBroker` issues `OwnerApprovalChallenge` -> human operator signs/submits `OwnerApprovalReceipt` (distinct from `COCHEM_API_KEY`) -> `PlanningJournal.apply_owner_approval()` records receipt bound to `combined_scope_digest` -> `microtask_board_428.py` materializes DAG (`wbs_fragment` + `assembly` + `final_test`) -> `task_release_428.py` verifies 100% requirement & test coverage before root completion.
4. **Failed / Pivot / Fracture / Locked Flow (10 / 20 / 30 quality failures):**
   - `FencedAttemptOutcome(outcome_class="quality_failure")` increments `AttemptLedger` once per `(job_id, lease_epoch)` -> at `10`, `failure_dossier_428.py` collects 3-channel failure research and `pivot_runtime_428.py` switches to a higher/different accepted model -> at `20`, `fracture_runtime_428.py` creates `FRACTURE_CHILD` nodes sharing `attempt_lineage_id = parent.attempt_lineage_id` while preserving the escalated model floor on the core failed scope and assembly -> at `30`, lineage transitions to `LOCKED` until an authenticated `LockedTaskOwnerDecision` is applied.
5. **Independent Repair Flow (`CompletionAuditReceipt` failure or runtime fault):**
   - `completion_audit_428.py` detects a missing deliverable/test defect or runtime fault -> opens deduplicated `RepairReservationRecord(repair_tier=10)` -> `repair_admission_428.py` reserves a shared slot and tier-10 max-effort route -> `repair_executor_428.py` runs isolated worktree verification via `scripts/run_source_tests_428.py` and records `installation_hold` for elevated deployment handoff.

---

## 5. Shared-File Edit Schedule & Lane Ownership

All shared files are modified exclusively according to the dependency-ordered schedule below so no parallel lane overwrites another lane's changes:

| Shared File | Reserved Lane / Task Order | Responsibility |
| --- | --- | --- |
| `src/cochem_pipeline/task_routing.py` | `R` (`P428-02`) -> `C` (`P428-23`) | 5-option policy, gap packet, and runtime hook export |
| `src/cochem_pipeline/catalog_activation.py`, `catalog_journal.py` | `R` (`P428-03`) | Task-matrix profile binding to protected live catalog authority |
| `src/cochem_pipeline/argon_catalog.py`, `native_effort.py`, `agy_protocol.py` | `N` (`P428-04`) | Exact Gemini 4 Argon Low/Medium/High native protocol contracts |
| `src/cochem_pipeline/failures.py` | `N` (`P428-05`) | R6 Claude HTTP status & sanitized error preservation |
| `src/cochem_pipeline/planning_journal.py` | `Q` (`P428-06`) -> `H` (`P428-09`) -> `C` (`P428-23`) | Research excerpt digest binding, human approval receipt validation |
| `src/cochem_pipeline/planning_gateway.py` | `Q` (`P428-08`) -> `C` (`P428-23`) | Hydrate prompts with verified 3-channel research excerpts & failure dossiers |
| `src/cochem_pipeline/planning_runtime.py` | `Q` (`P428-08`) -> `E` (`P428-11`, `P428-14`) -> `C` (`P428-23`) | Nonblocking research pump, simple/WBS execution materialization, assembly/final release |
| `src/cochem_pipeline/workflow_428.py` | `E` (`P428-12`) -> `F` (`P428-15`..`P428-18`) -> `C` (`P428-23`) | WBS DAG validation, fenced attempt outcomes, pivot/fracture/locked state machine |
| `src/cochem_pipeline/coding.py` | `E` (`P428-13`) | Safe predecessor artifact & code fragment staging |
| `src/cochem_pipeline/server.py`, `service.py` | `H` (`P428-10`) -> `C` (`P428-23`) | MCP/CLI/HTTP 4.2.8 intake, owner approval endpoints, progress/locked-task views |
| `src/cochem_pipeline/operator_views.py` | `F` (`P428-18`) -> `C` (`P428-23`) | Locked-task, dossier, audit, and repair status reporting |
| `src/cochem_pipeline/repair_queue_428.py` | `A` (`P428-19`) -> `O` (`P428-20`..`P428-21`) | Spot-check audit sampling, cross-process repair reservation & installation hold |
| `src/cochem_pipeline/config.py`, `__init__.py`, `pyproject.toml` | `D` (`P428-22`) -> `C` (`P428-23`) | Version 4.2.8 metadata and additive migration wiring |
| `src/cochem_pipeline/runtime.py`, `store.py`, `admission.py`, `routing_store.py` | `C` (`P428-23`) | Single-integrator wiring of planning, routing, execution, attempt, audit, and repair hooks |
