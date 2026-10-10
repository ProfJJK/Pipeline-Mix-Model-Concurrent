"""Behavioural tests for the Claude Code host guard hook (.claude/hooks/cochem_host_guard.py).

Each case pipes a PreToolUse payload to the real hook in a fresh ``python -I`` process and
checks the permission decision. The hook never executes the command it inspects, so these
tests start nothing on the host. Set COCHEM_HOST_GUARD to test another copy of the hook.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = Path(os.environ.get("COCHEM_HOST_GUARD") or ROOT / ".claude" / "hooks" / "cochem_host_guard.py")
pytestmark = pytest.mark.skipif(not GUARD.exists(), reason="host guard hook is not installed in this checkout")


def run_guard(tool: str, tool_input, raw: str | None = None) -> tuple[bool, str, int]:
    payload = raw if raw is not None else json.dumps({"tool_name": tool, "tool_input": tool_input})
    env = dict(os.environ, HOME=str(Path(os.environ.get("TEMP", ".")) / "guard-test-home"))
    env["USERPROFILE"] = env["HOME"]
    proc = subprocess.run([sys.executable, "-I", "-X", "utf8", str(GUARD)], input=payload, capture_output=True,
                          text=True, timeout=30, env=env)
    denied = '"permissionDecision": "deny"' in proc.stdout
    return denied, proc.stdout + proc.stderr, proc.returncode


ALLOWED_COMMANDS = [
    "ls",
    "git status && git log --oneline -5",
    "cd repo && timeout 600 .venv/Scripts/python.exe -m pytest pipeline_tests -q -p no:cacheprovider",
    "python -m pytest -n 4 -q",
    "python -m pytest pipeline_tests/test_hardware_guard.py -q",
    "sed -n 1,40p src/cochem_pipeline/hardware_guard.py",
    "python -m cochem_pipeline mcp --client-config C:/Users/ansac/CoChem427/pipeline-client-r3.json",
    "python -m cochem_pipeline status --client-config x.json --workflow-id abc",
    "python -m cochem_supervisor status --config x.json",
    "taskkill /PID 1234",
    "docker ps && docker inspect abc && docker logs abc",
    "docker run --rm alpine echo hi",
    "uv sync --frozen --extra dev",
    "printf 'x' > D:/x/CLAUDE.md && ls -la D:/x/.claude/settings.json D:/x/.claude/hooks/cochem_host_guard.py",
    "cat .claude/settings.json; python .claude/hooks/cochem_host_guard.py < in.json",
    "cat README.md > notes.txt && ls",
    "git log --oneline -3 | tee out.txt",
    "ls -la ~/.claude",
    "grep -rn Startup docs/ | head",
    "grep -rn gemini src/ | head",
    "git add .claude/settings.json .claude/hooks/cochem_host_guard.py AGENTS.md && git commit -m x",
    "Get-VM | Select-Object Name, State",
    "Get-Process python | Select-Object Id, WorkingSet64",
    "Get-Service | Where-Object Status -eq Running",
    "schtasks /query /tn CoChem-4.2.7-Warden /fo LIST",
    "Get-ScheduledTask | Where-Object TaskName -like 'CoChem*'",
    "net use",
    "dotnet build",
    "powershell.exe -NoProfile -File install-stopped-runtime-r4.ps1 -Manifest m.json -ManifestSha256 abc",
    "ForEach-Object -Parallel { $_ } -ThrottleLimit 4",
    "1..3 | ForEach-Object -Parallel { $_ } -ThrottleLimit 2",
    "make -j4",
    "xargs -P 4 -n1 echo",
]

DENIED_COMMANDS = [
    "wsl --shutdown",
    "wsl.exe --shutdown",
    '& "C:\\Windows\\System32\\wsl.exe" --shutdown',
    "wsl -t Ubuntu",
    "wsl -d Ubuntu --unregister",
    "docker compose down",
    "docker-compose down",
    "docker compose up -d",
    "docker stop abc",
    "docker container prune -f",
    "docker system prune -af",
    "docker rm -f abc",
    "Stop-VM -Name CoChem-Golden-Baker -Force",
    "Set-VMMemory -VMName CoChem-Golden-Baker -StartupBytes 8GB",
    "Restore-VMSnapshot -VMName x -Name y",
    "Remove-VMSwitch -Name CoChem-Quarantine-Switch",
    "Restart-Computer -Force",
    "shutdown /r /t 0",
    "shutdown -r -t 0",
    "shutdown /p",
    'schtasks /run /tn "CoChem V4.1.2 Swarm"',
    "schtasks -run -tn x",
    "Start-ScheduledTask -TaskName CoChemHostWarden_V412",
    "Register-ScheduledTask -TaskName x -Action $a",
    "cmd /c D:\\__CoChem\\__agentic\\v4.2.0\\start_pipeline.bat",
    "powershell -File D:\\__CoChem\\__agentic\\v4.2.0\\.scripts\\provision.ps1",
    "start /B pythonw.exe -m cochem.dsp.worker_daemon",
    "python -m cochem_pipeline daemon --config x.json",
    "python -m cochem_pipeline provision-execution --config x.json",
    "python -m cochem_supervisor daemon --config x.json",
    "powershell.exe -NoProfile -File install-stopped-runtime-r4.ps1 -Manifest m.json -ManifestSha256 abc -Apply",
    "Stop-Service -Name Spooler",
    "net stop ImDskSvc",
    "sc stop ImDskSvc",
    "python -m pytest -n auto",
    "python -m pytest -n 12 -q",
    "python -m pytest --numprocesses=8",
    "xargs -P 8 -n1 echo",
    "ForEach-Object -Parallel { $_ }",
    "ForEach-Object -Parallel { $_ } -ThrottleLimit 8",
    "taskkill /IM python.exe /F",
    "taskkill -im python.exe -f",
    "taskkill /F /T /PID 1234",
    "Stop-Process -Name python -Force",
    "Stop-Process -Force -Name python",
    "Get-Process python | Stop-Process -Force",
    "gps node | kill",
    "pkill -f python",
    "Start-Process pwsh -Verb RunAs -ArgumentList '-File x.ps1'",
    "Start-Process pwsh -ArgumentList '-File x.ps1' -Verb RunAs",
    "Start-Process -FilePath pwsh -Verb:RunAs",
    "sudo wsl --install",
    "sudo.exe whoami",
    '"sudo" whoami',
    "Start-Process wsl -ArgumentList '--shutdown'",
    "cmd /c wsl --shutdown",
    "Invoke-Expression 'wsl --shutdown'",
    "echo '[wsl2]' > C:/Users/ansac/.wslconfig",
    "echo x 2> C:/Users/ansac/.wslconfig",
    "cp mine.wslconfig ~/.wslconfig",
    "Copy-Item x.json $env:APPDATA\\Docker\\settings-store.json",
    "echo hi > ~/.claude/settings.json",
    "cp scratch/cochem_host_guard.py .claude/hooks/cochem_host_guard.py",
    "rm -f .claude/settings.json",
    "sed -i 's/deny/allow/' .claude/hooks/cochem_host_guard.py",
    "git checkout -- .claude/hooks/cochem_host_guard.py",
    "git -C D:/__CoChem/GitHub-Repo checkout .claude/settings.json",
    "Copy-Item x.json .claude\\settings.json -Force",
    "touch ~/.claude/cochem-host-guard.off",
    "New-Item -ItemType File C:\\Users\\ansac\\.claude\\cochem-host-guard.off",
    "echo > %USERPROFILE%\\.claude\\cochem-host-guard.off",
    "Set-ItemProperty -Path 'HKLM:\\SYSTEM\\x' -Name y -Value 1",
    "Set-ItemProperty -Path 'Registry::HKEY_LOCAL_MACHINE\\SOFTWARE\\x' -Name y -Value 1",
    "reg add HKLM\\SOFTWARE\\x /v y /d 1",
    "reg import evil.reg",
    "winget install Microsoft.WinDbg",
    'imdisk -a -s 8G -m R: -p "/fs:ntfs /q /y"',
    "diskpart /s script.txt",
    "mountvol R: /D",
    "Format-Volume -DriveLetter R",
    "claude -p 'do things' --dangerously-skip-permissions",
    "claude.cmd -p 'do things'",
    "npx -y @anthropic-ai/claude-code -p hi",
    "codex exec 'do things'",
    "codex --full-auto 'do things'",
    "gemini --yolo 'do things'",
    "cd x && claude -p hi",
    "timeout 60 claude -p hi",
    "x" * 25000,
]

ALLOWED_PATHS = [
    ("Edit", "D:\\__CoChem\\GitHub-Repo\\README.md"),
    ("Write", str(ROOT / "src" / "cochem_pipeline" / "resource_telemetry.py")),
    ("Write", "C:\\Users\\ansac\\AppData\\Local\\Temp\\claude\\x\\scratchpad\\notes.md"),
    ("Write", "C:\\Users\\ansac\\CoChem427\\stopped-runtime-r4-source\\README.md"),
]

DENIED_PATHS = [
    ("Write", "C:\\Users\\ansac\\.wslconfig"),
    ("Write", "C:/Users/ansac//.wslconfig"),
    ("Write", "\\\\?\\C:\\Users\\ansac\\.wslconfig"),
    ("Write", "\\\\localhost\\C$\\Users\\ansac\\.wslconfig"),
    ("Write", "C:\\Users\\ansac\\AppData\\Roaming\\Docker\\settings-store.json"),
    ("Write", "C:\\Program Files\\CoChem\\x.txt"),
    ("Write", "C:\\ProgramData\\CoChemPipeline427\\private\\x.db"),
    ("Edit", "D:\\__CoChem\\GitHub-Repo\\.claude\\hooks\\cochem_host_guard.py"),
    ("Write", "D:\\__CoChem\\GitHub-Repo\\.claude\\settings.json"),
    ("Write", "D:\\__CoChem\\GitHub-Repo\\.claude\\settings.local.json"),
    ("Write", "C:\\Users\\ansac\\.claude\\settings.json"),
    ("Write", "C:\\Users\\ansac\\.claude\\cochem-host-guard.off"),
    ("NotebookEdit", "C:\\Users\\ansac\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\x.ipynb"),
    ("Write", "D:\\__CoChem\\__agentic\\v4.2.0\\start_pipeline.bat"),
]

MCP_CASES = [
    ("mcp__plugin_desktop-commander_desktop-commander__start_process", {"command": "wsl --shutdown", "timeout_ms": 5000}, True),
    ("mcp__plugin_desktop-commander_desktop-commander__start_process", {"command": "git status", "timeout_ms": 5000}, False),
    ("mcp__plugin_desktop-commander_desktop-commander__write_file", {"path": "C:\\Users\\ansac\\.claude\\cochem-host-guard.off", "content": ""}, True),
    ("mcp__plugin_desktop-commander_desktop-commander__write_file", {"path": "D:\\__CoChem\\GitHub-Repo\\.claude\\hooks\\cochem_host_guard.py", "content": "x"}, True),
    ("mcp__plugin_desktop-commander_desktop-commander__write_file", {"path": "D:\\__CoChem\\GitHub-Repo\\notes.md", "content": "wsl --shutdown is bad"}, False),
    ("mcp__plugin_desktop-commander_desktop-commander__edit_block", {"file_path": "C:\\Users\\ansac\\.wslconfig", "old_string": "a", "new_string": "b"}, True),
    ("mcp__plugin_desktop-commander_desktop-commander__move_file", {"source": "x", "destination": "D:\\__CoChem\\GitHub-Repo\\.claude\\settings.json"}, True),
    ("mcp__plugin_desktop-commander_desktop-commander__interact_with_process", {"pid": 1, "input": "Stop-VM -Name x"}, True),
    ("mcp__terminal__run_in_terminal", {"command": "schtasks /run /tn x"}, True),
    ("mcp__terminal__run_in_terminal", {"command": "git log --oneline -3"}, False),
    ("mcp__cochem-pipeline__pipeline_health", {}, False),
    ("mcp__cochem-pipeline__pipeline_submit", {"objective": "Write a six-chapter SRS", "requirements": ["REQ-1"], "chapter_count": 6}, False),
]


@pytest.mark.parametrize("command", ALLOWED_COMMANDS, ids=lambda c: c[:60])
def test_ordinary_developer_commands_are_allowed(command):
    denied, output, code = run_guard("Bash", {"command": command})
    assert code == 0 and not denied, output


@pytest.mark.parametrize("command", DENIED_COMMANDS, ids=lambda c: c[:60])
def test_host_lifecycle_commands_are_denied(command):
    denied, output, code = run_guard("Bash", {"command": command})
    assert code == 0 and denied, output
    assert "CoChem host guard blocked this" in output


def test_powershell_tool_uses_the_same_rules():
    assert run_guard("PowerShell", {"command": "Stop-VM -Name x"})[0]
    assert not run_guard("PowerShell", {"command": "Get-ChildItem C:\\"})[0]


@pytest.mark.parametrize("tool,path", ALLOWED_PATHS, ids=lambda v: str(v)[-40:])
def test_ordinary_file_writes_are_allowed(tool, path):
    denied, output, code = run_guard(tool, {"file_path": path, "content": "x"})
    assert code == 0 and not denied, output


@pytest.mark.parametrize("tool,path", DENIED_PATHS, ids=lambda v: str(v)[-40:])
def test_protected_file_writes_are_denied(tool, path):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    denied, output, code = run_guard(tool, {key: path, "content": "x"})
    assert code == 0 and denied, output


@pytest.mark.parametrize("tool,tool_input,expect_denied", MCP_CASES, ids=lambda v: str(v)[-50:])
def test_mcp_tools_are_inspected_for_commands_and_paths(tool, tool_input, expect_denied):
    denied, output, code = run_guard(tool, tool_input)
    assert code == 0 and denied == expect_denied, output


def test_malformed_payloads_fail_closed():
    for raw in ("", "not json", "[1,2]", '{"tool_name": "Bash", "tool_input": "wsl --shutdown"}'):
        denied, output, code = run_guard("Bash", None, raw=raw)
        assert code == 0 and denied, (raw, output)


def test_denial_output_is_valid_hook_json():
    denied, output, code = run_guard("Bash", {"command": "wsl --shutdown"})
    decision = json.loads(output.strip().splitlines()[-1])["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse" and decision["permissionDecision"] == "deny"
    assert "WSL lifecycle" in decision["permissionDecisionReason"]
