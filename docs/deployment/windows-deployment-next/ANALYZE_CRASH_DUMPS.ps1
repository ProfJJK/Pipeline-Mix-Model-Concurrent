#Requires -Version 5.1
<# Identify the driver behind this host's bugchecks (owner, Administrator Windows PowerShell 5.1).
   Read-only toward the system except: installs Microsoft WinDbg with winget if no debugger is present,
   keeps a symbol cache in C:\symbols, and writes copies of the minidumps plus the analysis into
   crash-analysis-<stamp>\ next to this script (owner-readable, never published).
   For each minidump (newest 15 by default, -All for every one) it runs `cdb -z <dump> -c "!analyze -v; q"`
   and extracts the bugcheck code, the faulting module/image, the process and the failure bucket.
   The first run downloads symbols and takes longest; later dumps are faster. Nothing is changed in the
   pipeline, its tasks or its state. #>
[CmdletBinding()]
param([switch]$All,[int]$Newest=15,[int]$PerDumpTimeoutSeconds=240)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if(-not [Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Run this in Windows PowerShell started with "Run as administrator" (the minidumps are Administrators-only).'}
$stamp=(Get-Date).ToString('yyyyMMdd-HHmmss');$out=Join-Path $PSScriptRoot ('crash-analysis-'+$stamp);$null=New-Item -ItemType Directory -Path $out
$log=Join-Path $out 'analysis.log';Start-Transcript -Path $log | Out-Null
try{
    function Find-Cdb {
        foreach($candidate in @('C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe','C:\Program Files\Windows Kits\10\Debuggers\x64\cdb.exe')){if(Test-Path -LiteralPath $candidate){return $candidate}}
        $package=Get-AppxPackage -AllUsers -Name 'Microsoft.WinDbg' -ErrorAction SilentlyContinue|Sort-Object Version -Descending|Select-Object -First 1
        if($package){foreach($sub in @('amd64\cdb.exe','x64\cdb.exe')){$path=Join-Path $package.InstallLocation $sub;if(Test-Path -LiteralPath $path){return $path}}}
        $null}
    $cdb=Find-Cdb
    if(-not $cdb){
        Write-Host 'No debugger found; installing Microsoft WinDbg with winget (a minute or two)...'
        $winget=(Get-Command winget.exe -ErrorAction SilentlyContinue)
        if(-not $winget){throw 'winget is not available; install WinDbg from the Microsoft Store, then rerun.'}
        & $winget.Source install --id Microsoft.WinDbg -e --silent --accept-package-agreements --accept-source-agreements | Out-Host
        $cdb=Find-Cdb
        if(-not $cdb){throw 'WinDbg installed but cdb.exe was not found in its package; send the log to the agent.'}}
    Write-Host ('Debugger: '+$cdb)
    $null=New-Item -ItemType Directory -Path 'C:\symbols' -Force
    $env:_NT_SYMBOL_PATH='srv*C:\symbols*https://msdl.microsoft.com/download/symbols'
    $dumps=@(Get-ChildItem -LiteralPath 'C:\Windows\Minidump' -Filter '*.dmp' | Sort-Object LastWriteTime -Descending)
    if(-not $All){$dumps=@($dumps|Select-Object -First $Newest)}
    Write-Host ('Analyzing '+$dumps.Count+' minidumps; the first one downloads symbols and is the slowest.')
    $rows=@();$index=0
    foreach($dump in ($dumps|Sort-Object LastWriteTime)){
        $index++;Write-Host ('['+$index+'/'+$dumps.Count+'] '+$dump.Name+' ('+$dump.LastWriteTime+')')
        $copy=Join-Path $out $dump.Name;Copy-Item -LiteralPath $dump.FullName -Destination $copy
        $text=Join-Path $out ($dump.BaseName+'.analyze.txt')
        $process=Start-Process -FilePath $cdb -ArgumentList @('-z',('"'+$copy+'"'),'-c','"!analyze -v; q"') -RedirectStandardOutput $text -RedirectStandardError ($text+'.err') -NoNewWindow -PassThru
        if(-not $process.WaitForExit($PerDumpTimeoutSeconds*1000)){try{$process.Kill()}catch{};Write-Host '   timed out; partial output kept'}
        $content=$(if(Test-Path -LiteralPath $text){Get-Content -LiteralPath $text -Raw}else{''})
        function Get-Field {param([string]$Name)if($content -match ('(?m)^'+[regex]::Escape($Name)+':\s*(.+)$')){$Matches[1].Trim()}else{''}}
        $row=[ordered]@{dump=$dump.Name;time=$dump.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss');bugcheck=(Get-Field 'BUGCHECK_CODE');bugcheck_name=$(if($content -match '(?m)^([A-Z_]+) \([0-9a-f]+\)\s*$'){$Matches[1]}else{''});
            module=(Get-Field 'MODULE_NAME');image=(Get-Field 'IMAGE_NAME');process=(Get-Field 'PROCESS_NAME');symbol=(Get-Field 'SYMBOL_NAME');bucket=(Get-Field 'FAILURE_BUCKET_ID');os_build=(Get-Field 'OS_VERSION')}
        $rows+=[pscustomobject]$row
        Write-Host ('   '+$row.bugcheck_name+' | module '+$row.module+' | image '+$row.image+' | process '+$row.process)}
    $rows|Export-Csv -LiteralPath (Join-Path $out 'summary.csv') -NoTypeInformation -Encoding UTF8
    $rows|ConvertTo-Json -Depth 3|Set-Content -LiteralPath (Join-Path $out 'summary.json') -Encoding UTF8
    Write-Host ''
    Write-Host 'Faulting modules, most frequent first:' -ForegroundColor Green
    $rows|Group-Object image|Sort-Object Count -Descending|ForEach-Object {Write-Host ('  '+$_.Count+'  '+$(if($_.Name){$_.Name}else{'(not identified)'}))}
    Write-Host ('DONE. Results: '+$out+'  (summary.csv / summary.json; tell the agent the folder name)') -ForegroundColor Green
}finally{try{Stop-Transcript|Out-Null}catch{}}
