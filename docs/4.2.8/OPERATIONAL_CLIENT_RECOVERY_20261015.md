# Corrected MCP client recognition — owner recovery

The owner ran `r428-op-recovery-01f782a` and it stopped in preconditions,
before any new fence, task change, catalog acceptance or cutover. The process
classifier omitted the existing, previously reviewed legacy Codex/Claude
`cochem_mcp` clients. It also treated shell commands that merely mentioned
`cochem_pipeline` as native pipeline activity. Both defects are corrected in
`4eabf2e9e385cefd2204559eeb4cc355e9b17b6b`.
The spent launcher did not record the rejected PID, so the exact triggering
process in that run is not established; the observed legacy forms reproduce
the rejection in the old classifier.

## Run once as owner

Use this fresh command once in **Administrator Windows PowerShell**. Existing
MCP clients can remain open. No sign-in, browser, choices, restart or later
input is planned. Leave PowerShell and the computer running; protected
verification and native acceptance continue unattended.

```powershell
C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -File "C:\Users\ansac\CoChem427\r428-op-recovery-4eabf2e\run_operational_428_launch.ps1" -LaunchManifest "C:\Users\ansac\CoChem427\r428-op-recovery-4eabf2e\launch-manifest.json" -LaunchManifestSha256 c4f0a26ad04e1a53a810c8fd6d3370ab637906e57d312cdecaff3d09f37fd9f2 -Apply
```

The local instruction sheet is `W\RETURN_SETUP_428_OPERATIONAL_RECOVERY_4eabf2e.txt`;
its tracked mirror is under `docs/deployment/windows-deployment-next/`.
Do not reuse the original `865a29b` launch or the spent `01f782a` recovery.

Success is `R428_OPERATIONAL_RUNNING_VERIFIED`. If held, preserve the final
sanitized JSON and do not repeat this one-use command. Status is written to:

`C:\Program Files\CoChem\R428OperationalRecovery-20261015-a62bffb278044fffbaf21207a866ff81-515bacb6893f4453822944b1e3235f1b`

## What the correction permits

The legacy exemption requires the exact protected Python executable, exact
`cochem_mcp` module invocation, Codex or Claude provider, and the fixed
`bridge.local.json` configuration path. Extra arguments, a different config,
foreign executables and unknown native roles still hold. The modern MCP form
is unchanged. Arbitrary shell/search text no longer counts as Python execution.
Future process rejections expose only a PID, allowlisted process name/reason
and command hash; raw arguments and credentials are not published.

One read-only ordinary-user snapshot recognized 20 modern and four legacy MCP
processes. Two SYSTEM Python processes concealed their image and command line
from this session. The snapshot does not prove quiescence or protected ACLs.
The owner entrypoint must inspect those processes with its existing elevated
visibility and holds if their role is still unknown. No process exemption is
granted based on an access-denied result. No process was closed or modified.

The new recovery identifier preserves every spent attempt. The launcher reopens
the original pinned protected installation, baseline, fence and task records,
then checks current processes, task definitions/ACLs, instances, last-run values
and controller port before mutation. It reuses the completed installed r5
payload and existing sign-ins. A fresh fence must prove idle board/catalog
authority. Catalog acceptance, cutover and scoped Codex integration follow
only if those checks succeed. Existing rollback and publication checks remain.

## Package evidence

| Item | Value |
|---|---|
| Unchanged installed application source | `865a29b113a8b59c822f6aa4d921a45c18407fe5` |
| Corrected launcher source | `4eabf2e9e385cefd2204559eeb4cc355e9b17b6b` |
| Launch manifest SHA256 | `c4f0a26ad04e1a53a810c8fd6d3370ab637906e57d312cdecaff3d09f37fd9f2` |
| Packaged launcher SHA256 | `c7234bfc529d4132486114796ad284b6364103713b77871b4f0c16f7d3b90ea6` |
| Recovery instructions SHA256 | `a7f5e355af4a09c35c623a006ad4147d13ee6481faf467ac0dac6d465d3b683f` |
| Source-test evidence SHA256 | `5f370bd5b050f4ecede23e8ab2f034d40d88f90829ca3dd3d1fabf3ae501ea6b` |
| Source-test log SHA256 | `db3033022d8e633083dd7384d072ce48e592bbed3de52187fa5bc12031b29e74` |
| Packaged read-only plan log SHA256 | `e83a71063ca5ea3203a2662b2f01107e3efcef0365e364a86a1f927bf73f1ede` |

The exact root source passed **233 serialized source/inert tests in 48.51s**,
without skips or deselections. The nine files cover recovery, package contracts,
launch ordering, fence cleanup, diagnostic projection, process roles, release
construction, admission fences and owner catalog handling. The actual packaged
Windows PowerShell 5.1 read-only plan returned `READ_ONLY_PLAN_VERIFIED`.
No providers, deployment or host lifecycle actions ran during verification.

Offline preparation verified all 15 direct package inputs and 406 original
installation inputs, totaling 130,560,536 bytes. Keep those original input
directories in place. Evidence is in
`C:\Users\ansac\CoChem427\r428-op-recovery-tests-4eabf2e`; tracked copies use
LF line endings, while pins above refer to unchanged original local files.
The independent review is preserved alongside those records.

This is source/package verification, not actual deployment or useful-job
acceptance. The agent has not run Apply. After owner success, verify controller
identity, refreshed Codex MCP access and actual job receipts/deliverables.
The three selected existing useful jobs remain unsubmitted. Strict coverage
holds, quota/backoff, credentials, databases, old captures, budgets, four slots,
R: and specialist integrations are preserved. Completion-audit dispatch and
independent repair callbacks remain unconfigured.
