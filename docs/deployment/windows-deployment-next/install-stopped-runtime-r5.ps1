#Requires -Version 5.1
<# Fresh code/configuration only (r5 = installed r4 + the 13 reviewed r5 source repairs).
   Never calls install_pipeline_windows.ps1. Default is metadata/hash inspection.
   -Apply requires the owner elevated. No account, credential, token, scheduled
   task, database, RAM or daemon setup. The r4 Warden may be running or down: this
   script only creates a new stopped revision root beside r4 and never touches r4's
   files, any scheduled task (the Warden task included) or state; tasks_changed is 0.
   A completed source freeze and independent review are prerequisites
   (freeze-stopped-runtime-r5-source.py; its manifest and freeze receipt).
   The r5 install-after.json keeps every r4 field name and type and only adds r5
   fields; retarget-warden-r5.ps1 binds it by content verification (sitting S11). #>
[CmdletBinding()]
param([string]$Manifest,[ValidatePattern('^[a-f0-9]{64}$')][string]$ManifestSha256,[switch]$Apply)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest

function Import-ReviewedFunctions {
    param([string]$Path,[string]$Hash,[string[]]$Names)
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try{
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$actual=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        if($actual -ne $Hash){throw 'Reviewed function source changed.'}
        $stream.Position=0;$reader=[IO.StreamReader]::new($stream,[Text.Encoding]::UTF8,$true,4096,$true)
        $tokens=$null;$errors=$null;try{$ast=[Management.Automation.Language.Parser]::ParseInput($reader.ReadToEnd(),[ref]$tokens,[ref]$errors)}finally{$reader.Dispose()}
        if($errors.Count){throw 'Reviewed helper parse failure.'}
        $found=@()
        foreach($function in $ast.FindAll({param($node)$node -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){
            if($function.Name -in $Names){$found+=$function.Name;$function.Extent.Text}}
        if(@($Names|Where-Object {$_ -notin $found}).Count){throw 'Reviewed function was not found.'}
    }finally{$stream.Dispose()}
}

function Get-OptionalMember {
    param($Object,[string]$Name)
    # One parsed-JSON member without guessing and without a StrictMode error: $null when the object or member is absent.
    if($null -eq $Object -or $Object -isnot [Management.Automation.PSCustomObject]){return $null}
    $property=$Object.PSObject.Properties[$Name]
    if($null -eq $property){return $null}
    ,$property.Value
}

function Test-SameOrdinalSet {
    param([object[]]$Items,[string[]]$Expected)
    # True when Items are unique strings forming exactly the Expected set (case-sensitive).
    $set=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach($item in @($Items)){if($item -isnot [string] -or -not $set.Add($item)){return $false}}
    $wanted=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach($item in @($Expected)){$null=$wanted.Add($item)}
    ($set.Count -eq $wanted.Count) -and $set.SetEquals($wanted)
}

function Get-RuntimeFiles {
    param($Inventory)
    if($Inventory.schema -ne 'cochem-stopped-runtime-source/1' -or $Inventory.host -ne 'AETHERDESK' -or
       $Inventory.complete_source_freeze -ne $true -or $Inventory.source_repository -cne $script:repo -or
       $Inventory.target_root -cne $script:targetRoot -or
       $Inventory.previous_source_manifest_sha256 -ne $script:priorManifestHash -or
       (Get-OptionalMember $Inventory 'previous_install_receipt_sha256') -cne $script:priorInstallHash -or
       (Get-OptionalMember $Inventory 'configuration_sha256') -cne $script:configHash -or
       -not ((Get-OptionalMember $Inventory 'configuration_unchanged') -is [bool] -and (Get-OptionalMember $Inventory 'configuration_unchanged'))){
        throw 'A complete reviewed r5 source freeze tied to the preserved r4 installation is required.'}
    $rows=@($Inventory.files)
    if($rows.Count -lt 100 -or $rows.Count -gt 10000){throw 'Unexpected source inventory size.'}
    $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase);$total=[long]0
    foreach($row in $rows){
        $key=[string]$row.relative
        if($key.Contains('\') -or $key -match '[\x00-\x1f<>:"|?*]' -or
           @($key.Split('/')|Where-Object {$_ -in @('','.','..') -or $_.EndsWith('.') -or $_.EndsWith(' ') -or $_ -match '^(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)'}).Count -or
           (-not $key.StartsWith('src/',[StringComparison]::Ordinal) -and $key -notin @('README.md','pyproject.toml','uv.lock')) -or
           $key -match '(^|/)(__pycache__|[^/]+\.egg-info)(/|$)|\.pyc$' -or -not $seen.Add($key)){
            throw 'Unsafe, unexpected or duplicate source inventory path.'}
        if([string]$row.sha256 -notmatch '^[a-f0-9]{64}$' -or [long]$row.length -lt 0 -or [long]$row.length -gt 16777216){throw 'Invalid source hash/length.'}
        $total+=[long]$row.length;if($total -gt 134217728){throw 'Source snapshot exceeds 128 MiB.'}
        [pscustomobject]@{source=(Join-Path $script:repo $key);destination=(Join-Path $script:sourceRoot $key);relative=$key;sha256=[string]$row.sha256;length=[long]$row.length}
    }
    $requiredFiles=@('README.md','pyproject.toml','uv.lock','src/cochem_pipeline/resource_telemetry.py','src/cochem_pipeline/resource_limits.py','src/cochem_pipeline/ramdisk.py','src/cochem_pipeline/deployment.py','src/cochem_pipeline/config.py','src/cochem_pipeline/deployment_revision.py','src/cochem_supervisor/engine.py')+@($script:reviewedRepairPaths)
    foreach($required in $requiredFiles){
        if(-not $seen.Contains($required)){throw 'Source inventory omits a required frozen file.'}}
}

function Test-ReviewedRepairPinsFilled {
    param($Pins)
    # True only when the pinned table names exactly the 13 reviewed paths, each with a lowercase sha256.
    if($null -eq $Pins -or $Pins -isnot [Collections.IDictionary] -or $Pins.Count -ne @($script:reviewedRepairPaths).Count){return $false}
    foreach($key in @($Pins.Keys)){if([string]$key -cnotin $script:reviewedRepairPaths){return $false}}
    foreach($relative in $script:reviewedRepairPaths){
        if(-not $Pins.Contains($relative) -or [string]$Pins[$relative] -cnotmatch '^[a-f0-9]{64}$'){return $false}}
    $true
}

function Get-ManifestRepairs {
    param($Inventory)
    # The r5 freeze adds reviewed_repairs (a list of paths) and reviewed_repairs_sha256 (path -> sha256);
    # both must name each repair exactly once, one-to-one. Returns the paths in manifest order and the map.
    $list=Get-OptionalMember $Inventory 'reviewed_repairs';$pins=Get-OptionalMember $Inventory 'reviewed_repairs_sha256'
    if($null -eq $list -or $list -isnot [Array] -or @($list).Count -lt 1 -or $null -eq $pins -or $pins -isnot [Management.Automation.PSCustomObject]){
        throw 'The r5 source manifest lacks its reviewed_repairs list and reviewed_repairs_sha256 map.'}
    $order=[Collections.Generic.List[string]]::new()
    $map=[Collections.Generic.Dictionary[string,string]]::new([StringComparer]::Ordinal)
    foreach($path in @($list)){
        if($path -isnot [string] -or $map.ContainsKey($path)){throw 'The r5 source manifest reviewed_repairs list is malformed or repeats a path.'}
        $sha=Get-OptionalMember $pins $path
        if($sha -isnot [string] -or $sha -cnotmatch '^[a-f0-9]{64}$'){throw ('The r5 source manifest has no sha256 for a reviewed repair: '+$path)}
        $order.Add($path);$map.Add($path,$sha)}
    # PSObject member lookup ignores case, so bind the map's own key spellings one-to-one as well.
    $keys=@($pins.PSObject.Properties|ForEach-Object {$_.Name})
    if($keys.Count -ne $map.Count -or @($keys|Where-Object {-not $map.ContainsKey([string]$_)}).Count){
        throw 'The r5 source manifest reviewed_repairs_sha256 map does not match its reviewed_repairs list one-to-one.'}
    [pscustomobject]@{order=[string[]]$order.ToArray();sha256=$map}
}

function Assert-ReviewedR5Delta {
    param($Inventory,$Previous,$Pins)
    # $Pins is the reviewed path->sha256 table embedded in this script; the manifest (bound by -ManifestSha256)
    # must agree with it file by file. Invoke-NewRuntimeInstallation re-asserts every pin before creating anything.
    if(-not (Test-ReviewedRepairPinsFilled $Pins)){throw 'The reviewed r5 repair sha256 pins are not filled (PIN-AFTER-COMMIT); refusing.'}
    $rows=@($Inventory.files);$prior=@($Previous.files)
    if($rows.Count -ne 166 -or $prior.Count -ne 166){throw 'The r5 snapshot must retain all 166 r4 source assets.'}
    $byName=[Collections.Generic.Dictionary[string,object]]::new([StringComparer]::Ordinal)
    foreach($row in $prior){$key=[string]$row.relative;if($byName.ContainsKey($key)){throw 'The pinned r4 manifest repeats a source asset.'};$byName.Add($key,$row)}
    $current=[Collections.Generic.Dictionary[string,object]]::new([StringComparer]::Ordinal)
    $changed=[Collections.Generic.List[string]]::new();$unchanged=0
    foreach($row in $rows){
        $key=[string]$row.relative
        if($current.ContainsKey($key)){throw 'The r5 manifest repeats a source asset.'}
        $current.Add($key,$row)
        if(-not $byName.ContainsKey($key)){throw 'A source asset was added or removed outside the reviewed r5 repairs.'}
        $before=$byName[$key]
        if([string]$row.sha256 -cne [string]$before.sha256 -or [long]$row.length -ne [long]$before.length){$changed.Add($key)}else{$unchanged++}
    }
    $expected=[string[]]@($script:reviewedRepairPaths)
    if($expected.Count -ne 13 -or -not (Test-SameOrdinalSet $expected $expected)){throw 'The installer must pin exactly the 13 reviewed r5 repair paths.'}
    if(-not (Test-SameOrdinalSet $changed.ToArray() $expected) -or $unchanged -ne $script:expectedUnchanged){
        throw 'Exactly the 13 reviewed r5 repairs may differ from r4, with every other r4 source asset verified unchanged.'}
    # The freeze's own declarations must agree with the measured delta.
    $declared=Get-OptionalMember $Inventory 'changes_from_previous_source'
    $added=Get-OptionalMember $declared 'added';$removed=Get-OptionalMember $declared 'removed';$declaredChanged=Get-OptionalMember $declared 'changed'
    if($added -isnot [Array] -or @($added).Count -ne 0 -or $removed -isnot [Array] -or @($removed).Count -ne 0 -or
       $declaredChanged -isnot [Array] -or -not (Test-SameOrdinalSet @($declaredChanged) $expected)){
        throw 'The r5 manifest must declare exactly the reviewed repairs as changed and nothing added or removed.'}
    $listed=Get-ManifestRepairs $Inventory
    if(-not (Test-SameOrdinalSet $listed.order $expected)){throw 'The r5 manifest reviewed_repairs must name exactly the 13 reviewed repairs.'}
    $declaredUnchanged=Get-OptionalMember $Inventory 'verified_unchanged'
    if(-not ((($declaredUnchanged -is [int]) -or ($declaredUnchanged -is [long])) -and [long]$declaredUnchanged -eq $script:expectedUnchanged)){
        throw 'The r5 manifest verified_unchanged count is not 153.'}
    if((Get-OptionalMember $Inventory 'source_commit') -isnot [string] -or (Get-OptionalMember $Inventory 'source_commit') -cnotmatch '^[0-9a-f]{40}$'){
        throw 'The r5 manifest does not name its full 40-hex source commit.'}
    # Records follow the manifest's reviewed_repairs order (r4 row order) so install-after.json carries it unchanged.
    foreach($relative in $listed.order){
        $row=$current[$relative]
        if($listed.sha256[$relative] -cne [string]$row.sha256){throw ('The r5 manifest reviewed_repairs_sha256 disagrees with its file row: '+$relative)}
        if([string]$Pins[$relative] -cne [string]$row.sha256){throw ('The r5 repair differs from its reviewed pin: '+$relative)}
        [pscustomobject]@{relative=$relative;sha256=[string]$row.sha256;length=[long]$row.length;line_endings=$(if($relative -cin $script:lfRepairPaths){'LF'}else{'CRLF'})}
    }
}

function Test-PureLineEndings {
    param([byte[]]$Bytes,[string]$Convention)
    # ISO-8859-1 maps each byte to one character, so these are byte counts (UTF-8 never encodes CR/LF inside a sequence).
    $text=[Text.Encoding]::GetEncoding(28591).GetString($Bytes)
    $lf=$text.Length-$text.Replace("`n",'').Length
    $cr=$text.Length-$text.Replace("`r",'').Length
    $pairs=($text.Length-$text.Replace("`r`n",'').Length)/2
    if($lf -lt 1){return $false}
    if($Convention -ceq 'LF'){return ($cr -eq 0)}
    if($Convention -ceq 'CRLF'){return ($cr -eq $lf -and $pairs -eq $lf)}
    $false
}

function Assert-RepairLineEndings {
    param([object[]]$Files,[object[]]$Repairs)
    # A6: every repair is pure in its r4 convention (LF for agy_protocol.py, CRLF for every other file),
    # read from the verified staged bytes that are copied.
    $byRelative=[Collections.Generic.Dictionary[string,object]]::new([StringComparer]::Ordinal)
    foreach($file in $Files){$byRelative[[string]$file.relative]=$file}
    foreach($repair in $Repairs){
        if(-not $byRelative.ContainsKey([string]$repair.relative)){throw 'A reviewed r5 repair is missing from the staged source.'}
        $file=$byRelative[[string]$repair.relative]
        $stream=Open-VerifiedFile $file.source $file.sha256 $file.length
        try{$buffer=[IO.MemoryStream]::new();try{$stream.CopyTo($buffer);$bytes=$buffer.ToArray()}finally{$buffer.Dispose()}}finally{$stream.Dispose()}
        if(-not (Test-PureLineEndings $bytes ([string]$repair.line_endings))){throw ('A reviewed r5 repair does not keep pure '+$repair.line_endings+' line endings: '+$repair.relative)}
    }
}

function Assert-ExactPreservedConfig {
    param([string]$Original,[string]$Candidate)
    if($Original -cne $Candidate){throw 'The r4 configuration must remain byte-for-byte equivalent to the pinned r3 configuration.'}
    $config=$Candidate|ConvertFrom-Json
    if($config.max_execution_slots -ne 4 -or @($config.workers.PSObject.Properties.Name).Count -ne 6 -or
       $config.ramdisk.workspace_subdirectory -cne 'CoChem427-windows-20261007' -or
       $config.ramdisk.mount_root -cne 'R:\') {throw 'Preserved configuration has unexpected capacity or RAM workspace.'}
}

function Assert-PreservedDenialTask {
    param($Folder)
    # Absence, access-denied and every other lookup error are failures here.
    # This reads the original failed task; it never runs, stops or changes it.
    $task=$Folder.GetTask('CoChem-4.2.7-WorkerDenial-slot1');$definition=$task.Definition
    $root='C:\Program Files\CoChem\WorkerDenial4.2.7-windows-20261006-slot1'
    if($task.State -notin @(1,3) -or $task.GetInstances(0).Count -ne 0 -or $task.LastTaskResult -ne 2 -or
       $definition.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or $definition.Principal.LogonType -ne 5 -or
       $definition.Principal.RunLevel -ne 1 -or $definition.Triggers.Count -ne 0 -or $definition.Actions.Count -ne 1){
        throw 'Original slot1 denial task must retain its exact terminal failed SYSTEM definition.'}
    $action=$definition.Actions.Item(1)
    if($action.Type -ne 0 -or $action.Path -cne 'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261006\.venv\Scripts\python.exe' -or
       $action.Arguments -cne ('-I -B "'+$root+'\worker-denial-acceptance.py" --slot slot1 --nonce 06478e2f265546cd8257aa09111373f4') -or
       $action.WorkingDirectory -cne $root){throw 'Original failed slot1 task action differs; preserve it for review.'}
}

function Read-HeldText {
    param([IO.Stream]$Stream)
    $Stream.Position=0;$reader=[IO.StreamReader]::new($Stream,[Text.UTF8Encoding]::new($false,$true),$true,4096,$true)
    try{$reader.ReadToEnd()}finally{$reader.Dispose();$Stream.Position=0}
}

function Assert-UvVenvText {
    param([string]$Text)
    $values=@{}
    foreach($line in ($Text -split "`r?`n")){
        if(-not $line.Trim()){continue}
        if($line -notmatch '^([^=]+?)\s*=\s*(.*)$'){throw 'Unexpected pyvenv record.'}
        $key=$matches[1].Trim()
        if($values.ContainsKey($key)){throw 'Duplicate pyvenv key.'}
        $values[$key]=$matches[2].Trim()
    }
    $expected=@{home=(Split-Path -Parent $script:python);implementation='CPython';uv='0.12.17';version_info='3.12.13';'include-system-site-packages'='false';prompt='cochem'}
    if($values.Count -ne $expected.Count){throw 'Expected the six-key uv venv format.'}
    foreach($key in $expected.Keys){if(-not $values.ContainsKey($key) -or $values[$key] -cne $expected[$key]){throw 'Venv interpreter/policy differs from the reviewed protected toolchain.'}}
}

function Assert-NewRuntimeInterpreter {
    param([string]$Root)
    $cfg=Join-Path $Root '.venv\pyvenv.cfg';$exe=Join-Path $Root '.venv\Scripts\python.exe'
    $cfgHash='0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d'
    $exeHash='560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'
    $cfgStream=Open-VerifiedFile $cfg $cfgHash (Get-Item -LiteralPath $cfg).Length
    try{Assert-UvVenvText (Read-HeldText $cfgStream)}finally{$cfgStream.Dispose()}
    $exeStream=Open-VerifiedFile $exe $exeHash (Get-Item -LiteralPath $exe).Length;$exeStream.Dispose()
    [pscustomobject]@{pyvenv_sha256=$cfgHash;venv_python_sha256=$exeHash;base_python_sha256='d8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa';base_root=(Split-Path -Parent $script:python)}
}

function New-ControlCopyRecords {
    param([string]$ManifestPath,[string]$ManifestHash)
    # Typed records avoid PowerShell 5.1 flattening nested singleton arrays.
    @(
        [pscustomobject]@{source=$script:oldConfig;destination=(Join-Path $script:targetRoot 'pipeline.json');sha256=$script:configHash;length=(Get-Item -LiteralPath $script:oldConfig).Length}
        [pscustomobject]@{source=$script:layout;destination=(Join-Path $script:targetRoot 'windows-layout.json');sha256=$script:layoutHash;length=(Get-Item -LiteralPath $script:layout).Length}
        [pscustomobject]@{source=$ManifestPath;destination=(Join-Path $script:targetRoot 'source-manifest.json');sha256=$ManifestHash;length=(Get-Item -LiteralPath $ManifestPath).Length}
    )
}

function Assert-PriorReceipts {
    param($Installation,$Denial)
    # The preserved r4 build: r3 + the reviewed telemetry repair, verified and never activated by this script.
    if($Installation.schema -ne 'cochem-stopped-runtime-update/1' -or $Installation.mode -ne 'FRESH_STOPPED_RUNTIME_READY' -or
       $Installation.target_root -cne $script:oldRoot -or $Installation.previous_runtime_root -cne $script:r3Root -or
       $Installation.source_manifest_sha256 -ne $script:priorManifestHash -or
       $Installation.previous_source_manifest_sha256 -ne $script:r3ManifestHash -or $Installation.previous_install_receipt_sha256 -ne $script:r3InstallHash -or
       $Installation.configuration_sha256 -ne $script:configHash -or $Installation.source_files -ne 166 -or
       $Installation.reviewed_repair -cne $script:inheritedRepair -or $Installation.reviewed_repair_sha256 -ne $script:inheritedRepairHash -or
       $Installation.tasks_changed -ne 0 -or @($Installation.holds).Count -ne 0 -or $Installation.verification.telemetry_repair_installed -ne $true -or
       $Installation.verification.revision.verified -ne $true -or $Installation.verification.revision.files -ne 109 -or
       $Installation.verification.revision.source_sha256 -ne $script:priorRevisionHash){
        throw 'The preserved r4 installation receipt differs.'}
    if($Denial.schema -ne 'cochem-worker-denial-acceptance/1' -or $Denial.status -ne 'DENIAL_CHECK_FAILED' -or
       $Denial.nonce -ne '06478e2f265546cd8257aa09111373f4' -or $Denial.slot -ne 'slot1' -or $Denial.system_sid -ne 'S-1-5-18' -or
       $Denial.failure.phase -ne 'worker_launch' -or $Denial.failure.error_type -ne 'ResourcePolicyError' -or
       $null -ne $Denial.failure.winerror -or $Denial.worker_released -ne $false -or $Denial.cleanup_verified -ne $false){
        throw 'Original failed denial receipt differs; do not treat it as accepted worker evidence.'}
}

function Get-ManagedDaemonTaskState {
    param($Folder)
    # r3 may be running. This revision only requires that no managed daemon task
    # already references the fresh r4 root; it never stops, disables or starts one.
    # SYSTEM task definitions are unreadable to an ordinary owner process, so plan
    # mode defers them with a hold; -Apply runs elevated and must read them all.
    $states=@()
    foreach($name in @('CoChem-4.2.7-Warden','CoChem-4.2.7-Supervisor','CoChem-4.2.2-Warden','CoChem-4.2.3-Supervisor')){
        $task=$null;$missing=$false;$denied=$false
        try{$task=$Folder.GetTask($name)}catch{
            $errorItem=$_.Exception
            while($null -ne $errorItem){
                if($errorItem.HResult -eq -2147024894){$missing=$true;break}
                if($errorItem.HResult -eq -2147024891){$denied=$true;break}
                $errorItem=$errorItem.InnerException}
            if(-not $missing -and -not $denied){throw 'Daemon task state is unknown.'}}
        if($denied){$states+=[pscustomobject]@{name=$name;state='ACCESS_DENIED_DEFERRED';references_new_root=$null};continue}
        if($missing){$states+=[pscustomobject]@{name=$name;state='ABSENT';references_new_root=$false};continue}
        # A task may be listable yet have an unreadable definition; map that to the same deferral.
        $references=$false;$summary=$null
        try{
            foreach($action in @($task.Definition.Actions)){
                foreach($text in @([string]$action.Path,[string]$action.Arguments,[string]$action.WorkingDirectory)){
                    if($text -and $text.IndexOf($script:targetRoot,[StringComparison]::OrdinalIgnoreCase) -ge 0){$references=$true}}}
            $summary='ENABLED='+$task.Enabled+';STATE='+$task.State+';INSTANCES='+$task.GetInstances(0).Count
        }catch{
            $errorItem=$_.Exception;$partial=$false
            while($null -ne $errorItem){if($errorItem.HResult -eq -2147024891){$partial=$true;break};$errorItem=$errorItem.InnerException}
            if(-not $partial){throw 'Daemon task definition could not be read.'}
            $states+=[pscustomobject]@{name=$name;state='ACCESS_DENIED_DEFERRED';references_new_root=$null};continue
        }
        # A reference is reported, not thrown: plan mode surfaces it as a hold and -Apply refuses.
        $states+=[pscustomobject]@{name=$name;state=$summary;references_new_root=$references}
    }
    $states
}

function Get-R5SiblingRoots {
    # retarget-warden-r5.ps1 requires exactly one Pipeline4.2.7-windows-<date>-r5 root; any other one is a hold here.
    @(Get-ChildItem -LiteralPath $script:base -Directory -Force -ErrorAction Stop|
        Where-Object {$_.Name -cmatch '^Pipeline4\.2\.7-windows-[0-9]{8}-r5$' -and $_.FullName.TrimEnd('\') -ne $script:targetRoot}|
        ForEach-Object {$_.FullName})
}

function Get-FrozenSyncArguments {
    @('--no-config','--no-cache','sync','--project',$script:sourceRoot,'--frozen','--no-editable','--link-mode','copy','--extra','mcp','--python',$script:python,'--no-python-downloads')
}

function Assert-PostBuildFrozenFiles {
    param([object[]]$Files)
    foreach($file in $Files){
        $stream=Open-VerifiedFile $file.destination $file.sha256 $file.length
        $stream.Dispose()
    }
}

function Assert-InstalledRepairs {
    param([string]$Root,[object[]]$Repairs)
    # The installed package, not only the frozen source copy, must carry every reviewed repair byte for byte;
    # retarget-warden-r5.ps1 re-hashes the same two files per repair before the cutover.
    foreach($repair in $Repairs){
        $relative=[string]$repair.relative
        if(-not $relative.StartsWith('src/',[StringComparison]::Ordinal)){throw 'A reviewed r5 repair is not a package source path.'}
        foreach($path in @((Join-Path $Root ('source\'+$relative.Replace('/','\'))),(Join-Path $Root ('.venv\Lib\site-packages\'+$relative.Substring(4).Replace('/','\'))))){
            $stream=Open-VerifiedFile $path ([string]$repair.sha256) ([long]$repair.length);$stream.Dispose()}}
}

function Write-NewRuntimeReport {
    param([string]$Path,$Value)
    Assert-ProtectedPath (Split-Path -Parent $Path)
    $stream=[IO.FileStream]::new($Path,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,4096,[IO.FileOptions]::None,(New-CodeAcl $false))
    try{$raw=[Text.UTF8Encoding]::new($false).GetBytes(($Value|ConvertTo-Json -Depth 12));$stream.Write($raw,0,$raw.Length);$stream.Flush($true)}finally{$stream.Dispose()}
}

function Write-InstallHeldRecord {
    param([string]$Stage,[string]$Message,$Plan)
    # A held record instead of a retry: the fresh root stays exactly as it is for review; nothing is cleaned or reused.
    $record=[ordered]@{schema='cochem-stopped-runtime-update-held/1';mode='HELD_FRESH_ROOT_PRESERVED';target_root=$script:targetRoot;
        previous_runtime_root=$script:oldRoot;failed_stage=$Stage;error=$Message;held_utc=[DateTime]::UtcNow.ToString('o');
        source_manifest_sha256=$Plan.source_manifest_sha256;reviewed_repairs=[string[]]@($Plan.reviewed_repairs);
        accounts_provisioned=0;tasks_changed=0;credentials_modified=$false;databases_modified=$false;ram_modified=$false;pipeline_started=$false;activation_ready=$false;
        next_step='r4 is untouched. Preserve this root and its logs; never rerun into it. Hand install-held.json and frozen-build.log to the agent.'}
    Write-NewRuntimeReport (Join-Path $script:targetRoot 'install-held.json') $record
}

function Protect-NewRuntimeTree {
    param([string]$Path)
    if([IO.Path]::GetFullPath($Path).TrimEnd('\') -cne $script:targetRoot){throw 'Only this newly created revision may receive installation ACLs.'}
    # Directory ACL inheritance may affect descendants. Prove the ENTIRE tree
    # has trusted custody, no reparse paths and no external hardlinks before
    # the first Set-Acl, rather than discovering an alias after propagation.
    $null=Assert-CodeTreeOnce $Path
    $queue=[Collections.Generic.Queue[string]]::new();$queue.Enqueue($Path);$count=0
    while($queue.Count){
        if(++$count -gt 50000){throw 'New runtime tree exceeds its custody bound.'}
        $item=Get-Item -LiteralPath ($queue.Dequeue()) -Force
        if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'New runtime contains a reparse entry; no redirect will be protected.'}
        if($item.PSIsContainer){foreach($child in Get-ChildItem -LiteralPath $item.FullName -Force){$queue.Enqueue($child.FullName)}}else{
            $stream=[IO.File]::Open($item.FullName,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
            try{[CoChemStagedFileIdentity]::Check($stream,$item.FullName)}finally{$stream.Dispose()}}
        # Never apply an ACL through a hardlink. All objects here belong to the
        # fresh versioned root, whose parent was protected before the build.
        Set-Acl -LiteralPath $item.FullName -AclObject (New-CodeAcl $item.PSIsContainer)
    }
}

function Invoke-FrozenRuntimeBuild {
    # Avoid ambient Python/uv policy and user-cache writes. The current process
    # environment is restored on every outcome; profiles/credentials are untouched.
    $saved=@{};$keys=@(Get-ChildItem Env:|Where-Object {$_.Name -match '^(UV_|PYTHON)' -or $_.Name -in @('VIRTUAL_ENV','TEMP','TMP')}|ForEach-Object {$_.Name})
    foreach($key in $keys){$saved[$key]=[Environment]::GetEnvironmentVariable($key,'Process');[Environment]::SetEnvironmentVariable($key,$null,'Process')}
    try{
        $env:UV_PROJECT_ENVIRONMENT=Join-Path $script:targetRoot '.venv'
        $env:TEMP=Join-Path $script:targetRoot 'build-temp';$env:TMP=$env:TEMP
        $env:PYTHONNOUSERSITE='1';$env:PYTHONDONTWRITEBYTECODE='1'
        # Output is local to the new protected root; no inherited uv index/key
        # configuration is printed. A failed/interruptible build is never reused.
        $log=Join-Path $script:targetRoot 'frozen-build.log'
        if(Test-Path -LiteralPath $log){throw 'Preserve existing build log.'}
        $syncArguments=@(Get-FrozenSyncArguments)
        $previousPreference=$ErrorActionPreference;$global:LASTEXITCODE=$null;$buildExit=$null
        try{
            # Windows PowerShell 5.1 represents redirected native stderr as
            # ErrorRecords even for exit 0. Judge the native exit code; do not
            # mistake normal uv progress for a terminating PowerShell failure.
            $ErrorActionPreference='Continue'
            & $script:uv @syncArguments *> $log
            $buildExit=$global:LASTEXITCODE
        }finally{$ErrorActionPreference=$previousPreference}
        if($null -eq $buildExit -or $buildExit -ne 0){throw ('Frozen uv synchronization failed, exit '+$buildExit+'. Preserve the fresh root/log; no provisioning occurred.')}
    }finally{
        foreach($item in @(Get-ChildItem Env:|Where-Object {$_.Name -match '^(UV_|PYTHON)' -or $_.Name -in @('VIRTUAL_ENV','TEMP','TMP')})){
            [Environment]::SetEnvironmentVariable($item.Name,$null,'Process')}
        foreach($key in $saved.Keys){[Environment]::SetEnvironmentVariable($key,$saved[$key],'Process')}
    }
}

function Invoke-NewRuntimeValidation {
    param([string]$Root)
    $newPython=Join-Path $Root '.venv\Scripts\python.exe'
    # Sitting S1 with the r5 interpreter: load_config on the commissioned 135cd9ec bytes (6 workers / 4 slots),
    # the inherited telemetry and revision checks, then the r5 checks. Each r5 check names its repair, so an
    # unrepaired tree fails with that name. No database, task, network, model or worker is touched.
    $validation=@'
import contextlib,ctypes,inspect,io,json,sys,tempfile
from pathlib import Path
# r5: the reviewed agy identity policy is importable (checked first, so an unrepaired tree names it).
from cochem_pipeline import agy_protocol
assert getattr(agy_protocol,'IDENTITY_POLICY',None)=='reported-model-equality', 'r5 repair missing: agy_protocol.IDENTITY_POLICY'
assert isinstance(getattr(agy_protocol,'AgyIdentityError',None),type) and issubclass(agy_protocol.AgyIdentityError,ValueError), 'r5 repair missing: agy_protocol.AgyIdentityError'
from cochem_pipeline.config import load_config
from cochem_pipeline.deployment_revision import verify_installed_revision
from cochem_pipeline import resource_telemetry
root=Path(sys.argv[1]); config=load_config(str(root/'pipeline.json'))
assert config.max_execution_slots==4 and len(config.workers)==6
assert config.ramdisk.workspace_subdirectory=='CoChem427-windows-20261007'
assert config.ramdisk.mount_root=='R:\\' and config.ramdisk.adopted_drive
# The repaired telemetry must be the installed one: module-scope structure and cached binding.
assert hasattr(resource_telemetry,'PerformanceInformation') and hasattr(resource_telemetry,'_commit_probe'), 'telemetry repair missing: PerformanceInformation/_commit_probe'
assert ctypes.sizeof(resource_telemetry.PerformanceInformation)==104, 'telemetry repair ABI differs from PERFORMANCE_INFORMATION'
result=verify_installed_revision(root/'source',Path(sys.executable).parent.parent/'Lib/site-packages',root/'source')
# r5: one agy stream-json parse fixture under the identity policy; a different reported model is refused.
model='gemini-3.8-flash-high'; session='r5-install-validation'
stream=json.dumps({'event':'init','conversation_id':session,'init':{'model':model,'tools':[]}})+chr(10)+json.dumps({'event':'result','result':{'conversation_id':session,'status':'SUCCESS','num_turns':1,'response':'ok','usage':{}}})+chr(10)
parsed=agy_protocol.parse_stream(stream,model,identity_policy=agy_protocol.IDENTITY_POLICY)
assert parsed['reported_model']==model and parsed['native_selected_model']==model, 'r5 repair missing: agy_protocol.parse_stream identity receipt'
try:
    agy_protocol.parse_stream(stream,'gemini-3.8-flash-low',identity_policy=agy_protocol.IDENTITY_POLICY)
    identity_refused=False
except agy_protocol.AgyIdentityError:
    identity_refused=True
assert identity_refused, 'r5 repair missing: agy_protocol refuses a different reported model'
# r5: one chapter WBS drift fixture through reconcile_chapter_wbs, then JobStore._chapter.
try:
    from cochem_pipeline.store import JobStore,reconcile_chapter_wbs
except ImportError:
    raise AssertionError('r5 repair missing: store.reconcile_chapter_wbs') from None
declared=[{'id':'T1','description':'Declared task one','requirements':['REQ-001']},{'id':'T2','description':'Declared task two','requirements':['REQ-002']}]
job={'workflow_id':'r5-install-validation','chapter_id':'ch1','payload':{'requirements':['REQ-001','REQ-002'],'wbs_tasks_defined':declared}}
drifted={'chapter_id':'ch1','requirements_traced':['REQ-001','REQ-002'],'artifact_uri':'db://r5-install-validation/ch1','wbs_tasks_defined':[{'id':'T1','description':'Declared task one, reworded by the model','requirements':['REQ-001']},{'id':'T3','description':'Model task','requirements':['REQ-002']}]}
try:
    JobStore._chapter(job,drifted)
    drift_refused=False
except ValueError:
    drift_refused=True
assert drift_refused, 'WBS drift fixture was not refused before reconciliation'
reconciled,evidence=reconcile_chapter_wbs(job['payload'],drifted)
try:
    JobStore._chapter(job,reconciled)
except ValueError as error:
    raise AssertionError('r5 repair missing: JobStore._chapter refuses the reconciled chapter: '+str(error)) from None
assert evidence is not None and evidence['schema']=='cochem-chapter-wbs-reconciliation/1', 'r5 repair missing: chapter WBS reconciliation evidence'
assert (evidence['restored_omitted_ids'],evidence['restored_rewritten_ids'],evidence['additional_task_ids'])==(['T2'],['T1'],['T3']), 'r5 repair missing: chapter WBS reconciliation result'
# r5: read_workspace inventories a temporary plain file (Windows link count from os.lstat).
from cochem_pipeline.coding import read_workspace
with tempfile.TemporaryDirectory(prefix='cochem-r5-install-') as folder:
    Path(folder,'plain.txt').write_bytes(b'r5 install validation')
    try:
        listed=read_workspace(Path(folder))
    except ValueError as error:
        raise AssertionError('r5 repair missing: coding.read_workspace refuses a plain file: '+str(error)) from None
assert listed=={'plain.txt':b'r5 install validation'}, 'r5 repair missing: coding.read_workspace inventory differs'
# r5 (A2): the reboot-safe daemon options are importable and parsable; the daemon itself never runs here.
from cochem_pipeline import __main__ as entry
signature=inspect.signature(entry.daemon)
parameters=signature.parameters
assert 'queue_launch_output_root' in parameters and 'docker_wait_seconds' in parameters and parameters['docker_wait_seconds'].default==0, 'r5 repair missing: daemon(queue_launch_output_root, docker_wait_seconds)'
calls=[]; outcomes={}
cases={'accepted':['--queue-launch-output-root','queue-launch-r5','--docker-wait-seconds','900'],'exclusive':['--queue-launch-output','queue-a','--queue-launch-output-root','queue-b'],'negative_wait':['--docker-wait-seconds','-1']}
saved=(entry.daemon,sys.argv)
try:
    entry.daemon=lambda *args,**kwargs: calls.append(dict(signature.bind(*args,**kwargs).arguments))
    with contextlib.redirect_stderr(io.StringIO()):
        for name,extra in cases.items():
            sys.argv=['cochem_pipeline','daemon','--config','pipeline.json']+extra
            try:
                entry.main()
                outcomes[name]=0
            except SystemExit as error:
                outcomes[name]=error.code
finally:
    entry.daemon,sys.argv=saved
assert outcomes=={'accepted':0,'exclusive':2,'negative_wait':2} and len(calls)==1, 'r5 repair missing: daemon --queue-launch-output-root/--docker-wait-seconds are not parsable as reviewed'
assert calls[0].get('queue_launch_output_root')=='queue-launch-r5' and calls[0].get('docker_wait_seconds')==900 and calls[0].get('queue_launch_output') is None, 'r5 repair missing: daemon options do not reach daemon()'
r5={'max_execution_slots':config.max_execution_slots,'workers':len(config.workers),'identity_policy':agy_protocol.IDENTITY_POLICY,
    'agy_parse_fixture':{'reported_model':parsed['reported_model'],'identity_mismatch_refused':identity_refused},
    'wbs_reconciliation':{'drift_refused_before':drift_refused,'accepted_after':True,'restored_omitted_ids':evidence['restored_omitted_ids'],'restored_rewritten_ids':evidence['restored_rewritten_ids'],'additional_task_ids':evidence['additional_task_ids']},
    'read_workspace_plain_file':True,
    'daemon_options':{'queue_launch_output_root':True,'docker_wait_seconds':calls[0]['docker_wait_seconds'],'mutually_exclusive':True,'negative_wait_refused':True}}
print(json.dumps({'revision':result,'configuration_parsed':True,'ram_workspace_root':str(config.ramdisk.workspace_root),'telemetry_repair_installed':True,'no_system_or_model_execution':True,'r5_repairs_installed':True,'r5':r5}))
'@
    # Judge the native exit code (Windows PowerShell 5.1 turns redirected native stderr into ErrorRecords)
    # and keep the stderr tail for the held record.
    $previousPreference=$ErrorActionPreference;$global:LASTEXITCODE=$null;$validationExit=$null;$lines=@()
    try{
        $ErrorActionPreference='Continue'
        $lines=@(& $newPython -I -B -c $validation $Root 2>&1)
        $validationExit=$global:LASTEXITCODE
    }finally{$ErrorActionPreference=$previousPreference}
    $stdout=@($lines|Where-Object {$_ -isnot [Management.Automation.ErrorRecord]}|ForEach-Object {[string]$_})
    $stderr=@($lines|Where-Object {$_ -is [Management.Automation.ErrorRecord]}|ForEach-Object {$_.ToString()})
    if($null -eq $validationExit -or $validationExit -ne 0){
        $detail=($stderr -join "`n");if($detail.Length -gt 2000){$detail=$detail.Substring($detail.Length-2000)}
        throw ('New r5 revision/config validation failed, exit '+$validationExit+'. Preserve fresh root; old runtime remains selected. '+$detail)}
    $verification=($stdout -join "`n")|ConvertFrom-Json
    if($verification.revision.verified -ne $true -or $verification.configuration_parsed -ne $true -or $verification.telemetry_repair_installed -ne $true -or
       $verification.no_system_or_model_execution -ne $true -or $verification.r5_repairs_installed -ne $true -or
       $verification.r5.identity_policy -cne 'reported-model-equality' -or $verification.r5.max_execution_slots -ne 4 -or $verification.r5.workers -ne 6 -or
       $verification.r5.agy_parse_fixture.identity_mismatch_refused -ne $true -or $verification.r5.wbs_reconciliation.drift_refused_before -ne $true -or
       $verification.r5.wbs_reconciliation.accepted_after -ne $true -or $verification.r5.read_workspace_plain_file -ne $true -or
       $verification.r5.daemon_options.mutually_exclusive -ne $true -or $verification.r5.daemon_options.docker_wait_seconds -ne 900){
        throw 'New r5 revision did not produce valid verification metadata.'}
    return $verification
}

function New-InstallPlan {
    param([string]$ManifestSha256,[int]$SourceFiles,[object[]]$Repairs,[bool]$PriorTaskCheckDeferred,[object[]]$TaskStates,[object[]]$Holds,$Inventory)
    # The r4 cochem-stopped-runtime-update/1 fields come first with their names and types unchanged
    # (reviewed_repair is the inherited r4 telemetry repair, still installed); r5 fields are only added.
    $repairPaths=[string[]]@($Repairs|ForEach-Object {[string]$_.relative})
    $repairPins=[ordered]@{};$lineEndings=[ordered]@{}
    foreach($repair in $Repairs){$repairPins[[string]$repair.relative]=[string]$repair.sha256;$lineEndings[[string]$repair.relative]=[string]$repair.line_endings}
    $commit=Get-OptionalMember $Inventory 'source_commit'
    [ordered]@{schema='cochem-stopped-runtime-update/1';mode='READ_ONLY_PLAN';target_root=$script:targetRoot;previous_runtime_root=$script:oldRoot;
        previous_install_receipt_sha256=$script:priorInstallHash;previous_source_manifest_sha256=$script:priorManifestHash;source_manifest_sha256=$ManifestSha256;
        source_files=$SourceFiles;reviewed_repair=$script:inheritedRepair;reviewed_repair_sha256=$script:inheritedRepairHash;configuration_sha256=$script:configHash;
        configuration_unchanged=$true;only_config_change=$null;preserved_denial_receipt_sha256=$script:denialHash;preserved_denial_task_terminal_check_deferred=$PriorTaskCheckDeferred;
        managed_daemon_tasks=[object[]]@($TaskStates);preserved_worker_cleanup_verified=$false;accounts_provisioned=0;tasks_changed=0;credentials_modified=$false;
        databases_modified=$false;ram_modified=$false;pipeline_started=$false;activation_ready=$false;holds=[object[]]@($Holds);
        revision_label='r5';runtime_python=(Join-Path $script:targetRoot '.venv\Scripts\python.exe');source_stage_root=$script:repo;
        source_commit=$(if($commit -is [string]){$commit}else{$null});previous_revision_sha256=$script:priorRevisionHash;
        reviewed_repairs=$repairPaths;reviewed_repairs_sha256=$repairPins;repair_line_endings=$lineEndings;
        verified_unchanged=$(if($repairPaths.Count -eq 13){[int]$script:expectedUnchanged}else{$null});installed_repairs_verified=$false}
}

function Invoke-NewRuntimeInstallation {
    param([object[]]$Files,[object[]]$ControlFiles,$Folder,$Plan,[object[]]$Repairs)
$mutex=[Threading.Mutex]::new($false,$script:setupMutexName);$locked=$false
try{
    try{$locked=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$locked=$true}
    if(-not $locked){throw 'Another code-only revision update owns the setup mutex.'}
    # Two keys before anything is created: the manifest (bound by -ManifestSha256) and this script's reviewed pins.
    if(-not (Test-ReviewedRepairPinsFilled $script:reviewedRepairPins)){throw 'Reviewed r5 repair pins are placeholders (PIN-AFTER-COMMIT); nothing was created.'}
    if(-not (Test-SameOrdinalSet ([string[]]@($Repairs|ForEach-Object {[string]$_.relative})) ([string[]]@($script:reviewedRepairPaths)))){throw 'The reviewed r5 repairs were not established; nothing was created.'}
    foreach($repair in $Repairs){if([string]$script:reviewedRepairPins[[string]$repair.relative] -cne [string]$repair.sha256){throw ('A reviewed r5 repair differs from its pin; nothing was created: '+$repair.relative)}}
    $taskStates=@(Get-ManagedDaemonTaskState $Folder)
    if(@($taskStates|Where-Object {$_.state -eq 'ACCESS_DENIED_DEFERRED'}).Count){throw 'Elevated apply could not read a managed daemon task; nothing was created.'}
    if(@($taskStates|Where-Object {$_.references_new_root -eq $true}).Count){throw 'A managed daemon task already references the fresh r5 root; nothing was created.'}
    Assert-PreservedDenialTask $Folder
    if(Test-Path -LiteralPath $script:targetRoot){throw 'Fresh revision root appeared; preserve it.'}
    if(@(Get-R5SiblingRoots).Count){throw 'Another r5 runtime root appeared; nothing was created.'}
    $null=Assert-CodeTreeOnce (Split-Path -Parent $script:python);Assert-ProtectedPath $script:uv
    $null=Assert-CodeTreeOnce $script:oldRoot
    $stage='create-root'
    try{
        New-ProtectedDirectory $script:targetRoot;New-ProtectedDirectory $script:sourceRoot
        $stage='copy-source'
        $directories=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        foreach($file in $Files){$parent=Split-Path -Parent $file.destination;while($parent -ne $script:sourceRoot){$null=$directories.Add($parent);$parent=Split-Path -Parent $parent}}
        foreach($directory in @($directories|Sort-Object Length)){New-ProtectedDirectory $directory}
        foreach($file in $Files){Copy-VerifiedPayload $file}
        $stage='copy-control'
        foreach($file in $ControlFiles){Copy-VerifiedPayload $file}
        $stage='install-before'
        Write-NewRuntimeReport (Join-Path $script:targetRoot 'install-before.json') $Plan
        $stage='build'
        New-ProtectedDirectory (Join-Path $script:targetRoot 'build-temp')
        Invoke-FrozenRuntimeBuild
        $stage='protect'
        Protect-NewRuntimeTree $script:targetRoot
        $verifiedEntries=Assert-CodeTreeOnce $script:targetRoot
        # Build backends may change their source tree. Bind the post-build bytes to
        # the reviewed manifest again before importing any freshly installed code.
        $stage='post-build-rebind'
        Assert-PostBuildFrozenFiles $Files
        Assert-PostBuildFrozenFiles $ControlFiles
        $stage='installed-repairs'
        Assert-InstalledRepairs $script:targetRoot $Repairs
        $stage='interpreter'
        $runtimeBindings=Assert-NewRuntimeInterpreter $script:targetRoot
        $stage='validation'
        $verification=Invoke-NewRuntimeValidation $script:targetRoot
        $stage='task-recheck'
        $taskStates=@(Get-ManagedDaemonTaskState $Folder)
        if(@($taskStates|Where-Object {$_.state -eq 'ACCESS_DENIED_DEFERRED' -or $_.references_new_root -eq $true}).Count){throw 'A managed daemon task is unreadable or references the fresh r5 root after the build.'}
        Assert-PreservedDenialTask $Folder
        foreach($pin in $script:pins){$stream=Open-VerifiedFile $pin.source $pin.sha256 (Get-Item -LiteralPath $pin.source).Length;$stream.Dispose()}
        $stage='install-after'
        $Plan.mode='FRESH_STOPPED_RUNTIME_READY';$Plan.preserved_denial_task_terminal_check_deferred=$false;$Plan.managed_daemon_tasks=[object[]]$taskStates;$Plan.holds=[object[]]@()
        $Plan.installed_repairs_verified=$true;$Plan['verified_entries']=$verifiedEntries;$Plan['verification']=$verification;$Plan['runtime_bindings']=$runtimeBindings
        Write-NewRuntimeReport (Join-Path $script:targetRoot 'install-after.json') $Plan
    }catch{
        $failure=$_
        # Only a root this run created can exist here (an existing root was refused above).
        if(Test-Path -LiteralPath $script:targetRoot){try{Write-InstallHeldRecord $stage $failure.Exception.Message $Plan}catch{}}
        throw $failure
    }
    $Plan|ConvertTo-Json -Depth 8
}finally{if($locked){$mutex.ReleaseMutex()};$mutex.Dispose()}

}

function Assert-InstallerHost {
    param([string]$Edition,[bool]$Is64BitProcess,[string]$ComputerName)
    if($Edition -ne 'Desktop' -or -not $Is64BitProcess -or $ComputerName -ne 'AETHERDESK'){throw 'Use 64-bit Windows PowerShell 5.1 on AETHERDESK.'}
}

function Assert-ApplyAuthority {
    param([bool]$ApplyRequested,[bool]$Admin,[string]$IdentityName)
    if($ApplyRequested -and (-not $Admin -or $IdentityName -ne 'AETHERDESK\ansac')){throw '-Apply requires the owner in Administrator Windows PowerShell.'}
}

function Set-InstallerConstants {
    $script:setupMutexName='Global\CoChem427-CodeOnlyRuntimeUpdate'
    $script:programFiles='C:\Program Files';$script:base=Join-Path $script:programFiles 'CoChem'
    # The r5 source is the frozen r4 tree plus the 13 reviewed repairs, staged by
    # freeze-stopped-runtime-r5-source.py outside Google Drive and outside any git checkout.
    $script:repo='C:\Users\ansac\CoChem427\stopped-runtime-r5-source'
    $script:r3Root=Join-Path $script:base 'Pipeline4.2.7-windows-20261007-r3'
    $script:oldRoot=Join-Path $script:base 'Pipeline4.2.7-windows-20261009-r4'
    $script:targetRoot=Join-Path $script:base 'Pipeline4.2.7-windows-20261011-r5';$script:sourceRoot=Join-Path $script:targetRoot 'source'
    $script:python=Join-Path $script:base 'Toolchain4.2.7-windows-20261006\Python312\python.exe'
    $script:pythonHash='d8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa'
    $script:uv=Join-Path $script:base 'Toolchain4.2.7-windows-20261006\uv\uv.exe'
    $script:uvHash='2019cdf564cb8f749262f5f021cedc75a99abb1c6081227ca340bbcda972611d'
    # Reviewed helpers, hash-pinned (recomputed from disk 2026-10-11; unchanged since the r4 installer).
    $script:copyHelper='C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1'
    $script:copyHelperHash='0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b'
    $script:treeHelperHash='1576882fe655d27894aa6f9da25a14ae4ddd08540c865d51cc43b26fa3dd6f9d'
    # r5 keeps the r4 runtime's configuration and layout (the commissioned 135cd9ec bytes).
    $script:oldConfig=Join-Path $script:oldRoot 'pipeline.json';$script:layout=Join-Path $script:oldRoot 'windows-layout.json'
    $script:commissionedConfig=Join-Path $script:base 'WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json'
    $script:configHash='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
    $script:layoutHash='8430fdf1109c63c4a89479f03da8a465dfebf5566c7791c64f868202170672c4'
    # The preserved r4 build (pins recomputed from disk 2026-10-11).
    $script:priorManifestHash='1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189'
    $script:priorInstallHash='629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502'
    $script:priorRevisionHash='38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e'
    $script:r3ManifestHash='6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1'
    $script:r3InstallHash='3b613128192ac44a0a3d9c4b4476fb4c47541edb7563541b9bbf18f84f9a90f6'
    # Inherited r4 repair (commit 5d592f9), unchanged in r5 and still asserted by the validation.
    $script:inheritedRepair='src/cochem_pipeline/resource_telemetry.py'
    $script:inheritedRepairHash='e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc'
    $script:denialHash='691c70560436f948464c529b9d2d6a3e33ce240749642af86ca79c748791461d'
    $script:denialPath='C:\Program Files\CoChem\WorkerDenial4.2.7-windows-20261006-slot1\worker-denial-acceptance.json'
    # Addendum A6: the 12 spec files plus __main__.py; 153 of the 166 r4 source assets stay byte-identical.
    $script:reviewedRepairPaths=@('src/cochem_pipeline/__main__.py','src/cochem_pipeline/agy_protocol.py','src/cochem_pipeline/coding.py',
        'src/cochem_pipeline/config.py','src/cochem_pipeline/controller_guard.py','src/cochem_pipeline/failures.py',
        'src/cochem_pipeline/knowledge.py','src/cochem_pipeline/operator_views.py','src/cochem_pipeline/runtime.py',
        'src/cochem_pipeline/service.py','src/cochem_pipeline/store.py','src/cochem_pipeline/worker.py','src/cochem_supervisor/runner.py')
    $script:lfRepairPaths=@('src/cochem_pipeline/agy_protocol.py')
    $script:expectedUnchanged=153
    # Reviewed r5 repair pins: sha256 of each blob in commit 8554c7645801a7bc9c4abad4861bfcbe4ed014b0 on
    # feature/r5-gemini-and-runtime-fixes (r4 line-ending convention, pure), the same table BUILD-FREEZE pins
    # (freeze-stopped-runtime-r5-source.py REPAIRS). A PIN-AFTER-COMMIT placeholder refuses every mode.
    $script:reviewedRepairPins=[ordered]@{
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
        'src/cochem_supervisor/runner.py'='adc8ccf33841438f3104e64325ff84b7826c49db297c8bc3f02ebb55ad96cf31'
    }
}

function Invoke-InstallerMain {
    param([string]$Manifest,[string]$ManifestSha256,[bool]$ApplyRequested,[bool]$Admin,$Folder)
    # An unreviewed pin table refuses before anything is read, in plan mode as well as with -Apply.
    if(-not (Test-ReviewedRepairPinsFilled $script:reviewedRepairPins)){
        throw 'The reviewed r5 repair sha256 pins in this installer are PIN-AFTER-COMMIT placeholders; fill them from the committed source (the same table BUILD-FREEZE pins) before any run.'}
    $holds=@()
    if(-not $Manifest -or -not $ManifestSha256){$holds+='Awaiting the complete reviewed r5 source freeze manifest and its SHA256.'}
    if(Test-Path -LiteralPath $script:targetRoot){$holds+='Fresh revision root already exists; preserve it and do not reuse.'}
    $siblings=@(Get-R5SiblingRoots)
    if($siblings.Count){$holds+=('Another r5 runtime root exists; retarget-warden-r5.ps1 requires exactly one: '+($siblings -join ', '))}
    $files=@();$inventory=$null;$repairs=@()
    if($Manifest -and $ManifestSha256){
        $inventory=Read-Inventory $Manifest $ManifestSha256
        $files=@(Get-RuntimeFiles $inventory)
        foreach($file in $files){$stream=Open-VerifiedFile $file.source $file.sha256 $file.length;$stream.Dispose()}}
    $script:pins=@(
        [pscustomobject]@{source=$script:python;sha256=$script:pythonHash}
        [pscustomobject]@{source=$script:uv;sha256=$script:uvHash}
        [pscustomobject]@{source=$script:oldConfig;sha256=$script:configHash}
        [pscustomobject]@{source=$script:layout;sha256=$script:layoutHash}
        [pscustomobject]@{source=(Join-Path $script:oldRoot 'source-manifest.json');sha256=$script:priorManifestHash}
        [pscustomobject]@{source=(Join-Path $script:oldRoot 'install-after.json');sha256=$script:priorInstallHash}
        [pscustomobject]@{source=$script:denialPath;sha256=$script:denialHash}
    )
    $held=[Collections.Generic.List[IO.Stream]]::new()
    try{
        foreach($pin in $script:pins){$stream=Open-VerifiedFile $pin.source $pin.sha256 (Get-Item -LiteralPath $pin.source).Length;$held.Add($stream)}
        # The r5 runtime keeps the r4 configuration; it must also equal the configuration the Warden
        # task's current action names (the commissioned copy: same reviewed bytes, different file).
        $configText=Read-HeldText $held[2]
        $commissioned=Open-VerifiedFile $script:commissionedConfig $script:configHash (Get-Item -LiteralPath $script:commissionedConfig).Length
        $held.Add($commissioned)
        Assert-ExactPreservedConfig $configText (Read-HeldText $commissioned)
        Assert-PriorReceipts ((Read-HeldText $held[5])|ConvertFrom-Json) ((Read-HeldText $held[6])|ConvertFrom-Json)
        if($inventory){
            $repairs=@(Assert-ReviewedR5Delta $inventory ((Read-HeldText $held[4])|ConvertFrom-Json) $script:reviewedRepairPins)
            Assert-RepairLineEndings $files $repairs}
        $controlFiles=@()
        if($inventory){$controlFiles=@(New-ControlCopyRecords $Manifest $ManifestSha256);foreach($file in $controlFiles){$stream=Open-VerifiedFile $file.source $file.sha256 $file.length;$held.Add($stream)}}
        $taskStates=@(Get-ManagedDaemonTaskState $Folder)
        $deferredTasks=@($taskStates|Where-Object {$_.state -eq 'ACCESS_DENIED_DEFERRED'}|ForEach-Object {$_.name})
        $referencing=@($taskStates|Where-Object {$_.references_new_root -eq $true}|ForEach-Object {$_.name})
        if($referencing.Count){$holds+=('A managed daemon task already references the fresh r5 root: '+($referencing -join ', '))}
        if($deferredTasks.Count){
            $holds+=($(if($Admin){'Managed daemon task definitions are unreadable even when elevated; nothing will be created: '}else{'Managed daemon task definitions are unreadable without elevation; re-read during -Apply: '})+($deferredTasks -join ', '))}
        $priorTaskCheckDeferred=$false
        if($Admin){Assert-PreservedDenialTask $Folder}else{$priorTaskCheckDeferred=$true}
        $plan=New-InstallPlan $ManifestSha256 $files.Count $repairs $priorTaskCheckDeferred $taskStates $holds $inventory
        if(-not $ApplyRequested){return ($plan|ConvertTo-Json -Depth 6)}
        # -Apply is elevated, so every task definition was readable above; any hold blocks.
        if($holds.Count){throw ($holds -join ' ')}
        Invoke-NewRuntimeInstallation $files $controlFiles $Folder $plan $repairs
    }finally{foreach($stream in $held){$stream.Dispose()}}
}

# Invocation boundary. Tests extract actual functions only; no installation runs.
foreach($module in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$module\$module.psd1") -ErrorAction Stop}
Assert-InstallerHost $PSVersionTable.PSEdition ([Environment]::Is64BitProcess) $env:COMPUTERNAME
$identity=[Security.Principal.WindowsIdentity]::GetCurrent();$admin=[Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Assert-ApplyAuthority ([bool]$Apply) $admin $identity.Name
Set-InstallerConstants
$definitions=@(Import-ReviewedFunctions $script:copyHelper $script:copyHelperHash @('Get-LocalPath','Assert-NoReparseAncestors','Assert-ProtectedPath','New-CodeAcl','New-ProtectedDirectory','Initialize-FileIdentity','Open-VerifiedFile','Read-Inventory','Copy-VerifiedPayload'))
foreach($definition in $definitions){. ([scriptblock]::Create($definition))}
$definitions=@(Import-ReviewedFunctions (Join-Path $PSScriptRoot 'check-worker-denials.ps1') $script:treeHelperHash @('Assert-CodeTreeOnce'))
foreach($definition in $definitions){. ([scriptblock]::Create($definition))}
Initialize-FileIdentity
# Read-only COM access: GetTask/GetInstances/Definition only; nothing is registered, run, stopped, enabled or disabled.
$scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect();$folder=$scheduler.GetFolder('\')
Invoke-InstallerMain $Manifest $ManifestSha256 ([bool]$Apply) $admin $folder
