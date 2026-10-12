from pathlib import Path

import pytest

from pipeline_tests import test_install_r6_runtime as ps_fixture


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(ps_fixture,'SCRIPT',Path(__file__).parents[1]/'scripts/run_r6_launch.ps1')
    return ps_fixture.run_ps


@pytest.mark.parametrize('failure', ['', 'offline_install','agent_staging','knowledge','agent','native','preview','activation'])
def test_sequence_stops_at_first_failure_and_never_calls_old_r5_cutover_or_fixture(run_ps, failure):
    result=run_ps(r"""
$script:events=[Collections.Generic.List[string]]::new()
$script:SittingRoot='C:\fixture\sitting';$script:R6CutoverRequested=$false
$script:R6Pins=@{'r6_retarget_core.ps1'=('a'*64);'install_r6_runtime.ps1'=('b'*64)}
$script:R5=@{base_source=@{kind='r4-restore';source_attempt='v3';stop_attempt='v4'}}
$manifest=@{install_manifest='C:\fixture\manifest.json';manifest_sha256=('c'*64);candidate_sha256=('d'*64)}
function Invoke-R5Stage0 {$script:events.Add('inspection')}
function Invoke-R5Stage2 {$script:events.Add('quiescence')}
function Invoke-R6LaunchChild {param($Name,$Arguments,[switch]$Attended)
    $script:events.Add($script:R6Phase)
    if($script:R6Phase -ceq 'FAILURE'){throw 'fixture hold'}
    if($Name -ceq 'install_r6_runtime.ps1'){return @{status='STOPPED_RUNTIME_INSTALLED'}}
    if($Name -ceq 'agy-isolation-evidence-r4-v1.ps1'){
        if('-StageOnly' -cnotin $Arguments){throw 'model evidence must use R6 routes'}
        return @{decision='COMPLETE'}}
    if($Name -ceq 'activate_r6_runtime.ps1'){
        if('-SourceAttempt' -notin $Arguments -or 'v3' -notin $Arguments -or 'v4' -notin $Arguments){throw 'lost source/stop lineage'}
        return @{status='WARDEN_R6_RUNNING_HEALTH_VERIFIED'}}
    throw 'unexpected child'
}
function Invoke-R6AcceptancePhase {param($Phase,$Manifest)
    $script:events.Add($Phase)
    if($Phase -ceq 'FAILURE'){throw 'fixture hold'}
    @{phase=$Phase;result=@{status='ALL_SESSIONS_VERIFIED'};receipt_path=('C:\fixture\'+$Phase);receipt_sha256=('e'*64)}}
function Write-R5RecordText {param($Path,$Text) $script:events.Add('index');'f'*64}
function Get-R5FreeAttempt {param($Prefix) 'v1'}
function Write-Host {param($Object,$ForegroundColor)}
function Write-R6PublicStatus {param($Status,$Result)}
function Save-R6AuthSummary {param($Result)}
$failed=$false
try{$null=Invoke-R6LaunchSequence $manifest}catch{$failed=$true}
@{failed=$failed;events=@($script:events);cutover=$script:R6CutoverRequested}|ConvertTo-Json -Compress
""".replace('FAILURE',failure))
    expected=['inspection','quiescence','offline_install','auth','agent_staging','knowledge','agent','native','preview','index','activation']
    if failure: expected=expected[:expected.index(failure)+1]
    assert result['events']==expected
    assert result['failed'] is bool(failure)
    assert result['cutover'] is (failure in ('','activation'))


def test_launch_refuses_unpinned_manifest_before_open(run_ps):
    result=run_ps("""
$held=$false
try{Read-R6LaunchManifest 'C:\\does-not-exist' 'bad'}catch{$held=$true;$message=$_.Exception.Message}
@{held=$held;message=$message}|ConvertTo-Json -Compress
""")
    assert result['held'] and 'exact launch manifest hash' in result['message']


def test_released_helpers_initialize_in_nested_scope_without_host_operations(run_ps):
    released=str(Path(__file__).parents[1]/'docs/deployment/windows-deployment-next/RUN_427_R5_SITTING.ps1').replace("'","''")
    result=run_ps(r"""
function Load-InNestedScope {
    . 'RELEASED' -Attempt v1 -Gemini attempt -SkipFixProof
    Initialize-R6ReleasedState
    @{attempt=$script:R5.attempt;gemini=$script:R5.gemini;slug=$script:R5.effort_null_slug;
      stopped=$script:R5.s2_done;cutover=$script:R5.r5_running;workspace=$script:Workspace}|ConvertTo-Json -Compress
}
Load-InNestedScope
""".replace('RELEASED',released))
    assert result['attempt']=='v1' and result['gemini']=='attempt'
    assert result['slug']=='gemini-3.8-flash-low'
    assert not result['stopped'] and not result['cutover']


@pytest.mark.parametrize('hold', [False, True])
def test_recovery_checks_existing_install_before_stop_and_never_reinstalls(run_ps, hold):
    result=run_ps(r'''
$script:events=[Collections.Generic.List[string]]::new()
$script:SittingRoot='C:\fixture';$script:R6CutoverRequested=$false
$script:R6Pins=@{'install_r6_runtime.ps1'=('a'*64);'run_r6_system_phase.ps1'=('b'*64);'r6_retarget_core.ps1'=('c'*64)}
$script:R5=@{base_source=@{kind='r4-restore';source_attempt='v2';stop_attempt='v2'}}
$manifest=[pscustomobject]@{auth_recovery='20261012-first-auth-hold';
manifest_sha256='bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4';
candidate_sha256='a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288'}
function Invoke-R5Stage0 {$script:events.Add('inspection')}
function Invoke-R5Stage2 {$script:events.Add('stop')}
function Invoke-R6LaunchChild {param($Name,$Arguments)
    $script:events.Add($Name)
    if($Name -ceq 'verify_r6_auth_recovery.ps1'){
        if(HOLD){throw 'preflight hold'}
        return @{status='EXISTING_R6_AUTH_RECOVERY_PREREQUISITES_VERIFIED'}}
    if($Name -ceq 'agy-isolation-evidence-r4-v1.ps1'){return @{decision='COMPLETE'}}
    if($Name -ceq 'activate_r6_runtime.ps1'){return @{status='WARDEN_R6_RUNNING_HEALTH_VERIFIED'}}
    throw 'unexpected child'}
function Invoke-R6AcceptancePhase {param($Phase,$Manifest)
    $script:events.Add($Phase)
    @{phase=$Phase;result=@{status='ALL_SESSIONS_VERIFIED'};receipt_path='fixture';receipt_sha256=('d'*64)}}
function Write-Host {param($Object,$ForegroundColor)}
function Write-R6PublicStatus {param($Status,$Result)}
function Save-R6AuthSummary {param($Result)}
function Write-R5RecordText {param($Path,$Text) 'e'*64}
function Get-R5FreeAttempt {param($Prefix) 'v1'}
$held=$false
try{$null=Invoke-R6LaunchSequence $manifest}catch{$held=$true}
@{held=$held;events=@($script:events)}|ConvertTo-Json -Compress
'''.replace('HOLD','$true' if hold else '$false'))
    assert result['held'] is hold
    assert 'install_r6_runtime.ps1' not in result['events']
    assert result['events'][:2]==['inspection','verify_r6_auth_recovery.ps1']
    if hold: assert len(result['events'])==2
    else: assert result['events'][2]=='stop' and result['events'][-1]=='activate_r6_runtime.ps1'


def test_public_auth_summary_excludes_arbitrary_diagnostics(run_ps):
    result=run_ps(r'''
function Write-R6PublicStatus {param($Status,$Result)}
$rows=@()
foreach($n in 1..6){foreach($p in @('codex','claude','gemini')){
    $rows+=[pscustomobject]@{worker=('slot'+$n);provider=$p;status='STATUS_UNVERIFIED';exit_code=1;
        reason='AGY_STATUS_UNRESOLVED';failure_category='auth';diagnostic_hint='secret token';raw_output='secret@example.com'}}}
Save-R6AuthSummary ([pscustomobject]@{checks=$rows})
@{rows=$script:R6AuthSummary}|ConvertTo-Json -Depth 6 -Compress
''')
    assert len(result['rows'])==18
    assert all(row.get('reason')=='AGY_STATUS_UNRESOLVED' for row in result['rows'])
    assert all('raw_output' not in row and 'diagnostic_hint' not in row for row in result['rows'])
