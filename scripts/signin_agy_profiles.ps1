#Requires -Version 5.1
<# Standalone owner-run Agy account maintenance. No deployment, Warden stop,
   browser launching, inference or token copying. Default verifies an inert plan.
   One SYSTEM broker uses six existing identities sequentially and exclusive
   profile locks, with one small 512 MiB / 5% CPU authentication Job at a time. #>
[CmdletBinding()]
param([string]$ManifestSha256,[switch]$Apply)

function Import-SigninDefinitions {
    param([string]$Path)
    $t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$t,[ref]$e)
    if($e.Count){throw 'Pinned sign-in helper does not parse.'}
    foreach($node in $ast.EndBlock.Statements){
        if($node -is [Management.Automation.Language.FunctionDefinitionAst]){$node.Extent.Text}
    }
}

function Open-SigninManifest {
    param([string]$Directory,[string]$Expected,$Handles)
    if($Expected -cnotmatch '^[a-f0-9]{64}$'){throw 'The owner command must supply its pinned manifest digest.'}
    $controls=@(@{relative='manifest.json';sha256=$Expected;length=$null});$manifest=$null
    $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    for($i=0;$i -lt $controls.Count;$i++){
        $row=$controls[$i];$name=[string]$row.relative
        if($name -cnotmatch '^[A-Za-z0-9_-]+\.(ps1|py|json)$' -or -not $seen.Add($name)){
            throw 'The sign-in package has an unsafe or duplicate filename.'}
        $path=Join-Path $Directory $name
        $item=Get-Item -LiteralPath $path -ErrorAction Stop
        if($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.Length -gt 4194304){throw 'A package input is not a bounded ordinary file.'}
        $stream=[IO.File]::Open($path,'Open','Read','Read');$Handles.Add($stream)
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$digest=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        if($digest -cne $row.sha256 -or ($null -ne $row.length -and $stream.Length -ne $row.length)){throw ('Pinned package input differs: '+$name)}
        if($i -eq 0){
            $stream.Position=0;$reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true,4096,$true)
            try{$manifest=$reader.ReadToEnd()|ConvertFrom-Json}finally{$reader.Dispose()}
            if($manifest.schema -cne 'cochem-agy-signin-package/1' -or $manifest.host -cne 'AETHERDESK' -or
               @($manifest.files).Count -lt 10 -or @($manifest.files).Count -gt 40){throw 'Unexpected standalone sign-in manifest.'}
            $controls+=@($manifest.files)
        }
        $stream.Position=0
    }
    foreach($required in @('signin_agy_profiles.ps1','worker_agy_signin_batch.py','worker_agy_terminal_bridge.py',
        'attended_agy_terminal.py','login_pipeline_worker_agy_terminal.ps1')){
        if(-not $seen.Contains($required)){throw 'The package is incomplete.'}}
    $manifest
}

function Assert-SigninTask {
    param($Task,[string]$Name,[string]$Arguments,[string]$Root)
    Assert-RegisteredTaskAcl ([string]$Task.GetSecurityDescriptor(7))
    $d=$Task.Definition
    if($d.Actions.Count -ne 1){throw 'Sign-in task must have exactly one action.'}
    $a=$d.Actions.Item(1)
    if($Task.Name -cne $Name -or $d.Principal.UserId -cnotin @('SYSTEM','S-1-5-18') -or
        $d.Principal.LogonType -ne 5 -or $d.Principal.RunLevel -ne 1 -or $d.Triggers.Count -ne 0 -or
        $a.Type -ne 0 -or $a.Path -cne $script:python -or $a.Arguments -cne $Arguments -or $a.WorkingDirectory -cne $Root -or
        $d.Settings.MultipleInstances -ne 2 -or $d.Settings.RestartCount -ne 0 -or
        [Xml.XmlConvert]::ToTimeSpan($d.Settings.ExecutionTimeLimit).TotalSeconds -ne 1800 -or
        $d.Settings.Enabled -ne $true -or $d.Settings.AllowDemandStart -ne $true -or
        $Task.Enabled -ne $true -or $Task.State -ne 3 -or
        $Task.GetInstances(0).Count -ne 0 -or $Task.LastTaskResult -ne 267011){throw 'The fresh sign-in task definition/state differs.'}
}

function Assert-NoRunningSignins {
    param($Folder)
    # Old ended tasks/receipts stay in place. Never run, reset or delete them.
    foreach($task in @($Folder.GetTasks(1))){
        if($task.Name -cmatch '^CoChem-4\.2\.7-(InteractiveAgy|AgySignIn|NativeAuthStatus)'){
            if($task.GetInstances(0).Count -ne 0 -or $task.State -notin @(1,3)){
                throw 'An earlier profile sign-in/status task is still active; preserve it.'}
            if($task.Name -cmatch '^CoChem-4\.2\.7-AgySignIn-' -and $task.LastTaskResult -notin @(0,267011)){
                throw 'An earlier standalone broker failed; preserve its result for review before another attempt.'}
        }
    }
}

function Get-SigninFailure {
    param($ErrorRecord,[string]$Phase)
    $errorValue=$ErrorRecord.Exception;$chain=@();$line=$ErrorRecord.InvocationInfo.ScriptLineNumber
    while($null -ne $errorValue -and $chain.Count -lt 6){
        $chain+=,@{type=$errorValue.GetType().Name;hresult=[long]$errorValue.HResult}
        $errorValue=$errorValue.InnerException
    }
    @{status='HELD';phase=$Phase;line=$line;error_chain=$chain;activation_ready=$false;automatic_retry=$false}
}

function Read-SigninJson {
    param([string]$Path)
    $control=Read-R3Control $Path '' 65536
    (Read-R3Text $control)|ConvertFrom-Json
}

function Wait-SigninSlot {
    param($Instance,[string]$Root,[string]$Nonce,[DateTime]$Deadline)
    $decision=Join-Path $Root 'login-required.json';$result=Join-Path $Root 'result.json'
    $until=[DateTime]::UtcNow.AddSeconds(90)
    while(-not (Test-Path -LiteralPath $decision) -and -not (Test-Path -LiteralPath $result) -and -not (Test-InstanceComplete $Instance)){
        if([DateTime]::UtcNow -ge $until){Write-CancelRequest $Root $Nonce;throw 'The bounded sign-in status check did not finish.'}
        Start-Sleep -Milliseconds 100
    }
    if(Test-Path -LiteralPath $decision){
        $value=Read-SigninJson $decision
        if($value.nonce -cne $Nonce -or $value.decision -cne 'LOGIN_REQUIRED' -or $value.slot -cne (Split-Path $Root -Leaf)){
            throw 'Sign-in decision identity differs.'}
        Invoke-SigninConsole $Instance $Root $Nonce $Deadline
    }
    if(-not (Test-Path -LiteralPath $result)){throw 'The broker stopped before this profile produced a result.'}
    Read-SigninJson $result
}

function Invoke-SigninConsole {
    param($Instance,[string]$Root,[string]$Nonce,[DateTime]$Deadline)
    $log=Join-Path $Root 'operator.log';$closed=Join-Path $Root 'input.closed';$result=Join-Path $Root 'result.json'
    $seen=0;$ready=$false;$state=New-ClaudeCodeInput;$submittedAt=$null
    try{
        $null=Clear-ClaudeConsoleInput
        while(-not (Test-Path -LiteralPath $result) -and -not (Test-InstanceComplete $Instance)){
            if(-not $state.Submitted -and [DateTime]::UtcNow -ge $Deadline){
                Write-CancelRequest $Root $Nonce;throw 'The initial input window expired; no late sign-in is requested.'}
            if($state.Submitted -and [DateTime]::UtcNow -ge $submittedAt.AddSeconds(180)){
                Write-CancelRequest $Root $Nonce;throw 'Native completion exceeded its bound; preserve the broker task.'}
            $windowClosed=Test-Path -LiteralPath $closed
            if(-not $ready -and -not $state.Submitted -and (Test-Path -LiteralPath $log)){
                $text=Read-AgyOperatorLog $log;$at=Find-AgyCodePrompt $text
                $end=if($at -ge 0){$at}else{$text.Length-(Get-AgyPromptPrefixHold $text)}
                if($end -gt $seen){Write-AgyConsoleText ($text.Substring($seen,$end-$seen));$seen=$end}
                if($at -ge 0 -and -not $windowClosed){
                    $ready=$true;Write-Host '';Write-Host 'Open the fresh URL above yourself. Paste ONLY its returned authorization code, then Enter.'
                    [Console]::Write('Code (masked; Escape cancels): ')
                }
            }
            $count=0
            while($count -lt 256 -and (Test-AgyConsoleKeyAvailable)){
                $key=Read-AgyConsoleKey;$count++
                if($windowClosed -or $state.Submitted -or $state.Closed){continue}
                Invoke-AgyTerminalKey $state $key $ready
                if($state.CancelRequested -or $state.SubmissionRequested){break}
            }
            $key=$null
            if($state.CancelRequested){Write-CancelRequest $Root $Nonce;throw 'Sign-in cancelled; no later profile will start.'}
            if($state.SubmissionRequested -and -not $state.Submitted -and $ready -and -not $windowClosed){
                if([DateTime]::UtcNow -lt $Deadline -and -not (Test-Path -LiteralPath $closed)){
                    Write-PrivatePacket (Join-Path $Root 'input.once') $Nonce $state.Secret
                    Complete-ClaudeCodeInput -State $state;$submittedAt=[DateTime]::UtcNow
                    Write-Host '';Write-Host 'Code submitted. Verifying this profile...'
                }
            }
            Start-Sleep -Milliseconds 100
        }
    }finally{
        Close-ClaudeCodeInput -State $state
        $drained=Clear-ClaudeConsoleInput
        if(-not $drained.console_queue_clear){throw 'Console queue did not clear; no later prompt is safe.'}
    }
}

function Write-SigninPublic {
    param([string]$Root,$Value)
    # Only this sanitized file allows ordinary-user read. Standard Windows
    # bypass-traverse privilege permits its known path, not directory listing.
    $acl=New-PrivateAcl
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-5-32-545'),'Read','Allow'))
    $bytes=[Text.UTF8Encoding]::new($false).GetBytes(($Value|ConvertTo-Json -Depth 8))
    $path=Join-Path $Root 'status.json'
    $stream=[IO.FileStream]::new($path,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::Read,4096,[IO.FileOptions]::None,$acl)
    try{$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
    $path
}

function Invoke-SigninMain {
    param([string]$Directory,[string]$Expected,[bool]$ApplyRequested)
    $held=[Collections.Generic.List[IO.FileStream]]::new();$leases=@();$root=$null;$instance=$null;$task=$null;$phase='package';$rows=@()
    $began=[DateTime]::UtcNow;$deadline=$began.AddMinutes(20)
    try{
        $manifest=Open-SigninManifest $Directory $Expected $held
        if(-not $ApplyRequested){
            @{schema='cochem-agy-signin-plan/1';slots=6;system_tasks=1;native_model_jobs=0;
              browser_opened=$false;daemon_tasks_changed=$false;input_window_minutes=20;
              profile_authentication_only=$true;maximum_auth_jobs=1;memory_mb=512;cpu_percent=5;
              package_files=@($manifest.files).Count;activation_ready=$false}|ConvertTo-Json -Compress
            return
        }
        foreach($definition in @(Import-SigninDefinitions (Join-Path $Directory 'login_pipeline_worker_agy_terminal.ps1'))){. ([scriptblock]::Create($definition))}
        foreach($definition in @(Import-AgyTerminalLegacy $Directory '381fb8daec6999d16e75ab163f28d0dda6459b1b44f9695962cf43213cedcb60')){. ([scriptblock]::Create($definition))}
        Assert-AgyLoginHost $true $true
        Set-AgyLoginConstants 'slot1' 'tui' $Directory
        $script:copyHelper=Join-Path $Directory 'stage_aetherdesk_427_payloads.ps1'
        foreach($definition in @(Get-AgyLoginHelperDefinitions)){. ([scriptblock]::Create($definition))}
        Initialize-FileIdentity
        foreach($name in @('Global\CoChem427-R7OwnerSitting','Global\CoChem427-R6Launch','Global\CoChem427-AgyProfileSignIn')){
            $mutex=[Threading.Mutex]::new($false,$name);$lease=@{mutex=$mutex;owned=$false};$leases+=,$lease
            try{$lease.owned=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$lease.owned=$true}
            if(-not $lease.owned){throw 'Another owner setup/sign-in console is active. Preserve its state.'}
        }
        $phase='custody';Write-Host 'Checking the installed Agy and six profile bindings once. R4 stays running.'
        $runtime=Assert-R4InstalledBindings;Open-AgyLoginPins
        $null=Assert-CodeTreeOnce $script:installRoot;$null=Assert-CodeTreeOnce $script:basePythonRoot;$null=Assert-CodeTreeOnce $script:nativeRoot
        $connection=Connect-AgyTaskFolder
        Assert-NoRunningSignins $connection.folder
        $nonce=New-AgyLoginNonce;$root=Join-Path $script:cochemRoot ('AgySignIn427-'+$nonce)
        $taskName='CoChem-4.2.7-AgySignIn-'+$nonce
        if((Test-Path -LiteralPath $root) -or $null -ne (Get-ExactTaskOrAbsent $connection.folder $taskName)){throw 'Fresh sign-in namespace is occupied.'}
        Assert-ProtectedPath $script:cochemRoot
        $rootAcl=New-PrivateAcl -Directory
        $null=[IO.Directory]::CreateDirectory($root,$rootAcl)
        foreach($slot in 1..6){$null=[IO.Directory]::CreateDirectory((Join-Path $root ('slot'+$slot)),(New-PrivateAcl -Directory))}
        $script:sessionRoot=$root;$phase='copy';Copy-AgySessionSources
        $helpers=@{'worker_agy_login_bridge_r4_v1.py'=$script:bridgeHash;'worker_native_status_support.py'=$script:supportHash}
        foreach($name in @('worker_agy_signin_batch.py','worker_agy_terminal_bridge.py','attended_agy_terminal.py')){
            $pin=@($manifest.files|Where-Object {$_.relative -ceq $name})
            if($pin.Count -ne 1){throw 'Broker helper pin is missing.'}
            $source=Open-VerifiedFile (Join-Path $Directory $name) $pin[0].sha256 $pin[0].length
            try{
                $destination=Join-Path $root $name
                $output=[IO.FileStream]::new($destination,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,4096,[IO.FileOptions]::None,(New-PrivateAcl))
                try{$source.CopyTo($output);$output.Flush($true)}finally{$output.Dispose()}
                $held.Add((Open-VerifiedFile $destination $pin[0].sha256 $pin[0].length))
                $helpers[$name]=$pin[0].sha256
            }finally{$source.Dispose()}
        }
        $null=Write-AgySessionRecord (Join-Path $root 'helpers.json') $helpers
        $epoch=([DateTimeOffset]$deadline).ToUnixTimeSeconds().ToString([Globalization.CultureInfo]::InvariantCulture)
        $arguments='-I -B "'+(Join-Path $root 'worker_agy_signin_batch.py')+'" --nonce '+$nonce+' --deadline '+$epoch
        $definition=New-AgyLoginTaskDefinition $connection.scheduler $arguments
        $definition.Settings.ExecutionTimeLimit='PT30M'
        $phase='register'
        $task=$connection.folder.RegisterTaskDefinition($taskName,$definition,18,'SYSTEM',$null,5,$script:taskSddl)
        Assert-SigninTask $task $taskName $arguments $root
        Write-Host ('Profile sign-in starts after '+[Math]::Round(([DateTime]::UtcNow-$began).TotalSeconds,1)+' seconds of setup.')
        Write-Host 'Six profiles, in order. Open each printed URL manually; never reuse an old URL or code.'
        $phase='profiles';$instance=$task.Run($null)
        foreach($number in 1..6){
            $slot='slot'+$number;Write-Host '';Write-Host ('['+$number+'/6] Agy '+$slot)
            $row=Wait-SigninSlot $instance (Join-Path $root $slot) $nonce $deadline
            # Only these bounded fields go to public status. No provider output/account identifiers.
            $safe=@{slot=$slot;authenticated=($row.authenticated -eq $true);cleanup_verified=($row.cleanup_verified -eq $true);
                status=[string]$row.status;login_requested=($row.login_requested -eq $true)}
            foreach($key in @('error_type','winerror','reason','login_failure','frames','causes','login')){
                if($null -ne $row.PSObject.Properties[$key]){$safe[$key]=$row.$key}}
            foreach($stage in @('before','after')){
                if($null -ne $row.PSObject.Properties[$stage]){
                    $projection=@{}
                    foreach($key in @('decision','exit_code','stdout_bytes','stderr_bytes','stdout_sha256','stderr_sha256','cleanup_verified')){
                        if($null -ne $row.$stage.PSObject.Properties[$key]){$projection[$key]=$row.$stage.$key}}
                    $safe[$stage]=$projection
                }
            }
            $rows+=,$safe
            if(-not $safe.authenticated -or -not $safe.cleanup_verified){throw 'Profile sign-in did not verify. The status report contains its failure metadata.'}
            Write-Host ($slot+': '+$row.status) -ForegroundColor Green
        }
        $until=[DateTime]::UtcNow.AddSeconds(30)
        while(-not (Test-InstanceComplete $instance) -and [DateTime]::UtcNow -lt $until){Start-Sleep -Milliseconds 100}
        Assert-TaskTerminal $task
        $result=Read-SigninJson (Join-Path $root 'result.json')
        if($task.LastTaskResult -ne 0 -or $result.status -cne 'ALL_SIX_AGY_PROFILES_VERIFIED' -or $result.nonce -cne $nonce){throw 'Final broker result did not verify.'}
        $record=@{schema='cochem-agy-signin-result/1';status='ALL_SIX_AGY_PROFILES_VERIFIED';checks=$rows;root=$root;
            native_model_jobs_executed=0;daemon_tasks_changed=$false;credentials_copied=$false;activation_ready=$false}
        $record.status_path=Write-SigninPublic $root $record
        $record|ConvertTo-Json -Depth 8
    }catch{
        $record=Get-SigninFailure $_ $phase
        $record.schema='cochem-agy-signin-result/1';$record.checks=$rows;$record.root=$root
        # Let this broker consume cancellation and close its own Job; never kill
        # an unknown task or touch Warden. No new slot is requested after failure.
        try{
            if($null -ne $instance -and -not (Test-InstanceComplete $instance)){
                Write-CancelRequest $root $nonce
                foreach($number in 1..6){
                    $child=Join-Path $root ('slot'+$number)
                    if(-not (Test-Path -LiteralPath (Join-Path $child 'result.json'))){Write-CancelRequest $child $nonce}
                }
                $until=[DateTime]::UtcNow.AddSeconds(45)
                while(-not (Test-InstanceComplete $instance) -and [DateTime]::UtcNow -lt $until){Start-Sleep -Milliseconds 100}
                $record.broker_terminal=Test-InstanceComplete $instance
            }
        }catch{$record.cleanup_error=Get-SigninFailure $_ 'cleanup'}
        try{
            if($root -and (Test-Path -LiteralPath (Join-Path $root 'result.json'))){
                $broker=Read-SigninJson (Join-Path $root 'result.json')
                foreach($key in @('phase','error_type','winerror','frames','causes')){if($null -ne $broker.PSObject.Properties[$key]){$record['broker_'+$key]=$broker.$key}}
            }
        }catch{$record.receipt_error=Get-SigninFailure $_ 'receipt'}
        try{if($root -and (Test-Path -LiteralPath $root)){$record.status_path=Write-SigninPublic $root $record}}
        catch{$record.publication_error=Get-SigninFailure $_ 'publication'}
        $record|ConvertTo-Json -Depth 8
        throw 'Agy sign-in held; the printed status has the diagnostic. No deployment or Warden stop was performed.'
    }finally{
        foreach($stream in $held){$stream.Dispose()}
        [array]::Reverse($leases)
        foreach($lease in $leases){if($lease.owned){$lease.mutex.ReleaseMutex()};$lease.mutex.Dispose()}
    }
}

$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
Invoke-SigninMain $PSScriptRoot $ManifestSha256 ([bool]$Apply)
