"""Inert PS5.1 fixtures for login-six-workers-status-first-r4-v1.ps1 (build-manifest step 5).

Nothing here registers or runs a task, runs the status leaf, any login child or the agy/claude/codex CLIs,
contacts the live controller, reads a worker profile, uses the network, or runs the driver with -Apply.
Functions are taken from the driver's AST (its only top-level statement is the invocation, which never runs
here) and driven in a throwaway powershell.exe; every system call is stubbed and every write lands under
pytest's tmp_path. Reviewed helper definitions are imported read-only through the driver's own hash-pinned
importer. The -Apply gate is exercised only at function level (Invoke-LoginSeriesMain with stubbed host facts).
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

import pytest

import ps_toplevel_smoke as smoke

W = Path(__file__).parent
DRIVER = W / 'login-six-workers-status-first-r4-v1.ps1'
SERIES_V6 = W / 'login-six-workers-status-first-r3-v6.ps1'
LEAF = W / 'check-worker-native-auth-status-six-r4-v1.ps1'
STATUS_PY = W / 'worker-native-auth-status-six-r4-v1.py'
RETARGET = W / 'retarget-warden-r4.ps1'
COPY_HELPER = Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1')
CODEX_HELPER = Path(r'C:\Program Files\CoChem\InstallGuard4.2.7-windows-20261006\repository\scripts\login_pipeline_worker.ps1')
PS = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
COCHEM = r'C:\Program Files\CoChem'
ATTEMPT = '0123456789abcdef0123456789abcdef'
ZERO = '0' * 32
SLOTS = [f'slot{n}' for n in range(1, 7)]
WRAPPER_NAME = 'login_pipeline_worker_interactive_agy_r4_v1.ps1'
WRAPPER = W / WRAPPER_NAME
BRIDGE_PY = W / 'worker_agy_login_bridge_r4_v1.py'
HISTORY = W / 'agy-session-history-r4-v1.ps1'
# Final bridge pins handed over by the lead after the onboarding fix wave (also recomputed from disk below).
FINAL_BRIDGE_PINS = {'agyBridgeWrapperPin': (WRAPPER, 'da166c1dbdb047e93692eeb47abf3d315dbe797cf9040d34b440d9649626014a'),
                     'agyBridgePythonPin': (BRIDGE_PY, '4074878f100ae59b804c95bd97b3280ccaa09f919ffaa365a3e2c6985045b8d9'),
                     'agyHistoryPin': (HISTORY, '4e86b712314e2a6a8ea9f13e1dfcc9e65dda4035d2895b8043fbf6ceed0424d4')}
# The onboarding-fix status leaf (O-F5: task result 2 on HOLD), pinned by the driver as statusLeafHash.
FINAL_STATUS_LEAF_PIN = 'c0b5df803a339a7dbbbd59727ea59a75dc4722d474f4bb05852d5cdc8778e265'
LEAF_TESTS = W / 'test_check_worker_native_auth_status_six_r4_v1.py'
SECRETS = ('owner@example.invalid', 'SECRETSTATE123', 'SECRETCODE456', 'accounts.google.com')
NEUTRAL_LOG = ('Starting OAuth authentication flow\nPlease visit the following URL to authorize the application:\n'
               'https://accounts.google.com/o/oauth2/auth?client_id=x&state=SECRETSTATE123\n'
               'Or, paste the authorization code here and press Enter:\nSuccessfully exchanged authorization code for token\n'
               'Successfully authenticated as owner@example.invalid.\n')
V6_IMPORTS = ['Initialize-SeriesDirectory', 'Assert-SeriesPrivateRoot', 'Write-SeriesRecord', 'Get-SeriesWorkerRootHolds', 'Assert-SeriesDaemonsStopped',
              'Invoke-SeriesConsoleChild', 'Show-CodexDeviceLoginInstructions', 'Confirm-AttendedLoginReady', 'Invoke-SixStatusFirst']
COMMON_IMPORTS = (['Assert-NoReparseAncestors', 'Assert-ProtectedPath', 'Initialize-FileIdentity', 'Open-VerifiedFile', 'Read-R3Control', 'Read-R3Text',
                   'Assert-R3InstalledBindings', 'Assert-R4InstalledBindings', 'Assert-VenvBinding', 'Assert-AuthStatusReceipt', 'Add-AuthStatusFailureMetadata',
                   'New-PrivateAcl', 'Get-ExactTaskOrAbsent', 'Assert-CodeTreeOnce'] + V6_IMPORTS)
CLAUDE_HISTORY_IMPORTS = ['Test-ClaudeHistoryInteger', 'Get-ClaudeHistoryValue', 'Get-ClaudeHistorySafeReceiptMetadata', 'Assert-ClaudeHistoryPrivateAcl',
                          'Assert-ClaudeHistoryPrivateRoot', 'Assert-ClaudeHistoryTask', 'Assert-ClaudeHistoryReceipt', 'Assert-ReviewedClaudeHistory']


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


status = load(STATUS_PY, 'worker_native_auth_status_six_r4_v1_for_series')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def functions(path):
    return (f"$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$t,[ref]$e);if($e.Count){{throw $e[0]}};"
            "foreach($f in $ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){. ([scriptblock]::Create($f.Extent.Text))};")


PREFIX = ("$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;"
          "foreach($m in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME \"Modules\\$m\\$m.psd1\")};")


def ps(code, tmp_path, timeout=180):
    """Run fixture code from a file under tmp_path (dot-sourced as a scriptblock; no script file is executed)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    index = len(list(tmp_path.glob('fixture-*.ps1')))
    path = tmp_path / f'fixture-{index}.ps1'
    path.write_text(code, encoding='utf-8')
    command = PREFIX + f". ([scriptblock]::Create([IO.File]::ReadAllText('{path}')))"
    return subprocess.run([PS, '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, text=True, timeout=timeout)


def result_of(run):
    assert run.returncode == 0, run.stdout + run.stderr
    lines = [line for line in run.stdout.splitlines() if line.startswith('RESULT ')]
    assert lines, run.stdout + run.stderr
    return json.loads(lines[-1][len('RESULT '):])


def function_text(path, name, tmp_path):
    code = (f"$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$t,[ref]$e);"
            f"$n=@($ast.FindAll({{param($x)$x -is [Management.Automation.Language.FunctionDefinitionAst] -and $x.Name -ceq '{name}'}},$true));if($n.Count -ne 1){{throw 'count'}};"
            "'RESULT '+(@{text=$n[0].Extent.Text}|ConvertTo-Json -Compress)")
    return result_of(ps(code, tmp_path))['text']


def driver_text():
    return DRIVER.read_text(encoding='utf-8')


def driver_constant(name):
    match = re.search(r"\$script:" + re.escape(name) + r"='([^']*)'", driver_text())
    assert match, name
    return match.group(1)


# ---------------------------------------------------------------------------------------------- static checks

def test_script_parses_with_one_invocation_ascii_and_reviewed_param_block(tmp_path):
    code = ("$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile('" + str(DRIVER) + "',[ref]$t,[ref]$e);"
            "$s=@($a.EndBlock.Statements);$p=@($a.ParamBlock.Parameters);"
            "$sets=@(foreach($x in $p){foreach($at in @($x.Attributes|Where-Object{$_.TypeName.Name -eq 'ValidateSet'})){$x.Name.VariablePath.UserPath+'='+(@($at.PositionalArguments|ForEach-Object{$_.Value}) -join ',')}});"
            "'RESULT '+(@{errors=$e.Count;statements=$s.Count;functions=@($s|Where-Object{$_ -is [Management.Automation.Language.FunctionDefinitionAst]}).Count;"
            "last=$s[-1].Extent.Text;params=@($p|ForEach-Object{$_.Name.VariablePath.UserPath});sets=$sets}|ConvertTo-Json -Compress)")
    value = result_of(ps(code, tmp_path))
    assert value['errors'] == 0 and value['statements'] == value['functions'] + 1
    assert value['last'].startswith('Invoke-LoginSeriesMain ') and '-ApplyRequested ([bool]$Apply)' in value['last']
    assert value['params'] == ['Provider', 'LoginMode', 'Apply', 'Interactive', 'Attempt']
    # -LoginMode has no [ValidateSet] (2026-10-11 r5 sitting; see test_no_assignment_writes_a_validated_parameter_variable).
    assert value['sets'] == ['Provider=codex,claude,gemini']
    text = driver_text()
    assert text.isascii()
    for forbidden in ('Start-Process', 'Stop-Process', 'taskkill', 'Remove-Item', 'Unregister-ScheduledTask', 'Register-ScheduledTask', 'Start-ScheduledTask',
                      'Stop-ScheduledTask', 'schtasks', 'Invoke-Expression', 'cmd /c', 'RunAs', '.Stop(', 'DeleteTask', 'Enabled=$false', 'RegisterTaskDefinition',
                      '.Run(', 'Set-ExecutionPolicy', 'wsl', 'docker', 'D:\\Gdrive', '20261008-r3-v3', 'Pipeline4.2.7-windows-20261007-r3'):
        assert forbidden not in text, forbidden


def test_pins_equal_the_files_on_disk():
    local = {'statusLeafHash': LEAF, 'statusPythonHash': STATUS_PY, 'copyHelperPin': COPY_HELPER,
             'statusFunctionsPin': W / 'check-worker-native-status-r3.ps1', 'inspectionFunctionsPin': W / 'protected-code-inspection-v4.ps1',
             'seriesV6Pin': SERIES_V6, 'claudeHelperPin': W / 'login_pipeline_worker_interactive_r3_v6.ps1', 'claudeHistoryPin': W / 'claude-session-history-v6.ps1',
             'claudeBridgePin': W / 'worker_claude_login_bridge_r3.py', 'claudeSupportPin': W / 'worker-native-status-r3.py'}
    for name, path in local.items():
        assert driver_constant(name) == sha(path), name
    assert driver_constant('statusLeafHash') == FINAL_STATUS_LEAF_PIN == sha(LEAF)
    for stale in ('e47f14a3', 'ebda8c1e', '63b21fd1', '6f3a04c6'):
        assert stale not in driver_text(), stale
    if CODEX_HELPER.exists():
        assert driver_constant('codexHelperPin') == sha(CODEX_HELPER)
    assert driver_constant('basePythonPin') == status.BASE_PYTHON_SHA256 and driver_constant('venvConfigPin') == status.VENV_CONFIG_SHA256
    assert driver_constant('layoutPin') == status.LAYOUT_SHA256
    for provider in ('codex', 'claude', 'gemini'):
        assert f"{provider}='{status.CONTRACTS[provider]['sha256']}'" in driver_text()
    # The leaf pins the same helper the series holds and passes to the bridge as its support module.
    assert f"$script:sourceHash='{sha(STATUS_PY)}'" in LEAF.read_text(encoding='utf-8')
    # The bridge pins are single named constants equal to the final, reconciled bridge files on disk.
    assert 'RECONCILE-PENDING' not in driver_text()
    for name, (path, pin) in FINAL_BRIDGE_PINS.items():
        assert driver_text().count(f"$script:{name}=") == 1, name
        assert driver_constant(name) == pin == sha(path), name
    # The wrapper and the history script pin the same bridge, support module and history file as the driver.
    wrapper = WRAPPER.read_text(encoding='utf-8')
    assert f"$script:bridgeHash='{sha(BRIDGE_PY)}'" in wrapper and f"$script:supportHash='{sha(STATUS_PY)}'" in wrapper
    assert f"$script:historyHash='{sha(HISTORY)}'" in wrapper
    assert f"bridge='{sha(BRIDGE_PY)}'" in HISTORY.read_text(encoding='utf-8') and f"support='{sha(STATUS_PY)}'" in HISTORY.read_text(encoding='utf-8')


def test_driver_imports_the_same_eighteen_history_functions_as_the_wrapper(tmp_path):
    wrapper = WRAPPER.read_text(encoding='utf-8')
    block = wrapper[wrapper.index('Import-PinnedFunctions $script:history $script:historyHash @('):]
    wrapper_names = re.findall(r"'([A-Za-z-]+)'", block[:block.index(')')])
    driver = driver_text()
    block = driver[driver.index('$script:agyHistoryFunctionNames=@('):]
    driver_names = re.findall(r"'([A-Za-z-]+)'", block[:block.index(')')])
    assert len(wrapper_names) == 18 and driver_names == wrapper_names
    code = functions(DRIVER) + (f"Set-SeriesConstants 'gemini' '{ATTEMPT}' '{W}' 'print';$names=@();"
                                "foreach($t in @(Get-AgyHistoryDefinitions)){$tk=$null;$er=$null;$ast=[Management.Automation.Language.Parser]::ParseInput($t,[ref]$tk,[ref]$er);"
                                "$names+=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$false))[0].Name};"
                                "'RESULT '+(ConvertTo-Json -InputObject $names -Compress)")
    assert result_of(ps(code, tmp_path)) == wrapper_names


def test_driver_scope_provides_every_command_the_history_script_calls(tmp_path):
    """Every command the pinned history functions call is defined there, imported by the driver, or a built-in cmdlet."""
    imported = COMMON_IMPORTS + ['Assert-FreshAgyLogin']
    code = (f"$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile('{HISTORY}',[ref]$t,[ref]$e);"
            "$defined=@($a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)|ForEach-Object{$_.Name});"
            "$called=@($a.FindAll({param($n)$n -is [Management.Automation.Language.CommandAst]},$true)|ForEach-Object{$_.GetCommandName()}|Where-Object{$_}|Sort-Object -Unique);"
            "$external=@($called|Where-Object{$_ -cnotin $defined});"
            "$cmdlets=@($external|Where-Object{$null -ne (Get-Command -Name $_ -CommandType Cmdlet -ErrorAction SilentlyContinue)});"
            "'RESULT '+(@{external=$external;cmdlets=$cmdlets}|ConvertTo-Json -Compress)")
    value = result_of(ps(code, tmp_path))
    functions_needed = sorted(set(value['external']) - set(value['cmdlets']))
    assert functions_needed == sorted(['Assert-NoReparseAncestors', 'Assert-ProtectedPath', 'Read-R3Control', 'Read-R3Text', 'Get-ExactTaskOrAbsent'])
    assert set(functions_needed) <= set(imported)
    # Read-R3Control adds each stream to the caller's $held list, which the driver's main scope creates first.
    main = function_text(DRIVER, 'Invoke-LoginSeriesMain', tmp_path)
    assert main.index('$held=[Collections.Generic.List[IO.FileStream]]::new()') < main.index('Get-AgyHistoryDefinitions')


@pytest.mark.parametrize('case', ['clean_slot', 'older_session', 'stray_task'])
def test_history_review_runs_through_the_driver_call_site_with_stubbed_system_calls(tmp_path, case):
    parent = tmp_path / 'cochem'
    parent.mkdir()
    if case == 'older_session':
        (parent / f'InteractiveAgy427-slot2-{"e" * 32}').mkdir()
    stray = f'CoChem-4.2.7-InteractiveAgy-r4-slot2-{"f" * 32}' if case == 'stray_task' else ''
    code = functions(DRIVER) + (
        f"Set-SeriesConstants 'gemini' '{ATTEMPT}' '{W}' 'print' -Base '{parent}'\n"
        "foreach($t in @(Get-SeriesHelperDefinitions 'gemini')){. ([scriptblock]::Create($t))}\n"
        "foreach($t in @(Get-AgyHistoryDefinitions)){. ([scriptblock]::Create($t))}\n"
        f"$script:calls=[Collections.Generic.List[string]]::new();$stray='{stray}';$parentPath='{parent}'\n" + r"""
      function Get-AgyHistoryParent {$parentPath}
      function Assert-NoReparseAncestors {param($Path)$script:calls.Add('reparse:'+$Path)}
      function Assert-ProtectedPath {param($Path)$script:calls.Add('protected:'+$Path)}
      function Read-R3Control {param($Path,$Hash,$Maximum)throw 'INERT: no receipt is read for this fixture'}
      function Read-R3Text {param($Control)throw 'INERT'}
      function Get-ExactTaskOrAbsent {param($Folder,$Name)$script:calls.Add('task:'+$Name);return $null}
      $folder=[pscustomobject]@{Stray=$stray}
      $folder|Add-Member ScriptMethod GetTasks {param($flags)$script:calls.Add('census:'+$flags);if($this.Stray){,@([pscustomobject]@{Name=$this.Stray})}else{,@()}}
      $held=[Collections.Generic.List[IO.FileStream]]::new()
      $script:taskFolder=$folder
      $script:runtime=[ordered]@{install_receipt_sha256='inert';source_manifest_sha256='inert';configuration_sha256='inert';revision=[ordered]@{source_sha256='inert'}}
      $m=$null;try{Assert-FreshAgyLogin 'slot2'}catch{$m=$_.Exception.Message}
      'RESULT '+([ordered]@{message=$m;calls=@($script:calls.ToArray())}|ConvertTo-Json -Compress)""")
    value = result_of(ps(code, tmp_path / 'scripts'))
    assert value['calls'][:2] == [f'reparse:{parent}', f'protected:{parent}']
    if case == 'clean_slot':
        assert value['message'] is None and value['calls'][2:] == ['census:1']
    elif case == 'older_session':
        assert value['message'] == 'An older non-r4 agy session remains outside this reviewed history; preserve it for diagnosis.'
        assert not any(c.startswith('census:') for c in value['calls'])
    else:
        assert value['message'] == 'An agy login task has no matching reviewed session root; preserve it for diagnosis.'


def test_reviewed_importer_is_byte_identical_and_reviewed_functions_are_not_redefined(tmp_path):
    importer = function_text(DRIVER, 'Import-ReviewedFunctions', tmp_path)
    assert importer == function_text(RETARGET, 'Import-ReviewedFunctions', tmp_path) == function_text(LEAF, 'Import-ReviewedFunctions', tmp_path)
    defined = set(re.findall(r'^function ([A-Za-z-]+)', driver_text(), re.M))
    assert not defined & set(COMMON_IMPORTS + CLAUDE_HISTORY_IMPORTS), defined & set(COMMON_IMPORTS)
    assert 'Invoke-SixStatusFirst' not in defined and 'Write-SeriesRecord' not in defined


def test_imported_function_set_by_hash_per_provider(tmp_path):
    code = functions(DRIVER) + (
        "$out=[ordered]@{};foreach($p in @('codex','claude','gemini')){Set-SeriesConstants $p '" + ATTEMPT + "' '" + str(W) + "' '';$names=@();"
        "foreach($t in @(Get-SeriesHelperDefinitions $p)){$tk=$null;$er=$null;$ast=[Management.Automation.Language.Parser]::ParseInput($t,[ref]$tk,[ref]$er);"
        "if($er.Count){throw 'parse'};$names+=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$false))[0].Name};$out[$p]=$names};"
        "'RESULT '+($out|ConvertTo-Json -Compress)")
    value = result_of(ps(code, tmp_path))
    assert value['codex'] == COMMON_IMPORTS and value['gemini'] == COMMON_IMPORTS
    assert value['claude'] == COMMON_IMPORTS + CLAUDE_HISTORY_IMPORTS


@pytest.mark.parametrize('change', ['byte', 'missing_name'])
def test_importer_refuses_a_changed_source_or_a_missing_definition(tmp_path, change):
    copy = tmp_path / 'series-copy.ps1'
    data = SERIES_V6.read_bytes()
    copy.write_bytes(data + (b' ' if change == 'byte' else b''))
    names = "@('Invoke-SixStatusFirst')" if change == 'byte' else "@('Invoke-SixStatusFirstR4')"
    code = functions(DRIVER) + (f"$m=$null;try{{$null=@(Import-ReviewedFunctions '{copy}' '{sha(SERIES_V6)}' {names})}}catch{{$m=$_.Exception.Message}};"
                                "'RESULT '+(@{message=$m}|ConvertTo-Json -Compress)")
    message = result_of(ps(code, tmp_path))['message']
    assert message and ('Reviewed function source changed' in message if change == 'byte' else 'Expected exactly one reviewed definition' in message)


def test_constants_bind_the_r4_namespaces(tmp_path):
    code = functions(DRIVER) + (
        "$out=[ordered]@{};foreach($p in @('codex','claude','gemini')){Set-SeriesConstants $p '" + ATTEMPT + "' '" + str(W) + "' '';"
        "$b=Get-StatusLeafNamespace 'slot6' 'after';$out[$p]=[ordered]@{series=$script:seriesRoot;install=$script:installRoot;native=$script:native;hash=$script:nativeHash;"
        "status_root=$b.root;status_task=$b.task;status_receipt=$b.receipt;status_helper=$b.helper;capture=$script:captureRoot;bridge_parent=$script:agyBridgeParent;"
        "bridge_prefix=$script:agyBridgeRootPrefix;wrapper=$script:agyBridgeWrapper;daemons=$script:daemonTaskNames;leaf=$script:statusLeaf;helper=$script:statusPython;"
        "accepted=$script:agyBridgeAcceptedStatuses;schema=$script:agyBridgeReceiptSchema;history_names=$script:agyHistoryFunctionNames;powershell=$script:powershell}};"
        "'RESULT '+($out|ConvertTo-Json -Compress -Depth 4)")
    value = result_of(ps(code, tmp_path))
    for provider, v in value.items():
        assert v['series'] == rf'{COCHEM}\NativeAuthSix4.2.7-windows-20261011-r4-v1-{ATTEMPT}-{provider}'
        assert v['install'] == str(status.INSTALL) and v['hash'] == status.CONTRACTS[provider]['sha256']
        assert v['native'] == str(status.NATIVE / status.NATIVE_EXECUTABLES[provider])
        assert v['status_root'] == rf'{COCHEM}\{status.ROOT_PREFIX}{ATTEMPT}-slot6-{provider}-after'
        assert v['status_task'] == f'CoChem-4.2.7-NativeAuthStatusSix-20261010-r4-v1-{ATTEMPT}-slot6-{provider}-after'
        assert v['status_receipt'] == v['status_root'] + r'\worker-native-status.json' and v['status_helper'] == v['status_root'] + '\\' + status.HELPER_NAME
        assert v['capture'] == rf'{COCHEM}\AgyCapture4.2.7-windows-20261010-r4-v1-{ATTEMPT}-slot1-signed-out'
        assert v['bridge_parent'] == COCHEM and v['bridge_prefix'] == 'InteractiveAgy427-r4-' and v['wrapper'] == str(W / WRAPPER_NAME)
        assert v['daemons'] == list(status.DAEMON_TASK_NAMES) and v['leaf'] == str(LEAF) and v['helper'] == str(STATUS_PY)
        assert v['accepted'] == ['LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED', 'LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED']
        assert v['schema'] == 'cochem-interactive-agy-login/1' and v['history_names'][-1] == 'Assert-ReviewedAgyHistory'
        assert v['powershell'] == r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'


def test_fresh_holds_check_the_series_root_and_all_twelve_status_targets(tmp_path):
    code = functions(DRIVER) + ("Set-SeriesConstants 'gemini' '" + ATTEMPT + "' '" + str(W) + r"""' 'print'
      $script:checks=[Collections.Generic.List[string]]::new()
      function Test-Path {param($LiteralPath,$ErrorAction,$PathType)$script:checks.Add($LiteralPath);return $LiteralPath -ceq $script:seriesRoot}
      function Get-ExactTaskOrAbsent {param($Folder,$Name)$script:checks.Add($Name);return $null}
      $holds=@(Get-SeriesFreshHolds $null)
      'RESULT '+([ordered]@{holds=$holds;checks=@($script:checks.ToArray())}|ConvertTo-Json -Compress)""")
    value = result_of(ps(code, tmp_path))
    assert len(value['holds']) == 1 and 'no automatic repeat or resume' in value['holds'][0]
    assert len(value['checks']) == 25
    for slot in SLOTS:
        for stage in ('before', 'after'):
            assert rf'{COCHEM}\{status.ROOT_PREFIX}{ATTEMPT}-{slot}-gemini-{stage}' in value['checks']
            assert f'CoChem-4.2.7-NativeAuthStatusSix-20261010-r4-v1-{ATTEMPT}-{slot}-gemini-{stage}' in value['checks']


def test_daemon_check_keeps_exactly_the_four_names(tmp_path):
    code = functions(DRIVER) + ("Set-SeriesConstants 'gemini' '" + ATTEMPT + "' '" + str(W) + "' 'print' -Base '" + str(tmp_path) + r"""'
      foreach($t in @(Get-SeriesHelperDefinitions 'gemini')){. ([scriptblock]::Create($t))}
      $script:asked=@()
      function New-InertFolder {param([string]$Active)
        $f=[pscustomobject]@{Active=$Active}
        $f|Add-Member ScriptMethod GetTask {param($name)$script:asked+=$name
          if($name -ceq $this.Active){$t=[pscustomobject]@{Enabled=$true;State=3};$t|Add-Member ScriptMethod GetInstances {param($x)[pscustomobject]@{Count=0}};return $t}
          if($name -ceq 'CoChem-4.2.7-Warden'){$t=[pscustomobject]@{Enabled=$false;State=1};$t|Add-Member ScriptMethod GetInstances {param($x)[pscustomobject]@{Count=0}};return $t}
          throw [Runtime.InteropServices.COMException]::new('absent',-2147024894)}
        $f}
      $clean=$true;try{Assert-SeriesDaemonsStopped (New-InertFolder '')}catch{$clean=$false}
      $firstAsked=@($script:asked);$script:asked=@()
      $refused=$false;try{Assert-SeriesDaemonsStopped (New-InertFolder 'CoChem-4.2.3-Supervisor')}catch{$refused=$true}
      $holds=@(Get-SeriesPreflightHolds (New-InertFolder 'CoChem-4.2.7-Warden') $null)
      'RESULT '+([ordered]@{clean=$clean;asked=$firstAsked;refused=$refused;holds=$holds;names=$script:daemonTaskNames}|ConvertTo-Json -Compress)""")
    value = result_of(ps(code, tmp_path))
    assert value['clean'] is True and value['refused'] is True
    assert value['asked'] == list(status.DAEMON_TASK_NAMES) == value['names']
    assert any(h.startswith('Protected daemons must remain stopped and disabled') for h in value['holds'])


APPLY_FACTS = {'edition': 'Desktop', 'is64': True, 'computer': 'AETHERDESK', 'identity': 'AETHERDESK\\ansac', 'administrator': True,
               'user_interactive': True, 'input_redirected': False, 'output_redirected': False, 'host_name': 'ConsoleHost'}
OWNER = 'Apply requires the owner at an elevated interactive ConsoleHost, with -Interactive and no redirected input/output.'
PLATFORM = 'Use 64-bit Windows PowerShell5.1 on AETHERDESK.'
REFUSAL_CASES = [
    ('owner_apply', {}, True, True, None), ('plan', {}, False, False, None), ('plan_non_interactive_token', {'user_interactive': False}, False, False, None),
    ('non_interactive_token', {'user_interactive': False}, True, True, OWNER), ('no_interactive_switch', {}, True, False, OWNER),
    ('not_administrator', {'administrator': False}, True, True, OWNER), ('other_identity', {'identity': 'AETHERDESK\\CoChem422Worker1'}, True, True, OWNER),
    ('input_redirected', {'input_redirected': True}, True, True, OWNER), ('output_redirected', {'output_redirected': True}, True, True, OWNER),
    ('ise_host', {'host_name': 'Windows PowerShell ISE Host'}, True, True, OWNER), ('x86', {'is64': False}, False, False, PLATFORM),
    ('core', {'edition': 'Core'}, True, True, PLATFORM), ('other_host', {'computer': 'OTHERDESK'}, False, False, PLATFORM)]


def test_apply_gate_refuses_every_non_owner_context_at_function_level(tmp_path):
    cases = tmp_path / 'cases.json'
    cases.write_text(json.dumps([{'name': n, 'facts': {**APPLY_FACTS, **c}, 'apply': a, 'interactive': i} for n, c, a, i, _ in REFUSAL_CASES]))
    code = functions(DRIVER) + (f"$out=[ordered]@{{}};$cases=[IO.File]::ReadAllText('{cases}')|ConvertFrom-Json;foreach($c in $cases){{"
                                "$out[[string]$c.name]=Get-SeriesApplyRefusal ([bool]$c.apply) ([bool]$c.interactive) $c.facts};'RESULT '+($out|ConvertTo-Json -Compress)")
    value = result_of(ps(code, tmp_path))
    assert value == {n: expected for n, _, _, _, expected in REFUSAL_CASES}


def test_login_mode_rules_at_function_level(tmp_path):
    rows = [('gemini', 'print', True, None), ('gemini', 'tui', False, None), ('gemini', '', False, None),
            ('gemini', '', True, 'Gemini -Apply requires -LoginMode'), ('gemini', 'none', False, '-LoginMode must be print or tui'),
            ('codex', 'print', False, '-LoginMode applies only to -Provider gemini'), ('claude', 'tui', True, '-LoginMode applies only to -Provider gemini'),
            ('codex', '', True, None)]
    code = functions(DRIVER) + "$out=@();" + ''.join(
        f"$out+=[string](Get-LoginModeRefusal '{p}' '{m}' ${str(a).lower()});" for p, m, a, _ in rows) + "'RESULT '+(ConvertTo-Json -InputObject $out -Compress)"
    value = result_of(ps(code, tmp_path))
    assert len(value) == len(rows)
    for (provider, mode, apply, expected), got in zip(rows, value):
        assert (got == '') if expected is None else got.startswith(expected), (provider, mode, apply, got)


@pytest.mark.parametrize('case,attempt,apply,interactive,provider,mode,facts,expected', [
    ('all_zero_apply', ZERO, True, True, 'gemini', 'print', {}, 'Apply forbids the all-zero preview attempt'),
    ('uppercase_attempt', 'A' * 32, False, False, 'gemini', 'print', {}, 'A lowercase32-hex Attempt is required'),
    ('non_interactive_token', ATTEMPT, True, True, 'gemini', 'print', {'user_interactive': False}, OWNER),
    ('redirected_output', ATTEMPT, True, True, 'gemini', 'print', {'output_redirected': True}, OWNER),
    ('no_interactive_switch', ATTEMPT, True, False, 'gemini', 'print', {}, OWNER),
    ('gemini_apply_without_mode', ATTEMPT, True, True, 'gemini', '', {}, 'Gemini -Apply requires -LoginMode'),
    ('codex_with_mode', ATTEMPT, False, False, 'codex', 'print', {}, '-LoginMode applies only to -Provider gemini'),
    ('plan_from_ordinary_token', ZERO, False, False, 'gemini', 'print', {'user_interactive': False, 'administrator': False, 'identity': 'x'}, 'SENTINEL')])
def test_main_refuses_before_any_constant_or_import(tmp_path, case, attempt, apply, interactive, provider, mode, facts, expected):
    facts_path = tmp_path / 'facts.json'
    facts_path.write_text(json.dumps({**APPLY_FACTS, **facts}))
    code = functions(DRIVER) + (
        "function Set-SeriesConstants {throw 'SENTINEL: constants reached'}"
        f"\nfunction Get-SeriesHostFacts {{[IO.File]::ReadAllText('{facts_path}')|ConvertFrom-Json}}\n"
        f"$m=$null;try{{Invoke-LoginSeriesMain -Provider '{provider}' -LoginMode '{mode}' -ApplyRequested ${str(apply).lower()} -InteractiveRequested ${str(interactive).lower()} "
        f"-Attempt '{attempt}' -ScriptRoot '{W}'}}catch{{$m=$_.Exception.Message}};'RESULT '+(@{{message=$m}}|ConvertTo-Json -Compress)")
    message = result_of(ps(code, tmp_path))['message']
    assert message and expected in message, message
    if expected != 'SENTINEL':
        assert 'SENTINEL' not in message


# ------------------------------------------------------------------------------------------- shared fixtures

def write_capture(base, attempt, mode='print', gate=True, held=False, summary_attempt=None, file_mode=None, tamper=False):
    root = base / f'AgyCapture4.2.7-windows-20261010-r4-v1-{attempt}-slot1-signed-out'
    root.mkdir(parents=True)
    decided = {'print': 'P3', 'tui': 'P6'}.get(file_mode or mode)
    raw = json.dumps({'schema': 'cochem-agy-login-mode/1', 'attempt': attempt, 'nonce': 'c' * 32, 'slot': 'slot1', 'stage': 'signed-out',
                      'mode': file_mode or mode, 'decided_by': decided, 'rule': 'fixture', 'evidence': {}, 'evidence_sha256': 'd' * 64},
                     sort_keys=True, indent=2).encode('ascii')
    (root / 'login-mode.json').write_bytes(raw)
    summary = {'schema': 'cochem-agy-status-capture-result/1', 'status': 'CAPTURE_COMPLETE', 'decision': 'COMPLETE', 'attempt': summary_attempt or attempt,
               'slot': 'slot1', 'stage': 'signed-out', 'nonce': 'c' * 32, 'gate': {'passed': gate, 'reasons': [] if gate else ['LOGIN_MODE_NONE']},
               'login_mode': {'mode': mode, 'decided_by': decided, 'sha256': '0' * 64 if tamper else hashlib.sha256(raw).hexdigest()}}
    (root / 'capture-summary.json').write_text(json.dumps(summary))
    if held:
        (root / 'capture-held.json').write_text('{}')
    return root


READ_STUBS = r"""
function Read-R3Control {param([string]$Path,[string]$Hash='',[long]$Maximum=16777216)
  if(Get-Command Add-Journal -ErrorAction SilentlyContinue){Add-Journal 'read' $Path}
  $length=(Get-Item -LiteralPath $Path -Force).Length;if($length -gt $Maximum){throw 'Bounded fixture length differs.'}
  $h=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant();if($Hash -and $h -cne $Hash){throw 'Fixture pin mismatch.'}
  [pscustomobject]@{Path=$Path;Sha256=$h;Length=$length}}
function Read-R3Text {param($Control)[IO.File]::ReadAllText($Control.Path)}
"""


@pytest.mark.parametrize('case', ['print', 'tui', 'mismatch', 'mode_none', 'gate_failed', 'held', 'other_attempt', 'tampered', 'absent'])
def test_login_mode_must_equal_the_signed_out_capture_of_the_same_attempt(tmp_path, case):
    base = tmp_path / 'cochem'
    base.mkdir()
    requested = {'tui': 'tui', 'mismatch': 'tui'}.get(case, 'print')
    if case != 'absent':
        write_capture(base, ATTEMPT, mode={'tui': 'tui', 'mode_none': 'none'}.get(case, 'print'), gate=case not in ('gate_failed', 'mode_none'), held=case == 'held',
                      summary_attempt='f' * 32 if case == 'other_attempt' else None, tamper=case == 'tampered')
    code = functions(DRIVER) + f"Set-SeriesConstants 'gemini' '{ATTEMPT}' '{W}' '{requested}' -Base '{base}'\n" + READ_STUBS + (
        f"$r=$null;$m=$null;try{{$r=Assert-AgyLoginModeBinding '{ATTEMPT}' '{requested}'}}catch{{$m=$_.Exception.Message}};"
        "'RESULT '+([ordered]@{binding=$r;message=$m}|ConvertTo-Json -Compress -Depth 4)")
    value = result_of(ps(code, tmp_path))
    if case in ('print', 'tui'):
        assert value['message'] is None and value['binding']['mode'] == case
        assert value['binding']['decided_by'] == {'print': 'P3', 'tui': 'P6'}[case]
        root = base / f'AgyCapture4.2.7-windows-20261010-r4-v1-{ATTEMPT}-slot1-signed-out'
        assert value['binding']['login_mode_sha256'] == sha(root / 'login-mode.json') and value['binding']['capture_summary_sha256'] == sha(root / 'capture-summary.json')
    else:
        assert value['binding'] is None and value['message']
        expected = {'mismatch': '-LoginMode tui differs from login-mode.json (print)', 'mode_none': 'did not pass its gate',
                    'gate_failed': 'did not pass its gate', 'held': 'is held', 'other_attempt': 'did not pass its gate',
                    'tampered': 'Fixture pin mismatch', 'absent': 'No signed-out AgyCapture exists'}[case]
        assert expected in value['message'], value['message']


def test_login_mode_none_with_a_passed_gate_is_still_refused(tmp_path):
    base = tmp_path / 'cochem'
    base.mkdir()
    write_capture(base, ATTEMPT, mode='none', gate=True)
    code = functions(DRIVER) + f"Set-SeriesConstants 'gemini' '{ATTEMPT}' '{W}' 'print' -Base '{base}'\n" + READ_STUBS + (
        f"$m=$null;try{{$null=Assert-AgyLoginModeBinding '{ATTEMPT}' 'print'}}catch{{$m=$_.Exception.Message}};'RESULT '+(@{{message=$m}}|ConvertTo-Json -Compress)")
    assert 'decided mode none' in result_of(ps(code, tmp_path))['message']


def test_pause_marker_classes_are_reported_without_text(tmp_path):
    rows = [('Please verify it is you before continuing', ['verification_present']), ('Identity   verification\r\n required', ['verification_present']),
            ('We noticed unusual\nactivity on this account', ['unusual_activity_present']), ('You can submit an appeal', ['appeal_present']),
            ('Error 429: Too Many Requests', ['rate_limit_present']), ('rate limit exceeded; try again later', ['rate_limit_present']),
            ('RESOURCE_EXHAUSTED quota exceeded', ['rate_limit_present']),
            ('Verify your account or appeal: rate-limited', ['rate_limit_present', 'verification_present', 'appeal_present']),
            # The bridge's word boundaries: no pause on these benign forms.
            ('Verifying...', []), ('Verifying your session', []), ('Verification code sent', []), ('reverify', []), ('appealing design', []),
            # The lead's must-pause list.
            ('Please verify your identity', ['verification_present']), ('Rate limit reached', ['rate_limit_present']), ('RESOURCE_EXHAUSTED', ['rate_limit_present']),
            ('unusual activity detected', ['unusual_activity_present']), ('You can appeal this decision', ['appeal_present']), ('too many requests', ['rate_limit_present']),
            # The bridge's O-F8 forms: separators become spaces, ratelimit without a space, and a standalone 429.
            ('Error: RESOURCE_EXHAUSTED: per-user quota', ['rate_limit_present']), ('oauth2: 429 ratelimit', ['rate_limit_present']),
            ('rate-limited, retry in 60s', ['rate_limit_present']), ('TOO_MANY_REQUESTS', ['rate_limit_present']), ('Resource-Exhausted', ['rate_limit_present']),
            ('HTTP 429', ['rate_limit_present']), ('status (429)', ['rate_limit_present']), ('"429"', ['rate_limit_present']), ('code 429.', ['rate_limit_present']),
            ('id 14290', []), ('code=4291', []), ('port 4290 open', []), ('x429y', []), ('pre-verify', ['verification_present']),
            (NEUTRAL_LOG, [])]
    path = tmp_path / 'rows.json'
    path.write_text(json.dumps([r[0] for r in rows]))
    code = functions(DRIVER) + (f"Set-SeriesConstants 'gemini' '{ATTEMPT}' '{W}' 'print';$out=@();"
                                f"$texts=[IO.File]::ReadAllText('{path}')|ConvertFrom-Json;foreach($t in $texts){{$out+=(@(Get-PauseMarkerClasses $t) -join ',')}};"
                                "'RESULT '+(ConvertTo-Json -InputObject $out -Compress)")
    value = result_of(ps(code, tmp_path))
    assert value == [','.join(r[1]) for r in rows]
    # The same pause classes as the bridge's own before-input classifier on every row (same patterns, same normalisation).
    bridge = load(BRIDGE_PY, 'worker_agy_login_bridge_r4_v1_for_series')
    for text, _ in rows:
        markers = bridge.classify_markers(text, after_input=False)
        assert ','.join(name for name in bridge.PAUSE_MARKERS if markers[name]) == value[[r[0] for r in rows].index(text)], text


def test_pause_patterns_are_exactly_the_bridge_before_patterns():
    bridge_text = BRIDGE_PY.read_text(encoding='utf-8')
    driver = driver_text()
    block = driver[driver.index('$script:pauseMarkers=[ordered]@{'):]
    block = block[:block.index("'}") + 2]
    driver_patterns = dict(re.findall(r"(\w+)='([^']*)'", block))
    pause_names = re.search(r"PAUSE_MARKERS = \(([^)]*)\)", bridge_text).group(1)
    names = re.findall(r"'(\w+)'", pause_names)
    assert list(driver_patterns) == names == ['rate_limit_present', 'verification_present', 'appeal_present', 'unusual_activity_present']
    for name in names:
        bridge_pattern = re.search(r"'" + name + r"': r'([^']*)',", bridge_text).group(1)
        assert driver_patterns[name] == bridge_pattern, name
    assert "_WHITESPACE = re.compile(r'\\s+')" in bridge_text and "folded = _WHITESPACE.sub(' ', text).casefold()" in bridge_text
    # O-F8: the bridge replaces '-'/'_' with a space before it collapses whitespace; the driver does the same, in the same order.
    assert "_MARKER_SEPARATORS = re.compile('[-_]')" in bridge_text
    classify = bridge_text[bridge_text.index('def classify_markers('):]
    assert classify.index("text = _MARKER_SEPARATORS.sub(' ', text)") < classify.index("folded = _WHITESPACE.sub(' ', text).casefold()")
    assert "$folded=[regex]::Replace([regex]::Replace([string]$Text,'[-_]',' '),'\\s+',' ').ToLowerInvariant()" in driver


def test_runtime_binding_failures_become_holds_not_actions(tmp_path):
    code = functions(DRIVER) + (f"Set-SeriesConstants 'claude' '{ATTEMPT}' '{W}' '' -Base '{tmp_path}'\n" + r"""
      function Assert-R4InstalledBindings {throw 'inert r4 receipt differs'}
      function Assert-R3InstalledBindings {throw 'inert r3 receipt differs'}
      $b=Get-SeriesRuntimeBindings 'claude'
      'RESULT '+([ordered]@{runtime=$b.runtime;layout=$b.layout;holds=@($b.holds)}|ConvertTo-Json -Compress)""")
    value = result_of(ps(code, tmp_path))
    assert value['runtime'] is None and value['layout'] is None
    assert value['holds'] == ['r4 stopped runtime is not the reviewed build: inert r4 receipt differs',
                              'r3 runtime of the Claude login child is not the reviewed build: inert r3 receipt differs']


# ----------------------------------------------------------------- status leaf contract (child binding)

def status_receipt(kind):
    raw = {'reuse': (json.dumps({'status': 'SUCCESS', 'command': {'name': 'models', 'data': {'models': [{'id': 'gemini-3.8-flash-high', 'label': 'Gemini 3.8 Flash (High)'}]}}}).encode(), b'Fetching available models...\n', 0),
           'missing': (b'', b'Please sign in to view available models. Launch the CLI without arguments to sign in.\n', 1),
           'hold': (b'', b'Fetching available models...\n', 0)}.get(kind, (b'', b'', 0))
    a = status.parse_status('gemini', *raw)
    value = {'schema': 'cochem-worker-native-auth-status/1', 'attempt': ATTEMPT, 'nonce': 'b' * 32, 'stage': 'before', 'slot': 'slot1', 'provider': 'gemini',
             'system_sid': 'S-1-5-18', 'helper_sha256': sha(STATUS_PY), 'runtime_root': str(status.INSTALL),
             'install_receipt_sha256': status.INSTALL_RECEIPT_SHA256, 'source_manifest_sha256': status.MANIFEST_SHA256, 'resource_limits_sha256': status.RESOURCE_SHA256,
             'status': 'NATIVE_SUBSCRIPTION_AUTHENTICATION_VERIFIED' if a['native_subscription_authentication_verified'] else 'AUTHENTICATION_NOT_VERIFIED',
             'config_sha256': status.CONFIG_SHA256, 'layout_sha256': status.LAYOUT_SHA256, 'revision': {'verified': True, 'source_sha256': status.REVISION_SHA256},
             'cleanup_verified': True, 'runtime_custody_verified': True, 'daemon_states_verified_before_and_after': True, 'native_model_jobs_executed': 0,
             'login_commands_executed': 0, 'process': {'token_matches_selected_worker': True, 'image_matches_reviewed_executable': True, 'owned_job_membership_verified': True},
             'native_executable_sha256_before': status.CONTRACTS['gemini']['sha256'], 'native_executable_sha256_after': status.CONTRACTS['gemini']['sha256'],
             'native_status_commands_executed': 1, 'native_exit_code': raw[2], 'authentication': a, 'decision': status.authentication_decision(a)}
    if kind in ('failed', 'double_summary'):
        for key in ('authentication', 'native_exit_code'):
            value.pop(key)
        value.update(status='STATUS_CHECK_FAILED', decision='HOLD', cleanup_verified=False, native_exit_code=2,
                     failure={'phase': 'native_launch', 'error_type': 'WindowsIsolationError', 'winerror': 5, 'message': 'secret-receipt-output owner@example.invalid'})
    return value


STATUS_CASES = [('reuse', 0, 0), ('missing', 0, 0), ('failed', 1, 2), ('wrong_task', 0, 0), ('wrong_receipt_hash', 0, 0), ('double_summary', 1, 2),
                ('hold_exit2', 1, 2), ('hold_exit0', 1, 0), ('wrong_namespace', 0, 0)]


@pytest.mark.parametrize('kind,leaf_exit,task_result', STATUS_CASES)
def test_status_child_binds_the_r4_task_and_receipt_and_projects_only_safe_failure(tmp_path, kind, leaf_exit, task_result):
    receipt_kind = {'hold_exit2': 'hold', 'hold_exit0': 'hold'}.get(kind, kind if kind in ('missing', 'failed', 'double_summary') else 'reuse')
    value = status_receipt(receipt_kind)
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps(value))
    decision = value['decision']
    root = rf'{COCHEM}\{status.ROOT_PREFIX}{ATTEMPT}-slot1-gemini-before'
    path = root + r'\worker-native-status.json'
    if kind == 'wrong_namespace':
        path = rf'{COCHEM}\NativeAuthStatusSix4.2.7-windows-20261008-r3-v3-{ATTEMPT}-slot1-gemini-before\worker-native-status.json'
    summary = {'schema': 'cochem-worker-native-auth-status-task-result/1', 'attempt': ATTEMPT, 'slot': 'slot1', 'provider': 'gemini', 'stage': 'before',
               'nonce': 'b' * 32, 'receipt_sha256': '0' * 64 if kind == 'wrong_receipt_hash' else sha(receipt), 'receipt_path': path,
               'decision': decision, 'secret': 'do-not-forward'}
    lines = []
    if leaf_exit:
        lines = ['untrusted provider stderr owner@example.invalid', 'COCHEM_NATIVE_AUTH_STATUS_RESULT ' + json.dumps(summary)]
        if kind == 'double_summary':
            lines.append(lines[-1])
    else:
        lines = [json.dumps(summary)]
    leaf_out = tmp_path / 'leaf-out.txt'
    leaf_out.write_text('\n'.join(lines))
    code = functions(DRIVER) + f"Set-SeriesConstants 'gemini' '{ATTEMPT}' '{W}' 'print'\n" + (
        "foreach($t in @(Get-SeriesHelperDefinitions 'gemini')){. ([scriptblock]::Create($t))}\n"
        f"$script:runtime=[pscustomobject]@{{install_receipt_sha256='{status.INSTALL_RECEIPT_SHA256}';source_manifest_sha256='{status.MANIFEST_SHA256}';"
        f"configuration_sha256='{status.CONFIG_SHA256}';revision=[pscustomobject]@{{verified=$true;source_sha256='{status.REVISION_SHA256}'}}}};$script:taskFolder=$null;$script:lastStatusHold=$null\n"
        f"$fixtureReceipt='{receipt}';$fixturePython='{STATUS_PY}';$leafOut='{leaf_out}';$leafExit={leaf_exit};$taskResult={task_result};$kind='{kind}'\n" + r"""
      function Invoke-StatusLeafProcess {param($Slot,$Stage)[pscustomobject]@{text=[IO.File]::ReadAllText($leafOut);code=$leafExit}}
      function Get-ExactTaskOrAbsent {param($Folder,$Name)
        $ns=Get-StatusLeafNamespace 'slot1' 'before'
        if($Name -cne $ns.task){throw 'unexpected task name'}
        $action=[pscustomobject]@{Path=(Join-Path $script:installRoot '.venv\Scripts\python.exe');Arguments=('-I -B "'+$ns.helper+'" --slot slot1 --provider gemini --nonce '+('b'*32)+' --stage before --attempt '+$script:Attempt);WorkingDirectory=$ns.root}
        if($kind -ceq 'wrong_task'){$action.Arguments+=' --bad'}
        $actions=[pscustomobject]@{Count=1;Action=$action};$actions|Add-Member ScriptMethod Item {param($i)$this.Action}
        $t=[pscustomobject]@{State=3;LastTaskResult=$taskResult;Definition=[pscustomobject]@{Principal=[pscustomobject]@{UserId='SYSTEM';LogonType=5;RunLevel=1};Triggers=[pscustomobject]@{Count=0};Actions=$actions;Settings=[pscustomobject]@{MultipleInstances=2;ExecutionTimeLimit='PT3M'}}}
        $t|Add-Member ScriptMethod GetInstances {param($f)[pscustomobject]@{Count=0}};$t}
      function Read-R3Control {param($Path,$Hash,$Maximum=16777216)
        $p=$(if($Path.EndsWith('.py')){$fixturePython}else{$fixtureReceipt})
        $h=(Get-FileHash -LiteralPath $p).Hash.ToLowerInvariant()
        if($h -cne $Hash -or (Get-Item -LiteralPath $p).Length -gt $Maximum){throw 'Fixture pin mismatch'}
        [pscustomobject]@{Path=$p;Sha256=$h}}
      function Read-R3Text {param($Control)[IO.File]::ReadAllText($Control.Path)}
      $rejected=$false;$decision=$null;$message=$null
      try{$decision=(Invoke-AuthStatusChild 'slot1' 'before').decision}catch{$rejected=$true;$message=$_.Exception.Message}
      'RESULT '+([ordered]@{rejected=$rejected;decision=$decision;message=$message;hold=$script:lastStatusHold}|ConvertTo-Json -Compress -Depth 4)""")
    run = ps(code, tmp_path)
    result = result_of(run)
    accepted = kind in ('reuse', 'missing')
    assert result['rejected'] is (not accepted), result
    if accepted:
        assert result['decision'] == {'reuse': 'REUSE_VERIFIED_SESSION', 'missing': 'ATTENDED_LOGIN_REQUIRED'}[kind]
    tagged = [line for line in run.stdout.splitlines() if line.startswith('COCHEM_NATIVE_AUTH_STATUS_RESULT ')]
    assert len(tagged) == int(kind in ('failed', 'hold_exit2'))
    for secret in ('owner@example', 'secret-receipt', 'do-not-forward'):
        assert secret not in run.stdout
    if tagged:
        safe = json.loads(tagged[0].split(' ', 1)[1])
        assert safe['decision'] == 'HOLD' and safe['receipt_sha256'] == sha(receipt) and safe['last_task_result'] == 2
        assert result['hold']['decision'] == 'HOLD' and result['message'].startswith('Native status did not establish reuse or explicit logout.')
        if kind == 'failed':
            assert safe['failure'] == {'phase': 'native_launch', 'error_type': 'WindowsIsolationError', 'winerror': 5} and safe['native_exit_code'] == 2
    if kind == 'hold_exit0':
        assert result['message'] == 'A HOLD status receipt requires task result 2.'


def test_status_child_reaches_the_task_result_view_with_the_real_leaf_hold_output(tmp_path):
    """O-F5 end to end: the real onboarding-fix leaf (its Invoke-AuthStatusApply driven by its own test module's inert
    stubs) ends a gemini HOLD with task result 2 by printing exactly one COCHEM_NATIVE_AUTH_STATUS_RESULT line. The
    driver's Invoke-AuthStatusChild accepts that line, rebinds the receipt with Assert-AuthStatusReceipt imported by
    hash from the pinned leaf through Get-StatusTaskResultView (HOLD, task result 2), and projects a safe HOLD."""
    leaf_tests = load(LEAF_TESTS, 'leaf_fixtures_for_series')
    assert leaf_tests.ATTEMPT == ATTEMPT
    base = tmp_path / 'cochem'
    base.mkdir()
    value, leaf_stdout = leaf_tests.drive_apply(base, 'hold', leaf_tests.receipt_fixture('gemini', b'', leaf_tests.FETCH, 0), last_result=2)
    root = Path(value['root'])
    assert root.parent == base and value['summary'] is None and value['message'].startswith('Status is not an established subscription')
    tagged = [line for line in leaf_stdout.splitlines() if line.startswith('COCHEM_NATIVE_AUTH_STATUS_RESULT ')]
    assert len(tagged) == 1
    summary = json.loads(tagged[0].split(' ', 1)[1])
    assert summary['decision'] == 'HOLD' and summary['last_task_result'] == 2 and summary['receipt_path'] == str(root / 'worker-native-status.json')
    leaf_out = tmp_path / 'leaf-out.txt'
    leaf_out.write_text('\n'.join([line for line in leaf_stdout.splitlines() if not line.startswith('RESULT ')] + [value['message']]))
    code = functions(DRIVER) + f"Set-SeriesConstants 'gemini' '{ATTEMPT}' '{W}' 'print' -Base '{base}'\n" + (
        "foreach($t in @(Get-SeriesHelperDefinitions 'gemini')){. ([scriptblock]::Create($t))}\n"
        f"$script:runtime=[pscustomobject]@{{install_receipt_sha256='{status.INSTALL_RECEIPT_SHA256}';source_manifest_sha256='{status.MANIFEST_SHA256}';"
        f"configuration_sha256='{status.CONFIG_SHA256}';revision=[pscustomobject]@{{verified=$true;source_sha256='{status.REVISION_SHA256}'}}}};$script:taskFolder=$null;$script:lastStatusHold=$null\n"
        f"$leafOut='{leaf_out}';$leafNonce='{summary['nonce']}'\n" + r"""
      $script:viewCalls=@();$script:originalView=${function:Get-StatusTaskResultView}
      function Get-StatusTaskResultView {param($Receipt,$Task)
        $script:viewCalls+=,([ordered]@{status=$Receipt.status;decision=$Receipt.decision;task_result=$Task.LastTaskResult});& $script:originalView $Receipt $Task}
      function Invoke-StatusLeafProcess {param($Slot,$Stage)[pscustomobject]@{text=[IO.File]::ReadAllText($leafOut);code=1}}
      function Get-ExactTaskOrAbsent {param($Folder,$Name)
        $ns=Get-StatusLeafNamespace 'slot1' 'before'
        if($Name -cne $ns.task){throw 'unexpected task name'}
        $action=[pscustomobject]@{Path=(Join-Path $script:installRoot '.venv\Scripts\python.exe');Arguments=('-I -B "'+$ns.helper+'" --slot slot1 --provider gemini --nonce '+$leafNonce+' --stage before --attempt '+$script:Attempt);WorkingDirectory=$ns.root}
        $actions=[pscustomobject]@{Count=1;Action=$action};$actions|Add-Member ScriptMethod Item {param($i)$this.Action}
        $t=[pscustomobject]@{State=3;LastTaskResult=2;Definition=[pscustomobject]@{Principal=[pscustomobject]@{UserId='SYSTEM';LogonType=5;RunLevel=1};Triggers=[pscustomobject]@{Count=0};Actions=$actions;Settings=[pscustomobject]@{MultipleInstances=2;ExecutionTimeLimit='PT3M'}}}
        $t|Add-Member ScriptMethod GetInstances {param($f)[pscustomobject]@{Count=0}};$t}
      function Read-R3Control {param($Path,$Hash,$Maximum=16777216)
        $h=(Get-FileHash -LiteralPath $Path).Hash.ToLowerInvariant()
        if(($Hash -and $h -cne $Hash) -or (Get-Item -LiteralPath $Path).Length -gt $Maximum){throw 'Fixture pin mismatch'}
        [pscustomobject]@{Path=$Path;Sha256=$h}}
      function Read-R3Text {param($Control)[IO.File]::ReadAllText($Control.Path)}
      $rejected=$false;$message=$null
      try{$null=Invoke-AuthStatusChild 'slot1' 'before'}catch{$rejected=$true;$message=$_.Exception.Message}
      'RESULT '+([ordered]@{rejected=$rejected;message=$message;hold=$script:lastStatusHold;view_calls=@($script:viewCalls)}|ConvertTo-Json -Compress -Depth 5)""")
    run = ps(code, tmp_path)
    result = result_of(run)
    assert result['rejected'] is True and result['message'].startswith('Native status did not establish reuse or explicit logout.'), result
    assert result['view_calls'] == [{'status': 'AUTHENTICATION_NOT_VERIFIED', 'decision': 'HOLD', 'task_result': 2}]
    hold = result['hold']
    assert hold['decision'] == 'HOLD' and hold['last_task_result'] == 2 and hold['nonce'] == summary['nonce']
    assert hold['receipt_sha256'] == sha(root / 'worker-native-status.json') == summary['receipt_sha256']
    driver_tagged = [line for line in run.stdout.splitlines() if line.startswith('COCHEM_NATIVE_AUTH_STATUS_RESULT ')]
    assert len(driver_tagged) == 1 and json.loads(driver_tagged[0].split(' ', 1)[1]) == hold
    assert 'owner@example.invalid' not in run.stdout


# ---------------------------------------------------------------------------- Invoke-LoginSeriesMain harness

HARNESS = r"""
$fixture='@@F@@';$journalPath='@@J@@';$W='@@W@@'
$scenario=[IO.File]::ReadAllText('@@S@@')|ConvertFrom-Json
$fx=[IO.File]::ReadAllText('@@X@@')|ConvertFrom-Json
function Add-Journal {param([string]$Kind,$Value)[IO.File]::AppendAllText($journalPath,($Kind+' '+(ConvertTo-Json -InputObject $Value -Compress -Depth 8))+"`n")}
@@FUNCTIONS@@
Set-SeriesConstants '@@P@@' '@@A@@' $W '@@M@@'
foreach($t in @(Get-SeriesHelperDefinitions '@@P@@')){. ([scriptblock]::Create($t))}
$realSet=${function:Set-SeriesConstants}
function Set-SeriesConstants {
  param([string]$Provider,[string]$Attempt,[string]$ScriptRoot,[string]$LoginMode)
  & $realSet -Provider $Provider -Attempt $Attempt -ScriptRoot $ScriptRoot -LoginMode $LoginMode -Base $fixture
  $script:powershell=(Join-Path $fixture 'inert-powershell-never-run.exe')
  if(-not $fx.real_bridge){$script:agyBridgeWrapper=$fx.wrapper;$script:agyBridgeWrapperPin=$fx.wrapper_sha;$script:agyBridgePython=$fx.bridge;$script:agyBridgePythonPin=$fx.bridge_sha;$script:agyHistory=$fx.history;$script:agyHistoryPin=$fx.history_sha}
  $script:nativeHash=$fx.native_sha;$script:codexHelperPin=$fx.codex_sha
  Add-Journal 'constants' $Provider
}
function Get-SeriesHelperDefinitions {param($Provider)}
if(-not $fx.real_history){function Get-AgyHistoryDefinitions {}}
function Initialize-FileIdentity {}
function Get-SeriesHostFacts {[pscustomobject]@{edition='Desktop';is64=$true;computer='AETHERDESK';identity='AETHERDESK\ansac';administrator=$true;user_interactive=$true;input_redirected=$false;output_redirected=$false;host_name='ConsoleHost'}}
$fixtureRuntime=[ordered]@{install_receipt_sha256='@@IR@@';source_manifest_sha256='@@MS@@';configuration_sha256='@@CS@@';revision=[ordered]@{verified=$true;source_sha256='@@RS@@'}}
function Get-SeriesRuntimeBindings {param($Provider)Add-Journal 'runtime' $Provider;[pscustomobject]@{runtime=$fixtureRuntime;claude_runtime=[ordered]@{fixture='r3'};layout=[pscustomobject]@{fixture=$true};holds=@()}}
function Get-SeriesTaskFolder {Add-Journal 'folder' 1;[pscustomobject]@{fixture='inert-task-folder'}}
function Assert-SeriesDaemonsStopped {param($Folder)Add-Journal 'daemons' 1;if($scenario.daemons_active){throw 'Protected daemons must remain stopped and disabled.'}}
function Get-SeriesWorkerRootHolds {param($Layout)}
function Get-ExactTaskOrAbsent {param($Folder,$Name)Add-Journal 'task' $Name;return $null}
function Assert-ProtectedPath {param($Path)}
function Assert-CodeTreeOnce {param($Path)Add-Journal 'codetree' $Path;1}
function Open-VerifiedFile {param([string]$Path,[string]$Sha256,[long]$Length)
  Add-Journal 'held' $Path
  if((Get-Item -LiteralPath $Path).Length -ne $Length -or (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Sha256){throw 'Inert fixture content drift'}
  ,[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)}
@@READ_STUBS@@
function New-PrivateAcl {param([switch]$Directory)
  $a=[Security.AccessControl.FileSecurity]::new();$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User;$a.SetOwner($sid);$a.SetAccessRuleProtection($true,$false)
  $a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','Allow'));$a}
function Assert-SeriesPrivateRoot {param($Path)if(-not [IO.Directory]::Exists($Path)){throw 'fixture directory absent'}}
function New-SeriesRoot {param([string]$Path)Add-Journal 'series_root' $Path;if(Test-Path -LiteralPath $Path){throw 'Series root exists.'};$null=[IO.Directory]::CreateDirectory($Path)}
function Assert-ReviewedAgyHistory {param($Slot,$Folder,$Runtime)Add-Journal 'agy_history' $Slot;if($null -eq $Runtime -or $null -eq $Folder){throw 'history inputs missing'}}
function Assert-ReviewedClaudeHistory {param($Slot,$Folder,$Runtime)Add-Journal 'claude_history' $Slot}
function Start-Process {throw 'INERT: no process may be started by a fixture.'}
function Invoke-StatusLeafProcess {param($Slot,$Stage)throw 'INERT: the status leaf is never run by a fixture.'}
$script:answers=[Collections.Generic.Queue[string]]::new();foreach($fixtureAnswer in @($scenario.answers)){$script:answers.Enqueue([string]$fixtureAnswer)}
function Read-Host {param([Parameter(Position=0)]$Prompt)Add-Journal 'prompt' ([string]$Prompt);if($script:answers.Count){$script:answers.Dequeue()}else{'READY'}}
function Invoke-AuthStatusChild {param([string]$Slot,[string]$Stage)
  Add-Journal 'status' "$Slot|$Stage"
  $p=$scenario.status.PSObject.Properties["$Slot|$Stage"];$d=$(if($null -ne $p){[string]$p.Value}else{'REUSE_VERIFIED_SESSION'})
  if($d -ceq 'HOLD'){$script:lastStatusHold=[ordered]@{decision='HOLD';status='AUTHENTICATION_NOT_VERIFIED'};throw 'Native status did not establish reuse or explicit logout (inert).'}
  [pscustomobject]@{decision=$d;stage=$Stage;receipt_path=(Join-Path $fixture "status-$Slot-$Stage.json");receipt_sha256=('a'*64)}}
function Invoke-SeriesConsoleChild {param([string[]]$Arguments)
  Add-Journal 'child' @($Arguments)
  $slot=$Arguments[[Array]::IndexOf($Arguments,'-Slot')+1]
  $cfg=$scenario.bridge.PSObject.Properties[$slot]
  if($null -eq $cfg){return 0}
  $c=$cfg.Value
  if($c.root){
    $nonce=[Guid]::NewGuid().ToString('N');$root=Join-Path $fixture ('InteractiveAgy427-r4-'+$slot+'-'+$nonce);$null=[IO.Directory]::CreateDirectory($root)
    if($null -ne $c.log){[IO.File]::WriteAllText((Join-Path $root 'operator.log'),[string]$c.log)}
    $receiptSha=$null
    if($null -ne $c.status){
      $receiptPath=Join-Path $root 'receipt.json'
      [IO.File]::WriteAllText($receiptPath,([ordered]@{schema=$c.schema;slot=$slot;nonce=$nonce;status=$c.status;login_mode=$c.login_mode;cleanup_verified=$c.cleanup;pause_marker_seen=[bool]$c.pause_seen;account_line='authenticated as owner@example.invalid';code='SECRETCODE456'}|ConvertTo-Json))
      $receiptSha=(Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash.ToLowerInvariant()}
    if($null -ne $c.result){
      # Shape of the wrapper's session-result.json (Invoke-AgyLoginApply), with one field changed per variant.
      $r=[ordered]@{schema='cochem-interactive-agy-login-result/1';runtime_root='inert';slot=$slot;nonce=$nonce;login_mode=$c.login_mode;status=$c.status;
        classification='TERMINAL_NATIVE_LOGIN_CLEANUP_VERIFIED';outcome=$(if([int]$c.exit -eq 20){'PAUSED_RATE_LIMIT_OR_IDENTITY_VERIFICATION'}else{'LOGIN_ENDED_STATUS_REQUIRED'});
        exit_code=[int]$c.exit;message='inert SECRETCODE456 owner@example.invalid';pause_marker_seen=[bool]$c.pause_seen;cleanup_verified=$true;session_root=$root;
        receipt_path=(Join-Path $root 'receipt.json');receipt_sha256=$receiptSha;authentication_verified=$false;model_jobs_executed=0;activation_ready=$false}
      switch([string]$c.result){'slot_mismatch'{$r.slot='slot6'}'nonce_mismatch'{$r.nonce=('f'*32)}'receipt_mismatch'{$r.receipt_sha256=('0'*64)}'schema_wrong'{$r.schema='cochem-interactive-agy-login-held/1'}'outcome_wrong'{$r.outcome='LOGIN_NOT_COMPLETED'}}
      [IO.File]::WriteAllText((Join-Path $root 'session-result.json'),($r|ConvertTo-Json))}
    if($c.held){[IO.File]::WriteAllText((Join-Path $root 'session-held.json'),([ordered]@{schema='cochem-interactive-agy-login-held/1';slot=$slot;nonce=$nonce;reason='inert owner@example.invalid'}|ConvertTo-Json))}
  }
  [int]$c.exit}
$out=$null;$err=$null
try{$out=(@(Invoke-LoginSeriesMain -Provider '@@P@@' -LoginMode '@@M@@' -ApplyRequested $@@APPLY@@ -InteractiveRequested $true -Attempt '@@A@@' -ScriptRoot $W)|ForEach-Object{[string]$_}) -join "`n"}catch{$err=$_.Exception.Message}
Add-Journal 'end' ([ordered]@{out=$out;error=$err})
"""


def bridge(exit=0, status_value='LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED', log=NEUTRAL_LOG, root=True, login_mode='print', cleanup=True,
           schema='cochem-interactive-agy-login/1', pause_seen=False, result='default', held=None):
    """One simulated wrapper run. As the final wrapper: exit 0 and 20 leave session-result.json, exit 1 session-held.json."""
    if result == 'default':
        result = 'ok' if exit in (0, 20) else None
    if held is None:
        held = exit not in (0, 20)
    return {'exit': exit, 'status': status_value, 'log': log, 'root': root, 'login_mode': login_mode, 'cleanup': cleanup, 'schema': schema,
            'pause_seen': pause_seen, 'result': result, 'held': held}


class Series:
    def __init__(self, tmp_path, run, base, attempt, provider):
        self.run, self.base, self.attempt, self.provider = run, base, attempt, provider
        self.events = []
        journal = tmp_path / 'journal.txt'
        if journal.exists():
            for line in journal.read_text(encoding='utf-8').splitlines():
                kind, _, value = line.partition(' ')
                self.events.append((kind, json.loads(value)))
        self.root = base / f'NativeAuthSix4.2.7-windows-20261011-r4-v1-{attempt}-{provider}'

    def kinds(self, *names):
        return [(k, v) for k, v in self.events if k in names]

    def values(self, name):
        return [v for k, v in self.events if k == name]

    @property
    def end(self):
        ends = self.values('end')
        return ends[-1] if ends else None

    def record(self, name):
        return json.loads((self.root / name).read_text(encoding='utf-8'))

    def files(self):
        return sorted(p.name for p in self.root.iterdir()) if self.root.exists() else []


def run_series(tmp_path, status_table=None, bridges=None, answers=(), provider='gemini', mode='print', attempt=ATTEMPT, apply=True,
               real_bridge=False, real_history=False, capture=True, capture_mode=None, daemons_active=False, existing_root=False, wrong_wrapper_pin=False):
    base = tmp_path / 'cochem'
    base.mkdir()
    review = tmp_path / 'review'
    review.mkdir()
    fx = {'real_bridge': real_bridge, 'real_history': real_history}
    for key, name in (('wrapper', WRAPPER_NAME), ('bridge', 'worker_agy_login_bridge_r4_v1.py'), ('history', 'agy-session-history-r4-v1.ps1')):
        path = review / name
        path.write_bytes(f'# inert {key} fixture\n'.encode())
        fx[key], fx[key + '_sha'] = str(path), sha(path)
    if wrong_wrapper_pin:
        fx['wrapper_sha'] = FINAL_BRIDGE_PINS['agyBridgeWrapperPin'][1]
    native = base / 'Native4.2.7-windows-20261006' / status.NATIVE_EXECUTABLES[provider]
    native.parent.mkdir(parents=True)
    native.write_bytes(b'MZ inert native fixture')
    fx['native_sha'] = sha(native)
    codex = base / 'InstallGuard4.2.7-windows-20261006' / 'repository' / 'scripts' / 'login_pipeline_worker.ps1'
    codex.parent.mkdir(parents=True)
    codex.write_bytes(b'# inert codex child fixture\n')
    fx['codex_sha'] = sha(codex)
    if capture and provider == 'gemini':
        write_capture(base, attempt, mode=capture_mode or mode or 'print')
    if existing_root:
        (base / f'NativeAuthSix4.2.7-windows-20261011-r4-v1-{attempt}-{provider}').mkdir()
    scenario = {'status': status_table or {}, 'bridge': bridges or {}, 'answers': list(answers), 'daemons_active': daemons_active}
    (tmp_path / 'scenario.json').write_text(json.dumps(scenario))
    (tmp_path / 'fx.json').write_text(json.dumps(fx))
    code = HARNESS
    for token, value in (('@@FUNCTIONS@@', functions(DRIVER)), ('@@READ_STUBS@@', READ_STUBS), ('@@F@@', str(base)), ('@@J@@', str(tmp_path / 'journal.txt')),
                         ('@@W@@', str(W)), ('@@S@@', str(tmp_path / 'scenario.json')), ('@@X@@', str(tmp_path / 'fx.json')), ('@@P@@', provider),
                         ('@@M@@', mode), ('@@A@@', attempt), ('@@APPLY@@', 'true' if apply else 'false'), ('@@IR@@', status.INSTALL_RECEIPT_SHA256),
                         ('@@MS@@', status.MANIFEST_SHA256), ('@@CS@@', status.CONFIG_SHA256), ('@@RS@@', status.REVISION_SHA256)):
        code = code.replace(token, value)
    run = ps(code, tmp_path / 'scripts', timeout=240)
    return Series(tmp_path, run, base, attempt, provider)


def sequence(series):
    """Ordered status/child/prompt/history events: proves strictly serial slot handling."""
    out = []
    for kind, value in series.kinds('status', 'child', 'prompt', 'agy_history', 'claude_history'):
        if kind == 'child':
            out.append('child:' + value[value.index('-Slot') + 1])
        elif kind == 'prompt':
            out.append('prompt:' + re.search(r'slot\d', value).group(0))
        elif kind in ('agy_history', 'claude_history'):
            out.append(kind + ':' + value)
        else:
            out.append('status:' + value)
    return out


def assert_no_secrets(series):
    texts = [series.run.stdout, series.run.stderr, json.dumps(series.end)]
    if series.root.exists():
        texts += [p.read_text(encoding='utf-8') for p in series.root.iterdir()]
    for text in texts:
        for secret in SECRETS:
            assert secret not in text, secret


def test_plan_preview_with_the_all_zero_attempt_creates_nothing(tmp_path):
    series = run_series(tmp_path, attempt=ZERO, apply=False, capture=False, real_bridge=True, real_history=True)
    assert series.run.returncode == 0, series.run.stdout + series.run.stderr
    assert series.end['error'] is None
    plan = json.loads(series.end['out'])
    assert plan['schema'] == 'cochem-six-worker-status-first-plan/1' and plan['mode'] == 'READ_ONLY_PLAN' and plan['attempt'] == ZERO
    assert plan['provider'] == 'gemini' and plan['selected_workers'] == SLOTS and plan['shared_capacity'] == 4 and plan['maximum_logins'] == 6
    assert plan['series_root'] == str(series.root) and plan['login_mode'] == 'print' and plan['login_mode_binding'] is None
    assert plan['native_commands_executed'] == 0 and plan['model_jobs_executed'] == 0 and plan['activation_ready'] is False and plan['configuration_applied'] is False
    assert plan['runtime']['install_receipt_sha256'] == status.INSTALL_RECEIPT_SHA256 and plan['exit_codes'] == {'completed': 0, 'orderly_pause': 20}
    assert plan['status_leaf'] == {'path': str(LEAF), 'sha256': sha(LEAF), 'helper_sha256': sha(STATUS_PY)}
    assert plan['login_child'] == {'path': str(WRAPPER), 'sha256': sha(WRAPPER)} and plan['daemon_tasks_required_stopped'] == list(status.DAEMON_TASK_NAMES)
    # The final bridge files open against their pins and the real history imports by hash: only the missing capture holds.
    assert len(plan['holds']) == 1 and 'No signed-out AgyCapture exists' in plan['holds'][0]
    assert str(WRAPPER) in series.values('held') and str(BRIDGE_PY) in series.values('held') and str(HISTORY) in series.values('held')
    assert not series.values('series_root') and not series.values('child') and not series.values('status') and not series.values('prompt')
    assert not series.values('codetree') and not series.root.exists()


def test_plan_reports_no_hold_when_every_gemini_prerequisite_is_bound(tmp_path):
    series = run_series(tmp_path, apply=False)
    plan = json.loads(series.end['out'])
    assert plan['holds'] == [] and plan['login_mode_binding']['mode'] == 'print' and plan['attempt'] == ATTEMPT
    assert not series.root.exists() and not series.values('child') and not series.values('status')


def test_apply_refuses_when_a_bridge_file_differs_from_its_pin_and_changes_nothing(tmp_path):
    series = run_series(tmp_path, wrong_wrapper_pin=True, status_table={'slot1|before': 'ATTENDED_LOGIN_REQUIRED'})
    assert series.end['error'].startswith('The login series is held. Nothing was changed: Reviewed file ')
    assert WRAPPER_NAME in series.end['error'] and 'is absent or differs from its pin: Inert fixture content drift' in series.end['error']
    assert not series.root.exists() and not series.values('series_root') and not series.values('child') and not series.values('status')


def test_gemini_series_is_strictly_serial_with_the_exact_bridge_argv_and_a_complete_record(tmp_path):
    table = {'slot1|before': 'ATTENDED_LOGIN_REQUIRED', 'slot3|before': 'ATTENDED_LOGIN_REQUIRED'}
    series = run_series(tmp_path, status_table=table, bridges={'slot1': bridge(), 'slot3': bridge(status_value='LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED')})
    assert series.run.returncode == 0, series.run.stdout + series.run.stderr
    assert series.end['error'] is None, series.end
    assert sequence(series) == ['status:slot1|before', 'agy_history:slot1', 'prompt:slot1', 'agy_history:slot1', 'child:slot1', 'status:slot1|after',
                                'status:slot2|before',
                                'status:slot3|before', 'agy_history:slot3', 'prompt:slot3', 'agy_history:slot3', 'child:slot3', 'status:slot3|after',
                                'status:slot4|before', 'status:slot5|before', 'status:slot6|before']
    wrapper = json.loads((tmp_path / 'fx.json').read_text())['wrapper']
    for slot, argv in zip(('slot1', 'slot3'), series.values('child')):
        assert argv == ['-NoProfile', '-File', wrapper, '-Slot', slot, '-LoginMode', 'print', '-CaptureAttempt', ATTEMPT, '-Apply', '-Interactive']
    assert 'One slot can take up to about 15 minutes' in series.run.stdout
    assert series.values('codetree') == [str(series.base / 'Pipeline4.2.7-windows-20261009-r4'), str(series.base / 'Toolchain4.2.7-windows-20261006' / 'Python312'),
                                         str(series.base / 'Native4.2.7-windows-20261006')]
    complete = series.record('series-complete.json')
    assert json.loads(series.end['out']) == complete
    assert complete['schema'] == 'cochem-six-worker-status-first-result/1' and complete['status'] == 'SIX_CONFIGURED_WORKERS_SUBSCRIPTION_AUTHENTICATION_VERIFIED'
    assert complete['provider'] == 'gemini' and complete['attempt'] == ATTEMPT and re.fullmatch('[a-f0-9]{32}', complete['nonce'])
    assert complete['selected_workers_verified'] == 6 and complete['login_commands_executed'] == 2 and complete['existing_sessions_reused'] == 4
    assert complete['all_slots_reuse_verified'] is True and complete['login_mode'] == 'print' and complete['login_mode_binding']['mode'] == 'print'
    assert complete['model_jobs_executed'] == 0 and complete['activation_ready'] is False and complete['configuration_applied'] is False
    rows = {row['slot']: row for row in complete['slots']}
    assert list(rows) == SLOTS
    for slot in SLOTS:
        row = rows[slot]
        assert row['final_decision'] == 'REUSE_VERIFIED_SESSION' and row['reuse_verified'] is True
        if slot in ('slot1', 'slot3'):
            assert row['outcome'] == 'AUTHENTICATED_AFTER_LOGIN' and row['before']['decision'] == 'ATTENDED_LOGIN_REQUIRED'
            assert row['after']['decision'] == 'REUSE_VERIFIED_SESSION' and row['after']['stage'] == 'after' and row['login_commands_executed'] == 1
            assert row['bridge']['accepted'] is True and row['bridge']['pause_markers'] == [] and row['bridge']['receipt_login_mode'] == 'print'
            assert row['bridge']['operator_log_scanned'] is True and row['bridge']['raw_operator_text_recorded'] is False
            assert row['bridge']['session_result_present'] is True and row['bridge']['session_held_present'] is False
            assert row['bridge']['session_result_bound'] is True and re.fullmatch('[a-f0-9]{64}', row['bridge']['session_result_sha256'])
        else:
            assert row['outcome'] == 'REUSED_VERIFIED_SESSION' and row['before']['decision'] == 'REUSE_VERIFIED_SESSION' and row['after'] is None
            assert row['login_commands_executed'] == 0 and row['bridge'] is None
    assert [r['slot'] for r in complete['status_receipts']] == SLOTS
    files = series.files()
    for name in ('series-start.json', 'slot1-LOGIN_BRIDGE_OUTCOME.json', 'slot3-LOGIN_BRIDGE_OUTCOME.json', 'slot1-AUTHENTICATED_AFTER_LOGIN.json',
                 'slot2-REUSED_VERIFIED_SESSION.json', 'slot3-LOGIN_EXITED_ZERO.json', 'slot6-STATUS_BEFORE_COMPLETE.json'):
        assert name in files, name
    assert 'series-held.json' not in files and 'series-paused.json' not in files
    start = series.record('series-start.json')
    assert start['status'] == 'IN_PROGRESS' and start['login_mode'] == 'print' and start['nonce'] == complete['nonce']
    assert_no_secrets(series)


def test_reuse_verified_session_skips_every_login(tmp_path):
    series = run_series(tmp_path)
    assert series.end['error'] is None
    assert sequence(series) == [f'status:{slot}|before' for slot in SLOTS]
    complete = series.record('series-complete.json')
    assert complete['login_commands_executed'] == 0 and complete['existing_sessions_reused'] == 6 and complete['all_slots_reuse_verified'] is True
    assert all(row['after'] is None and row['outcome'] == 'REUSED_VERIFIED_SESSION' for row in complete['slots'])
    assert not any(name.endswith('LOGIN_STARTED.json') for name in series.files())


def test_bridge_failure_holds_the_slot_and_starts_no_later_slot(tmp_path):
    series = run_series(tmp_path, status_table={'slot2|before': 'ATTENDED_LOGIN_REQUIRED'},
                        bridges={'slot2': bridge(exit=1, status_value='LOGIN_COMMAND_FAILED')}, answers=['READY', 'HOLD'])
    assert series.run.returncode == 0 and series.end['error'] == 'Attended login did not exit successfully. Preserve evidence; no automatic repeat or later slot was started.'
    assert sequence(series) == ['status:slot1|before', 'status:slot2|before', 'agy_history:slot2', 'prompt:slot2', 'agy_history:slot2', 'child:slot2', 'prompt:slot2']
    held = series.record('series-held.json')
    assert held['schema'] == 'cochem-six-worker-status-first-held/1' and held['status'] == 'AUTHENTICATION_HELD' and held['held_slot'] == 'slot2'
    assert held['phase'] == 'login' and held['held_reason'] == 'LOGIN_NOT_COMPLETED' and held['gemini_held'] is True and held['later_slots_started'] is False
    assert held['automatic_resume_allowed'] is False and held['login_commands_executed'] == 1 and held['existing_sessions_reused'] == 1
    rows = {row['slot']: row for row in held['slots']}
    assert rows['slot1']['outcome'] == 'REUSED_VERIFIED_SESSION' and rows['slot2']['outcome'] == 'HELD'
    assert rows['slot2']['bridge']['receipt_status'] == 'LOGIN_COMMAND_FAILED' and rows['slot2']['bridge']['wrapper_exit_code'] == 1
    assert rows['slot2']['bridge']['accepted'] is False and rows['slot2']['bridge']['pause_required'] is False and rows['slot2']['after'] is None
    # A non-zero exit records only the presence of the wrapper's terminal records, never their content.
    assert rows['slot2']['bridge']['session_held_present'] is True and rows['slot2']['bridge']['session_result_present'] is False
    assert rows['slot2']['bridge']['session_result_bound'] is False and rows['slot2']['bridge']['session_result_sha256'] is None
    assert not [e for e in series.values('read') if e.endswith('session-held.json') or e.endswith('session-result.json')]
    assert all(rows[s]['outcome'] == 'NOT_STARTED' for s in ('slot3', 'slot4', 'slot5', 'slot6'))
    assert 'series-complete.json' not in series.files() and 'series-paused.json' not in series.files()
    assert_no_secrets(series)


@pytest.mark.parametrize('change', ['no_root', 'status_failed', 'cleanup_false', 'mode_mismatch', 'schema_wrong', 'no_receipt',
                                    'result_missing', 'held_present', 'result_slot_mismatch', 'result_nonce_mismatch', 'result_receipt_mismatch',
                                    'result_schema_wrong', 'result_outcome_wrong'])
def test_bridge_exit_zero_without_an_accepted_bound_receipt_is_held(tmp_path, change):
    config = {'no_root': bridge(root=False), 'status_failed': bridge(status_value='LOGIN_COMMAND_FAILED'), 'cleanup_false': bridge(cleanup=False),
              'mode_mismatch': bridge(login_mode='tui'), 'schema_wrong': bridge(schema='cochem-interactive-claude-login/1'),
              'no_receipt': bridge(status_value=None), 'result_missing': bridge(result=None), 'held_present': bridge(held=True),
              'result_slot_mismatch': bridge(result='slot_mismatch'), 'result_nonce_mismatch': bridge(result='nonce_mismatch'),
              'result_receipt_mismatch': bridge(result='receipt_mismatch'), 'result_schema_wrong': bridge(result='schema_wrong'),
              'result_outcome_wrong': bridge(result='outcome_wrong')}[change]
    series = run_series(tmp_path, status_table={'slot1|before': 'ATTENDED_LOGIN_REQUIRED'}, bridges={'slot1': config})
    assert series.end['error'].startswith('The agy sign-in exited 0 without a bound accepted bridge receipt.')
    held = series.record('series-held.json')
    assert held['held_slot'] == 'slot1' and held['held_reason'] == 'LOGIN_NOT_COMPLETED'
    assert 'status:slot1|after' not in sequence(series) and 'status:slot2|before' not in sequence(series)
    outcome = held['slots'][0]['bridge']
    assert outcome['accepted'] is False
    if change not in ('status_failed', 'cleanup_false', 'mode_mismatch'):
        # (Those three mirror a receipt that is itself refused, so their session-result binds to it but the slot is still not accepted.)
        assert outcome['session_result_bound'] is False and outcome['session_result_sha256'] is None
    if change == 'result_missing':
        assert outcome['session_result_present'] is False and outcome['session_held_present'] is False and outcome['receipt_bound'] is True
    if change == 'held_present':
        assert outcome['session_held_present'] is True and outcome['session_result_present'] is True
    if change.startswith('result_') and change != 'result_missing':
        assert outcome['session_result_present'] is True and outcome['session_held_present'] is False and outcome['receipt_bound'] is True
    assert_no_secrets(series)


def test_after_status_that_is_not_reuse_is_held(tmp_path):
    series = run_series(tmp_path, status_table={'slot1|before': 'ATTENDED_LOGIN_REQUIRED', 'slot1|after': 'ATTENDED_LOGIN_REQUIRED'}, bridges={'slot1': bridge()})
    assert series.end['error'] == 'Post-login authentication is not verified. Preserve evidence; no automatic repeat.'
    held = series.record('series-held.json')
    assert held['phase'] == 'status_after' and held['held_reason'] == 'AFTER_STATUS_NOT_VERIFIED' and held['held_slot'] == 'slot1'
    row = held['slots'][0]
    assert row['before']['decision'] == 'ATTENDED_LOGIN_REQUIRED' and row['after']['decision'] == 'ATTENDED_LOGIN_REQUIRED' and row['final_decision'] == 'ATTENDED_LOGIN_REQUIRED'
    assert 'status:slot2|before' not in sequence(series)


@pytest.mark.parametrize('stage', ['before', 'after'])
def test_status_hold_is_held_without_further_login(tmp_path, stage):
    table = {'slot1|before': 'HOLD'} if stage == 'before' else {'slot1|before': 'ATTENDED_LOGIN_REQUIRED', 'slot1|after': 'HOLD'}
    series = run_series(tmp_path, status_table=table, bridges={'slot1': bridge()})
    held = series.record('series-held.json')
    assert held['phase'] == f'status_{stage}' and held['held_slot'] == 'slot1'
    assert held['slots'][0][stage]['decision'] == 'HOLD' and held['slots'][0][stage]['summary']['decision'] == 'HOLD'
    assert len(series.values('child')) == (0 if stage == 'before' else 1) and 'status:slot2|before' not in sequence(series)


@pytest.mark.parametrize('capture_mode,requested', [('tui', 'print'), ('none', 'print')])
def test_login_mode_mismatch_or_none_is_refused_before_any_change(tmp_path, capture_mode, requested):
    series = run_series(tmp_path, mode=requested, capture_mode=capture_mode, status_table={'slot1|before': 'ATTENDED_LOGIN_REQUIRED'})
    assert series.end['error'].startswith('The login series is held. Nothing was changed:')
    assert ('differs from login-mode.json' if capture_mode == 'tui' else 'did not pass its gate') in series.end['error'] or 'decided mode none' in series.end['error']
    assert not series.root.exists() and not series.values('child') and not series.values('status') and not series.values('series_root')


@pytest.mark.parametrize('text,marker', [("Google wants to verify it's you. Try another way.", 'verification_present'),
                                         ('This account was disabled. Submit an appeal.', 'appeal_present'),
                                         ('Error: 429 Too Many Requests. Try again later.', 'rate_limit_present'),
                                         ('We noticed unusual activity on this account.', 'unusual_activity_present')])
def test_verification_or_rate_limit_text_pauses_with_exit_20_and_records_the_slot(tmp_path, text, marker):
    series = run_series(tmp_path, status_table={'slot2|before': 'ATTENDED_LOGIN_REQUIRED'},
                        bridges={'slot2': bridge(exit=1, status_value='LOGIN_FAILED_OR_CANCELLED', log=NEUTRAL_LOG + text + '\n')})
    assert series.run.returncode == 20, series.run.stdout + series.run.stderr
    assert series.end is None
    paused = series.record('series-paused.json')
    assert paused['schema'] == 'cochem-six-worker-status-first-paused/1' and paused['status'] == 'AUTHENTICATION_PAUSED_AFTER_LOGIN'
    assert paused['paused_slot'] == 'slot2' and paused['marker_slot'] == 'slot2' and marker in paused['pause_markers']
    assert paused['pause_reason'] == 'RATE_LIMIT_OR_IDENTITY_VERIFICATION' and paused['exit_code'] == 20 and paused['gemini_held'] is True
    assert paused['before_status_proof']['decision'] == 'ATTENDED_LOGIN_REQUIRED' and paused['automatic_retry_allowed'] is False
    rows = {row['slot']: row for row in paused['slots']}
    assert rows['slot2']['outcome'] == 'PAUSED_AFTER_LOGIN' and rows['slot3']['outcome'] == 'NOT_STARTED'
    # Markers in the log make the owner-reported prompt unnecessary; no later slot is touched.
    assert sequence(series)[-1] == 'child:slot2' and len(series.values('prompt')) == 1
    assert 'series-held.json' not in series.files() and 'series-complete.json' not in series.files()
    assert_no_secrets(series)


def test_benign_verifying_output_does_not_pause_the_series(tmp_path):
    table = {'slot1|before': 'ATTENDED_LOGIN_REQUIRED', 'slot2|before': 'ATTENDED_LOGIN_REQUIRED'}
    log = NEUTRAL_LOG + 'Verifying...\nVerifying your session\nVerification code sent\n'
    series = run_series(tmp_path, status_table=table, bridges={'slot1': bridge(log=log), 'slot2': bridge(log=log)})
    assert series.run.returncode == 0 and series.end['error'] is None, series.run.stdout + series.run.stderr
    complete = series.record('series-complete.json')
    assert complete['login_commands_executed'] == 2 and all(row['bridge'] is None or row['bridge']['pause_markers'] == [] for row in complete['slots'])


def test_marker_after_a_successful_slot_pauses_before_the_next_consent(tmp_path):
    table = {'slot2|before': 'ATTENDED_LOGIN_REQUIRED', 'slot3|before': 'ATTENDED_LOGIN_REQUIRED'}
    series = run_series(tmp_path, status_table=table, bridges={'slot2': bridge(log=NEUTRAL_LOG + 'Warning: rate limit approaching\n'), 'slot3': bridge()})
    assert series.run.returncode == 20, series.run.stdout + series.run.stderr
    assert sequence(series) == ['status:slot1|before', 'status:slot2|before', 'agy_history:slot2', 'prompt:slot2', 'agy_history:slot2', 'child:slot2',
                                'status:slot2|after', 'status:slot3|before']
    paused = series.record('series-paused.json')
    assert paused['status'] == 'AUTHENTICATION_PAUSED_BEFORE_LOGIN' and paused['paused_slot'] == 'slot3' and paused['marker_slot'] == 'slot2'
    assert paused['pause_reason'] == 'RATE_LIMIT_OR_IDENTITY_VERIFICATION' and paused['pause_markers'] == ['rate_limit_present']
    assert paused['before_status_proof']['decision'] == 'ATTENDED_LOGIN_REQUIRED' and paused['login_commands_executed'] == 1
    rows = {row['slot']: row for row in paused['slots']}
    assert rows['slot2']['outcome'] == 'AUTHENTICATED_AFTER_LOGIN' and rows['slot2']['final_decision'] == 'REUSE_VERIFIED_SESSION'
    assert rows['slot3']['outcome'] == 'PAUSED_BEFORE_LOGIN' and rows['slot3']['login_commands_executed'] == 0
    assert 'slot3-PAUSED_BEFORE_LOGIN.json' in series.files()


def test_bridge_pause_exit_20_pauses_the_series_without_an_owner_prompt(tmp_path):
    series = run_series(tmp_path, status_table={'slot1|before': 'ATTENDED_LOGIN_REQUIRED'},
                        bridges={'slot1': bridge(exit=20, status_value='LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED', pause_seen=True)})
    assert series.run.returncode == 20, series.run.stdout + series.run.stderr
    paused = series.record('series-paused.json')
    assert paused['status'] == 'AUTHENTICATION_PAUSED_AFTER_LOGIN' and paused['paused_slot'] == 'slot1'
    assert paused['pause_markers'] == ['bridge_receipt_pause_marker', 'bridge_pause_exit'] and paused['pause_reason'] == 'RATE_LIMIT_OR_IDENTITY_VERIFICATION'
    assert len(series.values('prompt')) == 1 and 'status:slot1|after' not in sequence(series) and 'status:slot2|before' not in sequence(series)
    outcome = paused['slots'][0]['bridge']
    assert outcome['session_result_present'] is True and outcome['session_held_present'] is False
    assert outcome['session_result_bound'] is False and outcome['session_result_sha256'] is None
    assert not [e for e in series.values('read') if e.endswith('session-result.json')]
    assert_no_secrets(series)


def test_receipt_pause_flag_on_an_accepted_slot_pauses_before_the_next_consent(tmp_path):
    table = {'slot1|before': 'ATTENDED_LOGIN_REQUIRED', 'slot2|before': 'ATTENDED_LOGIN_REQUIRED'}
    series = run_series(tmp_path, status_table=table, bridges={'slot1': bridge(pause_seen=True), 'slot2': bridge()})
    assert series.run.returncode == 20, series.run.stdout + series.run.stderr
    paused = series.record('series-paused.json')
    assert paused['status'] == 'AUTHENTICATION_PAUSED_BEFORE_LOGIN' and paused['paused_slot'] == 'slot2' and paused['marker_slot'] == 'slot1'
    assert paused['pause_markers'] == ['bridge_receipt_pause_marker'] and [v[v.index('-Slot') + 1] for v in series.values('child')] == ['slot1']
    assert {row['slot']: row['outcome'] for row in paused['slots']}['slot1'] == 'AUTHENTICATED_AFTER_LOGIN'


def test_owner_pause_at_readiness_exits_20_without_a_login(tmp_path):
    series = run_series(tmp_path, status_table={'slot4|before': 'ATTENDED_LOGIN_REQUIRED'}, answers=['PAUSE'])
    assert series.run.returncode == 20
    paused = series.record('series-paused.json')
    assert paused['status'] == 'AUTHENTICATION_PAUSED_BEFORE_LOGIN' and paused['paused_slot'] == 'slot4' and paused['pause_reason'] == 'OWNER_PAUSED_BEFORE_LOGIN'
    assert paused['pause_markers'] == [] and paused['marker_slot'] is None and paused['existing_sessions_reused'] == 3 and paused['login_commands_executed'] == 0
    assert not series.values('child') and 'status:slot5|before' not in sequence(series)
    assert 'open the printed Google sign-in URL in your own browser now; paste the returned code at the masked prompt; Escape cancels' in series.run.stdout


def test_owner_reported_verification_after_a_failed_sign_in_exits_20(tmp_path):
    series = run_series(tmp_path, status_table={'slot1|before': 'ATTENDED_LOGIN_REQUIRED'},
                        bridges={'slot1': bridge(exit=1, status_value='LOGIN_FAILED_OR_CANCELLED')}, answers=['READY', 'PAUSE'])
    assert series.run.returncode == 20
    paused = series.record('series-paused.json')
    assert paused['status'] == 'AUTHENTICATION_PAUSED_AFTER_LOGIN' and paused['paused_slot'] == 'slot1'
    assert paused['pause_reason'] == 'OWNER_REPORTED_RATE_LIMIT_OR_IDENTITY_VERIFICATION' and paused['pause_markers'] == ['owner_reported']
    assert 'identity-verification, appeal or rate-limit page' in series.values('prompt')[-1]


def test_records_are_create_new_and_an_existing_series_root_is_never_reused(tmp_path):
    series = run_series(tmp_path, existing_root=True, status_table={'slot1|before': 'ATTENDED_LOGIN_REQUIRED'})
    assert 'An earlier six-worker provider series root exists. Preserve it; no automatic repeat or resume.' in series.end['error']
    assert not series.values('series_root') and not series.values('status') and series.files() == []
    target = tmp_path / 'private'
    target.mkdir()
    code = functions(DRIVER) + f"Set-SeriesConstants 'gemini' '{ATTEMPT}' '{W}' 'print'\n" + (
        "foreach($t in @(Get-SeriesHelperDefinitions 'gemini')){. ([scriptblock]::Create($t))}\n" + r"""
      function Assert-SeriesPrivateRoot {param($Path)}
      function New-PrivateAcl {$a=[Security.AccessControl.FileSecurity]::new();$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User;$a.SetOwner($sid);$a.SetAccessRuleProtection($true,$false);$a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','Allow'));$a}
      """ + f"$p='{target}\\slot1-LOGIN_STARTED.json';Write-SeriesRecord $p ([ordered]@{{first=$true}});$second=$false;try{{Write-SeriesRecord $p ([ordered]@{{first=$false}})}}catch{{$second=$true}};"
        "'RESULT '+(@{refused=$second;content=[IO.File]::ReadAllText($p)}|ConvertTo-Json -Compress)")
    value = result_of(ps(code, tmp_path / 'scripts2'))
    assert value['refused'] is True and json.loads(value['content']) == {'first': True}


def test_daemons_active_hold_the_plan_and_refuse_apply(tmp_path):
    series = run_series(tmp_path, daemons_active=True)
    assert series.end['error'].startswith('The login series is held. Nothing was changed: Protected daemons must remain stopped and disabled')
    assert not series.root.exists() and not series.values('status')


@pytest.mark.parametrize('provider', ['codex', 'claude'])
def test_codex_and_claude_children_keep_their_reviewed_arguments(tmp_path, provider):
    series = run_series(tmp_path, provider=provider, mode='', status_table={'slot2|before': 'ATTENDED_LOGIN_REQUIRED'})
    assert series.end['error'] is None, series.end
    [argv] = series.values('child')
    if provider == 'codex':
        assert argv == ['-NoProfile', '-File', str(series.base / 'InstallGuard4.2.7-windows-20261006' / 'repository' / 'scripts' / 'login_pipeline_worker.ps1'),
                        '-Slot', 'slot2', '-Provider', 'codex', '-Executable', str(series.base / 'Native4.2.7-windows-20261006' / 'codex.exe'),
                        '-InstallRoot', str(series.base / 'Pipeline4.2.7-windows-20261009-r4')]
        assert not series.values('claude_history')
    else:
        assert argv == ['-NoProfile', '-File', str(W / 'login_pipeline_worker_interactive_r3_v6.ps1'), '-Slot', 'slot2', '-Apply', '-Interactive']
        assert series.values('claude_history') == ['slot2', 'slot2']
    assert not series.values('agy_history')
    complete = series.record('series-complete.json')
    assert complete['provider'] == provider and complete['login_mode'] is None and complete['login_commands_executed'] == 1
    assert complete['slots'][1]['bridge'] is None and not any('LOGIN_BRIDGE_OUTCOME' in n for n in series.files())


def test_bridge_call_is_isolated_in_one_function(tmp_path):
    body = driver_text().split('[CmdletBinding()]', 1)[1]  # code after the header comment
    assert body.count(WRAPPER_NAME) == 1 and body.count("'-LoginMode'") == 1
    code = ("$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile('" + str(DRIVER) + "',[ref]$t,[ref]$e);"
            "$f=@($a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Invoke-AgyBridgeLogin'},$true))[0];"
            "$calls=@($f.Body.FindAll({param($n)$n -is [Management.Automation.Language.CommandAst]},$true)|ForEach-Object{$_.GetCommandName()});"
            "$users=@($a.FindAll({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -ceq 'Invoke-AgyBridgeLogin'},$true)|ForEach-Object{"
            "$p=$_.Parent;while($null -ne $p -and $p -isnot [Management.Automation.Language.FunctionDefinitionAst]){$p=$p.Parent};$p.Name});"
            "'RESULT '+(@{calls=$calls;users=$users}|ConvertTo-Json -Compress)")
    value = result_of(ps(code, tmp_path))
    assert value['calls'] == ['Invoke-SeriesConsoleChild'] and value['users'] == ['Invoke-SeriesLoginHook']


# ------------------------------------------------------------------- top level, plan mode only (ps_toplevel_smoke.py)
# The fixtures above dot-source single functions, so the real param block never ran here. That hid the 2026-10-11 17:22
# class: a script parameter variable keeps its [Validate*] attributes for the whole run, so Set-SeriesConstants'
# $script:LoginMode='' (claude, codex, and gemini without -LoginMode) threw ValidationMetadataException before any change.
# These tests run the REAL driver top level with the host stubbed; the helper refuses -Apply, so each documented sitting
# call runs with -Apply removed (its plan).

PLAN_SCHEMA = 'cochem-six-worker-status-first-plan/1'
SITTING_CALLS = [
    # RUN_427_R5_SITTING.ps1 S3: the owner accepts the attended re-login (Invoke-R5Attended -Provider claude|codex).
    pytest.param('claude', ['-Provider', 'claude', '-Attempt', ATTEMPT, '-Interactive'], id='S3-claude'),
    pytest.param('codex', ['-Provider', 'codex', '-Attempt', ATTEMPT, '-Interactive'], id='S3-codex'),
    # S6: Gemini sign-in with the signed-out capture's login mode.
    pytest.param('gemini', ['-Provider', 'gemini', '-LoginMode', 'print', '-Attempt', ATTEMPT, '-Interactive'], id='S6-gemini-print'),
    pytest.param('gemini', ['-Provider', 'gemini', '-LoginMode', 'tui', '-Attempt', ATTEMPT, '-Interactive'], id='S6-gemini-tui'),
]


def validated_parameter_assignments(script, tmp_path):
    """Assignments that write a [Validate*] script parameter variable: $script:/$global:<name> anywhere (functions run in
    the script's scope), or a bare <name> at the top level; names compare case-insensitively, as PowerShell does."""
    code = ("$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile('" + str(script) + "',[ref]$t,[ref]$e);if($e.Count){throw $e[0]};"
            "$v=@{};foreach($p in @($a.ParamBlock.Parameters)){if(@($p.Attributes|Where-Object{$_.TypeName.Name -like 'Validate*'}).Count){$v[$p.Name.VariablePath.UserPath.ToLowerInvariant()]=1}};"
            "$hits=@(foreach($n in $a.FindAll({param($x)$x -is [Management.Automation.Language.AssignmentStatementAst]},$true)){"
            "$targets=@($n.Left);if($n.Left -is [Management.Automation.Language.ArrayLiteralAst]){$targets=@($n.Left.Elements)};"
            "foreach($l in $targets){if($l -is [Management.Automation.Language.ConvertExpressionAst]){$l=$l.Child};if($l -isnot [Management.Automation.Language.VariableExpressionAst]){continue};"
            "$name=($l.VariablePath.UserPath -replace '^(script|global|local|private):','').ToLowerInvariant();"
            "$f=$n.Parent;while($null -ne $f -and $f -isnot [Management.Automation.Language.FunctionDefinitionAst]){$f=$f.Parent};"
            "if($v.ContainsKey($name) -and ($l.VariablePath.IsScript -or $l.VariablePath.IsGlobal -or $null -eq $f)){$l.Extent.Text+'='+$n.Right.Extent.Text}}});"
            "$sv=@($a.FindAll({param($x)$x -is [Management.Automation.Language.CommandAst] -and $x.GetCommandName() -in @('Set-Variable','New-Variable','sv','nv')},$true)).Count;"
            "'RESULT '+(@{validated=@($v.Keys|Sort-Object);hits=@($hits|Sort-Object);set_variable=$sv}|ConvertTo-Json -Compress)")
    return result_of(ps(code, tmp_path))


def test_no_assignment_writes_a_validated_parameter_variable(tmp_path):
    value = validated_parameter_assignments(DRIVER, tmp_path)
    # -LoginMode carries no [ValidateSet]: Get-LoginModeRefusal enforces print|tui (after lowercasing) and gemini-only.
    assert value['validated'] == ['attempt', 'provider']
    # The two remaining writes carry values Invoke-LoginSeriesMain has already checked: a lowercase 32-hex -Attempt
    # (-cnotmatch) and the lowercased -Provider (-cnotin codex|claude|gemini); a [ValidateSet] compares case-insensitively.
    assert value['hits'] == ['$script:Attempt=$Attempt', '$script:Provider=$Provider'] and value['set_variable'] == 0


@pytest.mark.parametrize('invocation', ['file', 'command'])
@pytest.mark.parametrize('provider,args', SITTING_CALLS)
def test_toplevel_plan_for_each_documented_sitting_call(provider, args, invocation):
    result = smoke.run_toplevel(DRIVER, args, invocation=invocation)
    assert smoke.plan_mode_outcome(result, plan_schema=PLAN_SCHEMA) == 'plan', result.describe()
    plan = result.plan
    mode = args[args.index('-LoginMode') + 1] if '-LoginMode' in args else None
    assert plan['provider'] == provider and plan['attempt'] == ATTEMPT and plan['login_mode'] == mode
    assert plan['series_root'] == COCHEM + '\\NativeAuthSix4.2.7-windows-20261011-r4-v1-' + ATTEMPT + '-' + provider
    assert plan['native_commands_executed'] == 0 and plan['model_jobs_executed'] == 0 and isinstance(plan['holds'], list)
    child = {'codex': CODEX_HELPER, 'claude': W / 'login_pipeline_worker_interactive_r3_v6.ps1', 'gemini': WRAPPER}[provider]
    assert plan['login_child']['path'].lower() == str(child).lower()


@pytest.mark.parametrize('args,message', [
    (['-Provider', 'claude', '-LoginMode', 'print', '-Attempt', ATTEMPT], '-LoginMode applies only to -Provider gemini; nothing was changed.'),
    (['-Provider', 'codex', '-LoginMode', 'tui', '-Attempt', ATTEMPT, '-Interactive'], '-LoginMode applies only to -Provider gemini; nothing was changed.'),
    (['-Provider', 'gemini', '-LoginMode', 'none', '-Attempt', ATTEMPT], '-LoginMode must be print or tui (the signed-out capture decision); nothing was changed.'),
    (['-Provider', 'gemini', '-LoginMode', 'bogus', '-Attempt', ATTEMPT], '-LoginMode must be print or tui (the signed-out capture decision); nothing was changed.'),
], ids=['claude-with-mode', 'codex-with-mode', 'gemini-none', 'gemini-bogus'])
def test_toplevel_login_mode_outside_the_reviewed_set_is_refused_cleanly(args, message):
    # Without a [ValidateSet] the driver's own refusal is the only gate; it runs before any host command.
    result = smoke.run_toplevel(DRIVER, args)
    assert smoke.plan_mode_outcome(result) == 'refusal', result.describe()
    assert result.error.message == message and not result.trace, result.describe()


def test_toplevel_gemini_plan_without_login_mode_holds_instead_of_failing():
    result = smoke.run_toplevel(DRIVER, ['-Provider', 'gemini', '-Attempt', ATTEMPT])
    assert smoke.plan_mode_outcome(result, plan_schema=PLAN_SCHEMA) == 'plan', result.describe()
    assert result.plan['login_mode'] is None
    assert 'Gemini requires -LoginMode print or tui equal to login-mode.json of the signed-out AgyCapture of this -Attempt.' in result.plan['holds']


def test_toplevel_upper_case_login_mode_is_lowercased_as_before():
    result = smoke.run_toplevel(DRIVER, ['-Provider', 'Gemini', '-LoginMode', 'PRINT', '-Attempt', ATTEMPT, '-Interactive'], invocation='command')
    assert smoke.plan_mode_outcome(result, plan_schema=PLAN_SCHEMA) == 'plan', result.describe()
    assert result.plan['provider'] == 'gemini' and result.plan['login_mode'] == 'print'
