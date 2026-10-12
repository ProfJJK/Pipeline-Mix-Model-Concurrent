#Requires -Version 5.1
<# Read-only prerequisite for the specific 2026-10-12 authentication hold.
   Does not run Python, providers, tasks, installation or a daemon. #>
[CmdletBinding()]
param([string]$InstallerSha256,[string]$PhaseWrapperSha256)

function Read-R6RecoveryJson {
    param([string]$Path,[string]$Hash='')
    Assert-ProtectedPath $Path
    $length=(Get-Item -LiteralPath $Path).Length
    if($length -gt 4194304){throw 'Recovery evidence exceeds its bound.'}
    if(-not $Hash){$Hash=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
    $stream=Open-VerifiedFile $Path $Hash $length
    try{$reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true,4096,$true)
        try{$reader.ReadToEnd()|ConvertFrom-Json}finally{$reader.Dispose()}
    }finally{$stream.Dispose()}
}

function Assert-R6AuthRecoveryRows {
    param($Value)
    if($Value.schema -cne 'cochem-r6-authentication/1' -or $Value.status -cne 'ATTENDED_AUTH_REVIEW_REQUIRED' -or
        $Value.native_model_jobs_executed -ne 0 -or $Value.credentials_copied -ne $false -or @($Value.checks).Count -ne 18){
        throw 'The original authentication result differs from the owner-reviewed failure.'}
    $seen=@{}
    foreach($row in @($Value.checks)){
        $key=[string]$row.worker+':'+[string]$row.provider
        if($row.worker -cnotmatch '^slot[1-6]$' -or $row.provider -cnotin @('codex','claude','gemini') -or
            $seen.ContainsKey($key) -or $row.cleanup_verified -ne $true){throw 'Original authentication inventory differs.'}
        $seen[$key]=$true
        if($row.provider -ceq 'gemini'){
            if($row.authenticated -ne $false -or $row.status -cne 'STATUS_UNVERIFIED' -or $row.exit_code -ne 1){throw 'Original Agy failure differs.'}
        }elseif($row.authenticated -ne $true -or $row.status -cne 'REUSE_VERIFIED_SESSION' -or $row.exit_code -ne 0){
            throw 'Original successful sessions differ.'}
    }
}

function Invoke-R6AuthRecoveryVerification {
    param([string]$InstallerHash,[string]$PhaseHash)
    foreach($hash in @($InstallerHash,$PhaseHash)){if($hash -cnotmatch '^[a-f0-9]{64}$'){throw 'Recovery helper pins are required.'}}
    $phase=Join-Path $PSScriptRoot 'run_r6_system_phase.ps1'
    $handle=[IO.File]::Open($phase,'Open','Read','Read')
    try{
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$hash=[BitConverter]::ToString($sha.ComputeHash($handle)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        if($hash -cne $PhaseHash){throw 'Recovery phase helper differs.'}
        $handle.Position=0;$reader=[IO.StreamReader]::new($handle,[Text.Encoding]::UTF8,$true,4096,$true)
        try{$text=$reader.ReadToEnd()}finally{$reader.Dispose()}
        $tokens=$null;$errors=$null
        $ast=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
        if($errors.Count){throw 'Recovery phase helper does not parse.'}
        foreach($node in $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){
            . ([scriptblock]::Create($node.Extent.Text))}
        foreach($definition in @(Import-R6PhaseInstaller $InstallerHash)){. ([scriptblock]::Create($definition))}
        Set-R6Constants
        foreach($definition in @(Import-R6CopyFunctions $PSScriptRoot)){. ([scriptblock]::Create($definition))}
        Initialize-FileIdentity
        $manifestHash='bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4'
        $candidateHash='a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288'
        $manifest=Read-R6RecoveryJson (Join-Path $script:targetRoot 'install-manifest.json') $manifestHash
        $candidate=Read-R6RecoveryJson (Join-Path $script:targetRoot 'pipeline.json') $candidateHash
        $installed=Read-R6RecoveryJson (Join-Path $script:targetRoot 'install-after.json')
        if((Test-Path -LiteralPath (Join-Path $script:targetRoot 'install-held.json')) -or
            $installed.status -cne 'STOPPED_RUNTIME_INSTALLED' -or $installed.manifest_sha256 -cne $manifestHash -or
            $installed.source_commit -cne '359ca92e57b2d74eb407b258cf53123d80ef1467'){
            throw 'Only the completed, unchanged R6 installation may be reused.'}
        $oldRoot=Join-Path $script:base 'R6Acceptance4.2.7-windows-20261012-v1-auth-3579f2f48a4a479087399688e3eb020f'
        $old=Read-R6RecoveryJson (Join-Path $oldRoot 'result.json')
        if($old.phase -cne 'auth' -or $old.status -cne 'PHASE_COMPLETED' -or $old.manifest_sha256 -cne $manifestHash -or
            $old.candidate_sha256 -cne $candidateHash){throw 'Original phase binding differs.'}
        Assert-R6AuthRecoveryRows $old.result
        $held=Read-R6RecoveryJson (Join-Path $script:base 'R6Sitting4.2.7-windows-20261012-fd8b4d855c6942aba8373f196a7161b4\r6-held.json')
        if($held.status -cne 'HELD_PRESERVE_EVIDENCE' -or $held.phase -cne 'auth' -or $held.cutover_requested -ne $false -or
            $held.recovery.ok -ne $true -or $held.recovery.restored -ne $true){throw 'Original hold/recovery binding differs.'}
        if(Test-Path -LiteralPath $candidate.knowledge.state_root){throw 'A later knowledge phase already exists; preserve it.'}
        foreach($folder in Get-ChildItem -LiteralPath $script:base -Directory){
            if($folder.Name -cmatch '^R6Acceptance4\.2\.7-windows-20261012-v1-(knowledge|agent|native|preview)-'){
                throw 'A later acceptance phase already exists; preserve it.'}
            if($folder.Name -clike 'R6Acceptance4.2.7-windows-20261012-v1-auth-*' -and
                (Test-Path -LiteralPath (Join-Path $folder.FullName 'r6_auth_recovery.py'))){
                throw 'A recovery authentication attempt already exists; preserve it and do not repeat.'}}
        Assert-R6NotReferenced
        $null=Assert-R6Tree;Assert-R6Interpreter
        @{status='EXISTING_R6_AUTH_RECOVERY_PREREQUISITES_VERIFIED';installation_repeated=$false;state_modified=$false;
            original_auth_sha256=(Get-FileHash -LiteralPath (Join-Path $oldRoot 'result.json') -Algorithm SHA256).Hash.ToLowerInvariant()}
    }finally{$handle.Dispose()}
}

$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
Invoke-R6AuthRecoveryVerification $InstallerSha256 $PhaseWrapperSha256|ConvertTo-Json -Depth 6
