# Observer task ACL compatibility — owner recovery

The owner ran `490bf2e`; it is spent. It passed the observer's immutable file and
public record checks, then held before runtime mutation at `Assert-OpObserverTask`
line 330, which called `Assert-428TaskAcl`. The rejection identified parent PID
3132 and the exact historical observer launcher hash. See
[the preserved public reports](evidence/operational-recovery-490bf2e-hold.json).

The new observer verifier incorrectly reused a Warden-specific permissions
policy. The observer's original installer instead uses `task-private-acl-v8.ps1`.
That policy supports Windows Scheduler's three-entry service descriptor only
after independent proof that the exact task backing file retains a protected
SYSTEM/Administrators-only full-control ACL. The original observer fixture
substituted a no-op for the ACL check, so the previous 273-test run missed this
compatibility regression. The current live descriptor/backing file is not
readable by the ordinary agent process; the exact live representation remains
an owner-run check, rather than an inferred fact.

## Correction and verification

Source `90c9c1df400ed831c1bbb82683d05e4eaaba8847` restores v8-equivalent checks
only for `CoChem-4.2.7-HeldSupervisorObservation-20261007-r3-v1`.
The common Warden validator and all other task policies are unchanged.
The backing-file path is fixed; the read verifies size, digest, non-reparse
ancestry, exact handle path and single-link identity. It denies writes/replacement
while reading the independent ACL, then closes the handle immediately. Unsafe
service or file grants, missing custody and different task names still hold.
No task, permission, process or protected configuration is modified by this check.

New fixtures exercise actual Windows descriptor parsing and a real temporary
file held against writes. The regression demonstrates that the old Warden
validator rejects the supported projection while the observer validator accepts
it only with private backing-file proof. Integration fixtures now exercise the
real ACL validator. **315 serialized source/inert tests passed in 78.13 seconds**,
without skips or deselections, across eleven test modules. Independent source
review found no blocking issue. The actual packaged Windows PowerShell 5.1
read-only plan returned `READ_ONLY_PLAN_VERIFIED`.

These checks are not actual protected task/native acceptance or deployment.
The previous file/heartbeat verification is retained; task/native checks still
run at owner execution. The observer is left running. Existing sign-ins, the
installed r5 payload, databases, quotas, budgets, four shared slots and R: remain
unchanged. The package continues the original exact installed-r5 recovery, with
the original runtime source fixed at `865a29b`.

## Run once as owner

In Administrator Windows PowerShell, run the following new command once.
No sign-in, browser, choice, reboot or later input is planned. Leave the window
and computer running while verification and acceptance continue unattended.
The agent has not executed Apply.

```powershell
C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -File "C:\Users\ansac\CoChem427\r428-op-recovery-90c9c1d\run_operational_428_launch.ps1" -LaunchManifest "C:\Users\ansac\CoChem427\r428-op-recovery-90c9c1d\launch-manifest.json" -LaunchManifestSha256 a0cb076c2bfa31600d60de1c4969372601af5ac64a44bdc0b67390445d1f22a2 -Apply
```

Success is `R428_OPERATIONAL_RUNNING_VERIFIED`. If held, preserve and return the
final sanitized JSON; do not repeat the spent command. Do not stop the observer,
close MCP clients, repeat sign-ins or remove old evidence. All prior packages
remain unchanged. The owner sheet is
`W\RETURN_SETUP_428_OPERATIONAL_RECOVERY_90c9c1d.txt`, mirrored under
`docs/deployment/windows-deployment-next/`.

Status directory:
`C:\Program Files\CoChem\R428OperationalRecovery-20261015-a62bffb278044fffbaf21207a866ff81-09bc46790fa14c2cbf85450f158550fe`

## Package pins

| Item | SHA256 or commit |
|---|---|
| Unchanged runtime source | `865a29b113a8b59c822f6aa4d921a45c18407fe5` |
| Launcher source | `90c9c1df400ed831c1bbb82683d05e4eaaba8847` |
| Launch manifest | `a0cb076c2bfa31600d60de1c4969372601af5ac64a44bdc0b67390445d1f22a2` |
| Packaged launcher | `5b8c49821dba41c2fcab3abdcb302d22a89b1da6574c2e08a26ddab2c889de4f` |
| Recovery contract | `1bac767ec41a6b03361a3f9248571ad1bf212307f277222d1a27374686ceddfd` |
| Source-test evidence | `1cb888e697b91917240f89d8ac01f4e09c3eb1726dd105da21bfbdc7ba51f243` |
| Original local source-test log | `187e7ec3b1b59fe6ea79a7006f9c678aea9de7a44bae7fe140fbd8d072a265e0` |
| Original local read-only plan log | `e83a71063ca5ea3203a2662b2f01107e3efcef0365e364a86a1f927bf73f1ede` |

Preparation verifies 15 direct package files and 406 original installation
inputs, totaling 130,560,536 bytes. Preserve the original input directories.
Evidence and the independent package review are in
`C:\Users\ansac\CoChem427\r428-op-recovery-tests-90c9c1d`, with tracked copies
under `docs/4.2.8/evidence/operational-recovery-90c9c1d/`. Tracked logs use LF;
the table pins their unchanged original local bytes.

The selected useful jobs are still unsubmitted. Live controller identity,
catalog acceptance, Codex MCP access and actual successful job deliverables must
be verified after owner recovery. Strict coverage holds remain in place, and
completion-audit dispatch/independent repair callbacks remain unconfigured.
