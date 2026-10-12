#Requires -Version 5.1
<# Owner-only cutover after protected R6 evidence. This script is prepared and
   tested with inert fixtures; engineering sessions must never invoke -Apply.
   R4/R5 source lineage and backup/start transactions use the reviewed core.
   No implicit resume or automatic rollback after a task mutation is allowed. #>
[CmdletBinding()]
param([string]$CoreSha256,[string]$InstallerSha256,[string]$ManifestSha256,
    [string]$CandidateSha256,[string]$EvidencePath,[string]$EvidenceSha256,
    [string]$Attempt,[string]$SourceAttempt='',[string]$StopAttempt='',
    [string]$RetirementHelperSha256='',[switch]$Apply)

function Import-R6ActivationFunctions {
    param([string]$Path,[string]$Hash)
    $stream=[IO.File]::Open($Path,'Open','Read','Read')
    try{
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$actual=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        if($actual -cne $Hash){throw 'Activation helper differs from its reviewed hash.'}
        $stream.Position=0;$reader=[IO.StreamReader]::new($stream)
        try{$text=$reader.ReadToEnd()}finally{$reader.Dispose()}
        $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
        if($errors.Count){throw 'Activation helper does not parse.'}
        foreach($node in $ast.EndBlock.Statements){if($node -is [Management.Automation.Language.FunctionDefinitionAst]){$node.Extent.Text}}
    }finally{$stream.Dispose()}
}

function Assert-R6AcceptanceIndex {
    param($Index,[string]$ManifestHash,[string]$CandidateHash,[string]$RetirementHelperHash='')
    if($Index.schema -cne 'cochem-r6-acceptance-index/1' -or $Index.manifest_sha256 -cne $ManifestHash -or
        $Index.candidate_sha256 -cne $CandidateHash -or @($Index.phases).Count -ne 5){throw 'R6 acceptance index binding differs.'}
    $seen=@{};$revision=$null
    foreach($entry in @($Index.phases)){
        $phase=[string]$entry.phase
        if($phase -cnotin @('auth','agent','native','knowledge','preview') -or $seen.ContainsKey($phase) -or
            [string]$entry.receipt_sha256 -cnotmatch '^[a-f0-9]{64}$') {throw 'Duplicate or unbound acceptance phase.'}
        $path=[string]$entry.receipt_path
        if($path -cnotmatch ('^C:\\Program Files\\CoChem\\R6Acceptance4\.2\.7-windows-20261012-v1-'+$phase+'-[a-f0-9]{32}\\result\.json$')){
            throw 'Acceptance receipt is outside its reviewed private namespace.'}
        $root=Split-Path -Parent $path
        foreach($heldName in @('held.json','wrapper-held.json')){if(Test-Path -LiteralPath (Join-Path $root $heldName)){throw 'A held acceptance must be preserved, not activated.'}}
        Assert-PrivateAcl $path
        $row=(Read-R3Text (Read-R3Control $path $entry.receipt_sha256 4194304))|ConvertFrom-Json
        if($row.schema -cne 'cochem-r6-system-phase/1' -or $row.phase -cne $phase -or $row.status -cne 'PHASE_COMPLETED' -or
            $row.manifest_sha256 -cne $ManifestHash -or $row.candidate_sha256 -cne $CandidateHash -or
            -not (Test-ExactBool $row.revision.verified $true)){throw 'Protected phase receipt did not verify this R6 candidate.'}
        if($null -eq $revision){$revision=$row.revision.source_sha256}
        elseif($revision -cne $row.revision.source_sha256){throw 'Acceptance phases refer to different installed revisions.'}
        $result=$row.result
        switch -CaseSensitive ($phase){
            'auth' {if($result.status -cne 'ALL_SESSIONS_VERIFIED' -or @($result.checks).Count -ne 18 -or
                @($result.checks|Where-Object {-not (Test-ExactBool $_.authenticated $true)}).Count){throw 'Worker authentication is incomplete.'}}
            'agent' {if($result.status -cne 'SIX_WORKER_AGENT_CUSTODY_VERIFIED'){throw 'Six-worker custody was not verified.'}}
            'knowledge' {if($result.status -cne 'NEW_KNOWLEDGE_AUTHORITY_VERIFIED'){throw 'R6 knowledge authority was not verified.'}}
            'native' {
                $expectedTargets=if($RetirementHelperHash){26}else{27}
                if($result.status -cnotin @('ALL_NATIVE_SELECTORS_ACCEPTED','NATIVE_ACCEPTANCE_PARTIAL_AVAILABILITY') -or
                    @($result.targets).Count -ne $expectedTargets){throw 'Native selector evidence is incomplete.'}
                # Quota exhaustion is not a protocol defect. Record unavailable
                # targets without blocking lower tiers on exhausted upper-tier
                # subscriptions. The separate owner-pinned retirement amendment
                # omits only Pro High; it never attests or replaces that model.
                if($RetirementHelperHash){
                    Assert-R6NativeRetirement $result $RetirementHelperHash
                    if($result.owner_retirement.original_plan_sha256 -cne $row.native_plan_sha256){
                        throw 'Retirement evidence does not bind the original installed plan.'}
                }
                $covered=@{};$pro=$false
                foreach($target in @($result.targets)){
                    if($target.status -ceq 'NATIVE_SELECTOR_ACCEPTED'){
                        foreach($position in @($target.route_positions)){$covered[[int]$position.tier]=$true}
                        if($target.provider -ceq 'gemini' -and $target.model -ceq 'gemini-3.1-pro' -and $target.effort -ceq 'high'){$pro=$true}}
                    elseif($target.status -cnotin @('NOT_PROBED_POOL_UNAVAILABLE','PROVIDER_TEMPORARILY_UNAVAILABLE')){throw 'A native protocol or identity check failed.'}}
                if(-not $RetirementHelperHash -and -not $pro){throw 'The owner-required Gemini Pro High route has not passed native acceptance.'}
            }
            'preview' {if(@($result.identities).Count -or @($result.database.schema_changes).Count -or
                -not (Test-ExactBool $result.database.migration_executed $false)){throw 'Unreviewed identity or database migration.'}}
        }
        $seen[$phase]=$true
    }
    $revision
}

function Assert-R6NativeRetirement {
    param($Result,[string]$HelperHash)
    $value=$Result.owner_retirement
    if($HelperHash -cnotmatch '^[a-f0-9]{64}$' -or $value.schema -cne 'cochem-owner-model-retirement/1' -or
        $value.decision -cne 'owner-2026-10-12-pro-retired' -or $value.helper_sha256 -cne $HelperHash -or
        $value.original_plan_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
        $value.retired_target.provider -cne 'gemini' -or $value.retired_target.model -cne 'gemini-3.1-pro' -or
        $value.retired_target.reasoning_effort -cne 'high' -or $value.retired_status -cne 'OWNER_RETIRED_MODEL_NOT_PROBED' -or
        $value.retired_model_jobs_executed -ne 0 -or -not (Test-ExactBool $value.replacement_selected $false) -or
        $Result.count -ne 26 -or @($Result.targets).Count -ne 26 -or
        @($Result.targets|Where-Object {$_.provider -ceq 'gemini' -and $_.model -ceq 'gemini-3.1-pro'}).Count){
        throw 'The owner-pinned model retirement evidence differs.'}
}

function New-R6TargetContext {
    param($Runtime,[string]$CandidateHash)
    $queue=Join-Path $script:privateRoot 'queue-launch-r6'
    $config=Join-Path $Runtime.root 'pipeline.json'
    [ordered]@{target='r6';retargeted_status='WARDEN_RETARGETED_TO_R6_NOT_STARTED';started_status='WARDEN_R6_RUNNING_HEALTH_VERIFIED';
        runtime_root=$Runtime.root;source_root=$Runtime.source_root;config_path=$config;config_sha256=$CandidateHash;config_mode='OWNER_TEN_TIER_ACCEPTED';
        install_after_path=$Runtime.install_after_path;install_after_sha256=$Runtime.install_after_sha256;deployment_revision_sha256=$Runtime.revision_sha256;
        source_manifest_sha256=$Runtime.source_manifest_sha256;
        action=[ordered]@{execute=$Runtime.python;arguments=(Get-R5Arguments $config $queue 900);working_directory=$Runtime.root};
        triggers=(Get-TriggerReceiptForm 'r6');queue_launch_output=$null;queue_launch_output_root=$queue;docker_wait_seconds=900;
        admission_field='components.warden_controller.admission_ready';description=('Reviewed R6 owner-matrix cutover '+$script:Attempt+'. Logon only after verified health; no retries.')}
}

function Invoke-R6Activation {
    param([string]$CoreHash,[string]$InstallerHash,[string]$ManifestHash,[string]$CandidateHash,
        [string]$EvidencePath,[string]$EvidenceHash,[string]$Attempt,[string]$SourceAttempt,[string]$StopAttempt,[bool]$ApplyRequested,
        [string]$RetirementHelperHash='')
    foreach($hash in @($CoreHash,$InstallerHash,$ManifestHash,$CandidateHash,$EvidenceHash)){
        if($hash -cnotmatch '^[a-f0-9]{64}$'){throw 'Activation requires exact reviewed hashes.'}}
    if($RetirementHelperHash -and ($RetirementHelperHash -cnotmatch '^[a-f0-9]{64}$' -or
        $ManifestHash -cne 'bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4' -or
        $CandidateHash -cne 'a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288')){
        throw 'Model retirement is restricted to the exact installed R6.'}
    if($Attempt -cnotmatch '^v[1-9][0-9]{0,2}$' -or ($SourceAttempt -and $SourceAttempt -cnotmatch '^v[1-9][0-9]{0,2}$') -or
        ($StopAttempt -and ($StopAttempt -cnotmatch '^v[1-9][0-9]{0,2}$' -or -not $SourceAttempt))){throw 'Invalid source/stop/target attempt.'}
    if($EvidencePath -cnotmatch '^C:\\Program Files\\CoChem\\R6Sitting4\.2\.7-windows-20261012-[a-f0-9]{32}\\acceptance-index\.json$'){
        throw 'Unexpected protected acceptance index location.'}
    foreach($text in @(Import-R6ActivationFunctions (Join-Path $PSScriptRoot 'r6_retarget_core.ps1') $CoreHash)){. ([scriptblock]::Create($text))}
    foreach($text in @(Import-R6ActivationFunctions (Join-Path $PSScriptRoot 'install_r6_runtime.ps1') $InstallerHash)){. ([scriptblock]::Create($text))}
    $script:Target='r6';$script:Attempt=$Attempt;$script:SourceAttempt=$SourceAttempt;$script:StopAttempt=$StopAttempt;$script:scriptDirectory=$PSScriptRoot
    $hostContext=Initialize-RetargetHost;Assert-ApplyIdentity $ApplyRequested $hostContext
    if(-not $hostContext.admin){throw 'Protected activation evidence requires the owner Administrator window.'}
    $script:admin=$true;Set-R6Constants
    $runtimeRoot=$script:targetRoot
    $held=[Collections.Generic.List[IO.FileStream]]::new()
    try{
        foreach($text in @(Import-R6CopyFunctions $PSScriptRoot)){. ([scriptblock]::Create($text))};Initialize-FileIdentity
        $null=Assert-R6Tree;Assert-R6Interpreter
        Set-RetargetConstants
        . Import-RetargetHelpers
        $installPath=Join-Path $runtimeRoot 'install-after.json'
        if(Test-Path -LiteralPath (Join-Path $runtimeRoot 'install-held.json')){throw 'Installation is held.'}
        $installControl=Read-R3Control $installPath
        $installed=(Read-R3Text $installControl)|ConvertFrom-Json
        $manifest=(Read-R3Text (Read-R3Control (Join-Path $runtimeRoot 'install-manifest.json') $ManifestHash))|ConvertFrom-Json
        if($installed.status -cne 'STOPPED_RUNTIME_INSTALLED' -or $installed.manifest_sha256 -cne $ManifestHash -or
            $installed.source_commit -cne $manifest.source_commit){throw 'Installed R6 receipt does not bind this manifest.'}
        foreach($file in @($manifest.files)){
            Assert-R6Relative $file.relative
            $held.Add((Open-VerifiedFile (Join-Path $runtimeRoot $file.relative) $file.sha256 $file.length))}
        $null=Read-R3Control (Join-Path $runtimeRoot 'pipeline.json') $CandidateHash
        Assert-PrivateAcl $EvidencePath
        $index=(Read-R3Text (Read-R3Control $EvidencePath $EvidenceHash))|ConvertFrom-Json
        $revision=Assert-R6AcceptanceIndex $index $ManifestHash $CandidateHash $RetirementHelperHash
        if($revision -cne $installed.revision.source_sha256){throw 'R6 acceptance revision differs from installation.'}
        $null=Assert-R4Pins (Assert-R4InstalledBindings);$lineage=Assert-R4RetargetLineage;$null=Assert-ClientConfig
        $null=Assert-CodeTreeOnce $script:r4Root
        $runtime=[ordered]@{root=$runtimeRoot;python=(Join-Path $runtimeRoot '.venv\Scripts\python.exe');source_root=(Join-Path $runtimeRoot '.venv\Lib');
            install_after_path=$installPath;install_after_sha256=$installControl.Sha256;revision_sha256=$revision;source_manifest_sha256=$ManifestHash}
        $context=New-R6TargetContext $runtime $CandidateHash
        $script:targetRoot=Join-Path $script:base ('WardenRetarget4.2.7-windows-20261012-r6-'+$Attempt)
        $script:targetSourceRoot=$context.source_root
        # Docker readiness may legitimately consume its full 900-second bound.
        # This wait is unattended and does not consume owner input time.
        $script:startWaitSeconds=1200
        $script:runtimeRoots=@($script:runtimeRoots)+@($runtimeRoot)+@(Get-R5RootCandidates)
        $folder=Connect-TaskFolder
        $source=Assert-RetargetSource (Get-WardenTaskState $folder)
        if(Test-Path -LiteralPath $script:targetRoot){throw 'Existing R6 cutover evidence must be preserved; no automatic resume.'}
        if(-not $ApplyRequested){@{status='R6_ACTIVATION_READ_ONLY_PLAN';source=$source;context=$context;activation_ready=$false}|ConvertTo-Json -Depth 8;return}
        $result=Invoke-Retarget $folder $context $lineage
        $binding=[ordered]@{receipt_path=$result.retarget_receipt_path;receipt_sha256=$result.retarget_receipt_sha256;sddl=$result.sddl;
            source=[ordered]@{source_state=$result.source.source_state;source_attempt=$result.source.source_attempt;stop_attempt=$result.source.stop_attempt}}
        $start=Invoke-StartOnce $folder $context $binding
        @{schema='cochem-r6-activation-result/1';status=$start.status;receipt_path=$start.receipt_path;receipt_sha256=$start.receipt_sha256;
            evidence_sha256=$EvidenceHash;manifest_sha256=$ManifestHash;candidate_sha256=$CandidateHash;full_srs_acceptance=$false}|ConvertTo-Json -Depth 8
    }finally{foreach($stream in $held){$stream.Dispose()}}
}

$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
Invoke-R6Activation $CoreSha256 $InstallerSha256 $ManifestSha256 $CandidateSha256 $EvidencePath $EvidenceSha256 $Attempt $SourceAttempt $StopAttempt ([bool]$Apply) $RetirementHelperSha256
