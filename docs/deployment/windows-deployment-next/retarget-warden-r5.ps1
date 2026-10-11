#Requires -Version 5.1
<# Reviewed CoChem-4.2.7-Warden retarget between the r4 and r5 runtimes: the r5 cutover (-Target r5) and the r4 restore
   (-Target r4). Derived from retarget-warden-r4.ps1 v2.2 (sha256 8ee6b412f6be176dfac7c2c1b2340f1973e08358c7d22da6d4515e79f0327a4e);
   every function shared with v2.2 that needs no target awareness is a byte-identical copy, and the reviewed helpers are
   imported by hash exactly as v2.2 does. ARMY_ADDENDUM_20261011 A1/A2 apply.

   Usage (owner, elevated 64-bit Windows PowerShell 5.1 on AETHERDESK for -Apply; without -Apply a read-only plan):
     retarget-warden-r5.ps1 -Target r5 -Config <config> -Attempt vN [-SourceAttempt vM [-StopAttempt vK]] [-Apply [-Start]]
     retarget-warden-r5.ps1 -Target r4 -Attempt vN [-SourceAttempt vM [-StopAttempt vK]] [-Apply [-Start]]
     <config> is a staged C:\Program Files\CoChem\WardenConfig4.2.7-windows-<date>-r5-vN\pipeline.json, or exactly the
     commissioning copy C:\Program Files\CoChem\WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json (sha 135cd9ec,
     the Gemini fallback). -Apply -StartOnly (or -Apply -Start on an attempt that already holds its retarget-receipt.json)
     starts that attempt once.

   Accepted source states, each with no task instance and port 47824 free (anything else is held and nothing changes). The
   live action selects r4-v1, an r5 attempt or an r4 restore attempt (WardenRetarget4.2.7-windows-20261011-<r5|r4>-<SourceAttempt>);
   the evidence in that attempt's root selects the state:
     r4-v1               the pinned r4-v1 action (down since the 2026-10-11 00:57 reboot; its queue directory is consumed),
                         Enabled true or false, no trigger, no -SourceAttempt/-StopAttempt.
     r5-retarget-receipt / r4-restore-retarget-receipt   -SourceAttempt alone: retargeted, never started. Its retarget receipt
                         (enabled_after false, trigger_enabled_after false for r5) binds the live action; no start evidence (live
                         XML == the receipt's task_xml_sha256) or a start-held.json proving the hold came before any instance
                         could start (held_before_run; live XML == its task_xml_after_sha256); task and trigger disabled.
     r5-retarget-held / r4-restore-retarget-held          -SourceAttempt alone, -Target r4 only: the attempt's TASK_UPDATE was
                         held at its readback (retarget-held.json MUTATION_READBACK whose readback shows the task disabled, no
                         instance and the live XML sha) or interrupted before its receipt (retarget-intent.json alone); the live
                         action is the intent's action_after, the description names the attempt, the SDDL and the XML outside
                         the retarget fields equal the captured before-files.
     r5-receipt / r4-restore-receipt                      -SourceAttempt and -StopAttempt: started (its start receipt binds the
                         live action and warden-task-started.xml, the r5 trigger enabled), then stopped by stop-warden-r5.
     r5-start-held / r4-restore-start-held                -SourceAttempt and -StopAttempt: a start that ran without a receipt
                         (interrupted, crashed, or held after Run before or after its health gate: start-held.json
                         stop_recovery_allowed, held_before_run false), then stopped by stop-warden-r5 -RecoverInterruptedStart
                         (start_binding START_INTERRUPTED_HELD, START_HELD_AFTER_HEALTH_GATE, START_HELD_BEFORE_HEALTH_GATE or
                         START_CRASHED_NO_RECORD). Only a hold before Run is recovered without a stop (retarget-receipt states).
     A stop receipt is always WardenStop4.2.7-windows-20261011-r5-<StopAttempt>\stop-receipt.json (cochem-warden-stop/2)
     naming retarget_target, retarget_attempt, the task XML read now, start_binding and the digests of the source attempt's
     retarget receipt, start intent, start receipt or start-held record and warden-task-after.xml, and the live trigger
     state; no stop-held.json there. Every started or stopped source's live XML equals its warden-task-after.xml outside the
     task and trigger Enabled flags (audit C-F5).

   Every TASK_UPDATE registers the task DISABLED, and for r5 its logon trigger DISABLED too. -Start is two-phase: it enables
   the task immediately before its single Run, and only after the health gate, the readback and the process proof pass does
   a second TASK_UPDATE enable the logon trigger, read back, write warden-task-started.xml and then start-receipt.json
   (trigger_enabled_after true). A host crash before that leaves at most a task whose trigger is disabled. Every held or
   interrupted start disables the task again (best effort, never End) and writes start-held.json (interrupted, stage,
   health_gate_passed, stop_recovery_allowed = not held_before_run or interrupted, held_before_run, trigger_enabled_after),
   so an unverified runtime cannot relaunch at the next logon; once start-receipt.json exists nothing is held. A start only
   starts the task its own attempt registered (live XML == its warden-task-after.xml outside the Enabled flags).

   -Target r5: action <r5 root>\.venv\Scripts\python.exe -I -B -m cochem_pipeline daemon --config "<staged config>"
     --queue-launch-output-root "C:\ProgramData\CoChemPipeline427\private\queue-launch-r5" --docker-wait-seconds 900, working
     directory the r5 root, and one LOGON trigger for AETHERDESK\ansac with a PT1M delay, so the Warden restarts itself after
     every reboot once the owner signs in (Docker Desktop runs in that session). The r5 install-after.json and the staged
     configuration cannot be pre-pinned: they are bound by content verification at run time, against the pinned reviewed
     freeze manifest, its 13 repair digests and the venv bytes (audit C-F4; no install-held.json), and a staged
     configuration only with its cochem-config-only-staging/2 receipt beside it and no staging-held record (audit C-F8).
   -Target r4: action <r4 root>\.venv\Scripts\python.exe with the commissioned <r4 root>\pipeline.json (135cd9ec...) and a
     fresh --queue-launch-output ...\private\queue-restart-20261011-r4-<Attempt>, no trigger (r4 lacks the reboot-safe
     options, so its queue directory is consumed by every start).
   Principal, settings (MultipleInstancesPolicy IgnoreNew, no execution time limit) and the private DACL are preserved and
   proved unchanged by an XML comparison outside Actions/Triggers/RegistrationInfo.

   -Apply proves no controller/worker is alive, probes the backup rights (robocopy /L) before any namespace is consumed,
   creates C:\Program Files\CoChem\WardenRetarget4.2.7-windows-20261011-<Target>-<Attempt> (refused when present), writes
   the task XML/SDDL and a durable intent, takes two robocopy /B copies of the private SQLite stores that must agree byte for
   byte (the pinned helper verifies one), and then makes the single TASK_UPDATE. -Start then requests exactly one Run
   (enabling a disabled task first and recording it) and accepts the controller only when /health answers twice with a
   stable SYSTEM identity from the target root, no active work, no quarantined slot, no execution quarantine, knowledge
   ready with authority_matches_capture, the Warden controller admitting work (r5 admission_ready; the flapping r4 ready
   is recorded, not gated), one running task instance, and the reported pid running the target daemon command (Toolchain
   image, target venv launcher parent) and owning the socket; then the r5 second phase enables the logon trigger.
   Every failure after the attempt root exists leaves retarget-held.json or start-held.json: a reviewed recovery is
   required, never an automatic retry. No stop, kill, delete, credential, RAM, knowledge or budget change ever occurs.

   The parameters carry no [Validate*] attribute on purpose: Assert-RetargetParameters validates every value (case-sensitive)
   before anything is read, and the main then copies the request into these script-scope variables. A script parameter
   variable keeps its attributes even when it was not bound, so that copy threw ValidationMetadataException for the empty
   value of an omitted -SourceAttempt or -StopAttempt (the 2026-10-11 17:22 R4-RESTORE). #>
[CmdletBinding()]
param([string]$Target,[string]$Config='',[switch]$Apply,[switch]$Start,[switch]$StartOnly,
      [string]$Attempt='v1',[string]$SourceAttempt='',
      [string]$StopAttempt='')

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

function Invoke-NativeJudged {
    # Windows PowerShell 5.1 turns native stderr into terminating errors under
    # ErrorActionPreference=Stop. Judge native commands by exit code only, and decode their
    # output as UTF-8 (every Python child runs with -X utf8).
    param([string]$Executable,[string[]]$Arguments)
    if(-not (Test-Path -LiteralPath $Executable -PathType Leaf)){throw ('Native executable is missing: '+$Executable)}
    $previous=$ErrorActionPreference;$previousEncoding=[Console]::OutputEncoding;$global:LASTEXITCODE=$null;$all=@();$code=$null
    try{$ErrorActionPreference='Continue';[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$all=@(& $Executable @Arguments 2>&1);$code=$global:LASTEXITCODE}
    finally{$ErrorActionPreference=$previous;[Console]::OutputEncoding=$previousEncoding}
    $stdout=@($all|Where-Object {$_ -isnot [Management.Automation.ErrorRecord]}|ForEach-Object {[string]$_})
    $stderr=@($all|Where-Object {$_ -is [Management.Automation.ErrorRecord]}|ForEach-Object {[string]$_.Exception.Message})
    [pscustomobject]@{code=$code;stdout=($stdout -join "`n");stderr=($stderr -join "`n")}
}

function Get-ExpectedArguments {
    param([string]$ConfigPath,[string]$QueuePath)
    '-I -B -m cochem_pipeline daemon --config "'+$ConfigPath+'" --queue-launch-output "'+$QueuePath+'"'
}

function Get-R5Arguments {
    param([string]$ConfigPath,[string]$QueueRoot,[int]$DockerWaitSeconds)
    # ARMY_ADDENDUM_20261011 A2: a fresh child of the queue root per start and a bounded wait for the Docker engine.
    '-I -B -m cochem_pipeline daemon --config "'+$ConfigPath+'" --queue-launch-output-root "'+$QueueRoot+'" --docker-wait-seconds '+$DockerWaitSeconds
}

function Test-ExactBool {param($Value,[bool]$Expected)($Value -is [bool]) -and ($Value -eq $Expected)}
function Test-ExactInt {param($Value,[long]$Expected)(($Value -is [int]) -or ($Value -is [long])) -and ([long]$Value -eq $Expected)}
function Test-Sha256Text {param($Value)($Value -is [string]) -and ($Value -cmatch '^[a-f0-9]{64}$')}

function Get-JsonMember {
    param($Object,[string]$Path)
    # A dotted lookup in parsed JSON that never guesses and never throws under StrictMode: $null when any step is absent.
    $current=$Object
    foreach($name in $Path.Split('.')){
        if($null -eq $current -or $current -isnot [Management.Automation.PSCustomObject]){return $null}
        $property=$current.PSObject.Properties[$name]
        if($null -eq $property){return $null}
        $current=$property.Value}
    ,$current
}

function Get-JsonProperty {
    param($Object,[string]$Name)
    # One property by its exact name (names may contain dots, such as the reviewed repair paths); $null when absent.
    if($null -eq $Object -or $Object -isnot [Management.Automation.PSCustomObject]){return $null}
    $property=$Object.PSObject.Properties[$Name]
    if($null -eq $property){return $null}
    ,$property.Value
}

function Get-JsonListField {
    param($Object,[string]$Name)
    # A JSON list read without guessing: valid only when the field is present and is a JSON array.
    if($null -eq $Object -or $Object -isnot [Management.Automation.PSCustomObject]){return [pscustomobject]@{valid=$false;items=@()}}
    $property=$Object.PSObject.Properties[$Name]
    if($null -eq $property -or $null -eq $property.Value -or $property.Value -isnot [Array]){return [pscustomobject]@{valid=$false;items=@()}}
    [pscustomobject]@{valid=$true;items=@($property.Value)}
}

function Get-TaskXmlSha256 {
    param([string]$Xml)
    # The one task XML hash of the r5 cutover: sha256 (lowercase hex) of the UTF-8 bytes, without a byte order mark, of the
    # exact string RegisteredTask.Xml returned, no normalization. stop-warden-r4.ps1 records task_xml_after_sha256 as the
    # return value of Write-RegistrationControl, which writes exactly these bytes and hashes the file, so both agree.
    $sha=[Security.Cryptography.SHA256]::Create()
    try{[BitConverter]::ToString($sha.ComputeHash([Text.UTF8Encoding]::new($false).GetBytes($Xml))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
}

function Assert-R4InstalledBindings {
    # The r4 stopped runtime must be the exact reviewed build: r3 + the telemetry repair.
    # Receipt booleans and counts must carry their native JSON types, not look-alike strings.
    $afterControl=Read-R3Control (Join-Path $script:r4Root 'install-after.json') '' 1048576
    $after=(Read-R3Text $afterControl)|ConvertFrom-Json;$revision=$after.verification.revision
    if($after.schema -cne 'cochem-stopped-runtime-update/1' -or $after.mode -cne 'FRESH_STOPPED_RUNTIME_READY' -or
       $after.target_root -cne $script:r4Root -or $after.previous_runtime_root -cne $script:r3Root -or
       $after.source_manifest_sha256 -cne $script:r4ManifestPin -or $after.configuration_sha256 -cne $script:configPin -or
       $after.reviewed_repair -cne 'src/cochem_pipeline/resource_telemetry.py' -or $after.reviewed_repair_sha256 -cne $script:repairPin -or
       $after.previous_install_receipt_sha256 -cne $script:r3InstallPin -or $after.previous_source_manifest_sha256 -cne $script:r3ManifestPin -or
       -not (Test-ExactBool $after.configuration_unchanged $true) -or -not (Test-ExactInt $after.source_files 166) -or @($after.holds).Count -ne 0 -or
       -not (Test-ExactInt $after.tasks_changed 0) -or -not (Test-ExactBool $after.pipeline_started $false) -or -not (Test-ExactBool $after.credentials_modified $false) -or
       -not (Test-ExactBool $after.databases_modified $false) -or -not (Test-ExactBool $after.ram_modified $false) -or
       -not (Test-ExactBool $after.verification.configuration_parsed $true) -or -not (Test-ExactBool $after.verification.telemetry_repair_installed $true) -or
       -not (Test-ExactBool $after.verification.no_system_or_model_execution $true) -or $after.verification.ram_workspace_root -cne 'R:\CoChem427-windows-20261007' -or
       $revision.schema -cne 'cochem-installed-revision/1' -or -not (Test-ExactBool $revision.verified $true) -or -not (Test-ExactBool $revision.read_only $true) -or
       -not (Test-ExactInt $revision.files 109) -or -not (Test-ExactInt $revision.acceptance_files 0) -or $revision.source_sha256 -cnotmatch '^[a-f0-9]{64}$' -or
       $revision.source_sha256 -ceq $script:r3RevisionPin){
        throw 'The r4 installation receipt is not the reviewed successful stopped-runtime build.'}
    if($after.runtime_bindings.pyvenv_sha256 -cne '0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d' -or
       $after.runtime_bindings.venv_python_sha256 -cne '560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e' -or
       $after.runtime_bindings.base_python_sha256 -cne $script:probePythonPin -or
       $after.runtime_bindings.base_root -cne $script:basePythonRoot){throw 'r4 runtime binding receipt differs.'}
    $manifest=(Read-R3Text (Read-R3Control (Join-Path $script:r4Root 'source-manifest.json') $script:r4ManifestPin))|ConvertFrom-Json
    if($manifest.schema -cne 'cochem-stopped-runtime-source/1' -or $manifest.target_root -cne $script:r4Root -or -not (Test-ExactBool $manifest.complete_source_freeze $true) -or
       @($manifest.files).Count -ne 166 -or @($manifest.changes_from_previous_source.changed).Count -ne 1 -or
       $manifest.changes_from_previous_source.changed[0] -cne 'src/cochem_pipeline/resource_telemetry.py'){throw 'Frozen r4 manifest binding differs.'}
    $null=Read-R3Control (Join-Path $script:r4Root 'pipeline.json') $script:configPin
    $null=Read-R3Control (Join-Path $script:r4Root '.venv\pyvenv.cfg') '0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d'
    $null=Read-R3Control $script:r4Python '560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'
    $null=Read-R3Control $script:basePython $script:probePythonPin
    # The installed package must carry the repair, not only the frozen source copy.
    $null=Read-R3Control (Join-Path $script:r4Root '.venv\Lib\site-packages\cochem_pipeline\resource_telemetry.py') $script:repairPin
    $null=Read-R3Control (Join-Path $script:r4Root 'source\src\cochem_pipeline\resource_telemetry.py') $script:repairPin
    [ordered]@{install_receipt_sha256=$afterControl.Sha256;source_manifest_sha256=$script:r4ManifestPin;configuration_sha256=$script:configPin;revision_sha256=$revision.source_sha256}
}

function Assert-R4Pins {
    param($Runtime)
    # The r4 install receipt and revision are pinned exactly (the v2.2 content bindings above accept any non-r3 revision).
    if($Runtime.install_receipt_sha256 -cne $script:r4InstallPin){throw 'The r4 installation receipt is not the pinned receipt.'}
    if($Runtime.revision_sha256 -cne $script:r4RevisionPin){throw 'The r4 installed revision is not the pinned revision.'}
    $Runtime
}

function Assert-R4RetargetLineage {
    # The task was last retargeted and started by the reviewed r4 v1 attempt; its receipts and after-XML are pinned and
    # its controller identity is carried into the intent as the old controller.
    $retargetControl=Read-R3Control (Join-Path $script:r4v1Root 'retarget-receipt.json') $script:r4v1RetargetReceiptPin 1048576
    $retarget=(Read-R3Text $retargetControl)|ConvertFrom-Json
    if($retarget.schema -cne 'cochem-warden-retarget/2' -or $retarget.status -cne 'WARDEN_RETARGETED_TO_R4_NOT_STARTED' -or $retarget.attempt -cne 'v1' -or
       $retarget.task_name -cne $script:taskName -or $retarget.to_runtime_root -cne $script:r4Root -or $retarget.action_path -cne $script:r4Python -or
       $retarget.working_directory -cne $script:r4Root -or $retarget.action_arguments -cne (Get-ExpectedArguments $script:commissioningConfig $script:queueR4v1) -or
       $retarget.queue_launch_output -cne $script:queueR4v1 -or $retarget.config_sha256 -cne $script:configPin -or
       $retarget.task_xml_after_sha256 -cne $script:r4v1TaskXmlPin){throw 'The r4 v1 retarget receipt does not bind the r4-v1 action.'}
    $startControl=Read-R3Control (Join-Path $script:r4v1Root 'start-receipt.json') $script:r4v1StartReceiptPin 1048576
    $started=(Read-R3Text $startControl)|ConvertFrom-Json
    if($started.schema -cne 'cochem-warden-start/2' -or $started.status -cne 'WARDEN_R4_RUNNING_HEALTH_VERIFIED' -or $started.attempt -cne 'v1' -or
       $started.task_name -cne $script:taskName -or $started.runtime_root -cne $script:r4Root){throw 'The r4 v1 start receipt does not bind the r4-v1 start.'}
    $xmlControl=Read-R3Control (Join-Path $script:r4v1Root 'warden-task-after.xml') $script:r4v1TaskXmlPin 1048576
    [ordered]@{retarget_receipt_sha256=$retargetControl.Sha256;start_receipt_sha256=$startControl.Sha256;task_xml_after_sha256=$xmlControl.Sha256;
        old_controller=[ordered]@{pid=$started.controller.pid;instance_id=$started.controller.instance_id;process_started_at=$started.controller.process_started_at}}
}

function Get-R5RootCandidates {
    @(Get-ChildItem -LiteralPath $script:base -Directory -Force -ErrorAction Stop|Where-Object {$_.Name -cmatch $script:r5RootPattern}|ForEach-Object {$_.FullName})
}

function Find-R5Root {
    # The installer sets the dated r5 root name; exactly one installed r5 root may exist, and its receipt must name it.
    $found=@(Get-R5RootCandidates)
    if($found.Count -ne 1){throw ('Expected exactly one installed r5 runtime root Pipeline4.2.7-windows-<date>-r5 under '+$script:base+'; found '+$found.Count+'.')}
    $found[0]
}

function Assert-R5InstalledBindings {
    param([string]$Root)
    # Content verification of the r5 stopped runtime (its install-after.json cannot be pre-pinned): the receipt must be the
    # successful fresh r5 build on top of the pinned r4 receipt and manifest, and every file it binds is re-hashed on disk
    # behind a deny-write handle that stays open for the whole run.
    $afterPath=Join-Path $Root 'install-after.json'
    if(Test-Path -LiteralPath (Join-Path $Root 'install-held.json')){throw 'The r5 runtime root holds install-held.json (a held installation); preserve it for review.'}
    $afterControl=Read-R3Control $afterPath '' 1048576
    $after=$null;try{$after=(Read-R3Text $afterControl)|ConvertFrom-Json}catch{throw 'The r5 installation receipt is not JSON.'}
    if($null -eq $after -or $after -isnot [Management.Automation.PSCustomObject]){throw 'The r5 installation receipt is not a JSON object.'}
    $repairs=Get-JsonMember $after 'reviewed_repairs';$repairPins=Get-JsonMember $after 'reviewed_repairs_sha256'
    $revisionSha=Get-JsonMember $after 'verification.revision.source_sha256';$manifestSha=Get-JsonMember $after 'source_manifest_sha256'
    if((Get-JsonMember $after 'schema') -cne 'cochem-stopped-runtime-update/1' -or (Get-JsonMember $after 'mode') -cne 'FRESH_STOPPED_RUNTIME_READY' -or
       (Get-JsonMember $after 'target_root') -cne $Root -or (Get-JsonMember $after 'previous_runtime_root') -cne $script:r4Root -or
       (Get-JsonMember $after 'previous_install_receipt_sha256') -cne $script:r4InstallPin -or (Get-JsonMember $after 'previous_source_manifest_sha256') -cne $script:r4ManifestPin -or
       -not (Test-Sha256Text $manifestSha) -or $manifestSha -ceq $script:r4ManifestPin -or
       (Get-JsonMember $after 'configuration_sha256') -cne $script:configPin -or -not (Test-ExactBool (Get-JsonMember $after 'configuration_unchanged') $true) -or
       -not (Test-ExactInt (Get-JsonMember $after 'source_files') 166) -or -not ((Get-JsonListField $after 'holds').valid) -or @((Get-JsonListField $after 'holds').items).Count -ne 0 -or
       -not (Test-ExactInt (Get-JsonMember $after 'tasks_changed') 0) -or -not (Test-ExactBool (Get-JsonMember $after 'pipeline_started') $false) -or
       -not (Test-ExactBool (Get-JsonMember $after 'credentials_modified') $false) -or -not (Test-ExactBool (Get-JsonMember $after 'databases_modified') $false) -or
       -not (Test-ExactBool (Get-JsonMember $after 'ram_modified') $false) -or
       -not (Test-ExactBool (Get-JsonMember $after 'verification.configuration_parsed') $true) -or
       -not (Test-ExactBool (Get-JsonMember $after 'verification.no_system_or_model_execution') $true) -or
       (Get-JsonMember $after 'verification.ram_workspace_root') -cne 'R:\CoChem427-windows-20261007' -or
       (Get-JsonMember $after 'verification.revision.schema') -cne 'cochem-installed-revision/1' -or
       -not (Test-ExactBool (Get-JsonMember $after 'verification.revision.verified') $true) -or -not (Test-ExactBool (Get-JsonMember $after 'verification.revision.read_only') $true) -or
       -not (Test-ExactInt (Get-JsonMember $after 'verification.revision.acceptance_files') 0) -or
       -not ((Get-JsonMember $after 'verification.revision.files') -is [int] -or (Get-JsonMember $after 'verification.revision.files') -is [long]) -or
       [long](Get-JsonMember $after 'verification.revision.files') -lt 1 -or
       -not (Test-Sha256Text $revisionSha) -or $revisionSha -ceq $script:r4RevisionPin -or $revisionSha -ceq $script:r3RevisionPin){
        throw 'The r5 installation receipt is not the reviewed successful stopped-runtime build on top of the pinned r4 runtime.'}
    # The reviewed freeze and the installer's own verification (audit C-F4): the pinned manifest, every repair installed and
    # verified, and the 153 unchanged files the freeze declares.
    if($manifestSha -cne $script:r5SourceManifestPin){throw 'The r5 installation receipt does not name the reviewed freeze manifest.'}
    if(-not (Test-ExactBool (Get-JsonMember $after 'verification.r5_repairs_installed') $true) -or -not (Test-ExactBool (Get-JsonMember $after 'installed_repairs_verified') $true) -or
       -not (Test-ExactInt (Get-JsonMember $after 'verified_unchanged') $script:r5VerifiedUnchanged)){
        throw ('The r5 installation receipt does not prove the reviewed repairs installed and verified with '+$script:r5VerifiedUnchanged+' verified unchanged files.')}
    $pyvenvSha=Get-JsonMember $after 'runtime_bindings.pyvenv_sha256';$venvPythonSha=Get-JsonMember $after 'runtime_bindings.venv_python_sha256'
    if($pyvenvSha -cne $script:r5PyvenvPin -or $venvPythonSha -cne $script:r5VenvPythonPin){throw 'The r5 venv bindings are not the pinned pyvenv.cfg and venv launcher.'}
    if(-not (Test-Sha256Text $pyvenvSha) -or -not (Test-Sha256Text $venvPythonSha) -or
       (Get-JsonMember $after 'runtime_bindings.base_python_sha256') -cne $script:probePythonPin -or
       (Get-JsonMember $after 'runtime_bindings.base_root') -cne $script:basePythonRoot){throw 'r5 runtime binding receipt differs from the pinned Toolchain interpreter.'}
    # The reviewed repairs: a non-empty unique list of package paths, mapped one-to-one to their pinned bytes, including the
    # __main__.py that carries the reboot-safe daemon options this action uses.
    if($null -eq $repairs -or $repairs -isnot [Array] -or @($repairs).Count -lt 1 -or $null -eq $repairPins -or $repairPins -isnot [Management.Automation.PSCustomObject]){
        throw 'The r5 installation receipt lacks the reviewed_repairs list and its reviewed_repairs_sha256 map.'}
    $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach($relative in @($repairs)){
        if($relative -isnot [string] -or $relative -cnotmatch '^src/cochem_(pipeline|supervisor)/[A-Za-z0-9_]+(/[A-Za-z0-9_]+)*\.py$' -or -not $seen.Add($relative)){throw 'The r5 reviewed repair list is not a unique list of package source paths.'}
        if(-not (Test-Sha256Text (Get-JsonProperty $repairPins $relative))){throw ('The r5 reviewed repair has no pinned sha256: '+$relative)}}
    if(@($repairPins.PSObject.Properties).Count -ne $seen.Count){throw 'The r5 reviewed repair pins do not map one-to-one to the reviewed repairs.'}
    if(-not $seen.Contains('src/cochem_pipeline/__main__.py')){throw 'The r5 build does not carry the reviewed __main__.py with the reboot-safe daemon options.'}
    # Exactly the reviewed repairs of the pinned freeze, each with its reviewed digest.
    if($seen.Count -ne @($script:r5RepairPins.Keys).Count){throw 'The r5 reviewed repairs are not exactly the repairs of the reviewed freeze.'}
    foreach($relative in @($script:r5RepairPins.Keys)){
        if(-not $seen.Contains($relative) -or (Get-JsonProperty $repairPins $relative) -cne $script:r5RepairPins[$relative]){throw ('The r5 reviewed repair is not the reviewed digest of the freeze: '+$relative)}}
    $manifest=$null;try{$manifest=(Read-R3Text (Read-R3Control (Join-Path $Root 'source-manifest.json') $manifestSha 4194304))|ConvertFrom-Json}catch{throw ('The r5 source manifest does not match its receipt: '+$_.Exception.Message)}
    $changes=Get-JsonMember $manifest 'changes_from_previous_source'
    $changedField=Get-JsonListField $changes 'changed';$changed=@($changedField.items)
    $added=Get-JsonListField $changes 'added';$removed=Get-JsonListField $changes 'removed'
    $changedSet=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal);foreach($item in $changed){if($item -is [string]){$null=$changedSet.Add($item)}}
    if((Get-JsonMember $manifest 'schema') -cne 'cochem-stopped-runtime-source/1' -or (Get-JsonMember $manifest 'target_root') -cne $Root -or
       -not (Test-ExactBool (Get-JsonMember $manifest 'complete_source_freeze') $true) -or @((Get-JsonListField $manifest 'files').items).Count -ne 166 -or
       -not $changedField.valid -or $changed.Count -ne $seen.Count -or $changedSet.Count -ne $seen.Count -or -not $changedSet.SetEquals($seen) -or
       ($added.valid -and @($added.items).Count -ne 0) -or ($removed.valid -and @($removed.items).Count -ne 0)){
        throw 'The frozen r5 manifest does not change exactly the reviewed repairs of the r4 source.'}
    # The frozen manifest must list every reviewed repair with the digest the receipt pins (the rule stop-warden-r5 applies too,
    # so a build this cutover accepts is never refused by its rollback stop).
    $listed=[Collections.Generic.Dictionary[string,string]]::new([StringComparer]::Ordinal)
    foreach($entry in @((Get-JsonListField $manifest 'files').items)){
        $listedName=Get-JsonProperty $entry 'relative';$listedSha=Get-JsonProperty $entry 'sha256'
        if($listedName -is [string] -and $listedSha -is [string] -and -not $listed.ContainsKey($listedName)){$listed[$listedName]=$listedSha}}
    foreach($relative in @($seen)){if(-not $listed.ContainsKey($relative) -or $listed[$relative] -cne (Get-JsonProperty $repairPins $relative)){throw ('The frozen r5 manifest does not list the reviewed digest of '+$relative)}}
    $null=Read-R3Control (Join-Path $Root 'pipeline.json') $script:configPin
    $null=Read-R3Control (Join-Path $Root '.venv\pyvenv.cfg') $pyvenvSha
    $python=Join-Path $Root '.venv\Scripts\python.exe'
    $null=Read-R3Control $python $venvPythonSha 4194304
    $null=Read-R3Control $script:basePython $script:probePythonPin 4194304
    # Both the frozen source copy and the installed package must carry every reviewed repair.
    foreach($relative in @($seen)){
        $pin=Get-JsonProperty $repairPins $relative;$windowsRelative=$relative.Replace('/','\')
        $null=Read-R3Control (Join-Path $Root ('source\'+$windowsRelative)) $pin
        $null=Read-R3Control (Join-Path $Root ('.venv\Lib\site-packages\'+$windowsRelative.Substring(4))) $pin}
    [ordered]@{root=$Root;python=$python;source_root=(Join-Path $Root '.venv\Lib');install_after_path=$afterPath;install_after_sha256=$afterControl.Sha256;
        source_manifest_sha256=$manifestSha;revision_sha256=$revisionSha;reviewed_repairs=@($repairs);venv_python_sha256=$venvPythonSha}
}

function Assert-R5Config {
    param([string]$Path)
    # Exactly two forms. (1) The staged r5 configuration, which cannot be pre-pinned: a NEW protected WardenConfig path holding
    # either the commissioned bytes (Gemini held) or the commissioned document with only providers.gemini changed. (2) The
    # Gemini fallback: exactly the commissioning copy WardenCommissioning...-r3-v1\pipeline.json, only with sha 135cd9ec.
    if([string]::IsNullOrEmpty($Path)){throw '-Target r5 requires -Config <staged r5 pipeline.json>.'}
    if($Path -ceq $script:commissioningConfig){
        $commissioning=Read-R3Control $Path $script:configPin 1048576
        return [ordered]@{path=$Path;sha256=$commissioning.Sha256;length=$commissioning.Length;mode='GEMINI_HELD_COMMISSIONING_FILE'}}
    if($Path -cnotmatch $script:r5ConfigPattern){throw ('The r5 configuration must be C:\Program Files\CoChem\WardenConfig4.2.7-windows-<date>-r5-vN\pipeline.json or exactly the commissioning copy '+$script:commissioningConfig+': '+$Path)}
    $control=Read-R3Control $Path '' 1048576
    $reference=Read-R3Control $script:r4RestoreConfig $script:configPin 1048576
    # Audit C-F8: the stager's receipt for exactly these bytes sits beside them, and no staging-held record.
    $staging=Assert-StagingReceipt $Path $control.Sha256
    if($control.Sha256 -ceq $script:configPin){return [ordered]@{path=$Path;sha256=$control.Sha256;length=$control.Length;mode='GEMINI_HELD_COMMISSIONED_BYTES';staging_receipt_path=$staging.path;staging_receipt_sha256=$staging.sha256}}
    $candidate=$null;$commissioned=$null
    try{$candidate=(Read-R3Text $control)|ConvertFrom-Json}catch{throw 'The staged r5 configuration is not JSON.'}
    $commissioned=(Read-R3Text $reference)|ConvertFrom-Json
    if($candidate -isnot [Management.Automation.PSCustomObject] -or $null -eq (Get-JsonMember $candidate 'providers') -or
       (Get-JsonMember $candidate 'providers') -isnot [Management.Automation.PSCustomObject] -or
       (Get-JsonMember $candidate 'providers.gemini') -isnot [Management.Automation.PSCustomObject]){throw 'The staged r5 configuration has no providers.gemini object.'}
    $candidateGemini=(Get-JsonMember $candidate 'providers.gemini')|ConvertTo-Json -Depth 64 -Compress
    $commissionedGemini=(Get-JsonMember $commissioned 'providers.gemini')|ConvertTo-Json -Depth 64 -Compress
    $candidate.providers.PSObject.Properties.Remove('gemini');$commissioned.providers.PSObject.Properties.Remove('gemini')
    if(($candidate|ConvertTo-Json -Depth 64 -Compress) -cne ($commissioned|ConvertTo-Json -Depth 64 -Compress)){throw 'The staged r5 configuration changes more than providers.gemini; preserve it for review.'}
    if($candidateGemini -ceq $commissionedGemini){throw 'The staged r5 configuration differs from the commissioned bytes without a providers.gemini change; preserve it for review.'}
    [ordered]@{path=$Path;sha256=$control.Sha256;length=$control.Length;mode='GEMINI_CONTRACT';staging_receipt_path=$staging.path;staging_receipt_sha256=$staging.sha256}
}

function Assert-StagingReceipt {
    param([string]$Path,[string]$Sha256)
    # The staged configuration's directory must hold a cochem-config-only-staging/2 receipt naming this path and these bytes,
    # and no staging-held-*.json (a held staging needs a reviewed recovery and another -Attempt). Returns the newest such receipt.
    $directory=Split-Path -Parent $Path
    $entries=@(Get-ChildItem -LiteralPath $directory -Force -File -ErrorAction Stop)
    $heldNames=@($entries|Where-Object {$_.Name -like 'staging-held-*.json'}|ForEach-Object {$_.Name})
    if($heldNames.Count){throw ('The staged r5 configuration directory holds a held staging record ('+(($heldNames|Sort-Object) -join ', ')+'); preserve it for review.')}
    $match=$null
    foreach($entry in @($entries|Where-Object {$_.Name -cmatch $script:stagingReceiptPattern}|Sort-Object Name)){
        $read=Read-JsonControl $entry.FullName 'The staging receipt'
        if((Get-JsonMember $read.value 'schema') -ceq $script:stagingReceiptSchema -and (Get-JsonMember $read.value 'staged_path') -ceq $Path -and
           (Get-JsonMember $read.value 'staged_sha256') -ceq $Sha256 -and (Get-JsonMember $read.value 'status') -cin @('STAGED','ALREADY_STAGED_IDENTICAL')){$match=$read}}
    if($null -eq $match){throw ('The staged r5 configuration has no '+$script:stagingReceiptSchema+' staging receipt naming '+$Path+' with sha256 '+$Sha256+'; stage it with stage-pipeline-config-r5-v1.ps1 -Apply.')}
    [ordered]@{path=$match.path;sha256=$match.sha256}
}

function Invoke-R5ConfigParser {
    param([string]$Python,[string]$Path)
    # Parser-only validation with the r5 interpreter (single-quoted Python only, as Windows PowerShell 5.1 argv requires).
    $code='import json,sys'+"`n"+'from cochem_pipeline.config import load_config'+"`n"+'c=load_config(sys.argv[1])'+"`n"+
        'print(json.dumps({''parser_valid'':True,''worker_identities'':len(c.workers),''max_shared_slots'':c.max_execution_slots,''knowledge_enabled'':bool(c.knowledge.enabled)}))'
    $result=Invoke-NativeJudged $Python @('-I','-B','-X','utf8','-c',$code,$Path)
    if($result.code -ne 0){throw ('The r5 configuration parser failed (exit '+$result.code+'): '+$result.stderr)}
    $parsed=$null;try{$parsed=$result.stdout|ConvertFrom-Json}catch{throw 'The r5 configuration parser printed no JSON.'}
    if(-not (Test-ExactBool (Get-JsonMember $parsed 'parser_valid') $true) -or -not (Test-ExactInt (Get-JsonMember $parsed 'worker_identities') 6) -or
       -not (Test-ExactInt (Get-JsonMember $parsed 'max_shared_slots') 4) -or -not (Test-ExactBool (Get-JsonMember $parsed 'knowledge_enabled') $true)){
        throw 'The r5 configuration does not load as six worker identities, four shared slots and enabled knowledge.'}
    $parsed
}

function Assert-ClientConfig {
    # The elevated health probe trusts the owner-writable client config only for the pinned port and token file, and holds
    # it behind a deny-write handle for the whole run.
    $stream=[IO.File]::Open($script:clientConfig,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);$held.Add($stream)
    $sha=[Security.Cryptography.SHA256]::Create()
    try{$digest=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
    $stream.Position=0;$reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true,4096,$true)
    try{$text=$reader.ReadToEnd()}finally{$reader.Dispose();$stream.Position=0}
    $value=$null;try{$value=$text|ConvertFrom-Json}catch{throw 'The client config is not JSON.'}
    if(-not (Test-ExactInt (Get-JsonMember $value 'port') $script:port) -or (Get-JsonMember $value 'token_file') -cne $script:tokenFile){
        throw ('The client config must name port '+$script:port+' and token file '+$script:tokenFile+'.')}
    [ordered]@{path=$script:clientConfig;sha256=$digest;port=$script:port}
}

function Get-TaskTriggerList {
    param($Definition)
    # Every trigger, read through the collection's 1-based Item; logon-only properties are read only from logon triggers.
    $list=@();$count=[int]$Definition.Triggers.Count
    for($index=1;$index -le $count;$index++){
        $trigger=$Definition.Triggers.Item($index);$type=[int]$trigger.Type;$userId=$null;$delay=$null
        if($type -eq 9){$userId=[string]$trigger.UserId;$delay=[string]$trigger.Delay}
        $list+=[pscustomobject]@{type=$type;enabled=[bool]$trigger.Enabled;user_id=$userId;delay=$delay;start_boundary=[string]$trigger.StartBoundary;
            end_boundary=[string]$trigger.EndBoundary;execution_time_limit=[string]$trigger.ExecutionTimeLimit;
            repetition_interval=[string]$trigger.Repetition.Interval;repetition_duration=[string]$trigger.Repetition.Duration}}
    ,$list
}

function Get-WardenTaskState {
    param($Folder)
    # Exact state or an explicit deferral; never a guess (v2.2, plus the trigger list).
    $task=$null
    try{$task=$Folder.GetTask($script:taskName)}catch{
        $errorItem=$_.Exception
        while($null -ne $errorItem){
            if($errorItem.HResult -eq -2147024894){throw 'The CoChem-4.2.7-Warden task is absent; there is nothing to retarget.'}
            if($errorItem.HResult -eq -2147024891){return [pscustomobject]@{readable=$false;task=$null}}
            $errorItem=$errorItem.InnerException}
        throw 'Warden task state is unknown.'}
    try{
        $definition=$task.Definition;$action=$definition.Actions.Item(1)
        return [pscustomobject]@{readable=$true;task=$task;enabled=[bool]$task.Enabled;state=[int]$task.State;instances=[int]$task.GetInstances(0).Count;
            last_task_result=[int]$task.LastTaskResult;user=[string]$definition.Principal.UserId;logon_type=[int]$definition.Principal.LogonType;run_level=[int]$definition.Principal.RunLevel;
            triggers=[int]$definition.Triggers.Count;trigger_list=(Get-TaskTriggerList $definition);actions=[int]$definition.Actions.Count;multiple_instances=[int]$definition.Settings.MultipleInstances;
            execution_time_limit=[string]$definition.Settings.ExecutionTimeLimit;restart_count=[int]$definition.Settings.RestartCount;allow_demand_start=[bool]$definition.Settings.AllowDemandStart;
            action_type=[int]$action.Type;action_path=[string]$action.Path;action_arguments=[string]$action.Arguments;action_working_directory=[string]$action.WorkingDirectory;
            sddl=[string]$task.GetSecurityDescriptor(7);xml=[string]$task.Xml}
    }catch{
        $errorItem=$_.Exception
        while($null -ne $errorItem){if($errorItem.HResult -eq -2147024891){return [pscustomobject]@{readable=$false;task=$null}};$errorItem=$errorItem.InnerException}
        throw 'Warden task definition could not be read.'}
}

function Get-OtherDaemonTaskStates {
    param($Folder)
    # The other managed daemons must stay stopped and disabled (every reference required this).
    $states=@()
    foreach($name in @('CoChem-4.2.7-Supervisor','CoChem-4.2.2-Warden','CoChem-4.2.3-Supervisor')){
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

function Assert-OtherDaemonsIdle {
    param($States)
    $active=@($States|Where-Object {$_.active -eq $true}|ForEach-Object {$_.name})
    if($active.Count){throw ('Managed daemon tasks must remain stopped and disabled: '+($active -join ', '))}
    $deferred=@($States|Where-Object {$_.state -eq 'ACCESS_DENIED_DEFERRED'}|ForEach-Object {$_.name})
    if($deferred.Count){throw ('Managed daemon task definitions are unreadable: '+($deferred -join ', '))}
}

function Assert-TaskDefinition {
    param($State,[string]$Message)
    # The reviewed SYSTEM daemon definition: principal, one Exec action, IgnoreNew, no execution time limit, no restarts.
    if($State.user -notin @('SYSTEM','S-1-5-18') -or $State.logon_type -ne 5 -or $State.run_level -ne 1 -or $State.actions -ne 1 -or
       $State.multiple_instances -ne 2 -or $State.execution_time_limit -cne 'PT0S' -or $State.restart_count -ne 0 -or $State.allow_demand_start -ne $true -or
       $State.action_type -ne 0){throw $Message}
}

function Get-TriggerReceiptForm {
    param([string]$Target)
    # The receipt form of the expected triggers: r5 one logon trigger, r4 none.
    $list=@();if($Target -ceq 'r5'){$list+=[ordered]@{type='logon';user_id=$script:logonUser;delay=$script:logonDelay}}
    ,$list
}

function Get-AccountSid {
    param([string]$Name)
    # The SID of an account name or SID string, or $null when it cannot be resolved (never a guess).
    if([string]::IsNullOrEmpty($Name)){return $null}
    try{
        if($Name -cmatch '^S-1-[0-9]+(-[0-9]+)+$'){return ([Security.Principal.SecurityIdentifier]::new($Name)).Value}
        ([Security.Principal.NTAccount]::new($Name)).Translate([Security.Principal.SecurityIdentifier]).Value
    }catch{$null}
}

function Test-SameAccount {
    param([string]$Actual,[string]$Expected)
    # Audit C-F2: Task Scheduler may read a logon trigger's user back as a SID or another spelling; equal SIDs are the same user.
    if($Actual -ceq $Expected){return $true}
    $actualSid=Get-AccountSid $Actual;$expectedSid=Get-AccountSid $Expected
    ($null -ne $actualSid) -and ($null -ne $expectedSid) -and ($actualSid -ceq $expectedSid)
}

function Assert-LogonTrigger {
    param($List,$Enabled=$false)
    # Exactly the reviewed reboot-safe trigger: one logon trigger for the owner (compared by SID) with a PT1M delay, no
    # repetition, no expiry and no trigger time limit (which would end the daemon). Two-phase start: every TASK_UPDATE
    # registers it DISABLED and only a start whose health gate passed enables it, so $Enabled names the state expected here
    # ($true, $false, or $null for either).
    $items=@($List)
    if($items.Count -ne 1){throw ('The task must have exactly one logon trigger; it has '+$items.Count+' trigger(s).')}
    $trigger=$items[0]
    if($trigger.type -ne 9 -or -not (Test-SameAccount ([string]$trigger.user_id) $script:logonUser) -or $trigger.delay -cne $script:logonDelay -or
       $trigger.end_boundary -cne '' -or $trigger.repetition_interval -cne '' -or $trigger.execution_time_limit -cnotin @('','PT0S')){
        throw ('The task trigger is not the reviewed '+$script:logonUser+' logon trigger with a '+$script:logonDelay+' delay.')}
    if($null -ne $Enabled -and [bool]$trigger.enabled -ne [bool]$Enabled){
        throw ('The reviewed logon trigger is '+$(if($trigger.enabled){'enabled'}else{'disabled'})+'; it must be '+$(if($Enabled){'enabled (after a verified start)'}else{'disabled (until a verified start enables it)'})+'.')}
}

function Get-LiveTriggerEnabled {
    param($State,[string]$Target)
    # The live logon trigger's Enabled flag for r5 (one trigger), $null for r4 (no trigger) or an unreadable task.
    if($null -eq $State -or -not $State.readable -or $Target -cne 'r5'){return $null}
    $items=@($State.trigger_list)
    if($items.Count -ne 1){return $null}
    [bool]$items[0].enabled
}

function Test-TriggerReceiptValue {
    param($Value,[string]$Target)
    # A receipt's triggers field: r5 exactly one {type logon, user_id, delay}; r4 an empty array.
    if($null -eq $Value -or $Value -isnot [Array]){return $false}
    $items=@($Value)
    if($Target -ceq 'r4'){return ($items.Count -eq 0)}
    if($items.Count -ne 1){return $false}
    ((Get-JsonMember $items[0] 'type') -ceq 'logon') -and ((Get-JsonMember $items[0] 'user_id') -ceq $script:logonUser) -and ((Get-JsonMember $items[0] 'delay') -ceq $script:logonDelay)
}

function Read-JsonControl {
    param([string]$Path,[string]$What)
    # A bounded JSON control file read behind a deny-write handle; anything but a JSON object is refused.
    $control=Read-R3Control $Path '' 1048576
    $value=$null;try{$value=(Read-R3Text $control)|ConvertFrom-Json}catch{$value=$null}
    if($null -eq $value -or $value -isnot [Management.Automation.PSCustomObject]){throw ($What+' is not a JSON object.')}
    [pscustomobject]@{path=$Path;sha256=$control.Sha256;value=$value}
}

function Test-ReceiptActionEqualsLive {
    param($Receipt,$State)
    # The receipt's action object equals the live action, ordinal and exact, field by field.
    $execute=Get-JsonMember $Receipt 'action.execute';$arguments=Get-JsonMember $Receipt 'action.arguments';$directory=Get-JsonMember $Receipt 'action.working_directory'
    ($execute -is [string]) -and ($arguments -is [string]) -and ($directory -is [string]) -and
    ($State.action_path -ceq $execute) -and ($State.action_arguments -ceq $arguments) -and ($State.action_working_directory -ceq $directory)
}

function Get-R4RestoreQueueAttempt {
    param($State)
    # The r4 restore form this script registers: r4 python and root, the commissioned r4-root configuration and a
    # queue-restart-20261011-r4-vN directory. Returns vN, or $null for any other action.
    if($State.action_path -cne $script:r4Python -or $State.action_working_directory -cne $script:r4Root){return $null}
    $queuePrefix=Join-Path $script:privateRoot ('queue-restart-'+$script:namespaceDate+'-r4-')
    $match=[regex]::Match([string]$State.action_arguments,'^'+[regex]::Escape('-I -B -m cochem_pipeline daemon --config "'+$script:r4RestoreConfig+'" --queue-launch-output "'+$queuePrefix)+'(v[0-9]{1,3})"$')
    if(-not $match.Success){return $null}
    $attempt=$match.Groups[1].Value
    if($State.action_arguments -cne (Get-ExpectedArguments $script:r4RestoreConfig ($queuePrefix+$attempt))){return $null}
    $attempt
}

function Test-R5ActionForm {
    param($State)
    # The reboot-safe r5 form (addendum A2): an installed r5 root, its venv python, any configuration path, the r5 queue root.
    $root=[string]$State.action_working_directory
    if($root -cnotmatch ('^'+[regex]::Escape((Join-Path $script:programFiles 'CoChem')+'\')+'Pipeline4\.2\.7-windows-[0-9]{8}-r5$')){return $false}
    if($State.action_path -cne (Join-Path $root '.venv\Scripts\python.exe')){return $false}
    $match=[regex]::Match([string]$State.action_arguments,'^-I -B -m cochem_pipeline daemon --config "([^"]+)" ')
    $match.Success -and ($State.action_arguments -ceq (Get-R5Arguments $match.Groups[1].Value $script:r5QueueRoot $script:dockerWaitSeconds))
}

function Test-ActionObjectEqualsLive {
    param($Action,$State)
    # An action object {execute, arguments, working_directory} equals the live action, ordinal and exact, field by field.
    $execute=Get-JsonProperty $Action 'execute';$arguments=Get-JsonProperty $Action 'arguments';$directory=Get-JsonProperty $Action 'working_directory'
    ($execute -is [string]) -and ($arguments -is [string]) -and ($directory -is [string]) -and
    ($State.action_path -ceq $execute) -and ($State.action_arguments -ceq $arguments) -and ($State.action_working_directory -ceq $directory)
}

function New-SourceRecord {
    param([string]$SourceState,$Live,[hashtable]$Fields)
    # One shape for every accepted source state (the intent and the receipts copy it); unset fields stay null.
    $record=[ordered]@{source_state=$SourceState;source_attempt=$null;stop_attempt=$null;source_receipt_path=$null;source_receipt_sha256=$null;source_start_receipt_sha256=$null;
        source_start_evidence=$null;source_start_intent_sha256=$null;source_start_held_sha256=$null;source_retarget_held_sha256=$null;source_mutation_evidence=$null;
        stop_receipt_path=$null;stop_receipt_sha256=$null;stop_status=$null;stop_start_binding=$null;source_config_sha256=$null;enabled_before=$Live.enabled;
        trigger_enabled_before=(Get-LiveTriggerEnabled $Live 'r5');task_xml_sha256=(Get-TaskXmlSha256 $Live.xml)}
    foreach($key in @($Fields.Keys)){if(-not $record.Contains($key)){throw ('Unknown source record field: '+$key)};$record[$key]=$Fields[$key]}
    $record
}

function Get-SourceLabel {
    param([string]$SourceTarget)
    if($SourceTarget -ceq 'r5'){return 'r5 attempt'}
    'r4 restore attempt'
}

function Assert-StopLineage {
    param($State,[string]$RetargetTarget,$Expect)
    # One stop-warden-r5 namespace for both runtimes: its receipt must name this source attempt and runtime, prove the
    # task ended (or was already stopped) and disabled, record exactly the task XML read now, and bind exactly the start
    # evidence of the source attempt (start_binding and the digests below), plus the live logon trigger state.
    $stopRoot=Join-Path $script:base ('WardenStop4.2.7-windows-'+$script:namespaceDate+'-r5-'+$script:StopAttempt)
    if(Test-Path -LiteralPath (Join-Path $stopRoot 'stop-held.json')){throw ('The stop-warden-r5 attempt '+$script:StopAttempt+' holds stop-held.json; a reviewed recovery is required.')}
    $read=Read-JsonControl (Join-Path $stopRoot 'stop-receipt.json') 'The stop-warden-r5 receipt';$stop=$read.value
    if((Get-JsonMember $stop 'schema') -cne 'cochem-warden-stop/2' -or
       (Get-JsonMember $stop 'status') -cnotin @('WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED','WARDEN_ALREADY_STOPPED_CLEAN_NOOP') -or
       (Get-JsonMember $stop 'retarget_target') -cne $RetargetTarget -or (Get-JsonMember $stop 'retarget_attempt') -cne $script:SourceAttempt -or
       (Get-JsonMember $stop 'task_name') -cne $script:taskName -or
       -not (Test-ExactBool (Get-JsonMember $stop 'enabled_after') $false) -or -not (Test-ExactInt (Get-JsonMember $stop 'instances_after') 0)){
        throw ('The stop-warden-r5 receipt of attempt '+$script:StopAttempt+' does not prove the '+$RetargetTarget+' attempt '+$script:SourceAttempt+' ended and disabled.')}
    if((Get-JsonMember $stop 'task_xml_after_sha256') -cne (Get-TaskXmlSha256 $State.xml)){throw 'The task XML changed since stop-warden-r5 recorded it (task_xml_after_sha256 differs); preserve it for review.'}
    $binding=Get-JsonMember $stop 'start_binding'
    if($binding -cne $Expect.start_binding -or (Get-JsonMember $stop 'retarget_receipt_sha256') -cne $Expect.retarget_receipt_sha256 -or
       (Get-JsonMember $stop 'start_intent_sha256') -cne $Expect.start_intent_sha256 -or (Get-JsonMember $stop 'start_receipt_sha256') -cne $Expect.start_receipt_sha256 -or
       (Get-JsonMember $stop 'start_held_sha256') -cne $Expect.start_held_sha256 -or (Get-JsonMember $stop 'source_task_xml_after_sha256') -cne $Expect.source_task_xml_after_sha256){
        throw ('The stop-warden-r5 receipt of attempt '+$script:StopAttempt+' does not bind the start evidence of the '+$RetargetTarget+' attempt '+$script:SourceAttempt+' ('+$Expect.start_binding+'); preserve it for review.')}
    $stopTrigger=Get-JsonMember $stop 'trigger_enabled_after';$liveTrigger=Get-LiveTriggerEnabled $State $RetargetTarget
    if(($RetargetTarget -ceq 'r5' -and ($stopTrigger -isnot [bool] -or $null -eq $liveTrigger -or $stopTrigger -ne $liveTrigger)) -or ($RetargetTarget -ceq 'r4' -and $null -ne $stopTrigger)){
        throw ('The stop-warden-r5 receipt of attempt '+$script:StopAttempt+' does not record the live logon trigger state (trigger_enabled_after); preserve it for review.')}
    [ordered]@{stop_receipt_path=$read.path;stop_receipt_sha256=$read.sha256;stop_status=(Get-JsonMember $stop 'status');stop_start_binding=$binding}
}

function Assert-SourceRetargetReceipt {
    param($State,[string]$SourceTarget,[string]$Root)
    # The source attempt's retarget receipt: a successful retarget of this attempt to $SourceTarget, registered disabled with
    # its logon trigger disabled (r5), whose recorded action is exactly the live one, and the warden-task-after.xml it pins,
    # whose registration Description names the attempt (audit C-F5).
    if(Test-Path -LiteralPath (Join-Path $Root 'retarget-held.json')){throw ('The '+$SourceTarget+' retarget attempt '+$script:SourceAttempt+' holds retarget-held.json; a reviewed recovery is required.')}
    $read=Read-JsonControl (Join-Path $Root 'retarget-receipt.json') ('The source '+$SourceTarget+' retarget receipt');$receipt=$read.value
    $status=$(if($SourceTarget -ceq 'r5'){'WARDEN_RETARGETED_TO_R5_NOT_STARTED'}else{'WARDEN_RETARGETED_TO_R4_NOT_STARTED'})
    if((Get-JsonMember $receipt 'schema') -cne 'cochem-warden-retarget/3' -or (Get-JsonMember $receipt 'status') -cne $status -or
       (Get-JsonMember $receipt 'target') -cne $SourceTarget -or (Get-JsonMember $receipt 'attempt') -cne $script:SourceAttempt -or (Get-JsonMember $receipt 'task_name') -cne $script:taskName -or
       ($SourceTarget -ceq 'r4' -and ((Get-JsonMember $receipt 'runtime_root') -cne $script:r4Root -or (Get-JsonMember $receipt 'config_path') -cne $script:r4RestoreConfig -or
        (Get-JsonMember $receipt 'config_sha256') -cne $script:configPin))){
        throw ('The source '+$SourceTarget+' retarget receipt does not bind attempt '+$script:SourceAttempt+'.')}
    if(-not (Test-ReceiptActionEqualsLive $receipt $State)){throw ('The live Warden action differs from the '+$SourceTarget+' action recorded by retarget attempt '+$script:SourceAttempt+'; preserve it for review.')}
    if(-not (Test-TriggerReceiptValue (Get-JsonMember $receipt 'triggers') $SourceTarget)){
        throw $(if($SourceTarget -ceq 'r5'){'The source r5 retarget receipt does not record the reviewed logon trigger.'}else{'The source r4 retarget receipt does not record an empty trigger list.'})}
    if(-not (Test-ExactBool (Get-JsonMember $receipt 'enabled_after') $false)){throw ('The source '+$SourceTarget+' retarget receipt does not record the task registered disabled (enabled_after false).')}
    $triggerAfter=Get-JsonMember $receipt 'trigger_enabled_after'
    if(($SourceTarget -ceq 'r5' -and -not (Test-ExactBool $triggerAfter $false)) -or ($SourceTarget -ceq 'r4' -and $null -ne $triggerAfter)){
        throw ('The source '+$SourceTarget+' retarget receipt does not record the logon trigger registered disabled (trigger_enabled_after).')}
    $afterSha=Get-JsonMember $receipt 'task_xml_after_sha256'
    if(-not (Test-Sha256Text $afterSha) -or (Get-JsonMember $receipt 'task_xml_sha256') -cne $afterSha){throw ('The source '+$SourceTarget+' retarget receipt does not record its task XML (task_xml_sha256, task_xml_after_sha256).')}
    $afterXml=Read-R3Text (Read-R3Control (Join-Path $Root 'warden-task-after.xml') $afterSha 1048576)
    if((Get-TaskXmlDescription $afterXml) -cne (Get-TargetDescription $SourceTarget $script:SourceAttempt)){
        throw ('The task XML recorded by the source '+$SourceTarget+' attempt '+$script:SourceAttempt+' does not carry that attempt''s registration description; preserve it for review.')}
    [pscustomobject]@{path=$read.path;sha256=$read.sha256;value=$receipt;after_xml=$afterXml;after_xml_sha256=$afterSha}
}

function Assert-SourceLiveTriggers {
    param($State,[string]$SourceTarget,$Enabled)
    # r5: the reviewed logon trigger in the expected state ($true, $false, or $null for either); r4 restore: no trigger.
    if($SourceTarget -ceq 'r5'){Assert-LogonTrigger $State.trigger_list $Enabled;return}
    if($State.triggers -ne 0 -or @($State.trigger_list).Count -ne 0){throw 'The r4 restore source task must have no trigger; preserve it for review.'}
}

function Assert-LiveXmlMatchesSource {
    param($State,$Retarget,[string]$SourceTarget)
    # Audit C-F5: the live task is the source attempt's task; only the task and trigger Enabled flags may differ from its
    # warden-task-after.xml (a start enables both, a stop disables the task).
    if((Get-TaskXmlWithoutEnabledFlags $State.xml -Triggers) -cne (Get-TaskXmlWithoutEnabledFlags $Retarget.after_xml -Triggers)){
        throw ('The live task XML differs from the warden-task-after.xml of the source '+$SourceTarget+' attempt '+$script:SourceAttempt+' outside the task and trigger Enabled flags; preserve it for review.')}
}

function Assert-StartedSourceLineage {
    param($State,[string]$SourceTarget,[string]$Root)
    # Source r5-receipt / r4-restore-receipt: an attempt whose start completed (its start receipt binds the live action and its
    # final task XML, the r5 logon trigger enabled), then ended and disabled by stop-warden-r5 without anything changing since.
    $label=Get-SourceLabel $SourceTarget
    if(Test-Path -LiteralPath (Join-Path $Root 'start-held.json')){throw ('The '+$label+' '+$script:SourceAttempt+' holds start-held.json; a reviewed recovery is required.')}
    $retarget=Assert-SourceRetargetReceipt $State $SourceTarget $Root
    $start=Read-JsonControl (Join-Path $Root 'start-receipt.json') ('The source '+$SourceTarget+' start receipt');$receipt=$start.value
    $status=$(if($SourceTarget -ceq 'r5'){'WARDEN_R5_RUNNING_HEALTH_VERIFIED'}else{'WARDEN_R4_RESTARTED_HEALTH_VERIFIED'})
    if((Get-JsonMember $receipt 'schema') -cne 'cochem-warden-start/3' -or (Get-JsonMember $receipt 'status') -cne $status -or
       (Get-JsonMember $receipt 'target') -cne $SourceTarget -or (Get-JsonMember $receipt 'attempt') -cne $script:SourceAttempt -or
       (Get-JsonMember $receipt 'task_name') -cne $script:taskName -or (Get-JsonMember $receipt 'runtime_root') -cne (Get-JsonMember $retarget.value 'runtime_root') -or
       (Get-JsonMember $receipt 'config_path') -cne (Get-JsonMember $retarget.value 'config_path') -or (Get-JsonMember $receipt 'config_sha256') -cne (Get-JsonMember $retarget.value 'config_sha256') -or
       -not (Test-ReceiptActionEqualsLive $receipt $State) -or -not (Test-TriggerReceiptValue (Get-JsonMember $receipt 'triggers') $SourceTarget) -or
       (Get-JsonMember $receipt 'retarget_receipt_sha256') -cne $retarget.sha256){
        throw ('The source '+$SourceTarget+' start receipt does not bind attempt '+$script:SourceAttempt+' and the live action.')}
    $startedSha=Get-JsonMember $receipt 'task_xml_sha256';$triggerBefore=Get-JsonMember $receipt 'trigger_enabled_before';$triggerAfter=Get-JsonMember $receipt 'trigger_enabled_after'
    if(-not (Test-Sha256Text $startedSha) -or (Get-JsonMember $receipt 'task_xml_started_sha256') -cne $startedSha -or
       ($SourceTarget -ceq 'r5' -and (-not (Test-ExactBool $triggerAfter $true) -or -not (Test-ExactBool $triggerBefore $false))) -or
       ($SourceTarget -ceq 'r4' -and ($null -ne $triggerAfter -or $null -ne $triggerBefore))){
        throw ('The source '+$SourceTarget+' start receipt does not record the verified two-phase start (task_xml_started_sha256, trigger_enabled_before/after); preserve it for review.')}
    $startedXml=Read-R3Text (Read-R3Control (Join-Path $Root 'warden-task-started.xml') $startedSha 1048576)
    $intent=Read-JsonControl (Join-Path $Root 'start-intent.json') ('The source '+$SourceTarget+' start intent')
    if((Get-JsonMember $receipt 'intent_sha256') -cne $intent.sha256){throw ('The source '+$SourceTarget+' start receipt does not bind the start intent of attempt '+$script:SourceAttempt+'.')}
    if($State.enabled -ne $false){throw ('An '+$SourceTarget+' source must be disabled by stop-warden-r5; the live task is enabled. Preserve it for review.')}
    Assert-SourceLiveTriggers $State $SourceTarget $(if($SourceTarget -ceq 'r5'){$true}else{$null})
    if((Get-TaskXmlWithoutEnabledFlags $State.xml) -cne (Get-TaskXmlWithoutEnabledFlags $startedXml)){
        throw ('The live task XML differs from the warden-task-started.xml of the source '+$SourceTarget+' attempt '+$script:SourceAttempt+' outside Settings/Enabled; preserve it for review.')}
    Assert-LiveXmlMatchesSource $State $retarget $SourceTarget
    $stop=Assert-StopLineage $State $SourceTarget ([ordered]@{start_binding='START_RECEIPT';retarget_receipt_sha256=$retarget.sha256;start_intent_sha256=$intent.sha256;
        start_receipt_sha256=$start.sha256;start_held_sha256=$null;source_task_xml_after_sha256=$retarget.after_xml_sha256})
    New-SourceRecord $(if($SourceTarget -ceq 'r5'){'r5-receipt'}else{'r4-restore-receipt'}) $State @{source_attempt=$script:SourceAttempt;stop_attempt=$script:StopAttempt;
        source_receipt_path=$retarget.path;source_receipt_sha256=$retarget.sha256;source_start_receipt_sha256=$start.sha256;source_start_evidence='START_RECEIPT';
        source_start_intent_sha256=$intent.sha256;stop_receipt_path=$stop.stop_receipt_path;stop_receipt_sha256=$stop.stop_receipt_sha256;stop_status=$stop.stop_status;
        stop_start_binding=$stop.stop_start_binding;source_config_sha256=(Get-JsonMember $retarget.value 'config_sha256')}
}

function Assert-HeldStartSourceLineage {
    param($State,[string]$SourceTarget,[string]$Root)
    # Source r5-start-held / r4-restore-start-held (audit C-F1(b), re-audit R-F1): a start was requested (start-intent.json)
    # and Run was called, but no start receipt was written: interrupted (start-held.json interrupted true), crashed (no record
    # at all), held after a passing health gate (its trigger enable or receipt failed) or held after Run before its health gate
    # passed (knowledge not ready, a quarantine, a process proof), then ended and disabled by stop-warden-r5
    # -RecoverInterruptedStart, which bound exactly this evidence. A hold before Run never comes here (it needs no stop).
    $label=Get-SourceLabel $SourceTarget
    $retarget=Assert-SourceRetargetReceipt $State $SourceTarget $Root
    $intent=Read-JsonControl (Join-Path $Root 'start-intent.json') ('The source '+$SourceTarget+' start intent');$value=$intent.value
    if((Get-JsonMember $value 'schema') -cne 'cochem-warden-start-intent/3' -or (Get-JsonMember $value 'attempt') -cne $script:SourceAttempt -or
       (Get-JsonMember $value 'target') -cne $SourceTarget -or (Get-JsonMember $value 'task_name') -cne $script:taskName -or
       (Get-JsonMember $value 'retarget_receipt_sha256') -cne $retarget.sha256){
        throw ('The source '+$SourceTarget+' start intent does not bind attempt '+$script:SourceAttempt+' and its retarget receipt.')}
    $heldPath=Join-Path $Root 'start-held.json';$heldSha=$null;$binding='START_CRASHED_NO_RECORD';$heldTrigger=$null
    if(Test-Path -LiteralPath $heldPath){
        $heldRecord=Read-JsonControl $heldPath ('The source '+$SourceTarget+' start-held record');$record=$heldRecord.value;$heldSha=$heldRecord.sha256
        $interrupted=Get-JsonMember $record 'interrupted';$gate=Get-JsonMember $record 'health_gate_passed';$allowed=Get-JsonMember $record 'stop_recovery_allowed'
        $beforeRun=Get-JsonMember $record 'held_before_run'
        if((Get-JsonMember $record 'schema') -cne 'cochem-warden-start-held/3' -or (Get-JsonMember $record 'target') -cne $SourceTarget -or
           (Get-JsonMember $record 'attempt') -cne $script:SourceAttempt -or (Get-JsonMember $record 'task_name') -cne $script:taskName -or
           -not (Test-ExactBool (Get-JsonMember $record 'receipt_written') $false) -or $interrupted -isnot [bool] -or $gate -isnot [bool] -or
           -not (Test-ExactBool $beforeRun $false) -or -not (Test-ExactBool (Get-JsonMember $record 'run_requested') $true) -or
           -not (Test-ExactBool $allowed $true) -or $allowed -ne ((-not $beforeRun) -or $interrupted)){
            throw ('The start-held record of the '+$label+' '+$script:SourceAttempt+' does not allow a stop recovery (stop_recovery_allowed true for a hold after Run): a hold before Run is the retarget-receipt source (-SourceAttempt alone); anything else needs the owner''s review.')}
        $binding=$(if($interrupted){'START_INTERRUPTED_HELD'}elseif($gate){'START_HELD_AFTER_HEALTH_GATE'}else{'START_HELD_BEFORE_HEALTH_GATE'})
        $heldTrigger=Get-JsonMember $record 'trigger_enabled_after'
        if(($null -ne $heldTrigger -and $heldTrigger -isnot [bool]) -or ($SourceTarget -ceq 'r4' -and $null -ne $heldTrigger)){
            throw ('The start-held record of the '+$label+' '+$script:SourceAttempt+' records an invalid trigger_enabled_after; preserve it for review.')}}
    if($State.enabled -ne $false){throw ('An '+$SourceTarget+' source must be disabled by stop-warden-r5; the live task is enabled. Preserve it for review.')}
    # The logon trigger is disabled until a verified start enables it; a held record that read it back binds its state, an
    # interruption or crash without one may have left it in either state (the XML comparison below binds everything else).
    Assert-SourceLiveTriggers $State $SourceTarget $heldTrigger
    Assert-LiveXmlMatchesSource $State $retarget $SourceTarget
    $stop=Assert-StopLineage $State $SourceTarget ([ordered]@{start_binding=$binding;retarget_receipt_sha256=$retarget.sha256;start_intent_sha256=$intent.sha256;
        start_receipt_sha256=$null;start_held_sha256=$heldSha;source_task_xml_after_sha256=$retarget.after_xml_sha256})
    New-SourceRecord $(if($SourceTarget -ceq 'r5'){'r5-start-held'}else{'r4-restore-start-held'}) $State @{source_attempt=$script:SourceAttempt;stop_attempt=$script:StopAttempt;
        source_receipt_path=$retarget.path;source_receipt_sha256=$retarget.sha256;source_start_evidence=$binding;source_start_intent_sha256=$intent.sha256;
        source_start_held_sha256=$heldSha;stop_receipt_path=$stop.stop_receipt_path;stop_receipt_sha256=$stop.stop_receipt_sha256;stop_status=$stop.stop_status;
        stop_start_binding=$stop.stop_start_binding;source_config_sha256=(Get-JsonMember $retarget.value 'config_sha256')}
}

function Assert-NeverStartedSourceLineage {
    param($State,[string]$SourceTarget,[string]$Root)
    # Source r5-retarget-receipt / r4-restore-retarget-receipt (audit C-F3 for r4): a retarget of this sitting that never
    # started (nothing ran, so no stop receipt). The start evidence in its root must be either nothing at all, or a
    # start-held.json proving the hold came before any instance could start (Run never called, or Run threw without an
    # instance and the readback showed none - audit C-F7) with the task and its logon trigger disabled again; the live XML
    # must equal what that evidence recorded.
    $label=Get-SourceLabel $SourceTarget
    $retarget=Assert-SourceRetargetReceipt $State $SourceTarget $Root
    $intent=Test-Path -LiteralPath (Join-Path $Root 'start-intent.json');$heldPath=Join-Path $Root 'start-held.json'
    $evidence=$null;$expectedXml=$null;$heldSha=$null
    if(Test-Path -LiteralPath $heldPath){
        $heldRecord=Read-JsonControl $heldPath ('The source '+$SourceTarget+' start-held record');$record=$heldRecord.value
        $runRequested=Get-JsonMember $record 'run_requested';$heldTrigger=Get-JsonMember $record 'trigger_enabled_after'
        $beforeRun=(Test-ExactBool (Get-JsonMember $record 'held_before_run') $true) -and ($runRequested -is [bool]) -and ($null -eq (Get-JsonMember $record 'instance_guid')) -and
            (Test-ExactBool (Get-JsonMember $record 'enabled_after') $false) -and (Test-Sha256Text (Get-JsonMember $record 'task_xml_after_sha256')) -and
            (($SourceTarget -ceq 'r5' -and (Test-ExactBool $heldTrigger $false)) -or ($SourceTarget -ceq 'r4' -and $null -eq $heldTrigger))
        if($beforeRun -and $runRequested){
            # Audit C-F7: Run was called but threw without an instance, and the readback showed no instance.
            $runException=Get-JsonMember $record 'run_exception'
            $beforeRun=($runException -is [string]) -and ($runException.Length -gt 0) -and (Test-ExactInt (Get-JsonMember $record 'running_instances') 0)}
        if(-not $beforeRun){throw ('The start-held record of attempt '+$script:SourceAttempt+' does not prove the hold came before Run with the task disabled again; preserve it for review.')}
        $evidence='START_HELD_BEFORE_RUN';$expectedXml=Get-JsonMember $record 'task_xml_after_sha256';$heldSha=$heldRecord.sha256}
    elseif($intent){throw ('The '+$label+' '+$script:SourceAttempt+' holds start-intent.json without start-held.json: a start may have been requested; recover it with stop-warden-r5 -RecoverInterruptedStart, then -SourceAttempt with -StopAttempt.')}
    else{$evidence='NO_START';$expectedXml=Get-JsonMember $retarget.value 'task_xml_sha256'}
    if($State.enabled -ne $false){throw ('An '+$SourceTarget+' retarget that never started must still be disabled; the live task is enabled. Preserve it for review.')}
    Assert-SourceLiveTriggers $State $SourceTarget $(if($SourceTarget -ceq 'r5'){$false}else{$null})
    if(-not (Test-Sha256Text $expectedXml) -or (Get-TaskXmlSha256 $State.xml) -cne $expectedXml){throw ('The task XML differs from the one the '+$SourceTarget+' retarget attempt recorded; preserve it for review.')}
    New-SourceRecord $(if($SourceTarget -ceq 'r5'){'r5-retarget-receipt'}else{'r4-restore-retarget-receipt'}) $State @{source_attempt=$script:SourceAttempt;
        source_receipt_path=$retarget.path;source_receipt_sha256=$retarget.sha256;source_start_evidence=$evidence;source_start_held_sha256=$heldSha;
        source_config_sha256=(Get-JsonMember $retarget.value 'config_sha256')}
}

function Assert-RetargetHeldSourceLineage {
    param($State,[string]$SourceTarget,[string]$Root)
    # Source r5-retarget-held / r4-restore-retarget-held (audit C-F1(b) crash window and C-F2): the attempt's single
    # TASK_UPDATE was requested but its retarget receipt was never written - held at the readback (MUTATION_READBACK) or
    # interrupted/crashed between RegisterTaskDefinition and the receipt. Recovered only by an r4 restore (-Target r4), and
    # only when the live task is exactly what that update intended: the intent's action, the attempt's description, the task
    # disabled with no instance, the captured SDDL, and the captured before-XML unchanged outside the retarget fields. A
    # MUTATION_READBACK hold binds the live XML by its recorded readback; without a readback the triggers must be exactly the
    # intended ones (disabled for r5).
    $label=Get-SourceLabel $SourceTarget
    if($script:Target -cne 'r4'){throw ('The '+$label+' '+$script:SourceAttempt+' was held or interrupted at its task update; its reviewed recovery is an r4 restore (-Target r4 -SourceAttempt '+$script:SourceAttempt+').')}
    foreach($name in @('start-intent.json','start-held.json')){if(Test-Path -LiteralPath (Join-Path $Root $name)){throw ('The '+$label+' '+$script:SourceAttempt+' holds '+$name+' without a retarget receipt; preserve it for review.')}}
    $intent=Read-JsonControl (Join-Path $Root 'retarget-intent.json') ('The source '+$SourceTarget+' retarget intent');$value=$intent.value
    $beforeSha=Get-JsonMember $value 'task_xml_before_sha256';$beforeSddlSha=Get-JsonMember $value 'task_sddl_before_sha256'
    if((Get-JsonMember $value 'schema') -cne 'cochem-warden-retarget-intent/3' -or (Get-JsonMember $value 'attempt') -cne $script:SourceAttempt -or
       (Get-JsonMember $value 'target') -cne $SourceTarget -or (Get-JsonMember $value 'task_name') -cne $script:taskName -or
       -not (Test-ActionObjectEqualsLive (Get-JsonMember $value 'action_after') $State) -or -not (Test-Sha256Text $beforeSha) -or -not (Test-Sha256Text $beforeSddlSha)){
        throw ('The source '+$SourceTarget+' retarget intent does not bind attempt '+$script:SourceAttempt+' and the live action.')}
    $beforeXml=Read-R3Text (Read-R3Control (Join-Path $Root 'warden-task-before.xml') $beforeSha 1048576)
    $beforeSddl=Read-R3Text (Read-R3Control (Join-Path $Root 'warden-task-before.sddl') $beforeSddlSha 65536)
    if($State.sddl -cne $beforeSddl){throw ('The live task security descriptor differs from the one the '+$label+' '+$script:SourceAttempt+' captured; preserve it for review.')}
    if((Get-TaskXmlOutsideRetarget $State.xml) -cne (Get-TaskXmlOutsideRetarget $beforeXml)){
        throw ('The live task XML changed outside Actions/Triggers/RegistrationInfo/Settings-Enabled since the '+$label+' '+$script:SourceAttempt+' captured it; preserve it for review.')}
    if((Get-TaskXmlDescription $State.xml) -cne (Get-TargetDescription $SourceTarget $script:SourceAttempt)){
        throw ('The live task does not carry the registration description of the '+$label+' '+$script:SourceAttempt+'; preserve it for review.')}
    if($State.enabled -ne $false){throw ('A retarget held at its task update must have left the task disabled; the live task is enabled. Preserve it for review.')}
    $heldPath=Join-Path $Root 'retarget-held.json';$heldSha=$null;$evidence='MUTATION_INTERRUPTED';$readback=$false
    if(Test-Path -LiteralPath $heldPath){
        $heldRecord=Read-JsonControl $heldPath ('The source '+$SourceTarget+' retarget-held record');$record=$heldRecord.value;$heldSha=$heldRecord.sha256
        if((Get-JsonMember $record 'schema') -cne 'cochem-warden-retarget-held/3' -or (Get-JsonMember $record 'attempt') -cne $script:SourceAttempt -or
           (Get-JsonMember $record 'target') -cne $SourceTarget -or (Get-JsonMember $record 'task_name') -cne $script:taskName -or
           (Get-JsonMember $record 'phase') -cne 'MUTATION_READBACK' -or -not (Test-ExactBool (Get-JsonMember $record 'mutation_requested') $true) -or
           -not (Test-ExactBool (Get-JsonMember $record 'receipt_written') $false)){
            throw ('The retarget-held record of the '+$label+' '+$script:SourceAttempt+' is not a MUTATION_READBACK hold of this attempt; preserve it for review.')}
        $evidence='MUTATION_READBACK_UNREADABLE'
        if(Test-ExactBool (Get-JsonMember $record 'readback_readable') $true){
            if(-not (Test-ExactBool (Get-JsonMember $record 'readback.enabled') $false) -or -not (Test-ExactInt (Get-JsonMember $record 'readback.instances') 0) -or
               (Get-JsonMember $record 'readback.task_xml_sha256') -cne (Get-TaskXmlSha256 $State.xml)){
                throw ('The readback recorded by the held update of the '+$label+' '+$script:SourceAttempt+' does not show the task disabled with no instance and the live task XML; preserve it for review.')}
            $evidence='MUTATION_READBACK_HELD';$readback=$true}}
    if(-not $readback){
        Assert-SourceLiveTriggers $State $SourceTarget $(if($SourceTarget -ceq 'r5'){$false}else{$null})
        $afterPath=Join-Path $Root 'warden-task-after.xml'
        if(Test-Path -LiteralPath $afterPath){
            if((Read-R3Control $afterPath '' 1048576).Sha256 -cne (Get-TaskXmlSha256 $State.xml)){throw ('The live task XML differs from the warden-task-after.xml the '+$label+' '+$script:SourceAttempt+' recorded; preserve it for review.')}}}
    New-SourceRecord $(if($SourceTarget -ceq 'r5'){'r5-retarget-held'}else{'r4-restore-retarget-held'}) $State @{source_attempt=$script:SourceAttempt;
        source_receipt_path=$intent.path;source_receipt_sha256=$intent.sha256;source_retarget_held_sha256=$heldSha;source_mutation_evidence=$evidence;
        source_config_sha256=(Get-JsonMember $value 'config_sha256')}
}

function Assert-RetargetSource {
    param($State)
    # Accepted sources, each with no instance (port and processes are proved by the caller):
    #   r4-v1                          exact pinned r4-v1 action, no attempts given (addendum A1);
    #   per attempt of this sitting (-SourceAttempt names it; the live action selects r5 or the r4 restore, the evidence in its
    #   root selects the state):
    #   r5-retarget-receipt / r4-restore-retarget-receipt  -SourceAttempt alone: retargeted, never started (or held before Run);
    #   r5-retarget-held / r4-restore-retarget-held        -SourceAttempt alone, -Target r4 only: the task update was held at its
    #                                                      readback or interrupted before the retarget receipt;
    #   r5-receipt / r4-restore-receipt                    with -StopAttempt: started (start receipt), then stopped by stop-warden-r5;
    #   r5-start-held / r4-restore-start-held              with -StopAttempt: a start that ran without a receipt (interrupted, crashed,
    #                                                      or held after Run), stopped by stop-warden-r5 -RecoverInterruptedStart.
    if(-not $State.readable){throw 'Warden task definition is unreadable.'}
    if($State.instances -ne 0 -or $State.state -notin @(1,3)){throw 'The Warden task has a running or queued instance; no retarget while a controller may be alive.'}
    Assert-TaskDefinition $State 'The Warden task is not the exact reviewed SYSTEM daemon definition; preserve it for review.'
    Assert-RegisteredTaskAcl $State.sddl
    $hasSource=-not [string]::IsNullOrEmpty($script:SourceAttempt);$hasStop=-not [string]::IsNullOrEmpty($script:StopAttempt)
    if($hasStop -and -not $hasSource){throw '-StopAttempt needs -SourceAttempt (the attempt the stop receipt names).'}
    if($State.action_path -ceq $script:r4Python -and $State.action_working_directory -ceq $script:r4Root -and
       $State.action_arguments -ceq (Get-ExpectedArguments $script:commissioningConfig $script:queueR4v1)){
        # Source r4-v1 (ARMY_ADDENDUM A1): idle since the reboot, Enabled true or false, no stop receipt needed.
        if($hasSource -or $hasStop){throw 'The live action is the r4-v1 action; -SourceAttempt and -StopAttempt apply only to a later source and must be omitted.'}
        if($State.triggers -ne 0 -or @($State.trigger_list).Count -ne 0){throw 'The r4-v1 source task must have no trigger; preserve it for review.'}
        return New-SourceRecord 'r4-v1' $State @{source_config_sha256=$script:configPin}}
    $sourceTarget=$null;$restoreAttempt=Get-R4RestoreQueueAttempt $State
    if($null -ne $restoreAttempt){
        if(-not $hasSource){throw 'An r4 restore source needs -SourceAttempt (the r4 restore attempt), plus -StopAttempt once that attempt was started and stopped by stop-warden-r5.'}
        if($restoreAttempt -cne $script:SourceAttempt){throw ('The live r4 restore action names queue attempt '+$restoreAttempt+', not -SourceAttempt '+$script:SourceAttempt+'; preserve it for review.')}
        $sourceTarget='r4'}
    elseif(Test-R5ActionForm $State){
        if(-not $hasSource){throw 'An r5 source needs -SourceAttempt (the r5 retarget attempt), plus -StopAttempt once that attempt was started and stopped by stop-warden-r5.'}
        $sourceTarget='r5'}
    else{throw 'The Warden task action is neither the pinned r4-v1 action, an r4 restore action nor an r5 action; preserve it for review.'}
    $root=Join-Path $script:base ('WardenRetarget4.2.7-windows-'+$script:namespaceDate+'-'+$sourceTarget+'-'+$script:SourceAttempt);$label=Get-SourceLabel $sourceTarget
    if($hasStop){
        if(Test-Path -LiteralPath (Join-Path $root 'start-receipt.json')){return Assert-StartedSourceLineage $State $sourceTarget $root}
        if(Test-Path -LiteralPath (Join-Path $root 'start-intent.json')){return Assert-HeldStartSourceLineage $State $sourceTarget $root}
        throw ('The '+$label+' '+$script:SourceAttempt+' has no start receipt and no start intent: it never started, so it is a retarget-receipt source (-SourceAttempt alone).')}
    if(Test-Path -LiteralPath (Join-Path $root 'start-receipt.json')){throw ('The '+$label+' '+$script:SourceAttempt+' holds a start receipt: it ran, so it needs -StopAttempt after stop-warden-r5.')}
    if(Test-Path -LiteralPath (Join-Path $root 'retarget-receipt.json')){return Assert-NeverStartedSourceLineage $State $sourceTarget $root}
    if(Test-Path -LiteralPath (Join-Path $root 'retarget-intent.json')){return Assert-RetargetHeldSourceLineage $State $sourceTarget $root}
    throw ('The '+$label+' '+$script:SourceAttempt+' has no retarget receipt and no retarget intent; preserve it for review.')
}

function Get-TargetDescription {
    param([string]$Target,[string]$Attempt)
    # The registration Description each retarget writes; it names the attempt, so a task XML is bound to its attempt (C-F5).
    if($Target -ceq 'r5'){return ('Reviewed r5 retarget '+$Attempt+' (reboot-safe logon trigger) of the r4 retarget task. Logon trigger only, no retries; preserve on any failure.')}
    'Reviewed r4 restart '+$Attempt+' after the r5 sitting. No triggers/retries; preserve on any failure.'
}

function New-TargetContext {
    param([string]$Target,$Runtime,$ConfigBinding)
    # Everything the mutation, the readback, the start and the receipts expect for the chosen target.
    if($Target -ceq 'r5'){
        return [ordered]@{target='r5';retargeted_status='WARDEN_RETARGETED_TO_R5_NOT_STARTED';started_status='WARDEN_R5_RUNNING_HEALTH_VERIFIED';
            runtime_root=$Runtime.root;source_root=$Runtime.source_root;config_path=$ConfigBinding.path;config_sha256=$ConfigBinding.sha256;config_mode=$ConfigBinding.mode;
            install_after_path=$Runtime.install_after_path;install_after_sha256=$Runtime.install_after_sha256;deployment_revision_sha256=$Runtime.revision_sha256;
            source_manifest_sha256=$Runtime.source_manifest_sha256;
            action=[ordered]@{execute=$Runtime.python;arguments=(Get-R5Arguments $ConfigBinding.path $script:r5QueueRoot $script:dockerWaitSeconds);working_directory=$Runtime.root};
            triggers=(Get-TriggerReceiptForm 'r5');queue_launch_output=$null;queue_launch_output_root=$script:r5QueueRoot;docker_wait_seconds=$script:dockerWaitSeconds;
            admission_field='components.warden_controller.admission_ready';description=(Get-TargetDescription 'r5' $script:Attempt)}}
    [ordered]@{target='r4';retargeted_status='WARDEN_RETARGETED_TO_R4_NOT_STARTED';started_status='WARDEN_R4_RESTARTED_HEALTH_VERIFIED';
        runtime_root=$script:r4Root;source_root=$script:r4SourceRoot;config_path=$script:r4RestoreConfig;config_sha256=$script:configPin;config_mode='COMMISSIONED';
        install_after_path=$null;install_after_sha256=$null;deployment_revision_sha256=$Runtime.revision_sha256;source_manifest_sha256=$Runtime.source_manifest_sha256;
        action=[ordered]@{execute=$script:r4Python;arguments=(Get-ExpectedArguments $script:r4RestoreConfig $script:queueRestart);working_directory=$script:r4Root};
        triggers=(Get-TriggerReceiptForm 'r4');queue_launch_output=$script:queueRestart;queue_launch_output_root=$null;docker_wait_seconds=$null;
        # Audit C-F6: r4's components.warden_controller.ready flaps with its 50 MiB check, so the r4 restore records it in the
        # start receipt but never gates on it (no admission field).
        admission_field=$null;description=(Get-TargetDescription 'r4' $script:Attempt)}
}

function Assert-RetargetedTask {
    param($State,$Context,[string]$ExpectedSddl,[bool]$TriggerEnabled=$false)
    # The r5 logon trigger is disabled after every TASK_UPDATE and enabled only by a start whose health gate passed.
    if(-not $State.readable){throw 'Retargeted task could not be read back.'}
    Assert-TaskDefinition $State 'Retargeted task lost its reviewed principal/settings; investigate before any start.'
    if($State.action_path -cne $Context.action.execute -or $State.action_working_directory -cne $Context.action.working_directory -or
       $State.action_arguments -cne $Context.action.arguments){throw ('Retargeted task action is not the expected '+$Context.target+' action.')}
    if($Context.target -ceq 'r5'){Assert-LogonTrigger $State.trigger_list $TriggerEnabled}
    elseif($State.triggers -ne 0 -or @($State.trigger_list).Count -ne 0){throw 'The r4 restore task must have no trigger.'}
    if($State.sddl -cne $ExpectedSddl){throw 'Retargeted task security descriptor changed.'}
    Assert-RegisteredTaskAcl $State.sddl
}

function Get-TaskXmlOutsideRetarget {
    param([string]$Xml)
    # What the retarget may change: the action, the triggers, the registration description and <Settings><Enabled> (the
    # task is registered disabled; only -Start enables it). Everything else must be byte-equal.
    $document=[xml]$Xml;$root=$document.DocumentElement
    foreach($child in @($root.ChildNodes)){if($child.LocalName -in @('Actions','Triggers','RegistrationInfo')){$null=$root.RemoveChild($child)}}
    foreach($settings in @($root.ChildNodes|Where-Object {$_.LocalName -ceq 'Settings'})){
        foreach($child in @($settings.ChildNodes)){if($child.LocalName -ceq 'Enabled'){$null=$settings.RemoveChild($child)}}}
    $root.OuterXml
}

function Assert-TaskXmlOutsideRetargetUnchanged {
    param([string]$Before,[string]$After)
    if((Get-TaskXmlOutsideRetarget $Before) -cne (Get-TaskXmlOutsideRetarget $After)){throw 'Retargeted task XML changed outside Actions/Triggers/RegistrationInfo/Settings-Enabled; investigate before any start.'}
}

function Get-TaskXmlWithoutEnabledFlags {
    param([string]$Xml,[switch]$Triggers)
    # The task XML without <Settings><Enabled> and, with -Triggers, without every <Triggers><*><Enabled>: what a start (task
    # enable, then logon trigger enable) and a stop (task disable) may change. Everything else must be byte-equal.
    $document=[xml]$Xml;$root=$document.DocumentElement
    foreach($settings in @($root.ChildNodes|Where-Object {$_.LocalName -ceq 'Settings'})){
        foreach($child in @($settings.ChildNodes)){if($child.LocalName -ceq 'Enabled'){$null=$settings.RemoveChild($child)}}}
    if($Triggers){
        foreach($list in @($root.ChildNodes|Where-Object {$_.LocalName -ceq 'Triggers'})){
            foreach($trigger in @($list.ChildNodes)){foreach($child in @($trigger.ChildNodes)){if($child.LocalName -ceq 'Enabled'){$null=$trigger.RemoveChild($child)}}}}}
    $root.OuterXml
}

function Get-TaskXmlDescription {
    param([string]$Xml)
    # The registration Description of a task XML ('' when absent).
    $document=[xml]$Xml
    foreach($info in @($document.DocumentElement.ChildNodes|Where-Object {$_.LocalName -ceq 'RegistrationInfo'})){
        foreach($child in @($info.ChildNodes)){if($child.LocalName -ceq 'Description'){return [string]$child.InnerText}}}
    ''
}

function Get-ControllerPresence {
    # Fail closed: an unanswerable port query is a hold, not "free"; only the cmdlet's own
    # no-match error means that nothing listens. Controller-like command lines are recognised
    # from any image path. The two reviewed observer recorders and GUI MCP clients are
    # reported, not counted. Python processes whose image and command line cannot be read are
    # counted as uninspectable (an unelevated plan sees every SYSTEM process that way).
    # (v2.2, with the runtime roots extended by every installed r5 root, and the owner's Antigravity bridge client
    # '"<runtime python>" -m cochem_mcp --provider codex|claude --config C:\Users\ansac\CoChem427\bridge.local.json'
    # reported as a client in exactly that form; any other form stays an unclassified runtime process.)
    try{$listening=@(Get-NetTCPConnection -LocalPort $script:port -State Listen -ErrorAction Stop)}
    catch{if($_.FullyQualifiedErrorId -like 'CmdletizationQuery_NotFound*'){$listening=@()}else{throw ('Loopback port state could not be established: '+$_.Exception.Message)}}
    $controllers=@();$observers=@();$clients=@();$unclassified=@();$uninspectable=0
    foreach($process in @(Get-CimInstance Win32_Process -ErrorAction Stop)){
        $path=[string]$process.ExecutablePath;$command=[string]$process.CommandLine;$name=[string]$process.Name
        $rooted=$false;if($path){foreach($root in @($script:runtimeRoots)){if($path.StartsWith($root,[StringComparison]::OrdinalIgnoreCase)){$rooted=$true;break}}}
        $entry=[ordered]@{pid=$process.ProcessId;parent=$process.ParentProcessId;path=$path;command=$command}
        if($command -match 'cochem_pipeline\s+daemon\b|cochem_supervisor\b|provision-execution\b|cochem-supervisor\b|cochem-pipeline(\.exe)?"?\s+daemon\b'){$controllers+=$entry}
        elseif($command -match $script:observerPattern){$observers+=$entry}
        elseif($rooted -and ($command -match 'cochem_pipeline\s+(mcp|health|status|submit|cancel|projects|code|code-status|code-cancel|code-resume|knowledge-\w+)\b' -or $command -cmatch '^"[^"]+\\python\.exe" -m cochem_mcp --provider (codex|claude) --config C:\\Users\\ansac\\CoChem427\\bridge\.local\.json\z')){$clients+=$entry}
        elseif($rooted){$unclassified+=$entry}
        elseif(-not $path -and -not $command -and $name -match '^python(w)?\.exe$'){$uninspectable++}
    }
    [ordered]@{port=$script:port;listening=$listening.Count;controller_processes=$controllers;observer_processes=$observers;client_processes=$clients;
        unclassified_runtime_processes=$unclassified;uninspectable_python_processes=$uninspectable;authoritative=$script:admin}
}

function Test-ControllerAlive {
    param($Presence)
    ($Presence.listening -ne 0) -or (@($Presence.controller_processes).Count -ne 0) -or (@($Presence.unclassified_runtime_processes).Count -ne 0) -or
    ([bool]$Presence.authoritative -and $Presence.uninspectable_python_processes -ne 0)
}

function Test-LoopbackFree {
    # Exclusive bind probe, as the r3 commissioning did; single-quoted Python only, run by the
    # pinned base interpreter behind a deny-write handle that stays open for the probe.
    $null=Read-R3Control $script:probePython $script:probePythonPin 4194304
    $probe='import socket,sys'+"`n"+'s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)'+"`n"+'s.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)'+"`n"+'try:'+"`n"+'    s.bind((''127.0.0.1'',int(sys.argv[1])))'+"`n"+'except OSError:'+"`n"+'    sys.exit(2)'+"`n"+'finally:'+"`n"+'    s.close()'+"`n"+'sys.exit(0)'
    $result=Invoke-NativeJudged $script:probePython @('-I','-B','-X','utf8','-c',$probe,[string]$script:port)
    if($result.code -eq 0){return $true}
    if($result.code -eq 2){return $false}
    throw ('Loopback bind probe failed: '+$result.stderr)
}

function Get-WorkerProcesses {
    # Slot workers run under the six isolated identities; any such process means work is
    # active. Elevated, owners come from one Get-Process -IncludeUserName call (fast, covers
    # protected processes); the per-process GetOwner call is the fallback. A process whose
    # owner still cannot be resolved is re-queried: gone means it exited during the sweep,
    # still present means uninspectable, which is reported, never silently ignored.
    $workers=@();$uninspectable=@();$exited=0;$owners=@{}
    if($script:admin){foreach($entry in @(Get-Process -IncludeUserName -ErrorAction Stop)){if($entry.UserName){$owners[[int]$entry.Id]=[string]$entry.UserName}}}
    foreach($process in @(Get-CimInstance Win32_Process -ErrorAction Stop)){
        $processId=[int]$process.ProcessId;$user=$null
        if($owners.ContainsKey($processId)){$user=$owners[$processId]}
        else{
            $owner=$null;try{$owner=Invoke-CimMethod -InputObject $process -MethodName GetOwner -ErrorAction Stop}catch{$owner=$null}
            if($null -ne $owner -and $owner.ReturnValue -eq 0){$user=[string]$owner.User}
            else{
                $still=$null;try{$still=Get-CimInstance Win32_Process -Filter ('ProcessId = '+$processId) -ErrorAction Stop}catch{$still=$null}
                if($null -eq $still){$exited++;continue}
                $uninspectable+=[ordered]@{pid=$processId;name=[string]$process.Name;path=[string]$process.ExecutablePath};continue}}
        $account=$user;$separator=$account.LastIndexOf('\');if($separator -ge 0){$account=$account.Substring($separator+1)}
        if($account -cmatch '^CoChem422Worker[1-6]$'){$workers+=[ordered]@{pid=$processId;user=$user;path=[string]$process.ExecutablePath}}
    }
    [ordered]@{workers=$workers;uninspectable_processes=$uninspectable;exited_during_sweep=$exited;authoritative=$script:admin}
}

function Assert-NoWorkers {
    param($Result,[string]$Context)
    if(@($Result.workers).Count){throw ('Slot worker processes are alive'+$Context)}
    # Elevated, every user-mode process with an image path must answer; kernel pseudo-processes carry none.
    $opaque=@($Result.uninspectable_processes|Where-Object {$_.path})
    if([bool]$Result.authoritative -and $opaque.Count){throw ('Processes could not be inspected for worker ownership'+$Context+' ('+(($opaque|ForEach-Object {[string]$_.pid+' '+$_.name}) -join ', ')+')')}
}

function New-PrivateAcl {
    param([bool]$Directory)
    $acl=if($Directory){[Security.AccessControl.DirectorySecurity]::new()}else{[Security.AccessControl.FileSecurity]::new()}
    $acl.SetAccessRuleProtection($true,$false)
    $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
    $inherit=if($Directory){[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'}else{[Security.AccessControl.InheritanceFlags]::None}
    foreach($sid in @('S-1-5-18','S-1-5-32-544')){
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),[Security.AccessControl.FileSystemRights]::FullControl,$inherit,[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow))}
    $acl
}

function Assert-PrivateAcl {
    param([string]$Path)
    $acl=Get-Acl -LiteralPath $Path
    if($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin @('S-1-5-18','S-1-5-32-544')){throw ('Private backup path has an untrusted owner: '+$Path)}
    foreach($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){
        if($rule.AccessControlType -eq 'Allow' -and $rule.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544')){throw ('Private backup path grants access beyond SYSTEM/Administrators: '+$Path)}}
}

function New-PrivateDirectory {
    param([string]$Path)
    if(Test-Path -LiteralPath $Path){throw ('Private directory already exists; preserve it: '+$Path)}
    Assert-ProtectedPath (Split-Path -Parent $Path)
    $directory=[IO.DirectoryInfo]::new($Path);$directory.Create((New-PrivateAcl $true))
    Assert-NoReparseAncestors $Path
    Assert-PrivateAcl $Path
}

function Get-BackupCopyArguments {
    param([string]$Destination,[switch]$ListOnly)
    # Fixed switches only; the paths come from Join-Path (no trailing separator). /A-:RSH strips
    # read-only/system/hidden from the copies so the verifier can checkpoint them; /XJ skips junctions.
    $arguments=@($script:privateRoot,$Destination,'*.db','*.db-wal','*.db-journal','/S','/LEV:4')+@($script:backupCopyFlags)
    if($ListOnly){$arguments+='/L'}
    $arguments+@('/COPY:DAT','/A-:RSH','/R:0','/W:0','/NJH','/NJS','/NP','/NDL','/NC','/NS','/XJ')
}

function Test-BackupCopyRights {
    # robocopy /L under backup semantics lists the private stores without creating or writing
    # anything; it refuses upfront (exit 16) when the token lacks the Backup and Restore rights
    # or cannot enumerate the SYSTEM-only root. Runs before any attempt namespace is consumed.
    $probe=Invoke-NativeJudged (Join-Path $env:SystemRoot 'System32\robocopy.exe') (Get-BackupCopyArguments (Join-Path $script:targetRoot 'state-backup') -ListOnly)
    if($probe.code -notin @(0,1)){throw ('Backup copy rights/readability probe failed (robocopy exit '+$probe.code+'): '+(($probe.stdout+"`n"+$probe.stderr).Trim())+'. Confirm SeBackupPrivilege and SeRestorePrivilege with whoami /priv in the elevated shell.')}
    $true
}

function Get-TreeHashes {
    param([string]$Root)
    $hashes=@{}
    foreach($file in @(Get-ChildItem -LiteralPath $Root -Recurse -File -Force)){$hashes[$file.FullName.Substring($Root.Length).TrimStart('\')]=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
    $hashes
}

function Backup-PrivateDatabases {
    param([string]$Destination)
    # The private root is SYSTEM-only (windows.py provisions O:SYG:SYD:P(A;OICI;FA;;;SY)), so the
    # elevated owner copies with robocopy backup semantics: *.db, *.db-wal and *.db-journal are
    # opened read-only and never by SQLite (a read-only SQLite open would still create -wal/-shm
    # files beside a cleanly closed WAL store). Two independent passes must agree byte for byte
    # (a torn copy or an active writer shows up as a difference); the witness copy stays raw.
    # The hash-pinned helper is copied into the retarget root, run by path, and verifies the
    # primary copies only: nothing is passed through the native argument binder except plain
    # paths and fixed switches.
    $robocopy=Join-Path $env:SystemRoot 'System32\robocopy.exe';$witness=$Destination+'-witness'
    New-PrivateDirectory $witness
    $copy=Invoke-NativeJudged $robocopy (Get-BackupCopyArguments $Destination)
    if($copy.code -notin @(0,1)){throw ('Private database copy failed (robocopy exit '+$copy.code+'): '+(($copy.stdout+"`n"+$copy.stderr).Trim()))}
    $second=Invoke-NativeJudged $robocopy (Get-BackupCopyArguments $witness)
    if($second.code -notin @(0,1)){throw ('Private database witness copy failed (robocopy exit '+$second.code+'): '+(($second.stdout+"`n"+$second.stderr).Trim()))}
    $primary=Get-TreeHashes $Destination;$shadow=Get-TreeHashes $witness
    $primaryKeys=(@($primary.Keys)|Sort-Object) -join '|';$shadowKeys=(@($shadow.Keys)|Sort-Object) -join '|'
    if($primaryKeys -cne $shadowKeys){throw 'Private database copies differ in file set between passes; a writer may be active.'}
    foreach($key in @($primary.Keys)){if($primary[$key] -cne $shadow[$key]){throw ('Private database copies differ between passes: '+$key+'; a writer may be active.')}}
    if($primary.Count -eq 0){throw 'No private database was copied.'}
    $helperTarget=Join-Path $script:targetRoot 'backup-private-databases-r4.py'
    Copy-VerifiedPayload ([pscustomobject]@{source=$script:backupHelper;destination=$helperTarget;sha256=$script:backupHelperPin;length=(Get-Item -LiteralPath $script:backupHelper).Length})
    $result=Invoke-NativeJudged $script:r4Python @('-I','-B','-X','utf8',$helperTarget,$Destination)
    if($result.code -ne 0){throw ('Private database verification failed (exit '+$result.code+'): '+$result.stderr)}
    $report=$null;try{$report=$result.stdout|ConvertFrom-Json}catch{throw ('Backup verification output is not JSON: '+$_.Exception.Message)}
    if($null -eq $report){throw 'Backup helper printed no report.'}
    if($report.schema -cne 'cochem-private-database-backup/3' -or -not (Test-ExactBool $report.sources_opened $false)){throw 'Unexpected backup report.'}
    foreach($entry in @($report.databases)){if($entry.integrity -cne 'ok'){throw ('Backup copy failed integrity: '+$entry.relative)}}
    foreach($item in @(Get-ChildItem -LiteralPath $Destination -Recurse -Force)+@(Get-ChildItem -LiteralPath $witness -Recurse -Force)){Assert-PrivateAcl $item.FullName}
    [ordered]@{copy_exit_code=$copy.code;witness_exit_code=$second.code;copy_flags=@($script:backupCopyFlags);witness_root=$witness;raw_copies_sha256=$primary;verification=$report}
}

function Get-HealthSample {
    # The pinned r4 interpreter is the /health client for both targets (wire-compatible); the identity must be the SYSTEM
    # controller running from the target root.
    $result=Invoke-NativeJudged $script:healthPython @('-I','-B','-X','utf8','-m','cochem_pipeline','health','--client-config',$script:clientConfig)
    if($result.code -ne 0){return [pscustomobject]@{ok=$false;error=$result.stderr;health=$null}}
    $health=$null;try{$health=$result.stdout|ConvertFrom-Json}catch{return [pscustomobject]@{ok=$false;error='health output is not JSON';health=$null}}
    if($null -eq $health -or $health -isnot [Management.Automation.PSCustomObject]){return [pscustomobject]@{ok=$false;error='health output is not a JSON object';health=$null}}
    foreach($field in @('service_identity','source_root','pid','instance_id','process_started_at','active','quarantined_slots')){
        if($null -eq $health.PSObject.Properties[$field]){return [pscustomobject]@{ok=$false;error=('health lacks '+$field);health=$health}}}
    if($health.service_identity -cne 'SYSTEM' -or [string]$health.source_root -cne $script:targetSourceRoot){return [pscustomobject]@{ok=$false;error='health answered with an unexpected identity or source root';health=$health}}
    [pscustomobject]@{ok=$true;error='';health=$health}
}

function Get-StartGateFailures {
    param($Health,$Context)
    # Hard gates fail the start at once; readiness gates are polled until the start deadline.
    $hard=[Collections.Generic.List[string]]::new();$soft=[Collections.Generic.List[string]]::new()
    $active=Get-JsonListField $Health 'active'
    if(-not $active.valid){$hard.Add('health has no active list')}elseif($active.items.Count){$hard.Add('the controller reports '+$active.items.Count+' active job(s) immediately after start')}
    $slots=Get-JsonMember $Health 'quarantined_slots'
    if($null -eq $slots -or $slots -isnot [Management.Automation.PSCustomObject]){$hard.Add('health has no quarantined_slots object')}
    elseif(@($slots.PSObject.Properties).Count){$hard.Add('the controller reports quarantined slots: '+((@($slots.PSObject.Properties)|ForEach-Object {$_.Name}) -join ', '))}
    $barriers=Get-JsonListField (Get-JsonMember $Health 'routing') 'execution_quarantines'
    if(-not $barriers.valid){$hard.Add('health has no routing.execution_quarantines list')}elseif($barriers.items.Count){$hard.Add('the controller reports '+$barriers.items.Count+' execution quarantine row(s)')}
    if(-not (Test-ExactBool (Get-JsonMember $Health 'knowledge.ready') $true) -or -not (Test-ExactBool (Get-JsonMember $Health 'knowledge.authority_matches_capture') $true)){
        $soft.Add('knowledge is not ready with authority_matches_capture true')}
    if($Context.admission_field -and -not (Test-ExactBool (Get-JsonMember $Health $Context.admission_field) $true)){$soft.Add('the Warden controller does not admit work yet ('+$Context.admission_field+' is not true)')}
    [pscustomobject]@{hard=@($hard);soft=@($soft)}
}

function Get-ProcessCreationUtc {
    param($Process)
    if($null -eq $Process -or $null -eq $Process.CreationDate){return $null}
    ([DateTime]$Process.CreationDate).ToUniversalTime().ToString('o')
}

function Get-TargetProcessProof {
    param([int]$ProcessId,$Context)
    # The /health pid must be the Toolchain interpreter running the target daemon command as SYSTEM, started by the target
    # venv launcher with the same command, and must own every listener on the controller port.
    $process=Get-CimInstance Win32_Process -Filter ('ProcessId = '+$ProcessId) -ErrorAction Stop
    if($null -eq $process){throw 'The controller pid reported by /health does not exist.'}
    $expected=$Context.action.arguments
    if([string]$process.ExecutablePath -cne $script:basePython){throw 'The controller pid does not run the Toolchain interpreter.'}
    if(([string]$process.CommandLine).IndexOf($expected,[StringComparison]::Ordinal) -lt 0){throw ('The controller pid is not running the expected '+$Context.target+' daemon command.')}
    try{$listeners=@(Get-NetTCPConnection -LocalPort $script:port -State Listen -ErrorAction Stop)}
    catch{if($_.FullyQualifiedErrorId -like 'CmdletizationQuery_NotFound*'){$listeners=@()}else{throw ('The controller port owner could not be established: '+$_.Exception.Message)}}
    if($listeners.Count -eq 0){throw 'Nothing listens on the controller port.'}
    foreach($listener in $listeners){if([int]$listener.OwningProcess -ne $ProcessId){throw ('The controller port is owned by pid '+$listener.OwningProcess+', not the pid reported by /health.')}}
    $parent=Get-CimInstance Win32_Process -Filter ('ProcessId = '+[int]$process.ParentProcessId) -ErrorAction Stop
    if($null -eq $parent -or -not [string]::Equals([string]$parent.ExecutablePath,[string]$Context.action.execute,[StringComparison]::OrdinalIgnoreCase) -or
       ([string]$parent.CommandLine).IndexOf($expected,[StringComparison]::Ordinal) -lt 0){throw ('The controller parent is not the '+$Context.target+' venv launcher started by the task action.')}
    $owner=$null;try{$owner=Invoke-CimMethod -InputObject $process -MethodName GetOwner -ErrorAction Stop}catch{$owner=$null}
    if($null -eq $owner -or $owner.ReturnValue -ne 0 -or [string]$owner.User -cne 'SYSTEM'){throw 'The controller pid does not run as SYSTEM.'}
    [ordered]@{pid=[int]$process.ProcessId;image=[string]$process.ExecutablePath;creation_utc=(Get-ProcessCreationUtc $process);parent_pid=[int]$process.ParentProcessId;
        parent_image=[string]$parent.ExecutablePath;parent_creation_utc=(Get-ProcessCreationUtc $parent);owner=[string]$owner.User;port_owner_verified=$true;listeners=$listeners.Count}
}

function Write-HeldControl {
    param([string]$Name,$Record)
    # A held record is best effort on top of the throw: its own failure is reported in the message, never swallowed.
    try{$null=Write-RegistrationControl (Join-Path $script:targetRoot $Name) ($Record|ConvertTo-Json -Depth 10);''}catch{' The held record could not be written: '+$_.Exception.Message}
}

function New-ReceiptHead {
    param([string]$Schema,[string]$Status,$Context,$Source,[string]$TaskXmlSha256)
    # The fields both receipts carry with these exact names (the CUTOVER interface contract).
    [ordered]@{schema=$Schema;status=$Status;target=$Context.target;attempt=$script:Attempt;task_name=$script:taskName;runtime_root=$Context.runtime_root;config_path=$Context.config_path;
        config_sha256=$Context.config_sha256;install_after_path=$Context.install_after_path;install_after_sha256=$Context.install_after_sha256;
        action=[ordered]@{execute=$Context.action.execute;arguments=$Context.action.arguments;working_directory=$Context.action.working_directory};
        triggers=$Context.triggers;task_xml_sha256=$TaskXmlSha256;source_state=$Source.source_state;source_attempt=$Source.source_attempt;stop_attempt=$Source.stop_attempt}
}

function Add-OrderedFields {
    param($Target,$Fields)
    foreach($key in @($Fields.Keys)){$Target[$key]=$Fields[$key]}
}

function Invoke-Retarget {
    param($Folder,$Context,$Lineage)
    $state=Get-WardenTaskState $Folder;$source=Assert-RetargetSource $state
    Assert-OtherDaemonsIdle (Get-OtherDaemonTaskStates $Folder)
    $presence=Get-ControllerPresence
    if(Test-ControllerAlive $presence){throw 'A controller process, an unclassified runtime process or the loopback port is alive; no retarget while a controller may be running.'}
    Assert-NoWorkers (Get-WorkerProcesses) '; no retarget while work may be active.'
    if(-not (Test-LoopbackFree)){throw 'The controller port cannot be bound exclusively; a controller may be alive.'}
    if(Test-Path -LiteralPath $script:targetRoot){throw 'Retarget root already exists; preserve it and choose a new attempt.'}
    if($Context.target -ceq 'r4'){
        # The private root is SYSTEM-only: a probe of an existing child is refused, a missing one answers false; the attempt root is the namespace guard.
        $queueExists=$false;try{$queueExists=[bool](Test-Path -LiteralPath $Context.queue_launch_output -ErrorAction Stop)}catch{$queueExists=$true}
        if($queueExists){throw 'The fresh queue-observation directory already exists (or its probe was refused); choose a new attempt.'}}
    $null=Test-BackupCopyRights
    try{New-ProtectedDirectory $script:targetRoot}catch{
        $reason=$_.Exception.Message
        if(-not (Test-Path -LiteralPath $script:targetRoot)){throw ('The retarget root could not be created: '+$reason+' Nothing was changed.')}
        $note=Write-HeldControl 'retarget-held.json' ([ordered]@{schema='cochem-warden-retarget-held/3';phase='ROOT';target=$Context.target;attempt=$script:Attempt;task_name=$script:taskName;
            mutation_requested=$false;reason=$reason;automatic_retry_allowed=$false;requires_reviewed_recovery=$true})
        throw ('The retarget root '+$script:targetRoot+' exists but could not be secured: '+$reason+' Nothing was retargeted; preserve the root and choose another -Attempt after review.'+$note)}
    # From here the attempt namespace is consumed: every failure leaves retarget-held.json.
    $beforeXml=$null;$beforeSddl=$null;$intentHash=$null;$backupHash=$null;$now=$null
    try{
        $beforeXml=Write-RegistrationControl (Join-Path $script:targetRoot 'warden-task-before.xml') $state.xml
        $beforeSddl=Write-RegistrationControl (Join-Path $script:targetRoot 'warden-task-before.sddl') $state.sddl
        if($beforeXml -cne $source.task_xml_sha256){throw 'the task XML hash conversion differs from the recorded control file'}
        $intent=[ordered]@{schema='cochem-warden-retarget-intent/3';attempt=$script:Attempt;target=$Context.target;task_name=$script:taskName;source=$source;
            action_before=[ordered]@{execute=$state.action_path;arguments=$state.action_arguments;working_directory=$state.action_working_directory};
            triggers_before=@($state.trigger_list);enabled_before=$state.enabled;action_after=$Context.action;triggers_after=$Context.triggers;
            runtime_root=$Context.runtime_root;config_path=$Context.config_path;config_sha256=$Context.config_sha256;config_mode=$Context.config_mode;
            install_after_path=$Context.install_after_path;install_after_sha256=$Context.install_after_sha256;deployment_revision_sha256=$Context.deployment_revision_sha256;
            queue_launch_output=$Context.queue_launch_output;queue_launch_output_root=$Context.queue_launch_output_root;docker_wait_seconds=$Context.docker_wait_seconds;
            r4_lineage=$Lineage;old_controller=$Lineage.old_controller;observer_processes=$presence.observer_processes;task_xml_before_sha256=$beforeXml;task_sddl_before_sha256=$beforeSddl;
            trigger_enabled_after=$(if($Context.target -ceq 'r5'){$false}else{$null});mode='RETARGET_ACTION_AND_TRIGGERS';description_rewritten=$true;start_requested=$false}
        $intentHash=Write-RegistrationControl (Join-Path $script:targetRoot 'retarget-intent.json') ($intent|ConvertTo-Json -Depth 8)
        New-PrivateDirectory (Join-Path $script:targetRoot 'state-backup')
        $backup=Backup-PrivateDatabases (Join-Path $script:targetRoot 'state-backup')
        $backupHash=Write-RegistrationControl (Join-Path $script:targetRoot 'state-backup.json') ($backup|ConvertTo-Json -Depth 10)
        # Re-attest immediately before the only mutation.
        $now=Get-WardenTaskState $Folder;$again=Assert-RetargetSource $now
        if($again.source_state -cne $source.source_state -or $now.xml -cne $state.xml -or $now.sddl -cne $state.sddl){throw 'the task definition changed during preparation'}
        Assert-OtherDaemonsIdle (Get-OtherDaemonTaskStates $Folder)
        if(Test-ControllerAlive (Get-ControllerPresence)){throw 'a controller appeared during preparation'}
        Assert-NoWorkers (Get-WorkerProcesses) ' during preparation'
        if(-not (Test-LoopbackFree)){throw 'the controller port became busy during preparation'}
    }catch{
        $reason=$_.Exception.Message
        $note=Write-HeldControl 'retarget-held.json' ([ordered]@{schema='cochem-warden-retarget-held/3';phase='PREPARATION';target=$Context.target;attempt=$script:Attempt;task_name=$script:taskName;
            mutation_requested=$false;intent_sha256=$intentHash;state_backup_sha256=$backupHash;reason=$reason;automatic_retry_allowed=$false;requires_reviewed_recovery=$true})
        throw ('The retarget is held before any task change: '+$reason.TrimEnd('.')+'. Nothing was retargeted; the attempt root is consumed, so preserve it and review retarget-held.json before another -Attempt.'+$note)}
    # The only mutation: TASK_UPDATE=4 on the same name with the captured private DACL; never CREATE_OR_UPDATE on a different name.
    $mutationRequested=$false;$after=$null;$afterXml=$null;$afterSddl=$null;$receipt=$null;$receiptHash=$null
    try{
        $definition=$now.task.Definition;$action=$definition.Actions.Item(1)
        $action.Path=$Context.action.execute;$action.WorkingDirectory=$Context.action.working_directory;$action.Arguments=$Context.action.arguments
        $definition.Triggers.Clear()
        # Two-phase start: the r5 logon trigger is registered DISABLED; only a start whose health gate passed enables it, so a host
        # crash at any earlier point cannot relaunch an unverified runtime at the next logon.
        if($Context.target -ceq 'r5'){$trigger=$definition.Triggers.Create(9);$trigger.UserId=$script:logonUser;$trigger.Delay=$script:logonDelay;$trigger.Enabled=$false}
        $definition.RegistrationInfo.Description=$Context.description
        # Registered DISABLED for both targets: only -Start ever enables (no surprise start at the next logon).
        $definition.Settings.Enabled=$false
        $mutationRequested=$true
        $null=$Folder.RegisterTaskDefinition($script:taskName,$definition,4,'SYSTEM',$null,5,$now.sddl)
        # From here the task may already be changed.
        $after=Get-WardenTaskState $Folder
        if($after.readable){
            $afterXml=Write-RegistrationControl (Join-Path $script:targetRoot 'warden-task-after.xml') $after.xml
            $afterSddl=Write-RegistrationControl (Join-Path $script:targetRoot 'warden-task-after.sddl') $after.sddl}
        Assert-RetargetedTask $after $Context $now.sddl
        if($after.enabled -ne $false){throw 'The retargeted task is not disabled after the update; only -Start may enable it.'}
        Assert-TaskXmlOutsideRetargetUnchanged $now.xml $after.xml
        if($after.instances -ne 0 -or $after.state -notin @(1,3)){throw 'The retargeted task shows a running or queued instance.'}
        if($afterXml -cne (Get-TaskXmlSha256 $after.xml)){throw 'The task XML hash conversion differs from the recorded control file.'}
        $receipt=New-ReceiptHead 'cochem-warden-retarget/3' $Context.retargeted_status $Context $source $afterXml
        Add-OrderedFields $receipt ([ordered]@{config_mode=$Context.config_mode;deployment_revision_sha256=$Context.deployment_revision_sha256;source_manifest_sha256=$Context.source_manifest_sha256;
            queue_launch_output=$Context.queue_launch_output;queue_launch_output_root=$Context.queue_launch_output_root;docker_wait_seconds=$Context.docker_wait_seconds;
            enabled_before=$now.enabled;enabled_after=$after.enabled;trigger_enabled_after=(Get-LiveTriggerEnabled $after $Context.target);task_state=$after.state;running_instances=$after.instances;
            action_before=[ordered]@{execute=$now.action_path;arguments=$now.action_arguments;working_directory=$now.action_working_directory};
            triggers_before=@($now.trigger_list);
            source_receipt_path=$source.source_receipt_path;source_receipt_sha256=$source.source_receipt_sha256;source_start_receipt_sha256=$source.source_start_receipt_sha256;
            source_start_evidence=$source.source_start_evidence;source_start_intent_sha256=$source.source_start_intent_sha256;source_start_held_sha256=$source.source_start_held_sha256;
            source_retarget_held_sha256=$source.source_retarget_held_sha256;source_mutation_evidence=$source.source_mutation_evidence;
            stop_receipt_sha256=$source.stop_receipt_sha256;stop_status=$source.stop_status;stop_start_binding=$source.stop_start_binding;
            intent_sha256=$intentHash;state_backup_sha256=$backupHash;task_xml_before_sha256=$beforeXml;task_xml_after_sha256=$afterXml;
            task_sddl_before_sha256=$beforeSddl;task_sddl_after_sha256=$afterSddl;sddl_preserved=$true;xml_outside_action_triggers_unchanged=$true;
            restart_count=0;r4_lineage=$Lineage;old_controller=$Lineage.old_controller;observer_processes=$presence.observer_processes;
            started=$false;supervisor_and_recorder_rebound=$false;credentials_modified=$false;databases_modified=$false;ram_modified=$false;knowledge_rebuilt=$false})
        $receiptHash=Write-RegistrationControl (Join-Path $script:targetRoot 'retarget-receipt.json') ($receipt|ConvertTo-Json -Depth 10)
    }catch{
        $reason=$_.Exception.Message;$readable=($null -ne $after -and $after.readable)
        $note=Write-HeldControl 'retarget-held.json' ([ordered]@{schema='cochem-warden-retarget-held/3';phase=$(if($mutationRequested){'MUTATION_READBACK'}else{'MUTATION_PREPARATION'});
            target=$Context.target;attempt=$script:Attempt;task_name=$script:taskName;mutation_requested=$mutationRequested;readback_readable=$readable;
            readback=$(if($readable){[ordered]@{enabled=$after.enabled;state=$after.state;instances=$after.instances;action_path=$after.action_path;action_arguments=$after.action_arguments;
                working_directory=$after.action_working_directory;triggers=@($after.trigger_list);trigger_enabled=(Get-LiveTriggerEnabled $after $Context.target);sddl=$after.sddl;
                task_xml_sha256=(Get-TaskXmlSha256 $after.xml)}}else{$null});
            task_xml_after_sha256=$afterXml;receipt_written=($null -ne $receiptHash);reason=$reason;automatic_retry_allowed=$false;requires_reviewed_recovery=$true})
        if(-not $mutationRequested){throw ('The retarget is held before the task change: '+$reason+' The task was not registered; preserve the attempt root and review retarget-held.json.'+$note)}
        throw ('The retarget readback is held: '+$reason+' The task action may already be changed; preserve everything and review retarget-held.json. Do not retry with another -Attempt.'+$note)}
    [ordered]@{schema='cochem-warden-retarget-result/3';status=$receipt.status;mode='RETARGET';target=$Context.target;attempt=$script:Attempt;
        receipt_path=(Join-Path $script:targetRoot 'retarget-receipt.json');receipt_sha256=$receiptHash;retarget_receipt_path=(Join-Path $script:targetRoot 'retarget-receipt.json');
        retarget_receipt_sha256=$receiptHash;task_name=$script:taskName;runtime_root=$Context.runtime_root;source_state=$source.source_state;started=$false;
        enabled_before=$now.enabled;enabled_after=$after.enabled;sddl=$now.sddl;source=$source}
}

function Read-RetargetReceipt {
    $path=Join-Path $script:targetRoot 'retarget-receipt.json'
    $control=Read-R3Control $path '' 1048576
    $receipt=$null;try{$receipt=(Read-R3Text $control)|ConvertFrom-Json}catch{throw 'The retarget receipt is not JSON.'}
    [pscustomobject]@{path=$path;sha256=$control.Sha256;receipt=$receipt}
}

function Assert-RetargetReceiptBinding {
    param($Read,$Context)
    # -StartOnly: the attempt root must hold this attempt's successful retarget receipt for exactly the current bindings.
    $receipt=$Read.receipt
    if((Get-JsonMember $receipt 'schema') -cne 'cochem-warden-retarget/3' -or (Get-JsonMember $receipt 'status') -cne $Context.retargeted_status -or
       (Get-JsonMember $receipt 'target') -cne $Context.target -or (Get-JsonMember $receipt 'attempt') -cne $script:Attempt -or
       (Get-JsonMember $receipt 'task_name') -cne $script:taskName -or (Get-JsonMember $receipt 'runtime_root') -cne $Context.runtime_root -or
       (Get-JsonMember $receipt 'config_path') -cne $Context.config_path -or (Get-JsonMember $receipt 'config_sha256') -cne $Context.config_sha256 -or
       (Get-JsonMember $receipt 'install_after_path') -cne $Context.install_after_path -or (Get-JsonMember $receipt 'install_after_sha256') -cne $Context.install_after_sha256 -or
       (Get-JsonMember $receipt 'action.execute') -cne $Context.action.execute -or (Get-JsonMember $receipt 'action.arguments') -cne $Context.action.arguments -or
       (Get-JsonMember $receipt 'action.working_directory') -cne $Context.action.working_directory -or
       -not (Test-TriggerReceiptValue (Get-JsonMember $receipt 'triggers') $Context.target) -or -not (Test-Sha256Text (Get-JsonMember $receipt 'task_xml_sha256')) -or
       (Get-JsonMember $receipt 'source_state') -cnotin @('r4-v1','r5-receipt','r4-restore-receipt','r5-retarget-receipt','r4-restore-retarget-receipt',
           'r5-start-held','r4-restore-start-held','r5-retarget-held','r4-restore-retarget-held') -or
       -not (Test-ExactBool (Get-JsonMember $receipt 'sddl_preserved') $true) -or -not (Test-ExactBool (Get-JsonMember $receipt 'enabled_after') $false) -or
       ($Context.target -ceq 'r5' -and -not (Test-ExactBool (Get-JsonMember $receipt 'trigger_enabled_after') $false)) -or
       ($Context.target -ceq 'r4' -and $null -ne (Get-JsonMember $receipt 'trigger_enabled_after'))){
        throw 'The retarget receipt does not bind this attempt and target.'}
    if(Test-Path -LiteralPath (Join-Path $script:targetRoot 'retarget-held.json')){throw 'This attempt holds a retarget-held.json record; a reviewed recovery is required.'}
    $sddlControl=Read-R3Control (Join-Path $script:targetRoot 'warden-task-before.sddl') '' 65536
    [ordered]@{receipt_path=$Read.path;receipt_sha256=$Read.sha256;sddl=(Read-R3Text $sddlControl);
        source=[ordered]@{source_state=(Get-JsonMember $receipt 'source_state');source_attempt=(Get-JsonMember $receipt 'source_attempt');stop_attempt=(Get-JsonMember $receipt 'stop_attempt')}}
}

function Assert-AttemptTaskXml {
    param($State,$Context,$Binding)
    # Re-audit R-F3: a start (-Start, -StartOnly, or -Apply -Start continuing an attempt) only starts the task THIS attempt
    # registered: the live XML equals this attempt's warden-task-after.xml, digest-bound by its retarget receipt, outside the
    # task and trigger Enabled flags, and that XML's registration Description names this attempt.
    $receipt=$null;try{$receipt=(Read-R3Text (Read-R3Control $Binding.receipt_path $Binding.receipt_sha256 1048576))|ConvertFrom-Json}catch{throw ('The retarget receipt of this attempt could not be bound: '+$_.Exception.Message)}
    $afterSha=Get-JsonMember $receipt 'task_xml_after_sha256'
    if(-not (Test-Sha256Text $afterSha)){throw 'The retarget receipt of this attempt does not record its task XML (task_xml_after_sha256).'}
    $afterXml=Read-R3Text (Read-R3Control (Join-Path $script:targetRoot 'warden-task-after.xml') $afterSha 1048576)
    if((Get-TaskXmlDescription $afterXml) -cne (Get-TargetDescription $Context.target $script:Attempt)){
        throw ('The task XML this attempt recorded does not carry the registration description of '+$Context.target+' attempt '+$script:Attempt+'; preserve it for review.')}
    if((Get-TaskXmlWithoutEnabledFlags $State.xml -Triggers) -cne (Get-TaskXmlWithoutEnabledFlags $afterXml -Triggers)){
        throw ('The live Warden task is not the task '+$Context.target+' attempt '+$script:Attempt+' registered: its XML differs from this attempt''s warden-task-after.xml outside the task and trigger Enabled flags; preserve it for review.')}
    $afterSha
}

function Write-StartHeldRecord {
    param($Folder,$Context,$State,$Facts,[bool]$Interrupted,[string]$Reason)
    # Best effort, on every held or interrupted start (before or after Run): disable the task again so an unverified runtime
    # cannot relaunch at the next logon. Never End it: a running controller is preserved for the owner's review. Then record
    # what was read back, including the r5 logon trigger state (disabled unless the second update already enabled it).
    $disableError=$null
    try{$State.task.Enabled=$false}catch{$disableError=$_.Exception.Message}
    $latest=$null;try{$latest=Get-WardenTaskState $Folder}catch{$latest=$null}
    $readable=($null -ne $latest -and $latest.readable)
    $enabledAfter=$null;$xmlAfter=$null;if($readable){$enabledAfter=$latest.enabled;$xmlAfter=Get-TaskXmlSha256 $latest.xml}
    if($null -eq $disableError -and $enabledAfter -ne $false){$disableError=$(if($readable){'the task still reads enabled after the disable request'}else{'the task could not be read back after the disable request'})}
    # Before Run: Run was never called, or it threw without an instance and the readback shows none (audit C-F7).
    $heldBeforeRun=(-not $Facts.run_requested) -or ($null -eq $Facts.instance_guid -and $null -ne $Facts.run_exception -and $readable -and $latest.instances -eq 0)
    # Re-audit R-F1: every hold after Run is recovered through stop-warden-r5 -RecoverInterruptedStart (its idle, process and XML
    # proofs carry the safety); only a hold before Run keeps the no-stop path (r5-retarget-receipt / r4-restore-retarget-receipt).
    $gate=[bool]$Facts.health_gate_passed
    $record=[ordered]@{schema='cochem-warden-start-held/3';target=$Context.target;attempt=$script:Attempt;task_name=$script:taskName;
        interrupted=$Interrupted;stage=$Facts.stage;health_gate_passed=$gate;stop_recovery_allowed=((-not $heldBeforeRun) -or $Interrupted);
        run_requested=[bool]$Facts.run_requested;run_exception=$Facts.run_exception;held_before_run=[bool]$heldBeforeRun;enable_requested=[bool]$Facts.enable_requested;
        instance_guid=$Facts.instance_guid;task_readable=$readable;
        task_state=$(if($readable){$latest.state}else{$null});running_instances=$(if($readable){$latest.instances}else{$null});
        enabled_before=$State.enabled;enabled_after=$enabledAfter;disable_attempted=$true;disable_error=$disableError;task_xml_after_sha256=$xmlAfter;
        trigger_enable_requested=[bool]$Facts.trigger_enable_requested;trigger_enabled_after=$(if($readable){Get-LiveTriggerEnabled $latest $Context.target}else{$null});
        last_task_result=$(if($readable){$latest.last_task_result}else{$null});last_health_pid=$Facts.last_health_pid;
        receipt_written=$false;reason=$Reason;automatic_retry_allowed=$false;controller_preserved=$true;requires_reviewed_recovery=$true}
    $note=Write-HeldControl 'start-held.json' $record
    [pscustomobject]@{note=$note;disable_error=$disableError;record=$record}
}

function Invoke-StartOnce {
    param($Folder,$Context,$Binding)
    $state=Get-WardenTaskState $Folder;Assert-RetargetedTask $state $Context $Binding.sddl $false
    if($state.instances -ne 0 -or $state.state -notin @(1,3)){throw 'The retargeted task already has an instance; no second start.'}
    $null=Assert-AttemptTaskXml $state $Context $Binding
    Assert-OtherDaemonsIdle (Get-OtherDaemonTaskStates $Folder)
    if(Test-ControllerAlive (Get-ControllerPresence)){throw 'A controller is already alive; no second start.'}
    Assert-NoWorkers (Get-WorkerProcesses) '; no start while work may be active.'
    if(-not (Test-LoopbackFree)){throw 'The controller port is busy; no second start.'}
    if(Test-Path -LiteralPath (Join-Path $script:targetRoot 'start-intent.json')){throw 'A start was already requested from this attempt; preserve it, no automatic repeat.'}
    if(Test-Path -LiteralPath (Join-Path $script:targetRoot 'start-held.json')){throw 'This attempt holds a start-held.json record; a reviewed recovery is required.'}
    $twoPhase=($Context.target -ceq 'r5')
    $intent=[ordered]@{schema='cochem-warden-start-intent/3';attempt=$script:Attempt;target=$Context.target;task_name=$script:taskName;runtime_root=$Context.runtime_root;
        retarget_receipt_sha256=$Binding.receipt_sha256;requested_utc=[DateTime]::UtcNow.ToString('o');enabled_before=$state.enabled;enable_before_run=(-not $state.enabled);
        trigger_enable_after_health_gate=$twoPhase;exactly_one_start=$true;retry=$false}
    $intentHash=Write-RegistrationControl (Join-Path $script:targetRoot 'start-intent.json') ($intent|ConvertTo-Json -Depth 4)
    # From here a start may have happened: every failure leaves start-held.json, and so does an interruption (Ctrl+C, a closed
    # console: the finally below), so only a hard crash leaves start-intent.json alone (stop-warden-r5 -RecoverInterruptedStart).
    $facts=[ordered]@{stage='BEFORE_RUN';run_requested=$false;run_exception=$null;enable_requested=$false;instance_guid=$null;health_gate_passed=$false;
        trigger_enable_requested=$false;last_health_pid=$null}
    $after=$null;$final=$null;$second=$null;$proof=$null;$failure=$null;$enabledByStart=$false;$evaluations=0;$receipt=$null;$receiptHash=$null;$startedXml=$null;$outcomeRecorded=$false
    try{
        try{
            $task=$state.task
            if(-not $task.Enabled){$enabledByStart=$true;$facts.enable_requested=$true;$task.Enabled=$true}
            $facts.stage='RUN';$facts.run_requested=$true
            $instance=$null;try{$instance=$task.Run($null)}catch{$facts.run_exception=$_.Exception.Message;throw}
            $facts.instance_guid=[string]$instance.InstanceGuid
            $facts.stage='HEALTH_WAIT'
            $deadline=[DateTime]::UtcNow.AddSeconds($script:startWaitSeconds);$first=$null;$lastError='';$lastReadiness='';$ended=$false;$hardFailure=$null
            do{
                Start-Sleep -Seconds $script:healthPollSeconds
                try{$instance.Refresh()}catch{
                    $errorItem=$_.Exception;$notRunning=$false
                    while($null -ne $errorItem){if($errorItem.HResult -eq -2147216629){$notRunning=$true;break};$errorItem=$errorItem.InnerException}
                    if($notRunning){$ended=$true;$lastError='the task instance ended before health answered';break}
                    throw}
                $sample=Get-HealthSample
                if(-not $sample.ok){$lastError=$sample.error;continue}
                $facts.last_health_pid=$sample.health.pid
                if($null -eq $first){$first=$sample.health;continue}
                if($sample.health.pid -eq $first.pid -and $sample.health.instance_id -ceq $first.instance_id -and $sample.health.process_started_at -eq $first.process_started_at){
                    $evaluations++;$gates=Get-StartGateFailures $sample.health $Context
                    if(@($gates.hard).Count){$hardFailure=(@($gates.hard) -join '; ');break}
                    if(@($gates.soft).Count){$lastReadiness=(@($gates.soft) -join '; ');$lastError=('post-start readiness not met: '+$lastReadiness);$first=$sample.health;continue}
                    $second=$sample.health;break}
                $first=$sample.health;$lastError='controller identity changed between samples'
            }while([DateTime]::UtcNow -lt $deadline)
            $after=Get-WardenTaskState $Folder
            if($null -ne $hardFailure){throw $hardFailure}
            if($null -eq $second){
                # The owner sees the last transport error and, separately, the last readiness gate that was still open.
                $detail=$lastError;if($lastReadiness -and $detail -cne ('post-start readiness not met: '+$lastReadiness)){$detail+=('; last post-start readiness not met: '+$lastReadiness)}
                throw $(if($ended){$detail}else{('the '+$Context.target+' controller did not answer /health twice with a stable SYSTEM identity from the '+$Context.target+' root and every post-start gate within '+$script:startWaitSeconds+' s: '+$detail)})}
            $facts.stage='POST_START_READBACK'
            if(-not $after.readable){throw 'the task could not be read back after the start'}
            if($after.state -ne 4 -or $after.instances -ne 1){throw 'the task does not show exactly one running instance'}
            $running=[string]$after.task.GetInstances(0).Item(1).InstanceGuid
            if($running -cne $facts.instance_guid){throw 'the running task instance is not the one requested here'}
            if($after.enabled -ne $true){throw 'the task is not enabled after the start'}
            Assert-RetargetedTask $after $Context $Binding.sddl $false
            $proof=Get-TargetProcessProof ([int]$second.pid) $Context
            $facts.health_gate_passed=$true;$final=$after
            if($twoPhase){
                # Second phase (r5 only): the controller is verified, so enable the logon trigger in a second TASK_UPDATE on the same
                # name with the captured DACL, then prove it: the trigger enabled, the task enabled, the same single instance, the
                # SDDL unchanged and the XML unchanged outside the task and trigger Enabled flags.
                $facts.stage='TRIGGER_ENABLE'
                $definition=$after.task.Definition;$definition.Triggers.Item(1).Enabled=$true
                $facts.trigger_enable_requested=$true
                $null=$Folder.RegisterTaskDefinition($script:taskName,$definition,4,'SYSTEM',$null,5,$Binding.sddl)
                $final=Get-WardenTaskState $Folder
                if(-not $final.readable){throw 'the task could not be read back after its logon trigger was enabled'}
                Assert-RetargetedTask $final $Context $Binding.sddl $true
                if($final.enabled -ne $true){throw 'the task is not enabled after its logon trigger was enabled'}
                if($final.state -ne 4 -or $final.instances -ne 1){throw 'the task does not show exactly one running instance after its logon trigger was enabled'}
                if([string]$final.task.GetInstances(0).Item(1).InstanceGuid -cne $facts.instance_guid){throw 'the running task instance changed when the logon trigger was enabled'}
                if((Get-TaskXmlWithoutEnabledFlags $after.xml -Triggers) -cne (Get-TaskXmlWithoutEnabledFlags $final.xml -Triggers)){
                    throw 'the task XML changed outside the task and trigger Enabled flags when the logon trigger was enabled'}}
            $facts.stage='RECEIPT'
            $startedXml=Write-RegistrationControl (Join-Path $script:targetRoot 'warden-task-started.xml') $final.xml
            if($startedXml -cne (Get-TaskXmlSha256 $final.xml)){throw 'The started task XML hash conversion differs from the recorded control file.'}
            $receipt=New-ReceiptHead 'cochem-warden-start/3' $Context.started_status $Context $Binding.source $startedXml
            $routingHolds=Get-JsonListField (Get-JsonMember $second 'routing') 'holds'
            Add-OrderedFields $receipt ([ordered]@{config_mode=$Context.config_mode;deployment_revision_sha256=$Context.deployment_revision_sha256;retarget_receipt_sha256=$Binding.receipt_sha256;
                intent_sha256=$intentHash;instance_guid=$facts.instance_guid;task_state=$final.state;running_instances=$final.instances;
                enabled_before=$state.enabled;enabled_by_start=$enabledByStart;enabled_after=$final.enabled;
                trigger_enabled_before=(Get-LiveTriggerEnabled $after $Context.target);trigger_enabled_after=(Get-LiveTriggerEnabled $final $Context.target);
                task_xml_started_sha256=$startedXml;task_xml_before_trigger_enable_sha256=$(if($twoPhase){Get-TaskXmlSha256 $after.xml}else{$null});
                controller=[ordered]@{pid=$second.pid;instance_id=$second.instance_id;process_started_at=$second.process_started_at;source_root=$second.source_root;
                    version=(Get-JsonMember $second 'version');admission_capacity=(Get-JsonMember $second 'admission_capacity');
                    warden_controller_ready=(Get-JsonMember $second 'components.warden_controller.ready');warden_controller_admission_ready=(Get-JsonMember $second 'components.warden_controller.admission_ready');
                    knowledge_ready=(Get-JsonMember $second 'knowledge.ready');knowledge_authority_matches_capture=(Get-JsonMember $second 'knowledge.authority_matches_capture');
                    trip_errors=(Get-JsonMember $second 'trip_errors')};
                health=[ordered]@{samples_stable=$true;gate_evaluations=$evaluations;admission_field=$Context.admission_field;admission_gated=[bool]$Context.admission_field;
                    active=@((Get-JsonListField $second 'active').items).Count;quarantined_slots=@((Get-JsonMember $second 'quarantined_slots').PSObject.Properties).Count;
                    execution_quarantines=@((Get-JsonListField (Get-JsonMember $second 'routing') 'execution_quarantines').items).Count;
                    routing_holds=$(if($routingHolds.valid){@($routingHolds.items).Count}else{$null})};
                process_proof=$proof;health_samples=2;exactly_one_start_requested=$true;automatic_retry_allowed=$false;supervisor_and_recorder_rebound=$false})
            $receiptHash=Write-RegistrationControl (Join-Path $script:targetRoot 'start-receipt.json') ($receipt|ConvertTo-Json -Depth 10)
            $outcomeRecorded=$true
        }catch{$failure=$_.Exception.Message}
        if($null -ne $failure){
            $heldStart=Write-StartHeldRecord $Folder $Context $state $facts $false $failure
            $outcomeRecorded=$true
            $disableNote=$(if($null -eq $heldStart.disable_error){' The task was disabled again, so it cannot relaunch at the next logon; nothing was ended.'}else{' The task could NOT be confirmed disabled ('+$heldStart.disable_error+'); nothing was ended.'})
            throw ('The '+$Context.target+' start is held: '+$failure.TrimEnd('.')+'. Preserve the task, any running process and all receipts; no automatic retry or stop, and no further -Attempt without a reviewed recovery.'+$disableNote+$heldStart.note)}
    }finally{
        # Audit C-F1(a): an interruption (Ctrl+C, a closed console) skips every catch, so neither start-receipt.json nor
        # start-held.json would exist and the task would stay enabled. Disable it (best effort, never End) and record the
        # interruption with what was read back - unless start-receipt.json already exists: the start completed, and its
        # receipt (not a held record) is what stop-warden-r5 binds (re-audit R-F4).
        if(-not $outcomeRecorded -and $null -eq $receiptHash -and -not (Test-Path -LiteralPath (Join-Path $script:targetRoot 'start-receipt.json'))){
            $null=Write-StartHeldRecord $Folder $Context $state $facts $true ('interrupted at '+$facts.stage+' before a start receipt or a start-held record was written'+$(if($null -ne $failure){' ('+$failure+')'}else{''}))}}
    [ordered]@{schema='cochem-warden-start-result/3';status=$receipt.status;target=$Context.target;attempt=$script:Attempt;
        receipt_path=(Join-Path $script:targetRoot 'start-receipt.json');receipt_sha256=$receiptHash;enabled_by_start=$enabledByStart;enabled_after=$final.enabled;
        trigger_enabled_after=(Get-LiveTriggerEnabled $final $Context.target);controller=$receipt.controller;process_proof=$proof}
}

function Assert-RetargetParameters {
    param($Arguments)
    # Pure parameter rules, checked before anything is read (indexer access: an absent key reads as empty under StrictMode).
    $target=[string]$Arguments['Target'];$attempt=[string]$Arguments['Attempt'];$config=[string]$Arguments['Config']
    $source=[string]$Arguments['SourceAttempt'];$stop=[string]$Arguments['StopAttempt']
    $apply=[bool]$Arguments['Apply'];$startRequested=[bool]$Arguments['Start'];$startOnly=[bool]$Arguments['StartOnly']
    if($target -cnotin @('r5','r4')){throw 'Choose -Target r5 (cutover) or -Target r4 (restore); nothing was changed.'}
    if($attempt -cnotmatch '^v[0-9]{1,3}$'){throw '-Attempt must be v followed by 1-3 digits; nothing was changed.'}
    if($source -and $source -cnotmatch '^v[0-9]{1,3}$'){throw '-SourceAttempt must be v followed by 1-3 digits; nothing was changed.'}
    if($stop -and $stop -cnotmatch '^v[0-9]{1,3}$'){throw '-StopAttempt must be v followed by 1-3 digits; nothing was changed.'}
    # -SourceAttempt alone selects an r5 retarget that never started; with -StopAttempt it selects a started and stopped attempt.
    if($stop -and -not $source){throw '-StopAttempt needs -SourceAttempt (the attempt the stop receipt names). Nothing was changed.'}
    if($startRequested -and -not $apply){throw '-Start is only meaningful together with -Apply.'}
    if($startRequested -and $startOnly){throw 'Choose -Start (retarget then start) or -StartOnly (start an already retargeted attempt), not both.'}
    if($startOnly -and $source){throw '-StartOnly continues an existing attempt from its receipt; -SourceAttempt and -StopAttempt belong to the retarget.'}
    if($target -ceq 'r5' -and -not $startOnly -and -not $config){throw '-Target r5 requires -Config <staged r5 pipeline.json>; nothing was changed.'}
    [ordered]@{target=$target;attempt=$attempt;config=$(if($target -ceq 'r5'){$config}else{''});config_argument_ignored=($target -ceq 'r4' -and [bool]$config);
        source_attempt=$source;stop_attempt=$stop;apply=$apply;start=$startRequested;start_only=$startOnly}
}

function Initialize-RetargetHost {
    foreach($module in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security','CimCmdlets','NetTCPIP')){Import-Module (Join-Path $PSHOME "Modules\$module\$module.psd1") -ErrorAction Stop}
    if($PSVersionTable.PSEdition -ne 'Desktop' -or -not [Environment]::Is64BitProcess -or $env:COMPUTERNAME -cne 'AETHERDESK'){throw 'Use 64-bit Windows PowerShell 5.1 on AETHERDESK.'}
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    [pscustomobject]@{admin=[Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator);name=[string]$identity.Name}
}

function Assert-ApplyIdentity {
    param([bool]$ApplyRequested,$HostContext)
    if($ApplyRequested -and (-not [bool]$HostContext.admin -or [string]$HostContext.name -cne 'AETHERDESK\ansac')){throw '-Apply requires the owner in Administrator Windows PowerShell; nothing was changed.'}
}

function Set-RetargetConstants {
    # Pins recomputed from the files on disk on 2026-10-11. The r5 root, its install-after.json and the staged r5
    # configuration are bound by content verification at run time (Assert-R5InstalledBindings, Assert-R5Config).
    $script:programFiles='C:\Program Files';$script:base=Join-Path $script:programFiles 'CoChem'
    $script:r3Root=Join-Path $script:base 'Pipeline4.2.7-windows-20261007-r3'
    $script:r4Root=Join-Path $script:base 'Pipeline4.2.7-windows-20261009-r4';$script:r4Python=Join-Path $script:r4Root '.venv\Scripts\python.exe';$script:r4SourceRoot=Join-Path $script:r4Root '.venv\Lib'
    $script:basePythonRoot=Join-Path $script:base 'Toolchain4.2.7-windows-20261006\Python312';$script:basePython=Join-Path $script:basePythonRoot 'python.exe'
    # The bind probe runs the pinned base interpreter; each probe re-verifies it behind a deny-write handle.
    $script:probePython=$script:basePython;$script:probePythonPin='d8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa'
    $script:configPin='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
    $script:r3ManifestPin='6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1';$script:r3InstallPin='3b613128192ac44a0a3d9c4b4476fb4c47541edb7563541b9bbf18f84f9a90f6'
    $script:r3RevisionPin='309eb48d9b1c43179ae1f0784d0139357168314f8312a64fb84dbd8380d44eb4'
    $script:r4ManifestPin='1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189';$script:repairPin='e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc'
    $script:r4InstallPin='629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502';$script:r4RevisionPin='38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e'
    # The r4-v1 action names the WardenCommissioning copy; the r4 restore uses the commissioned copy in the r4 root (same bytes).
    $script:commissioningConfig=Join-Path $script:base 'WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json'
    $script:r4RestoreConfig=Join-Path $script:r4Root 'pipeline.json'
    $script:privateRoot='C:\ProgramData\CoChemPipeline427\private'
    $script:queueR4v1=Join-Path $script:privateRoot 'queue-retarget-20261010-r4-v1'
    $script:r4v1Root=Join-Path $script:base 'WardenRetarget4.2.7-windows-20261010-r4-v1'
    $script:r4v1RetargetReceiptPin='1e32c47688ef8ccf7bdd6f2f640ce736e6025508ad7ba04b37543905c3f7feb2'
    $script:r4v1StartReceiptPin='ff6845d18238471775d538641f3e0015aebbbeb73c318c57df177e2a3241db7b'
    $script:r4v1TaskXmlPin='fbfdcd8318d2418cbb8d28badad53a1a8e829a1e9c7143d13600bb62fd04c2be'
    # Fixed namespace date of this sitting (the contract with stop-warden-r5); -Attempt selects the namespace, never reused.
    $script:namespaceDate='20261011'
    $script:r5RootPattern='^Pipeline4\.2\.7-windows-[0-9]{8}-r5$'
    $script:r5ConfigPattern='^C:\\Program Files\\CoChem\\WardenConfig4\.2\.7-windows-[0-9]{8}-r5-v[0-9]{1,3}\\pipeline\.json$'
    $script:r5QueueRoot=Join-Path $script:privateRoot 'queue-launch-r5';$script:dockerWaitSeconds=900
    # The reviewed r5 freeze (W\stopped-runtime-r5-source-manifest.json, source commit 8554c7645801a7bc9c4abad4861bfcbe4ed014b0):
    # its manifest sha, the 13 repair digests of its reviewed_repairs_sha256 map, and the venv bytes the installer pins.
    $script:r5SourceManifestPin='5d8d337baebbc1e4ac29439d418333ab41c0999eb8c0ef8b02acee66850a3045'
    $script:r5RepairPins=[ordered]@{'src/cochem_pipeline/__main__.py'='19f24fc7bcd4d6d0133386aff916efc3ceb6fb359d8604041ef17bdab931b1b3';
        'src/cochem_pipeline/agy_protocol.py'='eaf8d1f407c8792be1343c657afabcf370992df3f82cd9dfb7fe13cf9d41545e';'src/cochem_pipeline/coding.py'='0b97d7bdec4e5c4a1b8f3d1ca8a974f3205d838c6e275e3cc66c5c9826998174';
        'src/cochem_pipeline/config.py'='908e61267a6133379fad7b26b7452e03f1deb97f44f53eb9e26c07de8212bbd4';'src/cochem_pipeline/controller_guard.py'='e18304719af11e0dd5280d777c6157cc9bc873dd29b7dc15527d6b3667656eba';
        'src/cochem_pipeline/failures.py'='625f9c6e045f6a108be04a6a13767593db08ac960bb3839fade0a37e36c6edf5';'src/cochem_pipeline/knowledge.py'='1bf720ed5df342704552b3e0996ee1cdaebd8f9d7f26fc345b4e5a848e2d2f0f';
        'src/cochem_pipeline/operator_views.py'='8b6b51e9ef3879ad13f714ee44390fc4bb7e41cc9bf5c7cbdc589413f1efaf42';'src/cochem_pipeline/runtime.py'='946adaf95b1755138f0e7bf79576c8290569d7fb98851e8962e00ca73b40a208';
        'src/cochem_pipeline/service.py'='38ab9dc1853dc38b0ee824a1f80f5e4bea503ec2e821c7803b065baa501c5128';'src/cochem_pipeline/store.py'='b3604d227b23d2f3a68e0106b852ad672127089df68b0d512131455fa552d0a0';
        'src/cochem_pipeline/worker.py'='20a084071bfa172aa787d1a96168b8c541089823559e8f00518b164c16ae0f41';'src/cochem_supervisor/runner.py'='adc8ccf33841438f3104e64325ff84b7826c49db297c8bc3f02ebb55ad96cf31'}
    $script:r5PyvenvPin='0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d';$script:r5VenvPythonPin='560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'
    $script:r5VerifiedUnchanged=153
    # The stager's receipt (stage-pipeline-config-r5-v1.ps1) beside every staged r5 configuration; a held staging record refuses it.
    $script:stagingReceiptSchema='cochem-config-only-staging/2';$script:stagingReceiptPattern='^staging-receipt-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.json$'
    $script:logonUser='AETHERDESK\ansac';$script:logonDelay='PT1M'
    $script:taskName='CoChem-4.2.7-Warden';$script:port=47824;$script:clientConfig='C:\Users\ansac\CoChem427\pipeline-client-r3.json'
    $script:tokenFile='C:\Users\ansac\CoChem427\controller.token';$script:startWaitSeconds=240;$script:healthPollSeconds=5
    $script:backupCopyFlags=@('/B')
    # The two reviewed observer recorders (SYSTEM tasks that only record), matched on their pinned script paths.
    $script:observerPattern='\\SupervisorObservation4\.2\.7-windows-20261007-r3-v1\\held-supervisor-observation-r3-v1\.py"?\s+--observe\b|\\ResourceObservation4\.2\.7-windows-20261008-r3-v4\\package\\observe_resources\.py"?\s+--run-observer\b'
    $script:backupHelper=Join-Path $script:scriptDirectory 'backup-private-databases-r4.py';$script:backupHelperPin='f00ad064215d1a689f1355a18da9f159b16d45699507975de957a4cb832a0f8b'
    $script:targetRoot=Join-Path $script:base ('WardenRetarget4.2.7-windows-'+$script:namespaceDate+'-'+$script:Target+'-'+$script:Attempt)
    $script:queueRestart=Join-Path $script:privateRoot ('queue-restart-'+$script:namespaceDate+'-r4-'+$script:Attempt)
    $script:healthPython=$script:r4Python;$script:targetSourceRoot=$null
    $script:runtimeRoots=@($script:r3Root,$script:r4Root,$script:basePythonRoot)
}

function Import-RetargetHelpers {
    # Dot-sourced by Invoke-RetargetR5Main, so the reviewed functions are defined in its scope (hash-pinned, as v2.2).
    $copyHelper='C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1'
    foreach($text in Import-ReviewedFunctions $copyHelper '0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b' @('Assert-NoReparseAncestors','Assert-ProtectedPath','New-CodeAcl','New-ProtectedDirectory','Initialize-FileIdentity','Open-VerifiedFile','Copy-VerifiedPayload')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $script:scriptDirectory 'check-worker-native-status-r3.ps1') '18f58ebb448d8a0c6329dd187d4a9a27fa9cbe942cd05e906bb7aabc67e787a7' @('Read-R3Control','Read-R3Text')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $script:scriptDirectory 'register-stopped-warden-r3.ps1') 'eccc593f36cbf488a54775b4343bcf3cf8b261b7cd81e5536fb7f2f18466a198' @('Assert-RegisteredTaskAcl','Write-RegistrationControl')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $script:scriptDirectory 'protected-code-inspection-v4.ps1') '5c01543cbb8b8d64b2b9f1bab4a13f87f8ff9e1ab3e82dfb6fc547144c77b95d' @('Assert-CodeTreeOnce')){. ([scriptblock]::Create($text))}
    Initialize-FileIdentity
    $held.Add((Open-VerifiedFile $script:backupHelper $script:backupHelperPin (Get-Item -LiteralPath $script:backupHelper).Length))
}

function Connect-TaskFolder {
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect();$scheduler.GetFolder('\')
}

function Invoke-RetargetR5Main {
    param($Arguments,[string]$ScriptDirectory)
    $ErrorActionPreference='Stop';Set-StrictMode -Version Latest
    $request=Assert-RetargetParameters $Arguments
    # The validated request becomes the script-scope state ('' for an omitted -SourceAttempt/-StopAttempt); the parameters
    # carry no [Validate*] attribute, so these copies cannot throw (see the header).
    $script:Target=$request.target;$script:Attempt=$request.attempt;$script:SourceAttempt=$request.source_attempt;$script:StopAttempt=$request.stop_attempt
    $script:scriptDirectory=$ScriptDirectory
    $hostContext=Initialize-RetargetHost;$script:admin=[bool]$hostContext.admin
    Assert-ApplyIdentity $request.apply $hostContext
    Set-RetargetConstants
    $held=[Collections.Generic.List[IO.FileStream]]::new()
    try{
        . Import-RetargetHelpers
        $holds=@();$runtime4=$null;$lineage=$null;$client=$null;$r5=$null;$configBinding=$null;$parser=$null;$codeTree=$null;$context=$null
        $taskState=$null;$source=$null;$binding=$null;$otherDaemons=@();$presence=$null;$workers=$null;$loopbackFree=$null;$backupRights=$null;$receiptRead=$null
        try{$script:runtimeRoots=@($script:runtimeRoots)+@(Get-R5RootCandidates)}catch{$holds+=('Installed runtime roots could not be listed: '+$_.Exception.Message)}
        # -Apply -Start on an attempt that already holds its retarget receipt continues with the start only.
        $startOnly=$request.start_only;$continued=$false
        if($request.apply -and $request.start -and (Test-Path -LiteralPath (Join-Path $script:targetRoot 'retarget-receipt.json'))){$startOnly=$true;$continued=$true}
        try{$runtime4=Assert-R4Pins (Assert-R4InstalledBindings)}catch{$holds+=('r4 runtime is not the reviewed build: '+$_.Exception.Message)}
        try{$lineage=Assert-R4RetargetLineage}catch{$holds+=('r4 v1 retarget lineage: '+$_.Exception.Message)}
        try{$client=Assert-ClientConfig}catch{$holds+=('Client config: '+$_.Exception.Message)}
        $configPath=$request.config
        if($startOnly){
            try{$receiptRead=Read-RetargetReceipt
                $recorded=Get-JsonMember $receiptRead.receipt 'config_path'
                if($request.target -ceq 'r5'){if(-not $configPath){$configPath=[string]$recorded}elseif($configPath -cne $recorded){$holds+='-Config differs from the configuration this attempt was retargeted to.'}}
                if($continued -and $request.source_attempt -and ($request.source_attempt -cne [string](Get-JsonMember $receiptRead.receipt 'source_attempt') -or $request.stop_attempt -cne [string](Get-JsonMember $receiptRead.receipt 'stop_attempt'))){
                    $holds+='-SourceAttempt/-StopAttempt differ from the source recorded by this attempt.'}
            }catch{$holds+=('Retarget receipt: '+$_.Exception.Message)}}
        if($request.target -ceq 'r5'){
            try{$r5=Assert-R5InstalledBindings (Find-R5Root)}catch{$holds+=('r5 runtime (run install-stopped-runtime-r5.ps1 -Apply first): '+$_.Exception.Message)}
            try{$configBinding=Assert-R5Config $configPath}catch{$holds+=('r5 configuration: '+$_.Exception.Message)}
            if($null -ne $r5 -and $null -ne $configBinding){$context=New-TargetContext 'r5' $r5 $configBinding}
        }elseif($null -ne $runtime4){$context=New-TargetContext 'r4' $runtime4 $null}
        if($null -ne $context){$script:targetSourceRoot=$context.source_root}
        # Elevated, every runtime tree whose interpreter runs with the elevated token or as SYSTEM is inspected once.
        if($script:admin){
            $codeTree=$true
            foreach($root in @($script:r4Root)+@($(if($null -ne $r5){$r5.root}))){try{$null=Assert-CodeTreeOnce $root}catch{$codeTree=$false;$holds+=('Code tree inspection of '+$root+': '+$_.Exception.Message)}}}
        if($request.target -ceq 'r5' -and $null -ne $context -and (-not $script:admin -or $codeTree -eq $true)){
            try{$parser=Invoke-R5ConfigParser $r5.python $configBinding.path}catch{$holds+=('r5 configuration parser: '+$_.Exception.Message)}}
        $folder=Connect-TaskFolder
        try{$taskState=Get-WardenTaskState $folder
            if(-not $taskState.readable){$holds+='Warden task definition is unreadable without elevation; re-read during -Apply.'}
            elseif($startOnly){
                if($null -ne $context -and $null -ne $receiptRead){$binding=Assert-RetargetReceiptBinding $receiptRead $context;Assert-RetargetedTask $taskState $context $binding.sddl $false
                    $null=Assert-AttemptTaskXml $taskState $context $binding}
                elseif($null -eq $receiptRead){$holds+='Warden task: no retarget receipt binds this attempt.'}}
            else{$source=Assert-RetargetSource $taskState}
        }catch{$holds+=('Warden task: '+$_.Exception.Message)}
        try{$otherDaemons=@(Get-OtherDaemonTaskStates $folder)
            $active=@($otherDaemons|Where-Object {$_.active -eq $true}|ForEach-Object {$_.name});$deferred=@($otherDaemons|Where-Object {$_.state -eq 'ACCESS_DENIED_DEFERRED'}|ForEach-Object {$_.name})
            if($active.Count){$holds+=('Managed daemon tasks must remain stopped and disabled: '+($active -join ', '))}
            if($deferred.Count){$holds+=('Managed daemon task definitions are unreadable without elevation; re-read during -Apply: '+($deferred -join ', '))}
        }catch{$holds+=('Managed daemon tasks: '+$_.Exception.Message)}
        try{$presence=Get-ControllerPresence
            if(Test-ControllerAlive $presence){$holds+='A controller process, an unclassified runtime process or the loopback port is alive; stop nothing, investigate.'}
            elseif(-not $script:admin -and $presence.uninspectable_python_processes -ne 0){$holds+=([string]$presence.uninspectable_python_processes+' python processes could not be inspected without elevation (observer recorder processes are expected); the elevated plan and run classify them.')}}
        catch{$holds+=('Controller presence could not be established: '+$_.Exception.Message)}
        try{$workers=Get-WorkerProcesses;Assert-NoWorkers $workers '; stop nothing, investigate.'}catch{$holds+=('Worker processes: '+$_.Exception.Message)}
        try{$loopbackFree=Test-LoopbackFree;if(-not $loopbackFree){$holds+='The controller port cannot be bound exclusively; a controller may be alive.'}}catch{$holds+=('Loopback probe: '+$_.Exception.Message)}
        # Elevated, the read-only plan also proves the backup rights and the readability of the SYSTEM-only root (robocopy /L writes nothing).
        if($script:admin -and -not $startOnly){try{$backupRights=Test-BackupCopyRights}catch{$holds+=('Backup copy rights: '+$_.Exception.Message)}}
        if($startOnly){
            if(Test-Path -LiteralPath (Join-Path $script:targetRoot 'start-intent.json')){$holds+='A start was already requested from this attempt; preserve it.'}
            if(Test-Path -LiteralPath (Join-Path $script:targetRoot 'start-held.json')){$holds+='This attempt holds a start-held.json record; a reviewed recovery is required.'}
            if(Test-Path -LiteralPath (Join-Path $script:targetRoot 'retarget-held.json')){$holds+='This attempt holds a retarget-held.json record; a reviewed recovery is required.'}}
        else{
            if(Test-Path -LiteralPath $script:targetRoot){$holds+='Retarget root already exists for this attempt; preserve it and choose another -Attempt.'}
            if($request.target -ceq 'r4'){
                # A probe of an existing child of the SYSTEM-only root is refused; a missing child answers false.
                try{if(Test-Path -LiteralPath $script:queueRestart -ErrorAction Stop){$holds+='Fresh queue-observation directory already exists; choose another -Attempt.'}}catch{$holds+='Fresh queue-observation directory probe was refused, so it exists under the SYSTEM-only root; choose another -Attempt.'}}}
        $readable=($null -ne $taskState -and $taskState.readable)
        # Arrays are taken by plain assignment (a $() subexpression would unroll a one-element trigger list).
        $expectedAction=$null;$expectedTriggers=$null;if($null -ne $context){$expectedAction=$context.action;$expectedTriggers=$context.triggers}
        $plan=[ordered]@{schema='cochem-warden-retarget-plan/3';mode='READ_ONLY_PLAN';target=$request.target;attempt=$script:Attempt;start_only=$startOnly;continued_from_retarget_receipt=$continued;
            task_name=$script:taskName;target_root=$script:targetRoot;source=$source;source_attempt=$script:SourceAttempt;stop_attempt=$script:StopAttempt;
            r4_runtime_verified=($null -ne $runtime4);r4_lineage=$lineage;client_config=$client;
            target_runtime=$(if($null -ne $context){[ordered]@{runtime_root=$context.runtime_root;source_root=$context.source_root;install_after_path=$context.install_after_path;install_after_sha256=$context.install_after_sha256;deployment_revision_sha256=$context.deployment_revision_sha256}}else{$null});
            config=$(if($null -ne $context){[ordered]@{path=$context.config_path;sha256=$context.config_sha256;mode=$context.config_mode;parser=$parser}}else{$null});config_argument_ignored=$request.config_argument_ignored;
            expected_action=$expectedAction;expected_triggers=$expectedTriggers;
            queue_launch_output_new=$(if($request.target -ceq 'r4'){$script:queueRestart}else{$null});queue_launch_output_root=$(if($request.target -ceq 'r5'){$script:r5QueueRoot}else{$null});
            code_tree_verified=$codeTree;task_readable=$readable;
            task_summary=$(if($readable){[ordered]@{enabled=$taskState.enabled;state=$taskState.state;instances=$taskState.instances;action_path=$taskState.action_path;triggers=$taskState.triggers;task_xml_sha256=(Get-TaskXmlSha256 $taskState.xml)}}else{$null});
            other_daemon_tasks=$otherDaemons;controller_presence=$presence;
            worker_processes=$(if($null -ne $workers){[ordered]@{workers=$workers.workers;uninspectable_count=@($workers.uninspectable_processes).Count;exited_during_sweep=$workers.exited_during_sweep;authoritative=$workers.authoritative}}else{$null});
            loopback_port_free=$loopbackFree;backup_copy_rights_verified=$backupRights;backup_helper_sha256=$script:backupHelperPin;backup_copy_flags=$script:backupCopyFlags;
            administrator=$script:admin;holds=$holds;tasks_changed=0;started=$false;supervisor_and_recorder_rebound=$false;automatic_retry_allowed=$false}
        if(-not $request.apply){$plan|ConvertTo-Json -Depth 8;return}
        if($holds.Count){throw ('Retarget is held. Nothing was changed: '+($holds -join ' | '))}
        if($startOnly){
            $result=[ordered]@{schema='cochem-warden-retarget-result/3';status=$null;mode='START_ONLY';target=$context.target;attempt=$script:Attempt;receipt_path=$null;receipt_sha256=$null;
                retarget_receipt_path=$binding.receipt_path;retarget_receipt_sha256=$binding.receipt_sha256;continued_from_retarget_receipt=$continued}
            $result.start=Invoke-StartOnce $folder $context $binding
            $result.status=$result.start.status;$result.receipt_path=$result.start.receipt_path;$result.receipt_sha256=$result.start.receipt_sha256
            $result.enabled_by_start=$result.start.enabled_by_start;$result.enabled_after=$result.start.enabled_after
        }else{
            $result=Invoke-Retarget $folder $context $lineage
            if($request.start){
                $binding=[ordered]@{receipt_path=$result.retarget_receipt_path;receipt_sha256=$result.retarget_receipt_sha256;sddl=$result.sddl;
                    source=[ordered]@{source_state=$result.source.source_state;source_attempt=$result.source.source_attempt;stop_attempt=$result.source.stop_attempt}}
                $result.start=Invoke-StartOnce $folder $context $binding;$result.mode='RETARGET_AND_START';$result.started=$true;$result.retarget_status=$result.status
                $result.status=$result.start.status;$result.receipt_path=$result.start.receipt_path;$result.receipt_sha256=$result.start.receipt_sha256
                $result.retarget_enabled_after=$result.enabled_after;$result.enabled_by_start=$result.start.enabled_by_start;$result.enabled_after=$result.start.enabled_after}
            $result.Remove('sddl');$result.Remove('source')
        }
        $result|ConvertTo-Json -Depth 8
    }finally{foreach($stream in $held){$stream.Dispose()}}
}

# Invocation boundary: the only top-level statement. Fixtures dot-source the functions above from the AST without running it.
Invoke-RetargetR5Main -Arguments ([ordered]@{Target=$Target;Config=$Config;Apply=[bool]$Apply;Start=[bool]$Start;StartOnly=[bool]$StartOnly;Attempt=$Attempt;SourceAttempt=$SourceAttempt;StopAttempt=$StopAttempt}) -ScriptDirectory $PSScriptRoot
