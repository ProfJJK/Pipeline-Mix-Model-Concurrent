#Requires -Version 5.1
<# Owner-only restoration after the exact zero-output TUI attempt. Default is
   an inert plan. Apply admits only the inspected terminal bridge/stop hashes,
   then calls the unchanged hash-bound R4 retarget/start implementation once.
   No login, cleanup, receipt replacement, R6/R7 deployment or retry occurs. #>
[CmdletBinding()]
param([switch]$Apply)

function Assert-R4TuiReceipt {
    param($Receipt)
    if($Receipt.schema -cne 'cochem-interactive-agy-login/1' -or $Receipt.slot -cne 'slot1' -or
        $Receipt.nonce -cne '43804e7a8d44457aa9810305923c219f' -or $Receipt.login_mode -cne 'tui' -or
        $Receipt.status -cne 'LOGIN_FAILED_OR_CANCELLED' -or $Receipt.cleanup_verified -ne $true -or
        $Receipt.one_line_submitted -ne $false -or $Receipt.input_closed_marker_written -ne $true -or
        $Receipt.login_commands_executed -ne 1 -or $Receipt.model_jobs_executed -ne 0 -or
        $Receipt.authentication_verified -ne $false -or $Receipt.activation_ready -ne $false -or
        $Receipt.secret_published -ne $false -or $Receipt.native_output_after_input_published -ne $false -or
        $Receipt.native_output_bytes_before_input -ne 0 -or $Receipt.native_output_published_bytes_before_input -ne 0 -or
        $Receipt.failure.phase -cne 'native_wait' -or $Receipt.failure.error_type -cne 'TimeoutError' -or
        $Receipt.helper_sha256 -cne '4074878f100ae59b804c95bd97b3280ccaa09f919ffaa365a3e2c6985045b8d9' -or
        $Receipt.support_sha256 -cne '45681477194d97b144e8ee4505d4364d73d58aaef19c8428c846df642c834839' -or
        $Receipt.native_executable_sha256 -cne '38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741'){
        throw 'The exact terminal zero-output login receipt is not verified; preserve state.'}
}

function Get-R4TuiRestoreArguments {
    @('-Target','r4','-Attempt','v6','-SourceAttempt','v5','-StopAttempt','v5','-Apply','-Start')
}

function Assert-R4TuiRecoveryLock {
    param([bool]$Owned)
    if(-not $Owned){throw 'An earlier deployment console is still running. Do not start another series; preserve its window and output.'}
}

function Get-R4TuiRecoveryPlan {
    @{schema='cochem-r4-after-tui-recovery/1';mode='READ_ONLY_PLAN';target='r4';attempt='v6';source_attempt='v5';stop_attempt='v5';
        provider_commands_executed=0;deployment_attempted=$false;automatic_retry=$false;
        receipt_sha256='dfad79544643ccfbca3653a66024f3e3020fa63ea23f46ce702430da9376b72a'}
}

function Open-R4TuiPinnedText {
    param([string]$Path,[string]$Expected,$Handles)
    if($Expected -cnotmatch '^[a-f0-9]{64}$'){throw 'Recovery requires a digest.'}
    $item=Get-Item -LiteralPath $Path -ErrorAction Stop
    if($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.Length -gt 4194304){
        throw 'Recovery input is not a bounded ordinary file.'}
    $stream=[IO.File]::Open($Path,'Open','Read','Read');$Handles.Add($stream)
    $sha=[Security.Cryptography.SHA256]::Create()
    try{$hash=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
    if($hash -cne $Expected){throw 'Reviewed recovery input changed; preserve it.'}
    $stream.Position=0;$reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true,4096,$true)
    try{return $reader.ReadToEnd()}finally{$reader.Dispose()}
}

function Assert-R4TuiTask {
    param($Task,[string]$Root)
    $definition=$Task.Definition;$actions=@($definition.Actions)
    $arguments='-I -B "'+(Join-Path $Root 'worker_agy_login_bridge_r4_v1.py')+'" --slot slot1 --nonce 43804e7a8d44457aa9810305923c219f --login-mode tui'
    if($Task.Name -cne 'CoChem-4.2.7-InteractiveAgy-r4-slot1-43804e7a8d44457aa9810305923c219f' -or
        $Task.State -ne 3 -or @($Task.GetInstances(0)).Count -ne 0 -or [long]$Task.LastTaskResult -ne 2 -or
        $definition.Principal.UserId -cnotin @('SYSTEM','S-1-5-18') -or $definition.Principal.LogonType -ne 5 -or
        $definition.Principal.RunLevel -ne 1 -or @($definition.Triggers).Count -ne 0 -or $actions.Count -ne 1 -or
        $actions[0].Type -ne 0 -or $actions[0].Path -cne 'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\Scripts\python.exe' -or
        $actions[0].Arguments -cne $arguments -or $actions[0].WorkingDirectory -cne $Root){
        throw 'The reviewed login task is not the exact terminal SYSTEM task.'}
}

function Invoke-R4TuiRecovery {
    param([bool]$ApplyRequested)
    if(-not $ApplyRequested){Get-R4TuiRecoveryPlan|ConvertTo-Json -Compress;return}
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    $principal=[Security.Principal.WindowsPrincipal]::new($identity)
    if($env:COMPUTERNAME -cne 'AETHERDESK' -or $identity.Name -ine 'AETHERDESK\ansac' -or
        -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
        throw 'Only the owner in their Administrator PowerShell window may restore this host.'}
    $handles=[Collections.Generic.List[IO.FileStream]]::new();$leases=@()
    try{
        foreach($name in @('Global\CoChem427-R7OwnerSitting','Global\CoChem427-R6Launch')){
            $mutex=[Threading.Mutex]::new($false,$name);$lease=@{mutex=$mutex;owned=$false};$leases+=,$lease
            try{$lease.owned=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$lease.owned=$true}
            Assert-R4TuiRecoveryLock $lease.owned}
        $base='C:\Program Files\CoChem'
        $root=Join-Path $base 'InteractiveAgy427-r4-slot1-43804e7a8d44457aa9810305923c219f'
        $receipt=Open-R4TuiPinnedText (Join-Path $root 'receipt.json') 'dfad79544643ccfbca3653a66024f3e3020fa63ea23f46ce702430da9376b72a' $handles|ConvertFrom-Json
        Assert-R4TuiReceipt $receipt
        if(Test-Path -LiteralPath (Join-Path $root 'input.once')){throw 'An input packet remains; preserve the session.'}
        $scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$folder=$scheduler.GetFolder('\')
        Assert-R4TuiTask ($folder.GetTask('CoChem-4.2.7-InteractiveAgy-r4-slot1-43804e7a8d44457aa9810305923c219f')) $root
        $null=Open-R4TuiPinnedText (Join-Path $base 'WardenStop4.2.7-windows-20261011-r5-v5\stop-receipt.json') 'f62d79731b2e1d0440f1ed49b6d43334f8ff3ddfc2b1a45ab670a85f0d232d67' $handles
        if(Test-Path -LiteralPath (Join-Path $base 'WardenRetarget4.2.7-windows-20261011-r4-v6')){
            throw 'Fresh recovery v6 already exists; preserve it and do not repeat.'}
        $directory='C:\Users\ansac\CoChem427\r7-bundle-b274974\r6-prerequisite'
        $source=Open-R4TuiPinnedText (Join-Path $directory 'run_r6_launch.ps1') 'd1a389d5ceb1a1cd21d41b7d8aa67139adef08eeecb5d7ddf8e869a7738d9ec0' $handles
        $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors)
        if($errors.Count){throw 'Pinned package reader does not parse.'}
        foreach($node in $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){
            if($node.Name -cin @('Read-R6LaunchManifest','Open-R6LaunchPins')){. ([scriptblock]::Create($node.Extent.Text))}}
        $manifest=Read-R6LaunchManifest (Join-Path $directory 'launch-manifest.json') 'd5e37a6df5299de71f30b9b7d4051c376efac3bace9da5ccc8b6b27865a4c812'
        $pins=Open-R6LaunchPins $manifest $directory $handles
        if($pins['retarget-warden-r5.ps1'] -cne '991703ab10b7bf280fb092ec984e79d1095379070857e7c2859d0a5ba0c0dee7'){
            throw 'The existing reviewed restore implementation differs.'}
        Write-Host 'Reviewed terminal bridge and stopped R4 v5 verified. Restoring R4 once as v6; no sign-in or deployment.'
        $powershell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $saved=$ErrorActionPreference
        try{$ErrorActionPreference='Continue'; & $powershell -NoProfile -NonInteractive -File (Join-Path $directory 'retarget-warden-r5.ps1') @(Get-R4TuiRestoreArguments);$code=$LASTEXITCODE}
        finally{$ErrorActionPreference=$saved}
        if($code -ne 0){throw 'Reviewed restoration held. Preserve its printed evidence; do not rerun or clean up.'}
        @{schema='cochem-r4-after-tui-recovery/1';status='REVIEWED_R4_RESTORE_EXITED_ZERO';target='r4';attempt='v6';
            provider_commands_executed=0;deployment_attempted=$false;automatic_retry=$false}|ConvertTo-Json -Compress
    }finally{
        foreach($stream in $handles){$stream.Dispose()}
        [array]::Reverse($leases)
        foreach($lease in $leases){if($lease.owned){$lease.mutex.ReleaseMutex()};$lease.mutex.Dispose()}
    }
}

$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
Invoke-R4TuiRecovery ([bool]$Apply)
