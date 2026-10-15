# Selected useful-work intake after operational deployment

`scripts/submit_428_selected_work.py` is a separate unprivileged client for the
owner-approved useful-work selection. It is not imported by the installer. It
does not delete/archive live jobs, bulk-import a backlog, change routes or quotas,
sign in, or start a controller/provider. The script has not run against the live
controller. Source tests use loopback HTTP, temporary SQLite and inert workers.

The approved preparation remains immutable in:
`C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\backlog-preparation-20261015\review-v1`.

| Input | SHA256 of exact file bytes |
|---|---|
| `useful-work-selection.json` | `68790ffc1bfa2e9be6c8c520aefa983c8cd92126f54c1c9ffd5ff03b66ad3474` |
| `resolved-recovery-plan.json` | `f5b8f7b3c521ae2c0f7f9a0a8768bd0bc3cd856226603cef9b5d48f367b5163b` |

Its three quick-reference tasks retain these deterministic identities:

- `legacy428-8cd59498011699ca843c312d25708ce3840f7e25ebeaa6ecbac0e8c35c4dd7e9`
- `legacy428-91a7b8beafae3e02d3c0233a2cf3b1e35473ed137fb6f0fce8b1c62fec093153`
- `legacy428-188e929d221b78155dc88095d490b5f74a69f465fff08eb7b2d5bdd9ec6a7c7e`

The exact text excerpts are embedded in their prepared initial objectives, along
with output formats, checks and source limitations. Inputs are rehashed before
submission. Exam/YouTube work is excluded; no specialist configuration changes.

## Controller and transport prerequisites

After the owner deploys and refreshes Codex, the agent must compare the new
controller's health identity against the successful owner deployment receipt.
Save that verified identity to a new ordinary local JSON file:

```json
{
  "schema": "cochem-backlog-controller-binding/1",
  "version": "4.2.8",
  "instance_id": "ACTUAL_VERIFIED_CONTROLLER_INSTANCE",
  "pid": 12345,
  "process_started_at": 1234567890.0,
  "source_root": "ACTUAL_VERIFIED_INSTALLED_SOURCE_ROOT"
}
```

The example values are placeholders, not an accepted host identity. Hash that
file and the existing client configuration without reading or copying its bearer
token into a report. This is agent-side evidence preparation, not another owner
deployment step. A running service alone is insufficient: live health must match
all five identity fields, report `task_planning.status=ENABLED` and
`execution_materialization=CONNECTED`, and have no trip errors. The client also
reads configured projects and refuses a missing project or `windows-acceptance`.
Quota waits are left intact; zero current admission capacity does not justify
changing models or resubmitting the same work.

Use the same permanent local ledger path on every invocation, for example
`review-v1\selected-submission-ledger.db`. Never remove or switch this ledger to
force another submission. Use a fresh evidence destination each time.

```powershell
& 'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\.venv\Scripts\python.exe' -I scripts/submit_428_selected_work.py `
  --selection <absolute-useful-work-selection.json> `
  --selection-sha256 68790ffc1bfa2e9be6c8c520aefa983c8cd92126f54c1c9ffd5ff03b66ad3474 `
  --plan <absolute-resolved-recovery-plan.json> `
  --plan-sha256 f5b8f7b3c521ae2c0f7f9a0a8768bd0bc3cd856226603cef9b5d48f367b5163b `
  --controller-binding <absolute-verified-controller-binding.json> `
  --controller-binding-sha256 <actual-file-sha256> `
  --client-config <absolute-existing-pipeline-client.json> `
  --client-config-sha256 <actual-file-sha256> `
  --ledger <absolute-permanent-selected-submission-ledger.db> `
  --destination <absolute-new-evidence-directory>
```

Default invocation inspects without reserving or posting jobs. Once the verified
deployment is available, the existing owner authorization permits the agent to
run the same prepared selection with `--submit` and another fresh evidence
destination. The reviewed source checkout and actual pins must replace the
placeholders; do not paste this template as a deployment command.

## Once-only behavior and completion evidence

Each selected row must exactly match its pinned recovery-plan row. A durable
SQLite `RESERVED` record binds its request, original aliases and plan before the
single POST. An authenticated exact-ID GET must establish either a matching
task or explicit `404/TASK_NOT_FOUND`. Other HTTP failures and internal projection
errors do not prove absence. If a POST times out, the client performs only exact
GET reconciliation. An absent reserved task remains held; there is no automatic
POST retry. A changed controller identity or input holds the remaining series.

`started.json` and `result.json` contain sanitized identities, hashes, statuses
and error types. A crash may leave only `started.json`; the durable ledger still
prevents a duplicate POST. Existing historical source captures stay unchanged.

Submission is not acceptance. Follow each retained task ID through planning,
research/review when required, physical artifact verification and final release.
Verify the requested JSON/Markdown files, hashes and evidence-linked assertions.
Report quota waits or owner-review gates as waits. The transport always reports
`completion_verified=false`; it cannot establish native execution or successful
useful work from acknowledgement alone.
