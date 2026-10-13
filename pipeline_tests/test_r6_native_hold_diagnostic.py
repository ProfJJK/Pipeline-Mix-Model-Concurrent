"""Inert Windows PowerShell fixtures: no provider, task or protected-state execution."""
import hashlib
import json
from pathlib import Path

import pytest

from pipeline_tests import test_install_r6_runtime as ps_fixture

SCRIPT = Path(__file__).parents[1] / 'scripts/inspect_r6_native_hold.ps1'
SECRET = 'DO-NOT-PUBLISH-https://private.invalid/code'


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(ps_fixture, 'SCRIPT', SCRIPT)
    return ps_fixture.run_ps


def ps(value):
    return "'" + value.replace("'", "''") + "'"


def events():
    return [
        {'event': 'init', 'conversation_id': SECRET,
         'init': {'model': 'gemini-3.8-flash-low', 'tools': []}},
        {'event': 'result', 'result': {'conversation_id': SECRET, 'status': 'SUCCESS',
                                     'num_turns': 1, 'response': SECRET}},
    ]


def protocol(run_ps, data=None, stderr=''):
    text = '\n'.join(json.dumps(row) for row in (events() if data is None else data))
    result = run_ps(f"Get-NativeHoldProtocol {ps(text)} {ps(stderr)} 'gemini-3.8-flash-low' | ConvertTo-Json -Depth 10 -Compress")
    assert SECRET not in json.dumps(result)
    return result


def test_valid_empty_registry_and_missing_optional_terminal_model(run_ps):
    value = protocol(run_ps)
    assert value['json_valid'] and value['event_order_matches']
    assert value['init_model'] == 'EXPECTED'
    assert value['terminal_model'] == 'ABSENT'
    assert value['init_tools_present'] and value['init_tools_empty_array']
    assert value['init_tools_count'] == 0
    assert value['model_mismatches'] == value['tool_steps'] == 0
    assert value['session_matches'] and value['one_turn'] and value['terminal_success']


@pytest.mark.parametrize('change', ['missing', 'null', 'tools', 'step'])
def test_tool_registry_violations_are_distinguishable_without_tool_names(run_ps, change):
    data = events()
    if change == 'missing':
        del data[0]['init']['tools']
    elif change == 'null':
        data[0]['init']['tools'] = None
    elif change == 'tools':
        data[0]['init']['tools'] = [SECRET]
    else:
        data.insert(1, {'event': 'step_update', 'step_update': {'tool_name': SECRET}})
    value = protocol(run_ps, data)
    assert value['json_valid']
    if change == 'step':
        assert value['tool_steps'] == 1
    else:
        assert not value['init_tools_empty_array']
        assert value['init_tools_present'] == (change != 'missing')
    if change == 'tools':
        assert value['init_tools_count'] == 1


@pytest.mark.parametrize('reported,expected', [
    ('gemini-3.8-flash', 'CANONICAL_FLASH_WITHOUT_EFFORT'),
    ('gemini-3.8-flash-high', 'OTHER_VALUE'), (SECRET, 'OTHER_VALUE'),
])
def test_model_identity_disagreement_is_projected_without_arbitrary_names(run_ps, reported, expected):
    data = events()
    data[0]['init']['model'] = reported
    data[-1]['result']['model'] = reported
    value = protocol(run_ps, data)
    assert value['init_model'] == value['terminal_model'] == expected
    assert value['model_mismatches'] == 2


def test_recursive_reroute_model_collection_and_styled_stderr(run_ps):
    data = events()
    data[1]['result']['nested'] = {'fallback': SECRET, 'models': {SECRET: {}}, 'selected_model': SECRET}
    value = protocol(run_ps, data, 'Model\x1b[31m resolved via\x1b[0m ' + SECRET)
    assert value['reroute_members'] == 1
    assert value['model_mismatches'] == 1
    assert value['model_collection_mismatches'] == 1
    assert value['stderr_markers']['Model resolved via']


@pytest.mark.parametrize('text', ['', '{}', '{}\nnot-json', '[[]]\n{}'])
def test_invalid_or_unrecognized_stream_never_attests_protocol(run_ps, text):
    value = run_ps(f"Get-NativeHoldProtocol {ps(text)} '' 'gemini-3.8-flash-low' | ConvertTo-Json -Depth 10 -Compress")
    assert not (value['json_valid'] and value['event_order_matches'])


def test_record_projection_keeps_typed_failure_and_restore_flags_only(run_ps):
    value = run_ps(f"""
$record=@{{schema='cochem-native-failure-metadata/1';category='compatibility';envelope_kind='agy_identity';
 exit_code=0;stdout_sha256=('a'*64);stage='HEALTH_WAIT';run_requested=$true;reason='post-start readiness not met {SECRET}';
 message='{SECRET}';status='{SECRET}';target='{SECRET}';arbitrary='{SECRET}'}}
Select-NativeHoldRecord $record|ConvertTo-Json -Depth 8 -Compress
""")
    assert SECRET not in json.dumps(value)
    assert value['category'] == 'compatibility' and value['envelope_kind'] == 'agy_identity'
    assert value['stage'] == 'HEALTH_WAIT' and value['run_requested']
    assert value['reason_markers']['post-start readiness not met']
    assert value['status'] == value['target'] == 'UNRECOGNIZED'
    assert value['stdout_sha256'] == 'a' * 64


def test_reader_hash_and_missing_and_size_bound(run_ps, tmp_path):
    path = tmp_path / 'record.json'
    path.write_text('{"schema":"fixture/1"}', encoding='utf-8')
    before = path.stat().st_mtime_ns
    value = run_ps(f"""
$read=Read-NativeHoldFile {ps(str(path))}
$missing=Read-NativeHoldFile {ps(str(tmp_path / 'absent.json'))}
$bounded=$false;try{{$null=Read-NativeHoldFile {ps(str(path))} 2}}catch{{$bounded=$true}}
@{{sha=$read.sha256;record=$read.value;missing=$missing;bounded=$bounded}}|ConvertTo-Json -Depth 8 -Compress
""")
    assert value['sha'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert value['record'] == {'schema': 'fixture/1'}
    assert value['missing'] == {'present': False} and value['bounded']
    assert path.stat().st_mtime_ns == before


def fixture_report(run_ps, *, tamper=False, read_error=False):
    # Everything including COM is replaced. This executes the complete report
    # builder against synthetic receipts, including its bound attempt paths.
    stdout = '\n'.join(json.dumps(row) for row in events())
    return run_ps(f"""
$script:reads=[Collections.Generic.List[string]]::new()
function Read-NativeHoldFile {{param([string]$Path,[int]$Maximum=4194304,[switch]$Text)
 $script:reads.Add($Path)
 if($Path.EndsWith('start-held.json')){{throw 'fixture denied'}}
 if($Path.EndsWith('native-held.json')){{
  return @{{present=$true;sha256=('a'*64);value=@{{schema='cochem-r6-native-acceptance/1';phase='target-00'}}}}}}
 if($Path.EndsWith('target-00-reservation.json')){{
  return @{{present=$true;sha256=('b'*64);value=@{{schema='cochem-r6-disposable-native-reservation/1';
   node=@{{attempt_id='{('../bad' if tamper else 'c' * 32)}';worker_slot='slot1';route=@{{provider='gemini';model='gemini-3.8-flash';reasoning_effort='low'}}}}}}}}}}
 if($Path.EndsWith('failure.json')){{
  return @{{present=$true;sha256=('d'*64);value=@{{schema='cochem-native-failure-metadata/1';category='compatibility';
    envelope_kind='agy_identity';stdout_sha256=('e'*64);stderr_sha256=('f'*64)}}}}}}
 if($Path.EndsWith('stdout.log')){{
  {"throw 'fixture denied'" if read_error else "return @{present=$true;sha256=('e'*64);value=" + ps(stdout) + "}"}}}
 if($Path.EndsWith('stderr.log')){{return @{{present=$true;sha256=('f'*64);value=''}}}}
 return @{{present=$false}}
}}
function Get-NativeHoldTaskFolder {{'fixture-folder'}}
function Get-NativeHoldTask {{param($Folder,$Name)
 if($Folder -cne 'fixture-folder'){{throw 'unexpected fixture'}}
 @{{readable=$true;state=4;enabled=$true;instances=1}}
}}
$report=Get-NativeHoldReport
@{{report=$report;reads=@($script:reads)}}|ConvertTo-Json -Depth 14 -Compress
""")


def test_complete_report_builder_is_read_only_and_excludes_raw_evidence(run_ps):
    result = fixture_report(run_ps)
    assert SECRET not in json.dumps(result)
    value = result['report']
    assert value['native_detail_status'] == 'PROJECTED_EXISTING_PROBE'
    assert value['native_failure']['projection']['envelope_kind'] == 'agy_identity'
    assert value['protocol']['init_tools_empty_array']
    assert value['stream_hashes_match_failure']
    assert value['raw_provider_output_read'] and not value['raw_provider_output_published']
    assert value['provider_commands_executed'] == value['task_mutations'] == 0
    assert value['tasks']['warden']['instances'] == 1
    assert len(value['records']) == 9
    assert any(row.get('error_type') == 'READ_FAILED' for row in value['records'])
    assert any(path.endswith('native\\attempts\\' + 'c' * 32 + '\\stdout.log') for path in result['reads'])


@pytest.mark.parametrize('tamper,read_error', [(True, False), (False, True)])
def test_bad_probe_binding_or_unreadable_output_preserves_other_diagnostics(run_ps, tamper, read_error):
    result = fixture_report(run_ps, tamper=tamper, read_error=read_error)
    assert result['report']['native_detail_status'] == 'READ_OR_BINDING_FAILED'
    assert result['report']['tasks']['warden']['readable']
    if tamper:
        assert not any(path.endswith('stdout.log') for path in result['reads'])


def test_task_projection_does_not_export_command_arguments(run_ps):
    value = run_ps(rf"""
$action=[pscustomobject]@{{Path='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\Scripts\python.exe';
 WorkingDirectory='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4';Arguments='{SECRET}'}}
$actions=[pscustomobject]@{{Count=1;action=$action}}
$actions|Add-Member ScriptMethod Item {{param($i) $this.action}}
$task=[pscustomobject]@{{State=4;Enabled=$true;LastTaskResult=267009;
 Definition=[pscustomobject]@{{Actions=$actions;Principal=[pscustomobject]@{{UserId='SYSTEM'}}}}}}
$task|Add-Member ScriptMethod GetInstances {{param($flags) @('fixture-instance')}}
$folder=[pscustomobject]@{{task=$task}}
$folder|Add-Member ScriptMethod GetTask {{param($name) $this.task}}
Get-NativeHoldTask $folder 'CoChem-4.2.7-Warden'|ConvertTo-Json -Compress
""")
    assert value['instances'] == 1 and value['r4_executable'] and value['system_principal']
    assert value['r4_working_directory'] and SECRET not in json.dumps(value)


def test_export_has_no_mutation_or_provider_entry_points():
    source = SCRIPT.read_text(encoding='utf-8')
    for forbidden in ('Start-Process', 'RegisterTask', 'Set-Acl', 'Stop-Process',
                      '.Run(', '.Enabled=', 'Invoke-Expression', 'Invoke-RestMethod',
                      'controller.token', 'Get-Credential', 'Remove-Item'):
        assert forbidden not in source
    assert "'CreateNew','Write','Read'" in source
    assert 'Invoke-NativeHoldDiagnostic $OutputDirectory' in source
