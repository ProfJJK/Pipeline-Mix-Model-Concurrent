# R6 native command exit — 13 October, 11:37 run

**Update, 13 October:** the requested v2 report was received. Agy Flash Low
and Claude Haiku Medium passed; Codex Luna Medium failed at startup with the
exact fingerprint of Windows error 1. See
[the RAM cwd repair](R6_CODEX_RAM_CWD_REPAIR_2026-10-13.md). The diagnostic below
is complete; do not ask the owner to repeat it. The following text records the
earlier evidence request.

The owner ran `r6-launch-d6d336e`. It is spent; preserve its contents and all
protected evidence. No new deployment or sign-in command is ready.

All 18 Codex/Claude/Agy sessions were verified. Knowledge and agent acceptance
completed. Native acceptance then raised `ProviderFailure('code')` at original
installed worker.py:1033. That line is reached for a nonzero CLI exit that the
typed native-failure parser did not recognize. It occurs before response
validation. The public report does not identify the failed target, exit code,
or diagnostic reason. Do not infer that the registry repair passed on this run,
or that the failure is authentication, quota, or a model selector problem.

R4 was restored as v10 with verified health. The returned controller reports
admission capacity zero and `warden_controller_ready=false`; restoration is
not evidence of readiness to admit production work. R6 was not cut over.

## Exact saved evidence

All these roots are under `C:\Program Files\CoChem`:

- Sitting: `R6Sitting4.2.7-windows-20261012-6d84c3a598054685ad8060f4282c584c`.
- Native: `R6Acceptance4.2.7-windows-20261012-v1-native-c9ff4ce625824ebaafff6f4d216f271d`.
- Auth: `R6Acceptance4.2.7-windows-20261012-v1-auth-3f38a0d197444bc885366496eb549ac6`.
- Knowledge: `R6Acceptance4.2.7-windows-20261012-v1-knowledge-bcc27b51c50d4bf7bd733cfecffcdec2`.
- Agent: `R6Acceptance4.2.7-windows-20261012-v1-agent-6ca1c0225e8a4e6caac5c4fd0349558b`.
- Stop v9 receipt SHA256: `1f5bd8bd8207d8756ab13939cb663f4b2b9d72de52aed07ec96cc3b2b6a4ce9b`.
- R4 v10 start receipt SHA256: `fbfa6309cc0a8475ef8063342760750ad8208b91d8fa9f55733693e6dca97974`.
- R4 v10 retarget receipt SHA256: `30b09e86c8e921cec5abdc46c00fcbc0ea86e93188cecc2d0e4651d6c878bbc9`.

The native child log is `native-3dcf80f7d69d4731b4e58cc307ee2905.log`
inside the sitting root. The ordinary engineering token was denied access to
both native `held.json` and `native\native-held.json`.

## Read-only diagnostic

Source `scripts/inspect_r6_native_hold.ps1` now produces schema
`cochem-r6-native-hold-diagnostic/2`. The earlier v1 staged copy remains unchanged.
The new script reads the exact attempt above, its bound reservation and failed
native streams, preceding target summaries, and R4 v10 task/receipt metadata.
It handles all approved provider/model families without assuming which failed.

The exported JSON contains hashes, signed/unsigned exit codes, typed envelope
metadata, fixed diagnostic indicators, known option names and protocol counts.
It never exports raw answers, prompts, URLs, credentials, sessions or arbitrary
provider error text. Indicators are observations, not availability classification
or native acceptance. A mismatched stream hash is explicitly reported.

No provider, login, task change, process start/stop, cleanup, permission change or
deployment occurs. Only a fresh sanitized report is written in the ordinary
deployment workspace. Windows private receipt permissions require the owner's
existing Administrator window for this read-only operation.

```powershell
C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -File "C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\inspect-r6-native-hold-20261013-v2.ps1"
```

Return the printed report path. No deployment replay or new sign-in is requested.
Source, repository mirror and staged v2 script share SHA256
`9ad6581e8e06291f170fb77a22c973dfa74d04ceb275270892c2f961948e971d`.

Forty serialized Windows PowerShell source/fixture tests passed in 15.46 seconds.
They exercise the complete report builder with synthetic receipts for all three
providers, previous accepted targets, exact path bindings, malformed/unreadable
records, signed exits, hash mismatches, output bounds, protocol observations,
terminal styling and secret exclusion. No protected state or providers were
executed. These tests do not attest the cause of this host failure.

After receiving the report, diagnose the actual exit before issuing a fresh
continuation bound to the successful R4 v10 restoration. Reuse verified sessions
and completed knowledge. Keep the existing unattended-input contract and retain
every old package. R7 remains separate from this R6 repair.
