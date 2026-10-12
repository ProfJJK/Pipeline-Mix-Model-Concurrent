#Requires -Version 5.1
<# Ends and disables the r4 CoChem-4.2.7-Warden for the Gemini sign-in series (decision 2B, build-manifest step 1).
   Derived from retarget-warden-r4.ps1 v2.2 (sha256 8ee6b412f6be176dfac7c2c1b2340f1973e08358c7d22da6d4515e79f0327a4e):
   every function shared with v2.2 is a byte-identical copy except one line of Get-ControllerPresence (below), and the
   reviewed helpers are imported by hash as v2.2 does.
   2026-10-11 17:22 sitting fix: S2 (task enabled, no instance) held on the owner's four Antigravity bridge MCP clients
   ("<runtime python>" -m cochem_mcp --provider codex|claude --config C:\Users\ansac\CoChem427\bridge.local.json: stdio
   front ends of the job board that only call 127.0.0.1:47824 as clients, never bind it, never run as SYSTEM). A rooted
   process whose command line is exactly that entry is now a GUI client, like 'cochem_pipeline mcp'; controller-like command
   lines stay controllers from any image, and every other rooted process stays unclassified (and holds).
   Default is a read-only plan (cochem-warden-stop-plan/1). It reads the task, the managed daemon tasks, the processes,
   the loopback port and the controller's /health and /operator views, and prints the same idle predicate -Apply
   enforces. Unelevated, the SYSTEM-only task definition is unreadable and is deferred to -Apply.
   -Apply (AETHERDESK\ansac in elevated 64-bit Windows PowerShell 5.1):
     1. binds the reviewed r4 runtime (the v2.2 bindings plus the install, revision, layout, configuration and
        retarget-evidence pins) and inspects the r4 code tree once before an r4 interpreter runs elevated;
     2. requires the live task to be the exact r4-v1 SYSTEM daemon (pinned action, principal, settings, private DACL)
        running exactly one enabled instance, or already stopped (ALREADY_STOPPED: no End; the task is still disabled);
     3. proves the controller idle: two /health samples at least 5 s apart with one stable SYSTEM r4 identity, then one
        GET /operator; active [], quarantined_slots {}, routing.active_reservations [], routing.execution_quarantines []
        and no queue row IN_PROGRESS, PENDING or PENDING_RETRY; polled no faster than every 10 s up to -IdleWaitSeconds;
     4. records the controller and its launcher (image, parent, creation time, socket owner), the boot time and the
        observer processes (left alone);
     5. creates C:\Program Files\CoChem\WardenStop4.2.7-windows-20261010-r4-<Attempt> (refused when present) and writes
        the task XML and SDDL, the idle evidence and stop-intent.json before any change;
     6. requests Task Scheduler End exactly once (the COM task object's Stop method, flags 0);
     7. waits up to -ExitWaitSeconds for: no task instance; launcher and controller gone (pid and creation time); no
        controller-like process; nothing listening on 47824 and an exclusive bind succeeding; no slot worker. Anything
        left -> stop-held.json naming it and a throw: the task is NOT disabled and nothing is killed;
     8. disables the task and proves it: disabled, no instance, action unchanged, security descriptor byte-equal and
        the XML unchanged outside <Settings><Enabled> (the live XML carries no such element today);
     9. writes stop-receipt.json (cochem-warden-stop/1) stating what the next start will see.
   End terminates the daemon outside its SIGINT/SIGTERM path, so this is an unclean shutdown by construction (no crash
   record, no finally block); the receipt says so. Every failure after the stop root exists leaves stop-held.json.
   Never touched: any other task (the held supervisor observation and the resource observation recorder included),
   credentials, databases, the RAM disk, Docker, knowledge. No start, retry, kill or delete ever occurs. #>
[CmdletBinding()]
param([switch]$Apply,[ValidatePattern('^v[0-9]{1,3}$')][string]$Attempt='v1',[ValidateRange(10,900)][int]$IdleWaitSeconds=120,[ValidateRange(10,900)][int]$ExitWaitSeconds=90)

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
        $rooted=$path -and ($path.StartsWith($script:r3Root,[StringComparison]::OrdinalIgnoreCase) -or $path.StartsWith($script:r4Root,[StringComparison]::OrdinalIgnoreCase) -or $path.StartsWith($script:basePythonRoot,[StringComparison]::OrdinalIgnoreCase))
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

function Get-HealthSample {
    $result=Invoke-NativeJudged $script:r4Python @('-I','-B','-X','utf8','-m','cochem_pipeline','health','--client-config',$script:clientConfig)
    if($result.code -ne 0){return [pscustomobject]@{ok=$false;error=$result.stderr;health=$null}}
    $health=$null;try{$health=$result.stdout|ConvertFrom-Json}catch{return [pscustomobject]@{ok=$false;error='health output is not JSON';health=$null}}
    if($null -eq $health -or $health -isnot [Management.Automation.PSCustomObject]){return [pscustomobject]@{ok=$false;error='health output is not a JSON object';health=$null}}
    foreach($field in @('service_identity','source_root','pid','instance_id','process_started_at','active','quarantined_slots')){
        if($null -eq $health.PSObject.Properties[$field]){return [pscustomobject]@{ok=$false;error=('health lacks '+$field);health=$health}}}
    if($health.service_identity -cne 'SYSTEM' -or [string]$health.source_root -cne $script:r4SourceRoot){return [pscustomobject]@{ok=$false;error='health answered with an unexpected identity or source root';health=$health}}
    [pscustomobject]@{ok=$true;error='';health=$health}
}

function Get-ProcessProof {
    param([int]$ProcessId)
    $process=Get-CimInstance Win32_Process -Filter ('ProcessId = '+$ProcessId) -ErrorAction Stop
    if($null -eq $process){throw 'The controller pid reported by /health does not exist.'}
    $expected=Get-ExpectedArguments $script:commissioningConfig $script:queueNew
    if([string]$process.ExecutablePath -cne $script:basePython -and [string]$process.ExecutablePath -cne $script:r4Python){throw 'The controller pid does not run the r4 toolchain interpreter.'}
    if(([string]$process.CommandLine).IndexOf($expected,[StringComparison]::Ordinal) -lt 0){throw 'The controller pid is not running the expected r4 daemon command.'}
    try{$listeners=@(Get-NetTCPConnection -LocalPort $script:port -State Listen -ErrorAction Stop)}
    catch{if($_.FullyQualifiedErrorId -like 'CmdletizationQuery_NotFound*'){$listeners=@()}else{throw ('The controller port owner could not be established: '+$_.Exception.Message)}}
    if($listeners.Count -eq 0){throw 'Nothing listens on the controller port.'}
    foreach($listener in $listeners){if([int]$listener.OwningProcess -ne $ProcessId){throw ('The controller port is owned by pid '+$listener.OwningProcess+', not the pid reported by /health.')}}
    $parent=Get-CimInstance Win32_Process -Filter ('ProcessId = '+[int]$process.ParentProcessId) -ErrorAction SilentlyContinue
    $owner=$null;try{$owner=Invoke-CimMethod -InputObject $process -MethodName GetOwner -ErrorAction Stop}catch{$owner=$null}
    if($null -eq $owner -or $owner.ReturnValue -ne 0 -or [string]$owner.User -cne 'SYSTEM'){throw 'The controller pid does not run as SYSTEM.'}
    [ordered]@{pid=$process.ProcessId;image=$process.ExecutablePath;parent_pid=$process.ParentProcessId;parent_image=$(if($null -ne $parent){[string]$parent.ExecutablePath}else{$null});owner=$owner.User;port_owner_verified=$true}
}

function Set-StopConstants {
    # The v2.2 pin block (values unchanged), the r4-v1 action, the operator call and the stop namespace.
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
    $script:r4LayoutPin='8430fdf1109c63c4a89479f03da8a465dfebf5566c7791c64f868202170672c4'
    $script:commissioningRoot=Join-Path $script:base 'WardenCommissioning4.2.7-windows-20261007-r3-v1';$script:commissioningConfig=Join-Path $script:commissioningRoot 'pipeline.json'
    $script:privateRoot='C:\ProgramData\CoChemPipeline427\private'
    # The live action is the one the reviewed retarget v1 installed; its after-XML is the evidence of that action.
    $script:queueR4v1=Join-Path $script:privateRoot 'queue-retarget-20261010-r4-v1'
    # Get-ProcessProof (v2.2, unchanged) binds the daemon command line through $queueNew: here that is the r4-v1 queue.
    $script:queueNew=$script:queueR4v1
    $script:retargetTaskXml=Join-Path $script:base 'WardenRetarget4.2.7-windows-20261010-r4-v1\warden-task-after.xml'
    $script:retargetTaskXmlPin='fbfdcd8318d2418cbb8d28badad53a1a8e829a1e9c7143d13600bb62fd04c2be'
    $script:taskName='CoChem-4.2.7-Warden';$script:port=47824;$script:clientConfig='C:\Users\ansac\CoChem427\pipeline-client-r3.json'
    # The two reviewed observer recorders (SYSTEM tasks that only record), matched on their pinned script paths.
    $script:observerPattern='\\SupervisorObservation4\.2\.7-windows-20261007-r3-v1\\held-supervisor-observation-r3-v1\.py"?\s+--observe\b|\\ResourceObservation4\.2\.7-windows-20261008-r3-v4\\package\\observe_resources\.py"?\s+--run-observer\b'
    # Fixed namespace date (the build date), as v2.2 fixes its own; -Attempt selects the namespace, which is never reused.
    $script:stopNamespaceDate='20261010'
    $script:targetRoot=Join-Path $script:base ('WardenStop4.2.7-windows-'+$script:stopNamespaceDate+'-r4-'+$script:Attempt)
    $script:healthSpacingSeconds=5;$script:idlePollSeconds=10;$script:exitPollSeconds=3
    $script:blockingQueueStatuses=@('IN_PROGRESS','PENDING','PENDING_RETRY')
    # 0x41306 SCHED_S_TASK_TERMINATED: what End is expected to leave in LastTaskResult; recorded, never asserted.
    $script:expectedEndResult=267014
    # GET /operator (ControlClient issues GET when data is None); single-quoted Python only, projected to the queue rows.
    $script:operatorCall=@(
        'import json,sys',
        'from pathlib import Path',
        'from cochem_pipeline.service import ControlClient',
        'config=json.loads(Path(sys.argv[1]).read_text(encoding=''utf-8-sig''))',
        'value=ControlClient(int(config.get(''port'',47824)),config[''token_file'']).call(''/operator'')',
        'queue=value.get(''queue'') if isinstance(value,dict) else None',
        'rows=[{key:row.get(key) for key in (''job_id'',''workflow_id'',''kind'',''status'')} if isinstance(row,dict) else row for row in queue] if isinstance(queue,list) else queue',
        'print(json.dumps({''schema'':''cochem-operator-queue-extract/1'',''queue'':rows},ensure_ascii=False))') -join "`n"
}

function Assert-StopRuntimePins {
    param($Runtime)
    # The manifest's r4 pins beyond the v2.2 content bindings, plus the configuration and action evidence the task uses.
    if($Runtime.install_receipt_sha256 -cne $script:r4InstallPin){throw 'The r4 installation receipt is not the pinned receipt.'}
    if($Runtime.revision_sha256 -cne $script:r4RevisionPin){throw 'The r4 installed revision is not the pinned revision.'}
    $layout=Read-R3Control (Join-Path $script:r4Root 'windows-layout.json') $script:r4LayoutPin
    $null=Read-R3Control $script:commissioningConfig $script:configPin
    $retarget=Read-R3Control $script:retargetTaskXml $script:retargetTaskXmlPin 1048576
    [ordered]@{install_receipt_sha256=$Runtime.install_receipt_sha256;source_manifest_sha256=$Runtime.source_manifest_sha256;revision_sha256=$Runtime.revision_sha256;
        configuration_sha256=$script:configPin;layout_sha256=$layout.Sha256;retarget_task_xml_sha256=$retarget.Sha256;reviewed_repair_sha256=$script:repairPin}
}

function Assert-StopDefinition {
    param($State)
    if($State.user -notin @('SYSTEM','S-1-5-18') -or $State.logon_type -ne 5 -or $State.run_level -ne 1 -or $State.triggers -ne 0 -or $State.actions -ne 1 -or
       $State.multiple_instances -ne 2 -or $State.execution_time_limit -cne 'PT0S' -or $State.restart_count -ne 0 -or $State.allow_demand_start -ne $true){
        throw 'The Warden task is not the exact reviewed SYSTEM daemon definition; preserve it for review.'}
    if($State.action_type -ne 0 -or $State.action_path -cne $script:r4Python -or $State.action_working_directory -cne $script:r4Root -or
       $State.action_arguments -cne (Get-ExpectedArguments $script:commissioningConfig $script:queueR4v1)){
        throw 'The Warden task action differs from the pinned r4-v1 action; preserve it for review.'}
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

function Test-IdlePredicate {
    param($First,$Second,$OperatorText)
    # Idle only when every clause holds on both samples and on the operator queue; anything unreadable holds.
    $reasons=[Collections.Generic.List[string]]::new();$jobs=[Collections.Generic.List[string]]::new()
    $samples=@($First,$Second);$uncleared=$null;$routeHolds=$null
    for($index=0;$index -lt 2;$index++){
        $sample=$samples[$index];$label='health sample '+($index+1)
        if($null -eq $sample -or $sample -isnot [Management.Automation.PSCustomObject]){$reasons.Add($label+' is unavailable or not a JSON object');continue}
        $identity=$sample.PSObject.Properties['service_identity'];$source=$sample.PSObject.Properties['source_root']
        if($null -eq $identity -or [string]$identity.Value -cne 'SYSTEM' -or $null -eq $source -or [string]$source.Value -cne $script:r4SourceRoot){$reasons.Add($label+' is not the SYSTEM controller from the r4 root')}
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
    $queueRows=$null;$inProgress=$null;$statusCounts=[ordered]@{}
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
            foreach($key in @($counts.Keys|Sort-Object)){$statusCounts[$key]=$counts[$key]}}}
    [ordered]@{idle=($reasons.Count -eq 0);reasons=@($reasons);offending_job_ids=@($jobs|Select-Object -Unique);queue_rows=$queueRows;queue_status_counts=$statusCounts;
        in_progress_rows=$inProgress;uncleared_cleanup_rows=$uncleared;routing_holds=$routeHolds}
}

function Get-OperatorSnapshot {
    $result=Invoke-NativeJudged $script:r4Python @('-I','-B','-X','utf8','-c',$script:operatorCall,$script:clientConfig)
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
    $deadline=[DateTime]::UtcNow.AddSeconds($script:IdleWaitSeconds)
    $limit=[Math]::Max(1,[int][Math]::Floor($script:IdleWaitSeconds/$script:idlePollSeconds));$evaluations=0;$last=$null
    while($true){
        $evaluations++;$last=Get-IdleEvidence
        if($last.idle){$last.evaluations=$evaluations;return $last}
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
    # The v2.2 proof (r4 daemon command, SYSTEM owner, socket owner) plus the launcher the task started and both
    # creation times, so that a reused pid is never mistaken for the controller later.
    $proof=Get-ProcessProof $ProcessId
    $controller=Get-CimInstance Win32_Process -Filter ('ProcessId = '+$ProcessId) -ErrorAction Stop
    if($null -eq $controller){throw 'The controller pid exited during the process proof.'}
    $controllerCreation=Get-ProcessCreationUtc $controller
    if($null -eq $controllerCreation){throw 'The controller creation time could not be read.'}
    $launcher=$null
    if([string]$controller.ExecutablePath -ceq $script:basePython){
        $parent=Get-CimInstance Win32_Process -Filter ('ProcessId = '+[int]$controller.ParentProcessId) -ErrorAction Stop
        $expected=Get-ExpectedArguments $script:commissioningConfig $script:queueR4v1
        if($null -eq $parent -or -not [string]::Equals([string]$parent.ExecutablePath,$script:r4Python,[StringComparison]::OrdinalIgnoreCase) -or
           ([string]$parent.CommandLine).IndexOf($expected,[StringComparison]::Ordinal) -lt 0){throw 'The controller parent is not the r4 venv launcher started by the task action.'}
        $launcherCreation=Get-ProcessCreationUtc $parent
        if($null -eq $launcherCreation){throw 'The launcher creation time could not be read.'}
        $launcher=[ordered]@{pid=[int]$parent.ProcessId;image=[string]$parent.ExecutablePath;creation_utc=$launcherCreation}}
    [ordered]@{controller=[ordered]@{pid=[int]$controller.ProcessId;image=[string]$controller.ExecutablePath;creation_utc=$controllerCreation;parent_pid=[int]$controller.ParentProcessId};
        launcher=$launcher;owner=$proof.owner;port_owner_verified=$proof.port_owner_verified;last_boot_up_time=(Get-LastBootUtc)}
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

function Invoke-StopWarden {
    param($Folder,$Pins)
    $state=$null;$mode=$null;$otherDaemons=@();$idle=$null;$proof=$null;$boot=$null;$presence=$null
    try{
        $state=Get-WardenTaskState $Folder;$mode=Assert-StopSource $state
        $otherDaemons=@(Get-OtherDaemonTaskStates $Folder);Assert-OtherDaemonsIdle $otherDaemons
        if(Test-Path -LiteralPath $script:targetRoot){throw 'The stop root already exists for this attempt; preserve it and choose another -Attempt. Nothing was changed.'}
        if($mode -ceq 'RUNNING'){
            Assert-NoWorkers (Get-WorkerProcesses) ' while the controller should be idle; nothing was changed.'
            $idle=Wait-WardenIdle
            $proof=Get-StopProcessProof ([int]$idle.controller.pid);$boot=$proof.last_boot_up_time
            $presence=Get-ControllerPresence;Assert-OnlyProvenController $presence $proof
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
    New-ProtectedDirectory $script:targetRoot
    # From here the attempt namespace is consumed: every failure leaves stop-held.json.
    $phase='PREPARATION';$stopRequested=$false;$disableRequested=$false;$exit=$null;$after=$null;$failure=$null
    $beforeXml=$null;$beforeSddl=$null;$idleHash=$null;$intentHash=$null;$afterXml=$null;$afterSddl=$null;$receiptHash=$null;$receipt=$null
    try{
        $beforeXml=Write-RegistrationControl (Join-Path $script:targetRoot 'warden-task-before.xml') $state.xml
        $beforeSddl=Write-RegistrationControl (Join-Path $script:targetRoot 'warden-task-before.sddl') $state.sddl
        if($null -ne $idle){$idleHash=Write-RegistrationControl (Join-Path $script:targetRoot 'idle-evidence.json') ($idle|ConvertTo-Json -Depth 12)}
        $intent=[ordered]@{schema='cochem-warden-stop-intent/1';attempt=$script:Attempt;task_name=$script:taskName;mode=$mode;requested_utc=[DateTime]::UtcNow.ToString('o');
            action_before=[ordered]@{path=$state.action_path;arguments=$state.action_arguments;working_directory=$state.action_working_directory};enabled_before=$state.enabled;
            task_xml_before_sha256=$beforeXml;task_sddl_before_sha256=$beforeSddl;controller=$controller;idle_evidence_sha256=$idleHash;last_boot_up_time=$boot;
            end_requested=($mode -ceq 'RUNNING');disable_planned=$true;unclean_shutdown_expected=($mode -ceq 'RUNNING');kill_allowed=$false;retry=$false}
        $intentHash=Write-RegistrationControl (Join-Path $script:targetRoot 'stop-intent.json') ($intent|ConvertTo-Json -Depth 6)
        # Re-attest immediately before the only End request.
        $now=Get-WardenTaskState $Folder
        if((Assert-StopSource $now) -cne $mode){throw 'the task state changed during preparation'}
        if($now.sddl -cne $state.sddl -or $now.xml -cne $state.xml){throw 'the task definition changed during preparation'}
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
        if($current.enabled){$disableRequested=$true;$current.task.Enabled=$false}
        $phase='DISABLE_READBACK'
        $after=Get-WardenTaskState $Folder
        if($after.readable){
            $afterXml=Write-RegistrationControl (Join-Path $script:targetRoot 'warden-task-after.xml') $after.xml
            $afterSddl=Write-RegistrationControl (Join-Path $script:targetRoot 'warden-task-after.sddl') $after.sddl}
        Assert-StopDisabledTask $after $state
        $phase='RECEIPT'
        if($mode -ceq 'RUNNING'){
            $status='WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED'
            $expectations=[ordered]@{evidenced=$true;crash_record_written=$false;uncleared_cleanup_rows_at_stop=$idle.uncleared_cleanup_rows;in_progress_leases_at_stop=$idle.in_progress_rows;
                expected_startup_quarantines=$idle.uncleared_cleanup_rows;fresh_queue_launch_output_required=$true;queue_launch_output_never_reused=$script:queueR4v1;
                ram_ledger_expected_action='VERIFY';ram_ledger_condition='adopted drive and the same boot as last_boot_up_time';warm_containers_reconciled_on_start=$true;observer_rebinds_itself=$true;
                basis='End terminates outside the SIGINT/SIGTERM handlers, so record_crash and the Runtime.run finally block never run (__main__.py:61-64, 86-91; runtime.py:602-640); no uncleared cleanup row and no active lease at stop, so the next start quarantines nothing (store.py:246-247, 1167-1198; runtime.py:117-118, 160-196); same boot keeps the RAM ledger on VERIFY (ramdisk.py:253-279).'}
        }else{
            $status='WARDEN_ALREADY_STOPPED_AND_DISABLED'
            $expectations=[ordered]@{evidenced=$false;crash_record_written=$null;uncleared_cleanup_rows_at_stop=$null;in_progress_leases_at_stop=$null;expected_startup_quarantines=$null;
                fresh_queue_launch_output_required=$true;queue_launch_output_never_reused=$script:queueR4v1;ram_ledger_expected_action=$null;warm_containers_reconciled_on_start=$null;observer_rebinds_itself=$true;
                basis='The controller was already stopped when this attempt ran; how it stopped is not evidenced here.'}
        }
        $receipt=[ordered]@{schema='cochem-warden-stop/1';status=$status;mode=$mode;attempt=$script:Attempt;task_name=$script:taskName;runtime_root=$script:r4Root;
            action_path=$after.action_path;action_arguments=$after.action_arguments;working_directory=$after.action_working_directory;action_unchanged=$true;
            enabled_before=$state.enabled;enabled=$after.enabled;task_state=$after.state;running_instances=$after.instances;last_task_result=$after.last_task_result;
            last_task_result_expected=$(if($stopRequested){$script:expectedEndResult}else{$null});last_task_result_asserted=$false;end_requested=$stopRequested;disable_requested=$disableRequested;
            intent_sha256=$intentHash;idle_evidence_sha256=$idleHash;task_xml_before_sha256=$beforeXml;task_sddl_before_sha256=$beforeSddl;task_xml_after_sha256=$afterXml;task_sddl_after_sha256=$afterSddl;
            sddl_preserved=$true;xml_unchanged_outside_settings_enabled=$true;controller=$controller;process_proof=$proof;last_boot_up_time=$boot;controller_exit=$exit;
            unclean_shutdown_expected=$stopRequested;next_start_expectations=$expectations;observer_processes=$presence.observer_processes;observer_and_recorder_tasks_touched=$false;
            other_daemon_tasks=$otherDaemons;r4_bindings=$Pins;queue_launch_output=$script:queueR4v1;processes_killed=$false;started=$false;credentials_modified=$false;databases_modified=$false;
            ram_modified=$false;knowledge_rebuilt=$false;automatic_retry_allowed=$false}
        $receiptHash=Write-RegistrationControl (Join-Path $script:targetRoot 'stop-receipt.json') ($receipt|ConvertTo-Json -Depth 10)
    }catch{$failure=$_.Exception.Message}
    if($null -ne $failure){
        $latest=$null;try{$latest=Get-WardenTaskState $Folder}catch{$latest=$null}
        $readable=($null -ne $latest -and $latest.readable)
        $heldRecord=[ordered]@{schema='cochem-warden-stop-held/1';attempt=$script:Attempt;task_name=$script:taskName;mode=$mode;phase=$phase;reason=$failure;
            end_requested=$stopRequested;disable_requested=$disableRequested;task_readable=$readable;enabled=$(if($readable){$latest.enabled}else{$null});
            task_state=$(if($readable){$latest.state}else{$null});running_instances=$(if($readable){$latest.instances}else{$null});last_task_result=$(if($readable){$latest.last_task_result}else{$null});
            controller=$controller;surviving_processes=@($(if($null -ne $exit){$exit.surviving_processes}));port_listening=$(if($null -ne $exit){$exit.port_listening}else{$null});
            exclusive_bind_free=$(if($null -ne $exit){$exit.exclusive_bind_free}else{$null});worker_pids=@($(if($null -ne $exit){$exit.worker_pids}));exit_observation=$exit;
            intent_sha256=$intentHash;task_xml_after_sha256=$afterXml;processes_killed=$false;automatic_retry_allowed=$false;requires_reviewed_recovery=$true}
        $heldNote=''
        try{$null=Write-RegistrationControl (Join-Path $script:targetRoot 'stop-held.json') ($heldRecord|ConvertTo-Json -Depth 10)}catch{$heldNote=(' The held record could not be written: '+$_.Exception.Message)}
        $survivors=@();if($null -ne $exit){$survivors=@($exit.surviving_processes|ForEach-Object {[string]$_.pid})}
        $message=switch($phase){
            'PREPARATION'{'The Warden stop is held before any task change: '+$failure+'. Nothing was ended, disabled or killed; preserve the stop root and review stop-held.json before another -Attempt.'}
            'END_REQUEST'{'The Warden stop is held at the End request: '+$failure+'. The task was NOT disabled and nothing was killed; preserve everything and review stop-held.json.'}
            'END_WAIT'{'The Warden stop is held after the End request: '+$failure+'.'+$(if($survivors.Count){' Surviving pid(s): '+($survivors -join ', ')+'.'}else{''})+' The task was NOT disabled and nothing was killed; the owner reviews stop-held.json before any further action.'}
            'RECEIPT'{'The Warden is ended and disabled but the stop receipt could not be completed: '+$failure+'. Preserve everything and review stop-held.json.'}
            default{'The Warden stop is held at the disable step: '+$failure+'. The controller has exited and the task may already be disabled; preserve everything and review stop-held.json.'}}
        throw ($message+$heldNote)
    }
    [ordered]@{schema='cochem-warden-stop-result/1';status=$receipt.status;mode=$mode;attempt=$script:Attempt;receipt_path=(Join-Path $script:targetRoot 'stop-receipt.json');receipt_sha256=$receiptHash;
        task_xml_after_sha256=$afterXml;enabled=$after.enabled;running_instances=$after.instances;last_task_result=$after.last_task_result;end_requested=$stopRequested;disable_requested=$disableRequested}
}

function Invoke-StopWardenMain {
    param([bool]$ApplyRequested)
    $ErrorActionPreference='Stop';Set-StrictMode -Version Latest
    foreach($module in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security','CimCmdlets','NetTCPIP')){Import-Module (Join-Path $PSHOME "Modules\$module\$module.psd1") -ErrorAction Stop}
    if($PSVersionTable.PSEdition -ne 'Desktop' -or -not [Environment]::Is64BitProcess -or $env:COMPUTERNAME -cne 'AETHERDESK'){throw 'Use 64-bit Windows PowerShell 5.1 on AETHERDESK.'}
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent();$script:admin=[Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if($ApplyRequested -and (-not $script:admin -or $identity.Name -cne 'AETHERDESK\ansac')){throw '-Apply requires the owner in Administrator Windows PowerShell; nothing was changed.'}
    Set-StopConstants
    $copyHelper='C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1'
    foreach($text in Import-ReviewedFunctions $copyHelper '0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b' @('Assert-NoReparseAncestors','Assert-ProtectedPath','New-CodeAcl','New-ProtectedDirectory','Initialize-FileIdentity','Open-VerifiedFile')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $PSScriptRoot 'check-worker-native-status-r3.ps1') '18f58ebb448d8a0c6329dd187d4a9a27fa9cbe942cd05e906bb7aabc67e787a7' @('Read-R3Control','Read-R3Text')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $PSScriptRoot 'register-stopped-warden-r3.ps1') 'eccc593f36cbf488a54775b4343bcf3cf8b261b7cd81e5536fb7f2f18466a198' @('Assert-RegisteredTaskAcl','Write-RegistrationControl')){. ([scriptblock]::Create($text))}
    foreach($text in Import-ReviewedFunctions (Join-Path $PSScriptRoot 'protected-code-inspection-v4.ps1') '5c01543cbb8b8d64b2b9f1bab4a13f87f8ff9e1ab3e82dfb6fc547144c77b95d' @('Assert-CodeTreeOnce')){. ([scriptblock]::Create($text))}
    Initialize-FileIdentity
    $held=[Collections.Generic.List[IO.FileStream]]::new()
    try{
        $holds=@();$runtime=$null;$pins=$null;$codeTree=$null;$taskState=$null;$mode='DEFERRED';$otherDaemons=@();$presence=$null;$workers=$null;$loopbackFree=$null;$idle=$null;$proof=$null
        try{$runtime=Assert-R4InstalledBindings;$pins=Assert-StopRuntimePins $runtime}catch{$holds+=('r4 runtime is not the reviewed build: '+$_.Exception.Message)}
        # Elevated, the r4 code tree is inspected once before an r4 interpreter runs with the elevated token.
        if($script:admin){try{$null=Assert-CodeTreeOnce $script:r4Root;$codeTree=$true}catch{$codeTree=$false;$holds+=('r4 code tree inspection: '+$_.Exception.Message)}}
        $r4Trusted=($null -ne $pins) -and (-not $script:admin -or $codeTree -eq $true)
        $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect();$folder=$scheduler.GetFolder('\')
        try{$taskState=Get-WardenTaskState $folder
            if(-not $taskState.readable){$holds+='Warden task definition is unreadable without elevation; re-read during -Apply.'}
            else{$mode=Assert-StopSource $taskState}
        }catch{$mode='REFUSED';$holds+=('Warden task: '+$_.Exception.Message)}
        try{$otherDaemons=@(Get-OtherDaemonTaskStates $folder)
            $active=@($otherDaemons|Where-Object {$_.active -eq $true}|ForEach-Object {$_.name});$deferred=@($otherDaemons|Where-Object {$_.state -eq 'ACCESS_DENIED_DEFERRED'}|ForEach-Object {$_.name})
            if($active.Count){$holds+=('Managed daemon tasks must remain stopped and disabled: '+($active -join ', '))}
            if($deferred.Count){$holds+=('Managed daemon task definitions are unreadable without elevation; re-read during -Apply: '+($deferred -join ', '))}
        }catch{$holds+=('Managed daemon tasks: '+$_.Exception.Message)}
        try{$presence=Get-ControllerPresence}catch{$holds+=('Controller presence could not be established: '+$_.Exception.Message)}
        try{$workers=Get-WorkerProcesses;Assert-NoWorkers $workers '; stop nothing, investigate.'}catch{$holds+=('Worker processes: '+$_.Exception.Message)}
        if($mode -ceq 'ALREADY_STOPPED'){
            if($null -ne $presence -and (Test-ControllerAlive $presence)){$holds+='The task is stopped but a controller process, an unclassified runtime process or the loopback port is alive; investigate.'}
            try{$loopbackFree=Test-LoopbackFree;if(-not $loopbackFree){$holds+='The task is stopped but the controller port cannot be bound exclusively.'}}catch{$holds+=('Loopback probe: '+$_.Exception.Message)}
        }elseif(-not $ApplyRequested -and $mode -cin @('RUNNING','DEFERRED')){
            # The plan evaluates the idle predicate once, read-only; -Apply polls it (Wait-WardenIdle) inside the stop.
            if(-not $r4Trusted){$holds+='The idle predicate was not evaluated: the r4 runtime (and, elevated, its code tree) is not verified.'}
            else{
                try{$idle=Get-IdleEvidence
                    if(-not $idle.idle){$holds+=('The Warden is not idle now: '+(@($idle.reasons) -join '; ')+$(if(@($idle.offending_job_ids).Count){'; offending job ids: '+(@($idle.offending_job_ids) -join ', ')}else{''}))}
                }catch{$holds+=('Idle predicate: '+$_.Exception.Message)}
                if($script:admin -and $mode -ceq 'RUNNING' -and $null -ne $idle -and $null -ne $idle.controller -and $null -ne $presence){
                    try{$proof=Get-StopProcessProof ([int]$idle.controller.pid);Assert-OnlyProvenController $presence $proof}catch{$holds+=('Process proof: '+$_.Exception.Message)}}}
        }
        if(Test-Path -LiteralPath $script:targetRoot){$holds+='The stop root already exists for this attempt; preserve it and choose another -Attempt.'}
        $readable=($null -ne $taskState -and $taskState.readable)
        $plan=[ordered]@{schema='cochem-warden-stop-plan/1';mode='READ_ONLY_PLAN';stop_mode=$mode;attempt=$script:Attempt;task_name=$script:taskName;runtime_root=$script:r4Root;target_root=$script:targetRoot;
            r4_runtime_verified=($null -ne $pins);r4_bindings=$pins;code_tree_verified=$codeTree;task_readable=$readable;
            task_summary=$(if($readable){[ordered]@{enabled=$taskState.enabled;state=$taskState.state;instances=$taskState.instances;last_task_result=$taskState.last_task_result;action_path=$taskState.action_path;action_arguments=$taskState.action_arguments;working_directory=$taskState.action_working_directory}}else{$null});
            expected_action=[ordered]@{path=$script:r4Python;arguments=(Get-ExpectedArguments $script:commissioningConfig $script:queueR4v1);working_directory=$script:r4Root};
            other_daemon_tasks=$otherDaemons;controller_presence=$presence;
            worker_processes=$(if($null -ne $workers){[ordered]@{workers=$workers.workers;uninspectable_count=@($workers.uninspectable_processes).Count;exited_during_sweep=$workers.exited_during_sweep;authoritative=$workers.authoritative}}else{$null});
            loopback_port_free=$loopbackFree;
            idle=$(if($null -ne $idle){[ordered]@{idle=$idle.idle;reasons=$idle.reasons;offending_job_ids=$idle.offending_job_ids;errors=$idle.errors;queue_rows=$idle.queue_rows;queue_status_counts=$idle.queue_status_counts;in_progress_rows=$idle.in_progress_rows;uncleared_cleanup_rows=$idle.uncleared_cleanup_rows;routing_holds=$idle.routing_holds;controller=$idle.controller}}else{$null});
            process_proof=$proof;process_proof_note=$(if($script:admin){$null}else{'The controller process proof needs the elevated token; -Apply records it.'});
            idle_wait_seconds=$script:IdleWaitSeconds;exit_wait_seconds=$script:ExitWaitSeconds;administrator=$script:admin;holds=$holds;
            tasks_changed=0;ended=$false;disabled=$false;processes_killed=$false;observer_and_recorder_tasks_touched=$false;automatic_retry_allowed=$false}
        if(-not $ApplyRequested){$plan|ConvertTo-Json -Depth 8;return}
        if($holds.Count){throw ('The Warden stop is held. Nothing was changed: '+($holds -join ' | '))}
        $result=Invoke-StopWarden $folder $pins
        $result|ConvertTo-Json -Depth 8
    }finally{foreach($stream in $held){$stream.Dispose()}}
}

# Invocation boundary: the only top-level statement. Fixtures dot-source the functions above from the AST without running it.
Invoke-StopWardenMain -ApplyRequested ([bool]$Apply)
