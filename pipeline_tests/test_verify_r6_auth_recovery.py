import json
import hashlib
from pathlib import Path

import pytest

from pipeline_tests import test_install_r6_runtime as ps_fixture


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(ps_fixture,'SCRIPT',Path(__file__).parents[1]/'scripts/verify_r6_auth_recovery.ps1')
    return ps_fixture.run_ps


@pytest.mark.parametrize('mutation', ['', 'stderr', 'helper', 'phase', 'cleanup', 'cutover', 'restored',
    'task_state', 'task_instances', 'task_result', 'task_arguments', 'task_duration', 'task_acl'])
def test_reviewed_prefix_failure_requires_exact_evidence_and_terminal_task(run_ps, mutation):
    phase=str(Path(__file__).parents[1]/'scripts/run_r6_system_phase.ps1').replace("'", "''")
    result = run_ps(r'''
$script:base='C:\fixture';$script:targetRoot='C:\fixture\r6'
$root=Join-Path $script:base 'R6Acceptance4.2.7-windows-20261012-v1-auth-226ce1d64f29486c838fca043f6bf904'
$script:events=[Collections.Generic.List[string]]::new()
function Read-R6RecoveryJson {param($Path,$Hash)
  if($Path -like '*result.json'){
    $rows=@();foreach($i in 1..6){foreach($p in @('codex','claude','gemini')){
      $row=@{worker=('slot'+$i);provider=$p;authenticated=($p -ne 'gemini');cleanup_verified=('MUTATION' -ne 'cleanup');
        status=$(if($p -eq 'gemini'){'STATUS_UNVERIFIED'}else{'REUSE_VERIFIED_SESSION'});exit_code=$(if($p -eq 'gemini'){1}else{0})}
      if($p -eq 'gemini'){$row.stdout_bytes=0;$row.stderr_bytes=122;$row.reason='AGY_STATUS_UNRESOLVED';
        $row.stdout_sha256='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855';
        $row.stderr_sha256=$(if('MUTATION' -eq 'stderr'){'0'*64}else{'148fc48c6aeaf4d5f5780d0e38fc39215de098c1537c57e09410d4dad9718a1d'})}
      $rows+=$row}}
    return @{phase=$(if('MUTATION' -eq 'phase'){'native'}else{'auth'});status='PHASE_COMPLETED';
      manifest_sha256='bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4';
      candidate_sha256='a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288';
      result=@{schema='cochem-r6-authentication/1';status='ATTENDED_AUTH_REVIEW_REQUIRED';checks=$rows;native_model_jobs_executed=0;credentials_copied=$false;
        status_helper_sha256=$(if('MUTATION' -eq 'helper'){'0'*64}else{'574e5b220fb15963b0d4d3e1561402d946d6caedc70b1ac268d2f0d6546ddf53'})}}
  }
  if($Path -like '*r6-held.json'){return @{status='HELD_PRESERVE_EVIDENCE';phase='auth';cutover_requested=('MUTATION' -eq 'cutover');
    recovery=@{ok=$true;restored=('MUTATION' -ne 'restored');kind='base'}}}
  if($Path -like '*start-receipt.json'){
    if($Hash -cne '3e32dc204f9003c709a758f9025610204b4596cfaa67ac31be379bd7a94a067b'){throw 'unbound restore'}
    return @{schema='cochem-warden-start/3';status='WARDEN_R4_RESTARTED_HEALTH_VERIFIED';target='r4';attempt='v3';
      task_name='CoChem-4.2.7-Warden';enabled_after=$true;task_state=4;running_instances=1;health_samples=2;
      health=@{samples_stable=$true};exactly_one_start_requested=$true;automatic_retry_allowed=$false}}
  throw 'unexpected read'
}
function Get-R6ReviewedAuthTask {
  $settings=[pscustomobject]@{MultipleInstances=2;RestartCount=0;AllowDemandStart=$true;ExecutionTimeLimit='PT15M';Enabled=$true}
  $arguments='-I -B "'+(Join-Path $root 'r6_auth_recovery.py')+'" --output "'+$root+'" --manifest-hash bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4 --candidate-hash a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288'
  $action=[pscustomobject]@{Type=0;Path=(Join-Path $script:targetRoot '.venv\Scripts\python.exe');Arguments=$arguments;WorkingDirectory=$script:targetRoot}
  $actions=[pscustomobject]@{Count=1;Action=$action};$actions|Add-Member ScriptMethod Item {param($Number) $this.Action}
  $definition=[pscustomobject]@{Settings=$settings;Principal=[pscustomobject]@{UserId='SYSTEM';LogonType=5;RunLevel=1};Actions=$actions;Triggers=[pscustomobject]@{Count=0}}
  if('MUTATION' -eq 'task_arguments'){$action.Arguments='changed'}
  if('MUTATION' -eq 'task_duration'){$settings.ExecutionTimeLimit='PT1M'}
  $task=[pscustomobject]@{Definition=$definition;Enabled=$true;Acl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)';
    State=$(if('MUTATION' -eq 'task_state'){4}else{3});LastTaskResult=$(if('MUTATION' -eq 'task_result'){1}else{0});LastRunTime=[DateTime]'2026-10-12'}
  if('MUTATION' -eq 'task_acl'){$task.Acl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BU)'}
  $task|Add-Member ScriptMethod GetInstances {param($Flags) @{Count=$(if('MUTATION' -eq 'task_instances'){1}else{0})}}
  $task|Add-Member ScriptMethod GetSecurityDescriptor {param($Mask) $this.Acl}
  $script:events.Add('task_lookup');$task
}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('PHASE_PATH',[ref]$tokens,[ref]$errors)
$definition=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Assert-R6PhaseTask'},$false))[0]
. ([scriptblock]::Create($definition.Extent.Text))
$held=$false
try{Assert-R6ReviewedPrefixFailure $root}catch{$held=$true}
@{held=$held;events=@($script:events)}|ConvertTo-Json -Compress
'''.replace('MUTATION', mutation).replace('PHASE_PATH', phase))
    assert result['held'] is bool(mutation)
    if not mutation:
        assert result['events'] == ['task_lookup']


@pytest.mark.parametrize('mutation', ['', 'duplicate','success_changed','agy_changed','cleanup','count'])
def test_recovery_requires_exact_owner_reviewed_eighteen_statuses(run_ps, mutation):
    checks=[dict(worker=f'slot{i}',provider=p,authenticated=p!='gemini',
        status='STATUS_UNVERIFIED' if p=='gemini' else 'REUSE_VERIFIED_SESSION',
        exit_code=1 if p=='gemini' else 0,cleanup_verified=True)
        for i in range(1,7) for p in ('codex','claude','gemini')]
    if mutation=='duplicate': checks[-1]=checks[2]
    if mutation=='success_changed':checks[0]['authenticated']=False
    if mutation=='agy_changed':checks[2]['exit_code']=2
    if mutation=='cleanup':checks[0]['cleanup_verified']=False
    if mutation=='count':checks.pop()
    value=dict(schema='cochem-r6-authentication/1',status='ATTENDED_AUTH_REVIEW_REQUIRED',checks=checks,
        native_model_jobs_executed=0,credentials_copied=False)
    result=run_ps("$value='"+json.dumps(value)+"'|ConvertFrom-Json\n"+r'''
$held=$false
try{Assert-R6AuthRecoveryRows $value}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
''')
    assert result['held'] is bool(mutation)


def test_imported_phase_loader_uses_explicit_directory_before_host_access(run_ps):
    directory=str(Path(__file__).parents[1]/'scripts').replace("'","''")
    result=run_ps(r'''
$path=Join-Path 'DIRECTORY' 'run_r6_system_phase.ps1'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)
$node=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Import-R6PhaseInstaller'},$false))[0]
. ([scriptblock]::Create($node.Extent.Text))
$message=''
try{$null=Import-R6PhaseInstaller ('0'*64) 'DIRECTORY'}catch{$message=$_.Exception.Message}
@{message=$message}|ConvertTo-Json -Compress
'''.replace('DIRECTORY',directory))
    assert result['message']=='R6 installer helper differs from the reviewed pin.'


def test_import_chain_loads_actual_installer_and_copy_definitions_without_host_actions(run_ps):
    directory=str(Path(__file__).parents[1]/'scripts').replace("'","''")
    pin=hashlib.sha256((Path(__file__).parents[1]/'scripts/install_r6_runtime.ps1').read_bytes()).hexdigest()
    result=run_ps(r'''
$directory='DIRECTORY'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $directory 'run_r6_system_phase.ps1'),[ref]$tokens,[ref]$errors)
$node=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Import-R6PhaseInstaller'},$false))[0]
. ([scriptblock]::Create($node.Extent.Text))
$pin='INSTALLER_PIN'
foreach($definition in @(Import-R6PhaseInstaller $pin $directory)){. ([scriptblock]::Create($definition))}
foreach($definition in @(Import-R6CopyFunctions $directory)){. ([scriptblock]::Create($definition))}
@{tree=[bool](Get-Command Assert-R6Tree);interpreter=[bool](Get-Command Assert-R6Interpreter);
  file=[bool](Get-Command Open-VerifiedFile);acl=[bool](Get-Command Assert-ProtectedPath)}|ConvertTo-Json -Compress
'''.replace('DIRECTORY',directory).replace('INSTALLER_PIN',pin))
    assert result==dict(tree=True,interpreter=True,file=True,acl=True)


def test_reviewed_restore_accepts_actual_receipt_writer_without_invented_started_field(run_ps):
    """Run only the production writer's pure receipt expressions, never StartOnce."""
    core = str(Path(__file__).parents[1] / 'docs/deployment/windows-deployment-next/r6_retarget_core.ps1').replace("'", "''")
    result = run_ps(r'''
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('CORE',[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Receipt writer parse error'}
foreach($name in @('New-ReceiptHead','Add-OrderedFields')){
  $node=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$false))[0]
  . ([scriptblock]::Create($node.Extent.Text))}
$start=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-StartOnce'},$false))[0]
$head=@($start.FindAll({param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Extent.Text -like '$receipt=New-ReceiptHead *'},$true))[0]
$fields=@($start.FindAll({param($n) $n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -ceq 'Add-OrderedFields'},$true))[0]
$script:Attempt='v3';$script:taskName='CoChem-4.2.7-Warden'
$Context=@{target='r4';started_status='WARDEN_R4_RESTARTED_HEALTH_VERIFIED';runtime_root='fixture';config_path='fixture';
  config_sha256=('a'*64);install_after_path='fixture';install_after_sha256=('a'*64);config_mode='runtime';
  deployment_revision_sha256=('a'*64);admission_field=$null;
  action=@{execute='fixture';arguments='fixture';working_directory='fixture'};triggers=@()}
$Binding=@{source=@{source_state='r4';source_attempt='v2';stop_attempt='v3'};receipt_sha256=('a'*64)}
$state=@{enabled=$false};$final=@{state=4;instances=1;enabled=$true}
$facts=@{instance_guid='fixture'};$enabledByStart=$true;$twoPhase=$false;$after=@{}
$intentHash='b'*64;$startedXml='c'*64;$evaluations=2;$proof=@{}
$second=[pscustomobject]@{pid=1;instance_id='fixture';process_started_at=1;source_root='fixture';quarantined_slots=[pscustomobject]@{}}
$routingHolds=@{valid=$true;items=@()}
function Get-JsonMember {param($Object,$Name) if($Name -ceq 'quarantined_slots'){$Object.quarantined_slots}else{$null}}
function Get-JsonListField {param($Object,$Name) @{valid=$true;items=@()}}
function Get-LiveTriggerEnabled {param($State,$Target) $true}
. ([scriptblock]::Create($head.Extent.Text))
. ([scriptblock]::Create($fields.Extent.Text))
$script:written=$receipt|ConvertTo-Json -Depth 10|ConvertFrom-Json
$message='';$held=$false
try{Assert-R6ReviewedRestore $script:written}catch{$held=$true;$message=$_.Exception.Message}
@{held=$held;message=$message;schema=$script:written.schema;has_started=($null -ne $script:written.PSObject.Properties['started'])}|ConvertTo-Json -Compress
'''.replace('CORE', core))
    assert result['schema'] == 'cochem-warden-start/3'
    assert result['has_started'] is False
    assert result['held'] is False, result['message']


@pytest.mark.parametrize('field,value', [
    ('schema', 'wrong'), ('status', 'wrong'), ('target', 'r6'), ('attempt', 'v4'),
    ('task_name', 'wrong'), ('enabled_after', False), ('task_state', 3),
    ('running_instances', 0), ('health_samples', 1), ('health', {'samples_stable': False}),
    ('exactly_one_start_requested', False), ('automatic_retry_allowed', True),
])
def test_reviewed_restore_refuses_changed_persisted_evidence(run_ps, field, value):
    receipt=dict(schema='cochem-warden-start/3', status='WARDEN_R4_RESTARTED_HEALTH_VERIFIED',
        target='r4', attempt='v3', task_name='CoChem-4.2.7-Warden', enabled_after=True,
        task_state=4, running_instances=1, health_samples=2, health={'samples_stable': True},
        exactly_one_start_requested=True, automatic_retry_allowed=False)
    receipt[field]=value
    result=run_ps("$receipt='"+json.dumps(receipt)+"'|ConvertFrom-Json\n"+r'''
$held=$false
try{Assert-R6ReviewedRestore $receipt}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
''')
    assert result['held'] is True


@pytest.mark.parametrize('mutation', ['', 'helper', 'status', 'cleanup', 'stream', 'phase',
    'cutover', 'recovery', 'restore', 'task', 'session_root', 'session_task'])
def test_console_hold_requires_exact_signed_out_inventory_restore_and_no_login_session(run_ps, mutation):
    rows=[dict(worker=f'slot{i}',provider=p,authenticated=p!='gemini',cleanup_verified=True,
        status='ATTENDED_LOGIN_REQUIRED' if p=='gemini' else 'REUSE_VERIFIED_SESSION',
        exit_code=1 if p=='gemini' else 0) for i in range(1,7) for p in ('codex','claude','gemini')]
    for row in rows:
        if row['provider']=='gemini':
            row.update(reason='AGY_MODELS_EXPLICIT_SIGN_OUT',stdout_bytes=0,stderr_bytes=122,
                stdout_sha256='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
                stderr_sha256='148fc48c6aeaf4d5f5780d0e38fc39215de098c1537c57e09410d4dad9718a1d')
    if mutation=='status':rows[2]['status']='STATUS_UNVERIFIED'
    if mutation=='cleanup':rows[0]['cleanup_verified']=False
    if mutation=='stream':rows[2]['stderr_sha256']='a'*64
    evidence=dict(phase='auth',status='PHASE_COMPLETED',
        manifest_sha256='bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4',
        candidate_sha256='a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288',
        result=dict(schema='cochem-r6-authentication/1',status='ATTENDED_AUTH_REVIEW_REQUIRED',
            status_helper_sha256='a'*64 if mutation=='helper' else '79b7029cd998f25c0a01300924bb3972f830f7783618ce3c99260b089510aaec',
            native_model_jobs_executed=0,credentials_copied=False,checks=rows))
    result=run_ps("$script:evidence='"+json.dumps(evidence)+"'|ConvertFrom-Json\n"+r'''
$script:base='C:\fixture';$script:targetRoot='C:\fixture\r6';$script:events=[Collections.Generic.List[string]]::new()
$root=Join-Path $script:base 'R6Acceptance4.2.7-windows-20261012-v1-auth-56126335ff314eb497cd409fd58e6b1e'
function Read-R6RecoveryJson {param($Path,$Hash)
  if($Path -like '*result.json'){return $script:evidence}
  if($Path -like '*r6-held.json'){return @{status='HELD_PRESERVE_EVIDENCE';
    phase=$(if('MUTATION' -eq 'phase'){'auth'}else{'attended_gemini_slot1'});cutover_requested=('MUTATION' -eq 'cutover');
    recovery=@{ok=$true;restored=('MUTATION' -ne 'recovery');kind='base'}}}
  if($Path -like '*start-receipt.json'){
    if($Hash -cne '4b20035cdcb90d9547dbe95a1302ba7574424877dedfa7ae0db1da4d5e849852'){throw 'unbound restoration'}
    return @{schema='cochem-warden-start/3';status='WARDEN_R4_RESTARTED_HEALTH_VERIFIED';target='r4';attempt='v4';
      task_name='CoChem-4.2.7-Warden';enabled_after=$true;task_state=4;running_instances=1;
      health_samples=$(if('MUTATION' -eq 'restore'){1}else{2});health=@{samples_stable=$true};
      exactly_one_start_requested=$true;automatic_retry_allowed=$false}}
  throw 'unexpected evidence read'
}
function Assert-R6ReviewedAuthTask {param($Root,$Name)
  if($Name -cne 'CoChem-4.2.7-R6Acceptance-auth-56126335ff314eb497cd409fd58e6b1e' -or
    $Root -notlike '*auth-56126335ff314eb497cd409fd58e6b1e'){throw 'wrong prior task'}
  if('MUTATION' -eq 'task'){throw 'task changed'};$script:events.Add('task')}
function Get-ChildItem {param($LiteralPath,[switch]$Directory,$Filter)
  if($LiteralPath -cne $script:base -or $Filter -cne 'InteractiveAgy427-r4-slot1-*'){throw 'wrong session census'}
  if('MUTATION' -eq 'session_root'){[pscustomobject]@{Name='preserved-session'}}}
function Get-R6Slot1InteractiveTasks {if('MUTATION' -eq 'session_task'){[pscustomobject]@{Name='preserved-task'}}}
$held=$false
try{Assert-R6ReviewedConsoleHold $root}catch{$held=$true}
@{held=$held;events=@($script:events)}|ConvertTo-Json -Compress
'''.replace('MUTATION',mutation))
    assert result['held'] is bool(mutation)
    if not mutation:assert result['events']==['task']


@pytest.mark.parametrize('mutation',['','install_held','wrong_install','wrong_phase','restore_failed','knowledge_exists','later_phase','recovery_exists','reviewed_recovery','reviewed_recovery_failed','reviewed_console','reviewed_console_failed'])
def test_complete_preflight_with_inert_host_boundaries(run_ps,mutation):
    result=run_ps(r'''
$script:base='C:\fixture';$script:targetRoot='C:\fixture\r6';$script:events=[Collections.Generic.List[string]]::new()
$script:mh='bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4'
$script:ch='a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288'
function Read-R6RecoveryJson {param($Path,$Hash)
  $leaf=Split-Path -Leaf $Path
  switch($leaf){
    'install-manifest.json' {return @{}}
    'pipeline.json' {return @{knowledge=@{state_root='C:\fixture\knowledge'}}}
    'install-after.json' {return @{status=$(if('MUTATION' -eq 'wrong_install'){'WRONG'}else{'STOPPED_RUNTIME_INSTALLED'});
       manifest_sha256=$script:mh;source_commit='359ca92e57b2d74eb407b258cf53123d80ef1467'}}
    'result.json' {
      $rows=@();foreach($i in 1..6){foreach($p in @('codex','claude','gemini')){
        $rows+=@{worker=('slot'+$i);provider=$p;authenticated=($p -ne 'gemini');cleanup_verified=$true;
          status=$(if($p -eq 'gemini'){'STATUS_UNVERIFIED'}else{'REUSE_VERIFIED_SESSION'});exit_code=$(if($p -eq 'gemini'){1}else{0})}}}
      return @{phase=$(if('MUTATION' -eq 'wrong_phase'){'native'}else{'auth'});status='PHASE_COMPLETED';
        manifest_sha256=$script:mh;candidate_sha256=$script:ch;
        result=@{schema='cochem-r6-authentication/1';status='ATTENDED_AUTH_REVIEW_REQUIRED';checks=$rows;native_model_jobs_executed=0;credentials_copied=$false}}}
    'r6-held.json' {return @{status='HELD_PRESERVE_EVIDENCE';phase='auth';cutover_requested=$false;
      recovery=@{ok=('MUTATION' -ne 'restore_failed');restored=$true}}}
    default {throw 'unexpected read'}
  }}
function Test-Path {param($LiteralPath)
  return (('MUTATION' -eq 'install_held' -and $LiteralPath -like '*install-held.json') -or
    ('MUTATION' -eq 'knowledge_exists' -and $LiteralPath -eq 'C:\fixture\knowledge') -or
    ('MUTATION' -in @('recovery_exists','reviewed_recovery','reviewed_recovery_failed','reviewed_console','reviewed_console_failed') -and $LiteralPath -like '*r6_auth_recovery.py'))}
function Get-ChildItem {param($LiteralPath,[switch]$Directory)
  if('MUTATION' -eq 'later_phase'){[pscustomobject]@{Name='R6Acceptance4.2.7-windows-20261012-v1-native-fixture';FullName='C:\fixture\native'}}
  if('MUTATION' -eq 'recovery_exists'){[pscustomobject]@{Name='R6Acceptance4.2.7-windows-20261012-v1-auth-fixture';FullName='C:\fixture\auth'}}
  if('MUTATION' -in @('reviewed_recovery','reviewed_recovery_failed')){[pscustomobject]@{Name='R6Acceptance4.2.7-windows-20261012-v1-auth-226ce1d64f29486c838fca043f6bf904';FullName='C:\fixture\reviewed'}}
  if('MUTATION' -in @('reviewed_console','reviewed_console_failed')){[pscustomobject]@{Name='R6Acceptance4.2.7-windows-20261012-v1-auth-56126335ff314eb497cd409fd58e6b1e';FullName='C:\fixture\console'}}}
function Assert-R6ReviewedPrefixFailure {param($Root)
  if('MUTATION' -eq 'reviewed_recovery_failed'){throw 'reviewed evidence differs'}
  if($Root -cne 'C:\fixture\reviewed'){throw 'wrong reviewed root'}
  $script:events.Add('reviewed_attempt')}
function Assert-R6ReviewedConsoleHold {param($Root)
  if('MUTATION' -eq 'reviewed_console_failed'){throw 'console evidence differs'}
  if($Root -cne 'C:\fixture\console'){throw 'wrong console root'}
  $script:events.Add('console_attempt')}
function Assert-R6NotReferenced {$script:events.Add('task_reference')}
function Assert-R6Tree {$script:events.Add('tree');100}
function Assert-R6Interpreter {$script:events.Add('interpreter')}
function Get-FileHash {param($LiteralPath,$Algorithm) @{Hash=('a'*64)}}
$held=$false;$status=$null
try{$status=(Assert-R6AuthRecoveryEvidence).status}catch{$held=$true}
@{held=$held;status=$status;events=@($script:events)}|ConvertTo-Json -Compress
'''.replace('MUTATION',mutation))
    success = mutation in ('', 'reviewed_recovery', 'reviewed_console')
    assert result['held'] is not success
    if success:
        assert result['status']=='EXISTING_R6_AUTH_RECOVERY_PREREQUISITES_VERIFIED'
        expected = {'reviewed_recovery':['reviewed_attempt'], 'reviewed_console':['console_attempt']}.get(mutation, [])
        assert result['events']==expected+['task_reference','tree','interpreter']
    else: assert result['events']==[]
