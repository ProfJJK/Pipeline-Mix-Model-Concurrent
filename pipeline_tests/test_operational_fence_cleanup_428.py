"""Inert Windows PowerShell fixtures; no tasks, providers or process lifecycle."""
import pytest

from pipeline_tests.test_operational_launch_428 import inert_ps


FENCE = r"""
$script:mode='MODE';$script:writes=0;$script:count=1
$script:OpPrivate='PRIVATE';$script:OpOldConfig='C:\fixture\old\pipeline.json'
$script:OpConfig=@{private_root='C:\fixture\board'}
$script:OpManifest=@{previous_config_sha256=('a'*64);request_sha256=('b'*64)}
$nonce='a'*32;$root=Join-Path $script:OpPrivate ('stop-fence-'+('d'*32))
$when=[DateTime]::UtcNow.AddSeconds(-1)
if($script:mode -eq 'stale'){$when=$when.AddSeconds(-210)}
if($script:mode -like 'terminal_*'){$when=$when.AddSeconds(-300);$script:count=0}
$args='-I -B -m cochem_pipeline.owner_admission_fence_428 --config "'+$script:OpOldConfig+'" --config-sha256 '+$script:OpManifest.previous_config_sha256+
    ' --output-root "'+$root+'" --nonce '+$nonce+' --request-sha256 '+$script:OpManifest.request_sha256+' --wait-seconds 1800 --hold-seconds 240'
$script:OpRoot='C:\fixture\new'
# The one-shot's registered definition, read from a fresh task copy (structural identity).
$fixtureAction=[pscustomobject]@{Type=0;Arguments=$args}
# Registered under whatever r5 root the test sets before the fence is checked.
$fixtureAction|Add-Member ScriptProperty Path {Join-Path $script:OpRoot '.venv\Scripts\python.exe'}
$fixtureAction|Add-Member ScriptProperty WorkingDirectory {$script:OpRoot}
$fixtureActions=[pscustomobject]@{Count=1;A=$fixtureAction};$fixtureActions|Add-Member ScriptMethod Item {param($i)$this.A}
$script:task=[pscustomobject]@{State=4;Xml='exact-xml';LastRunTime=$when;LastTaskResult=0;
    Definition=[pscustomobject]@{Triggers=[pscustomobject]@{Count=0};Actions=$fixtureActions;Principal=[pscustomobject]@{UserId='SYSTEM';LogonType=5;RunLevel=1};
        Settings=[pscustomobject]@{Enabled=$true;RestartCount=0;MultipleInstances=2;AllowDemandStart=$true;ExecutionTimeLimit='PT2100S'}}}
if($script:mode -like 'terminal_*'){$script:task.LastTaskResult=2;$script:task.State=3}
$script:task|Add-Member ScriptMethod GetSecurityDescriptor {param($f)'exact-sddl'}
$script:task|Add-Member ScriptMethod GetInstances {
    param($f)$v=[pscustomobject]@{Count=$script:count}
    $v|Add-Member ScriptMethod Item {param($i)[pscustomobject]@{InstanceGuid=$(if($script:mode -eq 'foreign_instance'){'other'}else{'exact-instance'})}};return $v
}
$script:OpFolder=[pscustomobject]@{}
$script:OpFolder|Add-Member ScriptMethod GetTask {param($n)return $script:task}
$handle=@{name=('CoChem-4.2.8-Fence-'+$nonce);arguments=$args;instance='exact-instance';started=$when;seconds=2100;sddl='exact-sddl'}
$script:ready=[pscustomobject]@{schema='cochem-owner-admission-fence/4.2.8';status='WRITER_FENCE_HELD';nonce=$nonce;
    config_sha256=('a'*64);request_sha256=('b'*64);database_path='C:\fixture\board\job_board.db';pid=123;
    ready_at=([DateTimeOffset]$when).ToUnixTimeSeconds();expires_at=([DateTimeOffset]$when).ToUnixTimeSeconds()+240;
    counts=[pscustomobject]@{active_leases=0}}
$fence=@{root=$root;nonce=$nonce;arguments=$args;name=$handle.name;intent_at=$when.AddSeconds(-1);owned=$true;handle=$handle;
    ready=$script:ready;ready_pin=('c'*64);released=$false;process=$null;completion=$null}
switch($script:mode){
    'nonzero' {$script:ready.counts.active_leases=1}
    'foreign_nonce' {$script:ready.nonce='b'*32}
    'foreign_request' {$script:ready.request_sha256='d'*64}
    'foreign_config' {$script:ready.config_sha256='d'*64}
    'foreign_database' {$script:ready.database_path='C:\foreign\board.db'}
    'foreign_task' {$fixtureAction.Arguments='changed'}
    'incomplete_handle' {$fence.owned=$false}
    'changed_ready_pin' {$fence.ready_pin='d'*64}
}
function Assert-ProtectedPath {param($p)}
function Assert-428TaskAcl {param($t)}
function Get-428FileSha256 {param($p)return ('c'*64)}
function Open-428Pin {param($p,$h)return [IO.MemoryStream]::new()}
function Read-428Json {param($s)return $script:ready}
function Confirm-OpFenceProcess {
    param($f)Assert-OpFenceBinding $f;$null=Assert-OpOneShot $f.handle $true
    $p=[pscustomobject]@{HasExited=$false}
    $p|Add-Member ScriptMethod WaitForExit {param($ms)return $true}
    $f.process=$p
}
function Get-CimInstance {
    param($class,$filter)
    if($script:mode -eq 'terminal_foreign_pid'){return [pscustomobject]@{ProcessId=123}}
    return $null
}
function Write-OpRecord {
    param($p,$r)$script:writes++
    if(Test-Path -LiteralPath (Join-Path $root 'release.json')){throw 'Release was exposed before complete write.'}
    [IO.File]::WriteAllText($p,($r|ConvertTo-Json -Compress))
    $script:count=0;$script:task.State=3
}
function Read-OpPrivateRecord {
    param($p)
    if($p.EndsWith('release.json')){return (Get-Content -LiteralPath $p -Raw|ConvertFrom-Json)}
    $expired=$script:mode -like 'terminal_*'
    return [pscustomobject]@{schema='cochem-owner-admission-fence/4.2.8';status=$(if($expired){'FENCE_EXPIRED'}else{'LOCK_RELEASED'});
        nonce=$nonce;ready_sha256=('c'*64);request_sha256=('b'*64);config_sha256=('a'*64);
        database_path='C:\fixture\board\job_board.db';pid=$(if($script:mode -eq 'terminal_bad_receipt'){999}else{123});
        released=(-not $expired);lock_released=$true}
}
$admission_rejected=$false
try{Assert-OpFence $fence}catch{$admission_rejected=$true}
$held=$false;$failure=$null
try{Release-OpFence $fence}catch{$held=$true;$failure=Get-OpFailure $_ 'fence_cleanup'}
@{held=$held;admission_rejected=$admission_rejected;writes=$script:writes;completion=$fence.completion;
    released=$fence.released;
    failure=$failure;release_exists=(Test-Path -LiteralPath (Join-Path $root 'release.json'));
    pending_exists=(Test-Path -LiteralPath (Join-Path $root 'release.pending'))}|ConvertTo-Json -Depth 6 -Compress
"""


@pytest.mark.parametrize('mode', ['none', 'stale', 'nonzero'])
def test_exact_owned_fence_can_release_without_authorizing_admission(tmp_path, mode):
    (tmp_path / ('stop-fence-' + 'd'*32)).mkdir()
    result = inert_ps(FENCE.replace('MODE', mode).replace('PRIVATE', str(tmp_path)))
    assert not result['held'], result
    assert result['writes'] == 1
    assert result['release_exists'] and not result['pending_exists']
    assert result['admission_rejected'] == (mode != 'none')
    assert result['completion'] == dict(status='LOCK_RELEASED', lock_released=True,
                                       native_exit_verified=True, release_requested=True)


@pytest.mark.parametrize('mode', ['foreign_nonce', 'foreign_request', 'foreign_config',
    'foreign_database', 'foreign_task', 'foreign_instance', 'incomplete_handle', 'changed_ready_pin'])
def test_foreign_or_incomplete_fence_never_receives_release(tmp_path, mode):
    (tmp_path / ('stop-fence-' + 'd'*32)).mkdir()
    result = inert_ps(FENCE.replace('MODE', mode).replace('PRIVATE', str(tmp_path)))
    assert result['held'] and result['completion'] is None, result
    assert result['writes'] == 0 and not result['release_exists']
    assert not result['released']


@pytest.mark.parametrize('mode,held', [('terminal_expired', False),
    ('terminal_foreign_pid', True), ('terminal_bad_receipt', True)])
def test_terminal_expiry_never_sends_another_release(tmp_path, mode, held):
    (tmp_path / ('stop-fence-' + 'd'*32)).mkdir()
    result = inert_ps(FENCE.replace('MODE', mode).replace('PRIVATE', str(tmp_path)))
    assert result['held'] == held, result
    assert result['writes'] == 0 and not result['release_exists']
    if not held:
        assert result['completion'] == dict(status='FENCE_EXPIRED', lock_released=True,
                                           native_exit_verified=True, release_requested=False)
    else:
        assert result['completion'] is None


def test_pre_stop_failure_settles_owned_fence_without_restoration_and_sanitizes_frames():
    result = inert_ps(r"""
$state=@{phase=$null;status=$null;rollback=$null;stop_requested=$false;stopped=$false;acceptance_started=$false;
    acceptance_exited=$false;cutover_requested=$false;acceptance=$null;fence=$null}
$script:seen=[Collections.Generic.List[string]]::new();$actions=@{}
foreach($name in @('preconditions','offline_install','codex_preflight')){$actions[$name]={param($s)}}
$actions.admission_fence={param($s)$s.substage='fence_validate_ready';$s.fence=@{completion=$null};throw 'private-secret-C:\private\file'}
$actions.stop_previous={param($s)throw 'Stop must never be reached'}
$actions.restore_previous={param($s)throw 'Restore must never be reached'}
function Release-OpFence {param($f)$script:seen.Add('release');$f.completion=@{status='LOCK_RELEASED'}}
$state=Invoke-OpTransaction $actions $state
$record=New-OpResultRecord $state ([pscustomobject]@{source_commit=('a'*40);request_sha256=('b'*64)}) ('c'*64)
@{record=$record;seen=@($script:seen)}|ConvertTo-Json -Depth 10 -Compress
""")
    assert result['seen'] == ['release']
    record = result['record']
    assert record['rollback'] == 'NOT_REQUIRED'
    assert record['fence_cleanup']['status'] == 'LOCK_RELEASED'
    failure = record['launcher_failure']
    assert failure['error_type'] == 'RuntimeException'
    assert failure['substage'] == 'fence_validate_ready'
    assert failure['frames']
    assert 'private-secret' not in str(record)
    assert r'C:\private' not in str(record)


def test_partial_task_creation_is_evidence_only_and_cannot_release(tmp_path):
    result = inert_ps(r"""
$script:OpPrivate='PRIVATE';$script:OpOldConfig='C:\fixture\old\pipeline.json'
$script:OpManifest=@{previous_config_sha256=('a'*64);request_sha256=('b'*64)}
$script:OpScheduler=$null;$script:OpFolder=$null;$script:writes=0
function Write-OpStatus {param($p,$s,$r,$step)}
function New-OpPrivateDirectory {param($p)$null=[IO.Directory]::CreateDirectory($p)}
function Write-OpRecord {param($p,$r)$script:writes++;[IO.File]::WriteAllText($p,($r|ConvertTo-Json -Compress))}
function New-OpOneShot {param($s,$f,$n,$a,$seconds)throw 'Task Run outcome is uncertain'}
$state=@{fence=$null};$startHeld=$false;$releaseHeld=$false
try{$state.fence=Start-OpFence 'stop-fence' $state 'fence'}catch{$startHeld=$true}
try{Release-OpFence $state.fence}catch{$releaseHeld=$true}
@{start_held=$startHeld;release_held=$releaseHeld;owned=$state.fence.owned;handle=$state.fence.handle;
    writes=$script:writes;files=@([IO.Directory]::EnumerateFiles($script:OpPrivate)|ForEach-Object{[IO.Path]::GetFileName($_)});
    child_files=@([IO.Directory]::EnumerateFileSystemEntries($state.fence.root))}|ConvertTo-Json -Depth 5 -Compress
""".replace('PRIVATE', str(tmp_path)))
    assert result['start_held'] and result['release_held']
    assert not result['owned'] and result['handle'] is None
    assert result['writes'] == 1 and result['child_files'] == []
    assert len(result['files']) == 1 and result['files'][0].startswith('fence-owner-intent-')
