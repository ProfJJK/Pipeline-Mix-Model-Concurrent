import json
from pathlib import Path

import pytest

from pipeline_tests import test_install_r6_runtime as ps_fixture


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(ps_fixture, 'SCRIPT', Path(__file__).parents[1] / 'scripts/inspect_r6_agy_failure.ps1')
    return ps_fixture.run_ps


def test_projection_excludes_secret_and_free_text_fields(run_ps):
    result = run_ps(r'''
$receipt=@{status='LOGIN_COMMAND_FAILED';login_mode='print';cleanup_verified=$true;one_line_submitted=$true;
 native_exit_code=1;started_at_unix_ms=100;finished_at_unix_ms=80000;secret='DO-NOT-PUBLISH';
 native_markers=@{before_input=@{authentication_required_present=$true;unexpected='DO-NOT-PUBLISH'};
 after_input=@{authentication_failed_present=$true;url='DO-NOT-PUBLISH'}};
 login_failure=@{phase='native_result';error_type='NativeLoginExitNonZero';message='DO-NOT-PUBLISH'};
 token_storage_observed=@{file_check='ok';file_token_present=$false;token_contents_read=$false;token='DO-NOT-PUBLISH'}}
$held=@{phase='DECISION';receipt_present=$true;reason='DO-NOT-PUBLISH';console=@{one_line_submitted=$true;input='DO-NOT-PUBLISH'}}
Get-R6AgyFailureProjection $receipt $held|ConvertTo-Json -Depth 8 -Compress
''')
    assert 'DO-NOT-PUBLISH' not in json.dumps(result)
    assert result['receipt']['native_exit_code'] == 1
    assert result['receipt']['native_markers']['after_input']['authentication_failed_present'] is True
    assert result['held']['console'] == {'one_line_submitted': True}


@pytest.mark.parametrize('record', [
    "@{cleanup_verified='DO-NOT-PUBLISH'}",
    "@{native_exit_code='DO-NOT-PUBLISH'}",
    "@{status='DO-NOT-PUBLISH'}",
    "@{helper_sha256='DO-NOT-PUBLISH'}",
    "@{native_markers=@{after_input=@{authentication_failed_present='DO-NOT-PUBLISH'}}}",
])
def test_projection_refuses_incorrect_types_without_echoing_value(run_ps, record):
    result = run_ps(f'''
$rejected=$false;$message=''
try{{$null=Get-R6AgyFailureProjection {record} @{{}}}}catch{{$rejected=$true;$message=$_.Exception.Message}}
@{{rejected=$rejected;message=$message}}|ConvertTo-Json -Compress
''')
    assert result['rejected'] and 'DO-NOT-PUBLISH' not in result['message']


def test_reader_checks_schema_and_digest_on_same_read_handle(run_ps, tmp_path):
    path = tmp_path / 'receipt.json'
    path.write_text('{"schema":"fixture/1","status":"LOGIN_COMMAND_FAILED"}')
    result = run_ps(f'''
$value=Read-R6AgyDiagnosticRecord '{str(path).replace("'", "''")}' 'fixture/1'
@{{sha256=$value.sha256;schema=$value.record.schema}}|ConvertTo-Json -Compress
''')
    import hashlib
    assert result == {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'schema': 'fixture/1'}


def test_authentication_projection_keeps_binding_and_rejects_raw_output(run_ps):
    result = run_ps(r'''
$rows=@();foreach($i in 1..6){foreach($provider in @('codex','claude','gemini')){
 $rows+=@{worker=('slot'+$i);provider=$provider;status=$(if($provider -eq 'gemini'){'ATTENDED_LOGIN_REQUIRED'}else{'REUSE_VERIFIED_SESSION'});
 authenticated=($provider -ne 'gemini');cleanup_verified=$true;exit_code=$(if($provider -eq 'gemini'){1}else{0});raw_output='DO-NOT-PUBLISH'}}}
$envelope=@{phase='auth';status='PHASE_COMPLETED';manifest_sha256=('a'*64);candidate_sha256=('b'*64);secret='DO-NOT-PUBLISH';
 result=@{schema='cochem-r6-authentication/1';status='ATTENDED_AUTH_REVIEW_REQUIRED';checks=$rows;provider_output='DO-NOT-PUBLISH'}}
Get-R6AgyAuthProjection $envelope|ConvertTo-Json -Depth 8 -Compress
''')
    assert 'DO-NOT-PUBLISH' not in json.dumps(result)
    assert len(result['result']['checks']) == 18
    assert result['manifest_sha256'] == 'a' * 64


@pytest.mark.parametrize('schema', ['wrong/1', ''])
def test_reader_refuses_unexpected_record_schema(run_ps, tmp_path, schema):
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps({'schema': schema, 'secret': 'DO-NOT-PUBLISH'}))
    result = run_ps(f'''
$held=$false;$message=''
try{{$null=Read-R6AgyDiagnosticRecord '{str(path).replace("'", "''")}' 'fixture/1'}}catch{{$held=$true;$message=$_.Exception.Message}}
@{{held=$held;message=$message}}|ConvertTo-Json -Compress
''')
    assert result['held'] and 'DO-NOT-PUBLISH' not in result['message']
