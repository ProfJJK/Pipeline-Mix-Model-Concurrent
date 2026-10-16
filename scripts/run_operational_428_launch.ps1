#Requires -Version 5.1
<# Owner-only 4.2.8 r4 -> r5 sitting: fresh install or explicitly pinned recovery.
   Default is an offline read-only plan.
   No sign-in, late prompt, reboot, database restoration, automatic retry, or
   old bundle modification. Only an explicit -Apply reaches host operations. #>
[CmdletBinding()]
param([string]$LaunchManifest,[string]$LaunchManifestSha256,[switch]$Apply)

function Import-OpHelpers {
    param([string]$Directory)
    $path=Join-Path $Directory 'reviewed_428_launch_helpers.ps1'
    $stream=[IO.File]::Open($path,'Open','Read','Read')
    try{
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$pin=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        if($pin -cne 'e4ac275f8bc32e41c6503e0c04472139dce10930768fbfcada3e3d1e5fcd9dcd'){throw 'Reviewed pure launch helper differs.'}
        $stream.Position=0;$reader=[IO.StreamReader]::new($stream)
        try{$source=$reader.ReadToEnd()}finally{$reader.Dispose()}
        $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors)
        if($errors.Count){throw 'Reviewed helper syntax differs.'}
        foreach($name in @('Open-428Pin','Read-428Json','Import-428Installer','Assert-428TaskAcl',
            'Get-428InvariantDefinition','Assert-428WardenTask','Get-428Health','Assert-428Health',
            'Assert-428PortFree','Get-428FileSha256','Start-428AwakeLease','Stop-428AwakeLease')){
            $nodes=@($ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$false))
            if($nodes.Count -ne 1){throw 'Reviewed helper is missing or duplicated.'};$nodes[0].Extent.Text
        }
    }finally{$stream.Dispose()}
}

function Get-OpProperty {
    param($Object,[string]$Name,$Default=$null)
    if($Object -is [Collections.IDictionary]){if($Object.Contains($Name)){return $Object[$Name]};return $Default}
    if($null -ne $Object -and $null -ne $Object.PSObject.Properties[$Name]){return $Object.$Name};return $Default
}

function Get-OpRecoveryExpected {
    # Reviewed protected evidence from this one spent attempt. The exported
    # diagnostic supplied these pins; execution reopens the protected records.
    return @{schema='cochem-428-admission-recovery/1';scenario='INSTALLED_R5_EXPIRED_FENCE_20261015';
        runtime_source_commit='865a29b113a8b59c822f6aa4d921a45c18407fe5';
        original_launch_manifest_sha256='49481181faa25f4b8762b85013bece21afb3f58b3f9b8e7417237fa3dacfc75c';
        original_sitting='C:\Program Files\CoChem\R428Operational-20261015-a62bffb278044fffbaf21207a866ff81';
        install_after_sha256='0d4b036eda13a5381b700d766aa7eb097cbc893f6e0a6ff07b770e53bbe947ae';
        baseline_sha256='6dfc1cab0ebce9b73d341d03cf99d1e769b4351446d0af7b7ccc5ccd4e150767';
        owner_result_sha256='de2dde03d0cb6abfe681eafe6cc0814cdacfa0c1dce29ce0bd51cb1ac5a83652';
        fence=@{directory='stop-fence-d8196aa484dc4562a213e19faf9e3b05';nonce='a232264b12984ff2ab9ef33b7ec24c75';pid=46440;
            started_sha256='ac89c6175162298f10ebf05623bcfaaa884bc740e9673603ce657e73a0c07317';
            ready_sha256='c13d512da76fefa0ea1b6509eb35282f80d3c0a4135396f7ac5c6814b86f7912';
            result_sha256='2e808d80b655db392ce0d0dda8b93d828c604e7b296088cc63d1603b1ac8ce28';
            task_xml_sha256='351e830d81725f0d103ff69347cd4b889b4911548165d829dd725910a2df5004';
            task_sddl_sha256='bcacae79e462afbe0623b80a0898c24360cf59472d049fd6bc264d6308c04eff';
            last_run_utc='2026-10-15T18:41:18Z';last_task_result=2};
        warden=@{pid=24424;task_xml_sha256='aa3efe0fce92975a3b407dba19b6195368bfbd7f56fa438c77d3f4e509e93fe5';
            task_sddl_sha256='bcacae79e462afbe0623b80a0898c24360cf59472d049fd6bc264d6308c04eff';
            last_run_utc='2026-10-15T01:37:07Z';last_task_result=1}}
}

function Assert-OpExactFields {
    param($Actual,[Collections.IDictionary]$Expected,[string[]]$Additional=@())
    $names=if($Actual -is [Collections.IDictionary]){@($Actual.Keys)}else{@($Actual.PSObject.Properties.Name)}
    if($names.Count -ne $Expected.Count+$Additional.Count -or @($names|Where-Object{$_ -notin $Expected.Keys -and $_ -notin $Additional}).Count){throw 'Recovery field set differs.'}
    foreach($key in $Expected.Keys){
        $value=Get-OpProperty $Actual $key
        if($Expected[$key] -is [Collections.IDictionary]){Assert-OpExactFields $value $Expected[$key]}
        elseif(($Expected[$key] -is [string] -and $value -isnot [string]) -or
            (($Expected[$key] -is [int] -or $Expected[$key] -is [long]) -and $value -isnot [int] -and $value -isnot [long]) -or
            $value -cne $Expected[$key]){throw 'Recovery evidence identity or type differs.'}
    }
}

function Assert-OpRecoveryManifest {
    param($Recovery,$Manifest,$Original)
    Assert-OpExactFields $Recovery (Get-OpRecoveryExpected) @('recovery_id','launcher_source_commit')
    if($Recovery.recovery_id -cnotmatch '^[a-f0-9]{32}$' -or $Recovery.launcher_source_commit -cnotmatch '^[a-f0-9]{40}$' -or
        $Recovery.launcher_source_commit -cne $Manifest.launcher_source_commit -or
        $Manifest.source_commit -cne $Recovery.runtime_source_commit -or $Original.source_commit -cne $Recovery.runtime_source_commit){throw 'Recovery source/claim identity differs.'}
    foreach($name in @('schema','revision','source_commit','previous_root','target_root','previous_config_sha256','previous_install_sha256',
        'install_manifest_sha256','bootstrap_sha256','request_sha256','request_id','catalog_timeout_seconds','integration_manifest','integration_sha256',
        'input_window_minutes','late_prompts','pending_backlog_allowed')){
        if((Get-OpProperty $Manifest $name) -cne (Get-OpProperty $Original $name)){throw 'Recovery changed an original runtime input.'}
    }
    foreach($old in @($Original.files)){
        $current=@($Manifest.files|Where-Object{$_.name -ceq $old.name})
        if($current.Count -ne 1){throw 'Recovery lost an original input.'}
        if($old.name -cne 'run_operational_428_launch.ps1' -and
            ($current[0].sha256 -cne $old.sha256 -or $current[0].length -ne $old.length)){throw 'Recovery mutated an immutable runtime input.'}
    }
}

function Get-OpTextSha256 {
    param([string]$Text)
    $hash=[Security.Cryptography.SHA256]::Create()
    try{return [BitConverter]::ToString($hash.ComputeHash([Text.UTF8Encoding]::new($false).GetBytes($Text))).Replace('-','').ToLowerInvariant()}
    finally{$hash.Dispose()}
}

function New-OpRecoverySitting {
    param($Recovery,$Manifest,[string]$ManifestHash)
    $root='C:\Program Files\CoChem\R428OperationalRecovery-20261015-a62bffb278044fffbaf21207a866ff81-'+$Recovery.recovery_id
    if(Test-Path -LiteralPath $root){throw 'This recovery sitting is spent; preserve its claim and do not replay.'}
    New-ProtectedDirectory $root
    Write-OpRecord (Join-Path $root 'recovery-claim.json') @{schema='cochem-428-admission-recovery-claim/1';recovery_id=$Recovery.recovery_id;
        recovery_sha256=$Manifest.recovery_sha256;launch_manifest_sha256=$ManifestHash;runtime_source_commit=$Manifest.source_commit;launcher_source_commit=$Manifest.launcher_source_commit}
    return $root
}

function Read-OpRecoveryRecord {
    param([string]$Path,[string]$Sha256,$Pins)
    Assert-ProtectedPath $Path
    $stream=Open-428Pin $Path $Sha256;$Pins.Add($stream)
    return Read-428Json $stream
}

function Assert-OpRecoveryTask {
    param($Task,$Expected,[string]$Root,[string]$Arguments,[int]$Triggers)
    Assert-428TaskAcl $Task
    $d=$Task.Definition
    if((Get-OpTextSha256 $Task.Xml) -cne $Expected.task_xml_sha256 -or
        (Get-OpTextSha256 ($Task.GetSecurityDescriptor(7))) -cne $Expected.task_sddl_sha256 -or
        [int]$Task.State -ne 3 -or -not $Task.Enabled -or $Task.GetInstances(0).Count -ne 0 -or
        [int64]$Task.LastTaskResult -ne $Expected.last_task_result -or
        ([DateTime]$Task.LastRunTime).ToUniversalTime() -ne [DateTime]::Parse($Expected.last_run_utc).ToUniversalTime() -or
        $d.Actions.Count -ne 1 -or $d.Actions.Item(1).Type -ne 0 -or
        $d.Actions.Item(1).Path -cne (Join-Path $Root '.venv\Scripts\python.exe') -or
        $d.Actions.Item(1).WorkingDirectory -cne $Root -or $d.Actions.Item(1).Arguments -cne $Arguments -or
        $d.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or $d.Principal.LogonType -ne 5 -or $d.Principal.RunLevel -ne 1 -or
        $d.Settings.RestartCount -ne 0 -or $d.Settings.MultipleInstances -ne 2 -or $d.Triggers.Count -ne $Triggers){throw 'Exact stopped recovery task no longer matches.'}
    if($Triggers -eq 1 -and ($d.Triggers.Item(1).Type -ne 9 -or -not $d.Triggers.Item(1).Enabled -or
        $d.Triggers.Item(1).UserId -cne 'AETHERDESK\ansac')){throw 'Recovery Warden trigger changed.'}
}

function ConvertFrom-OpUnixTime {
    # Pinned records carry Python time.time() values; Windows PowerShell 5.1
    # JSON parsing yields decimal, double or integer types for them.
    param($Value)
    if($Value -isnot [double] -and $Value -isnot [decimal] -and $Value -isnot [int] -and $Value -isnot [long]){return $null}
    $seconds=[double]$Value
    if([double]::IsNaN($seconds) -or $seconds -lt 1577836800 -or $seconds -gt 4102444800){return $null}
    return [DateTime]::new(1970,1,1,0,0,0,[DateTimeKind]::Utc).AddSeconds($seconds)
}

function Test-OpMayBePythonOriginal {
    # Images never change during a process lifetime. Only a nameless row, a
    # Python-family image or a runtime/pipeline executable can still be an
    # original Python fence or Warden process.
    param($Row)
    $image=[string](Get-OpProperty $Row 'ExecutablePath');$name=[string](Get-OpProperty $Row 'Name')
    $base=if($image){[IO.Path]::GetFileName($image)}else{$name}
    if(-not $base){return $true}
    return ($base -match '^(?:python(?:w|[0-9]+(?:\.[0-9]+)?)?|py)\.exe$' -or
        $null -ne (Get-OpPipelineProcessReason $image ([string](Get-OpProperty $Row 'CommandLine')) $name))
}

function Test-OpPidReused {
    # Windows recycles a PID once its process ends, so occupancy alone never
    # identifies the original. A possible original (Test-OpMayBePythonOriginal)
    # is a different process only when created more than two minutes after
    # $CreatedBy, a pinned time by which the original already existed.
    # Anything ambiguous returns $false and stays an occupied hold.
    param($Row,$CreatedBy)
    if(-not (Test-OpMayBePythonOriginal $Row)){return $true}
    $created=Get-OpProperty $Row 'CreationDate'
    if($CreatedBy -isnot [DateTime] -or $created -isnot [DateTime]){return $false}
    return $created.ToUniversalTime() -gt $CreatedBy.AddSeconds(120)
}

function Get-OpObserverTransientIds {
    # Each held-observer cycle runs its sterile detector: the handle-proven
    # observer child starts a venv launcher, which starts the base interpreter
    # (plus a console host), all bounded by a 5 s timeout. A row qualifies only
    # when its whole ancestry (at most two levels) to that child is present in
    # this same snapshot and each process was created no earlier than its parent.
    param($Rows,[int]$ObserverChild)
    $byId=@{};foreach($row in $Rows){$byId[[int]$row.ProcessId]=$row}
    $ids=@()
    if(-not $byId.ContainsKey($ObserverChild)){return $ids}
    foreach($row in $Rows){
        $node=$row
        for($depth=1;$depth -le 2;$depth++){
            $parentId=[int]$node.ParentProcessId
            if($parentId -eq [int]$node.ProcessId -or -not $byId.ContainsKey($parentId)){break}
            $parent=$byId[$parentId]
            $created=Get-OpProperty $node 'CreationDate';$parentCreated=Get-OpProperty $parent 'CreationDate'
            if($created -isnot [DateTime] -or $parentCreated -isnot [DateTime] -or $created -lt $parentCreated){break}
            if($parentId -eq $ObserverChild){$ids+=[int]$row.ProcessId;break}
            $node=$parent
        }
    }
    return $ids
}

function Wait-OpProcessesExited {
    # Waits, bounded, for these exact processes (PID and creation time) to end.
    # It never accepts them: the caller takes a complete new inventory.
    param($Rows,[int]$Seconds)
    $deadline=[DateTime]::UtcNow.AddSeconds($Seconds)
    foreach($row in @($Rows)){
        do{
            # A failed poll only ends this wait early; the next inventory decides.
            try{$now=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$row.ProcessId)}catch{break}
            if($null -eq $now -or (Get-OpProperty $now 'CreationDate') -ne (Get-OpProperty $row 'CreationDate')){break}
            Start-Sleep -Milliseconds 100
        }while([DateTime]::UtcNow -lt $deadline)
    }
}

function Get-OpNamedPipes {
    return @([IO.Directory]::GetFiles('\\.\pipe\'))
}

function Test-OpNamedPipePath {
    # Only used when listing fails on an unrelated pipe name; probes one exact pipe.
    param([string]$Path)
    return [IO.File]::Exists($Path)
}

function Assert-OpRecoveryRuntimeDependencies {
    # Recovery starts with no controller, so nothing has proven the catalog
    # runtime's RAM-disk workspace or Docker engine pipe since r4 ended. Check
    # the pinned bootstrap values read-only before the first fence or task change.
    param([string]$Bootstrap,[string]$Sha256)
    $stream=Open-428Pin $Bootstrap $Sha256
    try{$config=Read-428Json $stream}finally{$stream.Dispose()}
    $ramdisk=Get-OpProperty $config 'ramdisk';$docker=Get-OpProperty $config 'docker'
    $root=[string](Get-OpProperty $ramdisk 'mount_root');$workspace=[string](Get-OpProperty $ramdisk 'workspace_subdirectory')
    # [IO.Path]::Combine, unlike Join-Path, does not require the drive to exist.
    if(-not $root -or -not $workspace -or -not (Test-Path -LiteralPath ([IO.Path]::Combine($root,$workspace)) -PathType Container)){
        throw 'Pinned RAM-disk workspace is unavailable; hold before any fence or task change.'}
    if([string](Get-OpProperty $docker 'endpoint') -cnotmatch '^npipe:////\./pipe/([A-Za-z0-9_.-]+)$'){throw 'Pinned Docker endpoint is not a local named pipe.'}
    $pipe='\\.\pipe\'+$Matches[1]
    $present=try{(Get-OpNamedPipes) -contains $pipe}catch{Test-OpNamedPipePath $pipe}
    if(-not $present){throw 'Pinned Docker engine pipe is unavailable; hold before any fence or task change.'}
}

function Assert-OpRecoveryQuiescent {
    # $NotAfter (UTC) stops further bounded waits, so a caller with a deadline
    # gets the normal rejection instead of a late inventory.
    param($Recovery,$AllowedFence=$null,$Pins=$null,$State=$null,$NotAfter=$null)
    Assert-428PortFree
    $createdBy=if($State -is [Collections.IDictionary] -and $State.Contains('preserved_pid_created_by')){$State.preserved_pid_created_by}else{@{}}
    foreach($id in @($Recovery.warden.pid,$Recovery.fence.pid)){
        # A reused PID is only a free PID; the inventory below still judges
        # every live process, including that occupant, by its executable role.
        $occupied=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$id)
        if($null -ne $occupied -and -not (Test-OpPidReused $occupied $createdBy[[string][int]$id])){
            throw (New-OpProcessRejection $occupied 'PRESERVED_PID_OCCUPIED')}
    }
    for($attempt=1;;$attempt++){
        if($attempt -gt 1){Assert-428PortFree}
        # Read-only bounded inventory. MCP clients are permitted only in their exact
        # module form; no daemon, provider, unknown launcher or competing owner phase
        # is accepted merely because the task has zero visible instances.
        $rows=@(Get-CimInstance Win32_Process)
        if($rows.Count -gt 4096){throw 'Recovery native inventory exceeds bound.'}
        $byId=@{};foreach($row in $rows){$byId[[int]$row.ProcessId]=$row}
        $observerIds=@()
        foreach($row in $rows){
            if(Test-OpHeldObserverCommand ([string]$row.ExecutablePath) ([string]$row.CommandLine)){
                try{$observerIds=@(Assert-OpHeldObserver $rows $Pins $State)}
                catch{
                    $proof=Get-OpFailure $_ 'observer_proof';$rejection=New-OpProcessRejection $row 'OBSERVER_PROOF_UNVERIFIED'
                    $rejection.Data['cochem_observer_proof']=@{error_type=$proof.error_type;frames=$proof.frames}
                    throw $rejection
                }
                break
            }
        }
        $transient=if($observerIds.Count){@(Get-OpObserverTransientIds $rows $observerIds[0])}else{@()}
        $pending=@()
        foreach($row in $rows){
            $image=[string]$row.ExecutablePath;$command=[string]$row.CommandLine
            $reason=Get-OpPipelineProcessReason $image $command ([string](Get-OpProperty $row 'Name'))
            if($null -eq $reason){continue}
            if(Test-OpExactMcpProcess $image $command){continue}
            if([int]$row.ProcessId -in $observerIds){continue}
            if($null -ne $AllowedFence -and $command.IndexOf($AllowedFence.arguments,[StringComparison]::Ordinal) -ge 0 -and
                (([int]$row.ProcessId -eq [int]$AllowedFence.ready.pid -and $image -ceq $script:python) -or
                 ($image -ceq (Join-Path $script:OpRoot '.venv\Scripts\python.exe') -and
                  $byId.ContainsKey([int]$AllowedFence.ready.pid) -and
                  [int]$byId[[int]$AllowedFence.ready.pid].ParentProcessId -eq [int]$row.ProcessId))){continue}
            # The observer's bounded detector, and a row whose image or command line
            # was unreadable (typically a process exiting between the snapshot and
            # its detail read), is never accepted: wait for those exact processes
            # to end, then require a complete clean inventory. A readable rejected
            # row still holds at once.
            if($attempt -lt 6 -and ([int]$row.ProcessId -in $transient -or -not $image -or -not $command) -and
                ($null -eq $NotAfter -or [DateTime]::UtcNow.AddSeconds(10) -lt $NotAfter)){$pending+=$row;continue}
            throw (New-OpProcessRejection $row $reason)
        }
        if(-not $pending.Count){return}
        Wait-OpProcessesExited $pending 8
    }
}

function Get-OpKnownPythonPattern {
    $venv='C:\\Program Files\\CoChem\\Pipeline4\.2\.(?:7|8)-windows-[0-9]{8}-r[0-9]+\\\.venv\\Scripts\\python\.exe'
    return '(?i:'+[regex]::Escape($script:python)+'|'+$venv+')'
}

function Get-OpPipelineProcessReason {
    # Executable identity makes native processes relevant. A shell/search argv
    # merely mentioning a source module is not evidence of Python execution.
    param([string]$Image,[string]$Command,[string]$Name='')
    if($Image -cmatch ('^(?:'+(Get-OpKnownPythonPattern)+')$')){return 'PROTECTED_PYTHON'}
    if($Image -ieq ((Get-OpHeldObserverExpected).python)){return 'PROTECTED_PYTHON'}
    if($Image.StartsWith($script:OpOldRoot+'\',[StringComparison]::OrdinalIgnoreCase) -or
        $Image.StartsWith($script:OpRoot+'\',[StringComparison]::OrdinalIgnoreCase)){return 'RUNTIME_IMAGE'}
    $base=if($Image){[IO.Path]::GetFileName($Image)}else{$Name}
    if($base -match '^(?:python(?:w|[0-9]+(?:\.[0-9]+)?)?|py)\.exe$'){
        if(-not $Image -or -not $Command){return 'UNINSPECTABLE_PYTHON'}
        if($Command -match 'cochem_(?:pipeline|mcp|supervisor)|held-supervisor-observation'){return 'PIPELINE_PYTHON'}
    }
    if($base -match '^cochem-(?:pipeline|supervisor)\.exe$'){return 'PIPELINE_ENTRYPOINT'}
    return $null
}

function New-OpProcessRejection {
    param($Process,[string]$Reason)
    $base=[IO.Path]::GetFileName([string](Get-OpProperty $Process 'ExecutablePath'))
    if(-not $base){$base=[string](Get-OpProperty $Process 'Name')}
    $base=$base.ToLowerInvariant()
    if($base -cnotin @('python.exe','pythonw.exe','py.exe','node.exe','powershell.exe','pwsh.exe','cmd.exe',
        'cochem-pipeline.exe','cochem-supervisor.exe','uv.exe')){$base='other'}
    $e=[InvalidOperationException]::new('A native pipeline process remains or its role is unknown; preserve evidence.')
    $e.Data['cochem_recovery_process']=@{pid=[int64]$Process.ProcessId;name=$base;
        command_sha256=(Get-OpTextSha256 ([string](Get-OpProperty $Process 'CommandLine')));reason=$Reason}
    return $e
}

function Test-OpExactMcpProcess {
    param([string]$Image,[string]$Command)
    $executable=Get-OpKnownPythonPattern
    if($Image -cnotmatch ('^(?:'+$executable+')$')){return $false}
    $client='(?i:'+[regex]::Escape('C:\Users\ansac\CoChem427\pipeline-client-r3.json')+')'
    $pattern='^\s*(?:"'+$executable+'"|'+$executable+')\s+-I\s+-B\s+-m\s+cochem_pipeline\s+mcp\s+--client-config\s+(?:"'+$client+'"|'+$client+')\s*$'
    # Preserve the reviewed controller-only bridge used by existing Claude and
    # Codex clients (r6_retarget_core.ps1 Get-ControllerPresence). It has no -I/-B.
    $bridge='(?i:'+[regex]::Escape('C:\Users\ansac\CoChem427\bridge.local.json')+')'
    $legacy='^\s*(?:"'+$executable+'"|'+$executable+')\s+-m\s+cochem_mcp\s+--provider\s+(?:codex|claude)\s+--config\s+(?:"'+$bridge+'"|'+$bridge+')\s*$'
    if($Command -cnotmatch $pattern -and $Command -cnotmatch $legacy){return $false}
    Assert-ProtectedPath $Image
    return $true
}

function Get-OpHeldObserverExpected {
    return @{root='C:\Program Files\CoChem\SupervisorObservation4.2.7-windows-20261007-r3-v1';
        staging='C:\Program Files\CoChem\Supervisor4.2.7-windows-20261007-staging-v1';
        python='C:\Program Files\CoChem\Supervisor4.2.7-windows-20261007-staging-v1\.venv\Scripts\python.exe';
        task='CoChem-4.2.7-HeldSupervisorObservation-20261007-r3-v1';
        helper='held-supervisor-observation-r3-v1.py';
        helper_sha256='d2fd68543963a05ba918c6194729a8bca642322565235ab18c7ba17ccad17640';
        configuration_sha256='e3f2ce4d4ace15f6428c181c158507f286ce974a0e2fefd6757c350c4744d49f';
        provisioning_sha256='beff7c79325f1c123ba7ae01aba4e810c033769063ba4aae5f9a9c5a67656e50';
        inputs_sha256='e65f44e1396a1f02802372a69579008e118ef93d1987d8edf7301a45b1218c61';
        nonce='10c0d0613b1740108e38138630b6b4ad';
        manifest_sha256='6aec5eaf82205be34e5849e73700f2e817e157be5c5ddd4366f04e549b75f0c4'}
}

function Test-OpHeldObserverCommand {
    param([string]$Image,[string]$Command)
    $e=Get-OpHeldObserverExpected
    if($Image -ine $script:python -and $Image -ine $e.python){return $false}
    $exe='(?i:'+[regex]::Escape($Image)+')'
    $helper='(?i:'+[regex]::Escape((Join-Path $e.root $e.helper))+')'
    return $Command -cmatch ('^\s*"'+$exe+'"\s+-I\s+-B\s+"'+$helper+'"\s+--observe\s*$')
}

function Read-OpObserverSnapshot {
    param([string]$Path)
    # The held observer atomically replaces this public heartbeat. Never pin it
    # against writes/deletes: doing so would break the observer we are inspecting.
    Assert-ProtectedPath $Path
    $stream=[IO.File]::Open($Path,'Open','Read',([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
    try{
        [CoChemStagedFileIdentity]::Check($stream,$Path)
        if($stream.Length -le 0 -or $stream.Length -gt 65536){throw 'Observer snapshot size differs.'}
        $raw=[byte[]]::new([int]$stream.Length);$offset=0
        while($offset -lt $raw.Length){$n=$stream.Read($raw,$offset,$raw.Length-$offset);if($n -le 0){throw 'Observer snapshot shortened.'};$offset+=$n}
        if($stream.ReadByte() -ne -1){throw 'Observer snapshot grew.'}
        [CoChemStagedFileIdentity]::Check($stream,$Path)
        return ([Text.UTF8Encoding]::new($false,$true).GetString($raw)|ConvertFrom-Json)
    }finally{$stream.Dispose()}
}

function Assert-OpObserverRecords {
    param($Provision,$Config,$Runtime)
    $e=Get-OpHeldObserverExpected
    if($Provision.schema -cne 'cochem-held-supervisor-provision/1' -or $Provision.status -cne 'HELD_OBSERVATION_PROVISIONED' -or
        $Provision.phase -cne 'complete' -or $Provision.root -cne $e.root -or $Provision.nonce -cne $e.nonce -or
        $Config.observation_only_contract.schema -cne 'cochem-held-observation/1' -or
        $Config.observation_only_contract.authority_evidence_sha256 -cne '1cf291591724b6edef17ba7e8d48fc6cce75830872ff6183ac1139aa313a3177' -or
        $Config.observation_only_contract.all_actuation_disabled -isnot [bool] -or -not $Config.observation_only_contract.all_actuation_disabled -or
        $Runtime.schema -cne 'cochem-held-supervisor-runtime/1' -or $Runtime.status -cne 'HELD_SUPERVISOR_OBSERVATION_RUNNING' -or
        $Runtime.provision_nonce -cne $e.nonce -or $Runtime.service_identity -cne 'SYSTEM' -or
        $Runtime.instance_id -cnotmatch '^[a-f0-9]{32}$' -or $Runtime.sequence -lt 1 -or
        ($Runtime.pid -isnot [int] -and $Runtime.pid -isnot [long]) -or $Runtime.pid -le 0 -or
        ($Runtime.process_creation_filetime -isnot [long] -and $Runtime.process_creation_filetime -isnot [int]) -or $Runtime.process_creation_filetime -le 0){throw 'Observer public identity differs.'}
    foreach($name in @('configuration_sha256','helper_sha256','inputs_sha256')){
        if($Provision.$name -cne $e[$name] -or $Runtime.$name -cne $e[$name]){throw 'Observer immutable binding differs.'}
    }
    foreach($pair in @(@($Config,'auto_deploy'),@($Config.observation_only_contract,'warden_task_or_pointer_changes_authorized'),
        @($Provision,'paid_repair_enabled'),@($Provision,'component_recovery_enabled'),@($Provision,'existing_warden_changed'),
        @($Provision,'existing_pipeline_pointer_changed'),@($Runtime,'paid_repair_enabled'),@($Runtime,'component_recovery_enabled'),
        @($Runtime,'warden_actuation_enabled'),@($Runtime,'full_srs_acceptance'))){
        $v=Get-OpProperty $pair[0] $pair[1];if($v -isnot [bool] -or $v){throw 'Observer actuation is not permanently held.'}
    }
    $checked=$Runtime.checked_at
    if(($checked -isnot [double] -and $checked -isnot [decimal] -and $checked -isnot [long] -and $checked -isnot [int]) -or
        [double]::IsNaN([double]$checked) -or [double]::IsInfinity([double]$checked) -or
        [Math]::Abs([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0-[double]$checked) -gt 30){throw 'Observer heartbeat is not fresh.'}
}

function Assert-OpObserverFiles {
    param($Pins)
    if($null -eq $Pins){throw 'Observer custody retention is missing.'}
    $e=Get-OpHeldObserverExpected
    $provision=Read-OpRecoveryRecord (Join-Path $e.root 'provisioning.json') $e.provisioning_sha256 $Pins
    $config=Read-OpRecoveryRecord (Join-Path $e.root 'supervisor.json') $e.configuration_sha256 $Pins
    $null=Read-OpRecoveryRecord (Join-Path $e.root 'inputs.json') $e.inputs_sha256 $Pins
    foreach($file in @(@((Join-Path $e.root $e.helper),$e.helper_sha256),
        @((Join-Path $e.staging 'controls\stage-independent-supervisor-holds-r3-v1.py'),'215af8db414c7bbc4352c825dbf250b7bbc244a8a2dbc2d4addadc72cf1acb74'),
        @((Join-Path $e.staging '.venv\pyvenv.cfg'),'0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d'),
        @($e.python,'560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'),
        @($script:python,'d8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa'))){
        Assert-ProtectedPath $file[0];$Pins.Add((Open-428Pin $file[0] $file[1]))
    }
    $manifest=Read-OpRecoveryRecord (Join-Path $e.staging 'controls\staging-manifest.json') $e.manifest_sha256 $Pins
    if($manifest.schema -cne 'cochem-independent-supervisor-staging-freeze/1' -or $manifest.target_root -cne $e.staging -or
        $manifest.complete_source_freeze -ne $true -or $manifest.activation_authorized -ne $false){throw 'Observer staged import manifest differs.'}
    $site=Join-Path $e.staging '.venv\Lib\site-packages'
    $rows=@($manifest.source_files|Where-Object{$_.relative -cmatch '^src/(cochem_pipeline|cochem_mcp|cochem_supervisor)/'})
    if($rows.Count -ne 109){throw 'Observer installed import inventory differs.'}
    foreach($row in $rows){
        # The exact pinned manifest authorizes package files only, never unrelated
        # source artifacts (for example src/x.py) or a fresh package substitution.
        $path=Join-Path $site $row.relative.Substring(4);Assert-ProtectedPath $path
        $Pins.Add((Open-VerifiedFile $path $row.sha256 $row.bytes))
    }
    $pth=@{'_virtualenv.pth'='69ac3d8f27e679c81b94ab30b3b56e9cd138219b1ba94a1fa3606d5a76a1433d';
        'pywin32.pth'='e7cd73df98b91c407dfd96d1f4dd18b7f9a60f29902b92cf5ece79b6eb637b81'}
    $startup=@(Get-ChildItem -LiteralPath $site -Filter '*.pth' -File -Force)
    if($startup.Count -ne $pth.Count){throw 'Observer import startup inventory differs.'}
    foreach($item in $startup){
        if(-not $pth.ContainsKey($item.Name)){throw 'Observer import startup name differs.'}
        Assert-ProtectedPath $item.FullName;$Pins.Add((Open-428Pin $item.FullName $pth[$item.Name]))
    }
    return @{provision=$provision;config=$config}
}

function Assert-OpObserverTaskAcl {
    # Preserve the observer installer's reviewed task-private-acl-v8 policy.
    # Scheduler may project its protected task-file DACL as an unprotected
    # three-ACE service descriptor. Only this exact observer may use that path;
    # Warden/one-shot validators remain unchanged.
    param($Task)
    $expected=Get-OpHeldObserverExpected
    if($Task.Name -cne $expected.task){throw 'Observer ACL requires the exact root task name.'}
    $sd=[Security.AccessControl.RawSecurityDescriptor]::new($Task.GetSecurityDescriptor(7))
    if($null -eq $sd.Owner -or $sd.Owner.Value -notin @('S-1-5-18','S-1-5-32-544') -or
        $null -eq $sd.DiscretionaryAcl -or $sd.DiscretionaryAcl.Count -notin @(2,3)){throw 'Observer task ownership/private DACL differs.'}
    $seen=[Collections.Generic.HashSet[string]]::new();$systemRead=$false
    foreach($ace in $sd.DiscretionaryAcl){
        if($ace.AceType -ne [Security.AccessControl.AceType]::AccessAllowed -or
            $ace.AceFlags -ne [Security.AccessControl.AceFlags]::None){throw 'Observer task ACL grants differ.'}
        $sid=$ace.SecurityIdentifier.Value
        if($ace.AccessMask -eq 2032127 -and $sid -in @('S-1-5-18','S-1-5-32-544')){
            if(-not $seen.Add($sid)){throw 'Observer task ACL grants differ.'}
        }elseif($ace.AccessMask -eq 1179785 -and $sid -ceq 'S-1-5-18' -and -not $systemRead){$systemRead=$true}
        else{throw 'Observer task ACL grants differ.'}
    }
    if($seen.Count -ne 2 -or -not $seen.Contains('S-1-5-18') -or -not $seen.Contains('S-1-5-32-544')){throw 'Observer task ACL grants differ.'}
    if($sd.ControlFlags -band [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected){return}
    if($sd.DiscretionaryAcl.Count -ne 3 -or -not $systemRead){throw 'Observer descriptor is not the reviewed Scheduler projection.'}
    $path=[IO.Path]::Combine('C:\Windows\System32\Tasks',$expected.task)
    $item=Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if($item.PSIsContainer -isnot [bool] -or $item.PSIsContainer -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or ($item.Attributes -band [IO.FileAttributes]::Directory) -or
        $item.Length -lt 1 -or $item.Length -gt 131072){throw 'Observer task backing file is not ordinary and bounded.'}
    $hash=Get-FileHash -LiteralPath $path -Algorithm SHA256 -ErrorAction Stop
    if($hash.Hash -isnot [string] -or $hash.Hash -cnotmatch '\A[a-fA-F0-9]{64}\z'){throw 'Observer task backing digest is invalid.'}
    $stream=$null
    try{
        # This existing custody boundary verifies non-reparse ancestors, resolved
        # handle identity, one link, length and digest while denying replacement.
        $stream=Open-VerifiedFile $path $hash.Hash.ToLowerInvariant() ([long]$item.Length)
        if($null -eq $stream){throw 'Observer task backing custody is missing.'}
        $acl=Get-Acl -LiteralPath $path -ErrorAction Stop
        $sections=[Security.AccessControl.AccessControlSections]::Owner -bor [Security.AccessControl.AccessControlSections]::Access
        $backing=[Security.AccessControl.RawSecurityDescriptor]::new($acl.GetSecurityDescriptorSddlForm($sections))
        if($null -eq $backing.Owner -or $backing.Owner.Value -notin @('S-1-5-18','S-1-5-32-544') -or
            -not ($backing.ControlFlags -band [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected) -or
            $null -eq $backing.DiscretionaryAcl -or $backing.DiscretionaryAcl.Count -ne 2){throw 'Observer task backing ownership/private DACL differs.'}
        $backingSeen=[Collections.Generic.HashSet[string]]::new()
        foreach($ace in $backing.DiscretionaryAcl){
            if($ace.AceType -ne [Security.AccessControl.AceType]::AccessAllowed -or
                $ace.AceFlags -ne [Security.AccessControl.AceFlags]::None -or $ace.AccessMask -ne 2032127 -or
                $ace.SecurityIdentifier.Value -notin @('S-1-5-18','S-1-5-32-544') -or
                -not $backingSeen.Add($ace.SecurityIdentifier.Value)){throw 'Observer task backing ACL grants differ.'}
        }
    }finally{if($null -ne $stream){$stream.Dispose()}}
}

function Assert-OpObserverTask {
    param($Task)
    $e=Get-OpHeldObserverExpected;$d=$Task.Definition
    Assert-OpObserverTaskAcl $Task
    if($Task.Name -cne $e.task -or [int]$Task.State -ne 4 -or -not $Task.Enabled -or
        $d.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or $d.Principal.LogonType -ne 5 -or $d.Principal.RunLevel -ne 1 -or
        $d.Actions.Count -ne 1 -or $d.Actions.Item(1).Type -ne 0 -or $d.Actions.Item(1).Path -cne $e.python -or
        $d.Actions.Item(1).Arguments -cne ('-I -B "'+(Join-Path $e.root $e.helper)+'" --observe') -or
        $d.Actions.Item(1).WorkingDirectory -cne $e.root -or $d.Settings.AllowDemandStart -ne $true -or
        [Xml.XmlConvert]::ToTimeSpan($d.Settings.ExecutionTimeLimit).Ticks -ne 0 -or
        $d.Settings.RestartCount -ne 0 -or $d.Settings.MultipleInstances -ne 2 -or
        $d.Triggers.Count -ne 1 -or $d.Triggers.Item(1).Type -ne 8 -or -not $d.Triggers.Item(1).Enabled){throw 'Observer task is not the held definition.'}
    $instances=$Task.GetInstances(0)
    if($instances.Count -ne 1 -or [string]$instances.Item(1).InstanceGuid -notmatch '^\{?[a-fA-F0-9-]{36}\}?$'){throw 'Observer running instance differs.'}
    return [string]$instances.Item(1).InstanceGuid
}

function Open-OpObserverProcess {
    param($Row)
    if((Invoke-CimMethod -InputObject $Row -MethodName GetOwnerSid).Sid -cne 'S-1-5-18'){throw 'Observer process is not SYSTEM.'}
    $p=[Diagnostics.Process]::GetProcessById([int]$Row.ProcessId)
    try{
        $null=$p.Handle
        if($p.HasExited -or $p.MainModule.FileName -ine $Row.ExecutablePath -or
            [Math]::Abs(($p.StartTime.ToUniversalTime()-([DateTime]$Row.CreationDate).ToUniversalTime()).TotalSeconds) -gt 1){throw 'Observer native creation changed.'}
        return $p
    }catch{$p.Dispose();throw}
}

function Assert-OpHeldObserver {
    param($Rows,$Pins,$State)
    if($null -eq $State){throw 'Observer identity retention is missing.'}
    $e=Get-OpHeldObserverExpected
    if(-not $State.ContainsKey('observer_files')){$State.observer_files=Assert-OpObserverFiles $Pins}
    $files=$State.observer_files
    $runtime=Read-OpObserverSnapshot (Join-Path $e.root 'observation-runtime.json')
    Assert-OpObserverRecords $files.provision $files.config $runtime
    $matches=@($Rows|Where-Object{Test-OpHeldObserverCommand ([string]$_.ExecutablePath) ([string]$_.CommandLine)})
    $child=@($matches|Where-Object{$_.ProcessId -eq $runtime.pid -and $_.ExecutablePath -ieq $script:python})
    if($matches.Count -ne 2 -or $child.Count -ne 1){throw 'Observer native pair differs.'}
    $parent=@($matches|Where-Object{$_.ProcessId -eq $child[0].ParentProcessId -and $_.ExecutablePath -ieq $e.python})
    if($parent.Count -ne 1){throw 'Observer launcher pair differs.'}
    $task=$script:OpFolder.GetTask($e.task);$instance=Assert-OpObserverTask $task
    $taskXml=$task.Xml;$taskSddl=$task.GetSecurityDescriptor(7);$lastRun=[DateTime]$task.LastRunTime
    $held=[Collections.Generic.List[Diagnostics.Process]]::new()
    try{
        foreach($row in @($child[0],$parent[0])){$held.Add((Open-OpObserverProcess $row))}
        if($held[0].StartTime.ToUniversalTime().ToFileTimeUtc() -ne $runtime.process_creation_filetime -or
            $held[1].StartTime -gt $held[0].StartTime){throw 'Observer heartbeat/native creation binding differs.'}
        $again=$script:OpFolder.GetTask($e.task)
        if((Assert-OpObserverTask $again) -cne $instance -or $again.Xml -cne $taskXml -or
            $again.GetSecurityDescriptor(7) -cne $taskSddl -or ([DateTime]$again.LastRunTime) -ne $lastRun -or
            @($held|Where-Object{$_.HasExited}).Count){throw 'Observer changed during read-only verification.'}
        if(-not $State.ContainsKey('observer_processes')){$State.observer_processes=[Collections.Generic.List[Diagnostics.Process]]::new()}
        foreach($p in $held){$State.observer_processes.Add($p)};$held.Clear()
        return @([int]$child[0].ProcessId,[int]$parent[0].ProcessId)
    }finally{foreach($p in $held){$p.Dispose()}}
}

function Assert-OpRecoveryCatalog {
    param($Original,$Current)
    foreach($key in @('active_policy_sha256','active_catalog_sha256')){
        if((Get-OpProperty $Original $key) -cne (Get-OpProperty $Current $key)){throw 'Catalog authority changed after the reviewed sitting; hold.'}
    }
}

function Assert-OpRecoveryEvidence {
    param($Recovery,$Manifest,$Inventory,$Pins,[hashtable]$State)
    $prior=Join-Path $Recovery.original_sitting 'private';$froot=Join-Path $prior $Recovery.fence.directory
    foreach($name in @('catalog-phase','final-config.json')){
        if(Test-Path -LiteralPath (Join-Path $prior $name)){throw 'The original attempt has later phase evidence; hold.'}
    }
    foreach($file in @(Get-ChildItem -LiteralPath $Recovery.original_sitting -Filter 'status-*.json' -File)){
        $r=Read-OpPrivateRecord $file.FullName
        if($r.phase -notin @('preconditions','offline_install','codex_preflight','admission_fence')){throw 'Original sitting progressed beyond the reviewed boundary.'}
    }
    $baseline=Read-OpRecoveryRecord (Join-Path $prior 'baseline.json') $Recovery.baseline_sha256 $Pins
    $owner=Read-OpRecoveryRecord (Join-Path $prior 'owner-result.json') $Recovery.owner_result_sha256 $Pins
    $install=Read-OpRecoveryRecord (Join-Path $script:OpRoot 'install-after.json') $Recovery.install_after_sha256 $Pins
    $started=Read-OpRecoveryRecord (Join-Path $froot 'started.json') $Recovery.fence.started_sha256 $Pins
    $ready=Read-OpRecoveryRecord (Join-Path $froot 'ready.json') $Recovery.fence.ready_sha256 $Pins
    $result=Read-OpRecoveryRecord (Join-Path $froot 'result.json') $Recovery.fence.result_sha256 $Pins
    if($owner.schema -cne 'cochem-428-operational-owner-result/1' -or $owner.status -cne 'R428_OPERATIONAL_HELD_PRESERVE_EVIDENCE' -or
        $owner.phase -cne 'admission_fence' -or $owner.rollback -cne 'NOT_REQUIRED' -or $owner.cutover_requested -ne $false -or
        $owner.source_commit -cne $Recovery.runtime_source_commit -or $owner.request_sha256 -cne $Manifest.request_sha256 -or
        $owner.launch_manifest_sha256 -cne $Recovery.original_launch_manifest_sha256 -or
        $install.schema -cne 'cochem-428-offline-install/1' -or $install.status -cne 'STOPPED_RUNTIME_INSTALLED' -or
        $install.source_commit -cne $Recovery.runtime_source_commit -or $install.manifest_sha256 -cne $Manifest.install_manifest_sha256 -or
        $baseline.config_sha256 -cne $Manifest.previous_config_sha256 -or $baseline.health.pid -ne $Recovery.warden.pid -or
        (Get-OpTextSha256 $baseline.xml) -cne $Recovery.warden.task_xml_sha256 -or
        (Get-OpTextSha256 $baseline.sddl) -cne $Recovery.warden.task_sddl_sha256){throw 'Protected original installation/boundary differs.'}
    foreach($r in @($started,$ready,$result)){
        if($r.schema -cne 'cochem-owner-admission-fence/4.2.8' -or $r.nonce -cne $Recovery.fence.nonce -or $r.pid -ne $Recovery.fence.pid -or
            $r.config_sha256 -cne $Manifest.previous_config_sha256 -or $r.request_sha256 -cne $Manifest.request_sha256 -or
            $r.database_path -cne (Join-Path $script:OpConfig.private_root 'job_board.db') -or $r.database_rows_modified -ne 0){throw 'Protected expired-fence binding differs.'}
    }
    if($started.status -cne 'WAITING_FOR_IDLE' -or $ready.status -cne 'WRITER_FENCE_HELD' -or
        $result.status -cne 'FENCE_EXPIRED' -or $result.released -ne $false -or $result.lock_released -ne $true -or
        $result.ready_sha256 -cne $Recovery.fence.ready_sha256 -or
        (Test-Path -LiteralPath (Join-Path $froot 'release.json')) -or (Test-Path -LiteralPath (Join-Path $froot 'held.json'))){throw 'Original fence did not expire at the reviewed boundary.'}
    foreach($p in $ready.counts.PSObject.Properties){if($p.Value -ne 0){throw 'Original fence contained active execution.'}}
    # Each original process existed when it wrote these pinned values, so a
    # holder of its recycled PID created later is a different process.
    $State.preserved_pid_created_by=@{([string][int]$Recovery.fence.pid)=(ConvertFrom-OpUnixTime (Get-OpProperty $ready 'ready_at'));
        ([string][int]$Recovery.warden.pid)=(ConvertFrom-OpUnixTime (Get-OpProperty $baseline.health 'process_started_at'))}
    $script:OpOriginalXml=$baseline.xml;$script:OpOriginalSddl=$baseline.sddl
    Assert-OpRecoveryTask ($script:OpFolder.GetTask('CoChem-4.2.7-Warden')) $Recovery.warden $script:OpOldRoot $script:OpOldArgs 1
    $fargs='-I -B -m cochem_pipeline.owner_admission_fence_428 --config "'+$script:OpOldConfig+'" --config-sha256 '+$Manifest.previous_config_sha256+
        ' --output-root "'+$froot+'" --nonce '+$Recovery.fence.nonce+' --request-sha256 '+$Manifest.request_sha256+' --wait-seconds 1800 --hold-seconds 240'
    Assert-OpRecoveryTask ($script:OpFolder.GetTask('CoChem-4.2.8-Fence-'+$Recovery.fence.nonce)) $Recovery.fence $script:OpRoot $fargs 0
    Assert-OpRecoveryQuiescent $Recovery $null $Pins $State
    $Pins.Add((Open-428Pin (Join-Path $script:OpRoot 'install-manifest.json') $Manifest.install_manifest_sha256))
    $null=Assert-428Tree;Assert-428Interpreter
    foreach($file in @(Get-428InstallFiles $Inventory)){
        $p=Open-VerifiedFile $file.destination $file.sha256 $file.length;$Pins.Add($p)
    }
    $State.recovery_catalog=$ready.catalog
    $State.verified_stopped_at_entry=$true;$State.old_task_last_run=[DateTime]::Parse($Recovery.warden.last_run_utc).ToUniversalTime()
    Write-OpRecord (Join-Path $script:OpPrivate 'baseline.json') @{xml=$script:OpOriginalXml;sddl=$script:OpOriginalSddl;
        config_sha256=$Manifest.previous_config_sha256;original_baseline_sha256=$Recovery.baseline_sha256;verified_stopped_at_entry=$true}
}

function New-OpResultRecord {
    param([hashtable]$State,$Manifest,[string]$ManifestHash)
    return @{schema='cochem-428-operational-owner-result/1';status=$State.status;phase=$State.phase;rollback=$State.rollback;
        source_commit=$Manifest.source_commit;launch_manifest_sha256=$ManifestHash;request_sha256=$Manifest.request_sha256;
        launcher_source_commit=(Get-OpProperty $Manifest 'launcher_source_commit' $Manifest.source_commit);
        verified_stopped_at_entry=(Get-OpProperty $State 'verified_stopped_at_entry' $false);
        publication_state=(Get-OpProperty $State.acceptance 'publication_state' 'UNKNOWN');cutover_requested=$State.cutover_requested;
        runtime_health_verified=($null -ne (Get-OpProperty $State 'health'));
        codex_integration_status=(Get-OpProperty (Get-OpProperty $State 'integration') 'status' 'NOT_APPLIED');
        codex_session_refresh_required=($null -ne (Get-OpProperty $State 'integration'));
        all_routes_usable=(Get-OpProperty $State.acceptance 'all_routes_usable' $false);
        coverage_holds=(Get-OpProperty $State.acceptance 'coverage_holds');
        error_type=(Get-OpProperty $State 'error_type');
        launcher_failure=(Get-OpProperty $State 'launcher_failure');
        fence_cleanup=(Get-OpProperty $State 'fence_cleanup');
        acceptance_failure=(Get-OpProperty $State.acceptance 'failure');
        late_prompt=$false;automatic_retry=$false;useful_job_acceptance=$false}
}

function Test-OpRestoreAuthority {
    # Absence, a crash after commit, or an uncertain process is never permission.
    param($Receipt,[bool]$PhaseStarted,[bool]$PhaseExited,[bool]$CutoverRequested)
    if($CutoverRequested){return $false}
    if(-not $PhaseStarted){return $true}
    $proof=Get-OpProperty $Receipt 'publication_proof'
    return ($PhaseExited -and (Get-OpProperty $Receipt 'publication_state') -ceq 'NOT_COMMITTED' -and
        (Get-OpProperty $Receipt 'runtime_resources_closed' $false) -eq $true -and
        (Get-OpProperty $proof 'catalog_probe_cleanup_verified' $false) -eq $true)
}

function Invoke-OpTransaction {
    # Inert action seam: tests exercise real ordering and failure branches without
    # COM/tasks/processes. Host adapters below are used only by owner -Apply.
    param([hashtable]$Actions,[hashtable]$State)
    try{
        foreach($phase in @('preconditions','offline_install','codex_preflight','admission_fence','stop_previous','release_fence','catalog_acceptance','cutover','verify_running','enable_trigger','codex_integration')){
            $State.phase=$phase
            $State.substage=$null
            if($phase -ceq 'stop_previous'){$State.stop_requested=$true}
            if($phase -ceq 'catalog_acceptance'){$State.acceptance_started=$true}
            if($phase -ceq 'cutover'){$State.cutover_requested=$true}
            & $Actions[$phase] $State
        }
        $State.status='R428_OPERATIONAL_RUNNING_VERIFIED'
    }catch{
        $State.error_type=$_.Exception.GetType().Name
        $State.launcher_failure=Get-OpFailure $_ (Get-OpProperty $State 'substage')
        $State.status='R428_OPERATIONAL_HELD_PRESERVE_EVIDENCE'
        $State.rollback='NOT_REQUIRED'
        if((Get-OpProperty $State 'verified_stopped_at_entry' $false) -and -not $State.stop_requested){
            $State.rollback='NO_RESTART_ATTEMPTED_PREVIOUS_ALREADY_STOPPED'
        }
        if(-not $State.stop_requested -and $null -ne (Get-OpProperty $State 'fence')){
            # Starting a writer fence is meaningful even when READY validation
            # fails before the stop action. Retain and settle only this sitting's
            # exact verified one-shot; never infer old-runtime health/restoration.
            try{Release-OpFence $State.fence;$State.fence_cleanup=$State.fence.completion}
            catch{$State.fence_cleanup=@{status='HELD_PRESERVE_FENCE';failure=(Get-OpFailure $_ 'fence_cleanup')}}
        }
        if($State.stopped -and (Test-OpRestoreAuthority $State.acceptance $State.acceptance_started $State.acceptance_exited $State.cutover_requested)){
            try{& $Actions.restore_previous $State;$State.rollback='PREVIOUS_RUNTIME_RESTORED_HEALTH_VERIFIED'}
            catch{$State.rollback='HELD_PRESERVE_STOPPED_OR_RUNNING_STATE';$State.recovery_error_type=$_.Exception.GetType().Name}
        }elseif($State.stop_requested -or $State.acceptance_started -or $State.cutover_requested){
            $State.rollback='HELD_PRESERVE_STOPPED_OR_RUNNING_STATE'
        }
    }
    return $State
}

function New-OpPrivateAcl {
    param([bool]$Directory)
    $acl=New-CodeAcl $Directory
    foreach($rule in @($acl.GetAccessRules($true,$false,[Security.Principal.SecurityIdentifier]))){
        if($rule.IdentityReference.Value -ceq 'S-1-5-32-545'){$acl.RemoveAccessRuleSpecific($rule)}
    };return $acl
}

function New-OpPrivateDirectory {
    param([string]$Path)
    if(Test-Path -LiteralPath $Path){throw 'Preserve existing owner evidence directory.'}
    Assert-ProtectedPath (Split-Path -Parent $Path)
    [IO.DirectoryInfo]::new($Path).Create((New-OpPrivateAcl $true));Assert-ProtectedPath $Path
}

function Write-OpRecord {
    param([string]$Path,$Record,[bool]$Public=$false)
    Assert-ProtectedPath (Split-Path -Parent $Path)
    $acl=if($Public){New-CodeAcl $false}else{New-OpPrivateAcl $false}
    $s=[IO.FileStream]::new($Path,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,4096,[IO.FileOptions]::None,$acl)
    try{$raw=[Text.UTF8Encoding]::new($false).GetBytes(($Record|ConvertTo-Json -Depth 20));$s.Write($raw,0,$raw.Length);$s.Flush($true)}finally{$s.Dispose()}
}

function Write-OpStatus {
    param([string]$Phase,[string]$Status='RUNNING',$Result=$null,$Substage=$null)
    if(-not $script:OpSitting){return}
    Write-OpRecord (Join-Path $script:OpSitting ('status-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffff')+'-'+[Guid]::NewGuid().ToString('N')+'.json')) `
        @{schema='cochem-428-operational-status/1';phase=$Phase;substage=$Substage;status=$Status;utc=[DateTime]::UtcNow.ToString('o');result=$Result;late_prompt=$false;automatic_retry=$false} $true
}

function Get-OpFailure {
    param($Record,$Substage)
    $frames=@()
    foreach($line in ([string]$Record.ScriptStackTrace -split '\r?\n')){
        if($line -match '^at ([A-Za-z0-9_-]+|<ScriptBlock>), .+: line ([0-9]+)$'){
            $frames+=@{function=$Matches[1];line=[int]$Matches[2]}
        }
        if($frames.Count -eq 8){break}
    }
    $process=$null;$observer=$null;$exception=$Record.Exception
    for($i=0;$i -lt 4 -and $null -ne $exception;$i++){
        $v=$exception.Data['cochem_recovery_process']
        if($v -is [Collections.IDictionary] -and $v.Count -eq 4 -and
            $v.Contains('pid') -and $v.Contains('name') -and $v.Contains('reason') -and $v.Contains('command_sha256') -and
            ($v.pid -is [int] -or $v.pid -is [long]) -and $v.pid -gt 0 -and $v.pid -le [uint32]::MaxValue -and
            $v.name -is [string] -and $v.reason -is [string] -and
            $v.name -cin @('python.exe','pythonw.exe','py.exe','node.exe','powershell.exe','pwsh.exe','cmd.exe','cochem-pipeline.exe','cochem-supervisor.exe','uv.exe','other') -and
            $v.reason -cin @('PROTECTED_PYTHON','RUNTIME_IMAGE','PIPELINE_PYTHON','UNINSPECTABLE_PYTHON','PIPELINE_ENTRYPOINT','PRESERVED_PID_OCCUPIED','OBSERVER_PROOF_UNVERIFIED') -and
            $v.command_sha256 -is [string] -and $v.command_sha256 -cmatch '^[a-f0-9]{64}$'){
            $process=@{pid=$v.pid;name=$v.name;reason=$v.reason;command_sha256=$v.command_sha256}
            $o=$exception.Data['cochem_observer_proof']
            if($v.reason -ceq 'OBSERVER_PROOF_UNVERIFIED' -and $o -is [Collections.IDictionary] -and $o.Count -eq 2 -and
                $o.Contains('error_type') -and $o.Contains('frames') -and $o.error_type -cin @('RuntimeException','InvalidOperationException',
                    'UnauthorizedAccessException','IOException','FileNotFoundException','DirectoryNotFoundException','MethodInvocationException',
                    'ParameterBindingException','ParameterBindingValidationException','PropertyNotFoundException')){
                $safe=@()
                foreach($f in @($o.frames)){
                    if($safe.Count -eq 8){break}
                    $name=Get-OpProperty $f 'function';$line=Get-OpProperty $f 'line'
                    if($name -is [string] -and $name -cmatch '^(Assert|Read|Open|Test)-Op(Observer[A-Za-z]*|HeldObserver)$' -and
                        $line -is [int] -and $line -gt 0 -and $line -le 100000){$safe+=@{function=$name;line=$line}}
                }
                $observer=@{error_type=$o.error_type;frames=$safe}
            };break
        }
        $exception=$exception.InnerException
    }
    return @{error_type=$Record.Exception.GetType().Name;substage=$Substage;frames=$frames;process_rejection=$process;observer_proof=$observer}
}

function Set-OpSubstage {
    param([hashtable]$State,[string]$Name)
    if($null -eq $State){return}
    if((Get-OpProperty $State 'substage') -ceq $Name){return}
    $State.substage=$Name
    Write-OpStatus (Get-OpProperty $State 'phase' 'admission_fence') 'RUNNING' $null $Name
}

function Read-OpPrivateRecord {
    param([string]$Path)
    Assert-ProtectedPath $Path
    $pin=Get-428FileSha256 $Path;$s=Open-VerifiedFile $Path $pin (Get-Item -LiteralPath $Path).Length
    try{return Read-428Json $s}finally{$s.Dispose()}
}

function Get-OpDaemonArguments {
    param([string]$Config,[string]$PrivateRoot)
    return '-I -B -m cochem_pipeline daemon --config "'+$Config+'" --queue-launch-output-root "'+(Join-Path $PrivateRoot 'queue-launch-428')+'" --docker-wait-seconds 900'
}

function Assert-OpIdleHealth {
    param($Health,[int]$ExpectedPid,[string]$ExpectedInstance)
    if($Health.pid -ne $ExpectedPid -or $Health.instance_id -cne $ExpectedInstance -or
        @($Health.active).Count -or @($Health.quarantined_slots.PSObject.Properties).Count){throw 'Previous controller changed or is not idle.'}
}

function Get-OpRetainedTaskState {
    # The old runtime has a five-second SQLite writer timeout. Once the fence
    # holds its board, HTTP health may wait behind that writer and is not a
    # usable stop dependency. These native handles and task identity were
    # captured while health was still available, before requesting the fence.
    param($Task,[string]$Instance,[DateTime]$LastRunTime,$Processes,$FenceReadyAt=$null)
    if(@($Processes).Count -ne 2 -or ([DateTime]$Task.LastRunTime).ToUniversalTime() -ne $LastRunTime.ToUniversalTime()){
        throw 'Previous task run or retained native identities differ.'}
    foreach($process in $Processes){
        if($process.HasExited -and ($null -eq $FenceReadyAt -or
            ([DateTimeOffset]$process.ExitTime.ToUniversalTime()).ToUnixTimeMilliseconds()/1000.0 -lt [double]$FenceReadyAt)){
            throw 'A retained old process ended before this writer fence.'}
    }
    $instances=$Task.GetInstances(0)
    if($instances.Count -eq 1){
        if([string]$instances.Item(1).InstanceGuid -cne $Instance){throw 'Previous task instance changed.'}
        return 'RUNNING'
    }
    if($instances.Count -ne 0 -or @($Processes|Where-Object{-not $_.HasExited}).Count){
        throw 'Task ended without verified exit of both retained native processes.'}
    return 'ENDED'
}

function Stop-OpRetainedTask {
    param($Task,[string]$Instance,[DateTime]$LastRunTime,$Processes,$FenceReadyAt)
    if((Get-OpRetainedTaskState $Task $Instance $LastRunTime $Processes $FenceReadyAt) -ceq 'ENDED'){return}
    try{$Task.Stop(0)}catch{
        # A writer timeout can end the exact old instance between readback and
        # Stop(). Accept only its complete retained exit, never another run.
        if((Get-OpRetainedTaskState $Task $Instance $LastRunTime $Processes $FenceReadyAt) -cne 'ENDED'){throw}
    }
}

function Open-OpProcessProof {
    param($Health,[string]$Root,[string]$Config)
    $process=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$Health.pid)
    if($null -eq $process -or $process.ExecutablePath -cne $script:python -or
        ([string]$process.CommandLine).IndexOf('daemon --config "'+$Config+'"',[StringComparison]::Ordinal) -lt 0 -or
        (Invoke-CimMethod -InputObject $process -MethodName GetOwnerSid).Sid -cne 'S-1-5-18'){throw 'Controller native identity differs.'}
    $parent=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$process.ParentProcessId)
    if($null -eq $parent -or $parent.ExecutablePath -cne (Join-Path $Root '.venv\Scripts\python.exe') -or
        ([string]$parent.CommandLine).IndexOf('daemon --config "'+$Config+'"',[StringComparison]::Ordinal) -lt 0 -or
        (Invoke-CimMethod -InputObject $parent -MethodName GetOwnerSid).Sid -cne 'S-1-5-18'){throw 'Controller launcher identity differs.'}
    $listeners=@(Get-NetTCPConnection -LocalPort 47824 -State Listen -ErrorAction SilentlyContinue)
    if(-not $listeners.Count -or @($listeners|Where-Object{$_.OwningProcess -ne $Health.pid}).Count){throw 'Controller listener ownership differs.'}
    $held=[Collections.Generic.List[Diagnostics.Process]]::new()
    try{
        foreach($row in @($process,$parent)){
            $p=[Diagnostics.Process]::GetProcessById([int]$row.ProcessId);$null=$p.Handle
            if($p.HasExited -or [Math]::Abs(($p.StartTime.ToUniversalTime()-([DateTime]$row.CreationDate).ToUniversalTime()).TotalSeconds) -gt 1){$p.Dispose();throw 'Native process creation changed.'}
            $held.Add($p)
        };return ,$held
    }catch{foreach($p in $held){$p.Dispose()};throw}
}

function New-OpOneShot {
    param($Scheduler,$Folder,[string]$Name,[string]$Arguments,[int]$Seconds)
    $d=$Scheduler.NewTask(0);$d.Principal.UserId='SYSTEM';$d.Principal.LogonType=5;$d.Principal.RunLevel=1
    $d.Settings.Enabled=$false;$d.Settings.AllowDemandStart=$true;$d.Settings.MultipleInstances=2
    $d.Settings.RestartCount=0;$d.Settings.ExecutionTimeLimit='PT'+$Seconds+'S'
    $a=$d.Actions.Create(0);$a.Path=Join-Path $script:OpRoot '.venv\Scripts\python.exe';$a.Arguments=$Arguments;$a.WorkingDirectory=$script:OpRoot
    $task=$Folder.RegisterTaskDefinition($Name,$d,18,'SYSTEM',$null,5,'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)')
    Assert-428TaskAcl $task;$r=$task.Definition
    if($r.Triggers.Count -ne 0 -or $r.Actions.Count -ne 1 -or $r.Actions.Item(1).Type -ne 0 -or
        $r.Actions.Item(1).Path -cne $a.Path -or $r.Actions.Item(1).Arguments -cne $Arguments -or $r.Actions.Item(1).WorkingDirectory -cne $script:OpRoot -or
        $r.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or $r.Principal.LogonType -ne 5 -or $r.Principal.RunLevel -ne 1 -or
        $r.Settings.RestartCount -ne 0 -or $r.Settings.MultipleInstances -ne 2 -or -not $r.Settings.AllowDemandStart -or
        [Xml.XmlConvert]::ToTimeSpan($r.Settings.ExecutionTimeLimit).TotalSeconds -ne $Seconds -or $task.Enabled -or $task.GetInstances(0).Count){throw 'One-shot task readback differs.'}
    $task.Enabled=$true;$requested=[DateTime]::UtcNow;$instance=$task.Run($null)
    return @{name=$Name;task=$task;instance=[string]$instance.InstanceGuid;arguments=$Arguments;xml=$task.Xml;sddl=$task.GetSecurityDescriptor(7);started=$requested}
}

function Assert-OpOneShot {
    param($Handle,[bool]$Running)
    $t=$script:OpFolder.GetTask($Handle.name);Assert-428TaskAcl $t
    if($t.Xml -cne $Handle.xml -or $t.GetSecurityDescriptor(7) -cne $Handle.sddl){throw 'One-shot identity changed.'}
    $instances=$t.GetInstances(0)
    if($Running -and ($instances.Count -ne 1 -or [string]$instances.Item(1).InstanceGuid -cne $Handle.instance)){throw 'One-shot is no longer the exact running instance.'}
    return $t
}

function Wait-OpOneShot {
    param($Handle,[int]$Seconds)
    $deadline=[DateTime]::UtcNow.AddSeconds($Seconds)
    do{
        $task=Assert-OpOneShot $Handle $false
        if(Test-OpTaskTerminal $task $Handle.started){$task.Enabled=$false;return [int64]$task.LastTaskResult}
        Start-Sleep -Seconds 1
    }while([DateTime]::UtcNow -lt $deadline)
    throw 'One-shot exceeded its bound; preserve task/process state, no automatic termination or restart.'
}

function Test-OpTaskTerminal {
    param($Task,[DateTime]$Requested)
    # Run() can return before the registered task transitions from queued to
    # running. State and result are separate observations; an empty instance
    # collection/recent LastRunTime cannot override queued/running/unknown state.
    # TASK_STATE_DISABLED/READY are 1/3. The five SCHED_S values below mean
    # ready/running/disabled/never-run/queued, not completion of our new action.
    # https://learn.microsoft.com/en-us/windows/win32/taskschd/registeredtask-state
    # https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-error-and-success-constants
    return ([int]$Task.State -in @(1,3) -and $Task.GetInstances(0).Count -eq 0 -and
        [int64]$Task.LastTaskResult -notin @(0x41300,0x41301,0x41302,0x41303,0x41325) -and
        ([DateTime]$Task.LastRunTime).ToUniversalTime() -ge $Requested.AddSeconds(-2))
}

function Open-OpOneShotProcess {
    param($Handle,[int]$ProcessId)
    $child=Get-CimInstance Win32_Process -Filter ('ProcessId='+$ProcessId)
    if($null -eq $child -or $child.ExecutablePath -cne $script:python -or
        ([string]$child.CommandLine).IndexOf($Handle.arguments,[StringComparison]::Ordinal) -lt 0 -or
        (Invoke-CimMethod -InputObject $child -MethodName GetOwnerSid).Sid -cne 'S-1-5-18' -or
        ([DateTime]$child.CreationDate).ToUniversalTime() -lt $Handle.started.AddSeconds(-2)){throw 'One-shot native identity differs.'}
    $parent=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$child.ParentProcessId)
    if($null -eq $parent -or $parent.ExecutablePath -cne (Join-Path $script:OpRoot '.venv\Scripts\python.exe') -or
        ([string]$parent.CommandLine).IndexOf($Handle.arguments,[StringComparison]::Ordinal) -lt 0 -or
        (Invoke-CimMethod -InputObject $parent -MethodName GetOwnerSid).Sid -cne 'S-1-5-18' -or
        ([DateTime]$parent.CreationDate).ToUniversalTime() -lt $Handle.started.AddSeconds(-2)){throw 'One-shot launcher identity differs.'}
    $held=[Collections.Generic.List[Diagnostics.Process]]::new()
    try{
        foreach($row in @($child,$parent)){
            $p=[Diagnostics.Process]::GetProcessById([int]$row.ProcessId);$null=$p.Handle
            if($p.HasExited -or [Math]::Abs(($p.StartTime.ToUniversalTime()-([DateTime]$row.CreationDate).ToUniversalTime()).TotalSeconds) -gt 1){$p.Dispose();throw 'One-shot creation identity changed.'}
            $held.Add($p)
        };return ,$held
    }catch{foreach($p in $held){$p.Dispose()};throw}
}

function Confirm-OpPhaseStart {
    param($Handle,[string]$StartPath,[string]$Nonce,$Manifest)
    $pin=Get-428FileSha256 $StartPath;$retained=Open-428Pin $StartPath $pin
    $processes=$null
    try{
        $start=Read-OpPrivateRecord $StartPath
        if($Nonce -cnotmatch '^[0-9a-f]{32}$' -or $start.schema -cne 'cochem-owner-task-catalog-start/4.2.8' -or
            $start.nonce -cne $Nonce -or $start.bootstrap_sha256 -cne $Manifest.bootstrap_sha256 -or $start.request_sha256 -cne $Manifest.request_sha256 -or
            [double]$start.started_at -lt ([DateTimeOffset]$Handle.started).ToUnixTimeSeconds()-2 -or
            [double]$start.started_at -gt [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+2){throw 'Catalog phase start identity differs.'}
        $null=Assert-OpOneShot $Handle $true
        $processes=Open-OpOneShotProcess $Handle ([int]$start.pid)
        foreach($p in $processes){if($p.HasExited){throw 'Catalog phase exited before custody acknowledgment.'}}
        $ack=@{schema='cochem-owner-task-catalog-start-ack/4.2.8';nonce=$Nonce;start_sha256=$pin;pid=[int]$start.pid;
            bootstrap_sha256=$Manifest.bootstrap_sha256;request_sha256=$Manifest.request_sha256}
        # The phase polls this final name; publish only flushed complete bytes.
        $pending=Join-Path (Split-Path -Parent $StartPath) 'phase-start-ack.pending'
        Write-OpRecord $pending $ack
        [IO.File]::Move($pending,(Join-Path (Split-Path -Parent $StartPath) 'phase-start-ack.json'))
        return ,$processes
    }catch{if($null -ne $processes){foreach($p in $processes){$p.Dispose()}};throw}
    finally{$retained.Dispose()}
}

function Start-OpFence {
    param([string]$Label,[hashtable]$State,[string]$StateKey='fence')
    if($Label -notin @('stop-fence','restore-fence') -or $StateKey -notin @('fence','restore_fence') -or
        $null -eq $State -or $null -ne (Get-OpProperty $State $StateKey)){throw 'Fresh caller-owned fence state is required.'}
    $root=Join-Path $script:OpPrivate ($Label+'-'+[Guid]::NewGuid().ToString('N'))
    $nonce=[Guid]::NewGuid().ToString('N')
    $args='-I -B -m cochem_pipeline.owner_admission_fence_428 --config "'+$script:OpOldConfig+'" --config-sha256 '+$script:OpManifest.previous_config_sha256+
        ' --output-root "'+$root+'" --nonce '+$nonce+' --request-sha256 '+$script:OpManifest.request_sha256+' --wait-seconds 1800 --hold-seconds 240'
    $fence=@{root=$root;nonce=$nonce;arguments=$args;name=('CoChem-4.2.8-Fence-'+$nonce);intent_at=[DateTime]::UtcNow;
        owned=$false;handle=$null;ready=$null;ready_pin=$null;released=$false;process=$null;completion=$null}
    # Assignment precedes every operation that could create a task or writer lock.
    # A partial intent is evidence only and never authorizes release/stop.
    $State[$StateKey]=$fence;Set-OpSubstage $State 'fence_create_directory'
    New-OpPrivateDirectory $root
    Write-OpRecord (Join-Path $script:OpPrivate ('fence-owner-intent-'+$nonce+'.json')) @{schema='cochem-owner-admission-intent/4.2.8';nonce=$nonce;
        task_name=$fence.name;config_sha256=$script:OpManifest.previous_config_sha256;request_sha256=$script:OpManifest.request_sha256;
        requested_at=$fence.intent_at.ToString('o')}
    Set-OpSubstage $State 'fence_create_task'
    $handle=New-OpOneShot $script:OpScheduler $script:OpFolder $fence.name $args 2100
    $fence.handle=$handle;$fence.owned=$true
    $deadline=[DateTime]::UtcNow.AddSeconds(1830)
    do{
        if(Test-Path -LiteralPath (Join-Path $root 'ready.json')){
            Set-OpSubstage $State 'fence_read_ready'
            Read-OpFenceReady $fence
            Set-OpSubstage $State 'fence_validate_ready'
            Assert-OpFence $fence;return $fence
        }
        Set-OpSubstage $State 'fence_wait_ready'
        $t=Assert-OpOneShot $handle $false
        if(Test-OpTaskTerminal $t $handle.started){throw 'Admission fence ended without readiness.'}
        Start-Sleep -Seconds 1
    }while([DateTime]::UtcNow -lt $deadline)
    throw 'Admission did not drain within the bound; old runtime is preserved.'
}

function Assert-OpOwnedFence {
    param($Fence)
    if($null -eq $Fence -or -not $Fence.owned -or $null -eq $Fence.handle -or $Fence.nonce -cnotmatch '^[a-f0-9]{32}$' -or
        (Split-Path -Parent $Fence.root) -cne $script:OpPrivate -or (Split-Path -Leaf $Fence.root) -cnotmatch '^(stop|restore)-fence-[a-f0-9]{32}$' -or
        $Fence.name -cne ('CoChem-4.2.8-Fence-'+$Fence.nonce) -or $Fence.handle.name -cne $Fence.name -or
        $Fence.handle.arguments -cne $Fence.arguments -or $Fence.handle.started -lt $Fence.intent_at -or
        [string]::IsNullOrEmpty($Fence.handle.instance)){throw 'Fence ownership is incomplete or changed; preserve evidence.'}
    $expected='-I -B -m cochem_pipeline.owner_admission_fence_428 --config "'+$script:OpOldConfig+'" --config-sha256 '+$script:OpManifest.previous_config_sha256+
        ' --output-root "'+$Fence.root+'" --nonce '+$Fence.nonce+' --request-sha256 '+$script:OpManifest.request_sha256+' --wait-seconds 1800 --hold-seconds 240'
    if($Fence.arguments -cne $expected){throw 'Fence command binding differs.'}
}

function Read-OpFenceReady {
    param($Fence)
    Assert-OpOwnedFence $Fence
    $path=Join-Path $Fence.root 'ready.json';Assert-ProtectedPath $path
    $pin=Get-428FileSha256 $path;$stream=Open-428Pin $path $pin
    try{$ready=Read-428Json $stream}finally{$stream.Dispose()}
    if($null -ne $Fence.ready_pin -and $Fence.ready_pin -cne $pin){throw 'Fence readiness bytes changed.'}
    $Fence.ready=$ready;$Fence.ready_pin=$pin
}

function Assert-OpFenceBinding {
    # A release is not admission: stale readiness or nonzero accounting may
    # reject a stop while still permitting release of our exact owned lock.
    param($Fence)
    Assert-OpOwnedFence $Fence
    $r=$Fence.ready
    if($null -eq $r -or $Fence.ready_pin -cnotmatch '^[a-f0-9]{64}$' -or
        $r.schema -cne 'cochem-owner-admission-fence/4.2.8' -or $r.status -cne 'WRITER_FENCE_HELD' -or
        $r.nonce -cne $Fence.nonce -or $r.config_sha256 -cne $script:OpManifest.previous_config_sha256 -or
        $r.request_sha256 -cne $script:OpManifest.request_sha256 -or $r.database_path -cne (Join-Path $script:OpConfig.private_root 'job_board.db') -or
        [int64]$r.pid -le 0 -or $r.ready_at -lt ([DateTimeOffset]$Fence.handle.started).ToUnixTimeSeconds()-2 -or
        $r.ready_at -gt [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+2 -or $r.expires_at-$r.ready_at -ne 240){throw 'Fence readiness is unbound.'}
}

function Assert-OpFence {
    param($Fence)
    Assert-OpFenceBinding $Fence
    $r=$Fence.ready;$now=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    if($Fence.released -or $null -ne $Fence.completion -or $r.expires_at -lt $now+150){throw 'Admission fence is absent or stale.'}
    foreach($p in $r.counts.PSObject.Properties){if($p.Value -ne 0){throw 'Admission fence contains active execution.'}}
    Confirm-OpFenceProcess $Fence
}

function Confirm-OpFenceProcess {
    param($Fence)
    Assert-OpFenceBinding $Fence
    $r=$Fence.ready
    $null=Assert-OpOneShot $Fence.handle $true
    $native=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$r.pid)
    if($null -eq $native -or $native.ExecutablePath -cne $script:python -or
        ([string]$native.CommandLine).IndexOf($Fence.handle.arguments,[StringComparison]::Ordinal) -lt 0 -or
        (Invoke-CimMethod -InputObject $native -MethodName GetOwnerSid).Sid -cne 'S-1-5-18' -or
        ([DateTime]$native.CreationDate).ToUniversalTime() -lt $Fence.handle.started.AddSeconds(-2)){throw 'Admission fence native identity differs.'}
    if($null -eq $Fence.process){
        $p=[Diagnostics.Process]::GetProcessById([int]$r.pid);$null=$p.Handle
        if($p.HasExited -or [Math]::Abs(($p.StartTime.ToUniversalTime()-([DateTime]$native.CreationDate).ToUniversalTime()).TotalSeconds) -gt 1){$p.Dispose();throw 'Fence process creation changed.'}
        $Fence.process=$p
    }elseif($Fence.process.HasExited){throw 'The retained fence process has exited.'}
}

function Release-OpFence {
    param($Fence)
    if($Fence.released -or $null -ne $Fence.completion){return}
    Assert-OpOwnedFence $Fence
    Read-OpFenceReady $Fence;Assert-OpFenceBinding $Fence
    $task=Assert-OpOneShot $Fence.handle $false
    $terminal=Test-OpTaskTerminal $task $Fence.handle.started
    $sent=$false
    if(-not $terminal){
        Confirm-OpFenceProcess $Fence
        $path=Join-Path $Fence.root 'release.json'
        $release=@{schema='cochem-owner-admission-release/4.2.8';nonce=$Fence.nonce;ready_sha256=$Fence.ready_pin;request_sha256=$script:OpManifest.request_sha256}
        if(Test-Path -LiteralPath $path){
            $old=Read-OpPrivateRecord $path
            if(@($old.PSObject.Properties).Count -ne 4){throw 'Existing fence release differs.'}
            foreach($key in $release.Keys){if((Get-OpProperty $old $key) -cne $release[$key]){throw 'Existing fence release differs.'}}
        }else{
            # Atomic name publication; the fence never sees a partially written release.
            $pending=Join-Path $Fence.root 'release.pending';Write-OpRecord $pending $release
            [IO.File]::Move($pending,$path)
        }
        $sent=$true;$deadline=[DateTime]::UtcNow.AddSeconds(30)
        do{
            $task=Assert-OpOneShot $Fence.handle $false
            if(Test-OpTaskTerminal $task $Fence.handle.started){$terminal=$true;break}
            Start-Sleep -Milliseconds 100
        }while([DateTime]::UtcNow -lt $deadline)
        if(-not $terminal){throw 'Owned fence release did not reach terminal state; preserve evidence.'}
    }
    $r=Read-OpPrivateRecord (Join-Path $Fence.root 'result.json')
    $expectedStatus=if($r.released -eq $true){'LOCK_RELEASED'}else{'FENCE_EXPIRED'}
    $expectedCode=if($r.released -eq $true){0}else{2}
    if([int64]$task.LastTaskResult -ne $expectedCode -or $r.schema -cne 'cochem-owner-admission-fence/4.2.8' -or $r.status -cne $expectedStatus -or $r.nonce -cne $Fence.nonce -or
        $r.ready_sha256 -cne $Fence.ready_pin -or $r.request_sha256 -cne $script:OpManifest.request_sha256 -or
        $r.config_sha256 -cne $script:OpManifest.previous_config_sha256 -or $r.database_path -cne $Fence.ready.database_path -or
        $r.pid -ne $Fence.ready.pid -or $r.lock_released -ne $true){throw 'Admission fence terminal receipt did not verify.'}
    if($null -ne $Fence.process){
        if(-not $Fence.process.WaitForExit(5000)){throw 'Fence native process did not exit.'}
    }else{
        # Without a retained handle, only a provably different occupant of the
        # recycled PID shows that the fence process (alive at ready_at) exited.
        # No inventory follows here, so an occupant carrying this fence's nonce
        # or an unreadable Python command line also holds, independent of clocks.
        $occupied=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$r.pid)
        if($null -ne $occupied){
            $command=[string](Get-OpProperty $occupied 'CommandLine')
            if($command.IndexOf($Fence.nonce,[StringComparison]::Ordinal) -ge 0 -or
                (-not $command -and (Test-OpMayBePythonOriginal $occupied)) -or
                -not (Test-OpPidReused $occupied (ConvertFrom-OpUnixTime (Get-OpProperty $Fence.ready 'ready_at')))){
                throw 'Terminal fence PID is still occupied; preserve evidence.'}
        }
    }
    $Fence.released=$r.released -eq $true
    $Fence.completion=@{status=$r.status;lock_released=$true;native_exit_verified=$true;release_requested=$sent}
}

function Wait-OpHealth {
    param([string]$Root,[bool]$RequirePlanning,[int]$Seconds=300)
    $deadline=[DateTime]::UtcNow.AddSeconds($Seconds);$previous=$null
    do{
        try{
            $health=Get-428Health;Assert-428Health $health $Root (-not $RequirePlanning)
            if($health.version -cne '4.2.8'){throw 'Unexpected runtime version.'}
            if($RequirePlanning -and ((Get-OpProperty $health.task_planning 'status') -cne 'ENABLED' -or
                (Get-OpProperty $health.task_planning 'execution_materialization') -cne 'CONNECTED')){throw 'Task planning execution is not connected.'}
            if($null -ne $previous -and $previous.pid -eq $health.pid -and $previous.instance_id -ceq $health.instance_id){return $health}
            $previous=$health
        }catch{$previous=$null}
        Start-Sleep -Seconds 2
    }while([DateTime]::UtcNow -lt $deadline)
    throw 'Runtime health/planning/admission did not verify within its bound.'
}

function Restore-OpPrevious {
    param($State)
    if($null -ne $State.fence -and -not $State.fence.released){Release-OpFence $State.fence}
    if($State.acceptance_started){
        if(-not (Test-OpRestoreAuthority $State.acceptance $true $State.acceptance_exited $State.cutover_requested)){throw 'Catalog state does not authorize previous-runtime restoration.'}
        # Exact pinned config and stopped task must still match. A fresh writer
        # fence independently proves the board has no unreconciled native work.
        $State.restore_fence=Start-OpFence 'restore-fence' $State 'restore_fence'
        $before=$State.fence.ready.catalog;$after=$State.restore_fence.ready.catalog;$phase=$State.acceptance.publication_proof
        foreach($key in @('active_policy_sha256','active_catalog_sha256')){
            if((Get-OpProperty $before $key) -cne (Get-OpProperty $after $key) -or
                (Get-OpProperty $before $key) -cne (Get-OpProperty $phase $key)){throw 'Old catalog authority is no longer compatible with restoration.'}
        }
    }
    try{
        Assert-428PortFree;$task=$script:OpFolder.GetTask('CoChem-4.2.7-Warden')
        Assert-428WardenTask $task $script:OpOriginalXml $script:OpOriginalSddl $script:OpOldRoot $script:OpOldArgs $false $false 1
        if($task.GetInstances(0).Count){throw 'A controller is still running.'}
        $pin=Open-428Pin $script:OpOldConfig $script:OpManifest.previous_config_sha256;$pin.Dispose()
        if($null -ne $State.restore_fence){Release-OpFence $State.restore_fence}
        $definition=$script:OpScheduler.NewTask(0);$definition.XmlText=$script:OpOriginalXml;$definition.Triggers.Item(1).Enabled=$false
        $null=$script:OpFolder.RegisterTaskDefinition('CoChem-4.2.7-Warden',$definition,20,'SYSTEM',$null,5,$script:OpOriginalSddl)
        $task=$script:OpFolder.GetTask('CoChem-4.2.7-Warden');Assert-428WardenTask $task $script:OpOriginalXml $script:OpOriginalSddl $script:OpOldRoot $script:OpOldArgs $true $false 1
        # The restored Warden also waits up to 900 s for Docker (--docker-wait-seconds).
        $instance=$task.Run($null);$health=Wait-OpHealth $script:OpOldRoot $false 1200;$held=Open-OpProcessProof $health $script:OpOldRoot $script:OpOldConfig
        try{
            $task=$script:OpFolder.GetTask('CoChem-4.2.7-Warden')
            if($task.GetInstances(0).Count -ne 1 -or $task.GetInstances(0).Item(1).InstanceGuid -cne $instance.InstanceGuid){throw 'Restored task instance differs.'}
            $d=$task.Definition;$d.Triggers.Item(1).Enabled=$true
            $null=$script:OpFolder.RegisterTaskDefinition('CoChem-4.2.7-Warden',$d,20,'SYSTEM',$null,5,$script:OpOriginalSddl)
            Assert-428WardenTask ($script:OpFolder.GetTask('CoChem-4.2.7-Warden')) $script:OpOriginalXml $script:OpOriginalSddl $script:OpOldRoot $script:OpOldArgs $true $true 1
        }finally{foreach($p in $held){$p.Dispose()}}
    }finally{if($null -ne $State.restore_fence -and -not $State.restore_fence.released){try{Release-OpFence $State.restore_fence}catch{}}}
}

function Invoke-OperationalLaunch {
    param([string]$ManifestPath,[string]$ManifestHash,[bool]$ApplyRequested,[string]$Directory)
    $script:OpSitting=$null;$script:Headers428=$null;$script:OpRecovery=$null;$pins=[Collections.Generic.List[IO.Stream]]::new()
    $mutex=$null;$locked=$false;$awake=$null;$state=$null;$processes=$null
    try{
        foreach($text in @(Import-OpHelpers $Directory)){. ([scriptblock]::Create($text))}
        $s=Open-428Pin $ManifestPath $ManifestHash;$pins.Add($s);$m=Read-428Json $s;$script:OpManifest=$m
        $script:OpOldRoot='C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r4'
        $script:OpRoot='C:\Program Files\CoChem\Pipeline4.2.8-windows-20261015-r5'
        $script:OpOldConfig=Join-Path $script:OpOldRoot 'pipeline.json'
        if($m.schema -cne 'cochem-428-operational-launch/1' -or $m.previous_root -cne $script:OpOldRoot -or $m.target_root -cne $script:OpRoot -or
            $m.revision -cne 'windows-20261015-428-v5' -or $m.previous_config_sha256 -cne 'daaa4b6a8c15aa49ed39af48c087bfe2fcfefdcbae14520b298d46287414509a' -or
            $m.previous_install_sha256 -cne 'fdf93bcbec72533eca5577b2bf5fded8da11dde38e71a13b79bd58af5ca40fa3' -or
            $m.source_commit -cnotmatch '^[a-f0-9]{40}$' -or $m.request_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            $m.input_window_minutes -ne 20 -or $m.late_prompts -ne $false -or $m.catalog_timeout_seconds -ne 7200){throw 'Operational launch manifest identity differs.'}
        $seen=@{}
        foreach($row in @($m.files)){
            if($row.name -cnotmatch '^[A-Za-z0-9_.-]+$' -or $seen.ContainsKey($row.name)){throw 'Unsafe/duplicate launch input.'}
            $seen[$row.name]=$true;$pins.Add((Open-428Pin (Join-Path $Directory $row.name) $row.sha256 $row.length))
        }
        foreach($name in @('run_operational_428_launch.ps1','reviewed_428_launch_helpers.ps1','install_operational_428_runtime.ps1','stage_aetherdesk_427_payloads.ps1',
            'pipeline.json','install-manifest.json','source-test-evidence.json','operational-release.json','task-catalog-request.json')){
            if(-not $seen.ContainsKey($name)){throw 'Required operational launch input is missing.'}
        }
        if($null -ne (Get-OpProperty $m 'recovery_manifest')){
            if($m.recovery_manifest -cne 'admission-recovery.json' -or $m.recovery_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
                $m.launcher_source_commit -cnotmatch '^[a-f0-9]{40}$'){throw 'Recovery opt-in identity differs.'}
            foreach($name in @('admission-recovery.json','original-launch-manifest.json','recovery-source-test-evidence.json')){
                if(-not $seen.ContainsKey($name)){throw 'Recovery input is missing.'}
            }
            $s=Open-428Pin (Join-Path $Directory $m.recovery_manifest) $m.recovery_sha256;$pins.Add($s);$script:OpRecovery=Read-428Json $s
            $expected=Get-OpRecoveryExpected
            $s=Open-428Pin (Join-Path $Directory 'original-launch-manifest.json') $expected.original_launch_manifest_sha256;$pins.Add($s);$original=Read-428Json $s
            Assert-OpRecoveryManifest $script:OpRecovery $m $original
            $row=@($m.files|Where-Object{$_.name -ceq 'recovery-source-test-evidence.json'})[0]
            $s=Open-428Pin (Join-Path $Directory $row.name) $row.sha256 $row.length;$pins.Add($s);$evidence=Read-428Json $s
            if($evidence.schema -cne 'cochem-428-operational-recovery-source-tests/1' -or $evidence.status -cne 'PASSED' -or
                $evidence.launcher_source_commit -cne $m.launcher_source_commit -or $evidence.runtime_source_commit -cne $m.source_commit -or
                $evidence.runner -cne 'scripts/run_source_tests_428.py' -or $evidence.passed -lt 1 -or $evidence.failed -ne 0 -or
                $evidence.source_test_report_sha256 -cnotmatch '^[a-f0-9]{64}$' -or $evidence.host_acceptance_executed -ne $false){throw 'Recovery source-test evidence differs.'}
        }elseif($null -ne (Get-OpProperty $m 'launcher_source_commit') -or $null -ne (Get-OpProperty $m 'recovery_sha256')){
            throw 'Incomplete recovery opt-in is not fresh-install authority.'
        }
        foreach($text in @(Import-428Installer (Join-Path $Directory 'install_operational_428_runtime.ps1'))){. ([scriptblock]::Create($text))};Set-428Constants
        $installPath=Join-Path $Directory 'install-manifest.json';$s=Open-428Pin $installPath $m.install_manifest_sha256;$pins.Add($s);$inventory=Read-428Json $s
        $null=Get-428InstallFiles $inventory
        if($inventory.source_commit -cne $m.source_commit){throw 'Installed source and launcher differ.'}
        foreach($row in $inventory.files){$pins.Add((Open-428Pin $row.source $row.sha256 $row.length))}
        $pins.Add((Open-428Pin (Join-Path $Directory 'pipeline.json') $m.bootstrap_sha256));$pins.Add((Open-428Pin (Join-Path $Directory 'task-catalog-request.json') $m.request_sha256))
        if(-not $ApplyRequested){
            @{schema='cochem-428-operational-launch-plan/1';status='READ_ONLY_PLAN_VERIFIED';source_commit=$m.source_commit;target_root=$script:OpRoot;
                payload_files=@($inventory.files).Count;host_executed=$false;input_window_minutes=20;late_prompts=$false;maximum_shared_slots=4;pending_backlog_allowed=$true}|ConvertTo-Json;return
        }
        $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
        if($PSVersionTable.PSEdition -cne 'Desktop' -or -not [Environment]::Is64BitProcess -or $env:COMPUTERNAME -cne 'AETHERDESK' -or
            $identity.Name -cne 'AETHERDESK\ansac' -or -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
            throw 'Run once in Administrator Windows PowerShell as AETHERDESK\ansac.'}
        foreach($text in @(Import-R6CopyFunctions $Directory)){. ([scriptblock]::Create($text))};Initialize-FileIdentity
        $mutex=[Threading.Mutex]::new($false,'Global\CoChem428-OwnerSitting')
        try{$locked=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$locked=$true;throw 'Earlier owner sitting was interrupted; preserve evidence.'}
        if(-not $locked){throw 'Another owner sitting is running.'}
        if($null -eq $script:OpRecovery -and (Test-Path -LiteralPath $script:OpRoot)){throw 'Fresh r5 root already exists; preserve it, no automatic reuse.'}
        if($null -ne $script:OpRecovery -and -not (Test-Path -LiteralPath $script:OpRoot)){throw 'The exact completed r5 installation is missing.'}
        $pins.Add((Open-VerifiedFile $script:python $script:pythonPin (Get-Item -LiteralPath $script:python).Length))
        $awake=Start-428AwakeLease
        if($null -eq $script:OpRecovery){
            $script:OpSitting='C:\Program Files\CoChem\R428Operational-20261015-'+[Guid]::NewGuid().ToString('N');New-ProtectedDirectory $script:OpSitting
        }else{$script:OpSitting=New-OpRecoverySitting $script:OpRecovery $m $ManifestHash}
        $script:OpPrivate=Join-Path $script:OpSitting 'private';New-OpPrivateDirectory $script:OpPrivate
        Write-Host ('Sanitized status reports: '+$script:OpSitting+'\status-*.json')
        $state=@{phase='package';stopped=$false;verified_stopped_at_entry=$false;stop_requested=$false;cutover_requested=$false;acceptance_started=$false;acceptance_exited=$false;acceptance=$null;fence=$null;restore_fence=$null;rollback='NOT_REQUIRED';error_type=$null;health=$null;integration=$null}
        $actions=@{}
        $actions.preconditions={param($state)
            Write-OpStatus $state.phase
            Assert-ProtectedPath $script:OpOldConfig
            $s=Open-428Pin $script:OpOldConfig $m.previous_config_sha256;$pins.Add($s);$script:OpConfig=Read-428Json $s
            $pins.Add((Open-428Pin (Join-Path $script:OpOldRoot 'install-manifest.json') $m.previous_install_sha256))
            $saved=$script:targetRoot;try{$script:targetRoot=$script:OpOldRoot;$null=Assert-428Tree;Assert-428Interpreter}finally{$script:targetRoot=$saved}
            $script:Headers428=@{Authorization='Bearer '+[IO.File]::ReadAllText([string]$script:OpConfig.token_file).Trim()}
            $script:OpScheduler=New-Object -ComObject 'Schedule.Service';$script:OpScheduler.Connect();$script:OpFolder=$script:OpScheduler.GetFolder('\')
            $task=$script:OpFolder.GetTask('CoChem-4.2.7-Warden');Assert-428TaskAcl $task;$d=$task.Definition
            $script:OpOldArgs=Get-OpDaemonArguments $script:OpOldConfig $script:OpConfig.private_root
            if($null -ne $script:OpRecovery){
                Set-OpSubstage $state 'verify_original_recovery_evidence'
                Assert-OpRecoveryEvidence $script:OpRecovery $m $inventory $pins $state
                Write-Host 'Exact stopped baseline and completed r5 installation verified. No reinstall or sign-in is needed; you can walk away.' -ForegroundColor Green
                return
            }
            if($d.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or $d.Principal.LogonType -ne 5 -or $d.Principal.RunLevel -ne 1 -or
                $d.Settings.RestartCount -ne 0 -or $d.Settings.MultipleInstances -ne 2 -or $d.Triggers.Count -ne 1 -or
                $d.Triggers.Item(1).Type -ne 9 -or $d.Triggers.Item(1).UserId -cne 'AETHERDESK\ansac' -or $task.GetInstances(0).Count -ne 1){throw 'Current r4 Warden invariants differ.'}
            $script:OpOriginalXml=$task.Xml;$script:OpOriginalSddl=$task.GetSecurityDescriptor(7)
            Assert-428WardenTask $task $script:OpOriginalXml $script:OpOriginalSddl $script:OpOldRoot $script:OpOldArgs $true $true 1
            $health=Get-428Health;Assert-428Health $health $script:OpOldRoot $true
            if($health.version -cne '4.2.8'){throw 'Current runtime version differs.'}
            $state.baseline_processes=Open-OpProcessProof $health $script:OpOldRoot $script:OpOldConfig
            $state.old_pid=$health.pid;$state.old_instance=$health.instance_id
            $state.old_task_instance=[string]$task.GetInstances(0).Item(1).InstanceGuid;$state.old_task_last_run=[DateTime]$task.LastRunTime
            Write-OpRecord (Join-Path $script:OpPrivate 'baseline.json') @{xml=$script:OpOriginalXml;sddl=$script:OpOriginalSddl;health=$health;config_sha256=$m.previous_config_sha256}
            Write-Host 'Initial checks passed. Existing sign-ins are reused; no input or restart is planned. You can walk away.' -ForegroundColor Green
        }
        $actions.offline_install={param($state)
            Write-OpStatus $state.phase;$saved=$script:targetRoot
            if($null -eq $script:OpRecovery){
              foreach($name in @('install_operational_428_runtime.ps1','stage_aetherdesk_427_payloads.ps1','install-manifest.json')){
                $row=@($m.files|Where-Object{$_.name -ceq $name})[0]
                Copy-VerifiedPayload ([pscustomobject]@{source=(Join-Path $Directory $name);destination=(Join-Path $script:OpPrivate $name);sha256=$row.sha256;length=$row.length})
              }
              try{$script:targetRoot=$script:OpPrivate
                Invoke-428Native (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') @('-NoProfile','-NonInteractive','-File',
                    (Join-Path $script:OpPrivate 'install_operational_428_runtime.ps1'),'-Manifest',(Join-Path $script:OpPrivate 'install-manifest.json'),'-ManifestSha256',$m.install_manifest_sha256,'-Apply') 'offline-install' 1200
              }finally{$script:targetRoot=$saved}
              $null=Assert-428Tree;Assert-428Interpreter
              $r=Read-OpPrivateRecord (Join-Path $script:OpRoot 'install-after.json')
              if($r.status -cne 'STOPPED_RUNTIME_INSTALLED' -or $r.manifest_sha256 -cne $m.install_manifest_sha256 -or $r.source_commit -cne $m.source_commit){throw 'Fresh installation did not verify.'}
            }else{Set-OpSubstage $state 'reuse_verified_installation'}
            $script:OpRequest=Join-Path $script:OpPrivate 'task-catalog-request.json'
            Copy-VerifiedPayload ([pscustomobject]@{source=(Join-Path $Directory 'task-catalog-request.json');destination=$script:OpRequest;sha256=$m.request_sha256;length=(Get-Item -LiteralPath (Join-Path $Directory 'task-catalog-request.json')).Length})
        }
        $actions.admission_fence={param($state)
            Write-OpStatus $state.phase
            if($null -ne $script:OpRecovery){
                Set-OpSubstage $state 'recheck_stopped_recovery_baseline'
                Assert-OpRecoveryTask ($script:OpFolder.GetTask('CoChem-4.2.7-Warden')) $script:OpRecovery.warden $script:OpOldRoot $script:OpOldArgs 1
                Assert-OpRecoveryQuiescent $script:OpRecovery $null $pins $state
                Set-OpSubstage $state 'recheck_runtime_dependencies'
                Assert-OpRecoveryRuntimeDependencies (Join-Path $Directory 'pipeline.json') $m.bootstrap_sha256
                $state.fence=Start-OpFence 'stop-fence' $state 'fence'
                Assert-OpRecoveryCatalog $state.recovery_catalog $state.fence.ready.catalog;return
            }
            # Finish HTTP/native health verification before excluding writers.
            # Active work may still drain during Start-OpFence; its locked
            # durable accounting supplies the later idle/cleanup proof.
            Set-OpSubstage $state 'previous_health'
            $health=Get-428Health;Assert-428Health $health $script:OpOldRoot $true
            if($health.pid -ne $state.old_pid -or $health.instance_id -cne $state.old_instance){throw 'Previous controller changed before fencing.'}
            Set-OpSubstage $state 'previous_native_identity'
            $state.processes=Open-OpProcessProof $health $script:OpOldRoot $script:OpOldConfig
            Set-OpSubstage $state 'previous_task_identity'
            $task=$script:OpFolder.GetTask('CoChem-4.2.7-Warden')
            if($task.Xml -cne $script:OpOriginalXml -or $task.GetSecurityDescriptor(7) -cne $script:OpOriginalSddl -or
                (Get-OpRetainedTaskState $task $state.old_task_instance $state.old_task_last_run $state.processes) -cne 'RUNNING'){
                throw 'Previous task changed before fencing.'}
            $state.fence=Start-OpFence 'stop-fence' $state 'fence'
        }
        $actions.stop_previous={param($state)
            Write-OpStatus $state.phase;Assert-OpFence $state.fence
            $task=$script:OpFolder.GetTask('CoChem-4.2.7-Warden')
            if($null -ne $script:OpRecovery){
                Set-OpSubstage $state 'disable_verified_stopped_baseline'
                Assert-OpRecoveryTask $task $script:OpRecovery.warden $script:OpOldRoot $script:OpOldArgs 1
                Assert-OpRecoveryQuiescent $script:OpRecovery $state.fence $pins $state;Assert-OpFence $state.fence
                Assert-OpRecoveryCatalog $state.recovery_catalog $state.fence.ready.catalog
                # The post-disable re-check must end while the fence keeps its 150 s
                # margin (Assert-OpFence); without room for it, hold before any change.
                Set-OpSubstage $state 'fence_budget_before_trigger_disable'
                $expires=ConvertFrom-OpUnixTime (Get-OpProperty $state.fence.ready 'expires_at')
                if($null -eq $expires){throw 'Fence expiry is unreadable; hold before any task change.'}
                $notAfter=$expires.AddSeconds(-160)
                if([DateTime]::UtcNow.AddSeconds(30) -gt $notAfter){throw 'Fence validity is too short for the post-disable re-check; hold before any task change.'}
                Set-OpSubstage $state 'disable_warden_trigger'
                $d=$task.Definition;$d.Triggers.Item(1).Enabled=$false
                $null=$script:OpFolder.RegisterTaskDefinition('CoChem-4.2.7-Warden',$d,20,'SYSTEM',$null,5,$script:OpOriginalSddl)
                $task=$script:OpFolder.GetTask('CoChem-4.2.7-Warden')
                Assert-428WardenTask $task $script:OpOriginalXml $script:OpOriginalSddl $script:OpOldRoot $script:OpOldArgs $true $false 1
                if($task.GetInstances(0).Count -or [int]$task.State -ne 3 -or
                    ([DateTime]$task.LastRunTime).ToUniversalTime() -ne $state.old_task_last_run -or
                    [int64]$task.LastTaskResult -ne $script:OpRecovery.warden.last_task_result){throw 'Stopped Warden changed during trigger disable.'}
                Assert-OpRecoveryQuiescent $script:OpRecovery $state.fence $pins $state $notAfter;Assert-OpFence $state.fence
                $task.Enabled=$false
                Assert-428WardenTask $task $script:OpOriginalXml $script:OpOriginalSddl $script:OpOldRoot $script:OpOldArgs $false $false 1
                Assert-428PortFree;$state.stopped=$true;return
            }
            if($task.Xml -cne $script:OpOriginalXml -or $task.GetSecurityDescriptor(7) -cne $script:OpOriginalSddl){throw 'Old task changed before stop.'}
            $null=Get-OpRetainedTaskState $task $state.old_task_instance $state.old_task_last_run $state.processes $state.fence.ready.ready_at
            Assert-OpFence $state.fence
            $d=$task.Definition;$d.Triggers.Item(1).Enabled=$false
            $null=$script:OpFolder.RegisterTaskDefinition('CoChem-4.2.7-Warden',$d,20,'SYSTEM',$null,5,$script:OpOriginalSddl)
            $task=$script:OpFolder.GetTask('CoChem-4.2.7-Warden');Assert-428WardenTask $task $script:OpOriginalXml $script:OpOriginalSddl $script:OpOldRoot $script:OpOldArgs $true $false 1
            Assert-OpFence $state.fence;Stop-OpRetainedTask $task $state.old_task_instance $state.old_task_last_run $state.processes $state.fence.ready.ready_at
            $deadline=[DateTime]::UtcNow.AddSeconds(120)
            do{
                $task=$script:OpFolder.GetTask('CoChem-4.2.7-Warden');$gone=@($state.processes|Where-Object{-not $_.HasExited}).Count -eq 0
                if($gone -and $task.GetInstances(0).Count -eq 0){break};Start-Sleep -Seconds 1
            }while([DateTime]::UtcNow -lt $deadline)
            if(-not $gone -or $task.GetInstances(0).Count){throw 'Exact old processes did not exit; preserve state.'}
            $task.Enabled=$false;Assert-428WardenTask $task $script:OpOriginalXml $script:OpOriginalSddl $script:OpOldRoot $script:OpOldArgs $false $false 1
            Assert-428PortFree;$state.stopped=$true
        }
        $actions.release_fence={param($state)Write-OpStatus $state.phase;Release-OpFence $state.fence}
        $actions.catalog_acceptance={param($state)
            Write-OpStatus $state.phase;Assert-428PortFree
            $root=Join-Path $script:OpPrivate 'catalog-phase';New-OpPrivateDirectory $root;$state.phase_root=$root
            $nonce=[Guid]::NewGuid().ToString('N')
            $args='-I -B -m cochem_pipeline.owner_task_catalog_428 --bootstrap-config "'+(Join-Path $script:OpRoot 'pipeline.json')+'" --bootstrap-sha256 '+$m.bootstrap_sha256+
                ' --request "'+$script:OpRequest+'" --request-sha256 '+$m.request_sha256+' --output-root "'+$root+'" --timeout-seconds 7200 --start-gate --start-nonce '+$nonce
            $handle=New-OpOneShot $script:OpScheduler $script:OpFolder ('CoChem-4.2.8-Catalog-'+[Guid]::NewGuid().ToString('N')) $args 7500
            $startPath=Join-Path $root 'phase-started.json';$startDeadline=[DateTime]::UtcNow.AddSeconds(90)
            while(-not (Test-Path -LiteralPath $startPath)){
                $task=Assert-OpOneShot $handle $false
                if((Test-OpTaskTerminal $task $handle.started) -or [DateTime]::UtcNow -gt $startDeadline){throw 'Catalog phase started identity is unavailable; publication is unknown.'}
                Start-Sleep -Milliseconds 200
            }
            $state.phase_processes=Confirm-OpPhaseStart $handle $startPath $nonce $m
            $code=Wait-OpOneShot $handle 7530;$state.acceptance_exited=$true
            foreach($p in $state.phase_processes){if(-not $p.WaitForExit(5000)){$state.acceptance_exited=$false;throw 'Catalog phase native process remains; preserve state.'}}
            $path=Join-Path $root $(if($code -eq 0){'result.json'}else{'held.json'})
            $r=Read-OpPrivateRecord $path
            if($r.schema -cne 'cochem-owner-task-catalog-result/4.2.8' -or $r.request_sha256 -cne $m.request_sha256 -or $r.bootstrap_sha256 -cne $m.bootstrap_sha256){throw 'Acceptance terminal receipt is unbound.'}
            $state.acceptance=$r
            if($code -ne 0 -or $r.status -cne 'TASK_CATALOG_CANDIDATE_READY' -or $r.cleanup_verified -ne $true -or $r.runtime_resources_closed -ne $true -or
                $r.publication_state -cne 'COMMITTED' -or $r.publication_proof.catalog_probe_cleanup_verified -ne $true){throw 'Native catalog acceptance held; preserve its evidence.'}
            if($r.configuration_path -cne (Join-Path $root 'pipeline.json') -or $r.catalog_path -cne (Join-Path $root 'accepted-catalog.json')){throw 'Final configuration/catalog paths differ.'}
            $pins.Add((Open-428Pin $r.configuration_path $r.configuration_sha256));$pins.Add((Open-428Pin $r.catalog_path $r.catalog_sha256))
            $state.final_config=$r.configuration_path;$state.final_arguments=Get-OpDaemonArguments $state.final_config $script:OpConfig.private_root
        }
        $actions.cutover={param($state)
            Write-OpStatus $state.phase;Assert-428PortFree
            $task=$script:OpFolder.GetTask('CoChem-4.2.7-Warden');Assert-428WardenTask $task $script:OpOriginalXml $script:OpOriginalSddl $script:OpOldRoot $script:OpOldArgs $false $false 1
            if($task.GetInstances(0).Count){throw 'Unexpected task instance before cutover.'}
            $d=$task.Definition;$a=$d.Actions.Item(1);$a.Path=Join-Path $script:OpRoot '.venv\Scripts\python.exe';$a.WorkingDirectory=$script:OpRoot;$a.Arguments=$state.final_arguments
            $d.Settings.Enabled=$true;$d.Triggers.Item(1).Enabled=$false
            $null=$script:OpFolder.RegisterTaskDefinition('CoChem-4.2.7-Warden',$d,20,'SYSTEM',$null,5,$script:OpOriginalSddl)
            $task=$script:OpFolder.GetTask('CoChem-4.2.7-Warden');Assert-428WardenTask $task $script:OpOriginalXml $script:OpOriginalSddl $script:OpRoot $state.final_arguments $true $false 1
            $instance=$task.Run($null);$state.new_instance=[string]$instance.InstanceGuid
        }
        $actions.verify_running={param($state)
            # The new Warden may wait up to 900 s for Docker before serving health
            # (--docker-wait-seconds); allow that plus startup, as the r4 launch did.
            Write-OpStatus $state.phase;$health=Wait-OpHealth $script:OpRoot $true 1200
            $state.new_processes=Open-OpProcessProof $health $script:OpRoot $state.final_config
            $task=$script:OpFolder.GetTask('CoChem-4.2.7-Warden')
            if($task.GetInstances(0).Count -ne 1 -or [string]$task.GetInstances(0).Item(1).InstanceGuid -cne $state.new_instance){throw 'New Warden instance differs.'}
            $state.health=$health
        }
        $actions.enable_trigger={param($state)
            Write-OpStatus $state.phase;$task=$script:OpFolder.GetTask('CoChem-4.2.7-Warden')
            Assert-428WardenTask $task $script:OpOriginalXml $script:OpOriginalSddl $script:OpRoot $state.final_arguments $true $false 1
            $d=$task.Definition;$d.Triggers.Item(1).Enabled=$true
            $null=$script:OpFolder.RegisterTaskDefinition('CoChem-4.2.7-Warden',$d,20,'SYSTEM',$null,5,$script:OpOriginalSddl)
            Assert-428WardenTask ($script:OpFolder.GetTask('CoChem-4.2.7-Warden')) $script:OpOriginalXml $script:OpOriginalSddl $script:OpRoot $state.final_arguments $true $true 1
        }
        $actions.codex_preflight={param($state)
            if($null -eq (Get-OpProperty $m 'integration_manifest')){return}
            Write-OpStatus $state.phase
            if($m.integration_manifest -cne 'codex-integration.json' -or $m.integration_sha256 -cnotmatch '^[a-f0-9]{64}$'){throw 'Scoped Codex integration manifest differs.'}
            $source=Join-Path $Directory $m.integration_manifest;$s=Open-428Pin $source $m.integration_sha256;$pins.Add($s);$integration=Read-428Json $s
            if($integration.schema -cne 'cochem-codex-integration-update/1' -or $integration.source_commit -cne $m.source_commit -or
                $integration.user_home -cne 'C:\Users\ansac' -or $integration.runtime_root -cne $script:OpRoot -or
                $integration.client_config -cne 'C:\Users\ansac\CoChem427\pipeline-client-r3.json'){throw 'Scoped Codex integration identity differs.'}
            $path=Join-Path $script:OpPrivate 'codex-integration.json'
            Copy-VerifiedPayload ([pscustomobject]@{source=$source;destination=$path;sha256=$m.integration_sha256;length=(Get-Item -LiteralPath $source).Length})
            $saved=$script:targetRoot
            try{$script:targetRoot=$script:OpPrivate
                Invoke-428Native (Join-Path $script:OpRoot '.venv\Scripts\python.exe') @('-I','-B','-m','cochem_pipeline.codex_integration_428',
                    '--manifest',$path,'--manifest-sha256',$m.integration_sha256) 'codex-preflight' 120
            }finally{$script:targetRoot=$saved}
            $result=Read-OpPrivateRecord (Join-Path $script:OpPrivate 'codex-preflight.stdout.log')
            if($result.status -cne 'CODEX_UPDATE_PLAN_VERIFIED' -or $result.files_changed -ne 0){throw 'Codex integration preflight did not verify.'}
        }
        $actions.codex_integration={param($state)
            if($null -eq (Get-OpProperty $m 'integration_manifest')){return}
            Write-OpStatus $state.phase
            $path=Join-Path $script:OpPrivate 'codex-integration.json'
            $saved=$script:targetRoot
            try{$script:targetRoot=$script:OpPrivate
                Invoke-428Native (Join-Path $script:OpRoot '.venv\Scripts\python.exe') @('-I','-B','-m','cochem_pipeline.codex_integration_428',
                    '--manifest',$path,'--manifest-sha256',$m.integration_sha256,'--apply') 'codex-integration' 120
            }finally{$script:targetRoot=$saved}
            $result=Read-OpPrivateRecord (Join-Path $script:OpPrivate 'codex-integration.stdout.log')
            if($result.status -cne 'CODEX_INTEGRATION_UPDATED_REFRESH_REQUIRED' -or $result.current_session_tools_loaded -ne $false){throw 'Codex integration did not verify.'}
            $state.integration=$result
        }
        $actions.restore_previous={param($state)Restore-OpPrevious $state}
        $state=Invoke-OpTransaction $actions $state
        $record=New-OpResultRecord $state $m $ManifestHash
        Write-OpRecord (Join-Path $script:OpPrivate 'owner-result.json') $record;Write-OpStatus $state.phase $state.status $record
        $record|ConvertTo-Json -Depth 8
        if($state.status -cne 'R428_OPERATIONAL_RUNNING_VERIFIED'){throw 'Operational upgrade held. Preserve reports; do not repeat this spent launch.'}
    }finally{
        if($null -ne $state){
            foreach($key in @('baseline_processes','processes','new_processes','phase_processes','observer_processes')){if($state.ContainsKey($key)){foreach($p in $state[$key]){$p.Dispose()}}}
            foreach($key in @('fence','restore_fence')){
                if($null -ne $state[$key] -and -not $state[$key].released){try{Release-OpFence $state[$key]}catch{}}
                if($null -ne $state[$key] -and $null -ne $state[$key].process){$state[$key].process.Dispose()}
            }
        }
        foreach($s in $pins){$s.Dispose()}
        if($locked){$mutex.ReleaseMutex()};if($null -ne $mutex){$mutex.Dispose()}
        if($null -ne $awake){Stop-428AwakeLease $awake};$script:Headers428=$null
    }
}

$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
if(-not $LaunchManifest){throw 'A pinned operational launch manifest is required.'}
Invoke-OperationalLaunch ([IO.Path]::GetFullPath($LaunchManifest)) $LaunchManifestSha256 ([bool]$Apply) $PSScriptRoot
