#Requires -Version 5.1
<# Retire the legacy 4.1.2 Hyper-V quarantine VM and its disks (owner, 64-bit Administrator Windows PowerShell 5.1).
   Default is a read-only plan: it lists every VM, marks the legacy targets and what would happen.
   -Apply: for each legacy VM (name CoChem*, or any disk/DVD under the legacy vm folder) it discards a
   saved state, powers the VM off (a hard turn-off, never a guest shutdown request, as a timed job),
   removes the VM definition (checkpoint configurations included, no disk merge), deletes the disk
   files that live under the legacy vm folder, removes the legacy
   virtual switch when no VM uses it any more, and finally removes the empty legacy tree. Disks
   outside the legacy folder are never deleted; they are listed for the owner. A receipt is written
   to the workspace evidence folder. Nothing else on the host is touched. #>
[CmdletBinding()]
param([switch]$Apply)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$legacyTree='D:\__CoChem\__agentic\v4.1.2';$legacyVmFolder=Join-Path $legacyTree 'vm';$legacyNamePattern='^CoChem';$legacySwitch='CoChem-Quarantine-Switch'
$evidence=Join-Path $PSScriptRoot 'legacy-removal-evidence-20261010'

function Get-VmInventory {
    $inventory=@()
    foreach($vm in @(Get-VM -ErrorAction Stop)){
        $disks=@(Get-VMHardDiskDrive -VMName $vm.Name -ErrorAction SilentlyContinue|ForEach-Object {[string]$_.Path})
        $dvds=@(Get-VMDvdDrive -VMName $vm.Name -ErrorAction SilentlyContinue|Where-Object {$_.Path}|ForEach-Object {[string]$_.Path})
        $switches=@(Get-VMNetworkAdapter -VMName $vm.Name -ErrorAction SilentlyContinue|Where-Object {$_.SwitchName}|ForEach-Object {[string]$_.SwitchName})
        $checkpoints=@(Get-VMSnapshot -VMName $vm.Name -ErrorAction SilentlyContinue|ForEach-Object {[string]$_.Name})
        $inventory+=[pscustomobject]@{name=[string]$vm.Name;state=[string]$vm.State;memory_mb=[int64]($vm.MemoryAssigned/1MB);disks=$disks;dvds=$dvds;switches=$switches;checkpoints=$checkpoints;
            configuration=[string]$vm.ConfigurationLocation;legacy=(Test-LegacyVm -Name $vm.Name -Paths ($disks+$dvds))}
    }
    $inventory
}

function Test-LegacyVm {
    param([string]$Name,[string[]]$Paths)
    if($Name -match $script:legacyNamePattern){return $true}
    foreach($path in $Paths){if($path -and $path.StartsWith($script:legacyVmFolder,[StringComparison]::OrdinalIgnoreCase)){return $true}}
    $false
}

function Wait-HyperVJob {
    # Every Hyper-V mutation runs as a job with a deadline so a guest or the VMMS can never block the console.
    param($Job,[int]$Seconds,[string]$What)
    if($null -eq $Job){return}
    $finished=Wait-Job -Job $Job -Timeout $Seconds
    if($null -eq $finished){Stop-Job -Job $Job -ErrorAction SilentlyContinue;Remove-Job -Job $Job -Force -ErrorAction SilentlyContinue;throw ($What+' did not finish within '+$Seconds+' s; Hyper-V is not responding for this VM. Nothing else was changed.')}
    $failed=($Job.State -eq 'Failed');$output=@(Receive-Job -Job $Job -ErrorAction SilentlyContinue 2>&1|ForEach-Object {[string]$_})
    Remove-Job -Job $Job -Force -ErrorAction SilentlyContinue
    if($failed){throw ($What+' failed: '+($output -join ' '))}
}

function Stop-LegacyVm {
    param([string]$Name)
    $state=[string](Get-VM -Name $Name -ErrorAction Stop).State
    if($state -eq 'Off'){return 'already off'}
    if($state -eq 'Saved'){Remove-VMSavedState -VMName $Name -ErrorAction Stop;if([string](Get-VM -Name $Name).State -eq 'Off'){return 'saved state discarded'}}
    # Hard power-off only, never a guest shutdown request: the quarantine guest holds nothing worth
    # keeping, and a guest that ignores the request would hold the owner's console indefinitely.
    Wait-HyperVJob (Stop-VM -Name $Name -TurnOff -Force -AsJob -ErrorAction Stop) 120 ('Turning off '+$Name)
    $deadline=(Get-Date).AddSeconds(60)
    while((Get-Date) -lt $deadline){if([string](Get-VM -Name $Name).State -eq 'Off'){return 'turned off'};Start-Sleep -Seconds 3}
    throw ('VM '+$Name+' did not reach the Off state after the turn-off.')
}

function Invoke-VmRetirement {
    param($Inventory)
    $targets=@($Inventory|Where-Object {$_.legacy})
    $actions=@()
    foreach($vm in $targets){
        $how=Stop-LegacyVm -Name $vm.name
        # Removing the VM drops its definition and checkpoint configurations; the disk files are deleted below, so no merge is run.
        Wait-HyperVJob (Remove-VM -Name $vm.name -Force -Confirm:$false -AsJob -ErrorAction Stop) 120 ('Removing '+$vm.name)
        $actions+=[ordered]@{vm=$vm.name;stopped=$how;removed=$true;disks_outside_legacy_folder=@(($vm.disks+$vm.dvds)|Where-Object {$_ -and -not $_.StartsWith($script:legacyVmFolder,[StringComparison]::OrdinalIgnoreCase)})}
    }
    $deleted=@();$deleteErrors=@()
    if(Test-Path -LiteralPath $script:legacyVmFolder){
        foreach($file in @(Get-ChildItem -LiteralPath $script:legacyVmFolder -Recurse -File -Force)){
            try{$file.Attributes='Normal';Remove-Item -LiteralPath $file.FullName -Force -ErrorAction Stop;$deleted+=$file.Name}catch{$deleteErrors+=($file.Name+': '+$_.Exception.Message)}}
        if(-not $deleteErrors.Count){Remove-Item -LiteralPath $script:legacyVmFolder -Recurse -Force -ErrorAction Stop}}
    $switchRemoved=$false
    if(Get-VMSwitch -Name $script:legacySwitch -ErrorAction SilentlyContinue){
        $stillUsed=@(Get-VM -ErrorAction Stop|ForEach-Object {Get-VMNetworkAdapter -VMName $_.Name -ErrorAction SilentlyContinue}|Where-Object {$_.SwitchName -eq $script:legacySwitch})
        if(-not $stillUsed.Count){Remove-VMSwitch -Name $script:legacySwitch -Force -Confirm:$false -ErrorAction Stop;$switchRemoved=$true}}
    $treeRemoved=$false
    if((Test-Path -LiteralPath $script:legacyTree) -and -not @(Get-ChildItem -LiteralPath $script:legacyTree -Force -ErrorAction SilentlyContinue).Count){Remove-Item -LiteralPath $script:legacyTree -Force -ErrorAction Stop;$treeRemoved=$true}
    [ordered]@{schema='cochem-legacy-vm-retirement/1';status=$(if($deleteErrors.Count){'VM_REMOVED_DISKS_PARTIALLY_RETAINED'}else{'LEGACY_VM_RETIRED'});vms=$actions;deleted_files=$deleted;delete_errors=$deleteErrors;switch_removed=$switchRemoved;legacy_tree_removed=$treeRemoved;
        remaining_vms=@(Get-VM -ErrorAction Stop|ForEach-Object {[string]$_.Name})}
}

# Invocation boundary. The harness loads the functions above without running this block.
Import-Module Hyper-V -ErrorAction Stop
$identity=[Security.Principal.WindowsIdentity]::GetCurrent();$admin=[Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if($Apply -and (-not $admin -or $identity.Name -cne 'AETHERDESK\ansac' -or -not [Environment]::Is64BitProcess)){throw '-Apply requires the owner in 64-bit Administrator Windows PowerShell; nothing was changed.'}
$inventory=@(Get-VmInventory)
$plan=[ordered]@{schema='cochem-legacy-vm-plan/1';mode='READ_ONLY_PLAN';legacy_vm_folder=$legacyVmFolder;legacy_switch=$legacySwitch;
    vms=@($inventory|ForEach-Object {[ordered]@{name=$_.name;state=$_.state;memory_mb=$_.memory_mb;legacy=$_.legacy;disks=$_.disks;dvds=$_.dvds;switches=$_.switches;checkpoints=$_.checkpoints}});
    targets=@($inventory|Where-Object {$_.legacy}|ForEach-Object {$_.name});
    files_in_legacy_folder=@(if(Test-Path -LiteralPath $legacyVmFolder){Get-ChildItem -LiteralPath $legacyVmFolder -Recurse -File -Force|ForEach-Object {$_.Name+' ('+[int64]($_.Length/1MB)+' MB)'}})}
if(-not $Apply){$plan|ConvertTo-Json -Depth 6;return}
if(-not @($plan.targets).Count){Write-Output (([ordered]@{schema='cochem-legacy-vm-retirement/1';status='NO_LEGACY_VM_FOUND';remaining_vms=@($inventory|ForEach-Object {$_.name})})|ConvertTo-Json -Depth 4);return}
$null=New-Item -ItemType Directory -Path $evidence -Force
$planPath=Join-Path $evidence ('vm-retirement-plan-'+(Get-Date).ToString('yyyyMMdd-HHmmss')+'.json');$plan|ConvertTo-Json -Depth 6|Set-Content -LiteralPath $planPath -Encoding UTF8
$result=Invoke-VmRetirement $inventory
$result.plan_path=$planPath
$result|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $evidence ('vm-retirement-receipt-'+(Get-Date).ToString('yyyyMMdd-HHmmss')+'.json')) -Encoding UTF8
$result|ConvertTo-Json -Depth 6
