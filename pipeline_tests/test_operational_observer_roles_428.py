"""Exact held observer proof; all task/CIM/filesystem/native ports are inert.

The only Process objects used are handles to this inert PowerShell fixture itself.
No observer process, protected file, task, provider or lifecycle action is invoked.
"""
import json
from pathlib import Path

import pytest

from pipeline_tests.test_operational_launch_428 import ROOT, inert_ps
from pipeline_tests.test_operational_process_roles_428 import PYTHON, inspect_rows, row


STAGING=r'C:\Program Files\CoChem\Supervisor4.2.7-windows-20261007-staging-v1'
OBSERVER=r'C:\Program Files\CoChem\SupervisorObservation4.2.7-windows-20261007-r3-v1'
PARENT=STAGING+r'\.venv\Scripts\python.exe'
HELPER=OBSERVER+r'\held-supervisor-observation-r3-v1.py'


FIXTURE=r'''
$script:python='C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe'
$script:OpOldRoot='C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r4'
$script:OpRoot='C:\Program Files\CoChem\Pipeline4.2.8-windows-20261015-r5'
$e=Get-OpHeldObserverExpected
$script:own=[Diagnostics.Process]::GetCurrentProcess()
$script:start=$script:own.StartTime.ToUniversalTime()
$script:provision=[pscustomobject]@{schema='cochem-held-supervisor-provision/1';status='HELD_OBSERVATION_PROVISIONED';
 phase='complete';root=$e.root;nonce=$e.nonce;configuration_sha256=$e.configuration_sha256;helper_sha256=$e.helper_sha256;
 inputs_sha256=$e.inputs_sha256;paid_repair_enabled=$false;component_recovery_enabled=$false;
 existing_warden_changed=$false;existing_pipeline_pointer_changed=$false}
$script:config=[pscustomobject]@{auto_deploy=$false;observation_only_contract=[pscustomobject]@{
 schema='cochem-held-observation/1';authority_evidence_sha256='1cf291591724b6edef17ba7e8d48fc6cce75830872ff6183ac1139aa313a3177';
 all_actuation_disabled=$true;warden_task_or_pointer_changes_authorized=$false}}
$script:runtime=[pscustomobject]@{schema='cochem-held-supervisor-runtime/1';status='HELD_SUPERVISOR_OBSERVATION_RUNNING';
 provision_nonce=$e.nonce;service_identity='SYSTEM';instance_id=('b'*32);sequence=9631;pid=9612;
 process_creation_filetime=$script:start.ToFileTimeUtc();configuration_sha256=$e.configuration_sha256;
 helper_sha256=$e.helper_sha256;inputs_sha256=$e.inputs_sha256;paid_repair_enabled=$false;
 component_recovery_enabled=$false;warden_actuation_enabled=$false;full_srs_acceptance=$false;
 checked_at=([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0)}
function Collection($item){$c=[pscustomobject]@{Count=1;entry=$item};$c|Add-Member ScriptMethod Item {param($n)return $this.entry};return $c}
$args='-I -B "'+(Join-Path $e.root $e.helper)+'" --observe'
$script:task=[pscustomobject]@{Name=$e.task;State=4;Enabled=$true;LastRunTime=$script:start;Xml='immutable';
 Definition=[pscustomobject]@{Principal=[pscustomobject]@{UserId='SYSTEM';LogonType=5;RunLevel=1};
 Actions=(Collection ([pscustomobject]@{Type=0;Path=$e.python;Arguments=$args;WorkingDirectory=$e.root}));
 Settings=[pscustomobject]@{AllowDemandStart=$true;ExecutionTimeLimit='PT0S';RestartCount=0;MultipleInstances=2};
 Triggers=(Collection ([pscustomobject]@{Type=8;Enabled=$true}))}}
$script:task|Add-Member ScriptMethod GetInstances {param($flags)return (Collection ([pscustomobject]@{InstanceGuid='{11111111-1111-1111-1111-111111111111}'}))}
$script:task|Add-Member ScriptMethod GetSecurityDescriptor {param($flags)return 'fixed-task-acl'}
$script:OpFolder=[pscustomobject]@{};$script:OpFolder|Add-Member ScriptMethod GetTask {param($name)return $script:task}
$script:rows=@([pscustomobject]@{ProcessId=9612;ParentProcessId=3132;Name='python.exe';ExecutablePath=$script:python;CommandLine=('"'+$script:python+'" '+$args)},
 [pscustomobject]@{ProcessId=3132;ParentProcessId=2768;Name='python.exe';ExecutablePath=$e.python;CommandLine=('"'+$e.python+'" '+$args)})
$script:fileProofs=0;$script:taskChecks=0
function Assert-OpObserverFiles {param($pins)$script:fileProofs++;return @{provision=$script:provision;config=$script:config}}
function Read-OpObserverSnapshot {param($p)return $script:runtime}
function Open-OpObserverProcess {param($row)return [Diagnostics.Process]::GetCurrentProcess()}
function Assert-428TaskAcl {param($t)$script:taskChecks++}
function Assert-ProtectedPath {}
function Assert-428PortFree {}
function Get-CimInstance {param($class,$filter)if($filter){return $null};return $script:rows}
$pins=[Collections.Generic.List[IO.Stream]]::new();$state=@{}
'''


def observer_fixture(change='', *, repeat=False):
    return inert_ps(FIXTURE+change+r'''
$held=$false;$failure=$null
try{
 Assert-OpRecoveryQuiescent (Get-OpRecoveryExpected) $null $pins $state
 REPEAT
}catch{$held=$true;$failure=Get-OpFailure $_ 'recovery_quiescence'}
$count=if($state.ContainsKey('observer_processes')){$state.observer_processes.Count}else{0}
@{held=$held;failure=$failure;files=$script:fileProofs;handles=$count;tasks=$script:taskChecks}|ConvertTo-Json -Depth 10 -Compress
if($state.ContainsKey('observer_processes')){foreach($p in $state.observer_processes){$p.Dispose()}};$script:own.Dispose()
'''.replace('REPEAT', 'Assert-OpRecoveryQuiescent (Get-OpRecoveryExpected) $null $pins $state' if repeat else ''))


def test_exact_current_observer_pair_preserved_and_immutable_files_verified_once():
    result=observer_fixture(repeat=True)
    assert not result['held'],result
    assert result['files']==1 and result['handles']==4 and result['tasks']==4


@pytest.mark.parametrize('change',[
    "$script:runtime.paid_repair_enabled=$true",
    "$script:runtime.component_recovery_enabled=$true",
    "$script:runtime.warden_actuation_enabled=$true",
    "$script:runtime.full_srs_acceptance=$true",
    "$script:config.auto_deploy=$true",
    "$script:config.observation_only_contract.all_actuation_disabled=$false",
    "$script:config.observation_only_contract.warden_task_or_pointer_changes_authorized=$true",
    "$script:provision.existing_warden_changed=$true",
    "$script:runtime.paid_repair_enabled='false'",
    "$script:runtime.checked_at-=31",
    "$script:runtime.checked_at+=[double]::NaN",
    "$script:runtime.helper_sha256=('f'*64)",
    "$script:runtime.provision_nonce=('a'*32)",
    "$script:runtime.process_creation_filetime+=1",
    "$script:runtime.status='HELD_OBSERVATION_FAILED'",
    "$script:runtime.pid=9613",
    "$script:rows[0].ParentProcessId=3133",
    "$script:rows[1].CommandLine+=' --prepare'",
    "$script:task.Definition.Actions.entry.Arguments+=' --prepare'",
    "$script:task.Definition.Settings.RestartCount=1",
    "$script:task.Definition.Triggers.entry.Type=9",
    "$script:task.Definition.Principal.UserId='OTHER'",
    "$script:task.State=3",
    "$script:task.Enabled=$false",
])
def test_observer_only_allowed_with_complete_live_permanent_hold_proof(change):
    result=observer_fixture(change)
    assert result['held'],result
    assert result['handles']==0
    failure=result['failure']
    assert failure['process_rejection']['reason']=='OBSERVER_PROOF_UNVERIFIED'
    assert failure['observer_proof']['frames']
    assert any('Observer' in f['function'] for f in failure['observer_proof']['frames'])
    assert 'C:\\' not in json.dumps(failure)


def test_current_boot_instance_is_used_and_zero_duration_is_semantic():
    result=observer_fixture("$script:task.Definition.Settings.ExecutionTimeLimit='PT0H0M0S';$script:task.LastRunTime=$script:start.AddSeconds(-30)")
    assert not result['held'],result


def test_mutable_heartbeat_is_checked_again_after_immutable_file_cache():
    result=inert_ps(FIXTURE+r'''
Assert-OpRecoveryQuiescent (Get-OpRecoveryExpected) $null $pins $state
$script:runtime.warden_actuation_enabled=$true;$held=$false
try{Assert-OpRecoveryQuiescent (Get-OpRecoveryExpected) $null $pins $state}catch{$held=$true}
@{held=$held;files=$script:fileProofs}|ConvertTo-Json -Compress
foreach($p in $state.observer_processes){$p.Dispose()};$script:own.Dispose()
''')
    assert result==dict(held=True,files=1)


@pytest.mark.parametrize('image,command',[
    (PYTHON,f'"{PYTHON}" -I -B "{HELPER}" --observe --prepare'),
    (PYTHON,f'"{PYTHON}" -I -B "{HELPER}" --prepare'),
    (PYTHON,f'"{PYTHON}" -I -B "{OBSERVER}\\unknown.py" --observe'),
    (PARENT,f'"{PARENT}" -m cochem_supervisor daemon'),
    (r'C:\foreign\python.exe',rf'"C:\foreign\python.exe" -I -B "{HELPER}" --observe'),
])
def test_observer_path_or_name_is_never_a_blanket_exemption(image,command):
    result=inspect_rows([row(image,command)])
    assert result['held'],result
    assert result['failure']['process_rejection']['reason']!='OBSERVER_PROOF_UNVERIFIED'


def test_missing_immutable_file_retains_sanitized_underlying_proof_frame():
    result=observer_fixture("function Assert-OpObserverFiles {param($pins)throw [IO.FileNotFoundException]::new('secret file path')}")
    assert result['held']
    assert result['failure']['observer_proof']['frames'][0]['function']=='Assert-OpObserverFiles'
    assert 'secret' not in json.dumps(result)


def test_real_archived_manifest_maps_only_109_installed_package_inputs():
    path=ROOT/'docs/evidence/windows-2026-10-06/independent-supervisor-staging-preparation-2026-10-07/independent-supervisor-staging-r3-v1.manifest.json'
    result=inert_ps(r'''
$script:python='PYTHON';$e=Get-OpHeldObserverExpected
$script:manifest=Get-Content -LiteralPath 'MANIFEST' -Raw|ConvertFrom-Json
$script:opened=[Collections.Generic.List[object]]::new()
function Assert-ProtectedPath {}
function Read-OpRecoveryRecord {param($p,$hash,$pins)
 if($p.EndsWith('staging-manifest.json')){if($hash -cne $e.manifest_sha256){throw 'pin'};return $script:manifest};return @{fixture=$true}}
function Open-428Pin {param($p,$hash)$script:opened.Add(@{path=$p;sha256=$hash});return [IO.MemoryStream]::new()}
function Open-VerifiedFile {param($p,$hash,$length)$script:opened.Add(@{path=$p;sha256=$hash;length=$length});return [IO.MemoryStream]::new()}
function Get-ChildItem {param($LiteralPath,$Filter,[switch]$File,[switch]$Force)
 foreach($name in @('_virtualenv.pth','pywin32.pth')){[pscustomobject]@{Name=$name;FullName=(Join-Path $LiteralPath $name)}}}
$pins=[Collections.Generic.List[IO.Stream]]::new()
$null=Assert-OpObserverFiles $pins
@{opened=$script:opened.ToArray();pins=$pins.Count}|ConvertTo-Json -Depth 5 -Compress
foreach($p in $pins){$p.Dispose()}
'''.replace('PYTHON',PYTHON).replace('MANIFEST',str(path)))
    expected=json.loads(path.read_text())['source_files']
    expected={str(Path(STAGING)/'.venv/Lib/site-packages'/r['relative'][4:]):r for r in expected
              if r['relative'].startswith(('src/cochem_pipeline/','src/cochem_mcp/','src/cochem_supervisor/'))}
    installed=[r for r in result['opened'] if 'length' in r]
    assert len(installed)==109
    assert {r['path'] for r in installed}==set(expected)
    assert all(r['sha256']==expected[r['path']]['sha256'] and r['length']==expected[r['path']]['bytes'] for r in installed)
    assert result['pins']==116


def test_observer_snapshot_reader_keeps_atomic_writer_sharing_contract():
    source=(ROOT/'scripts/run_operational_428_launch.ps1').read_text()
    body=source.split('function Read-OpObserverSnapshot {',1)[1].split('\nfunction ',1)[0]
    assert '[IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete' in body
    assert body.count('[CoChemStagedFileIdentity]::Check($stream,$Path)')==2
    assert 'finally{$stream.Dispose()}' in body


def test_real_json_runtime_schema_preserves_filetime_and_fractional_timestamp():
    result=inert_ps(FIXTURE+r'''
$script:runtime.process_creation_filetime=[long]134364756554327555
$script:runtime.checked_at=[Math]::Floor([double]$script:runtime.checked_at)+0.125
$script:runtime|Add-Member NoteProperty process_created_at_unix_seconds ([double]1792002055.4327557)
$value=$script:runtime|ConvertTo-Json -Depth 5|ConvertFrom-Json
Assert-OpObserverRecords $script:provision $script:config $value
@{filetime=$value.process_creation_filetime;fractional=($value.checked_at -is [double] -or $value.checked_at -is [decimal]);valid=$true}|ConvertTo-Json -Compress
$script:own.Dispose()
''')
    assert result==dict(filetime=134364756554327555,fractional=True,valid=True)


def test_open_observer_process_only_observes_fixture_itself_and_rejects_owner_drift():
    # Reference only this inert PS process, not any live supervisor/worker.
    result=inert_ps(r'''
$own=[Diagnostics.Process]::GetCurrentProcess()
$row=[pscustomobject]@{ProcessId=$own.Id;ExecutablePath=$own.MainModule.FileName;CreationDate=$own.StartTime.ToUniversalTime()}
function Invoke-CimMethod {param($InputObject,$MethodName)return @{Sid='S-1-5-18'}}
$retained=Open-OpObserverProcess $row
$exact=($retained.StartTime.ToUniversalTime().ToFileTimeUtc() -eq $own.StartTime.ToUniversalTime().ToFileTimeUtc())
$retained.Dispose()
function Invoke-CimMethod {param($InputObject,$MethodName)return @{Sid='S-1-5-21-foreign'}}
$held=$false;try{$p=Open-OpObserverProcess $row;$p.Dispose()}catch{$held=$true}
$own.Dispose();@{exact=$exact;foreign_held=$held}|ConvertTo-Json -Compress
''')
    assert result==dict(exact=True,foreign_held=True)


@pytest.mark.parametrize('mutation',[
    "$script:task.Xml='changed'",
    "$script:task.LastRunTime=$script:task.LastRunTime.AddSeconds(1)",
    "$script:task|Add-Member -Force ScriptMethod GetInstances {param($f)return (Collection ([pscustomobject]@{InstanceGuid='{22222222-2222-2222-2222-222222222222}'}))}",
])
def test_task_identity_is_captured_before_retaining_native_pair(mutation):
    result=observer_fixture(r'''
$script:opens=0
function Open-OpObserverProcess {param($row)
 $script:opens++;if($script:opens -eq 2){MUTATION}
 return [Diagnostics.Process]::GetCurrentProcess()
}
'''.replace('MUTATION',mutation))
    assert result['held'] and result['handles']==0,result
    assert result['failure']['observer_proof']['frames'][0]['function']=='Assert-OpHeldObserver'
