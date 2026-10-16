# Running-r4 recovery with Codex integration — owner recovery

The owner ran `7a5e785`; it is spent. It held in preconditions at substage
`verify_original_recovery_evidence` (`Assert-OpRecoveryTask`, line 127)
before any task or runtime change. See
[the preserved public reports](evidence/operational-recovery-7a5e785-hold.json).

## Cause

The host rebooted on 2026-10-15 at 23:17 local time, and the owner signed in
at 06:19. The r4 Warden's logon trigger then started r4 again (PID 27208,
instance `586fc1c8…`). Every earlier recovery contract pinned a *stopped* r4
Warden: last run 2026-10-15T01:37:07Z, result 1, no instance. That state
cannot return, so the stopped contract can never match this host again.

Codex has also rewritten its own `config.toml` since preparation, at sign-in.
Its digest is now `d9363bd4…` against the pin `f97b0fe2…`. The Codex rules,
skill and metadata files still match their pins.

## Correction (`ab900e9`)

**Running-r4 scenario** (`cochem-428-admission-recovery/2`,
`INSTALLED_R5_RUNNING_R4_20261016`). Every pinned record of the original
sitting is re-verified exactly as before:
- the baseline;
- the owner result;
- the expired fence;
- the installed r5 inventory.

The live r4 is then bound instead of a stopped one:
- the Warden principal, settings and single logon trigger, against the pinned baseline task XML and SDDL;
- a running instance whose last run is later than the pinned stopped run;
- health from the exact r4 root, version 4.2.8;
- the native controller and launcher handles.

r4 is then fenced on the reviewed fresh-path order:
1. Re-check the Docker pipe and R:.
2. Re-capture r4's identity.
3. Fence.
4. Re-check catalog authority.
5. Disable the trigger.
6. Stop exactly the retained run, or accept its exit after READY.
7. Prove both native processes exited.

Catalog acceptance, cutover, verification and trigger enable are unchanged.

**Codex is integrated in this sitting.** The launcher captures
`config.toml`'s current SHA-256, with full sharing, twice: in
`codex_preflight`, before any host change, and again immediately before
`--apply`. Each capture writes a private manifest that differs from the
reviewed packaged one only in `expected.config`. The installed module
(`865a29b`) still:
- re-checks the live hash;
- replaces only the `cochem-pipeline` MCP server table;
- proves every other setting unchanged;
- backs up the file and rolls back on any concurrent edit.

If the rules, skill or metadata files differ from their pins, the sitting
holds before anything is written. The installed module's `patch_config`
accepts the owner's current `config.toml`; this was checked in memory, with
no file written. The owner result reports `codex_config_recaptured` and both
manifest digests.

**Holds settle the fence first.** In running mode, a hold after the fence
reached READY settles the fence before r4 is judged:
- The fence is released.
- If release fails, this sitting's exact nonce processes are ended through one
  pinned handle each. Settlement needs the run's terminal task record and no
  nonce process in two observations at least 1 s apart.
- ENDED, restored: the exact retained run ended after READY, including READY
  first seen on disk after the stop.
- RUNNING, left alone: after a 90 s bound, the exact old controller still
  answers health twice with admission ready.
- UNSETTLED, held: anything else.
- Unsettled fence: always a hold.

Restore waits up to 60 s for the old instance and listener to clear. A
restore fence that fails, even before READY, is settled the same way.
Sanitized stop evidence and any restore failure appear in the owner result.

**Windows PowerShell detail.** Windows PowerShell 5.1 returns `$null` when a
.NET property getter throws, even under StrictMode, for example
`Process.Handle`, `HasExited` or `StartTime` on a process it cannot open. The
new process checks therefore call `get_Handle()`, `get_HasExited()` and
`get_StartTime()`, and an unanswerable liveness question counts as "still that
process", which holds. A sweep of every other process-property read in the
launcher found each one already fails closed.

## Verification

**558 serialized source/inert tests passed at `ab900e9`** across the 13
focused modules, including the new `test_operational_running_recovery_428.py`.
The fixtures drive:
- the real running-mode evidence and actions;
- the transaction catch in every mode;
- fence termination against this inert process's real identity;
- the real ready-file and owned-fence checks;
- the real Codex re-capture against temporary files shaped like the packaged manifest.

Four review rounds ran, each with adversarial verification. The first used
four lenses plus a completeness critic; three follow-up checks covered the
fixes. They confirmed 17 distinct findings (one major: the owned stop gave up
on a process that vanished mid-check). All are fixed and tested. The packaged
Windows PowerShell 5.1 read-only plan returned `READ_ONLY_PLAN_VERIFIED` with
`recovery_scenario` `INSTALLED_R5_RUNNING_R4_20261016`. The independent package
review found no blocking findings. It:
- rehashed 15 direct and 406 original inputs (130,560,536 bytes);
- confirmed the packaged launcher is byte-identical to `ab900e9`;
- showed the recovery contract equals the preparer's running spec, with
  identical PowerShell and Python contracts;
- confirmed the Warden helper and Codex manifest are unchanged;
- confirmed a fresh recovery ID and an absent target sitting.

Read-only host observations at review:
- the Docker Linux engine pipe is present;
- `R:\CoChem427-windows-20261007` exists;
- the three pinned Codex files match;
- `config.toml` differs from its pin, so a re-capture is expected;
- AC power is on;
- Windows Update was not yet paused.

None of this is deployment acceptance. This is the first run of the
running-r4 path, the held observer's task/native proof and the Codex
re-capture on the host. Live controller identity, catalog acceptance, Codex MCP
access and job deliverables are verified only after a successful owner run.
Catalog acceptance remains the largest risk; an uncertain catalog outcome
leaves no controller until a reviewed follow-up.

## Run once as owner

Conditions, from the owner sheet:
- Docker Desktop Linux engine running; `R:\CoChem427-windows-20261007` present.
- Windows Update paused; PC on AC power.
- r4 running as it is, with its Warden task, the expired fence task and
  `C:\Program Files\CoChem` untouched.
- No job in progress. The YouTube specialist, agent sessions or workflows that
  submit pipeline jobs, and any other submitters paused; no OBS recording.
- Codex and Claude open but idle: no tasks, tests, builds, submissions,
  re-sign-in, updates, settings changes or edits to the Codex rules and skill files.
- Heavy apps closed.
- One Administrator Windows PowerShell 5.1 window.
- Do not sign out, restart or sleep until the final JSON.

```powershell
C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -File "C:\Users\ansac\CoChem427\r428-op-recovery-ab900e9\run_operational_428_launch.ps1" -LaunchManifest "C:\Users\ansac\CoChem427\r428-op-recovery-ab900e9\launch-manifest.json" -LaunchManifestSha256 a7fcb35afa4fa52007b014feea978ef3f0bae6066371cc3207aa5988d14253bf -Apply
```

Success is `R428_OPERATIONAL_RUNNING_VERIFIED`; then quit and reopen Codex and
Claude so they load the r5 pipeline connection. If held, return the final
sanitized JSON; do not repeat the spent command. Owner sheet:
`W\RETURN_SETUP_428_OPERATIONAL_RECOVERY_ab900e9.txt`, mirrored under
`docs/deployment/windows-deployment-next/`.

Status directory:
`C:\Program Files\CoChem\R428OperationalRecovery-20261015-a62bffb278044fffbaf21207a866ff81-8a78c86d7a5b4bf4b52964451110ffef`

## Package pins

| Item | SHA256 or value |
|---|---|
| Unchanged runtime source | `865a29b113a8b59c822f6aa4d921a45c18407fe5` |
| Launcher source | `ab900e9703fba0a05e7a72324540924cc68f22c4` |
| Scenario | `INSTALLED_R5_RUNNING_R4_20261016` |
| Recovery ID | `8a78c86d7a5b4bf4b52964451110ffef` |
| Launch manifest | `a7fcb35afa4fa52007b014feea978ef3f0bae6066371cc3207aa5988d14253bf` |
| Recovery contract | `38dcd8b42e9f6b19d01ab55cd1340c5797923d215e8c96d96250952abe62b6d1` |
| Source-test evidence | `405fb84434c330aecac0850ae3a26dd44b7b3191cc6c81e694e6bfa821848666` |
| Original local source-test log | `a818e1e12691d7f5240373c2cb5a98eeedb3648e3e44c723a895f4ff722d3d1e` |
| Original local read-only plan log | `5812c7652275fd5e4ec5cea55ca9d710e28b28ede96bb0a51fba9820685a8b29` |

Preparation verified 15 direct package files and 406 original installation
inputs (130,560,536 bytes). Evidence is in
`C:\Users\ansac\CoChem427\r428-op-recovery-tests-ab900e9`, with tracked copies
under `docs/4.2.8/evidence/operational-recovery-ab900e9/` (logs LF-normalized;
the table pins the original local bytes).

The three selected useful jobs remain unsubmitted (no ledger exists yet). After
a successful run they are submitted once each through
`scripts/submit_428_selected_work.py` with the permanent ledger.
