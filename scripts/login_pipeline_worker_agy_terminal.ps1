#Requires -Version 5.1
<# Owner-only native terminal OAuth transport, one configured worker, no inference.
   The legacy bridge/custody helpers are imported as pinned definitions only.
   A fresh protected namespace preserves every earlier attempt. The absolute
   input deadline is inherited from the sitting; no late prompt or retry.
   Default prints an inert plan. Only the owner invokes Apply. #>
[CmdletBinding()]
param([ValidateSet('slot1','slot2','slot3','slot4','slot5','slot6')][string]$Slot,
      [string]$DeadlineUtc,[string]$LegacyWrapperSha256,[string]$PublicStatusRoot,[switch]$Apply)

function Import-AgyTerminalLegacy {
    param([string]$Directory,[string]$Expected)
    if($Expected -cne '381fb8daec6999d16e75ab163f28d0dda6459b1b44f9695962cf43213cedcb60'){throw 'The legacy custody wrapper binding differs.'}
    $path=Join-Path $Directory 'login_pipeline_worker_interactive_agy_r4_v1.ps1'
    $stream=[IO.File]::Open($path,'Open','Read','Read')
    try{
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$hash=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        if($hash -cne $Expected){throw 'The legacy custody wrapper changed.'}
        $stream.Position=0;$reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true,4096,$true)
        try{$text=$reader.ReadToEnd()}finally{$reader.Dispose()}
        $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
        if($errors.Count){throw 'The legacy custody wrapper does not parse.'}
        foreach($node in $ast.EndBlock.Statements){
            if($node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -cnotin @('Invoke-AgyLoginMain','Invoke-AgyLoginApply')){$node.Extent.Text}
        }
    }finally{$stream.Dispose()}
}

function Set-AgyTerminalConstants {
    param([string]$Directory)
    $script:terminalSource=Join-Path $Directory 'attended_agy_terminal.py'
    $script:terminalBridgeSource=Join-Path $Directory 'worker_agy_terminal_bridge.py'
    $script:terminalHash='bedff42652ca92031ef056ef9f21d584c502bc9f1227598b1098f83f808ebeda'
    $script:terminalBridgeHash='f7955a7d744ff2c6145eab989ae502f0346170f078a7490b5461abd54cdfce8f'
}

function Set-AgyTerminalNames {
    param([string]$Slot,[string]$Nonce)
    if($Slot -cnotmatch '^slot[1-6]$' -or $Nonce -cnotmatch '^[a-f0-9]{32}$' -or $Nonce -ceq ('0'*32)){throw 'Invalid terminal namespace.'}
    $script:sessionRoot=Join-Path $script:cochemRoot ('InteractiveAgyTerminal427-r4-'+$Slot+'-'+$Nonce)
    $script:taskName='CoChem-4.2.7-InteractiveAgyTerminal-r4-'+$Slot+'-'+$Nonce
}

function Get-AgyTerminalArguments {
    param([string]$Slot,[string]$Nonce)
    if($Slot -cnotmatch '^slot[1-6]$' -or $Nonce -cnotmatch '^[a-f0-9]{32}$' -or $Nonce -ceq ('0'*32)){throw 'Invalid terminal arguments.'}
    '-I -B "'+(Join-Path $script:sessionRoot 'worker_agy_terminal_bridge.py')+'" --slot '+$Slot+' --nonce '+$Nonce
}

function Assert-AgyTerminalReceiptIdentity {
    param($Receipt,[string]$Slot,[string]$Nonce)
    foreach($pair in @(@('schema','cochem-interactive-agy-terminal-login/1'),@('transport','CONPTY_MANUAL_GOOGLE'),
        @('slot',$Slot),@('nonce',$Nonce),@('login_mode','terminal'),@('system_sid','S-1-5-18'),
        @('helper_sha256',$script:terminalBridgeHash),@('terminal_module_sha256',$script:terminalHash),
        @('parent_bridge_sha256',$script:bridgeHash),@('support_sha256',$script:supportHash))){
        $property=$Receipt.PSObject.Properties[$pair[0]]
        if($null -eq $property -or $property.Value -isnot [string] -or $property.Value -cne $pair[1]){throw 'The terminal receipt identity or helper binding differs.'}
    }
}

function Assert-AgyTerminalReceipt {
    param($Receipt,[string]$Slot,[string]$Nonce)
    Assert-AgyTerminalReceiptIdentity $Receipt $Slot $Nonce
    foreach($name in @('cleanup_verified','terminal_cleanup_verified','one_line_submitted','code_write_completed','input_file_deleted','input_closed_marker_written')){
        $value=$Receipt.PSObject.Properties[$name].Value
        if($value -isnot [bool] -or -not $value){throw 'Terminal input or cleanup is incomplete.'}
    }
    foreach($name in @('secret_published','native_output_after_input_published','activation_ready','authentication_verified')){
        $value=$Receipt.PSObject.Properties[$name].Value
        if($value -isnot [bool] -or $value){throw 'The terminal receipt makes an unsupported disclosure or activation claim.'}
    }
    if($Receipt.status -cnotin @('LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED','LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED') -or
       $Receipt.login_commands_executed -isnot [long] -and $Receipt.login_commands_executed -isnot [int] -or
       $Receipt.login_commands_executed -ne 1 -or $Receipt.model_jobs_executed -ne 0 -or
       $Receipt.native_executable_sha256 -cne $script:agyHash -or $Receipt.native_executable_sha256_after -cne $script:agyHash){throw 'The terminal native result differs.'}
    $sid=Get-AgyHistoryExpectedSid $Slot
    if($Receipt.process.token_sid -cne $sid){throw 'The terminal child token differs from the selected worker.'}
    foreach($name in @('token_matches_selected_worker','image_matches_reviewed_executable','owned_job_membership_verified')){
        $value=$Receipt.process.PSObject.Properties[$name].Value
        if($value -isnot [bool] -or -not $value){throw 'The terminal child custody is incomplete.'}
    }
}

function Invoke-AgyTerminalKey {
    param($State,[ConsoleKeyInfo]$Key,[bool]$PromptReady)
    if(-not $PromptReady){
        if($Key.Key -eq [ConsoleKey]::Escape){$State.CancelRequested=$true}
        return  # Discard stale input, including Enter and old authorization codes.
    }
    Update-ClaudeCodeInput -State $State -Key $Key
}

function Get-AgyTerminalPublicProjection {
    param($Record)
    $safe=[ordered]@{schema='cochem-agy-terminal-public-status/1';slot=$Record.slot;nonce=$Record.nonce;
        status='HELD';cleanup_verified=$false;authentication_verified=$false;activation_ready=$false;automatic_retry=$false}
    if($safe.slot -cnotmatch '^slot[1-6]$' -or $safe.nonce -cnotmatch '^[a-f0-9]{32}$'){throw 'Invalid public session identity.'}
    $status=if($Record -is [Collections.IDictionary]){$Record['status']}else{
        $property=$Record.PSObject.Properties['status'];if($null -ne $property){$property.Value}else{$null}}
    if($status -ceq 'LOGIN_ENDED_STATUS_REQUIRED'){$safe.status='LOGIN_ENDED_STATUS_REQUIRED'}
    foreach($key in @('cleanup_verified','terminal_cleanup_verified')){
        $property=$Record.PSObject.Properties[$key]
        if($Record -is [Collections.IDictionary]){$value=$Record[$key]}else{$value=$(if($null -ne $property){$property.Value}else{$null})}
        if($value -is [bool]){$safe[$key]=$value}
    }
    foreach($key in @('phase','reason','error_type','receipt_sha256')){
        if($Record -is [Collections.IDictionary]){$value=$Record[$key]}else{
            $property=$Record.PSObject.Properties[$key];$value=$(if($null -ne $property){$property.Value}else{$null})}
        $allowed=switch ($key){
            'phase'{@('copy','register','run','console','receipt')}
            'reason'{@('TERMINAL_SIGN_IN_HELD','NO_NATIVE_STARTUP_OUTPUT','FRESH_GOOGLE_PROMPT_NOT_OBSERVED','OWNER_INPUT_WINDOW_EXPIRED')}
            'error_type'{@('RuntimeException','InvalidOperationException','IOException','TimeoutException','COMException','UnauthorizedAccessException')}
            default {@()}}
        if($value -is [string] -and ($value -cin $allowed -or ($key -ceq 'receipt_sha256' -and $value -cmatch '^[a-f0-9]{64}$'))){$safe[$key]=$value}
    }
    $safe
}

function Assert-AgyTerminalPublicRoot {
    param([string]$Root)
    if($Root -cnotmatch '^C:\\Program Files\\CoChem\\R6Sitting4\.2\.7-windows-20261012-[a-f0-9]{32}$'){throw 'Public status must use the current protected sitting namespace.'}
}

function Write-AgyTerminalPublicStatus {
    param($Record)
    if(-not $script:terminalPublicRoot){return}
    Assert-AgyTerminalPublicRoot $script:terminalPublicRoot;Assert-ProtectedPath $script:terminalPublicRoot
    $safe=Get-AgyTerminalPublicProjection $Record
    $acl=[Security.AccessControl.FileSecurity]::new();$acl.SetAccessRuleProtection($true,$false)
    $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
    foreach($sid in @('S-1-5-18','S-1-5-32-544')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','Allow'))}
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-5-32-545'),'Read','Allow'))
    $path=Join-Path $script:terminalPublicRoot ('status-agy-terminal-'+$Record.nonce+'.json')
    $bytes=[Text.UTF8Encoding]::new($false).GetBytes(($safe|ConvertTo-Json -Depth 4))
    $stream=[IO.FileStream]::new($path,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::Read,4096,[IO.FileOptions]::None,$acl)
    try{$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
}

function Wait-AgyTerminalCleanup {
    param($Instance,[string]$Root,[string]$Nonce)
    Write-CancelRequest $Root $Nonce
    $until=[DateTime]::UtcNow.AddSeconds(45)
    while(-not (Test-InstanceComplete $Instance) -and [DateTime]::UtcNow -lt $until){Start-Sleep -Milliseconds 100}
    if(-not (Test-InstanceComplete $Instance)){throw 'Terminal cleanup has not completed; preserve the running session. No automatic retry.'}
}

function Invoke-AgyTerminalConsoleLoop {
    param($Instance,[string]$Root,[string]$Nonce,[DateTime]$Deadline)
    $log=Join-Path $Root 'operator.log';$closed=Join-Path $Root 'input.closed';$seen=0;$ready=$false;$cancel=$false
    $state=New-ClaudeCodeInput
    try{
        while(-not (Test-InstanceComplete $Instance)){
            if([DateTime]::UtcNow -ge $Deadline -and -not $cancel){
                $cancel=$true;Wait-AgyTerminalCleanup $Instance $Root $Nonce
                throw 'The owner-input deadline expired; no further code is accepted.'
            }
            $windowClosed=Test-Path -LiteralPath $closed
            if(-not $ready -and -not $state.Submitted -and -not $cancel -and (Test-Path -LiteralPath $log)){
                $text=Read-AgyOperatorLog $log;$at=Find-AgyCodePrompt $text
                $end=if($at -ge 0){$at}else{$text.Length-(Get-AgyPromptPrefixHold $text)}
                if($end -gt $seen){Write-AgyConsoleText ($text.Substring($seen,$end-$seen));$seen=$end}
                if($at -ge 0 -and -not $windowClosed){
                    $seen=$text.Length;$ready=$true;Write-Host ''
                    Write-Host 'Use only the fresh Google URL above. Paste the returned code below, then press Enter.'
                    [Console]::Write('Code (masked; Escape cancels): ')
                }
            }
            $count=0
            while($count -lt 256 -and (Test-AgyConsoleKeyAvailable)){
                $key=Read-AgyConsoleKey;$count++
                if($windowClosed -or $state.Closed -or $state.Submitted){continue}
                Invoke-AgyTerminalKey $state $key $ready
                if($state.CancelRequested -or $state.SubmissionRequested){break}
            }
            $key=$null
            if($state.CancelRequested -and -not $cancel){
                $cancel=$true;Write-Host '';Write-Host 'Cancellation requested; waiting for owned cleanup.'
                Wait-AgyTerminalCleanup $Instance $Root $Nonce
            }elseif($state.SubmissionRequested -and -not $state.Submitted -and $ready -and -not $cancel){
                if(-not (Test-Path -LiteralPath $closed) -and -not (Test-InstanceComplete $Instance) -and [DateTime]::UtcNow -lt $Deadline){
                    Write-PrivatePacket (Join-Path $Root 'input.once') $Nonce $state.Secret
                    Complete-ClaudeCodeInput -State $state
                    Write-Host '';Write-Host 'Code submitted privately. Waiting for native completion and cleanup; the next status check decides authentication.'
                }
            }
            Start-Sleep -Milliseconds 100
        }
    }catch{
        if(-not (Test-InstanceComplete $Instance)){Wait-AgyTerminalCleanup $Instance $Root $Nonce}
        throw
    }finally{
        Close-ClaudeCodeInput -State $state
        $drain=Clear-ClaudeConsoleInput
        if($drain.console_queue_clear -isnot [bool] -or -not $drain.console_queue_clear){throw 'Console clearing exceeded its bound; preserve the session.'}
    }
    [pscustomobject]@{native_prompt_seen=$ready;one_line_submitted=[bool]$state.Submitted;cancel_requested=$cancel}
}

function Assert-AgyTerminalTask {
    param($Task,[string]$Slot,[string]$Nonce)
    Assert-RegisteredTaskAcl ([string]$Task.GetSecurityDescriptor(7))
    $d=$Task.Definition;$a=$d.Actions.Item(1)
    if($Task.Name -cne $script:taskName -or $d.Principal.UserId -cnotin @('SYSTEM','S-1-5-18') -or
       $d.Principal.LogonType -ne 5 -or $d.Principal.RunLevel -ne 1 -or $d.Triggers.Count -ne 0 -or $d.Actions.Count -ne 1 -or
       $a.Type -ne 0 -or $a.Path -cne $script:python -or $a.Arguments -cne (Get-AgyTerminalArguments $Slot $Nonce) -or
       $a.WorkingDirectory -cne $script:sessionRoot -or $d.Settings.MultipleInstances -ne 2 -or $d.Settings.RestartCount -ne 0 -or
       $d.Settings.ExecutionTimeLimit -cne 'PT15M' -or $d.Settings.Enabled -ne $true -or $d.Settings.AllowDemandStart -ne $true){throw 'The new terminal task definition differs.'}
}

function Copy-AgyTerminalSources {
    Copy-AgySessionSources  # Exact pinned legacy parent and support, CreateNew private files.
    foreach($row in @(@($script:terminalSource,'attended_agy_terminal.py',$script:terminalHash),
                     @($script:terminalBridgeSource,'worker_agy_terminal_bridge.py',$script:terminalBridgeHash))){
        $length=(Get-Item -LiteralPath $row[0]).Length;$path=Join-Path $script:sessionRoot $row[1]
        $inputStream=Open-VerifiedFile $row[0] $row[2] $length
        try{
            $outputStream=[IO.FileStream]::new($path,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,4096,[IO.FileOptions]::None,(New-PrivateAcl))
            try{$inputStream.CopyTo($outputStream);$outputStream.Flush($true)}finally{$outputStream.Dispose()}
        }finally{$inputStream.Dispose()}
        $held.Add((Open-VerifiedFile $path $row[2] $length))
    }
}

function Invoke-AgyTerminalApply {
    param($Scheduler,$Folder,$Runtime,[string]$Slot,[DateTime]$Deadline)
    $null=Assert-CodeTreeOnce $script:installRoot;$null=Assert-CodeTreeOnce $script:basePythonRoot;$null=Assert-CodeTreeOnce $script:nativeRoot
    $null=@(Assert-ReviewedAgyHistory -Slot $Slot -Folder $Folder -Runtime $Runtime)
    $previous=@(Get-ChildItem -LiteralPath $script:cochemRoot -Directory -Filter ('InteractiveAgyTerminal427-r4-'+$Slot+'-*'))
    $previousTasks=@($Folder.GetTasks(1)|Where-Object {$_.Name -clike ('CoChem-4.2.7-InteractiveAgyTerminal-r4-'+$Slot+'-*')})
    if($previous.Count -or $previousTasks.Count){throw 'An earlier terminal attempt needs review; no automatic repeat.'}
    if([DateTime]::UtcNow -ge $Deadline.AddSeconds(-30)){throw 'The owner-input window has closed.'}
    $nonce=New-AgyLoginNonce;Set-AgyTerminalNames $Slot $nonce
    if((Test-Path -LiteralPath $script:sessionRoot) -or $null -ne (Get-ExactTaskOrAbsent $Folder $script:taskName)){throw 'Fresh terminal namespace is not empty.'}
    Assert-ProtectedPath $script:cochemRoot
    $null=[IO.Directory]::CreateDirectory($script:sessionRoot,(New-PrivateAcl -Directory))
    $phase='copy';$task=$null;$runRequested=$false;$receipt=$null;$receiptControl=$null
    try{
        Copy-AgyTerminalSources
        $phase='register';$arguments=Get-AgyTerminalArguments $Slot $nonce
        $task=$Folder.RegisterTaskDefinition($script:taskName,(New-AgyLoginTaskDefinition $Scheduler $arguments),18,'SYSTEM',$null,5,$script:taskSddl)
        Assert-AgyTerminalTask $task $Slot $nonce
        $phase='run';Write-Host ('Fresh Gemini terminal sign-in for '+$Slot+'. Waiting for its Google URL; keys are ignored until the fresh code prompt.')
        $instance=$task.Run($null);$runRequested=$true
        $phase='console';$loop=Invoke-AgyTerminalConsoleLoop $instance $script:sessionRoot $nonce $Deadline
        $phase='receipt';Assert-TaskTerminal $task
        $receiptControl=Read-R3Control (Join-Path $script:sessionRoot 'receipt.json') '' $script:receiptLimit
        $receipt=(Read-R3Text $receiptControl)|ConvertFrom-Json
        Assert-AgyTerminalReceiptIdentity $receipt $Slot $nonce
        $proof=Assert-AgyTerminalFullReceipt $receipt $task $Slot $nonce 'terminal' $Runtime (Get-AgyHistoryExpectedSid $Slot)
        Assert-AgyTerminalReceipt $receipt $Slot $nonce
        if(-not $proof.accepted -or $proof.pause_marker_seen){throw 'Native sign-in did not complete or requires provider review.'}
        $result=[ordered]@{schema='cochem-interactive-agy-terminal-result/1';slot=$Slot;nonce=$nonce;status='LOGIN_ENDED_STATUS_REQUIRED';
            receipt_sha256=$receiptControl.Sha256;receipt_path=(Join-Path $script:sessionRoot 'receipt.json');
            task_name=$script:taskName;cleanup_verified=$true;terminal_cleanup_verified=$true;authentication_verified=$false;
            login_commands_executed=1;model_jobs_executed=0;automatic_retry=$false;activation_ready=$false}
        $null=Write-AgySessionRecord (Join-Path $script:sessionRoot 'session-result.json') $result
        Write-AgyTerminalPublicStatus $result
        Write-AgyLoginJson $result
    }catch{
        # Publish only bounded enums/pins, never exception text or raw provider output.
        $kind=$_.Exception.GetType().Name;$reason='TERMINAL_SIGN_IN_HELD';$clean=$false
        if($null -ne $receipt){
            try{Assert-AgyTerminalReceiptIdentity $receipt $Slot $nonce
                $clean=($receipt.cleanup_verified -is [bool] -and $receipt.cleanup_verified -and $receipt.terminal_cleanup_verified -is [bool] -and $receipt.terminal_cleanup_verified)
                if($receipt.terminal_hold_reason -cin @('NO_NATIVE_STARTUP_OUTPUT','FRESH_GOOGLE_PROMPT_NOT_OBSERVED','OWNER_INPUT_WINDOW_EXPIRED')){$reason=$receipt.terminal_hold_reason}
            }catch{}
        }
        $heldRecord=[ordered]@{schema='cochem-interactive-agy-terminal-held/1';status='HELD';slot=$Slot;nonce=$nonce;phase=$phase;
            reason=$reason;error_type=$kind;task_name=$script:taskName;run_requested=$runRequested;cleanup_verified=$clean;
            receipt_sha256=$(if($null -ne $receiptControl){$receiptControl.Sha256}else{$null});
            raw_provider_output_recorded=$false;code_recorded=$false;automatic_retry=$false;activation_ready=$false}
        $null=Write-AgySessionRecord (Join-Path $script:sessionRoot 'session-held.json') $heldRecord
        Write-AgyTerminalPublicStatus $heldRecord
        Write-AgyLoginJson $heldRecord
        throw ('Gemini terminal sign-in held: '+$reason+'. Preserve the task and session. No automatic repeat.')
    }
}

# The complete pinned legacy receipt classifier, with only the explicitly
# versioned terminal schema/helper/argv additions below. Old evidence is unchanged.
function Assert-AgyTerminalFullReceipt {
    param($Receipt,$Task,[string]$Slot,[string]$Nonce,[string]$LoginMode,$Runtime,[string]$ExpectedSid)
    try{
        Assert-AgyTerminalReceiptIdentity $Receipt $Slot $Nonce
        foreach($name in @('terminal_cleanup_verified','code_write_completed','native_google_start_key_sent')){
            if($Receipt.PSObject.Properties[$name].Value -isnot [bool]){throw 'Terminal receipt flags are not JSON booleans.'}
        }
        if(-not (Test-AgyHistoryInteger $Receipt.terminal_query_replies 0 128) -or
            $Receipt.terminal_hold_reason -cnotin @($null,'NO_NATIVE_STARTUP_OUTPUT','FRESH_GOOGLE_PROMPT_NOT_OBSERVED','OWNER_INPUT_WINDOW_EXPIRED') -or
            $Receipt.cleanup_verified -ne $Receipt.terminal_cleanup_verified -or
            $Receipt.one_line_submitted -and -not $Receipt.code_write_completed){throw 'Terminal cleanup, protocol or code-write proof differs.'}
        $pins=Get-AgyHistoryPins
        $allowed=@('transport','parent_bridge_sha256','terminal_module_sha256','terminal_cleanup_verified','code_write_completed','native_google_start_key_sent','terminal_query_replies','terminal_hold_reason','schema','slot','nonce','login_mode','native_arguments','system_sid','helper_sha256','support_sha256','status','cleanup_verified',
            'one_line_submitted','input_file_deleted','operator_cancelled','terminated_after_input','login_commands_executed','model_jobs_executed',
            'authentication_verified','activation_ready','secret_published','native_output_after_input_published','native_output_bytes_before_input',
            'native_output_bound_reached_after_input','pause_marker_seen','native_markers','token_storage_observed',
            'started_at_unix_ms','finished_at_unix_ms','revision','runtime_root','install_receipt_sha256','source_manifest_sha256','resource_limits_sha256',
            'layout_sha256','config_sha256','native_executable_sha256','native_executable_sha256_after','process','native_exit_code','login_failure','failure',
            'input_closed_marker_written','native_output_published_bytes_before_input','native_output_bound_reached_before_input')
        $required=@('transport','parent_bridge_sha256','terminal_module_sha256','terminal_cleanup_verified','code_write_completed','native_google_start_key_sent','terminal_query_replies','terminal_hold_reason','schema','slot','nonce','login_mode','native_arguments','system_sid','helper_sha256','support_sha256','status','cleanup_verified',
            'one_line_submitted','input_file_deleted','operator_cancelled','terminated_after_input','login_commands_executed','model_jobs_executed',
            'authentication_verified','activation_ready','secret_published','native_output_after_input_published','native_output_bytes_before_input',
            'native_output_bound_reached_after_input','pause_marker_seen','native_markers','token_storage_observed',
            'started_at_unix_ms','finished_at_unix_ms','revision','runtime_root','install_receipt_sha256','source_manifest_sha256','resource_limits_sha256',
            'layout_sha256','config_sha256','input_closed_marker_written','native_output_published_bytes_before_input','native_output_bound_reached_before_input')
        if($Receipt -isnot [Management.Automation.PSCustomObject]){throw 'Historical agy receipt must be one JSON object.'}
        $names=@($Receipt.PSObject.Properties|ForEach-Object{$_.Name})
        if(@($names|Where-Object{$_ -cnotin $allowed}).Count -or @($required|Where-Object{$_ -cnotin $names}).Count){throw 'Historical agy receipt fields differ from the pinned producer.'}
        if($Slot -cnotmatch '\Aslot[1-6]\z' -or $Nonce -cnotmatch '\A[a-f0-9]{32}\z' -or $Nonce -ceq ('0'*32) -or $LoginMode -cne 'terminal' -or
           $ExpectedSid -cnotmatch '\AS-1-5-21-[0-9]+-[0-9]+-[0-9]+-[0-9]+\z'){throw 'Historical agy selected worker binding is invalid.'}
        $taskArguments=[string]$Task.Definition.Actions.Item(1).Arguments
        if(-not $taskArguments.EndsWith(('" --slot '+$Slot+' --nonce '+$Nonce+''),[StringComparison]::Ordinal)){throw 'Historical agy task action differs from the receipt binding.'}
        if((Get-AgyHistoryValue $Runtime 'install_receipt_sha256') -cne $pins.install -or (Get-AgyHistoryValue $Runtime 'source_manifest_sha256') -cne $pins.manifest -or
           (Get-AgyHistoryValue $Runtime 'configuration_sha256') -cne $pins.config -or (Get-AgyHistoryValue (Get-AgyHistoryValue $Runtime 'revision') 'source_sha256') -cne $pins.revision){
            throw 'Historical agy review requires the exact current r4 runtime.'
        }
        foreach($pair in @(
            @('schema','cochem-interactive-agy-terminal-login/1'),@('slot',$Slot),@('nonce',$Nonce),@('login_mode',$LoginMode),@('system_sid','S-1-5-18'),
            @('helper_sha256',$script:terminalBridgeHash),@('support_sha256',$pins.support),@('runtime_root',$pins.runtime_root),
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

function Invoke-AgyTerminalMain {
    param([string]$Slot,[string]$DeadlineText,[string]$LegacyHash,[bool]$ApplyRequested,[string]$Directory,[string]$PublicRoot='')
    $ErrorActionPreference='Stop';Set-StrictMode -Version Latest
    if($Slot -cnotmatch '^slot[1-6]$'){throw 'Only a configured worker slot is accepted.'}
    if(-not $ApplyRequested){
        [ordered]@{schema='cochem-agy-terminal-plan/1';slot=$Slot;transport='CONPTY_MANUAL_GOOGLE';
            tasks_changed=0;provider_commands_executed=0;model_jobs_executed=0;activation_ready=$false;
            startup_output_seconds=30;fresh_prompt_seconds=60;maximum_input_lines=1;late_prompts=$false}|ConvertTo-Json -Compress
        return
    }
    $deadline=[DateTime]::ParseExact($DeadlineText,'o',[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()
    if($deadline -le [DateTime]::UtcNow.AddSeconds(30) -or $deadline -gt [DateTime]::UtcNow.AddMinutes(20)){throw 'The absolute owner-input window is closed or invalid.'}
    if($PublicRoot){Assert-AgyTerminalPublicRoot $PublicRoot};$script:terminalPublicRoot=$PublicRoot
    foreach($definition in @(Import-AgyTerminalLegacy $Directory $LegacyHash)){. ([scriptblock]::Create($definition))}
    Assert-AgyLoginHost $true $true
    Set-AgyLoginConstants $Slot 'tui' $Directory;Set-AgyTerminalConstants $Directory
    foreach($definition in @(Get-AgyLoginHelperDefinitions)){. ([scriptblock]::Create($definition))}
    Initialize-FileIdentity
    $held=[Collections.Generic.List[IO.FileStream]]::new()
    try{
        $runtime=Assert-R4InstalledBindings;Open-AgyLoginPins
        foreach($row in @(@($script:terminalSource,$script:terminalHash),@($script:terminalBridgeSource,$script:terminalBridgeHash))){
            $held.Add((Open-VerifiedFile $row[0] $row[1] (Get-Item -LiteralPath $row[0]).Length))
        }
        $connection=Connect-AgyTaskFolder;$holds=@(Get-AgyDaemonHolds $connection.folder)
        if($holds.Count){throw ($holds -join ' | ')}
        Invoke-AgyTerminalApply $connection.scheduler $connection.folder $runtime $Slot $deadline
    }finally{foreach($stream in $held){$stream.Dispose()}}
}

Invoke-AgyTerminalMain $Slot $DeadlineUtc $LegacyWrapperSha256 ([bool]$Apply) $PSScriptRoot $PublicStatusRoot
