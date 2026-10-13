"""Sanitized verification errors; only inert PowerShell and ordinary fixtures."""
import json
import subprocess
from pathlib import Path

import pytest

from pipeline_tests import test_install_r6_runtime as ps_fixture

ROOT = Path(__file__).parents[1]


def import_functions(path, names=None):
    predicate = '' if names is None else ' -and $n.Name -cin @('+','.join("'"+n+"'" for n in names)+')'
    return r'''
$a=[Management.Automation.Language.Parser]::ParseFile('PATH',[ref]$null,[ref]$null)
foreach($f in $a.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]PREDICATE},$false)){
 . ([scriptblock]::Create($f.Extent.Text))}
'''.replace('PATH', str(path).replace("'", "''")).replace('PREDICATE', predicate)


def test_missing_property_reports_source_location_not_error_text(monkeypatch):
    monkeypatch.setattr(ps_fixture, 'SCRIPT', ROOT/'scripts/verify_r6_auth_recovery.ps1')
    result = ps_fixture.run_ps(r'''
function Assert-R6Fixture { $v=[pscustomobject]@{}; $null=$v.secret_account_or_code }
try {Assert-R6Fixture}catch{Get-R6VerificationFailure $_|ConvertTo-Json -Depth 6 -Compress}
''')
    assert result['error_type'] == 'PropertyNotFoundException'
    assert result['frames'][0]['function'] == 'Assert-R6Fixture'
    assert result['frames'][0]['line'] > 0
    assert 'secret_account_or_code' not in json.dumps(result)
    assert result['raw_error_published'] is False


@pytest.mark.parametrize('fault', ['', 'schema', 'type', 'function', 'line', 'raw', 'too_many', 'missing'])
def test_parent_reprojects_only_valid_fixed_metadata(monkeypatch, fault):
    monkeypatch.setattr(ps_fixture, 'SCRIPT', ROOT/'scripts/run_r6_launch.ps1')
    value = dict(schema='cochem-r6-verification-failure/1', status='VERIFICATION_FAILED',
                 error_type='PropertyNotFoundException', hresult=-2146233087,
                 frames=[dict(function='Assert-R6VerifiedSignInRows', line=13, path='private-path')],
                 raw_error_published=False, message='secret-account', output='secret-code')
    if fault == 'schema': value['schema'] = 'other'
    if fault == 'type': value['error_type'] = 'secret-account'
    if fault == 'function': value['frames'][0]['function'] = 'https://secret.example/code'
    if fault == 'line': value['frames'][0]['line'] = 'secret'
    if fault == 'raw': value['raw_error_published'] = True
    if fault == 'too_many': value['frames'] *= 7
    if fault == 'missing': del value['hresult']
    body = import_functions(ROOT/'docs/deployment/windows-deployment-next/RUN_427_R5_SITTING.ps1', ['Get-R5JsonTail'])
    body += "$text='"+json.dumps(value)+"'\n"
    body += "@{diagnostic=(Read-R6VerificationFailure $text)}|ConvertTo-Json -Depth 6 -Compress"
    result = ps_fixture.run_ps(body)['diagnostic']
    if fault:
        assert result is None
    else:
        assert result == dict(error_type='PropertyNotFoundException', hresult=-2146233087,
                             frames=[dict(function='Assert-R6VerifiedSignInRows', line=13)])
        assert 'secret' not in json.dumps(result) and 'private-path' not in json.dumps(result)


def test_actual_verifier_failure_exits_nonzero_with_parseable_metadata_before_host_access(monkeypatch):
    # Invalid pins fail before importing helpers or opening any protected path.
    result = subprocess.run([ps_fixture.PS, '-NoProfile', '-NonInteractive', '-File',
        str(ROOT/'scripts/verify_r6_auth_recovery.ps1'), '-InstallerSha256', 'invalid',
        '-PhaseWrapperSha256', 'invalid'], capture_output=True, timeout=20)
    assert result.returncode == 1
    diagnostic = json.loads(result.stdout.decode('utf-8-sig'))
    assert diagnostic['status'] == 'VERIFICATION_FAILED'
    assert diagnostic['frames'][0]['function'] == 'Invoke-R6AuthRecoveryVerification'
    assert 'message' not in diagnostic


def test_failed_child_metadata_reaches_launcher_and_raw_output_stays_private(monkeypatch):
    monkeypatch.setattr(ps_fixture, 'SCRIPT', ROOT/'scripts/run_r6_launch.ps1')
    body = import_functions(ROOT/'docs/deployment/windows-deployment-next/RUN_427_R5_SITTING.ps1', ['Get-R5JsonTail'])
    body += r'''
$script:R6Pins=@{'verify_r6_auth_recovery.ps1'=('a'*64)}
$script:R6Directory='C:\fixture';$script:SittingRoot='C:\fixture'
$script:R6PowerShell='Invoke-R6FixtureChild';$script:R6Phase='verify_existing_installation'
$script:R6VerificationFailure=$null;$script:privateText=''
function Invoke-R6FixtureChild {
 $global:LASTEXITCODE=1
 'arbitrary private diagnostic text'
 '{"schema":"cochem-r6-verification-failure/1","status":"VERIFICATION_FAILED","error_type":"RuntimeException","hresult":-2146233087,"frames":[{"function":"Assert-R6VerifiedSignInRows","line":10}],"raw_error_published":false}'
}
function Write-R5RecordText {param($Path,$Text) $script:privateText=$Text; 'a'*64}
$held=$false
try{Invoke-R6LaunchChild 'verify_r6_auth_recovery.ps1' @()}catch{$held=$true}
@{held=$held;diagnostic=$script:R6VerificationFailure;private_preserved=$script:privateText.Contains('arbitrary private diagnostic text')}|ConvertTo-Json -Depth 6 -Compress
'''
    result = ps_fixture.run_ps(body)
    assert result['held'] and result['private_preserved']
    assert result['diagnostic']['frames'][0]['function'] == 'Assert-R6VerifiedSignInRows'
    assert 'arbitrary' not in json.dumps(result)
