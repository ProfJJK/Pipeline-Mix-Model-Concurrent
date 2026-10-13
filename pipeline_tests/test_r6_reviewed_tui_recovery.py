"""Exact failed TUI and independent R4 v6 recovery; all host boundaries inert."""
import json
from pathlib import Path

import pytest

from pipeline_tests import test_install_r6_runtime as fixture

ROOT=Path(__file__).parents[1]
NONCE='43804e7a8d44457aa9810305923c219f'


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(fixture,'SCRIPT',ROOT/'scripts/verify_r6_auth_recovery.ps1')
    return fixture.run_ps


def receipt():
    return dict(schema='cochem-interactive-agy-login/1',slot='slot1',nonce=NONCE,
        login_mode='tui',status='LOGIN_FAILED_OR_CANCELLED',system_sid='S-1-5-18',
        cleanup_verified=True,one_line_submitted=False,input_closed_marker_written=True,
        login_commands_executed=1,model_jobs_executed=0,authentication_verified=False,
        activation_ready=False,secret_published=False,native_output_after_input_published=False,
        native_output_bytes_before_input=0,native_output_published_bytes_before_input=0,
        failure=dict(phase='native_wait',error_type='TimeoutError',winerror=None),
        helper_sha256='4074878f100ae59b804c95bd97b3280ccaa09f919ffaa365a3e2c6985045b8d9',
        support_sha256='45681477194d97b144e8ee4505d4364d73d58aaef19c8428c846df642c834839',
        native_executable_sha256='38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741')


@pytest.mark.parametrize('mutation',['','cleanup','input','output','helper','sid','native','wrong-phase','other-error','job'])
def test_only_exact_zero_output_no_input_failure_is_admitted(run_ps,mutation):
    r=receipt()
    changes=dict(cleanup=('cleanup_verified',False),input=('one_line_submitted',True),
        output=('native_output_bytes_before_input',1),helper=('helper_sha256','a'*64),
        sid=('system_sid','S-1-5-32-544'),native=('native_executable_sha256','a'*64),job=('model_jobs_executed',1))
    if mutation in changes:
        key,value=changes[mutation];r[key]=value
    if mutation=='wrong-phase':r['failure']['phase']='native_result'
    if mutation=='other-error':r['failure']['error_type']='WindowsIsolationError'
    result=run_ps("$r='"+json.dumps(r)+"'|ConvertFrom-Json\n"+r'''
$held=$false;try{Assert-R6ReviewedTuiReceipt $r}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
''')
    assert result['held'] is bool(mutation)


@pytest.mark.parametrize('mutation',['','receipt-hash','running','instances','result','input-left','wrapper-record','restore-hash','restore-health','helper'])
def test_preserved_tui_requires_independent_v6_restore_not_missing_wrapper_inference(run_ps,mutation):
    result=run_ps("$script:receipt='"+json.dumps(receipt())+"'|ConvertFrom-Json\n"+r'''
$script:base='C:\fixture';$script:events=[Collections.Generic.List[string]]::new()
function Read-R6RecoveryJson {param($Path,$Hash)
 if($Path -like '*\receipt.json'){
  if($Hash -cne 'dfad79544643ccfbca3653a66024f3e3020fa63ea23f46ce702430da9376b72a' -or 'MUTATION' -eq 'receipt-hash'){throw 'receipt not pinned'}
  return $script:receipt}
 if($Path -like '*\stop-receipt.json'){
  if($Hash -cne 'f62d79731b2e1d0440f1ed49b6d43334f8ff3ddfc2b1a45ab670a85f0d232d67'){throw 'stop not pinned'}
  $script:events.Add('stop');return @{}}
 if($Path -like '*\retarget-receipt.json'){
  if($Hash -cne '0a59de000c06cda9426ea5f9e7f76ff1e9f63dd11c33ced8a85f7cbffa577fc7'){throw 'retarget not pinned'}
  $script:events.Add('retarget');return @{}}
 if($Path -like '*\start-receipt.json'){
  if($Hash -cne 'f2de0214197af0c54ff04c25246dd74a13d210de007fc107e6d485b9ad5ab50f' -or 'MUTATION' -eq 'restore-hash'){throw 'restore not pinned'}
  $script:events.Add('start')
  return @{schema='cochem-warden-start/3';status='WARDEN_R4_RESTARTED_HEALTH_VERIFIED';target='r4';attempt='v6';task_name='CoChem-4.2.7-Warden';
   enabled_after=$true;task_state=4;running_instances=1;health_samples=2;health=@{samples_stable=('MUTATION' -ne 'restore-health')};
   exactly_one_start_requested=$true;automatic_retry_allowed=$false}}
 throw 'unexpected read'}
function Get-R6ReviewedTuiTask {
 $task=[pscustomobject]@{Name='CoChem-4.2.7-InteractiveAgy-r4-slot1-43804e7a8d44457aa9810305923c219f';
  State=$(if('MUTATION' -eq 'running'){4}else{3});LastTaskResult=$(if('MUTATION' -eq 'result'){0}else{2})}
 $task|Add-Member ScriptMethod GetInstances {param($Flags) @{Count=$(if('MUTATION' -eq 'instances'){1}else{0})}}
 $task}
function Assert-R6PhaseTask {param($Task,$Python,$Arguments,$Root,$Seconds,$Enabled)
 if($Seconds -ne 900 -or -not $Enabled -or $Arguments -cne ('-I -B "'+$Root+'\worker_agy_login_bridge_r4_v1.py" --slot slot1 --nonce 43804e7a8d44457aa9810305923c219f --login-mode tui') -or
  $Python -cne 'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\Scripts\python.exe'){throw 'task arguments differ'}}
function Test-Path {param($LiteralPath)
 return ('MUTATION' -eq 'input-left' -and $LiteralPath -like '*\input.once') -or ('MUTATION' -eq 'wrapper-record' -and $LiteralPath -like '*\session-held.json')}
function Assert-ProtectedPath {param($Path)}
function Get-Item {param($LiteralPath) @{Length=100}}
function Open-VerifiedFile {param($Path,$Hash,$Length)
 if('MUTATION' -eq 'helper'){throw 'changed helper'};$script:events.Add((Split-Path -Leaf $Path));[IO.MemoryStream]::new()}
$held=$false;try{Assert-R6ReviewedTuiSession}catch{$held=$true}
@{held=$held;events=@($script:events)}|ConvertTo-Json -Compress
'''.replace('MUTATION',mutation))
    assert result['held'] is bool(mutation),result
    if not mutation:
        assert result['events']==['stop','retarget','start','worker_agy_login_bridge_r4_v1.py','worker_native_status_support.py']


def test_interactive_census_requires_both_reviewed_sessions_and_rejects_an_extra(run_ps):
    result=run_ps(r'''
$script:base='C:\fixture';$script:extra=$false
function Get-ChildItem {param($LiteralPath,[switch]$Directory,$Filter)
 foreach($n in @('67d70b0983cc48e2abf7c561aca29f86','43804e7a8d44457aa9810305923c219f')){
  $name='InteractiveAgy427-r4-slot1-'+$n;[pscustomobject]@{Name=$name;FullName=(Join-Path $script:base $name)}}
 if($script:extra){[pscustomobject]@{Name='unexpected';FullName='C:\unexpected'}}}
function Get-R6Slot1InteractiveTasks {
 foreach($n in @('67d70b0983cc48e2abf7c561aca29f86','43804e7a8d44457aa9810305923c219f')){
  [pscustomobject]@{Name=('CoChem-4.2.7-InteractiveAgy-r4-slot1-'+$n)}}}
Assert-R6ReviewedInteractiveCensus $true $true
$script:extra=$true;$held=$false;try{Assert-R6ReviewedInteractiveCensus $true $true}catch{$held=$true}
@{extra_held=$held}|ConvertTo-Json -Compress
''')
    assert result['extra_held']
