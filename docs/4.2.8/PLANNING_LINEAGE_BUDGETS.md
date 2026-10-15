# Planning lineage budgets across physical generations

The operational repair requires every dispatch, including a formatting repair,
to retain its overall dispatch and time budget. A new physical retry/pivot job
ID must not restart that budget. `planning_budgets_428.capture_lineage_budget`
is a controller-only helper for that insertion boundary.

## Integration order

1. Reconcile prior board/native/physical outcomes and initialize the stable
   `AttemptLedger` lineage outside the job-board write transaction. Existing
   lineages must never be recreated. Fracture members resolve to their original
   root; ordinary WBS microtasks have independent roots.
2. Build the final physical payload and its scoped Chapter 06 routing policy.
3. Inside `JobStore._write()`, return an existing identical job before capture.
4. Call `capture_lineage_budget(conn, job_id, payload, policy,
   attempt_ledger=accounting_or_ledger)` before inserting that job or its root.
5. Insert the root, call `capture_workflow(...,
   max_dispatches=budget.max_dispatches)`, then insert the TASK_PLAN job with
   `max_attempts=budget.max_attempts`.
6. Handle `LineageBudgetHold.reason` as a durable controller hold. Do not catch
   it and retry insertion with default budgets or a new lineage identifier.

The helper reads the actual attempt ledger through an attached read snapshot
on the caller's board connection. It requires READY, completed required
research, a retained reasoning floor/pivot model, and no active quality lease.
Failures 10/20 remain held until their real pivot completes; failure 30 remains
locked. The quality allowance is `10 - (failures % 10)`.

Recommended call sites are the simple execution materializer, individual
microtask board materializer and planning gateway stage insertion. Their
payloads use exactly `PlanningOutcomeRuntime.lineage_for_job` semantics.
`PIVOT_REVIEW` and aggregate swarm jobs are deliberately excluded from ordinary
quality capture: their existing stable control-job IDs / child accounting must
not be used to pretend that research has completed or double-charge children.

## Preserved authority and enforcement

New immutable sidecar records associate historical/current physical IDs with
the stable root and record the cumulative ceiling and remaining allowance.
No historical job, routing-policy snapshot, expiry, or workflow capture is
rewritten. An existing capture is returned unchanged on repeated polls.

The first new generation adopts actual historical `dispatches`, including
availability and formatting attempts. Later generations retain the original
finite ceiling, not a previously reduced per-generation allowance. A configured
zero means unlimited only when there is no prior finite limit. Exhaustion raises
an explicit hold; it is never passed to routing as zero/unlimited.

The earliest existing expiry survives every generation. Applying a new finite
time limit to old unlimited history starts at the oldest routing capture, not
at the current poll. `ensure_job` validates the controller sidecar against the
new payload, scoped policy and insertion budgets, then stores its absolute
expiry on the first routing insert.

Read-only route previews, atomic selection and reservation all check summed
dispatches across mapped physical IDs. Two fracture children captured before
either dispatches cannot each spend the same remaining allowance. Existing
unmapped/legacy jobs retain their previous behavior until a new generation
adopts the lineage; the historical records themselves stay immutable.

Tests use temporary SQLite databases and inert board claims only. They do not
constitute native provider, Windows deployment or physical acceptance evidence.
