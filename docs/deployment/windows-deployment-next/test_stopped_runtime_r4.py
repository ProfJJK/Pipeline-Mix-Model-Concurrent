"""Inert PS5.1 flow/security fixtures for install-stopped-runtime-r4.ps1.

No installation, task, or privileged API runs. Functions are extracted from the
actual script text and exercised with fixtures; real r3 receipts are read only.
The two validation-body tests run the installer's exact Python validation text in
ordinary processes against temp fixtures (the r3 interpreter for the negative case,
the staged r4 source for the positive case); neither touches production state.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).parent
SCRIPT = ROOT / 'install-stopped-runtime-r4.ps1'
REPO = Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent')
R3 = Path(r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r3')
R3_MANIFEST_SHA256 = '6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1'
R4_MANIFEST = ROOT / 'stopped-runtime-r4-source-manifest.json'
R4_STAGE = Path(r'C:\Users\ansac\CoChem427\stopped-runtime-r4-source')
REPAIR_SHA256 = 'e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc'


def run(body):
    source = str(SCRIPT).replace("'", "''")
    prelude = f"""$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;
      foreach($m in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){{Import-Module (Join-Path $PSHOME "Modules\\$m\\$m.psd1")}};
      $tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('{source}',[ref]$tokens,[ref]$errors);
      if($errors.Count){{throw ($errors|Out-String)}};
      foreach($f in $ast.FindAll({{param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]}},$true)){{. ([scriptblock]::Create($f.Extent.Text))}};
    """
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', prelude + body],
                          capture_output=True, text=True, timeout=60)


def validation_body():
    return SCRIPT.read_text(encoding='utf-8').split("$validation=@'\n", 1)[1].split("\n'@", 1)[0]


def build_revision_fixture(tmp_path, source_tree):
    fixture = tmp_path / 'revision'
    (fixture / 'source/src').mkdir(parents=True)
    for package in ('cochem_pipeline', 'cochem_mcp', 'cochem_supervisor'):
        shutil.copytree(source_tree / 'src' / package, fixture / 'source/src' / package,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('pyproject.toml', 'uv.lock'):
        shutil.copyfile(source_tree / name, fixture / 'source' / name)
    shutil.copyfile(R3 / 'pipeline.json', fixture / 'pipeline.json')
    return fixture


def run_validation(tmp_path, interpreter, code, fixture):
    ps = "$ErrorActionPreference='Stop';$validation=@'\n" + code + "\n'@\n"
    ps += "& '" + str(interpreter) + "' -I -B -c $validation '" + str(fixture) + "'\nexit $LASTEXITCODE"
    command = tmp_path / 'argv-fixture.ps1'
    command.write_text(ps, encoding='utf-8')
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(command)],
                          capture_output=True, text=True, timeout=90)


def test_script_parses_and_pins_r3_as_the_preserved_previous_runtime():
    text = SCRIPT.read_text(encoding='utf-8')
    assert "Pipeline4.2.7-windows-20261007-r3'" in text and "Pipeline4.2.7-windows-20261009-r4'" in text
    assert f"$priorManifestHash='{R3_MANIFEST_SHA256}'" in text
    assert "$priorInstallHash='3b613128192ac44a0a3d9c4b4476fb4c47541edb7563541b9bbf18f84f9a90f6'" in text
    assert f"$repairHash='{REPAIR_SHA256}'" in text
    assert 'install_pipeline_windows' not in text.replace('Never calls install_pipeline_windows.ps1', '')
    for forbidden in ('Register-ScheduledTask', 'Start-ScheduledTask', 'Stop-ScheduledTask', 'schtasks', 'Start-Process', 'Stop-Process'):
        assert forbidden not in text, forbidden


def test_unchanged_functions_match_the_reviewed_r3_installer():
    """Functions carried over from r3 must stay byte-identical; only the listed ones may differ."""
    def extract(path):
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', (
            "$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('" + str(path).replace("'", "''")
            + "',[ref]$tokens,[ref]$errors);if($errors.Count){throw 'parse'};"
            "$ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)|ForEach-Object {"
            "[pscustomobject]@{name=$_.Name;sha=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($_.Extent.Text))).Replace('-','')}}|ConvertTo-Json -Compress")],
            capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        return {row['name']: row['sha'] for row in json.loads(result.stdout)}
    r3 = extract(ROOT / 'install-stopped-runtime-r3.ps1')
    r4 = extract(SCRIPT)
    allowed_to_differ = {'Get-RuntimeFiles', 'Assert-ExactPreservedConfig', 'Assert-PriorReceipts', 'Invoke-NewRuntimeValidation', 'Invoke-NewRuntimeInstallation'}
    renamed = {'Assert-ReviewedR3Delta': 'Assert-ReviewedR4Delta', 'Assert-StoppedRuntimeTasks': 'Get-ManagedDaemonTaskState'}
    for name, sha in r3.items():
        if name in renamed:
            assert renamed[name] in r4
            continue
        assert name in r4, name
        if name not in allowed_to_differ:
            assert r4[name] == sha, f'{name} drifted from the reviewed r3 definition'


@pytest.mark.parametrize('case', ['valid', 'unsafe', 'duplicate', 'incomplete', 'baseline', 'missing', 'previous_target', 'no_repair_file'])
def test_inventory_is_complete_confined_and_bound_to_prior_r3_source(case):
    result = run(f"$case='{case}';" + r'''
      $script:repo='D:\repo';$script:targetRoot='C:\Program Files\CoChem\new';$script:sourceRoot=$script:targetRoot+'\source';
      $script:priorManifestHash='6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1';
      $required=@('README.md','pyproject.toml','uv.lock','src/cochem_pipeline/resource_telemetry.py','src/cochem_pipeline/resource_limits.py','src/cochem_pipeline/ramdisk.py','src/cochem_pipeline/deployment.py','src/cochem_pipeline/config.py','src/cochem_pipeline/deployment_revision.py','src/cochem_supervisor/engine.py');
      $rows=@($required|ForEach-Object {[pscustomobject]@{relative=$_;sha256=('a'*64);length=1}});
      foreach($i in 1..90){$rows+=[pscustomobject]@{relative="src/package/item$i.py";sha256=('a'*64);length=1}};
      $inventory=[pscustomobject]@{schema='cochem-stopped-runtime-source/1';host='AETHERDESK';complete_source_freeze=$true;source_repository=$script:repo;target_root=$script:targetRoot;previous_source_manifest_sha256=$script:priorManifestHash;files=$rows};
      switch($case){'unsafe'{$rows[20].relative='src/../../secret'}'duplicate'{$rows[20].relative='SRC/COCHEM_PIPELINE/ramdisk.py'}'incomplete'{$inventory.complete_source_freeze=$false}'baseline'{$inventory.previous_source_manifest_sha256=('b'*64)}'missing'{$rows[1].relative='src/other.py'}'previous_target'{$inventory.target_root='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r3'}'no_repair_file'{$rows[3].relative='src/cochem_pipeline/other_telemetry.py'}};
      $refused=$false;$count=0;try{$files=@(Get-RuntimeFiles $inventory);$count=$files.Count}catch{$refused=$true};
      [ordered]@{refused=$refused;count=$count}|ConvertTo-Json -Compress
    ''')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'refused': case != 'valid', 'count': 100 if case == 'valid' else 0}


@pytest.mark.parametrize('case', ['valid', 'second_change', 'wrong_fix', 'removed', 'added', 'unchanged'])
def test_r4_manifest_accepts_only_reviewed_telemetry_repair_from_pinned_r3(case):
    assert R4_MANIFEST.exists(), 'run freeze-stopped-runtime-r4-source.py first'
    result = run(f"$case='{case}';$script:repairHash='{REPAIR_SHA256}';" + r'''
      $prior=Get-Content -LiteralPath 'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r3\source-manifest.json' -Raw|ConvertFrom-Json;
      $current=Get-Content -LiteralPath 'REPLACE_MANIFEST' -Raw|ConvertFrom-Json;
      $repair=($current.files|Where-Object {$_.relative -eq 'src/cochem_pipeline/resource_telemetry.py'});
      $priorRepair=($prior.files|Where-Object {$_.relative -eq 'src/cochem_pipeline/resource_telemetry.py'});
      switch($case){
        'second_change'{$current.files[0].sha256='a'*64}
        'wrong_fix'{$repair.sha256='b'*64}
        'removed'{$current.files=@($current.files|Select-Object -Skip 1)}
        'added'{$current.files[0].relative='src/extra.py'}
        'unchanged'{$repair.sha256=$priorRepair.sha256;$repair.length=$priorRepair.length}
      };
      $refused=$false;try{Assert-ReviewedR4Delta $current $prior}catch{$refused=$true};
      @{refused=$refused}|ConvertTo-Json -Compress
    '''.replace('REPLACE_MANIFEST', str(R4_MANIFEST)))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['refused'] == (case != 'valid')


@pytest.mark.parametrize('case', ['valid', 'capacity', 'worker', 'subtree', 'whitespace'])
def test_actual_r3_configuration_requires_exact_preservation(case):
    result = run(f"$case='{case}';" + r'''
      $before=Get-Content -LiteralPath 'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r3\pipeline.json' -Raw;
      $after=$before;
      switch($case){
        'capacity'{$after=$after.Replace('"max_execution_slots": 4','"max_execution_slots": 6')}
        'worker'{$after=$after.Replace('"slot6"','"other"')}
        'subtree'{$after=$after.Replace('CoChem427-windows-20261007','Different')}
        'whitespace'{$after=$after+" `n"}
      };
      if($case -ne 'valid' -and $before -ceq $after){throw 'Fixture did not mutate the configuration'};
      $refused=$false;try{Assert-ExactPreservedConfig $before $after}catch{$refused=$true};
      @{refused=$refused}|ConvertTo-Json -Compress
    ''')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['refused'] == (case != 'valid')


@pytest.mark.parametrize('case', ['valid', 'mode', 'target', 'manifest', 'files', 'source_sha', 'denial_status', 'denial_nonce'])
def test_prior_receipts_must_be_the_exact_preserved_r3_installation(case):
    result = run(f"$case='{case}';" + r'''
      $script:oldRoot='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r3';
      $script:priorManifestHash='6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1';
      $script:configHash='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c';
      $install=Get-Content -LiteralPath 'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r3\install-after.json' -Raw|ConvertFrom-Json;
      $denial=Get-Content -LiteralPath 'C:\Program Files\CoChem\WorkerDenial4.2.7-windows-20261006-slot1\worker-denial-acceptance.json' -Raw|ConvertFrom-Json;
      switch($case){
        'mode'{$install.mode='READ_ONLY_PLAN'}
        'target'{$install.target_root='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r2'}
        'manifest'{$install.source_manifest_sha256='c'*64}
        'files'{$install.source_files=165}
        'source_sha'{$install.verification.revision.source_sha256='d'*64}
        'denial_status'{$denial.status='DENIAL_CHECK_PASSED'}
        'denial_nonce'{$denial.nonce='0'*32}
      };
      $refused=$false;try{Assert-PriorReceipts $install $denial}catch{$refused=$true};
      @{refused=$refused}|ConvertTo-Json -Compress
    ''')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['refused'] == (case != 'valid')


@pytest.mark.parametrize('case', ['absent', 'denied', 'partial_denied', 'running', 'disabled', 'references_target', 'wrong_hresult', 'partial_other'])
def test_managed_daemon_task_state_never_requires_stopped_r3_and_refuses_new_root_references(case):
    result = run(f"$script:case='{case}';$script:targetRoot='C:\\Program Files\\CoChem\\Pipeline4.2.7-windows-20261009-r4';" + r'''
      $folder=[pscustomobject]@{};$folder|Add-Member ScriptMethod GetTask {param($name)
        if($script:case -in @('absent','denied','wrong_hresult')){$code=if($script:case -eq 'absent'){-2147024894}elseif($script:case -eq 'denied'){-2147024891}else{-2147216625};throw [Runtime.InteropServices.COMException]::new('fixture',$code)};
        $path=if($script:case -eq 'references_target'){$script:targetRoot+'\.venv\Scripts\python.exe'}else{'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r3\.venv\Scripts\python.exe'};
        $action=[pscustomobject]@{Path=$path;Arguments='-I -B -m cochem_pipeline daemon --config x';WorkingDirectory='C:\Program Files\CoChem'};
        $task=[pscustomobject]@{Enabled=($script:case -ne 'disabled');State=$(if($script:case -eq 'running'){4}else{3});Definition=[pscustomobject]@{Actions=@($action)}};
        $task|Add-Member ScriptMethod GetInstances {param($unused)
          if($script:case -eq 'partial_denied'){throw [Runtime.InteropServices.COMException]::new('denied',-2147024891)};
          if($script:case -eq 'partial_other'){throw [Runtime.InteropServices.COMException]::new('other',-2147216625)};
          @{Count=$(if($script:case -eq 'running'){1}else{0})}};$task
      };
      $refused=$false;$states=@();try{$states=@(Get-ManagedDaemonTaskState $folder)}catch{$refused=$true};
      [ordered]@{refused=$refused;states=@($states|ForEach-Object {$_.state});deferred=@($states|Where-Object {$_.state -eq 'ACCESS_DENIED_DEFERRED'}).Count;referencing=@($states|Where-Object {$_.references_new_root -eq $true}).Count}|ConvertTo-Json -Compress
    ''')
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['refused'] == (case in ('wrong_hresult', 'partial_other'))
    if case == 'references_target':
        assert value['referencing'] == 4
    if case in ('denied', 'partial_denied'):
        assert value['deferred'] == 4
    if case in ('running', 'disabled'):
        assert value['deferred'] == 0 and all(state.startswith('ENABLED=') for state in value['states'])
    if case == 'absent':
        assert value['states'] == ['ABSENT'] * 4


@pytest.mark.parametrize('case', ['valid', 'missing', 'denied', 'running', 'instances', 'exit', 'nonce', 'principal', 'trigger'])
def test_original_failed_task_must_be_exact_and_terminal(case):
    result = run(f"$script:case='{case}';" + r'''
      $root='C:\Program Files\CoChem\WorkerDenial4.2.7-windows-20261006-slot1';
      $script:action=[pscustomobject]@{Type=0;Path='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261006\.venv\Scripts\python.exe';Arguments=('-I -B "'+$root+'\worker-denial-acceptance.py" --slot slot1 --nonce 06478e2f265546cd8257aa09111373f4');WorkingDirectory=$root};
      if($script:case -eq 'nonce'){$script:action.Arguments+='0'};
      $actions=[pscustomobject]@{Count=1};$actions|Add-Member ScriptMethod Item {param($i)$script:action};
      $script:task=[pscustomobject]@{State=$(if($script:case -eq 'running'){4}else{3});LastTaskResult=$(if($script:case -eq 'exit'){0}else{2});Definition=[pscustomobject]@{
        Principal=[pscustomobject]@{UserId=$(if($script:case -eq 'principal'){'ansac'}else{'SYSTEM'});LogonType=5;RunLevel=1};Triggers=[pscustomobject]@{Count=$(if($script:case -eq 'trigger'){1}else{0})};Actions=$actions}};
      $script:task|Add-Member ScriptMethod GetInstances {param($n)@{Count=$(if($script:case -eq 'instances'){1}else{0})}};
      $folder=[pscustomobject]@{};$folder|Add-Member ScriptMethod GetTask {param($name)
        if($script:case -eq 'missing'){throw [Runtime.InteropServices.COMException]::new('missing',-2147024894)};
        if($script:case -eq 'denied'){throw [Runtime.InteropServices.COMException]::new('denied',-2147024891)};
        $script:task};
      $refused=$false;try{Assert-PreservedDenialTask $folder}catch{$refused=$true};
      @{refused=$refused}|ConvertTo-Json -Compress
    ''')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['refused'] == (case != 'valid')


def test_frozen_build_restores_environment_on_failure_and_does_not_call_installer(tmp_path):
    escaped = str(tmp_path).replace("'", "''")
    result = run(f"$script:targetRoot='{escaped}';" + r'''
      $script:sourceRoot=$script:targetRoot+'\source';$script:python='C:\protected\python.exe';$script:uv='Invoke-FixtureUv';
      $env:UV_INDEX_URL='fixture-existing-index';$env:PYTHONPATH='fixture-existing-pythonpath';$beforeTemp=$env:TEMP;
      function Invoke-FixtureUv {
        if($null -ne $env:UV_INDEX_URL -or $null -ne $env:PYTHONPATH){throw 'Ambient policy leaked'};
        if($env:UV_PROJECT_ENVIRONMENT -ne ($script:targetRoot+'\.venv') -or $env:TEMP -ne ($script:targetRoot+'\build-temp')){throw 'Build escaped fresh root'};
        $script:arguments=@($args);$global:LASTEXITCODE=17
      };
      $failed=$false;try{Invoke-FrozenRuntimeBuild}catch{$failed=$true};
      [ordered]@{failed=$failed;restored=($env:UV_INDEX_URL -eq 'fixture-existing-index' -and $env:PYTHONPATH -eq 'fixture-existing-pythonpath' -and $env:TEMP -eq $beforeTemp);arguments=$script:arguments}|ConvertTo-Json -Compress
    ''')
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['failed'] and value['restored']
    arguments = value['arguments']
    assert arguments[:3] == ['--no-config', '--no-cache', 'sync']
    assert '--frozen' in arguments and '--no-editable' in arguments and '--no-python-downloads' in arguments
    assert arguments[arguments.index('--link-mode') + 1] == 'copy'
    assert arguments[arguments.index('--extra') + 1] == 'mcp'
    assert not any('install_pipeline_windows' in value or 'provision' in value for value in arguments)


@pytest.mark.parametrize('exit_code', [0, 7])
def test_actual_native_stderr_is_judged_by_exit_code_in_ps51(tmp_path, exit_code):
    python = Path(r'C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe')
    result = run(f"$script:targetRoot='{tmp_path}';$script:uv='{python}';$script:fixtureExit={exit_code};" + r'''
      function Get-FrozenSyncArguments { @('-I','-B','-c',("import sys; print('benign native stderr',file=sys.stderr); sys.exit("+$script:fixtureExit+")")) };
      $failed=$false;try{Invoke-FrozenRuntimeBuild}catch{$failed=$true};
      [ordered]@{failed=$failed;preference=[string]$ErrorActionPreference;log_contains_stderr=((Get-Content -LiteralPath (Join-Path $script:targetRoot 'frozen-build.log') -Raw) -match 'benign native stderr')}|ConvertTo-Json -Compress
    ''')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'failed': exit_code != 0, 'preference': 'Stop', 'log_contains_stderr': True}


def test_runtime_tree_hardlink_is_refused_before_file_acl_mutation(tmp_path):
    outside = tmp_path / 'outside.txt'
    outside.write_bytes(b'preserved')
    root = tmp_path / 'new'
    root.mkdir()
    os.link(outside, root / 'alias.txt')
    helper = str(REPO / 'scripts/stage_aetherdesk_427_payloads.ps1').replace("'", "''")
    result = run(f"$script:targetRoot='{str(root)}';$helper='{helper}';" + r'''
      $tokens=$null;$errors=$null;$a=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$tokens,[ref]$errors);
      $f=$a.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Initialize-FileIdentity'},$true);
      . ([scriptblock]::Create($f.Extent.Text));Initialize-FileIdentity;
      function Assert-ProtectedPath {param($Path)};function New-CodeAcl {param($Directory)$null};
    ''' + f"$treeSource='{str(ROOT / 'check-worker-denials.ps1')}';" + r'''
      $treeAst=[Management.Automation.Language.Parser]::ParseFile($treeSource,[ref]$tokens,[ref]$errors);
      $treeFunction=$treeAst.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Assert-CodeTreeOnce'},$true);
      . ([scriptblock]::Create($treeFunction.Extent.Text));
      function Get-Acl {param($LiteralPath)
        $acl=[Security.AccessControl.DirectorySecurity]::new();$acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'));
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-5-18'),'FullControl','Allow'));$acl};
      $script:aclsChanged=0;function Set-Acl {param($LiteralPath,$AclObject)$script:aclsChanged++};
      $refused=$false;try{Protect-NewRuntimeTree $script:targetRoot}catch{$refused=$true};
      [ordered]@{refused=$refused;acls_changed=$script:aclsChanged}|ConvertTo-Json -Compress
    ''')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'refused': True, 'acls_changed': 0}
    assert outside.read_bytes() == b'preserved'


@pytest.mark.parametrize('mutate', [False, True])
def test_post_build_source_rebinding_rejects_identical_source_and_installed_drift(tmp_path, mutate):
    source = tmp_path / 'source.py'
    installed = tmp_path / 'installed.py'
    original = b'approved source\n'
    changed = b'mutated source!\n'
    source.write_bytes(changed if mutate else original)
    installed.write_bytes(source.read_bytes())
    helper = REPO / 'scripts/stage_aetherdesk_427_payloads.ps1'
    result = run(f"$helper='{helper}';$file='{source}';$expected='{hashlib.sha256(original).hexdigest()}';$length={len(original)};" + r'''
      $tokens=$null;$errors=$null;$a=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$tokens,[ref]$errors);
      foreach($f in $a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -in @('Initialize-FileIdentity','Assert-NoReparseAncestors','Open-VerifiedFile')},$true)){. ([scriptblock]::Create($f.Extent.Text))};Initialize-FileIdentity;
      $refused=$false;try{Assert-PostBuildFrozenFiles @([pscustomobject]@{destination=$file;sha256=$expected;length=$length})}catch{$refused=$true};
      @{refused=$refused}|ConvertTo-Json -Compress
    ''')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['refused'] == mutate


def test_held_text_reader_disposal_retains_file_handle(tmp_path):
    control = tmp_path / 'control.json'
    control.write_bytes(b'{"safe":true}')
    result = run(f"$path='{control}';" + r'''
      $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);
      try{$first=Read-HeldText $stream;$second=Read-HeldText $stream;
        $refused=$false;try{$w=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::Read);$w.Dispose()}catch{$refused=$true};
        @{repeat=($first -ceq $second);write_denied=$refused;readable=$stream.CanRead}|ConvertTo-Json -Compress
      }finally{$stream.Dispose()}
    ''')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'repeat': True, 'write_denied': True, 'readable': True}


def test_nonadmin_apply_refuses_before_source_manifest_or_targets():
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(SCRIPT), '-Apply'],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert '-Apply requires the owner in Administrator Windows PowerShell' in result.stderr


@pytest.mark.parametrize('case', ['valid', 'base', 'version', 'system_site', 'extra', 'duplicate', 'legacy'])
def test_exact_actual_uv_venv_format_and_policy_against_r3(case):
    result = run(f"$case='{case}';" + r'''
      $script:python='C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe';
      $text=Get-Content -LiteralPath 'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r3\.venv\pyvenv.cfg' -Raw;
      switch($case){
        'base'{$text=$text.Replace('Python312','WrongBase')}
        'version'{$text=$text.Replace('3.12.13','3.12.12')}
        'system_site'{$text=$text.Replace('false','true')}
        'extra'{$text+="`nexecutable = C:\unexpected\python.exe"}
        'duplicate'{$text+="`nimplementation = CPython"}
        'legacy'{$text=$text.Replace('version_info','version')}
      };
      $refused=$false;try{Assert-UvVenvText $text}catch{$refused=$true};
      @{refused=$refused}|ConvertTo-Json -Compress
    ''')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['refused'] == (case != 'valid')


def test_validation_body_refuses_an_unrepaired_runtime(tmp_path):
    """The exact validation body, run with the unrepaired r3 interpreter, must fail on the repair check."""
    fixture = build_revision_fixture(tmp_path, R3 / 'source')
    result = run_validation(tmp_path, R3 / '.venv/Scripts/python.exe', validation_body(), fixture)
    assert result.returncode != 0
    assert 'telemetry repair missing: PerformanceInformation/_commit_probe' in result.stderr


def test_validation_body_accepts_the_staged_r4_source(tmp_path):
    """The exact validation body passes against the staged r4 source (repair present, 104-byte ABI).

    The staged tree stands in for the not-yet-built r4 site-packages, so the revision
    comparison binds the fixture source to itself; everything else is the real body.
    """
    assert R4_STAGE.exists(), 'run freeze-stopped-runtime-r4-source.py first'
    fixture = build_revision_fixture(tmp_path, R4_STAGE)
    body = validation_body()
    assert "Path(sys.executable).parent.parent/'Lib/site-packages'" in body
    code = "import sys;sys.path.insert(0," + repr(str(fixture / 'source' / 'src')) + ")\n"
    code += body.replace("Path(sys.executable).parent.parent/'Lib/site-packages'", "root/'source'/'src'")
    result = run_validation(tmp_path, R3 / '.venv/Scripts/python.exe', code, fixture)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['telemetry_repair_installed'] and value['revision']['verified'] and value['configuration_parsed']
    assert value['ram_workspace_root'] == 'R:\\CoChem427-windows-20261007'


@pytest.mark.parametrize('case', ['success', 'source_drift', 'existing_root', 'failed_task', 'build_failure', 'deferred_task'])
def test_exact_apply_branch_real_control_copies_and_stops_on_failure(tmp_path, case):
    """Execute the actual Apply function with real temp source/control copies.

    Explicit boundaries replace administrator ACL creation, task COM access,
    package build and installed-runtime execution. No privileged operation runs.
    """
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    for name in ('pipeline.json', 'windows-layout.json', 'manifest.json', 'source.py'):
        (inputs / name).write_bytes(('fixture ' + name + '\n').encode())
    target = tmp_path / 'new-runtime'
    if case == 'existing_root':
        target.mkdir()
        (target / 'preserve.txt').write_bytes(b'untouched')
    result = run(f"$case='{case}';$fixture='{tmp_path}';$inputs='{inputs}';$script:targetRoot='{target}';" + r'''
      $script:setupMutexName='Local\CoChem-R4-Inert-'+[Guid]::NewGuid().ToString('N');
      $script:sourceRoot=Join-Path $script:targetRoot 'source';$script:oldRoot=$inputs;
      $script:oldConfig=Join-Path $inputs 'pipeline.json';$script:layout=Join-Path $inputs 'windows-layout.json';
      $script:configHash=(Get-FileHash $script:oldConfig).Hash.ToLowerInvariant();$script:layoutHash=(Get-FileHash $script:layout).Hash.ToLowerInvariant();
      $manifest=Join-Path $inputs 'manifest.json';$manifestHash=(Get-FileHash $manifest).Hash.ToLowerInvariant();
      $controls=@(New-ControlCopyRecords $manifest $manifestHash);
      if($controls.Count -ne 3 -or @($controls|Where-Object {$_ -is [string]}).Count){throw 'Copy records flattened'};
      $source=Join-Path $inputs 'source.py';$files=@([pscustomobject]@{source=$source;destination=(Join-Path $script:sourceRoot 'src\package\source.py');sha256=(Get-FileHash $source).Hash.ToLowerInvariant();length=(Get-Item $source).Length});
      $script:python='C:\fixture-base\python.exe';$script:uv='C:\fixture-uv\uv.exe';$script:pins=@();
      $script:copied=[Collections.Generic.List[string]]::new();$script:builds=0;$script:validations=0;$script:taskChecks=0;
      function Get-ManagedDaemonTaskState {param($Folder)if($case -eq 'deferred_task'){@([pscustomobject]@{name='CoChem-4.2.7-Warden';state='ACCESS_DENIED_DEFERRED';references_new_root=$null})}else{@([pscustomobject]@{name='CoChem-4.2.7-Warden';state='ENABLED=True;STATE=4;INSTANCES=1';references_new_root=$false})}};
      function Assert-PreservedDenialTask {param($Folder)$script:taskChecks++;if($case -eq 'failed_task'){throw 'fixture nonterminal'}};
      function Assert-CodeTreeOnce {param($Path)7};function Assert-ProtectedPath {param($Path)};
      function New-ProtectedDirectory {param($Path)$null=[IO.Directory]::CreateDirectory($Path)};
      function Protect-NewRuntimeTree {param($Path)};
      function Open-VerifiedFile {param($Path,$Hash,$Length)
        $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);
        $sha=[Security.Cryptography.SHA256]::Create();
        try{$actual=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()};
        if($actual -cne $Hash -or $stream.Length -ne $Length){$stream.Dispose();throw 'fixture binding differs'};
        $stream.Position=0;return $stream
      };
      function Copy-VerifiedPayload {param($File)
        $sourceStream=Open-VerifiedFile $File.source $File.sha256 $File.length;
        try{$dest=[IO.File]::Open($File.destination,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);
          try{$sourceStream.CopyTo($dest);$dest.Flush($true)}finally{$dest.Dispose()}
        }finally{$sourceStream.Dispose()};$script:copied.Add($File.destination)
      };
      function Write-NewRuntimeReport {param($Path,$Value)[IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth 12))};
      function Invoke-FrozenRuntimeBuild {$script:builds++;if($case -eq 'build_failure'){throw 'fixture build failed'};
        if($case -eq 'source_drift'){[IO.File]::AppendAllText($files[0].destination,'changed by fixture build')}};
      function Invoke-NewRuntimeValidation {param($Root)$script:validations++;[pscustomobject]@{revision=[pscustomobject]@{verified=$true};configuration_parsed=$true;telemetry_repair_installed=$true}};
      function Assert-NewRuntimeInterpreter {param($Root)[pscustomobject]@{fixture=$true}};
      $plan=[ordered]@{mode='READ_ONLY_PLAN';holds=@();preserved_denial_task_terminal_check_deferred=$true;managed_daemon_tasks=@()};
      $failed=$false;try{$null=Invoke-NewRuntimeInstallation $files $controls $null $plan}catch{$failed=$true};
      $hashes=@();foreach($record in $controls){if(Test-Path -LiteralPath $record.destination){$hashes+=((Get-FileHash $record.destination).Hash.ToLowerInvariant() -ceq $record.sha256)}};
      @{failed=$failed;copied=$script:copied.Count;controls_correct=@($hashes|Where-Object {$_ -eq $true}).Count;builds=$script:builds;validations=$script:validations;task_checks=$script:taskChecks;after=(Test-Path -LiteralPath (Join-Path $script:targetRoot 'install-after.json'));mode=$plan.mode}|ConvertTo-Json -Compress
    ''')
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['failed'] == (case != 'success')
    before_copy = case in ('existing_root', 'failed_task', 'deferred_task')
    assert value['copied'] == (0 if before_copy else 4)
    assert value['controls_correct'] == (0 if before_copy else 3)
    assert value['builds'] == (0 if before_copy else 1)
    assert value['validations'] == (1 if case == 'success' else 0)
    assert value['after'] == (case == 'success')
    if case == 'existing_root':
        assert (target / 'preserve.txt').read_bytes() == b'untouched'
    assert all((inputs / name).read_bytes() == ('fixture ' + name + '\n').encode()
               for name in ('pipeline.json', 'windows-layout.json', 'manifest.json', 'source.py'))
