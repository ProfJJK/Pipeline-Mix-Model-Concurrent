# Process identity beyond recyclable PIDs — owner recovery

The owner ran `90c9c1d`; it is spent. It held in preconditions at substage
`verify_original_recovery_evidence`, in `Assert-OpRecoveryQuiescent`, before
any task or runtime change. The rejected process was PID 46440, `cmd.exe`,
reason `PRESERVED_PID_OCCUPIED`. See
[the preserved public reports](evidence/operational-recovery-90c9c1d-hold.json).

## Cause

The recovery contract records two historical PIDs: the r4 Warden (24424) and
the expired `865a29b` stop fence (46440). The launcher held if *any* process
currently had either PID. Windows recycles a PID as soon as its process ends.
The original fence was the base Python interpreter; the owner diagnostic had
already recorded PID 46440 absent at 18:57:01Z, and the `490bf2e` sitting passed
this same check at 00:26Z. A process's image never changes, so a `cmd.exe` at
PID 46440 cannot be that fence. Three independent skeptics failed to refute this.

A sweep of every place that compares a recorded PID with live process state
found exactly two PID-only checks, both able to cause only spurious holds:
the preserved-PID loop (run four times per sitting, including once after the
Warden trigger is disabled) and `Release-OpFence` without a retained handle.

## Correction (`7a5e785`)

- **Preserved-PID identity.** An occupant whose immutable image is neither
  Python-family nor a runtime/pipeline executable is a different process. A
  possible original is a different process only if it was created more than
  120 s after a pinned time by which the original already existed: `ready_at`
  from the pinned fence `ready.json`, `process_started_at` from the pinned r4
  baseline. Missing name, creation time or bound still holds.
- **`Release-OpFence` without a handle** uses the same rule, and also holds on
  an occupant carrying this fence's nonce or an unreadable Python command line.
- **Held-observer detector.** Each ~12 s observer cycle runs a sterile detector
  (observer child → staging venv launcher → base interpreter, 5 s timeout).
  These and rows whose image or command line was unreadable (processes exiting
  between the snapshot and its detail read, e.g. agent hook or MCP churn) are
  never accepted: their exact PID and creation time are waited out (8 s) and a
  complete new inventory, including a fresh observer proof, is required; at
  most six inventories, then the original rejection. Ancestry must be present in
  the same snapshot with each process created no earlier than its parent.
  Readable rejected rows still hold at once.
- **Before any fence or task change:** the pinned bootstrap's RAM-disk workspace
  (`R:\CoChem427-windows-20261007`) and Docker engine pipe must exist (read-only).
- **Before disabling the Warden trigger:** at least 190 s of fence validity must
  remain, so the post-disable re-check cannot outlast `Assert-OpFence`.
- The controller port is re-checked on every retry; `verify_running` and the
  restore path wait 1200 s for health (both Wardens use `--docker-wait-seconds 900`).

The recovery contract (`Get-OpRecoveryExpected` / `make_recovery_spec`), the
helper pin and every other package input are unchanged.

## Verification

Regression fixtures drive the real checks with host-shaped `Win32_Process`
rows (UInt32 identities, creation times), real pinned-record JSON parsing,
the real observer proof and the real extracted recovery actions. Against the
exact delivered `90c9c1d` launcher bytes (`5b8c4982…`) they reproduce both the
owner hold (`cmd.exe`, `PRESERVED_PID_OCCUPIED`) and the forecast detector hold
(`PROTECTED_PYTHON`). At `7a5e785`, **416 serialized source/inert tests passed**
across the eleven focused modules plus `test_operational_preserved_pid_428.py`.
Two independent multi-lens reviews with adversarial verification and a
three-claim skeptic round found no blocker. The packaged Windows PowerShell 5.1
read-only plan returned `READ_ONLY_PLAN_VERIFIED`. Independent package review rehashed 15 direct and 406 original inputs (130,560,536 bytes): no blocking findings.

None of this is protected task/native acceptance or deployment. The observer's
task/native proof has never completed on the host; this sitting is its first
live run, and any hold there is before any task or runtime change.

## Run once as owner

Conditions, from the owner sheet: Docker Desktop engine running and R:
present; Windows Update paused; PC on AC power; Codex/Claude open but idle (no
tasks, tests, builds, Codex restarts/updates or settings changes); heavy apps
closed. Do not sign out, restart or sleep until the final JSON.

```powershell
C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -File "C:\Users\ansac\CoChem427\r428-op-recovery-7a5e785\run_operational_428_launch.ps1" -LaunchManifest "C:\Users\ansac\CoChem427\r428-op-recovery-7a5e785\launch-manifest.json" -LaunchManifestSha256 58ee18e120fbe1c0cfbe2afade324f19e20a2dd89dab0143c100b2091515f6fd -Apply
```

Success is `R428_OPERATIONAL_RUNNING_VERIFIED`. If held, return the final
sanitized JSON; do not repeat the spent command. Owner sheet:
`W\RETURN_SETUP_428_OPERATIONAL_RECOVERY_7a5e785.txt`, mirrored under
`docs/deployment/windows-deployment-next/`.

Status directory:
`C:\Program Files\CoChem\R428OperationalRecovery-20261015-a62bffb278044fffbaf21207a866ff81-f47844af074547798477c85a9a9a0eb0`

## Package pins

| Item | SHA256 or value |
|---|---|
| Unchanged runtime source | `865a29b113a8b59c822f6aa4d921a45c18407fe5` |
| Launcher source | `7a5e785447e5fa49a4cd7edc1c912ede529f961c` |
| Recovery ID | `f47844af074547798477c85a9a9a0eb0` |
| Launch manifest | `58ee18e120fbe1c0cfbe2afade324f19e20a2dd89dab0143c100b2091515f6fd` |
| Recovery contract | `a5c1363e62c8987af2fb70ca7592dcdf36089d3ff4a72d881d82d78f5e555263` |
| Source-test evidence | `d16cb09b2a545f48d2e7fda6597e67272b540f06c56fe7cdd8548a9bd9267a5b` |
| Original local source-test log | `453299c9fc7754bca933ea8b7df912d2b2eee199197d5319699bce1a644392f9` |
| Original local read-only plan log | `e83a71063ca5ea3203a2662b2f01107e3efcef0365e364a86a1f927bf73f1ede` |

Preparation verified 15 direct package files and 406 original installation
inputs (130,560,536 bytes). Evidence is in
`C:\Users\ansac\CoChem427\r428-op-recovery-tests-7a5e785`, with tracked copies
under `docs/4.2.8/evidence/operational-recovery-7a5e785/` (logs LF-normalized;
the table pins the original local bytes).

The three selected useful jobs remain unsubmitted (no ledger exists yet). Live
controller identity, catalog acceptance, Codex MCP access and actual job
deliverables are verified only after a successful owner run.
