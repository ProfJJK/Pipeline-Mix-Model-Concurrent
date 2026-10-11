"""Stub-driven checks for retire-legacy-hyperv.ps1 (no Hyper-V cmdlet is ever really called)."""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
SCRIPT = ROOT / 'retire-legacy-hyperv.ps1'
TEXT = SCRIPT.read_text(encoding='utf-8')


def ps(path):
    return str(path).replace("'", "''")


def run(tmp_path, body, vms, states=None, switch_used_elsewhere=False):
    """Dot-source the script's functions with Hyper-V stubs; vms is a list of dicts."""
    tree = tmp_path / 'v4.1.2'
    folder = tree / 'vm'
    folder.mkdir(parents=True)
    (folder / 'CoChem-Quarantine-Golden.vhdx').write_bytes(b'x' * 10)
    (folder / 'ubuntu.iso').write_bytes(b'y' * 10)
    def quoted(values):
        return ','.join("'" + str(value) + "'" for value in values)  # PowerShell single quotes keep backslashes literal
    vm_lines = ';'.join(
        f"[pscustomobject]@{{Name='{v['name']}';State='{v.get('state', 'Off')}';MemoryAssigned=1048576;ConfigurationLocation='C:\\vm';disks=@({quoted(v.get('disks', []))});dvds=@({quoted(v.get('dvds', []))});switch='{v.get('switch', '')}';checkpoints=@({quoted(v.get('checkpoints', []))})}}"
        for v in vms)
    turn_off_after = 1 if states is None else states
    prelude = f"""$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;
      $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('{ps(SCRIPT)}',[ref]$tokens,[ref]$errors);
      if($errors.Count){{throw ($errors|Out-String)}};
      foreach($f in $ast.FindAll({{param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]}},$true)){{. ([scriptblock]::Create($f.Extent.Text))}};
      $script:legacyTree='{ps(tree)}';$script:legacyVmFolder='{ps(folder)}';$script:legacyNamePattern='^CoChem';$script:legacySwitch='CoChem-Quarantine-Switch';
      $script:vms=@({vm_lines});$script:stopCalls=@();$script:removed=@();$script:snapshotsRemoved=@();$script:switchRemoved=$false;$script:turnOffAfter={turn_off_after};
      function Get-VM {{param($Name,$ErrorAction)if($Name){{$v=$script:vms|Where-Object {{$_.Name -eq $Name}};if(-not $v){{throw 'no such vm'}};return $v}};$script:vms}};
      function Get-VMHardDiskDrive {{param($VMName,$ErrorAction)($script:vms|Where-Object {{$_.Name -eq $VMName}}).disks|ForEach-Object {{[pscustomobject]@{{Path=$_}}}}}};
      function Get-VMDvdDrive {{param($VMName,$ErrorAction)($script:vms|Where-Object {{$_.Name -eq $VMName}}).dvds|ForEach-Object {{[pscustomobject]@{{Path=$_}}}}}};
      function Get-VMNetworkAdapter {{param($VMName,$ErrorAction)$v=$script:vms|Where-Object {{$_.Name -eq $VMName}};if($v.switch){{[pscustomobject]@{{SwitchName=$v.switch}}}}}};
      function Get-VMSnapshot {{param($VMName,$ErrorAction)($script:vms|Where-Object {{$_.Name -eq $VMName}}).checkpoints|ForEach-Object {{[pscustomobject]@{{Name=$_}}}}}};
      function Stop-VM {{param($Name,[switch]$Force,[switch]$TurnOff,[switch]$AsJob,$ErrorAction)$script:stopCalls+=$(if($TurnOff){{'turnoff:'+$Name}}else{{'graceful:'+$Name}});
        if($script:turnOffAfter -eq 0){{throw 'turn-off refused by the fixture'}};$v=$script:vms|Where-Object {{$_.Name -eq $Name}};$v.State='Off';$null}};
      function Remove-VMSavedState {{param($VMName,$ErrorAction)$script:snapshotsRemoved+=('saved:'+$VMName);($script:vms|Where-Object {{$_.Name -eq $VMName}}).State='Off'}};
      function Remove-VM {{param($Name,[switch]$Force,[switch]$Confirm,[switch]$AsJob,$ErrorAction)$script:removed+=$Name;$script:vms=@($script:vms|Where-Object {{$_.Name -ne $Name}});$null}};
      function Wait-HyperVJob {{param($Job,$Seconds,$What)$script:waits+=$What}};$script:waits=@();
      function Get-VMSwitch {{param($Name,$ErrorAction)[pscustomobject]@{{Name=$Name}}}};
      function Remove-VMSwitch {{param($Name,[switch]$Force,[switch]$Confirm,$ErrorAction)$script:switchRemoved=$true}};
      function Start-Sleep {{param($Seconds)}};
      {body}
    """
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', prelude], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


LEGACY = {'name': 'CoChem-Golden-Baker', 'state': 'Running', 'disks': [r'D:\__CoChem\__agentic\v4.1.2\vm\CoChem-Quarantine-Golden.vhdx'], 'dvds': [r'D:\__CoChem\__agentic\v4.1.2\vm\ubuntu.iso'],
          'switch': 'CoChem-Quarantine-Switch', 'checkpoints': ['before-provision']}
OTHER = {'name': 'DevBox', 'state': 'Running', 'disks': [r'E:\VMs\devbox.vhdx'], 'switch': 'Default Switch'}


def test_parses_and_only_targets_legacy_vms():
    assert 'Remove-VM -Name $vm.name' in TEXT and TEXT.count('Remove-VM ') == 1
    assert "$legacyNamePattern='^CoChem'" in TEXT and "legacyVmFolder=Join-Path $legacyTree 'vm'" in TEXT
    assert 'Remove-Item -LiteralPath $file.FullName' in TEXT and 'StartsWith($script:legacyVmFolder' in TEXT, 'only files under the legacy vm folder are deleted'
    assert 'Checkpoint-VM' not in TEXT and 'New-VM' not in TEXT and 'Start-VM' not in TEXT


def test_inventory_marks_legacy_by_name_or_disk_location(tmp_path):
    vms = [LEGACY, OTHER, {'name': 'Scratch', 'disks': [r'D:\__CoChem\__agentic\v4.1.2\vm\other.vhdx']}]
    value = run(tmp_path, "$inv=@(Get-VmInventory);@{legacy=@($inv|Where-Object {$_.legacy}|ForEach-Object name);all=@($inv|ForEach-Object name)}|ConvertTo-Json -Compress",
                [dict(v, disks=[d.replace(r'D:\__CoChem\__agentic\v4.1.2\vm', str(tmp_path / 'v4.1.2' / 'vm')) for d in v.get('disks', [])]) for v in vms])
    assert sorted(value['legacy']) == ['CoChem-Golden-Baker', 'Scratch'] and sorted(value['all']) == ['CoChem-Golden-Baker', 'DevBox', 'Scratch']


@pytest.mark.parametrize('mode', ['running', 'stopping', 'saved', 'already_off'])
def test_retirement_powers_off_removes_and_deletes_only_legacy(tmp_path, mode):
    folder = tmp_path / 'v4.1.2' / 'vm'
    legacy = dict(LEGACY, disks=[str(folder / 'CoChem-Quarantine-Golden.vhdx')], dvds=[str(folder / 'ubuntu.iso')])
    legacy['state'] = {'saved': 'Saved', 'already_off': 'Off', 'stopping': 'Stopping'}.get(mode, 'Running')
    value = run(tmp_path, "$inv=@(Get-VmInventory);$r=Invoke-VmRetirement $inv;[ordered]@{result=$r;stops=$script:stopCalls;removed=$script:removed;snaps=$script:snapshotsRemoved;switch=$script:switchRemoved;waits=$script:waits}|ConvertTo-Json -Compress -Depth 6",
                [legacy, OTHER])
    result = value['result']
    assert result['status'] == 'LEGACY_VM_RETIRED' and value['removed'] == ['CoChem-Golden-Baker']
    expected_stops = {'running': ['turnoff:CoChem-Golden-Baker'], 'stopping': ['turnoff:CoChem-Golden-Baker'], 'saved': [], 'already_off': []}[mode]
    assert value['stops'] == expected_stops, 'a guest shutdown request is never issued'
    assert value['snaps'] == (['saved:CoChem-Golden-Baker'] if mode == 'saved' else [])
    assert result['vms'][0]['stopped'] == {'running': 'turned off', 'stopping': 'turned off', 'saved': 'saved state discarded', 'already_off': 'already off'}[mode]
    assert value['waits'] == (['Turning off CoChem-Golden-Baker', 'Removing CoChem-Golden-Baker'] if mode in ('running', 'stopping') else ['Removing CoChem-Golden-Baker'])


def test_turn_off_failure_stops_before_anything_is_deleted(tmp_path):
    folder = tmp_path / 'v4.1.2' / 'vm'
    legacy = dict(LEGACY, disks=[str(folder / 'CoChem-Quarantine-Golden.vhdx')], dvds=[str(folder / 'ubuntu.iso')])
    value = run(tmp_path, "$inv=@(Get-VmInventory);$failed=$false;$message='';try{$null=Invoke-VmRetirement $inv}catch{$failed=$true;$message=$_.Exception.Message};"
                          "[ordered]@{failed=$failed;message=$message;removed=$script:removed;files=@(Get-ChildItem -LiteralPath $script:legacyVmFolder -File|ForEach-Object Name)}|ConvertTo-Json -Compress",
                [legacy, OTHER], states=0)
    assert value['failed'] and 'turn-off refused' in value['message'] and value['removed'] == []
    assert sorted(value['files']) == ['CoChem-Quarantine-Golden.vhdx', 'ubuntu.iso'], 'no disk file is deleted when the VM could not be powered off'


def test_hyperv_job_wait_times_out_instead_of_blocking():
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                f"$e=$null;$t=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('{ps(SCRIPT)}',[ref]$t,[ref]$e);"
                "foreach($f in $ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Wait-HyperVJob'},$true)){. ([scriptblock]::Create($f.Extent.Text))};"
                "$slow=Start-Job {Start-Sleep -Seconds 30};$quick=Start-Job {'ok'};$bad=Start-Job {throw 'boom'};$timedOut=$false;$failedText='';"
                "try{Wait-HyperVJob $slow 2 'Slow op'}catch{$timedOut=$_.Exception.Message};"
                "Wait-HyperVJob $quick 20 'Quick op';"
                "try{Wait-HyperVJob $bad 20 'Bad op'}catch{$failedText=$_.Exception.Message};"
                "@{timed_out=$timedOut;failed=$failedText;jobs_left=@(Get-Job).Count}|ConvertTo-Json -Compress"], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert 'did not finish within 2 s' in value['timed_out'] and value['failed'].startswith('Bad op failed') and value['jobs_left'] == 0


def test_switch_is_kept_when_another_vm_uses_it_and_outside_disks_are_listed(tmp_path):
    folder = tmp_path / 'v4.1.2' / 'vm'
    legacy = dict(LEGACY, disks=[str(folder / 'CoChem-Quarantine-Golden.vhdx'), r'E:\golden\base.vhdx'], dvds=[])
    other = dict(OTHER, switch='CoChem-Quarantine-Switch')
    value = run(tmp_path, "$inv=@(Get-VmInventory);$r=Invoke-VmRetirement $inv;[ordered]@{result=$r;switch=$script:switchRemoved}|ConvertTo-Json -Compress -Depth 6", [legacy, other])
    assert value['switch'] is False and value['result']['vms'][0]['disks_outside_legacy_folder'] == [r'E:\golden\base.vhdx']
    assert value['result']['remaining_vms'] == ['DevBox']
