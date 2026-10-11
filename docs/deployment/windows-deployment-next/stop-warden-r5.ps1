#Requires -Version 5.1
<# Ends and disables the r5 CoChem-4.2.7-Warden: the rollback and Gemini-fallback stop of the r5 sitting (stages S11-S14,
   R4-RESTORE). Derived from stop-warden-r4.ps1 (sha256 bd54cb8194d256109aa8dae95451b87780566f7094f26f52d251840944bbc71b),
   itself derived from retarget-warden-r4.ps1 v2.2 (sha256 8ee6b412f6be176dfac7c2c1b2340f1973e08358c7d22da6d4515e79f0327a4e):
   functions shared unchanged with those scripts are identical copies, and the reviewed helpers are imported by hash as they
   import them.
   It stops whichever runtime the reviewed retarget-warden-r5.ps1 last started, named by -RetargetTarget (r5, the default,
   or r4 for an R4-RESTORE) and -RetargetAttempt: its start receipt is
   C:\Program Files\CoChem\WardenRetarget4.2.7-windows-20261011-<RetargetTarget>-<RetargetAttempt>\start-receipt.json.
   Nothing about the live task is pre-pinned here. The action and the trigger set (r5: one logon trigger; r4: none) are
   bound from that start receipt. The r5 runtime is bound by content verification of the installation receipt the start
   receipt names (Assert-R5InstalledBindings; its sha cannot exist before the sitting); the r4 runtime by the reviewed v2.2
   bindings and the r4 pins (Assert-R4InstalledBindings, Assert-R4Pins). The controller pid and instance in the start
   receipt are deliberately NOT bound: the r5 logon trigger restarts the Warden after every reboot with a new pid and a new
   queue-launch child directory. The live controller is identified from the live task instance, its process (image, command
   line, SYSTEM owner, launcher, creation time) and the owner of the loopback port.
   Default is a read-only plan (cochem-warden-stop-plan/2). It binds the start receipt and the installation, reads the task,
   the managed daemon tasks, the processes, the loopback port and the controller's /health and /operator views, and prints
   the same predicates -Apply enforces. Unelevated, the SYSTEM-only task definition is unreadable and is deferred.
   -Apply (AETHERDESK\ansac in elevated 64-bit Windows PowerShell 5.1):
     1. binds the start receipt and the installation and inspects that runtime's code tree once before its interpreter runs
        elevated; the client configuration must name exactly the loopback port 47824 and the pinned token file;
     2. requires the live task to be the exact SYSTEM daemon the receipt names (its action and trigger set, principal,
        settings, private DACL) running exactly one enabled instance (RUNNING), or already stopped with no instance and a free
        port (ALREADY_STOPPED, enabled or disabled);
     RUNNING:
     3. proves the controller idle: two /health samples at least 5 s apart with one stable SYSTEM identity from the bound
        runtime's source root, one GET
        /operator whose 200-job window is not truncated, active [], quarantined_slots {}, routing.active_reservations [],
        routing.execution_quarantines [], no queue row IN_PROGRESS, PENDING or PENDING_RETRY, then no slot worker process;
        polled no faster than every 10 s up to -IdleWaitSeconds;
     4. records the controller and its launcher (image, parent, creation time, socket owner), the running task instance,
        the boot time and the observer processes (left alone);
     5. creates C:\Program Files\CoChem\WardenStop4.2.7-windows-20261011-r5-<Attempt> (the one stop namespace for both
        targets; refused when present; a root that existed before this run is never written to) and writes the task XML and
        SDDL, the idle evidence and stop-intent.json before any change;
     6. requests Task Scheduler End exactly once (the COM task object's Stop method, flags 0);
     7. waits up to -ExitWaitSeconds for: no task instance; launcher and controller gone (pid and creation time); no
        controller-like process; nothing listening on 47824 and an exclusive bind succeeding; no slot worker. Anything left
        -> stop-held.json naming it and a throw: the task is NOT disabled and nothing is killed;
     8. disables the task (otherwise an r5 logon trigger relaunches it at the next logon, and the retarget requires a
        disabled source either way) and proves it: disabled, no instance, action and trigger set unchanged, security
        descriptor byte-equal and the XML unchanged outside <Settings><Enabled>; then the port is proved free once more;
     9. writes stop-receipt.json (cochem-warden-stop/2, WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED) carrying
        retarget_target and retarget_attempt.
     ALREADY_STOPPED: no idle wait and no End. A task that is still enabled is disabled with the same gate and readback; an
     already disabled task is not written at all. stop-receipt.json says WARDEN_ALREADY_STOPPED_CLEAN_NOOP.
   task_xml_after_sha256 is Get-TaskXmlSha256 of the live RegisteredTask.Xml string read after the disable: the sha256
   (lowercase hex) of its UTF-8 bytes without BOM, no normalization; retarget-warden-r5.ps1 binds it.
   End terminates the daemon outside its SIGINT/SIGTERM path, so a RUNNING stop is unclean by construction (no crash record,
   no finally block); the receipt says so. Every failure after the stop root exists leaves stop-held.json.
   Never touched: any other task (the held supervisor observation and the resource observation recorder included),
   credentials, databases, the RAM disk, Docker, knowledge. No start, retry, kill or delete ever occurs.
   Audit fixes (2026-10-11 r5 sitting audit):
   C-F1(b) -RecoverInterruptedStart binds a start of the -RetargetAttempt attempt that has start-intent.json and NO
     start-receipt.json: no start-held.json at all (START_CRASHED_NO_RECORD), or a start-held.json of a hold after Run
     (held_before_run false, stop_recovery_allowed true; re-audit R-F1): interrupted true -> START_INTERRUPTED_HELD; else
     health_gate_passed true -> START_HELD_AFTER_HEALTH_GATE; else START_HELD_BEFORE_HEALTH_GATE. A hold before Run is refused
     (the retarget binds it as a never-started source). The action, triggers, runtime and configuration are then bound from
     the same attempt's retarget-receipt.json, pinned by the start intent. Without the switch only a completed start
     (START_RECEIPT) binds, as before. A disabled task with exactly one running instance is stopped as RUNNING for every
     binding (re-audit R-F5); the live logon trigger user is compared by SID (re-audit R-F2).
   C-F4 the r5 installation must name the reviewed freeze manifest (5d8d337b...), its 13 repair digests and the installer's
     pyvenv.cfg and venv launcher pins, prove installed_repairs_verified, verification.r5_repairs_installed and
     verified_unchanged 153, and its root must not hold install-held.json.
   C-F5 the live task XML is bound to the attempt's warden-task-after.xml (its Description names the attempt) outside
     <Settings><Enabled> and the trigger Enabled flags, and for a completed start to its warden-task-started.xml outside
     <Settings><Enabled>. The r5 logon trigger is registered disabled and enabled only after the health gate (two-phase start):
     a completed start must show it enabled; an interrupted or crashed start may show it disabled, or enabled when its held
     readback says so or no readback exists. stop-receipt.json records start_binding and trigger_enabled_after. #>
[CmdletBinding()]
param([switch]$Apply,[ValidatePattern('^v[0-9]{1,3}$')][string]$Attempt='v1',[Parameter(Mandatory=$true)][ValidatePattern('^v[0-9]{1,3}$')][string]$RetargetAttempt,
      [ValidateSet('r5','r4',IgnoreCase=$false)][string]$RetargetTarget='r5',[ValidateRange(10,900)][int]$IdleWaitSeconds=120,[ValidateRange(10,900)][int]$ExitWaitSeconds=90,
      [switch]$RecoverInterruptedStart)

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

function Test-ExactBool {param($Value,[bool]$Expected)($Value -is [bool]) -and ($Value -eq $Expected)}
function Test-ExactInt {param($Value,[long]$Expected)(($Value -is [int]) -or ($Value -is [long])) -and ([long]$Value -eq $Expected)}

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

function Get-WardenTaskState {
    param($Folder)
    # Exact state or an explicit deferral; never a guess.
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
            triggers=[int]$definition.Triggers.Count;actions=[int]$definition.Actions.Count;multiple_instances=[int]$definition.Settings.MultipleInstances;
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

function Get-ControllerPresence {
    # Fail closed: an unanswerable port query is a hold, not "free"; only the cmdlet's own
    # no-match error means that nothing listens. Controller-like command lines are recognised
    # from any image path. The two reviewed observer recorders and GUI MCP clients are
    # reported, not counted. Python processes whose image and command line cannot be read are
    # counted as uninspectable (an unelevated plan sees every SYSTEM process that way).
    try{$listening=@(Get-NetTCPConnection -LocalPort $script:port -State Listen -ErrorAction Stop)}
    catch{if($_.FullyQualifiedErrorId -like 'CmdletizationQuery_NotFound*'){$listening=@()}else{throw ('Loopback port state could not be established: '+$_.Exception.Message)}}
    $controllers=@();$observers=@();$clients=@();$unclassified=@();$uninspectable=0
    foreach($process in @(Get-CimInstance Win32_Process -ErrorAction Stop)){
        $path=[string]$process.ExecutablePath;$command=[string]$process.CommandLine;$name=[string]$process.Name
        $rooted=$path -and ($path.StartsWith($script:runtimePrefix,[StringComparison]::OrdinalIgnoreCase) -or $path.StartsWith($script:basePythonRoot,[StringComparison]::OrdinalIgnoreCase))
        $entry=[ordered]@{pid=$process.ProcessId;parent=$process.ParentProcessId;path=$path;command=$command}
        if($command -match 'cochem_pipeline\s+daemon\b|cochem_supervisor\b|provision-execution\b|cochem-supervisor\b|cochem-pipeline(\.exe)?"?\s+daemon\b'){$controllers+=$entry}
        elseif($command -match $script:observerPattern){$observers+=$entry}
        elseif($rooted -and $command -match 'cochem_pipeline\s+(mcp|health|status|submit|cancel|projects|code|code-status|code-cancel|code-resume|knowledge-\w+)\b'){$clients+=$entry}
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

function Set-StopConstants {
    # The pins this stop needs (values as v2.2, stop-warden-r4 and retarget-warden-r5), the r4 runtime and its restore action,
    # the r4 lineage the r5 install must name, the reviewed r5 repair set (addendum A6), the r5 action shape (addendum A2),
    # the loopback client pins and the two namespaces.
    $script:programFiles='C:\Program Files';$script:base=Join-Path $script:programFiles 'CoChem'
    $script:r3Root=Join-Path $script:base 'Pipeline4.2.7-windows-20261007-r3'
    $script:r4Root=Join-Path $script:base 'Pipeline4.2.7-windows-20261009-r4';$script:r4Python=Join-Path $script:r4Root '.venv\Scripts\python.exe';$script:r4SourceRoot=Join-Path $script:r4Root '.venv\Lib'
    # Every pipeline runtime root (r1..r5) lies under this prefix; Get-ControllerPresence classifies their processes.
    $script:runtimePrefix=Join-Path $script:base 'Pipeline4.2.7-windows-'
    $script:basePythonRoot=Join-Path $script:base 'Toolchain4.2.7-windows-20261006\Python312';$script:basePython=Join-Path $script:basePythonRoot 'python.exe'
    # The bind probe runs the pinned base interpreter; each probe re-verifies it behind a deny-write handle.
    $script:probePython=$script:basePython;$script:probePythonPin='d8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa'
    # The reference configuration every runtime root keeps (configuration_unchanged); the task's own config is bound by the start receipt.
    $script:configPin='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
    $script:r3ManifestPin='6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1';$script:r3InstallPin='3b613128192ac44a0a3d9c4b4476fb4c47541edb7563541b9bbf18f84f9a90f6'
    $script:r3RevisionPin='309eb48d9b1c43179ae1f0784d0139357168314f8312a64fb84dbd8380d44eb4'
    $script:r4ManifestPin='1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189';$script:repairPin='e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc'
    $script:r4InstallPin='629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502';$script:r4RevisionPin='38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e'
    # The commissioned file: the r4 restore uses the copy in the r4 root, the r5 Gemini-held fallback may name the WardenCommissioning copy.
    $script:commissioningConfig=Join-Path $script:base 'WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json'
    $script:r4RestoreConfig=Join-Path $script:r4Root 'pipeline.json'
    $script:r5SourceFiles=166
    # Addendum A6: the 12 r5 source files plus src/cochem_pipeline/__main__.py (13 changed, 153 of 166 unchanged).
    $script:reviewedRepairPaths=@('src/cochem_pipeline/__main__.py','src/cochem_pipeline/agy_protocol.py','src/cochem_pipeline/coding.py','src/cochem_pipeline/config.py',
        'src/cochem_pipeline/controller_guard.py','src/cochem_pipeline/failures.py','src/cochem_pipeline/knowledge.py','src/cochem_pipeline/operator_views.py',
        'src/cochem_pipeline/runtime.py','src/cochem_pipeline/service.py','src/cochem_pipeline/store.py','src/cochem_pipeline/worker.py','src/cochem_supervisor/runner.py')
    # C-F4 (audit-build F4): the reviewed r5 freeze is pinned, as install-stopped-runtime-r5.ps1 pins it: the manifest
    # stopped-runtime-r5-source-manifest.json (source commit 8554c7645801a7bc9c4abad4861bfcbe4ed014b0), the 13 digests of its
    # reviewed_repairs_sha256 map, and the pyvenv.cfg and venv launcher of the installer's Assert-NewRuntimeInterpreter.
    $script:r5ManifestPin='5d8d337baebbc1e4ac29439d418333ab41c0999eb8c0ef8b02acee66850a3045'
    $script:r5RepairPins=[ordered]@{
        'src/cochem_pipeline/__main__.py'='19f24fc7bcd4d6d0133386aff916efc3ceb6fb359d8604041ef17bdab931b1b3'
        'src/cochem_pipeline/agy_protocol.py'='eaf8d1f407c8792be1343c657afabcf370992df3f82cd9dfb7fe13cf9d41545e'
        'src/cochem_pipeline/coding.py'='0b97d7bdec4e5c4a1b8f3d1ca8a974f3205d838c6e275e3cc66c5c9826998174'
        'src/cochem_pipeline/config.py'='908e61267a6133379fad7b26b7452e03f1deb97f44f53eb9e26c07de8212bbd4'
        'src/cochem_pipeline/controller_guard.py'='e18304719af11e0dd5280d777c6157cc9bc873dd29b7dc15527d6b3667656eba'
        'src/cochem_pipeline/failures.py'='625f9c6e045f6a108be04a6a13767593db08ac960bb3839fade0a37e36c6edf5'
        'src/cochem_pipeline/knowledge.py'='1bf720ed5df342704552b3e0996ee1cdaebd8f9d7f26fc345b4e5a848e2d2f0f'
        'src/cochem_pipeline/operator_views.py'='8b6b51e9ef3879ad13f714ee44390fc4bb7e41cc9bf5c7cbdc589413f1efaf42'
        'src/cochem_pipeline/runtime.py'='946adaf95b1755138f0e7bf79576c8290569d7fb98851e8962e00ca73b40a208'
        'src/cochem_pipeline/service.py'='38ab9dc1853dc38b0ee824a1f80f5e4bea503ec2e821c7803b065baa501c5128'
        'src/cochem_pipeline/store.py'='b3604d227b23d2f3a68e0106b852ad672127089df68b0d512131455fa552d0a0'
        'src/cochem_pipeline/worker.py'='20a084071bfa172aa787d1a96168b8c541089823559e8f00518b164c16ae0f41'
        'src/cochem_supervisor/runner.py'='adc8ccf33841438f3104e64325ff84b7826c49db297c8bc3f02ebb55ad96cf31'}
    $script:r5PyvenvPin='0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d';$script:r5VenvPythonPin='560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'
    $script:r5VerifiedUnchanged=153
    $script:r5RootPattern='^C:\\Program Files\\CoChem\\Pipeline4\.2\.7-windows-[0-9]{8}-r5\z'
    # The staged r5 configuration, or the commissioned file for the held fallback; both are protected and sha-bound by the receipt.
    $script:r5ConfigPattern='^C:\\Program Files\\CoChem\\(WardenConfig4\.2\.7-windows-[0-9]{8}-r5-v[0-9]{1,3}|WardenCommissioning4\.2\.7-windows-20261007-r3-v1)\\pipeline\.json\z'
    $script:privateRoot='C:\ProgramData\CoChemPipeline427\private'
    # Addendum A2: the reboot-safe action creates a fresh child under this root on every start and waits up to 900 s for Docker.
    $script:queueLaunchRootR5=Join-Path $script:privateRoot 'queue-launch-r5';$script:dockerWaitSeconds=900
    $script:logonUser='AETHERDESK\ansac';$script:logonDelay='PT1M'
    $script:taskName='CoChem-4.2.7-Warden';$script:port=47824
    # The owner-writable client configuration is trusted for nothing but the token path; both values are pinned and re-checked per call.
    $script:clientConfig='C:\Users\ansac\CoChem427\pipeline-client-r3.json';$script:clientTokenFile='C:\Users\ansac\CoChem427\controller.token'
    # The two reviewed observer recorders (SYSTEM tasks that only record), matched on their pinned script paths.
    $script:observerPattern='\\SupervisorObservation4\.2\.7-windows-20261007-r3-v1\\held-supervisor-observation-r3-v1\.py"?\s+--observe\b|\\ResourceObservation4\.2\.7-windows-20261008-r3-v4\\package\\observe_resources\.py"?\s+--run-observer\b'
    # Fixed namespace dates (the r5 sitting date); -Attempt, -RetargetTarget and -RetargetAttempt select the namespaces, which
    # are never reused. The stop root is the one stop-warden-r5 namespace whichever runtime it stops.
    $script:retargetNamespaceDate='20261011';$script:stopNamespaceDate='20261011'
    $script:retargetRoot=Join-Path $script:base ('WardenRetarget4.2.7-windows-'+$script:retargetNamespaceDate+'-'+$script:RetargetTarget+'-'+$script:RetargetAttempt)
    $script:startReceiptPath=Join-Path $script:retargetRoot 'start-receipt.json'
    $script:targetRoot=Join-Path $script:base ('WardenStop4.2.7-windows-'+$script:stopNamespaceDate+'-r5-'+$script:Attempt)
    # The fresh queue directory retarget-warden-r5.ps1 -Target r4 gave the restore action of that attempt.
    $script:queueRestart=Join-Path $script:privateRoot ('queue-restart-'+$script:retargetNamespaceDate+'-r4-'+$script:RetargetAttempt)
    $script:healthSpacingSeconds=5;$script:idlePollSeconds=10;$script:exitPollSeconds=3
    $script:blockingQueueStatuses=@('IN_PROGRESS','PENDING','PENDING_RETRY')
    # 0x41306 SCHED_S_TASK_TERMINATED: what End is expected to leave in LastTaskResult; recorded, never asserted.
    $script:expectedEndResult=267014
    # Bound by Read-StartReceipt (the runtime the receipt names); nothing that needs them runs before the receipt is bound.
    $script:runtimeRoot=$null;$script:runtimePython=$null;$script:runtimeSourceRoot=$null;$script:expectedAction=$null;$script:expectedTriggers=$null
    # Also bound by Read-StartReceipt: the start evidence kind, the attempt's registered (warden-task-after.xml) and, for a
    # completed start, started (warden-task-started.xml) task XML, and the live trigger Enabled states that evidence allows.
    $script:startBinding=$null;$script:sourceTaskXml=$null;$script:startedTaskXml=$null;$script:allowedTriggerEnabled=@()
    # GET /health and GET /operator (ControlClient issues GET when data is None); single-quoted Python only. Each call refuses
    # (exit 3) unless the client configuration names exactly the pinned port and token file, and connects to the pinned port.
    $prefix=@(
        'import json,sys',
        'from pathlib import Path',
        'from cochem_pipeline.service import ControlClient',
        'port=int(sys.argv[3])',
        'config=json.loads(Path(sys.argv[1]).read_text(encoding=''utf-8-sig''))',
        'if not isinstance(config,dict) or type(config.get(''port'')) is not int or config.get(''port'')!=port or config.get(''token_file'')!=sys.argv[2]:',
        '    sys.exit(3)',
        'client=ControlClient(port,sys.argv[2])')
    $script:healthCall=(@($prefix)+@('print(json.dumps(client.call(''/health''),ensure_ascii=True))')) -join "`n"
    $script:operatorCall=(@($prefix)+@(
        'value=client.call(''/operator'')',
        'queue=value.get(''queue'') if isinstance(value,dict) else None',
        'window=value.get(''window'') if isinstance(value,dict) else None',
        'rows=[{key:row.get(key) for key in (''job_id'',''workflow_id'',''kind'',''status'')} if isinstance(row,dict) else row for row in queue] if isinstance(queue,list) else queue',
        'view={key:window.get(key) for key in (''job_limit'',''jobs_total'',''jobs_truncated'')} if isinstance(window,dict) else window',
        'print(json.dumps({''schema'':''cochem-operator-queue-extract/2'',''queue'':rows,''window'':view},ensure_ascii=True))')) -join "`n"
}

function Get-R5ExpectedArguments {
    param([string]$ConfigPath)
    # The reboot-safe r5 daemon action (addendum A2).
    '-I -B -m cochem_pipeline daemon --config "'+$ConfigPath+'" --queue-launch-output-root "'+$script:queueLaunchRootR5+'" --docker-wait-seconds '+$script:dockerWaitSeconds
}

function Get-TaskXmlSha256 {
    param([string]$Xml)
    # sha256 (lowercase hex) of the UTF-8 bytes, without BOM, of the exact RegisteredTask.Xml string; no normalization.
    # Write-RegistrationControl stores the same bytes, so the captured file hashes to the same value.
    $sha=[Security.Cryptography.SHA256]::Create()
    try{[BitConverter]::ToString($sha.ComputeHash([Text.UTF8Encoding]::new($false).GetBytes($Xml))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
}

function Assert-ApplyIdentity {
    param([bool]$ApplyRequested,[bool]$Admin,[string]$Name)
    if($ApplyRequested -and (-not $Admin -or $Name -cne 'AETHERDESK\ansac')){throw '-Apply requires the owner in Administrator Windows PowerShell; nothing was changed.'}
}

function Get-FieldValue {
    param($Object,[string]$Name)
    # One JSON field read without guessing: $null when the object is not a JSON object or lacks the field.
    if($null -eq $Object -or $Object -isnot [Management.Automation.PSCustomObject]){return $null}
    $property=$Object.PSObject.Properties[$Name]
    if($null -eq $property){return $null}
    ,$property.Value
}

function Get-StringField {
    param($Object,[string]$Name)
    # A JSON string field; anything else (absent, null, number, list, object) reads as $null.
    $value=Get-FieldValue $Object $Name
    if($value -is [string]){return [string]$value}
    $null
}

function Get-JsonListField {
    param($Object,[string]$Name)
    # A JSON list read without guessing: valid only when the field is present and is a JSON array.
    if($null -eq $Object -or $Object -isnot [Management.Automation.PSCustomObject]){return [pscustomobject]@{valid=$false;items=@()}}
    $property=$Object.PSObject.Properties[$Name]
    if($null -eq $property -or $null -eq $property.Value -or $property.Value -isnot [Array]){return [pscustomobject]@{valid=$false;items=@()}}
    [pscustomobject]@{valid=$true;items=@($property.Value)}
}

function Get-JobIdText {
    param($Item)
    if($Item -is [Management.Automation.PSCustomObject] -and $null -ne $Item.PSObject.Properties['job_id'] -and $null -ne $Item.PSObject.Properties['job_id'].Value){return [string]$Item.PSObject.Properties['job_id'].Value}
    $null
}

function Test-RepairList {
    param($Items)
    # A reviewed repair list in the form retarget-warden-r5.ps1 admits: a non-empty list of unique package source paths that
    # includes src/cochem_pipeline/__main__.py, which carries the reboot-safe daemon options the r5 action uses. The C-F4 pins
    # (Assert-R5InstalledBindings) then require exactly the 13 repairs of the reviewed freeze, as the cutover does.
    $list=@($Items);$seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    if($list.Count -lt 1){return $false}
    foreach($item in $list){if($item -isnot [string] -or $item -cnotmatch '^src/cochem_(pipeline|supervisor)/[A-Za-z0-9_]+(/[A-Za-z0-9_]+)*\.py\z' -or -not $seen.Add($item)){return $false}}
    $seen.Contains('src/cochem_pipeline/__main__.py')
}

function Test-SameStringSet {
    param($Left,$Right)
    # Ordinal set equality of two lists of unique strings; a duplicate or a non-string on either side is a difference.
    $a=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal);foreach($item in @($Left)){if($item -isnot [string] -or -not $a.Add($item)){return $false}}
    $b=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal);foreach($item in @($Right)){if($item -isnot [string] -or -not $b.Add($item)){return $false}}
    $a.SetEquals($b)
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

function Assert-ClientConfig {
    # Verifier finding (client-config port): the idle proof trusts this owner-writable file for nothing but the token path.
    # It must name exactly port 47824 and the pinned token file; every controller call re-checks both and connects to 47824.
    $item=Get-Item -LiteralPath $script:clientConfig -Force
    if($item.PSIsContainer -or $item.Length -gt 65536){throw 'The client configuration is not a small file.'}
    $raw=[IO.File]::ReadAllBytes($script:clientConfig)
    $config=$null;try{$config=([Text.UTF8Encoding]::new($false,$true).GetString($raw).TrimStart([char]0xFEFF))|ConvertFrom-Json}catch{throw 'The client configuration is not UTF-8 JSON.'}
    if($null -eq $config -or $config -isnot [Management.Automation.PSCustomObject]){throw 'The client configuration is not a JSON object.'}
    if(-not (Test-ExactInt (Get-FieldValue $config 'port') $script:port)){throw ('The client configuration does not name the controller port '+$script:port+'.')}
    if((Get-StringField $config 'token_file') -cne $script:clientTokenFile){throw 'The client configuration does not name the pinned controller token file.'}
    $sha=[Security.Cryptography.SHA256]::Create()
    try{$digest=[BitConverter]::ToString($sha.ComputeHash($raw)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
    [ordered]@{path=$script:clientConfig;sha256=$digest;port=$script:port;token_file=$script:clientTokenFile}
}

function Read-BoundJson {
    param([string]$Path,[string]$What,[string]$Pin='')
    # One bounded JSON control file behind a deny-write handle, digest-bound when a pin is given; anything but a JSON object is refused.
    if(-not (Test-Path -LiteralPath $Path -PathType Leaf)){throw ('The '+$What+' is missing: '+$Path)}
    $control=Read-R3Control $Path $Pin 1048576
    $value=$null;try{$value=(Read-R3Text $control)|ConvertFrom-Json}catch{$value=$null}
    if($null -eq $value -or $value -isnot [Management.Automation.PSCustomObject]){throw ('The '+$What+' is not a JSON object.')}
    [pscustomobject]@{path=$Path;sha256=$control.Sha256;value=$value}
}

function Assert-AttemptReceiptHead {
    param($Receipt,[string]$What)
    # The New-ReceiptHead fields retarget-warden-r5.ps1 writes into both receipts of one attempt (its retarget receipt and its
    # start receipt): the attempt and task, the runtime root, the configuration, the installation receipt, the action and the
    # trigger set. Returns them in one fixed form.
    $target=$script:RetargetTarget;$field=@{}
    foreach($name in @('attempt','task_name','runtime_root','config_path','config_sha256','install_after_path','install_after_sha256')){$field[$name]=Get-StringField $Receipt $name}
    if($field['attempt'] -cne $script:RetargetAttempt -or $field['task_name'] -cne $script:taskName){throw ('The '+$What+' does not name this -RetargetAttempt and the CoChem-4.2.7-Warden task.')}
    $action=Get-FieldValue $Receipt 'action'
    $execute=Get-StringField $action 'execute';$arguments=Get-StringField $action 'arguments';$workingDirectory=Get-StringField $action 'working_directory'
    $triggers=Get-JsonListField $Receipt 'triggers';$root=$field['runtime_root']
    if($target -ceq 'r4'){
        # The r4 restore (retarget-warden-r5.ps1 New-TargetContext 'r4'): the r4 root, its commissioned pipeline.json, no
        # installation receipt of its own, no trigger, and the fresh queue-restart directory of this retarget attempt.
        if($root -cne $script:r4Root){throw ('The '+$What+' does not name the r4 runtime root.')}
        if($field['config_path'] -cne $script:r4RestoreConfig -or $field['config_sha256'] -cne $script:configPin){throw ('The '+$What+' configuration is not the commissioned pipeline.json of the r4 root.')}
        foreach($name in @('install_after_path','install_after_sha256')){
            $property=$Receipt.PSObject.Properties[$name]
            if($null -eq $property -or $null -ne $property.Value){throw ('The r4 '+$What+' must record '+$name+' as null.')}}
        if($execute -cne $script:r4Python -or $workingDirectory -cne $script:r4Root -or $arguments -cne (Get-ExpectedArguments $script:r4RestoreConfig $script:queueRestart)){
            throw ('The '+$What+' action is not the reviewed r4 restore action of this retarget attempt.')}
        if(-not $triggers.valid -or $triggers.items.Count -ne 0){throw ('The r4 '+$What+' must record an empty trigger list.')}
        $list=@()
    }else{
        if($null -eq $root -or $root -cnotmatch $script:r5RootPattern){throw ('The '+$What+' does not name an r5 runtime root.')}
        if($null -eq $field['config_path'] -or $field['config_path'] -cnotmatch $script:r5ConfigPattern -or $null -eq $field['config_sha256'] -or $field['config_sha256'] -cnotmatch '^[a-f0-9]{64}\z'){
            throw ('The '+$What+' configuration is not a reviewed protected r5 configuration with a lowercase sha256.')}
        # The Gemini-held fallback may name the commissioned WardenCommissioning copy, and then only with the commissioned bytes.
        if($field['config_path'] -ceq $script:commissioningConfig -and $field['config_sha256'] -cne $script:configPin){
            throw ('The '+$What+' names the commissioned configuration with a sha256 other than the commissioned one.')}
        if($field['install_after_path'] -cne (Join-Path $root 'install-after.json') -or $null -eq $field['install_after_sha256'] -or $field['install_after_sha256'] -cnotmatch '^[a-f0-9]{64}\z'){
            throw ('The '+$What+' does not bind the installation receipt of its own r5 runtime root.')}
        if($execute -cne (Join-Path $root '.venv\Scripts\python.exe') -or $workingDirectory -cne $root -or $arguments -cne (Get-R5ExpectedArguments $field['config_path'])){
            throw ('The '+$What+' action is not the reviewed r5 daemon action for its own runtime root and configuration.')}
        if(-not $triggers.valid -or $triggers.items.Count -ne 1){throw ('The '+$What+' does not record exactly one trigger.')}
        $trigger=$triggers.items[0];$type=Get-StringField $trigger 'type';$user=Get-StringField $trigger 'user_id';$delay=Get-StringField $trigger 'delay'
        if($type -cne 'logon' -or $null -eq $user -or -not [string]::Equals($user,$script:logonUser,[StringComparison]::OrdinalIgnoreCase) -or $delay -cne $script:logonDelay){
            throw ('The '+$What+' trigger is not the reviewed logon trigger for AETHERDESK\ansac with a PT1M delay.')}
        $list=@([ordered]@{type=$type;user_id=$user;delay=$delay})
    }
    [ordered]@{runtime_root=$root;config_path=$field['config_path'];config_sha256=$field['config_sha256'];install_after_path=$field['install_after_path'];
        install_after_sha256=$field['install_after_sha256'];action=[ordered]@{execute=$execute;arguments=$arguments;working_directory=$workingDirectory};triggers=$list}
}

function Get-TaskXmlTriggerFlags {
    param([string]$Xml)
    # The Enabled flag of every trigger of a task XML, in document order; an absent Enabled element is Task Scheduler's default, true.
    $document=[xml]$Xml
    foreach($triggers in @($document.DocumentElement.ChildNodes|Where-Object {$_.LocalName -ceq 'Triggers'})){
        foreach($trigger in @($triggers.ChildNodes|Where-Object {$_ -is [Xml.XmlElement]})){
            $flag=@($trigger.ChildNodes|Where-Object {$_.LocalName -ceq 'Enabled'})
            if($flag.Count -eq 0){$true;continue}
            switch -CaseSensitive ([string]$flag[0].InnerText){'true'{$true}'false'{$false}default{throw 'A task XML trigger Enabled flag is neither true nor false.'}}}}
}

function Get-TaskXmlOutsideEnabledFlags {
    param([string]$Xml)
    # Get-TaskXmlOutsideEnabled that also removes the Enabled element of every trigger: the flags a start writes (the task enabled
    # before Run) and the two-phase r5 start writes (the logon trigger enabled after the health gate). All else stays byte-equal.
    $document=[xml]$Xml;$root=$document.DocumentElement
    foreach($settings in @($root.ChildNodes|Where-Object {$_.LocalName -ceq 'Settings'})){
        foreach($child in @($settings.ChildNodes)){if($child.LocalName -ceq 'Enabled'){$null=$settings.RemoveChild($child)}}}
    foreach($triggers in @($root.ChildNodes|Where-Object {$_.LocalName -ceq 'Triggers'})){
        foreach($trigger in @($triggers.ChildNodes|Where-Object {$_ -is [Xml.XmlElement]})){
            foreach($child in @($trigger.ChildNodes)){if($child.LocalName -ceq 'Enabled'){$null=$trigger.RemoveChild($child)}}}}
    $root.OuterXml
}

function Read-StartReceipt {
    # Binds the start of -RetargetAttempt that retarget-warden-r5.ps1 -Target <RetargetTarget> recorded: the action and trigger
    # set it installed, its runtime root and configuration (from its retarget receipt, repeated by a completed start receipt),
    # the task XML the attempt registered (warden-task-after.xml) and, for a completed start, the XML it started
    # (warden-task-started.xml). Controller pids and instances are never bound.
    #   START_RECEIPT                 (no -RecoverInterruptedStart) start-receipt.json, no start-held.json;
    #   START_INTERRUPTED_HELD        (-RecoverInterruptedStart) start-intent.json, no start receipt, start-held.json of a hold
    #                                 after Run (held_before_run false, stop_recovery_allowed true), interrupted (the finally ran);
    #   START_HELD_AFTER_HEALTH_GATE  the same with interrupted false and health_gate_passed true (the trigger enable or the
    #                                 receipt failed after the health gate);
    #   START_HELD_BEFORE_HEALTH_GATE the same with interrupted and health_gate_passed false (the health gate timed out or failed);
    #   START_CRASHED_NO_RECORD       start-intent.json, no start receipt and no start-held.json (a host or console crash).
    # Every file except the root of trust (the start receipt, or the start intent for the three recoveries, and the held
    # record) is read digest-bound to the file that names it.
    $target=$script:RetargetTarget;$root=$script:retargetRoot;$recover=[bool]$script:RecoverInterruptedStart
    $intentPath=Join-Path $root 'start-intent.json';$heldPath=Join-Path $root 'start-held.json'
    $afterPath=Join-Path $root 'warden-task-after.xml';$startedPath=Join-Path $root 'warden-task-started.xml'
    if(Test-Path -LiteralPath (Join-Path $root 'retarget-held.json')){throw ('The retarget attempt '+$target+' '+$script:RetargetAttempt+' holds retarget-held.json; it needs a reviewed recovery, not a stop bound to it.')}
    $start=$null;$held=$null;$intentPin='';$kind=$null;$heldTrigger=$null
    if(-not $recover){
        if(Test-Path -LiteralPath $heldPath){throw ('The retarget attempt '+$target+' '+$script:RetargetAttempt+' holds start-held.json; it needs a reviewed recovery, not a stop bound to it (when its stop_recovery_allowed is true, bind it with -RecoverInterruptedStart).')}
        if(-not (Test-Path -LiteralPath $script:startReceiptPath -PathType Leaf)){
            $hint='';if(Test-Path -LiteralPath $intentPath){$hint=' The attempt holds start-intent.json without a start receipt: an interrupted or crashed start, which -RecoverInterruptedStart binds.'}
            throw ('The '+$target+' start receipt is missing: '+$script:startReceiptPath+'.'+$hint)}
        $start=Read-BoundJson $script:startReceiptPath ($target+' start receipt')
        $status=$(if($target -ceq 'r4'){'WARDEN_R4_RESTARTED_HEALTH_VERIFIED'}else{'WARDEN_R5_RUNNING_HEALTH_VERIFIED'})
        if((Get-StringField $start.value 'schema') -cne 'cochem-warden-start/3' -or (Get-StringField $start.value 'status') -cne $status -or (Get-StringField $start.value 'target') -cne $target){
            throw ('The start receipt is not a successful '+$target+' start (cochem-warden-start/3, '+$status+', target '+$target+').')}
        $head=Assert-AttemptReceiptHead $start.value 'start receipt'
        foreach($name in @('retarget_receipt_sha256','intent_sha256','task_xml_sha256')){
            if((Get-StringField $start.value $name) -cnotmatch '^[a-f0-9]{64}\z'){throw ('The start receipt does not record '+$name+' as a lowercase sha256.')}}
        if((Get-StringField $start.value 'task_xml_started_sha256') -cne (Get-StringField $start.value 'task_xml_sha256')){throw 'The start receipt task_xml_started_sha256 is not its task_xml_sha256.'}
        $startBefore=Get-FieldValue $start.value 'trigger_enabled_before';$startAfter=Get-FieldValue $start.value 'trigger_enabled_after'
        if(($target -ceq 'r5' -and (-not (Test-ExactBool $startBefore $false) -or -not (Test-ExactBool $startAfter $true))) -or ($target -ceq 'r4' -and ($null -ne $startBefore -or $null -ne $startAfter))){
            throw ('The start receipt does not record the two-phase start (trigger_enabled_before '+$(if($target -ceq 'r5'){'false, trigger_enabled_after true'}else{'and trigger_enabled_after null'})+').')}
        $intentPin=Get-StringField $start.value 'intent_sha256';$kind='START_RECEIPT'
    }else{
        if(Test-Path -LiteralPath $script:startReceiptPath){throw ('The '+$target+' attempt '+$script:RetargetAttempt+' holds a start receipt: the start completed, so bind it without -RecoverInterruptedStart.')}
        if(-not (Test-Path -LiteralPath $intentPath -PathType Leaf)){throw ('The '+$target+' attempt '+$script:RetargetAttempt+' has no start-intent.json: no start was requested, so there is no interrupted start to recover.')}
        if(Test-Path -LiteralPath $heldPath){
            $held=Read-BoundJson $heldPath ($target+' start-held record');$value=$held.value
            $interrupted=Get-FieldValue $value 'interrupted';$passed=Get-FieldValue $value 'health_gate_passed'
            $beforeRun=Get-FieldValue $value 'held_before_run';$allowed=Get-FieldValue $value 'stop_recovery_allowed'
            if((Get-StringField $value 'schema') -cne 'cochem-warden-start-held/3' -or (Get-StringField $value 'target') -cne $target -or (Get-StringField $value 'attempt') -cne $script:RetargetAttempt -or
               (Get-StringField $value 'task_name') -cne $script:taskName -or -not (Test-ExactBool (Get-FieldValue $value 'receipt_written') $false)){
                throw 'The start-held record is not a held start of this -RetargetAttempt and the CoChem-4.2.7-Warden task without a start receipt.'}
            # Re-audit R-F1: retarget-warden-r5.ps1 writes stop_recovery_allowed = (not held_before_run) or interrupted, so every
            # hold after Run is stop-recoverable (whether or not its health gate passed); a hold before Run (Run never called, or
            # Run threw without an instance) cannot have left an instance and takes the retarget's no-stop path instead.
            if($interrupted -isnot [bool] -or $passed -isnot [bool] -or $beforeRun -isnot [bool] -or $allowed -isnot [bool]){
                throw 'The start-held record does not allow a stop recovery (interrupted, health_gate_passed, held_before_run and stop_recovery_allowed must be booleans); preserve it for review.'}
            if($beforeRun){throw 'The start-held record shows a start held before Run (held_before_run): no instance can be running, so no stop is bound; the retarget binds it as a never-started source.'}
            if(-not $allowed -or $allowed -ne ((-not $beforeRun) -or $interrupted)){
                throw 'The start-held record does not allow a stop recovery (stop_recovery_allowed must be true for a hold after Run); preserve it for review.'}
            $heldTrigger=Get-FieldValue $value 'trigger_enabled_after'
            if($null -ne $heldTrigger -and ($heldTrigger -isnot [bool] -or $target -ceq 'r4')){throw 'The start-held record trigger_enabled_after is neither the r5 logon trigger state nor null.'}
            $kind=$(if($interrupted){'START_INTERRUPTED_HELD'}elseif($passed){'START_HELD_AFTER_HEALTH_GATE'}else{'START_HELD_BEFORE_HEALTH_GATE'})
        }else{$kind='START_CRASHED_NO_RECORD'}
    }
    $intent=Read-BoundJson $intentPath ($target+' start intent') $intentPin;$intentValue=$intent.value
    if((Get-StringField $intentValue 'schema') -cne 'cochem-warden-start-intent/3' -or (Get-StringField $intentValue 'target') -cne $target -or
       (Get-StringField $intentValue 'attempt') -cne $script:RetargetAttempt -or (Get-StringField $intentValue 'task_name') -cne $script:taskName -or
       (Get-StringField $intentValue 'retarget_receipt_sha256') -cnotmatch '^[a-f0-9]{64}\z'){
        throw 'The start intent is not a start request of this -RetargetAttempt and the CoChem-4.2.7-Warden task naming its retarget receipt.'}
    if($null -ne $start -and (Get-StringField $intentValue 'retarget_receipt_sha256') -cne (Get-StringField $start.value 'retarget_receipt_sha256')){throw 'The start receipt and its start intent name different retarget receipts.'}
    $retarget=Read-BoundJson (Join-Path $root 'retarget-receipt.json') ($target+' retarget receipt') (Get-StringField $intentValue 'retarget_receipt_sha256');$retargetValue=$retarget.value
    $retargetStatus=$(if($target -ceq 'r4'){'WARDEN_RETARGETED_TO_R4_NOT_STARTED'}else{'WARDEN_RETARGETED_TO_R5_NOT_STARTED'})
    if((Get-StringField $retargetValue 'schema') -cne 'cochem-warden-retarget/3' -or (Get-StringField $retargetValue 'status') -cne $retargetStatus -or
       (Get-StringField $retargetValue 'target') -cne $target -or -not (Test-ExactBool (Get-FieldValue $retargetValue 'enabled_after') $false) -or
       (Get-StringField $retargetValue 'task_xml_after_sha256') -cnotmatch '^[a-f0-9]{64}\z' -or
       (Get-StringField $retargetValue 'task_xml_sha256') -cne (Get-StringField $retargetValue 'task_xml_after_sha256')){
        throw ('The retarget receipt is not a successful '+$target+' retarget registered disabled (cochem-warden-retarget/3, '+$retargetStatus+', enabled_after false, task_xml_sha256 = task_xml_after_sha256).')}
    $retargetTrigger=Get-FieldValue $retargetValue 'trigger_enabled_after'
    if(($target -ceq 'r5' -and -not (Test-ExactBool $retargetTrigger $false)) -or ($target -ceq 'r4' -and $null -ne $retargetTrigger)){
        throw ('The retarget receipt does not record the two-phase registration (trigger_enabled_after '+$(if($target -ceq 'r5'){'false'}else{'null'})+').')}
    $retargetHead=Assert-AttemptReceiptHead $retargetValue 'retarget receipt'
    if($null -eq $start){$head=$retargetHead}
    elseif(($head|ConvertTo-Json -Depth 6 -Compress) -cne ($retargetHead|ConvertTo-Json -Depth 6 -Compress)){
        throw 'The start receipt does not repeat its retarget receipt (runtime, configuration, installation receipt, action and triggers); preserve both for review.'}
    if((Get-StringField $intentValue 'runtime_root') -cne $head.runtime_root){throw 'The start intent does not name the runtime root of its retarget receipt.'}
    # C-F5: the task XML this attempt registered; its Description names the attempt, and the r5 logon trigger is registered disabled.
    if(-not (Test-Path -LiteralPath $afterPath -PathType Leaf)){throw ('The task XML the '+$target+' retarget attempt registered is missing: '+$afterPath)}
    $afterControl=Read-R3Control $afterPath (Get-StringField $retargetValue 'task_xml_after_sha256') 1048576;$sourceXml=Read-R3Text $afterControl
    $description=$null;$flags=$null
    try{
        foreach($info in @(([xml]$sourceXml).DocumentElement.ChildNodes|Where-Object {$_.LocalName -ceq 'RegistrationInfo'})){
            foreach($node in @($info.ChildNodes|Where-Object {$_.LocalName -ceq 'Description'})){$description=[string]$node.InnerText}}
        $flags=(@(Get-TaskXmlTriggerFlags $sourceXml)|ForEach-Object {[string]$_}) -join ','
    }catch{throw ('The task XML the '+$target+' retarget attempt registered cannot be read: '+$_.Exception.Message)}
    if($null -eq $description -or $description -cnotmatch ('(?<![0-9A-Za-z])'+[regex]::Escape($script:RetargetAttempt)+'(?![0-9A-Za-z])')){
        throw ('The task XML the '+$target+' retarget attempt '+$script:RetargetAttempt+' registered does not name that attempt in its Description.')}
    if($flags -cne $(if($target -ceq 'r5'){'False'}else{''})){throw ('The task XML the '+$target+' retarget attempt registered does not carry '+$(if($target -ceq 'r5'){'exactly one disabled logon trigger (two-phase start)'}else{'no trigger'})+'.')}
    $startedXml=$null;$startedSha=$null
    if($null -ne $start){
        # C-F5 for a completed start: the task XML it started (r5: after the trigger enable), digest-bound to the start receipt.
        if(-not (Test-Path -LiteralPath $startedPath -PathType Leaf)){throw ('The task XML the '+$target+' start recorded is missing: '+$startedPath)}
        $startedControl=Read-R3Control $startedPath (Get-StringField $start.value 'task_xml_sha256') 1048576;$startedXml=Read-R3Text $startedControl;$startedSha=$startedControl.Sha256
        $startedFlags=$null;$startedOutside=$null;$sourceOutside=$null
        try{$startedFlags=(@(Get-TaskXmlTriggerFlags $startedXml)|ForEach-Object {[string]$_}) -join ',';$startedOutside=Get-TaskXmlOutsideEnabledFlags $startedXml;$sourceOutside=Get-TaskXmlOutsideEnabledFlags $sourceXml}
        catch{throw ('The task XML the '+$target+' start recorded cannot be read: '+$_.Exception.Message)}
        if($startedFlags -cne $(if($target -ceq 'r5'){'True'}else{''}) -or $startedOutside -cne $sourceOutside){
            throw 'The task XML the start recorded is not the registered task XML with only its Enabled flags changed (r5: the logon trigger enabled); preserve both for review.'}
    }
    $allowed=@()
    if($target -ceq 'r5'){
        if($kind -ceq 'START_RECEIPT'){$allowed=@($true)}elseif($heldTrigger -is [bool]){$allowed=@([bool]$heldTrigger)}else{$allowed=@($true,$false)}}
    $script:runtimeRoot=$head.runtime_root;$script:runtimePython=$head.action.execute;$script:runtimeSourceRoot=Join-Path $head.runtime_root '.venv\Lib'
    $script:expectedAction=$head.action;$script:expectedTriggers=@($head.triggers)
    $script:startBinding=$kind;$script:sourceTaskXml=$sourceXml;$script:startedTaskXml=$startedXml;$script:allowedTriggerEnabled=$allowed
    $evidence=$(if($null -ne $start){$start.value}else{$retargetValue})
    [ordered]@{binding=$kind;path=$(if($null -ne $start){$start.path}else{$null});sha256=$(if($null -ne $start){$start.sha256}else{$null});
        schema=(Get-StringField $evidence 'schema');status=(Get-StringField $evidence 'status');target=$target;attempt=$script:RetargetAttempt;task_name=$script:taskName;
        runtime_root=$head.runtime_root;config_path=$head.config_path;config_sha256=$head.config_sha256;install_after_path=$head.install_after_path;install_after_sha256=$head.install_after_sha256;
        action=$script:expectedAction;triggers=$script:expectedTriggers;task_xml_sha256=$startedSha;source_state=(Get-FieldValue $evidence 'source_state');
        source_attempt=(Get-FieldValue $evidence 'source_attempt');stop_attempt=(Get-FieldValue $evidence 'stop_attempt');controller_bound=$false;
        retarget_receipt_path=$retarget.path;retarget_receipt_sha256=$retarget.sha256;start_intent_path=$intent.path;start_intent_sha256=$intent.sha256;
        start_held_path=$(if($null -ne $held){$held.path}else{$null});start_held_sha256=$(if($null -ne $held){$held.sha256}else{$null});held_trigger_enabled_after=$heldTrigger;
        source_task_xml_after_path=$afterPath;source_task_xml_after_sha256=$afterControl.Sha256;source_task_xml_started_path=$(if($null -ne $start){$startedPath}else{$null});
        source_task_xml_started_sha256=$startedSha;trigger_enabled_allowed=$allowed}
}

function Assert-R5InstalledBindings {
    param($Receipt)
    # Assert-R4InstalledBindings re-based on r5. The install receipt cannot be pre-pinned, so it is bound by content: the sha
    # the bound receipt names, the pinned r4 lineage, the reviewed repair list (each digest re-verified in the frozen source,
    # the installed package and the frozen manifest) and every file the task action runs or reads. C-F4: the reviewed freeze
    # itself is pinned (manifest, 13 repair digests, pyvenv.cfg and venv launcher), the installation must prove the repairs
    # installed with 153 files unchanged, and a root that holds install-held.json is refused, as retarget-warden-r5.ps1 does.
    $root=[string]$Receipt.runtime_root
    if(Test-Path -LiteralPath (Join-Path $root 'install-held.json')){throw 'The r5 runtime root holds install-held.json: its installation was held; preserve it for review.'}
    $afterControl=Read-R3Control ([string]$Receipt.install_after_path) ([string]$Receipt.install_after_sha256) 1048576
    if($afterControl.Sha256 -cne [string]$Receipt.install_after_sha256){throw 'The r5 installation receipt is not the one the start receipt names.'}
    $after=$null;try{$after=(Read-R3Text $afterControl)|ConvertFrom-Json}catch{$after=$null}
    if($null -eq $after -or $after -isnot [Management.Automation.PSCustomObject]){throw 'The r5 installation receipt is not a JSON object.'}
    $verification=Get-FieldValue $after 'verification';$revision=Get-FieldValue $verification 'revision';$holds=Get-JsonListField $after 'holds'
    $manifestPin=Get-StringField $after 'source_manifest_sha256';$revisionPin=Get-StringField $revision 'source_sha256'
    if((Get-StringField $after 'schema') -cne 'cochem-stopped-runtime-update/1' -or (Get-StringField $after 'mode') -cne 'FRESH_STOPPED_RUNTIME_READY' -or
       (Get-StringField $after 'target_root') -cne $root -or (Get-StringField $after 'previous_runtime_root') -cne $script:r4Root -or
       (Get-StringField $after 'previous_install_receipt_sha256') -cne $script:r4InstallPin -or (Get-StringField $after 'previous_source_manifest_sha256') -cne $script:r4ManifestPin -or
       $null -eq $manifestPin -or $manifestPin -cnotmatch '^[a-f0-9]{64}\z' -or $manifestPin -ceq $script:r4ManifestPin -or
       (Get-StringField $after 'configuration_sha256') -cne $script:configPin -or -not (Test-ExactBool (Get-FieldValue $after 'configuration_unchanged') $true) -or
       -not (Test-ExactInt (Get-FieldValue $after 'source_files') $script:r5SourceFiles) -or -not $holds.valid -or $holds.items.Count -ne 0 -or
       -not (Test-ExactInt (Get-FieldValue $after 'tasks_changed') 0) -or -not (Test-ExactBool (Get-FieldValue $after 'pipeline_started') $false) -or
       -not (Test-ExactBool (Get-FieldValue $after 'credentials_modified') $false) -or -not (Test-ExactBool (Get-FieldValue $after 'databases_modified') $false) -or
       -not (Test-ExactBool (Get-FieldValue $after 'ram_modified') $false) -or -not (Test-ExactBool (Get-FieldValue $verification 'configuration_parsed') $true) -or
       -not (Test-ExactBool (Get-FieldValue $verification 'no_system_or_model_execution') $true) -or (Get-StringField $verification 'ram_workspace_root') -cne 'R:\CoChem427-windows-20261007' -or
       (Get-StringField $revision 'schema') -cne 'cochem-installed-revision/1' -or -not (Test-ExactBool (Get-FieldValue $revision 'verified') $true) -or
       -not (Test-ExactBool (Get-FieldValue $revision 'read_only') $true) -or -not (((Get-FieldValue $revision 'files') -is [int] -or (Get-FieldValue $revision 'files') -is [long]) -and [long](Get-FieldValue $revision 'files') -ge 1) -or
       -not (Test-ExactInt (Get-FieldValue $revision 'acceptance_files') 0) -or $null -eq $revisionPin -or $revisionPin -cnotmatch '^[a-f0-9]{64}\z' -or
       $revisionPin -ceq $script:r3RevisionPin -or $revisionPin -ceq $script:r4RevisionPin){
        throw 'The r5 installation receipt is not the reviewed successful stopped-runtime build on the r4 lineage.'}
    if($manifestPin -cne $script:r5ManifestPin){throw ('The r5 installation receipt does not name the reviewed freeze manifest '+$script:r5ManifestPin+'.')}
    if(-not (Test-ExactBool (Get-FieldValue $after 'installed_repairs_verified') $true) -or -not (Test-ExactBool (Get-FieldValue $verification 'r5_repairs_installed') $true) -or
       -not (Test-ExactInt (Get-FieldValue $after 'verified_unchanged') $script:r5VerifiedUnchanged)){
        throw ('The r5 installation receipt does not prove the reviewed repairs installed (installed_repairs_verified, verification.r5_repairs_installed, verified_unchanged '+$script:r5VerifiedUnchanged+').')}
    $bindings=Get-FieldValue $after 'runtime_bindings'
    $pyvenvPin=Get-StringField $bindings 'pyvenv_sha256';$venvPythonPin=Get-StringField $bindings 'venv_python_sha256'
    # An empty pin would make Read-R3Control hash whatever is there; every digest handed to it must be the reviewed sha256.
    if($null -eq $pyvenvPin -or $pyvenvPin -cnotmatch '^[a-f0-9]{64}\z' -or $null -eq $venvPythonPin -or $venvPythonPin -cnotmatch '^[a-f0-9]{64}\z' -or
       $pyvenvPin -cne $script:r5PyvenvPin -or $venvPythonPin -cne $script:r5VenvPythonPin -or
       (Get-StringField $bindings 'base_python_sha256') -cne $script:probePythonPin -or (Get-StringField $bindings 'base_root') -cne $script:basePythonRoot){throw 'r5 runtime binding receipt differs.'}
    $repairList=Get-JsonListField $after 'reviewed_repairs'
    if(-not $repairList.valid -or -not (Test-RepairList $repairList.items)){throw 'The r5 reviewed repairs are not a unique list of package source paths that includes src/cochem_pipeline/__main__.py.'}
    $repairs=[string[]]@($repairList.items);[Array]::Sort($repairs,[StringComparer]::Ordinal)
    $map=Get-FieldValue $after 'reviewed_repairs_sha256'
    if($null -eq $map -or $map -isnot [Management.Automation.PSCustomObject] -or @($map.PSObject.Properties).Count -ne $repairs.Count){throw 'The r5 reviewed repair digests are not one per reviewed path.'}
    $digests=[ordered]@{}
    foreach($relative in $repairs){
        $digest=Get-StringField $map $relative
        if($null -eq $digest -or $digest -cnotmatch '^[a-f0-9]{64}\z'){throw ('The r5 reviewed repair digest is missing or malformed: '+$relative)}
        $digests[$relative]=$digest}
    if(-not (Test-SameStringSet $repairs @($script:r5RepairPins.Keys))){throw ('The r5 reviewed repairs are not the '+$script:r5RepairPins.Count+' repairs of the pinned freeze.')}
    foreach($relative in $repairs){if($digests[$relative] -cne [string]$script:r5RepairPins[$relative]){throw ('The r5 reviewed repair digest differs from the pinned freeze: '+$relative)}}
    $manifestControl=Read-R3Control (Join-Path $root 'source-manifest.json') $manifestPin
    $manifest=$null;try{$manifest=(Read-R3Text $manifestControl)|ConvertFrom-Json}catch{$manifest=$null}
    $changes=Get-FieldValue $manifest 'changes_from_previous_source';$changed=Get-JsonListField $changes 'changed';$added=Get-JsonListField $changes 'added';$removed=Get-JsonListField $changes 'removed'
    $files=Get-JsonListField $manifest 'files'
    if((Get-StringField $manifest 'schema') -cne 'cochem-stopped-runtime-source/1' -or (Get-StringField $manifest 'target_root') -cne $root -or
       -not (Test-ExactBool (Get-FieldValue $manifest 'complete_source_freeze') $true) -or -not $files.valid -or $files.items.Count -ne $script:r5SourceFiles -or
       -not $changed.valid -or -not (Test-SameStringSet $changed.items $repairs) -or ($added.valid -and $added.items.Count -ne 0) -or ($removed.valid -and $removed.items.Count -ne 0)){
        throw 'Frozen r5 manifest binding differs.'}
    $listed=[Collections.Generic.Dictionary[string,string]]::new([StringComparer]::Ordinal)
    foreach($entry in $files.items){$relative=Get-StringField $entry 'relative';$sha=Get-StringField $entry 'sha256';if($null -ne $relative -and $null -ne $sha -and -not $listed.ContainsKey($relative)){$listed[$relative]=$sha}}
    foreach($relative in $repairs){if(-not $listed.ContainsKey($relative) -or $listed[$relative] -cne $digests[$relative]){throw ('The frozen r5 manifest does not list the reviewed digest of '+$relative)}}
    $null=Read-R3Control (Join-Path $root 'pipeline.json') $script:configPin
    $null=Read-R3Control (Join-Path $root '.venv\pyvenv.cfg') $pyvenvPin
    $null=Read-R3Control (Join-Path $root '.venv\Scripts\python.exe') $venvPythonPin
    $null=Read-R3Control $script:basePython $script:probePythonPin
    # The installed package must carry every reviewed repair, not only the frozen source copy.
    foreach($relative in $repairs){
        $null=Read-R3Control (Join-Path $root ('source\'+$relative.Replace('/','\'))) $digests[$relative]
        $null=Read-R3Control (Join-Path $root ('.venv\Lib\site-packages\'+$relative.Substring(4).Replace('/','\'))) $digests[$relative]}
    $configControl=Read-R3Control ([string]$Receipt.config_path) ([string]$Receipt.config_sha256) 4194304
    if($configControl.Sha256 -cne [string]$Receipt.config_sha256){throw 'The task configuration is not the one the bound receipt names.'}
    [ordered]@{install_after_path=[string]$Receipt.install_after_path;install_after_sha256=$afterControl.Sha256;source_manifest_sha256=$manifestPin;revision_sha256=$revisionPin;
        previous_install_receipt_sha256=$script:r4InstallPin;reference_configuration_sha256=$script:configPin;task_config_path=[string]$Receipt.config_path;
        task_config_sha256=$configControl.Sha256;reviewed_repairs=$repairs;reviewed_repairs_sha256=$digests;
        a6_repair_set=(Test-SameStringSet $repairs $script:reviewedRepairPaths);a6_repair_set_asserted=$true;freeze_manifest_pinned=$true;
        installed_repairs_verified=$true;verified_unchanged=$script:r5VerifiedUnchanged;pyvenv_sha256=$pyvenvPin;venv_python_sha256=$venvPythonPin;install_held_record_absent=$true}
}

function Assert-TargetRuntimeBindings {
    param($Receipt)
    # The installation the bound start runs. r5: content verification of the install receipt the start receipt names.
    # r4: the reviewed v2.2 bindings plus the exact r4 install receipt and revision pins (the pins retarget-warden-r5.ps1 uses);
    # Assert-R4InstalledBindings also re-hashes the restore configuration <r4 root>\pipeline.json against the commissioned pin.
    if($script:RetargetTarget -ceq 'r4'){
        $runtime=Assert-R4Pins (Assert-R4InstalledBindings)
        return [ordered]@{runtime='r4';install_receipt_sha256=$runtime.install_receipt_sha256;source_manifest_sha256=$runtime.source_manifest_sha256;
            revision_sha256=$runtime.revision_sha256;reviewed_repair_sha256=$script:repairPin;task_config_path=$script:r4RestoreConfig;task_config_sha256=$script:configPin}}
    $bindings=Assert-R5InstalledBindings $Receipt;$bindings.runtime='r5';$bindings
}

function Get-TaskTriggerSet {
    param($Task)
    # The live triggers in the start receipt's vocabulary (TASK_TRIGGER_LOGON 9 -> logon, TASK_TRIGGER_BOOT 8 -> boot); 1-based COM collection.
    $collection=$Task.Definition.Triggers;$items=@()
    for($index=1;$index -le [int]$collection.Count;$index++){
        $trigger=$collection.Item($index);$type=[int]$trigger.Type
        $name=switch($type){9{'logon'}8{'boot'}default{'type-'+$type}}
        $items+=[pscustomobject]@{type=$name;user_id=$(if($type -eq 9){[string]$trigger.UserId}else{$null});delay=$(if($type -in @(8,9)){[string]$trigger.Delay}else{$null});enabled=[bool]$trigger.Enabled}}
    $items
}

function Get-RunningInstanceEvidence {
    param($Task,$Proof)
    # The live task instance (GUID and engine pid) next to the proven processes; recorded evidence, never asserted.
    $guid=$null;$engine=$null;$readable=$false
    try{$running=$Task.GetInstances(0);if([int]$running.Count -eq 1){$item=$running.Item(1);$guid=[string]$item.InstanceGuid;$engine=[int]$item.EnginePID;$readable=$true}}catch{$readable=$false}
    $known=@();if($null -ne $Proof){$known=@(Get-ProofProcesses $Proof|ForEach-Object {[int]$_.pid})}
    [ordered]@{readable=$readable;instance_guid=$guid;engine_pid=$engine;engine_pid_is_proven_process=$(if($null -ne $engine){$engine -in $known}else{$null});asserted=$false}
}

function Assert-StopDefinition {
    param($State)
    if($State.user -notin @('SYSTEM','S-1-5-18') -or $State.logon_type -ne 5 -or $State.run_level -ne 1 -or $State.actions -ne 1 -or
       $State.multiple_instances -ne 2 -or $State.execution_time_limit -cne 'PT0S' -or $State.restart_count -ne 0 -or $State.allow_demand_start -ne $true){
        throw 'The Warden task is not the exact reviewed SYSTEM daemon definition; preserve it for review.'}
    if($null -eq $script:expectedAction){throw 'The r5 start receipt is not bound; the live task cannot be compared.'}
    # A completed start is bound through its start receipt; an interrupted or crashed one through its attempt's retarget receipt.
    $bound=$(if($null -eq $script:startBinding -or $script:startBinding -ceq 'START_RECEIPT'){'start receipt'}else{'retarget receipt'})
    if($State.action_type -ne 0 -or $State.action_path -cne $script:expectedAction.execute -or $State.action_working_directory -cne $script:expectedAction.working_directory -or
       $State.action_arguments -cne $script:expectedAction.arguments){
        throw ('The Warden task action differs from the '+$script:RetargetTarget+' action recorded by the '+$bound+'; preserve it for review.')}
    $live=@(Get-TaskTriggerSet $State.task);$expected=@($script:expectedTriggers)
    # Re-audit R-F2: the live logon trigger user is compared by SID (Test-SameAccount, a byte-identical copy of the cutover's),
    # since Task Scheduler may read it back as the SID or another spelling of the owner; a different account still differs.
    $same=($State.triggers -eq $expected.Count) -and ($live.Count -eq $expected.Count)
    if($same){for($index=0;$index -lt $expected.Count;$index++){
        if($live[$index].type -cne $expected[$index].type -or -not (Test-SameAccount ([string]$live[$index].user_id) ([string]$expected[$index].user_id)) -or
           $live[$index].delay -cne $expected[$index].delay){$same=$false}}}
    if(-not $same){throw ('The Warden task triggers differ from the '+$script:RetargetTarget+' '+$bound+'; preserve it for review.')}
    # Two-phase r5 start: the logon trigger is registered disabled and enabled only after the health gate, so its live Enabled
    # state must be one the bound start evidence allows (a completed start: enabled).
    foreach($trigger in $live){
        if([bool]$trigger.enabled -notin @($script:allowedTriggerEnabled)){
            throw ('The Warden '+$trigger.type+' trigger is '+$(if($trigger.enabled){'enabled'}else{'disabled'})+', which the bound '+$script:RetargetTarget+' start evidence ('+$script:startBinding+') does not allow; preserve it for review.')}}
    # C-F5: the live definition is the one this attempt registered (warden-task-after.xml, whose Description names the attempt)
    # outside <Settings><Enabled> and the trigger Enabled flags, and after a completed start the one it started
    # (warden-task-started.xml) outside <Settings><Enabled>.
    if($null -eq $script:sourceTaskXml){throw 'The task XML of the retarget attempt is not bound; the live task cannot be compared.'}
    if((Get-TaskXmlOutsideEnabledFlags $State.xml) -cne (Get-TaskXmlOutsideEnabledFlags $script:sourceTaskXml)){
        throw ('The Warden task XML differs from the one the '+$script:RetargetTarget+' retarget attempt '+$script:RetargetAttempt+' registered (warden-task-after.xml) outside <Settings><Enabled> and the trigger Enabled flags; preserve it for review.')}
    if($null -ne $script:startedTaskXml -and (Get-TaskXmlOutsideEnabled $State.xml) -cne (Get-TaskXmlOutsideEnabled $script:startedTaskXml)){
        throw ('The Warden task XML differs from the one the '+$script:RetargetTarget+' start of attempt '+$script:RetargetAttempt+' recorded (warden-task-started.xml) outside <Settings><Enabled>; preserve it for review.')}
}

function Assert-StopSource {
    param($State)
    # RUNNING: enabled, one running instance. ALREADY_STOPPED: no instance (the caller still proves the port free).
    if(-not $State.readable){throw 'Warden task definition is unreadable.'}
    Assert-StopDefinition $State
    Assert-RegisteredTaskAcl $State.sddl
    if($State.enabled -eq $true -and $State.state -eq 4 -and $State.instances -eq 1){return 'RUNNING'}
    if($State.state -in @(1,3) -and $State.instances -eq 0){return 'ALREADY_STOPPED'}
    throw ('The Warden task is neither running exactly one enabled instance nor stopped (enabled '+$State.enabled+', state '+$State.state+', instances '+$State.instances+'); preserve it for review.')
}

function Get-StopMode {
    param($State)
    # Assert-StopSource, plus a disabled task with exactly one running instance: a held or interrupted start disables the task
    # again (never Ending it) while the instance it ran keeps running, and a completed start's task may be disabled the same way
    # (re-audit R-F5). That instance is stopped as RUNNING for every binding; the task stays disabled.
    if($State.readable -and $State.enabled -eq $false -and $State.state -eq 4 -and $State.instances -eq 1){
        Assert-StopDefinition $State;Assert-RegisteredTaskAcl $State.sddl;return 'RUNNING'}
    Assert-StopSource $State
}

function Get-TaskXmlOutsideEnabled {
    param([string]$Xml)
    # Variant of Get-TaskXmlOutsideAction: removes only <Settings><Enabled>, which disabling inserts or rewrites.
    $document=[xml]$Xml;$root=$document.DocumentElement
    foreach($settings in @($root.ChildNodes|Where-Object {$_.LocalName -ceq 'Settings'})){
        foreach($child in @($settings.ChildNodes)){if($child.LocalName -ceq 'Enabled'){$null=$settings.RemoveChild($child)}}}
    $root.OuterXml
}

function Assert-StopDisabledTask {
    param($State,$Before)
    if(-not $State.readable){throw 'The task could not be read back after the disable.'}
    if($State.enabled -ne $false){throw 'The task is still enabled after the disable request.'}
    if($State.instances -ne 0 -or $State.state -notin @(1,3)){throw 'The disabled task shows a running or queued instance.'}
    Assert-StopDefinition $State
    if($State.sddl -cne $Before.sddl){throw 'The task security descriptor changed during the stop.'}
    Assert-RegisteredTaskAcl $State.sddl
    if((Get-TaskXmlOutsideEnabled $Before.xml) -cne (Get-TaskXmlOutsideEnabled $State.xml)){throw 'The task XML changed outside <Settings><Enabled> during the stop.'}
}

function Get-HealthSample {
    # GET /health with the bound runtime's interpreter through the pinned port and token file (the client configuration is
    # re-checked by the call); the answer must come from SYSTEM and from that runtime's source root.
    $result=Invoke-NativeJudged $script:runtimePython @('-I','-B','-X','utf8','-c',$script:healthCall,$script:clientConfig,$script:clientTokenFile,[string]$script:port)
    if($result.code -eq 3){return [pscustomobject]@{ok=$false;error='the client configuration does not name the pinned controller port and token file';health=$null}}
    if($result.code -ne 0){return [pscustomobject]@{ok=$false;error=$result.stderr;health=$null}}
    $health=$null;try{$health=$result.stdout|ConvertFrom-Json}catch{return [pscustomobject]@{ok=$false;error='health output is not JSON';health=$null}}
    if($null -eq $health -or $health -isnot [Management.Automation.PSCustomObject]){return [pscustomobject]@{ok=$false;error='health output is not a JSON object';health=$null}}
    foreach($field in @('service_identity','source_root','pid','instance_id','process_started_at','active','quarantined_slots')){
        if($null -eq $health.PSObject.Properties[$field]){return [pscustomobject]@{ok=$false;error=('health lacks '+$field);health=$health}}}
    if($health.service_identity -cne 'SYSTEM' -or [string]$health.source_root -cne $script:runtimeSourceRoot){return [pscustomobject]@{ok=$false;error='health answered with an unexpected identity or source root';health=$health}}
    [pscustomobject]@{ok=$true;error='';health=$health}
}

function Test-IdlePredicate {
    param($First,$Second,$OperatorText)
    # Idle only when every clause holds on both samples and on the operator queue; anything unreadable holds.
    $reasons=[Collections.Generic.List[string]]::new();$jobs=[Collections.Generic.List[string]]::new()
    $samples=@($First,$Second);$uncleared=$null;$routeHolds=$null
    for($index=0;$index -lt 2;$index++){
        $sample=$samples[$index];$label='health sample '+($index+1)
        if($null -eq $sample -or $sample -isnot [Management.Automation.PSCustomObject]){$reasons.Add($label+' is unavailable or not a JSON object');continue}
        $identity=$sample.PSObject.Properties['service_identity'];$source=$sample.PSObject.Properties['source_root']
        if($null -eq $identity -or [string]$identity.Value -cne 'SYSTEM' -or $null -eq $source -or [string]$source.Value -cne $script:runtimeSourceRoot){$reasons.Add($label+' is not the SYSTEM controller from the '+$script:RetargetTarget+' root')}
        $active=Get-JsonListField $sample 'active'
        if(-not $active.valid){$reasons.Add($label+' has no active list')}
        elseif($active.items.Count){$reasons.Add($label+' reports '+$active.items.Count+' active job(s)');foreach($item in $active.items){$id=Get-JobIdText $item;if($null -ne $id){$jobs.Add($id)}}}
        $slots=$sample.PSObject.Properties['quarantined_slots']
        if($null -eq $slots -or $slots.Value -isnot [Management.Automation.PSCustomObject]){$reasons.Add($label+' has no quarantined_slots object')}
        elseif(@($slots.Value.PSObject.Properties).Count){$reasons.Add($label+' reports quarantined slot(s): '+((@($slots.Value.PSObject.Properties)|ForEach-Object {$_.Name}) -join ', '))}
        $routingProperty=$sample.PSObject.Properties['routing'];$routing=$null
        if($null -ne $routingProperty){$routing=$routingProperty.Value}
        if($null -eq $routing -or $routing -isnot [Management.Automation.PSCustomObject]){$reasons.Add($label+' has no routing object');continue}
        $reservations=Get-JsonListField $routing 'active_reservations'
        if(-not $reservations.valid){$reasons.Add($label+' has no routing.active_reservations list')}
        elseif($reservations.items.Count){$reasons.Add($label+' reports '+$reservations.items.Count+' active route reservation(s)');foreach($item in $reservations.items){$id=Get-JobIdText $item;if($null -ne $id){$jobs.Add($id)}}}
        $barriers=Get-JsonListField $routing 'execution_quarantines'
        if(-not $barriers.valid){$reasons.Add($label+' has no routing.execution_quarantines list')}
        else{
            if($barriers.items.Count){$reasons.Add($label+' reports '+$barriers.items.Count+' uncleared execution cleanup row(s)');foreach($item in $barriers.items){$id=Get-JobIdText $item;if($null -ne $id){$jobs.Add($id)}}}
            if($index -eq 1){$uncleared=$barriers.items.Count}}
        $holdList=Get-JsonListField $routing 'holds';if($index -eq 1 -and $holdList.valid){$routeHolds=$holdList.items.Count}
    }
    if($First -is [Management.Automation.PSCustomObject] -and $Second -is [Management.Automation.PSCustomObject]){
        $same=$true
        foreach($field in @('pid','instance_id','process_started_at')){
            $a=$First.PSObject.Properties[$field];$b=$Second.PSObject.Properties[$field]
            if($null -eq $a -or $null -eq $b -or $null -eq $a.Value -or [string]$a.Value -cne [string]$b.Value){$same=$false}}
        if(-not $same){$reasons.Add('controller identity changed between samples (pid, instance_id, process_started_at)')}}
    $queueRows=$null;$inProgress=$null;$statusCounts=[ordered]@{};$jobsTotal=$null;$jobsTruncated=$null
    if([string]::IsNullOrWhiteSpace([string]$OperatorText)){$reasons.Add('operator snapshot is unavailable')}
    else{
        $operator=$null;$parsed=$true
        try{$operator=$OperatorText|ConvertFrom-Json}catch{$parsed=$false}
        $queue=Get-JsonListField $operator 'queue'
        if(-not $parsed){$reasons.Add('operator snapshot is not JSON')}
        elseif(-not $queue.valid){$reasons.Add('operator snapshot has no queue list')}
        else{
            $queueRows=$queue.items.Count;$inProgress=0;$counts=@{}
            foreach($row in $queue.items){
                $status=$null
                if($row -is [Management.Automation.PSCustomObject] -and $null -ne $row.PSObject.Properties['status'] -and $row.PSObject.Properties['status'].Value -is [string]){$status=[string]$row.PSObject.Properties['status'].Value}
                if($null -eq $status){$reasons.Add('operator queue row without a status');continue}
                if($counts.ContainsKey($status)){$counts[$status]++}else{$counts[$status]=1}
                if($status -ceq 'IN_PROGRESS'){$inProgress++}
                if($status -cin $script:blockingQueueStatuses){
                    $id=Get-JobIdText $row;$reasons.Add('queue row '+$(if($null -ne $id){$id}else{'<no job_id>'})+' is '+$status);if($null -ne $id){$jobs.Add($id)}}}
            foreach($key in @($counts.Keys|Sort-Object)){$statusCounts[$key]=$counts[$key]}
            # Verifier finding (operator window): the view keeps at most 200 jobs, so only an untruncated window proves
            # that no PENDING or PENDING_RETRY row lies beyond it.
            $window=Get-FieldValue $operator 'window'
            $jobsTotal=Get-FieldValue $window 'jobs_total';$jobsTruncated=Get-FieldValue $window 'jobs_truncated'
            if(-not (Test-ExactBool $jobsTruncated $false)){$reasons.Add('operator queue window is truncated or unproven (window.jobs_truncated is not false)')}}}
    [ordered]@{idle=($reasons.Count -eq 0);reasons=@($reasons);offending_job_ids=@($jobs|Select-Object -Unique);queue_rows=$queueRows;queue_status_counts=$statusCounts;
        in_progress_rows=$inProgress;uncleared_cleanup_rows=$uncleared;routing_holds=$routeHolds;jobs_total=$jobsTotal;jobs_truncated=$jobsTruncated}
}

function Get-OperatorSnapshot {
    $result=Invoke-NativeJudged $script:runtimePython @('-I','-B','-X','utf8','-c',$script:operatorCall,$script:clientConfig,$script:clientTokenFile,[string]$script:port)
    if($result.code -eq 3){return [pscustomobject]@{ok=$false;error='the client configuration does not name the pinned controller port and token file';text=$null}}
    if($result.code -ne 0){return [pscustomobject]@{ok=$false;error=$result.stderr;text=$null}}
    [pscustomobject]@{ok=$true;error='';text=$result.stdout}
}

function Get-IdleEvidence {
    # One evaluation: /health, a pause of at least 5 s, /health again, then one GET /operator.
    $first=Get-HealthSample;$firstUtc=[DateTime]::UtcNow.ToString('o')
    Start-Sleep -Seconds $script:healthSpacingSeconds
    $second=Get-HealthSample;$secondUtc=[DateTime]::UtcNow.ToString('o')
    $operator=Get-OperatorSnapshot
    $firstHealth=$null;if($first.ok){$firstHealth=$first.health}
    $secondHealth=$null;if($second.ok){$secondHealth=$second.health}
    $operatorText=$null;if($operator.ok){$operatorText=$operator.text}
    $verdict=Test-IdlePredicate $firstHealth $secondHealth $operatorText
    $errors=@()
    if(-not $first.ok){$errors+=('health sample 1: '+$first.error)}
    if(-not $second.ok){$errors+=('health sample 2: '+$second.error)}
    if(-not $operator.ok){$errors+=('operator snapshot: '+$operator.error)}
    $controller=$null
    if($second.ok){$controller=[ordered]@{pid=$second.health.pid;instance_id=$second.health.instance_id;process_started_at=$second.health.process_started_at;source_root=$second.health.source_root}}
    [ordered]@{schema='cochem-warden-idle-evidence/1';idle=$verdict.idle;reasons=$verdict.reasons;offending_job_ids=$verdict.offending_job_ids;errors=$errors;
        queue_rows=$verdict.queue_rows;queue_status_counts=$verdict.queue_status_counts;in_progress_rows=$verdict.in_progress_rows;
        uncleared_cleanup_rows=$verdict.uncleared_cleanup_rows;routing_holds=$verdict.routing_holds;controller=$controller;spacing_seconds=$script:healthSpacingSeconds;
        samples=@([ordered]@{sampled_utc=$firstUtc;ok=$first.ok;health=$first.health},[ordered]@{sampled_utc=$secondUtc;ok=$second.ok;health=$second.health});
        operator_extract=$operator.text}
}

function Wait-WardenIdle {
    # Polls no faster than every 10 s (the controller's 5 percent CPU budget) up to IdleWaitSeconds; consumes nothing.
    # Verifier finding (slot check order): the slot-worker sweep runs only after the controller reports idle, inside the
    # poll, so a controller that is briefly busy with a live worker is polled rather than refused at once.
    $deadline=[DateTime]::UtcNow.AddSeconds($script:IdleWaitSeconds)
    $limit=[Math]::Max(1,[int][Math]::Floor($script:IdleWaitSeconds/$script:idlePollSeconds));$evaluations=0;$last=$null
    while($true){
        $evaluations++;$last=Get-IdleEvidence;$last.worker_pids=@()
        if($last.idle){
            $workers=Get-WorkerProcesses;$last.worker_pids=@($workers.workers|ForEach-Object {$_.pid})
            $workerFailure='';try{Assert-NoWorkers $workers ' after the controller reported idle'}catch{$workerFailure=$_.Exception.Message}
            if(-not $workerFailure){$last.evaluations=$evaluations;return $last}
            $last.idle=$false;$last.reasons=@($last.reasons)+@($workerFailure+$(if(@($last.worker_pids).Count){' (pids '+(@($last.worker_pids) -join ', ')+')'}else{''}))}
        if($evaluations -ge $limit -or [DateTime]::UtcNow.AddSeconds($script:idlePollSeconds) -ge $deadline){break}
        Start-Sleep -Seconds $script:idlePollSeconds
    }
    $ids=@($last.offending_job_ids)
    throw ('The Warden is not idle after '+$evaluations+' evaluation(s) within '+$script:IdleWaitSeconds+' s: '+(@($last.reasons) -join '; ')+
        $(if($ids.Count){'; offending job ids: '+($ids -join ', ')}else{''})+'. Nothing was changed; let the work finish, submit nothing during the sitting, then run again.')
}

function Get-ProcessCreationUtc {
    param($Process)
    if($null -eq $Process -or $null -eq $Process.CreationDate){return $null}
    ([DateTime]$Process.CreationDate).ToUniversalTime().ToString('o')
}

function Get-LastBootUtc {
    $system=Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    ([DateTime]$system.LastBootUpTime).ToUniversalTime().ToString('o')
}

function Get-StopProcessProof {
    param([int]$ProcessId)
    # The pid /health reports, bound to the live task action (interpreter image and daemon command line), the SYSTEM owner
    # and the listening socket, plus the launcher the task started and both creation times, so that a reused pid is never
    # mistaken for the controller later. Nothing here comes from the start receipt's controller fields.
    $controller=Get-CimInstance Win32_Process -Filter ('ProcessId = '+$ProcessId) -ErrorAction Stop
    if($null -eq $controller){throw 'The controller pid reported by /health does not exist.'}
    $image=[string]$controller.ExecutablePath;$arguments=[string]$script:expectedAction.arguments
    if($image -cne $script:basePython -and $image -cne $script:runtimePython){throw ('The controller pid does not run the '+$script:RetargetTarget+' toolchain interpreter.')}
    if(([string]$controller.CommandLine).IndexOf($arguments,[StringComparison]::Ordinal) -lt 0){throw ('The controller pid is not running the '+$script:RetargetTarget+' daemon command of the live task action.')}
    try{$listeners=@(Get-NetTCPConnection -LocalPort $script:port -State Listen -ErrorAction Stop)}
    catch{if($_.FullyQualifiedErrorId -like 'CmdletizationQuery_NotFound*'){$listeners=@()}else{throw ('The controller port owner could not be established: '+$_.Exception.Message)}}
    if($listeners.Count -eq 0){throw 'Nothing listens on the controller port.'}
    foreach($listener in $listeners){if([int]$listener.OwningProcess -ne $ProcessId){throw ('The controller port is owned by pid '+$listener.OwningProcess+', not the pid reported by /health.')}}
    $owner=$null;try{$owner=Invoke-CimMethod -InputObject $controller -MethodName GetOwner -ErrorAction Stop}catch{$owner=$null}
    if($null -eq $owner -or $owner.ReturnValue -ne 0 -or [string]$owner.User -cne 'SYSTEM'){throw 'The controller pid does not run as SYSTEM.'}
    $controllerCreation=Get-ProcessCreationUtc $controller
    if($null -eq $controllerCreation){throw 'The controller creation time could not be read.'}
    $launcher=$null
    if($image -ceq $script:basePython){
        $parent=Get-CimInstance Win32_Process -Filter ('ProcessId = '+[int]$controller.ParentProcessId) -ErrorAction Stop
        if($null -eq $parent -or -not [string]::Equals([string]$parent.ExecutablePath,$script:runtimePython,[StringComparison]::OrdinalIgnoreCase) -or
           ([string]$parent.CommandLine).IndexOf($arguments,[StringComparison]::Ordinal) -lt 0){throw ('The controller parent is not the '+$script:RetargetTarget+' venv launcher started by the task action.')}
        $launcherCreation=Get-ProcessCreationUtc $parent
        if($null -eq $launcherCreation){throw 'The launcher creation time could not be read.'}
        $launcher=[ordered]@{pid=[int]$parent.ProcessId;image=[string]$parent.ExecutablePath;creation_utc=$launcherCreation}}
    [ordered]@{controller=[ordered]@{pid=[int]$controller.ProcessId;image=$image;creation_utc=$controllerCreation;parent_pid=[int]$controller.ParentProcessId};
        launcher=$launcher;owner=[string]$owner.User;port_owner_verified=$true;last_boot_up_time=(Get-LastBootUtc)}
}

function Get-ProofProcesses {
    param($Proof)
    [ordered]@{role='controller';pid=$Proof.controller.pid;image=$Proof.controller.image;creation_utc=$Proof.controller.creation_utc}
    if($null -ne $Proof.launcher){[ordered]@{role='launcher';pid=$Proof.launcher.pid;image=$Proof.launcher.image;creation_utc=$Proof.launcher.creation_utc}}
}

function Assert-OnlyProvenController {
    param($Presence,$Proof)
    $known=@(Get-ProofProcesses $Proof|ForEach-Object {[int]$_.pid})
    $foreign=@(@($Presence.controller_processes)+@($Presence.unclassified_runtime_processes)|Where-Object {[int]$_.pid -notin $known})
    if($foreign.Count){throw ('Controller-like or unclassified runtime processes other than the proven controller are alive: '+(($foreign|ForEach-Object {[string]$_.pid}) -join ', ')+'; nothing was changed.')}
    if([bool]$Presence.authoritative -and $Presence.uninspectable_python_processes -ne 0){throw ([string]$Presence.uninspectable_python_processes+' python processes could not be inspected; nothing was changed.')}
}

function Test-ProcessInstancePresent {
    param([int]$ProcessId,[string]$CreationUtc)
    # Present only when the same pid exists with the same creation time; an unreadable creation time counts as present.
    $process=Get-CimInstance Win32_Process -Filter ('ProcessId = '+$ProcessId) -ErrorAction Stop
    if($null -eq $process){return $false}
    $creation=Get-ProcessCreationUtc $process
    if($null -eq $creation){return $true}
    $creation -ceq $CreationUtc
}

function Get-ExitObservation {
    param($Folder,$Proof)
    $reasons=[Collections.Generic.List[string]]::new()
    $state=Get-WardenTaskState $Folder
    if(-not $state.readable){$reasons.Add('the task could not be read')}
    elseif($state.instances -ne 0 -or $state.state -notin @(1,3)){$reasons.Add('the task still shows state '+$state.state+' with '+$state.instances+' instance(s)')}
    $survivors=@()
    foreach($entry in @(Get-ProofProcesses $Proof)){
        if(Test-ProcessInstancePresent ([int]$entry.pid) ([string]$entry.creation_utc)){$survivors+=[ordered]@{role=$entry.role;pid=$entry.pid;image=$entry.image;creation_utc=$entry.creation_utc}}}
    if($survivors.Count){$reasons.Add('surviving pid(s): '+(($survivors|ForEach-Object {[string]$_.pid+' ('+$_.role+')'}) -join ', '))}
    $presence=Get-ControllerPresence
    $controllers=@(@($presence.controller_processes)+@($presence.unclassified_runtime_processes))
    if($controllers.Count){$reasons.Add('controller-like or unclassified runtime process(es) alive: '+(($controllers|ForEach-Object {[string]$_.pid}) -join ', '))}
    if([bool]$presence.authoritative -and $presence.uninspectable_python_processes -ne 0){$reasons.Add([string]$presence.uninspectable_python_processes+' python process(es) could not be inspected')}
    $free=$false
    if($presence.listening -ne 0){$reasons.Add('port '+$script:port+' still has a listener')}
    else{$free=Test-LoopbackFree;if(-not $free){$reasons.Add('port '+$script:port+' cannot be bound exclusively')}}
    $workers=Get-WorkerProcesses;$workerPids=@($workers.workers|ForEach-Object {$_.pid})
    try{Assert-NoWorkers $workers ''}catch{$reasons.Add($_.Exception.Message)}
    [ordered]@{complete=($reasons.Count -eq 0);reasons=@($reasons);observed_utc=[DateTime]::UtcNow.ToString('o');task_readable=$state.readable;
        task_state=$(if($state.readable){$state.state}else{$null});running_instances=$(if($state.readable){$state.instances}else{$null});
        enabled=$(if($state.readable){$state.enabled}else{$null});last_task_result=$(if($state.readable){$state.last_task_result}else{$null});
        surviving_processes=$survivors;controller_processes=$controllers;port_listening=$presence.listening;exclusive_bind_free=$free;worker_pids=$workerPids;
        observer_processes=$presence.observer_processes}
}

function Wait-WardenExit {
    param($Folder,$Proof)
    # Observes only. A survivor is named for the owner; nothing is ever killed.
    $started=[DateTime]::UtcNow;$deadline=$started.AddSeconds($script:ExitWaitSeconds)
    $limit=[Math]::Max(1,[int][Math]::Floor($script:ExitWaitSeconds/$script:exitPollSeconds))+1;$polls=0;$last=$null;$lastError=''
    while($true){
        $polls++
        try{$last=Get-ExitObservation $Folder $Proof;$lastError=''}catch{$lastError=$_.Exception.Message}
        if($null -ne $last -and $last.complete -and -not $lastError){break}
        if($polls -ge $limit -or [DateTime]::UtcNow -ge $deadline){break}
        Start-Sleep -Seconds $script:exitPollSeconds
    }
    if($null -eq $last){$last=[ordered]@{complete=$false;reasons=@('the exit could not be observed');surviving_processes=@();controller_processes=@();port_listening=$null;exclusive_bind_free=$null;worker_pids=@()}}
    if($lastError){$last.complete=$false;$last.reasons=@($last.reasons)+@('the last observation failed: '+$lastError)}
    $last.polls=$polls;$last.elapsed_seconds=[Math]::Round(([DateTime]::UtcNow-$started).TotalSeconds,1);$last.last_error=$lastError
    $last
}

function New-StopRoot {
    # Verifier finding (root creation): the root is created outside the stop's main try, and a root that existed before this
    # run is refused and never written to. If the reviewed helper fails after creating the root, the consumed namespace gets
    # stop-held.json (phase ROOT_CREATE) and a plain message.
    if(Test-Path -LiteralPath $script:targetRoot){throw 'The stop root already exists for this attempt; preserve it and choose another -Attempt. Nothing was changed.'}
    try{New-ProtectedDirectory $script:targetRoot}catch{
        $reason=$_.Exception.Message
        if(-not (Test-Path -LiteralPath $script:targetRoot)){throw ('The stop root could not be created: '+$reason.TrimEnd('.')+'; nothing was changed.')}
        $note=''
        $heldRecord=[ordered]@{schema='cochem-warden-stop-held/2';attempt=$script:Attempt;retarget_target=$script:RetargetTarget;retarget_attempt=$script:RetargetAttempt;task_name=$script:taskName;mode=$null;phase='ROOT_CREATE';
            reason=$reason;start_binding=$script:startBinding;end_requested=$false;disable_requested=$false;root_preserved=$true;processes_killed=$false;automatic_retry_allowed=$false;requires_reviewed_recovery=$true}
        try{$null=Write-RegistrationControl (Join-Path $script:targetRoot 'stop-held.json') ($heldRecord|ConvertTo-Json -Depth 4)}catch{$note=(' The held record could not be written: '+$_.Exception.Message)}
        throw ('The stop root could not be secured: '+$reason.TrimEnd('.')+'. Nothing was ended or disabled; preserve '+$script:targetRoot+' and choose another -Attempt.'+$note)}
}

function Get-TriggerStateBasis {
    param($Binding,$Enabled)
    # Why the live logon trigger state is admitted (stop-receipt.json trigger_state_basis); the trigger-less r4 restore has none.
    if($null -eq $Enabled){return 'NO_TRIGGER'}
    if($Binding.binding -ceq 'START_RECEIPT'){return 'START_RECEIPT_TRIGGER_ENABLED'}
    if(-not $Enabled){return 'TRIGGER_NOT_YET_ENABLED'}
    if(Test-ExactBool $Binding.held_trigger_enabled_after $true){return 'TRIGGER_ENABLED_HELD_READBACK'}
    'TRIGGER_ENABLED_XML_EQUAL_OUTSIDE_FLAGS'
}

function Invoke-StopWarden {
    param($Folder,$Bindings,$StartReceipt)
    $state=$null;$mode=$null;$otherDaemons=@();$idle=$null;$proof=$null;$boot=$null;$presence=$null;$instance=$null
    try{
        $state=Get-WardenTaskState $Folder;$mode=Get-StopMode $state
        $otherDaemons=@(Get-OtherDaemonTaskStates $Folder);Assert-OtherDaemonsIdle $otherDaemons
        if(Test-Path -LiteralPath $script:targetRoot){throw 'The stop root already exists for this attempt; preserve it and choose another -Attempt. Nothing was changed.'}
        if($mode -ceq 'RUNNING'){
            # Idle proof first (polled, including the slot-worker sweep), then the process proof of the live controller.
            $idle=Wait-WardenIdle
            $proof=Get-StopProcessProof ([int]$idle.controller.pid);$boot=$proof.last_boot_up_time
            $presence=Get-ControllerPresence;Assert-OnlyProvenController $presence $proof
            $instance=Get-RunningInstanceEvidence $state.task $proof
        }else{
            $presence=Get-ControllerPresence
            if(Test-ControllerAlive $presence){throw 'The task is stopped but a controller process, an unclassified runtime process or the loopback port is alive; nothing was changed.'}
            if(-not (Test-LoopbackFree)){throw 'The task is stopped but the controller port cannot be bound exclusively; nothing was changed.'}
            Assert-NoWorkers (Get-WorkerProcesses) '; nothing was changed.'
            $boot=Get-LastBootUtc
        }
    }catch{
        # Before the stop root exists nothing is consumed: the refusal is a plain message and the same -Attempt stays usable.
        $reason=$_.Exception.Message
        if($reason -notmatch 'nothing was changed'){$reason=$reason.TrimEnd('.')+'; nothing was changed.'}
        throw $reason}
    $controller=$null
    if($null -ne $idle){$controller=[ordered]@{pid=$idle.controller.pid;launcher_pid=$(if($null -ne $proof.launcher){$proof.launcher.pid}else{$null});instance_id=$idle.controller.instance_id;process_started_at=$idle.controller.process_started_at}}
    New-StopRoot
    # From here the attempt namespace is consumed: every failure leaves stop-held.json.
    $phase='PREPARATION';$stopRequested=$false;$disableRequested=$false;$exit=$null;$after=$null;$failure=$null;$portFreeAfter=$null;$afterTriggers=@()
    $beforeXml=$null;$beforeSddl=$null;$idleHash=$null;$intentHash=$null;$afterXml=$null;$afterSddl=$null;$receiptHash=$null;$receipt=$null
    $receiptPath=Join-Path $script:targetRoot 'stop-receipt.json'
    # The live logon trigger state (r5; null for the trigger-less r4 restore), already admitted by Assert-StopDefinition.
    $triggersBefore=@(Get-TaskTriggerSet $state.task);$triggerBefore=$(if($triggersBefore.Count){[bool]$triggersBefore[0].enabled}else{$null});$triggerAfter=$null
    try{
        $beforeXml=Write-RegistrationControl (Join-Path $script:targetRoot 'warden-task-before.xml') $state.xml
        if($beforeXml -cne (Get-TaskXmlSha256 $state.xml)){throw 'the captured task XML does not hash like the live XML string'}
        $beforeSddl=Write-RegistrationControl (Join-Path $script:targetRoot 'warden-task-before.sddl') $state.sddl
        if($null -ne $idle){$idleHash=Write-RegistrationControl (Join-Path $script:targetRoot 'idle-evidence.json') ($idle|ConvertTo-Json -Depth 12)}
        $intent=[ordered]@{schema='cochem-warden-stop-intent/2';attempt=$script:Attempt;retarget_target=$script:RetargetTarget;retarget_attempt=$script:RetargetAttempt;task_name=$script:taskName;mode=$mode;
            runtime_root=$script:runtimeRoot;requested_utc=[DateTime]::UtcNow.ToString('o');
            action_before=[ordered]@{execute=$state.action_path;arguments=$state.action_arguments;working_directory=$state.action_working_directory};triggers_before=$triggersBefore;
            enabled_before=$state.enabled;task_xml_before_sha256=$beforeXml;task_sddl_before_sha256=$beforeSddl;start_receipt_path=$StartReceipt.path;start_receipt_sha256=$StartReceipt.sha256;
            start_binding=$StartReceipt.binding;retarget_receipt_sha256=$StartReceipt.retarget_receipt_sha256;start_intent_sha256=$StartReceipt.start_intent_sha256;
            start_held_sha256=$StartReceipt.start_held_sha256;source_task_xml_after_sha256=$StartReceipt.source_task_xml_after_sha256;trigger_enabled_before=$triggerBefore;
            controller=$controller;running_instance=$instance;idle_evidence_sha256=$idleHash;last_boot_up_time=$boot;
            end_requested=($mode -ceq 'RUNNING');disable_planned=[bool]$state.enabled;unclean_shutdown_expected=($mode -ceq 'RUNNING');kill_allowed=$false;retry=$false}
        $intentHash=Write-RegistrationControl (Join-Path $script:targetRoot 'stop-intent.json') ($intent|ConvertTo-Json -Depth 6)
        # Re-attest immediately before the only End request (or the disable of an already stopped task).
        # The definition is compared first, so a changed definition is reported as such rather than as a binding refusal.
        $now=Get-WardenTaskState $Folder
        if($now.readable -and ($now.sddl -cne $state.sddl -or $now.xml -cne $state.xml)){throw 'the task definition changed during preparation'}
        if((Get-StopMode $now) -cne $mode){throw 'the task state changed during preparation'}
        if($mode -ceq 'RUNNING'){
            foreach($entry in @(Get-ProofProcesses $proof)){if(-not (Test-ProcessInstancePresent ([int]$entry.pid) ([string]$entry.creation_utc))){throw ('the proven '+$entry.role+' pid '+$entry.pid+' changed during preparation')}}
            $phase='END_REQUEST';$stopRequested=$true
            $now.task.Stop(0)
            $phase='END_WAIT'
            $exit=Wait-WardenExit $Folder $proof
            if(-not $exit.complete){throw ('the Warden did not fully exit within '+$script:ExitWaitSeconds+' s: '+(@($exit.reasons) -join '; '))}
        }
        $phase='DISABLE'
        $current=Get-WardenTaskState $Folder
        if(-not $current.readable){throw 'the task could not be read before the disable'}
        if($current.instances -ne 0 -or $current.state -notin @(1,3)){throw 'the task shows a running or queued instance at the disable gate'}
        if(Test-ControllerAlive (Get-ControllerPresence)){throw 'a controller process or the loopback listener is present at the disable gate'}
        if(-not (Test-LoopbackFree)){throw 'the controller port cannot be bound exclusively at the disable gate'}
        # The logon trigger would relaunch an enabled task at the next logon, so a no-op stop still disables; a disabled task is not written.
        if($current.enabled){$disableRequested=$true;$current.task.Enabled=$false}
        $phase='DISABLE_READBACK'
        $after=Get-WardenTaskState $Folder
        if($after.readable){
            $afterXml=Write-RegistrationControl (Join-Path $script:targetRoot 'warden-task-after.xml') $after.xml
            $afterSddl=Write-RegistrationControl (Join-Path $script:targetRoot 'warden-task-after.sddl') $after.sddl}
        Assert-StopDisabledTask $after $state
        if($afterXml -cne (Get-TaskXmlSha256 $after.xml)){throw 'the captured task XML does not hash like the live XML string'}
        $afterTriggers=@(Get-TaskTriggerSet $after.task);$triggerAfter=$(if($afterTriggers.Count){[bool]$afterTriggers[0].enabled}else{$null})
        if($triggerAfter -ne $triggerBefore){throw 'the logon trigger Enabled state changed during the stop'}
        $phase='FINAL_CHECK'
        if(Test-ControllerAlive (Get-ControllerPresence)){throw 'a controller process or the loopback listener is present after the disable'}
        $portFreeAfter=Test-LoopbackFree
        if(-not $portFreeAfter){throw 'the controller port cannot be bound exclusively after the disable'}
        $phase='RECEIPT'
        # What the next start of each action will need: the r5 action makes a fresh queue-launch child under its root on every
        # start (and its logon trigger is inert while the task is disabled); the r4 restore action names one fixed queue
        # directory, which the daemon refuses to reuse, so any later r4 start needs a fresh reviewed retarget.
        if($script:RetargetTarget -ceq 'r4'){
            $queueFacts=[ordered]@{queue_launch_output_root=$null;queue_launch_output=$script:queueRestart;fresh_queue_launch_child_per_start=$false;
                fresh_queue_launch_output_required=$true;r4_restore_requires_fresh_queue_launch_output=$true;logon_trigger_inert_while_disabled=$null}
            $queueBasis='the r4 restore action names the fixed queue directory '+$script:queueRestart+', which is never reused, and has no trigger.'
        }else{
            $queueFacts=[ordered]@{queue_launch_output_root=$script:queueLaunchRootR5;queue_launch_output=$null;fresh_queue_launch_child_per_start=$true;
                fresh_queue_launch_output_required=$false;r4_restore_requires_fresh_queue_launch_output=$true;logon_trigger_inert_while_disabled=$true}
            $queueBasis='the r5 action creates a fresh queue-launch child under its root on every start; a disabled task does not fire its logon trigger.'
        }
        if($mode -ceq 'RUNNING'){
            $status='WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED'
            $expectations=[ordered]@{evidenced=$true;crash_record_written=$false;uncleared_cleanup_rows_at_stop=$idle.uncleared_cleanup_rows;in_progress_leases_at_stop=$idle.in_progress_rows;
                expected_startup_quarantines=$idle.uncleared_cleanup_rows;ram_ledger_expected_action='VERIFY';ram_ledger_condition='adopted drive and the same boot as last_boot_up_time';
                warm_containers_reconciled_on_start=$true;observer_rebinds_itself=$true;
                basis=('End terminates outside the SIGINT/SIGTERM handlers, so the crash record and the Runtime.run finally block never run; no uncleared cleanup row and no active lease at stop, so the next start quarantines nothing; the same boot keeps the RAM ledger on VERIFY; '+$queueBasis)}
        }else{
            $status='WARDEN_ALREADY_STOPPED_CLEAN_NOOP'
            $expectations=[ordered]@{evidenced=$false;crash_record_written=$null;uncleared_cleanup_rows_at_stop=$null;in_progress_leases_at_stop=$null;expected_startup_quarantines=$null;
                ram_ledger_expected_action=$null;warm_containers_reconciled_on_start=$null;observer_rebinds_itself=$true;
                basis=('The controller was already stopped when this attempt ran (no task instance, port free); how it stopped is not evidenced here; '+$queueBasis)}
        }
        foreach($key in @($queueFacts.Keys)){$expectations[$key]=$queueFacts[$key]}
        $receipt=[ordered]@{schema='cochem-warden-stop/2';status=$status;mode=$mode;attempt=$script:Attempt;retarget_target=$script:RetargetTarget;retarget_attempt=$script:RetargetAttempt;
            task_name=$script:taskName;runtime_root=$script:runtimeRoot;
            action=[ordered]@{execute=$after.action_path;arguments=$after.action_arguments;working_directory=$after.action_working_directory};triggers=$afterTriggers;
            task_xml_after_sha256=$afterXml;task_xml_after_sha256_conversion='sha256 of the UTF-8 bytes (no BOM) of the RegisteredTask.Xml string, lowercase hex, no normalization';
            enabled_before=$state.enabled;enabled_after=$after.enabled;task_state_after=$after.state;instances_after=$after.instances;port_free_after=$portFreeAfter;
            ended_by_this_run=$stopRequested;disabled_by_this_run=$disableRequested;last_task_result=$after.last_task_result;
            last_task_result_expected=$(if($stopRequested){$script:expectedEndResult}else{$null});last_task_result_asserted=$false;
            action_unchanged=$true;triggers_unchanged=$true;sddl_preserved=$true;xml_unchanged_outside_settings_enabled=$true;
            task_xml_before_sha256=$beforeXml;task_sddl_before_sha256=$beforeSddl;task_sddl_after_sha256=$afterSddl;intent_sha256=$intentHash;idle_evidence_sha256=$idleHash;
            start_receipt_path=$StartReceipt.path;start_receipt_sha256=$StartReceipt.sha256;start_receipt_controller_bound=$false;runtime_bindings=$Bindings;
            start_binding=$StartReceipt.binding;retarget_receipt_path=$StartReceipt.retarget_receipt_path;retarget_receipt_sha256=$StartReceipt.retarget_receipt_sha256;
            start_intent_path=$StartReceipt.start_intent_path;start_intent_sha256=$StartReceipt.start_intent_sha256;start_held_path=$StartReceipt.start_held_path;
            start_held_sha256=$StartReceipt.start_held_sha256;source_task_xml_after_path=$StartReceipt.source_task_xml_after_path;
            source_task_xml_after_sha256=$StartReceipt.source_task_xml_after_sha256;source_task_xml_started_sha256=$StartReceipt.source_task_xml_started_sha256;
            live_xml_matches_source_outside_enabled_flags=$true;trigger_enabled_before=$triggerBefore;trigger_enabled_after=$triggerAfter;
            trigger_state_basis=(Get-TriggerStateBasis $StartReceipt $triggerAfter);
            controller=$controller;process_proof=$proof;running_instance=$instance;last_boot_up_time=$boot;controller_exit=$exit;unclean_shutdown_expected=$stopRequested;
            next_start_expectations=$expectations;observer_processes=$presence.observer_processes;observer_and_recorder_tasks_touched=$false;other_daemon_tasks=$otherDaemons;
            processes_killed=$false;started=$false;credentials_modified=$false;databases_modified=$false;ram_modified=$false;knowledge_rebuilt=$false;automatic_retry_allowed=$false}
        $receiptHash=Write-RegistrationControl $receiptPath ($receipt|ConvertTo-Json -Depth 10)
    }catch{$failure=$_.Exception.Message}
    if($null -ne $failure){
        $latest=$null;try{$latest=Get-WardenTaskState $Folder}catch{$latest=$null}
        $readable=($null -ne $latest -and $latest.readable)
        $heldRecord=[ordered]@{schema='cochem-warden-stop-held/2';attempt=$script:Attempt;retarget_target=$script:RetargetTarget;retarget_attempt=$script:RetargetAttempt;task_name=$script:taskName;
            runtime_root=$script:runtimeRoot;mode=$mode;phase=$phase;reason=$failure;start_binding=$StartReceipt.binding;
            end_requested=$stopRequested;disable_requested=$disableRequested;task_readable=$readable;enabled=$(if($readable){$latest.enabled}else{$null});
            task_state=$(if($readable){$latest.state}else{$null});running_instances=$(if($readable){$latest.instances}else{$null});last_task_result=$(if($readable){$latest.last_task_result}else{$null});
            task_xml_sha256_now=$(if($readable){Get-TaskXmlSha256 $latest.xml}else{$null});controller=$controller;surviving_processes=@($(if($null -ne $exit){$exit.surviving_processes}));
            port_listening=$(if($null -ne $exit){$exit.port_listening}else{$null});exclusive_bind_free=$(if($null -ne $exit){$exit.exclusive_bind_free}else{$null});
            worker_pids=@($(if($null -ne $exit){$exit.worker_pids}));exit_observation=$exit;intent_sha256=$intentHash;task_xml_after_sha256=$afterXml;
            processes_killed=$false;automatic_retry_allowed=$false;requires_reviewed_recovery=$true}
        $heldNote=''
        try{$null=Write-RegistrationControl (Join-Path $script:targetRoot 'stop-held.json') ($heldRecord|ConvertTo-Json -Depth 10)}catch{$heldNote=(' The held record could not be written: '+$_.Exception.Message)}
        $survivors=@();if($null -ne $exit){$survivors=@($exit.surviving_processes|ForEach-Object {[string]$_.pid})}
        $message=switch($phase){
            'PREPARATION'{'The Warden stop is held before any task change: '+$failure+'. Nothing was ended, disabled or killed; preserve the stop root and review stop-held.json before another -Attempt.'}
            'END_REQUEST'{'The Warden stop is held at the End request: '+$failure+'. The task was NOT disabled and nothing was killed; preserve everything and review stop-held.json.'}
            'END_WAIT'{'The Warden stop is held after the End request: '+$failure+'.'+$(if($survivors.Count){' Surviving pid(s): '+($survivors -join ', ')+'.'}else{''})+' The task was NOT disabled and nothing was killed; the owner reviews stop-held.json before any further action.'}
            'DISABLE'{'The Warden stop is held at the disable gate: '+$failure+'. The task was NOT disabled and nothing was killed; review stop-held.json.'}
            'FINAL_CHECK'{'The Warden stop is held after the disabled task was verified: '+$failure+'. The task is disabled and nothing was killed; preserve everything and review stop-held.json.'}
            'RECEIPT'{'The Warden is '+$(if($stopRequested){'ended and '}else{''})+'disabled but the stop receipt could not be completed: '+$failure+'. Preserve everything and review stop-held.json.'}
            default{
                if($disableRequested){'The Warden stop is held after the disable request: '+$failure+'. The task may already be disabled and nothing was killed; preserve everything and review stop-held.json.'}
                else{'The Warden stop is held after the disable gate: '+$failure+'. The task was NOT written by this run and nothing was killed; preserve everything and review stop-held.json.'}}}
        throw ($message+$heldNote)
    }
    [ordered]@{schema='cochem-warden-stop-result/2';status=$receipt.status;mode=$mode;attempt=$script:Attempt;retarget_target=$script:RetargetTarget;retarget_attempt=$script:RetargetAttempt;
        runtime_root=$script:runtimeRoot;receipt_path=$receiptPath;receipt_sha256=$receiptHash;
        task_xml_after_sha256=$afterXml;enabled_after=$after.enabled;instances_after=$after.instances;port_free_after=$portFreeAfter;ended_by_this_run=$stopRequested;
        disabled_by_this_run=$disableRequested;last_task_result=$after.last_task_result;start_binding=$StartReceipt.binding;trigger_enabled_after=$triggerAfter}
}

function Invoke-StopWardenSession {
    param($Folder,[bool]$ApplyRequested)
    # The read-only plan, and for -Apply its holds followed by the stop. Returns the plan or the result object.
    $holds=@();$startReceipt=$null;$bindings=$null;$codeTree=$null;$client=$null;$taskState=$null;$mode='DEFERRED';$otherDaemons=@();$presence=$null;$workers=$null
    $loopbackFree=$null;$idle=$null;$proof=$null;$liveTriggers=$null;$target=$script:RetargetTarget
    try{$startReceipt=Read-StartReceipt}catch{$holds+=($target+' start receipt: '+$_.Exception.Message)}
    if($null -ne $startReceipt){
        try{$bindings=Assert-TargetRuntimeBindings $startReceipt}catch{$holds+=($target+' runtime is not the reviewed installed build: '+$_.Exception.Message)}
        # Elevated, the bound runtime's code tree is inspected once before its interpreter runs with the elevated token.
        if($script:admin -and $null -ne $bindings){try{$null=Assert-CodeTreeOnce $script:runtimeRoot;$codeTree=$true}catch{$codeTree=$false;$holds+=($target+' code tree inspection: '+$_.Exception.Message)}}}
    $runtimeTrusted=($null -ne $bindings) -and (-not $script:admin -or $codeTree -eq $true)
    try{$client=Assert-ClientConfig}catch{$holds+=('Client configuration: '+$_.Exception.Message)}
    try{$taskState=Get-WardenTaskState $Folder
        if(-not $taskState.readable){$holds+='Warden task definition is unreadable without elevation; re-read during -Apply.'}
        else{
            $liveTriggers=@(Get-TaskTriggerSet $taskState.task)
            if($null -eq $startReceipt){$mode='UNBOUND'}else{$mode=Get-StopMode $taskState}}
    }catch{$mode='REFUSED';$holds+=('Warden task: '+$_.Exception.Message)}
    try{$otherDaemons=@(Get-OtherDaemonTaskStates $Folder)
        $active=@($otherDaemons|Where-Object {$_.active -eq $true}|ForEach-Object {$_.name});$deferred=@($otherDaemons|Where-Object {$_.state -eq 'ACCESS_DENIED_DEFERRED'}|ForEach-Object {$_.name})
        if($active.Count){$holds+=('Managed daemon tasks must remain stopped and disabled: '+($active -join ', '))}
        if($deferred.Count){$holds+=('Managed daemon task definitions are unreadable without elevation; re-read during -Apply: '+($deferred -join ', '))}
    }catch{$holds+=('Managed daemon tasks: '+$_.Exception.Message)}
    try{$presence=Get-ControllerPresence}catch{$holds+=('Controller presence could not be established: '+$_.Exception.Message)}
    # Verifier finding (slot check order): a live slot worker holds the plan and an ALREADY_STOPPED -Apply; a RUNNING -Apply
    # instead sweeps the workers after the polled idle proof (Wait-WardenIdle), so a briefly busy controller is not refused.
    try{$workers=Get-WorkerProcesses
        if(-not $ApplyRequested -or $mode -cne 'RUNNING'){Assert-NoWorkers $workers '; stop nothing, investigate.'}
    }catch{$holds+=('Worker processes: '+$_.Exception.Message)}
    if($mode -ceq 'ALREADY_STOPPED'){
        if($null -ne $presence -and (Test-ControllerAlive $presence)){$holds+='The task is stopped but a controller process, an unclassified runtime process or the loopback port is alive; investigate.'}
        try{$loopbackFree=Test-LoopbackFree;if(-not $loopbackFree){$holds+='The task is stopped but the controller port cannot be bound exclusively.'}}catch{$holds+=('Loopback probe: '+$_.Exception.Message)}
    }elseif(-not $ApplyRequested -and $mode -cin @('RUNNING','DEFERRED')){
        # The plan evaluates the idle predicate once, read-only; -Apply polls it (Wait-WardenIdle) inside the stop.
        if(-not $runtimeTrusted -or $null -eq $client){$holds+=('The idle predicate was not evaluated: the '+$target+' runtime (and, elevated, its code tree) or the client configuration is not verified.')}
        else{
            try{$idle=Get-IdleEvidence
                if(-not $idle.idle){$holds+=('The Warden is not idle now: '+(@($idle.reasons) -join '; ')+$(if(@($idle.offending_job_ids).Count){'; offending job ids: '+(@($idle.offending_job_ids) -join ', ')}else{''}))}
            }catch{$holds+=('Idle predicate: '+$_.Exception.Message)}
            if($script:admin -and $mode -ceq 'RUNNING' -and $null -ne $idle -and $null -ne $idle.controller -and $null -ne $presence){
                try{$proof=Get-StopProcessProof ([int]$idle.controller.pid);Assert-OnlyProvenController $presence $proof}catch{$holds+=('Process proof: '+$_.Exception.Message)}}}
    }
    if(Test-Path -LiteralPath $script:targetRoot){$holds+='The stop root already exists for this attempt; preserve it and choose another -Attempt.'}
    $readable=($null -ne $taskState -and $taskState.readable)
    # Arrays are taken by plain assignment (a $() subexpression would unroll a one-element list).
    $allowedTriggers=$null;if($null -ne $startReceipt){$allowedTriggers=$startReceipt.trigger_enabled_allowed}
    $plan=[ordered]@{schema='cochem-warden-stop-plan/2';mode='READ_ONLY_PLAN';stop_mode=$mode;attempt=$script:Attempt;retarget_target=$target;retarget_attempt=$script:RetargetAttempt;
        task_name=$script:taskName;start_receipt_path=$script:startReceiptPath;start_receipt=$startReceipt;runtime_root=$script:runtimeRoot;target_root=$script:targetRoot;
        recover_interrupted_start=[bool]$script:RecoverInterruptedStart;start_binding=$(if($null -ne $startReceipt){$startReceipt.binding}else{$null});
        trigger_enabled_allowed=$allowedTriggers;
        runtime_verified=($null -ne $bindings);runtime_bindings=$bindings;code_tree_verified=$codeTree;client_config=$client;task_readable=$readable;
        task_summary=$(if($readable){[ordered]@{enabled=$taskState.enabled;state=$taskState.state;instances=$taskState.instances;last_task_result=$taskState.last_task_result;action_path=$taskState.action_path;action_arguments=$taskState.action_arguments;working_directory=$taskState.action_working_directory;triggers=$liveTriggers;task_xml_sha256=(Get-TaskXmlSha256 $taskState.xml)}}else{$null});
        expected_action=$script:expectedAction;expected_triggers=$script:expectedTriggers;other_daemon_tasks=$otherDaemons;controller_presence=$presence;
        worker_processes=$(if($null -ne $workers){[ordered]@{workers=$workers.workers;uninspectable_count=@($workers.uninspectable_processes).Count;exited_during_sweep=$workers.exited_during_sweep;authoritative=$workers.authoritative}}else{$null});
        loopback_port_free=$loopbackFree;
        idle=$(if($null -ne $idle){[ordered]@{idle=$idle.idle;reasons=$idle.reasons;offending_job_ids=$idle.offending_job_ids;errors=$idle.errors;queue_rows=$idle.queue_rows;queue_status_counts=$idle.queue_status_counts;in_progress_rows=$idle.in_progress_rows;uncleared_cleanup_rows=$idle.uncleared_cleanup_rows;routing_holds=$idle.routing_holds;controller=$idle.controller}}else{$null});
        process_proof=$proof;process_proof_note=$(if($script:admin){$null}else{'The controller process proof needs the elevated token; -Apply records it.'});
        idle_wait_seconds=$script:IdleWaitSeconds;exit_wait_seconds=$script:ExitWaitSeconds;administrator=$script:admin;holds=$holds;
        tasks_changed=0;ended=$false;disabled=$false;processes_killed=$false;observer_and_recorder_tasks_touched=$false;automatic_retry_allowed=$false}
    if(-not $ApplyRequested){return $plan}
    if($holds.Count){throw ('The Warden stop is held. Nothing was changed: '+($holds -join ' | '))}
    Invoke-StopWarden $Folder $bindings $startReceipt
}

function Invoke-StopWardenMain {
    param([bool]$ApplyRequested)
    $ErrorActionPreference='Stop';Set-StrictMode -Version Latest
    foreach($module in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security','CimCmdlets','NetTCPIP')){Import-Module (Join-Path $PSHOME "Modules\$module\$module.psd1") -ErrorAction Stop}
    if($PSVersionTable.PSEdition -ne 'Desktop' -or -not [Environment]::Is64BitProcess -or $env:COMPUTERNAME -cne 'AETHERDESK'){throw 'Use 64-bit Windows PowerShell 5.1 on AETHERDESK.'}
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent();$script:admin=[Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    Assert-ApplyIdentity $ApplyRequested $script:admin $identity.Name
    Set-StopConstants
    $copyHelper='C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1'
    foreach($text in Import-ReviewedFunctions $copyHelper '0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b' @('Assert-NoReparseAncestors','Assert-ProtectedPath','New-CodeAcl','New-ProtectedDirectory','Initialize-FileIdentity','Open-VerifiedFile')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $PSScriptRoot 'check-worker-native-status-r3.ps1') '18f58ebb448d8a0c6329dd187d4a9a27fa9cbe942cd05e906bb7aabc67e787a7' @('Read-R3Control','Read-R3Text')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $PSScriptRoot 'register-stopped-warden-r3.ps1') 'eccc593f36cbf488a54775b4343bcf3cf8b261b7cd81e5536fb7f2f18466a198' @('Assert-RegisteredTaskAcl','Write-RegistrationControl')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $PSScriptRoot 'protected-code-inspection-v4.ps1') '5c01543cbb8b8d64b2b9f1bab4a13f87f8ff9e1ab3e82dfb6fc547144c77b95d' @('Assert-CodeTreeOnce')){. ([scriptblock]::Create($text))}
    Initialize-FileIdentity
    $held=[Collections.Generic.List[IO.FileStream]]::new()
    try{
        $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect();$folder=$scheduler.GetFolder('\')
        Invoke-StopWardenSession $folder $ApplyRequested|ConvertTo-Json -Depth 10
    }finally{foreach($stream in $held){$stream.Dispose()}}
}

# Invocation boundary: the only top-level statement. Fixtures dot-source the functions above from the AST without running it.
Invoke-StopWardenMain -ApplyRequested ([bool]$Apply)
