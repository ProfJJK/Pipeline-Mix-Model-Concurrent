#Requires -Version 5.1
<# Installs a fresh, stopped R6 runtime from a reviewed offline wheel bundle.
   Does not register/start/stop tasks, provision accounts, open databases or alter R:.
   Only the owner runs -Apply. A partial root is preserved and never reused.
   Activation and native acceptance belong to the enclosing reviewed series. #>
[CmdletBinding()]
param([string]$Manifest,[string]$ManifestSha256,[switch]$Apply)

function Import-R6CopyFunctions {
    param([string]$Directory)
    $path=Join-Path $Directory 'stage_aetherdesk_427_payloads.ps1'
    $pin='0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b'
    $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$actual=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        if($actual -cne $pin){throw 'Reviewed copy helper changed.'}
        $stream.Position=0;$reader=[IO.StreamReader]::new($stream)
        try{$text=$reader.ReadToEnd()}finally{$reader.Dispose()}
        $tokens=$null;$errors=$null
        $ast=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
        if($errors.Count){throw 'Reviewed copy helper cannot be parsed.'}
        foreach($name in @('Get-LocalPath','Assert-NoReparseAncestors','Assert-ProtectedPath','New-CodeAcl',
            'New-ProtectedDirectory','Initialize-FileIdentity','Open-VerifiedFile','Read-Inventory','Copy-VerifiedPayload')) {
            $found=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$false))
            if($found.Count -ne 1){throw 'Reviewed copy function is missing or duplicated.'}
            $found[0].Extent.Text
        }
    }finally{$stream.Dispose()}
}

function Set-R6Constants {
    $script:programFiles='C:\Program Files';$script:base='C:\Program Files\CoChem'
    $script:targetRoot=Join-Path $script:base 'Pipeline4.2.7-windows-20261012-r6-v1'
    $script:python=Join-Path $script:base 'Toolchain4.2.7-windows-20261006\Python312\python.exe'
    $script:uv=Join-Path $script:base 'Toolchain4.2.7-windows-20261006\uv\uv.exe'
    $script:pythonPin='d8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa'
    $script:uvPin='2019cdf564cb8f749262f5f021cedc75a99abb1c6081227ca340bbcda972611d'
    $script:venvPin='560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'
}

function Assert-R6Relative {
    param([string]$Relative)
    if($Relative -cnotmatch '^(source/|wheels/|pipeline\.json$)' -or $Relative.Contains('\') -or
        $Relative -match '[\x00-\x1f<>:"|?*]' -or
        @($Relative.Split('/')|Where-Object{$_ -in @('','.','..') -or $_.EndsWith('.') -or $_.EndsWith(' ') -or
            $_ -match '^(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)'}).Count){throw 'Unsafe R6 payload path.'}
}

function Get-R6InstallFiles {
    param($Inventory)
    if($Inventory.schema -cne 'cochem-r6-install-bundle/1' -or $Inventory.host -cne 'AETHERDESK' -or
        $Inventory.revision -cne 'windows-20261012-r6-v1' -or [string]$Inventory.source_commit -cnotmatch '^[a-f0-9]{40}$'){
        throw 'Unexpected R6 install manifest.'}
    $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $rows=[Collections.Generic.List[object]]::new();$total=[long]0
    foreach($file in @($Inventory.files)){
        $relative=[string]$file.relative;Assert-R6Relative $relative
        if(-not $seen.Add($relative) -or [string]$file.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            ($file.length -isnot [int] -and $file.length -isnot [long]) -or $file.length -lt 0 -or $file.length -gt 268435456){throw 'Invalid or duplicate R6 payload record.'}
        $source=[IO.Path]::GetFullPath([string]$file.source)
        if($source -cne [string]$file.source -or $source -notmatch '^[A-Za-z]:\\' -or
            $source -match '(?i)\\(?:gdrive|google drive)\\'){throw 'R6 sources must be literal local paths outside Google Drive.'}
        $total += [long]$file.length
        if($total -gt 2147483648 -or $rows.Count -ge 4096){throw 'R6 payload exceeds bounds.'}
        $rows.Add([pscustomobject]@{source=$source;relative=$relative;destination=(Join-Path $script:targetRoot $relative.Replace('/','\'));
            sha256=[string]$file.sha256;length=[long]$file.length})
    }
    foreach($required in @('source/README.md','source/pyproject.toml','source/uv.lock',
        'source/src/cochem_pipeline/__main__.py','source/src/cochem_pipeline/specification/routing_catalog_v3.json',
        'source/knowledge/v4.1.2_manifest.json','pipeline.json','wheels/runtime-requirements.txt',
        'wheels/cochem-4.2.7-py3-none-any.whl')){
        if(-not $seen.Contains($required)){throw ('Incomplete R6 payload: '+$required)}}
    $rows.ToArray()
}

function Get-R6VenvArguments {
    @('--no-config','--no-cache','--offline','venv',(Join-Path $script:targetRoot '.venv'),
      '--python',$script:python,'--no-python-downloads','--prompt','cochem')
}

function New-R6PayloadAcl {
    param([string]$Relative,[bool]$Directory)
    $acl=New-CodeAcl $Directory
    if($Relative -ceq 'source/knowledge' -or $Relative.StartsWith('source/knowledge/',[StringComparison]::Ordinal)){
        $users=[Security.Principal.SecurityIdentifier]::new('S-1-5-32-545')
        foreach($rule in @($acl.GetAccessRules($true,$false,[Security.Principal.SecurityIdentifier]))){
            if($rule.IdentityReference -eq $users){$acl.RemoveAccessRuleSpecific($rule)}}
    }
    $acl
}

function New-R6PayloadDirectory {
    param([string]$Path)
    if(Test-Path -LiteralPath $Path){throw 'Preserve existing payload directory.'}
    Assert-ProtectedPath (Split-Path -Parent $Path)
    $relative=$Path.Substring($script:targetRoot.Length+1).Replace('\','/')
    $directory=[IO.DirectoryInfo]::new($Path);$directory.Create((New-R6PayloadAcl $relative $true))
    Assert-ProtectedPath $Path
}

function Copy-R6Payload {
    param($File)
    $source=Open-VerifiedFile $File.source $File.sha256 $File.length
    try{
        Assert-ProtectedPath (Split-Path -Parent $File.destination)
        $target=[IO.FileStream]::new($File.destination,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,1048576,[IO.FileOptions]::None,(New-R6PayloadAcl $File.relative $false))
        try{$source.CopyTo($target);$target.Flush($true)}finally{$target.Dispose()}
    }finally{$source.Dispose()}
    $verify=Open-VerifiedFile $File.destination $File.sha256 $File.length;$verify.Dispose()
}
function Get-R6InstallArguments {
    @('--no-config','--no-cache','--offline','pip','install','--python',(Join-Path $script:targetRoot '.venv\Scripts\python.exe'),
      '--no-python-downloads','--no-index','--find-links',(Join-Path $script:targetRoot 'wheels'),
      '--require-hashes','--no-deps','--no-build','--link-mode','copy','--requirement',(Join-Path $script:targetRoot 'wheels\runtime-requirements.txt'))
}

function ConvertTo-R6NativeArgument {
    param([string]$Value)
    if($Value -match '[\x00\r\n]'){throw 'Invalid native argument.'}
    # Windows CommandLineToArgvW quoting, including slashes preceding quotes/end.
    '"'+[regex]::Replace([regex]::Replace($Value,'(\\*)"','$1$1\"'),'(\\+)$','$1$1')+'"'
}

function Invoke-R6Native {
    param([string]$Executable,[string[]]$Arguments,[string]$Label,[int]$Seconds=600)
    $stdout=Join-Path $script:targetRoot ($Label+'.stdout.log');$stderr=Join-Path $script:targetRoot ($Label+'.stderr.log')
    if((Test-Path -LiteralPath $stdout) -or (Test-Path -LiteralPath $stderr)){throw 'Preserve existing native logs.'}
    $argv=@($Arguments|ForEach-Object{ConvertTo-R6NativeArgument $_}) -join ' '
    $process=Start-Process -FilePath $Executable -ArgumentList $argv -WorkingDirectory $script:targetRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    try{
        # Cache the owned handle before waiting; PowerShell 5.1's Start-Process
        # wrapper can otherwise leave ExitCode null after a fast completion.
        $null=$process.Handle
        if(-not $process.WaitForExit($Seconds*1000)){throw 'Native installer exceeded its bound; preserve its owned process and partial root.'}
        $process.Refresh()
        if($null -eq $process.ExitCode -or $process.ExitCode -ne 0){throw ('Native installer failed: '+$Label)}
    }finally{$process.Dispose()}
}

function Assert-R6Interpreter {
    $path=Join-Path $script:targetRoot '.venv\Scripts\python.exe'
    $stream=Open-VerifiedFile $path $script:venvPin (Get-Item -LiteralPath $path).Length;$stream.Dispose()
    $values=@{}
    foreach($line in [IO.File]::ReadAllLines((Join-Path $script:targetRoot '.venv\pyvenv.cfg'))){
        if(-not $line.Trim()){continue}
        if($line -notmatch '^([^=]+?)\s*=\s*(.*)$' -or $values.ContainsKey($matches[1].Trim())){throw 'Unexpected venv configuration.'}
        $values[$matches[1].Trim()]=$matches[2].Trim()
    }
    $expected=@{home=(Split-Path -Parent $script:python);implementation='CPython';uv='0.12.17';version_info='3.12.13';'include-system-site-packages'='false';prompt='cochem'}
    if($values.Count -ne $expected.Count){throw 'Unexpected venv configuration keys.'}
    foreach($key in $expected.Keys){if($values[$key] -cne $expected[$key]){throw 'Venv does not bind the protected Python toolchain.'}}
}

function Assert-R6Tree {
    $queue=[Collections.Generic.Queue[string]]::new();$queue.Enqueue($script:targetRoot);$count=0
    while($queue.Count){
        if(++$count -gt 50000){throw 'Installed tree exceeds its bound.'}
        $item=Get-Item -LiteralPath ($queue.Dequeue()) -Force
        Assert-ProtectedPath $item.FullName
        if($item.PSIsContainer){foreach($child in Get-ChildItem -LiteralPath $item.FullName -Force){$queue.Enqueue($child.FullName)}}
        else{$stream=[IO.File]::Open($item.FullName,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
            try{[CoChemStagedFileIdentity]::Check($stream,$item.FullName)}finally{$stream.Dispose()}}
    }
    $count
}

function Write-R6InstallRecord {
    param([string]$Name,$Value)
    Assert-ProtectedPath $script:targetRoot
    $path=Join-Path $script:targetRoot $Name
    $stream=[IO.FileStream]::new($path,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,4096,[IO.FileOptions]::None,(New-CodeAcl $false))
    try{$bytes=[Text.UTF8Encoding]::new($false).GetBytes(($Value|ConvertTo-Json -Depth 12));$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
}

function Assert-R6NotReferenced {
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect();$folder=$scheduler.GetFolder('\')
    foreach($name in @('CoChem-4.2.7-Warden','CoChem-4.2.7-Supervisor')){
        $task=$null
        try{$task=$folder.GetTask($name)}catch{
            $cause=$_.Exception
            while($null -ne $cause.InnerException){$cause=$cause.InnerException}
            if($cause.HResult -ne -2147024894){throw}}
        if($null -ne $task){
            foreach($action in $task.Definition.Actions){
                if(([string]$action.Path).IndexOf($script:targetRoot,[StringComparison]::OrdinalIgnoreCase) -ge 0 -or
                    ([string]$action.Arguments).IndexOf($script:targetRoot,[StringComparison]::OrdinalIgnoreCase) -ge 0){throw 'A managed task already references the fresh R6 root.'}}
        }
    }
}

function Invoke-R6Installation {
    param($Inventory,[object[]]$Files,[string]$ManifestPath,[string]$ManifestHash)
    $mutex=[Threading.Mutex]::new($false,'Global\CoChem427-CodeOnlyRuntimeUpdate');$locked=$false;$created=$false;$phase='preflight'
    $saved=@{};$environmentChanged=$false
    try{
        try{$locked=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$locked=$true}
        if(-not $locked){throw 'Another code installation owns the setup mutex.'}
        Assert-R6NotReferenced
        if(Test-Path -LiteralPath $script:targetRoot){throw 'Preserve the existing R6 root; do not reuse.'}
        New-ProtectedDirectory $script:targetRoot;$created=$true
        $directories=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        foreach($file in $Files){$parent=Split-Path -Parent $file.destination
            while($parent -ne $script:targetRoot){$null=$directories.Add($parent);$parent=Split-Path -Parent $parent}}
        foreach($directory in @($directories|Sort-Object Length)){New-R6PayloadDirectory $directory}
        $phase='copy'
        foreach($file in $Files){Copy-R6Payload $file}
        Copy-VerifiedPayload ([pscustomobject]@{source=$ManifestPath;destination=(Join-Path $script:targetRoot 'install-manifest.json');sha256=$ManifestHash;length=(Get-Item -LiteralPath $ManifestPath).Length})
        Write-R6InstallRecord 'install-before.json' @{schema='cochem-r6-offline-install/1';status='PREPARED';manifest_sha256=$ManifestHash;source_commit=$Inventory.source_commit}
        $environmentChanged=$true
        foreach($item in @(Get-ChildItem Env:|Where-Object{$_.Name -match '^(UV_|PIP_|PYTHON)' -or $_.Name -in @('VIRTUAL_ENV','TEMP','TMP')})){
            $saved[$item.Name]=$item.Value;[Environment]::SetEnvironmentVariable($item.Name,$null,'Process')}
        New-ProtectedDirectory (Join-Path $script:targetRoot 'build-temp')
        $env:TEMP=Join-Path $script:targetRoot 'build-temp';$env:TMP=$env:TEMP;$env:PYTHONNOUSERSITE='1';$env:PYTHONDONTWRITEBYTECODE='1'
        $phase='venv';Invoke-R6Native $script:uv (Get-R6VenvArguments) 'create-venv' 120
        Assert-R6Interpreter
        $phase='offline-install';Invoke-R6Native $script:uv (Get-R6InstallArguments) 'install-wheels' 600
        $phase='verify-custody';$entries=Assert-R6Tree
        foreach($file in $Files){$s=Open-VerifiedFile $file.destination $file.sha256 $file.length;$s.Dispose()}
        Assert-R6Interpreter
        $phase='verify-revision';$source=Join-Path $script:targetRoot 'source'
        Invoke-R6Native (Join-Path $script:targetRoot '.venv\Scripts\python.exe') @('-I','-B','-m','cochem_pipeline.deployment_revision','--source-repository',$source,'--installed-source',$source) 'verify-revision' 120
        $revision=Get-Content -LiteralPath (Join-Path $script:targetRoot 'verify-revision.stdout.log') -Raw|ConvertFrom-Json
        if($revision.schema -cne 'cochem-installed-revision/1' -or $revision.verified -ne $true){throw 'Installed source verification did not pass.'}
        Assert-R6NotReferenced
        $record=[ordered]@{schema='cochem-r6-offline-install/1';status='STOPPED_RUNTIME_INSTALLED';target_root=$script:targetRoot;
            source_commit=$Inventory.source_commit;manifest_sha256=$ManifestHash;verified_entries=$entries;revision=$revision;
            tasks_changed=0;accounts_changed=0;credentials_modified=$false;existing_databases_modified=$false;ram_modified=$false;
            pipeline_started=$false;activation_ready=$false}
        Write-R6InstallRecord 'install-after.json' $record
        $record|ConvertTo-Json -Depth 8
    }catch{
        if($created){try{Write-R6InstallRecord 'install-held.json' @{schema='cochem-r6-offline-install/1';status='HELD_PRESERVE_PARTIAL';phase=$phase;
            manifest_sha256=$ManifestHash;error_type=$_.Exception.GetType().Name;automatic_retry=$false;activation_ready=$false}}catch{}}
        throw
    }finally{
        if($environmentChanged){
            foreach($item in @(Get-ChildItem Env:|Where-Object{$_.Name -match '^(UV_|PIP_|PYTHON)' -or $_.Name -in @('VIRTUAL_ENV','TEMP','TMP')})){
                [Environment]::SetEnvironmentVariable($item.Name,$null,'Process')}
            foreach($key in $saved.Keys){[Environment]::SetEnvironmentVariable($key,$saved[$key],'Process')}
        }
        if($locked){$mutex.ReleaseMutex()};$mutex.Dispose()
    }
}

function Invoke-R6InstallerMain {
    param([string]$ManifestPath,[string]$ManifestHash,[bool]$ApplyRequested)
    if($ManifestHash -cnotmatch '^[a-f0-9]{64}$' -or -not $ManifestPath){throw 'A pinned R6 manifest is required.'}
    if($PSVersionTable.PSEdition -cne 'Desktop' -or -not [Environment]::Is64BitProcess -or $env:COMPUTERNAME -cne 'AETHERDESK'){
        throw 'Use 64-bit Windows PowerShell 5.1 on AETHERDESK.'}
    if($ApplyRequested){
        $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
        if($identity.Name -cne 'AETHERDESK\ansac' -or -not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){
            throw 'Only the owner runs Apply in Administrator PowerShell.'}}
    Set-R6Constants
    foreach($definition in @(Import-R6CopyFunctions $PSScriptRoot)){. ([scriptblock]::Create($definition))}
    Initialize-FileIdentity
    $inventory=Read-Inventory $ManifestPath $ManifestHash;$files=@(Get-R6InstallFiles $inventory)
    if(Test-Path -LiteralPath $script:targetRoot){throw 'Preserve the existing R6 root; do not reuse.'}
    foreach($file in $files){$s=Open-VerifiedFile $file.source $file.sha256 $file.length;$s.Dispose()}
    $held=[Collections.Generic.List[IO.Stream]]::new()
    try{
        foreach($pin in @([pscustomobject]@{path=$script:python;hash=$script:pythonPin},[pscustomobject]@{path=$script:uv;hash=$script:uvPin})){
            Assert-ProtectedPath $pin.path;$held.Add((Open-VerifiedFile $pin.path $pin.hash (Get-Item -LiteralPath $pin.path).Length))}
        if(-not $ApplyRequested){@{schema='cochem-r6-offline-install/1';status='READ_ONLY_PLAN';files=$files.Count;target_root=$script:targetRoot;activation_ready=$false}|ConvertTo-Json;return}
        Invoke-R6Installation $inventory $files ([IO.Path]::GetFullPath($ManifestPath)) $ManifestHash
    }finally{foreach($stream in $held){$stream.Dispose()}}
}

$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
Invoke-R6InstallerMain $Manifest $ManifestSha256 ([bool]$Apply)
