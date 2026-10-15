"""Inert PowerShell functions and offline temp-file preparation, never Apply."""
import base64
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
LAUNCH=ROOT/'scripts/run_operational_428_launch.ps1'
PS51=r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
spec=importlib.util.spec_from_file_location('operational_launch',ROOT/'scripts/prepare_operational_launch_428.py')
prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)


def inert_ps(body):
    source="""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('SOURCE',[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
foreach($node in $ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){. ([scriptblock]::Create($node.Extent.Text))}
function Get-CimInstance {throw 'Forbidden real CIM'}
function Get-NetTCPConnection {throw 'Forbidden real TCP inspection'}
function Start-Process {throw 'Forbidden child launch'}
function New-Object {throw 'Forbidden COM construction'}
BODY
""".replace('SOURCE',str(LAUNCH).replace("'","''")).replace('BODY',body)
    result=subprocess.run([PS51,'-NoProfile','-NonInteractive','-EncodedCommand',
        base64.b64encode(source.encode('utf-16-le')).decode()],capture_output=True,timeout=25)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    return json.loads(result.stdout.decode('utf-8-sig'))


def test_actual_empty_quarantine_object_is_idle_but_nonempty_is_not():
    result=inert_ps(r"""
$health='{"pid":123,"instance_id":"same","active":[],"quarantined_slots":{}}'|ConvertFrom-Json
Assert-OpIdleHealth $health 123 'same'
$health.quarantined_slots=[pscustomobject]@{slot1='cleanup'};$held=$false
try{Assert-OpIdleHealth $health 123 'same'}catch{$held=$true}
@{idle_verified=$true;quarantine_held=$held}|ConvertTo-Json -Compress
""")
    assert result==dict(idle_verified=True,quarantine_held=True)


def test_ps51_retained_native_process_list_preserves_exact_pair_shape():
    """Only reference this inert PowerShell fixture process; never start/stop one."""
    result = inert_ps(r"""
function Get-FixtureHeldProcesses {
    $held=[Collections.Generic.List[Diagnostics.Process]]::new()
    $held.Add([Diagnostics.Process]::GetCurrentProcess())
    $held.Add([Diagnostics.Process]::GetCurrentProcess())
    return ,$held
}
$state=@{processes=(Get-FixtureHeldProcesses)}
$when=[DateTime]'2026-10-15T12:00:00Z'
$task=[pscustomobject]@{LastRunTime=$when}
$task|Add-Member ScriptMethod GetInstances {
    param($flags)$c=[pscustomobject]@{Count=1}
    $c|Add-Member ScriptMethod Item {param($i)[pscustomobject]@{InstanceGuid='original'}};return $c
}
$failure=$null;$result=$null;$count=$null
try{
    $count=@($state.processes).Count
    $result=Get-OpRetainedTaskState $task 'original' $when $state.processes
}catch{
    $failure=@{type=$_.Exception.GetType().Name;line=$_.InvocationInfo.ScriptLineNumber;
        function=(Get-OpProperty $_.InvocationInfo.MyCommand 'Name');message=$_.Exception.Message}
}finally{foreach($p in $state.processes){$p.Dispose()}}
@{ps_edition=$PSVersionTable.PSEdition;ps_major=$PSVersionTable.PSVersion.Major;
    list_type=$state.processes.GetType().FullName;count=$count;result=$result;failure=$failure}|ConvertTo-Json -Depth 5 -Compress
""")
    assert result['ps_edition'] == 'Desktop'
    assert result['ps_major'] == 5
    assert result['list_type'].startswith('System.Collections.Generic.List`1[[System.Diagnostics.Process,')
    assert result['failure'] is None, result
    assert result['count'] == 2, result
    assert result['result'] == 'RUNNING', result


def test_starting_fence_context_survives_ready_validation_failure(tmp_path):
    """A failed admission proof must not discard the exact created-fence identity."""
    result = inert_ps(r"""
$script:OpPrivate='PRIVATE';$script:OpOldConfig='C:\fixture\old\pipeline.json'
$script:OpManifest=@{previous_config_sha256=('a'*64);request_sha256=('b'*64)}
$script:OpScheduler=$null;$script:OpFolder=$null
$script:seen=[Collections.Generic.List[string]]::new()
function Write-OpStatus {param($p,$s,$r,$step)}
function New-OpPrivateDirectory {param($p)$script:seen.Add('fresh_directory');$script:freshRoot=$p;$null=[IO.Directory]::CreateDirectory($p)}
function Write-OpRecord {param($p,$r)
    if((Split-Path -Parent $p) -cne $script:OpPrivate){throw 'Intent must not pollute the fresh child directory'}
    $script:seen.Add('intent_saved');[IO.File]::WriteAllText($p,($r|ConvertTo-Json -Compress))
}
function Assert-ProtectedPath {param($p)}
function New-OpOneShot {param($s,$f,$n,$a,$seconds)
    if(@([IO.Directory]::EnumerateFileSystemEntries($script:freshRoot)).Count){throw 'Child output root must be empty'}
    $script:seen.Add('task_created')
    return @{name=$n;arguments=$a;instance='fixture-instance';started=[DateTime]::UtcNow}
}
function Test-Path {param($LiteralPath)return $true}
function Open-428Pin {param($p,$h)return [IO.MemoryStream]::new()}
function Read-428Json {param($s)$script:seen.Add('read_ready');return @{status='WRITER_FENCE_HELD'}}
function Get-428FileSha256 {param($p)return ('c'*64)}
function Assert-OpFence {param($f)$script:seen.Add('validate_ready');throw [InvalidOperationException]::new('fixture admission rejection')}
$state=@{fence=$null};$failure=$null
try{$state.fence=Start-OpFence 'stop-fence' $state 'fence'}catch{
    $failure=@{type=$_.Exception.GetType().Name;line=$_.InvocationInfo.ScriptLineNumber;
        function=(Get-OpProperty $_.InvocationInfo.MyCommand 'Name');message=$_.Exception.Message}
}
$retained=$null
if($null -ne $state.fence){$retained=@{root=$state.fence.root;nonce=$state.fence.nonce;
    instance=$state.fence.handle.instance;ready_pin=$state.fence.ready_pin}}
@{seen=@($script:seen);failure=$failure;retained=$retained}|ConvertTo-Json -Depth 5 -Compress
""".replace('PRIVATE', str(tmp_path)))
    assert result['seen'] == ['fresh_directory', 'intent_saved', 'task_created', 'read_ready', 'validate_ready']
    assert result['failure']['type'] == 'InvalidOperationException'
    assert result['retained'] is not None, result
    assert result['retained']['instance'] == 'fixture-instance'
    assert result['retained']['ready_pin'] == 'c' * 64


@pytest.mark.parametrize('scenario,held,stops', [
    ('running', False, 1), ('ended', False, 0), ('exit_during_stop', False, 1),
    ('other_instance', True, 0), ('later_run', True, 0), ('orphan', True, 0),
    ('stop_error_still_running', True, 1), ('ended_before_fence', True, 0),
])
def test_fenced_stop_accepts_only_exact_retained_run_or_its_complete_exit(scenario, held, stops):
    result = inert_ps(r"""
$script:scenario='SCENARIO';$script:stops=0;$script:count=1
$script:guid=if($script:scenario -eq 'other_instance'){'replacement'}else{'original'}
$script:processes=@([pscustomobject]@{HasExited=$false;ExitTime=[DateTime]'2026-10-15T12:02:00Z'},[pscustomobject]@{HasExited=$false;ExitTime=[DateTime]'2026-10-15T12:02:00Z'})
$when=[DateTime]'2026-10-15T12:00:00Z'
$task=[pscustomobject]@{LastRunTime=$when}
if($script:scenario -eq 'later_run'){$task.LastRunTime=$when.AddSeconds(1)}
if($script:scenario -in @('ended','orphan','ended_before_fence')){
    $script:count=0;$script:processes[0].HasExited=$true
    $script:processes[1].HasExited=$script:scenario -ne 'orphan'
    if($script:scenario -eq 'ended_before_fence'){$script:processes[0].ExitTime=$when}
}
$task|Add-Member ScriptMethod GetInstances {
    param($flags)$c=[pscustomobject]@{Count=$script:count}
    $c|Add-Member ScriptMethod Item {param($i)[pscustomobject]@{InstanceGuid=$script:guid}};return $c
}
$task|Add-Member ScriptMethod Stop {
    param($flags)$script:stops++
    if($script:scenario -eq 'stop_error_still_running'){throw 'stop rejected'}
    $script:count=0;foreach($p in $script:processes){$p.HasExited=$true}
    if($script:scenario -eq 'exit_during_stop'){throw 'exact old run already ended'}
}
$held=$false
try{Stop-OpRetainedTask $task 'original' $when $script:processes ([DateTimeOffset]$when.AddMinutes(1)).ToUnixTimeSeconds()}catch{$held=$true}
@{held=$held;stops=$script:stops}|ConvertTo-Json -Compress
""".replace('SCENARIO', scenario))
    assert result == dict(held=held, stops=stops)


@pytest.mark.parametrize('ended_at_ready', [False, True])
def test_real_stop_actions_never_request_health_after_writer_fence(ended_at_ready):
    result = inert_ps(r"""
$script:seen=[Collections.Generic.List[string]]::new();$script:fenced=$false;$script:count=1
$script:endedAtReady=ENDED;$script:when=[DateTime]'2026-10-15T12:00:00Z'
$script:processes=@([pscustomobject]@{HasExited=$false;ExitTime=$script:when.AddMinutes(2)},[pscustomobject]@{HasExited=$false;ExitTime=$script:when.AddMinutes(2)})
$trigger=[pscustomobject]@{Enabled=$true};$triggers=[pscustomobject]@{trigger=$trigger}
$triggers|Add-Member ScriptMethod Item {param($i)$this.trigger}
$script:task=[pscustomobject]@{Xml='xml';LastRunTime=$script:when;Definition=[pscustomobject]@{Triggers=$triggers};Enabled=$true}
$script:task|Add-Member ScriptMethod GetSecurityDescriptor {param($flags)'sddl'}
$script:task|Add-Member ScriptMethod GetInstances {
    param($flags)$c=[pscustomobject]@{Count=$script:count}
    $c|Add-Member ScriptMethod Item {param($i)[pscustomobject]@{InstanceGuid='instance'}};return $c
}
$script:task|Add-Member ScriptMethod Stop {
    param($flags)$script:seen.Add('stop');$script:count=0;foreach($p in $script:processes){$p.HasExited=$true}
}
$script:OpFolder=[pscustomobject]@{}
$script:OpFolder|Add-Member ScriptMethod GetTask {param($name)$script:task}
$script:OpFolder|Add-Member ScriptMethod RegisterTaskDefinition {param($name,$d,$flags,$owner,$pw,$type,$sddl)$script:seen.Add('disable-trigger')}
$script:OpOldRoot='old';$script:OpOldConfig='old-config';$script:OpOldArgs='old-args'
$script:OpOriginalXml='xml';$script:OpOriginalSddl='sddl'
function Write-OpStatus {param($phase)}
function Get-428Health {
    if($script:fenced){throw 'HTTP health under SQLite fence'}
    $script:seen.Add('health');[pscustomobject]@{pid=123;instance_id='runtime'}
}
function Assert-428Health {param($health,$root,$allow)}
function Open-OpProcessProof {
    param($health,$root,$config)
    if($script:fenced){throw 'Native capture after fence'}
    $script:seen.Add('handles');return ,$script:processes
}
function Start-OpFence {
    param($label)$script:seen.Add('ready');$script:fenced=$true
    if($script:endedAtReady){$script:count=0;foreach($p in $script:processes){$p.HasExited=$true}}
    return @{released=$false;ready=@{ready_at=([DateTimeOffset]$script:when.AddMinutes(1)).ToUnixTimeSeconds()}}
}
function Assert-OpFence {param($fence)if(-not $script:fenced){throw 'Fence absent'}}
function Assert-428WardenTask {param($task,$xml,$sddl,$root,$args,$enabled,$trigger,$count)}
function Assert-428PortFree {$script:seen.Add('port-free')}
$state=@{phase='admission_fence';old_pid=123;old_instance='runtime';old_task_instance='instance';old_task_last_run=$script:when;stopped=$false}
foreach($name in @('admission_fence','stop_previous')){
    $assignment=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -ceq ('$actions.'+$name)},$true))
    if($assignment.Count -ne 1){throw 'Expected one actual action'}
    $text=$assignment[0].Right.Extent.Text.Trim();$action=[scriptblock]::Create($text.Substring(1,$text.Length-2))
    & $action $state
}
@{seen=@($script:seen);stopped=$state.stopped}|ConvertTo-Json -Compress
""".replace('ENDED', '$true' if ended_at_ready else '$false'))
    expected = ['health', 'handles', 'ready', 'disable-trigger']
    if not ended_at_ready:
        expected.append('stop')
    assert result == dict(seen=expected+['port-free'], stopped=True)


@pytest.mark.parametrize('state,closed,clean,exited,cutover,expected',[
    ('NOT_COMMITTED',True,True,True,False,True),
    ('COMMITTED',True,True,True,False,False),
    ('UNKNOWN',True,True,True,False,False),
    ('NOT_COMMITTED',False,True,True,False,False),
    ('NOT_COMMITTED',True,False,True,False,False),
    ('NOT_COMMITTED',True,True,False,False,False),
    ('NOT_COMMITTED',True,True,True,True,False),
])
def test_restore_requires_explicit_authority(state,closed,clean,exited,cutover,expected):
    ps=lambda value:'$true' if value else '$false'
    value=inert_ps("""
$r=[pscustomobject]@{publication_state='STATE';runtime_resources_closed=CLOSED;publication_proof=[pscustomobject]@{catalog_probe_cleanup_verified=CLEAN}}
@{restore=(Test-OpRestoreAuthority $r $true EXITED CUTOVER)}|ConvertTo-Json -Compress
""".replace('STATE',state).replace('CLOSED',ps(closed)).replace('CLEAN',ps(clean)).replace('EXITED',ps(exited)).replace('CUTOVER',ps(cutover)))
    assert value['restore']==expected


TRANSACTION=r"""
$seen=[Collections.Generic.List[string]]::new()
$state=@{phase='package';stopped=$false;stop_requested=$false;cutover_requested=$false;acceptance_started=$false;acceptance_exited=$false;acceptance=$null;rollback='NOT_REQUIRED';error_type=$null}
$actions=@{}
foreach($name in @('preconditions','offline_install','codex_preflight','admission_fence','stop_previous','release_fence','catalog_acceptance','cutover','verify_running','enable_trigger','codex_integration')){
    $actions[$name]={param($s)
        $seen.Add($s.phase)
        if($s.phase -eq 'stop_previous'){$s.stopped=$true}
        if($s.phase -eq 'catalog_acceptance'){$s.acceptance_exited=$true;$s.acceptance=[pscustomobject]@{publication_state='PUB';runtime_resources_closed=$true;publication_proof=[pscustomobject]@{catalog_probe_cleanup_verified=$true}}}
        if($s.phase -eq 'FAIL') {throw 'inert failure'}
    }
}
$actions.restore_previous={param($s)$seen.Add('restore_previous')}
$state=Invoke-OpTransaction $actions $state
$record=New-OpResultRecord $state ([pscustomobject]@{source_commit=('a'*40);request_sha256=('b'*64)}) ('c'*64)
@{status=$record.status;rollback=$record.rollback;error_type=$record.error_type;seen=@($seen);cutover=$record.cutover_requested;late_prompt=$record.late_prompt}|ConvertTo-Json -Compress
"""


def test_complete_sequence_and_strict_mode_success_projection():
    result=inert_ps(TRANSACTION.replace('PUB','COMMITTED').replace('FAIL','none'))
    assert result['status']=='R428_OPERATIONAL_RUNNING_VERIFIED'
    assert result['error_type'] is None
    assert result['seen']==['preconditions','offline_install','codex_preflight','admission_fence','stop_previous',
                           'release_fence','catalog_acceptance','cutover','verify_running','enable_trigger','codex_integration']


@pytest.mark.parametrize('failure,pub,restore',[
    ('offline_install','UNKNOWN',False),('codex_preflight','UNKNOWN',False),('admission_fence','UNKNOWN',False),
    ('release_fence','UNKNOWN',True),('catalog_acceptance','NOT_COMMITTED',True),
    ('catalog_acceptance','COMMITTED',False),('catalog_acceptance','UNKNOWN',False),
    ('cutover','COMMITTED',False),('verify_running','COMMITTED',False),('enable_trigger','COMMITTED',False),('codex_integration','COMMITTED',False),
])
def test_failure_preserves_evidence_and_never_restarts_after_unknown_or_committed_publication(failure,pub,restore):
    result=inert_ps(TRANSACTION.replace('PUB',pub).replace('FAIL',failure))
    assert result['status']=='R428_OPERATIONAL_HELD_PRESERVE_EVIDENCE'
    assert ('restore_previous' in result['seen'])==restore
    assert result['seen'][-1] in (failure,'restore_previous')


def test_explicit_final_config_path_not_install_bootstrap():
    row=inert_ps(r"""@{args=(Get-OpDaemonArguments 'C:\protected\phase\pipeline.json' 'C:\private')}|ConvertTo-Json -Compress""")
    assert r'--config "C:\protected\phase\pipeline.json"' in row['args']


def test_queued_task_is_not_mistaken_for_successful_exit():
    row=inert_ps(r"""
$t=[pscustomobject]@{State=3;LastTaskResult=0;LastRunTime=[DateTime]'2001-01-01Z'}
$t|Add-Member ScriptMethod GetInstances {param($flags)[pscustomobject]@{Count=0}}
$now=[DateTime]::UtcNow;$queued=Test-OpTaskTerminal $t $now
$t.LastRunTime=$now;$t.LastTaskResult=267009;$running=Test-OpTaskTerminal $t $now
$t.LastTaskResult=2;$ended=Test-OpTaskTerminal $t $now
@{queued=$queued;running=$running;ended=$ended}|ConvertTo-Json -Compress
""")
    assert row==dict(queued=False,running=False,ended=True)


@pytest.mark.parametrize('state,code,count,recent,terminal', [
    (2, 0, 0, True, False),  # Queued can have no visible instance and a cached zero result.
    (4, 0, 0, True, False), (0, 0, 0, True, False),
    (3, 0x41303, 0, True, False), (3, 0x41325, 0, True, False),
    (3, 0x41301, 0, True, False), (3, 0x41300, 0, True, False),
    (3, 0x41302, 0, True, False),
    (3, 0, 0, True, True), (3, 2, 0, True, True),
    (1, 0, 0, True, True), (1, 2, 0, True, True),
    (3, 2, 1, True, False), (3, 2, 0, False, False),
])
def test_terminal_detection_requires_idle_state_and_actual_completion(state, code, count, recent, terminal):
    result = inert_ps(r"""
$now=[DateTime]::UtcNow
$t=[pscustomobject]@{State=STATE;LastTaskResult=CODE;LastRunTime=$(if(RECENT){$now}else{$now.AddMinutes(-1)});FixtureCount=COUNT}
$t|Add-Member ScriptMethod GetInstances {param($flags)[pscustomobject]@{Count=$this.FixtureCount}}
@{terminal=(Test-OpTaskTerminal $t $now)}|ConvertTo-Json -Compress
""".replace('STATE', str(state)).replace('CODE', str(code)).replace('COUNT', str(count))
        .replace('RECENT', '$true' if recent else '$false'))
    assert result['terminal'] == terminal


@pytest.mark.parametrize('fault', ['none', 'nonce', 'exited', 'identity'])
def test_phase_ack_is_atomic_and_follows_retained_identity(tmp_path, fault):
    body=r"""
$script:seen=[Collections.Generic.List[string]]::new()
$script:start=[pscustomobject]@{schema='cochem-owner-task-catalog-start/4.2.8';nonce=('a'*32);pid=123;
    bootstrap_sha256=('b'*64);request_sha256=('c'*64);started_at=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()}
if('FAULT' -ceq 'nonce'){$script:start.nonce='wrong'}
function Get-428FileSha256 {param($p)return ('d'*64)}
function Open-428Pin {param($p,$h)return [IO.MemoryStream]::new()}
function Read-OpPrivateRecord {param($p)return $script:start}
function Assert-OpOneShot {param($h,$running)$script:seen.Add('task')}
function Open-OpOneShotProcess {param($h,$id)
    $script:seen.Add('handles');if('FAULT' -ceq 'identity'){throw 'identity mismatch'}
    $p=[pscustomobject]@{HasExited=('FAULT' -ceq 'exited')};$p|Add-Member ScriptMethod Dispose {}
    return ,@($p,$p)
}
function Write-OpRecord {param($p,$record)
    $script:seen.Add('ack');[IO.File]::WriteAllText($p,($record|ConvertTo-Json -Compress))
    if(Test-Path -LiteralPath (Join-Path 'ROOT' 'phase-start-ack.json')){throw 'Ack visible before flush'}
}
$held=$false
try{$null=Confirm-OpPhaseStart @{started=[DateTime]::UtcNow} (Join-Path 'ROOT' 'phase-started.json') ('a'*32) $script:start}
catch{$held=$true}
$ack=$null;$path=Join-Path 'ROOT' 'phase-start-ack.json'
if(Test-Path -LiteralPath $path){$ack=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json}
@{held=$held;seen=@($script:seen);ack=$ack;pending=(Test-Path -LiteralPath (Join-Path 'ROOT' 'phase-start-ack.pending'))}|ConvertTo-Json -Depth 5 -Compress
"""
    result=inert_ps(body.replace('ROOT',str(tmp_path).replace("'","''")).replace('FAULT',fault))
    if fault=='none':
        assert result['seen']==['task','handles','ack']
        assert not result['held'] and not result['pending']
        assert result['ack']==dict(schema='cochem-owner-task-catalog-start-ack/4.2.8',nonce='a'*32,
            start_sha256='d'*64,pid=123,bootstrap_sha256='b'*64,request_sha256='c'*64)
    else:
        assert result['held'] and result['ack'] is None and 'ack' not in result['seen']


@pytest.fixture
def package(tmp_path,monkeypatch):
    payload=tmp_path/'payload';payload.mkdir()
    task=tmp_path/'task';task.mkdir()
    config=dict(max_execution_slots=4,catalog_activation=True,task_planning=None)
    raw_config=json.dumps(config).encode()
    files={'pipeline.json':raw_config,'install-manifest.json':b'{}','source-test-evidence.json':b'{}',
           'install_operational_428_runtime.ps1':b'reviewed-installer','stage_aetherdesk_427_payloads.ps1':b'reviewed-copy'}
    release=dict(schema='cochem-428-operational-release/1',revision=prepare.REVISION,
        target_root=prepare.TARGET_ROOT,task_planning_enabled=False,catalog_publication_required=True,
        source_commit='a'*40,previous=dict(config_sha256=prepare.PREVIOUS_CONFIG_SHA256,install_manifest_sha256=prepare.PREVIOUS_INSTALL_SHA256),
        bootstrap_candidate_sha256=prepare.sha(raw_config),install_manifest_sha256=prepare.sha(b'{}'),
        files=[dict(name=n,sha256=prepare.sha(v),length=len(v)) for n,v in files.items()])
    for name,blob in files.items():(payload/name).write_bytes(blob)
    (payload/'operational-release.json').write_text(json.dumps(release))
    (task/'task-catalog-request.json').write_bytes(b'{"request":"test"}')
    manifest=dict(schema='cochem-task-catalog-release/4.2.8',source_commit='a'*40,request_id='b'*32,
        request_sha256=prepare.sha((task/'task-catalog-request.json').read_bytes()),
        request_bytes=(task/'task-catalog-request.json').stat().st_size,configuration_sha256=prepare.sha(prepare.encoded(config)))
    (task/'task-catalog-manifest.json').write_text(json.dumps(manifest))
    previous=tmp_path/'previous';previous.mkdir()
    helper=(ROOT/'scripts/run_428_launch.ps1').read_bytes()
    (previous/'run_428_launch.ps1').write_bytes(helper)
    monkeypatch.setattr(prepare,'_committed_script',lambda repo,commit,name:(repo/'scripts'/name).read_bytes())
    return dict(payload=payload,task_catalog_release=task,destination=tmp_path/'launch',repository=ROOT,previous_bundle=previous)


def test_fresh_launcher_binds_every_input_and_keeps_old_payload_unchanged(package):
    before={p.name:p.read_bytes() for p in package['payload'].iterdir()}
    result=prepare.prepare_operational_launch(**package)
    launch=package['destination'];manifest=json.loads((launch/'launch-manifest.json').read_text())
    assert result['host_executed'] is False
    assert result['administrator_review_required'] is True
    assert result['launch_manifest_sha256']==prepare.sha((launch/'launch-manifest.json').read_bytes())
    for row in manifest['files']:
        assert row['sha256']==prepare.sha((launch/row['name']).read_bytes())
    assert before=={p.name:p.read_bytes() for p in package['payload'].iterdir()}


@pytest.mark.parametrize('mutation',['source','bootstrap','request','input','helper','old_root'])
def test_unbound_release_refused_before_creating_destination(package,mutation):
    if mutation in ('source','bootstrap','request'):
        p=package['task_catalog_release']/'task-catalog-manifest.json';value=json.loads(p.read_text())
        key={'source':'source_commit','bootstrap':'configuration_sha256','request':'request_sha256'}[mutation]
        value[key]='0'*64;p.write_text(json.dumps(value))
    elif mutation=='input': (package['payload']/'pipeline.json').write_text('{}')
    elif mutation=='helper': (package['previous_bundle']/'run_428_launch.ps1').write_text('unexpected')
    else:
        p=package['payload']/'operational-release.json';value=json.loads(p.read_text());value['target_root']='old';p.write_text(json.dumps(value))
    with pytest.raises(ValueError):prepare.prepare_operational_launch(**package)
    assert not package['destination'].exists()


def test_scoped_codex_integration_is_pinned_to_exact_source_owner_and_runtime(package,tmp_path):
    integration=dict(schema='cochem-codex-integration-update/1',source_commit='a'*40,
        user_home=r'C:\Users\ansac',runtime_root=prepare.TARGET_ROOT,
        client_config=r'C:\Users\ansac\CoChem427\pipeline-client-r3.json')
    path=tmp_path/'codex.json';path.write_text(json.dumps(integration))
    prepare.prepare_operational_launch(**package,codex_integration=path)
    manifest=json.loads((package['destination']/'launch-manifest.json').read_text())
    assert manifest['integration_manifest']=='codex-integration.json'
    assert manifest['integration_sha256']==prepare.sha(path.read_bytes())
    assert (package['destination']/'codex-integration.json').read_bytes()==path.read_bytes()


@pytest.mark.parametrize('field',['source_commit','runtime_root','user_home','client_config'])
def test_integration_wrong_identity_never_packaged(package,tmp_path,field):
    integration=dict(schema='cochem-codex-integration-update/1',source_commit='a'*40,
        user_home=r'C:\Users\ansac',runtime_root=prepare.TARGET_ROOT,
        client_config=r'C:\Users\ansac\CoChem427\pipeline-client-r3.json')
    integration[field]='wrong';path=tmp_path/'codex.json';path.write_text(json.dumps(integration))
    with pytest.raises(ValueError,match='Codex integration'):
        prepare.prepare_operational_launch(**package,codex_integration=path)
    assert not package['destination'].exists()
