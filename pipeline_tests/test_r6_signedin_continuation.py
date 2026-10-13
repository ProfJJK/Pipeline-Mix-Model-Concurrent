"""Source and inert PowerShell boundaries only; no scheduled task is run."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from pipeline_tests import test_install_r6_runtime as ps_fixture
from cochem_pipeline.routing import load_routing_policy, RoutingPolicy

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('r6_retirement_guard', ROOT/'scripts/r6_retirement_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_retirement_preserves_captures_and_all_survivors_and_disables_old_targets(monkeypatch):
    policy = load_routing_policy({'policy_version': 3})
    before = policy.as_dict()
    digest = policy.digest
    original = RoutingPolicy.candidates
    expected = {n: original(policy, n) for n in range(1, 11)}
    monkeypatch.setattr(RoutingPolicy, 'candidates', original)
    guard.apply_retirement(RoutingPolicy)
    try:
        for n in range(1, 11):
            filtered = tuple(t for t in expected[n] if t.model not in guard.RETIRED)
            assert policy.candidates(n) == filtered
            assert len(filtered) == (2 if n in (5, 6) else 3)
        for n in (5, 6):
            retired = expected[n][-1]
            assert not policy.is_enabled(retired)
            assert all(t.provider != 'gemini' for t in policy.candidates(n))
        assert policy.as_dict() == before and policy.digest == digest
        assert policy.backoff_delay(1, 'same-job') > 0
        with pytest.raises(ValueError, match='already installed'):
            guard.apply_retirement(RoutingPolicy)
    finally:
        del RoutingPolicy._r6_owner_retirement


def test_guard_against_the_original_frozen_r6_selection_code(monkeypatch):
    # Load source text, never the protected interpreter or a daemon. This catches
    # incompatibility with the installed 359ca92 code, not just today's R7 tree.
    source = Path(r'C:\Users\ansac\CoChem427\r6-source-359ca92\src\cochem_pipeline\routing.py')
    if not source.exists(): pytest.skip('Original host source freeze not available')
    name = 'cochem_pipeline._r6_frozen_routing_test'
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    policy = module.load_routing_policy({'policy_version': 3})
    retired = policy.candidates(6)[2]
    guard.apply_retirement(module.RoutingPolicy)
    assert len(policy.candidates(5)) == len(policy.candidates(6)) == 2
    assert not policy.is_enabled(retired)
    assert policy.candidates(1)[0].model == 'gemini-3.8-flash'


def test_old_captured_indices_survive_and_retirement_is_checked_before_reservation(monkeypatch):
    from types import SimpleNamespace
    legacy=load_routing_policy({'policy_version':2})
    captured=legacy.candidates(5)
    calls=[]
    admission=SimpleNamespace(_candidate_unavailability=lambda *args:calls.append(args))
    original=RoutingPolicy.candidates
    monkeypatch.setattr(RoutingPolicy,'candidates',original)
    guard.apply_retirement(RoutingPolicy,admission)
    try:
        assert legacy.candidates(5)==captured
        for model in guard.RETIRED:
            assert admission._candidate_unavailability(None,None,None,{'provider':'gemini','model':model},None,0)=='retired_target'
        assert not calls  # No reservation, database write or consumed attempt.
        survivor={'provider':'claude','model':'claude-opus-5-5'}
        admission._candidate_unavailability(None,None,None,survivor,None,0)
        assert calls[0][3] is survivor
    finally:
        del RoutingPolicy._r6_owner_retirement


def rows():
    return dict(status='ALL_SIX_AGY_PROFILES_VERIFIED', native_model_jobs_executed=0,
        daemon_tasks_changed=False, credentials_copied=False, activation_ready=False,
        checks=[dict(slot=f'slot{i}',authenticated=True,status='SIGNED_IN_AND_VERIFIED',cleanup_verified=True,
            after=dict(decision='VERIFIED',exit_code=0,cleanup_verified=True),
            login=dict(terminal_cleanup_verified=True,input_file_deleted=True,code_write_completed=True))
            for i in range(1,7)])


@pytest.mark.parametrize('fault',['','duplicate','missing','auth','cleanup','after','login_exit_only','model_job',
    'row_cleanup','status_cleanup','input_left','code_not_written','missing_terminal_cleanup'])
def test_accept_only_six_verified_post_login_rows(monkeypatch,fault):
    monkeypatch.setattr(ps_fixture,'SCRIPT',ROOT/'scripts/verify_r6_auth_recovery.ps1')
    value=rows()
    if fault=='duplicate':value['checks'][-1]=value['checks'][0]
    if fault=='missing':value['checks'].pop()
    if fault=='auth':value['checks'][0]['authenticated']=False
    if fault=='cleanup':value['checks'][0]['login']['terminal_cleanup_verified']=False
    if fault=='after':value['checks'][0]['after']['exit_code']=1
    if fault=='login_exit_only':value['checks'][0]['after']['decision']='UNKNOWN'
    if fault=='model_job':value['native_model_jobs_executed']=1
    if fault=='row_cleanup':value['checks'][0]['cleanup_verified']=False
    if fault=='status_cleanup':value['checks'][0]['after']['cleanup_verified']=False
    if fault=='input_left':value['checks'][0]['login']['input_file_deleted']=False
    if fault=='code_not_written':value['checks'][0]['login']['code_write_completed']=False
    if fault=='missing_terminal_cleanup':del value['checks'][0]['login']['terminal_cleanup_verified']
    result=ps_fixture.run_ps("$value='"+json.dumps(value)+"'|ConvertFrom-Json\n"+r'''
$held=$false
try{Assert-R6VerifiedSignInRows $value}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
''')
    assert result['held'] is bool(fault)


def test_receipt_from_production_signin_sequence_passes_verifier(monkeypatch, tmp_path):
    """Exercise the producer's actual projection, with native operations replaced."""
    spec = importlib.util.spec_from_file_location('signin_producer', ROOT/'scripts/worker_agy_signin_batch.py')
    producer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(producer)
    monkeypatch.setattr(producer, 'write_new', lambda *args: None)
    def status(slot, child, phase):
        return dict(decision='LOGIN_REQUIRED' if phase == 'before' else 'VERIFIED',
                    exit_code=1 if phase == 'before' else 0, cleanup_verified=True)
    def login(slot, child):
        return dict(status='LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED', native_exit_code=1,
                    cleanup_verified=True, terminal_cleanup_verified=True, one_line_submitted=True,
                    code_write_completed=True, input_file_deleted=True, pause_marker_seen=False)
    value = rows()
    value['checks'] = producer.sequence(tmp_path, 'a'*32, float('inf'), status, login)
    assert all('cleanup_verified' not in row['login'] for row in value['checks'])
    monkeypatch.setattr(ps_fixture, 'SCRIPT', ROOT/'scripts/verify_r6_auth_recovery.ps1')
    result = ps_fixture.run_ps("$value='"+json.dumps(value)+"'|ConvertFrom-Json\n"+r'''
Assert-R6VerifiedSignInRows $value
@{verified=$true}|ConvertTo-Json -Compress
''')
    assert result['verified']


def test_owner_successful_public_receipt_passes_verifier(monkeypatch):
    """Read only the already-public report; never open private evidence or run providers."""
    path = Path(r'C:\Program Files\CoChem\AgySignIn427-6f2553e0f3e04a1598e64ffaad1d7255\status.json')
    if not path.exists():
        pytest.skip('Owner public receipt is not available on this host')
    import hashlib
    assert hashlib.sha256(path.read_bytes()).hexdigest() == '96e4d2a872ff64a265efde9f1d1dade42db73f9da85863befc93692ece7ccfff'
    monkeypatch.setattr(ps_fixture, 'SCRIPT', ROOT/'scripts/verify_r6_auth_recovery.ps1')
    result = ps_fixture.run_ps("$value=Get-Content -LiteralPath '"+str(path)+"' -Raw|ConvertFrom-Json\n"+r'''
Assert-R6VerifiedSignInRows $value
@{verified=$true;profiles=@($value.checks).Count}|ConvertTo-Json -Compress
''')
    assert result == dict(verified=True, profiles=6)


def test_task_action_binds_guard_and_still_uses_original_config(monkeypatch):
    monkeypatch.setattr(ps_fixture,'SCRIPT',ROOT/'scripts/activate_r6_runtime.ps1')
    result=ps_fixture.run_ps(r'''
$context=[ordered]@{config_path='C:\protected\pipeline.json';queue_launch_output_root='C:\private\queue';config_mode='old';action=@{arguments='old'}}
Set-R6RetirementContext $context 'C:\Program Files\CoChem\R6Retirement4.2.7-windows-20261013-v1\r6_retirement_guard.py' ('a'*64)
$context|ConvertTo-Json -Depth 5 -Compress
''')
    assert '--guard-sha256 '+'a'*64 in result['action']['arguments']
    assert '--config "C:\\protected\\pipeline.json"' in result['action']['arguments']
    assert result['retirement_guard']['replacement_selected'] is False


@pytest.mark.parametrize('bad', ['C:\\Users\\ansac\\guard.py', 'C:\\Program Files\\CoChem\\R6Retirement4.2.7-windows-20261013-v1\\..\\guard.py'])
def test_task_action_rejects_unprotected_or_ambiguous_guard(monkeypatch,bad):
    monkeypatch.setattr(ps_fixture,'SCRIPT',ROOT/'scripts/activate_r6_runtime.ps1')
    result=ps_fixture.run_ps("$held=$false\ntry{Set-R6RetirementContext @{} '"+bad+"' ('a'*64)}catch{$held=$true}\n@{held=$held}|ConvertTo-Json -Compress")
    assert result['held']


@pytest.mark.parametrize('auth_ok',[True,False])
def test_signedin_sequence_cannot_reenter_attended_login_or_reinstall(monkeypatch,auth_ok):
    monkeypatch.setattr(ps_fixture,'SCRIPT',ROOT/'scripts/run_r6_launch.ps1')
    result=ps_fixture.run_ps(r'''
$script:events=[Collections.Generic.List[string]]::new();$script:SittingRoot='C:\fixture'
$script:R6Pins=@{'install_r6_runtime.ps1'=('a'*64);'run_r6_system_phase.ps1'=('b'*64);'r6_retarget_core.ps1'=('c'*64);
 'r6_native_retirement.py'=('d'*64);'r6_retirement_guard.py'=('e'*64)}
$manifest=[pscustomobject]@{auth_recovery='20261012-first-auth-hold';verified_signin_continuation='20261013-six-agy-verified-r4-v7';
 manifest_sha256='bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4';candidate_sha256='a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288'}
$script:R5=@{base_source=@{kind='r4-restore';source_attempt='v7';stop_attempt='v7'}}
function Invoke-R5Stage0 {$script:events.Add('inspect')}
function Invoke-R5Stage2 {$script:events.Add('stop')}
function Write-R6PublicStatus {}
function Save-R6AuthSummary {}
function Write-Host {}
function Write-R5RecordText {'f'*64}
function Get-R5FreeAttempt {'v1'}
function Invoke-R6LaunchChild {param($Name,$Arguments,[switch]$Attended)
 if($Attended -or $Name -like '*attended*' -or $Name -eq 'install_r6_runtime.ps1'){throw 'Forbidden interactive/install branch'}
 $script:events.Add($Name)
 if($Name -eq 'verify_r6_auth_recovery.ps1'){
   if('-AuthenticatedContinuation' -notin $Arguments){throw 'lost verification gate'}
   return @{status='EXISTING_R6_AUTH_RECOVERY_PREREQUISITES_VERIFIED'}}
 if($Name -eq 'agy-isolation-evidence-r4-v1.ps1'){return @{decision='COMPLETE'}}
 if($Name -eq 'activate_r6_runtime.ps1'){
   if('-RetirementGuardSha256' -notin $Arguments -or 'v7' -notin $Arguments){throw 'lost runtime retirement/lineage'}
   return @{status='WARDEN_R6_RUNNING_HEALTH_VERIFIED'}}
 throw 'Unexpected child'
}
function Invoke-R6AcceptancePhase {param($Phase,$Manifest)
 $script:events.Add($Phase)
 @{phase=$Phase;receipt_path='C:\fixture\receipt';receipt_sha256=('f'*64);
 result=@{status=$(if($Phase -eq 'auth' -and 'AUTH_OK' -eq 'False'){'ATTENDED_AUTH_REVIEW_REQUIRED'}else{'ALL_SESSIONS_VERIFIED'})}}
}
$held=$false;$message=''
try{Invoke-R6LaunchSequence $manifest}catch{$held=$true;$message=$_.Exception.Message}
@{held=$held;events=@($script:events);message=$message}|ConvertTo-Json -Compress
'''.replace('AUTH_OK',str(auth_ok)))
    assert result['held'] is not auth_ok, result
    expected=['inspect','verify_r6_auth_recovery.ps1','stop','auth']
    if auth_ok:expected+=['agy-isolation-evidence-r4-v1.ps1','knowledge','agent','native','preview','activate_r6_runtime.ps1']
    assert result['events']==expected, result
    if not auth_ok:assert 'no legacy sign-in' in result['message']


@pytest.mark.parametrize('fault',['','phase','run_requested','result','instances','last_run','restore','artifact','task_missing'])
def test_registration_hold_is_never_run_and_restored_to_v7(monkeypatch,fault):
    monkeypatch.setattr(ps_fixture,'SCRIPT',ROOT/'scripts/verify_r6_auth_recovery.ps1')
    result=ps_fixture.run_ps(r'''
$script:base='C:\fixture';$script:task_checked=$false;$script:auth_checked=$false
function Read-R6RecoveryJson {param($Path,$Hash)
 if($Path -like '*result.json'){
   return @{phase='auth';status='PHASE_COMPLETED';manifest_sha256='bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4';
     candidate_sha256='a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288';
     result=@{status_helper_sha256='79b7029cd998f25c0a01300924bb3972f830f7783618ce3c99260b089510aaec'}}}
 if($Path -like '*session-held.json'){
   return @{schema='cochem-interactive-agy-terminal-held/1';status='HELD';slot='slot1';nonce='920c3ba4a0aa4c1094eaf4ce3319eba4';
     phase=$(if('FAULT' -eq 'phase'){'run'}else{'register'});run_requested=('FAULT' -eq 'run_requested');receipt_sha256=$null;
     raw_provider_output_recorded=$false;code_recorded=$false}}
 if($Path -like '*start-receipt.json'){
   if($Hash -ne '449bff46b15018e1ff47e389c5765df49f86b4cee36e3b1c8778390568e4cf97'){throw 'lost restore hash'}
   return @{attempt=$(if('FAULT' -eq 'restore'){'v6'}else{'v7'})}}
 if($Path -like '*retarget-receipt.json'){
   if($Hash -ne '80c50e6272940fe89bf53e2c01e9c38481ab6b1e32b7392d4c7946fed1c29d67'){throw 'lost lineage hash'};return @{}}
 throw 'Unexpected read'
}
function Assert-R6AuthRecoveryRows {param($Result,$Status) if($Status -ne 'ATTENDED_LOGIN_REQUIRED'){throw 'status drift'}}
function Assert-R6ReviewedAuthTask {param($Root,$Name)
 if($Name -ne 'CoChem-4.2.7-R6Acceptance-auth-c5ffd975db154abe9411be085e25f96d'){throw 'wrong auth task'};$script:auth_checked=$true}
function Assert-R6PhaseTask {param($Task,$Executable,$Arguments,$Directory,$Seconds,$Enabled)
 if($Seconds -ne 900 -or -not $Enabled -or $Arguments -notlike '*--nonce 920c3ba4a0aa4c1094eaf4ce3319eba4'){throw 'task binding drift'}
 $script:task_checked=$true}
function Assert-R6ReviewedRestore {param($Receipt,$Attempt) if($Receipt.attempt -ne 'v7' -or $Attempt -ne 'v7'){throw 'wrong restore'}}
function Test-Path {param($LiteralPath) ('FAULT' -eq 'artifact' -and $LiteralPath -like '*input.once')}
function Get-R6SignInTasks {
 if('FAULT' -eq 'task_missing'){return}
 $task=[pscustomobject]@{Name='CoChem-4.2.7-InteractiveAgyTerminal-r4-slot1-920c3ba4a0aa4c1094eaf4ce3319eba4';State=3;
  LastTaskResult=$(if('FAULT' -eq 'result'){0}else{267011});LastRunTime=$(if('FAULT' -eq 'last_run'){[DateTime]'2026-10-13'}else{[DateTime]'1999-11-30'})}
 $task|Add-Member ScriptMethod GetInstances {param($Flags) @{Count=$(if('FAULT' -eq 'instances'){1}else{0})}}
 $task
}
$held=$false
try{Assert-R6ReviewedRegistrationHold 'C:\fixture\auth'}catch{$held=$true}
@{held=$held;task_checked=$script:task_checked;auth_checked=$script:auth_checked}|ConvertTo-Json -Compress
'''.replace('FAULT',fault))
    assert result['held'] is bool(fault),result
    if not fault: assert result['task_checked'] and result['auth_checked']


@pytest.mark.parametrize('fault',['','missing_task','extra_task','running','broker_failed','nonce','private_status','input_left','prior_cleanup'])
def test_successful_signin_census_requires_terminal_brokers_and_private_evidence(monkeypatch,fault):
    monkeypatch.setattr(ps_fixture,'SCRIPT',ROOT/'scripts/verify_r6_auth_recovery.ps1')
    result=ps_fixture.run_ps("$script:fixtureRows='"+json.dumps(rows())+"'|ConvertFrom-Json\n"+r'''
$script:base='C:\fixture'
function Read-R6RecoveryJson {param($Path,$Hash)
 if($Path -like '*29d5943c97954a7695d57c722e917cd2\status.json'){
   if($Hash -ne 'a2d3cf3bbaf19f6917ac3826f3fc4bc3774f9fc327e24419e2cf0cb0449ccfa0'){throw 'prior pin drift'};return @{}}
 if($Path -like '*login.json'){return @{cleanup_verified=('FAULT' -ne 'prior_cleanup');terminal_cleanup_verified=$true;one_line_submitted=$false}}
 $value=$script:fixtureRows|ConvertTo-Json -Depth 8|ConvertFrom-Json
 if($Path -like '*status.json'){
   if($Hash -ne '96e4d2a872ff64a265efde9f1d1dade42db73f9da85863befc93692ece7ccfff'){throw 'success pin drift'}
   $value|Add-Member schema 'cochem-agy-signin-result/1';$value|Add-Member root 'C:\fixture\AgySignIn427-6f2553e0f3e04a1598e64ffaad1d7255'
 }else{
   $value|Add-Member schema 'cochem-agy-signin-batch/1';$value|Add-Member system_sid 'S-1-5-18'
   $value|Add-Member nonce $(if('FAULT' -eq 'nonce'){'wrong'}else{'6f2553e0f3e04a1598e64ffaad1d7255'})
   if('FAULT' -eq 'private_status'){$value.checks[0].after.exit_code=1}
 };$value
}
function Test-Path {param($LiteralPath) ('FAULT' -eq 'input_left')}
function Get-R6SignInTasks {
 $names=@('CoChem-4.2.7-InteractiveAgyTerminal-r4-slot1-920c3ba4a0aa4c1094eaf4ce3319eba4',
   'CoChem-4.2.7-AgySignIn-29d5943c97954a7695d57c722e917cd2','CoChem-4.2.7-AgySignIn-6f2553e0f3e04a1598e64ffaad1d7255')
 if('FAULT' -eq 'missing_task'){$names=$names[0..1]}
 if('FAULT' -eq 'extra_task'){$names+='unreviewed'}
 foreach($name in $names){
   $last=if($name -like '*29d*'){2}elseif($name -like '*Terminal*'){267011}elseif('FAULT' -eq 'broker_failed'){2}else{0}
   $task=[pscustomobject]@{Name=$name;State=$(if('FAULT' -eq 'running'){4}else{3});LastTaskResult=$last}
   $task|Add-Member ScriptMethod GetInstances {param($Flags) @{Count=0}};$task
 }
}
$held=$false;$message=''
try{Assert-R6SuccessfulStandaloneSignIn}catch{$held=$true;$message=$_.Exception.Message}
@{held=$held;message=$message}|ConvertTo-Json -Compress
'''.replace('FAULT',fault))
    assert result['held'] is bool(fault),result


@pytest.mark.parametrize('collision',[False,True])
def test_guard_copy_keeps_exact_bytes_and_never_reuses_an_existing_root(monkeypatch,tmp_path,collision):
    import hashlib
    monkeypatch.setattr(ps_fixture,'SCRIPT',ROOT/'scripts/activate_r6_runtime.ps1')
    source=tmp_path/'source.py';source.write_bytes(b'# inert fixture\n')
    destination=tmp_path/'private-fixture'/'guard.py'
    if collision:
        destination.parent.mkdir();destination.write_bytes(b'keep')
    body=r'''
function Open-VerifiedFile {param($Path,$Hash,$Length)
 $sha=[Security.Cryptography.SHA256]::Create()
 try{$actual=[BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($Path))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
 if($actual -cne $Hash){throw 'pin drift'}
 [IO.File]::Open($Path,'Open','Read','Read')
}
function New-PrivateDirectory {param($Path)
 if(Test-Path -LiteralPath $Path){throw 'preserve existing root'}
 $null=[IO.Directory]::CreateDirectory($Path)
}
function New-PrivateAcl {param($Directory)
 $acl=[Security.AccessControl.FileSecurity]::new()
 $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.WindowsIdentity]::GetCurrent().User,'FullControl','Allow'))
 $acl
}
$handles=[Collections.Generic.List[IO.FileStream]]::new();$held=$false;$message=''
try{Copy-R6RetirementGuard 'SOURCE' 'DESTINATION' 'HASH' $handles}catch{$held=$true;$message=$_.Exception.Message}
$count=$handles.Count;foreach($handle in $handles){$handle.Dispose()}
@{held=$held;handles=$count;message=$message}|ConvertTo-Json -Compress
'''.replace('SOURCE',str(source).replace("'","''")).replace('DESTINATION',str(destination).replace("'","''")).replace('HASH',hashlib.sha256(source.read_bytes()).hexdigest())
    result=ps_fixture.run_ps(body)
    assert result['held'] is collision,result
    assert result['handles']==(0 if collision else 1)
    assert destination.read_bytes()==(b'keep' if collision else source.read_bytes())
