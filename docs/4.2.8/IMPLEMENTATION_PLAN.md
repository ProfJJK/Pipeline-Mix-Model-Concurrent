# Pipeline 4.2.8 implementation and acceptance

This document retains the initial requirements and sequence. The current detailed
coding plan is [tasks/plan.md](../../tasks/plan.md), with the authoritative remaining
checklist in [tasks/todo.md](../../tasks/todo.md) and entry point in the
[root handoff](../../PIPELINE_4.2.8_AGENT_HANDOFF.md).

Owner request: 2026-10-13. Source baseline: 4554b67. Implementation branch:
`feature/4.2.8-task-routing`, outside Google Drive. The supplied Drive PDFs/JSON
are reference inputs, not executable authority. Delivered 4.2.7 bundles remain immutable.

## Confirmed decisions

- Complexity 10 review uses a different tier-10 underlying model at its maximum effort.
- Only complexity 8–10 needs owner approval of the current plan, architecture and SRS.
  Lower-complexity multi-type work needs WBS decomposition, not owner approval.
- All 4–10 tasks collect internet, wiki RAG and scholarly research and get independent
  plan improvement. Low-complexity multi-type or oversized tasks also get higher-tier
  SRS review and decomposition. Context fit includes instructions, evidence and output
  reserve, not just the SRS text.
- Routing checks every task-type floor. A good aggregate cannot hide a weak domain.
  Unavailable or below-floor models cannot be dispatched as degraded fallbacks.
- Availability failures move through eligible candidates, then bounded exponential
  backoff with full jitter and restart from the primary. They do not consume quality
  cycles. Ten failed quality cycles require a research dossier and pivot/fracture.
  Thirty failed quality cycles across the lineage lock further work. Fracturing cannot
  erase history or reset a failed task's budget.
- Approval binds the exact plan/architecture/SRS revision. Material revisions invalidate
  approval. Children are reclassified individually; orchestration/assembly/final testing
  are explicit jobs with their own routing and dependencies.
- Pipeline repair has separate identities, a durable out-of-band queue, tier-10-only
  routing and highest priority among eligible work. Quota exhaustion waits; it cannot
  create quota, steal active leases, bypass host protection or authorize elevation.
- All owner deployment interaction is at the beginning, within 20 minutes. No planned
  late sign-in/reboot/continuation. Source tests do not attest Windows deployment.

## Implementation sequence

1. Preserve and audit all supplied routing inputs; identify score/provenance, floor,
   effort, reviewer and subscription-cost problems. Produce reproducible audit output.
2. Implement versioned task-type routing, exact Gemini Argon candidate selectors,
   capability-floor enforcement, independent reviewer selection and backoff tests.
3. Implement ingestion/SRS approval/research/review/WBS/microtask transitions with
   revision-bound evidence and durable lineage retry accounting.
4. Connect those contracts to the existing controller, Chapter 06 reservations,
   native adapters and status projections without changing old workflow captures.
5. Add completion spot-checks and an out-of-band repair authority that retains the
   host's owner-only administrative boundary and serial execution constraints.
6. Reconcile R6's latest native failure from its exact protected records; never replay
   a spent sitting. Build a new consolidated owner package only after source checks
   and evidence binding are complete.

## Release criteria

All branches of the new workflow have controller-level regression tests; no job can
skip required research/review/approval, dispatch below a floor, self-review by changing
effort, reset attempts through fracture, or activate an unverified native binding.
No benchmark estimate is represented as an observed native capability. Old captures
remain replayable. Four shared execution slots, credentials, databases, budgets and
R: are preserved. Installer/rollback and native acceptance remain owner-run.

## Current host state

The owner's `r6-launch-d19b42c` run is spent. On 2026-10-13 it verified all 18
sessions and proceeded through knowledge and agent phases, then held in native
acceptance with `ProviderFailure: code`. R6 was not activated. R4 restoration v11
reported verified health; admission capacity was zero. The received v3 diagnostic
identifies Claude Fable 5.1 High with a failed result and HTTP 429 indicator; the
owner reports likely exhausted Fable quota. Its private native root is
`R6Acceptance4.2.7-windows-20261012-v1-native-47e4889af6284a9fad018142a14d5371`.
The ordinary agent token was denied access. No sign-in repetition or deployment
retry is justified by that public failure alone. See
`../R6_NATIVE_LATEST_2026-10-13.md` for the source HTTP-client classifier repair,
its tests and the remaining exact-host-result verification.

## Two-Staged Concurrency & Intra-Slot Agent Swarm (`P428-SWARM`)

- **Layer-2 OS Execution Slots (`slot1`..`slot4`):** 4 isolated Windows worker slots
  with per-slot `ResourceLimits.swarm_default()` (`memory_limit_mb=6144`, `node_heap_mb=4096`,
  `node_options="--max-old-space-size=4096 --max-semi-space-size=16"`, `max_processes=96`,
  `swarm_mode=True`, `SWARM_CREATION_FLAGS=0x08000200`; `4 x 6 GiB = 24 GiB`
  bounded within the 63.7 GiB host RAM envelope).
- **Layer-1 Intra-Slot Native Subagent Swarms:**
  - `claude`: up to `20` subagents per slot (`80` across 4 slots), `max_nesting_depth = 3`.
  - `codex`: up to `20` subagents per slot (`80` across 4 slots), `max_nesting_depth = 2`.
  - `gemini` (Agy): up to `64` subagents per slot (`256` across 4 slots), `max_nesting_depth = 2`.
- **Conflict-Colored Wave Packing (`swarm_batch_428.py`, `microtask_board_428.py`):**
  - **Case B (Disjoint Files):** Ready microtasks with disjoint file footprints pack by
    provider family up to `max_agents_per_slot` with monotonically increasing `batch_seq` across
    waves, overflowing into additional batches when needed, with each subagent executing at its
    microtask's exact routed `(model, reasoning_effort)` tier (including post-pivot `AttemptLedger`
    floor and model escalations).
  - **Case C (Shared / Overlapping Files):** At most 1 representative microtask from any
    overlapping file group is admitted and locks its file footprint globally across all
    4 slots in `microtask428_file_locks` (preserving active locks held by in-flight `DISPATCHED`
    batches in the same or other tasks); conflicting ready tasks are held in
    `WAITING_ON_FILE_LOCK` (`job_id=None`) until the active lock holder completes.
- **Partial-Batch Per-Microtask Commit & Failure Isolation:**
  In a batch of $N$ microtasks where $k$ succeed and $N-k$ fail validation (supporting both
  mapping and list `subagent_outputs`, as well as `JobStore.complete` auto-commit), the $k$
  valid microtasks commit `COMPLETED` immediately (releasing their file locks and
  unlocking downstream dependents), while only the $N-k$ failed microtasks record
  individual `AttemptLedger` quality failures (`10/20/30` accounting), release their
  file locks, and transition to `PENDING_RETRY` / `HELD`.

