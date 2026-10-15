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
