"""Read-only receipt and owner-sequence fixtures, with no host operations."""
import json
from pathlib import Path

import pytest

from pipeline_tests.test_r6_custody_continuation import ps


EVIDENCE = Path(__file__).parents[1] / 'docs/evidence/r6-native-hold-diagnostic-20261013.json'


@pytest.mark.parametrize('fault', ['', 'pin', 'candidate', 'category', 'completed', 'restore',
                                  'conflicting_hold', 'health', 'start_status', 'old_history'])
def test_reviewed_native_hold_checks_saved_pins_before_any_stop(monkeypatch, fault):
    diagnostic = json.loads(EVIDENCE.read_text(encoding='utf-8-sig'))
    records = {}
    for record in diagnostic['records'] + json.loads(EVIDENCE.with_name('r6-native-hold-v2-diagnostic-20261013.json').read_text(encoding='utf-8-sig'))['records']:
        if not record['present']:
            continue
        value = dict(record['projection'])
        if 'result_status' in value:
            value['result'] = {'status': value.pop('result_status')}
        records[record['relative']] = dict(value=value, hash=record['sha256'])
    literal = json.dumps(records).replace("'", "''")
    result = ps(monkeypatch, 'verify_r6_auth_recovery.ps1', "$script:records='" + literal + "'|ConvertFrom-Json\n" + r'''
$script:base='C:\fixture';$script:reads=0
function Read-R6RecoveryJson {param($Path,$Hash)
 $key=$Path.Substring($script:base.Length+1);$record=$script:records.PSObject.Properties[$key].Value
 if('FAULT' -eq 'pin' -and $key -like '*native-c9ff*'){$Hash='0'*64}
 if($Hash -cne $record.hash){throw 'fixture pin mismatch'}
 $script:reads++;$v=$record.value
 if('FAULT' -eq 'candidate' -and $key -like '*agent-6ca*'){$v.candidate_sha256='changed'}
 if('FAULT' -eq 'category' -and $key -like '*native-c9ff*\held.json'){$v.category='auth'}
 if('FAULT' -eq 'completed' -and $key -like '*native-c9ff*\native-held.json'){$v.completed=1}
 if('FAULT' -eq 'restore' -and $key -like '*v10\start-intent.json'){$v.retry=$true}
 if('FAULT' -eq 'health' -and $key -like '*v10\start-receipt.json'){$v.health_samples=0}
 if('FAULT' -eq 'start_status' -and $key -like '*v10\start-receipt.json'){$v.status='HELD'}
 if('FAULT' -eq 'old_history' -and $key -like '*native-3443*\held.json'){$v.category='code'}
 $v
}
function Test-Path {param($LiteralPath) ('FAULT' -eq 'conflicting_hold' -and $LiteralPath -like '*v10\start-held.json')}
$errorText=$null;$allowed=@();try{$allowed=@(Assert-R6NativeContinuationEvidence)}catch{$errorText=$_.Exception.Message}
@{error=$errorText;allowed=$allowed;reads=$script:reads}|ConvertTo-Json -Compress
'''.replace('FAULT', fault))
    assert bool(result['error']) is bool(fault), result
    if not fault:
        assert result['reads'] == 15
        assert len(result['allowed']) == 8


@pytest.mark.parametrize('fault', ['', 'source', 'stop', 'held'])
def test_owner_stop_handles_only_bound_verified_r4_v10_once(monkeypatch, fault):
    result = ps(monkeypatch, 'run_r6_launch.ps1', r'''
$script:R5=@{base_source=@{kind='r4-restore';source_attempt=$(if('FAULT' -eq 'source'){'v8'}else{'v10'})};s2_done=$false;s2_attempted=$false;s2_stop_attempt=$null}
$script:NsStopR5='fresh-stop-';$script:calls=0;$script:record=$null
function Get-R5FreeAttempt {param($Prefix) if($Prefix -cne 'fresh-stop-'){throw 'wrong namespace'};'v21'}
function Invoke-R5StopR5 {param($StopAttempt,$RetargetTarget,$RetargetAttempt,[switch]$RecoverInterruptedStart)
 $script:calls++
 if($StopAttempt -cne 'v21' -or $RetargetTarget -cne 'r4' -or $RetargetAttempt -cne 'v10' -or $RecoverInterruptedStart){throw 'wrong binding'}
 @{ok=('FAULT' -ne 'stop');held=('FAULT' -eq 'held');status='WARDEN_ALREADY_STOPPED_CLEAN_NOOP'}
}
function Write-R5Receipt {param($Name,$Status) $script:record=$Name}
$errorText=$null;try{Invoke-R6NativeContinuationStop}catch{$errorText=$_.Exception.Message}
@{error=$errorText;calls=$script:calls;state=$script:R5;record=$script:record}|ConvertTo-Json -Depth 6 -Compress
'''.replace('FAULT', fault))
    assert bool(result['error']) is bool(fault), result
    assert result['calls'] == (0 if fault == 'source' else 1)
    assert result['state']['s2_done'] is (not fault)
    if not fault:
        assert result['state']['base_source']['stop_attempt'] == 'v21'
        assert result['record'] == 'S02'


@pytest.mark.parametrize('field', ['', 'executable_sha256', 'agent_sha256', 'protocol_sha256',
                                  'worker_sha256', 'agent_identity_required', 'actual_tool_steps_rejected',
                                  'installed_files_modified', 'advertised_registry_scope', 'codex_workspace_selection'])
def test_startup_rejects_missing_or_changed_native_amendment(monkeypatch, field):
    from scripts import r6_custody_amendment as amendment
    value = dict(schema='cochem-r6-agy-registry-amendment/1', protocol_sha256=amendment.REGISTRY_PROTOCOL,
                 worker_sha256=amendment.REGISTRY_WORKER, executable_sha256=amendment.BINARY_SHA256,
                 agent_sha256=amendment.AGENT_SHA256, agent_identity_required=True,
                 actual_tool_steps_rejected=True, installed_files_modified=False,
                 advertised_registry_scope='cli_builtin_runners', codex_workspace_selection='validated_process_cwd')
    if field:
        value.pop(field)
    literal = json.dumps(value).replace("'", "''")
    result = ps(monkeypatch, 'activate_r6_runtime.ps1', "$v='" + literal + "'|ConvertFrom-Json\n" + r'''
function Test-ExactBool {param($Value,$Expected) ($Value -is [bool]) -and ($Value -eq $Expected)}
$held=$false;try{Assert-R6RegistryAmendment $v}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
''')
    assert result['held'] is bool(field)


def test_recovery_failure_projection_does_not_disclose_private_exception_text(monkeypatch):
    result = ps(monkeypatch, 'run_r6_launch.ps1', r'''
function Invoke-R5Fixture {throw [InvalidOperationException]::new('secret credential and private path')}
try{Invoke-R5Fixture}catch{Get-R6RecoveryFailure $_|ConvertTo-Json -Depth 4 -Compress}
''')
    assert result['error_type'] == 'InvalidOperationException'
    assert result['raw_error_published'] is False
    assert result['frames'][0]['function'] == 'Invoke-R5Fixture'
    assert 'secret' not in json.dumps(result) and 'private' not in json.dumps(result)
