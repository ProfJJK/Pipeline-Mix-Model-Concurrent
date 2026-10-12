#Requires -Version 5.1
<# Six-worker status-first login series for the r4 stopped runtime (build-manifest step 5; re-issue of
   login-six-workers-status-first-r3-v6.ps1, sha256 9e45266b..., with -Provider gemini added).
   Default is a read-only plan (schema cochem-six-worker-status-first-plan/1): it creates nothing,
   registers no task and runs no native command.
   -Apply -Interactive (AETHERDESK\ansac at an elevated interactive ConsoleHost, no redirection,
   nonzero -Attempt) runs slot1, then slot2..slot6, strictly one slot at a time:
     1. status leaf check-worker-native-auth-status-six-r4-v1.ps1 -Stage before (one SYSTEM one-shot
        task; for gemini CONTRACTS['gemini'] = agy --output-format json models);
     2. REUSE_VERIFIED_SESSION: recorded, no login. ATTENDED_LOGIN_REQUIRED: reviewed history, owner
        READY prompt, then ONE attended login child (gemini: the agy login bridge wrapper
        login_pipeline_worker_interactive_agy_r4_v1.ps1 -Slot <slot> -LoginMode <mode> -CaptureAttempt <attempt>
        -Apply -Interactive; -LoginMode must equal login-mode.json of the signed-out AgyCapture of the same -Attempt;
        an exit 0 counts only with a bound receipt.json and session-result.json and no session-held.json);
     3. the status leaf again with -Stage after, which must return REUSE_VERIFIED_SESSION.
   A slot waits on its login child with no timeout of its own (the wrapper ends at 14 minutes, its task at PT15M).
   The generic series functions and the status-first machine are imported unchanged by hash from r3-v6.
   Exit codes: 0 = plan printed, or series complete (series-complete.json lists every slot's before and
   after status); 20 = orderly pause (owner PAUSE, or a rate-limit / identity-verification / appeal
   message from Google or agy), series-paused.json; any other exit (an uncaught refusal) = refused before
   any change, or held after the series root exists (series-held.json). A held or paused series stops at
   that slot, starts no later slot and is never resumed or retried; under addendum A4 Gemini stays held.
   Never: model jobs, daemon starts, retries, resumes, kills, deletes, or provider/account text in a record. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('codex','claude','gemini')][string]$Provider,
    # No [ValidateSet] on -LoginMode: Set-SeriesConstants writes $script:LoginMode='' for claude and codex, and a validated
    # parameter variable rejects that value (2026-10-11 r5 sitting). Get-LoginModeRefusal enforces print|tui, gemini only.
    [string]$LoginMode,
    [switch]$Apply,
    [switch]$Interactive,
    [ValidatePattern('^[a-f0-9]{32}$')][string]$Attempt='00000000000000000000000000000000'
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

function Set-SeriesConstants {
    param([string]$Provider,[string]$Attempt,[string]$ScriptRoot,[string]$LoginMode,[string]$Base='C:\Program Files\CoChem')
    $script:Provider=$Provider;$script:Attempt=$Attempt;$script:LoginMode=$LoginMode
    $script:programFiles='C:\Program Files';$script:base=$Base
    $script:installRoot=Join-Path $Base 'Pipeline4.2.7-windows-20261009-r4'
    $script:basePythonRoot=Join-Path $Base 'Toolchain4.2.7-windows-20261006\Python312';$script:basePython=Join-Path $script:basePythonRoot 'python.exe'
    $script:nativeRoot=Join-Path $Base 'Native4.2.7-windows-20261006'
    $script:powershell='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    $script:basePythonPin='d8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa'
    $script:venvConfigPin='0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d'
    $script:layoutPin='8430fdf1109c63c4a89479f03da8a465dfebf5566c7791c64f868202170672c4'
    $script:nativeExecutables=@{codex='codex.exe';claude='claude.exe';gemini='agy.exe'}
    $script:nativeHashes=@{codex='fdda5fa3cf3fb3d000b876720742857676293e4315e4b045fae6f8bd7e866d1d';claude='0e4195524b73eb77efbdf3e2b36de5322a29f0ca575dfd2d9b4f946b1d425469';gemini='38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741'}
    $script:native=Join-Path $script:nativeRoot $script:nativeExecutables[$Provider];$script:nativeHash=$script:nativeHashes[$Provider]
    # Fixed namespace date (the build date of this re-issue); -Attempt selects the one-shot series root.
    $script:seriesNamespaceDate='20261011'
    $script:seriesRoot=Join-Path $Base ('NativeAuthSix4.2.7-windows-'+$script:seriesNamespaceDate+'-r4-v1-'+$Attempt+'-'+$Provider)
    # Status leaf contract (wave-1 reviewed pins; the leaf fixes its own namespace date 20261010).
    $script:statusNamespaceDate='20261010'
    $script:statusLeaf=Join-Path $ScriptRoot 'check-worker-native-auth-status-six-r4-v1.ps1'
    $script:statusLeafHash='34612ac49eb2e455076a01607634f21d4f0b284714ef07d5e614146a1a9a7a85'
    $script:statusPythonName='worker-native-auth-status-six-r4-v1.py'
    $script:statusPython=Join-Path $ScriptRoot $script:statusPythonName
    $script:statusPythonHash='45681477194d97b144e8ee4505d4364d73d58aaef19c8428c846df642c834839'
    $script:statusTaskTimeLimit='PT3M';$script:statusMetadataLimit=65536;$script:statusReceiptLimit=32768
    # Reviewed function sources imported by hash (definitions only, never their actions).
    $script:copyHelper='C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1'
    $script:copyHelperPin='0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b'
    $script:statusFunctions=Join-Path $ScriptRoot 'check-worker-native-status-r3.ps1';$script:statusFunctionsPin='18f58ebb448d8a0c6329dd187d4a9a27fa9cbe942cd05e906bb7aabc67e787a7'
    $script:inspectionFunctions=Join-Path $ScriptRoot 'protected-code-inspection-v4.ps1';$script:inspectionFunctionsPin='5c01543cbb8b8d64b2b9f1bab4a13f87f8ff9e1ab3e82dfb6fc547144c77b95d'
    $script:seriesV6=Join-Path $ScriptRoot 'login-six-workers-status-first-r3-v6.ps1';$script:seriesV6Pin='9e45266bdccbaa7765245eb23091211b669c92504c374dd7ded6eab0699a4665'
    $script:claudeHelper=Join-Path $ScriptRoot 'login_pipeline_worker_interactive_r3_v6.ps1';$script:claudeHelperPin='837f567c5cae00d30620e313d746df6acf98259c9ffa1ef43ebc217b7cf9c46d'
    $script:claudeHistory=Join-Path $ScriptRoot 'claude-session-history-v6.ps1';$script:claudeHistoryPin='36cac78f54d9a9370991df3a83bfdf36144e7e9f8ed2dabe4da3105e5edd4636'
    $script:claudeBridge=Join-Path $ScriptRoot 'worker_claude_login_bridge_r3.py';$script:claudeBridgePin='b5bbede85ceb099460c6d6634f09a361a9b6617740eb082ab8d3bf5931260c73'
    $script:claudeSupport=Join-Path $ScriptRoot 'worker-native-status-r3.py';$script:claudeSupportPin='c3c3069f097040442777ea30a6296abc506783968e381611fce26e20c7c4aed5'
    $script:codexHelper=Join-Path $Base 'InstallGuard4.2.7-windows-20261006\repository\scripts\login_pipeline_worker.ps1'
    $script:codexHelperPin='e3d4d93f58446e05e4d585ac9215410527f8d1ec2a884153dbf69feb4ee7b32a'
    # AGY BRIDGE CONTRACT (reconciled with the final bridge; see also Invoke-AgyBridgeLogin, the only call site).
    # A pin that differs from the file on disk is a hold in the plan, and -Apply refuses before any change.
    $script:agyBridgeWrapper=Join-Path $ScriptRoot 'login_pipeline_worker_interactive_agy_r4_v1.ps1'
    $script:agyBridgeWrapperPin='381fb8daec6999d16e75ab163f28d0dda6459b1b44f9695962cf43213cedcb60'
    $script:agyBridgePython=Join-Path $ScriptRoot 'worker_agy_login_bridge_r4_v1.py'
    $script:agyBridgePythonPin='4074878f100ae59b804c95bd97b3280ccaa09f919ffaa365a3e2c6985045b8d9'
    $script:agyHistory=Join-Path $ScriptRoot 'agy-session-history-r4-v1.ps1'
    $script:agyHistoryPin='4e86b712314e2a6a8ea9f13e1dfcc9e65dda4035d2895b8043fbf6ceed0424d4'
    $script:agyHistoryFunctionNames=@('Get-AgyHistoryParent','Get-AgyHistoryPins','Get-AgyHistoryMarkerNames','Test-AgyHistoryInteger','Get-AgyHistoryValue',
        'Test-AgyHistoryProperty','Get-AgyHistorySafeReceiptMetadata','Assert-AgyHistoryPrivateAcl','Assert-AgyHistoryPrivateRoot','Get-AgyHistoryTaskArguments','Assert-AgyHistoryTask',
        'Assert-AgyHistoryProcess','Assert-AgyHistoryMarkers','Assert-AgyHistoryTokenStorage','Assert-AgyHistoryReceipt','Get-AgyHistoryExpectedSid','Get-AgyHistorySessionRecord','Assert-ReviewedAgyHistory')
    $script:agyBridgePauseExitCode=20
    $script:agyBridgeParent=$Base;$script:agyBridgeRootPrefix='InteractiveAgy427-r4-'
    $script:agyBridgeReceiptSchema='cochem-interactive-agy-login/1'
    $script:agyBridgeAcceptedStatuses=@('LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED','LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED')
    $script:agyBridgeKnownStatuses=@('LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED','LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED','LOGIN_COMMAND_FAILED','LOGIN_FAILED_OR_CANCELLED','CLEANUP_UNVERIFIED','UNVERIFIED')
    $script:agyBridgeLogLimitBytes=131072;$script:agyBridgeReceiptLimitBytes=32768
    # session-result.json as written by the wrapper's Invoke-AgyLoginApply for an accepted (exit 0) login.
    $script:agyBridgeResultSchema='cochem-interactive-agy-login-result/1';$script:agyBridgeResultLimitBytes=65536
    $script:agyBridgeAcceptedClassification='TERMINAL_NATIVE_LOGIN_CLEANUP_VERIFIED';$script:agyBridgeAcceptedOutcome='LOGIN_ENDED_STATUS_REQUIRED'
    # Signed-out capture of the same -Attempt; its login-mode.json fixes -LoginMode.
    $script:captureRoot=Join-Path $Base ('AgyCapture4.2.7-windows-20261010-r4-v1-'+$Attempt+'-slot1-signed-out')
    # Orderly-pause markers: exactly the bridge's BEFORE_PATTERNS for its PAUSE_MARKERS (worker_agy_login_bridge_r4_v1.py),
    # matched case-insensitively on the bridge operator.log text with '-'/'_' replaced by a space and whitespace collapsed
    # (the bridge's O-F8 normalisation); matched text is never recorded.
    $script:pauseMarkers=[ordered]@{rate_limit_present='\brate ?limit|too many requests|resource exhausted|quota exceeded|try again later|(?<![^\s(\["])429(?![^\s.,;:!?)\]"])';
        verification_present='\bverify\b|identity verification|account verification|verification required';appeal_present='\bappeal\b';unusual_activity_present='unusual activity'}
    $script:daemonTaskNames=@('CoChem-4.2.7-Warden','CoChem-4.2.7-Supervisor','CoChem-4.2.2-Warden','CoChem-4.2.3-Supervisor')
}

function Get-SeriesHelperDefinitions {
    param([string]$Provider)
    # Exact reviewed definitions only; the caller dot-sources them in its own scope.
    Import-ReviewedFunctions $script:copyHelper $script:copyHelperPin @('Assert-NoReparseAncestors','Assert-ProtectedPath','Initialize-FileIdentity','Open-VerifiedFile')
    Import-ReviewedFunctions $script:statusFunctions $script:statusFunctionsPin @('Read-R3Control','Read-R3Text','Assert-R3InstalledBindings')
    Import-ReviewedFunctions $script:statusLeaf $script:statusLeafHash @('Assert-R4InstalledBindings','Assert-VenvBinding','Assert-AuthStatusReceipt','Add-AuthStatusFailureMetadata')
    Import-ReviewedFunctions $script:claudeHelper $script:claudeHelperPin @('New-PrivateAcl','Get-ExactTaskOrAbsent')
    Import-ReviewedFunctions $script:inspectionFunctions $script:inspectionFunctionsPin @('Assert-CodeTreeOnce')
    Import-ReviewedFunctions $script:seriesV6 $script:seriesV6Pin @('Initialize-SeriesDirectory','Assert-SeriesPrivateRoot','Write-SeriesRecord','Get-SeriesWorkerRootHolds','Assert-SeriesDaemonsStopped','Invoke-SeriesConsoleChild','Show-CodexDeviceLoginInstructions','Confirm-AttendedLoginReady','Invoke-SixStatusFirst')
    if($Provider -ceq 'claude'){
        Import-ReviewedFunctions $script:claudeHistory $script:claudeHistoryPin @('Test-ClaudeHistoryInteger','Get-ClaudeHistoryValue','Get-ClaudeHistorySafeReceiptMetadata','Assert-ClaudeHistoryPrivateAcl','Assert-ClaudeHistoryPrivateRoot','Assert-ClaudeHistoryTask','Assert-ClaudeHistoryReceipt','Assert-ReviewedClaudeHistory')
    }
}

function Get-AgyHistoryDefinitions {
    if($script:agyHistoryPin -cnotmatch '^[a-f0-9]{64}$'){throw ('The reviewed agy session-history pin is pending reconcile: '+$script:agyHistory)}
    Import-ReviewedFunctions $script:agyHistory $script:agyHistoryPin $script:agyHistoryFunctionNames
}

function Get-SeriesHostFacts {
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    [pscustomobject]@{edition=[string]$PSVersionTable.PSEdition;is64=[Environment]::Is64BitProcess;computer=[string]$env:COMPUTERNAME;identity=[string]$identity.Name;
        administrator=[Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator);
        user_interactive=[Environment]::UserInteractive;input_redirected=[Console]::IsInputRedirected;output_redirected=[Console]::IsOutputRedirected;host_name=[string]$Host.Name}
}

function Get-SeriesApplyRefusal {
    param([bool]$ApplyRequested,[bool]$InteractiveRequested,$Facts)
    if($Facts.edition -cne 'Desktop' -or $Facts.is64 -ne $true -or $Facts.computer -cne 'AETHERDESK'){return 'Use 64-bit Windows PowerShell5.1 on AETHERDESK.'}
    if($ApplyRequested -and (-not $InteractiveRequested -or $Facts.administrator -ne $true -or $Facts.identity -cne 'AETHERDESK\ansac' -or $Facts.user_interactive -ne $true -or
       $Facts.input_redirected -ne $false -or $Facts.output_redirected -ne $false -or $Facts.host_name -cne 'ConsoleHost')){
        return 'Apply requires the owner at an elevated interactive ConsoleHost, with -Interactive and no redirected input/output.'}
    return $null
}

function Get-LoginModeRefusal {
    param([string]$Provider,[string]$LoginMode,[bool]$ApplyRequested)
    if($LoginMode -and $LoginMode -cnotin @('print','tui')){return '-LoginMode must be print or tui (the signed-out capture decision); nothing was changed.'}
    if($Provider -cne 'gemini' -and $LoginMode){return '-LoginMode applies only to -Provider gemini; nothing was changed.'}
    if($Provider -ceq 'gemini' -and $ApplyRequested -and -not $LoginMode){return 'Gemini -Apply requires -LoginMode print or tui equal to login-mode.json of the signed-out AgyCapture of this -Attempt; nothing was changed.'}
    return $null
}

function Get-SeriesHeldFiles {
    param([string]$Provider)
    # Held open (FileShare.Read) for the whole series so a reviewed file cannot change underneath it.
    $rows=@([pscustomobject]@{path=$script:statusPython;sha256=$script:statusPythonHash;protected=$false})
    switch -CaseSensitive ($Provider){
        'codex'{$rows+=[pscustomobject]@{path=$script:codexHelper;sha256=$script:codexHelperPin;protected=$true}}
        'claude'{$rows+=@([pscustomobject]@{path=$script:claudeBridge;sha256=$script:claudeBridgePin;protected=$false},[pscustomobject]@{path=$script:claudeSupport;sha256=$script:claudeSupportPin;protected=$false})}
        # The agy bridge support module is the status helper above (worker_native_status_support.py in the bridge root).
        'gemini'{$rows+=@([pscustomobject]@{path=$script:agyBridgeWrapper;sha256=$script:agyBridgeWrapperPin;protected=$false},[pscustomobject]@{path=$script:agyBridgePython;sha256=$script:agyBridgePythonPin;protected=$false},[pscustomobject]@{path=$script:agyHistory;sha256=$script:agyHistoryPin;protected=$false})}
    }
    $rows+=[pscustomobject]@{path=$script:native;sha256=$script:nativeHash;protected=$true}
    $rows
}

function Add-SeriesHeldFiles {
    param($Rows,$Held)
    $holds=@()
    foreach($row in @($Rows)){
        if($row.sha256 -cnotmatch '^[a-f0-9]{64}$'){$holds+=('Reviewed pin pending reconcile (the lead refreshes it after the bridge review): '+$row.path);continue}
        try{
            if(-not (Test-Path -LiteralPath $row.path -PathType Leaf)){throw 'the file is absent'}
            if($row.protected){Assert-ProtectedPath $row.path}
            $Held.Add((Open-VerifiedFile $row.path $row.sha256 (Get-Item -LiteralPath $row.path).Length))
        }catch{$holds+=('Reviewed file '+$row.path+' is absent or differs from its pin: '+$_.Exception.Message)}
    }
    $holds
}

function Get-SeriesRuntimeBindings {
    param([string]$Provider)
    $holds=@();$runtime=$null;$claudeRuntime=$null;$layout=$null
    try{
        $runtime=Assert-R4InstalledBindings
        Assert-VenvBinding (Read-R3Text (Read-R3Control (Join-Path $script:installRoot '.venv\pyvenv.cfg') $script:venvConfigPin))
        $null=Read-R3Control $script:basePython $script:basePythonPin
        $layout=(Read-R3Text (Read-R3Control (Join-Path $script:installRoot 'windows-layout.json') $script:layoutPin))|ConvertFrom-Json
    }catch{$runtime=$null;$layout=$null;$holds+=('r4 stopped runtime is not the reviewed build: '+$_.Exception.Message)}
    if($Provider -ceq 'claude'){
        # The unchanged Claude v6 child and its session history bind the r3 runtime.
        try{$claudeRuntime=Assert-R3InstalledBindings}catch{$holds+=('r3 runtime of the Claude login child is not the reviewed build: '+$_.Exception.Message)}
    }
    [pscustomobject]@{runtime=$runtime;claude_runtime=$claudeRuntime;layout=$layout;holds=@($holds)}
}

function Get-SeriesTaskFolder {
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect();$scheduler.GetFolder('\')
}

function Get-StatusLeafNamespace {
    param([string]$Slot,[string]$Stage)
    $suffix=$script:Attempt+'-'+$Slot+'-'+$script:Provider+'-'+$Stage
    $root=Join-Path $script:base ('NativeAuthStatusSix4.2.7-windows-'+$script:statusNamespaceDate+'-r4-v1-'+$suffix)
    [pscustomobject]@{root=$root;task=('CoChem-4.2.7-NativeAuthStatusSix-'+$script:statusNamespaceDate+'-r4-v1-'+$suffix);
        receipt=(Join-Path $root 'worker-native-status.json');helper=(Join-Path $root $script:statusPythonName)}
}

function Get-SeriesFreshHolds {
    param($Folder)
    if(Test-Path -LiteralPath $script:seriesRoot -ErrorAction Stop){'An earlier six-worker provider series root exists. Preserve it; no automatic repeat or resume.'}
    foreach($n in 1..6){foreach($stage in @('before','after')){
        $slot="slot$n";$ns=Get-StatusLeafNamespace $slot $stage
        if(Test-Path -LiteralPath $ns.root -ErrorAction Stop){"Existing status evidence for $slot/$stage must be preserved."}
        if($null -ne (Get-ExactTaskOrAbsent $Folder $ns.task)){"Existing status task for $slot/$stage must be preserved."}
    }}
}

function Get-SeriesPreflightHolds {
    param($Folder,$Layout)
    $holds=@()
    try{Assert-SeriesDaemonsStopped $Folder}catch{$holds+=('Protected daemons must remain stopped and disabled (unreadable task definitions are re-read during -Apply): '+$_.Exception.Message)}
    if($null -ne $Layout){try{$holds+=@(Get-SeriesWorkerRootHolds $Layout)}catch{$holds+=('Worker slot roots: '+$_.Exception.Message)}}
    try{$holds+=@(Get-SeriesFreshHolds $Folder)}catch{$holds+=('Series namespace: '+$_.Exception.Message)}
    $holds
}

function Assert-AgyLoginModeBinding {
    param([string]$Attempt,[string]$LoginMode)
    # -LoginMode must equal login-mode.json of the signed-out AgyCapture of the same -Attempt (gate passed).
    if($LoginMode -cnotin @('print','tui')){throw 'Gemini requires -LoginMode print or tui; no login was started.'}
    $root=$script:captureRoot
    if(-not (Test-Path -LiteralPath $root -PathType Container)){throw ('No signed-out AgyCapture exists for this -Attempt ('+$root+'); run the signed-out capture first. Gemini stays held; no login was started.')}
    if(Test-Path -LiteralPath (Join-Path $root 'capture-held.json')){throw 'The signed-out AgyCapture of this -Attempt is held. Gemini stays held; no login was started.'}
    $summaryControl=Read-R3Control (Join-Path $root 'capture-summary.json') '' 1048576
    $summary=(Read-R3Text $summaryControl)|ConvertFrom-Json
    if($summary.schema -cne 'cochem-agy-status-capture-result/1' -or $summary.attempt -cne $Attempt -or $summary.slot -cne 'slot1' -or $summary.stage -cne 'signed-out' -or
       $summary.decision -cne 'COMPLETE' -or $summary.gate.passed -isnot [bool] -or -not $summary.gate.passed -or $null -eq $summary.login_mode -or
       $summary.login_mode.sha256 -cnotmatch '^[a-f0-9]{64}$'){throw 'The signed-out AgyCapture of this -Attempt did not pass its gate. Gemini stays held; no login was started.'}
    $modeControl=Read-R3Control (Join-Path $root 'login-mode.json') $summary.login_mode.sha256 65536
    $file=(Read-R3Text $modeControl)|ConvertFrom-Json
    if($file.schema -cne 'cochem-agy-login-mode/1' -or $file.attempt -cne $Attempt -or $file.slot -cne 'slot1' -or $file.stage -cne 'signed-out' -or
       $file.mode -cne $summary.login_mode.mode){throw 'login-mode.json contradicts the signed-out capture summary. Gemini stays held; no login was started.'}
    if($file.mode -cnotin @('print','tui')){throw 'login-mode.json of this -Attempt decided mode none (no sign-in path). Gemini stays held; no login was started.'}
    if($file.mode -cne $LoginMode){throw ('-LoginMode '+$LoginMode+' differs from login-mode.json ('+$file.mode+') of the signed-out AgyCapture of this -Attempt; refused. No login was started.')}
    [ordered]@{capture_root=$root;capture_summary_sha256=$summaryControl.Sha256;login_mode_sha256=$modeControl.Sha256;mode=[string]$file.mode;decided_by=[string]$file.decided_by}
}

function Invoke-StatusLeafProcess {
    param([string]$Slot,[string]$Stage)
    # The only place the reviewed status leaf runs (its own -Apply path: one SYSTEM one-shot task).
    $savedPreference=$ErrorActionPreference
    try{
        $ErrorActionPreference='Continue'
        $output=@(& $script:powershell -NoLogo -NoProfile -NonInteractive -File $script:statusLeaf -Slot $Slot -Provider $script:Provider -Stage $Stage -Attempt $script:Attempt -Apply 2>&1)
        $code=$LASTEXITCODE
    }finally{$ErrorActionPreference=$savedPreference}
    [pscustomobject]@{text=(($output|ForEach-Object{[string]$_}) -join [Environment]::NewLine);code=$code}
}

function Get-StatusTaskResultView {
    param($Receipt,$Task)
    # The helper exits 2 for every HOLD classification (wave-1 finding on the leaf, line 187): require
    # exactly 2 there and present 0 to the imported binding so all of its other checks still apply.
    if($Receipt.status -cne 'STATUS_CHECK_FAILED' -and $Receipt.decision -ceq 'HOLD'){
        if($Task.LastTaskResult -ne 2){throw 'A HOLD status receipt requires task result 2.'}
        return [pscustomobject]@{LastTaskResult=0}
    }
    $Task
}

function Invoke-AuthStatusChild {
    param([string]$Slot,[string]$Stage)
    $run=Invoke-StatusLeafProcess $Slot $Stage
    $text=[string]$run.text;$code=$run.code
    if($text.Length -gt $script:statusMetadataLimit){throw 'Native status metadata exceeded its bound. Preserve its receipt/task; no login was started.'}
    if($code -ne 0){
        # Accept only the reviewed leaf's tagged summary, then verify the protected receipt/task again
        # before projecting it. Never echo stderr/provider output.
        $tag='COCHEM_NATIVE_AUTH_STATUS_RESULT '
        $lines=@($text -split '\r?\n'|Where-Object{$_.StartsWith($tag,[StringComparison]::Ordinal)})
        if($lines.Count -ne 1){throw 'Native status could not establish a bound failure receipt. Preserve its task/root; no login or automatic retry was started.'}
        $text=$lines[0].Substring($tag.Length)
    }
    try{$result=$text|ConvertFrom-Json}catch{throw 'Native status returned malformed metadata; no login is authorized.'}
    $ns=Get-StatusLeafNamespace $Slot $Stage
    if($result.attempt -cne $script:Attempt -or $result.schema -cne 'cochem-worker-native-auth-status-task-result/1' -or $result.slot -cne $Slot -or $result.provider -cne $script:Provider -or
       $result.stage -cne $Stage -or $result.nonce -cnotmatch '^[a-f0-9]{32}$' -or $result.receipt_sha256 -cnotmatch '^[a-f0-9]{64}$'){throw 'Native status summary does not bind the requested stage.'}
    if($result.receipt_path -cne $ns.receipt){throw 'Native status path differs.'}
    $task=Get-ExactTaskOrAbsent $script:taskFolder $ns.task
    if($null -eq $task -or $task.State -notin @(1,3) -or $task.GetInstances(0).Count -ne 0){throw 'Native status task is not terminal.'}
    $d=$task.Definition
    $argv='-I -B "'+$ns.helper+'" --slot '+$Slot+' --provider '+$script:Provider+' --nonce '+$result.nonce+' --stage '+$Stage+' --attempt '+$script:Attempt
    if($d.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or $d.Principal.LogonType -ne 5 -or $d.Principal.RunLevel -ne 1 -or $d.Triggers.Count -ne 0 -or $d.Actions.Count -ne 1 -or
       $d.Actions.Item(1).Path -cne (Join-Path $script:installRoot '.venv\Scripts\python.exe') -or $d.Actions.Item(1).Arguments -cne $argv -or $d.Actions.Item(1).WorkingDirectory -cne $ns.root -or
       $d.Settings.MultipleInstances -ne 2 -or $d.Settings.ExecutionTimeLimit -cne $script:statusTaskTimeLimit){throw 'Native status task action/identity differs.'}
    $null=Read-R3Control $ns.helper $script:statusPythonHash
    $control=Read-R3Control $result.receipt_path $result.receipt_sha256 $script:statusReceiptLimit
    $value=(Read-R3Text $control)|ConvertFrom-Json
    $decision=Assert-AuthStatusReceipt $value (Get-StatusTaskResultView $value $task) $script:runtime $Slot $script:Provider $Stage $result.nonce $script:statusPythonHash $script:Attempt
    if($code -ne 0 -or $decision -ceq 'HOLD'){
        if($value.status -cnotin @('STATUS_CHECK_FAILED','AUTHENTICATION_NOT_VERIFIED','NATIVE_SUBSCRIPTION_AUTHENTICATION_VERIFIED') -or $value.cleanup_verified -isnot [bool]){throw 'Failure receipt has invalid status metadata.'}
        $safe=[ordered]@{schema='cochem-worker-native-auth-status-task-result/1';attempt=$script:Attempt;slot=$Slot;provider=$script:Provider;stage=$Stage;nonce=$result.nonce;decision='HOLD';receipt_path=$result.receipt_path;receipt_sha256=$control.Sha256;status=$value.status;cleanup_verified=$value.cleanup_verified;last_task_result=$task.LastTaskResult;task_preserved=$true;pipeline_started=$false}
        Add-AuthStatusFailureMetadata $safe $value
        $script:lastStatusHold=$safe
        Write-Host ('COCHEM_NATIVE_AUTH_STATUS_RESULT '+($safe|ConvertTo-Json -Depth 5 -Compress))
        throw 'Native status did not establish reuse or explicit logout. Preserve the reported receipt; no login or automatic retry was started.'
    }
    if($decision -cnotin @('REUSE_VERIFIED_SESSION','ATTENDED_LOGIN_REQUIRED') -or $decision -cne $result.decision){throw 'Native status is not an established reuse or login decision.'}
    [pscustomobject]@{decision=$decision;stage=$Stage;receipt_path=$result.receipt_path;receipt_sha256=$control.Sha256}
}

function Assert-FreshClaudeLogin {
    param([string]$Slot)
    $null=@(Assert-ReviewedClaudeHistory -Slot $Slot -Folder $script:taskFolder -Runtime $script:claudeRuntime)
}

function Assert-FreshAgyLogin {
    param([string]$Slot)
    # Every earlier InteractiveAgy427-r4-<slot>-* session must be terminal and reviewed before a new one.
    $null=@(Assert-ReviewedAgyHistory -Slot $Slot -Folder $script:taskFolder -Runtime $script:runtime)
}

function Show-AgyLoginInstructions {
    param([string]$Slot)
    Write-Host ('Antigravity (agy) Google sign-in for the pipeline worker '+$Slot+' (login mode '+$script:LoginMode+').')
    Write-Host 'open the printed Google sign-in URL in your own browser now; paste the returned code at the masked prompt; Escape cancels'
    Write-Host 'Open the URL promptly: agy may wait only about 60 seconds for the consent.'
    Write-Host 'One slot can take up to about 15 minutes (the sign-in window closes after 14 minutes); the series waits for it and never ends it early.'
    Write-Host 'If Google asks you to verify your identity, offers an appeal, or reports a rate limit, press Escape; the series then pauses safely (exit 20) and Gemini stays held.'
}

function Invoke-ProviderLoginChild {
    param([string]$Slot)
    # codex: InstallGuard child with the r4 install root; claude: the unchanged r3-v6 interactive child.
    $arguments=@('-NoProfile','-File')
    if($script:Provider -ceq 'codex'){$arguments+=@($script:codexHelper,'-Slot',$Slot,'-Provider','codex','-Executable',(Join-Path $script:nativeRoot 'codex.exe'),'-InstallRoot',$script:installRoot)}
    else{$arguments+=@($script:claudeHelper,'-Slot',$Slot,'-Apply','-Interactive')}
    Invoke-SeriesConsoleChild $arguments
}

function Invoke-AgyBridgeLogin {
    param([string]$Slot,[string]$LoginMode)
    # THE ONLY AGY BRIDGE CALL: console child, no capture or redirection, and no timeout of its own (the wrapper
    # enforces 14 minutes and its task PT15M; nothing here ever ends it). -CaptureAttempt makes the wrapper re-read
    # the same signed-out login-mode.json (defence in depth over Assert-AgyLoginModeBinding).
    # Exit 0: accepted terminal login (receipt.json + session-result.json, checked by Get-AgyBridgeOutcome);
    # exit 20 ($script:agyBridgePauseExitCode): orderly pause; any other exit: the login did not complete.
    Invoke-SeriesConsoleChild @('-NoProfile','-File',$script:agyBridgeWrapper,'-Slot',$Slot,'-LoginMode',$LoginMode,'-CaptureAttempt',$script:Attempt,'-Apply','-Interactive')
}

function Get-AgyBridgeRoots {
    param([string]$Slot)
    @(Get-ChildItem -LiteralPath $script:agyBridgeParent -Directory -Force -Filter ($script:agyBridgeRootPrefix+$Slot+'-*') -ErrorAction Stop|ForEach-Object{$_.Name})
}

function Get-PauseMarkerClasses {
    param([string]$Text)
    # As the bridge (O-F8): replace '-' and '_' with a space, then collapse whitespace runs to one space, fold case and
    # search each pattern (rate-limited, RESOURCE_EXHAUSTED and too_many_requests all match).
    $folded=[regex]::Replace([regex]::Replace([string]$Text,'[-_]',' '),'\s+',' ').ToLowerInvariant()
    foreach($name in @($script:pauseMarkers.Keys)){if([regex]::IsMatch($folded,$script:pauseMarkers[$name],[Text.RegularExpressions.RegexOptions]::IgnoreCase)){$name}}
}

function Read-AgyOperatorLogText {
    param([string]$Path)
    # Bounded read for marker scanning only; the text is never returned to a record.
    Assert-NoReparseAncestors $Path
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
    try{
        if($stream.Length -gt $script:agyBridgeLogLimitBytes){throw 'Operator log exceeds its bound.'}
        $reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true,4096,$true)
        try{[pscustomobject]@{text=$reader.ReadToEnd();bytes=$stream.Length}}finally{$reader.Dispose()}
    }finally{$stream.Dispose()}
}

function Get-AgyBridgeOutcome {
    param([string]$Slot,[string[]]$Before,$ExitCode)
    # Safe projection of the new bridge session root: allowlisted receipt fields and marker classes only.
    $outcome=[ordered]@{wrapper_exit_code=$(if($ExitCode -is [int]){$ExitCode}else{$null});bridge_root=$null;bridge_nonce=$null;new_roots=0;
        receipt_present=$false;receipt_sha256=$null;receipt_bound=$false;receipt_status=$null;receipt_login_mode=$null;receipt_cleanup_verified=$null;
        session_result_present=$false;session_held_present=$false;session_result_bound=$false;session_result_sha256=$null;accepted=$false;
        operator_log_present=$false;operator_log_bytes=$null;operator_log_scanned=$false;pause_markers=@();pause_required=$false;raw_operator_text_recorded=$false}
    $new=@(@(Get-AgyBridgeRoots $Slot)|Where-Object{$_ -cnotin @($Before)})
    $outcome.new_roots=$new.Count
    $receipt=$null
    if($new.Count -eq 1 -and $new[0] -cmatch ('\A'+[regex]::Escape($script:agyBridgeRootPrefix+$Slot+'-')+'([a-f0-9]{32})\z')){
        $outcome.bridge_nonce=$Matches[1];$root=Join-Path $script:agyBridgeParent $new[0];$outcome.bridge_root=$root
        # Presence only for the wrapper's terminal records; content is read only for an exit-0 session-result.json.
        $resultPath=Join-Path $root 'session-result.json'
        $outcome.session_result_present=[bool](Test-Path -LiteralPath $resultPath -PathType Leaf)
        $outcome.session_held_present=[bool](Test-Path -LiteralPath (Join-Path $root 'session-held.json') -PathType Leaf)
        $log=Join-Path $root 'operator.log'
        if(Test-Path -LiteralPath $log -PathType Leaf){
            $outcome.operator_log_present=$true
            try{$read=Read-AgyOperatorLogText $log;$outcome.operator_log_bytes=$read.bytes;$outcome.pause_markers=@(Get-PauseMarkerClasses $read.text);$outcome.operator_log_scanned=$true}
            catch{$outcome.pause_markers=@('operator_log_unverified')}
            finally{$read=$null}
        }
        $receiptPath=Join-Path $root 'receipt.json'
        if(Test-Path -LiteralPath $receiptPath -PathType Leaf){
            $outcome.receipt_present=$true
            try{
                $control=Read-R3Control $receiptPath '' $script:agyBridgeReceiptLimitBytes;$receipt=(Read-R3Text $control)|ConvertFrom-Json
                $outcome.receipt_sha256=$control.Sha256
                if($receipt.schema -ceq $script:agyBridgeReceiptSchema -and $receipt.slot -ceq $Slot -and $receipt.nonce -ceq $outcome.bridge_nonce){
                    $outcome.receipt_bound=$true
                    $outcome.receipt_status=$(if($receipt.status -is [string] -and $receipt.status -cin $script:agyBridgeKnownStatuses){$receipt.status}else{'UNRECOGNIZED'})
                    if($receipt.login_mode -is [string] -and $receipt.login_mode -cin @('print','tui')){$outcome.receipt_login_mode=$receipt.login_mode}
                    if($receipt.cleanup_verified -is [bool]){$outcome.receipt_cleanup_verified=$receipt.cleanup_verified}
                    $seen=$receipt.PSObject.Properties['pause_marker_seen']
                    if($null -ne $seen -and $seen.Value -is [bool] -and $seen.Value){$outcome.pause_markers=@($outcome.pause_markers)+@('bridge_receipt_pause_marker')}
                }
            }catch{$outcome.receipt_bound=$false;$outcome.receipt_status=$null;$receipt=$null}
        }
        if($ExitCode -is [int] -and $ExitCode -eq 0 -and $outcome.receipt_bound -and $outcome.session_result_present -and -not $outcome.session_held_present){
            # The wrapper's exit-0 record (Invoke-AgyLoginApply): it must name this receipt, slot, nonce and an accepted outcome.
            try{
                $resultControl=Read-R3Control $resultPath '' $script:agyBridgeResultLimitBytes;$result=(Read-R3Text $resultControl)|ConvertFrom-Json
                $bound=($result.schema -ceq $script:agyBridgeResultSchema -and $result.slot -ceq $receipt.slot -and $result.nonce -ceq $receipt.nonce -and
                    $result.login_mode -ceq $receipt.login_mode -and $result.status -ceq $receipt.status -and $result.classification -ceq $script:agyBridgeAcceptedClassification -and
                    $result.outcome -ceq $script:agyBridgeAcceptedOutcome -and ($result.exit_code -is [int] -or $result.exit_code -is [long]) -and $result.exit_code -eq 0 -and
                    $result.receipt_sha256 -ceq $outcome.receipt_sha256 -and $result.cleanup_verified -is [bool] -and $result.cleanup_verified)
                $outcome.session_result_bound=[bool]$bound
                if($bound){$outcome.session_result_sha256=$resultControl.Sha256}
            }catch{$outcome.session_result_bound=$false}
            finally{$result=$null}
        }
    }
    if($ExitCode -is [int] -and $ExitCode -eq $script:agyBridgePauseExitCode){$outcome.pause_markers=@($outcome.pause_markers)+@('bridge_pause_exit')}
    $outcome.pause_required=(@($outcome.pause_markers).Count -gt 0)
    $outcome.accepted=($ExitCode -is [int] -and $ExitCode -eq 0 -and $outcome.receipt_bound -and $outcome.receipt_status -cin $script:agyBridgeAcceptedStatuses -and
        $outcome.receipt_cleanup_verified -eq $true -and $outcome.receipt_login_mode -ceq $script:LoginMode -and $outcome.session_result_bound -and -not $outcome.session_held_present)
    [pscustomobject]$outcome
}

function Confirm-OwnerReportedPause {
    param([string]$Slot)
    # Google shows verification and rate-limit pages in the browser, not in agy's output.
    $answer=Read-Host ('The '+$Slot+' sign-in did not complete. Type PAUSE if Google showed an identity-verification, appeal or rate-limit page (orderly pause, exit 20); anything else records the slot as held')
    return ($answer -ceq 'PAUSE')
}

function Initialize-SeriesState {
    $script:slotTable=[ordered]@{}
    foreach($n in 1..6){$script:slotTable["slot$n"]=[ordered]@{slot="slot$n";outcome='NOT_STARTED';before=$null;after=$null;login_commands_executed=0;bridge=$null}}
    $script:authResults=[Collections.Generic.List[object]]::new();$script:loginCount=0;$script:reusedCount=0
    $script:pendingPause=$null;$script:pausedSlot=$null;$script:pausedProof=$null;$script:pauseReason=$null;$script:lastStatusHold=$null;$script:currentSlot=$null
}

function Get-SeriesSlotRows {
    foreach($key in @($script:slotTable.Keys)){
        $row=$script:slotTable[$key];$final=$null
        if($null -ne $row.after){$final=$row.after.decision}elseif($null -ne $row.before -and $row.before.decision -ceq 'REUSE_VERIFIED_SESSION'){$final='REUSE_VERIFIED_SESSION'}
        [pscustomobject][ordered]@{slot=$row.slot;outcome=$row.outcome;before=$row.before;after=$row.after;final_decision=$final;reuse_verified=($final -ceq 'REUSE_VERIFIED_SESSION');
            login_commands_executed=$row.login_commands_executed;bridge=$row.bridge}
    }
}

function Invoke-SeriesStatusHook {
    param([string]$slot,[string]$stage)
    $script:currentSlot=$slot;$script:seriesPhase=$(if($stage -ceq 'before'){'status_before'}else{'status_after'});$script:lastStatusHold=$null
    Assert-SeriesDaemonsStopped $script:taskFolder
    $row=$script:slotTable[$slot]
    try{$result=Invoke-AuthStatusChild $slot $stage}
    catch{$row[$stage]=[ordered]@{decision='HOLD';stage=$stage;receipt_bound=$false;summary=$script:lastStatusHold};throw}
    $row[$stage]=[ordered]@{decision=$result.decision;stage=$stage;receipt_path=$result.receipt_path;receipt_sha256=$result.receipt_sha256}
    $result
}

function Invoke-SeriesReadyHook {
    param([string]$slot)
    $script:seriesPhase='ready'
    if($null -ne $script:pendingPause){
        # Between slots: a verification, appeal or rate-limit message was seen; start no further consent.
        $script:pauseReason=$script:pendingPause.reason
        Write-Host ('A rate-limit, identity-verification or appeal message was seen during '+$script:pendingPause.slot+'; pausing before the '+$slot+' login.')
        return $false
    }
    if($script:Provider -ceq 'claude'){Assert-FreshClaudeLogin $slot}
    if($script:Provider -ceq 'gemini'){Assert-FreshAgyLogin $slot;Show-AgyLoginInstructions $slot}
    $ready=Confirm-AttendedLoginReady $slot $script:Provider
    if(-not $ready){$script:pauseReason='OWNER_PAUSED_BEFORE_LOGIN'}
    return [bool]$ready
}

function Invoke-SeriesLoginHook {
    param([string]$slot)
    $script:seriesPhase='login'
    Assert-SeriesDaemonsStopped $script:taskFolder
    if($script:Provider -ceq 'claude'){Assert-FreshClaudeLogin $slot}
    if($script:Provider -ceq 'gemini'){Assert-FreshAgyLogin $slot}
    Write-Host ('The selected '+$script:Provider+' worker '+$slot+' is explicitly logged out. Follow the provider browser instructions for this profile.')
    $script:loginCount++;$row=$script:slotTable[$slot];$row.login_commands_executed=1
    if($script:Provider -cne 'gemini'){return (Invoke-ProviderLoginChild $slot)}
    $before=@(Get-AgyBridgeRoots $slot)
    $code=Invoke-AgyBridgeLogin $slot $script:LoginMode
    $outcome=Get-AgyBridgeOutcome $slot $before $code
    if($code -isnot [int] -or $code -ne 0){
        if(-not $outcome.pause_required -and (Confirm-OwnerReportedPause $slot)){$outcome.pause_markers=@('owner_reported');$outcome.pause_required=$true}
    }
    $row.bridge=$outcome
    Write-SeriesRecord (Join-Path $script:seriesRoot "$slot-LOGIN_BRIDGE_OUTCOME.json") ([ordered]@{schema='cochem-six-worker-agy-bridge-outcome/1';attempt=$script:Attempt;provider=$script:Provider;slot=$slot;nonce=$script:nonce;bridge=$outcome;observed_utc=[DateTime]::UtcNow.ToString('o');raw_provider_output_recorded_by_series=$false})
    if($outcome.pause_required){
        $reason=$(if(@($outcome.pause_markers) -ceq 'owner_reported'){'OWNER_REPORTED_RATE_LIMIT_OR_IDENTITY_VERIFICATION'}else{'RATE_LIMIT_OR_IDENTITY_VERIFICATION'})
        $script:pendingPause=[ordered]@{slot=$slot;reason=$reason;markers=@($outcome.pause_markers)}
    }
    if($code -is [int] -and $code -eq 0 -and -not $outcome.accepted){throw 'The agy sign-in exited 0 without a bound accepted bridge receipt. Preserve evidence; Gemini stays held and no later slot was started.'}
    return $code
}

function Invoke-SeriesRecordHook {
    param([string]$slot,[string]$state,$proof)
    Write-SeriesRecord (Join-Path $script:seriesRoot "$slot-$state.json") ([ordered]@{schema='cochem-six-worker-auth-event/1';attempt=$script:Attempt;provider=$script:Provider;slot=$slot;nonce=$script:nonce;state=$state;proof=$proof;observed_utc=[DateTime]::UtcNow.ToString('o');raw_provider_output_recorded_by_series=$false})
    $script:slotTable[$slot].outcome=$state
    if($state -cin @('REUSED_VERIFIED_SESSION','AUTHENTICATED_AFTER_LOGIN')){$script:authResults.Add([pscustomobject]@{slot=$slot;status=$state;proof=$proof})}
    if($state -ceq 'REUSED_VERIFIED_SESSION'){$script:reusedCount++}
    if($state -ceq 'PAUSED_BEFORE_LOGIN'){$script:pausedSlot=$slot;$script:pausedProof=$proof}
}

function Get-SeriesPauseConversion {
    # A failure of the slot whose bridge output (or owner) reported a rate limit / verification is an orderly pause.
    if($null -eq $script:pendingPause -or $script:pendingPause.slot -cne $script:currentSlot -or $script:seriesPhase -cnotin @('login','status_after')){return $null}
    $script:pauseReason=$script:pendingPause.reason
    $script:pendingPause
}

function New-SeriesPausedRecord {
    param([string]$Status,[string]$Slot,$Proof)
    $markers=@();$markerSlot=$null
    if($null -ne $script:pendingPause){$markers=@($script:pendingPause.markers);$markerSlot=$script:pendingPause.slot}
    if($Slot -cnotin @('slot1','slot2','slot3','slot4','slot5','slot6')){throw 'The paused slot is unknown.'}
    if($null -eq $Proof){$Proof=$script:slotTable[$Slot].before}
    if($Status -ceq 'AUTHENTICATION_PAUSED_AFTER_LOGIN'){$script:slotTable[$Slot].outcome='PAUSED_AFTER_LOGIN'}
    [ordered]@{schema='cochem-six-worker-status-first-paused/1';attempt=$script:Attempt;status=$Status;provider=$script:Provider;nonce=$script:nonce;runtime=$script:runtime;
        paused_slot=$Slot;pause_reason=$script:pauseReason;pause_markers=$markers;marker_slot=$markerSlot;before_status_proof=$Proof;
        login_mode=$(if($script:LoginMode){$script:LoginMode}else{$null});configuration_applied=$false;login_commands_executed=$script:loginCount;existing_sessions_reused=$script:reusedCount;
        status_receipts=@($script:authResults.ToArray());slots=@(Get-SeriesSlotRows);model_jobs_executed=0;pipeline_started=$false;activation_ready=$false;
        gemini_held=($script:Provider -ceq 'gemini');later_slots_started=$false;series_preserved=$true;automatic_retry_allowed=$false;exit_code=20;paused_utc=[DateTime]::UtcNow.ToString('o')}
}

function New-SeriesHeldRecord {
    param([string]$ErrorType)
    $reason=switch -CaseSensitive ($script:seriesPhase){'status_before'{'BEFORE_STATUS_NOT_ESTABLISHED'}'ready'{'READINESS_OR_HISTORY_REFUSED'}'login'{'LOGIN_NOT_COMPLETED'}'status_after'{'AFTER_STATUS_NOT_VERIFIED'}default{'SERIES_FAILURE'}}
    $heldSlot=$(if($script:seriesPhase -cin @('status_before','ready','login','status_after')){$script:currentSlot}else{$null})
    if($null -ne $heldSlot){$script:slotTable[$heldSlot].outcome='HELD'}
    [ordered]@{schema='cochem-six-worker-status-first-held/1';attempt=$script:Attempt;status='AUTHENTICATION_HELD';provider=$script:Provider;nonce=$script:nonce;runtime=$script:runtime;
        held_slot=$heldSlot;phase=$script:seriesPhase;held_reason=$reason;error_type=$ErrorType;login_mode=$(if($script:LoginMode){$script:LoginMode}else{$null});
        configuration_applied=$false;login_commands_executed=$script:loginCount;existing_sessions_reused=$script:reusedCount;status_receipts=@($script:authResults.ToArray());
        slots=@(Get-SeriesSlotRows);model_jobs_executed=0;pipeline_started=$false;activation_ready=$false;gemini_held=($script:Provider -ceq 'gemini');later_slots_started=$false;
        series_preserved=$true;automatic_resume_allowed=$false;failed_utc=[DateTime]::UtcNow.ToString('o')}
}

function New-SeriesCompleteRecord {
    $rows=@(Get-SeriesSlotRows)
    [ordered]@{schema='cochem-six-worker-status-first-result/1';attempt=$script:Attempt;status='SIX_CONFIGURED_WORKERS_SUBSCRIPTION_AUTHENTICATION_VERIFIED';provider=$script:Provider;nonce=$script:nonce;
        runtime=$script:runtime;configuration_applied=$false;selected_workers_verified=6;other_accounts_preserved=$true;login_commands_executed=$script:loginCount;existing_sessions_reused=$script:reusedCount;
        status_receipts=@($script:authResults.ToArray());slots=$rows;all_slots_reuse_verified=(@($rows|Where-Object{$_.reuse_verified -eq $true}).Count -eq 6);
        login_mode=$(if($script:LoginMode){$script:LoginMode}else{$null});login_mode_binding=$script:loginModeBinding;model_jobs_executed=0;serving_model_verified=$false;
        provider_account_identity_verified=$false;activation_ready=$false;completed_utc=[DateTime]::UtcNow.ToString('o');series_preserved=$true}
}

function New-SeriesRoot {
    param([string]$Path)
    Assert-ProtectedPath (Split-Path -Parent $Path);Initialize-SeriesDirectory
    [CoChemNativeLoginSeriesDirectory]::Create($Path);Assert-SeriesPrivateRoot $Path
}

function Invoke-LoginSeriesMain {
    param([string]$Provider,[string]$LoginMode,[bool]$ApplyRequested,[bool]$InteractiveRequested,[string]$Attempt,[string]$ScriptRoot)
    if($Attempt -cnotmatch '^[a-f0-9]{32}$' -or ($ApplyRequested -and $Attempt -ceq '00000000000000000000000000000000')){throw 'A lowercase32-hex Attempt is required; Apply forbids the all-zero preview attempt.'}
    $ErrorActionPreference='Stop';Set-StrictMode -Version Latest
    $Provider=([string]$Provider).ToLowerInvariant();$LoginMode=([string]$LoginMode).ToLowerInvariant()
    if($Provider -cnotin @('codex','claude','gemini')){throw 'Only the reviewed codex, claude and gemini login series are supported.'}
    $modeRefusal=Get-LoginModeRefusal $Provider $LoginMode $ApplyRequested;if($null -ne $modeRefusal){throw $modeRefusal}
    foreach($m in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$m\$m.psd1") -ErrorAction Stop}
    $refusal=Get-SeriesApplyRefusal $ApplyRequested $InteractiveRequested (Get-SeriesHostFacts);if($null -ne $refusal){throw $refusal}
    Set-SeriesConstants $Provider $Attempt $ScriptRoot $LoginMode
    foreach($text in @(Get-SeriesHelperDefinitions $Provider)){. ([scriptblock]::Create($text))}
    Initialize-FileIdentity
    $held=[Collections.Generic.List[IO.FileStream]]::new()
    $ownsRoot=$false;$script:nonce=$null;$script:seriesPhase='preflight';$script:loginModeBinding=$null;$script:runtime=$null;$script:claudeRuntime=$null
    try{
        $bindings=Get-SeriesRuntimeBindings $Provider
        $script:runtime=$bindings.runtime;$script:claudeRuntime=$bindings.claude_runtime
        $holds=@($bindings.holds)
        $holds+=@(Add-SeriesHeldFiles @(Get-SeriesHeldFiles $Provider) $held)
        $script:taskFolder=Get-SeriesTaskFolder
        $holds+=@(Get-SeriesPreflightHolds $script:taskFolder $bindings.layout)
        if($Provider -ceq 'gemini'){
            if(-not $LoginMode){$holds+='Gemini requires -LoginMode print or tui equal to login-mode.json of the signed-out AgyCapture of this -Attempt.'}
            else{try{$script:loginModeBinding=Assert-AgyLoginModeBinding $Attempt $LoginMode}catch{$holds+=$_.Exception.Message}}
            try{foreach($text in @(Get-AgyHistoryDefinitions)){. ([scriptblock]::Create($text))}}catch{$holds+=('Reviewed agy session history: '+$_.Exception.Message)}
        }
        if(-not $ApplyRequested){
            [ordered]@{schema='cochem-six-worker-status-first-plan/1';attempt=$Attempt;mode='READ_ONLY_PLAN';provider=$Provider;selected_workers=@('slot1','slot2','slot3','slot4','slot5','slot6');
                shared_capacity=4;runtime=$script:runtime;configuration_applied=$false;series_root=$script:seriesRoot;human_console_required=$true;browser_login_only_for_explicit_logged_out_status=$true;
                maximum_logins=6;actual_logins_required=$null;no_automatic_repeat_or_resume=$true;native_commands_executed=0;model_jobs_executed=0;activation_ready=$false;holds=@($holds);
                login_mode=$(if($LoginMode){$LoginMode}else{$null});login_mode_binding=$script:loginModeBinding;
                login_child=[ordered]@{path=$(switch -CaseSensitive ($Provider){'codex'{$script:codexHelper}'claude'{$script:claudeHelper}default{$script:agyBridgeWrapper}});sha256=$(switch -CaseSensitive ($Provider){'codex'{$script:codexHelperPin}'claude'{$script:claudeHelperPin}default{$script:agyBridgeWrapperPin}})};
                status_leaf=[ordered]@{path=$script:statusLeaf;sha256=$script:statusLeafHash;helper_sha256=$script:statusPythonHash};
                daemon_tasks_required_stopped=@($script:daemonTaskNames);exit_codes=[ordered]@{completed=0;orderly_pause=20}}|ConvertTo-Json -Depth 8
            return
        }
        if($holds.Count){throw ('The login series is held. Nothing was changed: '+($holds -join ' | '))}
        $null=Assert-CodeTreeOnce $script:installRoot;$null=Assert-CodeTreeOnce $script:basePythonRoot;$null=Assert-CodeTreeOnce $script:nativeRoot
        Assert-SeriesDaemonsStopped $script:taskFolder
        $fresh=@(Get-SeriesWorkerRootHolds $bindings.layout)+@(Get-SeriesFreshHolds $script:taskFolder);if($fresh.Count){throw ($fresh -join ' ')}
        if($Provider -ceq 'gemini'){$script:loginModeBinding=Assert-AgyLoginModeBinding $Attempt $LoginMode}
        Initialize-SeriesState
        New-SeriesRoot $script:seriesRoot;$ownsRoot=$true
        $script:nonce=[Guid]::NewGuid().ToString('N')
        Write-SeriesRecord (Join-Path $script:seriesRoot 'series-start.json') ([ordered]@{schema='cochem-six-worker-status-first/1';attempt=$Attempt;status='IN_PROGRESS';provider=$Provider;nonce=$script:nonce;runtime=$script:runtime;
            login_mode=$(if($LoginMode){$LoginMode}else{$null});login_mode_binding=$script:loginModeBinding;configuration_applied=$false;started_utc=[DateTime]::UtcNow.ToString('o');activation_ready=$false})
        $script:seriesPhase='status_first_authentication'
        $completed=Invoke-SixStatusFirst ${function:Invoke-SeriesStatusHook} ${function:Invoke-SeriesLoginHook} ${function:Invoke-SeriesRecordHook} ${function:Invoke-SeriesReadyHook}
        $script:seriesPhase='completion'
        Assert-SeriesDaemonsStopped $script:taskFolder
        if(-not $completed){
            $paused=New-SeriesPausedRecord 'AUTHENTICATION_PAUSED_BEFORE_LOGIN' $script:pausedSlot $script:pausedProof
            Write-SeriesRecord (Join-Path $script:seriesRoot 'series-paused.json') $paused
            $paused|ConvertTo-Json -Depth 10
            exit 20
        }
        if($script:authResults.Count -ne 6){throw 'Six configured workers were not authenticated.'}
        $result=New-SeriesCompleteRecord
        Write-SeriesRecord (Join-Path $script:seriesRoot 'series-complete.json') $result
        $result|ConvertTo-Json -Depth 10
    }catch{
        $failure=$_
        if($ownsRoot){
            $paused=$null
            try{$pause=Get-SeriesPauseConversion;if($null -ne $pause){$paused=New-SeriesPausedRecord 'AUTHENTICATION_PAUSED_AFTER_LOGIN' $pause.slot $null;Write-SeriesRecord (Join-Path $script:seriesRoot 'series-paused.json') $paused}}catch{$paused=$null}
            if($null -ne $paused){$paused|ConvertTo-Json -Depth 10;exit 20}
            try{Write-SeriesRecord (Join-Path $script:seriesRoot 'series-held.json') (New-SeriesHeldRecord $failure.Exception.GetType().Name)}catch{}
        }
        throw $failure
    }finally{foreach($stream in $held){if($null -ne $stream){$stream.Dispose()}}}
}

# Invocation boundary: the only top-level statement. Fixtures dot-source the functions above from the AST without running it.
Invoke-LoginSeriesMain -Provider $Provider -LoginMode $LoginMode -ApplyRequested ([bool]$Apply) -InteractiveRequested ([bool]$Interactive) -Attempt $Attempt -ScriptRoot $PSScriptRoot
