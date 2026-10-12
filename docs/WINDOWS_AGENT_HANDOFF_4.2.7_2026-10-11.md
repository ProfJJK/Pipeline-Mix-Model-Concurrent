# Windows deployment agent handoff — 11 October 2026 (r5)

This continues the owner's 4.2.7 pipeline deployment on **AETHERDESK** (Windows, account `ansac`).
It supersedes the deployment-state sections of
[the 9 October handoff](WINDOWS_AGENT_HANDOFF_4.2.7_2026-10-09.md). Canonical policy is unchanged:
[4.2.7_SRS.md](../4.2.7_SRS.md), [owner addendum](SRS_ADDENDUM_4.2.7.md).
Written by the Claude Code session that built r5, for the next agent (the owner plans to continue with
ChatGPT/Codex).

**Read [AGENTS.md](../AGENTS.md) first.** Its host rules are enforced on this workstation by a PreToolUse
hook for Claude Code. Codex and Antigravity must follow them by reading the file.

> **Interim update, 2026-10-11 about 21:30 CDT.**
> - The owner's second sitting (v2, 20:27) got to S10. It then stopped and **restored r4**, so the Warden
>   is **running r4** now.
> - A third repair is in progress in this Claude Code session (section 5b).
> - The owner asked the next agent to start in parallel on the model-matrix redesign and on r6/r7.
>   **Section 11 says what you can start now and which files to leave alone.**
> - The `docs/deployment/` mirror still holds the pre-repair versions of the files under repair.
>   This session pushes the final repair later on this branch.

## 1. Where things stand (one paragraph)

r5 (Gemini identity policy, reboot-safe Warden start, 200 MiB Warden budget and a set of runtime fixes)
was built, tested and audited three times, reaching a final GO.

- **Sitting 1** (2026-10-11 17:22) stopped at S2 and changed nothing. It exposed six binding and
  process-classification bugs, which were repaired (section 5).
- **Sitting 2** (20:27) got further. S0-S2 and S9 worked. Then S3, S5 and S10 all held on one defect: a
  scheduled-task registration flag (section 5b). The sitting **restored r4 automatically**.
- **Now:** the Warden **runs r4 again**, but r4 admits no work, because the controller is over r4's
  strict 50 MiB memory budget (r5 raises it to 200 MiB). The r5 runtime is installed but not activated.
- **Next:** the flags-18 repair is being finished and reviewed. After that, the owner runs
  `-Apply -Attempt v3` (section 6).
- The owner has left the **model-tier routing redesign** and **r6/r7** to the next agent (sections 8
  and 11).

## 2. Repository and branches

- GitHub: <https://github.com/ProfJJK/Pipeline-Mix-Model-Concurrent> (**public**; default branch `master`).
  Never publish credentials, account data, private databases or the owner's e-mail address.
- Local checkout on the host: `C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent`.
- Branch **`feature/r5-gemini-and-runtime-fixes`** (pushed 2026-10-11). On top of `d5650d8` it carries:
  - `0821333`: WIP r5 coding link-count and Claude failure-classifier edits (army checkpoint).
  - `54ed222`: r5 (Gemini identity policy, chapter WBS reconciliation, memory and reboot fixes).
  - `8554c76`: r5 audit fixes (agy failure lines, stricter identity scan, admission and lock tuning).
    **This is the frozen r5 source.** At this commit the full suite gave 3394 passed and 389 skipped.
  - Later commits add only documentation: this handoff and the deployment workspace mirror (section 3).
- The local branch `agent-army/checkpoint-20261011-112925` (= `0821333`) is the army's rollback point.
  It is not pushed, because the feature branch already contains it.
- The local checkout has many untracked root files (`check_*.py`, `query_*.py` and similar) from earlier
  sessions. They are not part of the pipeline. **Never commit them**; always commit explicit paths.

## 3. Deployment workspace (owner-facing scripts)

The deployment layer (installers, freezes, cutover scripts, the sitting runner, owner sheets and their
test harnesses) is **not** in the source tree. It lives on the host at

`C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next` (called **W** below).

W is not a git repository. A curated, secret-scanned, byte-exact mirror is published in this repo at
[docs/deployment/windows-deployment-next/](deployment/windows-deployment-next/). It holds every top-level
script, harness, spec and sheet, plus `r5-army-specs/` and `gemini-build-specs/`, and
`EXPORT-MANIFEST.json` lists the sha256 of every file. Fixtures, evidence trees, temp folders,
checkpoints, XML test outputs and the large publication inventories were left out. `.gitattributes` marks
the mirror `-text` so the pinned sha256 values survive any checkout.

**Run owner scripts from W on the host, never from a clone.** The runner pins its children by sha256;
the mirror exists so you can read and diff it. If W and the mirror disagree, W is the truth on the host.
Compare it against `EXPORT-MANIFEST.json`.

Key W documents:

| File | What it is |
| --- | --- |
| `RUN_427_R5_SITTING.ps1` | The single elevated sitting runner (plan by default, `-Apply` to change) |
| `RETURN_SETUP_R5_20261011.txt` | Owner sheet for the sitting |
| `refresh-r5-sitting-pins.py` | Regenerates or checks (`--check`) the runner's pin table |
| `ps_toplevel_smoke.py` | Real top-level plan-mode smoke helper for PS 5.1 scripts (section 9) |
| `serialize-heavy.py` | Host-wide lock: one heavy test run at a time |
| `r5-army-specs/ARMY_ADDENDUM_20261011.md` | Decisions A1-A7 (section 7) |
| `r5-army-specs/INTERFACES-*.md`, `KEYSTONE-API.md`, `BOOT-API.md` | Interface contracts of every r5 script |
| `r5-army-specs/.army-state.md` | Build log of the r5 agent army |
| `R5_CHANGE_SPEC_20261011.json` | The r5 change spec |
| `stopped-runtime-r5-source-manifest.json` / `-freeze-receipt.json` | r5 freeze (manifest sha256 `5d8d337b…`) |
| `r5-sitting-20261011-172252.log` | Transcript of the failed first sitting |
| `R6_DESIGN_20261011.md`, `r5-army-specs/R6_SCOPE_V2_20261011.md`, `R6A_SCOPE_20261011.md` | r6 proposals: **input only**, see section 8 |

## 4. Host state (verified 2026-10-11, about 21:00 CDT, after sitting v2)

- **Warden RUNNING r4, admission paused.** Sitting v2's automatic restore retargeted and restarted the
  task: `C:\Program Files\CoChem\WardenRetarget4.2.7-windows-20261011-r4-v1`, status
  `WARDEN_R4_RESTARTED_HEALTH_VERIFIED`, controller pid 37840 running as SYSTEM, port 47824 listening, task
  enabled.
  - `pipeline_health` shows Docker, containers and knowledge healthy.
  - Admission is `pause_admission`, capacity 0, because the controller uses about 54.8 MiB, over r4's
    strict 50 MiB budget. This is the known r4 defect that r5 fixes.
  - Read-only diagnosis also saw the controller at 5.56 % CPU (budget 5 %) and disk IOPS of 4433 (limit
    4000). See the S12 risk in section 11.
  - r4 has no logon trigger, so it is **not reboot-safe**: after a reboot the Warden stays down until
    the next retarget.
- **History:** from the 2026-10-11 00:57 crash until sitting v2, the Warden was down on its consumed r4-v1
  action.
- **Left over by sitting v2:**
  - 14 registered, **never-run** SYSTEM tasks: 12 `CoChem-4.2.7-NativeAuthStatusSix-20261010-r4-v1-ea8225f6…`,
    1 `AgyCapture…-57fbb476…` and 1 `UpgradePreview…-116bb5fd…`. Their held roots
    (`status-held.json`, `capture-held.json`, `preview-held.json`) are under `C:\Program Files\CoChem`.
    They are inert. Removing them is optional and needs the owner, elevated.
  - The staged held config `WardenConfig4.2.7-windows-20261011-r5-v1\pipeline.json`, sha `135cd9ec`,
    which equals the commissioned bytes. The next sitting stages into `-r5-v2`.
  - `R5Sitting4.2.7-windows-20261011-v2` has ended. The next attempt is **v3**.
- **r4 runtime** (the last active one, launched 2026-10-10 20:01 by `RUN_427_LAUNCH_SERIES.ps1`):
  `C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4`; its switch receipts are under
  `C:\Program Files\CoChem\WardenRetarget4.2.7-windows-20261010-r4-v1`. The GUI MCP entries point at
  the r4 interpreter.
- **r5 runtime installed, never activated:** `C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5`.
  It was installed by sitting step S1 (`FRESH_STOPPED_RUNTIME_READY`). No task action, receipt or process
  references it.
- **r5 freeze:** `C:\Users\ansac\CoChem427\stopped-runtime-r5-source` (166 files: 13 changed,
  153 verified unchanged against r4).
- **Sitting roots:** `C:\Program Files\CoChem\R5Sitting4.2.7-windows-20261011-v1` (ended at S2) and
  `-v2` (ended at S10 after restoring r4). Both have `sitting-end.json`. **The next run is `-Attempt v3`.**
  For history, the v2 rerun worked as follows. Rerunning v1 stops at S0 with "Sitting attempt v1 has already ended". In v2, S0 skips the PyPI probe and S1 skips the install, because the existing r5 install verifies read-only (`install-after.json`, sha `91c75609…`, no `install-held.json`). S2 can use the stop namespace v1, which is still free because the v1 stop held before it created its folder.
- **Owner GUI clients:** the owner normally runs about 14 MCP client processes as `AETHERDESK\ansac`
  (Claude Desktop, Codex, Antigravity, Claude Code), from the r4 venv or the Toolchain Python. They are
  clients of the Warden, not controllers. They may stay open during the sitting once the repair is in place.
- The 8 GiB ImDisk `R:` volume, the `Mount_CoChem_RAMDisk` task, WSL2 and Docker Desktop are untouched
  and must stay that way (AGENTS.md). The legacy 4.1.2/4.2.0 pipelines and the Hyper-V VM
  `CoChem-Golden-Baker` were retired by the owner's reviewed runs on 2026-10-10. No VMs remain;
  AGENTS.md still names the VM for history.
- The Warden needs the owner logged in with Docker Desktop running, because its Docker preflight uses
  the engine of the owner's interactive session.

## 5. The first sitting (2026-10-11 17:22) and the repair

Transcript: `W\r5-sitting-20261011-172252.log`.

| Stage | Result |
| --- | --- |
| S0 preconditions | OK |
| S1 install r5 beside r4 | OK (about 4 min) |
| S2 stop-warden-r4 | **HELD, nothing changed**: "a controller process, an unclassified runtime process or the loopback port is alive" |
| R4-RESTORE (automatic) | **failed to bind**: `ValidationMetadataException` / `ValidateSetFailure` in `retarget-warden-r5.ps1` |
| Outcome | stopped; Warden still down, as it was before the sitting |

Root causes:

1. **Process classification.** The stop/retarget presence sweeps recognised
   `cochem_pipeline mcp …` clients but not the Antigravity bridge client
   `python -m cochem_mcp --provider X --config bridge.local.json`. Four of them were running, so they were
   counted as "unclassified runtime processes" and S2 held. The same logic was in `stop-warden-r4.ps1`,
   `stop-warden-r5.ps1` and `retarget-warden-r5.ps1`.
2. **PowerShell validated-parameter variables.** `retarget-warden-r5.ps1` declared
   `[ValidatePattern('^v[0-9]{1,3}$')][string]$SourceAttempt=''` and later assigned
   `$script:SourceAttempt=$request.source_attempt`. In PowerShell the parameter variable keeps its
   `Validate*` attributes, so assigning an empty or invalid value throws. The r4-restore call has no
   source attempt, so it always died. The harnesses had never caught this because they dot-sourced
   functions out of the AST and never ran the script top level.

The repair (workflow `r5-sitting-repair`, 2026-10-11 evening):

Diagnosis (two read-only agents) confirmed both root causes and found four more hazards of the same kinds.
The PowerShell 5.1 probes used each script's real param block and its real imported helpers.

| # | Script (new sha256 prefix) | Hazard | Would have failed at | Fix |
| --- | --- | --- | --- | --- |
| 1 | `retarget-warden-r5.ps1` (`991703ab`, was `97403e81`) | `$script:SourceAttempt/StopAttempt=''` on `[ValidatePattern]` parameters | S11 from base r4-v1, the r4 restore (seen 17:22) | Removed `Validate*` from the four parameters; `Assert-RetargetParameters` already validates them case-sensitively |
| 2 | `login-six-workers-status-first-r4-v1.ps1` (`9cfc0a98`, was `f4fedd50`) | `$script:LoginMode=''` on `[ValidateSet('print','tui')]` | every S3 Claude/Codex re-login | `-LoginMode` is a plain `[string]`; `Get-LoginModeRefusal` enforces the set |
| 3 | `agy-isolation-evidence-r4-v1.ps1` (`af773b1f`, was `b837f0f4`) | `$script:Slot=''` / `effortNullSlug=''` on `[ValidateSet]` | S8 `-StageOnly`, always, so Gemini would always be held | Plain `[string]`; the main function enforces slot1 and the three slugs |
| 4 | `stop-warden-r5.ps1` (`b5920f37`, was `6e519927`) | `Read-StartReceipt` local `$held` shadows the caller's list; the imported `Read-R3Control` calls `$held.Add()` through dynamic scope | **every** stop-warden-r5 run: the Gemini fallback stop, every r5 rollback, S2 after any r4 restore | Local renamed `$startHeld` |
| 5, 6 | `retarget-warden-r5.ps1` | same `$held` trap in `Assert-HeldStartSourceLineage` and `Assert-RetargetHeldSourceLineage` | r4 restore from held-after-Run and from an unreadable MUTATION_READBACK hold | Renamed `$heldRecord` (plus two hygiene renames) |
| P | `stop-warden-r4.ps1` (`43fc386b`, was `bd54cb81`), `stop-warden-r5.ps1`, `retarget-warden-r5.ps1` | Antigravity bridge `python.exe -m cochem_mcp --provider (codex\|claude) --config C:\Users\ansac\CoChem427\bridge.local.json` was "unclassified" | S2 (seen 17:22), S11, every restore | One identical client line in all three; it matches that exact command line only (near misses still hold) |

Cascade: `run-upgrade-preview-r5-v1.ps1` was re-pinned to the new retarget (`8f4c8064`, was `0be2a4ac`). The stager's
byte-identical copies did not change.

New safeguards:

- **`W\ps_toplevel_smoke.py`** + `test_ps_toplevel_smoke.py` (71 tests). It runs a real script top level in plan mode
  under Windows PowerShell 5.1 against stubs, as `-File` and as `-Command`.
- **Child-binding smoke** in `test_r5_sitting_flow.py`. Every call shape the runner can build (41 shapes, including
  every restore, fallback and recovery path) is bound against the real child script with `-Apply` dropped. A test
  copy of the 17:22 mistake must fail it.
- **S0 process precheck** in the runner. Before S11 it classifies live processes exactly as the three cutover
  scripts do, and stops at S0 with nothing changed if anything rooted in a pipeline runtime is unrecognised. It
  lists pid, parent and command line, and writes no receipt and no `sitting-end.json`. On the live host (read-only)
  all 16 MCP clients are recognised.
- Static checks that no script writes a validated parameter variable and no function shadows a variable that an
  imported reviewed helper reads.

Harness results on the final files, each run alone through `serialize-heavy.py`:

- retarget 530, stop-r5 570, stop-r4 167, smoke 71.
- preview 101, stager 61, installer/freeze 187, builder 89.
- driver 103, isolation 121, status leaf 66, capture 88, agy wrapper 82.
- Runner: static 68, flow 238. Pin check: 33 OK.
- An independent rerun of static + flow + smoke by the Commander: 377 passed in 417 s (2026-10-11 ~20:00).

Known limits:

- S2 can still hold on checks the S0 precheck does not cover (worker ownership, the port bind test).
- The bridge pattern is exact. If the owner adds `-I -B` to the Antigravity MCP entries or moves
  `bridge.local.json`, every stop holds on the bridges again; widen the pattern in all three scripts and in
  the runner's S0 mirror.
- The r3_v6 Claude login child loads its copy helper from `D:\Gdrive\...\scripts`, so that Google Drive path
  must exist on the day (it does now).
- The installer (S1) cannot run top level against stubs. It ran for real at 17:22 and is skipped in v2.

## 5b. The second sitting (2026-10-11 20:27) and the repair in progress

Transcript: `W\r5-sitting-20261011-202738.log` (in the mirror). Full diagnosis:
`W\r5-army-specs\R5_SITTING_V2_DIAGNOSIS_20261011.md` (in the mirror).

| Stage | Result |
| --- | --- |
| S0 | OK: 33 pins, Docker, 16 MCP clients recognised, nothing unclassified |
| S1 | skipped; the r5 install verified |
| S2 stop-warden-r4 | OK (`WARDEN_ALREADY_STOPPED_AND_DISABLED`) |
| S3 status checks (12) | **all HELD at task registration**: "Registered task ownership/private DACL differs" |
| S5 agy capture | **HELD**, same message. Gemini held; S6-S8 skipped |
| S9 build + stage | OK: held config staged as `WardenConfig…-r5-v1` (commissioned bytes) |
| S10 upgrade preview | **HELD**, same message, so the series stopped |
| R4-RESTORE | OK: `WARDEN_R4_RESTARTED_HEALTH_VERIFIED`, r4 running |

**Root cause:** five scripts written on 2026-10-10/11 call
`RegisterTaskDefinition(name, def, 2, 'SYSTEM', $null, 5, 'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)')`
(flags 2 = `TASK_CREATE`). They then apply the exact check `Assert-RegisteredTaskAcl` from
`register-stopped-warden-r3.ps1` (pin `eccc593f`), which requires a protected DACL with exactly SY FA and
BA FA. The five scripts are:

- `check-worker-native-auth-status-six-r4-v1.ps1` (S3, also used by S6)
- `agy-status-capture-r4-v1.ps1` (S5, S7)
- `login_pipeline_worker_interactive_agy_r4_v1.ps1` (S6)
- `agy-isolation-evidence-r4-v1.ps1` (S8)
- `run-upgrade-preview-r5-v1.ps1` (S10)

On this host, Task Scheduler reads a flags-2 registration back **unprotected and with an extra
`(A;;FR;;;<principal>)` ACE**, so the check always fails. This was already diagnosed on 2026-10-08 (see
`pending-warden-recovery-v7-preparation-20261008.json`, field `defect`). The r3 status leaves also used
flags 2 but never read the descriptor back. The new scripts added the strict read-back without the
partner fix.

**Fix (proven on this host):** flags **18** = `TASK_CREATE | TASK_DONT_ADD_PRINCIPAL_ACE` (`taskschd.h`:
0x2 | 0x10), keeping the exact check.

- On 2026-10-09 the owner's elevated `resume-pending-warden-r3-v7.ps1:125` registered a SYSTEM task with
  flags 18. It passed the same `eccc593f` check and ran to `WARDEN_RUNNING_CONTROL_PLANE_VERIFIED`
  (`C:\Program Files\CoChem\TaskAclRecovery4.2.7-windows-20261008-r3-v1\recovery-complete.json`).
- Windows build 26300 (UBR 9457) and PowerShell 5.1.26100.9444 have not changed since.
- Caveat: that is a single elevated sample.

**Repair status at this interim push.**

- **FIX-REGISTRATION done.** All five scripts set `$script:taskRegistrationFlags=18` and pass it. The pins
  of the status leaf and the agy wrapper in `login-six-workers-status-first-r4-v1.ps1` were updated.
- **Realistic test model.** A new shared model, `W\task_scheduler_host_projection.py`, makes every
  Task Scheduler stub return the host's real read-back. Flags 2 now fails the tests exactly as it failed
  on the host.
- **New static test.** `W\test_task_registration_flags_r5.py` requires flags 18 wherever the exact check
  follows a registration.
- 573 harness tests pass.
- New shas:

  | File | sha256 prefix |
  | --- | --- |
  | status leaf | `34612ac4` |
  | agy wrapper | `381fb8da` |
  | capture | `03198a30` |
  | isolation | `bd87ad31` |
  | preview | `98a8130a` |
  | login-six | `953f49d3` |

- **Still running:** FIX-NEXT (refresh the runner's pin table and make the v3 run safe from today's state),
  then two adversarial reviews. The final push of this session records the outcome and the owner's v3
  command.

Things the v3 walk-through found:

- S2 will, for the first time, **End a running controller**: an idle proof, then Task Scheduler End, then
  disable. Nobody may submit pipeline work just before or during the sitting.
- S9 stages into `WardenConfig…-r5-v2`.
- Restores use the r4 namespace v2.
- No v2 leftover blocks v3, because new runs get fresh ids.

## 6. Running the sitting (owner)

> Interim note: the command below is the **v2** command and is history. The final push replaces it with the
> verified **v3** command. Do not hand the v2 line to the owner again.

The owner opens an **elevated 64-bit Windows PowerShell 5.1** and runs:

```powershell
cd "$HOME\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\RUN_427_R5_SITTING.ps1 -Apply -Attempt v2
```

- Without `-Apply` the runner only prints the plan. `-Gemini skip` drops the six Google sign-ins.
  Gemini is attempted by default, and any Gemini gate failure degrades to held without failing the sitting.
- About 12-17 minutes attended (six Google sign-ins), 70-80 minutes in total.
- Failures after the Warden switch restore r4 automatically, except for rare reviewed-blocked states, which
  the outcome block names together with their recovery command (`retarget-warden-r5.ps1
  -RecoverInterruptedStart`, `START_HELD_BEFORE_HEALTH_GATE` and the r4-restore variants; see
  `INTERFACES-CUTOVER.md`).
- After the sitting, read the receipts under the new sitting root and the OUTCOME block. A green outcome
  means the Warden runs r5 from the logon trigger. That trigger is enabled only after the health gate,
  starts 1 minute after logon and uses `--docker-wait-seconds 900`. Then run the MCP `pipeline_health`
  and provider preflight.
- **Owner preference:** prepare and independently review everything first, then hand the owner **one**
  consolidated elevated series. Never ask again for approvals already granted. Do not schedule
  owner chores beyond that one series.

## 7. Decisions in force

From `r5-army-specs/ARMY_ADDENDUM_20261011.md`:

- **A1** The Warden is down. S2 (stop r4) is conditional, and retarget accepts the r4-v1 action with
  0 instances.
- **A2** Reboot-safe start. The new daemon options are `--queue-launch-output-root DIR` (a fresh child
  directory per start) and `--docker-wait-seconds N`. The r5 action adds a logon trigger for
  `AETHERDESK\ansac` with a 1-minute delay (Docker Desktop lives in the owner's session), uses
  MultipleInstancesPolicy IgnoreNew and has no execution time limit. An r4 restore keeps the r4 flags and
  has no trigger.
- **A3** Warden self-budget **200 MiB** (CPU 5 % unchanged), a named constant in `controller_guard.py`.
  The owner accepted it ("a pretty good middle number"). The repo-root `4.2.7_SRS.md` carries the
  amendment. The packaged `knowledge/wiki` SRS still says 50 MiB (a known text mismatch). Recovery
  hysteresis applies to memory only.
- **A4** Gemini is attempted; `-Gemini skip` is a switch.
- **A5** NF-1 (copy native-attempt evidence) is dropped.
- **A6** The freeze set is the 12 spec files plus `__main__.py`. Each file keeps r4's line endings
  (`agy_protocol.py` is LF, everything else CRLF).
- **A7** Host safety (AGENTS.md): every heavy run goes through `serialize-heavy.py` and runs
  single-process.

Audit outcomes and owner acceptance:

- Three audit rounds. Every finding was fixed or explicitly deferred.
- **RG-1, owner acceptance item:** Gemini isolation is proven at S8 only. Hooks added later (in `R:\` or
  `C:\ProgramData`) would go unnoticed until the next evidence run.
- Gemini identity policy `reported-model-equality` uses `model_bindings` and `effort_contracts`.
  `gemini-3.1-pro-preview` is **not** bound in r5.
- Standing owner rules (from the 9 October handoff, still valid):
  - Four execution slots at most.
  - Native subscription CLIs only: no paid API and no hidden fallbacks.
  - Preserve credentials, sign-ins, databases, knowledge generations and evidence.
  - Preserve the ImDisk `R:` volume and its task.

## 8. Left for the next agent: routing redesign and model upgrades

The owner said: "Leave the model tier complexity for a redesign by the next agent that picks this up.
Just wrap up the current revisions so I can pick it up with the new agent." Nothing below is built.
The owner's wishes, verbatim:

- "Add Gemini 3.1 Pro to r6 and a method to easily upgrade the model availability for Gemini models for
  when the new 4.0 comes out in a month or so. Build this so upgrades are faster and easier to accomplish
  for the rapidly developing models."
- "Gemini Pro should not be applicable to the higher tier difficulties. Gemini 3.1 Pro should be assigned
  the same tier of difficulty and complexity as Sonnet 5.5."
- "The anti-gravity CLI, or at least the anti-gravity IDE, has Opus 5.5 available at high effort. We can
  call Opus 5.5 through the anti-gravity when the quota is exhausted through Claude."
- "I don't really want to launch and run the pipeline without Gemini Pro access since most of my quota is
  consumed for Claude and ChatGPT for the week." (So the owner may prefer to hold the sitting until Pro is
  routable. Ask.)

Facts the redesign must respect:

- The routing tier table is **fixed in code**. `src/cochem_pipeline/routing.py` `_defaults`/`_normalize`
  require the config tiers to equal the canonical v2 table, and the tier sizes are fixed at 3/3/3/2. Any
  tier change (Pro in Sonnet's tier 4-6, an agy-served Opus fallback, Gemini 4.0) is therefore a **source
  change** with a new routing policy version. Captured jobs must keep decoding their v1/v2 snapshots.
- Changing the source means a new freeze and installer. Because the installed r5 root was never activated,
  a later revision can archive and replace it under the same root name.
- Gemini routes are bound per model slug and effort through `providers.gemini.model_bindings` and
  `effort_contracts`, and each binding needs a live isolation evidence run (S8) before the config
  builder will enable it.

Input material (proposals written before the owner deferred the redesign; not decisions):

- `W\R6_DESIGN_20261011.md`: full r6 design (catalog-driven tiers, model-upgrade kit, canary route,
  batch submission tool, decisions D1-D13).
- `W\r5-army-specs\R6A_SCOPE_20261011.md`: a deployment-only r6a split (superseded).
- `W\r5-army-specs\R6_SCOPE_V2_20261011.md`: a routing policy v3 sketch with Pro in tier 4-6 and agy Opus
  as the last fallback in 7-9 and 10.
- `W\r5-army-specs\R6_V3_RESEARCH_20261011.md`: read-only research (2026-10-11 evening) with two findings.
  - Whether and how agy serves Opus 5.5. The catalog lists `claude-opus-5-5-high` ("Claude Opus 5.5
    (High)"); no Opus run has happened on this host.
  - The exact source footprint of a policy v3. The minimum is `routing.py` + supervisor `probes.py`,
    `runner.py` is recommended, and the research lists pre-computed routing digests.

Key risk found by that research, for the agy-Opus wish: agy serves Claude models from Google's
**"Claude and GPT models"** weekly bucket. That bucket is separate from the Gemini bucket and shared
by the owner's IDE, the owner's CLI and all six worker slots. About 80 Sonnet 5.5 runs on 2026-10-03
emptied it for a week, and the next call returned `RESOURCE_EXHAUSTED` / "AI credits balance is too
low". Also, the pipeline's quota pool `gemini` would hold every Gemini route when that bucket runs dry.
Treat agy Opus as a small, capped fallback, and design the quota pool split before relying on it.

Other deferred items:

- RG-4 (`.gemini`-level rename) and RG-5 (G5 replay checks recomputed from the raw replay).
- Packaged SRS text (50 MiB); `/operator` body size (about 0.5 MB).
- Supervisor runner AGY_ERROR category; status helper `observe_child` exit fallback.
- Claude Extended effort contract (stays held).

## 9. Lessons for whoever continues

- **Crash cause, per the owner:** the host crashes (September BSODs, 2026-10-09 QUOTA_UNDERFLOW,
  2026-10-11 00:57) were **not hardware**. They were runaway Python scripts spawning agents in loops,
  hundreds per second, and the owner reports these were always written by Gemini 3.1 Pro. Never write
  unbounded subprocess or agent-spawn loops. Keep every fan-out bounded (at most 4 heavy processes) and
  never spawn headless agent CLIs. AGENTS.md and the guard hook encode this.
- **Test PowerShell entry points top level.** A harness that dot-sources functions from the AST will not
  see script-scope parameter binding or `Validate*` attribute behaviour. `W\ps_toplevel_smoke.py` runs a
  script top level in plan mode under Windows PowerShell 5.1 with stubs. Every orchestrator-to-child call
  must be bound against the real child script this way before an owner sitting.
- **PowerShell resolves free variables by dynamic scope.** A reviewed helper that writes to `$held` (meant to
  be the caller's list) writes to the nearest `$held` up the call stack. A function that declares its own local
  `$held` therefore breaks the helper. Stubs that do not reproduce such side effects hide this. Stubs must mimic
  the real helper's free-variable use, and a static test should flag shadowing.
- **Task Scheduler on this host rewrites descriptors.** A `TASK_CREATE` (2) registration reads back
  unprotected and with an extra read ACE for the principal. Use flags 18 whenever the exact descriptor
  check follows, and test against `task_scheduler_host_projection.py`, never against a stub that echoes the
  requested SDDL. More generally: when a fix is found on the host, put it in the shared helper or in a
  static test. A fix left in one script and one evidence file is lost to the next script that copies the
  pattern.
- **Classify live processes against the real host.** Fixture process lists missed the Antigravity bridge
  client. The sitting S0 now lists any unrecognised rooted process before anything changes.
- **Pins:** after changing any pinned W file, run the cascade (re-pin dependents), then
  `refresh-r5-sitting-pins.py` once, then `--check`.
- **Sub-agents:** in Claude Code, nested sub-agent completion notices go to the top-level session, not to
  the agent that spawned them. Keep about 10 working agents at most.

## 10. Evidence and paths

| Thing | Path |
| --- | --- |
| Pipeline interpreter | `C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\.venv\Scripts\python.exe` (3.12) |
| Runtime client config (all GUIs) | `C:\Users\ansac\CoChem427\pipeline-client-r3.json` |
| r5 runtime (inactive) | `C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5` |
| r5 freeze | `C:\Users\ansac\CoChem427\stopped-runtime-r5-source` |
| Sitting v1 root (ended) | `C:\Program Files\CoChem\R5Sitting4.2.7-windows-20261011-v1` |
| Deployment workspace W | see section 3; mirror in [docs/deployment/windows-deployment-next/](deployment/windows-deployment-next/) |
| Guard hook | `.claude/hooks/cochem_host_guard.py`; tests `pipeline_tests/test_cochem_host_guard.py` |

Final pinned script hashes (sha256 prefixes):

| File | sha256 prefix |
| --- | --- |
| `RUN_427_R5_SITTING.ps1` (runner; its table pins 33 files) | `f875a8f1` |
| `RETURN_SETUP_R5_20261011.txt` (owner sheet) | `80e5e55a` |
| `retarget-warden-r5.ps1` | `991703ab` |
| `stop-warden-r4.ps1` | `43fc386b` |
| `stop-warden-r5.ps1` | `b5920f37` |
| `run-upgrade-preview-r5-v1.ps1` | `8f4c8064` |
| `login-six-workers-status-first-r4-v1.ps1` | `9cfc0a98` |
| `agy-isolation-evidence-r4-v1.ps1` / `agy_isolation_evidence_r4_v1.py` | `af773b1f` / `767f03af` |
| `build-pipeline-config-r5-candidate.py` | `ab01d824` |
| `stage-pipeline-config-r5-v1.ps1` | `1066f6c3` |
| `install-stopped-runtime-r5.ps1` | `1f8041bc` |
| `cochem-inference-only.agent.md` | `5c0082d7` |
| `stopped-runtime-r5-source-manifest.json` (freeze manifest) | `5d8d337b` |

`refresh-r5-sitting-pins.py --check` must print `PINS OK: 33 files` before any sitting. Full hashes for every
mirrored file are in `docs/deployment/windows-deployment-next/EXPORT-MANIFEST.json`.

*Interim note:* this table predates the flags-18 repair. Section 5b lists the new shas of the six changed
files. The final push refreshes both the table and the mirror.

## 11. Parallel work: what the next agent can start now (model matrix, r6, r7)

The owner (2026-10-11 about 21:20) wants the next agent to start now, in parallel, on the **model-matrix
change** and the **r6 and r7 revisions**, while this Claude Code session finishes the r5 sitting repair.

### Takeover signal (interim)

This answers the trigger in the takeover agent's `docs/PIPELINE_TAKEOVER_PLAN_2026-10-11.md`, which is
untracked in the host checkout and written by that agent, not by this session.

- **Source commit:** `8554c76` is the frozen r5 source. The installed r5 runtime is a freeze of it
  (manifest `5d8d337b`). This push adds only documentation and mirror files.
- **Host state:** section 4, verified about 21:00. The Warden runs r4 (restored), admission is paused, and
  r5 is installed but not active.
- **Mirror and pins:** the `docs/deployment/` mirror is the `e559706` snapshot plus the v2 log and the v2
  diagnosis.
  - The files under repair (listed below) are **newer in W** than in the mirror.
  - Their interim shas are in section 5b.
  - The runner's pin table is being refreshed right now.
- **Completion:**
  - **Released to you now:** all source, routing, r6 and r7 work, and reading anything in W.
  - **Not yet complete:** the r5 sitting repair. FIX-NEXT and the two adversarial reviews are running.
  - When it completes, this session pushes a commit whose banner says **"r5 sitting repair COMPLETE"**,
    with the final pins, a re-exported mirror and the v3 command. After that commit, W is entirely yours.
- **Owner decisions:** the decisions recorded in the takeover plan take precedence over this handoff's
  routing proposals (R6_DESIGN, R6A, R6_SCOPE_V2), because the owner gave them to the takeover agent
  after this handoff was written:
  - the owner's ten-tier matrix in `docs/routing/4.2.7-routing-v3.owner-candidate.json`, with Gemini
    3.1 Pro High at tier 6
  - one combined final runtime
  - one administrator sitting of **20 minutes or less, elapsed**
- **The r5 v3 sitting is now an option, not the plan.**
  - Repaired, it runs about 65 minutes: S1 is skipped, and the six Google sign-ins at S6 are attended.
    That does not meet the 20-minute rule.
  - It would get a working pipeline sooner, because r4 admits no work now. Whether to run it is the
    owner's call. This session documents the command but will not press the owner to run it.
  - Either way, the repaired r5 cutover scripts are the reviewed building blocks for the combined package.
- **r7:** this session has no separate r7 specification. The owner mentioned r7 in chat. The only written
  material is `R6_DESIGN_20261011.md`'s draft of restart-free catalog activation, which the takeover plan
  already cites.

### Still owned by this session

Do not edit these until this session's final push lands on this branch:

- **The r5 sitting files in W:**
  - `RUN_427_R5_SITTING.ps1`, `RETURN_SETUP_R5_20261011.txt`, `refresh-r5-sitting-pins.py`
  - `test_r5_sitting_static.py`, `test_r5_sitting_flow.py`, `ps_toplevel_smoke.py`
  - The five flags-18 scripts in section 5b and `login-six-workers-status-first-r4-v1.ps1`, with their tests
  - `task_scheduler_host_projection.py`, `test_task_registration_flags_r5.py`
  - Any other W file the repair review touches
- **The mirror** `docs/deployment/windows-deployment-next/`. This session re-exports it; never edit it
  by hand.
- **The owner's next sitting** (`-Attempt v3`). This session hands the owner the verified command.

### What the next agent can start now

There is no overlap with the files above.

1. **Model-matrix (routing tier) redesign.** Section 8 has the owner's wishes verbatim:
   - Gemini 3.1 Pro in Sonnet 5.5's tier.
   - An agy-served Opus 5.5 fallback for when Claude quota is exhausted.
   - Fast upgrades for new models such as Gemini 4.0.

   Facts the design must respect:
   - The tiers are fixed in `src/cochem_pipeline/routing.py`, so any change is a source change with a
     new routing policy version.
   - `W\r5-army-specs\R6_V3_RESEARCH_20261011.md` gives the minimal footprint (`routing.py` + supervisor
     `probes.py`, `runner.py` recommended) and pre-computed digests.
   - agy Opus draws on Google's shared weekly "Claude and GPT models" bucket. Treat it as a small, capped
     fallback with its own quota pool.
2. **r6 and r7.** The owner names two revisions. The scope decisions in the takeover plan apply: one
   combined runtime and the owner's matrix. The older proposal material below splits into a
   deployment-layer part and a source part, and is useful as an inventory of building blocks.
   - **Deployment layer on the installed r5 runtime** ("r6a" in `R6A_SCOPE_20261011.md`):
     - a binding plan for Gemini routes
     - per-route evidence groups and builder gating
     - a `-GeminiPro required|optional` switch
     - a `-Mode rebind` kit for adding a model without a reinstall

     Limit: it can only bind routes that already exist in r5's code tier table. Gemini 3.1 Pro exists
     there today only in the higher tiers, so **moving it to tier 4-6 needs the source part**.
   - **Source revision** ("r6b" in `R6A_SCOPE`, and `R6_DESIGN_20261011.md`):
     - catalog-driven tiers (routing policy v3)
     - `target_kinds` allowlists
     - the PB "slug carries effort" contract
     - an operator canary route and a batch submission tool
     - a supervisor catalog and the Claude Extended effort contract
     - the deferred items in section 8
3. **Further candidates found today:**
   - **CPU budget.** r5 keeps the 5 % Warden CPU budget, and sitting step S12 waits up to 120 s for
     admission. The r4 controller was seen at 5.56 % CPU and 4433 IOPS (limit 4000), so a CPU-only pause
     could fail S12 and restore r4. Review the CPU budget and add hysteresis in the next source revision.
     Watch for this in the v3 sitting.
   - **Task registration rule.** Any new owner script that registers a one-shot task must use flags 18
     with the exact check, tested against `task_scheduler_host_projection.py` (section 5b).
   - **Cleanup.** An optional reviewed, elevated cleanup for never-run held tasks: the 14 from v2, plus
     anything later sittings leave.

### Where to work

- **Source:** create a new branch from `feature/r5-gemini-and-runtime-fixes` at `8554c76`, for example
  `feature/r6-model-matrix`. Do not change the 13 r5 source files on the r5 branch: the installed r5
  runtime is a freeze of `8554c76`, and the sitting verifies it by manifest.
- **New owner scripts for r6/r7:** create new files in W with new names (for example `*-r6-*`). Copy
  patterns from the repaired r5 scripts **after** the final push, so you inherit the flags-18 and
  validated-parameter fixes.

### Host rules while both agents work

- AGENTS.md allows only one live engineering session per host. The owner has asked for parallel work.
- If the next agent runs on AETHERDESK at the same time as this session:
  - Keep to design and code.
  - Run every test through `W\serialize-heavy.py`. Its lock is host-wide, so the two agents' runs queue
    instead of overlapping.
  - No sittings, no elevated or `-Apply` runs, no agent-spawning loops.
- If the next agent works from a cloud clone, GitHub is all it sees: read this handoff and the mirror.
