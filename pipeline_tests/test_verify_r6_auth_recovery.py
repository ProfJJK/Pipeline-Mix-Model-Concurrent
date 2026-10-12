import json
import hashlib
from pathlib import Path

import pytest

from pipeline_tests import test_install_r6_runtime as ps_fixture


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(ps_fixture,'SCRIPT',Path(__file__).parents[1]/'scripts/verify_r6_auth_recovery.ps1')
    return ps_fixture.run_ps


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


@pytest.mark.parametrize('mutation',['','install_held','wrong_install','wrong_phase','restore_failed','knowledge_exists','later_phase','recovery_exists'])
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
    ('MUTATION' -eq 'recovery_exists' -and $LiteralPath -like '*r6_auth_recovery.py'))}
function Get-ChildItem {param($LiteralPath,[switch]$Directory)
  if('MUTATION' -eq 'later_phase'){[pscustomobject]@{Name='R6Acceptance4.2.7-windows-20261012-v1-native-fixture';FullName='C:\fixture\native'}}
  if('MUTATION' -eq 'recovery_exists'){[pscustomobject]@{Name='R6Acceptance4.2.7-windows-20261012-v1-auth-fixture';FullName='C:\fixture\auth'}}}
function Assert-R6NotReferenced {$script:events.Add('task_reference')}
function Assert-R6Tree {$script:events.Add('tree');100}
function Assert-R6Interpreter {$script:events.Add('interpreter')}
function Get-FileHash {param($LiteralPath,$Algorithm) @{Hash=('a'*64)}}
$held=$false;$status=$null
try{$status=(Assert-R6AuthRecoveryEvidence).status}catch{$held=$true}
@{held=$held;status=$status;events=@($script:events)}|ConvertTo-Json -Compress
'''.replace('MUTATION',mutation))
    assert result['held'] is bool(mutation)
    if not mutation:
        assert result['status']=='EXISTING_R6_AUTH_RECOVERY_PREREQUISITES_VERIFIED'
        assert result['events']==['task_reference','tree','interpreter']
    else: assert result['events']==[]
