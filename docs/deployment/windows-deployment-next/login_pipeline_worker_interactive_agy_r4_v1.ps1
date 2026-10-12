#Requires -Version 5.1
<# Attended agy (Gemini, Antigravity CLI 1.3.1) Google sign-in for ONE worker slot of the r4 stopped runtime
   (Gemini build-manifest step 4). Modelled on login_pipeline_worker_interactive_r3_v6.ps1 (sha256 837f567c...);
   its reviewed packet, cancel, task-state and Claude code-input functions are imported unchanged by hash.
   Default is a read-only plan (cochem-interactive-agy-login-plan/1) that creates nothing and runs no native command.
   -Apply -Interactive (AETHERDESK\ansac at an elevated, non-redirected 64-bit Windows PowerShell 5.1 ConsoleHost):
     1. binds the r4 runtime (Assert-R4InstalledBindings), the bridge, its support module (= worker-native-auth-status-
        six-r4-v1.py), python/base/pyvenv/layout/pipeline.json and agy.exe by hash and holds them open; requires the four
        daemon tasks stopped and disabled; reviews every earlier session of the slot (Assert-ReviewedAgyHistory);
     2. creates C:\Program Files\CoChem\InteractiveAgy427-r4-<slot>-<nonce> (SYSTEM/BA only), copies the bridge and the
        support module, registers ONE trigger-free SYSTEM task CoChem-4.2.7-InteractiveAgy-r4-<slot>-<nonce> (PT15M,
        SDDL O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA), registration flags 18 = TASK_CREATE|TASK_DONT_ADD_PRINCIPAL_ACE) whose action is
        -I -B "<root>\worker_agy_login_bridge_r4_v1.py" --slot <slot> --nonce <nonce> --login-mode <print|tui>
        and requests exactly one Run;
     3. relays the bridge's sanitized operator.log (the Google sign-in URL) to this console until the native code
        prompt ((?i)(paste|enter) the authorization code|Enter the redirect URL, split-prefix guarded), then takes ONE
        masked line (Enter submits, Escape cancels) and writes it as the private CreateNew packet input.once;
        14-minute console deadline; the code is never echoed, logged or recorded. The masked prompt is shown only for a
        native prompt that follows an https://accounts.google.com/ URL; otherwise it is held. Once the bridge's
        input.closed marker exists (it left its 600 s read loop) or the task ended, no code is accepted or written;
     4. after the task ended, deletes an input.once the bridge never read (receipt one_line_submitted false, or no
        receipt) and states on the console what the receipt says about the line; binds receipt.json
        (cochem-interactive-agy-login/1) with the shared classifier Assert-AgyHistoryReceipt and
        writes session-result.json (cochem-interactive-agy-login-result/1, CreateNew) or, on any failure after the
        root exists, session-held.json (cochem-interactive-agy-login-held/1, CreateNew).
   -LoginMode is the signed-out capture's verdict (login-mode.json of agy-status-capture-r4-v1): print or tui; none is
   refused before any change (Gemini held). With -CaptureAttempt the wrapper itself re-reads that login-mode.json
   through the capture receipt's sha256 binding and holds on any mismatch.
   Exit codes: 0 plan printed, or accepted terminal login (LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED or
   LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED, verified cleanup) - the reviewed after-status check decides;
   20 orderly pause: a rate-limit or identity-verification marker was seen in a cleanly ended session (do not start
   another slot); 1 (terminating error) every refusal, hold or failed/cancelled login. Nothing is retried or killed and
   nothing but an unread input.once is deleted; the task and root are preserved as evidence. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('slot1','slot2','slot3','slot4','slot5','slot6')][string]$Slot,
    [Parameter(Mandatory=$true)][ValidateSet('print','tui','none')][string]$LoginMode,
    [switch]$Apply,
    [switch]$Interactive,
    [ValidatePattern('^[a-f0-9]{32}$')][string]$CaptureAttempt=''
)

function Import-PinnedFunctions {
    param([string]$Path,[string]$Expected,[string[]]$Names)
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try{
        $sha=[Security.Cryptography.SHA256]::Create();try{$digest=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        if($digest -cne $Expected){throw ('Reviewed helper changed: '+$Path)}
        $stream.Position=0;$reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true,4096,$true)
        try{$text=$reader.ReadToEnd()}finally{$reader.Dispose()}
        $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
        if($errors.Count){throw ('Reviewed helper does not parse: '+$Path)}
        foreach($name in $Names){
            $nodes=@($ast.FindAll({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst]},$true)|Where-Object{$_.Name -ceq $name})
            if($nodes.Count -ne 1){throw ('Expected exactly one reviewed definition of '+$name)}
            $nodes[0].Extent.Text
        }
    }finally{$stream.Dispose()}
}

function Set-AgyLoginConstants {
    param([string]$Slot,[string]$LoginMode,[string]$ScriptRoot)
    $script:programFiles='C:\Program Files';$script:cochemRoot='C:\Program Files\CoChem'
    $script:installRoot='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4'
    $script:basePythonRoot='C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312';$script:basePython=Join-Path $script:basePythonRoot 'python.exe'
    $script:python=Join-Path $script:installRoot '.venv\Scripts\python.exe';$script:venvConfig=Join-Path $script:installRoot '.venv\pyvenv.cfg'
    $script:layout=Join-Path $script:installRoot 'windows-layout.json';$script:config=Join-Path $script:installRoot 'pipeline.json'
    $script:nativeRoot='C:\Program Files\CoChem\Native4.2.7-windows-20261006';$script:native=Join-Path $script:nativeRoot 'agy.exe'
    $script:pythonHash='560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'
    $script:basePythonHash='d8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa'
    $script:venvHash='0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d'
    $script:layoutHash='8430fdf1109c63c4a89479f03da8a465dfebf5566c7791c64f868202170672c4'
    $script:configHash='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
    $script:agyHash='38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741'
    $script:workspace=$ScriptRoot
    $script:bridgeName='worker_agy_login_bridge_r4_v1.py';$script:bridgeSource=Join-Path $ScriptRoot $script:bridgeName
    $script:bridgeHash='4074878f100ae59b804c95bd97b3280ccaa09f919ffaa365a3e2c6985045b8d9'
    $script:supportName='worker_native_status_support.py';$script:supportSource=Join-Path $ScriptRoot 'worker-native-auth-status-six-r4-v1.py'
    $script:supportHash='45681477194d97b144e8ee4505d4364d73d58aaef19c8428c846df642c834839'
    $script:copyHelper='C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1'
    $script:copyHelperHash='0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b'
    $script:statusFunctions=Join-Path $ScriptRoot 'check-worker-native-status-r3.ps1';$script:statusFunctionsHash='18f58ebb448d8a0c6329dd187d4a9a27fa9cbe942cd05e906bb7aabc67e787a7'
    $script:leafFunctions=Join-Path $ScriptRoot 'check-worker-native-auth-status-six-r4-v1.ps1';$script:leafFunctionsHash='34612ac49eb2e455076a01607634f21d4f0b284714ef07d5e614146a1a9a7a85'
    $script:registrationFunctions=Join-Path $ScriptRoot 'register-stopped-warden-r3.ps1';$script:registrationFunctionsHash='eccc593f36cbf488a54775b4343bcf3cf8b261b7cd81e5536fb7f2f18466a198'
    $script:inspectionFunctions=Join-Path $ScriptRoot 'protected-code-inspection-v4.ps1';$script:inspectionFunctionsHash='5c01543cbb8b8d64b2b9f1bab4a13f87f8ff9e1ab3e82dfb6fc547144c77b95d'
    $script:codeInput=Join-Path $ScriptRoot 'claude-code-input-v6.ps1';$script:codeInputHash='74c41bf1b118a62d2decae8d7d9c2ffeb2c19d977033435267f8155fac1f7bf9'
    $script:v6Leaf=Join-Path $ScriptRoot 'login_pipeline_worker_interactive_r3_v6.ps1';$script:v6LeafHash='837f567c5cae00d30620e313d746df6acf98259c9ffa1ef43ebc217b7cf9c46d'
    $script:history=Join-Path $ScriptRoot 'agy-session-history-r4-v1.ps1';$script:historyHash='4e86b712314e2a6a8ea9f13e1dfcc9e65dda4035d2895b8043fbf6ceed0424d4'
    $script:captureNamespace='AgyCapture4.2.7-windows-20261010-r4-v1-'
    $script:daemonTaskNames=@('CoChem-4.2.7-Warden','CoChem-4.2.7-Supervisor','CoChem-4.2.2-Warden','CoChem-4.2.3-Supervisor')
    $script:taskTimeLimit='PT15M';$script:taskSddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)';$script:wrapperMinutes=14
    # Registration flags 18 = TASK_CREATE (0x2) | TASK_DONT_ADD_PRINCIPAL_ACE (0x10), still create-only. With 2 alone this host
    # stores the task DACL unprotected with an appended (A;;FR;;;SY) ACE, which Assert-RegisteredTaskAcl refuses (r5 sitting v2,
    # 2026-10-11) and which would leave a receipt-less InteractiveAgy root. 18 kept the exact protected two-ACE DACL and passed
    # the same validator on 2026-10-08 (resume-pending-warden-r3-v7.ps1:125, TaskAclRecovery4.2.7-windows-20261008-r3-v1).
    $script:taskRegistrationFlags=18
    $script:loginSeconds=600;$script:postInputSeconds=120
    $script:operatorLogLimit=131072;$script:receiptLimit=65536;$script:recordLimit=65536
    $script:sessionRoot=$null;$script:taskName=$null
}

function Get-AgyLoginHelperDefinitions {
    # Only exact reviewed definitions, never helper actions; the caller dot-sources them in its own scope.
    Import-PinnedFunctions $script:copyHelper $script:copyHelperHash @('Assert-NoReparseAncestors','Assert-ProtectedPath','Initialize-FileIdentity','Open-VerifiedFile')
    Import-PinnedFunctions $script:statusFunctions $script:statusFunctionsHash @('Read-R3Control','Read-R3Text')
    Import-PinnedFunctions $script:leafFunctions $script:leafFunctionsHash @('Assert-R4InstalledBindings','Assert-VenvBinding')
    Import-PinnedFunctions $script:registrationFunctions $script:registrationFunctionsHash @('Assert-RegisteredTaskAcl')
    Import-PinnedFunctions $script:inspectionFunctions $script:inspectionFunctionsHash @('Assert-CodeTreeOnce')
    Import-PinnedFunctions $script:codeInput $script:codeInputHash @('New-ClaudeCodeInput','Update-ClaudeCodeInput','Complete-ClaudeCodeInput','Close-ClaudeCodeInput','Clear-ClaudeConsoleInput')
    Import-PinnedFunctions $script:v6Leaf $script:v6LeafHash @('New-PrivateAcl','Write-PrivatePacket','Write-CancelRequest','Get-ExactTaskOrAbsent','Assert-TaskTerminal','Test-InstanceComplete')
    Import-PinnedFunctions $script:history $script:historyHash @('Get-AgyHistoryParent','Get-AgyHistoryPins','Get-AgyHistoryMarkerNames','Test-AgyHistoryInteger','Get-AgyHistoryValue',
        'Test-AgyHistoryProperty','Get-AgyHistorySafeReceiptMetadata','Assert-AgyHistoryPrivateAcl','Assert-AgyHistoryPrivateRoot','Get-AgyHistoryTaskArguments','Assert-AgyHistoryTask',
        'Assert-AgyHistoryProcess','Assert-AgyHistoryMarkers','Assert-AgyHistoryTokenStorage','Assert-AgyHistoryReceipt','Get-AgyHistoryExpectedSid','Get-AgyHistorySessionRecord','Assert-ReviewedAgyHistory')
}

function Get-AgyLoginHostProbe {
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    [pscustomobject]@{edition=[string]$PSVersionTable.PSEdition;is64=[Environment]::Is64BitProcess;computer=[string]$env:COMPUTERNAME;
        admin=[Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator);identity=[string]$identity.Name;
        user_interactive=[Environment]::UserInteractive;input_redirected=[Console]::IsInputRedirected;output_redirected=[Console]::IsOutputRedirected;host_name=[string]$Host.Name}
}

function Assert-AgyLoginHost {
    param([bool]$ApplyRequested,[bool]$InteractiveRequested,$Probe=$null)
    if($null -eq $Probe){$Probe=Get-AgyLoginHostProbe}
    $isTrue={param($Value)($Value -is [bool]) -and $Value};$isFalse={param($Value)($Value -is [bool]) -and -not $Value}
    if($Probe.edition -cne 'Desktop' -or -not (& $isTrue $Probe.is64) -or $Probe.computer -cne 'AETHERDESK'){throw 'Use 64-bit Windows PowerShell 5.1 on AETHERDESK.'}
    if($ApplyRequested -and (-not $InteractiveRequested -or -not (& $isTrue $Probe.admin) -or $Probe.identity -cne 'AETHERDESK\ansac' -or -not (& $isTrue $Probe.user_interactive) -or
       -not (& $isFalse $Probe.input_redirected) -or -not (& $isFalse $Probe.output_redirected) -or $Probe.host_name -cne 'ConsoleHost')){
        throw 'Apply requires the owner at an elevated interactive ConsoleHost, with -Interactive and no redirected input/output.'
    }
}

function Connect-AgyTaskFolder {
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect()
    [pscustomobject]@{scheduler=$scheduler;folder=$scheduler.GetFolder('\')}
}

function Get-AgyDaemonHolds {
    param($Folder)
    # The four daemon names of the sign-in series precondition; observer/recorder tasks are not inspected.
    foreach($name in $script:daemonTaskNames){
        $task=$null;$absent=$false;$denied=$false
        try{$task=$Folder.GetTask($name)}catch{
            $errorItem=$_.Exception
            while($null -ne $errorItem){
                if($errorItem.HResult -eq -2147024894){$absent=$true;break}
                if($errorItem.HResult -eq -2147024891){$denied=$true;break}
                $errorItem=$errorItem.InnerException}
            if(-not $absent -and -not $denied){('Daemon task state is unknown: '+$name);continue}
        }
        if($absent){continue}
        if($denied){('Daemon task definition is unreadable without elevation; re-read during -Apply: '+$name);continue}
        $active=$null
        try{$active=([bool]$task.Enabled -or [int]$task.State -notin @(1,3) -or [int]$task.GetInstances(0).Count -ne 0)}catch{('Daemon task could not be read: '+$name);continue}
        if($active){('Protected daemons must remain stopped and disabled: '+$name)}
    }
}

function Open-AgyLoginPins {
    # Hash-verified handles stay open (FileShare.Read) for the whole session: no reviewed byte can change underneath.
    foreach($pin in @(
        @($script:bridgeSource,$script:bridgeHash,$false),@($script:supportSource,$script:supportHash,$false),
        @($script:python,$script:pythonHash,$true),@($script:basePython,$script:basePythonHash,$true),@($script:venvConfig,$script:venvHash,$true),
        @($script:layout,$script:layoutHash,$true),@($script:config,$script:configHash,$true),@($script:native,$script:agyHash,$true),
        @($script:history,$script:historyHash,$false),@($script:codeInput,$script:codeInputHash,$false),@($script:v6Leaf,$script:v6LeafHash,$false),
        @($script:inspectionFunctions,$script:inspectionFunctionsHash,$false))){
        if($pin[2]){Assert-ProtectedPath $pin[0]}
        $stream=Open-VerifiedFile $pin[0] $pin[1] (Get-Item -LiteralPath $pin[0]).Length;$held.Add($stream)
        if($pin[0] -ceq $script:venvConfig){
            $reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true,4096,$true)
            try{Assert-VenvBinding $reader.ReadToEnd()}finally{$reader.Dispose()};$stream.Position=0
        }
    }
}

function Get-AgyLoginModeEvidence {
    param([string]$CaptureAttempt)
    # login-mode.json of the signed-out slot1 capture, bound by the sha256 recorded in its SYSTEM-written receipt.
    if($CaptureAttempt -cnotmatch '^[a-f0-9]{32}$' -or $CaptureAttempt -ceq ('0'*32)){throw 'A nonzero lowercase 32-hex -CaptureAttempt is required.'}
    $root=Join-Path $script:cochemRoot ($script:captureNamespace+$CaptureAttempt+'-slot1-signed-out')
    $receiptControl=Read-R3Control (Join-Path $root 'capture-receipt.json') '' 1048576
    $receipt=(Read-R3Text $receiptControl)|ConvertFrom-Json
    if($receipt.schema -cne 'cochem-agy-status-capture/1' -or $receipt.attempt -cne $CaptureAttempt -or $receipt.slot -cne 'slot1' -or $receipt.stage -cne 'signed-out' -or
       $receipt.status -cne 'CAPTURE_COMPLETE' -or $null -eq $receipt.login_mode -or $receipt.login_mode.path -cne 'login-mode.json' -or
       [string]$receipt.login_mode.sha256 -cnotmatch '^[a-f0-9]{64}$' -or $receipt.gate.passed -isnot [bool]){throw 'The signed-out capture receipt does not bind a login mode.'}
    $modePath=Join-Path $root 'login-mode.json'
    $modeControl=Read-R3Control $modePath $receipt.login_mode.sha256 65536
    $file=(Read-R3Text $modeControl)|ConvertFrom-Json
    if($file.schema -cne 'cochem-agy-login-mode/1' -or $file.attempt -cne $CaptureAttempt -or $file.slot -cne 'slot1' -or $file.stage -cne 'signed-out' -or
       $file.nonce -cne $receipt.nonce -or $file.mode -cnotin @('print','tui','none') -or $file.mode -cne $receipt.login_mode.mode){throw 'login-mode.json contradicts its capture receipt.'}
    [pscustomobject]@{capture_attempt=$CaptureAttempt;path=$modePath;sha256=$modeControl.Sha256;mode=[string]$file.mode;decided_by=$file.decided_by;
        capture_receipt_sha256=$receiptControl.Sha256;gate_passed=[bool]$receipt.gate.passed}
}

function Get-AgyLoginHolds {
    param($Folder,[string]$Slot,[string]$LoginMode,$Evidence,[bool]$ApplyRequested)
    if($LoginMode -ceq 'none'){'Login mode none: the signed-out capture saw no reachable sign-in path; Gemini stays held for this sitting and no login is started.'}
    if($null -ne $Evidence){
        if($Evidence.mode -cne $LoginMode){'-LoginMode '+$LoginMode+' differs from login-mode.json ('+$Evidence.mode+') of capture '+$Evidence.capture_attempt+'.'}
        if($Evidence.gate_passed -ne $true){'The signed-out capture gate did not pass; Gemini stays held for this sitting.'}
    }
    Get-AgyDaemonHolds $Folder
    if(-not $ApplyRequested){
        $previous=@(Get-ChildItem -LiteralPath $script:cochemRoot -Directory -Filter ('InteractiveAgy427-r4-'+$Slot+'-*') -ErrorAction Stop)
        $previous+=@(Get-ChildItem -LiteralPath $script:cochemRoot -Directory -Filter ('InteractiveAgy427-'+$Slot+'-*') -ErrorAction Stop)
        if($previous.Count){'Earlier agy sessions of this slot require protected terminal-receipt review (Assert-ReviewedAgyHistory) in Administrator -Apply before a new login.'}
    }
}

function New-AgyLoginNonce {[Guid]::NewGuid().ToString('N')}

function Set-AgySessionNames {
    param([string]$Slot,[string]$Nonce)
    $script:sessionRoot=Join-Path $script:cochemRoot ('InteractiveAgy427-r4-'+$Slot+'-'+$Nonce)
    $script:taskName='CoChem-4.2.7-InteractiveAgy-r4-'+$Slot+'-'+$Nonce
}

function New-AgyLoginTaskDefinition {
    param($Scheduler,[string]$Arguments)
    $definition=$Scheduler.NewTask(0)
    $definition.RegistrationInfo.Description='Explicit owner interactive agy (Gemini) Google sign-in for one worker; one private bounded input line; no model jobs or daemon activation.'
    $definition.Principal.UserId='SYSTEM';$definition.Principal.LogonType=5;$definition.Principal.RunLevel=1
    $definition.Settings.Enabled=$true;$definition.Settings.AllowDemandStart=$true;$definition.Settings.MultipleInstances=2
    $definition.Settings.ExecutionTimeLimit=$script:taskTimeLimit;$definition.Settings.RestartCount=0
    $action=$definition.Actions.Create(0);$action.Path=$script:python;$action.Arguments=$Arguments;$action.WorkingDirectory=$script:sessionRoot
    $definition
}

function Assert-AgyLoginTaskDefinition {
    param($Task,[string]$Slot,[string]$Nonce,[string]$LoginMode)
    # Read back exactly what was registered, with the same rules the history review applies later.
    $mode=Assert-AgyHistoryTask $Task $script:sessionRoot $Slot $Nonce
    $definition=$Task.Definition
    if($mode -cne $LoginMode -or $Task.Enabled -ne $true -or $definition.Settings.AllowDemandStart -ne $true -or
       $definition.Actions.Item(1).Arguments -cne (Get-AgyHistoryTaskArguments $script:sessionRoot $Slot $Nonce $LoginMode)){throw 'Registered login task action/identity differs.'}
    Assert-RegisteredTaskAcl ([string]$Task.GetSecurityDescriptor(7))
}

function Copy-AgySessionSources {
    foreach($copy in @(@($script:bridgeSource,$script:bridgeName,$script:bridgeHash),@($script:supportSource,$script:supportName,$script:supportHash))){
        $length=(Get-Item -LiteralPath $copy[0]).Length
        $destination=Join-Path $script:sessionRoot $copy[1]
        $inputStream=Open-VerifiedFile $copy[0] $copy[2] $length
        try{
            $outputStream=[IO.FileStream]::new($destination,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,4096,[IO.FileOptions]::None,(New-PrivateAcl))
            try{$inputStream.CopyTo($outputStream);$outputStream.Flush($true)}finally{$outputStream.Dispose()}
        }finally{$inputStream.Dispose()}
        $held.Add((Open-VerifiedFile $destination $copy[2] $length))
    }
}

function Write-AgySessionRecord {
    param([string]$Path,$Value)
    # CreateNew with the final SYSTEM/BA-only DACL; an existing record is never replaced.
    $bytes=[Text.UTF8Encoding]::new($false,$true).GetBytes(($Value|ConvertTo-Json -Depth 8))
    if($bytes.Length -gt $script:recordLimit){throw 'Session record exceeds its bound.'}
    $stream=[IO.FileStream]::new($Path,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,4096,[IO.FileOptions]::None,(New-PrivateAcl))
    try{$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
    $sha=[Security.Cryptography.SHA256]::Create()
    try{[BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
}

function Test-AgyConsoleKeyAvailable {[Console]::KeyAvailable}

function Read-AgyConsoleKey {[Console]::ReadKey($true)}

function Write-AgyConsoleText {
    param([string]$Text)
    # The bridge already publishes display-safe text; strip any control or bidi character again before the console.
    $clean=[regex]::Replace($Text,'[\x00-\x08\x0B-\x1F\x7F-\x9F\u200E\u200F\u202A-\u202E\u2066-\u2069]','')
    if($clean.Length){[Console]::Write($clean)}
}

function Read-AgyOperatorLog {
    param([string]$Path)
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
    try{
        if($stream.Length -gt $script:operatorLogLimit){throw 'Operator log exceeds its bound.'}
        $reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$false,4096,$true)
        try{$reader.ReadToEnd()}finally{$reader.Dispose()}
    }finally{$stream.Dispose()}
}

function Find-AgyNativePrompt {
    param([string]$Text)
    $match=[regex]::Match($Text,'(?i)(paste|enter) the authorization code|Enter the redirect URL')
    if($match.Success){return $match.Index}
    return -1
}

function Find-AgyGoogleSignInUrl {
    param([string]$Text)
    # The one reviewed sign-in origin (scheme, host and path separator exactly; case-insensitive like the bridge markers).
    return $Text.IndexOf('https://accounts.google.com/',[StringComparison]::OrdinalIgnoreCase)
}

function Find-AgyCodePrompt {
    param([string]$Text)
    # The first native code prompt that follows a Google sign-in URL, else -1: only it opens the masked code prompt.
    $google=Find-AgyGoogleSignInUrl $Text
    if($google -lt 0){return -1}
    $at=Find-AgyNativePrompt $Text.Substring($google)
    if($at -lt 0){return -1}
    return $google+$at
}

function Get-AgyPromptPrefixHold {
    param([string]$Text)
    # Retain only a possible split prompt prefix; complete URLs and all other output remain visible.
    $lower=$Text.ToLowerInvariant()
    $prompts=@('paste the authorization code','enter the authorization code','enter the redirect url')
    for($tail=[Math]::Min(27,$lower.Length);$tail -gt 0;$tail--){
        $suffix=$lower.Substring($lower.Length-$tail)
        foreach($prompt in $prompts){if($tail -lt $prompt.Length -and $prompt.StartsWith($suffix,[StringComparison]::Ordinal)){return $tail}}
    }
    return 0
}

function Show-AgyLoginInstructions {
    param([string]$Slot,[string]$LoginMode)
    Write-Host ('Gemini (agy) Google sign-in for '+$Slot+' in '+$LoginMode+' mode.')
    Write-Host 'Open the printed Google sign-in URL in your own browser now; the consent may time out after about 60 seconds.'
    Write-Host 'Paste the returned authorization code at the masked Code prompt, then press Enter. Escape cancels. Letters P and Q are ordinary code characters.'
    if($LoginMode -ceq 'tui'){Write-Host ('agy may stay open after sign-in; the bridge ends it at most '+$script:postInputSeconds+' seconds after your input. The after-status check decides.')}
}

function Invoke-AgyLoginConsoleLoop {
    param($Instance,[string]$Root,[string]$Nonce,[DateTime]$DeadlineUtc)
    $log=Join-Path $Root 'operator.log';$inputPath=Join-Path $Root 'input.once';$closedPath=Join-Path $Root 'input.closed'
    $seen=0;$nativePromptReady=$false;$cancelSent=$false;$urlNoticed=$false;$promptHeld=$false;$windowClosed=$false
    $inputState=New-ClaudeCodeInput
    try{
        while(-not (Test-InstanceComplete $Instance)){
            if([DateTime]::UtcNow -ge $DeadlineUtc){Write-CancelRequest $Root $Nonce;$cancelSent=$true;throw 'Login wrapper deadline reached; cancellation requested. Preserve the task/root and review terminal cleanup; no automatic retry.'}
            # The bridge writes input.closed before it leaves its read loop (600 s window, exit, cancellation or a stop).
            if(-not $windowClosed -and (Test-Path -LiteralPath $closedPath)){$windowClosed=$true}
            if(-not $nativePromptReady -and -not $inputState.Submitted -and -not $cancelSent -and (Test-Path -LiteralPath $log)){
                $text=Read-AgyOperatorLog $log
                $promptAt=Find-AgyNativePrompt $text
                $readyAt=Find-AgyCodePrompt $text
                # Everything before the native prompt (the sign-in URL) is shown; a possible split prompt prefix is held back.
                if($readyAt -ge 0){$displayEnd=$readyAt}elseif($promptAt -ge 0){$displayEnd=$promptAt}else{$displayEnd=$text.Length-(Get-AgyPromptPrefixHold $text)}
                if($displayEnd -gt $seen){Write-AgyConsoleText ($text.Substring($seen,$displayEnd-$seen));$seen=$displayEnd}
                if(-not $urlNoticed -and (Find-AgyGoogleSignInUrl $text.Substring(0,[Math]::Min($seen,$text.Length))) -ge 0){
                    $urlNoticed=$true;Write-Host '';Write-Host 'Open the Google sign-in URL shown above in your own browser now.'
                }
                if($readyAt -ge 0 -and -not $windowClosed){
                    $seen=$text.Length;$nativePromptReady=$true
                    Write-Host '';[Console]::Write('Code (masked; Enter submits, Escape cancels): ')
                }elseif($promptAt -ge 0 -and $readyAt -lt 0 -and -not $promptHeld){
                    $promptHeld=$true;Write-Host ''
                    Write-Host 'agy asks for a code, but no Google sign-in URL (https://accounts.google.com/) appeared before it: the code prompt is held and no code is accepted. Escape cancels.'
                }
            }
            $keysRead=0
            while($keysRead -lt 256 -and (Test-AgyConsoleKeyAvailable)){
                $key=Read-AgyConsoleKey;$keysRead++
                if($windowClosed -or $inputState.Closed){continue}  # Refused input: read and discarded, never kept.
                Update-ClaudeCodeInput -State $inputState -Key $key
                if($inputState.SubmissionRequested -or $inputState.CancelRequested){break}
            }
            $key=$null
            if($inputState.CancelRequested -and -not $cancelSent){
                Write-CancelRequest $Root $Nonce;$cancelSent=$true
                $drain=Clear-ClaudeConsoleInput;if($drain.console_queue_clear -isnot [bool] -or -not $drain.console_queue_clear){throw 'Console input exceeded its clearing bound; preserve the session.'}
                Write-Host '';Write-Host 'Cancellation requested; waiting for owned Job/profile cleanup.'
            }elseif($inputState.SubmissionRequested -and -not $inputState.Submitted -and $nativePromptReady -and -not $cancelSent){
                # Never write after the bridge left its read loop or after the task ended: nothing would read the line.
                if((Test-Path -LiteralPath $closedPath) -or (Test-InstanceComplete $Instance)){$windowClosed=$true}
                else{
                    Write-PrivatePacket $inputPath $Nonce $inputState.Secret
                    Complete-ClaudeCodeInput -State $inputState
                    $drain=Clear-ClaudeConsoleInput;if($drain.console_queue_clear -isnot [bool] -or -not $drain.console_queue_clear){throw 'Console input exceeded its clearing bound; preserve the session.'}
                    Write-Host '';Write-Host ('One line written for the bridge; its receipt will show whether agy received it. Waiting for the agy sign-in to finish (the bridge ends a still-open agy after '+$script:postInputSeconds+' s) and for cleanup. Escape cancels.')
                }
            }
            if($windowClosed -and -not $inputState.Submitted -and -not $inputState.Closed -and -not $cancelSent){
                Close-ClaudeCodeInput -State $inputState
                Write-Host '';Write-Host 'The bridge input window has closed (600 s elapsed or agy ended): no code is accepted and none was written. Waiting for cleanup.'
            }
            Start-Sleep -Milliseconds 100
        }
        if(-not $nativePromptReady -and -not $inputState.Submitted -and (Test-Path -LiteralPath $log)){
            # The native login ended before any prompt: show what it printed (for example a refusal line).
            $text=Read-AgyOperatorLog $log
            if($text.Length -gt $seen){Write-AgyConsoleText ($text.Substring($seen));Write-Host ''}
        }
    }catch{
        try{Write-CancelRequest $Root $Nonce}catch{};throw
    }finally{
        Close-ClaudeCodeInput -State $inputState
        $drain=Clear-ClaudeConsoleInput;if($drain.console_queue_clear -isnot [bool] -or -not $drain.console_queue_clear){throw 'Console input exceeded its clearing bound; preserve the session.'}
    }
    # one_line_submitted: this console wrote the packet; the receipt alone says whether the bridge fed it to agy.
    [pscustomobject]@{native_prompt_seen=$nativePromptReady;one_line_submitted=[bool]$inputState.Submitted;cancel_requested=$cancelSent;
        input_window_closed=$windowClosed;code_prompt_held=($promptHeld -and -not $nativePromptReady)}
}

function Remove-AgyUnconsumedInput {
    param([string]$Root,[string]$Slot,[string]$Nonce)
    # Only after the task ended. A line the bridge never read (its receipt says one_line_submitted false, or there is no
    # receipt, so the bridge never reached its read loop) still holds the code and is deleted. A consumed line follows
    # the bridge's verified-cleanup rule, and an unreadable or unbound receipt preserves everything for review.
    $inputPath=Join-Path $Root 'input.once';$receiptPath=Join-Path $Root 'receipt.json'
    $result=[ordered]@{input_present=$false;consumed=$null;deleted=$false}
    if(-not (Test-Path -LiteralPath $inputPath)){return $result}
    $result.input_present=$true
    if(Test-Path -LiteralPath $receiptPath){
        try{
            $receipt=(Read-R3Text (Read-R3Control $receiptPath '' $script:receiptLimit))|ConvertFrom-Json
            $submitted=Get-AgyHistoryValue $receipt 'one_line_submitted' -Optional
            if((Get-AgyHistoryValue $receipt 'schema' -Optional) -cne 'cochem-interactive-agy-login/1' -or (Get-AgyHistoryValue $receipt 'slot' -Optional) -cne $Slot -or
               (Get-AgyHistoryValue $receipt 'nonce' -Optional) -cne $Nonce -or $submitted -isnot [bool]){return $result}
            $result.consumed=$submitted
        }catch{return $result}
    }else{$result.consumed=$false}
    if($result.consumed){return $result}
    $item=Get-Item -LiteralPath $inputPath -Force -ErrorAction Stop
    if($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'The unread input channel is not an ordinary file; preserve the session.'}
    [IO.File]::Delete($inputPath)
    if(Test-Path -LiteralPath $inputPath){throw 'The unread input channel could not be deleted; preserve the session.'}
    $result.deleted=$true
    return $result
}

function Show-AgyInputReceiptLine {
    param($Loop,$Receipt,$InputCleanup)
    # The console states what the receipt says about the line this console wrote (never the line itself).
    if($null -eq $Loop -or -not $Loop.one_line_submitted){return}
    $fed=Get-AgyHistoryValue $Receipt 'one_line_submitted' -Optional
    if($fed -isnot [bool]){return}
    if($fed){Write-Host 'The receipt shows the bridge fed the one line to agy.';return}
    $line='The receipt shows the bridge never read the line, so agy did not receive it'
    if($null -ne $InputCleanup -and $InputCleanup.deleted){$line+='; the unread input.once was deleted.'}else{$line+='.'}
    Write-Host $line
}

function Get-AgyLoginFailureMessage {
    param($Proof)
    switch -CaseSensitive ([string]$Proof.classification){
        'TERMINAL_CANCELLED_NATIVE_LOGIN_CLEANUP_VERIFIED'{return 'The agy sign-in was cancelled at the console; cleanup is verified.'}
        'TERMINAL_TIMED_OUT_NATIVE_LOGIN_CLEANUP_VERIFIED'{return ('No authorization code was submitted within '+$script:loginSeconds+' s; cleanup is verified.')}
        'TERMINAL_PRE_NATIVE_CUSTODY_FAILURE_NO_CHILD_LAUNCHED'{return 'The login bridge refused before launching agy (native custody); no child was started.'}
        'TERMINAL_OUTPUT_BOUND_NATIVE_LOGIN_CLEANUP_VERIFIED'{return ('agy printed more display text than the '+$script:operatorLogLimit+'-byte bound before any code was submitted; the bridge stopped it, cleanup is verified and a fresh attempt is not blocked.')}
    }
    $message='The agy sign-in command ended with exit code '+$Proof.native_exit_code
    $markers=@($Proof.failure_markers)
    if('no_controlling_terminal_present' -cin $markers){$message+=' (agy refused interactive sign-in without a controlling terminal)'}
    elseif($markers.Count){$message+=(' (markers: '+($markers -join ', ')+')')}
    return ($message+'; cleanup is verified.')
}

function Get-AgyLoginOutcome {
    param($Proof)
    # 20 = orderly pause (rate limit / identity verification seen in a cleanly ended session); 0 = accepted; else failure.
    $ended=@('TERMINAL_NATIVE_LOGIN_CLEANUP_VERIFIED','TERMINAL_CANCELLED_NATIVE_LOGIN_CLEANUP_VERIFIED','TERMINAL_TIMED_OUT_NATIVE_LOGIN_CLEANUP_VERIFIED',
        'TERMINAL_OUTPUT_BOUND_NATIVE_LOGIN_CLEANUP_VERIFIED')
    $clean=($Proof.cleanup_verified -is [bool]) -and $Proof.cleanup_verified
    if($clean -and ($Proof.pause_marker_seen -is [bool]) -and $Proof.pause_marker_seen -and [string]$Proof.classification -cin $ended){
        return [pscustomobject]@{exit_code=20;outcome='PAUSED_RATE_LIMIT_OR_IDENTITY_VERIFICATION';message='Google or agy reported a rate limit or an identity-verification step. Pause the series; do not start another slot now.'}
    }
    if($clean -and ($Proof.accepted -is [bool]) -and $Proof.accepted -and [string]$Proof.classification -ceq 'TERMINAL_NATIVE_LOGIN_CLEANUP_VERIFIED'){
        return [pscustomobject]@{exit_code=0;outcome='LOGIN_ENDED_STATUS_REQUIRED';message='The agy sign-in ended. Run the reviewed after-status check; it alone decides whether the worker is signed in.'}
    }
    [pscustomobject]@{exit_code=$null;outcome='LOGIN_NOT_COMPLETED';message=(Get-AgyLoginFailureMessage $Proof)}
}

function Invoke-AgyLoginApply {
    param($Scheduler,$Folder,$Runtime,[string]$Slot,[string]$LoginMode,$Evidence)
    # Elevated: inspect the code trees once before the r4 interpreter runs as SYSTEM, then review earlier sessions.
    $null=Assert-CodeTreeOnce $script:installRoot;$null=Assert-CodeTreeOnce $script:basePythonRoot;$null=Assert-CodeTreeOnce $script:nativeRoot
    $null=@(Assert-ReviewedAgyHistory -Slot $Slot -Folder $Folder -Runtime $Runtime)
    $expectedSid=Get-AgyHistoryExpectedSid $Slot
    $nonce=New-AgyLoginNonce
    if($nonce -cnotmatch '^[a-f0-9]{32}$' -or $nonce -ceq ('0'*32)){throw 'A fresh nonzero session nonce is required. Nothing was changed.'}
    Set-AgySessionNames $Slot $nonce
    if(Test-Path -LiteralPath $script:sessionRoot){throw 'Fresh login root unexpectedly exists. Nothing was changed.'}
    if($null -ne (Get-ExactTaskOrAbsent $Folder $script:taskName)){throw 'Fresh login task unexpectedly exists. Nothing was changed.'}
    Assert-ProtectedPath $script:cochemRoot
    $null=[IO.Directory]::CreateDirectory($script:sessionRoot,(New-PrivateAcl -Directory))
    # From here the session namespace is consumed: every failure leaves session-held.json (CreateNew).
    $phase='ROOT';$task=$null;$registered=$false;$runRequested=$false;$loop=$null;$receiptControl=$null;$proof=$null;$outcome=$null;$result=$null
    $failure=$null;$failureMetadata=$null;$resultWritten=$false;$receiptPath=Join-Path $script:sessionRoot 'receipt.json';$inputCleanup=$null
    try{
        Assert-ProtectedPath $script:sessionRoot
        $phase='COPY';Copy-AgySessionSources
        $phase='REGISTER'
        $arguments=Get-AgyHistoryTaskArguments $script:sessionRoot $Slot $nonce $LoginMode
        $registered=$true
        $task=$Folder.RegisterTaskDefinition($script:taskName,(New-AgyLoginTaskDefinition $Scheduler $arguments),$script:taskRegistrationFlags,'SYSTEM',$null,5,$script:taskSddl)
        Assert-AgyLoginTaskDefinition $task $Slot $nonce $LoginMode
        $phase='RUN'
        Show-AgyLoginInstructions $Slot $LoginMode
        $runRequested=$true
        $instance=$task.Run($null)
        $phase='CONSOLE'
        $loop=Invoke-AgyLoginConsoleLoop $instance $script:sessionRoot $nonce ([DateTime]::UtcNow.AddMinutes($script:wrapperMinutes))
        $phase='TERMINAL';Assert-TaskTerminal $task
        $phase='INPUT_CLEANUP';$inputCleanup=Remove-AgyUnconsumedInput $script:sessionRoot $Slot $nonce
        $phase='RECEIPT'
        if(-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)){throw ('The login bridge left no receipt (LastTaskResult '+$task.LastTaskResult+').')}
        Assert-ProtectedPath $receiptPath
        $receiptControl=Read-R3Control $receiptPath '' $script:receiptLimit
        $receipt=(Read-R3Text $receiptControl)|ConvertFrom-Json
        Show-AgyInputReceiptLine $loop $receipt $inputCleanup
        $phase='DECISION'
        $proof=Assert-AgyHistoryReceipt $receipt $task $Slot $nonce $LoginMode $Runtime $expectedSid
        $outcome=Get-AgyLoginOutcome $proof
        if($null -eq $outcome.exit_code){throw $outcome.message}
        $phase='RESULT'
        $evidenceSummary=$null
        if($null -ne $Evidence){$evidenceSummary=[ordered]@{capture_attempt=$Evidence.capture_attempt;path=$Evidence.path;sha256=$Evidence.sha256;mode=$Evidence.mode}}
        $result=[ordered]@{schema='cochem-interactive-agy-login-result/1';runtime_root=$script:installRoot;install_receipt_sha256=$Runtime.install_receipt_sha256;
            source_manifest_sha256=$Runtime.source_manifest_sha256;slot=$Slot;nonce=$nonce;login_mode=$LoginMode;login_mode_evidence=$evidenceSummary;
            status=$proof.status;classification=$proof.classification;outcome=$outcome.outcome;exit_code=$outcome.exit_code;message=$outcome.message;
            pause_marker_seen=$proof.pause_marker_seen;failure_markers=@($proof.failure_markers);native_exit_code=$proof.native_exit_code;
            one_line_submitted=$proof.one_line_submitted;terminated_after_input=$proof.terminated_after_input;native_prompt_seen_by_console=$loop.native_prompt_seen;
            file_token_present=$proof.file_token_present;credential_manager_entry_present=$proof.credential_manager_entry_present;cleanup_verified=$true;
            session_root=$script:sessionRoot;receipt_path=$receiptPath;receipt_sha256=$receiptControl.Sha256;task_name=$script:taskName;last_task_result=$task.LastTaskResult;
            task_preserved=$true;authentication_verified=$false;
            next_step=('Reviewed native status check: check-worker-native-auth-status-six-r4-v1.ps1 -Slot '+$Slot+' -Provider gemini -Stage after');
            login_commands_executed=$proof.login_commands_executed;model_jobs_executed=0;activation_ready=$false;recorded_utc=[DateTime]::UtcNow.ToString('o');
            input_window_closed_by_console=$loop.input_window_closed;code_prompt_held=$loop.code_prompt_held;input_cleanup=$inputCleanup}
        $recordPath=Join-Path $script:sessionRoot 'session-result.json'
        $recordSha=Write-AgySessionRecord $recordPath $result;$resultWritten=$true
        $result.session_record_path=$recordPath;$result.session_record_sha256=$recordSha
    }catch{
        $failure=$_.Exception.Message;$errorValue=$_.Exception
        while($null -ne $errorValue){if($errorValue.Data.Contains('CoChemAgyHistorySafeMetadata')){$failureMetadata=$errorValue.Data['CoChemAgyHistorySafeMetadata'];break};$errorValue=$errorValue.InnerException}
    }
    if($null -ne $failure){
        $latest=$null;try{if($null -ne $task){$latest=[ordered]@{state=[int]$task.State;last_task_result=[long]$task.LastTaskResult;instances=[int]$task.GetInstances(0).Count}}}catch{$latest=$null}
        # A failure before INPUT_CLEANUP: delete an unread input.once only if the task is conclusively terminal now.
        if($null -eq $inputCleanup -and $runRequested -and $null -ne $latest -and $latest.state -in @(1,3) -and $latest.instances -eq 0){
            try{$inputCleanup=Remove-AgyUnconsumedInput $script:sessionRoot $Slot $nonce}catch{$inputCleanup=[ordered]@{input_present=$true;consumed=$null;deleted=$false}}
        }
        $proofSummary=$null
        if($null -ne $proof){$proofSummary=[ordered]@{classification=$proof.classification;status=$proof.status;pause_marker_seen=$proof.pause_marker_seen;failure_markers=@($proof.failure_markers);
            native_exit_code=$proof.native_exit_code;one_line_submitted=$proof.one_line_submitted;operator_cancelled=$proof.operator_cancelled;cleanup_verified=$proof.cleanup_verified}}
        $heldRecord=[ordered]@{schema='cochem-interactive-agy-login-held/1';slot=$Slot;nonce=$nonce;login_mode=$LoginMode;phase=$phase;reason=$failure;
            session_root=$script:sessionRoot;task_name=$script:taskName;task_registered=$registered;run_requested=$runRequested;task_after=$latest;console=$loop;
            receipt_path=$receiptPath;receipt_present=[bool](Test-Path -LiteralPath $receiptPath -PathType Leaf);
            receipt_sha256=$(if($null -ne $receiptControl){$receiptControl.Sha256}else{$null});receipt_proof=$proofSummary;receipt_metadata=$failureMetadata;
            raw_provider_output_recorded=$false;code_recorded=$false;login_authorized=$false;automatic_retry_allowed=$false;requires_owner_review=$true;
            recorded_utc=[DateTime]::UtcNow.ToString('o');input_cleanup=$inputCleanup}
        $heldNote=''
        if(-not $resultWritten){try{$null=Write-AgySessionRecord (Join-Path $script:sessionRoot 'session-held.json') $heldRecord}catch{$heldNote=(' The held record could not be written: '+$_.Exception.Message)}}
        throw ($failure.TrimEnd('.')+'. Gemini stays held for this slot; preserve '+$script:sessionRoot+' and the task '+$script:taskName+' and review session-held.json. No automatic retry.'+$heldNote)
    }
    [pscustomobject]@{exit_code=[int]$outcome.exit_code;result=$result}
}

function New-AgyLoginPlan {
    param([string]$Slot,[string]$LoginMode,$Runtime,$Evidence,[object[]]$Holds)
    $nativeArguments=@();if($LoginMode -ceq 'print'){$nativeArguments=@('-p','/model')}
    $evidenceSummary=$null
    if($null -ne $Evidence){$evidenceSummary=[ordered]@{capture_attempt=$Evidence.capture_attempt;path=$Evidence.path;sha256=$Evidence.sha256;mode=$Evidence.mode;decided_by=$Evidence.decided_by;gate_passed=$Evidence.gate_passed}}
    [ordered]@{schema='cochem-interactive-agy-login-plan/1';mode='READ_ONLY_PLAN';slot=$Slot;login_mode=$LoginMode;login_mode_evidence=$evidenceSummary;
        runtime_root=$script:installRoot;r4_runtime_verified=($null -ne $Runtime);
        install_receipt_sha256=$(if($null -ne $Runtime){$Runtime.install_receipt_sha256}else{$null});
        source_manifest_sha256=$(if($null -ne $Runtime){$Runtime.source_manifest_sha256}else{$null});
        revision_sha256=$(if($null -ne $Runtime){$Runtime.revision.source_sha256}else{$null});
        native_executable=$script:native;native_sha256=$script:agyHash;native_arguments=$nativeArguments;
        bridge_source=$script:bridgeSource;bridge_sha256=$script:bridgeHash;support_source=$script:supportSource;support_sha256=$script:supportHash;history_sha256=$script:historyHash;
        session_root_pattern=(Join-Path $script:cochemRoot ('InteractiveAgy427-r4-'+$Slot+'-<nonce>'));task_name_pattern=('CoChem-4.2.7-InteractiveAgy-r4-'+$Slot+'-<nonce>');
        task_execution_time_limit=$script:taskTimeLimit;wrapper_deadline_minutes=$script:wrapperMinutes;bridge_login_seconds=$script:loginSeconds;bridge_post_input_seconds=$script:postInputSeconds;
        human_console_required=$true;maximum_input_lines=1;maximum_input_bytes=2048;native_output_suppressed_after_input=$true;
        exit_codes=[ordered]@{'0'='plan, or accepted terminal login; the after-status check decides';'20'='orderly pause: rate-limit or identity-verification marker';'1'='refusal, hold or failed/cancelled login'};
        login_commands_executed=0;model_jobs_executed=0;tasks_changed=0;activation_ready=$false;holds=@($Holds)}
}

function Write-AgyLoginJson {
    param($Value)
    [Console]::Out.WriteLine(($Value|ConvertTo-Json -Depth 8))
}

function Invoke-AgyLoginMain {
    param([string]$Slot,[string]$LoginMode,[string]$CaptureAttempt,[bool]$ApplyRequested,[bool]$InteractiveRequested,[string]$ScriptRoot)
    $ErrorActionPreference='Stop';Set-StrictMode -Version Latest
    $Slot=$Slot.ToLowerInvariant();$LoginMode=$LoginMode.ToLowerInvariant()
    if($Slot -cnotmatch '^slot[1-6]$'){throw 'Only the six configured worker slots are supported. Nothing was changed.'}
    if($LoginMode -cnotin @('print','tui','none')){throw 'Only the login modes print, tui and none are defined. Nothing was changed.'}
    if($CaptureAttempt -and ($CaptureAttempt -cnotmatch '^[a-f0-9]{32}$' -or $CaptureAttempt -ceq ('0'*32))){throw 'A nonzero lowercase 32-hex -CaptureAttempt is required when one is given. Nothing was changed.'}
    foreach($module in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$module\$module.psd1") -ErrorAction Stop}
    Assert-AgyLoginHost $ApplyRequested $InteractiveRequested
    if($ApplyRequested -and $LoginMode -ceq 'none'){throw 'Gemini sign-in is held: the signed-out capture decided login mode none (no reachable sign-in path). No login is started and nothing was changed.'}
    Set-AgyLoginConstants $Slot $LoginMode $ScriptRoot
    foreach($definition in @(Get-AgyLoginHelperDefinitions)){. ([scriptblock]::Create($definition))}
    Initialize-FileIdentity
    $held=[Collections.Generic.List[IO.FileStream]]::new()
    try{
        $holds=@();$runtime=$null;$evidence=$null
        try{$runtime=Assert-R4InstalledBindings}catch{$holds+=('r4 stopped runtime is not the reviewed build: '+$_.Exception.Message)}
        try{Open-AgyLoginPins}catch{$holds+=('A pinned login file differs or is missing: '+$_.Exception.Message)}
        if($CaptureAttempt){try{$evidence=Get-AgyLoginModeEvidence $CaptureAttempt}catch{$holds+=('Signed-out capture evidence: '+$_.Exception.Message)}}
        $connection=Connect-AgyTaskFolder
        $holds+=@(Get-AgyLoginHolds $connection.folder $Slot $LoginMode $evidence $ApplyRequested)
        if(-not $ApplyRequested){Write-AgyLoginJson (New-AgyLoginPlan $Slot $LoginMode $runtime $evidence $holds);return 0}
        if($holds.Count){throw ('The agy login is held. Nothing was changed: '+($holds -join ' | '))}
        $outcome=Invoke-AgyLoginApply $connection.scheduler $connection.folder $runtime $Slot $LoginMode $evidence
        Write-AgyLoginJson $outcome.result
        if($outcome.exit_code -eq 20){Write-Host ('COCHEM_AGY_LOGIN_PAUSE '+$Slot+': '+$outcome.result.message)}
        return [int]$outcome.exit_code
    }finally{foreach($stream in $held){$stream.Dispose()}}
}

function Resolve-AgyLoginExitCode {
    param([object[]]$Values)
    if($null -eq $Values -or $Values.Count -ne 1 -or $Values[0] -isnot [int] -or $Values[0] -notin @(0,20)){throw 'The agy login wrapper produced an unexpected outcome; preserve any session root and review it.'}
    return $Values[0]
}

# Invocation boundary: the only top-level statement. Fixtures dot-source the functions above from the AST without running it.
exit (Resolve-AgyLoginExitCode @(Invoke-AgyLoginMain -Slot $Slot -LoginMode $LoginMode -CaptureAttempt $CaptureAttempt -ApplyRequested ([bool]$Apply) -InteractiveRequested ([bool]$Interactive) -ScriptRoot $PSScriptRoot))
