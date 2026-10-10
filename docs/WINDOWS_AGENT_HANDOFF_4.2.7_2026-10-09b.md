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

7. **Controlled switch prepared (10 October, v2 after an independent review).**
   `retarget-warden-r4.ps1` in the engineering workspace retargets the existing
   `CoChem-4.2.7-Warden` task's action (r4 interpreter, r4 working directory, same preserved
   configuration, fresh `--queue-launch-output` directory, because the daemon refuses a
   pre-existing one) after capturing the task XML and private DACL, writing a durable intent
   and taking read-only SQLite backups with WAL content. The review found two high-severity
   defects in v1 (a Python program passed through `-c` is truncated by Windows PowerShell
   5.1 quoting; native stderr became a terminating error under `Stop`) and v2 fixes them:
   the backup program is the hash-pinned helper `backup-private-databases-r4.py`, copied
   into the attempt root and run by path, and every native call is judged by exit code.
   v2 also stores backups under a SYSTEM/Administrators-only DACL, fails closed when the
   port query cannot answer, proves `127.0.0.1:47824` can be bound exclusively, requires the
   other managed daemon tasks to be stopped and disabled and no slot-worker process to be
   alive, diffs the task XML outside `Actions`/`RegistrationInfo` after the write, and
   namespaces every attempt (`-Attempt v1`, `v2`, ...; a consumed namespace is never
   reused). `-Apply -Start` (or `-Apply` then `-Apply -StartOnly`) requests exactly one Run
   and accepts only two stable `/health` samples (same pid, instance and start time, SYSTEM,
   r4 root, no active work, no quarantined slots) plus a task readback showing exactly that
   one running instance and a process proof for the pid; otherwise it writes
   `start-held.json` and stops. No retry, stop or delete exists. Inert harness
   `test_retarget_warden_r4.py` (56 cases, fixture-driven register and run paths, temp
   SQLite backups, real PowerShell 5.1 functions) passes; the read-only plan ran as the
   ordinary user with only the two expected holds (r4 not yet built, task definition
   unreadable without elevation). The held supervisor observer and resource recorder are
   deliberately not rebound by this script.

## Still open (unchanged unless noted)

- Rebinding of the held supervisor observer and resource recorder to the r4 controller
  instance (they still bind r3 PID 5788 / instance `c867588c…`): not written.
- Two approved synthetic workflows: unsubmitted; need a running, repaired Warden with
  fresh admission readiness.
- 48-hour observation window, desktop-heap evidence, recovery timing, repair-spend
  authority: open.
- Minidump `C:\WINDOWS\Minidump\100926-9843-01.dmp`: owner-only; `!analyze -v` recommended.
