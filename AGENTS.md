# Agent rules for this workstation (AETHERDESK) — read before running anything

**Why these rules exist.** On 2026-10-09 at 18:48 this machine bug-checked (Windows stop code 0x21
QUOTA_UNDERFLOW in `nt!PspReturnQuota`, roughly 32 GiB of commit quota returned by one process)
with an agent session open (idle at that moment; the stop code is a kernel fault, see the
post-mortem in the pipeline repository). Windows here is a pre-release Dev-channel build (26300)
running WSL2 + Docker Desktop, Hyper-V (VM `CoChem-Golden-Baker`, switch `CoChem-Quarantine-Switch`)
and an 8 GiB ImDisk RAM disk on R:. Large memory teardowns and process storms can take the whole
host down, and earlier BSODs (September 2026) came from agentic swarm spawn storms. Agents therefore
keep a small footprint and never touch host lifecycle. A PreToolUse hook in `.claude/settings.json`
(`.claude/hooks/cochem_host_guard.py`) enforces the hard rules for Claude Code's shell, file and
MCP tools; Codex and Antigravity agents must follow them by reading this file.

## Never — enforced by the hook
- Start, stop, restart or reconfigure WSL (shutdown, terminate, unregister, import/export),
  Docker (compose down/up, stop, kill, rm, prune, Docker Desktop), Hyper-V VMs (every `*-VM*`
  cmdlet except `Get-VM*`), ImDisk / volumes / diskpart, Windows services, scheduled tasks, or the
  machine itself, directly or through `Start-Process`, `Invoke-Expression` or `cmd /c`.
- Launch the legacy swarm daemons or any script under `D:\__CoChem\__agentic\v4.x`:
  `start_pipeline.bat`, `cochem_startup.vbs`, `pythonw -m cochem.*`, `watchdog_sre.py`,
  `worker_daemon`, `cochem_master_loop*`, `task_work_loop.py`, `cochem_ha_daemon_watchdog`.
- Start, provision or switch the live 4.2.7 controller/warden/supervisor (`cochem_pipeline daemon`,
  `provision-execution`, `cochem_supervisor daemon/once/recover/resume`, any deployment `.ps1`
  with `-Apply`). Those run as SYSTEM from scheduled tasks and only the owner starts them, through
  one reviewed Administrator series.
- Run more than four heavy processes at once (`pytest -n` or `--numprocesses` above 4, `xargs -P`
  above 4, `ForEach-Object -Parallel` without `-ThrottleLimit` 4 or less, `make -j` above 4).
- Kill processes by image name or tree (`taskkill /IM`, `/T`, `Stop-Process -Name`,
  `Get-Process x | Stop-Process`, `pkill`); kill a specific PID you own instead.
- Elevate (`-Verb RunAs`, `sudo`, `runas`, `psexec -s`), edit HKLM, `bcdedit`, install software,
  or write, copy over or delete `~/.wslconfig`, Docker settings, the Startup folder,
  `C:\Program Files\*`, `C:\ProgramData\CoChemPipeline427\*`, `.claude/settings*.json`,
  `.claude/hooks/*` or the guard off-switch.
- Spawn headless agent CLIs (`claude -p`, `codex exec`, `codex --full-auto`, `gemini --yolo`, `agy`).

## Never — rule only, not detectable by a hook
- Run a second Claude / Codex / Antigravity session doing pipeline work on this host at the same
  time as another one. One live engineering session per host.
- Have several agents or subagents each run a test suite or build at the same time.

The hook scans whole command texts (heredoc bodies included) and the command- and path-like
fields of MCP tool calls. If a harmless command is denied only because it *mentions* a blocked
pattern (for example writing documentation), use the Write / Edit / Read tools for that file.
It fails closed on internal errors. The owner can switch it off by creating
`%USERPROFILE%\.claude\cochem-host-guard.off`; agents never create or mention that file.
Blocked attempts are logged in `%USERPROFILE%\.claude\cochem-host-guard.log`. The hook's
behavioural tests live in the pipeline repository (`pipeline_tests/test_cochem_host_guard.py`).

## Always
- Use the pipeline's own interpreter: `C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\.venv\Scripts\python.exe`
  (Python 3.12, created with `uv sync --frozen --extra dev --extra mcp`). Never the global
  `C:\Python314` for pipeline code — its user site has ~17 `.pth` shims that shadow modules such
  as `scripts`. (The guard hook itself runs under the `py -3` launcher; that is fine.)
- Wrap long commands in `timeout` and keep test runs single-process (`-p no:cacheprovider`, no `-n`).
- Before running any test whose name says actual / real / live / physical, read it. It must be
  in-process only (loopback HTTP, temp SQLite, in-memory MCP). Skip it otherwise.
- Stop at the UAC boundary: prepare and independently review scripts, then hand the owner one
  consolidated Administrator PowerShell series. Never ask the owner to repeat approvals already
  granted (see `docs/WINDOWS_AGENT_HANDOFF_4.2.7_2026-10-09.md` in the pipeline repo).
- If the machine crashes again, the owner can analyze `C:\WINDOWS\Minidump\*.dmp` with WinDbg
  (`!analyze -v`).

## Owner-approved Codex, Claude and Agy sign-in experience
2026-10-13: the owner explicitly extended the successful `agy-signin-c4d4a66`
interaction format to **Codex, Claude and Agy**. Use the standard Windows
dialog with a selectable fresh URL, **Copy URL**, a masked field supporting normal
Ctrl+V, and **Submit**/Enter. The owner opens the URL manually. Handle profiles
sequentially, verify authentication after each, and skip already verified sessions.
Do not revert to automatic browser launching, native TUI navigation, raw console
key capture, or deployment as a prerequisite for signing in. Preserve the existing
isolation/cleanup checks. See `docs/AGY_SIGNIN_2026-10-13.md` for the successful
six-profile host receipt and the reusable implementation. Fresh attempts always
need their own URL/code; never reuse prior OAuth links or codes.
Respect each provider's protocol: Codex device codes are entered in the browser;
only show a masked callback-code field when the provider actually requires one.
This is the preferred interface, not a claim that all three adapters have been
implemented or accepted on this host. Reuse verified sessions before asking for input.

## Current handoff
2026-10-12: the Claude Code session has released all locks to the takeover agent; see
`docs/AGENT_RELEASE_NOTICE_2026-10-12.md`.
Start with `docs/WINDOWS_AGENT_HANDOFF_4.2.7_2026-10-11.md` (branch `feature/r5-gemini-and-runtime-fixes`):
the Warden is down, r5 is installed but not activated, and the owner's sitting rerun is the next step.
The routing-tier redesign is left open for the next agent. A mirror of the deployment workspace is in
`docs/deployment/windows-deployment-next/`.

## Where things are
| Thing | Path |
| --- | --- |
| Pipeline 4.2.7 source (GitHub ProfJJK/Pipeline-Mix-Model-Concurrent) | `C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent` |
| Installed protected runtimes (owner/admin only) | r4 (last active) `C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4`; r5 (installed, not activated) `...\Pipeline4.2.7-windows-20261011-r5`; r3 `...\Pipeline4.2.7-windows-20261007-r3` |
| Runtime client config used by every GUI's MCP entry | `C:\Users\ansac\CoChem427\pipeline-client-r3.json` |
| Deployment engineering workspace (installers, freezes, owner sheets) | `C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next` |
| Legacy agentic swarm trees (retired 2026-10-10; never start or restore) | `D:\__CoChem\__agentic\v4.1.2`, `D:\__CoChem\__agentic\v4.2.0` |
| Workspace folder (untracked inside the `D:\__CoChem` git repo) | `D:\__CoChem\GitHub-Repo` |
| Owner's hardening notes from earlier BSODs | `D:\__CoChem\PRIORITY-PIPELINE-*.md` |
