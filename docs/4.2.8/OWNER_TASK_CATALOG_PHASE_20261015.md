# One-shot owner catalog phase

`cochem_pipeline.owner_task_catalog_428` is source for the protected SYSTEM
phase of the owner-reviewed installer. It is not a command to run from an agent
session, a service launcher, or a deployment by itself.

The owner wrapper supplies these arguments to the protected Python runtime:

```text
-I -m cochem_pipeline.owner_task_catalog_428
  --bootstrap-config <protected bootstrap.json>
  --bootstrap-sha256 <reviewed SHA256>
  --request <protected request.json>
  --request-sha256 <reviewed SHA256>
  --output-root <fresh empty protected directory>
  --timeout-seconds 7200
```

Optional arguments are `--poll-seconds` (0.01–5, default 1) and
`--flash-context-limit`. The overall deadline must be 1–14400 seconds.
The bootstrap must enable catalog activation, disable task planning, and retain
four shared execution seats. The wrapper owns singleton, task/process containment,
initial authentication, stopped prior-runtime proof, and final task selection.

The phase retains input and output path custody, verifies exact bootstrap/request
bytes, and uses the normal guarded runtime without starting its daemon or HTTP
listener. A single monitor calls `tick(admit_jobs=False, catalog_poll=False)`.
Acceptance uses the existing shared reservations; an admission wait reuses only
the same request's committed evidence. Deadline, cancellation, critical guard,
or monitor failure revokes further probes. There is no sign-in or input prompt.

Fresh outputs are `phase-started.json`, `accepted-catalog.json`, `pipeline.json`,
and either `result.json` or `held.json`. Existing outputs are never overwritten.
The final normal configuration loader and protected catalog reader must validate
the accepted catalog before success. Runtime resources are drained while request
custody remains held. Files and committed evidence survive failures.

The final schema is `cochem-owner-task-catalog-result/4.2.8`. Successful status
`TASK_CATALOG_CANDIDATE_READY` includes `configuration_path`,
`configuration_sha256`, `catalog_path`, `catalog_sha256`, request/bootstrap pins,
per-row route coverage, and `cleanup_verified`. It explicitly does not request
cutover or claim ordinary-job execution. Provider exhaustion can leave genuine
coverage holds; five rankings and reasoning floors are preserved.

The wrapper must use `publication_state`, not a local progress flag, to reason
about restoration. A coherent final journal read reports `COMMITTED`,
`NOT_COMMITTED`, or `UNKNOWN`. The `publication_proof` includes active policy and
catalog digests, any matching committed catalog digest, and
`catalog_probe_cleanup_verified`. A post-commit file/coverage failure is still
`COMMITTED`. An absent terminal receipt or forced process termination is always
`UNKNOWN`. A held result separates `runtime_resources_closed` from successful
acceptance; it does not assert native cleanup solely because `Runtime.close`
returned. Only a proven `NOT_COMMITTED`, closed resources, clean probe reservations,
and the wrapper's independent old-task/configuration/board compatibility checks
can permit restoration. Never blindly restart an old runtime after publication.

Source tests exercise temporary files and SQLite with injected runtime and Git/
native ports. They prohibit child processes. They do not prove SYSTEM ACLs,
installed selector support, Windows deployment, or useful-job acceptance.
