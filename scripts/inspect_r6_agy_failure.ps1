#Requires -Version 5.1
<# Read-only diagnosis of the owner's 2026-10-12 failed Agy session.
   Never opens operator.log, input.once, credentials, profiles or databases.
   No task is registered, run, stopped or changed. Only a fresh sanitized report
   is written in the ordinary deployment engineering workspace. #>
[CmdletBinding()]
param([string]$OutputDirectory='C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next')

function Get-R6AgyDiagnosticValue {
    param($Record,[string]$Name)
    if($null -eq $Record){return $null}
    if($Record -is [Collections.IDictionary]){if($Record.Contains($Name)){return $Record[$Name]};return $null}
    $property=$Record.PSObject.Properties[$Name]
    if($null -ne $property){return $property.Value}
    return $null
}

function Select-R6AgyDiagnosticFields {
    param($Record,[string[]]$Booleans=@(),[string[]]$Integers=@(),$Enums=@{},[string[]]$Hashes=@())
    $safe=[ordered]@{}
    foreach($name in $Booleans){
        $value=Get-R6AgyDiagnosticValue $Record $name
        if($null -ne $value){if($value -isnot [bool]){throw 'Diagnostic boolean type differs.'};$safe[$name]=$value}}
    foreach($name in $Integers){
        $value=Get-R6AgyDiagnosticValue $Record $name
        if($null -ne $value){if(($value -isnot [int] -and $value -isnot [long]) -or $value -lt 0){throw 'Diagnostic integer type differs.'};$safe[$name]=$value}}
    foreach($name in $Enums.Keys){
        $value=Get-R6AgyDiagnosticValue $Record $name
        if($null -ne $value){if($value -isnot [string] -or $value -cnotin $Enums[$name]){throw 'Diagnostic enum value differs.'};$safe[$name]=$value}}
    foreach($name in $Hashes){
        $value=Get-R6AgyDiagnosticValue $Record $name
        if($null -ne $value){if($value -isnot [string] -or $value -cnotmatch '^[a-f0-9]{64}$'){throw 'Diagnostic digest type differs.'};$safe[$name]=$value}}
    return $safe
}

function Read-R6AgyDiagnosticRecord {
    param([string]$Path,[string]$Schema)
    $item=Get-Item -LiteralPath $Path -ErrorAction Stop
    if($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        $item.Length -le 0 -or $item.Length -gt 1048576){throw 'Diagnostic record must be a bounded ordinary file.'}
    $stream=[IO.File]::Open($Path,'Open','Read','Read')
    try{
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$hash=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        $stream.Position=0;$reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true,4096,$true)
        try{$record=$reader.ReadToEnd()|ConvertFrom-Json}finally{$reader.Dispose()}
        if((Get-R6AgyDiagnosticValue $record 'schema') -cne $Schema){throw 'Diagnostic record schema differs.'}
        return @{record=$record;sha256=$hash}
    }finally{$stream.Dispose()}
}

function Get-R6AgyFailureProjection {
    param($Receipt,$Held)
    $markers=Get-R6AgyDiagnosticValue $Receipt 'native_markers'
    $markerNames=@('url_present','google_accounts_url_present','paste_prompt_present','waiting_line_present',
        'token_exchanged_present','authenticated_as_present','authentication_required_present',
        'no_controlling_terminal_present','authentication_interrupted_present','auth_timed_out_present',
        'authorization_code_empty_present','no_authorization_code_received_present','authentication_failed_present',
        'rate_limit_present','verification_present','appeal_present','unusual_activity_present')
    $safeMarkers=[ordered]@{}
    foreach($phase in @('before_input','after_input')){
        $safeMarkers[$phase]=Select-R6AgyDiagnosticFields (Get-R6AgyDiagnosticValue $markers $phase) -Booleans $markerNames}
    $receiptSafe=Select-R6AgyDiagnosticFields $Receipt -Booleans @('cleanup_verified','one_line_submitted',
        'input_file_deleted','operator_cancelled','terminated_after_input','authentication_verified','activation_ready',
        'secret_published','native_output_after_input_published','input_closed_marker_written','pause_marker_seen') `
        -Integers @('native_exit_code','login_commands_executed','model_jobs_executed','started_at_unix_ms','finished_at_unix_ms') `
        -Enums @{status=@('UNVERIFIED','LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED','LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED',
            'LOGIN_COMMAND_FAILED','LOGIN_FAILED_OR_CANCELLED','CLEANUP_UNVERIFIED');login_mode=@('print','tui')} `
        -Hashes @('helper_sha256','support_sha256','native_executable_sha256','native_executable_sha256_after')
    $receiptSafe.native_markers=$safeMarkers
    foreach($key in @('failure','login_failure')){
        $receiptSafe[$key]=Select-R6AgyDiagnosticFields (Get-R6AgyDiagnosticValue $Receipt $key) `
            -Enums @{phase=@('runtime_custody','layout','native_custody','native_launch','native_attestation','native_wait','native_result','native_cleanup');
                error_type=@('NativeLoginExitNonZero','TimeoutError','InterruptedError','NativeOutputBoundError','WindowsIsolationError',
                    'PermissionError','ValueError','RuntimeError','OSError','BrokenPipeError')} -Integers @('winerror')}
    $storage=Get-R6AgyDiagnosticValue $Receipt 'token_storage_observed'
    $receiptSafe.token_storage_observed=Select-R6AgyDiagnosticFields $storage -Booleans @('file_token_present','file_token_regular',
        'credential_manager_entry_present','token_contents_read') -Enums @{file_check=@('ok','not_run','failed');
        credential_manager_check=@('ok','not_run','failed','timed_out')}
    $heldSafe=Select-R6AgyDiagnosticFields $Held -Booleans @('task_registered','run_requested','receipt_present',
        'raw_provider_output_recorded','code_recorded','login_authorized','automatic_retry_allowed','requires_owner_review') `
        -Enums @{phase=@('ROOT','COPY','REGISTER','RUN','CONSOLE','TERMINAL','INPUT_CLEANUP','RECEIPT','DECISION','RESULT');login_mode=@('print','tui')} `
        -Hashes @('receipt_sha256')
    $heldSafe.task_after=Select-R6AgyDiagnosticFields (Get-R6AgyDiagnosticValue $Held 'task_after') -Integers @('state','last_task_result','instances')
    $heldSafe.console=Select-R6AgyDiagnosticFields (Get-R6AgyDiagnosticValue $Held 'console') -Booleans @('native_prompt_seen',
        'one_line_submitted','cancel_requested','input_window_closed','code_prompt_held')
    $heldSafe.input_cleanup=Select-R6AgyDiagnosticFields (Get-R6AgyDiagnosticValue $Held 'input_cleanup') -Booleans @('input_present','consumed','deleted')
    return @{receipt=$receiptSafe;held=$heldSafe}
}

function Get-R6AgyAuthProjection {
    param($Envelope)
    $safe=Select-R6AgyDiagnosticFields $Envelope -Enums @{phase=@('auth');status=@('PHASE_COMPLETED')} `
        -Hashes @('manifest_sha256','candidate_sha256')
    $value=Get-R6AgyDiagnosticValue $Envelope 'result'
    $safe.result=Select-R6AgyDiagnosticFields $value -Enums @{schema=@('cochem-r6-authentication/1');
        status=@('ATTENDED_AUTH_REVIEW_REQUIRED','ALL_SESSIONS_VERIFIED')} -Booleans @('credentials_copied','activation_ready') `
        -Integers @('native_model_jobs_executed') -Hashes @('status_helper_sha256')
    $rows=@(Get-R6AgyDiagnosticValue $value 'checks')
    if($rows.Count -ne 18){throw 'Diagnostic authentication inventory differs.'}
    $safe.result.checks=@(foreach($row in $rows){
        Select-R6AgyDiagnosticFields $row -Booleans @('authenticated','cleanup_verified') -Integers @('exit_code','stdout_bytes','stderr_bytes') `
            -Hashes @('stdout_sha256','stderr_sha256') -Enums @{worker=@('slot1','slot2','slot3','slot4','slot5','slot6');
                provider=@('codex','claude','gemini');status=@('REUSE_VERIFIED_SESSION','ATTENDED_LOGIN_REQUIRED','STATUS_UNVERIFIED');
                reason=@('AGY_MODELS_CATALOG_VERIFIED','AGY_MODELS_EXPLICIT_SIGN_OUT','TYPED_AUTH_FAILURE','AGY_STATUS_UNRESOLVED')}})
    return $safe
}

function Invoke-R6AgyFailureDiagnostic {
    param([string]$Directory)
    $base='C:\Program Files\CoChem'
    $root=Join-Path $base 'InteractiveAgy427-r4-slot1-67d70b0983cc48e2abf7c561aca29f86'
    $receipt=Read-R6AgyDiagnosticRecord (Join-Path $root 'receipt.json') 'cochem-interactive-agy-login/1'
    $held=Read-R6AgyDiagnosticRecord (Join-Path $root 'session-held.json') 'cochem-interactive-agy-login-held/1'
    foreach($value in @($receipt.record,$held.record)){
        if((Get-R6AgyDiagnosticValue $value 'slot') -cne 'slot1' -or
            (Get-R6AgyDiagnosticValue $value 'nonce') -cne '67d70b0983cc48e2abf7c561aca29f86'){throw 'Diagnostic session identity differs.'}}
    if((Get-R6AgyDiagnosticValue $held.record 'receipt_sha256') -cne $receipt.sha256){throw 'Held receipt digest differs.'}
    $report=[ordered]@{schema='cochem-r6-agy-failure-diagnostic/1';session_root=$root;
        receipt_sha256=$receipt.sha256;held_sha256=$held.sha256;projection=(Get-R6AgyFailureProjection $receipt.record $held.record);
        protected_state_modified=$false;native_commands_executed=0;credentials_read=$false;raw_provider_output_read=$false}
    $auth=@()
    $folders=@(Get-ChildItem -LiteralPath $base -Directory -Filter 'R6Acceptance4.2.7-windows-20261012-v1-auth-*' -ErrorAction Stop)
    if($folders.Count -gt 32){throw 'Diagnostic authentication census exceeds its bound.'}
    foreach($folder in $folders){
        if($folder.Name -cnotmatch '^R6Acceptance4\.2\.7-windows-20261012-v1-auth-[a-f0-9]{32}$'){throw 'Diagnostic authentication name differs.'}
        $record=Read-R6AgyDiagnosticRecord (Join-Path $folder.FullName 'result.json') 'cochem-r6-system-phase/1'
        $auth+=@{root_name=$folder.Name;sha256=$record.sha256;projection=(Get-R6AgyAuthProjection $record.record)}}
    $report.authentication=$auth
    $restore=Read-R6AgyDiagnosticRecord (Join-Path $base 'WardenRetarget4.2.7-windows-20261011-r4-v5\start-receipt.json') 'cochem-warden-start/3'
    $report.restore_sha256=$restore.sha256
    $report.restore=Select-R6AgyDiagnosticFields $restore.record -Booleans @('enabled_after','exactly_one_start_requested','automatic_retry_allowed') `
        -Integers @('task_state','running_instances','health_samples') -Enums @{status=@('WARDEN_R4_RESTARTED_HEALTH_VERIFIED');target=@('r4');attempt=@('v5')}
    $destination=[IO.Path]::GetFullPath($Directory)
    if(-not (Test-Path -LiteralPath $destination -PathType Container) -or
        ($destination -cne 'C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next')){
        throw 'Use the existing ordinary deployment engineering workspace.'}
    $path=Join-Path $destination ('r6-agy-failure-diagnostic-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffff')+'-'+[Guid]::NewGuid().ToString('N')+'.json')
    $data=[Text.UTF8Encoding]::new($false).GetBytes(($report|ConvertTo-Json -Depth 8))
    $stream=[IO.File]::Open($path,'CreateNew','Write','Read')
    try{$stream.Write($data,0,$data.Length);$stream.Flush($true)}finally{$stream.Dispose()}
    @{schema='cochem-r6-agy-failure-diagnostic-result/1';status='SANITIZED_READ_ONLY_DIAGNOSTIC_SAVED';report_path=$path;
        protected_state_modified=$false;native_commands_executed=0}|ConvertTo-Json -Compress
}

$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
Invoke-R6AgyFailureDiagnostic $OutputDirectory
