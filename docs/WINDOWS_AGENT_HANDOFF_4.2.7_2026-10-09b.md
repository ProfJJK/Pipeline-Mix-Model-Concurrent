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
   and `RETURN_SETUP_R4_20261009.txt` with the owner's exact commands. The agent process
   was not permitted to execute the freeze or the read-only plan; the owner runs steps 0–1
   first and stops on any unexpected hold.
4. **Source-of-truth warning.** The GitHub clone (`C:\Users\ansac\source\repos\...`, LF
   endings, edited README/pyproject) and the Google Drive tree (CRLF, three supervisor
   files edited after the freeze: `performance_acceptance.py`, `cochem_supervisor/engine.py`,
   `cochem_supervisor/replay.py`) both differ from the installed r3 frozen source. r4 takes
   only the telemetry repair. Reconcile the clones before any wider r5.
5. **Agent guard rails.** `.claude/hooks/cochem_host_guard.py` + `.claude/settings.json`
   (Claude Code PreToolUse hook) and `AGENTS.md`/`CLAUDE.md`/`GEMINI.md` in this repository
   and in `D:\__CoChem\GitHub-Repo`. Read `AGENTS.md` before running anything on this host.
6. **GUI access.** The pipeline MCP server (`cochem_pipeline mcp`, 15 tools) is registered
   for Codex (`~/.codex/config.toml`) and Claude Code (`.mcp.json`). Claude Desktop and
   Antigravity entries were prepared but not written (owner permission); the Antigravity
   entry currently points at a 4.2.2 token path and must be replaced. See
   `RETURN_SETUP_R4_20261009.txt`.

## Still open (unchanged unless noted)

- Controlled r3 → r4 switch script (handoff steps 4–7): not written. Do not improvise.
- Two approved synthetic workflows: unsubmitted; need a running, repaired Warden with
  fresh admission readiness.
- 48-hour observation window, desktop-heap evidence, recovery timing, repair-spend
  authority: open.
- Minidump `C:\WINDOWS\Minidump\100926-9843-01.dmp`: owner-only; `!analyze -v` recommended.
