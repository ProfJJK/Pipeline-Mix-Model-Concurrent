#Requires -Version 5.1
<# Read-only plan by default. -Apply is an explicit one-shot, non-inference native
   authentication status check in one worker profile of the r4 stopped runtime
   (build-manifest step 3; re-issue of check-worker-native-auth-status-six-r3-v4.ps1,
   sha256 4448e76eaeb30f2d2905f5aa6d3e14f0cc29b3d7e703321bb3df55afcba58e81).
   Providers: codex, claude and gemini (the pinned Antigravity CLI agy.exe 1.3.1, status argv
   --output-format json models, classified by worker-native-auth-status-six-r4-v1.py).
   The plan reads the r4 install/manifest/revision receipts (full 166-file / 109-asset walk),
   the pinned interpreter, toolchain and native executable, the four managed daemon tasks and
   the one-shot namespace. Unelevated, SYSTEM-only task definitions are reported as deferred
   holds. No native command, task, or protected directory is created in plan mode.
   -Apply (AETHERDESK\ansac, elevated 64-bit Windows PowerShell 5.1): inspects the code trees
   once, re-checks every hold, creates the one-shot root
   C:\Program Files\CoChem\NativeAuthStatusSix4.2.7-windows-20261010-r4-v1-<attempt>-<slot>-<provider>-<stage>,
   copies the hash-pinned helper, registers ONE SYSTEM task
   CoChem-4.2.7-NativeAuthStatusSix-20261010-r4-v1-<attempt>-<slot>-<provider>-<stage>
   (no triggers, PT3M, SDDL O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA), registration flags 18 =
   TASK_CREATE|TASK_DONT_ADD_PRINCIPAL_ACE so that exact private DACL reads back), requests one Run, waits,
   and binds the helper's receipt (task result 2 for a HOLD classification, 0 for an established
   decision). Every failure after the root exists, including a failed post-create root check, leaves
   status-held.json (CreateNew) and a plain message; a valid decision is recorded in status-task-result.json.
   The four daemon tasks (CoChem-4.2.7-Warden, CoChem-4.2.7-Supervisor, CoChem-4.2.2-Warden,
   CoChem-4.2.3-Supervisor) must be stopped and disabled; observer/recorder tasks are not
   inspected or touched. No login, model inference, retry, stop, kill or delete ever occurs. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('slot1','slot2','slot3','slot4','slot5','slot6')][string]$Slot,
    [Parameter(Mandatory=$true)][ValidateSet('codex','claude','gemini')][string]$Provider,
    [Parameter(Mandatory=$true)][ValidateSet('before','after')][string]$Stage,
    [switch]$Apply,
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

function Set-AuthStatusConstants {
    param([string]$Slot,[string]$Provider,[string]$Stage,[string]$Attempt,[string]$ScriptRoot)
    $script:programFiles='C:\Program Files';$script:base=Join-Path $script:programFiles 'CoChem'
    $script:installRoot=Join-Path $script:base 'Pipeline4.2.7-windows-20261009-r4'
    $script:python=Join-Path $script:installRoot '.venv\Scripts\python.exe'
    $script:basePythonRoot=Join-Path $script:base 'Toolchain4.2.7-windows-20261006\Python312';$script:basePython=Join-Path $script:basePythonRoot 'python.exe'
    $script:venvConfig=Join-Path $script:installRoot '.venv\pyvenv.cfg'
    $script:layout=Join-Path $script:installRoot 'windows-layout.json';$script:config=Join-Path $script:installRoot 'pipeline.json'
    $script:nativeRoot=Join-Path $script:base 'Native4.2.7-windows-20261006'
    # Provider -> reviewed native executable, pin and status argv (the argv itself lives in the Python CONTRACTS).
    $script:nativeExecutables=@{codex='codex.exe';claude='claude.exe';gemini='agy.exe'}
    $script:nativeHashes=@{codex='fdda5fa3cf3fb3d000b876720742857676293e4315e4b045fae6f8bd7e866d1d';claude='0e4195524b73eb77efbdf3e2b36de5322a29f0ca575dfd2d9b4f946b1d425469';gemini='38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741'}
    $script:nativeArguments=@{codex=@('login','status');claude=@('--setting-sources','','auth','status','--json');gemini=@('--output-format','json','models')}
    $script:native=Join-Path $script:nativeRoot $script:nativeExecutables[$Provider];$script:nativeHash=$script:nativeHashes[$Provider]
    # Fixed namespace date (the build date of this re-issue); -Attempt selects the one-shot namespace.
    $script:namespaceDate='20261010'
    $script:targetRoot=Join-Path $script:base ('NativeAuthStatusSix4.2.7-windows-'+$script:namespaceDate+'-r4-v1-'+$Attempt+'-'+$Slot+'-'+$Provider+'-'+$Stage)
    $script:taskName='CoChem-4.2.7-NativeAuthStatusSix-'+$script:namespaceDate+'-r4-v1-'+$Attempt+'-'+$Slot+'-'+$Provider+'-'+$Stage
    $script:helperName='worker-native-auth-status-six-r4-v1.py'
    $script:source=Join-Path $ScriptRoot $script:helperName
    $script:sourceHash='45681477194d97b144e8ee4505d4364d73d58aaef19c8428c846df642c834839'
    $script:daemonTaskNames=@('CoChem-4.2.7-Warden','CoChem-4.2.7-Supervisor','CoChem-4.2.2-Warden','CoChem-4.2.3-Supervisor')
    $script:taskTimeLimit='PT3M';$script:taskSddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)';$script:taskWaitSeconds=175
    # Registration flags 18 = TASK_CREATE (0x2) | TASK_DONT_ADD_PRINCIPAL_ACE (0x10), still create-only. With 2 alone this host
    # stores the task DACL unprotected with an appended (A;;FR;;;SY) ACE, which Assert-RegisteredTaskAcl refuses (r5 sitting v2,
    # 2026-10-11: 12 of 12 held at REGISTER). 18 kept the exact protected two-ACE DACL and passed the same validator on
    # 2026-10-08 (resume-pending-warden-r3-v7.ps1:125, C:\Program Files\CoChem\TaskAclRecovery4.2.7-windows-20261008-r3-v1).
    $script:taskRegistrationFlags=18
    $script:statusTimeoutSeconds=30;$script:outputLimitBytes=65536;$script:receiptLimitBytes=32768
    $script:copyHelper='C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1';$script:copyHelperPin='0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b'
    $script:statusFunctions=Join-Path $ScriptRoot 'check-worker-native-status-r3.ps1';$script:statusFunctionsPin='18f58ebb448d8a0c6329dd187d4a9a27fa9cbe942cd05e906bb7aabc67e787a7'
    $script:registrationFunctions=Join-Path $ScriptRoot 'register-stopped-warden-r3.ps1';$script:registrationFunctionsPin='eccc593f36cbf488a54775b4343bcf3cf8b261b7cd81e5536fb7f2f18466a198'
    $script:inspectionFunctions=Join-Path $ScriptRoot 'protected-code-inspection-v4.ps1';$script:inspectionFunctionsPin='5c01543cbb8b8d64b2b9f1bab4a13f87f8ff9e1ab3e82dfb6fc547144c77b95d'
}

function Get-AuthStatusHelperDefinitions {
    # Only exact reviewed definitions, never helper actions; the caller dot-sources them in its own scope.
    Import-ReviewedFunctions $script:copyHelper $script:copyHelperPin @('Assert-NoReparseAncestors','Assert-ProtectedPath','New-CodeAcl','New-ProtectedDirectory','Initialize-FileIdentity','Open-VerifiedFile','Copy-VerifiedPayload')
    Import-ReviewedFunctions $script:statusFunctions $script:statusFunctionsPin @('Read-R3Control','Read-R3Text')
    Import-ReviewedFunctions $script:registrationFunctions $script:registrationFunctionsPin @('Assert-RegisteredTaskAcl','Write-RegistrationControl')
    Import-ReviewedFunctions $script:inspectionFunctions $script:inspectionFunctionsPin @('Assert-CodeTreeOnce')
}

function Assert-R4InstalledBindings {
    # The r3 Assert-R3InstalledBindings body with the r4 pins (r4 = r3 + the reviewed telemetry repair).
    # Literal pins only, so a caller can import this definition by hash; receipt booleans and counts
    # must carry their native JSON types.
    $root='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4'
    $manifestPin='1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189';$revisionPin='38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e'
    if($manifestPin -cnotmatch '^[a-f0-9]{64}$' -or $revisionPin -cnotmatch '^[a-f0-9]{64}$'){throw 'Reviewed r4 source freeze is pending.'}
    $configPin='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c';$repairPin='e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc'
    $afterControl=Read-R3Control (Join-Path $root 'install-after.json') '629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502' 1048576
    $after=(Read-R3Text $afterControl)|ConvertFrom-Json;$revision=$after.verification.revision
    if($after.schema -cne 'cochem-stopped-runtime-update/1' -or $after.mode -cne 'FRESH_STOPPED_RUNTIME_READY' -or
       $after.target_root -cne $root -or $after.source_manifest_sha256 -cne $manifestPin -or $after.configuration_sha256 -cne $configPin -or
       $after.previous_runtime_root -cne 'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r3' -or
       $after.previous_install_receipt_sha256 -cne '3b613128192ac44a0a3d9c4b4476fb4c47541edb7563541b9bbf18f84f9a90f6' -or
       $after.previous_source_manifest_sha256 -cne '6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1' -or
       $after.reviewed_repair -cne 'src/cochem_pipeline/resource_telemetry.py' -or $after.reviewed_repair_sha256 -cne $repairPin -or
       $after.configuration_unchanged -isnot [bool] -or $after.configuration_unchanged -ne $true -or $null -ne $after.only_config_change -or
       ($after.verified_entries -isnot [int] -and $after.verified_entries -isnot [long]) -or $after.verified_entries -lt 10000 -or
       $after.preserved_denial_receipt_sha256 -cne '691c70560436f948464c529b9d2d6a3e33ce240749642af86ca79c748791461d' -or
       $after.preserved_denial_task_terminal_check_deferred -isnot [bool] -or $after.preserved_denial_task_terminal_check_deferred -ne $false -or
       $after.preserved_worker_cleanup_verified -isnot [bool] -or $after.preserved_worker_cleanup_verified -ne $false -or
       $after.source_files -isnot [int] -or $after.source_files -ne 166 -or @($after.holds).Count -ne 0 -or
       $after.accounts_provisioned -isnot [int] -or $after.accounts_provisioned -ne 0 -or $after.tasks_changed -isnot [int] -or $after.tasks_changed -ne 0 -or
       $after.credentials_modified -isnot [bool] -or $after.credentials_modified -ne $false -or $after.databases_modified -isnot [bool] -or $after.databases_modified -ne $false -or
       $after.ram_modified -isnot [bool] -or $after.ram_modified -ne $false -or $after.pipeline_started -isnot [bool] -or $after.pipeline_started -ne $false -or
       $after.activation_ready -isnot [bool] -or $after.activation_ready -ne $false -or
       $after.verification.configuration_parsed -isnot [bool] -or $after.verification.configuration_parsed -ne $true -or
       $after.verification.telemetry_repair_installed -isnot [bool] -or $after.verification.telemetry_repair_installed -ne $true -or
       $after.verification.no_system_or_model_execution -isnot [bool] -or $after.verification.no_system_or_model_execution -ne $true -or
       $after.verification.ram_workspace_root -cne 'R:\CoChem427-windows-20261007' -or
       $revision.schema -cne 'cochem-installed-revision/1' -or $revision.verified -isnot [bool] -or $revision.verified -ne $true -or
       $revision.read_only -isnot [bool] -or $revision.read_only -ne $true -or $revision.files -isnot [int] -or $revision.files -ne 109 -or
       $revision.source_sha256 -cne $revisionPin -or $revision.acceptance_files -isnot [int] -or $revision.acceptance_files -ne 0 -or $null -ne $revision.acceptance_sha256){throw 'Successful r4 source/config/revision receipt bindings differ.'}
    if($after.runtime_bindings.pyvenv_sha256 -cne '0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d' -or
       $after.runtime_bindings.venv_python_sha256 -cne '560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e' -or
       $after.runtime_bindings.base_python_sha256 -cne 'd8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa' -or
       $after.runtime_bindings.base_root -cne 'C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312'){throw 'R4 runtime binding receipt differs.'}
    $manifest=(Read-R3Text (Read-R3Control (Join-Path $root 'source-manifest.json') $manifestPin))|ConvertFrom-Json
    if($manifest.schema -cne 'cochem-stopped-runtime-source/1' -or $manifest.target_root -cne $root -or $manifest.complete_source_freeze -isnot [bool] -or $manifest.complete_source_freeze -ne $true -or
       @($manifest.files).Count -ne 166 -or $manifest.previous_source_manifest_sha256 -cne '6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1' -or
       @($manifest.changes_from_previous_source.added).Count -ne 0 -or @($manifest.changes_from_previous_source.removed).Count -ne 0 -or
       @($manifest.changes_from_previous_source.changed).Count -ne 1 -or @($manifest.changes_from_previous_source.changed)[0] -cne 'src/cochem_pipeline/resource_telemetry.py'){throw 'Frozen r4 manifest binding differs.'}
    $null=Read-R3Control (Join-Path $root 'pipeline.json') $configPin
    $null=Read-R3Control (Join-Path $root 'windows-layout.json') '8430fdf1109c63c4a89479f03da8a465dfebf5566c7791c64f868202170672c4'
    $null=Read-R3Control (Join-Path $root '.venv\pyvenv.cfg') '0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d'
    $null=Read-R3Control (Join-Path $root '.venv\Scripts\python.exe') '560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'
    $null=Read-R3Control (Join-Path $root '.venv\Lib\site-packages\cochem_pipeline\resource_limits.py') 'de7fac91e32cef2f854bd53487037352bbc0915f95aaf987ee8a4a543317915f'
    $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase);$assets=0;$repairRows=0
    foreach($row in $manifest.files){
        $key=[string]$row.relative
        if($key -match '[\\:]' -or $key.StartsWith('/') -or @($key.Split('/')|Where-Object{$_ -in @('','.','..')}).Count -or
           ($key -cnotmatch '^src/' -and $key -cnotin @('README.md','pyproject.toml','uv.lock')) -or -not $seen.Add($key) -or
           $row.sha256 -cnotmatch '^[a-f0-9]{64}$' -or $row.length -lt 0 -or $row.length -gt 16777216){throw 'Unsafe frozen r4 source row.'}
        if($key -ceq 'src/cochem_pipeline/resource_telemetry.py'){if($row.sha256 -cne $repairPin){throw 'Frozen r4 repair row differs.'};$repairRows++}
        $control=Read-R3Control (Join-Path (Join-Path $root 'source') $key) $row.sha256
        if($control.Length -ne $row.length){throw 'Source length differs.'}
        if($key -cmatch '^src/(cochem_pipeline|cochem_mcp|cochem_supervisor)/.+\.(py|md|json|xml)$'){
            $control=Read-R3Control (Join-Path (Join-Path $root '.venv\Lib\site-packages') $key.Substring(4)) $row.sha256
            if($control.Length -ne $row.length){throw 'Installed asset differs from manifest.'};$assets++
        }
    }
    if($assets -ne 109 -or $repairRows -ne 1){throw 'Installed package inventory differs.'}
    [ordered]@{install_receipt_sha256=$afterControl.Sha256;source_manifest_sha256=$manifestPin;configuration_sha256=$configPin;revision=$revision;source_files_verified=166;installed_assets_verified=$assets;reviewed_repair_sha256=$repairPin}
}

function Assert-VenvBinding {
    param([string]$Text)
    $values=@{}
    foreach($line in ($Text -split '\r?\n')){
        if(-not $line.Trim()){continue}
        if($line -notmatch '^([^=]+?)\s*=\s*(.*)$'){throw 'Unexpected pyvenv record.'}
        $key=$matches[1].Trim()
        if($values.ContainsKey($key)){throw 'Duplicate pyvenv key.'}
        $values[$key]=$matches[2].Trim()
    }
    $expected=@{home=$basePythonRoot;implementation='CPython';uv='0.12.17';version_info='3.12.13';'include-system-site-packages'='false';prompt='cochem'}
    if($values.Count -ne $expected.Count){throw 'Expected the six-key uv venv format.'}
    foreach($key in $expected.Keys){if(-not $values.ContainsKey($key) -or $values[$key] -cne $expected[$key]){throw 'Venv interpreter/policy differs from the reviewed protected toolchain.'}}
}

function Add-AuthStatusFailureMetadata {
 param($Summary,$Receipt)
 if($null -ne $Receipt.PSObject.Properties['failure']){
  $f=$Receipt.failure
  if($f.phase -cnotin @('trusted_preflight','reservation','runtime_custody','layout','boundaries','native_custody','native_launch','native_attestation','native_wait','native_cleanup','native_result','daemon_postcheck') -or
     $f.error_type -cnotmatch '^[A-Za-z][A-Za-z0-9_]{0,79}$' -or
     ($null -ne $f.winerror -and (($f.winerror -isnot [int] -and $f.winerror -isnot [long]) -or $f.winerror -lt 0 -or $f.winerror -gt 4294967295))){throw 'Invalid sanitized authentication failure metadata.'}
  $Summary.failure=[ordered]@{phase=$f.phase;error_type=$f.error_type;winerror=$f.winerror}
 }
 if($null -ne $Receipt.PSObject.Properties['native_exit_code']){
  if(($Receipt.native_exit_code -isnot [int] -and $Receipt.native_exit_code -isnot [long]) -or $Receipt.native_exit_code -lt -2147483648 -or $Receipt.native_exit_code -gt 4294967295){throw 'Invalid native exit metadata.'}
  $Summary.native_exit_code=$Receipt.native_exit_code
 }
}
function Assert-AuthStatusReceipt {
 param($Value,$Task,$Runtime,[string]$Slot,[string]$Provider,[string]$Stage,[string]$Nonce,[string]$SourceHash,[string]$Attempt)
 if($Provider -cnotin @('codex','claude','gemini')){throw 'Status receipt names an unreviewed provider contract.'}
 if($Value.attempt -cne $Attempt -or $Value.schema -cne 'cochem-worker-native-auth-status/1' -or $Value.nonce -cne $Nonce -or $Value.stage -cne $Stage -or $Value.slot -cne $Slot -or $Value.provider -cne $Provider -or $Value.system_sid -cne 'S-1-5-18' -or $Value.helper_sha256 -cne $SourceHash -or
    $Value.runtime_root -cne 'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4' -or $Value.install_receipt_sha256 -cne $Runtime.install_receipt_sha256 -or $Value.source_manifest_sha256 -cne $Runtime.source_manifest_sha256 -or $Value.resource_limits_sha256 -cne 'de7fac91e32cef2f854bd53487037352bbc0915f95aaf987ee8a4a543317915f'){throw 'Status receipt identity/runtime binding differs.'}
 if($Value.status -ceq 'STATUS_CHECK_FAILED'){return 'HOLD'}
 if($Task.LastTaskResult -ne 0 -or $Value.config_sha256 -cne $Runtime.configuration_sha256 -or $Value.layout_sha256 -cne '8430fdf1109c63c4a89479f03da8a465dfebf5566c7791c64f868202170672c4' -or $Value.revision.verified -ne $true -or $Value.revision.source_sha256 -cne $Runtime.revision.source_sha256){throw 'Status receipt configuration/result binding differs.'}
 foreach($key in @('cleanup_verified','runtime_custody_verified','daemon_states_verified_before_and_after')){if($Value.$key -isnot [bool] -or $Value.$key -ne $true){throw 'Status receipt lacks verified physical custody/cleanup.'}}
 foreach($key in @('native_model_jobs_executed','login_commands_executed')){if(($Value.$key -isnot [int] -and $Value.$key -isnot [long]) -or $Value.$key -ne 0){throw 'Out-of-scope native execution was reported.'}}
 foreach($key in @('token_matches_selected_worker','image_matches_reviewed_executable','owned_job_membership_verified')){if($Value.process.$key -isnot [bool] -or $Value.process.$key -ne $true){throw 'Native status process identity was not verified.'}}
 $nativePin=switch -CaseSensitive ($Provider){'codex'{'fdda5fa3cf3fb3d000b876720742857676293e4315e4b045fae6f8bd7e866d1d'}'claude'{'0e4195524b73eb77efbdf3e2b36de5322a29f0ca575dfd2d9b4f946b1d425469'}'gemini'{'38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741'}}
 if($Value.native_executable_sha256_before -cne $nativePin -or $Value.native_executable_sha256_after -cne $nativePin -or $Value.native_status_commands_executed -ne 1){throw 'Native status command/executable binding differs.'}
 $a=$Value.authentication
 foreach($key in @('protocol_valid','logged_in','native_subscription_authentication_verified')){if($a.$key -isnot [bool]){throw 'Native status classification has invalid field types.'}}
 $result='HOLD';$expectedAuthKind=switch -CaseSensitive ($Provider){'codex'{'chatgpt'}'claude'{'claude.ai'}'gemini'{'google'}}
 if($a.protocol_valid -and $a.logged_in -and $a.native_subscription_authentication_verified -and $a.auth_kind -ceq $expectedAuthKind -and $Value.status -ceq 'NATIVE_SUBSCRIPTION_AUTHENTICATION_VERIFIED'){$result='REUSE_VERIFIED_SESSION'}
 elseif($a.protocol_valid -and -not $a.logged_in -and -not $a.native_subscription_authentication_verified -and $a.auth_kind -ceq 'none' -and $Value.status -ceq 'AUTHENTICATION_NOT_VERIFIED'){$result='ATTENDED_LOGIN_REQUIRED'}
 if($Value.decision -cne $result){throw 'Native status decision contradicts retained evidence.'}
 return $result
}
function Get-AuthStatusTaskResultView {
 param($Receipt,$Task)
 # O-F5: run() exits 2 for every HOLD classification and 0 for an established decision. A HOLD receipt requires
 # exactly 2 and is presented with 0 to Assert-AuthStatusReceipt (unchanged; the driver imports it by hash), so all
 # of its other checks, including the recomputed decision, still apply. Same rule as the r4-v1 driver's
 # Get-StatusTaskResultView; failed and established receipts keep the raw task.
 if($Receipt.status -cne 'STATUS_CHECK_FAILED' -and $Receipt.decision -ceq 'HOLD'){
  if($Task.LastTaskResult -ne 2){throw 'A HOLD status receipt requires task result 2.'}
  return [pscustomobject]@{LastTaskResult=0}
 }
 $Task
}

function Get-StatusTaskPresence {
    param($Folder,[string]$Name)
    # Exact presence or an explicit deferral; never a guess.
    try{$null=$Folder.GetTask($Name);return 'PRESENT'}catch{
        $errorItem=$_.Exception
        while($null -ne $errorItem){
            if($errorItem.HResult -eq -2147024894){return 'ABSENT'}
            if($errorItem.HResult -eq -2147024891){return 'ACCESS_DENIED_DEFERRED'}
            $errorItem=$errorItem.InnerException}
        throw ('Cannot establish exact Task Scheduler state of '+$Name+'; no native check is authorized by uncertainty.')}
}

function Get-DaemonTaskStates {
    param($Folder)
    # The four managed daemons must stay stopped and disabled. Observer/recorder tasks are deliberately not listed.
    $states=@()
    foreach($name in @('CoChem-4.2.7-Warden','CoChem-4.2.7-Supervisor','CoChem-4.2.2-Warden','CoChem-4.2.3-Supervisor')){
        $task=$null;$absent=$false;$denied=$false
        try{$task=$Folder.GetTask($name)}catch{
            $errorItem=$_.Exception
            while($null -ne $errorItem){
                if($errorItem.HResult -eq -2147024894){$absent=$true;break}
                if($errorItem.HResult -eq -2147024891){$denied=$true;break}
                $errorItem=$errorItem.InnerException}
            if(-not $absent -and -not $denied){throw ('Managed daemon task state is unknown: '+$name)}}
        if($absent){$states+=[pscustomobject]@{name=$name;state='ABSENT';active=$false};continue}
        if($denied){$states+=[pscustomobject]@{name=$name;state='ACCESS_DENIED_DEFERRED';active=$null};continue}
        try{$active=([bool]$task.Enabled -or [int]$task.State -notin @(1,3) -or [int]$task.GetInstances(0).Count -ne 0)}catch{
            $errorItem=$_.Exception;$partial=$false
            while($null -ne $errorItem){if($errorItem.HResult -eq -2147024891){$partial=$true;break};$errorItem=$errorItem.InnerException}
            if(-not $partial){throw ('Managed daemon task could not be read: '+$name)}
            $states+=[pscustomobject]@{name=$name;state='ACCESS_DENIED_DEFERRED';active=$null};continue}
        $states+=[pscustomobject]@{name=$name;state=$(if($active){'ACTIVE'}else{'STOPPED_DISABLED'});active=$active}
    }
    $states
}

function Get-AuthStatusHolds {
    param($Folder)
    $holds=@()
    foreach($path in @($script:python,$script:layout,$script:config,$script:native,$script:basePython,$script:venvConfig)){
        if(-not (Test-Path -LiteralPath $path -PathType Leaf)){$holds+=('A required stopped installation file is absent: '+$path);continue}
        try{Assert-ProtectedPath $path}catch{$holds+=('Protected ancestry of '+$path+': '+$_.Exception.Message)}
    }
    foreach($pin in @(@($script:native,$script:nativeHash),@($script:python,'560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'),@($script:basePython,'d8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa'),@($script:venvConfig,'0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d'))){
        if(-not (Test-Path -LiteralPath $pin[0] -PathType Leaf)){continue}
        try{
            $stream=Open-VerifiedFile $pin[0] $pin[1] (Get-Item -LiteralPath $pin[0]).Length
            try{if($pin[0] -eq $script:venvConfig){$reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8);Assert-VenvBinding $reader.ReadToEnd()}}finally{$stream.Dispose()}
        }catch{$holds+=('Pinned file '+$pin[0]+': '+$_.Exception.Message)}
    }
    if(Test-Path -LiteralPath $script:targetRoot){$holds+='This one-shot status root already exists; preserve its evidence, do not overwrite or rerun automatically.'}
    $statusTask=Get-StatusTaskPresence $Folder $script:taskName
    if($statusTask -ceq 'PRESENT'){$holds+='This one-shot status task already exists; preserve it.'}
    elseif($statusTask -ceq 'ACCESS_DENIED_DEFERRED'){$holds+='The one-shot status task name could not be read without elevation; re-read during -Apply.'}
    $daemons=@(Get-DaemonTaskStates $Folder)
    $active=@($daemons|Where-Object {$_.active -eq $true}|ForEach-Object {$_.name});$deferred=@($daemons|Where-Object {$_.state -eq 'ACCESS_DENIED_DEFERRED'}|ForEach-Object {$_.name})
    if($active.Count){$holds+=('Protected daemons must remain stopped and disabled: '+($active -join ', '))}
    if($deferred.Count){$holds+=('Protected daemon task definitions are unreadable without elevation; re-read during -Apply: '+($deferred -join ', '))}
    [pscustomobject]@{holds=$holds;daemon_tasks=$daemons;status_task=$statusTask}
}

function Get-AuthStatusArguments {
    param([string]$Destination,[string]$Slot,[string]$Provider,[string]$Nonce,[string]$Stage,[string]$Attempt)
    '-I -B "'+$Destination+'" --slot '+$Slot+' --provider '+$Provider+' --nonce '+$Nonce+' --stage '+$Stage+' --attempt '+$Attempt
}

function Assert-AuthStatusTaskDefinition {
    param($Task,[string]$Arguments)
    # Read back exactly what was registered: one SYSTEM action, no trigger, bounded limit, private DACL.
    $d=$Task.Definition
    if($d.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or $d.Principal.LogonType -ne 5 -or $d.Principal.RunLevel -ne 1 -or $d.Triggers.Count -ne 0 -or $d.Actions.Count -ne 1 -or
       $d.Actions.Item(1).Path -cne $script:python -or $d.Actions.Item(1).Arguments -cne $Arguments -or $d.Actions.Item(1).WorkingDirectory -cne $script:targetRoot -or
       $d.Settings.MultipleInstances -ne 2 -or $d.Settings.ExecutionTimeLimit -cne $script:taskTimeLimit){throw 'Registered status task action/identity differs.'}
    Assert-RegisteredTaskAcl ([string]$Task.GetSecurityDescriptor(7))
}

function Register-AuthStatusTask {
    param($Scheduler,$Folder,[string]$Arguments)
    # Create-only ($script:taskRegistrationFlags = 18 = TASK_CREATE|TASK_DONT_ADD_PRINCIPAL_ACE, never TASK_UPDATE): an existing
    # task of this one-shot name is never replaced. No trigger is added.
    $definition=$Scheduler.NewTask(0)
    $definition.RegistrationInfo.Description='One bounded native authentication-status command in one isolated worker profile of the r4 runtime. No login, model inference, daemon activation, credential copying or budget changes.'
    $definition.Principal.UserId='SYSTEM';$definition.Principal.LogonType=5;$definition.Principal.RunLevel=1
    $definition.Settings.Enabled=$true;$definition.Settings.AllowDemandStart=$true
    $definition.Settings.MultipleInstances=2;$definition.Settings.ExecutionTimeLimit=$script:taskTimeLimit
    $action=$definition.Actions.Create(0);$action.Path=$script:python
    $action.Arguments=$Arguments
    $action.WorkingDirectory=$script:targetRoot
    $Folder.RegisterTaskDefinition($script:taskName,$definition,$script:taskRegistrationFlags,'SYSTEM',$null,5,$script:taskSddl)
}

function Wait-StatusTaskInstance {
    param($Instance,[int]$TimeoutSeconds=175)
    $deadline=[DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        Start-Sleep -Milliseconds 250
        try {$Instance.Refresh()} catch {
            $completed=$false;$exception=$_.Exception
            while ($null -ne $exception) {if ($exception.HResult -eq -2147216629) {$completed=$true;break};$exception=$exception.InnerException}
            # SCHED_E_TASK_NOT_RUNNING ends polling only; it never proves success.
            if ($completed) {return}
            throw
        }
        if ([DateTime]::UtcNow -gt $deadline) {throw 'Status task wait timed out. Preserve task/root; its limit is three minutes. Cleanup is unverified: keep all pipeline tasks disabled and do not retry automatically.'}
    }while($Instance.State -in @(2,4))
}

function Assert-CompletedStatusTask {
    param($Task)
    if($Task.State -notin @(1,3) -or $Task.GetInstances(0).Count -ne 0){throw 'Status task is not conclusively terminal; preserve root/task and refuse its receipt.'}
}

function Get-AuthStatusHeldMessage {
    param([string]$Phase,[string]$Reason)
    $tail=' Preserve '+$script:targetRoot+' and the task '+$script:taskName+'; review status-held.json. No browser login or automatic retry is authorized.'
    switch -CaseSensitive ($Phase){
        'COPY'{'The status check is held while copying the reviewed helper: '+$Reason+' No task was registered.'+$tail}
        'REGISTER'{'The status check is held at task registration: '+$Reason+' The task may exist but was never run.'+$tail}
        'RUN'{'The status check is held at the single Run request: '+$Reason+$tail}
        'WAIT'{'The status check is held while waiting for the status task: '+$Reason+' Cleanup is unverified: keep all pipeline tasks disabled.'+$tail}
        'ROOT'{'The status check is held while creating its one-shot root: '+$Reason+' No task was registered. Preserve '+$script:targetRoot+' (the one-shot namespace is consumed) and review status-held.json. No browser login or automatic retry is authorized.'}
        'HOLD'{'Status is not an established subscription or explicit logged-out state. Preserve evidence; no browser login or automatic retry is authorized. Review '+(Join-Path $script:targetRoot 'status-held.json')+'.'}
        default{'The status check is held while binding its receipt: '+$Reason+$tail}
    }
}

function Invoke-AuthStatusApply {
    param($Scheduler,$Folder,$Runtime,[string]$Slot,[string]$Provider,[string]$Stage,[string]$Attempt)
    # Elevated: inspect the code trees once before the r4 interpreter runs as SYSTEM, then re-check every hold.
    $null=Assert-CodeTreeOnce $script:installRoot;$null=Assert-CodeTreeOnce $script:basePythonRoot;$null=Assert-CodeTreeOnce $script:nativeRoot
    $fresh=Get-AuthStatusHolds $Folder
    if(@($fresh.holds).Count){throw ('Status check is held. Nothing was changed: '+(@($fresh.holds) -join ' | '))}
    # The one-shot root is created inside the try (phase ROOT). Once it exists the namespace is consumed and every
    # failure leaves status-held.json; a root that was never created changes nothing.
    $phase='ROOT';$nonce=[Guid]::NewGuid().ToString('N');$task=$null;$registered=$false;$runRequested=$false;$rootVerified=$false
    $rootAbsentBefore=-not (Test-Path -LiteralPath $script:targetRoot)
    $receiptPath=Join-Path $script:targetRoot 'worker-native-status.json';$receiptControl=$null;$receipt=$null;$decision=$null;$summary=$null;$failure=$null
    try{
        New-ProtectedDirectory $script:targetRoot;$rootVerified=$true
        $phase='COPY'
        $destination=Join-Path $script:targetRoot $script:helperName
        $sourceLength=(Get-Item -LiteralPath $script:source).Length
        Copy-VerifiedPayload ([pscustomobject]@{source=$script:source;destination=$destination;sha256=$script:sourceHash;length=$sourceLength})
        $held.Add((Open-VerifiedFile $destination $script:sourceHash $sourceLength))
        $phase='REGISTER'
        $arguments=Get-AuthStatusArguments $destination $Slot $Provider $nonce $Stage $Attempt
        $task=Register-AuthStatusTask $Scheduler $Folder $arguments;$registered=$true
        Assert-AuthStatusTaskDefinition $task $arguments
        $phase='RUN'
        $instance=$task.Run($null);$runRequested=$true
        $phase='WAIT'
        Wait-StatusTaskInstance $instance $script:taskWaitSeconds
        Assert-CompletedStatusTask $task
        $phase='RECEIPT'
        if(-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)){throw ('Native status check has no receipt. LastTaskResult='+$task.LastTaskResult+'.')}
        Assert-ProtectedPath $receiptPath
        if((Get-Item -LiteralPath $receiptPath).Length -gt $script:receiptLimitBytes){throw 'Native status receipt exceeds its bound.'}
        $receiptControl=Read-R3Control $receiptPath '' $script:receiptLimitBytes
        $receipt=(Read-R3Text $receiptControl)|ConvertFrom-Json
        $phase='DECISION'
        $decision=Assert-AuthStatusReceipt $receipt (Get-AuthStatusTaskResultView $receipt $task) $Runtime $Slot $Provider $Stage $nonce $script:sourceHash $Attempt
        $summary=[ordered]@{schema='cochem-worker-native-auth-status-task-result/1';attempt=$Attempt;runtime_root=$script:installRoot;install_receipt_sha256=$Runtime.install_receipt_sha256;source_manifest_sha256=$Runtime.source_manifest_sha256;slot=$Slot;provider=$Provider;stage=$Stage;nonce=$nonce;decision=$decision;receipt_path=$receiptPath;receipt_sha256=$receiptControl.Sha256;status=$receipt.status;cleanup_verified=$receipt.cleanup_verified;last_task_result=$task.LastTaskResult;task_preserved=$true;native_model_jobs_executed=0;login_commands_executed=0;serving_model_verified=$false;ready_for_inference=$false;pipeline_started=$false}
        Add-AuthStatusFailureMetadata $summary $receipt
        if($decision -ceq 'HOLD'){$phase='HOLD';throw 'The receipt establishes neither a verified session nor an explicit logout.'}
        $phase='RESULT'
        $null=Write-RegistrationControl (Join-Path $script:targetRoot 'status-task-result.json') ($summary|ConvertTo-Json -Depth 5)
    }catch{$failure=$_.Exception.Message}
    if($null -ne $failure){
        if($phase -ceq 'ROOT' -and -not ($rootAbsentBefore -and (Test-Path -LiteralPath $script:targetRoot))){throw ('Status check is held before its one-shot root was created: '+$failure+' Nothing was changed.')}
        $latest=$null;try{if($null -ne $task){$latest=[ordered]@{state=[int]$task.State;last_task_result=[long]$task.LastTaskResult;instances=[int]$task.GetInstances(0).Count}}}catch{$latest=$null}
        $heldRecord=[ordered]@{schema='cochem-worker-native-auth-status-held/1';attempt=$Attempt;slot=$Slot;provider=$Provider;stage=$Stage;nonce=$nonce;phase=$phase;reason=$failure;
            target_root=$script:targetRoot;root_verified=$rootVerified;task_name=$script:taskName;task_registered=$registered;run_requested=$runRequested;task_after=$latest;
            receipt_path=$receiptPath;receipt_present=[bool](Test-Path -LiteralPath $receiptPath -PathType Leaf);receipt_sha256=$(if($null -ne $receiptControl){$receiptControl.Sha256}else{$null});
            decision=$(if($null -ne $decision){$decision}else{'HOLD'});summary=$summary;raw_provider_output_recorded=$false;login_authorized=$false;pipeline_started=$false;
            automatic_retry_allowed=$false;requires_owner_review=$true;recorded_utc=[DateTime]::UtcNow.ToString('o')}
        $heldNote=''
        try{$null=Write-RegistrationControl (Join-Path $script:targetRoot 'status-held.json') ($heldRecord|ConvertTo-Json -Depth 8)}catch{$heldNote=(' The held record could not be written: '+$_.Exception.Message)}
        if($phase -ceq 'HOLD' -and $null -ne $summary){Write-Host ('COCHEM_NATIVE_AUTH_STATUS_RESULT '+($summary|ConvertTo-Json -Depth 5 -Compress))}
        throw ((Get-AuthStatusHeldMessage $phase $failure)+$heldNote)
    }
    $summary
}

function Invoke-AuthStatusLeafMain {
    param([string]$Slot,[string]$Provider,[string]$Stage,[string]$Attempt,[bool]$ApplyRequested,[string]$ScriptRoot)
    if($Attempt -cnotmatch '^[a-f0-9]{32}$' -or ($ApplyRequested -and $Attempt -ceq '00000000000000000000000000000000')){throw 'A lowercase32-hex Attempt is required; Apply forbids the all-zero preview attempt.'}
    $ErrorActionPreference='Stop';Set-StrictMode -Version Latest
    $Slot=$Slot.ToLowerInvariant();$Provider=$Provider.ToLowerInvariant();$Stage=$Stage.ToLowerInvariant()
    if($Provider -cnotin @('codex','claude','gemini')){throw 'Only the reviewed codex, claude and gemini status contracts are supported.'}
    foreach($module in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$module\$module.psd1") -ErrorAction Stop}
    if($PSVersionTable.PSEdition -ne 'Desktop' -or -not [Environment]::Is64BitProcess -or $env:COMPUTERNAME -cne 'AETHERDESK'){throw 'Use 64-bit Windows PowerShell 5.1 on AETHERDESK.'}
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent();$admin=[Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if($ApplyRequested -and (-not $admin -or $identity.Name -cne 'AETHERDESK\ansac')){throw '-Apply requires the owner in Administrator Windows PowerShell; nothing was executed.'}
    Set-AuthStatusConstants $Slot $Provider $Stage $Attempt $ScriptRoot
    foreach($text in Get-AuthStatusHelperDefinitions){. ([scriptblock]::Create($text))}
    Initialize-FileIdentity
    $held=[Collections.Generic.List[IO.FileStream]]::new()
    try{
        $holds=@();$runtime=$null
        try{$runtime=Assert-R4InstalledBindings}catch{$holds+=('r4 stopped runtime is not the reviewed build: '+$_.Exception.Message)}
        try{$held.Add((Open-VerifiedFile $script:source $script:sourceHash (Get-Item -LiteralPath $script:source).Length))}catch{$holds+=('Reviewed status helper: '+$_.Exception.Message)}
        $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect();$folder=$scheduler.GetFolder('\')
        $state=Get-AuthStatusHolds $folder;$holds+=@($state.holds)
        $plan=[ordered]@{schema='cochem-worker-native-auth-status-plan/1';mode='READ_ONLY_PLAN';attempt=$Attempt;slot=$Slot;provider=$Provider;stage=$Stage;
            runtime_root=$script:installRoot;r4_runtime_verified=($null -ne $runtime);
            install_receipt_sha256=$(if($null -ne $runtime){$runtime.install_receipt_sha256}else{$null});source_manifest_sha256=$(if($null -ne $runtime){$runtime.source_manifest_sha256}else{$null});
            revision_sha256=$(if($null -ne $runtime){$runtime.revision.source_sha256}else{$null});
            owner=$identity.Name;administrator=$admin;source_sha256=$script:sourceHash;native_executable=$script:native;native_sha256=$script:nativeHash;
            native_status_arguments=@($script:nativeArguments[$Provider]);task_name=$script:taskName;target_root=$script:targetRoot;task_execution_time_limit=$script:taskTimeLimit;
            native_status_timeout_seconds=$script:statusTimeoutSeconds;native_output_limit_bytes=$script:outputLimitBytes;daemon_tasks=$state.daemon_tasks;status_task=$state.status_task;
            native_status_commands_executed=0;native_model_jobs_executed=0;logins_executed=0;tasks_changed=0;pipeline_started=$false;automatic_retry_allowed=$false;holds=$holds}
        if(-not $ApplyRequested){$plan|ConvertTo-Json -Depth 6;return}
        if($holds.Count){throw ('Status check is held. Nothing was changed: '+($holds -join ' | '))}
        $summary=Invoke-AuthStatusApply $scheduler $folder $runtime $Slot $Provider $Stage $Attempt
        $summary|ConvertTo-Json -Depth 5
    }finally{foreach($stream in $held){$stream.Dispose()}}
}

# Invocation boundary: the only top-level statement. Fixtures dot-source the functions above from the AST without running it.
Invoke-AuthStatusLeafMain -Slot $Slot -Provider $Provider -Stage $Stage -Attempt $Attempt -ApplyRequested ([bool]$Apply) -ScriptRoot $PSScriptRoot
