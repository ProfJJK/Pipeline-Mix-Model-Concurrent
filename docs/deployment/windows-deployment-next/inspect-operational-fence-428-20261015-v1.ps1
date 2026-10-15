#Requires -Version 5.1
<# Read-only metadata export for one failed operational sitting. No provider,
   task, service, deployment, sign-in or recovery operation is executed.
   Raw logs, task arguments/XML, credentials and exception messages stay private. #>
[CmdletBinding()]
param([string]$OutputDirectory='C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next')

function Get-OpDiagnosticMember {
    param($Value,[string]$Name)
    if($null -eq $Value){return $null}
    if($Value -is [Collections.IDictionary]){if($Value.Contains($Name)){return $Value[$Name]};return $null}
    $p=$Value.PSObject.Properties[$Name];if($null -ne $p){return $p.Value};return $null
}

function Get-OpDiagnosticHash {
    param([string]$Text)
    $sha=[Security.Cryptography.SHA256]::Create()
    try{return [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text))).Replace('-','').ToLowerInvariant()}
    finally{$sha.Dispose()}
}

function Assert-OpDiagnosticPath {
    param([string]$Path)
    $part=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    while($null -ne $part){
        if($part.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Redirected diagnostic path.'}
        $part=if($part -is [IO.FileInfo]){$part.Directory}else{$part.Parent}
    }
}

function Read-OpDiagnosticRecord {
    param([string]$Path)
    $r=@{read_status='ABSENT';sha256=$null;bytes=$null;record=$null}
    try{
        if(-not (Test-Path -LiteralPath $Path -ErrorAction Stop)){return $r}
        Assert-OpDiagnosticPath $Path
        $item=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        if($item.PSIsContainer -or $item.Length -gt 1048576){$r.read_status='SIZE_REJECTED';return $r}
        $s=[IO.File]::Open($Path,'Open','Read','Read')
        try{
            $r.bytes=$s.Length
            if($s.Length -gt 1048576){$r.read_status='SIZE_REJECTED';return $r}
            $sha=[Security.Cryptography.SHA256]::Create()
            try{$r.sha256=[BitConverter]::ToString($sha.ComputeHash($s)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
            if($s.Length -eq 0){$r.read_status='EMPTY_UNSEALED';return $r}
            $s.Position=0;$reader=[IO.StreamReader]::new($s,[Text.Encoding]::UTF8,$true,4096,$true)
            try{$text=$reader.ReadToEnd()}finally{$reader.Dispose()}
            try{$r.record=$text|ConvertFrom-Json -ErrorAction Stop;$r.read_status='READ_VERIFIED'}
            catch{$r.read_status='INVALID_JSON'}
        }finally{$s.Dispose()}
    }catch{$r.read_status='READ_FAILED'}
    return $r
}

function Select-OpDiagnosticRecord {
    param($Value)
    $safe=[ordered]@{}
    $enums=@{
        schema=@('cochem-owner-admission-fence/4.2.8','cochem-owner-admission-release/4.2.8','cochem-428-offline-install/1','cochem-428-operational-owner-result/1');
        status=@('WAITING_FOR_IDLE','WRITER_FENCE_HELD','LOCK_RELEASED','FENCE_EXPIRED','FENCE_HELD_PRESERVE_EVIDENCE','ADMISSION_FENCE_HELD','STOPPED_RUNTIME_INSTALLED','HELD_PRESERVE_PARTIAL','R428_OPERATIONAL_HELD_PRESERVE_EVIDENCE');
        phase=@('preconditions','offline_install','codex_preflight','admission_fence','stop_previous','release_fence','catalog_acceptance','cutover','verify_running','enable_trigger','codex_integration');
        error_type=@('OperationalError','ValueError','RuntimeError','TimeoutError','PermissionError','WindowsIsolationError','OSError','RuntimeException','PropertyNotFoundException','MethodInvocationException','UnauthorizedAccessException','InvalidOperationException','IOException');
        rollback=@('NOT_REQUIRED','PREVIOUS_RUNTIME_RESTORED_HEALTH_VERIFIED','HELD_PRESERVE_STOPPED_OR_RUNNING_STATE')}
    foreach($name in $enums.Keys){$v=Get-OpDiagnosticMember $Value $name
        if($null -ne $v){$safe[$name]=if($v -is [string] -and $v -cin $enums[$name]){$v}else{'UNRECOGNIZED'}}}
    foreach($name in @('config_sha256','request_sha256','ready_sha256','manifest_sha256','launch_manifest_sha256')){
        $v=Get-OpDiagnosticMember $Value $name;if($v -is [string] -and $v -cmatch '^[a-f0-9]{64}$'){$safe[$name]=$v}}
    foreach($pair in @(@('nonce',32),@('source_commit',40))){$v=Get-OpDiagnosticMember $Value $pair[0]
        if($v -is [string] -and $v -cmatch ('^[a-f0-9]{'+$pair[1]+'}$')){$safe[$pair[0]]=$v}}
    foreach($name in @('pid','ready_at','expires_at','database_rows_modified','verified_entries','tasks_changed','accounts_changed')){
        $v=Get-OpDiagnosticMember $Value $name
        if(($v -is [int] -or $v -is [long] -or $v -is [double]) -and $v -ge 0 -and $v -lt 1e16){$safe[$name]=$v}}
    foreach($name in @('released','lock_released','automatic_retry','activation_ready','pipeline_started','credentials_modified','existing_databases_modified','ram_modified','cutover_requested','runtime_health_verified')){
        $v=Get-OpDiagnosticMember $Value $name;if($v -is [bool]){$safe[$name]=$v}}
    $counts=Get-OpDiagnosticMember $Value 'counts'
    if($null -ne $counts){$safe.counts=[ordered]@{}
        foreach($name in @('active_leaves','active_leases','native_reservations','uncleared_containment','catalog_probes')){
            $v=Get-OpDiagnosticMember $counts $name
            if(($v -is [int] -or $v -is [long]) -and $v -ge 0 -and $v -le 2147483647){$safe.counts[$name]=$v}}}
    $frames=@(Get-OpDiagnosticMember $Value 'frames')
    if($frames.Count -le 12){$selected=@(foreach($frame in $frames){
        $name=Get-OpDiagnosticMember $frame 'function';$line=Get-OpDiagnosticMember $frame 'line'
        if($name -cin @('run','main','assert_quiescent','catalog_identity','admission_fence','Start-OpFence','Assert-OpFence','Get-OpRetainedTaskState','Open-OpProcessProof') -and
            ($line -is [int] -or $line -is [long]) -and $line -ge 1 -and $line -le 100000){@{function=$name;line=$line}}})
        if($selected.Count){$safe.frames=$selected}}
    return $safe
}

function Get-OpDiagnosticTaskProjection {
    param($Task,[string]$BaselineXml,[string]$BaselineSddl,[string]$ExpectedImage,[string]$ExpectedRoot,[string]$ExpectedArguments)
    $d=$Task.Definition;$a=if($d.Actions.Count -eq 1){$d.Actions.Item(1)}else{$null}
    $xml=[string]$Task.Xml;$sddl=[string]$Task.GetSecurityDescriptor(7)
    return @{readable=$true;state=[int]$Task.State;enabled=[bool]$Task.Enabled;instances=[int]$Task.GetInstances(0).Count;
        last_task_result=[int64]$Task.LastTaskResult;last_run_utc=([DateTime]$Task.LastRunTime).ToUniversalTime().ToString('o');
        xml_sha256=(Get-OpDiagnosticHash $xml);sddl_sha256=(Get-OpDiagnosticHash $sddl);
        xml_matches_baseline=($BaselineXml.Length -gt 0 -and $xml -ceq $BaselineXml);
        sddl_matches_baseline=($BaselineSddl.Length -gt 0 -and $sddl -ceq $BaselineSddl);
        actions=[int]$d.Actions.Count;triggers=[int]$d.Triggers.Count;system_identity=($d.Principal.UserId -cin @('SYSTEM','S-1-5-18'));
        logon_type=[int]$d.Principal.LogonType;run_level=[int]$d.Principal.RunLevel;restart_count=[int]$d.Settings.RestartCount;
        multiple_instances=[int]$d.Settings.MultipleInstances;
        action_image_matches=((Get-OpDiagnosticMember $a 'Path') -ceq $ExpectedImage);
        action_root_matches=((Get-OpDiagnosticMember $a 'WorkingDirectory') -ceq $ExpectedRoot);
        action_arguments_match=($ExpectedArguments.Length -gt 0 -and (Get-OpDiagnosticMember $a 'Arguments') -ceq $ExpectedArguments)}
}

function Get-OpDiagnosticFenceNonce {
    param([string]$Arguments,[string]$Root)
    if($Arguments.Length -gt 8192 -or -not $Arguments.StartsWith('-I -B -m cochem_pipeline.owner_admission_fence_428 ')){return $null}
    $outputs=[regex]::Matches($Arguments,'(?:^| )--output-root "([^"]+)"(?= |$)')
    $nonces=[regex]::Matches($Arguments,'(?:^| )--nonce ([a-f0-9]{32})(?= |$)')
    if($outputs.Count -ne 1 -or $nonces.Count -ne 1 -or $outputs[0].Groups[1].Value -cne $Root){return $null}
    return $nonces[0].Groups[1].Value
}

function Get-OpDiagnosticProcess {
    param($ProcessId,[string]$Config,[double]$StartedAt=0)
    if(($ProcessId -isnot [int] -and $ProcessId -isnot [long]) -or $ProcessId -le 0 -or $ProcessId -gt 2147483647){return @{status='NO_VALID_PID'}}
    try{
        $p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$ProcessId) -ErrorAction Stop
        if($null -eq $p){return @{status='PID_ABSENT';pid=$ProcessId}}
        $created=([DateTime]$p.CreationDate).ToUniversalTime()
        $epoch=([DateTimeOffset]$created).ToUnixTimeMilliseconds()/1000.0
        return @{status='PID_PRESENT';pid=$ProcessId;parent_pid=[int]$p.ParentProcessId;creation_utc=$created.ToString('o');
            python_image_matches=($p.ExecutablePath -ceq 'C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe');
            old_daemon_config_matches=([string]$p.CommandLine).Contains('daemon --config "'+$Config+'"');
            baseline_start_delta_seconds=if($StartedAt -gt 0){[Math]::Round($StartedAt-$epoch,3)}else{$null}}
    }catch{return @{status='PROCESS_READ_FAILED';pid=$ProcessId}}
}

function Get-OpDiagnosticReport {
    $sitting='C:\Program Files\CoChem\R428Operational-20261015-a62bffb278044fffbaf21207a866ff81'
    $private=Join-Path $sitting 'private';$old='C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r4'
    $new='C:\Program Files\CoChem\Pipeline4.2.8-windows-20261015-r5';$config=Join-Path $old 'pipeline.json'
    $report=[ordered]@{schema='cochem-operational-fence-diagnostic/4.2.8';observed_at_utc=[DateTime]::UtcNow.ToString('o');
        sitting_id='a62bffb278044fffbaf21207a866ff81';protected_state_modified=$false;provider_commands_executed=0;task_mutations=0;
        raw_logs_read=$false;credentials_read=$false;records=@();fences=@();tasks=@()}
    $baseline=Read-OpDiagnosticRecord (Join-Path $private 'baseline.json');$health=Get-OpDiagnosticMember $baseline.record 'health'
    $baselinePid=Get-OpDiagnosticMember $health 'pid';$started=Get-OpDiagnosticMember $health 'process_started_at'
    $report.baseline=@{read_status=$baseline.read_status;sha256=$baseline.sha256;
        config_sha256=(Get-OpDiagnosticMember (Select-OpDiagnosticRecord $baseline.record) 'config_sha256');
        process=(Get-OpDiagnosticProcess $baselinePid $config $started)}
    foreach($pair in @(@('install_after',(Join-Path $new 'install-after.json')),@('owner_result',(Join-Path $private 'owner-result.json')))){
        $r=Read-OpDiagnosticRecord $pair[1];$report.records+=@{label=$pair[0];read_status=$r.read_status;sha256=$r.sha256;bytes=$r.bytes;projection=(Select-OpDiagnosticRecord $r.record)}}
    $directories=@()
    try{Assert-OpDiagnosticPath $private
        $directories=@(Get-ChildItem -LiteralPath $private -Directory -Filter 'stop-fence-*' -ErrorAction Stop|Select-Object -First 9)
        if($directories.Count -gt 8){throw 'Fence count bound'}
        foreach($directory in $directories){
            if($directory.Name -cnotmatch '^stop-fence-[a-f0-9]{32}$'){throw 'Unexpected fence name'}
            Assert-OpDiagnosticPath $directory.FullName
            $f=@{directory=$directory.Name;records=@();processes=@()};$seen=@{}
            foreach($name in @('started.json','ready.json','held.json','release.json','result.json')){
                $r=Read-OpDiagnosticRecord (Join-Path $directory.FullName $name)
                $f.records+=@{name=$name;read_status=$r.read_status;sha256=$r.sha256;bytes=$r.bytes;projection=(Select-OpDiagnosticRecord $r.record)}
                $p=Get-OpDiagnosticMember $r.record 'pid'
                if(($p -is [int] -or $p -is [long]) -and -not $seen.ContainsKey([string]$p)){$seen[[string]$p]=$true;$f.processes+=Get-OpDiagnosticProcess $p $config}
            };$report.fences+=,$f
        }
    }catch{$report.fence_enumeration='READ_OR_BOUND_FAILED';$directories=@()}
    try{
        $scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$folder=$scheduler.GetFolder('\')
        try{$task=$folder.GetTask('CoChem-4.2.7-Warden')
            $xml=[string](Get-OpDiagnosticMember $baseline.record 'xml');$sddl=[string](Get-OpDiagnosticMember $baseline.record 'sddl')
            $expected='';if($xml.Length -gt 0){$doc=[xml]$xml;$ns=[Xml.XmlNamespaceManager]::new($doc.NameTable);$ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
                $node=$doc.SelectSingleNode('/t:Task/t:Actions/t:Exec/t:Arguments',$ns);if($null -ne $node){$expected=$node.InnerText}}
            $projection=Get-OpDiagnosticTaskProjection $task $xml $sddl (Join-Path $old '.venv\Scripts\python.exe') $old $expected
            $projection.baseline_pid_present=($report.baseline.process.status -ceq 'PID_PRESENT')
            $projection.task_last_run_before_baseline_start=if($null -ne $started){([DateTimeOffset]([DateTime]$task.LastRunTime).ToUniversalTime()).ToUnixTimeSeconds() -le [double]$started}else{$null}
            $report.tasks+=@{kind='warden';projection=$projection}
        }catch{$report.tasks+=@{kind='warden';readable=$false}}
        $tasks=$folder.GetTasks(1);if($tasks.Count -gt 4096){throw 'Task enumeration bound'};$candidates=0
        foreach($task in $tasks){
            if([string]$task.Name -cnotmatch '^CoChem-4\.2\.8-Fence-([a-f0-9]{32})$'){continue}
            if(++$candidates -gt 64){throw 'Fence task count bound'}
            $d=$task.Definition;if($d.Actions.Count -ne 1){continue};$a=$d.Actions.Item(1)
            foreach($directory in $directories){$nonce=Get-OpDiagnosticFenceNonce ([string]$a.Arguments) $directory.FullName
                if($null -eq $nonce -or [string]$task.Name -cne ('CoChem-4.2.8-Fence-'+$nonce)){continue}
                $report.tasks+=@{kind='fence';nonce=$nonce;directory=$directory.Name;
                    projection=(Get-OpDiagnosticTaskProjection $task '' '' (Join-Path $new '.venv\Scripts\python.exe') $new ([string]$a.Arguments))}
            }
        }
    }catch{$report.task_inspection='READ_OR_BOUND_FAILED'}
    try{$listeners=@(Get-NetTCPConnection -LocalPort 47824 -State Listen -ErrorAction SilentlyContinue|Select-Object -First 9)
        $report.listener=@{count=$listeners.Count;within_bound=($listeners.Count -le 8);baseline_pid_owns_all=($listeners.Count -gt 0 -and @($listeners|Where-Object{$_.OwningProcess -ne $baselinePid}).Count -eq 0)}}
    catch{$report.listener=@{readable=$false}}
    return $report
}

function Invoke-OpDiagnostic {
    param([string]$Directory)
    $destination='C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next'
    if([IO.Path]::GetFullPath($Directory) -cne $destination -or -not (Test-Path -LiteralPath $destination -PathType Container)){throw 'Use the existing ordinary deployment workspace.'}
    Assert-OpDiagnosticPath $destination
    $report=Get-OpDiagnosticReport
    $path=Join-Path $destination ('operational-fence-428-diagnostic-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffff')+'-'+[Guid]::NewGuid().ToString('N')+'.json')
    $data=[Text.UTF8Encoding]::new($false).GetBytes(($report|ConvertTo-Json -Depth 14))
    $s=[IO.File]::Open($path,'CreateNew','Write','Read')
    try{$s.Write($data,0,$data.Length);$s.Flush($true)}finally{$s.Dispose()}
    @{status='SANITIZED_READ_ONLY_DIAGNOSTIC_SAVED';report_path=$path;protected_state_modified=$false;provider_commands_executed=0;task_mutations=0}|ConvertTo-Json -Compress
}

$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
Invoke-OpDiagnostic $OutputDirectory
