#Requires -Version 5.1
<# Read-only prerequisite for the specific 2026-10-12 authentication hold.
   Does not run Python, providers, tasks, installation or a daemon. #>
[CmdletBinding()]
param([string]$InstallerSha256,[string]$PhaseWrapperSha256,[switch]$AuthenticatedContinuation)

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
    param($Value,[ValidateSet('STATUS_UNVERIFIED','ATTENDED_LOGIN_REQUIRED')][string]$AgyStatus='STATUS_UNVERIFIED')
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
            if($row.authenticated -ne $false -or $row.status -cne $AgyStatus -or $row.exit_code -ne 1){throw 'Original Agy failure differs.'}
        }elseif($row.authenticated -ne $true -or $row.status -cne 'REUSE_VERIFIED_SESSION' -or $row.exit_code -ne 0){
            throw 'Original successful sessions differ.'}
    }
}

function Get-R6ReviewedAuthTask {
    param([ValidateSet('CoChem-4.2.7-R6Acceptance-auth-226ce1d64f29486c838fca043f6bf904','CoChem-4.2.7-R6Acceptance-auth-56126335ff314eb497cd409fd58e6b1e','CoChem-4.2.7-R6Acceptance-auth-f1b5e414c1b44a5fb3c7d7686dbc9ff8','CoChem-4.2.7-R6Acceptance-auth-d16cef7a1743414db634d8a47acf894f','CoChem-4.2.7-R6Acceptance-auth-c5ffd975db154abe9411be085e25f96d')]
        [string]$Name='CoChem-4.2.7-R6Acceptance-auth-226ce1d64f29486c838fca043f6bf904')
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect()
    $scheduler.GetFolder('\').GetTask($Name)
}

function Assert-R6ReviewedRestore {
    param($Receipt,[ValidateSet('v3','v4','v5','v6','v7')][string]$Attempt='v3')
    # This is the hash-bound persisted start receipt, not a launch-series
    # result. The production writer does not put a "started" flag in it.
    if($Receipt.schema -cne 'cochem-warden-start/3' -or
        $Receipt.status -cne 'WARDEN_R4_RESTARTED_HEALTH_VERIFIED' -or $Receipt.target -cne 'r4' -or
        $Receipt.attempt -cne $Attempt -or $Receipt.task_name -cne 'CoChem-4.2.7-Warden' -or
        $Receipt.enabled_after -ne $true -or $Receipt.task_state -ne 4 -or $Receipt.running_instances -ne 1 -or
        $Receipt.health_samples -ne 2 -or $Receipt.health.samples_stable -ne $true -or
        $Receipt.exactly_one_start_requested -ne $true -or $Receipt.automatic_retry_allowed -ne $false){
        throw 'Reviewed R4 restoration differs.'}
}

function Get-R6Slot1InteractiveTasks {
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect()
    @($scheduler.GetFolder('\').GetTasks(1)|Where-Object {[string]$_.Name -clike 'CoChem-4.2.7-InteractiveAgy-r4-slot1-*'})
}

function Assert-R6ReviewedAuthTask {
    param([string]$Root,[string]$Name)
    $task=Get-R6ReviewedAuthTask $Name
    $executable=Join-Path $script:targetRoot '.venv\Scripts\python.exe'
    $arguments='-I -B "'+(Join-Path $Root 'r6_auth_recovery.py')+'" --output "'+$Root+'" --manifest-hash bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4 --candidate-hash a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288'
    Assert-R6PhaseTask $task $executable $arguments $script:targetRoot 900 $true
    if($task.State -notin @(1,3) -or $task.GetInstances(0).Count -ne 0 -or [int]$task.LastTaskResult -ne 0 -or
        $task.LastRunTime -lt [DateTime]'2026-10-12'){throw 'Reviewed authentication task is not terminal and successful.'}
}

function Assert-R6ReviewedConsoleHold {
    param([string]$Root)
    $result=Read-R6RecoveryJson (Join-Path $Root 'result.json')
    if($result.phase -cne 'auth' -or $result.status -cne 'PHASE_COMPLETED' -or
        $result.manifest_sha256 -cne 'bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4' -or
        $result.candidate_sha256 -cne 'a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288' -or
        $result.result.status_helper_sha256 -cne '79b7029cd998f25c0a01300924bb3972f830f7783618ce3c99260b089510aaec'){
        throw 'Reviewed console-hold authentication binding differs.'}
    Assert-R6AuthRecoveryRows $result.result 'ATTENDED_LOGIN_REQUIRED'
    foreach($row in @($result.result.checks|Where-Object {$_.provider -ceq 'gemini'})){
        if($row.reason -cne 'AGY_MODELS_EXPLICIT_SIGN_OUT' -or $row.stdout_bytes -ne 0 -or $row.stderr_bytes -ne 122 -or
            $row.stdout_sha256 -cne 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855' -or
            $row.stderr_sha256 -cne '148fc48c6aeaf4d5f5780d0e38fc39215de098c1537c57e09410d4dad9718a1d'){
            throw 'Reviewed console-hold sign-out evidence differs.'}}
    $held=Read-R6RecoveryJson (Join-Path $script:base 'R6Sitting4.2.7-windows-20261012-04883067accd48e48ca6b097296f2d93\r6-held.json')
    if($held.status -cne 'HELD_PRESERVE_EVIDENCE' -or $held.phase -cne 'attended_gemini_slot1' -or
        $held.cutover_requested -ne $false -or $held.recovery.ok -ne $true -or $held.recovery.restored -ne $true -or
        $held.recovery.kind -cne 'base'){throw 'Reviewed console hold/restoration differs.'}
    $restore=Read-R6RecoveryJson (Join-Path $script:base 'WardenRetarget4.2.7-windows-20261011-r4-v4\start-receipt.json') '4b20035cdcb90d9547dbe95a1302ba7574424877dedfa7ae0db1da4d5e849852'
    Assert-R6ReviewedRestore $restore 'v4'
    Assert-R6ReviewedAuthTask $Root 'CoChem-4.2.7-R6Acceptance-auth-56126335ff314eb497cd409fd58e6b1e'
    # The session census is evaluated once after all reviewed authentication
    # attempts. Only the separately hash-bound native failure below can admit
    # its one preserved terminal session; every other root/task remains a hold.
}

function Assert-R6ReviewedInteractiveCensus {
    param([bool]$ReviewedNativeFailure=$false,[bool]$ReviewedTuiFailure=$false)
    $roots=@(Get-ChildItem -LiteralPath $script:base -Directory -Filter 'InteractiveAgy427-r4-slot1-*')
    $tasks=@(Get-R6Slot1InteractiveTasks)
    if(-not $ReviewedNativeFailure){
        if($roots.Count -ne 0 -or $tasks.Count -ne 0){throw 'A slot1 interactive login session exists; preserve and review it.'}
        return
    }
    $nonces=@('67d70b0983cc48e2abf7c561aca29f86')
    if($ReviewedTuiFailure){$nonces+='43804e7a8d44457aa9810305923c219f'}
    if($roots.Count -ne $nonces.Count -or $tasks.Count -ne $nonces.Count){throw 'Interactive login inventory differs from reviewed terminal failures.'}
    foreach($nonce in $nonces){
        $rootName='InteractiveAgy427-r4-slot1-'+$nonce;$taskName='CoChem-4.2.7-InteractiveAgy-r4-slot1-'+$nonce
        $matched=@($roots|Where-Object {$_.Name -ceq $rootName -and $_.FullName -ceq (Join-Path $script:base $rootName)})
        if($matched.Count -ne 1 -or @($tasks|Where-Object {$_.Name -ceq $taskName}).Count -ne 1){throw 'Interactive login inventory contains an unreviewed root or task.'}
    }
}

function Assert-R6ReviewedTuiReceipt {
    param($Receipt)
    if($Receipt.schema -cne 'cochem-interactive-agy-login/1' -or $Receipt.slot -cne 'slot1' -or
        $Receipt.nonce -cne '43804e7a8d44457aa9810305923c219f' -or $Receipt.login_mode -cne 'tui' -or
        $Receipt.status -cne 'LOGIN_FAILED_OR_CANCELLED' -or $Receipt.system_sid -cne 'S-1-5-18' -or
        $Receipt.cleanup_verified -isnot [bool] -or -not $Receipt.cleanup_verified -or $Receipt.one_line_submitted -ne $false -or
        $Receipt.input_closed_marker_written -ne $true -or $Receipt.login_commands_executed -ne 1 -or $Receipt.model_jobs_executed -ne 0 -or
        $Receipt.authentication_verified -ne $false -or $Receipt.activation_ready -ne $false -or $Receipt.secret_published -ne $false -or
        $Receipt.native_output_after_input_published -ne $false -or $Receipt.native_output_bytes_before_input -ne 0 -or
        $Receipt.native_output_published_bytes_before_input -ne 0 -or $Receipt.failure.phase -cne 'native_wait' -or
        $Receipt.failure.error_type -cne 'TimeoutError' -or $null -ne $Receipt.failure.winerror -or
        $Receipt.helper_sha256 -cne '4074878f100ae59b804c95bd97b3280ccaa09f919ffaa365a3e2c6985045b8d9' -or
        $Receipt.support_sha256 -cne '45681477194d97b144e8ee4505d4364d73d58aaef19c8428c846df642c834839' -or
        $Receipt.native_executable_sha256 -cne '38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741'){
        throw 'The reviewed zero-output terminal session differs.'}
}

function Get-R6ReviewedTuiTask {
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect()
    $scheduler.GetFolder('\').GetTask('CoChem-4.2.7-InteractiveAgy-r4-slot1-43804e7a8d44457aa9810305923c219f')
}

function Assert-R6ReviewedTuiSession {
    # The outer console failed to finish. Do not infer a rollback from that
    # missing record: bind the independently completed owner recovery instead.
    $nonce='43804e7a8d44457aa9810305923c219f';$root=Join-Path $script:base ('InteractiveAgy427-r4-slot1-'+$nonce)
    $receipt=Read-R6RecoveryJson (Join-Path $root 'receipt.json') 'dfad79544643ccfbca3653a66024f3e3020fa63ea23f46ce702430da9376b72a'
    Assert-R6ReviewedTuiReceipt $receipt
    if((Test-Path -LiteralPath (Join-Path $root 'input.once')) -or (Test-Path -LiteralPath (Join-Path $root 'session-result.json')) -or
        (Test-Path -LiteralPath (Join-Path $root 'session-held.json'))){throw 'The reviewed TUI attempt now has different terminal artifacts.'}
    $task=Get-R6ReviewedTuiTask
    $python='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\Scripts\python.exe'
    $arguments='-I -B "'+(Join-Path $root 'worker_agy_login_bridge_r4_v1.py')+'" --slot slot1 --nonce '+$nonce+' --login-mode tui'
    Assert-R6PhaseTask $task $python $arguments $root 900 $true
    if($task.Name -cne ('CoChem-4.2.7-InteractiveAgy-r4-slot1-'+$nonce) -or $task.State -ne 3 -or
        $task.GetInstances(0).Count -ne 0 -or [long]$task.LastTaskResult -ne 2){throw 'The reviewed TUI task is not terminal.'}
    $null=Read-R6RecoveryJson (Join-Path $script:base 'WardenStop4.2.7-windows-20261011-r5-v5\stop-receipt.json') 'f62d79731b2e1d0440f1ed49b6d43334f8ff3ddfc2b1a45ab670a85f0d232d67'
    $null=Read-R6RecoveryJson (Join-Path $script:base 'WardenRetarget4.2.7-windows-20261011-r4-v6\retarget-receipt.json') '0a59de000c06cda9426ea5f9e7f76ff1e9f63dd11c33ced8a85f7cbffa577fc7'
    $restore=Read-R6RecoveryJson (Join-Path $script:base 'WardenRetarget4.2.7-windows-20261011-r4-v6\start-receipt.json') 'f2de0214197af0c54ff04c25246dd74a13d210de007fc107e6d485b9ad5ab50f'
    Assert-R6ReviewedRestore $restore 'v6'
    foreach($payload in @([pscustomobject]@{name='worker_agy_login_bridge_r4_v1.py';hash=$receipt.helper_sha256},
        [pscustomobject]@{name='worker_native_status_support.py';hash=$receipt.support_sha256})){
        $path=Join-Path $root $payload.name;Assert-ProtectedPath $path;$length=(Get-Item -LiteralPath $path).Length
        if($length -gt 1048576){throw 'The reviewed TUI helper exceeds its bound.'}
        $handle=Open-VerifiedFile $path $payload.hash $length;try{}finally{$handle.Dispose()}
    }
}

function Assert-R6ReviewedTuiAuth {
    param([string]$Root)
    if($Root -cne (Join-Path $script:base 'R6Acceptance4.2.7-windows-20261012-v1-auth-d16cef7a1743414db634d8a47acf894f')){throw 'Unreviewed TUI authentication namespace.'}
    $result=Read-R6RecoveryJson (Join-Path $Root 'result.json')
    if($result.phase -cne 'auth' -or $result.status -cne 'PHASE_COMPLETED' -or
        $result.manifest_sha256 -cne 'bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4' -or
        $result.candidate_sha256 -cne 'a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288' -or
        $result.result.status_helper_sha256 -cne '79b7029cd998f25c0a01300924bb3972f830f7783618ce3c99260b089510aaec'){
        throw 'The preserved TUI authentication binding differs.'}
    Assert-R6AuthRecoveryRows $result.result 'ATTENDED_LOGIN_REQUIRED'
    foreach($row in @($result.result.checks|Where-Object {$_.provider -ceq 'gemini'})){
        if($row.reason -cne 'AGY_MODELS_EXPLICIT_SIGN_OUT' -or $row.stdout_bytes -ne 0 -or $row.stderr_bytes -ne 122 -or
            $row.stdout_sha256 -cne 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855' -or
            $row.stderr_sha256 -cne '148fc48c6aeaf4d5f5780d0e38fc39215de098c1537c57e09410d4dad9718a1d'){
            throw 'Preserved TUI authentication was not the exact explicit sign-out protocol.'}}
    Assert-R6ReviewedAuthTask $Root 'CoChem-4.2.7-R6Acceptance-auth-d16cef7a1743414db634d8a47acf894f'
    Assert-R6ReviewedTuiSession
}

function Assert-R6ReviewedNativeLoginFailure {
    param([string]$Root)
    $result=Read-R6RecoveryJson (Join-Path $Root 'result.json') 'dc0af0b999e6e4a0cd72fed5b80fc05cfd30a85edf76d1ce659cc3b5b69aa5e0'
    if($result.phase -cne 'auth' -or $result.status -cne 'PHASE_COMPLETED' -or
        $result.manifest_sha256 -cne 'bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4' -or
        $result.candidate_sha256 -cne 'a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288' -or
        $result.result.status_helper_sha256 -cne '79b7029cd998f25c0a01300924bb3972f830f7783618ce3c99260b089510aaec'){
        throw 'Reviewed native-login authentication binding differs.'}
    Assert-R6AuthRecoveryRows $result.result 'ATTENDED_LOGIN_REQUIRED'
    foreach($row in @($result.result.checks|Where-Object {$_.provider -ceq 'gemini'})){
        if($row.reason -cne 'AGY_MODELS_EXPLICIT_SIGN_OUT' -or $row.stdout_bytes -ne 0 -or $row.stderr_bytes -ne 122 -or
            $row.stdout_sha256 -cne 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855' -or
            $row.stderr_sha256 -cne '148fc48c6aeaf4d5f5780d0e38fc39215de098c1537c57e09410d4dad9718a1d'){
            throw 'Reviewed native-login sign-out evidence differs.'}}
    Assert-R6ReviewedAuthTask $Root 'CoChem-4.2.7-R6Acceptance-auth-f1b5e414c1b44a5fb3c7d7686dbc9ff8'
    $held=Read-R6RecoveryJson (Join-Path $script:base 'R6Sitting4.2.7-windows-20261012-87bf2f05e1254ea6b5e7de51018b830c\r6-held.json')
    if($held.status -cne 'HELD_PRESERVE_EVIDENCE' -or $held.phase -cne 'attended_gemini_slot1' -or
        $held.cutover_requested -ne $false -or $held.recovery.ok -ne $true -or $held.recovery.restored -ne $true -or
        $held.recovery.kind -cne 'base'){throw 'Reviewed native-login hold/restoration differs.'}
    $restore=Read-R6RecoveryJson (Join-Path $script:base 'WardenRetarget4.2.7-windows-20261011-r4-v5\start-receipt.json') '978bad6cf2773df7151c21cca988e4ebd9a4549f9639976f920a9567d803528c'
    Assert-R6ReviewedRestore $restore 'v5'
    Assert-R6ReviewedAgySession
}

function Get-R6ReviewedAgyTask {
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect()
    $scheduler.GetFolder('\').GetTask('CoChem-4.2.7-InteractiveAgy-r4-slot1-67d70b0983cc48e2abf7c561aca29f86')
}

function Assert-R6ReviewedAgySession {
    # This admits only the exact terminal session inspected by the owner. It
    # never authorizes sign-in; the launch series must obtain fresh status.
    $nonce='67d70b0983cc48e2abf7c561aca29f86'
    $root=Join-Path $script:base ('InteractiveAgy427-r4-slot1-'+$nonce)
    $receiptHash='882326a4f4b30ca527cf22faaf5c15f528a9eb40421bc5aa052a12bfd77e9ec0'
    $receipt=Read-R6RecoveryJson (Join-Path $root 'receipt.json') $receiptHash
    $held=Read-R6RecoveryJson (Join-Path $root 'session-held.json') '52c9911858aa5b68b885e2c7f2c55402f52c91d810b2b4bd3529394f75fb24a8'
    if($receipt.schema -cne 'cochem-interactive-agy-login/1' -or $receipt.slot -cne 'slot1' -or
        $receipt.nonce -cne $nonce -or $receipt.login_mode -cne 'print' -or $receipt.status -cne 'LOGIN_COMMAND_FAILED' -or
        $receipt.cleanup_verified -ne $true -or $receipt.one_line_submitted -ne $true -or $receipt.input_file_deleted -ne $true -or
        $receipt.operator_cancelled -ne $false -or $receipt.terminated_after_input -ne $false -or
        $receipt.input_closed_marker_written -ne $true -or $receipt.native_exit_code -ne 1 -or
        $receipt.login_commands_executed -ne 1 -or $receipt.model_jobs_executed -ne 0 -or
        $receipt.authentication_verified -ne $false -or $receipt.activation_ready -ne $false -or
        $receipt.secret_published -ne $false -or $receipt.native_output_after_input_published -ne $false -or
        $receipt.pause_marker_seen -ne $false -or $receipt.native_markers.after_input.authentication_failed_present -ne $true -or
        $receipt.helper_sha256 -cne '4074878f100ae59b804c95bd97b3280ccaa09f919ffaa365a3e2c6985045b8d9' -or
        $receipt.support_sha256 -cne '45681477194d97b144e8ee4505d4364d73d58aaef19c8428c846df642c834839' -or
        $receipt.native_executable_sha256 -cne '38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741' -or
        $receipt.native_executable_sha256_after -cne $receipt.native_executable_sha256){
        throw 'Reviewed native-login receipt differs; preserve its state.'}
    if($held.phase -cne 'DECISION' -or $held.login_mode -cne 'print' -or $held.receipt_sha256 -cne $receiptHash -or
        $held.task_registered -ne $true -or $held.run_requested -ne $true -or $held.receipt_present -ne $true -or
        $held.raw_provider_output_recorded -ne $false -or $held.code_recorded -ne $false -or $held.login_authorized -ne $false -or
        $held.automatic_retry_allowed -ne $false -or $held.requires_owner_review -ne $true -or
        $held.task_after.state -ne 3 -or $held.task_after.instances -ne 0 -or $held.task_after.last_task_result -ne 2 -or
        $held.input_cleanup.input_present -ne $false){throw 'Reviewed native-login wrapper evidence differs.'}
    $task=Get-R6ReviewedAgyTask
    $python='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\Scripts\python.exe'
    $arguments='-I -B "'+(Join-Path $root 'worker_agy_login_bridge_r4_v1.py')+'" --slot slot1 --nonce '+$nonce+' --login-mode print'
    Assert-R6PhaseTask $task $python $arguments $root 900 $true
    if($task.Name -cne ('CoChem-4.2.7-InteractiveAgy-r4-slot1-'+$nonce) -or $task.State -ne 3 -or
        $task.GetInstances(0).Count -ne 0 -or [int]$task.LastTaskResult -ne 2 -or $task.LastRunTime -lt [DateTime]'2026-10-12'){
        throw 'Reviewed native-login task is not the exact terminal task.'}
    if(Test-Path -LiteralPath (Join-Path $root 'input.once')){throw 'Native-login input remains; preserve it.'}
    foreach($payload in @([pscustomobject]@{name='worker_agy_login_bridge_r4_v1.py';hash=$receipt.helper_sha256},
        [pscustomobject]@{name='worker_native_status_support.py';hash=$receipt.support_sha256})){
        $path=Join-Path $root $payload.name;Assert-ProtectedPath $path
        $length=(Get-Item -LiteralPath $path).Length
        if($length -gt 1048576){throw 'Reviewed native-login helper exceeds its bound.'}
        $handle=Open-VerifiedFile $path $payload.hash $length;try{}finally{$handle.Dispose()}
    }
}

function Assert-R6ReviewedPrefixFailure {
    param([string]$Root)
    # Explicitly reviewed owner attempt, never a general retry exemption.
    $result=Read-R6RecoveryJson (Join-Path $Root 'result.json')
    if($result.phase -cne 'auth' -or $result.status -cne 'PHASE_COMPLETED' -or
        $result.manifest_sha256 -cne 'bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4' -or
        $result.candidate_sha256 -cne 'a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288' -or
        $result.result.status_helper_sha256 -cne '574e5b220fb15963b0d4d3e1561402d946d6caedc70b1ac268d2f0d6546ddf53'){
        throw 'The reviewed prefix failure binding differs.'}
    Assert-R6AuthRecoveryRows $result.result
    foreach($row in @($result.result.checks|Where-Object {$_.provider -ceq 'gemini'})){
        if($row.reason -cne 'AGY_STATUS_UNRESOLVED' -or $row.stdout_bytes -ne 0 -or $row.stderr_bytes -ne 122 -or
            $row.stdout_sha256 -cne 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855' -or
            $row.stderr_sha256 -cne '148fc48c6aeaf4d5f5780d0e38fc39215de098c1537c57e09410d4dad9718a1d'){
            throw 'Only the exact owner-reported Agy prefix failure is reviewed.'}}
    $held=Read-R6RecoveryJson (Join-Path $script:base 'R6Sitting4.2.7-windows-20261012-d31408eed013418a8e64c9a4b8d6734b\r6-held.json')
    if($held.status -cne 'HELD_PRESERVE_EVIDENCE' -or $held.phase -cne 'auth' -or $held.cutover_requested -ne $false -or
        $held.recovery.ok -ne $true -or $held.recovery.restored -ne $true -or $held.recovery.kind -cne 'base'){
        throw 'The reviewed attempt did not restore its pre-cutover controller.'}
    $restore=Read-R6RecoveryJson (Join-Path $script:base 'WardenRetarget4.2.7-windows-20261011-r4-v3\start-receipt.json') '3e32dc204f9003c709a758f9025610204b4596cfaa67ac31be379bd7a94a067b'
    Assert-R6ReviewedRestore $restore
    Assert-R6ReviewedAuthTask $Root 'CoChem-4.2.7-R6Acceptance-auth-226ce1d64f29486c838fca043f6bf904'
}

function Get-R6SignInTasks {
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect()
    @($scheduler.GetFolder('\').GetTasks(1)|Where-Object {$_.Name -cmatch '^CoChem-4\.2\.7-(InteractiveAgyTerminal|AgySignIn)-'})
}

function Assert-R6ReviewedRegistrationHold {
    param([string]$Root)
    $result=Read-R6RecoveryJson (Join-Path $Root 'result.json')
    if($result.phase -cne 'auth' -or $result.status -cne 'PHASE_COMPLETED' -or
        $result.manifest_sha256 -cne 'bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4' -or
        $result.candidate_sha256 -cne 'a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288' -or
        $result.result.status_helper_sha256 -cne '79b7029cd998f25c0a01300924bb3972f830f7783618ce3c99260b089510aaec'){
        throw 'The reviewed pre-registration authentication binding differs.'}
    Assert-R6AuthRecoveryRows $result.result 'ATTENDED_LOGIN_REQUIRED'
    Assert-R6ReviewedAuthTask $Root 'CoChem-4.2.7-R6Acceptance-auth-c5ffd975db154abe9411be085e25f96d'
    $terminalRoot=Join-Path $script:base 'InteractiveAgyTerminal427-r4-slot1-920c3ba4a0aa4c1094eaf4ce3319eba4'
    $held=Read-R6RecoveryJson (Join-Path $terminalRoot 'session-held.json')
    if($held.schema -cne 'cochem-interactive-agy-terminal-held/1' -or $held.status -cne 'HELD' -or
        $held.slot -cne 'slot1' -or $held.nonce -cne '920c3ba4a0aa4c1094eaf4ce3319eba4' -or
        $held.phase -cne 'register' -or $held.run_requested -ne $false -or $null -ne $held.receipt_sha256 -or
        $held.raw_provider_output_recorded -ne $false -or $held.code_recorded -ne $false){throw 'The preserved never-run terminal hold differs.'}
    foreach($name in @('receipt.json','session-result.json','input.once')){
        if(Test-Path -LiteralPath (Join-Path $terminalRoot $name)){throw 'The reviewed never-run terminal has later artifacts.'}}
    $tasks=@(Get-R6SignInTasks|Where-Object {$_.Name -ceq 'CoChem-4.2.7-InteractiveAgyTerminal-r4-slot1-920c3ba4a0aa4c1094eaf4ce3319eba4'})
    if($tasks.Count -ne 1){throw 'Reviewed terminal task inventory differs.'}
    $task=$tasks[0]
    $arguments='-I -B "'+(Join-Path $terminalRoot 'worker_agy_terminal_bridge.py')+'" --slot slot1 --nonce 920c3ba4a0aa4c1094eaf4ce3319eba4'
    Assert-R6PhaseTask $task 'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\Scripts\python.exe' $arguments $terminalRoot 900 $true
    if($task.State -ne 3 -or $task.GetInstances(0).Count -ne 0 -or $task.LastTaskResult -ne 267011 -or
        $task.LastRunTime -ge [DateTime]'2026-10-12'){throw 'The reviewed terminal task is no longer never-run.'}
    $restore=Read-R6RecoveryJson (Join-Path $script:base 'WardenRetarget4.2.7-windows-20261011-r4-v7\start-receipt.json') '449bff46b15018e1ff47e389c5765df49f86b4cee36e3b1c8778390568e4cf97'
    Assert-R6ReviewedRestore $restore 'v7'
    $null=Read-R6RecoveryJson (Join-Path $script:base 'WardenRetarget4.2.7-windows-20261011-r4-v7\retarget-receipt.json') '80c50e6272940fe89bf53e2c01e9c38481ab6b1e32b7392d4c7946fed1c29d67'
}

function Assert-R6VerifiedSignInRows {
    param($Value)
    if($Value.status -cne 'ALL_SIX_AGY_PROFILES_VERIFIED' -or @($Value.checks).Count -ne 6 -or
        $Value.native_model_jobs_executed -ne 0 -or $Value.daemon_tasks_changed -ne $false -or
        $Value.credentials_copied -ne $false -or $Value.activation_ready -ne $false){throw 'The six-profile sign-in evidence differs.'}
    $seen=@{}
    foreach($row in @($Value.checks)){
        if($row.slot -cnotmatch '^slot[1-6]$' -or $seen.ContainsKey($row.slot) -or $row.authenticated -ne $true -or
            $row.status -cne 'SIGNED_IN_AND_VERIFIED' -or $row.cleanup_verified -ne $true -or
            $row.after.decision -cne 'VERIFIED' -or $row.after.exit_code -ne 0 -or $row.after.cleanup_verified -ne $true){
            throw 'A profile lacks post-login verification or cleanup.'}
        # The broker projects cleanup_verified onto the profile row above.
        # Its nested login projection contains terminal cleanup and input facts,
        # not another cleanup_verified property (see sequence() in the writer).
        foreach($field in @('terminal_cleanup_verified','input_file_deleted','code_write_completed')){
            if($row.login.$field -ne $true){throw 'A reviewed profile login did not finish cleanup.'}}
        $seen[$row.slot]=$true
    }
}

function Assert-R6SuccessfulStandaloneSignIn {
    $nonce='6f2553e0f3e04a1598e64ffaad1d7255';$root=Join-Path $script:base ('AgySignIn427-'+$nonce)
    $public=Read-R6RecoveryJson (Join-Path $root 'status.json') '96e4d2a872ff64a265efde9f1d1dade42db73f9da85863befc93692ece7ccfff'
    if($public.schema -cne 'cochem-agy-signin-result/1' -or $public.root -cne $root){throw 'Verified sign-in public binding differs.'}
    Assert-R6VerifiedSignInRows $public
    $private=Read-R6RecoveryJson (Join-Path $root 'result.json')
    if($private.schema -cne 'cochem-agy-signin-batch/1' -or $private.nonce -cne $nonce -or $private.system_sid -cne 'S-1-5-18'){
        throw 'Verified sign-in private binding differs.'}
    Assert-R6VerifiedSignInRows $private
    $names=@('CoChem-4.2.7-InteractiveAgyTerminal-r4-slot1-920c3ba4a0aa4c1094eaf4ce3319eba4',
        'CoChem-4.2.7-AgySignIn-29d5943c97954a7695d57c722e917cd2',('CoChem-4.2.7-AgySignIn-'+$nonce))
    $tasks=@(Get-R6SignInTasks)
    if($tasks.Count -ne $names.Count){throw 'An unreviewed profile sign-in task exists.'}
    foreach($task in $tasks){
        if($task.Name -cnotin $names -or $task.GetInstances(0).Count -ne 0 -or $task.State -notin @(1,3)){
            throw 'A profile sign-in task is active or unreviewed.'}
        if($task.Name -ceq $names[2] -and $task.LastTaskResult -ne 0){throw 'The successful sign-in broker is not terminal and successful.'}
        if($task.Name -ceq $names[1]){
            if($task.LastTaskResult -ne 2){throw 'The earlier prompt failure changed.'}
            $failedRoot=Join-Path $script:base 'AgySignIn427-29d5943c97954a7695d57c722e917cd2'
            $null=Read-R6RecoveryJson (Join-Path $failedRoot 'status.json') 'a2d3cf3bbaf19f6917ac3826f3fc4bc3774f9fc327e24419e2cf0cb0449ccfa0'
            $login=Read-R6RecoveryJson (Join-Path $failedRoot 'slot1\login.json')
            if($login.cleanup_verified -ne $true -or $login.terminal_cleanup_verified -ne $true -or $login.one_line_submitted -ne $false){
                throw 'The earlier prompt failure did not complete cleanup.'}}
    }
    foreach($slot in 1..6){if(Test-Path -LiteralPath (Join-Path $root ('slot'+$slot+'\input.once'))){throw 'Sign-in input remains; preserve it.'}}
}

function Invoke-R6AuthRecoveryVerification {
    param([string]$InstallerHash,[string]$PhaseHash,[string]$Directory=$PSScriptRoot,[bool]$VerifiedContinuation=$false)
    foreach($hash in @($InstallerHash,$PhaseHash)){if($hash -cnotmatch '^[a-f0-9]{64}$'){throw 'Recovery helper pins are required.'}}
    $phase=Join-Path $Directory 'run_r6_system_phase.ps1'
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
        foreach($definition in @(Import-R6PhaseInstaller $InstallerHash $Directory)){. ([scriptblock]::Create($definition))}
        Set-R6Constants
        foreach($definition in @(Import-R6CopyFunctions $Directory)){. ([scriptblock]::Create($definition))}
        Initialize-FileIdentity
        if($VerifiedContinuation){Assert-R6SuccessfulStandaloneSignIn}
        Assert-R6AuthRecoveryEvidence
    }finally{$handle.Dispose()}
}

function Get-R6VerificationFailure {
    param([Management.Automation.ErrorRecord]$Failure)
    # Publish only source positions and exception types, never error messages,
    # evidence contents, full paths, provider output, URLs or account details.
    $kind=$Failure.Exception.GetType().Name
    if($kind -cnotin @('RuntimeException','PropertyNotFoundException','PSArgumentException',
        'ArgumentException','InvalidOperationException','UnauthorizedAccessException','IOException',
        'ItemNotFoundException','CommandNotFoundException','MethodInvocationException',
        'ParameterBindingException','ParameterBindingValidationException','COMException')){$kind='OtherException'}
    $frames=@()
    foreach($match in [regex]::Matches([string]$Failure.ScriptStackTrace,'(?m)^at ([A-Za-z0-9_-]+), [^\r\n]*: line ([0-9]{1,7})\r?$')){
        $name=$match.Groups[1].Value
        if($name -cmatch '^(Assert|Read|Open|Get|Import|Initialize|Invoke|Set)-R6[A-Za-z0-9-]*$' -or
            $name -cin @('Assert-ProtectedPath','Open-VerifiedFile','Initialize-FileIdentity')){
            $frames+=@{function=$name;line=[int]$match.Groups[2].Value}
            if($frames.Count -ge 6){break}}
    }
    @{schema='cochem-r6-verification-failure/1';status='VERIFICATION_FAILED';error_type=$kind;
        hresult=[int]$Failure.Exception.HResult;frames=$frames;raw_error_published=$false}
}

function Assert-R6AuthRecoveryEvidence {
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
        $reviewedNativeFailure=$false;$reviewedTuiFailure=$false
        foreach($folder in Get-ChildItem -LiteralPath $script:base -Directory){
            if($folder.Name -cmatch '^R6Acceptance4\.2\.7-windows-20261012-v1-(knowledge|agent|native|preview)-'){
                throw 'A later acceptance phase already exists; preserve it.'}
            if($folder.Name -clike 'R6Acceptance4.2.7-windows-20261012-v1-auth-*' -and
                (Test-Path -LiteralPath (Join-Path $folder.FullName 'r6_auth_recovery.py'))){
                switch -CaseSensitive ($folder.Name){
                    'R6Acceptance4.2.7-windows-20261012-v1-auth-226ce1d64f29486c838fca043f6bf904'{Assert-R6ReviewedPrefixFailure $folder.FullName}
                    'R6Acceptance4.2.7-windows-20261012-v1-auth-56126335ff314eb497cd409fd58e6b1e'{Assert-R6ReviewedConsoleHold $folder.FullName}
                    'R6Acceptance4.2.7-windows-20261012-v1-auth-f1b5e414c1b44a5fb3c7d7686dbc9ff8'{Assert-R6ReviewedNativeLoginFailure $folder.FullName;$reviewedNativeFailure=$true}
                    'R6Acceptance4.2.7-windows-20261012-v1-auth-d16cef7a1743414db634d8a47acf894f'{Assert-R6ReviewedTuiAuth $folder.FullName;$reviewedTuiFailure=$true}
                    'R6Acceptance4.2.7-windows-20261012-v1-auth-c5ffd975db154abe9411be085e25f96d'{Assert-R6ReviewedRegistrationHold $folder.FullName}
                    default {throw 'An unreviewed recovery authentication attempt exists; preserve it and do not repeat.'}
                }}}
        Assert-R6ReviewedInteractiveCensus $reviewedNativeFailure $reviewedTuiFailure
        Assert-R6NotReferenced
        $null=Assert-R6Tree;Assert-R6Interpreter
        @{status='EXISTING_R6_AUTH_RECOVERY_PREREQUISITES_VERIFIED';installation_repeated=$false;state_modified=$false;
            original_auth_sha256=(Get-FileHash -LiteralPath (Join-Path $oldRoot 'result.json') -Algorithm SHA256).Hash.ToLowerInvariant()}
}

$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
try{
    Invoke-R6AuthRecoveryVerification $InstallerSha256 $PhaseWrapperSha256 $PSScriptRoot ([bool]$AuthenticatedContinuation)|ConvertTo-Json -Depth 6
}catch{
    $failure=$_
    Write-Error -ErrorRecord $failure -ErrorAction Continue
    Get-R6VerificationFailure $failure|ConvertTo-Json -Depth 6
    exit 1
}
