# Planning lifecycle repair — 15 October 2026

The default controller now supplies its actual `AttemptAccountingRuntime` to
the microtask board. `PlanningOutcomeRuntime` reconciles released native route
reservations, exact attempt/fencing identities and verified cleanup into the
same durable ledger. A restart cannot double-charge a processed reservation.
A deterministic ledger lease also repairs the interruption window between
lease creation and outbox insertion.

Quality categories (`code`, `protocol`, verification failures) consume the
quality budget. Provider/auth/quota/context/resource waits consume no quality
failures. An output-format correction is retained separately and is not
misreported as either a quality failure or a quota event. Unknown release
reasons produce a visible evidence hold. Aggregate swarm reservations are not
charged again; the existing child accounting owns those outcomes.

At the tenth, twentieth or thirtieth committed failure, the reconciler records
the boundary and registers fresh research bound to that exact ten-failure
window. Only published, digest-verified three-channel research can produce a
dossier. A dossier is not a model assessment: boundaries remain held awaiting
the independent pivot review; the thirtieth failure remains locked for the
owner. No guessed root cause, synthetic search result or fresh attempt budget
authorizes dispatch.

Cancellation now uses the real `board_status` API and includes batch jobs.
Durable cancellation obligations are written before the root changes stage.
Failures remain `CANCELLATION_PENDING` and reconcile on subsequent polls or
restart. Completed tasks enqueue deduplicated completion audits only from a
committed job receipt plus verified cleanup. `QUEUED` does not mean an audit
passed. Unconfigured independent repair execution callbacks fail explicitly;
this change does not launch repair agents.

The controller accepts the integrator's artifact runtime and prepares its
project capture before intake. Actual physical artifact execution, test
receipt production, task-catalog authority, and protected deployment are
separate integration slices.

Validation: 40 serialized in-process tests across planning lifecycle/outcome,
attempt-accounting, workflow, pivot and owner-decision suites passed. Tests
cover missed reservations, replay, bounded polling, cleanup holds, quota and
format separation, exact ten-failure research registration, cancellation
restart, audit deduplication and interrupted lease recovery. These are source
tests, not host acceptance or evidence that automatic pivot review execution
has been completed.

## Reviewed microtask pivot dispatch

The next bounded slice connects a ten-failure microtask dossier and published
three-channel research to a `PIVOT_REVIEW` job on the same board. Its captured
model family differs from the failed family and meets the next-tier floor.
The typed result supplies a new assessment, evidence-based cause synthesis,
hypotheses and a concrete changed approach. Only the controller applies it.

An accepted pivot creates a new microtask job capture with the exact selected
profile, effective complexity, reassessed tags, dossier and changed approach.
It never resumes the old blocked job. The original lineage retains its full
failure count: 10 and 20 allow researched pivots; 30 stays locked. Review
availability does not charge the failed task's quality budget. The exact
selected profile is committed with the ledger pivot, allowing restart recovery
if the secondary pivot projection was not written. Unmeasured model families
cannot bypass the reasoning floor through the previous family-name fallback.

An existing swarm test had chosen Flash for tier 6 despite lacking a qualifying
measured score. The test now selects a qualifying different family; a separate
regression proves that the unsupported selection is rejected.

Explicit remaining adapters: fracture proposals retain their evidence in
`FRACTURE_PLAN_REQUIRED`; a newly high-tier child without an approval receipt
holds as `PIVOT_OWNER_APPROVAL_REQUIRED`. Planning-stage and simple-execution
pivots hold as `PIVOT_SCOPE_ADAPTER_REQUIRED` pending their reclassification and
approval-aware journal adapters. These states are not completed work or live
acceptance. Review jobs and failure research are included in durable cancellation.

The subsequent planning adapter replaces `PIVOT_SCOPE_ADAPTER_REQUIRED` for
SRS, review, WBS, microtask planning/assessment and simple execution. It records
a controller-owned journal route override with the exact selected profile,
sticky floor and existing lineage. The journal validates subsequent completion
against the new capture. SRS output cannot lower that floor. A simple task that
now needs complexity 4+ or multiple types re-enters `REVISING_SRS`; its new SRS
then follows research, independent review, WBS and the existing 8–10 owner gate.
Complexity 1–3 single-type pivots expose `execution_pivot` for the simple adapter.
No terminal job or failure counter is reset. Planning stages after promotion
continue the preserved planning lineage, while existing WBS child policy stays
unchanged. Original approved SRS receipts stay valid only for their exact revision.

## Physical verification recovery

The microtask board now consumes committed verifier feedback only after the
original producer fence has been reconciled as one quality failure and its
lineage is ready. A green-test or content-review rejection regenerates the
assigned assembly ancestors and their downstream final checks. Assembly may
repair only its assigned implementation ancestor paths. A red-baseline failure
regenerates the final check alone. At a ten-failure boundary, recovery remains
held for the existing researched pivot; no counter or terminal job is reset.

Each new capture carries the exact verifier feedback and sealed-test producer
identities. Repeated polling retains that capture; committed new failures create
new identities. Completed board fragments carry controller-owned producer job,
attempt and fencing references so downstream physical snapshots can select the
exact repaired producer within the same plan generation. Old jobs and evidence
remain immutable. The artifact runtime separately enforces these references and
test-file custody; model text does not establish either proof.

Validation: 32 serialized source tests passed across physical-recovery board,
microtask dependency, pivot, planning lifecycle and release suites. The recovery
fixtures use the real temporary SQLite board and attempt ledger with inert
verifier ports. These tests do not attest native provider or host deployment
acceptance, and do not activate aggregate swarm execution.

High-tier child pivots now use the existing authenticated owner approval path.
The journal records a request tied to the exact review hash, boundary, tier,
task types and original SRS/microtask scope. The board exposes that request as
`HOLD_OWNER_APPROVAL`; the existing `approve_child_microtask` operation records
the matching authenticated receipt. The pivot bridge resumes that reviewed
boundary after approval and restart, retaining all ten failures. Changed review
evidence needs a new approval. This does not change the parent generation or
invalidate unrelated completed children. Fifteen serialized child approval,
pivot and microtask board tests passed; no owner action was performed.
