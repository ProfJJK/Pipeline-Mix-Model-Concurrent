"""Exact-attempt continuation ports are inert; no protected/task/provider actions."""
import json
import time

import pytest

from pipeline_tests.test_operational_launch_428 import inert_ps
from pipeline_tests.test_operational_recovery_package_428 import prepare


@pytest.mark.parametrize('fault', ['none', 'boolean_result', 'string_pid'])
def test_python_preparer_contract_matches_actual_powershell_fields_and_types(fault):
    spec=prepare.make_recovery_spec('b'*40,recovery_id='a'*32)
    if fault=='boolean_result':
        spec['warden']['last_task_result']=True
    if fault=='string_pid':
        spec['fence']['pid']=str(spec['fence']['pid'])
    result=inert_ps(r"""
$r='JSON'|ConvertFrom-Json;$held=$false
try{Assert-OpExactFields $r (Get-OpRecoveryExpected) @('recovery_id','launcher_source_commit')}catch{$held=$true}
@{held=$held;runtime_source=$r.runtime_source_commit}|ConvertTo-Json -Compress
""".replace('JSON',json.dumps(spec).replace("'","''")))
    assert result['held']==(fault!='none'),result
    assert result['runtime_source']==prepare.RUNTIME_SOURCE_COMMIT


@pytest.mark.parametrize('fault', ['none','record_pin','original_input','runtime_source','launcher_source','extra','catalog_timeout'])
def test_recovery_contract_preserves_exact_original_inputs(fault):
    result=inert_ps(r"""
$r=Get-OpRecoveryExpected;$r.recovery_id='a'*32;$r.launcher_source_commit='b'*40
$original=[pscustomobject]@{source_commit=$r.runtime_source_commit;files=@([pscustomobject]@{name='pipeline.json';sha256=('c'*64);length=9},
    [pscustomobject]@{name='run_operational_428_launch.ps1';sha256=('d'*64);length=10});catalog_timeout_seconds=7200}
$m=$original|ConvertTo-Json -Depth 8|ConvertFrom-Json
$m|Add-Member launcher_source_commit ('b'*40)
$m.files[1].sha256='e'*64
switch('FAULT'){
    'record_pin' {$r.owner_result_sha256='f'*64}
    'original_input' {$m.files[0].sha256='f'*64}
    'runtime_source' {$m.source_commit='f'*40}
    'launcher_source' {$m.launcher_source_commit='f'*40}
    'extra' {$r.unreviewed='extra'}
    'catalog_timeout' {$m.catalog_timeout_seconds=1}
}
$held=$false
try{Assert-OpRecoveryManifest $r $m $original}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
""".replace('FAULT',fault))
    assert result['held'] == (fault != 'none')


@pytest.mark.parametrize('image,command,accepted', [
    (r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\Scripts\python.exe',
     r'"C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\Scripts\python.exe" -I -B -m cochem_pipeline mcp --client-config C:\Users\ansac\CoChem427\pipeline-client-r3.json',True),
    (r'C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe',
     r'"C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r4\.venv\Scripts\python.exe" -I -B -m cochem_pipeline mcp --client-config "C:\Users\ansac\CoChem427\pipeline-client-r3.json"',True),
    (r'C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe',
     r'python -c "print(\"-m cochem_pipeline mcp\")"',False),
    (r'C:\untrusted\python.exe',
     r'"C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r4\.venv\Scripts\python.exe" -I -B -m cochem_pipeline mcp --client-config C:\Users\ansac\CoChem427\pipeline-client-r3.json',False),
    (r'C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe',
     r'"C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe" -I -B -m cochem_pipeline mcp --client-config C:\Users\ansac\CoChem427\pipeline-client-r3.json --extra',False),
])
def test_mcp_inventory_exemption_is_complete_exact_argv(image,command,accepted):
    result=inert_ps(r"""
$script:python='C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe'
$script:checked=0
function Assert-ProtectedPath {param($p)$script:checked++}
@{accepted=(Test-OpExactMcpProcess 'IMAGE' 'COMMAND');checked=$script:checked}|ConvertTo-Json -Compress
""".replace('IMAGE',image).replace('COMMAND',command))
    assert result==dict(accepted=accepted,checked=int(accepted))


def test_recovery_claim_is_create_once_even_after_a_hold():
    result=inert_ps(r"""
$script:exists=$false;$script:created=0;$script:written=0
function Test-Path {param($LiteralPath)return $script:exists}
function New-ProtectedDirectory {param($p)$script:created++;$script:exists=$true}
function Write-OpRecord {param($p,$r)$script:written++;if($r.recovery_id -cne ('a'*32)){throw 'Wrong claim'}}
$r=@{recovery_id=('a'*32)};$m=@{recovery_sha256=('b'*64);source_commit=('c'*40);launcher_source_commit=('d'*40)}
$path=New-OpRecoverySitting $r $m ('e'*64)
$held=$false;try{$null=New-OpRecoverySitting $r $m ('e'*64)}catch{$held=$true}
@{path=$path;held=$held;created=$script:created;written=$script:written}|ConvertTo-Json -Compress
""")
    assert result['held'] and result['created']==result['written']==1
    assert result['path'].endswith('a62bffb278044fffbaf21207a866ff81-'+'a'*32)


TASK=r"""
$script:recovery=Get-OpRecoveryExpected;$expected=$script:recovery.warden
$when=[DateTime]::Parse($expected.last_run_utc)
$action=[pscustomobject]@{Type=0;Path='C:\fixture\old\.venv\Scripts\python.exe';WorkingDirectory='C:\fixture\old';Arguments='exact-args'}
$actions=[pscustomobject]@{Count=1;Value=$action};$actions|Add-Member ScriptMethod Item {param($n)$this.Value}
$trigger=[pscustomobject]@{Type=9;UserId='AETHERDESK\ansac';Enabled=$true}
$triggers=[pscustomobject]@{Count=1;Value=$trigger};$triggers|Add-Member ScriptMethod Item {param($n)$this.Value}
$d=[pscustomobject]@{Actions=$actions;Triggers=$triggers;Principal=[pscustomobject]@{UserId='SYSTEM';LogonType=5;RunLevel=1};Settings=[pscustomobject]@{RestartCount=0;MultipleInstances=2}}
$script:task=[pscustomobject]@{State=3;Enabled=$true;LastTaskResult=1;LastRunTime=$when;Xml='exact-xml';Definition=$d;FixtureCount=0;FixtureSddl='exact-sddl'}
$script:task|Add-Member ScriptMethod GetSecurityDescriptor {param($f)$this.FixtureSddl}
$script:task|Add-Member ScriptMethod GetInstances {param($f)[pscustomobject]@{Count=$this.FixtureCount}}
function Assert-428TaskAcl {param($t)}
function Get-OpTextSha256 {param($t)if($t -ceq 'exact-xml'){return $expected.task_xml_sha256};if($t -ceq 'exact-sddl'){return $expected.task_sddl_sha256};return ('f'*64)}
"""


@pytest.mark.parametrize('fault',['none','xml','last_run','result','instance','running','disabled','trigger'])
def test_stopped_recovery_task_must_be_the_exact_preserved_run(fault):
    result=inert_ps(TASK+r"""
switch('FAULT'){
    'xml' {$script:task.Xml='different'}
    'last_run' {$script:task.LastRunTime=$when.AddSeconds(1)}
    'result' {$script:task.LastTaskResult=0}
    'instance' {$script:task.FixtureCount=1}
    'running' {$script:task.State=4}
    'disabled' {$script:task.Enabled=$false}
    'trigger' {$trigger.Enabled=$false}
}
$held=$false;try{Assert-OpRecoveryTask $script:task $expected 'C:\fixture\old' 'exact-args' 1}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
""".replace('FAULT',fault))
    assert result['held']==(fault!='none')


@pytest.mark.parametrize('fault',['none','pid_reused','daemon','orphan','unknown_python'])
def test_recovery_inventory_refuses_live_native_or_unknown_roles(fault):
    result=inert_ps(r"""
$script:OpOldRoot='C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r4'
$script:OpRoot='C:\Program Files\CoChem\Pipeline4.2.8-windows-20261015-r5'
$script:python='C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe'
function Assert-428PortFree {}
function Get-CimInstance {
    param($Class,$Filter)
    if($Filter){if('FAULT' -eq 'pid_reused'){return [pscustomobject]@{ProcessId=24424}};return $null}
    if('FAULT' -eq 'none'){return @()}
    $image=if('FAULT' -eq 'orphan'){Join-Path $script:OpOldRoot '.venv\Scripts\python.exe'}else{$script:python}
    $cmd=if('FAULT' -eq 'unknown_python'){'python -c unknown'}else{'python -I -B -m cochem_pipeline daemon --config old'}
    return @([pscustomobject]@{ProcessId=987;ExecutablePath=$image;CommandLine=$cmd;ParentProcessId=986})
}
$held=$false;try{Assert-OpRecoveryQuiescent (Get-OpRecoveryExpected)}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
""".replace('FAULT',fault))
    assert result['held']==(fault!='none')


@pytest.mark.parametrize('fault',['none','catalog_changed','last_run_changed','orphan'])
def test_extracted_recovery_actions_never_reinstall_start_or_stop_old_runtime(fault):
    result=inert_ps(TASK+r"""
$script:OpRecovery=$script:recovery;$script:OpPrivate='C:\fixture\fresh';$script:OpOldRoot='C:\fixture\old'
$script:OpOldArgs='exact-args';$script:OpOriginalXml='exact-xml';$script:OpOriginalSddl='exact-sddl';$script:targetRoot='C:\fixture\new'
$script:OpFolder=[pscustomobject]@{};$script:seen=[Collections.Generic.List[string]]::new()
$script:OpFolder|Add-Member ScriptMethod GetTask {param($n)$script:task}
$script:OpFolder|Add-Member ScriptMethod RegisterTaskDefinition {param($n,$d,$f,$u,$p,$l,$s)$script:seen.Add('disable-trigger')}
$script:task|Add-Member ScriptMethod Stop {param($f)throw 'Forbidden Stop'}
$script:task|Add-Member ScriptMethod Run {param($f)throw 'Forbidden Run'}
function Write-OpStatus {param($p,$s,$r,$step)}
function Invoke-428Native {throw 'Forbidden installer/native launch'}
function Get-428Health {throw 'Forbidden old health'}
function Get-Item {param($LiteralPath)[pscustomobject]@{Length=42}}
function Copy-VerifiedPayload {param($r)$script:seen.Add('copy-request')}
function Assert-OpRecoveryQuiescent {param($r,$f)if('FAULT' -eq 'orphan'){throw 'Native orphan'};$script:seen.Add('quiescent')}
function Assert-OpRecoveryRuntimeDependencies {param($b,$h)$script:seen.Add('runtime-dependencies')}
function Start-OpFence {param($l,$s,$k)
    $script:seen.Add('fresh-fence');$catalog=@{active_policy_sha256='policy';active_catalog_sha256=$null}
    if('FAULT' -eq 'catalog_changed'){$catalog.active_policy_sha256='changed'}
    $f=@{ready=@{catalog=$catalog;expires_at=([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0+240)}};$s[$k]=$f;return $f
}
function Assert-OpFence {param($f)$script:seen.Add('fence-proof')}
function Assert-428WardenTask {param($t,$x,$s,$r,$a,$e,$tr,$count)if($t.Enabled -ne $e){throw 'Unexpected enable state'}}
function Assert-428PortFree {$script:seen.Add('port-free')}
if('FAULT' -eq 'last_run_changed'){$script:task.LastRunTime=$when.AddSeconds(1)}
$m=@{request_sha256=('a'*64);bootstrap_sha256=('b'*64)};$Directory='C:\fixture\package';$pins=[Collections.Generic.List[IO.Stream]]::new();$state=@{phase='fixture';stopped=$false;
    old_task_last_run=$when.ToUniversalTime();recovery_catalog=@{active_policy_sha256='policy';active_catalog_sha256=$null}}
$held=$false
try{foreach($name in @('offline_install','admission_fence','stop_previous')){
    $nodes=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -ceq ('$actions.'+$name)},$true))
    $text=$nodes[0].Right.Extent.Text.Trim();$action=[scriptblock]::Create($text.Substring(1,$text.Length-2));& $action $state
}}catch{$held=$true}
@{held=$held;stopped=$state.stopped;enabled=$script:task.Enabled;seen=@($script:seen)}|ConvertTo-Json -Depth 5 -Compress
""".replace('FAULT',fault))
    assert result['held']==(fault!='none'),result
    assert result['seen'][0]=='copy-request'
    if fault=='none':
        assert result['stopped'] and not result['enabled']
        assert result['seen'].count('fresh-fence')==result['seen'].count('disable-trigger')==1
        assert result['seen'].index('runtime-dependencies')<result['seen'].index('fresh-fence')
    else:
        assert not result['stopped'] and result['enabled']
        assert 'disable-trigger' not in result['seen']


EVIDENCE=r"""
$script:recovery=Get-OpRecoveryExpected;$script:OpRecovery=$script:recovery
$script:OpRoot='C:\fixture\new';$script:OpOldRoot='C:\fixture\old';$script:OpOldConfig='C:\fixture\old\pipeline.json'
$script:OpOldArgs='exact-daemon-args';$script:OpPrivate='C:\fixture\fresh\private';$script:targetRoot=$script:OpRoot
$script:config=@{private_root='C:\fixture\board';token_file='TOKEN'};$script:OpConfig=$script:config
$m=@{request_sha256=('a'*64);previous_config_sha256=('b'*64);install_manifest_sha256=('c'*64);previous_install_sha256=('d'*64)}
$inventory=@{fixture='inventory'};$pins=[Collections.Generic.List[IO.Stream]]::new()
$state=@{verified_stopped_at_entry=$false;phase='preconditions'}
$script:seen=[Collections.Generic.List[string]]::new();$script:records=@{};$r=$script:recovery
$prior=Join-Path $r.original_sitting 'private';$froot=Join-Path $prior $r.fence.directory
$baseline=@{xml='baseline-xml';sddl='baseline-sddl';health=@{pid=$r.warden.pid};config_sha256=$m.previous_config_sha256}
$owner=@{schema='cochem-428-operational-owner-result/1';status='R428_OPERATIONAL_HELD_PRESERVE_EVIDENCE';phase='admission_fence';rollback='NOT_REQUIRED';
    cutover_requested=$false;source_commit=$r.runtime_source_commit;request_sha256=$m.request_sha256;launch_manifest_sha256=$r.original_launch_manifest_sha256}
$install=@{schema='cochem-428-offline-install/1';status='STOPPED_RUNTIME_INSTALLED';source_commit=$r.runtime_source_commit;manifest_sha256=$m.install_manifest_sha256}
function Add-FixtureRecord {param($p,$hash,$value)$script:records[$p]=@{pin=$hash;value=$value}}
Add-FixtureRecord (Join-Path $prior 'baseline.json') $r.baseline_sha256 $baseline
Add-FixtureRecord (Join-Path $prior 'owner-result.json') $r.owner_result_sha256 $owner
Add-FixtureRecord (Join-Path $script:OpRoot 'install-after.json') $r.install_after_sha256 $install
foreach($stage in @('started','ready','result')){
    $value=@{schema='cochem-owner-admission-fence/4.2.8';nonce=$r.fence.nonce;pid=$r.fence.pid;config_sha256=$m.previous_config_sha256;
        request_sha256=$m.request_sha256;database_path='C:\fixture\board\job_board.db';database_rows_modified=0}
    switch($stage){
        'started' {$value.status='WAITING_FOR_IDLE'}
        'ready' {$value.status='WRITER_FENCE_HELD';$value.counts=@{active_leaves=0;active_leases=0;native_reservations=0;uncleared_containment=0;catalog_probes=0};
            $value.catalog=@{active_policy_sha256=('e'*64);active_catalog_sha256=$null};$value.ready_at=1792089678.349171;$value.expires_at=1792089918.349171}
        'result' {$value.status='FENCE_EXPIRED';$value.released=$false;$value.lock_released=$true;$value.ready_sha256=$r.fence.ready_sha256}
    }
    Add-FixtureRecord (Join-Path $froot ($stage+'.json')) $r.fence[($stage+'_sha256')] $value
}
Add-FixtureRecord (Join-Path $script:OpRoot 'install-manifest.json') $m.install_manifest_sha256 @{}
Add-FixtureRecord $script:OpOldConfig $m.previous_config_sha256 $script:config
Add-FixtureRecord (Join-Path $script:OpOldRoot 'install-manifest.json') $m.previous_install_sha256 @{}
function Assert-ProtectedPath {param($p)$script:seen.Add('protected:'+[IO.Path]::GetFileName($p))}
function Open-428Pin {param($p,$hash)
    if(-not $script:records.ContainsKey($p) -or $script:records[$p].pin -cne $hash){throw 'Pinned record mismatch'}
    $script:seen.Add('pin:'+[IO.Path]::GetFileName($p));$raw=[Text.UTF8Encoding]::new($false).GetBytes(($script:records[$p].value|ConvertTo-Json -Depth 12))
    return [IO.MemoryStream]::new($raw)
}
function Read-428Json {param($stream)$reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true,4096,$true);try{return ($reader.ReadToEnd()|ConvertFrom-Json)}finally{$reader.Dispose()}}
function Test-Path {param($LiteralPath)return ('FAULT' -eq 'later_catalog' -and $LiteralPath.EndsWith('\catalog-phase'))}
function Get-ChildItem {param($LiteralPath,$Filter,[switch]$File)return @([pscustomobject]@{FullName='status-fixture'})}
function Read-OpPrivateRecord {param($p)return @{phase=$(if('FAULT' -eq 'later_status'){'catalog_acceptance'}else{'admission_fence'})}}
function Get-OpTextSha256 {param($t)if($t -ceq 'baseline-xml'){return $script:recovery.warden.task_xml_sha256};if($t -ceq 'baseline-sddl'){return $script:recovery.warden.task_sddl_sha256};throw 'Unexpected baseline'}
function Assert-OpRecoveryTask {param($t,$e,$root,$args,$triggers)
    if($triggers -eq 1 -and $root -cne $script:OpOldRoot){throw 'Wrong Warden root'}
    if($triggers -eq 0 -and ($root -cne $script:OpRoot -or $args -notlike '*--nonce a232264b12984ff2ab9ef33b7ec24c75*')){throw 'Wrong expired fence'}
    $script:seen.Add('task-proof:'+ $triggers)
}
function Assert-OpRecoveryQuiescent {param($r)$script:seen.Add('quiescent')}
function Assert-428Tree {$script:seen.Add('tree:'+$script:targetRoot)}
function Assert-428Interpreter {$script:seen.Add('interpreter:'+$script:targetRoot)}
function Get-428InstallFiles {param($i)if($i.fixture -cne 'inventory'){throw 'Wrong install inventory'};return @(@{destination='C:\fixture\new\source.py';sha256=('f'*64);length=9})}
function Open-VerifiedFile {param($p,$hash,$length)if($p -cne 'C:\fixture\new\source.py' -or $hash -cne ('f'*64) -or $length -ne 9){throw 'Payload differs'};$script:seen.Add('installed-payload');return [IO.MemoryStream]::new()}
function Write-OpRecord {param($p,$record)
    if($p -cne 'C:\fixture\fresh\private\baseline.json' -or -not $record.verified_stopped_at_entry -or $record.original_baseline_sha256 -cne $script:recovery.baseline_sha256){throw 'Unexpected output'}
    $script:seen.Add('new-baseline')
}
$script:task=[pscustomobject]@{Definition=@{}};$script:folder=[pscustomobject]@{}
$script:folder|Add-Member ScriptMethod GetTask {param($n)return $script:task};$script:OpFolder=$script:folder
if('FAULT' -eq 'swapped_record'){$script:records[(Join-Path $prior 'owner-result.json')].pin='0'*64}
if('FAULT' -eq 'wrong_binding'){$script:records[(Join-Path $froot 'result.json')].value.nonce='0'*32}
if('FAULT' -eq 'old_active'){$script:records[(Join-Path $froot 'ready.json')].value.counts.active_leases=1}
"""


@pytest.mark.parametrize('fault',['none','swapped_record','later_catalog','later_status','wrong_binding','old_active'])
def test_recovery_reopens_pinned_protected_evidence_before_reusing_installation(fault):
    result=inert_ps(EVIDENCE.replace('FAULT',fault)+r"""
$held=$false;$failure=$null
try{Assert-OpRecoveryEvidence $script:recovery $m $inventory $pins $state}catch{$held=$true;$failure=Get-OpFailure $_ 'fixture'}
@{held=$held;failure=$failure;verified=$state.verified_stopped_at_entry;seen=@($script:seen);pins=$pins.Count;
    catalog=(Get-OpProperty $state 'recovery_catalog')}|ConvertTo-Json -Depth 8 -Compress
""")
    assert result['held']==(fault!='none'),result
    assert result['verified']==(fault=='none')
    if fault=='none':
        assert result['pins']==8 and result['seen'][-1]=='new-baseline'
        assert result['catalog']==dict(active_policy_sha256='e'*64,active_catalog_sha256=None)
        assert {'task-proof:1','task-proof:0','installed-payload','quiescent'}<=set(result['seen'])
    else:
        assert 'installed-payload' not in result['seen'] and 'new-baseline' not in result['seen']


def test_extracted_recovery_preconditions_use_protected_evidence_without_old_health(tmp_path):
    token=tmp_path/'fixture-token.txt';token.write_text('inert-fixture-token')
    result=inert_ps(EVIDENCE.replace('FAULT','none').replace('TOKEN',str(token))+r"""
$script:scheduler=[pscustomobject]@{}
$script:scheduler|Add-Member ScriptMethod Connect {}
$script:scheduler|Add-Member ScriptMethod GetFolder {param($p)return $script:folder}
function New-Object {param($ComObject)if($ComObject -cne 'Schedule.Service'){throw 'Unexpected COM'};return $script:scheduler}
function Assert-428TaskAcl {param($t)}
function Write-OpStatus {param($phase,$status,$result,$substage)}
function Write-Host {param($text,$ForegroundColor)$script:seen.Add('walk-away')}
function Get-428Health {throw 'Forbidden old health request'}
function Open-OpProcessProof {throw 'Forbidden old process capture'}
$nodes=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -ceq '$actions.preconditions'},$true))
$text=$nodes[0].Right.Extent.Text.Trim();$action=[scriptblock]::Create($text.Substring(1,$text.Length-2));& $action $state
@{verified=$state.verified_stopped_at_entry;seen=@($script:seen);pins=$pins.Count}|ConvertTo-Json -Depth 6 -Compress
""")
    assert result['verified'] and result['pins']==10
    assert result['seen'][-1]=='walk-away'
    assert 'tree:C:\\fixture\\old' in result['seen'] and 'tree:C:\\fixture\\new' in result['seen']


def test_json_fractional_ready_times_pass_real_fence_binding_and_admission():
    ready_at=time.time()
    result=inert_ps(r"""
$script:OpPrivate='C:\fixture\private';$script:OpOldConfig='C:\fixture\old\pipeline.json'
$script:OpManifest=@{previous_config_sha256=('a'*64);request_sha256=('b'*64)};$script:OpConfig=@{private_root='C:\fixture\board'}
$nonce='a'*32;$root=Join-Path $script:OpPrivate ('stop-fence-'+('d'*32));$when=[DateTime]::UtcNow.AddSeconds(-1)
$argv='-I -B -m cochem_pipeline.owner_admission_fence_428 --config "'+$script:OpOldConfig+'" --config-sha256 '+$script:OpManifest.previous_config_sha256+
    ' --output-root "'+$root+'" --nonce '+$nonce+' --request-sha256 '+$script:OpManifest.request_sha256+' --wait-seconds 1800 --hold-seconds 240'
$r='JSON'|ConvertFrom-Json
$handle=@{name=('CoChem-4.2.8-Fence-'+$nonce);arguments=$argv;instance='fixture-instance';started=$when}
$f=@{root=$root;nonce=$nonce;arguments=$argv;name=$handle.name;intent_at=$when.AddSeconds(-1);owned=$true;handle=$handle;
    ready=$r;ready_pin=('c'*64);released=$false;completion=$null;process=$null}
$script:identityChecks=0
function Confirm-OpFenceProcess {param($f)Assert-OpFenceBinding $f;$script:identityChecks++}
Assert-OpFenceBinding $f;Assert-OpFence $f
@{identity_checks=$script:identityChecks;duration=($r.expires_at-$r.ready_at)}|ConvertTo-Json -Compress
""".replace('JSON',json.dumps(dict(schema='cochem-owner-admission-fence/4.2.8',status='WRITER_FENCE_HELD',
        nonce='a'*32,config_sha256='a'*64,request_sha256='b'*64,database_path=r'C:\fixture\board\job_board.db',
        pid=123,ready_at=ready_at,expires_at=ready_at+240,counts=dict(active_leaves=0,active_leases=0,
        native_reservations=0,uncleared_containment=0,catalog_probes=0)))))
    assert result==dict(identity_checks=1,duration=240)
