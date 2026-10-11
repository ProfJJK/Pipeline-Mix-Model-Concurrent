"""Inert harness for agy-session-history-r4-v1.ps1: receipt classification table and inventory rules.

Receipts are produced by the real bridge run() against fakes (test_agy_login_bridge_r4_v1.generate). The history
functions are dot-sourced from the script AST into powershell.exe; tasks and the scheduler folder are fixtures, and
the protected-path, reparse, layout and ACL checks are stubbed (the ACL predicate itself is tested on in-memory ACL
objects). No real task, Program Files path, worker profile or credential is touched.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

W = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('agy_bridge_fixtures_for_history', W / 'test_agy_login_bridge_r4_v1.py')
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)

HISTORY = W / 'agy-session-history-r4-v1.ps1'
STAGE = Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1')
STATUS = W / 'check-worker-native-status-r3.ps1'
V6 = W / 'login_pipeline_worker_interactive_r3_v6.ps1'
q = fx.q
EXPECTED_CODES = {name: 0 for name in ('print_exit_zero', 'print_echo', 'tui_terminated', 'callback_exit_zero')}


def ps_named(path, names):
    """Dot-source only the named function definitions of a script (from its AST)."""
    wanted = ','.join(q(name) for name in names)
    return ("$__tokens=$null;$__errors=$null;$__ast=[Management.Automation.Language.Parser]::ParseFile(" + q(path) + ",[ref]$__tokens,[ref]$__errors);"
            "if($__errors.Count){throw ($__errors|Out-String)};$__wanted=@(" + wanted + ");"
            "foreach($__f in $__ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){if($__f.Name -cin $__wanted){. ([scriptblock]::Create($__f.Extent.Text))}};\n")


PRELUDE = None


def prelude():
    global PRELUDE
    if PRELUDE is None:
        PRELUDE = (fx.ps_functions(HISTORY) + ps_named(STAGE, ['Initialize-FileIdentity', 'Open-VerifiedFile'])
                   + ps_named(STATUS, ['Read-R3Control', 'Read-R3Text']) + ps_named(V6, ['Get-ExactTaskOrAbsent']) + r'''
function Assert-NoReparseAncestors {param([string]$Path)}
function Assert-ProtectedPath {param([string]$Path)}
Initialize-FileIdentity
$held=[Collections.Generic.List[IO.FileStream]]::new()
$script:runtime=[ordered]@{install_receipt_sha256='629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502';source_manifest_sha256='1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189';configuration_sha256='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c';revision=[pscustomobject]@{source_sha256='38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e'}}
$script:sid=''' + q(fx.SID) + r'''
function New-FixtureTask {
    param([string]$Name,[string]$Root,[string]$Arguments,[int]$State=3,$LastTaskResult=0,[int]$Instances=0,[string]$Path='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\Scripts\python.exe',
          [string]$Limit='PT15M',[int]$Restart=0,[int]$Triggers=0,[string]$User='SYSTEM',[string]$WorkingDirectory=$null)
    if(-not $WorkingDirectory){$WorkingDirectory=$Root}
    $action=[pscustomobject]@{Type=0;Path=$Path;Arguments=$Arguments;WorkingDirectory=$WorkingDirectory}
    $actions=[pscustomobject]@{Count=1;Action=$action};$actions|Add-Member ScriptMethod Item {param($index) if($index -ne 1){throw 'fixture index'};$this.Action}
    $definition=[pscustomobject]@{Principal=[pscustomobject]@{UserId=$User;LogonType=5;RunLevel=1};Triggers=[pscustomobject]@{Count=$Triggers};Actions=$actions;
        Settings=[pscustomobject]@{MultipleInstances=2;ExecutionTimeLimit=$Limit;RestartCount=$Restart;AllowDemandStart=$true}}
    $task=[pscustomobject]@{Name=$Name;State=$State;LastTaskResult=$LastTaskResult;Definition=$definition;InstanceCount=$Instances;Enabled=$true}
    $task|Add-Member ScriptMethod GetInstances {param($flags)[pscustomobject]@{Count=$this.InstanceCount}}
    $task|Add-Member ScriptMethod GetSecurityDescriptor {param($flags)'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'}
    $task
}
function New-FixtureFolder {
    $folder=[pscustomobject]@{Tasks=@{}}
    $folder|Add-Member ScriptMethod GetTask {param($name) if($this.Tasks.ContainsKey($name)){return $this.Tasks[$name]};throw [Runtime.InteropServices.COMException]::new('fixture task missing',-2147024894)}
    $folder|Add-Member ScriptMethod GetTasks {param($flags) [object[]]@($this.Tasks.Values)}
    $folder
}
''')
    return PRELUDE


@pytest.fixture(scope='module')
def generated(tmp_path_factory):
    return fx.receipts(tmp_path_factory.mktemp('agy-history-receipts'))


def classify(tmp_path, cases):
    """cases: list of dicts {name, path, nonce, slot, mode, task_mode, last, runtime}. Returns name -> result."""
    case_file = tmp_path / 'cases.json'
    case_file.write_text(json.dumps(cases), encoding='utf-8')
    body = prelude() + "$cases=Get-Content -LiteralPath " + q(case_file) + r''' -Raw -Encoding UTF8|ConvertFrom-Json
$results=[ordered]@{}
foreach($case in $cases){
    $receipt=Get-Content -LiteralPath $case.path -Raw -Encoding UTF8|ConvertFrom-Json
    $root='C:\Program Files\CoChem\InteractiveAgy427-r4-'+$case.slot+'-'+$case.nonce
    $task=New-FixtureTask -Name ('CoChem-4.2.7-InteractiveAgy-r4-'+$case.slot+'-'+$case.nonce) -Root $root -Arguments (Get-AgyHistoryTaskArguments $root $case.slot $case.nonce $case.task_mode) -LastTaskResult $case.last
    $runtime=$script:runtime
    if($case.runtime -ceq 'other'){$runtime=[ordered]@{install_receipt_sha256=$script:runtime.install_receipt_sha256;source_manifest_sha256=$script:runtime.source_manifest_sha256;configuration_sha256=$script:runtime.configuration_sha256;revision=[pscustomobject]@{source_sha256=('9'*64)}}}
    try{
        $proof=Assert-AgyHistoryReceipt $receipt $task $case.slot $case.nonce $case.mode $runtime $script:sid
        $results[$case.name]=[ordered]@{ok=$true;proof=$proof}
    }catch{
        $results[$case.name]=[ordered]@{ok=$false;message=$_.Exception.Message;metadata=$_.Exception.Data['CoChemAgyHistorySafeMetadata']}
    }
}
$results|ConvertTo-Json -Depth 8 -Compress
'''
    return json.loads(fx.ps_run(body))


def case(name, path, mode='print', last=0, **extra):
    value = {'name': name, 'path': str(path), 'nonce': fx.NONCE, 'slot': fx.SLOT, 'mode': mode, 'task_mode': mode, 'last': last, 'runtime': 'same'}
    value.update(extra)
    return value


EXPECTED = {
    'print_exit_zero': ('TERMINAL_NATIVE_LOGIN_CLEANUP_VERIFIED', True, False),
    'print_echo': ('TERMINAL_NATIVE_LOGIN_CLEANUP_VERIFIED', True, False),
    'tui_terminated': ('TERMINAL_NATIVE_LOGIN_CLEANUP_VERIFIED', True, False),
    'callback_exit_zero': ('TERMINAL_NATIVE_LOGIN_CLEANUP_VERIFIED', True, False),
    'fail_before_input': ('TERMINAL_NATIVE_LOGIN_CLEANUP_VERIFIED', False, False),
    'fail_after_input': ('TERMINAL_NATIVE_LOGIN_CLEANUP_VERIFIED', False, False),
    'rate_limited': ('TERMINAL_NATIVE_LOGIN_CLEANUP_VERIFIED', False, True),
    'cancelled': ('TERMINAL_CANCELLED_NATIVE_LOGIN_CLEANUP_VERIFIED', False, False),
    'timed_out': ('TERMINAL_TIMED_OUT_NATIVE_LOGIN_CLEANUP_VERIFIED', False, False),
    'verify_cancelled': ('TERMINAL_CANCELLED_NATIVE_LOGIN_CLEANUP_VERIFIED', False, True),
    'native_custody_failure': ('TERMINAL_PRE_NATIVE_CUSTODY_FAILURE_NO_CHILD_LAUNCHED', False, False),
    # O-F7: the sanitized pre-input bound stop is a reviewed terminal class, so it never blocks the slot.
    'output_bound': ('TERMINAL_OUTPUT_BOUND_NATIVE_LOGIN_CLEANUP_VERIFIED', False, False),
}
DIAGNOSIS = {'agy_changed_after': 'LOGIN_FAILED_OR_CANCELLED', 'cleanup_unverified': 'CLEANUP_UNVERIFIED'}
SAFE_KEYS = {'status', 'login_mode', 'login_commands_executed', 'model_jobs_executed', 'pause_marker_seen', 'one_line_submitted',
             'terminated_after_input', 'operator_cancelled', 'cleanup_verified', 'native_exit_code', 'failure', 'login_failure', 'markers_seen',
             'input_closed_marker_written', 'native_output_bound_reached_before_input'}


def test_classification_table_over_real_bridge_receipts(tmp_path, generated):
    cases = [case(name, item['root'] / 'receipt.json', mode=fx.SCENARIOS[name]['mode'], last=item['code'])
             for name, item in generated.items()]
    results = classify(tmp_path, cases)
    assert set(results) == set(EXPECTED) | set(DIAGNOSIS)
    for name, (classification, accepted, pause) in EXPECTED.items():
        result = results[name]
        assert result['ok'], (name, result)
        proof = result['proof']
        assert (proof['classification'], proof['accepted'], proof['pause_marker_seen']) == (classification, accepted, pause), name
        assert proof['authentication_authorized_by_history'] is False and proof['model_jobs_executed'] == 0
        assert proof['status'] == generated[name]['receipt']['status'] and proof['login_mode'] == fx.SCENARIOS[name]['mode']
    assert set(results['fail_before_input']['proof']['failure_markers']) == {'authentication_required_present', 'no_controlling_terminal_present'}
    assert results['fail_after_input']['proof']['failure_markers'] == ['authentication_failed_present']
    assert results['tui_terminated']['proof']['terminated_after_input'] is True
    assert results['callback_exit_zero']['proof']['one_line_submitted'] is False
    assert results['print_exit_zero']['proof']['file_token_present'] is True
    assert results['print_exit_zero']['proof']['credential_manager_entry_present'] is False
    for name, status in DIAGNOSIS.items():
        result = results[name]
        assert not result['ok'] and result['message'].startswith('Historical agy receipt requires diagnosis')
        assert result['metadata']['status'] == status and set(result['metadata']) <= SAFE_KEYS
    text = json.dumps(results)
    assert fx.CODE.decode() not in text and fx.EMAIL not in text and 'https://' not in text


def test_both_accepted_statuses_require_their_task_result_and_failures_require_two(tmp_path, generated):
    cases = []
    for name in ('print_exit_zero', 'tui_terminated'):
        cases.append(case(name + '_last2', generated[name]['root'] / 'receipt.json', mode=fx.SCENARIOS[name]['mode'], last=2))
    for name in ('fail_before_input', 'cancelled', 'timed_out', 'native_custody_failure', 'output_bound'):
        cases.append(case(name + '_last0', generated[name]['root'] / 'receipt.json', mode=fx.SCENARIOS[name]['mode'], last=0))
    cases.append(case('print_as_tui_task', generated['print_exit_zero']['root'] / 'receipt.json', mode='print', task_mode='tui'))
    cases.append(case('print_claimed_tui', generated['print_exit_zero']['root'] / 'receipt.json', mode='tui'))
    cases.append(case('other_runtime', generated['print_exit_zero']['root'] / 'receipt.json', runtime='other'))
    cases.append(case('other_slot', generated['print_exit_zero']['root'] / 'receipt.json', slot='slot4'))
    cases.append(case('other_nonce', generated['print_exit_zero']['root'] / 'receipt.json', nonce='f' * 32))
    results = classify(tmp_path, cases)
    for name, result in results.items():
        assert not result['ok'], name
        assert result['message'].startswith('Historical agy receipt requires diagnosis'), name


MUTATIONS = {
    'extra_field_with_code': lambda r: r.update(raw_output=fx.CODE.decode()),
    'missing_markers': lambda r: r.pop('native_markers'),
    'helper_changed': lambda r: r.update(helper_sha256='e' * 64),
    'support_changed': lambda r: r.update(support_sha256='e' * 64),
    'arguments_for_tui': lambda r: r.update(native_arguments=[]),
    'arguments_extra': lambda r: r.update(native_arguments=['-p', '/model', '--yolo']),
    'authentication_claim': lambda r: r.update(authentication_verified=True),
    'secret_published': lambda r: r.update(secret_published=True),
    'after_input_published': lambda r: r.update(native_output_after_input_published=True),
    'pause_contradiction': lambda r: r.update(pause_marker_seen=True),
    'marker_extra_name': lambda r: r['native_markers']['before_input'].update(account_email_present=True),
    'marker_string_value': lambda r: r['native_markers']['after_input'].update(token_exchanged_present='true'),
    'token_read_claim': lambda r: r['token_storage_observed'].update(token_contents_read=True),
    'token_presence_null': lambda r: r['token_storage_observed'].update(file_token_present=None),
    'credential_count_mismatch': lambda r: r['token_storage_observed'].update(credential_manager_matching_entries=3),
    'exit_code_nonzero': lambda r: r.update(native_exit_code=1),
    'exit_code_missing': lambda r: r.pop('native_exit_code'),
    'process_sid': lambda r: r['process'].update(token_sid='S-1-5-21-9-9-9-9'),
    'process_flag_false': lambda r: r['process'].update(owned_job_membership_verified=False),
    'input_not_deleted': lambda r: r.update(input_file_deleted=False),
    'revision_files': lambda r: r['revision'].update(files=108),
    'install_pin': lambda r: r.update(install_receipt_sha256='a' * 64),
    'config_pin': lambda r: r.update(config_sha256='a' * 64),
    'failure_added': lambda r: r.update(failure={'phase': 'native_wait', 'error_type': 'TimeoutError', 'winerror': None}),
    'agy_after_differs': lambda r: r.update(native_executable_sha256_after='2' * 64),
    'model_job_claim': lambda r: r.update(model_jobs_executed=1),
    'login_count_string': lambda r: r.update(login_commands_executed='1'),
    'cleanup_array': lambda r: r.update(cleanup_verified=[True]),
    'schema_changed': lambda r: r.update(schema='cochem-interactive-claude-login/1'),
    'cancelled_flag': lambda r: r.update(operator_cancelled=True),
    'terminated_flag': lambda r: r.update(terminated_after_input=True),
    # Raw pre-input bytes are bounded by the login window (O-F7); the published display bytes keep the 131072 bound.
    'output_bytes_negative': lambda r: r.update(native_output_bytes_before_input=-1),
    'output_bytes_string': lambda r: r.update(native_output_bytes_before_input='8'),
    'published_bytes_over_bound': lambda r: r.update(native_output_published_bytes_before_input=131073),
    'published_bytes_missing': lambda r: r.pop('native_output_published_bytes_before_input'),
    'bound_reached_claim': lambda r: r.update(native_output_bound_reached_before_input=True),
    'bound_reached_string': lambda r: r.update(native_output_bound_reached_before_input='false'),
    'closed_marker_not_written': lambda r: r.update(input_closed_marker_written=False),
    'closed_marker_missing': lambda r: r.pop('input_closed_marker_written'),
}


def test_raw_pre_input_bytes_beyond_the_published_bound_are_accepted(tmp_path, generated):
    """O-F7: raw redraw bytes are bounded by time, not by count; only the published bytes are bounded."""
    value = copy.deepcopy(generated['print_exit_zero']['receipt'])
    value['native_output_bytes_before_input'] = 50 * 131072
    path = tmp_path / 'raw.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    result = classify(tmp_path, [case('raw', path)])['raw']
    assert result['ok'] and result['proof']['classification'] == 'TERMINAL_NATIVE_LOGIN_CLEANUP_VERIFIED'


@pytest.mark.parametrize('base', ['print_exit_zero'])
def test_every_mutation_of_an_accepted_receipt_requires_diagnosis_without_leaking(tmp_path, generated, base):
    original = generated[base]['receipt']
    cases = []
    for name, mutate in MUTATIONS.items():
        value = copy.deepcopy(original)
        mutate(value)
        path = tmp_path / (name + '.json')
        path.write_text(json.dumps(value), encoding='utf-8')
        cases.append(case(name, path))
    cases.append(case('control_unmutated', generated[base]['root'] / 'receipt.json'))
    results = classify(tmp_path, cases)
    assert results.pop('control_unmutated')['ok']
    for name, result in results.items():
        assert not result['ok'], name
        assert set(result['metadata'] or {}) <= SAFE_KEYS, name
    assert fx.CODE.decode() not in json.dumps(results)


def test_failure_class_mutations_require_diagnosis(tmp_path, generated):
    cases = []
    variants = {
        'cancel_without_flag': ('cancelled', lambda r: r.update(operator_cancelled=False)),
        'cancel_not_deleted': ('cancelled', lambda r: r.update(input_file_deleted=False)),
        'cancel_with_exit_code': ('cancelled', lambda r: r.update(native_exit_code=1)),
        'timeout_submitted': ('timed_out', lambda r: r.update(one_line_submitted=True, input_file_deleted=True)),
        'timeout_value_error': ('timed_out', lambda r: r['failure'].update(error_type='ValueError')),
        'timeout_token_checked': ('timed_out', lambda r: r['token_storage_observed'].update(file_check='ok', file_token_present=False)),
        'failed_wrong_phase': ('fail_before_input', lambda r: r['login_failure'].update(phase='native_result')),
        'failed_zero_exit': ('fail_before_input', lambda r: r.update(native_exit_code=0)),
        'custody_with_login': ('native_custody_failure', lambda r: r.update(login_commands_executed=1)),
        'custody_wrong_phase': ('native_custody_failure', lambda r: r['failure'].update(phase='native_launch')),
        'custody_with_markers': ('native_custody_failure', lambda r: r.update(native_markers={'before_input': {}, 'after_input': {}})),
        'custody_with_closed_marker': ('native_custody_failure', lambda r: r.update(input_closed_marker_written=True)),
        'timeout_with_bound_flag': ('timed_out', lambda r: r.update(native_output_bound_reached_before_input=True)),
        'cancel_with_bound_flag': ('cancelled', lambda r: r.update(native_output_bound_reached_before_input=True)),
        'bound_without_flag': ('output_bound', lambda r: r.update(native_output_bound_reached_before_input=False)),
        'bound_submitted': ('output_bound', lambda r: r.update(one_line_submitted=True, input_file_deleted=True)),
        'bound_cancelled': ('output_bound', lambda r: r.update(operator_cancelled=True)),
        'bound_with_exit_code': ('output_bound', lambda r: r.update(native_exit_code=0)),
        'bound_cleanup_unverified': ('output_bound', lambda r: r.update(cleanup_verified=False)),
        'bound_wrong_phase': ('output_bound', lambda r: r['failure'].update(phase='native_result')),
        'bound_no_closed_marker': ('output_bound', lambda r: r.update(input_closed_marker_written=False)),
        'bound_token_checked': ('output_bound', lambda r: r['token_storage_observed'].update(file_check='ok', file_token_present=False)),
        'value_error_is_not_the_bound': ('output_bound', lambda r: r['failure'].update(error_type='ValueError')),
    }
    for name, (base, mutate) in variants.items():
        value = copy.deepcopy(generated[base]['receipt'])
        mutate(value)
        path = tmp_path / (name + '.json')
        path.write_text(json.dumps(value), encoding='utf-8')
        cases.append(case(name, path, mode=fx.SCENARIOS[base]['mode'], last=generated[base]['code']))
    results = classify(tmp_path, cases)
    for name, result in results.items():
        assert not result['ok'], name


def test_safe_metadata_projection_never_throws_and_stays_allowlisted():
    body = prelude() + r'''
$inputs=@($null,'text',42,@(1,2),[pscustomobject]@{status='LOGIN_COMMAND_FAILED';failure=[pscustomobject]@{phase='native_wait';error_type='Bad Type!';winerror='x'};login_mode='Print';
    native_markers=[pscustomobject]@{before_input=[pscustomobject]@{rate_limit_present=$true;account_email='x@y'};after_input='junk'};native_exit_code=-1;one_line_submitted='yes';
    login_commands_executed=1;email='fixture-owner@example.invalid'})
$out=@();foreach($value in $inputs){$out+=,(Get-AgyHistorySafeReceiptMetadata $value)}
$out|ConvertTo-Json -Depth 6 -Compress
'''
    values = json.loads(fx.ps_run(body))
    assert values[:4] == [{}, {}, {}, {}]
    assert values[4] == {'status': 'LOGIN_COMMAND_FAILED', 'login_commands_executed': 1, 'failure': {'phase': 'native_wait'},
                         'markers_seen': ['rate_limit_present']}


def test_private_acl_predicate_on_in_memory_acls():
    body = prelude() + r'''
function New-TestAcl([switch]$Directory,[switch]$Extra,[switch]$Unprotected,[string]$Owner='S-1-5-32-544'){
    if($Directory){$acl=[Security.AccessControl.DirectorySecurity]::new();$inherit=[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'}else{$acl=[Security.AccessControl.FileSecurity]::new();$inherit=[Security.AccessControl.InheritanceFlags]::None}
    $acl.SetAccessRuleProtection((-not $Unprotected),$false);$acl.SetOwner([Security.Principal.SecurityIdentifier]::new($Owner))
    $sids=@('S-1-5-18','S-1-5-32-544');if($Extra){$sids+='S-1-5-32-545'}
    foreach($sid in $sids){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl',$inherit,'None','Allow'))}
    $acl
}
function Test-Acl([scriptblock]$Body){try{& $Body;$true}catch{$false}}
[ordered]@{
  directory=(Test-Acl {Assert-AgyHistoryPrivateAcl (New-TestAcl -Directory) -Directory})
  directory_extra=(Test-Acl {Assert-AgyHistoryPrivateAcl (New-TestAcl -Directory -Extra) -Directory})
  directory_unprotected=(Test-Acl {Assert-AgyHistoryPrivateAcl (New-TestAcl -Directory -Unprotected) -Directory})
  directory_user_owner=(Test-Acl {Assert-AgyHistoryPrivateAcl (New-TestAcl -Directory -Owner 'S-1-5-32-545') -Directory})
  file=(Test-Acl {Assert-AgyHistoryPrivateAcl (New-TestAcl)})
  file_as_directory=(Test-Acl {Assert-AgyHistoryPrivateAcl (New-TestAcl) -Directory})
  file_unprotected_inherited=(Test-Acl {Assert-AgyHistoryPrivateAcl (New-TestAcl -Unprotected) -AllowInherited})
  file_unprotected=(Test-Acl {Assert-AgyHistoryPrivateAcl (New-TestAcl -Unprotected)})
}|ConvertTo-Json -Compress
'''
    assert json.loads(fx.ps_run(body)) == {'directory': True, 'directory_extra': False, 'directory_unprotected': False,
                                           'directory_user_owner': False, 'file': True, 'file_as_directory': False,
                                           'file_unprotected_inherited': True, 'file_unprotected': False}


def test_task_definition_rules():
    body = prelude() + r'''
$root='C:\Program Files\CoChem\InteractiveAgy427-r4-slot3-''' + fx.NONCE + r''''
$name='CoChem-4.2.7-InteractiveAgy-r4-slot3-''' + fx.NONCE + r''''
$print=Get-AgyHistoryTaskArguments $root 'slot3' ''' + q(fx.NONCE) + r''' 'print'
$tui=Get-AgyHistoryTaskArguments $root 'slot3' ''' + q(fx.NONCE) + r''' 'tui'
$cases=[ordered]@{
  print=@{Name=$name;Root=$root;Arguments=$print}
  tui=@{Name=$name;Root=$root;Arguments=$tui}
  none_mode=@{Name=$name;Root=$root;Arguments=($print -replace 'print$','none')}
  running=@{Name=$name;Root=$root;Arguments=$print;State=4}
  instance=@{Name=$name;Root=$root;Arguments=$print;Instances=1}
  other_python=@{Name=$name;Root=$root;Arguments=$print;Path='C:\Python314\python.exe'}
  other_limit=@{Name=$name;Root=$root;Arguments=$print;Limit='PT0S'}
  restart=@{Name=$name;Root=$root;Arguments=$print;Restart=1}
  trigger=@{Name=$name;Root=$root;Arguments=$print;Triggers=1}
  user=@{Name=$name;Root=$root;Arguments=$print;User='AETHERDESK\ansac'}
  working_directory=@{Name=$name;Root=$root;Arguments=$print;WorkingDirectory='C:\Windows'}
  other_name=@{Name=($name+'0');Root=$root;Arguments=$print}
  result_string=@{Name=$name;Root=$root;Arguments=$print;LastTaskResult='0'}
}
$out=[ordered]@{}
foreach($key in $cases.Keys){$p=$cases[$key];$task=New-FixtureTask @p;try{$out[$key]=Assert-AgyHistoryTask $task $root 'slot3' ''' + q(fx.NONCE) + r'''}catch{$out[$key]='REFUSED'}}
$out|ConvertTo-Json -Compress
'''
    result = json.loads(fx.ps_run(body))
    assert result.pop('print') == 'print' and result.pop('tui') == 'tui'
    assert set(result.values()) == {'REFUSED'}
    assert f'-I -B "C:\\Program Files\\CoChem\\InteractiveAgy427-r4-slot3-{fx.NONCE}\\worker_agy_login_bridge_r4_v1.py" --slot slot3 --nonce {fx.NONCE} --login-mode print' \
        in fx.ps_run(prelude() + "Get-AgyHistoryTaskArguments 'C:\\Program Files\\CoChem\\InteractiveAgy427-r4-slot3-" + fx.NONCE + "' 'slot3' '" + fx.NONCE + "' 'print'")


def inventory(tmp_path, parent, tasks, slot='slot3'):
    """Run Assert-ReviewedAgyHistory over a fixture parent with fixture tasks: [{name, root, mode, last, state}]."""
    task_file = tmp_path / 'tasks.json'
    task_file.write_text(json.dumps(tasks), encoding='utf-8')
    body = prelude() + "function Get-AgyHistoryParent {" + q(parent) + "}\n" + r'''
$script:aclChecks=0
function Assert-AgyHistoryPrivateAcl {param($Acl,[switch]$Directory,[switch]$AllowInherited) $script:aclChecks++}
function Get-AgyHistoryExpectedSid {param([string]$Slot) $script:sid}
$folder=New-FixtureFolder
$taskList=Get-Content -LiteralPath ''' + q(task_file) + r''' -Raw|ConvertFrom-Json
foreach($t in $taskList){
    $arguments=Get-AgyHistoryTaskArguments $t.root $t.slot $t.nonce $t.mode
    $folder.Tasks[$t.name]=New-FixtureTask -Name $t.name -Root $t.root -Arguments $arguments -LastTaskResult $t.last -State $t.state
}
$hosts=[Collections.Generic.List[string]]::new()
function Write-Host {param($Object) $hosts.Add([string]$Object)}
try{$summaries=@(Assert-ReviewedAgyHistory -Slot ''' + q(slot) + r''' -Folder $folder -Runtime $script:runtime);$result=[ordered]@{ok=$true;summaries=$summaries}}
catch{$result=[ordered]@{ok=$false;message=$_.Exception.Message}}
$result.hosts=@($hosts);$result.acl_checks=$script:aclChecks
$result|ConvertTo-Json -Depth 8 -Compress
'''
    return json.loads(fx.ps_run(body))


def task_for(root, mode='print', last=0, state=3, nonce=None, slot='slot3'):
    nonce = nonce or fx.NONCE
    return {'name': f'CoChem-4.2.7-InteractiveAgy-r4-{slot}-{nonce}', 'root': str(root), 'mode': mode, 'last': last, 'state': state,
            'nonce': nonce, 'slot': slot}


def copy_root(generated, name, parent):
    target = Path(parent) / generated[name]['root'].name
    shutil.copytree(generated[name]['root'], target)
    return target


def test_inventory_empty_parent_returns_nothing(tmp_path):
    parent = tmp_path / 'CoChem'; parent.mkdir()
    result = inventory(tmp_path, parent, [])
    assert result['ok'] and result['summaries'] == []


def test_inventory_refuses_an_older_non_r4_session(tmp_path):
    parent = tmp_path / 'CoChem'; (parent / ('InteractiveAgy427-slot3-' + 'a' * 32)).mkdir(parents=True)
    result = inventory(tmp_path, parent, [])
    assert not result['ok'] and 'older non-r4 agy session' in result['message']


@pytest.mark.parametrize('name', ['InteractiveAgy427-r4-slot3-' + 'A' * 32, 'InteractiveAgy427-r4-slot3-' + '0' * 32,
                                  'InteractiveAgy427-r4-slot3-' + 'a' * 31, 'InteractiveAgy427-r4-slot3-' + 'a' * 32 + '-copy'])
def test_inventory_refuses_malformed_session_roots(tmp_path, name):
    parent = tmp_path / 'CoChem'; (parent / name).mkdir(parents=True)
    result = inventory(tmp_path, parent, [])
    assert not result['ok'] and 'root name or selected slot differs' in result['message']


@pytest.mark.parametrize('task_name', ['CoChem-4.2.7-InteractiveAgy-r4-slot3-' + 'c' * 32, 'CoChem-4.2.7-InteractiveAgy-slot3-' + 'c' * 32])
def test_inventory_refuses_a_task_without_a_reviewed_root(tmp_path, task_name):
    parent = tmp_path / 'CoChem'; parent.mkdir()
    task = task_for(parent / 'missing'); task['name'] = task_name
    result = inventory(tmp_path, parent, [task])
    assert not result['ok'] and 'no matching reviewed session root' in result['message']


def test_inventory_refuses_a_root_without_its_task(tmp_path, generated):
    parent = tmp_path / 'CoChem'; parent.mkdir()
    copy_root(generated, 'print_exit_zero', parent)
    result = inventory(tmp_path, parent, [])
    assert not result['ok'] and 'task is absent' in result['message']


def test_inventory_reviews_accepted_and_cancelled_sessions_and_reports_session_records(tmp_path, generated):
    for name, last, classification, accepted in (('print_exit_zero', 0, 'TERMINAL_NATIVE_LOGIN_CLEANUP_VERIFIED', True),
                                                 ('cancelled', 2, 'TERMINAL_CANCELLED_NATIVE_LOGIN_CLEANUP_VERIFIED', False),
                                                 ('tui_terminated', 0, 'TERMINAL_NATIVE_LOGIN_CLEANUP_VERIFIED', True),
                                                 ('output_bound', 2, 'TERMINAL_OUTPUT_BOUND_NATIVE_LOGIN_CLEANUP_VERIFIED', False)):
        parent = tmp_path / name / 'CoChem'; parent.mkdir(parents=True)
        root = copy_root(generated, name, parent)
        (root / 'session-result.json').write_text('{"schema":"cochem-interactive-agy-login-result/1"}', encoding='utf-8')
        (parent / ('InteractiveAgy427-r4-slot4-' + 'd' * 32)).mkdir()  # another slot is ignored
        other = task_for(parent / ('InteractiveAgy427-r4-slot4-' + 'd' * 32), nonce='d' * 32, slot='slot4')
        result = inventory(tmp_path / name, parent, [task_for(root, mode=fx.SCENARIOS[name]['mode'], last=last), other])
        assert result['ok'], (name, result)
        [summary] = result['summaries']
        assert summary['schema'] == 'cochem-reviewed-agy-session-history/1' and summary['classification'] == classification
        assert summary['accepted_terminal_status'] is accepted and summary['login_mode'] == fx.SCENARIOS[name]['mode']
        assert summary['receipt_sha256'] == hashlib.sha256((root / 'receipt.json').read_bytes()).hexdigest()
        assert summary['session_result_present'] is True and summary['session_held_present'] is False
        assert summary['session_result_sha256'] == hashlib.sha256((root / 'session-result.json').read_bytes()).hexdigest()
        assert summary['authentication_authorized_by_history'] is False and summary['current_logged_out_status_required'] is True
        assert result['acl_checks'] == 5  # root directory, bridge copy, support copy, receipt, session-result.json


def test_inventory_hold_prints_only_safe_metadata(tmp_path, generated):
    parent = tmp_path / 'CoChem'; parent.mkdir()
    root = copy_root(generated, 'cleanup_unverified', parent)
    result = inventory(tmp_path, parent, [task_for(root, last=2)])
    assert not result['ok'] and 'not sufficient for a fresh login' in result['message']
    [line] = [line for line in result['hosts'] if line.startswith('COCHEM_AGY_HISTORY_HOLD ')]
    metadata = json.loads(line[len('COCHEM_AGY_HISTORY_HOLD '):])
    assert metadata['status'] == 'CLEANUP_UNVERIFIED' and set(metadata) <= SAFE_KEYS
    assert fx.CODE.decode() not in json.dumps(result) and fx.EMAIL not in json.dumps(result)


@pytest.mark.parametrize('variant', ['running_task', 'mode_mismatch', 'bridge_copy_changed', 'receipt_missing'])
def test_inventory_refusals(tmp_path, generated, variant):
    parent = tmp_path / 'CoChem'; parent.mkdir()
    root = copy_root(generated, 'print_exit_zero', parent)
    task = task_for(root)
    if variant == 'running_task':
        task['state'] = 4
    elif variant == 'mode_mismatch':
        task['mode'] = 'tui'
    elif variant == 'bridge_copy_changed':
        (root / 'worker_agy_login_bridge_r4_v1.py').write_bytes(fx.BRIDGE_PATH.read_bytes() + b'\n')
    else:
        (root / 'receipt.json').unlink()
    result = inventory(tmp_path, parent, [task])
    assert not result['ok'], variant


def test_history_source_is_functions_only_and_pins_current_values():
    body = ("$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile(" + q(HISTORY) + ",[ref]$t,[ref]$e);"
            "[ordered]@{errors=$e.Count;param=($null -ne $a.ParamBlock);begin=($null -ne $a.BeginBlock);"
            "statements=@($a.EndBlock.Statements|ForEach-Object{$_.GetType().Name})}|ConvertTo-Json -Compress")
    shape = json.loads(fx.ps_run(body))
    assert shape['errors'] == 0 and not shape['param'] and not shape['begin']
    assert set(shape['statements']) == {'FunctionDefinitionAst'}
    text = HISTORY.read_text()
    for pin in ('629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502', '1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189',
                '135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c', '38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e',
                'de7fac91e32cef2f854bd53487037352bbc0915f95aaf987ee8a4a543317915f', '8430fdf1109c63c4a89479f03da8a465dfebf5566c7791c64f868202170672c4',
                fx.bridge.SUPPORT_SHA256, fx.bridge.AGY_SHA256, hashlib.sha256(fx.BRIDGE_PATH.read_bytes()).hexdigest()):
        assert f"'{pin}'" in text
    assert '"InteractiveAgy427-$Slot-*"' in text and 'operator.log' not in text.split('#>', 1)[1]
