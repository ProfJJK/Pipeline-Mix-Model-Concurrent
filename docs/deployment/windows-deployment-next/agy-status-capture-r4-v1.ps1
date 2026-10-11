#Requires -Version 5.1
<# Slot1 agy discovery capture under the worker token (Gemini build-manifest step 2, decisions 1B/2B/3B).
   Derived from check-worker-native-auth-status-six-r3-v4.ps1 (sha256 4448e76e...: preconditions, one-shot SYSTEM task
   registration and wait, receipt handling) and the house pattern of retarget-warden-r4.ps1 v2.2 (sha256 8ee6b412...:
   Import-ReviewedFunctions, r4 bindings, private directories). Every reviewed helper is imported by hash; the top level is
   a single invocation so fixtures can dot-source the functions from the AST without running anything.
   Default is a read-only plan (cochem-agy-status-capture-plan/1); it creates nothing and runs no native command.
   -Apply (AETHERDESK\ansac in elevated 64-bit Windows PowerShell 5.1, nonzero -Attempt):
     1. binds the reviewed r4 runtime (v2.2 bindings plus install receipt 629c87ec..., revision 38a99c3f..., layout,
        windows.py, resource_limits.py and the preserved-denial pin), the agy.exe pin 38f30c7d... and this helper's pin;
        requires the four daemon tasks stopped and disabled, no existing capture root or task, and inspects the r4,
        toolchain and native code trees once (Assert-CodeTreeOnce);
     2. creates C:\Program Files\CoChem\AgyCapture4.2.7-windows-20261010-r4-v1-<attempt>-slot1-<stage> with a SYSTEM/BA-only
        DACL (raw native output may hold the account email once signed in), copies the hash-pinned helper and writes
        capture-intent.json before any task exists;
     3. registers ONE trigger-free SYSTEM task CoChem-4.2.7-AgyCapture-20261010-r4-v1-<attempt>-slot1-<stage> (PT5M, private
        task DACL), requests exactly one Run and waits for it to end;
     4. verifies capture-receipt.json (cochem-agy-status-capture/1) against the pins, the probe table, the raw-file digests and
        login-mode.json, recomputes the login-mode decision and the orchestrator gate, and writes capture-summary.json.
   Stage signed-out runs P1-P8 (P3 '-p /model' and P6 bare agy get a held-open stdin pipe for 20 s that is never written,
   then the owned Job ends them: each may mint and abandon one OAuth URL, named in the owner sheet). Stage signed-in runs
   P1, P2, P2b, P7, P8, P3, P4, P5 with empty stdin files. No model inference, login input, credential read or token-file
   open occurs. The gate fails -> the summary is printed with a SERIES-STOP message and the script exits non-zero. Any
   failure after the root exists leaves capture-held.json. Nothing is ever retried, deleted, stopped or killed; the task and
   the root are preserved as evidence. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('slot1')][string]$Slot,
    [Parameter(Mandatory=$true)][ValidateSet('signed-out','signed-in')][string]$Stage,
    [ValidatePattern('^[a-f0-9]{32}$')][string]$Attempt='00000000000000000000000000000000',
    [switch]$Apply
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

function Set-CaptureConstants {
    param([string]$Slot,[string]$Stage,[string]$Attempt,[string]$Workspace)
    $script:Slot=$Slot;$script:Stage=$Stage;$script:Attempt=$Attempt;$script:workspace=$Workspace
    # The v2.2 pin block (values unchanged) used by the imported Assert-R4InstalledBindings.
    $script:programFiles='C:\Program Files';$script:base=Join-Path $script:programFiles 'CoChem'
    $script:r3Root=Join-Path $script:base 'Pipeline4.2.7-windows-20261007-r3'
    $script:r4Root=Join-Path $script:base 'Pipeline4.2.7-windows-20261009-r4';$script:r4Python=Join-Path $script:r4Root '.venv\Scripts\python.exe'
    $script:basePythonRoot=Join-Path $script:base 'Toolchain4.2.7-windows-20261006\Python312';$script:basePython=Join-Path $script:basePythonRoot 'python.exe'
    $script:probePythonPin='d8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa'
    $script:configPin='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
    $script:r3ManifestPin='6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1';$script:r3InstallPin='3b613128192ac44a0a3d9c4b4476fb4c47541edb7563541b9bbf18f84f9a90f6'
    $script:r3RevisionPin='309eb48d9b1c43179ae1f0784d0139357168314f8312a64fb84dbd8380d44eb4'
    $script:r4ManifestPin='1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189';$script:repairPin='e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc'
    # The manifest's further r4 pins (install-after key names verified on disk).
    $script:r4InstallPin='629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502';$script:r4RevisionPin='38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e'
    $script:r4LayoutPin='8430fdf1109c63c4a89479f03da8a465dfebf5566c7791c64f868202170672c4';$script:windowsPin='ca07b3bba2b22d0eb095c1f05b9a6c0969207bf7d8b25741adbaee184f4618ba'
    $script:resourcePin='de7fac91e32cef2f854bd53487037352bbc0915f95aaf987ee8a4a543317915f';$script:preservedDenialPin='691c70560436f948464c529b9d2d6a3e33ce240749642af86ca79c748791461d'
    $script:venvConfigPin='0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d';$script:venvPythonPin='560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'
    $script:nativeRoot=Join-Path $script:base 'Native4.2.7-windows-20261006';$script:nativeExecutable=Join-Path $script:nativeRoot 'agy.exe'
    $script:agyPin='38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741';$script:agyVersion='1.3.1'
    $script:helperName='agy_status_capture_r4_v1.py';$script:helperSource=Join-Path $Workspace $script:helperName
    $script:helperPin='ce103aad0f9dae042677ec61c2b16eb5512e9a24f5fca65bc97f4570bb884038'
    # Fixed namespace date (the build date), as v2.2 fixes its own; the helper refuses any other root name.
    $script:captureNamespaceDate='20261010'
    $script:targetRoot=Join-Path $script:base ('AgyCapture4.2.7-windows-'+$script:captureNamespaceDate+'-r4-v1-'+$Attempt+'-'+$Slot+'-'+$Stage)
    $script:taskName='CoChem-4.2.7-AgyCapture-'+$script:captureNamespaceDate+'-r4-v1-'+$Attempt+'-'+$Slot+'-'+$Stage
    $script:taskSddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)';$script:taskTimeLimit='PT5M';$script:taskWaitSeconds=295
    $script:daemonTaskNames=@('CoChem-4.2.7-Warden','CoChem-4.2.7-Supervisor','CoChem-4.2.2-Warden','CoChem-4.2.3-Supervisor')
    $script:workerIdentity='CoChem422Worker1';$script:workerProfile='C:\Users\CoChem422Worker1'
    $script:inventoryRoots=@('C:\Users\CoChem422Worker1\.gemini','C:\Users\CoChem422Worker1\AppData\Local\agy')
    $script:probeTimeoutSeconds=30;$script:windowSeconds=20;$script:outputLimitBytes=65536
    $script:receiptMaxBytes=1048576;$script:rawMaxBytes=16777216;$script:emptySha256='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
    $script:failurePhases=@('trusted_preflight','reservation','runtime_custody','layout','boundaries','native_custody','daemon_precheck','inventory_before','native_launch',
        'native_attestation','native_wait','native_cleanup','native_result','inventory_after','daemon_postcheck','login_mode')
}

function Get-ExpectedProbes {
    param([string]$Stage)
    # Mirrors PROBES/STAGE_PROBES of the helper (a test compares both tables).
    $arguments=@{P1=@('--version');P2=@('--output-format','json','models');P2b=@('models');P3=@('-p','/model');P4=@('-p','/usage');
        P5=@('--output-format','json','-p','/usage');P6=@();P7=@('--output-format','json','agents');P8=@('agents')}
    $order=if($Stage -ceq 'signed-out'){@('P1|empty_file','P2|empty_file','P2b|empty_file','P3|held_open_pipe','P4|empty_file','P5|empty_file','P6|held_open_pipe','P7|empty_file','P8|empty_file')}
        else{@('P1|empty_file','P2|empty_file','P2b|empty_file','P7|empty_file','P8|empty_file','P3|empty_file','P4|empty_file','P5|empty_file')}
    foreach($row in $order){
        $id,$mode=$row.Split('|')
        [pscustomobject]@{id=$id;stdin_mode=$mode;arguments=@($arguments[$id]);bound_seconds=$(if($mode -ceq 'held_open_pipe'){$script:windowSeconds}else{$script:probeTimeoutSeconds})}
    }
}

function Get-CaptureTaskArguments {
    param([string]$Destination,[string]$Nonce)
    '-I -B "'+$Destination+'" --slot '+$script:Slot+' --stage '+$script:Stage+' --nonce '+$Nonce+' --attempt '+$script:Attempt
}

function New-CaptureNonce {[Guid]::NewGuid().ToString('N')}

function Get-SeriesDaemonTaskStates {
    param($Folder)
    # The four daemon names of the sign-in series precondition; observer/recorder tasks are deliberately not listed.
    $states=@()
    foreach($name in $script:daemonTaskNames){
        $task=$null;$absent=$false;$denied=$false
        try{$task=$Folder.GetTask($name)}catch{
            $errorItem=$_.Exception
            while($null -ne $errorItem){
                if($errorItem.HResult -eq -2147024894){$absent=$true;break}
                if($errorItem.HResult -eq -2147024891){$denied=$true;break}
                $errorItem=$errorItem.InnerException}
            if(-not $absent -and -not $denied){throw ('Daemon task state is unknown: '+$name)}}
        if($absent){$states+=[pscustomobject]@{name=$name;state='ABSENT';active=$false};continue}
        if($denied){$states+=[pscustomobject]@{name=$name;state='ACCESS_DENIED_DEFERRED';active=$null};continue}
        try{$active=([bool]$task.Enabled -or [int]$task.State -notin @(1,3) -or [int]$task.GetInstances(0).Count -ne 0)}catch{
            $errorItem=$_.Exception;$partial=$false
            while($null -ne $errorItem){if($errorItem.HResult -eq -2147024891){$partial=$true;break};$errorItem=$errorItem.InnerException}
            if(-not $partial){throw ('Daemon task could not be read: '+$name)}
            $states+=[pscustomobject]@{name=$name;state='ACCESS_DENIED_DEFERRED';active=$null};continue}
        $states+=[pscustomobject]@{name=$name;state=$(if($active){'ACTIVE'}else{'STOPPED_DISABLED'});active=$active}
    }
    $states
}

function Get-TaskPresence {
    param($Folder,[string]$Name)
    try{$null=$Folder.GetTask($Name);return 'PRESENT'}catch{
        $errorItem=$_.Exception
        while($null -ne $errorItem){
            if($errorItem.HResult -eq -2147024894){return 'ABSENT'}
            if($errorItem.HResult -eq -2147024891){return 'PRESENT_UNREADABLE'}
            $errorItem=$errorItem.InnerException}
        throw ('Task Scheduler state is unknown for '+$Name)}
}

function Assert-CaptureRuntimePins {
    param($Runtime)
    # The manifest's r4 pins beyond the v2.2 content bindings, with the real install-after key names.
    if($Runtime.install_receipt_sha256 -cne $script:r4InstallPin){throw 'The r4 installation receipt is not the pinned receipt.'}
    if($Runtime.revision_sha256 -cne $script:r4RevisionPin){throw 'The r4 installed revision is not the pinned revision.'}
    $after=(Read-R3Text (Read-R3Control (Join-Path $script:r4Root 'install-after.json') $script:r4InstallPin 1048576))|ConvertFrom-Json
    if($after.preserved_denial_receipt_sha256 -cne $script:preservedDenialPin -or $after.reviewed_repair_sha256 -cne $script:repairPin -or
       $after.previous_install_receipt_sha256 -cne $script:r3InstallPin -or $after.previous_source_manifest_sha256 -cne $script:r3ManifestPin -or
       $after.source_manifest_sha256 -cne $script:r4ManifestPin -or $after.configuration_sha256 -cne $script:configPin -or
       -not (Test-ExactInt $after.source_files 166) -or $after.mode -cne 'FRESH_STOPPED_RUNTIME_READY' -or
       $after.verification.revision.source_sha256 -cne $script:r4RevisionPin){throw 'The r4 install-after bindings differ from the manifest pins.'}
    $layout=Read-R3Control (Join-Path $script:r4Root 'windows-layout.json') $script:r4LayoutPin
    $null=Read-R3Control (Join-Path $script:r4Root '.venv\Lib\site-packages\cochem_pipeline\windows.py') $script:windowsPin
    $null=Read-R3Control (Join-Path $script:r4Root '.venv\Lib\site-packages\cochem_pipeline\resource_limits.py') $script:resourcePin
    [ordered]@{install_receipt_sha256=$Runtime.install_receipt_sha256;source_manifest_sha256=$Runtime.source_manifest_sha256;revision_sha256=$Runtime.revision_sha256;
        configuration_sha256=$script:configPin;layout_sha256=$layout.Sha256;windows_runtime_sha256=$script:windowsPin;resource_limits_sha256=$script:resourcePin;
        reviewed_repair_sha256=$script:repairPin;preserved_denial_receipt_sha256=$script:preservedDenialPin}
}

function New-CaptureTaskDefinition {
    param($Scheduler,[string]$Destination,[string]$Nonce)
    $definition=$Scheduler.NewTask(0)
    $definition.RegistrationInfo.Description='One bounded agy discovery capture (build-manifest step 2) in the slot1 worker profile: non-inference listings and two abandoned sign-in-path probes. No login input, model inference, daemon activation or credential copying.'
    $definition.Principal.UserId='SYSTEM';$definition.Principal.LogonType=5;$definition.Principal.RunLevel=1
    $definition.Settings.Enabled=$true;$definition.Settings.AllowDemandStart=$true
    $definition.Settings.MultipleInstances=2;$definition.Settings.ExecutionTimeLimit=$script:taskTimeLimit;$definition.Settings.RestartCount=0
    $action=$definition.Actions.Create(0);$action.Path=$script:r4Python
    $action.Arguments=Get-CaptureTaskArguments $Destination $Nonce
    $action.WorkingDirectory=$script:targetRoot
    $definition
}

function Assert-CaptureTaskRegistration {
    param($Task,[string]$Destination,[string]$Nonce)
    $definition=$Task.Definition
    if($Task.Enabled -ne $true -or $Task.State -notin @(1,3) -or $Task.GetInstances(0).Count -ne 0 -or
       $definition.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or $definition.Principal.LogonType -ne 5 -or $definition.Principal.RunLevel -ne 1 -or
       $definition.Settings.AllowDemandStart -ne $true -or $definition.Settings.MultipleInstances -ne 2 -or $definition.Settings.RestartCount -ne 0 -or
       $definition.Settings.ExecutionTimeLimit -cne $script:taskTimeLimit -or $definition.Triggers.Count -ne 0 -or $definition.Actions.Count -ne 1){
        throw 'The capture task is not the exact idle, trigger-free, bounded SYSTEM definition.'}
    $action=$definition.Actions.Item(1)
    if($action.Type -ne 0 -or $action.Path -cne $script:r4Python -or $action.Arguments -cne (Get-CaptureTaskArguments $Destination $Nonce) -or
       $action.WorkingDirectory -cne $script:targetRoot){throw 'The registered capture action differs from the pinned interpreter, helper and arguments.'}
    Assert-RegisteredTaskAcl ($Task.GetSecurityDescriptor(7))
}

function Wait-CaptureTaskInstance {
    param($Instance,[int]$TimeoutSeconds)
    $deadline=[DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do{
        Start-Sleep -Milliseconds 250
        try{$Instance.Refresh()}catch{
            $completed=$false;$exception=$_.Exception
            while($null -ne $exception){if($exception.HResult -eq -2147216629){$completed=$true;break};$exception=$exception.InnerException}
            # SCHED_E_TASK_NOT_RUNNING ends polling only; it never proves success.
            if($completed){return}
            throw}
        if([DateTime]::UtcNow -gt $deadline){throw ('the capture task did not end within '+$TimeoutSeconds+' s (task limit '+$script:taskTimeLimit+')')}
    }while($Instance.State -in @(2,4))
}

function Assert-CompletedCaptureTask {
    param($Task)
    if($Task.State -notin @(1,3) -or $Task.GetInstances(0).Count -ne 0){throw 'the capture task is not conclusively terminal'}
}

function Test-StringList {
    param($Value,[string]$Pattern,[int]$Maximum)
    $items=@($Value)
    if($null -eq $Value){return $false}
    if($items.Count -gt $Maximum){return $false}
    foreach($item in $items){if($item -isnot [string] -or $item -cnotmatch $Pattern){return $false}}
    $true
}

function Assert-ProbeClassification {
    param($Record,$Expected)
    $c=$Record.classification
    foreach($key in @('timed_out','output_bound_exceeded','utf8_valid','stdout_empty','stderr_empty','sign_in_line_present','auth_required_present',
        'not_logged_in_present','no_controlling_terminal_present','waiting_line_present','paste_prompt_present','url_present')){
        if($c.$key -isnot [bool]){throw ('Probe '+$Record.id+' classification '+$key+' is not a boolean.')}}
    $hosts=@($c.url_hosts)
    if($null -eq $c.url_hosts){$hosts=@()}
    if(-not (Test-StringList $hosts '^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*|unparsed)$' 8) -or ($c.url_present -ne ($hosts.Count -gt 0))){
        throw ('Probe '+$Record.id+' URL classification is not a bounded host-only list.')}
    if($c.timed_out -ne ($Record.outcome -ceq 'timed_out_terminated')){throw ('Probe '+$Record.id+' timeout classification contradicts its outcome.')}
    if($Expected.stdin_mode -ceq 'held_open_pipe'){
        if(-not (Test-ExactBool $c.exited_before_window ($Record.outcome -ceq 'exited')) -or -not (Test-ExactInt $c.window_seconds $script:windowSeconds)){
            throw ('Probe '+$Record.id+' window classification contradicts its outcome.')}}
    switch($Record.id){
        'P1'{if(-not (Test-ExactBool $c.version_matches $true)){throw 'P1 did not report the reviewed agy version.'}}
        'P2'{if($c.status_helper_classification -cnotin @('LOGGED_IN','LOGGED_OUT','HOLD') -or $c.json_envelope_parsed -isnot [bool] -or $c.gemini_row_present -isnot [bool] -or
                ($null -ne $c.status_value -and $c.status_value -cnotin @('SUCCESS','ERROR','CANCELED','INTERRUPTED','INVALID','WAITING','RUNNING','OTHER')) -or
                ($null -ne $c.command_name -and $c.command_name -cnotin @('models','agents','OTHER'))){throw 'P2 classification is outside its allowlist.'}
            if($c.status_helper_classification -ceq 'LOGGED_IN' -and -not ((Test-ExactInt $Record.exit_code 0) -and $c.status_value -ceq 'SUCCESS' -and $c.command_name -ceq 'models' -and $c.gemini_row_present -eq $true)){
                throw 'P2 status classification contradicts its envelope fields.'}}
        {$_ -cin @('P7','P8')}{if(-not (Test-StringList $c.agents '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$' 64) -and @($c.agents).Count -ne 0){throw ('Probe '+$Record.id+' agents list is outside its allowlist.')}}
    }
}

function Assert-ProbeRecord {
    param($Record,$Expected,[string]$Root)
    if($Record.id -cne $Expected.id -or $Record.stdin_mode -cne $Expected.stdin_mode){throw ('The probe order differs at '+$Expected.id+'.')}
    $argv=@($script:nativeExecutable)+@($Expected.arguments);$actual=@($Record.argv)
    if($actual.Count -ne $argv.Count){throw ('Probe '+$Expected.id+' argv differs.')}
    for($i=0;$i -lt $argv.Count;$i++){if($actual[$i] -isnot [string] -or $actual[$i] -cne $argv[$i]){throw ('Probe '+$Expected.id+' argv differs.')}}
    if(-not (Test-ExactInt $Record.bound_seconds $Expected.bound_seconds) -or -not (Test-ExactInt $Record.stdin_bytes_written 0) -or -not (Test-ExactBool $Record.cleanup_verified $true)){
        throw ('Probe '+$Expected.id+' bound, stdin or cleanup evidence differs.')}
    $window=($Expected.stdin_mode -ceq 'held_open_pipe')
    if($Record.outcome -cnotin @('exited','timed_out_terminated','window_elapsed_terminated','output_bound_terminated') -or
       ($Record.outcome -ceq 'window_elapsed_terminated' -and -not $window) -or ($Record.outcome -ceq 'timed_out_terminated' -and $window)){throw ('Probe '+$Expected.id+' outcome is invalid.')}
    if($Record.outcome -ceq 'exited'){if(($Record.exit_code -isnot [int]) -and ($Record.exit_code -isnot [long])){throw ('Probe '+$Expected.id+' exit code is invalid.')}}
    elseif($Record.exit_code -isnot [string] -or $Record.exit_code -cne 'terminated'){throw ('Probe '+$Expected.id+' exit code is invalid.')}
    if((($Record.elapsed_ms -isnot [int]) -and ($Record.elapsed_ms -isnot [long])) -or $Record.elapsed_ms -lt 0 -or $Record.elapsed_ms -gt (($Expected.bound_seconds+15)*1000)){throw ('Probe '+$Expected.id+' elapsed time is invalid.')}
    $p=$Record.process
    foreach($key in @('token_matches_selected_worker','image_matches_reviewed_executable','owned_job_membership_verified','profile_matches_inventory_root')){
        if(-not (Test-ExactBool $p.$key $true)){throw ('Probe '+$Expected.id+' process attestation is incomplete.')}}
    if($p.image_query_format -cnotin @('win32','native_after_exit')){throw ('Probe '+$Expected.id+' image attestation format is invalid.')}
    if($Expected.stdin_mode -ceq 'empty_file' -and $Record.stdin_sha256 -cne $script:emptySha256){throw ('Probe '+$Expected.id+' stdin was not the empty file.')}
    foreach($stream in @('stdout','stderr')){
        $value=$Record.$stream
        if($Record.raw_path.$stream -cne ('raw/'+$Expected.id+'.'+$stream) -or $value.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
           (($value.bytes -isnot [int]) -and ($value.bytes -isnot [long])) -or $value.bytes -lt 0 -or $value.bytes -gt $script:rawMaxBytes){throw ('Probe '+$Expected.id+' '+$stream+' evidence is invalid.')}
        $control=Read-R3Control (Join-Path $Root ('raw\'+$Expected.id+'.'+$stream)) $value.sha256 $script:rawMaxBytes
        if($control.Length -ne $value.bytes){throw ('Probe '+$Expected.id+' raw '+$stream+' length differs from the receipt.')}
    }
    Assert-ProbeClassification $Record $Expected
}

function Get-LoginModeDecision {
    param($P3,$P6)
    # print if P3 shows an https://accounts.google.com/ URL or a paste prompt without 'no controlling terminal'; else tui if P6
    # does; else none. A URL on any other host (a docs or help link) is not sign-in evidence (mirrors login_mode_decision).
    $signInUrl={param($c)(Test-ExactBool $c.url_present $true) -and (@(@($c.url_hosts)|Where-Object {$_ -is [string] -and $_ -ceq 'accounts.google.com'}).Count -gt 0)}
    $shows={param($c)($null -ne $c) -and ((& $signInUrl $c) -or (Test-ExactBool $c.paste_prompt_present $true)) -and (Test-ExactBool $c.no_controlling_terminal_present $false)}
    if(& $shows $P3){return [pscustomobject]@{mode='print';decided_by='P3'}}
    if(& $shows $P6){return [pscustomobject]@{mode='tui';decided_by='P6'}}
    [pscustomobject]@{mode='none';decided_by=$null}
}

function Get-CaptureGate {
    param([string]$Stage,[string]$Status,$Probes,$LoginMode)
    # The sitting outline's orchestrator gates (S1-A2 signed-out, S1-A4 signed-in).
    if($Status -cne 'CAPTURE_COMPLETE'){return [pscustomobject]@{stage=$Stage;passed=$false;reasons=@('CAPTURE_NOT_COMPLETE')}}
    $reasons=[Collections.Generic.List[string]]::new()
    $p2=@(@($Probes)|Where-Object {$_.id -ceq 'P2'})
    if($p2.Count -ne 1){$reasons.Add('P2_NOT_RUN')}
    elseif($Stage -ceq 'signed-out'){
        $c=$p2[0].classification
        if($p2[0].outcome -cne 'exited' -or -not (Test-ExactBool $c.timed_out $false)){$reasons.Add('P2_NOT_COMPLETED_WITHIN_BOUND')}
        if($c.status_helper_classification -cne 'LOGGED_OUT'){$reasons.Add('P2_NOT_LOGGED_OUT_UNDER_STATUS_PREDICATE')}
        if($LoginMode -cnotin @('print','tui')){$reasons.Add('LOGIN_MODE_NONE')}
    }else{
        $c=$p2[0].classification
        if(-not (Test-ExactInt $p2[0].exit_code 0)){$reasons.Add('P2_EXIT_NOT_ZERO')}
        if($c.status_value -cne 'SUCCESS'){$reasons.Add('P2_STATUS_NOT_SUCCESS')}
        if($c.command_name -cne 'models'){$reasons.Add('P2_COMMAND_NOT_MODELS')}
        if(-not (Test-ExactBool $c.gemini_row_present $true)){$reasons.Add('P2_NO_GEMINI_ROW')}
    }
    [pscustomobject]@{stage=$Stage;passed=($reasons.Count -eq 0);reasons=@($reasons)}
}

function Assert-CaptureFailureMetadata {
    param($Value)
    if($null -eq $Value.PSObject.Properties['failure']){return $null}
    $f=$Value.failure
    if($f.phase -cnotin $script:failurePhases -or $f.error_type -cnotmatch '^[A-Za-z][A-Za-z0-9_]{0,79}$' -or
       ($null -ne $f.winerror -and (($f.winerror -isnot [int] -and $f.winerror -isnot [long]) -or $f.winerror -lt 0 -or $f.winerror -gt 4294967295))){throw 'Invalid sanitized capture failure metadata.'}
    [ordered]@{phase=$f.phase;error_type=$f.error_type;winerror=$f.winerror}
}

function Assert-CaptureReceipt {
    param($Value,$Task,$Pins,[string]$Nonce,[string]$Root)
    if($Value.schema -cne 'cochem-agy-status-capture/1' -or $Value.attempt -cne $script:Attempt -or $Value.nonce -cne $Nonce -or $Value.slot -cne $script:Slot -or
       $Value.stage -cne $script:Stage -or $Value.system_sid -cne 'S-1-5-18' -or $Value.helper_sha256 -cne $script:helperPin -or $Value.runtime_root -cne $script:r4Root -or
       $Value.install_receipt_sha256 -cne $Pins.install_receipt_sha256 -or $Value.source_manifest_sha256 -cne $Pins.source_manifest_sha256 -or
       $Value.resource_limits_sha256 -cne $script:resourcePin -or $Value.windows_runtime_sha256 -cne $script:windowsPin -or $Value.native_executable -cne $script:nativeExecutable){
        throw 'The capture receipt identity/runtime binding differs.'}
    $failure=Assert-CaptureFailureMetadata $Value
    if($Value.status -cin @('CAPTURE_FAILED','CAPTURE_INCOMPLETE')){
        return [pscustomobject]@{decision=$(if($Value.status -ceq 'CAPTURE_FAILED'){'FAILED'}else{'INCOMPLETE'});failure=$failure;gate=(Get-CaptureGate $script:Stage $Value.status @() $null);login_mode=$null}}
    if($Value.status -cne 'CAPTURE_COMPLETE' -or $null -ne $failure){throw 'The capture receipt status is not a known terminal status.'}
    if($Task.LastTaskResult -ne 0 -or $Value.config_sha256 -cne $Pins.configuration_sha256 -or $Value.layout_sha256 -cne $Pins.layout_sha256 -or
       -not (Test-ExactBool $Value.revision.verified $true) -or $Value.revision.source_sha256 -cne $Pins.revision_sha256 -or
       $Value.native_executable_sha256_before -cne $script:agyPin -or $Value.native_executable_sha256_after -cne $script:agyPin -or $Value.native_version_at_pin -cne $script:agyVersion){
        throw 'The capture receipt configuration/result binding differs.'}
    foreach($key in @('cleanup_verified','runtime_custody_verified','require_stopped_before','require_stopped_after','daemon_states_verified_before_and_after')){
        if(-not (Test-ExactBool $Value.$key $true)){throw ('The capture receipt lacks verified '+$key+'.')}}
    foreach($key in @('native_model_jobs_executed','login_inputs_written','stdin_bytes_written','token_files_opened')){
        if(-not (Test-ExactInt $Value.$key 0)){throw ('Out-of-scope execution was reported: '+$key+'.')}}
    foreach($key in @('owner_credentials_read','raw_output_published','pipeline_started')){if(-not (Test-ExactBool $Value.$key $false)){throw ('Out-of-scope action was reported: '+$key+'.')}}
    if($Value.worker_identity -cne $script:workerIdentity -or $Value.profile_root -cne $script:workerProfile -or @($Value.probes_skipped).Count -ne 0){throw 'The capture receipt worker/profile binding differs.'}
    if($null -eq $Value.profile_inventory_before -or $null -eq $Value.profile_inventory_after -or $Value.profile_inventory_before.profile_root -cne $script:workerProfile){throw 'The profile inventories are missing.'}
    $expected=@(Get-ExpectedProbes $script:Stage);$probes=@($Value.probes)
    if($probes.Count -ne $expected.Count){throw 'The capture receipt does not carry exactly the planned probes.'}
    for($i=0;$i -lt $expected.Count;$i++){Assert-ProbeRecord $probes[$i] $expected[$i] $Root}
    $minted=@($probes|Where-Object {$_.classification.url_present -eq $true}).Count
    if(-not (Test-ExactInt $Value.oauth_urls_possibly_minted $minted)){throw 'The minted-URL count contradicts the probe classifications.'}
    $loginMode=$null
    if($script:Stage -ceq 'signed-out'){
        $p3=@($probes|Where-Object {$_.id -ceq 'P3'})[0];$p6=@($probes|Where-Object {$_.id -ceq 'P6'})[0]
        $decision=Get-LoginModeDecision $p3.classification $p6.classification
        $mode=$Value.login_mode
        if($null -eq $mode -or $mode.mode -cne $decision.mode -or $mode.decided_by -cne $decision.decided_by -or $mode.path -cne 'login-mode.json' -or $mode.sha256 -cnotmatch '^[a-f0-9]{64}$'){
            throw 'The login-mode decision contradicts the retained P3/P6 evidence.'}
        $file=(Read-R3Text (Read-R3Control (Join-Path $Root 'login-mode.json') $mode.sha256 65536))|ConvertFrom-Json
        if($file.schema -cne 'cochem-agy-login-mode/1' -or $file.mode -cne $decision.mode -or $file.decided_by -cne $decision.decided_by -or $file.attempt -cne $script:Attempt -or
           $file.nonce -cne $Nonce -or $file.slot -cne $script:Slot -or $file.stage -cne $script:Stage -or $file.evidence_sha256 -cne $mode.evidence_sha256 -or
           $file.evidence.P3.stdout_sha256 -cne $p3.stdout.sha256 -or $file.evidence.P6.stdout_sha256 -cne $p6.stdout.sha256){throw 'login-mode.json contradicts the capture receipt.'}
        $loginMode=[ordered]@{mode=$decision.mode;decided_by=$decision.decided_by;sha256=$mode.sha256}
    }elseif($null -ne $Value.login_mode){throw 'A signed-in capture must not decide a login mode.'}
    $gate=Get-CaptureGate $script:Stage $Value.status $probes $(if($null -ne $loginMode){$loginMode.mode}else{$null})
    if(-not (Test-ExactBool $Value.gate.passed $gate.passed) -or (@($Value.gate.reasons) -join ',') -cne (@($gate.reasons) -join ',')){throw 'The capture gate contradicts the retained evidence.'}
    [pscustomobject]@{decision='COMPLETE';failure=$null;gate=$gate;login_mode=$loginMode}
}

function New-CaptureSummary {
    param($Receipt,$Verified,$Task,[string]$Nonce,[string]$ReceiptSha256)
    $probes=@();$complete=@()
    foreach($p in @($Receipt.probes)){
        # A failed capture can end inside a probe; such a record is reported as incomplete, never dereferenced.
        if($null -eq $p.PSObject.Properties['classification'] -or $null -eq $p.PSObject.Properties['stdout'] -or $null -eq $p.PSObject.Properties['outcome']){
            $probes+=[ordered]@{id=$p.id;incomplete=$true};continue}
        $c=$p.classification;$complete+=$p
        $probes+=[ordered]@{id=$p.id;outcome=$p.outcome;exit_code=$p.exit_code;elapsed_ms=$p.elapsed_ms;stdout_bytes=$p.stdout.bytes;stderr_bytes=$p.stderr.bytes;
            url_present=$c.url_present;url_hosts=@($c.url_hosts);paste_prompt_present=$c.paste_prompt_present;waiting_line_present=$c.waiting_line_present;
            no_controlling_terminal_present=$c.no_controlling_terminal_present;not_logged_in_present=$c.not_logged_in_present;
            auth_required_present=$c.auth_required_present;sign_in_line_present=$c.sign_in_line_present;timed_out=$c.timed_out}}
    $p2=@($complete|Where-Object {$_.id -ceq 'P2'})
    $status=$(if($p2.Count -and $null -ne $p2[0].classification.PSObject.Properties['status_helper_classification']){$p2[0].classification.status_helper_classification}else{$null})
    $tokens=@()
    if($null -ne $Receipt.profile_inventory_after){
        foreach($tree in @($Receipt.profile_inventory_after.trees.PSObject.Properties)){
            foreach($row in @($tree.Value.entries)){if($row.kind -ceq 'file' -and $null -ne $row.PSObject.Properties['token_file']){$tokens+=[ordered]@{path=$tree.Name+'/'+$row.path;size=$row.size}}}}}
    $gate=$Verified.gate;$root=$script:targetRoot
    if($Verified.decision -cne 'COMPLETE'){$message='SERIES-STOP: the capture did not complete ('+$Receipt.status+$(if($null -ne $Verified.failure){', phase '+$Verified.failure.phase+', '+$Verified.failure.error_type}else{''})+'); evidence in '+$root+'. Restore the service on r4 (A6); no login is attempted.'}
    elseif(-not $gate.passed -and $script:Stage -ceq 'signed-out'){$message='SERIES-STOP: sign-in path unreachable or the signed-out status is not established ('+(@($gate.reasons) -join ', ')+'); evidence in '+$root+'. Restore the service on r4 (A6); no login is attempted.'}
    elseif(-not $gate.passed){$message='SERIES-STOP: the signed-in shape is not confirmed ('+(@($gate.reasons) -join ', ')+'); evidence in '+$root+'.'}
    elseif($script:Stage -ceq 'signed-out'){$message='Signed-out capture verified: P2 LOGGED_OUT within 30 s; login mode '+$Verified.login_mode.mode+' ('+$Verified.login_mode.decided_by+'). Continue to the attended slot1 sign-in.'}
    else{$message='Signed-in capture verified: P2 SUCCESS envelope (command models) with a gemini row.'}
    [ordered]@{schema='cochem-agy-status-capture-result/1';status=$Receipt.status;decision=$Verified.decision;attempt=$script:Attempt;slot=$script:Slot;stage=$script:Stage;nonce=$Nonce;
        target_root=$root;receipt_path=(Join-Path $root 'capture-receipt.json');receipt_sha256=$ReceiptSha256;task_name=$script:taskName;last_task_result=$Task.LastTaskResult;task_preserved=$true;
        gate=[ordered]@{passed=$gate.passed;reasons=@($gate.reasons)};series_stop=(-not $gate.passed);failure=$Verified.failure;login_mode=$Verified.login_mode;
        p2_status_helper_classification=$status;probes=$probes;oauth_urls_possibly_minted=$Receipt.oauth_urls_possibly_minted;
        new_files=@(@($Receipt.new_files)|ForEach-Object {$_.path});new_directories=@($Receipt.new_directories);changed_files=@($Receipt.changed_files);removed_files=@($Receipt.removed_files);
        token_files_after=$tokens;
        raw_output_location=(Join-Path $root 'raw');raw_output_access='SYSTEM and BUILTIN\Administrators only';native_model_jobs_executed=0;login_inputs_written=0;pipeline_started=$false;
        automatic_retry_allowed=$false;message=$message}
}

function Invoke-AgyCapture {
    param($Scheduler,$Folder,$Pins,[long]$SourceLength)
    try{
        # Elevated: inspect the code trees once before the SYSTEM task runs the r4 interpreter against the native binary.
        $codeTrees=[ordered]@{runtime=(Assert-CodeTreeOnce $script:r4Root);toolchain=(Assert-CodeTreeOnce $script:basePythonRoot);native=(Assert-CodeTreeOnce $script:nativeRoot)}
        if((Get-TaskPresence $Folder $script:taskName) -cne 'ABSENT'){throw 'The capture task already exists; preserve it and choose another -Attempt.'}
        if(Test-Path -LiteralPath $script:targetRoot){throw 'The capture root already exists; preserve it and choose another -Attempt.'}
    }catch{
        $reason=$_.Exception.Message
        throw ('The agy status capture is held before any change: '+$reason.TrimEnd('.')+'. Nothing was changed.')}
    # The root is created inside the try below (phase PREPARATION). Once it exists the attempt namespace is consumed and
    # every failure leaves capture-held.json; a root that was never created changes nothing.
    $phase='PREPARATION';$registered=$false;$runRequested=$false;$task=$null;$nonce=$null;$failure=$null;$summary=$null;$intentHash=$null;$taskXmlHash=$null;$receiptPresent=$false;$verified=$null
    $rootVerified=$false;$rootAbsentBefore=-not (Test-Path -LiteralPath $script:targetRoot)
    try{
        New-PrivateDirectory $script:targetRoot;$rootVerified=$true
        $destination=Join-Path $script:targetRoot $script:helperName
        Copy-VerifiedPayload ([pscustomobject]@{source=$script:helperSource;destination=$destination;sha256=$script:helperPin;length=$SourceLength})
        $held.Add((Open-VerifiedFile $destination $script:helperPin $SourceLength))
        $nonce=New-CaptureNonce
        $intent=[ordered]@{schema='cochem-agy-status-capture-intent/1';attempt=$script:Attempt;slot=$script:Slot;stage=$script:Stage;nonce=$nonce;requested_utc=[DateTime]::UtcNow.ToString('o');
            task_name=$script:taskName;target_root=$script:targetRoot;helper_sha256=$script:helperPin;native_sha256=$script:agyPin;r4_bindings=$Pins;code_tree_entries=$codeTrees;
            task_action=[ordered]@{path=$script:r4Python;arguments=(Get-CaptureTaskArguments $destination $nonce);working_directory=$script:targetRoot};task_execution_time_limit=$script:taskTimeLimit;
            probes=@(Get-ExpectedProbes $script:Stage);oauth_urls_minted_expected=$(if($script:Stage -ceq 'signed-out'){2}else{0});login_inputs_planned=0;retry=$false}
        $intentHash=Write-RegistrationControl (Join-Path $script:targetRoot 'capture-intent.json') ($intent|ConvertTo-Json -Depth 8)
        $phase='REGISTRATION'
        $definition=New-CaptureTaskDefinition $Scheduler $destination $nonce
        $registered=$true
        $task=$Folder.RegisterTaskDefinition($script:taskName,$definition,2,'SYSTEM',$null,5,$script:taskSddl)
        Assert-CaptureTaskRegistration $task $destination $nonce
        $taskXmlHash=Write-RegistrationControl (Join-Path $script:targetRoot 'capture-task.xml') ([string]$task.Xml)
        $phase='RUN'
        $runRequested=$true
        $instance=$task.Run($null)
        $phase='WAIT'
        Wait-CaptureTaskInstance $instance $script:taskWaitSeconds
        Assert-CompletedCaptureTask $task
        $phase='RECEIPT'
        $receiptPath=Join-Path $script:targetRoot 'capture-receipt.json'
        if(-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)){throw ('the capture task left no receipt (LastTaskResult '+$task.LastTaskResult+')')}
        $receiptPresent=$true
        $receiptControl=Read-R3Control $receiptPath '' $script:receiptMaxBytes
        $receipt=(Read-R3Text $receiptControl)|ConvertFrom-Json
        $verified=Assert-CaptureReceipt $receipt $task $Pins $nonce $script:targetRoot
        $summary=New-CaptureSummary $receipt $verified $task $nonce $receiptControl.Sha256
        $summary.intent_sha256=$intentHash;$summary.task_xml_sha256=$taskXmlHash
        $phase='SUMMARY'
        $null=Write-RegistrationControl (Join-Path $script:targetRoot 'capture-summary.json') ($summary|ConvertTo-Json -Depth 8)
        if($verified.decision -cne 'COMPLETE'){$phase='HELPER';throw ('the capture helper reported '+$receipt.status)}
    }catch{$failure=$_.Exception.Message}
    if($null -ne $failure){
        if(-not $rootVerified -and -not ($rootAbsentBefore -and (Test-Path -LiteralPath $script:targetRoot))){
            throw ('The agy status capture is held before any change: '+$failure.TrimEnd('.')+'. Nothing was changed.')}
        $lastResult=$null;$state=$null;$instances=$null
        if($null -ne $task){try{$lastResult=[int]$task.LastTaskResult;$state=[int]$task.State;$instances=[int]$task.GetInstances(0).Count}catch{$lastResult=$null}}
        $heldRecord=[ordered]@{schema='cochem-agy-status-capture-held/1';attempt=$script:Attempt;slot=$script:Slot;stage=$script:Stage;nonce=$nonce;phase=$phase;reason=$failure;
            task_name=$script:taskName;task_registered=$registered;run_requested=$runRequested;task_state=$state;task_instances=$instances;last_task_result=$lastResult;
            receipt_present=$receiptPresent;helper_failure=$(if($null -ne $verified){$verified.failure}else{$null});intent_sha256=$intentHash;task_xml_sha256=$taskXmlHash;
            raw_output_location=(Join-Path $script:targetRoot 'raw');task_preserved=$true;root_preserved=$true;root_verified=$rootVerified;processes_killed=$false;automatic_retry_allowed=$false;requires_reviewed_recovery=$true}
        $heldNote=''
        try{$null=Write-RegistrationControl (Join-Path $script:targetRoot 'capture-held.json') ($heldRecord|ConvertTo-Json -Depth 8)}catch{$heldNote=(' The held record could not be written: '+$_.Exception.Message)}
        $message=switch($phase){
            'PREPARATION'{'The agy status capture is held before any task exists: '+$failure+'. Preserve '+$script:targetRoot+' and review capture-held.json before another -Attempt.'}
            'REGISTRATION'{'The agy status capture is held at task registration: '+$failure+'. No Run was requested; preserve the root and the task (if registered) and review capture-held.json.'}
            'RUN'{'The agy status capture is held at its single Run request: '+$failure+'. Preserve everything and review capture-held.json.'}
            'WAIT'{'The agy status capture did not end cleanly: '+$failure+'. Keep the daemons disabled, preserve the task and root, review capture-held.json; do not retry automatically.'}
            'HELPER'{'SERIES-STOP: '+$failure+'; evidence in '+$script:targetRoot+' (capture-summary.json, capture-held.json). Restore the service on r4 (A6); no login is attempted.'}
            default{'The agy status capture receipt is refused: '+$failure+'. Preserve the task and root and review capture-held.json; no login is attempted.'}}
        if($null -ne $summary){Write-Host ('COCHEM_AGY_STATUS_CAPTURE_RESULT '+($summary|ConvertTo-Json -Depth 8 -Compress))}
        throw ($message+$heldNote)
    }
    $summary
}

function Write-CaptureOutcome {
    param($Summary)
    # The orchestrator reads the JSON summary from stdout on success; a failed gate prints the summary line and exits non-zero.
    if((Test-ExactBool $Summary.gate.passed $true) -and $Summary.decision -ceq 'COMPLETE'){return ($Summary|ConvertTo-Json -Depth 8)}
    Write-Host ('COCHEM_AGY_STATUS_CAPTURE_RESULT '+($Summary|ConvertTo-Json -Depth 8 -Compress))
    throw $Summary.message
}

function Invoke-AgyCaptureMain {
    param([string]$Slot,[string]$Stage,[string]$Attempt,[bool]$ApplyRequested,[string]$Workspace)
    $ErrorActionPreference='Stop';Set-StrictMode -Version Latest
    if($Attempt -cnotmatch '^[a-f0-9]{32}$' -or ($ApplyRequested -and $Attempt -ceq '00000000000000000000000000000000')){throw 'A lowercase 32-hex -Attempt is required; -Apply forbids the all-zero preview attempt. Nothing was changed.'}
    $Slot=$Slot.ToLowerInvariant();$Stage=$Stage.ToLowerInvariant()
    if($Slot -cne 'slot1' -or $Stage -cnotin @('signed-out','signed-in')){throw 'Only -Slot slot1 with -Stage signed-out or signed-in is reviewed. Nothing was changed.'}
    foreach($module in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$module\$module.psd1") -ErrorAction Stop}
    if($PSVersionTable.PSEdition -ne 'Desktop' -or -not [Environment]::Is64BitProcess -or $env:COMPUTERNAME -cne 'AETHERDESK'){throw 'Use 64-bit Windows PowerShell 5.1 on AETHERDESK.'}
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent();$script:admin=[Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if($ApplyRequested -and (-not $script:admin -or $identity.Name -cne 'AETHERDESK\ansac')){throw '-Apply requires the owner in Administrator Windows PowerShell; nothing was changed.'}
    Set-CaptureConstants $Slot $Stage $Attempt $Workspace
    $copyHelper='C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1'
    foreach($text in Import-ReviewedFunctions $copyHelper '0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b' @('Assert-NoReparseAncestors','Assert-ProtectedPath','New-CodeAcl','Initialize-FileIdentity','Open-VerifiedFile','Copy-VerifiedPayload')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $Workspace 'check-worker-native-status-r3.ps1') '18f58ebb448d8a0c6329dd187d4a9a27fa9cbe942cd05e906bb7aabc67e787a7' @('Read-R3Control','Read-R3Text')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $Workspace 'register-stopped-warden-r3.ps1') 'eccc593f36cbf488a54775b4343bcf3cf8b261b7cd81e5536fb7f2f18466a198' @('Assert-RegisteredTaskAcl','Write-RegistrationControl')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $Workspace 'protected-code-inspection-v4.ps1') '5c01543cbb8b8d64b2b9f1bab4a13f87f8ff9e1ab3e82dfb6fc547144c77b95d' @('Assert-CodeTreeOnce')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $Workspace 'retarget-warden-r4.ps1') '8ee6b412f6be176dfac7c2c1b2340f1973e08358c7d22da6d4515e79f0327a4e' @('Test-ExactBool','Test-ExactInt','Assert-R4InstalledBindings','New-PrivateAcl','Assert-PrivateAcl','New-PrivateDirectory')){. ([scriptblock]::Create($text))}
    Initialize-FileIdentity
    $held=[Collections.Generic.List[IO.FileStream]]::new()
    try{
        $holds=@();$runtime=$null;$pins=$null;$sourceLength=$null;$nativeVerified=$false;$daemons=@();$taskPresence=$null;$profilePresent=$null
        try{$runtime=Assert-R4InstalledBindings;$pins=Assert-CaptureRuntimePins $runtime}catch{$holds+=('r4 runtime is not the reviewed build: '+$_.Exception.Message)}
        try{$sourceLength=(Get-Item -LiteralPath $script:helperSource).Length;$held.Add((Open-VerifiedFile $script:helperSource $script:helperPin $sourceLength))}
        catch{$sourceLength=$null;$holds+=('The reviewed capture helper differs from its pin or is missing: '+$_.Exception.Message)}
        foreach($path in @($script:r4Python,(Join-Path $script:r4Root 'windows-layout.json'),(Join-Path $script:r4Root 'pipeline.json'),$script:nativeExecutable,$script:basePython,(Join-Path $script:r4Root '.venv\pyvenv.cfg'))){
            if(-not (Test-Path -LiteralPath $path -PathType Leaf)){$holds+=('A required stopped installation file is absent: '+$path)}
            else{try{Assert-ProtectedPath $path}catch{$holds+=('Protected path check failed: '+$_.Exception.Message)}}}
        if(Test-Path -LiteralPath $script:nativeExecutable -PathType Leaf){
            try{$stream=Open-VerifiedFile $script:nativeExecutable $script:agyPin (Get-Item -LiteralPath $script:nativeExecutable).Length;$stream.Dispose();$nativeVerified=$true}
            catch{$holds+=('agy.exe differs from the reviewed pin: '+$_.Exception.Message)}}
        if(Test-Path -LiteralPath $script:targetRoot){$holds+='This one-shot capture root already exists; preserve its evidence and choose another -Attempt.'}
        $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect();$folder=$scheduler.GetFolder('\')
        try{$taskPresence=Get-TaskPresence $folder $script:taskName;if($taskPresence -cne 'ABSENT'){$holds+='This one-shot capture task already exists; preserve it and choose another -Attempt.'}}
        catch{$holds+=('Capture task state: '+$_.Exception.Message)}
        try{$daemons=@(Get-SeriesDaemonTaskStates $folder)
            $active=@($daemons|Where-Object {$_.active -eq $true}|ForEach-Object {$_.name});$deferred=@($daemons|Where-Object {$_.state -ceq 'ACCESS_DENIED_DEFERRED'}|ForEach-Object {$_.name})
            if($active.Count){$holds+=('Protected daemons must remain stopped and disabled (run stop-warden-r4 first): '+($active -join ', '))}
            if($deferred.Count){$holds+=('Daemon task definitions are unreadable without elevation; re-read during -Apply: '+($deferred -join ', '))}
        }catch{$holds+=('Daemon tasks: '+$_.Exception.Message)}
        try{$profilePresent=[bool](Test-Path -LiteralPath $script:workerProfile -PathType Container -ErrorAction Stop)}catch{$profilePresent=$null}
        if($script:admin -and $profilePresent -ne $true){$holds+=('The slot1 worker profile directory is not present: '+$script:workerProfile)}
        $plan=[ordered]@{schema='cochem-agy-status-capture-plan/1';mode='READ_ONLY_PLAN';attempt=$script:Attempt;slot=$script:Slot;stage=$script:Stage;owner=$identity.Name;administrator=$script:admin;
            runtime_root=$script:r4Root;r4_runtime_verified=($null -ne $pins);r4_bindings=$pins;helper_source=$script:helperSource;helper_sha256=$script:helperPin;helper_verified=($null -ne $sourceLength);
            native_executable=$script:nativeExecutable;native_sha256=$script:agyPin;native_verified=$nativeVerified;native_version_at_pin=$script:agyVersion;
            task_name=$script:taskName;task_presence=$taskPresence;target_root=$script:targetRoot;target_root_access='SYSTEM and BUILTIN\Administrators only';
            task_execution_time_limit=$script:taskTimeLimit;task_action=[ordered]@{path=$script:r4Python;arguments=(Get-CaptureTaskArguments (Join-Path $script:targetRoot $script:helperName) '<nonce>');working_directory=$script:targetRoot};
            probes=@(Get-ExpectedProbes $script:Stage|ForEach-Object {[ordered]@{id=$_.id;argv=@($script:nativeExecutable)+@($_.arguments);stdin_mode=$_.stdin_mode;bound_seconds=$_.bound_seconds}});
            probe_timeout_seconds=$script:probeTimeoutSeconds;window_seconds=$script:windowSeconds;output_limit_bytes=$script:outputLimitBytes;
            oauth_urls_minted_expected=$(if($script:Stage -ceq 'signed-out'){2}else{0});worker_identity=$script:workerIdentity;worker_profile=$script:workerProfile;worker_profile_present=$profilePresent;
            inventory_roots=$script:inventoryRoots;daemon_tasks=$daemons;holds=$holds;native_commands_executed=0;native_model_jobs_executed=0;login_inputs_written=0;
            tasks_changed=0;pipeline_started=$false;automatic_retry_allowed=$false}
        if(-not $ApplyRequested){$plan|ConvertTo-Json -Depth 8;return}
        if($holds.Count){throw ('The agy status capture is held. Nothing was changed: '+($holds -join ' | '))}
        Write-CaptureOutcome (Invoke-AgyCapture $scheduler $folder $pins $sourceLength)
    }finally{foreach($stream in $held){$stream.Dispose()}}
}

# Invocation boundary: the only top-level statement. Fixtures dot-source the functions above from the AST without running it.
Invoke-AgyCaptureMain -Slot $Slot -Stage $Stage -Attempt $Attempt -ApplyRequested ([bool]$Apply) -Workspace $PSScriptRoot
