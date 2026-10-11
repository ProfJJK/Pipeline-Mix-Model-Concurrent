"""Fixture-driven flow tests for RUN_427_LAUNCH_SERIES.ps1 (revision 3).

The stage functions are extracted from the script text and run in a throwaway Windows
PowerShell 5.1 process in which every host-changing cmdlet and every native or reviewed
invocation is replaced by a recording stub. Nothing on the host is read for state except
temporary directories created per test. The series itself is never executed.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
SCRIPT = Path(os.environ.get('LAUNCH_SERIES_SCRIPT', str(ROOT / 'RUN_427_LAUNCH_SERIES.ps1')))
RECEIPT_READY = '{"mode":"FRESH_STOPPED_RUNTIME_READY"}'
DOCKER_OK = '{"ID":"abcd","OSType":"linux","MemoryLimit":true,"SwapLimit":true,"CpuCfsQuota":true,"PidsLimit":true,"SecurityOptions":["name=seccomp,profile=builtin","name=cgroupns"]}'
IMAGE_OK = 'sha256:d9d3e8644b6fc407c7d5ee7151fcb22470d74b8c14a4e6ef8cf8e9acb62877a2 linux'
HEALTH_OK = '{"service_identity":"SYSTEM","source_root":"R4SOURCEROOT","pid":4242,"instance_id":"i","version":"4.2.7","admission_capacity":3,"active":[],"quarantined_slots":{}}'
PLAN_OK = '{"mode":"READ_ONLY_PLAN","holds":[],"source_files":166}'
RPLAN_OK = '{"mode":"READ_ONLY_PLAN","holds":[],"backup_copy_rights_verified":true}'
SWITCH_OK = '{"status":"WARDEN_R4_RUNNING_HEALTH_VERIFIED","retarget_status":"WARDEN_RETARGETED_TO_R4_NOT_STARTED","started":true}'


def ps(path):
    return str(path).replace("'", "''")


def run_flow(tmp_path, overrides='', stage='all', timeout=120):
    """Dot-source the script's functions with stubs and run the requested stage(s)."""
    work = tmp_path / 'work'
    for sub in ('workspace', 'base', 'archive-parent', 'startup', 'workers', 'd-cochem'):
        (work / sub).mkdir(parents=True)
    for name in ('install-stopped-runtime-r4.ps1', 'retarget-warden-r4.ps1', 'stopped-runtime-r4-source-manifest.json', 'backup-private-databases-r4.py'):
        (work / 'workspace' / name).write_text('x', encoding='utf-8')
    for slot in range(1, 7):
        (work / 'workers' / f'slot{slot}').mkdir()
    (work / 'startup' / 'cochem_startup.vbs').write_text('legacy', encoding='utf-8')
    for tree in ('v4.1.2', 'v4.2.0'):
        (work / 'd-cochem' / tree / 'src').mkdir(parents=True)
        (work / 'd-cochem' / tree / 'src' / 'a.py').write_text('legacy', encoding='utf-8')
    (work / 'runtime.json').write_text('{"observed_controller_state":"healthy"}', encoding='utf-8')
    prelude = f"""$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;
      foreach($m in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){{Import-Module (Join-Path $PSHOME "Modules\\$m\\$m.psd1")}};
      $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('{ps(SCRIPT)}',[ref]$tokens,[ref]$errors);
      if($errors.Count){{throw ($errors|Out-String)}};
      foreach($f in $ast.FindAll({{param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]}},$true)){{. ([scriptblock]::Create($f.Extent.Text))}};
      $w='{ps(work)}';
      $script:started=Get-Date;$script:log=Join-Path $w 'series.log';$script:psExe='C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe';
      $script:workspace=Join-Path $w 'workspace';$script:installer=Join-Path $script:workspace 'install-stopped-runtime-r4.ps1';$script:retarget=Join-Path $script:workspace 'retarget-warden-r4.ps1';
      $script:manifest=Join-Path $script:workspace 'stopped-runtime-r4-source-manifest.json';$script:clientConfig='C:\\client.json';
      $script:base=Join-Path $w 'base';$script:r4Root=Join-Path $script:base 'Pipeline4.2.7-windows-20261009-r4';$script:r4Python=Join-Path $script:r4Root '.venv\\Scripts\\python.exe';
      $script:receiptPath=Join-Path $script:r4Root 'install-after.json';$script:Attempt='v1';$script:r4SourceRoot=Join-Path $script:r4Root '.venv\\Lib';
      $script:attemptRoot=Join-Path $script:base 'WardenRetarget4.2.7-windows-20261010-r4-v1';$script:startReceipt=Join-Path $script:attemptRoot 'start-receipt.json';
      $script:archive=Join-Path (Join-Path $w 'archive-parent') '_retired-legacy-test';
      $script:legacyTasks=@('CoChemHostWarden_V412','CoChem V4.1.2 Swarm','CoChem-Fixture-TaskAcl-20261008-bbd9bf8061764e6ba8cdefa47fb6a149-create18','CoChem-Fixture-TaskAcl-20261008-bbd9bf8061764e6ba8cdefa47fb6a149-create2');
      $script:legacyTrees=@((Join-Path $w 'd-cochem\\v4.1.2'),(Join-Path $w 'd-cochem\\v4.2.0'));$script:legacyLauncher=Join-Path $w 'startup\\cochem_startup.vbs';
      $script:legacyProcessPattern='__CoChem\\\\__agentic\\\\v4\\.(1\\.2|2\\.0)|cochem\\.warden\\.mcp_server|cochem_kanban_mcp\\.py|auto_architect_mcp\\.py|start_pipeline\\.bat|cochem_master_loop|worker_daemon|watchdog_sre|task_work_loop|cochem_ha_daemon|cochem_startup\\.vbs';
      $script:legacyImagePattern='__CoChem\\\\__agentic\\\\v4\\.(1\\.2|2\\.0)\\\\';
      $script:dockerFields=@('OSType','MemoryLimit','SwapLimit','CpuCfsQuota','PidsLimit');$script:executionImage='sha256:d9d3e8644b6fc407c7d5ee7151fcb22470d74b8c14a4e6ef8cf8e9acb62877a2';
      $script:runtimeJson=Join-Path $w 'runtime.json';$script:workerRoot=Join-Path $w 'workers';$script:SkipLegacyRemoval=$false;$script:SkipObservers=$false;
      $script:alreadyStarted=$false;$script:built=$false;
      # ---- recording stubs (default: healthy host, first run) ----
      $script:calls=[Collections.Generic.List[string]]::new();$script:killed=@();$script:unregistered=@();$script:stoppedTasks=@();$script:docker='{DOCKER_OK}';$script:image='{IMAGE_OK}';
      $script:health=('{HEALTH_OK}'.Replace('R4SOURCEROOT',$script:r4SourceRoot.Replace('\\','\\\\')));$script:planOut='{PLAN_OK}';$script:applyOut='{RECEIPT_READY}';$script:rplanOut='{RPLAN_OK}';$script:switchOut='{SWITCH_OK}';$script:listeners=@{{47824=0;47821=0}};
      $script:pypi=$true;$script:clock=$null;
      function Test-PackageIndex {{$script:calls.Add('pypi-probe');$script:pypi}};
      $script:tasks=@{{'CoChemHostWarden_V412'='Running';'CoChem V4.1.2 Swarm'='Ready';'CoChem-Fixture-TaskAcl-20261008-bbd9bf8061764e6ba8cdefa47fb6a149-create18'='Disabled'}};
      $script:processes=@([pscustomobject]@{{ProcessId=4516;Name='python.exe';CommandLine='C:\\Python314\\python.exe -m cochem.warden.mcp_server --transport http --port 47821';ExecutablePath='C:\\Python314\\python.exe'}},
                          [pscustomobject]@{{ProcessId=7340;Name='python.exe';CommandLine='C:\\Python314\\python.exe D:\\__CoChem\\__agentic\\v4.2.0\\auto_architect_mcp.py';ExecutablePath='C:\\Python314\\python.exe'}},
                          [pscustomobject]@{{ProcessId=9472;Name='python.exe';CommandLine='"C:\\Program Files\\CoChem\\Toolchain4.2.7-windows-20261006\\Python312\\python.exe" -I -B "C:\\Program Files\\CoChem\\SupervisorObservation4.2.7-windows-20261007-r3-v1\\held-supervisor-observation-r3-v1.py" --observe';ExecutablePath='C:\\Program Files\\CoChem\\Toolchain4.2.7-windows-20261006\\Python312\\python.exe'}});
      $script:killStops=$true;
      function Assert-OwnerShell {{$script:calls.Add('owner-check')}};
      function Get-MpPreference {{[pscustomobject]@{{ExclusionPath=@(1..6|ForEach-Object {{Join-Path $script:workerRoot ('slot'+$_)}})}}}};
      function Get-NetTCPConnection {{param($LocalPort,$State,$ErrorAction)$n=$script:listeners[[int]$LocalPort];if($n -eq 'error'){{throw 'provider failure'}};if(-not $n){{$e=[Management.Automation.ErrorRecord]::new([Exception]::new('none'),'CmdletizationQuery_NotFound,Get-NetTCPConnection','ObjectNotFound',$null);throw $e}};@(1..$n|ForEach-Object {{[pscustomobject]@{{LocalPort=$LocalPort;OwningProcess=1}}}})}};
      function Get-ScheduledTask {{param($TaskName,$ErrorAction)if($script:tasks.ContainsKey($TaskName)){{[pscustomobject]@{{TaskName=$TaskName;State=$script:tasks[$TaskName]}}}}else{{$null}}}};
      function Export-ScheduledTask {{param($TaskName)'<Task/>'}};
      function Stop-ScheduledTask {{param($TaskName,$ErrorAction)$script:stoppedTasks+=$TaskName}};
      function Unregister-ScheduledTask {{param($TaskName,[switch]$Confirm)$script:unregistered+=$TaskName;$script:tasks.Remove($TaskName)}};
      function Get-CimInstance {{param($ClassName,$Filter,$ErrorAction)if($Filter){{return [pscustomobject]@{{ParentProcessId=1}}}};$script:processes}};
      function Stop-Process {{param($Id,[switch]$Force,$ErrorAction)$script:killed+=$Id;if($script:killStops){{$script:processes=@($script:processes|Where-Object {{$_.ProcessId -ne $Id}})}}}};
      function Start-Sleep {{param($Seconds,$Milliseconds)}};
      function Invoke-Native {{param([string]$Executable,[string[]]$Arguments)$script:calls.Add('native:'+(Split-Path -Leaf $Executable)+' '+($Arguments -join ' '));
        if($Executable -like '*whoami*'){{return [pscustomobject]@{{code=0;text='SeBackupPrivilege Disabled`nSeRestorePrivilege Disabled'}}}};
        if($Executable -like '*docker*' -and $Arguments[0] -eq 'info'){{return [pscustomobject]@{{code=$(if($script:docker){{0}}else{{1}});text=$script:docker}}}};
        if($Executable -like '*docker*'){{return [pscustomobject]@{{code=0;text=$script:image}}}};
        if($Arguments -contains 'health'){{return [pscustomobject]@{{code=$(if($script:health){{0}}else{{1}});text=$script:health}}}};
        [pscustomobject]@{{code=1;text='unexpected native call'}}}};
      function Invoke-Reviewed {{param([string]$Label,[string]$Script,[string[]]$Arguments)$script:calls.Add('reviewed:'+(Split-Path -Leaf $Script)+' '+($Arguments|Where-Object {{$_ -like '-*'}}) -join ' ');
        if($Script -like '*install*' -and $Arguments -contains '-Apply'){{if($script:applyOut -eq '{RECEIPT_READY}'){{$null=New-Item -ItemType Directory -Path $script:r4Root -Force;Set-Content -LiteralPath $script:receiptPath -Value $script:applyOut}};return [pscustomobject]@{{code=0;text=$script:applyOut}}}};
        if($Script -like '*install*'){{return [pscustomobject]@{{code=0;text=$script:planOut}}}};
        if($Arguments -contains '-Apply'){{if($script:switchOut -like '*HEALTH_VERIFIED*'){{$null=New-Item -ItemType Directory -Path $script:attemptRoot -Force;Set-Content -LiteralPath $script:startReceipt -Value '{{}}'}};return [pscustomobject]@{{code=0;text=$script:switchOut}}}};
        [pscustomobject]@{{code=0;text=$script:rplanOut}}}};
      function Get-Command {{param($Name,$ErrorAction)}};
      function Test-Path {{param($LiteralPath,$Path,$PathType,$ErrorAction)$p=$(if($LiteralPath){{$LiteralPath}}else{{$Path}});if($p -like 'C:\\Program Files\\Docker\\*'){{return $true}};if($PathType){{Microsoft.PowerShell.Management\\Test-Path -LiteralPath $p -PathType $PathType}}else{{Microsoft.PowerShell.Management\\Test-Path -LiteralPath $p}}}};
      {overrides}
      $stages=@{{'0'={{Invoke-Stage0}};'1'={{Invoke-Stage1}};'2'={{Invoke-Stage2}};'34'={{Invoke-Stage3And4}};'5'={{Invoke-Stage5}};'6'={{Invoke-Stage6}}}};
      $order=$(if('{stage}' -eq 'all'){{@('0','1','2','34','5','6')}}else{{@('{stage}'.Split(','))}});
      $halted=$false;$reason='';$trace='';$script:outLines=[Collections.Generic.List[string]]::new();
      try{{foreach($s in $order){{& $stages[$s] 6>&1|ForEach-Object {{$script:outLines.Add([string]$_)}}}}}}catch{{$halted=$true;$reason=$_.Exception.Message;$trace=$_.ScriptStackTrace}};
      [ordered]@{{stopped=$halted;reason=$reason;trace=$trace;calls=@($script:calls);killed=@($script:killed);unregistered=@($script:unregistered);stopped_tasks=@($script:stoppedTasks);
        already_started=$script:alreadyStarted;built=$script:built;output=($script:outLines -join "`n");
        launcher_moved=(-not (Microsoft.PowerShell.Management\\Test-Path -LiteralPath $script:legacyLauncher));
        trees_moved=@($script:legacyTrees|ForEach-Object {{-not (Microsoft.PowerShell.Management\\Test-Path -LiteralPath $_)}});
        archive_entries=@(if(Microsoft.PowerShell.Management\\Test-Path -LiteralPath $script:archive){{Get-ChildItem -LiteralPath $script:archive -Force|ForEach-Object Name}})}}|ConvertTo-Json -Compress -Depth 4
    """
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', prelude], capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_first_run_happy_path_runs_every_stage_in_order(tmp_path):
    value = run_flow(tmp_path)
    assert not value['stopped'], value['reason']
    reviewed = [c for c in value['calls'] if c.startswith('reviewed:')]
    assert reviewed == ['reviewed:install-stopped-runtime-r4.ps1 -Manifest -ManifestSha256', 'reviewed:install-stopped-runtime-r4.ps1 -Manifest -ManifestSha256 -Apply',
                        'reviewed:retarget-warden-r4.ps1 -Attempt', 'reviewed:retarget-warden-r4.ps1 -Apply -Start -Attempt']
    assert value['calls'].index('owner-check') < value['calls'].index(reviewed[0])
    assert value['unregistered'] == ['CoChemHostWarden_V412', 'CoChem V4.1.2 Swarm', 'CoChem-Fixture-TaskAcl-20261008-bbd9bf8061764e6ba8cdefa47fb6a149-create18']
    assert value['stopped_tasks'] == ['CoChemHostWarden_V412'], 'only the running task is stopped before unregistering'
    assert sorted(value['killed']) == [4516, 7340], 'the observer (9472) is never a victim'
    assert value['launcher_moved'] and value['trees_moved'] == [True, True]
    assert sorted(value['archive_entries']) == ['CoChem-Fixture-TaskAcl-20261008-bbd9bf8061764e6ba8cdefa47fb6a149-create18.xml', 'CoChemHostWarden_V412.xml', 'CoChem_V4.1.2_Swarm.xml', 'cochem_startup.vbs', 'v4.1.2', 'v4.2.0']
    assert 'health: answered as SYSTEM' in value['output'] and 'self-rebound' in value['output']
    assert 'installer preflight: clean' in value['output'] and value['output'].index('installer preflight: clean') < value['output'].index('Stage 1:')


@pytest.mark.parametrize('case', ['docker_engine_down', 'docker_missing_limit', 'docker_no_seccomp', 'docker_no_id', 'image_missing', 'preflight_holds', 'port_busy_first_run', 'receipt_but_port_free',
                                  'exclusion_missing', 'worker_dir_missing', 'r4_root_without_receipt', 'port_query_error', 'pypi_unreachable', 'attempt_root_stale'])
def test_stage0_stops_before_anything_is_removed(tmp_path, case):
    overrides = {
        'docker_engine_down': "$script:docker='';",
        'docker_no_id': "$script:docker='" + DOCKER_OK.replace('"OSType"', '"ID":"","OSType"') + "';",
        'pypi_unreachable': "$script:pypi=$false;",
        'attempt_root_stale': "$null=New-Item -ItemType Directory -Path $script:attemptRoot -Force;",
        'docker_missing_limit': "$script:docker='" + DOCKER_OK.replace('"PidsLimit":true', '"PidsLimit":false') + "';",
        'docker_no_seccomp': "$script:docker='" + DOCKER_OK.replace('"name=seccomp,profile=builtin",', '') + "';",
        'image_missing': "$script:image='Error: No such image';",
        'preflight_holds': "$script:planOut='{\"mode\":\"READ_ONLY_PLAN\",\"holds\":[\"Reviewed function source changed\"]}';",
        'port_busy_first_run': "$script:listeners[47824]=1;",
        'receipt_but_port_free': "$null=New-Item -ItemType Directory -Path $script:attemptRoot -Force;Set-Content -LiteralPath $script:startReceipt -Value '{}';",
        'exclusion_missing': "function Get-MpPreference {[pscustomobject]@{ExclusionPath=@(1..5|ForEach-Object {Join-Path $script:workerRoot ('slot'+$_)})}};",
        'worker_dir_missing': "Remove-Item -LiteralPath (Join-Path $script:workerRoot 'slot6') -Recurse -Force;",
        'r4_root_without_receipt': "$null=New-Item -ItemType Directory -Path $script:r4Root -Force;",
        'port_query_error': "$script:listeners[47824]='error';",
    }[case]
    value = run_flow(tmp_path, overrides)
    assert value['stopped'] and value['reason'].startswith('SERIES-STOP: '), (value['reason'], value['trace'])
    assert value['unregistered'] == [] and value['killed'] == [] and not value['launcher_moved'] and value['trees_moved'] == [False, False]
    assert not any(c.endswith('-Apply') or '-Start' in c for c in value['calls']), 'no mutation after a stage-0 stop'
    expected = {'docker_engine_down': 'engine is not answering', 'docker_missing_limit': 'PidsLimit=False', 'docker_no_seccomp': 'no seccomp', 'image_missing': 'execution image is missing',
                'preflight_holds': 'installer preflight reports holds', 'port_busy_first_run': 'has not started a Warden', 'receipt_but_port_free': 'controller is not running',
                'exclusion_missing': 'Defender exclusions missing for: ', 'worker_dir_missing': 'Worker directories missing', 'r4_root_without_receipt': 'exists without a successful receipt',
                'port_query_error': 'could not be established', 'pypi_unreachable': 'PyPI (https://pypi.org/simple/) is not reachable', 'attempt_root_stale': 'Attempt root exists without a start receipt',
                'docker_no_id': 'engine ID missing'}[case]
    assert expected in value['reason'], value['reason']
    if case == 'exclusion_missing':
        assert value['reason'].rstrip(')').split('slot')[-1].startswith('6'), 'only slot6 is missing in this fixture'


def test_rerun_with_receipt_and_listening_controller_goes_straight_to_the_health_gate(tmp_path):
    overrides = ("$null=New-Item -ItemType Directory -Path $script:attemptRoot -Force;Set-Content -LiteralPath $script:startReceipt -Value '{}';"
                 "$null=New-Item -ItemType Directory -Path $script:r4Root -Force;Set-Content -LiteralPath $script:receiptPath -Value '" + RECEIPT_READY + "';"
                 "$script:listeners[47824]=1;$script:tasks=@{};$script:processes=@();")
    value = run_flow(tmp_path, overrides)
    assert not value['stopped'], value['reason']
    assert value['already_started'] is True and value['built'] is True
    assert not any(c.startswith('reviewed:') for c in value['calls']), 'neither installer nor retarget runs again'
    assert value['output'].count('already done by this attempt') == 2 and 'health: answered as SYSTEM' in value['output']
    assert value['archive_entries'] == [] and not value['launcher_moved'], 'a rerun after a verified start touches nothing in stage 1'


def test_rerun_after_a_successful_build_skips_the_installer_but_switches(tmp_path):
    overrides = "$null=New-Item -ItemType Directory -Path $script:r4Root -Force;Set-Content -LiteralPath $script:receiptPath -Value '" + RECEIPT_READY + "';"
    value = run_flow(tmp_path, overrides)
    assert not value['stopped'], value['reason']
    reviewed = [c for c in value['calls'] if c.startswith('reviewed:')]
    assert reviewed == ['reviewed:retarget-warden-r4.ps1 -Attempt', 'reviewed:retarget-warden-r4.ps1 -Apply -Start -Attempt']


@pytest.mark.parametrize('case', ['build_fails', 'plan_holds', 'plan_rights_unverified', 'switch_held', 'health_not_system', 'health_wrong_root', 'health_fails', 'legacy_warden_survives'])
def test_later_stops_leave_a_clear_reason_and_no_further_mutation(tmp_path, case):
    overrides = {
        'build_fails': "$script:applyOut='{\"mode\":\"HELD\"}';",
        'plan_holds': "$script:rplanOut='{\"mode\":\"READ_ONLY_PLAN\",\"holds\":[\"A controller process is alive\"],\"backup_copy_rights_verified\":true}';",
        'plan_rights_unverified': "$script:rplanOut='{\"mode\":\"READ_ONLY_PLAN\",\"holds\":[],\"backup_copy_rights_verified\":null}';",
        'switch_held': "$script:switchOut='{\"status\":\"WARDEN_RETARGETED_TO_R4_NOT_STARTED\",\"started\":false}';",
        'health_not_system': "$script:health=$script:health.Replace('SYSTEM','ansac');",
        'health_wrong_root': "$script:health=$script:health.Replace('.venv','.venv-r3');",
        'health_fails': "$script:health='';",
        'legacy_warden_survives': "$script:killStops=$false;$script:listeners[47821]=1;",
    }[case]
    value = run_flow(tmp_path, overrides)
    assert value['stopped'] and value['reason'].startswith('SERIES-STOP: '), value
    reviewed = [c for c in value['calls'] if c.startswith('reviewed:')]
    expected_reason, expected_last = {
        'build_fails': ('did not finish with FRESH_STOPPED_RUNTIME_READY', '-Apply'),
        'plan_holds': ('elevated plan reports holds: A controller process is alive', 'retarget-warden-r4.ps1 -Attempt'),
        'plan_rights_unverified': ('could not verify the backup copy rights', 'retarget-warden-r4.ps1 -Attempt'),
        'switch_held': ('retarget-held.json / start-held.json', '-Apply -Start -Attempt'),
        'health_not_system': ('did not answer /health as SYSTEM from the r4 root', '-Apply -Start -Attempt'),
        'health_wrong_root': ('did not answer /health as SYSTEM from the r4 root', '-Apply -Start -Attempt'),
        'health_fails': ('did not answer /health as SYSTEM from the r4 root', '-Apply -Start -Attempt'),
        'legacy_warden_survives': ('still listens on 47821', 'install-stopped-runtime-r4.ps1 -Manifest -ManifestSha256'),
    }[case]
    assert expected_reason in value['reason'], value['reason']
    assert reviewed[-1].endswith(expected_last), reviewed
    assert 'DONE' not in value['output']
    if case == 'legacy_warden_survives':
        assert 'WARNING: legacy processes survived the sweep' in value['output'] and value['trees_moved'] == [False, False], 'trees stay until the warden is gone'


def test_tree_move_failure_is_a_warning_not_a_stop(tmp_path):
    overrides = "function Move-Item {param($LiteralPath,$Destination)if($LiteralPath -like '*v4.1.2'){throw 'in use'};Microsoft.PowerShell.Management\\Move-Item -LiteralPath $LiteralPath -Destination $Destination};"
    value = run_flow(tmp_path, overrides)
    assert not value['stopped'], value['reason']
    assert 'WARNING: could not move' in value['output'] and value['trees_moved'] == [False, True] and value['launcher_moved']


def test_observer_wait_reports_but_never_stops(tmp_path):
    overrides = "Set-Content -LiteralPath $script:runtimeJson -Value '{\"observed_controller_state\":\"unavailable\"}';function Get-Date {param($x)if($null -ne $script:clock){$script:clock=$script:clock.AddSeconds(70)}else{$script:clock=[DateTime]::new(2026,10,10,20,0,0)};$script:clock};"
    value = run_flow(tmp_path, overrides, stage='6')
    assert not value['stopped'], value['reason']
    assert 'NOTE: held supervisor observer state is "unavailable"' in value['output']


def test_helpers_handle_preamble_and_missing_executables(tmp_path):
    body = ("$j=Get-JsonTail (\"warning {with braces}`nmore text`n{`n  \"\"mode\"\": \"\"READ_ONLY_PLAN\"\",`n  \"\"holds\"\": []`n}\");"
            "$miss=Invoke-Native (Join-Path $w 'no-such.exe') @('x');"
            "[ordered]@{mode=$j.mode;holds=@($j.holds).Count;miss_code=$miss.code;miss_text=$miss.text}|ConvertTo-Json -Compress")
    work = tmp_path / 'w'
    work.mkdir()
    prelude = (f"$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('{ps(SCRIPT)}',[ref]$tokens,[ref]$errors);"
               "foreach($f in $ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){. ([scriptblock]::Create($f.Extent.Text))};"
               f"$w='{ps(work)}';")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', prelude + body], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['mode'] == 'READ_ONLY_PLAN' and value['holds'] == 0
    assert value['miss_code'] is None and value['miss_text'].startswith('invoke failed:')
