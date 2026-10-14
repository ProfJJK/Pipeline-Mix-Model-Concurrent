#Requires -Version 5.1
<# Single owner entry point for Pipeline 4.2.8 (`P428-26`).
   All interactive owner input (including any newly needed dedicated repair-profile
   sign-ins and owner approval secret setup) is strictly front-loaded in the first
   20 minutes. After the walk-away boundary, every child is noninteractive.
   No reboot, late login, automatic retry, or evidence deletion is permitted.
   Engineering sessions may run the default read-only package plan only. #>
[CmdletBinding()]
param([string]$LaunchManifest,[string]$LaunchManifestSha256,[switch]$Apply)

function Open-428Pin {
    param([string]$Path,[string]$Pin,[long]$Length=-1)
    if($Pin -cnotmatch '^[a-f0-9]{64}$'){throw 'Invalid 4.2.8 file pin.'}
    $item=Get-Item -LiteralPath $Path -Force
    if($item.PSIsContainer){throw '4.2.8 input must be a file.'}
    for($p=$item.Directory;$null -ne $p;$p=$p.Parent){if($p.Attributes -band [IO.FileAttributes]::ReparsePoint){throw '4.2.8 inputs cannot traverse reparse points.'}}
    if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw '4.2.8 input cannot be redirected.'}
    if($item.PSIsContainer -or ($Length -ge 0 -and $item.Length -ne $Length)){throw '4.2.8 input length differs.'}
    $stream=[IO.File]::Open($item.FullName,'Open','Read','Read')
    try{
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$actual=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        if($actual -cne $Pin){throw '4.2.8 input hash differs.'}
        $stream.Position=0;return $stream
    }catch{$stream.Dispose();throw}
}

function Read-428Json {
    param([IO.Stream]$Stream)
    if($Stream.Length -gt 4194304){throw '4.2.8 metadata exceeds bounds.'}
    $reader=[IO.StreamReader]::new($Stream,[Text.Encoding]::UTF8,$true,4096,$true)
    try{($reader.ReadToEnd()|ConvertFrom-Json)}finally{$reader.Dispose();$Stream.Position=0}
}

function Import-428Installer {
    param([string]$Path)
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if($errors.Count){throw '4.2.8 installer parser failure.'}
    foreach($node in $ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){$node.Extent.Text}
}

function Assert-428TaskAcl {
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

function Get-428InvariantDefinition {
    param([string]$Xml)
    $doc=[xml]$Xml;$ns=[Xml.XmlNamespaceManager]::new($doc.NameTable);$ns.AddNamespace('t',$doc.DocumentElement.NamespaceURI)
    foreach($xpath in @('/t:Task/t:RegistrationInfo/t:Description','/t:Task/t:Settings/t:Enabled',
        '/t:Task/t:Triggers/t:LogonTrigger','/t:Task/t:Triggers/t:LogonTrigger/t:Enabled',
        '/t:Task/t:Actions/t:Exec/t:Command','/t:Task/t:Actions/t:Exec/t:Arguments','/t:Task/t:Actions/t:Exec/t:WorkingDirectory')){
        foreach($node in @($doc.SelectNodes($xpath,$ns))){if($null -ne $node.ParentNode){$null=$node.ParentNode.RemoveChild($node)}}}
    foreach($tr in @($doc.SelectNodes('/t:Task/t:Triggers',$ns))){if(-not $tr.HasChildNodes){$tr.IsEmpty=$true}}
    $doc.OuterXml
}

function Assert-428WardenTask {
    param($Task,[string]$OriginalXml,[string]$Sddl,[string]$Root,[string]$Arguments,[bool]$Enabled,[bool]$TriggerEnabled,[int]$ExpectedTriggers=1)
    Assert-428TaskAcl $Task
    $d=$Task.Definition
    $triggerOk=if($ExpectedTriggers -eq 0){$d.Triggers.Count -eq 0}else{
        $d.Triggers.Count -eq 1 -and [bool]$d.Triggers.Item(1).Enabled -eq $TriggerEnabled}
    if($Task.GetSecurityDescriptor(7) -cne $Sddl -or (Get-428InvariantDefinition $Task.Xml) -cne (Get-428InvariantDefinition $OriginalXml) -or
        $d.Actions.Count -ne 1 -or $d.Actions.Item(1).Type -ne 0 -or $d.Actions.Item(1).Path -cne (Join-Path $Root '.venv\Scripts\python.exe') -or
        $d.Actions.Item(1).Arguments -cne $Arguments -or $d.Actions.Item(1).WorkingDirectory -cne $Root -or
        [bool]$Task.Enabled -ne $Enabled -or [bool]$d.Settings.Enabled -ne $Enabled -or -not $triggerOk){
        throw 'Warden task readback differs outside the reviewed change.'}
}

function Assert-428InputWindow {
    param([DateTime]$StartedUtc,[DateTime]$NowUtc,[string]$OAuthUrl='',[string]$DialogId='')
    $elapsed=($NowUtc.ToUniversalTime()-$StartedUtc.ToUniversalTime()).TotalSeconds
    if($elapsed -lt 0){throw 'Clock skew rejected in owner input window.'}
    if($elapsed -gt 1200){throw 'The 20-minute front-loaded owner input window has expired; late prompts are forbidden.'}
    if($OAuthUrl){
        if($OAuthUrl.Length -gt 2048 -or $OAuthUrl -match '[\s\x00-\x1f]' -or $OAuthUrl -cnotmatch '^https://[^/\s]+/[^\s]*\?.+$'){
            throw 'Invalid or non-HTTPS OAuth URL.'}
        if(-not (Get-Variable -Name Seen428OAuthUrls -Scope Script -ErrorAction SilentlyContinue)){$script:Seen428OAuthUrls=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)}
        if(-not $script:Seen428OAuthUrls.Add($OAuthUrl)){throw 'Stale or replayed OAuth URL rejected.'}
    }
    if($DialogId){
        if($DialogId -cnotmatch '^[A-Za-z0-9_.:-]{4,128}$'){throw 'Invalid owner dialog identifier.'}
        if(-not (Get-Variable -Name Seen428Dialogs -Scope Script -ErrorAction SilentlyContinue)){$script:Seen428Dialogs=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)}
        if(-not $script:Seen428Dialogs.Add($DialogId)){throw 'Replayed owner dialog rejected.'}
    }
    [pscustomobject]@{within_window=$true;elapsed_seconds=[Math]::Round($elapsed,3);late_prompt=$false}
}

function Get-428CompletedBaseline {
    param([string]$CandidatePin,[string]$CoChemRoot='C:\Program Files\CoChem')
    $sitting=@(Get-ChildItem -LiteralPath $CoChemRoot -Directory -Filter 'R*Sitting*' -ErrorAction SilentlyContinue|ForEach-Object{
        foreach($leaf in @('r7-complete.json','r6-complete.json')){
            $path=Join-Path $_.FullName $leaf
            if(Test-Path -LiteralPath $path){Assert-ProtectedPath $path;Get-Content -LiteralPath $path -Raw|ConvertFrom-Json}}}|
        Where-Object{($_.status -ceq 'R7_RUNNING_CATALOG_PUBLICATION_VERIFIED' -or ($_.status -ceq 'WARDEN_R6_RUNNING_HEALTH_VERIFIED' -and $_.candidate_sha256 -ceq $CandidatePin))})
    if($sitting.Count -ge 1){return $sitting}
    $r4Receipt=Join-Path $CoChemRoot 'WardenRetarget4.2.7-windows-20261011-r4-v11\start-receipt.json'
    $r6Install=Join-Path $CoChemRoot 'Pipeline4.2.7-windows-20261012-r6-v1\install-after.json'
    $r6Cfg=Join-Path $CoChemRoot 'Pipeline4.2.7-windows-20261012-r6-v1\pipeline.json'
    if(-not (Test-Path -LiteralPath $r4Receipt) -or -not (Test-Path -LiteralPath $r6Install) -or -not (Test-Path -LiteralPath $r6Cfg)){return @()}
    Assert-ProtectedPath $r4Receipt;Assert-ProtectedPath $r6Install;Assert-ProtectedPath $r6Cfg
    try{$cfgStream=Open-428Pin $r6Cfg $CandidatePin;$cfgStream.Dispose()}catch{return @()}
    $r4=Get-Content -LiteralPath $r4Receipt -Raw|ConvertFrom-Json
    $r6=Get-Content -LiteralPath $r6Install -Raw|ConvertFrom-Json
    $pinnedHold=Join-Path $CoChemRoot 'R6Acceptance4.2.7-windows-20261012-v1-native-47e4889af6284a9fad018142a14d5371'
    $holdDirs=if(Test-Path -LiteralPath $pinnedHold){@(Get-Item -LiteralPath $pinnedHold)}else{
        @(Get-ChildItem -LiteralPath $CoChemRoot -Directory -Filter 'R6Acceptance4.2.7-windows-20261012-v1-native-*' -ErrorAction SilentlyContinue)}
    $holds=@($holdDirs|ForEach-Object{
        $hp=Join-Path $_.FullName 'held.json'
        $nhp=Join-Path $_.FullName 'native\native-held.json'
        if(Test-Path -LiteralPath $nhp){
            Assert-ProtectedPath $hp;Assert-ProtectedPath $nhp
            $hdoc=Get-Content -LiteralPath $hp -Raw|ConvertFrom-Json
            $nhdoc=Get-Content -LiteralPath $nhp -Raw|ConvertFrom-Json
            if($hdoc.phase -ceq 'native' -and $nhdoc.phase -ceq 'target-23' -and $nhdoc.completed -eq 23){$nhdoc}
        }elseif(Test-Path -LiteralPath $hp){
            Assert-ProtectedPath $hp
            $hdoc=Get-Content -LiteralPath $hp -Raw|ConvertFrom-Json
            if($hdoc.status -ceq 'HELD' -and $hdoc.phase -ceq 'target-23'){$hdoc}
        }})
    if($r4.status -ceq 'WARDEN_R4_RESTARTED_HEALTH_VERIFIED' -and
        $r6.status -cin @('STOPPED_RUNTIME_INSTALLED','R6_RUNTIME_INSTALLED_INERT') -and $holds.Count -eq 1){
        return @([pscustomobject]@{
            status='R4_RUNNING_R6_TARGET23_HOLD_BASELINE_VERIFIED';
            candidate_sha256=$CandidatePin;
            r4_root=[string]$r4.runtime_root;
            r6_hold_phase='target-23'
        })
    }
    return @()
}

function Invoke-428FrontLoadedInput {
    param($Manifest,[string]$Directory,[DateTime]$StartedUtc)
    $null=Assert-428InputWindow $StartedUtc ([DateTime]::UtcNow) '' 'front-loaded-preflight'
    $complete=@(Get-428CompletedBaseline $Manifest.expected_previous_candidate_sha256)
    if($complete.Count -lt 1){throw 'Completed R6/R7 baseline record is required before 4.2.8 launch.'}
    if($complete.Count -gt 2){throw 'Multiple ambiguous baseline completion records require review; no automatic selection.'}
    [pscustomobject]@{
        status='FRONT_LOADED_INPUT_VERIFIED';
        repair_profiles=@('repair_claude','repair_codex','repair_agy');
        late_prompt=$false
    }
}

function Start-428AwakeLease {
    if(-not ('CoChem428Awake' -as [type])){
        Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
public static class CoChem428Awake {
    [DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint flags);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
}
'@
    }
    [Threading.Thread]::BeginThreadAffinity()
    try{
        $thread=[CoChem428Awake]::GetCurrentThreadId()
        $previous=[CoChem428Awake]::SetThreadExecutionState([uint32]2147483649) # CONTINUOUS | SYSTEM_REQUIRED
        if($previous -eq 0){throw 'Could not establish the temporary unattended awake request.'}
        return [pscustomobject]@{thread=$thread;previous=$previous}
    }catch{[Threading.Thread]::EndThreadAffinity();throw}
}

function Stop-428AwakeLease {
    param($Lease)
    try{
        if([CoChem428Awake]::GetCurrentThreadId() -ne $Lease.thread){throw 'Awake request thread changed.'}
        $restored=[CoChem428Awake]::SetThreadExecutionState([uint32]$Lease.previous)
        if($restored -eq 0){throw 'Awake request restoration did not verify.'}
    }finally{[Threading.Thread]::EndThreadAffinity()}
}

function Get-428Health {
    Invoke-RestMethod -Uri 'http://127.0.0.1:47824/health' -Headers $script:Headers428 -TimeoutSec 10
}

function Assert-428Health {
    param($Health,[string]$Root,[bool]$AllowPausedAdmission=$false)
    if($Health.service_identity -cne 'SYSTEM' -or $Health.source_root -cne (Join-Path $Root '.venv\Lib')){
        throw 'Controller identity or admission readiness differs.'}
    if(-not $AllowPausedAdmission -and ($Health.admission_capacity -lt 1 -or $Health.components.warden_controller.admission_ready -ne $true)){
        throw 'Controller identity or admission readiness differs.'}
}

function Assert-428Idle {
    param($First,$Second,$Operator)
    foreach($row in @($First,$Second)){
        if(@($row.active).Count -or @($row.quarantined_slots.PSObject.Properties).Count -or
            @($row.routing.active_reservations).Count -or @($row.routing.execution_quarantines).Count){throw 'Controller is not idle with verified cleanup.'}}
    foreach($field in @('pid','instance_id','process_started_at')){
        if([string]$First.$field -cne [string]$Second.$field){throw 'Controller changed between idle observations.'}}
    if($Operator.window.jobs_truncated -ne $false -or
        @($Operator.queue|Where-Object{$_.status -cin @('IN_PROGRESS','PENDING','PENDING_RETRY')}).Count){throw 'Job board is not completely idle.'}
}

function Open-428ProcessProof {
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

function Assert-428PortFree {
    if(@(Get-NetTCPConnection -LocalPort 47824 -State Listen -ErrorAction SilentlyContinue).Count){throw 'Controller port is still occupied.'}
    $socket=[Net.Sockets.Socket]::new([Net.Sockets.AddressFamily]::InterNetwork,[Net.Sockets.SocketType]::Stream,[Net.Sockets.ProtocolType]::Tcp)
    try{$socket.ExclusiveAddressUse=$true;$socket.Bind([Net.IPEndPoint]::new([Net.IPAddress]::Loopback,47824))}finally{$socket.Dispose()}
}

function Invoke-428Migration {
    param($Scheduler,$Folder,[bool]$Rollback)
    Assert-428PortFree
    $name='CoChem-4.2.8-Migration-'+[Guid]::NewGuid().ToString('N')
    $definition=$Scheduler.NewTask(0);$definition.Principal.UserId='SYSTEM';$definition.Principal.LogonType=5;$definition.Principal.RunLevel=1
    $definition.Settings.Enabled=$false;$definition.Settings.AllowDemandStart=$true;$definition.Settings.MultipleInstances=2
    $definition.Settings.RestartCount=0;$definition.Settings.ExecutionTimeLimit='PT15M'
    $action=$definition.Actions.Create(0);$action.Path=Join-Path $script:Root428 '.venv\Scripts\python.exe'
    $action.Arguments='-I -B -m cochem_pipeline.migration_428 --state-root "C:\ProgramData\CoChemPipeline427\state" --evidence-root "'+$script:Migration428+'" --candidate-config "'+(Join-Path $script:Root428 'pipeline.json')+'"'+$(if($Rollback){' --rollback'}else{''})
    $action.WorkingDirectory=$script:Root428
    $task=$Folder.RegisterTaskDefinition($name,$definition,18,'SYSTEM',$null,5,'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)')
    Assert-428TaskAcl $task
    $d=$task.Definition
    if($d.Triggers.Count -ne 0 -or $d.Actions.Count -ne 1 -or $d.Actions.Item(1).Arguments -cne $action.Arguments -or
        $d.Actions.Item(1).Path -cne $action.Path -or $d.Actions.Item(1).WorkingDirectory -cne $action.WorkingDirectory -or
        $d.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or $d.Principal.LogonType -ne 5 -or $d.Principal.RunLevel -ne 1 -or
        $d.Settings.RestartCount -ne 0 -or $d.Settings.MultipleInstances -ne 2 -or -not $d.Settings.AllowDemandStart -or
        [Xml.XmlConvert]::ToTimeSpan($d.Settings.ExecutionTimeLimit).TotalSeconds -ne 900 -or $task.Enabled -or
        $task.GetInstances(0).Count){throw 'Migration task readback differs.'}
    $task.Enabled=$true;$requested=[DateTime]::UtcNow;$null=$task.Run($null);$deadline=$requested.AddMinutes(15)
    $receipt=Join-Path $script:Migration428 $(if($Rollback){'rollback-428.json'}else{'migration-428.json'})
    do{
        Start-Sleep -Seconds 2;$task=$Folder.GetTask($name)
        $finished=$task.GetInstances(0).Count -eq 0 -and [int]$task.State -notin @(2,4) -and
            ([DateTime]$task.LastRunTime).ToUniversalTime() -ge $requested.AddSeconds(-2)
        if($finished){break}
    }while([DateTime]::UtcNow -lt $deadline)
    if(-not $finished -or [int]$task.LastTaskResult -ne 0 -or -not (Test-Path -LiteralPath $receipt)){
        throw 'SYSTEM 4.2.8 migration held; preserve its task and private evidence.'}
    $task.Enabled=$false
    $result=Get-Content -LiteralPath $receipt -Raw|ConvertFrom-Json
    $expected=if($Rollback){'PRE_CUTOVER_DATABASE_RESTORED'}else{'MIGRATION_428_VERIFIED'}
    Assert-ProtectedPath $receipt
    if($result.status -cne $expected -or $result.backup_preserved -ne $true){throw 'SYSTEM 4.2.8 migration receipt differs.'}
    return $result
}

function Wait-428Health {
    param([string]$Root,[bool]$AllowPausedAdmission=$false)
    $deadline=[DateTime]::UtcNow.AddMinutes(20);$first=$null
    do{
        Start-Sleep -Seconds 5
        try{
            $row=Get-428Health;Assert-428Health $row $Root $AllowPausedAdmission
            if($null -ne $first -and $row.pid -eq $first.pid -and $row.instance_id -ceq $first.instance_id){return $row}
            $first=$row
        }catch{$first=$null}
    }while([DateTime]::UtcNow -lt $deadline)
    throw 'Controller health did not verify within its unattended bound.'
}

function Restore-428BeforeStart {
    param($Scheduler,$Folder,[string]$OriginalXml,[string]$Sddl,[string]$OldRoot,[bool]$MigrationRequested,[bool]$Migrated)
    Assert-428PortFree
    if($MigrationRequested -and -not $Migrated){throw 'Migration completion is uncertain; preserve the stopped state.'}
    if($Migrated){$null=Invoke-428Migration $Scheduler $Folder $true}
    $definition=$Scheduler.NewTask(0);$definition.XmlText=$OriginalXml
    $arguments=$definition.Actions.Item(1).Arguments
    $triggerCount=if($null -ne $definition.Triggers.PSObject.Properties['Count']){[int]$definition.Triggers.Count}else{1}
    if($triggerCount -ge 1){$definition.Triggers.Item(1).Enabled=$false}
    $definition.Settings.Enabled=$true
    $null=$Folder.RegisterTaskDefinition('CoChem-4.2.7-Warden',$definition,20,'SYSTEM',$null,5,$Sddl)
    $task=$Folder.GetTask('CoChem-4.2.7-Warden')
    if($triggerCount -eq 0){
        Assert-428WardenTask $task $OriginalXml $Sddl $OldRoot $arguments $true $false 0
    }else{
        Assert-428WardenTask $task $OriginalXml $Sddl $OldRoot $arguments $true $false
    }
    $allowPaused=($OldRoot -ceq 'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4')
    $instance=$task.Run($null)
    $health=if($allowPaused){Wait-428Health $OldRoot $true}else{Wait-428Health $OldRoot}
    $proof=Open-428ProcessProof $health $OldRoot
    try{
        $task=$Folder.GetTask('CoChem-4.2.7-Warden')
        if($task.GetInstances(0).Count -ne 1 -or $task.GetInstances(0).Item(1).InstanceGuid -cne $instance.InstanceGuid){throw 'Restored previous runtime instance differs.'}
        if($triggerCount -ge 1){
            $definition=$task.Definition;$definition.Triggers.Item(1).Enabled=$true
            $null=$Folder.RegisterTaskDefinition('CoChem-4.2.7-Warden',$definition,20,'SYSTEM',$null,5,$Sddl)
            Assert-428WardenTask ($Folder.GetTask('CoChem-4.2.7-Warden')) $OriginalXml $Sddl $OldRoot $arguments $true $true
        }else{
            Assert-428WardenTask ($Folder.GetTask('CoChem-4.2.7-Warden')) $OriginalXml $Sddl $OldRoot $arguments $true $false 0
        }
    }finally{foreach($p in $proof){$p.Dispose()}}
    'PREVIOUS_RUNTIME_RESTORED_HEALTH_VERIFIED'
}

function Write-428Status {
    param([string]$Phase,[string]$Status='RUNNING',$Result=$null)
    if(-not $script:Sitting428){return}
    $saved=$script:targetRoot
    try{
        $script:targetRoot=$script:Sitting428
        $record=@{schema='cochem-428-sanitized-status/1';version='4.2.8';phase=$Phase;status=$Status;
            utc=[DateTime]::UtcNow.ToString('o');result=$Result;late_prompt=$false;full_srs_acceptance=$false}
        Write-428InstallRecord ('status-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffff')+'-'+[Guid]::NewGuid().ToString('N')+'.json') $record
    }finally{$script:targetRoot=$saved}
}

function Invoke-428SequenceStep {
    param([string]$Phase,[scriptblock]$Action)
    $script:Phase428=$Phase
    Write-428Status $Phase 'RUNNING'
    & $Action
}

function Invoke-428Launch {
    param([string]$ManifestPath,[string]$ManifestHash,[bool]$ApplyRequested,[string]$Directory)
    $pins=[Collections.Generic.List[IO.Stream]]::new();$processes=$null;$mutex=$null;$locked=$false;$ownerMutex=$null;$ownerLocked=$false;$awake=$null
    $stopped=$false;$stopRequested=$false;$migrationRequested=$false;$migrated=$false;$startRequested=$false;$phase='package'
    $script:Root428='C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r1'
    $oldR7='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261012-r7-v1'
    $oldR6='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261012-r6-v1'
    $oldR4='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4'
    $script:Migration428='C:\ProgramData\CoChemPipeline427\private\migration-428-20261014-v1'
    $script:Sitting428=$null
    $startedUtc=[DateTime]::UtcNow
    $authority='C:\Program Files\CoChem\RoutingCatalog4.2.8';$folder=$null;$original=$null;$originalSddl=$null;$old=$null
    try{
        $pin=Open-428Pin $ManifestPath $ManifestHash;$pins.Add($pin);$manifest=Read-428Json $pin
        if((Split-Path -Parent ([IO.Path]::GetFullPath($ManifestPath))) -cne $Directory -or
            $manifest.schema -cne 'cochem-428-launch-package/1' -or $manifest.host -cne 'AETHERDESK' -or
            $manifest.version -cne '4.2.8' -or @($manifest.files).Count -lt 8 -or
            $manifest.source_commit -cnotmatch '^[a-f0-9]{40}$' -or
            $manifest.request_id -cnotmatch '^[a-f0-9]{32}$' -or
            $manifest.baseline_policy_digest -cnotmatch '^[a-f0-9]{64}$' -or
            $manifest.catalog_policy_digest -cnotmatch '^[a-f0-9]{64}$' -or
            $manifest.late_prompts -ne $false -or $manifest.input_window_minutes -ne 20){
            throw '4.2.8 launch package identity differs.'}
        $seen=@{}
        foreach($row in @($manifest.files)){
            if($row.name -cnotmatch '^[A-Za-z0-9_.-]+$' -or $seen.ContainsKey($row.name)){throw 'Duplicate/unsafe 4.2.8 package input.'}
            $seen[$row.name]=$true;$pins.Add((Open-428Pin (Join-Path $Directory $row.name) $row.sha256 $row.length))}
        foreach($name in @('install_428_runtime.ps1','stage_aetherdesk_427_payloads.ps1','accept_428_native.py','verify_prior_native_428.py','r6_custody_amendment.py','run_428_launch.ps1',
            'pipeline.json','install-manifest.json','source-test-evidence.json','routing-candidate.json','proposal.json','pointer.json')){
            if(-not $seen.ContainsKey($name)){throw ('Missing reviewed 4.2.8 package input: '+$name)}}
        $installPath=Join-Path $Directory 'install-manifest.json'
        $stream=Open-428Pin $installPath $manifest.install_manifest_sha256;$pins.Add($stream);$inventory=Read-428Json $stream
        foreach($text in @(Import-428Installer (Join-Path $Directory 'install_428_runtime.ps1'))){. ([scriptblock]::Create($text))}
        Set-428Constants;$null=Get-428InstallFiles $inventory
        if($inventory.source_commit -cne $manifest.source_commit -or $inventory.version -cne '4.2.8'){throw '4.2.8 source lineage differs.'}
        foreach($row in @($inventory.files)){$pins.Add((Open-428Pin $row.source $row.sha256 $row.length))}
        if(-not $ApplyRequested){
            @{schema='cochem-428-launch-plan/1';status='R428_LAUNCH_READ_ONLY_PLAN';version='4.2.8';
                revision=$manifest.revision;source_commit=$manifest.source_commit;
                payload_files=@($inventory.files).Count;maximum_shared_slots=4;
                repair_profiles=@('repair_claude','repair_codex','repair_agy');
                repair_consumes_worker_slot=$false;input_window_minutes=20;
                late_prompts=$false;host_executed=$false}|ConvertTo-Json;return}
        $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
        if($PSVersionTable.PSEdition -cne 'Desktop' -or -not [Environment]::Is64BitProcess -or $env:COMPUTERNAME -cne 'AETHERDESK' -or
            $identity.Name -cne 'AETHERDESK\ansac' -or -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
            throw 'Run once in Administrator Windows PowerShell as AETHERDESK\ansac.'}
        foreach($text in @(Import-R6CopyFunctions $Directory)){. ([scriptblock]::Create($text))};Initialize-FileIdentity
        $ownerMutex=[Threading.Mutex]::new($false,'Global\CoChem428-OwnerSitting')
        try{$ownerLocked=$ownerMutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$ownerLocked=$true;throw 'An earlier 4.2.8 sitting was interrupted; preserve evidence.'}
        if(-not $ownerLocked){throw 'Another 4.2.8 sitting is already active.'}
        foreach($path in @($script:Root428,$script:Migration428,$authority)){if(Test-Path -LiteralPath $path){throw 'A prior 4.2.8 target exists. Preserve it; no automatic repeat.'}}
        $awake=Start-428AwakeLease
        $phase='front_loaded_input'
        $frontLoaded=Invoke-428FrontLoadedInput $manifest $Directory $startedUtc
        $mutex=[Threading.Mutex]::new($false,'Global\CoChem428-Launch')
        try{$locked=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$locked=$true;throw 'Earlier 4.2.8 deployment was interrupted; preserve evidence.'}
        if(-not $locked){throw 'Another deployment sitting is active.'}
        $pins.Add((Open-VerifiedFile $script:python $script:pythonPin (Get-Item -LiteralPath $script:python).Length))
        $phase='preconditions'
        $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect();$folder=$scheduler.GetFolder('\')
        $task=$folder.GetTask('CoChem-4.2.7-Warden');Assert-428TaskAcl $task
        $action=$task.Definition.Actions.Item(1)
        $old=[string]$action.WorkingDirectory
        if($old -cnotin @($oldR7,$oldR6,$oldR4)){throw 'Live Warden working directory is not a recognized baseline root.'}
        Assert-ProtectedPath (Join-Path $old 'pipeline.json')
        $oldCfg=Get-Content -LiteralPath (Join-Path $old 'pipeline.json') -Raw|ConvertFrom-Json
        $script:targetRoot=$old;$null=Assert-428Tree;Assert-428Interpreter;$script:targetRoot=$script:Root428
        $token=[IO.File]::ReadAllText([string]$oldCfg.token_file).Trim();$script:Headers428=@{Authorization='Bearer '+$token}
        $oldTriggerCount=[int]$task.Definition.Triggers.Count
        $triggerValid=if($old -ceq $oldR4){
            $oldTriggerCount -eq 0 -or ($oldTriggerCount -eq 1 -and [int]$task.Definition.Triggers.Item(1).Type -eq 9 -and [bool]$task.Definition.Triggers.Item(1).Enabled)
        }else{
            $oldTriggerCount -eq 1 -and [int]$task.Definition.Triggers.Item(1).Type -eq 9 -and [bool]$task.Definition.Triggers.Item(1).Enabled
        }
        if($task.Definition.Actions.Count -ne 1 -or $action.Path -cne (Join-Path $old '.venv\Scripts\python.exe') -or
            $action.WorkingDirectory -cne $old -or
            $task.Definition.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or $task.Definition.Principal.LogonType -ne 5 -or
            $task.Definition.Principal.RunLevel -ne 1 -or $task.Definition.Settings.RestartCount -ne 0 -or
            $task.Definition.Settings.MultipleInstances -ne 2 -or -not $triggerValid -or
            -not $task.Enabled -or $task.GetInstances(0).Count -ne 1){throw 'Live Warden definition differs from verified baseline.'}
        $expectedOldArgs=$action.Arguments
        $allowOldPaused=($old -ceq $oldR4)
        $health=Get-428Health;Assert-428Health $health $old $allowOldPaused
        $original=$task.Xml;$originalSddl=$task.GetSecurityDescriptor(7)
        Assert-428WardenTask $task $original $originalSddl $old $expectedOldArgs $true ($oldTriggerCount -ge 1) $oldTriggerCount
        $script:Sitting428='C:\Program Files\CoChem\R428Sitting-windows-20261014-'+[Guid]::NewGuid().ToString('N')
        New-ProtectedDirectory $script:Sitting428
        Write-Host ('Sanitized status reports: '+$script:Sitting428+'\status-*.json')
        Write-Host '4.2.8 prerequisites and front-loaded inputs verified. You can walk away; all remaining stages are unattended.' -ForegroundColor Green
        $phase='offline_install';Write-428Status $phase
        $powershell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $saved=$script:targetRoot
        try{
            $script:targetRoot=$script:Sitting428
            Invoke-428Native $powershell @('-NoProfile','-NonInteractive','-File',(Join-Path $Directory 'install_428_runtime.ps1'),
                '-Manifest',$installPath,'-ManifestSha256',$manifest.install_manifest_sha256,'-Apply') 'stopped-install' 900
        }finally{$script:targetRoot=$saved}
        $script:targetRoot=$script:Root428;$null=Assert-428Tree;Assert-428Interpreter
        $phase='native_acceptance';Write-428Status $phase
        $saved=$script:targetRoot
        try{
            $script:targetRoot=$script:Sitting428
            Invoke-428Native (Join-Path $script:Root428 '.venv\Scripts\python.exe') @(
                '-I','-B',(Join-Path $Directory 'accept_428_native.py'),
                '--mode','accept','--bundle-dir',$Directory,'--launch-manifest',$ManifestPath,
                '--output',(Join-Path $script:Sitting428 'native-acceptance.json'),'--apply'
            ) 'native-acceptance' 600
        }finally{$script:targetRoot=$saved}
        $phase='idle';Write-428Status $phase
        $deadline=[DateTime]::UtcNow.AddMinutes(30);$idle=$false
        do{
            try{$first=Get-428Health;Assert-428Health $first $old $allowOldPaused;Start-Sleep -Seconds 5;$second=Get-428Health;Assert-428Health $second $old $allowOldPaused
                $operator=Invoke-RestMethod -Uri 'http://127.0.0.1:47824/operator' -Headers $script:Headers428 -TimeoutSec 10
                Assert-428Idle $first $second $operator;$idle=$true;break}catch{Start-Sleep -Seconds 10}
        }while([DateTime]::UtcNow -lt $deadline)
        if(-not $idle){throw 'Previous controller did not become idle within the unattended bound.'}
        $processes=Open-428ProcessProof $second $old
        $task=$folder.GetTask('CoChem-4.2.7-Warden')
        if($task.Xml -cne $original -or $task.GetSecurityDescriptor(7) -cne $originalSddl){throw 'Warden changed during installation.'}
        Write-428InstallRecord 'warden-task-before.xml.json' @{xml=$original;sddl=$originalSddl;pid=$second.pid;instance_id=$second.instance_id}
        $phase='stop';Write-428Status $phase;$stopRequested=$true
        if($oldTriggerCount -ge 1){
            $definition=$task.Definition;$definition.Triggers.Item(1).Enabled=$false
            $null=$folder.RegisterTaskDefinition('CoChem-4.2.7-Warden',$definition,20,'SYSTEM',$null,5,$originalSddl)
            $task=$folder.GetTask('CoChem-4.2.7-Warden')
            Assert-428WardenTask $task $original $originalSddl $old $expectedOldArgs $true $false $oldTriggerCount
        }
        try{$task.Stop(0)}catch{
            $cause=$_.Exception;while($cause.InnerException){$cause=$cause.InnerException}
            if($cause.HResult -ne -2147216629){throw}
        }
        $deadline=[DateTime]::UtcNow.AddMinutes(2)
        do{Start-Sleep -Seconds 2;$task=$folder.GetTask('CoChem-4.2.7-Warden')
            $gone=@($processes|Where-Object{-not $_.HasExited}).Count -eq 0
            if($gone -and $task.GetInstances(0).Count -eq 0){break}
        }while([DateTime]::UtcNow -lt $deadline)
        if(-not $gone -or $task.GetInstances(0).Count){throw 'Owned native processes did not exit; preserve running state.'}
        $task.Enabled=$false
        Assert-428WardenTask $task $original $originalSddl $old $expectedOldArgs $false $false $oldTriggerCount
        Assert-428PortFree;$stopped=$true
        $phase='migration';Write-428Status $phase
        Assert-NoReparseAncestors $script:Migration428
        $null=[IO.Directory]::CreateDirectory($script:Migration428,(New-428PayloadAcl 'source/knowledge/control' $true))
        $migrationRequested=$true;$migration=Invoke-428Migration $scheduler $folder $false;$migrated=$true
        New-ProtectedDirectory $authority
        foreach($copy in @([pscustomobject]@{name='proposal.json';leaf=($manifest.proposal_sha256+'.json')},
            [pscustomobject]@{name='pointer.json';leaf='current-request.json'})){
            $source=Join-Path $Directory $copy.name;$destination=Join-Path $authority $copy.leaf
            $pin=(@($manifest.files)|Where-Object{$_.name -ceq $copy.name})[0]
            Copy-VerifiedPayload ([pscustomobject]@{source=$source;destination=$destination;sha256=$pin.sha256;length=$pin.length})}
        $phase='cutover';Write-428Status $phase
        $task=$folder.GetTask('CoChem-4.2.7-Warden');$definition=$task.Definition
        $action=$definition.Actions.Item(1);$action.Path=Join-Path $script:Root428 '.venv\Scripts\python.exe';$action.WorkingDirectory=$script:Root428
        $action.Arguments='-I -B -m cochem_pipeline daemon --config "'+(Join-Path $script:Root428 'pipeline.json')+'" --queue-launch-output-root "'+(Join-Path $oldCfg.private_root 'queue-launch-428')+'" --docker-wait-seconds 900'
        $definition.Settings.Enabled=$true
        if($definition.Triggers.Count -eq 0){
            $trigger=$definition.Triggers.Create(9);$trigger.UserId='AETHERDESK\ansac';$trigger.Delay='PT1M';$trigger.Enabled=$false
        }else{
            $definition.Triggers.Item(1).Enabled=$false
        }
        $null=$folder.RegisterTaskDefinition('CoChem-4.2.7-Warden',$definition,20,'SYSTEM',$null,5,$originalSddl)
        $task=$folder.GetTask('CoChem-4.2.7-Warden')
        $newArguments=$action.Arguments
        Assert-428WardenTask $task $original $originalSddl $script:Root428 $newArguments $true $false 1
        $startRequested=$true;$instance=$task.Run($null)
        $health=Wait-428Health $script:Root428;$proof=Open-428ProcessProof $health $script:Root428
        try{
            $task=$folder.GetTask('CoChem-4.2.7-Warden')
            if($task.GetInstances(0).Count -ne 1 -or $task.GetInstances(0).Item(1).InstanceGuid -cne $instance.InstanceGuid){throw '4.2.8 task instance differs.'}
            $definition=$task.Definition;$definition.Triggers.Item(1).Enabled=$true
            $null=$folder.RegisterTaskDefinition('CoChem-4.2.7-Warden',$definition,20,'SYSTEM',$null,5,$originalSddl)
            Assert-428WardenTask ($folder.GetTask('CoChem-4.2.7-Warden')) $original $originalSddl $script:Root428 $newArguments $true $true 1
        }finally{foreach($p in $proof){$p.Dispose()}}
        $phase='catalog_publication';Write-428Status $phase;$deadline=[DateTime]::UtcNow.AddMinutes(30)
        do{
            Start-Sleep -Seconds 5;$health=Get-428Health;Assert-428Health $health $script:Root428
            $catalog=$health.catalog_activation
            if($catalog.status -cin @('PUBLISHED_IN_CALLER_TRANSACTION','ALREADY_PUBLISHED') -and $catalog.request_id -ceq $manifest.request_id -and
                $catalog.policy_digest -ceq $manifest.catalog_policy_digest){break}
            if($catalog.status -ceq 'HELD'){throw '4.2.8 catalog control probe held. Preserve the running controller and evidence.'}
        }while([DateTime]::UtcNow -lt $deadline)
        if($catalog.request_id -cne $manifest.request_id -or $catalog.policy_digest -cne $manifest.catalog_policy_digest -or
            $catalog.status -cnotin @('PUBLISHED_IN_CALLER_TRANSACTION','ALREADY_PUBLISHED')){throw 'Catalog publication exceeded its unattended bound.'}
        $record=@{schema='cochem-428-owner-sitting/1';status='R428_RUNNING_CATALOG_PUBLICATION_VERIFIED';version='4.2.8';
            source_commit=$manifest.source_commit;launch_manifest_sha256=$ManifestHash;request_id=$manifest.request_id;
            native_control_probe_verified=$true;backup_preserved=$true;full_srs_acceptance=$false;late_prompt=$false}
        Write-428InstallRecord 'r428-complete.json' $record;Write-428Status 'complete' 'COMPLETE' $record;$record|ConvertTo-Json -Depth 6
    }catch{
        $failure=$_;$rollback='NOT_REQUIRED'
        if($stopped -and -not $startRequested){
            try{
                $rollback=Restore-428BeforeStart $scheduler $folder $original $originalSddl $old $migrationRequested $migrated
            }catch{$rollback='HELD_PRESERVE_STOPPED_OR_RUNNING_STATE'}
        }elseif($stopRequested -or $startRequested){$rollback='HELD_PRESERVE_POSSIBLY_RUNNING_STATE'}
        $record=@{schema='cochem-428-owner-sitting/1';status='R428_HELD_PRESERVE_EVIDENCE';version='4.2.8';phase=$phase;
            error_type=$failure.Exception.GetType().Name;rollback=$rollback;automatic_retry=$false;late_prompt=$false;start_requested=$startRequested}
        if(Test-Path -LiteralPath $script:Root428){try{Write-428InstallRecord 'r428-held.json' $record}catch{}}
        if($script:Sitting428){try{Write-428Status $phase 'HELD' $record}catch{}}
        $record|ConvertTo-Json -Depth 6;throw $failure
    }finally{
        if($null -ne $processes){foreach($p in $processes){$p.Dispose()}}
        foreach($stream in $pins){$stream.Dispose()}
        if($locked){$mutex.ReleaseMutex()};if($null -ne $mutex){$mutex.Dispose()}
        if($ownerLocked){$ownerMutex.ReleaseMutex()};if($null -ne $ownerMutex){$ownerMutex.Dispose()}
        if($null -ne $awake){try{Stop-428AwakeLease $awake}catch{Write-Warning 'The temporary awake request ends when this command process exits.'}}
        $script:Headers428=$null
    }
}

$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1') -ErrorAction Stop
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
Invoke-428Launch $LaunchManifest $LaunchManifestSha256 ([bool]$Apply) $PSScriptRoot
