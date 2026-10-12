"""PowerShell 5.1 functions with fixture paths; never installs or elevates."""
import base64
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/install_r6_runtime.ps1'
PS = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'


def run_ps(body):
    path = str(SCRIPT).replace("'", "''")
    source = f"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$tokens,[ref]$errors)
if($errors.Count){{throw 'Script parse error'}}
foreach($f in $ast.FindAll({{param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]}},$false)){{
 . ([scriptblock]::Create($f.Extent.Text))
}}
$script:targetRoot='C:\\fixture\\r6'
{body}
"""
    result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-EncodedCommand',
        base64.b64encode(source.encode('utf-16-le')).decode()], capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    return json.loads(result.stdout.decode('utf-8-sig'))


def test_installer_native_commands_are_offline_and_have_no_source_build():
    data = run_ps("""
$script:python='C:\\protected\\python.exe';$script:uv='C:\\protected\\uv.exe'
@{venv=@(Get-R6VenvArguments);install=@(Get-R6InstallArguments)}|ConvertTo-Json -Compress
""")
    assert '--offline' in data['install'] and '--no-index' in data['install']
    assert '--require-hashes' in data['install'] and '--no-deps' in data['install']
    assert '--no-build' in data['install']
    assert '--no-python-downloads' in data['venv']
    assert 'copy' in data['install']


def test_copy_helper_import_uses_explicit_directory_after_ast_import():
    directory=str(SCRIPT.parent).replace("'","''")
    result=run_ps(f"""
$definitions=@(Import-R6CopyFunctions '{directory}')
@{{count=$definitions.Count;has_copy=[bool]($definitions -match 'function Copy-VerifiedPayload')}}|ConvertTo-Json -Compress
""")
    assert result==dict(count=9,has_copy=True)


@pytest.mark.parametrize('relative', ['../escape', 'source/../../escape', 'wheels/CON.whl',
    'source/name:stream', 'C:/outside', 'source/a.', 'other/file.py', 'wheels/a\\..\\b'])
def test_installer_refuses_unsafe_or_unexpected_payload_paths(relative):
    literal = relative.replace("'", "''")
    result = run_ps(f"""
$held=$false
try{{Assert-R6Relative '{literal}'}}catch{{$held=$true}}
@{{held=$held}}|ConvertTo-Json -Compress
""")
    assert result['held']


def test_manifest_requires_complete_source_and_wheel_payload():
    result = run_ps("""
$m=[pscustomobject]@{schema='cochem-r6-install-bundle/1';host='AETHERDESK';revision='windows-20261012-r6-v1';
 source_commit=('a'*40);files=@([pscustomobject]@{relative='source/README.md';source='C:\\fixture\\README.md';sha256=('b'*64);length=5})}
$held=$false
try{$null=@(Get-R6InstallFiles $m)}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
""")
    assert result['held']


def test_manifest_materializes_typed_records_without_flattened_paths():
    result = run_ps("""
$relatives=@('source/README.md','source/pyproject.toml','source/uv.lock',
 'source/src/cochem_pipeline/__main__.py','source/src/cochem_pipeline/specification/routing_catalog_v3.json',
 'source/knowledge/v4.1.2_manifest.json','pipeline.json','wheels/runtime-requirements.txt','wheels/cochem-4.2.7-py3-none-any.whl')
$m=[pscustomobject]@{schema='cochem-r6-install-bundle/1';host='AETHERDESK';revision='windows-20261012-r6-v1';
 source_commit=('a'*40);files=@($relatives|ForEach-Object{[pscustomobject]@{relative=$_;source=('C:\\fixture\\'+$_.Replace('/','\\'));sha256=('b'*64);length=5}})}
$rows=@(Get-R6InstallFiles $m)
@{count=$rows.Count;first_source=$rows[0].source;first_destination=$rows[0].destination}|ConvertTo-Json -Compress
""")
    assert result['count'] == 9
    assert result['first_source'].endswith('source\\README.md')
    assert result['first_destination'].endswith('source\\README.md')


@pytest.mark.parametrize('failure', ['', 'offline-install', 'verify-revision'])
def test_install_flow_preserves_failure_and_restores_environment(tmp_path, failure):
    root = str(tmp_path / 'fresh').replace("'", "''")
    manifest = tmp_path / 'manifest.json'
    manifest.write_text('{}')
    manifest_path = str(manifest).replace("'", "''")
    data = run_ps(f"""
$script:targetRoot='{root}';$script:uv='fixture-uv';$script:python='fixture-python'
$script:trace=[Collections.Generic.List[string]]::new();$script:records=@{{}}
function Assert-R6NotReferenced {{$script:trace.Add('task-read-only')}}
function New-ProtectedDirectory {{param($Path) $null=[IO.Directory]::CreateDirectory($Path)}}
function Copy-VerifiedPayload {{param($File) $script:trace.Add('copy')}}
function Write-R6InstallRecord {{param($Name,$Value) $script:records[$Name]=$Value}}
function Assert-R6Interpreter {{$script:trace.Add('interpreter')}}
function Assert-R6Tree {{42}}
function Invoke-R6Native {{param($Executable,$Arguments,$Label,$Seconds)
 $script:trace.Add($Label)
 if(('{failure}' -eq 'offline-install' -and $Label -eq 'install-wheels') -or
    ('{failure}' -eq 'verify-revision' -and $Label -eq 'verify-revision')){{throw 'fixture failure'}}
 if($Label -eq 'verify-revision'){{[IO.File]::WriteAllText((Join-Path $script:targetRoot 'verify-revision.stdout.log'),
 '{{"schema":"cochem-installed-revision/1","verified":true}}')}}
}}
$beforeTemp=$env:TEMP;$env:UV_R6_FIXTURE='preserve-me';$failed=$false
try{{Invoke-R6Installation ([pscustomobject]@{{source_commit=('a'*40)}}) @() '{manifest_path}' ('b'*64)|Out-Null}}catch{{$failed=$true}}
@{{failed=$failed;root_preserved=(Test-Path -LiteralPath $script:targetRoot);
 environment_restored=($env:TEMP -ceq $beforeTemp -and $env:UV_R6_FIXTURE -ceq 'preserve-me');
 trace=@($script:trace.ToArray());records=$script:records}}|ConvertTo-Json -Depth 8 -Compress
""")
    assert data['root_preserved'] and data['environment_restored']
    assert data['failed'] == bool(failure)
    if failure:
        assert data['records']['install-held.json']['phase'] == failure
        assert 'install-after.json' not in data['records']
        assert data['records']['install-held.json']['automatic_retry'] is False
    else:
        receipt = data['records']['install-after.json']
        assert receipt['status'] == 'STOPPED_RUNTIME_INSTALLED'
        assert receipt['tasks_changed'] == 0 and receipt['pipeline_started'] is False
        assert receipt['activation_ready'] is False


def test_script_parameter_boundary_rejects_unpinned_input_without_host_work():
    result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-File', str(SCRIPT),
                            '-Manifest', 'C:\\fixture\\manifest.json', '-ManifestSha256', 'invalid'],
                            capture_output=True, timeout=15)
    assert result.returncode != 0
    assert b'pinned R6 manifest is required' in result.stderr


def test_corpus_payload_acl_excludes_worker_read_without_changing_code_acl():
    data = run_ps("""
function New-CodeAcl {param([bool]$Directory)
 $acl=if($Directory){[Security.AccessControl.DirectorySecurity]::new()}else{[Security.AccessControl.FileSecurity]::new()}
 $acl.SetAccessRuleProtection($true,$false)
 foreach($sid in @('S-1-5-18','S-1-5-32-544','S-1-5-32-545')){
  $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'ReadAndExecute','Allow'))}
 $acl
}
$private=New-R6PayloadAcl 'source/knowledge/.sources/doc.md' $false
$public=New-R6PayloadAcl 'source/src/cochem_pipeline/runtime.py' $false
$getSids={param($acl) @($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])|ForEach-Object{$_.IdentityReference.Value})}
@{corpus=@(& $getSids $private);code=@(& $getSids $public)}|ConvertTo-Json -Compress
""")
    assert 'S-1-5-32-545' not in data['corpus']
    assert 'S-1-5-32-545' in data['code']
