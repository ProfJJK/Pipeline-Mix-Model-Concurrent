"""Inert PS5.1 fixtures for retarget-warden-r4.ps1 (v2.1).

No task is registered, updated or started; no privileged API runs. Functions are
extracted from the script text and exercised against fixtures that model the COM
task objects (including RegisterTaskDefinition and Run) so the mutation and start
paths are driven end to end with stubs. Backup tests run the real robocopy (without
backup mode, which needs the elevated token) and the real verification helper against
temporary SQLite databases.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys

import pytest

ROOT = Path(__file__).parent
SCRIPT = ROOT / 'retarget-warden-r4.ps1'
HELPER = ROOT / 'backup-private-databases-r4.py'
R3 = Path(r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r3')
R3_PY = str(R3 / '.venv' / 'Scripts' / 'python.exe')
R4_ROOT = r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4'
R4_PY = R4_ROOT + r'\.venv\Scripts\python.exe'
BASE_PY = r'C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe'
CONFIG = r'C:\Program Files\CoChem\WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json'
QUEUE_OLD = r'C:\ProgramData\CoChemPipeline427\private\queue-commissioning-20261007-r3-v1'
QUEUE_NEW = r'C:\ProgramData\CoChemPipeline427\private\queue-retarget-20261010-r4-v1'
SDDL = 'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'
TEST_PY = R3_PY if Path(R3_PY).exists() else sys.executable
OBSERVER_PATTERN = (r'\\SupervisorObservation4\.2\.7-windows-20261007-r3-v1\\held-supervisor-observation-r3-v1\.py"?\s+--observe\b'
                    r'|\\ResourceObservation4\.2\.7-windows-20261008-r3-v4\\package\\observe_resources\.py"?\s+--run-observer\b')


def ps(path):
    return str(path).replace("'", "''")


def run(body, timeout=90):
    prelude = f"""$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;
      foreach($m in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){{Import-Module (Join-Path $PSHOME "Modules\\$m\\$m.psd1")}};
      $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('{ps(SCRIPT)}',[ref]$tokens,[ref]$errors);
      if($errors.Count){{throw ($errors|Out-String)}};
      foreach($f in $ast.FindAll({{param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]}},$true)){{. ([scriptblock]::Create($f.Extent.Text))}};
      $script:r3Root='C:\\Program Files\\CoChem\\Pipeline4.2.7-windows-20261007-r3';$script:r3Python='{R3_PY}';
      $script:r4Root='{R4_ROOT}';$script:r4Python='{R4_PY}';$script:r4SourceRoot='{R4_ROOT}\\.venv\\Lib';
      $script:basePythonRoot='C:\\Program Files\\CoChem\\Toolchain4.2.7-windows-20261006\\Python312';$script:basePython='{BASE_PY}';
      $script:commissioningConfig='{CONFIG}';$script:queueOld='{QUEUE_OLD}';$script:queueNew='{QUEUE_NEW}';$script:taskName='CoChem-4.2.7-Warden';$script:port=47824;$script:startWaitSeconds=3;
      $script:Attempt='v1';$script:admin=$false;$script:configPin='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c';$script:repairPin='e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc';
      $script:observerPattern='{OBSERVER_PATTERN}';$script:backupCopyFlags=@();$script:probePython='{TEST_PY}';$script:probePythonPin='';
      $script:clientConfig='C:\\Users\\ansac\\CoChem427\\pipeline-client-r3.json';
      $regAst=[Management.Automation.Language.Parser]::ParseFile('{ps(ROOT / 'register-stopped-warden-r3.ps1')}',[ref]$tokens,[ref]$errors);
      foreach($f in $regAst.FindAll({{param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Assert-RegisteredTaskAcl'}},$true)){{. ([scriptblock]::Create($f.Extent.Text))}};
    """
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', prelude + body],
                          capture_output=True, text=True, timeout=timeout)


TASK_FIXTURE = r'''
      $script:registered=@();$script:runs=0
      function New-FixtureFolder {param([hashtable]$Overrides)
        $v=@{Enabled=$true;State=3;Instances=0;LastTaskResult=0;UserId='SYSTEM';LogonType=5;RunLevel=1;Triggers=0;Actions=1;MultipleInstances=2;ExecutionTimeLimit='PT0S';RestartCount=0;AllowDemandStart=$true;
             ActionType=0;Path='R3PY';Arguments=('-I -B -m cochem_pipeline daemon --config "CONFIG" --queue-launch-output "QUEUEOLD"');WorkingDirectory='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r3';Sddl='SDDL';
             DenyDefinition=$false;DenyGetTask=$false;Absent=$false;RegisterApplies=$true;RunState=4;RunInstances=1;RunThrows=$false;DenyAfterRun=$false;
             Xml='<Task xmlns="urn:x"><RegistrationInfo><Description>d</Description></RegistrationInfo><Settings><Enabled>true</Enabled></Settings><Actions><Exec><Command>c</Command></Exec></Actions></Task>'};
        foreach($k in $Overrides.Keys){$v[$k]=$Overrides[$k]};
        $script:fx=$v
        $script:action=[pscustomobject]@{Type=$v.ActionType;Path=$v.Path;Arguments=$v.Arguments;WorkingDirectory=$v.WorkingDirectory};
        $actions=[pscustomobject]@{Count=$v.Actions};$actions|Add-Member ScriptMethod Item {param($i)if($script:fx.DenyDefinition){throw [Runtime.InteropServices.COMException]::new('denied',-2147024891)};$script:action};
        $definition=[pscustomobject]@{Principal=[pscustomobject]@{UserId=$v.UserId;LogonType=$v.LogonType;RunLevel=$v.RunLevel};Triggers=[pscustomobject]@{Count=$v.Triggers};Actions=$actions;
          Settings=[pscustomobject]@{MultipleInstances=$v.MultipleInstances;ExecutionTimeLimit=$v.ExecutionTimeLimit;RestartCount=$v.RestartCount;AllowDemandStart=$v.AllowDemandStart};RegistrationInfo=[pscustomobject]@{Description='d'}};
        $script:task=[pscustomobject]@{Enabled=$v.Enabled;State=$v.State;LastTaskResult=$v.LastTaskResult;Xml=$v.Xml;Definition=$definition};
        $script:instances=$v.Instances;$script:instanceGuid='{00000000-0000-0000-0000-00000000aaaa}'
        $script:task|Add-Member ScriptMethod GetInstances {param($n)$items=[pscustomobject]@{Count=$script:instances};$items|Add-Member ScriptMethod Item {param($i)[pscustomobject]@{InstanceGuid=$script:instanceGuid}};$items};
        $script:task|Add-Member ScriptMethod GetSecurityDescriptor {param($n)$script:fx.Sddl};
        $script:task|Add-Member ScriptMethod Run {param($a)if($script:fx.RunThrows){throw [Runtime.InteropServices.COMException]::new('run refused',-2147216615)};$script:runs++;$script:task.State=$script:fx.RunState;$script:instances=$script:fx.RunInstances;$inst=[pscustomobject]@{InstanceGuid=$script:instanceGuid};$inst|Add-Member ScriptMethod Refresh {};$inst};
        $folder=[pscustomobject]@{};$folder|Add-Member ScriptMethod GetTask {param($name)
          if($script:fx.Absent){throw [Runtime.InteropServices.COMException]::new('absent',-2147024894)};
          if($script:fx.DenyGetTask -or ($script:fx.DenyAfterRun -and $script:runs -gt 0)){throw [Runtime.InteropServices.COMException]::new('denied',-2147024891)};
          if($name -ne 'CoChem-4.2.7-Warden'){throw [Runtime.InteropServices.COMException]::new('absent',-2147024894)};$script:task};
        $folder|Add-Member ScriptMethod RegisterTaskDefinition {param($name,$def,$flags,$user,$pw,$logon,$sddl)
          $script:registered+=[pscustomobject]@{name=$name;flags=$flags;user=$user;logon=$logon;sddl=$sddl};
          if(-not $script:fx.RegisterApplies){$script:action.Path=$script:fx.Path;$script:action.WorkingDirectory=$script:fx.WorkingDirectory;$script:action.Arguments=$script:fx.Arguments}
          else{$script:task.Xml=$script:fx.Xml.Replace('<Command>c</Command>','<Command>r4</Command>').Replace('<Description>d</Description>','<Description>r4</Description>')}};
        $folder
      };
'''.replace('R3PY', R3_PY).replace('CONFIG', CONFIG).replace('QUEUEOLD', QUEUE_OLD).replace('SDDL', SDDL)

STUBS = r'''
      function New-ProtectedDirectory {param($Path)$null=[IO.Directory]::CreateDirectory($Path)};
      function New-PrivateDirectory {param($Path)$null=[IO.Directory]::CreateDirectory($Path)};
      function Assert-CodeTreeOnce {param($Path)1};
      function Write-RegistrationControl {param($Path,$Text)if(Test-Path -LiteralPath $Path){throw ('control exists: '+$Path)};[IO.File]::WriteAllText($Path,$Text);(Get-FileHash -LiteralPath $Path).Hash.ToLowerInvariant()};
      function Backup-PrivateDatabases {param($Destination)$script:backups++;[ordered]@{copy_exit_code=1;witness_exit_code=1;copy_flags=@();verification=[ordered]@{schema='cochem-private-database-backup/3';databases=@()}}};
      function Get-OtherDaemonTaskStates {param($Folder)@([pscustomobject]@{name='CoChem-4.2.7-Supervisor';state='ABSENT';active=$false})};
      function Get-WorkerProcesses {[ordered]@{workers=@();uninspectable_processes=@();exited_during_sweep=0;authoritative=$true}};
      function Test-LoopbackFree {$true};
      function Test-BackupCopyRights {$script:rightsProbes++;$true};
      $script:presenceCalls=0;$script:backups=0;$script:rightsProbes=0
      function Get-ControllerPresence {$script:presenceCalls++;$alive=($script:fixtureAliveAt -contains $script:presenceCalls);[ordered]@{port=47824;listening=$(if($alive){1}else{0});controller_processes=@();observer_processes=@(@{pid=9472;command='observer'});client_processes=@();unclassified_runtime_processes=@();uninspectable_python_processes=0;authoritative=$true}};
'''


def test_script_parses_and_pins_the_reviewed_inputs():
    text = SCRIPT.read_text(encoding='utf-8')
    helper_pin = hashlib.sha256(HELPER.read_bytes()).hexdigest()
    assert f"$backupHelperPin='{helper_pin}'" in text, 'backup helper pin must match the file on disk'
    for pin in ("'1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189'",
                "'e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc'",
                "'4bf82adb21852c52df8dd20c112b8df912b4813c225aa66cdfdcb272fe148bd3'",
                "'135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'",
                "$probePythonPin='d8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa'",
                "Pipeline4.2.7-windows-20261009-r4'", "WardenCommissioning4.2.7-windows-20261007-r3-v1'"):
        assert pin in text, pin
    for forbidden in ('Unregister-ScheduledTask', 'Stop-ScheduledTask', 'Register-ScheduledTask', 'Start-ScheduledTask', 'schtasks', 'Start-Process',
                      'Stop-Process', 'taskkill', 'Remove-Item', 'Stop-Service', '.Stop(', 'DeleteTask', 'python -c', "-c $script", '/MIR', '/MOV', '/PURGE'):
        assert forbidden not in text, forbidden
    assert text.count('.Run($null)') == 1 and 'RegisterTaskDefinition($script:taskName,$definition,4,' in text
    assert "$ErrorActionPreference='Continue'" in text, 'native commands must be judged by exit code'
    assert '$startWaitSeconds=240' in text and 'AddSeconds($script:startWaitSeconds)' in text, 'the production start wait is 240 s'
    assert "$backupCopyFlags=@('/B')" in text, 'production copies use robocopy backup semantics'
    assert "'/A-:RSH'" in text and "'/XJ'" in text and "$arguments+='/L'" in text, 'copies strip attributes, skip junctions, and the rights probe lists only'
    assert text.count("'CmdletizationQuery_NotFound*'") == 2, 'only the no-match error means nothing listens (presence and proof)'
    assert text.count("'-X','utf8'") == 3, 'every Python child runs with -X utf8'
    assert 'retarget-held.json' in text and 'start-held.json' in text and "$witness=$Destination+'-witness'" in text
    assert "'CimCmdlets','NetTCPIP'" in text, 'the CIM and TCP modules are imported by path'
    assert 'Get-Process -IncludeUserName' in text and '$exited++' in text, 'the elevated worker sweep uses one username call and tolerates exits'


def test_expected_arguments_match_the_commissioned_task_xml_on_disk():
    raw = Path(r'C:\Program Files\CoChem\WardenCommissioning4.2.7-windows-20261007-r3-v1\disabled-warden-task.xml').read_bytes()
    xml = raw.decode('utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig')  # header says UTF-16, bytes are UTF-8
    result = run(f"Get-ExpectedArguments '{CONFIG}' '{QUEUE_OLD}'")
    assert result.returncode == 0, result.stderr
    expected = result.stdout.strip()
    assert expected.replace('"', '&quot;') in xml or expected in xml


@pytest.mark.parametrize('case', ['stderr_exit_0', 'stderr_exit_1', 'stdout_only', 'utf8_stdout', 'missing_executable'])
def test_native_commands_are_judged_by_exit_code_not_stderr(case):
    program = {'stderr_exit_0': "import sys;sys.stderr.write('warn');print('out');sys.exit(0)",
               'stderr_exit_1': "import sys;sys.stderr.write('boom');sys.exit(1)",
               'stdout_only': "print('{\"ok\":1}')",
               'utf8_stdout': "print('{\"mark\":\"\\u2713 caf\\u00e9\"}')",
               'missing_executable': "print('unused')"}[case]
    fixture = ROOT / '.native-judge-fixture.py'
    fixture.write_text(program, encoding='utf-8')
    executable = TEST_PY if case != 'missing_executable' else str(ROOT / 'no-such-python.exe')
    try:
        result = run(f"$refused=$false;$r=$null;try{{$r=Invoke-NativeJudged '{executable}' @('-I','-B','-X','utf8','{ps(fixture)}')}}catch{{$refused=$true}};"
                     "[ordered]@{refused=$refused;code=$(if($r){$r.code}else{$null});stdout=$(if($r){@([int[]][char[]]$r.stdout)}else{@()});stderr=$(if($r){$r.stderr}else{$null});preference=[string]$ErrorActionPreference;encoding=[Console]::OutputEncoding.WebName}|ConvertTo-Json -Compress")
    finally:
        fixture.unlink()
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    stdout = ''.join(chr(code) for code in value['stdout'])  # code points, so the test's own pipe encoding cannot interfere
    assert value['preference'] == 'Stop'
    if case == 'missing_executable':
        assert value['refused'] is True
        return
    assert value['refused'] is False and value['encoding'] != 'utf-8', 'the console encoding must be restored'
    assert value['code'] == (1 if case == 'stderr_exit_1' else 0)
    if case == 'stderr_exit_0':
        assert stdout == 'out' and 'warn' in value['stderr']
    if case == 'stdout_only':
        assert json.loads(stdout) == {'ok': 1}
    if case == 'utf8_stdout':
        assert json.loads(stdout) == {'mark': '\u2713 caf\u00e9'}, 'UTF-8 child output must be decoded as UTF-8'


@pytest.mark.parametrize('case', ['readable', 'absent', 'denied', 'definition_denied', 'other_error'])
def test_task_state_is_exact_or_explicitly_deferred(case):
    overrides = {'absent': '@{Absent=$true}', 'denied': '@{DenyGetTask=$true}', 'definition_denied': '@{DenyDefinition=$true}',
                 'other_error': '@{}', 'readable': '@{}'}[case]
    body = TASK_FIXTURE + f"$folder=New-FixtureFolder {overrides};"
    if case == 'other_error':
        body += "$folder|Add-Member -Force ScriptMethod GetTask {param($n)throw [Runtime.InteropServices.COMException]::new('other',-2147216625)};"
    body += r'''
      $refused=$false;$state=$null;$message='';try{$state=Get-WardenTaskState $folder}catch{$refused=$true;$message=$_.Exception.Message};
      [ordered]@{refused=$refused;readable=$(if($null -ne $state){$state.readable}else{$null});message=$message}|ConvertTo-Json -Compress
    '''
    result = run(body)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    if case == 'readable':
        assert value == {'refused': False, 'readable': True, 'message': ''}
    elif case in ('denied', 'definition_denied'):
        assert value['refused'] is False and value['readable'] is False
    elif case == 'absent':
        assert value['refused'] and 'absent' in value['message']
    else:
        assert value['refused'] and 'unknown' in value['message']


SOURCE_CASES = {
    'valid': ('@{}', ''), 'running': ('@{State=4}', 'running or queued'), 'queued': ('@{State=2}', 'running or queued'),
    'instances': ('@{Instances=1}', 'running or queued'), 'principal': ("@{UserId='ansac'}", 'exact reviewed SYSTEM'),
    'logon': ('@{LogonType=2}', 'exact reviewed SYSTEM'), 'trigger': ('@{Triggers=1}', 'exact reviewed SYSTEM'),
    'two_actions': ('@{Actions=2}', 'exact reviewed SYSTEM'), 'limit': ("@{ExecutionTimeLimit='PT8M'}", 'exact reviewed SYSTEM'),
    'restart': ('@{RestartCount=1}', 'exact reviewed SYSTEM'), 'wrong_path': ("@{Path='C:\\other\\python.exe'}", 'pinned r3 commissioning action'),
    'wrong_args': ("@{Arguments='-I -B -m cochem_pipeline daemon --config \"x\"'}", 'pinned r3 commissioning action'),
    'wrong_workdir': ("@{WorkingDirectory='C:\\Program Files\\CoChem'}", 'pinned r3 commissioning action'),
    'wrong_sddl': ("@{Sddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;BU)'}", 'ownership/private DACL'),
    'already_r4': (f"@{{Path='{R4_PY}'}}", 'pinned r3 commissioning action'),
}


@pytest.mark.parametrize('case', sorted(SOURCE_CASES))
def test_retarget_source_must_be_the_exact_commissioned_r3_task(case):
    overrides, expected_message = SOURCE_CASES[case]
    body = TASK_FIXTURE + f"$folder=New-FixtureFolder {overrides};" + r'''
      $refused=$false;$message='';try{Assert-RetargetSource (Get-WardenTaskState $folder)}catch{$refused=$true;$message=$_.Exception.Message};
      @{refused=$refused;message=$message}|ConvertTo-Json -Compress
    '''
    result = run(body)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['refused'] == (case != 'valid'), value
    assert expected_message in value['message']


@pytest.mark.parametrize('case', ['valid', 'still_r3', 'wrong_queue', 'sddl_changed', 'principal'])
def test_retargeted_task_readback_must_show_the_r4_action_and_preserved_dacl(case):
    new_args = f'-I -B -m cochem_pipeline daemon --config "{CONFIG}" --queue-launch-output "{QUEUE_NEW}"'
    base = f"@{{Path='{R4_PY}';WorkingDirectory='{R4_ROOT}';Arguments='{new_args}'"
    overrides = {'valid': base + '}', 'still_r3': '@{}', 'wrong_queue': base.replace(QUEUE_NEW, QUEUE_OLD) + '}',
                 'sddl_changed': base + ";Sddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;BU)'}", 'principal': base + ";UserId='ansac'}"}[case]
    body = TASK_FIXTURE + f"$folder=New-FixtureFolder {overrides};" + f"$expected='{SDDL}';" + r'''
      $refused=$false;try{Assert-RetargetedTask (Get-WardenTaskState $folder) $expected}catch{$refused=$true};@{refused=$refused}|ConvertTo-Json -Compress
    '''
    result = run(body)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['refused'] == (case != 'valid')


@pytest.mark.parametrize('case', ['only_action_and_description', 'settings_changed', 'principal_changed'])
def test_task_xml_comparison_ignores_only_actions_and_registration_info(case):
    before = ('<Task xmlns="urn:x"><RegistrationInfo><Date>1</Date><Description>d</Description></RegistrationInfo>'
              '<Principals><Principal><UserId>SYSTEM</UserId></Principal></Principals><Settings><Enabled>true</Enabled></Settings>'
              '<Actions><Exec><Command>r3</Command></Exec></Actions></Task>')
    after = before.replace('<Command>r3</Command>', '<Command>r4</Command>').replace('<Description>d</Description>', '<Description>r4</Description>')
    if case == 'settings_changed':
        after = after.replace('<Enabled>true</Enabled>', '<Enabled>false</Enabled>')
    if case == 'principal_changed':
        after = after.replace('<UserId>SYSTEM</UserId>', '<UserId>ansac</UserId>')
    result = run(f"$b='{before}';$a='{after}';$refused=$false;try{{Assert-TaskXmlOutsideActionUnchanged $b $a}}catch{{$refused=$true}};@{{refused=$refused}}|ConvertTo-Json -Compress")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['refused'] == (case != 'only_action_and_description')


@pytest.mark.parametrize('case', ['bool_true', 'string_true', 'int_one', 'int_exact', 'string_int', 'long_exact'])
def test_receipt_bindings_require_native_json_types(case):
    expression = {'bool_true': 'Test-ExactBool $true $true', 'string_true': "Test-ExactBool 'true' $true", 'int_one': 'Test-ExactBool 1 $true',
                  'int_exact': 'Test-ExactInt 166 166', 'string_int': "Test-ExactInt '166' 166", 'long_exact': 'Test-ExactInt ([long]166) 166'}[case]
    result = run(f"@{{value=[bool]({expression})}}|ConvertTo-Json -Compress")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['value'] == (case in ('bool_true', 'int_exact', 'long_exact'))


def make_wal_database(path: Path, clean: bool) -> None:
    """Create a WAL-mode database; clean=False leaves -wal/-shm orphaned, as after a crash."""
    program = ("import sqlite3,os,sys\np=sys.argv[1]\nc=sqlite3.connect(p)\nc.execute('PRAGMA journal_mode=WAL')\n"
               "c.execute('create table jobs(id integer primary key, name text)')\n"
               "c.executemany('insert into jobs(name) values (?)',[('a',),('b',),('c',)])\nc.commit()\n"
               + ("c.close()\n" if clean else "os._exit(0)\n"))
    subprocess.run([TEST_PY, '-I', '-c', program, str(path)], check=True, timeout=60)
    assert Path(str(path) + '-wal').exists() is (not clean), 'WAL presence must match the requested state'


def fingerprints(directory: Path) -> dict:
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.rglob('*')) if p.is_file()}


def test_backup_helper_verifies_copies_only_and_recovers_wal_content(tmp_path):
    destination = tmp_path / 'state-backup'
    (destination / 'containers').mkdir(parents=True)
    make_wal_database(destination / 'job_board.db', clean=True)
    make_wal_database(destination / 'containers' / 'containers.db', clean=False)
    (destination / 'containers' / 'containers.db-shm').unlink()  # robocopy never copies -shm
    result = subprocess.run([TEST_PY, '-I', '-B', '-X', 'utf8', str(HELPER), str(destination)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['schema'] == 'cochem-private-database-backup/3' and report['sources_opened'] is False
    assert {k['relative']: k['present'] for k in report['known_stores']} == {
        'job_board.db': True, 'containers\\containers.db': True, 'oracle\\tracking.db': False, 'operations\\objectives.db': False}
    assert report['other_stores'] == []
    by_name = {entry['relative']: entry for entry in report['databases']}
    assert by_name['containers\\containers.db']['wal_copied'] is True and by_name['job_board.db']['wal_copied'] is False
    for entry in by_name.values():
        assert entry['integrity'] == 'ok' and entry['tables'] == ['jobs'] and entry['wal_after_close_bytes'] == 0
        copy = sqlite3.connect(entry['backup_path'])
        assert [row[0] for row in copy.execute('SELECT name FROM jobs ORDER BY id')] == ['a', 'b', 'c'], 'WAL-only rows must be in the copy'
        copy.close()
    assert not list(destination.rglob('*.db-wal')) and (destination / 'verification.json').exists()
    again = subprocess.run([TEST_PY, '-I', '-B', '-X', 'utf8', str(HELPER), str(destination)], capture_output=True, text=True, timeout=60)
    assert again.returncode != 0 and 'VERIFICATION_EXISTS' in again.stderr


@pytest.mark.parametrize('case', ['usage', 'missing_required', 'shm_present', 'corrupt_copy', 'not_a_directory'])
def test_backup_helper_fails_closed(tmp_path, case):
    destination = tmp_path / 'state-backup'
    destination.mkdir()
    arguments = [str(destination)]
    if case == 'usage':
        arguments = []
    elif case == 'missing_required':
        make_wal_database(destination / 'other.db', clean=True)
    elif case == 'shm_present':
        make_wal_database(destination / 'job_board.db', clean=True)
        (destination / 'job_board.db-shm').write_bytes(b'\0' * 32)
    elif case == 'corrupt_copy':
        (destination / 'job_board.db').write_bytes(b'not a database at all' * 100)
    elif case == 'not_a_directory':
        arguments = [str(destination / 'absent')]
    result = subprocess.run([TEST_PY, '-I', '-B', '-X', 'utf8', str(HELPER), *arguments], capture_output=True, text=True, timeout=60)
    assert result.returncode != 0
    token = {'usage': 'USAGE', 'missing_required': 'REQUIRED_STORE_MISSING:job_board.db', 'shm_present': 'SHM_COPIED',
             'corrupt_copy': 'COPY_UNREADABLE', 'not_a_directory': 'DESTINATION_NOT_A_DIRECTORY'}[case]
    assert token in result.stderr, result.stderr
    assert not (destination / 'verification.json').exists()


def test_backup_function_copies_with_robocopy_and_leaves_sources_untouched(tmp_path):
    """The PowerShell wrapper runs robocopy, then the pinned helper by path, and parses its report."""
    private = tmp_path / 'private'
    (private / 'containers').mkdir(parents=True)
    (private / 'queue-old').mkdir()
    make_wal_database(private / 'job_board.db', clean=True)
    make_wal_database(private / 'containers' / 'containers.db', clean=False)
    (private / 'queue-old' / 'launch.log').write_text('not a database', encoding='utf-8')
    before = fingerprints(private)
    target = tmp_path / 'root'
    (target / 'state-backup').mkdir(parents=True)
    helper_pin = hashlib.sha256(HELPER.read_bytes()).hexdigest()
    body = (f"$script:targetRoot='{ps(target)}';$script:privateRoot='{ps(private)}';$script:r4Python='{TEST_PY}';"
            f"$script:backupHelper='{ps(HELPER)}';$script:backupHelperPin='{helper_pin}';"
            r'''
      function Copy-VerifiedPayload {param($File)if((Get-FileHash -LiteralPath $File.source).Hash.ToLowerInvariant() -ne $File.sha256){throw 'pin'};Copy-Item -LiteralPath $File.source -Destination $File.destination};
      function New-PrivateDirectory {param($Path)if(Test-Path -LiteralPath $Path){throw 'exists'};$null=[IO.Directory]::CreateDirectory($Path)};
      function Assert-PrivateAcl {param($Path)$script:aclChecks++};$script:aclChecks=0;
      $report=Backup-PrivateDatabases (Join-Path $script:targetRoot 'state-backup');
      [ordered]@{copy_exit=$report.copy_exit_code;witness_exit=$report.witness_exit_code;schema=$report.verification.schema;present=@($report.verification.known_stores|Where-Object {$_.present}|ForEach-Object {$_.relative});
        raw=@($report.raw_copies_sha256.Keys|Sort-Object);acl_checks=$script:aclChecks;helper_copied=(Test-Path (Join-Path $script:targetRoot 'backup-private-databases-r4.py'))}|ConvertTo-Json -Compress
    ''')
    result = run(body, timeout=120)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['copy_exit'] == 1 and value['witness_exit'] == 1 and value['schema'] == 'cochem-private-database-backup/3' and value['helper_copied'] is True
    assert value['present'] == ['job_board.db', 'containers\\containers.db']
    assert value['raw'] == ['containers\\containers.db', 'containers\\containers.db-wal', 'job_board.db'], 'the raw copies are hashed before verification'
    assert value['acl_checks'] >= 8, 'every copied file, directory and the report in both trees must be ACL-checked'
    assert fingerprints(private) == before, 'source bytes must be untouched and no -wal/-shm may appear beside a clean store'
    copied = sorted(str(p.relative_to(target / 'state-backup')) for p in (target / 'state-backup').rglob('*') if p.is_file())
    assert copied == ['containers\\containers.db', 'job_board.db', 'verification.json'], copied
    witness = target / 'state-backup-witness'
    raw = sorted(str(p.relative_to(witness)) for p in witness.rglob('*') if p.is_file())
    assert raw == ['containers\\containers.db', 'containers\\containers.db-wal', 'job_board.db'], 'the witness copy stays raw'
    assert hashlib.sha256((witness / 'job_board.db').read_bytes()).hexdigest() == before['job_board.db']
    rows = sqlite3.connect(str(target / 'state-backup' / 'containers' / 'containers.db')).execute('SELECT count(*) FROM jobs').fetchone()[0]
    assert rows == 3


@pytest.mark.parametrize('case', ['listable', 'missing_source'])
def test_backup_rights_probe_lists_without_writing(tmp_path, case):
    private = tmp_path / 'private'
    if case == 'listable':
        private.mkdir()
        make_wal_database(private / 'job_board.db', clean=True)
    target = tmp_path / 'root'
    body = (f"$script:targetRoot='{ps(target)}';$script:privateRoot='{ps(private)}';"
            "$refused=$false;$message='';$ok=$null;try{$ok=Test-BackupCopyRights}catch{$refused=$true;$message=$_.Exception.Message};"
            "[ordered]@{refused=$refused;ok=$ok;message=$message;root_created=(Test-Path -LiteralPath $script:targetRoot)}|ConvertTo-Json -Compress")
    result = run(body)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['root_created'] is False, 'the probe must not create the attempt root'
    if case == 'listable':
        assert value['refused'] is False and value['ok'] is True
    else:
        assert value['refused'] is True and 'robocopy exit 16' in value['message'] and 'whoami /priv' in value['message']


@pytest.mark.parametrize('case', ['robocopy_failure', 'helper_failure', 'empty_report', 'passes_differ'])
def test_backup_function_fails_closed_on_copy_or_report_errors(tmp_path, case):
    private = tmp_path / 'private'
    private.mkdir()
    make_wal_database(private / 'job_board.db', clean=True)
    target = tmp_path / 'root'
    (target / 'state-backup').mkdir(parents=True)
    helper_pin = hashlib.sha256(HELPER.read_bytes()).hexdigest()
    fake_copy = ("if($Executable -like '*robocopy*'){$null=[IO.Directory]::CreateDirectory($Arguments[1]);Copy-Item -LiteralPath (Join-Path $script:privateRoot 'job_board.db') -Destination $Arguments[1];"
                 "return [pscustomobject]@{code=1;stdout='';stderr=''}};")
    stub = {'robocopy_failure': "function Invoke-NativeJudged {param($Executable,$Arguments)if($Executable -like '*robocopy*'){return [pscustomobject]@{code=16;stdout='ERROR 5';stderr=''}};[pscustomobject]@{code=0;stdout='{}';stderr=''}};",
            'helper_failure': "function Invoke-NativeJudged {param($Executable,$Arguments)" + fake_copy + "[pscustomobject]@{code=1;stdout='';stderr='INTEGRITY_FAILED:job_board.db'}};",
            'empty_report': "function Invoke-NativeJudged {param($Executable,$Arguments)" + fake_copy + "[pscustomobject]@{code=0;stdout='';stderr=''}};",
            'passes_differ': ("function Invoke-NativeJudged {param($Executable,$Arguments)" + fake_copy.replace("return [pscustomobject]", "if($Arguments[1] -like '*-witness'){[IO.File]::AppendAllText((Join-Path $Arguments[1] 'job_board.db'),'x')};return [pscustomobject]")
                              + "[pscustomobject]@{code=0;stdout='{}';stderr=''}};")}[case]
    body = (f"$script:targetRoot='{ps(target)}';$script:privateRoot='{ps(private)}';$script:r4Python='{TEST_PY}';"
            f"$script:backupHelper='{ps(HELPER)}';$script:backupHelperPin='{helper_pin}';" + stub +
            r'''
      function Copy-VerifiedPayload {param($File)Copy-Item -LiteralPath $File.source -Destination $File.destination};
      function New-PrivateDirectory {param($Path)$null=[IO.Directory]::CreateDirectory($Path)};
      function Assert-PrivateAcl {param($Path)};
      $refused=$false;$message='';try{$null=Backup-PrivateDatabases (Join-Path $script:targetRoot 'state-backup')}catch{$refused=$true;$message=$_.Exception.Message};
      @{refused=$refused;message=$message}|ConvertTo-Json -Compress
    ''')
    result = run(body)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['refused'] is True
    assert {'robocopy_failure': 'robocopy exit 16', 'helper_failure': 'INTEGRITY_FAILED', 'empty_report': 'printed no report',
            'passes_differ': 'differ between passes: job_board.db'}[case] in value['message']


def test_private_acl_grants_only_system_and_administrators(tmp_path):
    result = run(f"$acl=New-PrivateAcl $true;$sids=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])|ForEach-Object {{$_.IdentityReference.Value}});"
                 "[ordered]@{owner=$acl.GetOwner([Security.Principal.SecurityIdentifier]).Value;sids=$sids;protected=$acl.AreAccessRulesProtected}|ConvertTo-Json -Compress")
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['owner'] == 'S-1-5-32-544' and sorted(value['sids']) == ['S-1-5-18', 'S-1-5-32-544'] and value['protected'] is True


NO_LISTENER = ("$e=[Management.Automation.ErrorRecord]::new([Exception]::new('No MSFT_NetTCPConnection objects found'),"
               "'CmdletizationQuery_NotFound,Get-NetTCPConnection','ObjectNotFound',$null);throw $e")


@pytest.mark.parametrize('case', ['free', 'listening', 'controller', 'client_only', 'unclassified', 'observer', 'uninspectable_elevated',
                                  'uninspectable_plan', 'query_error', 'command_not_found'])
def test_controller_presence_fails_closed_and_classifies_processes(case):
    observer_command = (f'"{BASE_PY}" -I -S -B -X "pycache_prefix=C:\\Program Files\\CoChem\\ResourceObservationState4.2.7-windows-20261008-r3-v4\\empty-cache" '
                        f'"C:\\Program Files\\CoChem\\ResourceObservation4.2.7-windows-20261008-r3-v4\\package\\observe_resources.py" --run-observer --source-manifest-sha256 x')
    held_command = ('"C:\\Program Files\\CoChem\\Supervisor4.2.7-windows-20261007-staging-v1\\.venv\\Scripts\\python.exe" -I -B '
                    '"C:\\Program Files\\CoChem\\SupervisorObservation4.2.7-windows-20261007-r3-v1\\held-supervisor-observation-r3-v1.py" --observe')
    procs = {
        'free': '@()', 'listening': '@()', 'query_error': '@()', 'command_not_found': '@()',
        'controller': "@([pscustomobject]@{ProcessId=7;ParentProcessId=1;Name='python.exe';ExecutablePath='C:\\elsewhere\\python.exe';CommandLine='python -m cochem_pipeline daemon --config x'})",
        'client_only': f"@([pscustomobject]@{{ProcessId=8;ParentProcessId=1;Name='python.exe';ExecutablePath='{R3_PY}';CommandLine='\"{R3_PY}\" -I -B -m cochem_pipeline mcp --client-config c.json'}})",
        'unclassified': f"@([pscustomobject]@{{ProcessId=9;ParentProcessId=1;Name='python.exe';ExecutablePath='{R3_PY}';CommandLine='\"{R3_PY}\" -c pass'}})",
        'observer': (f"@([pscustomobject]@{{ProcessId=9472;ParentProcessId=1;Name='python.exe';ExecutablePath='{BASE_PY}';CommandLine='{observer_command}'}},"
                     f"[pscustomobject]@{{ProcessId=9473;ParentProcessId=1;Name='python.exe';ExecutablePath='C:\\Program Files\\CoChem\\Supervisor4.2.7-windows-20261007-staging-v1\\.venv\\Scripts\\python.exe';CommandLine='{held_command}'}})"),
        'uninspectable_elevated': "@([pscustomobject]@{ProcessId=10;ParentProcessId=1;Name='python.exe';ExecutablePath=$null;CommandLine=$null})",
        'uninspectable_plan': "@([pscustomobject]@{ProcessId=10;ParentProcessId=1;Name='python.exe';ExecutablePath=$null;CommandLine=$null})",
    }[case]
    net = {'listening': "@([pscustomobject]@{LocalPort=47824;OwningProcess=1})", 'query_error': "throw 'provider failure'",
           'command_not_found': "$e=[Management.Automation.ErrorRecord]::new([Management.Automation.CommandNotFoundException]::new('not recognized'),'CommandNotFoundException','ObjectNotFound',$null);throw $e"
           }.get(case, NO_LISTENER)
    admin = '$true' if case != 'uninspectable_plan' else '$false'
    body = (f"$script:admin={admin};function Get-CimInstance {{param($ClassName,$Filter,$ErrorAction){procs}}};"
            f"function Get-NetTCPConnection {{param($LocalPort,$State,$ErrorAction){net}}};"
            r'''
      $refused=$false;$alive=$null;$p=$null;try{$p=Get-ControllerPresence;$alive=Test-ControllerAlive $p}catch{$refused=$true};
      [ordered]@{refused=$refused;alive=$alive;controllers=$(if($p){@($p.controller_processes).Count}else{-1});observers=$(if($p){@($p.observer_processes).Count}else{-1});
        clients=$(if($p){@($p.client_processes).Count}else{-1});unclassified=$(if($p){@($p.unclassified_runtime_processes).Count}else{-1});uninspectable=$(if($p){$p.uninspectable_python_processes}else{-1})}|ConvertTo-Json -Compress
    ''')
    result = run(body)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    if case in ('query_error', 'command_not_found'):
        assert value['refused'], 'an unanswerable port query (including a missing cmdlet) must be a hold'
        return
    assert not value['refused']
    assert value['alive'] == (case in ('listening', 'controller', 'unclassified', 'uninspectable_elevated'))
    assert (value['controllers'], value['observers'], value['clients'], value['unclassified'], value['uninspectable']) == {
        'free': (0, 0, 0, 0, 0), 'listening': (0, 0, 0, 0, 0), 'controller': (1, 0, 0, 0, 0), 'client_only': (0, 0, 1, 0, 0), 'unclassified': (0, 0, 0, 1, 0),
        'observer': (0, 2, 0, 0, 0), 'uninspectable_elevated': (0, 0, 0, 0, 1), 'uninspectable_plan': (0, 0, 0, 0, 1)}[case]


@pytest.mark.parametrize('case', ['clean', 'worker', 'worker_by_username', 'opaque_elevated', 'opaque_plan', 'kernel_pseudo_process', 'exited_during_sweep'])
def test_worker_scan_reports_uninspectable_processes(case):
    owner = {'clean': "[pscustomobject]@{ReturnValue=0;User='ansac'}", 'worker': "[pscustomobject]@{ReturnValue=0;User='CoChem422Worker3'}",
             'worker_by_username': "throw 'GetOwner must not be called when the username is known'",
             'opaque_elevated': "[pscustomobject]@{ReturnValue=2;User=$null}", 'opaque_plan': "throw 'denied'", 'kernel_pseudo_process': "[pscustomobject]@{ReturnValue=2;User=$null}",
             'exited_during_sweep': "throw [Microsoft.Management.Infrastructure.CimException]::new('Not found')"}[case]
    path = '$null' if case == 'kernel_pseudo_process' else "'C:\\x\\claude.exe'"
    admin = '$false' if case == 'opaque_plan' else '$true'
    usernames = "@([pscustomobject]@{Id=4;UserName='AETHERDESK\\CoChem422Worker2'})" if case == 'worker_by_username' else '@()'
    requery = '$null' if case == 'exited_during_sweep' else "[pscustomobject]@{ProcessId=4}"
    body = (f"$script:admin={admin};function Get-Process {{param([switch]$IncludeUserName,$ErrorAction)if(-not $script:admin){{throw 'requires elevated user rights'}};{usernames}}};"
            f"function Get-CimInstance {{param($ClassName,$Filter,$ErrorAction)if($Filter){{return {requery}}};@([pscustomobject]@{{ProcessId=4;Name='x';ExecutablePath={path}}})}};"
            f"function Invoke-CimMethod {{param($InputObject,$MethodName,$ErrorAction){owner}}};"
            r'''
      $r=Get-WorkerProcesses;$refused=$false;$message='';try{Assert-NoWorkers $r ' here'}catch{$refused=$true;$message=$_.Exception.Message};
      [ordered]@{workers=@($r.workers).Count;uninspectable=@($r.uninspectable_processes).Count;exited=$r.exited_during_sweep;refused=$refused;message=$message;user=$(if(@($r.workers).Count){$r.workers[0].user}else{$null})}|ConvertTo-Json -Compress
    ''')
    result = run(body)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    expected = {'clean': (0, 0, 0, False), 'worker': (1, 0, 0, True), 'worker_by_username': (1, 0, 0, True), 'opaque_elevated': (0, 1, 0, True),
                'opaque_plan': (0, 1, 0, False), 'kernel_pseudo_process': (0, 1, 0, False), 'exited_during_sweep': (0, 0, 1, False)}[case]
    assert (value['workers'], value['uninspectable'], value['exited'], value['refused']) == expected, value
    if case in ('worker', 'worker_by_username'):
        assert 'Slot worker processes are alive here' in value['message']
    if case == 'worker_by_username':
        assert value['user'] == 'AETHERDESK\\CoChem422Worker2'
    if case == 'opaque_elevated':
        assert 'could not be inspected' in value['message'] and '4 x' in value['message']


@pytest.mark.parametrize('case', ['free', 'held', 'interpreter_missing'])
def test_loopback_probe_binds_exclusively_with_the_pinned_interpreter(case):
    holder = None
    if case == 'held':
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.bind(('127.0.0.1', 0))
        holder.listen(1)
        port = holder.getsockname()[1]
    else:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
        probe.close()
    interpreter = TEST_PY if case != 'interpreter_missing' else str(ROOT / 'no-such-python.exe')
    body = (f"$script:port={port};$script:probePython='{interpreter}';$script:pinChecks=0;"
            "function Read-R3Control {param($Path,$Hash,$Maximum)$script:pinChecks++;if(-not (Test-Path -LiteralPath $Path)){throw 'pinned file missing'};$null};"
            "$refused=$false;$free=$null;try{$free=Test-LoopbackFree}catch{$refused=$true};[ordered]@{refused=$refused;free=$free;pin_checks=$script:pinChecks}|ConvertTo-Json -Compress")
    try:
        result = run(body)
    finally:
        if holder is not None:
            holder.close()
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['pin_checks'] == 1, 'the probe interpreter is verified before it runs'
    if case == 'interpreter_missing':
        assert value['refused'] is True
    else:
        assert value['refused'] is False and value['free'] == (case == 'free')


@pytest.mark.parametrize('case', ['ok', 'empty', 'array', 'missing_field', 'wrong_identity', 'nonzero_exit'])
def test_health_sample_requires_a_json_object_with_the_r4_identity(case):
    good = ('{"service_identity":"SYSTEM","source_root":"' + R4_ROOT.replace('\\', '\\\\') + '\\\\.venv\\\\Lib","pid":4242,"instance_id":"i","process_started_at":1.5,'
            '"active":[],"quarantined_slots":{}}')
    stdout = {'ok': good, 'empty': '', 'array': '[1,2]', 'missing_field': good.replace('"pid":4242,', ''), 'wrong_identity': good.replace('SYSTEM', 'ansac'), 'nonzero_exit': good}[case]
    code = 1 if case == 'nonzero_exit' else 0
    body = (f"function Invoke-NativeJudged {{param($Executable,$Arguments)[pscustomobject]@{{code={code};stdout='{stdout}';stderr='x'}}}};"
            "$s=Get-HealthSample;[ordered]@{ok=$s.ok;error=$s.error}|ConvertTo-Json -Compress")
    result = run(body)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['ok'] == (case == 'ok'), value
    if case in ('empty', 'array'):
        assert 'not a JSON object' in value['error']
    if case == 'missing_field':
        assert 'health lacks pid' in value['error']


@pytest.mark.parametrize('case', ['ok', 'socket_owned_elsewhere', 'nothing_listens', 'wrong_command', 'not_system'])
def test_process_proof_ties_the_pid_to_the_command_the_socket_and_system(case):
    expected = f'-I -B -m cochem_pipeline daemon --config "{CONFIG}" --queue-launch-output "{QUEUE_NEW}"'
    command = ('"' + BASE_PY + '" ' + expected) if case != 'wrong_command' else '"' + BASE_PY + '" -I -B -m cochem_pipeline daemon --config "other"'
    listeners = {'socket_owned_elsewhere': "@([pscustomobject]@{LocalPort=47824;OwningProcess=99})", 'nothing_listens': NO_LISTENER}.get(
        case, "@([pscustomobject]@{LocalPort=47824;OwningProcess=4242})")
    user = 'ansac' if case == 'not_system' else 'SYSTEM'
    body = (f"function Get-CimInstance {{param($ClassName,$Filter,$ErrorAction)if($Filter -like '*4242'){{return [pscustomobject]@{{ProcessId=4242;ParentProcessId=1;ExecutablePath='{BASE_PY}';CommandLine='{ps(command)}'}}}};$null}};"
            f"function Get-NetTCPConnection {{param($LocalPort,$State,$ErrorAction){listeners}}};"
            f"function Invoke-CimMethod {{param($InputObject,$MethodName,$ErrorAction)[pscustomobject]@{{ReturnValue=0;User='{user}'}}}};"
            "$refused=$false;$message='';$proof=$null;try{$proof=Get-ProcessProof 4242}catch{$refused=$true;$message=$_.Exception.Message};"
            "[ordered]@{refused=$refused;message=$message;verified=$(if($proof){$proof.port_owner_verified}else{$null})}|ConvertTo-Json -Compress")
    result = run(body)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['refused'] == (case != 'ok'), value
    if case == 'ok':
        assert value['verified'] is True
    expected_message = {'socket_owned_elsewhere': 'owned by pid 99', 'nothing_listens': 'Nothing listens', 'wrong_command': 'not running the expected r4 daemon command',
                        'not_system': 'does not run as SYSTEM'}.get(case)
    if expected_message:
        assert expected_message in value['message']


@pytest.mark.parametrize('case', ['success', 'controller_appears_before_mutation', 'register_does_not_apply', 'readback_denied', 'other_daemon_active',
                                  'worker_alive', 'worker_opaque', 'queue_exists', 'queue_probe_refused', 'rights_probe_fails'])
def test_retarget_mutation_path_is_driven_with_fixtures(tmp_path, case):
    target = tmp_path / 'retarget-root'
    queue = tmp_path / 'queue-new'
    if case == 'queue_exists':
        queue.mkdir()
    overrides = {'register_does_not_apply': '@{RegisterApplies=$false}', 'readback_denied': '@{DenyAfterRegister=$true}'}.get(case, '@{}')
    body = (TASK_FIXTURE + STUBS + f"$folder=New-FixtureFolder {overrides};$script:targetRoot='{ps(target)}';$script:queueNew='{ps(queue)}';"
            + ("$script:fixtureAliveAt=@(2);" if case == 'controller_appears_before_mutation' else "$script:fixtureAliveAt=@();")
            + ("function Get-OtherDaemonTaskStates {param($Folder)@([pscustomobject]@{name='CoChem-4.2.7-Supervisor';state='ACTIVE';active=$true})};" if case == 'other_daemon_active' else '')
            + ("function Get-WorkerProcesses {[ordered]@{workers=@(@{pid=5;user='CoChem422Worker1'});uninspectable_processes=@();exited_during_sweep=0;authoritative=$true}};" if case == 'worker_alive' else '')
            + ("function Get-WorkerProcesses {[ordered]@{workers=@();uninspectable_processes=@(@{pid=6;name='claude.exe';path='C:\\x\\claude.exe'});exited_during_sweep=0;authoritative=$true}};" if case == 'worker_opaque' else '')
            + ("function Test-Path {param($LiteralPath,$Path,$PathType,$ErrorAction)if($LiteralPath -eq $script:queueNew){throw [UnauthorizedAccessException]::new('Access is denied')};Microsoft.PowerShell.Management\\Test-Path @PSBoundParameters};" if case == 'queue_probe_refused' else '')
            + ("function Test-BackupCopyRights {throw 'Backup copy rights/readability probe failed (robocopy exit 16): ERROR : You do not have the Backup and Restore Files user rights.'};" if case == 'rights_probe_fails' else '')
            + ("$folder|Add-Member -Force ScriptMethod RegisterTaskDefinition {param($name,$def,$flags,$user,$pw,$logon,$sddl)$script:registered+=[pscustomobject]@{name=$name;flags=$flags;user=$user;logon=$logon;sddl=$sddl};$script:fx.DenyGetTask=$true};" if case == 'readback_denied' else '')
            + r'''
      $runtime=[ordered]@{install_receipt_sha256='a'*64;source_manifest_sha256='b'*64;revision_sha256='c'*64};$commissioning=[ordered]@{old_controller_pid=5788};
      $failed=$false;$message='';$result=$null;try{$result=Invoke-Retarget $null $folder $runtime $commissioning}catch{$failed=$true;$message=$_.Exception.Message};
      [ordered]@{failed=$failed;message=$message;registered=@($script:registered).Count;flags=$(if($script:registered){$script:registered[0].flags}else{$null});sddl=$(if($script:registered){$script:registered[0].sddl}else{$null});
        backups=$script:backups;receipt=(Test-Path (Join-Path $script:targetRoot 'retarget-receipt.json'));intent=(Test-Path (Join-Path $script:targetRoot 'retarget-intent.json'));
        held=(Test-Path (Join-Path $script:targetRoot 'retarget-held.json'));after_xml=(Test-Path (Join-Path $script:targetRoot 'warden-task-after.xml'));root=(Test-Path $script:targetRoot);
        status=$(if($result){$result.status}else{$null});action=$script:action.Path;runs=$script:runs;rights_probes=$script:rightsProbes}|ConvertTo-Json -Compress
    ''')
    result = run(body, timeout=120)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['runs'] == 0, 'the retarget path must never start the task'
    if case == 'success':
        assert not value['failed'], value['message']
        assert value['registered'] == 1 and value['flags'] == 4 and value['sddl'] == SDDL and value['rights_probes'] == 1
        assert value['status'] == 'WARDEN_RETARGETED_TO_R4_NOT_STARTED' and value['receipt'] and value['intent'] and value['after_xml'] and value['backups'] == 1 and not value['held']
        assert value['action'] == R4_PY
        receipt = json.loads((target / 'retarget-receipt.json').read_text(encoding='utf-8'))
        assert receipt['queue_launch_output'] == str(queue) and receipt['started'] is False and receipt['xml_outside_action_unchanged'] is True
        assert receipt['observer_processes'][0]['pid'] == 9472, 'the observers alive during the switch are recorded'
        intent = json.loads((target / 'retarget-intent.json').read_text(encoding='utf-8'))
        assert intent['observer_processes'][0]['pid'] == 9472
        return
    assert value['failed'], case
    if case == 'controller_appears_before_mutation':
        assert value['registered'] == 0 and value['intent'] and 'appeared during preparation' in value['message'] and not value['held']
    if case == 'register_does_not_apply':
        assert value['registered'] == 1 and not value['receipt'] and value['held'] and value['after_xml']
        assert 'retarget readback is held' in value['message'] and 'not the expected r4 action' in value['message'] and 'Do not retry with another -Attempt' in value['message']
        held = json.loads((target / 'retarget-held.json').read_text(encoding='utf-8'))
        assert held['mutation_requested'] is True and held['readback_readable'] is True and held['requires_reviewed_recovery'] is True and held['readback']['action_path'] == R3_PY
    if case == 'readback_denied':
        assert value['registered'] == 1 and not value['receipt'] and value['held'] and not value['after_xml']
        held = json.loads((target / 'retarget-held.json').read_text(encoding='utf-8'))
        assert held['readback_readable'] is False and held['readback'] is None and 'could not be read back' in held['reason']
    if case in ('other_daemon_active', 'worker_alive', 'worker_opaque', 'queue_exists', 'queue_probe_refused', 'rights_probe_fails'):
        assert value['registered'] == 0 and value['backups'] == 0 and not value['intent'] and not value['held'] and not value['root'], 'nothing may be consumed before the mutation gate'
    if case == 'worker_opaque':
        assert 'could not be inspected for worker ownership' in value['message'] and '6 claude.exe' in value['message']
    if case in ('queue_exists', 'queue_probe_refused'):
        assert 'queue-observation directory already exists' in value['message']
    if case == 'rights_probe_fails':
        assert 'Backup and Restore Files user rights' in value['message']


@pytest.mark.parametrize('case', ['success', 'enables_disabled_task', 'never_healthy', 'identity_changes', 'duplicate_start', 'instance_mismatch', 'run_throws',
                                  'readback_unreadable', 'proof_fails'])
def test_start_once_path_is_driven_with_fixtures(tmp_path, case):
    target = tmp_path / 'retarget-root'
    target.mkdir()
    if case == 'duplicate_start':
        (target / 'start-intent.json').write_text('{}', encoding='utf-8')
    new_args = f'-I -B -m cochem_pipeline daemon --config "{CONFIG}" --queue-launch-output "{QUEUE_NEW}"'
    overrides = f"@{{Path='{R4_PY}';WorkingDirectory='{R4_ROOT}';Arguments='{new_args}'"
    overrides += {'instance_mismatch': ';RunInstances=2}', 'run_throws': ';RunThrows=$true}', 'readback_unreadable': ';DenyAfterRun=$true}',
                  'enables_disabled_task': ';Enabled=$false;State=1}'}.get(case, '}')
    health = {'success': "@($null,$null,'A','A')", 'enables_disabled_task': "@('A','A')", 'never_healthy': "@()", 'identity_changes': "@('A','B','C','D','E','F')",
              'duplicate_start': "@('A','A')", 'instance_mismatch': "@('A','A')", 'run_throws': "@('A','A')", 'readback_unreadable': "@('A','A')", 'proof_fails': "@('A','A')"}[case]
    proof = "throw 'The controller port is owned by pid 99, not the pid reported by /health.'" if case == 'proof_fails' else "[ordered]@{pid=$ProcessId;owner='SYSTEM';port_owner_verified=$true}"
    body = (TASK_FIXTURE + STUBS + f"$folder=New-FixtureFolder {overrides};$script:targetRoot='{ps(target)}';$script:fixtureAliveAt=@();"
            + f"$script:healthScript={health};$script:healthIndex=0;$script:sleeps=0;"
            + r'''
      function Start-Sleep {param($Seconds,$Milliseconds)$script:sleeps++};
      function Get-HealthSample {
        if($script:healthIndex -ge $script:healthScript.Count){return [pscustomobject]@{ok=$false;error='refused';health=$null}};
        $tag=$script:healthScript[$script:healthIndex];$script:healthIndex++;
        if($null -eq $tag){return [pscustomobject]@{ok=$false;error='refused';health=$null}};
        $fixturePid=$(if($tag -eq 'A'){4242}else{4000+$script:healthIndex});
        [pscustomobject]@{ok=$true;error='';health=[pscustomobject]@{service_identity='SYSTEM';source_root=$script:r4SourceRoot;pid=$fixturePid;instance_id=('id-'+$tag);process_started_at=1.5;active=@();quarantined_slots=[pscustomobject]@{};version='4.2.7';admission_capacity=3}}};
      function Get-ProcessProof {param($ProcessId)PROOF};
      $failed=$false;$message='';$result=$null;try{$result=Invoke-StartOnce $folder 'SDDLVALUE'}catch{$failed=$true;$message=$_.Exception.Message};
      [ordered]@{failed=$failed;message=$message;runs=$script:runs;status=$(if($result){$result.status}else{$null});held=(Test-Path (Join-Path $script:targetRoot 'start-held.json'));receipt=(Test-Path (Join-Path $script:targetRoot 'start-receipt.json'));intent=(Test-Path (Join-Path $script:targetRoot 'start-intent.json'));enabled=$script:task.Enabled}|ConvertTo-Json -Compress
    '''.replace('SDDLVALUE', SDDL).replace('PROOF', proof))
    result = run(body, timeout=600)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    if case in ('success', 'enables_disabled_task'):
        assert not value['failed'], value['message']
        assert value['runs'] == 1 and value['status'] == 'WARDEN_R4_RUNNING_HEALTH_VERIFIED' and value['receipt'] and not value['held'] and value['enabled'] is True
        intent = json.loads((target / 'start-intent.json').read_text(encoding='utf-8'))
        assert intent['enabled_before'] is (case == 'success') and intent['enable_before_run'] is (case == 'enables_disabled_task')
        return
    assert value['failed'] and not value['receipt']
    if case == 'duplicate_start':
        assert value['runs'] == 0 and 'already requested' in value['message'] and not value['held']
        return
    assert value['held'] and value['intent'], 'every failure after the intent must leave start-held.json'
    assert 'no further -Attempt without a reviewed recovery' in value['message']
    held = json.loads((target / 'start-held.json').read_text(encoding='utf-8'))
    assert held['requires_reviewed_recovery'] is True and held['automatic_retry_allowed'] is False
    if case == 'run_throws':
        assert value['runs'] == 0 and held['run_requested'] is True and held['instance_guid'] is None and 'run refused' in held['reason'], 'a Run that throws may still have started the task'
    else:
        assert value['runs'] == 1 and held['run_requested'] is True
    if case == 'instance_mismatch':
        assert 'exactly one running instance' in value['message']
    if case == 'readback_unreadable':
        assert held['task_readable'] is False and held['task_state'] is None and 'could not be read back' in held['reason']
    if case == 'proof_fails':
        assert 'owned by pid 99' in held['reason']
    if case == 'never_healthy':
        assert 'within 3 s' in held['reason']


def test_nonadmin_apply_and_start_refuse_before_any_change_and_startonly_plans():
    for flags, text in ((['-Apply'], 'requires the owner in Administrator Windows PowerShell'), (['-Start'], 'only meaningful together with -Apply'),
                        (['-Apply', '-Start', '-StartOnly'], 'not both')):
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(SCRIPT), *flags], capture_output=True, text=True, timeout=60)
        assert result.returncode != 0 and text in result.stderr, (flags, result.stderr)
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(SCRIPT), '-StartOnly', '-Attempt', 'v1'], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan['mode'] == 'READ_ONLY_PLAN' and plan['start_only'] is True
    if not Path(r'C:\Program Files\CoChem\WardenRetarget4.2.7-windows-20261010-r4-v1').exists():
        assert any(hold.startswith('Retarget receipt:') for hold in plan['holds']), plan['holds']


def test_read_only_plan_reports_holds_without_changing_anything():
    retarget_root = Path(r'C:\Program Files\CoChem\WardenRetarget4.2.7-windows-20261010-r4-v1')
    if retarget_root.exists():
        pytest.skip('an r4 retarget attempt already exists on this host')
    commissioning = Path(r'C:\Program Files\CoChem\WardenCommissioning4.2.7-windows-20261007-r3-v1')
    before = sorted(p.name + str(p.stat().st_size) for p in commissioning.iterdir())
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(SCRIPT), '-Attempt', 'v1'], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan['mode'] == 'READ_ONLY_PLAN' and plan['attempt'] == 'v1' and plan['r3_commissioning_verified'] is True
    assert plan['loopback_port_free'] is True and plan['backup_copy_flags'] == ['/B'] and plan['administrator'] is False
    if not Path(R4_PY).exists():
        assert any('r4 stopped runtime is not the reviewed build' in hold for hold in plan['holds'])
    presence = plan['controller_presence']
    assert presence['authoritative'] is False and presence['listening'] == 0 and presence['controller_processes'] == []
    assert all('cochem_pipeline mcp' in (entry.get('command') or '') for entry in presence['client_processes'])
    assert plan['worker_processes']['authoritative'] is False and plan['worker_processes']['workers'] == [] and plan['worker_processes']['exited_during_sweep'] >= 0
    assert plan['backup_copy_rights_verified'] is None, 'the rights probe needs the elevated token'
    assert plan['private_root_readable'] is False, 'the private root is SYSTEM-only; an ordinary process cannot read it'
    assert sorted(p.name + str(p.stat().st_size) for p in commissioning.iterdir()) == before
    assert not retarget_root.exists()
