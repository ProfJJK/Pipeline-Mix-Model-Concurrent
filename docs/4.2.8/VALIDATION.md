# Pipeline 4.2.8 — Integrated Validation & Regression Evidence (`P428-24`)

## Operational repair source verification — 15 October 2026

The current repair checkout is `Pipeline-Mix-Model-Concurrent-428-repair`, branch
`fix/428-operational-repair`. Tests use the repository Python 3.12 interpreter
and `scripts/run_source_tests_428.py`, serialized with the shared host lock.

At `affa811`, all modified test modules since baseline `c714854` except
`pipeline_tests/test_service.py` were run. The selection excluded
`real_process_cleanup`, `fresh_process`, and `actual_native_controller_priority`:
**746 passed, 1 skipped, 2 deselected in 166.43 seconds**. The service module was
not included because its broader fixtures include real child launches.

At `a156f7a`, the budget and physical fracture-board suites passed **42 tests in
33.14 seconds**. These exercise actual temporary files, snapshots and SQLite
transactions, but provider responses and native receipt ports are inert. They
cover parent release after fracture of an implementation or final-test scope,
external predecessors, nested aliases, failure-research parking and unchanged
dispatch/time/quality limits. Owner-launch tests execute selected pure functions
in PowerShell with host lifecycle and process ports replaced by forbidden or
inert ports. No installer Apply, task start, native provider command, protected
write, or live deployment was performed by these tests.

These results supersede claims that the historical 525-test fixture sweep alone
proves the newly connected production path. Live installed native acceptance,
SYSTEM cutover, refreshed Codex MCP visibility and useful-job deliverables must
each have their own receipts. Earlier evidence is retained below as history.

## 1. Scope & Provenance

- **Branch:** `feature/4.2.8-task-routing`
- **Checkout:** `C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent-r6`
- **Source Test Runner:** `scripts/run_source_tests_428.py` (enforces `-I` isolated Python mode, prepends checkout `src/`, rejects site-packages shadow imports, and blocks parallel pytest workers).
- **Interpreter:** `C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\.venv\Scripts\python.exe` (Python 3.12.13, pytest 9.1.1).

---

## 2. Integrated 4.2.8 Acceptance & Recovery Suites

Command:

```powershell
& "C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\.venv\Scripts\python.exe" -I scripts/run_source_tests_428.py --timeout-seconds 120 -- pipeline_tests/test_acceptance_428.py pipeline_tests/test_recovery_428.py --tb=short
```

Observed Result:
- `5 passed in 4.89s`

### Coverage Summary

1. **`pipeline_tests/test_acceptance_428.py` (`3 passed`)**:
   - **Simple Single-Type Workflow (`test_simple_single_type_task_reaches_verified_artifact_and_passes_spotcheck`)**:
     - Submits a tier-2 `COD-TERM` task (`SRS -> READY -> SIMPLE_EXECUTION -> COMPLETED`).
     - Verifies deliverables, SHA-256 digests, requirement evidence, and release criteria via `SimpleTaskExecutionRuntime`.
     - Executes deterministic post-completion spot-check via `CompletionAuditRuntime` using an independent model family (`claude-opus-5-5` auditing `gpt-6-luna`/`gpt-6.1-sol`), confirming `VERIFIED_PASS` with zero false-positive repair incidents.
   - **Multitype Workflow (`test_multitype_task_decomposes_and_releases_verified_manifest`)**:
     - Submits a tier-2 multitype task (`['COD-TERM', 'SCI-FORMAL']`), verifying that multitype work bypasses the simple fast path (`needs_wbs=True`) and traverses `PLAN_REVIEW -> WBS -> MICROTASKS -> MICROTASK_ASSESSMENT -> MICROTASKS_READY`.
     - Dispatches independent fragments (`M1`, `M2`) and dependent `assembly` (`M3`) + `final_test` (`M4`) through `JointAdmission` (4-seat ceiling) and `TaskReleaseRuntime`, requiring a controller-recorded test receipt before `deliverable_completed == True`.
   - **Researched WBS & Owner-Approved High-Tier Workflows (`test_researched_wbs_and_owner_approved_high_tier_tasks_complete_end_to_end`)**:
     - Exercises a tier-5 task through 3-channel research (`internet`, `wiki_rag`, `papers`) via `ResearchRuntime`, verifying hydrated research excerpts inside the `PLAN_REVIEW` prompt before WBS/microtask execution and release.
     - Exercises a tier-8 task through `OWNER_APPROVAL`, confirming `OwnerApprovalBroker` rejects the shared agent bearer token (`PermissionError`) and accepts a human-owner HMAC receipt, followed by 3-channel research, tier-9 independent review, WBS/microtask decomposition, and verified release.

2. **`pipeline_tests/test_recovery_428.py` (`2 passed`)**:
   - **10/20/30 Failure-Injection, Availability Non-Charging, Pivot, Fracture & Locked Owner Recovery (`test_integrated_10_20_30_availability_pivot_fracture_and_locked_owner_recovery`)**:
     - Confirms availability categories (`quota`, `auth`, `resource`, `rate_limit`) release active attempt leases with `failures == 0`.
     - Charges 10 quality failures (`tests_failed`) to reach `PIVOT_RESEARCH`, verifies `MISSING_FAILURE_DOSSIER` hold before dossier creation, records 3-channel boundary-10 dossier, and pivots (`PivotRuntime.evaluate_pivot`) with sticky upward floor (`4 -> 5`) and a distinct underlying model family.
     - Charges failures 11–20 (`validation_error`) on the pivoted model, compiles boundary-20 dossier, and fractures (`FractureRuntime.execute_fracture`) into narrower child fragments (`frag-lexer`, `frag-parser` at tier 3) plus elevated `frag-assembly` (tier 6) while preserving `inherited_failures == 20`.
     - Charges failures 21–30 on `frag-lexer` to reach `LOCKED` (`failures == 30`), verifies credential scrubbing (`REDACTED`) on status links, compiles boundary-30 dossier, and executes an authenticated owner `revise_scope` decision (`REVISED_NEW_REVISION`) that creates `task-rec-lineage-v2` while preserving the 30-failure audit history on the locked lineage.
   - **Spot-Check False-Completion Revocation & Broken-Board Independent Repair Execution (`test_spotcheck_revokes_false_completion_and_broken_board_supervisor_repairs_pipeline_fault`)**:
     - Confirms `CompletionAuditRuntime` revokes a completion missing requirement verification (`FALSE_COMPLETION_TASK_DEFECT`) without opening a pipeline repair incident.
     - Confirms a systemic controller fault (`uncleaned_seat_lease_released`) opens a grounded incident (`PIPELINE_DEFECT_INCIDENT_OPENED`) in `RepairQueue`.
     - Exercises `SupervisorRepairAdmission428` and `IsolatedRepairExecutor428` against an isolated worktree (`SOURCE_REPAIRED`), verifies explicit hold when supervisor transition authority is absent (`AWAITING_SUPERVISOR_TRANSITION`), and transitions to `RESOLVED` once reviewed supervisor authority, runtime digest, and smoke-check digest are supplied.

---

## 3. Full Serialized 4.2.8 + R6/R7 Regression Sweep

Command:

```powershell
& "C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\.venv\Scripts\python.exe" -I scripts/run_source_tests_428.py --timeout-seconds 300 -- pipeline_tests/test_acceptance_428.py pipeline_tests/test_recovery_428.py pipeline_tests/test_source_runner_428.py pipeline_tests/test_task_routing_428.py pipeline_tests/test_task_catalog_428.py pipeline_tests/test_argon_native_428.py pipeline_tests/test_prior_native_428.py pipeline_tests/test_research_evidence_428.py pipeline_tests/test_research_search_428.py pipeline_tests/test_research_runtime_428.py pipeline_tests/test_owner_approval_428.py pipeline_tests/test_task_interface_428.py pipeline_tests/test_task_execution_428.py pipeline_tests/test_microtask_board_428.py pipeline_tests/test_task_artifacts_428.py pipeline_tests/test_task_release_428.py pipeline_tests/test_attempt_runtime_428.py pipeline_tests/test_pivot_runtime_428.py pipeline_tests/test_fracture_runtime_428.py pipeline_tests/test_task_decisions_428.py pipeline_tests/test_completion_audit_428.py pipeline_tests/test_repair_admission_428.py pipeline_tests/test_repair_executor_428.py pipeline_tests/test_repair_queue_428.py pipeline_tests/test_migration_428.py pipeline_tests/test_runtime_428.py pipeline_tests/test_planning_runtime_428.py pipeline_tests/test_planning_gateway_428.py pipeline_tests/test_planning_journal_428.py pipeline_tests/test_workflow_428.py pipeline_tests/test_r7_migration.py pipeline_tests/test_config.py pipeline_tests/test_argon_catalog.py pipeline_tests/test_catalog_activation.py pipeline_tests/test_catalog_journal.py pipeline_tests/test_container_policy.py pipeline_tests/test_cochem_host_guard.py -k "not live" --tb=short
```

Observed Result:
- `525 passed, 1 deselected in 48.78s`

---

## 4. Explicit Separation of Inert Source Verification vs. Deferred Host Acceptance (`P428-28`)

| Verification Boundary | Status in `P428-00`..`P428-24` | Deferred to Owner-Run `P428-28` |
|---|---|---|
| 4.2.8 state machines, SQLite WAL journals, routing, 10/20/30 recovery, owner approval HMAC, completion audit, isolated repair executor, and 4.2.7->4.2.8 DB migration | **Verified (525 passed)** using real SQLite databases, real git worktree fixtures, and deterministic HTTP/clock transports | Live cutover against `C:\ProgramData\CoChem\jobs.db` under `NT AUTHORITY\SYSTEM` |
| `argon-low` / `argon-med` / `argon-high` native selector & thinking-level verification | **Inert contract & parser verified** (`test_argon_native_428.py`) | Live `agy` worker account CLI execution and trace verification (`P428-28`) |
| Prior 15 Codex / Claude / Gemini Flash native profiles | **Inert receipt & hash verifier tested** (`test_prior_native_428.py`) | Inspection of physical host R6/R7 receipts and targeted live native probes where missing (`P428-28`) |
| Dedicated repair profiles (`repair_claude`, `repair_codex`, `repair_agy`) | **Inert admission, 4-slot priority, and isolated worktree executor verified** (`test_repair_admission_428.py`, `test_repair_executor_428.py`) | Front-loaded interactive sign-in (if missing on host) and live SYSTEM supervisor smoke check (`P428-28`) |
