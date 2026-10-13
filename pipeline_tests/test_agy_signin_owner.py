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
    result=run_ps(r'''
$root='ROOT';$nonce=('a'*32);$script:sent=@();$script:display='';$script:messages=@()
function Write-Host {param($Object) $script:messages+=,[string]$Object}
function Test-InstanceComplete {param($Instance) $false}
function Read-SigninJson {param($Path) Get-Content -LiteralPath $Path -Raw|ConvertFrom-Json}
function Show-SigninCodePrompt {param($Url,$Slot,$Root,$Deadline)
 $script:display=$Url
 $secret=[Security.SecureString]::new();foreach($c in 'FixtureQCode'.ToCharArray()){$secret.AppendChar($c)}
 @{Status='SUBMIT';Secret=$secret}}
function Write-PrivatePacket {param($Path,$Nonce,$Secret)
 $ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secret)
 try{$script:sent+=,[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)}finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)}
 [IO.File]::WriteAllText((Join-Path $root 'result.json'),'{}')}
[IO.File]::WriteAllText((Join-Path $root 'prompt-ready.json'),(@{schema='cochem-agy-code-prompt/1';
 nonce=$nonce;slot=(Split-Path $root -Leaf);url='https://accounts.google.com/o/oauth2/auth?fixture=fresh'}|ConvertTo-Json))
$output=[IO.StringWriter]::new();$original=[Console]::Out
try{[Console]::SetOut($output);Invoke-SigninConsole 'fixture' $root $nonce ([DateTime]::UtcNow.AddMinutes(1))}finally{[Console]::SetOut($original)}
@{sent=@($script:sent);url=$script:display;console=$output.ToString();messages=@($script:messages)}|ConvertTo-Json -Compress
'''.replace('ROOT',str(tmp_path)))
    assert result['sent']==['FixtureQCode']
    assert 'https://accounts.google.com/' in result['url']
    assert 'FixtureQCode' not in result['console']
    assert any('Verifying' in text for text in result['messages'])


@pytest.mark.parametrize('mutation', ['', 'nonce', 'slot', 'scheme', 'host', 'userinfo', 'fragment'])
def test_fresh_prompt_identity_and_url_are_bound_before_dialog(run_ps, mutation):
    value=run_ps(r'''
$p=[pscustomobject]@{schema='cochem-agy-code-prompt/1';nonce=('a'*32);slot='slot1';url='https://accounts.google.com/oauth?fixture=fresh'}
switch('MUTATION'){
 'nonce'{$p.nonce='other'} 'slot'{$p.slot='slot2'} 'scheme'{$p.url='http://accounts.google.com/oauth'}
 'host'{$p.url='https://accounts.google.com.evil/oauth'} 'userinfo'{$p.url='https://user@accounts.google.com/oauth'}
 'fragment'{$p.url='https://accounts.google.com/oauth#other'}}
$held=$false;try{Assert-SigninPrompt $p 'slot1' ('a'*32)}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
'''.replace('MUTATION',mutation))
    assert value['held'] is bool(mutation)


@pytest.mark.parametrize('mode',['submit','empty','expired','closed'])
def test_standard_windows_fields_and_submit_boundary_without_showing_window(run_ps,tmp_path,mode):
    result=run_ps(r'''
$root='ROOT';$deadline=[DateTime]::UtcNow.AddMinutes(1)
$view=New-SigninPromptView 'https://accounts.google.com/oauth?fixture=fresh' 'slot1'
$context=@{Result=$null;Error=$null}
try{
 $view.Url.SelectAll();$selected=$view.Url.SelectedText
 if('MODE' -ne 'empty'){$view.Code.Password='Fixture-Q-Code'}
 if('MODE' -eq 'expired'){$deadline=[DateTime]::UtcNow.AddSeconds(-1)}
 if('MODE' -eq 'closed'){[IO.File]::WriteAllText((Join-Path $root 'input.closed'),'fixture')}
 Complete-SigninPrompt $view $context $root $deadline
 Complete-SigninPrompt $view $context $root $deadline
 $state=if($context.Result){$context.Result.Status}else{'EMPTY'}
 $length=if($context.Result -and $context.Result.Secret){$context.Result.Secret.Length}else{0}
 @{state=$state;secret_length=$length;selected=$selected;readonly=$view.Url.IsReadOnly;
   masked_type=$view.Code.GetType().FullName;custom_bindings=$view.Code.InputBindings.Count;
   default_button=$view.Submit.IsDefault;cancel_button=$view.Cancel.IsCancel;
   field_cleared=($view.Code.SecurePassword.Length -eq 0)}|ConvertTo-Json -Compress
}finally{if($context.Result -and $context.Result.Secret){$context.Result.Secret.Dispose()};$view.Code.Clear();$view.Window.Close()}
'''.replace('ROOT',str(tmp_path)).replace('MODE',mode))
    assert result['state']==dict(submit='SUBMIT',empty='EMPTY',expired='EXPIRED',closed='EXPIRED')[mode]
    assert result['secret_length']==(14 if mode=='submit' else 0)
    assert result['selected']=='https://accounts.google.com/oauth?fixture=fresh'
    assert result['readonly'] and result['masked_type']=='System.Windows.Controls.PasswordBox'
    assert result['custom_bindings']==0 and result['default_button'] and result['cancel_button']
    if mode=='submit':assert result['field_cleared']


@pytest.mark.parametrize('mutation',['','task','active','exit','hash','nonce','cleanup','submitted','reason'])
def test_only_reviewed_ended_prompt_failure_may_be_preserved_and_passed(run_ps, mutation):
    value=run_ps(r'''
$script:cochemRoot='C:\fixture';$script:nonce='29d5943c97954a7695d57c722e917cd2'
$task=[pscustomobject]@{Name=('CoChem-4.2.7-AgySignIn-'+$script:nonce);LastTaskResult=2;State=3;Instances=0}
$task|Add-Member ScriptMethod GetSecurityDescriptor {param($flags) 'fixture-sddl'}
$task|Add-Member ScriptMethod GetInstances {param($flags) [pscustomobject]@{Count=$this.Instances}}
function Assert-RegisteredTaskAcl {param($Sddl) if($Sddl -cne 'fixture-sddl'){throw 'bad'}}
function Read-R3Control {param($Path,$Hash,$Maximum)
 if('MUTATION' -eq 'hash' -or $Hash -cne 'a2d3cf3bbaf19f6917ac3826f3fc4bc3774f9fc327e24419e2cf0cb0449ccfa0'){throw 'changed'}}
function Write-Host {param($Object)}
$script:result=[pscustomobject]@{nonce=$script:nonce;checks=@([pscustomobject]@{slot='slot1';cleanup_verified=$true})}
$script:login=[pscustomobject]@{nonce=$script:nonce;cleanup_verified=$true;terminal_cleanup_verified=$true;
 input_closed_marker_written=$true;one_line_submitted=$false;code_write_completed=$false;
 terminal_hold_reason='FRESH_GOOGLE_PROMPT_NOT_OBSERVED'}
function Read-SigninJson {param($Path) if($Path.EndsWith('login.json')){$script:login}else{$script:result}}
switch('MUTATION'){
 'task'{$task.Name+='other'} 'active'{$task.Instances=1} 'exit'{$task.LastTaskResult=3}
 'nonce'{$script:result.nonce='other'} 'cleanup'{$script:login.cleanup_verified=$false}
 'submitted'{$script:login.one_line_submitted=$true} 'reason'{$script:login.terminal_hold_reason='other'}}
$folder=[pscustomobject]@{Task=$task};$folder|Add-Member ScriptMethod GetTasks {param($flags) ,$this.Task}
$held=$false;try{Assert-NoRunningSignins $folder}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
'''.replace('MUTATION',mutation))
    assert value['held'] is bool(mutation)
