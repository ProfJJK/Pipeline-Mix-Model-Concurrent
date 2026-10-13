#Requires -Version 5.1
<# Read-only export of the exact 2026-10-13 09:34 R6 native hold and R4 v9
   restoration. No provider, task, daemon, sign-in, cleanup or deployment is
   executed. Existing native output is reduced to protocol flags/counts; no
   output text, prompt, session ID, credential or URL is exported. #>
[CmdletBinding()]
param([string]$OutputDirectory='C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next')

function Get-NativeHoldMember {
    param($Value,[string]$Name)
    if($null -eq $Value){return $null}
    if($Value -is [Collections.IDictionary]){if($Value.Contains($Name)){return $Value[$Name]};return $null}
    $property=$Value.PSObject.Properties[$Name]
    if($null -ne $property){return $property.Value}
    return $null
}

function Read-NativeHoldFile {
    param([string]$Path,[int]$Maximum=4194304,[switch]$Text)
    if(-not (Test-Path -LiteralPath $Path)){return @{present=$false}}
    $item=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if($item.PSIsContainer -or $item.Length -gt $Maximum){throw 'Diagnostic file exceeds its ordinary-file bound.'}
    $part=$item
    while($null -ne $part){
        if($part.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Diagnostic path is redirected.'}
        $part=if($part -is [IO.FileInfo]){$part.Directory}else{$part.Parent}}
    $stream=[IO.File]::Open($Path,'Open','Read','Read')
    try{
        if($stream.Length -gt $Maximum){throw 'Diagnostic file grew beyond its bound.'}
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$hash=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        $length=$stream.Length;$stream.Position=0
        $reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true,4096,$true)
        try{$content=$reader.ReadToEnd()}finally{$reader.Dispose()}
        $record=if($Text){$content}else{$content|ConvertFrom-Json}
        return @{present=$true;sha256=$hash;bytes=$length;value=$record}
    }finally{$stream.Dispose()}
}

function Select-NativeHoldRecord {
    param($Value)
    $safe=[ordered]@{}
    $enums=@{
        schema=@('cochem-r6-system-phase/1','cochem-r6-native-acceptance/1','cochem-native-failure-metadata/1',
            'cochem-warden-start-intent/3','cochem-warden-start/3','cochem-warden-start-held/3',
            'cochem-warden-retarget/3','cochem-warden-retarget-intent/3','cochem-r6-launch-result/1');
        status=@('PHASE_COMPLETED','HELD_PRESERVE_PARTIAL','HELD_PRESERVE_EVIDENCE',
            'WARDEN_R4_RESTARTED_HEALTH_VERIFIED','WARDEN_RETARGETED_TO_R4_NOT_STARTED','WARDEN_START_HELD',
            'SIX_WORKER_AGENT_CUSTODY_VERIFIED','SIX_WORKER_CUSTODY_VERIFIED',
            'EXISTING_KNOWLEDGE_AUTHORITY_VERIFIED','ALL_SESSIONS_VERIFIED');
        phase=@('auth','knowledge','agent','native','preview');target=@('r4','r6');attempt=@('v8','v9');
        error_type=@('ProviderFailure','ValueError','RuntimeError','WindowsIsolationError','OSError','PermissionError',
            'TimeoutError','RuntimeException','PropertyNotFoundException','UnauthorizedAccessException');
        category=@('compatibility','protocol','code','auth','quota','busy','provider','resource','timeout','unknown','configuration');
        envelope_kind=@('none','agy_identity','agy_tool_registry','agy_error','claude_result','claude_api_error');
        stage=@('BEFORE_RUN','RUN','HEALTH_WAIT','POST_START_READBACK','TRIGGER_ENABLE','RECEIPT')}
    foreach($name in $enums.Keys){
        $v=Get-NativeHoldMember $Value $name
        if($null -ne $v){$safe[$name]=if($v -is [string] -and $v -cin $enums[$name]){$v}else{'UNRECOGNIZED'}}}
    $phase=Get-NativeHoldMember $Value 'phase'
    if($phase -is [string] -and $phase -cmatch '^target-[0-9]{2}$'){$safe.phase=$phase}
    foreach($name in @('manifest_sha256','candidate_sha256','native_plan_sha256','stdout_sha256','stderr_sha256',
        'retarget_receipt_sha256','receipt_sha256','helper_sha256')){
        $v=Get-NativeHoldMember $Value $name
        if($v -is [string] -and $v -cmatch '^[a-f0-9]{64}$'){$safe[$name]=$v}}
    foreach($name in @('completed','exit_code','stdout_bytes','stderr_bytes','started_at','finished_at',
        'task_state','running_instances','last_task_result','last_health_pid','health_samples')){
        $v=Get-NativeHoldMember $Value $name
        if($v -is [int] -or $v -is [long] -or $v -is [double]){if($v -ge 0 -and $v -lt 1e16){$safe[$name]=$v}}}
    foreach($name in @('automatic_retry','automatic_retry_allowed','late_prompt','activation_ready','cutover_requested',
        'enabled_before','enabled_after','exactly_one_start','exactly_one_start_requested','run_requested',
        'held_before_run','enable_requested','health_gate_passed','stop_recovery_allowed','interrupted',
        'disable_attempted','task_readable','receipt_written','controller_preserved','requires_reviewed_recovery',
        'started','enable_before_run','retry')){
        $v=Get-NativeHoldMember $Value $name
        if($v -is [bool]){$safe[$name]=$v}}
    $child=Get-NativeHoldMember $Value 'result'
    if($null -ne $child){
        $safe.result_status=Get-NativeHoldMember (Select-NativeHoldRecord @{status=(Get-NativeHoldMember $child 'status')}) 'status'}
    $reason=Get-NativeHoldMember $Value 'reason'
    if($reason -is [string]){
        $safe.reason_markers=[ordered]@{}
        foreach($marker in @('post-start readiness not met','knowledge is not ready',
            'does not admit work yet','execution quarantine','task instance ended',
            'property','Access','interrupted','could not be read back','identity changed')){
            $safe.reason_markers[$marker]=$reason.Contains($marker)}}
    return $safe
}

function Get-NativeHoldProtocol {
    param([string]$Stdout,[string]$Stderr,[string]$Expected)
    if($Expected -cnotin @('gemini-3.8-flash-low','gemini-3.8-flash-medium','gemini-3.8-flash-high')){
        throw 'Only the reviewed Flash binding may be inspected.'}
    $safe=[ordered]@{json_valid=$false;expected_model=$Expected;events=0;init_model='ABSENT';terminal_model='ABSENT';
        init_tools_present=$false;init_tools_empty_array=$false;init_tools_count=$null;tool_steps=0;
        model_mismatches=0;model_collection_mismatches=0;reroute_members=0;session_matches=$false;
        event_order_matches=$false;terminal_success=$false;one_turn=$false}
    # Match the installed parser's removal of terminal styling before marker scanning.
    $Stderr=[regex]::Replace($Stderr,'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]','')
    $markers=[ordered]@{}
    foreach($marker in @('AGY_ERROR:','is no longer available. Using','Model resolved via','Restored session model',
        'resolves to a different model','defaulting to','Restoring model')){$markers[$marker]=$Stderr.Contains($marker)}
    $safe.stderr_markers=$markers
    try{
        $lines=@($Stdout -split "`n"|Where-Object {$_.Trim()})
        if($lines.Count -lt 2 -or $lines.Count -gt 32768){return $safe}
        $events=@(foreach($line in $lines){$line|ConvertFrom-Json -ErrorAction Stop})
        $safe.events=$events.Count;$safe.json_valid=$true
        $safe.event_order_matches=((Get-NativeHoldMember $events[0] 'event') -ceq 'init' -and
            (Get-NativeHoldMember $events[-1] 'event') -ceq 'result')
        $init=Get-NativeHoldMember $events[0] 'init';$terminal=Get-NativeHoldMember $events[-1] 'result'
        foreach($pair in @(@{name='init_model';record=$init},@{name='terminal_model';record=$terminal})){
            $model=Get-NativeHoldMember $pair.record 'model'
            if($null -ne $model){$safe[$pair.name]=if($model -ceq $Expected){'EXPECTED'}elseif($model -ceq 'gemini-3.8-flash'){'CANONICAL_FLASH_WITHOUT_EFFORT'}else{'OTHER_VALUE'}}}
        $tools=Get-NativeHoldMember $init 'tools'
        $safe.init_tools_present=($null -ne $tools)
        # Empty arrays can be unrolled to null by PowerShell: read the property directly.
        if($null -ne $init -and $null -ne $init.PSObject.Properties['tools']){
            $safe.init_tools_present=$true;$tools=$init.PSObject.Properties['tools'].Value
            if($tools -is [array]){$safe.init_tools_count=$tools.Count;$safe.init_tools_empty_array=($tools.Count -eq 0)}}
        $session=Get-NativeHoldMember $events[0] 'conversation_id'
        $safe.session_matches=($session -is [string] -and $session.Length -gt 0 -and
            (Get-NativeHoldMember $terminal 'conversation_id') -ceq $session)
        $safe.terminal_success=((Get-NativeHoldMember $terminal 'status') -ceq 'SUCCESS')
        $turns=Get-NativeHoldMember $terminal 'num_turns'
        $safe.one_turn=($turns -is [int] -and $turns -eq 1)
        $queue=[Collections.Generic.Queue[object]]::new();foreach($event in $events){$queue.Enqueue(@{value=$event;depth=0})}
        $visited=0
        while($queue.Count){
            if(++$visited -gt 100000){throw 'Projection bound'}
            $node=$queue.Dequeue();$value=$node.value
            if($node.depth -gt 32){throw 'Projection depth'}
            if($value -is [array]){foreach($item in $value){if($null -ne $item){$queue.Enqueue(@{value=$item;depth=($node.depth+1)})}}}
            elseif($value -is [pscustomobject]){
                foreach($property in $value.PSObject.Properties){
                    $name=($property.Name.ToLowerInvariant() -replace '[^a-z0-9]','');$v=$property.Value
                    if($name -in @('model','selectedmodel','modelid','modelname','modelversion','resolvedmodel') -and $v -cne $Expected){$safe.model_mismatches++}
                    if($name -eq 'models'){
                        $names=if($v -is [pscustomobject]){@($v.PSObject.Properties.Name)}elseif($v -is [array]){$v}elseif($v -is [string]){@($v)}elseif($v){@('__NON_NAME__')}else{@()}
                        foreach($candidate in $names){if($candidate -cne $Expected){$safe.model_collection_mismatches++}}}
                    if($v -and $name -match 'rerout|fallback|deprecat|resolved|substitut|downgrad|usednongeminimodel|capacityexhausted'){$safe.reroute_members++}
                    if($name -in @('toolname','toolinfo','subagentinfo')){$safe.tool_steps++}
                    if($null -ne $v){$queue.Enqueue(@{value=$v;depth=($node.depth+1)})}}}}
    }catch{$safe.json_valid=$false}
    return $safe
}

function Get-NativeHoldTask {
    param($Folder,[string]$Name)
    try{$task=$Folder.GetTask($Name)}catch{
        return @{readable=$false;present=$null}}
    $safe=@{readable=$true;present=$true;state=[int]$task.State;enabled=[bool]$task.Enabled;
        last_result=[long]$task.LastTaskResult;instances=@($task.GetInstances(0)).Count}
    if($Name -ceq 'CoChem-4.2.7-Warden'){
        $definition=$task.Definition;$safe.actions=[int]$definition.Actions.Count
        $safe.system_principal=([string]$definition.Principal.UserId -cin @('SYSTEM','S-1-5-18'))
        if($safe.actions -eq 1){
            $action=$definition.Actions.Item(1)
            $r4='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4'
            $safe.r4_executable=([string]$action.Path -ceq ($r4+'\.venv\Scripts\python.exe'))
            $safe.r4_working_directory=([string]$action.WorkingDirectory -ceq $r4)
        }}
    $safe
}

function Get-NativeHoldTaskFolder {
    $scheduler=New-Object -ComObject Schedule.Service;$scheduler.Connect();$scheduler.GetFolder('\')
}

function Get-NativeHoldReport {
    $base='C:\Program Files\CoChem'
    $native=Join-Path $base 'R6Acceptance4.2.7-windows-20261012-v1-native-344364d3b6434266a29c7bb61a654220'
    $restore=Join-Path $base 'WardenRetarget4.2.7-windows-20261011-r4-v9'
    $report=[ordered]@{schema='cochem-r6-native-hold-diagnostic/1';observed_at_utc=[DateTime]::UtcNow.ToString('o');
        protected_state_modified=$false;provider_commands_executed=0;task_mutations=0;credentials_read=$false;
        raw_provider_output_read=$false;raw_provider_output_published=$false;records=@();tasks=@{}}
    $paths=@((Join-Path $native 'held.json'),(Join-Path $native 'native\native-held.json'))
    foreach($entry in @('auth-91783f2dd02046cb898f5f56d6611eb1','knowledge-92f0eb26813548c3a3e63337f64e90d9','agent-85176adb54f04d4ea21eaa66a126b336')){
        $paths+=Join-Path $base ('R6Acceptance4.2.7-windows-20261012-v1-'+$entry+'\result.json')}
    foreach($name in @('retarget-receipt.json','start-intent.json','start-held.json','start-receipt.json')){$paths+=Join-Path $restore $name}
    foreach($path in $paths){
        try{$read=Read-NativeHoldFile $path
            $report.records+=@{relative=$path.Substring($base.Length+1);present=$read.present;
                sha256=(Get-NativeHoldMember $read 'sha256');projection=(Select-NativeHoldRecord (Get-NativeHoldMember $read 'value'))}}
        catch{$report.records+=@{relative=$path.Substring($base.Length+1);readable=$false;error_type='READ_FAILED'}}}
    try{
        $held=Read-NativeHoldFile (Join-Path $native 'native\native-held.json')
        $phase=Get-NativeHoldMember $held.value 'phase'
        if($held.value.schema -cne 'cochem-r6-native-acceptance/1' -or
            $phase -cnotmatch '^target-[0-9]{2}$'){throw 'Unexpected held target'}
        $reservation=Read-NativeHoldFile (Join-Path $native ('native\'+$phase+'-reservation.json'))
        $node=$reservation.value.node;$route=$node.route;$id=$node.attempt_id
        if($reservation.value.schema -cne 'cochem-r6-disposable-native-reservation/1' -or
            $id -isnot [string] -or $id -cnotmatch '^[a-f0-9]{32}$' -or $route.provider -cne 'gemini' -or $route.model -cne 'gemini-3.8-flash' -or
            $route.reasoning_effort -cnotin @('low','medium','high') -or $node.worker_slot -cnotmatch '^slot[1-6]$'){
            throw 'Unexpected probe identity'}
        $report.target=@{phase=$phase;provider='gemini';model='gemini-3.8-flash';effort=$route.reasoning_effort;
            worker=$node.worker_slot;reservation_sha256=$reservation.sha256}
        $attempt=Join-Path $native ('native\attempts\'+$id)
        $failure=Read-NativeHoldFile (Join-Path $attempt 'failure.json')
        if($failure.value.schema -cne 'cochem-native-failure-metadata/1'){throw 'Unexpected native metadata'}
        $report.native_failure=@{sha256=$failure.sha256;projection=(Select-NativeHoldRecord $failure.value)}
        $out=Read-NativeHoldFile (Join-Path $attempt 'stdout.log') 8388608 -Text
        $err=Read-NativeHoldFile (Join-Path $attempt 'stderr.log') 8388608 -Text
        $report.raw_provider_output_read=$true
        $report.protocol=Get-NativeHoldProtocol $out.value $err.value ('gemini-3.8-flash-'+$route.reasoning_effort)
        $report.stream_hashes=@{stdout=$out.sha256;stderr=$err.sha256}
        $report.stream_hashes_match_failure=($out.sha256 -ceq $failure.value.stdout_sha256 -and $err.sha256 -ceq $failure.value.stderr_sha256)
        $report.native_detail_status='PROJECTED_EXISTING_PROBE'
    }catch{$report.native_detail_status='READ_OR_BINDING_FAILED'}
    try{
        $folder=Get-NativeHoldTaskFolder
        $report.tasks.warden=Get-NativeHoldTask $folder 'CoChem-4.2.7-Warden'
        $report.tasks.native=Get-NativeHoldTask $folder 'CoChem-4.2.7-R6Acceptance-native-344364d3b6434266a29c7bb61a654220'
    }catch{$report.task_inspection='UNREADABLE'}
    return $report
}

function Invoke-NativeHoldDiagnostic {
    param([string]$Directory)
    $destination='C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next'
    if([IO.Path]::GetFullPath($Directory) -cne $destination -or -not (Test-Path -LiteralPath $destination -PathType Container)){
        throw 'Use the existing ordinary deployment workspace.'}
    $part=Get-Item -LiteralPath $destination -Force
    while($null -ne $part){
        if($part.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Diagnostic destination is redirected.'}
        $part=$part.Parent}
    $report=Get-NativeHoldReport
    $path=Join-Path $destination ('r6-native-hold-diagnostic-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffffff')+'-'+[Guid]::NewGuid().ToString('N')+'.json')
    $data=[Text.UTF8Encoding]::new($false).GetBytes(($report|ConvertTo-Json -Depth 12))
    $stream=[IO.File]::Open($path,'CreateNew','Write','Read')
    try{$stream.Write($data,0,$data.Length);$stream.Flush($true)}finally{$stream.Dispose()}
    @{status='SANITIZED_READ_ONLY_DIAGNOSTIC_SAVED';report_path=$path;protected_state_modified=$false;
        provider_commands_executed=0;task_mutations=0}|ConvertTo-Json -Compress
}

$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
Invoke-NativeHoldDiagnostic $OutputDirectory
