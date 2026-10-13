#Requires -Version 5.1
<# Read-only prerequisite for the specific 2026-10-12 authentication hold.
   Does not run Python, providers, tasks, installation or a daemon. #>
[CmdletBinding()]
param([string]$InstallerSha256,[string]$PhaseWrapperSha256,[switch]$AuthenticatedContinuation,[switch]$AgentCustodyContinuation,[switch]$NativeRegistryContinuation)

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
    param([string]$InstallerHash,[string]$PhaseHash,[string]$Directory=$PSScriptRoot,[bool]$VerifiedContinuation=$false,[bool]$CustodyContinuation=$false,[bool]$NativeContinuation=$false)
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
        if($NativeContinuation -and -not $CustodyContinuation){throw 'Native continuation requires custody verification.'}
        if($CustodyContinuation){Assert-R6CustodyContinuationEvidence $NativeContinuation}
        else{
            if($VerifiedContinuation){Assert-R6SuccessfulStandaloneSignIn}
            Assert-R6AuthRecoveryEvidence}
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

function Assert-R6NativeContinuationEvidence {
    # Bind the owner's exported 09:34 evidence. Do not retry an arbitrary hold.
    $prefix='R6Acceptance4.2.7-windows-20261012-v1-'
    $rows=@(
        @{phase='auth';id='91783f2dd02046cb898f5f56d6611eb1';file='result.json';hash='a8fe47bba5a6a8437765610042a6d231d8196e5e62e3c7edad7ebb850b64a770';status='PHASE_COMPLETED';result='ALL_SESSIONS_VERIFIED'},
        @{phase='knowledge';id='92f0eb26813548c3a3e63337f64e90d9';file='result.json';hash='1a492e54af1b730645bd06e0a304ef9b1250e777d36fe18e378a1dd00ba4eaf6';status='PHASE_COMPLETED';result='EXISTING_KNOWLEDGE_AUTHORITY_VERIFIED'},
        @{phase='agent';id='85176adb54f04d4ea21eaa66a126b336';file='result.json';hash='1b8e84ccf9eba790ea95572cba320e5e7bffa946e65569ed3c95edd92f118fa9';status='PHASE_COMPLETED';result='SIX_WORKER_AGENT_CUSTODY_VERIFIED'},
        @{phase='native';id='344364d3b6434266a29c7bb61a654220';file='held.json';hash='13a505a84a2d0d2e129e42ae97337f83b01cdcfd6d848bc7ec262bb8af893b90';status='HELD_PRESERVE_PARTIAL';result=$null})
    foreach($entry in $rows){
        $root=Join-Path $script:base ($prefix+$entry.phase+'-'+$entry.id)
        $value=Read-R6RecoveryJson (Join-Path $root $entry.file) $entry.hash
        if($value.schema -cne 'cochem-r6-system-phase/1' -or $value.phase -cne $entry.phase -or
            $value.status -cne $entry.status -or $value.manifest_sha256 -cne 'bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4' -or
            $value.candidate_sha256 -cne 'a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288'){
            throw 'Reviewed native continuation phase differs.'}
        if($entry.result -and $value.result.status -cne $entry.result){throw 'Reviewed successful phase status differs.'}
        if($entry.phase -ceq 'native'){
            if($value.error_type -cne 'ProviderFailure' -or $value.category -cne 'compatibility'){
                throw 'Reviewed native failure category differs.'}
            if(Test-Path -LiteralPath (Join-Path $root 'result.json')){throw 'The held native phase has later completion evidence.'}
            $held=Read-R6RecoveryJson (Join-Path $root 'native\native-held.json') 'f9a489cd608ce0bf2d2046be330aee4f0950c9f1bd533a147ed15e61fe127a85'
            if($held.schema -cne 'cochem-r6-native-acceptance/1' -or $held.phase -cne 'target-00' -or $held.completed -ne 0 -or
                $held.native_plan_sha256 -cne '8b20f15b86945386ae879617f1dd984957082164511621c295300bcf2bfd38bd'){
                throw 'Reviewed first native target differs.'}}
    }
    $restoreRoot=Join-Path $script:base 'WardenRetarget4.2.7-windows-20261011-r4-v9'
    $retarget=Read-R6RecoveryJson (Join-Path $restoreRoot 'retarget-receipt.json') '470901a6b367c1fec344e4177ca4c721dd28d49a2b6f2b528b70a60966f2637a'
    $intent=Read-R6RecoveryJson (Join-Path $restoreRoot 'start-intent.json') 'c550a17610e67da86695412f1616b565edebdccd19d1691de307e8b3f2837bd0'
    if($retarget.schema -cne 'cochem-warden-retarget/3' -or $retarget.status -cne 'WARDEN_RETARGETED_TO_R4_NOT_STARTED' -or
        $retarget.target -cne 'r4' -or $retarget.attempt -cne 'v9' -or $retarget.started -ne $false -or
        $intent.schema -cne 'cochem-warden-start-intent/3' -or $intent.target -cne 'r4' -or $intent.attempt -cne 'v9' -or
        $intent.retarget_receipt_sha256 -cne '470901a6b367c1fec344e4177ca4c721dd28d49a2b6f2b528b70a60966f2637a' -or
        $intent.exactly_one_start -ne $true -or $intent.enable_before_run -ne $true -or $intent.retry -ne $false){
        throw 'Reviewed R4 v9 interrupted-start binding differs.'}
    foreach($name in @('start-receipt.json','start-held.json')){
        if(Test-Path -LiteralPath (Join-Path $restoreRoot $name)){throw 'R4 v9 has later evidence; do not guess a continuation.'}}
    # The released stop helper validates the task/action/process and idle proof
    # again at the actual mutation boundary, using RecoverInterruptedStart.
    foreach($entry in $rows){$prefix+$entry.phase+'-'+$entry.id}
}

function Assert-R6CustodyContinuationEvidence {
    param([bool]$NativeContinuation=$false)
    # A separate, evidence-bound continuation for the completed 07:33 attempt.
    # Do not weaken the old first-auth-hold verifier or rebuild its knowledge.
    $manifestHash='bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4'
    $candidateHash='a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288'
    $null=Read-R6RecoveryJson (Join-Path $script:targetRoot 'install-manifest.json') $manifestHash
    $null=Read-R6RecoveryJson (Join-Path $script:targetRoot 'pipeline.json') $candidateHash
    $installed=Read-R6RecoveryJson (Join-Path $script:targetRoot 'install-after.json')
    if((Test-Path -LiteralPath (Join-Path $script:targetRoot 'install-held.json')) -or
        $installed.status -cne 'STOPPED_RUNTIME_INSTALLED' -or $installed.manifest_sha256 -cne $manifestHash -or
        $installed.source_commit -cne '359ca92e57b2d74eb407b258cf53123d80ef1467'){
        throw 'Only the completed immutable R6 installation may be reused.'}
    $evidence=@(
        @{phase='auth';id='9e0a79eaef0d4c2eb749842913ce38ec';file='result.json';status='PHASE_COMPLETED';hash='32361af0aeee844c2a6173d8f44e3e5898a22d0640adcdb6f8bc9b0f4b026d85'},
        @{phase='knowledge';id='47776d31bd0e4773be318bde56f5be0a';file='result.json';status='PHASE_COMPLETED';hash='5bcc2dc08c3edb5c7918e75f66ef33959b5f5cbaf8d62dd1c2c2c86db73a6abf'},
        @{phase='agent';id='0269bb0c420b488bbb4874841be21ea0';file='held.json';status='HELD_PRESERVE_PARTIAL';hash='5c86817a543f53cdbb6307832bca5dad4634a014f81de88979046eaf8fdab1a4'})
    foreach($entry in $evidence){
        $name='R6Acceptance4.2.7-windows-20261012-v1-'+$entry.phase+'-'+$entry.id
        $row=Read-R6RecoveryJson (Join-Path (Join-Path $script:base $name) $entry.file) $entry.hash
        if($row.schema -cne 'cochem-r6-system-phase/1' -or $row.phase -cne $entry.phase -or
            $row.status -cne $entry.status -or $row.manifest_sha256 -cne $manifestHash -or
            $row.candidate_sha256 -cne $candidateHash){throw 'Reviewed phase binding differs.'}
        if($entry.phase -ceq 'auth' -and ($row.result.status -cne 'ALL_SESSIONS_VERIFIED' -or
            @($row.result.checks).Count -ne 18 -or @($row.result.checks|Where-Object {$_.authenticated -ne $true -or $_.cleanup_verified -ne $true}).Count)){
            throw 'The reviewed successful sign-ins differ.'}
        if($entry.phase -ceq 'knowledge' -and $row.result.status -cne 'NEW_KNOWLEDGE_AUTHORITY_VERIFIED'){
            throw 'The completed knowledge receipt differs.'}
    }
    # This preflight runs as the owner, not SYSTEM. The pinned candidate and
    # prior receipt bind the expected state without opening its SYSTEM-only
    # directory. The mandatory SYSTEM knowledge phase checks the directory,
    # generation, authority and integrity before native acceptance/cutover.
    # Its validate_private_directory call precedes KnowledgeService creation:
    # missing/inaccessible state holds; it is never created or refreshed here.
    $diagnostic=Read-R6RecoveryJson (Join-Path $script:base 'R6AgentDiagnostic427-45da557a0e364dac95d42e2ae2f9a4fc\status.json') 'c124feb02e72f061109624993cb0538ef0ebe30431a3c2eeff39f659ca3b7f0c'
    if($diagnostic.status -cne 'DIAGNOSTIC_CAPTURED' -or @($diagnostic.workers).Count -ne 1 -or
        $diagnostic.workers[0].failure.reason -cne 'CUSTODY_ACCESS_NOT_DENIED' -or
        $diagnostic.workers[0].handle_cleanup_observed -ne $true){throw 'Reviewed directory diagnostic differs.'}
    $restore=Read-R6RecoveryJson (Join-Path $script:base 'WardenRetarget4.2.7-windows-20261011-r4-v8\start-receipt.json') '3cd7e7f1826acc141f7e7144f03c062e32162d5be0a7b6282d82aba3db13fbc4'
    if($restore.schema -cne 'cochem-warden-start/3' -or $restore.status -cne 'WARDEN_R4_RESTARTED_HEALTH_VERIFIED' -or
        $restore.target -cne 'r4' -or $restore.attempt -cne 'v8' -or $restore.enabled_after -ne $true -or
        $restore.running_instances -ne 1 -or $restore.health.samples_stable -ne $true){throw 'Reviewed R4 v8 restoration differs.'}
    $nativeEvidence=@()
    if($NativeContinuation){$nativeEvidence=@(Assert-R6NativeContinuationEvidence)}
    foreach($folder in Get-ChildItem -LiteralPath $script:base -Directory){
        if($folder.Name -cmatch '^R6Acceptance4\.2\.7-windows-20261012-v1-(knowledge|agent|native|preview)-'){
            $allowed=@($evidence|Where-Object {('R6Acceptance4.2.7-windows-20261012-v1-'+$_.phase+'-'+$_.id) -ceq $folder.Name})
            if($allowed.Count -ne 1 -and $folder.Name -cnotin $nativeEvidence){throw 'An unreviewed later R6 phase exists. Preserve it; do not repeat.'}}}
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect()
    foreach($task in @($scheduler.GetFolder('\').GetTasks(1))){
        if([string]$task.Name -cmatch '^CoChem-4\.2\.7-(R6Acceptance-|AgySignIn-|InteractiveAgy|R6AgentDiagnostic-)' -and
            ($task.State -in @(2,4) -or $task.GetInstances(0).Count -ne 0)){throw 'A prior profile or acceptance task is active.'}}
    Assert-R6NotReferenced
    $null=Assert-R6Tree;Assert-R6Interpreter
    @{status='EXISTING_R6_AUTH_RECOVERY_PREREQUISITES_VERIFIED';continuation=$(if($NativeContinuation){'AGY_REGISTRY_REPAIR'}else{'AGENT_CUSTODY_REPAIR'});
        installation_repeated=$false;knowledge_rebuild_allowed=$false;state_modified=$false;
        knowledge_state_verified=$false;knowledge_state_verification='REQUIRED_IN_SYSTEM_KNOWLEDGE_PHASE'}
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
    Invoke-R6AuthRecoveryVerification $InstallerSha256 $PhaseWrapperSha256 $PSScriptRoot ([bool]$AuthenticatedContinuation) ([bool]$AgentCustodyContinuation) ([bool]$NativeRegistryContinuation)|ConvertTo-Json -Depth 6
}catch{
    $failure=$_
    Write-Error -ErrorRecord $failure -ErrorAction Continue
    Get-R6VerificationFailure $failure|ConvertTo-Json -Depth 6
    exit 1
}
