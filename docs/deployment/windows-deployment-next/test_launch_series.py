"""Static and regex checks for RUN_427_LAUNCH_SERIES.ps1 (never executes the series)."""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
SCRIPT = ROOT / 'RUN_427_LAUNCH_SERIES.ps1'
TEXT = SCRIPT.read_text(encoding='utf-8')


def ps(body):
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', body], capture_output=True, text=True, timeout=90)


def test_parses_and_declares_only_the_expected_functions():
    result = ps(f"$e=$null;$t=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('{SCRIPT}',[ref]$t,[ref]$e);"
                "@{errors=$e.Count;functions=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)|ForEach-Object Name)}|ConvertTo-Json -Compress")
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['errors'] == 0 and sorted(value['functions']) == sorted([
        'Say', 'Stop-Series', 'Invoke-Native', 'Test-PackageIndex', 'Invoke-Reviewed', 'Get-JsonTail', 'Get-LastLine', 'Test-Elapsed', 'Get-ListenerCount', 'Get-LegacyProcesses',
        'Assert-OwnerShell', 'Invoke-Stage0', 'Invoke-Stage1', 'Invoke-Stage2', 'Invoke-Stage3And4', 'Invoke-Stage5', 'Invoke-Stage6', 'Invoke-Series'])
    assert TEXT.rstrip().endswith('Invoke-Series'), 'the main block is a single call so the harness can load the functions without running it'


def test_legacy_removal_moves_and_never_deletes():
    assert 'Remove-Item' not in TEXT, 'the series archives legacy material; it never deletes'
    assert TEXT.count('Unregister-ScheduledTask') == 1 and 'Unregister-ScheduledTask -TaskName $name -Confirm:$false' in TEXT
    legacy = re.search(r"\$legacyTasks=@\((.*?)\)\n", TEXT).group(1)
    names = re.findall(r"'([^']+)'", legacy)
    assert names == ['CoChemHostWarden_V412', 'CoChem V4.1.2 Swarm',
                     'CoChem-Fixture-TaskAcl-20261008-bbd9bf8061764e6ba8cdefa47fb6a149-create18',
                     'CoChem-Fixture-TaskAcl-20261008-bbd9bf8061764e6ba8cdefa47fb6a149-create2']
    assert not any(name.startswith('CoChem-4.2.7') or 'RAMDisk' in name or 'Backup' in name for name in names)
    trees = re.findall(r"'(D:\\__CoChem\\__agentic\\[^']+)'", TEXT)
    assert sorted(set(trees)) == ['D:\\__CoChem\\__agentic\\v4.1.2', 'D:\\__CoChem\\__agentic\\v4.2.0']
    assert 'Move-Item -LiteralPath $tree' in TEXT and 'Move-Item -LiteralPath $script:legacyLauncher' in TEXT


def test_reviewed_scripts_are_invoked_with_the_documented_arguments():
    assert "@('-Manifest',$script:manifest,'-ManifestSha256',$manifestHash,'-Apply')" in TEXT
    assert "@('-Attempt',$script:Attempt)" in TEXT and "@('-Apply','-Start','-Attempt',$script:Attempt)" in TEXT
    assert TEXT.index("'-Apply','-Start'") > TEXT.index("@($planJson.holds).Count"), 'the switch runs only after the zero-hold plan'
    assert "FRESH_STOPPED_RUNTIME_READY" in TEXT and "WARDEN_R4_RUNNING_HEALTH_VERIFIED" in TEXT
    assert 'Stop-ScheduledTask' in TEXT and 'Start-ScheduledTask' not in TEXT and 'Register-ScheduledTask' not in TEXT.replace('Unregister-ScheduledTask', '')
    assert 'Add-MpPreference' not in TEXT and 'Set-MpPreference' not in TEXT, 'Defender exclusions are checked, never changed'
    assert 'Is64BitProcess' in TEXT, 'a 32-bit shell must be refused before the removal stage'
    assert TEXT.index("read-only plan (installer preconditions") < TEXT.index('Stage 1: legacy'), 'the installer preflight runs before any removal'
    assert TEXT.index("Stop-Series ('The r4 controller did not answer /health as SYSTEM") < TEXT.index("'DONE: the 4.2.7 pipeline"), 'health is a gate before DONE'
    assert TEXT.count("'CmdletizationQuery_NotFound*'") == 1 and 'Get-ListenerCount 47824' in TEXT and 'Get-ListenerCount 47821' in TEXT, 'both port probes go through the one fail-closed helper'


def test_docker_check_mirrors_the_controller_preflight():
    assert "@('info','--format','{{json .}}')" in TEXT, 'docker info is read as JSON, as containers.py does'
    assert "{{.CpuCfsQuota}}" not in TEXT and "{{.CPUCfsQuota}}" not in TEXT, 'no Go-template field access for docker info'
    fields = re.search(r"\$dockerFields=@\((.*?)\)\n", TEXT).group(1)
    assert re.findall(r"'([^']+)'", fields) == ['OSType', 'MemoryLimit', 'SwapLimit', 'CpuCfsQuota', 'PidsLimit'], 'the JSON keys the daemon preflight reads'
    assert "'{{.Id}} {{.Os}}'" in TEXT


@pytest.mark.parametrize('image,expected', [
    (r'D:\__CoChem\__agentic\v4.1.2\.venv\Scripts\pythonw.exe', True),
    (r'D:\__CoChem\__agentic\v4.2.0\.venv\Scripts\python.exe', True),
    (r'D:\__CoChem\__agentic\.venv\Scripts\python.exe', False),
    (r'D:\__CoChem\__agentic\setup\tool.exe', False),
    (r'C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe', False),
])
def test_process_sweep_image_pattern_is_limited_to_the_two_trees(image, expected):
    pattern = re.search(r"\$legacyImagePattern='([^']+)'", TEXT).group(1)
    result = ps(f"$p='{pattern}';@{{m=[bool]('{image}' -match $p)}}|ConvertTo-Json -Compress")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['m'] is expected, image


LEGACY_COMMANDS = [
    r'C:\WINDOWS\System32\cmd.exe /d /s /c "set "PYTHONPATH=D:\__CoChem\__agentic\v4.1.2\src;..." && "C:\Python314\python.exe" -m cochem.warden.mcp_server --transport http --port 47821',
    r'C:\Python314\python.exe -m cochem.warden.mcp_server --transport http --port 47821',
    r'D:\__CoChem\__agentic\v4.1.2\start_pipeline.bat',
    r'C:\Python314\python.exe D:\__CoChem\__agentic\v4.2.0\auto_architect_mcp.py',
    r'C:\Python314\python.exe D:\__agentic\mcp\cochem_kanban_mcp.py',
    r'pythonw -m cochem.watchdog_sre',
]
PROTECTED_COMMANDS = [
    r'"C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\Scripts\python.exe" -I -B -m cochem_pipeline daemon --config "C:\Program Files\CoChem\WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json" --queue-launch-output "C:\ProgramData\CoChemPipeline427\private\queue-retarget-20261010-r4-v1"',
    r'"C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe" -I -S -B -X "pycache_prefix=..." "C:\Program Files\CoChem\ResourceObservation4.2.7-windows-20261008-r3-v4\package\observe_resources.py" --run-observer',
    r'"C:\Program Files\CoChem\Supervisor4.2.7-windows-20261007-staging-v1\.venv\Scripts\python.exe" -I -B "C:\Program Files\CoChem\SupervisorObservation4.2.7-windows-20261007-r3-v1\held-supervisor-observation-r3-v1.py" --observe',
    r'"C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r3\.venv\Scripts\python.exe" -I -B -m cochem_pipeline mcp --client-config C:\Users\ansac\CoChem427\pipeline-client-r3.json',
    r'D:\Gdrive\__CoChem\GitHub-Repo\Antigravity_additions\.venv-mcp\Scripts\python.exe -m cochem_mcp --provider codex --config D:\Gdrive\__CoChem\GitHub-Repo\Antigravity_additions\config\bridge.local.json',
    r'"C:\Program Files\Docker\Docker\Docker Desktop.exe"',
    r'C:\Python314\python.exe C:\Users\ansac\.gemini\config\plugins\antigravity-rl\rl_mcp_server.py',
]


@pytest.mark.parametrize('command', LEGACY_COMMANDS + PROTECTED_COMMANDS)
def test_process_sweep_pattern_matches_only_legacy_commands(command):
    pattern = re.search(r"\$legacyProcessPattern='([^']+)'", TEXT).group(1)
    escaped = command.replace("'", "''")
    result = ps(f"$p='{pattern}';@{{m=[bool]('{escaped}' -match $p)}}|ConvertTo-Json -Compress")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['m'] is (command in LEGACY_COMMANDS), command
