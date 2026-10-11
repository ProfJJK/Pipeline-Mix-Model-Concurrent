#Requires -Version 5.1
<# Functions only (Gemini build-manifest step 4). Read-only review of preserved, protected agy (Gemini) login
   sessions of the r4 runtime: roots C:\Program Files\CoChem\InteractiveAgy427-r4-<slot>-<nonce> and their
   one-shot tasks CoChem-4.2.7-InteractiveAgy-r4-<slot>-<nonce>, produced by
   login_pipeline_worker_interactive_agy_r4_v1.ps1 and worker_agy_login_bridge_r4_v1.py.
   Parameterised re-issue of Assert-ReviewedClaudeHistory (claude-session-history-v6.ps1, sha256 36cac78f...):
   r4 runtime pins, the agy bridge/support pins, receipt schema cochem-interactive-agy-login/1, both accepted
   terminal statuses (LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED, LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED),
   and the older-session guard 'any InteractiveAgy427-<slot>-* root without -r4-'.
   Onboarding fix wave: the bridge's sanitized pre-input output-bound stop (failure NativeOutputBoundError, flag
   native_output_bound_reached_before_input) is the reviewed terminal class TERMINAL_OUTPUT_BOUND_NATIVE_LOGIN_CLEANUP_VERIFIED,
   so it never blocks the slot; raw pre-input bytes are bounded by the bridge's login window, published bytes by
   output_limit; every launched session must have written its input.closed marker (input_closed_marker_written).
   Assert-AgyHistoryReceipt is the single receipt classifier: the wrapper binds a fresh session's receipt with it
   and the six-worker driver reviews history with Assert-ReviewedAgyHistory before every attended login.
   A historical receipt never authorizes a login: the caller must obtain a current explicit logged-out status
   and attended READY. Import these definitions from a pinned, held source; do not dot-source a mutable copy.
   Caller-provided functions: Assert-NoReparseAncestors, Assert-ProtectedPath (stage_aetherdesk_427_payloads.ps1),
   Read-R3Control, Read-R3Text (check-worker-native-status-r3.ps1) and Get-ExactTaskOrAbsent
   (login_pipeline_worker_interactive_r3_v6.ps1). Never reads operator.log, input.once or cancel.request. #>

function Get-AgyHistoryParent {'C:\Program Files\CoChem'}

function Get-AgyHistoryPins {
    [ordered]@{
        runtime_root='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4'
        python='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\Scripts\python.exe'
        layout='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\windows-layout.json'
        install='629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502'
        manifest='1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189'
        config='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
        revision='38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e'
        resource='de7fac91e32cef2f854bd53487037352bbc0915f95aaf987ee8a4a543317915f'
        layout_sha256='8430fdf1109c63c4a89479f03da8a465dfebf5566c7791c64f868202170672c4'
        bridge='4074878f100ae59b804c95bd97b3280ccaa09f919ffaa365a3e2c6985045b8d9'
        support='45681477194d97b144e8ee4505d4364d73d58aaef19c8428c846df642c834839'
        agy='38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741'
        bridge_name='worker_agy_login_bridge_r4_v1.py'
        support_name='worker_native_status_support.py'
        root_prefix='InteractiveAgy427-r4-'
        task_prefix='CoChem-4.2.7-InteractiveAgy-r4-'
        task_time_limit='PT15M'
        output_limit=131072
    }
}

function Get-AgyHistoryMarkerNames {
    param([ValidateSet('before_input','after_input','pause','failure')][string]$Kind)
    $common=@('paste_prompt_present','waiting_line_present','token_exchanged_present','authenticated_as_present','authentication_required_present',
        'no_controlling_terminal_present','authentication_interrupted_present','auth_timed_out_present','authorization_code_empty_present',
        'no_authorization_code_received_present','authentication_failed_present','rate_limit_present','verification_present','appeal_present','unusual_activity_present')
    switch -CaseSensitive ($Kind){
        'before_input'{@('url_present','google_accounts_url_present')+$common}
        'after_input'{$common}
        'pause'{@('rate_limit_present','verification_present','appeal_present','unusual_activity_present')}
        'failure'{@('authentication_required_present','no_controlling_terminal_present','authentication_interrupted_present','auth_timed_out_present',
            'authorization_code_empty_present','no_authorization_code_received_present','authentication_failed_present')}
    }
}

function Test-AgyHistoryInteger {
    param($Value,[long]$Minimum=0,[long]$Maximum=4294967295)
    return (($Value -is [int] -or $Value -is [long]) -and $Value -ge $Minimum -and $Value -le $Maximum)
}

function Get-AgyHistoryValue {
    param($Value,[string]$Name,[switch]$Optional)
    if($Value -is [Collections.IDictionary]){
        $keys=@($Value.Keys|Where-Object{$_ -is [string] -and $_ -ceq $Name})
        if($keys.Count -eq 1){return $Value[$keys[0]]}
    }elseif($null -ne $Value){
        $properties=@($Value.PSObject.Properties|Where-Object{$_.Name -ceq $Name})
        if($properties.Count -eq 1){return $properties[0].Value}
    }
    if($Optional){return $null}
    throw 'Historical agy evidence is missing a required exact field.'
}

function Test-AgyHistoryProperty {
    param($Value,[string]$Name)
    return ($null -ne $Value -and @($Value.PSObject.Properties|Where-Object{$_.Name -ceq $Name}).Count -eq 1)
}

function Get-AgyHistorySafeReceiptMetadata {
    param($Receipt)
    # Allowlisted projection only: never a path, message, marker text, e-mail or token.
    $result=[ordered]@{}
    $status=Get-AgyHistoryValue $Receipt 'status' -Optional
    if($status -is [string] -and $status -cin @('UNVERIFIED','LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED','LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED','LOGIN_COMMAND_FAILED','LOGIN_FAILED_OR_CANCELLED','CLEANUP_UNVERIFIED')){$result.status=$status}
    $mode=Get-AgyHistoryValue $Receipt 'login_mode' -Optional
    if($mode -is [string] -and $mode -cin @('print','tui')){$result.login_mode=$mode}
    foreach($name in @('login_commands_executed','model_jobs_executed')){
        $value=Get-AgyHistoryValue $Receipt $name -Optional
        if(Test-AgyHistoryInteger $value 0 1){$result[$name]=$value}
    }
    foreach($name in @('pause_marker_seen','one_line_submitted','terminated_after_input','operator_cancelled','cleanup_verified',
        'input_closed_marker_written','native_output_bound_reached_before_input')){
        $value=Get-AgyHistoryValue $Receipt $name -Optional
        if($value -is [bool]){$result[$name]=$value}
    }
    $code=Get-AgyHistoryValue $Receipt 'native_exit_code' -Optional
    if(Test-AgyHistoryInteger $code 0 4294967295){$result.native_exit_code=$code}
    foreach($key in @('failure','login_failure')){
        $failure=Get-AgyHistoryValue $Receipt $key -Optional
        if($null -ne $failure){
            $safe=[ordered]@{}
            $phase=Get-AgyHistoryValue $failure 'phase' -Optional
            if($phase -is [string] -and $phase -cin @('trusted_preflight','reservation','runtime_custody','layout','boundaries','native_custody','native_launch','native_attestation','native_wait','native_cleanup','native_result','daemon_postcheck')){$safe.phase=$phase}
            $kind=Get-AgyHistoryValue $failure 'error_type' -Optional
            if($kind -is [string] -and $kind -cmatch '\A[A-Za-z][A-Za-z0-9_]{0,79}\z'){$safe.error_type=$kind}
            $winerror=Get-AgyHistoryValue $failure 'winerror' -Optional
            if($null -eq $winerror -or (Test-AgyHistoryInteger $winerror 0 4294967295)){$safe.winerror=$winerror}
            if($safe.Count){$result[$key]=$safe}
        }
    }
    $markers=Get-AgyHistoryValue $Receipt 'native_markers' -Optional
    if($null -ne $markers){
        $seen=@()
        foreach($phaseName in @('before_input','after_input')){
            $phaseValue=Get-AgyHistoryValue $markers $phaseName -Optional
            if($null -eq $phaseValue){continue}
            foreach($name in @(Get-AgyHistoryMarkerNames -Kind $phaseName)){
                $flag=Get-AgyHistoryValue $phaseValue $name -Optional
                if($flag -is [bool] -and $flag -and $name -cnotin $seen){$seen+=$name}
            }
        }
        $result.markers_seen=@($seen)
    }
    return [pscustomobject]$result
}

function Assert-AgyHistoryPrivateAcl {
    param($Acl,[switch]$Directory,[switch]$AllowInherited)
    $rules=@($Acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
    if(($Directory -and $AllowInherited) -or (-not $Acl.AreAccessRulesProtected -and -not $AllowInherited) -or $Acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -cnotin @('S-1-5-18','S-1-5-32-544') -or $rules.Count -ne 2){throw 'Historical agy evidence must retain its exact private ownership and ACL.'}
    $expectedInheritance=if($Directory){[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'}else{[Security.AccessControl.InheritanceFlags]::None}
    $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach($rule in $rules){
        if($rule.IdentityReference.Value -cnotin @('S-1-5-18','S-1-5-32-544') -or -not $seen.Add($rule.IdentityReference.Value) -or
           $rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or [long]$rule.FileSystemRights -ne 2032127 -or
           $rule.InheritanceFlags -ne $expectedInheritance -or $rule.PropagationFlags -ne [Security.AccessControl.PropagationFlags]::None){throw 'Historical agy evidence private grants differ.'}
    }
}

function Assert-AgyHistoryPrivateRoot {
    param([string]$Path)
    Assert-NoReparseAncestors $Path
    Assert-ProtectedPath $Path
    $item=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if(-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Historical agy session root must be an ordinary private directory.'}
    Assert-AgyHistoryPrivateAcl (Get-Acl -LiteralPath $Path -ErrorAction Stop) -Directory
}

function Get-AgyHistoryTaskArguments {
    param([string]$Root,[string]$Slot,[string]$Nonce,[string]$LoginMode)
    '-I -B "'+(Join-Path $Root 'worker_agy_login_bridge_r4_v1.py')+'" --slot '+$Slot+' --nonce '+$Nonce+' --login-mode '+$LoginMode
}

function Assert-AgyHistoryTask {
    param($Task,[string]$Root,[string]$Slot,[string]$Nonce)
    # Returns the login mode fixed in the task action (print or tui).
    $pins=Get-AgyHistoryPins
    if($null -eq $Task){throw 'Historical agy session task is absent; preserve evidence for diagnosis.'}
    if($Task.Name -cne ($pins.task_prefix+$Slot+'-'+$Nonce)){throw 'Historical agy task name differs from its exact session.'}
    if(-not (Test-AgyHistoryInteger $Task.State 1 3) -or $Task.State -notin @(1,3) -or $Task.GetInstances(0).Count -ne 0){throw 'Historical agy session task is not conclusively terminal.'}
    $definition=$Task.Definition
    if($definition.Principal.UserId -cnotin @('SYSTEM','S-1-5-18') -or $definition.Principal.LogonType -ne 5 -or $definition.Principal.RunLevel -ne 1 -or
       $definition.Triggers.Count -ne 0 -or $definition.Actions.Count -ne 1){throw 'Historical agy session task identity or fixed action differs.'}
    $action=$definition.Actions.Item(1)
    $mode=$null
    foreach($candidate in @('print','tui')){if($action.Arguments -ceq (Get-AgyHistoryTaskArguments $Root $Slot $Nonce $candidate)){$mode=$candidate}}
    if($action.Type -ne 0 -or $action.Path -cne $pins.python -or $null -eq $mode -or $action.WorkingDirectory -cne $Root -or
       $definition.Settings.MultipleInstances -ne 2 -or $definition.Settings.ExecutionTimeLimit -cne $pins.task_time_limit -or $definition.Settings.RestartCount -ne 0){
        throw 'Historical agy session task identity or fixed action differs.'
    }
    if(-not (Test-AgyHistoryInteger $Task.LastTaskResult 0 4294967295)){throw 'Historical agy task result is not a bounded integer.'}
    return $mode
}

function Assert-AgyHistoryProcess {
    param($Process,[string]$ExpectedSid)
    if($Process -isnot [Management.Automation.PSCustomObject]){throw 'Historical agy native child attestation must be a JSON object.'}
    foreach($name in @('token_sid','source','profile_directory_sha256')){
        if((Get-AgyHistoryValue $Process $name) -isnot [string]){throw 'Historical agy child identity must be a JSON string.'}
    }
    foreach($name in @('pid','creation_time_filetime')){
        $value=Get-AgyHistoryValue $Process $name
        if($value -isnot [int] -and $value -isnot [long]){throw 'Historical agy child identifiers must be JSON integers.'}
    }
    if((Get-AgyHistoryValue $Process 'token_sid') -cne $ExpectedSid -or
       (Get-AgyHistoryValue $Process 'source') -cne 'owned_windows_process_handle_and_child_token' -or
       -not (Test-AgyHistoryInteger (Get-AgyHistoryValue $Process 'pid') 1 4294967295) -or
       -not (Test-AgyHistoryInteger (Get-AgyHistoryValue $Process 'creation_time_filetime') 1 ([long]::MaxValue)) -or
       (Get-AgyHistoryValue $Process 'profile_directory_sha256') -cnotmatch '\A[a-f0-9]{64}\z'){throw 'Historical agy native child attestation differs.'}
    foreach($name in @('token_matches_selected_worker','image_matches_reviewed_executable','owned_job_membership_verified')){
        $flag=Get-AgyHistoryValue $Process $name;if($flag -isnot [bool] -or -not $flag){throw 'Historical agy native child verification flag differs.'}
    }
}

function Assert-AgyHistoryMarkers {
    param($Markers)
    # Returns the pause flag and the names of the failure markers seen; only allowlisted booleans are accepted.
    if($Markers -isnot [Management.Automation.PSCustomObject]){throw 'Historical agy marker evidence must be a JSON object.'}
    $phases=@($Markers.PSObject.Properties|ForEach-Object{$_.Name})
    if($phases.Count -ne 2 -or 'before_input' -cnotin $phases -or 'after_input' -cnotin $phases){throw 'Historical agy marker phases differ from the pinned producer.'}
    $pause=$false;$failures=@();$pauseNames=@(Get-AgyHistoryMarkerNames -Kind 'pause');$failureNames=@(Get-AgyHistoryMarkerNames -Kind 'failure')
    foreach($phaseName in @('before_input','after_input')){
        $expected=@(Get-AgyHistoryMarkerNames -Kind $phaseName)
        $value=$Markers.PSObject.Properties[$phaseName].Value
        if($value -isnot [Management.Automation.PSCustomObject]){throw 'Historical agy marker phase must be a JSON object.'}
        $names=@($value.PSObject.Properties|ForEach-Object{$_.Name})
        if($names.Count -ne $expected.Count -or @($names|Where-Object{$_ -cnotin $expected}).Count){throw 'Historical agy marker names differ from the pinned producer.'}
        foreach($property in $value.PSObject.Properties){
            if($property.Value -isnot [bool]){throw 'Historical agy markers must be JSON booleans.'}
            if($property.Value -and $property.Name -cin $pauseNames){$pause=$true}
            if($property.Value -and $property.Name -cin $failureNames -and $property.Name -cnotin $failures){$failures+=$property.Name}
        }
    }
    [pscustomobject]@{pause_marker_seen=$pause;failure_markers=@($failures)}
}

function Assert-AgyHistoryTokenStorage {
    param($Value)
    $expected=@('file_check','file_token_present','file_token_bytes','file_token_regular','credential_manager_check','credential_manager_entry_present','credential_manager_matching_entries','token_contents_read')
    if($Value -isnot [Management.Automation.PSCustomObject]){throw 'Historical agy token-storage observation must be a JSON object.'}
    $names=@($Value.PSObject.Properties|ForEach-Object{$_.Name})
    if($names.Count -ne $expected.Count -or @($names|Where-Object{$_ -cnotin $expected}).Count){throw 'Historical agy token-storage fields differ from the pinned producer.'}
    $fileCheck=$Value.file_check;$present=$Value.file_token_present;$bytes=$Value.file_token_bytes;$regular=$Value.file_token_regular
    $credentialCheck=$Value.credential_manager_check;$entry=$Value.credential_manager_entry_present;$matching=$Value.credential_manager_matching_entries
    if($Value.token_contents_read -isnot [bool] -or $Value.token_contents_read){throw 'Historical agy evidence claims a token read.'}
    if($fileCheck -isnot [string] -or $fileCheck -cnotin @('ok','failed','not_run') -or $credentialCheck -isnot [string] -or $credentialCheck -cnotin @('ok','failed','timed_out','not_run')){throw 'Historical agy token-storage check status differs.'}
    if($fileCheck -ceq 'ok'){
        if($present -isnot [bool]){throw 'Historical agy file-token presence must be a JSON boolean.'}
        if($present -and (-not (Test-AgyHistoryInteger $bytes 0 1073741824) -or $regular -isnot [bool])){throw 'Historical agy file-token size or kind differs.'}
        if(-not $present -and ($null -ne $bytes -or $null -ne $regular)){throw 'Historical agy absent file token carries a size.'}
    }elseif($null -ne $present -or $null -ne $bytes -or $null -ne $regular){throw 'Historical agy unverified file-token check carries values.'}
    if($credentialCheck -ceq 'ok'){
        if($entry -isnot [bool] -or -not (Test-AgyHistoryInteger $matching 0 4096) -or $entry -ne ($matching -gt 0)){throw 'Historical agy credential-name observation differs.'}
    }elseif($null -ne $entry -or $null -ne $matching){throw 'Historical agy unverified credential check carries values.'}
    [pscustomobject]@{file_check=$fileCheck;file_token_present=$present;credential_manager_check=$credentialCheck;credential_manager_entry_present=$entry}
}

function Assert-AgyHistoryReceipt {
    param($Receipt,$Task,[string]$Slot,[string]$Nonce,[string]$LoginMode,$Runtime,[string]$ExpectedSid)
    try{
        $pins=Get-AgyHistoryPins
        $allowed=@('schema','slot','nonce','login_mode','native_arguments','system_sid','helper_sha256','support_sha256','status','cleanup_verified',
            'one_line_submitted','input_file_deleted','operator_cancelled','terminated_after_input','login_commands_executed','model_jobs_executed',
            'authentication_verified','activation_ready','secret_published','native_output_after_input_published','native_output_bytes_before_input',
            'native_output_bound_reached_after_input','pause_marker_seen','native_markers','token_storage_observed',
            'started_at_unix_ms','finished_at_unix_ms','revision','runtime_root','install_receipt_sha256','source_manifest_sha256','resource_limits_sha256',
            'layout_sha256','config_sha256','native_executable_sha256','native_executable_sha256_after','process','native_exit_code','login_failure','failure',
            'input_closed_marker_written','native_output_published_bytes_before_input','native_output_bound_reached_before_input')
        $required=@('schema','slot','nonce','login_mode','native_arguments','system_sid','helper_sha256','support_sha256','status','cleanup_verified',
            'one_line_submitted','input_file_deleted','operator_cancelled','terminated_after_input','login_commands_executed','model_jobs_executed',
            'authentication_verified','activation_ready','secret_published','native_output_after_input_published','native_output_bytes_before_input',
            'native_output_bound_reached_after_input','pause_marker_seen','native_markers','token_storage_observed',
            'started_at_unix_ms','finished_at_unix_ms','revision','runtime_root','install_receipt_sha256','source_manifest_sha256','resource_limits_sha256',
            'layout_sha256','config_sha256','input_closed_marker_written','native_output_published_bytes_before_input','native_output_bound_reached_before_input')
        if($Receipt -isnot [Management.Automation.PSCustomObject]){throw 'Historical agy receipt must be one JSON object.'}
        $names=@($Receipt.PSObject.Properties|ForEach-Object{$_.Name})
        if(@($names|Where-Object{$_ -cnotin $allowed}).Count -or @($required|Where-Object{$_ -cnotin $names}).Count){throw 'Historical agy receipt fields differ from the pinned producer.'}
        if($Slot -cnotmatch '\Aslot[1-6]\z' -or $Nonce -cnotmatch '\A[a-f0-9]{32}\z' -or $Nonce -ceq ('0'*32) -or $LoginMode -cnotin @('print','tui') -or
           $ExpectedSid -cnotmatch '\AS-1-5-21-[0-9]+-[0-9]+-[0-9]+-[0-9]+\z'){throw 'Historical agy selected worker binding is invalid.'}
        $taskArguments=[string]$Task.Definition.Actions.Item(1).Arguments
        if(-not $taskArguments.EndsWith(('" --slot '+$Slot+' --nonce '+$Nonce+' --login-mode '+$LoginMode),[StringComparison]::Ordinal)){throw 'Historical agy task action differs from the receipt binding.'}
        if((Get-AgyHistoryValue $Runtime 'install_receipt_sha256') -cne $pins.install -or (Get-AgyHistoryValue $Runtime 'source_manifest_sha256') -cne $pins.manifest -or
           (Get-AgyHistoryValue $Runtime 'configuration_sha256') -cne $pins.config -or (Get-AgyHistoryValue (Get-AgyHistoryValue $Runtime 'revision') 'source_sha256') -cne $pins.revision){
            throw 'Historical agy review requires the exact current r4 runtime.'
        }
        foreach($pair in @(
            @('schema','cochem-interactive-agy-login/1'),@('slot',$Slot),@('nonce',$Nonce),@('login_mode',$LoginMode),@('system_sid','S-1-5-18'),
            @('helper_sha256',$pins.bridge),@('support_sha256',$pins.support),@('runtime_root',$pins.runtime_root),
            @('install_receipt_sha256',$pins.install),@('source_manifest_sha256',$pins.manifest),@('config_sha256',$pins.config),
            @('resource_limits_sha256',$pins.resource),@('layout_sha256',$pins.layout_sha256),@('status',$null))){
            $value=$Receipt.PSObject.Properties[$pair[0]].Value
            if($value -isnot [string] -or ($null -ne $pair[1] -and $value -cne $pair[1])){throw 'Historical agy receipt fixed identity or runtime binding differs.'}
        }
        $arguments=$Receipt.PSObject.Properties['native_arguments'].Value
        $expectedArguments=@();if($LoginMode -ceq 'print'){$expectedArguments=@('-p','/model')}
        if($arguments -isnot [Array] -or $arguments.Count -ne $expectedArguments.Count){throw 'Historical agy receipt argv differs from its login mode.'}
        for($index=0;$index -lt $expectedArguments.Count;$index++){if($arguments[$index] -isnot [string] -or $arguments[$index] -cne $expectedArguments[$index]){throw 'Historical agy receipt argv differs from its login mode.'}}
        $revision=$Receipt.PSObject.Properties['revision'].Value
        if($revision -isnot [Management.Automation.PSCustomObject] -or (Get-AgyHistoryValue $revision 'schema') -cne 'cochem-installed-revision/1' -or
           (Get-AgyHistoryValue $revision 'source_sha256') -cne $pins.revision -or -not (Test-AgyHistoryInteger (Get-AgyHistoryValue $revision 'files') 109 109) -or
           -not (Test-AgyHistoryInteger (Get-AgyHistoryValue $revision 'acceptance_files') 0 0) -or $null -ne (Get-AgyHistoryValue $revision 'acceptance_sha256')){throw 'Historical agy receipt revision differs.'}
        foreach($name in @('verified','read_only')){$flag=Get-AgyHistoryValue $revision $name;if($flag -isnot [bool] -or -not $flag){throw 'Historical agy revision verification flag differs.'}}
        foreach($name in @('cleanup_verified','one_line_submitted','input_file_deleted','operator_cancelled','terminated_after_input','authentication_verified',
            'activation_ready','secret_published','native_output_after_input_published','native_output_bound_reached_after_input','pause_marker_seen',
            'input_closed_marker_written','native_output_bound_reached_before_input')){
            if($Receipt.PSObject.Properties[$name].Value -isnot [bool]){throw 'Historical agy receipt flag must be a JSON boolean.'}
        }
        foreach($name in @('authentication_verified','activation_ready','secret_published','native_output_after_input_published')){
            if($Receipt.PSObject.Properties[$name].Value){throw 'Historical agy receipt makes an unexpected authentication, activation or disclosure claim.'}
        }
        $logins=$Receipt.login_commands_executed;$models=$Receipt.model_jobs_executed;$started=$Receipt.started_at_unix_ms;$finished=$Receipt.finished_at_unix_ms
        # Raw pre-input bytes (redraw escapes included) are bounded by the bridge's login window; published display bytes by output_limit.
        if(-not (Test-AgyHistoryInteger $logins 0 1) -or -not (Test-AgyHistoryInteger $models 0 0) -or
           -not (Test-AgyHistoryInteger $Receipt.native_output_bytes_before_input 0 ([long]::MaxValue)) -or
           -not (Test-AgyHistoryInteger $Receipt.native_output_published_bytes_before_input 0 $pins.output_limit) -or
           -not (Test-AgyHistoryInteger $started 1 ([long]::MaxValue)) -or -not (Test-AgyHistoryInteger $finished $started ([long]::MaxValue))){throw 'Historical agy receipt counts or terminal timestamps differ.'}
        $storage=Assert-AgyHistoryTokenStorage $Receipt.token_storage_observed
        $status=$Receipt.status;$cleanup=$Receipt.cleanup_verified;$submitted=$Receipt.one_line_submitted;$deleted=$Receipt.input_file_deleted
        $cancelled=$Receipt.operator_cancelled;$terminated=$Receipt.terminated_after_input
        $closedMarker=$Receipt.input_closed_marker_written;$boundReached=$Receipt.native_output_bound_reached_before_input
        $markers=$Receipt.native_markers;$markerProof=$null
        if($null -ne $markers){$markerProof=Assert-AgyHistoryMarkers $markers}
        $pause=if($null -ne $markerProof){$markerProof.pause_marker_seen}else{$false}
        if($Receipt.pause_marker_seen -ne $pause){throw 'Historical agy pause flag contradicts its markers.'}
        $failure=if(Test-AgyHistoryProperty $Receipt 'failure'){$Receipt.failure}else{$null}
        $loginFailure=if(Test-AgyHistoryProperty $Receipt 'login_failure'){$Receipt.login_failure}else{$null}
        $process=if(Test-AgyHistoryProperty $Receipt 'process'){$Receipt.process}else{$null}
        $nativeExitPresent=Test-AgyHistoryProperty $Receipt 'native_exit_code'
        $nativeCode=if($nativeExitPresent){$Receipt.native_exit_code}else{$null}
        $before=if(Test-AgyHistoryProperty $Receipt 'native_executable_sha256'){$Receipt.native_executable_sha256}else{$null}
        $afterPresent=Test-AgyHistoryProperty $Receipt 'native_executable_sha256_after'
        $after=if($afterPresent){$Receipt.native_executable_sha256_after}else{$null}
        $failureMarkers=@();if($null -ne $markerProof){$failureMarkers=@($markerProof.failure_markers)}
        $proof=[ordered]@{classification=$null;status=$status;accepted=$false;login_mode=$LoginMode;pause_marker_seen=$pause;failure_markers=$failureMarkers;
            login_commands_executed=$logins;model_jobs_executed=0;cleanup_verified=$cleanup;native_exit_code=$nativeCode;one_line_submitted=$submitted;
            terminated_after_input=$terminated;operator_cancelled=$cancelled;file_token_present=$storage.file_token_present;
            credential_manager_entry_present=$storage.credential_manager_entry_present;authentication_authorized_by_history=$false}
        # Class A: the native login command ran and ended (exit, failure exit or post-input termination) with verified cleanup.
        if($logins -eq 1 -and $cleanup -and $status -cin @('LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED','LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED','LOGIN_COMMAND_FAILED') -and $null -eq $failure){
            if(-not (Test-AgyHistoryInteger $nativeCode 0 4294967295) -or $null -eq $markerProof -or $before -cne $pins.agy -or $after -cne $pins.agy -or
               -not $closedMarker -or $boundReached){throw 'Historical agy native result evidence is incomplete.'}
            if($status -ceq 'LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED' -and ($nativeCode -ne 0 -or $terminated -or $Task.LastTaskResult -ne 0 -or $null -ne $loginFailure)){throw 'Historical agy native and task terminal results disagree.'}
            if($status -ceq 'LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED' -and (-not $submitted -or -not $terminated -or $Task.LastTaskResult -ne 0 -or $null -ne $loginFailure)){throw 'Historical agy post-input termination evidence differs.'}
            if($status -ceq 'LOGIN_COMMAND_FAILED'){
                $expectedPhase=if($submitted){'native_result'}else{'native_wait'}
                if($nativeCode -eq 0 -or $terminated -or $Task.LastTaskResult -ne 2 -or $loginFailure -isnot [Management.Automation.PSCustomObject] -or
                   @($loginFailure.PSObject.Properties).Count -ne 3 -or (Get-AgyHistoryValue $loginFailure 'phase') -cne $expectedPhase -or
                   (Get-AgyHistoryValue $loginFailure 'error_type') -cne 'NativeLoginExitNonZero' -or $null -ne (Get-AgyHistoryValue $loginFailure 'winerror')){throw 'Historical agy failed native exit evidence differs.'}
            }
            Assert-AgyHistoryProcess $process $ExpectedSid
            if($cancelled -or ($submitted -ne $deleted)){throw 'Historical agy consumed input or cancellation state differs.'}
            $proof.classification='TERMINAL_NATIVE_LOGIN_CLEANUP_VERIFIED'
            $proof.accepted=($status -cin @('LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED','LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED'))
            return [pscustomobject]$proof
        }
        # Class B: cancellation, the pre-input deadline or the sanitized pre-input output bound after launch; the receipt
        # follows owned Job/profile cleanup, reader termination, daemon postcheck and consumed-channel deletion.
        # native_exit_code is absent, not null.
        if($logins -eq 1 -and $cleanup -and $status -ceq 'LOGIN_FAILED_OR_CANCELLED' -and (Test-AgyHistoryInteger $Task.LastTaskResult 2 2) -and
           -not $nativeExitPresent -and $null -ne $failure -and $null -eq $loginFailure -and -not $afterPresent){
            if($failure -isnot [Management.Automation.PSCustomObject] -or @($failure.PSObject.Properties).Count -ne 3 -or
               (Get-AgyHistoryValue $failure 'phase') -cne 'native_wait' -or (Get-AgyHistoryValue $failure 'error_type') -cnotin @('InterruptedError','TimeoutError','NativeOutputBoundError') -or
               $null -ne (Get-AgyHistoryValue $failure 'winerror')){throw 'Historical agy cancellation, deadline or output-bound failure metadata differs.'}
            if($null -eq $markerProof -or $before -cne $pins.agy -or $storage.file_check -cne 'not_run' -or $storage.credential_manager_check -cne 'not_run' -or $terminated -or
               -not $closedMarker){throw 'Historical agy cancelled session evidence is incomplete.'}
            Assert-AgyHistoryProcess $process $ExpectedSid
            $errorType=Get-AgyHistoryValue $failure 'error_type'
            if($errorType -ceq 'NativeOutputBoundError'){
                # The bridge stopped before any input was read: display text exceeded its published bound.
                if(-not $boundReached -or $cancelled -or $submitted -or $deleted){throw 'Historical agy output-bound stop evidence differs.'}
                $proof.classification='TERMINAL_OUTPUT_BOUND_NATIVE_LOGIN_CLEANUP_VERIFIED'
            }elseif($boundReached){throw 'Historical agy output-bound flag contradicts its failure type.'}
            elseif($errorType -ceq 'InterruptedError'){
                if(-not $cancelled -or -not $deleted){throw 'Historical agy cancellation lacks consumed-channel cleanup proof.'}
                $proof.classification='TERMINAL_CANCELLED_NATIVE_LOGIN_CLEANUP_VERIFIED'
            }else{
                if($cancelled -or $submitted -or $deleted){throw 'Historical agy deadline interaction and channel cleanup differ.'}
                $proof.classification='TERMINAL_TIMED_OUT_NATIVE_LOGIN_CLEANUP_VERIFIED'
            }
            return [pscustomobject]$proof
        }
        # Class C: native_custody failure after full bindings and before launch_worker was called (no child).
        if($logins -eq 0 -and -not $cleanup -and $status -ceq 'LOGIN_FAILED_OR_CANCELLED' -and $Task.LastTaskResult -eq 2 -and
           $null -eq $process -and -not $nativeExitPresent -and $null -eq $loginFailure -and -not $afterPresent -and $null -eq $markers -and $null -ne $failure -and
           $failure -is [Management.Automation.PSCustomObject] -and (Get-AgyHistoryValue $failure 'phase') -ceq 'native_custody' -and
           (Get-AgyHistoryValue $failure 'error_type') -is [string] -and (Get-AgyHistoryValue $failure 'error_type') -cmatch '\A[A-Za-z][A-Za-z0-9_]{0,79}\z'){
            $code=Get-AgyHistoryValue $failure 'winerror'
            if($null -ne $code -and -not (Test-AgyHistoryInteger $code 0 4294967295)){throw 'Historical agy prelaunch failure metadata differs.'}
            if($null -ne $before -and $before -cne $pins.agy){throw 'Historical agy prelaunch executable binding differs.'}
            if($submitted -or $deleted -or $cancelled -or $terminated -or $pause -or $storage.file_check -cne 'not_run' -or $storage.credential_manager_check -cne 'not_run' -or
               $closedMarker -or $boundReached -or $Receipt.native_output_published_bytes_before_input -ne 0){throw 'Historical agy prelaunch evidence contains an inconsistent interaction flag.'}
            $proof.classification='TERMINAL_PRE_NATIVE_CUSTODY_FAILURE_NO_CHILD_LAUNCHED'
            return [pscustomobject]$proof
        }
        throw 'Historical agy receipt does not prove terminal native cleanup or a reviewed failure before launch.'
    }catch{
        $errorValue=[InvalidOperationException]::new('Historical agy receipt requires diagnosis; preserve all evidence and do not retry login automatically.')
        $errorValue.Data['CoChemAgyHistorySafeMetadata']=Get-AgyHistorySafeReceiptMetadata $Receipt
        throw $errorValue
    }
}

function Get-AgyHistoryExpectedSid {
    param([string]$Slot)
    $pins=Get-AgyHistoryPins
    $layout=(Read-R3Text (Read-R3Control $pins.layout $pins.layout_sha256 1048576))|ConvertFrom-Json
    $sid=Get-AgyHistoryValue (Get-AgyHistoryValue (Get-AgyHistoryValue $layout 'slots') $Slot) 'sid'
    if($sid -isnot [string] -or $sid -cnotmatch '\AS-1-5-21-[0-9]+-[0-9]+-[0-9]+-[0-9]+\z'){throw 'Installed r4 layout SID for the selected worker is invalid.'}
    return $sid
}

function Get-AgyHistorySessionRecord {
    param([string]$Root,[string]$Name)
    # Optional wrapper record (session-result.json or session-held.json): presence and digest only.
    $path=Join-Path $Root $Name
    if(-not (Test-Path -LiteralPath $path)){return [pscustomobject]@{present=$false;sha256=$null}}
    Assert-AgyHistoryPrivateAcl (Get-Acl -LiteralPath $path -ErrorAction Stop)
    $control=Read-R3Control $path '' 65536
    return [pscustomobject]@{present=$true;sha256=$control.Sha256}
}

function Assert-ReviewedAgyHistory {
    param([Parameter(Mandatory=$true)][ValidateSet('slot1','slot2','slot3','slot4','slot5','slot6')][string]$Slot,[Parameter(Mandatory=$true)]$Folder,[Parameter(Mandatory=$true)]$Runtime)
    if($Slot -cnotmatch '\Aslot[1-6]\z'){throw 'Historical agy slot must use its exact lowercase spelling.'}
    $pins=Get-AgyHistoryPins;$parent=Get-AgyHistoryParent
    Assert-NoReparseAncestors $parent;Assert-ProtectedPath $parent
    $old=@(Get-ChildItem -LiteralPath $parent -Directory -Force -Filter "InteractiveAgy427-$Slot-*" -ErrorAction Stop)
    if($old.Count){throw 'An older non-r4 agy session remains outside this reviewed history; preserve it for diagnosis.'}
    $roots=@(Get-ChildItem -LiteralPath $parent -Directory -Force -Filter ($pins.root_prefix+$Slot+'-*') -ErrorAction Stop)
    if($roots.Count -gt 128){throw 'Historical agy session inventory exceeded its bound.'}
    $expectedTasks=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach($root in $roots){
        if($root.Name -cnotmatch ('\AInteractiveAgy427-r4-'+$Slot+'-([a-f0-9]{32})\z') -or $Matches[1] -ceq ('0'*32) -or $root.FullName -cne (Join-Path $parent $root.Name)){
            throw 'Historical agy session root name or selected slot differs.'
        }
        if(-not $expectedTasks.Add(($pins.task_prefix+$Slot+'-'+$Matches[1]))){throw 'Historical agy session inventory contains a duplicate.'}
    }
    $tasks=@($Folder.GetTasks(1));if($tasks.Count -gt 5000){throw 'Historical agy scheduler census exceeded its bound.'}
    foreach($candidate in $tasks){
        if($candidate.Name -like "CoChem-4.2.7-InteractiveAgy-$Slot-*" -or $candidate.Name -like "CoChem-4.2.7-InteractiveAgy-r4-$Slot-*"){
            if(-not $expectedTasks.Contains([string]$candidate.Name)){throw 'An agy login task has no matching reviewed session root; preserve it for diagnosis.'}
        }
    }
    if(-not $roots.Count){return}
    $expectedSid=Get-AgyHistoryExpectedSid $Slot
    $summaries=[Collections.Generic.List[object]]::new()
    foreach($root in $roots){
        $null=$root.Name -cmatch ('\AInteractiveAgy427-r4-'+$Slot+'-([a-f0-9]{32})\z');$nonce=$Matches[1]
        $taskName=$pins.task_prefix+$Slot+'-'+$nonce
        Assert-AgyHistoryPrivateRoot $root.FullName
        foreach($pair in @(@($pins.bridge_name,$pins.bridge),@($pins.support_name,$pins.support))){
            $path=Join-Path $root.FullName $pair[0]
            Assert-AgyHistoryPrivateAcl (Get-Acl -LiteralPath $path -ErrorAction Stop)
            $null=Read-R3Control $path $pair[1] 1048576
        }
        $task=Get-ExactTaskOrAbsent $Folder $taskName
        $mode=Assert-AgyHistoryTask $task $root.FullName $Slot $nonce
        $receiptPath=Join-Path $root.FullName 'receipt.json'
        # pathlib.open('x') creates this receipt with the inherited BA/SY-only ACL of the verified private root.
        Assert-AgyHistoryPrivateAcl (Get-Acl -LiteralPath $receiptPath -ErrorAction Stop) -AllowInherited
        $control=Read-R3Control $receiptPath '' 65536
        try{
            $receipt=(Read-R3Text $control)|ConvertFrom-Json
            $proof=Assert-AgyHistoryReceipt $receipt $task $Slot $nonce $mode $Runtime $expectedSid
        }catch{
            $errorValue=$_.Exception
            while($null -ne $errorValue){
                if($errorValue.Data.Contains('CoChemAgyHistorySafeMetadata')){
                    Write-Host ('COCHEM_AGY_HISTORY_HOLD '+($errorValue.Data['CoChemAgyHistorySafeMetadata']|ConvertTo-Json -Depth 4 -Compress));break
                }
                $errorValue=$errorValue.InnerException
            }
            throw 'Historical agy receipt is not sufficient for a fresh login; preserve every file and task for diagnosis.'
        }
        $result=Get-AgyHistorySessionRecord $root.FullName 'session-result.json'
        $heldRecord=Get-AgyHistorySessionRecord $root.FullName 'session-held.json'
        # Re-read exact scheduler state after taking immutable receipt/source handles. Nothing is changed.
        $null=Assert-AgyHistoryTask (Get-ExactTaskOrAbsent $Folder $taskName) $root.FullName $Slot $nonce
        $summaries.Add([pscustomobject]@{schema='cochem-reviewed-agy-session-history/1';slot=$Slot;nonce=$nonce;login_mode=$mode;root=$root.FullName;task_name=$taskName;
            receipt_path=$receiptPath;receipt_sha256=$control.Sha256;classification=$proof.classification;status=$proof.status;accepted_terminal_status=$proof.accepted;
            pause_marker_seen=$proof.pause_marker_seen;failure_markers=@($proof.failure_markers);login_commands_executed=$proof.login_commands_executed;cleanup_verified=$proof.cleanup_verified;
            session_result_present=$result.present;session_result_sha256=$result.sha256;session_held_present=$heldRecord.present;session_held_sha256=$heldRecord.sha256;
            prior_state_preserved=$true;authentication_authorized_by_history=$false;current_logged_out_status_required=$true;operator_ready_required=$true})
    }
    return $summaries.ToArray()
}
