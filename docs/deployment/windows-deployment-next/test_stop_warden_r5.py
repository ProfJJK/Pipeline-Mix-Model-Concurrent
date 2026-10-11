"""Inert Windows PowerShell 5.1 harness for stop-warden-r5.ps1 (r5 rollback / Gemini-fallback stop).

Nothing here reads a real task, ends, disables, enables or starts anything, contacts the live controller or runs the
script top level directly (never with -Apply; the only top-level runs are the plan-mode smoke tests at the end, through
ps_toplevel_smoke.py, which stubs the host and refuses -Apply before any process starts). The script's functions are extracted from its AST into
a throwaway powershell.exe and driven with stubs for every system call: the Task Scheduler COM folder and task (Stop, the
Enabled setter, GetInstances, the trigger collection), Get-CimInstance, Get-NetTCPConnection, Invoke-CimMethod, the
loopback bind probe, the worker sweep, the reviewed protected-path helpers (Read-R3Control, New-ProtectedDirectory,
Write-RegistrationControl, Assert-CodeTreeOnce) and Start-Sleep. The r5 runtime, its install receipt and the r5 start
receipt are fixtures in pytest temporary directories; every C:\\Program Files\\CoChem path is redirected there by the
Read-R3Control stub. The two Python snippets run against an in-process loopback HTTP server only.
Test bodies are written to a temporary file and dot-sourced, so no body is limited by the command-line length.
The audit fixes (C-F1(b) -RecoverInterruptedStart, C-F4 freeze pins, C-F5 task XML binding) are covered with the same fixtures;
retarget-warden-r5.ps1's start-held writer and source lineage run the same inert way (its functions from its AST) to prove
both directions of the cutover interface.

2026-10-11 17:22 sitting fixes, each proved by a test that failed first:
- Read-StartReceipt kept its start-held record in a local named $held. The reviewed Read-R3Control (imported by hash from
  check-worker-native-status-r3.ps1) adds every stream to $held by dynamic scope, so it found that local ($null, or the record)
  instead of the main's stream list and every bound read threw 'You cannot call a method on a null-valued expression': every
  plan and -Apply held at 'start receipt'. The Read-R3Control stub now touches $held as the real one does, one test runs the
  real Read-R3Control, and a static rule forbids any function but the main to assign a variable a reviewed helper reads freely.
- Get-ControllerPresence left the four Antigravity bridge MCP clients ('<runtime python> -m cochem_mcp --provider codex|claude
  --config C:\\Users\\ansac\\CoChem427\\bridge.local.json') unclassified, so every stop held on them. The presence table, the
  plan and -Apply sessions over the 14 live MCP clients and the top-level smoke tests run the REAL Get-ControllerPresence.
"""
import hashlib
import http.server
import itertools
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading

import pytest

import ps_toplevel_smoke as smoke

ROOT = Path(__file__).parent
SCRIPT = ROOT / 'stop-warden-r5.ps1'
STOP_R4 = ROOT / 'stop-warden-r4.ps1'
STOP_R4_SHA256 = 'bd54cb8194d256109aa8dae95451b87780566f7094f26f52d251840944bbc71b'
V22 = ROOT / 'retarget-warden-r4.ps1'
V22_SHA256 = '8ee6b412f6be176dfac7c2c1b2340f1973e08358c7d22da6d4515e79f0327a4e'
REGISTER = ROOT / 'register-stopped-warden-r3.ps1'
SPEC = ROOT / 'r5-army-specs' / 'deploy-stop-warden-r5.json'
ADDENDUM = ROOT / 'r5-army-specs' / 'ARMY_ADDENDUM_20261011.md'

COCHEM = r'C:\Program Files\CoChem'
R3_ROOT = COCHEM + r'\Pipeline4.2.7-windows-20261007-r3'
R4_ROOT = COCHEM + r'\Pipeline4.2.7-windows-20261009-r4'
R4_PY = R4_ROOT + r'\.venv\Scripts\python.exe'
R5_ROOT = COCHEM + r'\Pipeline4.2.7-windows-20261011-r5'
R5_PY = R5_ROOT + r'\.venv\Scripts\python.exe'
R5_SOURCE = R5_ROOT + r'\.venv\Lib'
BASE_ROOT = COCHEM + r'\Toolchain4.2.7-windows-20261006\Python312'
BASE_PY = BASE_ROOT + r'\python.exe'
R5_CONFIG = COCHEM + r'\WardenConfig4.2.7-windows-20261011-r5-v1\pipeline.json'
HELD_CONFIG = COCHEM + r'\WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json'
QUEUE_ROOT = r'C:\ProgramData\CoChemPipeline427\private\queue-launch-r5'
QUEUE_R4V1 = r'C:\ProgramData\CoChemPipeline427\private\queue-retarget-20261010-r4-v1'
RETARGET_ROOT = COCHEM + r'\WardenRetarget4.2.7-windows-20261011-r5-v3'
START_RECEIPT = RETARGET_ROOT + r'\start-receipt.json'
STOP_ROOT_V1 = COCHEM + r'\WardenStop4.2.7-windows-20261011-r5-v1'
CLIENT_CONFIG = r'C:\Users\ansac\CoChem427\pipeline-client-r3.json'
TOKEN_FILE = r'C:\Users\ansac\CoChem427\controller.token'
R4_INSTALL_PIN = '629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502'
R4_MANIFEST_PIN = '1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189'
R4_REVISION_PIN = '38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e'
R3_REVISION_PIN = '309eb48d9b1c43179ae1f0784d0139357168314f8312a64fb84dbd8380d44eb4'
CONFIG_PIN = '135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
BASE_PY_PIN = 'd8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa'
SDDL = 'O:BAG:BAD:PAI(A;;FA;;;SY)(A;;FA;;;BA)'
REPAIRS = sorted(['src/cochem_pipeline/__main__.py', 'src/cochem_pipeline/agy_protocol.py', 'src/cochem_pipeline/coding.py', 'src/cochem_pipeline/config.py',
                  'src/cochem_pipeline/controller_guard.py', 'src/cochem_pipeline/failures.py', 'src/cochem_pipeline/knowledge.py', 'src/cochem_pipeline/operator_views.py',
                  'src/cochem_pipeline/runtime.py', 'src/cochem_pipeline/service.py', 'src/cochem_pipeline/store.py', 'src/cochem_pipeline/worker.py',
                  'src/cochem_supervisor/runner.py'])


def r5_args(config=R5_CONFIG):
    return f'-I -B -m cochem_pipeline daemon --config "{config}" --queue-launch-output-root "{QUEUE_ROOT}" --docker-wait-seconds 900'


R5_ARGS = r5_args()
R4V1_ARGS = f'-I -B -m cochem_pipeline daemon --config "{HELD_CONFIG}" --queue-launch-output "{QUEUE_R4V1}"'
TASK_XML = ('<?xml version="1.0" encoding="UTF-16"?><Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
            '<RegistrationInfo><SecurityDescriptor>O:BAG:BAD:PAI(A;;FA;;;SY)(A;;FA;;;BA)</SecurityDescriptor><Description>Reviewed r5 retarget v3 (reboot-safe logon trigger) '
            'of the r4 retarget task. Logon trigger only, no retries; preserve on any failure.</Description><URI>\\CoChem-4.2.7-Warden</URI></RegistrationInfo>'
            '<Principals><Principal id="Author"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>'
            '<Settings><DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy></Settings>'
            '<Triggers><LogonTrigger><Enabled>true</Enabled><UserId>AETHERDESK\\ansac</UserId><Delay>PT1M</Delay></LogonTrigger></Triggers>'
            '<Actions Context="Author"><Exec><Command>c</Command></Exec></Actions></Task>')
TASK_XML_DISABLED = TASK_XML.replace('<Settings>', '<Settings><Enabled>false</Enabled>')
# Two-phase r5 start (C-F1): retarget-warden-r5 registers the task and its logon trigger disabled (warden-task-after.xml);
# -Start enables the task, Runs, and enables the trigger only after the health gate (warden-task-started.xml == TASK_XML).
SOURCE_XML = TASK_XML_DISABLED.replace('<LogonTrigger><Enabled>true', '<LogonTrigger><Enabled>false')
LIVE_XML_TRIGGER_OFF = TASK_XML.replace('<LogonTrigger><Enabled>true', '<LogonTrigger><Enabled>false')
TRIGGER_OFF = "Triggers=@(@{Type=9;UserId='AETHERDESK\\ansac';Delay='PT1M';Enabled=$false})"
R5_MANIFEST_PIN = '5d8d337baebbc1e4ac29439d418333ab41c0999eb8c0ef8b02acee66850a3045'
R5_SOURCE_COMMIT = '8554c7645801a7bc9c4abad4861bfcbe4ed014b0'
PYVENV_PIN = '0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d'
VENV_PYTHON_PIN = '560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'

REUSED_V22 = ['Import-ReviewedFunctions', 'Invoke-NativeJudged', 'Get-ExpectedArguments', 'Test-ExactBool', 'Test-ExactInt', 'Assert-R4InstalledBindings',
              'Get-WardenTaskState', 'Get-OtherDaemonTaskStates', 'Assert-OtherDaemonsIdle', 'Test-ControllerAlive', 'Test-LoopbackFree', 'Get-WorkerProcesses',
              'Assert-NoWorkers']
REUSED_STOP_R4 = ['Get-JsonListField', 'Get-JobIdText', 'Assert-StopSource', 'Get-TaskXmlOutsideEnabled', 'Assert-StopDisabledTask', 'Get-IdleEvidence',
                  'Get-ProcessCreationUtc', 'Get-LastBootUtc', 'Get-ProofProcesses', 'Assert-OnlyProvenController', 'Test-ProcessInstancePresent',
                  'Get-ExitObservation', 'Wait-WardenExit']
EXPECTED_NAMES = ['Import-ReviewedFunctions', 'Invoke-NativeJudged', 'Get-ExpectedArguments', 'Test-ExactBool', 'Test-ExactInt', 'Assert-R4InstalledBindings',
                  'Assert-R4Pins', 'Get-WardenTaskState', 'Get-OtherDaemonTaskStates',
                  'Assert-OtherDaemonsIdle', 'Get-ControllerPresence', 'Test-ControllerAlive', 'Test-LoopbackFree', 'Get-WorkerProcesses', 'Assert-NoWorkers',
                  'Set-StopConstants', 'Get-R5ExpectedArguments', 'Get-TaskXmlSha256', 'Assert-ApplyIdentity', 'Get-FieldValue', 'Get-StringField',
                  'Get-JsonListField', 'Get-JobIdText', 'Test-RepairList', 'Test-SameStringSet', 'Get-AccountSid', 'Test-SameAccount', 'Assert-ClientConfig',
                  'Read-BoundJson', 'Assert-AttemptReceiptHead',
                  'Get-TaskXmlTriggerFlags', 'Get-TaskXmlOutsideEnabledFlags', 'Read-StartReceipt', 'Assert-R5InstalledBindings',
                  'Assert-TargetRuntimeBindings', 'Get-TaskTriggerSet', 'Get-RunningInstanceEvidence', 'Assert-StopDefinition', 'Assert-StopSource', 'Get-StopMode',
                  'Get-TaskXmlOutsideEnabled', 'Assert-StopDisabledTask', 'Get-HealthSample', 'Test-IdlePredicate', 'Get-OperatorSnapshot', 'Get-IdleEvidence', 'Wait-WardenIdle',
                  'Get-ProcessCreationUtc', 'Get-LastBootUtc', 'Get-StopProcessProof', 'Get-ProofProcesses', 'Assert-OnlyProvenController',
                  'Test-ProcessInstancePresent', 'Get-ExitObservation', 'Wait-WardenExit', 'New-StopRoot', 'Get-TriggerStateBasis', 'Invoke-StopWarden', 'Invoke-StopWardenSession',
                  'Invoke-StopWardenMain']
COUNTER = itertools.count()
# Get-ControllerPresence's GUI-client line in v2.2, and the 2026-10-11 17:22 fix shared with stop-warden-r4.ps1: a rooted
# process whose command line is exactly '"<...\python.exe>" -m cochem_mcp --provider codex|claude --config <the owner's
# bridge.local.json>' (the Antigravity bridge entries, pure loopback clients of the job board) is a client too.
OLD_CLIENT_LINE = (r"elseif($rooted -and $command -match 'cochem_pipeline\s+(mcp|health|status|submit|cancel|projects|code|code-status|code-cancel|"
                   r"code-resume|knowledge-\w+)\b'){$clients+=$entry}")
NEW_CLIENT_LINE = (r"elseif($rooted -and ($command -match 'cochem_pipeline\s+(mcp|health|status|submit|cancel|projects|code|code-status|code-cancel|"
                   r"code-resume|knowledge-\w+)\b' -or $command -cmatch '^" + '"[^"]+' + r"\\python\.exe" + '"' +
                   r" -m cochem_mcp --provider (codex|claude) --config C:\\Users\\ansac\\CoChem427\\bridge\.local\.json\z')){$clients+=$entry}")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def ps(value):
    return str(value).replace("'", "''")


PRELUDE = r'''$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
foreach($m in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$m\$m.psd1")}
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('SCRIPTPATH',[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
foreach($f in $ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){. ([scriptblock]::Create($f.Extent.Text))}
$regAst=[Management.Automation.Language.Parser]::ParseFile('REGPATH',[ref]$tokens,[ref]$errors)
foreach($f in $regAst.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Assert-RegisteredTaskAcl'},$true)){. ([scriptblock]::Create($f.Extent.Text))}
$script:Attempt='v1';$script:RetargetAttempt='v3';$script:RetargetTarget='r5';$script:RecoverInterruptedStart=$false;$script:IdleWaitSeconds=30;$script:ExitWaitSeconds=9;Set-StopConstants;$script:admin=$false
$held=[Collections.Generic.List[IO.FileStream]]::new()
'''.replace('SCRIPTPATH', ps(SCRIPT)).replace('REGPATH', ps(REGISTER))


def run_ps(body, workdir, prelude=True, timeout=300):
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / f'body-{next(COUNTER)}.ps1'
    path.write_text((PRELUDE if prelude else "$ErrorActionPreference='Stop';Set-StrictMode -Version Latest\n") + body, encoding='utf-8')
    command = "$ErrorActionPreference='Stop';. ([scriptblock]::Create([IO.File]::ReadAllText('" + ps(path) + "')))"
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, text=True, timeout=timeout)


def run_json(body, workdir, prelude=True, timeout=300):
    result = run_ps(body, workdir, prelude, timeout)
    assert result.returncode == 0, result.stderr[-6000:]
    return json.loads(result.stdout)


# --------------------------------------------------------------------------------------------------------------------
# Fixtures shared by the PowerShell bodies
# --------------------------------------------------------------------------------------------------------------------

def bound_evidence(root, binding, source_xml, started_xml, allowed, start_sha):
    """The Read-StartReceipt results Invoke-StopWarden and the live checks consume, set directly (no files)."""
    started = "$null" if started_xml is None else "'" + ps(started_xml) + "'"
    path = "$null" if start_sha is None else "'" + ps(root + r'\start-receipt.json') + "'"
    return (f"$script:startBinding='{binding}';$script:sourceTaskXml='{ps(source_xml)}';$script:startedTaskXml={started};$script:allowedTriggerEnabled=@({allowed})\n"
            f"$startReceipt=[ordered]@{{binding='{binding}';path={path};sha256={'$null' if start_sha is None else repr(start_sha)};"
            f"retarget_receipt_path='{ps(root)}\\retarget-receipt.json';retarget_receipt_sha256=('1'*64);start_intent_path='{ps(root)}\\start-intent.json';start_intent_sha256=('2'*64);"
            f"start_held_path=$null;start_held_sha256=$null;held_trigger_enabled_after=$null;source_task_xml_after_path='{ps(root)}\\warden-task-after.xml';"
            f"source_task_xml_after_sha256=('3'*64);source_task_xml_started_sha256={'$null' if started_xml is None else repr('4' * 64)}}}\n")


BOUND = r'''
$script:runtimeRoot='R5ROOT';$script:runtimePython='R5PY';$script:runtimeSourceRoot='R5SOURCE'
$script:expectedAction=[ordered]@{execute='R5PY';arguments='R5ARGS';working_directory='R5ROOT'}
$script:expectedTriggers=@([ordered]@{type='logon';user_id='AETHERDESK\ansac';delay='PT1M'})
$bindings=[ordered]@{runtime='r5';install_after_sha256=('a'*64);task_config_sha256=('c'*64)}
'''.replace('R5ROOT', R5_ROOT).replace('R5PY', R5_PY).replace('R5SOURCE', R5_SOURCE).replace('R5ARGS', R5_ARGS) + \
    bound_evidence(RETARGET_ROOT, 'START_RECEIPT', SOURCE_XML, TASK_XML, '$true', 'e' * 64)
# An interrupted or crashed start (C-F1(b)) bound through the attempt's retarget receipt: no start receipt, no started XML.
BOUND_CRASHED = BOUND + bound_evidence(RETARGET_ROOT, 'START_CRASHED_NO_RECORD', SOURCE_XML, None, '$true,$false', None)

# The r4 restore written by retarget-warden-r5.ps1 -Target r4 (New-TargetContext 'r4', sha b3678ee1...).
R4_SOURCE = R4_ROOT + r'\.venv\Lib'
R4_RESTORE_CONFIG = R4_ROOT + r'\pipeline.json'
RETARGET_ROOT_R4 = COCHEM + r'\WardenRetarget4.2.7-windows-20261011-r4-v3'
START_RECEIPT_R4 = RETARGET_ROOT_R4 + r'\start-receipt.json'
REPAIR_PIN = 'e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc'
R3_MANIFEST_PIN = '6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1'
R3_INSTALL_PIN = '3b613128192ac44a0a3d9c4b4476fb4c47541edb7563541b9bbf18f84f9a90f6'


def queue_restart(attempt='v3'):
    return rf'C:\ProgramData\CoChemPipeline427\private\queue-restart-20261011-r4-{attempt}'


def r4_restore_args(attempt='v3'):
    return f'-I -B -m cochem_pipeline daemon --config "{R4_RESTORE_CONFIG}" --queue-launch-output "{queue_restart(attempt)}"'


R4_RESTORE_ARGS = r4_restore_args()
TASK_XML_R4 = TASK_XML.replace('<Triggers><LogonTrigger><Enabled>true</Enabled><UserId>AETHERDESK\\ansac</UserId><Delay>PT1M</Delay></LogonTrigger></Triggers>',
                               '<Triggers />').replace('Reviewed r5 retarget v3 (reboot-safe logon trigger) of the r4 retarget task. Logon trigger only, no retries;',
                                                       'Reviewed r4 restart v3 after the r5 sitting. No triggers/retries;')
TASK_XML_R4_DISABLED = TASK_XML_R4.replace('<Settings>', '<Settings><Enabled>false</Enabled>')
R4_TASK = ("@{Path='" + R4_PY + "';Arguments='" + R4_RESTORE_ARGS + "';WorkingDirectory='" + R4_ROOT + "';Triggers=@();Xml='" + TASK_XML_R4 + "'")
BOUND_R4 = r'''
$script:RetargetTarget='r4';Set-StopConstants
$script:runtimeRoot='R4ROOT';$script:runtimePython='R4PY';$script:runtimeSourceRoot='R4SOURCE'
$script:expectedAction=[ordered]@{execute='R4PY';arguments='R4ARGS';working_directory='R4ROOT'}
$script:expectedTriggers=@()
$bindings=[ordered]@{runtime='r4';install_receipt_sha256='R4INSTALL';revision_sha256='R4REVISION';task_config_sha256='CONFIGPIN'}
'''.replace('R4ROOT', R4_ROOT).replace('R4PY', R4_PY).replace('R4SOURCE', R4_SOURCE).replace('R4ARGS', R4_RESTORE_ARGS) \
   .replace('R4INSTALL', R4_INSTALL_PIN).replace('R4REVISION', R4_REVISION_PIN).replace('CONFIGPIN', CONFIG_PIN) + \
    bound_evidence(RETARGET_ROOT_R4, 'START_RECEIPT', TASK_XML_R4_DISABLED, TASK_XML_R4, '', 'f' * 64)

# Re-audit R-F2: account lookups are stubbed (the copies of retarget-warden-r5's Get-AccountSid/Test-SameAccount are compared
# byte for byte, and resolved for real on this host, in their own test): the owner in any spelling or as the SID read back by
# Task Scheduler is S-1-5-21-9-9-9-1001; AETHERDESK\other is another account; anything else does not resolve.
SID_STUB = r'''
function Get-AccountSid {param([string]$Name)
  if([string]::Equals($Name,'AETHERDESK\ansac',[StringComparison]::OrdinalIgnoreCase) -or $Name -ceq 'S-1-5-21-9-9-9-1001'){return 'S-1-5-21-9-9-9-1001'}
  if([string]::Equals($Name,'AETHERDESK\other',[StringComparison]::OrdinalIgnoreCase)){return 'S-1-5-21-9-9-9-2002'}
  if($Name -cmatch '^S-1-[0-9]+(-[0-9]+)+$'){return $Name}
  $null}
'''

TASK_FIXTURE = SID_STUB + r'''
$script:stops=0;$script:stopFlags=$null;$script:events=@();$script:enabledWrites=@();$script:sleeps=@();$script:foreignPids=@();$script:loopbackProbes=0
$script:presenceCalls=0;$script:listenAtCall=0;$script:trace=@()
function New-TriggerCollection {param($Items)
  $collection=[pscustomobject]@{Count=@($Items).Count;List=@($Items)};$collection|Add-Member ScriptMethod Item {param($i)@($this.List)[$i-1]};$collection}
function New-FixtureFolder {param([hashtable]$Overrides)
  $v=@{Enabled=$true;State=4;Instances=1;LastTaskResult=267009;UserId='S-1-5-18';LogonType=5;RunLevel=1;Actions=1;MultipleInstances=2;ExecutionTimeLimit='PT0S';RestartCount=0;AllowDemandStart=$true;
       ActionType=0;Path='R5PYVALUE';Arguments='R5ARGSVALUE';WorkingDirectory='R5ROOTVALUE';Sddl='SDDLVALUE';Xml='XMLVALUE';DenyGetTask=$false;AbsentTask=$false;
       Triggers=@(@{Type=9;UserId='AETHERDESK\ansac';Delay='PT1M';Enabled=$true});
       StopThrows=$false;StopEffective=$true;PidSurvives=$false;PortListenerRemains=$false;ExclusiveBindRefused=$false;WorkerSurvives=$false;
       DisableChangesXml=$false;DisableSddl='';DisableChangesTrigger=$false;DenyAfterDisable=$false;ReceiptCollision=$false;ChangeXmlOnIntent=$false}
  foreach($k in $Overrides.Keys){$v[$k]=$Overrides[$k]}
  $script:fx=$v;$script:fxEnabled=[bool]$v.Enabled;$script:instances=$v.Instances
  $running=($v.State -eq 4);$script:portListening=$(if($running){1}else{0});$script:portFree=(-not $running);$script:alivePids=$(if($running){@(20664,5320)}else{@()});$script:workerPids=@()
  $script:action=[pscustomobject]@{Type=$v.ActionType;Path=$v.Path;Arguments=$v.Arguments;WorkingDirectory=$v.WorkingDirectory}
  $actions=[pscustomobject]@{Count=$v.Actions};$actions|Add-Member ScriptMethod Item {param($i)$script:action}
  $script:fxTriggers=@(@($v.Triggers)|ForEach-Object {[pscustomobject]$_})
  $definition=[pscustomobject]@{Principal=[pscustomobject]@{UserId=$v.UserId;LogonType=$v.LogonType;RunLevel=$v.RunLevel};Triggers=(New-TriggerCollection $script:fxTriggers);Actions=$actions;
    Settings=[pscustomobject]@{MultipleInstances=$v.MultipleInstances;ExecutionTimeLimit=$v.ExecutionTimeLimit;RestartCount=$v.RestartCount;AllowDemandStart=$v.AllowDemandStart}}
  $script:task=[pscustomobject]@{State=$v.State;LastTaskResult=$v.LastTaskResult;Xml=$v.Xml;Definition=$definition}
  $script:task|Add-Member ScriptProperty Enabled {$script:fxEnabled} {param($value)
    $script:events+='disable';$script:enabledWrites+=[pscustomobject]@{value=$value;instances=$script:instances;state=$script:task.State;port_listening=$script:portListening;port_free=$script:portFree;alive=@($script:alivePids).Count}
    $script:fxEnabled=[bool]$value
    if(-not $value){$script:task.State=1
      $script:task.Xml=$script:task.Xml.Replace('<Settings>','<Settings><Enabled>false</Enabled>')
      if($script:fx.DisableChangesXml){$script:task.Xml=$script:task.Xml.Replace('IgnoreNew','Parallel')}
      if($script:fx.DisableSddl){$script:fx.Sddl=$script:fx.DisableSddl}
      if($script:fx.DisableChangesTrigger){@($script:fxTriggers)[0].Delay='PT5M'}
      if($script:fx.DenyAfterDisable){$script:fx.DenyGetTask=$true}
      if($script:fx.ReceiptCollision){[IO.File]::WriteAllText((Join-Path $script:targetRoot 'stop-receipt.json'),'{}')}}}
  $script:task|Add-Member ScriptMethod GetInstances {param($n)$c=[pscustomobject]@{Count=$script:instances};$c|Add-Member ScriptMethod Item {param($i)[pscustomobject]@{InstanceGuid='{0F5A2C3E-0000-4000-8000-000000000005}';EnginePID=5320}};$c}
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
    if($script:fx.AbsentTask -or $name -ne 'CoChem-4.2.7-Warden'){throw [Runtime.InteropServices.COMException]::new('absent',-2147024894)};$script:task}
  $folder}
'''.replace('R5PYVALUE', R5_PY).replace('R5ARGSVALUE', R5_ARGS).replace('R5ROOTVALUE', R5_ROOT).replace('SDDLVALUE', SDDL).replace('XMLVALUE', TASK_XML)

STUBS = r'''
$script:otherActive=$false;$script:proofGone=$false;$script:notIdle=$false;$script:idleEvaluations=0;$script:workerPlan=@();$script:workerSweeps=0;$script:rootFailure='';$script:codeTreeCalls=@();$script:codeTreeFails=$false
function New-ProtectedDirectory {param($Path)
  if(Test-Path -LiteralPath $Path){throw ('Destination already exists; preserve and review it: '+$Path)}
  if($script:rootFailure -eq 'before'){throw 'Protected ancestry did not reach Program Files.'}
  $null=[IO.Directory]::CreateDirectory($Path);$script:events+='root'
  if($script:rootFailure -eq 'after'){throw 'Untrusted protected owner: simulated'}}
function Write-RegistrationControl {param($Path,$Text)
  if(Test-Path -LiteralPath $Path){throw ('control exists: '+$Path)}
  [IO.File]::WriteAllText($Path,$Text,[Text.UTF8Encoding]::new($false));$script:events+=('write:'+(Split-Path -Leaf $Path))
  if($script:fx.ChangeXmlOnIntent -and (Split-Path -Leaf $Path) -eq 'stop-intent.json'){$script:task.Xml=$script:task.Xml.Replace('<Description>','<Description>changed ')}
  (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
function Get-OtherDaemonTaskStates {param($Folder)if($script:otherActive){@([pscustomobject]@{name='CoChem-4.2.7-Supervisor';state='ACTIVE';active=$true})}else{@([pscustomobject]@{name='CoChem-4.2.7-Supervisor';state='STOPPED_DISABLED';active=$false})}}
function Get-WorkerProcesses {$script:workerSweeps++;$script:trace+='workers'
  $pids=@($script:workerPids)
  if($script:workerSweeps -le @($script:workerPlan).Count){$pids=@(([string]@($script:workerPlan)[$script:workerSweeps-1]) -split ','|Where-Object {$_}|ForEach-Object {[int]$_})}
  [ordered]@{workers=@($pids|ForEach-Object {[ordered]@{pid=$_;user='CoChem422Worker1';path='C:\x\agy.exe'}});uninspectable_processes=@();exited_during_sweep=0;authoritative=$true}}
function Get-ControllerPresence {$script:presenceCalls++
  $listen=$script:portListening;if($script:listenAtCall -gt 0 -and $script:presenceCalls -ge $script:listenAtCall){$listen=1}
  $c=@(@($script:alivePids)+@($script:foreignPids)|ForEach-Object {[ordered]@{pid=$_;parent=1;path='x';command='python -m cochem_pipeline daemon'}})
  [ordered]@{port=47824;listening=$listen;controller_processes=$c;observer_processes=@([ordered]@{pid=9472;command='observer'});client_processes=@();unclassified_runtime_processes=@();uninspectable_python_processes=0;authoritative=$true}}
function Test-LoopbackFree {$script:loopbackProbes++;[bool]$script:portFree}
function Test-ProcessInstancePresent {param($ProcessId,$CreationUtc)if($script:proofGone){return $false};[int]$ProcessId -in @($script:alivePids)}
function Start-Sleep {param($Seconds,$Milliseconds)$script:sleeps+=@($Seconds)}
function Get-LastBootUtc {'2026-10-11T00:57:00.0000000Z'}
function Assert-CodeTreeOnce {param($Path)$script:codeTreeCalls+=@($Path);if($script:codeTreeFails){throw 'Protected code inspection refused; simulated'};@()}
function Get-StopProcessProof {param($ProcessId)$script:trace+='proof'
  [ordered]@{controller=[ordered]@{pid=[int]$ProcessId;image='BASEPYVALUE';creation_utc='2026-10-11T12:00:56.0000000Z';parent_pid=5320};launcher=[ordered]@{pid=5320;image=$script:runtimePython;creation_utc='2026-10-11T12:00:55.0000000Z'};
    owner='SYSTEM';port_owner_verified=$true;last_boot_up_time='2026-10-11T00:57:00.0000000Z'}}
function Get-IdleEvidence {$script:idleEvaluations++;$script:trace+='idle'
  $idle=-not $script:notIdle
  [ordered]@{schema='cochem-warden-idle-evidence/1';idle=$idle;reasons=@($(if($idle){}else{'queue row job-7 is PENDING'}));offending_job_ids=@($(if($idle){}else{'job-7'}));errors=@();queue_rows=2;
    queue_status_counts=[ordered]@{BLOCKED=1;COMPLETED=1};in_progress_rows=0;uncleared_cleanup_rows=0;routing_holds=0;
    controller=[ordered]@{pid=20664;instance_id='0f5a2c3e9b8d4e7fa1b2c3d4e5f60718';process_started_at=1791720056.25;source_root=$script:runtimeSourceRoot}}}
$script:fxR4Install='R4INSTALL';$script:fxR4Revision='R4REVISION';$script:r4BindingCalls=0;$script:fxR4Refuse=''
function Assert-R4InstalledBindings {$script:r4BindingCalls++;if($script:fxR4Refuse){throw $script:fxR4Refuse}
  [ordered]@{install_receipt_sha256=$script:fxR4Install;source_manifest_sha256=$script:r4ManifestPin;configuration_sha256=$script:configPin;revision_sha256=$script:fxR4Revision}}
'''.replace('BASEPYVALUE', BASE_PY).replace('R4INSTALL', R4_INSTALL_PIN).replace('R4REVISION', R4_REVISION_PIN)

FX_READ = SID_STUB + r'''
$script:reads=@();$script:fxBase=''
function Resolve-Fx {param([string]$Path)
  $prefix='C:\Program Files\CoChem\'
  if($Path.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){return (Join-Path $script:fxBase $Path.Substring($prefix.Length))}
  $Path}
function Read-R3Control {param([string]$Path,[string]$Hash='',[long]$Maximum=16777216)
  $real=Resolve-Fx $Path
  if(-not (Test-Path -LiteralPath $real -PathType Leaf)){throw ('Fixture control is missing: '+$Path)}
  $length=(Get-Item -LiteralPath $real -Force).Length
  if($length -lt 0 -or $length -gt $Maximum){throw 'Bounded r3 control length differs.'}
  $actual=(Get-FileHash -LiteralPath $real -Algorithm SHA256).Hash.ToLowerInvariant()
  if($Hash -and $actual -cne $Hash){throw ('Source digest changed: '+$Path)}
  $script:reads+=[pscustomobject]@{path=$Path;hash=$Hash;maximum=$Maximum}
  # As the reviewed Read-R3Control does: the stream joins the caller's $held list, found by dynamic scope (17:22 fix).
  $held.Add($null)
  [pscustomobject]@{Stream=$null;Sha256=$(if($Hash){$Hash}else{$actual});Length=$length;Real=$real}}
function Read-R3Text {param($Control)[IO.File]::ReadAllText($Control.Real,[Text.UTF8Encoding]::new($false))}
# Test-Path sees the same redirected tree (the r5 root's install-held.json, the attempt's records).
function Test-Path {param([string]$LiteralPath,[string]$PathType='Any')Microsoft.PowerShell.Management\Test-Path -LiteralPath (Resolve-Fx $LiteralPath) -PathType $PathType}
function Use-Fixture {param([string]$Base,[string]$ConfigPin,[string]$ProbePin,$Pins=$null)
  $script:fxBase=$Base;$script:reads=@()
  $script:retargetRoot=Resolve-Fx $script:retargetRoot;$script:startReceiptPath=Resolve-Fx $script:startReceiptPath
  $script:configPin=$ConfigPin;$script:probePythonPin=$ProbePin
  # The fixture build stands in for the reviewed freeze: its manifest, venv and repair digests replace the C-F4 pins.
  if($null -ne $Pins){$script:r5ManifestPin=[string]$Pins.manifest;$script:r5PyvenvPin=[string]$Pins.pyvenv;$script:r5VenvPythonPin=[string]$Pins.venv
    $map=[ordered]@{};foreach($p in $Pins.repairs.PSObject.Properties){$map[$p.Name]=[string]$p.Value};$script:r5RepairPins=$map}}
'''

# --------------------------------------------------------------------------------------------------------------------
# The r5 runtime, its install receipt and the r5 start receipt as fixtures (under <base>\CoChem)
# --------------------------------------------------------------------------------------------------------------------

AUTO = '<auto>'
REFERENCE_CONFIG = b'{"stand_in": "runtime-root reference configuration"}\r\n'
STAGED_CONFIG = b'{"stand_in": "staged r5 configuration"}\r\n'
COMMISSIONED_CONFIG = b'{"stand_in": "commissioned configuration for the held fallback"}\r\n'
PYVENV = b'home = C:\\Program Files\\CoChem\\Toolchain4.2.7-windows-20261006\\Python312\r\ninclude-system-site-packages = false\r\n'
VENV_PY = b'MZ r5 venv launcher stand-in'
BASE_PY_BYTES = b'MZ toolchain python stand-in'


def repair_bytes(path):
    return f'# reviewed r5 bytes of {path}\r\n'.encode('ascii')


def runtime_ctx():
    repairs = {p: repair_bytes(p) for p in REPAIRS}
    digests = {p: sha(d) for p, d in repairs.items()}
    manifest = {'schema': 'cochem-stopped-runtime-source/1', 'host': 'AETHERDESK', 'complete_source_freeze': True, 'target_root': R5_ROOT,
                'previous_source_manifest_sha256': R4_MANIFEST_PIN, 'previous_install_receipt_sha256': R4_INSTALL_PIN, 'previous_manifest_entries': 166,
                'configuration_sha256': sha(REFERENCE_CONFIG), 'configuration_unchanged': True,
                'changes_from_previous_source': {'added': [], 'removed': [], 'changed': list(REPAIRS)},
                'files': [{'relative': p, 'sha256': digests[p], 'length': len(repairs[p])} for p in REPAIRS] +
                         [{'relative': f'src/cochem_pipeline/unchanged_{i:03d}.py', 'sha256': sha(str(i).encode()), 'length': len(str(i))} for i in range(166 - len(REPAIRS))]}
    after = {'schema': 'cochem-stopped-runtime-update/1', 'mode': 'FRESH_STOPPED_RUNTIME_READY', 'target_root': R5_ROOT, 'previous_runtime_root': R4_ROOT,
             'previous_install_receipt_sha256': R4_INSTALL_PIN, 'previous_source_manifest_sha256': R4_MANIFEST_PIN, 'source_manifest_sha256': AUTO,
             'source_files': 166, 'reviewed_repairs': list(REPAIRS), 'reviewed_repairs_sha256': dict(digests), 'configuration_sha256': sha(REFERENCE_CONFIG),
             'configuration_unchanged': True, 'only_config_change': None, 'tasks_changed': 0, 'credentials_modified': False, 'databases_modified': False,
             'ram_modified': False, 'pipeline_started': False, 'activation_ready': False, 'holds': [], 'verified_entries': 15013,
             'installed_repairs_verified': True, 'verified_unchanged': 153,
             'verification': {'revision': {'schema': 'cochem-installed-revision/1', 'verified': True, 'read_only': True, 'files': 109, 'source_sha256': 'ab' * 32,
                                           'acceptance_files': 0, 'acceptance_sha256': None},
                              'configuration_parsed': True, 'ram_workspace_root': 'R:\\CoChem427-windows-20261007', 'no_system_or_model_execution': True,
                              'telemetry_repair_installed': True, 'r5_repairs_installed': True},
             'runtime_bindings': {'pyvenv_sha256': sha(PYVENV), 'venv_python_sha256': sha(VENV_PY), 'base_python_sha256': sha(BASE_PY_BYTES), 'base_root': BASE_ROOT}}
    receipt = {'schema': 'cochem-warden-start/3', 'status': 'WARDEN_R5_RUNNING_HEALTH_VERIFIED', 'target': 'r5', 'attempt': 'v3', 'task_name': 'CoChem-4.2.7-Warden',
               'runtime_root': R5_ROOT, 'config_path': R5_CONFIG, 'config_sha256': AUTO, 'install_after_path': R5_ROOT + r'\install-after.json',
               'install_after_sha256': AUTO, 'action': {'execute': R5_PY, 'arguments': R5_ARGS, 'working_directory': R5_ROOT},
               'triggers': [{'type': 'logon', 'user_id': 'AETHERDESK\\ansac', 'delay': 'PT1M'}], 'task_xml_sha256': AUTO,
               'source_state': 'r4-v1', 'source_attempt': 'v1', 'stop_attempt': 'v1', 'retarget_receipt_sha256': AUTO, 'intent_sha256': AUTO,
               'task_xml_started_sha256': AUTO, 'trigger_enabled_before': False, 'trigger_enabled_after': True,
               'controller': {'pid': 31337, 'instance_id': 'deadbeefdeadbeefdeadbeefdeadbeef', 'process_started_at': 1.5, 'source_root': R5_SOURCE}, 'health_samples': 2}
    intent = {'schema': 'cochem-warden-start-intent/3', 'attempt': 'v3', 'target': 'r5', 'task_name': 'CoChem-4.2.7-Warden', 'runtime_root': R5_ROOT,
              'retarget_receipt_sha256': AUTO, 'requested_utc': '2026-10-11T12:00:00.0000000Z', 'enabled_before': False, 'enable_before_run': True,
              'exactly_one_start': True, 'retry': False}
    files = {R5_ROOT + r'\pipeline.json': REFERENCE_CONFIG, R5_ROOT + r'\.venv\pyvenv.cfg': PYVENV, R5_PY: VENV_PY, BASE_PY: BASE_PY_BYTES, R5_CONFIG: STAGED_CONFIG}
    for p, data in repairs.items():
        files[R5_ROOT + '\\source\\' + p.replace('/', '\\')] = data
        files[R5_ROOT + '\\.venv\\Lib\\site-packages\\' + p[4:].replace('/', '\\')] = data
    return {'manifest': manifest, 'after': after, 'receipt': receipt, 'files': files, 'post': {}, 'held': [], 'receipt_bytes': None,
            'intent': intent, 'retarget_patch': [], 'held_record': None, 'after_xml': SOURCE_XML, 'started_xml': TASK_XML, 'pins': {}}


def fx_path(base, windows_path):
    assert windows_path.lower().startswith(COCHEM.lower() + '\\'), windows_path
    return Path(base) / 'CoChem' / windows_path[len(COCHEM) + 1:]


HEAD_KEYS = ('target', 'attempt', 'task_name', 'runtime_root', 'config_path', 'config_sha256', 'install_after_path', 'install_after_sha256', 'action', 'triggers',
             'source_state', 'source_attempt', 'stop_attempt')


def retarget_receipt_for(receipt, status, trigger_enabled_after):
    """The retarget receipt of the same attempt (New-ReceiptHead fields equal to the start receipt's), registered disabled."""
    value = {'schema': 'cochem-warden-retarget/3', 'status': status}
    for key in HEAD_KEYS:
        if key in receipt:
            value[key] = json.loads(json.dumps(receipt[key]))
    value.update({'task_xml_sha256': AUTO, 'config_mode': 'GEMINI_CONTRACT', 'enabled_before': True, 'enabled_after': False, 'trigger_enabled_after': trigger_enabled_after,
                  'task_state': 1, 'running_instances': 0, 'task_xml_after_sha256': AUTO, 'sddl_preserved': True, 'started': False})
    return value


def attempt_records(receipt, retarget, intent, after_xml, started_xml):
    """Fill the AUTO digests that chain start receipt -> start intent -> retarget receipt -> warden-task-after.xml / -started.xml."""
    after_bytes = after_xml.encode() if isinstance(after_xml, str) else after_xml
    for key in ('task_xml_after_sha256', 'task_xml_sha256'):
        if retarget.get(key) == AUTO:
            retarget[key] = sha(after_bytes)
    retarget_bytes = json.dumps(retarget, indent=1).encode()
    if intent.get('retarget_receipt_sha256') == AUTO:
        intent['retarget_receipt_sha256'] = sha(retarget_bytes)
    intent_bytes = json.dumps(intent, indent=1).encode()
    started_bytes = started_xml.encode() if isinstance(started_xml, str) else started_xml
    for key, value in (('retarget_receipt_sha256', sha(retarget_bytes)), ('intent_sha256', sha(intent_bytes)), ('task_xml_sha256', sha(started_bytes)),
                       ('task_xml_started_sha256', sha(started_bytes))):
        if receipt.get(key) == AUTO:
            receipt[key] = value
    return {'retarget-receipt.json': retarget_bytes, 'start-intent.json': intent_bytes, 'warden-task-after.xml': after_bytes, 'warden-task-started.xml': started_bytes}


def materialize(ctx, base):
    manifest_bytes = json.dumps(ctx['manifest'], indent=1).encode()
    if ctx['after'].get('source_manifest_sha256') == AUTO:
        ctx['after']['source_manifest_sha256'] = sha(manifest_bytes)
    after_bytes = json.dumps(ctx['after'], indent=1).encode()
    receipt = ctx['receipt']
    if receipt.get('install_after_sha256') == AUTO:
        receipt['install_after_sha256'] = sha(after_bytes)
    if receipt.get('config_sha256') == AUTO:
        receipt['config_sha256'] = sha(ctx['files'].get(receipt['config_path'], STAGED_CONFIG))
    retarget = retarget_receipt_for(receipt, 'WARDEN_RETARGETED_TO_R5_NOT_STARTED', False)
    for patch in ctx['retarget_patch']:
        patch(retarget)
    files = dict(ctx['files'])
    for name, data in attempt_records(receipt, retarget, ctx['intent'], ctx['after_xml'], ctx['started_xml']).items():
        files[RETARGET_ROOT + '\\' + name] = data
    files[R5_ROOT + r'\install-after.json'] = after_bytes
    files[R5_ROOT + r'\source-manifest.json'] = manifest_bytes
    files[START_RECEIPT] = ctx['receipt_bytes'] if ctx['receipt_bytes'] is not None else json.dumps(receipt, indent=1).encode()
    for name in ctx['held']:
        files[RETARGET_ROOT + '\\' + name] = b'{}'
    if ctx['held_record'] is not None:
        held = ctx['held_record']
        files[RETARGET_ROOT + r'\start-held.json'] = held if isinstance(held, bytes) else json.dumps(held, indent=1).encode()
    for path, data in ctx['post'].items():
        files[path] = data(files.get(path)) if callable(data) else data
    for path, data in files.items():
        if data is None:
            continue
        target = fx_path(base, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    pins = {'manifest': sha(manifest_bytes), 'pyvenv': sha(PYVENV), 'venv': sha(VENV_PY), 'repairs': {p: sha(repair_bytes(p)) for p in REPAIRS}}
    for key, value in ctx['pins'].items():
        if key == 'repairs':
            pins['repairs'].update(value)
        else:
            pins[key] = value

    def digest(name):
        data = files.get(RETARGET_ROOT + '\\' + name)
        return sha(data) if data is not None else None
    return {'base': str(Path(base) / 'CoChem'), 'config_pin': sha(REFERENCE_CONFIG), 'probe_pin': sha(BASE_PY_BYTES), 'receipt': receipt, 'pins': pins,
            'receipt_sha256': sha(files[START_RECEIPT]) if files.get(START_RECEIPT) is not None else None,
            'retarget_sha256': digest('retarget-receipt.json'), 'intent_sha256': digest('start-intent.json'), 'held_sha256': digest('start-held.json'),
            'after_xml_sha256': digest('warden-task-after.xml'), 'started_xml_sha256': digest('warden-task-started.xml')}


def edit(section, *path, value=None, delete=False):
    def mutate(ctx):
        node = ctx[section]
        for key in path[:-1]:
            node = node[key]
        if delete:
            del node[path[-1]]
        else:
            node[path[-1]] = value
    return mutate


def post(path, data):
    def mutate(ctx):
        ctx['post'][path] = data
    return mutate


def chain(*mutators):
    def mutate(ctx):
        for m in mutators:
            m(ctx)
    return mutate


def held_fallback(ctx, data=REFERENCE_CONFIG):
    """The Gemini-held fallback names the WardenCommissioning copy; in the fixture the commissioned bytes are REFERENCE_CONFIG."""
    ctx['receipt']['config_path'] = HELD_CONFIG
    ctx['receipt']['action']['arguments'] = r5_args(HELD_CONFIG)
    ctx['files'][HELD_CONFIG] = data


def receipt_bytes(data):
    def mutate(ctx):
        ctx['receipt_bytes'] = data
    return mutate


def add_held(name):
    def mutate(ctx):
        ctx['held'].append(name)
    return mutate


def retarget_edit(*path, value=None, delete=False):
    """Change the attempt's retarget receipt only (the start receipt keeps the reviewed head)."""
    def mutate(ctx):
        def patch(retarget):
            node = retarget
            for key in path[:-1]:
                node = node[key]
            if delete:
                del node[path[-1]]
            else:
                node[path[-1]] = value
        ctx['retarget_patch'].append(patch)
    return mutate


def set_ctx(key, value):
    def mutate(ctx):
        ctx[key] = value
    return mutate


def pin(key, value):
    def mutate(ctx):
        ctx['pins'][key] = value
    return mutate


ATTEMPT_FILE = {name: RETARGET_ROOT + '\\' + name for name in ('retarget-receipt.json', 'start-intent.json', 'start-held.json', 'warden-task-after.xml',
                                                               'warden-task-started.xml')}
# start-held.json as retarget-warden-r5.ps1 writes it (FIXD-RETARGET schema): here interrupted by Ctrl+C during the health wait.
HELD_RECORD = {'schema': 'cochem-warden-start-held/3', 'target': 'r5', 'attempt': 'v3', 'task_name': 'CoChem-4.2.7-Warden', 'interrupted': True, 'stage': 'HEALTH_WAIT',
               'health_gate_passed': False, 'stop_recovery_allowed': True, 'run_requested': True, 'run_exception': None, 'held_before_run': False, 'enable_requested': True,
               'instance_guid': '{0F5A2C3E-0000-4000-8000-000000000005}', 'task_readable': True, 'task_state': 4, 'running_instances': 1, 'enabled_before': False,
               'enabled_after': False, 'disable_attempted': True, 'disable_error': None, 'task_xml_after_sha256': 'ab' * 32, 'trigger_enable_requested': False,
               'trigger_enabled_after': False, 'last_task_result': 267009, 'last_health_pid': None, 'receipt_written': False, 'reason': 'The pipeline has been stopped.',
               'automatic_retry_allowed': False, 'controller_preserved': True, 'requires_reviewed_recovery': True}


def held_record(**changes):
    """An interrupted or held start: start-intent.json, no start receipt, start-held.json with these changes."""
    def mutate(ctx):
        record = dict(HELD_RECORD)
        for key, value in changes.items():
            if value is DELETE:
                record.pop(key)
            else:
                record[key] = value
        ctx['held_record'] = record
        no_start_receipt(ctx)
    return mutate


DELETE = object()


def no_start_receipt(ctx):
    """A crashed start: start-intent.json, no start receipt (nor the started XML written just before it) and no held record."""
    ctx['post'][START_RECEIPT] = None
    ctx['post'][ATTEMPT_FILE['warden-task-started.xml']] = None


EXTRA_REPAIR = 'src/cochem_pipeline/probes.py'


def fourteen_repairs(ctx):
    """A consistent build with one more reviewed repair than addendum A6 names: retarget-warden-r5 admits it, so must the stop."""
    data = repair_bytes(EXTRA_REPAIR)
    ctx['after']['reviewed_repairs'].append(EXTRA_REPAIR)
    ctx['after']['reviewed_repairs_sha256'][EXTRA_REPAIR] = sha(data)
    ctx['manifest']['changes_from_previous_source']['changed'].append(EXTRA_REPAIR)
    ctx['manifest']['files'][-1] = {'relative': EXTRA_REPAIR, 'sha256': sha(data), 'length': len(data)}
    ctx['files'][R5_ROOT + '\\source\\' + EXTRA_REPAIR.replace('/', '\\')] = data
    ctx['files'][R5_ROOT + '\\.venv\\Lib\\site-packages\\' + EXTRA_REPAIR[4:].replace('/', '\\')] = data


SITE = R5_ROOT + '\\.venv\\Lib\\site-packages\\cochem_pipeline\\worker.py'
SOURCE = R5_ROOT + '\\source\\src\\cochem_pipeline\\worker.py'
TRIGGER = {'type': 'logon', 'user_id': 'AETHERDESK\\ansac', 'delay': 'PT1M'}
BINDING_CASES = {
    # start receipt binding
    'valid': (None, ''),
    'held_config_fallback': (held_fallback, ''),
    'held_config_other_sha': (lambda ctx: held_fallback(ctx, COMMISSIONED_CONFIG), 'commissioned configuration with a sha256 other than the commissioned one'),
    'trigger_user_case_insensitive': (edit('receipt', 'triggers', 0, 'user_id', value='aetherdesk\\ANSAC'), ''),
    'receipt_missing': (post(START_RECEIPT, None), 'start receipt is missing'),
    'receipt_not_json': (receipt_bytes(b'{"schema":'), 'not a JSON object'),
    'receipt_json_array': (receipt_bytes(b'[1,2]'), 'not a JSON object'),
    'receipt_oversize': (edit('receipt', 'padding', value='x' * 1100000), 'Bounded r3 control length differs'),
    'schema_v2': (edit('receipt', 'schema', value='cochem-warden-start/2'), 'not a successful r5 start'),
    'status_r4_restart': (edit('receipt', 'status', value='WARDEN_R4_RESTARTED_HEALTH_VERIFIED'), 'not a successful r5 start'),
    'target_r4': (edit('receipt', 'target', value='r4'), 'not a successful r5 start'),
    'target_missing': (edit('receipt', 'target', delete=True), 'not a successful r5 start'),
    'attempt_other': (edit('receipt', 'attempt', value='v2'), 'does not name this -RetargetAttempt'),
    'attempt_number': (edit('receipt', 'attempt', value=3), 'does not name this -RetargetAttempt'),
    'task_name_other': (edit('receipt', 'task_name', value='CoChem-4.2.2-Warden'), 'does not name this -RetargetAttempt'),
    'runtime_root_r4': (edit('receipt', 'runtime_root', value=R4_ROOT), 'does not name an r5 runtime root'),
    'runtime_root_trailing_newline': (edit('receipt', 'runtime_root', value=R5_ROOT + '\n'), 'does not name an r5 runtime root'),
    'runtime_root_list': (edit('receipt', 'runtime_root', value=[R5_ROOT]), 'does not name an r5 runtime root'),
    'config_outside_program_files': (edit('receipt', 'config_path', value=r'C:\Users\ansac\CoChem427\pipeline.json'), 'not a reviewed protected r5 configuration'),
    'config_sha_uppercase': (edit('receipt', 'config_sha256', value='A' * 64), 'not a reviewed protected r5 configuration'),
    'config_sha_missing': (edit('receipt', 'config_sha256', delete=True), 'not a reviewed protected r5 configuration'),
    'install_after_other_root': (edit('receipt', 'install_after_path', value=R4_ROOT + r'\install-after.json'), 'does not bind the installation receipt'),
    'install_after_sha_short': (edit('receipt', 'install_after_sha256', value='abc'), 'does not bind the installation receipt'),
    'action_execute_r4': (edit('receipt', 'action', 'execute', value=R4_PY), 'action is not the reviewed r5 daemon action'),
    'action_arguments_r4_queue_flag': (edit('receipt', 'action', 'arguments', value=f'-I -B -m cochem_pipeline daemon --config "{R5_CONFIG}" --queue-launch-output "{QUEUE_ROOT}"'),
                                       'action is not the reviewed r5 daemon action'),
    'action_arguments_no_docker_wait': (edit('receipt', 'action', 'arguments', value=r5_args().replace(' --docker-wait-seconds 900', '')), 'action is not the reviewed r5 daemon action'),
    'action_arguments_other_config': (edit('receipt', 'action', 'arguments', value=r5_args(HELD_CONFIG)), 'action is not the reviewed r5 daemon action'),
    'action_working_directory_r4': (edit('receipt', 'action', 'working_directory', value=R4_ROOT), 'action is not the reviewed r5 daemon action'),
    'action_missing': (edit('receipt', 'action', delete=True), 'action is not the reviewed r5 daemon action'),
    'action_execute_number': (edit('receipt', 'action', 'execute', value=5), 'action is not the reviewed r5 daemon action'),
    'triggers_empty': (edit('receipt', 'triggers', value=[]), 'exactly one trigger'),
    'triggers_two': (edit('receipt', 'triggers', value=[TRIGGER, TRIGGER]), 'exactly one trigger'),
    'triggers_missing': (edit('receipt', 'triggers', delete=True), 'exactly one trigger'),
    'triggers_object': (edit('receipt', 'triggers', value=TRIGGER), 'exactly one trigger'),
    'trigger_boot': (edit('receipt', 'triggers', 0, 'type', value='boot'), 'not the reviewed logon trigger'),
    'trigger_user_other': (edit('receipt', 'triggers', 0, 'user_id', value='AETHERDESK\\other'), 'not the reviewed logon trigger'),
    'trigger_delay_zero': (edit('receipt', 'triggers', 0, 'delay', value='PT0S'), 'not the reviewed logon trigger'),
    'retarget_held_present': (add_held('retarget-held.json'), 'holds retarget-held.json'),
    'start_held_present': (add_held('start-held.json'), 'holds start-held.json'),
    # r5 installation, content-verified against the receipt
    'install_after_changed_on_disk': (post(R5_ROOT + r'\install-after.json', lambda data: data + b' '), 'Source digest changed'),
    'install_after_missing': (post(R5_ROOT + r'\install-after.json', None), 'Fixture control is missing'),
    'install_schema_v2': (edit('after', 'schema', value='cochem-stopped-runtime-update/2'), 'not the reviewed successful stopped-runtime build'),
    'install_mode': (edit('after', 'mode', value='FRESH_STOPPED_RUNTIME_HELD'), 'not the reviewed successful stopped-runtime build'),
    'install_target_root_r4': (edit('after', 'target_root', value=R4_ROOT), 'not the reviewed successful stopped-runtime build'),
    'install_previous_root_r3': (edit('after', 'previous_runtime_root', value=R3_ROOT), 'not the reviewed successful stopped-runtime build'),
    'install_previous_receipt': (edit('after', 'previous_install_receipt_sha256', value='3b613128192ac44a0a3d9c4b4476fb4c47541edb7563541b9bbf18f84f9a90f6'), 'not the reviewed successful'),
    'install_previous_manifest': (edit('after', 'previous_source_manifest_sha256', value='6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1'), 'not the reviewed successful'),
    'install_manifest_is_r4': (edit('after', 'source_manifest_sha256', value=R4_MANIFEST_PIN), 'not the reviewed successful'),
    'install_configuration_differs': (edit('after', 'configuration_sha256', value='0' * 64), 'not the reviewed successful'),
    'install_configuration_unchanged_string': (edit('after', 'configuration_unchanged', value='true'), 'not the reviewed successful'),
    'install_source_files': (edit('after', 'source_files', value=165), 'not the reviewed successful'),
    'install_holds': (edit('after', 'holds', value=['PyPI unreachable']), 'not the reviewed successful'),
    'install_holds_missing': (edit('after', 'holds', delete=True), 'not the reviewed successful'),
    'install_tasks_changed': (edit('after', 'tasks_changed', value=1), 'not the reviewed successful'),
    'install_pipeline_started': (edit('after', 'pipeline_started', value=True), 'not the reviewed successful'),
    'install_databases_modified': (edit('after', 'databases_modified', value=True), 'not the reviewed successful'),
    'install_revision_files_110_admitted': (edit('after', 'verification', 'revision', 'files', value=110), ''),
    'install_revision_files_zero': (edit('after', 'verification', 'revision', 'files', value=0), 'not the reviewed successful'),
    'install_revision_files_string': (edit('after', 'verification', 'revision', 'files', value='109'), 'not the reviewed successful'),
    'install_revision_is_r4': (edit('after', 'verification', 'revision', 'source_sha256', value=R4_REVISION_PIN), 'not the reviewed successful'),
    'install_revision_is_r3': (edit('after', 'verification', 'revision', 'source_sha256', value=R3_REVISION_PIN), 'not the reviewed successful'),
    'install_revision_unverified': (edit('after', 'verification', 'revision', 'verified', value=False), 'not the reviewed successful'),
    'install_verification_missing': (edit('after', 'verification', delete=True), 'not the reviewed successful'),
    'install_ram_root': (edit('after', 'verification', 'ram_workspace_root', value='R:\\other'), 'not the reviewed successful'),
    'binding_base_python': (edit('after', 'runtime_bindings', 'base_python_sha256', value='0' * 64), 'runtime binding receipt differs'),
    'binding_base_root': (edit('after', 'runtime_bindings', 'base_root', value=R4_ROOT), 'runtime binding receipt differs'),
    'binding_pyvenv_empty': (edit('after', 'runtime_bindings', 'pyvenv_sha256', value=''), 'runtime binding receipt differs'),
    'binding_venv_python_missing': (edit('after', 'runtime_bindings', 'venv_python_sha256', delete=True), 'runtime binding receipt differs'),
    'venv_python_file_differs': (post(R5_PY, b'MZ another launcher'), 'Source digest changed'),
    'pyvenv_file_differs': (post(R5_ROOT + r'\.venv\pyvenv.cfg', b'home = elsewhere\r\n'), 'Source digest changed'),
    'reference_config_differs': (post(R5_ROOT + r'\pipeline.json', b'{}'), 'Source digest changed'),
    'base_python_differs': (post(BASE_PY, b'MZ other base'), 'Source digest changed'),
    # C-F4: a consistent build with a 14th repair is no longer the reviewed freeze (retarget-warden-r5 pins the same 13).
    'fourteen_repairs_consistent': (fourteen_repairs, 'not the 13 repairs of the pinned freeze'),
    'install_held_record_present': (post(R5_ROOT + r'\install-held.json', b'{}'), 'holds install-held.json'),
    'install_manifest_not_the_pinned_freeze': (pin('manifest', '0' * 64), 'does not name the reviewed freeze manifest'),
    'install_repairs_verified_false': (edit('after', 'installed_repairs_verified', value=False), 'does not prove the reviewed repairs installed'),
    'install_repairs_verified_missing': (edit('after', 'installed_repairs_verified', delete=True), 'does not prove the reviewed repairs installed'),
    'install_r5_repairs_installed_false': (edit('after', 'verification', 'r5_repairs_installed', value=False), 'does not prove the reviewed repairs installed'),
    'install_r5_repairs_installed_missing': (edit('after', 'verification', 'r5_repairs_installed', delete=True), 'does not prove the reviewed repairs installed'),
    'install_verified_unchanged_152': (edit('after', 'verified_unchanged', value=152), 'does not prove the reviewed repairs installed'),
    'install_verified_unchanged_string': (edit('after', 'verified_unchanged', value='153'), 'does not prove the reviewed repairs installed'),
    'repair_digest_not_the_pinned_freeze': (pin('repairs', {'src/cochem_pipeline/worker.py': '0' * 64}), 'differs from the pinned freeze: src/cochem_pipeline/worker.py'),
    'pyvenv_not_the_installer_pin': (pin('pyvenv', '0' * 64), 'runtime binding receipt differs'),
    'venv_launcher_not_the_installer_pin': (pin('venv', '0' * 64), 'runtime binding receipt differs'),
    # The attempt's records behind a completed start (C-F1(b) and C-F5 bind the same chain).
    'retarget_receipt_missing': (post(ATTEMPT_FILE['retarget-receipt.json'], None), 'r5 retarget receipt is missing'),
    'retarget_receipt_other_attempt': (retarget_edit('attempt', value='v2'), 'The retarget receipt does not name this -RetargetAttempt'),
    'retarget_receipt_started_status': (retarget_edit('status', value='WARDEN_R5_RUNNING_HEALTH_VERIFIED'), 'not a successful r5 retarget registered disabled'),
    'retarget_receipt_registered_enabled': (retarget_edit('enabled_after', value=True), 'not a successful r5 retarget registered disabled'),
    'retarget_receipt_two_task_xml_digests': (retarget_edit('task_xml_sha256', value='0' * 64), 'not a successful r5 retarget registered disabled'),
    'retarget_receipt_trigger_registered_enabled': (retarget_edit('trigger_enabled_after', value=True), 'does not record the two-phase registration'),
    'retarget_receipt_trigger_state_missing': (retarget_edit('trigger_enabled_after', delete=True), 'does not record the two-phase registration'),
    'retarget_receipt_other_config': (chain(retarget_edit('config_path', value=HELD_CONFIG), retarget_edit('config_sha256', value=sha(REFERENCE_CONFIG)),
                                            retarget_edit('action', 'arguments', value=r5_args(HELD_CONFIG))), 'does not repeat its retarget receipt'),
    'retarget_receipt_other_trigger_user': (retarget_edit('triggers', 0, 'user_id', value='aetherdesk\\ANSAC'), 'does not repeat its retarget receipt'),
    'start_names_other_retarget_receipt': (edit('receipt', 'retarget_receipt_sha256', value='f' * 64), 'name different retarget receipts'),
    'start_retarget_sha_uppercase': (edit('receipt', 'retarget_receipt_sha256', value='F' * 64), 'does not record retarget_receipt_sha256 as a lowercase sha256'),
    'start_trigger_enabled_after_false': (edit('receipt', 'trigger_enabled_after', value=False), 'does not record the two-phase start'),
    'start_trigger_enabled_after_missing': (edit('receipt', 'trigger_enabled_after', delete=True), 'does not record the two-phase start'),
    'start_trigger_enabled_before_true': (edit('receipt', 'trigger_enabled_before', value=True), 'does not record the two-phase start'),
    'start_task_xml_started_differs': (edit('receipt', 'task_xml_started_sha256', value='0' * 64), 'task_xml_started_sha256 is not its task_xml_sha256'),
    'start_intent_missing': (post(ATTEMPT_FILE['start-intent.json'], None), 'r5 start intent is missing'),
    'start_intent_changed_on_disk': (post(ATTEMPT_FILE['start-intent.json'], lambda data: data + b' '), 'Source digest changed'),
    'start_intent_other_attempt': (edit('intent', 'attempt', value='v2'), 'The start intent is not a start request of this -RetargetAttempt'),
    'start_intent_other_runtime_root': (edit('intent', 'runtime_root', value=R4_ROOT), 'does not name the runtime root of its retarget receipt'),
    'source_xml_missing': (post(ATTEMPT_FILE['warden-task-after.xml'], None), 'retarget attempt registered is missing'),
    'source_xml_changed_on_disk': (post(ATTEMPT_FILE['warden-task-after.xml'], b'<Task/>'), 'Source digest changed'),
    'source_xml_names_other_attempt': (set_ctx('after_xml', SOURCE_XML.replace('retarget v3', 'retarget v2')), 'does not name that attempt in its Description'),
    'source_xml_trigger_registered_enabled': (set_ctx('after_xml', TASK_XML_DISABLED), 'does not carry exactly one disabled logon trigger'),
    'started_xml_missing': (post(ATTEMPT_FILE['warden-task-started.xml'], None), 'start recorded is missing'),
    'started_xml_trigger_still_disabled': (set_ctx('started_xml', LIVE_XML_TRIGGER_OFF), 'not the registered task XML with only its Enabled flags changed'),
    'started_xml_other_setting': (set_ctx('started_xml', TASK_XML.replace('IgnoreNew', 'Parallel')), 'not the registered task XML with only its Enabled flags changed'),
    'started_xml_other_attempt': (set_ctx('started_xml', TASK_XML.replace('retarget v3', 'retarget v2')), 'not the registered task XML with only its Enabled flags changed'),
    'repairs_without_main': (edit('after', 'reviewed_repairs', value=[p for p in REPAIRS if not p.endswith('__main__.py')]), 'includes src/cochem_pipeline/__main__.py'),
    'repairs_extra_path_without_digest': (edit('after', 'reviewed_repairs', value=REPAIRS + [EXTRA_REPAIR]), 'not one per reviewed path'),
    'repairs_duplicate': (edit('after', 'reviewed_repairs', value=REPAIRS[:-1] + [REPAIRS[0]]), 'not a unique list of package source paths'),
    'repairs_parent_segment': (edit('after', 'reviewed_repairs', value=REPAIRS[:-1] + ['src/cochem_pipeline/../x.py']), 'not a unique list of package source paths'),
    'repairs_not_a_package_path': (edit('after', 'reviewed_repairs', value=REPAIRS[:-1] + ['README.md']), 'not a unique list of package source paths'),
    'repairs_empty': (edit('after', 'reviewed_repairs', value=[]), 'not a unique list of package source paths'),
    'repairs_r4_singular_form': (chain(edit('after', 'reviewed_repairs', delete=True), edit('after', 'reviewed_repair', value='src/cochem_pipeline/resource_telemetry.py')),
                                 'not a unique list of package source paths'),
    'repair_digests_missing_one': (edit('after', 'reviewed_repairs_sha256', 'src/cochem_pipeline/worker.py', delete=True), 'not one per reviewed path'),
    'repair_digest_uppercase': (edit('after', 'reviewed_repairs_sha256', 'src/cochem_pipeline/worker.py', value='F' * 64), 'missing or malformed'),
    'installed_package_differs': (post(SITE, b'# unreviewed\r\n'), 'Source digest changed'),
    'frozen_source_differs': (post(SOURCE, b'# unreviewed\r\n'), 'Source digest changed'),
    'manifest_changed_set': (edit('manifest', 'changes_from_previous_source', 'changed', value=REPAIRS[1:]), 'Frozen r5 manifest binding differs'),
    'manifest_added_module': (edit('manifest', 'changes_from_previous_source', 'added', value=['src/cochem_pipeline/new.py']), 'Frozen r5 manifest binding differs'),
    'manifest_changed_extra': (edit('manifest', 'changes_from_previous_source', 'changed', value=REPAIRS + [EXTRA_REPAIR]), 'Frozen r5 manifest binding differs'),
    'manifest_removed_module': (edit('manifest', 'changes_from_previous_source', 'removed', value=['src/cochem_pipeline/old.py']), 'Frozen r5 manifest binding differs'),
    'manifest_added_absent_admitted': (edit('manifest', 'changes_from_previous_source', 'added', delete=True), ''),
    'manifest_schema': (edit('manifest', 'schema', value='cochem-stopped-runtime-source/2'), 'Frozen r5 manifest binding differs'),
    'manifest_not_complete': (edit('manifest', 'complete_source_freeze', value=False), 'Frozen r5 manifest binding differs'),
    'manifest_target_root': (edit('manifest', 'target_root', value=R4_ROOT), 'Frozen r5 manifest binding differs'),
    'manifest_file_count': (lambda ctx: ctx['manifest']['files'].pop(), 'Frozen r5 manifest binding differs'),
    'manifest_repair_digest_differs': (lambda ctx: ctx['manifest']['files'][REPAIRS.index('src/cochem_pipeline/worker.py')].update(sha256='0' * 64),
                                       'does not list the reviewed digest of src/cochem_pipeline/worker.py'),
    'staged_config_differs': (post(R5_CONFIG, b'{"other": 1}'), 'Source digest changed'),
    'staged_config_missing': (post(R5_CONFIG, None), 'Fixture control is missing'),
}


def run_binding_table(work, table, recover):
    """Read-StartReceipt then Assert-TargetRuntimeBindings over one fixture tree per case, in one powershell.exe."""
    cases = []
    for name, entry in table.items():
        ctx = runtime_ctx()
        if entry[0]:
            entry[0](ctx)
        info = materialize(ctx, work / name)
        cases.append(dict(info, name=name, receipt=None))
    (work / 'cases.json').write_text(json.dumps(cases), encoding='utf-8')
    body = FX_READ + r'''
$cases=[IO.File]::ReadAllText('CASES')|ConvertFrom-Json
$out=[ordered]@{}
foreach($case in $cases){
  Set-StopConstants;$script:RecoverInterruptedStart=RECOVER;Use-Fixture $case.base $case.config_pin $case.probe_pin $case.pins
  $message='';$receipt=$null;$bindings=$null;$stage='receipt'
  try{$receipt=Read-StartReceipt;$stage='bindings';$bindings=Assert-TargetRuntimeBindings $receipt;$stage='done'}catch{$message=$_.Exception.Message}
  $out[$case.name]=[ordered]@{message=$message;stage=$stage;receipt=$receipt;bindings=$bindings;expected_action=$script:expectedAction;expected_triggers=$script:expectedTriggers;
    runtime_root=$script:runtimeRoot;runtime_python=$script:runtimePython;runtime_source=$script:runtimeSourceRoot;reads=@($script:reads);start_binding=$script:startBinding;
    allowed=@($script:allowedTriggerEnabled);source_xml_bound=($null -ne $script:sourceTaskXml);started_xml_bound=($null -ne $script:startedTaskXml)}}
$out|ConvertTo-Json -Depth 8 -Compress'''.replace('CASES', ps(work / 'cases.json')).replace('RECOVER', '$true' if recover else '$false')
    return {'results': run_json(body, work, timeout=600), 'cases': {c['name']: c for c in cases}}


@pytest.fixture(scope='module')
def binding_results(tmp_path_factory):
    return run_binding_table(tmp_path_factory.mktemp('bindings'), BINDING_CASES, False)


def r4_receipt():
    """The start receipt retarget-warden-r5.ps1 -Target r4 -Attempt v3 writes (New-ReceiptHead + the start fields)."""
    return {'schema': 'cochem-warden-start/3', 'status': 'WARDEN_R4_RESTARTED_HEALTH_VERIFIED', 'target': 'r4', 'attempt': 'v3', 'task_name': 'CoChem-4.2.7-Warden',
            'runtime_root': R4_ROOT, 'config_path': R4_RESTORE_CONFIG, 'config_sha256': CONFIG_PIN, 'install_after_path': None, 'install_after_sha256': None,
            'action': {'execute': R4_PY, 'arguments': R4_RESTORE_ARGS, 'working_directory': R4_ROOT}, 'triggers': [], 'task_xml_sha256': AUTO,
            'source_state': 'r5-receipt', 'source_attempt': 'v3', 'stop_attempt': 'v1', 'config_mode': 'COMMISSIONED', 'deployment_revision_sha256': R4_REVISION_PIN,
            'retarget_receipt_sha256': AUTO, 'intent_sha256': AUTO, 'task_xml_started_sha256': AUTO, 'trigger_enabled_before': None, 'trigger_enabled_after': None,
            'enabled_after': True, 'enabled_by_start': True, 'enable_before_run': True, 'instance_guid': '{0F5A2C3E-0000-4000-8000-0000000000R4}',
            'controller': {'pid': 4242, 'instance_id': 'feedfacefeedfacefeedfacefeedface', 'process_started_at': 2.5, 'source_root': R4_SOURCE}}


def write_r4_receipt(base, mutate=None, held=(), retarget_patch=None):
    """The r4 restore attempt's records: start receipt, start intent, retarget receipt and the registered/started task XML."""
    receipt = r4_receipt()
    retarget = retarget_receipt_for(receipt, 'WARDEN_RETARGETED_TO_R4_NOT_STARTED', None)
    if retarget_patch:
        retarget_patch(retarget)
    intent = {'schema': 'cochem-warden-start-intent/3', 'attempt': 'v3', 'target': 'r4', 'task_name': 'CoChem-4.2.7-Warden', 'runtime_root': R4_ROOT,
              'retarget_receipt_sha256': AUTO, 'requested_utc': '2026-10-11T13:00:00.0000000Z', 'enabled_before': False, 'enable_before_run': True,
              'exactly_one_start': True, 'retry': False}
    records = attempt_records(receipt, retarget, intent, TASK_XML_R4_DISABLED, TASK_XML_R4)
    raw = None
    if mutate:
        raw = mutate(receipt)
    root = Path(base) / 'CoChem' / 'WardenRetarget4.2.7-windows-20261011-r4-v3'
    root.mkdir(parents=True, exist_ok=True)
    for name, data in records.items():
        (root / name).write_bytes(data)
    if raw != 'MISSING':
        (root / 'start-receipt.json').write_bytes(raw if isinstance(raw, bytes) else json.dumps(receipt, indent=1).encode())
    for name in held:
        (root / name).write_bytes(b'{}')
    return {'base': str(Path(base) / 'CoChem'), 'receipt': receipt, 'retarget_sha256': sha(records['retarget-receipt.json'])}


def r4_edit(*path, value=None, delete=False):
    def mutate(receipt):
        node = receipt
        for key in path[:-1]:
            node = node[key]
        if delete:
            del node[path[-1]]
        else:
            node[path[-1]] = value
    return mutate


R4_BINDING_CASES = {
    # name: (receipt mutator, held records, r4 binding stub flags, expected refusal fragment or '')
    'r4_valid': (None, (), '', ''),
    'r4_without_start_enable_fields': (lambda r: [r.pop(k) for k in ('enabled_after', 'enabled_by_start', 'enable_before_run')] and None, (), '', ''),
    'r4_receipt_missing': (lambda r: 'MISSING', (), '', 'r4 start receipt is missing'),
    'r4_receipt_not_json': (lambda r: b'{"schema":', (), '', 'r4 start receipt is not a JSON object'),
    'r4_schema_v2': (r4_edit('schema', value='cochem-warden-start/2'), (), '', 'not a successful r4 start'),
    'r4_status_r5': (r4_edit('status', value='WARDEN_R5_RUNNING_HEALTH_VERIFIED'), (), '', 'not a successful r4 start'),
    'r4_status_retargeted_not_started': (r4_edit('status', value='WARDEN_RETARGETED_TO_R4_NOT_STARTED'), (), '', 'not a successful r4 start'),
    'r4_target_r5': (r4_edit('target', value='r5'), (), '', 'not a successful r4 start'),
    'r4_attempt_other': (r4_edit('attempt', value='v2'), (), '', 'does not name this -RetargetAttempt'),
    'r4_task_name_other': (r4_edit('task_name', value='CoChem-4.2.2-Warden'), (), '', 'does not name this -RetargetAttempt'),
    'r4_runtime_root_r5': (r4_edit('runtime_root', value=R5_ROOT), (), '', 'does not name the r4 runtime root'),
    'r4_runtime_root_r3': (r4_edit('runtime_root', value=R3_ROOT), (), '', 'does not name the r4 runtime root'),
    'r4_config_commissioning_copy': (r4_edit('config_path', value=HELD_CONFIG), (), '', 'not the commissioned pipeline.json of the r4 root'),
    'r4_config_sha_other': (r4_edit('config_sha256', value='0' * 64), (), '', 'not the commissioned pipeline.json of the r4 root'),
    'r4_config_sha_uppercase': (r4_edit('config_sha256', value=CONFIG_PIN.upper()), (), '', 'not the commissioned pipeline.json of the r4 root'),
    'r4_install_after_path_set': (r4_edit('install_after_path', value=R4_ROOT + r'\install-after.json'), (), '', 'must record install_after_path as null'),
    'r4_install_after_sha_set': (r4_edit('install_after_sha256', value=R4_INSTALL_PIN), (), '', 'must record install_after_sha256 as null'),
    'r4_install_after_path_absent': (r4_edit('install_after_path', delete=True), (), '', 'must record install_after_path as null'),
    'r4_action_other_attempt_queue': (r4_edit('action', 'arguments', value=r4_restore_args('v9')), (), '', 'not the reviewed r4 restore action of this retarget attempt'),
    'r4_action_r4v1': (r4_edit('action', 'arguments', value=R4V1_ARGS), (), '', 'not the reviewed r4 restore action'),
    'r4_action_r5_flags': (r4_edit('action', 'arguments', value=r5_args(R4_RESTORE_CONFIG)), (), '', 'not the reviewed r4 restore action'),
    'r4_action_execute_r5': (r4_edit('action', 'execute', value=R5_PY), (), '', 'not the reviewed r4 restore action'),
    'r4_action_working_directory': (r4_edit('action', 'working_directory', value=R5_ROOT), (), '', 'not the reviewed r4 restore action'),
    'r4_action_missing': (r4_edit('action', delete=True), (), '', 'not the reviewed r4 restore action'),
    'r4_triggers_logon': (r4_edit('triggers', value=[TRIGGER]), (), '', 'must record an empty trigger list'),
    'r4_triggers_null': (r4_edit('triggers', value=None), (), '', 'must record an empty trigger list'),
    'r4_triggers_missing': (r4_edit('triggers', delete=True), (), '', 'must record an empty trigger list'),
    'r4_retarget_held': (None, ('retarget-held.json',), '', 'holds retarget-held.json'),
    'r4_start_held': (None, ('start-held.json',), '', 'holds start-held.json'),
    'r4_install_pin_differs': (None, (), "$script:fxR4Install=('0'*64);", 'not the pinned receipt'),
    'r4_revision_pin_differs': (None, (), "$script:fxR4Revision=('0'*64);", 'not the pinned revision'),
    'r4_bindings_refused': (None, (), "$script:fxR4Refuse='The r4 installation receipt is not the reviewed successful stopped-runtime build.';", 'not the reviewed successful stopped-runtime build'),
    # The r4 restore attempt's chain (no trigger: trigger_enabled_* are null) and its retarget receipt.
    'r4_start_trigger_state_bool': (r4_edit('trigger_enabled_after', value=False), (), '', 'does not record the two-phase start (trigger_enabled_before and trigger_enabled_after null)'),
    'r4_retarget_trigger_state_false': (None, (), '', 'does not record the two-phase registration (trigger_enabled_after null)', lambda r: r.update(trigger_enabled_after=False)),
    'r4_retarget_other_queue_attempt': (None, (), '', 'The retarget receipt action is not the reviewed r4 restore action',
                                        lambda r: r['action'].update(arguments=r4_restore_args('v9'))),
    'r4_retarget_status_r5': (None, (), '', 'not a successful r4 retarget registered disabled', lambda r: r.update(status='WARDEN_RETARGETED_TO_R5_NOT_STARTED')),
    'r4_start_names_other_intent': (r4_edit('intent_sha256', value='0' * 64), (), '', 'Source digest changed'),
}


@pytest.fixture(scope='module')
def r4_binding_results(tmp_path_factory):
    work = tmp_path_factory.mktemp('r4bindings')
    lines = [FX_READ, STUBS, '$out=[ordered]@{}']
    receipts = {}
    for name, (mutator, held, flags, _, *rest) in R4_BINDING_CASES.items():
        info = write_r4_receipt(work / name, mutator, held, rest[0] if rest else None)
        receipts[name] = info['receipt']
        lines.append(f"$script:RetargetTarget='r4';Set-StopConstants;Use-Fixture '{ps(info['base'])}' '{CONFIG_PIN}' '{BASE_PY_PIN}';"
                     f"$script:fxR4Install='{R4_INSTALL_PIN}';$script:fxR4Revision='{R4_REVISION_PIN}';$script:fxR4Refuse='';$script:r4BindingCalls=0;{flags}"
                     "$m='';$receipt=$null;$bindings=$null;try{$receipt=Read-StartReceipt;$bindings=Assert-TargetRuntimeBindings $receipt}catch{$m=$_.Exception.Message};"
                     f"$out['{name}']=[ordered]@{{message=$m;receipt=$receipt;bindings=$bindings;expected_action=$script:expectedAction;expected_trigger_count=@($script:expectedTriggers).Count;"
                     "expected_triggers_bound=($null -ne $script:expectedTriggers);runtime_root=$script:runtimeRoot;runtime_python=$script:runtimePython;runtime_source=$script:runtimeSourceRoot;"
                     "retarget_root=$script:retargetRoot;binding_calls=$script:r4BindingCalls;reads=@($script:reads)}")
    lines.append('$out|ConvertTo-Json -Depth 8 -Compress')
    return run_json('\n'.join(lines), work, timeout=600)


@pytest.mark.parametrize('case', list(R4_BINDING_CASES))
def test_r4_restore_start_receipt_and_r4_runtime_binding_table(r4_binding_results, case):
    expected = R4_BINDING_CASES[case][3]
    value = r4_binding_results[case]
    assert value['retarget_root'].endswith('WardenRetarget4.2.7-windows-20261011-r4-v3'), 'the r4 restore namespace of -RetargetAttempt'
    if expected:
        assert expected in value['message'], value['message']
        return
    assert value['message'] == '', value['message']
    assert value['expected_action'] == {'execute': R4_PY, 'arguments': R4_RESTORE_ARGS, 'working_directory': R4_ROOT}
    assert value['expected_trigger_count'] == 0 and value['expected_triggers_bound'] is True, 'an r4 restore binds an empty trigger set'
    assert value['runtime_root'] == R4_ROOT and value['runtime_python'] == R4_PY and value['runtime_source'] == R4_SOURCE
    receipt = value['receipt']
    assert receipt['target'] == 'r4' and receipt['status'] == 'WARDEN_R4_RESTARTED_HEALTH_VERIFIED' and receipt['controller_bound'] is False
    assert receipt['install_after_path'] is None and receipt['install_after_sha256'] is None and receipt['triggers'] in ([], None)
    bindings = value['bindings']
    assert bindings == {'runtime': 'r4', 'install_receipt_sha256': R4_INSTALL_PIN, 'source_manifest_sha256': R4_MANIFEST_PIN, 'revision_sha256': R4_REVISION_PIN,
                        'reviewed_repair_sha256': REPAIR_PIN, 'task_config_path': R4_RESTORE_CONFIG, 'task_config_sha256': CONFIG_PIN}
    hashes = [r['hash'] for r in value['reads']]
    assert value['binding_calls'] == 1 and hashes[0] == '' and len(hashes) == 5 and all(hashes[1:]), \
        'only the start receipt is read unpinned (then the digest-bound intent, retarget receipt and registered/started XML); the r4 tree is bound by Assert-R4InstalledBindings'
    assert receipt['binding'] == 'START_RECEIPT' and receipt['trigger_enabled_allowed'] in ([], None) and receipt['source_task_xml_after_sha256'] == sha(TASK_XML_R4_DISABLED.encode())
    assert receipt['source_task_xml_started_sha256'] == sha(TASK_XML_R4.encode())


def test_r4_restore_interrupted_or_crashed_start_binds_with_recover_interrupted_start(tmp_path):
    """C-F1(b) for an r4 restore: no trigger, so the held record's trigger_enabled_after must be null and no trigger state is admitted."""
    held = dict(HELD_RECORD, target='r4', trigger_enabled_after=None)
    cases = {'r4_crashed_no_record': (None, 'START_CRASHED_NO_RECORD'), 'r4_interrupted_held': (held, 'START_INTERRUPTED_HELD'),
             'r4_held_after_health_gate': (dict(held, interrupted=False, health_gate_passed=True, stage='RECEIPT'), 'START_HELD_AFTER_HEALTH_GATE'),
             'r4_held_trigger_bool': (dict(held, trigger_enabled_after=False), 'neither the r5 logon trigger state nor null'),
             'r4_held_not_recoverable': (dict(held, interrupted=False, stop_recovery_allowed=False), 'does not allow a stop recovery')}
    lines = [FX_READ, STUBS, '$out=[ordered]@{}']
    for name, (record, _) in cases.items():
        info = write_r4_receipt(tmp_path / name, lambda receipt: 'MISSING')
        root = Path(info['base']) / 'WardenRetarget4.2.7-windows-20261011-r4-v3'
        (root / 'warden-task-started.xml').unlink()
        if record is not None:
            (root / 'start-held.json').write_text(json.dumps(record), encoding='utf-8')
        lines.append(f"$script:RetargetTarget='r4';Set-StopConstants;$script:RecoverInterruptedStart=$true;Use-Fixture '{ps(info['base'])}' '{CONFIG_PIN}' '{BASE_PY_PIN}';"
                     "$script:r4BindingCalls=0;$m='';$receipt=$null;$bindings=$null;try{$receipt=Read-StartReceipt;$bindings=Assert-TargetRuntimeBindings $receipt}catch{$m=$_.Exception.Message};"
                     f"$out['{name}']=[ordered]@{{message=$m;receipt=$receipt;bindings=$bindings;expected_action=$script:expectedAction;trigger_count=@($script:expectedTriggers).Count;"
                     "allowed=@($script:allowedTriggerEnabled);binding=$script:startBinding;retarget_sha=$(if($receipt){$receipt.retarget_receipt_sha256}else{$null})}")
        cases[name] = (record, cases[name][1], info)
    lines.append('$out|ConvertTo-Json -Depth 6 -Compress')
    value = run_json('\n'.join(lines), tmp_path, timeout=300)
    for name, (record, expected, info) in cases.items():
        result = value[name]
        if not expected.startswith('START_'):
            assert expected in result['message'], (name, result['message'])
            continue
        assert result['message'] == '' and result['binding'] == expected and result['allowed'] == [] and result['trigger_count'] == 0, (name, result['message'])
        assert result['expected_action'] == {'execute': R4_PY, 'arguments': R4_RESTORE_ARGS, 'working_directory': R4_ROOT} and result['retarget_sha'] == info['retarget_sha256']
        assert result['receipt']['sha256'] is None and result['receipt']['source_task_xml_after_sha256'] == sha(TASK_XML_R4_DISABLED.encode())
        assert result['bindings']['runtime'] == 'r4' and result['bindings']['revision_sha256'] == R4_REVISION_PIN


def test_r4_bindings_and_pins_hold_against_the_installed_r4_runtime_read_only(tmp_path):
    """The reviewed v2.2 r4 bindings and the r4 pins, run over the real r4 files (read-only hashing, no protected-path API)."""
    if not Path(R4_ROOT, 'install-after.json').exists():
        pytest.skip('the r4 runtime is not installed on this host')
    body = FX_READ + r'''
      $script:RetargetTarget='r4';Set-StopConstants;$script:fxBase='C:\Program Files\CoChem'
      $m='';$b=$null;try{$b=Assert-TargetRuntimeBindings ([ordered]@{})}catch{$m=$_.Exception.Message}
      [ordered]@{message=$m;bindings=$b;reads=@($script:reads|ForEach-Object {[ordered]@{path=$_.path;hash=$_.hash}})}|ConvertTo-Json -Depth 5 -Compress'''
    value = run_json(body, tmp_path)
    assert value['message'] == '', value['message']
    assert value['bindings']['install_receipt_sha256'] == R4_INSTALL_PIN and value['bindings']['revision_sha256'] == R4_REVISION_PIN
    reads = {r['path']: r['hash'] for r in value['reads']}
    assert reads[R4_RESTORE_CONFIG] == CONFIG_PIN and reads[BASE_PY] == BASE_PY_PIN and reads[R4_ROOT + r'\source-manifest.json'] == R4_MANIFEST_PIN
    assert reads[R4_ROOT + r'\.venv\Lib\site-packages\cochem_pipeline\resource_telemetry.py'] == REPAIR_PIN
    assert reads[R4_PY] == '560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'


# --------------------------------------------------------------------------------------------------------------------
# Static checks
# --------------------------------------------------------------------------------------------------------------------

def ast_dump(path, workdir):
    body = (r"$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile('PATH',[ref]$t,[ref]$e);"
            r"$top=@($a.EndBlock.Statements|Where-Object {$_ -isnot [Management.Automation.Language.FunctionDefinitionAst]}|ForEach-Object {$_.Extent.Text});"
            r"$names=@($a.EndBlock.Statements|Where-Object {$_ -is [Management.Automation.Language.FunctionDefinitionAst]}|ForEach-Object {$_.Name});"
            r"$texts=[ordered]@{};foreach($f in $a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){$texts[$f.Name]=$f.Extent.Text};"
            r"$params=@($(if($a.ParamBlock){$a.ParamBlock.Parameters|ForEach-Object {[ordered]@{name=$_.Name.VariablePath.UserPath;default=$(if($_.DefaultValue){$_.DefaultValue.Extent.Text}else{$null});attributes=@($_.Attributes|ForEach-Object {$_.Extent.Text})}}}));"
            r"[ordered]@{errors=$e.Count;top=$top;names=$names;texts=$texts;params=$params;edition=$PSVersionTable.PSEdition;major=$PSVersionTable.PSVersion.Major}|ConvertTo-Json -Depth 5 -Compress").replace('PATH', ps(path))
    return run_json(body, workdir, prelude=False)


def lf(text):
    return text.replace('\r\n', '\n')


def test_script_parses_under_windows_powershell_51_is_ascii_and_has_one_invocation(tmp_path):
    raw = SCRIPT.read_bytes()
    assert raw.isascii(), 'the owner script is pure ASCII'
    value = ast_dump(SCRIPT, tmp_path)
    assert value['edition'] == 'Desktop' and value['major'] == 5, 'parsed by Windows PowerShell 5.1'
    assert value['errors'] == 0
    assert value['names'] == EXPECTED_NAMES, 'the script declares exactly the reviewed and the new functions'
    assert value['top'] == ['Invoke-StopWardenMain -ApplyRequested ([bool]$Apply)'], 'the top level is a single invocation'
    params = {p['name']: p for p in value['params']}
    assert list(params) == ['Apply', 'Attempt', 'RetargetAttempt', 'RetargetTarget', 'IdleWaitSeconds', 'ExitWaitSeconds', 'RecoverInterruptedStart']
    assert params['RecoverInterruptedStart']['default'] is None and params['RecoverInterruptedStart']['attributes'] == ['[switch]']
    assert params['Apply']['default'] is None and params['Attempt']['default'] == "'v1'"
    assert params['RetargetAttempt']['default'] is None and '[Parameter(Mandatory=$true)]' in params['RetargetAttempt']['attributes']
    assert params['RetargetTarget']['default'] == "'r5'" and "[ValidateSet('r5','r4',IgnoreCase=$false)]" in params['RetargetTarget']['attributes']
    assert params['IdleWaitSeconds']['default'] == '120' and params['ExitWaitSeconds']['default'] == '90'
    assert raw.startswith(b'#Requires -Version 5.1')


def test_reused_functions_are_identical_to_the_reviewed_predecessors(tmp_path):
    assert sha(V22.read_bytes()) == V22_SHA256 and sha(STOP_R4.read_bytes()) == STOP_R4_SHA256
    mine = ast_dump(SCRIPT, tmp_path)['texts']
    v22 = ast_dump(V22, tmp_path)['texts']
    stop_r4 = ast_dump(STOP_R4, tmp_path)['texts']
    # The predecessors are CRLF files; the comparison is exact apart from the line terminator.
    for name in REUSED_V22:
        assert lf(mine[name]) == lf(v22[name]), name
    for name in REUSED_STOP_R4:
        assert lf(mine[name]) == lf(stop_r4[name]), name
    old_line = '$rooted=$path -and ($path.StartsWith($script:r3Root,[StringComparison]::OrdinalIgnoreCase) -or $path.StartsWith($script:r4Root,[StringComparison]::OrdinalIgnoreCase) -or $path.StartsWith($script:basePythonRoot,[StringComparison]::OrdinalIgnoreCase))'
    new_line = '$rooted=$path -and ($path.StartsWith($script:runtimePrefix,[StringComparison]::OrdinalIgnoreCase) -or $path.StartsWith($script:basePythonRoot,[StringComparison]::OrdinalIgnoreCase))'
    assert old_line in v22['Get-ControllerPresence'] and v22['Get-ControllerPresence'].count(OLD_CLIENT_LINE) == 1
    # Two deltas: the rooted test (every runtime root, r5 included) and the 2026-10-11 17:22 client line (the Antigravity
    # bridge), which is the same line stop-warden-r4.ps1 carries.
    assert lf(mine['Get-ControllerPresence']) == lf(v22['Get-ControllerPresence']).replace(old_line, new_line).replace(OLD_CLIENT_LINE, NEW_CLIENT_LINE)
    assert stop_r4['Get-ControllerPresence'].count(NEW_CLIENT_LINE) == 1, 'stop-warden-r4.ps1 classifies the bridge with the same line'
    for dropped in ('Assert-StopRuntimePins', 'Get-ProcessProof', 'Assert-R3Commissioning', 'Assert-RetargetSource',
                    'Invoke-Retarget', 'Invoke-StartOnce', 'Backup-PrivateDatabases'):
        assert dropped not in mine, dropped
    assert 'function Assert-R4Pins' in mine['Assert-R4Pins'] and '$script:r4InstallPin' in mine['Assert-R4Pins'] and '$script:r4RevisionPin' in mine['Assert-R4Pins']


def test_pins_helper_hashes_and_forbidden_operations():
    text = SCRIPT.read_text(encoding='ascii')
    helpers = {Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1'): '0300b827',
               ROOT / 'check-worker-native-status-r3.ps1': '18f58ebb', REGISTER: 'eccc593f', ROOT / 'protected-code-inspection-v4.ps1': '5c01543c'}
    for path, prefix in helpers.items():
        digest = sha(path.read_bytes())
        assert digest.startswith(prefix) and f"'{digest}'" in text, path
    for pin in (f"$script:probePythonPin='{BASE_PY_PIN}'", f"$script:configPin='{CONFIG_PIN}'", f"$script:r4InstallPin='{R4_INSTALL_PIN}'",
                f"$script:r4ManifestPin='{R4_MANIFEST_PIN}'", f"$script:r4RevisionPin='{R4_REVISION_PIN}'", f"$script:r3RevisionPin='{R3_REVISION_PIN}'",
                f"$script:repairPin='{REPAIR_PIN}'", f"$script:r3ManifestPin='{R3_MANIFEST_PIN}'", f"$script:r3InstallPin='{R3_INSTALL_PIN}'",
                "'0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d'", "'560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'",
                "$script:retargetNamespaceDate='20261011';$script:stopNamespaceDate='20261011'", '$script:expectedEndResult=267014',
                '$script:healthSpacingSeconds=5;$script:idlePollSeconds=10;$script:exitPollSeconds=3', "$script:logonUser='AETHERDESK\\ansac';$script:logonDelay='PT1M'",
                f"$script:clientConfig='{CLIENT_CONFIG}';$script:clientTokenFile='{TOKEN_FILE}'", "$script:taskName='CoChem-4.2.7-Warden';$script:port=47824"):
        assert pin in text, pin
    for forbidden in ('Stop-ScheduledTask', 'Disable-ScheduledTask', 'Register-ScheduledTask', 'Unregister-ScheduledTask', 'Start-ScheduledTask', 'RegisterTaskDefinition',
                      'schtasks', 'Start-Process', 'Stop-Process', 'taskkill', '.Run(', 'Remove-Item', 'DeleteTask', 'Stop-Service', '.Kill(', 'Invoke-Expression',
                      'Copy-VerifiedPayload', 'CoChem-4.2.7-HeldSupervisorObservation', 'CoChem-4.2.7-ResourceObservation', '/MIR', 'robocopy', 'Enabled=$true',
                      'queue-retarget-20261010-r4-v1', 'fbfdcd8318d2418cbb8d28badad53a1a8e829a1e9c7143d13600bb62fd04c2be'):
        assert forbidden not in text, forbidden
    assert text.count('.Stop(0)') == 1 and text.count('.Enabled=$false') == 1, 'one End request and one disable'
    assert text.count('.GetTask(') == 2, 'only the Warden and the three managed daemon names are ever looked up'
    assert "retarget_target=$script:RetargetTarget" in text and text.count('retarget_target=') == 6, 'intent, receipt, both held records, result and plan'
    assert text.count("'-X','utf8'") == 3, 'health, bind probe and operator snapshot all run with -X utf8'
    assert 'WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED' in text and 'WARDEN_ALREADY_STOPPED_CLEAN_NOOP' in text
    assert "schema='cochem-warden-stop/2'" in text and "schema='cochem-warden-stop-result/2'" in text and "schema='cochem-warden-stop-plan/2'" in text


def test_r4_lineage_pins_recompute_from_the_installed_r4_receipts():
    for path, pin in ((Path(R4_ROOT) / 'install-after.json', R4_INSTALL_PIN), (Path(R4_ROOT) / 'source-manifest.json', R4_MANIFEST_PIN),
                      (Path(HELD_CONFIG), CONFIG_PIN), (Path(BASE_PY), BASE_PY_PIN)):
        if not path.exists():
            pytest.skip(f'{path} is not on this host')
        assert sha(path.read_bytes()) == pin, path
    after = json.loads((Path(R4_ROOT) / 'install-after.json').read_text(encoding='utf-8-sig'))
    assert after['verification']['revision']['source_sha256'] == R4_REVISION_PIN and after['verification']['revision']['files'] == 109
    assert after['source_files'] == 166 and after['runtime_bindings']['base_root'] == BASE_ROOT and after['verification']['ram_workspace_root'] == 'R:\\CoChem427-windows-20261007'


def test_r4_pins_match_retarget_warden_r5():
    sibling = ROOT / 'retarget-warden-r5.ps1'
    if not sibling.exists():
        pytest.skip('retarget-warden-r5.ps1 is not in the workspace')
    theirs = sibling.read_text(encoding='utf-8')
    mine = SCRIPT.read_text(encoding='ascii')
    for name in ('configPin', 'probePythonPin', 'r3ManifestPin', 'r3InstallPin', 'r3RevisionPin', 'r4ManifestPin', 'repairPin', 'r4InstallPin', 'r4RevisionPin'):
        pattern = r"\$script:" + name + r"='([a-f0-9]{64})'"
        a, b = re.search(pattern, mine), re.search(pattern, theirs)
        assert a and b and a.group(1) == b.group(1), name
    assert "'WARDEN_R4_RESTARTED_HEALTH_VERIFIED'" in theirs and "'queue-restart-'" in theirs, 'the r4 restore status and queue namespace this stop binds'


def test_c_f4_pins_are_the_reviewed_freeze_manifest_and_the_installer_pins(tmp_path):
    """C-F4: the freeze manifest sha 5d8d337b..., its 13 repair digests, and the installer's pyvenv.cfg and venv launcher pins."""
    raw = (ROOT / 'stopped-runtime-r5-source-manifest.json').read_bytes()
    assert sha(raw) == R5_MANIFEST_PIN
    manifest = json.loads(raw)
    assert manifest['source_commit'] == R5_SOURCE_COMMIT and manifest['verified_unchanged'] == 153 and sorted(manifest['reviewed_repairs']) == REPAIRS
    assert manifest['target_root'] == R5_ROOT and manifest['previous_source_manifest_sha256'] == R4_MANIFEST_PIN
    text = SCRIPT.read_text(encoding='ascii')
    block = text[text.index('$script:r5RepairPins=[ordered]@{'):]
    block = block[:block.index('}')]
    pins = dict(re.findall(r"'([^']+)'='([a-f0-9]{64})'", block))
    assert pins == manifest['reviewed_repairs_sha256'] and len(pins) == 13
    installer = (ROOT / 'install-stopped-runtime-r5.ps1').read_text(encoding='utf-8')
    installer_block = installer[installer.index('$script:reviewedRepairPins=[ordered]@{'):]
    installer_block = installer_block[:installer_block.index('}')]
    assert dict(re.findall(r"'([^']+)'='([a-f0-9]{64})'", installer_block)) == pins, 'the installer installed exactly these digests'
    assert f"$cfgHash='{PYVENV_PIN}'" in installer and f"$exeHash='{VENV_PYTHON_PIN}'" in installer
    for line in (f"$script:r5ManifestPin='{R5_MANIFEST_PIN}'", f"$script:r5PyvenvPin='{PYVENV_PIN}';$script:r5VenvPythonPin='{VENV_PYTHON_PIN}'",
                 '$script:r5VerifiedUnchanged=153'):
        assert line in text, line
    value = run_json('[ordered]@{manifest=$script:r5ManifestPin;repairs=$script:r5RepairPins;pyvenv=$script:r5PyvenvPin;venv=$script:r5VenvPythonPin;unchanged=$script:r5VerifiedUnchanged;'
                     'paths=$script:reviewedRepairPaths}|ConvertTo-Json -Depth 4 -Compress', tmp_path)
    assert value['manifest'] == R5_MANIFEST_PIN and value['repairs'] == pins and value['pyvenv'] == PYVENV_PIN and value['venv'] == VENV_PYTHON_PIN
    assert value['unchanged'] == 153 and sorted(value['paths']) == sorted(pins), 'the A6 path list and the pinned digests name the same 13 files'


def test_c_f4_pins_match_retarget_warden_r5():
    """The stop never admits a build the cutover refuses, nor refuses one it admits: both pin the same reviewed freeze."""
    sibling = ROOT / 'retarget-warden-r5.ps1'
    theirs = sibling.read_text(encoding='utf-8') if sibling.exists() else ''
    if '$script:r5RepairPins=[ordered]@{' not in theirs:
        pytest.skip('retarget-warden-r5.ps1 does not pin the r5 freeze')

    def pins(text):
        block = text[text.index('$script:r5RepairPins=[ordered]@{'):]
        return dict(re.findall(r"'([^']+)'='([a-f0-9]{64})'", block[:block.index('}')]))
    mine = SCRIPT.read_text(encoding='ascii')
    assert pins(mine) == pins(theirs) and len(pins(mine)) == 13
    manifest = re.search(r"\$script:r5(?:Source)?ManifestPin='([a-f0-9]{64})'", theirs)
    assert manifest and manifest.group(1) == R5_MANIFEST_PIN
    for name, value in (('r5PyvenvPin', PYVENV_PIN), ('r5VenvPythonPin', VENV_PYTHON_PIN)):
        assert f"$script:{name}='{value}'" in theirs and f"$script:{name}='{value}'" in mine, name
    assert '$script:r5VerifiedUnchanged=153' in theirs and "'install-held.json'" in theirs


def test_reviewed_repair_set_is_the_spec_list_plus_main_from_the_addendum(tmp_path):
    spec = json.loads(SPEC.read_text(encoding='utf-8'))
    listed = [entry.split()[0] for entry in spec['r5_changed_files'] if entry.startswith('src/')]
    addendum = ADDENDUM.read_text(encoding='utf-8')
    assert len(listed) == 12 and 'PLUS src/cochem_pipeline/__main__.py' in addendum and '13 changed' in addendum
    assert sorted(listed + ['src/cochem_pipeline/__main__.py']) == REPAIRS
    value = run_json('@{repairs=$script:reviewedRepairPaths}|ConvertTo-Json -Compress', tmp_path)
    assert sorted(value['repairs']) == REPAIRS and len(set(value['repairs'])) == 13


def test_constants_snippets_and_namespaces(tmp_path):
    value = run_json(r'''$v=[ordered]@{health=$script:healthCall;operator=$script:operatorCall;target=$script:targetRoot;retarget=$script:retargetRoot;start=$script:startReceiptPath;
      args=(Get-R5ExpectedArguments 'CFG');prefix=$script:runtimePrefix;bound=($null -eq $script:expectedAction -and $null -eq $script:runtimePython)}
      $script:RetargetTarget='r4';$script:RetargetAttempt='v7';$script:Attempt='v2';Set-StopConstants
      $v.r4=[ordered]@{target=$script:targetRoot;retarget=$script:retargetRoot;start=$script:startReceiptPath;queue=$script:queueRestart;config=$script:r4RestoreConfig;
        args=(Get-ExpectedArguments $script:r4RestoreConfig $script:queueRestart);python=$script:r4Python;source=$script:r4SourceRoot}
      $v|ConvertTo-Json -Compress''', tmp_path)
    for snippet in (value['health'], value['operator']):
        assert '"' not in snippet, 'single-quoted Python only (Windows PowerShell 5.1 native argument passing)'
        assert "type(config.get('port')) is not int or config.get('port')!=port or config.get('token_file')!=sys.argv[2]:\n    sys.exit(3)" in snippet
        assert 'client=ControlClient(port,sys.argv[2])' in snippet and 'port=int(sys.argv[3])' in snippet
    assert "client.call('/health')" in value['health'] and "client.call('/operator')" in value['operator']
    assert "'jobs_truncated'" in value['operator'] and "'window':view" in value['operator']
    assert value['target'] == STOP_ROOT_V1 and value['retarget'] == RETARGET_ROOT and value['start'] == START_RECEIPT
    assert value['args'] == f'-I -B -m cochem_pipeline daemon --config "CFG" --queue-launch-output-root "{QUEUE_ROOT}" --docker-wait-seconds 900'
    assert value['prefix'] == COCHEM + r'\Pipeline4.2.7-windows-' and value['bound'] is True, 'nothing is bound before the start receipt'
    r4 = value['r4']
    assert r4['target'] == COCHEM + r'\WardenStop4.2.7-windows-20261011-r5-v2', 'one stop namespace whichever runtime is stopped'
    assert r4['retarget'] == COCHEM + r'\WardenRetarget4.2.7-windows-20261011-r4-v7' and r4['start'] == r4['retarget'] + r'\start-receipt.json'
    assert r4['queue'] == queue_restart('v7') and r4['config'] == R4_RESTORE_CONFIG and r4['args'] == r4_restore_args('v7')
    assert r4['python'] == R4_PY and r4['source'] == R4_SOURCE


def test_main_runs_the_owner_gate_before_any_import_or_scheduler_access(tmp_path):
    texts = ast_dump(SCRIPT, tmp_path)['texts']
    main = texts['Invoke-StopWardenMain']
    order = [main.index(token) for token in ("$PSVersionTable.PSEdition -ne 'Desktop' -or -not [Environment]::Is64BitProcess -or $env:COMPUTERNAME -cne 'AETHERDESK'",
                                             'Assert-ApplyIdentity $ApplyRequested $script:admin $identity.Name', 'Set-StopConstants', 'Import-ReviewedFunctions',
                                             'Initialize-FileIdentity', "New-Object -ComObject 'Schedule.Service'", 'Invoke-StopWardenSession $folder $ApplyRequested|ConvertTo-Json')]
    assert order == sorted(order)
    assert 'foreach($stream in $held){$stream.Dispose()}' in main
    session = texts['Invoke-StopWardenSession']
    assert session.index('if(-not $ApplyRequested){return $plan}') < session.index("if($holds.Count){throw ('The Warden stop is held. Nothing was changed: '") < session.index('Invoke-StopWarden $Folder')
    helper = REGISTER.read_text(encoding='utf-8')
    assert '[Text.UTF8Encoding]::new($false).GetBytes($Text)' in helper and '[IO.FileMode]::CreateNew' in helper, \
        'Write-RegistrationControl stores the same UTF-8 (no BOM) bytes Get-TaskXmlSha256 hashes, CreateNew'


def test_this_harness_never_runs_the_script_top_level_except_through_the_plan_mode_smoke_runner():
    source = Path(__file__).read_text(encoding='utf-8')
    assert ("'-" + "File'") not in source and ('-' + 'Apply' + "'") not in source, 'no direct whole-script run, no -Apply argument'
    # The top-level smoke tests run through ps_toplevel_smoke's runner only (host stubbed, -Apply refused before any
    # process starts), from one helper that re-checks its arguments first.
    call = 'smoke.' + 'run_toplevel('
    assert source.count(call) == 1, 'one top-level runner call'
    helper = source[source.index('\ndef smoke_plan('):]
    helper = helper[:helper.index('\n\n\n')]
    assert call in helper and helper.index('smoke.apply_argument(args) is None') < helper.index(call)


# --------------------------------------------------------------------------------------------------------------------
# Parameters, owner gate, native judging, task XML digest
# --------------------------------------------------------------------------------------------------------------------

PARAM_CASES = {
    'defaults': ("-RetargetAttempt v3", None),
    'all_given': ("-Apply -Attempt v12 -RetargetAttempt v2 -IdleWaitSeconds 900 -ExitWaitSeconds 10", None),
    'retarget_missing': ("-Attempt v1", 'RetargetAttempt'),
    'retarget_invalid': ("-RetargetAttempt 2", 'RetargetAttempt'),
    'attempt_invalid': ("-Attempt x1 -RetargetAttempt v3", 'Attempt'),
    'attempt_long': ("-Attempt v1000 -RetargetAttempt v3", 'Attempt'),
    'idle_too_short': ("-RetargetAttempt v3 -IdleWaitSeconds 5", 'IdleWaitSeconds'),
    'exit_too_long': ("-RetargetAttempt v3 -ExitWaitSeconds 901", 'ExitWaitSeconds'),
    'target_r4': ("-RetargetAttempt v4 -RetargetTarget r4", None),
    'target_r6': ("-RetargetAttempt v3 -RetargetTarget r6", 'RetargetTarget'),
    'target_uppercase': ("-RetargetAttempt v3 -RetargetTarget R4", 'RetargetTarget'),
    'target_empty': ("-RetargetAttempt v3 -RetargetTarget ''", 'RetargetTarget'),
    'recover_interrupted_start': ("-Apply -Attempt v2 -RetargetAttempt v1 -RecoverInterruptedStart", None),
}


def test_parameter_block_validation_without_running_the_script(tmp_path):
    lines = [r"$attr=($ast.ParamBlock.Attributes|ForEach-Object {$_.Extent.Text}) -join ''",
             r". ([scriptblock]::Create('function Test-StopParameters { '+$attr+[Environment]::NewLine+$ast.ParamBlock.Extent.Text+[Environment]::NewLine+' [ordered]@{Apply=[bool]$Apply;Attempt=$Attempt;RetargetAttempt=$RetargetAttempt;RetargetTarget=$RetargetTarget;IdleWaitSeconds=$IdleWaitSeconds;ExitWaitSeconds=$ExitWaitSeconds;RecoverInterruptedStart=[bool]$RecoverInterruptedStart} }'))",
             '$out=[ordered]@{}']
    for name, (args, _) in PARAM_CASES.items():
        lines.append(f"$v=$null;$m='';try{{$v=Test-StopParameters {args}}}catch{{$m=$_.Exception.Message}};$out['{name}']=[ordered]@{{value=$v;message=$m}}")
    lines.append('$out|ConvertTo-Json -Depth 4 -Compress')
    value = run_json('\n'.join(lines), tmp_path)
    for name, (_, expected) in PARAM_CASES.items():
        if expected is None:
            assert value[name]['message'] == '', (name, value[name])
        else:
            assert value[name]['value'] is None and expected in value[name]['message'], (name, value[name])
    assert value['defaults']['value'] == {'Apply': False, 'Attempt': 'v1', 'RetargetAttempt': 'v3', 'RetargetTarget': 'r5', 'IdleWaitSeconds': 120, 'ExitWaitSeconds': 90,
                                          'RecoverInterruptedStart': False}
    assert value['all_given']['value'] == {'Apply': True, 'Attempt': 'v12', 'RetargetAttempt': 'v2', 'RetargetTarget': 'r5', 'IdleWaitSeconds': 900, 'ExitWaitSeconds': 10,
                                           'RecoverInterruptedStart': False}
    assert value['recover_interrupted_start']['value']['RecoverInterruptedStart'] is True and value['recover_interrupted_start']['value']['RetargetTarget'] == 'r5'
    assert value['target_r4']['value']['RetargetTarget'] == 'r4' and value['target_r4']['value']['RetargetAttempt'] == 'v4'


def test_apply_requires_the_elevated_owner(tmp_path):
    cases = {'apply_owner_admin': ('$true', '$true', 'AETHERDESK\\ansac', False), 'apply_not_admin': ('$true', '$false', 'AETHERDESK\\ansac', True),
             'apply_other_user': ('$true', '$true', 'AETHERDESK\\other', True), 'apply_case_variant': ('$true', '$true', 'aetherdesk\\ansac', True),
             'plan_not_admin': ('$false', '$false', 'AETHERDESK\\ansac', False), 'plan_other_user': ('$false', '$false', 'AETHERDESK\\other', False)}
    lines = ['$out=[ordered]@{}']
    for name, (apply, admin, user, _) in cases.items():
        lines.append(f"$m='';try{{Assert-ApplyIdentity {apply} {admin} '{user}'}}catch{{$m=$_.Exception.Message}};$out['{name}']=$m")
    lines.append('$out|ConvertTo-Json -Compress')
    value = run_json('\n'.join(lines), tmp_path)
    for name, (_, _, _, refused) in cases.items():
        assert (value[name] == '-Apply requires the owner in Administrator Windows PowerShell; nothing was changed.') is refused, name
        assert refused or value[name] == ''


@pytest.mark.parametrize('case', ['stderr_exit_0', 'stderr_exit_1', 'missing_executable'])
def test_native_commands_are_judged_by_exit_code_not_stderr(tmp_path, case):
    program = {'stderr_exit_0': "import sys;sys.stderr.write('warn');print('out');sys.exit(0)",
               'stderr_exit_1': "import sys;sys.stderr.write('boom');sys.exit(1)", 'missing_executable': "print('unused')"}[case]
    fixture = tmp_path / 'native.py'
    fixture.write_text(program, encoding='utf-8')
    executable = sys.executable if case != 'missing_executable' else str(tmp_path / 'no-such-python.exe')
    value = run_json(f"$refused=$false;$r=$null;try{{$r=Invoke-NativeJudged '{ps(executable)}' @('-I','-B','-X','utf8','{ps(fixture)}')}}catch{{$refused=$true}};"
                     "[ordered]@{refused=$refused;code=$(if($r){$r.code}else{$null});stdout=$(if($r){$r.stdout}else{$null});stderr=$(if($r){$r.stderr}else{$null});preference=[string]$ErrorActionPreference}|ConvertTo-Json -Compress", tmp_path)
    assert value['preference'] == 'Stop'
    if case == 'missing_executable':
        assert value['refused'] is True
        return
    assert value['refused'] is False and value['code'] == (1 if case == 'stderr_exit_1' else 0)
    if case == 'stderr_exit_0':
        assert value['stdout'] == 'out' and 'warn' in value['stderr']


def test_task_xml_sha256_is_the_utf8_no_bom_digest_of_the_exact_string(tmp_path):
    strings = {'ascii': TASK_XML, 'crlf': '<Task>\r\n  <Settings/>\r\n</Task>\r\n', 'non_ascii': '<Task><Description>\u00e9\u4e2d</Description></Task>', 'empty': ''}
    body = [r"$s=[ordered]@{ascii='ASCII';crlf=('<Task>'+[char]13+[char]10+'  <Settings/>'+[char]13+[char]10+'</Task>'+[char]13+[char]10);non_ascii=('<Task><Description>'+[char]0x00E9+[char]0x4E2D+'</Description></Task>');empty=''}".replace('ASCII', ps(TASK_XML)),
            '$out=[ordered]@{}',
            r"foreach($k in @($s.Keys)){$p=Join-Path 'DIR' ($k+'.xml');[IO.File]::WriteAllBytes($p,[Text.UTF8Encoding]::new($false).GetBytes($s[$k]));$out[$k]=[ordered]@{sha=(Get-TaskXmlSha256 $s[$k]);file=(Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant()}}".replace('DIR', ps(tmp_path)),
            '$out|ConvertTo-Json -Compress']
    value = run_json('\n'.join(body), tmp_path)
    for name, text in strings.items():
        expected = sha(text.encode('utf-8'))
        assert value[name]['sha'] == expected == value[name]['file'], name
    assert value['non_ascii']['sha'] != sha(b'\xef\xbb\xbf' + strings['non_ascii'].encode('utf-8')), 'no BOM'


# --------------------------------------------------------------------------------------------------------------------
# Start receipt and r5 installation binding (dynamic pins bound by content)
# --------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('case', list(BINDING_CASES))
def test_start_receipt_and_r5_install_binding_table(binding_results, case):
    _, expected = BINDING_CASES[case]
    result = binding_results['results'][case]
    if expected:
        assert expected in result['message'], result['message']
        return
    assert result['message'] == '' and result['stage'] == 'done', result['message']
    receipt = result['receipt']
    config = HELD_CONFIG if case == 'held_config_fallback' else R5_CONFIG
    assert result['expected_action'] == {'execute': R5_PY, 'arguments': r5_args(config), 'working_directory': R5_ROOT}
    assert result['runtime_root'] == R5_ROOT and result['runtime_python'] == R5_PY and result['runtime_source'] == R5_SOURCE
    assert len(result['expected_triggers']) == 1 and result['expected_triggers'][0]['type'] == 'logon' and result['expected_triggers'][0]['delay'] == 'PT1M'
    assert receipt['sha256'] == binding_results['cases'][case]['receipt_sha256'] and receipt['controller_bound'] is False
    assert receipt['runtime_root'] == R5_ROOT and receipt['config_path'] == config and receipt['source_attempt'] == 'v1'
    bindings = result['bindings']
    assert bindings['runtime'] == 'r5' and receipt['target'] == 'r5'
    assert bindings['install_after_sha256'] == receipt['install_after_sha256'] and bindings['task_config_path'] == config
    assert bindings['task_config_sha256'] == receipt['config_sha256'] and bindings['previous_install_receipt_sha256'] == R4_INSTALL_PIN
    repairs = sorted(REPAIRS)
    assert sorted(bindings['reviewed_repairs_sha256']) == repairs and bindings['reviewed_repairs'] == repairs, 'ordinal-sorted, one digest per repair'
    assert bindings['a6_repair_set'] is True and bindings['a6_repair_set_asserted'] is True and bindings['freeze_manifest_pinned'] is True, \
        'C-F4: the 13 repairs of the pinned freeze are asserted, as retarget-warden-r5 asserts them'
    assert bindings['installed_repairs_verified'] is True and bindings['verified_unchanged'] == 153 and bindings['install_held_record_absent'] is True
    info = binding_results['cases'][case]
    assert bindings['source_manifest_sha256'] == info['pins']['manifest'] and bindings['pyvenv_sha256'] == info['pins']['pyvenv']
    reads = {(r['path'], r['hash']) for r in result['reads']}
    unpinned = [r['path'] for r in result['reads'] if not r['hash']]
    attempt = Path(info['base']) / 'WardenRetarget4.2.7-windows-20261011-r5-v3'
    start_receipt = str(attempt / 'start-receipt.json')
    assert unpinned == [start_receipt] and receipt['path'] == start_receipt, 'only the start receipt is read without a pin; every other file is digest-bound'
    assert (str(attempt / 'start-intent.json'), info['intent_sha256']) in reads and (str(attempt / 'retarget-receipt.json'), info['retarget_sha256']) in reads
    assert (str(attempt / 'warden-task-after.xml'), info['after_xml_sha256']) in reads and (str(attempt / 'warden-task-started.xml'), info['started_xml_sha256']) in reads
    assert info['after_xml_sha256'] == sha(SOURCE_XML.encode()) and info['started_xml_sha256'] == sha(TASK_XML.encode())
    assert (R5_ROOT + r'\install-after.json', receipt['install_after_sha256']) in reads
    assert (R5_ROOT + r'\pipeline.json', info['config_pin']) in reads
    assert (config, receipt['config_sha256']) in reads and (BASE_PY, info['probe_pin']) in reads
    for relative in repairs:
        digest = sha(repair_bytes(relative))
        assert bindings['reviewed_repairs_sha256'][relative] == digest
        assert (R5_ROOT + '\\source\\' + relative.replace('/', '\\'), digest) in reads
        assert (R5_ROOT + '\\.venv\\Lib\\site-packages\\' + relative[4:].replace('/', '\\'), digest) in reads
    assert len(result['reads']) == 12 + 2 * len(repairs)
    sizes = {r['path']: r['maximum'] for r in result['reads']}
    assert sizes[start_receipt] == 1048576 and sizes[R5_ROOT + r'\install-after.json'] == 1048576, 'receipts are read with a size cap'
    # The completed start binds the whole attempt chain and admits only an enabled logon trigger (two-phase start).
    assert receipt['binding'] == result['start_binding'] == 'START_RECEIPT' and result['allowed'] == [True]
    assert receipt['retarget_receipt_sha256'] == info['retarget_sha256'] and receipt['start_intent_sha256'] == info['intent_sha256']
    assert receipt['start_held_sha256'] is None and receipt['start_held_path'] is None
    assert receipt['source_task_xml_after_sha256'] == info['after_xml_sha256'] and receipt['source_task_xml_started_sha256'] == info['started_xml_sha256']
    assert receipt['task_xml_sha256'] == info['started_xml_sha256'] and result['source_xml_bound'] is True and result['started_xml_bound'] is True


def test_without_the_switch_an_interrupted_start_is_refused_and_the_switch_is_named(binding_results):
    """Default binding stays START_RECEIPT only: a start-held.json or an intent without a receipt points at -RecoverInterruptedStart."""
    missing = binding_results['results']['receipt_missing']['message']
    assert 'start receipt is missing' in missing and 'start-intent.json without a start receipt' in missing and '-RecoverInterruptedStart' in missing
    held = binding_results['results']['start_held_present']['message']
    assert 'holds start-held.json' in held and 'bind it with -RecoverInterruptedStart' in held


# --------------------------------------------------------------------------------------------------------------------
# C-F1(b): -RecoverInterruptedStart binds an interrupted, held or crashed start through the same attempt's retarget receipt
# --------------------------------------------------------------------------------------------------------------------

INTERRUPTED_CASES = {
    # name: (mutator, refusal fragment or '', binding, admitted live trigger Enabled states)
    'crashed_no_record': (no_start_receipt, '', 'START_CRASHED_NO_RECORD', [True, False]),
    'interrupted_held_trigger_disabled': (held_record(), '', 'START_INTERRUPTED_HELD', [False]),
    'interrupted_held_after_trigger_enable': (held_record(stage='RECEIPT', health_gate_passed=True, trigger_enable_requested=True, trigger_enabled_after=True), '',
                                              'START_INTERRUPTED_HELD', [True]),
    'interrupted_held_trigger_unreadable': (held_record(task_readable=False, trigger_enabled_after=None), '', 'START_INTERRUPTED_HELD', [True, False]),
    'held_after_health_gate': (held_record(interrupted=False, health_gate_passed=True, stage='TRIGGER_ENABLE', trigger_enable_requested=True), '',
                               'START_HELD_AFTER_HEALTH_GATE', [False]),
    # Re-audit R-F1: every hold after Run is stop-recoverable (stop_recovery_allowed = (not held_before_run) or interrupted),
    # including a health gate that timed out (sweep N1) or failed hard (sweep N2); before-Run holds use the retarget's no-stop path.
    'held_before_health_gate_knowledge_timeout': (held_record(interrupted=False, reason='post-start readiness not met: knowledge is not ready'), '',
                                                  'START_HELD_BEFORE_HEALTH_GATE', [False]),
    'held_before_health_gate_hard_gate': (held_record(interrupted=False, reason='the controller reports 1 execution quarantine row(s)'), '',
                                          'START_HELD_BEFORE_HEALTH_GATE', [False]),
    'held_before_health_gate_trigger_unreadable': (held_record(interrupted=False, task_readable=False, trigger_enabled_after=None), '',
                                                   'START_HELD_BEFORE_HEALTH_GATE', [True, False]),
    'held_after_run_not_recoverable': (held_record(interrupted=False, stop_recovery_allowed=False), 'does not allow a stop recovery', None, None),
    'held_before_run': (held_record(interrupted=False, stage='BEFORE_RUN', run_requested=False, held_before_run=True, instance_guid=None, stop_recovery_allowed=False),
                        'held before Run', None, None),
    'held_before_run_claims_recovery': (held_record(interrupted=False, stage='BEFORE_RUN', run_requested=False, held_before_run=True, instance_guid=None),
                                        'held before Run', None, None),
    'interrupted_before_run': (held_record(stage='BEFORE_RUN', run_requested=False, held_before_run=True, instance_guid=None), 'held before Run', None, None),
    'held_run_threw_without_instance': (held_record(interrupted=False, stage='RUN', run_exception='The task cannot start.', held_before_run=True, instance_guid=None,
                                                    stop_recovery_allowed=False), 'held before Run', None, None),
    'held_before_run_flag_missing': (held_record(held_before_run=DELETE), 'does not allow a stop recovery', None, None),
    'held_before_run_flag_string': (held_record(held_before_run='false'), 'does not allow a stop recovery', None, None),
    'held_gate_flag_missing': (held_record(health_gate_passed=DELETE), 'does not allow a stop recovery', None, None),
    'held_recovery_flag_string': (held_record(stop_recovery_allowed='true'), 'does not allow a stop recovery', None, None),
    'held_recovery_flag_missing': (held_record(stop_recovery_allowed=DELETE), 'does not allow a stop recovery', None, None),
    'held_interrupted_string': (held_record(interrupted='true'), 'does not allow a stop recovery', None, None),
    'held_receipt_written': (held_record(receipt_written=True), 'is not a held start of this -RetargetAttempt', None, None),
    'held_other_attempt': (held_record(attempt='v2'), 'is not a held start of this -RetargetAttempt', None, None),
    'held_schema_v2': (held_record(schema='cochem-warden-start-held/2'), 'is not a held start of this -RetargetAttempt', None, None),
    'held_trigger_state_string': (held_record(trigger_enabled_after='false'), 'neither the r5 logon trigger state nor null', None, None),
    'held_not_json': (chain(held_record(), set_ctx('held_record', b'{"interrupted":')), 'r5 start-held record is not a JSON object', None, None),
    'completed_start_with_switch': (None, 'holds a start receipt: the start completed, so bind it without -RecoverInterruptedStart', None, None),
    'intent_missing': (chain(no_start_receipt, post(ATTEMPT_FILE['start-intent.json'], None)), 'has no start-intent.json', None, None),
    'intent_names_other_retarget_receipt': (chain(no_start_receipt, edit('intent', 'retarget_receipt_sha256', value='0' * 64)), 'Source digest changed', None, None),
    'intent_other_attempt': (chain(no_start_receipt, edit('intent', 'attempt', value='v2')), 'The start intent is not a start request of this -RetargetAttempt', None, None),
    'intent_other_target': (chain(no_start_receipt, edit('intent', 'target', value='r4')), 'The start intent is not a start request of this -RetargetAttempt', None, None),
    'intent_other_runtime_root': (chain(no_start_receipt, edit('intent', 'runtime_root', value=R4_ROOT)), 'does not name the runtime root of its retarget receipt', None, None),
    'retarget_receipt_missing': (chain(no_start_receipt, post(ATTEMPT_FILE['retarget-receipt.json'], None)), 'r5 retarget receipt is missing', None, None),
    'retarget_receipt_other_attempt': (chain(no_start_receipt, retarget_edit('attempt', value='v2')), 'The retarget receipt does not name this -RetargetAttempt', None, None),
    'retarget_receipt_r4_restore': (chain(no_start_receipt, retarget_edit('status', value='WARDEN_RETARGETED_TO_R4_NOT_STARTED')),
                                    'not a successful r5 retarget registered disabled', None, None),
    'retarget_receipt_action_other_config': (chain(no_start_receipt, retarget_edit('action', 'arguments', value=r5_args(HELD_CONFIG))),
                                             'The retarget receipt action is not the reviewed r5 daemon action', None, None),
    'retarget_receipt_action_r4_python': (chain(no_start_receipt, retarget_edit('action', 'execute', value=R4_PY)),
                                          'The retarget receipt action is not the reviewed r5 daemon action', None, None),
    'retarget_receipt_trigger_delay': (chain(no_start_receipt, retarget_edit('triggers', 0, 'delay', value='PT0S')), 'The retarget receipt trigger is not the reviewed logon trigger', None, None),
    'retarget_receipt_no_trigger': (chain(no_start_receipt, retarget_edit('triggers', value=[])), 'The retarget receipt does not record exactly one trigger', None, None),
    'retarget_receipt_runtime_r4': (chain(no_start_receipt, retarget_edit('runtime_root', value=R4_ROOT)), 'The retarget receipt does not name an r5 runtime root', None, None),
    'retarget_receipt_config_bytes_differ': (chain(no_start_receipt, retarget_edit('config_sha256', value='0' * 64)), 'Source digest changed', None, None),
    'retarget_receipt_install_receipt_differs': (chain(no_start_receipt, retarget_edit('install_after_sha256', value='0' * 64)), 'Source digest changed', None, None),
    'retarget_receipt_trigger_registered_enabled': (chain(no_start_receipt, retarget_edit('trigger_enabled_after', value=True)), 'does not record the two-phase registration', None, None),
    'retarget_held_present': (chain(no_start_receipt, add_held('retarget-held.json')), 'holds retarget-held.json', None, None),
    'source_xml_names_other_attempt': (chain(no_start_receipt, set_ctx('after_xml', SOURCE_XML.replace('retarget v3', 'retarget v2'))),
                                       'does not name that attempt in its Description', None, None),
    'source_xml_missing': (chain(no_start_receipt, post(ATTEMPT_FILE['warden-task-after.xml'], None)), 'retarget attempt registered is missing', None, None),
    'install_held_record_present': (chain(no_start_receipt, post(R5_ROOT + r'\install-held.json', b'{}')), 'holds install-held.json', None, None),
}


@pytest.fixture(scope='module')
def interrupted_results(tmp_path_factory):
    return run_binding_table(tmp_path_factory.mktemp('interrupted'), INTERRUPTED_CASES, True)


@pytest.mark.parametrize('case', list(INTERRUPTED_CASES))
def test_interrupted_or_crashed_start_binds_through_the_retarget_receipt(interrupted_results, case):
    _, expected, binding, allowed = INTERRUPTED_CASES[case]
    result = interrupted_results['results'][case]
    info = interrupted_results['cases'][case]
    if expected:
        assert expected in result['message'], result['message']
        assert result['stage'] == ('bindings' if case in ('retarget_receipt_config_bytes_differ', 'retarget_receipt_install_receipt_differs', 'install_held_record_present')
                                   else 'receipt'), result['stage']
        return
    assert result['message'] == '' and result['stage'] == 'done', result['message']
    receipt = result['receipt']
    assert receipt['binding'] == result['start_binding'] == binding and result['allowed'] == allowed
    assert receipt['path'] is None and receipt['sha256'] is None and receipt['task_xml_sha256'] is None, 'no start receipt is bound'
    assert receipt['source_task_xml_started_sha256'] is None and result['started_xml_bound'] is False and result['source_xml_bound'] is True
    assert receipt['retarget_receipt_sha256'] == info['retarget_sha256'] and receipt['start_intent_sha256'] == info['intent_sha256']
    assert receipt['start_held_sha256'] == info['held_sha256'] and (info['held_sha256'] is None) is (binding == 'START_CRASHED_NO_RECORD')
    assert receipt['source_task_xml_after_sha256'] == info['after_xml_sha256'] == sha(SOURCE_XML.encode())
    assert receipt['schema'] == 'cochem-warden-retarget/3' and receipt['status'] == 'WARDEN_RETARGETED_TO_R5_NOT_STARTED' and receipt['controller_bound'] is False
    # The action, triggers, runtime and configuration come from the retarget receipt of the same attempt.
    assert result['expected_action'] == {'execute': R5_PY, 'arguments': R5_ARGS, 'working_directory': R5_ROOT}
    assert result['expected_triggers'] == [{'type': 'logon', 'user_id': 'AETHERDESK\\ansac', 'delay': 'PT1M'}]
    assert result['runtime_root'] == R5_ROOT and result['runtime_python'] == R5_PY and result['runtime_source'] == R5_SOURCE
    assert receipt['config_path'] == R5_CONFIG and receipt['config_sha256'] == sha(STAGED_CONFIG) and receipt['install_after_path'] == R5_ROOT + r'\install-after.json'
    bindings = result['bindings']
    assert bindings['runtime'] == 'r5' and bindings['task_config_sha256'] == receipt['config_sha256'] and bindings['install_after_sha256'] == receipt['install_after_sha256']
    attempt = Path(info['base']) / 'WardenRetarget4.2.7-windows-20261011-r5-v3'
    unpinned = [r['path'] for r in result['reads'] if not r['hash']]
    assert unpinned == [str(attempt / 'start-held.json')] * (binding != 'START_CRASHED_NO_RECORD') + [str(attempt / 'start-intent.json')], \
        'the held record and the start intent are the roots of trust; the retarget receipt and the registered XML are digest-bound'
    reads = {(r['path'], r['hash']) for r in result['reads']}
    assert (str(attempt / 'retarget-receipt.json'), info['retarget_sha256']) in reads and (str(attempt / 'warden-task-after.xml'), info['after_xml_sha256']) in reads


# --------------------------------------------------------------------------------------------------------------------
# Live task binding: definition, action and trigger from the receipt, RUNNING / ALREADY_STOPPED
# --------------------------------------------------------------------------------------------------------------------

SOURCE_CASES = {
    'running': ('@{}', 'RUNNING'),
    'already_stopped_ready': ('@{State=3;Instances=0}', 'ALREADY_STOPPED'),
    'already_stopped_disabled': ('@{Enabled=$false;State=1;Instances=0}', 'ALREADY_STOPPED'),
    # Re-audit R-F5: a disabled task with exactly one running instance is RUNNING for every binding (sweep N6).
    'running_but_disabled': ('@{Enabled=$false}', 'RUNNING'),
    'disabled_with_two_instances': ('@{Enabled=$false;Instances=2}', 'neither running'),
    'queued': ('@{State=2;Instances=0}', 'neither running'),
    'two_instances': ('@{Instances=2}', 'neither running'),
    'stopped_with_instance': ('@{State=3;Instances=1}', 'neither running'),
    'principal': ("@{UserId='ansac'}", 'exact reviewed SYSTEM'),
    'logon_type': ('@{LogonType=2}', 'exact reviewed SYSTEM'),
    'run_level': ('@{RunLevel=0}', 'exact reviewed SYSTEM'),
    'parallel': ('@{MultipleInstances=0}', 'exact reviewed SYSTEM'),
    'time_limit': ("@{ExecutionTimeLimit='PT8M'}", 'exact reviewed SYSTEM'),
    'restart_count': ('@{RestartCount=3}', 'exact reviewed SYSTEM'),
    'no_demand_start': ('@{AllowDemandStart=$false}', 'exact reviewed SYSTEM'),
    'two_actions': ('@{Actions=2}', 'exact reviewed SYSTEM'),
    'action_execute_r4': ("@{Path='" + R4_PY + "'}", 'differs from the r5 action recorded by the start receipt'),
    'action_r4v1_arguments': ("@{Arguments='" + R4V1_ARGS + "'}", 'differs from the r5 action recorded by the start receipt'),
    'action_other_config': ("@{Arguments='" + r5_args(HELD_CONFIG) + "'}", 'differs from the r5 action recorded by the start receipt'),
    'action_working_directory': ("@{WorkingDirectory='" + R4_ROOT + "'}", 'differs from the r5 action recorded by the start receipt'),
    'action_type': ('@{ActionType=5}', 'differs from the r5 action recorded by the start receipt'),
    'no_trigger': ('@{Triggers=@()}', 'triggers differ from the r5 start receipt'),
    'boot_trigger': ("@{Triggers=@(@{Type=8;UserId='';Delay='PT1M';Enabled=$true})}", 'triggers differ'),
    'trigger_other_user': ("@{Triggers=@(@{Type=9;UserId='AETHERDESK\\other';Delay='PT1M';Enabled=$true})}", 'triggers differ'),
    # Re-audit R-F2: the trigger user is compared by SID (retarget-warden-r5 Test-SameAccount), not by spelling (sweep N5).
    'trigger_user_other_spelling': ("@{Triggers=@(@{Type=9;UserId='aetherdesk\\ANSAC';Delay='PT1M';Enabled=$true})}", 'RUNNING'),
    'trigger_user_read_back_as_sid': ("@{Triggers=@(@{Type=9;UserId='S-1-5-21-9-9-9-1001';Delay='PT1M';Enabled=$true})}", 'RUNNING'),
    'trigger_user_other_sid': ("@{Triggers=@(@{Type=9;UserId='S-1-5-21-1-2-3-1001';Delay='PT1M';Enabled=$true})}", 'triggers differ'),
    'trigger_user_unresolvable': ("@{Triggers=@(@{Type=9;UserId='AETHERDESK\\no-such-account';Delay='PT1M';Enabled=$true})}", 'triggers differ'),
    'trigger_user_empty': ("@{Triggers=@(@{Type=9;UserId='';Delay='PT1M';Enabled=$true})}", 'triggers differ'),
    'trigger_delay': ("@{Triggers=@(@{Type=9;UserId='AETHERDESK\\ansac';Delay='PT5M';Enabled=$true})}", 'triggers differ'),
    'two_triggers': ("@{Triggers=@(@{Type=9;UserId='AETHERDESK\\ansac';Delay='PT1M';Enabled=$true},@{Type=8;UserId='';Delay='';Enabled=$true})}", 'triggers differ'),
    # Two-phase start: a completed start enabled its logon trigger; a disabled one is not what the start receipt recorded.
    'trigger_disabled_after_completed_start': ("@{" + TRIGGER_OFF + ";Xml='" + ps(LIVE_XML_TRIGGER_OFF) + "'}",
                                               'trigger is disabled, which the bound r5 start evidence (START_RECEIPT) does not allow'),
    'already_stopped_disabled_trigger_enabled': ("@{Enabled=$false;State=1;Instances=0;Xml='" + ps(TASK_XML_DISABLED) + "'}", 'ALREADY_STOPPED'),
    # C-F5: the live XML is the one this attempt registered and started (its Description names the attempt).
    'xml_names_other_attempt': ("@{Xml='" + ps(TASK_XML.replace('retarget v3', 'retarget v2')) + "'}", 'registered (warden-task-after.xml) outside <Settings><Enabled>'),
    'xml_other_setting': ("@{Xml='" + ps(TASK_XML.replace('IgnoreNew', 'Parallel')) + "'}", 'registered (warden-task-after.xml) outside <Settings><Enabled>'),
    'xml_trigger_flag_differs_from_started': ("@{Xml='" + ps(LIVE_XML_TRIGGER_OFF) + "'}", 'recorded (warden-task-started.xml) outside <Settings><Enabled>'),
    'extra_ace': ("@{Sddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;BU)'}", 'ownership/private DACL'),
    'unreadable': ('@{DenyGetTask=$true}', 'unreadable'),
    'absent': ('@{AbsentTask=$true}', 'absent'),
    'receipt_not_bound': ('@{}', 'start receipt is not bound'),
}


@pytest.fixture(scope='module')
def source_results(tmp_path_factory):
    work = tmp_path_factory.mktemp('source')
    lines = [TASK_FIXTURE, BOUND, '$out=[ordered]@{}']
    for name, (overrides, _) in SOURCE_CASES.items():
        unbind = '$script:expectedAction=$null;' if name == 'receipt_not_bound' else ''
        lines.append(f"$saved=$script:expectedAction;{unbind}$folder=New-FixtureFolder {overrides};$mode=$null;$m='';try{{$mode=Get-StopMode (Get-WardenTaskState $folder)}}catch{{$m=$_.Exception.Message}};"
                     f"$script:expectedAction=$saved;$out['{name}']=[ordered]@{{mode=$mode;message=$m;triggers=@(Get-TaskTriggerSet $script:task)}}")
    lines.append('$out|ConvertTo-Json -Depth 5 -Compress')
    return run_json('\n'.join(lines), work)


@pytest.mark.parametrize('case', list(SOURCE_CASES))
def test_live_task_binds_the_receipt_action_and_trigger_exactly(source_results, case):
    _, expected = SOURCE_CASES[case]
    value = source_results[case]
    if expected in ('RUNNING', 'ALREADY_STOPPED'):
        assert value['mode'] == expected and value['message'] == '', value
    else:
        assert value['mode'] is None and expected in value['message'], value
    if case == 'running':
        assert value['triggers'] == [{'type': 'logon', 'user_id': 'AETHERDESK\\ansac', 'delay': 'PT1M', 'enabled': True}]
    if case == 'two_triggers':
        assert [t['type'] for t in value['triggers']] == ['logon', 'boot']


# An interrupted, held or crashed start (C-F1(b)): bound through the retarget receipt, whose XML registered the task and the
# logon trigger disabled; the start's held path may have disabled the task again while its instance runs.
HELD_SAYS = "$script:startBinding='START_INTERRUPTED_HELD';$startReceipt.binding='START_INTERRUPTED_HELD';$script:allowedTriggerEnabled=@({})"
INTERRUPTED_SOURCE_CASES = {
    # name: (extra binding code, task overrides, expected mode or refusal fragment)
    'crashed_running_trigger_not_yet_enabled': ('', "@{" + TRIGGER_OFF + ";Xml='" + ps(LIVE_XML_TRIGGER_OFF) + "'}", 'RUNNING'),
    'crashed_running_in_the_trigger_enable_window': ('', '@{}', 'RUNNING'),
    'crashed_stopped_enabled_trigger_off': ('', "@{State=3;Instances=0;" + TRIGGER_OFF + ";Xml='" + ps(LIVE_XML_TRIGGER_OFF) + "'}", 'ALREADY_STOPPED'),
    'crashed_stopped_disabled_trigger_off': ('', "@{Enabled=$false;State=1;Instances=0;" + TRIGGER_OFF + ";Xml='" + ps(SOURCE_XML) + "'}", 'ALREADY_STOPPED'),
    'held_running_task_disabled_by_the_held_path': (HELD_SAYS.format('$false'), "@{Enabled=$false;" + TRIGGER_OFF + ";Xml='" + ps(SOURCE_XML) + "'}", 'RUNNING'),
    'held_running_disabled_trigger_enabled_readback': (HELD_SAYS.format('$true'), "@{Enabled=$false;Xml='" + ps(TASK_XML_DISABLED) + "'}", 'RUNNING'),
    'held_says_trigger_disabled_but_enabled': (HELD_SAYS.format('$false'), '@{}', 'trigger is enabled, which the bound r5 start evidence (START_INTERRUPTED_HELD) does not allow'),
    'held_says_trigger_enabled_but_disabled': (HELD_SAYS.format('$true'), "@{" + TRIGGER_OFF + ";Xml='" + ps(LIVE_XML_TRIGGER_OFF) + "'}",
                                               'trigger is disabled, which the bound r5 start evidence (START_INTERRUPTED_HELD) does not allow'),
    'crashed_disabled_queued': ('', "@{Enabled=$false;State=2;Instances=0;Xml='" + ps(SOURCE_XML) + "';" + TRIGGER_OFF + "}", 'neither running'),
    'crashed_disabled_two_instances': ('', "@{Enabled=$false;Instances=2;Xml='" + ps(SOURCE_XML) + "';" + TRIGGER_OFF + "}", 'neither running'),
    'crashed_action_other_config': ('', "@{Arguments='" + r5_args(HELD_CONFIG) + "'}", 'differs from the r5 action recorded by the retarget receipt'),
    'crashed_trigger_delay': ('', "@{Triggers=@(@{Type=9;UserId='AETHERDESK\\ansac';Delay='PT5M';Enabled=$false})}", 'triggers differ from the r5 retarget receipt'),
    'crashed_no_trigger': ('', "@{Triggers=@()}", 'triggers differ from the r5 retarget receipt'),
    'crashed_xml_names_other_attempt': ('', "@{Xml='" + ps(TASK_XML.replace('retarget v3', 'retarget v2')) + "'}", 'registered (warden-task-after.xml) outside'),
    'crashed_xml_other_principal': ('', "@{Xml='" + ps(TASK_XML.replace('S-1-5-18', 'S-1-5-19')) + "'}", 'registered (warden-task-after.xml) outside'),
    'crashed_xml_other_trigger_user_in_xml': ('', "@{Xml='" + ps(TASK_XML.replace('AETHERDESK\\ansac', 'AETHERDESK\\other')) + "'}", 'registered (warden-task-after.xml) outside'),
    'crashed_principal': ("", "@{UserId='ansac'}", 'exact reviewed SYSTEM'),
}


@pytest.fixture(scope='module')
def interrupted_source_results(tmp_path_factory):
    work = tmp_path_factory.mktemp('interruptedsource')
    lines = [TASK_FIXTURE, '$out=[ordered]@{}']
    for name, (extra, overrides, _) in INTERRUPTED_SOURCE_CASES.items():
        lines.append(BOUND_CRASHED + extra)
        lines.append(f"$folder=New-FixtureFolder {overrides};$mode=$null;$m='';try{{$mode=Get-StopMode (Get-WardenTaskState $folder)}}catch{{$m=$_.Exception.Message}};"
                     f"$out['{name}']=[ordered]@{{mode=$mode;message=$m;triggers=@(Get-TaskTriggerSet $script:task)}}")
    lines.append('$out|ConvertTo-Json -Depth 5 -Compress')
    return run_json('\n'.join(lines), work)


@pytest.mark.parametrize('case', list(INTERRUPTED_SOURCE_CASES))
def test_interrupted_start_live_task_must_match_its_retarget_receipt(interrupted_source_results, case):
    expected = INTERRUPTED_SOURCE_CASES[case][2]
    value = interrupted_source_results[case]
    if expected in ('RUNNING', 'ALREADY_STOPPED'):
        assert value['mode'] == expected and value['message'] == '', value
    else:
        assert value['mode'] is None and expected in value['message'], value


def test_a_disabled_task_with_one_running_instance_is_running_for_every_binding(source_results, interrupted_source_results):
    """Re-audit R-F5 (sweep N6): START_RECEIPT included; anything else with the task disabled stays refused."""
    assert source_results['running_but_disabled']['mode'] == 'RUNNING' and source_results['running_but_disabled']['message'] == ''
    assert interrupted_source_results['held_running_task_disabled_by_the_held_path']['mode'] == 'RUNNING'
    assert 'neither running' in source_results['disabled_with_two_instances']['message']
    assert 'neither running' in interrupted_source_results['crashed_disabled_queued']['message']


@pytest.mark.parametrize('case', ['apply_running_task_disabled_after_completed_start', 'apply_trigger_user_read_back_as_sid'])
def test_completed_start_stops_a_disabled_running_task_and_a_sid_read_back_trigger(tmp_path, case):
    """Re-audit R-F5 and R-F2 end to end: the completed start (START_RECEIPT) is stopped and its receipt written."""
    value, target, info = drive_session(tmp_path, case)
    assert not value['failed'], value['message']
    receipt = read_json(target / 'stop-receipt.json')
    assert receipt['start_binding'] == 'START_RECEIPT' and receipt['status'] == 'WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED' and value['stops'] == 1
    assert receipt['enabled_after'] is False and receipt['instances_after'] == 0 and receipt['trigger_enabled_after'] is True
    assert receipt['task_xml_after_sha256'] == sha((target / 'warden-task-after.xml').read_bytes())
    if case == 'apply_running_task_disabled_after_completed_start':
        assert receipt['enabled_before'] is False and receipt['disabled_by_this_run'] is False and value['enabled_writes'] == [], \
            'the task was already disabled: its running instance is ended and the task is not written'
    else:
        assert receipt['triggers'][0]['user_id'] == 'S-1-5-21-9-9-9-1001' and receipt['disabled_by_this_run'] is True and len(value['enabled_writes']) == 1


def test_account_sid_helpers_are_retarget_warden_r5_copies_and_resolve_on_this_host(tmp_path):
    """Re-audit R-F2: Get-AccountSid and Test-SameAccount are byte-identical to retarget-warden-r5.ps1's; resolved for real here."""
    sibling = ROOT / 'retarget-warden-r5.ps1'
    if not sibling.exists():
        pytest.skip('retarget-warden-r5.ps1 is not in the workspace')
    mine, theirs = ast_dump(SCRIPT, tmp_path)['texts'], ast_dump(sibling, tmp_path)['texts']
    for name in ('Get-AccountSid', 'Test-SameAccount'):
        assert name in theirs and mine[name] == theirs[name], name
    value = run_json(r'''$sid=Get-AccountSid 'AETHERDESK\ansac'
      [ordered]@{host=$env:COMPUTERNAME;sid=$sid;exact=(Test-SameAccount 'AETHERDESK\ansac' 'AETHERDESK\ansac');
        as_sid=$(if($sid){Test-SameAccount $sid 'AETHERDESK\ansac'}else{$null});spelling=$(if($sid){Test-SameAccount 'aetherdesk\ANSAC' 'AETHERDESK\ansac'}else{$null});
        other_sid=(Test-SameAccount 'S-1-5-21-1-2-3-1001' 'AETHERDESK\ansac');unknown=(Test-SameAccount 'AETHERDESK\no-such-account-r-f2' 'AETHERDESK\ansac');
        empty=(Test-SameAccount '' 'AETHERDESK\ansac');bad_sid=(Get-AccountSid 'S-1-x')}|ConvertTo-Json -Compress''', tmp_path)
    assert value['exact'] is True and value['other_sid'] is False and value['unknown'] is False and value['empty'] is False and value['bad_sid'] is None
    if value['host'] != 'AETHERDESK' or value['sid'] is None:
        pytest.skip('the owner account does not resolve on this host')
    assert value['sid'].startswith('S-1-5-') and value['as_sid'] is True and value['spelling'] is True


R4_SOURCE_CASES = {
    # The live task of an r4 restore: the restore action of this retarget attempt and no trigger. CR2: the retarget leaves an
    # idle task enabled or disabled; a running task is enabled.
    'r4_running': (R4_TASK + '}', 'RUNNING'),
    'r4_already_stopped_enabled': (R4_TASK + ';State=3;Instances=0}', 'ALREADY_STOPPED'),
    'r4_already_stopped_disabled': (R4_TASK.replace(TASK_XML_R4, TASK_XML_R4_DISABLED) + ';Enabled=$false;State=1;Instances=0}', 'ALREADY_STOPPED'),
    'r4_running_but_disabled': (R4_TASK + ';Enabled=$false}', 'RUNNING'),
    'r4_logon_trigger_present': (R4_TASK.replace('Triggers=@()', "Triggers=@(@{Type=9;UserId='AETHERDESK\\ansac';Delay='PT1M';Enabled=$true})") + '}', 'triggers differ from the r4 start receipt'),
    'r4_boot_trigger_present': (R4_TASK.replace('Triggers=@()', "Triggers=@(@{Type=8;UserId='';Delay='';Enabled=$true})") + '}', 'triggers differ from the r4 start receipt'),
    'r4_live_r5_action': ('@{}', 'differs from the r4 action recorded by the start receipt'),
    'r4_live_r4v1_action': (R4_TASK.replace(R4_RESTORE_ARGS, R4V1_ARGS) + '}', 'differs from the r4 action recorded by the start receipt'),
    'r4_live_other_restore_attempt': (R4_TASK.replace(R4_RESTORE_ARGS, r4_restore_args('v2')) + '}', 'differs from the r4 action recorded by the start receipt'),
    'r4_live_r3_python': (R4_TASK.replace(R4_PY, R3_ROOT + r'\.venv\Scripts\python.exe') + '}', 'differs from the r4 action recorded by the start receipt'),
}


@pytest.fixture(scope='module')
def r4_source_results(tmp_path_factory):
    work = tmp_path_factory.mktemp('r4source')
    lines = [TASK_FIXTURE, BOUND_R4, '$out=[ordered]@{}']
    for name, (overrides, _) in R4_SOURCE_CASES.items():
        lines.append(f"$folder=New-FixtureFolder {overrides};$mode=$null;$m='';try{{$mode=Get-StopMode (Get-WardenTaskState $folder)}}catch{{$m=$_.Exception.Message}};"
                     f"$out['{name}']=[ordered]@{{mode=$mode;message=$m;trigger_count=@(Get-TaskTriggerSet $script:task).Count}}")
    lines.append('$out|ConvertTo-Json -Depth 5 -Compress')
    return run_json('\n'.join(lines), work)


@pytest.mark.parametrize('case', list(R4_SOURCE_CASES))
def test_live_r4_restore_task_binds_the_receipt_action_and_no_trigger(r4_source_results, case):
    expected = R4_SOURCE_CASES[case][1]
    value = r4_source_results[case]
    if expected in ('RUNNING', 'ALREADY_STOPPED'):
        assert value['mode'] == expected and value['message'] == '' and value['trigger_count'] == 0, value
    else:
        assert value['mode'] is None and expected in value['message'], value


XML_BEFORE = TASK_XML
XML_CASES = {
    'absent_to_false': (XML_BEFORE, XML_BEFORE.replace('<Settings>', '<Settings><Enabled>false</Enabled>'), False),
    'absent_to_false_at_end': (XML_BEFORE, XML_BEFORE.replace('</Settings>', '<Enabled>false</Enabled></Settings>'), False),
    'true_to_false': (XML_BEFORE.replace('<Settings>', '<Settings><Enabled>true</Enabled>'), XML_BEFORE.replace('<Settings>', '<Settings><Enabled>false</Enabled>'), False),
    'whitespace_only': (XML_BEFORE, XML_BEFORE.replace('<Settings>', '<Settings>\n    <Enabled>false</Enabled>\n    '), False),
    'other_setting_changed': (XML_BEFORE, XML_BEFORE.replace('<Settings>', '<Settings><Enabled>false</Enabled>').replace('IgnoreNew', 'Parallel'), True),
    'logon_trigger_disabled': (XML_BEFORE, XML_BEFORE.replace('<LogonTrigger><Enabled>true', '<LogonTrigger><Enabled>false'), True),
    'logon_trigger_delay': (XML_BEFORE, XML_BEFORE.replace('<Delay>PT1M', '<Delay>PT5M'), True),
    'logon_trigger_user': (XML_BEFORE, XML_BEFORE.replace('AETHERDESK\\ansac', 'AETHERDESK\\other'), True),
    'description_changed': (XML_BEFORE, XML_BEFORE.replace('<Description>Reviewed', '<Description>Changed'), True),
    'action_changed': (XML_BEFORE, XML_BEFORE.replace('<Command>c<', '<Command>x<'), True),
    'principal_changed': (XML_BEFORE, XML_BEFORE.replace('S-1-5-18', 'S-1-5-19'), True),
}


@pytest.fixture(scope='module')
def xml_results(tmp_path_factory):
    work = tmp_path_factory.mktemp('xml')
    lines = ['$out=[ordered]@{}']
    for name, (before, after, _) in XML_CASES.items():
        lines.append(f"$out['{name}']=((Get-TaskXmlOutsideEnabled '{ps(before)}') -cne (Get-TaskXmlOutsideEnabled '{ps(after)}'))")
    lines.append('$out|ConvertTo-Json -Compress')
    return run_json('\n'.join(lines), work)


@pytest.mark.parametrize('case', list(XML_CASES))
def test_xml_comparator_ignores_only_settings_enabled_including_absent_to_present(xml_results, case):
    assert xml_results[case] is XML_CASES[case][2]


XML_FLAG_CASES = {
    # C-F5 comparator: ignores <Settings><Enabled> and every trigger's Enabled flag, nothing else.
    'registered_vs_started': (SOURCE_XML, TASK_XML, False),
    'trigger_flag_only': (TASK_XML, LIVE_XML_TRIGGER_OFF, False),
    'trigger_flag_absent_vs_true': (TASK_XML, TASK_XML.replace('<LogonTrigger><Enabled>true</Enabled>', '<LogonTrigger>'), False),
    'settings_flag_only': (TASK_XML, TASK_XML_DISABLED, False),
    'description_other_attempt': (SOURCE_XML, TASK_XML.replace('retarget v3', 'retarget v2'), True),
    'trigger_delay': (SOURCE_XML, TASK_XML.replace('<Delay>PT1M', '<Delay>PT5M'), True),
    'trigger_user': (SOURCE_XML, TASK_XML.replace('AETHERDESK\\ansac', 'AETHERDESK\\other'), True),
    'other_setting': (SOURCE_XML, TASK_XML.replace('IgnoreNew', 'Parallel'), True),
    'action': (SOURCE_XML, TASK_XML.replace('<Command>c<', '<Command>x<'), True),
    'principal': (SOURCE_XML, TASK_XML.replace('S-1-5-18', 'S-1-5-19'), True),
    'second_trigger_added': (SOURCE_XML, TASK_XML.replace('</Triggers>', '<BootTrigger><Enabled>true</Enabled></BootTrigger></Triggers>'), True),
}
TRIGGER_FLAG_CASES = {'started': (TASK_XML, [True]), 'registered': (SOURCE_XML, [False]), 'absent_flag': (TASK_XML.replace('<LogonTrigger><Enabled>true</Enabled>', '<LogonTrigger>'), [True]),
                      'r4_no_trigger': (TASK_XML_R4, []), 'two_triggers': (TASK_XML.replace('</Triggers>', '<BootTrigger><Enabled>false</Enabled></BootTrigger></Triggers>'), [True, False]),
                      'not_a_boolean': (TASK_XML.replace('<LogonTrigger><Enabled>true', '<LogonTrigger><Enabled>1'), None)}


def test_xml_comparator_for_the_registered_xml_ignores_only_the_enabled_flags(tmp_path):
    lines = ['$out=[ordered]@{}']
    for name, (left, right, _) in XML_FLAG_CASES.items():
        lines.append(f"$out['{name}']=((Get-TaskXmlOutsideEnabledFlags '{ps(left)}') -cne (Get-TaskXmlOutsideEnabledFlags '{ps(right)}'))")
    for name, (text, _) in TRIGGER_FLAG_CASES.items():
        lines.append(f"$v=$null;try{{$v=@(Get-TaskXmlTriggerFlags '{ps(text)}')}}catch{{$v='refused'}};$out['flags_{name}']=$v")
    lines.append('$out|ConvertTo-Json -Compress')
    value = run_json('\n'.join(lines), tmp_path)
    for name, (_, _, differs) in XML_FLAG_CASES.items():
        assert value[name] is differs, name
    for name, (_, flags) in TRIGGER_FLAG_CASES.items():
        assert value['flags_' + name] == (flags if flags is not None else 'refused'), name


STATE_FIXTURE = r'''
function New-TriggerCollection {param($Items)
  $collection=[pscustomobject]@{Count=@($Items).Count;List=@($Items)};$collection|Add-Member ScriptMethod Item {param($i)@($this.List)[$i-1]};$collection}
function New-TriggerTask {param($Triggers)[pscustomobject]@{Definition=[pscustomobject]@{Triggers=(New-TriggerCollection @(@($Triggers)|ForEach-Object {[pscustomobject]$_}))}}}
function New-State {param([hashtable]$Overrides)
  $v=[ordered]@{readable=$true;enabled=$false;state=1;instances=0;last_task_result=267014;user='S-1-5-18';logon_type=5;run_level=1;triggers=1;actions=1;multiple_instances=2;execution_time_limit='PT0S';
    restart_count=0;allow_demand_start=$true;action_type=0;action_path='R5PYVALUE';action_arguments='R5ARGSVALUE';action_working_directory='R5ROOTVALUE';sddl='SDDLVALUE';xml='XMLVALUE';
    task=(New-TriggerTask @(@{Type=9;UserId='AETHERDESK\ansac';Delay='PT1M';Enabled=$true}))}
  foreach($k in $Overrides.Keys){$v[$k]=$Overrides[$k]};[pscustomobject]$v}
$before=New-State @{enabled=$true;state=4;instances=1}
$afterXml=$before.xml.Replace('<Settings>','<Settings><Enabled>false</Enabled>')
'''.replace('R5PYVALUE', R5_PY).replace('R5ARGSVALUE', R5_ARGS).replace('R5ROOTVALUE', R5_ROOT).replace('SDDLVALUE', SDDL).replace('XMLVALUE', TASK_XML)
READBACK_CASES = {
    'valid': ('@{xml=$afterXml}', ''),
    'already_disabled_unchanged': ('@{xml=$afterXml}', ''),
    'still_enabled': ('@{xml=$afterXml;enabled=$true;state=3}', 'still enabled'),
    'instance': ('@{xml=$afterXml;instances=1;state=4}', 'running or queued instance'),
    'queued': ('@{xml=$afterXml;state=2}', 'running or queued instance'),
    'unreadable': ('@{readable=$false}', 'could not be read back'),
    'sddl_changed': ("@{xml=$afterXml;sddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'}", 'security descriptor changed'),
    'xml_changed_elsewhere': ("@{xml=$afterXml.Replace('IgnoreNew','Parallel')}", 'outside <Settings><Enabled>'),
    'action_changed': ("@{xml=$afterXml;action_arguments='-I -B -m cochem_pipeline daemon'}", 'differs from the r5 action recorded by the start receipt'),
    'trigger_delay_changed': ("@{xml=$afterXml;task=(New-TriggerTask @(@{Type=9;UserId='AETHERDESK\\ansac';Delay='PT5M';Enabled=$true}))}", 'triggers differ'),
    'trigger_removed': ('@{xml=$afterXml;triggers=0;task=(New-TriggerTask @())}', 'triggers differ'),
}


@pytest.fixture(scope='module')
def readback_results(tmp_path_factory):
    work = tmp_path_factory.mktemp('readback')
    lines = [BOUND, STATE_FIXTURE, '$out=[ordered]@{}']
    for name, (overrides, _) in READBACK_CASES.items():
        base = '$before' if name != 'already_disabled_unchanged' else '(New-State @{xml=$afterXml})'
        lines.append(f"$after=New-State {overrides};$m='';try{{Assert-StopDisabledTask $after {base}}}catch{{$m=$_.Exception.Message}};$out['{name}']=$m")
    lines.append('$out|ConvertTo-Json -Compress')
    return run_json('\n'.join(lines), work)


@pytest.mark.parametrize('case', list(READBACK_CASES))
def test_disabled_readback_requires_unchanged_action_trigger_sddl_and_xml(readback_results, case):
    expected = READBACK_CASES[case][1]
    if expected:
        assert expected in readback_results[case], readback_results[case]
    else:
        assert readback_results[case] == ''


# --------------------------------------------------------------------------------------------------------------------
# Idle proof: predicate, evidence, polling and the slot-worker order
# --------------------------------------------------------------------------------------------------------------------

def health(**changes):
    value = {'service_identity': 'SYSTEM', 'source_root': R5_SOURCE, 'pid': 20664, 'instance_id': '0f5a2c3e9b8d4e7fa1b2c3d4e5f60718',
             'process_started_at': 1791720056.25, 'active': [], 'quarantined_slots': {},
             'routing': {'holds': [{'scope': 'model', 'resource_key': 'x'}], 'active_reservations': [], 'execution_quarantines': [], 'counts': {'COMPLETED': 3}}}
    for key, change in changes.items():
        if key == 'routing':
            value['routing'].update(change)
        else:
            value[key] = change
    return value


ROWS = [{'job_id': 'job-b', 'workflow_id': 'w', 'kind': 'CHAPTER', 'status': 'BLOCKED'}, {'job_id': 'job-c', 'workflow_id': 'w', 'kind': 'CHAPTER', 'status': 'COMPLETED'},
        {'job_id': 'job-f', 'workflow_id': 'w', 'kind': 'CHAPTER', 'status': 'FAILED'}]
WINDOW = {'job_limit': 200, 'jobs_total': 3, 'jobs_truncated': False}


def operator(rows, window=WINDOW):
    value = {'schema': 'cochem-operator-queue-extract/2', 'queue': rows}
    if window is not None:
        value['window'] = window
    return json.dumps(value)


IDLE_CASES = {
    'idle_blocked_completed_failed': (health(), health(), operator(ROWS), True, None, []),
    'idle_empty_queue': (health(), health(), operator([], {'job_limit': 200, 'jobs_total': 0, 'jobs_truncated': False}), True, None, []),
    'blocked_only': (health(), health(), operator(ROWS[:1]), True, None, []),
    'active_job': (health(), health(active=[{'job_id': 'job-a', 'slot': 1, 'pid': 5, 'route': None}]), operator(ROWS), False, '1 active job(s)', ['job-a']),
    'reservation': (health(), health(routing={'active_reservations': [{'job_id': 'job-r', 'provider': 'codex'}]}), operator(ROWS), False, 'active route reservation', ['job-r']),
    'execution_quarantine': (health(routing={'execution_quarantines': [{'job_id': 'job-q', 'attempt_id': 'a'}]}), health(), operator(ROWS), False, 'uncleared execution cleanup', ['job-q']),
    'quarantined_slot': (health(quarantined_slots={'slot2': 'cleanup unconfirmed'}), health(), operator(ROWS), False, 'quarantined slot(s): slot2', []),
    'pending': (health(), health(), operator(ROWS + [{'job_id': 'job-p', 'workflow_id': 'w', 'kind': 'CHAPTER', 'status': 'PENDING'}]), False, 'job-p is PENDING', ['job-p']),
    'pending_retry': (health(), health(), operator([{'job_id': 'job-pr', 'workflow_id': 'w', 'kind': 'CHAPTER', 'status': 'PENDING_RETRY'}]), False, 'job-pr is PENDING_RETRY', ['job-pr']),
    'in_progress': (health(), health(), operator([{'job_id': 'job-ip', 'workflow_id': 'w', 'kind': 'CHAPTER', 'status': 'IN_PROGRESS'}]), False, 'job-ip is IN_PROGRESS', ['job-ip']),
    'window_truncated': (health(), health(), operator(ROWS, {'job_limit': 200, 'jobs_total': 241, 'jobs_truncated': True}), False, 'window is truncated or unproven', []),
    'window_missing': (health(), health(), operator(ROWS, None), False, 'window is truncated or unproven', []),
    'window_truncated_as_string': (health(), health(), operator(ROWS, {'job_limit': 200, 'jobs_total': 3, 'jobs_truncated': 'false'}), False, 'window is truncated or unproven', []),
    'window_truncated_null': (health(), health(), operator(ROWS, {'job_limit': 200, 'jobs_total': 3, 'jobs_truncated': None}), False, 'window is truncated or unproven', []),
    'window_not_object': (health(), health(), operator(ROWS, [1]), False, 'window is truncated or unproven', []),
    'malformed_operator_json': (health(), health(), '{"queue":[', False, 'not JSON', []),
    'operator_unavailable': (health(), health(), None, False, 'operator snapshot is unavailable', []),
    'operator_without_queue': (health(), health(), '{"schema":"x"}', False, 'no queue list', []),
    'row_without_status': (health(), health(), operator([{'job_id': 'job-x'}]), False, 'without a status', []),
    'routing_missing': ({k: v for k, v in health().items() if k != 'routing'}, health(), operator(ROWS), False, 'no routing object', []),
    'active_not_a_list': (health(active=None), health(), operator(ROWS), False, 'no active list', []),
    'identity_changed': (health(), health(pid=4242), operator(ROWS), False, 'identity changed between samples', []),
    'instance_changed': (health(), health(instance_id='other'), operator(ROWS), False, 'identity changed between samples', []),
    'wrong_identity': (health(service_identity='ansac'), health(), operator(ROWS), False, 'not the SYSTEM controller from the r5 root', []),
    'r4_source_root': (health(), health(source_root=R4_ROOT + r'\.venv\Lib'), operator(ROWS), False, 'not the SYSTEM controller from the r5 root', []),
    'health_unavailable': (None, health(), operator(ROWS), False, 'health sample 1 is unavailable', []),
}


def ps_json(value):
    if value is None:
        return '$null'
    text = json.dumps(value)
    assert "'" not in text
    return f"('{text}'|ConvertFrom-Json)"


@pytest.fixture(scope='module')
def idle_results(tmp_path_factory):
    work = tmp_path_factory.mktemp('idle')
    lines = [BOUND, '$out=[ordered]@{}']
    for name, (first, second, operator_text, *_rest) in IDLE_CASES.items():
        op = '$null' if operator_text is None else "'" + operator_text + "'"
        lines.append(f"$out['{name}']=(Test-IdlePredicate {ps_json(first)} {ps_json(second)} {op})")
    lines.append('$out|ConvertTo-Json -Depth 6 -Compress')
    return run_json('\n'.join(lines), work)


def test_r4_idle_proof_binds_the_r4_source_root(tmp_path):
    r4_health = health(source_root=R4_SOURCE)
    lines = [BOUND_R4, '$out=[ordered]@{}',
             f"$out['r4']=(Test-IdlePredicate {ps_json(r4_health)} {ps_json(r4_health)} '{operator(ROWS)}')",
             f"$out['r5_answers']=(Test-IdlePredicate {ps_json(health())} {ps_json(health())} '{operator(ROWS)}')",
             '$out|ConvertTo-Json -Depth 6 -Compress']
    value = run_json('\n'.join(lines), tmp_path)
    assert value['r4']['idle'] is True and value['r4']['reasons'] == []
    assert value['r5_answers']['idle'] is False and any('not the SYSTEM controller from the r4 root' in r for r in value['r5_answers']['reasons'])


@pytest.mark.parametrize('case', list(IDLE_CASES))
def test_idle_predicate_table(idle_results, case):
    _, _, _, idle, reason, jobs = IDLE_CASES[case]
    value = idle_results[case]
    assert value['idle'] is idle, value
    if reason:
        assert any(reason in item for item in value['reasons']), value['reasons']
    else:
        assert value['reasons'] == []
    assert value['offending_job_ids'] == jobs
    if case == 'idle_blocked_completed_failed':
        assert value['queue_status_counts'] == {'BLOCKED': 1, 'COMPLETED': 1, 'FAILED': 1} and value['queue_rows'] == 3
        assert value['in_progress_rows'] == 0 and value['uncleared_cleanup_rows'] == 0 and value['routing_holds'] == 1
        assert value['jobs_total'] == 3 and value['jobs_truncated'] is False
    if case == 'window_truncated':
        assert value['jobs_total'] == 241 and value['jobs_truncated'] is True


def test_idle_evidence_spaces_two_pinned_health_calls_and_one_get_operator(tmp_path):
    good = json.dumps(health())
    body = BOUND + (f"$script:h='{good}';" + r'''
      $script:sleeps=@();$script:native=@()
      function Start-Sleep {param($Seconds,$Milliseconds)$script:sleeps+=@($Seconds)}
      function Invoke-NativeJudged {param($Executable,$Arguments)$script:native+=[pscustomobject]@{exe=$Executable;args=@($Arguments)}
        if(@($Arguments)[5] -like '*/operator*'){return [pscustomobject]@{code=0;stdout='{"schema":"cochem-operator-queue-extract/2","queue":[],"window":{"job_limit":200,"jobs_total":0,"jobs_truncated":false}}';stderr=''}}
        [pscustomobject]@{code=0;stdout=$script:h;stderr=''}}
      $e=Get-IdleEvidence
      [ordered]@{idle=$e.idle;reasons=$e.reasons;sleeps=$script:sleeps;calls=@($script:native|ForEach-Object {[ordered]@{exe=$_.exe;args=$_.args}});controller=$e.controller;samples=@($e.samples).Count;
        health=$script:healthCall;operator=$script:operatorCall}|ConvertTo-Json -Depth 5 -Compress''')
    value = run_json(body, tmp_path)
    assert value['idle'] is True and value['reasons'] == [] and value['samples'] == 2
    assert value['sleeps'] == [5], 'two samples at least 5 s apart'
    calls = value['calls']
    assert len(calls) == 3 and all(call['exe'] == R5_PY for call in calls), 'the r5 interpreter answers for the r5 controller'
    assert [call['args'][5] for call in calls] == [value['health'], value['health'], value['operator']]
    for call in calls:
        assert call['args'][:5] == ['-I', '-B', '-X', 'utf8', '-c'] and call['args'][6:] == [CLIENT_CONFIG, TOKEN_FILE, '47824'], 'the pinned port is passed, not read'
    assert value['controller']['pid'] == 20664 and value['controller']['source_root'] == R5_SOURCE


class _Recorder(http.server.BaseHTTPRequestHandler):
    seen = None
    payloads = None

    def _record(self):
        length = int(self.headers.get('Content-Length') or 0)
        self.seen.append({'method': self.command, 'path': self.path, 'auth': self.headers.get('Authorization'), 'body': self.rfile.read(length).decode() if length else ''})
        payload = json.dumps(self.payloads[self.path]).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _record
    do_POST = _record

    def log_message(self, *args):
        pass


def loopback_call(tmp_path, config, call):
    seen = []
    handler = type('Handler', (_Recorder,), {'seen': seen, 'payloads': {
        '/health': health(),
        '/operator': {'schema': 'cochem-operator/4.2.7', 'queue': [{'job_id': 'j1', 'workflow_id': 'w1', 'kind': 'CHAPTER', 'status': 'BLOCKED', 'score': {'x': 1}}],
                      'window': {'job_limit': 200, 'event_limit': 200, 'jobs_total': 1, 'jobs_truncated': False, 'events_available': 9}, 'timeline': [1, 2, 3]}}})
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        token = tmp_path / 'token.txt'
        token.write_text('tok-123\n', encoding='utf-8')
        port = server.server_address[1]
        client = tmp_path / 'client.json'
        client.write_text(json.dumps(config(port, str(token))), encoding='utf-8')
        body = BOUND + (f"$script:runtimePython='{ps(sys.executable)}';$script:clientConfig='{ps(client)}';$script:clientTokenFile='{ps(token)}';$script:port={port};"
                        f"$r={call};[ordered]@{{ok=$r.ok;error=$r.error;text=$(if($r.PSObject.Properties['text']){{$r.text}}else{{$null}});health=$(if($r.PSObject.Properties['health']){{$r.health}}else{{$null}})}}|ConvertTo-Json -Depth 6 -Compress")
        value = run_json(body, tmp_path, timeout=180)
    finally:
        server.shutdown()
        server.server_close()
    return value, seen


def test_operator_snippet_projects_queue_and_window_through_one_authenticated_get(tmp_path):
    value, seen = loopback_call(tmp_path, lambda port, token: {'port': port, 'token_file': token}, 'Get-OperatorSnapshot')
    assert value['ok'] is True, value['error']
    assert seen == [{'method': 'GET', 'path': '/operator', 'auth': 'Bearer tok-123', 'body': ''}]
    assert json.loads(value['text']) == {'schema': 'cochem-operator-queue-extract/2', 'queue': [{'job_id': 'j1', 'workflow_id': 'w1', 'kind': 'CHAPTER', 'status': 'BLOCKED'}],
                                         'window': {'job_limit': 200, 'jobs_total': 1, 'jobs_truncated': False}}


def test_health_snippet_issues_one_authenticated_get_and_binds_the_r5_root(tmp_path):
    value, seen = loopback_call(tmp_path, lambda port, token: {'port': port, 'token_file': token}, 'Get-HealthSample')
    assert value['ok'] is True and value['health']['source_root'] == R5_SOURCE, value['error']
    assert seen == [{'method': 'GET', 'path': '/health', 'auth': 'Bearer tok-123', 'body': ''}]


@pytest.mark.parametrize('case', ['other_port', 'port_as_string', 'port_as_bool', 'other_token_file', 'not_an_object'])
@pytest.mark.parametrize('call', ['Get-HealthSample', 'Get-OperatorSnapshot'])
def test_snippets_refuse_a_client_config_that_is_not_the_pinned_port_and_token(tmp_path, case, call):
    config = {'other_port': lambda port, token: {'port': port + 1, 'token_file': token}, 'port_as_string': lambda port, token: {'port': str(port), 'token_file': token},
              'port_as_bool': lambda port, token: {'port': True, 'token_file': token}, 'other_token_file': lambda port, token: {'port': port, 'token_file': token + '.other'},
              'not_an_object': lambda port, token: [port, token]}[case]
    value, seen = loopback_call(tmp_path, config, call)
    assert value['ok'] is False and 'does not name the pinned controller port and token file' in value['error']
    assert seen == [], 'nothing is requested from any port when the configuration differs'


@pytest.fixture(scope='module')
def wait_results(tmp_path_factory):
    work = tmp_path_factory.mktemp('wait')
    cases = {'idle_first': ('@($true)', "@('')"), 'idle_third': ('@($false,$false,$true)', "@('')"), 'never_idle': ('@($false,$false,$false,$false)', '@()'),
             'worker_then_gone': ('@($true,$true)', "@('4444','')"), 'worker_persists': ('@($true,$true,$true)', "@('4444','4444','4444')"),
             'opaque_process': ('@($true,$true,$true)', "@('opaque','opaque','opaque')"), 'worker_then_busy_then_idle': ('@($true,$false,$true)', "@('4444','')")}
    lines = [r'''
function Start-Sleep {param($Seconds,$Milliseconds)$script:sleeps+=@($Seconds)}
function Get-IdleEvidence {$idle=[bool]@($script:plan)[$script:evals];$script:evals++;$script:order+='idle'
  [ordered]@{idle=$idle;reasons=@($(if($idle){}else{'queue row job-7 is PENDING'}));offending_job_ids=@($(if($idle){}else{'job-7'}));controller=[ordered]@{pid=20664}}}
function Get-WorkerProcesses {$script:sweeps++;$script:order+='workers'
  $text='';if($script:sweeps -le @($script:workerPlan).Count){$text=[string]@($script:workerPlan)[$script:sweeps-1]}
  $pids=@();$opaque=@()
  if($text -eq 'opaque'){$opaque=@([ordered]@{pid=6060;name='svc.exe';path='C:\x\svc.exe'})}else{$pids=@($text -split ','|Where-Object {$_}|ForEach-Object {[int]$_})}
  [ordered]@{workers=@($pids|ForEach-Object {[ordered]@{pid=$_;user='CoChem422Worker2';path='C:\x\claude.exe'}});uninspectable_processes=$opaque;exited_during_sweep=0;authoritative=$true}}
$out=[ordered]@{}''']
    for name, (plan, workers) in cases.items():
        lines.append(f"$script:plan={plan};$script:workerPlan={workers};$script:sleeps=@();$script:evals=0;$script:sweeps=0;$script:order=@();$failed=$false;$m='';$r=$null;"
                     f"try{{$r=Wait-WardenIdle}}catch{{$failed=$true;$m=$_.Exception.Message}};"
                     f"$out['{name}']=[ordered]@{{failed=$failed;message=$m;sleeps=$script:sleeps;evals=$script:evals;sweeps=$script:sweeps;order=$script:order;evaluations=$(if($r){{$r.evaluations}}else{{$null}});worker_count=$(if($r){{@($r.worker_pids).Count}}else{{$null}})}}")
    lines.append('$out|ConvertTo-Json -Depth 5 -Compress')
    return run_json('\n'.join(lines), work)


@pytest.mark.parametrize('case', ['idle_first', 'idle_third', 'never_idle', 'worker_then_gone', 'worker_persists', 'opaque_process', 'worker_then_busy_then_idle'])
def test_wait_idle_polls_every_ten_seconds_and_sweeps_workers_only_after_idle(wait_results, case):
    value = wait_results[case]
    expected = {'idle_first': (1, 1, ['idle', 'workers'], False), 'idle_third': (3, 1, ['idle', 'idle', 'idle', 'workers'], False),
                'never_idle': (3, 0, ['idle', 'idle', 'idle'], True), 'worker_then_gone': (2, 2, ['idle', 'workers', 'idle', 'workers'], False),
                'worker_persists': (3, 3, ['idle', 'workers'] * 3, True), 'opaque_process': (3, 3, ['idle', 'workers'] * 3, True),
                'worker_then_busy_then_idle': (3, 2, ['idle', 'workers', 'idle', 'idle', 'workers'], False)}[case]
    evals, sweeps, order, failed = expected
    assert value['evals'] == evals and value['sweeps'] == sweeps and value['order'] == order, value
    assert value['sleeps'] == [10] * (evals - 1), 'IdleWaitSeconds 30 / poll 10 s bounds the evaluations to 3'
    assert value['failed'] is failed
    if failed:
        assert 'Nothing was changed' in value['message']
    if case == 'never_idle':
        assert 'offending job ids: job-7' in value['message']
    if case == 'worker_persists':
        assert 'Slot worker processes are alive after the controller reported idle (pids 4444)' in value['message']
    if case == 'opaque_process':
        assert 'could not be inspected for worker ownership after the controller reported idle (6060 svc.exe)' in value['message']
    if not failed:
        assert value['evaluations'] == evals and value['worker_count'] == 0


# --------------------------------------------------------------------------------------------------------------------
# Process proof of the live controller (never the receipt's pid)
# --------------------------------------------------------------------------------------------------------------------

PROOF_STUBS = r'''
function New-Proc {param($ProcessId,$Parent,$Path,$Command,$Created)[pscustomobject]@{ProcessId=$ProcessId;ParentProcessId=$Parent;ExecutablePath=$Path;CommandLine=$Command;CreationDate=$Created}}
function Reset-Proof {
  $script:controller=New-Proc 20664 5320 'BASEPYVALUE' '"BASEPYVALUE" R5ARGSVALUE' ([DateTime]::new(2026,10,11,12,0,56,[DateTimeKind]::Utc))
  $script:launcher=New-Proc 5320 900 'R5PYVALUE' '"R5PYVALUE" R5ARGSVALUE' ([DateTime]::new(2026,10,11,12,0,55,[DateTimeKind]::Utc))
  $script:listenerOwners=@(20664);$script:ownerUser='SYSTEM'}
function Get-CimInstance {param($ClassName,$Filter,$ErrorAction)
  if($ClassName -eq 'Win32_OperatingSystem'){return [pscustomobject]@{LastBootUpTime=[DateTime]::new(2026,10,11,0,57,0,[DateTimeKind]::Utc)}}
  if($Filter -eq 'ProcessId = 20664'){return $script:controller};if($Filter -eq 'ProcessId = 5320'){return $script:launcher};$null}
function Get-NetTCPConnection {param($LocalPort,$State,$ErrorAction)@($script:listenerOwners|ForEach-Object {[pscustomobject]@{LocalPort=47824;OwningProcess=$_}})}
function Invoke-CimMethod {param($InputObject,$MethodName,$ErrorAction)[pscustomobject]@{ReturnValue=0;User=$script:ownerUser}}
'''.replace('BASEPYVALUE', BASE_PY).replace('R5PYVALUE', R5_PY).replace('R5ARGSVALUE', R5_ARGS)
PROOF_CASES = {
    'ok': ('', ''),
    'controller_is_venv_python': (f"$script:controller.ExecutablePath='{R5_PY}';", ''),
    'parent_not_launcher': ("$script:launcher.ExecutablePath='C:\\Windows\\System32\\svchost.exe';", 'not the r5 venv launcher'),
    'parent_is_r4_launcher': (f"$script:launcher.ExecutablePath='{R4_PY}';", 'not the r5 venv launcher'),
    'parent_wrong_arguments': (f"$script:launcher.CommandLine='\"{R5_PY}\" {R4V1_ARGS}';", 'not the r5 venv launcher'),
    'controller_r4_image': (f"$script:controller.ExecutablePath='{R4_PY}';", 'does not run the r5 toolchain interpreter'),
    'controller_r4v1_arguments': (f"$script:controller.CommandLine='\"{BASE_PY}\" {R4V1_ARGS}';", 'not running the r5 daemon command'),
    'controller_other_config': (f"$script:controller.CommandLine='\"{BASE_PY}\" {r5_args(HELD_CONFIG)}';", 'not running the r5 daemon command'),
    'creation_unreadable': ('$script:controller.CreationDate=$null;', 'creation time could not be read'),
    'launcher_creation_unreadable': ('$script:launcher.CreationDate=$null;', 'launcher creation time could not be read'),
    'port_owned_elsewhere': ('$script:listenerOwners=@(4242);', 'owned by pid 4242'),
    'port_two_owners': ('$script:listenerOwners=@(20664,4242);', 'owned by pid 4242'),
    'nothing_listens': ('$script:listenerOwners=@();', 'Nothing listens on the controller port'),
    'not_system': ("$script:ownerUser='ansac';", 'does not run as SYSTEM'),
    'pid_missing': ('$pidOverride=4243;', 'does not exist'),
}


@pytest.fixture(scope='module')
def proof_results(tmp_path_factory):
    work = tmp_path_factory.mktemp('proof')
    lines = [BOUND, PROOF_STUBS, '$out=[ordered]@{}']
    for name, (change, _) in PROOF_CASES.items():
        lines.append(f"Reset-Proof;$pidOverride=20664;{change}$m='';$p=$null;try{{$p=Get-StopProcessProof $pidOverride}}catch{{$m=$_.Exception.Message}};$out['{name}']=[ordered]@{{message=$m;proof=$p}}")
    lines.append('$out|ConvertTo-Json -Depth 6 -Compress')
    return run_json('\n'.join(lines), work)


@pytest.mark.parametrize('case', list(PROOF_CASES))
def test_process_proof_binds_the_live_controller_to_the_live_action(proof_results, case):
    value = proof_results[case]
    expected = PROOF_CASES[case][1]
    if expected:
        assert expected in value['message'], value
        return
    assert value['message'] == '', value['message']
    proof = value['proof']
    if case == 'controller_is_venv_python':
        assert proof['launcher'] is None and proof['controller']['image'] == R5_PY
        return
    assert proof['controller'] == {'pid': 20664, 'image': BASE_PY, 'creation_utc': '2026-10-11T12:00:56.0000000Z', 'parent_pid': 5320}
    assert proof['launcher'] == {'pid': 5320, 'image': R5_PY, 'creation_utc': '2026-10-11T12:00:55.0000000Z'}
    assert proof['owner'] == 'SYSTEM' and proof['port_owner_verified'] is True and proof['last_boot_up_time'] == '2026-10-11T00:57:00.0000000Z'


R4_PROOF_CASES = {
    'r4_ok': ('', ''),
    'r4_parent_is_r5_launcher': (f"$script:launcher.ExecutablePath='{R5_PY}';", 'not the r4 venv launcher'),
    'r4_controller_r5_image': (f"$script:controller.ExecutablePath='{R5_PY}';", 'does not run the r4 toolchain interpreter'),
    'r4_controller_r5_arguments': (f"$script:controller.CommandLine='\"{BASE_PY}\" {R5_ARGS}';", 'not running the r4 daemon command'),
}


def test_process_proof_binds_an_r4_restore_controller_to_the_r4_action(tmp_path):
    stubs = PROOF_STUBS.replace(R5_ARGS, R4_RESTORE_ARGS).replace(R5_PY, R4_PY)
    lines = [BOUND_R4, stubs, '$out=[ordered]@{}']
    for name, (change, _) in R4_PROOF_CASES.items():
        lines.append(f"Reset-Proof;{change}$m='';$p=$null;try{{$p=Get-StopProcessProof 20664}}catch{{$m=$_.Exception.Message}};$out['{name}']=[ordered]@{{message=$m;proof=$p}}")
    lines.append('$out|ConvertTo-Json -Depth 6 -Compress')
    value = run_json('\n'.join(lines), tmp_path)
    for name, (_, expected) in R4_PROOF_CASES.items():
        if expected:
            assert expected in value[name]['message'], (name, value[name])
        else:
            assert value[name]['message'] == '' and value[name]['proof']['launcher']['image'] == R4_PY and value[name]['proof']['controller']['image'] == BASE_PY


def test_process_identity_uses_pid_and_creation_time(tmp_path):
    procs = {'absent': '$null', 'same': '[pscustomobject]@{ProcessId=20664;CreationDate=[DateTime]::new(2026,10,11,12,0,56,[DateTimeKind]::Utc)}',
             'reused_pid': '[pscustomobject]@{ProcessId=20664;CreationDate=[DateTime]::new(2026,10,11,13,0,0,[DateTimeKind]::Utc)}',
             'creation_unreadable': '[pscustomobject]@{ProcessId=20664;CreationDate=$null}'}
    lines = ['$out=[ordered]@{}']
    for name, proc in procs.items():
        lines.append(f"function Get-CimInstance {{param($ClassName,$Filter,$ErrorAction){proc}}};$out['{name}']=(Test-ProcessInstancePresent 20664 '2026-10-11T12:00:56.0000000Z')")
    lines.append('$out|ConvertTo-Json -Compress')
    value = run_json('\n'.join(lines), tmp_path)
    assert value == {'absent': False, 'same': True, 'reused_pid': False, 'creation_unreadable': True}, 'a reused pid is gone; an unreadable creation time is kept as present'


def test_running_instance_is_recorded_not_asserted(tmp_path):
    body = TASK_FIXTURE + r'''
      $folder=New-FixtureFolder @{}
      $proof=[ordered]@{controller=[ordered]@{pid=20664;image='x';creation_utc='c'};launcher=[ordered]@{pid=5320;image='y';creation_utc='d'}}
      $a=Get-RunningInstanceEvidence $script:task $proof
      $other=[ordered]@{controller=[ordered]@{pid=1;image='x';creation_utc='c'};launcher=$null}
      $b=Get-RunningInstanceEvidence $script:task $other
      $script:task|Add-Member -Force ScriptMethod GetInstances {param($n)throw 'denied'}
      $c=Get-RunningInstanceEvidence $script:task $proof
      [ordered]@{a=$a;b=$b;c=$c}|ConvertTo-Json -Compress'''
    value = run_json(body, tmp_path)
    assert value['a'] == {'readable': True, 'instance_guid': '{0F5A2C3E-0000-4000-8000-000000000005}', 'engine_pid': 5320, 'engine_pid_is_proven_process': True, 'asserted': False}
    assert value['b']['engine_pid_is_proven_process'] is False and value['b']['asserted'] is False
    assert value['c']['readable'] is False and value['c']['engine_pid'] is None


# --------------------------------------------------------------------------------------------------------------------
# Client configuration pin (verifier finding)
# --------------------------------------------------------------------------------------------------------------------

CLIENT_CASES = {
    'valid': ('{"port": 47824, "token_file": "TOKEN"}', ''),
    'valid_with_bom': ('\ufeff{"port": 47824, "token_file": "TOKEN"}', ''),
    'other_port': ('{"port": 47825, "token_file": "TOKEN"}', 'does not name the controller port 47824'),
    'port_string': ('{"port": "47824", "token_file": "TOKEN"}', 'does not name the controller port 47824'),
    'port_float': ('{"port": 47824.0, "token_file": "TOKEN"}', 'does not name the controller port 47824'),
    'port_missing': ('{"token_file": "TOKEN"}', 'does not name the controller port 47824'),
    'other_token': ('{"port": 47824, "token_file": "C:\\\\Users\\\\ansac\\\\other.token"}', 'pinned controller token file'),
    'token_missing': ('{"port": 47824}', 'pinned controller token file'),
    'not_json': ('{"port": 47824', 'not UTF-8 JSON'),
    'json_array': ('[47824]', 'not a JSON object'),
    'oversize': ('{"port": 47824, "token_file": "TOKEN", "pad": "' + 'x' * 70000 + '"}', 'not a small file'),
}


@pytest.fixture(scope='module')
def client_results(tmp_path_factory):
    work = tmp_path_factory.mktemp('client')
    lines = ['$out=[ordered]@{}']
    for name, (text, _) in CLIENT_CASES.items():
        path = work / f'{name}.json'
        path.write_bytes(text.replace('TOKEN', TOKEN_FILE.replace('\\', '\\\\')).encode('utf-8'))
        lines.append(f"$script:clientConfig='{ps(path)}';$m='';$r=$null;try{{$r=Assert-ClientConfig}}catch{{$m=$_.Exception.Message}};$out['{name}']=[ordered]@{{message=$m;result=$r}}")
    lines.append('$out|ConvertTo-Json -Depth 4 -Compress')
    return {'results': run_json('\n'.join(lines), work), 'work': work}


@pytest.mark.parametrize('case', list(CLIENT_CASES))
def test_client_configuration_must_name_the_pinned_port_and_token_file(client_results, case):
    value = client_results['results'][case]
    expected = CLIENT_CASES[case][1]
    if expected:
        assert expected in value['message'], value
        return
    assert value['message'] == '' and value['result']['port'] == 47824 and value['result']['token_file'] == TOKEN_FILE
    assert value['result']['sha256'] == sha((client_results['work'] / f'{case}.json').read_bytes())


# --------------------------------------------------------------------------------------------------------------------
# The stop itself (Invoke-StopWarden) with the COM task, process and port fixtures
# --------------------------------------------------------------------------------------------------------------------

APPLY_OVERRIDES = {
    'pid_survives': '@{PidSurvives=$true}', 'port_listener_remains': '@{PortListenerRemains=$true}', 'exclusive_bind_refused': '@{ExclusiveBindRefused=$true}',
    'stop_ineffective': '@{StopEffective=$false}', 'worker_survives': '@{WorkerSurvives=$true}', 'stop_throws': '@{StopThrows=$true}',
    'disable_changes_xml': '@{DisableChangesXml=$true}', 'disable_changes_sddl': "@{DisableSddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'}",
    'disable_changes_trigger': '@{DisableChangesTrigger=$true}', 'readback_unreadable': '@{DenyAfterDisable=$true}', 'receipt_collision': '@{ReceiptCollision=$true}',
    'task_changed_during_preparation': '@{ChangeXmlOnIntent=$true}',
    'noop_enabled': '@{State=3;Instances=0;LastTaskResult=267014}', 'noop_disabled': "@{Enabled=$false;State=1;Instances=0;LastTaskResult=267014;Xml='" + TASK_XML_DISABLED + "'}",
    'noop_port_busy': '@{State=3;Instances=0}', 'noop_controller_alive': '@{State=3;Instances=0}', 'noop_worker': '@{State=3;Instances=0}',
    'noop_disable_gate_listener': '@{State=3;Instances=0}',
}
APPLY_FLAGS = {
    'not_idle': '$script:notIdle=$true;', 'other_daemon_active': '$script:otherActive=$true;', 'proof_changed_before_end': '$script:proofGone=$true;',
    'foreign_controller': '$script:foreignPids=@(9999);', 'worker_after_idle_then_gone': "$script:workerPlan=@('4444','','');",
    'worker_after_idle_persists': "$script:workerPlan=@('4444','4444','4444');", 'disable_gate_listener': '$script:listenAtCall=3;',
    'final_check_listener': '$script:listenAtCall=4;', 'root_create_fails_after_create': "$script:rootFailure='after';",
    'root_create_fails_before_create': "$script:rootFailure='before';", 'noop_port_busy': '$script:portFree=$false;',
    'noop_controller_alive': '$script:alivePids=@(20664);', 'noop_worker': '$script:workerPids=@(4444);', 'noop_disable_gate_listener': '$script:listenAtCall=2;',
}
RUNNING_EVENTS = ['root', 'write:warden-task-before.xml', 'write:warden-task-before.sddl', 'write:idle-evidence.json', 'write:stop-intent.json', 'stop', 'disable',
                  'write:warden-task-after.xml', 'write:warden-task-after.sddl', 'write:stop-receipt.json']
NOOP_EVENTS = ['root', 'write:warden-task-before.xml', 'write:warden-task-before.sddl', 'write:stop-intent.json', 'disable', 'write:warden-task-after.xml',
               'write:warden-task-after.sddl', 'write:stop-receipt.json']
RECEIPT_FIELDS = {'schema', 'status', 'attempt', 'retarget_target', 'retarget_attempt', 'task_name', 'runtime_bindings', 'action', 'task_xml_after_sha256', 'enabled_after', 'instances_after', 'port_free_after',
                  'ended_by_this_run', 'disabled_by_this_run', 'last_task_result', 'last_task_result_expected', 'last_task_result_asserted', 'triggers', 'mode', 'runtime_root',
                  'start_receipt_sha256', 'start_receipt_controller_bound', 'next_start_expectations', 'processes_killed', 'observer_and_recorder_tasks_touched',
                  # C-F1(b) and C-F5 (FIXD-RETARGET's lineage reads these)
                  'start_binding', 'retarget_receipt_path', 'retarget_receipt_sha256', 'start_intent_path', 'start_intent_sha256', 'start_held_path', 'start_held_sha256',
                  'source_task_xml_after_path', 'source_task_xml_after_sha256', 'source_task_xml_started_sha256', 'live_xml_matches_source_outside_enabled_flags',
                  'trigger_enabled_before', 'trigger_enabled_after', 'trigger_state_basis', 'start_receipt_path'}


R4_APPLY_OVERRIDES = {
    'r4_success': R4_TASK + '}', 'r4_noop_enabled': R4_TASK + ';State=3;Instances=0;LastTaskResult=267014}',
    'r4_noop_disabled': R4_TASK.replace(TASK_XML_R4, TASK_XML_R4_DISABLED) + ';Enabled=$false;State=1;Instances=0;LastTaskResult=267014}',
    'r4_pid_survives': R4_TASK + ';PidSurvives=$true}', 'r4_root_create_fails_after_create': R4_TASK + '}',
}


def drive_apply(tmp_path, case):
    target = tmp_path / 'stop-root'
    if case == 'root_exists':
        target.mkdir()
    r4 = case.startswith('r4_')
    overrides = R4_APPLY_OVERRIDES[case] if r4 else APPLY_OVERRIDES.get(case, '@{}')
    flags = "$script:rootFailure='after';" if case == 'r4_root_create_fails_after_create' else APPLY_FLAGS.get(case, '')
    body = (TASK_FIXTURE + STUBS + (BOUND_R4 if r4 else BOUND) + f"$folder=New-FixtureFolder {overrides};$script:targetRoot='{ps(target)}';{flags}" + r'''
      $failed=$false;$message='';$result=$null;try{$result=Invoke-StopWarden $folder $bindings $startReceipt}catch{$failed=$true;$message=$_.Exception.Message}
      [ordered]@{failed=$failed;message=$message;stops=$script:stops;stop_flags=$script:stopFlags;events=@($script:events);enabled_writes=@($script:enabledWrites);enabled=$script:fxEnabled;
        sleeps=@($script:sleeps);idle_evaluations=$script:idleEvaluations;worker_sweeps=$script:workerSweeps;trace=@($script:trace);presence_calls=$script:presenceCalls;
        result=$result;root=(Test-Path -LiteralPath $script:targetRoot);xml_now=$script:task.Xml}|ConvertTo-Json -Depth 6 -Compress''')
    return run_json(body, tmp_path, timeout=240), target


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', ['success', 'worker_after_idle_then_gone'])
def test_running_stop_ends_once_then_disables_and_writes_the_bound_receipt(tmp_path, case):
    value, target = drive_apply(tmp_path, case)
    assert not value['failed'], value['message']
    receipt_path = target / 'stop-receipt.json'
    receipt, intent = read_json(receipt_path), read_json(target / 'stop-intent.json')
    after_xml = (target / 'warden-task-after.xml').read_bytes()
    assert not (target / 'stop-held.json').exists() and value['events'] == RUNNING_EVENTS
    assert value['stops'] == 1 and value['stop_flags'] == 0 and len(value['enabled_writes']) == 1 and value['enabled'] is False
    for write in value['enabled_writes']:
        assert write['value'] is False and write['instances'] == 0 and write['port_free'] is True and write['port_listening'] == 0 and write['alive'] == 0, \
            'Enabled is set false only after instances==0, the port is free and no controller pid is alive'
    if case == 'success':
        assert value['idle_evaluations'] == 1 and value['sleeps'] == [] and value['trace'][:3] == ['idle', 'workers', 'proof']
    else:
        assert value['idle_evaluations'] == 2 and value['sleeps'] == [10] and value['trace'][:5] == ['idle', 'workers', 'idle', 'workers', 'proof'], \
            'a slot worker alive after the first idle evaluation is polled, not refused'
    assert RECEIPT_FIELDS <= set(receipt), RECEIPT_FIELDS - set(receipt)
    assert receipt['schema'] == 'cochem-warden-stop/2' and receipt['status'] == 'WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED' and receipt['mode'] == 'RUNNING'
    assert receipt['attempt'] == 'v1' and receipt['retarget_attempt'] == 'v3' and receipt['task_name'] == 'CoChem-4.2.7-Warden' and receipt['runtime_root'] == R5_ROOT
    assert receipt['retarget_target'] == 'r5' and 'r5_bindings' not in receipt
    assert receipt['action'] == {'execute': R5_PY, 'arguments': R5_ARGS, 'working_directory': R5_ROOT}
    assert receipt['triggers'] == [{'type': 'logon', 'user_id': 'AETHERDESK\\ansac', 'delay': 'PT1M', 'enabled': True}]
    assert receipt['task_xml_after_sha256'] == sha(after_xml) == sha(value['xml_now'].encode('utf-8')), 'the sha of the live XML string the retarget will read'
    assert b'<Settings><Enabled>false</Enabled>' in after_xml and b'<Enabled>' not in (target / 'warden-task-before.xml').read_bytes().replace(b'<LogonTrigger><Enabled>', b'')
    assert receipt['enabled_after'] is False and receipt['instances_after'] == 0 and receipt['port_free_after'] is True
    assert receipt['ended_by_this_run'] is True and receipt['disabled_by_this_run'] is True and receipt['unclean_shutdown_expected'] is True
    assert receipt['last_task_result'] == 267014 and receipt['last_task_result_expected'] == 267014 and receipt['last_task_result_asserted'] is False
    assert receipt['start_receipt_sha256'] == 'e' * 64 and receipt['start_receipt_controller_bound'] is False and receipt['runtime_bindings']['install_after_sha256'] == 'a' * 64
    assert receipt['start_binding'] == 'START_RECEIPT' and receipt['start_receipt_path'] == START_RECEIPT and receipt['retarget_receipt_sha256'] == '1' * 64
    assert receipt['start_intent_sha256'] == '2' * 64 and receipt['start_held_sha256'] is None and receipt['source_task_xml_after_sha256'] == '3' * 64
    assert receipt['source_task_xml_started_sha256'] == '4' * 64 and receipt['live_xml_matches_source_outside_enabled_flags'] is True
    assert receipt['trigger_enabled_before'] is True and receipt['trigger_enabled_after'] is True and receipt['trigger_state_basis'] == 'START_RECEIPT_TRIGGER_ENABLED'
    assert receipt['controller'] == {'pid': 20664, 'launcher_pid': 5320, 'instance_id': '0f5a2c3e9b8d4e7fa1b2c3d4e5f60718', 'process_started_at': 1791720056.25}
    assert receipt['running_instance']['engine_pid'] == 5320 and receipt['running_instance']['asserted'] is False
    assert receipt['processes_killed'] is False and receipt['observer_and_recorder_tasks_touched'] is False and receipt['observer_processes'][0]['pid'] == 9472
    assert receipt['sddl_preserved'] is True and receipt['xml_unchanged_outside_settings_enabled'] is True and receipt['triggers_unchanged'] is True
    expectations = receipt['next_start_expectations']
    assert expectations['crash_record_written'] is False and expectations['expected_startup_quarantines'] == 0 and expectations['ram_ledger_expected_action'] == 'VERIFY'
    assert expectations['fresh_queue_launch_child_per_start'] is True and expectations['queue_launch_output_root'] == QUEUE_ROOT and expectations['logon_trigger_inert_while_disabled'] is True
    assert expectations['queue_launch_output'] is None and expectations['fresh_queue_launch_output_required'] is False
    assert receipt['controller_exit']['complete'] is True and receipt['controller_exit']['polls'] == 1
    assert intent['schema'] == 'cochem-warden-stop-intent/2' and intent['retarget_attempt'] == 'v3' and intent['kill_allowed'] is False and intent['unclean_shutdown_expected'] is True
    assert intent['retarget_target'] == 'r5' and intent['runtime_root'] == R5_ROOT
    assert intent['task_xml_before_sha256'] == sha((target / 'warden-task-before.xml').read_bytes()) == sha(TASK_XML.encode())
    assert intent['idle_evidence_sha256'] == sha((target / 'idle-evidence.json').read_bytes()) and intent['action_before']['arguments'] == R5_ARGS
    result = value['result']
    assert result['schema'] == 'cochem-warden-stop-result/2' and result['status'] == receipt['status'] and result['receipt_path'] == str(receipt_path)
    assert result['receipt_sha256'] == sha(receipt_path.read_bytes()) and result['task_xml_after_sha256'] == receipt['task_xml_after_sha256']
    assert result['enabled_after'] is False and result['instances_after'] == 0 and result['port_free_after'] is True and result['retarget_attempt'] == 'v3'
    assert result['retarget_target'] == 'r5' and result['runtime_root'] == R5_ROOT and result['start_binding'] == 'START_RECEIPT' and result['trigger_enabled_after'] is True
    assert intent['start_binding'] == 'START_RECEIPT' and intent['retarget_receipt_sha256'] == '1' * 64 and intent['trigger_enabled_before'] is True


@pytest.mark.parametrize('case', ['r4_success', 'r4_noop_enabled', 'r4_noop_disabled'])
def test_r4_restore_stop_records_the_r4_target_and_disables_the_task(tmp_path, case):
    value, target = drive_apply(tmp_path, case)
    assert not value['failed'], value['message']
    receipt_path = target / 'stop-receipt.json'
    receipt, intent = read_json(receipt_path), read_json(target / 'stop-intent.json')
    assert RECEIPT_FIELDS <= set(receipt), RECEIPT_FIELDS - set(receipt)
    assert receipt['retarget_target'] == 'r4' and receipt['retarget_attempt'] == 'v3' and receipt['runtime_root'] == R4_ROOT
    assert receipt['action'] == {'execute': R4_PY, 'arguments': R4_RESTORE_ARGS, 'working_directory': R4_ROOT} and receipt['triggers'] in ([], None)
    assert receipt['enabled_after'] is False and receipt['instances_after'] == 0 and receipt['port_free_after'] is True
    assert receipt['task_xml_after_sha256'] == sha(value['xml_now'].encode('utf-8')) == sha((target / 'warden-task-after.xml').read_bytes())
    assert receipt['runtime_bindings']['runtime'] == 'r4' and receipt['runtime_bindings']['revision_sha256'] == R4_REVISION_PIN
    assert receipt['start_receipt_path'] == START_RECEIPT_R4 and receipt['start_receipt_sha256'] == 'f' * 64
    assert receipt['start_binding'] == 'START_RECEIPT' and receipt['trigger_enabled_before'] is None and receipt['trigger_enabled_after'] is None
    assert receipt['trigger_state_basis'] == 'NO_TRIGGER' and receipt['retarget_receipt_path'] == RETARGET_ROOT_R4 + r'\retarget-receipt.json'
    expectations = receipt['next_start_expectations']
    assert expectations['queue_launch_output'] == queue_restart() and expectations['queue_launch_output_root'] is None
    assert expectations['fresh_queue_launch_output_required'] is True and expectations['fresh_queue_launch_child_per_start'] is False
    assert expectations['logon_trigger_inert_while_disabled'] is None
    assert intent['retarget_target'] == 'r4' and intent['runtime_root'] == R4_ROOT and intent['triggers_before'] in ([], None)
    result = value['result']
    assert result['retarget_target'] == 'r4' and result['runtime_root'] == R4_ROOT and result['receipt_sha256'] == sha(receipt_path.read_bytes())
    if case == 'r4_success':
        assert receipt['status'] == 'WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED' and value['events'] == RUNNING_EVENTS and value['stops'] == 1
        assert receipt['ended_by_this_run'] is True and receipt['disabled_by_this_run'] is True and value['trace'][:3] == ['idle', 'workers', 'proof']
        assert receipt['process_proof']['launcher']['image'] == R4_PY
    elif case == 'r4_noop_enabled':
        assert receipt['status'] == 'WARDEN_ALREADY_STOPPED_CLEAN_NOOP' and value['events'] == NOOP_EVENTS and value['stops'] == 0
        assert receipt['disabled_by_this_run'] is True and value['idle_evaluations'] == 0, 'an idle enabled r4 restore is disabled so enabled_after is false'
    else:
        assert receipt['status'] == 'WARDEN_ALREADY_STOPPED_CLEAN_NOOP' and value['enabled_writes'] == [] and receipt['disabled_by_this_run'] is False
        assert value['xml_now'] == TASK_XML_R4_DISABLED


@pytest.mark.parametrize('case', ['r4_pid_survives', 'r4_root_create_fails_after_create'])
def test_r4_held_records_carry_the_r4_target(tmp_path, case):
    value, target = drive_apply(tmp_path, case)
    assert value['failed']
    held = read_json(target / 'stop-held.json')
    assert held['retarget_target'] == 'r4' and held['retarget_attempt'] == 'v3' and held['processes_killed'] is False
    assert held['phase'] == ('END_WAIT' if case == 'r4_pid_survives' else 'ROOT_CREATE')
    if case == 'r4_pid_survives':
        assert held['runtime_root'] == R4_ROOT and value['enabled'] is True and value['enabled_writes'] == []


@pytest.mark.parametrize('case', ['noop_enabled', 'noop_disabled'])
def test_already_stopped_task_is_a_clean_noop_that_still_disables_an_enabled_task(tmp_path, case):
    value, target = drive_apply(tmp_path, case)
    assert not value['failed'], value['message']
    receipt = read_json(target / 'stop-receipt.json')
    assert value['stops'] == 0 and value['idle_evaluations'] == 0 and 'proof' not in value['trace'], 'no idle wait and no End'
    assert receipt['status'] == 'WARDEN_ALREADY_STOPPED_CLEAN_NOOP' and receipt['mode'] == 'ALREADY_STOPPED' and receipt['ended_by_this_run'] is False
    assert receipt['enabled_after'] is False and receipt['instances_after'] == 0 and receipt['port_free_after'] is True and receipt['retarget_attempt'] == 'v3'
    assert receipt['task_xml_after_sha256'] == sha(value['xml_now'].encode('utf-8')) == sha((target / 'warden-task-after.xml').read_bytes())
    assert receipt['idle_evidence_sha256'] is None and receipt['unclean_shutdown_expected'] is False and receipt['next_start_expectations']['evidenced'] is False
    assert receipt['last_task_result_expected'] is None and receipt['controller'] is None
    if case == 'noop_enabled':
        assert value['events'] == NOOP_EVENTS and receipt['disabled_by_this_run'] is True and len(value['enabled_writes']) == 1
        assert value['enabled_writes'][0]['instances'] == 0 and value['enabled_writes'][0]['port_free'] is True
        assert '<Settings><Enabled>false</Enabled>' in value['xml_now']
    else:
        assert value['events'] == [e for e in NOOP_EVENTS if e != 'disable'] and value['enabled_writes'] == [] and receipt['disabled_by_this_run'] is False, \
            'an already disabled task is not written'
        assert value['xml_now'] == TASK_XML_DISABLED and receipt['task_xml_before_sha256'] == receipt['task_xml_after_sha256']


REFUSED_CASES = {
    'not_idle': 'offending job ids: job-7', 'other_daemon_active': 'must remain stopped and disabled', 'root_exists': 'already exists',
    'foreign_controller': '9999', 'worker_after_idle_persists': 'Slot worker processes are alive after the controller reported idle (pids 4444)',
    'noop_port_busy': 'cannot be bound exclusively', 'noop_controller_alive': 'a controller process', 'noop_worker': 'Slot worker processes are alive',
    'root_create_fails_before_create': 'The stop root could not be created',
}


@pytest.mark.parametrize('case', list(REFUSED_CASES))
def test_refusals_before_the_stop_root_change_nothing(tmp_path, case):
    value, target = drive_apply(tmp_path, case)
    assert value['failed'] and REFUSED_CASES[case] in value['message'], value['message']
    assert 'othing was changed' in value['message'], 'refusals before the stop root exists change nothing'
    assert value['stops'] == 0 and value['enabled_writes'] == [] and 'root' not in value['events'] and not any(e.startswith('write:') for e in value['events'])
    assert value['root'] is (case == 'root_exists')
    if case == 'root_exists':
        assert list(target.iterdir()) == [], 'a root that existed before this run is never written to'
    if case == 'not_idle':
        assert value['idle_evaluations'] == 3 and value['sleeps'] == [10, 10] and value['worker_sweeps'] == 0
    if case == 'worker_after_idle_persists':
        assert value['idle_evaluations'] == 3 and value['worker_sweeps'] == 3 and 'proof' not in value['trace']


HELD_CASES = {
    # phase, events, stops, disable writes, message fragment
    'proof_changed_before_end': ('PREPARATION', RUNNING_EVENTS[:5], 0, 0, 'Nothing was ended, disabled or killed'),
    'task_changed_during_preparation': ('PREPARATION', RUNNING_EVENTS[:5], 0, 0, 'Nothing was ended, disabled or killed'),
    'stop_throws': ('END_REQUEST', RUNNING_EVENTS[:6], 1, 0, 'The task was NOT disabled and nothing was killed'),
    'pid_survives': ('END_WAIT', RUNNING_EVENTS[:6], 1, 0, 'Surviving pid(s): 20664'),
    'port_listener_remains': ('END_WAIT', RUNNING_EVENTS[:6], 1, 0, 'The task was NOT disabled and nothing was killed'),
    'exclusive_bind_refused': ('END_WAIT', RUNNING_EVENTS[:6], 1, 0, 'The task was NOT disabled and nothing was killed'),
    'stop_ineffective': ('END_WAIT', RUNNING_EVENTS[:6], 1, 0, 'The task was NOT disabled and nothing was killed'),
    'worker_survives': ('END_WAIT', RUNNING_EVENTS[:6], 1, 0, 'The task was NOT disabled and nothing was killed'),
    'disable_gate_listener': ('DISABLE', RUNNING_EVENTS[:6], 1, 0, 'held at the disable gate'),
    'noop_disable_gate_listener': ('DISABLE', NOOP_EVENTS[:4], 0, 0, 'held at the disable gate'),
    'disable_changes_xml': ('DISABLE_READBACK', RUNNING_EVENTS[:9], 1, 1, 'may already be disabled'),
    'disable_changes_sddl': ('DISABLE_READBACK', RUNNING_EVENTS[:9], 1, 1, 'may already be disabled'),
    'disable_changes_trigger': ('DISABLE_READBACK', RUNNING_EVENTS[:9], 1, 1, 'may already be disabled'),
    'readback_unreadable': ('DISABLE_READBACK', RUNNING_EVENTS[:7], 1, 1, 'may already be disabled'),
    'final_check_listener': ('FINAL_CHECK', RUNNING_EVENTS[:9], 1, 1, 'held after the disabled task was verified'),
    'receipt_collision': ('RECEIPT', RUNNING_EVENTS[:9], 1, 1, 'The Warden is ended and disabled but the stop receipt could not be completed'),
    'root_create_fails_after_create': ('ROOT_CREATE', ['root'], 0, 0, 'The stop root could not be secured'),
}


@pytest.mark.parametrize('case', list(HELD_CASES))
def test_every_failure_after_the_root_leaves_stop_held_and_never_kills(tmp_path, case):
    phase, events, stops, writes, fragment = HELD_CASES[case]
    value, target = drive_apply(tmp_path, case)
    assert value['failed'] and fragment in value['message'], value['message']
    held = read_json(target / 'stop-held.json')
    assert held['schema'] == 'cochem-warden-stop-held/2' and held['phase'] == phase and held['retarget_attempt'] == 'v3' and held['retarget_target'] == 'r5'
    assert held['processes_killed'] is False and held['requires_reviewed_recovery'] is True and held['automatic_retry_allowed'] is False
    assert value['events'] == events + ['write:stop-held.json'], value['events']
    assert value['stops'] == stops and len(value['enabled_writes']) == writes
    assert held['end_requested'] is (stops == 1) and held['disable_requested'] is (writes == 1)
    if case == 'receipt_collision':
        assert (target / 'stop-receipt.json').read_text() == '{}', 'CreateNew: a receipt that is not this run\'s is never overwritten'
    else:
        assert not (target / 'stop-receipt.json').exists()
    if phase in ('END_REQUEST', 'END_WAIT', 'DISABLE'):
        assert value['enabled'] is True and 'The task was NOT disabled' in value['message'], 'no disable when anything survives or the gate fails'
    if phase == 'END_WAIT':
        assert held['exit_observation']['polls'] == 4 and value['sleeps'] == [3, 3, 3], 'ExitWaitSeconds 9 / poll 3 s -> 4 bounded polls'
    if case == 'pid_survives':
        assert [p['pid'] for p in held['surviving_processes']] == [20664]
    if case == 'stop_ineffective':
        assert 'still shows state 4 with 1 instance' in held['reason'] and {p['pid'] for p in held['surviving_processes']} == {20664, 5320}
    if case == 'worker_survives':
        assert held['worker_pids'] == [7777] and 'Slot worker processes are alive' in held['reason']
    if case == 'exclusive_bind_refused':
        assert held['port_listening'] == 0 and held['exclusive_bind_free'] is False
    if case == 'disable_changes_trigger':
        assert 'triggers differ' in held['reason']
    if case == 'final_check_listener':
        assert value['enabled'] is False and 'present after the disable' in held['reason']
    if case == 'root_create_fails_after_create':
        assert held['root_preserved'] is True and 'Nothing was ended or disabled' in value['message'] and 'choose another -Attempt' in value['message']
    if case == 'proof_changed_before_end':
        assert 'pid 20664 changed during preparation' in value['message']
    if case == 'task_changed_during_preparation':
        assert 'task definition changed during preparation' in value['message']


def test_noop_receipt_collision_on_a_disabled_task_is_held_without_any_task_write(tmp_path):
    target = tmp_path / 'stop-root'
    body = (TASK_FIXTURE + STUBS + BOUND + f"$folder=New-FixtureFolder {APPLY_OVERRIDES['noop_disabled']};$script:targetRoot='{ps(target)}';" + r'''
      function Test-LoopbackFree {$script:loopbackProbes++;if($script:loopbackProbes -eq 2){[IO.File]::WriteAllText((Join-Path $script:targetRoot 'stop-receipt.json'),'{}')};$true}
      $failed=$false;$message='';try{$null=Invoke-StopWarden $folder $bindings $startReceipt}catch{$failed=$true;$message=$_.Exception.Message}
      [ordered]@{failed=$failed;message=$message;events=@($script:events);enabled_writes=@($script:enabledWrites);stops=$script:stops}|ConvertTo-Json -Depth 4 -Compress''')
    value = run_json(body, tmp_path, timeout=240)
    assert value['failed'] and 'The Warden is disabled but the stop receipt could not be completed' in value['message']
    held = read_json(target / 'stop-held.json')
    assert held['phase'] == 'RECEIPT' and held['disable_requested'] is False and value['enabled_writes'] == [] and value['stops'] == 0
    assert (target / 'stop-receipt.json').read_text() == '{}'


# --------------------------------------------------------------------------------------------------------------------
# The plan and the -Apply dispatch (Invoke-StopWardenSession) over the fixture runtime
# --------------------------------------------------------------------------------------------------------------------

SESSION_CASES = {
    # name: (apply, admin, task overrides, flags, runtime mutator)
    'plan_unelevated_deferred': (False, False, '@{DenyGetTask=$true}', '', None),
    'plan_running_idle': (False, False, '@{}', '', None),
    'plan_admin_running_with_proof': (False, True, '@{}', '', None),
    'plan_admin_code_tree_refused': (False, True, '@{}', '$script:codeTreeFails=$true;', None),
    'plan_receipt_missing': (False, False, '@{}', '', post(START_RECEIPT, None)),
    'plan_install_changed': (False, False, '@{}', '', post(R5_ROOT + r'\install-after.json', lambda data: data + b' ')),
    'plan_client_config_port': (False, False, '@{}', 'CLIENTPORT', None),
    'plan_worker_alive': (False, False, '@{}', '$script:workerPids=@(4444);', None),
    'plan_not_idle': (False, False, '@{}', '$script:notIdle=$true;', None),
    'plan_noop_port_busy': (False, False, '@{State=3;Instances=0}', '$script:portFree=$false;', None),
    'plan_root_exists': (False, False, '@{}', 'ROOTEXISTS', None),
    'plan_other_daemon_active': (False, False, '@{}', '$script:otherActive=$true;', None),
    'plan_task_is_r4v1': (False, False, "@{Path='" + R4_PY + "';Arguments='" + R4V1_ARGS + "';WorkingDirectory='" + R4_ROOT + "';Triggers=@()}", '', None),
    'apply_held_receipt_missing': (True, True, '@{}', '', post(START_RECEIPT, None)),
    'apply_running_worker_polled': (True, True, '@{}', "$script:workerPlan=@('4444','','');", None),
    'apply_noop_worker_held': (True, True, '@{State=3;Instances=0}', '$script:workerPids=@(4444);', None),
    'apply_running_success': (True, True, '@{}', '', None),
    'apply_noop_success': (True, True, '@{State=3;Instances=0;LastTaskResult=267014}', '', None),
    # Re-audit R-F5 (sweep N6): a completed start whose task was disabled while its instance runs is stopped as RUNNING.
    'apply_running_task_disabled_after_completed_start': (True, True, "@{Enabled=$false;Xml='" + ps(TASK_XML_DISABLED) + "'}", '', None),
    # Re-audit R-F2 (sweep N5): Task Scheduler reads the logon trigger user back as the owner's SID.
    'apply_trigger_user_read_back_as_sid': (True, True, "@{Triggers=@(@{Type=9;UserId='S-1-5-21-9-9-9-1001';Delay='PT1M';Enabled=$true})}", '', None),
}


def drive_session(tmp_path, case, table=None, recover=False, live=None):
    """live: a process list for the REAL Get-ControllerPresence (live_presence below) instead of the presence stub."""
    apply, admin, overrides, flags, mutator = (table or SESSION_CASES)[case]
    ctx = runtime_ctx()
    if mutator:
        mutator(ctx)
    info = materialize(ctx, tmp_path / 'fx')
    client = tmp_path / 'client.json'
    client.write_text(json.dumps({'port': 47825 if flags == 'CLIENTPORT' else 47824, 'token_file': TOKEN_FILE}), encoding='utf-8')
    target = tmp_path / 'stop-root'
    if flags == 'ROOTEXISTS':
        target.mkdir()
    flags = '' if flags in ('CLIENTPORT', 'ROOTEXISTS') else flags
    pins = json.dumps(info['pins'])
    body = (FX_READ + TASK_FIXTURE + STUBS + (live_presence(live) if live is not None else '') +
            f"$script:RecoverInterruptedStart={'$true' if recover else '$false'};"
            f"Use-Fixture '{ps(info['base'])}' '{info['config_pin']}' '{info['probe_pin']}' ('{pins}'|ConvertFrom-Json);$script:clientConfig='{ps(client)}';$script:targetRoot='{ps(target)}';"
            f"$script:admin={'$true' if admin else '$false'};$folder=New-FixtureFolder {overrides};{flags}" + r'''
      $failed=$false;$message='';$value=$null;try{$value=Invoke-StopWardenSession $folder APPLY}catch{$failed=$true;$message=$_.Exception.Message}
      [ordered]@{failed=$failed;message=$message;value=$value;stops=$script:stops;enabled_writes=@($script:enabledWrites);idle_evaluations=$script:idleEvaluations;
        worker_sweeps=$script:workerSweeps;code_tree_calls=@($script:codeTreeCalls);events=@($script:events);trace=@($script:trace)}|ConvertTo-Json -Depth 9 -Compress'''.replace('APPLY', '$true' if apply else '$false'))
    return run_json(body, tmp_path, timeout=300), target, info


@pytest.mark.parametrize('case', [c for c in SESSION_CASES if c.startswith('plan_')])
def test_read_only_plan_reports_holds_and_changes_nothing(tmp_path, case):
    value, target, info = drive_session(tmp_path, case)
    assert not value['failed'], value['message']
    plan = value['value']
    assert plan['schema'] == 'cochem-warden-stop-plan/2' and plan['mode'] == 'READ_ONLY_PLAN' and plan['retarget_attempt'] == 'v3' and plan['attempt'] == 'v1'
    assert plan['tasks_changed'] == 0 and plan['ended'] is False and plan['disabled'] is False and plan['processes_killed'] is False
    assert value['stops'] == 0 and value['enabled_writes'] == [] and value['events'] == [], 'the plan writes nothing and touches no task'
    assert target.exists() is (case == 'plan_root_exists') and (case != 'plan_root_exists' or list(target.iterdir()) == [])
    holds = plan['holds']
    expected = {
        'plan_unelevated_deferred': ('DEFERRED', ['unreadable without elevation']),
        'plan_running_idle': ('RUNNING', []),
        'plan_admin_running_with_proof': ('RUNNING', []),
        'plan_admin_code_tree_refused': ('RUNNING', ['r5 code tree inspection', 'was not evaluated']),
        'plan_receipt_missing': ('UNBOUND', ['r5 start receipt: The r5 start receipt is missing']),
        'plan_install_changed': ('RUNNING', ['r5 runtime is not the reviewed installed build', 'was not evaluated']),
        'plan_client_config_port': ('RUNNING', ['Client configuration: The client configuration does not name the controller port 47824', 'was not evaluated']),
        'plan_worker_alive': ('RUNNING', ['Worker processes: Slot worker processes are alive; stop nothing, investigate.']),
        'plan_not_idle': ('RUNNING', ['The Warden is not idle now: queue row job-7 is PENDING; offending job ids: job-7']),
        'plan_noop_port_busy': ('ALREADY_STOPPED', ['cannot be bound exclusively']),
        'plan_root_exists': ('RUNNING', ['The stop root already exists']),
        'plan_other_daemon_active': ('RUNNING', ['Managed daemon tasks must remain stopped and disabled']),
        'plan_task_is_r4v1': ('REFUSED', ['Warden task: The Warden task action differs from the r5 action recorded by the start receipt']),
    }[case]
    assert plan['stop_mode'] == expected[0], plan['stop_mode']
    assert len(holds) == len(expected[1]), holds
    for fragment in expected[1]:
        assert any(fragment in hold for hold in holds), (fragment, holds)
    if case in ('plan_running_idle', 'plan_admin_running_with_proof', 'plan_unelevated_deferred', 'plan_not_idle', 'plan_worker_alive'):
        assert value['idle_evaluations'] == 1 and plan['idle']['controller']['source_root'] == R5_SOURCE, 'the plan evaluates the idle predicate once, read-only'
    if 'was not evaluated' in ' '.join(expected[1]) or case in ('plan_receipt_missing', 'plan_task_is_r4v1', 'plan_noop_port_busy'):
        assert value['idle_evaluations'] == 0 and plan['idle'] is None
    if case == 'plan_running_idle':
        assert plan['expected_action'] == {'execute': R5_PY, 'arguments': R5_ARGS, 'working_directory': R5_ROOT}
        assert plan['expected_triggers'] == [{'type': 'logon', 'user_id': 'AETHERDESK\\ansac', 'delay': 'PT1M'}]
        assert plan['task_summary']['task_xml_sha256'] == sha(TASK_XML.encode()) and plan['task_summary']['triggers'][0]['type'] == 'logon'
        assert plan['start_receipt']['sha256'] == info['receipt_sha256'] and plan['runtime_verified'] is True and plan['runtime_root'] == R5_ROOT
        assert plan['retarget_target'] == 'r5' and plan['runtime_bindings']['runtime'] == 'r5'
        assert plan['client_config']['port'] == 47824 and plan['process_proof'] is None and 'elevated token' in plan['process_proof_note']
        assert plan['code_tree_verified'] is None and value['code_tree_calls'] == []
    if case == 'plan_admin_running_with_proof':
        assert value['code_tree_calls'] == [R5_ROOT] and plan['code_tree_verified'] is True and plan['process_proof']['launcher']['image'] == R5_PY
    if case == 'plan_unelevated_deferred':
        assert plan['task_readable'] is False and plan['task_summary'] is None


def test_apply_with_any_hold_refuses_before_any_change(tmp_path):
    value, target, _ = drive_session(tmp_path, 'apply_held_receipt_missing')
    assert value['failed'] and value['message'].startswith('The Warden stop is held. Nothing was changed: r5 start receipt:')
    assert value['stops'] == 0 and value['enabled_writes'] == [] and value['events'] == [] and not target.exists()


def test_apply_with_a_live_worker_on_an_already_stopped_task_is_held(tmp_path):
    value, target, _ = drive_session(tmp_path, 'apply_noop_worker_held')
    assert value['failed'] and 'Worker processes: Slot worker processes are alive' in value['message'] and 'Nothing was changed' in value['message']
    assert value['events'] == [] and not target.exists()


@pytest.mark.parametrize('case', ['apply_running_worker_polled', 'apply_running_success', 'apply_noop_success'])
def test_apply_dispatch_binds_the_receipt_and_stops(tmp_path, case):
    value, target, info = drive_session(tmp_path, case)
    assert not value['failed'], value['message']
    result = value['value']
    receipt = read_json(target / 'stop-receipt.json')
    assert result['schema'] == 'cochem-warden-stop-result/2' and result['receipt_sha256'] == sha((target / 'stop-receipt.json').read_bytes())
    assert receipt['start_receipt_sha256'] == info['receipt_sha256'] and receipt['runtime_bindings']['install_after_sha256'] == info['receipt']['install_after_sha256']
    assert receipt['runtime_bindings']['task_config_sha256'] == info['receipt']['config_sha256'] and receipt['retarget_attempt'] == 'v3' and receipt['retarget_target'] == 'r5'
    assert value['code_tree_calls'] == [R5_ROOT]
    assert receipt['start_binding'] == 'START_RECEIPT' and receipt['retarget_receipt_sha256'] == info['retarget_sha256'] and receipt['start_intent_sha256'] == info['intent_sha256']
    assert receipt['source_task_xml_after_sha256'] == info['after_xml_sha256'] and receipt['source_task_xml_started_sha256'] == info['started_xml_sha256']
    assert receipt['trigger_enabled_after'] is True and receipt['trigger_state_basis'] == 'START_RECEIPT_TRIGGER_ENABLED' and receipt['start_held_sha256'] is None
    assert receipt['runtime_bindings']['freeze_manifest_pinned'] is True and receipt['runtime_bindings']['a6_repair_set_asserted'] is True
    if case == 'apply_noop_success':
        assert result['status'] == 'WARDEN_ALREADY_STOPPED_CLEAN_NOOP' and value['stops'] == 0 and receipt['disabled_by_this_run'] is True
        return
    assert result['status'] == 'WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED' and value['stops'] == 1 and len(value['enabled_writes']) == 1
    assert value['idle_evaluations'] == 1, '-Apply does not evaluate the plan idle predicate; it polls inside the stop'
    if case == 'apply_running_worker_polled':
        assert value['worker_sweeps'] == 3 and value['trace'][:3] == ['workers', 'idle', 'workers'], \
            'a worker seen by the session sweep is not a hold for a RUNNING -Apply; the post-idle sweep decides'


INTERRUPTED_SESSION_CASES = {
    # C-F1(b) end to end with -RecoverInterruptedStart: (apply, admin, task overrides, flags, fixture mutator)
    'apply_interrupted_held_running_task_disabled': (True, True, "@{Enabled=$false;" + TRIGGER_OFF + ";Xml='" + ps(SOURCE_XML) + "'}", '', held_record()),
    'apply_crashed_no_record_stopped_trigger_off': (True, True, "@{State=3;Instances=0;LastTaskResult=267014;" + TRIGGER_OFF + ";Xml='" + ps(LIVE_XML_TRIGGER_OFF) + "'}", '',
                                                    no_start_receipt),
    'apply_crashed_in_the_trigger_enable_window': (True, True, '@{}', '', no_start_receipt),
    'apply_held_after_health_gate_trigger_enabled': (True, True, "@{Enabled=$false;Xml='" + ps(TASK_XML_DISABLED) + "'}", '',
                                                     held_record(interrupted=False, health_gate_passed=True, stage='RECEIPT', trigger_enable_requested=True, trigger_enabled_after=True)),
    # Re-audit R-F1 (sweep N1/N2): a health gate that timed out or failed after Run; the held path disabled the task, the instance runs.
    'apply_held_before_health_gate_running_task_disabled': (True, True, "@{Enabled=$false;" + TRIGGER_OFF + ";Xml='" + ps(SOURCE_XML) + "'}", '',
                                                            held_record(interrupted=False, reason='the controller reports 1 execution quarantine row(s)')),
    'apply_held_says_trigger_disabled_live_enabled': (True, True, '@{}', '', held_record()),
    'apply_held_before_run_refused': (True, True, "@{Enabled=$false;State=1;Instances=0;" + TRIGGER_OFF + ";Xml='" + ps(SOURCE_XML) + "'}", '',
                                      held_record(interrupted=False, stage='BEFORE_RUN', run_requested=False, held_before_run=True, instance_guid=None,
                                                  stop_recovery_allowed=False)),
    'apply_interrupted_live_action_differs': (True, True, "@{Arguments='" + r5_args(HELD_CONFIG) + "'}", '', no_start_receipt),
    'apply_interrupted_live_xml_names_other_attempt': (True, True, "@{Xml='" + ps(TASK_XML.replace('retarget v3', 'retarget v2')) + "'}", '', no_start_receipt),
    'apply_interrupted_retarget_config_differs': (True, True, '@{}', '', chain(no_start_receipt, retarget_edit('config_sha256', value='0' * 64))),
    'apply_interrupted_health_gate_failure_held': (True, True, "@{Enabled=$false;" + TRIGGER_OFF + ";Xml='" + ps(SOURCE_XML) + "'}", '',
                                                   held_record(interrupted=False, health_gate_passed=False, stop_recovery_allowed=False)),
    'plan_interrupted_held_running_task_disabled': (False, True, "@{Enabled=$false;" + TRIGGER_OFF + ";Xml='" + ps(SOURCE_XML) + "'}", '', held_record()),
}
INTERRUPTED_SESSION_REFUSALS = {
    'apply_held_says_trigger_disabled_live_enabled': 'trigger is enabled, which the bound r5 start evidence (START_INTERRUPTED_HELD) does not allow',
    'apply_interrupted_live_action_differs': 'differs from the r5 action recorded by the retarget receipt',
    'apply_interrupted_live_xml_names_other_attempt': 'registered (warden-task-after.xml) outside',
    'apply_interrupted_retarget_config_differs': 'r5 runtime is not the reviewed installed build',
    'apply_interrupted_health_gate_failure_held': 'does not allow a stop recovery',
    'apply_held_before_run_refused': 'held before Run',
}


@pytest.mark.parametrize('case', [c for c in INTERRUPTED_SESSION_CASES if c.startswith('apply_') and c not in INTERRUPTED_SESSION_REFUSALS])
def test_recover_interrupted_start_stops_and_records_the_binding(tmp_path, case):
    value, target, info = drive_session(tmp_path, case, INTERRUPTED_SESSION_CASES, recover=True)
    assert not value['failed'], value['message']
    result = value['value']
    receipt_path = target / 'stop-receipt.json'
    receipt, intent = read_json(receipt_path), read_json(target / 'stop-intent.json')
    attempt = Path(info['base']) / 'WardenRetarget4.2.7-windows-20261011-r5-v3'
    binding = {'apply_interrupted_held_running_task_disabled': 'START_INTERRUPTED_HELD', 'apply_crashed_no_record_stopped_trigger_off': 'START_CRASHED_NO_RECORD',
               'apply_crashed_in_the_trigger_enable_window': 'START_CRASHED_NO_RECORD', 'apply_held_after_health_gate_trigger_enabled': 'START_HELD_AFTER_HEALTH_GATE',
               'apply_held_before_health_gate_running_task_disabled': 'START_HELD_BEFORE_HEALTH_GATE'}[case]
    trigger = case in ('apply_crashed_in_the_trigger_enable_window', 'apply_held_after_health_gate_trigger_enabled')
    basis = {'apply_interrupted_held_running_task_disabled': 'TRIGGER_NOT_YET_ENABLED', 'apply_crashed_no_record_stopped_trigger_off': 'TRIGGER_NOT_YET_ENABLED',
             'apply_crashed_in_the_trigger_enable_window': 'TRIGGER_ENABLED_XML_EQUAL_OUTSIDE_FLAGS', 'apply_held_after_health_gate_trigger_enabled': 'TRIGGER_ENABLED_HELD_READBACK',
             'apply_held_before_health_gate_running_task_disabled': 'TRIGGER_NOT_YET_ENABLED'}[case]
    # The stop receipt FIXD-RETARGET's r5-start-held lineage binds: no start receipt, the attempt's retarget receipt, intent, held record and registered XML.
    assert RECEIPT_FIELDS <= set(receipt), RECEIPT_FIELDS - set(receipt)
    assert receipt['schema'] == 'cochem-warden-stop/2' and receipt['start_binding'] == binding and result['start_binding'] == binding
    assert receipt['start_receipt_path'] is None and receipt['start_receipt_sha256'] is None and receipt['source_task_xml_started_sha256'] is None
    assert receipt['retarget_receipt_sha256'] == info['retarget_sha256'] == sha((attempt / 'retarget-receipt.json').read_bytes())
    assert receipt['retarget_receipt_path'] == str(attempt / 'retarget-receipt.json') and receipt['start_intent_path'] == str(attempt / 'start-intent.json')
    assert receipt['start_intent_sha256'] == info['intent_sha256'] == sha((attempt / 'start-intent.json').read_bytes())
    assert receipt['start_held_sha256'] == info['held_sha256'] and (receipt['start_held_sha256'] is None) is (binding == 'START_CRASHED_NO_RECORD')
    assert receipt['source_task_xml_after_sha256'] == sha(SOURCE_XML.encode()) and receipt['live_xml_matches_source_outside_enabled_flags'] is True
    assert receipt['trigger_enabled_before'] is trigger and receipt['trigger_enabled_after'] is trigger and receipt['trigger_state_basis'] == basis
    assert result['trigger_enabled_after'] is trigger
    assert receipt['enabled_after'] is False and receipt['instances_after'] == 0 and receipt['port_free_after'] is True and receipt['retarget_attempt'] == 'v3'
    assert receipt['task_xml_after_sha256'] == sha((target / 'warden-task-after.xml').read_bytes()) and receipt['runtime_root'] == R5_ROOT
    assert receipt['action'] == {'execute': R5_PY, 'arguments': R5_ARGS, 'working_directory': R5_ROOT}
    assert receipt['runtime_bindings']['task_config_sha256'] == sha(STAGED_CONFIG) and receipt['runtime_bindings']['freeze_manifest_pinned'] is True
    assert intent['start_binding'] == binding and intent['retarget_receipt_sha256'] == info['retarget_sha256'] and intent['start_receipt_sha256'] is None
    assert value['code_tree_calls'] == [R5_ROOT] and not (target / 'stop-held.json').exists()
    if case == 'apply_crashed_no_record_stopped_trigger_off':
        assert receipt['status'] == 'WARDEN_ALREADY_STOPPED_CLEAN_NOOP' and value['stops'] == 0 and receipt['disabled_by_this_run'] is True and len(value['enabled_writes']) == 1, \
            'the crashed start left the task enabled: the stop disables it (the logon trigger is still disabled)'
    else:
        assert receipt['status'] == 'WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED' and value['stops'] == 1 and receipt['ended_by_this_run'] is True
        if case == 'apply_crashed_in_the_trigger_enable_window':
            assert receipt['enabled_before'] is True and receipt['disabled_by_this_run'] is True and len(value['enabled_writes']) == 1
        else:
            assert receipt['enabled_before'] is False and receipt['disabled_by_this_run'] is False and value['enabled_writes'] == [], \
                'the held start already disabled the task: its running instance is ended, the task is not written'


@pytest.mark.parametrize('case', list(INTERRUPTED_SESSION_REFUSALS))
def test_recover_interrupted_start_refuses_when_the_live_task_or_evidence_disagrees(tmp_path, case):
    value, target, _ = drive_session(tmp_path, case, INTERRUPTED_SESSION_CASES, recover=True)
    assert value['failed'] and value['message'].startswith('The Warden stop is held. Nothing was changed: ') and INTERRUPTED_SESSION_REFUSALS[case] in value['message'], value['message']
    assert value['stops'] == 0 and value['enabled_writes'] == [] and value['events'] == [] and not target.exists()


def test_recover_interrupted_start_plan_binds_a_disabled_running_task(tmp_path):
    value, target, info = drive_session(tmp_path, 'plan_interrupted_held_running_task_disabled', INTERRUPTED_SESSION_CASES, recover=True)
    assert not value['failed'], value['message']
    plan = value['value']
    assert plan['holds'] == [] and plan['stop_mode'] == 'RUNNING' and plan['start_binding'] == 'START_INTERRUPTED_HELD' and plan['recover_interrupted_start'] is True
    assert plan['trigger_enabled_allowed'] == [False] and plan['start_receipt']['start_held_sha256'] == info['held_sha256']
    assert value['stops'] == 0 and value['enabled_writes'] == [] and value['events'] == [] and not target.exists()


R4_SESSION_CASES = {
    # name: (apply, admin, task overrides, flags, receipt mutator)
    'plan_r4_running_idle': (False, True, R4_TASK + '}', '', None),
    'plan_r4_live_task_is_r5': (False, True, '@{}', '', None),
    'plan_r4_pins_differ': (False, True, R4_TASK + '}', "$script:fxR4Revision=('0'*64);", None),
    'plan_r4_receipt_is_an_r5_start': (False, True, R4_TASK + '}', '', r4_edit('status', value='WARDEN_R5_RUNNING_HEALTH_VERIFIED')),
    'apply_r4_running_success': (True, True, R4_TASK + '}', '', None),
    'apply_r4_noop_disabled_success': (True, True, R4_TASK.replace(TASK_XML_R4, TASK_XML_R4_DISABLED) + ';Enabled=$false;State=1;Instances=0}', '', None),
}


def drive_session_r4(tmp_path, case, table=None, live=None):
    apply, admin, overrides, flags, mutator = (table or R4_SESSION_CASES)[case]
    info = write_r4_receipt(tmp_path / 'fx', mutator)
    client = tmp_path / 'client.json'
    client.write_text(json.dumps({'port': 47824, 'token_file': TOKEN_FILE}), encoding='utf-8')
    target = tmp_path / 'stop-root'
    body = (FX_READ + TASK_FIXTURE + STUBS + (live_presence(live) if live is not None else '') +
            f"$script:RetargetTarget='r4';Set-StopConstants;Use-Fixture '{ps(info['base'])}' '{CONFIG_PIN}' '{BASE_PY_PIN}';$script:clientConfig='{ps(client)}';"
            f"$script:targetRoot='{ps(target)}';$script:admin={'$true' if admin else '$false'};$folder=New-FixtureFolder {overrides};{flags}" + r'''
      $failed=$false;$message='';$value=$null;try{$value=Invoke-StopWardenSession $folder APPLY}catch{$failed=$true;$message=$_.Exception.Message}
      [ordered]@{failed=$failed;message=$message;value=$value;stops=$script:stops;enabled_writes=@($script:enabledWrites);idle_evaluations=$script:idleEvaluations;
        code_tree_calls=@($script:codeTreeCalls);events=@($script:events);r4_binding_calls=$script:r4BindingCalls}|ConvertTo-Json -Depth 9 -Compress'''.replace('APPLY', '$true' if apply else '$false'))
    return run_json(body, tmp_path, timeout=300), target


@pytest.mark.parametrize('case', [c for c in R4_SESSION_CASES if c.startswith('plan_')])
def test_r4_restore_plan_binds_the_r4_runtime_and_changes_nothing(tmp_path, case):
    value, target = drive_session_r4(tmp_path, case)
    assert not value['failed'], value['message']
    plan = value['value']
    assert plan['retarget_target'] == 'r4' and plan['start_receipt_path'].endswith('WardenRetarget4.2.7-windows-20261011-r4-v3\\start-receipt.json')
    assert value['stops'] == 0 and value['enabled_writes'] == [] and value['events'] == [] and not target.exists()
    holds = plan['holds']
    if case == 'plan_r4_running_idle':
        assert holds == [] and plan['stop_mode'] == 'RUNNING' and plan['runtime_root'] == R4_ROOT and plan['runtime_verified'] is True
        assert plan['runtime_bindings']['runtime'] == 'r4' and plan['runtime_bindings']['revision_sha256'] == R4_REVISION_PIN and value['r4_binding_calls'] == 1
        assert value['code_tree_calls'] == [R4_ROOT], 'the r4 code tree is inspected before the r4 interpreter runs elevated'
        assert plan['expected_action'] == {'execute': R4_PY, 'arguments': R4_RESTORE_ARGS, 'working_directory': R4_ROOT} and plan['expected_triggers'] in ([], None)
        assert plan['idle']['controller']['source_root'] == R4_SOURCE and value['idle_evaluations'] == 1 and plan['process_proof']['launcher']['image'] == R4_PY
        assert plan['task_summary']['task_xml_sha256'] == sha(TASK_XML_R4.encode())
    elif case == 'plan_r4_live_task_is_r5':
        assert plan['stop_mode'] == 'REFUSED' and any('differs from the r4 action recorded by the start receipt' in h for h in holds)
    elif case == 'plan_r4_pins_differ':
        assert any('r4 runtime is not the reviewed installed build: The r4 installed revision is not the pinned revision' in h for h in holds)
        assert any('was not evaluated: the r4 runtime' in h for h in holds) and value['code_tree_calls'] == [] and value['idle_evaluations'] == 0
    else:
        assert plan['stop_mode'] == 'UNBOUND' and len(holds) == 1 and 'r4 start receipt: The start receipt is not a successful r4 start' in holds[0]


@pytest.mark.parametrize('case', [c for c in R4_SESSION_CASES if c.startswith('apply_')])
def test_r4_restore_apply_dispatch_stops_and_records_the_r4_target(tmp_path, case):
    value, target = drive_session_r4(tmp_path, case)
    assert not value['failed'], value['message']
    result, receipt = value['value'], read_json(target / 'stop-receipt.json')
    assert result['retarget_target'] == 'r4' and receipt['retarget_target'] == 'r4' and receipt['runtime_root'] == R4_ROOT
    assert receipt['enabled_after'] is False and receipt['instances_after'] == 0 and receipt['task_xml_after_sha256'] == sha((target / 'warden-task-after.xml').read_bytes())
    assert receipt['start_receipt_path'].endswith('WardenRetarget4.2.7-windows-20261011-r4-v3\\start-receipt.json') and receipt['runtime_bindings']['runtime'] == 'r4'
    if case == 'apply_r4_running_success':
        assert result['status'] == 'WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED' and value['stops'] == 1 and len(value['enabled_writes']) == 1
    else:
        assert result['status'] == 'WARDEN_ALREADY_STOPPED_CLEAN_NOOP' and value['stops'] == 0 and value['enabled_writes'] == [] and receipt['disabled_by_this_run'] is False


# --------------------------------------------------------------------------------------------------------------------
# Both directions with retarget-warden-r5.ps1 (its functions from its AST, inert): the start-held.json its held and
# interrupted starts write is bound here, and the stop receipt written here is accepted by its source lineage.
# --------------------------------------------------------------------------------------------------------------------

SIBLING = ROOT / 'retarget-warden-r5.ps1'
SIBLING_PRELUDE = r'''$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
foreach($m in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$m\$m.psd1")}
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('SIBLINGPATH',[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
foreach($f in @($ast.EndBlock.Statements|Where-Object {$_ -is [Management.Automation.Language.FunctionDefinitionAst]})){. ([scriptblock]::Create($f.Extent.Text))}
$script:Target='r5';$script:Attempt='v3';$script:SourceAttempt='';$script:StopAttempt='';$script:scriptDirectory='ROOTPATH';Set-RetargetConstants;$script:admin=$false
$held=[Collections.Generic.List[IO.FileStream]]::new()
function Read-R3Control {param([string]$Path,[string]$Hash='',[long]$Maximum=16777216)
  $bytes=[IO.File]::ReadAllBytes($Path);if($bytes.Length -gt $Maximum){throw 'Bounded r3 control length differs.'}
  $actual=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant();if($Hash -and $actual -cne $Hash){throw ('Source digest changed: '+$Path)}
  [pscustomobject]@{Stream=[IO.MemoryStream]::new($bytes);Sha256=$actual;Length=$bytes.Length}}
function Read-R3Text {param($Control)$Control.Stream.Position=0;$reader=[IO.StreamReader]::new($Control.Stream,[Text.Encoding]::UTF8,$true,4096,$true);try{$reader.ReadToEnd()}finally{$reader.Dispose()}}
function Write-RegistrationControl {param([string]$Path,[string]$Text)[IO.File]::WriteAllText($Path,$Text,[Text.UTF8Encoding]::new($false));(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
'''.replace('SIBLINGPATH', ps(SIBLING)).replace('ROOTPATH', ps(ROOT))


def sibling_has(*names):
    if not SIBLING.exists():
        return False
    text = SIBLING.read_text(encoding='utf-8')
    return all(f'function {name} ' in text or f'function {name}{{' in text for name in names)


INSTANCE_GUID = "'{0F5A2C3E-0000-4000-8000-000000000005}'"
HELD_WRITER_CASES = {
    # name: (stage, interrupted, health_gate_passed, live trigger Enabled read back, expected binding or refusal, Run requested)
    'interrupted_during_health_wait': ('HEALTH_WAIT', True, False, False, 'START_INTERRUPTED_HELD', True),
    'interrupted_after_trigger_enable': ('RECEIPT', True, True, True, 'START_INTERRUPTED_HELD', True),
    'held_after_health_gate': ('TRIGGER_ENABLE', False, True, False, 'START_HELD_AFTER_HEALTH_GATE', True),
    'held_health_gate_failure': ('HEALTH_WAIT', False, False, False, 'START_HELD_BEFORE_HEALTH_GATE', True),
    'held_before_run': ('BEFORE_RUN', False, False, False, 'held before Run', False),
    'interrupted_before_run': ('BEFORE_RUN', True, False, False, 'held before Run', False),
}


def test_start_held_records_written_by_retarget_warden_r5_are_bound_by_recover_interrupted_start(tmp_path):
    """C-F1(b): the start-held.json of retarget-warden-r5.ps1 Write-StartHeldRecord (its finally and its held path)."""
    if not sibling_has('Write-StartHeldRecord', 'Get-LiveTriggerEnabled', 'Write-HeldControl'):
        pytest.skip('retarget-warden-r5.ps1 does not define the two-phase start-held writer')
    lines = [SIBLING_PRELUDE, '$out=[ordered]@{}']
    for name, (stage, interrupted, gate, trigger, _, run) in HELD_WRITER_CASES.items():
        target = tmp_path / 'writer' / name
        live = TASK_XML_DISABLED if trigger else SOURCE_XML
        lines.append(
            f"$script:targetRoot='{ps(target)}';$null=[IO.Directory]::CreateDirectory($script:targetRoot);$task=[pscustomobject]@{{Enabled=$true}}\n"
            f"$trigger=[pscustomobject]@{{type=9;enabled=${str(trigger).lower()};user_id='AETHERDESK\\ansac';delay='PT1M';start_boundary='';end_boundary='';execution_time_limit='';"
            f"repetition_interval='';repetition_duration=''}}\n"
            f"function Get-WardenTaskState {{param($Folder)[pscustomobject]@{{readable=$true;enabled=$false;state=4;instances=1;last_task_result=267009;xml='{ps(live)}';"
            f"trigger_list=@($trigger);task=$task}}}}\n"
            f"$facts=[ordered]@{{stage='{stage}';run_requested=${str(run).lower()};run_exception=$null;enable_requested=$true;"
            f"instance_guid={INSTANCE_GUID if run else '$null'};"
            f"health_gate_passed=${str(gate).lower()};trigger_enable_requested=${str(trigger).lower()};last_health_pid=20664}}\n"
            f"$r=Write-StartHeldRecord $null ([ordered]@{{target='r5'}}) ([pscustomobject]@{{readable=$true;enabled=$true;task=$task}}) $facts ${str(interrupted).lower()} 'test'\n"
            f"$out['{name}']=[ordered]@{{note=$r.note;disable_error=$r.disable_error;task_enabled=$task.Enabled}}")
    lines.append('$out|ConvertTo-Json -Depth 4 -Compress')
    (tmp_path / 'sibling.ps1').write_text('\n'.join(lines), encoding='utf-8')
    command = "$ErrorActionPreference='Stop';. ([scriptblock]::Create([IO.File]::ReadAllText('" + ps(tmp_path / 'sibling.ps1') + "')))"
    run = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stderr[-4000:]
    written = json.loads(run.stdout)
    table = {}
    for name, (_, interrupted, gate, trigger, expected, run) in HELD_WRITER_CASES.items():
        assert written[name]['note'] == '' and written[name]['task_enabled'] is False, 'the writer disabled the task (never End) and recorded it'
        record = json.loads((tmp_path / 'writer' / name / 'start-held.json').read_text(encoding='utf-8'))
        assert record['interrupted'] is interrupted and record['health_gate_passed'] is gate and record['held_before_run'] is (not run)
        assert record['stop_recovery_allowed'] is ((not record['held_before_run']) or interrupted), 're-audit R-F1: every hold after Run is stop-recoverable'
        assert record['trigger_enabled_after'] is trigger and record['receipt_written'] is False and record['attempt'] == 'v3'
        table[name] = (set_ctx('held_record', record), expected)
    value = run_binding_table(tmp_path / 'bind', {name: (chain(no_start_receipt, mutate), '', None, None) for name, (mutate, _) in table.items()}, True)
    for name, (_, _, _, trigger, expected, _) in HELD_WRITER_CASES.items():
        result = value['results'][name]
        if expected.startswith('START_'):
            assert result['message'] == '' and result['start_binding'] == expected and result['allowed'] == [trigger], (name, result['message'])
            assert result['receipt']['start_held_sha256'] == value['cases'][name]['held_sha256']
        else:
            assert expected in result['message'], (name, result['message'])


LINEAGE_CASES = {
    # stop session case -> the retarget-warden-r5 source lineage that must accept its stop receipt
    'apply_interrupted_held_running_task_disabled': 'r5-start-held', 'apply_crashed_no_record_stopped_trigger_off': 'r5-start-held',
    'apply_crashed_in_the_trigger_enable_window': 'r5-start-held', 'apply_held_after_health_gate_trigger_enabled': 'r5-start-held',
    'apply_held_before_health_gate_running_task_disabled': 'r5-start-held', 'apply_running_success': 'r5-receipt',
    'apply_running_task_disabled_after_completed_start': 'r5-receipt',
}


@pytest.mark.parametrize('case', list(LINEAGE_CASES))
def test_retarget_warden_r5_source_lineage_accepts_this_stop_receipt(tmp_path, case):
    """C-F1(b)/C-F5: the next retarget (-SourceAttempt v3 -StopAttempt v1) accepts the stop receipt written here."""
    if not sibling_has('Assert-HeldStartSourceLineage', 'Assert-StartedSourceLineage', 'Assert-StopLineage'):
        pytest.skip('retarget-warden-r5.ps1 does not define the start-held and started source lineages')
    recover = LINEAGE_CASES[case] == 'r5-start-held'
    value, target, info = drive_session(tmp_path, case, INTERRUPTED_SESSION_CASES if recover else SESSION_CASES, recover=recover)
    assert not value['failed'], value['message']
    base = Path(info['base'])
    shutil.copytree(target, base / 'WardenStop4.2.7-windows-20261011-r5-v1')
    receipt = read_json(target / 'stop-receipt.json')
    live = (target / 'warden-task-after.xml').read_text(encoding='utf-8')
    function = 'Assert-HeldStartSourceLineage' if recover else 'Assert-StartedSourceLineage'
    body = SIBLING_PRELUDE + (
        f"$script:base='{ps(base)}';$script:SourceAttempt='v3';$script:StopAttempt='v1'\n"
        f"$trigger=[pscustomobject]@{{type=9;enabled=${str(receipt['trigger_enabled_after']).lower()};user_id='AETHERDESK\\ansac';delay='PT1M';start_boundary='';end_boundary='';"
        f"execution_time_limit='';repetition_interval='';repetition_duration=''}}\n"
        f"$State=[pscustomobject]@{{readable=$true;enabled=$false;state=1;instances=0;xml='{ps(live)}';triggers=1;trigger_list=@($trigger);"
        f"action_path='{R5_PY}';action_arguments='{R5_ARGS}';action_working_directory='{R5_ROOT}'}}\n"
        f"$m='';$r=$null;try{{$r={function} $State 'r5' (Join-Path $script:base 'WardenRetarget4.2.7-windows-20261011-r5-v3')}}catch{{$m=$_.Exception.Message}}\n"
        "[ordered]@{message=$m;record=$r}|ConvertTo-Json -Depth 5 -Compress")
    (tmp_path / 'lineage.ps1').write_text(body, encoding='utf-8')
    command = "$ErrorActionPreference='Stop';. ([scriptblock]::Create([IO.File]::ReadAllText('" + ps(tmp_path / 'lineage.ps1') + "')))"
    run = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stderr[-4000:]
    out = json.loads(run.stdout)
    assert out['message'] == '', out['message']
    record = out['record']
    assert record['source_state'] == LINEAGE_CASES[case] and record['stop_start_binding'] == receipt['start_binding']
    assert record['stop_receipt_sha256'] == sha((target / 'stop-receipt.json').read_bytes()) and record['source_receipt_sha256'] == info['retarget_sha256']
