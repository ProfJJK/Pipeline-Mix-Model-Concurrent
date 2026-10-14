# Pipeline 4.2.8 coding handoff

**Owner instruction:** complete the remaining 4.2.8 coding, testing and release
preparation using an owner-managed Gemini 4 engineering swarm. Launch only when
4.2.8 is ready. This handoff assigns the work; it does not start agents or deploy.

## Start here

1. Read `AGENTS.md`, this file, `tasks/plan.md`, and your assigned item in
   `tasks/todo.md`. The checklist contains remaining work, not claims of completion.
2. Start from branch **`feature/4.2.8-task-routing`** in
   **https://github.com/ProfJJK/Pipeline-Mix-Model-Concurrent**. Do not start from
   an older main, R5 branch, installed runtime, or an old deployment bundle.
3. Implementation baseline: **`c33c7ea2a9d7c655b6998081080b4eae2273ee1b`**.
   The handoff commit follows that baseline and contains the authoritative task
   list. Preserve later work. Check branch, HEAD, status and remote before editing.
4. Complete P428-00/P428-01 first; they establish worktree-correct testing and
   cross-agent interfaces. Assign one integrator for shared files and merges.
5. Deliver small reviewed commits with focused test evidence. Do not turn a
   missing integration into a permissive stub, fake receipt or skipped check.

Repository checkout on AETHERDESK:
`C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent-r6`.
Its directory name is historical; the checked-out branch contains 4.2.8 work.
Use separate worktrees outside Google Drive. No reset, clean, force-push or
overwriting another agent's work. The owner authorizes direct repository
maintenance; pipeline repairs do not need the `pipeline_code` connector.

## What exists and what does not

| Area | Implemented source | Remaining integration |
| --- | --- | --- |
| Routing | Audited 11 task types, 10 tiers, five comparison profiles per row, explicit efforts, floors and independent-model selection | Resolve documented coverage gaps; bind current admission and installed native acceptance |
| Argon | Low/Medium/High catalog-binding proposal compiler | Actual captured CLI selectors, native effort acceptance and activation |
| Planning | SRS/review/approval/research/WBS/microtask reducers and durable journal | Real research and human approval adapters |
| Controller | Bounded planning pump, restart-safe board gateway, authenticated intake/status | Execution materialization and user-facing MCP/CLI entry points |
| Execution | Existing Chapter 06 scheduler, native isolation, coding coordinator and four-slot admission | Simple task and microtask execution, artifact dependencies, assembly and final release |
| Failures | Durable 10/20/30 attempt ledger and pivot/fracture primitives | Actual outcome binding, dossiers, reassessment, locked-task operator decisions |
| Self-healing | Completion sampling and independent tier-10 incident queue contracts | Audit executor, independent supervisor, quota/slot arbitration and repository repair execution |
| R7 | Protected catalog reader, journal, shared-slot probes, runtime integration and migration source | Adapt to 4.2.8 catalog authority; old owner bundles are not reusable |
| R6 | Source fixes for Agy registry, Codex RAM cwd, custody and Claude HTTP-client quota parsing | Exact private-result replay and fresh installed-state/continuation bindings |
| Release | R6/R7 build/installer patterns and immutable prior evidence | Versioned 4.2.8 offline artifacts, reviewed single owner command and host acceptance |

The new planning feature defaults off. `PlanningConfig.read_catalog()` requires
a pinned protected catalog with host acceptance; flipping a boolean in the
candidate JSON is not native evidence. `PlanningController.status()` explicitly
reports `execution_materialization=NOT_CONNECTED`. `PLAN_READY_EXECUTION_PENDING`
does not mean the user's deliverable is complete.

## Decisions already made by the owner

- Use the supplied two PDFs and JSON. Reference extracts and the JSON are in
  `docs/4.2.8/references/`; implementation must not run in Google Drive.
- Show five ranked model/effort options for every task-type/tier, with performance
  and honestly labelled cost metrics. The source PDFs permit effort variants in
  slots four/five; these are not different underlying models for review/pivots.
- Preserve minimum reasoning capability. Review a complex plan with a different
  underlying model one tier higher; at tier 10 use a different tier-10 model at
  its maximum effort. No substitution by changing effort on the same model.
- Only complexity 8–10 requires owner approval of the current plan/architecture/
  SRS. Lower multi-type tasks get decomposition, not an extra owner gate.
- Complexity 4–10 needs internet, wiki RAG and paper research and independent
  plan improvement. Lower multi-type or over-context tasks also need higher-tier
  review and WBS. Simple 1–3 single-type tasks that fit may go directly to execution.
- Microtasks are individually assessed, normally 1–5 and single-type, with explicit
  assembly and final-test jobs. Reassess after changes; never lower classification
  merely to avoid approval or fit an available model.
- Ten quality failures require researched pivot/fracture. After three blocks of
  ten, lock and present context, options, pros, cons and risks on the next status
  request. Availability failures do not spend that quality budget.
- Repair agents use dedicated profiles, tier 10 maximum effort and direct
  repository access outside the broken job pipeline. They log/version changes.
  They have highest priority for competing quota, not permission to create quota,
  preempt active leases, elevate or replace installed code unsafely.
- Four shared execution slots, six existing ordinary identities, Chapter 06,
  original databases/captures, credentials, budgets and R: remain preserved.
- Gemini Pro 3.1 was retired from Agy. Do not restore it as a fallback. Gemini 4
  Argon is the new requested family; confirm exact installed selectors.
- A separate consequence-risk floor was discussed but not adopted. Do not claim
  it implemented or add new owner gates without identifying the policy change.

## Swarm operation

The latest owner request authorizes parallel source engineering for 4.2.8.
Use one lane per isolated worktree/branch and one integrator. AETHERDESK's prior
crashes make unbounded native process fan-out unacceptable: keep at most four
heavy activities in total on this host, and serialize **all** builds/test suites
through the same host lock. This is not four activities per agent. Additional
parallel lanes can run on separate hosts without access to this host's live state.

The integrator owns changes to `runtime.py`, `store.py`, `config.py`, `service.py`,
`server.py`, routing admission, shared schemas, dependency locks, version metadata,
and launch composition. Lane agents primarily add their focused modules/tests;
shared-file changes require an explicit reservation or a small integration patch.
Do not merge several migrations concurrently. Do not edit another lane's branch.

Source-swarm authorization does not authorize engineering to run native agent
CLIs, live Wardens/daemons, SYSTEM probes, `-Apply`, protected writes, host service
actions or privilege elevation. Owner-managed engineering sessions are distinct
from the pipeline's future runtime repair agents. Do not launch the retired swarm.

## Last verified host evidence

R4 restoration **v11** returned verified SYSTEM health, with **admission capacity
zero**. This is the last recorded observation, not a fresh live census. R6 was
installed but never activated; R7 never cut over. The latest spent package is
`r6-launch-d19b42c`. All eighteen Codex/Claude/Agy sessions, knowledge and agent
checks passed in that attempt.

The received diagnostic identifies target-23, **Claude Fable 5.1 High**, with
failed result/exit 1 and HTTP 429. The owner reports likely exhausted Fable quota.
The repaired parser handles an additional anchored HTTP-client error format;
255 inert regression tests passed. Exact raw host text remains private, so source
tests do not prove that this particular saved output is now classified correctly.
Read `docs/R6_NATIVE_LATEST_2026-10-13.md` and the sanitized evidence it references.
Do not ask the owner to repeat that completed diagnostic or sign in again.

The release lane must include a protected, read-only replay of this exact saved
failure before cutover, then use the verified availability/fallback/backoff path.
Quota exhaustion must neither become a code defect nor count as successful native
acceptance. Unknown reset times stay unknown; generic 429 does not prove a finer
per-model quota boundary. Preserve all spent packages and partial receipts.

## Validation checkpoint

At implementation baseline c33c7ea:

- 472 serialized source/in-process tests passed; two real-process cleanup tests
  were deselected.
- A separate HTTP selection passed 54 tests; ten coding tests were deselected.
- One additional runtime-maintenance integration test passed after those runs.
- Earlier R6 parser/amendment selection: 255 passed. Do not add overlapping
  historical selections into a claimed full-suite total.

No tests here attest native provider, SYSTEM isolation, physical R:, service
activation, or a deployed 4.2.8 workflow. The exact source-test commands and the
worktree harness trap are in `tasks/plan.md`. Do not blindly run all pytest files:
some launch real processes or require protected host state.

## Release handover to the owner

The integrator must deliver a fresh immutable 4.2.8 package, command and manifest
pin, source/test evidence, all known holds, and reviewed recovery behavior.
No old R5/R6/R7 command is the 4.2.8 launch command. Avoid installing/activating an
intermediate revision merely because an old wrapper requires it; reconcile the
actual host state and select one reviewed migration path.

The owner has at most **20 minutes of active input at the beginning**. Total
unattended runtime can be much longer. Front-load prerequisites, UAC, necessary
OAuth and choices. Reuse sessions. Any necessary login must use the successful
fresh URL + Copy URL + manual browser + standard masked Windows dialog format
(respect Codex's browser-entered device code). No late prompt, restart or manual
continuation. Late failures preserve evidence and report/recover without input.

Only the owner runs the final elevated entry point, after all non-admin coding,
testing, build and review work is complete. P428-28 records that remaining physical
acceptance. Do not claim deployment based on a wheel, test count or health alone.

## Prompt for the swarm coordinator

> Take over Pipeline 4.2.8 from feature/4.2.8-task-routing. Read
> PIPELINE_4.2.8_AGENT_HANDOFF.md, AGENTS.md, tasks/plan.md and tasks/todo.md.
> Complete the open coding, integration, tests and offline release preparation.
> Assign bounded tasks by dependency and file ownership; merge and run tests
> serially on AETHERDESK. Preserve all existing source commits, host receipts,
> credentials, databases, captured policies and four-slot admission. Publish
> reviewed commits and update the task list with actual evidence. Deliver one
> fresh, reviewed 4.2.8 Administrator launch command with all active owner input
> in the first twenty minutes; do not execute it. Do not mark source fixtures as
> native acceptance, lower reasoning floors silently, or fabricate receipts.
