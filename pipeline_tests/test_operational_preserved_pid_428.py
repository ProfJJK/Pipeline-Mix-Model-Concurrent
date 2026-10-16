"""Inert PID-reuse and transient-observer fixtures; nothing queries the host.

The 90c9c1d owner sitting held because Windows had recycled the expired stop
fence's PID 46440 for an unrelated cmd.exe. These fixtures drive the real
launcher checks with host-shaped Win32_Process rows (including CreationDate),
the real observer proof and the real extracted recovery actions.
"""
from datetime import datetime, timezone
import hashlib
import json

import pytest

from pipeline_tests.test_operational_fence_cleanup_428 import FENCE
from pipeline_tests.test_operational_launch_428 import inert_ps
from pipeline_tests.test_operational_observer_roles_428 import FIXTURE as OBSERVER_FIXTURE
from pipeline_tests.test_operational_recovery_428 import EVIDENCE, TASK


PYTHON=r'C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe'
R4=r'C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r4'
R5=r'C:\Program Files\CoChem\Pipeline4.2.8-windows-20261015-r5'
R5_VENV=R5+r'\.venv\Scripts\python.exe'
CMD=r'C:\Windows\System32\cmd.exe'
USER_PYTHON=r'C:\Users\ansac\AppData\Local\Programs\Python\Python313\python.exe'
READY_AT=1792089678.349171          # pinned ready.json of the expired fence (EVIDENCE fixture)
WARDEN_STARTED=1792028236.3145344   # r4 heartbeat process_started_at in the pinned baseline
OWNER_RUN='2026-10-16T00:38:03Z'    # 90c9c1d sitting that found PID 46440 occupied
ORIGINAL_FENCE=(f'"{R5_VENV}" -I -B -m cochem_pipeline.owner_admission_fence_428 '
                '--nonce a232264b12984ff2ab9ef33b7ec24c75')
NEW_FENCE_ARGS='-I -B -m cochem_pipeline.owner_admission_fence_428 --nonce ' + 'f'*32


def at(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace('+00:00', 'Z')


def occupant(pid, image, command, created, name=None, parent=4242):
    return dict(pid=pid, image=image, command=command, created=created, parent=parent,
                name=name if name is not None else image.rsplit('\\', 1)[-1])


ROWS=r"""
$list='OCCUPANTS'|ConvertFrom-Json;$script:occupants=[ordered]@{}
foreach($o in $list){
    $row=[pscustomobject]@{ProcessId=[uint32]$o.pid;ParentProcessId=[uint32]$o.parent;Name=$o.name;ExecutablePath=$o.image;CommandLine=$o.command}
    if($o.created){$row|Add-Member NoteProperty CreationDate ([DateTimeOffset]::Parse($o.created).LocalDateTime)}
    $script:occupants[[string]$o.pid]=$row
}
"""

BOUNDS=("@{preserved_pid_created_by=@{'46440'=(ConvertFrom-OpUnixTime READY);'24424'=(ConvertFrom-OpUnixTime WARDEN)}}"
        .replace('READY', repr(READY_AT)).replace('WARDEN', repr(WARDEN_STARTED)))

QUIESCENT=r"""
$script:OpOldRoot='R4';$script:OpRoot='R5';$script:python='PYTHON'
$script:queries=[Collections.Generic.List[string]]::new()
ROWS
function Assert-428PortFree {}
function Assert-ProtectedPath {param($p)}
# Occupants here never exit; count bounded waits instead of sleeping.
$script:waits=0;function Wait-OpProcessesExited {param($r,$s)$script:waits++}
function Get-CimInstance {param($ClassName,$Filter)
    if($ClassName -cne 'Win32_Process'){throw 'Unexpected CIM class'}
    if($Filter){$script:queries.Add($Filter);return $script:occupants[$Filter.Substring(10)]}
    return @($script:occupants.Values)
}
$state=STATE
$fence=FENCE_ARG
$held=$false;$failure=$null
try{Assert-OpRecoveryQuiescent (Get-OpRecoveryExpected) $fence $null $state}catch{$held=$true;$failure=Get-OpFailure $_ 'verify_original_recovery_evidence'}
@{held=$held;failure=$failure;queries=@($script:queries);waits=$script:waits}|ConvertTo-Json -Depth 8 -Compress
"""


def quiescent(occupants, *, bounds=True, fence=None):
    fence_ps='$null' if fence is None else (
        "@{arguments='ARGS';ready=@{pid=PID}}".replace('ARGS', fence['arguments']).replace('PID', str(fence['pid'])))
    return inert_ps(QUIESCENT.replace('ROWS', ROWS).replace('R4', R4).replace('R5', R5).replace('PYTHON', PYTHON)
        .replace('OCCUPANTS', json.dumps(occupants).replace("'", "''"))
        .replace('STATE', BOUNDS if bounds else '$null').replace('FENCE_ARG', fence_ps))


def rejection(result):
    return result['failure']['process_rejection']


# --- Preserved-PID identity ------------------------------------------------

@pytest.mark.parametrize('bounds', [True, False])
def test_owner_hold_unrelated_cmd_on_recycled_fence_pid_is_not_the_original(bounds):
    # Exact 90c9c1d boundary: real expected map, real Assert-OpRecoveryQuiescent.
    result=quiescent([occupant(46440, CMD, 'cmd.exe /c exit 0', OWNER_RUN)], bounds=bounds)
    assert not result['held'], result
    assert result['queries']==['ProcessId=24424', 'ProcessId=46440']


@pytest.mark.parametrize('row', [
    occupant(24424, CMD, 'cmd.exe /d /c ver', OWNER_RUN),
    occupant(46440, '', '', None, name='cmd.exe'),
    occupant(46440, CMD, 'cmd.exe /c exit 0', None),
    occupant(46440, CMD, 'cmd.exe /c exit 0', at(READY_AT - 60)),
])
@pytest.mark.parametrize('bounds', [True, False])
def test_non_python_image_is_never_the_original_without_any_clock(row, bounds):
    result=quiescent([row], bounds=bounds)
    assert not result['held'], result


@pytest.mark.parametrize('pid,image,command,created', [
    (46440, PYTHON, ORIGINAL_FENCE, at(READY_AT - 1)),
    (46440, PYTHON, ORIGINAL_FENCE, at(READY_AT + 119)),
    (46440, R5_VENV, ORIGINAL_FENCE, at(READY_AT - 2)),
    (46440, R5+r'\cochem-pipeline.exe', 'cochem-pipeline.exe daemon', at(READY_AT - 1)),
    (46440, USER_PYTHON, 'python.exe -m pytest -q', at(READY_AT + 30)),
    (24424, PYTHON, 'python -I -B -m cochem_pipeline daemon --config old', at(WARDEN_STARTED - 9)),
    (24424, R4+r'\.venv\Scripts\python.exe', 'python -I -B -m cochem_pipeline daemon', at(WARDEN_STARTED + 60)),
])
def test_possible_original_created_before_pinned_bound_still_holds(pid, image, command, created):
    result=quiescent([occupant(pid, image, command, created)])
    assert result['held'], result
    assert rejection(result)==dict(pid=pid, name=image.rsplit('\\', 1)[-1].lower(),
        reason='PRESERVED_PID_OCCUPIED', command_sha256=hashlib.sha256(command.encode()).hexdigest())


@pytest.mark.parametrize('case', ['no_bounds', 'no_creation_time', 'no_identity', 'uninspectable_no_time'])
def test_ambiguous_occupant_identity_fails_closed(case):
    row=occupant(46440, PYTHON, ORIGINAL_FENCE, OWNER_RUN)
    if case=='no_creation_time':
        row['created']=None
    if case=='no_identity':
        row.update(image='', name='', command='', created=None)
    if case=='uninspectable_no_time':
        row.update(image='', name='python.exe', command='', created=None)
    result=quiescent([row], bounds=case!='no_bounds')
    assert result['held'], result
    assert rejection(result)['reason']=='PRESERVED_PID_OCCUPIED'


@pytest.mark.parametrize('bounds,held', [(True, False), (False, True)])
def test_unrelated_later_python_needs_the_pinned_bound(bounds, held):
    # A user's later pytest interpreter is no pipeline process: the inventory
    # ignores it, so only the creation bound decides the PID gate.
    result=quiescent([occupant(46440, USER_PYTHON, 'python.exe -m pytest -q', OWNER_RUN)], bounds=bounds)
    assert result['held']==held, result
    if held:
        assert rejection(result)['reason']=='PRESERVED_PID_OCCUPIED'


@pytest.mark.parametrize('image,name,reason', [
    (PYTHON, None, 'PROTECTED_PYTHON'),
    ('', 'python.exe', 'UNINSPECTABLE_PYTHON'),
    (R5+r'\cmd.exe', None, 'RUNTIME_IMAGE'),
])
def test_later_process_on_recycled_pid_is_still_judged_by_the_inventory(image, name, reason):
    # Passing the PID-identity gate never whitelists a process.
    command='' if not image else ORIGINAL_FENCE
    result=quiescent([occupant(46440, image, command, OWNER_RUN, name=name)])
    assert result['held'], result
    assert rejection(result)['reason']==reason and rejection(result)['pid']==46440


def test_tolerated_warden_occupant_does_not_mask_a_possible_fence_original():
    result=quiescent([occupant(24424, CMD, 'cmd.exe /c ver', OWNER_RUN),
                      occupant(46440, PYTHON, ORIGINAL_FENCE, at(READY_AT - 1))])
    assert result['held'], result
    assert rejection(result)['pid']==46440 and rejection(result)['reason']=='PRESERVED_PID_OCCUPIED'


@pytest.mark.parametrize('offset,held', [(121, False), (3600, False), (119, True)])
def test_this_sittings_new_fence_child_may_be_assigned_a_recycled_pid(offset, held):
    command=f'"{PYTHON}" {NEW_FENCE_ARGS}'
    result=quiescent([occupant(46440, PYTHON, command, at(READY_AT + offset))],
                     fence=dict(arguments=NEW_FENCE_ARGS, pid=46440))
    assert result['held']==held, result
    if held:
        assert rejection(result)['reason']=='PRESERVED_PID_OCCUPIED'


@pytest.mark.parametrize('ready_pid,held', [(50000, False), (60000, True)])
def test_this_sittings_new_fence_launcher_may_be_assigned_a_recycled_pid(ready_pid, held):
    launcher=occupant(46440, R5_VENV, f'"{R5_VENV}" {NEW_FENCE_ARGS}', OWNER_RUN)
    child=occupant(50000, PYTHON, f'"{PYTHON}" {NEW_FENCE_ARGS}', OWNER_RUN, parent=46440)
    result=quiescent([launcher, child], fence=dict(arguments=NEW_FENCE_ARGS, pid=ready_pid))
    assert result['held']==held, result
    if held:
        assert rejection(result)=={**rejection(result), 'pid': 46440, 'reason': 'PROTECTED_PYTHON'}


@pytest.mark.parametrize('literal,type_name,expected', [
    ('(\'{"t":1792089678.349171}\'|ConvertFrom-Json).t', 'Decimal', at(READY_AT)),
    ('(\'{"t":1792089678}\'|ConvertFrom-Json).t', 'Int32', '2026-10-15T18:41:18Z'),
    ('(\'{"t":1.792089678E9}\'|ConvertFrom-Json).t', None, '2026-10-15T18:41:18Z'),
    ('[double]1792028236.3145344', 'Double', at(WARDEN_STARTED)),
    ('[long]1792089678', 'Int64', '2026-10-15T18:41:18Z'),
    ("'1792089678'", 'String', None),
    ('$true', 'Boolean', None),
    ('[double]12', 'Double', None),
    ('[double]-1792089678', 'Double', None),
    ('[double]::NaN', 'Double', None),
    ('[double]::PositiveInfinity', 'Double', None),
])
def test_pinned_unix_times_parse_from_windows_powershell_json_types(literal, type_name, expected):
    result=inert_ps(r"""
$in=(VALUE);$v=ConvertFrom-OpUnixTime $in
@{type=$in.GetType().Name;value=$(if($null -eq $v){$null}else{@{kind=[string]$v.Kind;iso=$v.ToString('yyyy-MM-ddTHH:mm:ss.ffffff')+'Z'}})}|ConvertTo-Json -Compress
""".replace('VALUE', literal))
    if type_name:
        assert result['type']==type_name, result
    if expected is None:
        assert result['value'] is None, result
    else:
        assert result['value']['kind']=='Utc'
        got=datetime.fromisoformat(result['value']['iso'].replace('Z', '+00:00'))
        want=datetime.fromisoformat(expected.replace('Z', '+00:00'))
        assert abs((got-want).total_seconds())<0.001, result


def test_null_pinned_unix_time_is_no_bound():
    result=inert_ps(r"""@{none=($null -eq (ConvertFrom-OpUnixTime $null))}|ConvertTo-Json -Compress""")
    assert result==dict(none=True)


# --- Real preconditions and recovery actions -------------------------------

STUB="function Assert-OpRecoveryQuiescent {param($r)$script:seen.Add('quiescent')}\n"
HEALTH='health=@{pid=$r.warden.pid}'
REAL_HASH=r"""
# EVIDENCE maps only the baseline texts; rejection identities need real hashes.
function Get-OpTextSha256 {param($t)
    if($t -ceq 'baseline-xml'){return $script:recovery.warden.task_xml_sha256};if($t -ceq 'baseline-sddl'){return $script:recovery.warden.task_sddl_sha256}
    $h=[Security.Cryptography.SHA256]::Create()
    try{return [BitConverter]::ToString($h.ComputeHash([Text.UTF8Encoding]::new($false).GetBytes([string]$t))).Replace('-','').ToLowerInvariant()}finally{$h.Dispose()}
}
"""


def evidence_chain(occupants):
    # The real Assert-OpRecoveryQuiescent is reached from Assert-OpRecoveryEvidence
    # through the pinned-record fixture, exactly as at the owner's frame 486.
    assert EVIDENCE.count(STUB)==1 and EVIDENCE.count(HEALTH)==1
    body=EVIDENCE.replace('FAULT', 'none').replace(STUB, '').replace(
        HEALTH, 'health=@{pid=$r.warden.pid;process_started_at=' + repr(WARDEN_STARTED) + '}')
    return inert_ps((body + ROWS + REAL_HASH + r"""
$script:python='PYTHON'
function Assert-428PortFree {$script:seen.Add('port-free')}
function Get-CimInstance {param($ClassName,$Filter)if($Filter){return $script:occupants[$Filter.Substring(10)]};return @($script:occupants.Values)}
$held=$false;$failure=$null
try{Assert-OpRecoveryEvidence $script:recovery $m $inventory $pins $state}catch{$held=$true;$failure=Get-OpFailure $_ 'verify_original_recovery_evidence'}
$bounds=@{};$b=Get-OpProperty $state 'preserved_pid_created_by'
if($null -ne $b){foreach($k in $b.Keys){$bounds[$k]=$(if($null -eq $b[$k]){$null}else{$b[$k].ToString('yyyy-MM-ddTHH:mm:ss.ffffff')+'Z'})}}
@{held=$held;failure=$failure;verified=$state.verified_stopped_at_entry;seen=@($script:seen);pins=$pins.Count;bounds=$bounds}|ConvertTo-Json -Depth 8 -Compress
""").replace('PYTHON', PYTHON).replace('OCCUPANTS', json.dumps(occupants).replace("'", "''")))


@pytest.mark.parametrize('row', [
    occupant(46440, CMD, 'cmd.exe /c exit 0', OWNER_RUN),
    occupant(46440, USER_PYTHON, 'python.exe -m pytest -q', OWNER_RUN),
    occupant(24424, USER_PYTHON, 'python.exe -m pytest -q', OWNER_RUN),
])
def test_evidence_chain_binds_pinned_json_bounds_before_the_real_pid_gate(row):
    result=evidence_chain([row])
    assert not result['held'], result
    assert result['verified'] and result['pins']==8
    assert {'port-free', 'installed-payload', 'new-baseline'}<=set(result['seen'])
    assert set(result['bounds'])=={'46440', '24424'}
    for key, seconds in (('46440', READY_AT), ('24424', WARDEN_STARTED)):
        got=datetime.fromisoformat(result['bounds'][key].replace('Z', '+00:00'))
        assert abs(got.timestamp()-seconds)<0.001, result


@pytest.mark.parametrize('row', [
    occupant(46440, PYTHON, ORIGINAL_FENCE, at(READY_AT - 1)),
    occupant(46440, USER_PYTHON, 'python.exe -m pytest -q', at(READY_AT - 1)),
    occupant(24424, USER_PYTHON, 'python.exe -m pytest -q', at(WARDEN_STARTED + 60)),
])
def test_evidence_chain_still_holds_a_possible_surviving_original(row):
    result=evidence_chain([row])
    assert result['held'] and not result['verified'], result
    assert rejection(result)['reason']=='PRESERVED_PID_OCCUPIED' and rejection(result)['pid']==row['pid']
    functions=[frame['function'] for frame in result['failure']['frames']]
    assert functions[:2]==['Assert-OpRecoveryQuiescent', 'Assert-OpRecoveryEvidence'], functions
    assert 'installed-payload' not in result['seen'] and 'new-baseline' not in result['seen']


ACTIONS=r"""
$script:OpRecovery=$script:recovery;$script:OpPrivate='C:\fixture\fresh';$script:OpOldRoot='C:\fixture\old';$script:OpRoot='C:\fixture\new'
$script:python='PYTHON';$script:OpOldArgs='exact-args';$script:OpOriginalXml='exact-xml';$script:OpOriginalSddl='exact-sddl';$script:targetRoot='C:\fixture\new'
$script:OpFolder=[pscustomobject]@{};$script:seen=[Collections.Generic.List[string]]::new();$script:queries=[Collections.Generic.List[string]]::new()
$script:OpFolder|Add-Member ScriptMethod GetTask {param($n)$script:task}
$script:OpFolder|Add-Member ScriptMethod RegisterTaskDefinition {param($n,$d,$f,$u,$p,$l,$s)$script:seen.Add('disable-trigger')}
$script:task|Add-Member ScriptMethod Stop {param($f)throw 'Forbidden Stop'}
$script:task|Add-Member ScriptMethod Run {param($f)throw 'Forbidden Run'}
function Write-OpStatus {param($p,$s,$r,$step)}
function Invoke-428Native {throw 'Forbidden installer/native launch'}
function Get-428Health {throw 'Forbidden old health'}
function Get-Item {param($LiteralPath)[pscustomobject]@{Length=42}}
function Copy-VerifiedPayload {param($r)$script:seen.Add('copy-request')}
function Start-OpFence {param($l,$s,$k)
    $script:seen.Add('fresh-fence')
    $f=@{arguments='NEW_ARGS';ready=@{pid=46440;expires_at=EXPIRES;catalog=@{active_policy_sha256='policy';active_catalog_sha256=$null}}}
    $s[$k]=$f;return $f
}
function Assert-OpFence {param($f)$script:seen.Add('fence-proof')}
function Assert-428WardenTask {param($t,$x,$s,$r,$a,$e,$tr,$count)if($t.Enabled -ne $e){throw 'Unexpected enable state'}}
function Assert-428PortFree {$script:seen.Add('port-free')}
function Assert-ProtectedPath {param($p)}
# Real Assert-OpRecoveryRuntimeDependencies over the pinned bootstrap's key layout.
$script:bootstrap='{"ramdisk":{"mount_root":"R:\\","workspace_subdirectory":"CoChem427-windows-20261007"},"docker":{"endpoint":"npipe:////./pipe/dockerDesktopLinuxEngine"}}'
$script:noWorkspace=$false;$script:noPipe=$false
function Open-428Pin {param($p,$h)
    if($p -cne 'C:\fixture\package\pipeline.json' -or $h -cne ('b'*64)){throw 'Unexpected bootstrap pin'}
    $script:seen.Add('bootstrap-pin');return [IO.MemoryStream]::new([Text.UTF8Encoding]::new($false).GetBytes($script:bootstrap))
}
function Read-428Json {param($s)$r=[IO.StreamReader]::new($s);try{return ($r.ReadToEnd()|ConvertFrom-Json)}finally{$r.Dispose()}}
function Test-Path {param($LiteralPath,$PathType)return ($LiteralPath -ceq 'R:\CoChem427-windows-20261007' -and $PathType -eq 'Container' -and -not $script:noWorkspace)}
function Get-OpNamedPipes {if($script:noPipe){return @('\\.\pipe\other')};return @('\\.\pipe\other','\\.\pipe\dockerDesktopLinuxEngine')}
ACTION_CHANGE
ROWS
$script:byStage=@{admission=$script:occupants['1'];before=$script:occupants['2'];after=$script:occupants['3']}
function Get-CimInstance {param($ClassName,$Filter)
    $stage=if($script:seen.Contains('disable-trigger')){'after'}elseif($script:seen.Contains('fresh-fence')){'before'}else{'admission'}
    $occ=$script:byStage[$stage]
    if($Filter){$script:queries.Add($stage+':'+$Filter);if($null -ne $occ -and $Filter -ceq ('ProcessId='+$occ.ProcessId)){return $occ};return $null}
    if($null -eq $occ){return @()};return @($occ)
}
$m=@{request_sha256=('a'*64);bootstrap_sha256=('b'*64)};$Directory='C:\fixture\package';$pins=[Collections.Generic.List[IO.Stream]]::new()
$state=@{phase='fixture';stopped=$false;old_task_last_run=$when.ToUniversalTime();recovery_catalog=@{active_policy_sha256='policy';active_catalog_sha256=$null};
    preserved_pid_created_by=@{'46440'=(ConvertFrom-OpUnixTime READY);'24424'=(ConvertFrom-OpUnixTime WARDEN)}}
$held=$false;$failure=$null
try{foreach($name in @('offline_install','admission_fence','stop_previous')){
    $nodes=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -ceq ('$actions.'+$name)},$true))
    $text=$nodes[0].Right.Extent.Text.Trim();$action=[scriptblock]::Create($text.Substring(1,$text.Length-2));& $action $state
}}catch{$held=$true;$failure=Get-OpFailure $_ 'fixture'}
@{held=$held;failure=$failure;stopped=$state.stopped;enabled=$script:task.Enabled;seen=@($script:seen);queries=@($script:queries)}|ConvertTo-Json -Depth 8 -Compress
"""


FRESH_EXPIRY='([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0+240)'


def actions(after, *, change='', expires=FRESH_EXPIRY):
    # Keys 1/2/3 are the 46440 occupants at admission_fence, before and after
    # the Warden trigger disable in stop_previous.
    new_fence=occupant(46440, PYTHON, f'"{PYTHON}" {NEW_FENCE_ARGS}', OWNER_RUN)
    rows=[dict(occupant(46440, CMD, 'cmd.exe /c exit 0', OWNER_RUN), key=1),
          dict(new_fence, key=2), dict(after, key=3)]
    rows=[{**r, 'pid': r.pop('key'), 'real_pid': r['pid']} for r in rows]
    body=(TASK+ACTIONS).replace('ROWS', ROWS.replace('[uint32]$o.pid', '[uint32]$o.real_pid'))
    return inert_ps(body.replace('ACTION_CHANGE', change).replace('EXPIRES', expires)
        .replace('PYTHON', PYTHON).replace('NEW_ARGS', NEW_FENCE_ARGS)
        .replace('READY', repr(READY_AT)).replace('WARDEN', repr(WARDEN_STARTED))
        .replace('OCCUPANTS', json.dumps(rows).replace("'", "''")))


def test_real_recovery_actions_tolerate_recycled_pids_across_every_recheck():
    result=actions(occupant(46440, PYTHON, f'"{PYTHON}" {NEW_FENCE_ARGS}', OWNER_RUN))
    assert not result['held'], result
    assert result['stopped'] and not result['enabled']
    assert result['seen'].count('disable-trigger')==1 and result['seen'].count('fresh-fence')==1
    assert result['seen'].index('bootstrap-pin')<result['seen'].index('fresh-fence')
    assert result['queries']==[f'{stage}:ProcessId={pid}' for stage in ('admission', 'before', 'after')
                               for pid in (24424, 46440)]


@pytest.mark.parametrize('change,function', [
    ('$script:noPipe=$true', 'Assert-OpRecoveryRuntimeDependencies'),
    ('$script:noWorkspace=$true', 'Assert-OpRecoveryRuntimeDependencies'),
    ("$script:bootstrap='{\"ramdisk\":{\"mount_root\":\"R:\\\\\",\"workspace_subdirectory\":\"CoChem427-windows-20261007\"},\"docker\":{\"endpoint\":\"tcp://127.0.0.1:2375\"}}'",
     'Assert-OpRecoveryRuntimeDependencies'),
])
def test_missing_runtime_dependency_holds_before_any_fence_or_task_change(change, function):
    result=actions(occupant(46440, CMD, 'cmd.exe /c exit 0', OWNER_RUN), change=change)
    assert result['held'] and not result['stopped'] and result['enabled'], result
    assert 'fresh-fence' not in result['seen'] and 'disable-trigger' not in result['seen']
    assert result['failure']['frames'][0]['function']==function, result


@pytest.mark.parametrize('seconds,held', [(185, True), (200, False)])
def test_trigger_disable_requires_fence_time_for_the_post_disable_recheck(seconds, held):
    expires=f'([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0+{seconds})'
    result=actions(occupant(46440, PYTHON, f'"{PYTHON}" {NEW_FENCE_ARGS}', OWNER_RUN), expires=expires)
    assert result['held']==held, result
    assert result['seen'].count('disable-trigger')==(0 if held else 1)
    if held:
        assert not result['stopped'] and result['enabled']


def test_real_recovery_actions_still_hold_a_possible_original_after_trigger_disable():
    result=actions(occupant(46440, PYTHON, ORIGINAL_FENCE, at(READY_AT - 1)))
    assert result['held'] and not result['stopped'] and result['enabled'], result
    assert rejection(result)['reason']=='PRESERVED_PID_OCCUPIED'
    assert result['seen'].count('disable-trigger')==1


# --- Held-observer sterile detector ----------------------------------------

DETECTOR=r"""
# Host Win32_Process rows carry UInt32 identities and a CreationDate.
foreach($r in $script:rows){$r.ProcessId=[uint32]$r.ProcessId;$r.ParentProcessId=[uint32]$r.ParentProcessId}
$script:rows[0]|Add-Member NoteProperty CreationDate $script:start.ToLocalTime()
$script:rows[1]|Add-Member NoteProperty CreationDate $script:start.ToLocalTime().AddSeconds(-2)
$bootstrap=Join-Path $e.root '..\Supervisor4.2.7-windows-20261007-staging-v1\.venv\Lib\site-packages\cochem_supervisor\detector_bootstrap.py'
$t0=$script:start.ToLocalTime().AddHours(1)
function Row($id,$parent,$image,$command,$created){[pscustomobject]@{ProcessId=[uint32]$id;ParentProcessId=[uint32]$parent;Name=[IO.Path]::GetFileName($image);ExecutablePath=$image;CommandLine=$command;CreationDate=$created}}
$script:detector=@(
 (Row 41092 9612 $e.python ('"'+$e.python+'" -I -S "'+$bootstrap+'"') $t0),
 (Row 42560 41092 'C:\Windows\System32\conhost.exe' '\??\C:\Windows\system32\conhost.exe 0x4' $t0.AddMilliseconds(20)),
 (Row 35164 41092 $script:python ('"'+$script:python+'" -I -S "'+$bootstrap+'"') $t0.AddMilliseconds(50)))
$script:extra=@();$script:extraFrom=1;$script:snapshots=0;$script:detectorSnapshots=1;$script:waits=0;$script:onSnapshot={}
CHANGE
function Get-CimInstance {param($class,$filter)
 if($filter){
  $id=[int]$filter.Substring(10)
  if($script:snapshots -lt $script:detectorSnapshots){$hit=@($script:detector+$script:extra|Where-Object{[int]$_.ProcessId -eq $id});if($hit.Count){return $hit[0]}}
  return $null
 }
 $script:snapshots++;& $script:onSnapshot
 $extra=if($script:snapshots -ge $script:extraFrom){@($script:extra)}else{@()}
 if($script:snapshots -le $script:detectorSnapshots){return @($script:rows)+@($script:detector)+$extra}
 return @($script:rows)+$extra
}
"""


def detector_fixture(change=''):
    return inert_ps(OBSERVER_FIXTURE+DETECTOR.replace('CHANGE', change)+r'''
$held=$false;$failure=$null
try{Assert-OpRecoveryQuiescent (Get-OpRecoveryExpected) $null $pins $state}catch{$held=$true;$failure=Get-OpFailure $_ 'recovery_quiescence'}
$count=if($state.ContainsKey('observer_processes')){$state.observer_processes.Count}else{0}
@{held=$held;failure=$failure;snapshots=$script:snapshots;waits=$script:waits;handles=$count;tasks=$script:taskChecks}|ConvertTo-Json -Depth 10 -Compress
if($state.ContainsKey('observer_processes')){foreach($p in $state.observer_processes){$p.Dispose()}};$script:own.Dispose()
''')


def test_observer_detector_is_waited_out_then_a_complete_clean_inventory_is_required():
    result=detector_fixture()
    assert not result['held'], result
    assert result['snapshots']==2 and result['handles']==4 and result['tasks']==4


def test_persistent_observer_descendants_hold_after_bounded_reinventories():
    result=detector_fixture(r"$script:detectorSnapshots=99;function Wait-OpProcessesExited {param($rows,$seconds)$script:waits++;if($seconds -ne 8){throw 'bound'}}")
    assert result['held'], result
    assert result['waits']==5 and result['snapshots']==6
    assert rejection(result)['pid']==41092 and rejection(result)['reason']=='PROTECTED_PYTHON'


DAEMON="'python -I -B -m cochem_pipeline daemon --config x'"


@pytest.mark.parametrize('change,pid', [
    ("$script:detector[0].ParentProcessId=[uint32]9999", 41092),
    ("$script:detector[0].CreationDate=$script:start.ToLocalTime().AddSeconds(-10)", 41092),
    ("$script:detector=@($script:detector[2])", 35164),
    ("$script:detector[2].CreationDate=$t0.AddSeconds(-1)", 35164),
    ("$script:detector+=(Row 777 35164 $script:python 'x' $t0.AddSeconds(1))", 777),
    ("$script:extra=@(Row 888 4 $script:python " + DAEMON + " $t0)", 888),
    # Depth-2 order: an intermediate whose recorded parent is a stale 9612.
    ("$script:detector=@((Row 500 9612 'C:\\Windows\\System32\\cmd.exe' 'cmd /c x' $script:start.ToLocalTime().AddSeconds(-10)),(Row 501 500 $script:python " + DAEMON + " $t0))", 501),
    # The root is the observer child only, never its launcher parent 3132.
    ("$script:extra=@(Row 889 3132 $script:python " + DAEMON + " $t0)", 889),
    # Unreadable creation times break the ancestry proof.
    ("$script:detector[0]=$script:detector[0]|Select-Object * -ExcludeProperty CreationDate", 41092),
    ("$script:detector[2]=$script:detector[2]|Select-Object * -ExcludeProperty CreationDate", 35164),
    ("$script:rows[0]=$script:rows[0]|Select-Object * -ExcludeProperty CreationDate", 41092),
])
def test_only_proven_observer_descendants_are_waited_for(change, pid):
    result=detector_fixture(change+r";function Wait-OpProcessesExited {param($rows,$seconds)$script:waits++}")
    assert result['held'], result
    assert result['waits']==0 and result['snapshots']==1
    assert rejection(result)['pid']==pid


@pytest.mark.parametrize('change,pid,reason', [
    # A pipeline daemon that appears during the wait is judged in the new inventory.
    ("$script:extra=@(Row 888 4 $script:python " + DAEMON + " $t0);$script:extraFrom=2", 888, 'PROTECTED_PYTHON'),
    # Ancestry is proven again in every inventory, not carried over.
    ("$script:detectorSnapshots=2;$script:onSnapshot={if($script:snapshots -eq 2){$script:detector[0].ParentProcessId=[uint32]4}}", 41092, 'PROTECTED_PYTHON'),
])
def test_each_reinventory_is_complete_and_judged_again(change, pid, reason):
    result=detector_fixture(change+r";function Wait-OpProcessesExited {param($rows,$seconds)$script:waits++}")
    assert result['held'], result
    assert result['waits']==1 and result['snapshots']==2
    assert rejection(result)['pid']==pid and rejection(result)['reason']==reason


UNREADABLE=r"""
$script:OpOldRoot='R4';$script:OpRoot='R5';$script:python='PYTHON'
$script:snapshots=0;$script:waits=0;$script:ports=0;$script:liveUntil=1
$script:row=[pscustomobject]@{ProcessId=[uint32]70000;ParentProcessId=[uint32]4242;Name='NAME';ExecutablePath='IMAGE';CommandLine='COMMAND';CreationDate=[DateTime]::Now}
function Assert-428PortFree {$script:ports++}
function Assert-ProtectedPath {param($p)}
function Get-CimInstance {param($ClassName,$Filter)
    if($Filter){if($Filter -ceq 'ProcessId=70000' -and $script:snapshots -lt $script:liveUntil){return $script:row};return $null}
    $script:snapshots++;if($script:snapshots -le $script:liveUntil){return @($script:row)};return @()
}
CHANGE
$held=$false;$failure=$null
try{Assert-OpRecoveryQuiescent (Get-OpRecoveryExpected) $null $null @{} NOTAFTER}catch{$held=$true;$failure=Get-OpFailure $_ 'verify_original_recovery_evidence'}
@{held=$held;failure=$failure;snapshots=$script:snapshots;waits=$script:waits;ports=$script:ports}|ConvertTo-Json -Depth 8 -Compress
"""
HOOK=dict(name='py.exe', image='', command='')                      # exiting guard-hook launcher
MCP_EXITING=dict(name='python.exe', image=PYTHON, command='')        # exiting MCP base, command gone
READABLE_DAEMON=dict(name='python.exe', image=PYTHON, command='python -I -B -m cochem_pipeline daemon --config x')


def unreadable(row, *, change='', not_after='$null'):
    return inert_ps(UNREADABLE.replace('R4', R4).replace('R5', R5).replace('PYTHON', PYTHON)
        .replace('NAME', row['name']).replace('IMAGE', row['image']).replace('COMMAND', row['command'])
        .replace('CHANGE', change).replace('NOTAFTER', not_after))


@pytest.mark.parametrize('row', [HOOK, MCP_EXITING])
def test_unreadable_exiting_row_is_waited_out_then_a_clean_inventory_is_required(row):
    result=unreadable(row)
    assert not result['held'], result
    assert result['snapshots']==2 and result['ports']==2


@pytest.mark.parametrize('row,reason', [(HOOK, 'UNINSPECTABLE_PYTHON'), (MCP_EXITING, 'PROTECTED_PYTHON')])
def test_persistent_unreadable_row_still_holds_after_the_bound(row, reason):
    result=unreadable(row, change=r"$script:liveUntil=99;function Wait-OpProcessesExited {param($r,$s)$script:waits++}")
    assert result['held'], result
    assert result['waits']==5 and result['snapshots']==6
    assert rejection(result)['reason']==reason and rejection(result)['pid']==70000


def test_readable_pipeline_row_is_rejected_at_once():
    result=unreadable(READABLE_DAEMON, change=r"$script:liveUntil=99;function Wait-OpProcessesExited {param($r,$s)$script:waits++}")
    assert result['held'] and result['waits']==0 and result['snapshots']==1, result
    assert rejection(result)['reason']=='PROTECTED_PYTHON'


def test_caller_deadline_stops_further_waits():
    result=unreadable(HOOK, change=r"$script:liveUntil=99;function Wait-OpProcessesExited {param($r,$s)$script:waits++}",
                      not_after='([DateTime]::UtcNow.AddSeconds(5))')
    assert result['held'] and result['waits']==0 and result['snapshots']==1, result
    assert rejection(result)['reason']=='UNINSPECTABLE_PYTHON'


DEPENDENCIES=r"""
$script:bootstrap='JSON';$script:asked=$null
function Open-428Pin {param($p,$h)if($h -cne ('b'*64)){throw 'Pinned bootstrap mismatch'};return [IO.MemoryStream]::new([Text.UTF8Encoding]::new($false).GetBytes($script:bootstrap))}
function Read-428Json {param($s)$r=[IO.StreamReader]::new($s);try{return ($r.ReadToEnd()|ConvertFrom-Json)}finally{$r.Dispose()}}
function Test-Path {param($LiteralPath,$PathType)$script:asked=$LiteralPath;return ($LiteralPath -ceq 'WORKSPACE' -and $PathType -eq 'Container')}
$script:listingThrows=THROWS
function Get-OpNamedPipes {if($script:listingThrows){throw [ArgumentException]::new('Illegal characters in path.')};return @(PIPES)}
$script:probed=$null;function Test-OpNamedPipePath {param($p)$script:probed=$p;return PROBE}
$held=$false;$message=$null;$type=$null
try{Assert-OpRecoveryRuntimeDependencies 'C:\fixture\package\pipeline.json' 'HASH'}catch{$held=$true;$message=$_.Exception.Message;$type=$_.Exception.GetType().Name}
@{held=$held;message=$message;type=$type;asked=$script:asked;probed=$script:probed}|ConvertTo-Json -Compress
"""
BOOT=dict(ramdisk=dict(mount_root='R:\\', workspace_subdirectory='CoChem427-windows-20261007'),
          docker=dict(endpoint='npipe:////./pipe/dockerDesktopLinuxEngine'))
ENGINE_PIPE=r"'\\.\pipe\other','\\.\pipe\dockerDesktopLinuxEngine'"


@pytest.mark.parametrize('case,held', [
    ('present', False), ('no_workspace', True), ('unmounted_drive', True), ('no_pipe', True), ('tcp_endpoint', True),
    ('no_ramdisk_key', True), ('pin_mismatch', True), ('listing_throws_present', False), ('listing_throws_absent', True),
])
def test_runtime_dependencies_are_read_from_the_pinned_bootstrap(case, held):
    boot=json.loads(json.dumps(BOOT));workspace=r'R:\CoChem427-windows-20261007';pipes=ENGINE_PIPE;pin='b'*64;probe='$false'
    if case=='no_workspace': workspace=r'R:\elsewhere'
    if case=='unmounted_drive': boot['ramdisk']['mount_root']='Q:\\'   # no such drive on any test host
    if case=='no_pipe': pipes=r"'\\.\pipe\other'"
    if case=='tcp_endpoint': boot['docker']['endpoint']='tcp://127.0.0.1:2375'
    if case=='no_ramdisk_key': del boot['ramdisk']
    if case=='pin_mismatch': pin='c'*64
    throws='$false'
    if case.startswith('listing_throws'): throws='$true';probe='$true' if case.endswith('present') else '$false'
    result=inert_ps(DEPENDENCIES.replace('JSON', json.dumps(boot).replace("'", "''")).replace('WORKSPACE', workspace)
        .replace('PIPES', pipes).replace('THROWS', throws).replace('PROBE', probe).replace('HASH', pin))
    assert result['held']==held, result
    if case in ('present', 'listing_throws_present'):
        assert result['asked']==r'R:\CoChem427-windows-20261007'
    if case.startswith('listing_throws'):
        assert result['probed']==r'\\.\pipe\dockerDesktopLinuxEngine', result
    if case=='unmounted_drive':
        # A missing drive is a clean, described hold, not a provider exception.
        assert result['asked']==r'Q:\CoChem427-windows-20261007' and result['type']=='RuntimeException', result
        assert 'RAM-disk workspace' in result['message']


def test_every_health_wait_allows_the_daemons_docker_wait():
    # Both Wait-OpHealth callers start a Warden with --docker-wait-seconds 900.
    result=inert_ps(r"""
$calls=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -ceq 'Wait-OpHealth'},$true))
$args900=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Get-OpDaemonArguments'},$true))[0].Extent.Text
@{calls=@($calls|ForEach-Object{@($_.CommandElements|Select-Object -Skip 1|ForEach-Object{$_.Extent.Text}) -join ' '});docker_wait=($args900 -match '--docker-wait-seconds 900')}|ConvertTo-Json -Compress
""")
    assert result['docker_wait'], result
    assert sorted(result['calls'])==sorted(['$script:OpOldRoot $false 1200', '$script:OpRoot $true 1200']), result


def test_health_wait_bound_is_enforced():
    result=inert_ps(r"""
function Get-428Health {throw 'no listener'}
$watch=[Diagnostics.Stopwatch]::StartNew();$held=$false
try{$null=Wait-OpHealth 'C:\fixture\new' $true 1}catch{$held=$true}
@{held=$held;elapsed=$watch.Elapsed.TotalSeconds}|ConvertTo-Json -Compress
""")
    assert result['held'] and result['elapsed']<6, result


def test_wait_for_exit_binds_pid_to_creation_time_and_is_bounded():
    result=inert_ps(r"""
$t=[DateTime]::Now.AddMinutes(-1)
$rows=@([pscustomobject]@{ProcessId=1;CreationDate=$t},[pscustomobject]@{ProcessId=2;CreationDate=$t},[pscustomobject]@{ProcessId=3;CreationDate=$t})
$script:polls=@{1=0;2=0;3=0}
function Get-CimInstance {param($ClassName,$Filter)$id=[int]$Filter.Substring(10);$script:polls[$id]++
 switch($id){1{return $null}2{return [pscustomobject]@{ProcessId=2;CreationDate=$t.AddSeconds(5)}}3{return [pscustomobject]@{ProcessId=3;CreationDate=$t}}}}
$watch=[Diagnostics.Stopwatch]::StartNew();Wait-OpProcessesExited $rows 1;$watch.Stop()
@{elapsed=$watch.Elapsed.TotalSeconds;gone=$script:polls[1];reused=$script:polls[2];persistent=$script:polls[3]}|ConvertTo-Json -Compress
""")
    assert result['gone']==1 and result['reused']==1, result
    assert result['persistent']>=5 and 0.9<=result['elapsed']<5, result


# --- Release-OpFence without a retained handle ------------------------------

RELEASE_CIM="""function Get-CimInstance {
    param($class,$filter)
    if($script:mode -eq 'terminal_foreign_pid'){return [pscustomobject]@{ProcessId=123}}
    return $null
}"""
RELEASE_READ='function Read-428Json {param($s)return $script:ready}'


@pytest.mark.parametrize('mode,held', [
    ('terminal_reused_cmd', False),
    ('terminal_reused_cmd_early', False),
    ('terminal_reused_python', False),
    ('terminal_python_121', False),
    ('terminal_python_119', True),
    ('terminal_possible_original', True),
    ('terminal_nonce_command', True),
    ('terminal_python_no_command', True),
    ('terminal_foreign_pid', True),
    ('terminal_reused_cmd_no_command', False),
    ('terminal_other_fence', False),
])
def test_terminal_fence_release_binds_native_exit_to_identity_not_pid(tmp_path, mode, held):
    (tmp_path / ('stop-fence-' + 'd'*32)).mkdir()
    assert FENCE.count(RELEASE_CIM)==1 and FENCE.count(RELEASE_READ)==1
    # The launcher sets these roots before any fence exists. Readiness passes
    # through real JSON parsing, so ready_at arrives as a PS 5.1 decimal.
    cim=r"""$script:OpOldRoot='R4';$script:OpRoot='R5';$script:python='PYTHON'
$script:ready.ready_at=[double]$script:ready.ready_at+0.349171;$script:ready.expires_at=[double]$script:ready.expires_at+0.349171
function Get-CimInstance {
    param($class,$filter)
    if($filter -cne 'ProcessId=123'){throw 'Unexpected filter'}
    $readyAt=[DateTime]::new(1970,1,1,0,0,0,[DateTimeKind]::Utc).AddSeconds([double]$script:ready.ready_at).ToLocalTime()
    $created=[DateTime]::Now;$image='PYTHON';$command='fixture'
    switch($script:mode){
        'terminal_foreign_pid' {return [pscustomobject]@{ProcessId=123}}
        'terminal_reused_cmd' {$image='CMD'}
        'terminal_reused_cmd_early' {$image='CMD';$created=$readyAt.AddSeconds(-30)}
        'terminal_python_121' {$created=$readyAt.AddSeconds(121)}
        'terminal_python_119' {$created=$readyAt.AddSeconds(119)}
        'terminal_possible_original' {$created=$readyAt}
        'terminal_nonce_command' {$command='"PYTHON" -I -B -m cochem_pipeline.owner_admission_fence_428 --nonce '+$nonce}
        'terminal_python_no_command' {$command=''}
        'terminal_reused_cmd_no_command' {$image='CMD';$command=''}
        'terminal_other_fence' {$created=$readyAt.AddSeconds(300);$command='"PYTHON" -I -B -m cochem_pipeline.owner_admission_fence_428 --nonce '+('e'*32)}
    }
    return [pscustomobject]@{ProcessId=[uint32]123;Name=[IO.Path]::GetFileName($image);ExecutablePath=$image;CommandLine=$command;CreationDate=$created}
}
function Read-428Json {param($s)return ($script:ready|ConvertTo-Json -Depth 5|ConvertFrom-Json)}""".replace('R4', R4).replace('R5', R5).replace('PYTHON', PYTHON).replace('CMD', CMD)
    result=inert_ps(FENCE.replace(RELEASE_CIM, cim).replace(RELEASE_READ, '').replace('MODE', mode).replace('PRIVATE', str(tmp_path)))
    assert result['held']==held, result
    assert result['writes']==0 and not result['release_exists']
    if held:
        assert result['completion'] is None
        assert result['failure']['frames'][0]['function']=='Release-OpFence', result
    else:
        assert result['completion']==dict(status='FENCE_EXPIRED', lock_released=True,
                                          native_exit_verified=True, release_requested=False)
