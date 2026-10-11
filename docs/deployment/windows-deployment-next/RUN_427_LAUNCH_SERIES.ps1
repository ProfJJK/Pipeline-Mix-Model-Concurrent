#Requires -Version 5.1
<# ONE-SITTING LAUNCH SERIES for the CoChem 4.2.7 pipeline (owner, 64-bit Administrator Windows PowerShell 5.1).
   Revision 3 after two adversarial reviews: stage functions driven by an inert harness
   (test_launch_series_flow.py); the health gate pins the r4 source root; PyPI reachability and the
   attempt namespace are checked before anything is removed; a rerun after a verified start touches
   nothing but the health gate.

   What it does, in order, stopping at the first hold with a plain STOP line and a log file:
     0  Preconditions: elevated 64-bit owner token, Docker Desktop engine answering with the limits
        the controller preflight needs (read as JSON, as the daemon does), backup rights, Defender
        exclusions and the six worker directories present, controller port state consistent with
        this series' own start receipt, the attempt namespace unused, and (until r4 is built) PyPI
        reachable and the installer's own read-only plan clean, so nothing is removed if the build
        could not run.
     1  Legacy removal: unregisters the 4.1.2 host-warden and swarm tasks and the two disabled
        test fixtures, ends every legacy process, moves the Startup launcher and the
        __agentic\v4.1.2 and v4.2.0 trees into D:\__CoChem\_retired-legacy-<stamp>\ (nothing is deleted).
     2  Builds the repaired r4 runtime (reviewed installer, -Apply). Skipped if already built.
     3  Elevated read-only retarget plan; must report zero holds.
     4  Retargets the CoChem-4.2.7-Warden task to r4 and starts it exactly once (reviewed script).
     5  Health gate: the new controller must answer /health as SYSTEM from the r4 root; the admission
        state is printed.
     6  Waits for the held supervisor observer to report the new controller healthy (it rebinds
        itself; nothing is changed) and records that the old resource recorder stays retired.
   Rerun after a STOP is safe: finished stages are detected and skipped. If this series already
   started the Warden (start receipt present) and it is still listening, a rerun goes straight to
   the health gate; if it is no longer listening, the rerun stops and the agent reviews.
   It never asks a question and never waits for input. #>
[CmdletBinding()]
param([ValidatePattern('^v[0-9]{1,3}$')][string]$Attempt='v1',[switch]$SkipLegacyRemoval,[switch]$SkipObservers)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$started=Get-Date;$stamp=$started.ToString('yyyyMMdd-HHmmss');$workspace=$PSScriptRoot
$log=Join-Path $workspace ('launch-series-'+$stamp+'.log')
$psExe=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$base='C:\Program Files\CoChem';$r4Root=Join-Path $base 'Pipeline4.2.7-windows-20261009-r4';$r4Python=Join-Path $r4Root '.venv\Scripts\python.exe';$r4SourceRoot=Join-Path $r4Root '.venv\Lib'
$installer=Join-Path $workspace 'install-stopped-runtime-r4.ps1';$retarget=Join-Path $workspace 'retarget-warden-r4.ps1'
$manifest=Join-Path $workspace 'stopped-runtime-r4-source-manifest.json';$clientConfig='C:\Users\ansac\CoChem427\pipeline-client-r3.json'
$attemptRoot=Join-Path $base ('WardenRetarget4.2.7-windows-20261010-r4-'+$Attempt);$startReceipt=Join-Path $attemptRoot 'start-receipt.json'
$receiptPath=Join-Path $r4Root 'install-after.json'
$archive=Join-Path 'D:\__CoChem' ('_retired-legacy-'+$stamp)
$legacyTasks=@('CoChemHostWarden_V412','CoChem V4.1.2 Swarm','CoChem-Fixture-TaskAcl-20261008-bbd9bf8061764e6ba8cdefa47fb6a149-create18','CoChem-Fixture-TaskAcl-20261008-bbd9bf8061764e6ba8cdefa47fb6a149-create2')
$legacyTrees=@('D:\__CoChem\__agentic\v4.1.2','D:\__CoChem\__agentic\v4.2.0')
$legacyLauncher=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\cochem_startup.vbs'
$legacyProcessPattern='__CoChem\\__agentic\\v4\.(1\.2|2\.0)|cochem\.warden\.mcp_server|cochem_kanban_mcp\.py|auto_architect_mcp\.py|start_pipeline\.bat|cochem_master_loop|worker_daemon|watchdog_sre|task_work_loop|cochem_ha_daemon|cochem_startup\.vbs'
$legacyImagePattern='__CoChem\\__agentic\\v4\.(1\.2|2\.0)\\'
$dockerFields=@('OSType','MemoryLimit','SwapLimit','CpuCfsQuota','PidsLimit')
$executionImage='sha256:d9d3e8644b6fc407c7d5ee7151fcb22470d74b8c14a4e6ef8cf8e9acb62877a2'
$runtimeJson='C:\Program Files\CoChem\SupervisorObservation4.2.7-windows-20261007-r3-v1\observation-runtime.json'
$workerRoot='C:\ProgramData\CoChemPipeline427\workers'
$alreadyStarted=$false;$built=$false

function Say {param([string]$Text)Write-Host ('['+(Get-Date).ToString('HH:mm:ss')+'] '+$Text)}
function Stop-Series {param([string]$Reason)throw ('SERIES-STOP: '+$Reason)}
function Invoke-Native {param([string]$Executable,[string[]]$Arguments)
    # Judge native commands by exit code; PS 5.1 would otherwise turn stderr into errors. An
    # executable that cannot be launched is reported through the result, never thrown.
    $previous=$ErrorActionPreference;$previousEncoding=[Console]::OutputEncoding;$global:LASTEXITCODE=$null;$lines=@();$code=$null
    try{$ErrorActionPreference='Continue';try{[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)}catch{}
        $lines=@(& $Executable @Arguments 2>&1|ForEach-Object {[string]$_});$code=$global:LASTEXITCODE}
    catch{$code=$null;$lines=@('invoke failed: '+$_.Exception.Message)}
    finally{$ErrorActionPreference=$previous;try{[Console]::OutputEncoding=$previousEncoding}catch{}}
    [pscustomobject]@{code=$code;text=($lines -join "`n")}}
function Test-PackageIndex {
    # The r4 build downloads ~107 locked wheels from PyPI; prove reachability before anything is removed.
    try{[Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12}catch{}
    try{$response=Invoke-WebRequest -Uri 'https://pypi.org/simple/' -Method Head -UseBasicParsing -TimeoutSec 20 -ErrorAction Stop;return ([int]$response.StatusCode -eq 200)}catch{return $false}}
function Invoke-Reviewed {param([string]$Label,[string]$Script,[string[]]$Arguments)
    Say ('--- '+$Label);$result=Invoke-Native $script:psExe (@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$Script)+$Arguments)
    Write-Host $result.text;$result}
function Get-JsonTail {param([string]$Text)
    # The reviewed scripts print one JSON document last; skip any preamble by trying every column-0 brace.
    foreach($candidate in [regex]::Matches($Text,'(?m)^\{')){try{return ($Text.Substring($candidate.Index)|ConvertFrom-Json)}catch{}}
    $null}
function Get-LastLine {param([string]$Text)@($Text -split "`n"|Where-Object {$_.Trim()})|Select-Object -Last 1}
function Test-Elapsed {Say ('elapsed '+[int]((Get-Date)-$script:started).TotalMinutes+' min')}
function Get-ListenerCount {param([int]$Port)
    # Fail closed: only the cmdlet's own no-match error means nothing listens.
    try{return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop).Count}
    catch{if($_.FullyQualifiedErrorId -like 'CmdletizationQuery_NotFound*'){return 0};Stop-Series ('Loopback port state for '+$Port+' could not be established: '+$_.Exception.Message)}}
function Get-LegacyProcesses {
    $self=$PID;$parent=(Get-CimInstance Win32_Process -Filter ('ProcessId = '+$PID)).ParentProcessId
    @(Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne $self -and $_.ProcessId -ne $parent -and (([string]$_.CommandLine) -match $script:legacyProcessPattern -or ([string]$_.ExecutablePath) -match $script:legacyImagePattern)})}
function Assert-OwnerShell {
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    if(-not [Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or $identity.Name -cne 'AETHERDESK\ansac' -or $env:COMPUTERNAME -cne 'AETHERDESK'){
        Stop-Series 'Run this in Windows PowerShell started with "Run as administrator" as AETHERDESK\ansac.'}
    if($PSVersionTable.PSEdition -ne 'Desktop' -or -not [Environment]::Is64BitProcess){Stop-Series 'Use 64-bit Windows PowerShell 5.1: the plain "Windows PowerShell" Start entry, not "(x86)" and not PowerShell 7.'}}

function Invoke-Stage0 {
    Say 'Stage 0: preconditions'
    Assert-OwnerShell
    foreach($file in @($script:installer,$script:retarget,$script:manifest,(Join-Path $script:workspace 'backup-private-databases-r4.py'))){if(-not (Test-Path -LiteralPath $file)){Stop-Series ('Missing reviewed file: '+$file)}}
    $privileges=(Invoke-Native (Join-Path $env:SystemRoot 'System32\whoami.exe') @('/priv')).text
    if($privileges -notmatch 'SeBackupPrivilege' -or $privileges -notmatch 'SeRestorePrivilege'){Stop-Series 'The elevated token lacks SeBackupPrivilege/SeRestorePrivilege (needed for the private-store backup).'}
    # Docker: the controller preflight reads these JSON keys from `docker info` (containers.py); use the same source.
    $candidates=@('C:\Program Files\Docker\Docker\resources\bin\docker.exe');$onPath=Get-Command docker.exe -ErrorAction SilentlyContinue
    if($null -ne $onPath){$candidates+=@($onPath|ForEach-Object {[string]$_.Source})}
    $dockerExe=$null;foreach($candidate in $candidates){if($candidate -and (Test-Path -LiteralPath $candidate)){$dockerExe=$candidate;break}}
    if(-not $dockerExe){Stop-Series 'docker.exe not found; Docker Desktop must be installed and running for the controller preflight.'}
    $dockerInfo=Invoke-Native $dockerExe @('info','--format','{{json .}}')
    $infoJson=$null
    if($dockerInfo.code -eq 0){$infoLine=@($dockerInfo.text -split "`n"|Where-Object {$_.Trim().StartsWith('{')})|Select-Object -Last 1;try{if($infoLine){$infoJson=$infoLine|ConvertFrom-Json}}catch{$infoJson=$null}}
    if($null -eq $infoJson){Stop-Series ('Docker Desktop engine is not answering (docker info exit '+$dockerInfo.code+'): '+$dockerInfo.text.Trim()+'. Start Docker Desktop, wait for "Engine running", stay logged in, rerun.')}
    $dockerProblems=@()
    foreach($field in $script:dockerFields){if($null -eq $infoJson.PSObject.Properties[$field]){$dockerProblems+=($field+' missing');continue}
        $value=$infoJson.$field;$expected=$(if($field -eq 'OSType'){'linux'}else{$true})
        if(-not ($value -eq $expected)){$dockerProblems+=($field+'='+[string]$value)}}
    $securityOptions=$(if($null -ne $infoJson.PSObject.Properties['SecurityOptions']){@($infoJson.SecurityOptions)}else{@()})
    if(-not ($securityOptions|Where-Object {[string]$_ -match 'seccomp'})){$dockerProblems+='no seccomp security option'}
    if($null -eq $infoJson.PSObject.Properties['ID'] -or -not [string]$infoJson.ID){$dockerProblems+='engine ID missing'}
    if($dockerProblems.Count){Stop-Series ('Docker engine does not meet the controller preflight: '+($dockerProblems -join ', ')+'. Expected a Linux (WSL2) engine with memory, swap, CPU-quota and pids limits and seccomp.')}
    $image=Invoke-Native $dockerExe @('image','inspect',$script:executionImage,'--format','{{.Id}} {{.Os}}')
    if($image.code -ne 0 -or [string](Get-LastLine $image.text) -cne ($script:executionImage+' linux')){Stop-Series ('The allowlisted execution image is missing from the Docker engine (got: '+$image.text.Trim()+').')}
    Say 'Docker engine and execution image: ok'
    $exclusions=@((Get-MpPreference).ExclusionPath)
    $missingExclusions=@();$missingDirs=@()
    foreach($slot in 1..6){$dir=Join-Path $script:workerRoot ('slot'+$slot)
        if(-not ($exclusions|Where-Object {([string]$_).TrimEnd('\') -ieq $dir})){$missingExclusions+=$dir}
        if(-not (Test-Path -LiteralPath $dir)){$missingDirs+=$dir}}
    if($missingExclusions.Count){Stop-Series ('Defender exclusions missing for: '+($missingExclusions -join ', ')+' (the daemon refuses to start without them; this needs a reviewed fix, not a manual exclusion edit).')}
    if($missingDirs.Count){Stop-Series ('Worker directories missing: '+($missingDirs -join ', '))}
    Say 'Defender exclusions and worker directories: ok'
    # Controller port, fail closed, read together with this series' own start receipt.
    $script:alreadyStarted=[bool](Test-Path -LiteralPath $script:startReceipt)
    $busy=Get-ListenerCount 47824
    if($busy -and -not $script:alreadyStarted){Stop-Series 'Something already listens on 127.0.0.1:47824 and this series has not started a Warden; a controller may be alive. Investigate, do not kill it.'}
    if($script:alreadyStarted -and -not $busy){Stop-Series ('Attempt '+$script:Attempt+' started and verified the r4 Warden earlier ('+$script:startReceipt+') but nothing listens on 127.0.0.1:47824 now: the controller is not running. Do not start the task by hand and do not rerun; the agent reviews the attempt root.')}
    if($script:alreadyStarted){Say ('attempt '+$script:Attempt+' already started the r4 Warden and it is listening; skipping to the health gate')}
    elseif(Test-Path -LiteralPath $script:attemptRoot){Stop-Series ('Attempt root exists without a start receipt: '+$script:attemptRoot+'. Do not reuse it; the agent reviews it and names the next -Attempt.')}
    # r4 build state, and the installer's own read-only plan while a build is still ahead (nothing is removed if it could not run).
    $script:built=$false
    if(Test-Path -LiteralPath $script:receiptPath){try{$script:built=((Get-Content -LiteralPath $script:receiptPath -Raw|ConvertFrom-Json).mode -ceq 'FRESH_STOPPED_RUNTIME_READY')}catch{$script:built=$false}}
    if(-not $script:built){
        if(Test-Path -LiteralPath $script:r4Root){Stop-Series ('The r4 root exists without a successful receipt: '+$script:r4Root+'. Preserve it; the agent must review it before another build.')}
        if(-not (Test-PackageIndex)){Stop-Series 'PyPI (https://pypi.org/simple/) is not reachable; the r4 build needs it. Check the connection (and the VPN), then rerun.'}
        $manifestHash=(Get-FileHash -LiteralPath $script:manifest -Algorithm SHA256).Hash.ToLowerInvariant()
        $preflight=Invoke-Reviewed 'install-stopped-runtime-r4.ps1 read-only plan (installer preconditions; nothing changed)' $script:installer @('-Manifest',$script:manifest,'-ManifestSha256',$manifestHash)
        $preflightJson=Get-JsonTail $preflight.text
        if($preflight.code -ne 0 -or $null -eq $preflightJson -or $preflightJson.mode -cne 'READ_ONLY_PLAN'){Stop-Series 'The installer preflight did not produce a read-only plan.'}
        if(@($preflightJson.holds).Count){Stop-Series ('The installer preflight reports holds: '+(@($preflightJson.holds) -join ' | '))}
        Say 'installer preflight: clean'}
    Test-Elapsed}

function Invoke-Stage1 {
    if($script:SkipLegacyRemoval){Say 'Stage 1: legacy removal skipped by switch';return}
    if($script:alreadyStarted){Say 'Stage 1: already done by this attempt';return}
    Say 'Stage 1: legacy 4.1.2 / 4.2.0 removal'
    $null=New-Item -ItemType Directory -Path $script:archive -Force
    foreach($name in $script:legacyTasks){
        $task=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if($null -eq $task){Say ('task already absent: '+$name);continue}
        try{Export-ScheduledTask -TaskName $name | Set-Content -LiteralPath (Join-Path $script:archive (($name -replace '[^A-Za-z0-9._-]','_')+'.xml')) -Encoding Unicode}catch{Say ('  (task XML export failed: '+$_.Exception.Message+')')}
        if($task.State -eq 'Running'){Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue}
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Say ('task removed: '+$name)}
    foreach($round in 1..3){
        $victims=@(Get-LegacyProcesses)
        if(-not $victims.Count){break}
        foreach($victim in $victims){Say ('ending legacy process '+$victim.ProcessId+' '+$victim.Name+': '+([string]$victim.CommandLine).Substring(0,[Math]::Min(120,([string]$victim.CommandLine).Length)));Stop-Process -Id $victim.ProcessId -Force -ErrorAction SilentlyContinue}
        Start-Sleep -Seconds 2}
    $survivors=@(Get-LegacyProcesses)
    if($survivors.Count){Say ('WARNING: legacy processes survived the sweep: '+(($survivors|ForEach-Object {[string]$_.ProcessId+' '+$_.Name}) -join ', '))}
    if(Get-ListenerCount 47821){Stop-Series 'The legacy host warden still listens on 47821 after the sweep; investigate before continuing.'}
    if(Test-Path -LiteralPath $script:legacyLauncher){Move-Item -LiteralPath $script:legacyLauncher -Destination (Join-Path $script:archive 'cochem_startup.vbs');Say 'startup launcher moved to the archive'}
    foreach($tree in $script:legacyTrees){
        if(-not (Test-Path -LiteralPath $tree)){Say ('tree already absent: '+$tree);continue}
        try{Move-Item -LiteralPath $tree -Destination (Join-Path $script:archive (Split-Path -Leaf $tree));Say ('tree moved to the archive: '+$tree)}
        catch{Say ('WARNING: could not move '+$tree+' ('+$_.Exception.Message+'); the agent will retire it afterwards. Continuing.')}}
    Say ('legacy archive: '+$script:archive)
    Test-Elapsed}

function Invoke-Stage2 {
    Say 'Stage 2: repaired r4 runtime'
    if($script:built){Say 'r4 already built; skipping the installer'}else{
        $manifestHash=(Get-FileHash -LiteralPath $script:manifest -Algorithm SHA256).Hash.ToLowerInvariant()
        $build=Invoke-Reviewed 'install-stopped-runtime-r4.ps1 -Apply (downloads ~107 locked wheels; a few minutes)' $script:installer @('-Manifest',$script:manifest,'-ManifestSha256',$manifestHash,'-Apply')
        $buildJson=Get-JsonTail $build.text
        if($build.code -ne 0 -or $null -eq $buildJson -or $buildJson.mode -cne 'FRESH_STOPPED_RUNTIME_READY'){Stop-Series 'The r4 build did not finish with FRESH_STOPPED_RUNTIME_READY (see output above).'}
        Say 'r4 built and verified'}
    Test-Elapsed}

function Invoke-Stage3And4 {
    if($script:alreadyStarted){Say 'Stages 3-4: already done by this attempt';return}
    Say 'Stage 3: elevated read-only retarget plan'
    $plan=Invoke-Reviewed ('retarget-warden-r4.ps1 -Attempt '+$script:Attempt+' (read-only)') $script:retarget @('-Attempt',$script:Attempt)
    $planJson=Get-JsonTail $plan.text
    if($plan.code -ne 0 -or $null -eq $planJson){Stop-Series 'The retarget plan did not produce JSON.'}
    if(@($planJson.holds).Count){Stop-Series ('The elevated plan reports holds: '+(@($planJson.holds) -join ' | '))}
    if($planJson.backup_copy_rights_verified -ne $true){Stop-Series 'The plan could not verify the backup copy rights.'}
    Say 'plan: zero holds'
    Test-Elapsed
    Say 'Stage 4: retarget to r4 and single start (waits up to 240 s for health)'
    $switch=Invoke-Reviewed ('retarget-warden-r4.ps1 -Apply -Start -Attempt '+$script:Attempt) $script:retarget @('-Apply','-Start','-Attempt',$script:Attempt)
    $switchJson=Get-JsonTail $switch.text
    if($switch.code -ne 0 -or $null -eq $switchJson -or $switchJson.status -cne 'WARDEN_R4_RUNNING_HEALTH_VERIFIED'){
        Stop-Series ('The switch/start did not reach WARDEN_R4_RUNNING_HEALTH_VERIFIED. Attempt root: '+$script:attemptRoot+' (look for retarget-held.json / start-held.json). Do not retry, do not start the task by hand.')}
    Say 'r4 Warden running, health verified twice'
    Test-Elapsed}

function Invoke-Stage5 {
    Say 'Stage 5: /health from the new controller'
    $health=Invoke-Native $script:r4Python @('-I','-B','-X','utf8','-m','cochem_pipeline','health','--client-config',$script:clientConfig)
    $h=$(if($health.code -eq 0){Get-JsonTail $health.text}else{$null})
    if($null -eq $h -or $null -eq $h.PSObject.Properties['service_identity'] -or $h.service_identity -cne 'SYSTEM' -or
       $null -eq $h.PSObject.Properties['source_root'] -or [string]$h.source_root -cne $script:r4SourceRoot){
        Stop-Series ('The r4 controller did not answer /health as SYSTEM from the r4 root (exit '+$health.code+'): '+$health.text.Trim()+'. The Warden task was already started and verified by the retarget script; do not start anything, send the log.')}
    foreach($field in @('pid','instance_id','service_identity','version','admission_capacity','rss_mib','controller_rss_mib','active','quarantined_slots')){
        if($null -ne $h.PSObject.Properties[$field]){Say ('  '+$field+' = '+(($h.$field|ConvertTo-Json -Compress -Depth 3)))}}
    Say 'health: answered as SYSTEM'
    Test-Elapsed}

function Invoke-Stage6 {
    if($script:SkipObservers){Say 'Stage 6: observer check skipped by switch';return}
    Say 'Stage 6: observer recorders'
    # The held supervisor observer rebinds itself: every 10 s it reads /health and accepts any SYSTEM
    # controller whose pid/instance match the heartbeat. Only wait for it to report the new controller.
    $observerState='unknown';$deadline=(Get-Date).AddSeconds(120)
    do{
        try{$stream=[IO.File]::Open($script:runtimeJson,[IO.FileMode]::Open,[IO.FileAccess]::Read,([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
            try{$reader=[IO.StreamReader]::new($stream);$runtimeText=$reader.ReadToEnd()}finally{$stream.Dispose()}
            $observerState=$(if($runtimeText -match '"observed_controller_state"\s*:\s*"([^"]+)"'){$Matches[1]}else{'field missing'})}
        catch{$observerState='unreadable: '+$_.Exception.Message}
        if($observerState -ceq 'healthy'){break};Start-Sleep -Seconds 10
    }while((Get-Date) -lt $deadline)
    if($observerState -ceq 'healthy'){Say 'held supervisor observer reports the new controller healthy (self-rebound; nothing was changed)'}
    else{Say ('NOTE: held supervisor observer state is "'+$observerState+'" after 120 s; it keeps polling on its own and the pipeline is unaffected.')}
    Say 'resource recorder (48-hour acceptance instrument): the r3 recorder cannot bind an r4 controller by design and is left untouched; its r4 replacement is a separate reviewed build that needs no owner time until it exists.'
    Test-Elapsed}

function Invoke-Series {
    Start-Transcript -Path $script:log -Force | Out-Null
    $outcome=1
    try{
        Invoke-Stage0;Invoke-Stage1;Invoke-Stage2;Invoke-Stage3And4;Invoke-Stage5;Invoke-Stage6
        Write-Host '';Write-Host 'DONE: the 4.2.7 pipeline is running on the repaired r4 runtime.' -ForegroundColor Green
        Write-Host 'Last manual step: quit and reopen Claude Desktop and Antigravity, and start a fresh Codex/Claude Code session, so their pipeline MCP children use r4.'
        if(Test-Path -LiteralPath $script:archive){Write-Host ('Legacy archive (the agent deletes it later): '+$script:archive)}
        Write-Host ('Log: '+$script:log)
        $outcome=0
    }catch{
        $message=$_.Exception.Message
        $position=$(if($null -ne $_.InvocationInfo){[string]$_.InvocationInfo.PositionMessage}else{''})
        $reason=$(if($message.StartsWith('SERIES-STOP: ')){$message.Substring(13)}else{'Unexpected error: '+$message+' at '+$position})
        Write-Host '';Write-Host ('STOP: '+$reason) -ForegroundColor Red
        Write-Host ('Nothing after this point was changed. Log: '+$script:log);Write-Host 'Send the log to the agent; do not start anything by hand.'
    }finally{try{Stop-Transcript | Out-Null}catch{}}
    exit $outcome}

# Invocation boundary. The harness loads the functions above without running this block.
Invoke-Series
