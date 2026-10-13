#Requires -Version 5.1
<# Owner-only one-shot handle diagnostic. No providers, sign-ins, daemon
   changes or deployment. Existing evidence and completed knowledge survive.
   Without Apply, verifies only this local package and returns its plan. #>
[CmdletBinding()]
param([string]$ManifestSha256,[switch]$Apply)

function Open-AgentDiagnosticFile {
    param([string]$Path,[string]$Hash,$Length,$Handles)
    if($Hash -cnotmatch '^[a-f0-9]{64}$'){throw 'Invalid diagnostic pin.'}
    $stream=[IO.File]::Open($Path,'Open','Read','Read')
    try{
        if($stream.Length -gt 4194304 -or ($null -ne $Length -and $stream.Length -ne $Length)){throw 'Diagnostic input length differs.'}
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$actual=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        if($actual -cne $Hash){throw 'Diagnostic input hash differs.'}
        $stream.Position=0
        $reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true,4096,$true)
        try{$text=$reader.ReadToEnd()}finally{$reader.Dispose()}
        $Handles.Add($stream);$stream=$null
        return $text
    }finally{if($null -ne $stream){$stream.Dispose()}}
}

function Open-AgentDiagnosticPackage {
    param([string]$Directory,[string]$Expected,$Handles)
    $manifest=(Open-AgentDiagnosticFile (Join-Path $Directory 'manifest.json') $Expected $null $Handles)|ConvertFrom-Json
    $required=@('inspect_r6_agent_custody.ps1','diagnose_r6_agent_custody.py','run_r6_system_phase.ps1',
        'install_r6_runtime.ps1','stage_aetherdesk_427_payloads.ps1')
    if($manifest.schema -cne 'cochem-r6-agent-diagnostic-package/1' -or $manifest.host -cne 'AETHERDESK' -or
        $manifest.nonce -cnotmatch '^[a-f0-9]{32}$' -or @($manifest.files).Count -ne $required.Count){throw 'Unexpected diagnostic package.'}
    $pins=@{};$texts=@{}
    foreach($row in @($manifest.files)){
        $name=[string]$row.name
        if($name -cnotin $required -or $pins.ContainsKey($name) -or
            ($row.length -isnot [int] -and $row.length -isnot [long]) -or $row.length -lt 1){throw 'Unexpected or duplicate diagnostic file.'}
        $texts[$name]=Open-AgentDiagnosticFile (Join-Path $Directory $name) $row.sha256 $row.length $Handles
        $pins[$name]=$row
    }
    return @{manifest=$manifest;pins=$pins;texts=$texts}
}

function Get-AgentDiagnosticDefinitions {
    param([string]$Text)
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseInput($Text,[ref]$tokens,[ref]$errors)
    if($errors.Count){throw 'Diagnostic helper parse failed.'}
    foreach($node in $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){
        $node.Extent.Text}
}

function Assert-AgentDiagnosticIdle {
    param($Folder)
    foreach($task in @($Folder.GetTasks(1))){
        if([string]$task.Name -cmatch '^CoChem-4\.2\.7-(R6Acceptance-|R6AgentDiagnostic-|AgySignIn-|NativeAuthStatus-)' -and
            (@($task.GetInstances(0)).Count -gt 0 -or [int]$task.State -in @(2,4))){
            throw 'An acceptance, sign-in or diagnostic task is active; preserve it.'}}
}

function Publish-AgentDiagnostic {
    param([string]$Root,$Report)
    # Only our sanitized report becomes Users-readable. Existing private files
    # and directory permissions are never changed.
    $acl=New-R6PayloadAcl 'source/knowledge/control' $false
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        [Security.Principal.SecurityIdentifier]::new('S-1-5-32-545'),'Read','Allow'))
    $path=Join-Path $Root 'status.json'
    $data=[Text.UTF8Encoding]::new($false).GetBytes(($Report|ConvertTo-Json -Depth 14))
    $stream=[IO.FileStream]::new($path,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,
        [IO.FileShare]::Read,4096,[IO.FileOptions]::None,$acl)
    try{$stream.Write($data,0,$data.Length);$stream.Flush($true)}finally{$stream.Dispose()}
    return $path
}

function Get-AgentDiagnosticFailure {
    param($ErrorRecord,[string]$Phase)
    $allowed=@('RuntimeException','IOException','UnauthorizedAccessException','COMException',
        'InvalidOperationException','ParameterBindingException','PropertyNotFoundException')
    $name=$ErrorRecord.Exception.GetType().Name
    if($name -cnotin $allowed){$name='OtherError'}
    @{schema='cochem-r6-agent-diagnostic-wrapper/1';status='DIAGNOSTIC_HELD';phase=$Phase;
        error_type=$name;hresult=[int]$ErrorRecord.Exception.HResult;line=[int]$ErrorRecord.InvocationInfo.ScriptLineNumber;
        activation_ready=$false;automatic_retry=$false;daemon_tasks_changed=$false;raw_error_published=$false}
}

function Invoke-AgentDiagnosticTask {
    param($Scheduler,$Folder,[string]$Root,[string]$Name)
    $exe=Join-Path $script:targetRoot '.venv\Scripts\python.exe'
    $arguments='-I -B "'+(Join-Path $Root 'diagnose_r6_agent_custody.py')+'"'
    $definition=$Scheduler.NewTask(0)
    $definition.RegistrationInfo.Description='One handle-only RG4 diagnostic; no providers, deployment, triggers or retries.'
    $definition.Principal.UserId='SYSTEM';$definition.Principal.LogonType=5;$definition.Principal.RunLevel=1
    $definition.Settings.Enabled=$false;$definition.Settings.AllowDemandStart=$true;$definition.Settings.MultipleInstances=2
    $definition.Settings.RestartCount=0;$definition.Settings.ExecutionTimeLimit='PT10M'
    $definition.Settings.DisallowStartIfOnBatteries=$false;$definition.Settings.StopIfGoingOnBatteries=$false
    $action=$definition.Actions.Create(0);$action.Path=$exe;$action.Arguments=$arguments;$action.WorkingDirectory=$script:targetRoot
    $task=$Folder.RegisterTaskDefinition($Name,$definition,18,'SYSTEM',$null,5,'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)')
    Assert-R6PhaseTask $task $exe $arguments $script:targetRoot 600 $false
    Assert-AgentDiagnosticIdle $Folder
    $task.Enabled=$true;$task=$Folder.GetTask($Name)
    Assert-R6PhaseTask $task $exe $arguments $script:targetRoot 600 $true
    $requested=[DateTime]::UtcNow
    $null=$task.Run($null)
    $until=$requested.AddSeconds(620);$finished=$false
    do{
        Start-Sleep -Milliseconds 500
        $task=$Folder.GetTask($Name)
        $finished=Test-R6PhaseFinished $task $Root $requested
        if($finished){break}
    }while([DateTime]::UtcNow -lt $until)
    if(-not $finished){throw 'Diagnostic exceeded its bound; preserve its task and files.'}
    $path=Join-Path $Root 'result.json'
    Assert-ProtectedPath $path
    if((Get-Item -LiteralPath $path).Length -gt 131072){throw 'Diagnostic report exceeds bounds.'}
    $report=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json
    if($report.schema -cne 'cochem-r6-agent-diagnostic/1' -or
        $report.status -cnotin @('DIAGNOSTIC_CAPTURED','DIAGNOSTIC_HELD') -or
        $report.manifest_sha256 -cne 'bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4' -or
        $report.candidate_sha256 -cne 'a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288' -or
        $report.activation_ready -ne $false -or $report.provider_commands_executed -ne 0 -or
        $report.existing_state_modified -ne $false -or $report.acceptance_decisions_unchanged -ne $true -or
        ([int]$task.LastTaskResult -ne $(if($report.status -ceq 'DIAGNOSTIC_CAPTURED'){0}else{2}))){
        throw 'Diagnostic result binding differs.'}
    return $report
}

function Invoke-AgentDiagnostic {
    param([string]$Directory,[string]$Hash,[bool]$ApplyRequested)
    $held=[Collections.Generic.List[IO.FileStream]]::new();$leases=@();$root=$null;$created=$false;$phase='package'
    try{
        $package=Open-AgentDiagnosticPackage $Directory $Hash $held
        if(-not $ApplyRequested){
            @{schema='cochem-r6-agent-diagnostic-plan/1';status='READ_ONLY_PACKAGE_VERIFIED';files=$package.pins.Count;
                system_tasks=1;workers_maximum=6;concurrent_workers=1;provider_commands=0;daemon_tasks_changed=$false;
                sign_ins=0;existing_state_modified=$false;deployment_attempted=$false;automatic_retry=$false}|ConvertTo-Json
            return
        }
        $phase='host'
        $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
        if($PSVersionTable.PSEdition -cne 'Desktop' -or -not [Environment]::Is64BitProcess -or
            $env:COMPUTERNAME -cne 'AETHERDESK' -or $identity.Name -cne 'AETHERDESK\ansac' -or
            -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
            throw 'The owner runs this command in 64-bit Administrator Windows PowerShell on AETHERDESK.'}
        foreach($name in @('install_r6_runtime.ps1','run_r6_system_phase.ps1')){
            foreach($f in @(Get-AgentDiagnosticDefinitions $package.texts[$name])){. ([scriptblock]::Create($f))}}
        Set-R6Constants
        foreach($f in @(Import-R6CopyFunctions $Directory)){. ([scriptblock]::Create($f))}
        Initialize-FileIdentity
        foreach($name in @('Global\CoChem427-R7OwnerSitting','Global\CoChem427-R6Launch',
            'Global\CoChem427-R6Acceptance','Global\CoChem427-AgyProfileSignIn')){
            $mutex=[Threading.Mutex]::new($false,$name);$lease=@{mutex=$mutex;owned=$false};$leases+=,$lease
            try{$lease.owned=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{
                $lease.owned=$true;throw 'Previous owner operation ended unexpectedly; preserve its evidence.'}
            if(-not $lease.owned){throw 'Another setup or sign-in console is active.'}}
        $phase='installed_code'
        Write-Host 'Checking protected diagnostic code. R4 stays running; no sign-in or deployment.'
        $null=Assert-R6Tree;Assert-R6Interpreter;Assert-R6NotReferenced
        Assert-ProtectedPath $script:python
        $held.Add((Open-VerifiedFile $script:python $script:pythonPin (Get-Item -LiteralPath $script:python).Length))
        $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect();$folder=$scheduler.GetFolder('\')
        Assert-AgentDiagnosticIdle $folder
        $nonce=$package.manifest.nonce;$root=Join-Path $script:base ('R6AgentDiagnostic427-'+$nonce)
        $name='CoChem-4.2.7-R6AgentDiagnostic-'+$nonce
        if(Test-Path -LiteralPath $root){throw 'Diagnostic namespace already exists; preserve it and do not repeat.'}
        foreach($task in @($folder.GetTasks(1))){if([string]$task.Name -ceq $name){throw 'Diagnostic task already exists; preserve it.'}}
        Assert-ProtectedPath $script:base
        $phase='copy'
        $null=[IO.Directory]::CreateDirectory($root,(New-R6PayloadAcl 'source/knowledge/control' $true));$created=$true
        $pin=$package.pins['diagnose_r6_agent_custody.py']
        Copy-R6Payload ([pscustomobject]@{source=(Join-Path $Directory $pin.name);destination=(Join-Path $root $pin.name);
            relative='source/knowledge/control';sha256=$pin.sha256;length=$pin.length})
        Write-R6PhasePrivate (Join-Path $root 'intent.json') @{schema='cochem-r6-agent-diagnostic-intent/1';
            manifest_sha256=$Hash;helper_sha256=$pin.sha256;task_name=$name;automatic_retry=$false;daemon_tasks_changed=$false}
        $phase='observation';Write-Host 'Recording handle-check stages and Windows result codes; no input is required.'
        $report=Invoke-AgentDiagnosticTask $scheduler $folder $root $name
        $path=Publish-AgentDiagnostic $root $report
        @{schema='cochem-r6-agent-diagnostic-result/1';status=$report.status;report_path=$path;observation=$report;
            daemon_tasks_changed=$false;deployment_attempted=$false;activation_ready=$false}|ConvertTo-Json -Depth 14
    }catch{
        $record=Get-AgentDiagnosticFailure $_ $phase
        if($created){try{$record.report_path=Publish-AgentDiagnostic $root $record}catch{}}
        $record|ConvertTo-Json -Depth 8
        throw
    }finally{
        foreach($lease in $leases){if($lease.owned){$lease.mutex.ReleaseMutex()};$lease.mutex.Dispose()}
        foreach($stream in $held){$stream.Dispose()}
    }
}

$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
Invoke-AgentDiagnostic $PSScriptRoot $ManifestSha256 ([bool]$Apply)
