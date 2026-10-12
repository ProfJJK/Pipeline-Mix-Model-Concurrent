#Requires -Version 5.1
<# Reviewed one-shot SYSTEM upgrade preview of the r5 runtime: r5 sitting stage S10, build-manifest step 14.
   Derived from agy-status-capture-r4-v1.ps1 (one-shot SYSTEM task registration, wait, receipt verification, held
   records) and retarget-warden-r5.ps1 (content binding of the r5 install and of the staged r5 configuration, whose
   functions are imported by hash). Every reviewed helper is imported by hash; the top level is a single invocation so
   fixtures can dot-source the functions from the AST without running anything.

   Usage (owner, elevated 64-bit Windows PowerShell 5.1 on AETHERDESK for -Apply; without -Apply a read-only plan):
     run-upgrade-preview-r5-v1.ps1 -Attempt <32 lowercase hex> -CandidateSha256 <staging receipt candidate sha256> [-Apply]
       [-InstallRoot <C:\Program Files\CoChem\Pipeline4.2.7-windows-<date>-r5>] [-Candidate <staged WardenConfig...-r5-vN\pipeline.json>]
       [-Current <commissioned pipeline.json>]

   The default plan (cochem-upgrade-preview-r5-plan/1) reads only; it registers, runs and creates nothing.
   -Apply:
     1. binds the one installed r5 runtime by content (Assert-R5InstalledBindings: install-after.json mode
        FRESH_STOPPED_RUNTIME_READY on top of the pinned r4 receipt, the pinned r5 freeze manifest and its 13 reviewed repair
        digests including __main__.py, the pinned pyvenv.cfg and venv interpreter), the commissioned configuration 135cd9ec
        and the staged candidate (Assert-R5Config: the commissioned bytes = held mode, or only providers.gemini changed =
        enabled mode, with the stager's receipt beside it, and equal to -CandidateSha256); in enabled mode it also records
        the per-provider digests of both bound files for the gate;
        inspects the r5 and toolchain code trees once and requires no existing preview root or task;
     2. creates C:\Program Files\CoChem\UpgradePreview4.2.7-windows-20261011-r5-v1-<attempt> with a SYSTEM/BA-only DACL,
        copies the hash-pinned run_upgrade_preview_r5_v1.py and writes preview-intent.json before any task exists;
     3. registers ONE trigger-free SYSTEM task CoChem-4.2.7-UpgradePreview-20261011-r5-v1-<attempt> (PT3M, private task
        DACL) running '<r5 python> -I -B <root>\run_upgrade_preview_r5_v1.py ...', requests exactly one Run and waits;
     4. verifies upgrade-preview-receipt.json against the bindings, re-reads upgrade-preview.json by its sha256, recomputes
        the S10 gate and writes preview-summary.json. Gate: read_only true; native_models_executed false; no changed
        identity; no changed protected path except the configuration path swap; database.exists true;
        database.schema_changes []; configuration_changes keys within ['providers'] ([] in held mode); in enabled mode
        (deploy audit B-F5) the per-provider sha256 of providers.<name> (compact JSON) read from the two bound files at
        binding time differ for 'gemini' only.
   A failed gate prints the summary with a SERIES-STOP message (R4-RESTORE, or an explicit owner waiver line in the series
   log) and exits non-zero. Any failure after the root exists leaves preview-held.json. Nothing is ever retried, deleted,
   stopped or killed; the task and the root are preserved as evidence. No model, provider, database or task other than
   this one-shot preview task is touched. #>
[CmdletBinding()]
param(
    [ValidatePattern('^[a-f0-9]{32}$')][string]$Attempt='00000000000000000000000000000000',
    [string]$InstallRoot='',
    [string]$Current='C:\Program Files\CoChem\WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json',
    [string]$Candidate='C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-r5-v1\pipeline.json',
    [string]$CandidateSha256='',
    [switch]$Apply
)

function Import-ReviewedFunctions {
    param([string]$Path,[string]$Hash,[string[]]$Names)
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try{
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$actual=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        if($actual -cne $Hash){throw ('Reviewed function source changed: '+$Path)}
        $stream.Position=0;$reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true,4096,$true)
        $tokens=$null;$errors=$null;try{$ast=[Management.Automation.Language.Parser]::ParseInput($reader.ReadToEnd(),[ref]$tokens,[ref]$errors)}finally{$reader.Dispose()}
        if($errors.Count){throw 'Reviewed helper parse failure.'}
        foreach($name in $Names){
            $nodes=@($ast.FindAll({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object {$_.Name -ceq $name})
            if($nodes.Count -ne 1){throw ('Expected exactly one reviewed definition of '+$name)}
            $nodes[0].Extent.Text}
    }finally{$stream.Dispose()}
}

function Set-PreviewConstants {
    param([string]$Attempt,[string]$Workspace)
    $script:Attempt=$Attempt;$script:workspace=$Workspace
    # The v2.2 / retarget-warden-r5 pin block (values unchanged) used by the imported Assert-R5InstalledBindings and Assert-R5Config.
    $script:programFiles='C:\Program Files';$script:base=Join-Path $script:programFiles 'CoChem'
    $script:r3Root=Join-Path $script:base 'Pipeline4.2.7-windows-20261007-r3'
    $script:r4Root=Join-Path $script:base 'Pipeline4.2.7-windows-20261009-r4'
    $script:basePythonRoot=Join-Path $script:base 'Toolchain4.2.7-windows-20261006\Python312';$script:basePython=Join-Path $script:basePythonRoot 'python.exe'
    $script:probePythonPin='d8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa'
    $script:configPin='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
    $script:r3RevisionPin='309eb48d9b1c43179ae1f0784d0139357168314f8312a64fb84dbd8380d44eb4'
    $script:r4ManifestPin='1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189'
    $script:r4InstallPin='629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502';$script:r4RevisionPin='38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e'
    $script:commissioningConfig=Join-Path $script:base 'WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json'
    $script:r4RestoreConfig=Join-Path $script:r4Root 'pipeline.json'
    $script:r5RootPattern='^Pipeline4\.2\.7-windows-[0-9]{8}-r5$'
    $script:r5ConfigPattern='^C:\\Program Files\\CoChem\\WardenConfig4\.2\.7-windows-[0-9]{8}-r5-v[0-9]{1,3}\\pipeline\.json$'
    # The reviewed r5 freeze (W\stopped-runtime-r5-source-manifest.json, source commit 8554c7645801a7bc9c4abad4861bfcbe4ed014b0):
    # its manifest sha, the 13 repair digests of its reviewed_repairs_sha256 map, and the venv bytes the installer pins.
    $script:r5SourceManifestPin='5d8d337baebbc1e4ac29439d418333ab41c0999eb8c0ef8b02acee66850a3045'
    $script:r5RepairPins=[ordered]@{'src/cochem_pipeline/__main__.py'='19f24fc7bcd4d6d0133386aff916efc3ceb6fb359d8604041ef17bdab931b1b3';
        'src/cochem_pipeline/agy_protocol.py'='eaf8d1f407c8792be1343c657afabcf370992df3f82cd9dfb7fe13cf9d41545e';'src/cochem_pipeline/coding.py'='0b97d7bdec4e5c4a1b8f3d1ca8a974f3205d838c6e275e3cc66c5c9826998174';
        'src/cochem_pipeline/config.py'='908e61267a6133379fad7b26b7452e03f1deb97f44f53eb9e26c07de8212bbd4';'src/cochem_pipeline/controller_guard.py'='e18304719af11e0dd5280d777c6157cc9bc873dd29b7dc15527d6b3667656eba';
        'src/cochem_pipeline/failures.py'='625f9c6e045f6a108be04a6a13767593db08ac960bb3839fade0a37e36c6edf5';'src/cochem_pipeline/knowledge.py'='1bf720ed5df342704552b3e0996ee1cdaebd8f9d7f26fc345b4e5a848e2d2f0f';
        'src/cochem_pipeline/operator_views.py'='8b6b51e9ef3879ad13f714ee44390fc4bb7e41cc9bf5c7cbdc589413f1efaf42';'src/cochem_pipeline/runtime.py'='946adaf95b1755138f0e7bf79576c8290569d7fb98851e8962e00ca73b40a208';
        'src/cochem_pipeline/service.py'='38ab9dc1853dc38b0ee824a1f80f5e4bea503ec2e821c7803b065baa501c5128';'src/cochem_pipeline/store.py'='b3604d227b23d2f3a68e0106b852ad672127089df68b0d512131455fa552d0a0';
        'src/cochem_pipeline/worker.py'='20a084071bfa172aa787d1a96168b8c541089823559e8f00518b164c16ae0f41';'src/cochem_supervisor/runner.py'='adc8ccf33841438f3104e64325ff84b7826c49db297c8bc3f02ebb55ad96cf31'}
    $script:r5PyvenvPin='0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d';$script:r5VenvPythonPin='560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'
    $script:r5VerifiedUnchanged=153
    # The stager's receipt (stage-pipeline-config-r5-v1.ps1) beside every staged r5 configuration; a held staging record refuses it.
    $script:stagingReceiptSchema='cochem-config-only-staging/2';$script:stagingReceiptPattern='^staging-receipt-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.json$'
    $script:installRootPattern='^C:\\Program Files\\CoChem\\Pipeline4\.2\.7-windows-[0-9]{8}-r5$'
    $script:helperName='run_upgrade_preview_r5_v1.py';$script:helperSource=Join-Path $Workspace $script:helperName
    $script:helperPin='71e0383272057ab7be59f339a9dcb0c57e74ac5329f46d575cc49cde62816051'
    # Fixed namespace date of this sitting; -Attempt selects the namespace, never reused.
    $script:namespaceDate='20261011'
    $script:targetRoot=Join-Path $script:base ('UpgradePreview4.2.7-windows-'+$script:namespaceDate+'-r5-v1-'+$Attempt)
    $script:taskName='CoChem-4.2.7-UpgradePreview-'+$script:namespaceDate+'-r5-v1-'+$Attempt
    $script:taskSddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)';$script:taskTimeLimit='PT3M';$script:taskWaitSeconds=175
    $script:daemonTaskNames=@('CoChem-4.2.7-Warden','CoChem-4.2.7-Supervisor','CoChem-4.2.2-Warden','CoChem-4.2.3-Supervisor')
    $script:receiptName='upgrade-preview-receipt.json';$script:previewName='upgrade-preview.json';$script:runnerHeldName='upgrade-preview-held.json'
    $script:receiptMaxBytes=1048576;$script:previewMaxBytes=67108864
    $script:allowedConfigurationKeys=@('providers');$script:allowedChangedProviders=@('gemini')
    # The helper's REASONS, FAILURE_PHASES and FAILURE_REASONS (a test compares the lists).
    $script:gateReasons=@('PREVIEW_SCHEMA_INVALID','READ_ONLY_NOT_TRUE','NATIVE_MODELS_EXECUTED','CURRENT_BINDING_DIFFERS','PROPOSED_BINDING_DIFFERS',
        'IDENTITIES_MALFORMED','IDENTITIES_CHANGED','PROTECTED_PATHS_MALFORMED','PROTECTED_PATHS_CHANGED','DATABASE_MALFORMED','DATABASE_NOT_PRESENT',
        'SCHEMA_CHANGES_MALFORMED','SCHEMA_CHANGES_PRESENT','MIGRATION_EXECUTED','CONFIGURATION_CHANGES_MALFORMED','CONFIGURATION_CHANGES_OUTSIDE_PROVIDERS',
        'CONFIGURATION_CHANGES_IN_HELD_MODE','PROVIDER_DIGESTS_MALFORMED','PROVIDERS_CHANGED_OUTSIDE_GEMINI')
    $script:failurePhases=@('install_binding','config_binding','preview_launch','preview_output','gate','output')
    $script:failureReasons=@('INSTALL_BINDING_DIFFERS','CONFIG_BINDING_DIFFERS','PREVIEW_LAUNCH_FAILED','PREVIEW_TIMED_OUT','PREVIEW_EXIT_NONZERO',
        'PREVIEW_OUTPUT_TOO_LARGE','PREVIEW_OUTPUT_MALFORMED','GATE_EVALUATION_FAILED','OUTPUT_WRITE_FAILED','UNEXPECTED_ERROR')
    $script:statusExitCodes=[ordered]@{UPGRADE_PREVIEW_GATE_PASSED=0;UPGRADE_PREVIEW_GATE_FAILED=3;UPGRADE_PREVIEW_FAILED=4}
}

function Assert-PreviewParameters {
    param($Arguments)
    # Formats only; nothing is read before these pass.
    $attempt=[string]$Arguments.Attempt;$sha=[string]$Arguments.CandidateSha256;$root=[string]$Arguments.InstallRoot;$apply=[bool]$Arguments.Apply
    if($attempt -cnotmatch '^[a-f0-9]{32}$' -or ($apply -and $attempt -ceq '00000000000000000000000000000000')){throw 'A lowercase 32-hex -Attempt is required; -Apply forbids the all-zero preview attempt. Nothing was changed.'}
    if($sha -and $sha -cnotmatch '^[a-f0-9]{64}$'){throw '-CandidateSha256 must be the lowercase sha256 from the staging receipt. Nothing was changed.'}
    if($apply -and -not $sha){throw '-Apply requires -CandidateSha256 from the staging receipt (cochem-config-only-staging/2). Nothing was changed.'}
    if($root -and $root -cnotmatch '^C:\\Program Files\\CoChem\\Pipeline4\.2\.7-windows-[0-9]{8}-r5$'){throw '-InstallRoot must be C:\Program Files\CoChem\Pipeline4.2.7-windows-<date>-r5. Nothing was changed.'}
    [ordered]@{attempt=$attempt;install_root=$root;current=[string]$Arguments.Current;candidate=[string]$Arguments.Candidate;candidate_sha256=$sha;apply=$apply}
}

function Initialize-PreviewHost {
    foreach($module in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$module\$module.psd1") -ErrorAction Stop}
    if($PSVersionTable.PSEdition -ne 'Desktop' -or -not [Environment]::Is64BitProcess -or $env:COMPUTERNAME -cne 'AETHERDESK'){throw 'Use 64-bit Windows PowerShell 5.1 on AETHERDESK.'}
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    [pscustomobject]@{admin=[Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator);name=[string]$identity.Name}
}

function Assert-PreviewApplyIdentity {
    param([bool]$ApplyRequested,$HostContext)
    if($ApplyRequested -and (-not [bool]$HostContext.admin -or [string]$HostContext.name -cne 'AETHERDESK\ansac')){throw '-Apply requires the owner in Administrator Windows PowerShell; nothing was changed.'}
}

function Import-PreviewHelpers {
    # Dot-sourced by Invoke-UpgradePreviewMain, so the reviewed functions are defined in its scope (hash-pinned).
    $copyHelper='C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1'
    foreach($text in Import-ReviewedFunctions $copyHelper '0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b' @('Assert-NoReparseAncestors','Assert-ProtectedPath','New-CodeAcl','Initialize-FileIdentity','Open-VerifiedFile','Copy-VerifiedPayload')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $script:workspace 'check-worker-native-status-r3.ps1') '18f58ebb448d8a0c6329dd187d4a9a27fa9cbe942cd05e906bb7aabc67e787a7' @('Read-R3Control','Read-R3Text')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $script:workspace 'register-stopped-warden-r3.ps1') 'eccc593f36cbf488a54775b4343bcf3cf8b261b7cd81e5536fb7f2f18466a198' @('Assert-RegisteredTaskAcl','Write-RegistrationControl')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $script:workspace 'protected-code-inspection-v4.ps1') '5c01543cbb8b8d64b2b9f1bab4a13f87f8ff9e1ab3e82dfb6fc547144c77b95d' @('Assert-CodeTreeOnce')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $script:workspace 'retarget-warden-r4.ps1') '8ee6b412f6be176dfac7c2c1b2340f1973e08358c7d22da6d4515e79f0327a4e' @('Test-ExactBool','Test-ExactInt','New-PrivateAcl','Assert-PrivateAcl','New-PrivateDirectory')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $script:workspace 'retarget-warden-r5.ps1') '991703ab10b7bf280fb092ec984e79d1095379070857e7c2859d0a5ba0c0dee7' @('Test-Sha256Text','Get-JsonMember','Get-JsonProperty','Get-JsonListField','Get-R5RootCandidates','Find-R5Root','Assert-R5InstalledBindings','Assert-R5Config','Assert-StagingReceipt','Read-JsonControl')){. ([scriptblock]::Create($text))}
    Initialize-FileIdentity
}

function Connect-TaskFolder {
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect()
    [pscustomobject]@{scheduler=$scheduler;folder=$scheduler.GetFolder('\')}
}

function Get-PreviewTaskArguments {
    param([string]$Destination,[string]$Nonce,$Context)
    '-I -B "'+$Destination+'" --attempt '+$script:Attempt+' --nonce '+$Nonce+' --install-root "'+$Context.install_root+'" --install-after-sha256 '+$Context.install_after_sha256+
        ' --venv-python-sha256 '+$Context.venv_python_sha256+' --current "'+$Context.current_path+'" --current-sha256 '+$Context.current_sha256+
        ' --proposed "'+$Context.proposed_path+'" --proposed-sha256 '+$Context.proposed_sha256+' --mode '+$Context.mode+
        ' --output "'+(Join-Path $script:targetRoot $script:previewName)+'"'
}

function New-PreviewNonce {[Guid]::NewGuid().ToString('N')}

function Get-TaskPresence {
    param($Folder,[string]$Name)
    try{$null=$Folder.GetTask($Name);return 'PRESENT'}catch{
        $errorItem=$_.Exception
        while($null -ne $errorItem){
            if($errorItem.HResult -eq -2147024894){return 'ABSENT'}
            if($errorItem.HResult -eq -2147024891){return 'PRESENT_UNREADABLE'}
            $errorItem=$errorItem.InnerException}
        throw ('Task Scheduler state is unknown for '+$Name)}
}

function Get-DaemonTaskObservations {
    param($Folder)
    # Informational only: the preview opens the job board read-only, so it is valid with the Warden up or down (A1).
    foreach($name in $script:daemonTaskNames){
        $task=$null;$state='UNKNOWN'
        try{$task=$Folder.GetTask($name)}catch{
            $errorItem=$_.Exception
            while($null -ne $errorItem){
                if($errorItem.HResult -eq -2147024894){$state='ABSENT';break}
                if($errorItem.HResult -eq -2147024891){$state='ACCESS_DENIED_DEFERRED';break}
                $errorItem=$errorItem.InnerException}}
        if($null -eq $task){[pscustomobject]@{name=$name;state=$state;enabled=$null;task_state=$null;instances=$null};continue}
        try{[pscustomobject]@{name=$name;state='PRESENT';enabled=[bool]$task.Enabled;task_state=[int]$task.State;instances=[int]$task.GetInstances(0).Count}}
        catch{[pscustomobject]@{name=$name;state='ACCESS_DENIED_DEFERRED';enabled=$null;task_state=$null;instances=$null}}
    }
}

function Resolve-R5Install {
    param([string]$Requested)
    # The one installed r5 root, bound by content exactly as retarget-warden-r5 binds it for S11.
    $found=Find-R5Root
    if($Requested -and $Requested -cne $found){throw ('-InstallRoot '+$Requested+' is not the one installed r5 runtime root '+$found+'.')}
    Assert-R5InstalledBindings $found
}

function Assert-CurrentConfig {
    param([string]$Path)
    if($Path -cne $script:commissioningConfig -and $Path -cne $script:r4RestoreConfig){
        throw ('The current configuration must be the commissioned '+$script:commissioningConfig+' or its r4 reference copy '+$script:r4RestoreConfig+'.')}
    $control=Read-R3Control $Path $script:configPin 1048576
    [ordered]@{path=$Path;sha256=$control.Sha256;length=$control.Length}
}

function Resolve-Candidate {
    param([string]$Path,[string]$ExpectedSha256)
    $binding=Assert-R5Config $Path
    if($ExpectedSha256 -and $binding.sha256 -cne $ExpectedSha256){throw ('The staged candidate sha256 '+$binding.sha256+' differs from the staging receipt sha256 '+$ExpectedSha256+'.')}
    $binding
}

function Get-ProviderDigests {
    param([string]$Path,[string]$Sha256)
    # Deploy audit B-F5: the sha256 of each providers.<name> value (compact JSON in document order) of one bound file, read
    # by its sha256; names compare ordinally (case-sensitive). $null when the file has no providers object.
    $control=Read-R3Control $Path $Sha256 1048576
    $document=$null;try{$document=(Read-R3Text $control)|ConvertFrom-Json}catch{throw ('A bound configuration is not JSON: '+$Path)}
    $providers=Get-JsonMember $document 'providers'
    if($providers -isnot [Management.Automation.PSCustomObject]){return $null}
    $digests=[Collections.Generic.SortedDictionary[string,string]]::new([StringComparer]::Ordinal)
    $sha=[Security.Cryptography.SHA256]::Create()
    try{
        foreach($member in $providers.PSObject.Properties){
            $json=ConvertTo-Json -InputObject $member.Value -Depth 64 -Compress
            $digests[[string]$member.Name]=[BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]$json))).Replace('-','').ToLowerInvariant()}
    }finally{$sha.Dispose()}
    ,$digests
}

function New-PreviewContext {
    param($R5,$CurrentBinding,$CandidateBinding)
    # Held mode is the commissioned bytes, whichever path holds them; any other candidate is the providers.gemini contract.
    $mode=$(if($CandidateBinding.sha256 -ceq $script:configPin){'held'}else{'enabled'})
    $currentDigests=$null;$proposedDigests=$null
    if($mode -ceq 'enabled'){$currentDigests=Get-ProviderDigests $CurrentBinding.path $CurrentBinding.sha256;$proposedDigests=Get-ProviderDigests $CandidateBinding.path $CandidateBinding.sha256}
    [ordered]@{install_root=$R5.root;python=$R5.python;install_after_path=$R5.install_after_path;install_after_sha256=$R5.install_after_sha256;
        venv_python_sha256=$R5.venv_python_sha256;source_manifest_sha256=$R5.source_manifest_sha256;revision_sha256=$R5.revision_sha256;
        reviewed_repairs=@($R5.reviewed_repairs);current_path=$CurrentBinding.path;current_sha256=$CurrentBinding.sha256;
        proposed_path=$CandidateBinding.path;proposed_sha256=$CandidateBinding.sha256;candidate_mode=$CandidateBinding.mode;mode=$mode;
        current_providers_sha256=$currentDigests;proposed_providers_sha256=$proposedDigests}
}

function New-PreviewTaskDefinition {
    param($Scheduler,[string]$Destination,[string]$Nonce,$Context)
    $definition=$Scheduler.NewTask(0)
    $definition.RegistrationInfo.Description='One read-only r5 upgrade preview (sitting S10): cochem_pipeline upgrade-preview with the r5 interpreter, the commissioned 135cd9ec configuration against the staged r5 candidate, job board opened read-only. No model, provider, database, configuration or task change; no retry.'
    $definition.Principal.UserId='SYSTEM';$definition.Principal.LogonType=5;$definition.Principal.RunLevel=1
    $definition.Settings.Enabled=$true;$definition.Settings.AllowDemandStart=$true
    $definition.Settings.MultipleInstances=2;$definition.Settings.ExecutionTimeLimit=$script:taskTimeLimit;$definition.Settings.RestartCount=0
    $action=$definition.Actions.Create(0);$action.Path=$Context.python
    $action.Arguments=Get-PreviewTaskArguments $Destination $Nonce $Context
    $action.WorkingDirectory=$script:targetRoot
    $definition
}

function Assert-PreviewTaskRegistration {
    param($Task,[string]$Destination,[string]$Nonce,$Context)
    $definition=$Task.Definition
    if($Task.Enabled -ne $true -or $Task.State -notin @(1,3) -or $Task.GetInstances(0).Count -ne 0 -or
       $definition.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or $definition.Principal.LogonType -ne 5 -or $definition.Principal.RunLevel -ne 1 -or
       $definition.Settings.AllowDemandStart -ne $true -or $definition.Settings.MultipleInstances -ne 2 -or $definition.Settings.RestartCount -ne 0 -or
       $definition.Settings.ExecutionTimeLimit -cne $script:taskTimeLimit -or $definition.Triggers.Count -ne 0 -or $definition.Actions.Count -ne 1){
        throw 'The preview task is not the exact idle, trigger-free, bounded SYSTEM definition.'}
    $action=$definition.Actions.Item(1)
    if($action.Type -ne 0 -or $action.Path -cne $Context.python -or $action.Arguments -cne (Get-PreviewTaskArguments $Destination $Nonce $Context) -or
       $action.WorkingDirectory -cne $script:targetRoot){throw 'The registered preview action differs from the bound r5 interpreter, helper and arguments.'}
    Assert-RegisteredTaskAcl ($Task.GetSecurityDescriptor(7))
}

function Wait-PreviewTaskInstance {
    param($Instance,[int]$TimeoutSeconds)
    $deadline=[DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do{
        Start-Sleep -Milliseconds 250
        try{$Instance.Refresh()}catch{
            $completed=$false;$exception=$_.Exception
            while($null -ne $exception){if($exception.HResult -eq -2147216629){$completed=$true;break};$exception=$exception.InnerException}
            # SCHED_E_TASK_NOT_RUNNING ends polling only; it never proves success.
            if($completed){return}
            throw}
        if([DateTime]::UtcNow -gt $deadline){throw ('the preview task did not end within '+$TimeoutSeconds+' s (task limit '+$script:taskTimeLimit+')')}
    }while($Instance.State -in @(2,4))
}

function Assert-CompletedPreviewTask {
    param($Task)
    if($Task.State -notin @(1,3) -or $Task.GetInstances(0).Count -ne 0){throw 'the preview task is not conclusively terminal'}
}

function Test-PreviewChangeEntries {
    param($Items)
    # The module's _changes list: objects with a string key and an exact boolean changed flag.
    foreach($item in @($Items)){
        if($null -eq $item -or $item -isnot [Management.Automation.PSCustomObject]){return $false}
        $key=$item.PSObject.Properties['key'];$changed=$item.PSObject.Properties['changed']
        if($null -eq $key -or $key.Value -isnot [string] -or $null -eq $changed -or $changed.Value -isnot [bool]){return $false}}
    $true
}

function Get-PreviewGate {
    param($Preview,[string]$Mode,$Context)
    # The S10 gate, evaluated exactly as the helper's evaluate_gate (a test compares both on the same previews).
    $result=[ordered]@{passed=$false;reasons=@();identities_changed=@();protected_paths_changed=@();configuration_path_swap_accepted=$false;
        configuration_change_keys=@();schema_change_count=$null;database_exists=$null;workflows_captured=$null;providers_changed=@()}
    if($null -eq $Preview -or $Preview -isnot [Management.Automation.PSCustomObject] -or (Get-JsonMember $Preview 'schema') -cne 'cochem-upgrade-preview/1'){
        $result.reasons=@('PREVIEW_SCHEMA_INVALID');return $result}
    $reasons=[Collections.Generic.List[string]]::new()
    if(-not (Test-ExactBool (Get-JsonMember $Preview 'read_only') $true)){$reasons.Add('READ_ONLY_NOT_TRUE')}
    if(-not (Test-ExactBool (Get-JsonMember $Preview 'native_models_executed') $false)){$reasons.Add('NATIVE_MODELS_EXECUTED')}
    foreach($pair in @(@('current',$Context.current_path,$Context.current_sha256,'CURRENT_BINDING_DIFFERS'),@('proposed',$Context.proposed_path,$Context.proposed_sha256,'PROPOSED_BINDING_DIFFERS'))){
        $info=Get-JsonMember $Preview $pair[0]
        if($null -eq $info -or $info -isnot [Management.Automation.PSCustomObject] -or (Get-JsonMember $info 'path') -isnot [string] -or (Get-JsonMember $info 'path') -cne $pair[1] -or
           (Get-JsonMember $info 'sha256') -isnot [string] -or (Get-JsonMember $info 'sha256') -cne $pair[2]){$reasons.Add($pair[3])}}
    $identities=Get-JsonListField $Preview 'identities'
    if(-not $identities.valid -or -not (Test-PreviewChangeEntries $identities.items)){$reasons.Add('IDENTITIES_MALFORMED')}
    else{
        $changed=@(@($identities.items)|Where-Object {$_.changed}|ForEach-Object {[string]$_.key})
        $result.identities_changed=$changed
        if($changed.Count){$reasons.Add('IDENTITIES_CHANGED')}}
    $paths=Get-JsonListField $Preview 'protected_paths'
    if(-not $paths.valid -or -not (Test-PreviewChangeEntries $paths.items)){$reasons.Add('PROTECTED_PATHS_MALFORMED')}
    else{
        $changed=@()
        foreach($item in @($paths.items)){
            if(-not $item.changed){continue}
            # The one expected difference: the configuration file moves from the commissioned copy to the staged candidate.
            $before=Get-JsonMember $item 'before';$after=Get-JsonMember $item 'after'
            if($item.key -ceq 'configuration' -and $before -is [string] -and $before -ceq $Context.current_path -and $after -is [string] -and $after -ceq $Context.proposed_path){
                $result.configuration_path_swap_accepted=$true;continue}
            $changed+=[string]$item.key}
        $result.protected_paths_changed=@($changed)
        if($changed.Count){$reasons.Add('PROTECTED_PATHS_CHANGED')}}
    $database=Get-JsonMember $Preview 'database'
    if($null -eq $database -or $database -isnot [Management.Automation.PSCustomObject]){$reasons.Add('DATABASE_MALFORMED')}
    else{
        $exists=Get-JsonMember $database 'exists';$result.database_exists=$exists
        if(-not (Test-ExactBool $exists $true)){$reasons.Add('DATABASE_NOT_PRESENT')}
        $schemaChanges=Get-JsonListField $database 'schema_changes'
        if(-not $schemaChanges.valid){$reasons.Add('SCHEMA_CHANGES_MALFORMED')}
        else{$result.schema_change_count=@($schemaChanges.items).Count;if(@($schemaChanges.items).Count){$reasons.Add('SCHEMA_CHANGES_PRESENT')}}
        if(-not (Test-ExactBool (Get-JsonMember $database 'migration_executed') $false)){$reasons.Add('MIGRATION_EXECUTED')}
        $workflows=Get-JsonListField $database 'workflows';if($workflows.valid){$result.workflows_captured=@($workflows.items).Count}}
    $changes=Get-JsonListField $Preview 'configuration_changes';$wellFormed=$changes.valid;$keys=@()
    if($wellFormed){foreach($item in @($changes.items)){
        if($null -eq $item -or $item -isnot [Management.Automation.PSCustomObject] -or (Get-JsonMember $item 'key') -isnot [string]){$wellFormed=$false;break}
        $keys+=[string]$item.key}}
    if(-not $wellFormed){$reasons.Add('CONFIGURATION_CHANGES_MALFORMED')}
    else{
        $result.configuration_change_keys=@($keys)
        if(@($keys|Where-Object {$_ -cnotin $script:allowedConfigurationKeys}).Count){$reasons.Add('CONFIGURATION_CHANGES_OUTSIDE_PROVIDERS')}
        if($Mode -ceq 'held' -and $keys.Count){$reasons.Add('CONFIGURATION_CHANGES_IN_HELD_MODE')}}
    if($Mode -ceq 'enabled'){
        # Deploy audit B-F5: the bound files themselves may differ in providers.gemini only (a 'providers' key alone says nothing).
        $before=$Context['current_providers_sha256'];$after=$Context['proposed_providers_sha256']
        if(-not (Test-ProviderDigestMap $before) -or -not (Test-ProviderDigestMap $after)){$reasons.Add('PROVIDER_DIGESTS_MALFORMED')}
        else{
            $names=[Collections.Generic.SortedSet[string]]::new([StringComparer]::Ordinal)
            foreach($name in @($before.Keys)+@($after.Keys)){$null=$names.Add([string]$name)}
            $changed=@(foreach($name in $names){if(-not $before.ContainsKey($name) -or -not $after.ContainsKey($name) -or [string]$before[$name] -cne [string]$after[$name]){$name}})
            $result.providers_changed=@($changed)
            if(@($changed|Where-Object {$_ -cnotin $script:allowedChangedProviders}).Count){$reasons.Add('PROVIDERS_CHANGED_OUTSIDE_GEMINI')}}}
    $result.reasons=@($reasons);$result.passed=($reasons.Count -eq 0)
    $result
}

function Test-ProviderDigestMap {
    param($Map)
    # Get-ProviderDigests output: an ordinal (case-sensitive) string map of provider name to lowercase sha256.
    if($Map -isnot [Collections.Generic.SortedDictionary[string,string]] -or -not [object]::ReferenceEquals($Map.Comparer,[StringComparer]::Ordinal)){return $false}
    foreach($value in @($Map.Values)){if([string]$value -cnotmatch '^[a-f0-9]{64}$'){return $false}}
    $true
}

function Assert-PreviewFailureMetadata {
    param($Value)
    $failure=Get-JsonMember $Value 'failure'
    if($null -eq $failure){return $null}
    if($failure -isnot [Management.Automation.PSCustomObject] -or (Get-JsonMember $failure 'phase') -cnotin $script:failurePhases -or
       (Get-JsonMember $failure 'reason') -cnotin $script:failureReasons -or (Get-JsonMember $failure 'error_type') -isnot [string] -or
       (Get-JsonMember $failure 'error_type') -cnotmatch '^[A-Za-z][A-Za-z0-9_]{0,79}$'){throw 'Invalid sanitized preview failure metadata.'}
    [ordered]@{phase=$failure.phase;reason=$failure.reason;error_type=$failure.error_type}
}

function Assert-PreviewReceipt {
    param($Value,$Task,$Context,[string]$Nonce,[string]$Root)
    if($null -eq $Value -or $Value -isnot [Management.Automation.PSCustomObject]){throw 'The preview receipt is not a JSON object.'}
    if((Get-JsonMember $Value 'schema') -cne 'cochem-upgrade-preview-r5-receipt/1' -or (Get-JsonMember $Value 'attempt') -cne $script:Attempt -or
       (Get-JsonMember $Value 'nonce') -cne $Nonce -or (Get-JsonMember $Value 'system_sid') -cne 'S-1-5-18' -or (Get-JsonMember $Value 'helper_sha256') -cne $script:helperPin -or
       (Get-JsonMember $Value 'install_root') -cne $Context.install_root -or (Get-JsonMember $Value 'config_mode') -cne $Context.mode -or
       (Get-JsonMember $Value 'commissioned_sha256') -cne $script:configPin){throw 'The preview receipt identity/runtime binding differs.'}
    $status=Get-JsonMember $Value 'status'
    if($status -isnot [string] -or $status -cnotin @($script:statusExitCodes.Keys)){throw 'The preview receipt status is not a known terminal status.'}
    foreach($key in @('native_models_executed','automatic_retry_allowed')){if(-not (Test-ExactBool (Get-JsonMember $Value $key) $false)){throw ('Out-of-scope claim in the preview receipt: '+$key+'.')}}
    if(-not (Test-ExactInt (Get-JsonMember $Value 'tasks_changed') 0)){throw 'Out-of-scope claim in the preview receipt: tasks_changed.'}
    if([long]$Task.LastTaskResult -ne [long]$script:statusExitCodes[$status]){throw ('The task result '+$Task.LastTaskResult+' contradicts the preview receipt status '+$status+'.')}
    $heldPath=Get-JsonMember $Value 'held_record_path';$heldSha=Get-JsonMember $Value 'held_record_sha256'
    if($status -ceq 'UPGRADE_PREVIEW_GATE_PASSED'){
        if($null -ne $heldPath -or (Test-Path -LiteralPath (Join-Path $Root $script:runnerHeldName))){throw 'A passed preview must not carry a held record.'}}
    else{
        if($heldPath -cne $script:runnerHeldName -or -not (Test-Sha256Text $heldSha)){throw 'The preview helper did not record its held record.'}
        $null=Read-R3Control (Join-Path $Root $script:runnerHeldName) $heldSha $script:receiptMaxBytes}
    $failure=Assert-PreviewFailureMetadata $Value
    if($status -ceq 'UPGRADE_PREVIEW_FAILED'){
        if($null -eq $failure){throw 'A failed preview must carry its sanitized failure metadata.'}
        # A run that failed after binding must still name the bound runtime and configurations.
        foreach($key in @('install_after_sha256','venv_python_sha256')){$v=Get-JsonMember $Value $key;if($null -ne $v -and $v -cne $Context[$key]){throw 'The failed preview receipt names another runtime binding.'}}
        return [pscustomobject]@{decision='FAILED';failure=$failure;gate=$null;preview=$null}}
    if($null -ne $failure){throw 'A completed preview must not carry failure metadata.'}
    if((Get-JsonMember $Value 'install_after_sha256') -cne $Context.install_after_sha256 -or (Get-JsonMember $Value 'venv_python') -cne $Context.python -or
       (Get-JsonMember $Value 'venv_python_sha256') -cne $Context.venv_python_sha256 -or (Get-JsonMember $Value 'install_mode') -cne 'FRESH_STOPPED_RUNTIME_READY' -or
       (Get-JsonMember $Value 'current.path') -cne $Context.current_path -or (Get-JsonMember $Value 'current.sha256') -cne $Context.current_sha256 -or
       (Get-JsonMember $Value 'proposed.path') -cne $Context.proposed_path -or (Get-JsonMember $Value 'proposed.sha256') -cne $Context.proposed_sha256){
        throw 'The preview receipt runtime/configuration binding differs.'}
    $command=Get-JsonListField $Value 'command'
    $expected=@($Context.python,'-I','-B','-X','utf8','-m','cochem_pipeline','upgrade-preview','--current-config',$Context.current_path,'--proposed-config',$Context.proposed_path)
    if(-not $command.valid -or @($command.items).Count -ne $expected.Count){throw 'The preview child command differs from the reviewed command.'}
    for($i=0;$i -lt $expected.Count;$i++){if(@($command.items)[$i] -isnot [string] -or @($command.items)[$i] -cne $expected[$i]){throw 'The preview child command differs from the reviewed command.'}}
    if(-not (Test-ExactInt (Get-JsonMember $Value 'child.exit_code') 0) -or -not (Test-ExactBool (Get-JsonMember $Value 'child.timed_out') $false)){throw 'The preview child did not exit 0 within its bound.'}
    $previewSha=Get-JsonMember $Value 'preview_sha256'
    if((Get-JsonMember $Value 'preview_path') -cne $script:previewName -or -not (Test-Sha256Text $previewSha)){throw 'The preview receipt does not name the retained upgrade-preview.json.'}
    $control=Read-R3Control (Join-Path $Root $script:previewName) $previewSha $script:previewMaxBytes
    $preview=$null;try{$preview=(Read-R3Text $control)|ConvertFrom-Json}catch{throw 'The retained upgrade preview is not JSON.'}
    $gate=Get-PreviewGate $preview $Context.mode $Context
    $recorded=Get-JsonMember $Value 'gate';$recordedReasons=Get-JsonListField $recorded 'reasons'
    if(-not (Test-ExactBool (Get-JsonMember $recorded 'passed') ([bool]$gate.passed)) -or -not $recordedReasons.valid -or
       (@($recordedReasons.items) -join ',') -cne (@($gate.reasons) -join ',') -or (Get-JsonMember $recorded 'mode') -cne $Context.mode){
        throw 'The gate in the preview receipt contradicts the retained preview.'}
    if([bool]$gate.passed -ne ($status -ceq 'UPGRADE_PREVIEW_GATE_PASSED')){throw 'The preview receipt status contradicts its gate.'}
    [pscustomobject]@{decision=$(if($gate.passed){'PASSED'}else{'GATE_FAILED'});failure=$null;gate=$gate;preview=$preview}
}

function New-PreviewSummary {
    param($Receipt,$Verified,$Task,[string]$Nonce,[string]$ReceiptSha256,$Context)
    $gate=$Verified.gate;$root=$script:targetRoot
    $prerequisites=@()
    if($null -ne $Verified.preview){
        $items=Get-JsonListField $Verified.preview 'rollback_prerequisites'
        if($items.valid){$prerequisites=@(@($items.items)|ForEach-Object {[ordered]@{id=(Get-JsonMember $_ 'id');required=(Get-JsonMember $_ 'required');verified=(Get-JsonMember $_ 'verified');detail=(Get-JsonMember $_ 'detail')}})}}
    # Arrays are assigned outside $(...) so a single entry stays a JSON list.
    $reasons=@();$identities=$null;$paths=$null;$keys=$null;$providers=$null
    if($null -ne $gate){$reasons=@($gate.reasons);$identities=@($gate.identities_changed);$paths=@($gate.protected_paths_changed);$keys=@($gate.configuration_change_keys)
        $providers=@($gate.providers_changed)}
    if($Verified.decision -ceq 'PASSED'){$message='S10 upgrade preview gate passed ('+$Context.mode+' mode): read_only, no native model run, no identity, protected-path or schema change, job board present, configuration changes within providers. Continue to S11.'}
    elseif($Verified.decision -ceq 'GATE_FAILED'){$message='SERIES-STOP (S10): the upgrade preview gate failed ('+($reasons -join ', ')+'); evidence in '+$root+'. R4-RESTORE, or record an explicit owner waiver line in the series log and continue.'}
    else{$message='SERIES-STOP (S10): the upgrade preview did not complete ('+$Verified.failure.reason+', phase '+$Verified.failure.phase+'); evidence in '+$root+'. R4-RESTORE, or record an explicit owner waiver line in the series log and continue.'}
    [ordered]@{schema='cochem-upgrade-preview-r5-result/1';status=(Get-JsonMember $Receipt 'status');decision=$Verified.decision;attempt=$script:Attempt;nonce=$Nonce;
        target_root=$root;receipt_path=(Join-Path $root $script:receiptName);receipt_sha256=$ReceiptSha256;task_name=$script:taskName;last_task_result=$Task.LastTaskResult;task_preserved=$true;
        config_mode=$Context.mode;candidate_mode=$Context.candidate_mode;current=[ordered]@{path=$Context.current_path;sha256=$Context.current_sha256};
        proposed=[ordered]@{path=$Context.proposed_path;sha256=$Context.proposed_sha256};install_root=$Context.install_root;install_after_sha256=$Context.install_after_sha256;
        venv_python_sha256=$Context.venv_python_sha256;gate=[ordered]@{passed=$(if($null -ne $gate){[bool]$gate.passed}else{$false});reasons=$reasons};
        series_stop=($Verified.decision -cne 'PASSED');
        identities_changed=$identities;protected_paths_changed=$paths;
        configuration_path_swap_accepted=$(if($null -ne $gate){$gate.configuration_path_swap_accepted}else{$null});
        configuration_change_keys=$keys;providers_changed=$providers;schema_change_count=$(if($null -ne $gate){$gate.schema_change_count}else{$null});
        database_exists=$(if($null -ne $gate){$gate.database_exists}else{$null});workflows_captured=$(if($null -ne $gate){$gate.workflows_captured}else{$null});
        rollback_prerequisites=$prerequisites;preview_path=$(if($null -ne $Verified.preview){Join-Path $root $script:previewName}else{$null});
        preview_sha256=(Get-JsonMember $Receipt 'preview_sha256');failure=$Verified.failure;
        runner_held_record=$(if($Verified.decision -cne 'PASSED'){Join-Path $root $script:runnerHeldName}else{$null});
        native_models_executed=$false;database_modified=$false;automatic_retry_allowed=$false;message=$message}
}

function Invoke-UpgradePreview {
    param($Scheduler,$Folder,$Context,[long]$SourceLength)
    try{
        # Elevated: inspect the code trees once before the SYSTEM task runs the r5 interpreter.
        $codeTrees=[ordered]@{runtime=(Assert-CodeTreeOnce $Context.install_root);toolchain=(Assert-CodeTreeOnce $script:basePythonRoot)}
        if((Get-TaskPresence $Folder $script:taskName) -cne 'ABSENT'){throw 'The preview task already exists; preserve it and choose another -Attempt.'}
        if(Test-Path -LiteralPath $script:targetRoot){throw 'The preview root already exists; preserve it and choose another -Attempt.'}
    }catch{
        $reason=$_.Exception.Message
        throw ('The upgrade preview is held before any change: '+$reason.TrimEnd('.')+'. Nothing was changed.')}
    New-PrivateDirectory $script:targetRoot
    # From here the attempt namespace is consumed: every failure leaves preview-held.json.
    $phase='PREPARATION';$registered=$false;$runRequested=$false;$task=$null;$nonce=$null;$failure=$null;$summary=$null;$intentHash=$null;$taskXmlHash=$null;$receiptPresent=$false;$verified=$null
    try{
        $destination=Join-Path $script:targetRoot $script:helperName
        Copy-VerifiedPayload ([pscustomobject]@{source=$script:helperSource;destination=$destination;sha256=$script:helperPin;length=$SourceLength})
        $held.Add((Open-VerifiedFile $destination $script:helperPin $SourceLength))
        $nonce=New-PreviewNonce
        $arguments=Get-PreviewTaskArguments $destination $nonce $Context
        $intent=[ordered]@{schema='cochem-upgrade-preview-r5-intent/1';attempt=$script:Attempt;nonce=$nonce;requested_utc=[DateTime]::UtcNow.ToString('o');
            task_name=$script:taskName;target_root=$script:targetRoot;helper_sha256=$script:helperPin;context=$Context;code_tree_entries=$codeTrees;
            task_action=[ordered]@{path=$Context.python;arguments=$arguments;working_directory=$script:targetRoot};task_execution_time_limit=$script:taskTimeLimit;
            gate='read_only true; native_models_executed false; identities unchanged; protected_paths unchanged except the configuration path swap; database.exists true; database.schema_changes []; configuration_changes keys within [providers] ([] in held mode); enabled mode: only providers.gemini differs between the bound files';
            retry=$false}
        $intentHash=Write-RegistrationControl (Join-Path $script:targetRoot 'preview-intent.json') ($intent|ConvertTo-Json -Depth 8)
        $phase='REGISTRATION'
        $definition=New-PreviewTaskDefinition $Scheduler $destination $nonce $Context
        $registered=$true
        $task=$Folder.RegisterTaskDefinition($script:taskName,$definition,2,'SYSTEM',$null,5,$script:taskSddl)
        Assert-PreviewTaskRegistration $task $destination $nonce $Context
        $taskXmlHash=Write-RegistrationControl (Join-Path $script:targetRoot 'preview-task.xml') ([string]$task.Xml)
        $phase='RUN'
        $runRequested=$true
        $instance=$task.Run($null)
        $phase='WAIT'
        Wait-PreviewTaskInstance $instance $script:taskWaitSeconds
        Assert-CompletedPreviewTask $task
        $phase='RECEIPT'
        $receiptPath=Join-Path $script:targetRoot $script:receiptName
        if(-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)){throw ('the preview task left no receipt (LastTaskResult '+$task.LastTaskResult+')')}
        $receiptPresent=$true
        $receiptControl=Read-R3Control $receiptPath '' $script:receiptMaxBytes
        $receipt=$null;try{$receipt=(Read-R3Text $receiptControl)|ConvertFrom-Json}catch{throw 'the preview receipt is not JSON'}
        $verified=Assert-PreviewReceipt $receipt $task $Context $nonce $script:targetRoot
        $summary=New-PreviewSummary $receipt $verified $task $nonce $receiptControl.Sha256 $Context
        $summary.intent_sha256=$intentHash;$summary.task_xml_sha256=$taskXmlHash
        $phase='SUMMARY'
        $null=Write-RegistrationControl (Join-Path $script:targetRoot 'preview-summary.json') ($summary|ConvertTo-Json -Depth 8)
        if($verified.decision -cne 'PASSED'){$phase='GATE';throw ('the upgrade preview reported '+$receipt.status)}
    }catch{$failure=$_.Exception.Message}
    if($null -ne $failure){
        $lastResult=$null;$state=$null;$instances=$null
        if($null -ne $task){try{$lastResult=[int]$task.LastTaskResult;$state=[int]$task.State;$instances=[int]$task.GetInstances(0).Count}catch{$lastResult=$null}}
        $gateReasons=$null;if($null -ne $verified -and $null -ne $verified.gate){$gateReasons=@($verified.gate.reasons)}
        $heldRecord=[ordered]@{schema='cochem-upgrade-preview-r5-task-held/1';attempt=$script:Attempt;nonce=$nonce;phase=$phase;reason=$failure;
            task_name=$script:taskName;task_registered=$registered;run_requested=$runRequested;task_state=$state;task_instances=$instances;last_task_result=$lastResult;
            receipt_present=$receiptPresent;helper_failure=$(if($null -ne $verified){$verified.failure}else{$null});
            gate_reasons=$gateReasons;
            runner_held_record=(Join-Path $script:targetRoot $script:runnerHeldName);intent_sha256=$intentHash;task_xml_sha256=$taskXmlHash;
            task_preserved=$true;root_preserved=$true;processes_killed=$false;automatic_retry_allowed=$false;requires_reviewed_recovery=$true;
            owner_options=@('R4-RESTORE: retarget-warden-r5.ps1 -Target r4 -Apply -Start -Attempt <fresh>','OWNER_WAIVER: record an explicit owner waiver line in the series log and continue')}
        $heldNote=''
        try{$null=Write-RegistrationControl (Join-Path $script:targetRoot 'preview-held.json') ($heldRecord|ConvertTo-Json -Depth 8)}catch{$heldNote=(' The held record could not be written: '+$_.Exception.Message)}
        $message=switch($phase){
            'PREPARATION'{'The upgrade preview is held before any task exists: '+$failure+'. Preserve '+$script:targetRoot+' and review preview-held.json before another -Attempt.'}
            'REGISTRATION'{'The upgrade preview is held at task registration: '+$failure+'. No Run was requested; preserve the root and the task (if registered) and review preview-held.json.'}
            'RUN'{'The upgrade preview is held at its single Run request: '+$failure+'. Preserve everything and review preview-held.json.'}
            'WAIT'{'The upgrade preview task did not end cleanly: '+$failure+'. Preserve the task and root, review preview-held.json; do not retry automatically.'}
            'GATE'{$summary.message}
            default{'SERIES-STOP (S10): the upgrade preview receipt is refused: '+$failure+'. Preserve the task and root and review preview-held.json; R4-RESTORE or an explicit owner waiver line.'}}
        if($null -ne $summary){Write-Host ('COCHEM_UPGRADE_PREVIEW_RESULT '+($summary|ConvertTo-Json -Depth 8 -Compress))}
        throw ($message+$heldNote)
    }
    $summary
}

function Write-PreviewOutcome {
    param($Summary)
    # The orchestrator reads the JSON summary from stdout on success; a failed gate prints the summary line and exits non-zero.
    if((Test-ExactBool $Summary.gate.passed $true) -and $Summary.decision -ceq 'PASSED'){return ($Summary|ConvertTo-Json -Depth 8)}
    Write-Host ('COCHEM_UPGRADE_PREVIEW_RESULT '+($Summary|ConvertTo-Json -Depth 8 -Compress))
    throw $Summary.message
}

function Get-PreviewPlan {
    param($Request,$Folder,$HostContext)
    $holds=@();$r5=$null;$current=$null;$candidate=$null;$context=$null;$sourceLength=$null;$taskPresence=$null;$daemons=@()
    try{$r5=Resolve-R5Install $Request.install_root}catch{$holds+=('r5 runtime (run install-stopped-runtime-r5.ps1 -Apply first): '+$_.Exception.Message)}
    try{$current=Assert-CurrentConfig $Request.current}catch{$holds+=('Current configuration: '+$_.Exception.Message)}
    try{$candidate=Resolve-Candidate $Request.candidate $Request.candidate_sha256}catch{$holds+=('Staged r5 candidate (run stage-pipeline-config-r5-v1.ps1 -Apply first): '+$_.Exception.Message)}
    if(-not $Request.candidate_sha256){$holds+='-CandidateSha256 from the staging receipt is required to bind the candidate by content.'}
    try{$sourceLength=(Get-Item -LiteralPath $script:helperSource).Length;$held.Add((Open-VerifiedFile $script:helperSource $script:helperPin $sourceLength))}
    catch{$sourceLength=$null;$holds+=('The reviewed preview helper differs from its pin or is missing: '+$_.Exception.Message)}
    if($null -ne $r5 -and $null -ne $current -and $null -ne $candidate){
        try{$context=New-PreviewContext $r5 $current $candidate}catch{$context=$null;$holds+=('Provider digests of the bound configurations: '+$_.Exception.Message)}}
    if(Test-Path -LiteralPath $script:targetRoot){$holds+='This one-shot preview root already exists; preserve its evidence and choose another -Attempt.'}
    try{$taskPresence=Get-TaskPresence $Folder $script:taskName;if($taskPresence -cne 'ABSENT'){$holds+='This one-shot preview task already exists; preserve it and choose another -Attempt.'}}
    catch{$holds+=('Preview task state: '+$_.Exception.Message)}
    try{$daemons=@(Get-DaemonTaskObservations $Folder)}catch{$daemons=@([pscustomobject]@{name='*';state=('UNREADABLE: '+$_.Exception.Message)})}
    $document=[ordered]@{schema='cochem-upgrade-preview-r5-plan/1';mode='READ_ONLY_PLAN';attempt=$script:Attempt;owner=$HostContext.name;administrator=[bool]$HostContext.admin;
        install_root_requested=$Request.install_root;r5_runtime_verified=($null -ne $r5);
        r5_binding=$(if($null -ne $r5){[ordered]@{root=$r5.root;python=$r5.python;install_after_path=$r5.install_after_path;install_after_sha256=$r5.install_after_sha256;
            venv_python_sha256=$r5.venv_python_sha256;source_manifest_sha256=$r5.source_manifest_sha256;revision_sha256=$r5.revision_sha256;reviewed_repairs=@($r5.reviewed_repairs)}}else{$null});
        current=$current;candidate=$(if($null -ne $candidate){[ordered]@{path=$candidate.path;sha256=$candidate.sha256;mode=$candidate.mode;expected_sha256=$Request.candidate_sha256}}else{$null});
        runner_mode=$(if($null -ne $context){$context.mode}else{$null});helper_source=$script:helperSource;helper_sha256=$script:helperPin;helper_verified=($null -ne $sourceLength);
        task_name=$script:taskName;task_presence=$taskPresence;target_root=$script:targetRoot;target_root_access='SYSTEM and BUILTIN\Administrators only';
        task_execution_time_limit=$script:taskTimeLimit;task_sddl=$script:taskSddl;
        task_action=$(if($null -ne $context){[ordered]@{path=$context.python;arguments=(Get-PreviewTaskArguments (Join-Path $script:targetRoot $script:helperName) '<nonce>' $context);working_directory=$script:targetRoot}}else{$null});
        receipt_path=(Join-Path $script:targetRoot $script:receiptName);runner_held_record=(Join-Path $script:targetRoot $script:runnerHeldName);
        wrapper_held_record=(Join-Path $script:targetRoot 'preview-held.json');summary_path=(Join-Path $script:targetRoot 'preview-summary.json');
        gate=@('read_only true','native_models_executed false','identities unchanged','protected_paths unchanged except the configuration path swap','database.exists true',
            'database.schema_changes []','configuration_changes keys within [providers] ([] in held mode)','enabled mode: only providers.gemini differs between the bound files');
        daemon_tasks=$daemons;holds=$holds;tasks_changed=0;native_models_executed=$false;job_board_opened=$false;automatic_retry_allowed=$false}
    [pscustomobject]@{document=$document;holds=$holds;context=$context;source_length=$sourceLength}
}

function Invoke-UpgradePreviewMain {
    param($Arguments,[string]$Workspace)
    $ErrorActionPreference='Stop';Set-StrictMode -Version Latest
    $request=Assert-PreviewParameters $Arguments
    $hostContext=Initialize-PreviewHost;$script:admin=[bool]$hostContext.admin
    Assert-PreviewApplyIdentity $request.apply $hostContext
    Set-PreviewConstants $request.attempt $Workspace
    $held=[Collections.Generic.List[IO.FileStream]]::new()
    try{
        . Import-PreviewHelpers
        $connection=Connect-TaskFolder
        $plan=Get-PreviewPlan $request $connection.folder $hostContext
        if(-not $request.apply){$plan.document|ConvertTo-Json -Depth 8;return}
        if(@($plan.holds).Count){throw ('The upgrade preview is held. Nothing was changed: '+(@($plan.holds) -join ' | '))}
        Write-PreviewOutcome (Invoke-UpgradePreview $connection.scheduler $connection.folder $plan.context $plan.source_length)
    }finally{foreach($stream in $held){$stream.Dispose()}}
}

# Invocation boundary: the only top-level statement. Fixtures dot-source the functions above from the AST without running it.
Invoke-UpgradePreviewMain -Arguments ([ordered]@{Attempt=$Attempt;InstallRoot=$InstallRoot;Current=$Current;Candidate=$Candidate;CandidateSha256=$CandidateSha256;Apply=[bool]$Apply}) -Workspace $PSScriptRoot
