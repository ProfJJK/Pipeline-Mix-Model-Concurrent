# What must happen before the 4.2.7 pipeline runs again

> **Superseded by the one-step series (later on 10 October).** All owner steps below are now
> executed by `RUN_427_LAUNCH_SERIES.ps1` in one elevated run; see "THE ONE STEP" at the top
> of `RETURN_SETUP_R4_20261009.txt`. The agent has already done the non-elevated items
> (GUI entries point at r4, fix branch pushed, legacy entries removed from the Antigravity
> config). This page remains as the audit record.

AETHERDESK, 10 October 2026. Result of a seven-agent read-only audit of the live host plus the
deployment documents. Commands and expected outputs are in `RETURN_SETUP_R4_20261009.txt`
(same folder); this page is the ordered summary. Nothing below has been started.

## State today

- The 4.2.7 Warden is down since the 9 October crash: nothing listens on 127.0.0.1:47824.
- The installed r3 runtime still carries the telemetry leak. The repaired r4 runtime is **not
  built**. Its source (166 files, one changed) is staged and verified; the clone, toolchain,
  r3 receipts and PyPI reachability all check out.
- Host after the reboot: R: RAM disk present (the daemon recreates its workspace itself),
  WSL2 and the Docker backend up, token file and ACLs intact, six worker identities present,
  twelve CLI sessions last verified 8 October with no expiry on record, clock synchronised,
  no pending Windows Update reboot.
- Running beside the pipeline: the held-supervisor observer (passive, still bound to the dead
  r3 controller) and the **legacy 4.1.2 swarm**: `CoChemHostWarden_V412` is running as
  elevated ansac (python PID 4516 on 127.0.0.1:47821) and `CoChem V4.1.2 Swarm` starts
  `start_pipeline.bat` at every logon. Agents may not touch those tasks.

## Owner steps, in order (gate in italics)

1. **Pre-step, ordinary shell.** Stay logged in with Docker Desktop running from now on: the
   daemon's Docker preflight uses the engine of your logon session. Run `docker info` and
   `docker image inspect` on the allowlisted image as written in the sheet. Decide, in Task
   Scheduler, whether the two legacy 4.1.2 tasks stay enabled while 4.2.7 runs.
   *Gate: engine answers linux / all limits true; image Id matches; decision made.*
2. **Step 2, Administrator PowerShell 5.1.** Build the stopped r4 runtime with the installer and
   `-Apply` (internet needed, about 107 locked wheels).
   *Gate: mode FRESH_STOPPED_RUNTIME_READY, holds empty, install-after.json present.*
3. **Step 3a-elevated, same shell.** `whoami /priv` must list SeBackupPrivilege and
   SeRestorePrivilege. Run the retarget script **without** `-Apply`. Then the two read-only
   checks the scripts cannot make: Defender exclusions for the six slot roots, and the six
   worker directories present.
   *Gate: holds empty, backup rights verified, no uninspectable or unclassified processes.*
4. **Step 3b, same shell.** Retarget script with `-Apply -Start -Attempt v1`. It backs up the
   private stores twice with robocopy backup mode, switches the task action to r4, starts it
   once and waits up to 240 s for two stable health answers.
   *Gate: console status WARDEN_R4_RUNNING_HEALTH_VERIFIED. A retarget-held.json or
   start-held.json means stop and hand back the files; never start the task by hand, never
   retry with another attempt.*
5. **Post-start health (agent, no owner action).** Read /health through the existing MCP
   client. *Gate: RSS under 50 MiB, admission capacity above zero, no quarantined slots,
   knowledge component ok.* Nothing is submitted while admission is paused.
6. **GUI repointing (after 5).** Agent edits the Codex entry and both `.mcp.json` files to the
   r4 path. You paste the r4 entry into Claude Desktop (no `mcpServers` key exists yet) and
   replace the stale Antigravity entry (still a 4.2.2 token path and the old Drive clone).
   Restart each GUI. *Gate: each GUI lists 15 tools and pipeline_health returns JSON.*
7. **Observer rebinding (agent writes and reviews; you run elevated).** Rebind the
   held-supervisor observer and the resource recorder to the r4 controller instance and start
   the recorder once. *Gate: a fresh, uninterrupted 48-hour window starts.* Consider pausing
   Windows Update for that window.
8. **Synthetic workflows.** Approval is on file and must not be re-asked. Mechanism to decide
   first: GUI submission or a reviewed successor preserving the recorded request IDs.

## Not launch gates (after launch)

- Push the 13 unpushed commits of `fix/telemetry-commit-probe-retention` (needs your go).
- Decide the regenerated `src/cochem.egg-info/PKG-INFO` in the clone.
- Agy/Gemini provider stays on its verification hold; Claude and Codex serve jobs.
- Minidump analysis with WinDbg, Dev-channel and WSL2-cap decisions from the post-mortem.
- Retire the old Antigravity clone once attested safe; stray `x.py` in the frozen src root.
