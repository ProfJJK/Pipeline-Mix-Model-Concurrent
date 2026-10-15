"""Inert process inventory fixtures, never host queries or child lifecycle."""
import hashlib
import json

import pytest

from pipeline_tests.test_operational_launch_428 import inert_ps


PYTHON=r'C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe'
OLD427=r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\Scripts\python.exe'
OLD428=r'C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r4\.venv\Scripts\python.exe'
BRIDGE=r'C:\Users\ansac\CoChem427\bridge.local.json'
CLIENT=r'C:\Users\ansac\CoChem427\pipeline-client-r3.json'


def inspect_rows(rows):
    return inert_ps(r"""
$script:OpOldRoot='C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r4'
$script:OpRoot='C:\Program Files\CoChem\Pipeline4.2.8-windows-20261015-r5'
$script:python='PYTHON';$script:checked=0
$script:rows='ROWS'|ConvertFrom-Json
function Assert-428PortFree {}
function Assert-ProtectedPath {param($p)$script:checked++}
function Get-CimInstance {param($class,$filter)if($filter){return $null};return $script:rows}
$state=@{status='fixture';phase='preconditions';rollback='NOT_REQUIRED';cutover_requested=$false;acceptance=$null}
$held=$false;$failure=$null
try{Assert-OpRecoveryQuiescent (Get-OpRecoveryExpected)}catch{$held=$true;$failure=Get-OpFailure $_ 'verify_original_recovery_evidence';$state.launcher_failure=$failure}
$public=New-OpResultRecord $state @{source_commit=('a'*40);request_sha256=('b'*64)} ('c'*64)
@{held=$held;checked=$script:checked;failure=$failure;public=$public}|ConvertTo-Json -Depth 12 -Compress
""".replace('PYTHON',PYTHON).replace('ROWS',json.dumps(rows).replace("'","''")))


def row(image, command, *, pid=987, name=None):
    return dict(ProcessId=pid,ParentProcessId=986,ExecutablePath=image,CommandLine=command,
                Name=name if name is not None else image.rsplit('\\',1)[-1])


@pytest.mark.parametrize('provider',['claude','codex'])
@pytest.mark.parametrize('quoted',[False,True])
def test_legacy_bridge_children_and_parents_are_exact_permitted_clients(provider,quoted):
    config=f'"{BRIDGE}"' if quoted else BRIDGE
    rows=[row(exe,f'"{exe}" -m cochem_mcp --provider {provider} --config {config}',pid=987+i)
          for i,exe in enumerate((PYTHON,OLD427))]
    result=inspect_rows(rows)
    assert not result['held'],result
    assert result['checked']==2


def test_mixed_modern_legacy_and_unrelated_source_inspection_inventory():
    rows=[row(PYTHON,f'"{OLD428}" -I -B -m cochem_pipeline mcp --client-config {CLIENT}'),
          row(OLD428,f'"{OLD428}" -I -B -m cochem_pipeline mcp --client-config "{CLIENT}"',pid=988),
          row(PYTHON,f'"{PYTHON}" -m cochem_mcp --provider codex --config {BRIDGE}',pid=989),
          row(r'C:\Program Files\PowerShell\7\pwsh.exe',
              'pwsh.exe -Command "Get-Content src/cochem_pipeline/worker.py"',pid=990),
          row(r'C:\Tools\rg.exe','rg.exe -n cochem_pipeline src',pid=991),
          row(r'C:\Windows\System32\cmd.exe','cmd.exe /c type src\\cochem_pipeline\\worker.py',pid=992)]
    result=inspect_rows(rows)
    assert not result['held'],result
    assert result['checked']==3


@pytest.mark.parametrize('image,command,reason',[
    (PYTHON,f'"{PYTHON}" -m cochem_mcp --provider gemini --config {BRIDGE}','PROTECTED_PYTHON'),
    (PYTHON,f'"{PYTHON}" -m cochem_mcp --provider codex --config C:\\foreign\\bridge.json','PROTECTED_PYTHON'),
    (PYTHON,f'"{PYTHON}" -m cochem_mcp --provider claude --config {BRIDGE} --extra','PROTECTED_PYTHON'),
    (PYTHON,f'"{PYTHON}" -c "print(\"-m cochem_mcp --provider codex --config {BRIDGE}\")"','PROTECTED_PYTHON'),
    (r'C:\foreign\python.exe',f'"{PYTHON}" -m cochem_mcp --provider codex --config {BRIDGE}','PIPELINE_PYTHON'),
    (PYTHON,f'"{PYTHON}" -I -B -m cochem_pipeline daemon --config C:\\private\\secret.json','PROTECTED_PYTHON'),
    (OLD428,f'"{OLD428}" -c unknown','PROTECTED_PYTHON'),
    (r'C:\foreign\python.exe','python.exe -I -m cochem_pipeline.owner_task_catalog_428 --request private-secret','PIPELINE_PYTHON'),
])
def test_unknown_native_roles_hold_with_sanitized_rejection_identity(image,command,reason):
    result=inspect_rows([row(image,command)])
    assert result['held'],result
    expected=dict(pid=987,name='python.exe',command_sha256=hashlib.sha256(command.encode()).hexdigest(),reason=reason)
    assert result['failure']['process_rejection']==expected
    assert result['public']['launcher_failure']['process_rejection']==expected
    assert 'private-secret' not in json.dumps(result) and command not in json.dumps(result)
    assert 'C:\\private' not in str(result)


def test_uninspectable_python_is_a_hold_not_silent_quiescence():
    result=inspect_rows([row('', '', name='python.exe')])
    assert result['held'],result
    assert result['failure']['process_rejection']['reason']=='UNINSPECTABLE_PYTHON'


@pytest.mark.parametrize('payload',[
    dict(pid=987,name='private-secret',reason='UNREVIEWED',command_sha256='x'*64),
    dict(pid=987,name='python.exe',reason='PROTECTED_PYTHON',raw='never-copy'),
    dict(pid=True,name='python.exe',reason='PROTECTED_PYTHON',command_sha256='a'*64),
])
def test_arbitrary_exception_metadata_cannot_leak_into_public_failure(payload):
    result=inert_ps(r"""
$e=[InvalidOperationException]::new('secret private output')
$v='JSON'|ConvertFrom-Json;$data=@{};foreach($p in $v.PSObject.Properties){$data[$p.Name]=$p.Value}
$e.Data['cochem_recovery_process']=$data
try{throw $e}catch{Get-OpFailure $_ 'fixture'|ConvertTo-Json -Depth 6 -Compress}
""".replace('JSON',json.dumps(payload)))
    assert result.get('process_rejection') is None
    assert 'private-secret' not in json.dumps(result) and 'never-copy' not in json.dumps(result)
