# Accepted task catalog authority repair

TASK_PLAN admission and native dispatch now require the captured task catalog to
exist byte-for-byte in the protected board's immutable catalog history. Publisher
benchmark scores and a job payload's host_accepted flag cannot authorize dispatch.
Both paths use the current protected generation for target retirement and capacity;
historical accepted job captures remain unchanged. Non-planning legacy routes keep
their existing capture semantics.

Runtime initialization adopts the exact catalog read by protected
PlanningConfig.read_catalog, only with catalog journal activation enabled. It
initializes the installed baseline once and preserves a later published generation
on restart. An unrelated installation baseline, missing authority, or stale policy
binding holds rather than silently trusting a payload. PlanningController must use
Runtime.accepted_task_catalog for its initial new-work catalog.

Verification uses temporary SQLite, compiled synthetic acceptance receipts, and
inert model outputs. Existing planning tests now install those accepted fixture
generations instead of relying on research candidates. This is source evidence,
not native selector acceptance or deployment approval. The owner publication must
provide the protected accepted catalog and enable catalog_activation before startup.

The serialized focused run passed 38 tests; a second planning/execution regression
run passed 25. Two pre-existing base-checkpoint issues were reported to the integrator:
the positional schema-migration bug (already repaired in a36e486) and an MCP test
fixture using an unvalidated coding-project dictionary. Further final test evidence
is reported with the commit handoff.
