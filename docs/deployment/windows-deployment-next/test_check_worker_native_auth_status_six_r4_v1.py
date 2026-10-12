"""Inert PS5.1 fixtures for check-worker-native-auth-status-six-r4-v1.ps1 (build-manifest step 3).

No task is registered or run and no privileged API is called. Functions are taken from the
script's AST (its only top-level statement is the invocation, which never runs here) and driven
in a throwaway powershell.exe with stubs that model the Task Scheduler COM objects. The reviewed
helper definitions are imported by hash through the script's own Import-ReviewedFunctions. The
r4 receipts under Program Files are only read. The real script is run only in its read-only plan
mode or with arguments it refuses before running anything; it is never run with -Apply (its -Apply
guards are checked at function level from the AST). The tests at the end also run every documented call's plan
through ps_toplevel_smoke.py (stubbed host).
"""
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

import pytest

import ps_toplevel_smoke as smoke
import task_scheduler_host_projection as hostacl

W = Path(__file__).parent
LEAF = W / 'check-worker-native-auth-status-six-r4-v1.ps1'
LEAF_R3 = W / 'check-worker-native-auth-status-six-r3-v4.ps1'
LEAF_R3_SHA256 = '4448e76eaeb30f2d2905f5aa6d3e14f0cc29b3d7e703321bb3df55afcba58e81'
RETARGET = W / 'retarget-warden-r4.ps1'
DRIVER = W / 'login-six-workers-status-first-r4-v1.ps1'
PY = W / 'worker-native-auth-status-six-r4-v1.py'
PS = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
COCHEM = Path(r'C:\Program Files\CoChem')
R4 = COCHEM / 'Pipeline4.2.7-windows-20261009-r4'
R3 = COCHEM / 'Pipeline4.2.7-windows-20261007-r3'
ATTEMPT = '0123456789abcdef0123456789abcdef'
SDDL = 'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'
REVIEWED_PINS = {
    Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1'): '0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b',
    W / 'check-worker-native-status-r3.ps1': '18f58ebb448d8a0c6329dd187d4a9a27fa9cbe942cd05e906bb7aabc67e787a7',
    W / 'register-stopped-warden-r3.ps1': 'eccc593f36cbf488a54775b4343bcf3cf8b261b7cd81e5536fb7f2f18466a198',
    W / 'protected-code-inspection-v4.ps1': '5c01543cbb8b8d64b2b9f1bab4a13f87f8ff9e1ab3e82dfb6fc547144c77b95d',
}


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


status = load(PY, 'worker_native_auth_status_six_r4_v1_for_leaf')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def functions(path):
    return (f"$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$t,[ref]$e);if($e.Count){{throw $e[0]}};"
            "foreach($f in $ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){. ([scriptblock]::Create($f.Extent.Text))};")


def ps(code, timeout=180):
    prefix = ("$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;"
              "foreach($m in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME \"Modules\\$m\\$m.psd1\")};")
    return subprocess.run([PS, '-NoProfile', '-NonInteractive', '-Command', prefix + code], capture_output=True, text=True, timeout=timeout)


def success(result):
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line for line in result.stdout.splitlines() if line.startswith('RESULT ')]
    return json.loads(lines[-1][len('RESULT '):]) if lines else json.loads(result.stdout)


def harness(provider='gemini', stage='before', imports=True):
    code = functions(LEAF) + f"Set-AuthStatusConstants 'slot1' '{provider}' '{stage}' '{ATTEMPT}' '{W}';"
    if imports:
        code += "foreach($text in Get-AuthStatusHelperDefinitions){. ([scriptblock]::Create($text))};Initialize-FileIdentity;"
    return code + "$held=[Collections.Generic.List[IO.FileStream]]::new();"


def function_text(path, name):
    text = path.read_text(encoding='utf-8')
    code = functions(path).replace("foreach($f in $ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){. ([scriptblock]::Create($f.Extent.Text))};", '')
    code += f"$n=@($ast.FindAll({{param($x)$x -is [Management.Automation.Language.FunctionDefinitionAst] -and $x.Name -ceq '{name}'}},$true));if($n.Count -ne 1){{throw 'count'}};'RESULT '+(@{{text=$n[0].Extent.Text}}|ConvertTo-Json -Compress)"
    return success(ps(code))['text']


def is_elevated():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return True


def test_script_parses_with_one_invocation_and_pins_the_files_on_disk():
    result = ps("$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile('" + str(LEAF) + "',[ref]$t,[ref]$e);"
                "$s=@($a.EndBlock.Statements);'RESULT '+(@{errors=$e.Count;statements=$s.Count;functions=@($s|Where-Object{$_ -is [Management.Automation.Language.FunctionDefinitionAst]}).Count;"
                "last=$s[-1].Extent.Text;params=@($a.ParamBlock.Parameters|ForEach-Object{$_.Name.VariablePath.UserPath})}|ConvertTo-Json -Compress)")
    value = success(result)
    assert value['errors'] == 0 and value['statements'] == value['functions'] + 1
    assert value['last'].startswith('Invoke-AuthStatusLeafMain ') and value['params'] == ['Slot', 'Provider', 'Stage', 'Apply', 'Attempt']
    text = LEAF.read_text(encoding='utf-8')
    assert f"$script:sourceHash='{sha(PY)}'" in text, 'the Python helper pin must equal the file on disk'
    for path, pin in REVIEWED_PINS.items():
        assert sha(path) == pin, path
        assert pin in text, path
    assert "ValidateSet('codex','claude','gemini')" in text and text.isascii()
    for forbidden in ('Unregister-ScheduledTask', 'Stop-ScheduledTask', 'Register-ScheduledTask', 'Start-ScheduledTask', 'schtasks', 'Start-Process',
                      'Stop-Process', 'taskkill', 'Remove-Item', 'Stop-Service', '.Stop(', 'DeleteTask', 'RunAs', 'Invoke-Expression', 'cmd /c',
                      'HeldSupervisorObservation', 'ResourceObservation', 'Enabled=$false', '.Enabled=$false', '20261008-r3-v3'):
        assert forbidden not in text, forbidden


def test_reused_definitions_are_byte_identical_to_the_reviewed_sources():
    assert sha(LEAF_R3) == LEAF_R3_SHA256
    assert function_text(LEAF, 'Import-ReviewedFunctions') == function_text(RETARGET, 'Import-ReviewedFunctions')
    for name in ('Assert-VenvBinding', 'Add-AuthStatusFailureMetadata', 'Wait-StatusTaskInstance', 'Assert-CompletedStatusTask'):
        assert function_text(LEAF, name) == function_text(LEAF_R3, name), name
    # Definitions a caller imports by hash carry literal pins only (no script-scope dependency).
    for name in ('Assert-R4InstalledBindings', 'Assert-AuthStatusReceipt', 'Add-AuthStatusFailureMetadata', 'Get-DaemonTaskStates', 'Get-AuthStatusTaskResultView'):
        assert '$script:' not in function_text(LEAF, name), name


def test_constants_bind_the_r4_namespace_and_the_python_contracts():
    out = {}
    for provider in ('codex', 'claude', 'gemini'):
        code = harness(provider, 'after', imports=False) + ("'RESULT '+([ordered]@{root=$script:targetRoot;task=$script:taskName;native=$script:native;hash=$script:nativeHash;"
                                                          f"args=@($script:nativeArguments['{provider}']);"
                                                          "python=$script:python;install=$script:installRoot;limit=$script:taskTimeLimit;sddl=$script:taskSddl;wait=$script:taskWaitSeconds;"
                                                          "flags=$script:taskRegistrationFlags;"
                                                          "daemons=$script:daemonTaskNames;source=$script:source}|ConvertTo-Json -Compress)")
        out[provider] = success(ps(code))
    for provider, value in out.items():
        assert value['root'] == str(COCHEM / f'NativeAuthStatusSix4.2.7-windows-20261010-r4-v1-{ATTEMPT}-slot1-{provider}-after')
        assert value['root'] == str(COCHEM / f'{status.ROOT_PREFIX}{ATTEMPT}-slot1-{provider}-after')
        assert value['task'] == f'CoChem-4.2.7-NativeAuthStatusSix-20261010-r4-v1-{ATTEMPT}-slot1-{provider}-after'
        assert value['native'] == str(status.NATIVE / status.NATIVE_EXECUTABLES[provider])
        assert value['hash'] == status.CONTRACTS[provider]['sha256'] and value['args'] == status.CONTRACTS[provider]['arguments']
        assert value['python'] == str(R4 / '.venv' / 'Scripts' / 'python.exe') and value['install'] == str(R4)
        assert value['limit'] == 'PT3M' and value['sddl'] == SDDL and value['wait'] < 180
        assert value['flags'] == hostacl.TASK_CREATE_WITHOUT_PRINCIPAL_ACE == 18
        assert value['daemons'] == list(status.DAEMON_TASK_NAMES) and value['source'] == str(W / PY.name)


@pytest.mark.skipif(not (R4 / 'install-after.json').exists(), reason='the r4 runtime is not installed on this host')
def test_r4_installed_bindings_pass_on_the_real_receipts_read_only():
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in R4.iterdir() if p.is_file()}
    code = harness() + "try{$r=Assert-R4InstalledBindings;'RESULT '+($r|ConvertTo-Json -Compress -Depth 5)}finally{foreach($s in $held){$s.Dispose()}}"
    value = success(ps(code))
    assert value['install_receipt_sha256'] == status.INSTALL_RECEIPT_SHA256 == sha(R4 / 'install-after.json')
    assert value['source_manifest_sha256'] == status.MANIFEST_SHA256 and value['configuration_sha256'] == status.CONFIG_SHA256
    assert value['revision']['source_sha256'] == status.REVISION_SHA256 and value['revision']['files'] == 109
    assert value['source_files_verified'] == 166 and value['installed_assets_verified'] == 109
    assert value['reviewed_repair_sha256'] == status.REPAIR_SHA256
    assert {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in R4.iterdir() if p.is_file()} == before


@pytest.mark.skipif(not (R3 / 'install-after.json').exists(), reason='the r3 runtime is not installed on this host')
@pytest.mark.parametrize('change', ['r3_root', 'r3_root_with_r3_receipt_pin'])
def test_r4_installed_bindings_refuse_an_r3_root(tmp_path, change):
    text = function_text(LEAF, 'Assert-R4InstalledBindings')
    assert text.count("$root='C:\\Program Files\\CoChem\\Pipeline4.2.7-windows-20261009-r4'") == 1
    text = text.replace("$root='C:\\Program Files\\CoChem\\Pipeline4.2.7-windows-20261009-r4'", "$root='C:\\Program Files\\CoChem\\Pipeline4.2.7-windows-20261007-r3'")
    if change == 'r3_root_with_r3_receipt_pin':
        text = text.replace(status.INSTALL_RECEIPT_SHA256, status.PREVIOUS_INSTALL_RECEIPT_SHA256)
    path = tmp_path / 'inert-r3-bindings.ps1'
    path.write_text(text, encoding='utf-8')
    code = harness() + f"$f=[IO.File]::ReadAllText('{path}');. ([scriptblock]::Create($f));$ok=$false;$m='';try{{$null=Assert-R4InstalledBindings;$ok=$true}}catch{{$m=$_.Exception.Message}}finally{{foreach($s in $held){{$s.Dispose()}}}};'RESULT '+(@{{accepted=$ok;message=$m}}|ConvertTo-Json -Compress)"
    value = success(ps(code))
    assert value['accepted'] is False and value['message']
    if change == 'r3_root_with_r3_receipt_pin':
        assert 'receipt bindings differ' in value['message']


def receipt_fixture(provider, stdout, stderr, code, kind=''):
    a = status.parse_status(provider, stdout, stderr, code)
    value = {'schema': 'cochem-worker-native-auth-status/1', 'attempt': ATTEMPT, 'nonce': 'b' * 32, 'stage': 'before', 'slot': 'slot1', 'provider': provider,
             'system_sid': 'S-1-5-18', 'helper_sha256': sha(PY), 'runtime_root': str(R4),
             'install_receipt_sha256': status.INSTALL_RECEIPT_SHA256, 'source_manifest_sha256': status.MANIFEST_SHA256,
             'resource_limits_sha256': status.RESOURCE_SHA256,
             'status': 'NATIVE_SUBSCRIPTION_AUTHENTICATION_VERIFIED' if a['native_subscription_authentication_verified'] else 'AUTHENTICATION_NOT_VERIFIED',
             'config_sha256': status.CONFIG_SHA256, 'layout_sha256': status.LAYOUT_SHA256,
             'revision': {'verified': True, 'source_sha256': status.REVISION_SHA256}, 'cleanup_verified': True, 'runtime_custody_verified': True,
             'daemon_states_verified_before_and_after': True, 'native_model_jobs_executed': 0, 'login_commands_executed': 0,
             'process': {'token_matches_selected_worker': True, 'image_matches_reviewed_executable': True, 'owned_job_membership_verified': True},
             'native_executable_sha256_before': status.CONTRACTS[provider]['sha256'], 'native_executable_sha256_after': status.CONTRACTS[provider]['sha256'],
             'native_status_commands_executed': 1, 'native_exit_code': code, 'authentication': a, 'decision': status.authentication_decision(a)}
    if kind == 'failed':
        for key in ('authentication', 'native_exit_code'):
            value.pop(key)
        value.update(status='STATUS_CHECK_FAILED', decision='HOLD', cleanup_verified=False, failure_kind='timeout',
                     failure={'phase': 'native_wait', 'error_type': 'TimeoutError', 'winerror': None})
    return value


FETCH = b'Fetching available models...\n'
SIGN_IN = b'Please sign in to view available models. Launch the CLI without arguments to sign in.\n'


def gemini_envelope(status_value='SUCCESS'):
    rows = [('gemini-3.8-flash-high', 'Gemini 3.8 Flash (High)'), ('claude-opus-5-5-low', 'Claude Opus 5.5 (Low)')]
    return json.dumps({'status': status_value, 'command': {'name': 'models', 'data': {'models': [{'id': a, 'label': b} for a, b in rows]}}}).encode()


RUNTIME = (f"$runtime=[pscustomobject]@{{install_receipt_sha256='{status.INSTALL_RECEIPT_SHA256}';source_manifest_sha256='{status.MANIFEST_SHA256}';"
           f"configuration_sha256='{status.CONFIG_SHA256}';revision=[pscustomobject]@{{verified=$true;source_sha256='{status.REVISION_SHA256}'}}}};")

DECISION_CASES = [
    ('gemini', 'reuse', ''), ('gemini', 'missing', ''), ('gemini', 'error_envelope', ''), ('gemini', 'hold', ''), ('gemini', 'email', ''),
    ('gemini', 'failed', ''), ('codex', 'reuse', ''), ('codex', 'missing', ''), ('claude', 'reuse', ''),
    ('gemini', 'reuse', 'wrong_auth_kind'), ('gemini', 'reuse', 'claude_native_pin'), ('gemini', 'reuse', 'r3_runtime_root'),
    ('gemini', 'reuse', 'string_bool'), ('gemini', 'reuse', 'decision_downgraded'), ('gemini', 'missing', 'decision_upgraded'),
    ('gemini', 'reuse', 'cleanup'), ('gemini', 'reuse', 'model_job'), ('gemini', 'reuse', 'last_task_result'), ('gemini', 'reuse', 'helper_hash'),
    ('gemini', 'reuse', 'unreviewed_provider'), ('gemini', 'missing', 'image'), ('gemini', 'reuse', 'status_text')]


@pytest.mark.parametrize('provider,kind,change', DECISION_CASES)
def test_receipt_decision_table_requires_bound_evidence(tmp_path, provider, kind, change):
    raw = {'gemini': {'reuse': (gemini_envelope(), FETCH, 0), 'missing': (b'', SIGN_IN, 1), 'error_envelope': (gemini_envelope('ERROR'), FETCH, 0),
                      'hold': (b'', FETCH, 0), 'email': (gemini_envelope(), FETCH + b'owner@example.invalid\n', 0), 'failed': (b'', b'', 0)},
           'codex': {'reuse': (b'Logged in using ChatGPT', b'', 0), 'missing': (b'Not logged in', b'', 1)},
           'claude': {'reuse': (json.dumps({'loggedIn': True, 'authMethod': 'claude.ai', 'apiProvider': 'firstParty', 'subscriptionType': 'max'}).encode(), b'', 0)}}[provider][kind]
    value = receipt_fixture(provider, *raw, kind=kind)
    task_result = 0
    called_provider = provider
    if change == 'wrong_auth_kind':
        value['authentication']['auth_kind'] = 'claude.ai'
    if change == 'claude_native_pin':
        value['native_executable_sha256_before'] = value['native_executable_sha256_after'] = status.CONTRACTS['claude']['sha256']
    if change == 'r3_runtime_root':
        value['runtime_root'] = str(R3)
    if change == 'string_bool':
        value['authentication']['logged_in'] = 'true'
    if change == 'decision_downgraded':
        value['decision'] = 'ATTENDED_LOGIN_REQUIRED'
    if change == 'decision_upgraded':
        value['decision'] = 'REUSE_VERIFIED_SESSION'
    if change == 'cleanup':
        value['cleanup_verified'] = False
    if change == 'model_job':
        value['native_model_jobs_executed'] = 1
    if change == 'last_task_result':
        task_result = 1
    if change == 'helper_hash':
        value['helper_sha256'] = '0' * 64
    if change == 'unreviewed_provider':
        value['provider'] = called_provider = 'openai'
    if change == 'image':
        value['process']['image_matches_reviewed_executable'] = False
    if change == 'status_text':
        value['status'] = 'AUTHENTICATION_NOT_VERIFIED'
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps(value))
    code = (functions(LEAF) + RUNTIME + f"$v=Get-Content -LiteralPath '{path}' -Raw|ConvertFrom-Json;$task=[pscustomobject]@{{LastTaskResult={task_result}}};$ok=$false;$d=$null;"
            f"try{{$d=Assert-AuthStatusReceipt $v $task $runtime 'slot1' '{called_provider}' 'before' ('b'*32) '{sha(PY)}' '{ATTEMPT}';$ok=$true}}catch{{}};"
            "$s=[ordered]@{};Add-AuthStatusFailureMetadata $s $v;'RESULT '+([ordered]@{accepted=$ok;decision=$d;summary=$s}|ConvertTo-Json -Compress -Depth 4)")
    result = success(ps(code))
    assert result['accepted'] is (not change), result
    if not change:
        expected = 'HOLD' if kind == 'failed' else status.authentication_decision(value['authentication'])
        assert result['decision'] == expected
        assert result['decision'] == {'reuse': 'REUSE_VERIFIED_SESSION', 'missing': 'ATTENDED_LOGIN_REQUIRED', 'error_envelope': 'ATTENDED_LOGIN_REQUIRED'}.get(kind, 'HOLD')
        if kind == 'failed':
            assert result['summary']['failure'] == {'phase': 'native_wait', 'error_type': 'TimeoutError', 'winerror': None}


VIEW_CASES = [('AUTHENTICATION_NOT_VERIFIED', 'HOLD', 2, 0), ('AUTHENTICATION_NOT_VERIFIED', 'HOLD', 0, None), ('AUTHENTICATION_NOT_VERIFIED', 'HOLD', 1, None),
              ('NATIVE_SUBSCRIPTION_AUTHENTICATION_VERIFIED', 'HOLD', 2, 0), ('NATIVE_SUBSCRIPTION_AUTHENTICATION_VERIFIED', 'REUSE_VERIFIED_SESSION', 0, 0),
              ('NATIVE_SUBSCRIPTION_AUTHENTICATION_VERIFIED', 'REUSE_VERIFIED_SESSION', 2, 2), ('AUTHENTICATION_NOT_VERIFIED', 'ATTENDED_LOGIN_REQUIRED', 0, 0),
              ('AUTHENTICATION_NOT_VERIFIED', 'ATTENDED_LOGIN_REQUIRED', 2, 2), ('STATUS_CHECK_FAILED', 'HOLD', 2, 2), ('STATUS_CHECK_FAILED', 'HOLD', 0, 0)]


def test_task_result_view_requires_2_for_hold_and_matches_the_driver():
    """O-F5 (leaf ~187): run() exits 2 for every HOLD classification. The leaf presents a HOLD receipt's task result 2 as 0
    to the unchanged Assert-AuthStatusReceipt (which the driver imports by hash) and refuses any other result, exactly as
    the r4-v1 driver's Get-StatusTaskResultView does; REUSE/ATTENDED and failed receipts keep the raw task result."""
    cases = ','.join(f"@('{s}','{d}',{r})" for s, d, r, _ in VIEW_CASES)
    code = functions(LEAF) + (
        f"$d=[Management.Automation.Language.Parser]::ParseFile('{DRIVER}',[ref]$t,[ref]$e);if($e.Count){{throw $e[0]}};"
        "$f=@($d.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Get-StatusTaskResultView'},$true));"
        "if($f.Count -ne 1){throw 'driver view count'};. ([scriptblock]::Create($f[0].Extent.Text));") + (
        f"$out=@();foreach($c in @({cases})){{$receipt=[pscustomobject]@{{status=$c[0];decision=$c[1]}};$task=[pscustomobject]@{{LastTaskResult=$c[2];Marker='raw'}};$row=[ordered]@{{}};"
        "foreach($n in @('Get-AuthStatusTaskResultView','Get-StatusTaskResultView')){try{$v=& $n $receipt $task;$row[$n]=@{ok=$true;presented=$v.LastTaskResult;raw=($null -ne $v.PSObject.Properties['Marker'])}}"
        "catch{$row[$n]=@{ok=$false;error=$_.Exception.Message}}};$out+=$row};'RESULT '+(ConvertTo-Json @($out) -Compress -Depth 4)")
    rows = success(ps(code))
    assert len(rows) == len(VIEW_CASES)
    for (status_value, decision, task_result, presented), row in zip(VIEW_CASES, rows):
        leaf, driver = row['Get-AuthStatusTaskResultView'], row['Get-StatusTaskResultView']
        assert leaf == driver, (status_value, decision, task_result, row)
        if presented is None:
            assert leaf == {'ok': False, 'error': 'A HOLD status receipt requires task result 2.'}
        else:
            assert leaf['ok'] is True and leaf['presented'] == presented
            assert leaf['raw'] is (decision != 'HOLD' or status_value == 'STATUS_CHECK_FAILED')


def test_daemon_states_cover_exactly_the_four_names_and_defer_access_denied():
    code = functions(LEAF) + r"""
      $script:asked=@()
      $folder=[pscustomobject]@{};$folder|Add-Member ScriptMethod GetTask {param($name)$script:asked+=$name
        switch($name){
          'CoChem-4.2.7-Warden'{throw [Runtime.InteropServices.COMException]::new('denied',-2147024891)}
          'CoChem-4.2.7-Supervisor'{$t=[pscustomobject]@{Enabled=$false;State=1};$t|Add-Member ScriptMethod GetInstances {param($f)[pscustomobject]@{Count=0}};return $t}
          'CoChem-4.2.2-Warden'{$t=[pscustomobject]@{Enabled=$true;State=3};$t|Add-Member ScriptMethod GetInstances {param($f)[pscustomobject]@{Count=0}};return $t}
          default{throw [Runtime.InteropServices.COMException]::new('absent',-2147024894)}}}
      $states=@(Get-DaemonTaskStates $folder)
      $presence=@('ABSENT','DENIED','PRESENT','UNKNOWN'|ForEach-Object{
        $f=[pscustomobject]@{Mode=$_};$f|Add-Member ScriptMethod GetTask {param($n)switch($this.Mode){'ABSENT'{throw [Runtime.InteropServices.COMException]::new('a',-2147024894)}'DENIED'{throw [Runtime.InteropServices.COMException]::new('d',-2147024891)}'PRESENT'{[pscustomobject]@{}}default{throw [Runtime.InteropServices.COMException]::new('x',-2147467259)}}}
        try{Get-StatusTaskPresence $f 'x'}catch{'THROWN'}})
      'RESULT '+([ordered]@{asked=$script:asked;states=$states;presence=$presence}|ConvertTo-Json -Compress -Depth 4)"""
    value = success(ps(code))
    assert value['asked'] == list(status.DAEMON_TASK_NAMES)
    assert [(s['name'], s['state'], s['active']) for s in value['states']] == [
        ('CoChem-4.2.7-Warden', 'ACCESS_DENIED_DEFERRED', None), ('CoChem-4.2.7-Supervisor', 'STOPPED_DISABLED', False),
        ('CoChem-4.2.2-Warden', 'ACTIVE', True), ('CoChem-4.2.3-Supervisor', 'ABSENT', False)]
    assert value['presence'] == ['ABSENT', 'ACCESS_DENIED_DEFERRED', 'PRESENT', 'THROWN']


# The folder stub reads the task descriptor back the way this host's Task Scheduler stores it
# (task_scheduler_host_projection.py), never the requested SDDL verbatim (r5 sitting v2, 2026-10-11).
APPLY_STUBS = hostacl.PS_FUNCTION + r"""
      function Assert-CodeTreeOnce {param($Path)$script:inspected+=$Path;1}
      function Assert-ProtectedPath {param($Path)}
      function New-ProtectedDirectory {param($Path)if(Test-Path -LiteralPath $Path){throw 'exists'}
        if($script:fixtureMode -cne 'root_refused'){$null=[IO.Directory]::CreateDirectory($Path)}
        if($script:fixtureMode -clike 'root_*'){throw ('Untrusted protected owner: '+$Path)}}
      function Open-VerifiedFile {param($Path,$Sha256,$Length)
        if((Get-Item -LiteralPath $Path).Length -ne $Length -or (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Sha256){throw 'Inert fixture content drift'}
        [IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)}
      function Copy-VerifiedPayload {param($File)$i=Open-VerifiedFile $File.source $File.sha256 $File.length;try{$o=[IO.File]::Open($File.destination,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);try{$i.CopyTo($o)}finally{$o.Dispose()}}finally{$i.Dispose()}}
      function Write-RegistrationControl {param($Path,$Text)if($script:fixtureMode -ceq 'root_unwritable'){throw 'Untrusted protected owner of the held record parent.'};$s=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);try{$b=[Text.UTF8Encoding]::new($false).GetBytes($Text);$s.Write($b,0,$b.Length)}finally{$s.Dispose()};(Get-FileHash -LiteralPath $Path).Hash.ToLowerInvariant()}
      function Start-Sleep {param($Milliseconds)}
      function Get-AuthStatusHolds {param($Folder)$script:holdChecks++;[pscustomobject]@{holds=@($script:fixtureHolds);daemon_tasks=@();status_task='ABSENT'}}
      $script:inspected=@();$script:holdChecks=0;$script:registered=@();$script:runs=0;$script:registeredSddl=$null
      function New-StubTask {param($Definition)
        $t=[pscustomobject]@{State=3;LastTaskResult=$script:fixtureLastResult;Definition=$Definition}
        $t|Add-Member ScriptMethod GetInstances {param($f)[pscustomobject]@{Count=0}}
        $t|Add-Member ScriptMethod GetSecurityDescriptor {param($i)$script:registeredSddl}
        $t|Add-Member ScriptMethod Run {param($a)$script:runs++
          if($script:fixtureMode -ne 'no_receipt'){
            $arguments=$this.Definition.Actions.Item(1).Arguments;if($arguments -notmatch '--nonce ([a-f0-9]{32}) '){throw 'no nonce'};$nonce=$matches[1]
            $v=Get-Content -LiteralPath $script:fixtureReceipt -Raw|ConvertFrom-Json;$v.nonce=$nonce
            [IO.File]::WriteAllText((Join-Path $script:targetRoot 'worker-native-status.json'),($v|ConvertTo-Json -Depth 10))}
          $inst=[pscustomobject]@{State=4};$inst|Add-Member ScriptMethod Refresh {$this.State=3};$inst}
        $t}
      $scheduler=[pscustomobject]@{};$scheduler|Add-Member ScriptMethod NewTask {param($f)
        $action=[pscustomobject]@{Path='';Arguments='';WorkingDirectory=''}
        $actions=[pscustomobject]@{Count=0;Action=$action};$actions|Add-Member ScriptMethod Create {param($k)$this.Count=1;$this.Action};$actions|Add-Member ScriptMethod Item {param($i)$this.Action}
        [pscustomobject]@{RegistrationInfo=[pscustomobject]@{Description=''};Principal=[pscustomobject]@{UserId='';LogonType=0;RunLevel=0};
          Settings=[pscustomobject]@{Enabled=$false;AllowDemandStart=$false;MultipleInstances=0;ExecutionTimeLimit=''};Triggers=[pscustomobject]@{Count=0};Actions=$actions}}
      $folder=[pscustomobject]@{};$folder|Add-Member ScriptMethod RegisterTaskDefinition {param($n,$d,$f,$u,$p,$l,$s)
        $script:registeredSddl=Get-HostTaskSddlProjection $f $s $u
        $script:registered+=[pscustomobject]@{name=$n;flags=$f;user=$u;password_null=($null -eq $p);logon=$l;sddl=$s;readback=$script:registeredSddl;
          principal=@($d.Principal.UserId,$d.Principal.LogonType,$d.Principal.RunLevel);limit=$d.Settings.ExecutionTimeLimit;multiple=$d.Settings.MultipleInstances;
          enabled=$d.Settings.Enabled;demand=$d.Settings.AllowDemandStart;triggers=$d.Triggers.Count;path=$d.Actions.Item(1).Path;arguments=$d.Actions.Item(1).Arguments;
          working=$d.Actions.Item(1).WorkingDirectory;description=$d.RegistrationInfo.Description}
        if($script:fixtureMode -eq 'bad_limit'){$d.Settings.ExecutionTimeLimit='PT0S'}
        New-StubTask $d}
"""


def drive_apply(tmp_path, mode='', receipt=None, last_result=0, holds=(), flags=None):
    fixture = tmp_path / 'fixture-receipt.json'
    fixture.write_text(json.dumps(receipt or receipt_fixture('gemini', gemini_envelope(), FETCH, 0)))
    holds_ps = ','.join("'" + h + "'" for h in holds) or ''
    override = '' if flags is None else f'$script:taskRegistrationFlags={int(flags)};'
    code = harness() + APPLY_STUBS + RUNTIME + override + (
        f"$script:fixtureMode='{mode}';$script:fixtureReceipt='{fixture}';$script:fixtureLastResult={last_result};$script:fixtureHolds=@({holds_ps});"
        f"$script:targetRoot=Join-Path '{tmp_path}' (Split-Path -Leaf $script:targetRoot);$out=$null;$message=$null;"
        f"try{{$out=Invoke-AuthStatusApply $scheduler $folder $runtime 'slot1' 'gemini' 'before' '{ATTEMPT}'}}catch{{$message=$_.Exception.Message}}finally{{foreach($s in $held){{$s.Dispose()}}}};"
        "'RESULT '+([ordered]@{summary=$out;message=$message;registered=$script:registered;runs=$script:runs;inspected=$script:inspected;hold_checks=$script:holdChecks;root=$script:targetRoot}|ConvertTo-Json -Compress -Depth 6)")
    result = ps(code)
    return success(result), result.stdout


def test_apply_tail_registers_one_reviewed_system_task_and_binds_the_receipt(tmp_path):
    value, stdout = drive_apply(tmp_path)
    root = Path(value['root'])
    assert root.name == f'{status.ROOT_PREFIX}{ATTEMPT}-slot1-gemini-before' and value['message'] is None
    assert value['runs'] == 1 and value['hold_checks'] == 1 and value['inspected'] == [str(R4), str(status.BASE_PYTHON.parent), str(status.NATIVE)]
    [registered] = value['registered']
    assert registered['name'] == f'CoChem-4.2.7-NativeAuthStatusSix-20261010-r4-v1-{ATTEMPT}-slot1-gemini-before'
    assert registered['flags'] == 18 and registered['user'] == 'SYSTEM' and registered['password_null'] is True and registered['logon'] == 5
    assert registered['sddl'] == SDDL and registered['principal'] == ['SYSTEM', 5, 1] and registered['triggers'] == 0
    assert registered['readback'] == hostacl.HOST_SDDL_AFTER_FLAGS_18
    assert registered['limit'] == 'PT3M' and registered['multiple'] == 2 and registered['enabled'] is True and registered['demand'] is True
    assert registered['path'] == str(R4 / '.venv' / 'Scripts' / 'python.exe') and registered['working'] == str(root)
    nonce = value['summary']['nonce']
    assert re.fullmatch('[a-f0-9]{32}', nonce)
    assert registered['arguments'] == f'-I -B "{root / PY.name}" --slot slot1 --provider gemini --nonce {nonce} --stage before --attempt {ATTEMPT}'
    assert 'r4 runtime' in registered['description'] and 'No login, model inference' in registered['description']
    assert (root / PY.name).read_bytes() == PY.read_bytes()
    summary = value['summary']
    assert summary['schema'] == 'cochem-worker-native-auth-status-task-result/1' and summary['decision'] == 'REUSE_VERIFIED_SESSION'
    assert summary['runtime_root'] == str(R4) and summary['receipt_path'] == str(root / 'worker-native-status.json')
    assert summary['receipt_sha256'] == sha(root / 'worker-native-status.json') and summary['task_preserved'] is True
    assert json.loads((root / 'status-task-result.json').read_text(encoding='utf-8')) == summary
    assert not (root / 'status-held.json').exists() and 'COCHEM_NATIVE_AUTH_STATUS_RESULT' not in stdout


@pytest.mark.parametrize('flags', [hostacl.TASK_CREATE, hostacl.TASK_CREATE_WITHOUT_PRINCIPAL_ACE])
def test_registration_flags_against_the_host_task_acl_read_back(tmp_path, flags):
    """r5 sitting v2 regression (2026-10-11, 12 of 12 S3 checks held at REGISTER): with TASK_CREATE alone (2) this host reads
    the task DACL back unprotected with an appended (A;;FR;;;SY) ACE, so the exact Assert-RegisteredTaskAcl holds before any
    Run; the reviewed flags 18 (TASK_CREATE|TASK_DONT_ADD_PRINCIPAL_ACE) read back as D:PAI with exactly the two requested
    ACEs and the check runs. The realistic folder stub models both (task_scheduler_host_projection.py)."""
    value, stdout = drive_apply(tmp_path, flags=flags)
    root = Path(value['root'])
    [registered] = value['registered']
    assert registered['flags'] == flags and registered['sddl'] == SDDL == hostacl.PRIVATE_TASK_SDDL
    assert registered['readback'] == hostacl.host_projection(flags, SDDL, 'SYSTEM')
    if flags == hostacl.TASK_CREATE:
        assert registered['readback'] == hostacl.HOST_SDDL_AFTER_FLAGS_2
        assert value['summary'] is None and value['runs'] == 0 and 'COCHEM_NATIVE_AUTH_STATUS_RESULT' not in stdout
        assert value['message'].startswith('The status check is held at task registration: ' + hostacl.HELD_ACL_REASON + ' The task may exist but was never run.')
        held = json.loads((root / 'status-held.json').read_text(encoding='utf-8'))
        assert held['phase'] == 'REGISTER' and held['reason'] == hostacl.HELD_ACL_REASON
        assert held['task_registered'] is True and held['run_requested'] is False and not (root / 'status-task-result.json').exists()
    else:
        assert registered['readback'] == hostacl.HOST_SDDL_AFTER_FLAGS_18
        assert value['message'] is None and value['runs'] == 1 and value['summary']['decision'] == 'REUSE_VERIFIED_SESSION'
        assert (root / 'status-task-result.json').exists() and not (root / 'status-held.json').exists()


APPLY_TAIL_CASES =[('hold', 'hold', 'HOLD', 2), ('failed', 'failed', 'HOLD', 2), ('failed_exit0', 'failed', 'HOLD', 0), ('no_receipt', 'reuse', 'RECEIPT', 0),
                    ('bad_limit', 'reuse', 'REGISTER', 0), ('last_result', 'reuse', 'DECISION', 1), ('hold_exit0', 'hold', 'DECISION', 0),
                    ('reuse_exit2', 'reuse', 'DECISION', 2), ('missing_exit2', 'missing', 'DECISION', 2), ('missing', 'missing', '', 0), ('reuse', 'reuse', '', 0)]


@pytest.mark.parametrize('mode,kind,phase,last_result', APPLY_TAIL_CASES)
def test_apply_tail_failures_leave_a_held_record_and_a_plain_message(tmp_path, mode, kind, phase, last_result):
    """O-F5: a classification HOLD ends with task result 2 (run() exits 2), so the realistic 'hold' row uses 2 and reaches
    the HOLD path with its COCHEM_NATIVE_AUTH_STATUS_RESULT line (the driver's Get-StatusTaskResultView path). A HOLD
    receipt with task result 0, or an established decision with task result 2, is refused at DECISION without the line."""
    raw = {'hold': (b'', FETCH, 0), 'failed': (b'', b'', 0), 'reuse': (gemini_envelope(), FETCH, 0), 'missing': (b'', SIGN_IN, 1)}[kind]
    value, stdout = drive_apply(tmp_path, mode, receipt_fixture('gemini', *raw, kind=kind), last_result=last_result)
    root = Path(value['root'])
    tagged = [line for line in stdout.splitlines() if line.startswith('COCHEM_NATIVE_AUTH_STATUS_RESULT ')]
    if not phase:
        assert value['message'] is None and value['summary']['decision'] == {'missing': 'ATTENDED_LOGIN_REQUIRED', 'reuse': 'REUSE_VERIFIED_SESSION'}[kind]
        assert value['summary']['last_task_result'] == 0 and tagged == []
        assert (root / 'status-task-result.json').exists() and not (root / 'status-held.json').exists()
        return
    assert value['summary'] is None and value['message']
    held = json.loads((root / 'status-held.json').read_text(encoding='utf-8'))
    assert held['schema'] == 'cochem-worker-native-auth-status-held/1' and held['phase'] == phase and held['decision'] == 'HOLD'
    assert held['automatic_retry_allowed'] is False and held['login_authorized'] is False and held['requires_owner_review'] is True
    assert held['task_name'] == value['registered'][0]['name'] and held['task_registered'] is True and held['root_verified'] is True
    assert held['run_requested'] is (mode != 'bad_limit') and value['runs'] == (0 if mode == 'bad_limit' else 1)
    assert 'status-held.json' in value['message'] and 'automatic retry' in value['message']
    if phase == 'HOLD':
        assert len(tagged) == 1
        line = json.loads(tagged[0].split(' ', 1)[1])
        assert line['decision'] == 'HOLD' and line['last_task_result'] == last_result and line['receipt_sha256'] == sha(root / 'worker-native-status.json')
        assert line == held['summary'] and held['summary']['schema'] == 'cochem-worker-native-auth-status-task-result/1'
        assert value['message'].startswith('Status is not an established subscription or explicit logged-out state.')
        assert held['receipt_present'] is True and held['receipt_sha256'] == sha(root / 'worker-native-status.json')
    else:
        assert tagged == []
    if mode == 'hold_exit0':
        assert held['reason'] == 'A HOLD status receipt requires task result 2.' and held['summary'] is None
    if mode in ('reuse_exit2', 'missing_exit2', 'last_result'):
        assert held['reason'] == 'Status receipt configuration/result binding differs.' and held['summary'] is None
    if kind == 'failed':
        assert held['summary']['failure'] == {'phase': 'native_wait', 'error_type': 'TimeoutError', 'winerror': None}
    assert 'owner@example.invalid' not in (root / 'status-held.json').read_text(encoding='utf-8')
    assert not (root / 'status-task-result.json').exists()


@pytest.mark.parametrize('mode', ['root_acl', 'root_unwritable', 'root_refused'])
def test_apply_tail_root_creation_runs_inside_the_held_record_guard(tmp_path, mode):
    """Wave-1 low (leaf ~333): New-ProtectedDirectory runs inside the try as phase ROOT. A root that exists after its
    post-create check failed is the consumed one-shot namespace: status-held.json records it (root_verified false) and
    the plain message names the root, also when the held record cannot be written. A root never created changes nothing."""
    value, stdout = drive_apply(tmp_path, mode)
    root = Path(value['root'])
    assert value['summary'] is None and value['registered'] == [] and value['runs'] == 0 and value['hold_checks'] == 1
    assert 'COCHEM_NATIVE_AUTH_STATUS_RESULT' not in stdout
    reason = f'Untrusted protected owner: {root}'
    if mode == 'root_refused':
        assert not root.exists()
        assert value['message'] == f'Status check is held before its one-shot root was created: {reason} Nothing was changed.'
        return
    assert root.is_dir() and not (root / PY.name).exists() and not (root / 'status-task-result.json').exists()
    assert value['message'].startswith(f'The status check is held while creating its one-shot root: {reason} No task was registered. Preserve {root} ')
    assert 'automatic retry' in value['message'] and 'status-held.json' in value['message']
    if mode == 'root_unwritable':
        assert not (root / 'status-held.json').exists()
        assert value['message'].endswith(' The held record could not be written: Untrusted protected owner of the held record parent.')
        return
    held = json.loads((root / 'status-held.json').read_text(encoding='utf-8'))
    assert held['schema'] == 'cochem-worker-native-auth-status-held/1' and held['phase'] == 'ROOT' and held['reason'] == reason
    assert held['root_verified'] is False and held['target_root'] == str(root) and held['task_registered'] is False and held['run_requested'] is False
    assert held['task_after'] is None and held['receipt_present'] is False and held['receipt_sha256'] is None and held['summary'] is None
    assert held['decision'] == 'HOLD' and held['automatic_retry_allowed'] is False and held['requires_owner_review'] is True


def test_apply_tail_with_a_hold_changes_nothing(tmp_path):
    value, _ = drive_apply(tmp_path, holds=('Protected daemons must remain stopped and disabled: CoChem-4.2.7-Warden',))
    assert value['message'].startswith('Status check is held. Nothing was changed: Protected daemons')
    assert value['registered'] == [] and value['runs'] == 0 and not Path(value['root']).exists()


def cochem_listing():
    return sorted(p.name for p in COCHEM.iterdir())


def run_leaf(*args, timeout=240):
    return subprocess.run([PS, '-NoProfile', '-NonInteractive', '-File', str(LEAF), *args], capture_output=True, text=True, timeout=timeout)


@pytest.mark.skipif(not (R4 / 'install-after.json').exists(), reason='the r4 runtime is not installed on this host')
@pytest.mark.parametrize('provider', ['gemini', 'codex', 'claude'])
def test_read_only_plan_creates_nothing(provider):
    before = cochem_listing()
    result = run_leaf('-Slot', 'slot1', '-Provider', provider, '-Stage', 'before', '-Attempt', ATTEMPT)
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan['schema'] == 'cochem-worker-native-auth-status-plan/1' and plan['mode'] == 'READ_ONLY_PLAN'
    assert plan['provider'] == provider and plan['r4_runtime_verified'] is True and plan['runtime_root'] == str(R4)
    assert plan['install_receipt_sha256'] == status.INSTALL_RECEIPT_SHA256 and plan['revision_sha256'] == status.REVISION_SHA256
    assert plan['source_sha256'] == sha(PY) and plan['native_sha256'] == status.CONTRACTS[provider]['sha256']
    assert plan['native_status_arguments'] == status.CONTRACTS[provider]['arguments'] and plan['task_execution_time_limit'] == 'PT3M'
    assert plan['native_status_commands_executed'] == 0 and plan['tasks_changed'] == 0 and plan['logins_executed'] == 0
    assert plan['status_task'] == 'ABSENT' and [d['name'] for d in plan['daemon_tasks']] == list(status.DAEMON_TASK_NAMES)
    assert not any('helper' in hold.lower() or 'r4 stopped runtime' in hold for hold in plan['holds']), plan['holds']
    assert not Path(plan['target_root']).exists() and cochem_listing() == before


def squeezed(text):
    """Console error records may wrap anywhere; compare without whitespace."""
    return re.sub(r'\s+', '', text)


def test_validate_set_and_attempt_rules():
    refused = [('-Provider', 'openai'), ('-Slot', 'slot7'), ('-Stage', 'during')]
    for flag, bad in refused:
        args = {'-Slot': 'slot1', '-Provider': 'gemini', '-Stage': 'before'}
        args[flag] = bad
        result = run_leaf(*[x for pair in args.items() for x in pair], timeout=60)
        assert result.returncode != 0 and 'ValidateSet' in squeezed(result.stderr), (flag, result.stderr)
        assert result.stdout.strip() == ''
    result = run_leaf('-Slot', 'slot1', '-Provider', 'gemini', '-Stage', 'before', '-Attempt', 'A' * 32, timeout=60)
    assert result.returncode != 0 and squeezed('lowercase32-hex Attempt') in squeezed(result.stderr)


def test_apply_guards_refuse_before_any_change_at_function_level():
    """Wave-1 finding (medium): the leaf is never run with -Apply. The attempt guard, the first statement of
    Invoke-AuthStatusLeafMain, is driven from the AST with the all-zero attempt (constants, imports and the apply
    tail are sentinels); the owner/elevation guard is checked by AST position ahead of every constant or import."""
    code = functions(LEAF) + (
        "function Set-AuthStatusConstants {throw 'SENTINEL: constants reached'};function Get-AuthStatusHelperDefinitions {throw 'SENTINEL: imports reached'};"
        "function Invoke-AuthStatusApply {throw 'SENTINEL: apply reached'};"
        f"$m=$null;try{{Invoke-AuthStatusLeafMain -Slot 'slot1' -Provider 'gemini' -Stage 'before' -Attempt '{'0' * 32}' -ApplyRequested $true -ScriptRoot '{W}'}}catch{{$m=$_.Exception.Message}};"
        f"$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('{LEAF}',[ref]$t,[ref]$e);"
        "$f=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Invoke-AuthStatusLeafMain'},$true))[0];"
        "'RESULT '+([ordered]@{message=$m;statements=@($f.Body.EndBlock.Statements|ForEach-Object{$_.Extent.Text})}|ConvertTo-Json -Compress)")
    value = success(ps(code))
    assert value['message'] == 'A lowercase32-hex Attempt is required; Apply forbids the all-zero preview attempt.'
    statements = value['statements']
    assert statements[0].startswith("if($Attempt -cnotmatch '^[a-f0-9]{32}$' -or ($ApplyRequested -and $Attempt -ceq '00000000000000000000000000000000'))")
    guard = [i for i, s in enumerate(statements) if '-Apply requires the owner in Administrator Windows PowerShell; nothing was executed.' in s]
    assert len(guard) == 1 and statements[guard[0]].startswith("if($ApplyRequested -and (-not $admin -or $identity.Name -cne 'AETHERDESK\\ansac'))")
    assert statements[guard[0] - 1].startswith('$admin=[Security.Principal.WindowsPrincipal]::new($identity).IsInRole(')
    constants = [i for i, s in enumerate(statements) if s.startswith('Set-AuthStatusConstants ')]
    assert len(constants) == 1 and guard[0] < constants[0]
    for statement in statements[:guard[0]]:
        for later in ('Set-AuthStatusConstants', 'Get-AuthStatusHelperDefinitions', 'Invoke-AuthStatusApply', 'Schedule.Service', 'New-ProtectedDirectory'):
            assert later not in statement, later


# ------------------------------------------------------------------- top level, plan mode only (ps_toplevel_smoke.py)
# The fixtures above dot-source single functions; these run the REAL leaf top level (real param block and binding, the
# 2026-10-11 17:22 failure class) with the host stubbed. The helper refuses -Apply, so each documented call runs as its
# plan: RUN_427_R5_SITTING.ps1 S3 (twelve calls, -Stage before) and the six-worker driver's before/after checks.

PLAN_SCHEMA = 'cochem-worker-native-auth-status-plan/1'
SMOKE_CALLS = ([pytest.param(provider, slot, 'before', 'file', id=f'S3-{provider}-{slot}') for provider in ('claude', 'codex') for slot in
                [f'slot{n}' for n in range(1, 7)]]
               + [pytest.param('gemini', 'slot1', 'before', 'command', id='driver-gemini-before-typed'),
                  pytest.param('gemini', 'slot6', 'after', 'file', id='driver-gemini-after'),
                  pytest.param('claude', 'slot3', 'after', 'command', id='driver-claude-after-typed')])


@pytest.mark.parametrize('provider,slot,stage,invocation', SMOKE_CALLS)
def test_toplevel_plan_for_each_documented_call(provider, slot, stage, invocation):
    args = ['-Slot', slot, '-Provider', provider, '-Stage', stage, '-Attempt', ATTEMPT]
    result = smoke.run_toplevel(LEAF, args, invocation=invocation)
    assert smoke.plan_mode_outcome(result, plan_schema=PLAN_SCHEMA) == 'plan', result.describe()
    plan = result.plan
    assert (plan['attempt'], plan['slot'], plan['provider'], plan['stage']) == (ATTEMPT, slot, provider, stage)
    assert plan['native_status_commands_executed'] == 0 and plan['tasks_changed'] == 0 and isinstance(plan['holds'], list)
