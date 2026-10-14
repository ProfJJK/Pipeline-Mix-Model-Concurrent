# Routing evidence and remaining limits

The owner confirmed the two PDFs and JSON in
`D:\Gdrive\__agentic\pipeline_plans\4.2.8` as the supplied rating documents.
They were read as reference inputs; implementation remains in the local Git
checkout outside Google Drive. Extracted document text and the original JSON
are retained under `references/`.

`scripts/audit_428_routing.py` reproduces the numeric observations, audit JSON,
versioned candidate and readable `ROUTING_MATRIX.md` from the preserved inputs.
Each published observation records its exact model/effort identity, page URL,
capture timestamp and source digest. Compact numeric projections retain the
digest of their original public-page capture; full captures are archived at
`C:\Users\ansac\CoChem427\research-428-benchmark-captures-20261013`.

The audit found 281 supplied/published score differences larger than the
whole-unit display rounding tolerance and 263 structural findings. The latter
include repeated fallback families, below-floor choices and reviewers that can
be the producer itself. These are not 263 separate runtime failures.

There are complete, non-estimated publisher observations for 34 of 37 profiles.
Flash 3.8 Low and Argon Low/Medium do not yet have complete captured breakdowns;
their missing values are not interpolated. The public rating comparison is
separate from what the installed subscription CLI actually supports. In
particular, published DefaultFallback configurations do not attest a strictly
pinned single-model CLI result.

The candidate shows exactly five comparisons in every one of 110 rows. The
PDFs permit effort variants in positions four/five; changing effort never
qualifies as an independent model for review or pivot. Tiers 1–7 rank eligible
profiles by reference evaluation cost, then score; tiers 8–10 rank by score,
then cost. Tier 10 uses maximum effort. The displayed cost is the publisher's
Intelligence Index evaluation cost per task, not this task type's measured
cost, a subscription charge, or the owner's remaining quota.

The supplied floors still leave one execution gap (SCI-FORMAL tier 10) and
20 producer/reviewer combinations without an eligible different-model review.
Those combinations are explicitly held. Comparison entries below a floor are
shown as HELD and cannot execute. `routing-decision-packet.json` packages the
3 missing effort profiles (`flash38-low`, `argon-low`, `argon-med`), the
`SCI-FORMAL` tier-10 execution gap, the 20 single-family reviewer gaps, and
the 7 concrete two-family calibration floor deltas alongside the calibrated
5-option proposal (`floor_changed` / `uncalibrated_floor` explicitly retained).
The default unattended runtime policy remains `hold_strict_supplied_floors`;
the five-comparison request has not been treated as permission to fabricate
scores or silently waive a reasoning floor.

Primary references used for availability/selector constraints include the
[Agy headless CLI documentation](https://www.agy.dev/docs/cli/headless/),
[Agy model documentation](https://www.agy.dev/docs/models/), and
[Google's Gemini model documentation](https://ai.google.dev/gemini-api/docs/latest-model?hl=en).
Exact benchmark-page URLs and numerical provenance are attached to each record
in `benchmark-observations.json`. Future release dates and unobserved selectors
are not assumed.

Intra-slot swarm batching (`src/cochem_pipeline/swarm_batch_428.py` and
`src/cochem_pipeline/microtask_board_428.py`) preserves per-microtask routing
authority: ready microtasks with disjoint file footprints (Case B) pack by
provider family (`claude` $\le 20$ / depth $3$, `codex` $\le 20$ / depth $2$,
`gemini`/Agy $\le 64$ / depth $2$ per slot across the 4 OS slots), while each
spawned subagent executes at its own microtask's exact routed `(model, reasoning_effort)`
tier (`candidate_profiles[0]`, honoring `AttemptLedger` 10/20/30 upward floor and
model pivots). Overlapping file footprints (Case C) admit at most one microtask
per shared file group into `microtask428_file_locks` across all 4 slots (preserving
in-flight `DISPATCHED` batches across wave transitions) and hold remaining tasks in
`WAITING_ON_FILE_LOCK` until lock release.

