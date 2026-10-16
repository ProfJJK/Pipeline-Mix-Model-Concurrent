"""The ab900e9 owner sitting held in admission_fence (2026-10-16).

Public frames: Assert-OpOneShot line 1023 ('One-shot definition changed.') from
Start-OpFence at substage fence_wait_ready, one second after the one-shot was
created; every owned-stop pass then failed on the same check for its full
60 s bound, so the fence ran on, took the writer and r4 ended. The original
865a29b sitting held at the same boundary with an unrecovered RuntimeException
after its fence reached READY on its own.

New-OpOneShot pinned the raw XML read back from the registration's own COM
object after Enabled/Run; every later check reads a fresh copy of the task.
These fixtures model that Task Scheduler behaviour (the registration object keeps
its snapshot; GetTask returns the stored definition) and drive the real
New-OpOneShot, Start-OpFence and Stop-OpOwnedFenceTask, against both the exact
delivered ab900e9 launcher bytes and the current launcher. Everything is inert.
"""
import base64
import hashlib
import json
import subprocess

import pytest

from pipeline_tests.test_operational_launch_428 import LAUNCH, PS51, ROOT

DELIVERED_COMMIT='ab900e9703fba0a05e7a72324540924cc68f22c4'
DELIVERED_SHA256='d9f24c87b3d1485891e2f1eb49104e78b79928ffd56631d6a24616dab75d0926'   # packaged r428-op-recovery-ab900e9 launcher


def inert_ps_at(source, body):
    """inert_ps against a given launcher file (function definitions only)."""
    script="""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('SOURCE',[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
foreach($node in $ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){. ([scriptblock]::Create($node.Extent.Text))}
$script:OpRecovery=$null
function Get-CimInstance {throw 'Forbidden real CIM'}
function Get-NetTCPConnection {throw 'Forbidden real TCP inspection'}
function Start-Process {throw 'Forbidden child launch'}
function New-Object {throw 'Forbidden COM construction'}
BODY
""".replace('SOURCE', str(source).replace("'", "''")).replace('BODY', body)
    result=subprocess.run([PS51, '-NoProfile', '-NonInteractive', '-EncodedCommand',
        base64.b64encode(script.encode('utf-16-le')).decode()], capture_output=True, timeout=60)
    assert result.returncode==0, result.stderr.decode(errors='replace')
    return json.loads(result.stdout.decode('utf-8-sig'))


@pytest.fixture(scope='module')
def delivered(tmp_path_factory):
    raw=subprocess.run(['git', '-C', str(ROOT), 'show', DELIVERED_COMMIT+':scripts/run_operational_428_launch.ps1'],
        capture_output=True, check=True).stdout
    assert hashlib.sha256(raw).hexdigest()==DELIVERED_SHA256
    path=tmp_path_factory.mktemp('delivered')/'run_operational_428_launch.ps1'
    path.write_bytes(raw)
    return path


# A Task Scheduler model: the registered store is authoritative; the object a
# registration returns keeps the XML/definition snapshot it was created with,
# while GetTask returns the stored task (including Enabled changes).
SCHEDULER=r"""
$script:store=@{};$script:fetches=0
function Get-FixtureXml {param($e)'<Task><Settings><Enabled>'+([string]$e.enabled).ToLowerInvariant()+'</Enabled></Settings><Exec>'+$e.def.Actions.Item(1).Arguments+'</Exec></Task>'}
function New-FixtureTask {param($e,[bool]$registration)
    $t=[pscustomobject]@{E=$e;Registration=$registration;SnapXml=(Get-FixtureXml $e)}
    $t|Add-Member ScriptProperty Xml {if($this.Registration){$this.SnapXml}else{Get-FixtureXml $this.E}}
    $t|Add-Member ScriptProperty Enabled {[bool]$this.E.enabled} {param($v)$this.E.enabled=[bool]$v}
    $t|Add-Member ScriptProperty Definition {if(-not $this.Registration){$this.E.def.Settings.Enabled=$this.E.enabled};$this.E.def}
    $t|Add-Member ScriptProperty State {if($this.E.running){4}elseif($this.E.enabled){3}else{1}}
    $t|Add-Member ScriptProperty LastRunTime {$this.E.lastRun}
    $t|Add-Member ScriptProperty LastTaskResult {$this.E.result}
    $t|Add-Member ScriptMethod GetSecurityDescriptor {param($f)$this.E.sddl}
    $t|Add-Member ScriptMethod GetInstances {param($f)$c=[pscustomobject]@{Count=$this.E.running};$c|Add-Member ScriptMethod Item {param($i)[pscustomobject]@{InstanceGuid='{fence-run}'}};$c}
    $t|Add-Member ScriptMethod Run {param($a)$this.E.running=1;$this.E.lastRun=[DateTime]::UtcNow;$this.E.result=0x41301;[pscustomobject]@{InstanceGuid='{fence-run}'}}
    $t|Add-Member ScriptMethod Stop {param($f)$this.E.running=0;$this.E.result=0x41306}
    return $t
}
$script:OpScheduler=[pscustomobject]@{}
$script:OpScheduler|Add-Member ScriptMethod NewTask {param($f)
    $actions=[pscustomobject]@{L=[Collections.ArrayList]::new()}
    $actions|Add-Member ScriptProperty Count {$this.L.Count}
    $actions|Add-Member ScriptMethod Create {param($t)$a=[pscustomobject]@{Type=$t;Path=$null;Arguments=$null;WorkingDirectory=$null};$null=$this.L.Add($a);$a}
    $actions|Add-Member ScriptMethod Item {param($i)$this.L[$i-1]}
    [pscustomobject]@{Principal=[pscustomobject]@{UserId=$null;LogonType=0;RunLevel=0};Triggers=[pscustomobject]@{Count=0};Actions=$actions;
        Settings=[pscustomobject]@{Enabled=$true;AllowDemandStart=$false;MultipleInstances=0;RestartCount=3;ExecutionTimeLimit='PT72H'}}}
$script:OpFolder=[pscustomobject]@{}
$script:OpFolder|Add-Member ScriptMethod RegisterTaskDefinition {param($n,$d,$flags,$u,$p,$l,$sddl)
    $e=@{def=$d;enabled=[bool]$d.Settings.Enabled;sddl=$sddl;running=0;lastRun=[DateTime]'1899-12-30';result=0x41303}
    $script:store[$n]=$e;return (New-FixtureTask $e $true)}
$script:OpFolder|Add-Member ScriptMethod GetTask {param($n)$script:fetches++;return (New-FixtureTask $script:store[$n] $false)}
function Assert-428TaskAcl {param($t)if($t.GetSecurityDescriptor(7) -cne 'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'){throw 'Unexpected one-shot ACL'}}
$script:OpPrivate='C:\fixture\private';$script:OpRoot='C:\fixture\r5';$script:OpOldConfig='C:\fixture\r4\pipeline.json'
$script:OpManifest=@{previous_config_sha256=('a'*64);request_sha256=('b'*64)}
function New-OpPrivateDirectory {param($p)}
function Write-OpRecord {param($p,$r)}
function Write-OpStatus {param($p,$s,$r,$step)}
"""

START=SCHEDULER+r"""
# READY is published by the fence one poll after it starts.
$script:probes=0
function Test-Path {param($LiteralPath)$script:probes++;return ($script:probes -ge 2)}
function Read-OpFenceReady {param($f)$f.ready=@{ready_at=1}}
function Assert-OpFence {param($f)}
$state=@{phase='admission_fence'};$failure=$null;$ready=$false
try{$f=Start-OpFence 'stop-fence' $state 'fence';$ready=$null -ne $f.ready}catch{$failure=Get-OpFailure $_ (Get-OpProperty $state 'substage')}
@{ready=$ready;failure=$failure;fetches=$script:fetches;sddl_baseline=(Get-OpProperty $state.fence.handle 'sddl')}|ConvertTo-Json -Depth 6 -Compress
"""


def test_delivered_ab900e9_reproduces_the_owner_hold_at_the_first_fence_wait(delivered):
    result=inert_ps_at(delivered, START)
    assert not result['ready'], result
    failure=result['failure']
    assert failure['substage']=='fence_wait_ready' and failure['error_type']=='RuntimeException', result
    assert [f['function'] for f in failure['frames'][:2]]==['Assert-OpOneShot', 'Start-OpFence'], result
    # The very first check of a fresh copy already disagrees with the pinned snapshot.
    assert result['fetches']==1, result


def test_fixed_launcher_passes_the_same_boundary_and_reaches_ready():
    result=inert_ps_at(LAUNCH, START)
    assert result['ready'] and result['failure'] is None, result
    assert result['sddl_baseline']=='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)', result


STOP=SCHEDULER+r"""
# The one-shot was created and run; the launcher then held before READY.
$nonce='c'*32;$root=Join-Path $script:OpPrivate ('stop-fence-'+$nonce)
$argv='-I -B -m cochem_pipeline.owner_admission_fence_428 --nonce '+$nonce
$handle=New-OpOneShot $script:OpScheduler $script:OpFolder ('CoChem-4.2.8-Fence-'+$nonce) $argv 2100
$fence=@{root=$root;nonce=$nonce;arguments=$argv;name=('CoChem-4.2.8-Fence-'+$nonce);owned=$true;handle=$handle;ready=$null;released=$false;completion=$null}
function Get-OpFenceNativeRows {param($f)return}
function Test-Path {param($LiteralPath)return $false}
$status=$null;$held=$false
try{$status=Stop-OpOwnedFenceTask $fence 4}catch{$held=$true}
@{held=$held;status=(Get-OpProperty $status 'status');settled=(Test-OpFenceSettled $fence);running=$script:store[$fence.name].running;
  stop_failure=(Get-OpProperty $fence 'stop_failure')}|ConvertTo-Json -Depth 6 -Compress
"""


def test_delivered_ab900e9_owned_stop_could_never_end_its_own_fence(delivered):
    result=inert_ps_at(delivered, STOP)
    assert result['held'] and not result['settled'] and result['running']==1, result
    assert result['stop_failure']['last_pass']=='EXCEPTION', result
    assert result['stop_failure']['exception']['frames'][0]['function']=='Assert-OpOneShot', result


def test_fixed_launcher_owned_stop_ends_its_own_fence():
    result=inert_ps_at(LAUNCH, STOP)
    assert not result['held'] and result['settled'] and result['running']==0, result
    assert result['status']=='STOPPED_OWNED_FENCE_TASK', result


IDENTITY=SCHEDULER+r"""
$argv='-I -B -m cochem_pipeline.owner_admission_fence_428 --nonce '+('d'*32)
$handle=New-OpOneShot $script:OpScheduler $script:OpFolder 'CoChem-4.2.8-Fence-x' $argv 2100
$null=Assert-OpOneShot $handle $true
$e=$script:store['CoChem-4.2.8-Fence-x']
CHANGE
$message=$null;try{$null=Assert-OpOneShot $handle $true}catch{$message=$_.Exception.Message}
@{message=$message}|ConvertTo-Json -Compress
"""


@pytest.mark.parametrize('change,message', [
    ('', None),
    ('$e.enabled=$false', None),                                   # this sitting toggles Enabled itself
    # Stored-form normalizations of the same registration (repo evidence shows
    # stored one-shots with S-1-5-18 and a minutes-form time limit).
    ("$e.def.Principal.UserId='S-1-5-18'", None),
    ("$e.def.Principal.UserId='NT AUTHORITY\\SYSTEM'", None),
    ("$e.def.Settings.ExecutionTimeLimit='PT35M'", None),
    ("$e.def.Actions.Item(1).Arguments='tampered'", 'One-shot definition changed.'),
    ("$e.def.Actions.Item(1).Path='C:\\other\\python.exe'", 'One-shot definition changed.'),
    ("$e.def.Actions.Item(1).WorkingDirectory='C:\\other'", 'One-shot definition changed.'),
    ("$e.def.Principal.UserId='AETHERDESK\\ansac'", 'One-shot definition changed.'),
    ('$e.def.Principal.RunLevel=0', 'One-shot definition changed.'),
    ('$e.def.Triggers.Count=1', 'One-shot definition changed.'),
    ("$e.def.Settings.ExecutionTimeLimit='PT72H'", 'One-shot definition changed.'),
    ('$e.def.Settings.RestartCount=3', 'One-shot definition changed.'),
    ("$null=$e.def.Actions.Create(0)", 'One-shot definition changed.'),
    ("$e.sddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;AU)'", 'Unexpected one-shot ACL'),
    ("$handle.sddl='O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)'", 'One-shot security descriptor changed.'),
    ('$e.running=0', 'One-shot no longer has exactly one running instance.'),
    ("$handle.instance='{other-run}'", 'One-shot is no longer the exact running instance.'),
])
def test_one_shot_identity_is_structural_and_still_detects_every_tamper(change, message):
    result=inert_ps_at(LAUNCH, IDENTITY.replace('CHANGE', change))
    assert result['message']==message, result


def test_each_definition_group_holds_on_its_own_frame_line():
    # Public evidence carries frames, not messages: each group must be distinct.
    result=inert_ps_at(LAUNCH, SCHEDULER+r"""
$argv='-I -B -m cochem_pipeline.owner_admission_fence_428 --nonce '+('d'*32)
$tampers=[ordered]@{
    triggers={param($d)$d.Triggers.Count=1};actions={param($d)$null=$d.Actions.Create(0)};path={param($d)$d.Actions.Item(1).Path='C:\other\python.exe'}
    arguments={param($d)$d.Actions.Item(1).Arguments='tampered'};workdir={param($d)$d.Actions.Item(1).WorkingDirectory='C:\other'}
    principal={param($d)$d.Principal.RunLevel=0};restart={param($d)$d.Settings.RestartCount=3};instances={param($d)$d.Settings.MultipleInstances=0}
    limit={param($d)$d.Settings.ExecutionTimeLimit='PT72H'}}
$lines=[ordered]@{}
foreach($k in @($tampers.Keys)){
    $h=New-OpOneShot $script:OpScheduler $script:OpFolder ('CoChem-4.2.8-Fence-'+$k) $argv 2100
    & $tampers[$k] $script:store['CoChem-4.2.8-Fence-'+$k].def
    try{$null=Assert-OpOneShot $h $true;$lines[$k]=$null}catch{$f=Get-OpFailure $_ 'x';$lines[$k]=@{function=$f.frames[0].function;line=$f.frames[0].line}}
}
$lines|ConvertTo-Json -Depth 4 -Compress
""")
    assert all(v and v['function']=='Assert-OpOneShotDefinition' for v in result.values()), result
    assert len({v['line'] for v in result.values()})==len(result), result
