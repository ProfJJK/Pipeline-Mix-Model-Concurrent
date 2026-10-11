$ErrorActionPreference='Stop'
$sourceRoot='D:\Gdrive\__CoChem\GitHub-Repo\Antigravity_additions'
$backupRoot='C:\Users\ansac\source\repo-backups\Pipeline-Mix-Model-Concurrent-20261009'
$cloneRoot='C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent'
if(Test-Path -LiteralPath $backupRoot){throw 'Backup already exists; preserve and inspect it.'}
if(Test-Path -LiteralPath $cloneRoot){throw 'New clone path already exists; preserve and inspect it.'}
foreach($ancestor in @('C:\Users\ansac','C:\Users\ansac\source','C:\Users\ansac\source\repos')){
    $item=Get-Item -LiteralPath $ancestor -Force
    if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Destination ancestor is redirected; preserve state.'}
}
[void][IO.Directory]::CreateDirectory($backupRoot)
$bundle=Join-Path $backupRoot 'all-local-git-history.bundle'
& git --no-optional-locks -C $sourceRoot bundle create $bundle --all
if($LASTEXITCODE -ne 0){throw 'Git history backup did not complete.'}
& git --no-optional-locks -C $sourceRoot bundle verify $bundle
if($LASTEXITCODE -ne 0){throw 'Git history backup did not verify.'}
$copyRoot=Join-Path $backupRoot 'original-checkout'
$logPath=Join-Path $backupRoot 'filesystem-copy.log'
& robocopy $sourceRoot $copyRoot /E /COPY:DAT /DCOPY:DAT /XJ /R:1 /W:1 /NFL /NDL /NP ('/LOG:'+ $logPath)
if($LASTEXITCODE -ge 8){throw 'Checkout preservation copy incomplete; leave all copies intact.'}
& 'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r3\.venv\Scripts\python.exe' -I (Join-Path $PSScriptRoot 'verify-preserved-checkout-20261009.py') $sourceRoot $copyRoot (Join-Path $backupRoot 'exact-byte-manifest.json')
if($LASTEXITCODE -ne 0){throw 'Preserved checkout bytes did not verify; no new clone started.'}
& git -c core.autocrlf=false clone 'https://github.com/ProfJJK/Pipeline-Mix-Model-Concurrent.git' $cloneRoot
if($LASTEXITCODE -ne 0){throw 'Fresh clone did not complete; preserve backup and partial clone.'}
& git -C $cloneRoot config core.autocrlf false
if($LASTEXITCODE -ne 0){throw 'Cannot set exact-byte checkout behavior.'}
& git -C $cloneRoot merge --no-ff --no-edit origin/docs/windows-agent-handoff-2026-10-09
if($LASTEXITCODE -ne 0){throw 'Approved documentation merge did not complete; inspect without resetting.'}
[ordered]@{status='EXACT_LOCAL_BACKUP_AND_FRESH_NON_SYNCED_CLONE_READY';backup_root=$backupRoot;clone_root=$cloneRoot;original_checkout_unchanged=$true;protected_deployment_changed=$false}|ConvertTo-Json
