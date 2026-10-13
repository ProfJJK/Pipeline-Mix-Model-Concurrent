#Requires -Version 5.1
<# Consolidated owner entry point. All interactive input is bounded to the
   first 20 minutes. After authentication, every child is noninteractive.
   No automatic second attempt, cleanup, reboot or late sign-in is permitted.
   Engineering sessions prepare/test this file; only the owner runs -Apply. #>
[CmdletBinding()]
param([string]$LaunchManifest,[string]$LaunchManifestSha256,[switch]$Apply)

function Read-R6LaunchManifest {
    param([string]$Path,[string]$Expected)
    if($Expected -cnotmatch '^[a-f0-9]{64}$'){throw 'An exact launch manifest hash is required.'}
    $stream=[IO.File]::Open($Path,'Open','Read','Read')
    try{
        if($stream.Length -gt 4194304){throw 'Launch manifest exceeds bounds.'}
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$hash=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        if($hash -cne $Expected){throw 'Launch manifest changed after preparation.'}
        $stream.Position=0;$reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true,4096,$true)
        try{$value=$reader.ReadToEnd()|ConvertFrom-Json}finally{$reader.Dispose()}
        if($value.schema -cne 'cochem-r6-launch-package/1' -or $value.host -cne 'AETHERDESK' -or
            $value.manifest_sha256 -cnotmatch '^[a-f0-9]{64}$' -or $value.candidate_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            @($value.scripts).Count -lt 10 -or @($value.scripts).Count -gt 1024){throw 'Invalid launch package.'}
        $value
    }finally{$stream.Dispose()}
}

function Open-R6LaunchPins {
    param($Manifest,[string]$Directory,$Handles)
    $pins=@{}
    foreach($row in @($Manifest.scripts)){
        $name=[string]$row.name
        if($name -cnotmatch '^[A-Za-z0-9_.-]+$' -or $pins.ContainsKey($name) -or
            [string]$row.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            ($row.length -isnot [int] -and $row.length -isnot [long]) -or $row.length -lt 0 -or $row.length -gt 16777216){throw 'Unsafe or duplicate launch input.'}
        $path=Join-Path $Directory $name
        $item=Get-Item -LiteralPath $path
        if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Launch input is redirected.'}
        $stream=[IO.File]::Open($path,'Open','Read','Read');$Handles.Add($stream)
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$hash=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        if($hash -cne $row.sha256 -or $stream.Length -ne $row.length){throw ('Launch input differs: '+$name)}
        $stream.Position=0;$pins[$name]=[string]$row.sha256
    }
    foreach($name in @('run_r6_launch.ps1','install_r6_runtime.ps1','run_r6_system_phase.ps1','activate_r6_runtime.ps1',
        'r6_retarget_core.ps1','r6_attended_agy.ps1','RUN_427_R5_SITTING.ps1','stage_aetherdesk_427_payloads.ps1',
        'login_pipeline_worker_agy_terminal.ps1','worker_agy_terminal_bridge.py','attended_agy_terminal.py')){
        if(-not $pins.ContainsKey($name)){throw ('Launch package is missing '+$name)}}
    $pins
}

function Invoke-R6LaunchChild {
    param([string]$Name,[string[]]$Arguments,[switch]$Attended)
    if(-not $script:R6Pins.ContainsKey($Name)){throw 'Child is not in the reviewed launch package.'}
    $path=Join-Path $script:R6Directory $Name
    # The series keeps deny-write/delete handles on every package input until
    # it returns, including the current child and all imported helpers.
    if($Attended){
        if([DateTime]::UtcNow -ge $script:R6InputDeadline){throw 'The owner-input window is closed.'}
        & $script:R6PowerShell -NoLogo -NoProfile -File $path @Arguments
        if($LASTEXITCODE -ne 0){throw 'Attended authentication did not complete. Preserve its receipt.'}
        return
    }
    $preference=$ErrorActionPreference
    try{$ErrorActionPreference='Continue'
        $output=@(& $script:R6PowerShell -NoLogo -NoProfile -NonInteractive -File $path @Arguments 2>&1)
        $code=$LASTEXITCODE
    }finally{$ErrorActionPreference=$preference}
    # Raw output stays in the private sitting folder. Public status contains
    # only phase, fixed status, receipt paths and hashes, never provider output.
    $text=($output|ForEach-Object {$_.ToString()}) -join "`n"
    $log=Join-Path $script:SittingRoot ($script:R6Phase+'-'+[Guid]::NewGuid().ToString('N')+'.log')
    $null=Write-R5RecordText $log $text
    if($code -ne 0){throw ('Phase child failed; protected log: '+$log)}
    $json=Get-R5JsonTail $text
    if($null -eq $json){throw 'Phase child returned no structured result.'}
    $json
}

function Write-R5RecordText {
    param([string]$Path,[string]$Text)
    $acl=[Security.AccessControl.FileSecurity]::new();$acl.SetAccessRuleProtection($true,$false)
    $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
    foreach($sid in @('S-1-5-18','S-1-5-32-544')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','Allow'))}
    $stream=[IO.FileStream]::new($Path,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,4096,[IO.FileOptions]::None,$acl)
    try{$data=[Text.UTF8Encoding]::new($false).GetBytes($Text);$stream.Write($data,0,$data.Length);$stream.Flush($true)}finally{$stream.Dispose()}
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Invoke-R6AcceptancePhase {
    param([string]$Phase,$Manifest)
    $script:R6Phase=$Phase
    Write-R6PublicStatus 'RUNNING'
    Write-Host ('R6 phase: '+$Phase)
    $arguments=@('-Phase',$Phase,'-ManifestSha256',$Manifest.manifest_sha256,
        '-CandidateSha256',$Manifest.candidate_sha256,'-InstallerSha256',$script:R6Pins['install_r6_runtime.ps1'],
        '-Attempt',[Guid]::NewGuid().ToString('N'),'-Apply')
    if($Phase -ceq 'auth' -and (Test-R6AuthRecovery $Manifest)){
        $arguments+=@('-AuthRecoverySha256',$script:R6Pins['r6_auth_recovery.py'])}
    if($Phase -ceq 'native' -and $script:R6Pins.ContainsKey('r6_native_retirement.py')){
        $arguments+=@('-NativeRetirementSha256',$script:R6Pins['r6_native_retirement.py'])}
    Invoke-R6LaunchChild 'run_r6_system_phase.ps1' $arguments
}

function Test-R6AuthRecovery {
    param($Manifest)
    $property=$Manifest.PSObject.Properties['auth_recovery']
    if($null -eq $property){return $false}
    if($property.Value -cne '20261012-first-auth-hold' -or
        $Manifest.manifest_sha256 -cne 'bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4' -or
        $Manifest.candidate_sha256 -cne 'a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288'){
        throw 'Recovery must bind the specific installed R6 release.'}
    return $true
}

function Test-R6VerifiedContinuation {
    param($Manifest)
    $property=$Manifest.PSObject.Properties['verified_signin_continuation']
    if($null -eq $property){return $false}
    if($property.Value -cne '20261013-six-agy-verified-r4-v7' -or -not (Test-R6AuthRecovery $Manifest)){
        throw 'Unreviewed signed-in continuation mode.'}
    foreach($name in @('r6_native_retirement.py','r6_retirement_guard.py')){
        if(-not $script:R6Pins.ContainsKey($name)){throw 'Owner retirement code is not pinned.'}}
    return $true
}

function Write-R6PublicStatus {
    param([string]$Status,$Result=$null)
    if(-not (Test-Path -LiteralPath $script:SittingRoot -PathType Container)){return}
    $safe=[ordered]@{schema='cochem-r6-public-status/1';status=$Status;phase=$script:R6Phase;
        updated_utc=[DateTime]::UtcNow.ToString('o');protected_evidence_root=$script:SittingRoot;
        input_window_ends_utc=$script:R6InputDeadline.ToString('o');late_prompts=$false;full_srs_acceptance=$false}
    if($null -ne $Result){
        foreach($key in @('status','receipt_path','receipt_sha256','phase','error_type','cutover_requested')){
            if($Result -is [Collections.IDictionary]){if($Result.Contains($key)){$safe[$key]=$Result[$key]}}
            elseif($null -ne $Result.PSObject.Properties[$key]){$safe[$key]=$Result.PSObject.Properties[$key].Value}}}
    if($null -ne (Get-Variable -Name R6AuthSummary -Scope Script -ErrorAction SilentlyContinue)){
        $safe.authentication=$script:R6AuthSummary}
    $name='status-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffff')+'-'+[Guid]::NewGuid().ToString('N')+'.json'
    $acl=[Security.AccessControl.FileSecurity]::new();$acl.SetAccessRuleProtection($true,$false)
    $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
    foreach($sid in @('S-1-5-18','S-1-5-32-544')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','Allow'))}
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-5-32-545'),'Read','Allow'))
    $stream=[IO.FileStream]::new((Join-Path $script:SittingRoot $name),[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::Read,4096,[IO.FileOptions]::None,$acl)
    try{$data=[Text.UTF8Encoding]::new($false).GetBytes(($safe|ConvertTo-Json -Depth 5));$stream.Write($data,0,$data.Length);$stream.Flush($true)}finally{$stream.Dispose()}
}

function Save-R6AuthSummary {
    param($Result)
    $rows=@()
    foreach($row in @($Result.checks)){
        if($row.worker -cnotmatch '^slot[1-6]$' -or $row.provider -cnotin @('codex','claude','gemini') -or
            $row.status -cnotin @('REUSE_VERIFIED_SESSION','ATTENDED_LOGIN_REQUIRED','STATUS_UNVERIFIED') -or
            ($row.exit_code -isnot [int] -and $row.exit_code -isnot [long])){throw 'Authentication summary is outside its allowlist.'}
        $item=[ordered]@{worker=$row.worker;provider=$row.provider;status=$row.status;exit_code=$row.exit_code}
        $allowed=@{reason=@('AGY_MODELS_CATALOG_VERIFIED','AGY_MODELS_EXPLICIT_SIGN_OUT','TYPED_AUTH_FAILURE','AGY_STATUS_UNRESOLVED');
            failure_category=@('auth','quota','busy','context','provider','timeout','protocol','code','configuration','compatibility','resource');
            diagnostic_hint=@('Subscription authentication failed','Provider quota or rate limit reached','Provider service unavailable',
                'Unknown native CLI argument or output protocol','Host resources exhausted: out of memory or disk full',
                'Native CLI permission denied','Unclassified native CLI failure; protected logs require diagnosis')}
        foreach($key in @('reason','failure_category','diagnostic_hint')){
            $property=$row.PSObject.Properties[$key]
            if($null -ne $property -and $null -ne $property.Value -and $property.Value -cin $allowed[$key]){$item[$key]=$property.Value}}
        $rows+= $item
    }
    if($rows.Count -ne 18){throw 'Authentication summary inventory differs.'}
    $script:R6AuthSummary=$rows
    Write-R6PublicStatus 'AUTHENTICATION_CHECKED'
}

function Invoke-R6LaunchSequence {
    param($Manifest)
    $script:R6Phase='inspection';Invoke-R5Stage0
    Write-Host ('Sanitized status reports: '+$script:SittingRoot+'\status-*.json')
    Write-R6PublicStatus 'RUNNING'
    $resume=Test-R6AuthRecovery $Manifest
    $signedIn=Test-R6VerifiedContinuation $Manifest
    if($resume){
        $script:R6Phase='verify_existing_installation'
        $verifyArguments=@('-InstallerSha256',$script:R6Pins['install_r6_runtime.ps1'],
            '-PhaseWrapperSha256',$script:R6Pins['run_r6_system_phase.ps1'])
        if($signedIn){$verifyArguments+='-AuthenticatedContinuation'}
        $verified=Invoke-R6LaunchChild 'verify_r6_auth_recovery.ps1' $verifyArguments
        if($verified.status -cne 'EXISTING_R6_AUTH_RECOVERY_PREREQUISITES_VERIFIED'){throw 'Existing R6 recovery prerequisites differ.'}}
    $script:R6Phase='quiescence';Invoke-R5Stage2
    if(-not $resume){
        $script:R6Phase='offline_install'
        $installed=Invoke-R6LaunchChild 'install_r6_runtime.ps1' @('-Manifest',$Manifest.install_manifest,'-ManifestSha256',$Manifest.manifest_sha256,'-Apply')
        if($installed.status -cne 'STOPPED_RUNTIME_INSTALLED'){throw 'Stopped R6 installation was not verified.'}}
    $auth=Invoke-R6AcceptancePhase 'auth' $Manifest
    Save-R6AuthSummary $auth.result
    # This result contains only fixed status metadata. Print it now so a hold
    # never requires the owner to extract another private provider report.
    Write-Host ($auth.result|ConvertTo-Json -Depth 8)
    if($auth.result.status -cne 'ALL_SESSIONS_VERIFIED'){
        if($signedIn){throw 'A verified session changed. Status is recorded above; no legacy sign-in or late prompt was started.'}
        $missing=@($auth.result.checks|Where-Object {$_.authenticated -ne $true})
        # Existing Claude/Codex sign-ins are never copied or reset. An unclear
        # status or expired session is a prerequisite failure at the attended
        # beginning, not permission for a late login or a provider substitution.
        if(@($missing|Where-Object {$_.status -cne 'ATTENDED_LOGIN_REQUIRED' -or $_.provider -cne 'gemini'}).Count){
            throw 'Authentication needs review at the attended start; no late login was requested.'}
        foreach($row in $missing){
            $script:R6Phase='attended_gemini_'+$row.worker
            Invoke-R6LaunchChild 'r6_attended_agy.ps1' @('-Slot',$row.worker,'-DeadlineUtc',$script:R6InputDeadline.ToString('o'),
                '-WrapperSha256',$script:R6Pins['login_pipeline_worker_interactive_agy_r4_v1.ps1'],
                '-TerminalWrapperSha256',$script:R6Pins['login_pipeline_worker_agy_terminal.ps1'],
                '-PublicStatusRoot',$script:SittingRoot,'-Apply') -Attended
        }
        $auth=Invoke-R6AcceptancePhase 'auth' $Manifest
        Save-R6AuthSummary $auth.result
        if($auth.result.status -cne 'ALL_SESSIONS_VERIFIED'){throw 'Authentication remained unverified after the attended window.'}
    }
    Write-Host 'Authentication verified. You can walk away now. No further input or restart is planned.' -ForegroundColor Green
    $script:R6Phase='agent_staging'
    $stage=Invoke-R6LaunchChild 'agy-isolation-evidence-r4-v1.ps1' @('-StageOnly','-Attempt',[Guid]::NewGuid().ToString('N'),'-Apply')
    if($stage.decision -cne 'COMPLETE'){throw 'Protected six-worker agent staging was not verified.'}
    $phases=@($auth)
    foreach($phase in @('knowledge','agent','native','preview')){$phases+=Invoke-R6AcceptancePhase $phase $Manifest}
    $index=[ordered]@{schema='cochem-r6-acceptance-index/1';manifest_sha256=$Manifest.manifest_sha256;candidate_sha256=$Manifest.candidate_sha256;
        phases=@($phases|ForEach-Object {@{phase=$_.phase;receipt_path=$_.receipt_path;receipt_sha256=$_.receipt_sha256}});agent_staging=$stage}
    $indexPath=Join-Path $script:SittingRoot 'acceptance-index.json'
    $indexHash=Write-R5RecordText $indexPath ($index|ConvertTo-Json -Depth 12)
    $script:R6Phase='activation'
    $targetAttempt=Get-R5FreeAttempt 'WardenRetarget4.2.7-windows-20261012-r6-'
    $arguments=@('-CoreSha256',$script:R6Pins['r6_retarget_core.ps1'],'-InstallerSha256',$script:R6Pins['install_r6_runtime.ps1'],
        '-ManifestSha256',$Manifest.manifest_sha256,'-CandidateSha256',$Manifest.candidate_sha256,
        '-EvidencePath',$indexPath,'-EvidenceSha256',$indexHash,'-Attempt',$targetAttempt,'-Apply')
    if($script:R5.base_source.kind -ceq 'r4-restore'){
        $arguments+=@('-SourceAttempt',$script:R5.base_source.source_attempt,'-StopAttempt',$script:R5.base_source.stop_attempt)}
    if($script:R6Pins.ContainsKey('r6_native_retirement.py')){
        $arguments+=@('-RetirementHelperSha256',$script:R6Pins['r6_native_retirement.py'])}
    if($signedIn){$arguments+=@('-RetirementGuardSha256',$script:R6Pins['r6_retirement_guard.py'])}
    $script:R6CutoverRequested=$true
    $activated=Invoke-R6LaunchChild 'activate_r6_runtime.ps1' $arguments
    if($activated.status -cne 'WARDEN_R6_RUNNING_HEALTH_VERIFIED'){throw 'R6 activation was not verified.'}
    # Return through script state. Capturing this sequence's success stream
    # makes PowerShell redirect nested native children, including attended
    # login. Their console handles must remain inherited and interactive.
    $script:R6LaunchResult=$activated
}

function Initialize-R6ReleasedState {
    # Dot-sourcing inside a function binds parameters in that function's scope.
    # The released helpers deliberately read script-scoped parameters instead.
    $script:Attempt='v1';$script:Gemini='attempt'
    $script:EffortNullSlug='gemini-3.8-flash-low'
    $script:SkipFixProof=$true
    Initialize-R5Paths
}

function Invoke-R6LaunchMain {
    param([string]$ManifestPath,[string]$ManifestHash,[bool]$ApplyRequested)
    $manifest=Read-R6LaunchManifest $ManifestPath $ManifestHash
    $script:R6Directory=Split-Path -Parent ([IO.Path]::GetFullPath($ManifestPath))
    if($script:R6Directory -cne $PSScriptRoot){throw 'Launch manifest must be beside this entry point.'}
    $handles=[Collections.Generic.List[IO.FileStream]]::new();$mutex=$null;$locked=$false;$started=$false
    $script:R6CutoverRequested=$false;$script:R6Phase='package';$script:R5=$null
    try{
        $script:R6Pins=Open-R6LaunchPins $manifest $script:R6Directory $handles
        $signedIn=Test-R6VerifiedContinuation $manifest
        if(Test-R6AuthRecovery $manifest){
            foreach($name in @('r6_auth_recovery.py','verify_r6_auth_recovery.ps1')){
                if(-not $script:R6Pins.ContainsKey($name)){throw 'Recovery helper is not pinned.'}}}
        if(-not $ApplyRequested){
            $retired=$script:R6Pins.ContainsKey('r6_native_retirement.py')
            @{status='R6_LAUNCH_PLAN';model_targets=$(if($retired){26}else{27});retired_model_targets=$(if($retired){1}else{0});
                maximum_shared_slots=4;input_window_minutes=20;later_prompts=$false;reuse_verified_sessions=$signedIn;
                runtime_retirement_guard=$signedIn;installation_and_host_acceptance_executed=$false}|ConvertTo-Json;return
        }
        $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
        if($PSVersionTable.PSEdition -cne 'Desktop' -or -not [Environment]::Is64BitProcess -or $env:COMPUTERNAME -cne 'AETHERDESK' -or
            $identity.Name -cne 'AETHERDESK\ansac' -or -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
            throw 'Run once in 64-bit Administrator Windows PowerShell as AETHERDESK\ansac.'}
        $script:R6InputDeadline=[DateTime]::UtcNow.AddMinutes(20)
        $mutex=[Threading.Mutex]::new($false,'Global\CoChem427-R6Launch')
        try{$locked=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$locked=$true;throw 'An earlier launch was interrupted. Preserve its evidence; no automatic resume.'}
        if(-not $locked){throw 'Another R6 launch is already active.'}
        $script:R6PowerShell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        # Loading this reviewed script defines its functions only. Never call
        # Invoke-R5Series: R6 has its own install, candidate, tests and cutover.
        . (Join-Path $script:R6Directory 'RUN_427_R5_SITTING.ps1') -Attempt 'v1' -Gemini 'attempt' -SkipFixProof
        Initialize-R6ReleasedState
        $script:SittingRoot=Join-Path $script:Base ('R6Sitting4.2.7-windows-20261012-'+[Guid]::NewGuid().ToString('N'))
        $started=$true
        $script:R6LaunchResult=$null
        Invoke-R6LaunchSequence $manifest
        $result=$script:R6LaunchResult
        if($null -eq $result){throw 'R6 sequence did not record its completion result.'}
        $script:R6Phase='complete'
        $null=Write-R5RecordText (Join-Path $script:SittingRoot 'r6-complete.json') ($result|ConvertTo-Json -Depth 12)
        Write-R6PublicStatus 'COMPLETE' $result
        $result|ConvertTo-Json -Depth 8
    }catch{
        $failure=$_;$restore=$null
        # Before the R6 task transaction, the unchanged released R5 recovery
        # code can restore the exact proven R4 source. After that boundary,
        # preserve a possibly running R6 process and never guess a rollback.
        if($started -and -not $script:R6CutoverRequested -and $null -ne $script:R5 -and $script:R5.s2_done){
            try{$restore=Invoke-R5Restore 'R6 preparation held before cutover'}catch{$restore=@{ok=$false;restored=$false}}}
        $record=@{schema='cochem-r6-launch-result/1';status='HELD_PRESERVE_EVIDENCE';phase=$script:R6Phase;error_type=$failure.Exception.GetType().Name;
            automatic_retry=$false;late_prompt=$false;cutover_requested=$script:R6CutoverRequested;recovery=$restore;activation_ready=$false}
        if($started -and (Test-Path -LiteralPath $script:SittingRoot)){
            $record.receipt_path=Join-Path $script:SittingRoot 'r6-held.json'
            $null=Write-R5RecordText $record.receipt_path ($record|ConvertTo-Json -Depth 8)}
        if($started){Write-R6PublicStatus 'HELD' $record}
        $record|ConvertTo-Json -Depth 8
        throw $failure
    }finally{foreach($stream in $handles){$stream.Dispose()};if($locked){$mutex.ReleaseMutex()};if($null -ne $mutex){$mutex.Dispose()}}
}

$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
Invoke-R6LaunchMain $LaunchManifest $LaunchManifestSha256 ([bool]$Apply)
