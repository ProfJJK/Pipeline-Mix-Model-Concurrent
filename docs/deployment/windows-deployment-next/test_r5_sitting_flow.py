"""Fixture-driven flow tests for RUN_427_R5_SITTING.ps1 (the r5 single sitting).

Mechanism (as test_launch_series_flow.py for rev 3): the function definitions are extracted from the script's AST and
dot-sourced into a throwaway Windows PowerShell 5.1 process, followed by the script's top-level assignments. The
workspace ($script:Workspace) and the Program Files base ($script:Base) are then redirected to per-test temporary
directories, $script:Pins is replaced by the real sha256 of stub child files written into the temporary workspace, and
every launcher or host probe is replaced by a recording stub:

  Invoke-R5Native        the lowest launcher: every reviewed child (powershell.exe -File) and the S9 builder (r5 python)
  Start-Process          the attended console children (Invoke-R5Attended stays real, so its pin check runs)
  Invoke-R5Control       ControlClient calls (/health, /preflight, /workflow/<id>, /submit, /coding/...)
  Read-R5YesNo, Request-R5Attention, Wait-R5Seconds, Get-R5Now, Assert-R5OwnerShell, Get-R5WardenState,
  Get-R5DockerInfo, Test-R5PackageIndex, Get-R5FreeDiskGB, Get-R5ListenerCount, New-R5HexAttempt,
  Start-Transcript, Stop-Transcript

Everything else (pin checks, receipts, stage gates, Gemini-held degradation, restore and fallback selection, the series
driver) is the real code. Each stub child emits the documented stdout of the reviewed child and writes its documented
files under the redirected base. The retarget-warden-r5 and stop-warden-r5 stubs mirror the acceptance rules of the real
scripts (INTERFACES-CUTOVER final: source states, the live task action, start bindings, the stop's idle proof), so a call the
real script would refuse is refused here too and recorded. Stubs append one JSON line per event to a trace file, so a
sitting that ends with `exit` (as Invoke-R5Series does) is still observable. Nothing is started, stopped, registered or
written outside the per-test temporary directories, and no network is used.
"""
import base64
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
SCRIPT = Path(os.environ.get('R5_SITTING_SCRIPT', str(ROOT / 'RUN_427_R5_SITTING.ps1')))

CHILDREN = [
    'install-stopped-runtime-r5.ps1', 'stop-warden-r4.ps1', 'check-worker-native-auth-status-six-r4-v1.ps1',
    'login-six-workers-status-first-r4-v1.ps1', 'agy-status-capture-r4-v1.ps1', 'agy-isolation-evidence-r4-v1.ps1',
    'build-pipeline-config-r5-candidate.py', 'stage-pipeline-config-r5-v1.ps1', 'run-upgrade-preview-r5-v1.ps1',
    'retarget-warden-r5.ps1', 'stop-warden-r5.ps1',
]
INSTALL, STOP_R4, LEAF, LOGIN, CAPTURE, ISOLATION = CHILDREN[:6]
BUILDER, STAGER, PREVIEW, RETARGET, STOP_R5 = CHILDREN[6:]
REPAIRS = [f'src/cochem_pipeline/repair_{index:02d}.py' for index in range(1, 14)]
COMMISSIONED_BYTES = b'{\r\n  "commissioned": "stub of the 135cd9ec pipeline.json",\r\n  "providers": {"gemini": {"integration_hold": {}}}\r\n}\r\n'
CONTRACT_BYTES = b'{\r\n  "commissioned": "stub of the 135cd9ec pipeline.json",\r\n  "providers": {"gemini": {"protocol": "agy-stream-json"}}\r\n}\r\n'
COMMISSIONED_SHA = hashlib.sha256(COMMISSIONED_BYTES).hexdigest()
TOKEN_FILE = 'C:\\Users\\ansac\\CoChem427\\controller.token'  # the controller token path the cutover scripts' Assert-ClientConfig pins
CONTRACT_SHA = hashlib.sha256(CONTRACT_BYTES).hexdigest()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ps_quote(value) -> str:
    return str(value).replace("'", "''")


# ---------------------------------------------------------------------------------------------------------------------
# PowerShell harness (placeholders __NAME__ are filled by run_sitting)

HARNESS = r'''
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
foreach($hxModule in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security','Microsoft.PowerShell.Management')){Import-Module (Join-Path $PSHOME "Modules\$hxModule\$hxModule.psd1")}
$script:HXTrace='__TRACE__';$script:HXSeq=0;$script:HXStage='';$script:HXStack=[Collections.Generic.List[string]]::new()
$script:HXClock=[DateTime]::new(2026,10,11,20,0,0,[DateTimeKind]::Local);$script:HXHex=__HEX_SEED__
function HX-Trace {param([string]$Kind,[hashtable]$Data=@{})
    $entry=[ordered]@{kind=$Kind;seq=$script:HXSeq;stage=$script:HXStage};$script:HXSeq++
    foreach($key in @($Data.Keys)){$entry[$key]=$Data[$key]}
    [IO.File]::AppendAllText($script:HXTrace,(($entry|ConvertTo-Json -Compress -Depth 12)+"`n"),[Text.UTF8Encoding]::new($false))}
function HX-Result {param($Code,[string]$Text)[pscustomobject]@{code=$Code;text=$Text}}
function HX-Arg {param([object[]]$Argv,[string]$Name)$list=@($Argv|ForEach-Object {[string]$_});for($i=0;$i -lt $list.Count-1;$i++){if($list[$i] -ceq $Name){return $list[$i+1]}};$null}
function HX-Has {param([object[]]$Argv,[string]$Name)(@($Argv|ForEach-Object {[string]$_}) -ccontains $Name)}
function HX-Write {param([string]$Path,[string]$Text)$dir=[IO.Path]::GetDirectoryName($Path);if(-not [IO.Directory]::Exists($dir)){$null=[IO.Directory]::CreateDirectory($dir)};[IO.File]::WriteAllText($Path,$Text,[Text.Encoding]::ASCII)}
function HX-WriteBytes {param([string]$Path,[byte[]]$Bytes)$dir=[IO.Path]::GetDirectoryName($Path);if(-not [IO.Directory]::Exists($dir)){$null=[IO.Directory]::CreateDirectory($dir)};[IO.File]::WriteAllBytes($Path,$Bytes)}
function HX-WriteJson {param([string]$Path,$Value)HX-Write $Path ($Value|ConvertTo-Json -Depth 12)}
function HX-Json {param($Value)$Value|ConvertTo-Json -Compress -Depth 12}
function HX-Obj {param($Value)(HX-Json $Value)|ConvertFrom-Json}
function HX-Sha {param([string]$Path)$h=[Security.Cryptography.SHA256]::Create();try{-join ($h.ComputeHash([IO.File]::ReadAllBytes($Path))|ForEach-Object {$_.ToString('x2')})}finally{$h.Dispose()}}
function HX-Next {param([string]$Key,$Default)
    # Pops the next scripted value of a queue in $script:HX; the last value is sticky.
    if(-not $script:HX.ContainsKey($Key)){return $Default}
    $queue=$script:HX[$Key]
    if($queue -is [Collections.IList]){if($queue.Count -eq 0){return $Default};$value=$queue[0];if($queue.Count -gt 1){$queue.RemoveAt(0)};return $value}
    $queue}

# ---- the sitting's functions and top-level assignments (the guarded entry is never executed) ----
$hxTokens=$null;$hxErrors=$null;$hxAst=[Management.Automation.Language.Parser]::ParseFile('__SCRIPT__',[ref]$hxTokens,[ref]$hxErrors)
if($hxErrors.Count){throw ($hxErrors|Out-String)}
foreach($hxStatement in $hxAst.EndBlock.Statements){if($hxStatement -is [Management.Automation.Language.FunctionDefinitionAst]){. ([scriptblock]::Create($hxStatement.Extent.Text))}}
# The real ControlClient wrapper, kept for the focused client-config tests (Invoke-R5Python / Invoke-R5Native stay stubbed).
$script:HXOrigControl=(Get-Item -LiteralPath 'function:Invoke-R5Control').ScriptBlock
$Attempt='__ATTEMPT__';$Gemini='__GEMINI__';$EffortNullSlug='__SLUG__';$Apply=[Management.Automation.SwitchParameter]::new(__APPLY__);$SkipFixProof=[Management.Automation.SwitchParameter]::new(__SKIP__)
$script:Attempt=$Attempt;$script:Gemini=$Gemini;$script:EffortNullSlug=$EffortNullSlug;$script:Apply=$Apply;$script:SkipFixProof=$SkipFixProof
foreach($hxStatement in $hxAst.EndBlock.Statements){if($hxStatement -is [Management.Automation.Language.AssignmentStatementAst]){. ([scriptblock]::Create($hxStatement.Extent.Text))}}
$script:Workspace='__WS__';$script:Base='__BASE__'
$script:Pins=@{__PINS__}
$script:HXCommissionedSha='__COMMISSIONED_SHA__';$script:HXBuilderSha='__BUILDER_SHA__'
$script:HXRepairs=@(__REPAIRS__);$script:HXRepairPins=@{__REPAIR_PINS__}
$script:HXContractBytes=[Convert]::FromBase64String('__CONTRACT_B64__')
$script:HXClientConfig='__CLIENT_CONFIG__';$script:HXPyvenvSha='__PYVENV_SHA__';$script:HXVenvPythonSha='__VENV_PYTHON_SHA__'

# ---- scenario defaults: today's host (Warden r4-v1 enabled but idle, 0 instances) and every gate passing ----
$script:HX=@{
    warden=[ordered]@{readable=$true;enabled=$true;instances=0;task_state=3;source='r4-v1';source_attempt=$null;listening=0;error=$null;action=$null}
    docker=[Collections.ArrayList]@($true);pypi=$true;disk=250.0
    install_plan_code=0;install_plan_holds=@();install_apply_code=0;install_mode='FRESH_STOPPED_RUNTIME_READY'
    install_after=@{verified_unchanged=153;tasks_changed=0;holds=@();r5_repairs_installed=$true;repairs=13;pin_tamper=$false;installed_repairs_verified=$true;pyvenv_tamper=$false;venv_python_tamper=$false}
    throw_in=''
    stop_r4='ok';sess=@{};answers=[Collections.ArrayList]@($true);login_exit=@{claude=0;codex=0;gemini=0};login_complete=@{claude=$true;codex=$true;gemini=$true}
    s5_code=0;s5_passed=$true;s5_mode='print';s5_decision='COMPLETE';s7_code=0;s7_passed=$true;s7_decision='COMPLETE';s8_evidence=0;s8_stage=0
    builder_queue=[Collections.ArrayList]@();stager_plan='PLAN_OK';stager_apply='STAGED';stager_code=0;stager_sha_tamper=$false;stager_outcome_override=$null
    preview_plan_code=0;preview_apply_code=0;preview_decision='PASSED';preview_install_after_tamper=$false;start_tamper=[Collections.ArrayList]@('')
    retarget_r5=[Collections.ArrayList]@('ok');retarget_r4=[Collections.ArrayList]@('ok');stop_r5=[Collections.ArrayList]@('ok');retarget_mode_override=$null
    health_overrides=@{};admission=[Collections.ArrayList]@(3);preflight=[Collections.ArrayList]@('ok');s14_planning='ok';s14_coding='ok'
    active_mode='';crash_in=''
}
$script:HXWorkflows=@{}

# ---- stubs: host probes ----
function Assert-R5OwnerShell {HX-Trace 'owner-check'}
function Get-R5WardenState {$w=$script:HX.warden;$a=$w.action
    HX-Trace 'warden-state' @{source=$w.source;instances=$w.instances;enabled=$w.enabled;listening=$w.listening}
    # The live Actions.Item(1) fields with the names retarget-warden-r5.ps1 Get-WardenTaskState uses (F1).
    [pscustomobject]@{readable=$w.readable;enabled=$w.enabled;instances=$w.instances;task_state=$w.task_state;source=$w.source;source_attempt=$w.source_attempt;
        listening=$w.listening;running=(([int]$w.instances -gt 0) -or ([int]$w.listening -gt 0));error=$w.error;
        action_path=$(if($null -ne $a){$a.execute}else{$null});action_arguments=$(if($null -ne $a){$a.arguments}else{$null});action_working_directory=$(if($null -ne $a){$a.working_directory}else{$null})}}
function HX-ActionFor {param([string]$Kind,[string]$Attempt,[string]$Config)
    # The task action each reviewed source state carries (retarget-warden-r5.ps1 Get-ExpectedArguments / Get-R5Arguments).
    $r4Python=Join-Path $script:R4Root '.venv\Scripts\python.exe'
    switch -CaseSensitive ($Kind){
        'r4-v1'{[ordered]@{execute=$r4Python;arguments=('-I -B -m cochem_pipeline daemon --config "'+$script:CommissioningConfig+'" --queue-launch-output "C:\ProgramData\CoChemPipeline427\private\queue-retarget-20261010-r4-v1"');working_directory=$script:R4Root}}
        'r5'{[ordered]@{execute=$script:R5Python;arguments=('-I -B -m cochem_pipeline daemon --config "'+$Config+'" --queue-launch-output-root "C:\ProgramData\CoChemPipeline427\private\queue-launch-r5" --docker-wait-seconds 900');working_directory=$script:R5Root}}
        'r4'{[ordered]@{execute=$r4Python;arguments=('-I -B -m cochem_pipeline daemon --config "'+$script:CommissionedR4Config+'" --queue-launch-output "C:\ProgramData\CoChemPipeline427\private\queue-restart-20261011-r4-'+$Attempt+'"');working_directory=$script:R4Root}}
        default{[ordered]@{execute='C:\Windows\System32\notepad.exe';arguments='unreviewed';working_directory='C:\'}}}}
function HX-SameAction {param($A,$B)($null -ne $A -and $null -ne $B -and [string]$A.execute -ceq [string]$B.execute -and [string]$A.arguments -ceq [string]$B.arguments -and [string]$A.working_directory -ceq [string]$B.working_directory)}
function HX-CanWrite {param([string]$Path)try{$s=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite);$s.Dispose();$true}catch{$false}}
function HX-LockProbe {param([string]$Where)
    # F6: a pinned child file stays behind a deny-write handle only while its child runs; record any handle left open.
    $locked=@(foreach($name in @($script:Pins.Keys)){$p=Join-Path $script:Workspace $name;if([IO.File]::Exists($p) -and -not (HX-CanWrite $p)){$name}})
    HX-Trace 'locks' @{where=$Where;locked=@($locked)}}
function Get-R5DockerInfo {$ok=[bool](HX-Next 'docker' $true);HX-Trace 'docker' @{ok=$ok}
    [pscustomobject]@{ok=$ok;reason=$(if($ok){'Docker engine and execution image: ok'}else{'Docker Desktop engine is not answering (docker info exit 1). Start Docker Desktop.'})}}
function Test-R5PackageIndex {HX-Trace 'pypi';[bool]$script:HX.pypi}
function Get-R5FreeDiskGB {param([string]$Path)HX-Trace 'disk' @{path=$Path};[double]$script:HX.disk}
function Get-R5ListenerCount {param([int]$Port)$n=$(if($Port -eq 47824){[int]$script:HX.warden.listening}else{0});HX-Trace 'listeners' @{port=$Port;count=$n};$n}
function Read-R5YesNo {param([string]$Question)$answer=$false;if($script:HX.answers.Count){$answer=[bool]$script:HX.answers[0];$script:HX.answers.RemoveAt(0)};HX-Trace 'prompt' @{question=$Question;answer=$answer};$answer}
function Request-R5Attention {param([string]$Text)HX-Trace 'attention' @{text=[string]$Text}}
function Wait-R5Seconds {param([int]$Seconds)HX-Trace 'wait' @{seconds=$Seconds};$script:HXClock=$script:HXClock.AddSeconds($Seconds)}
function Get-R5Now {$script:HXClock}
function New-R5HexAttempt {$script:HXHex++;$value=('c0ffee'+$script:HXHex.ToString('x').PadLeft(26,'0'));HX-Trace 'hex' @{value=$value};$value}
function Start-Transcript {param($Path,[switch]$Force,[switch]$Append)HX-Trace 'transcript' @{path=[string]$Path}}
function Stop-Transcript {}
function Read-Host {param($Prompt)HX-Trace 'unexpected' @{child='Read-Host'};throw 'harness: Read-Host must not be reached (Read-R5YesNo is stubbed)'}
function Start-Sleep {param($Seconds,$Milliseconds)HX-Trace 'unexpected' @{child='Start-Sleep'};throw 'harness: Start-Sleep must not be reached (Wait-R5Seconds is stubbed)'}
function Invoke-WebRequest {HX-Trace 'unexpected' @{child='Invoke-WebRequest'};throw 'harness: no network'}

# ---- stubs: launchers ----
function Invoke-R5Native {param([string]$Executable,[string[]]$Arguments)HX-Dispatch $Executable $Arguments 'native'}
function Start-Process {param([string]$FilePath,[object]$ArgumentList,[switch]$NoNewWindow,[switch]$Wait,[switch]$PassThru,[string]$WorkingDirectory,[string]$WindowStyle)
    $list=@()
    if($ArgumentList -is [Array]){$list=@($ArgumentList|ForEach-Object {([string]$_).Trim('"')})}
    else{$list=@([regex]::Matches([string]$ArgumentList,'"[^"]*"|\S+')|ForEach-Object {$_.Value.Trim('"')})}
    HX-Trace 'start-process' @{file=$FilePath;no_new_window=[bool]$NoNewWindow;passthru=[bool]$PassThru}
    $result=HX-Dispatch $FilePath $list 'attended'
    $process=[pscustomobject]@{ExitCode=$result.code;Id=4242;HasExited=$true;Handle=[IntPtr]::new(1)}
    $process|Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {}
    $process}
function HX-Dispatch {param([string]$Executable,[object[]]$Arguments,[string]$How)
    $argv=[string[]]@($Arguments|ForEach-Object {[string]$_})
    $rest=@();$scriptPath=$null;$pre=@()
    $fileIndex=[Array]::IndexOf($argv,'-File')
    if($fileIndex -ge 0 -and $fileIndex+1 -lt $argv.Count){$scriptPath=$argv[$fileIndex+1];$pre=@($argv|Select-Object -First $fileIndex);$rest=@($argv|Select-Object -Skip ($fileIndex+2))}
    else{$py=@($argv|Where-Object {$_ -like '*.py'});if($py.Count){$scriptPath=$py[0];$index=[Array]::IndexOf($argv,$py[0]);$pre=@($argv|Select-Object -First $index);$rest=@($argv|Select-Object -Skip ($index+1))}else{$rest=@($argv)}}
    $leaf=$(if($scriptPath){[IO.Path]::GetFileName($scriptPath)}else{[IO.Path]::GetFileName($Executable)})
    # F6: while a pinned W file runs, the sitting holds it behind a deny-write/delete handle.
    $writeDenied=$null;if($scriptPath -and [IO.File]::Exists($scriptPath)){$writeDenied=-not (HX-CanWrite $scriptPath)}
    HX-Trace 'run' @{child=$leaf;args=@($rest);pre=@($pre);how=$How;exe=$Executable;script=$scriptPath;write_denied=$writeDenied}
    if($script:HX.crash_in -and $script:HX.crash_in -ceq ($leaf+':'+[string](HX-Arg $rest '-Provider'))){HX-Trace 'crash' @{child=$leaf};[Environment]::Exit(9)}
    if($script:HX.throw_in -and $script:HX.throw_in -ceq $leaf){HX-Trace 'launch-throw' @{child=$leaf};throw ('harness: the launch of '+$leaf+' threw')}
    if(-not $script:HXHandlers.ContainsKey($leaf)){HX-Trace 'unexpected' @{child=$leaf};return (HX-Result 97 ('harness: no handler for '+$leaf))}
    $result=& $script:HXHandlers[$leaf] @($rest) $Executable $scriptPath @($pre)
    HX-Trace 'result' @{child=$leaf;code=$result.code}
    $result}

# ---- child handlers: the documented exit codes, last-line JSON and files of each reviewed child ----
function HX-InstallAfter {
    $ia=$script:HX.install_after;$paths=@($script:HXRepairs|Select-Object -First $ia.repairs);$map=[ordered]@{}
    foreach($p in $paths){$map[$p]=$(if($ia.pin_tamper){'f'*64}else{$script:HXRepairPins[$p]})}
    # runtime_bindings as install-stopped-runtime-r5.ps1 writes them; the harness points the sitting's venv pins at these stub files.
    HX-Write (Join-Path $script:R5Root '.venv\Scripts\python.exe') 'stub r5 python'
    HX-Write (Join-Path $script:R5Root '.venv\pyvenv.cfg') 'stub pyvenv.cfg'
    $after=[ordered]@{schema='cochem-stopped-runtime-update/1';mode=$script:HX.install_mode;source_manifest_sha256=$script:Pins['stopped-runtime-r5-source-manifest.json'];
        reviewed_repairs=[string[]]$paths;reviewed_repairs_sha256=$map;verified_unchanged=$ia.verified_unchanged;tasks_changed=$ia.tasks_changed;holds=@($ia.holds);
        installed_repairs_verified=$ia.installed_repairs_verified;
        runtime_bindings=[ordered]@{pyvenv_sha256=$(if($ia.pyvenv_tamper){'d'*64}else{HX-Sha (Join-Path $script:R5Root '.venv\pyvenv.cfg')});
            venv_python_sha256=$(if($ia.venv_python_tamper){'e'*64}else{HX-Sha (Join-Path $script:R5Root '.venv\Scripts\python.exe')})};
        verification=[ordered]@{r5_repairs_installed=$ia.r5_repairs_installed;configuration_parsed=$true;telemetry_repair_installed=$true}}
    HX-WriteJson (Join-Path $script:R5Root 'install-after.json') $after}
$script:HXHandlers=@{}
$script:HXHandlers['install-stopped-runtime-r5.ps1']={param($A,$Exe,$Path,$Pre)
    if(-not (HX-Has $A '-Apply')){return (HX-Result $script:HX.install_plan_code ("plan`n"+(HX-Json ([ordered]@{schema='cochem-stopped-runtime-update-plan/1';mode='READ_ONLY_PLAN';holds=@($script:HX.install_plan_holds)}))))}
    if($script:HX.install_apply_code -ne 0){HX-WriteJson (Join-Path $script:R5Root 'install-held.json') ([ordered]@{failed_stage='SYNC';reason='uv sync failed'});return (HX-Result $script:HX.install_apply_code 'The r5 install is held (failed_stage SYNC).')}
    HX-InstallAfter
    HX-Result 0 ("installing...`n"+(HX-Json ([ordered]@{schema='cochem-stopped-runtime-update-result/1';mode=$script:HX.install_mode;install_after=(Join-Path $script:R5Root 'install-after.json')})))}
$script:HXHandlers['stop-warden-r4.ps1']={param($A,$Exe,$Path,$Pre)
    $attempt=HX-Arg $A '-Attempt';$root=Join-Path $script:Base ('WardenStop4.2.7-windows-20261010-r4-'+$attempt)
    if($script:HX.stop_r4 -ceq 'refused'){return (HX-Result 1 'The Warden stop is refused: the controller is not idle (an IN_PROGRESS row). Nothing was changed.')}
    $null=[IO.Directory]::CreateDirectory($root)
    if($script:HX.stop_r4 -ceq 'held'){HX-WriteJson (Join-Path $root 'stop-held.json') @{reason='a controller-like process survived End'};$script:HX.warden.instances=0;$script:HX.warden.listening=0;return (HX-Result 1 'The Warden stop is held after End: a controller-like process survived; the task is NOT disabled and nothing was killed.')}
    $status=$(if($script:HX.warden.instances -gt 0){'WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED'}else{'WARDEN_ALREADY_STOPPED_AND_DISABLED'})
    HX-WriteJson (Join-Path $root 'stop-receipt.json') ([ordered]@{schema='cochem-warden-stop/1';status=$status})
    $script:HX.warden.enabled=$false;$script:HX.warden.instances=0;$script:HX.warden.listening=0;$script:HX.warden.task_state=1
    HX-Result 0 (HX-Json ([ordered]@{schema='cochem-warden-stop-result/1';status=$status;receipt_path=(Join-Path $root 'stop-receipt.json');receipt_sha256=(HX-Sha (Join-Path $root 'stop-receipt.json'))}))}
$script:HXHandlers['check-worker-native-auth-status-six-r4-v1.ps1']={param($A,$Exe,$Path,$Pre)
    $slot=HX-Arg $A '-Slot';$provider=HX-Arg $A '-Provider';$stage=HX-Arg $A '-Stage';$key=($provider+':'+$slot)
    $decision=$(if($script:HX.sess.ContainsKey($key)){$script:HX.sess[$key]}else{'REUSE_VERIFIED_SESSION'})
    $root=Join-Path $script:Base ('NativeAuthStatusSix4.2.7-windows-20261010-r4-v1-'+(HX-Arg $A '-Attempt')+'-'+$slot+'-'+$provider+'-'+$stage);$null=[IO.Directory]::CreateDirectory($root)
    if($decision -ceq 'HOLD'){HX-WriteJson (Join-Path $root 'status-held.json') ([ordered]@{schema='cochem-worker-native-auth-status-held/1';slot=$slot;provider=$provider;decision='HOLD'})
        return (HX-Result 1 'Status check is held: the receipt establishes neither a verified session nor an explicit logout.')}
    HX-WriteJson (Join-Path $root 'status-task-result.json') ([ordered]@{decision=$decision})
    HX-Result 0 (HX-Json ([ordered]@{schema='cochem-worker-native-auth-status-task-result/1';attempt=(HX-Arg $A '-Attempt');slot=$slot;provider=$provider;stage=$stage;decision=$decision;
        status=$(if($decision -ceq 'REUSE_VERIFIED_SESSION'){'NATIVE_SUBSCRIPTION_AUTHENTICATION_VERIFIED'}else{'AUTHENTICATION_NOT_VERIFIED'});pipeline_started=$false}))}
$script:HXHandlers['login-six-workers-status-first-r4-v1.ps1']={param($A,$Exe,$Path,$Pre)
    $provider=HX-Arg $A '-Provider';$attempt=HX-Arg $A '-Attempt';$code=$script:HX.login_exit[$provider]
    $root=Join-Path $script:Base ('NativeAuthSix4.2.7-windows-20261011-r4-v1-'+$attempt+'-'+$provider)
    if($code -eq 0 -and $script:HX.login_complete[$provider]){
        HX-WriteJson (Join-Path $root 'series-complete.json') ([ordered]@{schema='cochem-six-worker-status-first-result/1';status='SIX_CONFIGURED_WORKERS_SUBSCRIPTION_AUTHENTICATION_VERIFIED';provider=$provider;attempt=$attempt;all_slots_reuse_verified=$true;selected_workers_verified=6})}
    elseif($code -eq 20){HX-WriteJson (Join-Path $root 'series-paused.json') ([ordered]@{status='PAUSED';reason='rate limit'})}
    elseif($code -ne 0){HX-WriteJson (Join-Path $root 'series-held.json') ([ordered]@{status='HELD';reason='login command failed'})}
    HX-Result $code ''}
$script:HXHandlers['agy-status-capture-r4-v1.ps1']={param($A,$Exe,$Path,$Pre)
    $stage=HX-Arg $A '-Stage';$attempt=HX-Arg $A '-Attempt';$root=Join-Path $script:Base ('AgyCapture4.2.7-windows-20261010-r4-v1-'+$attempt+'-slot1-'+$stage)
    $null=[IO.Directory]::CreateDirectory($root)
    if($stage -ceq 'signed-out'){$code=$script:HX.s5_code;$passed=$script:HX.s5_passed;$decision=$script:HX.s5_decision;$mode=[ordered]@{mode=$script:HX.s5_mode;decided_by='P3';sha256=('a'*64)}
        HX-WriteJson (Join-Path $root 'login-mode.json') ([ordered]@{schema='cochem-agy-login-mode/1';mode=$script:HX.s5_mode})}
    else{$code=$script:HX.s7_code;$passed=$script:HX.s7_passed;$decision=$script:HX.s7_decision;$mode=$null}
    $summary=[ordered]@{schema='cochem-agy-status-capture-result/1';status='CAPTURED';decision=$decision;attempt=$attempt;slot='slot1';stage=$stage;target_root=$root;
        gate=[ordered]@{passed=$passed;reasons=@()};series_stop=(-not $passed);login_mode=$mode;message='stub'}
    HX-WriteJson (Join-Path $root 'capture-summary.json') $summary
    if($code -ne 0){HX-WriteJson (Join-Path $root 'capture-held.json') ([ordered]@{schema='cochem-agy-status-capture-held/1';stage=$stage;reason='stub capture failure'})}
    HX-Result $code (HX-Json $summary)}
$script:HXHandlers['agy-isolation-evidence-r4-v1.ps1']={param($A,$Exe,$Path,$Pre)
    $attempt=HX-Arg $A '-Attempt';$stageOnly=HX-Has $A '-StageOnly'
    $root=Join-Path $script:Base ('AgyIsolation4.2.7-windows-20261011-r4-v1-'+$attempt+$(if($stageOnly){'-stage'}else{''}))
    $null=[IO.Directory]::CreateDirectory($root)
    $code=$(if($stageOnly){$script:HX.s8_stage}else{$script:HX.s8_evidence})
    if($code -eq 0){if($stageOnly){HX-WriteJson (Join-Path $root 'stage-receipt.json') @{status='STAGED'};HX-WriteJson (Join-Path $root 'stage-summary.json') @{slots=6}}
                    else{HX-WriteJson (Join-Path $root 'isolation-receipt.json') @{status='PASSED'};HX-WriteJson (Join-Path $root 'isolation-summary.json') @{capability_reference='x#y'}}}
    else{HX-WriteJson (Join-Path $root $(if($stageOnly){'stage-held.json'}else{'isolation-held.json'})) @{status=$(if($code -eq 10){'GEMINI_HELD'}else{'HELD_BY_ERROR'})}}
    HX-Result $code (HX-Json ([ordered]@{schema='cochem-agy-isolation-result/1';status=$(if($code -eq 0){'PASSED'}else{'HELD'});target_root=$root;exit_code=$code;stage_only=$stageOnly}))}
$script:HXHandlers['build-pipeline-config-r5-candidate.py']={param($A,$Exe,$Path,$Pre)
    $mode=HX-Arg $A '--mode';$out=HX-Arg $A '--out-dir';$commissionedPath=HX-Arg $A '--commissioned'
    $spec=@{exit=0;outcome='auto';tamper=''};$next=HX-Next 'builder_queue' $null;if($null -ne $next){foreach($k in @($next.Keys)){$spec[$k]=$next[$k]}}
    if($spec.exit -ne 0){return (HX-Result $spec.exit (HX-Json ([ordered]@{schema='cochem-r5-config-decision-result/1';status='REFUSED';exit_code=$spec.exit;reason='stub refusal'})))}
    if([IO.Directory]::Exists($out) -and @([IO.Directory]::GetFileSystemEntries($out)).Count){return (HX-Result 4 'out-dir not empty')}
    $null=[IO.Directory]::CreateDirectory($out)
    $commissioned=[IO.File]::ReadAllBytes($commissionedPath)
    $outcome=$spec.outcome;if($outcome -ceq 'auto'){$outcome=$(if($mode -ceq 'attempt'){'GEMINI_CONTRACT'}else{'GEMINI_HELD_COMMISSIONED_BYTES'})}
    $bytes=$(if($outcome -ceq 'GEMINI_CONTRACT' -or $spec.tamper -ceq 'held-with-contract-bytes'){$script:HXContractBytes}else{$commissioned})
    HX-WriteBytes (Join-Path $out 'pipeline.json') $bytes
    $candidateSha=HX-Sha (Join-Path $out 'pipeline.json')
    $gatePass=($outcome -ceq 'GEMINI_CONTRACT');$gates=[ordered]@{}
    foreach($g in 'G1','G2','G3','G4','G5','G6'){$gates[$g]=[ordered]@{pass=$gatePass;reason=$(if($gatePass){'passed'}elseif($mode -ceq 'held'){'not evaluated: held mode requested'}else{'stub gate failure'})}}
    $decision=[ordered]@{schema='cochem-r5-config-decision/1';mode=$mode;outcome=$outcome;gates=$gates;
        chosen_bindings=$(if($gatePass){[ordered]@{'gemini-3.8-flash'='gemini-3.8-flash-low'}}else{$null});error=$null;
        candidate_file='pipeline.json';candidate_sha256=$candidateSha;candidate_length=$bytes.Length;commissioned_path=$commissionedPath;
        commissioned_sha256=$script:HXCommissionedSha;commissioned_length=$commissioned.Length;commissioned_pin=$script:HXCommissionedSha;
        inputs=[ordered]@{login_root=(HX-Arg $A '--login-root');capture_root=(HX-Arg $A '--capture-root');isolation_root=(HX-Arg $A '--isolation-root');stage_root=(HX-Arg $A '--stage-root');evidence_read=($mode -ceq 'attempt')};
        builder=[ordered]@{name='build-pipeline-config-r5-candidate.py';script_sha256=$script:HXBuilderSha;python=$Exe;python_version='3.12.13';isolated_mode=(@($Pre) -ccontains '-I')}}
    switch($spec.tamper){
        'schema'{$decision.schema='cochem-r5-config-decision/0'}
        'sha'{$decision.candidate_sha256=('0'*64)}
        'length'{$decision.candidate_length=$bytes.Length+1}
        'python'{$decision.builder.python='C:\Python314\python.exe'}
        'isolated'{$decision.builder.isolated_mode=$false}
        'script-sha'{$decision.builder.script_sha256=('1'*64)}
        'commissioned-pin'{$decision.commissioned_sha256=('5'*64);$decision.commissioned_pin=('5'*64)}
        'gate'{$decision.gates.G5=[ordered]@{pass=$false;reason='replay mismatch'}}
        'error'{$decision.error='InvariantError: stub'}
        'no-bindings'{$decision.chosen_bindings=$null}
        'mode'{$decision.mode='held'}
        'unknown-outcome'{$decision.outcome='GEMINI_MAYBE'}
    }
    HX-WriteJson (Join-Path $out 'decision.json') $decision
    HX-Result 0 (HX-Json ([ordered]@{schema='cochem-r5-config-decision-result/1';status='DECISION_WRITTEN';exit_code=0;mode=$mode;outcome=$decision.outcome;candidate_sha256=$candidateSha;decision_sha256=(HX-Sha (Join-Path $out 'decision.json'));out_dir=$out}))}
$script:HXHandlers['stage-pipeline-config-r5-v1.ps1']={param($A,$Exe,$Path,$Pre)
    $dir=HX-Arg $A '-BuildDirectory';$attempt=HX-Arg $A '-Attempt';if(-not $attempt){$attempt='v1'}
    $decision=[IO.File]::ReadAllText((Join-Path $dir 'decision.json'))|ConvertFrom-Json
    $target=Join-Path $script:Base ('WardenConfig4.2.7-windows-20261011-r5-'+$attempt);$staged=Join-Path $target 'pipeline.json'
    if(-not (HX-Has $A '-Apply')){
        $status=[string](HX-Next 'stager_plan' 'PLAN_OK')
        return (HX-Result $(if($status -ceq 'PLAN_OK'){0}else{1}) ("plan line 1`nplan line 2`n"+(HX-Json ([ordered]@{status=$status;staged_path=$staged;staged_sha256=$decision.candidate_sha256;outcome=$decision.outcome;mode=$decision.mode;receipt_path=$null;target_state='ABSENT';exit_code=$(if($status -ceq 'PLAN_OK'){0}else{1});reason=$(if($status -ceq 'PLAN_OK'){$null}else{'stub plan refusal'})}))))}
    if([IO.Directory]::Exists($target) -and @([IO.Directory]::GetFiles($target,'staging-held-*.json')).Count){return (HX-Result 1 ("held`n"+(HX-Json ([ordered]@{status='REFUSED';staged_path=$staged;staged_sha256=$null;outcome=$decision.outcome;mode=$decision.mode;receipt_path=$null;target_state='HELD';exit_code=1;reason='a held staging record blocks this -Attempt'}))))}
    $stagerCode=[int](HX-Next 'stager_code' 0)
    if($stagerCode -ne 0){$null=[IO.Directory]::CreateDirectory($target);HX-WriteJson (Join-Path $target 'staging-held-20261011T200000Z-0001.json') @{reason='stub'}
        return (HX-Result $stagerCode ("held`n"+(HX-Json ([ordered]@{status='HELD';staged_path=$staged;staged_sha256=$null;outcome=$decision.outcome;mode=$decision.mode;receipt_path=$null;target_state='HELD';exit_code=$stagerCode;reason='stub staging failure'}))))}
    HX-WriteBytes $staged ([IO.File]::ReadAllBytes((Join-Path $dir 'pipeline.json')))
    $receipt=Join-Path $target 'staging-receipt-20261011T200000Z-0001.json';HX-WriteJson $receipt ([ordered]@{schema='cochem-config-only-staging/2'})
    $stagedSha=HX-Sha $staged;if($script:HX.stager_sha_tamper){$stagedSha=('2'*64)}
    $outcome=$decision.outcome;if($script:HX.stager_outcome_override){$outcome=$script:HX.stager_outcome_override}
    HX-Result 0 ("staged line 1`n"+(HX-Json ([ordered]@{status=$script:HX.stager_apply;staged_path=$staged;staged_sha256=$stagedSha;outcome=$outcome;mode=$decision.mode;receipt_path=$receipt;target_state='CREATED';exit_code=0;reason=$null})))}
$script:HXHandlers['run-upgrade-preview-r5-v1.ps1']={param($A,$Exe,$Path,$Pre)
    $attempt=HX-Arg $A '-Attempt';$root=Join-Path $script:Base ('UpgradePreview4.2.7-windows-20261011-r5-v1-'+$attempt)
    if(-not (HX-Has $A '-Apply')){return (HX-Result ([int](HX-Next 'preview_plan_code' 0)) (HX-Json ([ordered]@{schema='cochem-upgrade-preview-plan/1';mode='READ_ONLY_PLAN';holds=@()})))}
    $null=[IO.Directory]::CreateDirectory($root)
    $previewDecision=[string](HX-Next 'preview_decision' 'PASSED');$previewCode=[int](HX-Next 'preview_apply_code' 0)
    $installAfter=$(if($script:HX.preview_install_after_tamper){'7'*64}else{HX-Sha (Join-Path $script:R5Root 'install-after.json')})
    HX-WriteJson (Join-Path $root 'preview-summary.json') ([ordered]@{schema='cochem-upgrade-preview-r5-result/1';status='PREVIEW_COMPLETED';decision=$previewDecision;attempt=$attempt;
        proposed=[ordered]@{path=(HX-Arg $A '-Candidate');sha256=(HX-Arg $A '-CandidateSha256')};install_root=$script:R5Root;install_after_sha256=$installAfter;
        gate=[ordered]@{passed=($previewDecision -ceq 'PASSED');reasons=@()}})
    if($previewCode -ne 0 -or $previewDecision -cne 'PASSED'){HX-WriteJson (Join-Path $root 'preview-held.json') @{decision=$previewDecision}
        return (HX-Result $(if($previewCode){$previewCode}else{1}) ('COCHEM_UPGRADE_PREVIEW_RESULT {"decision":"'+$previewDecision+'"}'+"`nSERIES-STOP (S10): the upgrade preview gate failed"))}
    HX-Result 0 (HX-Json ([ordered]@{schema='cochem-upgrade-preview-result/1';decision='PASSED';root=$root}))}
function HX-Has-File {param([string]$Root,[string]$Name)[IO.File]::Exists((Join-Path $Root $Name))}
function HX-ReadJson {param([string]$Path)[IO.File]::ReadAllText($Path)|ConvertFrom-Json}
function HX-RetargetSource {param([string]$Target,[string]$SourceAttempt,[string]$StopAttempt)
    # The accepted source states of retarget-warden-r5.ps1 (INTERFACES-CUTOVER final, C-F1..C-F8); '' = accepted, else the refusal.
    $w=$script:HX.warden
    if([int]$w.instances -gt 0 -or [int]$w.listening -gt 0){return 'a controller instance is running or 47824 is busy'}
    if(-not $SourceAttempt){if($StopAttempt){return '-StopAttempt needs -SourceAttempt'};if($w.source -cne 'r4-v1'){return ('the live action is '+$w.source+', not r4-v1')};return ''}
    $liveTarget=$(if($w.source -ceq 'r5'){'r5'}elseif($w.source -ceq 'r4-restore'){'r4'}else{''})
    if(-not $liveTarget -or [string]$w.source_attempt -cne $SourceAttempt){return ('the live action is not that of attempt '+$SourceAttempt)}
    $root=Join-Path $script:Base ('WardenRetarget4.2.7-windows-20261011-'+$liveTarget+'-'+$SourceAttempt)
    if($StopAttempt){
        $stop=Join-Path $script:Base ('WardenStop4.2.7-windows-20261011-r5-'+$StopAttempt+'\stop-receipt.json')
        if(-not [IO.File]::Exists($stop)){return ('no stop receipt for -StopAttempt '+$StopAttempt)}
        $s=HX-ReadJson $stop
        if([string]$s.retarget_attempt -cne $SourceAttempt -or [string]$s.retarget_target -cne $liveTarget){return 'the stop receipt names another attempt'}
        return ''}
    $intentAfter=$null;if(HX-Has-File $root 'retarget-intent.json'){try{$intentAfter=(HX-ReadJson (Join-Path $root 'retarget-intent.json')).action_after}catch{$intentAfter=$null}}
    if(HX-Has-File $root 'retarget-held.json'){
        $h=$null;try{$h=HX-ReadJson (Join-Path $root 'retarget-held.json')}catch{return 'retarget-held.json is unreadable'}
        if($h.phase -cne 'MUTATION_READBACK' -or $Target -cne 'r4'){return 'retarget-held.json is not a readback hold restorable to r4'}
        if(-not (HX-SameAction $w.action $intentAfter)){return 'the live action is not the retarget intent action_after'};return ''}
    if(-not (HX-Has-File $root 'retarget-receipt.json')){
        if((HX-Has-File $root 'retarget-intent.json') -and $Target -ceq 'r4'){if(-not (HX-SameAction $w.action $intentAfter)){return 'the live action is not the retarget intent action_after'};return ''}
        return 'the source attempt has no retarget receipt'}
    if(HX-Has-File $root 'start-receipt.json'){return 'the source attempt started: it needs -StopAttempt after stop-warden-r5'}
    if(HX-Has-File $root 'start-held.json'){$h=HX-ReadJson (Join-Path $root 'start-held.json');if($h.held_before_run -eq $true){return ''};return 'the source start was held after Run'}
    if(HX-Has-File $root 'start-intent.json'){return 'the source start was requested without a record (needs stop-warden-r5 -RecoverInterruptedStart)'}
    ''}
function HX-StartHeld {param([string]$Root,[string]$Target,[string]$Attempt,[hashtable]$Fields)
    $held=[ordered]@{schema='cochem-warden-start-held/3';target=$Target;attempt=$Attempt;task_name='CoChem-4.2.7-Warden';interrupted=$false;stage='HEALTH_WAIT';
        health_gate_passed=$false;stop_recovery_allowed=$false;run_requested=$true;run_exception=$null;held_before_run=$false;instance_guid=$null;
        trigger_enable_requested=$false;trigger_enabled_after=$(if($Target -ceq 'r5'){$false}else{$null});receipt_written=$false;enabled_after=$false;
        task_xml_after_sha256=('3'*64);reason='stub hold';automatic_retry_allowed=$false;requires_reviewed_recovery=$true}
    $legacy=$Fields.ContainsKey('legacy_no_recovery')
    foreach($k in @($Fields.Keys|Where-Object {$_ -cne 'legacy_no_recovery'})){$held[$k]=$Fields[$k]}
    # retarget-warden-r5.ps1 97403e81 (R-F1): stop_recovery_allowed = (not held_before_run) or interrupted. A record from an
    # earlier retarget build ('legacy') may still say false after Run.
    if(-not $legacy){$held.stop_recovery_allowed=((-not [bool]$held.held_before_run) -or [bool]$held.interrupted)}
    HX-WriteJson (Join-Path $Root 'start-held.json') $held}
function HX-StartedRoot {param([string]$Target,[string]$Attempt,[string]$Config)
    # A completed two-phase start of an earlier attempt (used to fake an r4 restore that this sitting must stop first).
    $root=Join-Path $script:Base ('WardenRetarget4.2.7-windows-20261011-'+$Target+'-'+$Attempt);$null=[IO.Directory]::CreateDirectory($root)
    HX-WriteJson (Join-Path $root 'retarget-receipt.json') ([ordered]@{schema='cochem-warden-retarget/3';status=('WARDEN_RETARGETED_TO_'+$Target.ToUpperInvariant()+'_NOT_STARTED');target=$Target;attempt=$Attempt;enabled_after=$false})
    HX-WriteJson (Join-Path $root 'start-intent.json') ([ordered]@{schema='cochem-warden-start-intent/3';target=$Target;attempt=$Attempt})
    HX-Write (Join-Path $root 'warden-task-started.xml') '<Task/>';$xml=HX-Sha (Join-Path $root 'warden-task-started.xml')
    HX-WriteJson (Join-Path $root 'start-receipt.json') ([ordered]@{schema='cochem-warden-start/3';status=$(if($Target -ceq 'r5'){'WARDEN_R5_RUNNING_HEALTH_VERIFIED'}else{'WARDEN_R4_RESTARTED_HEALTH_VERIFIED'});
        target=$Target;attempt=$Attempt;config_path=$Config;task_xml_sha256=$xml;task_xml_started_sha256=$xml;trigger_enabled_before=$null;trigger_enabled_after=$null})}
$script:HXHandlers['retarget-warden-r5.ps1']={param($A,$Exe,$Path,$Pre)
    # Kinds (queues retarget_r5 / retarget_r4), INTERFACES-CUTOVER final:
    #   ok | refused | held-before-update (PREPARATION) | held-readback (MUTATION_READBACK) | retarget-interrupted (intent only)
    #   held-before-run | held-run-exception (C-F7) | held-after-run (gate not passed) | interrupted (Ctrl+C finally) | crashed (start intent only)
    #   held-after-gate-trigger (TRIGGER_ENABLE) | held-after-gate-readback (POST_START_READBACK)
    #   receipt-trigger-after-false | receipt-trigger-before-true | receipt-xml-mismatch (malformed start receipts)
    $target=HX-Arg $A '-Target';$attempt=HX-Arg $A '-Attempt';$config=HX-Arg $A '-Config'
    if(-not (HX-Has $A '-Apply')){return (HX-Result 0 (HX-Json ([ordered]@{schema='cochem-warden-retarget-plan/3';mode='READ_ONLY_PLAN';target=$target;holds=@()})))}
    $kind=[string](HX-Next $(if($target -ceq 'r5'){'retarget_r5'}else{'retarget_r4'}) 'ok')
    $root=Join-Path $script:Base ('WardenRetarget4.2.7-windows-20261011-'+$target+'-'+$attempt)
    if($kind -ceq 'refused'){return (HX-Result 1 'The retarget is refused: the source state is not accepted. Nothing was changed.')}
    if([IO.Directory]::Exists($root)){return (HX-Result 1 ('The attempt root exists: '+$root+'. Namespaces are never reused. Nothing was changed.'))}
    $why=HX-RetargetSource $target (HX-Arg $A '-SourceAttempt') (HX-Arg $A '-StopAttempt')
    if($why){HX-Trace 'retarget-refused' @{why=$why};return (HX-Result 1 ('The retarget is refused before any change: '+$why+'. Nothing was changed.'))}
    $null=[IO.Directory]::CreateDirectory($root)
    $mode='COMMISSIONED'
    if($target -ceq 'r5'){$mode=$(if($config -ceq $script:CommissioningConfig){'GEMINI_HELD_COMMISSIONING_FILE'}elseif((HX-Sha $config) -ceq $script:HXCommissionedSha){'GEMINI_HELD_COMMISSIONED_BYTES'}else{'GEMINI_CONTRACT'})}
    if($script:HX.retarget_mode_override -and $target -ceq 'r5'){$mode=$script:HX.retarget_mode_override}
    $actionBefore=$script:HX.warden.action;$actionAfter=HX-ActionFor $target $attempt $config
    HX-WriteJson (Join-Path $root 'retarget-intent.json') ([ordered]@{schema='cochem-warden-retarget-intent/3';attempt=$attempt;target=$target;task_name='CoChem-4.2.7-Warden';
        action_before=$actionBefore;action_after=$actionAfter;config_path=$config;enabled_before=$script:HX.warden.enabled})
    if($kind -ceq 'held-before-update'){HX-WriteJson (Join-Path $root 'retarget-held.json') ([ordered]@{schema='cochem-warden-retarget-held/3';phase='PREPARATION';target=$target;attempt=$attempt;mutation_requested=$false;reason='stub'});return (HX-Result 1 'The retarget is held before any task change: stub. Nothing was retargeted.')}
    # TASK_UPDATE (RegisterTaskDefinition). F1: '-unapplied' kinds model a call that threw before the task changed, '-other'
    # a live action that is neither the intent's before nor after; every other kind applies the update (registered disabled).
    $applied=-not ($kind -like '*-unapplied' -or $kind -like '*-other')
    if($applied){$script:HX.warden.action=$actionAfter;$script:HX.warden.source=$(if($target -ceq 'r5'){'r5'}else{'r4-restore'});$script:HX.warden.source_attempt=$attempt}
    elseif($kind -like '*-other'){$script:HX.warden.action=HX-ActionFor 'other' '' '';$script:HX.warden.source='unknown';$script:HX.warden.source_attempt=$null}
    $script:HX.warden.enabled=$false;$script:HX.warden.instances=0;$script:HX.warden.listening=0
    if($kind -like 'held-readback*' -or $kind -ceq 'retarget-held-unreadable'){
        $readable=($kind -ceq 'held-readback')
        if($kind -ceq 'retarget-held-unreadable'){HX-Write (Join-Path $root 'retarget-held.json') '{ not json'}
        else{HX-WriteJson (Join-Path $root 'retarget-held.json') ([ordered]@{schema='cochem-warden-retarget-held/3';phase='MUTATION_READBACK';target=$target;attempt=$attempt;mutation_requested=$true;
            readback_readable=$readable;readback=$(if($readable){[ordered]@{enabled=$false;instances=0;action_path=$actionAfter.execute;action_arguments=$actionAfter.arguments}}else{$null});
            task_xml_after_sha256=$(if($readable){'b'*64}else{$null});receipt_written=$false;reason=$(if($readable){'logon trigger user readback mismatch'}else{'(0x80041318) RegisterTaskDefinition threw'})})}
        return (HX-Result 1 'The retarget readback is held. The task action may already be changed; preserve everything and review retarget-held.json.')}
    if($kind -like 'retarget-interrupted*'){return (HX-Result -1073741510 'invoke failed: the console was closed during the task update')}
    HX-Write (Join-Path $root 'warden-task-after.xml') ('<Task attempt="'+$attempt+'"/>')
    HX-WriteJson (Join-Path $root 'retarget-receipt.json') ([ordered]@{schema='cochem-warden-retarget/3';status=('WARDEN_RETARGETED_TO_'+$target.ToUpperInvariant()+'_NOT_STARTED');target=$target;attempt=$attempt;
        enabled_after=$false;trigger_enabled_after=$(if($target -ceq 'r5'){$false}else{$null});config_path=$config;config_mode=$mode;task_xml_sha256=(HX-Sha (Join-Path $root 'warden-task-after.xml'))})
    $retargetLine=HX-Json ([ordered]@{schema='cochem-warden-retarget-result/3';status=('WARDEN_RETARGETED_TO_'+$target.ToUpperInvariant()+'_NOT_STARTED');mode='RETARGET';target=$target;attempt=$attempt;receipt_path=(Join-Path $root 'retarget-receipt.json')})
    if(-not (HX-Has $A '-Start')){return (HX-Result 0 $retargetLine)}
    if($kind -ceq 'held-before-run'){HX-StartHeld $root $target $attempt @{stage='BEFORE_RUN';run_requested=$false;held_before_run=$true;reason='enable before Run failed'};return (HX-Result 1 ($retargetLine+"`nThe "+$target+' start is held before Run.'))}
    HX-WriteJson (Join-Path $root 'start-intent.json') ([ordered]@{schema='cochem-warden-start-intent/3';target=$target;attempt=$attempt;task_name='CoChem-4.2.7-Warden';retarget_receipt_sha256=(HX-Sha (Join-Path $root 'retarget-receipt.json'))})
    if($kind -ceq 'held-run-exception'){HX-StartHeld $root $target $attempt @{stage='RUN';run_requested=$true;run_exception='The task Run threw: 0x80070005';held_before_run=$true;reason='Run threw with no instance'};return (HX-Result 1 ($retargetLine+"`nThe "+$target+' start is held: Run threw.'))}
    # Run requested: a controller may be alive from here on.
    $script:HX.warden.instances=1;$script:HX.warden.listening=1
    switch -CaseSensitive ($kind){
        # R-F1: the retarget writes stop_recovery_allowed true for every hold after Run.
        'held-after-run'{HX-StartHeld $root $target $attempt @{stage='HEALTH_WAIT';stop_recovery_allowed=$true;instance_guid='{1234}';reason='health gate timed out'};return (HX-Result 1 ($retargetLine+"`nThe "+$target+' start is held: health gate timed out.'))}
        'held-unreadable'{HX-Write (Join-Path $root 'start-held.json') '{ truncated';return (HX-Result 1 ($retargetLine+"`nThe "+$target+' start is held.'))}
        'held-after-run-legacy'{HX-StartHeld $root $target $attempt @{stage='HEALTH_WAIT';stop_recovery_allowed=$false;legacy_no_recovery=$true;instance_guid='{1234}';reason='health gate timed out'};return (HX-Result 1 ($retargetLine+"`nThe "+$target+' start is held: health gate timed out.'))}
        'interrupted'{HX-StartHeld $root $target $attempt @{interrupted=$true;stop_recovery_allowed=$true;stage='HEALTH_WAIT';instance_guid='{1234}';reason='interrupted (Ctrl+C)'};return (HX-Result -1073741510 ($retargetLine+"`nThe "+$target+' start was interrupted.'))}
        'crashed'{return (HX-Result -1073741510 'invoke failed: the console was closed')}
        'held-after-gate-trigger'{HX-StartHeld $root $target $attempt @{health_gate_passed=$true;stop_recovery_allowed=$true;stage='TRIGGER_ENABLE';trigger_enable_requested=$true;instance_guid='{1234}';reason='trigger enable readback failed'};return (HX-Result 1 ($retargetLine+"`nThe "+$target+' start is held after its health gate.'))}
        'held-after-gate-readback'{HX-StartHeld $root $target $attempt @{health_gate_passed=$true;stop_recovery_allowed=$true;stage='POST_START_READBACK';instance_guid='{1234}';reason='process proof failed'};return (HX-Result 1 ($retargetLine+"`nThe "+$target+' start is held after its health gate.'))}}
    $status=$(if($target -ceq 'r5'){'WARDEN_R5_RUNNING_HEALTH_VERIFIED'}else{'WARDEN_R4_RESTARTED_HEALTH_VERIFIED'})
    # The start receipt (New-ReceiptHead + two-phase fields): config_sha256 of the configuration started, install_after_sha256 of the runtime.
    HX-Write (Join-Path $root 'warden-task-started.xml') ('<Task attempt="'+$attempt+'" started="1"/>')
    $xml=HX-Sha (Join-Path $root 'warden-task-started.xml');$xmlStarted=$xml
    $before=$(if($target -ceq 'r5'){$false}else{$null});$after=$(if($target -ceq 'r5'){$true}else{$null})
    if($kind -ceq 'receipt-trigger-after-false'){$after=$false};if($kind -ceq 'receipt-trigger-before-true'){$before=$true};if($kind -ceq 'receipt-xml-mismatch'){$xmlStarted=('c'*64)}
    $configSha=$(if($target -ceq 'r5'){HX-Sha $config}else{$script:HXCommissionedSha})
    $installSha=$(if($target -ceq 'r5'){HX-Sha (Join-Path $script:R5Root 'install-after.json')}else{$null})
    $tamper=$(if($target -ceq 'r5'){[string](HX-Next 'start_tamper' '')}else{''})
    if($tamper -ceq 'config'){$configSha=('6'*64)};if($tamper -ceq 'install'){$installSha=('8'*64)}
    $receiptPath=Join-Path $root 'start-receipt.json'
    HX-WriteJson $receiptPath ([ordered]@{schema='cochem-warden-start/3';status=$status;target=$target;attempt=$attempt;task_name='CoChem-4.2.7-Warden';config_path=$config;config_sha256=$configSha;
        install_after_sha256=$installSha;config_mode=$mode;retarget_receipt_sha256=(HX-Sha (Join-Path $root 'retarget-receipt.json'));intent_sha256=(HX-Sha (Join-Path $root 'start-intent.json'));
        task_xml_sha256=$xml;task_xml_started_sha256=$xmlStarted;trigger_enabled_before=$before;trigger_enabled_after=$after})
    $receiptSha=HX-Sha $receiptPath
    if($tamper -ceq 'receipt-sha'){$receiptSha=('9'*64)}
    if($tamper -ceq 'receipt-path'){$receiptPath=Join-Path $script:Base 'elsewhere\start-receipt.json'}
    $script:HX.warden.enabled=$true;$script:HX.warden.task_state=4;$script:HX.active_mode=$mode
    HX-Result 0 ($retargetLine+"`n"+(HX-Json ([ordered]@{schema='cochem-warden-start-result/3';status=$status;target=$target;attempt=$attempt;receipt_path=$receiptPath;receipt_sha256=$receiptSha;enabled_by_start=$true;enabled_after=$true})))}
function HX-StopBinding {param([string]$Target,[string]$Attempt,[bool]$Recover)
    # The start binding of stop-warden-r5.ps1 (R-F1): START_RECEIPT without -RecoverInterruptedStart; START_INTERRUPTED_HELD,
    # START_HELD_AFTER_HEALTH_GATE, START_HELD_BEFORE_HEALTH_GATE or START_CRASHED_NO_RECORD with it, plus the idle proof
    # (stable SYSTEM identity from the bound runtime's source root, active [], quarantined_slots {}, execution_quarantines []).
    # Every other combination is refused before any change.
    $root=Join-Path $script:Base ('WardenRetarget4.2.7-windows-20261011-'+$Target+'-'+$Attempt)
    $fail={param($Why)[pscustomobject]@{ok=$false;why=$Why;kind=$null}}
    if($script:HX.warden.source -cne $(if($Target -ceq 'r5'){'r5'}else{'r4-restore'}) -or [string]$script:HX.warden.source_attempt -cne $Attempt){return (& $fail ('the live action is not that of '+$Target+' '+$Attempt))}
    if([int]$script:HX.warden.listening -gt 0){
        $h=HX-Health;$sourceRoot=$(if($Target -ceq 'r5'){$script:R5SourceRoot}else{$script:R4SourceRoot})
        if($h.service_identity -cne 'SYSTEM' -or [string]$h.source_root -ine $sourceRoot -or @($h.active).Count -or @($h.quarantined_slots.Keys).Count -or @($h.routing.execution_quarantines).Count){
            return (& $fail 'The controller is not idle under the bound SYSTEM identity and runtime root (polled up to -IdleWaitSeconds).')}}
    if(HX-Has-File $root 'retarget-held.json'){return (& $fail 'the retarget attempt holds retarget-held.json; it needs a reviewed recovery, not a stop')}
    if(-not $Recover){
        if(HX-Has-File $root 'start-held.json'){return (& $fail 'the retarget attempt holds start-held.json (bind it with -RecoverInterruptedStart when stop_recovery_allowed is true)')}
        if(-not (HX-Has-File $root 'start-receipt.json')){return (& $fail ('the start receipt is missing'+$(if(HX-Has-File $root 'start-intent.json'){'; start-intent.json without a start receipt is bound by -RecoverInterruptedStart'}else{''})))}
        $r=HX-ReadJson (Join-Path $root 'start-receipt.json')
        if($Target -ceq 'r5' -and ($r.trigger_enabled_before -ne $false -or $r.trigger_enabled_after -ne $true)){return (& $fail 'The start receipt does not record the two-phase start (trigger_enabled_before false, trigger_enabled_after true).')}
        if([string]$r.task_xml_started_sha256 -cne [string]$r.task_xml_sha256){return (& $fail 'The start receipt task_xml_started_sha256 is not its task_xml_sha256.')}
        return [pscustomobject]@{ok=$true;why='';kind='START_RECEIPT'}}
    if(HX-Has-File $root 'start-receipt.json'){return (& $fail 'the attempt holds a start receipt: bind it without -RecoverInterruptedStart')}
    if(-not (HX-Has-File $root 'start-intent.json')){return (& $fail 'the attempt has no start-intent.json: there is no interrupted start to recover')}
    if(HX-Has-File $root 'start-held.json'){
        $h=$null;try{$h=HX-ReadJson (Join-Path $root 'start-held.json')}catch{return (& $fail 'the start-held record is unreadable')}
        if($h.stop_recovery_allowed -ne $true -or $h.held_before_run -eq $true){return (& $fail 'the start-held record does not allow a stop recovery')}
        return [pscustomobject]@{ok=$true;why='';kind=$(if($h.interrupted -eq $true){'START_INTERRUPTED_HELD'}elseif($h.health_gate_passed -eq $true){'START_HELD_AFTER_HEALTH_GATE'}else{'START_HELD_BEFORE_HEALTH_GATE'})}}
    [pscustomobject]@{ok=$true;why='';kind='START_CRASHED_NO_RECORD'}}
$script:HXHandlers['stop-warden-r5.ps1']={param($A,$Exe,$Path,$Pre)
    $attempt=HX-Arg $A '-Attempt';$root=Join-Path $script:Base ('WardenStop4.2.7-windows-20261011-r5-'+$attempt)
    if(-not (HX-Has $A '-Apply')){return (HX-Result 0 (HX-Json ([ordered]@{schema='cochem-warden-stop-plan/2';mode='READ_ONLY_PLAN'})))}
    $kind=HX-Next 'stop_r5' 'ok'
    if($kind -ceq 'refused'){return (HX-Result 1 'The Warden stop is refused: not idle. Nothing was changed.')}
    if([IO.Directory]::Exists($root)){return (HX-Result 1 ('The stop attempt root exists: '+$root+'. Nothing was changed.'))}
    $retargetTarget=HX-Arg $A '-RetargetTarget';$retargetAttempt=HX-Arg $A '-RetargetAttempt';$recover=HX-Has $A '-RecoverInterruptedStart'
    $binding=HX-StopBinding $retargetTarget $retargetAttempt $recover
    if(-not $binding.ok){HX-Trace 'stop-refused' @{why=$binding.why};return (HX-Result 1 ('The Warden stop is refused before any change: '+$binding.why+' Nothing was changed.'))}
    $null=[IO.Directory]::CreateDirectory($root)
    if($kind -ceq 'held'){HX-WriteJson (Join-Path $root 'stop-held.json') @{reason='survivor'};return (HX-Result 1 'The Warden stop is held after End; nothing was killed.')}
    HX-WriteJson (Join-Path $root 'stop-receipt.json') ([ordered]@{schema='cochem-warden-stop/2';status='WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED';retarget_target=$retargetTarget;
        retarget_attempt=$retargetAttempt;recover_interrupted_start=$recover;start_binding=$binding.kind})
    $script:HX.warden.enabled=$false;$script:HX.warden.instances=0;$script:HX.warden.listening=0;$script:HX.warden.task_state=1;$script:HX.active_mode=''
    HX-Result 0 (HX-Json ([ordered]@{schema='cochem-warden-stop-result/2';status='WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED';mode='STOP';attempt=$attempt;retarget_target=$retargetTarget;
        retarget_attempt=$retargetAttempt;start_binding=$binding.kind;receipt_path=(Join-Path $root 'stop-receipt.json');receipt_sha256=(HX-Sha (Join-Path $root 'stop-receipt.json'))}))}

# The r5 interpreter running the ControlClient snippet (reached only by the focused tests of the real Invoke-R5Control).
$script:HXHandlers['python.exe']={param($A,$Exe,$Path,$Pre)HX-Result 0 ("noise`n"+(HX-Json ([ordered]@{service_identity='SYSTEM';probe='real-control';argv=@($A)})))}

# ---- ControlClient stub: the public /health and workflow shapes of the r5 service ----
function HX-Health {
    # One /health view of the controller now running (also used by the stop stub's idle proof).
    $capacity=$(if($script:HXStage -ceq 'S13'){HX-Next 'admission' 3}else{3})
    $sourceRoot=$(if($script:HX.warden.source -ceq 'r5'){$script:R5SourceRoot}else{$script:R4SourceRoot})
    $health=[ordered]@{service_identity='SYSTEM';source_root=$sourceRoot;pid=4242;instance_id='i-1';version='4.2.7';admission_capacity=$capacity;active=@();quarantined_slots=[ordered]@{};
        routing=[ordered]@{holds=@();execution_quarantines=@()};knowledge=[ordered]@{ready=$true;authority_matches_capture=$true};
        admission=[ordered]@{reasons=$(if($capacity -gt 0){@()}else{@('host governor: disk IOPS')})};
        components=[ordered]@{warden_controller=[ordered]@{ready=$true;admission_ready=$true;recovery_hold=$false;rss_mib=41.5}};rss_mib=41.5;controller_rss_mib=41.5}
    foreach($k in @($script:HX.health_overrides.Keys)){
        $parts=$k.Split('.');$node=$health;for($i=0;$i -lt $parts.Count-1;$i++){$node=$node[$parts[$i]]};$node[$parts[-1]]=$script:HX.health_overrides[$k]}
    $health}
function Invoke-R5Control {param([string]$Operation,$Data=$null)
    HX-Trace 'control' @{operation=$Operation;data=$(if($null -ne $Data){HX-Json $Data}else{$null})}
    if([int]$script:HX.warden.listening -le 0){$script:R5LastControlError='exit 1: ConnectionRefusedError';return $null}
    if($Operation -ceq '/health'){return (HX-Obj (HX-Health))}
    if($Operation -ceq '/preflight'){
        $id=[string]$Data.workflow_id;$script:HXWorkflows[$id]=[string](HX-Next 'preflight' 'ok')
        return (HX-Obj ([ordered]@{workflow_id=$id;status='IN_PROGRESS';jobs=@();events=@()}))}
    if($Operation -ceq '/submit'){$id=[string]$Data.workflow_id;$script:HXWorkflows[$id]=('planning-'+$script:HX.s14_planning);return (HX-Obj ([ordered]@{workflow_id=$id;status='IN_PROGRESS';jobs=@()}))}
    if($Operation -ceq '/coding/submit'){$id=[string]$Data.workflow_id;$script:HXWorkflows[$id]=('coding-'+$script:HX.s14_coding);return (HX-Obj ([ordered]@{workflow_id=$id;status='IN_PROGRESS';jobs=@()}))}
    if($Operation -like '/workflow/*' -or $Operation -like '/coding/workflow/*'){
        $id=$Operation.Substring($Operation.LastIndexOf('/')+1)
        if(-not $script:HXWorkflows.ContainsKey($id)){$script:R5LastControlError='exit 1: Unknown job_id';return $null}
        return (HX-Obj (HX-Workflow $id $script:HXWorkflows[$id]))}
    HX-Trace 'unexpected-control' @{operation=$Operation};$null}
function HX-Workflow {param([string]$Id,[string]$Kind)
    $gemini=($script:HX.active_mode -ceq 'GEMINI_CONTRACT')
    $provider=$(if($gemini){'gemini'}else{'claude'});$model=$(if($gemini){'gemini-3.8-flash'}else{'claude-sonnet-4-5'});$native=$(if($gemini){'gemini-3.8-flash-low'}else{$model})
    $status='COMPLETED';$jobKind='PREFLIGHT_REQUEST';$events=@()
    switch -CaseSensitive ($Kind){
        'ok'{}
        'failed'{$status='FAILED'}
        'wrong-native'{$native='gemini-3.8-flash-high'}
        'other-provider'{$provider='mystery';$model='mystery-model';$native=$model}
        'hold-event'{$events+=[ordered]@{event='ROUTE_SKIPPED';details=[ordered]@{action='integration_verification_hold'}}}
        'blocked-limit'{$status='BLOCKED';$events+=[ordered]@{event='ROUTING_BLOCKED';details=[ordered]@{reason='routing_operator_limit'}}}
        'pending'{$status='IN_PROGRESS'}
        'planning-ok'{$jobKind='CHAPTER_DRAFT'}
        'planning-failed'{$status='FAILED';$jobKind='CHAPTER_DRAFT'}
        'coding-ok'{$jobKind='CODE_PLAN'}
        'coding-failed'{$status='FAILED';$jobKind='CODE_PLAN'}}
    $job=[ordered]@{job_id=('job-'+$Id);workflow_id=$Id;kind=$jobKind;status=$status;
        route=[ordered]@{provider=$provider;model=$model;reasoning_effort=$null;worker_slot='slot1'};
        receipt=$(if($status -ceq 'COMPLETED'){[ordered]@{provider=$provider;reported_model=$model;native_reported_model=$native;requested_model=$model}}else{$null})}
    $root=[ordered]@{job_id=$Id;kind='MACRO_PLANNING_REQUEST';status=$status}
    $jobs=@($job);if($Kind -like 'planning-*'){$second=[ordered]@{};foreach($k in $job.Keys){$second[$k]=$job[$k]};$second.job_id=('job2-'+$Id);$jobs+=$second}
    [ordered]@{workflow_id=$Id;status=$status;root=$root;jobs=$jobs;artifacts=@();events=$events}}

# ---- tracing wrappers around real functions (stage boundaries, pin checks, Gemini held, stops) ----
$script:HXOrig=@{}
foreach($hxName in @('Assert-R5Pin','Set-R5GeminiHeld','Stop-R5Series','Invoke-R5Restore','Invoke-R5GeminiFallback','Read-R5JsonFile','Write-R5Outcome')+@(0..14|ForEach-Object {'Invoke-R5Stage'+$_})){
    $hxItem=Get-Item -LiteralPath ('function:'+$hxName) -ErrorAction SilentlyContinue
    if($null -eq $hxItem){continue}
    $script:HXOrig[$hxName]=$hxItem.ScriptBlock}
function Assert-R5Pin {param([string]$Name)HX-Trace 'pin' @{name=$Name};& $script:HXOrig['Assert-R5Pin'] -Name $Name}
function Read-R5JsonFile {param([string]$Path)HX-Trace 'read' @{path=$Path};& $script:HXOrig['Read-R5JsonFile'] -Path $Path}
function Set-R5GeminiHeld {param([string]$Stage,[string]$Reason)HX-Trace 'gemini-held' @{held_stage=$Stage;reason=$Reason};& $script:HXOrig['Set-R5GeminiHeld'] -Stage $Stage -Reason $Reason}
function Stop-R5Series {param([string]$Reason,[switch]$Restore)HX-Trace 'series-stop' @{reason=$Reason;restore=[bool]$Restore};& $script:HXOrig['Stop-R5Series'] -Reason $Reason -Restore:$Restore}
function HX-Enter {param([string]$Name,[string]$Label)HX-LockProbe ('before '+$Name);$script:HXStack.Add($script:HXStage);$script:HXStage=$Label;HX-Trace 'enter' @{name=$Name}}
function Write-R5Outcome {param([string]$Phase)HX-LockProbe ('outcome '+$Phase);& $script:HXOrig['Write-R5Outcome'] -Phase $Phase}
function HX-Leave {param([string]$Name)HX-Trace 'leave' @{name=$Name};$script:HXStage=$script:HXStack[$script:HXStack.Count-1];$script:HXStack.RemoveAt($script:HXStack.Count-1)}
function Invoke-R5Restore {param([string]$Reason)HX-Enter 'Invoke-R5Restore' 'RESTORE';try{$r=& $script:HXOrig['Invoke-R5Restore'] -Reason $Reason;HX-Trace 'restore-result' @{ok=[bool]$r.ok;restored=[bool]$r.restored;message=[string]$r.message};$r}finally{HX-Leave 'Invoke-R5Restore'}}
function Invoke-R5GeminiFallback {param([string]$Reason)HX-Enter 'Invoke-R5GeminiFallback' 'FALLBACK';try{& $script:HXOrig['Invoke-R5GeminiFallback'] -Reason $Reason}finally{HX-Leave 'Invoke-R5GeminiFallback'}}
foreach($hxNumber in 0..14){
    $hxName='Invoke-R5Stage'+$hxNumber
    if(-not $script:HXOrig.ContainsKey($hxName)){continue}
    $hxBody="HX-Enter '$hxName' 'S$hxNumber';try{& `$script:HXOrig['$hxName']}finally{HX-Leave '$hxName'}"
    Set-Item -LiteralPath ('function:script:'+$hxName) -Value ([scriptblock]::Create($hxBody))}
# Initialize-R5Paths stays real; the harness re-applies its own bindings after every call.
$script:HXOrig['Initialize-R5Paths']=(Get-Item -LiteralPath 'function:Initialize-R5Paths').ScriptBlock
function Initialize-R5Paths {& $script:HXOrig['Initialize-R5Paths'];HX-Trace 'paths';$script:CommissionedSha256=$script:HXCommissionedSha
    # Bindings the harness owns: a temp client config (F6) and the venv pins of the stub r5 runtime (F7); the token file path
    # and port stay the orchestrator's constants. The live task starts on today's r4-v1 action (F1).
    $script:ClientConfig=$script:HXClientConfig;$script:R5PyvenvPin=$script:HXPyvenvSha;$script:R5VenvPythonPin=$script:HXVenvPythonSha
    if($null -eq $script:HX.warden.action){$script:HX.warden.action=HX-ActionFor 'r4-v1' '' ''}}

# ---- test-specific setup ----
__OVERRIDES__

# ---- run (Invoke-R5Series ends the process with exit 0 or 1) ----
HX-Trace 'start' @{apply=[bool]$script:Apply;gemini=$script:Gemini;attempt=$script:Attempt}
$hxOutcome=__ENTRY__
HX-Trace 'end' @{outcome=[string]$hxOutcome}
'''


class Flow:
    """The trace of one harness run."""

    def __init__(self, returncode, stdout, stderr, events, base, workspace):
        self.returncode, self.stdout, self.stderr, self.events = returncode, stdout, stderr, events
        self.base, self.workspace = base, workspace

    def of(self, kind):
        return [e for e in self.events if e['kind'] == kind]

    @property
    def runs(self):
        return self.of('run')

    def child_runs(self, child):
        return [e for e in self.runs if e['child'] == child]

    def children(self):
        return [e['child'] for e in self.runs]

    def stages(self):
        return [e['name'] for e in self.of('enter')]

    def waits(self, stage=None):
        return [e['seconds'] for e in self.of('wait') if stage is None or e['stage'] == stage]

    def controls(self, operation=None):
        return [e for e in self.of('control') if operation is None or e['operation'] == operation]

    def retargets(self, target=None):
        return [e for e in self.child_runs(RETARGET) if target is None or arg(e, '-Target') == target]

    def sitting_root(self, attempt='v1'):
        return self.base / f'R5Sitting4.2.7-windows-20261011-{attempt}'

    def receipts(self, attempt='v1'):
        root = self.sitting_root(attempt)
        return sorted(p.name.split('-')[0] for p in root.glob('S*-receipt.json')) if root.exists() else []

    def receipt(self, stage, attempt='v1'):
        return json.loads((self.sitting_root(attempt) / f'{stage}-receipt.json').read_text(encoding='utf-8-sig'))

    def sitting_end(self, attempt='v1'):
        path = self.sitting_root(attempt) / 'sitting-end.json'
        return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else None

    def held_stages(self):
        return [e['held_stage'] for e in self.of('gemini-held')]

    def explain(self):
        tail = '\n'.join(json.dumps(e)[:400] for e in self.events[-30:])
        return f'exit {self.returncode}\nSTDOUT (tail):\n{self.stdout[-5000:]}\nSTDERR:\n{self.stderr[-3000:]}\nTRACE TAIL:\n{tail}'


def arg(event, name):
    args = event['args']
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


def flags(event):
    return sorted(a for a in event['args'] if a.startswith('-'))


def prepare(tmp_path, freeze_sha=None):
    work = tmp_path / 'work'
    workspace, base = work / 'workspace', work / 'base'
    for d in (workspace, base):
        d.mkdir(parents=True, exist_ok=True)
    for name in CHILDREN:
        path = workspace / name
        if not path.exists():
            path.write_bytes(f'# stub of {name} for the r5 sitting harness\n'.encode('ascii'))
    repair_pins = {p: sha(p.encode()) for p in REPAIRS}
    manifest = workspace / 'stopped-runtime-r5-source-manifest.json'
    if not manifest.exists():
        manifest.write_text(json.dumps({'schema': 'cochem-stopped-runtime-source/2', 'reviewed_repairs': REPAIRS, 'reviewed_repairs_sha256': repair_pins,
                                        'verified_unchanged': 153}, indent=1), encoding='ascii')
    receipt = workspace / 'stopped-runtime-r5-freeze-receipt.json'
    if not receipt.exists():
        receipt.write_text(json.dumps({'schema': 'cochem-stopped-runtime-r5-freeze/1', 'manifest_sha256': freeze_sha or sha(manifest.read_bytes())}), encoding='ascii')
    pins = {name: sha((workspace / name).read_bytes()) for name in CHILDREN + [manifest.name, receipt.name]}
    r4 = base / 'Pipeline4.2.7-windows-20261009-r4'
    (r4 / '.venv' / 'Scripts').mkdir(parents=True, exist_ok=True)
    (r4 / 'pipeline.json').write_bytes(COMMISSIONED_BYTES)
    (r4 / '.venv' / 'Scripts' / 'python.exe').write_bytes(b'stub r4 python')
    commissioning = base / 'WardenCommissioning4.2.7-windows-20261007-r3-v1'
    commissioning.mkdir(parents=True, exist_ok=True)
    (commissioning / 'pipeline.json').write_bytes(COMMISSIONED_BYTES)
    client = work / 'client' / 'pipeline-client-r3.json'
    if not client.exists():
        client.parent.mkdir(parents=True, exist_ok=True)
        client.write_text(json.dumps({'port': 47824, 'token_file': TOKEN_FILE}), encoding='ascii')
    return work, workspace, base, pins, repair_pins


def snapshot(base):
    return sorted(str(p.relative_to(base)) for p in base.rglob('*'))


def run_sitting(tmp_path, overrides='', *, apply=True, gemini='attempt', attempt='v1', slug='gemini-3.8-flash-low', skip_fix_proof=False,
                entry='Invoke-R5Series', timeout=300, run_label='run', hex_seed=0, tamper=None, pin_overrides=None, freeze_sha=None):
    work, workspace, base, pins, repair_pins = prepare(tmp_path, freeze_sha)
    if pin_overrides:
        pins.update(pin_overrides)
    if tamper:
        tamper(workspace, base)
    trace = work / f'{run_label}-trace.jsonl'
    if trace.exists():
        trace.unlink()
    body = (HARNESS.replace('__TRACE__', ps_quote(trace)).replace('__SCRIPT__', ps_quote(SCRIPT)).replace('__WS__', ps_quote(workspace))
            .replace('__BASE__', ps_quote(base)).replace('__PINS__', ';'.join(f"'{ps_quote(k)}'='{ps_quote(v)}'" for k, v in sorted(pins.items())))
            .replace('__ATTEMPT__', attempt).replace('__GEMINI__', gemini).replace('__SLUG__', slug)
            .replace('__APPLY__', '$true' if apply else '$false').replace('__SKIP__', '$true' if skip_fix_proof else '$false')
            .replace('__COMMISSIONED_SHA__', COMMISSIONED_SHA).replace('__BUILDER_SHA__', pins[BUILDER])
            .replace('__REPAIRS__', ','.join(f"'{p}'" for p in REPAIRS)).replace('__REPAIR_PINS__', ';'.join(f"'{p}'='{v}'" for p, v in repair_pins.items()))
            .replace('__CONTRACT_B64__', base64.b64encode(CONTRACT_BYTES).decode('ascii')).replace('__HEX_SEED__', str(int(hex_seed)))
            .replace('__CLIENT_CONFIG__', ps_quote(work / 'client' / 'pipeline-client-r3.json'))
            .replace('__PYVENV_SHA__', sha(b'stub pyvenv.cfg')).replace('__VENV_PYTHON_SHA__', sha(b'stub r5 python'))
            .replace('__OVERRIDES__', 'Initialize-R5Paths\n' + overrides).replace('__ENTRY__', entry))
    harness = work / f'{run_label}-harness.ps1'
    harness.write_text(body, encoding='utf-8-sig')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(harness)],
                            capture_output=True, text=True, timeout=timeout, cwd=str(work))
    events = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines() if line.strip()] if trace.exists() else []
    return Flow(result.returncode, result.stdout, result.stderr, events, base, workspace)


# ---------------------------------------------------------------------------------------------------------------------
# Harness safety: every host-touching primitive of the sitting lives in a function the harness replaces

STUBBED = {'Invoke-R5Native', 'Invoke-R5Control', 'Read-R5YesNo', 'Request-R5Attention', 'Wait-R5Seconds', 'Get-R5Now', 'Assert-R5OwnerShell',
           'Get-R5WardenState', 'Get-R5DockerInfo', 'Test-R5PackageIndex', 'Get-R5FreeDiskGB', 'Get-R5ListenerCount', 'New-R5HexAttempt'}
HOST_PRIMITIVES = (r'ComObject|Get-NetTCPConnection|Invoke-WebRequest|Invoke-RestMethod|DriveInfo|Beep|WindowsIdentity|Read-Host|ReadKey|'
                   r'Start-Sleep|Get-CimInstance|Get-WmiObject|Get-MpPreference|Get-Command|Get-Date|NewGuid|&\s*\$Executable|Net\.Sockets|WebClient')


def test_every_host_primitive_sits_in_a_stubbed_function():
    text = SCRIPT.read_text(encoding='ascii')
    bodies = dict(re.findall(r'(?ms)^function ([\w-]+) (.*?)(?=^function |^if\(\$MyInvocation)', text))
    assert len(bodies) > 50
    offenders = sorted(name for name, body in bodies.items()
                       if re.search(HOST_PRIMITIVES, '\n'.join(l for l in body.splitlines() if not l.lstrip().startswith('#'))) and name not in STUBBED)
    assert offenders == [], 'functions touching the host that the harness does not replace: ' + repr(offenders)
    # Start-Process (Invoke-R5Attended) and Start-Transcript (Invoke-R5Series) are cmdlets the harness shadows by name.
    assert re.findall(r'\bStart-Process\b', text) and all(n == 'Invoke-R5Attended' for n, b in bodies.items() if re.search(r'\bStart-Process\b', b))
    assert all(n == 'Invoke-R5Series' for n, b in bodies.items() if re.search(r'\bStart-Transcript\b', b))


# ---------------------------------------------------------------------------------------------------------------------
# Shared assertions


def assert_clean_trace(flow):
    assert not flow.of('unexpected') and not flow.of('unexpected-control'), flow.explain()


def assert_pin_checked_before_every_run(flow):
    """Each child launch is immediately preceded by Assert-R5Pin for that same file (a fresh check per launch)."""
    pending = None
    for event in flow.events:
        if event['kind'] == 'pin':
            pending = event['name']
        elif event['kind'] == 'run':
            assert pending == event['child'], f"{event['child']} started without its own pin check (last pin: {pending})\n" + flow.explain()
            pending = None


def assert_succeeded(flow):
    assert flow.returncode == 0, flow.explain()
    assert 'DONE: the 4.2.7 pipeline runs on r5.' in flow.stdout, flow.explain()
    assert 'Sitting root: ' + str(flow.sitting_root()) in flow.stdout, flow.explain()
    assert not flow.retargets('r4') and flow.sitting_end()['outcome'] == 'DEPLOYED', flow.explain()
    assert_clean_trace(flow)
    assert_pin_checked_before_every_run(flow)


def assert_stopped(flow, reason_part=None):
    assert flow.returncode == 1, flow.explain()
    assert 'STOP at ' in flow.stdout, flow.explain()
    assert 'Sitting root: ' + str(flow.sitting_root()) in flow.stdout, flow.explain()
    if reason_part:
        assert reason_part in flow.stdout, flow.explain()
    assert 'DONE: the 4.2.7 pipeline' not in flow.stdout
    assert_clean_trace(flow)
    assert_pin_checked_before_every_run(flow)


def assert_claude_and_codex_fine(flow):
    leaves = flow.child_runs(LEAF)
    assert [(arg(e, '-Provider'), arg(e, '-Slot')) for e in leaves] == [(p, f'slot{n}') for p in ('claude', 'codex') for n in range(1, 7)]
    assert 'Claude  : 6/6 worker sessions verified' in flow.stdout and 'Codex   : 6/6 worker sessions verified' in flow.stdout, flow.explain()


def gemini_held_build(flow):
    builds = flow.child_runs(BUILDER)
    assert len(builds) == 1, flow.explain()
    build = builds[0]
    assert arg(build, '--mode') == 'held' and flags(build) == ['--commissioned', '--mode', '--out-dir'], build
    return build


def restore_calls(flow):
    """The restore children in order, as (child, flags-with-values)."""
    out = []
    for e in flow.runs:
        if e['stage'] == 'RESTORE':
            out.append((e['child'], ' '.join(e['args'])))
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Happy path (Gemini attempted and enabled)

@pytest.fixture(scope='module')
def happy(tmp_path_factory):
    return run_sitting(tmp_path_factory.mktemp('happy'))


def test_happy_path_runs_every_stage_and_deploys_r5_with_gemini_active(happy):
    assert_succeeded(happy)
    assert happy.stages() == ['Invoke-R5Stage' + str(n) for n in range(0, 15)]
    assert happy.children() == ([INSTALL, INSTALL, STOP_R4] + [LEAF] * 12 +
                                [CAPTURE, LOGIN, CAPTURE, ISOLATION, ISOLATION, BUILDER, STAGER, STAGER, PREVIEW, PREVIEW, RETARGET])
    assert happy.receipts() == ['S%02d' % n for n in range(0, 15)]
    assert happy.receipt('S13')['status'] == 'PASSED' and happy.receipt('S09')['status'] == 'GEMINI_CONTRACT'
    assert 'Gemini  : ACTIVE' in happy.stdout and 'Warden  : r5 RUNNING' in happy.stdout and 'Reboot  : SAFE' in happy.stdout
    assert happy.held_stages() == [] and not happy.of('prompt'), 'no question when every session is verified'
    assert not happy.child_runs(STOP_R5)


def test_happy_path_s1_installs_with_the_freeze_receipt_sha_plan_first(happy):
    plan, apply_ = happy.child_runs(INSTALL)
    manifest = happy.workspace / 'stopped-runtime-r5-source-manifest.json'
    freeze = json.loads((happy.workspace / 'stopped-runtime-r5-freeze-receipt.json').read_text())
    for run in (plan, apply_):
        assert arg(run, '-Manifest') == str(manifest) and arg(run, '-ManifestSha256') == freeze['manifest_sha256'] == sha(manifest.read_bytes())
        assert run['how'] == 'native' and run['pre'] == ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass']
        assert run['script'] == str(happy.workspace / INSTALL) and run['exe'].lower().endswith('\\windowspowershell\\v1.0\\powershell.exe')
    assert '-Apply' not in plan['args'] and apply_['args'][-1] == '-Apply'
    assert happy.receipt('S01')['state']['install_after_sha256'] == sha((happy.base / 'Pipeline4.2.7-windows-20261011-r5' / 'install-after.json').read_bytes())


def test_happy_path_s2_disables_todays_enabled_idle_warden(happy):
    (stop,) = happy.child_runs(STOP_R4)
    assert stop['args'] == ['-Apply', '-Attempt', 'v1']
    assert happy.receipt('S02')['status'] == 'WARDEN_ALREADY_STOPPED_AND_DISABLED'


def test_happy_path_s3_is_twelve_sequential_status_checks_with_one_attempt(happy):
    leaves = happy.child_runs(LEAF)
    assert [(arg(e, '-Provider'), arg(e, '-Slot')) for e in leaves] == [(p, f'slot{n}') for p in ('claude', 'codex') for n in range(1, 7)]
    assert {arg(e, '-Attempt') for e in leaves} == {leaves[0]['args'][leaves[0]['args'].index('-Attempt') + 1]}
    assert all(arg(e, '-Stage') == 'before' and e['args'][-1] == '-Apply' and e['how'] == 'native' for e in leaves)
    seqs = [e['seq'] for e in happy.events if e['kind'] in ('run', 'result') and e['child'] == LEAF]
    kinds = [e['kind'] for e in happy.events if e['kind'] in ('run', 'result') and e['child'] == LEAF]
    assert kinds == ['run', 'result'] * 12 and seqs == sorted(seqs), 'strictly one status check at a time'


def test_happy_path_gemini_onboarding_uses_one_attempt_and_the_attended_console(happy):
    out_, in_ = happy.child_runs(CAPTURE)
    (login,) = happy.child_runs(LOGIN)
    evidence, stage_only = happy.child_runs(ISOLATION)
    gx = arg(out_, '-Attempt')
    assert len(gx) == 32 and all(arg(e, '-Attempt') == gx for e in (in_, login, evidence, stage_only))
    assert out_['args'] == ['-Slot', 'slot1', '-Stage', 'signed-out', '-Attempt', gx, '-Apply']
    assert in_['args'] == ['-Slot', 'slot1', '-Stage', 'signed-in', '-Attempt', gx, '-Apply']
    assert login['how'] == 'attended' and login['args'] == ['-Provider', 'gemini', '-LoginMode', 'print', '-Attempt', gx, '-Apply', '-Interactive']
    assert '-NonInteractive' not in login['pre'], 'the attended child keeps the console interactive'
    assert happy.of('start-process')[0]['no_new_window'] is True
    assert evidence['args'] == ['-Slot', 'slot1', '-EffortNullSlug', 'gemini-3.8-flash-low', '-Attempt', gx, '-Apply']
    assert stage_only['args'] == ['-StageOnly', '-Attempt', gx, '-Apply']
    attention = [e for e in happy.of('attention') if e['stage'] == 'S6']
    assert len(attention) == 1 and attention[0]['seq'] < login['seq'], 'the owner is called to the keyboard before the sign-ins'


def test_happy_path_s9_builder_hand_offs(happy):
    (build,) = happy.child_runs(BUILDER)
    base = happy.base
    gx = arg(happy.child_runs(CAPTURE)[0], '-Attempt')
    r5python = base / 'Pipeline4.2.7-windows-20261011-r5' / '.venv' / 'Scripts' / 'python.exe'
    assert build['exe'] == str(r5python) and build['pre'][:2] == ['-I', '-B'] and build['script'] == str(happy.workspace / BUILDER)
    assert arg(build, '--commissioned') == str(base / 'Pipeline4.2.7-windows-20261009-r4' / 'pipeline.json')
    assert arg(build, '--login-root') == str(base / f'NativeAuthSix4.2.7-windows-20261011-r4-v1-{gx}-gemini')
    assert arg(build, '--capture-root') == str(base / f'AgyCapture4.2.7-windows-20261010-r4-v1-{gx}-slot1-signed-in')
    assert arg(build, '--isolation-root') == str(base / f'AgyIsolation4.2.7-windows-20261011-r4-v1-{gx}')
    assert '--stage-root' not in build['args'], 'the stage root is the default <isolation-root>-stage'
    assert arg(build, '--mode') == 'attempt' and Path(arg(build, '--out-dir')).parent == happy.sitting_root()
    assert Path(arg(build, '--out-dir')).name.endswith('-a')
    plan, apply_ = happy.child_runs(STAGER)
    assert plan['args'] == ['-BuildDirectory', arg(build, '--out-dir'), '-Attempt', 'v1'] and apply_['args'] == plan['args'] + ['-Apply']
    assert plan['how'] == apply_['how'] == 'native', 'the stager runs in the owner session, never as a SYSTEM task'


def test_happy_path_s10_and_s11_carry_the_staged_sha_and_path(happy):
    staged = happy.base / 'WardenConfig4.2.7-windows-20261011-r5-v1' / 'pipeline.json'
    assert sha(staged.read_bytes()) == CONTRACT_SHA
    plan, apply_ = happy.child_runs(PREVIEW)
    for run in (plan, apply_):
        assert arg(run, '-CandidateSha256') == CONTRACT_SHA and arg(run, '-Candidate') == str(staged) and len(arg(run, '-Attempt')) == 32
    assert arg(plan, '-Attempt') == arg(apply_, '-Attempt') and apply_['args'][-1] == '-Apply' and '-Apply' not in plan['args']
    (retarget,) = happy.child_runs(RETARGET)
    assert retarget['args'] == ['-Target', 'r5', '-Config', str(staged), '-Attempt', 'v1', '-Apply', '-Start']
    assert (happy.sitting_root() / 'S11-intent.json').exists()


def test_happy_path_s12_s13_s14_use_the_controller_with_bounded_polls(happy):
    assert all(s >= 10 for s in happy.waits('S13')), happy.waits('S13')
    assert len(happy.controls('/preflight')) == 1
    (preflight,) = happy.controls('/preflight')
    assert json.loads(preflight['data'])['workflow_id'].endswith('-pf1')
    submit = json.loads(happy.controls('/submit')[0]['data'])
    coding = json.loads(happy.controls('/coding/submit')[0]['data'])
    assert submit['chapter_count'] == 2 and len(submit['requirements']) == 2
    assert coding['project_id'] == 'windows-acceptance' and coding['objective']
    assert set(happy.waits('S14')) == {15}
    fix = happy.receipt('S14')['state']['fix_proof']
    assert fix['planning'].startswith('PASSED') and fix['coding'].startswith('PASSED')


def test_happy_path_every_launch_is_pin_checked_and_the_trace_is_clean(happy):
    assert_pin_checked_before_every_run(happy)
    assert_clean_trace(happy)
    pinned = {e['name'] for e in happy.of('pin')}
    assert set(happy.children()) <= pinned


# ---------------------------------------------------------------------------------------------------------------------
# Gemini held at each of S5..S9: the sitting still deploys r5 with Claude and Codex

GEMINI_HELD = {
    's5_exit': ("$script:HX.s5_code=1;", 'S5', [CAPTURE]),
    's5_login_mode_none': ("$script:HX.s5_mode='none';$script:HX.s5_passed=$false;", 'S5', [CAPTURE]),
    's5_incomplete': ("$script:HX.s5_decision='INCOMPLETE';", 'S5', [CAPTURE]),
    's6_paused_exit_20': ("$script:HX.login_exit.gemini=20;", 'S6', [CAPTURE, LOGIN]),
    's6_held_exit_1': ("$script:HX.login_exit.gemini=1;", 'S6', [CAPTURE, LOGIN]),
    's6_no_series_complete': ("$script:HX.login_complete.gemini=$false;", 'S6', [CAPTURE, LOGIN]),
    's7_failed': ("$script:HX.s7_code=1;", 'S7', [CAPTURE, LOGIN, CAPTURE]),
    's7_gate_not_passed': ("$script:HX.s7_passed=$false;", 'S7', [CAPTURE, LOGIN, CAPTURE]),
    's8_evidence_held_10': ("$script:HX.s8_evidence=10;", 'S8', [CAPTURE, LOGIN, CAPTURE, ISOLATION]),
    's8_evidence_refused_1': ("$script:HX.s8_evidence=1;", 'S8', [CAPTURE, LOGIN, CAPTURE, ISOLATION]),
    's8_stage_held_10': ("$script:HX.s8_stage=10;", 'S8', [CAPTURE, LOGIN, CAPTURE, ISOLATION, ISOLATION]),
}


@pytest.mark.parametrize('case', sorted(GEMINI_HELD))
def test_gemini_held_before_s9_degrades_and_the_sitting_still_deploys(tmp_path, case):
    overrides, stage, gemini_children = GEMINI_HELD[case]
    flow = run_sitting(tmp_path, overrides)
    assert_succeeded(flow)
    assert flow.held_stages() == [stage], flow.explain()
    onboarding = [c for c in flow.children() if c in (CAPTURE, LOGIN, ISOLATION)]
    assert onboarding == gemini_children, 'later Gemini stages are skipped once Gemini is held'
    gemini_held_build(flow)
    staged = flow.base / 'WardenConfig4.2.7-windows-20261011-r5-v1' / 'pipeline.json'
    assert sha(staged.read_bytes()) == COMMISSIONED_SHA, 'held mode stages the commissioned bytes'
    assert arg(flow.child_runs(PREVIEW)[1], '-CandidateSha256') == COMMISSIONED_SHA
    assert arg(flow.retargets('r5')[0], '-Config') == str(staged)
    assert len(flow.controls('/preflight')) == 1 and 'Invoke-R5GeminiFallback' not in flow.stages()
    assert 'Gemini  : HELD' in flow.stdout and flow.receipt('S09')['status'] == 'GEMINI_HELD_COMMISSIONED_BYTES'
    assert_claude_and_codex_fine(flow)


def test_gemini_held_at_s9_when_the_builder_gates_fail(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.builder_queue.Add(@{outcome='GEMINI_HELD_COMMISSIONED_BYTES'})|Out-Null;")
    assert_succeeded(flow)
    (build,) = flow.child_runs(BUILDER)
    assert arg(build, '--mode') == 'attempt', 'all evidence passed, so the builder was asked to attempt'
    assert flow.held_stages() == ['S9'] and 'Gemini  : HELD' in flow.stdout
    assert sha((flow.base / 'WardenConfig4.2.7-windows-20261011-r5-v1' / 'pipeline.json').read_bytes()) == COMMISSIONED_SHA
    assert_claude_and_codex_fine(flow)


def test_gemini_skip_runs_no_gemini_child_and_builds_held(tmp_path):
    flow = run_sitting(tmp_path, gemini='skip')
    assert_succeeded(flow)
    assert not any(c in (CAPTURE, LOGIN, ISOLATION) for c in flow.children())
    gemini_held_build(flow)
    assert flow.held_stages() == [] and 'Gemini  : SKIPPED' in flow.stdout
    assert [flow.receipt(s)['status'] for s in ('S05', 'S06', 'S07', 'S08')] == ['SKIPPED'] * 4
    assert not [e for e in flow.of('attention') if e['stage'] == 'S6'], 'no sign-in call to the owner when Gemini is skipped'
    assert_claude_and_codex_fine(flow)


# ---------------------------------------------------------------------------------------------------------------------
# S2: conditional stop of the r4 Warden

def test_s2_is_skipped_for_a_disabled_warden_without_instances(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.warden.enabled=$false;$script:HX.warden.task_state=1;")
    assert_succeeded(flow)
    assert not flow.child_runs(STOP_R4) and flow.receipt('S02')['status'] == 'SKIPPED'


def test_s2_stops_a_running_controller(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.warden.instances=1;$script:HX.warden.listening=1;$script:HX.warden.task_state=4;")
    assert_succeeded(flow)
    (stop,) = flow.child_runs(STOP_R4)
    assert stop['args'] == ['-Apply', '-Attempt', 'v1'] and flow.children().index(STOP_R4) == 2, 'after S1, before S3'
    assert flow.receipt('S02')['status'] == 'WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED'


def test_s2_takes_the_next_free_stop_namespace(tmp_path):
    flow = run_sitting(tmp_path, "$null=New-Item -ItemType Directory -Path (Join-Path $script:Base 'WardenStop4.2.7-windows-20261010-r4-v1');")
    assert_succeeded(flow)
    assert arg(flow.child_runs(STOP_R4)[0], '-Attempt') == 'v2'


def test_s2_refused_while_r4_runs_stops_with_nothing_changed(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.warden.instances=1;$script:HX.warden.listening=1;$script:HX.stop_r4='refused';")
    assert_stopped(flow, 'S2: the Warden stop was refused before any change')
    assert flow.children()[-1] == STOP_R4 and not flow.retargets()
    assert flow.sitting_end() is None, 'nothing changed: a rerun stays possible'


def test_s2_held_after_end_restores_r4(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.warden.instances=1;$script:HX.warden.listening=1;$script:HX.stop_r4='held';")
    assert_stopped(flow, 'S2: the Warden stop did not complete')
    assert restore_calls(flow) == [(RETARGET, '-Target r4 -Attempt v1 -Apply -Start')], (
        'deploy-r5-sitting.json S2: "Ended but held after End: R4-RESTORE = retarget-warden-r5.ps1 -Target r4 -Apply -Start"\n' + flow.explain())


def test_s2_from_a_restored_r4_uses_stop_warden_r5_and_s11_names_the_lineage(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.warden.source='r4-restore';$script:HX.warden.source_attempt='v3';$script:HX.warden.instances=1;$script:HX.warden.listening=1;"
                                 "$script:HX.warden.action=HX-ActionFor 'r4' 'v3' '';HX-StartedRoot 'r4' 'v3' '';")
    assert_succeeded(flow)
    assert not flow.child_runs(STOP_R4) and not flow.of('stop-refused')
    assert json.loads((flow.base / 'WardenStop4.2.7-windows-20261011-r5-v1' / 'stop-receipt.json').read_text())['start_binding'] == 'START_RECEIPT'
    (stop,) = flow.child_runs(STOP_R5)
    assert stop['args'] == ['-Apply', '-Attempt', 'v1', '-RetargetTarget', 'r4', '-RetargetAttempt', 'v3']
    (retarget,) = flow.retargets('r5')
    assert arg(retarget, '-SourceAttempt') == 'v3' and arg(retarget, '-StopAttempt') == 'v1'


# ---------------------------------------------------------------------------------------------------------------------
# S3: Claude/Codex session health with at most one question

def test_s3_signed_out_slots_accepted_ask_once_and_run_the_attended_logins(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.sess['claude:slot3']='ATTENDED_LOGIN_REQUIRED';$script:HX.sess['codex:slot5']='ATTENDED_LOGIN_REQUIRED';$script:HX.answers=[Collections.ArrayList]@($true);")
    assert_succeeded(flow)
    assert len(flow.of('prompt')) == 1 and flow.of('prompt')[0]['stage'] == 'S3'
    beeps = [e for e in flow.of('attention') if e['stage'] == 'S3']
    assert len(beeps) == 1 and beeps[0]['seq'] < flow.of('prompt')[0]['seq'], 'the owner is called (beep) right before the one question'
    assert 'claude slot3' in beeps[0]['text'] and 'codex slot5' in beeps[0]['text']
    logins = [e for e in flow.child_runs(LOGIN) if arg(e, '-Provider') in ('claude', 'codex')]
    assert [arg(e, '-Provider') for e in logins] == ['claude', 'codex']
    for e in logins:
        assert e['how'] == 'attended' and flags(e) == ['-Apply', '-Attempt', '-Interactive', '-Provider'] and len(arg(e, '-Attempt')) == 32
    assert arg(logins[0], '-Attempt') != arg(logins[1], '-Attempt'), 'a fresh series namespace per provider'
    assert max(e['seq'] for e in flow.child_runs(LEAF)) < logins[0]['seq'], 'the question comes after all twelve checks'
    assert flow.receipt('S03')['state']['sessions']['claude']['relogin'] == 'VERIFIED'
    assert 'Claude  : 6/6 worker sessions verified' in flow.stdout


def test_s3_declined_is_recorded_and_the_sitting_continues(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.sess['claude:slot3']='ATTENDED_LOGIN_REQUIRED';$script:HX.sess['codex:slot5']='ATTENDED_LOGIN_REQUIRED';$script:HX.answers=[Collections.ArrayList]@($false);")
    assert_succeeded(flow)
    assert len(flow.of('prompt')) == 1
    assert not [e for e in flow.child_runs(LOGIN) if arg(e, '-Provider') in ('claude', 'codex')]
    sessions = flow.receipt('S03')['state']['sessions']
    assert sessions['claude']['relogin'] == 'DECLINED' and sessions['codex']['relogin'] == 'DECLINED'
    assert 'signed out: slot3' in flow.stdout and 'signed out: slot5' in flow.stdout


def test_s3_held_status_and_failed_login_never_stop_the_sitting(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.sess['claude:slot2']='HOLD';$script:HX.sess['codex:slot6']='ATTENDED_LOGIN_REQUIRED';$script:HX.login_exit.codex=1;")
    assert_succeeded(flow)
    assert len(flow.of('prompt')) == 1
    sessions = flow.receipt('S03')['state']['sessions']
    assert sessions['claude']['hold'] == ['slot2'] and sessions['codex']['relogin'].startswith('UNVERIFIED')
    assert 'status unclear: slot2' in flow.stdout


def test_s3_without_signed_out_slots_never_asks(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.sess['claude:slot1']='HOLD';", gemini='skip')
    assert_succeeded(flow)
    assert not flow.of('prompt')


# ---------------------------------------------------------------------------------------------------------------------
# S9: builder retry, decision checks, staging

@pytest.mark.parametrize('exit_code', [2, 3, 4, 5])
def test_s9_builder_crash_retries_once_in_forced_held_mode_in_a_fresh_dir(tmp_path, exit_code):
    flow = run_sitting(tmp_path, f"$script:HX.builder_queue.Add(@{{exit={exit_code}}})|Out-Null;$script:HX.builder_queue.Add(@{{exit=0}})|Out-Null;")
    assert_succeeded(flow)
    first, second = flow.child_runs(BUILDER)
    assert arg(first, '--mode') == 'attempt' and arg(second, '--mode') == 'held'
    assert flags(second) == ['--commissioned', '--mode', '--out-dir']
    assert arg(first, '--out-dir') != arg(second, '--out-dir') and arg(second, '--out-dir').endswith('-b')
    assert arg(flow.child_runs(STAGER)[0], '-BuildDirectory') == arg(second, '--out-dir')
    assert flow.held_stages() == ['S9'] and 'Gemini  : HELD' in flow.stdout


DECISION_TAMPERS = ['schema', 'sha', 'length', 'python', 'isolated', 'script-sha', 'gate', 'error', 'no-bindings', 'mode', 'unknown-outcome', 'commissioned-pin']


@pytest.mark.parametrize('tamper', DECISION_TAMPERS)
def test_s9_decision_checks_refuse_and_retry_held(tmp_path, tamper):
    # 'commissioned-pin': the builder reports a commissioned pin other than $script:CommissionedSha256 (135cd9ec in the
    # sitting; the harness re-points it at the stub commissioned bytes after every Initialize-R5Paths).
    flow = run_sitting(tmp_path, f"$script:HX.builder_queue.Add(@{{tamper='{tamper}'}})|Out-Null;$script:HX.builder_queue.Add(@{{exit=0}})|Out-Null;")
    assert_succeeded(flow)
    first, second = flow.child_runs(BUILDER)
    assert arg(second, '--mode') == 'held' and arg(first, '--out-dir') != arg(second, '--out-dir'), flow.explain()
    assert flow.held_stages() == ['S9']
    assert sha((flow.base / 'WardenConfig4.2.7-windows-20261011-r5-v1' / 'pipeline.json').read_bytes()) == COMMISSIONED_SHA


def test_s9_held_outcome_with_non_commissioned_bytes_is_refused(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.builder_queue.Add(@{outcome='GEMINI_HELD_COMMISSIONED_BYTES';tamper='held-with-contract-bytes'})|Out-Null;$script:HX.builder_queue.Add(@{exit=0})|Out-Null;")
    assert_succeeded(flow)
    assert len(flow.child_runs(BUILDER)) == 2


@pytest.mark.parametrize('second', ['exit=3', "tamper='schema'"])
def test_s9_builder_failing_twice_stops_and_restores_r4(tmp_path, second):
    flow = run_sitting(tmp_path, f"$script:HX.builder_queue.Add(@{{exit=5}})|Out-Null;$script:HX.builder_queue.Add(@{{{second}}})|Out-Null;")
    assert_stopped(flow, 'S9: the configuration builder failed twice')
    assert len(flow.child_runs(BUILDER)) == 2 and not flow.child_runs(STAGER)
    assert restore_calls(flow) == [(RETARGET, '-Target r4 -Attempt v1 -Apply -Start')]
    assert 'R4-RESTORE: r4 restarted' in flow.stdout and flow.sitting_end()['outcome'] == 'STOPPED'


STAGING_FAILURES = {
    # sticky knobs: the failure repeats on every staging, so a held retry fails as well
    'plan_refused': "$script:HX.stager_plan='HELD';",
    'apply_failed': "$script:HX.stager_code=1;",
    'staged_sha_mismatch': "$script:HX.stager_sha_tamper=$true;",
    'unknown_status': "$script:HX.stager_apply='MAYBE_STAGED';",
}
BASE_RESTORE = [(RETARGET, '-Target r4 -Attempt v1 -Apply -Start')]


def builds(flow):
    return [(arg(e, '--mode'), Path(arg(e, '--out-dir')).name) for e in flow.child_runs(BUILDER)]


@pytest.mark.parametrize('case', sorted(STAGING_FAILURES))
def test_s9_staging_failure_in_held_mode_restores_r4_at_once(tmp_path, case):
    flow = run_sitting(tmp_path, STAGING_FAILURES[case], gemini='skip')
    assert_stopped(flow, 'S9:')
    assert len(flow.child_runs(BUILDER)) == 1 and not flow.child_runs(PREVIEW) and not flow.retargets('r5')
    assert restore_calls(flow) == BASE_RESTORE


@pytest.mark.parametrize('case', sorted(STAGING_FAILURES))
def test_s9_contract_staging_failure_retries_held_and_restores_only_when_that_fails_too(tmp_path, case):
    # F3: with decision GEMINI_CONTRACT a staging failure holds Gemini and rebuilds/stages the held configuration first.
    flow = run_sitting(tmp_path, STAGING_FAILURES[case])
    assert_stopped(flow, 'S9:')
    assert [m for m, _ in builds(flow)] == ['attempt', 'held'], builds(flow)
    first, held = flow.child_runs(BUILDER)
    assert flags(held) == ['--commissioned', '--mode', '--out-dir'] and arg(held, '--out-dir') != arg(first, '--out-dir')
    assert arg(flow.child_runs(STAGER)[-1], '-BuildDirectory') == arg(held, '--out-dir'), 'the held build is the one staged last'
    assert flow.held_stages() == ['S9']
    assert not flow.retargets('r5') and restore_calls(flow) == BASE_RESTORE
    restore_seq = min(e['seq'] for e in flow.runs if e['stage'] == 'RESTORE')
    assert max(e['seq'] for e in flow.child_runs(STAGER)) < restore_seq, 'the restore comes only after the held path failed'


@pytest.mark.parametrize('first', ['plan_refused', 'apply_failed', 'outcome_mismatch'])
def test_s9_contract_staging_failure_then_held_staging_deploys_r5_with_gemini_held(tmp_path, first):
    overrides = {'plan_refused': "$script:HX.stager_plan=[Collections.ArrayList]@('HELD','PLAN_OK');",
                 'apply_failed': "$script:HX.stager_code=[Collections.ArrayList]@(1,0);",
                 'outcome_mismatch': "$script:HX.stager_outcome_override='GEMINI_HELD_COMMISSIONED_BYTES';"}[first]
    flow = run_sitting(tmp_path, overrides)
    assert_succeeded(flow)
    assert [m for m, _ in builds(flow)] == ['attempt', 'held'], builds(flow)
    assert flow.held_stages() == ['S9'] and 'Gemini  : HELD' in flow.stdout
    applies = [e for e in flow.child_runs(STAGER) if '-Apply' in e['args']]
    if first == 'apply_failed':
        assert [arg(e, '-Attempt') for e in applies] == ['v1', 'v2'], 'a held staging record blocks v1: the held build goes to the next WardenConfig attempt'
    staged = flow.base / f"WardenConfig4.2.7-windows-20261011-r5-{arg(applies[-1], '-Attempt')}" / 'pipeline.json'
    assert sha(staged.read_bytes()) == COMMISSIONED_SHA
    last_preview = flow.child_runs(PREVIEW)[-1]
    assert arg(last_preview, '-CandidateSha256') == COMMISSIONED_SHA and arg(last_preview, '-Candidate') == str(staged)
    assert arg(flow.retargets('r5')[0], '-Config') == str(staged) and restore_calls(flow) == []


def test_s9_staged_path_is_carried_forward_not_assumed_v1(tmp_path):
    flow = run_sitting(tmp_path, "$null=New-Item -ItemType Directory -Path (Join-Path $script:Base 'WardenConfig4.2.7-windows-20261011-r5-v1');")
    assert_succeeded(flow)
    staged = str(flow.base / 'WardenConfig4.2.7-windows-20261011-r5-v2' / 'pipeline.json')
    assert arg(flow.child_runs(STAGER)[1], '-Attempt') == 'v2'
    assert arg(flow.child_runs(PREVIEW)[1], '-Candidate') == staged and arg(flow.retargets('r5')[0], '-Config') == staged


# ---------------------------------------------------------------------------------------------------------------------
# S10, S11, S12

PREVIEW_FAILURES = {'apply_exit': "$script:HX.preview_apply_code=1;", 'decision_failed': "$script:HX.preview_decision='FAILED';",
                    'plan_exit': "$script:HX.preview_plan_code=1;"}
PREVIEW_ONCE = {'apply_exit': "$script:HX.preview_apply_code=[Collections.ArrayList]@(1,0);",
                'decision_failed': "$script:HX.preview_decision=[Collections.ArrayList]@('GATE_FAILED','PASSED');",
                'plan_exit': "$script:HX.preview_plan_code=[Collections.ArrayList]@(1,0);"}


@pytest.mark.parametrize('case', sorted(PREVIEW_FAILURES))
def test_s10_preview_failure_in_held_mode_restores_r4_at_once(tmp_path, case):
    flow = run_sitting(tmp_path, PREVIEW_FAILURES[case], gemini='skip')
    assert_stopped(flow, 'S10:')
    assert len(flow.child_runs(BUILDER)) == 1, 'no rebuild when the configuration is already held'
    assert not flow.retargets('r5') and not flow.child_runs(STOP_R5)
    assert restore_calls(flow) == BASE_RESTORE
    assert 'Warden  : r4 RESTORED' in flow.stdout


@pytest.mark.parametrize('case', sorted(PREVIEW_FAILURES))
def test_s10_contract_preview_failure_retries_held_and_restores_only_when_that_fails_too(tmp_path, case):
    flow = run_sitting(tmp_path, PREVIEW_FAILURES[case])
    assert_stopped(flow, 'S10:')
    assert [m for m, _ in builds(flow)] == ['attempt', 'held'], builds(flow)
    assert flow.held_stages() == ['S10']
    assert {arg(e, '-CandidateSha256') for e in flow.child_runs(PREVIEW)} == {CONTRACT_SHA, COMMISSIONED_SHA}, 'S10 ran once more on the held configuration'
    assert not flow.retargets('r5') and restore_calls(flow) == BASE_RESTORE


@pytest.mark.parametrize('case', sorted(PREVIEW_ONCE))
def test_s10_contract_preview_failure_then_held_preview_deploys_r5_with_gemini_held(tmp_path, case):
    # F3: Gemini held, S9 rebuilt in held mode in a fresh build dir, staged to the next WardenConfig attempt, S10 once more.
    flow = run_sitting(tmp_path, PREVIEW_ONCE[case])
    assert_succeeded(flow)
    assert [m for m, _ in builds(flow)] == ['attempt', 'held'] and builds(flow)[0][1] != builds(flow)[1][1], builds(flow)
    assert flow.held_stages() == ['S10'] and 'Gemini  : HELD' in flow.stdout
    applies = [e for e in flow.child_runs(STAGER) if '-Apply' in e['args']]
    assert [arg(e, '-Attempt') for e in applies] == ['v1', 'v2']
    staged = flow.base / 'WardenConfig4.2.7-windows-20261011-r5-v2' / 'pipeline.json'
    assert sha(staged.read_bytes()) == COMMISSIONED_SHA
    held_previews = [e for e in flow.child_runs(PREVIEW) if arg(e, '-CandidateSha256') == COMMISSIONED_SHA]
    assert held_previews and all(arg(e, '-Candidate') == str(staged) for e in held_previews)
    assert len({arg(e, '-Attempt') for e in flow.child_runs(PREVIEW)}) == 2, 'a fresh preview attempt for the held configuration'
    assert arg(flow.retargets('r5')[0], '-Config') == str(staged) and restore_calls(flow) == []


RESTORED = 'Warden  : r4 RESTORED and running (r5 not deployed)'


def cutover_restore(vn, previous):
    """The documented INTERFACES-CUTOVER (final) restore calls for the state an r5 attempt vn reached (vK = v{n}, vM = v1)."""
    vk = vn
    return {
        'previous': previous,
        'retarget-held': [(RETARGET, f'-Target r4 -Attempt v1 -SourceAttempt {vn} -Apply -Start')],
        'never-started': [(RETARGET, f'-Target r4 -Attempt v1 -SourceAttempt {vn} -Apply -Start')],
        'interrupted': [(STOP_R5, f'-Apply -Attempt {vk} -RetargetTarget r5 -RetargetAttempt {vn} -RecoverInterruptedStart'),
                        (RETARGET, f'-Target r4 -Attempt v1 -SourceAttempt {vn} -StopAttempt {vk} -Apply -Start')],
        'started': [(STOP_R5, f'-Apply -Attempt {vk} -RetargetTarget r5 -RetargetAttempt {vn}'),
                    (RETARGET, f'-Target r4 -Attempt v1 -SourceAttempt {vn} -StopAttempt {vk} -Apply -Start')],
        'blocked': [],
    }


# retarget-warden-r5 outcome kind -> (cutover state, stop binding expected in the stop receipt)
CUTOVER_STATES = {
    'refused': ('previous', None),
    'held-before-update': ('previous', None),
    'held-readback': ('retarget-held', None),
    # F1: MUTATION_READBACK without a readable readback, and intent-only roots, are classified by the live task action.
    'held-readback-unreadable': ('retarget-held', None),
    'held-readback-unapplied': ('previous', None),
    'held-readback-other': ('blocked', None),
    'retarget-interrupted': ('retarget-held', None),
    'retarget-interrupted-unapplied': ('previous', None),
    'retarget-interrupted-other': ('blocked', None),
    'retarget-held-unreadable': ('blocked', None),
    'held-before-run': ('never-started', None),
    'held-run-exception': ('never-started', None),
    'interrupted': ('interrupted', 'START_INTERRUPTED_HELD'),
    'crashed': ('interrupted', 'START_CRASHED_NO_RECORD'),
    'held-after-gate-trigger': ('interrupted', 'START_HELD_AFTER_HEALTH_GATE'),
    'held-after-gate-readback': ('interrupted', 'START_HELD_AFTER_HEALTH_GATE'),
    # R-F1: every hold after Run is stop-recoverable; stop-warden-r5 binds START_HELD_BEFORE_HEALTH_GATE.
    'held-after-run': ('interrupted', 'START_HELD_BEFORE_HEALTH_GATE'),
    'held-unreadable': ('blocked', None),
    'receipt-trigger-after-false': ('blocked', None),
    'receipt-trigger-before-true': ('blocked', None),
    'receipt-xml-mismatch': ('blocked', None),
}


def assert_restore_outcome(flow, state, binding, stop_attempt):
    if state == 'blocked':
        assert 'R4-RESTORE NOT DONE' in flow.stdout and not warden_line(flow).startswith('Warden  : r4 RESTORED'), flow.explain()
        assert not [e for e in flow.runs if e['stage'] == 'RESTORE'], 'blocked: no restore child is started'
    else:
        assert 'R4-RESTORE: r4 restarted' in flow.stdout and warden_line(flow) == RESTORED, flow.explain()
    assert not flow.of('stop-refused') and not flow.of('retarget-refused'), 'every restore call is one the real scripts accept\n' + flow.explain()
    if binding:
        stop = flow.base / f'WardenStop4.2.7-windows-20261011-r5-{stop_attempt}' / 'stop-receipt.json'
        assert json.loads(stop.read_text())['start_binding'] == binding
    assert flow.sitting_end()['outcome'] == 'STOPPED'


@pytest.mark.parametrize('kind', sorted(CUTOVER_STATES))
def test_s11_failure_chooses_the_cutover_restore_for_the_state_reached(tmp_path, kind):
    state, binding = CUTOVER_STATES[kind]
    flow = run_sitting(tmp_path, f"$script:HX.retarget_r5=[Collections.ArrayList]@('{kind}');")
    assert_stopped(flow, 'S11: ')
    expected = cutover_restore('v1', [(RETARGET, '-Target r4 -Attempt v1 -Apply -Start')])[state]
    assert restore_calls(flow) == expected, flow.explain()
    assert_restore_outcome(flow, state, binding, 'v1')
    assert not flow.controls('/health'), 'no health gate after a failed cutover'


def test_r_f1_any_hold_after_run_takes_the_recovery_stop_even_with_a_legacy_record(tmp_path):
    # R-F1: a start-held with held_before_run false is r5-start-interrupted whatever stop_recovery_allowed says; 'blocked'
    # is only a held stop, an unreadable held record or a start receipt failing the two-phase checks. The real stop then
    # refuses a record whose stop_recovery_allowed is false, so the owner gets R4-RESTORE NOT DONE after that attempt.
    flow = run_sitting(tmp_path, "$script:HX.retarget_r5=[Collections.ArrayList]@('held-after-run-legacy');")
    held = json.loads((flow.base / 'WardenRetarget4.2.7-windows-20261011-r5-v1' / 'start-held.json').read_text())
    assert held['held_before_run'] is False and held['stop_recovery_allowed'] is False
    assert_stopped(flow, 'S11: ')
    assert restore_calls(flow) == [(STOP_R5, '-Apply -Attempt v1 -RetargetTarget r5 -RetargetAttempt v1 -RecoverInterruptedStart')], flow.explain()
    assert flow.of('stop-refused') and 'R4-RESTORE NOT DONE' in flow.stdout


def test_s11_run_threw_with_no_instance_restores_before_run_without_a_stop(tmp_path):
    # Required by the deploy fix review: a held start branches on held_before_run, never on run_requested.
    flow = run_sitting(tmp_path, "$script:HX.retarget_r5=[Collections.ArrayList]@('held-run-exception');")
    held = json.loads((flow.base / 'WardenRetarget4.2.7-windows-20261011-r5-v1' / 'start-held.json').read_text())
    assert held['run_requested'] is True and held['run_exception'] and held['held_before_run'] is True and held['stop_recovery_allowed'] is False
    assert_stopped(flow, 'S11: ')
    assert not flow.child_runs(STOP_R5)
    assert restore_calls(flow) == [(RETARGET, '-Target r4 -Attempt v1 -SourceAttempt v1 -Apply -Start')]
    assert warden_line(flow) == RESTORED


# Gemini-fallback retarget (r5 v2 from the stopped r5 v1, stop v1): the same state machine at attempt v2.
FALLBACK_STATES = {
    'held-before-update': ('previous', None),
    'held-readback': ('retarget-held', None),
    'held-readback-unreadable': ('retarget-held', None),
    'held-readback-unapplied': ('previous', None),
    'held-readback-other': ('blocked', None),
    'retarget-interrupted': ('retarget-held', None),
    'retarget-interrupted-unapplied': ('previous', None),
    'held-before-run': ('never-started', None),
    'held-run-exception': ('never-started', None),
    'interrupted': ('interrupted', 'START_INTERRUPTED_HELD'),
    'crashed': ('interrupted', 'START_CRASHED_NO_RECORD'),
    'held-after-gate-trigger': ('interrupted', 'START_HELD_AFTER_HEALTH_GATE'),
    'held-after-run': ('interrupted', 'START_HELD_BEFORE_HEALTH_GATE'),
    'held-unreadable': ('blocked', None),
    'receipt-xml-mismatch': ('blocked', None),
}


@pytest.mark.parametrize('kind', sorted(FALLBACK_STATES))
def test_gemini_fallback_retarget_failure_uses_the_same_cutover_state_machine(tmp_path, kind):
    state, binding = FALLBACK_STATES[kind]
    flow = run_sitting(tmp_path, f"$script:HX.preflight=[Collections.ArrayList]@('failed','ok');$script:HX.retarget_r5=[Collections.ArrayList]@('ok','{kind}');")
    assert_stopped(flow, 'Gemini fallback: ')
    assert [arg(e, '-Attempt') for e in flow.retargets('r5')] == ['v1', 'v2']
    fallback_stop = [(e['child'], ' '.join(e['args'])) for e in flow.runs if e['stage'] == 'FALLBACK' and e['child'] == STOP_R5]
    assert fallback_stop == [(STOP_R5, '-Apply -Attempt v1 -RetargetTarget r5 -RetargetAttempt v1')]
    previous = [(RETARGET, '-Target r4 -Attempt v1 -SourceAttempt v1 -StopAttempt v1 -Apply -Start')]
    expected = cutover_restore('v2', previous)[state]
    assert restore_calls(flow) == expected, flow.explain()
    assert_restore_outcome(flow, state, binding, 'v2')


def test_a_failed_restore_reports_the_pipeline_down_and_the_held_records(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.retarget_r5=[Collections.ArrayList]@('interrupted');$script:HX.retarget_r4=[Collections.ArrayList]@('held-before-run');")
    assert_stopped(flow, 'S11: ')
    assert restore_calls(flow) == cutover_restore('v1', None)['interrupted']
    assert 'R4-RESTORE NOT DONE' in flow.stdout and not warden_line(flow).startswith('Warden  : r4 RESTORED'), flow.explain()
    held = [line.strip() for line in flow.stdout.splitlines() if line.strip().startswith('Held    : ')]
    assert held, flow.explain()
    for path in (flow.base / 'WardenRetarget4.2.7-windows-20261011-r5-v1' / 'start-held.json',
                 flow.base / 'WardenRetarget4.2.7-windows-20261011-r4-v1' / 'start-held.json'):
        assert str(path) in held[-1], held[-1]


def test_a_held_stop_blocks_the_restore(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.health_overrides['components.warden_controller.admission_ready']=$false;$script:HX.stop_r5=[Collections.ArrayList]@('held');")
    assert_stopped(flow, 'S12: the r5 health gate failed')
    assert restore_calls(flow) == [(STOP_R5, '-Apply -Attempt v1 -RetargetTarget r5 -RetargetAttempt v1')], 'no retarget after a held stop'
    assert 'R4-RESTORE NOT DONE' in flow.stdout and not warden_line(flow).startswith('Warden  : r4 RESTORED')
    held = [line for line in flow.stdout.splitlines() if line.strip().startswith('Held    : ')]
    assert held and str(flow.base / 'WardenStop4.2.7-windows-20261011-r5-v1' / 'stop-held.json') in held[-1], flow.explain()


def test_happy_path_binds_the_preview_summary_and_the_start_receipt_to_s1_and_s9(happy):
    install_sha = sha((happy.base / 'Pipeline4.2.7-windows-20261011-r5' / 'install-after.json').read_bytes())
    reads = [e['path'] for e in happy.of('read')]
    summaries = [p for p in reads if p.endswith('preview-summary.json')]
    starts = {p for p in reads if p.endswith('start-receipt.json')}
    assert summaries and json.loads(Path(summaries[-1]).read_text())['install_after_sha256'] == install_sha
    start = happy.base / 'WardenRetarget4.2.7-windows-20261011-r5-v1' / 'start-receipt.json'
    assert starts == {str(start)}, 'S11 reads the start receipt named by the retarget result'
    receipt = json.loads(start.read_text())
    assert receipt['install_after_sha256'] == install_sha and receipt['config_sha256'] == CONTRACT_SHA and receipt['config_mode'] == 'GEMINI_CONTRACT'
    assert happy.receipt('S01')['state']['install_after_sha256'] == install_sha


def test_s10_preview_bound_to_another_installation_restores_r4(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.preview_install_after_tamper=$true;")
    assert_stopped(flow, 'S10: the upgrade preview bound another r5 installation')
    assert not flow.retargets('r5')
    assert restore_calls(flow) == [(RETARGET, '-Target r4 -Attempt v1 -Apply -Start')]


@pytest.mark.parametrize('tamper,why', [
    ('config', 'the started config_sha256'),
    ('install', 'the started runtime install_after_sha256'),
    ('receipt-sha', 'the start receipt bytes differ from receipt_sha256'),
    ('receipt-path', 'the start receipt path is'),
])
def test_s11_start_receipt_not_bound_to_this_sitting_stops_r5_then_restores(tmp_path, tamper, why):
    flow = run_sitting(tmp_path, f"$script:HX.start_tamper=[Collections.ArrayList]@('{tamper}');")
    assert_stopped(flow, 'S11: the r5 start receipt does not bind this sitting: ' + why)
    assert restore_calls(flow) == [(STOP_R5, '-Apply -Attempt v1 -RetargetTarget r5 -RetargetAttempt v1'),
                                   (RETARGET, '-Target r4 -Attempt v1 -SourceAttempt v1 -StopAttempt v1 -Apply -Start')]
    assert not flow.controls('/health'), 'no health gate on an unbound start'


@pytest.mark.parametrize('tamper', ['config', 'install'])
def test_gemini_fallback_start_receipt_not_bound_restores_r4_from_the_fallback_attempt(tmp_path, tamper):
    flow = run_sitting(tmp_path, f"$script:HX.preflight=[Collections.ArrayList]@('failed','ok');$script:HX.start_tamper=[Collections.ArrayList]@('','{tamper}');")
    assert_stopped(flow, 'Gemini fallback: the r5 start receipt does not bind this sitting')
    assert [e['args'][e['args'].index('-Attempt') + 1] for e in flow.retargets('r5')] == ['v1', 'v2']
    assert restore_calls(flow) == [(STOP_R5, '-Apply -Attempt v2 -RetargetTarget r5 -RetargetAttempt v2'),
                                   (RETARGET, '-Target r4 -Attempt v1 -SourceAttempt v2 -StopAttempt v2 -Apply -Start')]
    assert len(flow.controls('/preflight')) == 1, 'no second preflight on an unbound fallback start'


def test_s11_config_mode_mismatch_after_start_stops_r5_then_restores(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.retarget_mode_override='GEMINI_HELD_COMMISSIONED_BYTES';")
    assert_stopped(flow, 'differs from the builder decision')
    assert restore_calls(flow) == [(STOP_R5, '-Apply -Attempt v1 -RetargetTarget r5 -RetargetAttempt v1'),
                                   (RETARGET, '-Target r4 -Attempt v1 -SourceAttempt v1 -StopAttempt v1 -Apply -Start')]


def test_s11_without_docker_stops_before_the_cutover_and_a_rerun_continues(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.docker=[Collections.ArrayList]@($true,$false);")
    assert_stopped(flow, 'The cutover needs the engine')
    assert not flow.retargets() and flow.sitting_end() is None
    assert flow.receipts() == ['S%02d' % n for n in range(0, 11)]
    rerun = run_sitting(tmp_path, "$script:HX.warden.enabled=$false;$script:HX.warden.task_state=1;", run_label='rerun', hex_seed=100)
    assert_succeeded(rerun)
    assert rerun.children() == [RETARGET], 'only the cutover runs again; S1-S10 are skipped by their receipts'
    assert arg(rerun.retargets('r5')[0], '-Config') == str(flow.base / 'WardenConfig4.2.7-windows-20261011-r5-v1' / 'pipeline.json')


S12_FAILURES = {
    # case: (overrides, reason, awaited, rollback stop accepted by the real stop-warden-r5 idle proof)
    'admission_ready_false_ready_true': ("$script:HX.health_overrides['components.warden_controller.admission_ready']=$false;", 'admission_ready is not true', True, True),
    'knowledge_not_ready': ("$script:HX.health_overrides['knowledge.ready']=$false;", 'knowledge is not ready', True, True),
    'wrong_source_root': ("$script:HX.health_overrides['source_root']='C:\\elsewhere\\.venv\\Lib';", 'source_root is', False, False),
    'not_system': ("$script:HX.health_overrides['service_identity']='ansac';", 'service_identity is not SYSTEM', False, False),
    'active_work': ("$script:HX.health_overrides['active']=@('job');", 'active work is present', False, False),
}
NOT_VERIFIED = 'Warden  : r5 RUNNING, NOT VERIFIED (rollback stop refused)'


@pytest.mark.parametrize('case', sorted(S12_FAILURES))
def test_s12_health_gate_failure_stops_r5_then_restores_r4(tmp_path, case):
    overrides, reason, awaited, stoppable = S12_FAILURES[case]
    flow = run_sitting(tmp_path, overrides)
    assert_stopped(flow, 'S12: the r5 health gate failed')
    assert reason in flow.stdout
    waits = flow.waits('S12')
    if awaited:
        assert waits and set(waits) == {10} and sum(waits) <= 130, waits
    else:
        assert waits == [], 'a hard health failure is not polled'
    stop = (STOP_R5, '-Apply -Attempt v1 -RetargetTarget r5 -RetargetAttempt v1')
    if stoppable:
        assert restore_calls(flow) == [stop, (RETARGET, '-Target r4 -Attempt v1 -SourceAttempt v1 -StopAttempt v1 -Apply -Start')]
        assert warden_line(flow) == RESTORED
    else:
        # The real stop-warden-r5 proves the controller idle under the bound SYSTEM identity and r5 root before End: a
        # controller with active work, another identity or another root makes it refuse, so no r4 retarget can follow (F2).
        assert restore_calls(flow) == [stop] and flow.of('stop-refused'), flow.explain()
        assert 'R4-RESTORE NOT DONE' in flow.stdout and warden_line(flow) == NOT_VERIFIED, flow.explain()
        assert 'Reboot  : SAFE' not in flow.stdout
    assert not flow.controls('/preflight')


def test_s12_ignores_the_bare_ready_field(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.health_overrides['components.warden_controller.ready']=$false;", skip_fix_proof=True)
    assert_succeeded(flow)
    assert flow.receipt('S12')['status'] == 'HEALTH_VERIFIED'


def test_s12_reports_routing_holds_without_gating_on_them(tmp_path):
    holds = ("@([ordered]@{scope='provider';resource_key='claude';reason='auth'},"
             "[ordered]@{scope='model';resource_key='gemini-3.8-flash';reason='quota'})")
    flow = run_sitting(tmp_path, f"$script:HX.health_overrides['routing.holds']={holds};", skip_fix_proof=True)
    assert_succeeded(flow)
    assert not flow.waits('S12') and flow.receipt('S12')['status'] == 'HEALTH_VERIFIED', 'holds are not awaited'
    assert 'Holds   : 2 active routing hold(s): provider:claude (auth), model:gemini-3.8-flash (quota) (reported, not gated)' in flow.stdout, flow.explain()


def test_s12_with_no_routing_holds_reports_zero(happy):
    assert 'Holds   : 0 active routing hold(s) (reported, not gated)' in happy.stdout


# ---------------------------------------------------------------------------------------------------------------------
# S13 acceptance

@pytest.mark.parametrize('kind', ['failed', 'wrong-native', 'hold-event'])
def test_s13_gemini_preflight_failure_falls_back_to_the_held_commissioning_config(tmp_path, kind):
    flow = run_sitting(tmp_path, f"$script:HX.preflight=[Collections.ArrayList]@('{kind}','ok');")
    assert_succeeded(flow)
    assert 'Invoke-R5GeminiFallback' in flow.stages()
    fallback = [(e['child'], ' '.join(e['args'])) for e in flow.runs if e['stage'] == 'FALLBACK']
    commissioning = flow.base / 'WardenCommissioning4.2.7-windows-20261007-r3-v1' / 'pipeline.json'
    assert fallback == [(STOP_R5, '-Apply -Attempt v1 -RetargetTarget r5 -RetargetAttempt v1'),
                        (RETARGET, f'-Target r5 -Config {commissioning} -Attempt v2 -SourceAttempt v1 -StopAttempt v1 -Apply -Start')]
    ids = [json.loads(e['data'])['workflow_id'] for e in flow.controls('/preflight')]
    assert len(ids) == 2 and ids[0].endswith('-pf1') and ids[1].endswith('-fb1')
    health_after = [e for e in flow.controls('/health') if e['stage'] == 'FALLBACK']
    assert health_after, 'the S12 gate runs again after the fallback'
    assert (flow.sitting_root() / 'fallback-intent.json').exists()
    assert flow.held_stages() == ['S13'] and 'Gemini  : HELD' in flow.stdout and 'Warden  : r5 RUNNING' in flow.stdout
    assert all(s >= 10 for s in flow.waits('S13') + flow.waits('FALLBACK'))


def test_s13_fallback_preflight_failure_restores_r4_from_the_fallback_attempt(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.preflight=[Collections.ArrayList]@('failed','failed');")
    assert_stopped(flow, 'S13: the acceptance preflight failed')
    assert restore_calls(flow) == [(STOP_R5, '-Apply -Attempt v2 -RetargetTarget r5 -RetargetAttempt v2'),
                                   (RETARGET, '-Target r4 -Attempt v1 -SourceAttempt v2 -StopAttempt v2 -Apply -Start')]


def test_s13_non_gemini_preflight_failure_restores_r4_without_a_fallback(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.preflight=[Collections.ArrayList]@('failed');", gemini='skip')
    assert_stopped(flow, 'S13: the acceptance preflight failed')
    assert 'Invoke-R5GeminiFallback' not in flow.stages()
    assert restore_calls(flow) == [(STOP_R5, '-Apply -Attempt v1 -RetargetTarget r5 -RetargetAttempt v1'),
                                   (RETARGET, '-Target r4 -Attempt v1 -SourceAttempt v1 -StopAttempt v1 -Apply -Start')]


def test_s13_governor_pause_is_waited_out_and_is_not_a_failure(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.admission=[Collections.ArrayList]@(0,0,0,0,2);")
    assert_succeeded(flow)
    assert 'Invoke-R5GeminiFallback' not in flow.stages() and len(flow.controls('/preflight')) == 1
    waits = flow.waits('S13')
    assert waits[:4] == [15, 15, 15, 15] and all(s >= 10 for s in waits)
    s13_health = [e for e in flow.controls('/health') if e['stage'] == 'S13']
    assert len(s13_health) == 5 and s13_health[-1]['seq'] < flow.controls('/preflight')[0]['seq']
    assert 'waiting for admission capacity' in flow.stdout


def test_s13_admission_closed_for_ten_minutes_is_deferred_and_r5_is_kept(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.admission=[Collections.ArrayList]@(0);")
    assert flow.returncode == 0, flow.explain()
    assert not flow.controls('/preflight') and not flow.retargets('r4') and not flow.child_runs(STOP_R5)
    waits = flow.waits('S13')
    assert set(waits) == {15} and 600 <= sum(waits) <= 615, sum(waits)
    assert flow.receipt('S13')['status'] == 'DEFERRED' and flow.receipt('S14')['status'] == 'SKIPPED'
    assert 'not an r5 failure' in flow.stdout and 'Warden  : r5 RUNNING' in flow.stdout


def test_s13_routing_operator_limit_resubmits_once_with_a_new_id(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.preflight=[Collections.ArrayList]@('blocked-limit','ok');")
    assert_succeeded(flow)
    ids = [json.loads(e['data'])['workflow_id'] for e in flow.controls('/preflight')]
    assert len(ids) == 2 and ids[0].endswith('-pf1') and ids[1].endswith('-pf2')
    assert 'Invoke-R5GeminiFallback' not in flow.stages() and 'Gemini  : ACTIVE' in flow.stdout


def test_s13_polls_the_workflow_no_faster_than_every_ten_seconds(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.preflight=[Collections.ArrayList]@('pending','pending','pending','ok');", skip_fix_proof=True)
    assert flow.returncode in (0, 1), flow.explain()
    polls = [e for e in flow.controls() if e['operation'].startswith('/workflow/') and e['stage'] == 'S13']
    assert polls
    waits = flow.waits('S13')
    assert waits and min(waits) >= 10
    poll_seqs = [e['seq'] for e in polls]
    for earlier, later in zip(poll_seqs, poll_seqs[1:]):
        assert any(e['kind'] == 'wait' and earlier < e['seq'] < later and e['seconds'] >= 10 for e in flow.events), 'a wait of >= 10 s between polls'


# ---------------------------------------------------------------------------------------------------------------------
# S14 fix-proof tail

def test_s14_soft_failures_are_recorded_and_never_restore(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.s14_planning='failed';$script:HX.s14_coding='failed';")
    assert_succeeded(flow)
    fix = flow.receipt('S14')['state']['fix_proof']
    assert fix['planning'].startswith('SOFT FAIL') and fix['coding'].startswith('SOFT FAIL')
    assert not flow.child_runs(STOP_R5) and 'SOFT FAIL' in flow.stdout and 'Warden  : r5 RUNNING' in flow.stdout


def test_s14_is_skipped_by_switch(tmp_path):
    flow = run_sitting(tmp_path, skip_fix_proof=True)
    assert_succeeded(flow)
    assert not flow.controls('/submit') and not flow.controls('/coding/submit') and flow.receipt('S14')['status'] == 'SKIPPED'


# ---------------------------------------------------------------------------------------------------------------------
# S0 and S1 stops: nothing changes, no restore

S0_STOPS = {
    'docker_down': ("$script:HX.docker=[Collections.ArrayList]@($false);", 'Docker Desktop engine is not answering'),
    'pypi_unreachable': ("$script:HX.pypi=$false;", 'PyPI (https://pypi.org/simple/) is not reachable'),
    'low_disk': ("$script:HX.disk=2.0;", 'the r5 build needs at least 5 GB'),
    'warden_unreadable': ("$script:HX.warden.readable=$false;$script:HX.warden.error='Access is denied';", 'could not be read'),
    'warden_unknown_source': ("$script:HX.warden.source='unknown';", 'does not run a reviewed r4 action'),
    'port_unknown': ("$script:HX.warden.listening=-1;", 'could not be established'),
    'owner_shell': ("function Assert-R5OwnerShell {Stop-R5Series 'Run this in Windows PowerShell started with \"Run as administrator\" as AETHERDESK\\ansac.'};", 'Run as administrator'),
}


@pytest.mark.parametrize('case', sorted(S0_STOPS))
def test_s0_stops_before_any_child(tmp_path, case):
    overrides, reason = S0_STOPS[case]
    flow = run_sitting(tmp_path, overrides)
    assert_stopped(flow, reason)
    assert flow.runs == [] and not flow.of('prompt')
    assert flow.sitting_end() is None and flow.receipts() == []


def test_s0_freeze_receipt_must_name_the_pinned_manifest(tmp_path):
    flow = run_sitting(tmp_path, freeze_sha='9' * 64)
    assert_stopped(flow, 'freeze receipt does not name the pinned source manifest')
    assert flow.runs == []


def test_s0_pin_drift_stops_before_any_child(tmp_path):
    def tamper(workspace, base):
        with open(workspace / RETARGET, 'ab') as handle:
            handle.write(b'# edited after review\n')
    flow = run_sitting(tmp_path, tamper=tamper)
    assert_stopped(flow, 'Reviewed files differ from the pin table: retarget-warden-r5.ps1 (changed)')
    assert flow.runs == []


def test_s0_placeholder_pin_stops_before_any_child(tmp_path):
    flow = run_sitting(tmp_path, pin_overrides={STAGER: 'MISSING-FILE-NOT-PINNED'})
    assert_stopped(flow, 'stage-pipeline-config-r5-v1.ps1 (placeholder)')
    assert flow.runs == []


def test_pin_mismatch_mid_sitting_stops_before_that_child_runs(tmp_path):
    overrides = ("$hxS8=$script:HXHandlers['agy-isolation-evidence-r4-v1.ps1'];"
                 "$script:HXHandlers['agy-isolation-evidence-r4-v1.ps1']={param($A,$Exe,$Path,$Pre)"
                 "if(HX-Has $A '-StageOnly'){[IO.File]::AppendAllText((Join-Path $script:Workspace 'stage-pipeline-config-r5-v1.ps1'),'# tampered')};& $hxS8 $A $Exe $Path $Pre}.GetNewClosure();")
    flow = run_sitting(tmp_path, overrides)
    assert_stopped(flow, 'Pinned file changed since review: stage-pipeline-config-r5-v1.ps1')
    assert flow.child_runs(BUILDER) and not flow.child_runs(STAGER), 'the tampered stager never starts'
    assert not flow.retargets('r5') and not flow.child_runs(PREVIEW)
    assert flow.of('pin')[-1]['name'] in (STAGER, RETARGET)


S1_STOPS = {
    'plan_holds': ("$script:HX.install_plan_holds=@('Reviewed function source changed');", 'The r5 installer plan reports holds'),
    'plan_exit': ("$script:HX.install_plan_code=1;", 'The r5 installer plan did not run'),
    'install_held': ("$script:HX.install_apply_code=1;", 'failed_stage SYNC'),
    'verified_unchanged_154': ("$script:HX.install_after.verified_unchanged=154;", 'verified_unchanged 154'),
    'tasks_changed': ("$script:HX.install_after.tasks_changed=1;", 'tasks_changed is not 0'),
    'repairs_not_installed': ("$script:HX.install_after.r5_repairs_installed=$false;", 'r5_repairs_installed is not true'),
    'twelve_repairs': ("$script:HX.install_after.repairs=12;", 'reviewed_repairs differ'),
    'repair_pin_differs': ("$script:HX.install_after.pin_tamper=$true;", 'repair pin differs'),
    'install_holds': ("$script:HX.install_after.holds=@('x');", 'holds are present'),
    'wrong_mode': ("$script:HX.install_mode='HELD_PARTIAL';", 'FRESH_STOPPED_RUNTIME_READY'),
}


def warden_line(flow):
    lines = [line.strip() for line in flow.stdout.splitlines() if line.strip().startswith('Warden  : ')]
    assert lines, flow.explain()
    return lines[-1]


@pytest.mark.parametrize('case', sorted(S1_STOPS))
def test_s1_failure_restores_r4_from_todays_r4v1_state(tmp_path, case):
    # Commander decision (2026-10-11): an S1 failure restores r4 (the Warden is down today) with the plain r4-v1 restore call.
    overrides, reason = S1_STOPS[case]
    flow = run_sitting(tmp_path, overrides)
    assert_stopped(flow, reason)
    assert set(flow.children()[:-1]) == {INSTALL} and flow.children()[-1] == RETARGET, 'no S2+ child ran; the restore is the only other child'
    assert restore_calls(flow) == [(RETARGET, '-Target r4 -Attempt v1 -Apply -Start')]
    assert warden_line(flow).startswith('Warden  : r4 RESTORED, r5 not installed: ') and reason in warden_line(flow), warden_line(flow)
    assert flow.sitting_end()['outcome'] == 'STOPPED'


@pytest.mark.parametrize('kind', ['held-before-run', 'refused'])
def test_s1_failure_with_a_failed_restore_reports_the_pipeline_down_and_the_held_records(tmp_path, kind):
    flow = run_sitting(tmp_path, f"$script:HX.install_plan_holds=@('x');$script:HX.retarget_r4=[Collections.ArrayList]@('{kind}');")
    assert_stopped(flow, 'The r5 installer plan reports holds: x')
    assert restore_calls(flow) == [(RETARGET, '-Target r4 -Attempt v1 -Apply -Start')]
    assert 'R4-RESTORE NOT DONE' in flow.stdout and warden_line(flow) == 'Warden  : pipeline DOWN as before this sitting'
    held = [line.strip() for line in flow.stdout.splitlines() if line.strip().startswith('Held    : ')]
    if kind == 'held-before-run':
        assert held and str(flow.base / 'WardenRetarget4.2.7-windows-20261011-r4-v1' / 'start-held.json') in held[-1], flow.explain()
    else:
        assert held == [], 'a refused restore leaves no held record'
    assert flow.sitting_end()['outcome'] == 'STOPPED'


def test_s1_failure_while_r4_runs_leaves_r4_alone(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.warden.instances=1;$script:HX.warden.listening=1;$script:HX.install_plan_holds=@('x');")
    assert_stopped(flow, 'The r5 installer plan reports holds: x')
    assert flow.children() == [INSTALL] and not flow.retargets()
    assert warden_line(flow) == 'Warden  : r4 still running (never stopped)'
    assert flow.sitting_end() is None, 'nothing changed: a rerun stays possible'


def test_s1_install_held_record_is_listed(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.install_apply_code=1;")
    assert_stopped(flow, 'failed_stage SYNC')
    held = [line for line in flow.stdout.splitlines() if line.strip().startswith('Held    : ')]
    assert held and str(flow.base / 'Pipeline4.2.7-windows-20261011-r5' / 'install-held.json') in held[-1], flow.explain()


def test_s1_accepts_an_existing_verified_install_without_rerunning_the_installer(tmp_path):
    flow = run_sitting(tmp_path, "HX-InstallAfter;")
    assert_succeeded(flow)
    assert not flow.child_runs(INSTALL)


# ---------------------------------------------------------------------------------------------------------------------
# Reruns and plan mode

def test_rerun_after_an_interrupted_window_skips_every_stage_whose_receipt_verifies(tmp_path):
    first = run_sitting(tmp_path, "$script:HX.crash_in='login-six-workers-status-first-r4-v1.ps1:gemini';")
    assert first.returncode == 9 and first.of('crash'), first.explain()
    assert first.receipts() == ['S%02d' % n for n in range(0, 6)]
    rerun = run_sitting(tmp_path, "$script:HX.warden.enabled=$false;$script:HX.warden.task_state=1;", run_label='rerun', hex_seed=100)
    assert_succeeded(rerun)
    assert rerun.children()[:1] == [LOGIN] and INSTALL not in rerun.children() and LEAF not in rerun.children()
    assert rerun.children().count(CAPTURE) == 1, 'the signed-out capture is not repeated'
    gx = arg(first.child_runs(CAPTURE)[0], '-Attempt')
    assert arg(rerun.child_runs(LOGIN)[0], '-Attempt') == gx and arg(rerun.child_runs(CAPTURE)[0], '-Attempt') == gx, 'S5 state restored from its receipt'
    assert 'already done by this attempt' in rerun.stdout


def test_rerun_after_a_deployed_sitting_refuses_at_s0(tmp_path):
    first = run_sitting(tmp_path, skip_fix_proof=True)
    assert_succeeded(first)
    rerun = run_sitting(tmp_path, "$script:HX.warden.source='r5';$script:HX.warden.instances=1;$script:HX.warden.listening=1;", run_label='rerun', skip_fix_proof=True)
    assert_stopped(rerun, 'has already ended')
    assert rerun.runs == []


def test_rerun_after_a_restore_refuses_at_s0(tmp_path):
    first = run_sitting(tmp_path, "$script:HX.preview_apply_code=1;")
    assert_stopped(first, 'S10:')
    assert first.sitting_end()['outcome'] == 'STOPPED'
    rerun = run_sitting(tmp_path, "$script:HX.warden.source='r4-restore';$script:HX.warden.source_attempt='v1';", run_label='rerun')
    assert_stopped(rerun, 'has already ended')
    assert rerun.runs == []


def test_rerun_after_an_interrupted_cutover_refuses(tmp_path):
    first = run_sitting(tmp_path, "$script:HX.crash_in='retarget-warden-r5.ps1:';")
    assert first.returncode == 9 and (first.sitting_root() / 'S11-intent.json').exists()
    rerun = run_sitting(tmp_path, "$script:HX.warden.enabled=$false;", run_label='rerun', hex_seed=100)
    assert_stopped(rerun, 'interrupted during the r5 cutover')
    assert rerun.runs == []


def test_plan_mode_without_apply_changes_nothing(tmp_path):
    work, workspace, base, _, _ = prepare(tmp_path)
    before = snapshot(base), snapshot(workspace)
    flow = run_sitting(tmp_path, apply=False)
    assert flow.returncode == 0, flow.explain()
    assert flow.runs == [] and not flow.of('prompt') and not flow.of('attention') and not flow.of('transcript')
    assert (snapshot(base), snapshot(workspace)) == before, 'no file or directory created'
    for text in ('READ-ONLY PLAN', 'pins: ', 'Warden task: source r4-v1', 'S2 runs stop-warden-r4 (disable only)', 'To run it: add -Apply'):
        assert text in flow.stdout, flow.explain()
    assert_clean_trace(flow)


def test_plan_mode_reports_pin_drift_and_still_changes_nothing(tmp_path):
    def tamper(workspace, base):
        (workspace / INSTALL).write_bytes(b'# different\n')
    flow = run_sitting(tmp_path, apply=False, tamper=tamper)
    assert flow.returncode == 0 and flow.runs == []
    assert 'NOT READY - install-stopped-runtime-r5.ps1 (changed)' in flow.stdout, flow.explain()


# ---------------------------------------------------------------------------------------------------------------------
# Re-audit REAUDIT-SITTING (8943de6c): F2 live re-read and outcome, F4 deferred acceptance, F6 pin handles and client
# config, F7 install gate, F8 held records of the onboarding roots.

def reboot_line(flow):
    lines = [line.strip() for line in flow.stdout.splitlines() if line.strip().startswith('Reboot  : ')]
    return lines[-1] if lines else ''


def test_f2_s11_unbound_start_with_a_refused_rollback_reports_r5_running_not_verified(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.start_tamper=[Collections.ArrayList]@('config');$script:HX.stop_r5=[Collections.ArrayList]@('refused');")
    assert_stopped(flow, 'S11: the r5 start receipt does not bind this sitting')
    assert restore_calls(flow) == [(STOP_R5, '-Apply -Attempt v1 -RetargetTarget r5 -RetargetAttempt v1')]
    assert 'R4-RESTORE NOT DONE' in flow.stdout and warden_line(flow) == NOT_VERIFIED, flow.explain()
    assert not reboot_line(flow).startswith('Reboot  : SAFE'), 'SAFE only on DONE with r5 verified'
    assert flow.sitting_end()['state']['r5_running'] is False, 'r5_running is set only after the start-receipt binding passes'
    assert 'S11' not in flow.receipts()


def test_f2_outcome_after_a_stop_rereads_the_live_task_disabled_with_one_instance_is_running(tmp_path):
    # A held start after Run leaves the task disabled with its controller still running; the rollback stop is refused.
    flow = run_sitting(tmp_path, "$script:HX.retarget_r5=[Collections.ArrayList]@('held-after-run');$script:HX.stop_r5=[Collections.ArrayList]@('refused');")
    assert_stopped(flow, 'S11: ')
    assert restore_calls(flow) == [(STOP_R5, '-Apply -Attempt v1 -RetargetTarget r5 -RetargetAttempt v1 -RecoverInterruptedStart')]
    reread = [e for e in flow.of('warden-state') if e['seq'] > flow.of('restore-result')[-1]['seq']]
    assert reread, 'after the STOP the orchestrator re-reads the live task'
    line = warden_line(flow)
    assert line.startswith('Warden  : r5 RUNNING, NOT VERIFIED (') and 'DOWN' not in line, line
    assert not reboot_line(flow).startswith('Reboot  : SAFE')


def test_f2_reboot_safe_only_on_done_with_r5_verified(happy, tmp_path):
    assert reboot_line(happy).startswith('Reboot  : SAFE')
    flow = run_sitting(tmp_path, "$script:HX.preflight=[Collections.ArrayList]@('failed');", gemini='skip')
    assert_stopped(flow, 'S13: the acceptance preflight failed')
    assert not reboot_line(flow).startswith('Reboot  : SAFE')


@pytest.mark.parametrize('case', ['s1_failure', 's12_restored', 's10_restored'])
def test_f2_gemini_default_line_only_when_r5_runs_a_contract_config(tmp_path, case):
    overrides = {'s1_failure': "$script:HX.install_apply_code=1;",
                 's12_restored': "$script:HX.health_overrides['components.warden_controller.admission_ready']=$false;",
                 's10_restored': "$script:HX.preview_apply_code=1;"}[case]
    flow = run_sitting(tmp_path, overrides)
    assert_stopped(flow)
    assert 'Gemini  : CONFIGURED, NOT YET PROVEN' not in flow.stdout, flow.explain()
    assert [line for line in flow.stdout.splitlines() if line.strip().startswith('Gemini  : ')], 'a Gemini line is still printed'


def test_f2_gemini_default_line_when_r5_runs_the_contract_and_acceptance_was_deferred(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.admission=[Collections.ArrayList]@(0);")
    assert flow.returncode == 0 and 'Gemini  : CONFIGURED, NOT YET PROVEN' in flow.stdout, flow.explain()
    assert reboot_line(flow).startswith('Reboot  : SAFE')


@pytest.mark.parametrize('kinds', [('blocked-limit', 'blocked-limit'), ('pending',)])
def test_f4_non_gemini_preflight_blocked_twice_or_timed_out_is_deferred_and_keeps_r5(tmp_path, kinds):
    queue = ','.join(f"'{k}'" for k in kinds)
    flow = run_sitting(tmp_path, f"$script:HX.preflight=[Collections.ArrayList]@({queue});", gemini='skip')
    assert flow.returncode == 0 and 'DONE: the 4.2.7 pipeline runs on r5.' in flow.stdout, flow.explain()
    assert restore_calls(flow) == [] and not flow.child_runs(STOP_R5)
    assert flow.receipt('S13')['status'] == 'DEFERRED' and flow.receipt('S14')['status'] == 'SKIPPED'
    assert 'Accept  : DEFERRED' in flow.stdout and 'Warden  : r5 RUNNING' in flow.stdout
    if kinds == ('pending',):
        assert [e for e in flow.controls() if e['operation'].startswith('/workflow/')]
        assert sum(flow.waits('S13')) <= 300 + 30, 'TIMEOUT after 300 s of polling'


def test_f4_after_the_gemini_fallback_a_blocked_preflight_is_deferred_too(tmp_path):
    flow = run_sitting(tmp_path, "$script:HX.preflight=[Collections.ArrayList]@('failed','blocked-limit','blocked-limit');")
    assert flow.returncode == 0, flow.explain()
    assert 'Invoke-R5GeminiFallback' in flow.stages() and not flow.retargets('r4')
    assert flow.receipt('S13')['status'] == 'DEFERRED' and 'Warden  : r5 RUNNING' in flow.stdout


@pytest.mark.parametrize('kind', ['failed', 'other-provider'])
def test_f4_non_gemini_preflight_failed_or_on_an_unexpected_provider_restores(tmp_path, kind):
    flow = run_sitting(tmp_path, f"$script:HX.preflight=[Collections.ArrayList]@('{kind}');", gemini='skip')
    assert_stopped(flow, 'S13: the acceptance preflight failed')
    assert restore_calls(flow) == [(STOP_R5, '-Apply -Attempt v1 -RetargetTarget r5 -RetargetAttempt v1'),
                                   (RETARGET, '-Target r4 -Attempt v1 -SourceAttempt v1 -StopAttempt v1 -Apply -Start')]


def test_f6_pinned_files_are_write_locked_exactly_while_their_child_runs(happy):
    runs = [e for e in happy.runs if e['script']]
    assert runs and all(e['write_denied'] is True for e in runs), [(e['child'], e['write_denied']) for e in runs if e['write_denied'] is not True]
    for how in ('native', 'attended'):
        assert [e for e in runs if e['how'] == how], how
    assert [e for e in runs if e['child'] == BUILDER], 'the builder run through Invoke-R5Python is locked too'
    leaked = [e for e in happy.of('locks') if e['locked']]
    assert leaked == [], 'a deny-write handle outlived its child: ' + repr(leaked[:3])


def test_f6_the_pin_handle_is_disposed_when_the_launch_throws(tmp_path):
    flow = run_sitting(tmp_path, f"$script:HX.throw_in='{PREVIEW}';")
    assert flow.returncode == 1 and flow.of('launch-throw'), flow.explain()
    thrown = flow.child_runs(PREVIEW)
    assert len(thrown) == 1 and thrown[0]['write_denied'] is True
    leaked = [e for e in flow.of('locks') if e['locked']]
    assert leaked == [], 'the handle of the child whose launch threw stays open: ' + repr(leaked[:3])
    assert flow.of('locks') and flow.of('locks')[-1]['where'].startswith('outcome'), 'probed again at the outcome block'


CONTROL_PROBE = (
    "function HX-ControlProbe {$r=& $script:HXOrigControl '/health';"
    "HX-Trace 'control-probe' @{value=$(if($null -ne $r){HX-Json $r}else{$null});error=[string]$script:R5LastControlError};'probed'};")


@pytest.mark.parametrize('content,ok', [
    ({'port': 47824, 'token_file': TOKEN_FILE}, True),
    ({'port': 47825, 'token_file': TOKEN_FILE}, False),
    ({'port': '47824', 'token_file': TOKEN_FILE}, False),
    ({'port': 47824, 'token_file': 'C:\\Users\\ansac\\CoChem427\\other.token'}, False),
    ({'port': 47824}, False),
    ('not json', False),
    (None, False),
], ids=['valid', 'port-47825', 'port-string', 'other-token-file', 'no-token-file', 'not-json', 'missing'])
def test_f6_invoke_control_trusts_the_client_config_only_for_the_pinned_port_and_token_file(tmp_path, content, ok):
    client = tmp_path / 'work' / 'client' / 'pipeline-client-r3.json'
    client.parent.mkdir(parents=True, exist_ok=True)
    if content is not None:
        client.write_text(content if isinstance(content, str) else json.dumps(content), encoding='ascii')
    else:
        client.write_text('{}', encoding='ascii')  # prepare() keeps an existing file; remove it right before the run
    tamper = (lambda workspace, base: client.unlink()) if content is None else None
    flow = run_sitting(tmp_path, CONTROL_PROBE + "$script:HX.warden.listening=1;", entry='HX-ControlProbe', tamper=tamper)
    probes = flow.of('control-probe')
    assert probes, flow.explain()
    probe = probes[-1]
    pythons = [e for e in flow.runs if e['child'] == 'python.exe']
    if ok:
        assert probe['value'] and json.loads(probe['value'])['probe'] == 'real-control', flow.explain()
        assert len(pythons) == 1 and '-c' in pythons[0]['args'], pythons
    else:
        assert probe['value'] is None and not pythons, 'no ControlClient call with an untrusted client config\n' + flow.explain()
        assert 'client config' in probe['error'].lower(), probe['error']


F7_CASES = {
    'installed_repairs_not_verified': ("$script:HX.install_after.installed_repairs_verified=$false;", 'installed_repairs_verified'),
    'pyvenv_pin': ("$script:HX.install_after.pyvenv_tamper=$true;", 'pyvenv'),
    'venv_python_pin': ("$script:HX.install_after.venv_python_tamper=$true;", 'venv_python'),
}


@pytest.mark.parametrize('case', sorted(F7_CASES))
def test_f7_install_gate_requires_verified_repairs_and_the_venv_pins(tmp_path, case):
    overrides, reason = F7_CASES[case]
    flow = run_sitting(tmp_path, overrides)
    assert_stopped(flow, reason)
    assert flow.children()[-1] == RETARGET and LEAF not in flow.children(), 'S1 stops before S2; the restore follows the Commander decision'


def test_f7_an_install_held_record_beside_a_passing_install_after_fails_the_gate(tmp_path):
    flow = run_sitting(tmp_path, "HX-InstallAfter;HX-WriteJson (Join-Path $script:R5Root 'install-held.json') ([ordered]@{failed_stage='VERIFY';reason='stub'});")
    assert_stopped(flow, 'install-held.json')
    assert not flow.child_runs(INSTALL) and STOP_R4 not in flow.children(), 'the held installation is never accepted or reinstalled'


def first_attempt(flow, child, provider=None):
    runs = [e for e in flow.child_runs(child) if provider is None or arg(e, '-Provider') == provider]
    return arg(runs[0], '-Attempt')


F8_CASES = {
    's3_status_hold': ("$script:HX.sess['claude:slot2']='HOLD';",
                       lambda f: f.base / f'NativeAuthStatusSix4.2.7-windows-20261010-r4-v1-{first_attempt(f, LEAF)}-slot2-claude-before' / 'status-held.json'),
    's3_login_series_held': ("$script:HX.sess['codex:slot4']='ATTENDED_LOGIN_REQUIRED';$script:HX.login_exit.codex=1;",
                             lambda f: f.base / f"NativeAuthSix4.2.7-windows-20261011-r4-v1-{first_attempt(f, LOGIN, 'codex')}-codex" / 'series-held.json'),
    's5_capture_held': ("$script:HX.s5_code=1;",
                        lambda f: f.base / f'AgyCapture4.2.7-windows-20261010-r4-v1-{first_attempt(f, CAPTURE)}-slot1-signed-out' / 'capture-held.json'),
    's6_series_held': ("$script:HX.login_exit.gemini=1;",
                       lambda f: f.base / f'NativeAuthSix4.2.7-windows-20261011-r4-v1-{first_attempt(f, CAPTURE)}-gemini' / 'series-held.json'),
    's7_capture_held': ("$script:HX.s7_code=1;",
                        lambda f: f.base / f'AgyCapture4.2.7-windows-20261010-r4-v1-{first_attempt(f, CAPTURE)}-slot1-signed-in' / 'capture-held.json'),
    's8_isolation_held': ("$script:HX.s8_evidence=10;",
                          lambda f: f.base / f'AgyIsolation4.2.7-windows-20261011-r4-v1-{first_attempt(f, CAPTURE)}' / 'isolation-held.json'),
    's8_stage_held': ("$script:HX.s8_stage=10;",
                      lambda f: f.base / f'AgyIsolation4.2.7-windows-20261011-r4-v1-{first_attempt(f, CAPTURE)}-stage' / 'stage-held.json'),
}


@pytest.mark.parametrize('case', sorted(F8_CASES))
def test_f8_held_records_of_the_onboarding_roots_are_listed(tmp_path, case):
    overrides, expected = F8_CASES[case]
    flow = run_sitting(tmp_path, overrides, skip_fix_proof=True)
    assert_succeeded(flow)
    path = expected(flow)
    assert path.exists(), 'the stub wrote the held record: ' + str(path)
    held = [line.strip() for line in flow.stdout.splitlines() if line.strip().startswith('Held    : ')]
    assert held and str(path) in held[-1], flow.explain()
