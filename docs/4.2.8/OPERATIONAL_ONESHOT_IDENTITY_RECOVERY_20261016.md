# One-shot identity on fresh task copies — owner recovery

The owner ran `ab900e9`; it is spent. On the host it passed:
- the running-r4 preconditions;
- the expired-fence and reused-installation checks;
- the Codex live re-capture with the installed module's plan check;
- the runtime-dependency and previous-identity re-checks;
- fence one-shot creation.

It then held at `Start-OpFence` (`fence_wait_ready`), in `Assert-OpOneShot` line
1023 (`One-shot definition changed.`). See
[the preserved public reports](evidence/operational-recovery-ab900e9-hold.json).

## Cause

`New-OpOneShot` pinned the raw XML of the COM object that
`RegisterTaskDefinition` returned, read after `Enabled=$true` and `Run()`. Every
later check reads a fresh `GetTask` copy, and that copy's XML differed on the
first read. `fence_wait_ready` began at 17:38:32Z and the hold came at 17:39:33Z,
which is exactly the 60 s owned-stop bound, because every owned-stop pass failed
on the same check. The fence therefore could neither be verified nor stopped.
It drained the idle board, took the writer and held it until expiry, and r4
ended on its busy timeout. r4's health now refuses connections; the Warden task
itself is unchanged.

The original `865a29b` sitting has the same code and held at the same boundary,
recorded only as a RuntimeException: its fence reached READY on its own and r4
ended. The host-proven r4 launcher never compared a one-shot's raw XML after
`Enabled`/`Run`, and compares the Warden through an invariant projection that
strips `Enabled`.

## Correction (`d5d6094`)

**One-shot identity is structural, on fresh copies only.** Raw XML is not
compared. A fresh `GetTask` copy must pass:
- the ACL policy;
- every registered field except `Enabled`, which the sitting toggles itself: no
  triggers, one exec action with the exact path, arguments and working
  directory, the SYSTEM principal (any spelling) with LogonType 5 and RunLevel
  1, RestartCount 0, MultipleInstances 2, AllowDemandStart, and the time limit;
- an exact SDDL match against the first fresh copy;
- the instance checks.

Each field group throws from its own line, so a hold names the group.

**The owned stop always ends its own fence processes.** Task.Stop needs a
verified copy. The exact nonce processes, however, are bound by their own
identity, so they are ended through one pinned handle each even when no copy
verifies. Per-pass evidence is recorded.

**Warden changes are verified on re-fetched copies.** Run identity also accepts
the scheduler's never-run value after the trigger-disable update, because the
host has never shown whether an update keeps the run history; any other run
holds. `wait_previous_exit` re-checks the exact run on every poll, and again
after the Warden is disabled. An ended instance with a live retained process is
an orphan and holds before any change, as reviewed.

**Running preconditions wait (bounded) for r4 health**: two consistent answers
within 1200 s, the daemon's Docker wait included, instead of a single read. The
last failed attempt is kept as sanitized evidence.

The recovery contract (`cochem-428-admission-recovery/2`, running-r4), every
original input and the Codex integration are unchanged.

## Verification

**583 serialized source/inert tests passed at `d5d6094`** across 14 focused
modules. The new `test_operational_oneshot_identity_428.py` models Task
Scheduler: the registration object keeps its snapshot, while `GetTask` returns
the stored task. Against the **exact delivered `ab900e9` bytes** (git blob
`d9f24c87…`), the real `New-OpOneShot` and `Start-OpFence` reproduce the owner
hold:
- the same frames, `Assert-OpOneShot` ← `Start-OpFence`;
- substage `fence_wait_ready`;
- failure on the first fetch;
- `Stop-OpOwnedFenceTask` never ends the fence.

The fixed launcher passes the same boundary, reaches READY and ends its own
fence. The model is consistent with both host holds but is not itself host
proof. The fix does not depend on what exactly differed in the XML, because raw
XML is no longer compared.

Review history:
- An independent review covered root cause, the untested rest of the path,
  stop semantics and tests, with adversarial verification and a critic. It
  confirmed the repair, and its six follow-ups (including two likely spurious
  holds the critic found) are fixed.
- A further adversarial check of that delta found only evidence gaps; they are
  fixed.
- The packaged Windows PowerShell 5.1 read-only plan returned
  `READ_ONLY_PLAN_VERIFIED` with the running-r4 scenario.

The independent package review found no blocking findings. It:
- rehashed 15 direct and 406 original inputs (130,560,536 bytes);
- confirmed the launcher is byte-identical to `d5d6094`;
- confirmed the contract equals the preparer's running spec, with identical
  PowerShell and Python contracts and 8 of 8 mutations rejected;
- confirmed the helper and Codex manifest are unchanged;
- confirmed a fresh recovery ID and an absent target sitting.

Read-only host observations at review:
- no `owner_admission_fence_428` process is alive;
- nothing listens on 47824 (r4 is down);
- the Docker Linux engine pipe, `R:\CoChem427-windows-20261007` and the pinned
  image are present;
- the three pinned Codex files match;
- AC power is on;
- Windows Update is not paused.

None of this is deployment acceptance. From fence READY onward, the path has not
yet run on this host.

## Run as owner (two steps)

r4 is down. Step 1 restarts its unchanged Warden task in Administrator Windows
PowerShell, but only if the task is idle and Ready:

```powershell
$t=Get-ScheduledTask -TaskPath '\' -TaskName 'CoChem-4.2.7-Warden'; "Before: $($t.State)"; if($t.State -eq 'Ready'){Start-ScheduledTask -TaskPath '\' -TaskName 'CoChem-4.2.7-Warden'; Start-Sleep -Seconds 5; "After: $((Get-ScheduledTask -TaskPath '\' -TaskName 'CoChem-4.2.7-Warden').State)"}
```

Claude then confirms, read-only, that r4 answers health and is idle. Step 2,
under the owner-sheet conditions, runs once:

```powershell
C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -File "C:\Users\ansac\CoChem427\r428-op-recovery-d5d6094\run_operational_428_launch.ps1" -LaunchManifest "C:\Users\ansac\CoChem427\r428-op-recovery-d5d6094\launch-manifest.json" -LaunchManifestSha256 b07c9c2be9cf12f15bb82566d2f92915cf87ad1f39e6f7c4f028cf4d374d6052 -Apply
```

Success is `R428_OPERATIONAL_RUNNING_VERIFIED`; then quit and reopen Codex and
Claude. If it holds, return the final JSON and do not repeat the command. The
owner sheet is `W\RETURN_SETUP_428_OPERATIONAL_RECOVERY_d5d6094.txt`, mirrored
under `docs/deployment/windows-deployment-next/`.

Status directory:
`C:\Program Files\CoChem\R428OperationalRecovery-20261015-a62bffb278044fffbaf21207a866ff81-e3009266c1b048088c7fa58c860c2cff`

## Package pins

| Item | SHA256 or value |
|---|---|
| Unchanged runtime source | `865a29b113a8b59c822f6aa4d921a45c18407fe5` |
| Launcher source | `d5d6094f90d24606bd68a10de11300ea3df8b2fb` |
| Scenario | `INSTALLED_R5_RUNNING_R4_20261016` |
| Recovery ID | `e3009266c1b048088c7fa58c860c2cff` |
| Launch manifest | `b07c9c2be9cf12f15bb82566d2f92915cf87ad1f39e6f7c4f028cf4d374d6052` |
| Recovery contract | `c55934380e67926b3096281b7640bc2bb68559692887b794fb12cf71c87657af` |
| Source-test evidence | `4698c22acaf2367258da9989b8b411197caa90ad55f98d5a867f7651eaab725d` |
| Original local source-test log | `b9db2a5986088e1bc56ea646ce803a62f561c4690927e9a79587a31609cef798` |
| Original local read-only plan log | `5812c7652275fd5e4ec5cea55ca9d710e28b28ede96bb0a51fba9820685a8b29` |

Preparation verified 15 direct package files and 406 original installation
inputs (130,560,536 bytes). Evidence is in
`C:\Users\ansac\CoChem427\r428-op-recovery-tests-d5d6094`, with tracked copies
under `docs/4.2.8/evidence/operational-recovery-d5d6094/`.

The three selected useful jobs remain unsubmitted (no ledger exists yet).
