# Catalog acceptance cannot complete on the installed r5 runtime

The owner ran `d5d6094`; it is spent. For the first time on this host the
following all passed:
- the running-r4 preconditions;
- the Codex re-capture and plan check;
- the admission fence (structural one-shot identity);
- the exact r4 stop and fence release;
- the catalog phase's start custody.

The installed catalog phase then rejected its request in `decode_request`
(`task_catalog_acceptance_428.py:114`, "stale or claims its own authority"). Nothing
was published. The launcher brought up a restore fence, restarted r4 and
verified its health in under 30 s, so r4 is serving again (PID 42380). See
[the preserved public reports](evidence/operational-recovery-d5d6094-hold.json).

## Cause of this hold

The 865a29b task-catalog request was prepared from the r5 bootstrap
`pipeline.json` routing, which is the installed baseline policy `6a76497a…`. The
job board's active policy is `c8444fe2…`, which r4's own launch published on
2026-10-14 (bundle `3dab7f2`, request `b8ef2785…`). `compile_change(baseline, r4
proposal)` rebuilds `c8444fe2…` exactly, and the installed `decode_request` gives
the host error offline.

## Further blockers found before shipping another package

An independent review of a re-prepared request, followed by direct source
checks, found that catalog acceptance cannot complete with the installed
865a29b runtime, whatever the launcher does:

1. **Bootstrap routing.** After publication, `enabled_candidate`
   (`task_catalog_acceptance_428.py:360`) requires the bootstrap's routing to
   equal the published policy. A request re-prepared for `c8444fe2…` therefore
   fails *after COMMIT* with the baseline bootstrap, leaving r4 stopped with no
   automatic restore. A bootstrap routed to `c8444fe2…` also needs the retired
   `gemini-3.1-pro:high` removed from the Gemini bindings.
2. **Missing runtime attribute.** `run_acceptance` reads
   `runtime.catalog_containment_id` (line 454). The real `Runtime` has no such
   attribute; only the unit tests' fake runtime did. The first real probe raises
   `AttributeError`.
3. **Codex effort evidence.** `record_result` requires `reasoning_effort`
   evidence (model, binary digest, version) for every probe, but for Codex
   `effort_contract()` returns `None`, so the native runner never records it.
   Every Codex probe is rejected.

Items 2 and 3 are in the installed runtime and need a corrected, reviewed
runtime and a new installation; a launcher or recovery package cannot fix them.
This catalog path had never executed on a real runtime: r4's 2026-10-14 catalog
used `CatalogController`, and the r5 tests used fakes.

## What changed in source (`scripts/` and tests only)

- **Pre-stop catalog-request check.** The launcher establishes one validated
  catalog-request authority (`Resolve-OpCatalogRequest`). After the fence is
  READY, and before any task change, `Assert-OpCatalogRequestBoard` checks that
  the request names the board's live policy and task catalog. A stale request
  now holds before r4 is touched.
- **Replacement request preparation.** The preparer can re-prepare the request
  against the pinned, rebuilt active policy (`--catalog-request active`). It
  refuses while the bootstrap routing differs from that policy (blocker 1).
- **Tests.** `test_operational_catalog_request_428.py` reproduces the host error
  with the installed code.

No new owner package is delivered. r4 remains the serving 4.2.8 runtime; Codex
is still configured to reach it through the `cochem-pipeline` MCP table, and its
board has Codex routes.
