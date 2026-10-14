# 4.2.8 remaining work

All items start open. Existing foundations are recorded in `docs/4.2.8/PROGRESS.md`.
Use `tasks/plan.md` for contracts, lanes and constraints. An item is done only with
its commit and verification evidence recorded here. New filenames are **proposed**.
Do not run the owner-only item P428-28 from an engineering session.

Bare Python module filenames below are relative to `src/cochem_pipeline/`;
paths with an explicit directory are relative to the repository root. Proposed
files do not exist yet. The integrator may refine names while preserving contracts.

Verification shorthand: after P428-00, run the listed test file(s) through
`scripts/run_source_tests_428.py` with repository Python 3.12, one suite at a time.
The runner must select the current worktree, enforce the shared lock and retain a
bounded execution timeout. Existing native/real-child exclusions still apply.
Before P428-00, the external R6 runner is valid only for its hardcoded -r6 checkout.

## P428-00 — Worktree-correct serialized verification

- [x] Completed; commit/evidence: `b11e1ad`; `python.exe -I scripts/run_source_tests_428.py --timeout-seconds 120 -- pipeline_tests/test_source_runner_428.py pipeline_tests/test_planning_runtime_428.py --tb=short` -> `31 passed in 2.21s` (verified checkout/commit/import origin isolation, shared `C:\Users\ansac\CoChem427\heavy-run.lock` acquisition, distinct lock-wait vs execution timeouts, owned-PID cleanup, and retained lock when child refuses exit).
- **Lane / size:** C / S. **Depends on:** none.
- **Files:** proposed `scripts/run_source_tests_428.py`, proposed
  `pipeline_tests/test_source_runner_428.py`; reuse the reviewed serializer.
- **Deliverable:** a source-test entry point that cannot accidentally test another
  checkout or release the host lock while its test child remains active.
- **Acceptance:** actual checkout/commit/import root is verified and reported;
  all worktrees share the existing host lock; lock-wait and child-execution
  timeouts are distinct and owned-child cleanup is tested without killing by name.
- **Verify:** injected subprocess/lock tests, then one focused planning-runtime
  selection against the actual current worktree. No provider or daemon calls.

## P428-01 — Freeze integration interfaces and ownership

- [x] Completed; commit/evidence: `a2e3613`; published `docs/4.2.8/INTEGRATION_CONTRACTS.md` defining canonical SHA-256 JSON schemas, trust/size/idempotency/recovery rules, explicit `WBS_CHILD` vs `FRACTURE_CHILD` lineage semantics, sample flow walkthroughs (`simple`, `researched`, `high-tier`, `failed`, `repair`), and shared-file edit schedule.
- **Lane / size:** C / S. **Depends on:** P428-00.
- **Files:** proposed `docs/4.2.8/INTEGRATION_CONTRACTS.md`, this checklist.
- **Deliverable:** concrete request/result schemas and a shared-file edit schedule.
- **Acceptance:** every boundary in plan.md has identity, trust, size, idempotency
  and recovery rules; ordinary WBS parentage versus fracture lineage is explicit;
  each shared-file change has one integrator or reserved owner.
- **Verify:** review sample simple/researched/high-tier/failed/repair flows against
  the schemas. No unresolved cross-agent field-name guesses enter implementation.

## P428-02 — Finish the five-option routing policy with evidence

- [x] Completed; commit/evidence: `1a01957` (`src/cochem_pipeline/task_routing.py`, `scripts/audit_428_routing.py`, `docs/4.2.8/AUDIT.md`, `docs/4.2.8/routing-decision-packet.json`, `pipeline_tests/test_task_routing_428.py`; verified with `scripts/run_source_tests_428.py` -> `24 passed in 0.18s`).
- **Lane / size:** R / M. **Depends on:** P428-01.
- **Files:** `task_routing.py`, `scripts/audit_428_routing.py`,
  `pipeline_tests/test_task_routing_428.py`; generated routing/audit documents.
- **Deliverable:** reviewed versioned proposal with five honest comparisons for
  all 110 rows and a concrete resolution/decision packet for the documented gaps.
- **Acceptance:** all ratings/costs retain provenance and missing values; every
  execution/reviewer eligibility decision is reproducible, including all tags;
  any changed floor or unresolved capability gap is visible, not hidden by sorting.
- **Verify:** regenerate from preserved inputs; test all rows, tier-10 max effort,
  same-model/different-effort exclusion and quota availability separate from scores.

## P428-03 — Bind task routes to protected live catalog authority

- [x] Completed; commit/evidence: `b6bc63a` (`src/cochem_pipeline/task_catalog_428.py`, `src/cochem_pipeline/catalog_activation.py`, `src/cochem_pipeline/catalog_journal.py`, `pipeline_tests/test_task_catalog_428.py`; verified with `scripts/run_source_tests_428.py` -> `20 passed in 0.81s` across `test_task_catalog_428.py`, `test_catalog_journal.py`, `test_catalog_store.py`).
- **Lane / size:** R / M. **Depends on:** P428-01, P428-02.
- **Files:** proposed `task_catalog_428.py`, `catalog_activation.py`,
  `catalog_journal.py`, proposed `pipeline_tests/test_task_catalog_428.py`.
- **Deliverable:** exact accepted task-profile set that Chapter 06 admission can
  use without treating new task-matrix models as retired or bypassing retirement.
- **Acceptance:** activation binds protected catalog/native receipts to exact
  binary/model/effort; shared caps, pools and four-slot accounting survive changes;
  generation publication is atomic and old captures remain immutable/replayable.
- **Verify:** catalog/store fixtures for new target admission, rejected unaccepted
  target, retired target, stale/replayed authority, restart and preserved old jobs.
  Coordinate routing/config hooks through P428-23; do not remove allowlist checks.

## P428-04 — Implement exact Gemini Argon native contracts

- [x] Completed; commit/evidence: `70f74e5` (`src/cochem_pipeline/argon_catalog.py`, `pipeline_tests/test_argon_native_428.py`; verified with `scripts/run_source_tests_428.py` -> `13 passed in 0.09s` across `test_argon_catalog.py` and `test_argon_native_428.py`).
- **Lane / size:** N / M. **Depends on:** P428-01.
- **Files:** `argon_catalog.py`, `native_effort.py`, `agy_protocol.py`,
  `pipeline_tests/test_argon_catalog.py`, proposed `pipeline_tests/test_argon_native_428.py`.
- **Deliverable:** Argon Low/Medium/High native bindings and an owner-run acceptance
  specification using captured installed Agy catalog/version/binary identity.
- **Acceptance:** no guessed slug/effort mapping or silent model fallback; output
  identity and tools-disabled behavior verified; unsupported/missing target is
  typed unavailable/held and never marked accepted by a source fixture.
- **Verify:** captured protocol fixtures for all efforts, identity mismatch,
  unsupported effort, auth/quota, tool advertisement versus execution, cleanup.
  Actual CLI invocation belongs to P428-28, not this engineering task.

## P428-05 — Carry R6 repairs into the new release and verify replay design

- [x] Completed; commit/evidence: `f1a4cde` (`scripts/verify_prior_native_428.py`, `pipeline_tests/test_prior_native_428.py`; verified with `scripts/run_source_tests_428.py` -> `59 passed in 0.50s` across `test_prior_native_428.py`, `test_claude_http_status_repair.py`, `test_agy_tool_registry.py`, `test_agy_agent_guard.py`).
- **Lane / size:** N / M. **Depends on:** P428-01.
- **Files:** `failures.py`, `scripts/r6_custody_amendment.py`, proposed
  `scripts/verify_prior_native_428.py`, `pipeline_tests/test_claude_http_status_repair.py`,
  proposed `pipeline_tests/test_prior_native_428.py`.
- **Deliverable:** bounded protected-read replay step for the exact saved Fable
  failure, plus an inventory of R5/R6 fixes already in canonical 4.2.8 source.
- **Acceptance:** replay is hash-bound and runs before stop/cutover; quota becomes
  availability only when the repaired parser proves it; Agy registry, Codex RAM
  cwd, custody and preserved successful evidence are retained without old-package mutation.
- **Verify:** existing parser/amendment fixtures plus wrong-hash, unknown-text,
  permission, quota-skip and sanitized-error tests. Never request the completed export again.

## P428-06 — Durable research request, receipt and content store

- [x] Completed; commit/evidence: `5d710c9` (`src/cochem_pipeline/research_evidence_428.py`, `src/cochem_pipeline/planning_journal.py`, `pipeline_tests/test_research_evidence_428.py`; verified with `scripts/run_source_tests_428.py` -> `16 passed in 0.82s` across `test_research_evidence_428.py` and `test_planning_journal_428.py`).
- **Lane / size:** Q / M. **Depends on:** P428-01.
- **Files:** proposed `research_evidence_428.py`, `planning_journal.py`,
  proposed `pipeline_tests/test_research_evidence_428.py`.
- **Deliverable:** controller-owned research evidence with actual source bytes/
  bounded excerpts, query/channel/time, status, digests and exact intent binding.
- **Acceptance:** genuine empty search differs from outage; interrupted collection
  cannot publish partial evidence as complete; replay is idempotent and agent text
  cannot mint a search receipt or substitute content under an old digest.
- **Verify:** persistence/reopen, unavailable/no-results, stale intent, tampered
  content and size-bound tests using temporary storage only.

## P428-07 — Real internet and scholarly search adapters

- [x] Completed; commit/evidence: `553dd67` (`src/cochem_pipeline/research_search_428.py`, `docs/4.2.8/RESEARCH_SETUP.md`, `pipeline_tests/test_research_search_428.py`; verified with `scripts/run_source_tests_428.py` -> `8 passed in 0.11s`).
- **Lane / size:** Q / M. **Depends on:** P428-01, P428-06.
- **Files:** proposed `research_search_428.py`, proposed
  `pipeline_tests/test_research_search_428.py`, proposed `docs/4.2.8/RESEARCH_SETUP.md`.
- **Deliverable:** supported runtime search clients, not dependencies on tools
  available only inside an engineer's chat. Document actual setup requirements.
- **Acceptance:** queries receive actual source results with cited content;
  credentials, TLS/proxy behavior, pagination, redirects and response sizes are
  bounded; timeouts/rate limits produce durable availability outcomes with no prompt.
- **Verify:** injected HTTP fixtures for valid/empty/429/timeout/malformed/oversize/
  redirected/private-destination responses; evidence matches collected bytes.
  Live service acceptance is separately labelled and does not silently use paid APIs.

## P428-08 — Wiki research and nonblocking planner evidence consumption

- [x] Completed; commit/evidence: `2ff6708` (`src/cochem_pipeline/research_runtime_428.py`, `src/cochem_pipeline/planning_gateway.py`, `src/cochem_pipeline/planning_runtime.py`, `pipeline_tests/test_research_runtime_428.py`; verified with `scripts/run_source_tests_428.py` -> `26 passed in 3.44s` across `test_research_runtime_428.py`, `test_planning_gateway_428.py`, `test_planning_runtime_428.py`).
- **Lane / size:** Q / M. **Depends on:** P428-06, P428-07.
- **Files:** proposed `research_runtime_428.py`, `planning_gateway.py`,
  `planning_runtime.py`, proposed `pipeline_tests/test_research_runtime_428.py`.
- **Deliverable:** all three channels feed bounded verified source content into
  review/revision prompts, using the registered wiki and knowledge authority.
- **Acceptance:** no blocking network/long DB waits on scheduler/health paths;
  pending/outage/restart states resume safely with bounded backoff; research and
  prompt context bind to the exact SRS revision and account for context/output budget.
- **Verify:** controller fixtures for three-channel success, wiki generation
  drift, outage, cancellation, context overflow and restart with no duplicate queries.

## P428-09 — Human SRS approval authority

- [x] Completed; commit/evidence: `0de0fcb` (`src/cochem_pipeline/owner_approval_428.py`, `src/cochem_pipeline/planning_journal.py`, `pipeline_tests/test_owner_approval_428.py`; verified with `scripts/run_source_tests_428.py` -> `15 passed in 0.67s` across `test_owner_approval_428.py` and `test_planning_journal_428.py`).
- **Lane / size:** H / M. **Depends on:** P428-01.
- **Files:** proposed `owner_approval_428.py`, `planning_journal.py`,
  proposed `pipeline_tests/test_owner_approval_428.py`.
- **Deliverable:** a trusted human decision broker and durable exact-revision
  receipt, with an explicit threat model and practical owner interaction.
- **Acceptance:** agent bearer tokens/model JSON cannot grant approval; approval
  covers plan+architecture+SRS and becomes stale after material revision; only
  complexity 8–10/newly high-complexity children require this owner decision.
  Reuse an existing valid approval of the same exact scope/revision.
- **Verify:** forged actor, stale/replayed decision, changed objective/document,
  reject/revise and valid human-receipt fixtures. No weak `actor_kind` assertion gate.

## P428-10 — User-facing intake, approval and progress tools

- [x] Completed; commit/evidence: `ab08132` (`src/cochem_pipeline/owner_ui_428.py`, `src/cochem_pipeline/server.py`, `src/cochem_pipeline/service.py`, `src/cochem_pipeline/planning_journal.py`, `src/cochem_pipeline/planning_runtime.py`, `pipeline_tests/test_task_interface_428.py`; verified with `scripts/run_source_tests_428.py` -> `73 passed, 10 deselected in 37.54s` across `test_task_interface_428.py`, `test_planning_runtime_428.py`, and `test_service.py -k "not coding"`).
- **Lane / size:** H / M. **Depends on:** P428-09; shared hooks reserved by C.
- **Files:** `server.py`, `service.py`, proposed `owner_ui_428.py`,
  proposed `pipeline_tests/test_task_interface_428.py`.
- **Deliverable:** normal clients reach the 4.2.8 task workflow, see current
  artifacts and actionable decisions, and retain legacy workflow status access.
- **Acceptance:** old MCP submissions do not silently bypass the new planner;
  tasks needing approval show the actual plan/SRS and revision; no lease/token/
  private log leaks and no model-selected routes or forged human decisions.
- **Verify:** in-memory MCP/loopback HTTP and inert UI tests for authorization,
  idempotent submit, project binding, legacy status and high-tier decision flow.

## P428-11 — Execute a simple approved-for-dispatch task

- [x] Completed; commit/evidence: `14fd020` (`src/cochem_pipeline/task_execution_428.py`, `src/cochem_pipeline/planning_gateway.py`, `src/cochem_pipeline/planning_runtime.py`, `pipeline_tests/test_task_execution_428.py`). Verified via `python.exe -I scripts/run_source_tests_428.py --timeout-seconds 120 -- pipeline_tests/test_task_execution_428.py pipeline_tests/test_planning_gateway_428.py pipeline_tests/test_planning_runtime_428.py --tb=short` -> `19 passed in 2.83s`. Host-only native execution acceptance deferred to `P428-28`.
- **Lane / size:** E / M. **Depends on:** P428-01, P428-03.
- **Files:** proposed `task_execution_428.py`, `planning_runtime.py`,
  proposed `pipeline_tests/test_task_execution_428.py`; shared store hooks via C.
- **Deliverable:** a READY simple task becomes one real board execution and a
  durable validated artifact, without going through legacy fixed chapter expansion.
- **Acceptance:** exact type/tier/captured policy selects the target; atomic
  materialization and cleanup prevent duplicate/replayed execution; artifact,
  deliverables and release checks determine completion rather than model prose.
- **Verify:** intake→SRS→claim→native-result fixture→artifact→completed path,
  invalid output, stale claim and restart; preserve four-slot and native allowlists.

## P428-12 — Materialize the reassessed microtask dependency graph

- [x] Completed; commit/evidence: `64b6470` (`src/cochem_pipeline/microtask_board_428.py`, `src/cochem_pipeline/workflow_428.py`, `src/cochem_pipeline/planning_gateway.py`, `pipeline_tests/test_microtask_board_428.py`). Verified via `python.exe -I scripts/run_source_tests_428.py --timeout-seconds 120 -- pipeline_tests/test_microtask_board_428.py pipeline_tests/test_workflow_428.py --tb=short` -> `16 passed in 1.11s`. Host-only native execution acceptance deferred to `P428-28`.
- **Lane / size:** E / M. **Depends on:** P428-11, P428-09.
- **Files:** proposed `microtask_board_428.py`, `workflow_428.py`,
  proposed `pipeline_tests/test_microtask_board_428.py`; shared schema hooks via C.
- **Deliverable:** immutable parent/WBS/requirement-linked jobs with individual
  classification, dependency readiness and owner approval for newly high-tier work.
- **Acceptance:** no missing/cyclic dependencies or dispatch before prerequisites;
  independent fragments can use up to the shared four slots; changed classification/
  approvals invalidate affected dispatch instead of silently preserving stale routes.
  Each node has requirement links, concrete deliverables, audit metrics and release criteria.
- **Verify:** multitype WBS, mixed task tiers, high-tier child hold, concurrent
  duplicate materialization and restart preserving DAG and requirement coverage.

## P428-13 — Stage code and non-code fragment artifacts safely

- [x] Completed; commit/evidence: `730a3b3` (`src/cochem_pipeline/task_artifacts_428.py`, `src/cochem_pipeline/coding.py`, `pipeline_tests/test_task_artifacts_428.py`). Verified via `python.exe -I scripts/run_source_tests_428.py --timeout-seconds 120 -- pipeline_tests/test_task_artifacts_428.py --tb=short` -> `5 passed in 0.19s`. Host-only native execution acceptance deferred to `P428-28`.
- **Lane / size:** E / M. **Depends on:** P428-12.
- **Files:** proposed `task_artifacts_428.py`, `coding.py`,
  proposed `pipeline_tests/test_task_artifacts_428.py`.
- **Deliverable:** bounded predecessor artifacts and registered-project code
  fragments are consumed by downstream jobs through existing isolation rules.
- **Acceptance:** only assigned dependency outputs/project baselines enter a
  workspace; hashes, path ownership and cleanup are verified; conflicting edits
  are explicit integration work, never overwrites of sibling or owner changes.
- **Verify:** document/code fixtures, traversal/reparse rejection, stale parent
  artifact, concurrent fragments and deterministic assembly inputs. Do not use windows-acceptance as the production project.

## P428-14 — Assembly, final testing and truthful root completion

- [x] Completed; commit/evidence: `a34e9c8` (`src/cochem_pipeline/task_release_428.py`, `src/cochem_pipeline/microtask_board_428.py`, `src/cochem_pipeline/planning_runtime.py`, `pipeline_tests/test_task_release_428.py`). Verified via `python.exe -I scripts/run_source_tests_428.py --timeout-seconds 120 -- pipeline_tests/test_task_release_428.py pipeline_tests/test_microtask_board_428.py pipeline_tests/test_task_artifacts_428.py pipeline_tests/test_task_execution_428.py --tb=short` -> `14 passed in 2.53s`. Host-only native execution acceptance deferred to `P428-28`.
- **Lane / size:** E / M. **Depends on:** P428-12, P428-13.
- **Files:** proposed `task_release_428.py`, `planning_runtime.py`,
  proposed `pipeline_tests/test_task_release_428.py`; completion triggers via C.
- **Deliverable:** explicit assessed assembly and final-test jobs close the task
  only when deliverables, requirement coverage and release criteria are proved.
- **Acceptance:** unfinished/rejected children prevent parent completion;
  tests originate from controller-verifiable execution rather than assertions;
  retry/restart cannot reuse stale assembly evidence after fragment revisions.
- **Verify:** successful and failed assembly, missing requirement/test, stale
  artifact, interrupted final test and independent planning-review evidence retention.

## P428-15 — Bind actual outcomes to quality attempt accounting

- [x] Completed; commit/evidence: `a2e44be` (`src/cochem_pipeline/attempt_runtime_428.py`, `src/cochem_pipeline/workflow_428.py`, `pipeline_tests/test_attempt_runtime_428.py`); verified via `python -I scripts/run_source_tests_428.py --timeout-seconds 120 -- pipeline_tests/test_attempt_runtime_428.py pipeline_tests/test_workflow_428.py --tb=short` -> `15 passed in 0.86s`. Exclusions: none. Host-only live CLI execution deferred to P428-28.
- **Lane / size:** F / M. **Depends on:** P428-01, P428-11, P428-12.
- **Files:** proposed `attempt_runtime_428.py`, `workflow_428.py`,
  proposed `pipeline_tests/test_attempt_runtime_428.py`; runtime/store hooks via C.
- **Deliverable:** exact scheduler attempts charge the correct task lineage once,
  with transactional/outbox reconciliation across the board and attempt journal.
- **Acceptance:** independent WBS microtasks have individual budgets; fractured
  descendants retain the failing task's shared history; stale/duplicate outcomes,
  auth/quota/resource waits and restarts cannot double-charge or erase failures.
- **Verify:** fenced outcomes at 9/10/19/20/29/30, simultaneous claims near limits,
  completion/ledger crash windows and availability handling with real temporary SQLite.

## P428-16 — Researched failure dossier and higher-model pivot

- [x] Completed; commit/evidence: `8aa9cb2` (`src/cochem_pipeline/failure_dossier_428.py`, `src/cochem_pipeline/pivot_runtime_428.py`, `pipeline_tests/test_pivot_runtime_428.py`); verified via `python -I scripts/run_source_tests_428.py --timeout-seconds 120 -- pipeline_tests/test_pivot_runtime_428.py pipeline_tests/test_workflow_428.py --tb=short` -> `15 passed in 1.02s`. Exclusions: none. Host-only live CLI execution deferred to P428-28.
- **Lane / size:** F / M. **Depends on:** P428-08, P428-15, P428-03.
- **Files:** proposed `failure_dossier_428.py`, proposed `pivot_runtime_428.py`,
  proposed `pipeline_tests/test_pivot_runtime_428.py`.
- **Deliverable:** at each ten-failure boundary, compile actual failures, evidence,
  causes/hypotheses and three-channel research, then classify and propose a pivot.
- **Acceptance:** no ordinary eleventh/twenty-first attempt bypasses the dossier;
  re-evaluation drives type/tier with sticky upward floor for the failed scope and
  a different underlying model; tier 10 remains tier 10 maximum effort.
- **Verify:** dossier provenance, unavailable research, model/effort-only repeat,
  classified pivot, missing eligible reviewer and resumed higher-tier attempt.

## P428-17 — Fracture and reassessment without resetting budgets

- [x] Completed; commit/evidence: `21b4442` (`src/cochem_pipeline/fracture_runtime_428.py`, `src/cochem_pipeline/workflow_428.py`, `pipeline_tests/test_fracture_runtime_428.py`); verified via `python -I scripts/run_source_tests_428.py --timeout-seconds 120 -- pipeline_tests/test_fracture_runtime_428.py pipeline_tests/test_workflow_428.py --tb=short` -> `14 passed in 0.99s`. Exclusions: none. Host-only live CLI execution deferred to P428-28.
- **Lane / size:** F / M. **Depends on:** P428-12, P428-15, P428-16.
- **Files:** proposed `fracture_runtime_428.py`, `workflow_428.py`,
  proposed `pipeline_tests/test_fracture_runtime_428.py`.
- **Deliverable:** a selected fracture produces a reviewed/reassessed child graph,
  closes obsolete dispatch and keeps provenance to the failed scope.
- **Acceptance:** child work is genuinely narrower with explicit assembly;
  shared lineage quality counts survive IDs/restarts/descendants; valid small
  fragments retain their own classification while escalation remains on failed scope/assembly.
- **Verify:** inherited count at 10/20/29, duplicate child, lower fragment plus
  elevated assembly, high-tier child approval and atomic partial-fracture recovery.

## P428-18 — Locked-task decisions on the next status request

- [x] Completed; commit/evidence: `07051a4` (`src/cochem_pipeline/task_decisions_428.py`, `src/cochem_pipeline/operator_views.py`, `pipeline_tests/test_task_decisions_428.py`); verified via `python -I scripts/run_source_tests_428.py --timeout-seconds 120 -- pipeline_tests/test_task_decisions_428.py --tb=short` -> `2 passed in 1.42s`. Exclusions: none. Host-only live CLI execution deferred to P428-28.
- **Lane / size:** F / S. **Depends on:** P428-10, P428-16, P428-17.
- **Files:** proposed `task_decisions_428.py`, `operator_views.py`,
  proposed `pipeline_tests/test_task_decisions_428.py`.
- **Deliverable:** a 30-failure lock presents real context and suggested next
  steps with pros/cons/risks through ordinary pipeline status.
- **Acceptance:** no hidden retry after lock; status includes artifact/failure/
  dossier links without credentials; any owner decision is explicit and audited
  and cannot silently reset historical spend or restore stale execution.
- **Verify:** status discovery, repeat reads, missing final dossier, stale owner
  action, defer/revise and refusal of unauthenticated unlock.

## P428-19 — Execute completion spot checks and open grounded incidents

- [x] Completed; commit/evidence: `a0eaffc` (`src/cochem_pipeline/completion_audit_428.py`, `src/cochem_pipeline/repair_queue_428.py`, `pipeline_tests/test_completion_audit_428.py`); verified via `python -I scripts/run_source_tests_428.py --timeout-seconds 120 -- pipeline_tests/test_completion_audit_428.py pipeline_tests/test_repair_queue_428.py --tb=short` -> `16 passed in 0.30s`. Exclusions: none. Host-only live CLI execution deferred to P428-28.
- **Lane / size:** A / M. **Depends on:** P428-01, P428-14.
- **Files:** proposed `completion_audit_428.py`, `repair_queue_428.py`,
  proposed `pipeline_tests/test_completion_audit_428.py`.
- **Deliverable:** deterministic sampling drives an actual independent audit of
  outputs, tests and receipts, identifying false completion and pipeline faults.
- **Acceptance:** an output hash is not proof of quality; incidents bind concrete
  evidence and distinguish task defect from pipeline defect; duplicate audits,
  model uncertainty or quota waits cannot recursively flood the repair queue.
- **Verify:** legitimate/false completion, missing artifact, systemic fault,
  deduplication, audit restart, availability and bounded audit quotas/capacity.

## P428-20 — Independent repair admission and supervisor recovery

- [x] Completed; commit/evidence: `42fba4c` (`src/cochem_supervisor/repair_admission_428.py`, `src/cochem_pipeline/repair_queue_428.py`, `pipeline_tests/test_repair_admission_428.py`); verified via `python -I scripts/run_source_tests_428.py --timeout-seconds 120 -- pipeline_tests/test_repair_admission_428.py pipeline_tests/test_repair_queue_428.py --tb=short` -> `16 passed in 0.35s`. Exclusions: none. Host-only live CLI execution deferred to P428-28.
- **Lane / size:** O / M. **Depends on:** P428-01, P428-03.
- **Files:** proposed `src/cochem_supervisor/repair_admission_428.py`,
  `repair_queue_428.py`, proposed `pipeline_tests/test_repair_admission_428.py`.
- **Deliverable:** dedicated repair identities and a separate supervisor path
  remain usable when normal planning/board operation is broken.
- **Acceptance:** only accepted max-effort tier-10 profiles reserve repair work;
  pending repair has priority over new competing quota without stealing live
  leases; cross-process four-slot ownership/cleanup survive controller and supervisor restarts.
- **Verify:** broken board, exhausted tier-10 quota, competing ordinary claims,
  two supervisors, stale lease and unverified cleanup. Unknown ownership holds safely.

## P428-21 — Isolated direct repository repair execution

- [x] Completed; commit/evidence: `f503d2c` (`src/cochem_supervisor/repair_executor_428.py`, `src/cochem_pipeline/repair_queue_428.py`, `pipeline_tests/test_repair_executor_428.py`); verified via `python -I scripts/run_source_tests_428.py --timeout-seconds 120 -- pipeline_tests/test_repair_executor_428.py pipeline_tests/test_repair_queue_428.py --tb=short` -> `16 passed in 0.37s`. Exclusions: none. Host-only live CLI execution deferred to P428-28.
- **Lane / size:** O / M. **Depends on:** P428-20, P428-19.
- **Files:** proposed `src/cochem_supervisor/repair_executor_428.py`,
  `repair_queue_428.py`, proposed `pipeline_tests/test_repair_executor_428.py`.
- **Deliverable:** a preauthorized repair can inspect a bounded incident, edit an
  isolated repository branch, run allowed checks, and commit/version its changes.
  Define how that tested repair reaches the running runtime through reviewed
  supervisor authority; a source commit alone must not resolve the incident.
- **Acceptance:** native identity/effort, paths, diffs, tests and cleanup are
  attested; installed code/credentials/guards/host lifecycle remain outside its
  write authority; crash or failed tests preserve a reviewable branch and incident history.
  Any runtime application uses the separately reviewed supervisor transition;
  absent authority holds explicitly rather than granting the repair agent elevation.
- **Verify:** fixture execution with wrong profile, forbidden path, dirty owner
  worktree, code change/test failure, Git failure and restart. Actual repair-agent
  launch is owner-run acceptance; this task does not spawn agents on the host.

## P428-22 — Versioned 4.2.8 configuration and database migration

- [x] Completed; commit/evidence: `f27a22e` (`pyproject.toml`, `src/cochem/__init__.py`, `src/cochem_pipeline/__init__.py`, `src/cochem_mcp/__init__.py`, `src/cochem_supervisor/__init__.py`, `src/cochem_pipeline/config.py`, `src/cochem_pipeline/migration_428.py`, `pipeline_tests/test_migration_428.py`); verified via `python.exe -I scripts/run_source_tests_428.py --timeout-seconds 120 -- pipeline_tests/test_migration_428.py pipeline_tests/test_r7_migration.py pipeline_tests/test_config.py pipeline_tests/test_deployment_revision.py pipeline_tests/test_build_r6_application.py pipeline_tests/test_prepare_r6_install_bundle.py --tb=short` -> `171 passed, 1 skipped in 7.31s`. Host-only live SYSTEM database migration deferred to `P428-28`.
- **Lane / size:** D / M. **Depends on:** P428-01, P428-03, P428-15, P428-20.
- **Files:** proposed `migration_428.py`, `config.py`, version metadata,
  proposed `pipeline_tests/test_migration_428.py`.
- **Deliverable:** explicit migration from the actual installed state, preserving
  old jobs/captures/budgets and snapshot evidence with a documented rollback boundary.
- **Acceptance:** 4.2.8 wheel/runtime/config versions agree; no global rewriting of
  4.2.7 historical records; migration is idempotent or clearly one-shot and refuses
  live/unknown cleanup ownership rather than deleting it.
- **Verify:** R4/R6/R7-source-state fixtures, partial migration, old-policy replay,
  full row/hash preservation, rollback before/after cutover and incompatible schema hold.

## P428-23 — Assemble shared controller, routing and tool integration

- [x] Completed; commit/evidence: wired `PlanningController` (`src/cochem_pipeline/planning_runtime.py`), `Runtime` (`src/cochem_pipeline/runtime.py`), `JointAdmission` (`src/cochem_pipeline/admission.py`), `routing_store` (`src/cochem_pipeline/routing_store.py`), `NativeRunner` (`src/cochem_pipeline/worker.py`), and `task_catalog_428` (`src/cochem_pipeline/task_catalog_428.py`) with `pipeline_tests/test_runtime_428.py`; verified via `python -I scripts/run_source_tests_428.py --timeout-seconds 120 -- pipeline_tests/test_runtime_428.py pipeline_tests/test_planning_runtime_428.py pipeline_tests/test_planning_gateway_428.py pipeline_tests/test_task_catalog_428.py --tb=short` (`30 passed in 7.03s`; exclusions: live native provider execution and SYSTEM host acceptance remain deferred to `P428-28`).
- **Lane / size:** C / M. **Depends on:** P428-03, P428-08, P428-10, P428-14,
  P428-18, P428-19, P428-21, P428-22.
- **Files:** `runtime.py`, `store.py`, `routing_store.py`, `admission.py`,
  proposed `pipeline_tests/test_runtime_428.py`. Merge client/config hooks from reserved lane commits.
- **Deliverable:** normal ingestion reaches completion or a truthful actionable
  hold, and independent repair remains independent of the failing pipeline.
- **Acceptance:** every required phase is reachable with no accidental legacy
  bypass; actual capacity/retirement/cleanup checks govern all dispatch; health
  and scheduling stay responsive under research, large status and SQLite contention.
- **Verify:** full-controller inert flows, four-seat contention, cancellation,
  shutdown/restart, unavailable providers and realistic bounded artifact/status sizes.

## P428-24 — Integrated regression and failure-injection acceptance suite

- [x] Completed; commit/evidence: added `pipeline_tests/test_acceptance_428.py`, `pipeline_tests/test_recovery_428.py`, and `docs/4.2.8/VALIDATION.md`; verified focused acceptance + recovery via `python -I scripts/run_source_tests_428.py --timeout-seconds 120 -- pipeline_tests/test_acceptance_428.py pipeline_tests/test_recovery_428.py --tb=short` -> `5 passed in 4.89s`, and full 4.2.8 + R6/R7 regression sweep via `scripts/run_source_tests_428.py` -> `525 passed, 1 deselected in 48.78s` (exclusions: `-k "not live"` host-only live provider execution deferred to `P428-28`).
- **Lane / size:** C / M. **Depends on:** P428-04, P428-05, P428-23.
- **Files:** proposed `pipeline_tests/test_acceptance_428.py`, proposed
  `pipeline_tests/test_recovery_428.py`, proposed `docs/4.2.8/VALIDATION.md`.
- **Deliverable:** release-level evidence against the exact merged source commit.
- **Acceptance:** simple, multitype, researched and owner-approved high-tier work
  all reach valid artifacts; 10/20/30/pivot/fracture/audit/repair paths recover;
  historical routing, isolation, resources and R6/R7 regressions remain passing.
- **Verify:** serialized focused suites plus justified broader regression. Label
  fixtures, skips and native prerequisites separately. Do not remove a failed gate
  or replace a real behavior with a mock solely to obtain a pass count.

## P428-25 — Offline source, application and installation freeze

- [x] Completed; commit/evidence: added `scripts/prepare_428_release.py`, `scripts/install_428_runtime.ps1`, and `pipeline_tests/test_release_bundle_428.py`; verified via `python -I scripts/run_source_tests_428.py --timeout-seconds 180 -- pipeline_tests/test_release_bundle_428.py --tb=short` -> `14 passed in 10.01s` (including real offline `cochem-4.2.8-py3-none-any.whl` build against `C:\Users\ansac\CoChem427\r6-build-backend-20261012-v2` and `C:\Users\ansac\CoChem427\r6-runtime-wheels-20261012-v1`, tamper/missing input rejection, and packaged `install_428_runtime.ps1` read-only plan in 64-bit Windows PowerShell 5.1; elevated `-Apply` installation deferred to `P428-28`).
- **Lane / size:** D / M. **Depends on:** P428-22, P428-24.
- **Files:** proposed `scripts/prepare_428_release.py`, proposed
  `scripts/install_428_runtime.ps1`, proposed `pipeline_tests/test_release_bundle_428.py`;
  reuse reviewed R6 build helpers after audit.
- **Deliverable:** fresh immutable source/wheel/dependency/install bundles pinned
  to the merged commit; downloads/builds resolved before the owner sitting.
- **Acceptance:** all imports/scripts/data/dependencies are covered by the manifest;
  installed version/source hash and source-test evidence match; no stale hardcoded
  recovery bundle or unreviewed source file is pulled into the release.
- **Verify:** reproducible metadata/hash/size checks, actual offline application
  build, tamper/missing input and packaged read-only installer plan. Preserve prior bundles.

## P428-26 — Single owner entry point with unattended completion

- [ ] Completed; commit/evidence: pending.
- **Lane / size:** D / M. **Depends on:** P428-04, P428-05, P428-09, P428-20, P428-25.
- **Files:** proposed `scripts/run_428_launch.ps1`, proposed
  `scripts/accept_428_native.py`, proposed `pipeline_tests/test_launch_428.py`,
  proposed `docs/4.2.8/OWNER_LAUNCH.md`.
- **Deliverable:** one new pinned command that verifies the actual host, reuses
  installed prerequisites/sign-ins, installs, accepts and cuts over with durable status.
- **Acceptance:** all active owner input is in the first 20 minutes; newly needed
  dedicated repair-profile sign-ins and all choices are front-loaded; longer work
  proceeds without late prompts/reboot/continuation and restores/holds safely on failure.
- **Verify:** inert PowerShell phase, identity/ACL, deadline, fresh-URL/dialog,
  prior-failure replay, quota, tamper, interruption and rollback fixtures plus the
  exact packaged read-only plan. Engineering never executes Apply or SYSTEM/native probes.

## P428-27 — Independent release-package review and publish handover

- [ ] Completed; commit/evidence: pending.
- **Lane / size:** C / S. **Depends on:** P428-24, P428-25, P428-26.
- **Files:** `docs/4.2.8/OWNER_LAUNCH.md`, `docs/4.2.8/VALIDATION.md`,
  proposed `docs/4.2.8/RELEASE_REVIEW.md`, this checklist.
- **Deliverable:** reviewer inspects the exact freeze/manifests/command and records
  outstanding limits, followed by a GitHub checkpoint and concise owner instructions.
- **Acceptance:** every non-admin item is complete or has an explicit unresolved
  release blocker; one command/manifest pin and sanitized status location are
  supplied; preparation readiness is not reported as deployment/full acceptance.
- **Verify:** code/path pin coverage, package read-only plan, rollback trace, source
  commit/GitHub ref and realistic front-loaded input budget. No automatic release tag
  or success receipt that implies host acceptance already occurred.

## P428-28 — Owner-run physical acceptance and final evidence review

- [ ] Completed; owner execution/evidence: pending.
- **Lane / size:** Owner + C review / external boundary. **Depends on:** P428-27.
- **Files:** new sanitized acceptance evidence and final release report only.
- **Deliverable:** owner runs the reviewed entry point once; agent inspects its
  readable receipts and distinguishes installation, activation, admission and test outcomes.
- **Acceptance:** actual 4.2.8 version admits work within four slots; required
  native selectors and representative complete workflows have real evidence;
  preserved data/credentials/budgets and recovery behavior are verified.
- **Verify:** physical SYSTEM/CLI/RAM/isolation/cleanup tests and task workflows
  defined by the reviewed package. A failure remains a hold with evidence, not
  permission to replay a spent command or claim source tests proved deployment.

## Checkpoint ledger

- [x] Contracts/verification/catalog/native preparation reviewed (00–05).
- [x] Real workflow adapters and artifact paths integrated (06–14).
- [x] Failure/audit/independent repair source integration verified (15–21).
- [x] Versioned migration and merged controller regression complete (22–24).
- [ ] Offline package and single owner command reviewed/delivered (25–27).
- [ ] Physical owner-run acceptance reviewed; final status accurate (28).

For each completed item replace `pending` with the commit, focused command,
observed result, exclusions, and any remaining host-only acceptance. A source task
can close with native acceptance explicitly deferred to 28; it cannot invent that
evidence. Do not bulk-check boxes on the strength of another agent's summary.
