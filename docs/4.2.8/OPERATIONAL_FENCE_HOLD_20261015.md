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

Return the printed report path or error. Do not rerun the deployment.

## Independent source defect under repair

`Start-OpFence` currently returns its context only after readiness validation.
If validation throws, the caller loses the task/nonce/receipt context needed to
release its own temporary database writer fence. This can leave that fence held
until its bounded expiry. The source defect is confirmed by inspection; its role
in this host failure is **not yet established**. A regression and repair are in
progress. No cleanup, recovery, restart, or replacement Apply was performed by
the agent.

Any continuation must bind the saved installation receipt, verified exact task
state and catalog publication state. Reusing an installed root requires explicit
verification; the old fresh-install command is not a continuation mechanism.
