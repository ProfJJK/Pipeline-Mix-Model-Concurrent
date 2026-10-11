"""Tests for ps_toplevel_smoke.py: the top-level plan-mode smoke runner, and its first use on the r5 cutover scripts.

Run only through the heavy-run lock, single process (AGENTS.md):
    PY -I serialize-heavy.py --timeout-minutes 120 --label <name> -- PY -I -B -m pytest -p no:cacheprovider -q test_ps_toplevel_smoke.py

Nothing here runs anything with -Apply (the runner refuses it before a process starts), reads a real task, process, port,
Program Files or ProgramData path, or changes the host: every host-touching command is a stub or is denied (see the module
docstring of ps_toplevel_smoke.py). The direct 'powershell.exe -File' runs used for the fidelity comparison execute only an
inert fixture written to a pytest temporary directory.

retarget-warden-r5.ps1 used to assign '' to the [ValidatePattern] parameter variables $script:SourceAttempt and
$script:StopAttempt (Invoke-RetargetR5Main), so every plan for a call without both -SourceAttempt and -StopAttempt died with
a ValidationMetadataException - the 2026-10-11 17:22 R4-RESTORE failure. FIX-RETARGET removed the attributes (the values are
validated by Assert-RetargetParameters); the plan tests below, strict xfail until then, now pass for every documented call.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

import pytest

import ps_toplevel_smoke as smoke

W = smoke.WORKSPACE
RETARGET = W / 'retarget-warden-r5.ps1'
STOP_R5 = W / 'stop-warden-r5.ps1'
STOP_R4 = W / 'stop-warden-r4.ps1'
CUTOVER_DOC = W / 'r5-army-specs' / 'INTERFACES-CUTOVER.md'
R5_CONFIG_V1 = r'C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-r5-v1\pipeline.json'
R5_CONFIG_V2 = r'C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-r5-v2\pipeline.json'
# The doc's attempt placeholders: r5 attempt vN, r4-restore attempt vM, stop attempts vK / vK2.
PLACEHOLDERS = {'vK2': 'v2', 'vN': 'v1', 'vM': 'v2', 'vK': 'v1'}
RETARGET_PLAN = 'cochem-warden-retarget-plan/3'
STOP_R5_PLAN = 'cochem-warden-stop-plan/2'
STOP_R4_PLAN = 'cochem-warden-stop-plan/1'


def _split_call(text: str) -> list[str]:
    lexer = shlex.shlex(text, posix=False)
    lexer.whitespace_split = True
    return [token[1:-1] if len(token) >= 2 and token[0] == token[-1] == '"' else token for token in lexer]


def documented_calls() -> list[tuple[str, tuple[str, ...]]]:
    """The '.\\<script>.ps1 ...' calls of INTERFACES-CUTOVER.md's 'Calls' section, placeholders filled, de-duplicated."""
    text = CUTOVER_DOC.read_text(encoding='utf-8')
    section = text.split('## Calls', 1)[1].split('\n## ', 1)[0]
    calls: list[tuple[str, tuple[str, ...]]] = []
    for match in re.finditer(r'\.\\(retarget-warden-r5|stop-warden-r5)\.ps1 ([^\n]+)', section):
        line = match.group(2).strip()
        for placeholder, value in PLACEHOLDERS.items():
            line = re.sub(r'\b' + placeholder + r'\b', value, line)
        line = line.replace('"<cfg>"', '"' + R5_CONFIG_V2 + '"')
        key = (match.group(1) + '.ps1', tuple(_split_call(line)))
        if key not in calls:
            calls.append(key)
    return calls


def _without(args, *names) -> tuple[str, ...]:
    lowered = {n.lower() for n in names}
    return tuple(a for a in args if a.lower() not in lowered)


def _value(args, name):
    return args[args.index(name) + 1] if name in args else None


def _call_id(args) -> str:
    out = []
    for a in args:
        out.append(Path(a).parent.name if '\\' in a else a.lstrip('-'))
    return '_'.join(out)


DOC_CALLS = documented_calls()
RETARGET_DOC = [args for script, args in DOC_CALLS if script == 'retarget-warden-r5.ps1']
STOP_R5_DOC = [args for script, args in DOC_CALLS if script == 'stop-warden-r5.ps1']
# The 'restored r4 back to r5 later' calls the doc gives in prose (C-F3): stop the restored r4 (vM = v2), then retarget.
RETARGET_PROSE = [('-Target', 'r5', '-Config', R5_CONFIG_V1, '-Attempt', 'v3', '-SourceAttempt', 'v2', '-StopAttempt', 'v2'),
                  ('-Target', 'r5', '-Config', R5_CONFIG_V1, '-Attempt', 'v3', '-SourceAttempt', 'v2')]
STOP_R5_PROSE = [('-Attempt', 'v2', '-RetargetTarget', 'r4', '-RetargetAttempt', 'v2'),
                 ('-Attempt', 'v2', '-RetargetTarget', 'r4', '-RetargetAttempt', 'v2', '-RecoverInterruptedStart')]


def _plan_args(args) -> tuple[str, ...]:
    return _without(args, '-Apply', '-Start')


RETARGET_PLAN_CALLS = []
for _args in [_plan_args(a) for a in RETARGET_DOC] + RETARGET_PROSE:
    if _args not in RETARGET_PLAN_CALLS:
        RETARGET_PLAN_CALLS.append(_args)
STOP_R5_PLAN_CALLS = []
for _args in [_without(a, '-Apply') for a in STOP_R5_DOC] + STOP_R5_PROSE:
    if _args not in STOP_R5_PLAN_CALLS:
        STOP_R5_PLAN_CALLS.append(_args)


def _expect_retarget_plan(result: smoke.SmokeResult, args) -> dict:
    # A PsVariableValidationError here is the 17:22 bug coming back (retarget-warden-r5.ps1 assigning to a validated variable).
    outcome = smoke.plan_mode_outcome(result, plan_schema=RETARGET_PLAN)
    assert outcome == 'plan', result.describe()
    plan = result.plan
    assert plan['target'] == _value(args, '-Target')
    assert plan['attempt'] == (_value(args, '-Attempt') or 'v1')
    assert plan['tasks_changed'] == 0 and plan['started'] is False and plan['automatic_retry_allowed'] is False
    assert plan['administrator'] is False and plan['task_readable'] is False
    assert any('Warden task definition is unreadable without elevation' in h for h in plan['holds']), plan['holds']
    return plan


def _assert_no_temp_left(before: set[str]) -> None:
    after = {p.name for p in Path(tempfile.gettempdir()).glob('ps-toplevel-smoke-*')}
    assert not (after - before), f'temporary run directories left behind: {sorted(after - before)}'


# ---------------------------------------------------------------------------------------------------------------- pure

@pytest.mark.parametrize('args', [
    ['-Apply'], ['-apply'], ['-APPLY:$true'], ['-Apply:$false'], ['-App'], ['-Ap'], ['-A'], ['\u2013Apply'],
    ['\u2014apply'], ['-Target', 'r4', '-Attempt', 'v1', '-Apply', '-Start'], ['-Appl:', 'x'],
])
def test_apply_is_refused_before_any_process_starts(args, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError('a process was started for an -Apply argument list')
    monkeypatch.setattr(smoke.subprocess, 'run', forbidden)
    with pytest.raises(smoke.SmokeRefused, match='would bind -Apply'):
        smoke.run_toplevel(RETARGET, args)


@pytest.mark.parametrize('args', [['-Attempt', 'v1'], ['-Target', 'r4'], ['Apply'], ['-SourceAttempt', 'v1'], ['-AttemptX']])
def test_non_apply_arguments_pass_the_refusal(args):
    assert smoke.apply_argument(args) is None


def test_command_text_keeps_parameter_tokens_and_quotes_values():
    text = smoke.render_command_text(r'C:\W\s.ps1', ['-Target', 'r5', '-Config', r"C:\Program Files\it's.json",
                                                     '-Flag:$false', '-Count', '7', '-Name:', 'a b', '$(evil)', '-x;y'])
    assert text == (r"& 'C:\W\s.ps1' -Target 'r5' -Config 'C:\Program Files\it''s.json' -Flag:$false -Count 7 -Name: 'a b' "
                    r"'$(evil)' '-x;y'")


def test_stub_definition_typos_are_rejected():
    with pytest.raises(ValueError, match='unknown stub keys'):
        smoke.run_toplevel(STOP_R4, [], stub={'proceses': []})
    stub = smoke.default_stub()
    stub['host']['elevation'] = True
    with pytest.raises(ValueError, match='unknown host keys'):
        smoke.run_toplevel(STOP_R4, [], stub=stub)


def test_error_classification():
    variable = smoke.ErrorInfo.from_json({'fqid': 'ValidateSetFailure,retarget-warden-r5.ps1', 'inner_fqid': 'ValidateSetFailure',
        'category': 'MetadataError', 'exception_type': 'System.Management.Automation.ValidationMetadataException',
        'chain': [], 'message': 'The variable cannot be validated because the value  is not a valid value for the SourceAttempt variable.'})
    assert variable.is_binding and variable.variable == 'SourceAttempt' and not variable.is_clean_refusal
    bound = smoke.ErrorInfo.from_json({'fqid': 'ParameterArgumentValidationError,x.ps1', 'inner_fqid': 'ParameterArgumentValidationError,x.ps1',
        'category': 'InvalidData', 'exception_type': 'System.Management.Automation.ParameterBindingValidationException',
        'chain': ['System.Management.Automation.ParameterBindingValidationException', 'System.Management.Automation.ValidationMetadataException'],
        'message': 'Cannot validate argument on parameter'})
    assert bound.is_binding and bound.variable is None
    refusal = smoke.ErrorInfo.from_json({'fqid': 'Held, nothing changed: a | b', 'inner_fqid': 'Held, nothing changed: a | b',
        'category': 'OperationStopped', 'exception_type': 'System.Management.Automation.RuntimeException', 'chain': [],
        'message': 'Held, nothing changed: a | b'})
    assert refusal.is_clean_refusal and not refusal.is_binding
    engine = smoke.ErrorInfo.from_json({'fqid': 'InvokeMethodOnNull', 'inner_fqid': 'InvokeMethodOnNull', 'category': 'InvalidOperation',
        'exception_type': 'System.Management.Automation.RuntimeException', 'chain': [], 'message': 'You cannot call a method on a null-valued expression.'})
    assert not engine.is_clean_refusal and not engine.is_binding


def test_cutover_doc_calls_are_found():
    # The parser must keep finding the documented calls; a reformatted 'Calls' section has to be followed here.
    assert len(RETARGET_DOC) >= 7 and len(STOP_R5_DOC) >= 2, DOC_CALLS
    assert ('-Target', 'r4', '-Attempt', 'v1', '-Apply', '-Start') in RETARGET_DOC
    assert all('-Apply' in args for args in RETARGET_DOC + STOP_R5_DOC)
    assert all(smoke.apply_argument(args) is None for args in RETARGET_PLAN_CALLS + STOP_R5_PLAN_CALLS)


# ------------------------------------------------------------------------------------------- fidelity against direct runs

FIDELITY_FIXTURE = r'''[CmdletBinding()]
param([ValidateSet('a','b')][string]$Mode='a',[switch]$Flag,[ValidatePattern('^v[0-9]{1,3}$')][string]$Att='',[int]$Count=1,
      [Parameter(Mandatory=$true)][string]$Need)
$fixtureScopeProbe = 'x'
'scope_is_global=' + [bool](Get-Variable fixtureScopeProbe -Scope Global -ErrorAction SilentlyContinue)
'mode=' + $Mode + ' flag=' + [bool]$Flag + ' att=[' + $Att + '] count=' + $Count + ' need=[' + $Need + ']'
function Set-Bad { $ErrorActionPreference = 'Stop'; Set-StrictMode -Version Latest; $script:Att = '' }
if ($Need -eq 'exit3') { exit 3 }
if ($Need -eq 'throw') { throw 'fixture refused' }
if ($Need -eq 'assign') { $script:Att = '' }
if ($Need -eq 'assign-stop') { Set-Bad }
'end'
'''

FILE_CASES = [
    ['-Need', 'x', '-Mode', 'b', '-Flag'], ['-Need:x', '-Att:v12', '-Count', '7'], ['-Need:', 'two words', '-Flag:$true'],
    ['-Need', 'x', '-Flag:$false'], ['-Need', 'x', '-Mode', 'c'], ['-Mode', 'a'], ['-Need', 'x', 'extra'],
    ['-Need', 'x', '-Nope', '1'], ['-Need', ''], ['-Need', 'exit3'], ['-Need', 'throw'], ['-Need', 'assign'],
    ['-Need', 'assign-stop'], ['-Need', 'x', '-Count', 'many'],
]
COMMAND_CASES = [['-Need', 'x', '-Mode', 'b', '-Flag:$false', '-Count', '7'], ['-Need', 'x', '-Mode', 'c'], ['-Need', 'throw'],
                 ['-Need', 'assign'], ['-Need', 'assign-stop']]


@pytest.fixture(scope='module')
def fidelity_fixture(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp('fidelity') / 'fidelity-fixture.ps1'
    path.write_text(FIDELITY_FIXTURE, encoding='ascii')
    return path


def _direct(fixture: Path, args, invocation: str) -> dict:
    tail = ['-File', str(fixture), *args] if invocation == 'file' else ['-Command', smoke.render_command_text(fixture, args)]
    env = dict(os.environ)
    env['PSModulePath'] = str(smoke.PSHOME / 'Modules')
    run = subprocess.run([str(smoke.POWERSHELL), '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', *tail],
                         cwd=str(fixture.parent), env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=120,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    stderr = run.stderr.decode('utf-8', errors='replace')
    match = re.search(r'FullyQualifiedErrorId\s*:\s*(.+?)\s*$', stderr, re.M)
    return {'exit': run.returncode, 'fqid': match.group(1) if match else None,
            'stdout': [line.strip() for line in run.stdout.decode('utf-8', errors='replace').splitlines() if line.strip()]}


def _helper(fixture: Path, args, invocation: str) -> dict:
    result = smoke.run_toplevel(fixture, args, invocation=invocation)
    result.raise_for_harness()
    assert not result.denied, result.describe()
    first = result.error or (result.errors[0] if result.errors else None)
    return {'exit': result.exit_code, 'fqid': first.fqid if first else None,
            'stdout': [line.strip() for line in result.stdout.splitlines() if line.strip()]}


@pytest.mark.parametrize('args', FILE_CASES, ids=[f'file{i}' for i in range(len(FILE_CASES))])
def test_file_invocation_matches_powershell_dash_file(fidelity_fixture, args):
    assert _helper(fidelity_fixture, args, 'file') == _direct(fidelity_fixture, args, 'file')


@pytest.mark.parametrize('args', COMMAND_CASES, ids=[f'command{i}' for i in range(len(COMMAND_CASES))])
def test_command_invocation_matches_a_console_line(fidelity_fixture, args):
    helper, direct = _helper(fidelity_fixture, args, 'command'), _direct(fidelity_fixture, args, 'command')
    assert helper['fqid'] == direct['fqid'] and helper['stdout'] == direct['stdout']
    assert helper['exit'] == direct['exit'] or (helper['exit'] == 1 and direct['exit'] == 1)


def test_exit_statement_and_scope_semantics(fidelity_fixture):
    exited = smoke.run_toplevel(fidelity_fixture, ['-Need', 'exit3'])
    assert exited.exit_code == 3 and exited.error is None and exited.stdout.splitlines()[0] == 'scope_is_global=True'
    with pytest.raises(smoke.PlanModeError):
        smoke.plan_mode_outcome(exited)
    refused = smoke.run_toplevel(fidelity_fixture, ['-Need', 'throw'])
    assert smoke.plan_mode_outcome(refused) == 'refusal' and refused.error.message == 'fixture refused'
    # At the top level (ErrorActionPreference Continue) the failed assignment is statement-terminating: the script goes on.
    assigned = smoke.run_toplevel(fidelity_fixture, ['-Need', 'assign'])
    with pytest.raises(smoke.PsVariableValidationError):
        smoke.plan_mode_outcome(assigned)
    assert assigned.exit_code == 0 and assigned.error is None and assigned.errors[0].variable == 'Att'
    assert assigned.stdout.split()[-1] == 'end'
    # Inside a function with ErrorActionPreference Stop (retarget-warden-r5.ps1's shape) it stops the script: exit 1 with
    # -File, and an error that ends the '& script' line as typed at a console.
    for invocation in ('file', 'command'):
        stopped = smoke.run_toplevel(fidelity_fixture, ['-Need', 'assign-stop'], invocation=invocation)
        with pytest.raises(smoke.PsVariableValidationError):
            smoke.plan_mode_outcome(stopped)
        assert stopped.exit_code == 1 and stopped.error.variable == 'Att', stopped.describe()
        assert stopped.error.fqid == 'ValidateSetFailure,fidelity-fixture.ps1' and 'end' not in stopped.stdout.split()
    command = smoke.run_toplevel(fidelity_fixture, ['-Need', 'x'], invocation='command')
    assert command.stdout.splitlines()[0] == 'scope_is_global=False'


# ------------------------------------------------------------------------------------------------------- guard and stubs

GUARD_FIXTURE = r'''param([string]$Sentinel)
$ErrorActionPreference = 'Stop'; Set-StrictMode -Version Latest
$attempts = [ordered]@{}
function Try-It([string]$Name, [scriptblock]$Block) { try { $null = & $Block; $attempts[$Name] = 'ran' } catch { $attempts[$Name] = 'blocked: ' + $_.Exception.Message } }
Try-It 'new-item' { New-Item -ItemType File -Path (Join-Path $Sentinel 'leak-new-item.txt') }
Try-It 'set-content' { Set-Content -LiteralPath (Join-Path $Sentinel 'leak-set-content.txt') -Value 'x' }
Try-It 'out-file' { 'x' | Out-File -FilePath (Join-Path $Sentinel 'leak-out-file.txt') }
Try-It 'io-file-write' { [IO.File]::WriteAllText((Join-Path $Sentinel 'leak-io.txt'), 'x') }
Try-It 'io-file-open-write' { [IO.File]::Open((Join-Path $Sentinel 'leak-open.txt'), [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None) }
Try-It 'cmd' { cmd.exe /c "echo leak> `"$Sentinel\leak-cmd.txt`"" }
Try-It 'native-path' { & "$env:SystemRoot\System32\whoami.exe" }
Try-It 'start-process' { Start-Process -FilePath "$env:SystemRoot\System32\whoami.exe" -NoNewWindow -Wait }
Try-It 'module-qualified-cmdlet' { Microsoft.PowerShell.Management\Get-Service -Name 'Spooler' }
Try-It 'invoke-expression' { Invoke-Expression '1' }
Try-It 'module-function' { Get-NetIPAddress -AddressFamily IPv4 }
Try-It 'external-script' { & (Join-Path $Sentinel 'other.ps1') }
Try-It 'registry' { Test-Path -LiteralPath 'HKLM:\SOFTWARE' }
Try-It 'com-other' { New-Object -ComObject 'WScript.Shell' }
Try-It 'net-type' { New-Object -TypeName 'System.Net.WebClient' }
$scheduler = New-Object -ComObject 'Schedule.Service'; $scheduler.Connect(); $folder = $scheduler.GetFolder('\')
$task = $folder.GetTask('Readable')
Try-It 'com-run' { $task.Run($null) }
Try-It 'com-enable' { $task.Enabled = $true }
Try-It 'com-instance-stop' { $task.GetInstances(0).Item(1).Stop() }
Try-It 'com-register' { $folder.RegisterTaskDefinition('X', $null, 6, $null, $null, 5) }
Try-It 'com-delete' { $folder.DeleteTask('Readable', 0) }
Try-It 'com-new-task' { $scheduler.NewTask(0) }
Try-It 'sleep-budget' { foreach ($i in 1..5) { Start-Sleep -Milliseconds 1 } }
$attempts | ConvertTo-Json -Compress
'''

OTHER_SCRIPT = "Set-Content -LiteralPath (Join-Path $PSScriptRoot 'leak-other.txt') -Value 'x'\n"


def test_unstubbed_host_commands_are_denied_not_executed(tmp_path):
    sentinel = tmp_path / 'sentinel'
    sentinel.mkdir()
    (sentinel / 'other.ps1').write_text(OTHER_SCRIPT, encoding='ascii')
    fixture = tmp_path / 'guard-fixture.ps1'
    fixture.write_text(GUARD_FIXTURE, encoding='ascii')
    stub = smoke.default_stub()
    stub['tasks']['Readable'] = {'enabled': False, 'state': 1, 'instances': 1}
    stub['sleep_budget'] = 3
    before = {p.name for p in Path(tempfile.gettempdir()).glob('ps-toplevel-smoke-*')}
    result = smoke.run_toplevel(fixture, ['-Sentinel', str(sentinel)], stub=stub)
    _assert_no_temp_left(before)
    result.raise_for_harness()
    assert result.exit_code == 0 and result.guard_intact is True, result.describe()
    attempts = json.loads(result.stdout)
    leaked = {name: outcome for name, outcome in attempts.items() if not outcome.startswith('blocked: ')}
    assert not leaked, leaked
    assert all('SmokeDenied' in outcome for outcome in attempts.values()), attempts
    assert sorted(p.name for p in sentinel.iterdir()) == ['other.ps1']
    denied = {entry['command'] for entry in result.denied}
    for command in ('New-Item', 'Set-Content', 'Out-File', '[IO.File]::WriteAllText', '[IO.File]::Open', 'cmd.exe',
                    'Start-Process', 'Microsoft.PowerShell.Management\\Get-Service', 'Invoke-Expression', 'Get-NetIPAddress',
                    'Test-Path', 'New-Object', 'Schedule.Service.Task.Run',
                    'Schedule.Service.Task.Enabled', 'Schedule.Service.RunningTask.Stop', 'Schedule.Service.Folder.RegisterTaskDefinition',
                    'Schedule.Service.Folder.DeleteTask', 'Schedule.Service.NewTask', 'Start-Sleep'):
        assert command in denied, (command, sorted(denied))
    assert any(e['command'].lower().endswith('whoami.exe') for e in result.denied)
    assert any(e['command'].endswith('other.ps1') for e in result.denied)
    with pytest.raises(smoke.HostAccessDenied):
        smoke.plan_mode_outcome(result)


STUB_FIXTURE = r'''param()
$ErrorActionPreference = 'Stop'; Set-StrictMode -Version Latest
$r = [ordered]@{}
function Get-Fqid([scriptblock]$Block) { try { $null = & $Block; 'no-error' } catch { [string]$_.FullyQualifiedErrorId + ' | ' + $_.Exception.Message } }
$procs = @(Get-CimInstance Win32_Process -ErrorAction Stop)
$r.process_count = $procs.Count
$mine = @($procs | Where-Object { $_.ProcessId -eq 21000 })[0]
$r.mine_path = [string]$mine.ExecutablePath
$r.mine_owner = [string](Invoke-CimMethod -InputObject $mine -MethodName GetOwner -ErrorAction Stop).User
$system = @(Get-CimInstance Win32_Process -Filter 'ProcessId = 4' -ErrorAction Stop)[0]
$r.system_path_is_null = ($null -eq $system.ExecutablePath -and $null -eq $system.CommandLine)
$r.system_owner_return = [int](Invoke-CimMethod -InputObject $system -MethodName GetOwner -ErrorAction Stop).ReturnValue
$r.gone = @(Get-CimInstance Win32_Process -Filter 'ProcessId = 99999' -ErrorAction Stop).Count
$r.boot = (Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$r.include_user = Get-Fqid { Get-Process -IncludeUserName -ErrorAction Stop }
$r.process_name = @(Get-Process -Id 21000 -ErrorAction Stop)[0].ProcessName
$r.listen_47824 = Get-Fqid { Get-NetTCPConnection -LocalPort 47824 -State Listen -ErrorAction Stop }
$r.listen_47825_owner = [int]@(Get-NetTCPConnection -LocalPort 47825 -State Listen -ErrorAction Stop)[0].OwningProcess
$scheduler = New-Object -ComObject 'Schedule.Service'; $scheduler.Connect(); $folder = $scheduler.GetFolder('\')
foreach ($name in @('CoChem-4.2.7-Warden', 'NoSuchTask')) {
    $code = 0
    try { $null = $folder.GetTask($name) } catch { $e = $_.Exception; while ($null -ne $e) { if ($e.HResult -in @(-2147024891, -2147024894)) { $code = $e.HResult }; $e = $e.InnerException } }
    $r['hresult_' + $name] = $code
}
$task = $folder.GetTask('Readable')
$r.readable = [ordered]@{ enabled = $task.Enabled; state = $task.State; instances = $task.GetInstances(0).Count; actions = $task.Definition.Actions.Count
    action_path = $task.Definition.Actions.Item(1).Path; trigger_user = $task.Definition.Triggers.Item(1).UserId; trigger_enabled = $task.Definition.Triggers.Item(1).Enabled
    repetition = $task.Definition.Triggers.Item(1).Repetition.Interval; sddl = $task.GetSecurityDescriptor(7); user = $task.Definition.Principal.UserId; xml = $task.Xml }
$r.gst_denied = Get-Fqid { Get-ScheduledTask -TaskName 'CoChem-4.2.7-Warden' -ErrorAction Stop }
$r.gst_state = [string](Get-ScheduledTask -TaskName 'Readable' -ErrorAction Stop).State
$clock = [Diagnostics.Stopwatch]::StartNew(); Start-Sleep -Seconds 30; $r.slept_ms = $clock.ElapsedMilliseconds
$probeOut = & 'C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe' -I -B -c 'import socket' 47824
$r.native_out = [string]$probeOut
$r.native_exit = $LASTEXITCODE
$r.native_unmatched = Get-Fqid { robocopy.exe 'C:\a' 'C:\b' /L }
$r.vfile_text = (Get-Content -LiteralPath 'C:\Users\ansac\CoChem427\pipeline-client-r3.json' -Raw).Trim()
$r.vfile_hash = (Get-FileHash -LiteralPath 'C:\Users\ansac\CoChem427\pipeline-client-r3.json' -Algorithm SHA256).Hash
$r.vacl = Get-Fqid { Get-Acl -LiteralPath 'C:\Program Files\CoChem' }
$r.absent_item = Get-Fqid { Get-Item -LiteralPath 'C:\Program Files\CoChem\Nope' }
$r.absent_test = Test-Path -LiteralPath 'C:\Windows\win.ini'
$r.vdir_leaf = Test-Path -LiteralPath 'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5' -PathType Leaf
$r.vdir_container = Test-Path -LiteralPath 'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5' -PathType Container
$r.real_item = (Get-Item -LiteralPath $PSCommandPath).Name
$r.vdir_children = @(Get-ChildItem -LiteralPath 'C:\Program Files\CoChem' -Directory -Filter 'Pipeline*' | ForEach-Object { $_.Name })
$r.io_read = [IO.File]::ReadAllText('C:\Users\ansac\CoChem427\pipeline-client-r3.json').Trim()
$r.io_absent = try { $null = [IO.File]::ReadAllBytes('C:\Windows\win.ini'); 'read' } catch { $_.Exception.InnerException.GetType().Name }
$r.io_exists_real = [IO.File]::Exists($PSCommandPath)
$r.admin = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$r.computer = $env:COMPUTERNAME
$r.http_ok = (Invoke-RestMethod -Uri 'http://127.0.0.1:47825/health').status
$r.http_refused = Get-Fqid { Invoke-RestMethod -Uri 'http://127.0.0.1:47824/health' }
$r.http_remote = Get-Fqid { Invoke-WebRequest -Uri 'https://example.com/' -UseBasicParsing }
$r | ConvertTo-Json -Compress -Depth 4
'''


def _stub_world(elevated: bool = False) -> dict:
    stub = smoke.default_stub()
    stub['host']['elevated'] = elevated
    stub['processes'] = smoke.live_mcp_clients_20261011() + [
        {'pid': 4, 'name': 'System', 'owner': 'NT AUTHORITY\\SYSTEM'},
        {'pid': 3000, 'parent_pid': 900, 'name': 'python.exe', 'path': smoke.TOOLCHAIN_PYTHON, 'owner': 'NT AUTHORITY\\SYSTEM',
         'command_line': 'python.exe held-supervisor-observation-r3-v1.py --observe'}]
    stub['listeners'] = [{'port': 47825, 'pid': 3000}]
    stub['tasks']['NoSuchTask'] = 'absent'
    stub['tasks']['Readable'] = {
        'enabled': False, 'state': 1, 'instances': 2, 'xml': '<Task/>', 'sddl': 'D:P(A;;FA;;;SY)',
        'principal': {'user_id': 'S-1-5-18', 'logon_type': 5, 'run_level': 1},
        'actions': [{'path': r'C:\x\python.exe', 'arguments': '-I -B -m cochem_pipeline daemon', 'working_directory': r'C:\x'}],
        'triggers': [{'type': 9, 'enabled': False, 'user_id': 'AETHERDESK\\ansac', 'delay': 'PT1M', 'repetition_interval': ''}]}
    stub['natives'] = {'python.exe': [{'match': r'-c import socket 47824$', 'exit': 2, 'stdout': 'probe-out\n'}],
                       'robocopy.exe': [{'match': '/MIR', 'exit': 1}]}
    stub['http'] = {'http://127.0.0.1:47825/health': {'status': 200, 'body': '{"status": "ok"}'}}
    return stub


def test_stubbed_host_answers_are_deterministic(tmp_path):
    fixture = tmp_path / 'stub-fixture.ps1'
    fixture.write_text(STUB_FIXTURE, encoding='ascii')
    result = smoke.run_toplevel(fixture, [], stub=_stub_world())
    result.raise_for_harness()
    assert result.exit_code == 0, result.describe()
    r = json.loads(result.stdout)
    assert r['process_count'] == 16 and r['gone'] == 0
    assert r['mine_path'].endswith(r'.venv\Scripts\python.exe') and r['mine_owner'] == 'ansac'
    assert r['system_path_is_null'] is True and r['system_owner_return'] == 2
    assert r['boot'] == '2026-10-10T22:57:00Z'
    assert r['include_user'].startswith('IncludeUserNameRequiresElevation')
    assert r['process_name'] == 'python'
    assert r['listen_47824'].startswith('CmdletizationQuery_NotFound,Get-NetTCPConnection')
    assert r['listen_47825_owner'] == 3000
    assert r['hresult_CoChem-4.2.7-Warden'] == -2147024891 and r['hresult_NoSuchTask'] == -2147024894
    assert r['readable'] == {'enabled': False, 'state': 1, 'instances': 2, 'actions': 1, 'action_path': r'C:\x\python.exe',
                             'trigger_user': 'AETHERDESK\\ansac', 'trigger_enabled': False, 'repetition': '',
                             'sddl': 'D:P(A;;FA;;;SY)', 'user': 'S-1-5-18', 'xml': '<Task/>'}
    assert r['gst_denied'].startswith('HRESULT 0x80070005') and r['gst_state'] == 'Disabled'
    assert r['slept_ms'] < 5000
    assert r['native_out'] == 'probe-out' and r['native_exit'] == 2
    assert 'SmokeDenied' in r['native_unmatched']
    assert r['vfile_text'] == r['io_read'] == '{"port": 47824, "token_file": "C:\\\\Users\\\\ansac\\\\CoChem427\\\\controller.token"}'
    assert r['vfile_hash'] == __import__('hashlib').sha256(
        smoke.default_stub()['fs']['virtual_files'][smoke.CLIENT_CONFIG].encode()).hexdigest().upper()
    assert r['vacl'].startswith('SmokeVirtualAcl') and r['absent_item'].startswith('PathNotFound,Get-Item')
    assert r['absent_test'] is False and r['vdir_leaf'] is False and r['vdir_container'] is True
    assert r['real_item'] == 'stub-fixture.ps1'
    assert r['vdir_children'] == ['Pipeline4.2.7-windows-20261007-r3', 'Pipeline4.2.7-windows-20261009-r4', 'Pipeline4.2.7-windows-20261011-r5']
    assert r['io_absent'] == 'FileNotFoundException' and r['io_exists_real'] is True
    assert r['admin'] is False and r['computer'] == 'AETHERDESK'
    assert r['http_ok'] == 'ok' and r['http_refused'].startswith('WebCmdletWebResponseException')
    assert 'SmokeDenied' in r['http_remote']
    assert {e['command'] for e in result.denied} == {'robocopy.exe', 'Invoke-WebRequest'}, result.denied
    assert [e['detail'] for e in result.calls('Start-Sleep', kind='sleep')] == ['30s (not slept)']
    assert result.calls('C:\\Program Files\\CoChem\\Toolchain4.2.7-windows-20261006\\Python312\\python.exe', kind='native')
    pretend = smoke.run_toplevel(fixture, [], stub=_stub_world(elevated=True))
    r2 = json.loads(pretend.stdout)
    assert r2['admin'] is True and r2['system_owner_return'] == 0 and r2['system_path_is_null'] is True  # System has no path
    assert r2['include_user'] == 'no-error'


# ------------------------------------------------------------------------- the r5 cutover scripts, top level, plan mode

@pytest.mark.parametrize('args', [pytest.param(a, id=_call_id(_without(a, '-Apply'))) for a in RETARGET_DOC])
def test_retarget_documented_call_without_apply_is_refused_cleanly(args):
    # The documented calls keep -Start; without -Apply the script's own parameter rules refuse before anything is read.
    result = smoke.run_toplevel(RETARGET, _without(args, '-Apply'))
    assert smoke.plan_mode_outcome(result) == 'refusal', result.describe()
    assert result.error.message == '-Start is only meaningful together with -Apply.'
    assert result.trace == ()


@pytest.mark.parametrize('args', [pytest.param(a, id=_call_id(a)) for a in RETARGET_PLAN_CALLS])
def test_retarget_documented_call_plan(args):
    result = smoke.run_toplevel(RETARGET, args)
    _expect_retarget_plan(result, args)


@pytest.mark.parametrize('args', [
    pytest.param(('-Target', 'r4', '-Attempt', 'v1'), id='r4_v1'),
    pytest.param(('-Target', 'r4', '-Attempt', 'v2', '-SourceAttempt', 'v1', '-StopAttempt', 'v1'), id='r4_v2_from_r5_v1'),
])
def test_retarget_plan_as_typed_at_a_console(args):
    result = smoke.run_toplevel(RETARGET, args, invocation='command')
    _expect_retarget_plan(result, args)


def test_retarget_plan_sees_the_live_mcp_clients():
    # The 17:22 host: 14 owner MCP clients, nothing on 47824. The plan must account for every one of them (how they are
    # classified is the presence logic's business, not this runner's).
    stub = smoke.default_stub()
    stub['processes'] = smoke.live_mcp_clients_20261011()
    args = ('-Target', 'r4', '-Attempt', 'v2', '-SourceAttempt', 'v1', '-StopAttempt', 'v1')
    result = smoke.run_toplevel(RETARGET, args, stub=stub)
    presence = _expect_retarget_plan(result, args)['controller_presence']
    assert presence['listening'] == 0 and presence['controller_processes'] == []
    seen = presence['client_processes'] + presence['unclassified_runtime_processes'] + presence['observer_processes']
    assert sorted(p['pid'] for p in seen) == sorted(p['pid'] for p in smoke.live_mcp_clients_20261011())


@pytest.mark.parametrize('args', [pytest.param(a, id=_call_id(a)) for a in STOP_R5_PLAN_CALLS])
def test_stop_warden_r5_plan(args):
    result = smoke.run_toplevel(STOP_R5, args)
    assert smoke.plan_mode_outcome(result, plan_schema=STOP_R5_PLAN) == 'plan', result.describe()
    plan = result.plan
    assert plan['retarget_target'] == _value(args, '-RetargetTarget') and plan['retarget_attempt'] == _value(args, '-RetargetAttempt')
    assert plan['attempt'] == _value(args, '-Attempt') and plan['recover_interrupted_start'] is ('-RecoverInterruptedStart' in args)
    assert plan['tasks_changed'] == 0 and plan['ended'] is False and plan['disabled'] is False and plan['processes_killed'] is False
    assert plan['administrator'] is False and plan['task_readable'] is False


def test_stop_warden_r5_plan_with_live_mcp_clients_and_as_typed():
    stub = smoke.default_stub()
    stub['processes'] = smoke.live_mcp_clients_20261011()
    args = ('-Attempt', 'v1', '-RetargetTarget', 'r5', '-RetargetAttempt', 'v1')
    result = smoke.run_toplevel(STOP_R5, args, stub=stub, invocation='command')
    assert smoke.plan_mode_outcome(result, plan_schema=STOP_R5_PLAN) == 'plan', result.describe()
    presence = result.plan['controller_presence']
    seen = presence['client_processes'] + presence['unclassified_runtime_processes'] + presence['observer_processes']
    assert len(seen) == 14 and presence['controller_processes'] == [] and presence['listening'] == 0


def test_stop_warden_r5_without_the_mandatory_retarget_attempt_is_a_binding_error():
    # A caller error, not a script bug: the runner must report it as a binding error, never as a plan or refusal.
    result = smoke.run_toplevel(STOP_R5, ['-Attempt', 'v1'])
    assert result.binding_error and result.error.fqid == 'MissingMandatoryParameter,stop-warden-r5.ps1'
    with pytest.raises(smoke.PsBindingError):
        smoke.plan_mode_outcome(result)


@pytest.mark.parametrize('args', [(), ('-Attempt', 'v1'), ('-Attempt', 'v2', '-IdleWaitSeconds', '60', '-ExitWaitSeconds', '30')],
                         ids=['defaults', 'sitting_S2_v1', 'v2_waits'])
def test_stop_warden_r4_plan(args):
    result = smoke.run_toplevel(STOP_R4, args)
    assert smoke.plan_mode_outcome(result, plan_schema=STOP_R4_PLAN) == 'plan', result.describe()
    plan = result.plan
    assert plan['attempt'] == (_value(args, '-Attempt') or 'v1')
    assert plan['tasks_changed'] == 0 and plan['ended'] is False and plan['disabled'] is False and plan['processes_killed'] is False


def test_stop_warden_r4_rejects_an_out_of_range_wait_as_a_binding_error():
    result = smoke.run_toplevel(STOP_R4, ['-Attempt', 'v1', '-IdleWaitSeconds', '5'])
    assert result.error is not None and result.error.fqid == 'ParameterArgumentValidationError,stop-warden-r4.ps1'
    with pytest.raises(smoke.PsBindingError):
        smoke.plan_mode_outcome(result)
