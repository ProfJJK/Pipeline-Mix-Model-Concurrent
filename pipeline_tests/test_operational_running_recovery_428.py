"""Inert fixtures for the running-r4 recovery scenario (after the 2026-10-15 reboot).

The r4 Warden's logon trigger restarted r4, so the stopped-Warden contract can
never match again. These fixtures drive the real launcher functions and
extracted actions; every task, process, health and filesystem port is inert.
"""
import hashlib
import json

import pytest

from pipeline_tests.test_operational_launch_428 import inert_ps
from pipeline_tests.test_operational_recovery_428 import EVIDENCE
from pipeline_tests.test_operational_recovery_package_428 import package, prepare  # noqa: F401 (fixture)

RUNNING='INSTALLED_R5_RUNNING_R4_20261016'
EXTRACT=r"""
function Invoke-Extracted {param([string]$Name,$State)
    $nodes=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -ceq ('$actions.'+$Name)},$true))
    if($nodes.Count -ne 1){throw 'Expected one actual action'}
    $text=$nodes[0].Right.Extent.Text.Trim();& ([scriptblock]::Create($text.Substring(1,$text.Length-2))) $State
}
"""


# --- Contract ---------------------------------------------------------------

def contract(spec):
    return inert_ps(r"""
$r='JSON'|ConvertFrom-Json;$held=$false
try{Assert-OpExactFields $r (Get-OpRecoveryExpectedFor $r) @('recovery_id','launcher_source_commit')}catch{$held=$true}
@{held=$held;selected=(Get-OpRecoveryExpectedFor $r).scenario}|ConvertTo-Json -Compress
""".replace('JSON', json.dumps(spec).replace("'", "''")))


def test_running_contract_is_identical_in_python_and_powershell():
    spec=prepare.make_recovery_spec('b'*40, recovery_id='a'*32, scenario='running')
    assert spec['schema']=='cochem-428-admission-recovery/2' and spec['scenario']==RUNNING
    assert spec['warden']==dict(pid=24424, task_xml_sha256=spec['warden']['task_xml_sha256'],
        task_sddl_sha256=spec['warden']['task_sddl_sha256'], last_run_after_utc='2026-10-15T01:37:07Z')
    stopped=prepare.make_recovery_spec('b'*40, recovery_id='a'*32)
    assert {k: v for k, v in spec.items() if k not in ('schema', 'scenario', 'warden')}==\
        {k: v for k, v in stopped.items() if k not in ('schema', 'scenario', 'warden')}
    assert contract(spec)==dict(held=False, selected=RUNNING)
    prepare.validate_recovery_spec(spec)


@pytest.mark.parametrize('fault', ['stopped_field', 'extra', 'schema', 'warden_pid', 'fence_pin', 'scenario_label'])
def test_running_contract_rejects_mixed_or_altered_fields(fault):
    spec=prepare.make_recovery_spec('b'*40, recovery_id='a'*32, scenario='running')
    if fault=='stopped_field': spec['warden']['last_task_result']=1
    if fault=='extra': spec['unreviewed']=True
    if fault=='schema': spec['schema']='cochem-428-admission-recovery/1'
    if fault=='warden_pid': spec['warden']['pid']=27208
    if fault=='fence_pin': spec['fence']['ready_sha256']='0'*64
    if fault=='scenario_label': spec['scenario']='INSTALLED_R5_EXPIRED_FENCE_20261015'
    with pytest.raises(ValueError):
        prepare.validate_recovery_spec(spec)
    assert contract(spec)['held'], fault


def test_running_scenario_requires_an_explicit_preparer_choice():
    with pytest.raises(ValueError):
        prepare.make_recovery_spec('b'*40, recovery_id='a'*32, scenario='rebooted')


@pytest.mark.parametrize('argv', [[], ['--scenario', 'rebooted']])
def test_preparer_cli_refuses_a_missing_or_unknown_scenario(monkeypatch, capsys, argv):
    monkeypatch.setattr('sys.argv', ['prepare', '--destination', 'd', '--repository', 'r', '--recovery-source-tests', 't',
        '--launcher-source-commit', 'b'*40, '--recovery-source-tests-sha256', 'c'*64]+argv)
    monkeypatch.setattr(prepare, 'prepare_operational_recovery', lambda **kw: pytest.fail('must not prepare'))
    with pytest.raises(SystemExit) as exit_info:
        prepare.main()
    assert exit_info.value.code==2 and '--scenario' in capsys.readouterr().err


def test_preparer_validates_each_scenario_against_its_own_contract():
    running=prepare.make_recovery_spec('b'*40, recovery_id='a'*32, scenario='running')
    stopped=prepare.make_recovery_spec('b'*40, recovery_id='a'*32)
    prepare.validate_recovery_spec(stopped)
    # A running label on the stopped body, or the reverse, is neither contract.
    for spec in (dict(stopped, scenario=running['scenario']), dict(running, scenario=stopped['scenario'])):
        with pytest.raises(ValueError):
            prepare.validate_recovery_spec(spec)
        assert contract(spec)['held']


@pytest.mark.parametrize('fault', ['none', 'record_pin', 'original_input', 'runtime_source', 'launcher_source', 'schema_v1', 'warden_shape'])
def test_running_manifest_preserves_exact_original_inputs(fault):
    result=inert_ps(r"""
$r=Get-OpRunningRecoveryExpected;$r.recovery_id='a'*32;$r.launcher_source_commit='b'*40
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
    'schema_v1' {$r.schema='cochem-428-admission-recovery/1'}
    'warden_shape' {$r.warden.last_task_result=1}
}
$r=$r|ConvertTo-Json -Depth 8|ConvertFrom-Json
$held=$false
try{Assert-OpRecoveryManifest $r $m $original}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
""".replace('FAULT', fault))
    assert result['held']==(fault!='none'), fault


def test_running_package_needs_the_running_entrypoint_and_records_its_scenario(package, monkeypatch):
    with pytest.raises(ValueError):
        prepare.prepare_operational_recovery(**package, scenario='running')
    launcher=b'function Assert-OpRecoveryManifest { }\nfunction Assert-OpRunningRecoveryEvidence { }\n'
    monkeypatch.setattr(prepare, '_committed_script', lambda repo, commit, name: launcher)
    result=prepare.prepare_operational_recovery(**package, scenario='running')
    recovery=json.loads((package['destination']/'admission-recovery.json').read_bytes())
    assert result['scenario']==recovery['scenario']==RUNNING
    assert recovery['schema']=='cochem-428-admission-recovery/2'
    assert 'last_task_result' not in recovery['warden'] and recovery['warden']['last_run_after_utc']=='2026-10-15T01:37:07Z'


# --- Running-mode evidence ----------------------------------------------------

RUNNING_EVIDENCE=EVIDENCE.replace('FAULT', 'none')+r"""
$script:recovery=Get-OpRunningRecoveryExpected;$script:OpRecovery=$script:recovery;$script:OpOriginalXml=$null
$trigger=[pscustomobject]@{Type=9;UserId='AETHERDESK\ansac';Enabled=$true}
$triggers=[pscustomobject]@{Count=1;Value=$trigger};$triggers|Add-Member ScriptMethod Item {param($n)$this.Value}
$def=[pscustomobject]@{Triggers=$triggers;Principal=[pscustomobject]@{UserId='SYSTEM';LogonType=5;RunLevel=1};Settings=[pscustomobject]@{RestartCount=0;MultipleInstances=2}}
$script:running=[pscustomobject]@{State=4;Enabled=$true;LastRunTime=[DateTime]'2026-10-16T11:20:15Z';Xml='live-xml';Definition=$def;Instances=1}
$script:running|Add-Member ScriptMethod GetSecurityDescriptor {param($f)'live-sddl'}
$script:running|Add-Member ScriptMethod GetInstances {param($f)$c=[pscustomobject]@{Count=$script:running.Instances}
    $c|Add-Member ScriptMethod Item {param($i)[pscustomobject]@{InstanceGuid='{run-guid}'}};return $c}
$script:version='4.2.8';$script:definition='baseline'
function Write-OpStatus {param($p,$s,$r,$step)}
function Assert-428WardenTask {param($t,$x,$s,$root,$a,$enabled,$trigger,$count)
    if($script:definition -ne 'baseline'){throw 'Warden task readback differs outside the reviewed change.'}
    $script:seen.Add('warden-definition:'+$x+':'+$s+':'+$root+':'+$a+':'+$enabled+':'+$trigger)}
function Get-428Health {$script:seen.Add('health');[pscustomobject]@{pid=27208;instance_id='586fc1c8';version=$script:version}}
function Assert-428Health {param($h,$root,$allow)if($root -cne $script:OpOldRoot){throw 'Wrong runtime root'}}
function Open-OpProcessProof {param($h,$root,$config)$script:seen.Add('native-proof');return ,@([pscustomobject]@{HasExited=$false},[pscustomobject]@{HasExited=$false})}
function Write-OpRecord {param($p,$record)
    if($p -cne 'C:\fixture\fresh\private\baseline.json' -or $record.verified_stopped_at_entry -ne $false -or
        $record.original_baseline_sha256 -cne $script:recovery.baseline_sha256 -or $null -eq $record.health){throw 'Unexpected running baseline'}
    $script:seen.Add('running-baseline')}
$state.previous_health_seconds=4
CHANGE
$held=$false;$failure=$null
try{Assert-OpRunningRecoveryEvidence $script:recovery $m $inventory $pins $state $script:running}catch{$held=$true;$failure=Get-OpFailure $_ 'fixture'}
@{held=$held;failure=$failure;seen=@($script:seen);pins=$pins.Count;substage=(Get-OpProperty $state 'substage');
  health_attempt=(Get-OpProperty $state 'health_last_attempt');
  verified=(Get-OpProperty $state 'verified_stopped_at_entry');old_pid=(Get-OpProperty $state 'old_pid');
  task_instance=(Get-OpProperty $state 'old_task_instance');previous_xml=(Get-OpProperty $state 'previous_task_xml');
  catalog=(Get-OpProperty $state 'recovery_catalog');original=$script:OpOriginalXml}|ConvertTo-Json -Depth 8 -Compress
"""


def running_evidence(change=''):
    return inert_ps(RUNNING_EVIDENCE.replace('CHANGE', change))


def test_running_evidence_reverifies_pins_and_binds_the_live_r4_run():
    result=running_evidence()
    assert not result['held'], result
    assert result['pins']==8 and result['verified'] is False
    assert result['old_pid']==27208 and result['task_instance']=='{run-guid}' and result['previous_xml']=='live-xml'
    assert result['original']=='baseline-xml'
    # Two consistent health answers (a just-started r4 may still be in its Docker wait).
    assert result['seen'].count('health')>=2, result
    assert 'warden-definition:baseline-xml:baseline-sddl:C:\\fixture\\old:exact-daemon-args:True:True' in result['seen']
    # Only the expired fence task is checked against the stopped contract helper.
    assert 'task-proof:0' in result['seen'] and 'task-proof:1' not in result['seen']
    assert result['seen'].index('native-proof')<result['seen'].index('installed-payload')<result['seen'].index('running-baseline')
    assert result['catalog']==dict(active_policy_sha256='e'*64, active_catalog_sha256=None)


def test_extracted_running_preconditions_take_the_running_evidence_path_only(tmp_path):
    token=tmp_path/'fixture-token.txt';token.write_text('inert-fixture-token')
    result=inert_ps(EXTRACT+EVIDENCE.replace('FAULT', 'none').replace('TOKEN', str(token))+r"""
$script:OpRecovery=Get-OpRunningRecoveryExpected
$script:scheduler=[pscustomobject]@{}
$script:scheduler|Add-Member ScriptMethod Connect {}
$script:scheduler|Add-Member ScriptMethod GetFolder {param($p)return $script:folder}
function New-Object {param($ComObject)if($ComObject -cne 'Schedule.Service'){throw 'Unexpected COM'};return $script:scheduler}
function Assert-428TaskAcl {param($t)$script:seen.Add('task-acl')}
function Write-OpStatus {param($phase,$status,$result,$substage)}
function Write-Host {param($text,$ForegroundColor)$script:seen.Add('walk-away:'+$text.StartsWith('Running r4 baseline'))}
function Assert-OpRecoveryEvidence {throw 'Stopped-contract evidence in running mode'}
function Assert-OpRunningRecoveryEvidence {param($r,$mm,$inv,$p,$s,$t)
    if(-not [object]::ReferenceEquals($t,$script:task) -or $r.scenario -cne 'INSTALLED_R5_RUNNING_R4_20261016'){throw 'Not the live Warden or running contract'}
    $script:seen.Add('running-evidence')}
Invoke-Extracted 'preconditions' $state
@{seen=@($script:seen);substage=(Get-OpProperty $state 'substage')}|ConvertTo-Json -Depth 6 -Compress
""")
    assert result['seen'][-3:]==['task-acl', 'running-evidence', 'walk-away:True'], result
    assert result['substage']=='verify_original_recovery_evidence'


@pytest.mark.parametrize('change,function', [
    ('$script:running.State=3', 'Assert-OpRunningRecoveryEvidence'),
    ('$script:running.Instances=0', 'Assert-OpRunningRecoveryEvidence'),
    ('$script:running.Instances=2', 'Assert-OpRunningRecoveryEvidence'),
    ("$script:running.LastRunTime=[DateTime]'2026-10-15T01:37:07Z'", 'Assert-OpRunningRecoveryEvidence'),
    ('$trigger.Type=8', 'Assert-OpRunningRecoveryEvidence'),
    ("$def.Principal.UserId='OTHER'", 'Assert-OpRunningRecoveryEvidence'),
    ("$script:definition='changed'", 'Assert-428WardenTask'),
    ("$script:version='4.2.7'", 'Wait-OpHealth'),   # bounded wait for a consistent 4.2.8 answer, then hold
    ("$script:records[(Join-Path $prior 'owner-result.json')].pin='0'*64", 'Open-428Pin'),
])
def test_running_evidence_holds_on_any_unverified_fact(change, function):
    result=running_evidence(change)
    assert result['held'], result
    assert result['failure']['frames'][0]['function']==function, result
    if function=='Wait-OpHealth':
        # The timeout keeps the last attempt's own sanitized failure.
        assert result['health_attempt']['substage']=='health_attempt' and result['health_attempt']['frames'], result
    assert 'running-baseline' not in result['seen'] and 'installed-payload' not in result['seen']


# --- Real running-mode actions -------------------------------------------------

RUNNING_ACTIONS=EXTRACT+r"""
$script:OpRecovery=Get-OpRunningRecoveryExpected
$script:OpPrivate='C:\fixture\fresh\private';$script:OpOldRoot='C:\fixture\old';$script:OpRoot='C:\fixture\new';$script:OpOldConfig='C:\fixture\old\pipeline.json'
$script:OpOldArgs='old-args';$script:OpOriginalXml='baseline-xml';$script:OpOriginalSddl='baseline-sddl';$script:python='C:\fixture\python.exe'
$script:targetRoot='C:\fixture\new'
$script:seen=[Collections.Generic.List[string]]::new();$script:fenced=$false;$script:count=1;$script:when=[DateTime]'2026-10-16T11:20:15Z'
$script:processes=@([pscustomobject]@{HasExited=$false;ExitTime=[DateTime]::UtcNow.AddMinutes(5)},[pscustomobject]@{HasExited=$false;ExitTime=[DateTime]::UtcNow.AddMinutes(5)})
$trigger=[pscustomobject]@{Enabled=$true};$triggers=[pscustomobject]@{trigger=$trigger};$triggers|Add-Member ScriptMethod Item {param($i)$this.trigger}
$script:task=[pscustomobject]@{Xml='live-xml';LastRunTime=$script:when;Definition=[pscustomobject]@{Triggers=$triggers};Enabled=$true}
$script:task|Add-Member ScriptMethod GetSecurityDescriptor {param($f)'live-sddl'}
$script:task|Add-Member ScriptMethod GetInstances {param($f)$c=[pscustomobject]@{Count=$script:count};$c|Add-Member ScriptMethod Item {param($i)[pscustomobject]@{InstanceGuid='instance'}};return $c}
$script:task|Add-Member ScriptMethod Stop {param($f)$script:seen.Add('stop');$script:count=0;foreach($p in $script:processes){$p.HasExited=$true}}
$script:OpFolder=[pscustomobject]@{}
$script:OpFolder|Add-Member ScriptMethod GetTask {param($n)$script:task}
$script:OpFolder|Add-Member ScriptMethod RegisterTaskDefinition {param($n,$d,$f,$u,$p,$l,$s)$script:seen.Add('disable-trigger')}
function Write-OpStatus {param($p,$s,$r,$step)}
function Get-Item {param($LiteralPath)[pscustomobject]@{Length=42}}
function Copy-VerifiedPayload {param($r)$script:seen.Add('copy-request')}
function Invoke-428Native {throw 'Forbidden installer/native launch'}
function Assert-OpRecoveryQuiescent {throw 'Whole-host inventory is not part of running recovery'}
function Assert-OpRecoveryTask {throw 'Stopped-task contract is not part of running recovery'}
function Assert-OpRecoveryRuntimeDependencies {param($b,$h)if($script:fenced){throw 'Dependencies after fence'};$script:seen.Add('runtime-dependencies')}
function Get-428Health {if($script:fenced){throw 'HTTP health under SQLite fence'};$script:seen.Add('health');[pscustomobject]@{pid=27208;instance_id='runtime'}}
function Assert-428Health {param($h,$root,$allow)}
function Open-OpProcessProof {param($h,$root,$config)if($script:fenced){throw 'Native capture after fence'};$script:seen.Add('handles');return ,$script:processes}
$script:OpCatalogRequest=@{name='task-catalog-request.json';sha256=('a'*64);request_id=('c'*32);
    previous_policy_digest=$(if('MODE' -eq 'stale_request'){'baseline'}else{'policy'});previous_task_catalog_sha256=$null}
function Start-OpFence {param($label,$s,$k)
    $script:seen.Add('ready');$script:fenced=$true
    if('MODE' -eq 'ended_at_ready'){$script:count=0;foreach($p in $script:processes){$p.HasExited=$true}}
    # Instance gone while a retained process lives on: an orphan, never accepted.
    if('MODE' -eq 'exiting_at_stop'){$script:count=0;$script:processes[0].HasExited=$true}
    $now=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $f=@{released=$false;ready=@{ready_at=$now-1;expires_at=$now+239;
        catalog=@{active_policy_sha256=$(if('MODE' -eq 'catalog_changed'){'changed'}else{'policy'});active_catalog_sha256=$null}}}
    $s[$k]=$f;return $f}
function Assert-OpFence {param($fence)if(-not $script:fenced){throw 'Fence absent'}}
function Assert-428WardenTask {param($task,$xml,$sddl,$root,$a,$enabled,$trigger,$count)if($xml -cne 'baseline-xml' -or $sddl -cne 'baseline-sddl'){throw 'Not the pinned baseline'}}
function Assert-428PortFree {$script:seen.Add('port-free')}
if('MODE' -eq 'live_xml_changed'){$script:task.Xml='edited-xml'}
# The trigger-disable update may reset the scheduler's run history (never-run),
# or a different run may appear; only the former is the same run.
$script:OpFolder|Add-Member -Force ScriptMethod RegisterTaskDefinition {param($n,$d,$f,$u,$p,$l,$s)$script:seen.Add('disable-trigger')
    if('MODE' -eq 'history_reset'){$script:task.LastRunTime=[DateTime]'1899-12-30'}
    if('MODE' -eq 'new_run_after_disable'){$script:task.LastRunTime=[DateTime]::UtcNow}}
# Stop ends the launcher but the interpreter never exits.
if('MODE' -eq 'never_exits'){$script:task|Add-Member -Force ScriptMethod Stop {param($f)$script:seen.Add('stop');$script:count=0;$script:processes[1].HasExited=$true}}
if('MODE' -eq 'stale_objects'){
    # Each GetTask is a fresh copy; a copy keeps the definition it was fetched
    # with even after its own Enabled is changed, so only a re-fetch verifies.
    $script:OpFolder|Add-Member -Force ScriptMethod GetTask {param($n)
        $c=[pscustomobject]@{Xml=$script:task.Xml;LastRunTime=$script:task.LastRunTime;
            Definition=[pscustomobject]@{Triggers=$script:task.Definition.Triggers;Settings=[pscustomobject]@{Enabled=[bool]$script:task.Enabled}}}
        $c|Add-Member ScriptProperty Enabled {[bool]$script:task.Enabled} {param($v)$script:task.Enabled=[bool]$v}
        $c|Add-Member ScriptMethod GetSecurityDescriptor {param($f)'live-sddl'}
        $c|Add-Member ScriptMethod GetInstances {param($f)$script:task.GetInstances($f)}
        $c|Add-Member ScriptMethod Stop {param($f)$script:task.Stop($f)}
        return $c}
    function Assert-428WardenTask {param($task,$xml,$sddl,$root,$a,$enabled,$trigger,$count)
        if($xml -cne 'baseline-xml' -or $sddl -cne 'baseline-sddl'){throw 'Not the pinned baseline'}
        if([bool]$task.Definition.Settings.Enabled -ne $enabled){throw 'Verified a stale task definition'}}
}
$m=@{request_sha256=('a'*64);bootstrap_sha256=('b'*64)};$Directory='C:\fixture\package'
$state=@{phase='admission_fence';old_pid=27208;old_instance='runtime';old_task_instance='instance';old_task_last_run=$script:when;stopped=$false;
    previous_task_xml='live-xml';previous_task_sddl='live-sddl';recovery_catalog=@{active_policy_sha256='policy';active_catalog_sha256=$null};verified_stopped_at_entry=$false}
if('MODE' -eq 'never_exits'){$state.previous_exit_seconds=1}
$held=$false;$failure=$null
try{foreach($name in @('offline_install','codex_preflight','admission_fence','stop_previous')){$state.phase=$name;Invoke-Extracted $name $state}}
catch{$held=$true;$failure=Get-OpFailure $_ 'fixture'}
@{held=$held;failure=$failure;seen=@($script:seen);stopped=$state.stopped;end=(Get-OpProperty $state 'previous_state_at_stop');
  exit_timeout=(Get-OpProperty $state 'previous_state_at_exit_timeout');
  enabled=$script:task.Enabled;substage=(Get-OpProperty $state 'substage')}|ConvertTo-Json -Depth 8 -Compress
"""


def running_actions(mode='normal'):
    return inert_ps(RUNNING_ACTIONS.replace('MODE', mode))


@pytest.mark.parametrize('mode,end,stops', [('normal', 'RUNNING', 1), ('ended_at_ready', 'ENDED', 0), ('stale_objects', 'RUNNING', 1),
                                            ('history_reset', 'RUNNING', 1)])
def test_real_running_actions_fence_and_stop_r4_with_live_identity_only(mode, end, stops):
    result=running_actions(mode)
    assert not result['held'], result
    assert result['stopped'] and not result['enabled'] and result['end']==end
    expected=['copy-request', 'runtime-dependencies', 'health', 'handles', 'ready', 'disable-trigger']+['stop']*stops+['port-free']
    assert result['seen']==expected, result


@pytest.mark.parametrize('mode,substage,stops', [
    ('never_exits', 'wait_previous_exit', 1),          # Stop ended the launcher; the interpreter never exits
    ('new_run_after_disable', 'stop_previous_task', 0),  # a different run is never stopped or accepted
])
def test_real_running_actions_hold_when_the_exact_run_is_not_proven_ended(mode, substage, stops):
    result=running_actions(mode)
    assert result['held'] and not result['stopped'] and result['substage']==substage, result
    assert 'disable-trigger' in result['seen'] and result['seen'].count('stop')==stops and 'port-free' not in result['seen'], result
    # A timeout records whether the run was still listed or only a process remained.
    assert result['exit_timeout']==('EXITING' if mode=='never_exits' else None), result


@pytest.mark.parametrize('mode,function,substage', [
    ('catalog_changed', 'Assert-OpRecoveryCatalog', 'recheck_catalog_authority'),
    ('live_xml_changed', '<ScriptBlock>', 'previous_task_identity'),
    ('exiting_at_stop', 'Get-OpRetainedTaskState', 'verify_retained_previous'),   # orphan: hold before any change
    # The d5d6094 cause: a request prepared against a policy the board no longer
    # has active now holds right after READY, before r4 is touched.
    ('stale_request', 'Assert-OpCatalogRequestBoard', 'recheck_catalog_request'),
])
def test_real_running_actions_hold_before_any_task_change(mode, function, substage):
    result=running_actions(mode)
    assert result['held'] and not result['stopped'] and result['enabled'], result
    assert 'disable-trigger' not in result['seen'] and 'stop' not in result['seen']
    assert result['failure']['frames'][0]['function']==function and result['substage']==substage, result


# --- Transaction: fence settlement and post-READY restore ---------------------

TRANSACTION=r"""
$script:OpRecovery=SCENARIO
$seen=[Collections.Generic.List[string]]::new()
$state=@{phase='package';stopped=$false;stop_requested=$false;cutover_requested=$false;acceptance_started=$false;acceptance_exited=$false;acceptance=$null;rollback='NOT_REQUIRED';error_type=$null;fence=$null}
$actions=@{}
foreach($name in @('preconditions','offline_install','codex_preflight','admission_fence','stop_previous','release_fence','catalog_acceptance','cutover','verify_running','enable_trigger','codex_integration')){
    $actions[$name]={param($s)$seen.Add($s.phase)}}
$actions.admission_fence={param($s)$seen.Add('admission_fence')
    $s.fence=@{completion=$null;released=$false;ready=__READY__;root=__ROOT__}
    if('__AT__' -eq 'admission_fence'){throw 'inert post-fence failure'}}
$actions.stop_previous={param($s)$seen.Add('stop_previous');if('__AT__' -eq 'stop_previous'){throw 'inert stop failure'};$s.stopped=$true}
$actions.release_fence={param($s)$seen.Add('release_fence');$s.fence.released=$true;$s.fence.completion=@{status='LOCK_RELEASED';lock_released=$true;native_exit_verified=$true}}
$actions.catalog_acceptance={param($s)$seen.Add('catalog_acceptance');$s.acceptance=__RECEIPT__;$s.acceptance_exited=$true
    if('__AT__' -eq 'catalog_acceptance'){throw 'inert catalog failure'}}
$actions.codex_integration={param($s)$seen.Add('codex_integration');if('__AT__' -eq 'codex_integration'){throw 'inert Codex failure after cutover'}}
function Release-OpFence {param($f)if($f.released -or $null -ne $f.completion){return}
    # 'fails_after_ready': settlement is the first to read ready.json, then cannot release.
    if('__REL__' -eq 'fails_after_ready'){$f.ready=@{ready_at=1};throw 'cannot release'}
    if('__REL__' -eq 'fails'){throw 'cannot release'}
    $seen.Add('release');$f.released=$true;$f.completion=@{status='LOCK_RELEASED';lock_released=$true;native_exit_verified=$true}}
function Stop-OpOwnedFenceTask {param($f,$sec)if('__STOPF__' -eq 'fails'){throw 'cannot stop'};$seen.Add('stop-owned-fence');$f.stopped_by_owner=$true
    $f.completion=@{status='STOPPED_OWNED_FENCE_TASK';lock_released=$true;native_exit_verified=$true};return $f.completion.Clone()}
function Wait-OpPreviousRuntimeSettled {param($s,$sec)$seen.Add('settle-previous');return '__PREV__'}
# The fence may publish ready.json after the release attempt and before the owner stop.
function Test-Path {param($LiteralPath)if(-not $LiteralPath.EndsWith('\ready.json')){throw 'Unexpected probe'};return ('__DISK__' -ne 'none')}
function Read-OpFenceReady {param($f)$seen.Add('read-ready-disk');if('__DISK__' -eq 'unreadable'){throw 'readiness pin differs'};$f.ready=@{ready_at=1}}
function Invoke-FixtureRestoreFailure {throw 'restored controller health did not verify'}
$actions.restore_previous={param($s)$seen.Add('restore_previous');if('__RESTORE__' -eq 'fails'){Invoke-FixtureRestoreFailure}}
$state=Invoke-OpTransaction $actions $state
$record=New-OpResultRecord $state ([pscustomobject]@{source_commit=('a'*40);request_sha256=('b'*64)}) ('c'*64)
@{rollback=$record.rollback;cleanup=$record.fence_cleanup;seen=@($seen);status=$record.status;previous=$record.previous_runtime_at_hold;
  recovery=$record.recovery_failure;recovery_type=$record.recovery_error_type}|ConvertTo-Json -Depth 6 -Compress
"""

NOT_COMMITTED="@{publication_state='NOT_COMMITTED';runtime_resources_closed=$true;publication_proof=@{catalog_probe_cleanup_verified=$true}}"


def transaction(*, running=True, ready=True, previous='ENDED', at='admission_fence', release='ok', stopfence='ok', receipt='$null',
                root='$null', disk='none', restore='ok'):
    return inert_ps(TRANSACTION.replace('SCENARIO', '(Get-OpRunningRecoveryExpected)' if running else '(Get-OpRecoveryExpected)')
        .replace('__READY__', '@{ready_at=1}' if ready else '$null').replace('__PREV__', previous).replace('__AT__', at)
        .replace('__REL__', release).replace('__STOPF__', stopfence).replace('__RECEIPT__', receipt)
        .replace('__ROOT__', root).replace('__DISK__', disk).replace('__RESTORE__', restore))


def test_a_failed_restore_keeps_its_sanitized_cause_in_the_owner_result():
    result=transaction(restore='fails')
    assert result['rollback']==HELD and result['recovery_type']=='RuntimeException', result
    assert result['recovery']['substage']=='restore_previous', result
    assert result['recovery']['frames'][0]['function']=='Invoke-FixtureRestoreFailure', result
    assert transaction()['recovery'] is None


RESTORED='PREVIOUS_RUNTIME_RESTORED_HEALTH_VERIFIED'
HELD='HELD_PRESERVE_STOPPED_OR_RUNNING_STATE'


@pytest.mark.parametrize('running,ready,previous,at,rollback', [
    (True, True, 'ENDED', 'admission_fence', RESTORED),     # r4 ended on its writer timeout after READY
    (True, True, 'RUNNING', 'admission_fence', 'NOT_REQUIRED'),  # r4 survived the released fence
    (True, True, 'UNSETTLED', 'admission_fence', HELD),     # partial exit, new run or early exit
    (True, False, 'ENDED', 'admission_fence', 'NOT_REQUIRED'),   # settled with no READY (none on disk): no fence-caused end
    (False, True, 'ENDED', 'admission_fence', 'NOT_REQUIRED'),   # stopped scenario keeps its reviewed semantics
    (True, True, 'ENDED', 'stop_previous', RESTORED),       # stop hold: fence settled first, then restored
    (True, True, 'RUNNING', 'stop_previous', HELD),         # trigger may be off: preserve and report
    (False, True, 'ENDED', 'stop_previous', HELD),          # stopped scenario: no fence settle in the catch
])
def test_post_ready_hold_settles_the_fence_then_restores_only_an_ended_r4(running, ready, previous, at, rollback):
    result=transaction(running=running, ready=ready, previous=previous, at=at)
    assert result['status']=='R428_OPERATIONAL_HELD_PRESERVE_EVIDENCE'
    assert result['rollback']==rollback, result
    assert ('restore_previous' in result['seen'])==(rollback==RESTORED), result
    judged=running and ready
    assert ('settle-previous' in result['seen'])==judged and result['previous']==(previous if judged else None), result
    if judged:
        assert result['seen'].index('release')<result['seen'].index('settle-previous'), result
    if not running and at=='stop_previous':
        assert 'release' not in result['seen'], result


@pytest.mark.parametrize('at,ready', [('stop_previous', True), ('admission_fence', True), ('admission_fence', False)])
def test_unsettled_fence_is_never_followed_by_an_old_runtime_judgement_or_restore(at, ready):
    # Before READY too: an orphaned fence would take the writer from r4 later.
    result=transaction(at=at, ready=ready, release='fails', stopfence='fails')
    assert result['cleanup']['status']=='HELD_PRESERVE_FENCE' and result['previous']=='UNSETTLED', result
    assert 'settle-previous' not in result['seen'] and 'restore_previous' not in result['seen']
    assert result['rollback']==HELD


@pytest.mark.parametrize('stopfence,previous,rollback', [
    ('ok', 'ENDED', RESTORED),     # owner stop settled it, r4 ended after READY: restore
    ('fails', 'UNSETTLED', HELD),  # never settled
])
def test_readiness_first_seen_during_settlement_still_judges_the_old_runtime(stopfence, previous, rollback):
    result=transaction(ready=False, release='fails_after_ready', stopfence=stopfence, previous='ENDED')
    assert result['previous']==previous and result['rollback']==rollback, result
    assert ('settle-previous' in result['seen'])==(stopfence=='ok')


@pytest.mark.parametrize('disk,previous,rollback', [
    ('readable', 'ENDED', RESTORED),       # READY was published before the owner stop ended the fence
    ('unreadable', 'UNSETTLED', HELD),     # a ready.json that cannot be verified is never "no READY"
    ('none', None, 'NOT_REQUIRED'),        # truly no READY on disk: no fence-caused end
])
def test_owner_stopped_fence_is_judged_by_ready_json_on_disk(disk, previous, rollback):
    result=transaction(ready=False, release='fails', root="'C:\\fixture\\private\\stop-fence-x'", disk=disk)
    assert result['cleanup']['status']=='STOPPED_OWNED_FENCE_TASK', result
    assert result['previous']==previous and result['rollback']==rollback, result
    assert ('read-ready-disk' in result['seen'])==(disk!='none')
    assert ('settle-previous' in result['seen'])==(disk=='readable')


@pytest.mark.parametrize('at', ['catalog_acceptance', 'codex_integration'])
def test_holds_after_a_verified_stop_record_the_proven_end_instead_of_rejudging(at):
    result=transaction(at=at, receipt=NOT_COMMITTED.replace('NOT_COMMITTED', 'COMMITTED'))
    assert result['previous']=='ENDED_AT_STOP' and 'settle-previous' not in result['seen'], result
    assert result['rollback']==HELD and 'restore_previous' not in result['seen']
    if at=='codex_integration':
        assert result['seen'][-1]=='codex_integration' and 'cutover' in result['seen']


@pytest.mark.parametrize('receipt,rollback', [
    ('$null', HELD),                                           # UNKNOWN publication: never restore
    (NOT_COMMITTED.replace('NOT_COMMITTED', 'COMMITTED'), HELD),  # committed catalog: never restore
    (NOT_COMMITTED.replace('$true;publication', '$false;publication'), HELD),  # resources not closed
    (NOT_COMMITTED, RESTORED),                                 # proven non-publication with closure
])
def test_catalog_hold_restores_only_with_proven_non_publication(receipt, rollback):
    result=transaction(at='catalog_acceptance', receipt=receipt)
    assert result['rollback']==rollback, result
    assert ('restore_previous' in result['seen'])==(rollback==RESTORED)


@pytest.mark.parametrize('release,stopfence,status', [
    ('ok', 'ok', 'LOCK_RELEASED'),
    ('fails', 'ok', 'STOPPED_OWNED_FENCE_TASK'),
    ('fails', 'fails', 'HELD_PRESERVE_FENCE'),
])
def test_unreleasable_owned_fence_is_stopped_not_left_to_take_the_board(release, stopfence, status):
    result=transaction(previous='RUNNING', release=release, stopfence=stopfence)
    assert result['cleanup']['status']==status, result
    if release=='fails':
        assert result['cleanup']['failure']['substage']=='fence_cleanup'


STOP_FENCE=r"""
$nonce='a'*32;$name='CoChem-4.2.8-Fence-'+$nonce;$argv='-m cochem_pipeline.owner_admission_fence_428 --nonce '+$nonce
$script:OpRoot='C:\fixture\new'
$fence=@{owned=$true;nonce=$nonce;name=$name;arguments=$argv;handle=@{name=$name;arguments=$argv;seconds=2100;sddl=$null;instance='i';started=[DateTime]::UtcNow}}
$script:inst=INST;$script:stops=0;$script:native=NATIVE;$script:kills=0
$fixtureAction=[pscustomobject]@{Type=0;Path='C:\fixture\new\.venv\Scripts\python.exe';Arguments=$argv;WorkingDirectory='C:\fixture\new'}
$fixtureActions=[pscustomobject]@{Count=1;A=$fixtureAction};$fixtureActions|Add-Member ScriptMethod Item {param($i)$this.A}
$script:task=[pscustomobject]@{Name=$fence.name;State=$(if($script:inst){4}else{3});Enabled=$true;
    LastRunTime=[DateTime]::UtcNow;LastTaskResult=$(if($script:inst){0x41301}else{2});
    Definition=[pscustomobject]@{Triggers=[pscustomobject]@{Count=0};Actions=$fixtureActions;Principal=[pscustomobject]@{UserId='SYSTEM';LogonType=5;RunLevel=1};
        Settings=[pscustomobject]@{Enabled=$true;RestartCount=0;MultipleInstances=2;AllowDemandStart=$true;ExecutionTimeLimit='PT2100S'}}}
# 'queued': Run() was accepted but the action never started; it only looks stopped.
if('MODE' -eq 'queued'){$script:task.LastRunTime=[DateTime]'1899-12-30';$script:task.LastTaskResult=0x41303}
$script:task|Add-Member ScriptMethod GetSecurityDescriptor {param($f)'s'}
$script:task|Add-Member ScriptMethod GetInstances {param($f)[pscustomobject]@{Count=$script:inst}}
$script:task|Add-Member ScriptMethod Stop {param($f)$script:stops++;if('MODE' -ne 'stuck'){$script:inst=0;$script:task.State=3;$script:task.LastTaskResult=0x41306}}
$script:OpFolder=[pscustomobject]@{};$script:OpFolder|Add-Member ScriptMethod GetTask {param($n)if($n -cne $fence.name){throw 'Unexpected task name'};$script:task}
function Assert-428TaskAcl {param($t)}
$script:releaseOnDisk=$false
function Test-Path {param($LiteralPath)if(-not $LiteralPath.EndsWith('\release.json')){throw 'Unexpected probe'};$script:releaseOnDisk}
$script:enumerations=0
function Get-OpFenceNativeRows {param($f)$script:enumerations++
    # 'vanishing': the first snapshot's row exits mid-check (Stop is asynchronous).
    if('MODE' -eq 'vanishing' -and $script:enumerations -eq 1){throw 'CimException: Not found'}
    $rows=@();for($i=0;$i -lt $script:native;$i++){$rows+=[pscustomobject]@{ProcessId=100+$i}};return $rows}
function Stop-OpFenceNative {param($row)$script:kills++
    if('MODE' -eq 'terminating' -and $script:kills -eq 1){throw 'Fence process identity changed before termination.'}
    if('MODE' -ne 'unkillable'){$script:native--}}
CHANGE
$held=$false;$status=$null
$started=[DateTime]::UtcNow
try{$status=Stop-OpOwnedFenceTask $fence BOUND}catch{$held=$true}
@{held=$held;status=(Get-OpProperty $status 'status');native=(Get-OpProperty $status 'native_exit_verified');lock=(Get-OpProperty $status 'lock_released');
  requested=(Get-OpProperty $status 'release_requested');
  stops=$script:stops;kills=$script:kills;enabled=$script:task.Enabled;owner=(Get-OpProperty $fence 'stopped_by_owner' $false);
  settled=(Test-OpFenceSettled $fence);elapsed=([DateTime]::UtcNow-$started).TotalSeconds;
  stop_failure=(Get-OpProperty $fence 'stop_failure')}|ConvertTo-Json -Depth 6 -Compress
"""


@pytest.mark.parametrize('mode,inst,native,change,held,stops,kills', [
    ('normal', 1, 0, '', False, 1, 0),
    ('normal', 0, 0, '', False, 0, 0),
    ('orphan', 1, 1, '', False, 1, 1),        # Stop left the base interpreter holding the lock
    ('vanishing', 1, 1, '', False, None, 1),  # a row exits mid-check: retried, not held
    ('terminating', 1, 1, '', False, None, 2),  # a transient kill-path failure is retried
    ('stuck', 1, 0, '', True, None, 0),
    ('unkillable', 0, 1, '', True, 0, None),
    ('queued', 0, 0, '', True, 0, 0),         # no terminal record of this run: never certified
    # The fence protocol already received release.json before the owner stop.
    ('normal', 1, 0, "$fence.root='C:\\fixture\\private\\stop-fence-x';$script:releaseOnDisk=$true", False, 1, 0),
    ('normal', 1, 0, "$fence.nonce='b'*32", True, 0, 0),
    ('normal', 1, 0, '$fence.owned=$false', True, 0, 0),
    ('normal', 1, 0, "$fixtureAction.Arguments='tampered'", True, 0, 0),
    # The task copy never verifies, yet the exact nonce processes are still ended.
    ('normal', 1, 1, "$fixtureAction.Arguments='tampered'", True, 0, None),
    ('normal', 1, 0, "$fence.handle.sddl='changed'", True, 0, 0),
])
def test_owned_fence_stop_ends_every_nonce_process_and_proves_exit(mode, inst, native, change, held, stops, kills):
    # Settlement needs two observations >= 1 s apart: success cases get room for them.
    result=inert_ps(STOP_FENCE.replace('MODE', mode).replace('INST', str(inst)).replace('NATIVE', str(native)).replace('CHANGE', change)
        .replace('BOUND', '2' if held else '6'))
    assert result['held']==held, result
    if not held:
        assert result['elapsed']>=1 and result['requested'] is ('releaseOnDisk' in change), result
    if 'handle.' in change or 'tampered' in change:
        # The refusing check is kept for the owner record (type and frames only),
        # with what the unverified passes still observed after ending nonce processes.
        failure=result['stop_failure']
        assert failure['last_pass']=='TASK_UNVERIFIED', result
        assert failure['observation']=={'task_verified': False, 'native_processes': 0}, result
        refusing='Assert-OpOneShotDefinition' if 'tampered' in change else 'Assert-OpOneShot'
        assert failure['task_exception']['frames'][0]['function']==refusing, result
        assert failure['exception']['frames'][0]['function']==refusing, result
    if mode in ('stuck', 'queued', 'unkillable'):
        # No exception: the last pass's observation says why it did not settle.
        failure=result['stop_failure']
        assert failure['last_pass']=='NOT_SETTLED' and failure['exception'] is None, result
        assert failure['observation']['terminal'] is (mode=='unkillable'), result
        assert failure['observation']['native_processes']==native, result
    if 'nonce=' in change or 'owned=' in change:
        assert result['stop_failure'] is None, result
    if stops is not None:
        assert result['stops']==stops, result
    else:
        assert result['stops']>=1, result
    if kills is not None:
        assert result['kills']==kills, result
    else:
        assert result['kills']>=1, result
    assert result['settled']==(not held), result
    if not held:
        assert result['status']=='STOPPED_OWNED_FENCE_TASK' and result['native'] is True and result['lock'] is True
        assert result['enabled'] is False and result['owner'] is True
    else:
        assert result['owner'] is False


NATIVE_ROWS=r"""
$nonce='a'*32;$argv='-I -B -m cochem_pipeline.owner_admission_fence_428 --nonce '+$nonce
$script:python='C:\fixture\base\python.exe';$script:OpRoot='C:\fixture\new'
# Rows name this inert PowerShell process (live, never touched) or a PID that
# cannot exist (2147483644): a mismatch on a live row holds, on a gone row it is skipped.
$self=[Diagnostics.Process]::GetCurrentProcess();$started=$self.StartTime.ToUniversalTime()
$fence=@{nonce=$nonce;arguments=$argv;handle=@{started=$started}}
$script:filter=$null;$gone=2147483644
$rows=@([pscustomobject]@{ProcessId=$PID;ExecutablePath='C:\fixture\new\.venv\Scripts\python.exe';CommandLine=('"launcher" '+$argv);CreationDate=$started},
        [pscustomobject]@{ProcessId=$PID;ExecutablePath=$script:python;CommandLine=('"base" '+$argv);CreationDate=$started})
CHANGE
function Get-CimInstance {param($ClassName,$Filter)$script:filter=$Filter;if('EMPTY' -eq 'yes'){return};return $rows}
function Invoke-CimMethod {param($InputObject,$MethodName)
    if($InputObject.ProcessId -eq $gone){throw 'CimException: Not found'}
    [pscustomobject]@{Sid=$(if('OWNER' -eq 'other'){'S-1-5-21-1'}else{'S-1-5-18'})}}
$held=$false;$count=$null
try{$count=@(Get-OpFenceNativeRows $fence).Count}catch{$held=$true}
@{held=$held;count=$count;filter=$script:filter;alive=(-not $self.HasExited)}|ConvertTo-Json -Compress
"""


@pytest.mark.parametrize('change,empty,owner,held,count', [
    ('', 'no', 'system', False, 2),
    ('', 'yes', 'system', False, 0),
    ("$rows[1].ExecutablePath='C:\\other\\python.exe'", 'no', 'system', True, None),
    ("$rows[0].CommandLine='other '+$nonce", 'no', 'system', True, None),
    ("$fence.handle.started=$started.AddSeconds(3)", 'no', 'system', True, None),   # live process older than the fence
    ('', 'no', 'other', True, None),
    # Exited between the snapshot and the identity read (Stop is asynchronous): skipped.
    ("$rows[1].ProcessId=$gone;$rows[1].ExecutablePath=$null", 'no', 'system', False, 1),
    ("$rows[1].ProcessId=$gone", 'no', 'system', False, 1),
    # The PID now belongs to a different (younger) process: the original is gone.
    ("$rows[1].ExecutablePath='C:\\other\\python.exe';$rows[1].CreationDate=$started.AddMinutes(-5)", 'no', 'system', False, 1),
])
def test_fence_native_rows_select_only_this_nonce_and_hold_on_any_other_identity(change, empty, owner, held, count):
    result=inert_ps(NATIVE_ROWS.replace('CHANGE', change).replace('EMPTY', empty).replace('OWNER', owner))
    assert result['held']==held and result['count']==count, result
    assert result['filter']=="CommandLine LIKE '%"+'a'*32+"%'" and result['alive'] is True


def test_fence_native_termination_checks_creation_time_before_any_kill():
    result=inert_ps(r"""
$message=$null
try{Stop-OpFenceNative ([pscustomobject]@{ProcessId=$PID;CreationDate=[DateTime]'2000-01-01T00:00:00Z'})}catch{$message=$_.Exception.Message}
$absent=$true;try{Stop-OpFenceNative ([pscustomobject]@{ProcessId=2147483644;CreationDate=[DateTime]::UtcNow})}catch{$absent=$false}
@{message=$message;absent=$absent;alive=(-not [Diagnostics.Process]::GetCurrentProcess().HasExited)}|ConvertTo-Json -Compress
""")
    assert result==dict(message='Fence process identity changed before termination.', absent=True, alive=True)


NATIVE_STOP=r"""
$script:created=[DateTime]'2026-10-16T12:00:00Z';$script:events=[Collections.Generic.List[string]]::new()
$script:same=SAME
function New-FixtureProcess {
    $p=[pscustomobject]@{HasExited=$false;StartTime=$script:created.ToLocalTime()}
    $p|Add-Member ScriptMethod get_Handle {$script:events.Add('pinned');[IntPtr]42}
    $p|Add-Member ScriptMethod get_HasExited {$this.HasExited}
    $p|Add-Member ScriptMethod get_StartTime {$this.StartTime}
    $p|Add-Member ScriptMethod Kill {$script:events.Add('kill');if('MODE' -eq 'terminating'){throw 'Access is denied (terminating)'};$this.HasExited=$true}
    $p|Add-Member ScriptMethod WaitForExit {param($ms)$script:events.Add('wait');if('MODE' -eq 'terminating'){$this.HasExited=$true};return $this.HasExited}
    $p|Add-Member ScriptMethod Dispose {$script:events.Add('dispose')}
    return $p
}
# 'protected': a real, unassociated .NET Process object (starts nothing) whose
# Handle getter genuinely throws, as opening a protected process does.
function Get-OpProcessById {param($id)if('MODE' -eq 'gone'){return $null};if('MODE' -eq 'protected'){return [Diagnostics.Process]::new()};return (New-FixtureProcess)}
function Test-OpSameLiveProcess {param($row)$script:events.Add('same-check');return $script:same}
$row=[pscustomobject]@{ProcessId=1234;CreationDate=CREATED}
$message=$null;try{Stop-OpFenceNative $row}catch{$message=$_.Exception.Message}
@{message=$message;events=@($script:events)}|ConvertTo-Json -Compress
"""


@pytest.mark.parametrize('mode,same,created,message,events', [
    ('normal', '$false', '$script:created', None, ['pinned', 'kill', 'wait', 'dispose']),
    ('terminating', '$false', '$script:created', None, ['pinned', 'kill', 'wait', 'dispose']),   # exit proven by the wait
    ('normal', '$false', '$script:created.AddMinutes(-5)', 'Fence process identity changed before termination.', ['pinned', 'dispose']),
    ('protected', '$true', '$script:created', 'No process is associated', ['same-check']),   # cannot pin a live one: hold
    ('protected', '$false', '$script:created', None, ['same-check']),                        # it is gone: nothing to end
    ('gone', '$false', '$script:created', None, []),
])
def test_fence_native_termination_pins_one_handle_before_any_kill(mode, same, created, message, events):
    result=inert_ps(NATIVE_STOP.replace('MODE', mode).replace('SAME', same).replace('CREATED', created))
    assert result['events']==events, result
    assert (result['message'] or None)==message or (message and message in result['message']), result


def test_windows_powershell_hides_property_getter_failures_so_process_checks_use_get_methods():
    # A real, unassociated Process object (starts nothing): every getter fails.
    result=inert_ps(r"""
$p=[Diagnostics.Process]::new()
$property=$null;try{$property=($null -eq $p.Handle)}catch{$property='threw'}
$method=$null;try{$null=$p.get_Handle();$method='returned'}catch{$method='threw'}
function Get-OpProcessById {param($id)return [Diagnostics.Process]::new()}
$same=Test-OpSameLiveProcess ([pscustomobject]@{ProcessId=1234;CreationDate=[DateTime]::UtcNow})
@{property_is_null=$property;method=$method;unanswerable_is_same=$same}|ConvertTo-Json -Compress
""")
    # The property silently reads as $null; only the method throws. An unanswerable
    # liveness question must never be read as "gone" (that would skip a hold).
    assert result==dict(property_is_null=True, method='threw', unanswerable_is_same=True)


READY_ON_DISK=r"""
$script:OpRecovery=Get-OpRunningRecoveryExpected
$script:OpPrivate='C:\fixture\private';$script:OpOldConfig='C:\fixture\old\pipeline.json'
$script:OpManifest=@{previous_config_sha256=('a'*64);request_sha256=('b'*64)}
$nonce='c'*32;$root=Join-Path $script:OpPrivate ('stop-fence-'+$nonce)
$argv='-I -B -m cochem_pipeline.owner_admission_fence_428 --config "'+$script:OpOldConfig+'" --config-sha256 '+('a'*64)+
    ' --output-root "'+$root+'" --nonce '+$nonce+' --request-sha256 '+('b'*64)+' --wait-seconds 1800 --hold-seconds 240'
$intent=[DateTime]::UtcNow.AddMinutes(-1)
$seen=[Collections.Generic.List[string]]::new()
$state=@{phase='package';stopped=$false;stop_requested=$false;cutover_requested=$false;acceptance_started=$false;acceptance_exited=$false;acceptance=$null;rollback='NOT_REQUIRED';error_type=$null;fence=$null}
$actions=@{}
foreach($name in @('preconditions','offline_install','codex_preflight','admission_fence','stop_previous','release_fence','catalog_acceptance','cutover','verify_running','enable_trigger','codex_integration')){
    $actions[$name]={param($s)$seen.Add($s.phase)}}
# The fence published READY after the release attempt and before the owner stop ended it.
$actions.admission_fence={param($s)$seen.Add('admission_fence')
    $s.fence=@{root=$root;nonce=$nonce;arguments=$argv;name=('CoChem-4.2.8-Fence-'+$nonce);intent_at=$intent;owned=$true;
        handle=@{name=('CoChem-4.2.8-Fence-'+$nonce);arguments=$argv;instance='i';started=$intent.AddSeconds(1)};ready=$null;ready_pin=PIN;released=$false;process=$null;completion=$null}
    throw 'inert pre-READY failure'}
function Release-OpFence {param($f)throw 'ready.json was not there yet'}
function Stop-OpOwnedFenceTask {param($f,$sec)$seen.Add('stop-owned-fence');$f.stopped_by_owner=$true
    $f.completion=@{status='STOPPED_OWNED_FENCE_TASK';lock_released=$true;native_exit_verified=$true;release_requested=$false};return $f.completion.Clone()}
function Test-Path {param($LiteralPath)if($LiteralPath -cne (Join-Path $root 'ready.json')){throw 'Unexpected probe'};return $true}
# Real Read-OpFenceReady and Assert-OpOwnedFence; only file access is inert.
function Assert-ProtectedPath {param($p)}
function Get-428FileSha256 {param($p)return ('d'*64)}
function Open-428Pin {param($p,$h)if($h -cne ('d'*64)){throw 'pin'};[IO.MemoryStream]::new()}
function Read-428Json {param($s)$seen.Add('ready-read');[pscustomobject]@{status='WRITER_FENCE_HELD';ready_at=1}}
function Wait-OpPreviousRuntimeSettled {param($s,$sec)$seen.Add('settle-previous:'+$s.fence.ready.ready_at);return 'ENDED'}
$actions.restore_previous={param($s)$seen.Add('restore_previous')}
$state=Invoke-OpTransaction $actions $state
$record=New-OpResultRecord $state ([pscustomobject]@{source_commit=('a'*40);request_sha256=('b'*64)}) ('c'*64)
@{rollback=$record.rollback;previous=$record.previous_runtime_at_hold;seen=@($seen)}|ConvertTo-Json -Compress
"""


@pytest.mark.parametrize('pin,previous,rollback', [
    ('$null', 'ENDED', RESTORED),             # readable and bound to this exact owned fence: judged
    ("('d'*64)", 'ENDED', RESTORED),
    ("('e'*64)", 'UNSETTLED', HELD),          # readiness bytes differ from what this sitting saw
])
def test_ready_json_on_disk_is_read_through_the_real_owned_fence_checks(pin, previous, rollback):
    result=inert_ps(READY_ON_DISK.replace('PIN', pin))
    assert result['previous']==previous and result['rollback']==rollback, result
    assert ('settle-previous:1' in result['seen'])==(previous=='ENDED'), result
    assert 'stop-owned-fence' in result['seen'] and 'ready-read' in result['seen']


RESTORE_FENCE=r"""
$script:OpRecovery=Get-OpRunningRecoveryExpected
$seen=[Collections.Generic.List[string]]::new()
$state=@{status='R428_OPERATIONAL_HELD_PRESERVE_EVIDENCE';phase='catalog_acceptance';rollback='NOT_REQUIRED';
    fence=@{released=$true;completion=@{status='LOCK_RELEASED';lock_released=$true;native_exit_verified=$true}};restore_fence=$null;
    acceptance_started=$true;acceptance_exited=$true;cutover_requested=$false;
    acceptance=@{publication_state='NOT_COMMITTED';runtime_resources_closed=$true;publication_proof=@{catalog_probe_cleanup_verified=$true}}}
# The restore fence's one-shot runs, then the launcher fails before READY.
function Start-OpFence {param($label,$s,$key)$s[$key]=@{owned=$true;ready=$null;released=$false;completion=$null};throw 'transient scheduler error before READY'}
function Release-OpFence {param($f)$seen.Add('release-restore-fence');if($null -eq $f.ready){throw 'no ready.json yet'}}
function Stop-OpOwnedFenceTask {param($f,$sec)$seen.Add('stop-restore-fence');if('__STOP__' -eq 'fails'){throw 'cannot stop'}
    $f.completion=@{status='STOPPED_OWNED_FENCE_TASK';lock_released=$true;native_exit_verified=$true;release_requested=$false};return $f.completion.Clone()}
$message=$null;try{Restore-OpPrevious $state 1}catch{$message=$_.Exception.Message}
$record=New-OpResultRecord $state ([pscustomobject]@{source_commit=('a'*40);request_sha256=('b'*64)}) ('c'*64)
@{message=$message;seen=@($seen);cleanup=$record.restore_fence_cleanup}|ConvertTo-Json -Depth 6 -Compress
"""


@pytest.mark.parametrize('stop,status', [('ok', 'STOPPED_OWNED_FENCE_TASK'), ('fails', 'HELD_PRESERVE_FENCE')])
def test_restore_fence_failing_before_ready_is_settled_not_left_to_take_the_writer(stop, status):
    result=inert_ps(RESTORE_FENCE.replace('__STOP__', stop))
    assert result['message']=='transient scheduler error before READY', result
    assert result['seen']==['release-restore-fence', 'stop-restore-fence'], result
    assert result['cleanup']['status']==status and result['cleanup']['failure']['substage']=='restore_fence_cleanup', result


@pytest.mark.parametrize('completion,settled', [
    ('$null', False),
    ("@{status='LOCK_RELEASED';lock_released=$true;native_exit_verified=$true}", True),
    ("@{status='STOPPED_OWNED_FENCE_TASK';lock_released=$null;native_exit_verified=$false}", False),
    ("@{status='LOCK_RELEASED';lock_released=$true;native_exit_verified=$false}", False),
])
def test_fence_settlement_requires_released_lock_and_proven_exit(completion, settled):
    result=inert_ps(r"""@{none=(Test-OpFenceSettled $null);fence=(Test-OpFenceSettled @{completion=COMPLETION})}|ConvertTo-Json -Compress"""
        .replace('COMPLETION', completion))
    assert result==dict(none=True, fence=settled)


# --- Old-runtime judgement after a post-READY hold ------------------------------

SETTLE=r"""
$script:when=[DateTime]'2026-10-16T11:20:15Z';$ready=([DateTimeOffset]$script:when.AddMinutes(10)).ToUnixTimeSeconds()
$script:polls=0;$script:count=COUNT
$script:processes=@([pscustomobject]@{HasExited=EXIT0;ExitTime=$script:when.AddMinutes(11)},[pscustomobject]@{HasExited=EXIT1;ExitTime=$script:when.AddMinutes(11)})
$script:task=[pscustomobject]@{LastRunTime=$script:when}
$script:task|Add-Member ScriptMethod GetInstances {param($f)$script:polls++
    if('MODE' -eq 'late_exit' -and $script:polls -ge 2){$script:processes[1].HasExited=$true}
    $c=[pscustomobject]@{Count=$script:count};$c|Add-Member ScriptMethod Item {param($i)[pscustomobject]@{InstanceGuid='GUID'}};$c}
$script:OpFolder=[pscustomobject]@{};$script:OpFolder|Add-Member ScriptMethod GetTask {param($n)if($n -cne 'CoChem-4.2.7-Warden'){throw 'Unexpected task'};$script:task}
$script:OpOldRoot='C:\fixture\old';$script:health=0;$script:healthMode='serving'
function Get-428Health {$script:health++
    if($script:healthMode -eq 'unreachable'){throw 'health timeout'}
    $instance=if($script:healthMode -eq 'replaced' -and $script:health -eq 2){'other'}else{'runtime'}
    if($script:healthMode -eq 'exits_after' -and $script:health -eq 2){$script:processes[0].HasExited=$true}
    [pscustomobject]@{pid=27208;instance_id=$instance;process_started_at='2026-10-16T11:20:16Z';ready=($script:healthMode -ne 'not_admitting')}}
function Assert-428Health {param($h,$root,$allow)if($root -cne 'C:\fixture\old' -or $allow){throw 'Wrong health contract'};if(-not $h.ready){throw 'admission not ready'}}
CHANGE
$state=@{processes=$script:processes;old_pid=27208;old_instance='runtime';old_task_instance='instance';old_task_last_run=$script:when;fence=@{ready=@{ready_at=$ready}}}
CHANGE2
@{result=(Wait-OpPreviousRuntimeSettled $state BOUND);health=$script:health}|ConvertTo-Json -Compress
"""


@pytest.mark.parametrize('mode,count,exit0,exit1,guid,change,change2,expected', [
    ('ended', 0, True, True, 'instance', '', '', 'ENDED'),
    ('late_exit', 0, True, False, 'instance', '', '', 'ENDED'),              # instance ends just before its processes
    ('running', 1, False, False, 'instance', '', '', 'RUNNING'),
    ('partial', 1, True, False, 'instance', '', '', 'UNSETTLED'),            # one process gone, run still listed
    ('orphan', 0, True, False, 'instance', '', '', 'UNSETTLED'),             # never completes within the bound
    ('early', 0, True, True, 'instance', '$script:processes[0].ExitTime=$script:when', '', 'UNSETTLED'),
    ('new_run', 1, True, True, 'other', '$script:task.LastRunTime=$script:when.AddMinutes(12)', '', 'UNSETTLED'),
    ('other_instance', 1, False, False, 'other', '', '', 'UNSETTLED'),
    ('no_ready', 0, True, True, 'instance', '', '$state.fence.ready=$null', 'UNSETTLED'),
    # Still listed and alive is not enough: the exact old controller must keep serving.
    ('health_unreachable', 1, False, False, 'instance', "$script:healthMode='unreachable'", '', 'UNSETTLED'),
    ('health_replaced', 1, False, False, 'instance', "$script:healthMode='replaced'", '', 'UNSETTLED'),
    ('not_admitting', 1, False, False, 'instance', "$script:healthMode='not_admitting'", '', 'UNSETTLED'),
    ('exits_during_proof', 1, False, False, 'instance', "$script:healthMode='exits_after'", '', 'UNSETTLED'),
])
def test_old_runtime_judgement_accepts_only_the_exact_run_ending_after_ready(mode, count, exit0, exit1, guid, change, change2, expected):
    ps=lambda v: '$true' if v else '$false'
    result=inert_ps(SETTLE.replace('MODE', mode).replace('COUNT', str(count)).replace('EXIT0', ps(exit0)).replace('EXIT1', ps(exit1))
        .replace('GUID', guid).replace('CHANGE2', change2).replace('CHANGE', change)
        .replace('BOUND', '5' if mode=='late_exit' else '1'))   # late_exit needs a second poll; it returns on ENDED
    assert result['result']==expected, result
    # Health is consulted only for a candidate RUNNING verdict, after the bound.
    assert (result['health']>0)==(count==1 and not exit0 and not exit1 and guid=='instance'), result


# --- Start-OpFence and one-shot identity --------------------------------------

START_FENCE=r"""
$script:OpPrivate='C:\fixture\private';$script:OpOldConfig='C:\fixture\old\pipeline.json';$script:OpScheduler=$null;$script:OpFolder=$null
$script:OpManifest=@{previous_config_sha256=('a'*64);request_sha256=('b'*64)}
$script:obs=0;$script:pattern=@(PATTERN)
function New-OpPrivateDirectory {param($p)}
function Write-OpRecord {param($p,$r)}
function Write-OpStatus {param($p,$s,$r,$step)}
function New-OpOneShot {param($sch,$f,$n,$a,$s)@{name=$n;instance='i';arguments=$a;xml='x';sddl='s';started=[DateTime]::UtcNow}}
function Assert-OpOneShot {param($h,$r)
    $script:obs++;$term=$script:obs -le $script:pattern.Count -and $script:pattern[$script:obs-1]
    $t=[pscustomobject]@{State=$(if($term){3}else{4});LastTaskResult=$(if($term){2}else{0x41301});LastRunTime=[DateTime]::UtcNow}
    $t|Add-Member ScriptMethod GetInstances {param($f)[pscustomobject]@{Count=$(if($this.State -eq 3){0}else{1})}};return $t}
function Test-Path {param($LiteralPath)return ($script:obs -ge READYAFTER)}
function Read-OpFenceReady {param($f)$f.ready=@{ready_at=1}}
function Assert-OpFence {param($f)}
$state=@{phase='admission_fence'};$message=$null
try{$null=Start-OpFence 'stop-fence' $state 'fence';$ok=$true}catch{$ok=$false;$message=$_.Exception.Message}
@{ok=$ok;message=$message;observations=$script:obs}|ConvertTo-Json -Compress
"""


@pytest.mark.parametrize('pattern,ready_after,ok,observations', [
    ('$true,$false,$false', 3, True, 3),        # one transient terminal-looking observation
    ('$true,$false,$true,$false', 4, True, 4),  # never twice in a row
    ('$true,$true,$true', 99, False, 2),        # two consecutive terminal observations >= 1 s apart
])
def test_fence_wait_needs_two_consecutive_terminal_observations(pattern, ready_after, ok, observations):
    result=inert_ps(START_FENCE.replace('PATTERN', pattern).replace('READYAFTER', str(ready_after)))
    assert result['ok']==ok and result['observations']==observations, result
    if not ok:
        assert result['message']=='Admission fence ended without readiness.'


# One-shot identity (structural definition, ACL, fresh-copy descriptor baseline,
# instance) is covered against a Task Scheduler model in
# test_operational_oneshot_identity_428.py, including the exact ab900e9 hold.


# --- Restore-OpPrevious in the running scenario --------------------------------

RESTORE=r"""
$script:OpRecovery=SCENARIO
$script:OpOldRoot='C:\fixture\old';$script:OpOldConfig='C:\fixture\old\pipeline.json';$script:OpOldArgs='old-args'
$script:OpOriginalXml='baseline-xml';$script:OpOriginalSddl='baseline-sddl';$script:OpManifest=@{previous_config_sha256=('a'*64)}
$script:seen=[Collections.Generic.List[string]]::new();$script:inst=0;$script:busy=0;$script:lingering=0
$trigger=[pscustomobject]@{Enabled=TRIG};$triggers=[pscustomobject]@{Count=1;t=$trigger};$triggers|Add-Member ScriptMethod Item {param($i)$this.t}
$script:task=[pscustomobject]@{Enabled=ENABLED;Definition=[pscustomobject]@{Triggers=$triggers}}
$script:task|Add-Member ScriptMethod GetInstances {param($f)
    $n=$script:inst;if($script:lingering -gt 0){$script:lingering--;$n=1}
    $c=[pscustomobject]@{Count=$n};$c|Add-Member ScriptMethod Item {param($i)[pscustomobject]@{InstanceGuid='new'}};$c}
$script:task|Add-Member ScriptMethod Run {param($a)$script:seen.Add('run');$script:inst=1;[pscustomobject]@{InstanceGuid='new'}}
$script:OpFolder=[pscustomobject]@{};$script:OpFolder|Add-Member ScriptMethod GetTask {param($n)$script:task}
$script:OpFolder|Add-Member ScriptMethod RegisterTaskDefinition {param($n,$d,$f,$u,$p,$l,$s)$script:seen.Add('register:'+[string]$d.Triggers.Item(1).Enabled)}
$script:OpScheduler=[pscustomobject]@{}
$script:OpScheduler|Add-Member ScriptMethod NewTask {param($f)$nt=[pscustomobject]@{Enabled=$true};$tt=[pscustomobject]@{t=$nt};$tt|Add-Member ScriptMethod Item {param($i)$this.t};[pscustomobject]@{XmlText='';Triggers=$tt}}
function Assert-428PortFree {if($script:busy -gt 0){$script:busy--;throw 'port still bound'};$script:seen.Add('port-free')}
function Assert-428WardenTask {param($t,$x,$s,$r,$a,$e,$tr,$c)$script:seen.Add('assert:'+$e+':'+$tr)}
function Open-428Pin {param($p,$h)[IO.MemoryStream]::new()}
function Wait-OpHealth {param($r,$p,$s)$script:seen.Add('health:'+$s);[pscustomobject]@{pid=1}}
function Open-OpProcessProof {param($h,$r,$c)$script:seen.Add('proof');return ,@()}
function Release-OpFence {param($f)$script:seen.Add('release')}
$state=@{fence=$null;acceptance_started=$false;restore_fence=$null}
CHANGE
$message=$null
try{Restore-OpPrevious $state CLEAR}catch{$message=$_.Exception.Message}
@{seen=@($script:seen);message=$message}|ConvertTo-Json -Compress
"""


def restore(scenario='(Get-OpRunningRecoveryExpected)', enabled=True, trigger=True, change='', clear=10):
    ps=lambda v: '$true' if v else '$false'
    return inert_ps(RESTORE.replace('SCENARIO', scenario).replace('ENABLED', ps(enabled)).replace('TRIG', ps(trigger))
        .replace('CHANGE', change).replace('CLEAR', str(clear)))


@pytest.mark.parametrize('enabled,trigger,expected', [
    (True, True, ['port-free', 'assert:True:True', 'run', 'health:1200', 'proof', 'assert:True:True']),
    (True, False, ['port-free', 'assert:True:False', 'register:False', 'assert:True:False', 'run', 'health:1200', 'proof',
                   'register:True', 'assert:True:True']),
    (False, False, ['port-free', 'assert:False:False', 'register:False', 'assert:True:False', 'run', 'health:1200', 'proof',
                    'register:True', 'assert:True:True']),
])
def test_running_restore_reruns_an_untouched_warden_and_reenables_a_disabled_one(enabled, trigger, expected):
    result=restore(enabled=enabled, trigger=trigger)
    assert result['message'] is None and result['seen']==expected, result


def test_stopped_scenario_restore_keeps_the_reviewed_disabled_task_requirement():
    result=restore('(Get-OpRecoveryExpected)')
    assert result['seen'][:3]==['port-free', 'assert:False:False', 'register:False'], result


def test_restore_waits_briefly_for_the_old_instance_and_listener_to_clear():
    result=restore(change='$script:busy=2;$script:lingering=2')
    # Two bound-port checks, then two lingering-instance checks with a free port.
    assert result['message'] is None and result['seen'][:5]==['port-free']*3+['assert:True:True', 'run'], result


def test_restore_holds_when_the_old_controller_never_clears():
    result=restore(change='$script:inst=1', clear=2)
    assert result['message']=='A controller instance or listener remains; preserve state.' and 'run' not in result['seen'], result


@pytest.mark.parametrize('fence,message,released', [
    ("@{released=$false;completion=$null}", 'Stop fence is not verifiably settled; restoration would contend with it.', True),
    ("@{released=$false;stopped_by_owner=$true;completion=@{lock_released=$null;native_exit_verified=$false}}",
     'Stop fence is not verifiably settled; restoration would contend with it.', False),
    ("@{released=$false;stopped_by_owner=$true;completion=@{lock_released=$true;native_exit_verified=$true}}", None, False),
])
def test_restore_requires_a_released_or_verifiably_stopped_fence(fence, message, released):
    result=restore(change='$state.fence='+fence)
    assert result['message']==message, result
    assert ('release' in result['seen'])==released
    assert ('run' in result['seen'])==(message is None)


# --- Codex settings drift -------------------------------------------------------

CODEX_FILES={'config': '.codex/config.toml', 'rules': '.codex/AGENTS.md',
             'skill': '.agents/skills/codex-pipeline/SKILL.md', 'metadata': '.agents/skills/codex-pipeline/agents/openai.yaml'}


def codex_home(tmp_path):
    home=tmp_path/'home';expected={}
    for key, relative in CODEX_FILES.items():
        path=home/relative;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(('pinned '+key).encode())
        expected[key]=hashlib.sha256(('pinned '+key).encode()).hexdigest()
    # Shaped like the packaged manifest: Python json.dumps(indent=2), templates included.
    manifest=dict(schema='cochem-codex-integration-update/1', source_commit='e'*40, user_home=str(home),
        runtime_root='C:\\Program Files\\CoChem\\Pipeline4.2.8-windows-20261015-r5',
        client_config='C:\\Users\\ansac\\CoChem427\\pipeline-client-r3.json', expected=expected,
        templates=dict(rules='# rules\n', skill='---\nname: codex-pipeline\n---\n', metadata='interface: {}\n'),
        refresh_required=True, provider_commands_executed=0, other_integrations_changed=False)
    return home, manifest, json.dumps(manifest, indent=2).encode()


LIVE_MANIFEST=r"""
$script:OpPrivate='PRIVATE'
function Write-OpPrivateBytes {param($p,$b)if((Split-Path -Parent $p) -cne $script:OpPrivate){throw 'Outside private'};[IO.File]::WriteAllBytes($p,$b)}
$raw=[IO.File]::ReadAllBytes('RAW');$integration=[Text.Encoding]::UTF8.GetString($raw)|ConvertFrom-Json
$result=$null;$message=$null
try{$result=New-OpCodexLiveManifest $raw $integration 'codex-integration-preflight.json'}catch{$message=$_.Exception.Message}
@{result=$result;message=$message}|ConvertTo-Json -Compress
"""


def live_manifest(tmp_path, raw):
    private=tmp_path/'private';private.mkdir()
    (tmp_path/'raw.json').write_bytes(raw)
    return inert_ps(LIVE_MANIFEST.replace('PRIVATE', str(private)).replace('RAW', str(tmp_path/'raw.json'))), private


@pytest.mark.parametrize('rewritten', [False, True])
def test_codex_live_manifest_rebinds_only_the_config_digest_captured_now(tmp_path, rewritten):
    home, manifest, raw=codex_home(tmp_path)
    if rewritten:
        (home/CODEX_FILES['config']).write_bytes(b'[mcp_servers."cochem-pipeline"]\n# Codex rewrote this after sign-in\n')
    result, private=live_manifest(tmp_path, raw)
    assert result['message'] is None, result
    written=(private/'codex-integration-preflight.json').read_bytes()
    assert result['result']['path']==str(private/'codex-integration-preflight.json')
    assert result['result']['sha256']==hashlib.sha256(written).hexdigest()
    assert result['result']['config_recaptured'] is rewritten
    live=hashlib.sha256((home/CODEX_FILES['config']).read_bytes()).hexdigest()
    assert written==raw.replace(manifest['expected']['config'].encode(), live.encode())
    expected=dict(manifest, expected=dict(manifest['expected'], config=live))
    assert json.loads(written)==expected


@pytest.mark.parametrize('case,message', [
    ('rules_changed', 'Codex managed integration files changed since preparation; hold.'),
    ('skill_changed', 'Codex managed integration files changed since preparation; hold.'),
    ('metadata_missing', 'A Codex integration target is missing.'),
    ('pin_repeated', 'Codex configuration pin is not unique in the reviewed manifest.'),
    ('pin_malformed', 'Codex configuration pin is malformed.'),
])
def test_codex_live_manifest_holds_before_writing_on_any_other_change(tmp_path, case, message):
    home, manifest, raw=codex_home(tmp_path)
    if case=='rules_changed': (home/CODEX_FILES['rules']).write_bytes(b'edited rules')
    if case=='skill_changed': (home/CODEX_FILES['skill']).write_bytes(b'edited skill')
    if case=='metadata_missing': (home/CODEX_FILES['metadata']).unlink()
    if case=='pin_repeated':
        # The digest also appears as another quoted value: replacement is ambiguous.
        manifest['templates']['rules']=manifest['expected']['config'];raw=json.dumps(manifest, indent=2).encode()
    if case=='pin_malformed':
        manifest['expected']['config']='not-a-digest';raw=json.dumps(manifest, indent=2).encode()
    result, private=live_manifest(tmp_path, raw)
    assert result['message']==message, result
    assert list(private.iterdir())==[]


def test_codex_live_manifest_reads_settings_codex_holds_open(tmp_path):
    home, manifest, raw=codex_home(tmp_path)
    with open(home/CODEX_FILES['config'], 'ab'):
        result, _=live_manifest(tmp_path, raw)
    assert result['message'] is None and result['result']['config_recaptured'] is False, result


CODEX_PHASES=EXTRACT+r"""
$script:OpRecovery=SCENARIO;$script:OpRoot='C:\Program Files\CoChem\Pipeline4.2.8-windows-20261015-r5';$script:OpPrivate='C:\fixture\private'
$script:targetRoot=$script:OpRoot
$script:seen=[Collections.Generic.List[string]]::new()
$m=[pscustomobject]@{integration_manifest='codex-integration.json';integration_sha256=('d'*64);source_commit=('e'*40)}
$Directory='C:\fixture\package';$pins=[Collections.Generic.List[IO.Stream]]::new()
function Write-OpStatus {param($p,$s,$r,$step)}
function Open-428Pin {param($p,$h)if($p -cne 'C:\fixture\package\codex-integration.json' -or $h -cne ('d'*64)){throw 'Unpinned manifest'};[IO.MemoryStream]::new([byte[]](1,2,3))}
function Read-428Json {param($s)[pscustomobject]@{schema='cochem-codex-integration-update/1';source_commit=('e'*40);user_home='C:\Users\ansac';
    runtime_root=$script:OpRoot;client_config='C:\Users\ansac\CoChem427\pipeline-client-r3.json';expected=[pscustomobject]@{}}}
function New-OpCodexLiveManifest {param($raw,$i,$name)if(@($raw).Count -ne 3){throw 'Not the pinned bytes'}
    if('LIVE' -eq 'holds'){throw 'Codex managed integration files changed since preparation; hold.'}
    # Unchanged at preflight; Codex rewrites config.toml before apply.
    $apply=$name -ceq 'codex-integration-apply.json'
    $script:seen.Add('live:'+$name);@{path=('C:\fixture\private\'+$name);sha256=$(if($apply){'9'*64}else{'f'*64});config_recaptured=$apply}}
function Copy-VerifiedPayload {param($r)$script:seen.Add('copy-integration')}
function Get-Item {param($LiteralPath)[pscustomobject]@{Length=42}}
function Invoke-428Native {param($exe,$argv,$label,$seconds)$script:seen.Add('native:'+$label+':'+[IO.Path]::GetFileName($argv[5])+':'+$argv[7]+':'+($argv.Count -eq 9 -and $argv[8] -ceq '--apply'))}
function Read-OpPrivateRecord {param($p)
    if($p.EndsWith('codex-preflight.stdout.log')){return [pscustomobject]@{status='CODEX_UPDATE_PLAN_VERIFIED';files_changed=0}}
    return [pscustomobject]@{status='CODEX_INTEGRATION_UPDATED_REFRESH_REQUIRED';current_session_tools_loaded=$false}}
$state=@{phase='codex_preflight';integration=$null;status='fixture';rollback='NOT_REQUIRED';acceptance=$null;cutover_requested=$false}
$held=$false;try{Invoke-Extracted 'codex_preflight' $state;$state.phase='codex_integration';Invoke-Extracted 'codex_integration' $state}catch{$held=$true}
$record=New-OpResultRecord $state ([pscustomobject]@{source_commit=('a'*40);request_sha256=('b'*64)}) ('c'*64)
@{held=$held;seen=@($script:seen);status=$record.codex_integration_status;refresh=$record.codex_session_refresh_required;
  recaptured=$record.codex_config_recaptured;digests=$record.codex_manifest_sha256;substage=(Get-OpProperty $state 'substage')}|ConvertTo-Json -Compress
"""


def test_recovery_integrates_codex_with_settings_captured_before_plan_and_again_before_apply():
    result=inert_ps(CODEX_PHASES.replace('SCENARIO', '(Get-OpRunningRecoveryExpected)').replace('LIVE', 'ok'))
    assert not result['held'], result
    assert result['seen']==['live:codex-integration-preflight.json', 'native:codex-preflight:codex-integration-preflight.json:'+'f'*64+':False',
                            'live:codex-integration-apply.json', 'native:codex-integration:codex-integration-apply.json:'+'9'*64+':True'], result
    assert 'copy-integration' not in result['seen']
    assert result['status']=='CODEX_INTEGRATION_UPDATED_REFRESH_REQUIRED' and result['refresh'] is True
    # The apply-time re-capture is reported even though preflight matched the pin.
    assert result['recaptured'] is True and result['digests']==dict(preflight='f'*64, apply='9'*64)
    assert result['substage']=='codex_apply'


def test_recovery_holds_codex_preflight_before_any_host_change_when_managed_files_changed():
    result=inert_ps(CODEX_PHASES.replace('SCENARIO', '(Get-OpRunningRecoveryExpected)').replace('LIVE', 'holds'))
    assert result['held'] and result['seen']==[], result
    assert result['substage']=='codex_capture_live_settings' and result['status']=='NOT_APPLIED'


def test_fresh_path_codex_phases_keep_the_packaged_manifest_and_pin():
    result=inert_ps(CODEX_PHASES.replace('SCENARIO', '$null').replace('LIVE', 'ok'))
    assert not result['held'], result
    assert result['seen']==['copy-integration', 'native:codex-preflight:codex-integration.json:'+'d'*64+':False',
                            'native:codex-integration:codex-integration.json:'+'d'*64+':True'], result
    assert result['status']=='CODEX_INTEGRATION_UPDATED_REFRESH_REQUIRED' and result['recaptured'] is None and result['digests'] is None
