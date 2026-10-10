"""CoChem host guard: a Claude Code PreToolUse hook that blocks host-lifecycle commands.

Why this exists: AETHERDESK bug-checked on 2026-10-09 (0x21 QUOTA_UNDERFLOW) while agents
were working. The host runs a pre-release Windows build with WSL2/Docker, Hyper-V and an
ImDisk RAM disk, so VM/daemon/service churn and process storms can take the machine down.
This hook denies the commands that start, stop or restart host infrastructure, spawn the
agentic swarm daemons, elevate, or fan out more than four heavy processes.

It is a guard rail, not a sandbox. To disable it deliberately, the OWNER creates the file
%USERPROFILE%\\.claude\\cochem-host-guard.off (agents must not create it).
Blocked attempts are appended to %USERPROFILE%\\.claude\\cochem-host-guard.log.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys

HOME = os.path.expanduser("~")
OFF_SWITCH = os.path.join(HOME, ".claude", "cochem-host-guard.off")
LOG = os.path.join(HOME, ".claude", "cochem-host-guard.log")

# A shell "segment" ends at &&, ||, |, ; or a newline; path rules never cross one.
_SEG = r"[^\n&|;]*"
_GUARD_FILES = r"(\.wslconfig|settings-store\.json|host_guard\.py|[\\/]\.claude[\\/]settings(\.local)?\.json|Startup[\\/])"

# (pattern, reason). Matched case-insensitively against the whole command text.
COMMAND_RULES: list[tuple[str, str]] = [
    (r"\bwsl(\.exe)?\s+(--shutdown|--terminate|-t\b|--unregister|--import\b|--export\b|--install\b|--update\b)",
     "WSL lifecycle (shutdown/terminate/unregister/import) tears down the WSL2 VM and its memory"),
    (r"\bdocker(\.exe)?\s+(system\s+prune|rmi\b|kill\b|restart\b|stop\b|compose\s+(down|up|restart)|desktop\b|context\s+(use|rm))",
     "Docker lifecycle operations restart or tear down the Docker/WSL2 VM"),
    (r"\b(Stop|Start|Restart|Remove|Save|Suspend|Resume|Checkpoint|New|Set|Export|Import)-VM\b",
     "Hyper-V VM control is owner-only on this host"),
    (r"\b(Restart|Stop)-Computer\b|\bshutdown(\.exe)?\s+/[rsfgh]|\blogoff\b",
     "Power actions are owner-only"),
    (r"\bimdisk(\.exe)?\b|\b(Mount|Dismount)-DiskImage\b|\bNew-VirtualDisk\b|\bFormat-Volume\b|\bformat\s+[a-z]:",
     "RAM disk / volume operations are owner-only (R: is the pipeline's ImDisk volume)"),
    (r"\bschtasks(\.exe)?\s+/(run|delete|create|change|end)\b|\b(Register|Unregister|Start|Stop|Enable|Disable|Set)-ScheduledTask\b",
     "Scheduled-task control can launch SYSTEM daemons and swarms; the owner runs these in a reviewed Administrator series"),
    (r"start_pipeline\.bat|cochem_startup\.vbs|\bpythonw(\.exe)?\s+(-m\s+cochem|src[\\/]cochem)|-m\s+cochem\.(dsp\.worker_daemon|warden\.mcp_server|knowledge\.server|dsp\.toolkit)|watchdog_sre\.py|cochem_warden_oracle\.py|cochem_master_loop|task_work_loop\.py|cochem_ha_daemon_watchdog|hardware_guard\.py\s",
     "Legacy agentic swarm daemons (v4.1.x/v4.2.0) caused earlier spawn storms and BSODs; never start them from an agent"),
    (r"(-m\s+cochem_pipeline|\bcochem-pipeline(\.exe)?)\s+(daemon|provision-execution)\b|(-m\s+cochem_supervisor|\bcochem-supervisor(\.exe)?)\s+(daemon|once|recover|request-update|resume)\b",
     "Starting the live 4.2.7 controller/warden/supervisor is a reviewed Administrator action, not an agent action"),
    (r"\b(Stop|Restart|Start|Set)-Service\b|\bsc(\.exe)?\s+(stop|start|delete|config)\b|\bnet(\.exe)?\s+(stop|start)\b",
     "Service control is owner-only"),
    (r"\bStop-Process\s+(-Name|-ProcessName)\b|\btaskkill(\.exe)?\s" + _SEG + r"(/IM\b|/F\s+/T\b)|\bpkill\b|\bkillall\b",
     "Killing processes by image name hits other agents, GUIs and daemons; kill a specific PID you own instead"),
    (r"\bStart-Process\b" + _SEG + r"-Verb\s+RunAs|\brunas(\.exe)?\s|\bgsudo\b|(^|[\s;&|])sudo\s",
     "Elevation is owner-only; prepare the script and hand it to the owner"),
    (r"\bbcdedit\b|\breg(\.exe)?\s+(add|delete)\s+\"?HKLM|\b(Set|New|Remove)-ItemProperty\b" + _SEG + r"HKLM:|\bDISM(\.exe)?\s|\bsfc(\.exe)?\s|\bwinget\s+(install|upgrade|uninstall)\b|\bchoco\s+(install|upgrade|uninstall)\b|\bmsiexec\b",
     "System configuration and software installation are owner-only"),
    (r"(^|[\s&|;(])(>|>>|tee)\s*\"?" + r"[^\s\"&|;]*" + _GUARD_FILES
     + r"|\b(Set-Content|Out-File|Add-Content)\b" + _SEG + _GUARD_FILES
     + r"|\b(cp|mv|copy|move|robocopy|xcopy|rm|del|erase|Copy-Item|Move-Item|Remove-Item|rename|ren|Rename-Item|git\s+checkout|git\s+restore)\b" + _SEG + r"(host_guard\.py|[\\/]\.claude[\\/]settings(\.local)?\.json|[\\/]\.claude[\\/]hooks\b)",
     "Writing, copying over or removing WSL/Docker/startup/guard configuration from a shell is owner-only"),
    (r"\bpytest\b" + _SEG + r"\s-n\s*(auto|[5-9]\b|\d{2,})|\bxargs\b" + _SEG + r"\s-P\s*([5-9]\b|\d{2,})|-ThrottleLimit\s+([5-9]\b|\d{2,})|\bparallel\s+-j\s*([5-9]\b|\d{2,})",
     "More than four parallel heavy processes is a spawn-storm risk on this host; use at most 4"),
    (r"\b(claude|codex|agy|gemini)(\.exe)?\s" + _SEG + r"(\s-p\s|--print\b|\sexec\b|--yolo\b|--dangerously-skip-permissions\b)",
     "Spawning additional headless agent CLIs from an agent is a swarm risk; the owner starts agents"),
]

PROTECTED_PATH_RULES: list[tuple[str, str]] = [
    (r"/\.wslconfig$", "WSL memory/CPU configuration is owner-only"),
    (r"/AppData/Roaming/Docker/settings(-store)?\.json$", "Docker Desktop settings are owner-only"),
    (r"/Start Menu/Programs/Startup/", "Startup-folder launchers are owner-only"),
    (r"^[a-z]:/Windows/", "Windows system files are off-limits"),
    (r"^[a-z]:/Program Files( \(x86\))?/", "Program Files (including the protected CoChem runtime) needs the reviewed Administrator series"),
    (r"^[a-z]:/ProgramData/CoChemPipeline427/", "Production pipeline state is owner-only"),
    (r"/\.claude/hooks/|/\.claude/settings(\.local)?\.json$", "The host guard hooks and the settings that wire them may only be changed by the owner"),
    (r"/__agentic/v4\.[0-9.]+/start_pipeline\.bat$|/cochem_startup\.vbs$", "Swarm launchers are owner-only"),
]


def deny(reason: str, tool: str, detail: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as stream:
            stream.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} DENY {tool}: {detail[:400]!r} :: {reason}\n")
    except OSError:
        pass
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "CoChem host guard blocked this: " + reason + ". This host crashed on 2026-10-09 under agent load; "
                "host lifecycle, swarm daemons, elevation and >4-way parallelism are owner-only. "
                "Explain what you need and let the owner run it. (If the command was denied only because "
                "its text mentions a blocked pattern, use the Write/Edit/Read tools for that file.)"),
        }
    }))


def main() -> int:
    if os.path.exists(OFF_SWITCH):
        return 0
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    tool = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input") or {}
    if tool in {"Bash", "PowerShell"}:
        command = str(tool_input.get("command", ""))
        for pattern, reason in COMMAND_RULES:
            if re.search(pattern, command, flags=re.IGNORECASE | re.MULTILINE):
                deny(reason, tool, command)
                return 0
    elif tool in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        normalized = path.replace("\\", "/")
        for pattern, reason in PROTECTED_PATH_RULES:
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                deny(reason, tool, path)
                return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
