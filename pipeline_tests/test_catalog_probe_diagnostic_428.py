"""Inert tests for the read-only catalog probe diagnostic (sanitized export only)."""
import base64
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'inspect_catalog_probes_428.ps1'
PS51 = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
SECRETS = ('SECRET', 'person@example.com', 'sess-', 'secret-detail', 'ORG', 'ready')


def run(body):
    script = """
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('SOURCE',[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
foreach($node in $ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){. ([scriptblock]::Create($node.Extent.Text))}
function Start-Process {throw 'Forbidden child launch'}
function Get-ScheduledTask {throw 'Forbidden task access'}
BODY
""".replace('SOURCE', str(SCRIPT).replace("'", "''")).replace('BODY', body)
    result = subprocess.run([PS51, '-NoProfile', '-NonInteractive', '-EncodedCommand',
                             base64.b64encode(script.encode('utf-16-le')).decode()], capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    return result.stdout.decode('utf-8-sig')


@pytest.fixture
def attempts(tmp_path):
    root = tmp_path / 'attempts'
    accepted = root / ('a' * 32)
    accepted.mkdir(parents=True)
    (accepted / 'receipt.json').write_text(json.dumps(dict(provider='claude', requested_model='claude-fable-5-1',
        requested_effort='max', reported_model='claude-fable-5-1', reported_effort=None, exit_code=0, worker_slot='slot1',
        execution_kind='native_cli', session_id='sess-SECRET-1', started_at=1.0, finished_at=2.0,
        inference_policy=dict(reasoning_effort=dict(requested_profile='max', model='claude-fable-5-1',
            version='2.1.280 (Claude Code)', executable_sha256='0' * 64)))), encoding='utf-8')
    (accepted / 'stdout.log').write_text(json.dumps(dict(type='result', subtype='success', is_error=False,
        result='{"ready":true}', session_id='sess-SECRET-2', modelUsage={'claude-fable-5-1': {}})), encoding='utf-8')
    failed = root / ('b' * 32)
    failed.mkdir()
    (failed / 'failure.json').write_text(json.dumps(dict(schema='cochem-native-failure/1', category='code', exit_code=1,
        stdout_bytes=10, stdout_sha256='1' * 64, stderr_bytes=5, stderr_sha256='2' * 64, envelope_kind='claude_result',
        claude_result_subtype='success', api_status=400, started_at=3.0, finished_at=4.0)), encoding='utf-8')
    message = json.dumps({'type': 'error', 'error': {'type': 'invalid_request_error',
                                                      'message': 'secret-detail: effort is not supported for this model'}})
    (failed / 'stdout.log').write_text(json.dumps(dict(type='result', subtype='success', is_error=True,
        result='API Error: 400 ' + message, session_id='sess-SECRET-3', num_turns=1, duration_ms=900,
        modelUsage={'claude-haiku-5-5': {}})), encoding='utf-8')
    (failed / 'stderr.log').write_text('warning SECRET-STDERR network socket closed', encoding='utf-8')
    (failed / 'auth.out').write_text(json.dumps(dict(loggedIn=True, authMethod='claude.ai', apiProvider='firstParty',
        subscriptionType='max', email='person@example.com', orgId='ORGSECRET')), encoding='utf-8')
    old = root / ('c' * 32)
    old.mkdir()
    (old / 'failure.json').write_text('{}', encoding='utf-8')
    return root


def test_export_names_the_failure_without_any_raw_native_text(attempts):
    text = run(r"""
$old=Get-Item -LiteralPath (Join-Path 'ROOT' ('c'*32));$old.CreationTimeUtc=[DateTime]'2026-01-01T00:00:00Z'
$report=Invoke-OpProbeDiagnostic 'ROOT' ([DateTime]::UtcNow.AddHours(-1)) ([DateTime]::UtcNow.AddHours(1))
$report|ConvertTo-Json -Depth 12
""".replace('ROOT', str(attempts)))
    for secret in SECRETS:
        assert secret not in text, secret
    report = json.loads(text)
    assert report['raw_text_exported'] is False and report['task_mutations'] == 0
    names = [row['attempt'] for row in report['attempts']]
    assert names == ['a' * 32, 'b' * 32]
    accepted, failed = report['attempts']
    assert accepted['receipt']['requested_model'] == 'claude-fable-5-1'
    assert accepted['receipt']['effort_evidence']['version'] == '2.1.280 (Claude Code)'
    assert 'session_id' not in accepted['receipt']
    assert failed['failure']['api_status'] == 400 and failed['failure']['category'] == 'code'
    result = failed['stdout']['results'][0]
    assert result['is_error'] is True and result['model_usage_models'] == ['claude-haiku-5-5']
    assert result['result']['leading_api_status'] == 400
    assert 'invalid_request_error' in result['result']['type_tokens']
    assert {'effort', 'unsupported', 'model', 'api_error'} <= set(result['result']['keywords'])
    assert {'network'} <= set(failed['stderr']['keywords'])
    assert failed['auth'] == dict(parsed=True, loggedIn=True, authMethod='claude.ai', apiProvider='firstParty',
                                  subscriptionType='max')


def test_unparseable_streams_still_yield_only_facts(tmp_path):
    root = tmp_path / 'attempts'
    attempt = root / ('d' * 32)
    attempt.mkdir(parents=True)
    (attempt / 'stdout.log').write_text('plain SECRET text with an API Error: 500 mention', encoding='utf-8')
    (attempt / 'auth.out').write_text('not json SECRET', encoding='utf-8')
    text = run(r"""
(Invoke-OpProbeDiagnostic 'ROOT' ([DateTime]::UtcNow.AddHours(-1)) ([DateTime]::UtcNow.AddHours(1)))|ConvertTo-Json -Depth 12
""".replace('ROOT', str(root)))
    assert 'SECRET' not in text
    row = json.loads(text)['attempts'][0]
    assert row['stdout']['json_records'] == 0 and 'api_error' in row['stdout']['text']['keywords']
    assert row['auth'] == dict(parsed=False, length=len('not json SECRET'))


def test_entrypoint_is_read_only_and_requires_an_ordinary_output_folder():
    source = SCRIPT.read_text(encoding='utf-8')
    for forbidden in ('Remove-Item', 'Set-Content', 'Stop-Process', 'Start-ScheduledTask', 'Register-ScheduledTask',
                      'Set-Acl', 'Invoke-Expression', 'Start-Process', '-Apply', 'Move-Item', 'Copy-Item'):
        assert forbidden not in source, forbidden
    assert "[IO.FileMode]::CreateNew" in source and "C:\\Program Files" in source and "C:\\ProgramData" in source
