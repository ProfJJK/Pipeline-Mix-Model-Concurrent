"""Inert Windows PowerShell 5.1 harness for install-stopped-runtime-r5.ps1 (r5 sitting stage S1).

The installer is never invoked, with or without -Apply. Functions are extracted from the actual
script text (PowerShell AST) and run in ordinary powershell.exe processes against fixture trees in
tmp_path; every system boundary is stubbed (task COM folder, ACL owner checks, the uv build). Real
r4 receipts, manifests and configuration are only read. The validation tests run the installer's own
Invoke-NewRuntimeValidation (exact Python body, PS 5.1 native argument passing) through a copy of
the r4 venv launcher against temp runtime fixtures: the committed r5 tree (r4 frozen source + the 13
blobs of the reviewed commit) must pass, the r4 source and single reverted r5 files must fail. The
retarget contract test runs the real
Assert-R5InstalledBindings from retarget-warden-r5.ps1 against a fixture r5 root this installer's
Apply function produced. Nothing touches production state, tasks, services or the network.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from types import SimpleNamespace
import uuid

import pytest

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / 'install-stopped-runtime-r5.ps1'
R4_SCRIPT = ROOT / 'install-stopped-runtime-r4.ps1'
RETARGET = ROOT / 'retarget-warden-r5.ps1'
TREE_HELPER = ROOT / 'check-worker-denials.ps1'
FREEZE = ROOT / 'freeze-stopped-runtime-r5-source.py'
R5_MANIFEST = ROOT / 'stopped-runtime-r5-source-manifest.json'
REPO = Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent')
COPY_HELPER = REPO / 'scripts' / 'stage_aetherdesk_427_payloads.ps1'
PY = REPO / '.venv' / 'Scripts' / 'python.exe'
BASE = Path(r'C:\Program Files\CoChem')
R3 = BASE / 'Pipeline4.2.7-windows-20261007-r3'
R4 = BASE / 'Pipeline4.2.7-windows-20261009-r4'
R5_TARGET = r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5'
TOOLCHAIN_PYTHON = BASE / 'Toolchain4.2.7-windows-20261006' / 'Python312' / 'python.exe'
TOOLCHAIN_UV = BASE / 'Toolchain4.2.7-windows-20261006' / 'uv' / 'uv.exe'
COMMISSIONED = BASE / 'WardenCommissioning4.2.7-windows-20261007-r3-v1' / 'pipeline.json'
DENIAL = BASE / 'WorkerDenial4.2.7-windows-20261006-slot1' / 'worker-denial-acceptance.json'
R4_STAGE = Path(r'C:\Users\ansac\CoChem427\stopped-runtime-r4-source')
R5_STAGE = Path(r'C:\Users\ansac\CoChem427\stopped-runtime-r5-source')

COPY_HELPER_SHA256 = '0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b'
TREE_HELPER_SHA256 = '1576882fe655d27894aa6f9da25a14ae4ddd08540c865d51cc43b26fa3dd6f9d'
PYTHON_SHA256 = 'd8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa'
UV_SHA256 = '2019cdf564cb8f749262f5f021cedc75a99abb1c6081227ca340bbcda972611d'
CONFIG_SHA256 = '135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
LAYOUT_SHA256 = '8430fdf1109c63c4a89479f03da8a465dfebf5566c7791c64f868202170672c4'
R4_MANIFEST_SHA256 = '1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189'
R4_INSTALL_SHA256 = '629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502'
R4_REVISION_SHA256 = '38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e'
R3_REVISION_SHA256 = '309eb48d9b1c43179ae1f0784d0139357168314f8312a64fb84dbd8380d44eb4'
R3_MANIFEST_SHA256 = '6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1'
R3_INSTALL_SHA256 = '3b613128192ac44a0a3d9c4b4476fb4c47541edb7563541b9bbf18f84f9a90f6'
DENIAL_SHA256 = '691c70560436f948464c529b9d2d6a3e33ce240749642af86ca79c748791461d'
TELEMETRY_REPAIR = 'src/cochem_pipeline/resource_telemetry.py'
TELEMETRY_REPAIR_SHA256 = 'e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc'
PYVENV_SHA256 = '0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d'
VENV_PYTHON_SHA256 = '560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'
PLACEHOLDER = 'PIN-AFTER-COMMIT'
# The reviewed r5 commit and its 13 blob pins, as relayed by RUNTIME-BUILD from BUILD-FREEZE --print-pins
# (embedded in freeze-stopped-runtime-r5-source.py REPAIRS); re-derived below from the freeze table and git.
SOURCE_COMMIT = '8554c7645801a7bc9c4abad4861bfcbe4ed014b0'
PINS = {
    'src/cochem_pipeline/__main__.py': '19f24fc7bcd4d6d0133386aff916efc3ceb6fb359d8604041ef17bdab931b1b3',
    'src/cochem_pipeline/agy_protocol.py': 'eaf8d1f407c8792be1343c657afabcf370992df3f82cd9dfb7fe13cf9d41545e',
    'src/cochem_pipeline/coding.py': '0b97d7bdec4e5c4a1b8f3d1ca8a974f3205d838c6e275e3cc66c5c9826998174',
    'src/cochem_pipeline/config.py': '908e61267a6133379fad7b26b7452e03f1deb97f44f53eb9e26c07de8212bbd4',
    'src/cochem_pipeline/controller_guard.py': 'e18304719af11e0dd5280d777c6157cc9bc873dd29b7dc15527d6b3667656eba',
    'src/cochem_pipeline/failures.py': '625f9c6e045f6a108be04a6a13767593db08ac960bb3839fade0a37e36c6edf5',
    'src/cochem_pipeline/knowledge.py': '1bf720ed5df342704552b3e0996ee1cdaebd8f9d7f26fc345b4e5a848e2d2f0f',
    'src/cochem_pipeline/operator_views.py': '8b6b51e9ef3879ad13f714ee44390fc4bb7e41cc9bf5c7cbdc589413f1efaf42',
    'src/cochem_pipeline/runtime.py': '946adaf95b1755138f0e7bf79576c8290569d7fb98851e8962e00ca73b40a208',
    'src/cochem_pipeline/service.py': '38ab9dc1853dc38b0ee824a1f80f5e4bea503ec2e821c7803b065baa501c5128',
    'src/cochem_pipeline/store.py': 'b3604d227b23d2f3a68e0106b852ad672127089df68b0d512131455fa552d0a0',
    'src/cochem_pipeline/worker.py': '20a084071bfa172aa787d1a96168b8c541089823559e8f00518b164c16ae0f41',
    'src/cochem_supervisor/runner.py': 'adc8ccf33841438f3104e64325ff84b7826c49db297c8bc3f02ebb55ad96cf31',
}
# Addendum A6: the 12 spec files plus __main__.py; agy_protocol.py stays pure LF, the others pure CRLF.
REPAIRS = [
    'src/cochem_pipeline/__main__.py', 'src/cochem_pipeline/agy_protocol.py', 'src/cochem_pipeline/coding.py',
    'src/cochem_pipeline/config.py', 'src/cochem_pipeline/controller_guard.py', 'src/cochem_pipeline/failures.py',
    'src/cochem_pipeline/knowledge.py', 'src/cochem_pipeline/operator_views.py', 'src/cochem_pipeline/runtime.py',
    'src/cochem_pipeline/service.py', 'src/cochem_pipeline/store.py', 'src/cochem_pipeline/worker.py',
    'src/cochem_supervisor/runner.py',
]
LF_REPAIRS = {'src/cochem_pipeline/agy_protocol.py'}
PACKAGES = ('cochem_pipeline', 'cochem_mcp', 'cochem_supervisor')
# Shape of the real validation output (asserted against a real run below); used where validation is stubbed.
VERIFICATION = {
    'revision': {'schema': 'cochem-installed-revision/1', 'verified': True, 'read_only': True, 'files': 109,
                 'source_sha256': '5' * 64, 'acceptance_files': 0, 'acceptance_sha256': None},
    'configuration_parsed': True, 'ram_workspace_root': 'R:\\CoChem427-windows-20261007',
    'telemetry_repair_installed': True, 'no_system_or_model_execution': True, 'r5_repairs_installed': True,
    'r5': {'max_execution_slots': 4, 'workers': 6, 'identity_policy': 'reported-model-equality',
           'agy_parse_fixture': {'reported_model': 'gemini-3.8-flash-high', 'identity_mismatch_refused': True},
           'wbs_reconciliation': {'drift_refused_before': True, 'accepted_after': True, 'restored_omitted_ids': ['T2'],
                                  'restored_rewritten_ids': ['T1'], 'additional_task_ids': ['T3']},
           'read_workspace_plain_file': True,
           'daemon_options': {'queue_launch_output_root': True, 'docker_wait_seconds': 900, 'mutually_exclusive': True,
                              'negative_wait_refused': True}},
}


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


def q(value):
    """A PowerShell single-quoted literal."""
    return "'" + str(value).replace("'", "''") + "'"


PRELUDE = r'''$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
foreach($m in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$m\$m.psd1")}
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile(SCRIPT_PATH,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
foreach($f in $ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){. ([scriptblock]::Create($f.Extent.Text))}
'''

HELPERS = r'''$definitions=@(Import-ReviewedFunctions HELPER_PATH 'HELPER_SHA' @('Get-LocalPath','Assert-NoReparseAncestors','Assert-ProtectedPath','New-CodeAcl','New-ProtectedDirectory','Initialize-FileIdentity','Open-VerifiedFile','Read-Inventory','Copy-VerifiedPayload'))
foreach($definition in $definitions){. ([scriptblock]::Create($definition))}
Initialize-FileIdentity
'''.replace('HELPER_PATH', q(COPY_HELPER)).replace('HELPER_SHA', COPY_HELPER_SHA256)

# Boundary stubs for the Apply function: owner/ACL custody checks need SYSTEM/Administrators ownership, which a
# temp tree cannot have; files are still created through the real CreateNew helpers with a current-user ACL, and
# the real Protect-NewRuntimeTree walks the tree (identity checks included) with Set-Acl recorded, not applied.
BOUNDARY = r'''function Assert-ProtectedPath {param([string]$Path)}
$script:aclsSet=0;function Set-Acl {param($LiteralPath,$AclObject)$script:aclsSet++}
function New-CodeAcl {param([bool]$Directory)
  $acl=if($Directory){[Security.AccessControl.DirectorySecurity]::new()}else{[Security.AccessControl.FileSecurity]::new()}
  $inherit=if($Directory){[Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'}else{[Security.AccessControl.InheritanceFlags]::None}
  $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.WindowsIdentity]::GetCurrent().User,[Security.AccessControl.FileSystemRights]::FullControl,$inherit,[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow))
  $acl}
function Assert-CodeTreeOnce {param($Path)15013}
'''

# A read-only task folder: only GetTask exists, so any registration, run, stop, enable or delete call would fail.
FOLDER = r'''$script:taskMode='running';$script:denialMode='valid';$script:getTaskCalls=[Collections.Generic.List[string]]::new()
function New-FixtureDenialTask {
  $root='C:\Program Files\CoChem\WorkerDenial4.2.7-windows-20261006-slot1'
  $script:denialAction=[pscustomobject]@{Type=0;Path='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261006\.venv\Scripts\python.exe';Arguments=('-I -B "'+$root+'\worker-denial-acceptance.py" --slot slot1 --nonce 06478e2f265546cd8257aa09111373f4');WorkingDirectory=$root}
  $actions=[pscustomobject]@{Count=1};$actions|Add-Member ScriptMethod Item {param($i)$script:denialAction}
  $task=[pscustomobject]@{State=3;LastTaskResult=$(if($script:denialMode -eq 'invalid'){0}else{2});Definition=[pscustomobject]@{
    Principal=[pscustomobject]@{UserId='SYSTEM';LogonType=5;RunLevel=1};Triggers=[pscustomobject]@{Count=0};Actions=$actions}}
  $task|Add-Member ScriptMethod GetInstances {param($n)@{Count=0}};$task}
function New-FixtureFolder {
  $folder=[pscustomobject]@{}
  $folder|Add-Member ScriptMethod GetTask {param($name)
    $script:getTaskCalls.Add($name)
    if($name -eq 'CoChem-4.2.7-WorkerDenial-slot1'){return (New-FixtureDenialTask)}
    if($script:taskMode -eq 'absent'){throw [Runtime.InteropServices.COMException]::new('missing',-2147024894)}
    if($script:taskMode -eq 'denied'){throw [Runtime.InteropServices.COMException]::new('denied',-2147024891)}
    $path=if($script:taskMode -eq 'references'){$script:targetRoot+'\.venv\Scripts\python.exe'}else{'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\Scripts\python.exe'}
    $action=[pscustomobject]@{Path=$path;Arguments='-I -B -m cochem_pipeline daemon --config x';WorkingDirectory='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4'}
    $task=[pscustomobject]@{Enabled=$true;State=4;Definition=[pscustomobject]@{Actions=@($action)}}
    $task|Add-Member ScriptMethod GetInstances {param($flags)@{Count=1}};$task}
  $folder}
'''

SPIES = r'''$script:mutations=[Collections.Generic.List[string]]::new()
function New-ProtectedDirectory {param($Path)$script:mutations.Add('New-ProtectedDirectory')}
function Copy-VerifiedPayload {param($File)$script:mutations.Add('Copy-VerifiedPayload')}
function Write-NewRuntimeReport {param($Path,$Value)$script:mutations.Add('Write-NewRuntimeReport')}
function Invoke-FrozenRuntimeBuild {$script:mutations.Add('Invoke-FrozenRuntimeBuild')}
function Protect-NewRuntimeTree {param($Path)$script:mutations.Add('Protect-NewRuntimeTree')}
function Invoke-NewRuntimeValidation {param($Root)$script:mutations.Add('Invoke-NewRuntimeValidation')}
function Invoke-NewRuntimeInstallation {$script:mutations.Add('Invoke-NewRuntimeInstallation')}
function Set-Acl {$script:mutations.Add('Set-Acl')}
'''

_RUN_DIR = None


@pytest.fixture(scope='session', autouse=True)
def _case_directory(tmp_path_factory):
    global _RUN_DIR
    _RUN_DIR = tmp_path_factory.mktemp('ps-cases')


def run(body, timeout=180):
    path = _RUN_DIR / ('case-' + uuid.uuid4().hex + '.ps1')
    path.write_text(PRELUDE.replace('SCRIPT_PATH', q(SCRIPT)) + body + '\n', encoding='utf-8')
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(path)],
                          capture_output=True, text=True, timeout=timeout)


def result(completed):
    assert completed.returncode == 0, completed.stderr + completed.stdout
    lines = [line for line in completed.stdout.splitlines() if line.startswith('RESULT:')]
    assert len(lines) == 1, completed.stdout + completed.stderr
    return json.loads(lines[0][len('RESULT:'):])


def emit(fields):
    """PowerShell that prints one RESULT line from an [ordered] literal body."""
    return "'RESULT:'+([ordered]@{" + fields + "}|ConvertTo-Json -Compress -Depth 12)"


def manifest_bytes(stage, target_root, overrides, mutate=None):
    """A freeze manifest in BUILD-FREEZE's final shape (r4 keys unchanged, r5 keys before files)."""
    r4 = json.loads((R4 / 'source-manifest.json').read_text(encoding='utf-8'))
    rows, changed = [], []
    for row in r4['files']:
        if row['relative'] in overrides:
            data = overrides[row['relative']]
            rows.append({'relative': row['relative'], 'sha256': sha256_bytes(data), 'length': len(data)})
            changed.append(row['relative'])
        else:
            rows.append(dict(row))
    shas = {row['relative']: row['sha256'] for row in rows if row['relative'] in overrides}
    manifest = {
        'schema': 'cochem-stopped-runtime-source/1', 'host': 'AETHERDESK', 'captured_utc': '2026-10-11T12:00:00+00:00',
        'complete_source_freeze': True, 'source_repository': str(stage), 'target_root': str(target_root),
        'previous_source_manifest_sha256': R4_MANIFEST_SHA256, 'previous_install_receipt_sha256': R4_INSTALL_SHA256,
        'previous_manifest_entries': 166, 'max_execution_slots': 4, 'worker_identities': 6,
        'configuration_sha256': CONFIG_SHA256, 'configuration_unchanged': True, 'scope': 'r5 harness fixture',
        'changes_from_previous_source': {'added': [], 'removed': [], 'changed': list(changed)},
        'captured_utc_basis': 'committer timestamp of source_commit', 'source_commit': SOURCE_COMMIT,
        'verified_unchanged': 166 - len(changed), 'reviewed_repairs': list(changed),
        'reviewed_repairs_sha256': {relative: shas[relative] for relative in changed},
        'files': rows,
    }
    if mutate:
        mutate(manifest)
    return (json.dumps(manifest, indent=2) + '\n').encode('ascii')


def write_manifest(directory, stage, target_root, overrides, mutate=None):
    path = Path(directory) / 'stopped-runtime-r5-source-manifest.json'
    data = manifest_bytes(stage, target_root, overrides, mutate)
    path.write_bytes(data)
    return path, sha256_bytes(data)


def pins_literal(pins):
    if pins is None:
        return ''
    return '$script:reviewedRepairPins=[ordered]@{' + ';'.join(q(k) + '=' + q(v) for k, v in pins.items()) + '}\n'


def committed_blob(relative):
    """Raw blob bytes of the reviewed commit (read-only git; no smudge filters on cat-file)."""
    completed = subprocess.run(['git', '-C', str(REPO), 'cat-file', 'blob', SOURCE_COMMIT + ':' + relative],
                               capture_output=True, timeout=60)
    assert completed.returncode == 0, completed.stderr.decode(errors='replace')
    return completed.stdout


@pytest.fixture(scope='session')
def world(tmp_path_factory):
    """The r5 stage exactly as the freeze builds it: the reviewed r4 tree plus the 13 committed blobs of 8554c76."""
    top = tmp_path_factory.mktemp('r5world')
    stage = top / 'stage'
    shutil.copytree(R4_STAGE, stage)
    r4 = json.loads((R4 / 'source-manifest.json').read_text(encoding='utf-8'))
    for row in r4['files']:
        data = (stage / row['relative']).read_bytes()
        assert sha256_bytes(data) == row['sha256'] and len(data) == row['length'], row['relative']
    overrides = {}
    for relative in REPAIRS:
        data = committed_blob(relative)
        (stage / relative).write_bytes(data)
        overrides[relative] = data
    toolchain = top / 'toolchain'
    toolchain.mkdir()
    (toolchain / 'python.exe').write_bytes(b'fixture base python\n')
    (toolchain / 'uv.exe').write_bytes(b'fixture uv\n')
    order = [row['relative'] for row in r4['files'] if row['relative'] in overrides]
    pins = {relative: sha256_bytes(overrides[relative]) for relative in REPAIRS}
    assert pins == PINS, 'the committed blobs must equal the reviewed pins'
    return SimpleNamespace(top=top, stage=stage, overrides=overrides, python=toolchain / 'python.exe',
                           uv=toolchain / 'uv.exe', order=order, pins=pins)


def constants(world, base, target, stage=None):
    """Production constants with only the fresh roots, the stage and the toolchain binaries redirected."""
    return ('Set-InstallerConstants\n'
            '$script:base=' + q(base) + ';$script:repo=' + q(stage or world.stage) + ';$script:targetRoot=' + q(target)
            + ";$script:sourceRoot=Join-Path $script:targetRoot 'source'\n"
            '$script:python=' + q(world.python) + ";$script:pythonHash='" + sha256_file(world.python) + "'"
            + ';$script:uv=' + q(world.uv) + ";$script:uvHash='" + sha256_file(world.uv) + "'\n")


def snapshot(*roots):
    entries = {}
    for root in roots:
        for path in Path(root).rglob('*'):
            info = path.stat()
            entries[str(path)] = (path.is_dir(), info.st_size if path.is_file() else 0, info.st_mtime_ns)
    return entries


def ps_functions(path):
    """name -> sha256 of each function's exact text (PowerShell AST extents)."""
    completed = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', (
        "$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile(" + q(path)
        + ",[ref]$tokens,[ref]$errors);if($errors.Count){throw 'parse'};"
        "$ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)|ForEach-Object {"
        "[pscustomobject]@{name=$_.Name;sha=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($_.Extent.Text))).Replace('-','')}}|ConvertTo-Json -Compress")],
        capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    return {row['name']: row['sha'] for row in json.loads(completed.stdout)}


def validation_body():
    text = SCRIPT.read_text(encoding='utf-8').replace('\r\n', '\n')
    return text.split("$validation=@'\n", 1)[1].split("\n'@", 1)[0]


# ---------------------------------------------------------------------------------------------- static

def test_script_is_ascii_crlf_and_parses_in_windows_powershell_51():
    raw = SCRIPT.read_bytes()
    assert all(byte < 128 for byte in raw), 'owner scripts are ASCII only'
    assert not raw.startswith(b'\xef\xbb\xbf')
    assert raw.startswith(b'#Requires -Version 5.1')
    completed = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', (
        "$t=$null;$e=$null;$null=[Management.Automation.Language.Parser]::ParseFile(" + q(SCRIPT) + ",[ref]$t,[ref]$e);"
        "'{0}|{1}' -f $e.Count,$PSVersionTable.PSVersion.Major")], capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == '0|5'


def test_harness_is_ascii():
    assert all(byte < 128 for byte in Path(__file__).read_bytes())


def test_no_powershell_7_only_syntax():
    text = SCRIPT.read_text(encoding='utf-8')
    code = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))
    for token in ('&&', '||', '??', '?.', ' ? ', '-Parallel', '-AsHashtable', 'ConvertFrom-Json -Depth', '-AsArray',
                  '-AdditionalChildPath', 'Test-Json', '$PSStyle', 'Get-Error', 'clean{', 'clean {'):
        assert token not in code, token


def test_script_pins_r4_as_previous_and_targets_the_dated_r5_root():
    text = SCRIPT.read_text(encoding='utf-8')
    assert "'Pipeline4.2.7-windows-20261009-r4'" in text and "'Pipeline4.2.7-windows-20261011-r5'" in text
    assert "$script:repo='C:\\Users\\ansac\\CoChem427\\stopped-runtime-r5-source'" in text
    for pin in (R4_MANIFEST_SHA256, R4_INSTALL_SHA256, R4_REVISION_SHA256, CONFIG_SHA256, LAYOUT_SHA256, DENIAL_SHA256,
                TELEMETRY_REPAIR_SHA256, PYTHON_SHA256, UV_SHA256, COPY_HELPER_SHA256, TREE_HELPER_SHA256):
        assert pin in text, pin
    assert 'install_pipeline_windows' not in text.replace('Never calls install_pipeline_windows.ps1', '')


def test_never_touches_tasks_services_processes_or_host_lifecycle():
    text = SCRIPT.read_text(encoding='utf-8')
    for forbidden in ('Register-ScheduledTask', 'Unregister-ScheduledTask', 'Start-ScheduledTask', 'Stop-ScheduledTask',
                      'Enable-ScheduledTask', 'Disable-ScheduledTask', 'Set-ScheduledTask', 'schtasks', 'RegisterTaskDefinition',
                      'DeleteTask', '.Run(', '.Stop(', '.Enabled=', 'Start-Process', 'Stop-Process', 'taskkill', 'Set-Service',
                      'Stop-Service', 'Start-Service', 'Restart-Service', 'New-Service', 'Restart-Computer', 'Stop-Computer',
                      'Invoke-Expression', 'iex ', 'cmd /c', 'cmd.exe', 'RunAs', 'provision-execution', 'cochem_pipeline daemon',
                      '-m cochem_supervisor', 'Remove-Item', 'Move-Item', 'Copy-Item', 'Set-Content', 'Add-Content', 'Out-File',
                      'WriteAllText', 'WriteAllBytes', 'bcdedit', 'HKLM:', 'Set-ItemProperty', '.wslconfig', 'diskpart', 'imdisk'):
        assert forbidden not in text, forbidden
    for pattern in (r'\bdocker(\.exe)?\s', r'\bwsl(\.exe)?\b', r'\bpip\s+install\b', r'\bclaude\s+-p\b', r'\bagy\.exe\b'):
        assert not re.search(pattern, text, re.IGNORECASE), pattern
    # The only task COM calls are reads.
    assert set(re.findall(r'\$(?:Folder|folder|task|scheduler)\.(\w+)\(', text)) <= {'GetTask', 'GetInstances', 'Connect', 'GetFolder'}
    # Every report is CreateNew; the only other write is uv's own log, refused when it already exists.
    assert text.count('[IO.FileMode]::CreateNew') == 1
    assert "if(Test-Path -LiteralPath $log){throw 'Preserve existing build log.'}" in text
    for mode in ('FileMode]::Create)', 'FileMode]::Create,', 'OpenOrCreate', 'Truncate', 'FileMode]::Append'):
        assert mode not in text, mode


def test_apply_runs_only_after_a_plan_without_holds():
    text = SCRIPT.read_text(encoding='utf-8')
    main = text.split('function Invoke-InstallerMain', 1)[1]
    plan_return = main.index("if(-not $ApplyRequested){return ($plan|ConvertTo-Json -Depth 6)}")
    hold_gate = main.index("if($holds.Count){throw ($holds -join ' ')}")
    install = main.index('Invoke-NewRuntimeInstallation $files $controlFiles $Folder $plan $repairs')
    assert plan_return < hold_gate < install
    boundary = text.split('# Invocation boundary.', 1)[1]
    assert boundary.index('Assert-ApplyAuthority') < boundary.index('Set-InstallerConstants') < boundary.index('Invoke-InstallerMain')


def test_reviewed_helper_pins_are_recomputed_from_disk():
    assert sha256_file(COPY_HELPER) == COPY_HELPER_SHA256
    assert sha256_file(TREE_HELPER) == TREE_HELPER_SHA256
    text = SCRIPT.read_text(encoding='utf-8')
    assert "$script:copyHelperHash='" + COPY_HELPER_SHA256 + "'" in text
    assert "$script:treeHelperHash='" + TREE_HELPER_SHA256 + "'" in text


def test_production_pins_match_the_files_on_disk_read_only():
    assert sha256_file(TOOLCHAIN_PYTHON) == PYTHON_SHA256
    assert sha256_file(TOOLCHAIN_UV) == UV_SHA256
    assert sha256_file(R4 / 'pipeline.json') == CONFIG_SHA256
    assert sha256_file(COMMISSIONED) == CONFIG_SHA256
    assert sha256_file(R4 / 'windows-layout.json') == LAYOUT_SHA256
    assert sha256_file(R4 / 'source-manifest.json') == R4_MANIFEST_SHA256
    assert sha256_file(R4 / 'install-after.json') == R4_INSTALL_SHA256
    assert sha256_file(DENIAL) == DENIAL_SHA256
    assert sha256_file(R4 / '.venv' / 'pyvenv.cfg') == PYVENV_SHA256
    assert sha256_file(R4 / '.venv' / 'Scripts' / 'python.exe') == VENV_PYTHON_SHA256


def test_production_constants():
    value = result(run('Set-InstallerConstants\n' + emit(
        "base=$script:base;repo=$script:repo;old=$script:oldRoot;r3=$script:r3Root;target=$script:targetRoot;source=$script:sourceRoot;"
        "python=$script:python;uv=$script:uv;config=$script:oldConfig;layout=$script:layout;commissioned=$script:commissionedConfig;"
        "mutex=$script:setupMutexName;paths=[object[]]$script:reviewedRepairPaths;lf=[object[]]$script:lfRepairPaths;"
        "unchanged=$script:expectedUnchanged;pin_keys=[object[]]@($script:reviewedRepairPins.Keys);inherited=$script:inheritedRepair;"
        "denial=$script:denialPath;helper=$script:copyHelper")))
    assert value['base'] == str(BASE) and value['old'] == str(R4) and value['r3'] == str(R3)
    assert value['target'] == R5_TARGET and value['source'] == R5_TARGET + '\\source'
    assert value['repo'] == str(R5_STAGE)
    assert value['python'] == str(TOOLCHAIN_PYTHON) and value['uv'] == str(TOOLCHAIN_UV)
    assert value['config'] == str(R4 / 'pipeline.json') and value['layout'] == str(R4 / 'windows-layout.json')
    assert value['commissioned'] == str(COMMISSIONED) and value['denial'] == str(DENIAL)
    assert value['mutex'] == 'Global\\CoChem427-CodeOnlyRuntimeUpdate'
    assert value['paths'] == REPAIRS and value['lf'] == sorted(LF_REPAIRS) and value['unchanged'] == 153
    assert value['pin_keys'] == REPAIRS and value['inherited'] == TELEMETRY_REPAIR
    assert value['helper'] == str(COPY_HELPER)


def test_the_13_repair_paths_exist_in_r4_and_keep_their_conventions():
    rows = {row['relative']: row for row in json.loads((R4 / 'source-manifest.json').read_text(encoding='utf-8'))['files']}
    assert len(rows) == 166 and len(REPAIRS) == 13 and len(set(REPAIRS)) == 13
    assert 'src/cochem_pipeline/__main__.py' in REPAIRS
    for relative in REPAIRS:
        assert relative in rows
        data = (R4 / 'source' / relative).read_bytes()
        if relative in LF_REPAIRS:
            assert b'\r' not in data
        else:
            assert data.count(b'\r\n') > data.count(b'\n') // 2, relative


def test_embedded_repair_pins_are_the_reviewed_table_in_order():
    value = result(run('Set-InstallerConstants\n' + emit("keys=[object[]]@($script:reviewedRepairPins.Keys);values=[object[]]@($script:reviewedRepairPins.Values);"
                                                         "filled=(Test-ReviewedRepairPinsFilled $script:reviewedRepairPins)")))
    assert value['keys'] == REPAIRS and dict(zip(value['keys'], value['values'])) == PINS
    assert value['filled'] is True and ("='" + PLACEHOLDER + "'") not in SCRIPT.read_text(encoding='utf-8')


def test_embedded_pins_equal_the_freeze_table_and_the_committed_blobs():
    """Same source for both two-key halves: BUILD-FREEZE's REPAIRS table and the blobs of the reviewed commit."""
    import ast
    tree = ast.parse(FREEZE.read_text(encoding='utf-8'))
    table = next(ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == 'REPAIRS' for t in node.targets))
    assert [row[0] for row in table] == REPAIRS
    assert {row[0]: row[2] for row in table} == PINS
    assert {row[0]: row[1] for row in table} == {relative: ('LF' if relative in LF_REPAIRS else 'CRLF') for relative in REPAIRS}
    for relative in REPAIRS:
        data = committed_blob(relative)
        assert sha256_bytes(data) == PINS[relative], relative
        if relative in LF_REPAIRS:
            assert b'\r' not in data and data.count(b'\n') > 0, relative
        else:
            assert data.count(b'\r\n') == data.count(b'\n') == data.count(b'\r') > 0, relative
        assert data != (R4 / 'source' / relative).read_bytes(), relative + ' must differ from r4'


def test_filled_repair_pins_equal_the_frozen_manifest():
    if not R5_MANIFEST.exists():
        pytest.skip('the r5 freeze manifest does not exist yet (the Commander runs the real freeze)')
    manifest = json.loads(R5_MANIFEST.read_text(encoding='utf-8'))
    assert manifest['reviewed_repairs'] == REPAIRS and manifest['reviewed_repairs_sha256'] == PINS
    assert manifest['source_commit'] == SOURCE_COMMIT and manifest['verified_unchanged'] == 153
    assert manifest['target_root'] == R5_TARGET and manifest['source_repository'] == str(R5_STAGE)


def test_unchanged_functions_match_the_reviewed_r4_installer():
    """Functions carried over from r4 stay byte-identical; only the listed ones may differ."""
    r4 = ps_functions(R4_SCRIPT)
    r5 = ps_functions(SCRIPT)
    allowed_to_differ = {'Get-RuntimeFiles', 'Assert-PriorReceipts', 'Invoke-NewRuntimeValidation', 'Invoke-NewRuntimeInstallation'}
    renamed = {'Assert-ReviewedR4Delta': 'Assert-ReviewedR5Delta'}
    for name, sha in r4.items():
        if name in renamed:
            assert renamed[name] in r5 and name not in r5
            continue
        assert name in r5, name
        if name not in allowed_to_differ:
            assert r5[name] == sha, name + ' drifted from the reviewed r4 definition'
    added = set(r5) - set(r4) - set(renamed.values())
    assert added == {'Get-OptionalMember', 'Test-SameOrdinalSet', 'Test-ReviewedRepairPinsFilled', 'Get-ManifestRepairs',
                     'Test-PureLineEndings', 'Assert-RepairLineEndings', 'Get-R5SiblingRoots', 'Assert-InstalledRepairs',
                     'Write-InstallHeldRecord', 'New-InstallPlan', 'Assert-InstallerHost', 'Assert-ApplyAuthority',
                     'Set-InstallerConstants', 'Invoke-InstallerMain'}


def test_frozen_sync_arguments_equal_r4_except_the_source_path():
    r5 = result(run('Set-InstallerConstants\n' + emit('arguments=[object[]]@(Get-FrozenSyncArguments)')))['arguments']
    body = (r"$tokens=$null;$errors=$null;$a=[Management.Automation.Language.Parser]::ParseFile(" + q(R4_SCRIPT)
            + r",[ref]$tokens,[ref]$errors);$f=$a.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-FrozenSyncArguments'},$true);"
            r". ([scriptblock]::Create($f.Extent.Text));$script:sourceRoot=" + q(R4 / 'source') + ";$script:python=" + q(TOOLCHAIN_PYTHON) + "\n"
            + emit('arguments=[object[]]@(Get-FrozenSyncArguments)'))
    r4 = result(run(body))['arguments']
    assert len(r4) == len(r5) == 14
    assert [i for i, (a, b) in enumerate(zip(r4, r5)) if a != b] == [4]
    assert r4[4] == str(R4 / 'source') and r5[4] == R5_TARGET + '\\source'
    assert r5[:3] == ['--no-config', '--no-cache', 'sync'] and r5[r5.index('--link-mode') + 1] == 'copy'
    assert r5[r5.index('--extra') + 1] == 'mcp' and r5[r5.index('--python') + 1] == str(TOOLCHAIN_PYTHON)
    assert '--frozen' in r5 and '--no-editable' in r5 and r5[-1] == '--no-python-downloads'


def test_validation_body_is_argv_safe_and_names_every_s1_check():
    body = validation_body()
    assert all(ord(char) < 128 for char in body)
    assert '"' not in body, 'PS 5.1 native argument passing would mangle double quotes'
    assert not body.rstrip().endswith('\\')
    for marker in ("load_config(str(root/'pipeline.json'))", 'config.max_execution_slots==4 and len(config.workers)==6',
                   "config.ramdisk.workspace_subdirectory=='CoChem427-windows-20261007'",
                   'telemetry repair missing: PerformanceInformation/_commit_probe', 'verify_installed_revision(root/',
                   "'r5 repair missing: agy_protocol.IDENTITY_POLICY'", 'agy_protocol.parse_stream(stream,model,identity_policy=',
                   'reconcile_chapter_wbs(job[', 'JobStore._chapter(job,drifted)', 'JobStore._chapter(job,reconciled)',
                   'read_workspace(Path(folder))', "'--queue-launch-output-root','queue-launch-r5','--docker-wait-seconds','900'",
                   "'no_system_or_model_execution':True", "'r5_repairs_installed':True"):
        assert marker in body, marker
    for forbidden in ('subprocess', 'socket', 'urllib', 'http.client', 'sqlite3.connect', 'JobStore(', 'Runtime(', 'entry.daemon(',
                      'saved[0](', 'os.system', 'ControlClient(', 'queue_launch_output_child(', 'wait_for_docker('):
        assert forbidden not in body, forbidden
    # The real daemon is replaced before main() parses, and restored afterwards.
    assert body.index('entry.daemon=lambda') < body.index('entry.main()') < body.index('entry.daemon,sys.argv=saved')


# ---------------------------------------------------------------------------------------------- units

@pytest.mark.parametrize('case', ['valid', 'unsafe', 'duplicate', 'incomplete', 'baseline', 'previous_install', 'previous_install_missing',
                                  'config_sha', 'config_unchanged_false', 'config_unchanged_string', 'missing_required', 'missing_main',
                                  'previous_target', 'wrong_repo', 'wrong_schema', 'wrong_host', 'pycache', 'backslash', 'oversize'])
def test_inventory_is_complete_confined_and_bound_to_the_r4_installation(case):
    value = result(run("$case='" + case + "'\n" + r'''
      Set-InstallerConstants
      $script:repo='D:\stage';$script:targetRoot='C:\Program Files\CoChem\new';$script:sourceRoot=$script:targetRoot+'\source'
      $required=@('README.md','pyproject.toml','uv.lock','src/cochem_pipeline/resource_telemetry.py','src/cochem_pipeline/resource_limits.py','src/cochem_pipeline/ramdisk.py','src/cochem_pipeline/deployment.py','src/cochem_pipeline/deployment_revision.py','src/cochem_supervisor/engine.py')+@($script:reviewedRepairPaths)
      $rows=@($required|ForEach-Object {[pscustomobject]@{relative=$_;sha256=('a'*64);length=1}})
      foreach($i in 1..90){$rows+=[pscustomobject]@{relative="src/package/item$i.py";sha256=('a'*64);length=1}}
      $inventory=[pscustomobject]@{schema='cochem-stopped-runtime-source/1';host='AETHERDESK';complete_source_freeze=$true;source_repository=$script:repo;target_root=$script:targetRoot;
        previous_source_manifest_sha256=$script:priorManifestHash;previous_install_receipt_sha256=$script:priorInstallHash;configuration_sha256=$script:configHash;configuration_unchanged=$true;files=$rows}
      switch($case){
        'unsafe'{$rows[30].relative='src/../../secret'}
        'duplicate'{$rows[30].relative='SRC/COCHEM_PIPELINE/ramdisk.py'}
        'incomplete'{$inventory.complete_source_freeze=$false}
        'baseline'{$inventory.previous_source_manifest_sha256=('b'*64)}
        'previous_install'{$inventory.previous_install_receipt_sha256=('c'*64)}
        'previous_install_missing'{$inventory.PSObject.Properties.Remove('previous_install_receipt_sha256')}
        'config_sha'{$inventory.configuration_sha256=('d'*64)}
        'config_unchanged_false'{$inventory.configuration_unchanged=$false}
        'config_unchanged_string'{$inventory.configuration_unchanged='true'}
        'missing_required'{$rows[0].relative='src/other.md'}
        'missing_main'{if($rows[9].relative -cne 'src/cochem_pipeline/__main__.py'){throw 'fixture index'};$rows[9].relative='src/cochem_pipeline/other_main.py'}
        'previous_target'{$inventory.target_root='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4'}
        'wrong_repo'{$inventory.source_repository='C:\Users\ansac\CoChem427\stopped-runtime-r4-source'}
        'wrong_schema'{$inventory.schema='cochem-stopped-runtime-source/2'}
        'wrong_host'{$inventory.host='OTHERHOST'}
        'pycache'{$rows[30].relative='src/cochem_pipeline/__pycache__/x.cpython-312.pyc'}
        'backslash'{$rows[30].relative='src\cochem_pipeline\x.py'}
        'oversize'{$rows[30].length=16777217}
      }
      $refused=$false;$count=0;try{$files=@(Get-RuntimeFiles $inventory);$count=$files.Count}catch{$refused=$true}
    ''' + emit('refused=$refused;count=$count;rows=$rows.Count')))
    assert value['refused'] == (case != 'valid')
    assert value['count'] == (value['rows'] if case == 'valid' else 0)


DELTA_CASES = ['valid', 'null_pins', 'placeholder_pins', 'missing_change', 'extra_change', 'wrong_pin', 'added', 'removed', 'duplicate',
               'declared_changed_short', 'declared_added', 'declared_removed_missing', 'reviewed_repairs_missing',
               'reviewed_sha_missing', 'reviewed_sha_mismatch', 'reviewed_sha_extra_key', 'reviewed_list_duplicate',
               'reviewed_sha_case_alias', 'verified_unchanged_wrong', 'verified_unchanged_string', 'verified_unchanged_missing',
               'source_commit_short', 'expected_paths_tampered']


@pytest.mark.parametrize('case', DELTA_CASES)
def test_reviewed_r5_delta_accepts_exactly_the_13_pinned_repairs(world, tmp_path, case):
    manifest, _ = write_manifest(tmp_path, world.stage, R5_TARGET, world.overrides)
    pins = None if case == 'null_pins' else dict(world.pins)
    if case == 'wrong_pin':
        pins['src/cochem_pipeline/store.py'] = 'f' * 64
    if case == 'placeholder_pins':
        pins = {relative: PLACEHOLDER for relative in REPAIRS}
    body = ('Set-InstallerConstants\n' + pins_literal(world.pins) + "$case='" + case + "'\n"
            + '$current=Get-Content -LiteralPath ' + q(manifest) + ' -Raw|ConvertFrom-Json\n'
            + '$prior=Get-Content -LiteralPath ' + q(R4 / 'source-manifest.json') + ' -Raw|ConvertFrom-Json\n'
            + ('$pins=$null\n' if pins is None else '$pins=[ordered]@{' + ';'.join(q(k) + '=' + q(v) for k, v in pins.items()) + '}\n')
            + r'''
      function Get-Row {param($m,$r)@($m.files|Where-Object {$_.relative -ceq $r})[0]}
      switch($case){
        'missing_change'{$row=Get-Row $current 'src/cochem_pipeline/store.py';$before=Get-Row $prior 'src/cochem_pipeline/store.py';$row.sha256=$before.sha256;$row.length=$before.length}
        'extra_change'{(Get-Row $current 'README.md').sha256='a'*64}
        'added'{(Get-Row $current 'README.md').relative='src/extra.py'}
        'removed'{$current.files=@($current.files|Select-Object -Skip 1)}
        'duplicate'{$current.files[1].relative=$current.files[0].relative}
        'declared_changed_short'{$current.changes_from_previous_source.changed=@($current.changes_from_previous_source.changed|Select-Object -Skip 1)}
        'declared_added'{$current.changes_from_previous_source.added=@('src/extra.py')}
        'declared_removed_missing'{$current.changes_from_previous_source.PSObject.Properties.Remove('removed')}
        'reviewed_repairs_missing'{$current.PSObject.Properties.Remove('reviewed_repairs')}
        'reviewed_sha_missing'{$current.PSObject.Properties.Remove('reviewed_repairs_sha256')}
        'reviewed_sha_mismatch'{$current.reviewed_repairs_sha256.'src/cochem_pipeline/store.py'='e'*64}
        'reviewed_sha_extra_key'{$current.reviewed_repairs_sha256|Add-Member NoteProperty 'src/cochem_pipeline/extra.py' ('a'*64)}
        'reviewed_list_duplicate'{$current.reviewed_repairs=@($current.reviewed_repairs)+@('src/cochem_pipeline/store.py')}
        'reviewed_sha_case_alias'{$map=$current.reviewed_repairs_sha256;$v=$map.'src/cochem_pipeline/store.py';$map.PSObject.Properties.Remove('src/cochem_pipeline/store.py');$map|Add-Member NoteProperty 'SRC/cochem_pipeline/store.py' $v}
        'verified_unchanged_wrong'{$current.verified_unchanged=154}
        'verified_unchanged_string'{$current.verified_unchanged='153'}
        'verified_unchanged_missing'{$current.PSObject.Properties.Remove('verified_unchanged')}
        'source_commit_short'{$current.source_commit='0123456'}
        'expected_paths_tampered'{$script:reviewedRepairPaths=@($script:reviewedRepairPaths|Select-Object -Skip 1)}
      }
      $refused=$false;$message='';$records=@()
      try{$records=@(Assert-ReviewedR5Delta $current $prior $pins)}catch{$refused=$true;$message=$_.Exception.Message}
    ''' + emit("refused=$refused;message=$message;relative=[object[]]@($records|ForEach-Object {$_.relative});"
               "sha=[object[]]@($records|ForEach-Object {$_.sha256});eol=[object[]]@($records|ForEach-Object {$_.line_endings})"))
    value = result(run(body))
    assert value['refused'] == (case != 'valid'), value['message']
    if case in ('null_pins', 'placeholder_pins'):
        assert 'PIN-AFTER-COMMIT' in value['message']
    if not value['refused']:
        assert value['relative'] == world.order and sorted(world.order) == REPAIRS
        assert value['sha'] == [world.pins[relative] for relative in world.order]
        assert value['eol'] == ['LF' if relative in LF_REPAIRS else 'CRLF' for relative in world.order]


@pytest.mark.parametrize('case,convention,data,expected', [
    ('crlf_pure', 'CRLF', b'a\r\nb\r\n', True),
    ('crlf_mixed', 'CRLF', b'a\r\nb\n', False),
    ('crlf_lone_cr', 'CRLF', b'a\r\nb\rc\r\n', False),
    ('crlf_without_newline', 'CRLF', b'abc', False),
    ('lf_pure', 'LF', b'a\nb\n', True),
    ('lf_with_crlf', 'LF', b'a\r\nb\n', False),
    ('lf_lone_cr', 'LF', b'a\rb\n', False),
    ('unknown_convention', 'CR', b'a\rb\r', False),
    ('utf8_crlf', 'CRLF', 'caf\u00e9 \u2014 ok\r\nnext\r\n'.encode('utf-8'), True),
])
def test_pure_line_endings(case, convention, data, expected):
    value = result(run("$bytes=[Convert]::FromBase64String('" + base64.b64encode(data).decode() + "')\n"
                       + emit("pure=(Test-PureLineEndings $bytes '" + convention + "')")))
    assert value['pure'] is expected, case


@pytest.mark.parametrize('case', ['valid', 'mode', 'target', 'previous_root', 'manifest', 'previous_manifest', 'previous_install', 'config',
                                  'files', 'reviewed_repair', 'reviewed_repair_sha', 'tasks_changed', 'holds', 'telemetry_flag',
                                  'revision_files', 'source_sha', 'denial_status', 'denial_nonce', 'denial_winerror'])
def test_prior_receipts_must_be_the_exact_preserved_r4_installation(case):
    value = result(run("$case='" + case + "'\nSet-InstallerConstants\n" + r'''
      $install=Get-Content -LiteralPath (Join-Path $script:oldRoot 'install-after.json') -Raw|ConvertFrom-Json
      $denial=Get-Content -LiteralPath $script:denialPath -Raw|ConvertFrom-Json
      switch($case){
        'mode'{$install.mode='READ_ONLY_PLAN'}
        'target'{$install.target_root='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r3'}
        'previous_root'{$install.previous_runtime_root='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261006'}
        'manifest'{$install.source_manifest_sha256='c'*64}
        'previous_manifest'{$install.previous_source_manifest_sha256='c'*64}
        'previous_install'{$install.previous_install_receipt_sha256='c'*64}
        'config'{$install.configuration_sha256='c'*64}
        'files'{$install.source_files=165}
        'reviewed_repair'{$install.reviewed_repair='src/cochem_pipeline/worker.py'}
        'reviewed_repair_sha'{$install.reviewed_repair_sha256='c'*64}
        'tasks_changed'{$install.tasks_changed=1}
        'holds'{$install.holds=@('held')}
        'telemetry_flag'{$install.verification.telemetry_repair_installed=$false}
        'revision_files'{$install.verification.revision.files=108}
        'source_sha'{$install.verification.revision.source_sha256='d'*64}
        'denial_status'{$denial.status='DENIAL_CHECK_PASSED'}
        'denial_nonce'{$denial.nonce='0'*32}
        'denial_winerror'{$denial.failure.winerror=5}
      }
      $refused=$false;try{Assert-PriorReceipts $install $denial}catch{$refused=$true}
    ''' + emit('refused=$refused')))
    assert value['refused'] == (case != 'valid')


@pytest.mark.parametrize('case', ['valid', 'capacity', 'worker', 'subtree', 'whitespace'])
def test_actual_r4_configuration_requires_exact_preservation(case):
    value = result(run("$case='" + case + "'\n" + r'''
      $before=Get-Content -LiteralPath 'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\pipeline.json' -Raw
      $after=$before
      switch($case){
        'capacity'{$after=$after.Replace('"max_execution_slots": 4','"max_execution_slots": 6')}
        'worker'{$after=$after.Replace('"slot6"','"other"')}
        'subtree'{$after=$after.Replace('CoChem427-windows-20261007','Different')}
        'whitespace'{$after=$after+" `n"}
      }
      if($case -ne 'valid' -and $before -ceq $after){throw 'Fixture did not mutate the configuration'}
      $refused=$false;try{Assert-ExactPreservedConfig $before $after}catch{$refused=$true}
    ''' + emit('refused=$refused')))
    assert value['refused'] == (case != 'valid')


@pytest.mark.parametrize('case', ['absent', 'denied', 'partial_denied', 'running', 'disabled', 'references_target', 'wrong_hresult', 'partial_other'])
def test_managed_daemon_task_state_never_requires_a_stopped_warden_and_flags_r5_references(case):
    value = result(run("$script:case='" + case + "';$script:targetRoot=" + q(R5_TARGET) + "\n" + r'''
      $folder=[pscustomobject]@{};$folder|Add-Member ScriptMethod GetTask {param($name)
        if($script:case -in @('absent','denied','wrong_hresult')){$code=if($script:case -eq 'absent'){-2147024894}elseif($script:case -eq 'denied'){-2147024891}else{-2147216625};throw [Runtime.InteropServices.COMException]::new('fixture',$code)}
        $path=if($script:case -eq 'references_target'){$script:targetRoot+'\.venv\Scripts\python.exe'}else{'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\Scripts\python.exe'}
        $action=[pscustomobject]@{Path=$path;Arguments='-I -B -m cochem_pipeline daemon --config x';WorkingDirectory='C:\Program Files\CoChem'}
        $task=[pscustomobject]@{Enabled=($script:case -ne 'disabled');State=$(if($script:case -eq 'running'){4}else{3});Definition=[pscustomobject]@{Actions=@($action)}}
        $task|Add-Member ScriptMethod GetInstances {param($unused)
          if($script:case -eq 'partial_denied'){throw [Runtime.InteropServices.COMException]::new('denied',-2147024891)}
          if($script:case -eq 'partial_other'){throw [Runtime.InteropServices.COMException]::new('other',-2147216625)}
          @{Count=$(if($script:case -eq 'running'){1}else{0})}};$task
      }
      $refused=$false;$states=@();try{$states=@(Get-ManagedDaemonTaskState $folder)}catch{$refused=$true}
    ''' + emit("refused=$refused;states=[object[]]@($states|ForEach-Object {$_.state});deferred=@($states|Where-Object {$_.state -eq 'ACCESS_DENIED_DEFERRED'}).Count;"
               "referencing=@($states|Where-Object {$_.references_new_root -eq $true}).Count")))
    assert value['refused'] == (case in ('wrong_hresult', 'partial_other'))
    if case == 'references_target':
        assert value['referencing'] == 4
    if case in ('denied', 'partial_denied'):
        assert value['deferred'] == 4
    if case in ('running', 'disabled'):
        assert value['deferred'] == 0 and value['referencing'] == 0 and all(state.startswith('ENABLED=') for state in value['states'])
    if case == 'absent':
        assert value['states'] == ['ABSENT'] * 4


@pytest.mark.parametrize('case', ['valid', 'missing', 'denied', 'running', 'instances', 'exit', 'nonce', 'principal', 'trigger'])
def test_original_failed_task_must_be_exact_and_terminal(case):
    value = result(run("$script:case='" + case + "'\n" + r'''
      $root='C:\Program Files\CoChem\WorkerDenial4.2.7-windows-20261006-slot1'
      $script:action=[pscustomobject]@{Type=0;Path='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261006\.venv\Scripts\python.exe';Arguments=('-I -B "'+$root+'\worker-denial-acceptance.py" --slot slot1 --nonce 06478e2f265546cd8257aa09111373f4');WorkingDirectory=$root}
      if($script:case -eq 'nonce'){$script:action.Arguments+='0'}
      $actions=[pscustomobject]@{Count=1};$actions|Add-Member ScriptMethod Item {param($i)$script:action}
      $script:task=[pscustomobject]@{State=$(if($script:case -eq 'running'){4}else{3});LastTaskResult=$(if($script:case -eq 'exit'){0}else{2});Definition=[pscustomobject]@{
        Principal=[pscustomobject]@{UserId=$(if($script:case -eq 'principal'){'ansac'}else{'SYSTEM'});LogonType=5;RunLevel=1};Triggers=[pscustomobject]@{Count=$(if($script:case -eq 'trigger'){1}else{0})};Actions=$actions}}
      $script:task|Add-Member ScriptMethod GetInstances {param($n)@{Count=$(if($script:case -eq 'instances'){1}else{0})}}
      $folder=[pscustomobject]@{};$folder|Add-Member ScriptMethod GetTask {param($name)
        if($script:case -eq 'missing'){throw [Runtime.InteropServices.COMException]::new('missing',-2147024894)}
        if($script:case -eq 'denied'){throw [Runtime.InteropServices.COMException]::new('denied',-2147024891)}
        $script:task}
      $refused=$false;try{Assert-PreservedDenialTask $folder}catch{$refused=$true}
    ''' + emit('refused=$refused')))
    assert value['refused'] == (case != 'valid')


def test_frozen_build_restores_environment_on_failure_and_does_not_call_installer(tmp_path):
    value = result(run("$script:targetRoot=" + q(tmp_path) + "\n" + r'''
      $script:sourceRoot=$script:targetRoot+'\source';$script:python='C:\protected\python.exe';$script:uv='Invoke-FixtureUv'
      $env:UV_INDEX_URL='fixture-existing-index';$env:PYTHONPATH='fixture-existing-pythonpath';$beforeTemp=$env:TEMP
      function Invoke-FixtureUv {
        if($null -ne $env:UV_INDEX_URL -or $null -ne $env:PYTHONPATH){throw 'Ambient policy leaked'}
        if($env:UV_PROJECT_ENVIRONMENT -ne ($script:targetRoot+'\.venv') -or $env:TEMP -ne ($script:targetRoot+'\build-temp')){throw 'Build escaped fresh root'}
        $script:arguments=@($args);$global:LASTEXITCODE=17
      }
      $failed=$false;try{Invoke-FrozenRuntimeBuild}catch{$failed=$true}
    ''' + emit("failed=$failed;restored=($env:UV_INDEX_URL -eq 'fixture-existing-index' -and $env:PYTHONPATH -eq 'fixture-existing-pythonpath' -and $env:TEMP -eq $beforeTemp);arguments=[object[]]$script:arguments")))
    assert value['failed'] and value['restored']
    arguments = value['arguments']
    assert arguments[:3] == ['--no-config', '--no-cache', 'sync']
    assert '--frozen' in arguments and '--no-editable' in arguments and '--no-python-downloads' in arguments
    assert arguments[arguments.index('--link-mode') + 1] == 'copy' and arguments[arguments.index('--extra') + 1] == 'mcp'
    assert not any('install_pipeline_windows' in item or 'provision' in item for item in arguments)


@pytest.mark.parametrize('exit_code', [0, 7])
def test_native_stderr_is_judged_by_exit_code_in_ps51(tmp_path, exit_code):
    value = result(run("$script:targetRoot=" + q(tmp_path) + ";$script:uv=" + q(PY) + ";$script:fixtureExit=" + str(exit_code) + "\n" + r'''
      function Get-FrozenSyncArguments { @('-I','-B','-c',("import sys; print('benign native stderr',file=sys.stderr); sys.exit("+$script:fixtureExit+")")) }
      $failed=$false;try{Invoke-FrozenRuntimeBuild}catch{$failed=$true}
    ''' + emit("failed=$failed;preference=[string]$ErrorActionPreference;log_contains_stderr=((Get-Content -LiteralPath (Join-Path $script:targetRoot 'frozen-build.log') -Raw) -match 'benign native stderr')")))
    assert value == {'failed': exit_code != 0, 'preference': 'Stop', 'log_contains_stderr': True}


def test_runtime_tree_hardlink_is_refused_before_file_acl_mutation(tmp_path):
    outside = tmp_path / 'outside.txt'
    outside.write_bytes(b'preserved')
    root = tmp_path / 'new'
    root.mkdir()
    os.link(outside, root / 'alias.txt')
    value = result(run("$script:targetRoot=" + q(root) + ";$helper=" + q(COPY_HELPER) + ";$treeSource=" + q(TREE_HELPER) + "\n" + r'''
      $tokens=$null;$errors=$null;$a=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$tokens,[ref]$errors)
      $f=$a.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Initialize-FileIdentity'},$true)
      . ([scriptblock]::Create($f.Extent.Text));Initialize-FileIdentity
      function Assert-ProtectedPath {param($Path)};function New-CodeAcl {param($Directory)$null}
      $treeAst=[Management.Automation.Language.Parser]::ParseFile($treeSource,[ref]$tokens,[ref]$errors)
      $treeFunction=$treeAst.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Assert-CodeTreeOnce'},$true)
      . ([scriptblock]::Create($treeFunction.Extent.Text))
      function Get-Acl {param($LiteralPath)
        $acl=[Security.AccessControl.DirectorySecurity]::new();$acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-5-18'),'FullControl','Allow'));$acl}
      $script:aclsChanged=0;function Set-Acl {param($LiteralPath,$AclObject)$script:aclsChanged++}
      $refused=$false;try{Protect-NewRuntimeTree $script:targetRoot}catch{$refused=$true}
    ''' + emit('refused=$refused;acls_changed=$script:aclsChanged')))
    assert value == {'refused': True, 'acls_changed': 0}
    assert outside.read_bytes() == b'preserved'


@pytest.mark.parametrize('mutate', [False, True])
def test_post_build_source_rebinding_rejects_installed_drift(tmp_path, mutate):
    source = tmp_path / 'source.py'
    original = b'approved source\n'
    source.write_bytes(b'mutated source!\n' if mutate else original)
    value = result(run(HELPERS + "$file=" + q(source) + ";$expected='" + sha256_bytes(original) + "';$length=" + str(len(original)) + "\n"
                       + "$refused=$false;try{Assert-PostBuildFrozenFiles @([pscustomobject]@{destination=$file;sha256=$expected;length=$length})}catch{$refused=$true}\n"
                       + emit('refused=$refused')))
    assert value['refused'] == mutate


def test_held_text_reader_disposal_retains_file_handle(tmp_path):
    control = tmp_path / 'control.json'
    control.write_bytes(b'{"safe":true}')
    value = result(run("$path=" + q(control) + "\n" + r'''
      $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
      try{$first=Read-HeldText $stream;$second=Read-HeldText $stream
        $refused=$false;try{$w=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::Read);$w.Dispose()}catch{$refused=$true}
        $out=[ordered]@{repeat=($first -ceq $second);write_denied=$refused;readable=$stream.CanRead}
      }finally{$stream.Dispose()}
      'RESULT:'+($out|ConvertTo-Json -Compress)
    '''))
    assert value == {'repeat': True, 'write_denied': True, 'readable': True}


@pytest.mark.parametrize('case', ['valid', 'base', 'version', 'system_site', 'extra', 'duplicate', 'legacy'])
def test_exact_actual_uv_venv_format_and_policy_against_r4(case):
    value = result(run("$case='" + case + "'\nSet-InstallerConstants\n" + r'''
      $text=Get-Content -LiteralPath 'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\pyvenv.cfg' -Raw
      switch($case){
        'base'{$text=$text.Replace('Python312','WrongBase')}
        'version'{$text=$text.Replace('3.12.13','3.12.12')}
        'system_site'{$text=$text.Replace('false','true')}
        'extra'{$text+="`nexecutable = C:\unexpected\python.exe"}
        'duplicate'{$text+="`nimplementation = CPython"}
        'legacy'{$text=$text.Replace('version_info','version')}
      }
      $refused=$false;try{Assert-UvVenvText $text}catch{$refused=$true}
    ''' + emit('refused=$refused')))
    assert value['refused'] == (case != 'valid')


def test_reports_are_create_new_and_keep_arrays_and_maps(tmp_path):
    report = tmp_path / 'install-after.json'
    value = result(run(BOUNDARY + "$path=" + q(report) + "\n" + r'''
      $value=[ordered]@{reviewed_repairs=[string[]]@('src/cochem_pipeline/__main__.py');holds=[object[]]@();reviewed_repairs_sha256=[ordered]@{'src/cochem_pipeline/__main__.py'=('a'*64)};empty_map=[ordered]@{};tasks_changed=0;flag=$false}
      Write-NewRuntimeReport $path $value
      $second=$false;try{Write-NewRuntimeReport $path ([ordered]@{replaced=$true})}catch{$second=$true}
    ''' + emit('second_refused=$second')))
    assert value['second_refused'] is True
    written = json.loads(report.read_text(encoding='utf-8'))
    assert written == {'reviewed_repairs': ['src/cochem_pipeline/__main__.py'], 'holds': [],
                       'reviewed_repairs_sha256': {'src/cochem_pipeline/__main__.py': 'a' * 64}, 'empty_map': {},
                       'tasks_changed': 0, 'flag': False}


@pytest.mark.parametrize('case,expected', [('production', True), ('placeholders', False), ('one_placeholder', False), ('filled', True),
                                           ('missing_key', False), ('extra_key', False), ('uppercase_hex', False), ('case_alias_key', False),
                                           ('not_a_map', False)])
def test_repair_pin_table_must_be_complete_before_any_run(world, case, expected):
    body = 'Set-InstallerConstants\n'
    if case == 'placeholders':
        body += pins_literal({relative: PLACEHOLDER for relative in REPAIRS})
    elif case == 'one_placeholder':
        body += pins_literal(dict(world.pins, **{'src/cochem_pipeline/store.py': PLACEHOLDER}))
    elif case != 'production':
        body += pins_literal(world.pins)
    body += "$case='" + case + "'\n" + r'''
      switch($case){
        'missing_key'{$script:reviewedRepairPins.Remove('src/cochem_pipeline/store.py')}
        'extra_key'{$script:reviewedRepairPins['src/cochem_pipeline/extra.py']=('a'*64)}
        'uppercase_hex'{$script:reviewedRepairPins['src/cochem_pipeline/store.py']=('A'*64)}
        'case_alias_key'{$v=$script:reviewedRepairPins['src/cochem_pipeline/store.py'];$script:reviewedRepairPins.Remove('src/cochem_pipeline/store.py');$script:reviewedRepairPins['SRC/cochem_pipeline/store.py']=$v}
        'not_a_map'{$script:reviewedRepairPins=@($script:reviewedRepairPins.Values)}
      }
    ''' + emit('filled=(Test-ReviewedRepairPinsFilled $script:reviewedRepairPins)')
    assert result(run(body))['filled'] is expected


@pytest.mark.parametrize('apply,admin,name,refused', [(False, False, 'AETHERDESK\\ansac', False), (True, False, 'AETHERDESK\\ansac', True),
                                                      (True, True, 'AETHERDESK\\other', True), (True, True, 'AETHERDESK\\ansac', False),
                                                      (False, True, 'NT AUTHORITY\\SYSTEM', False)])
def test_apply_requires_the_elevated_owner(apply, admin, name, refused):
    value = result(run("$refused=$false;try{Assert-ApplyAuthority $" + str(apply).lower() + " $" + str(admin).lower() + " " + q(name)
                       + "}catch{$refused=$true}\n" + emit('refused=$refused')))
    assert value['refused'] is refused


@pytest.mark.parametrize('edition,is64,computer,refused', [('Desktop', True, 'AETHERDESK', False), ('Core', True, 'AETHERDESK', True),
                                                           ('Desktop', False, 'AETHERDESK', True), ('Desktop', True, 'OTHERHOST', True)])
def test_host_must_be_64_bit_windows_powershell_on_aetherdesk(edition, is64, computer, refused):
    value = result(run("$refused=$false;try{Assert-InstallerHost '" + edition + "' $" + str(is64).lower() + " '" + computer
                       + "'}catch{$refused=$true}\n" + emit('refused=$refused')))
    assert value['refused'] is refused


@pytest.mark.parametrize('case', ['valid', 'wrong_pin', 'missing_function'])
def test_reviewed_helpers_are_imported_only_at_their_pins(case):
    pin = 'b' * 64 if case == 'wrong_pin' else COPY_HELPER_SHA256
    names = "@('Open-VerifiedFile','No-SuchFunction')" if case == 'missing_function' else "@('Open-VerifiedFile','Read-Inventory')"
    value = result(run("$refused=$false;$message='';$count=0;try{$count=@(Import-ReviewedFunctions " + q(COPY_HELPER) + " '" + pin + "' " + names
                       + ").Count}catch{$refused=$true;$message=$_.Exception.Message}\n" + emit('refused=$refused;message=$message;count=$count')))
    assert value['refused'] == (case != 'valid')
    if case == 'valid':
        assert value['count'] == 2
    if case == 'wrong_pin':
        assert value['message'] == 'Reviewed function source changed.'


@pytest.mark.parametrize('case', ['none', 'sibling', 'target_only', 'non_matching'])
def test_any_other_r5_root_is_reported(tmp_path, case):
    base = tmp_path / 'CoChem'
    base.mkdir()
    target = base / 'Pipeline4.2.7-windows-20261011-r5'
    (base / 'Pipeline4.2.7-windows-20261009-r4').mkdir()
    if case == 'sibling':
        (base / 'Pipeline4.2.7-windows-20261012-r5').mkdir()
    if case == 'target_only':
        target.mkdir()
    if case == 'non_matching':
        for name in ('Pipeline4.2.7-windows-20261011-r5-old', 'pipeline4.2.7-windows-20261011-r5x', 'Pipeline4.2.7-windows-2026101-r5'):
            (base / name).mkdir()
    value = result(run("$script:base=" + q(base) + ";$script:targetRoot=" + q(target) + "\n"
                       + emit('siblings=[object[]]@(Get-R5SiblingRoots)')))
    assert value['siblings'] == ([str(base / 'Pipeline4.2.7-windows-20261012-r5')] if case == 'sibling' else [])


# ------------------------------------------------------------------------------------- plan, end to end

PLAN_CASES = ['no_manifest', 'valid', 'valid_admin', 'placeholders', 'wrong_manifest_sha', 'existing_target', 'sibling_root',
              'task_references', 'tasks_denied', 'apply_with_holds', 'repair_reverted', 'pin_mismatch', 'mixed_eol',
              'lf_convention_changed', 'manifest_targets_r4']
PLAN_REFUSED = {'placeholders': 'PIN-AFTER-COMMIT', 'wrong_manifest_sha': 'digest', 'apply_with_holds': 'Awaiting',
                'repair_reverted': 'Exactly the 13 reviewed r5 repairs', 'pin_mismatch': 'differs from its reviewed pin',
                'mixed_eol': 'line endings', 'lf_convention_changed': 'line endings', 'manifest_targets_r4': 'tied to the preserved r4 installation'}
PLAN_HOLDS = {'no_manifest': ['Awaiting'], 'valid': [], 'valid_admin': [],
              'existing_target': ['already exists'], 'sibling_root': ['Another r5 runtime root exists'],
              'task_references': ['references the fresh r5 root'], 'tasks_denied': ['unreadable without elevation']}


@pytest.mark.parametrize('case', PLAN_CASES)
def test_plan_mode_end_to_end_is_read_only(world, tmp_path, case):
    """The real Invoke-InstallerMain with the real reviewed helpers, real r4 receipts and a fixture freeze."""
    base = tmp_path / 'CoChem'
    base.mkdir()
    target = base / 'Pipeline4.2.7-windows-20261011-r5'
    stage, overrides = world.stage, dict(world.overrides)
    if case in ('repair_reverted', 'mixed_eol', 'lf_convention_changed'):
        stage = tmp_path / 'stage'
        shutil.copytree(world.stage, stage)
        if case == 'repair_reverted':
            relative = 'src/cochem_pipeline/store.py'
            data = (R4_STAGE / relative).read_bytes()
            del overrides[relative]
        elif case == 'mixed_eol':
            relative = 'src/cochem_pipeline/store.py'
            data = overrides[relative] + b'# one bare LF line\n'
            overrides[relative] = data
        else:
            relative = 'src/cochem_pipeline/agy_protocol.py'
            data = (R4_STAGE / relative).read_bytes().replace(b'\n', b'\r\n') + b'# converted to CRLF\r\n'
            overrides[relative] = data
        (stage / relative).write_bytes(data)
    manifest, manifest_sha = write_manifest(tmp_path, stage, R4 if case == 'manifest_targets_r4' else target, overrides)
    if case == 'existing_target':
        target.mkdir()
        (target / 'preserve.txt').write_bytes(b'untouched')
    if case == 'sibling_root':
        (base / 'Pipeline4.2.7-windows-20261012-r5').mkdir()
    pins = {relative: sha256_bytes(data) for relative, data in overrides.items()}
    if case == 'pin_mismatch':
        pins['src/cochem_pipeline/store.py'] = 'f' * 64
    if case == 'repair_reverted':
        pins['src/cochem_pipeline/store.py'] = sha256_bytes((R4_STAGE / 'src/cochem_pipeline/store.py').read_bytes())
    if case == 'placeholders':
        pins = {relative: PLACEHOLDER for relative in REPAIRS}
    use_manifest = case not in ('no_manifest', 'apply_with_holds')
    sha = 'a' * 64 if case == 'wrong_manifest_sha' else manifest_sha
    # The production pin table is used as is wherever the case does not need different pins.
    body = (constants(world, base, target, stage) + ('' if pins == PINS else pins_literal(pins)) + HELPERS + SPIES + FOLDER
            + ("$script:taskMode='references'\n" if case == 'task_references' else '')
            + ("$script:taskMode='denied'\n" if case == 'tasks_denied' else '')
            + '$manifest=' + (q(manifest) if use_manifest else "''") + ";$manifestSha='" + (sha if use_manifest else '') + "'\n"
            + '$apply=$' + str(case == 'apply_with_holds').lower() + ';$admin=$' + str(case in ('valid_admin', 'apply_with_holds')).lower() + '\n'
            + r'''$folder=New-FixtureFolder
      $refused=$false;$message='';$output=$null
      try{$output=Invoke-InstallerMain $manifest $manifestSha $apply $admin $folder}catch{$refused=$true;$message=$_.Exception.Message}
    ''' + emit("refused=$refused;message=$message;plan=$(if($null -ne $output){[string]($output -join [Environment]::NewLine)}else{$null});"
               "mutations=[object[]]$script:mutations.ToArray();target_exists=(Test-Path -LiteralPath $script:targetRoot);task_calls=[object[]]$script:getTaskCalls.ToArray()"))
    before = snapshot(tmp_path, world.top)
    value = result(run(body))
    assert snapshot(tmp_path, world.top) == before, 'plan mode must not create, change or delete anything'
    assert value['mutations'] == []
    assert value['target_exists'] == (case == 'existing_target')
    assert all(name in ('CoChem-4.2.7-Warden', 'CoChem-4.2.7-Supervisor', 'CoChem-4.2.2-Warden', 'CoChem-4.2.3-Supervisor',
                        'CoChem-4.2.7-WorkerDenial-slot1') for name in value['task_calls'])
    if case in PLAN_REFUSED:
        assert value['refused'], case
        assert PLAN_REFUSED[case] in value['message'], value['message']
        return
    assert not value['refused'], value['message']
    plan = json.loads(value['plan'])
    holds = plan['holds']
    assert len(holds) == len(PLAN_HOLDS[case]) and all(any(fragment in hold for hold in holds) for fragment in PLAN_HOLDS[case]), holds
    r4_before = json.loads((R4 / 'install-before.json').read_text(encoding='utf-8-sig'))
    for key, expected in r4_before.items():
        assert key in plan, key
        if expected is not None and key != 'source_manifest_sha256':
            assert type(plan[key]) is type(expected), key
    assert plan['mode'] == 'READ_ONLY_PLAN' and plan['target_root'] == str(target) and plan['previous_runtime_root'] == str(R4)
    assert plan['tasks_changed'] == 0 and plan['accounts_provisioned'] == 0 and plan['pipeline_started'] is False
    assert plan['activation_ready'] is False and plan['installed_repairs_verified'] is False
    assert plan['reviewed_repair'] == TELEMETRY_REPAIR and plan['reviewed_repair_sha256'] == TELEMETRY_REPAIR_SHA256
    assert plan['preserved_denial_task_terminal_check_deferred'] is (case != 'valid_admin')
    assert len(plan['managed_daemon_tasks']) == 4
    if case == 'no_manifest':
        assert plan['reviewed_repairs'] == [] and plan['reviewed_repairs_sha256'] == {} and plan['verified_unchanged'] is None
        assert plan['source_files'] == 0
        return
    assert plan['source_manifest_sha256'] == manifest_sha and plan['source_files'] == 166
    assert plan['reviewed_repairs'] == world.order
    assert plan['reviewed_repairs_sha256'] == {relative: world.pins[relative] for relative in world.order}
    assert list(plan['reviewed_repairs_sha256']) == world.order
    assert plan['repair_line_endings'] == {relative: ('LF' if relative in LF_REPAIRS else 'CRLF') for relative in world.order}
    assert plan['verified_unchanged'] == 153 and plan['source_commit'] == SOURCE_COMMIT
    assert plan['runtime_python'] == str(target / '.venv' / 'Scripts' / 'python.exe')
    if case == 'valid':
        assert all(task['state'] == 'ENABLED=True;STATE=4;INSTANCES=1' and task['references_new_root'] is False
                   for task in plan['managed_daemon_tasks']), 'a running r4 Warden is allowed and untouched'


# ---------------------------------------------------------------------------------- apply, with stubs

APPLY_CASES = {
    # case: (failed, held stage or None, builds, validations)
    'success': (False, None, 1, 1),
    'existing_root': (True, None, 0, 0),
    'sibling_root': (True, None, 0, 0),
    'failed_denial_task': (True, None, 0, 0),
    'deferred_task': (True, None, 0, 0),
    'references_new_root': (True, None, 0, 0),
    'placeholder_pins': (True, None, 0, 0),
    'pin_mismatch': (True, None, 0, 0),
    'build_failure': (True, 'build', 1, 0),
    'source_drift': (True, 'post-build-rebind', 1, 0),
    'installed_repair_mismatch': (True, 'installed-repairs', 1, 0),
    'interpreter_mismatch': (True, 'interpreter', 1, 0),
    'validation_failure': (True, 'validation', 1, 1),
    'task_appears_after_build': (True, 'task-recheck', 1, 1),
    'install_after_exists': (True, 'install-after', 1, 1),
}

APPLY_BODY = r'''$script:setupMutexName='Local\CoChem-R5-Inert-'+[Guid]::NewGuid().ToString('N')
$script:python=TOOLCHAIN_PYTHON
$script:pins=@([pscustomobject]@{source=PIN_FILE;sha256=PIN_SHA})
$script:builds=0;$script:validations=0
$script:verificationJson=VERIFICATION_JSON
function Invoke-FrozenRuntimeBuild {
  $script:builds++
  if($case -eq 'build_failure'){throw 'fixture uv synchronization failed'}
  $venv=Join-Path $script:targetRoot '.venv'
  $null=[IO.Directory]::CreateDirectory((Join-Path $venv 'Scripts'))
  [IO.File]::Copy((Join-Path $r4Venv 'pyvenv.cfg'),(Join-Path $venv 'pyvenv.cfg'))
  [IO.File]::Copy((Join-Path $r4Venv 'Scripts\python.exe'),(Join-Path $venv 'Scripts\python.exe'))
  foreach($repair in $repairs){
    $destination=Join-Path $venv ('Lib\site-packages\'+$repair.relative.Substring(4).Replace('/','\'))
    $null=[IO.Directory]::CreateDirectory((Split-Path -Parent $destination))
    [IO.File]::Copy((Join-Path $fixtureStage $repair.relative),$destination)}
  switch($case){
    'source_drift'{[IO.File]::AppendAllText((Join-Path $script:sourceRoot 'README.md'),'changed by fixture build')}
    'installed_repair_mismatch'{[IO.File]::AppendAllText((Join-Path $venv 'Lib\site-packages\cochem_pipeline\store.py'),'# drift')}
    'interpreter_mismatch'{[IO.File]::AppendAllText((Join-Path $venv 'pyvenv.cfg'),'extra = 1')}
    'task_appears_after_build'{$script:taskMode='references'}
    'install_after_exists'{[IO.File]::WriteAllText((Join-Path $script:targetRoot 'install-after.json'),'{}')}
  }
}
function Invoke-NewRuntimeValidation {param($Root)
  $script:validations++
  if($case -eq 'validation_failure'){throw 'New r5 revision/config validation failed, exit 1. AssertionError: r5 repair missing: store.reconcile_chapter_wbs'}
  $script:verificationJson|ConvertFrom-Json}
$inventory=Get-Content -LiteralPath $manifest -Raw|ConvertFrom-Json
$prior=Get-Content -LiteralPath (Join-Path $script:oldRoot 'source-manifest.json') -Raw|ConvertFrom-Json
$repairs=@(Assert-ReviewedR5Delta $inventory $prior $fixturePins)
$names=@($repairs|ForEach-Object {$_.relative})+@('README.md')
$files=@(Get-RuntimeFiles $inventory|Where-Object {$_.relative -cin $names})
$controls=@(New-ControlCopyRecords $manifest $manifestSha)
$plan=New-InstallPlan $manifestSha 166 $repairs $true @() @() $inventory
$folder=New-FixtureFolder
switch($case){
  'failed_denial_task'{$script:denialMode='invalid'}
  'deferred_task'{$script:taskMode='denied'}
  'references_new_root'{$script:taskMode='references'}
}
$failed=$false;$message='';try{$null=Invoke-NewRuntimeInstallation $files $controls $folder $plan $repairs}catch{$failed=$true;$message=$_.Exception.Message}
function Read-Optional {param($Path)if(Test-Path -LiteralPath $Path){[IO.File]::ReadAllText($Path)}else{$null}}
$script:extraResult=$null
'''

RETARGET_BODY = r'''if(-not $failed){
  try{
    $rt=$null;$re=$null;$rast=[Management.Automation.Language.Parser]::ParseFile(RETARGET_PATH,[ref]$rt,[ref]$re)
    if($re.Count){throw 'retarget-warden-r5.ps1 does not parse'}
    # Every retarget function as it is on disk now (the installation above is finished, so overriding a shared helper
    # name is harmless); only the two protected-file readers are replaced below by hash-checking fixture readers.
    $retargetFunctions=@($rast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$false))
    if(-not @($retargetFunctions|Where-Object {$_.Name -eq 'Assert-R5InstalledBindings'}).Count){throw 'retarget function missing: Assert-R5InstalledBindings'}
    foreach($retargetFunction in $retargetFunctions){. ([scriptblock]::Create($retargetFunction.Extent.Text))}
    function Read-R3Control {param([string]$Path,[string]$Expected,[long]$Limit=1048576)
      $bytes=[IO.File]::ReadAllBytes($Path);if($bytes.Length -gt $Limit){throw ('fixture control exceeds its bound: '+$Path)}
      $sha=[Security.Cryptography.SHA256]::Create();try{$hex=[BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
      if($Expected -and $hex -cne $Expected){throw ('fixture control digest differs: '+$Path)}
      [pscustomobject]@{Path=$Path;Sha256=$hex;Bytes=$bytes}}
    function Read-R3Text {param($Control)[Text.UTF8Encoding]::new($false,$true).GetString($Control.Bytes)}
    $script:r4Root=R4_ROOT;$script:r4InstallPin='R4_INSTALL';$script:r4ManifestPin='R4_MANIFEST';$script:configPin='CONFIG_PIN'
    $script:r4RevisionPin='R4_REVISION';$script:r3RevisionPin='R3_REVISION'
    $script:basePythonRoot=BASE_ROOT;$script:basePython=BASE_PYTHON;$script:probePythonPin='PYTHON_PIN'
    # The reviewed-freeze pins (audit C-F4): only the manifest pin is redirected to this fixture's manifest; the repair digests,
    # venv bytes and unchanged count are the production values, which the test cross-checks against Set-RetargetConstants.
    $script:r5SourceManifestPin='FIXTURE_MANIFEST_SHA';$script:r5RepairPins=FIXTURE_REPAIR_PINS
    $script:r5PyvenvPin='FIXTURE_PYVENV_SHA';$script:r5VenvPythonPin='FIXTURE_VENV_LAUNCHER_SHA';$script:r5VerifiedUnchanged=153
    $bound=Assert-R5InstalledBindings $script:targetRoot
    $script:extraResult=[ordered]@{ok=$true;root=$bound.root;python=$bound.python;source_root=$bound.source_root;install_after_path=$bound.install_after_path;
      install_after_sha256=$bound.install_after_sha256;source_manifest_sha256=$bound.source_manifest_sha256;revision_sha256=$bound.revision_sha256;
      reviewed_repairs=[object[]]@($bound.reviewed_repairs);venv_python_sha256=$bound.venv_python_sha256}
  }catch{$script:extraResult=[ordered]@{ok=$false;error=$_.Exception.Message}}
}
'''


def run_apply(world, tmp_path, case, retarget=False):
    base = tmp_path / 'CoChem'
    base.mkdir()
    target = base / 'Pipeline4.2.7-windows-20261011-r5'
    manifest, manifest_sha = write_manifest(tmp_path, world.stage, target, world.overrides)
    if case == 'existing_root':
        target.mkdir()
        (target / 'preserve.txt').write_bytes(b'untouched')
    if case == 'sibling_root':
        (base / 'Pipeline4.2.7-windows-20261012-r5').mkdir()
    pin_file = tmp_path / 'pinned-control.bin'
    pin_file.write_bytes(b'pinned control\n')
    pins = None  # the production table
    if case == 'placeholder_pins':
        pins = {relative: PLACEHOLDER for relative in REPAIRS}
    if case == 'pin_mismatch':
        pins = dict(world.pins, **{'src/cochem_pipeline/worker.py': 'f' * 64})
    body = (constants(world, base, target) + pins_literal(pins) + HELPERS + BOUNDARY + FOLDER
            + "$case='" + case + "';$fixtureStage=" + q(world.stage) + ';$r4Venv=' + q(R4 / '.venv') + ';$manifest=' + q(manifest)
            + ";$manifestSha='" + manifest_sha + "'\n"
            + '$fixturePins=[ordered]@{' + ';'.join(q(k) + '=' + q(v) for k, v in world.pins.items()) + '}\n'
            + APPLY_BODY.replace('TOOLCHAIN_PYTHON', q(TOOLCHAIN_PYTHON)).replace('PIN_FILE', q(pin_file))
            .replace('PIN_SHA', q(sha256_file(pin_file))).replace('VERIFICATION_JSON', q(json.dumps(VERIFICATION))))
    if retarget:
        body += (RETARGET_BODY.replace('RETARGET_PATH', q(RETARGET)).replace('R4_ROOT', q(R4)).replace('R4_INSTALL', R4_INSTALL_SHA256)
                 .replace('R4_MANIFEST', R4_MANIFEST_SHA256).replace('CONFIG_PIN', CONFIG_SHA256).replace('R4_REVISION', R4_REVISION_SHA256)
                 .replace('R3_REVISION', R3_REVISION_SHA256).replace('BASE_ROOT', q(TOOLCHAIN_PYTHON.parent))
                 .replace('BASE_PYTHON', q(TOOLCHAIN_PYTHON)).replace('PYTHON_PIN', PYTHON_SHA256)
                 .replace('FIXTURE_MANIFEST_SHA', manifest_sha)
                 .replace('FIXTURE_REPAIR_PINS', '[ordered]@{' + ';'.join(q(k) + '=' + q(v) for k, v in world.pins.items()) + '}')
                 .replace('FIXTURE_PYVENV_SHA', PYVENV_SHA256).replace('FIXTURE_VENV_LAUNCHER_SHA', VENV_PYTHON_SHA256))
    body += emit("failed=$failed;message=$message;builds=$script:builds;validations=$script:validations;root_exists=(Test-Path -LiteralPath $script:targetRoot);"
                 "after=(Read-Optional (Join-Path $script:targetRoot 'install-after.json'));before=(Read-Optional (Join-Path $script:targetRoot 'install-before.json'));"
                 "held=(Read-Optional (Join-Path $script:targetRoot 'install-held.json'));"
                 "copied=@(if(Test-Path -LiteralPath (Join-Path $script:targetRoot 'source')){Get-ChildItem -LiteralPath (Join-Path $script:targetRoot 'source') -Recurse -File}).Count;"
                 "acls=$script:aclsSet;task_calls=[object[]]$script:getTaskCalls.ToArray();extra=$script:extraResult")
    value = result(run(body))
    return value, SimpleNamespace(base=base, target=target, manifest=manifest, manifest_sha=manifest_sha)


@pytest.mark.parametrize('case', list(APPLY_CASES))
def test_apply_function_creates_once_and_holds_on_failure(world, tmp_path, case):
    """The real Invoke-NewRuntimeInstallation with real CreateNew copies/reports; uv, ACL custody and validation stubbed."""
    failed, held_stage, builds, validations = APPLY_CASES[case]
    value, paths = run_apply(world, tmp_path, case)
    assert value['failed'] == failed, value['message']
    assert value['builds'] == builds and value['validations'] == validations
    created = held_stage is not None or case == 'success'
    assert value['root_exists'] == (created or case == 'existing_root')
    if case == 'existing_root':
        assert (paths.target / 'preserve.txt').read_bytes() == b'untouched'
        assert value['held'] is None and value['after'] is None and value['copied'] == 0
    if not created:
        assert value['held'] is None and value['before'] is None
        return
    assert value['copied'] == 14
    assert json.loads(value['before'])['mode'] == 'READ_ONLY_PLAN'
    if case == 'success':
        assert value['held'] is None and json.loads(value['after'])['mode'] == 'FRESH_STOPPED_RUNTIME_READY'
        assert value['acls'] > 20, 'the real Protect-NewRuntimeTree walked the fresh tree'
        # Task access is read-only and limited to the managed daemons and the preserved denial task.
        assert set(value['task_calls']) == {'CoChem-4.2.7-Warden', 'CoChem-4.2.7-Supervisor', 'CoChem-4.2.2-Warden',
                                            'CoChem-4.2.3-Supervisor', 'CoChem-4.2.7-WorkerDenial-slot1'}
        return
    held = json.loads(value['held'])
    assert held['schema'] == 'cochem-stopped-runtime-update-held/1' and held['mode'] == 'HELD_FRESH_ROOT_PRESERVED'
    assert held['failed_stage'] == held_stage and held['target_root'] == str(paths.target)
    assert held['tasks_changed'] == 0 and held['pipeline_started'] is False and held['reviewed_repairs'] == world.order
    if case == 'install_after_exists':
        assert value['after'] == '{}', 'install-after.json is CreateNew; an existing file is preserved'
    else:
        assert value['after'] is None
    if case == 'validation_failure':
        assert 'r5 repair missing' in held['error']


def _type_name(value):
    return 'int' if isinstance(value, int) and not isinstance(value, bool) else type(value).__name__


def test_install_after_is_a_superset_of_the_r4_receipt_with_r5_fields(world, tmp_path):
    value, paths = run_apply(world, tmp_path, 'success')
    assert not value['failed'], value['message']
    after = json.loads(value['after'])
    r4 = json.loads((R4 / 'install-after.json').read_text(encoding='utf-8-sig'))
    # Every r4 key keeps its name and JSON type, recursively for the nested objects.
    for key, expected in r4.items():
        assert key in after, key
        if expected is None:
            assert after[key] is None, key
        else:
            assert _type_name(after[key]) == _type_name(expected), key
    for section in ('verification', 'runtime_bindings'):
        for key, expected in r4[section].items():
            assert key in after[section] and _type_name(after[section][key]) == _type_name(expected), section + '.' + key
    for key, expected in r4['verification']['revision'].items():
        assert key in after['verification']['revision'] and _type_name(after['verification']['revision'][key]) == _type_name(expected), key
    assert list(after['runtime_bindings']) == list(r4['runtime_bindings'])
    assert [list(task) for task in after['managed_daemon_tasks']] == [['name', 'state', 'references_new_root']] * 4
    assert list(after)[:len(r4) - 3] == list(r4)[:len(r4) - 3], 'r4 plan keys keep their order'
    # The RUNTIME-BUILD / retarget-warden-r5 contract.
    assert after['schema'] == 'cochem-stopped-runtime-update/1' and after['mode'] == 'FRESH_STOPPED_RUNTIME_READY'
    assert after['target_root'] == str(paths.target) and after['previous_runtime_root'] == str(R4)
    assert after['previous_install_receipt_sha256'] == R4_INSTALL_SHA256 and after['previous_source_manifest_sha256'] == R4_MANIFEST_SHA256
    assert after['source_manifest_sha256'] == paths.manifest_sha != R4_MANIFEST_SHA256
    assert after['configuration_sha256'] == CONFIG_SHA256 and after['configuration_unchanged'] is True
    assert after['source_files'] == 166 and after['holds'] == [] and after['tasks_changed'] == 0
    for flag in ('pipeline_started', 'credentials_modified', 'databases_modified', 'ram_modified', 'activation_ready'):
        assert after[flag] is False, flag
    verification = after['verification']
    assert verification['configuration_parsed'] is True and verification['no_system_or_model_execution'] is True
    assert verification['ram_workspace_root'] == 'R:\\CoChem427-windows-20261007' and verification['telemetry_repair_installed'] is True
    revision = verification['revision']
    assert revision['schema'] == 'cochem-installed-revision/1' and revision['verified'] is True and revision['read_only'] is True
    assert revision['acceptance_files'] == 0 and isinstance(revision['files'], int) and revision['files'] >= 1
    assert revision['source_sha256'] not in (R4_REVISION_SHA256, R3_REVISION_SHA256)
    assert after['runtime_bindings'] == {'pyvenv_sha256': PYVENV_SHA256, 'venv_python_sha256': VENV_PYTHON_SHA256,
                                         'base_python_sha256': PYTHON_SHA256, 'base_root': str(TOOLCHAIN_PYTHON.parent)}
    assert isinstance(after['reviewed_repairs'], list) and after['reviewed_repairs'] == world.order
    assert sorted(after['reviewed_repairs']) == REPAIRS and 'src/cochem_pipeline/__main__.py' in after['reviewed_repairs']
    assert after['reviewed_repairs_sha256'] == {relative: world.pins[relative] for relative in world.order}
    # r4's singular pair stays, typed as in r4: the inherited, still installed telemetry repair.
    assert after['reviewed_repair'] == TELEMETRY_REPAIR and after['reviewed_repair_sha256'] == TELEMETRY_REPAIR_SHA256
    # r5 additions.
    added = set(after) - set(r4)
    assert added == {'revision_label', 'runtime_python', 'source_stage_root', 'source_commit', 'previous_revision_sha256',
                     'reviewed_repairs', 'reviewed_repairs_sha256', 'repair_line_endings', 'verified_unchanged', 'installed_repairs_verified'}
    assert after['verified_unchanged'] == 153 and after['installed_repairs_verified'] is True and after['revision_label'] == 'r5'
    assert after['runtime_python'] == str(paths.target / '.venv' / 'Scripts' / 'python.exe')
    assert after['source_stage_root'] == str(world.stage) and after['source_commit'] == SOURCE_COMMIT
    assert after['previous_revision_sha256'] == R4_REVISION_SHA256
    assert after['repair_line_endings'] == {relative: ('LF' if relative in LF_REPAIRS else 'CRLF') for relative in world.order}
    assert verification['r5_repairs_installed'] is True and verification['r5'] == VERIFICATION['r5']
    assert after['verified_entries'] == 15013 and after['preserved_denial_task_terminal_check_deferred'] is False
    assert all(task['references_new_root'] is False for task in after['managed_daemon_tasks'])
    # The copies are byte-exact and both reports are plain UTF-8 JSON without a byte order mark.
    for relative in world.order:
        assert (paths.target / 'source' / relative).read_bytes() == world.overrides[relative]
        assert (paths.target / '.venv' / 'Lib' / 'site-packages' / relative[4:]).read_bytes() == world.overrides[relative]
    assert sha256_file(paths.target / 'pipeline.json') == CONFIG_SHA256
    assert sha256_file(paths.target / 'windows-layout.json') == LAYOUT_SHA256
    assert sha256_file(paths.target / 'source-manifest.json') == paths.manifest_sha
    assert not (paths.target / 'install-after.json').read_bytes().startswith(b'\xef\xbb\xbf')
    before = json.loads(value['before'])
    r4_before = json.loads((R4 / 'install-before.json').read_text(encoding='utf-8-sig'))
    assert set(r4_before) <= set(before) and before['mode'] == 'READ_ONLY_PLAN'


def test_retarget_r5_binds_this_installers_receipt_by_content(world, tmp_path):
    """Run the real Assert-R5InstalledBindings (retarget-warden-r5.ps1) on a root this installer produced."""
    if not RETARGET.exists():
        pytest.skip('retarget-warden-r5.ps1 is not on disk yet')
    # The fixture injects the production reviewed-freeze pins (only the manifest pin is the fixture's own): they must be
    # exactly what Set-RetargetConstants pins, and its manifest pin must be the real freeze manifest on disk.
    text = RETARGET.read_text(encoding='ascii')
    assert "$script:r5SourceManifestPin='" + sha256_file(R5_MANIFEST) + "'" in text
    assert "$script:r5PyvenvPin='" + PYVENV_SHA256 + "'" in text and "$script:r5VenvPythonPin='" + VENV_PYTHON_SHA256 + "'" in text
    assert '$script:r5VerifiedUnchanged=153' in text
    for relative, digest in world.pins.items():
        assert "'" + relative + "'='" + digest + "'" in text, relative
    value, paths = run_apply(world, tmp_path, 'success', retarget=True)
    assert not value['failed'], value['message']
    bound = value['extra']
    assert bound['ok'], bound.get('error')
    assert bound['root'] == str(paths.target) and bound['python'] == str(paths.target / '.venv' / 'Scripts' / 'python.exe')
    assert bound['source_root'] == str(paths.target / '.venv' / 'Lib')
    assert bound['install_after_sha256'] == sha256_file(paths.target / 'install-after.json')
    assert bound['source_manifest_sha256'] == paths.manifest_sha and bound['reviewed_repairs'] == world.order
    assert bound['venv_python_sha256'] == VENV_PYTHON_SHA256


# ------------------------------------------------------------------------------ real validation body

def runtime_fixture(tmp_path, source_src, replacements=None):
    """A temp r5-shaped runtime root: r4 venv launcher + pyvenv.cfg, packages in source and site-packages.

    Third-party dependencies resolve from the installed r4 site-packages through a .pth line that appends it
    after the fixture packages, so the fixture's cochem_* packages are the ones imported and inventoried.
    """
    root = tmp_path / 'runtime'
    site = root / '.venv' / 'Lib' / 'site-packages'
    site.mkdir(parents=True)
    (root / '.venv' / 'Scripts').mkdir(parents=True)
    for package in PACKAGES:
        shutil.copytree(Path(source_src) / package, root / 'source' / 'src' / package,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for relative, path in (replacements or {}).items():
        shutil.copyfile(path, root / 'source' / relative)
    for package in PACKAGES:
        shutil.copytree(root / 'source' / 'src' / package, site / package)
    for name in ('pyproject.toml', 'uv.lock'):
        shutil.copyfile(R4 / 'source' / name, root / 'source' / name)
    shutil.copyfile(R4 / 'pipeline.json', root / 'pipeline.json')
    shutil.copyfile(R4 / '.venv' / 'pyvenv.cfg', root / '.venv' / 'pyvenv.cfg')
    shutil.copyfile(R4 / '.venv' / 'Scripts' / 'python.exe', root / '.venv' / 'Scripts' / 'python.exe')
    dependencies = (R4 / '.venv' / 'Lib' / 'site-packages').as_posix()
    (site / 'r4-dependencies.pth').write_text("import site; site.addsitedir('" + dependencies + "')\n", encoding='ascii')
    return root


def run_validation(root):
    return result(run('Set-InstallerConstants\n' + HELPERS + '$root=' + q(root) + '\n' + r'''
      $failed=$false;$message='';$verification=$null;$bindings=$null
      try{$bindings=Assert-NewRuntimeInterpreter $root;$verification=Invoke-NewRuntimeValidation $root}catch{$failed=$true;$message=$_.Exception.Message}
    ''' + emit('failed=$failed;message=$message;verification=$verification;bindings=$bindings'), timeout=300))


def _shape(value):
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in value.items()}
    return _type_name(value)


def test_validation_accepts_the_committed_r5_tree(world, tmp_path):
    """Exact body, r5 interpreter layout, the tree the freeze stages: r4 frozen source + the 13 blobs of 8554c76."""
    value = run_validation(runtime_fixture(tmp_path, world.stage / 'src'))
    assert not value['failed'], value['message']
    verification = value['verification']
    assert _shape(verification) == _shape(VERIFICATION), 'the stubbed apply tests must use the real output shape'
    assert verification['r5'] == VERIFICATION['r5']
    assert verification['revision']['verified'] is True and verification['revision']['files'] >= 100
    assert verification['ram_workspace_root'] == 'R:\\CoChem427-windows-20261007'
    assert value['bindings'] == {'pyvenv_sha256': PYVENV_SHA256, 'venv_python_sha256': VENV_PYTHON_SHA256,
                                 'base_python_sha256': PYTHON_SHA256, 'base_root': str(TOOLCHAIN_PYTHON.parent)}


def test_validation_accepts_the_staged_r5_source(tmp_path):
    if not (R5_STAGE / 'src' / 'cochem_pipeline' / '__main__.py').exists():
        pytest.skip('the r5 source is not frozen yet (freeze-stopped-runtime-r5-source.py runs after the commit)')
    value = run_validation(runtime_fixture(tmp_path, R5_STAGE / 'src'))
    assert not value['failed'], value['message']
    assert value['verification']['r5'] == VERIFICATION['r5']


@pytest.mark.parametrize('case,marker', [
    ('r4_tree', 'r5 repair missing: agy_protocol.IDENTITY_POLICY'),
    ('r4_agy_protocol', 'r5 repair missing: agy_protocol.IDENTITY_POLICY'),
    ('r4_store', 'r5 repair missing: store.reconcile_chapter_wbs'),
    ('r4_coding', 'r5 repair missing: coding.read_workspace'),
    ('r4_main', 'r5 repair missing: daemon'),
])
def test_validation_refuses_an_unrepaired_runtime(world, tmp_path, case, marker):
    """Each r5 check is load-bearing: the r4 tree, and the committed r5 tree with one file reverted to r4, fail by name."""
    if case == 'r4_tree':
        root = runtime_fixture(tmp_path, R4 / 'source' / 'src')
    else:
        relative = {'r4_agy_protocol': 'src/cochem_pipeline/agy_protocol.py', 'r4_store': 'src/cochem_pipeline/store.py',
                    'r4_coding': 'src/cochem_pipeline/coding.py', 'r4_main': 'src/cochem_pipeline/__main__.py'}[case]
        root = runtime_fixture(tmp_path, world.stage / 'src', {relative: R4 / 'source' / relative})
    value = run_validation(root)
    assert value['failed']
    assert marker in value['message'], value['message']
    assert 'validation failed, exit 1' in value['message']
    assert value['bindings']['venv_python_sha256'] == VENV_PYTHON_SHA256, 'the interpreter was accepted; the source was refused'
