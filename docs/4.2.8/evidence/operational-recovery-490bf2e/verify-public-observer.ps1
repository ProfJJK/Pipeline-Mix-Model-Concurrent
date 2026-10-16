$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1') -ErrorAction Stop
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
$script:programFiles='C:\Program Files'
$script:python='C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe'
$inputs=@(
    @('C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent-428-repair\scripts\stage_aetherdesk_427_payloads.ps1',@('Get-LocalPath','Assert-NoReparseAncestors','Assert-ProtectedPath','Initialize-FileIdentity','Open-VerifiedFile')),
    @('C:\Users\ansac\CoChem427\r428-op-launch-865a29b\reviewed_428_launch_helpers.ps1',@('Open-428Pin','Read-428Json')),
    @('C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent-428-repair\scripts\run_operational_428_launch.ps1',@('Get-OpProperty','Get-OpHeldObserverExpected','Read-OpRecoveryRecord','Read-OpObserverSnapshot','Assert-OpObserverRecords','Assert-OpObserverFiles'))
)
foreach($inputFile in $inputs){
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($inputFile[0],[ref]$tokens,[ref]$errors)
    if($errors.Count){throw 'Proof input has a PowerShell parse error.'}
    foreach($name in $inputFile[1]){
        $defs=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object Name -CEQ $name)
        if($defs.Count -ne 1){throw 'Proof function absent or ambiguous.'}
        . ([ScriptBlock]::Create($defs[0].Extent.Text))
    }
}
# Only the imported read-only file/record functions run. All lifecycle, process,
# task and provider inspection ports are forbidden in this ordinary-user replay.
function Get-CimInstance {throw 'Native inventory forbidden in file-only replay.'}
function Invoke-CimMethod {throw 'Native identity calls forbidden in file-only replay.'}
function Start-Process {throw 'Child launch forbidden in file-only replay.'}
function Get-ScheduledTask {throw 'Task inspection forbidden in file-only replay.'}
function New-Object {throw 'COM/lifecycle creation forbidden in file-only replay.'}
Initialize-FileIdentity
$pins=[Collections.Generic.List[IO.Stream]]::new()
$clock=[Diagnostics.Stopwatch]::StartNew()
try{
    $files=Assert-OpObserverFiles $pins
    $expected=Get-OpHeldObserverExpected
    $runtime=Read-OpObserverSnapshot (Join-Path $expected.root 'observation-runtime.json')
    Assert-OpObserverRecords $files.provision $files.config $runtime
    [ordered]@{
        schema='cochem-428-observer-file-record-proof/1'
        status='ACTUAL_PROTECTED_FILES_AND_PUBLIC_RECORDS_VERIFIED'
        source_launcher_sha256=(Get-FileHash -LiteralPath $inputs[2][0] -Algorithm SHA256).Hash.ToLowerInvariant()
        retained_file_count=$pins.Count
        immutable_package_file_count=109
        observer_pid=$runtime.pid
        observer_creation_filetime=$runtime.process_creation_filetime
        observation_only=$files.config.observation_only_contract.all_actuation_disabled
        protected_state_modified=$false
        provider_commands_executed=0
        task_calls_executed=0
        process_identity_calls_executed=0
        task_and_native_process_acceptance='NOT_EXECUTED'
        elapsed_seconds=[Math]::Round($clock.Elapsed.TotalSeconds,3)
    }|ConvertTo-Json -Depth 5
}finally{foreach($pin in $pins){$pin.Dispose()}}
