"""Inert Windows PowerShell 5.1 harness for retarget-warden-r5.ps1 (CUTOVER-RETARGET, r5 sitting 2026-10-11).

Nothing here registers, updates, enables, runs or stops a task, elevates, writes under C:\\Program Files or
C:\\ProgramData, or talks to the live controller. The functions are extracted from the script's AST and
dot-sourced into a throwaway powershell.exe (Windows PowerShell 5.1); every system call is a stub: the Task
Scheduler COM objects (GetTask, RegisterTaskDefinition, Enabled, Run, GetInstances), robocopy, Get-CimInstance,
Get-NetTCPConnection, Invoke-CimMethod and the /health client. The script is never run with -Apply. Its real top level
runs only through ps_toplevel_smoke.py, in plan mode, with every host command stubbed or denied (the last section):
the AST fixtures above cannot see the real param block, binding and script-scope parameter variables, which is where
the 2026-10-11 17:22 R4-RESTORE died. The only other child processes are the repository interpreter (a loopback bind on
an ephemeral port, never 47824) and the pinned backup helper against temporary SQLite files. A few tests read the
installed r4 artefacts under C:\\Program Files read-only to recompute pins; they skip when absent.
"""
import hashlib
import json
from pathlib import Path
import re
import shlex
import socket
import sqlite3
import subprocess
import sys

import pytest

import ps_toplevel_smoke as smoke

ROOT = Path(__file__).parent
SCRIPT = ROOT / 'retarget-warden-r5.ps1'
PREDECESSOR = ROOT / 'retarget-warden-r4.ps1'
STOP_R4 = ROOT / 'stop-warden-r4.ps1'
HELPER = ROOT / 'backup-private-databases-r4.py'
REGISTER = ROOT / 'register-stopped-warden-r3.ps1'
CHECK_R3 = ROOT / 'check-worker-native-status-r3.ps1'
INSPECTION = ROOT / 'protected-code-inspection-v4.ps1'
COPY_HELPER = Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1')
TEST_PY = sys.executable

PF = Path(r'C:\Program Files\CoChem')
R3_ROOT = r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r3'
R4_ROOT = r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4'
R4_PY = R4_ROOT + r'\.venv\Scripts\python.exe'
BASE_PY = r'C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe'
COMMISSIONING_CONFIG = r'C:\Program Files\CoChem\WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json'
R4_RESTORE_CONFIG = R4_ROOT + r'\pipeline.json'
QUEUE_R4V1 = r'C:\ProgramData\CoChemPipeline427\private\queue-retarget-20261010-r4-v1'
R4V1_ARGS = f'-I -B -m cochem_pipeline daemon --config "{COMMISSIONING_CONFIG}" --queue-launch-output "{QUEUE_R4V1}"'
R4V1_ROOT = PF / 'WardenRetarget4.2.7-windows-20261010-r4-v1'
R5_ROOT = r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5'
R5_PY = R5_ROOT + r'\.venv\Scripts\python.exe'
R5_CFG = r'C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-r5-v1\pipeline.json'
R5_QUEUE_ROOT = r'C:\ProgramData\CoChemPipeline427\private\queue-launch-r5'
R5_ARGS = f'-I -B -m cochem_pipeline daemon --config "{R5_CFG}" --queue-launch-output-root "{R5_QUEUE_ROOT}" --docker-wait-seconds 900'
SDDL = 'O:BAG:BAD:PAI(A;;FA;;;SY)(A;;FA;;;BA)'
CONFIG_PIN = '135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'


def ps(value) -> str:
    return str(value).replace("'", "''")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


PRELUDE = r'''
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
foreach($m in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$m\$m.psd1")}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('__SCRIPT__',[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
foreach($f in @($ast.EndBlock.Statements|Where-Object {$_ -is [Management.Automation.Language.FunctionDefinitionAst]})){. ([scriptblock]::Create($f.Extent.Text))}
$regAst=[Management.Automation.Language.Parser]::ParseFile('__REGISTER__',[ref]$tokens,[ref]$errors)
foreach($f in @($regAst.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Assert-RegisteredTaskAcl'},$true))){. ([scriptblock]::Create($f.Extent.Text))}
$script:Target='r5';$script:Attempt='v1';$script:SourceAttempt='';$script:StopAttempt='';$script:scriptDirectory='__ROOT__'
Set-RetargetConstants
$script:admin=$false;$script:startWaitSeconds=3;$script:healthPollSeconds=0
$held=[Collections.Generic.List[IO.FileStream]]::new()
$script:readControls=@()
# The real Read-R3Control (check-worker-native-status-r3.ps1) keeps its deny-write handle open through $held.Add($stream), and
# $held resolves dynamically to the CALLER's variable: the stub touches it the same way, so a function that shadows $held
# with a local (a JSON record, a held-start result) fails here exactly as it fails with the real helper (DIAG-BINDING 4-6).
function Read-R3Control {param([string]$Path,[string]$Hash='',[long]$Maximum=16777216)
  $held.Add($null);$held.RemoveAt($held.Count-1)
  if(-not (Test-Path -LiteralPath $Path -PathType Leaf)){throw ('Fixture control missing: '+$Path)}
  $bytes=[IO.File]::ReadAllBytes($Path);if($bytes.Length -gt $Maximum){throw 'Bounded r3 control length differs.'}
  $sha=[Security.Cryptography.SHA256]::Create();try{$actual=[BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
  if($Hash -and $actual -cne $Hash){throw ('Source digest changed: '+$Path)}
  $script:readControls+=$Path
  [pscustomobject]@{Stream=[IO.MemoryStream]::new($bytes);Sha256=$actual;Length=$bytes.Length}}
function Read-R3Text {param($Control)$Control.Stream.Position=0;$reader=[IO.StreamReader]::new($Control.Stream,[Text.Encoding]::UTF8,$true,4096,$true);try{$reader.ReadToEnd()}finally{$reader.Dispose()}}
function Write-RegistrationControl {param([string]$Path,[string]$Text)
  $stream=[IO.FileStream]::new($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try{$raw=[Text.UTF8Encoding]::new($false).GetBytes($Text);$stream.Write($raw,0,$raw.Length)}finally{$stream.Dispose()}
  (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
function Write-FixtureJson {param([string]$Path,$Object)$null=[IO.Directory]::CreateDirectory((Split-Path -Parent $Path));[IO.File]::WriteAllText($Path,($Object|ConvertTo-Json -Depth 10))}
function Merge-Hash {param($A,$B)$c=@{};foreach($k in @($A.Keys)){$c[$k]=$A[$k]};foreach($k in @($B.Keys)){$c[$k]=$B[$k]};$c}
$script:fixtureR5Root='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5'
$script:fixtureR5Py=Join-Path $script:fixtureR5Root '.venv\Scripts\python.exe'
$script:fixtureR5Config='C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-r5-v1\pipeline.json'
$script:fixtureR5Args=Get-R5Arguments $script:fixtureR5Config $script:r5QueueRoot 900
$script:fixtureLineage=[ordered]@{retarget_receipt_sha256=('1'*64);start_receipt_sha256=('2'*64);task_xml_after_sha256=$script:r4v1TaskXmlPin;old_controller=[ordered]@{pid=20664;instance_id='61497bdab0514590b88fd0cab689a404';process_started_at=1791680462.6393604}}
function New-FixtureR5Runtime {[ordered]@{root=$script:fixtureR5Root;python=$script:fixtureR5Py;source_root=(Join-Path $script:fixtureR5Root '.venv\Lib');install_after_path=(Join-Path $script:fixtureR5Root 'install-after.json');
  install_after_sha256=('a'*64);source_manifest_sha256=('b'*64);revision_sha256=('c'*64);reviewed_repairs=@('src/cochem_pipeline/__main__.py');venv_python_sha256=('f'*64)}}
function New-FixtureContext {param([string]$Target,[string]$ConfigPath=$script:fixtureR5Config)
  if($Target -ceq 'r5'){return New-TargetContext 'r5' (New-FixtureR5Runtime) ([ordered]@{path=$ConfigPath;sha256=('d'*64);length=10;mode='GEMINI_CONTRACT'})}
  New-TargetContext 'r4' ([ordered]@{install_receipt_sha256=$script:r4InstallPin;revision_sha256=$script:r4RevisionPin;source_manifest_sha256=$script:r4ManifestPin}) $null}
'''

FIXTURE = r'''
$script:registered=@();$script:runs=0;$script:runCalls=0;$script:xmlExtra=''
function New-FixtureTrigger {param([int]$Type=9,[string]$UserId='AETHERDESK\ansac',[string]$Delay='PT1M',[bool]$Enabled=$true)
  [pscustomobject]@{Type=$Type;Enabled=$Enabled;UserId=$UserId;Delay=$Delay;StartBoundary='';EndBoundary='';ExecutionTimeLimit='';Id='';Repetition=[pscustomobject]@{Interval='';Duration='';StopAtDurationEnd=$false}}}
function New-FixtureTriggerWith {param([hashtable]$Set)$t=New-FixtureTrigger -Enabled $false;foreach($k in @($Set.Keys)){if($k -ceq 'Interval'){$t.Repetition.Interval=$Set[$k]}else{$t.$k=$Set[$k]}};$t}
function Get-FixtureXml {
  $enabled='';if(-not $script:taskEnabled){$enabled='<Enabled>false</Enabled>'}
  $trig=(@($script:triggerItems)|ForEach-Object {'<LogonTrigger>'+$(if(-not $_.Enabled){'<Enabled>false</Enabled>'}else{''})+'<UserId>'+[Security.SecurityElement]::Escape([string]$_.UserId)+'</UserId><Delay>'+$_.Delay+'</Delay></LogonTrigger>'}) -join ''
  '<Task xmlns="urn:x"><RegistrationInfo><Description>'+[Security.SecurityElement]::Escape([string]$script:definition.RegistrationInfo.Description)+'</Description></RegistrationInfo>'+
  '<Principals><Principal><UserId>S-1-5-18</UserId></Principal></Principals><Settings>'+$enabled+'<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>'+$script:xmlExtra+'</Settings>'+
  '<Triggers>'+$trig+'</Triggers><Actions><Exec><Command>'+[Security.SecurityElement]::Escape([string]$script:action.Path)+'</Command><Arguments>'+[Security.SecurityElement]::Escape([string]$script:action.Arguments)+
  '</Arguments><WorkingDirectory>'+[Security.SecurityElement]::Escape([string]$script:action.WorkingDirectory)+'</WorkingDirectory></Exec></Actions></Task>'}
function Get-FixtureXmlWith {param([bool]$TaskEnabled,$TriggerEnabled)
  # The fixture task XML as it reads with the given task and trigger Enabled flags; the live flags are restored.
  $savedTask=$script:taskEnabled;$savedTriggers=@($script:triggerItems|ForEach-Object {[bool]$_.Enabled})
  try{$script:taskEnabled=$TaskEnabled;if($null -ne $TriggerEnabled){foreach($t in $script:triggerItems){$t.Enabled=[bool]$TriggerEnabled}};Get-FixtureXml}
  finally{$script:taskEnabled=$savedTask;for($i=0;$i -lt $savedTriggers.Count;$i++){$script:triggerItems[$i].Enabled=$savedTriggers[$i]}}}
function Set-FixtureTriggerEnabled {param([bool]$Enabled)foreach($t in $script:triggerItems){$t.Enabled=$Enabled}}
function New-FixtureFolder {param([hashtable]$Overrides=@{})
  $v=@{Enabled=$true;State=3;Instances=0;LastTaskResult=0;UserId='S-1-5-18';LogonType=5;RunLevel=1;Actions=1;MultipleInstances=2;ExecutionTimeLimit='PT0S';RestartCount=0;AllowDemandStart=$true;
       ActionType=0;Path=$script:r4Python;Arguments=(Get-ExpectedArguments $script:commissioningConfig $script:queueR4v1);WorkingDirectory=$script:r4Root;Sddl='__SDDL__';Triggers=@();
       DenyDefinition=$false;DenyGetTask=$false;Absent=$false;RegisterApplies=$true;RunState=4;RunInstances=1;RunThrows=$false;DenyAfterRun=$false;DenyAfterRegister=$false;
       ExtraAfterRegister='';TriggerUserAfterRegister=$null;RegisterIgnoresEnabled=$false;EnableThrows=$false;DisableThrows=$false;RunningGuid='{00000000-0000-0000-0000-00000000aaaa}';
       TriggerEnableIgnored=$false;SecondRegisterThrows=$false;Description='d'}
  foreach($k in @($Overrides.Keys)){$v[$k]=$Overrides[$k]}
  $script:fx=$v;$script:xmlExtra='';$script:registered=@();$script:runs=0;$script:runCalls=0;$script:events=@();$script:taskEnabled=[bool]$v.Enabled
  $script:action=[pscustomobject]@{Type=$v.ActionType;Path=$v.Path;Arguments=$v.Arguments;WorkingDirectory=$v.WorkingDirectory}
  $script:triggerItems=[Collections.Generic.List[object]]::new();foreach($t in @($v.Triggers|Where-Object {$null -ne $_})){$script:triggerItems.Add($t)}
  $script:original=@{Path=$v.Path;Arguments=$v.Arguments;WorkingDirectory=$v.WorkingDirectory;Triggers=@($script:triggerItems.ToArray())}
  $triggers=[pscustomobject]@{}
  $triggers|Add-Member ScriptProperty Count {$script:triggerItems.Count}
  $triggers|Add-Member ScriptMethod Item {param($i)$script:triggerItems[$i-1]}
  $triggers|Add-Member ScriptMethod Clear {$script:triggerItems.Clear()}
  $triggers|Add-Member ScriptMethod Create {param($type)$t=New-FixtureTrigger $type '' '';$script:triggerItems.Add($t);$t}
  $actions=[pscustomobject]@{Count=$v.Actions};$actions|Add-Member ScriptMethod Item {param($i)if($script:fx.DenyDefinition){throw [Runtime.InteropServices.COMException]::new('denied',-2147024891)};$script:action}
  $script:definition=[pscustomobject]@{Principal=[pscustomobject]@{UserId=$v.UserId;LogonType=$v.LogonType;RunLevel=$v.RunLevel};Triggers=$triggers;Actions=$actions;
     Settings=[pscustomobject]@{MultipleInstances=$v.MultipleInstances;ExecutionTimeLimit=$v.ExecutionTimeLimit;RestartCount=$v.RestartCount;AllowDemandStart=$v.AllowDemandStart;Enabled=[bool]$v.Enabled};
     RegistrationInfo=[pscustomobject]@{Description=$v.Description}}
  $script:task=[pscustomobject]@{State=$v.State;LastTaskResult=$v.LastTaskResult}
  # RegisteredTask.Definition: Settings.Enabled reads the live task state, as a fresh COM definition does.
  $script:task|Add-Member ScriptProperty Definition {$script:definition.Settings.Enabled=$script:taskEnabled;$script:definition}
  # RegisteredTask.Enabled: every write is an event; the fixture can refuse an enable or a disable.
  $script:task|Add-Member ScriptProperty Enabled {$script:taskEnabled} {param($value)
    if([bool]$value -and $script:fx.EnableThrows){throw [Runtime.InteropServices.COMException]::new('enable refused',-2147024891)}
    if(-not [bool]$value -and $script:fx.DisableThrows){throw [Runtime.InteropServices.COMException]::new('disable refused',-2147024891)}
    $script:events+=('enable:'+[bool]$value);$script:taskEnabled=[bool]$value}
  $script:task|Add-Member ScriptProperty Xml {Get-FixtureXml}
  $script:instances=$v.Instances
  $script:task|Add-Member ScriptMethod GetInstances {param($n)$items=[pscustomobject]@{Count=$script:instances};$items|Add-Member ScriptMethod Item {param($i)[pscustomobject]@{InstanceGuid=$script:fx.RunningGuid}};$items}
  $script:task|Add-Member ScriptMethod GetSecurityDescriptor {param($n)$script:fx.Sddl}
  # Task Scheduler End (IRegisteredTask.Stop): recorded so a test can prove it is never requested.
  $script:task|Add-Member ScriptMethod Stop {param($flags)$script:events+='end'}
  # Task Scheduler refuses to run a disabled task (SCHED_E_TASK_DISABLED), which proves the enable comes first.
  $script:task|Add-Member ScriptMethod Run {param($a)$script:runCalls++;$script:events+='run'
    if(-not $script:taskEnabled){throw [Runtime.InteropServices.COMException]::new('task disabled',-2147216602)}
    if($script:fx.RunThrows){throw [Runtime.InteropServices.COMException]::new('run refused',-2147216615)};$script:runs++;$script:task.State=$script:fx.RunState;$script:instances=$script:fx.RunInstances;$inst=[pscustomobject]@{InstanceGuid='{00000000-0000-0000-0000-00000000aaaa}'};$inst|Add-Member ScriptMethod Refresh {};$inst}
  $folder=[pscustomobject]@{}
  $folder|Add-Member ScriptMethod GetTask {param($name)
    if($script:fx.Absent){throw [Runtime.InteropServices.COMException]::new('absent',-2147024894)}
    if($script:fx.DenyGetTask -or ($script:fx.DenyAfterRun -and $script:runs -gt 0) -or ($script:fx.DenyAfterRegister -and @($script:registered).Count -gt 0)){throw [Runtime.InteropServices.COMException]::new('denied',-2147024891)}
    if($name -cne 'CoChem-4.2.7-Warden'){throw [Runtime.InteropServices.COMException]::new('absent',-2147024894)};$script:task}
  $folder|Add-Member ScriptMethod RegisterTaskDefinition {param($name,$def,$flags,$user,$pw,$logon,$sddl)
    # Each registration records the task and trigger Enabled flags it carries, the task events and /health samples before it.
    $script:registered+=[pscustomobject]@{name=$name;flags=$flags;user=$user;logon=$logon;sddl=$sddl;password_is_null=($null -eq $pw);task_enabled=[bool]$def.Settings.Enabled;
      trigger_enabled=@($script:triggerItems|ForEach-Object {[bool]$_.Enabled});events_before=@($script:events);health_before=$(if(Test-Path variable:script:healthIndex){$script:healthIndex}else{$null})}
    # The second-phase update is the one registered with the task enabled (every TASK_UPDATE registers it disabled).
    if([bool]$def.Settings.Enabled -and $script:fx.SecondRegisterThrows){foreach($t in $script:triggerItems){$t.Enabled=$false};throw [Runtime.InteropServices.COMException]::new('second update refused',-2147024891)}
    if(-not $script:fx.RegisterApplies){$script:action.Path=$script:original.Path;$script:action.WorkingDirectory=$script:original.WorkingDirectory;$script:action.Arguments=$script:original.Arguments;$script:triggerItems.Clear();foreach($t in @($script:original.Triggers)){$script:triggerItems.Add($t)}}
    if($script:fx.ExtraAfterRegister){$script:xmlExtra=$script:fx.ExtraAfterRegister}
    if($null -ne $script:fx.TriggerUserAfterRegister -and $script:triggerItems.Count){$script:triggerItems[0].UserId=$script:fx.TriggerUserAfterRegister}
    if([bool]$def.Settings.Enabled -and $script:fx.TriggerEnableIgnored){foreach($t in $script:triggerItems){$t.Enabled=$false}}
    # Registering a definition applies its Settings.Enabled (unless the fixture is told to ignore it).
    if($script:fx.RegisterApplies -and -not $script:fx.RegisterIgnoresEnabled){$script:taskEnabled=[bool]$def.Settings.Enabled}}
  $folder}
function Get-R5LiveOverrides {param([string]$ConfigPath=$script:fixtureR5Config)
  @{Path=$script:fixtureR5Py;Arguments=(Get-R5Arguments $ConfigPath $script:r5QueueRoot 900);WorkingDirectory=$script:fixtureR5Root;Triggers=@(New-FixtureTrigger -Enabled $false);Enabled=$false;State=1}}
function Get-R4RestoreLiveOverrides {param([string]$QueueAttempt='v1')
  @{Path=$script:r4Python;Arguments=(Get-ExpectedArguments $script:r4RestoreConfig (Join-Path $script:privateRoot ('queue-restart-20261011-r4-'+$QueueAttempt)));WorkingDirectory=$script:r4Root;Triggers=@();Enabled=$false;State=1}}
function Get-FixtureRetargetRoot {param([string]$Target)Join-Path $script:base ('WardenRetarget4.2.7-windows-20261011-'+$Target+'-'+$script:SourceAttempt)}
function Get-FixtureFileSha {param([string]$Path)if(-not (Test-Path -LiteralPath $Path)){return $null};(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
function Write-FixtureText {param([string]$Path,[string]$Text)$null=[IO.Directory]::CreateDirectory((Split-Path -Parent $Path));[IO.File]::WriteAllText($Path,$Text,[Text.UTF8Encoding]::new($false));Get-TaskXmlSha256 $Text}
function Get-FixtureHead {param([string]$Target)
  # The head fields this sitting's receipts carry for -SourceAttempt and the live action.
  $r5=($Target -ceq 'r5')
  [ordered]@{target=$Target;attempt=$script:SourceAttempt;task_name='CoChem-4.2.7-Warden';runtime_root=$(if($r5){$script:fixtureR5Root}else{$script:r4Root});
    config_path=$(if($r5){$script:fixtureR5Config}else{$script:r4RestoreConfig});config_sha256=$(if($r5){'d'*64}else{$script:configPin});
    action=[ordered]@{execute=$script:action.Path;arguments=$script:action.Arguments;working_directory=$script:action.WorkingDirectory};triggers=(Get-TriggerReceiptForm $Target)}}
function Get-FixtureLiveTrigger {param([string]$Target)if($Target -ceq 'r5' -and $script:triggerItems.Count -eq 1){return [bool]$script:triggerItems[0].Enabled};$null}
function Write-FixtureRetarget {param([string]$Target='r5',[hashtable]$Receipt=@{},[switch]$RetargetHeld,[string]$Description)
  # This sitting's retarget receipt of -SourceAttempt: the live action, registered disabled with its logon trigger disabled,
  # its warden-task-after.xml, and the attempt's description (set on the live task first, as that retarget did).
  if(-not $PSBoundParameters.ContainsKey('Description')){$Description=Get-TargetDescription $Target $script:SourceAttempt}
  $script:definition.RegistrationInfo.Description=$Description
  $root=Get-FixtureRetargetRoot $Target
  $afterSha=Write-FixtureText (Join-Path $root 'warden-task-after.xml') (Get-FixtureXmlWith $false $false)
  $r=[ordered]@{schema='cochem-warden-retarget/3';status=$(if($Target -ceq 'r5'){'WARDEN_RETARGETED_TO_R5_NOT_STARTED'}else{'WARDEN_RETARGETED_TO_R4_NOT_STARTED'})}
  $head=Get-FixtureHead $Target;foreach($k in @($head.Keys)){$r[$k]=$head[$k]}
  $r['enabled_after']=$false;$r['trigger_enabled_after']=$(if($Target -ceq 'r5'){$false}else{$null});$r['task_xml_sha256']=$afterSha;$r['task_xml_after_sha256']=$afterSha
  foreach($k in @($Receipt.Keys)){$r[$k]=$Receipt[$k]}
  Write-FixtureJson (Join-Path $root 'retarget-receipt.json') $r
  if($RetargetHeld){Write-FixtureJson (Join-Path $root 'retarget-held.json') @{x=1}}
  $root}
function Write-FixtureStartIntent {param([string]$Target,[hashtable]$Intent=@{})
  $root=Get-FixtureRetargetRoot $Target
  $i=[ordered]@{schema='cochem-warden-start-intent/3';attempt=$script:SourceAttempt;target=$Target;task_name='CoChem-4.2.7-Warden';
     retarget_receipt_sha256=(Get-FixtureFileSha (Join-Path $root 'retarget-receipt.json'))}
  foreach($k in @($Intent.Keys)){$i[$k]=$Intent[$k]}
  Write-FixtureJson (Join-Path $root 'start-intent.json') $i}
function Write-FixtureStarted {param([string]$Target='r5',[hashtable]$Start=@{},[switch]$NoStartReceipt,[switch]$NoIntent,[switch]$StartHeld)
  # A completed two-phase start: start-intent.json, warden-task-started.xml (task and trigger enabled) and the start receipt;
  # the live logon trigger is left enabled, as the second phase leaves it.
  $root=Get-FixtureRetargetRoot $Target;$r5=($Target -ceq 'r5')
  if(-not $NoIntent){Write-FixtureStartIntent $Target}
  $startedSha=Write-FixtureText (Join-Path $root 'warden-task-started.xml') (Get-FixtureXmlWith $true $(if($r5){$true}else{$null}))
  $s=[ordered]@{schema='cochem-warden-start/3';status=$(if($r5){'WARDEN_R5_RUNNING_HEALTH_VERIFIED'}else{'WARDEN_R4_RESTARTED_HEALTH_VERIFIED'})}
  $head=Get-FixtureHead $Target;foreach($k in @($head.Keys)){$s[$k]=$head[$k]}
  $s['retarget_receipt_sha256']=(Get-FixtureFileSha (Join-Path $root 'retarget-receipt.json'));$s['intent_sha256']=(Get-FixtureFileSha (Join-Path $root 'start-intent.json'))
  $s['task_xml_sha256']=$startedSha;$s['task_xml_started_sha256']=$startedSha
  $s['trigger_enabled_before']=$(if($r5){$false}else{$null});$s['trigger_enabled_after']=$(if($r5){$true}else{$null})
  foreach($k in @($Start.Keys)){$s[$k]=$Start[$k]}
  if(-not $NoStartReceipt){Write-FixtureJson (Join-Path $root 'start-receipt.json') $s}
  if($StartHeld){Write-FixtureJson (Join-Path $root 'start-held.json') @{x=1}}
  if($r5){Set-FixtureTriggerEnabled $true}}
function Write-FixtureStop {param([string]$RetargetTarget,[hashtable]$Stop=@{},[switch]$NoStop,[switch]$StopHeld,[string]$Binding)
  # The stop-warden-r5 receipt (FIXD-STOP fields) binding exactly the start evidence in the source attempt's root.
  $stopRoot=Join-Path $script:base ('WardenStop4.2.7-windows-20261011-r5-'+$script:StopAttempt);$root=Get-FixtureRetargetRoot $RetargetTarget
  $startSha=Get-FixtureFileSha (Join-Path $root 'start-receipt.json');$heldSha=Get-FixtureFileSha (Join-Path $root 'start-held.json')
  if(-not $Binding){$Binding=$(if($null -ne $startSha){'START_RECEIPT'}elseif($null -eq $heldSha){'START_CRASHED_NO_RECORD'}else{'START_INTERRUPTED_HELD'})}
  $s=[ordered]@{schema='cochem-warden-stop/2';status='WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED';retarget_target=$RetargetTarget;retarget_attempt=$script:SourceAttempt;
     task_name='CoChem-4.2.7-Warden';enabled_after=$false;instances_after=0;task_xml_after_sha256=(Get-TaskXmlSha256 $script:task.Xml);start_binding=$Binding;
     start_receipt_sha256=$(if($Binding -ceq 'START_RECEIPT'){$startSha}else{$null});start_held_sha256=$(if($Binding -ceq 'START_RECEIPT'){$null}else{$heldSha});
     retarget_receipt_sha256=(Get-FixtureFileSha (Join-Path $root 'retarget-receipt.json'));start_intent_sha256=(Get-FixtureFileSha (Join-Path $root 'start-intent.json'));
     source_task_xml_after_sha256=(Get-FixtureFileSha (Join-Path $root 'warden-task-after.xml'));trigger_enabled_after=(Get-FixtureLiveTrigger $RetargetTarget)}
  foreach($k in @($Stop.Keys)){if($null -eq $Stop[$k] -and $k -ceq 'retarget_target'){$s.Remove($k)}else{$s[$k]=$Stop[$k]}}
  if(-not $NoStop){Write-FixtureJson (Join-Path $stopRoot 'stop-receipt.json') $s}else{$null=[IO.Directory]::CreateDirectory($stopRoot)}
  if($StopHeld){Write-FixtureJson (Join-Path $stopRoot 'stop-held.json') @{x=1}}}
function Write-FixtureR5Retarget {param([hashtable]$Receipt=@{},[switch]$RetargetHeld)Write-FixtureRetarget 'r5' $Receipt -RetargetHeld:$RetargetHeld}
function Write-FixtureR5Source {param([hashtable]$Receipt=@{},[hashtable]$Start=@{},[hashtable]$Stop=@{},[switch]$NoStop,[switch]$StopHeld,[switch]$RetargetHeld,[switch]$NoStartReceipt,[switch]$NoIntent,[switch]$StartHeld,[string]$Description)
  # A started and stopped r5 attempt: retarget receipt, completed two-phase start, stop-warden-r5 receipt (retarget_target r5).
  $extra=@{};if($PSBoundParameters.ContainsKey('Description')){$extra['Description']=$Description}
  $null=Write-FixtureRetarget 'r5' $Receipt -RetargetHeld:$RetargetHeld @extra
  Write-FixtureStarted 'r5' $Start -NoStartReceipt:$NoStartReceipt -NoIntent:$NoIntent -StartHeld:$StartHeld
  Write-FixtureStop 'r5' $Stop -NoStop:$NoStop -StopHeld:$StopHeld}
function Write-FixtureNeverStarted {param([string]$Target='r5',[hashtable]$Receipt=@{},[hashtable]$Held=@{},[switch]$HeldBeforeRun,[switch]$IntentOnly,[switch]$StartReceipt,[switch]$RetargetHeld)
  # A retarget that never started (task and trigger disabled): optionally the start-intent/start-held pair a hold before Run leaves.
  Set-FixtureTriggerEnabled $false
  $root=Write-FixtureRetarget $Target $Receipt -RetargetHeld:$RetargetHeld
  if($HeldBeforeRun -or $IntentOnly){Write-FixtureStartIntent $Target}
  if($HeldBeforeRun){$h=[ordered]@{schema='cochem-warden-start-held/3';target=$Target;attempt=$script:SourceAttempt;task_name='CoChem-4.2.7-Warden';interrupted=$false;stage='RUN';
       health_gate_passed=$false;stop_recovery_allowed=$false;run_requested=$false;run_exception=$null;held_before_run=$true;enable_requested=$true;instance_guid=$null;
       running_instances=0;enabled_after=$false;disable_attempted=$true;disable_error=$null;task_xml_after_sha256=(Get-TaskXmlSha256 (Get-FixtureXmlWith $false $false));
       trigger_enable_requested=$false;trigger_enabled_after=$(if($Target -ceq 'r5'){$false}else{$null});receipt_written=$false}
     foreach($k in @($Held.Keys)){$h[$k]=$Held[$k]};Write-FixtureJson (Join-Path $root 'start-held.json') $h}
  if($StartReceipt){Write-FixtureJson (Join-Path $root 'start-receipt.json') @{schema='cochem-warden-start/3'}}}
function Write-FixtureR5NeverStarted {param([hashtable]$Receipt=@{},[hashtable]$Held=@{},[switch]$HeldBeforeRun,[switch]$IntentOnly,[switch]$StartReceipt,[switch]$RetargetHeld)
  Write-FixtureNeverStarted 'r5' $Receipt $Held -HeldBeforeRun:$HeldBeforeRun -IntentOnly:$IntentOnly -StartReceipt:$StartReceipt -RetargetHeld:$RetargetHeld}
function Write-FixtureR4RestoreSource {param([hashtable]$Start=@{},[hashtable]$Stop=@{},[switch]$NoStart,[switch]$StartHeld,[switch]$RetargetHeld,[switch]$StopHeld,[hashtable]$Receipt=@{})
  # A started and stopped r4 restore: its retarget receipt, completed start and the stop-warden-r5 receipt (retarget_target r4).
  $null=Write-FixtureRetarget 'r4' $Receipt -RetargetHeld:$RetargetHeld
  if(-not $NoStart){Write-FixtureStarted 'r4' $Start -StartHeld:$StartHeld}
  Write-FixtureStop 'r4' $Stop -StopHeld:$StopHeld}
function Write-FixtureHeldStart {param([string]$Target='r5',[string]$Kind='interrupted',[hashtable]$Held=@{},$TriggerEnabled=$false,[hashtable]$Stop=@{},[string]$Binding,[hashtable]$Intent=@{})
  # A start requested without a receipt (interrupted, held after its health gate, held after Run before its gate, held before
  # Run, or crashed with no record), then stopped by stop-warden-r5 -RecoverInterruptedStart; the live trigger is left as that
  # start left it. stop_recovery_allowed follows the re-audit R-F1 contract: (not held_before_run) or interrupted.
  if($Target -ceq 'r5'){Set-FixtureTriggerEnabled ([bool]$TriggerEnabled)}
  $root=Write-FixtureRetarget $Target
  Write-FixtureStartIntent $Target $Intent
  if($Kind -cne 'crashed'){
    $interrupted=($Kind -ceq 'interrupted');$gate=($Kind -ceq 'gate');$beforeRun=($Kind -ceq 'before_run')
    $h=[ordered]@{schema='cochem-warden-start-held/3';target=$Target;attempt=$script:SourceAttempt;task_name='CoChem-4.2.7-Warden';interrupted=$interrupted;
       stage=$(if($gate){'TRIGGER_ENABLE'}elseif($beforeRun){'BEFORE_RUN'}else{'HEALTH_WAIT'});health_gate_passed=$gate;stop_recovery_allowed=((-not $beforeRun) -or $interrupted);
       run_requested=(-not $beforeRun);run_exception=$null;held_before_run=$beforeRun;enable_requested=$true;
       instance_guid=$(if($beforeRun){$null}else{'{00000000-0000-0000-0000-00000000aaaa}'});running_instances=$(if($beforeRun){0}else{1});enabled_after=$false;disable_attempted=$true;
       disable_error=$null;task_xml_after_sha256=(Get-TaskXmlSha256 $script:task.Xml);trigger_enable_requested=$gate;
       trigger_enabled_after=$(if($Target -ceq 'r5'){$TriggerEnabled}else{$null});receipt_written=$false}
    foreach($k in @($Held.Keys)){$h[$k]=$Held[$k]};Write-FixtureJson (Join-Path $root 'start-held.json') $h}
  if(-not $Binding -and $Kind -ceq 'gate'){$Binding='START_HELD_AFTER_HEALTH_GATE'}
  if(-not $Binding -and $Kind -cin @('before_gate','before_run')){$Binding='START_HELD_BEFORE_HEALTH_GATE'}
  $extra=@{};if($Binding){$extra['Binding']=$Binding}
  Write-FixtureStop $Target $Stop @extra}
function Write-FixtureRetargetHeld {param([string]$Target='r5',[string]$Held='readback',[hashtable]$Intent=@{},[hashtable]$Record=@{},[string]$BeforeExtra='',[string]$BeforeSddl='__SDDL__',[switch]$StartIntent)
  # An attempt whose TASK_UPDATE was requested but never receipted: retarget-intent.json, the captured before-files, and a
  # MUTATION_READBACK retarget-held.json (readback or unreadable) or nothing (interrupted); the live task as the update left it.
  if($Target -ceq 'r5'){Set-FixtureTriggerEnabled $false}
  $script:definition.RegistrationInfo.Description=Get-TargetDescription $Target $script:SourceAttempt
  $root=Get-FixtureRetargetRoot $Target
  $beforeSha=Write-FixtureText (Join-Path $root 'warden-task-before.xml') ((Get-FixtureXmlWith $true $null).Replace('</Settings>',$BeforeExtra+'</Settings>'))
  $sddlSha=Write-FixtureText (Join-Path $root 'warden-task-before.sddl') $BeforeSddl
  $i=[ordered]@{schema='cochem-warden-retarget-intent/3';attempt=$script:SourceAttempt;target=$Target;task_name='CoChem-4.2.7-Warden';
     action_after=[ordered]@{execute=$script:action.Path;arguments=$script:action.Arguments;working_directory=$script:action.WorkingDirectory};
     config_sha256=$(if($Target -ceq 'r5'){'d'*64}else{$script:configPin});task_xml_before_sha256=$beforeSha;task_sddl_before_sha256=$sddlSha}
  foreach($k in @($Intent.Keys)){$i[$k]=$Intent[$k]}
  Write-FixtureJson (Join-Path $root 'retarget-intent.json') $i
  if($Held -cne 'none'){
    $readable=($Held -ceq 'readback')
    $h=[ordered]@{schema='cochem-warden-retarget-held/3';phase='MUTATION_READBACK';target=$Target;attempt=$script:SourceAttempt;task_name='CoChem-4.2.7-Warden';
       mutation_requested=$true;readback_readable=$readable;
       readback=$(if($readable){[ordered]@{enabled=$false;state=1;instances=0;task_xml_sha256=(Get-TaskXmlSha256 $script:task.Xml)}}else{$null});receipt_written=$false}
    foreach($k in @($Record.Keys)){$h[$k]=$Record[$k]}
    Write-FixtureJson (Join-Path $root 'retarget-held.json') $h}
  if($StartIntent){Write-FixtureJson (Join-Path $root 'start-intent.json') @{schema='cochem-warden-start-intent/3'}}
  $root}
'''.replace('__SDDL__', SDDL)

ENV_STUBS = r'''
$script:backups=0;$script:rightsProbes=0;$script:presenceCalls=0;$script:loopbackCalls=0;$script:fixtureAliveAt=@();$script:loopbackBusyAt=@();$script:codeTrees=@()
$script:rootFailsAfterCreate=$false;$script:backupFails=$false;$script:otherActive=$false;$script:workerFixture=$null;$script:rightsFail=$false
function New-ProtectedDirectory {param($Path)if(Test-Path -LiteralPath $Path){throw ('Destination already exists; preserve and review it: '+$Path)};$null=[IO.Directory]::CreateDirectory($Path);if($script:rootFailsAfterCreate){throw 'Untrusted protected owner: simulated'}}
function New-PrivateDirectory {param($Path)if(Test-Path -LiteralPath $Path){throw 'exists'};$null=[IO.Directory]::CreateDirectory($Path)}
function Assert-CodeTreeOnce {param($Path)$script:codeTrees+=$Path;1}
function Backup-PrivateDatabases {param($Destination)$script:backups++;if($script:backupFails){throw 'Private database copies differ between passes: job_board.db; a writer may be active.'};[ordered]@{copy_exit_code=1;witness_exit_code=1;copy_flags=@('/B');verification=[ordered]@{schema='cochem-private-database-backup/3';databases=@()}}}
function Get-OtherDaemonTaskStates {param($Folder)if($script:otherActive){return @([pscustomobject]@{name='CoChem-4.2.7-Supervisor';state='ACTIVE';active=$true})};@([pscustomobject]@{name='CoChem-4.2.7-Supervisor';state='ABSENT';active=$false})}
function Get-WorkerProcesses {if($null -ne $script:workerFixture){return $script:workerFixture};[ordered]@{workers=@();uninspectable_processes=@();exited_during_sweep=0;authoritative=$true}}
function Test-LoopbackFree {$script:loopbackCalls++;-not ($script:loopbackBusyAt -contains $script:loopbackCalls)}
function Test-BackupCopyRights {$script:rightsProbes++;if($script:rightsFail){throw 'Backup copy rights/readability probe failed (robocopy exit 16): ERROR : You do not have the Backup and Restore Files user rights.'};$true}
function Get-ControllerPresence {$script:presenceCalls++;$alive=($script:fixtureAliveAt -contains $script:presenceCalls);[ordered]@{port=47824;listening=$(if($alive){1}else{0});controller_processes=@();observer_processes=@(@{pid=9472;command='observer'});client_processes=@();unclassified_runtime_processes=@();uninspectable_python_processes=0;authoritative=$true}}
function Start-Sleep {param($Seconds,$Milliseconds)[Threading.Thread]::Sleep(10)}
'''


def run(tmp_path: Path, body: str, timeout: int = 180) -> dict:
    """Run PRELUDE + body in a throwaway Windows PowerShell 5.1 and parse the single JSON line it prints."""
    text = PRELUDE.replace('__SCRIPT__', ps(SCRIPT)).replace('__REGISTER__', ps(REGISTER)).replace('__ROOT__', ps(ROOT)) + body
    case = tmp_path / ('case-%d.ps1' % len(list(tmp_path.glob('case-*.ps1'))))
    case.write_text(text, encoding='utf-8-sig')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(case)], capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, (result.stdout[-4000:], result.stderr[-4000:])
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, result.stderr
    return json.loads(lines[-1])


@pytest.fixture(scope='module')
def batch_dir(tmp_path_factory):
    return tmp_path_factory.mktemp('batch')


# ----------------------------------------------------------------------------------------------- static checks

def test_script_is_ascii_and_parses_under_windows_powershell_5_1(tmp_path):
    raw = SCRIPT.read_bytes()
    assert all(byte < 128 for byte in raw), [i for i, byte in enumerate(raw) if byte >= 128][:5]
    assert not raw.startswith(b'\xef\xbb\xbf')
    probe = tmp_path / 'parse.ps1'
    probe.write_text(f"$t=$null;$e=$null;$null=[Management.Automation.Language.Parser]::ParseFile('{ps(SCRIPT)}',[ref]$t,[ref]$e);"
                     "[ordered]@{errors=@($e).Count;major=$PSVersionTable.PSVersion.Major;edition=$PSVersionTable.PSEdition}|ConvertTo-Json -Compress", encoding='utf-8-sig')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(probe)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout.strip().splitlines()[-1])
    assert value == {'errors': 0, 'major': 5, 'edition': 'Desktop'}


def test_only_top_level_statement_is_the_main_invocation_and_the_parameters_are_the_contract(tmp_path):
    value = run(tmp_path, r'''
      $other=@($ast.EndBlock.Statements|Where-Object {$_ -isnot [Management.Automation.Language.FunctionDefinitionAst]})
      $names=@($ast.ParamBlock.Parameters|ForEach-Object {$_.Name.VariablePath.UserPath})
      $nested=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)).Count-@($ast.EndBlock.Statements|Where-Object {$_ -is [Management.Automation.Language.FunctionDefinitionAst]}).Count
      [ordered]@{count=$other.Count;text=$(if($other.Count){$other[0].Extent.Text}else{''});params=$names;nested=$nested;begin=($null -ne $ast.BeginBlock);process=($null -ne $ast.ProcessBlock)}|ConvertTo-Json -Compress
    ''')
    assert value['count'] == 1 and value['text'].startswith('Invoke-RetargetR5Main -Arguments '), value
    assert value['params'] == ['Target', 'Config', 'Apply', 'Start', 'StartOnly', 'Attempt', 'SourceAttempt', 'StopAttempt']
    assert value['nested'] == 0 and value['begin'] is False and value['process'] is False


def test_no_script_scope_assignment_targets_a_validated_parameter_variable(tmp_path):
    """DIAG-BINDING rule (a), the 2026-10-11 17:22 root cause: a script parameter variable keeps its [Validate*] attributes
    even when the parameter was not bound, so Invoke-RetargetR5Main's $script:SourceAttempt='' (no -SourceAttempt) threw
    ValidationMetadataException before anything was read. No assignment that reaches the script scope ($script:/$global:,
    a top-level statement or Set-Variable/New-Variable) may name a parameter that carries a Validate* attribute; the values
    are validated by Assert-RetargetParameters (case-sensitive) instead."""
    value = run(tmp_path, r'''
      $validated=[ordered]@{}
      foreach($p in @($ast.ParamBlock.Parameters)){foreach($a in @($p.Attributes)){
        if($a -is [Management.Automation.Language.AttributeAst] -and $a.TypeName.Name -match '^Validate'){$validated[$p.Name.VariablePath.UserPath.ToLowerInvariant()]=$a.Extent.Text}}}
      $hits=@();$assigned=@()
      foreach($as in @($ast.FindAll({param($n)$n -is [Management.Automation.Language.AssignmentStatementAst]},$true))){
        $left=$as.Left;while($left -is [Management.Automation.Language.AttributedExpressionAst]){$left=$left.Child}
        if($left -isnot [Management.Automation.Language.VariableExpressionAst]){continue}
        $path=$left.VariablePath;$name=($path.UserPath -replace '^(script|global|local|private):','').ToLowerInvariant()
        $inFunction=$false;$parent=$as.Parent;while($null -ne $parent){if($parent -is [Management.Automation.Language.FunctionDefinitionAst]){$inFunction=$true;break};$parent=$parent.Parent}
        if($path.IsScript -or $path.IsGlobal -or -not $inFunction){$assigned+=$name;if($validated.Contains($name)){$hits+=$as.Extent.Text}}}
      $setters=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.CommandAst] -and [string]$n.GetCommandName() -in @('Set-Variable','New-Variable','sv','nv')},$true)|ForEach-Object {$_.Extent.Text})
      [ordered]@{validated=$validated;hits=$hits;setters=$setters;assigned=@($assigned|Sort-Object -Unique)}|ConvertTo-Json -Compress -Depth 4
    ''')
    assert value['hits'] == [] and value['setters'] == [], value
    assert {'target', 'attempt', 'sourceattempt', 'stopattempt'} <= set(value['assigned']), 'the main copies the validated request into the script scope'


def test_no_function_shadows_a_variable_the_imported_helpers_resolve_dynamically(tmp_path):
    """DIAG-BINDING rule (b): the reviewed Read-R3Control (check-worker-native-status-r3.ps1) calls $held.Add($stream) on the
    CALLER's $held (dynamic scope). A function that assigns its own $held (a JSON record, a held-start result) and then reads
    a control file makes the real helper fail ('does not contain a method named Add' / 'null-valued expression') - the
    stubbed harness could not see it. Every free variable of every imported helper may be assigned only by the main."""
    value = run(tmp_path, r'''
      function Get-FreeVariables {param($Function)
        $bound=@{};foreach($p in @($Function.FindAll({param($n)$n -is [Management.Automation.Language.ParameterAst]},$true))){$bound[$p.Name.VariablePath.UserPath.ToLowerInvariant()]=1}
        foreach($as in @($Function.FindAll({param($n)$n -is [Management.Automation.Language.AssignmentStatementAst]},$true))){
          $left=$as.Left;while($left -is [Management.Automation.Language.AttributedExpressionAst]){$left=$left.Child}
          if($left -is [Management.Automation.Language.VariableExpressionAst]){$bound[$left.VariablePath.UserPath.ToLowerInvariant()]=1}}
        foreach($loop in @($Function.FindAll({param($n)$n -is [Management.Automation.Language.ForEachStatementAst]},$true))){$bound[$loop.Variable.VariablePath.UserPath.ToLowerInvariant()]=1}
        $free=@{}
        foreach($v in @($Function.FindAll({param($n)$n -is [Management.Automation.Language.VariableExpressionAst]},$true))){
          $path=$v.VariablePath;$name=$path.UserPath.ToLowerInvariant()
          if(-not $path.IsUnqualified -or $bound.ContainsKey($name)){continue}
          if($name -in @('true','false','null','_','psitem','args','input','this','erroractionpreference','pshome','psscriptroot','lastexitcode','matches','pscmdlet','psboundparameters','myinvocation','psversiontable')){continue}
          $free[$name]=1}
        @($free.Keys|Sort-Object)}
      $imports=[ordered]@{'__CHECK__'=@('Read-R3Control','Read-R3Text');'__REGISTER__'=@('Assert-RegisteredTaskAcl','Write-RegistrationControl');
        '__INSPECTION__'=@('Assert-CodeTreeOnce');'__COPY__'=@('Assert-NoReparseAncestors','Assert-ProtectedPath','New-CodeAcl','New-ProtectedDirectory','Initialize-FileIdentity','Open-VerifiedFile','Copy-VerifiedPayload')}
      $helperFree=[ordered]@{}
      foreach($file in @($imports.Keys)){
        $t=$null;$e=$null;$helperAst=[Management.Automation.Language.Parser]::ParseFile($file,[ref]$t,[ref]$e)
        foreach($name in $imports[$file]){$f=@($helperAst.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true))
          if($f.Count -ne 1){throw ('expected one definition of '+$name)};$helperFree[$name]=@(Get-FreeVariables $f[0])}}
      $dynamic=@($helperFree.Values|ForEach-Object {$_}|Sort-Object -Unique)
      $shadows=@()
      foreach($f in @($ast.EndBlock.Statements|Where-Object {$_ -is [Management.Automation.Language.FunctionDefinitionAst]})){
        if($f.Name -ceq 'Invoke-RetargetR5Main'){continue}
        $names=@{};foreach($p in @($f.FindAll({param($n)$n -is [Management.Automation.Language.ParameterAst]},$true))){$names[$p.Name.VariablePath.UserPath.ToLowerInvariant()]=1}
        foreach($as in @($f.FindAll({param($n)$n -is [Management.Automation.Language.AssignmentStatementAst]},$true))){
          $left=$as.Left;while($left -is [Management.Automation.Language.AttributedExpressionAst]){$left=$left.Child}
          if($left -is [Management.Automation.Language.VariableExpressionAst]){$names[($left.VariablePath.UserPath -replace '^(script|global|local|private):','').ToLowerInvariant()]=1}}
        foreach($loop in @($f.FindAll({param($n)$n -is [Management.Automation.Language.ForEachStatementAst]},$true))){$names[$loop.Variable.VariablePath.UserPath.ToLowerInvariant()]=1}
        foreach($name in $dynamic){if($names.ContainsKey($name)){$shadows+=($f.Name+' assigns $'+$name)}}}
      $main=@($ast.EndBlock.Statements|Where-Object {$_ -is [Management.Automation.Language.FunctionDefinitionAst] -and $_.Name -ceq 'Invoke-RetargetR5Main'})[0].Extent.Text
      [ordered]@{helper_free=$helperFree;dynamic=$dynamic;shadows=$shadows;main_list=$main.Contains('$held=[Collections.Generic.List[IO.FileStream]]::new()')}|ConvertTo-Json -Compress -Depth 4
    '''.replace('__CHECK__', ps(CHECK_R3)).replace('__REGISTER__', ps(REGISTER)).replace('__INSPECTION__', ps(INSPECTION)).replace('__COPY__', ps(COPY_HELPER)))
    assert value['dynamic'] == ['held'] and value['helper_free']['Read-R3Control'] == ['held'], value['helper_free']
    assert value['main_list'] is True, 'the main owns the one $held list every reviewed read adds its handle to'
    assert value['shadows'] == [], value['shadows']


V22_IDENTICAL = ['Import-ReviewedFunctions', 'Invoke-NativeJudged', 'Get-ExpectedArguments', 'Test-ExactBool', 'Test-ExactInt', 'Assert-R4InstalledBindings',
                 'Get-OtherDaemonTaskStates', 'Assert-OtherDaemonsIdle', 'Test-ControllerAlive', 'Test-LoopbackFree', 'Get-WorkerProcesses', 'Assert-NoWorkers',
                 'New-PrivateAcl', 'Assert-PrivateAcl', 'New-PrivateDirectory', 'Get-BackupCopyArguments', 'Test-BackupCopyRights', 'Get-TreeHashes', 'Backup-PrivateDatabases']
STOP_R4_IDENTICAL = ['Get-JsonListField', 'Get-ProcessCreationUtc']


def test_functions_reused_from_v22_and_stop_r4_are_byte_identical(tmp_path):
    value = run(tmp_path, r'''
      function Get-Texts {param($Path)$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$t,[ref]$e);$m=@{};foreach($f in $a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){$m[$f.Name]=$f.Extent.Text};$m}
      $mine=Get-Texts '__SCRIPT__';$v22=Get-Texts '__V22__';$stop=Get-Texts '__STOP__'
      $diff=@();foreach($n in @(__V22LIST__)){if($mine[$n] -cne $v22[$n]){$diff+=$n}};foreach($n in @(__STOPLIST__)){if($mine[$n] -cne $stop[$n]){$diff+=$n}}
      [ordered]@{diff=$diff;count=$mine.Count}|ConvertTo-Json -Compress
    '''.replace('__SCRIPT__', ps(SCRIPT)).replace('__V22__', ps(PREDECESSOR)).replace('__STOP__', ps(STOP_R4))
       .replace('__V22LIST__', ','.join(f"'{n}'" for n in V22_IDENTICAL)).replace('__STOPLIST__', ','.join(f"'{n}'" for n in STOP_R4_IDENTICAL)))
    assert value['diff'] == [], value


def test_static_safety_text_and_contract_strings():
    text = SCRIPT.read_text(encoding='ascii')
    for forbidden in ('Unregister-ScheduledTask', 'Stop-ScheduledTask', 'Register-ScheduledTask', 'Start-ScheduledTask', 'Disable-ScheduledTask', 'Enable-ScheduledTask',
                      'schtasks', 'Start-Process', 'Stop-Process', 'taskkill', 'Remove-Item', 'Stop-Service', '.Stop(', 'DeleteTask', '/MIR', '/MOV', '/PURGE',
                      'Invoke-Expression', 'RunAs', 'wsl', 'docker ', 'Set-ExecutionPolicy', '.Kill(', 'Delete(', 'python -c'):
        assert forbidden not in text, forbidden
    assert text.count('.Run($null)') == 1, 'exactly one Run request'
    assert text.count('.RegisterTaskDefinition(') == 2 and text.count("RegisterTaskDefinition($script:taskName,$definition,4,'SYSTEM',$null,5,") == 2,         'the retarget TASK_UPDATE and the r5 second-phase trigger enable, both TASK_UPDATE on the same name'
    assert text.count('$task.Enabled=$true') == 1, 'the only enabling write of the task is the enable-before-run'
    assert text.count('$definition.Settings.Enabled=$false') == 1, 'every TASK_UPDATE registers the task disabled'
    assert text.count('$trigger.Enabled=$false') == 1 and text.count('Triggers.Create(9)') == 1, 'the r5 logon trigger is registered disabled'
    assert text.count('$definition.Triggers.Item(1).Enabled=$true') == 1, 'the only trigger enable is the second phase after the health gate'
    assert text.count('$State.task.Enabled=$false') == 1 and '$state.task.Enabled=$false' not in text, 'the only disabling write is the best-effort disable of a held or interrupted start'
    assert text.count('}finally{') >= 1 and 'Write-StartHeldRecord $Folder $Context $state $facts $true' in text, 'an interrupted start is recorded by the finally'
    assert "$script:startWaitSeconds=240" in text and 'AddSeconds($script:startWaitSeconds)' in text
    assert "$script:backupCopyFlags=@('/B')" in text and "$arguments+='/L'" in text and "'/A-:RSH'" in text and "'/XJ'" in text
    assert "$ErrorActionPreference='Continue'" in text, 'native commands are judged by exit code'
    assert "'CimCmdlets','NetTCPIP'" in text
    for contract in ('cochem-warden-retarget/3', 'cochem-warden-start/3', 'cochem-warden-retarget-result/3', 'cochem-warden-start-result/3',
                     'WARDEN_RETARGETED_TO_R5_NOT_STARTED', 'WARDEN_RETARGETED_TO_R4_NOT_STARTED', 'WARDEN_R5_RUNNING_HEALTH_VERIFIED', 'WARDEN_R4_RESTARTED_HEALTH_VERIFIED',
                     "'retarget-held.json'", "'start-held.json'", "'retarget-receipt.json'", "'start-receipt.json'", 'cochem-warden-stop/2',
                     "'WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED','WARDEN_ALREADY_STOPPED_CLEAN_NOOP'", "'WardenRetarget4.2.7-windows-'", "'WardenStop4.2.7-windows-'",
                     "$script:namespaceDate='20261011'", "$script:logonUser='AETHERDESK\\ansac';$script:logonDelay='PT1M'", '$script:dockerWaitSeconds=900',
                     "'queue-launch-r5'", "('queue-restart-'+$script:namespaceDate+'-r4-'+$script:Attempt)",
                     "New-SourceRecord 'r4-v1'", "'r5-retarget-receipt'", "'r4-restore-retarget-receipt'", "'r5-receipt'", "'r4-restore-receipt'", "'r5-start-held'",
                     "'r4-restore-start-held'", "'r5-retarget-held'", "'r4-restore-retarget-held'", "'retarget_target'", "'GEMINI_HELD_COMMISSIONING_FILE'",
                     "'START_RECEIPT'", "'START_INTERRUPTED_HELD'", "'START_HELD_AFTER_HEALTH_GATE'", "'START_CRASHED_NO_RECORD'", "'MUTATION_READBACK_HELD'",
                     "'MUTATION_READBACK_UNREADABLE'", "'MUTATION_INTERRUPTED'", "'START_HELD_BEFORE_RUN'", "'warden-task-started.xml'", "'cochem-config-only-staging/2'",
                     'disable_attempted=$true', 'task_xml_after_sha256=$xmlAfter', 'stop_recovery_allowed=((-not $heldBeforeRun) -or $Interrupted)', 'interrupted=$Interrupted', "'START_HELD_BEFORE_HEALTH_GATE'",
                     '$null=Assert-AttemptTaskXml $state $Context $Binding', '$null=Assert-AttemptTaskXml $taskState $context $binding',
                     'trigger_enabled_after=', 'held_before_run=', 'run_exception=', 'health_gate_passed=$gate', 'task_xml_started_sha256=$startedXml'):
        assert contract in text, contract
    assert 'Get-TaskXmlSha256' in text and '[Text.UTF8Encoding]::new($false).GetBytes($Xml)' in text


def test_embedded_pins_match_the_files_on_disk():
    text = SCRIPT.read_text(encoding='ascii')
    local = {HELPER: 'backupHelperPin', CHECK_R3: None, REGISTER: None, INSPECTION: None, COPY_HELPER: None}
    for path in local:
        assert sha256_file(path) in text, path
    assert f"$script:backupHelperPin='{sha256_file(HELPER)}'" in text
    installed = {R4_ROOT + r'\install-after.json': '629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502',
                 R4_ROOT + r'\source-manifest.json': '1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189',
                 R4_ROOT + r'\pipeline.json': CONFIG_PIN, COMMISSIONING_CONFIG: CONFIG_PIN,
                 R4_ROOT + r'\.venv\pyvenv.cfg': '0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d',
                 R4_PY: '560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e', BASE_PY: 'd8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa',
                 R4_ROOT + r'\.venv\Lib\site-packages\cochem_pipeline\resource_telemetry.py': 'e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc',
                 R4_ROOT + r'\source\src\cochem_pipeline\resource_telemetry.py': 'e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc',
                 str(R4V1_ROOT / 'retarget-receipt.json'): '1e32c47688ef8ccf7bdd6f2f640ce736e6025508ad7ba04b37543905c3f7feb2',
                 str(R4V1_ROOT / 'start-receipt.json'): 'ff6845d18238471775d538641f3e0015aebbbeb73c318c57df177e2a3241db7b',
                 str(R4V1_ROOT / 'warden-task-after.xml'): 'fbfdcd8318d2418cbb8d28badad53a1a8e829a1e9c7143d13600bb62fd04c2be',
                 R3_ROOT + r'\install-after.json': '3b613128192ac44a0a3d9c4b4476fb4c47541edb7563541b9bbf18f84f9a90f6',
                 R3_ROOT + r'\source-manifest.json': '6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1'}
    present = {path: pin for path, pin in installed.items() if Path(path).exists()}
    if not present:
        pytest.skip('installed r4 artefacts are absent on this host')
    for path, pin in present.items():
        assert pin in text, path
        assert sha256_file(Path(path)) == pin, path
    revision = json.loads(Path(R4_ROOT + r'\install-after.json').read_text(encoding='utf-8'))['verification']['revision']['source_sha256']
    assert revision == '38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e' and revision in text
    if Path(R3_ROOT + r'\install-after.json').exists():
        r3_revision = json.loads(Path(R3_ROOT + r'\install-after.json').read_text(encoding='utf-8'))['verification']['revision']['source_sha256']
        assert r3_revision == '309eb48d9b1c43179ae1f0784d0139357168314f8312a64fb84dbd8380d44eb4' and r3_revision in text


FREEZE_MANIFEST = ROOT / 'stopped-runtime-r5-source-manifest.json'
INSTALLER_R5 = ROOT / 'install-stopped-runtime-r5.ps1'


def test_r5_freeze_pins_are_the_reviewed_manifest_its_repair_digests_and_the_installer_venv_pins(tmp_path):
    """Audit C-F4: the manifest sha, the 13 reviewed repair digests and the venv pins are the reviewed values on disk."""
    text = SCRIPT.read_text(encoding='ascii')
    manifest = json.loads(FREEZE_MANIFEST.read_text(encoding='utf-8'))
    assert sha256_file(FREEZE_MANIFEST) == '5d8d337baebbc1e4ac29439d418333ab41c0999eb8c0ef8b02acee66850a3045'
    assert manifest['source_commit'] == '8554c7645801a7bc9c4abad4861bfcbe4ed014b0' and manifest['verified_unchanged'] == 153
    value = run(tmp_path, r'''
      [ordered]@{manifest=$script:r5SourceManifestPin;repairs=$script:r5RepairPins;pyvenv=$script:r5PyvenvPin;launcher=$script:r5VenvPythonPin;unchanged=$script:r5VerifiedUnchanged;
        staging=$script:stagingReceiptSchema;pattern=$script:stagingReceiptPattern}|ConvertTo-Json -Compress -Depth 4
    ''')
    assert value['manifest'] == sha256_file(FREEZE_MANIFEST) and value['unchanged'] == 153
    assert value['repairs'] == manifest['reviewed_repairs_sha256'] and list(value['repairs']) == manifest['reviewed_repairs'] and len(value['repairs']) == 13
    installer = INSTALLER_R5.read_text(encoding='ascii')
    assert f"$cfgHash='{value['pyvenv']}'" in installer and f"$exeHash='{value['launcher']}'" in installer
    assert value['staging'] == 'cochem-config-only-staging/2' and value['pattern'] == r'^staging-receipt-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.json$'


def test_r4v1_action_and_task_xml_hash_match_the_on_disk_r4v1_after_xml(tmp_path):
    xml_path = R4V1_ROOT / 'warden-task-after.xml'
    if not xml_path.exists():
        pytest.skip('the r4 v1 retarget evidence is absent on this host')
    raw = xml_path.read_bytes()
    assert not raw.startswith(b'\xef\xbb\xbf') and hashlib.sha256(raw).hexdigest() == 'fbfdcd8318d2418cbb8d28badad53a1a8e829a1e9c7143d13600bb62fd04c2be'
    value = run(tmp_path, r'''
      $text=[IO.File]::ReadAllText('__XML__',[Text.UTF8Encoding]::new($false))
      $doc=[xml]$text;$exec=$doc.Task.Actions.Exec
      [ordered]@{sha=(Get-TaskXmlSha256 $text);args_equal=([string]$exec.Arguments -ceq (Get-ExpectedArguments $script:commissioningConfig $script:queueR4v1));
        command_equal=([string]$exec.Command -ceq $script:r4Python);wd_equal=([string]$exec.WorkingDirectory -ceq $script:r4Root);
        triggers=@(@($doc.DocumentElement.ChildNodes|Where-Object {$_.LocalName -ceq 'Triggers'})[0].ChildNodes).Count;pin=$script:r4v1TaskXmlPin}|ConvertTo-Json -Compress
    '''.replace('__XML__', ps(xml_path)))
    assert value == {'sha': value['pin'], 'args_equal': True, 'command_equal': True, 'wd_equal': True, 'triggers': 0, 'pin': value['pin']}


def test_task_xml_hash_is_the_write_registration_control_conversion_stop_r4_uses(tmp_path):
    """stop-warden-r4 records task_xml_after_sha256 as Write-RegistrationControl's return value; Get-TaskXmlSha256 must equal it."""
    target = tmp_path / 'written.xml'
    value = run(tmp_path, r'''
      foreach($f in @($regAst.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Write-RegistrationControl'},$true))){. ([scriptblock]::Create($f.Extent.Text))}
      function Assert-ProtectedPath {param($Path)};function New-CodeAcl {param($Directory)$null}
      $xml='<?xml version="1.0" encoding="UTF-16"?>'+"`r`n"+'<Task><Description>caf'+[char]0x00e9+' '+[char]0x2713+'</Description></Task>'
      $written=Write-RegistrationControl '__TARGET__' $xml
      [ordered]@{written=$written;mine=(Get-TaskXmlSha256 $xml)}|ConvertTo-Json -Compress
    '''.replace('__TARGET__', ps(target)))
    expected = hashlib.sha256(('<?xml version="1.0" encoding="UTF-16"?>\r\n<Task><Description>caf\u00e9 \u2713</Description></Task>').encode('utf-8')).hexdigest()
    assert value['written'] == value['mine'] == expected == sha256_file(target)


def test_real_r4_bindings_and_r4v1_lineage_pass_read_only(tmp_path):
    if not Path(R4_ROOT + r'\install-after.json').exists() or not (R4V1_ROOT / 'retarget-receipt.json').exists():
        pytest.skip('installed r4 artefacts are absent on this host')
    value = run(tmp_path, r'''
      $runtime=Assert-R4Pins (Assert-R4InstalledBindings);$lineage=Assert-R4RetargetLineage;$fallback=Assert-R5Config $script:commissioningConfig
      [ordered]@{install=$runtime.install_receipt_sha256;revision=$runtime.revision_sha256;pid=$lineage.old_controller.pid;instance=$lineage.old_controller.instance_id;
        retarget=$lineage.retarget_receipt_sha256;start=$lineage.start_receipt_sha256;xml=$lineage.task_xml_after_sha256;fallback_mode=$fallback.mode;fallback_sha=$fallback.sha256}|ConvertTo-Json -Compress
    ''')
    assert value.pop('fallback_mode') == 'GEMINI_HELD_COMMISSIONING_FILE' and value.pop('fallback_sha') == CONFIG_PIN, 'the Gemini fallback config is the real commissioning copy'
    assert value == {'install': '629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502', 'revision': '38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e',
                     'pid': 20664, 'instance': '61497bdab0514590b88fd0cab689a404', 'retarget': '1e32c47688ef8ccf7bdd6f2f640ce736e6025508ad7ba04b37543905c3f7feb2',
                     'start': 'ff6845d18238471775d538641f3e0015aebbbeb73c318c57df177e2a3241db7b', 'xml': 'fbfdcd8318d2418cbb8d28badad53a1a8e829a1e9c7143d13600bb62fd04c2be'}


def test_r4_pins_refuse_a_different_install_receipt_or_revision(tmp_path):
    value = run(tmp_path, r'''
      $r=[ordered]@{}
      foreach($case in @(@('ok',$script:r4InstallPin,$script:r4RevisionPin),@('install',('0'*64),$script:r4RevisionPin),@('revision',$script:r4InstallPin,('0'*64)))){
        try{$null=Assert-R4Pins ([ordered]@{install_receipt_sha256=$case[1];revision_sha256=$case[2]});$r[$case[0]]='ok'}catch{$r[$case[0]]=$_.Exception.Message}}
      $r|ConvertTo-Json -Compress
    ''')
    assert value['ok'] == 'ok' and 'install' in value['install'] and 'revision' in value['revision']


def test_constants_name_the_contract_roots_queues_and_patterns(tmp_path):
    value = run(tmp_path, r'''
      $script:Target='r5';$script:Attempt='v3';Set-RetargetConstants;$r5Root=$script:targetRoot
      $script:Target='r4';$script:Attempt='v2';Set-RetargetConstants
      $configCases=[ordered]@{good='C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-r5-v1\pipeline.json';good_v12='C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261012-r5-v12\pipeline.json';
        commissioning=$script:commissioningConfig;r4_root=$script:r4RestoreConfig;r4_name='C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-r4-v1\pipeline.json';
        dotdot='C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-r5-v1\..\x\pipeline.json';other_drive='D:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-r5-v1\pipeline.json';
        upper='C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-R5-v1\pipeline.json';other_file='C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-r5-v1\pipeline.staged.json'}
      $config=[ordered]@{};foreach($k in @($configCases.Keys)){$config[$k]=[bool]($configCases[$k] -cmatch $script:r5ConfigPattern)}
      $rootCases=[ordered]@{good='Pipeline4.2.7-windows-20261011-r5';r4='Pipeline4.2.7-windows-20261009-r4';old='Pipeline4.2.7-windows-20261011-r5-old';upper='Pipeline4.2.7-windows-20261011-R5';short='Pipeline4.2.7-windows-2026101-r5'}
      $roots=[ordered]@{};foreach($k in @($rootCases.Keys)){$roots[$k]=[bool]($rootCases[$k] -cmatch $script:r5RootPattern)}
      [ordered]@{r5_root=$r5Root;r4_root=$script:targetRoot;queue_restart=$script:queueRestart;queue_root=$script:r5QueueRoot;docker=$script:dockerWaitSeconds;user=$script:logonUser;delay=$script:logonDelay;
        wait=$script:startWaitSeconds;restore_config=$script:r4RestoreConfig;health_python=$script:healthPython;flags=$script:backupCopyFlags;config=$config;roots=$roots;
        r5_args=(Get-R5Arguments 'C:\x\pipeline.json' $script:r5QueueRoot 900);token=$script:tokenFile;client=$script:clientConfig;port=$script:port}|ConvertTo-Json -Compress -Depth 4
    ''')
    assert value['r5_root'] == r'C:\Program Files\CoChem\WardenRetarget4.2.7-windows-20261011-r5-v3'
    assert value['r4_root'] == r'C:\Program Files\CoChem\WardenRetarget4.2.7-windows-20261011-r4-v2'
    assert value['queue_restart'] == r'C:\ProgramData\CoChemPipeline427\private\queue-restart-20261011-r4-v2'
    assert value['queue_root'] == R5_QUEUE_ROOT and value['docker'] == 900 and value['user'] == 'AETHERDESK\\ansac' and value['delay'] == 'PT1M'
    assert value['wait'] == 240 and value['restore_config'] == R4_RESTORE_CONFIG and value['health_python'] == R4_PY and value['flags'] == ['/B']
    assert value['config'] == {'good': True, 'good_v12': True, 'commissioning': False, 'r4_root': False, 'r4_name': False, 'dotdot': False, 'other_drive': False, 'upper': False, 'other_file': False}
    assert value['roots'] == {'good': True, 'r4': False, 'old': False, 'upper': False, 'short': False}
    assert value['r5_args'] == '-I -B -m cochem_pipeline daemon --config "C:\\x\\pipeline.json" --queue-launch-output-root "' + R5_QUEUE_ROOT + '" --docker-wait-seconds 900'
    assert value['token'] == r'C:\Users\ansac\CoChem427\controller.token' and value['client'] == r'C:\Users\ansac\CoChem427\pipeline-client-r3.json' and value['port'] == 47824


def test_target_contexts_carry_the_a2_r5_action_and_the_r4_restore_action(tmp_path):
    value = run(tmp_path, r'''
      $script:Attempt='v4';Set-RetargetConstants;$r5=New-FixtureContext 'r5';$r4=New-FixtureContext 'r4'
      [ordered]@{r5=$r5;r4=$r4}|ConvertTo-Json -Compress -Depth 6
    ''')
    r5, r4 = value['r5'], value['r4']
    assert r5['action'] == {'execute': R5_PY, 'arguments': R5_ARGS, 'working_directory': R5_ROOT}
    assert r5['triggers'] == [{'type': 'logon', 'user_id': 'AETHERDESK\\ansac', 'delay': 'PT1M'}]
    assert r5['source_root'] == R5_ROOT + r'\.venv\Lib' and r5['queue_launch_output'] is None and r5['queue_launch_output_root'] == R5_QUEUE_ROOT and r5['docker_wait_seconds'] == 900
    assert r5['retargeted_status'] == 'WARDEN_RETARGETED_TO_R5_NOT_STARTED' and r5['started_status'] == 'WARDEN_R5_RUNNING_HEALTH_VERIFIED'
    assert r5['admission_field'] == 'components.warden_controller.admission_ready' and r5['install_after_sha256'] == 'a' * 64
    restart = r'C:\ProgramData\CoChemPipeline427\private\queue-restart-20261011-r4-v4'
    assert r4['action'] == {'execute': R4_PY, 'arguments': f'-I -B -m cochem_pipeline daemon --config "{R4_RESTORE_CONFIG}" --queue-launch-output "{restart}"', 'working_directory': R4_ROOT}
    assert r4['triggers'] == [] and r4['install_after_path'] is None and r4['install_after_sha256'] is None and r4['config_sha256'] == CONFIG_PIN
    assert r4['config_path'] == R4_RESTORE_CONFIG and r4['queue_launch_output'] == restart and r4['docker_wait_seconds'] is None
    assert r4['retargeted_status'] == 'WARDEN_RETARGETED_TO_R4_NOT_STARTED' and r4['started_status'] == 'WARDEN_R4_RESTARTED_HEALTH_VERIFIED'
    assert r4['admission_field'] is None and r4['deployment_revision_sha256'] == '38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e', 'audit C-F6: r4 ready is recorded, not gated'
    assert 'Logon trigger only' in r5['description'] and 'No triggers' in r4['description'] and all(ord(c) < 128 for c in r5['description'] + r4['description'])


# ----------------------------------------------------------------------------------------------- parameters and identity

PARAMETER_CASES = {
    'r5_plan': ("@{Target='r5';Config='X';Attempt='v1'}", None),
    'r4_plan_config_ignored': ("@{Target='r4';Config='X';Attempt='v1'}", None),
    'missing_target': ("@{Attempt='v1'}", 'Choose -Target r5'),
    'upper_target': ("@{Target='R5';Config='X';Attempt='v1'}", 'Choose -Target r5'),
    'upper_attempt': ("@{Target='r4';Attempt='V1'}", '-Attempt must be'),
    'bad_attempt': ("@{Target='r4';Attempt='v1x'}", '-Attempt must be'),
    'r5_without_config': ("@{Target='r5';Attempt='v1'}", 'requires -Config'),
    'r5_startonly_without_config': ("@{Target='r5';Attempt='v1';StartOnly=$true}", None),
    'start_without_apply': ("@{Target='r4';Attempt='v1';Start=$true}", 'only meaningful together with -Apply'),
    'start_and_startonly': ("@{Target='r4';Attempt='v1';Start=$true;StartOnly=$true;Apply=$true}", 'not both'),
    'source_without_stop': ("@{Target='r4';Attempt='v1';SourceAttempt='v1'}", None),
    'stop_without_source': ("@{Target='r4';Attempt='v1';StopAttempt='v1'}", '-StopAttempt needs -SourceAttempt'),
    'bad_source': ("@{Target='r4';Attempt='v1';SourceAttempt='1';StopAttempt='v1'}", '-SourceAttempt must be'),
    'bad_stop': ("@{Target='r4';Attempt='v1';SourceAttempt='v1';StopAttempt='V1'}", '-StopAttempt must be'),
    'startonly_with_source': ("@{Target='r4';Attempt='v1';StartOnly=$true;SourceAttempt='v1';StopAttempt='v1'}", '-StartOnly continues'),
    'r5_source_pair': ("@{Target='r5';Config='X';Attempt='v2';SourceAttempt='v1';StopAttempt='v1';Apply=$true;Start=$true}", None),
}
IDENTITY_CASES = {'owner_admin': ('$true', 'AETHERDESK\\ansac', '$true', None), 'not_admin': ('$true', 'AETHERDESK\\ansac', '$false', 'requires the owner'),
                  'other_admin': ('$true', 'AETHERDESK\\other', '$true', 'requires the owner'), 'plan_not_admin': ('$false', 'AETHERDESK\\guest', '$false', None)}


@pytest.fixture(scope='module')
def parameter_results(batch_dir):
    lines = ['$r=[ordered]@{}']
    for name, (args, _) in PARAMETER_CASES.items():
        lines.append(f"try{{$x=Assert-RetargetParameters {args};$r['{name}']=[ordered]@{{refused=$false;message='';value=$x}}}}catch{{$r['{name}']=[ordered]@{{refused=$true;message=$_.Exception.Message;value=$null}}}}")
    for name, (apply, user, admin, _) in IDENTITY_CASES.items():
        lines.append(f"try{{Assert-ApplyIdentity {apply} ([pscustomobject]@{{admin={admin};name='{user}'}});$r['id_{name}']=[ordered]@{{refused=$false;message=''}}}}catch{{$r['id_{name}']=[ordered]@{{refused=$true;message=$_.Exception.Message}}}}")
    lines.append('$r|ConvertTo-Json -Compress -Depth 5')
    return run(batch_dir, '\n'.join(lines))


@pytest.mark.parametrize('case', sorted(PARAMETER_CASES))
def test_parameter_rules_refuse_before_anything_is_read(parameter_results, case):
    value = parameter_results[case]
    expected = PARAMETER_CASES[case][1]
    assert value['refused'] == (expected is not None), value
    if expected:
        assert expected in value['message']
    if case == 'r4_plan_config_ignored':
        assert value['value']['config'] == '' and value['value']['config_argument_ignored'] is True
    if case == 'r5_plan':
        assert value['value']['config'] == 'X' and value['value']['config_argument_ignored'] is False
    if case == 'r5_source_pair':
        assert value['value']['source_attempt'] == 'v1' and value['value']['stop_attempt'] == 'v1' and value['value']['start'] is True
    if case == 'source_without_stop':
        assert value['value']['source_attempt'] == 'v1' and value['value']['stop_attempt'] == '', 'an r5 retarget that never started is selected by -SourceAttempt alone'


@pytest.mark.parametrize('case', sorted(IDENTITY_CASES))
def test_apply_requires_the_elevated_owner(parameter_results, case):
    value = parameter_results['id_' + case]
    expected = IDENTITY_CASES[case][3]
    assert value['refused'] == (expected is not None), value
    if expected:
        assert expected in value['message'] and 'nothing was changed' in value['message']


# ----------------------------------------------------------------------------------------------- task state and source states

@pytest.mark.parametrize('case', ['readable', 'absent', 'denied', 'definition_denied', 'other_error'])
def test_task_state_is_exact_or_explicitly_deferred(tmp_path, case):
    overrides = {'absent': '@{Absent=$true}', 'denied': '@{DenyGetTask=$true}', 'definition_denied': '@{DenyDefinition=$true}'}.get(case, '@{}')
    body = FIXTURE + f"$folder=New-FixtureFolder {overrides};"
    if case == 'other_error':
        body += "$folder|Add-Member -Force ScriptMethod GetTask {param($n)throw [Runtime.InteropServices.COMException]::new('other',-2147216625)};"
    body += r'''
      $refused=$false;$state=$null;$message='';try{$state=Get-WardenTaskState $folder}catch{$refused=$true;$message=$_.Exception.Message}
      [ordered]@{refused=$refused;readable=$(if($null -ne $state){$state.readable}else{$null});message=$message;triggers=$(if($null -ne $state -and $state.readable){@($state.trigger_list).Count}else{$null})}|ConvertTo-Json -Compress
    '''
    value = run(tmp_path, body)
    if case == 'readable':
        assert value == {'refused': False, 'readable': True, 'message': '', 'triggers': 0}
    elif case in ('denied', 'definition_denied'):
        assert value['refused'] is False and value['readable'] is False
    elif case == 'absent':
        assert value['refused'] and 'absent' in value['message']
    else:
        assert value['refused'] and 'unknown' in value['message']


SOURCE_CASES_PS = r'''
$r5=(Get-R5LiveOverrides);$r4r=(Get-R4RestoreLiveOverrides)
$cases=@(
 @{name='r4v1_enabled';over=@{}},
 @{name='r4v1_disabled';over=@{Enabled=$false;State=1}},
 @{name='r4v1_with_source_attempts';over=@{};source='v1';stop='v1'},
 @{name='r4v1_with_source_only';over=@{};source='v1'},
 @{name='r4v1_with_trigger';over=@{Triggers=@(New-FixtureTrigger)}},
 @{name='stop_without_source';over=@{};stop='v1'},
 @{name='running';over=@{State=4;Instances=1}},
 @{name='queued';over=@{State=2}},
 @{name='instance_while_ready';over=@{Instances=1}},
 @{name='principal';over=@{UserId='ansac'}},
 @{name='logon_type';over=@{LogonType=3}},
 @{name='time_limit';over=@{ExecutionTimeLimit='PT72H'}},
 @{name='multiple_instances';over=@{MultipleInstances=0}},
 @{name='restart_count';over=@{RestartCount=3}},
 @{name='two_actions';over=@{Actions=2}},
 @{name='sddl_extra_grant';over=@{Sddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;BU)'}},
 @{name='r3_action';over=@{Path=($script:r3Root+'\.venv\Scripts\python.exe');WorkingDirectory=$script:r3Root;Arguments=(Get-ExpectedArguments $script:commissioningConfig ($script:privateRoot+'\queue-commissioning-20261007-r3-v1'))};source='v1';stop='v1'},
 @{name='r4_unknown_form';over=@{Arguments=(Get-ExpectedArguments $script:commissioningConfig ($script:privateRoot+'\queue-restart-20261011-r4-v1'))};source='v1';stop='v1'},
 @{name='r5_form_wrong_queue_root';over=(Merge-Hash $r5 @{Arguments=($script:fixtureR5Args.Replace('queue-launch-r5','queue-launch-r6'))});source='v1'},
 @{name='r5_form_outside_cochem';over=(Merge-Hash $r5 @{Path='C:\Other\Pipeline4.2.7-windows-20261011-r5\.venv\Scripts\python.exe';WorkingDirectory='C:\Other\Pipeline4.2.7-windows-20261011-r5'});source='v1'},
 @{name='r5_no_attempts';over=$r5},
 @{name='r5_valid';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source}},
 @{name='r5_valid_already_stopped';over=$r5;source='v2';stop='v3';setup={Write-FixtureR5Source -Stop @{status='WARDEN_ALREADY_STOPPED_CLEAN_NOOP'}}},
 @{name='r5_receipt_missing';over=$r5;source='v1';stop='v1';setup={}},
 @{name='r5_receipt_schema';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Receipt @{schema='cochem-warden-retarget/2'}}},
 @{name='r5_receipt_target_r4';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Receipt @{target='r4'}}},
 @{name='r5_receipt_status';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Receipt @{status='WARDEN_RETARGETED_TO_R4_NOT_STARTED'}}},
 @{name='r5_receipt_attempt';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Receipt @{attempt='v2'}}},
 @{name='r5_receipt_task';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Receipt @{task_name='CoChem-4.2.2-Warden'}}},
 @{name='r5_action_differs';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Receipt @{action=[ordered]@{execute=$script:fixtureR5Py;arguments=($script:fixtureR5Args+' ');working_directory=$script:fixtureR5Root}}}},
 @{name='r5_action_case_differs';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Receipt @{action=[ordered]@{execute=$script:fixtureR5Py.ToLowerInvariant();arguments=$script:fixtureR5Args;working_directory=$script:fixtureR5Root}}}},
 @{name='r5_receipt_no_trigger';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Receipt @{triggers=@()}}},
 @{name='r5_receipt_trigger_enabled_after';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Receipt @{trigger_enabled_after=$true}}},
 @{name='r5_receipt_after_xml_sha_differs';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Receipt @{task_xml_after_sha256=('0'*64)}}},
 @{name='r5_after_xml_description_other';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Description 'Reviewed r5 retarget v9 (reboot-safe logon trigger) of the r4 retarget task. Logon trigger only, no retries; preserve on any failure.'}},
 @{name='r5_retarget_held';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -RetargetHeld}},
 @{name='r5_start_receipt_missing';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -NoStartReceipt -NoIntent}},
 @{name='r5_start_held';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -StartHeld}},
 @{name='r5_start_status';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Start @{status='WARDEN_R4_RESTARTED_HEALTH_VERIFIED'}}},
 @{name='r5_start_attempt';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Start @{attempt='v9'}}},
 @{name='r5_start_action_differs';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Start @{action=[ordered]@{execute=$script:fixtureR5Py;arguments='x';working_directory=$script:fixtureR5Root}}}},
 @{name='r5_start_retarget_sha_differs';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Start @{retarget_receipt_sha256=('0'*64)}}},
 @{name='r5_start_intent_sha_differs';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Start @{intent_sha256=('0'*64)}}},
 @{name='r5_start_trigger_after_false';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Start @{trigger_enabled_after=$false}}},
 @{name='r5_start_trigger_before_true';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Start @{trigger_enabled_before=$true}}},
 @{name='r5_start_started_sha_differs';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Start @{task_xml_started_sha256=('0'*64)}}},
 @{name='r5_live_trigger_disabled_after_start';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source};post={Set-FixtureTriggerEnabled $false}},
 @{name='r5_live_differs_from_started_xml';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source};post={$script:xmlExtra='<Priority>4</Priority>'}},
 @{name='r5_live_enabled';over=(Merge-Hash $r5 @{Enabled=$true;State=3});source='v1';stop='v1';setup={Write-FixtureR5Source}},
 @{name='r5_live_trigger_user';over=(Merge-Hash $r5 @{Triggers=@(New-FixtureTrigger 9 'AETHERDESK\other' 'PT1M')});source='v1';stop='v1';setup={Write-FixtureR5Source}},
 @{name='r5_live_no_trigger';over=(Merge-Hash $r5 @{Triggers=@()});source='v1';stop='v1';setup={Write-FixtureR5Source}},
 @{name='r5_running';over=(Merge-Hash $r5 @{State=4;Instances=1});source='v1';stop='v1';setup={Write-FixtureR5Source}},
 @{name='r5_stop_missing';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -NoStop}},
 @{name='r5_stop_held';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -StopHeld}},
 @{name='r5_stop_schema';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{schema='cochem-warden-stop/1'}}},
 @{name='r5_stop_status';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{status='WARDEN_ENDED_AND_DISABLED'}}},
 @{name='r5_stop_attempt';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{retarget_attempt='v2'}}},
 @{name='r5_stop_task';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{task_name='CoChem-4.2.2-Warden'}}},
 @{name='r5_stop_target_r4';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{retarget_target='r4'}}},
 @{name='r5_stop_target_missing';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{retarget_target=$null}}},
 @{name='r5_stop_enabled_after';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{enabled_after=$true}}},
 @{name='r5_stop_enabled_after_string';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{enabled_after='false'}}},
 @{name='r5_stop_instances_after';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{instances_after=1}}},
 @{name='r5_stop_instances_string';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{instances_after='0'}}},
 @{name='r5_stop_xml_differs';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{task_xml_after_sha256=('0'*64)}}},
 @{name='r5_stop_binding_wrong';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{start_binding='START_CRASHED_NO_RECORD'}}},
 @{name='r5_stop_binding_missing';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{start_binding=$null}}},
 @{name='r5_stop_start_sha_differs';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{start_receipt_sha256=('0'*64)}}},
 @{name='r5_stop_retarget_sha_differs';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{retarget_receipt_sha256=('0'*64)}}},
 @{name='r5_stop_intent_sha_differs';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{start_intent_sha256=('0'*64)}}},
 @{name='r5_stop_after_xml_sha_differs';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{source_task_xml_after_sha256=('0'*64)}}},
 @{name='r5_stop_trigger_wrong';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{trigger_enabled_after=$false}}},
 @{name='r5_stop_trigger_missing';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5Source -Stop @{trigger_enabled_after=$null}}},
 @{name='r5_wrong_stop_namespace';over=$r5;source='v1';stop='v2';setup={$script:StopAttempt='v1';Write-FixtureR5Source;$script:StopAttempt='v2'}},
 @{name='r5sh_interrupted';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'interrupted'}},
 @{name='r5sh_interrupted_trigger_enabled';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'interrupted' -TriggerEnabled $true}},
 @{name='r5sh_gate';over=$r5;source='v2';stop='v3';setup={Write-FixtureHeldStart 'r5' 'gate'}},
 @{name='r5sh_gate_trigger_enabled';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'gate' -TriggerEnabled $true}},
 @{name='r5sh_crashed';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'crashed'}},
 @{name='r5sh_crashed_trigger_enabled';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'crashed' -TriggerEnabled $true}},
 @{name='r5sh_held_trigger_null_live_enabled';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'interrupted' -TriggerEnabled $true -Held @{trigger_enabled_after=$null}}},
 @{name='r5sh_before_gate';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'before_gate'}},
 @{name='r5sh_before_gate_post_readback';over=$r5;source='v2';stop='v4';setup={Write-FixtureHeldStart 'r5' 'before_gate' -Held @{stage='POST_START_READBACK'}}},
 @{name='r4sh_before_gate';over=$r4r;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r4' 'before_gate'}},
 @{name='r5sh_before_run_held';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'before_run'}},
 @{name='r5sh_interrupted_before_run';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'before_run' -Held @{interrupted=$true;stop_recovery_allowed=$true}}},
 @{name='r5sh_allowed_inconsistent';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'before_run' -Held @{stop_recovery_allowed=$true}}},
 @{name='r5sh_before_gate_not_allowed';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'before_gate' -Held @{stop_recovery_allowed=$false}}},
 @{name='r5sh_gate_before_run_inconsistent';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'gate' -Held @{held_before_run=$true}}},
 @{name='r5sh_held_before_run_string';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'before_gate' -Held @{held_before_run='false'}}},
 @{name='r5sh_stop_binding_interrupted_for_before_gate';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'before_gate' -Binding 'START_INTERRUPTED_HELD'}},
 @{name='r5sh_receipt_written';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'interrupted' -Held @{receipt_written=$true}}},
 @{name='r5sh_interrupted_string';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'interrupted' -Held @{interrupted='true'}}},
 @{name='r5sh_held_attempt';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'interrupted' -Held @{attempt='v9'}}},
 @{name='r5sh_held_trigger_disabled_live_enabled';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'interrupted' -TriggerEnabled $true -Held @{trigger_enabled_after=$false}}},
 @{name='r5sh_held_trigger_string';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'interrupted' -Held @{trigger_enabled_after='false'}}},
 @{name='r5sh_intent_retarget_sha';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'interrupted' -Intent @{retarget_receipt_sha256=('0'*64)}}},
 @{name='r5sh_stop_binding_receipt';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'interrupted' -Binding 'START_RECEIPT'}},
 @{name='r5sh_stop_binding_gate_for_interrupted';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'interrupted' -Binding 'START_HELD_AFTER_HEALTH_GATE'}},
 @{name='r5sh_stop_held_sha';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'interrupted' -Stop @{start_held_sha256=('0'*64)}}},
 @{name='r5sh_live_xml_differs';over=$r5;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'crashed'};post={$script:xmlExtra='<Priority>4</Priority>'}},
 @{name='r5sh_live_enabled';over=(Merge-Hash $r5 @{Enabled=$true;State=3});source='v1';stop='v1';setup={Write-FixtureHeldStart 'r5' 'interrupted'}},
 @{name='r4sh_interrupted';over=$r4r;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r4' 'interrupted'}},
 @{name='r4sh_crashed';over=$r4r;source='v1';stop='v2';setup={Write-FixtureHeldStart 'r4' 'crashed'}},
 @{name='r4sh_held_trigger_bool';over=$r4r;source='v1';stop='v1';setup={Write-FixtureHeldStart 'r4' 'interrupted' -Held @{trigger_enabled_after=$false}}},
 @{name='r5rt_no_start';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted}},
 @{name='r5rt_held_before_run';over=$r5;source='v3';setup={Write-FixtureR5NeverStarted -HeldBeforeRun}},
 @{name='r5rt_run_threw_without_instance';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -HeldBeforeRun -Held @{run_requested=$true;run_exception='run refused'}}},
 @{name='r5rt_receipt_missing';over=$r5;source='v1';setup={}},
 @{name='r5rt_with_stop_but_never_started';over=$r5;source='v1';stop='v1';setup={Write-FixtureR5NeverStarted}},
 @{name='r5rt_held_after_run';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -HeldBeforeRun -Held @{run_requested=$true;held_before_run=$false}}},
 @{name='r5rt_run_threw_no_exception';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -HeldBeforeRun -Held @{run_requested=$true}}},
 @{name='r5rt_run_threw_instance_seen';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -HeldBeforeRun -Held @{run_requested=$true;run_exception='run refused';running_instances=1}}},
 @{name='r5rt_held_before_run_missing';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -HeldBeforeRun -Held @{held_before_run=$null}}},
 @{name='r5rt_held_instance_guid';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -HeldBeforeRun -Held @{instance_guid='{00000000-0000-0000-0000-00000000aaaa}'}}},
 @{name='r5rt_held_enabled_after_true';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -HeldBeforeRun -Held @{enabled_after=$true}}},
 @{name='r5rt_held_enabled_after_missing';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -HeldBeforeRun -Held @{enabled_after=$null}}},
 @{name='r5rt_held_trigger_enabled';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -HeldBeforeRun -Held @{trigger_enabled_after=$true}}},
 @{name='r5rt_held_xml_missing';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -HeldBeforeRun -Held @{task_xml_after_sha256=$null}}},
 @{name='r5rt_held_xml_differs';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -HeldBeforeRun -Held @{task_xml_after_sha256=('0'*64)}}},
 @{name='r5rt_intent_only';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -IntentOnly}},
 @{name='r5rt_start_receipt_present';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -StartReceipt}},
 @{name='r5rt_held_and_start_receipt';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -HeldBeforeRun -StartReceipt}},
 @{name='r5rt_xml_differs';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -Receipt @{task_xml_sha256=('0'*64)}}},
 @{name='r5rt_enabled_after_true';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -Receipt @{enabled_after=$true}}},
 @{name='r5rt_enabled_after_missing';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -Receipt @{enabled_after=$null}}},
 @{name='r5rt_trigger_enabled_after_missing';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -Receipt @{trigger_enabled_after=$null}}},
 @{name='r5rt_receipt_status';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -Receipt @{status='WARDEN_R5_RUNNING_HEALTH_VERIFIED'}}},
 @{name='r5rt_receipt_attempt';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -Receipt @{attempt='v2'}}},
 @{name='r5rt_action_differs';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -Receipt @{action=[ordered]@{execute=$script:fixtureR5Py;arguments=($script:fixtureR5Args+' ');working_directory=$script:fixtureR5Root}}}},
 @{name='r5rt_retarget_held';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted -RetargetHeld}},
 @{name='r5rt_live_enabled';over=(Merge-Hash $r5 @{Enabled=$true;State=3});source='v1';setup={Write-FixtureR5NeverStarted}},
 @{name='r5rt_live_trigger_enabled';over=$r5;source='v1';setup={Write-FixtureR5NeverStarted};post={Set-FixtureTriggerEnabled $true}},
 @{name='r5rt_running';over=(Merge-Hash $r5 @{State=4;Instances=1});source='v1';setup={Write-FixtureR5NeverStarted}},
 @{name='r5rt_trigger_differs';over=(Merge-Hash $r5 @{Triggers=@(New-FixtureTrigger 9 'AETHERDESK\ansac' 'PT5M' $false)});source='v1';setup={Write-FixtureR5NeverStarted}},
 @{name='r4rt_no_start';over=$r4r;source='v1';setup={Write-FixtureNeverStarted 'r4'}},
 @{name='r4rt_held_before_run';over=(Get-R4RestoreLiveOverrides 'v2');source='v2';setup={Write-FixtureNeverStarted 'r4' -HeldBeforeRun}},
 @{name='r4rt_intent_only';over=$r4r;source='v1';setup={Write-FixtureNeverStarted 'r4' -IntentOnly}},
 @{name='r4rt_trigger';over=(Merge-Hash $r4r @{Triggers=@(New-FixtureTrigger -Enabled $false)});source='v1';setup={Write-FixtureNeverStarted 'r4'}},
 @{name='r4rt_receipt_target_r5';over=$r4r;source='v1';setup={Write-FixtureNeverStarted 'r4' -Receipt @{target='r5'}}},
 @{name='r4rt_receipt_config';over=$r4r;source='v1';setup={Write-FixtureNeverStarted 'r4' -Receipt @{config_path=$script:commissioningConfig}}},
 @{name='r4rt_receipt_trigger_bool';over=$r4r;source='v1';setup={Write-FixtureNeverStarted 'r4' -Receipt @{trigger_enabled_after=$false}}},
 @{name='r5rh_readback';target='r4';over=$r5;source='v1';setup={$null=Write-FixtureRetargetHeld 'r5' 'readback'}},
 @{name='r5rh_readback_trigger_user_sid';target='r4';over=(Merge-Hash $r5 @{Triggers=@(New-FixtureTrigger 9 'S-1-5-21-1-2-3-1001' 'PT1M' $false)});source='v1';setup={$null=Write-FixtureRetargetHeld 'r5' 'readback'}},
 @{name='r5rh_unreadable';target='r4';over=$r5;source='v2';setup={$null=Write-FixtureRetargetHeld 'r5' 'unreadable'}},
 @{name='r5rh_interrupted';target='r4';over=$r5;source='v1';setup={$null=Write-FixtureRetargetHeld 'r5' 'none'}},
 @{name='r5rh_interrupted_with_after_xml';target='r4';over=$r5;source='v1';setup={$root=Write-FixtureRetargetHeld 'r5' 'none';$null=Write-FixtureText (Join-Path $root 'warden-task-after.xml') $script:task.Xml}},
 @{name='r5rh_unreadable_with_after_xml';target='r4';over=$r5;source='v1';setup={$root=Write-FixtureRetargetHeld 'r5' 'unreadable';$null=Write-FixtureText (Join-Path $root 'warden-task-after.xml') $script:task.Xml}},
 @{name='r5rh_unreadable_after_xml_differs';target='r4';over=$r5;source='v1';setup={$root=Write-FixtureRetargetHeld 'r5' 'unreadable';$null=Write-FixtureText (Join-Path $root 'warden-task-after.xml') 'x'}},
 @{name='r4rh_readback';target='r4';over=$r4r;source='v1';setup={$null=Write-FixtureRetargetHeld 'r4' 'readback'}},
 @{name='r5rh_target_r5';over=$r5;source='v1';setup={$null=Write-FixtureRetargetHeld 'r5' 'readback'}},
 @{name='r5rh_readback_xml_differs';target='r4';over=$r5;source='v1';setup={$null=Write-FixtureRetargetHeld 'r5' 'readback' -Record @{readback=[ordered]@{enabled=$false;instances=0;task_xml_sha256=('0'*64)}}}},
 @{name='r5rh_readback_enabled';target='r4';over=$r5;source='v1';setup={$null=Write-FixtureRetargetHeld 'r5' 'readback' -Record @{readback=[ordered]@{enabled=$true;instances=0;task_xml_sha256=(Get-TaskXmlSha256 $script:task.Xml)}}}},
 @{name='r5rh_wrong_phase';target='r4';over=$r5;source='v1';setup={$null=Write-FixtureRetargetHeld 'r5' 'readback' -Record @{phase='PREPARATION'}}},
 @{name='r5rh_not_mutated';target='r4';over=$r5;source='v1';setup={$null=Write-FixtureRetargetHeld 'r5' 'readback' -Record @{mutation_requested=$false}}},
 @{name='r5rh_before_xml_outside_changed';target='r4';over=$r5;source='v1';setup={$null=Write-FixtureRetargetHeld 'r5' 'readback' -BeforeExtra '<Priority>4</Priority>'}},
 @{name='r5rh_sddl_differs';target='r4';over=$r5;source='v1';setup={$null=Write-FixtureRetargetHeld 'r5' 'readback' -BeforeSddl 'O:BAG:BAD:PAI(A;;FA;;;SY)'}},
 @{name='r5rh_action_differs';target='r4';over=$r5;source='v1';setup={$null=Write-FixtureRetargetHeld 'r5' 'readback' -Intent @{action_after=[ordered]@{execute=$script:fixtureR5Py;arguments='x';working_directory=$script:fixtureR5Root}}}},
 @{name='r5rh_intent_attempt';target='r4';over=$r5;source='v1';setup={$null=Write-FixtureRetargetHeld 'r5' 'readback' -Intent @{attempt='v2'}}},
 @{name='r5rh_with_start_intent';target='r4';over=$r5;source='v1';setup={$null=Write-FixtureRetargetHeld 'r5' 'readback' -StartIntent}},
 @{name='r5rh_description_other';target='r4';over=$r5;source='v1';setup={$null=Write-FixtureRetargetHeld 'r5' 'none'};post={$script:definition.RegistrationInfo.Description='d'}},
 @{name='r5rh_live_enabled';target='r4';over=(Merge-Hash $r5 @{Enabled=$true;State=3});source='v1';setup={$null=Write-FixtureRetargetHeld 'r5' 'readback'}},
 @{name='r5rh_interrupted_trigger_enabled';target='r4';over=$r5;source='v1';setup={$null=Write-FixtureRetargetHeld 'r5' 'none'};post={Set-FixtureTriggerEnabled $true}},
 @{name='r5rh_interrupted_trigger_user';target='r4';over=(Merge-Hash $r5 @{Triggers=@(New-FixtureTrigger 9 'S-1-5-21-1-2-3-1001' 'PT1M' $false)});source='v1';setup={$null=Write-FixtureRetargetHeld 'r5' 'none'}},
 @{name='r5rh_interrupted_after_xml_differs';target='r4';over=$r5;source='v1';setup={$root=Write-FixtureRetargetHeld 'r5' 'none';$null=Write-FixtureText (Join-Path $root 'warden-task-after.xml') 'x'}},
 @{name='r4r_valid';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource}},
 @{name='r4r_valid_already_stopped';over=(Get-R4RestoreLiveOverrides 'v2');source='v2';stop='v4';setup={Write-FixtureR4RestoreSource -Stop @{status='WARDEN_ALREADY_STOPPED_CLEAN_NOOP'}}},
 @{name='r4r_no_attempts';over=$r4r},
 @{name='r4r_source_only';over=$r4r;source='v1';setup={Write-FixtureR4RestoreSource}},
 @{name='r4r_queue_attempt_mismatch';over=$r4r;source='v2';stop='v1';setup={Write-FixtureR4RestoreSource}},
 @{name='r4r_start_missing';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -NoStart}},
 @{name='r4r_start_schema';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -Start @{schema='cochem-warden-start/2'}}},
 @{name='r4r_start_status';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -Start @{status='WARDEN_R4_RUNNING_HEALTH_VERIFIED'}}},
 @{name='r4r_start_target';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -Start @{target='r5'}}},
 @{name='r4r_start_attempt';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -Start @{attempt='v2'}}},
 @{name='r4r_start_root';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -Start @{runtime_root=$script:r3Root}}},
 @{name='r4r_start_config_path';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -Start @{config_path=$script:commissioningConfig}}},
 @{name='r4r_start_config_sha';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -Start @{config_sha256=('0'*64)}}},
 @{name='r4r_start_triggers';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -Start @{triggers=@([ordered]@{type='logon';user_id='AETHERDESK\ansac';delay='PT1M'})}}},
 @{name='r4r_start_trigger_bool';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -Start @{trigger_enabled_after=$true}}},
 @{name='r4r_start_action_differs';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -Start @{action=[ordered]@{execute=$script:r4Python;arguments='x';working_directory=$script:r4Root}}}},
 @{name='r4r_retarget_missing';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource;Remove-FixtureFile 'r4' 'retarget-receipt.json'}},
 @{name='r4r_after_xml_missing';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource;Remove-FixtureFile 'r4' 'warden-task-after.xml'}},
 @{name='r4r_retarget_held';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -RetargetHeld}},
 @{name='r4r_start_held';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -StartHeld}},
 @{name='r4r_live_enabled';over=(Merge-Hash $r4r @{Enabled=$true;State=3});source='v1';stop='v1';setup={Write-FixtureR4RestoreSource}},
 @{name='r4r_live_trigger';over=(Merge-Hash $r4r @{Triggers=@(New-FixtureTrigger)});source='v1';stop='v1';setup={Write-FixtureR4RestoreSource}},
 @{name='r4r_running';over=(Merge-Hash $r4r @{State=4;Instances=1});source='v1';stop='v1';setup={Write-FixtureR4RestoreSource}},
 @{name='r4r_stop_target_r5';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -Stop @{retarget_target='r5'}}},
 @{name='r4r_stop_target_missing';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -Stop @{retarget_target=$null}}},
 @{name='r4r_stop_attempt';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -Stop @{retarget_attempt='v2'}}},
 @{name='r4r_stop_xml';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -Stop @{task_xml_after_sha256=('0'*64)}}},
 @{name='r4r_stop_trigger_bool';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -Stop @{trigger_enabled_after=$false}}},
 @{name='r4r_stop_binding_wrong';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -Stop @{start_binding='START_INTERRUPTED_HELD'}}},
 @{name='r4r_stop_held';over=$r4r;source='v1';stop='v1';setup={Write-FixtureR4RestoreSource -StopHeld}}
)
function Remove-FixtureFile {param([string]$Target,[string]$Name)[IO.File]::Delete((Join-Path (Get-FixtureRetargetRoot $Target) $Name))}
$results=[ordered]@{}
foreach($case in $cases){
  $script:base=Join-Path '__TMP__' $case.name;$null=[IO.Directory]::CreateDirectory($script:base)
  $script:SourceAttempt=[string]$case['source'];$script:StopAttempt=[string]$case['stop'];$script:Target=$(if($case['target']){[string]$case['target']}else{'r5'})
  $folder=New-FixtureFolder $case['over']
  if($null -ne $case['setup']){. $case['setup']}
  if($null -ne $case['post']){. $case['post']}
  try{$s=Assert-RetargetSource (Get-WardenTaskState $folder)
      $results[$case.name]=[ordered]@{refused=$false;message='';state=$s.source_state;source=$s.source_attempt;stop=$s.stop_attempt;stop_sha=$s.stop_receipt_sha256;source_sha=$s.source_receipt_sha256;
        start_sha=$s.source_start_receipt_sha256;evidence=$s.source_start_evidence;stop_status=$s.stop_status;xml=$s.task_xml_sha256;enabled=$s.enabled_before;
        intent_sha=$s.source_start_intent_sha256;held_sha=$s.source_start_held_sha256;retarget_held_sha=$s.source_retarget_held_sha256;mutation=$s.source_mutation_evidence;
        binding=$s.stop_start_binding;trigger=$s.trigger_enabled_before;config=$s.source_config_sha256;keys=@($s.Keys)}}
  catch{$results[$case.name]=[ordered]@{refused=$true;message=$_.Exception.Message}}}
$results|ConvertTo-Json -Compress -Depth 4
'''
BINDS = 'does not bind attempt'
PROVES = 'does not prove'
EVIDENCE = 'does not bind the start evidence'
NO_RECOVERY = 'does not allow a stop recovery'
BEFORE_RUN = 'does not prove the hold came before Run'
SOURCE_KEYS = ['source_state', 'source_attempt', 'stop_attempt', 'source_receipt_path', 'source_receipt_sha256', 'source_start_receipt_sha256', 'source_start_evidence',
               'source_start_intent_sha256', 'source_start_held_sha256', 'source_retarget_held_sha256', 'source_mutation_evidence', 'stop_receipt_path', 'stop_receipt_sha256',
               'stop_status', 'stop_start_binding', 'source_config_sha256', 'enabled_before', 'trigger_enabled_before', 'task_xml_sha256']
SOURCE_EXPECTED = {
    # accepted: (source_state, source, stop, start evidence / mutation evidence, live trigger enabled)
    'r4v1_enabled': ('r4-v1', None, None, None, None), 'r4v1_disabled': ('r4-v1', None, None, None, None),
    'r5_valid': ('r5-receipt', 'v1', 'v1', 'START_RECEIPT', True), 'r5_valid_already_stopped': ('r5-receipt', 'v2', 'v3', 'START_RECEIPT', True),
    'r5sh_interrupted': ('r5-start-held', 'v1', 'v1', 'START_INTERRUPTED_HELD', False),
    'r5sh_interrupted_trigger_enabled': ('r5-start-held', 'v1', 'v1', 'START_INTERRUPTED_HELD', True),
    'r5sh_gate': ('r5-start-held', 'v2', 'v3', 'START_HELD_AFTER_HEALTH_GATE', False), 'r5sh_gate_trigger_enabled': ('r5-start-held', 'v1', 'v1', 'START_HELD_AFTER_HEALTH_GATE', True),
    'r5sh_crashed': ('r5-start-held', 'v1', 'v1', 'START_CRASHED_NO_RECORD', False), 'r5sh_crashed_trigger_enabled': ('r5-start-held', 'v1', 'v1', 'START_CRASHED_NO_RECORD', True),
    'r5sh_held_trigger_null_live_enabled': ('r5-start-held', 'v1', 'v1', 'START_INTERRUPTED_HELD', True),
    # re-audit R-F1: every hold after Run is recovered through the stop, including one held before its health gate passed
    'r5sh_before_gate': ('r5-start-held', 'v1', 'v1', 'START_HELD_BEFORE_HEALTH_GATE', False),
    'r5sh_before_gate_post_readback': ('r5-start-held', 'v2', 'v4', 'START_HELD_BEFORE_HEALTH_GATE', False),
    'r4sh_before_gate': ('r4-restore-start-held', 'v1', 'v1', 'START_HELD_BEFORE_HEALTH_GATE', None),
    'r4sh_interrupted': ('r4-restore-start-held', 'v1', 'v1', 'START_INTERRUPTED_HELD', None), 'r4sh_crashed': ('r4-restore-start-held', 'v1', 'v2', 'START_CRASHED_NO_RECORD', None),
    'r5rt_no_start': ('r5-retarget-receipt', 'v1', None, 'NO_START', False), 'r5rt_held_before_run': ('r5-retarget-receipt', 'v3', None, 'START_HELD_BEFORE_RUN', False),
    'r5rt_run_threw_without_instance': ('r5-retarget-receipt', 'v1', None, 'START_HELD_BEFORE_RUN', False),
    'r4rt_no_start': ('r4-restore-retarget-receipt', 'v1', None, 'NO_START', None), 'r4rt_held_before_run': ('r4-restore-retarget-receipt', 'v2', None, 'START_HELD_BEFORE_RUN', None),
    'r5rh_readback': ('r5-retarget-held', 'v1', None, 'MUTATION_READBACK_HELD', False), 'r5rh_readback_trigger_user_sid': ('r5-retarget-held', 'v1', None, 'MUTATION_READBACK_HELD', False),
    'r5rh_unreadable': ('r5-retarget-held', 'v2', None, 'MUTATION_READBACK_UNREADABLE', False), 'r5rh_interrupted': ('r5-retarget-held', 'v1', None, 'MUTATION_INTERRUPTED', False),
    'r5rh_interrupted_with_after_xml': ('r5-retarget-held', 'v1', None, 'MUTATION_INTERRUPTED', False), 'r4rh_readback': ('r4-restore-retarget-held', 'v1', None, 'MUTATION_READBACK_HELD', None),
    # DIAG-BINDING 6: an unreadable readback with warden-task-after.xml present reads that file after the held record (the real
    # Read-R3Control's $held.Add must reach the main's list, not the record).
    'r5rh_unreadable_with_after_xml': ('r5-retarget-held', 'v1', None, 'MUTATION_READBACK_UNREADABLE', False),
    'r4r_valid': ('r4-restore-receipt', 'v1', 'v1', 'START_RECEIPT', None), 'r4r_valid_already_stopped': ('r4-restore-receipt', 'v2', 'v4', 'START_RECEIPT', None),
    # refused: message fragment
    'r4v1_with_source_attempts': 'apply only to a later source', 'r4v1_with_source_only': 'apply only to a later source', 'r4v1_with_trigger': 'must have no trigger',
    'stop_without_source': '-StopAttempt needs -SourceAttempt', 'running': 'running or queued', 'queued': 'running or queued', 'instance_while_ready': 'running or queued',
    'principal': 'exact reviewed SYSTEM', 'logon_type': 'exact reviewed SYSTEM', 'time_limit': 'exact reviewed SYSTEM', 'multiple_instances': 'exact reviewed SYSTEM',
    'restart_count': 'exact reviewed SYSTEM', 'two_actions': 'exact reviewed SYSTEM', 'sddl_extra_grant': 'ownership/private DACL',
    'r3_action': 'neither the pinned r4-v1 action', 'r4_unknown_form': 'neither the pinned r4-v1 action', 'r5_form_wrong_queue_root': 'neither the pinned r4-v1 action',
    'r5_form_outside_cochem': 'neither the pinned r4-v1 action', 'r5_no_attempts': 'An r5 source needs -SourceAttempt',
    'r5_receipt_missing': 'has no start receipt', 'r5_receipt_schema': BINDS, 'r5_receipt_target_r4': BINDS, 'r5_receipt_status': BINDS, 'r5_receipt_attempt': BINDS,
    'r5_receipt_task': BINDS, 'r5_action_differs': 'differs from the r5 action recorded', 'r5_action_case_differs': 'differs from the r5 action recorded',
    'r5_receipt_no_trigger': 'reviewed logon trigger', 'r5_receipt_trigger_enabled_after': 'registered disabled (trigger_enabled_after)',
    'r5_receipt_after_xml_sha_differs': 'does not record its task XML', 'r5_after_xml_description_other': "carry that attempt's registration description",
    'r5_retarget_held': 'holds retarget-held.json', 'r5_start_receipt_missing': 'has no start receipt',
    'r5_start_held': 'holds start-held.json', 'r5_start_status': 'start receipt does not bind', 'r5_start_attempt': 'start receipt does not bind',
    'r5_start_action_differs': 'start receipt does not bind', 'r5_start_retarget_sha_differs': 'start receipt does not bind',
    'r5_start_intent_sha_differs': 'does not bind the start intent', 'r5_start_trigger_after_false': 'verified two-phase start',
    'r5_start_trigger_before_true': 'verified two-phase start', 'r5_start_started_sha_differs': 'verified two-phase start',
    'r5_live_trigger_disabled_after_start': 'it must be enabled', 'r5_live_differs_from_started_xml': 'warden-task-started.xml',
    'r5_live_enabled': 'must be disabled by stop-warden-r5', 'r5_live_trigger_user': 'logon trigger',
    'r5_live_no_trigger': 'exactly one logon trigger', 'r5_running': 'running or queued', 'r5_stop_missing': 'Fixture control missing', 'r5_stop_held': 'holds stop-held.json',
    'r5_stop_schema': PROVES, 'r5_stop_status': PROVES, 'r5_stop_attempt': PROVES, 'r5_stop_task': PROVES, 'r5_stop_target_r4': PROVES, 'r5_stop_target_missing': PROVES,
    'r5_stop_enabled_after': PROVES, 'r5_stop_enabled_after_string': PROVES, 'r5_stop_instances_after': PROVES, 'r5_stop_instances_string': PROVES,
    'r5_stop_xml_differs': 'task_xml_after_sha256 differs', 'r5_stop_binding_wrong': EVIDENCE, 'r5_stop_binding_missing': EVIDENCE, 'r5_stop_start_sha_differs': EVIDENCE,
    'r5_stop_retarget_sha_differs': EVIDENCE, 'r5_stop_intent_sha_differs': EVIDENCE, 'r5_stop_after_xml_sha_differs': EVIDENCE,
    'r5_stop_trigger_wrong': 'live logon trigger state', 'r5_stop_trigger_missing': 'live logon trigger state', 'r5_wrong_stop_namespace': 'Fixture control missing',
    'r5sh_before_run_held': NO_RECOVERY, 'r5sh_interrupted_before_run': NO_RECOVERY, 'r5sh_allowed_inconsistent': NO_RECOVERY,
    'r5sh_before_gate_not_allowed': NO_RECOVERY, 'r5sh_gate_before_run_inconsistent': NO_RECOVERY, 'r5sh_held_before_run_string': NO_RECOVERY,
    'r5sh_stop_binding_interrupted_for_before_gate': EVIDENCE, 'r5sh_receipt_written': NO_RECOVERY, 'r5sh_interrupted_string': NO_RECOVERY,
    'r5sh_held_attempt': NO_RECOVERY, 'r5sh_held_trigger_disabled_live_enabled': 'it must be disabled', 'r5sh_held_trigger_string': 'invalid trigger_enabled_after',
    'r5sh_intent_retarget_sha': 'start intent does not bind', 'r5sh_stop_binding_receipt': EVIDENCE, 'r5sh_stop_binding_gate_for_interrupted': EVIDENCE,
    'r5sh_stop_held_sha': EVIDENCE, 'r5sh_live_xml_differs': 'outside the task and trigger Enabled flags', 'r5sh_live_enabled': 'must be disabled by stop-warden-r5',
    'r4sh_held_trigger_bool': 'invalid trigger_enabled_after',
    'r5rt_receipt_missing': 'has no retarget receipt and no retarget intent', 'r5rt_with_stop_but_never_started': 'has no start receipt',
    'r5rt_held_after_run': BEFORE_RUN, 'r5rt_run_threw_no_exception': BEFORE_RUN, 'r5rt_run_threw_instance_seen': BEFORE_RUN, 'r5rt_held_before_run_missing': BEFORE_RUN,
    'r5rt_held_instance_guid': BEFORE_RUN, 'r5rt_held_enabled_after_true': BEFORE_RUN, 'r5rt_held_enabled_after_missing': BEFORE_RUN, 'r5rt_held_trigger_enabled': BEFORE_RUN,
    'r5rt_held_xml_missing': BEFORE_RUN, 'r5rt_held_xml_differs': 'task XML differs from the one the r5 retarget attempt recorded',
    'r5rt_intent_only': 'start-intent.json without start-held.json', 'r5rt_start_receipt_present': 'holds a start receipt', 'r5rt_held_and_start_receipt': 'holds a start receipt',
    'r5rt_xml_differs': 'does not record its task XML', 'r5rt_enabled_after_true': 'registered disabled (enabled_after false)',
    'r5rt_enabled_after_missing': 'registered disabled (enabled_after false)', 'r5rt_trigger_enabled_after_missing': 'registered disabled (trigger_enabled_after)',
    'r5rt_receipt_status': BINDS, 'r5rt_receipt_attempt': BINDS,
    'r5rt_action_differs': 'differs from the r5 action recorded', 'r5rt_retarget_held': 'holds retarget-held.json', 'r5rt_live_enabled': 'must still be disabled',
    'r5rt_live_trigger_enabled': 'it must be disabled', 'r5rt_running': 'running or queued', 'r5rt_trigger_differs': 'logon trigger',
    'r4rt_intent_only': 'start-intent.json without start-held.json', 'r4rt_trigger': 'must have no trigger', 'r4rt_receipt_target_r5': BINDS, 'r4rt_receipt_config': BINDS,
    'r4rt_receipt_trigger_bool': 'registered disabled (trigger_enabled_after)',
    'r5rh_target_r5': 'its reviewed recovery is an r4 restore', 'r5rh_readback_xml_differs': 'does not show the task disabled', 'r5rh_readback_enabled': 'does not show the task disabled',
    'r5rh_wrong_phase': 'not a MUTATION_READBACK hold', 'r5rh_not_mutated': 'not a MUTATION_READBACK hold', 'r5rh_before_xml_outside_changed': 'changed outside Actions/Triggers',
    'r5rh_sddl_differs': 'security descriptor differs', 'r5rh_action_differs': 'retarget intent does not bind', 'r5rh_intent_attempt': 'retarget intent does not bind',
    'r5rh_with_start_intent': 'holds start-intent.json without a retarget receipt', 'r5rh_description_other': 'registration description',
    'r5rh_live_enabled': 'must have left the task disabled', 'r5rh_interrupted_trigger_enabled': 'it must be disabled', 'r5rh_interrupted_trigger_user': 'logon trigger',
    'r5rh_interrupted_after_xml_differs': 'differs from the warden-task-after.xml', 'r5rh_unreadable_after_xml_differs': 'differs from the warden-task-after.xml',
    'r4r_no_attempts': 'An r4 restore source needs -SourceAttempt', 'r4r_source_only': 'holds a start receipt', 'r4r_queue_attempt_mismatch': 'names queue attempt v1, not -SourceAttempt v2',
    'r4r_start_missing': 'has no start receipt', 'r4r_start_schema': BINDS, 'r4r_start_status': BINDS, 'r4r_start_target': BINDS, 'r4r_start_attempt': BINDS,
    'r4r_start_root': BINDS, 'r4r_start_config_path': BINDS, 'r4r_start_config_sha': BINDS, 'r4r_start_triggers': BINDS, 'r4r_start_trigger_bool': 'verified two-phase start',
    'r4r_start_action_differs': 'start receipt does not bind', 'r4r_retarget_missing': 'Fixture control missing', 'r4r_after_xml_missing': 'Fixture control missing',
    'r4r_retarget_held': 'holds retarget-held.json', 'r4r_start_held': 'holds start-held.json',
    'r4r_live_enabled': 'must be disabled by stop-warden-r5', 'r4r_live_trigger': 'must have no trigger', 'r4r_running': 'running or queued',
    'r4r_stop_target_r5': PROVES, 'r4r_stop_target_missing': PROVES, 'r4r_stop_attempt': PROVES, 'r4r_stop_xml': 'task_xml_after_sha256 differs', 'r4r_stop_held': 'holds stop-held.json',
    'r4r_stop_trigger_bool': 'live logon trigger state', 'r4r_stop_binding_wrong': EVIDENCE,
}


@pytest.fixture(scope='module')
def source_results(batch_dir):
    folder = batch_dir / 'sources'
    folder.mkdir()
    return run(batch_dir, FIXTURE + SOURCE_CASES_PS.replace('__TMP__', ps(folder)), timeout=600)


@pytest.mark.parametrize('case', sorted(SOURCE_EXPECTED))
def test_retarget_source_accepts_exactly_the_reviewed_source_states(source_results, case):
    value = source_results[case]
    expected = SOURCE_EXPECTED[case]
    if isinstance(expected, str):
        assert value['refused'] is True, value
        assert expected in value['message'], value['message']
        return
    state, source, stop, evidence, trigger = expected
    assert value['refused'] is False, value
    assert value['keys'] == SOURCE_KEYS, 'one source record shape for every state'
    assert value['state'] == state and value['source'] == source and value['stop'] == stop and len(value['xml']) == 64 and value['trigger'] is trigger
    if state == 'r4-v1':
        assert value['stop_sha'] is None and value['source_sha'] is None and value['enabled'] is (case == 'r4v1_enabled') and value['evidence'] is None
        return
    assert value['enabled'] is False and len(value['source_sha']) == 64
    if state.endswith('retarget-held'):
        assert value['mutation'] == evidence and value['evidence'] is None and value['stop_sha'] is None and value['start_sha'] is None
        assert (value['retarget_held_sha'] is None) == (evidence == 'MUTATION_INTERRUPTED')
        return
    assert value['evidence'] == evidence and value['mutation'] is None and value['retarget_held_sha'] is None
    if state.endswith('retarget-receipt'):
        assert value['stop_sha'] is None and value['stop_status'] is None and value['start_sha'] is None and value['binding'] is None
        assert (value['held_sha'] is None) == (evidence == 'NO_START')
    else:
        assert len(value['stop_sha']) == 64 and len(value['intent_sha']) == 64 and value['binding'] == evidence
        assert value['stop_status'] == ('WARDEN_ALREADY_STOPPED_CLEAN_NOOP' if case.endswith('already_stopped') else 'WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED')
        if evidence == 'START_RECEIPT':
            assert len(value['start_sha']) == 64 and value['held_sha'] is None
        else:
            assert value['start_sha'] is None and (value['held_sha'] is None) == (evidence == 'START_CRASHED_NO_RECORD')


READBACK_CASES_PS = r'''
# Deterministic account resolution: the owner spellings and its SID resolve to one SID, another SID to itself.
function Get-AccountSid {param([string]$Name)
  if($Name -cin @('AETHERDESK\ansac','aetherdesk\ansac','ansac','S-1-5-21-9-9-9-1001')){return 'S-1-5-21-9-9-9-1001'}
  if($Name -ceq 'S-1-5-21-1-2-3-1001'){return 'S-1-5-21-1-2-3-1001'};$null}
$r5=New-FixtureContext 'r5';$r4=New-FixtureContext 'r4'
$r5Live=@{Path=$r5.action.execute;Arguments=$r5.action.arguments;WorkingDirectory=$r5.action.working_directory;Triggers=@(New-FixtureTrigger -Enabled $false)}
$r4Live=@{Path=$r4.action.execute;Arguments=$r4.action.arguments;WorkingDirectory=$r4.action.working_directory}
$cases=@(
 @{name='r5_valid';ctx=$r5;over=$r5Live},
 @{name='r5_valid_trigger_enabled_after_start';ctx=$r5;te=$true;over=(Merge-Hash $r5Live @{Triggers=@(New-FixtureTrigger)})},
 @{name='r5_trigger_enabled_after_update';ctx=$r5;over=(Merge-Hash $r5Live @{Triggers=@(New-FixtureTrigger)})},
 @{name='r5_trigger_disabled_after_start';ctx=$r5;te=$true;over=$r5Live},
 @{name='r5_no_trigger';ctx=$r5;over=(Merge-Hash $r5Live @{Triggers=@()})},
 @{name='r5_trigger_user';ctx=$r5;over=(Merge-Hash $r5Live @{Triggers=@(New-FixtureTrigger 9 'AETHERDESK\other' 'PT1M' $false)})},
 @{name='r5_trigger_user_case';ctx=$r5;over=(Merge-Hash $r5Live @{Triggers=@(New-FixtureTrigger 9 'aetherdesk\ansac' 'PT1M' $false)})},
 @{name='r5_trigger_user_bare';ctx=$r5;over=(Merge-Hash $r5Live @{Triggers=@(New-FixtureTrigger 9 'ansac' 'PT1M' $false)})},
 @{name='r5_trigger_user_same_sid';ctx=$r5;over=(Merge-Hash $r5Live @{Triggers=@(New-FixtureTrigger 9 'S-1-5-21-9-9-9-1001' 'PT1M' $false)})},
 @{name='r5_trigger_user_sid';ctx=$r5;over=(Merge-Hash $r5Live @{Triggers=@(New-FixtureTrigger 9 'S-1-5-21-1-2-3-1001' 'PT1M' $false)})},
 @{name='r5_trigger_user_empty';ctx=$r5;over=(Merge-Hash $r5Live @{Triggers=@(New-FixtureTrigger 9 '' 'PT1M' $false)})},
 @{name='r5_trigger_delay';ctx=$r5;over=(Merge-Hash $r5Live @{Triggers=@(New-FixtureTrigger 9 'AETHERDESK\ansac' 'PT5M' $false)})},
 @{name='r5_trigger_repetition';ctx=$r5;over=(Merge-Hash $r5Live @{Triggers=@(New-FixtureTriggerWith @{Interval='PT5M'})})},
 @{name='r5_trigger_time_limit';ctx=$r5;over=(Merge-Hash $r5Live @{Triggers=@(New-FixtureTriggerWith @{ExecutionTimeLimit='PT1H'})})},
 @{name='r5_trigger_zero_limit';ctx=$r5;over=(Merge-Hash $r5Live @{Triggers=@(New-FixtureTriggerWith @{ExecutionTimeLimit='PT0S'})})},
 @{name='r5_trigger_expiry';ctx=$r5;over=(Merge-Hash $r5Live @{Triggers=@(New-FixtureTriggerWith @{EndBoundary='2027-01-01T00:00:00'})})},
 @{name='r5_two_triggers';ctx=$r5;over=(Merge-Hash $r5Live @{Triggers=@((New-FixtureTrigger -Enabled $false),(New-FixtureTrigger -Enabled $false))})},
 @{name='r5_boot_trigger';ctx=$r5;over=(Merge-Hash $r5Live @{Triggers=@(New-FixtureTrigger 8 '' 'PT1M' $false)})},
 @{name='r5_r4_action';ctx=$r5;over=(Merge-Hash $r4Live @{Triggers=@(New-FixtureTrigger -Enabled $false)})},
 @{name='r5_principal';ctx=$r5;over=(Merge-Hash $r5Live @{UserId='ansac'})},
 @{name='r5_time_limit';ctx=$r5;over=(Merge-Hash $r5Live @{ExecutionTimeLimit='PT72H'})},
 @{name='r5_sddl_changed';ctx=$r5;over=(Merge-Hash $r5Live @{Sddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'})},
 @{name='r4_valid';ctx=$r4;over=$r4Live},
 @{name='r4_valid_after_start';ctx=$r4;te=$true;over=$r4Live},
 @{name='r4_with_trigger';ctx=$r4;over=(Merge-Hash $r4Live @{Triggers=@(New-FixtureTrigger -Enabled $false)})},
 @{name='r4_r4v1_queue';ctx=$r4;over=@{}},
 @{name='r4_r5_action';ctx=$r4;over=(Merge-Hash $r5Live @{Triggers=@()})}
)
$results=[ordered]@{}
foreach($case in $cases){
  $folder=New-FixtureFolder $case.over;$te=[bool]$case['te']
  try{Assert-RetargetedTask (Get-WardenTaskState $folder) $case.ctx '__SDDL__' $te;$results[$case.name]=''}catch{$results[$case.name]=$_.Exception.Message}}
$results|ConvertTo-Json -Compress
'''.replace('__SDDL__', SDDL)
READBACK_EXPECTED = {'r5_valid': None, 'r5_valid_trigger_enabled_after_start': None, 'r5_trigger_zero_limit': None, 'r4_valid': None, 'r4_valid_after_start': None,
                     # audit C-F2: the trigger user is compared by SID
                     'r5_trigger_user_case': None, 'r5_trigger_user_bare': None, 'r5_trigger_user_same_sid': None,
                     'r5_trigger_enabled_after_update': 'it must be disabled', 'r5_trigger_disabled_after_start': 'it must be enabled',
                     'r5_no_trigger': 'exactly one logon trigger', 'r5_trigger_user': 'logon trigger', 'r5_trigger_user_sid': 'logon trigger', 'r5_trigger_user_empty': 'logon trigger',
                     'r5_trigger_delay': 'logon trigger', 'r5_trigger_repetition': 'logon trigger', 'r5_trigger_time_limit': 'logon trigger', 'r5_trigger_expiry': 'logon trigger',
                     'r5_two_triggers': 'exactly one logon trigger', 'r5_boot_trigger': 'logon trigger', 'r5_r4_action': 'not the expected r5 action', 'r5_principal': 'principal/settings',
                     'r5_time_limit': 'principal/settings', 'r5_sddl_changed': 'security descriptor changed', 'r4_with_trigger': 'must have no trigger',
                     'r4_r4v1_queue': 'not the expected r4 action', 'r4_r5_action': 'not the expected r4 action'}


@pytest.fixture(scope='module')
def readback_results(batch_dir):
    return run(batch_dir, FIXTURE + READBACK_CASES_PS)


@pytest.mark.parametrize('case', sorted(READBACK_EXPECTED))
def test_retargeted_task_readback_requires_the_exact_action_trigger_state_and_dacl(readback_results, case):
    expected = READBACK_EXPECTED[case]
    if expected is None:
        assert readback_results[case] == ''
    else:
        assert expected in readback_results[case], readback_results[case]


def test_account_sid_resolution_compares_the_owner_by_sid_on_this_host(tmp_path):
    """Audit C-F2 on the real translation: the owner spellings and SID are one account; an unknown account never matches."""
    value = run(tmp_path, r'''
      $sid=Get-AccountSid 'AETHERDESK\ansac'
      [ordered]@{host=$env:COMPUTERNAME;sid=$sid;same_sid=$(if($sid){Test-SameAccount $sid 'AETHERDESK\ansac'}else{$null});
        same_lower=$(if($sid){Test-SameAccount 'aetherdesk\ansac' 'AETHERDESK\ansac'}else{$null});exact=(Test-SameAccount 'AETHERDESK\ansac' 'AETHERDESK\ansac');
        unknown=(Test-SameAccount 'AETHERDESK\no-such-account-c-f2' 'AETHERDESK\ansac');other_sid=(Test-SameAccount 'S-1-5-21-1-2-3-1001' 'AETHERDESK\ansac');
        empty=(Test-SameAccount '' 'AETHERDESK\ansac');bad_sid=(Get-AccountSid 'S-1-x')}|ConvertTo-Json -Compress
    ''')
    assert value['exact'] is True and value['unknown'] is False and value['other_sid'] is False and value['empty'] is False and value['bad_sid'] is None
    if value['host'] != 'AETHERDESK' or not value['sid']:
        pytest.skip('the owner account AETHERDESK\\ansac does not resolve on this host')
    assert value['sid'].startswith('S-1-5-21-') and value['same_sid'] is True and value['same_lower'] is True


XML_BEFORE = ('<Task xmlns="urn:x"><RegistrationInfo><Date>1</Date><Description>d</Description></RegistrationInfo>'
              '<Principals><Principal><UserId>S-1-5-18</UserId></Principal></Principals><Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy></Settings>'
              '<Triggers /><Actions><Exec><Command>r4</Command></Exec></Actions></Task>')


@pytest.mark.parametrize('case', ['action_trigger_description', 'trigger_removed', 'settings_enabled_inserted', 'settings_enabled_removed', 'principal_changed',
                                  'settings_priority_added', 'enabled_outside_settings'])
def test_task_xml_comparison_ignores_only_actions_triggers_registration_info_and_settings_enabled(tmp_path, case):
    after = XML_BEFORE.replace('<Command>r4</Command>', '<Command>r5</Command>').replace('<Description>d</Description>', '<Description>r5</Description>')
    before = XML_BEFORE
    if case in ('action_trigger_description',):
        after = after.replace('<Triggers />', '<Triggers><LogonTrigger><UserId>AETHERDESK\\ansac</UserId></LogonTrigger></Triggers>')
    if case == 'trigger_removed':
        before = XML_BEFORE.replace('<Triggers />', '<Triggers><LogonTrigger><Delay>PT1M</Delay></LogonTrigger></Triggers>')
    if case == 'settings_enabled_inserted':
        after = after.replace('<Settings>', '<Settings><Enabled>false</Enabled>')
    if case == 'principal_changed':
        after = after.replace('<UserId>S-1-5-18</UserId>', '<UserId>ansac</UserId>')
    if case == 'settings_enabled_removed':
        before = XML_BEFORE.replace('<Settings>', '<Settings><Enabled>false</Enabled>')
    if case == 'settings_priority_added':
        after = after.replace('</Settings>', '<Priority>4</Priority></Settings>')
    if case == 'enabled_outside_settings':
        after = after.replace('</Principal>', '<Enabled>false</Enabled></Principal>')
    value = run(tmp_path, f"$refused=$false;try{{Assert-TaskXmlOutsideRetargetUnchanged '{ps(before)}' '{ps(after)}'}}catch{{$refused=$true}};@{{refused=$refused}}|ConvertTo-Json -Compress")
    assert value['refused'] == (case in ('principal_changed', 'settings_priority_added', 'enabled_outside_settings'))


TRIGGER_VALUE_CASES = {
    'r5_ok': ('[{"type":"logon","user_id":"AETHERDESK\\\\ansac","delay":"PT1M"}]', 'r5', True),
    'r5_extra_key_ok': ('[{"type":"logon","user_id":"AETHERDESK\\\\ansac","delay":"PT1M","enabled":true}]', 'r5', True),
    'r5_empty': ('[]', 'r5', False), 'r5_two': ('[{"type":"logon","user_id":"AETHERDESK\\\\ansac","delay":"PT1M"},{"type":"logon","user_id":"AETHERDESK\\\\ansac","delay":"PT1M"}]', 'r5', False),
    'r5_user': ('[{"type":"logon","user_id":"AETHERDESK\\\\other","delay":"PT1M"}]', 'r5', False), 'r5_delay': ('[{"type":"logon","user_id":"AETHERDESK\\\\ansac","delay":"PT2M"}]', 'r5', False),
    'r5_type': ('[{"type":"boot","user_id":"AETHERDESK\\\\ansac","delay":"PT1M"}]', 'r5', False), 'r5_object': ('{"type":"logon","user_id":"AETHERDESK\\\\ansac","delay":"PT1M"}', 'r5', False),
    'r4_empty': ('[]', 'r4', True), 'r4_one': ('[{"type":"logon","user_id":"AETHERDESK\\\\ansac","delay":"PT1M"}]', 'r4', False), 'r4_null': ('null', 'r4', False),
}


def test_trigger_receipt_values_and_their_json_form(tmp_path):
    lines = ['$r=[ordered]@{}']
    for name, (text, target, _) in TRIGGER_VALUE_CASES.items():
        lines.append(f"$o=('{{\"t\":{ps(text)}}}'|ConvertFrom-Json);$r['{name}']=[bool](Test-TriggerReceiptValue (Get-JsonMember $o 't') '{target}')")
    lines.append("$r['json_r5']=([ordered]@{triggers=(Get-TriggerReceiptForm 'r5')}|ConvertTo-Json -Compress -Depth 5);$r['json_r4']=([ordered]@{triggers=(Get-TriggerReceiptForm 'r4')}|ConvertTo-Json -Compress -Depth 5)")
    lines.append('$r|ConvertTo-Json -Compress')
    value = run(tmp_path, '\n'.join(lines))
    for name, (_, _, expected) in TRIGGER_VALUE_CASES.items():
        assert value[name] is expected, name
    assert json.loads(value['json_r5']) == {'triggers': [{'type': 'logon', 'user_id': 'AETHERDESK\\ansac', 'delay': 'PT1M'}]}
    assert json.loads(value['json_r4']) == {'triggers': []}


# ----------------------------------------------------------------------------------------------- r5 bindings bound by content

REPAIRS = ['src/cochem_pipeline/__main__.py', 'src/cochem_pipeline/worker.py', 'src/cochem_supervisor/runner.py']
FAKE_R4_ROOT = r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4'


def make_r5_tree(root: Path, base_root: Path, case: str) -> str:
    root.mkdir(parents=True)
    files = {}

    def put(relative, data):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        files[relative] = hashlib.sha256(data).hexdigest()

    put('pipeline.json', b'{"reference":"135cd9ec stand-in"}')
    put('.venv/pyvenv.cfg', b'home = toolchain\r\n')
    put('.venv/Scripts/python.exe', b'MZ fake venv launcher')
    pins = {}
    for relative in REPAIRS:
        data = ('# reviewed ' + relative + '\r\n').encode('ascii')
        put('source/' + relative, data)
        put('.venv/Lib/site-packages/' + relative[4:], data)
        pins[relative] = hashlib.sha256(data).hexdigest()
    listed = [{'relative': relative, 'sha256': pins[relative], 'length': 1} for relative in REPAIRS]
    listed += [{'relative': f'src/cochem_pipeline/unchanged_{i}.py', 'sha256': '0' * 64, 'length': 1} for i in range(166 - len(listed))]
    manifest = {'schema': 'cochem-stopped-runtime-source/1', 'target_root': str(root), 'complete_source_freeze': True, 'files': listed,
                'changes_from_previous_source': {'added': [], 'removed': [], 'changed': list(REPAIRS)}}
    after = {'schema': 'cochem-stopped-runtime-update/1', 'mode': 'FRESH_STOPPED_RUNTIME_READY', 'target_root': str(root), 'previous_runtime_root': FAKE_R4_ROOT,
             'previous_install_receipt_sha256': '629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502',
             'previous_source_manifest_sha256': '1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189', 'source_manifest_sha256': None, 'source_files': 166,
             'reviewed_repairs': list(REPAIRS), 'reviewed_repairs_sha256': dict(pins), 'configuration_sha256': files['pipeline.json'], 'configuration_unchanged': True,
             'holds': [], 'tasks_changed': 0, 'pipeline_started': False, 'credentials_modified': False, 'databases_modified': False, 'ram_modified': False,
             'installed_repairs_verified': True, 'verified_unchanged': 153,
             'verification': {'revision': {'schema': 'cochem-installed-revision/1', 'verified': True, 'read_only': True, 'files': 109, 'source_sha256': '5' * 64, 'acceptance_files': 0, 'acceptance_sha256': None},
                              'configuration_parsed': True, 'ram_workspace_root': 'R:\\CoChem427-windows-20261007', 'no_system_or_model_execution': True, 'r5_repairs_installed': True},
             'runtime_bindings': {'pyvenv_sha256': files['.venv/pyvenv.cfg'], 'venv_python_sha256': files['.venv/Scripts/python.exe'],
                                  'base_python_sha256': sha256_file(base_root / 'python.exe'), 'base_root': str(base_root)}}
    mutate_manifest = {'manifest_changed_set_differs': lambda m: m['changes_from_previous_source'].update(changed=REPAIRS[:2]),
                       'manifest_added_nonempty': lambda m: m['changes_from_previous_source'].update(added=['src/x.py']),
                       'manifest_files_165': lambda m: m.update(files=m['files'][:165]), 'manifest_target_root': lambda m: m.update(target_root=FAKE_R4_ROOT),
                       'manifest_changed_missing': lambda m: m['changes_from_previous_source'].pop('changed'),
                       'manifest_repair_digest_differs': lambda m: m['files'][1].update(sha256='1' * 64),
                       'manifest_repair_unlisted': lambda m: m['files'][0].update(relative='src/cochem_pipeline/renamed.py')}
    if case in mutate_manifest:
        mutate_manifest[case](manifest)
    manifest_bytes = json.dumps(manifest, indent=2).encode('utf-8')
    (root / 'source-manifest.json').write_bytes(manifest_bytes)
    after['source_manifest_sha256'] = hashlib.sha256(manifest_bytes).hexdigest()
    mutate = {
        'schema': lambda a: a.update(schema='cochem-stopped-runtime-update/2'), 'mode': lambda a: a.update(mode='PARTIAL'),
        'target_root': lambda a: a.update(target_root=str(root) + 'x'), 'previous_root': lambda a: a.update(previous_runtime_root=R3_ROOT),
        'previous_install_pin': lambda a: a.update(previous_install_receipt_sha256='0' * 64), 'previous_manifest_pin': lambda a: a.update(previous_source_manifest_sha256='0' * 64),
        'manifest_equals_r4': lambda a: a.update(source_manifest_sha256='1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189'),
        'config_sha': lambda a: a.update(configuration_sha256='0' * 64), 'config_unchanged_string': lambda a: a.update(configuration_unchanged='true'),
        'source_files_165': lambda a: a.update(source_files=165), 'holds_nonempty': lambda a: a.update(holds=['x']), 'holds_missing': lambda a: a.pop('holds'),
        'tasks_changed_string': lambda a: a.update(tasks_changed='0'), 'pipeline_started': lambda a: a.update(pipeline_started=True),
        'credentials_modified': lambda a: a.update(credentials_modified=True), 'ram_workspace': lambda a: a['verification'].update(ram_workspace_root='R:\\other'),
        'revision_equals_r4': lambda a: a['verification']['revision'].update(source_sha256='38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e'),
        'revision_not_verified': lambda a: a['verification']['revision'].update(verified=False), 'revision_files_zero': lambda a: a['verification']['revision'].update(files=0),
        'revision_missing': lambda a: a['verification'].pop('revision'), 'base_python_pin': lambda a: a['runtime_bindings'].update(base_python_sha256='0' * 64),
        'base_root': lambda a: a['runtime_bindings'].update(base_root='C:\\Python312'), 'repairs_missing': lambda a: a.pop('reviewed_repairs'),
        'repairs_without_main': lambda a: (a.update(reviewed_repairs=REPAIRS[1:]), a['reviewed_repairs_sha256'].pop(REPAIRS[0])),
        'repairs_duplicate': lambda a: a.update(reviewed_repairs=REPAIRS + [REPAIRS[0]]),
        'repairs_bad_path': lambda a: (a.update(reviewed_repairs=REPAIRS + ['src/cochem_pipeline/../x.py']), a['reviewed_repairs_sha256'].update({'src/cochem_pipeline/../x.py': '1' * 64})),
        'repair_pins_extra_key': lambda a: a['reviewed_repairs_sha256'].update({'src/cochem_pipeline/extra.py': '1' * 64}),
        'repair_pin_not_hex': lambda a: a['reviewed_repairs_sha256'].update({REPAIRS[1]: 'Z' * 64}),
        # audit C-F4: the installer's own verification facts
        'repairs_installed_false': lambda a: a['verification'].update(r5_repairs_installed=False), 'repairs_installed_missing': lambda a: a['verification'].pop('r5_repairs_installed'),
        'repairs_verified_false': lambda a: a.update(installed_repairs_verified=False), 'repairs_verified_missing': lambda a: a.pop('installed_repairs_verified'),
        'verified_unchanged_152': lambda a: a.update(verified_unchanged=152), 'verified_unchanged_string': lambda a: a.update(verified_unchanged='153'),
    }
    if case in mutate:
        mutate[case](after)
    if case == 'installed_copy_differs':
        (root / '.venv/Lib/site-packages/cochem_pipeline/worker.py').write_bytes(b'# tampered\r\n')
    if case == 'source_copy_differs':
        (root / 'source/src/cochem_supervisor/runner.py').write_bytes(b'# tampered\r\n')
    if case == 'venv_python_differs':
        (root / '.venv/Scripts/python.exe').write_bytes(b'MZ another launcher')
    if case == 'manifest_file_differs':
        (root / 'source-manifest.json').write_bytes(manifest_bytes + b' ')
    if case == 'reference_config_differs':
        (root / 'pipeline.json').write_bytes(b'{"reference":"other"}')
    if case == 'install_held_present':
        (root / 'install-held.json').write_text('{"mode":"HELD"}', encoding='utf-8')
    text = 'not json {' if case == 'not_json' else json.dumps(after, indent=2)
    (root / 'install-after.json').write_text(text, encoding='utf-8')
    return hashlib.sha256(manifest_bytes).hexdigest()


R5_BINDING_CASES = ['valid', 'schema', 'mode', 'target_root', 'previous_root', 'previous_install_pin', 'previous_manifest_pin', 'manifest_equals_r4', 'config_sha',
                    'config_unchanged_string', 'source_files_165', 'holds_nonempty', 'holds_missing', 'tasks_changed_string', 'pipeline_started', 'credentials_modified',
                    'ram_workspace', 'revision_equals_r4', 'revision_not_verified', 'revision_files_zero', 'revision_missing', 'base_python_pin', 'base_root',
                    'repairs_missing', 'repairs_without_main', 'repairs_duplicate', 'repairs_bad_path', 'repair_pins_extra_key', 'repair_pin_not_hex',
                    'installed_copy_differs', 'source_copy_differs', 'venv_python_differs', 'manifest_file_differs', 'reference_config_differs',
                    'manifest_changed_set_differs', 'manifest_added_nonempty', 'manifest_files_165', 'manifest_target_root', 'manifest_changed_missing',
                    'manifest_repair_digest_differs', 'manifest_repair_unlisted', 'not_json',
                    'install_held_present', 'repairs_installed_false', 'repairs_installed_missing', 'repairs_verified_false', 'repairs_verified_missing',
                    'verified_unchanged_152', 'verified_unchanged_string', 'manifest_pin_differs', 'repair_pin_differs', 'repair_set_extra', 'repair_set_missing',
                    'pyvenv_pin_differs', 'launcher_pin_differs']
# Audit C-F4: the new refusals name what differs from the reviewed freeze or the installer's verification.
R5_BINDING_MESSAGES = {'install_held_present': 'install-held.json', 'repairs_installed_false': 'installed and verified', 'repairs_installed_missing': 'installed and verified',
                       'repairs_verified_false': 'installed and verified', 'repairs_verified_missing': 'installed and verified', 'verified_unchanged_152': '153 verified unchanged',
                       'verified_unchanged_string': '153 verified unchanged', 'manifest_pin_differs': 'reviewed freeze manifest', 'repair_pin_differs': 'reviewed digest of the freeze',
                       'repair_set_extra': 'exactly the repairs of the reviewed freeze', 'repair_set_missing': 'exactly the repairs of the reviewed freeze',
                       'pyvenv_pin_differs': 'pinned pyvenv.cfg and venv launcher', 'launcher_pin_differs': 'pinned pyvenv.cfg and venv launcher'}


@pytest.fixture(scope='module')
def r5_binding_results(batch_dir):
    folder = batch_dir / 'r5'
    base_root = folder / 'Toolchain' / 'Python312'
    base_root.mkdir(parents=True)
    (base_root / 'python.exe').write_bytes(b'MZ fake toolchain python')
    manifests = {case: make_r5_tree(folder / case, base_root, case) for case in R5_BINDING_CASES}
    config_sha = hashlib.sha256(b'{"reference":"135cd9ec stand-in"}').hexdigest()
    # The fixture freeze: its repair digests and venv bytes stand in for the reviewed pins; each case pins its own manifest.
    repair_pins = {relative: hashlib.sha256(('# reviewed ' + relative + '\r\n').encode('ascii')).hexdigest() for relative in REPAIRS}

    def pins_literal(pins):
        return '[ordered]@{' + ';'.join(f"'{k}'='{v}'" for k, v in pins.items()) + '}'
    special = {'manifest_pin_differs': "$script:r5SourceManifestPin=('0'*64)",
               'repair_pin_differs': '$script:r5RepairPins=' + pins_literal(dict(repair_pins, **{REPAIRS[1]: '1' * 64})),
               'repair_set_extra': '$script:r5RepairPins=' + pins_literal(dict(repair_pins, **{'src/cochem_pipeline/extra.py': '1' * 64})),
               'repair_set_missing': '$script:r5RepairPins=' + pins_literal({k: v for k, v in repair_pins.items() if k != REPAIRS[2]}),
               'pyvenv_pin_differs': "$script:r5PyvenvPin=('0'*64)", 'launcher_pin_differs': "$script:r5VenvPythonPin=('0'*64)"}
    lines = [f"$script:r4Root='{ps(FAKE_R4_ROOT)}';$script:configPin='{config_sha}';$script:basePythonRoot='{ps(base_root)}';$script:basePython='{ps(base_root / 'python.exe')}';"
             f"$script:probePythonPin='{sha256_file(base_root / 'python.exe')}';$results=[ordered]@{{}}"]
    for case in R5_BINDING_CASES:
        lines.append(f"$script:r5SourceManifestPin='{manifests[case]}';$script:r5RepairPins={pins_literal(repair_pins)};"
                     f"$script:r5PyvenvPin='{hashlib.sha256(b'home = toolchain' + bytes([13, 10])).hexdigest()}';$script:r5VenvPythonPin='{hashlib.sha256(b'MZ fake venv launcher').hexdigest()}';"
                     + special.get(case, '') + f";$root=Join-Path '{ps(folder)}' '{case}';try{{$b=Assert-R5InstalledBindings $root;$results['{case}']=[ordered]@{{refused=$false;value=$b}}}}"
                     f"catch{{$results['{case}']=[ordered]@{{refused=$true;message=$_.Exception.Message}}}}")
    lines.append('$results|ConvertTo-Json -Compress -Depth 5')
    body = '\n'.join(lines)
    return {'results': run(batch_dir, body), 'folder': folder}


@pytest.mark.parametrize('case', R5_BINDING_CASES)
def test_r5_install_receipt_is_bound_by_content(r5_binding_results, case):
    value = r5_binding_results['results'][case]
    assert value['refused'] == (case != 'valid'), value
    if case in R5_BINDING_MESSAGES:
        assert R5_BINDING_MESSAGES[case] in value['message'], value['message']
    if case == 'valid':
        root = r5_binding_results['folder'] / 'valid'
        binding = value['value']
        assert binding['root'] == str(root) and binding['python'] == str(root / '.venv' / 'Scripts' / 'python.exe') and binding['source_root'] == str(root / '.venv' / 'Lib')
        assert binding['install_after_sha256'] == sha256_file(root / 'install-after.json') and binding['revision_sha256'] == '5' * 64
        assert binding['source_manifest_sha256'] == sha256_file(root / 'source-manifest.json') and binding['reviewed_repairs'] == REPAIRS


def test_r5_root_is_discovered_only_when_exactly_one_installed_r5_root_exists(tmp_path):
    names = {'none': [], 'one': ['Pipeline4.2.7-windows-20261011-r5'], 'two': ['Pipeline4.2.7-windows-20261011-r5', 'Pipeline4.2.7-windows-20261012-r5'],
             'decoys': ['Pipeline4.2.7-windows-20261011-r5', 'Pipeline4.2.7-windows-20261011-r5-old', 'Pipeline4.2.7-windows-20261011-r5x', 'Pipeline4.2.7-windows-20261009-r4']}
    lines = ['$r=[ordered]@{}']
    for case, dirs in names.items():
        base = tmp_path / case
        base.mkdir()
        for name in dirs:
            (base / name).mkdir()
        lines.append(f"$script:base='{ps(base)}';try{{$r['{case}']=Find-R5Root}}catch{{$r['{case}']='REFUSED: '+$_.Exception.Message}}")
    lines.append('$r|ConvertTo-Json -Compress')
    value = run(tmp_path, '\n'.join(lines))
    assert value['one'] == str(tmp_path / 'one' / 'Pipeline4.2.7-windows-20261011-r5')
    assert value['decoys'] == str(tmp_path / 'decoys' / 'Pipeline4.2.7-windows-20261011-r5')
    assert value['none'].startswith('REFUSED') and 'found 0' in value['none'] and value['two'].startswith('REFUSED') and 'found 2' in value['two']


REFERENCE_CONFIG = {'private_root': 'C:\\ProgramData\\CoChemPipeline427\\private', 'workers': {f'slot{i}': {'name': f'CoChem422Worker{i}'} for i in range(1, 7)},
                    'providers': {'claude': {'executable': 'claude.exe', 'model': 'claude-x'}, 'gemini': {'executable': 'agy.exe', 'model': 'gemini-3.1-pro-preview', 'protocol': 'gemini-json',
                                  'integration_hold': {'state': 'verification_pending'}}, 'codex': {'executable': 'codex.exe'}},
                    'routing': {'policy_version': 2, 'tiers': [{'tier': 1, 'targets': ['gemini-3.8-flash']}, {'tier': 7, 'targets': ['gemini-3.1-pro-preview']}]}, 'timeout_seconds': 5.0}
CONFIG_CASES = {'held_bytes': 'GEMINI_HELD_COMMISSIONED_BYTES', 'gemini_contract': 'GEMINI_CONTRACT', 'gemini_contract_reformatted': 'GEMINI_CONTRACT',
                'tier_changed': 'changes more than providers.gemini', 'claude_changed': 'changes more than providers.gemini', 'extra_top_key': 'changes more than providers.gemini',
                'timeout_changed': 'changes more than providers.gemini', 'gemini_removed': 'no providers.gemini object', 'whitespace_only': 'without a providers.gemini change',
                'not_json': 'is not JSON', 'wrong_name': 'must be C:\\Program Files', 'empty': 'requires -Config',
                'commissioning_path': 'GEMINI_HELD_COMMISSIONING_FILE', 'commissioning_path_wrong_sha': 'Source digest changed',
                'commissioning_name_elsewhere': 'or exactly the commissioning copy', 'r4_root_config': 'or exactly the commissioning copy',
                # audit C-F8: the stager's receipt for exactly these bytes, and no held staging record
                'no_staging_receipt': 'has no cochem-config-only-staging/2 staging receipt', 'staging_receipt_wrong_sha': 'has no cochem-config-only-staging/2 staging receipt',
                'staging_receipt_wrong_path': 'has no cochem-config-only-staging/2 staging receipt', 'staging_receipt_wrong_schema': 'has no cochem-config-only-staging/2 staging receipt',
                'staging_receipt_bad_name': 'has no cochem-config-only-staging/2 staging receipt', 'staging_receipt_status_held': 'has no cochem-config-only-staging/2 staging receipt',
                'staging_held_present': 'held staging record', 'held_bytes_without_receipt': 'has no cochem-config-only-staging/2 staging receipt',
                'second_receipt_matches': 'GEMINI_CONTRACT'}
STAGING_RECEIPT_NAME = 'staging-receipt-20261011T101010Z-' + '0123456789abcdef' * 2 + '.json'
STAGING_SECOND_NAME = 'staging-receipt-20261011T111111Z-' + 'abcdef0123456789' * 2 + '.json'
STAGING_HELD_NAME = 'staging-held-20261011T101010Z-' + 'fedcba9876543210' * 2 + '.json'
COMMISSIONING_DIRS = {'commissioning_path': 'WardenCommissioning4.2.7-windows-20261007-r3-v1', 'commissioning_path_wrong_sha': 'WardenCommissioning4.2.7-windows-20261007-r3-v1',
                      'commissioning_name_elsewhere': 'WardenCommissioning4.2.7-windows-20261007-r3-v2'}


@pytest.fixture(scope='module')
def config_results(batch_dir):
    folder = batch_dir / 'config'
    folder.mkdir()
    reference = folder / 'reference.json'
    reference_bytes = json.dumps(REFERENCE_CONFIG, indent=2).encode('utf-8')
    reference.write_bytes(reference_bytes)
    paths = {}
    for case in CONFIG_CASES:
        directory = folder / case / COMMISSIONING_DIRS.get(case, 'WardenConfig4.2.7-windows-20261011-r4-v1' if case == 'wrong_name' else 'WardenConfig4.2.7-windows-20261011-r5-v1')
        directory.mkdir(parents=True)
        candidate = json.loads(json.dumps(REFERENCE_CONFIG))
        data = None
        if case in ('held_bytes', 'wrong_name', 'commissioning_path', 'commissioning_name_elsewhere'):
            data = reference_bytes
        elif case == 'commissioning_path_wrong_sha':
            data = reference_bytes + b'\n'
        elif case in ('gemini_contract', 'gemini_contract_reformatted'):
            candidate['providers']['gemini'] = {'executable': 'agy.exe', 'model': 'gemini-3.1-pro-preview', 'protocol': 'agy-stream-json', 'identity_policy': 'reported-model-equality'}
            data = json.dumps(candidate, indent=(4 if case.endswith('reformatted') else 2)).encode('utf-8')
        elif case == 'tier_changed':
            candidate['providers']['gemini']['protocol'] = 'agy-stream-json'
            candidate['routing']['tiers'][0]['targets'] = ['claude-x']
        elif case == 'claude_changed':
            candidate['providers']['claude']['model'] = 'claude-y'
        elif case == 'extra_top_key':
            candidate['extra'] = 1
        elif case == 'timeout_changed':
            candidate['timeout_seconds'] = 6.0
        elif case == 'gemini_removed':
            candidate['providers'].pop('gemini')
        elif case == 'whitespace_only':
            data = json.dumps(REFERENCE_CONFIG, indent=4).encode('utf-8')
        elif case == 'not_json':
            data = b'{not json'
        elif case == 'held_bytes_without_receipt':
            data = reference_bytes
        if data is None:
            if case in ('no_staging_receipt', 'staging_receipt_wrong_sha', 'staging_receipt_wrong_path', 'staging_receipt_wrong_schema', 'staging_receipt_bad_name',
                        'staging_receipt_status_held', 'staging_held_present', 'second_receipt_matches'):
                candidate['providers']['gemini'] = {'executable': 'agy.exe', 'model': 'gemini-3.1-pro-preview', 'protocol': 'agy-stream-json'}
            data = json.dumps(candidate, indent=2).encode('utf-8')
        (directory / 'pipeline.json').write_bytes(data)
        paths[case] = '' if case == 'empty' else str(directory / 'pipeline.json')
        if case not in COMMISSIONING_DIRS and case not in ('empty', 'no_staging_receipt', 'held_bytes_without_receipt'):
            # The stager's receipt beside the staged bytes (audit C-F8), mutated per case.
            receipt = {'schema': 'cochem-config-only-staging/2', 'status': 'STAGED', 'staged_path': str(directory / 'pipeline.json'), 'staged_sha256': hashlib.sha256(data).hexdigest()}
            receipt.update({'staging_receipt_wrong_sha': {'staged_sha256': '0' * 64}, 'staging_receipt_wrong_path': {'staged_path': str(directory / 'other.json')},
                            'staging_receipt_wrong_schema': {'schema': 'cochem-config-only-staging/1'}, 'staging_receipt_status_held': {'status': 'HELD'},
                            'second_receipt_matches': {'staged_sha256': '0' * 64}}.get(case, {}))
            name = 'staging-receipt-1.json' if case == 'staging_receipt_bad_name' else STAGING_RECEIPT_NAME
            (directory / name).write_text(json.dumps(receipt), encoding='utf-8')
            if case == 'second_receipt_matches':
                (directory / STAGING_SECOND_NAME).write_text(json.dumps(dict(receipt, staged_sha256=hashlib.sha256(data).hexdigest(), status='ALREADY_STAGED_IDENTICAL')), encoding='utf-8')
            if case == 'staging_held_present':
                (directory / STAGING_HELD_NAME).write_text('{}', encoding='utf-8')
    paths['r4_root_config'] = str(reference)
    lines = [f"$script:r4RestoreConfig='{ps(reference)}';$script:configPin='{hashlib.sha256(reference_bytes).hexdigest()}'",
             f"$script:commissioningConfig='{ps(paths['commissioning_path'])}'",
             r"$script:r5ConfigPattern='^.+\\WardenConfig4\.2\.7-windows-[0-9]{8}-r5-v[0-9]{1,3}\\pipeline\.json$'", '$r=[ordered]@{}']
    for case, path in paths.items():
        # The commissioning copy is accepted only at its exact path: each wrong-sha case points the pinned path at its own file.
        pinned = paths['commissioning_path_wrong_sha'] if case == 'commissioning_path_wrong_sha' else paths['commissioning_path']
        lines.append(f"$script:commissioningConfig='{ps(pinned)}';try{{$b=Assert-R5Config '{ps(path)}';$r['{case}']=[ordered]@{{refused=$false;mode=$b.mode;sha=$b.sha256;"
                     f"staging=$(if($b.Contains('staging_receipt_path')){{$b.staging_receipt_path}}else{{$null}});staging_sha=$(if($b.Contains('staging_receipt_sha256')){{$b.staging_receipt_sha256}}else{{$null}})}}}}"
                     f"catch{{$r['{case}']=[ordered]@{{refused=$true;message=$_.Exception.Message}}}}")
    lines.append('$r|ConvertTo-Json -Compress -Depth 4')
    return {'results': run(batch_dir, '\n'.join(lines)), 'paths': paths}


@pytest.mark.parametrize('case', sorted(CONFIG_CASES))
def test_staged_r5_config_is_bound_by_content(config_results, case):
    value = config_results['results'][case]
    expected = CONFIG_CASES[case]
    if expected.startswith('GEMINI_'):
        assert value['refused'] is False and value['mode'] == expected and value['sha'] == sha256_file(Path(config_results['paths'][case]))
        if expected != 'GEMINI_HELD_COMMISSIONING_FILE':
            # The staging receipt that names these bytes is reported (the newest one when several exist).
            directory = Path(config_results['paths'][case]).parent
            name = STAGING_SECOND_NAME if case == 'second_receipt_matches' else STAGING_RECEIPT_NAME
            assert value['staging'] == str(directory / name) and value['staging_sha'] == sha256_file(directory / name)
    else:
        assert value['refused'] is True and expected in value['message'], value


PARSER_CASES = {'ok': ('0', '{"parser_valid":true,"worker_identities":6,"max_shared_slots":4,"knowledge_enabled":true}', None),
                'five_workers': ('0', '{"parser_valid":true,"worker_identities":5,"max_shared_slots":4,"knowledge_enabled":true}', 'six worker identities'),
                'three_slots': ('0', '{"parser_valid":true,"worker_identities":6,"max_shared_slots":3,"knowledge_enabled":true}', 'six worker identities'),
                'knowledge_off': ('0', '{"parser_valid":true,"worker_identities":6,"max_shared_slots":4,"knowledge_enabled":false}', 'six worker identities'),
                'valid_string': ('0', '{"parser_valid":"true","worker_identities":6,"max_shared_slots":4,"knowledge_enabled":true}', 'six worker identities'),
                'exit_1': ('1', '', 'parser failed (exit 1)'), 'not_json': ('0', 'Traceback', 'printed no JSON')}


def test_r5_config_parser_runs_the_r5_interpreter_with_single_quoted_python(tmp_path):
    lines = ['$r=[ordered]@{};$script:calls=@()']
    for case, (code, stdout, _) in PARSER_CASES.items():
        lines.append(f"function Invoke-NativeJudged {{param($Executable,$Arguments)$script:calls+=,@($Executable,$Arguments);[pscustomobject]@{{code={code};stdout='{ps(stdout)}';stderr='boom'}}}}")
        lines.append(f"try{{$null=Invoke-R5ConfigParser 'C:\\r5\\python.exe' 'C:\\cfg\\pipeline.json';$r['{case}']=''}}catch{{$r['{case}']=$_.Exception.Message}}")
    lines.append("$first=$script:calls[0];$r['exe']=$first[0];$r['args']=@($first[1][0..4]+$first[1][6]);$r['code_has_double_quote']=($first[1][5].Contains([string][char]34));$r['code']=$first[1][5]")
    lines.append('$r|ConvertTo-Json -Compress')
    value = run(tmp_path, '\n'.join(lines))
    for case, (_, _, expected) in PARSER_CASES.items():
        assert (value[case] == '') if expected is None else (expected in value[case]), (case, value[case])
    assert value['exe'] == 'C:\\r5\\python.exe' and value['args'] == ['-I', '-B', '-X', 'utf8', '-c', 'C:\\cfg\\pipeline.json']
    assert value['code_has_double_quote'] is False and 'from cochem_pipeline.config import load_config' in value['code']


CLIENT_CASES = {'ok': b'{\n  "port": 47824,\n  "token_file": "C:\\\\Users\\\\ansac\\\\CoChem427\\\\controller.token"\n}\n',
                'bom_ok': b'\xef\xbb\xbf{"port":47824,"token_file":"C:\\\\Users\\\\ansac\\\\CoChem427\\\\controller.token"}',
                'port_other': b'{"port":47825,"token_file":"C:\\\\Users\\\\ansac\\\\CoChem427\\\\controller.token"}',
                'port_string': b'{"port":"47824","token_file":"C:\\\\Users\\\\ansac\\\\CoChem427\\\\controller.token"}',
                'port_missing': b'{"token_file":"C:\\\\Users\\\\ansac\\\\CoChem427\\\\controller.token"}',
                'token_other': b'{"port":47824,"token_file":"C:\\\\Users\\\\ansac\\\\other.token"}', 'not_json': b'port=47824'}


def test_client_config_must_name_the_pinned_port_and_token_and_is_held_open(tmp_path):
    lines = ['$r=[ordered]@{}']
    for case, data in CLIENT_CASES.items():
        path = tmp_path / f'client-{case}.json'
        path.write_bytes(data)
        lines.append(f"$script:clientConfig='{ps(path)}';try{{$c=Assert-ClientConfig;$r['{case}']=[ordered]@{{ok=$true;sha=$c.sha256}}}}catch{{$r['{case}']=[ordered]@{{ok=$false;message=$_.Exception.Message}}}}")
    lines.append(f"$writeDenied=$false;try{{[IO.File]::AppendAllText('{ps(tmp_path / 'client-ok.json')}','x')}}catch{{$writeDenied=$true}};$r['write_denied_while_held']=$writeDenied;$r['held']=$held.Count")
    lines.append('$r|ConvertTo-Json -Compress -Depth 3')
    value = run(tmp_path, '\n'.join(lines))
    assert value['ok']['ok'] is True and value['ok']['sha'] == sha256_file(tmp_path / 'client-ok.json') and value['bom_ok']['ok'] is True
    for case in ('port_other', 'port_string', 'port_missing', 'token_other'):
        assert value[case]['ok'] is False and 'must name port 47824' in value[case]['message'], case
    assert value['not_json']['ok'] is False and 'not JSON' in value['not_json']['message']
    assert value['write_denied_while_held'] is True and value['held'] == len(CLIENT_CASES)


# ----------------------------------------------------------------------------------------------- health, gates, process proof

def test_health_sample_requires_the_system_identity_from_the_target_root(tmp_path):
    good = {'service_identity': 'SYSTEM', 'source_root': R5_ROOT + r'\.venv\Lib', 'pid': 4242, 'instance_id': 'i', 'process_started_at': 1.5, 'active': [], 'quarantined_slots': {}}
    cases = {'ok': (0, json.dumps(good)), 'r4_root_for_r5': (0, json.dumps(dict(good, source_root=R4_ROOT + r'\.venv\Lib'))),
             'not_system': (0, json.dumps(dict(good, service_identity='ansac'))), 'missing_pid': (0, json.dumps({k: v for k, v in good.items() if k != 'pid'})),
             'array': (0, '[1,2]'), 'empty': (0, ''), 'nonzero': (1, json.dumps(good))}
    lines = [f"$script:targetSourceRoot='{ps(R5_ROOT)}\\.venv\\Lib';$r=[ordered]@{{}};$script:calls=@()"]
    for case, (code, stdout) in cases.items():
        lines.append(f"function Invoke-NativeJudged {{param($Executable,$Arguments)$script:calls+=,@($Executable,$Arguments);[pscustomobject]@{{code={code};stdout='{ps(stdout)}';stderr='x'}}}}")
        lines.append(f"$s=Get-HealthSample;$r['{case}']=[ordered]@{{ok=$s.ok;error=$s.error}}")
    lines.append("$r['exe']=$script:calls[0][0];$r['args']=$script:calls[0][1];$r|ConvertTo-Json -Compress -Depth 4")
    value = run(tmp_path, '\n'.join(lines))
    assert value['ok'] == {'ok': True, 'error': ''}
    for case in ('r4_root_for_r5', 'not_system'):
        assert value[case]['ok'] is False and 'unexpected identity or source root' in value[case]['error']
    assert 'health lacks pid' in value['missing_pid']['error'] and 'not a JSON object' in value['array']['error'] and value['empty']['ok'] is False and value['nonzero']['ok'] is False
    assert value['exe'] == R4_PY and value['args'] == ['-I', '-B', '-X', 'utf8', '-m', 'cochem_pipeline', 'health', '--client-config', r'C:\Users\ansac\CoChem427\pipeline-client-r3.json']


HEALTH_FIXTURE = r'''
function New-FixtureHealth {param([string]$Tag)
  $h=[ordered]@{service_identity='SYSTEM';source_root=$script:targetSourceRoot;pid=$(if($Tag -ceq 'B'){4100+$script:healthIndex}else{4242});instance_id=$(if($Tag -ceq 'B'){'id-B'+$script:healthIndex}else{'id-A'});process_started_at=1.5;
     active=@();quarantined_slots=[pscustomobject]@{};routing=[pscustomobject]@{execution_quarantines=@();holds=@();active_reservations=@()};
     knowledge=[pscustomobject]@{ready=$true;authority_matches_capture=$true};components=[pscustomobject]@{warden_controller=[pscustomobject]@{ready=$true;admission_ready=$true}};
     version='4.2.7';admission_capacity=3;trip_errors=[pscustomobject]@{}}
  switch -CaseSensitive ($Tag){
    'K'{$h.knowledge=[pscustomobject]@{ready=$false;authority_matches_capture=$null}}
    'U'{$h.knowledge=[pscustomobject]@{ready=$true;authority_matches_capture=$false}}
    'S'{$h.knowledge=[pscustomobject]@{ready='true';authority_matches_capture=$true}}
    'N'{$h.components=[pscustomobject]@{warden_controller=[pscustomobject]@{ready=$false;admission_ready=$false}}}
    'H'{$h.components=[pscustomobject]@{warden_controller=[pscustomobject]@{ready=$true;admission_ready=$false}}}
    'O'{$h.components=[pscustomobject]@{warden_controller=[pscustomobject]@{ready=$true}}}
    'C'{$h.components=[pscustomobject]@{}}
    'X'{$h.routing=[pscustomobject]@{execution_quarantines=@([pscustomobject]@{job_id='j1'});holds=@();active_reservations=@()}}
    'Y'{$h.routing=[pscustomobject]@{holds=@()}}
    'Q'{$h.quarantined_slots=[pscustomobject]@{slot2='cleanup'}}
    'W'{$h.active=@([pscustomobject]@{job_id='j2';slot='slot1'})}
    'M'{$h.Remove('active')}}
  [pscustomobject]$h}
$script:healthScript=@();$script:healthIndex=0
function Get-HealthSample {
  # Past the end of the script the controller keeps answering like its last sample.
  if($script:healthScript.Count -eq 0){return [pscustomobject]@{ok=$false;error='refused';health=$null}}
  $tag=$script:healthScript[[Math]::Min($script:healthIndex,$script:healthScript.Count-1)];$script:healthIndex++
  if($null -eq $tag){return [pscustomobject]@{ok=$false;error='refused';health=$null}}
  if($tag -ceq 'R'){return [pscustomobject]@{ok=$false;error='health answered with an unexpected identity or source root';health=$null}}
  [pscustomobject]@{ok=$true;error='';health=(New-FixtureHealth $tag)}}
'''
GATE_CASES = {'r5_ok': ('r5', 'A', [], []), 'r4_ok': ('r4', 'A', [], []), 'r4_only_ready': ('r4', 'O', [], []), 'r5_only_ready': ('r5', 'O', [], ['admission_ready']),
              'r5_hysteresis': ('r5', 'H', [], ['admission_ready']), 'r4_hysteresis_ignored': ('r4', 'H', [], []), 'not_ready': ('r5', 'N', [], ['admission_ready']),
              # audit C-F6: r4 records components.warden_controller.ready but never gates on it
              'r4_not_ready': ('r4', 'N', [], []), 'no_components': ('r4', 'C', [], []), 'r5_no_components': ('r5', 'C', [], ['admission_ready']),
              'knowledge': ('r5', 'K', [], ['knowledge']), 'authority': ('r5', 'U', [], ['knowledge']), 'knowledge_string': ('r4', 'S', [], ['knowledge']),
              'execution_quarantine': ('r5', 'X', ['execution quarantine'], []), 'no_execution_list': ('r4', 'Y', ['routing.execution_quarantines'], []),
              'quarantined_slot': ('r5', 'Q', ['quarantined slots: slot2'], []), 'active': ('r4', 'W', ['active job'], []), 'no_active_list': ('r5', 'M', ['no active list'], [])}


def test_post_start_gates_split_hard_failures_from_readiness(tmp_path):
    lines = [HEALTH_FIXTURE, '$r=[ordered]@{}']
    for case, (target, tag, _, _) in GATE_CASES.items():
        lines.append(f"$ctx=New-FixtureContext '{target}';$script:targetSourceRoot=$ctx.source_root;$g=Get-StartGateFailures (New-FixtureHealth '{tag}') $ctx;$r['{case}']=[ordered]@{{hard=@($g.hard);soft=@($g.soft)}}")
    lines.append('$r|ConvertTo-Json -Compress -Depth 4')
    value = run(tmp_path, FIXTURE + '\n'.join(lines))
    for case, (_, _, hard, soft) in GATE_CASES.items():
        got = value[case]
        assert len(got['hard']) == len(hard) and all(any(h in g for g in got['hard']) for h in hard), (case, got)
        assert len(got['soft']) == len(soft) and all(any(s in g for g in got['soft']) for s in soft), (case, got)


NO_LISTENER = ("$e=[Management.Automation.ErrorRecord]::new([Exception]::new('No MSFT_NetTCPConnection objects found'),"
               "'CmdletizationQuery_NotFound,Get-NetTCPConnection','ObjectNotFound',$null);throw $e")
PROOF_CASES = {'r5_ok': None, 'r4_ok': None, 'image_is_venv': 'Toolchain interpreter', 'wrong_command': 'expected r5 daemon command', 'parent_wrong_image': 'venv launcher',
               'parent_wrong_command': 'venv launcher', 'parent_missing': 'venv launcher', 'port_elsewhere': 'owned by pid 99', 'second_listener_elsewhere': 'owned by pid 77',
               'nothing_listens': 'Nothing listens', 'port_query_error': 'could not be established', 'not_system': 'does not run as SYSTEM', 'pid_missing': 'does not exist'}


def test_process_proof_ties_the_pid_to_the_toolchain_image_the_target_launcher_the_socket_and_system(tmp_path):
    lines = [r'''$r=[ordered]@{}
      function Invoke-Proof {param($Name,$Target,$Image,$Command,$ParentImage,$ParentCommand,$Listeners,$User,[switch]$NoParent,[switch]$NoProcess)
        $script:p=@{Image=$Image;Command=$Command;ParentImage=$ParentImage;ParentCommand=$ParentCommand;Listeners=$Listeners;User=$User;NoParent=[bool]$NoParent;NoProcess=[bool]$NoProcess}
        $ctx=New-FixtureContext $Target
        try{$proof=Get-TargetProcessProof 4242 $ctx;$script:r[$Name]=[ordered]@{refused=$false;proof=$proof}}catch{$script:r[$Name]=[ordered]@{refused=$true;message=$_.Exception.Message}}}
      $script:r=$r
      function Get-CimInstance {param($ClassName,$Filter,$ErrorAction)
        if($Filter -ceq 'ProcessId = 4242'){if($script:p.NoProcess){return $null};return [pscustomobject]@{ProcessId=4242;ParentProcessId=5320;ExecutablePath=$script:p.Image;CommandLine=$script:p.Command;CreationDate=[DateTime]'2026-10-11T12:00:00'}}
        if($Filter -ceq 'ProcessId = 5320'){if($script:p.NoParent){return $null};return [pscustomobject]@{ProcessId=5320;ParentProcessId=1;ExecutablePath=$script:p.ParentImage;CommandLine=$script:p.ParentCommand;CreationDate=[DateTime]'2026-10-11T11:59:59'}}
        $null}
      function Get-NetTCPConnection {param($LocalPort,$State,$ErrorAction)& $script:p.Listeners}
      function Invoke-CimMethod {param($InputObject,$MethodName,$ErrorAction)[pscustomobject]@{ReturnValue=0;User=$script:p.User}}
      $r5=New-FixtureContext 'r5';$r4=New-FixtureContext 'r4'
      $r5Child='"'+$script:basePython+'" '+$r5.action.arguments;$r5Parent='"'+$r5.action.execute+'" '+$r5.action.arguments
      $r4Child='"'+$script:basePython+'" '+$r4.action.arguments;$r4Parent='"'+$r4.action.execute+'" '+$r4.action.arguments
      $own={@([pscustomobject]@{LocalPort=47824;OwningProcess=4242})}
      Invoke-Proof 'r5_ok' 'r5' $script:basePython $r5Child $r5.action.execute $r5Parent $own 'SYSTEM'
      Invoke-Proof 'r4_ok' 'r4' $script:basePython $r4Child $r4.action.execute $r4Parent $own 'SYSTEM'
      Invoke-Proof 'image_is_venv' 'r5' $r5.action.execute $r5Child $r5.action.execute $r5Parent $own 'SYSTEM'
      Invoke-Proof 'wrong_command' 'r5' $script:basePython $r4Child $r5.action.execute $r5Parent $own 'SYSTEM'
      Invoke-Proof 'parent_wrong_image' 'r5' $script:basePython $r5Child $r4.action.execute $r5Parent $own 'SYSTEM'
      Invoke-Proof 'parent_wrong_command' 'r5' $script:basePython $r5Child $r5.action.execute $r4Parent $own 'SYSTEM'
      Invoke-Proof 'parent_missing' 'r5' $script:basePython $r5Child $r5.action.execute $r5Parent $own 'SYSTEM' -NoParent
      Invoke-Proof 'port_elsewhere' 'r5' $script:basePython $r5Child $r5.action.execute $r5Parent {@([pscustomobject]@{LocalPort=47824;OwningProcess=99})} 'SYSTEM'
      Invoke-Proof 'second_listener_elsewhere' 'r5' $script:basePython $r5Child $r5.action.execute $r5Parent {@([pscustomobject]@{LocalPort=47824;OwningProcess=4242},[pscustomobject]@{LocalPort=47824;OwningProcess=77})} 'SYSTEM'
      Invoke-Proof 'nothing_listens' 'r5' $script:basePython $r5Child $r5.action.execute $r5Parent {__NOLISTENER__} 'SYSTEM'
      Invoke-Proof 'port_query_error' 'r5' $script:basePython $r5Child $r5.action.execute $r5Parent {throw 'provider failure'} 'SYSTEM'
      Invoke-Proof 'not_system' 'r5' $script:basePython $r5Child $r5.action.execute $r5Parent $own 'ansac'
      Invoke-Proof 'pid_missing' 'r5' $script:basePython $r5Child $r5.action.execute $r5Parent $own 'SYSTEM' -NoProcess
      $r|ConvertTo-Json -Compress -Depth 5
    '''.replace('__NOLISTENER__', NO_LISTENER)]
    value = run(tmp_path, '\n'.join(lines))
    for case, expected in PROOF_CASES.items():
        got = value[case]
        assert got['refused'] == (expected is not None), (case, got)
        if expected:
            assert expected in got['message'], (case, got['message'])
    proof = value['r5_ok']['proof']
    assert proof['pid'] == 4242 and proof['image'] == BASE_PY and proof['parent_image'] == R5_PY and proof['owner'] == 'SYSTEM' and proof['port_owner_verified'] is True
    assert proof['creation_utc'].startswith('2026-10-11T') and proof['parent_creation_utc'].startswith('2026-10-11T') and proof['parent_pid'] == 5320


@pytest.mark.parametrize('case', ['free', 'listening', 'controller', 'r5_unclassified', 'r5_client', 'observer', 'query_error', 'uninspectable_elevated'])
def test_controller_presence_counts_r5_runtime_processes_and_fails_closed(tmp_path, case):
    r5_cmd = f'"{R5_PY}" -I -B -m cochem_pipeline health --client-config c.json'
    procs = {'controller': "@([pscustomobject]@{ProcessId=7;ParentProcessId=1;Name='python.exe';ExecutablePath='C:\\elsewhere\\python.exe';CommandLine='python -m cochem_pipeline daemon --config x'})",
             'r5_unclassified': f"@([pscustomobject]@{{ProcessId=9;ParentProcessId=1;Name='python.exe';ExecutablePath='{R5_PY}';CommandLine='\"{R5_PY}\" -c pass'}})",
             'r5_client': f"@([pscustomobject]@{{ProcessId=8;ParentProcessId=1;Name='python.exe';ExecutablePath='{R5_PY}';CommandLine='{ps(r5_cmd)}'}})",
             'observer': (f"@([pscustomobject]@{{ProcessId=9472;ParentProcessId=1;Name='python.exe';ExecutablePath='{BASE_PY}';"
                          "CommandLine='\"C:\\Program Files\\CoChem\\ResourceObservation4.2.7-windows-20261008-r3-v4\\package\\observe_resources.py\" --run-observer --x'})"),
             'uninspectable_elevated': "@([pscustomobject]@{ProcessId=10;ParentProcessId=1;Name='python.exe';ExecutablePath=$null;CommandLine=$null})"}.get(case, '@()')
    net = {'listening': "@([pscustomobject]@{LocalPort=47824;OwningProcess=1})", 'query_error': "throw 'provider failure'"}.get(case, NO_LISTENER)
    body = (f"$script:admin=$true;$script:runtimeRoots=@($script:runtimeRoots)+@($script:fixtureR5Root);function Get-CimInstance {{param($ClassName,$Filter,$ErrorAction){procs}}};"
            f"function Get-NetTCPConnection {{param($LocalPort,$State,$ErrorAction){net}}};" + r'''
      $refused=$false;$alive=$null;$p=$null;try{$p=Get-ControllerPresence;$alive=Test-ControllerAlive $p}catch{$refused=$true}
      [ordered]@{refused=$refused;alive=$alive;counts=$(if($p){@(@($p.controller_processes).Count,@($p.observer_processes).Count,@($p.client_processes).Count,@($p.unclassified_runtime_processes).Count,$p.uninspectable_python_processes)}else{@()})}|ConvertTo-Json -Compress
    ''')
    value = run(tmp_path, body)
    if case == 'query_error':
        assert value['refused'] is True
        return
    assert value['alive'] == (case in ('listening', 'controller', 'r5_unclassified', 'uninspectable_elevated'))
    assert value['counts'] == {'free': [0, 0, 0, 0, 0], 'listening': [0, 0, 0, 0, 0], 'controller': [1, 0, 0, 0, 0], 'r5_unclassified': [0, 0, 0, 1, 0],
                               'r5_client': [0, 0, 1, 0, 0], 'observer': [0, 1, 0, 0, 0], 'uninspectable_elevated': [0, 0, 0, 0, 1]}[case]


BRIDGE_CONFIG = r'C:\Users\ansac\CoChem427\bridge.local.json'
R3_PY = R3_ROOT + r'\.venv\Scripts\python.exe'


def bridge_command(image: str, provider: str = 'codex', config: str = BRIDGE_CONFIG, head: str = '-m cochem_mcp') -> str:
    return f'"{image}" {head} --provider {provider} --config {config}'


# The Antigravity bridge entries of the 2026-10-11 17:22 host (DIAG-PROCESSES): '<r4 venv or Toolchain python> -m cochem_mcp
# --provider codex|claude --config C:\Users\ansac\CoChem427\bridge.local.json', owner ansac, no listener, no daemon. A pure
# client of the Warden job board, so a client - only in exactly that form and only from a runtime image; every near miss
# stays an unclassified runtime process (fail closed). name: (image, command line, class: client | unclassified | None).
BRIDGE_PRESENCE_CASES = {
    'r4_venv_codex': (R4_PY, bridge_command(R4_PY), 'client'),
    'r4_venv_claude': (R4_PY, bridge_command(R4_PY, 'claude'), 'client'),
    'toolchain_codex': (BASE_PY, bridge_command(BASE_PY), 'client'),
    'toolchain_claude': (BASE_PY, bridge_command(BASE_PY, 'claude'), 'client'),
    'r5_venv_claude': (R5_PY, bridge_command(R5_PY, 'claude'), 'client'),
    'r3_venv_codex': (R3_PY, bridge_command(R3_PY), 'client'),
    'health_suffix': (R4_PY, bridge_command(R4_PY) + ' --health', 'unclassified'),
    'extra_argument': (R4_PY, bridge_command(R4_PY) + ' --verbose', 'unclassified'),
    'trailing_space': (R4_PY, bridge_command(R4_PY) + ' ', 'unclassified'),
    'other_config': (R4_PY, bridge_command(R4_PY, config=r'C:\Users\ansac\CoChem427\other.local.json'), 'unclassified'),
    'config_other_case': (R4_PY, bridge_command(R4_PY, config=r'c:\users\ansac\CoChem427\bridge.local.json'), 'unclassified'),
    'config_other_user': (R4_PY, bridge_command(R4_PY, config=r'C:\Users\other\CoChem427\bridge.local.json'), 'unclassified'),
    'provider_gemini': (R4_PY, bridge_command(R4_PY, 'gemini'), 'unclassified'),
    'provider_upper': (R4_PY, bridge_command(R4_PY, 'Codex'), 'unclassified'),
    'isolated_flags': (R4_PY, bridge_command(R4_PY, head='-I -B -m cochem_mcp'), 'unclassified'),
    'server_module': (R4_PY, bridge_command(R4_PY, head='-m cochem_mcp.server'), 'unclassified'),
    'other_module': (R4_PY, bridge_command(R4_PY, head='-m cochem_mcpx'), 'unclassified'),
    'unquoted_image': (R4_PY, bridge_command(R4_PY)[1:].replace('" ', ' ', 1), 'unclassified'),
    'pythonw_image': (R4_PY, bridge_command(R4_PY[:-len('python.exe')] + 'pythonw.exe'), 'unclassified'),
    'chained_command': (R4_PY, bridge_command(R4_PY) + ' & "' + R4_PY + '" -c pass', 'unclassified'),
    'daemon_is_still_a_controller': (R4_PY, f'"{R4_PY}" -I -B -m cochem_pipeline daemon --config x --provider codex --config {BRIDGE_CONFIG}', 'controller'),
    'unrooted_image': (r'C:\elsewhere\python.exe', bridge_command(r'C:\elsewhere\python.exe'), None),
}


def test_controller_presence_classifies_the_antigravity_bridge_as_a_client_and_fails_closed_on_near_misses(tmp_path):
    cases = [{'name': name, 'path': image, 'command': command} for name, (image, command, _) in BRIDGE_PRESENCE_CASES.items()]
    body = ("$script:admin=$false;$script:runtimeRoots=@($script:runtimeRoots)+@($script:fixtureR5Root)\n"
            f"function Get-NetTCPConnection {{param($LocalPort,$State,$ErrorAction){NO_LISTENER}}}\n"
            "function Get-CimInstance {param($ClassName,$Filter,$ErrorAction)$script:fixtureProcs}\n"
            f"$cases='{ps(json.dumps(cases))}'|ConvertFrom-Json\n" + r'''
      $r=[ordered]@{}
      foreach($case in $cases){
        $script:fixtureProcs=@([pscustomobject]@{ProcessId=4242;ParentProcessId=29188;Name='python.exe';ExecutablePath=$case.path;CommandLine=$case.command})
        $p=Get-ControllerPresence
        $r[$case.name]=[ordered]@{alive=(Test-ControllerAlive $p);counts=@(@($p.controller_processes).Count,@($p.observer_processes).Count,@($p.client_processes).Count,@($p.unclassified_runtime_processes).Count,$p.uninspectable_python_processes)}}
      $r|ConvertTo-Json -Compress -Depth 4
    ''')
    value = run(tmp_path, body)
    expected_counts = {'client': [0, 0, 1, 0, 0], 'unclassified': [0, 0, 0, 1, 0], 'controller': [1, 0, 0, 0, 0], None: [0, 0, 0, 0, 0]}
    for name, (_, _, kind) in BRIDGE_PRESENCE_CASES.items():
        got = value[name]
        assert got['counts'] == expected_counts[kind], (name, got)
        assert got['alive'] is (kind in ('unclassified', 'controller')), (name, got)


@pytest.mark.parametrize('case', ['clean', 'worker', 'opaque_elevated', 'exited_during_sweep'])
def test_worker_scan_reports_workers_and_uninspectable_processes(tmp_path, case):
    owner = {'clean': "[pscustomobject]@{ReturnValue=0;User='ansac'}", 'worker': "[pscustomobject]@{ReturnValue=0;User='CoChem422Worker3'}",
             'opaque_elevated': "[pscustomobject]@{ReturnValue=2;User=$null}", 'exited_during_sweep': "throw 'gone'"}[case]
    requery = '$null' if case == 'exited_during_sweep' else '[pscustomobject]@{ProcessId=4}'
    body = (f"$script:admin=$true;function Get-Process {{param([switch]$IncludeUserName,$ErrorAction)@()}};"
            f"function Get-CimInstance {{param($ClassName,$Filter,$ErrorAction)if($Filter){{return {requery}}};@([pscustomobject]@{{ProcessId=4;Name='x';ExecutablePath='C:\\x\\claude.exe'}})}};"
            f"function Invoke-CimMethod {{param($InputObject,$MethodName,$ErrorAction){owner}}};" + r'''
      $w=Get-WorkerProcesses;$refused=$false;$message='';try{Assert-NoWorkers $w ' here'}catch{$refused=$true;$message=$_.Exception.Message}
      [ordered]@{workers=@($w.workers).Count;uninspectable=@($w.uninspectable_processes).Count;exited=$w.exited_during_sweep;refused=$refused;message=$message}|ConvertTo-Json -Compress
    ''')
    value = run(tmp_path, body)
    assert (value['workers'], value['uninspectable'], value['exited'], value['refused']) == {
        'clean': (0, 0, 0, False), 'worker': (1, 0, 0, True), 'opaque_elevated': (0, 1, 0, True), 'exited_during_sweep': (0, 0, 1, False)}[case]


def test_native_commands_are_judged_by_exit_code_not_stderr(tmp_path):
    fixture = tmp_path / 'native.py'
    fixture.write_text("import sys\nmode=sys.argv[1]\nif mode=='err':\n    sys.stderr.write('warn');print('out');sys.exit(0)\nif mode=='fail':\n    sys.stderr.write('boom');sys.exit(3)\nprint('{\"ok\":1}')\n", encoding='utf-8')
    python, script, absent = ps(TEST_PY), ps(fixture), ps(tmp_path / 'absent.exe')
    value = run(tmp_path, r'''
      $r=[ordered]@{}
      foreach($mode in @('err','fail','ok')){$x=Invoke-NativeJudged '__PY__' @('-I','-B','-X','utf8','__SCRIPTFILE__',$mode);$r[$mode]=[ordered]@{code=$x.code;stdout=$x.stdout;stderr=$x.stderr}}
      try{$null=Invoke-NativeJudged '__ABSENT__' @();$r['missing']='ran'}catch{$r['missing']=$_.Exception.Message}
      $r['preference']=[string]$ErrorActionPreference;$r|ConvertTo-Json -Compress -Depth 4
    '''.replace('__PY__', python).replace('__SCRIPTFILE__', script).replace('__ABSENT__', absent))
    assert value['err'] == {'code': 0, 'stdout': 'out', 'stderr': 'warn'} and value['fail']['code'] == 3 and 'boom' in value['fail']['stderr']
    assert json.loads(value['ok']['stdout']) == {'ok': 1} and 'missing' in value['missing'] and value['preference'] == 'Stop'


@pytest.mark.parametrize('case', ['free', 'held'])
def test_loopback_probe_binds_exclusively_on_an_ephemeral_port(tmp_path, case):
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(('127.0.0.1', 0))
    port = holder.getsockname()[1]
    if case == 'held':
        holder.listen(1)
    else:
        holder.close()
    try:
        value = run(tmp_path, f"$script:port={port};$script:probePython='{ps(TEST_PY)}';$script:probePythonPin='';$free=Test-LoopbackFree;[ordered]@{{free=$free;reads=@($script:readControls).Count}}|ConvertTo-Json -Compress")
    finally:
        holder.close()
    assert port != 47824 and value == {'free': case == 'free', 'reads': 1}


# ----------------------------------------------------------------------------------------------- backup

def make_db(path: Path, rows=('a', 'b', 'c')) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    try:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('create table jobs(id integer primary key, name text)')
        connection.executemany('insert into jobs(name) values (?)', [(row,) for row in rows])
        connection.commit()
    finally:
        connection.close()


ROBOCOPY_STUB = r'''
$realNative=${function:Invoke-NativeJudged};$script:robocopyCalls=@()
function Invoke-NativeJudged {param([string]$Executable,[string[]]$Arguments)
  if($Executable -like '*robocopy.exe'){
    $script:robocopyCalls+=,@($Arguments)
    if($script:robocopyCode -notin @(0,1)){return [pscustomobject]@{code=$script:robocopyCode;stdout='ERROR 5 (0x00000005) Access is denied.';stderr=''}}
    if($Arguments -notcontains '/L'){
      $source=$Arguments[0];$destination=$Arguments[1]
      foreach($file in @(Get-ChildItem -LiteralPath $source -Recurse -File -Force|Where-Object {$_.Name -like '*.db' -or $_.Name -like '*.db-wal' -or $_.Name -like '*.db-journal'})){
        $relative=$file.FullName.Substring($source.Length).TrimStart('\');$target=Join-Path $destination $relative
        $null=[IO.Directory]::CreateDirectory((Split-Path -Parent $target));[IO.File]::Copy($file.FullName,$target)
        if($script:corruptWitness -and $destination -like '*-witness'){[IO.File]::AppendAllText($target,'x')}}}
    return [pscustomobject]@{code=1;stdout='';stderr=''}}
  if($null -ne $script:helperOverride){return $script:helperOverride}
  & $realNative $Executable $Arguments}
$script:robocopyCode=1;$script:corruptWitness=$false;$script:helperOverride=$null
function Copy-VerifiedPayload {param($File)if((Get-FileHash -LiteralPath $File.source -Algorithm SHA256).Hash.ToLowerInvariant() -cne $File.sha256){throw 'pin'};[IO.File]::Copy($File.source,$File.destination)}
function New-PrivateDirectory {param($Path)if(Test-Path -LiteralPath $Path){throw 'exists'};$null=[IO.Directory]::CreateDirectory($Path)}
function Assert-PrivateAcl {param($Path)$script:aclChecks++};$script:aclChecks=0
'''


@pytest.mark.parametrize('case', ['listable', 'refused'])
def test_backup_rights_probe_lists_with_backup_semantics_and_creates_nothing(tmp_path, case):
    target = tmp_path / 'root'
    value = run(tmp_path, ROBOCOPY_STUB + f"$script:targetRoot='{ps(target)}';$script:privateRoot='{ps(tmp_path / 'private')}';$script:robocopyCode={1 if case == 'listable' else 16};" + r'''
      $refused=$false;$message='';try{$null=Test-BackupCopyRights}catch{$refused=$true;$message=$_.Exception.Message}
      [ordered]@{refused=$refused;message=$message;args=@($script:robocopyCalls[0]);root=(Test-Path -LiteralPath $script:targetRoot)}|ConvertTo-Json -Compress
    ''')
    assert value['root'] is False and '/B' in value['args'] and '/L' in value['args'] and value['args'][0] == str(tmp_path / 'private')
    assert value['args'][1] == str(target / 'state-backup')
    assert value['refused'] is (case == 'refused')
    if case == 'refused':
        assert 'robocopy exit 16' in value['message'] and 'whoami /priv' in value['message']


@pytest.mark.parametrize('case', ['success', 'witness_differs', 'robocopy_fails', 'helper_fails', 'empty_report', 'nothing_copied'])
def test_double_backup_is_verified_by_the_pinned_helper_and_fails_closed(tmp_path, case):
    private = tmp_path / 'private'
    private.mkdir()
    if case != 'nothing_copied':
        make_db(private / 'job_board.db')
        make_db(private / 'containers' / 'containers.db')
    (private / 'queue-old').mkdir()
    (private / 'queue-old' / 'launch.log').write_text('not a database', encoding='utf-8')
    before = {str(p.relative_to(private)): sha256_file(p) for p in private.rglob('*') if p.is_file()}
    target = tmp_path / 'root'
    (target / 'state-backup').mkdir(parents=True)
    setup = {'witness_differs': '$script:corruptWitness=$true;', 'robocopy_fails': '$script:robocopyCode=16;',
             'helper_fails': "$script:helperOverride=[pscustomobject]@{code=1;stdout='';stderr='INTEGRITY_FAILED:job_board.db'};",
             'empty_report': "$script:helperOverride=[pscustomobject]@{code=0;stdout='';stderr=''};"}.get(case, '')
    value = run(tmp_path, ROBOCOPY_STUB + f"$script:targetRoot='{ps(target)}';$script:privateRoot='{ps(private)}';$script:r4Python='{ps(TEST_PY)}';$script:backupHelper='{ps(HELPER)}';{setup}" + r'''
      $refused=$false;$message='';$report=$null;try{$report=Backup-PrivateDatabases (Join-Path $script:targetRoot 'state-backup')}catch{$refused=$true;$message=$_.Exception.Message}
      $schema=$null;$raw=@();$flags=@();if($report){$schema=$report.verification.schema;$raw=@($report.raw_copies_sha256.Keys|Sort-Object);$flags=@($report.copy_flags)}
      [ordered]@{refused=$refused;message=$message;schema=$schema;raw=$raw;flags=$flags;acl=$script:aclChecks;copies=@($script:robocopyCalls).Count;helper=(Test-Path (Join-Path $script:targetRoot 'backup-private-databases-r4.py'))}|ConvertTo-Json -Compress -Depth 4
    ''')
    assert {str(p.relative_to(private)): sha256_file(p) for p in private.rglob('*') if p.is_file()} == before, 'sources are never opened for writing'
    if case == 'success':
        assert value['refused'] is False and value['schema'] == 'cochem-private-database-backup/3' and value['copies'] == 2 and value['helper'] is True
        assert value['raw'] == ['containers\\containers.db', 'job_board.db'] and value['flags'] == ['/B'] and value['acl'] >= 6
        assert (target / 'state-backup-witness' / 'job_board.db').read_bytes() == (private / 'job_board.db').read_bytes()
        assert (target / 'state-backup' / 'verification.json').exists()
        return
    assert value['refused'] is True
    assert {'witness_differs': 'differ between passes', 'robocopy_fails': 'robocopy exit 16', 'helper_fails': 'INTEGRITY_FAILED', 'empty_report': 'printed no report',
            'nothing_copied': 'No private database was copied'}[case] in value['message'], value['message']


@pytest.mark.parametrize('case', ['verified', 'required_store_missing'])
def test_pinned_backup_helper_verifies_copies_only(tmp_path, case):
    destination = tmp_path / 'state-backup'
    destination.mkdir()
    make_db(destination / ('job_board.db' if case == 'verified' else 'other.db'))
    result = subprocess.run([TEST_PY, '-I', '-B', '-X', 'utf8', str(HELPER), str(destination)], capture_output=True, text=True, timeout=60)
    if case == 'verified':
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report['schema'] == 'cochem-private-database-backup/3' and report['sources_opened'] is False and report['databases'][0]['integrity'] == 'ok'
    else:
        assert result.returncode != 0 and 'REQUIRED_STORE_MISSING:job_board.db' in result.stderr


# ----------------------------------------------------------------------------------------------- the mutation path

R5_CFG_V2 = R5_CFG.replace('-r5-v1', '-r5-v2')
SRC_R5 = "$script:SourceAttempt='v1';$script:StopAttempt='v1';"
# Audit C-F2: the logon trigger user is read back as a SID that resolves to the owner (deterministic stub).
SID_STUB = ("function Get-AccountSid {param([string]$Name)if($Name -cin @('AETHERDESK\\ansac','S-1-5-21-9-9-9-1001')){return 'S-1-5-21-9-9-9-1001'};"
            "if($Name -ceq 'S-1-5-21-1-2-3-1001'){return $Name};$null};")
MUTATION_CASES = {
    # success: (target, live overrides, setup, lineage writer, source_state, enabled_before, config)
    'r5_from_r4v1_enabled': ('r5', '@{}', '', '', 'r4-v1', True, R5_CFG),
    'r5_from_r4v1_disabled': ('r5', '@{Enabled=$false;State=1}', '', '', 'r4-v1', False, R5_CFG),
    'r4_from_r4v1': ('r4', '@{}', '', '', 'r4-v1', True, R5_CFG),
    'r4_from_r5_receipt': ('r4', '(Get-R5LiveOverrides)', SRC_R5, 'Write-FixtureR5Source;', 'r5-receipt', False, R5_CFG),
    'r5_gemini_fallback_from_r5_receipt': ('r5', '(Get-R5LiveOverrides)', "$script:SourceAttempt='v1';$script:StopAttempt='v2';$script:Attempt='v2';",
                                           'Write-FixtureR5Source;', 'r5-receipt', False, COMMISSIONING_CONFIG),
    'r4_restore_before_run_from_r5_retarget': ('r4', '(Get-R5LiveOverrides)', "$script:SourceAttempt='v1';", 'Write-FixtureR5NeverStarted;', 'r5-retarget-receipt', False, R5_CFG),
    'r5_retry_after_held_before_run': ('r5', '(Get-R5LiveOverrides)', "$script:SourceAttempt='v1';$script:Attempt='v2';", 'Write-FixtureR5NeverStarted -HeldBeforeRun;',
                                       'r5-retarget-receipt', False, COMMISSIONING_CONFIG),
    'r5_from_r4_restore_receipt': ('r5', '(Get-R4RestoreLiveOverrides)', "$script:SourceAttempt='v1';$script:StopAttempt='v2';", 'Write-FixtureR4RestoreSource;',
                                   'r4-restore-receipt', False, R5_CFG_V2),
    'r4_from_r4_restore_receipt': ('r4', '(Get-R4RestoreLiveOverrides)', "$script:SourceAttempt='v1';$script:StopAttempt='v1';$script:Attempt='v2';", 'Write-FixtureR4RestoreSource;',
                                   'r4-restore-receipt', False, R5_CFG),
    # audit C-F1(b): an interrupted, crashed or post-gate-held start recovered through stop-warden-r5 -RecoverInterruptedStart
    'r4_from_r5_interrupted_start': ('r4', '(Get-R5LiveOverrides)', SRC_R5, "Write-FixtureHeldStart 'r5' 'interrupted' -TriggerEnabled $true;", 'r5-start-held', False, R5_CFG),
    'r5_from_r5_crashed_start': ('r5', '(Get-R5LiveOverrides)', SRC_R5 + "$script:Attempt='v2';", "Write-FixtureHeldStart 'r5' 'crashed';", 'r5-start-held', False, R5_CFG_V2),
    'r5_from_r4_restore_held_after_gate': ('r5', '(Get-R4RestoreLiveOverrides)', SRC_R5, "Write-FixtureHeldStart 'r4' 'gate';", 'r4-restore-start-held', False, R5_CFG),
    # re-audit R-F1: the likeliest S11 failure (knowledge not ready, quarantines) is held after Run before the gate, and recoverable
    'r4_from_r5_held_before_gate': ('r4', '(Get-R5LiveOverrides)', SRC_R5, "Write-FixtureHeldStart 'r5' 'before_gate';", 'r5-start-held', False, R5_CFG),
    # audit C-F1(b) crash window and C-F2: an update held at its readback (or interrupted before its receipt) is restored to r4
    'r4_from_r5_retarget_held_readback': ('r4', "(Merge-Hash (Get-R5LiveOverrides) @{Triggers=@(New-FixtureTrigger 9 'S-1-5-21-1-2-3-1001' 'PT1M' $false)})",
                                          "$script:SourceAttempt='v1';$script:Attempt='v2';", "$null=Write-FixtureRetargetHeld 'r5' 'readback';", 'r5-retarget-held', False, R5_CFG),
    'r4_from_r5_retarget_interrupted': ('r4', '(Get-R5LiveOverrides)', "$script:SourceAttempt='v1';$script:Attempt='v2';", "$null=Write-FixtureRetargetHeld 'r5' 'none';",
                                        'r5-retarget-held', False, R5_CFG),
    # audit C-F3: an r4 restore retargeted but never started is a source of its own
    'r5_from_r4_restore_never_started': ('r5', '(Get-R4RestoreLiveOverrides)', "$script:SourceAttempt='v1';", "Write-FixtureNeverStarted 'r4';", 'r4-restore-retarget-receipt', False, R5_CFG_V2),
    # audit C-F2: the trigger user read back as the owner's SID is the same user
    'trigger_user_read_back_as_sid': ('r5', "@{TriggerUserAfterRegister='S-1-5-21-9-9-9-1001'}", SID_STUB, '', 'r4-v1', True, R5_CFG),
    # refused or held: (target, live overrides, setup, lineage writer)
    'controller_appears_before_mutation': ('r5', '@{}', '$script:fixtureAliveAt=@(2);', ''),
    'port_busy_before_mutation': ('r4', '@{}', '$script:loopbackBusyAt=@(2);', ''),
    'task_changes_during_preparation': ('r5', '@{}', "function Backup-PrivateDatabases {param($Destination)$script:backups++;$script:xmlExtra='<Priority>4</Priority>';[ordered]@{verification=[ordered]@{schema='cochem-private-database-backup/3'}}};", ''),
    'backup_mismatch': ('r5', '@{}', '$script:backupFails=$true;', ''),
    'register_does_not_apply': ('r5', '@{RegisterApplies=$false}', '', ''),
    'readback_denied': ('r4', '@{DenyAfterRegister=$true}', '', ''),
    'trigger_user_rewritten': ('r5', "@{TriggerUserAfterRegister='S-1-5-21-1-2-3-1001'}", SID_STUB, ''),
    'xml_outside_changed': ('r5', "@{ExtraAfterRegister='<Priority>4</Priority>'}", '', ''),
    'register_leaves_enabled': ('r4', '@{RegisterIgnoresEnabled=$true}', '', ''),
    'receipt_collision': ('r5', '@{}', "function New-ProtectedDirectory {param($Path)$null=[IO.Directory]::CreateDirectory($Path);[IO.File]::WriteAllText((Join-Path $Path 'retarget-receipt.json'),'PRE')};", ''),
    'root_fails_after_create': ('r5', '@{}', '$script:rootFailsAfterCreate=$true;', ''),
    'root_exists': ('r5', '@{}', '$null=[IO.Directory]::CreateDirectory($script:targetRoot);', ''),
    'queue_exists': ('r4', '@{}', '$null=[IO.Directory]::CreateDirectory($script:queueRestart);', ''),
    'queue_probe_refused': ('r4', '@{}', "function Test-Path {param($LiteralPath,$Path,$PathType,$ErrorAction)if($LiteralPath -eq $script:queueRestart){throw [UnauthorizedAccessException]::new('Access is denied')};Microsoft.PowerShell.Management\\Test-Path @PSBoundParameters};", ''),
    'rights_probe_fails': ('r5', '@{}', '$script:rightsFail=$true;', ''),
    'other_daemon_active': ('r5', '@{}', '$script:otherActive=$true;', ''),
    'worker_alive': ('r5', '@{}', "$script:workerFixture=[ordered]@{workers=@(@{pid=5;user='CoChem422Worker1'});uninspectable_processes=@();exited_during_sweep=0;authoritative=$true};", ''),
    'controller_alive_at_entry': ('r5', '@{}', '$script:fixtureAliveAt=@(1);', ''),
    'running_instance': ('r5', '@{State=4;Instances=1}', '', ''),
    'r5_source_without_attempts': ('r4', '(Get-R5LiveOverrides)', '', ''),
    'r4_restore_source_without_stop': ('r5', '(Get-R4RestoreLiveOverrides)', "$script:SourceAttempt='v1';", 'Write-FixtureR4RestoreSource;'),
    'r5_retarget_source_with_start_receipt': ('r4', '(Get-R5LiveOverrides)', "$script:SourceAttempt='v1';", 'Write-FixtureR5NeverStarted -StartReceipt;'),
    'r5_retarget_held_to_r5': ('r5', '(Get-R5LiveOverrides)', "$script:SourceAttempt='v1';$script:Attempt='v2';", "$null=Write-FixtureRetargetHeld 'r5' 'readback';"),
    'r5_before_run_held_start_with_stop': ('r4', '(Get-R5LiveOverrides)', SRC_R5, "Write-FixtureHeldStart 'r5' 'before_run';"),
}
NOTHING_CONSUMED = {'root_exists': 'already exists', 'queue_exists': 'queue-observation directory already exists', 'queue_probe_refused': 'queue-observation directory already exists',
                    'rights_probe_fails': 'Backup and Restore Files user rights', 'other_daemon_active': 'must remain stopped and disabled', 'worker_alive': 'Slot worker processes are alive',
                    'controller_alive_at_entry': 'no retarget while a controller', 'running_instance': 'running or queued', 'r5_source_without_attempts': 'needs -SourceAttempt',
                    'r4_restore_source_without_stop': 'holds a start receipt', 'r5_retarget_source_with_start_receipt': 'holds a start receipt',
                    'r5_retarget_held_to_r5': 'its reviewed recovery is an r4 restore', 'r5_before_run_held_start_with_stop': 'does not allow a stop recovery'}
PREPARATION_HELD = {'controller_appears_before_mutation': 'appeared during preparation', 'port_busy_before_mutation': 'became busy during preparation',
                    'task_changes_during_preparation': 'changed during preparation', 'backup_mismatch': 'differ between passes'}
READBACK_HELD = {'register_does_not_apply': 'not the expected r5 action', 'readback_denied': 'could not be read back', 'trigger_user_rewritten': 'logon trigger',
                 'xml_outside_changed': 'changed outside Actions/Triggers/RegistrationInfo/Settings-Enabled', 'register_leaves_enabled': 'not disabled after the update',
                 'receipt_collision': 'retarget-receipt.json'}
SOURCE_STOP_ATTEMPT = {'r5_gemini_fallback_from_r5_receipt': 'v2', 'r5_from_r4_restore_receipt': 'v2'}


@pytest.mark.parametrize('case', sorted(MUTATION_CASES))
def test_retarget_mutation_path_is_driven_with_fixtures(tmp_path, case):
    spec = MUTATION_CASES[case]
    target, overrides, setup, writer = spec[:4]
    config = spec[6] if len(spec) > 4 else R5_CFG
    base = tmp_path / 'CoChem'
    base.mkdir()
    queue = tmp_path / 'private' / 'queue-restart-20261011-r4-v1'
    # The target root is redirected into the tmp tree BEFORE any per-case setup runs, and again after it (a case may change -Attempt).
    redirect = "$script:targetRoot=Join-Path $script:base ('WardenRetarget4.2.7-windows-20261011-'+$script:Target+'-'+$script:Attempt);"
    body = (FIXTURE + ENV_STUBS + f"$script:base='{ps(base)}';$script:Target='{target}';$script:Attempt='v1';$script:queueRestart='{ps(queue)}';" + redirect + setup + redirect +
            f"$folder=New-FixtureFolder {overrides};" + writer + f"$context=New-FixtureContext $script:Target '{ps(config)}';" + r'''
      $failed=$false;$message='';$result=$null;try{$result=Invoke-Retarget $folder $context $script:fixtureLineage}catch{$failed=$true;$message=$_.Exception.Message}
      [ordered]@{failed=$failed;message=$message;registered=@($script:registered).Count;registration=$(if(@($script:registered).Count){$script:registered[0]}else{$null});
        backups=$script:backups;rights=$script:rightsProbes;root=(Test-Path -LiteralPath $script:targetRoot);target_root=$script:targetRoot;
        intent=(Test-Path (Join-Path $script:targetRoot 'retarget-intent.json'));held=(Test-Path (Join-Path $script:targetRoot 'retarget-held.json'));
        receipt=(Test-Path (Join-Path $script:targetRoot 'retarget-receipt.json'));after_xml=(Test-Path (Join-Path $script:targetRoot 'warden-task-after.xml'));
        result=$result;action=[ordered]@{path=$script:action.Path;arguments=$script:action.Arguments;wd=$script:action.WorkingDirectory};
        triggers=@($script:triggerItems|ForEach-Object {[ordered]@{type=$_.Type;user=$_.UserId;delay=$_.Delay;enabled=$_.Enabled}});enabled=$script:task.Enabled;
        events=@($script:events);description=$script:definition.RegistrationInfo.Description;runs=$script:runCalls;xml_now=(Get-TaskXmlSha256 $script:task.Xml)}|ConvertTo-Json -Compress -Depth 6
    ''')
    value = run(tmp_path, body)
    root = Path(value['target_root'])
    assert value['runs'] == 0 and value['events'] == [], 'the retarget path never runs, ends or enables the task directly'
    if case in NOTHING_CONSUMED:
        assert value['failed'] and value['registered'] == 0 and value['backups'] == 0 and not value['held'] and not value['intent']
        assert value['root'] == (case == 'root_exists'), 'nothing may be consumed before the mutation gate'
        assert NOTHING_CONSUMED[case] in value['message'], value['message']
        return
    if case == 'root_fails_after_create':
        assert value['failed'] and value['registered'] == 0 and value['backups'] == 0 and value['held'] and not value['intent']
        held = json.loads((root / 'retarget-held.json').read_text(encoding='utf-8'))
        assert held['phase'] == 'ROOT' and held['mutation_requested'] is False and held['requires_reviewed_recovery'] is True
        assert 'could not be secured' in value['message'] and 'choose another -Attempt' in value['message']
        return
    if case in PREPARATION_HELD:
        assert value['failed'] and value['registered'] == 0 and value['held'] and value['intent']
        held = json.loads((root / 'retarget-held.json').read_text(encoding='utf-8'))
        assert held['phase'] == 'PREPARATION' and held['mutation_requested'] is False and held['automatic_retry_allowed'] is False
        assert PREPARATION_HELD[case] in held['reason'] and 'held before any task change' in value['message'] and 'Nothing was retargeted' in value['message']
        return
    if case in READBACK_HELD:
        assert value['failed'] and value['registered'] == 1 and value['held']
        held = json.loads((root / 'retarget-held.json').read_text(encoding='utf-8'))
        assert held['phase'] == 'MUTATION_READBACK' and held['mutation_requested'] is True and held['requires_reviewed_recovery'] is True
        assert READBACK_HELD[case] in held['reason'], held['reason']
        assert 'retarget readback is held' in value['message'] and 'Do not retry with another -Attempt' in value['message']
        if case == 'readback_denied':
            assert held['readback_readable'] is False and held['readback'] is None
        else:
            assert held['readback_readable'] is True and len(held['readback']['task_xml_sha256']) == 64 and held['readback']['task_xml_sha256'] == value['xml_now']
        if case == 'register_does_not_apply':
            assert held['readback']['action_path'] == R4_PY
        if case == 'register_leaves_enabled':
            assert held['readback']['enabled'] is True
        if case == 'trigger_user_rewritten':
            assert held['readback']['trigger_enabled'] is False and held['readback']['enabled'] is False, 'the recorded readback a later r4 restore binds (C-F2 recovery)'
        if case == 'receipt_collision':
            assert (root / 'retarget-receipt.json').read_text(encoding='utf-8') == 'PRE' and held['receipt_written'] is False
        return
    # Success paths: registered DISABLED for both targets (the r5 logon trigger disabled too); only -Start ever enables.
    source_state, enabled_before = spec[4], spec[5]
    assert not value['failed'], value['message']
    registration = value['registration']
    assert value['registered'] == 1 and registration['flags'] == 4 and registration['user'] == 'SYSTEM' and registration['logon'] == 5 and registration['sddl'] == SDDL
    assert registration['name'] == 'CoChem-4.2.7-Warden' and registration['password_is_null'] is True and registration['task_enabled'] is False
    assert value['backups'] == 1 and value['rights'] == 1 and value['intent'] and value['after_xml'] and value['receipt'] and not value['held']
    assert value['enabled'] is False, 'a retarget without -Start leaves the task disabled (no surprise start at the next logon)'
    receipt = json.loads((root / 'retarget-receipt.json').read_text(encoding='utf-8'))
    intent = json.loads((root / 'retarget-intent.json').read_text(encoding='utf-8'))
    after_xml_sha = sha256_file(root / 'warden-task-after.xml')
    if target == 'r5':
        expected_args = R5_ARGS.replace(R5_CFG, config)
        user = 'S-1-5-21-9-9-9-1001' if case == 'trigger_user_read_back_as_sid' else 'AETHERDESK\\ansac'
        assert value['action'] == {'path': R5_PY, 'arguments': expected_args, 'wd': R5_ROOT}
        assert value['triggers'] == [{'type': 9, 'user': user, 'delay': 'PT1M', 'enabled': False}], 'the logon trigger is registered disabled (two-phase start)'
        assert registration['trigger_enabled'] == [False] and receipt['trigger_enabled_after'] is False and intent['trigger_enabled_after'] is False
        assert '<Enabled>false</Enabled><UserId>' in (root / 'warden-task-after.xml').read_text(encoding='utf-8'), 'the recorded XML carries the disabled trigger'
        assert receipt['status'] == 'WARDEN_RETARGETED_TO_R5_NOT_STARTED' and receipt['triggers'] == [{'type': 'logon', 'user_id': 'AETHERDESK\\ansac', 'delay': 'PT1M'}]
        assert receipt['install_after_path'] == R5_ROOT + r'\install-after.json' and receipt['install_after_sha256'] == 'a' * 64 and receipt['config_path'] == config
        assert receipt['queue_launch_output_root'] == R5_QUEUE_ROOT and receipt['docker_wait_seconds'] == 900 and receipt['queue_launch_output'] is None
        assert value['description'] == 'Reviewed r5 retarget ' + receipt['attempt'] + ' (reboot-safe logon trigger) of the r4 retarget task. Logon trigger only, no retries; preserve on any failure.'
    else:
        expected_args = f'-I -B -m cochem_pipeline daemon --config "{R4_RESTORE_CONFIG}" --queue-launch-output "{queue}"'
        assert value['action'] == {'path': R4_PY, 'arguments': expected_args, 'wd': R4_ROOT} and value['triggers'] == []
        assert receipt['status'] == 'WARDEN_RETARGETED_TO_R4_NOT_STARTED' and receipt['triggers'] == [] and receipt['install_after_path'] is None and receipt['install_after_sha256'] is None
        assert receipt['config_path'] == R4_RESTORE_CONFIG and receipt['config_sha256'] == CONFIG_PIN and receipt['queue_launch_output'] == str(queue)
        assert receipt['trigger_enabled_after'] is None and intent['trigger_enabled_after'] is None and registration['trigger_enabled'] == []
        assert value['description'] == 'Reviewed r4 restart ' + receipt['attempt'] + ' after the r5 sitting. No triggers/retries; preserve on any failure.'
    # The CUTOVER interface contract fields, with these exact names and the exact registered action.
    for field in ('schema', 'status', 'target', 'attempt', 'task_name', 'runtime_root', 'config_path', 'config_sha256', 'install_after_path', 'install_after_sha256',
                  'action', 'triggers', 'task_xml_sha256', 'source_state', 'source_attempt', 'stop_attempt', 'enabled_before', 'enabled_after', 'trigger_enabled_after',
                  'source_start_intent_sha256', 'source_start_held_sha256', 'source_retarget_held_sha256', 'source_mutation_evidence', 'stop_start_binding'):
        assert field in receipt, field
    assert list(receipt)[:2] == ['schema', 'status'] and receipt['schema'] == 'cochem-warden-retarget/3' and receipt['target'] == target and receipt['task_name'] == 'CoChem-4.2.7-Warden'
    assert receipt['action'] == {'execute': value['action']['path'], 'arguments': value['action']['arguments'], 'working_directory': value['action']['wd']}
    assert receipt['task_xml_sha256'] == receipt['task_xml_after_sha256'] == after_xml_sha == value['xml_now']
    assert receipt['enabled_before'] is enabled_before and receipt['enabled_after'] is False and receipt['sddl_preserved'] is True and receipt['started'] is False
    assert receipt['old_controller']['pid'] == 20664 and receipt['observer_processes'][0]['pid'] == 9472 and receipt['intent_sha256'] == sha256_file(root / 'retarget-intent.json')
    assert receipt['state_backup_sha256'] == sha256_file(root / 'state-backup.json') and receipt['task_xml_before_sha256'] == sha256_file(root / 'warden-task-before.xml')
    assert intent['schema'] == 'cochem-warden-retarget-intent/3' and intent['action_after'] == receipt['action'] and intent['start_requested'] is False
    assert receipt['source_state'] == source_state and intent['source']['source_state'] == source_state
    if source_state == 'r4-v1':
        assert receipt['source_attempt'] is None and receipt['stop_attempt'] is None and receipt['stop_receipt_sha256'] is None and receipt['source_receipt_sha256'] is None
    elif source_state.endswith('retarget-receipt'):
        assert receipt['source_attempt'] == 'v1' and receipt['stop_attempt'] is None and receipt['stop_receipt_sha256'] is None and len(receipt['source_receipt_sha256']) == 64
        assert receipt['source_start_evidence'] == ('START_HELD_BEFORE_RUN' if 'held_before_run' in case else 'NO_START')
    elif source_state.endswith('retarget-held'):
        assert receipt['source_attempt'] == 'v1' and receipt['stop_attempt'] is None and receipt['stop_receipt_sha256'] is None and len(receipt['source_receipt_sha256']) == 64
        assert receipt['source_mutation_evidence'] == ('MUTATION_READBACK_HELD' if 'readback' in case else 'MUTATION_INTERRUPTED')
        assert (receipt['source_retarget_held_sha256'] is None) == ('interrupted' in case)
    elif source_state.endswith('start-held'):
        assert receipt['source_attempt'] == 'v1' and receipt['stop_attempt'] == 'v1' and len(receipt['stop_receipt_sha256']) == 64 and receipt['source_start_receipt_sha256'] is None
        assert len(receipt['source_start_intent_sha256']) == 64 and receipt['stop_start_binding'] == receipt['source_start_evidence']
        assert receipt['source_start_evidence'] == {'r4_from_r5_interrupted_start': 'START_INTERRUPTED_HELD', 'r5_from_r5_crashed_start': 'START_CRASHED_NO_RECORD',
                                                    'r5_from_r4_restore_held_after_gate': 'START_HELD_AFTER_HEALTH_GATE',
                                                    'r4_from_r5_held_before_gate': 'START_HELD_BEFORE_HEALTH_GATE'}[case]
    else:
        assert receipt['source_attempt'] == 'v1' and len(receipt['stop_receipt_sha256']) == 64 and len(receipt['source_start_receipt_sha256']) == 64
        assert receipt['stop_attempt'] == SOURCE_STOP_ATTEMPT.get(case, 'v1') and receipt['stop_start_binding'] == 'START_RECEIPT'
    if source_state in ('r5-receipt', 'r5-retarget-receipt', 'r5-start-held', 'r5-retarget-held'):
        assert receipt['triggers_before'][0]['type'] == 9
    result = value['result']
    assert result['schema'] == 'cochem-warden-retarget-result/3' and result['status'] == receipt['status'] and result['receipt_sha256'] == sha256_file(root / 'retarget-receipt.json')
    assert result['receipt_path'] == str(root / 'retarget-receipt.json') and result['started'] is False and result['enabled_before'] is enabled_before and result['enabled_after'] is False


# ----------------------------------------------------------------------------------------------- the start path

START_CASES = {
    'r5_success': ('r5', '', "@($null,'A','A')"), 'r4_success': ('r4', '', "@('A','A')"), 'already_enabled': ('r5', 'Enabled=$true;State=3', "@('A','A')"),
    'readiness_then_ready': ('r5', '', "@('A','K','H','A')"), 'r4_controller_not_ready': ('r4', '', "@('A','N','N')"),
    'knowledge_never_ready': ('r5', '', "@('A','K','K','K')"), 'admission_never_ready': ('r5', '', "@('A','H','H')"),
    'execution_quarantine': ('r5', '', "@('A','X','A')"), 'quarantined_slot': ('r4', '', "@('A','Q')"), 'active_work': ('r5', '', "@('A','W')"),
    'wrong_source_root': ('r5', '', "@('R','R','R')"), 'identity_changes': ('r5', '', "@('B','B','B','B')"), 'port_owner_differs': ('r5', '', "@('A','A')"),
    'duplicate_start': ('r5', '', "@('A','A')"), 'start_held_exists': ('r5', '', "@('A','A')"), 'run_throws': ('r5', 'RunThrows=$true', "@('A','A')"),
    'enable_fails': ('r5', 'EnableThrows=$true', "@('A','A')"), 'disable_fails': ('r5', 'DisableThrows=$true', "@('A','K','K')"),
    'instance_mismatch': ('r5', 'RunInstances=2', "@('A','A')"), 'running_guid_differs': ('r5', "RunningGuid='{00000000-0000-0000-0000-00000000bbbb}'", "@('A','A')"),
    'readback_unreadable': ('r4', 'DenyAfterRun=$true', "@('A','A')"), 'receipt_collision': ('r5', '', "@('A','A')"), 'started_xml_collision': ('r5', '', "@('A','A')"),
    'r4_receipt_collision': ('r4', '', "@('A','A')"),
    'task_not_retargeted': ('r5', 'NOT_RETARGETED', "@('A','A')"), 'port_busy': ('r5', '', "@('A','A')"), 'trigger_already_enabled': ('r5', 'TRIGGER_ENABLED', "@('A','A')"),
    # the two-phase start: the trigger enable after the health gate, and its readback
    'trigger_enable_ignored': ('r5', 'TriggerEnableIgnored=$true', "@('A','A')"), 'second_register_throws': ('r5', 'SecondRegisterThrows=$true', "@('A','A')"),
    'trigger_enable_changes_xml': ('r5', "ExtraAfterRegister='<Priority>4</Priority>'", "@('A','A')"),
    'trigger_enable_readback_denied': ('r5', 'DenyAfterRegister=$true', "@('A','A')"),
    # re-audit R-F3: the live task must be the one THIS attempt registered (its digest-bound warden-task-after.xml)
    'other_attempt_registered': ('r5', '', "@('A','A')"), 'after_xml_names_other_attempt': ('r5', '', "@('A','A')"),
    'retarget_receipt_digest_differs': ('r5', '', "@('A','A')"), 'live_xml_outside_flags_differs': ('r4', '', "@('A','A')"),
}
START_HELD = {'knowledge_never_ready': 'knowledge is not ready', 'admission_never_ready': 'does not admit work', 'execution_quarantine': 'execution quarantine',
              'quarantined_slot': 'quarantined slots', 'active_work': 'active job', 'wrong_source_root': 'unexpected identity or source root',
              'identity_changes': 'identity changed', 'port_owner_differs': 'owned by pid 99', 'run_throws': 'run refused', 'instance_mismatch': 'exactly one running instance',
              'running_guid_differs': 'not the one requested', 'readback_unreadable': 'could not be read back', 'receipt_collision': 'start-receipt.json',
              'started_xml_collision': 'warden-task-started.xml', 'r4_receipt_collision': 'start-receipt.json',
              'enable_fails': 'enable refused', 'disable_fails': 'knowledge is not ready', 'trigger_enable_ignored': 'it must be enabled',
              'second_register_throws': 'second update refused', 'trigger_enable_changes_xml': 'outside the task and trigger Enabled flags',
              'trigger_enable_readback_denied': 'could not be read back after its logon trigger was enabled'}
START_STAGE = {'enable_fails': 'BEFORE_RUN', 'run_throws': 'RUN', 'knowledge_never_ready': 'HEALTH_WAIT', 'admission_never_ready': 'HEALTH_WAIT', 'execution_quarantine': 'HEALTH_WAIT',
               'quarantined_slot': 'HEALTH_WAIT', 'active_work': 'HEALTH_WAIT', 'wrong_source_root': 'HEALTH_WAIT', 'identity_changes': 'HEALTH_WAIT', 'disable_fails': 'HEALTH_WAIT',
               'port_owner_differs': 'POST_START_READBACK', 'instance_mismatch': 'POST_START_READBACK', 'running_guid_differs': 'POST_START_READBACK',
               'readback_unreadable': 'POST_START_READBACK', 'receipt_collision': 'RECEIPT', 'started_xml_collision': 'RECEIPT', 'r4_receipt_collision': 'RECEIPT',
               'trigger_enable_ignored': 'TRIGGER_ENABLE', 'second_register_throws': 'TRIGGER_ENABLE', 'trigger_enable_changes_xml': 'TRIGGER_ENABLE',
               'trigger_enable_readback_denied': 'TRIGGER_ENABLE'}
START_REFUSED = {'duplicate_start': 'already requested', 'start_held_exists': 'start-held.json', 'task_not_retargeted': 'not the expected r5 action', 'port_busy': 'port is busy',
                 'trigger_already_enabled': 'it must be disabled', 'other_attempt_registered': 'is not the task r5 attempt v1 registered',
                 'after_xml_names_other_attempt': 'registration description of r5 attempt v1', 'retarget_receipt_digest_differs': 'Source digest changed',
                 'live_xml_outside_flags_differs': 'is not the task r4 attempt v1 registered'}
# Per-case steps around the attempt's own retarget files: PRE runs before warden-task-after.xml is written, POST after.
START_PRE = {'after_xml_names_other_attempt': "$script:definition.RegistrationInfo.Description=(Get-TargetDescription $script:Target 'v2');"}
START_POST = {'other_attempt_registered': "$script:definition.RegistrationInfo.Description=(Get-TargetDescription $script:Target 'v2');",
              'retarget_receipt_digest_differs': "$binding.receipt_sha256=('0'*64);", 'live_xml_outside_flags_differs': "$script:xmlExtra='<Priority>4</Priority>';"}
START_BODY = r'''
$context=New-FixtureContext $script:Target;$script:targetSourceRoot=$context.source_root
# As every retarget leaves it: the target action, registered disabled, the r5 logon trigger disabled too.
$over=@{Path=$context.action.execute;Arguments=$context.action.arguments;WorkingDirectory=$context.action.working_directory;Triggers=@();Enabled=$false;State=1}
if($script:Target -ceq 'r5'){$over.Triggers=@(New-FixtureTrigger -Enabled $false)}
$folder=New-FixtureFolder __LIVE__
# This attempt's own retarget evidence: its description on the task, its warden-task-after.xml and the receipt that pins it.
$script:definition.RegistrationInfo.Description=(Get-TargetDescription $script:Target $script:Attempt)
__PRE__
$afterSha=Write-FixtureText (Join-Path $script:targetRoot 'warden-task-after.xml') (Get-FixtureXmlWith $false $(if($script:Target -ceq 'r5'){$false}else{$null}))
Write-FixtureJson (Join-Path $script:targetRoot 'retarget-receipt.json') ([ordered]@{schema='cochem-warden-retarget/3';attempt=$script:Attempt;task_xml_sha256=$afterSha;task_xml_after_sha256=$afterSha})
$binding=[ordered]@{receipt_path=(Join-Path $script:targetRoot 'retarget-receipt.json');receipt_sha256=(Get-FixtureFileSha (Join-Path $script:targetRoot 'retarget-receipt.json'));sddl='__SDDL__';
  source=[ordered]@{source_state='r5-receipt';source_attempt='v1';stop_attempt='v2'}}
__POST__
function Get-TargetProcessProof {param($ProcessId,$Context)if($script:proofFails){throw 'The controller port is owned by pid 99, not the pid reported by /health.'};[ordered]@{pid=$ProcessId;image=$script:basePython;parent_image=$Context.action.execute;owner='SYSTEM';port_owner_verified=$true}}
'''


@pytest.mark.parametrize('case', sorted(START_CASES))
def test_start_once_path_is_driven_with_fixtures(tmp_path, case):
    target, overrides, health = START_CASES[case]
    root = tmp_path / 'WardenRetarget4.2.7-windows-20261011-r5-v1'
    root.mkdir()
    if case == 'duplicate_start':
        (root / 'start-intent.json').write_text('{}', encoding='utf-8')
    if case == 'start_held_exists':
        (root / 'start-held.json').write_text('{}', encoding='utf-8')
    if case in ('receipt_collision', 'r4_receipt_collision'):
        (root / 'start-receipt.json').write_text('PRE', encoding='utf-8')
    if case == 'started_xml_collision':
        (root / 'warden-task-started.xml').write_text('PRE', encoding='utf-8')
    live = {'NOT_RETARGETED': '@{}', 'TRIGGER_ENABLED': '(Merge-Hash $over @{Triggers=@(New-FixtureTrigger)})'}.get(overrides, '$over' if not overrides else f'(Merge-Hash $over @{{{overrides}}})')
    extra = {'port_owner_differs': '$script:proofFails=$true;', 'port_busy': '$script:loopbackBusyAt=@(1);'}.get(case, '')
    body = (FIXTURE + ENV_STUBS + HEALTH_FIXTURE + f"$script:Target='{target}';$script:targetRoot='{ps(root)}';$script:healthScript={health};$script:proofFails=$false;{extra}"
            + START_BODY.replace('__LIVE__', live).replace('__SDDL__', SDDL).replace('__PRE__', START_PRE.get(case, '')).replace('__POST__', START_POST.get(case, '')) + r'''
      $failed=$false;$message='';$result=$null;try{$result=Invoke-StartOnce $folder $context $binding}catch{$failed=$true;$message=$_.Exception.Message}
      [ordered]@{failed=$failed;message=$message;runs=$script:runs;run_calls=$script:runCalls;result=$result;enabled=$script:taskEnabled;events=@($script:events);
        registered=@($script:registered);trigger_now=$(if($script:triggerItems.Count){[bool]$script:triggerItems[0].Enabled}else{$null});
        intent=(Test-Path (Join-Path $script:targetRoot 'start-intent.json'));held=(Test-Path (Join-Path $script:targetRoot 'start-held.json'));
        receipt=(Test-Path (Join-Path $script:targetRoot 'start-receipt.json'));started_xml=(Test-Path (Join-Path $script:targetRoot 'warden-task-started.xml'));
        xml_now=(Get-TaskXmlSha256 $script:task.Xml);action=$context.action}|ConvertTo-Json -Compress -Depth 6
    ''')
    value = run(tmp_path, body, timeout=300)
    assert 'end' not in value['events'], 'a start never Ends an instance'
    registered = value['registered']
    if case in START_REFUSED:
        assert value['failed'] and value['run_calls'] == 0 and START_REFUSED[case] in value['message'], value['message']
        assert value['events'] == [] and value['enabled'] is (case == 'task_not_retargeted'), 'a refusal before the intent never touches Enabled'
        assert registered == []
        if case not in ('duplicate_start', 'start_held_exists'):
            assert not value['intent'] and not value['held']
        if case == 'duplicate_start':
            assert not value['held']
        return
    if case in START_HELD:
        assert value['failed'] and value['intent'] and value['held'] and not (case != 'receipt_collision' and case != 'r4_receipt_collision' and value['receipt']), value
        held = json.loads((root / 'start-held.json').read_text(encoding='utf-8'))
        assert START_HELD[case] in held['reason'], held['reason']
        assert held['schema'] == 'cochem-warden-start-held/3' and held['requires_reviewed_recovery'] is True and held['automatic_retry_allowed'] is False
        assert held['disable_attempted'] is True and held['enabled_before'] is False and 'no further -Attempt without a reviewed recovery' in value['message']
        assert held['interrupted'] is False and held['stage'] == START_STAGE[case] and held['receipt_written'] is False
        after_gate = START_STAGE[case] in ('TRIGGER_ENABLE', 'RECEIPT')
        assert held['health_gate_passed'] is after_gate
        # Re-audit R-F1: every hold after Run is recoverable by a stop; only a hold before Run keeps the no-stop path.
        assert held['stop_recovery_allowed'] is (not held['held_before_run']) and held['held_before_run'] is (case in ('enable_fails', 'run_throws'))
        assert held['trigger_enable_requested'] is (after_gate and target == 'r5')
        if target == 'r4':
            assert held['trigger_enabled_after'] is None and registered == []
        elif held['task_readable']:
            # The logon trigger stays disabled unless the second phase already enabled it, recorded as read back.
            assert held['trigger_enabled_after'] is (case in ('receipt_collision', 'started_xml_collision', 'trigger_enable_changes_xml'))
            assert value['trigger_now'] is held['trigger_enabled_after']
        if not after_gate:
            assert registered == [] and value['trigger_now'] in (False, None), 'a failure before the health gate passes never enables the logon trigger'
        if case == 'enable_fails':
            # Held before Run: the evidence a later r5-retarget-receipt source accepts.
            assert value['run_calls'] == 0 and value['runs'] == 0 and held['run_requested'] is False and held['enable_requested'] is True and held['instance_guid'] is None
            assert held['held_before_run'] is True and held['run_exception'] is None
            assert value['events'] == ['enable:False'] and held['enabled_after'] is False and held['disable_error'] is None and held['task_xml_after_sha256'] == value['xml_now']
        else:
            assert held['run_requested'] is True and value['run_calls'] == 1 and value['runs'] == (0 if case == 'run_throws' else 1)
            assert value['events'][:2] == ['enable:True', 'run']
        if case == 'run_throws':
            # Audit C-F7: Run threw without an instance and the readback shows none, so the hold is before Run.
            assert held['instance_guid'] is None and 'run refused' in held['run_exception'] and held['running_instances'] == 0 and held['held_before_run'] is True
        elif case != 'enable_fails':
            assert held['held_before_run'] is False and held['run_exception'] is None and held['instance_guid'] == '{00000000-0000-0000-0000-00000000aaaa}'
        if case == 'readback_unreadable':
            assert held['task_readable'] is False and held['task_state'] is None and held['enabled_after'] is None and held['task_xml_after_sha256'] is None
            assert 'could not be read back after the disable request' in held['disable_error'] and value['enabled'] is False and 'could NOT be confirmed disabled' in value['message']
        elif case == 'trigger_enable_readback_denied':
            assert held['task_readable'] is False and held['trigger_enabled_after'] is None and len(registered) == 1 and registered[0]['trigger_enabled'] == [True]
        elif case == 'disable_fails':
            assert held['enabled_after'] is True and 'disable refused' in held['disable_error'] and value['enabled'] is True and value['events'] == ['enable:True', 'run']
            assert 'could NOT be confirmed disabled' in value['message']
        elif case != 'enable_fails':
            assert value['events'] == ['enable:True', 'run', 'enable:False'] and held['enabled_after'] is False and held['disable_error'] is None
            assert value['enabled'] is False and held['task_xml_after_sha256'] == value['xml_now'] and 'The task was disabled again' in value['message']
        if after_gate and target == 'r5':
            # The second phase: one more TASK_UPDATE after Run and the passing health samples, carrying the trigger enabled.
            assert len(registered) == 1 and registered[0]['flags'] == 4 and registered[0]['sddl'] == SDDL and registered[0]['task_enabled'] is True
            assert registered[0]['events_before'] == ['enable:True', 'run'] and registered[0]['health_before'] >= 2
        if case in ('receipt_collision', 'r4_receipt_collision'):
            assert (root / 'start-receipt.json').read_text(encoding='utf-8') == 'PRE' and held['receipt_written'] is False and value['started_xml']
        if case in ('trigger_enable_ignored', 'second_register_throws', 'trigger_enable_changes_xml', 'trigger_enable_readback_denied'):
            assert not value['receipt'] and not value['started_xml'], 'no receipt before the trigger readback passes'
        return
    assert not value['failed'], value['message']
    enabled_by_start = case != 'already_enabled'
    assert value['runs'] == 1 and value['run_calls'] == 1 and value['enabled'] is True and value['receipt'] and value['started_xml'] and not value['held']
    assert value['events'] == (['enable:True', 'run'] if enabled_by_start else ['run']), 'the single enable comes immediately before the single Run'
    intent = json.loads((root / 'start-intent.json').read_text(encoding='utf-8'))
    receipt = json.loads((root / 'start-receipt.json').read_text(encoding='utf-8'))
    started_xml = (root / 'warden-task-started.xml').read_text(encoding='utf-8')
    assert intent['enabled_before'] is (not enabled_by_start) and intent['enable_before_run'] is enabled_by_start and intent['exactly_one_start'] is True
    assert intent['trigger_enable_after_health_gate'] is (target == 'r5')
    status = 'WARDEN_R5_RUNNING_HEALTH_VERIFIED' if target == 'r5' else 'WARDEN_R4_RESTARTED_HEALTH_VERIFIED'
    assert receipt['schema'] == 'cochem-warden-start/3' and receipt['status'] == status and list(receipt)[:2] == ['schema', 'status']
    for field in ('target', 'attempt', 'task_name', 'runtime_root', 'config_path', 'config_sha256', 'install_after_path', 'install_after_sha256', 'action', 'triggers',
                  'task_xml_sha256', 'source_state', 'source_attempt', 'stop_attempt', 'enabled_before', 'enabled_by_start', 'enabled_after', 'trigger_enabled_before',
                  'trigger_enabled_after', 'task_xml_started_sha256', 'task_xml_before_trigger_enable_sha256'):
        assert field in receipt, field
    assert receipt['action'] == {'execute': value['action']['execute'], 'arguments': value['action']['arguments'], 'working_directory': value['action']['working_directory']}
    # The receipt binds the final task XML (after the second phase for r5), recorded in warden-task-started.xml first.
    assert receipt['task_xml_sha256'] == receipt['task_xml_started_sha256'] == value['xml_now'] == sha256_file(root / 'warden-task-started.xml')
    assert receipt['source_state'] == 'r5-receipt' and receipt['source_attempt'] == 'v1' and receipt['stop_attempt'] == 'v2'
    assert receipt['enabled_before'] is (not enabled_by_start) and receipt['enabled_by_start'] is enabled_by_start and receipt['enabled_after'] is True
    assert receipt['running_instances'] == 1 and receipt['task_state'] == 4
    assert receipt['controller']['pid'] == 4242 and receipt['controller']['instance_id'] == 'id-A' and receipt['controller']['knowledge_authority_matches_capture'] is True
    assert receipt['health']['active'] == 0 and receipt['health']['quarantined_slots'] == 0 and receipt['health']['execution_quarantines'] == 0
    assert receipt['process_proof']['port_owner_verified'] is True and receipt['retarget_receipt_sha256'] == sha256_file(root / 'retarget-receipt.json')
    assert receipt['exactly_one_start_requested'] is True
    result = value['result']
    if target == 'r5':
        assert receipt['triggers'] == [{'type': 'logon', 'user_id': 'AETHERDESK\\ansac', 'delay': 'PT1M'}] and receipt['controller']['warden_controller_admission_ready'] is True
        assert receipt['deployment_revision_sha256'] == 'c' * 64 and receipt['controller']['source_root'] == R5_ROOT + r'\.venv\Lib' and receipt['install_after_sha256'] == 'a' * 64
        # Two-phase start: the trigger was enabled by exactly one more TASK_UPDATE after Run and the passing health samples.
        assert receipt['trigger_enabled_before'] is False and receipt['trigger_enabled_after'] is True and value['trigger_now'] is True and result['trigger_enabled_after'] is True
        assert len(registered) == 1 and registered[0]['flags'] == 4 and registered[0]['user'] == 'SYSTEM' and registered[0]['sddl'] == SDDL and registered[0]['task_enabled'] is True
        assert registered[0]['trigger_enabled'] == [True] and registered[0]['events_before'] == value['events'] and registered[0]['health_before'] >= 2
        assert len(receipt['task_xml_before_trigger_enable_sha256']) == 64 and receipt['task_xml_before_trigger_enable_sha256'] != receipt['task_xml_sha256']
        assert '<LogonTrigger><UserId>' in started_xml and '<Enabled>false</Enabled>' not in started_xml
        assert receipt['health']['admission_field'] == 'components.warden_controller.admission_ready' and receipt['health']['admission_gated'] is True
    else:
        assert receipt['triggers'] == [] and receipt['install_after_sha256'] is None and receipt['controller']['warden_controller_ready'] is (case != 'r4_controller_not_ready')
        assert receipt['deployment_revision_sha256'] == '38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e' and receipt['controller']['source_root'] == R4_ROOT + r'\.venv\Lib'
        assert receipt['trigger_enabled_before'] is None and receipt['trigger_enabled_after'] is None and receipt['task_xml_before_trigger_enable_sha256'] is None and registered == []
        # Audit C-F6: r4 ready is recorded, never gated.
        assert receipt['health']['admission_field'] is None and receipt['health']['admission_gated'] is False
    if case == 'readiness_then_ready':
        assert receipt['health']['gate_evaluations'] == 3
    assert result['schema'] == 'cochem-warden-start-result/3' and result['status'] == status and result['receipt_path'] == str(root / 'start-receipt.json')
    assert result['receipt_sha256'] == sha256_file(root / 'start-receipt.json') and result['enabled_after'] is True and result['enabled_by_start'] is enabled_by_start


INTERRUPT_OUTER = r'''
$ErrorActionPreference='Stop'
$text=[IO.File]::ReadAllText('__DIR__\inner.ps1')
$ps=[PowerShell]::Create();$null=$ps.AddScript($text);$async=$ps.BeginInvoke()
$deadline=[DateTime]::UtcNow.AddSeconds(120)
while(-not (Test-Path '__DIR__\during.txt') -and [DateTime]::UtcNow -lt $deadline -and -not $async.IsCompleted){[Threading.Thread]::Sleep(200)}
[Threading.Thread]::Sleep(700)
# The interruption Ctrl+C or a closed console delivers: PowerShell.Stop(), a PipelineStoppedException that skips every catch.
$ps.Stop()
[ordered]@{invocation_state=[string]$ps.InvocationStateInfo.State;during=(Test-Path '__DIR__\during.txt');
  after_stop=$(if(Test-Path '__DIR__\finally.json'){[IO.File]::ReadAllText('__DIR__\finally.json')}else{$null});
  errors=@($ps.Streams.Error|ForEach-Object {[string]$_})}|ConvertTo-Json -Compress
'''


def run_interrupted(tmp_path: Path, target: str, health: str, hook: str) -> dict:
    """Run Invoke-StartOnce in a child runspace and stop it with PowerShell.Stop() once the hook signals (the audit-cutover technique)."""
    root = tmp_path / 'root'
    root.mkdir()
    prelude = PRELUDE.replace('__SCRIPT__', ps(SCRIPT)).replace('__REGISTER__', ps(REGISTER)).replace('__ROOT__', ps(ROOT))
    inner = (prelude + FIXTURE + ENV_STUBS + HEALTH_FIXTURE + f"$script:Target='{target}';$script:targetRoot='{ps(root)}';$script:healthScript={health};$script:proofFails=$false;"
             + START_BODY.replace('__LIVE__', '$over').replace('__SDDL__', SDDL).replace('__PRE__', '').replace('__POST__', '') + hook.replace('__DIR__', ps(tmp_path)) + r'''
      function Start-Sleep {param($Seconds,$Milliseconds)[Threading.Thread]::Sleep(200)}
      $script:startWaitSeconds=120
      try{$null=Invoke-StartOnce $folder $context $binding}
      finally{[IO.File]::WriteAllText('__DIR__\finally.json',([ordered]@{events=@($script:events);task_enabled=$script:taskEnabled;registered=@($script:registered).Count;
        trigger_now=$(if($script:triggerItems.Count){[bool]$script:triggerItems[0].Enabled}else{$null});xml_now=(Get-TaskXmlSha256 $script:task.Xml)}|ConvertTo-Json -Compress -Depth 4))}
    '''.replace('__DIR__', ps(tmp_path)))
    (tmp_path / 'inner.ps1').write_text(inner, encoding='utf-8-sig')
    outer = tmp_path / 'outer.ps1'
    outer.write_text(INTERRUPT_OUTER.replace('__DIR__', ps(tmp_path)), encoding='utf-8-sig')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(outer)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, (result.stdout[-4000:], result.stderr[-4000:])
    value = json.loads([line for line in result.stdout.splitlines() if line.strip()][-1])
    value['after_stop'] = json.loads(value['after_stop']) if value['after_stop'] else None
    value['held'] = json.loads((root / 'start-held.json').read_text(encoding='utf-8')) if (root / 'start-held.json').exists() else None
    value['files'] = sorted(p.name for p in root.iterdir())
    return value


def test_an_interrupt_during_the_health_wait_disables_the_task_without_end_and_records_start_held(tmp_path):
    """Audit C-F1(a), proved with the auditor's technique: PowerShell.Stop() while Invoke-StartOnce waits for /health."""
    hook = ("function Get-HealthSample {[IO.File]::WriteAllText('__DIR__\\during.txt','enabled='+[string]$script:taskEnabled+' runs='+$script:runs);"
            "[pscustomobject]@{ok=$false;error='controller not answering yet';health=$null}}\n")
    value = run_interrupted(tmp_path, 'r5', "@('A','A')", hook)
    assert value['during'] is True and value['invocation_state'] == 'Stopped', value
    after = value['after_stop']
    # The task-disable stub was called (enable:False after the Run) and End never was; the logon trigger never got enabled.
    assert after['events'] == ['enable:True', 'run', 'enable:False'] and 'end' not in after['events'] and after['task_enabled'] is False
    assert after['registered'] == 0 and after['trigger_now'] is False
    held = value['held']
    assert held is not None and value['files'] == ['retarget-receipt.json', 'start-held.json', 'start-intent.json', 'warden-task-after.xml'], value['files']
    assert held['schema'] == 'cochem-warden-start-held/3' and held['interrupted'] is True and held['stage'] == 'HEALTH_WAIT' and held['receipt_written'] is False
    assert held['run_requested'] is True and held['instance_guid'] == '{00000000-0000-0000-0000-00000000aaaa}' and held['held_before_run'] is False and held['run_exception'] is None
    assert held['health_gate_passed'] is False and held['stop_recovery_allowed'] is True and held['trigger_enable_requested'] is False and held['trigger_enabled_after'] is False
    assert held['disable_attempted'] is True and held['disable_error'] is None and held['enabled_before'] is False and held['enabled_after'] is False
    assert held['task_readable'] is True and held['running_instances'] == 1 and held['task_xml_after_sha256'] == after['xml_now']
    assert held['controller_preserved'] is True and held['requires_reviewed_recovery'] is True and 'interrupted at HEALTH_WAIT' in held['reason']


def test_an_interrupt_after_the_trigger_enable_before_the_receipt_is_recorded_as_interrupted(tmp_path):
    """Two-phase start: an interrupt between the trigger enable and the receipt leaves start-held.json (trigger enabled, task disabled)."""
    hook = ("$script:realWrite=${function:Write-RegistrationControl}\n"
            "function Write-RegistrationControl {param([string]$Path,[string]$Text)if($Path -like '*warden-task-started.xml'){[IO.File]::WriteAllText('__DIR__\\during.txt','x');"
            "while($true){Start-Sleep -Milliseconds 100}};& $script:realWrite $Path $Text}\n")
    value = run_interrupted(tmp_path, 'r5', "@('A','A')", hook)
    assert value['during'] is True and value['invocation_state'] == 'Stopped', value
    after = value['after_stop']
    assert after['events'] == ['enable:True', 'run', 'enable:False'] and 'end' not in after['events'] and after['task_enabled'] is False
    assert after['registered'] == 1 and after['trigger_now'] is True, 'the second phase had enabled the logon trigger'
    held = value['held']
    assert held is not None and value['files'] == ['retarget-receipt.json', 'start-held.json', 'start-intent.json', 'warden-task-after.xml'], value['files']
    assert held['interrupted'] is True and held['stage'] == 'RECEIPT' and held['health_gate_passed'] is True and held['stop_recovery_allowed'] is True
    assert held['trigger_enable_requested'] is True and held['trigger_enabled_after'] is True and held['enabled_after'] is False and held['disable_error'] is None
    assert held['receipt_written'] is False and held['task_xml_after_sha256'] == after['xml_now'] and held['running_instances'] == 1


def test_an_interrupt_after_the_start_receipt_file_exists_writes_no_start_held_and_keeps_the_task(tmp_path):
    """Re-audit R-F4 (sweep I6): once start-receipt.json exists the start completed; the finally neither disables nor holds."""
    hook = ("$script:realWrite=${function:Write-RegistrationControl}\n"
            "function Write-RegistrationControl {param([string]$Path,[string]$Text)$h=& $script:realWrite $Path $Text;if($Path -like '*start-receipt.json'){"
            "[IO.File]::WriteAllText('__DIR__\\during.txt','x');while($true){Start-Sleep -Milliseconds 100}};$h}\n")
    value = run_interrupted(tmp_path, 'r5', "@('A','A')", hook)
    assert value['during'] is True and value['invocation_state'] == 'Stopped', value
    after = value['after_stop']
    assert value['held'] is None and 'start-held.json' not in value['files'], value['files']
    assert value['files'] == ['retarget-receipt.json', 'start-intent.json', 'start-receipt.json', 'warden-task-after.xml', 'warden-task-started.xml'], value['files']
    assert after['events'] == ['enable:True', 'run'] and after['task_enabled'] is True and after['trigger_now'] is True and after['registered'] == 1


RECEIPT_BINDING_CASES = {'valid_r5': None, 'valid_r4': None, 'valid_from_r4_restore': None, 'valid_from_r5_retarget': None, 'valid_from_r5_receipt': None,
                         'wrong_schema': 'does not bind', 'wrong_status': 'does not bind', 'wrong_attempt': 'does not bind',
                         'wrong_config_sha': 'does not bind', 'action_differs': 'does not bind', 'triggers_missing': 'does not bind', 'xml_sha_bad': 'does not bind',
                         'source_state_bad': 'does not bind', 'sddl_preserved_string': 'does not bind', 'install_after_differs': 'does not bind',
                         'enabled_after_true': 'does not bind', 'enabled_after_missing': 'does not bind', 'held_present': 'retarget-held.json',
                         'valid_from_r4_restore_retarget': None, 'valid_from_r5_start_held': None, 'valid_from_r4_restore_start_held': None,
                         'valid_from_r5_retarget_held': None, 'valid_from_r4_restore_retarget_held': None,
                         'trigger_enabled_after_true': 'does not bind', 'trigger_enabled_after_missing': 'does not bind', 'r4_trigger_enabled_after_bool': 'does not bind'}
BINDING_SOURCE = {'valid_from_r4_restore': 'r4-restore-receipt', 'valid_from_r5_retarget': 'r5-retarget-receipt', 'valid_from_r5_receipt': 'r5-receipt',
                  'valid_from_r4_restore_retarget': 'r4-restore-retarget-receipt', 'valid_from_r5_start_held': 'r5-start-held',
                  'valid_from_r4_restore_start_held': 'r4-restore-start-held', 'valid_from_r5_retarget_held': 'r5-retarget-held',
                  'valid_from_r4_restore_retarget_held': 'r4-restore-retarget-held'}


def test_start_only_binds_this_attempts_retarget_receipt_from_any_accepted_source(tmp_path):
    lines = ['$r=[ordered]@{}']
    for case in RECEIPT_BINDING_CASES:
        target = 'r4' if case in ('valid_r4', 'r4_trigger_enabled_after_bool') else 'r5'
        mutate = {'wrong_schema': "$x.schema='cochem-warden-retarget/2'", 'wrong_status': "$x.status='WARDEN_RETARGETED_TO_R4_NOT_STARTED'", 'wrong_attempt': "$x.attempt='v9'",
                  'wrong_config_sha': "$x.config_sha256=('0'*64)", 'action_differs': "$x.action=[ordered]@{execute='x';arguments=$ctx.action.arguments;working_directory=$ctx.action.working_directory}",
                  'triggers_missing': '$x.triggers=@()', 'xml_sha_bad': "$x.task_xml_sha256='abc'", 'source_state_bad': "$x.source_state='r3'",
                  'sddl_preserved_string': "$x.sddl_preserved='true'", 'install_after_differs': "$x.install_after_sha256=('0'*64)",
                  'enabled_after_true': "$x.enabled_after=$true", 'enabled_after_missing': "$x.Remove('enabled_after')",
                  'trigger_enabled_after_true': "$x.trigger_enabled_after=$true", 'trigger_enabled_after_missing': "$x.Remove('trigger_enabled_after')",
                  'r4_trigger_enabled_after_bool': "$x.trigger_enabled_after=$false"}.get(case, '')
        source = BINDING_SOURCE.get(case, 'r4-v1')
        root = tmp_path / case
        lines.append(f"$script:targetRoot='{ps(root)}';$ctx=New-FixtureContext '{target}'"
                     f";$x=New-ReceiptHead 'cochem-warden-retarget/3' $ctx.retargeted_status $ctx ([ordered]@{{source_state='{source}';source_attempt=$null;stop_attempt=$null}}) ('f'*64)"
                     f";$x['sddl_preserved']=$true;$x['enabled_before']=$true;$x['enabled_after']=$false;$x['trigger_enabled_after']=$(if('{target}' -ceq 'r5'){{$false}}else{{$null}});{mutate}"
                     f";Write-FixtureJson (Join-Path $script:targetRoot 'retarget-receipt.json') $x;[IO.File]::WriteAllText((Join-Path $script:targetRoot 'warden-task-before.sddl'),'{SDDL}')")
        if case == 'held_present':
            lines.append("Write-FixtureJson (Join-Path $script:targetRoot 'retarget-held.json') @{x=1}")
        lines.append(f"try{{$b=Assert-RetargetReceiptBinding (Read-RetargetReceipt) $ctx;$r['{case}']=[ordered]@{{refused=$false;sddl=$b.sddl;source=$b.source.source_state;sha=$b.receipt_sha256}}}}catch{{$r['{case}']=[ordered]@{{refused=$true;message=$_.Exception.Message}}}}")
    lines.append('$r|ConvertTo-Json -Compress -Depth 4')
    value = run(tmp_path, FIXTURE + '\n'.join(lines))
    for case, expected in RECEIPT_BINDING_CASES.items():
        got = value[case]
        assert got['refused'] == (expected is not None), (case, got)
        if expected:
            assert expected in got['message'], (case, got)
        else:
            assert got['sddl'] == SDDL and got['source'] == BINDING_SOURCE.get(case, 'r4-v1') and got['sha'] == sha256_file(tmp_path / case / 'retarget-receipt.json')


# ----------------------------------------------------------------------------------------------- the main orchestration (all seams stubbed)

MAIN_STUBS = r'''
$script:calls=@();$script:fixtureAdmin=$false;$script:fixtureUser='AETHERDESK\ansac';$script:r5BindingFails=$false;$script:treeFails=$false
$realConstants=${function:Set-RetargetConstants}
function Set-RetargetConstants {& $realConstants;$script:calls+='constants';$script:base=$script:fixtureBase
  $script:targetRoot=Join-Path $script:base ('WardenRetarget4.2.7-windows-20261011-'+$script:Target+'-'+$script:Attempt);$script:queueRestart=Join-Path $script:fixtureBase ('queue-restart-20261011-r4-'+$script:Attempt)}
function Initialize-RetargetHost {$script:calls+='host';[pscustomobject]@{admin=$script:fixtureAdmin;name=$script:fixtureUser}}
function Import-RetargetHelpers {$script:calls+='helpers'}
function Connect-TaskFolder {$script:calls+='folder';$script:fixtureFolder}
function Assert-R4InstalledBindings {[ordered]@{install_receipt_sha256=$script:r4InstallPin;source_manifest_sha256=$script:r4ManifestPin;configuration_sha256=$script:configPin;revision_sha256=$script:r4RevisionPin}}
function Assert-R4RetargetLineage {$script:fixtureLineage}
function Assert-ClientConfig {[ordered]@{path='client';sha256=('9'*64);port=47824}}
function Get-R5RootCandidates {@($script:fixtureR5Root)}
function Find-R5Root {$script:fixtureR5Root}
function Assert-R5InstalledBindings {param($Root)if($script:r5BindingFails){throw 'The r5 installation receipt is not the reviewed successful stopped-runtime build.'};New-FixtureR5Runtime}
function Assert-R5Config {param($Path)if(-not $Path){throw '-Target r5 requires -Config <staged r5 pipeline.json>.'};[ordered]@{path=$Path;sha256=('d'*64);length=10;mode='GEMINI_CONTRACT'}}
function Invoke-R5ConfigParser {param($Python,$Path)$script:calls+='parser';[pscustomobject]@{parser_valid=$true;worker_identities=6;max_shared_slots=4;knowledge_enabled=$true}}
function Assert-CodeTreeOnce {param($Path)$script:calls+=('tree:'+$Path);if($script:treeFails){throw 'Protected code has an untrusted writer.'};1}
function Invoke-Retarget {param($Folder,$Context,$Lineage)$script:calls+='retarget'
  [ordered]@{schema='cochem-warden-retarget-result/3';status=$Context.retargeted_status;mode='RETARGET';target=$Context.target;attempt=$script:Attempt;receipt_path='RR';receipt_sha256=('1'*64);
    retarget_receipt_path='RR';retarget_receipt_sha256=('1'*64);task_name='CoChem-4.2.7-Warden';runtime_root=$Context.runtime_root;source_state='r4-v1';started=$false;enabled_before=$true;enabled_after=$false;sddl='__SDDL__';
    source=[ordered]@{source_state='r4-v1';source_attempt=$null;stop_attempt=$null}}}
function Invoke-StartOnce {param($Folder,$Context,$Binding)$script:calls+='start';$script:startBinding=$Binding
  [ordered]@{schema='cochem-warden-start-result/3';status=$Context.started_status;target=$Context.target;attempt=$script:Attempt;receipt_path='SR';receipt_sha256=('2'*64);enabled_by_start=$true;enabled_after=$true}}
function Invoke-Main {param([hashtable]$Arguments)
  $a=[ordered]@{Target='r5';Config='';Apply=$false;Start=$false;StartOnly=$false;Attempt='v1';SourceAttempt='';StopAttempt=''};foreach($k in @($Arguments.Keys)){$a[$k]=$Arguments[$k]}
  $out=$null;$failed=$false;$message=''
  try{$out=Invoke-RetargetR5Main -Arguments $a -ScriptDirectory '__ROOT__'}catch{$failed=$true;$message=$_.Exception.Message}
  [ordered]@{failed=$failed;message=$message;calls=@($script:calls);output=$(if($null -ne $out){[string](@($out) -join "`n")}else{$null});start_binding=$script:startBinding}|ConvertTo-Json -Compress -Depth 6}
$script:startBinding=$null
'''.replace('__SDDL__', SDDL).replace('__ROOT__', ps(ROOT))


def run_main(tmp_path: Path, arguments: str, setup: str = '', live: str = '@{}') -> dict:
    base = tmp_path / 'CoChem'
    base.mkdir(exist_ok=True)
    body = (FIXTURE + ENV_STUBS + MAIN_STUBS + f"$script:fixtureBase='{ps(base)}';$script:fixtureFolder=New-FixtureFolder {live};" + setup + f"Invoke-Main {arguments}")
    value = run(tmp_path, body)
    value['plan'] = json.loads(value['output']) if value['output'] else None
    return value


def test_main_refuses_a_non_owner_apply_before_any_read(tmp_path):
    for admin, user in (('$false', 'AETHERDESK\\ansac'), ('$true', 'AETHERDESK\\other')):
        value = run_main(tmp_path, "@{Target='r4';Apply=$true}", setup=f"$script:fixtureAdmin={admin};$script:fixtureUser='{user}';$script:calls=@();")
        assert value['failed'] and 'requires the owner in Administrator Windows PowerShell' in value['message']
        assert value['calls'] == ['host'], 'refused before constants, helpers, files or the task folder'
    value = run_main(tmp_path, "@{Target='r4';Start=$true}")
    assert value['failed'] and 'only meaningful together with -Apply' in value['message'] and value['calls'] == [], 'parameter rules run before the host is touched'


def test_main_read_only_plan_for_r5_binds_everything_and_changes_nothing(tmp_path):
    value = run_main(tmp_path, f"@{{Target='r5';Config='{ps(R5_CFG)}'}}")
    assert not value['failed'], value['message']
    plan = value['plan']
    assert 'retarget' not in value['calls'] and 'start' not in value['calls'] and 'parser' in value['calls'] and not any(c.startswith('tree:') for c in value['calls'])
    assert plan['schema'] == 'cochem-warden-retarget-plan/3' and plan['mode'] == 'READ_ONLY_PLAN' and plan['holds'] == [] and plan['tasks_changed'] == 0 and plan['started'] is False
    assert plan['expected_action'] == {'execute': R5_PY, 'arguments': R5_ARGS, 'working_directory': R5_ROOT}
    assert plan['expected_triggers'] == [{'type': 'logon', 'user_id': 'AETHERDESK\\ansac', 'delay': 'PT1M'}]
    assert plan['source']['source_state'] == 'r4-v1' and plan['config']['mode'] == 'GEMINI_CONTRACT' and plan['queue_launch_output_root'] == R5_QUEUE_ROOT
    assert plan['target_root'].endswith('WardenRetarget4.2.7-windows-20261011-r5-v1') and plan['backup_copy_rights_verified'] is None and plan['administrator'] is False
    assert not (tmp_path / 'CoChem' / 'WardenRetarget4.2.7-windows-20261011-r5-v1').exists()


def test_main_read_only_plan_for_r4_ignores_config_and_names_the_fresh_queue(tmp_path):
    value = run_main(tmp_path, "@{Target='r4';Config='C:\\anything.json';Attempt='v2'}")
    plan = value['plan']
    assert not value['failed'] and plan['holds'] == [] and plan['config_argument_ignored'] is True and 'parser' not in value['calls']
    queue = str(tmp_path / 'CoChem' / 'queue-restart-20261011-r4-v2')
    assert plan['expected_action'] == {'execute': R4_PY, 'arguments': f'-I -B -m cochem_pipeline daemon --config "{R4_RESTORE_CONFIG}" --queue-launch-output "{queue}"', 'working_directory': R4_ROOT}
    assert plan['expected_triggers'] == [] and plan['queue_launch_output_new'] == queue and plan['config']['path'] == R4_RESTORE_CONFIG and plan['config']['sha256'] == CONFIG_PIN


def test_main_plan_reports_holds_for_an_existing_queue_and_root(tmp_path):
    base = tmp_path / 'CoChem'
    (base / 'queue-restart-20261011-r4-v1').mkdir(parents=True)
    (base / 'WardenRetarget4.2.7-windows-20261011-r4-v1').mkdir()
    plan = run_main(tmp_path, "@{Target='r4'}")['plan']
    assert any('Retarget root already exists' in h for h in plan['holds']) and any('queue-observation directory already exists' in h for h in plan['holds'])


def test_main_apply_with_a_hold_changes_nothing(tmp_path):
    value = run_main(tmp_path, f"@{{Target='r5';Config='{ps(R5_CFG)}';Apply=$true;Start=$true}}", setup='$script:fixtureAdmin=$true;$script:r5BindingFails=$true;')
    assert value['failed'] and value['message'].startswith('Retarget is held. Nothing was changed:') and 'r5 runtime' in value['message']
    assert 'retarget' not in value['calls'] and 'start' not in value['calls'] and 'parser' not in value['calls']


def test_main_elevated_code_tree_failure_holds_and_skips_the_r5_parser(tmp_path):
    value = run_main(tmp_path, f"@{{Target='r5';Config='{ps(R5_CFG)}'}}", setup='$script:fixtureAdmin=$true;$script:treeFails=$true;')
    plan = value['plan']
    assert any('Code tree inspection of ' + R4_ROOT in h for h in plan['holds']) and any('Code tree inspection of ' + R5_ROOT in h for h in plan['holds'])
    assert 'parser' not in value['calls'] and plan['code_tree_verified'] is False and plan['backup_copy_rights_verified'] is True


def test_main_apply_start_retargets_then_starts_once_and_reports_the_start_receipt(tmp_path):
    value = run_main(tmp_path, f"@{{Target='r5';Config='{ps(R5_CFG)}';Apply=$true;Start=$true}}", setup='$script:fixtureAdmin=$true;')
    assert not value['failed'], value['message']
    assert value['calls'].count('retarget') == 1 and value['calls'].count('start') == 1 and value['calls'].index('retarget') < value['calls'].index('start')
    assert f'tree:{R4_ROOT}' in value['calls'] and f'tree:{R5_ROOT}' in value['calls']
    result = value['plan']
    assert result['schema'] == 'cochem-warden-retarget-result/3' and result['mode'] == 'RETARGET_AND_START' and result['status'] == 'WARDEN_R5_RUNNING_HEALTH_VERIFIED'
    assert result['retarget_status'] == 'WARDEN_RETARGETED_TO_R5_NOT_STARTED' and result['receipt_path'] == 'SR' and result['receipt_sha256'] == '2' * 64
    assert result['retarget_receipt_path'] == 'RR' and result['started'] is True and 'sddl' not in result and 'source' not in result
    assert result['retarget_enabled_after'] is False and result['enabled_by_start'] is True and result['enabled_after'] is True and result['enabled_before'] is True
    assert value['start_binding']['sddl'] == SDDL and value['start_binding']['receipt_sha256'] == '1' * 64


CONTINUATION_LIVE = ("@{Path=$script:fixtureR5Py;Arguments=$script:fixtureR5Args;WorkingDirectory=$script:fixtureR5Root;Triggers=@(New-FixtureTrigger -Enabled $false);"
                     "Enabled=$false;State=1;Description=(Get-TargetDescription 'r5' 'v1')}")


def continuation_setup(root: Path, description_attempt: str = 'v1') -> str:
    """A completed r5 retarget attempt v1 (its receipt, warden-task-after.xml and captured SDDL) for the stubbed main to continue."""
    return (f"$script:fixtureAdmin=$true;$script:Target='r5';$script:Attempt='v1';$ctx=New-FixtureContext 'r5';"
            f"$saved=$script:definition.RegistrationInfo.Description;$script:definition.RegistrationInfo.Description=(Get-TargetDescription 'r5' '{description_attempt}');"
            f"$afterSha=Write-FixtureText '{ps(root / 'warden-task-after.xml')}' (Get-FixtureXmlWith $false $false);$script:definition.RegistrationInfo.Description=$saved;"
            "$x=New-ReceiptHead 'cochem-warden-retarget/3' $ctx.retargeted_status $ctx ([ordered]@{source_state='r4-v1';source_attempt=$null;stop_attempt=$null}) $afterSha;$x['sddl_preserved']=$true;$x['enabled_after']=$false;$x['trigger_enabled_after']=$false;"
            "$x['task_xml_after_sha256']=$afterSha;"
            f"Write-FixtureJson '{ps(root / 'retarget-receipt.json')}' $x;[IO.File]::WriteAllText('{ps(root / 'warden-task-before.sddl')}','{SDDL}');")


def test_main_apply_start_on_a_retargeted_attempt_continues_with_the_start_only(tmp_path):
    root = tmp_path / 'CoChem' / 'WardenRetarget4.2.7-windows-20261011-r5-v1'
    value = run_main(tmp_path, f"@{{Target='r5';Config='{ps(R5_CFG)}';Apply=$true;Start=$true}}", setup=continuation_setup(root), live=CONTINUATION_LIVE)
    assert not value['failed'], value['message']
    assert 'retarget' not in value['calls'] and value['calls'].count('start') == 1
    result = value['plan']
    assert result['mode'] == 'START_ONLY' and result['continued_from_retarget_receipt'] is True and result['status'] == 'WARDEN_R5_RUNNING_HEALTH_VERIFIED'
    assert result['retarget_receipt_sha256'] == sha256_file(root / 'retarget-receipt.json') and result['receipt_path'] == 'SR' and result['receipt_sha256'] == '2' * 64
    assert value['start_binding']['source']['source_state'] == 'r4-v1' and value['start_binding']['sddl'] == SDDL
    assert result['enabled_after'] is True and result['enabled_by_start'] is True


def test_main_plan_restores_r4_from_an_r5_retarget_that_never_started(tmp_path):
    setup = "$script:base=$script:fixtureBase;$script:SourceAttempt='v1';Write-FixtureR5NeverStarted;"
    value = run_main(tmp_path, "@{Target='r4';Attempt='v1';SourceAttempt='v1'}", setup=setup, live='(Get-R5LiveOverrides)')
    plan = value['plan']
    assert not value['failed'] and plan['holds'] == [], plan['holds']
    assert plan['source']['source_state'] == 'r5-retarget-receipt' and plan['source']['source_attempt'] == 'v1' and plan['source']['stop_attempt'] is None
    assert plan['source']['source_start_evidence'] == 'NO_START' and plan['stop_attempt'] == '' and plan['expected_triggers'] == []
    (tmp_path / 'with-stop').mkdir()
    stopped = run_main(tmp_path / 'with-stop', "@{Target='r4';Attempt='v1';SourceAttempt='v1';StopAttempt='v1'}", setup=setup, live='(Get-R5LiveOverrides)')
    assert any('has no start receipt' in hold for hold in stopped['plan']['holds']), 'with -StopAttempt the same live r5 action is the r5-receipt source, which needs a start receipt'


def test_main_start_only_refuses_a_live_task_another_attempt_registered(tmp_path):
    """Re-audit R-F3 (sweep N4): the start-only plan binds the live task to THIS attempt's warden-task-after.xml."""
    root = tmp_path / 'CoChem' / 'WardenRetarget4.2.7-windows-20261011-r5-v1'
    other = CONTINUATION_LIVE.replace("Description=(Get-TargetDescription 'r5' 'v1')", "Description=(Get-TargetDescription 'r5' 'v2')")
    value = run_main(tmp_path, f"@{{Target='r5';Config='{ps(R5_CFG)}';StartOnly=$true}}", setup=continuation_setup(root), live=other)
    assert not value['failed'] and any('is not the task r5 attempt v1 registered' in h for h in value['plan']['holds']), value['plan']['holds']
    (tmp_path / 'named').mkdir()
    root2 = tmp_path / 'named' / 'CoChem' / 'WardenRetarget4.2.7-windows-20261011-r5-v1'
    named = run_main(tmp_path / 'named', f"@{{Target='r5';Config='{ps(R5_CFG)}';StartOnly=$true}}", setup=continuation_setup(root2, 'v2'), live=other)
    assert any('registration description of r5 attempt v1' in h for h in named['plan']['holds']), named['plan']['holds']
    applied = run_main(tmp_path / 'named', f"@{{Target='r5';Config='{ps(R5_CFG)}';Apply=$true;Start=$true}}", setup=continuation_setup(root2, 'v2'), live=other)
    assert applied['failed'] and 'registration description of r5 attempt v1' in applied['message'] and 'start' not in applied['calls']


def test_main_continuation_refuses_a_different_config(tmp_path):
    root = tmp_path / 'CoChem' / 'WardenRetarget4.2.7-windows-20261011-r5-v1'
    other_config = R5_CFG.replace('-r5-v1', '-r5-v2')
    value = run_main(tmp_path, f"@{{Target='r5';Config='{ps(other_config)}';Apply=$true;Start=$true}}", setup=continuation_setup(root), live=CONTINUATION_LIVE)
    assert value['failed'] and '-Config differs from the configuration this attempt was retargeted to' in value['message']
    assert 'start' not in value['calls'] and 'retarget' not in value['calls']


def test_main_start_only_plan_without_a_receipt_holds(tmp_path):
    value = run_main(tmp_path, "@{Target='r4';StartOnly=$true}")
    plan = value['plan']
    assert not value['failed'] and plan['start_only'] is True and any(h.startswith('Retarget receipt:') for h in plan['holds']) and 'start' not in value['calls']


# ----------------------------------------------------------------------------------------------- the real top level, plan mode only
# ps_toplevel_smoke.py runs the REAL script file (its param block, binding, script-scope parameter variables and main) in
# a throwaway Windows PowerShell 5.1 with every host command stubbed or denied; it refuses any argument that could bind
# -Apply before a process starts. The host is the 2026-10-11 AETHERDESK seen unelevated: the Warden task is unreadable,
# Program Files and ProgramData items are virtual (no readable ACL), so every reviewed protected read holds and the plan
# is a READ_ONLY_PLAN with holds - never a binding or engine error. This is the coverage that would have caught 17:22.

CUTOVER_DOC = ROOT / 'r5-army-specs' / 'INTERFACES-CUTOVER.md'
SITTING = ROOT / 'RUN_427_R5_SITTING.ps1'
RETARGET_PLAN_SCHEMA = 'cochem-warden-retarget-plan/3'
R5_CFG_V2 = R5_CFG.replace('-r5-v1', '-r5-v2')
# The attempt placeholders of INTERFACES-CUTOVER 'Calls': r5 attempt vN, r4-restore attempt vM, stop attempts vK / vK2.
DOC_PLACEHOLDERS = (('vK2', 'v2'), ('vN', 'v1'), ('vM', 'v2'), ('vK', 'v1'))
UNREADABLE_TASK_HOLD = 'Warden task definition is unreadable without elevation; re-read during -Apply.'
PRESENCE_HOLD = 'A controller process, an unclassified runtime process or the loopback port is alive; stop nothing, investigate.'


def _split_call(text: str) -> tuple:
    lexer = shlex.shlex(text, posix=False)
    lexer.whitespace_split = True
    return tuple(token[1:-1] if len(token) >= 2 and token[0] == token[-1] == '"' else token for token in lexer)


def documented_calls() -> list:
    """Every '.\\retarget-warden-r5.ps1 ...' call of INTERFACES-CUTOVER.md 'Calls', placeholders filled, in order, unique."""
    text = CUTOVER_DOC.read_text(encoding='utf-8')
    section = text.split('## Calls', 1)[1].split('\n## ', 1)[0]
    calls = []
    for match in re.finditer(r'\.\\retarget-warden-r5\.ps1 ([^\n]+)', section):
        line = match.group(1).strip()
        for placeholder, value in DOC_PLACEHOLDERS:
            line = re.sub(r'\b' + placeholder + r'\b', value, line)
        args = _split_call(line.replace('"<cfg>"', '"' + R5_CFG_V2 + '"'))
        if args not in calls:
            calls.append(args)
    return calls


def sitting_call(target: str, attempt: str, config: str = '', source: str = '', stop: str = '') -> tuple:
    """The argument vector RUN_427_R5_SITTING.ps1 Invoke-R5Retarget passes to 'powershell.exe -File' (its order, checked below)."""
    args = ['-Target', target] + (['-Config', config] if config else []) + ['-Attempt', attempt]
    args += (['-SourceAttempt', source] if source else []) + (['-StopAttempt', stop] if stop else [])
    return tuple(args + ['-Apply', '-Start'])


DOC_CALLS = documented_calls()
# 'Restored r4 back to r5 later' (given in prose, C-F3): from a stopped r4 restore vM (= v2), or one that never started.
PROSE_CALLS = [('-Target', 'r5', '-Config', R5_CFG, '-Attempt', 'v3', '-SourceAttempt', 'v2', '-StopAttempt', 'v2', '-Apply', '-Start'),
               ('-Target', 'r5', '-Config', R5_CFG, '-Attempt', 'v3', '-SourceAttempt', 'v2', '-Apply', '-Start')]
# The sitting's own child calls (S11 from either base, the S13 Gemini fallback, R4-RESTORE from every state reached).
SITTING_CALLS = [sitting_call('r5', 'v1', R5_CFG), sitting_call('r5', 'v1', R5_CFG, 'v2', 'v1'), sitting_call('r5', 'v2', COMMISSIONING_CONFIG, 'v1', 'v1'),
                 sitting_call('r4', 'v1'), sitting_call('r4', 'v2', '', 'v1'), sitting_call('r4', 'v2', '', 'v1', 'v1'), sitting_call('r4', 'v3', '', 'v2', 'v2')]
# The header's -StartOnly usage (start an attempt that already holds its retarget receipt).
START_ONLY_CALLS = [('-Target', 'r5', '-Attempt', 'v1', '-Apply', '-StartOnly'), ('-Target', 'r4', '-Attempt', 'v1', '-Apply', '-StartOnly')]


def _unique(calls) -> list:
    out = []
    for args in calls:
        if tuple(args) not in out:
            out.append(tuple(args))
    return out


def plan_args(args) -> tuple:
    return tuple(a for a in args if a.lower() not in ('-apply', '-start'))


ALL_DOCUMENTED = _unique(DOC_CALLS + PROSE_CALLS + SITTING_CALLS)
TOPLEVEL_PLAN_CALLS = _unique([plan_args(a) for a in ALL_DOCUMENTED + START_ONLY_CALLS])


def call_id(args) -> str:
    # A config path shows as its directory's dated tail (20261011-r5-v1, or 20261007-r3-v1 for the commissioning copy).
    return '_'.join(Path(a).parent.name.split('windows-')[-1] if '\\' in a else a.lstrip('-') for a in args)


def _arg(args, name):
    return args[args.index(name) + 1] if name in args else None


def expect_toplevel_plan(result: smoke.SmokeResult, args) -> dict:
    """A READ_ONLY_PLAN for exactly these arguments that changed nothing; raises the runner's verdict otherwise."""
    assert smoke.plan_mode_outcome(result, plan_schema=RETARGET_PLAN_SCHEMA) == 'plan', result.describe()
    plan = result.plan
    target, attempt = _arg(args, '-Target'), _arg(args, '-Attempt') or 'v1'
    assert plan['target'] == target and plan['attempt'] == attempt
    assert plan['source_attempt'] == (_arg(args, '-SourceAttempt') or '') and plan['stop_attempt'] == (_arg(args, '-StopAttempt') or '')
    assert plan['start_only'] is ('-StartOnly' in args) and plan['continued_from_retarget_receipt'] is False
    assert plan['target_root'] == rf'C:\Program Files\CoChem\WardenRetarget4.2.7-windows-20261011-{target}-{attempt}'
    assert plan['tasks_changed'] == 0 and plan['started'] is False and plan['automatic_retry_allowed'] is False and plan['administrator'] is False
    assert plan['task_readable'] is False and plan['source'] is None and UNREADABLE_TASK_HOLD in plan['holds'], plan['holds']
    assert not result.calls(kind='denied') and result.trace, 'every host question was answered by a stub'
    return plan


def test_sitting_retarget_calls_use_the_argument_order_modelled_here():
    text = SITTING.read_text(encoding='ascii')
    body = text[text.index('function Invoke-R5Retarget '):]
    body = body[:body.index('\nfunction ')]
    for line in ("$arguments=@('-Target','r5')", "$arguments=@('-Target','r4')", "if($Config){$arguments+=@('-Config',$Config)}",
                 "$arguments+=@('-Attempt',$TargetAttempt)", "if($SourceAttempt){$arguments+=@('-SourceAttempt',$SourceAttempt)}",
                 "if($StopAttempt){$arguments+=@('-StopAttempt',$StopAttempt)}", "$arguments+=@('-Apply','-Start')"):
        assert line in body, line
    assert "'retarget-warden-r5.ps1' $arguments" in body


def test_documented_calls_are_found_and_cover_every_source_shape():
    assert len(DOC_CALLS) >= 7, DOC_CALLS
    assert ('-Target', 'r4', '-Attempt', 'v1', '-Apply', '-Start') in DOC_CALLS, 'R4-RESTORE if S11 never applied (the 17:22 call)'
    assert ('-Target', 'r5', '-Config', R5_CFG, '-Attempt', 'v1', '-Apply', '-Start') in DOC_CALLS, 'S11'
    shapes = {('-SourceAttempt' in a, '-StopAttempt' in a, _arg(a, '-Target')) for a in TOPLEVEL_PLAN_CALLS}
    assert shapes >= {(False, False, 'r5'), (False, False, 'r4'), (True, False, 'r5'), (True, False, 'r4'), (True, True, 'r5'), (True, True, 'r4')}, shapes
    assert all(smoke.apply_argument(args) is None for args in TOPLEVEL_PLAN_CALLS)


@pytest.mark.parametrize('args', [pytest.param(a, id=call_id(a)) for a in ALL_DOCUMENTED])
def test_toplevel_documented_call_without_apply_is_refused_before_anything_is_read(args):
    # The documented calls keep -Start; without -Apply the parameter rules refuse before the host is touched at all.
    result = smoke.run_toplevel(SCRIPT, tuple(a for a in args if a != '-Apply'))
    assert smoke.plan_mode_outcome(result) == 'refusal', result.describe()
    assert result.error.message == '-Start is only meaningful together with -Apply.' and result.trace == ()


@pytest.mark.parametrize('invocation', ['file', 'command'])
@pytest.mark.parametrize('args', [pytest.param(a, id=call_id(a)) for a in TOPLEVEL_PLAN_CALLS])
def test_toplevel_plan_of_every_documented_call(args, invocation):
    """'file' is how the sitting starts it (powershell.exe -File); 'command' is the owner typing the line at a console."""
    expect_toplevel_plan(smoke.run_toplevel(SCRIPT, args, invocation=invocation), args)


TOPLEVEL_REFUSALS = {
    # Without [Validate*] attributes on the parameters, Assert-RetargetParameters is the one (case-sensitive) validation, and
    # every invalid value is a clean refusal before anything is read.
    'target_upper': (('-Target', 'R5', '-Config', R5_CFG, '-Attempt', 'v1'), 'Choose -Target r5 (cutover) or -Target r4 (restore); nothing was changed.'),
    'target_other': (('-Target', 'r6', '-Attempt', 'v1'), 'Choose -Target r5 (cutover) or -Target r4 (restore); nothing was changed.'),
    'target_missing': (('-Attempt', 'v1'), 'Choose -Target r5 (cutover) or -Target r4 (restore); nothing was changed.'),
    'attempt_upper': (('-Target', 'r4', '-Attempt', 'V1'), '-Attempt must be v followed by 1-3 digits; nothing was changed.'),
    'attempt_empty': (('-Target', 'r4', '-Attempt', ''), '-Attempt must be v followed by 1-3 digits; nothing was changed.'),
    'attempt_long': (('-Target', 'r4', '-Attempt', 'v1000'), '-Attempt must be v followed by 1-3 digits; nothing was changed.'),
    'source_upper': (('-Target', 'r4', '-Attempt', 'v2', '-SourceAttempt', 'V1'), '-SourceAttempt must be v followed by 1-3 digits; nothing was changed.'),
    'source_digits': (('-Target', 'r4', '-Attempt', 'v2', '-SourceAttempt', '1'), '-SourceAttempt must be v followed by 1-3 digits; nothing was changed.'),
    'stop_suffix': (('-Target', 'r4', '-Attempt', 'v2', '-SourceAttempt', 'v1', '-StopAttempt', 'v1x'), '-StopAttempt must be v followed by 1-3 digits; nothing was changed.'),
    'stop_without_source': (('-Target', 'r4', '-Attempt', 'v2', '-StopAttempt', 'v1'), '-StopAttempt needs -SourceAttempt (the attempt the stop receipt names). Nothing was changed.'),
    'r5_without_config': (('-Target', 'r5', '-Attempt', 'v1'), '-Target r5 requires -Config <staged r5 pipeline.json>; nothing was changed.'),
    'start_only_with_source': (('-Target', 'r4', '-Attempt', 'v2', '-StartOnly', '-SourceAttempt', 'v1'), '-StartOnly continues an existing attempt from its receipt'),
}


@pytest.mark.parametrize('case', sorted(TOPLEVEL_REFUSALS))
def test_toplevel_invalid_arguments_are_clean_refusals_before_anything_is_read(case):
    args, message = TOPLEVEL_REFUSALS[case]
    result = smoke.run_toplevel(SCRIPT, args)
    assert smoke.plan_mode_outcome(result) == 'refusal', result.describe()
    assert result.error.message.startswith(message) and result.trace == (), result.describe()


def test_toplevel_explicitly_empty_attempts_are_the_omitted_ones():
    # '' is what the sitting never passes but an owner might type; it selects the same source as omitting the parameter.
    args = ('-Target', 'r4', '-Attempt', 'v1', '-SourceAttempt', '', '-StopAttempt', '')
    plan = expect_toplevel_plan(smoke.run_toplevel(SCRIPT, args), ('-Target', 'r4', '-Attempt', 'v1'))
    assert plan['source_attempt'] == '' and plan['stop_attempt'] == ''


LIVE_CLIENT_CALLS = [plan_args(sitting_call('r4', 'v1')), plan_args(sitting_call('r5', 'v1', R5_CFG)), plan_args(sitting_call('r4', 'v2', '', 'v1', 'v1'))]


@pytest.mark.parametrize('args', [pytest.param(a, id=call_id(a)) for a in LIVE_CLIENT_CALLS])
def test_toplevel_plan_counts_the_live_owner_mcp_clients_and_antigravity_bridges_as_clients(args):
    """The 17:22 host: 10 'cochem_pipeline mcp' clients and 4 Antigravity 'cochem_mcp' bridges, nothing on 47824 - the
    bridges held S2 as unclassified runtime processes and would hold S11 and every R4-RESTORE the same way."""
    stub = smoke.default_stub()
    stub['processes'] = smoke.live_mcp_clients_20261011()
    plan = expect_toplevel_plan(smoke.run_toplevel(SCRIPT, args, stub=stub), args)
    presence = plan['controller_presence']
    assert presence['listening'] == 0 and presence['controller_processes'] == [] and presence['unclassified_runtime_processes'] == []
    assert sorted(p['pid'] for p in presence['client_processes']) == sorted(p['pid'] for p in stub['processes'])
    assert len([p for p in presence['client_processes'] if ' -m cochem_mcp --provider ' in p['command']]) == 4
    assert PRESENCE_HOLD not in plan['holds'] and not any('unclassified runtime process' in h for h in plan['holds']), plan['holds']


def test_toplevel_plan_still_holds_on_a_bridge_near_miss_beside_the_live_clients():
    stub = smoke.default_stub()
    stub['processes'] = smoke.live_mcp_clients_20261011() + [
        {'pid': 30000, 'parent_pid': 29188, 'name': 'python.exe', 'path': R4_PY, 'command_line': bridge_command(R4_PY, 'gemini'),
         'owner': 'AETHERDESK\\ansac', 'created_utc': '2026-10-11T16:00:00Z'},
        {'pid': 30004, 'parent_pid': 29188, 'name': 'python.exe', 'path': BASE_PY, 'command_line': bridge_command(BASE_PY, head='-I -B -m cochem_mcp'),
         'owner': 'AETHERDESK\\ansac', 'created_utc': '2026-10-11T16:00:01Z'}]
    args = plan_args(sitting_call('r4', 'v1'))
    plan = expect_toplevel_plan(smoke.run_toplevel(SCRIPT, args, stub=stub), args)
    presence = plan['controller_presence']
    assert sorted(p['pid'] for p in presence['unclassified_runtime_processes']) == [30000, 30004] and len(presence['client_processes']) == 14
    assert PRESENCE_HOLD in plan['holds'], plan['holds']
