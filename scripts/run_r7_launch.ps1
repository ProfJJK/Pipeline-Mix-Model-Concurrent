#Requires -Version 5.1
<# One owner sitting. Requires a completed, healthy R6 deployment. All later
   phases are noninteractive. No reboot, late login, retry or evidence deletion.
   Engineering sessions may run the default read-only package plan only. #>
[CmdletBinding()]
param([string]$LaunchManifest,[string]$LaunchManifestSha256,[switch]$Apply)

function Open-R7Pin {
    param([string]$Path,[string]$Pin,[long]$Length=-1)
    if($Pin -cnotmatch '^[a-f0-9]{64}$'){throw 'Invalid R7 file pin.'}
    $item=Get-Item -LiteralPath $Path -Force
    if($item.PSIsContainer){throw 'R7 input must be a file.'}
    for($p=$item.Directory;$null -ne $p;$p=$p.Parent){if($p.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'R7 inputs cannot traverse reparse points.'}}
    if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'R7 input cannot be redirected.'}
    if($item.PSIsContainer -or ($Length -ge 0 -and $item.Length -ne $Length)){throw 'R7 input length differs.'}
    $stream=[IO.File]::Open($item.FullName,'Open','Read','Read')
    try{
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$actual=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        if($actual -cne $Pin){throw 'R7 input hash differs.'}
        $stream.Position=0;return $stream
    }catch{$stream.Dispose();throw}
}

function Read-R7Json {
    param([IO.Stream]$Stream)
    if($Stream.Length -gt 4194304){throw 'R7 metadata exceeds bounds.'}
    $reader=[IO.StreamReader]::new($Stream,[Text.Encoding]::UTF8,$true,4096,$true)
    try{($reader.ReadToEnd()|ConvertFrom-Json)}finally{$reader.Dispose();$Stream.Position=0}
}

function Import-R7Installer {
    param([string]$Path)
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if($errors.Count){throw 'R7 installer parser failure.'}
    foreach($node in $ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){$node.Extent.Text}
}

function Assert-R7TaskAcl {
    param($Task)
    $acl=[Security.AccessControl.RawSecurityDescriptor]::new($Task.GetSecurityDescriptor(7))
    if($acl.Owner.Value -notin @('S-1-5-18','S-1-5-32-544') -or $acl.DiscretionaryAcl.Count -lt 2 -or
        -not ($acl.ControlFlags -band [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected)){throw 'Unexpected Warden task owner/ACL.'}
    $seen=@{}
    foreach($ace in $acl.DiscretionaryAcl){
        if([int]$ace.AceType -ne 0 -or [int]$ace.AceFlags -ne 0 -or $ace.AccessMask -ne 2032127 -or
            $ace.SecurityIdentifier.Value -notin @('S-1-5-18','S-1-5-32-544')){throw 'Warden task grants unexpected access.'}
        $seen[$ace.SecurityIdentifier.Value]=$true}
    if(-not $seen.ContainsKey('S-1-5-18') -or -not $seen.ContainsKey('S-1-5-32-544')){throw 'Warden task ACL is incomplete.'}
}

function Get-R7InvariantDefinition {
    param([string]$Xml)
    $doc=[xml]$Xml;$ns=[Xml.XmlNamespaceManager]::new($doc.NameTable);$ns.AddNamespace('t',$doc.DocumentElement.NamespaceURI)
    foreach($xpath in @('/t:Task/t:Settings/t:Enabled','/t:Task/t:Triggers/t:LogonTrigger/t:Enabled',
        '/t:Task/t:Actions/t:Exec/t:Command','/t:Task/t:Actions/t:Exec/t:Arguments','/t:Task/t:Actions/t:Exec/t:WorkingDirectory')){
        foreach($node in @($doc.SelectNodes($xpath,$ns))){$null=$node.ParentNode.RemoveChild($node)}}
    $doc.OuterXml
}

function Assert-R7WardenTask {
    param($Task,[string]$OriginalXml,[string]$Sddl,[string]$Root,[string]$Arguments,[bool]$Enabled,[bool]$TriggerEnabled)
    Assert-R7TaskAcl $Task
    $d=$Task.Definition
    if($Task.GetSecurityDescriptor(7) -cne $Sddl -or (Get-R7InvariantDefinition $Task.Xml) -cne (Get-R7InvariantDefinition $OriginalXml) -or
        $d.Actions.Count -ne 1 -or $d.Actions.Item(1).Type -ne 0 -or $d.Actions.Item(1).Path -cne (Join-Path $Root '.venv\Scripts\python.exe') -or
        $d.Actions.Item(1).Arguments -cne $Arguments -or $d.Actions.Item(1).WorkingDirectory -cne $Root -or
        [bool]$Task.Enabled -ne $Enabled -or [bool]$d.Settings.Enabled -ne $Enabled -or
        $d.Triggers.Count -ne 1 -or [bool]$d.Triggers.Item(1).Enabled -ne $TriggerEnabled){throw 'Warden task readback differs outside the reviewed change.'}
}

function Get-R7Health {
    Invoke-RestMethod -Uri 'http://127.0.0.1:47824/health' -Headers $script:R7Headers -TimeoutSec 10
}

function Assert-R7Health {
    param($Health,[string]$Root)
    if($Health.service_identity -cne 'SYSTEM' -or $Health.source_root -cne (Join-Path $Root '.venv\Lib') -or
        $Health.admission_capacity -lt 1 -or $Health.components.warden_controller.admission_ready -ne $true){
        throw 'Controller identity or admission readiness differs.'}
}

function Assert-R7Idle {
    param($First,$Second,$Operator)
    foreach($row in @($First,$Second)){
        if(@($row.active).Count -or @($row.quarantined_slots.PSObject.Properties).Count -or
            @($row.routing.active_reservations).Count -or @($row.routing.execution_quarantines).Count){throw 'Controller is not idle with verified cleanup.'}}
    foreach($field in @('pid','instance_id','process_started_at')){
        if([string]$First.$field -cne [string]$Second.$field){throw 'Controller changed between idle observations.'}}
    if($Operator.window.jobs_truncated -ne $false -or
        @($Operator.queue|Where-Object{$_.status -cin @('IN_PROGRESS','PENDING','PENDING_RETRY')}).Count){throw 'Job board is not completely idle.'}
}

function Open-R7ProcessProof {
    param($Health,[string]$Root)
    $process=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$Health.pid)
    if($null -eq $process -or $process.ExecutablePath -cne $script:python -or
        ([string]$process.CommandLine).IndexOf('daemon --config "'+(Join-Path $Root 'pipeline.json')+'"',[StringComparison]::Ordinal) -lt 0 -or
        (Invoke-CimMethod -InputObject $process -MethodName GetOwnerSid).Sid -cne 'S-1-5-18'){
        throw 'Controller native identity differs.'}
    $parent=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$process.ParentProcessId)
    if($null -eq $parent -or $parent.ExecutablePath -cne (Join-Path $Root '.venv\Scripts\python.exe') -or
        ([string]$parent.CommandLine).IndexOf('daemon --config "'+(Join-Path $Root 'pipeline.json')+'"',[StringComparison]::Ordinal) -lt 0 -or
        (Invoke-CimMethod -InputObject $parent -MethodName GetOwnerSid).Sid -cne 'S-1-5-18'){
        throw 'Controller launcher identity differs.'}
    $listeners=@(Get-NetTCPConnection -LocalPort 47824 -State Listen -ErrorAction SilentlyContinue)
    if(-not $listeners.Count -or @($listeners|Where-Object{$_.OwningProcess -ne $Health.pid}).Count){throw 'Controller does not own every listener.'}
    $held=[Collections.Generic.List[Diagnostics.Process]]::new()
    try{
        foreach($row in @($process,$parent)){
            $handle=[Diagnostics.Process]::GetProcessById([int]$row.ProcessId);$null=$handle.Handle
            if($handle.HasExited -or [Math]::Abs(($handle.StartTime.ToUniversalTime()-([DateTime]$row.CreationDate).ToUniversalTime()).TotalSeconds) -gt 1){
                $handle.Dispose();throw 'Native process creation identity changed.'}
            $held.Add($handle)}
        return ,$held
    }catch{foreach($handle in $held){$handle.Dispose()};throw}
}

function Assert-R7PortFree {
    if(@(Get-NetTCPConnection -LocalPort 47824 -State Listen -ErrorAction SilentlyContinue).Count){throw 'Controller port is still occupied.'}
    $socket=[Net.Sockets.Socket]::new([Net.Sockets.AddressFamily]::InterNetwork,[Net.Sockets.SocketType]::Stream,[Net.Sockets.ProtocolType]::Tcp)
    try{$socket.ExclusiveAddressUse=$true;$socket.Bind([Net.IPEndPoint]::new([Net.IPAddress]::Loopback,47824))}finally{$socket.Dispose()}
}

function Invoke-R7Migration {
    param($Scheduler,$Folder,[bool]$Rollback)
    Assert-R7PortFree
    $name='CoChem-4.2.7-R7Migration-'+[Guid]::NewGuid().ToString('N')
    $definition=$Scheduler.NewTask(0);$definition.Principal.UserId='SYSTEM';$definition.Principal.LogonType=5;$definition.Principal.RunLevel=1
    $definition.Settings.Enabled=$false;$definition.Settings.AllowDemandStart=$true;$definition.Settings.MultipleInstances=2
    $definition.Settings.RestartCount=0;$definition.Settings.ExecutionTimeLimit='PT15M'
    $action=$definition.Actions.Create(0);$action.Path=Join-Path $script:R7Root '.venv\Scripts\python.exe'
    $action.Arguments='-I -B -m cochem_pipeline.r7_migration'+$(if($Rollback){' --rollback'}else{''});$action.WorkingDirectory=$script:R7Root
    $task=$Folder.RegisterTaskDefinition($name,$definition,18,'SYSTEM',$null,5,'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)')
    Assert-R7TaskAcl $task
    $d=$task.Definition
    if($d.Triggers.Count -ne 0 -or $d.Actions.Count -ne 1 -or $d.Actions.Item(1).Arguments -cne $action.Arguments -or
        $d.Actions.Item(1).Path -cne $action.Path -or $d.Actions.Item(1).WorkingDirectory -cne $action.WorkingDirectory -or
        $d.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or $d.Principal.LogonType -ne 5 -or $d.Principal.RunLevel -ne 1 -or
        $d.Settings.RestartCount -ne 0 -or $d.Settings.MultipleInstances -ne 2 -or -not $d.Settings.AllowDemandStart -or
        [Xml.XmlConvert]::ToTimeSpan($d.Settings.ExecutionTimeLimit).TotalSeconds -ne 900 -or $task.Enabled -or
        $task.GetInstances(0).Count){throw 'Migration task readback differs.'}
    $task.Enabled=$true;$requested=[DateTime]::UtcNow;$null=$task.Run($null);$deadline=$requested.AddMinutes(15)
    $receipt=Join-Path $script:R7Migration $(if($Rollback){'rollback.json'}else{'migration.json'})
    do{
        Start-Sleep -Seconds 2;$task=$Folder.GetTask($name)
        $finished=$task.GetInstances(0).Count -eq 0 -and [int]$task.State -notin @(2,4) -and
            ([DateTime]$task.LastRunTime).ToUniversalTime() -ge $requested.AddSeconds(-2)
        if($finished){break}
    }while([DateTime]::UtcNow -lt $deadline)
    if(-not $finished -or [int]$task.LastTaskResult -ne 0 -or -not (Test-Path -LiteralPath $receipt)){
        $held=Join-Path $script:R7Migration $(if($Rollback){'rollback-held.json'}else{'migration-held.json'})
        if(Test-Path -LiteralPath $held){Get-Content -LiteralPath $held -Raw|Write-Host}
        throw 'SYSTEM migration held; preserve its task and private evidence.'}
    $task.Enabled=$false
    $result=Get-Content -LiteralPath $receipt -Raw|ConvertFrom-Json
    $expected=if($Rollback){'PRE_CUTOVER_DATABASE_RESTORED'}else{'CATALOG_MIGRATION_VERIFIED'}
    Assert-ProtectedPath $receipt
    if($result.status -cne $expected -or $result.backup_preserved -ne $true){throw 'SYSTEM migration receipt differs.'}
    if(-not $Rollback -and ($result.original_rows_preserved -ne $true -or $result.baseline_digest -cne $script:R7BaselineDigest)){
        throw 'SYSTEM migration baseline or preservation differs.'}
    return $result
}

function Wait-R7Health {
    param([string]$Root)
    $deadline=[DateTime]::UtcNow.AddMinutes(20);$first=$null
    do{
        Start-Sleep -Seconds 5
        try{
            $row=Get-R7Health;Assert-R7Health $row $Root
            if($null -ne $first -and $row.pid -eq $first.pid -and $row.instance_id -ceq $first.instance_id){return $row}
            $first=$row
        }catch{$first=$null}
    }while([DateTime]::UtcNow -lt $deadline)
    throw 'Controller health did not verify within its unattended bound.'
}

function Restore-R7BeforeStart {
    param($Scheduler,$Folder,[string]$OriginalXml,[string]$Sddl,[string]$OldRoot,[bool]$MigrationRequested,[bool]$Migrated)
    Assert-R7PortFree
    if($MigrationRequested -and -not $Migrated){throw 'Migration completion is uncertain; preserve the stopped state.'}
    if($Migrated){$null=Invoke-R7Migration $Scheduler $Folder $true}
    $definition=$Scheduler.NewTask(0);$definition.XmlText=$OriginalXml
    $arguments=$definition.Actions.Item(1).Arguments
    $definition.Triggers.Item(1).Enabled=$false;$definition.Settings.Enabled=$true
    $null=$Folder.RegisterTaskDefinition('CoChem-4.2.7-Warden',$definition,20,'SYSTEM',$null,5,$Sddl)
    $task=$Folder.GetTask('CoChem-4.2.7-Warden')
    Assert-R7WardenTask $task $OriginalXml $Sddl $OldRoot $arguments $true $false
    $instance=$task.Run($null);$health=Wait-R7Health $OldRoot;$proof=Open-R7ProcessProof $health $OldRoot
    try{
        $task=$Folder.GetTask('CoChem-4.2.7-Warden')
        if($task.GetInstances(0).Count -ne 1 -or $task.GetInstances(0).Item(1).InstanceGuid -cne $instance.InstanceGuid){throw 'Restored R6 instance differs.'}
        $definition=$task.Definition;$definition.Triggers.Item(1).Enabled=$true
        $null=$Folder.RegisterTaskDefinition('CoChem-4.2.7-Warden',$definition,20,'SYSTEM',$null,5,$Sddl)
        Assert-R7WardenTask ($Folder.GetTask('CoChem-4.2.7-Warden')) $OriginalXml $Sddl $OldRoot $arguments $true $true
    }finally{foreach($p in $proof){$p.Dispose()}}
    'R6_RESTORED_HEALTH_VERIFIED'
}

function Write-R7Status {
    param([string]$Phase,[string]$Status='RUNNING',$Result=$null)
    if(-not $script:R7Sitting){return}
    $saved=$script:targetRoot
    try{
        $script:targetRoot=$script:R7Sitting
        $record=@{schema='cochem-r7-sanitized-status/1';phase=$Phase;status=$Status;utc=[DateTime]::UtcNow.ToString('o');
            result=$Result;late_prompt=$false;full_srs_acceptance=$false}
        Write-R6InstallRecord ('status-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffff')+'-'+[Guid]::NewGuid().ToString('N')+'.json') $record
    }finally{$script:targetRoot=$saved}
}

function Get-R7CompletedR6 {
    param([string]$CandidatePin)
    @(Get-ChildItem -LiteralPath 'C:\Program Files\CoChem' -Directory -Filter 'R6Sitting*'|ForEach-Object{
        $path=Join-Path $_.FullName 'r6-complete.json'
        if(Test-Path -LiteralPath $path){Assert-ProtectedPath $path;Get-Content -LiteralPath $path -Raw|ConvertFrom-Json}}|
        Where-Object{$_.status -ceq 'WARDEN_R6_RUNNING_HEALTH_VERIFIED' -and $_.candidate_sha256 -ceq $CandidatePin})
}

function Invoke-R7Prerequisite {
    param($Manifest,[string]$Directory,[DateTime]$InputDeadline)
    $complete=@(Get-R7CompletedR6 $Manifest.expected_r6_candidate_sha256)
    if($complete.Count -eq 1){return}
    if($complete.Count -gt 1){throw 'Multiple completed R6 records require review; no automatic selection.'}
    $recovery=$Manifest.r6_prerequisite
    if($recovery.directory -cne (Join-Path $Directory 'r6-prerequisite') -or $recovery.input_deadline_inherited -ne $true){throw 'R6 prerequisite package differs.'}
    $handle=Open-R7Pin (Join-Path $recovery.directory 'launch-manifest.json') $recovery.manifest_sha256
    $entry=Open-R7Pin (Join-Path $recovery.directory 'run_r6_launch.ps1') $recovery.entry_sha256
    try{
        Write-Host 'Completing the reviewed pending R6 recovery first. Required sign-ins are allowed only in the initial 20-minute input window.'
        $powershell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $saved=$ErrorActionPreference
        try{
            $ErrorActionPreference='Continue'
            & $powershell -NoProfile -File (Join-Path $recovery.directory 'run_r6_launch.ps1') -LaunchManifest (Join-Path $recovery.directory 'launch-manifest.json') -LaunchManifestSha256 $recovery.manifest_sha256 -OwnerInputDeadlineUtc $InputDeadline.ToString('o') -Apply
            $code=$LASTEXITCODE
        }finally{$ErrorActionPreference=$saved}
        if($null -eq $code -or $code -ne 0){throw 'R6 prerequisite recovery held. No R7 installation or cutover was attempted.'}
    }finally{$entry.Dispose();$handle.Dispose()}
    if(@(Get-R7CompletedR6 $Manifest.expected_r6_candidate_sha256).Count -ne 1){throw 'R6 prerequisite completion did not verify.'}
}

function Invoke-R7Launch {
    param([string]$ManifestPath,[string]$ManifestHash,[bool]$ApplyRequested,[string]$Directory)
    $pins=[Collections.Generic.List[IO.Stream]]::new();$processes=$null;$mutex=$null;$locked=$false;$ownerMutex=$null;$ownerLocked=$false
    $stopped=$false;$stopRequested=$false;$migrationRequested=$false;$migrated=$false;$startRequested=$false;$phase='package'
    $script:R7Root='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261012-r7-v1'
    $old='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261012-r6-v1'
    $script:R7Migration='C:\ProgramData\CoChemPipeline427\private\r7-migration-20261012-v1'
    $script:R7Sitting=$null
    $inputDeadline=[DateTime]::UtcNow.AddMinutes(20)
    $authority='C:\Program Files\CoChem\RoutingCatalog4.2.7';$folder=$null;$original=$null;$originalSddl=$null
    try{
        $pin=Open-R7Pin $ManifestPath $ManifestHash;$pins.Add($pin);$manifest=Read-R7Json $pin
        if((Split-Path -Parent ([IO.Path]::GetFullPath($ManifestPath))) -cne $Directory -or
            $manifest.schema -cne 'cochem-r7-launch-package/1' -or $manifest.host -cne 'AETHERDESK' -or
            @($manifest.files).Count -ne 7 -or $manifest.source_commit -cnotmatch '^[a-f0-9]{40}$' -or
            $manifest.request_id -cnotmatch '^[a-f0-9]{32}$' -or $manifest.baseline_policy_digest -cnotmatch '^[a-f0-9]{64}$' -or
            $manifest.catalog_policy_digest -cnotmatch '^[a-f0-9]{64}$' -or $manifest.late_prompts -ne $false){throw 'R7 launch package identity differs.'}
        $seen=@{}
        foreach($row in @($manifest.files)){
            if($row.name -cnotmatch '^[A-Za-z0-9_.-]+$' -or $seen.ContainsKey($row.name)){throw 'Duplicate/unsafe R7 package input.'}
            $seen[$row.name]=$true;$pins.Add((Open-R7Pin (Join-Path $directory $row.name) $row.sha256 $row.length))}
        foreach($name in @('install_r7_runtime.ps1','stage_aetherdesk_427_payloads.ps1','run_r7_launch.ps1','pipeline.json','install-manifest.json','proposal.json','pointer.json')){
            if(-not $seen.ContainsKey($name)){throw 'Missing reviewed R7 package input.'}}
        $installPath=Join-Path $directory 'install-manifest.json'
        $stream=Open-R7Pin $installPath $manifest.install_manifest_sha256;$pins.Add($stream);$inventory=Read-R7Json $stream
        foreach($text in @(Import-R7Installer (Join-Path $directory 'install_r7_runtime.ps1'))){. ([scriptblock]::Create($text))}
        Set-R6Constants;$null=Get-R6InstallFiles $inventory
        if($inventory.source_commit -cne $manifest.source_commit){throw 'R7 source lineage differs.'}
        foreach($row in @($inventory.files)){$pins.Add((Open-R7Pin $row.source $row.sha256 $row.length))}
        if(-not $ApplyRequested){
            $recovery=$manifest.r6_prerequisite
            if($recovery.directory -cne (Join-Path $Directory 'r6-prerequisite')){throw 'R6 prerequisite directory differs.'}
            $pins.Add((Open-R7Pin (Join-Path $recovery.directory 'launch-manifest.json') $recovery.manifest_sha256))
            $pins.Add((Open-R7Pin (Join-Path $recovery.directory 'run_r6_launch.ps1') $recovery.entry_sha256))
            @{status='R7_LAUNCH_READ_ONLY_PLAN';payload_files=@($inventory.files).Count;maximum_shared_slots=4;
                completes_pending_R6_first=$true;input_window_minutes=20;late_prompts=$false;host_executed=$false}|ConvertTo-Json;return}
        $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
        if($PSVersionTable.PSEdition -cne 'Desktop' -or -not [Environment]::Is64BitProcess -or $env:COMPUTERNAME -cne 'AETHERDESK' -or
            $identity.Name -cne 'AETHERDESK\ansac' -or -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
            throw 'Run once in Administrator Windows PowerShell as AETHERDESK\ansac.'}
        foreach($text in @(Import-R6CopyFunctions $directory)){. ([scriptblock]::Create($text))};Initialize-FileIdentity
        $ownerMutex=[Threading.Mutex]::new($false,'Global\CoChem427-R7OwnerSitting')
        try{$ownerLocked=$ownerMutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$ownerLocked=$true;throw 'An earlier R7 sitting was interrupted; preserve evidence.'}
        if(-not $ownerLocked){throw 'Another R7 sitting is already active.'}
        foreach($path in @($script:R7Root,$script:R7Migration,$authority)){if(Test-Path -LiteralPath $path){throw 'A prior R7 target exists. Preserve it; no automatic repeat.'}}
        $phase='r6_prerequisite'
        Invoke-R7Prerequisite $manifest $Directory $inputDeadline
        $mutex=[Threading.Mutex]::new($false,'Global\CoChem427-R6Launch')
        try{$locked=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$locked=$true;throw 'Earlier deployment was interrupted; preserve evidence.'}
        if(-not $locked){throw 'Another deployment sitting is active.'}
        $script:R7BaselineDigest=$manifest.baseline_policy_digest
        $pins.Add((Open-VerifiedFile $script:python $script:pythonPin (Get-Item -LiteralPath $script:python).Length))
        $phase='preconditions'
        foreach($path in @($script:R7Root,$script:R7Migration,$authority)){if(Test-Path -LiteralPath $path){throw 'A prior R7 target exists. Preserve it; no automatic repeat.'}}
        $stream=Open-R7Pin (Join-Path $old 'pipeline.json') $manifest.expected_r6_candidate_sha256;$pins.Add($stream);$config=Read-R7Json $stream
        Assert-ProtectedPath (Join-Path $old 'pipeline.json')
        $complete=@(Get-R7CompletedR6 $manifest.expected_r6_candidate_sha256)
        if($complete.Count -ne 1){throw 'R6 deployment acceptance must complete before R7. No sign-in or stop was attempted.'}
        $script:targetRoot=$old;$null=Assert-R6Tree;Assert-R6Interpreter;$script:targetRoot=$script:R7Root
        $token=[IO.File]::ReadAllText([string]$config.token_file).Trim();$script:R7Headers=@{Authorization='Bearer '+$token}
        $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect();$folder=$scheduler.GetFolder('\')
        $task=$folder.GetTask('CoChem-4.2.7-Warden');Assert-R7TaskAcl $task
        $action=$task.Definition.Actions.Item(1)
        $expected='-I -B -m cochem_pipeline daemon --config "'+(Join-Path $old 'pipeline.json')+'" --queue-launch-output-root "'+(Join-Path $config.private_root 'queue-launch-r6')+'" --docker-wait-seconds 900'
        if($task.Definition.Actions.Count -ne 1 -or $action.Path -cne (Join-Path $old '.venv\Scripts\python.exe') -or
            $action.Arguments -cne $expected -or $action.WorkingDirectory -cne $old -or
            $task.Definition.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or $task.Definition.Principal.LogonType -ne 5 -or
            $task.Definition.Principal.RunLevel -ne 1 -or $task.Definition.Settings.RestartCount -ne 0 -or
            $task.Definition.Settings.MultipleInstances -ne 2 -or $task.Definition.Triggers.Count -ne 1 -or
            $task.Definition.Triggers.Item(1).Type -ne 9 -or -not $task.Enabled -or $task.GetInstances(0).Count -ne 1){throw 'Live Warden definition differs from completed R6.'}
        $health=Get-R7Health;Assert-R7Health $health $old
        $original=$task.Xml;$originalSddl=$task.GetSecurityDescriptor(7)
        Assert-R7WardenTask $task $original $originalSddl $old $expected $true $true
        $script:R7Sitting='C:\Program Files\CoChem\R7Sitting4.2.7-windows-20261012-'+[Guid]::NewGuid().ToString('N')
        New-ProtectedDirectory $script:R7Sitting
        Write-Host ('Sanitized status reports: '+$script:R7Sitting+'\status-*.json')
        Write-Host 'R6 prerequisites verified. No sign-in is needed. You can walk away; all remaining stages are unattended.' -ForegroundColor Green
        $phase='offline_install';Write-R7Status $phase
        $powershell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $saved=$script:targetRoot
        try{
            $script:targetRoot=$script:R7Sitting
            Invoke-R6Native $powershell @('-NoProfile','-NonInteractive','-File',(Join-Path $directory 'install_r7_runtime.ps1'),
                '-Manifest',$installPath,'-ManifestSha256',$manifest.install_manifest_sha256,'-Apply') 'stopped-install' 900
        }finally{$script:targetRoot=$saved}
        $script:targetRoot=$script:R7Root;$null=Assert-R6Tree;Assert-R6Interpreter
        $phase='idle';Write-R7Status $phase
        $deadline=[DateTime]::UtcNow.AddMinutes(30);$idle=$false
        do{
            try{$first=Get-R7Health;Assert-R7Health $first $old;Start-Sleep -Seconds 5;$second=Get-R7Health;Assert-R7Health $second $old
                $operator=Invoke-RestMethod -Uri 'http://127.0.0.1:47824/operator' -Headers $script:R7Headers -TimeoutSec 10
                Assert-R7Idle $first $second $operator;$idle=$true;break}catch{Start-Sleep -Seconds 10}
        }while([DateTime]::UtcNow -lt $deadline)
        if(-not $idle){throw 'R6 did not become idle within the unattended bound.'}
        $processes=Open-R7ProcessProof $second $old
        $task=$folder.GetTask('CoChem-4.2.7-Warden')
        if($task.Xml -cne $original -or $task.GetSecurityDescriptor(7) -cne $originalSddl){throw 'Warden changed during installation.'}
        Write-R6InstallRecord 'r6-task-before.xml.json' @{xml=$original;sddl=$originalSddl;pid=$second.pid;instance_id=$second.instance_id}
        $phase='stop';Write-R7Status $phase;$stopRequested=$true
        $definition=$task.Definition;$definition.Triggers.Item(1).Enabled=$false
        $null=$folder.RegisterTaskDefinition('CoChem-4.2.7-Warden',$definition,20,'SYSTEM',$null,5,$originalSddl)
        $task=$folder.GetTask('CoChem-4.2.7-Warden')
        Assert-R7WardenTask $task $original $originalSddl $old $expected $true $false
        try{$task.Stop(0)}catch{
            $cause=$_.Exception;while($cause.InnerException){$cause=$cause.InnerException}
            if($cause.HResult -ne -2147216629){throw} # 0x8004130B: verify actual handles below
        }
        $deadline=[DateTime]::UtcNow.AddMinutes(2)
        do{Start-Sleep -Seconds 2;$task=$folder.GetTask('CoChem-4.2.7-Warden')
            $gone=@($processes|Where-Object{-not $_.HasExited}).Count -eq 0
            if($gone -and $task.GetInstances(0).Count -eq 0){break}
        }while([DateTime]::UtcNow -lt $deadline)
        if(-not $gone -or $task.GetInstances(0).Count){throw 'Owned R6 native processes did not exit; preserve running state.'}
        $task.Enabled=$false
        Assert-R7WardenTask $task $original $originalSddl $old $expected $false $false
        Assert-R7PortFree;$stopped=$true
        $phase='migration';Write-R7Status $phase
        Assert-NoReparseAncestors $script:R7Migration
        $null=[IO.Directory]::CreateDirectory($script:R7Migration,(New-R6PayloadAcl 'source/knowledge/control' $true))
        $migrationRequested=$true;$migration=Invoke-R7Migration $scheduler $folder $false;$migrated=$true
        New-ProtectedDirectory $authority
        foreach($copy in @([pscustomobject]@{name='proposal.json';leaf=($manifest.proposal_sha256+'.json')},
            [pscustomobject]@{name='pointer.json';leaf='current-request.json'})){
            $source=Join-Path $directory $copy.name;$destination=Join-Path $authority $copy.leaf
            $pin=(@($manifest.files)|Where-Object{$_.name -ceq $copy.name})[0]
            Copy-VerifiedPayload ([pscustomobject]@{source=$source;destination=$destination;sha256=$pin.sha256;length=$pin.length})}
        $phase='cutover';Write-R7Status $phase
        $task=$folder.GetTask('CoChem-4.2.7-Warden');$definition=$task.Definition
        $action=$definition.Actions.Item(1);$action.Path=Join-Path $script:R7Root '.venv\Scripts\python.exe';$action.WorkingDirectory=$script:R7Root
        $action.Arguments='-I -B -m cochem_pipeline daemon --config "'+(Join-Path $script:R7Root 'pipeline.json')+'" --queue-launch-output-root "'+(Join-Path $config.private_root 'queue-launch-r7')+'" --docker-wait-seconds 900'
        $definition.Settings.Enabled=$true;$definition.Triggers.Item(1).Enabled=$false
        $null=$folder.RegisterTaskDefinition('CoChem-4.2.7-Warden',$definition,20,'SYSTEM',$null,5,$originalSddl)
        $task=$folder.GetTask('CoChem-4.2.7-Warden')
        $newArguments=$action.Arguments
        Assert-R7WardenTask $task $original $originalSddl $script:R7Root $newArguments $true $false
        $startRequested=$true;$instance=$task.Run($null)
        $health=Wait-R7Health $script:R7Root;$proof=Open-R7ProcessProof $health $script:R7Root
        try{
            $task=$folder.GetTask('CoChem-4.2.7-Warden')
            if($task.GetInstances(0).Count -ne 1 -or $task.GetInstances(0).Item(1).InstanceGuid -cne $instance.InstanceGuid){throw 'R7 task instance differs.'}
            $definition=$task.Definition;$definition.Triggers.Item(1).Enabled=$true
            $null=$folder.RegisterTaskDefinition('CoChem-4.2.7-Warden',$definition,20,'SYSTEM',$null,5,$originalSddl)
            Assert-R7WardenTask ($folder.GetTask('CoChem-4.2.7-Warden')) $original $originalSddl $script:R7Root $newArguments $true $true
        }finally{foreach($p in $proof){$p.Dispose()}}
        $phase='catalog_publication';Write-R7Status $phase;$deadline=[DateTime]::UtcNow.AddMinutes(30)
        do{
            Start-Sleep -Seconds 5;$health=Get-R7Health;Assert-R7Health $health $script:R7Root
            $catalog=$health.catalog_activation
            if($catalog.status -cin @('PUBLISHED_IN_CALLER_TRANSACTION','ALREADY_PUBLISHED') -and $catalog.request_id -ceq $manifest.request_id -and
                $catalog.policy_digest -ceq $manifest.catalog_policy_digest){break}
            if($catalog.status -ceq 'HELD'){throw 'R7 catalog control probe held. Preserve the running controller and evidence.'}
        }while([DateTime]::UtcNow -lt $deadline)
        if($catalog.request_id -cne $manifest.request_id -or $catalog.policy_digest -cne $manifest.catalog_policy_digest -or
            $catalog.status -cnotin @('PUBLISHED_IN_CALLER_TRANSACTION','ALREADY_PUBLISHED')){throw 'Catalog publication exceeded its unattended bound.'}
        $record=@{schema='cochem-r7-owner-sitting/1';status='R7_RUNNING_CATALOG_PUBLICATION_VERIFIED';source_commit=$manifest.source_commit;
            launch_manifest_sha256=$ManifestHash;request_id=$manifest.request_id;native_control_probe_verified=$true;
            original_rows_preserved=$migration.original_rows_preserved;backup_preserved=$true;full_srs_acceptance=$false;late_prompt=$false}
        Write-R6InstallRecord 'r7-complete.json' $record;Write-R7Status 'complete' 'COMPLETE' $record;$record|ConvertTo-Json -Depth 6
    }catch{
        $failure=$_;$rollback='NOT_REQUIRED'
        if($stopped -and -not $startRequested){
            try{
                $rollback=Restore-R7BeforeStart $scheduler $folder $original $originalSddl $old $migrationRequested $migrated
            }catch{$rollback='HELD_PRESERVE_STOPPED_OR_RUNNING_STATE'}
        }elseif($stopRequested -or $startRequested){$rollback='HELD_PRESERVE_POSSIBLY_RUNNING_STATE'}
        $record=@{schema='cochem-r7-owner-sitting/1';status='R7_HELD_PRESERVE_EVIDENCE';phase=$phase;error_type=$failure.Exception.GetType().Name;
            rollback=$rollback;automatic_retry=$false;late_prompt=$false;start_requested=$startRequested}
        if(Test-Path -LiteralPath $script:R7Root){try{Write-R6InstallRecord 'r7-held.json' $record}catch{}}
        if($script:R7Sitting){try{Write-R7Status $phase 'HELD' $record}catch{}}
        $record|ConvertTo-Json -Depth 6;throw $failure
    }finally{
        if($null -ne $processes){foreach($p in $processes){$p.Dispose()}}
        foreach($stream in $pins){$stream.Dispose()}
        if($locked){$mutex.ReleaseMutex()};if($null -ne $mutex){$mutex.Dispose()}
        if($ownerLocked){$ownerMutex.ReleaseMutex()};if($null -ne $ownerMutex){$ownerMutex.Dispose()}
        $script:R7Headers=$null
    }
}

$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
Invoke-R7Launch $LaunchManifest $LaunchManifestSha256 ([bool]$Apply) $PSScriptRoot
