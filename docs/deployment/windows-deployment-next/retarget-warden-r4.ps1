#Requires -Version 5.1
<# Controlled r3 -> r4 Warden switch (v2.2, after two independent reviews and their re-reviews).
   Default is a read-only plan (elevated, the plan also probes the backup rights).
   -Apply (owner elevated): proves no controller/worker is alive (loopback port, exclusive
   bind probe by the pinned base interpreter, process scan, other managed daemon tasks),
   probes the backup rights before any namespace is consumed, captures the existing
   CoChem-4.2.7-Warden task XML and security descriptor, writes a durable intent, backs up
   the private SQLite stores (the private root is SYSTEM-only, so two independent copies are
   taken with robocopy backup semantics and must agree byte for byte: sources opened
   read-only and never by SQLite; the hash-pinned helper verifies one copy, the witness copy
   stays raw), then updates the task ACTION
   only: r4 interpreter, r4 working directory, the same preserved configuration file, and a
   fresh queue-observation directory (the daemon refuses a pre-existing one). Principal,
   settings, triggers and the private DACL are preserved and proved unchanged by an XML
   comparison outside Actions/RegistrationInfo (the Description is rewritten to name this
   retarget). A failed readback after the mutation writes retarget-held.json and a failed
   start writes start-held.json; both need a reviewed recovery, never another -Attempt.
   -Apply -Start: additionally requests exactly one Run and accepts the controller only when
   /health answers twice with a stable SYSTEM identity from the r4 root, the task shows the
   same single running instance, and the reported pid runs the expected r4 daemon command and
   owns the listening socket.
   -Apply -StartOnly: performs that single start for an already retargeted attempt
   (-StartOnly alone prints the read-only start plan).
   -Attempt vN selects the retarget namespace (root and queue directory); a consumed
   namespace is never reused. No retry, stop, delete, credential, RAM, knowledge or budget
   change ever occurs. The held supervisor observer and the resource recorder (SYSTEM tasks
   that only record) are recognised, reported and left alone; they still bind the OLD
   controller instance and need their own reviewed rebinding. #>
[CmdletBinding()]
param([switch]$Apply,[switch]$Start,[switch]$StartOnly,[ValidatePattern('^v[0-9]{1,3}$')][string]$Attempt='v1')
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
if($Start -and -not $Apply){throw '-Start is only meaningful together with -Apply.'}
if($Start -and $StartOnly){throw 'Choose -Start (retarget then start) or -StartOnly (start an already retargeted attempt), not both.'}

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

function Assert-R3Commissioning {
    # The task being retargeted was created and started once by the reviewed r3 commissioning.
    $control=Read-R3Control $script:commissioningReceipt $script:commissioningPin 1048576
    $receipt=(Read-R3Text $control)|ConvertFrom-Json
    if($receipt.schema -cne 'cochem-warden-commissioning/1' -or $receipt.status -cne 'WARDEN_RUNNING_CONTROL_PLANE_VERIFIED' -or
       $receipt.task_name -cne $script:taskName -or $receipt.runtime_root -cne $script:r3Root -or
       $receipt.config_sha256 -cne $script:configPin -or $receipt.queue_launch_output -cne $script:queueOld -or
       -not (Test-ExactBool $receipt.exactly_one_start_requested $true)){throw 'The r3 commissioning receipt does not bind the task being retargeted.'}
    $null=Read-R3Control $script:commissioningConfig $script:configPin
    [ordered]@{old_controller_pid=$receipt.controller.pid;old_controller_instance_id=$receipt.controller.instance_id;old_controller_creation_filetime=$receipt.controller.creation_filetime}
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

function Assert-RetargetSource {
    param($State)
    if(-not $State.readable){throw 'Warden task definition is unreadable.'}
    if($State.instances -ne 0 -or $State.state -notin @(1,3)){throw 'The Warden task has a running or queued instance; no retarget while a controller may be alive.'}
    if($State.user -notin @('SYSTEM','S-1-5-18') -or $State.logon_type -ne 5 -or $State.run_level -ne 1 -or $State.triggers -ne 0 -or $State.actions -ne 1 -or
       $State.multiple_instances -ne 2 -or $State.execution_time_limit -cne 'PT0S' -or $State.restart_count -ne 0 -or $State.allow_demand_start -ne $true){
        throw 'The Warden task is not the exact reviewed SYSTEM daemon definition; preserve it for review.'}
    if($State.action_type -ne 0 -or $State.action_path -cne $script:r3Python -or $State.action_working_directory -cne $script:r3Root -or
       $State.action_arguments -cne (Get-ExpectedArguments $script:commissioningConfig $script:queueOld)){
        throw 'The Warden task action differs from the pinned r3 commissioning action; preserve it for review.'}
    Assert-RegisteredTaskAcl $State.sddl
}

function Assert-RetargetedTask {
    param($State,[string]$ExpectedSddl)
    if(-not $State.readable){throw 'Retargeted task could not be read back.'}
    if($State.user -notin @('SYSTEM','S-1-5-18') -or $State.logon_type -ne 5 -or $State.run_level -ne 1 -or
       $State.triggers -ne 0 -or $State.actions -ne 1 -or $State.multiple_instances -ne 2 -or $State.execution_time_limit -cne 'PT0S' -or $State.restart_count -ne 0 -or
       $State.allow_demand_start -ne $true){throw 'Retargeted task lost its reviewed principal/settings; investigate before any start.'}
    if($State.action_type -ne 0 -or $State.action_path -cne $script:r4Python -or $State.action_working_directory -cne $script:r4Root -or
       $State.action_arguments -cne (Get-ExpectedArguments $script:commissioningConfig $script:queueNew)){throw 'Retargeted task action is not the expected r4 action.'}
    if($State.sddl -cne $ExpectedSddl){throw 'Retargeted task security descriptor changed.'}
    Assert-RegisteredTaskAcl $State.sddl
}

function Get-TaskXmlOutsideAction {
    param([string]$Xml)
    $document=[xml]$Xml;$root=$document.DocumentElement
    foreach($child in @($root.ChildNodes)){if($child.LocalName -in @('Actions','RegistrationInfo')){$null=$root.RemoveChild($child)}}
    $root.OuterXml
}

function Assert-TaskXmlOutsideActionUnchanged {
    param([string]$Before,[string]$After)
    if((Get-TaskXmlOutsideAction $Before) -cne (Get-TaskXmlOutsideAction $After)){throw 'Retargeted task XML changed outside Actions/RegistrationInfo; investigate before any start.'}
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

function Invoke-Retarget {
    param($Scheduler,$Folder,$Runtime,$Commissioning)
    $state=Get-WardenTaskState $Folder;Assert-RetargetSource $state
    Assert-OtherDaemonsIdle (Get-OtherDaemonTaskStates $Folder)
    $presence=Get-ControllerPresence
    if(Test-ControllerAlive $presence){throw 'A controller process, an unclassified runtime process or the loopback port is alive; no retarget while r3 may be running.'}
    Assert-NoWorkers (Get-WorkerProcesses) '; no retarget while work may be active.'
    if(-not (Test-LoopbackFree)){throw 'The controller port cannot be bound exclusively; a controller may be alive.'}
    if(Test-Path -LiteralPath $script:targetRoot){throw 'Retarget root already exists; preserve it and choose a new attempt.'}
    # The private root is SYSTEM-only: a probe of an existing child is refused, a missing one answers false; the attempt root above is the namespace guard.
    $queueExists=$false;try{$queueExists=[bool](Test-Path -LiteralPath $script:queueNew -ErrorAction Stop)}catch{$queueExists=$true}
    if($queueExists){throw 'The fresh queue-observation directory already exists (or its probe was refused); choose a new attempt.'}
    $null=Test-BackupCopyRights
    $null=Assert-CodeTreeOnce $script:r4Root
    New-ProtectedDirectory $script:targetRoot
    $beforeXml=Write-RegistrationControl (Join-Path $script:targetRoot 'warden-task-before.xml') $state.xml
    $beforeSddl=Write-RegistrationControl (Join-Path $script:targetRoot 'warden-task-before.sddl') $state.sddl
    $intent=[ordered]@{schema='cochem-warden-retarget-intent/2';attempt=$script:Attempt;task_name=$script:taskName;from_runtime_root=$script:r3Root;to_runtime_root=$script:r4Root;
        config_path=$script:commissioningConfig;config_sha256=$script:configPin;queue_launch_output_old=$script:queueOld;queue_launch_output_new=$script:queueNew;
        r4_install_receipt_sha256=$Runtime.install_receipt_sha256;r4_source_manifest_sha256=$Runtime.source_manifest_sha256;r4_revision_sha256=$Runtime.revision_sha256;reviewed_repair_sha256=$script:repairPin;
        old_controller=$Commissioning;observer_processes=$presence.observer_processes;task_xml_before_sha256=$beforeXml;task_sddl_before_sha256=$beforeSddl;mode='RETARGET_ACTION_ONLY';description_rewritten=$true;start_requested=$false}
    $intentHash=Write-RegistrationControl (Join-Path $script:targetRoot 'retarget-intent.json') ($intent|ConvertTo-Json -Depth 6)
    New-PrivateDirectory (Join-Path $script:targetRoot 'state-backup')
    $backup=Backup-PrivateDatabases (Join-Path $script:targetRoot 'state-backup')
    $backupHash=Write-RegistrationControl (Join-Path $script:targetRoot 'state-backup.json') ($backup|ConvertTo-Json -Depth 10)
    # Re-attest immediately before the only mutation.
    $state=Get-WardenTaskState $Folder;Assert-RetargetSource $state
    Assert-OtherDaemonsIdle (Get-OtherDaemonTaskStates $Folder)
    if(Test-ControllerAlive (Get-ControllerPresence)){throw 'A controller appeared during preparation; nothing was changed.'}
    Assert-NoWorkers (Get-WorkerProcesses) ' during preparation; nothing was changed.'
    if(-not (Test-LoopbackFree)){throw 'The controller port became busy during preparation; nothing was changed.'}
    $definition=$state.task.Definition;$action=$definition.Actions.Item(1)
    $action.Path=$script:r4Python;$action.WorkingDirectory=$script:r4Root
    $action.Arguments=Get-ExpectedArguments $script:commissioningConfig $script:queueNew
    $definition.RegistrationInfo.Description='Reviewed r4 retarget '+$script:Attempt+' (Warden telemetry leak repair) of the r3 commissioning task. No triggers/retries; preserve on any failure.'
    # TASK_UPDATE=4 on the same name with the captured private DACL; never CREATE_OR_UPDATE on a different name.
    $null=$Folder.RegisterTaskDefinition($script:taskName,$definition,4,'SYSTEM',$null,5,$state.sddl)
    # From here the task may already be changed: every failure leaves a durable record.
    $after=$null;$afterXml=$null
    try{
        $after=Get-WardenTaskState $Folder
        if($after.readable){
            $afterXml=Write-RegistrationControl (Join-Path $script:targetRoot 'warden-task-after.xml') $after.xml
            $null=Write-RegistrationControl (Join-Path $script:targetRoot 'warden-task-after.sddl') $after.sddl}
        Assert-RetargetedTask $after $state.sddl
        Assert-TaskXmlOutsideActionUnchanged $state.xml $after.xml
    }catch{
        $readable=($null -ne $after -and $after.readable)
        $heldRecord=[ordered]@{schema='cochem-warden-retarget-held/2';attempt=$script:Attempt;task_name=$script:taskName;mutation_requested=$true;readback_readable=$readable;
            readback=$(if($readable){[ordered]@{enabled=$after.enabled;state=$after.state;instances=$after.instances;action_path=$after.action_path;action_arguments=$after.action_arguments;working_directory=$after.action_working_directory;sddl=$after.sddl}}else{$null});
            reason=$_.Exception.Message;automatic_retry_allowed=$false;requires_reviewed_recovery=$true}
        $null=Write-RegistrationControl (Join-Path $script:targetRoot 'retarget-held.json') ($heldRecord|ConvertTo-Json -Depth 6)
        throw ('The retarget readback is held: '+$_.Exception.Message+' The task action may already be changed; preserve everything and review retarget-held.json. Do not retry with another -Attempt.')}
    $receipt=[ordered]@{schema='cochem-warden-retarget/2';status='WARDEN_RETARGETED_TO_R4_NOT_STARTED';attempt=$script:Attempt;task_name=$script:taskName;from_runtime_root=$script:r3Root;to_runtime_root=$script:r4Root;
        action_path=$after.action_path;action_arguments=$after.action_arguments;working_directory=$after.action_working_directory;enabled=$after.enabled;task_state=$after.state;running_instances=$after.instances;
        config_path=$script:commissioningConfig;config_sha256=$script:configPin;queue_launch_output=$script:queueNew;intent_sha256=$intentHash;state_backup_sha256=$backupHash;
        task_xml_before_sha256=$beforeXml;task_xml_after_sha256=$afterXml;sddl_preserved=$true;xml_outside_action_unchanged=$true;triggers=0;restart_count=0;
        r4_install_receipt_sha256=$Runtime.install_receipt_sha256;r4_revision_sha256=$Runtime.revision_sha256;reviewed_repair_sha256=$script:repairPin;old_controller=$Commissioning;
        observer_processes=$presence.observer_processes;started=$false;supervisor_and_recorder_rebound=$false;credentials_modified=$false;databases_modified=$false;ram_modified=$false;knowledge_rebuilt=$false}
    $receiptHash=Write-RegistrationControl (Join-Path $script:targetRoot 'retarget-receipt.json') ($receipt|ConvertTo-Json -Depth 8)
    [ordered]@{schema='cochem-warden-retarget-result/2';status=$receipt.status;attempt=$script:Attempt;receipt_path=(Join-Path $script:targetRoot 'retarget-receipt.json');receipt_sha256=$receiptHash;task_name=$script:taskName;to_runtime_root=$script:r4Root;started=$false;sddl=$state.sddl}
}

function Assert-RetargetReceipt {
    # -StartOnly: the attempt root must hold a successful retarget receipt for this exact attempt.
    $control=Read-R3Control (Join-Path $script:targetRoot 'retarget-receipt.json') '' 1048576
    $receipt=(Read-R3Text $control)|ConvertFrom-Json
    if($receipt.schema -cne 'cochem-warden-retarget/2' -or $receipt.status -cne 'WARDEN_RETARGETED_TO_R4_NOT_STARTED' -or $receipt.attempt -cne $script:Attempt -or
       $receipt.task_name -cne $script:taskName -or $receipt.to_runtime_root -cne $script:r4Root -or $receipt.queue_launch_output -cne $script:queueNew -or
       $receipt.config_sha256 -cne $script:configPin -or $receipt.reviewed_repair_sha256 -cne $script:repairPin -or -not (Test-ExactBool $receipt.sddl_preserved $true)){throw 'The retarget receipt does not bind this attempt.'}
    $sddlControl=Read-R3Control (Join-Path $script:targetRoot 'warden-task-before.sddl') '' 65536
    [ordered]@{receipt_sha256=$control.Sha256;sddl=(Read-R3Text $sddlControl)}
}

function Invoke-StartOnce {
    param($Folder,[string]$ExpectedSddl)
    $state=Get-WardenTaskState $Folder;Assert-RetargetedTask $state $ExpectedSddl
    if($state.instances -ne 0 -or $state.state -notin @(1,3)){throw 'The retargeted task already has an instance; no second start.'}
    Assert-OtherDaemonsIdle (Get-OtherDaemonTaskStates $Folder)
    if(Test-ControllerAlive (Get-ControllerPresence)){throw 'A controller is already alive; no second start.'}
    Assert-NoWorkers (Get-WorkerProcesses) '; no start while work may be active.'
    if(-not (Test-LoopbackFree)){throw 'The controller port is busy; no second start.'}
    if(Test-Path -LiteralPath (Join-Path $script:targetRoot 'start-intent.json')){throw 'A start was already requested from this attempt; preserve it, no automatic repeat.'}
    $intent=[ordered]@{schema='cochem-warden-start-intent/2';attempt=$script:Attempt;task_name=$script:taskName;runtime_root=$script:r4Root;requested_utc=[DateTime]::UtcNow.ToString('o');
        enabled_before=$state.enabled;enable_before_run=(-not $state.enabled);exactly_one_start=$true;retry=$false}
    $null=Write-RegistrationControl (Join-Path $script:targetRoot 'start-intent.json') ($intent|ConvertTo-Json -Depth 4)
    # From here a start may have happened: every failure leaves start-held.json.
    $instanceGuid=$null;$after=$null;$second=$null;$proof=$null;$failure=$null;$runRequested=$false
    try{
        $task=$state.task
        if(-not $task.Enabled){$task.Enabled=$true}
        $runRequested=$true
        $instance=$task.Run($null);$instanceGuid=[string]$instance.InstanceGuid
        $deadline=[DateTime]::UtcNow.AddSeconds($script:startWaitSeconds);$first=$null;$lastError='';$ended=$false
        do{
            Start-Sleep -Seconds 5
            try{$instance.Refresh()}catch{
                $errorItem=$_.Exception;$notRunning=$false
                while($null -ne $errorItem){if($errorItem.HResult -eq -2147216629){$notRunning=$true;break};$errorItem=$errorItem.InnerException}
                if($notRunning){$ended=$true;$lastError='the task instance ended before health answered';break}
                throw}
            $sample=Get-HealthSample
            if(-not $sample.ok){$lastError=$sample.error;continue}
            if($null -eq $first){$first=$sample.health;continue}
            if($sample.health.pid -eq $first.pid -and $sample.health.instance_id -ceq $first.instance_id -and $sample.health.process_started_at -eq $first.process_started_at){$second=$sample.health;break}
            $first=$sample.health;$lastError='controller identity changed between samples'
        }while([DateTime]::UtcNow -lt $deadline)
        $after=Get-WardenTaskState $Folder
        if($null -eq $second){throw $(if($ended){$lastError}else{('the r4 controller did not answer /health twice with a stable SYSTEM identity from the r4 root within '+$script:startWaitSeconds+' s: '+$lastError)})}
        if(-not $after.readable){throw 'the task could not be read back after the start'}
        if($after.state -ne 4 -or $after.instances -ne 1){throw 'the task does not show exactly one running instance'}
        $running=[string]$after.task.GetInstances(0).Item(1).InstanceGuid
        if($running -cne $instanceGuid){throw 'the running task instance is not the one requested here'}
        if(@($second.active).Count -ne 0){throw 'the controller reports active work immediately after start'}
        if(@($second.quarantined_slots.PSObject.Properties).Count -ne 0){throw 'the controller reports quarantined slots'}
        $proof=Get-ProcessProof ([int]$second.pid)
    }catch{$failure=$_.Exception.Message}
    if($null -ne $failure){
        if($null -eq $after -or -not $after.readable){try{$after=Get-WardenTaskState $Folder}catch{$after=$null}}
        $readable=($null -ne $after -and $after.readable)
        $held=[ordered]@{schema='cochem-warden-start-held/2';attempt=$script:Attempt;task_name=$script:taskName;run_requested=$runRequested;instance_guid=$instanceGuid;task_readable=$readable;
            task_state=$(if($readable){$after.state}else{$null});running_instances=$(if($readable){$after.instances}else{$null});last_task_result=$(if($readable){$after.last_task_result}else{$null});
            reason=$failure;automatic_retry_allowed=$false;controller_preserved=$true;requires_reviewed_recovery=$true}
        $null=Write-RegistrationControl (Join-Path $script:targetRoot 'start-held.json') ($held|ConvertTo-Json -Depth 4)
        throw ('The r4 start is held: '+$failure+'. Preserve the task, any running process and all receipts; no automatic retry or stop, and no further -Attempt without a reviewed recovery.')}
    $receipt=[ordered]@{schema='cochem-warden-start/2';status='WARDEN_R4_RUNNING_HEALTH_VERIFIED';attempt=$script:Attempt;task_name=$script:taskName;runtime_root=$script:r4Root;instance_guid=$instanceGuid;
        task_state=$after.state;running_instances=$after.instances;
        controller=[ordered]@{pid=$second.pid;instance_id=$second.instance_id;process_started_at=$second.process_started_at;source_root=$second.source_root;version=$second.version;
            admission_capacity=$(if($null -ne $second.PSObject.Properties['admission_capacity']){$second.admission_capacity}else{$null});
            knowledge_ready=$(if($null -ne $second.PSObject.Properties['knowledge']){$second.knowledge.ready}else{$null});
            trip_errors=$(if($null -ne $second.PSObject.Properties['trip_errors']){$second.trip_errors}else{$null})};
        process_proof=$proof;health_samples=2;exactly_one_start_requested=$true;automatic_retry_allowed=$false;supervisor_and_recorder_rebound=$false}
    $receiptHash=Write-RegistrationControl (Join-Path $script:targetRoot 'start-receipt.json') ($receipt|ConvertTo-Json -Depth 6)
    [ordered]@{schema='cochem-warden-start-result/2';status=$receipt.status;receipt_sha256=$receiptHash;controller=$receipt.controller;process_proof=$proof}
}

# Invocation boundary. Fixtures load the functions above without running this block.
foreach($module in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security','CimCmdlets','NetTCPIP')){Import-Module (Join-Path $PSHOME "Modules\$module\$module.psd1") -ErrorAction Stop}
if($PSVersionTable.PSEdition -ne 'Desktop' -or -not [Environment]::Is64BitProcess -or $env:COMPUTERNAME -cne 'AETHERDESK'){throw 'Use 64-bit Windows PowerShell 5.1 on AETHERDESK.'}
$identity=[Security.Principal.WindowsIdentity]::GetCurrent();$admin=[Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if($Apply -and (-not $admin -or $identity.Name -cne 'AETHERDESK\ansac')){throw '-Apply requires the owner in Administrator Windows PowerShell; nothing was changed.'}
$programFiles='C:\Program Files';$base=Join-Path $programFiles 'CoChem'
$r3Root=Join-Path $base 'Pipeline4.2.7-windows-20261007-r3';$r3Python=Join-Path $r3Root '.venv\Scripts\python.exe'
$r4Root=Join-Path $base 'Pipeline4.2.7-windows-20261009-r4';$r4Python=Join-Path $r4Root '.venv\Scripts\python.exe';$r4SourceRoot=Join-Path $r4Root '.venv\Lib'
$basePythonRoot=Join-Path $base 'Toolchain4.2.7-windows-20261006\Python312';$basePython=Join-Path $basePythonRoot 'python.exe'
# The bind probe runs the pinned base interpreter (present before r4 exists); each probe re-verifies it behind a deny-write handle.
$probePython=$basePython;$probePythonPin='d8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa'
$configPin='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
$r3ManifestPin='6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1';$r3InstallPin='3b613128192ac44a0a3d9c4b4476fb4c47541edb7563541b9bbf18f84f9a90f6'
$r3RevisionPin='309eb48d9b1c43179ae1f0784d0139357168314f8312a64fb84dbd8380d44eb4'
$r4ManifestPin='1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189';$repairPin='e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc'
$commissioningRoot=Join-Path $base 'WardenCommissioning4.2.7-windows-20261007-r3-v1';$commissioningConfig=Join-Path $commissioningRoot 'pipeline.json'
$commissioningReceipt=Join-Path $commissioningRoot 'commissioning.json';$commissioningPin='4bf82adb21852c52df8dd20c112b8df912b4813c225aa66cdfdcb272fe148bd3'
$privateRoot='C:\ProgramData\CoChemPipeline427\private'
$queueOld=Join-Path $privateRoot 'queue-commissioning-20261007-r3-v1';$queueNew=Join-Path $privateRoot ('queue-retarget-20261010-r4-'+$Attempt)
$taskName='CoChem-4.2.7-Warden';$port=47824;$clientConfig='C:\Users\ansac\CoChem427\pipeline-client-r3.json';$startWaitSeconds=240
$backupCopyFlags=@('/B')
# The two reviewed observer recorders (SYSTEM tasks that only record), matched on their pinned script paths.
$observerPattern='\\SupervisorObservation4\.2\.7-windows-20261007-r3-v1\\held-supervisor-observation-r3-v1\.py"?\s+--observe\b|\\ResourceObservation4\.2\.7-windows-20261008-r3-v4\\package\\observe_resources\.py"?\s+--run-observer\b'
$targetRoot=Join-Path $base ('WardenRetarget4.2.7-windows-20261010-r4-'+$Attempt)
$backupHelper=Join-Path $PSScriptRoot 'backup-private-databases-r4.py';$backupHelperPin='f00ad064215d1a689f1355a18da9f159b16d45699507975de957a4cb832a0f8b'
$copyHelper='C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1'
foreach($text in Import-ReviewedFunctions $copyHelper '0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b' @('Assert-NoReparseAncestors','Assert-ProtectedPath','New-CodeAcl','New-ProtectedDirectory','Initialize-FileIdentity','Open-VerifiedFile','Copy-VerifiedPayload')){. ([scriptblock]::Create($text))}
foreach($text in Import-ReviewedFunctions (Join-Path $PSScriptRoot 'check-worker-native-status-r3.ps1') '18f58ebb448d8a0c6329dd187d4a9a27fa9cbe942cd05e906bb7aabc67e787a7' @('Read-R3Control','Read-R3Text')){. ([scriptblock]::Create($text))}
foreach($text in Import-ReviewedFunctions (Join-Path $PSScriptRoot 'register-stopped-warden-r3.ps1') 'eccc593f36cbf488a54775b4343bcf3cf8b261b7cd81e5536fb7f2f18466a198' @('Assert-RegisteredTaskAcl','Write-RegistrationControl')){. ([scriptblock]::Create($text))}
foreach($text in Import-ReviewedFunctions (Join-Path $PSScriptRoot 'protected-code-inspection-v4.ps1') '5c01543cbb8b8d64b2b9f1bab4a13f87f8ff9e1ab3e82dfb6fc547144c77b95d' @('Assert-CodeTreeOnce')){. ([scriptblock]::Create($text))}
Initialize-FileIdentity
$null=Open-VerifiedFile $backupHelper $backupHelperPin (Get-Item -LiteralPath $backupHelper).Length
$held=[Collections.Generic.List[IO.FileStream]]::new()
try{
    $holds=@();$runtime=$null;$commissioning=$null;$taskState=$null;$presence=$null;$otherDaemons=@();$workers=$null;$loopbackFree=$null;$receipt=$null
    try{$runtime=Assert-R4InstalledBindings}catch{$holds+=('r4 stopped runtime is not the reviewed build (run install-stopped-runtime-r4.ps1 -Apply first): '+$_.Exception.Message)}
    try{$commissioning=Assert-R3Commissioning}catch{$holds+=('r3 commissioning receipt binding: '+$_.Exception.Message)}
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect();$folder=$scheduler.GetFolder('\')
    try{$taskState=Get-WardenTaskState $folder
        if(-not $taskState.readable){$holds+='Warden task definition is unreadable without elevation; re-read during -Apply.'}
        elseif($StartOnly){Assert-RetargetedTask $taskState ((Assert-RetargetReceipt).sddl)}
        else{Assert-RetargetSource $taskState}
    }catch{$holds+=('Warden task: '+$_.Exception.Message)}
    try{$otherDaemons=@(Get-OtherDaemonTaskStates $folder)
        $active=@($otherDaemons|Where-Object {$_.active -eq $true}|ForEach-Object {$_.name});$deferred=@($otherDaemons|Where-Object {$_.state -eq 'ACCESS_DENIED_DEFERRED'}|ForEach-Object {$_.name})
        if($active.Count){$holds+=('Managed daemon tasks must remain stopped and disabled: '+($active -join ', '))}
        if($deferred.Count){$holds+=('Managed daemon task definitions are unreadable without elevation; re-read during -Apply: '+($deferred -join ', '))}
    }catch{$holds+=('Managed daemon tasks: '+$_.Exception.Message)}
    try{$presence=Get-ControllerPresence
        if(Test-ControllerAlive $presence){$holds+='A controller process, an unclassified runtime process or the loopback port is alive; stop nothing, investigate.'}
        elseif(-not $admin -and $presence.uninspectable_python_processes -ne 0){$holds+=([string]$presence.uninspectable_python_processes+' python processes could not be inspected without elevation (observer recorder processes are expected); the elevated plan and run classify them.')}}
    catch{$holds+=('Controller presence could not be established: '+$_.Exception.Message)}
    try{$workers=Get-WorkerProcesses;Assert-NoWorkers $workers '; stop nothing, investigate.'}catch{$holds+=('Worker processes: '+$_.Exception.Message)}
    try{$loopbackFree=Test-LoopbackFree;if(-not $loopbackFree){$holds+='The controller port cannot be bound exclusively; a controller may be alive.'}}catch{$holds+=('Loopback probe: '+$_.Exception.Message)}
    # Elevated, the read-only plan also proves the backup rights and the readability of the SYSTEM-only root (robocopy /L writes nothing).
    $backupRights=$null;if($admin -and -not $StartOnly){try{$backupRights=Test-BackupCopyRights}catch{$holds+=('Backup copy rights: '+$_.Exception.Message)}}
    if($StartOnly){try{$receipt=Assert-RetargetReceipt}catch{$holds+=('Retarget receipt: '+$_.Exception.Message)}
        if(Test-Path -LiteralPath (Join-Path $targetRoot 'start-intent.json')){$holds+='A start was already requested from this attempt; preserve it.'}
        if(Test-Path -LiteralPath (Join-Path $targetRoot 'retarget-held.json')){$holds+='This attempt holds a retarget-held.json record; a reviewed recovery is required.'}}
    else{
        if(Test-Path -LiteralPath $targetRoot){$holds+='Retarget root already exists for this attempt; preserve it and choose another -Attempt.'}
        # A probe of an existing child of the SYSTEM-only root is refused; a missing child answers false.
        try{if(Test-Path -LiteralPath $queueNew -ErrorAction Stop){$holds+='Fresh queue-observation directory already exists; choose another -Attempt.'}}catch{$holds+='Fresh queue-observation directory probe was refused, so it exists under the SYSTEM-only root; choose another -Attempt.'}}
    # The SYSTEM-only private root answers an ordinary probe with access denied, not false.
    $privateRootReadable=$false;try{$privateRootReadable=[bool](Test-Path -LiteralPath $privateRoot -ErrorAction Stop)}catch{$privateRootReadable=$false}
    $plan=[ordered]@{schema='cochem-warden-retarget-plan/2';mode='READ_ONLY_PLAN';attempt=$Attempt;start_only=[bool]$StartOnly;task_name=$taskName;from_runtime_root=$r3Root;to_runtime_root=$r4Root;
        r4_runtime_verified=($null -ne $runtime);r3_commissioning_verified=($null -ne $commissioning);task_readable=($null -ne $taskState -and $taskState.readable);
        task_summary=$(if($null -ne $taskState -and $taskState.readable){[ordered]@{enabled=$taskState.enabled;state=$taskState.state;instances=$taskState.instances;action_path=$taskState.action_path}}else{$null});
        other_daemon_tasks=$otherDaemons;controller_presence=$presence;
        worker_processes=$(if($null -ne $workers){[ordered]@{workers=$workers.workers;uninspectable_count=@($workers.uninspectable_processes).Count;uninspectable_with_image=@($workers.uninspectable_processes|Where-Object {$_.path}|ForEach-Object {[string]$_.pid+' '+$_.name});exited_during_sweep=$workers.exited_during_sweep;authoritative=$workers.authoritative}}else{$null});
        loopback_port_free=$loopbackFree;backup_copy_rights_verified=$backupRights;private_root_readable=$privateRootReadable;private_root_note='SYSTEM-only DACL; backups use robocopy backup semantics, queue namespace is guarded by the attempt root';
        config_path=$commissioningConfig;config_sha256=$configPin;queue_launch_output_new=$queueNew;target_root=$targetRoot;backup_helper_sha256=$backupHelperPin;backup_copy_flags=$backupCopyFlags;
        administrator=$admin;holds=$holds;tasks_changed=0;started=$false;supervisor_and_recorder_rebound=$false;automatic_retry_allowed=$false}
    if(-not $Apply){$plan|ConvertTo-Json -Depth 6;return}
    if($holds.Count){throw ('Retarget is held. Nothing was changed: '+($holds -join ' | '))}
    if($StartOnly){
        $result=[ordered]@{schema='cochem-warden-retarget-result/2';status=$null;mode='START_ONLY';attempt=$Attempt;retarget_receipt_sha256=$receipt.receipt_sha256}
        $result.start=Invoke-StartOnce $folder $receipt.sddl;$result.status=$result.start.status
    }else{
        $result=Invoke-Retarget $scheduler $folder $runtime $commissioning
        if($Start){$result.start=Invoke-StartOnce $folder $result.sddl;$result.started=$true;$result.retarget_status=$result.status;$result.status=$result.start.status}
        $result.Remove('sddl')
    }
    $result|ConvertTo-Json -Depth 8
}finally{foreach($stream in $held){$stream.Dispose()}}
