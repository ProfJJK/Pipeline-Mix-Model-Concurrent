# 4.2.8 source progress

2026-10-16 (evening): the owner ran `ab900e9`; it is spent. Every host check
passed up to fence creation, including the running-r4 binding and the Codex
re-capture. It then held at the first one-shot identity check: the raw XML
pinned from the registration COM object did not match a fresh copy
([hold](evidence/operational-recovery-ab900e9-hold.json)). The fence could be
neither verified nor stopped, and r4 ended; `865a29b` held at the same boundary.
`d5d6094` verifies one-shots structurally on fresh copies, always ends its own
fence's processes, verifies Warden changes on re-fetched copies, and waits for
r4 health. **583 serialized source/inert tests passed**, including a
reproduction on the exact delivered bytes; the packaged read-only plan passed.
The new [owner steps](OPERATIONAL_ONESHOT_IDENTITY_RECOVERY_20261016.md) first
restart r4, then run the only current command.

2026-10-16 (later): the owner ran `7a5e785`; it is spent. It held in
preconditions before any change: the host had rebooted, and the r4 Warden
logon trigger restarted r4, so the pinned stopped-Warden contract cannot match
([hold](evidence/operational-recovery-7a5e785-hold.json)). `ab900e9` adds the
running-r4 scenario. It binds the live r4 run, fences and stops it, and
integrates Codex in the same sitting: `config.toml` is re-captured live, and the
rules, skill and metadata files stay pinned. Holds settle the fence first and
restore r4 only on a proven end. **558 serialized source/inert tests passed**;
the packaged read-only plan passed. That
[owner command](OPERATIONAL_RUNNING_RECOVERY_20261016.md) has since run and is
spent (see above).

2026-10-16: the owner ran `90c9c1d`; it is spent. It held in preconditions on
`PRESERVED_PID_OCCUPIED`: Windows had recycled the expired fence's PID 46440
for an unrelated `cmd.exe` ([hold](evidence/operational-recovery-90c9c1d-hold.json)).
`7a5e785` binds process identity to image and pinned creation bounds, waits
out the held observer's sterile detector and unreadable exiting rows without
accepting them, checks the pinned Docker pipe and R: workspace before any fence,
and guards the fence budget before the Warden trigger disable. **416 serialized
source/inert tests passed**; the packaged read-only plan passed. That
[owner command](OPERATIONAL_PID_IDENTITY_RECOVERY_20261016.md) has since run
and is spent (see above).

Current agent transition: [operational passover](AGENT_PASSOVER_20261015.md)
and [starter prompt](NEW_AGENT_PROMPT_20261015.txt). The owner will append the
latest PowerShell result; `90c9c1d` host acceptance is unknown at this checkpoint.
Reconcile that result first. Older launch instructions below are historical,
and their packages are spent; do not replay them.

Observer-only ACL compatibility is corrected at `90c9c1d`. **315 serialized
source/inert tests passed**, including real descriptor parsing and backing-file
custody fixtures; the packaged read-only plan passed. The new
[owner command](OPERATIONAL_OBSERVER_ACL_RECOVERY_20261015.md) reuses installed
r5 and existing sessions. Warden task rules remain unchanged. Actual protected
task/native checks and deployment acceptance are pending owner execution.

The owner ran `490bf2e`; it is spent. Its immutable observer file/record checks
passed, but the task ACL call held before any mutation. The verifier used the
Warden-only ACL policy and omitted the observer's original v8 Scheduler
projection/private backing-file validation. That source mismatch is proven;
the exact current live descriptor has not been read by the ordinary session.
The original tests stubbed the ACL boundary. The narrow correction above tests
actual descriptor parsing and the independently verified backing-file rules.
See [the current hold](evidence/operational-recovery-490bf2e-hold.json).

The observer compatibility correction is ready at `490bf2e`: 273 serialized
source/inert tests passed; the final verifier checked 120 actual immutable
observer files and its fresh public heartbeat; the actual packaged read-only
plan passed. The new [owner recovery](OPERATIONAL_OBSERVER_RECOVERY_20261015.md)
preserves the observer and reuses installed r5 and existing sessions. Actual
Administrator task/native evidence and deployment acceptance remain pending.

The `4eabf2e` recovery has now run and is spent too. Its public rejection names
PID 9612 and a command hash that exactly matches the old held supervisor
observer. This is another omitted historical process role, not a provider or
authentication failure. No new fence/task mutation/cutover was reached. The new
protected observer verification is described above; preserve the running
observer and all prior packages. See
[exact hash and public status evidence](evidence/operational-recovery-4eabf2e-hold.json).

The owner has now run `r428-op-recovery-01f782a`; it stopped in preconditions and
is spent. The process check omitted the already-reviewed legacy Codex/Claude MCP
bridge form. Read-only current process metadata reproduces that category;
no new fence, task change or cutover was reached. The focused correction at
`4eabf2e` passed 233 source/inert tests and its fresh packaged read-only plan
passed. That [replacement command](OPERATIONAL_CLIENT_RECOVERY_20261015.md)
has also run and is spent as described above. Preserve
both failed packages and all evidence. No new owner diagnostic is needed.

The delivered operational r5 launch has run and is spent. Installation and Codex
preflight passed, then admission fencing held before catalog acceptance/cutover.
The received diagnostic proves fence expiry without a release request and an
ended r4 Warden, with no listener. Source cleanup/task-transition repairs are
committed. The [first continuation](OPERATIONAL_RECOVERY_DELIVERY_20261015.md)
is also spent; the corrected replacement above is now the owner entrypoint. See also
[the hold evidence](OPERATIONAL_FENCE_HOLD_20261015.md). Do not repeat the original
owner command or treat source tests as deployment acceptance.

## Current operational repair â€” 15 October 2026

The owner-approved seven-part repair is on `fix/428-operational-repair`, based
on `c714854506c736431e6a0d5aaea2471aba8ab5ff`, in the separate local
`Pipeline-Mix-Model-Concurrent-428-repair` checkout. The installed runtime is
unchanged by this engineering session. The earlier implementation summary below
is historical and does not prove that the installed planning path is enabled.

Implemented source work includes corrected CPU admission units and recovery from
transient pressure; scoped repository preparation; initial output contracts and
deterministic handoff forms; two bounded format corrections; legacy snapshot and
submission-ledger tools; and a scoped, reversible Codex integration update.
Planning now connects actual board claims, native receipt reconciliation,
controller-owned file/test verification, independent content review and final
delivery. Researched pivots and typed fracture plans preserve original quality,
dispatch and elapsed-time budgets. Nested scope proofs cannot substitute for the
parent's final release criteria. Research parks pending siblings without charging
another attempt; the thirtieth quality failure remains locked.

The current owner-package design is documented in
[OPERATIONAL_OWNER_LAUNCH_R5.md](OPERATIONAL_OWNER_LAUNCH_R5.md). It upgrades the
verified 4.2.8 r4 baseline to a fresh r5 runtime, accepts an exact task catalog,
and enables the connected planning configuration only after protected evidence
checks. It contains no sign-in or late prompt. The installed catalog, provider
quotas, SYSTEM execution and useful-job completion still require actual host
acceptance. No old R5/R6/R7 command is an operational r5 deployment command.

The final integrated source regression at `aa7706e` passed **973 tests**, with
one skip and eight documented exclusions, in 281.64 seconds. Tests include real
temporary files and SQLite with inert provider/process ports. Independent review
found no remaining launcher or exact-source package-coherence blocker. Fresh
immutable packaging and both actual packaged read-only plans passed at source
`865a29b`; the delivered pins are recorded in [OPERATIONAL_R5_DELIVERY_20261015.md](OPERATIONAL_R5_DELIVERY_20261015.md).
See [VALIDATION.md](VALIDATION.md) for the verification boundary.

Known limits remain explicit. The strict published reasoning floors leave some
task-type/tier combinations without eligible routes or a different-family
reviewer. [OPERATIONAL_CATALOG_CANDIDATE_20261015.json](OPERATIONAL_CATALOG_CANDIDATE_20261015.json)
records the proposed 27 contract-bound profiles and every held comparison;
benchmark scores alone do not establish installed CLI support. Automatic
completion-audit dispatch and isolated repair callbacks are not configured in
the production controller. Their fixture implementations are not operational
self-healing. Specialist exam, YouTube and Antigravity integrations are unchanged.

Three selected existing quick-reference jobs are prepared for useful-work
acceptance after deployment, with input hashes and a durable submission ledger.
They have not been submitted by this repair session. Original legacy rows,
completed work, credentials and all earlier runtime packages are preserved.

## Historical implementation handoff

Current coding handoff: [root handoff](../../PIPELINE_4.2.8_AGENT_HANDOFF.md),
[implementation plan](../../tasks/plan.md), [remaining tasks](../../tasks/todo.md),
[owner launch runbook](OWNER_LAUNCH.md), and [release review](RELEASE_REVIEW.md).

All source implementation and release-packaging tasks (`P428-00` through `P428-27`)
are implemented and exercised in source/test fixtures on `feature/4.2.8-task-routing`.
Only `P428-28` (physical elevated owner execution of `run_428_launch.ps1 -Apply`)
remains pending owner execution; engineering sessions do not claim live host launch
or full SRS acceptance before that sitting completes.

## Implemented and exercised (`P428-00` through `P428-27`)

- Reproducible audit of the owner's two PDFs and JSON (`P428-00`, `P428-01`, `P428-19`);
  preserved reference inputs and numeric publisher observations; a readable 110-row
  matrix with five ranked profiles per task-type/tier combination, scores, reference
  evaluation costs, and explicit provider-diverse reviewer selection.
- Versioned task-type selection (`P428-02`) enforcing every assigned type's floor,
  different-model reviewer selection, maximum-effort tier-10 review and
  availability backoff. Held comparison entries cannot dispatch.
- Exact Argon Low/Medium/High binding proposals (`P428-03`) from an explicit captured Agy
  catalog and executable identity, with non-blocking availability handling for HTTP `429`
  quota responses vs hard hold on protocol/identity/cleanup failures (`P428-20`).
- Durable SRS/research/owner-approval/review/WBS/microtask planning journal (`P428-04`),
  immutable revision/evidence bindings and separate trusted evidence ports.
  Model text cannot create a human approval or a search receipt.
- Conservative controller-computed context budget (`P428-05`); model token estimates
  cannot bypass review/decomposition. A producer change invalidates an earlier
  independent review even when the SRS text remains unchanged.
- Planning intent integration (`P428-06`, `P428-07`) with the existing Chapter 06 job board and
  native prompt/route validation. Planning completions are semantically checked
  before commit and imported only after exact cleanup evidence. Existing jobs
  and captured policies survive the new job-kind schema migration (`P428-25`).
- Bounded runtime planning pump (`P428-07`) with out-of-band research worker execution,
  restart safety without duplicates, fair rotation across waiting tasks, and
  sanitized per-task status under `/tasks/submit` and `/tasks/status/`.
- Controller-owned research adapters (`P428-10`, `P428-11`, `P428-12`) for HTTPS
  Wikipedia/OpenAlex search with DNS/redirect/size/content-type guards, read-only
  Wiki RAG citations bound to manifest generation, and bounded asynchronous
  polling in `research428.db` outside shared worker slots.
- Dedicated owner approval broker (`P428-13`) in `owner428.db` with a separate
  owner approval secret (`owner_approval.secret` disjoint from `controller.token`),
  exact SRS/WBS digest binding, single-use challenge nonces, and automatic
  invalidation on revision change or upward complexity reassessment.
- Simple-task direct execution (`P428-14`) and complex-task WBS/microtask release
  (`P428-15`) with DAG cycle rejection, assembly/final-test dependency gates,
  and automatic halt into `WAITING_FOR_OWNER_APPROVAL` when reassessed complexity
  reaches `>= 8`.
- Durable 10/20/30 quality-failure lineage accounting (`P428-08`, `P428-16`),
  structured failure dossiers (`P428-17`), research-backed pivot (`10`, `20`) and
  fracture (`25`) transitions (`P428-18`), and locked-task decision packets (`30`).
  Availability failures do not consume quality attempts; fractures retain their parent budget.
- Completion audit and repair incident runtime (`P428-09`, `P428-21`) with dedicated
  repair profiles (`repair_claude`, `repair_codex`, `repair_agy`) in `repair428.db`
  and `SupervisorRepairAdmission428` (`P428-22`) enforcing the 4-seat total native
  CLI ceiling while prioritizing repair reservations ahead of new normal reservations.
- Prior R5/R6 repair custody and saved Fable `target-23` HTTP `429` replay
  verification (`P428-24`), stopped-runtime offline wheel installer (`P428-25`),
  single owner entry point (`run_428_launch.ps1`, `accept_428_native.py` â€” `P428-26`)
  supporting the live `AETHERDESK` `R4 v11` + `R6 target-23` hold baseline as well as
  `R6`/`R7` sitting receipts, and immutable release bundle preparation (`P428-27`).
- Two-Staged Concurrency + Conflict-Colored Provider Batching + Intra-Slot Agent Swarm
  (`P428-SWARM`: `src/cochem_pipeline/swarm_batch_428.py`, `src/cochem_pipeline/microtask_board_428.py`,
  `src/cochem_pipeline/resource_limits.py`, `src/cochem_pipeline/inference_policy.py`,
  `src/cochem_pipeline/planning_gateway.py`, `src/cochem_pipeline/worker.py`,
  `pipeline_tests/test_swarm_batch_428.py`): 4 Layer-2 OS execution slots (`6144 MiB` RAM,
  `4096 MiB` V8 heap with `--max-old-space-size=4096 --max-semi-space-size=16`, `96` processes,
  `0x08000200` creation flags) paired with Layer-1 intra-slot subagent swarms (`claude` 20/depth 3,
  `codex` 20/depth 2, `gemini`/Agy 64/depth 2), Case B disjoint provider wave packing with exact
  per-subagent routed `(model, reasoning_effort)` and `10/20/30` `AttemptLedger` pivot escalation,
  Case C global cross-slot and in-flight same-task file locking (`microtask428_file_locks` +
  `WAITING_ON_FILE_LOCK`), `JobStore.complete` auto-commit, and partial-batch per-microtask commit
  with individual `AttemptLedger` failure isolation.

## Remaining owner action (`P428-28`)

1. Run the single elevated owner command in `docs/4.2.8/OWNER_LAUNCH.md` in an
   Administrator Windows PowerShell 5.1 window as `AETHERDESK\ansac`.
2. Complete any front-loaded interactive prompts (dedicated repair-profile sign-ins
   if not yet cached, and owner approval secret setup) during the initial 20-minute
   window, then walk away after the green banner while the unattended install,
   native acceptance, idle drain, stop, SYSTEM SQLite migration, cutover, and
   catalog publication verification complete.
