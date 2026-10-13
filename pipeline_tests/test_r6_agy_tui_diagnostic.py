"""Inert Windows diagnostic fixtures: no tasks, native providers or protected writes."""
import json
from pathlib import Path

import pytest

from pipeline_tests import test_install_r6_runtime as ps_fixture


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(ps_fixture, 'SCRIPT', Path(__file__).parents[1] / 'scripts/inspect_r6_agy_tui_failure.ps1')
    return ps_fixture.run_ps


def test_receipt_without_outer_held_record_does_not_claim_wrapper_cleanup(run_ps):
    result = run_ps(r'''
$receipt=@{schema='cochem-interactive-agy-login/1';slot='slot1';nonce=('a'*32);
 status='LOGIN_FAILED_OR_CANCELLED';login_mode='tui';cleanup_verified=$true;
 one_line_submitted=$false;native_output_bytes_before_input=0;native_output_published_bytes_before_input=0;
 failure=@{phase='native_wait';error_type='TimeoutError';message='DO-NOT-PUBLISH'}}
Get-R6AgyTuiSessionProjection $receipt $null|ConvertTo-Json -Depth 8 -Compress
''')
    assert result['bridge_receipt_present'] is True
    assert result['wrapper_held_record_present'] is False
    assert result['outer_wrapper_cleanup_verified'] is False
    assert result['receipt']['native_output_bytes_before_input'] == 0
    assert 'DO-NOT-PUBLISH' not in json.dumps(result)


def test_missing_optional_record_is_evidence_absence_not_a_terminal_receipt(run_ps, tmp_path):
    path = str(tmp_path / 'absent.json').replace("'", "''")
    result = run_ps(f"Read-R6AgyOptionalDiagnosticRecord '{path}' 'fixture/1'|ConvertTo-Json -Compress")
    assert result['status'] == 'ABSENT'
    assert result['record'] is None
    assert result['sha256'] is None


def test_empty_receipt_is_preserved_and_reported_unsealed(run_ps, tmp_path):
    path = tmp_path / 'receipt.json'
    path.write_bytes(b'')
    result = run_ps(f"Read-R6AgyOptionalDiagnosticRecord '{str(path).replace(chr(39), chr(39)*2)}' 'fixture/1'|ConvertTo-Json -Compress")
    assert result['status'] == 'EMPTY_UNSEALED'
    assert result['record'] is None
    assert path.read_bytes() == b''


def test_complete_optional_record_keeps_same_handle_digest(run_ps, tmp_path):
    path = tmp_path / 'receipt.json'
    path.write_text('{"schema":"fixture/1"}')
    result = run_ps(f"Read-R6AgyOptionalDiagnosticRecord '{str(path).replace(chr(39), chr(39)*2)}' 'fixture/1'|ConvertTo-Json -Compress")
    import hashlib
    assert result['status'] == 'READ_VERIFIED'
    assert result['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_wrong_session_identity_is_refused_without_echoing_record(run_ps):
    result = run_ps(r'''
$held=$false;$message=''
try{Assert-R6AgyTuiDiagnosticIdentity @{slot='slot2';nonce='DO-NOT-PUBLISH'}}catch{$held=$true;$message=$_.Exception.Message}
@{held=$held;message=$message}|ConvertTo-Json -Compress
''')
    assert result['held'] is True
    assert 'DO-NOT-PUBLISH' not in result['message']


def test_task_projection_omits_action_arguments_and_secrets(run_ps):
    result = run_ps(r'''
$task=[pscustomobject]@{State=3;Enabled=$true;LastTaskResult=2;Definition=[pscustomobject]@{secret='DO-NOT-PUBLISH';
 Actions=@(@{Arguments='DO-NOT-PUBLISH'})}}
$task|Add-Member -MemberType ScriptMethod -Name GetInstances -Value {param($flags) @()}
Get-R6AgyTuiTaskProjection $task|ConvertTo-Json -Compress
''')
    assert result['instances'] == 0
    assert result['state'] == 3
    assert result['last_task_result'] == 2
    assert 'DO-NOT-PUBLISH' not in json.dumps(result)


def test_diagnostic_entry_has_no_mutation_or_raw_login_output_reads():
    path = Path(__file__).parents[1] / 'scripts/inspect_r6_agy_tui_failure.ps1'
    text = path.read_text()
    assert 'InteractiveAgy427-r4-slot1-43804e7a8d44457aa9810305923c219f' in text
    assert "Join-Path $root 'operator.log'" not in text
    assert "Join-Path $root 'input.once'" not in text
    assert 'RegisterTask' not in text
    assert '.Run(' not in text
    assert 'Stop-Process' not in text
