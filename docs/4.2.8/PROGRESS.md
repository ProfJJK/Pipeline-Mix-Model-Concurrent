# 4.2.8 source progress

This branch is an implementation checkpoint, not a deployed or launch-ready
release. The running host remains on the last verified R4 restoration v11.
The R6 native failure and tested source repair are documented separately in
`../R6_NATIVE_LATEST_2026-10-13.md`; no spent package has been modified.

## Implemented and exercised

- Reproducible audit of the owner's two PDFs and JSON; preserved reference
  inputs and numeric publisher observations; a readable 110-row matrix with
  five ranked profiles per task-type/tier combination, scores and reference
  evaluation costs. Missing scores are not estimated.
- Versioned task-type selection enforcing every assigned type's floor,
  different-model reviewer selection, maximum-effort tier-10 review and
  availability backoff. Held comparison entries cannot dispatch.
- Exact Argon Low/Medium/High binding proposals from an explicit captured Agy
  catalog and executable identity. Missing catalog slugs remain held.
- Durable SRS/research/owner-approval/review/WBS/microtask planning journal,
  immutable revision/evidence bindings and separate trusted evidence ports.
  Model text cannot create a human approval or a search receipt.
- Conservative controller-computed context budget; model token estimates
  cannot bypass review/decomposition. A producer change invalidates an earlier
  independent review even when the SRS text remains unchanged.
- Planning intent integration with the existing Chapter 06 job board and
  native prompt/route validation. Planning completions are semantically checked
  before commit and imported only after exact cleanup evidence. Existing jobs
  and captured policies survive the new job-kind schema migration.
- A bounded runtime planning pump now submits and imports those jobs, survives
  restart without duplicates, rotates fairly across waiting tasks and persists
  sanitized per-task status. Authenticated `/tasks/submit` and `/tasks/status/`
  expose intake and progress. They cannot set a route or manufacture approval.
  Large status projections use the existing serialized HTTP projection lock.
  The feature defaults off and requires a pinned protected host-accepted catalog,
  v3 routing and four shared slots. The research candidate cannot enable it.
- Durable 10/20/30 quality-failure lineage accounting, research/pivot/fracture
  requirements and locked-task decision packets. Availability failures do not
  consume quality attempts; fractures retain their parent budget.
- Separate repair incident queue with dedicated-profile checks, maximum-effort
  tier-10 selection, priority over competing new quota reservations, and
  repository/commit/test/cleanup evidence contracts. No repair agent is launched.

The latest serialized regression run passed 472 tests with two real-process
tests excluded. A separate existing HTTP regression run passed 54 tests, with
ten coding tests excluded from that run. These cover the planning chain, restart,
cleanup, approval and research boundaries, quota accounting, configuration and
existing routing behavior. One subsequently added runtime-maintenance integration
test also passed. All model execution evidence is an explicit inert
fixture. Native providers, protected state and host tasks were not exercised.

## Remaining implementation and acceptance

1. Actual controller internet/wiki/paper research adapters with durable evidence
   and the separate authenticated human approval interface. The implemented pump
   waits at these boundaries; ordinary MCP/API credentials cannot approve an SRS.
2. Materialize/reassess execution microtasks on the job board, including explicit
   assembly/final-test dependencies and approval of newly high-complexity work.
   Integrate the lineage attempt ledger with actual runtime outcomes.
3. Connect completion audits and the independent repair supervisor to verified
   shared-slot/quota ownership and safe direct repository execution. The queue
   library is not an executing self-healing system.
4. Resolve the explicit benchmark/reviewer gaps without silently lowering floors
   or inventing missing effort results; complete installed CLI acceptance for
   Argon and every newly activated selector.
5. Complete the exact R6 host-error verification/continuation, update installer
   bindings, and prepare/review a fresh consolidated owner launch package.

This checkpoint does not include a reviewed 4.2.8 launch command. All delivered old
4.2.7 packages, credentials, databases and historical receipts remain preserved.

See `LAUNCH_PATH.md` for the release sequence and the owner's single-sitting
requirement. No host launch or sign-in is needed to continue source integration.
