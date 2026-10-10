"""CoChem host guard (v3): a Claude Code PreToolUse hook that blocks host-lifecycle actions.

Why this exists: AETHERDESK bug-checked on 2026-10-09 (0x21 QUOTA_UNDERFLOW) while an agent
session was open (idle at that moment). The host runs a pre-release Windows build with
WSL2/Docker, Hyper-V and an ImDisk RAM disk, so VM/daemon/service churn and process storms
can take the machine down, and earlier BSODs came from agentic spawn storms. This hook
denies commands that start, stop or restart host infrastructure, launch the legacy swarm
daemons or the live 4.2.7 controller, elevate, kill by image name, fan out more than four
heavy processes, spawn headless agent CLIs, or touch the guard's own files.

Coverage: Claude Code's Bash, PowerShell, Write, Edit, MultiEdit, NotebookEdit tools and
every MCP tool (matcher "mcp__.*"), where command-like and path-like inputs are inspected.
It is a guard rail, not a sandbox. It fails CLOSED: an internal error or an oversized
command is denied. The OWNER disables it by creating
%USERPROFILE%\\.claude\\cochem-host-guard.off (agents never create or mention it).
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
MAX_COMMAND_CHARS = 20000

_SEG = r"[^\n&|;]*"            # one shell segment (stops at && || | ; newline)
_LINE = r"[^\n]*"              # one line, for rules where ; or | are part of the attack
_Q = r"[\"']?"                 # optional closing quote after an executable name
_EXE = r"(\.exe|\.com|\.cmd|\.bat|\.ps1)?"
_SETTINGS = r"(^|[\s\"'=\\/])\.claude[\\/]settings(\.local)?\.json"
_HOOKS_DIR = r"(^|[\s\"'=\\/])\.claude[\\/]hooks\b"
_OFF_SWITCH = r"cochem-host-guard\.off"
_GUARD_FILES = (r"(\.wslconfig|settings-store\.json|host_guard\.py|" + _SETTINGS + r"|" + _HOOKS_DIR
                + r"|Startup[\\/]|" + _OFF_SWITCH + r")")
_HOST_EXES = (r"(wsl|docker|docker-compose|schtasks|taskkill|imdisk|shutdown|bcdedit|runas|sudo|gsudo|"
              r"diskpart|mountvol|net|net1|sc|reg|dism|sfc|winget|choco|msiexec|psexec|wusa)")
# Command position: start of a segment, or after a launcher prefix.
_CMDPOS = (r"(^|[;&|(]\s*|&\s*[\"']?|\b(timeout\s+\S+|nohup|start(\s+\"\")?(\s+/B)?|cmd(\.exe)?\s+/[ck]|"
           r"powershell(\.exe)?\s+(-\S+\s+)*-c(ommand)?|pwsh(\.exe)?\s+(-\S+\s+)*-c(ommand)?)\s+)")

# (pattern, reason). Matched case-insensitively against the whole command text.
COMMAND_RULES: list[tuple[str, str]] = [
    (r"\bwsl" + _EXE + _Q + r"\s+(" + _SEG + r"\s)?(--shutdown|--terminate|-t|--unregister|--import|--export|--install|--update|--mount|--unmount)(\s|$)",
     "WSL lifecycle (shutdown/terminate/unregister/import/mount) tears down or reshapes the WSL2 VM"),
    (r"\bdocker(-compose)?" + _EXE + _Q + r"\s+(" + _SEG + r"\s)?(compose\s+)?(down|up|restart|stop|kill|rm|rmi|prune|desktop)\b"
     r"|\bdocker" + _EXE + _Q + r"\s+(system|volume|image|builder|container|network)\s+(prune|rm|stop|kill)\b"
     r"|\bdocker" + _EXE + _Q + r"\s+context\s+(use|rm)\b",
     "Docker lifecycle operations restart or tear down the Docker/WSL2 VM or its containers"),
    (r"\b(?!Get-VM)[A-Za-z]+-VM[A-Za-z]*\b",
     "Hyper-V VM control (every *-VM* cmdlet except Get-VM*) is owner-only on this host"),
    (r"\b(Restart|Stop)-Computer\b|\bshutdown" + _EXE + _Q + r"\s+" + _SEG + r"[/-][rsfghp](\s|$)|\blogoff\b",
     "Power actions are owner-only"),
    (r"\bimdisk" + _EXE + r"\b|\bdiskpart\b|\bmountvol" + _EXE + r"\b" + _SEG + r"/[dp]\b|\b(Mount|Dismount)-DiskImage\b"
     r"|\b(Remove|Clear|Set|Initialize)-(Partition|Disk)\b|\bNew-VirtualDisk\b|\b(Format|Set)-Volume\b"
     r"|\bfsutil\s+volume\s+dismount|\bformat(\.com)?" + _Q + r"\s+[a-z]:",
     "RAM disk / volume operations are owner-only (R: is the pipeline's ImDisk volume)"),
    (r"\bschtasks" + _EXE + _Q + r"\s+" + _SEG + r"[/-](run|delete|create|change|end)\b"
     r"|\b(Register|Unregister|Start|Stop|Enable|Disable|Set|Export)-ScheduledTask\b"
     r"|\bSchedule\.Service\b" + _LINE + r"\.(RegisterTask|RegisterTaskDefinition|DeleteTask|DeleteFolder|Run|Stop)\(",
     "Scheduled-task control can launch SYSTEM daemons and swarms; the owner runs these in a reviewed Administrator series"),
    (r"start_pipeline\.bat|cochem_startup\.vbs|\bpythonw" + _EXE + _Q + r"\s+(" + _SEG + r"\s)?(-m\s+cochem|src[\\/]cochem)"
     r"|-m\s+cochem\.(dsp\.worker_daemon|warden\.mcp_server|knowledge\.server|dsp\.toolkit|watchdog)"
     r"|watchdog_sre\.py|cochem_warden_oracle\.py|cochem_master_loop|task_work_loop\.py|cochem_ha_daemon_watchdog"
     r"|__agentic[\\/]" + _SEG + r"(hardware_guard\.py|safe_chat_cli|\.(ps1|bat|cmd|vbs)\b)",
     "Legacy agentic swarm daemons and launchers (v4.1.x/v4.2.0) caused earlier spawn storms and BSODs; never start them from an agent"),
    (r"(-m\s+cochem_pipeline|\bcochem-pipeline" + _EXE + r")\s+(daemon|provision-execution)\b"
     r"|(-m\s+cochem_supervisor|\bcochem-supervisor" + _EXE + r")\s+(daemon|once|recover|request-update|resume)\b"
     r"|-m\s+cochem_pipeline\.(deployment|ramdisk|windows|queue_launch|runtime)\b"
     r"|\b(install|commission|run-pipeline|run-post|register|resume|recover|continue|accept)-[\w.-]*\.ps1\b" + _LINE + r"\s-Apply\b",
     "Starting, provisioning or switching the live 4.2.7 controller/warden/supervisor is a reviewed Administrator action, not an agent action"),
    (r"\b(Stop|Restart|Start|Set|Suspend|Resume|New|Remove)-Service\b|\b(spsv|sasv)\b"
     r"|\bsc" + _EXE + _Q + r"\s+(\\\\\S+\s+)?(stop|start|delete|config|create|pause|continue|failure)\b"
     r"|\bnet1?" + _EXE + _Q + r"\s+(stop|start|pause|continue)\s+\S",
     "Service control is owner-only"),
    (r"\bStop-Process\b" + _SEG + r"\s-(Name|ProcessName|InputObject)\b"
     r"|\b(Get-Process|gps)\b[^\n|]*\|\s*[^\n|]*\b(Stop-Process|kill|spps)\b"
     r"|\btaskkill" + _EXE + _Q + r"\s" + _SEG + r"([/-]IM\b|[/-]F\s+[/-]T\b|[/-]T\b)"
     r"|(^|[\s;&|(])pkill\s|\bkillall\b|\bwmic\s+process\b" + _SEG + r"\b(delete|terminate)\b",
     "Killing processes by image name or tree hits other agents, GUIs and daemons; kill a specific PID you own instead"),
    (r"\bStart-Process\b" + _LINE + r"-Verb\s*[:=]?\s*[\"']?RunAs|\brunas" + _EXE + _Q + r"\s"
     r"|(^|[\s;&|(\"'])g?sudo(\.exe)?[\"']?\s|\bpsexec" + _EXE + r"\b" + _SEG + r"\s-s\b|\belevate(\.exe)?\s",
     "Elevation is owner-only; prepare the script and hand it to the owner"),
    (r"\bbcdedit\b|\breg" + _EXE + _Q + r"\s+(add|delete|import|restore|load|unload|copy)\b"
     r"|\b(Set|New|Remove|Rename|Clear|Copy|Move)-Item(Property)?\b" + _LINE + r"(HKLM:|HKEY_LOCAL_MACHINE|Registry::HKEY_LOCAL)"
     r"|\bDISM" + _EXE + r"\s|\bsfc" + _EXE + r"\s|\bwinget" + _EXE + r"\s+(install|upgrade|uninstall|settings)\b"
     r"|\bchoco" + _EXE + r"\s+(install|upgrade|uninstall)\b|\bmsiexec\b|\bwusa\b|\bSet-ExecutionPolicy\b" + _SEG + r"LocalMachine",
     "System configuration and software installation are owner-only"),
    (r"(^|[\s&|;(])\d?>{1,2}\s*[\"']?[^\s\"'&|;]*" + _GUARD_FILES
     + r"|\b(tee|Set-Content|Out-File|Add-Content|Clear-Content|sc|ac|New-Item|ni|touch|truncate|sed\s+-[a-zA-Z]*i|perl\s+-[a-zA-Z]*i)\b" + _SEG + _GUARD_FILES
     + r"|\b(cp|mv|copy|move|robocopy|xcopy|rm|del|erase|rd|rmdir|Copy-Item|Move-Item|Remove-Item|rename|ren|Rename-Item|cpi|mi|ri|rni)\b" + _SEG + _GUARD_FILES
     + r"|\bgit\s+(-C\s+\S+\s+)?(checkout|restore|clean|reset|rm|mv|stash)\b" + _SEG + r"(host_guard\.py|" + _SETTINGS + r"|" + _HOOKS_DIR + r")"
     + r"|\bfsutil\s+file\s+createnew\b" + _SEG + _GUARD_FILES
     + r"|" + _OFF_SWITCH,
     "Writing, copying over or removing WSL/Docker/startup/guard configuration (or the guard off-switch) from a shell is owner-only"),
    (r"\bpytest\b" + _SEG + r"(\s-n\s*=?\s*|--numprocesses[\s=]+)(auto|0|[5-9]|\d{2,})\b|\bpytest\b" + _SEG + r"--dist[\s=]"
     r"|\bxargs\b" + _SEG + r"(\s-P\s*|--max-procs[\s=]+)(0|[5-9]|\d{2,})\b|-ThrottleLimit\s*[:=]?\s*(0|[5-9]|\d{2,})\b"
     r"|\bparallel\b" + _SEG + r"(\s-j|--jobs)[\s=]*(0|[5-9]|\d{2,})\b|\bmake\b" + _SEG + r"\s-j\s*(\d{2,}|[5-9])?(\s|$)",
     "More than four parallel heavy processes is a spawn-storm risk on this host; use at most 4"),
    (_CMDPOS + r"([A-Za-z]:[\\/][^\s\"']*[\\/])?(npx\s+(-y\s+|--yes\s+)?(@anthropic-ai/claude-code|@openai/codex|@google/gemini-cli)|claude|codex|agy|gemini)"
     + _EXE + _Q + r"\s+(" + _SEG + r"\s)?(-p|--print|--prompt|exec|-q|--quiet|--full-auto|-y|--yolo|--dangerously-skip-permissions|--approval-mode|--permission-mode|-a\s+never)(\s|$)",
     "Spawning additional headless agent CLIs from an agent is a swarm risk; the owner starts agents"),
    (r"\b(Start-Process|saps|Invoke-Expression|iex|Invoke-Command|icm|Invoke-Item|ii|cmd(\.exe)?\s+/[ck])\b" + _LINE + r"(^|[\s\"'\\/])" + _HOST_EXES + r"(\.exe)?\b",
     "Indirect launch (Start-Process/Invoke-Expression/cmd /c) of a host-lifecycle executable is owner-only"),
]

PROTECTED_PATH_RULES: list[tuple[str, str]] = [
    (r"/\.wslconfig$", "WSL memory/CPU configuration is owner-only"),
    (r"/AppData/Roaming/Docker/settings(-store)?\.json$", "Docker Desktop settings are owner-only"),
    (r"/Start Menu/Programs/Startup/", "Startup-folder launchers are owner-only"),
    (r"^[a-z]:/Windows/", "Windows system files are off-limits"),
    (r"^[a-z]:/Program Files( \(x86\))?/", "Program Files (including the protected CoChem runtime) needs the reviewed Administrator series"),
    (r"^[a-z]:/ProgramData/CoChemPipeline427/", "Production pipeline state is owner-only"),
    (r"/\.claude/hooks/|/\.claude/settings(\.local)?\.json$|/" + _OFF_SWITCH + r"$",
     "The host guard hooks, the settings that wire them and the guard off-switch may only be changed by the owner"),
    (r"/__agentic/v4\.[0-9.]+/start_pipeline\.bat$|/cochem_startup\.vbs$", "Swarm launchers are owner-only"),
]

_COMMAND_KEYS = {"command", "cmd", "script", "args", "arguments", "argv", "input", "text", "code", "line", "shell", "commandline"}
_PATH_KEYS = {"path", "file_path", "filepath", "notebook_path", "source", "destination", "cwd", "directory", "dir", "target",
              "old_path", "new_path", "from", "to", "root"}

_COMPILED = [(re.compile(p, re.IGNORECASE | re.MULTILINE), r) for p, r in COMMAND_RULES]
_COMPILED_PATHS = [(re.compile(p, re.IGNORECASE), r) for p, r in PROTECTED_PATH_RULES]
_PARALLEL = re.compile(r"-Parallel\b", re.IGNORECASE)
_THROTTLE_OK = re.compile(r"-ThrottleLimit\s*[:=]?\s*[1-4]\b", re.IGNORECASE)


def _normalize_path(path: str) -> str:
    text = path.strip().strip("\"'")
    if text.startswith("\\\\?\\"):
        text = text[4:]
    unc = re.match(r"^\\\\(localhost|127\.0\.0\.1|\.)\\([a-zA-Z])\$(.*)$", text)
    if unc:
        text = unc.group(2) + ":" + unc.group(3)
    text = text.replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    try:
        text = os.path.normpath(text).replace("\\", "/")
    except (TypeError, ValueError):
        pass
    if re.match(r"^[a-zA-Z]:/", text):
        text = text[0].lower() + text[1:]
    return text


def check_command(command: str) -> str | None:
    if len(command) > MAX_COMMAND_CHARS:
        return "Command text is too long for the guard to inspect; split it"
    for pattern, reason in _COMPILED:
        if pattern.search(command):
            return reason
    if _PARALLEL.search(command) and not _THROTTLE_OK.search(command):
        return "ForEach-Object -Parallel defaults to 5 workers; use -ThrottleLimit 4 or less"
    return None


def check_path(path: str) -> str | None:
    normalized = _normalize_path(path)
    for pattern, reason in _COMPILED_PATHS:
        if pattern.search(normalized):
            return reason
    return None


def _walk_strings(value, key=None, depth=0):
    if depth > 8:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk_strings(v, str(k).lower(), depth + 1)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_strings(v, key, depth + 1)
    elif isinstance(value, str):
        yield key, value


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
                "CoChem host guard blocked this: " + reason + ". This host crashed on 2026-10-09 with agents in session; "
                "host lifecycle, swarm daemons, elevation and >4-way parallelism are owner-only. "
                "Explain what you need and let the owner run it. (If the command was denied only because "
                "its text mentions a blocked pattern, use the Write/Edit/Read tools for that file.)"),
        }
    }))


def decide(payload: dict) -> tuple[str | None, str]:
    tool = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return "Unexpected tool input shape", tool
    if tool in {"Bash", "PowerShell"}:
        return check_command(str(tool_input.get("command", ""))), tool
    if tool in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
        return check_path(str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")), tool
    if tool.startswith("mcp__"):
        for key, text in _walk_strings(tool_input):
            if key in _PATH_KEYS:
                reason = check_path(text)
                if reason:
                    return reason, tool
            if key in _COMMAND_KEYS:
                reason = check_command(text)
                if reason:
                    return reason, tool
        return None, tool
    return None, tool


def main() -> int:
    if os.path.exists(OFF_SWITCH):
        return 0
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("hook payload is not an object")
        reason, tool = decide(payload)
        if reason:
            detail = json.dumps(payload.get("tool_input"), default=str)[:400]
            deny(reason, tool, detail)
        return 0
    except Exception as exc:  # fail closed: the guard must never silently allow on error
        try:
            deny("guard internal error (" + type(exc).__name__ + ": " + str(exc)[:120] + ")", "unknown", "")
            return 0
        except Exception:
            sys.stderr.write("CoChem host guard failed closed: " + repr(exc) + "\n")
            return 2


if __name__ == "__main__":
    sys.exit(main())
