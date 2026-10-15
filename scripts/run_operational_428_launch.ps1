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

function Assert-OpRecoveryQuiescent {
    param($Recovery,$AllowedFence=$null)
    Assert-428PortFree
    foreach($id in @($Recovery.warden.pid,$Recovery.fence.pid)){
        $occupied=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$id)
        if($null -ne $occupied){throw (New-OpProcessRejection $occupied 'PRESERVED_PID_OCCUPIED')}
    }
    # Read-only bounded inventory. MCP clients are permitted only in their exact
    # module form; no daemon, provider, unknown launcher or competing owner phase
    # is accepted merely because the task has zero visible instances.
    $rows=@(Get-CimInstance Win32_Process)
    if($rows.Count -gt 4096){throw 'Recovery native inventory exceeds bound.'}
    $byId=@{};foreach($row in $rows){$byId[[int]$row.ProcessId]=$row}
    foreach($row in $rows){
        $image=[string]$row.ExecutablePath;$command=[string]$row.CommandLine
        $reason=Get-OpPipelineProcessReason $image $command ([string](Get-OpProperty $row 'Name'))
        if($null -eq $reason){continue}
        if(Test-OpExactMcpProcess $image $command){continue}
        if($null -ne $AllowedFence -and $command.IndexOf($AllowedFence.arguments,[StringComparison]::Ordinal) -ge 0 -and
            (([int]$row.ProcessId -eq [int]$AllowedFence.ready.pid -and $image -ceq $script:python) -or
             ($image -ceq (Join-Path $script:OpRoot '.venv\Scripts\python.exe') -and
              $byId.ContainsKey([int]$AllowedFence.ready.pid) -and
              [int]$byId[[int]$AllowedFence.ready.pid].ParentProcessId -eq [int]$row.ProcessId))){continue}
        throw (New-OpProcessRejection $row $reason)
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
    if($Image.StartsWith($script:OpOldRoot+'\',[StringComparison]::OrdinalIgnoreCase) -or
        $Image.StartsWith($script:OpRoot+'\',[StringComparison]::OrdinalIgnoreCase)){return 'RUNTIME_IMAGE'}
    $base=if($Image){[IO.Path]::GetFileName($Image)}else{$Name}
    if($base -match '^(?:python(?:w|[0-9]+(?:\.[0-9]+)?)?|py)\.exe$'){
        if(-not $Image -or -not $Command){return 'UNINSPECTABLE_PYTHON'}
        if($Command -match 'cochem_(?:pipeline|mcp|supervisor)'){return 'PIPELINE_PYTHON'}
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
    $script:OpOriginalXml=$baseline.xml;$script:OpOriginalSddl=$baseline.sddl
    Assert-OpRecoveryTask ($script:OpFolder.GetTask('CoChem-4.2.7-Warden')) $Recovery.warden $script:OpOldRoot $script:OpOldArgs 1
    $fargs='-I -B -m cochem_pipeline.owner_admission_fence_428 --config "'+$script:OpOldConfig+'" --config-sha256 '+$Manifest.previous_config_sha256+
        ' --output-root "'+$froot+'" --nonce '+$Recovery.fence.nonce+' --request-sha256 '+$Manifest.request_sha256+' --wait-seconds 1800 --hold-seconds 240'
    Assert-OpRecoveryTask ($script:OpFolder.GetTask('CoChem-4.2.8-Fence-'+$Recovery.fence.nonce)) $Recovery.fence $script:OpRoot $fargs 0
    Assert-OpRecoveryQuiescent $Recovery
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
    $process=$null;$exception=$Record.Exception
    for($i=0;$i -lt 4 -and $null -ne $exception;$i++){
        $v=$exception.Data['cochem_recovery_process']
        if($v -is [Collections.IDictionary] -and $v.Count -eq 4 -and
            $v.Contains('pid') -and $v.Contains('name') -and $v.Contains('reason') -and $v.Contains('command_sha256') -and
            ($v.pid -is [int] -or $v.pid -is [long]) -and $v.pid -gt 0 -and $v.pid -le [uint32]::MaxValue -and
            $v.name -is [string] -and $v.reason -is [string] -and
            $v.name -cin @('python.exe','pythonw.exe','py.exe','node.exe','powershell.exe','pwsh.exe','cmd.exe','cochem-pipeline.exe','cochem-supervisor.exe','uv.exe','other') -and
            $v.reason -cin @('PROTECTED_PYTHON','RUNTIME_IMAGE','PIPELINE_PYTHON','UNINSPECTABLE_PYTHON','PIPELINE_ENTRYPOINT','PRESERVED_PID_OCCUPIED') -and
            $v.command_sha256 -is [string] -and $v.command_sha256 -cmatch '^[a-f0-9]{64}$'){
            $process=@{pid=$v.pid;name=$v.name;reason=$v.reason;command_sha256=$v.command_sha256};break
        }
        $exception=$exception.InnerException
    }
    return @{error_type=$Record.Exception.GetType().Name;substage=$Substage;frames=$frames;process_rejection=$process}
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
    }elseif($null -ne (Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$r.pid))){throw 'Terminal fence PID is still occupied; preserve evidence.'}
    $Fence.released=$r.released -eq $true
    $Fence.completion=@{status=$r.status;lock_released=$true;native_exit_verified=$true;release_requested=$sent}
}

function Wait-OpHealth {
    param([string]$Root,[bool]$RequirePlanning)
    $deadline=[DateTime]::UtcNow.AddSeconds(300);$previous=$null
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
        $instance=$task.Run($null);$health=Wait-OpHealth $script:OpOldRoot $false;$held=Open-OpProcessProof $health $script:OpOldRoot $script:OpOldConfig
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
                Assert-OpRecoveryQuiescent $script:OpRecovery
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
                Assert-OpRecoveryQuiescent $script:OpRecovery $state.fence;Assert-OpFence $state.fence
                Assert-OpRecoveryCatalog $state.recovery_catalog $state.fence.ready.catalog
                $d=$task.Definition;$d.Triggers.Item(1).Enabled=$false
                $null=$script:OpFolder.RegisterTaskDefinition('CoChem-4.2.7-Warden',$d,20,'SYSTEM',$null,5,$script:OpOriginalSddl)
                $task=$script:OpFolder.GetTask('CoChem-4.2.7-Warden')
                Assert-428WardenTask $task $script:OpOriginalXml $script:OpOriginalSddl $script:OpOldRoot $script:OpOldArgs $true $false 1
                if($task.GetInstances(0).Count -or [int]$task.State -ne 3 -or
                    ([DateTime]$task.LastRunTime).ToUniversalTime() -ne $state.old_task_last_run -or
                    [int64]$task.LastTaskResult -ne $script:OpRecovery.warden.last_task_result){throw 'Stopped Warden changed during trigger disable.'}
                Assert-OpRecoveryQuiescent $script:OpRecovery $state.fence;Assert-OpFence $state.fence
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
            Write-OpStatus $state.phase;$health=Wait-OpHealth $script:OpRoot $true
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
            foreach($key in @('baseline_processes','processes','new_processes','phase_processes')){if($state.ContainsKey($key)){foreach($p in $state[$key]){$p.Dispose()}}}
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
