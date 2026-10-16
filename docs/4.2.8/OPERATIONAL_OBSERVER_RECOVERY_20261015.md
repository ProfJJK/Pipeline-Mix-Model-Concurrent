# Held observer recognition — owner recovery

> **Spent — do not rerun.** The owner ran `490bf2e`; immutable observer files
> and public records passed, then the observer task ACL check held before
> mutations. The new verifier incorrectly reused the Warden-only ACL policy.
> The original observer installer uses the v8 Scheduler projection/private
> backing-file validation. See `evidence/operational-recovery-490bf2e-hold.json`.
> A separate correction is being prepared; preserve this package unchanged.

The `4eabf2e` recovery stopped before mutations because the launcher rejected
PID 9612 as `PROTECTED_PYTHON`. Its reported command hash exactly matches the
preserved 4.2.7 held observer invocation. The current public heartbeat identifies
the same PID and exact native creation FILETIME. The observer's protected helper
and configuration permanently disable paid repair, component recovery and
Warden actuation. The new recovery classifier had omitted this historical role;
earlier R6 process checks recognized it. This is a launcher compatibility defect.

The source correction is `490bf2e5c8273406e5beeeaea515fbddac22966a`.
It permits only the exact current observer parent/child pair after checking the
protected immutable files, current no-actuation records, fresh heartbeat, exact
SYSTEM task definition and process identities. It retains file/process handles
and rechecks live task/heartbeat evidence at subsequent recovery boundaries.
Unknown or changed processes still hold. Observer failures now retain bounded
sanitized proof frames without publishing raw arguments, paths or credentials.

The initial operational launch already installed r5 but held at admission
fencing. The old Warden was found ended. The later `01f782a` and `4eabf2e`
recoveries stopped in preconditions; neither started a fresh fence or cutover.
The new package reuses that exact installed r5 payload and existing sessions.
It does not repeat installation or sign-in, and does not stop the observer.

## Owner command

Run this fresh command **once** in Administrator Windows PowerShell. Leave that
window and the computer running. No browser, sign-in, choices, reboot or later
input is planned. The owner alone executes Apply; the agent has not run it.

```powershell
C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -File "C:\Users\ansac\CoChem427\r428-op-recovery-490bf2e\run_operational_428_launch.ps1" -LaunchManifest "C:\Users\ansac\CoChem427\r428-op-recovery-490bf2e\launch-manifest.json" -LaunchManifestSha256 b94f115342e07a8e5270da04aa669d1d3da4a77353a88fce674d0fde7535e3af -Apply
```

Success is `R428_OPERATIONAL_RUNNING_VERIFIED`. If held, preserve its final
sanitized JSON and do not rerun the spent command. Keep all prior packages,
captures, credentials and input directories. Do not close the observer or MCP
clients. The local sheet is `W\RETURN_SETUP_428_OPERATIONAL_RECOVERY_490bf2e.txt`;
the tracked copy is under `docs/deployment/windows-deployment-next/`.

Status directory:
`C:\Program Files\CoChem\R428OperationalRecovery-20261015-a62bffb278044fffbaf21207a866ff81-54a66375d4004523806f5fdaa296918c`

## Verified evidence and limits

- **273 serialized source/inert tests passed in 64.66 seconds**, with no skips
  or deselections, on the exact root commit. Ten test modules cover process
  roles, observer proof, recovery, fencing, package contracts and release flow.
- The final verifier ran read-only against the actual observer files and public
  records: **120 retained immutable file streams**, including 109 installed
  application files, and the fresh PID 9612 heartbeat passed in 0.716 seconds.
  No task, native process-identity or provider calls ran in this check.
- The actual packaged Windows PowerShell 5.1 read-only plan returned
  `READ_ONLY_PLAN_VERIFIED`. All 15 direct inputs and 406 external installation
  inputs (130,560,536 bytes) were checked during preparation.
- Independent source review found no blocking issue. The separate package
  review is saved with the evidence. Administrator-only task/native process
  checks remain mandatory at owner execution; these tests do not attest
  deployment, catalog acceptance, healthy runtime or successful useful jobs.

| Item | SHA256 or commit |
|---|---|
| Unchanged installed application source | `865a29b113a8b59c822f6aa4d921a45c18407fe5` |
| Corrected launcher source | `490bf2e5c8273406e5beeeaea515fbddac22966a` |
| Launch manifest | `b94f115342e07a8e5270da04aa669d1d3da4a77353a88fce674d0fde7535e3af` |
| Packaged launcher | `a85a02953de092d768ffa9a2c85ee0c75fa790dc8ea2826ffc0f6de7b85c846b` |
| Recovery contract | `34ff44fe184ac47d11960e3fb37417ea1e722d001eb9f191d751c232e0be137c` |
| Source-test evidence | `6bbe572ec7debe525912d6ba73a8a9ef46a6b2fa72881f9fe075668c2f8c12eb` |
| Original local source-test log | `b4cc21a2d488aee8fee2ff8adb77533e2bc541b543f23eea5bf9b028f81b7c37` |
| Original local observer file/record proof | `8474212dbfcf17c0ac26d360c828accf3d68ede29f38e605e2fa74435ccf0cfc` |
| Original local read-only plan log | `e83a71063ca5ea3203a2662b2f01107e3efcef0365e364a86a1f927bf73f1ede` |

Evidence directory: `C:\Users\ansac\CoChem427\r428-op-recovery-tests-490bf2e`.
Tracked evidence is under `docs/4.2.8/evidence/operational-recovery-490bf2e/`;
original local log pins refer to the original bytes, before Git line-ending
normalization. The file-only replay script is preserved there for audit.

Strict catalog coverage, quota/backoff, repair budgets, four shared slots, R:,
databases and specialist integrations remain unchanged. Completion-audit
dispatch and independent repair callbacks remain unconfigured. The selected
useful jobs remain unsubmitted until verified recovery and live MCP access.
