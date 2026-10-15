# Operational r5 admission-fence hold — 15 October 2026

The owner ran `r428-op-launch-865a29b`. Its immutable package is spent and must
not be replayed. The stopped r5 runtime installed successfully; Codex preflight
completed. The sitting held at `admission_fence` before `stop_previous`, catalog
acceptance, cutover, or Codex integration. No useful-job acceptance is claimed.

The public report records only `RuntimeException`, not its cause. Fresh MCP
health and project calls both returned connection refused. That does not prove
which process ended or why; do not claim the previous runtime remains healthy.
The ordinary agent process was denied access to the private owner evidence.
Sanitized observations are in `evidence/operational-r5-hold-a62bffb.json`.

## One read-only owner export

`scripts/inspect_operational_fence_428.ps1` is restricted to sitting
`a62bffb278044fffbaf21207a866ff81`. It reads bounded JSON metadata, exact matching
fence tasks and the Warden task, recorded process identities, and listener
metadata. It changes no protected state and executes no provider or task.
Raw messages, logs, task arguments, XML, and credentials are not exported.
Ten inert PowerShell fixture tests passed. The deployment-workspace copy and
repository mirror match SHA-256
`a0f121d44084654221ab3e8b72488dfb4d5a330c5f404584aec6dc31c047ae68`.

Run once from the owner's existing Administrator PowerShell window:

```powershell
C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -File "C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\inspect-operational-fence-428-20261015-v1.ps1"
```

This export has now been received; **do not repeat it or the deployment**.

## Received host evidence

The 18:57 UTC sanitized report is preserved in
`evidence/operational-r5-fence-diagnostic-a62bffb.json`. It verifies the existing
installation receipt, original baseline and owner-result records. The exact
fence reached READY with every active-work count zero. No release record was
present. Its final result is `FENCE_EXPIRED`, `released=false`, and
`lock_released=true`; the matching task ended with code 2 and its recorded PID
is absent. The Warden definition and ACL still match the baseline, but the task
has zero instances, last result 1, and no controller listener. The original
controller PID is absent. Neither task was restarted by the agent.

This establishes the unreleased-fence outcome and the unavailable old controller.
It does not recover the exact original PowerShell throw, which the old launcher
discarded. No catalog acceptance or cutover was reached. A separate narrow
continuation is being prepared to verify protected evidence directly, prove the
board idle, reuse the completed original installation, and continue without
starting the old controller merely to stop it again.

## Independent source defect repaired

The spent launch's `Start-OpFence` returned its context only after readiness validation.
If validation throws, the caller loses the task/nonce/receipt context needed to
release its own temporary database writer fence. This can leave that fence held
until its bounded expiry. The source defect is confirmed by inspection; its role
in this host failure is **not yet established**. The source repair retains
caller-owned context before task creation; incomplete task creation grants no
cleanup authority. Releasing a lock requires exact task, native process,
nonce, configuration, request, database and receipt bindings. Stale readiness or
nonzero accounting still prevents admission, while the exact owned lock can be
released safely. A verified expired fence is recorded without replaying release.
Sanitized error substage, function/line and cleanup outcome are included in the
public status. Independent review completed; 103 focused source/inert tests
passed. A second regression reproduced seven cases where queued, running or
never-run task observations incorrectly counted as terminal. The corrected
idle-state and result checks passed 80 focused launcher/cleanup tests. Those
source tests do not establish which throw occurred on the host.
No cleanup, recovery, restart, or replacement Apply was performed by the
agent. The delivered immutable package remains unchanged.

Any continuation must bind the saved installation receipt, verified exact task
state and catalog publication state. Reusing an installed root requires explicit
verification; the old fresh-install command is not a continuation mechanism.

## Recovery packaging

The offline recovery preparer validates the original twelve launch inputs and
406 installation inputs before writing a fresh user-owned package. It preserves
the application source at `865a29b` and replaces only the owner launcher, adding
the pinned original manifest, exact-attempt recovery instructions and separate
launcher test evidence. The recovery identifier names one new protected sitting;
an existing sitting is spent and cannot be replayed. The preparer passed 32 inert
fixture tests. The final root regression passed 200 tests, the actual packaged
read-only plan passed, and independent review verified the package inputs.
Use the [new recovery delivery record](OPERATIONAL_RECOVERY_DELIVERY_20261015.md).
Owner execution and actual deployment acceptance are still pending.
