# AETHERDESK crash post-mortem — 9 October 2026

Scope: the Windows bugcheck at 18:48:42 CDT on 9 October 2026 while two Claude Code
sessions were open, what the evidence shows, and the controls installed afterwards.
This is an engineering record for the owner; it does not change canonical SRS policy.

## What happened

| Local time (CDT) | Event | Source |
| --- | --- | --- |
| 16:56 | Claude session A (`d7fdb30d`) started on the 4.2.7 pipeline handoff | session transcript |
| 17:08 | Session A's model request timed out; idle until the owner typed "Try again" at 18:44 | transcript |
| 18:44–18:47 | Session A ran read-only inspection commands, then one pytest test (`test_actual_pipeline_mcp_session_creates_and_cancels_real_dag`, loopback HTTP + temp SQLite + in-memory MCP, no subprocess, no Docker, no live controller) | transcript |
| 18:47:30 | That test returned `1 passed in 6.49s`; no further tool ran | transcript tool result |
| 18:48:42 | **Bugcheck 0x21 QUOTA_UNDERFLOW** in `nt!PspReturnQuota`; parameters `(0xffffaa8db06e3040, 0x2, 0x7ffffffee, 0x7ffea5693)`; minidump `C:\WINDOWS\Minidump\100926-9843-01.dmp` | System log 6008/1001, Kernel-Power 41 |
| 18:49:17 | Automatic reboot | Kernel-General 12 |
| 18:53 | Claude session B (`af820e55`) started (plugin/skills question) | transcript |
| 19:23:28 | Owner-initiated restart from the Start menu | User32 1074 |
| 19:24:07 | Current boot | Kernel-General 12 |

Bugcheck 0x21 means the kernel tried to return more pagefile/commit quota (type 2) to a
process than that process had charged. The two amounts are both about 32 GiB. Only
kernel-mode code can trigger this stop code; user-mode programs cannot corrupt quota
accounting directly. The host runs a pre-release Windows build (26300.9457, Dev channel)
with WSL2 + Docker Desktop (VM cap 41,943,040,000 bytes in `.wslconfig`), Hyper-V
(`CoChem-Golden-Baker`, `CoChem-Quarantine-Switch`), an 8 GiB ImDisk RAM disk and the
NordVPN threat-protection filter driver, all of which allocate or release large
kernel-tracked memory.

## What the agents were doing

- Session A was idle for 72 seconds before the bugcheck. Its last command was in-process
  only and had exited. Session B did not exist yet.
- No pipeline state (`C:\Program Files\CoChem\*State*`, Warden/supervisor receipts) was
  written between 18:40 and 18:49; the installed controller was idle.
- Codex, Antigravity and Ollama logs show no activity in the window beyond Ollama's
  hourly update check at 18:46:49.
- The legacy v4.1.2/v4.2.0 agentic swarm daemons were not running (the v4.2.0 launcher
  logged "pipeline NOT started" at every logon; no `pythonw` processes).

Conclusion: the crash was a kernel quota-accounting fault, most plausibly during a
large virtual-machine or job-object memory teardown, on a pre-release kernel. It was
not caused by a command either Claude session was executing at the time. The minidump
is readable only by an administrator; `!analyze -v` in WinDbg would name the owning
process. Earlier BSODs on this host (September 2026, see `D:\__CoChem\PRIORITY-PIPELINE-*.md`)
were caused by agentic subprocess spawn storms, which is why agent load remains the
first suspect whenever this machine crashes.

## Controls installed

1. **Host guard hook** (`.claude/hooks/cochem_host_guard.py`, wired by `.claude/settings.json`
   in this repository and in `D:\__CoChem\GitHub-Repo`): a Claude Code PreToolUse hook that
   denies WSL/Docker/Hyper-V/service/scheduled-task lifecycle commands, legacy swarm daemon
   launches, live controller starts (`cochem_pipeline daemon`, `provision-execution`,
   `cochem_supervisor daemon/once/recover/resume`), elevation, HKLM edits, image-name kills,
   more than four-way parallelism, headless agent CLI spawns, and writes to `.wslconfig`,
   Docker settings, the Startup folder, `C:\Program Files`, `C:\ProgramData\CoChemPipeline427`
   and the guard itself. 54 self-test cases pass. Blocked attempts are logged to
   `%USERPROFILE%\.claude\cochem-host-guard.log`; the owner-only off switch is
   `%USERPROFILE%\.claude\cochem-host-guard.off`. It covers Claude Code's shell and file
   tools only (not MCP file tools), and it scans whole command text, so a heredoc that merely
   mentions a blocked pattern is refused; use the file tools for such documents.
2. **Written rules** for every agent GUI: `AGENTS.md` (imported by `CLAUDE.md` and
   `GEMINI.md`) in this repository and in `D:\__CoChem\GitHub-Repo`.
3. **Dedicated interpreter**: `.venv` (Python 3.12.13, `uv sync --frozen --extra dev --extra mcp`)
   so tests never run under the global `C:\Python314`, whose user site shadows modules.

## Recommendations for the owner (not done by the agent)

- Analyze the minidump once: install WinDbg (`winget install Microsoft.WinDbg`), open
  `C:\WINDOWS\Minidump\100926-9843-01.dmp`, run `!analyze -v`, and note the process name.
- Consider leaving the Dev channel for this workstation, or report the dump through
  Feedback Hub; the stop code is a kernel defect that no user-mode guard can fully prevent.
- Consider lowering the WSL2 cap in `~/.wslconfig` (currently ~39 GiB) so a VM teardown
  returns less memory at once, and set `vmIdleTimeout` deliberately.
- Keep one engineering agent session per host; the guard enforces the rest.
