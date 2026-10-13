"""Windows PowerShell fixtures exercise imported functions, never task COM."""
import json
from pathlib import Path

import pytest

from pipeline_tests import test_install_r6_runtime as fixture
from pipeline_tests.test_agy_signin_batch import load

ROOT=Path(__file__).parents[1]
SCRIPT=ROOT/'scripts/signin_agy_profiles.ps1'


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(fixture,'SCRIPT',SCRIPT)
    return fixture.run_ps


@pytest.mark.parametrize('mutation',['','path','arguments','principal','duration','acl','started','trigger'])
def test_task_readback_uses_real_acl_validator_and_exact_definition(run_ps,mutation):
    registration=str(ROOT/'docs/deployment/windows-deployment-next/register-stopped-warden-r3.ps1')
    result=run_ps(r'''
foreach($d in @(Import-SigninDefinitions 'REGISTRATION')){. ([scriptblock]::Create($d))}
$script:python='C:\fixture\python.exe'
$a=[pscustomobject]@{Type=0;Path=$script:python;Arguments='fixed';WorkingDirectory='C:\fixture'}
$actions=[pscustomobject]@{Count=1;Action=$a};$actions|Add-Member ScriptMethod Item {param($n) $this.Action}
$task=[pscustomobject]@{Name='fixed-name';LastTaskResult=267011;Enabled=$true;State=3;Sddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)';Definition=[pscustomobject]@{
 Principal=[pscustomobject]@{UserId='SYSTEM';LogonType=5;RunLevel=1};Triggers=[pscustomobject]@{Count=0};Actions=$actions;
 Settings=[pscustomobject]@{MultipleInstances=2;RestartCount=0;ExecutionTimeLimit='PT30M';Enabled=$true;AllowDemandStart=$true}}}
$task|Add-Member ScriptMethod GetSecurityDescriptor {param($flags) if($flags -ne 7){throw 'Wrong flags'};$this.Sddl}
$task|Add-Member ScriptMethod GetInstances {param($flags) [pscustomobject]@{Count=0}}
switch('MUTATION'){
 'path'{$a.Path='other'} 'arguments'{$a.Arguments='other'} 'principal'{$task.Definition.Principal.UserId='owner'}
 'duration'{$task.Definition.Settings.ExecutionTimeLimit='PT0S'} 'acl'{$task.Sddl='O:BAG:BAD:P(A;;FA;;;WD)'}
 'started'{$task.LastTaskResult=0} 'trigger'{$task.Definition.Triggers.Count=1}}
$held=$false;try{Assert-SigninTask $task 'fixed-name' 'fixed' 'C:\fixture'}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
'''.replace('REGISTRATION',registration.replace("'","''")).replace('MUTATION',mutation))
    assert result['held'] is bool(mutation)


def test_exact_staged_package_read_only_plan(run_ps,tmp_path):
    result=load('prepare_agy_signin').prepare(tmp_path/'package')
    value=run_ps("Invoke-SigninMain '"+str(tmp_path/'package')+"' '"+result['manifest_sha256']+"' $false")
    assert value['slots']==6 and value['system_tasks']==1 and value['package_files']==16
    assert not value['daemon_tasks_changed'] and not value['browser_opened']


def test_manifest_rejects_changed_broker_before_any_task_work(run_ps,tmp_path):
    result=load('prepare_agy_signin').prepare(tmp_path/'package')
    (tmp_path/'package/worker_agy_signin_batch.py').write_text('changed')
    value=run_ps("$handles=[Collections.Generic.List[IO.FileStream]]::new();$held=$false;try{$null=Open-SigninManifest '"+
        str(tmp_path/'package')+"' '"+result['manifest_sha256']+"' $handles}catch{$held=$true}finally{foreach($h in $handles){$h.Dispose()}}\n@{held=$held}|ConvertTo-Json -Compress")
    assert value['held']


@pytest.mark.parametrize('state,instances,held',[(3,0,False),(1,0,False),(4,1,True),(2,0,True),(3,1,True)])
def test_old_ended_login_tasks_preserved_active_tasks_refused(run_ps,state,instances,held):
    value=run_ps(r'''
$task=[pscustomobject]@{Name='CoChem-4.2.7-InteractiveAgyTerminal-r4-slot1-old';State=STATE;Instances=INSTANCES}
$task|Add-Member ScriptMethod GetInstances {param($flags) [pscustomobject]@{Count=$this.Instances}}
$folder=[pscustomobject]@{Task=$task};$folder|Add-Member ScriptMethod GetTasks {param($flags) ,$this.Task}
$held=$false;try{Assert-NoRunningSignins $folder}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
'''.replace('STATE',str(state)).replace('INSTANCES',str(instances)))
    assert value['held'] is held


def test_failure_metadata_omits_exception_text_and_contains_hresult(run_ps):
    value=run_ps(r'''
try{throw 'PRIVATE-CODE-AND-URL'}catch{Get-SigninFailure $_ 'register'|ConvertTo-Json -Depth 6 -Compress}
''')
    assert value['phase']=='register' and value['error_chain'][0]['hresult']
    assert 'PRIVATE' not in json.dumps(value)


def test_owner_console_relays_fresh_url_and_submits_one_masked_line(run_ps,tmp_path):
    code_source=str(ROOT/'docs/deployment/windows-deployment-next/claude-code-input-v6.ps1')
    terminal_source=str(ROOT/'scripts/login_pipeline_worker_agy_terminal.ps1')
    legacy_source=str(ROOT/'docs/deployment/windows-deployment-next/login_pipeline_worker_interactive_agy_r4_v1.ps1')
    result=run_ps(r'''
foreach($source in @('CODE','TERMINAL','LEGACY')){
 foreach($d in @(Import-SigninDefinitions $source)){. ([scriptblock]::Create($d))}}
$root='ROOT';$nonce=('a'*32);$script:sent=@();$script:display='';$script:messages=@();$script:keyIndex=0
$script:keys=@();foreach($c in 'FixtureQCode'.ToCharArray()){$script:keys+=,[ConsoleKeyInfo]::new($c,[ConsoleKey]::A,$false,$false,$false)}
$script:keys+=,[ConsoleKeyInfo]::new([char]13,[ConsoleKey]::Enter,$false,$false,$false)
function Clear-ClaudeConsoleInput {@{console_queue_clear=$true}}
function Write-Host {param($Object) $script:messages+=,[string]$Object}
function Test-InstanceComplete {param($Instance) $false}
function Read-AgyOperatorLog {param($Path) "https://accounts.google.com/o/oauth2/auth?fixture=fresh`nPaste the authorization code below:`n"}
function Write-AgyConsoleText {param($Text) $script:display+=$Text}
function Test-AgyConsoleKeyAvailable {$script:keyIndex -lt $script:keys.Count}
function Read-AgyConsoleKey {$key=$script:keys[$script:keyIndex];$script:keyIndex++;$key}
function Write-PrivatePacket {param($Path,$Nonce,$Secret)
 $ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secret)
 try{$script:sent+=,[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)}finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)}
 [IO.File]::WriteAllText((Join-Path $root 'result.json'),'{}')}
[IO.File]::WriteAllText((Join-Path $root 'operator.log'),'fixture')
$output=[IO.StringWriter]::new();$original=[Console]::Out
try{[Console]::SetOut($output);Invoke-SigninConsole 'fixture' $root $nonce ([DateTime]::UtcNow.AddMinutes(1))}finally{[Console]::SetOut($original)}
@{sent=@($script:sent);url=$script:display;console=$output.ToString();messages=@($script:messages)}|ConvertTo-Json -Compress
'''.replace('CODE',code_source).replace('TERMINAL',terminal_source).replace('LEGACY',legacy_source).replace('ROOT',str(tmp_path)))
    assert result['sent']==['FixtureQCode']
    assert 'https://accounts.google.com/' in result['url']
    assert 'FixtureQCode' not in result['console']
    assert any('Verifying' in text for text in result['messages'])
