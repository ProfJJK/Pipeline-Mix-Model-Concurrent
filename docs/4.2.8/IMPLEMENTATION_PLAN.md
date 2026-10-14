# Pipeline 4.2.8 implementation and acceptance

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
