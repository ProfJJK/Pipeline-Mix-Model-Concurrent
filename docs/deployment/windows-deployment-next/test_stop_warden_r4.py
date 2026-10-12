"""Inert PS5.1 fixtures for stop-warden-r4.ps1 (build-manifest step 1, decision 2B).

No task is read for real, ended, disabled or started and no privileged API runs. The script's
functions are extracted from its AST into a throwaway powershell.exe and driven with stubs: the
COM task is modelled with a Stop method and an Enabled property whose setter logs the process,
port and instance state at the moment of every write, so the ordering rules (End once, disable
only after the controller is gone and the port is free, no disable when anything survives) are
observed directly. Two whole-script runs exercise the refused unelevated -Apply and the
unelevated read-only plan, which must create nothing. One test runs the operator '-c' snippet
with the installed r4 interpreter against an in-process loopback HTTP server.

2026-10-11 17:22 sitting fix: the r5 sitting's S2 (-Apply -Attempt v1, task enabled with no instance) held because
Get-ControllerPresence left the four Antigravity bridge MCP clients ('<runtime python> -m cochem_mcp --provider
codex|claude --config C:\\Users\\ansac\\CoChem427\\bridge.local.json') unclassified. The presence table and the -Apply
fixtures below run the REAL Get-ControllerPresence over the 14 live MCP clients of that host (Win32_Process stubbed), and
the top-level plan-mode smoke tests run the real script top level through ps_toplevel_smoke.py (host stubbed, -Apply
refused before any process starts): the ALREADY_STOPPED disable-only plan must not hold on the clients, while every other
rooted process stays unclassified and every controller-like command line stays a controller.
"""
import hashlib
import http.server
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET

import pytest

import ps_toplevel_smoke as smoke

ROOT = Path(__file__).parent
SCRIPT = ROOT / 'stop-warden-r4.ps1'
V22 = ROOT / 'retarget-warden-r4.ps1'
V22_SHA256 = '8ee6b412f6be176dfac7c2c1b2340f1973e08358c7d22da6d4515e79f0327a4e'
REGISTER = ROOT / 'register-stopped-warden-r3.ps1'
COCHEM = Path(r'C:\Program Files\CoChem')
R4_ROOT = r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4'
R4_PY = R4_ROOT + r'\.venv\Scripts\python.exe'
R4_SOURCE = R4_ROOT + r'\.venv\Lib'
BASE_PY = r'C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe'
CONFIG = r'C:\Program Files\CoChem\WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json'
QUEUE_R4V1 = r'C:\ProgramData\CoChemPipeline427\private\queue-retarget-20261010-r4-v1'
QUEUE_COMMISSIONING = r'C:\ProgramData\CoChemPipeline427\private\queue-commissioning-20261007-r3-v1'
R4_ARGS = f'-I -B -m cochem_pipeline daemon --config "{CONFIG}" --queue-launch-output "{QUEUE_R4V1}"'
RETARGET_AFTER_XML = COCHEM / 'WardenRetarget4.2.7-windows-20261010-r4-v1' / 'warden-task-after.xml'
RETARGET_AFTER_XML_SHA256 = 'fbfdcd8318d2418cbb8d28badad53a1a8e829a1e9c7143d13600bb62fd04c2be'
STOP_ROOT_V1 = COCHEM / 'WardenStop4.2.7-windows-20261010-r4-v1'
SDDL = 'O:BAG:BAD:PAI(A;;FA;;;SY)(A;;FA;;;BA)'
TASK_XML = ('<?xml version="1.0" encoding="UTF-16"?><Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
            '<RegistrationInfo><SecurityDescriptor>O:BAG:BAD:PAI(A;;FA;;;SY)(A;;FA;;;BA)</SecurityDescriptor><Description>d</Description><URI>\\CoChem-4.2.7-Warden</URI></RegistrationInfo>'
            '<Principals><Principal id="Author"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>'
            '<Settings><DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy></Settings>'
            '<Triggers /><Actions Context="Author"><Exec><Command>c</Command></Exec></Actions></Task>')

REUSED = ['Import-ReviewedFunctions', 'Invoke-NativeJudged', 'Get-ExpectedArguments', 'Test-ExactBool', 'Test-ExactInt', 'Assert-R4InstalledBindings',
          'Get-WardenTaskState', 'Get-OtherDaemonTaskStates', 'Assert-OtherDaemonsIdle', 'Get-ControllerPresence', 'Test-ControllerAlive', 'Test-LoopbackFree',
          'Get-WorkerProcesses', 'Assert-NoWorkers', 'Get-HealthSample', 'Get-ProcessProof']
NEW = ['Set-StopConstants', 'Assert-StopRuntimePins', 'Assert-StopDefinition', 'Assert-StopSource', 'Get-TaskXmlOutsideEnabled', 'Assert-StopDisabledTask',
       'Get-JsonListField', 'Get-JobIdText', 'Test-IdlePredicate', 'Get-OperatorSnapshot', 'Get-IdleEvidence', 'Wait-WardenIdle', 'Get-ProcessCreationUtc',
       'Get-LastBootUtc', 'Get-StopProcessProof', 'Get-ProofProcesses', 'Assert-OnlyProvenController', 'Test-ProcessInstancePresent', 'Get-ExitObservation',
       'Wait-WardenExit', 'Invoke-StopWarden', 'Invoke-StopWardenMain']
# Get-ControllerPresence's GUI-client line in v2.2, and the 2026-10-11 17:22 fix: a rooted process whose command line is
# exactly '"<...\python.exe>" -m cochem_mcp --provider codex|claude --config <the owner's bridge.local.json>' (the
# Antigravity bridge entries, pure loopback clients of the job board) is a client too. The same line is in stop-warden-r5.ps1.
OLD_CLIENT_LINE = (r"elseif($rooted -and $command -match 'cochem_pipeline\s+(mcp|health|status|submit|cancel|projects|code|code-status|code-cancel|"
                   r"code-resume|knowledge-\w+)\b'){$clients+=$entry}")
NEW_CLIENT_LINE = (r"elseif($rooted -and ($command -match 'cochem_pipeline\s+(mcp|health|status|submit|cancel|projects|code|code-status|code-cancel|"
                   r"code-resume|knowledge-\w+)\b' -or $command -cmatch '^" + '"[^"]+' + r"\\python\.exe" + '"' +
                   r" -m cochem_mcp --provider (codex|claude) --config C:\\Users\\ansac\\CoChem427\\bridge\.local\.json\z')){$clients+=$entry}")
BRIDGE_CONFIG = r'C:\Users\ansac\CoChem427\bridge.local.json'
CLIENT_CONFIG = r'C:\Users\ansac\CoChem427\pipeline-client-r3.json'
R5_PY = r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5\.venv\Scripts\python.exe'


def ps(path):
    return str(path).replace("'", "''")


PRELUDE = r'''$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;
foreach($m in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$m\$m.psd1")};
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('SCRIPTPATH',[ref]$tokens,[ref]$errors);
if($errors.Count){throw ($errors|Out-String)};
foreach($f in $ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){. ([scriptblock]::Create($f.Extent.Text))};
$regAst=[Management.Automation.Language.Parser]::ParseFile('REGPATH',[ref]$tokens,[ref]$errors);
foreach($f in $regAst.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Assert-RegisteredTaskAcl'},$true)){. ([scriptblock]::Create($f.Extent.Text))};
$script:Attempt='v1';$script:IdleWaitSeconds=30;$script:ExitWaitSeconds=9;Set-StopConstants;$script:admin=$false;
$held=[Collections.Generic.List[IO.FileStream]]::new();
'''.replace('SCRIPTPATH', ps(SCRIPT)).replace('REGPATH', ps(REGISTER))


def run(body, timeout=120):
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', PRELUDE + body],
                          capture_output=True, text=True, timeout=timeout)


def run_json(body, timeout=120):
    result = run(body, timeout)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


TASK_FIXTURE = r'''
$script:stops=0;$script:stopFlags=$null;$script:events=@();$script:enabledWrites=@();$script:sleeps=@();$script:foreignPids=@();$script:loopbackProbes=0
function New-FixtureFolder {param([hashtable]$Overrides)
  $v=@{Enabled=$true;State=4;Instances=1;LastTaskResult=267009;UserId='S-1-5-18';LogonType=5;RunLevel=1;Triggers=0;Actions=1;MultipleInstances=2;ExecutionTimeLimit='PT0S';RestartCount=0;AllowDemandStart=$true;
       ActionType=0;Path='R4PYVALUE';Arguments='R4ARGSVALUE';WorkingDirectory='R4ROOTVALUE';Sddl='SDDLVALUE';Xml='XMLVALUE';DenyGetTask=$false;
       StopThrows=$false;StopEffective=$true;PidSurvives=$false;PortListenerRemains=$false;ExclusiveBindRefused=$false;WorkerSurvives=$false;DisableChangesXml=$false;DisableSddl=''};
  foreach($k in $Overrides.Keys){$v[$k]=$Overrides[$k]};
  $script:fx=$v;$script:fxEnabled=[bool]$v.Enabled;$script:instances=$v.Instances
  $running=($v.State -eq 4);$script:portListening=$(if($running){1}else{0});$script:portFree=(-not $running);$script:alivePids=$(if($running){@(20664,5320)}else{@()});$script:workerPids=@()
  $script:action=[pscustomobject]@{Type=$v.ActionType;Path=$v.Path;Arguments=$v.Arguments;WorkingDirectory=$v.WorkingDirectory}
  $actions=[pscustomobject]@{Count=$v.Actions};$actions|Add-Member ScriptMethod Item {param($i)$script:action}
  $definition=[pscustomobject]@{Principal=[pscustomobject]@{UserId=$v.UserId;LogonType=$v.LogonType;RunLevel=$v.RunLevel};Triggers=[pscustomobject]@{Count=$v.Triggers};Actions=$actions;
    Settings=[pscustomobject]@{MultipleInstances=$v.MultipleInstances;ExecutionTimeLimit=$v.ExecutionTimeLimit;RestartCount=$v.RestartCount;AllowDemandStart=$v.AllowDemandStart}}
  $script:task=[pscustomobject]@{State=$v.State;LastTaskResult=$v.LastTaskResult;Xml=$v.Xml;Definition=$definition}
  $script:task|Add-Member ScriptProperty Enabled {$script:fxEnabled} {param($value)
    $script:events+='disable';$script:enabledWrites+=[pscustomobject]@{value=$value;instances=$script:instances;state=$script:task.State;port_listening=$script:portListening;port_free=$script:portFree;alive=@($script:alivePids).Count}
    $script:fxEnabled=[bool]$value
    if(-not $value){$script:task.State=1
      $script:task.Xml=$script:task.Xml.Replace('<Settings>','<Settings><Enabled>false</Enabled>')
      if($script:fx.DisableChangesXml){$script:task.Xml=$script:task.Xml.Replace('IgnoreNew','Parallel')}
      if($script:fx.DisableSddl){$script:fx.Sddl=$script:fx.DisableSddl}}}
  $script:task|Add-Member ScriptMethod GetInstances {param($n)[pscustomobject]@{Count=$script:instances}}
  $script:task|Add-Member ScriptMethod GetSecurityDescriptor {param($n)$script:fx.Sddl}
  $script:task|Add-Member ScriptMethod Stop {param($flags)
    $script:stops++;$script:stopFlags=$flags;$script:events+='stop'
    if($script:fx.StopThrows){throw [Runtime.InteropServices.COMException]::new('stop refused',-2147216615)}
    if(-not $script:fx.StopEffective){return}
    $script:task.State=3;$script:instances=0;$script:task.LastTaskResult=267014
    $script:portListening=$(if($script:fx.PortListenerRemains){1}else{0});$script:portFree=-not ($script:fx.PortListenerRemains -or $script:fx.ExclusiveBindRefused)
    $script:alivePids=@($(if($script:fx.PidSurvives){20664}));$script:workerPids=@($(if($script:fx.WorkerSurvives){7777}))}
  $folder=[pscustomobject]@{};$folder|Add-Member ScriptMethod GetTask {param($name)
    if($script:fx.DenyGetTask){throw [Runtime.InteropServices.COMException]::new('denied',-2147024891)}
    if($name -ne 'CoChem-4.2.7-Warden'){throw [Runtime.InteropServices.COMException]::new('absent',-2147024894)};$script:task}
  $folder}
'''.replace('R4PYVALUE', R4_PY).replace('R4ARGSVALUE', R4_ARGS).replace('R4ROOTVALUE', R4_ROOT).replace('SDDLVALUE', SDDL).replace('XMLVALUE', TASK_XML)

STUBS = r'''
$script:otherActive=$false;$script:proofGone=$false;$script:notIdle=$false;$script:idleWaits=0
function New-ProtectedDirectory {param($Path)if(Test-Path -LiteralPath $Path){throw ('Destination already exists: '+$Path)};$null=[IO.Directory]::CreateDirectory($Path);$script:events+='root'}
function Write-RegistrationControl {param($Path,$Text)if(Test-Path -LiteralPath $Path){throw ('control exists: '+$Path)};[IO.File]::WriteAllText($Path,$Text,[Text.UTF8Encoding]::new($false));$script:events+=('write:'+(Split-Path -Leaf $Path));(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
function Get-OtherDaemonTaskStates {param($Folder)if($script:otherActive){@([pscustomobject]@{name='CoChem-4.2.7-Supervisor';state='ACTIVE';active=$true})}else{@([pscustomobject]@{name='CoChem-4.2.7-Supervisor';state='STOPPED_DISABLED';active=$false})}}
function Get-WorkerProcesses {[ordered]@{workers=@($script:workerPids|ForEach-Object {[ordered]@{pid=$_;user='CoChem422Worker1';path='C:\x\agy.exe'}});uninspectable_processes=@();exited_during_sweep=0;authoritative=$true}}
function Get-ControllerPresence {
  $c=@(@($script:alivePids)+@($script:foreignPids)|ForEach-Object {[ordered]@{pid=$_;parent=1;path='x';command='python -m cochem_pipeline daemon'}})
  [ordered]@{port=47824;listening=$script:portListening;controller_processes=$c;observer_processes=@([ordered]@{pid=9472;command='observer'});client_processes=@();unclassified_runtime_processes=@();uninspectable_python_processes=0;authoritative=$true}}
function Test-LoopbackFree {$script:loopbackProbes++;[bool]$script:portFree}
function Test-ProcessInstancePresent {param($ProcessId,$CreationUtc)if($script:proofGone){return $false};[int]$ProcessId -in @($script:alivePids)}
function Start-Sleep {param($Seconds,$Milliseconds)$script:sleeps+=@($Seconds)}
function Get-LastBootUtc {'2026-10-10T08:00:00.0000000Z'}
function Get-StopProcessProof {param($ProcessId)[ordered]@{controller=[ordered]@{pid=[int]$ProcessId;image='BASEPYVALUE';creation_utc='2026-10-11T01:00:56.0000000Z';parent_pid=5320};launcher=[ordered]@{pid=5320;image='R4PYVALUE';creation_utc='2026-10-11T01:00:55.0000000Z'};owner='SYSTEM';port_owner_verified=$true;last_boot_up_time='2026-10-10T08:00:00.0000000Z'}}
function Wait-WardenIdle {$script:idleWaits++
  if($script:notIdle){throw 'The Warden is not idle after 3 evaluation(s) within 30 s: queue row job-7 is PENDING; offending job ids: job-7. Nothing was changed; let the work finish, submit nothing during the sitting, then run again.'}
  [ordered]@{schema='cochem-warden-idle-evidence/1';idle=$true;reasons=@();offending_job_ids=@();queue_rows=2;queue_status_counts=[ordered]@{BLOCKED=1;COMPLETED=1};in_progress_rows=0;uncleared_cleanup_rows=0;routing_holds=0;
    controller=[ordered]@{pid=20664;instance_id='61497bdab0514590b88fd0cab689a404';process_started_at=1791680462.6393604;source_root='R4SOURCEVALUE'};evaluations=1}}
'''.replace('BASEPYVALUE', BASE_PY).replace('R4PYVALUE', R4_PY).replace('R4SOURCEVALUE', R4_SOURCE)


def ast_functions(path):
    body = ("$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile('" + ps(path) + "',[ref]$t,[ref]$e);"
            "$top=@($a.EndBlock.Statements|Where-Object {$_ -isnot [Management.Automation.Language.FunctionDefinitionAst]}|ForEach-Object {$_.Extent.Text});"
            "$names=@($a.EndBlock.Statements|Where-Object {$_ -is [Management.Automation.Language.FunctionDefinitionAst]}|ForEach-Object {$_.Name});"
            "$texts=[ordered]@{};foreach($f in $a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){$texts[$f.Name]=$f.Extent.Text};"
            "$params=@($a.ParamBlock.Parameters|ForEach-Object {[ordered]@{name=$_.Name.VariablePath.UserPath;default=$(if($_.DefaultValue){$_.DefaultValue.Extent.Text}else{$null})}});"
            "[ordered]@{errors=$e.Count;top=$top;names=$names;texts=$texts;params=$params}|ConvertTo-Json -Depth 4 -Compress")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', body], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_script_parses_declares_only_the_expected_functions_and_one_invocation():
    value = ast_functions(SCRIPT)
    assert value['errors'] == 0
    assert value['names'] == REUSED + NEW, 'the script declares exactly the reviewed and the new functions'
    assert value['top'] == ['Invoke-StopWardenMain -ApplyRequested ([bool]$Apply)'], 'the top level is a single invocation'
    assert value['params'] == [{'name': 'Apply', 'default': None}, {'name': 'Attempt', 'default': "'v1'"},
                               {'name': 'IdleWaitSeconds', 'default': '120'}, {'name': 'ExitWaitSeconds', 'default': '90'}]
    assert SCRIPT.read_bytes().isascii()


def test_reused_functions_are_byte_identical_to_the_reviewed_v22():
    assert hashlib.sha256(V22.read_bytes()).hexdigest() == V22_SHA256
    mine = ast_functions(SCRIPT)['texts']
    reviewed = ast_functions(V22)['texts']
    for name in REUSED:
        if name == 'Get-ControllerPresence':
            # 2026-10-11 17:22: the one reviewed delta - the GUI-client line also admits the Antigravity bridge.
            assert reviewed[name].count(OLD_CLIENT_LINE) == 1, 'v2.2 carries the original client line'
            assert mine[name] == reviewed[name].replace(OLD_CLIENT_LINE, NEW_CLIENT_LINE), 'only the client line changes'
            continue
        assert mine[name] == reviewed[name], name
    for dropped in ('Assert-R3Commissioning', 'Assert-RetargetSource', 'Invoke-Retarget', 'Invoke-StartOnce', 'Backup-PrivateDatabases'):
        assert dropped not in mine, 'r3 source checks and retarget/start paths are dropped'


def test_pins_helper_hashes_and_forbidden_operations():
    text = SCRIPT.read_text(encoding='utf-8')
    helpers = {Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1'): '0300b827',
               ROOT / 'check-worker-native-status-r3.ps1': '18f58ebb', REGISTER: 'eccc593f', ROOT / 'protected-code-inspection-v4.ps1': '5c01543c'}
    for path, prefix in helpers.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest.startswith(prefix) and f"'{digest}'" in text, path
    on_disk = {Path(R4_ROOT) / 'install-after.json': '$script:r4InstallPin', Path(R4_ROOT) / 'source-manifest.json': '$script:r4ManifestPin',
               Path(R4_ROOT) / 'windows-layout.json': '$script:r4LayoutPin', Path(CONFIG): '$script:configPin', Path(BASE_PY): '$script:probePythonPin',
               RETARGET_AFTER_XML: '$script:retargetTaskXmlPin'}
    for path, name in on_disk.items():
        if path.exists():
            assert f"{name}='{hashlib.sha256(path.read_bytes()).hexdigest()}'" in text, path
    for pin in ("$script:r4RevisionPin='38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e'",
                "$script:repairPin='e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc'",
                "'queue-retarget-20261010-r4-v1'", "$script:stopNamespaceDate='20261010'", "$script:expectedEndResult=267014",
                "$script:healthSpacingSeconds=5;$script:idlePollSeconds=10"):
        assert pin in text, pin
    for forbidden in ('Stop-ScheduledTask', 'Disable-ScheduledTask', 'Register-ScheduledTask', 'Unregister-ScheduledTask', 'Start-ScheduledTask', 'RegisterTaskDefinition',
                      'schtasks', 'Start-Process', 'Stop-Process', 'taskkill', '.Run(', 'Remove-Item', 'DeleteTask', 'Stop-Service', '.Kill(', 'Invoke-Expression',
                      'Copy-VerifiedPayload', 'CoChem-4.2.7-HeldSupervisorObservation', 'CoChem-4.2.7-ResourceObservation', '/MIR', 'robocopy'):
        assert forbidden not in text, forbidden
    assert text.count('.Stop(0)') == 1 and text.count('.Enabled=$false') == 1, 'one End request and one disable'
    assert text.count('.GetTask(') == 2, 'only the Warden and the three managed daemon names are ever looked up'
    assert text.count("'-X','utf8'") == 3, 'health, bind probe and operator snapshot all run with -X utf8'
    assert '"' not in text.split("$script:operatorCall=@(")[1].split("-join")[0], 'the -c snippet is single-quoted Python only'
    assert "$ErrorActionPreference='Continue'" in text and "-ApplyRequested ([bool]$Apply)" in text


def test_pinned_action_equals_the_exec_element_of_the_live_retarget_xml():
    if not RETARGET_AFTER_XML.exists():
        pytest.skip('the r4-v1 retarget evidence is not on this host')
    raw = RETARGET_AFTER_XML.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == RETARGET_AFTER_XML_SHA256
    text = raw.decode('utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig')  # header says UTF-16, bytes are UTF-8
    root = ET.fromstring(text.split('?>', 1)[1])
    ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    exec_node = root.find('t:Actions/t:Exec', ns)
    value = run_json("[ordered]@{path=$script:r4Python;arguments=(Get-ExpectedArguments $script:commissioningConfig $script:queueR4v1);wd=$script:r4Root;queue_new=$script:queueNew}|ConvertTo-Json -Compress")
    assert exec_node.find('t:Command', ns).text == value['path'] == R4_PY
    assert exec_node.find('t:Arguments', ns).text == value['arguments'] == R4_ARGS
    assert exec_node.find('t:WorkingDirectory', ns).text == value['wd'] == R4_ROOT
    assert value['queue_new'] == QUEUE_R4V1, 'Get-ProcessProof (unchanged) binds the r4-v1 daemon command'
    assert text.count('<Enabled>') == 0, 'the live XML carries no <Enabled>; disabling inserts one'


@pytest.mark.parametrize('case', ['stderr_exit_0', 'stderr_exit_1', 'missing_executable'])
def test_native_commands_are_judged_by_exit_code_not_stderr(tmp_path, case):
    program = {'stderr_exit_0': "import sys;sys.stderr.write('warn');print('out');sys.exit(0)",
               'stderr_exit_1': "import sys;sys.stderr.write('boom');sys.exit(1)", 'missing_executable': "print('unused')"}[case]
    fixture = tmp_path / 'native.py'
    fixture.write_text(program, encoding='utf-8')
    executable = sys.executable if case != 'missing_executable' else str(tmp_path / 'no-such-python.exe')
    value = run_json(f"$refused=$false;$r=$null;try{{$r=Invoke-NativeJudged '{ps(executable)}' @('-I','-B','-X','utf8','{ps(fixture)}')}}catch{{$refused=$true}};"
                     "[ordered]@{refused=$refused;code=$(if($r){$r.code}else{$null});stdout=$(if($r){$r.stdout}else{$null});stderr=$(if($r){$r.stderr}else{$null});preference=[string]$ErrorActionPreference}|ConvertTo-Json -Compress")
    assert value['preference'] == 'Stop'
    if case == 'missing_executable':
        assert value['refused'] is True
        return
    assert value['refused'] is False and value['code'] == (1 if case == 'stderr_exit_1' else 0)
    if case == 'stderr_exit_0':
        assert value['stdout'] == 'out' and 'warn' in value['stderr']


SOURCE_CASES = {
    'running': ('@{}', 'RUNNING'), 'already_stopped_ready': ('@{State=3;Instances=0}', 'ALREADY_STOPPED'),
    'already_stopped_disabled': ('@{Enabled=$false;State=1;Instances=0}', 'ALREADY_STOPPED'),
    'running_but_disabled': ('@{Enabled=$false}', 'neither running exactly one enabled instance'), 'queued': ('@{State=2;Instances=0}', 'neither running'),
    'two_instances': ('@{Instances=2}', 'neither running'), 'principal': ("@{UserId='ansac'}", 'exact reviewed SYSTEM'), 'logon': ('@{LogonType=2}', 'exact reviewed SYSTEM'),
    'trigger': ('@{Triggers=1}', 'exact reviewed SYSTEM'), 'parallel': ('@{MultipleInstances=0}', 'exact reviewed SYSTEM'),
    'time_limit': ("@{ExecutionTimeLimit='PT8M'}", 'exact reviewed SYSTEM'), 'r3_path': ("@{Path='C:\\Program Files\\CoChem\\Pipeline4.2.7-windows-20261007-r3\\.venv\\Scripts\\python.exe'}", 'pinned r4-v1 action'),
    'commissioning_queue': ("@{Arguments='" + R4_ARGS.replace(QUEUE_R4V1, QUEUE_COMMISSIONING) + "'}", 'pinned r4-v1 action'),
    'restart_queue': ("@{Arguments='" + R4_ARGS.replace('queue-retarget-20261010-r4-v1', 'queue-restart-20261011-r4-v1') + "'}", 'pinned r4-v1 action'),
    'working_directory': ("@{WorkingDirectory='C:\\Program Files\\CoChem'}", 'pinned r4-v1 action'),
    'extra_ace': ("@{Sddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;BU)'}", 'ownership/private DACL'), 'unreadable': ('@{DenyGetTask=$true}', 'unreadable'),
}


@pytest.mark.parametrize('case', sorted(SOURCE_CASES))
def test_stop_source_binds_the_live_r4v1_task_exactly(case):
    overrides, expected = SOURCE_CASES[case]
    value = run_json(TASK_FIXTURE + f"$folder=New-FixtureFolder {overrides};" + r'''
      $mode=$null;$message='';try{$mode=Assert-StopSource (Get-WardenTaskState $folder)}catch{$message=$_.Exception.Message};@{mode=$mode;message=$message}|ConvertTo-Json -Compress''')
    if expected in ('RUNNING', 'ALREADY_STOPPED'):
        assert value == {'mode': expected, 'message': ''}
    else:
        assert value['mode'] is None and expected in value['message'], value


XML_BEFORE = ('<?xml version="1.0" encoding="UTF-16"?><Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><RegistrationInfo><Description>d</Description></RegistrationInfo>'
              '<Principals><Principal id="Author"><UserId>S-1-5-18</UserId></Principal></Principals><Settings><ExecutionTimeLimit>PT0S</ExecutionTimeLimit>'
              '<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy></Settings><Triggers><TimeTrigger><Enabled>true</Enabled></TimeTrigger></Triggers>'
              '<Actions Context="Author"><Exec><Command>c</Command></Exec></Actions></Task>')
XML_CASES = {
    'absent_to_false': (XML_BEFORE, XML_BEFORE.replace('<Settings>', '<Settings><Enabled>false</Enabled>'), False),
    'absent_to_false_at_end': (XML_BEFORE, XML_BEFORE.replace('</Settings>', '<Enabled>false</Enabled></Settings>'), False),
    'true_to_false': (XML_BEFORE.replace('<Settings>', '<Settings><Enabled>true</Enabled>'), XML_BEFORE.replace('<Settings>', '<Settings><Enabled>false</Enabled>'), False),
    'whitespace_only': (XML_BEFORE, XML_BEFORE.replace('<Settings>', '<Settings>\n    <Enabled>false</Enabled>\n    '), False),
    'other_setting_changed': (XML_BEFORE, XML_BEFORE.replace('<Settings>', '<Settings><Enabled>false</Enabled>').replace('IgnoreNew', 'Parallel'), True),
    'trigger_enabled_changed': (XML_BEFORE, XML_BEFORE.replace('<TimeTrigger><Enabled>true', '<TimeTrigger><Enabled>false'), True),
    'description_changed': (XML_BEFORE, XML_BEFORE.replace('<Description>d<', '<Description>e<'), True),
    'action_changed': (XML_BEFORE, XML_BEFORE.replace('<Command>c<', '<Command>x<'), True),
    'principal_changed': (XML_BEFORE, XML_BEFORE.replace('S-1-5-18', 'S-1-5-19'), True),
}


@pytest.mark.parametrize('case', sorted(XML_CASES))
def test_xml_comparator_ignores_only_settings_enabled_including_absent_to_present(case):
    before, after, differs = XML_CASES[case]
    value = run_json(f"$b='{before}';$a='{after}';@{{differs=((Get-TaskXmlOutsideEnabled $b) -cne (Get-TaskXmlOutsideEnabled $a))}}|ConvertTo-Json -Compress")
    assert value['differs'] is differs


STATE_FIXTURE = r'''
function New-State {param([hashtable]$Overrides)
  $v=[ordered]@{readable=$true;enabled=$false;state=1;instances=0;last_task_result=267014;user='S-1-5-18';logon_type=5;run_level=1;triggers=0;actions=1;multiple_instances=2;execution_time_limit='PT0S';
    restart_count=0;allow_demand_start=$true;action_type=0;action_path='R4PYVALUE';action_arguments='R4ARGSVALUE';action_working_directory='R4ROOTVALUE';sddl='SDDLVALUE';xml='XMLVALUE'}
  foreach($k in $Overrides.Keys){$v[$k]=$Overrides[$k]};[pscustomobject]$v}
$before=New-State @{enabled=$true;state=4;instances=1}
$afterXml=$before.xml.Replace('<Settings>','<Settings><Enabled>false</Enabled>')
'''.replace('R4PYVALUE', R4_PY).replace('R4ARGSVALUE', R4_ARGS).replace('R4ROOTVALUE', R4_ROOT).replace('SDDLVALUE', SDDL).replace('XMLVALUE', TASK_XML)
READBACK_CASES = {
    'valid': ('@{xml=$afterXml}', ''), 'still_enabled': ('@{xml=$afterXml;enabled=$true;state=3}', 'still enabled'),
    'instance': ('@{xml=$afterXml;instances=1;state=4}', 'running or queued instance'), 'unreadable': ('@{readable=$false}', 'could not be read back'),
    'sddl_changed': ("@{xml=$afterXml;sddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'}", 'security descriptor changed'),
    'xml_changed_elsewhere': ("@{xml=$afterXml.Replace('IgnoreNew','Parallel')}", 'outside <Settings><Enabled>'),
    'action_changed': ("@{xml=$afterXml;action_arguments='-I -B -m cochem_pipeline daemon'}", 'pinned r4-v1 action'),
}


@pytest.mark.parametrize('case', sorted(READBACK_CASES))
def test_disabled_readback_requires_unchanged_action_sddl_and_xml(case):
    overrides, expected = READBACK_CASES[case]
    value = run_json(STATE_FIXTURE + f"$after=New-State {overrides};" + r'''
      $message='';try{Assert-StopDisabledTask $after $before}catch{$message=$_.Exception.Message};@{message=$message}|ConvertTo-Json -Compress''')
    if expected:
        assert expected in value['message'], value
    else:
        assert value['message'] == ''


def health(**changes):
    value = {'service_identity': 'SYSTEM', 'source_root': R4_SOURCE, 'pid': 20664, 'instance_id': '61497bdab0514590b88fd0cab689a404',
             'process_started_at': 1791680462.6393604, 'active': [], 'quarantined_slots': {},
             'routing': {'holds': [{'scope': 'model', 'resource_key': 'x'}], 'active_reservations': [], 'execution_quarantines': [], 'counts': {'COMPLETED': 3}}}
    for key, change in changes.items():
        if key == 'routing':
            value['routing'].update(change)
        else:
            value[key] = change
    return value


ROWS = [{'job_id': 'job-b', 'workflow_id': 'w', 'kind': 'CHAPTER', 'status': 'BLOCKED'}, {'job_id': 'job-c', 'workflow_id': 'w', 'kind': 'CHAPTER', 'status': 'COMPLETED'},
        {'job_id': 'job-f', 'workflow_id': 'w', 'kind': 'CHAPTER', 'status': 'FAILED'}]


def operator(rows):
    return json.dumps({'schema': 'cochem-operator-queue-extract/1', 'queue': rows})


IDLE_CASES = {
    'idle_blocked_completed_failed': (health(), health(), operator(ROWS), True, None, []),
    'idle_empty_queue': (health(), health(), operator([]), True, None, []),
    'blocked_only': (health(), health(), operator(ROWS[:1]), True, None, []),
    'completed_only': (health(), health(), operator(ROWS[1:2]), True, None, []),
    'active_job': (health(), health(active=[{'job_id': 'job-a', 'slot': 1, 'pid': 5, 'route': None}]), operator(ROWS), False, '1 active job(s)', ['job-a']),
    'reservation': (health(), health(routing={'active_reservations': [{'job_id': 'job-r', 'provider': 'codex'}]}), operator(ROWS), False, 'active route reservation', ['job-r']),
    'execution_quarantine': (health(routing={'execution_quarantines': [{'job_id': 'job-q', 'attempt_id': 'a'}]}), health(), operator(ROWS), False, 'uncleared execution cleanup', ['job-q']),
    'quarantined_slot': (health(quarantined_slots={'slot2': 'cleanup unconfirmed'}), health(), operator(ROWS), False, 'quarantined slot(s): slot2', []),
    'pending': (health(), health(), operator(ROWS + [{'job_id': 'job-p', 'workflow_id': 'w', 'kind': 'CHAPTER', 'status': 'PENDING'}]), False, 'job-p is PENDING', ['job-p']),
    'pending_retry': (health(), health(), operator([{'job_id': 'job-pr', 'workflow_id': 'w', 'kind': 'CHAPTER', 'status': 'PENDING_RETRY'}]), False, 'job-pr is PENDING_RETRY', ['job-pr']),
    'in_progress': (health(), health(), operator([{'job_id': 'job-ip', 'workflow_id': 'w', 'kind': 'CHAPTER', 'status': 'IN_PROGRESS'}]), False, 'job-ip is IN_PROGRESS', ['job-ip']),
    'malformed_operator_json': (health(), health(), '{"queue":[', False, 'not JSON', []),
    'operator_unavailable': (health(), health(), None, False, 'operator snapshot is unavailable', []),
    'operator_without_queue': (health(), health(), '{"schema":"x"}', False, 'no queue list', []),
    'row_without_status': (health(), health(), operator([{'job_id': 'job-x'}]), False, 'without a status', []),
    'routing_missing': ({k: v for k, v in health().items() if k != 'routing'}, health(), operator(ROWS), False, 'no routing object', []),
    'active_not_a_list': (health(active=None), health(), operator(ROWS), False, 'no active list', []),
    'identity_changed': (health(), health(pid=4242), operator(ROWS), False, 'identity changed between samples', []),
    'instance_changed': (health(), health(instance_id='other'), operator(ROWS), False, 'identity changed between samples', []),
    'wrong_identity': (health(service_identity='ansac'), health(), operator(ROWS), False, 'not the SYSTEM controller from the r4 root', []),
    'r3_source_root': (health(), health(source_root=R4_SOURCE.replace('20261009-r4', '20261007-r3')), operator(ROWS), False, 'not the SYSTEM controller from the r4 root', []),
    'health_unavailable': (None, health(), operator(ROWS), False, 'health sample 1 is unavailable', []),
}


def ps_json(value):
    if value is None:
        return '$null'
    text = json.dumps(value)
    assert "'" not in text
    return f"('{text}'|ConvertFrom-Json)"


@pytest.mark.parametrize('case', sorted(IDLE_CASES))
def test_idle_predicate_table(case):
    first, second, operator_text, idle, reason, jobs = IDLE_CASES[case]
    op = '$null' if operator_text is None else "'" + operator_text + "'"
    value = run_json(f"$r=Test-IdlePredicate {ps_json(first)} {ps_json(second)} {op};$r|ConvertTo-Json -Depth 5 -Compress")
    assert value['idle'] is idle, value
    if reason:
        assert any(reason in item for item in value['reasons']), value['reasons']
    else:
        assert value['reasons'] == []
    assert value['offending_job_ids'] == jobs
    if case == 'idle_blocked_completed_failed':
        assert value['queue_status_counts'] == {'BLOCKED': 1, 'COMPLETED': 1, 'FAILED': 1} and value['queue_rows'] == 3
        assert value['in_progress_rows'] == 0 and value['uncleared_cleanup_rows'] == 0 and value['routing_holds'] == 1


def test_idle_evidence_spaces_the_health_samples_and_issues_one_get_operator_call():
    good = json.dumps(health())
    body = (f"$script:h='{good}';" + r'''
      $script:sleeps=@();$script:native=@()
      function Start-Sleep {param($Seconds,$Milliseconds)$script:sleeps+=@($Seconds)}
      function Get-HealthSample {[pscustomobject]@{ok=$true;error='';health=($script:h|ConvertFrom-Json)}}
      function Invoke-NativeJudged {param($Executable,$Arguments)$script:native+=[pscustomobject]@{exe=$Executable;args=@($Arguments)};[pscustomobject]@{code=0;stdout='{"schema":"cochem-operator-queue-extract/1","queue":[]}';stderr=''}}
      $e=Get-IdleEvidence
      [ordered]@{idle=$e.idle;reasons=$e.reasons;sleeps=$script:sleeps;calls=@($script:native).Count;exe=$script:native[0].exe;args=$script:native[0].args;controller=$e.controller;samples=@($e.samples).Count}|ConvertTo-Json -Depth 5 -Compress''')
    value = run_json(body)
    assert value['idle'] is True and value['reasons'] == [] and value['samples'] == 2
    assert value['sleeps'] == [5], 'two samples at least 5 s apart'
    assert value['calls'] == 1 and value['exe'] == R4_PY
    args = value['args']
    assert args[:5] == ['-I', '-B', '-X', 'utf8', '-c'] and args[6] == r'C:\Users\ansac\CoChem427\pipeline-client-r3.json'
    assert "ControlClient(" in args[5] and ".call('/operator')" in args[5] and '"' not in args[5], 'GET: no data argument, single-quoted Python only'
    assert value['controller']['pid'] == 20664


def test_operator_snippet_issues_one_authenticated_get_against_a_loopback_server(tmp_path):
    if not Path(R4_PY).exists():
        pytest.skip('the r4 interpreter is not installed on this host')
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def _record(self):
            length = int(self.headers.get('Content-Length') or 0)
            seen.append({'method': self.command, 'path': self.path, 'auth': self.headers.get('Authorization'), 'body': self.rfile.read(length).decode() if length else ''})
            payload = json.dumps({'queue': [{'job_id': 'j1', 'workflow_id': 'w1', 'kind': 'CHAPTER', 'status': 'BLOCKED', 'score': {'x': 1}}],
                                  'timeline': [1, 2, 3]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = _record
        do_POST = _record

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        token = tmp_path / 'token.txt'
        token.write_text('tok-123\n', encoding='utf-8')
        config = tmp_path / 'client.json'
        config.write_text(json.dumps({'port': server.server_address[1], 'token_file': str(token)}), encoding='utf-8')
        value = run_json(f"$script:clientConfig='{ps(config)}';$o=Get-OperatorSnapshot;[ordered]@{{ok=$o.ok;error=$o.error;text=$o.text}}|ConvertTo-Json -Compress", timeout=120)
    finally:
        server.shutdown()
        server.server_close()
    assert value['ok'] is True, value['error']
    assert seen == [{'method': 'GET', 'path': '/operator', 'auth': 'Bearer tok-123', 'body': ''}]
    assert json.loads(value['text']) == {'schema': 'cochem-operator-queue-extract/1',
                                         'queue': [{'job_id': 'j1', 'workflow_id': 'w1', 'kind': 'CHAPTER', 'status': 'BLOCKED'}]}


@pytest.mark.parametrize('case', ['idle_first', 'idle_third', 'never_idle'])
def test_wait_idle_polls_no_faster_than_every_ten_seconds_and_names_job_ids(case):
    script = {'idle_first': '@($true)', 'idle_third': '@($false,$false,$true)', 'never_idle': '@($false,$false,$false,$false,$false)'}[case]
    value = run_json(f"$script:plan={script};" + r'''
      $script:sleeps=@();$script:evals=0
      function Start-Sleep {param($Seconds,$Milliseconds)$script:sleeps+=@($Seconds)}
      function Get-IdleEvidence {$idle=$script:plan[$script:evals];$script:evals++
        [ordered]@{idle=$idle;reasons=@($(if($idle){}else{'queue row job-7 is PENDING'}));offending_job_ids=@($(if($idle){}else{'job-7'}));controller=[ordered]@{pid=20664}}}
      $failed=$false;$message='';$r=$null;try{$r=Wait-WardenIdle}catch{$failed=$true;$message=$_.Exception.Message}
      [ordered]@{failed=$failed;message=$message;sleeps=$script:sleeps;evals=$script:evals;evaluations=$(if($r){$r.evaluations}else{$null})}|ConvertTo-Json -Compress''')
    expected_evals = {'idle_first': 1, 'idle_third': 3, 'never_idle': 3}[case]
    assert value['evals'] == expected_evals, 'IdleWaitSeconds 30 / poll 10 s bounds the evaluations to 3'
    assert value['sleeps'] == [10] * (expected_evals - 1)
    if case == 'never_idle':
        assert value['failed'] and 'offending job ids: job-7' in value['message'] and 'Nothing was changed' in value['message']
    else:
        assert not value['failed'] and value['evaluations'] == expected_evals


PROOF_STUBS = r'''
function New-Proc {param($ProcessId,$Parent,$Path,$Command,$Created)[pscustomobject]@{ProcessId=$ProcessId;ParentProcessId=$Parent;ExecutablePath=$Path;CommandLine=$Command;CreationDate=$Created}}
$script:controller=New-Proc 20664 5320 'BASEPYVALUE' '"BASEPYVALUE" R4ARGSVALUE' ([DateTime]::new(2026,10,11,1,0,56,[DateTimeKind]::Utc))
$script:launcher=New-Proc 5320 900 'R4PYVALUE' '"R4PYVALUE" R4ARGSVALUE' ([DateTime]::new(2026,10,11,1,0,55,[DateTimeKind]::Utc))
function Get-CimInstance {param($ClassName,$Filter,$ErrorAction)
  if($ClassName -eq 'Win32_OperatingSystem'){return [pscustomobject]@{LastBootUpTime=[DateTime]::new(2026,10,10,8,0,0,[DateTimeKind]::Utc)}}
  if($Filter -eq 'ProcessId = 20664'){return $script:controller};if($Filter -eq 'ProcessId = 5320'){return $script:launcher};$null}
function Get-NetTCPConnection {param($LocalPort,$State,$ErrorAction)@([pscustomobject]@{LocalPort=47824;OwningProcess=20664})}
function Invoke-CimMethod {param($InputObject,$MethodName,$ErrorAction)[pscustomobject]@{ReturnValue=0;User='SYSTEM'}}
'''.replace('BASEPYVALUE', BASE_PY).replace('R4PYVALUE', R4_PY).replace('R4ARGSVALUE', R4_ARGS)


@pytest.mark.parametrize('case', ['ok', 'parent_not_launcher', 'parent_wrong_queue', 'controller_is_venv_python', 'controller_wrong_queue', 'creation_unreadable'])
def test_stop_process_proof_binds_controller_launcher_and_creation_times(case):
    change = {'parent_not_launcher': "$script:launcher.ExecutablePath='C:\\Windows\\System32\\svchost.exe';",
              'parent_wrong_queue': f"$script:launcher.CommandLine=$script:launcher.CommandLine.Replace('{QUEUE_R4V1}','{QUEUE_COMMISSIONING}');",
              'controller_is_venv_python': f"$script:controller.ExecutablePath='{R4_PY}';",
              'controller_wrong_queue': f"$script:controller.CommandLine=$script:controller.CommandLine.Replace('{QUEUE_R4V1}','{QUEUE_COMMISSIONING}');",
              'creation_unreadable': '$script:controller.CreationDate=$null;'}.get(case, '')
    value = run_json(PROOF_STUBS + change + r'''
      $message='';$p=$null;try{$p=Get-StopProcessProof 20664}catch{$message=$_.Exception.Message};[ordered]@{message=$message;proof=$p}|ConvertTo-Json -Depth 5 -Compress''')
    if case == 'ok':
        proof = value['proof']
        assert value['message'] == '' and proof['controller'] == {'pid': 20664, 'image': BASE_PY, 'creation_utc': '2026-10-11T01:00:56.0000000Z', 'parent_pid': 5320}
        assert proof['launcher'] == {'pid': 5320, 'image': R4_PY, 'creation_utc': '2026-10-11T01:00:55.0000000Z'}
        assert proof['owner'] == 'SYSTEM' and proof['port_owner_verified'] is True and proof['last_boot_up_time'] == '2026-10-10T08:00:00.0000000Z'
    elif case == 'controller_is_venv_python':
        assert value['message'] == '' and value['proof']['launcher'] is None
    else:
        expected = {'parent_not_launcher': 'not the r4 venv launcher', 'parent_wrong_queue': 'not the r4 venv launcher',
                    'controller_wrong_queue': 'not running the expected r4 daemon command', 'creation_unreadable': 'creation time could not be read'}[case]
        assert expected in value['message'], value


@pytest.mark.parametrize('case', ['absent', 'same', 'reused_pid', 'creation_unreadable'])
def test_process_identity_uses_pid_and_creation_time(case):
    proc = {'absent': '$null', 'same': '[pscustomobject]@{ProcessId=20664;CreationDate=[DateTime]::new(2026,10,11,1,0,56,[DateTimeKind]::Utc)}',
            'reused_pid': '[pscustomobject]@{ProcessId=20664;CreationDate=[DateTime]::new(2026,10,11,2,0,0,[DateTimeKind]::Utc)}',
            'creation_unreadable': '[pscustomobject]@{ProcessId=20664;CreationDate=$null}'}[case]
    value = run_json(f"function Get-CimInstance {{param($ClassName,$Filter,$ErrorAction){proc}}};"
                     "@{present=(Test-ProcessInstancePresent 20664 '2026-10-11T01:00:56.0000000Z')}|ConvertTo-Json -Compress")
    assert value['present'] is (case in ('same', 'creation_unreadable')), 'a reused pid is gone; an unreadable creation time is kept as present'


APPLY_CASES = ['success', 'pid_survives', 'port_listener_remains', 'exclusive_bind_refused', 'stop_ineffective', 'worker_survives', 'stop_throws',
               'disable_changes_xml', 'disable_changes_sddl', 'not_idle', 'already_stopped_enabled', 'already_stopped_disabled', 'already_stopped_port_busy',
               'other_daemon_active', 'root_exists', 'proof_changed_before_end', 'foreign_controller', 'worker_before_end']
SUCCESS_EVENTS = ['root', 'write:warden-task-before.xml', 'write:warden-task-before.sddl', 'write:idle-evidence.json', 'write:stop-intent.json', 'stop', 'disable',
                  'write:warden-task-after.xml', 'write:warden-task-after.sddl', 'write:stop-receipt.json']
PREFIX = SUCCESS_EVENTS[:6]


@pytest.mark.parametrize('case', APPLY_CASES)
def test_stop_apply_path_is_driven_with_fixtures(tmp_path, case):
    target = tmp_path / 'stop-root'
    if case == 'root_exists':
        target.mkdir()
    overrides = {'pid_survives': '@{PidSurvives=$true}', 'port_listener_remains': '@{PortListenerRemains=$true}', 'exclusive_bind_refused': '@{ExclusiveBindRefused=$true}',
                 'stop_ineffective': '@{StopEffective=$false}', 'worker_survives': '@{WorkerSurvives=$true}', 'stop_throws': '@{StopThrows=$true}',
                 'disable_changes_xml': '@{DisableChangesXml=$true}', 'disable_changes_sddl': "@{DisableSddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'}",
                 'already_stopped_enabled': '@{State=3;Instances=0;LastTaskResult=267014}', 'already_stopped_port_busy': '@{State=3;Instances=0}',
                 'already_stopped_disabled': ("@{Enabled=$false;State=1;Instances=0;LastTaskResult=267014;Xml='" + TASK_XML.replace('<Settings>', '<Settings><Enabled>false</Enabled>') + "'}")
                 }.get(case, '@{}')
    flags = {'not_idle': '$script:notIdle=$true;', 'other_daemon_active': '$script:otherActive=$true;', 'already_stopped_port_busy': '$script:portFree=$false;',
             'proof_changed_before_end': '$script:proofGone=$true;', 'foreign_controller': '$script:foreignPids=@(9999);', 'worker_before_end': '$script:workerPids=@(4444);'}.get(case, '')
    body = (TASK_FIXTURE + STUBS + f"$folder=New-FixtureFolder {overrides};$script:targetRoot='{ps(target)}';{flags}" + r'''
      $failed=$false;$message='';$result=$null;try{$result=Invoke-StopWarden $folder ([ordered]@{install_receipt_sha256='a';revision_sha256='b'})}catch{$failed=$true;$message=$_.Exception.Message}
      [ordered]@{failed=$failed;message=$message;stops=$script:stops;stop_flags=$script:stopFlags;events=@($script:events);enabled_writes=@($script:enabledWrites);enabled=$script:fxEnabled;
        sleeps=@($script:sleeps);idle_waits=$script:idleWaits;status=$(if($result){$result.status}else{$null});root=(Test-Path -LiteralPath $script:targetRoot)}|ConvertTo-Json -Depth 5 -Compress''')
    value = run_json(body, timeout=180)
    receipt_path, held_path, intent_path = target / 'stop-receipt.json', target / 'stop-held.json', target / 'stop-intent.json'
    if case in ('success', 'already_stopped_enabled', 'already_stopped_disabled'):
        assert not value['failed'], value['message']
        assert not held_path.exists() and value['enabled'] is False
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        intent = json.loads(intent_path.read_text(encoding='utf-8'))
        after_xml = (target / 'warden-task-after.xml').read_bytes()
        assert receipt['schema'] == 'cochem-warden-stop/1' and receipt['task_xml_after_sha256'] == hashlib.sha256(after_xml).hexdigest()
        assert b'<Enabled>false</Enabled>' in after_xml and receipt['enabled'] is False and receipt['running_instances'] == 0
        assert receipt['sddl_preserved'] is True and receipt['xml_unchanged_outside_settings_enabled'] is True and receipt['action_unchanged'] is True
        assert receipt['action_arguments'] == R4_ARGS and receipt['processes_killed'] is False and receipt['observer_and_recorder_tasks_touched'] is False
        assert receipt['observer_processes'][0]['pid'] == 9472 and receipt['next_start_expectations']['fresh_queue_launch_output_required'] is True
        assert receipt['last_task_result'] == 267014 and receipt['last_task_result_asserted'] is False and intent['kill_allowed'] is False
        for write in value['enabled_writes']:
            assert write['value'] is False and write['instances'] == 0 and write['port_free'] is True and write['port_listening'] == 0 and write['alive'] == 0, \
                'Enabled is set false only after instances==0, the port is free and no controller pid is alive'
    if case == 'success':
        assert value['stops'] == 1 and value['stop_flags'] == 0 and value['idle_waits'] == 1 and value['events'] == SUCCESS_EVENTS
        assert value['status'] == 'WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED' and len(value['enabled_writes']) == 1
        assert receipt['mode'] == 'RUNNING' and receipt['end_requested'] is True and receipt['disable_requested'] is True and receipt['unclean_shutdown_expected'] is True
        assert receipt['last_task_result_expected'] == 267014 and receipt['controller'] == {'pid': 20664, 'launcher_pid': 5320, 'instance_id': '61497bdab0514590b88fd0cab689a404',
                                                                                           'process_started_at': 1791680462.6393604}
        expectations = receipt['next_start_expectations']
        assert {k: expectations[k] for k in ('crash_record_written', 'uncleared_cleanup_rows_at_stop', 'in_progress_leases_at_stop', 'expected_startup_quarantines',
                                             'fresh_queue_launch_output_required', 'ram_ledger_expected_action', 'warm_containers_reconciled_on_start', 'observer_rebinds_itself')} == {
            'crash_record_written': False, 'uncleared_cleanup_rows_at_stop': 0, 'in_progress_leases_at_stop': 0, 'expected_startup_quarantines': 0,
            'fresh_queue_launch_output_required': True, 'ram_ledger_expected_action': 'VERIFY', 'warm_containers_reconciled_on_start': True, 'observer_rebinds_itself': True}
        assert receipt['controller_exit']['complete'] is True and receipt['controller_exit']['polls'] == 1 and receipt['last_boot_up_time'] == '2026-10-10T08:00:00.0000000Z'
        assert intent['unclean_shutdown_expected'] is True and intent['controller']['launcher_pid'] == 5320
        assert intent['idle_evidence_sha256'] == hashlib.sha256((target / 'idle-evidence.json').read_bytes()).hexdigest()
        assert b'<Enabled>' not in (target / 'warden-task-before.xml').read_bytes()
        return
    if case in ('already_stopped_enabled', 'already_stopped_disabled'):
        assert value['stops'] == 0 and value['idle_waits'] == 0 and value['status'] == 'WARDEN_ALREADY_STOPPED_AND_DISABLED'
        assert receipt['mode'] == 'ALREADY_STOPPED' and receipt['end_requested'] is False and receipt['next_start_expectations']['evidenced'] is False
        assert receipt['idle_evidence_sha256'] is None and receipt['unclean_shutdown_expected'] is False
        if case == 'already_stopped_enabled':
            assert value['events'] == ['root', 'write:warden-task-before.xml', 'write:warden-task-before.sddl', 'write:stop-intent.json', 'disable',
                                       'write:warden-task-after.xml', 'write:warden-task-after.sddl', 'write:stop-receipt.json']
            assert receipt['disable_requested'] is True
        else:
            assert value['enabled_writes'] == [] and receipt['disable_requested'] is False, 'an already disabled task is not written again'
        return
    assert value['failed'] and not receipt_path.exists(), case
    if case in ('not_idle', 'other_daemon_active', 'root_exists', 'already_stopped_port_busy', 'foreign_controller', 'worker_before_end'):
        assert value['stops'] == 0 and value['enabled_writes'] == [] and 'root' not in value['events'] and not held_path.exists()
        assert 'othing was changed' in value['message'], 'refusals before the stop root exists change nothing'
        expected = {'not_idle': 'offending job ids: job-7', 'other_daemon_active': 'must remain stopped and disabled', 'root_exists': 'already exists',
                    'already_stopped_port_busy': 'cannot be bound exclusively', 'foreign_controller': '9999', 'worker_before_end': 'Slot worker processes are alive'}[case]
        assert expected in value['message']
        assert value['root'] is (case == 'root_exists')
        return
    held = json.loads(held_path.read_text(encoding='utf-8'))
    assert held['schema'] == 'cochem-warden-stop-held/1' and held['processes_killed'] is False and held['requires_reviewed_recovery'] is True and held['automatic_retry_allowed'] is False
    if case == 'proof_changed_before_end':
        assert value['stops'] == 0 and value['enabled_writes'] == [] and held['phase'] == 'PREPARATION' and held['end_requested'] is False
        assert 'Nothing was ended, disabled or killed' in value['message'] and 'pid 20664 changed during preparation' in value['message']
        return
    if case in ('disable_changes_xml', 'disable_changes_sddl'):
        assert value['stops'] == 1 and len(value['enabled_writes']) == 1 and held['phase'] == 'DISABLE_READBACK' and held['disable_requested'] is True
        assert value['events'] == SUCCESS_EVENTS[:9] + ['write:stop-held.json']
        assert ('outside <Settings><Enabled>' if case == 'disable_changes_xml' else 'security descriptor changed') in held['reason']
        assert 'may already be disabled' in value['message']
        return
    # Every End-phase hold: End requested exactly once, never a disable, the survivor or busy resource named, nothing killed.
    assert value['stops'] == 1 and value['enabled_writes'] == [] and value['enabled'] is True and held['disable_requested'] is False
    assert 'The task was NOT disabled and nothing was killed' in value['message']
    if case == 'stop_throws':
        assert held['phase'] == 'END_REQUEST' and held['end_requested'] is True and 'stop refused' in held['reason']
        assert value['events'] == PREFIX + ['write:stop-held.json']
        return
    assert held['phase'] == 'END_WAIT' and held['exit_observation']['polls'] == 4 and value['sleeps'] == [3, 3, 3], 'ExitWaitSeconds 9 / poll 3 s -> 4 bounded polls'
    assert value['events'] == PREFIX + ['write:stop-held.json']
    if case == 'pid_survives':
        assert [p['pid'] for p in held['surviving_processes']] == [20664] and 'Surviving pid(s): 20664' in value['message']
    if case == 'port_listener_remains':
        assert held['port_listening'] == 1 and 'still has a listener' in held['reason']
    if case == 'exclusive_bind_refused':
        assert held['port_listening'] == 0 and held['exclusive_bind_free'] is False and 'cannot be bound exclusively' in held['reason']
    if case == 'stop_ineffective':
        assert 'still shows state 4 with 1 instance' in held['reason'] and {p['pid'] for p in held['surviving_processes']} == {20664, 5320}
    if case == 'worker_survives':
        assert held['worker_pids'] == [7777] and 'Slot worker processes are alive' in held['reason']


def test_nonadmin_apply_and_invalid_parameters_refuse_before_any_change():
    before = sorted(p.name for p in COCHEM.iterdir()) if COCHEM.exists() else []
    for flags, text in ((['-Apply'], '-Apply requires the owner in Administrator Windows PowerShell; nothing was changed.'),
                        (['-Apply', '-Attempt', 'v1'], '-Apply requires the owner'), (['-Attempt', 'x1'], 'Attempt'),
                        (['-IdleWaitSeconds', '5'], 'IdleWaitSeconds'), (['-ExitWaitSeconds', '901'], 'ExitWaitSeconds')):
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(SCRIPT), *flags], capture_output=True, text=True, timeout=60)
        assert result.returncode != 0 and text in result.stderr, (flags, result.stderr)
    assert (sorted(p.name for p in COCHEM.iterdir()) if COCHEM.exists() else []) == before


def test_read_only_plan_reports_the_predicate_and_creates_nothing():
    if STOP_ROOT_V1.exists():
        pytest.skip('a stop attempt v1 already exists on this host')
    before = sorted(p.name for p in COCHEM.iterdir())
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(SCRIPT)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert sorted(p.name for p in COCHEM.iterdir()) == before and not STOP_ROOT_V1.exists(), 'the plan creates nothing'
    assert plan['schema'] == 'cochem-warden-stop-plan/1' and plan['mode'] == 'READ_ONLY_PLAN' and plan['attempt'] == 'v1'
    assert plan['administrator'] is False and plan['code_tree_verified'] is None and plan['target_root'] == str(STOP_ROOT_V1)
    assert plan['tasks_changed'] == 0 and plan['ended'] is False and plan['disabled'] is False and plan['processes_killed'] is False
    assert plan['expected_action'] == {'path': R4_PY, 'arguments': R4_ARGS, 'working_directory': R4_ROOT}
    assert plan['idle_wait_seconds'] == 120 and plan['exit_wait_seconds'] == 90
    if Path(R4_PY).exists():
        assert plan['r4_runtime_verified'] is True and plan['r4_bindings']['retarget_task_xml_sha256'] == RETARGET_AFTER_XML_SHA256
    if not plan['task_readable']:
        assert plan['stop_mode'] == 'DEFERRED' and any('unreadable without elevation' in hold for hold in plan['holds'])
    if plan['stop_mode'] in ('RUNNING', 'DEFERRED') and plan['r4_runtime_verified']:
        idle = plan['idle']
        assert idle is not None and isinstance(idle['idle'], bool) and isinstance(idle['reasons'], list), 'the plan prints the idle predicate read-only'
    assert plan['process_proof'] is None and 'elevated token' in plan['process_proof_note']
    assert plan['worker_processes']['authoritative'] is False


# --------------------------------------------------------------------------------------------------------------------
# 2026-10-11 17:22: the real Get-ControllerPresence over the live MCP clients (Win32_Process and the port stubbed)
# --------------------------------------------------------------------------------------------------------------------

def proc(pid, path, command, name='python.exe'):
    return {'pid': pid, 'parent_pid': 1, 'name': name, 'path': path, 'command_line': command}


def bridge(image, provider='codex', config=BRIDGE_CONFIG, tail=''):
    return f'"{image}" -m cochem_mcp --provider {provider} --config {config}{tail}'


PYTHONW = BASE_PY.replace('python.exe', 'pythonw.exe')
OUTSIDE_PY = r'C:\Python314\python.exe'
SUPERVISOR_OBSERVER = r'C:\Program Files\CoChem\SupervisorObservation4.2.7-windows-20261007-r3-v1\held-supervisor-observation-r3-v1.py'
RESOURCE_OBSERVER = r'C:\Program Files\CoChem\ResourceObservation4.2.7-windows-20261008-r3-v4\package\observe_resources.py'
# The two SYSTEM observer recorders (reported, never counted) and the 14 owner MCP clients alive at 17:22 (10 'cochem_pipeline
# mcp' clients, 4 Antigravity bridges), exactly as ps_toplevel_smoke.live_mcp_clients_20261011() describes them.
OBSERVERS = [proc(3132, BASE_PY, f'"{BASE_PY}" -I -B "{SUPERVISOR_OBSERVER}" --observe'),
             proc(9472, BASE_PY, f'"{BASE_PY}" -I -B "{RESOURCE_OBSERVER}" --run-observer')]
LIVE_CLIENTS = smoke.live_mcp_clients_20261011()
LIVE_CLIENT_PIDS = sorted(p['pid'] for p in LIVE_CLIENTS)
LIVE_BRIDGE_PIDS = sorted(p['pid'] for p in LIVE_CLIENTS if ' -m cochem_mcp ' in p['command_line'])
# Controller-like command lines (assembled, so that no single literal names a daemon start).
DAEMON = 'daemon'
SUPERVISOR_MODULE = 'cochem_' + 'supervisor'
PRESENCE_CASES = {
    # name: (one process, its class in stop-warden-r4)
    'bridge_r4_venv_codex': (proc(35760, R4_PY, bridge(R4_PY)), 'client'),
    'bridge_r4_venv_claude': (proc(17864, R4_PY, bridge(R4_PY, 'claude')), 'client'),
    'bridge_toolchain_codex': (proc(3192, BASE_PY, bridge(BASE_PY)), 'client'),
    'bridge_toolchain_claude': (proc(36468, BASE_PY, bridge(BASE_PY, 'claude')), 'client'),
    'pipeline_mcp_client': (proc(19036, R4_PY, f'"{R4_PY}" -I -B -m cochem_pipeline mcp --client-config {CLIENT_CONFIG}'), 'client'),
    # Outside stop-warden-r4's roots (r3, r4, the toolchain) a process is not counted, as before.
    'bridge_r5_venv_outside_the_r4_roots': (proc(120, R5_PY, bridge(R5_PY)), 'ignored'),
    'bridge_outside_the_runtime_roots': (proc(121, OUTSIDE_PY, bridge(OUTSIDE_PY)), 'ignored'),
    # Near misses of the bridge entry stay unclassified, so they still hold.
    'bridge_health_probe': (proc(100, R4_PY, bridge(R4_PY, tail=' --health')), 'unclassified'),
    'bridge_provider_gemini': (proc(101, R4_PY, bridge(R4_PY, 'gemini')), 'unclassified'),
    'bridge_provider_capitalised': (proc(102, R4_PY, bridge(R4_PY, 'Codex')), 'unclassified'),
    'bridge_other_config': (proc(103, R4_PY, bridge(R4_PY, config=r'C:\Users\ansac\CoChem427\other.json')), 'unclassified'),
    'bridge_config_other_case': (proc(104, R4_PY, bridge(R4_PY, config=BRIDGE_CONFIG.upper())), 'unclassified'),
    'bridge_isolated_flags': (proc(105, BASE_PY, f'"{BASE_PY}" -I -B -m cochem_mcp --provider codex --config {BRIDGE_CONFIG}'), 'unclassified'),
    'bridge_server_module': (proc(106, BASE_PY, f'"{BASE_PY}" -m cochem_mcp.server --provider codex --config {BRIDGE_CONFIG}'), 'unclassified'),
    'bridge_extra_argument': (proc(107, BASE_PY, bridge(BASE_PY, tail=' --verbose')), 'unclassified'),
    'bridge_trailing_newline': (proc(108, BASE_PY, bridge(BASE_PY, tail='\n')), 'unclassified'),
    'bridge_unquoted_image': (proc(109, BASE_PY, bridge(BASE_PY)[1:].replace('.exe"', '.exe', 1)), 'unclassified'),
    'bridge_pythonw_image': (proc(110, PYTHONW, bridge(PYTHONW), 'pythonw.exe'), 'unclassified'),
    'bridge_behind_cmd': (proc(111, BASE_PY, 'cmd /c ' + bridge(BASE_PY)), 'unclassified'),
    'other_rooted_python': (proc(118, R4_PY, f'"{R4_PY}" -I -B -c "print(1)"'), 'unclassified'),
    # Controller-like command lines are controllers from any image, before any client test.
    'controller_from_a_runtime_image': (proc(112, BASE_PY, f'"{BASE_PY}" {R4_ARGS}'), 'controller'),
    'controller_appended_to_a_bridge_line': (proc(113, R4_PY, bridge(R4_PY, tail=' cochem_pipeline ' + DAEMON)), 'controller'),
    'supervisor_from_any_image': (proc(114, OUTSIDE_PY, f'"{OUTSIDE_PY}" -m {SUPERVISOR_MODULE} {DAEMON}'), 'controller'),
    'provision_execution': (proc(115, R4_PY, f'"{R4_PY}" -I -B -m cochem_pipeline provision-' + 'execution'), 'controller'),
    'observer_recorder': (OBSERVERS[1], 'observer'),
    'uninspectable_python': (proc(119, None, None), 'uninspectable'),
}

# The real Get-ControllerPresence (re-dot-sourced after STUBS when those are loaded) over a fixture process list. With
# $script:liveDaemonArgs set, the fixture's alive pids are the task's controller (20664, toolchain python) and launcher
# (5320, r4 venv) running the task action, and $script:foreignPids are further such command lines.
PRESENCE_STUB = r'''
foreach($f in $ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Get-ControllerPresence'},$true)){. ([scriptblock]::Create($f.Extent.Text))}
$script:fxProcesses=@();$script:liveDaemonArgs=$null;$script:cimQueries=0
function Set-FixtureProcesses {param([string]$Json)$parsed=$Json|ConvertFrom-Json;$script:fxProcesses=@($parsed|ForEach-Object {$_})}
function Get-CimInstance {[CmdletBinding()]param([Parameter(Position=0)][string]$ClassName,[string]$Filter)
  if($ClassName -cne 'Win32_Process' -or $Filter){throw ('unexpected CIM query: '+$ClassName+' '+$Filter)}
  $script:cimQueries++
  foreach($p in @($script:fxProcesses)){[pscustomobject]@{ProcessId=[int]$p.pid;ParentProcessId=[int]$p.parent_pid;Name=[string]$p.name;ExecutablePath=$p.path;CommandLine=$p.command_line}}
  if($null -ne $script:liveDaemonArgs){
    foreach($id in @(@($script:alivePids)+@($script:foreignPids))){
      $image=$(if([int]$id -eq 5320){'R4PYVALUE'}else{'BASEPYVALUE'})
      [pscustomobject]@{ProcessId=[int]$id;ParentProcessId=$(if([int]$id -eq 20664){5320}else{1});Name='python.exe';ExecutablePath=$image;CommandLine=('"'+$image+'" '+$script:liveDaemonArgs)}}}}
function Get-NetTCPConnection {[CmdletBinding()]param($LocalPort,$State)
  if($null -ne $script:liveDaemonArgs -and $script:portListening){[pscustomobject]@{LocalPort=$LocalPort;State='Listen';OwningProcess=20664}}}
'''.replace('R4PYVALUE', R4_PY).replace('BASEPYVALUE', BASE_PY)


def run_file_json(body, workdir, timeout=300):
    """PRELUDE + body from a file (no command-line length limit), dot-sourced in one powershell.exe; its stdout as JSON."""
    path = Path(workdir) / 'body.ps1'
    path.write_text(PRELUDE + body, encoding='utf-8')
    command = "$ErrorActionPreference='Stop';. ([scriptblock]::Create([IO.File]::ReadAllText('" + ps(path) + "')))"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, result.stderr[-6000:]
    return json.loads(result.stdout)


def presence_table(workdir, cases, admin):
    lines = [PRESENCE_STUB, '$script:admin=' + ('$true' if admin else '$false') + ';$out=[ordered]@{}']
    for name, processes in cases.items():
        lines.append("Set-FixtureProcesses '" + ps(json.dumps(processes)) + "';$p=Get-ControllerPresence;$out['" + name + "']=[ordered]@{"
                     "controllers=@($p.controller_processes|ForEach-Object {[int]$_.pid});observers=@($p.observer_processes|ForEach-Object {[int]$_.pid});"
                     "clients=@($p.client_processes|ForEach-Object {[int]$_.pid});unclassified=@($p.unclassified_runtime_processes|ForEach-Object {[int]$_.pid});"
                     "uninspectable=$p.uninspectable_python_processes;listening=$p.listening;authoritative=$p.authoritative;alive=(Test-ControllerAlive $p)}")
    lines.append('$out|ConvertTo-Json -Depth 4 -Compress')
    return run_file_json('\n'.join(lines), workdir)


@pytest.fixture(scope='module')
def presence_results(tmp_path_factory):
    cases = {name: [process] for name, (process, _) in PRESENCE_CASES.items()}
    cases['live_17_22_inventory'] = LIVE_CLIENTS + OBSERVERS
    cases['live_inventory_and_a_gemini_bridge'] = LIVE_CLIENTS + OBSERVERS + [PRESENCE_CASES['bridge_provider_gemini'][0]]
    cases['live_inventory_and_a_controller'] = LIVE_CLIENTS + OBSERVERS + [PRESENCE_CASES['controller_from_a_runtime_image'][0]]
    return {admin: presence_table(tmp_path_factory.mktemp('presence'), cases, admin) for admin in (False, True)}


@pytest.mark.parametrize('admin', [False, True], ids=['unelevated', 'elevated'])
@pytest.mark.parametrize('case', list(PRESENCE_CASES))
def test_presence_admits_only_the_exact_antigravity_bridge_as_a_new_client(presence_results, case, admin):
    process, expected = PRESENCE_CASES[case]
    value = presence_results[admin][case]
    counts = {'controllers': [], 'observers': [], 'clients': [], 'unclassified': []}
    key = {'controller': 'controllers', 'observer': 'observers', 'client': 'clients', 'unclassified': 'unclassified'}.get(expected)
    if key:
        counts[key] = [process['pid']]
    assert {k: value[k] for k in counts} == counts, (case, value)
    assert value['uninspectable'] == (1 if expected == 'uninspectable' else 0) and value['authoritative'] is admin and value['listening'] == 0
    assert value['alive'] is (expected in ('controller', 'unclassified') or (expected == 'uninspectable' and admin)), (case, value)


def test_presence_over_the_live_17_22_inventory_counts_no_runtime_process(presence_results):
    for admin in (False, True):
        live = presence_results[admin]['live_17_22_inventory']
        assert sorted(live['clients']) == LIVE_CLIENT_PIDS and len(LIVE_BRIDGE_PIDS) == 4, 'all 14 owner MCP clients, the 4 bridges included'
        assert live['unclassified'] == [] and live['controllers'] == [] and sorted(live['observers']) == [3132, 9472] and live['alive'] is False
        gemini = presence_results[admin]['live_inventory_and_a_gemini_bridge']
        assert gemini['unclassified'] == [101] and sorted(gemini['clients']) == LIVE_CLIENT_PIDS and gemini['alive'] is True
        controller = presence_results[admin]['live_inventory_and_a_controller']
        assert controller['controllers'] == [112] and controller['unclassified'] == [] and controller['alive'] is True


LIVE_APPLY_CASES = {
    # name: (task overrides, extra processes, expected status or refusal)
    'already_stopped_enabled': ('@{State=3;Instances=0;LastTaskResult=267014}', [], 'WARDEN_ALREADY_STOPPED_AND_DISABLED'),
    'running': ('@{}', [], 'WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED'),
    'already_stopped_and_an_unknown_runtime_process': ('@{State=3;Instances=0}', [PRESENCE_CASES['bridge_provider_gemini'][0]],
                                                       'The task is stopped but a controller process, an unclassified runtime process or the loopback port is alive; nothing was changed.'),
    'running_and_an_unknown_runtime_process': ('@{}', [PRESENCE_CASES['bridge_isolated_flags'][0]],
                                               'Controller-like or unclassified runtime processes other than the proven controller are alive: 105; nothing was changed.'),
}


@pytest.mark.parametrize('case', list(LIVE_APPLY_CASES))
def test_stop_apply_path_with_the_live_mcp_clients_uses_the_real_presence(tmp_path, case):
    """The S2 -Apply (elevated) over the 17:22 host: the 14 MCP clients and the observers stay alive throughout."""
    overrides, extra, expected = LIVE_APPLY_CASES[case]
    target = tmp_path / 'stop-root'
    body = (TASK_FIXTURE + STUBS + PRESENCE_STUB + f"$folder=New-FixtureFolder {overrides};$script:targetRoot='{ps(target)}';$script:admin=$true;"
            f"Set-FixtureProcesses '{ps(json.dumps(LIVE_CLIENTS + OBSERVERS + extra))}';$script:liveDaemonArgs='{ps(R4_ARGS)}'" + r'''
      $failed=$false;$message='';$result=$null;try{$result=Invoke-StopWarden $folder ([ordered]@{install_receipt_sha256='a';revision_sha256='b'})}catch{$failed=$true;$message=$_.Exception.Message}
      [ordered]@{failed=$failed;message=$message;stops=$script:stops;events=@($script:events);enabled_writes=@($script:enabledWrites);enabled=$script:fxEnabled;
        cim_queries=$script:cimQueries;status=$(if($result){$result.status}else{$null})}|ConvertTo-Json -Depth 5 -Compress''')
    value = run_file_json(body, tmp_path)
    if not expected.startswith('WARDEN_'):
        assert value['failed'] and value['message'] == expected, value['message']
        assert value['stops'] == 0 and value['enabled_writes'] == [] and value['events'] == [] and not target.exists(), 'refused before the stop root'
        return
    assert not value['failed'], value['message']
    assert value['status'] == expected and value['enabled'] is False and value['cim_queries'] >= 2
    receipt = json.loads((target / 'stop-receipt.json').read_text(encoding='utf-8'))
    assert receipt['disable_requested'] is True and sorted(p['pid'] for p in receipt['observer_processes']) == [3132, 9472]
    if case == 'running':
        assert value['stops'] == 1 and value['events'] == SUCCESS_EVENTS and receipt['controller_exit']['controller_processes'] == []
    else:
        assert value['stops'] == 0 and receipt['mode'] == 'ALREADY_STOPPED'
    for write in value['enabled_writes']:
        assert write['value'] is False and write['instances'] == 0 and write['port_free'] is True and write['alive'] == 0


# --------------------------------------------------------------------------------------------------------------------
# Static binding rules (the two 17:22 failure classes, guarded here although stop-warden-r4.ps1 has neither)
# --------------------------------------------------------------------------------------------------------------------

def reviewed_imports(text):
    """The helpers Invoke-StopWardenMain imports by hash: [{path, names}], each file re-hashed against its pin."""
    main = text[text.index('function Invoke-StopWardenMain'):]
    copy_helper = re.search(r"\$copyHelper='([^']+)'", main).group(1)
    out = []
    for match in re.finditer(r"Import-ReviewedFunctions (\$copyHelper|\(Join-Path \$PSScriptRoot '([^']+)'\)) '([0-9a-f]{64})' @\(([^)]*)\)", main):
        path = copy_helper if match.group(1) == '$copyHelper' else str(ROOT / match.group(2))
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == match.group(3), path
        out.append({'path': path, 'names': re.findall(r"'([^']+)'", match.group(4))})
    return out


# Rule (a): no parameter variable is ever assigned at script or global scope, top level or through *-Variable (a script-scope
# parameter variable keeps its [Validate*] attributes, so '' can throw - the retarget-warden-r5 17:22 crash). Rule (b): no
# function but the main binds a name that an imported reviewed helper reads freely (by dynamic scope) - the stop-warden-r5
# Read-StartReceipt $held trap.
STATIC_RULES = r'''
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$spec=[IO.File]::ReadAllText('SPECPATH')|ConvertFrom-Json
$auto=@('_','null','true','false','args','this','input','PSScriptRoot','PSCommandPath','PSHOME','ErrorActionPreference','PSItem','LASTEXITCODE','matches',
        'PSCmdlet','MyInvocation','PSBoundParameters','Error','ExecutionContext','Host','PID','PWD','HOME','PSVersionTable','ProgressPreference',
        'VerbosePreference','WarningPreference','ConfirmPreference','DebugPreference','InformationPreference','foreach','switch','StackTrace')
function Get-BoundNames {param($Ast)
  foreach($p in $Ast.FindAll({param($n)$n -is [Management.Automation.Language.ParameterAst]},$true)){$p.Name.VariablePath.UserPath}
  foreach($s in $Ast.FindAll({param($n)$n -is [Management.Automation.Language.AssignmentStatementAst]},$true)){
    $l=$s.Left;while($l -is [Management.Automation.Language.AttributedExpressionAst]){$l=$l.Child}
    if($l -is [Management.Automation.Language.VariableExpressionAst] -and -not ($l.VariablePath.IsScript -or $l.VariablePath.IsGlobal)){$l.VariablePath.UserPath}}
  foreach($s in $Ast.FindAll({param($n)$n -is [Management.Automation.Language.ForEachStatementAst]},$true)){$s.Variable.VariablePath.UserPath}}
$free=[Collections.Generic.SortedSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach($helper in @($spec.helpers)){
  $t=$null;$e=$null;$h=[Management.Automation.Language.Parser]::ParseFile([string]$helper.path,[ref]$t,[ref]$e)
  foreach($name in @($helper.names)){
    $fn=@($h.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object {$_.Name -ceq $name})
    if($fn.Count -ne 1){throw ('reviewed helper not found exactly once: '+$name)}
    $bound=[Collections.Generic.HashSet[string]]::new([string[]]@(@(Get-BoundNames $fn[0])+$auto),[StringComparer]::OrdinalIgnoreCase)
    foreach($v in $fn[0].FindAll({param($n)$n -is [Management.Automation.Language.VariableExpressionAst]},$true)){
      $p=$v.VariablePath;if($p.IsScript -or $p.IsGlobal -or $p.IsDriveQualified -or $p.IsPrivate){continue}
      if(-not $bound.Contains($p.UserPath)){$null=$free.Add($p.UserPath)}}}}
$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile('SCRIPTPATH',[ref]$t,[ref]$e)
$params=@($a.ParamBlock.Parameters|ForEach-Object {$_.Name.VariablePath.UserPath})
$writes=@()
foreach($s in $a.FindAll({param($n)$n -is [Management.Automation.Language.AssignmentStatementAst]},$true)){
  $l=$s.Left;while($l -is [Management.Automation.Language.AttributedExpressionAst]){$l=$l.Child}
  if($l -isnot [Management.Automation.Language.VariableExpressionAst]){continue}
  $path=$l.VariablePath;$name=$path.UserPath -replace '^(?i)(script|global|local|private):',''
  if($params -notcontains $name){continue}
  $inFunction=$false;$q=$s.Parent;while($null -ne $q){if($q -is [Management.Automation.Language.FunctionDefinitionAst]){$inFunction=$true;break};$q=$q.Parent}
  if($path.IsScript -or $path.IsGlobal -or -not $inFunction){$writes+=('line '+$s.Extent.StartLineNumber+': '+$s.Extent.Text)}}
foreach($c in $a.FindAll({param($n)$n -is [Management.Automation.Language.CommandAst]},$true)){
  $cn=$c.GetCommandName();if($cn -and @('Set-Variable','New-Variable','Clear-Variable','Remove-Variable','sv','nv','clv','rv') -contains $cn){$writes+=('line '+$c.Extent.StartLineNumber+': '+$c.Extent.Text)}}
$shadows=@()
foreach($fn in $a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){
  if($fn.Name -ceq 'Invoke-StopWardenMain'){continue}
  foreach($name in @(Get-BoundNames $fn|Sort-Object -Unique)){if($free.Contains($name)){$shadows+=($fn.Name+' binds $'+$name)}}}
[ordered]@{params=$params;writes=$writes;free=@($free);shadows=$shadows}|ConvertTo-Json -Depth 4 -Compress
'''


def test_no_parameter_variable_is_assigned_and_no_function_shadows_what_a_reviewed_helper_reads(tmp_path):
    text = SCRIPT.read_text(encoding='ascii')
    helpers = reviewed_imports(text)
    assert [h['names'] for h in helpers] == [['Assert-NoReparseAncestors', 'Assert-ProtectedPath', 'New-CodeAcl', 'New-ProtectedDirectory', 'Initialize-FileIdentity', 'Open-VerifiedFile'],
                                             ['Read-R3Control', 'Read-R3Text'], ['Assert-RegisteredTaskAcl', 'Write-RegistrationControl'], ['Assert-CodeTreeOnce']]
    (tmp_path / 'spec.json').write_text(json.dumps({'helpers': helpers}), encoding='utf-8')
    (tmp_path / 'rules.ps1').write_text(STATIC_RULES.replace('SPECPATH', ps(tmp_path / 'spec.json')).replace('SCRIPTPATH', ps(SCRIPT)), encoding='utf-8')
    command = "$ErrorActionPreference='Stop';. ([scriptblock]::Create([IO.File]::ReadAllText('" + ps(tmp_path / 'rules.ps1') + "')))"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-4000:]
    value = json.loads(result.stdout)
    assert value['params'] == ['Apply', 'Attempt', 'IdleWaitSeconds', 'ExitWaitSeconds']
    assert value['writes'] == [], 'a script-scope parameter variable keeps its [Validate*] attributes; never assign one'
    assert value['free'] == ['held'], 'Read-R3Control adds each stream to the caller-scope $held list'
    assert value['shadows'] == [], 'only Invoke-StopWardenMain may bind $held (its stream list)'


# --------------------------------------------------------------------------------------------------------------------
# Top-level plan-mode smoke tests: the real script top level through ps_toplevel_smoke (host stubbed, never -Apply)
# --------------------------------------------------------------------------------------------------------------------

PLAN_SCHEMA = 'cochem-warden-stop-plan/1'
PRESENCE_HOLD = 'The task is stopped but a controller process, an unclassified runtime process or the loopback port is alive'
# The 17:22 host: the Warden task on the r4-v1 action, enabled, no instance (what S2 disables), the other managed daemons
# stopped and disabled. The two SYSTEM observer recorders are opaque to the unelevated token (no image, no command line).
SMOKE_TASKS = {
    'CoChem-4.2.7-Warden': {'enabled': True, 'state': 3, 'instances': 0, 'last_task_result': 267014, 'xml': TASK_XML, 'sddl': SDDL,
                            'principal': {'user_id': 'S-1-5-18', 'logon_type': 5, 'run_level': 1},
                            'settings': {'multiple_instances': 2, 'execution_time_limit': 'PT0S', 'restart_count': 0, 'allow_demand_start': True},
                            'actions': [{'path': R4_PY, 'arguments': R4_ARGS, 'working_directory': R4_ROOT}], 'triggers': []},
    'CoChem-4.2.7-Supervisor': {'enabled': False, 'state': 1, 'instances': 0},
    'CoChem-4.2.2-Warden': {'enabled': False, 'state': 1, 'instances': 0},
    'CoChem-4.2.3-Supervisor': {'enabled': False, 'state': 1, 'instances': 0},
}
SMOKE_SYSTEM_OBSERVERS = [dict(p, owner='NT AUTHORITY\\SYSTEM', pid=p['pid'] + 1) for p in OBSERVERS]
# S2 of the sitting (-Attempt vN, here without its apply switch), the defaults and a later attempt with explicit waits.
SMOKE_CALLS = [('-Attempt', 'v1'), (), ('-Attempt', 'v2', '-IdleWaitSeconds', '120', '-ExitWaitSeconds', '90')]


def smoke_stub(tasks=None, extra=()):
    stub = smoke.default_stub()
    stub['processes'] = smoke.live_mcp_clients_20261011() + SMOKE_SYSTEM_OBSERVERS + [dict(p, owner='AETHERDESK\\ansac') for p in extra]
    if tasks:
        stub['tasks'] = dict({'*': 'denied'}, **tasks)
    return stub


def smoke_plan(args, stub, invocation='file'):
    assert smoke.apply_argument(args) is None
    result = smoke.run_toplevel(SCRIPT, args, stub=stub, invocation=invocation)
    assert smoke.plan_mode_outcome(result, plan_schema=PLAN_SCHEMA) == 'plan', result.describe()
    plan = result.plan
    attempt = args[args.index('-Attempt') + 1] if '-Attempt' in args else 'v1'
    assert plan['attempt'] == attempt and plan['target_root'] == str(COCHEM / f'WardenStop4.2.7-windows-20261010-r4-{attempt}')
    assert plan['tasks_changed'] == 0 and plan['ended'] is False and plan['disabled'] is False and plan['processes_killed'] is False
    assert plan['administrator'] is False and plan['automatic_retry_allowed'] is False
    assert not result.calls('Schedule.Service.Task.Stop') and not result.calls('Schedule.Service.Task.Enabled'), 'no End, no disable'
    return plan


def assert_live_presence(presence):
    assert sorted(p['pid'] for p in presence['client_processes']) == LIVE_CLIENT_PIDS, 'all 14 owner MCP clients are clients'
    assert presence['unclassified_runtime_processes'] == [] and presence['controller_processes'] == [] and presence['listening'] == 0
    assert presence['uninspectable_python_processes'] == 2 and presence['authoritative'] is False, 'the SYSTEM observers are opaque unelevated'


@pytest.mark.parametrize('invocation', ['file', 'command'])
@pytest.mark.parametrize('args', SMOKE_CALLS, ids=['sitting_S2_v1', 'defaults', 'v2_explicit_waits'])
def test_toplevel_plan_smoke_with_the_live_mcp_clients(args, invocation):
    plan = smoke_plan(args, smoke_stub(), invocation)
    assert plan['stop_mode'] == 'DEFERRED' and plan['task_readable'] is False
    assert any('unreadable without elevation' in hold for hold in plan['holds']), plan['holds']
    assert_live_presence(plan['controller_presence'])
    assert plan['idle_wait_seconds'] == 120 and plan['exit_wait_seconds'] == 90


@pytest.mark.parametrize('invocation', ['file', 'command'])
def test_toplevel_plan_already_stopped_disable_only_path_does_not_hold_on_the_mcp_clients(invocation):
    # The 17:26 S2 hold, reproduced top level: a readable r4-v1 task, enabled, no instance -> ALREADY_STOPPED (disable only).
    plan = smoke_plan(('-Attempt', 'v1'), smoke_stub(SMOKE_TASKS), invocation)
    assert plan['stop_mode'] == 'ALREADY_STOPPED' and plan['task_readable'] is True and plan['task_summary']['enabled'] is True
    assert not any(PRESENCE_HOLD in hold for hold in plan['holds']), plan['holds']
    assert_live_presence(plan['controller_presence'])
    assert [d['state'] for d in plan['other_daemon_tasks']] == ['STOPPED_DISABLED'] * 3
    # What remains held is the smoke host's virtual protected tree (no readable ACL), never a process.
    assert plan['holds'] and all(hold.startswith(('r4 runtime is not the reviewed build:', 'Loopback probe:')) for hold in plan['holds']), plan['holds']


@pytest.mark.parametrize('name', ['bridge_provider_gemini', 'bridge_isolated_flags', 'other_rooted_python', 'controller_from_a_runtime_image'])
def test_toplevel_plan_already_stopped_still_holds_on_any_other_runtime_process(name):
    process, expected = PRESENCE_CASES[name]
    plan = smoke_plan(('-Attempt', 'v1'), smoke_stub(SMOKE_TASKS, [process]))
    assert plan['stop_mode'] == 'ALREADY_STOPPED'
    assert any(PRESENCE_HOLD in hold for hold in plan['holds']), plan['holds']
    presence = plan['controller_presence']
    key = 'controller_processes' if expected == 'controller' else 'unclassified_runtime_processes'
    assert [p['pid'] for p in presence[key]] == [process['pid']] and sorted(p['pid'] for p in presence['client_processes']) == LIVE_CLIENT_PIDS
