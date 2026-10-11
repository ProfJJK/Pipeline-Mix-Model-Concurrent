# Windows deployment agent handoff — 9 October 2026, evening continuation

Supersedes the deployment-state statements of
[the morning handoff](WINDOWS_AGENT_HANDOFF_4.2.7_2026-10-09.md) only where dated below;
canonical policy, owner decisions and preservation rules there are unchanged.

## What changed today (after 18:48 CDT)

1. **Host crash.** AETHERDESK bug-checked (0x21 QUOTA_UNDERFLOW) at 18:48:42 while a
   Claude session was idle; see [the post-mortem](WINDOWS_CRASH_POSTMORTEM_2026-10-09.md).
   After the reboots **the r3 Warden is not running** (nothing listens on 127.0.0.1:47824).
   The SYSTEM task `CoChem-4.2.7-Warden` is unreadable to ordinary processes; whether it
   is still registered and enabled must be reattested by the owner (Task Scheduler as
   Administrator) before any lifecycle action. The held supervisor observer and the
   resource recorder bound the old controller instance and also need reattestation.
2. **Telemetry repair implemented** (the morning handoff's confirmed blocker). Branch
   `fix/telemetry-commit-probe-retention` in this repository:
   `5d592f9` fix + tests + evidence, `1688b0f`/`1279136` agent guard, `85f08ac` CRLF
   normalisation, `47efbe1` `.mcp.json`. `resource_telemetry.PerformanceInformation` is
   defined once at module scope and `_commit_probe()` caches the `GetPerformanceInfo`
   binding with `functools.lru_cache(maxsize=1)` (failed binds are never cached). ABI,
   schema, thresholds and non-Windows behaviour are unchanged. Repaired file SHA256
   `e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc`.
   - Tests: `pipeline_tests/test_resource_telemetry.py` gained ABI (104-byte structure),
     schema, 1,000-probe retention/growth and failed-bind non-caching cases.
   - Full suite on this host in the repository venv (Python 3.12.13): **2756 passed,
     387 skipped**.
   - Isolated Windows measurement (`docs/evidence/windows-2026-10-09/telemetry-repair/`):
     r3 source retained 3,000 types / +41.6 MiB private over 3,000 probes; repaired
     source retained 1 type / +0.0 MiB.
3. **r4 stopped-runtime preparation** in the engineering workspace
   `C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next`:
   `freeze-stopped-runtime-r4-source.py` (stages the installed r3 frozen tree plus the
   one repaired file under `C:\Users\ansac\CoChem427\stopped-runtime-r4-source`, emits the
   `cochem-stopped-runtime-source/1` manifest), `install-stopped-runtime-r4.ps1`
   (adapted from the reviewed r3 installer: previous runtime r3, target
   `Pipeline4.2.7-windows-20261009-r4`, exactly one reviewed changed file, r3 receipts
   pinned, managed daemon tasks may keep running and are only checked for not referencing
   the new root; `-Apply` still requires the owner elevated), `test_stopped_runtime_r4.py`,
   and `RETURN_SETUP_R4_20261009.txt` with the owner's exact commands. The agent ran the
   freeze (manifest SHA256 `1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189`,
   166 files, 165 byte-identical to r3), the installer's read-only plan (mode `READ_ONLY_PLAN`,
   one expected hold: the SYSTEM task definitions are unreadable without elevation) and the
   inert harness. Step 2 (`-Apply`, elevated) is the owner's; it downloads the locked wheels
   from PyPI with `uv --no-cache`, exactly as the r3 build did, so it needs internet access.
4. **Source-of-truth warning.** Against the 166 installed r3 frozen files, the GitHub clone
   (`C:\Users\ansac\source\repos\...`) has 59 byte-identical files, 102 that differ only by
   line endings (LF in the clone, mostly CRLF in r3; `pyproject.toml` is one of these), and 5
   that differ in content: `README.md`, the repaired `resource_telemetry.py`, and three files
   edited after the freeze that the Google Drive tree carries too (`performance_acceptance.py`,
   `cochem_supervisor/engine.py`, `cochem_supervisor/replay.py`). r4 takes only the telemetry
   repair; those three post-freeze edits need their own review before any r5.
5. **Agent guard rails.** `.claude/hooks/cochem_host_guard.py` + `.claude/settings.json`
   (Claude Code PreToolUse hook) and `AGENTS.md`/`CLAUDE.md`/`GEMINI.md` in this repository
   and in `D:\__CoChem\GitHub-Repo`. Read `AGENTS.md` before running anything on this host.
6. **GUI access.** The pipeline MCP server (`cochem_pipeline mcp`, 15 tools) is registered
   for Codex (`~/.codex/config.toml`) and Claude Code (`.mcp.json`). Claude Desktop and
   Antigravity entries were prepared but not written (owner permission); the Antigravity
   entry currently points at a 4.2.2 token path and must be replaced. See
   `RETURN_SETUP_R4_20261009.txt`.

7. **Controlled switch prepared (10 October, v2.2 after two independent reviews and their
   re-reviews).** The re-reviews confirmed every earlier finding resolved and added, now in
   v2.2: a `robocopy /L` backup-rights probe before any attempt namespace is consumed (also
   run by the elevated read-only plan, which the owner sheet now requires before the
   switch); two independent backup passes that must agree byte for byte, the witness copy
   kept raw; `/A-:RSH` on the copies; an elevated worker sweep that takes owners from one
   `Get-Process -IncludeUserName` call, re-queries any process whose owner cannot be
   resolved and excludes the ones that exited mid-sweep (four on the live plan); a
   refused queue-directory probe treated as "exists"; `run_requested` set before `Run`;
   and the process proof's no-listener branch made reachable. Harness: 107 cases.
   Earlier text follows.
   `retarget-warden-r4.ps1` in the engineering workspace retargets the existing
   `CoChem-4.2.7-Warden` task's action (r4 interpreter, r4 working directory, same preserved
   configuration, fresh `--queue-launch-output` directory, because the daemon refuses a
   pre-existing one) after capturing the task XML and private DACL, writing a durable intent
   and backing up the private SQLite stores. The first review found two high-severity
   defects in v1 (a Python program passed through `-c` is truncated by Windows PowerShell
   5.1 quoting; native stderr became a terminating error under `Stop`); the second found two
   more in v2 (the private root is SYSTEM-only, provisioned by `windows.py` as
   `O:SYG:SYD:P(A;OICI;FA;;;SY)`, so the elevated owner cannot read it, and a read-only
   SQLite open of a cleanly closed WAL store still creates `-wal`/`-shm` beside the source).
   v2.1 therefore copies `*.db`, `*.db-wal` and `*.db-journal` with `robocopy /B` (backup
   semantics, sources never opened by SQLite) into a SYSTEM/Administrators-only
   `state-backup` directory, and the hash-pinned helper `backup-private-databases-r4.py`
   verifies the copies only (WAL recovery, `integrity_check`, tables, SHA256). Every native
   call is judged by exit code and decoded as UTF-8 (`-X utf8`); the port query fails
   closed unless the cmdlet's own no-match error is returned; `127.0.0.1:47824` must be
   bindable exclusively by the pinned base interpreter (verified behind a deny-write handle);
   the other managed daemon tasks must be stopped and disabled; slot-worker processes and,
   when elevated, any user-mode process whose owner cannot be resolved are holds; the two
   observer recorder tasks are recognised by their pinned script paths, recorded in the
   receipts and left alone; receipt booleans and counts must carry native JSON types; the
   task XML outside `Actions`/`RegistrationInfo` is diffed after the write; every attempt is
   namespaced (`-Attempt vN`, never reused). A failed readback after the mutation writes
   `retarget-held.json`; any failure after the start intent writes `start-held.json`; both
   require a reviewed recovery, and the owner sheet now says so (a retry with the next
   `-Attempt` is valid only for holds raised before the task changed). `-Apply -Start` (or
   `-Apply` then `-Apply -StartOnly`; `-StartOnly` alone prints the start plan) requests
   exactly one Run and accepts only two stable `/health` samples (same pid, instance and
   start time, SYSTEM, r4 root, no active work, no quarantined slots) plus a task readback
   showing exactly that one running instance and a process proof that the pid runs the r4
   daemon command, runs as SYSTEM and owns the listening socket. The top-level console
   status after a combined run is the start status. No retry, stop or delete exists. Inert
   harness `test_retarget_warden_r4.py` (100 cases: fixture-driven register and run paths
   including the held records, real robocopy without `/B`, the real helper on clean and
   crash-state WAL copies, the bind probe against a held port, real PowerShell 5.1
   functions) passes in about 150 s; the read-only plan ran as the ordinary user with three
   expected holds (r4 not yet built, task definition unreadable without elevation, three
   SYSTEM python processes uninspectable without elevation). Not exercised inertly: `/B`
   itself (needs the elevated token) and the scheduler's XML re-serialisation after a real
   `TASK_UPDATE`. The held supervisor observer and resource recorder are deliberately not
   rebound by this script.

8. **Launched (10 October, 19:57 to 20:01 CDT).** The owner ran the one-sitting series
   `RUN_427_LAUNCH_SERIES.ps1` (revision 3) once: zero holds, r4 built
   (`FRESH_STOPPED_RUNTIME_READY`), `CoChem-4.2.7-Warden` retargeted and started once,
   controller pid 20664 (launcher 5320) as SYSTEM from
   `Pipeline4.2.7-windows-20261009-r4\.venv\Lib`, instance `61497bdab0514590b88fd0cab689a404`,
   receipts under `WardenRetarget4.2.7-windows-20261010-r4-v1`. The held supervisor observer
   reported the new controller healthy within the run. Admission ramped from the recovery
   window to capacity 4. First real job: provider preflight workflow
   `3bc91a4f6d9640e39167ebafce69fde3` at 20:13, routed to gemini-3.8-flash first (refused by
   the integration hold as a `compatibility` failure, as designed), then completed on slot 1
   with claude-haiku-4-5, output `{"ready": true}` with a native receipt. Legacy pipelines:
   tasks `CoChemHostWarden_V412`, `CoChem V4.1.2 Swarm` and two disabled fixtures
   unregistered, the Startup launcher removed, `D:\__CoChem\__agentic\v4.2.0` and the contents
   of `v4.1.2` deleted; what remains is `v4.1.2\vm\`, the virtual disks of the Hyper-V
   quarantine VM, which Hyper-V keeps open and which only the owner may stop or remove. Task
   XML exports and the launcher are kept in the workspace folder
   `legacy-removal-evidence-20261010\`. All GUI MCP entries point at r4 and were verified
   (15 tools, health through the MCP). The fix branch is pushed.

## Still open (unchanged unless noted)

- Rebinding of the held supervisor observer and resource recorder to the r4 controller
  instance (they still bind r3 PID 5788 / instance `c867588c…`): not written.
- Two approved synthetic workflows: unsubmitted; need a running, repaired Warden with
  fresh admission readiness.
- 48-hour observation window, desktop-heap evidence, recovery timing, repair-spend
  authority: open.
- Minidump `C:\WINDOWS\Minidump\100926-9843-01.dmp`: owner-only; `!analyze -v` recommended.
