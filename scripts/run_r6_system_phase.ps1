#Requires -Version 5.1
<# Owner-only one-shot SYSTEM acceptance. Default is read-only.
   No daemon is changed or started. A late failure preserves its task/root.
   The enclosing series pins this script and the installer before invocation. #>
[CmdletBinding()]
param([ValidateSet('auth','knowledge','agent','native','preview')][string]$Phase,
    [string]$ManifestSha256,[string]$CandidateSha256,[string]$InstallerSha256,
    [string]$Attempt,[string]$AuthRecoverySha256,[string]$NativeRetirementSha256,[string]$CustodyAmendmentSha256,[switch]$Apply)

function Import-R6PhaseInstaller {
    param([string]$Hash,[string]$Directory=$PSScriptRoot)
    # AST-imported functions have no script filename. Their caller must supply
    # the reviewed package directory rather than inherit an empty PSScriptRoot.
    $path=Join-Path $Directory 'install_r6_runtime.ps1'
    $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try{
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$actual=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        if($actual -cne $Hash){throw 'R6 installer helper differs from the reviewed pin.'}
        $stream.Position=0;$reader=[IO.StreamReader]::new($stream)
        try{$text=$reader.ReadToEnd()}finally{$reader.Dispose()}
        $tokens=$null;$errors=$null
        $ast=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
        if($errors.Count){throw 'R6 installer helper does not parse.'}
        foreach($node in $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){
            $node.Extent.Text}
    }finally{$stream.Dispose()}
}

function Assert-R6PhaseQuiescence {
    param($Folder)
    foreach($task in @($Folder.GetTasks(1))){
        if([string]$task.Name -clike 'CoChem-4.2.7-R6Acceptance-*' -and
            (@($task.GetInstances(0)).Count -gt 0 -or [int]$task.State -in @(2,4))){
            throw 'A prior R6 acceptance task is still active; preserve it.'}}
    foreach($name in @('CoChem-4.2.7-Warden','CoChem-4.2.7-Supervisor','CoChem-4.2.2-Warden','CoChem-4.2.3-Supervisor')){
        $task=$null
        try{$task=$Folder.GetTask($name)}catch{
            $cause=$_.Exception;while($null -ne $cause.InnerException){$cause=$cause.InnerException}
            if($cause.HResult -ne -2147024894){throw}}
        if($null -ne $task -and ($task.Enabled -or @($task.GetInstances(0)).Count -gt 0 -or [int]$task.State -in @(2,4))){
            throw 'Managed daemons must be disabled and quiescent before acceptance.'}
    }
    $socket=[Net.Sockets.Socket]::new([Net.Sockets.AddressFamily]::InterNetwork,[Net.Sockets.SocketType]::Stream,[Net.Sockets.ProtocolType]::Tcp)
    try{$socket.ExclusiveAddressUse=$true;$socket.Bind([Net.IPEndPoint]::new([Net.IPAddress]::Loopback,47824))}finally{$socket.Dispose()}
}

function Write-R6PhasePrivate {
    param([string]$Path,$Value)
    $stream=[IO.FileStream]::new($Path,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,4096,[IO.FileOptions]::None,(New-R6PayloadAcl 'source/knowledge/control' $false))
    try{$data=[Text.UTF8Encoding]::new($false).GetBytes(($Value|ConvertTo-Json -Depth 12));$stream.Write($data,0,$data.Length);$stream.Flush($true)}finally{$stream.Dispose()}
}

function Assert-R6PhaseTask {
    param($Task,[string]$Executable,[string]$Arguments,[string]$Directory,[int]$Seconds,[bool]$Enabled)
    $definition=$Task.Definition
    if([string]$definition.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or [int]$definition.Principal.LogonType -ne 5 -or
        [int]$definition.Principal.RunLevel -ne 1 -or [int]$definition.Actions.Count -ne 1 -or
        [int]$definition.Triggers.Count -ne 0 -or [int]$definition.Settings.MultipleInstances -ne 2 -or
        [int]$definition.Settings.RestartCount -ne 0 -or -not $definition.Settings.AllowDemandStart -or
        [Xml.XmlConvert]::ToTimeSpan([string]$definition.Settings.ExecutionTimeLimit).TotalSeconds -ne $Seconds -or
        [bool]$Task.Enabled -ne $Enabled -or [bool]$definition.Settings.Enabled -ne $Enabled){throw 'R6 acceptance task settings differ.'}
    $action=$definition.Actions.Item(1)
    if([int]$action.Type -ne 0 -or [string]$action.Path -cne $Executable -or [string]$action.Arguments -cne $Arguments -or
        [string]$action.WorkingDirectory -cne $Directory){throw 'R6 acceptance task action differs.'}
    $acl=[Security.AccessControl.RawSecurityDescriptor]::new($Task.GetSecurityDescriptor(7))
    if($acl.Owner.Value -notin @('S-1-5-18','S-1-5-32-544') -or -not ($acl.ControlFlags -band 4096) -or $acl.DiscretionaryAcl.Count -ne 2){throw 'R6 acceptance task ACL differs.'}
    $seen=@{}
    foreach($ace in $acl.DiscretionaryAcl){
        if([int]$ace.AceType -ne 0 -or [int]$ace.AceFlags -ne 0 -or $ace.AccessMask -ne 2032127 -or
            $ace.SecurityIdentifier.Value -notin @('S-1-5-18','S-1-5-32-544') -or $seen.ContainsKey($ace.SecurityIdentifier.Value)){
            throw 'R6 acceptance task grants unexpected access.'}
        $seen[$ace.SecurityIdentifier.Value]=$true}
}

function Test-R6PhaseFinished {
    param($Task,[string]$Root,[DateTime]$RequestedAt)
    if(@($Task.GetInstances(0)).Count -ne 0 -or [int]$Task.State -in @(2,4)){return $false}
    # A unique task has never run before. Windows can round LastRunTime to
    # seconds; tolerate that precision only after Run returned successfully.
    $ran=([DateTime]$Task.LastRunTime).ToUniversalTime() -ge $RequestedAt.AddSeconds(-2)
    $receipt=(Test-Path -LiteralPath (Join-Path $Root 'result.json')) -or (Test-Path -LiteralPath (Join-Path $Root 'held.json')) -or
        (Test-Path -LiteralPath (Join-Path $Root 'amendment-failure.json'))
    if($ran -and -not $receipt){throw 'R6 acceptance exited without a receipt; preserve its task and logs.'}
    return ($ran -and $receipt)
}

function Invoke-R6PhaseTask {
    param($Scheduler,$Folder,[string]$Name,[string]$Root,[string]$Phase,[string]$ManifestHash,[string]$CandidateHash)
    $seconds=if($Phase -ceq 'native'){3900}elseif($Phase -ceq 'auth'){900}else{600}
    $executable=Join-Path $script:targetRoot '.venv\Scripts\python.exe'
    $arguments='-I -B -m cochem_pipeline.r6_host_acceptance --phase '+$Phase+' --output "'+$Root+'" --manifest-hash '+$ManifestHash+' --candidate-hash '+$CandidateHash
    if($Phase -ceq 'auth' -and $script:AuthRecoverySha256){
        $helper=Join-Path $Root 'r6_auth_recovery.py'
        $source=Join-Path $PSScriptRoot 'r6_auth_recovery.py'
        Copy-R6Payload ([pscustomobject]@{source=$source;destination=$helper;relative='source/knowledge/control';
            sha256=$script:AuthRecoverySha256;length=(Get-Item -LiteralPath $source).Length})
        $arguments='-I -B "'+$helper+'" --output "'+$Root+'" --manifest-hash '+$ManifestHash+' --candidate-hash '+$CandidateHash
    }
    if($Phase -ceq 'native' -and $script:NativeRetirementSha256){
        $helper=Join-Path $Root 'r6_native_retirement.py'
        $source=Join-Path $PSScriptRoot 'r6_native_retirement.py'
        Copy-R6Payload ([pscustomobject]@{source=$source;destination=$helper;relative='source/knowledge/control';
            sha256=$script:NativeRetirementSha256;length=(Get-Item -LiteralPath $source).Length})
        $arguments='-I -B "'+$helper+'" --output "'+$Root+'" --manifest-hash '+$ManifestHash+' --candidate-hash '+$CandidateHash
    }
    if($script:CustodyAmendmentSha256){
        $helper=Join-Path $Root 'r6_custody_amendment.py'
        $source=Join-Path $PSScriptRoot 'r6_custody_amendment.py'
        Copy-R6Payload ([pscustomobject]@{source=$source;destination=$helper;relative='source/knowledge/control';
            sha256=$script:CustodyAmendmentSha256;length=(Get-Item -LiteralPath $source).Length})
        if($Phase -cin @('agent','knowledge')){
            $arguments='-I -B "'+$helper+'" --phase '+$Phase+' --output "'+$Root+'" --manifest-hash '+$ManifestHash+' --candidate-hash '+$CandidateHash}
        $arguments+=' --custody-sha256 '+$script:CustodyAmendmentSha256
    }
    $definition=$Scheduler.NewTask(0)
    $definition.RegistrationInfo.Description='One reviewed R6 '+$Phase+' acceptance; no daemon launch, triggers, retries or automatic cleanup.'
    $definition.Principal.UserId='SYSTEM';$definition.Principal.LogonType=5;$definition.Principal.RunLevel=1
    $definition.Settings.Enabled=$false;$definition.Settings.AllowDemandStart=$true;$definition.Settings.MultipleInstances=2
    $definition.Settings.RestartCount=0;$definition.Settings.ExecutionTimeLimit=[Xml.XmlConvert]::ToString([TimeSpan]::FromSeconds($seconds))
    $definition.Settings.DisallowStartIfOnBatteries=$false;$definition.Settings.StopIfGoingOnBatteries=$false
    $action=$definition.Actions.Create(0);$action.Path=$executable;$action.Arguments=$arguments;$action.WorkingDirectory=$script:targetRoot
    Write-R6PhasePrivate (Join-Path $Root 'intent.json') @{schema='cochem-r6-system-phase-intent/1';phase=$Phase;
        manifest_sha256=$ManifestHash;candidate_sha256=$CandidateHash;task_name=$Name;seconds=$seconds;automatic_retry=$false}
    # 18 = CREATE | DONT_ADD_PRINCIPAL_ACE, preserving the reviewed private DACL.
    $task=$Folder.RegisterTaskDefinition($Name,$definition,18,'SYSTEM',$null,5,'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)')
    Assert-R6PhaseTask $task $executable $arguments $script:targetRoot $seconds $false
    Assert-R6PhaseQuiescence $Folder
    $task.Enabled=$true
    $task=$Folder.GetTask($Name)
    Assert-R6PhaseTask $task $executable $arguments $script:targetRoot $seconds $true
    $requestedAt=[DateTime]::UtcNow
    $instance=$task.Run($null)
    $deadline=[DateTime]::UtcNow.AddSeconds($seconds+20)
    do{
        Start-Sleep -Seconds 2
        $task=$Folder.GetTask($Name)
        # A fast finished task can have no running instance immediately. Task
        # LastRunTime and the unique result/held file identify this one request.
        $finished=Test-R6PhaseFinished $task $Root $requestedAt
        if($finished){break}
    }while([DateTime]::UtcNow -lt $deadline)
    if(-not $finished){throw 'R6 acceptance exceeded its bound; preserve its task/process and evidence.'}
    if([int]$task.LastTaskResult -ne 0 -or (Test-Path -LiteralPath (Join-Path $Root 'held.json'))){
        $diagnostic=Join-Path $Root 'amendment-failure.json'
        if(Test-Path -LiteralPath $diagnostic){
            Assert-ProtectedPath $diagnostic
            if((Get-Item -LiteralPath $diagnostic).Length -le 16384){
                Write-Host (Get-Content -LiteralPath $diagnostic -Raw)}}
        throw 'R6 acceptance held; no automatic retry.'}
    $path=Join-Path $Root 'result.json'
    if((Get-Item -LiteralPath $path).Length -gt 4194304){throw 'R6 acceptance result exceeds bounds.'}
    Assert-ProtectedPath $path
    $result=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json
    if($result.schema -cne 'cochem-r6-system-phase/1' -or $result.phase -cne $Phase -or $result.status -cne 'PHASE_COMPLETED' -or
        $result.manifest_sha256 -cne $ManifestHash -or $result.candidate_sha256 -cne $CandidateHash){throw 'R6 acceptance result binding differs.'}
    [ordered]@{schema='cochem-r6-system-phase-result/1';phase=$Phase;status=$result.status;result=$result.result;
        receipt_path=$path;receipt_sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant();
        task_preserved=$true;activation_ready=$false}
}

function Invoke-R6PhaseMain {
    param([string]$Phase,[string]$ManifestHash,[string]$CandidateHash,[string]$InstallerHash,[string]$Attempt,[bool]$ApplyRequested)
    foreach($value in @($ManifestHash,$CandidateHash,$InstallerHash)){if($value -cnotmatch '^[a-f0-9]{64}$'){throw 'Exact reviewed hashes are required.'}}
    if($script:AuthRecoverySha256 -and ($Phase -cne 'auth' -or $script:AuthRecoverySha256 -cnotmatch '^[a-f0-9]{64}$')){
        throw 'The reviewed recovery helper is restricted to authentication.'}
    if($script:NativeRetirementSha256 -and ($Phase -cne 'native' -or $script:NativeRetirementSha256 -cnotmatch '^[a-f0-9]{64}$' -or
        $ManifestHash -cne 'bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4' -or
        $CandidateHash -cne 'a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288')){
        throw 'Native retirement is restricted to the exact installed R6 native phase.'}
    if($script:CustodyAmendmentSha256 -and ($Phase -cnotin @('agent','knowledge','native') -or
        $script:CustodyAmendmentSha256 -cnotmatch '^[a-f0-9]{64}$' -or
        ($Phase -ceq 'native' -and -not $script:NativeRetirementSha256) -or
        $ManifestHash -cne 'bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4' -or
        $CandidateHash -cne 'a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288')){
        throw 'Custody repair is restricted to the reviewed R6 continuation phases.'}
    if($Phase -notin @('auth','knowledge','agent','native','preview') -or $Attempt -cnotmatch '^[a-f0-9]{32}$'){throw 'A reviewed phase and fresh attempt are required.'}
    if($PSVersionTable.PSEdition -cne 'Desktop' -or -not [Environment]::Is64BitProcess -or $env:COMPUTERNAME -cne 'AETHERDESK'){throw 'Use 64-bit Windows PowerShell 5.1 on AETHERDESK.'}
    if($ApplyRequested){
        $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
        if($identity.Name -cne 'AETHERDESK\ansac' -or -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
            throw 'The owner runs this phase from Administrator PowerShell.'}}
    foreach($definition in @(Import-R6PhaseInstaller $InstallerHash)){. ([scriptblock]::Create($definition))}
    Set-R6Constants
    foreach($definition in @(Import-R6CopyFunctions $PSScriptRoot)){. ([scriptblock]::Create($definition))}
    Initialize-FileIdentity
    $root=Join-Path $script:base ('R6Acceptance4.2.7-windows-20261012-v1-'+$Phase+'-'+$Attempt)
    $name='CoChem-4.2.7-R6Acceptance-'+$Phase+'-'+$Attempt
    if(Test-Path -LiteralPath $root){throw 'Preserve the existing acceptance root.'}
    $s=Open-VerifiedFile (Join-Path $script:targetRoot 'install-manifest.json') $ManifestHash (Get-Item -LiteralPath (Join-Path $script:targetRoot 'install-manifest.json')).Length;$s.Dispose()
    $s=Open-VerifiedFile (Join-Path $script:targetRoot 'pipeline.json') $CandidateHash (Get-Item -LiteralPath (Join-Path $script:targetRoot 'pipeline.json')).Length;$s.Dispose()
    $null=Assert-R6Tree;Assert-R6Interpreter
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect();$folder=$scheduler.GetFolder('\')
    Assert-R6PhaseQuiescence $folder
    if(-not $ApplyRequested){@{status='READ_ONLY_PLAN';phase=$Phase;activation_ready=$false}|ConvertTo-Json;return}
    Assert-ProtectedPath $script:base
    $mutex=[Threading.Mutex]::new($false,'Global\CoChem427-R6Acceptance');$locked=$false;$created=$false
    try{
        try{$locked=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{
            $locked=$true;throw 'Previous acceptance owner exited; review its evidence before another attempt.'}
        if(-not $locked){throw 'Another R6 acceptance phase is active.'}
        Assert-R6PhaseQuiescence $folder
        $directory=[IO.DirectoryInfo]::new($root);$directory.Create((New-R6PayloadAcl 'source/knowledge' $true));$created=$true
        Invoke-R6PhaseTask $scheduler $folder $name $root $Phase $ManifestHash $CandidateHash|ConvertTo-Json -Depth 14
    }
    catch{
        if($created){Write-R6PhasePrivate (Join-Path $root 'wrapper-held.json') @{status='HELD_PRESERVE_PARTIAL';phase=$Phase;
            error_type=$_.Exception.GetType().Name;automatic_retry=$false;activation_ready=$false}}
        throw
    }finally{if($locked){$mutex.ReleaseMutex()};$mutex.Dispose()}
}

$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
Invoke-R6PhaseMain $Phase $ManifestSha256 $CandidateSha256 $InstallerSha256 $Attempt ([bool]$Apply)
