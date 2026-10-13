# R6 native acceptance hold, 13 October 2026

**Diagnostic received and root cause resolved in source:** the first Agy request
was successful with no tool steps. This build advertises its global CLI runner
registry; the installed parser incorrectly treated it as the selected agent's
permissions. See `R6_AGY_REGISTRY_REPAIR_2026-10-13.md` for evidence, strict
binary/agent binding and the fresh owner continuation. The diagnostic request
below is historical and must not be repeated. Deployment remains unverified.

The owner ran immutable `r6-launch-7451831` at 09:34 local time. That package
is now spent and must not be replayed. Its contents and all earlier evidence
remain unchanged.

## Verified progress and remaining uncertainty

The submitted transcript confirms all 18 Codex, Claude and Agy sessions were
verified, including six `AGY_MODELS_CATALOG_VERIFIED` results. The sitting then
completed knowledge verification and the six-worker agent phase before holding
in native model acceptance. There is no evidence that another sign-in is needed.

The saved function/line trace ends at frozen `worker.py:1054`, which converts
`AgyIdentityError` (including its tool-registry subclass) to
`ProviderFailure('compatibility')`. This identifies the response validation
boundary, but does not distinguish a model mismatch, reroute diagnostic or
tool-registry violation. Do not loosen the parser or claim a root cause before
reading that attempt's saved metadata.

Sitting: `R6Sitting4.2.7-windows-20261012-e7c0c0d611214705b350d5bad65c9321`.
Native root: `R6Acceptance4.2.7-windows-20261012-v1-native-344364d3b6434266a29c7bb61a654220`.
Both are under `C:\Program Files\CoChem`.

The pre-cutover R4 restoration used attempt v9 but did not return verified
success. A read-only observation found `retarget-receipt.json` and
`start-intent.json`, with neither a start receipt nor a held-start record at
that observation. Port 47824 and authenticated `/health` responded from R4
PID 26220, instance `fc3751f579664da39c759d483bb686ea`, admission capacity zero.
This proves a responding R4 controller at that time, not a successful restore
transaction or readiness to admit work. R6 was not cut over.

## One read-only evidence export

`scripts/inspect_r6_native_hold.ps1` reads only the exact attempt's receipts,
one recorded disposable probe, and R4 v9 restoration/task metadata. It reduces
existing native streams to fixed protocol flags and counts; it does not export
prompts, responses, tool names, session IDs, credentials or URLs. It never runs
providers, starts/stops tasks, changes permissions or deploys. The only new file
is a sanitized JSON report in the ordinary deployment workspace. Missing or
unreadable records are recorded without dropping the other observations.

The owner runs the staged copy because Windows denies the engineering process
access to the private acceptance records:

```powershell
C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -File "C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\inspect-r6-native-hold-20261013-v1.ps1"
```

Return the printed report path. No deployment replay or sign-in is requested.
The report is diagnostic evidence, not an acceptance receipt. Its lightweight
JSON projection does not replace the production parser.

Twenty serialized Windows PowerShell fixture tests passed. They cover the
complete report builder against inert receipts, exact attempt-path binding,
malformed/unreadable data, model/reroute/tool distinctions, terminal styling,
same-handle hashing, size bounds, read-only task projection and secret exclusion.
These tests do not attest native provider support or Windows deployment.

Future continuation must preserve completed knowledge/custody evidence and
sign-ins, resolve the native incompatibility and bind the observed R4 state.
No new deployment package has been issued for this hold.

## Source reporting repair

The source-only failure projection now preserves the fixed `ProviderFailure`
type, its allowlisted category and the explicit `AgyIdentityError` or
`AgyToolRegistryError` cause. The public PowerShell consumer independently
validates those fields. Exception text, native response text and arbitrary
category/type values remain excluded. The previous immutable packages are
unchanged. This improves the next package's diagnostics; it does not resolve or
accept the current native compatibility failure.

The combined reporting, launch, custody-continuation and diagnostic regression
run passed **74 tests in 22.21 seconds**, serialized under repository Python
3.12. The new regression covers the actual ProviderFailure-from-Agy-error chain
through Python projection and Windows PowerShell public reporting.
