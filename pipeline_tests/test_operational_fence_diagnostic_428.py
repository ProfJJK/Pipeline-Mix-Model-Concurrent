"""Only AST-imported pure PS5.1 functions and temporary files; no host inspection."""
import hashlib
import json
from pathlib import Path

import pytest

from pipeline_tests import test_install_r6_runtime as ps_fixture

SCRIPT = Path(__file__).parents[1] / 'scripts/inspect_operational_fence_428.ps1'


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(ps_fixture, 'SCRIPT', SCRIPT)
    return ps_fixture.run_ps


def test_allowlist_never_exports_messages_xml_arguments_or_credentials(run_ps):
    value = run_ps(r'''
$v=@{schema='cochem-owner-admission-fence/4.2.8';status='FENCE_HELD_PRESERVE_EVIDENCE';
 error_type='OperationalError';pid=123;nonce=('a'*32);config_sha256=('b'*64);
 message='SECRET';xml='SECRET';arguments='SECRET';token='SECRET';database_path='SECRET';
 counts=@{active_leases=0;native_reservations=1;SECRET=99};
 frames=@(@{function='run';line=159;source='SECRET'},@{function='SECRET';line=2})}
Select-OpDiagnosticRecord $v|ConvertTo-Json -Depth 8 -Compress
''')
    assert value['status'] == 'FENCE_HELD_PRESERVE_EVIDENCE'
    assert value['counts'] == {'active_leases': 0, 'native_reservations': 1}
    assert value['frames'] == [{'function': 'run', 'line': 159}]
    assert 'SECRET' not in json.dumps(value)


def test_file_reader_hashes_exact_bytes_and_leaves_fixture_unchanged(run_ps, tmp_path):
    path = tmp_path / 'ready.json'
    raw = b'{"schema":"cochem-owner-admission-fence/4.2.8","status":"WRITER_FENCE_HELD"}'
    path.write_bytes(raw)
    value = run_ps(f"Read-OpDiagnosticRecord '{str(path)}'|ConvertTo-Json -Depth 6 -Compress")
    assert value['read_status'] == 'READ_VERIFIED'
    assert value['sha256'] == hashlib.sha256(raw).hexdigest()
    assert path.read_bytes() == raw


@pytest.mark.parametrize('content,status', [(b'', 'EMPTY_UNSEALED'), (b'{bad', 'INVALID_JSON'), (b'x' * 1048577, 'SIZE_REJECTED')], ids=['empty', 'invalid', 'oversized'])
def test_partial_or_oversized_metadata_is_not_asserted_as_receipt(run_ps, tmp_path, content, status):
    path = tmp_path / 'held.json'
    path.write_bytes(content)
    value = run_ps(f"Read-OpDiagnosticRecord '{str(path)}'|ConvertTo-Json -Depth 6 -Compress")
    assert value['read_status'] == status
    assert value['record'] is None
    assert path.read_bytes() == content


def test_task_projection_reports_state_and_binding_flags_without_definition(run_ps):
    value = run_ps(r'''
$actions=[pscustomobject]@{Count=1};$actions|Add-Member ScriptMethod Item {param($i)
 [pscustomobject]@{Path='EXPECTED';Arguments='SECRET';WorkingDirectory='ROOT';Type=0}}
$definition=[pscustomobject]@{Actions=$actions;Triggers=[pscustomobject]@{Count=0};
 Principal=[pscustomobject]@{UserId='SYSTEM';LogonType=5;RunLevel=1};
 Settings=[pscustomobject]@{RestartCount=0;MultipleInstances=2;ExecutionTimeLimit='PT2100S'}}
$task=[pscustomobject]@{Xml='SECRET';Enabled=$true;State=3;LastTaskResult=2;LastRunTime=[datetime]'2026-10-15T12:00:00Z';Definition=$definition}
$task|Add-Member ScriptMethod GetInstances {param($flags) [pscustomobject]@{Count=0}}
$task|Add-Member ScriptMethod GetSecurityDescriptor {param($flags) 'SECRET'}
Get-OpDiagnosticTaskProjection $task 'SECRET' 'SECRET' 'EXPECTED' 'ROOT' 'SECRET'|ConvertTo-Json -Depth 6 -Compress
''')
    assert value['instances'] == 0
    assert value['last_task_result'] == 2
    assert value['xml_matches_baseline'] is True
    assert value['action_arguments_match'] is True
    assert 'SECRET' not in json.dumps(value)


def test_non_matching_fence_task_is_not_selected(run_ps):
    value = run_ps(r'''
$root='C:\Program Files\CoChem\R428Operational-20261015-a62bffb278044fffbaf21207a866ff81\private\stop-fence-'+('a'*32)
$args='-I -B -m cochem_pipeline.owner_admission_fence_428 --output-root "'+$root+'" --nonce '+('b'*32)
@{match=(Get-OpDiagnosticFenceNonce $args $root);other=(Get-OpDiagnosticFenceNonce $args ($root+'x'));injected=(Get-OpDiagnosticFenceNonce ($args+' --nonce '+('c'*32)) $root)}|ConvertTo-Json -Compress
''')
    assert value == {'match': 'b' * 32, 'other': None, 'injected': None}


def test_complete_report_keeps_partial_metadata_and_absent_runtime_explicit(run_ps):
    value = run_ps(r'''
function Assert-OpDiagnosticPath {param($Path)}
function Get-ChildItem {param($LiteralPath,[switch]$Directory,$Filter,$ErrorAction)
 [pscustomobject]@{Name=('stop-fence-'+('a'*32));FullName=($LiteralPath+'\stop-fence-'+('a'*32))}}
function Read-OpDiagnosticRecord {param($Path)
 $r=@{read_status='READ_VERIFIED';sha256=('c'*64);bytes=100;record=$null}
 if($Path.EndsWith('baseline.json')){$r.record=@{health=@{pid=123;process_started_at=1792072800};config_sha256=('d'*64);xml='';sddl='SECRET'}}
 elseif($Path.EndsWith('ready.json')){$r.record=@{schema='cochem-owner-admission-fence/4.2.8';status='WRITER_FENCE_HELD';pid=456;nonce=('b'*32);counts=@{uncleared_containment=0;catalog_probes=0}}}
 elseif($Path.EndsWith('result.json') -and -not $Path.EndsWith('owner-result.json')){$r.record=@{schema='cochem-owner-admission-fence/4.2.8';status='FENCE_EXPIRED';lock_released=$true;released=$false}}
 else{$r.read_status='ABSENT'};return $r
}
function Get-CimInstance {param($ClassName,$Filter,$ErrorAction) return $null}
function Get-NetTCPConnection {param($LocalPort,$State,$ErrorAction) return @()}
function New-Object {param($ComObject)
 $scheduler=[pscustomobject]@{};$scheduler|Add-Member ScriptMethod Connect {}
 $scheduler|Add-Member ScriptMethod GetFolder {param($path)
  $f=[pscustomobject]@{};$f|Add-Member ScriptMethod GetTask {param($name) throw 'Unreadable fixture'}
  $f|Add-Member ScriptMethod GetTasks {param($flags) @()};return $f};return $scheduler
}
Get-OpDiagnosticReport|ConvertTo-Json -Depth 14 -Compress
''')
    assert value['baseline']['process'] == {'status': 'PID_ABSENT', 'pid': 123}
    assert value['fences'][0]['records'][1]['projection']['status'] == 'WRITER_FENCE_HELD'
    assert value['fences'][0]['records'][-1]['projection']['status'] == 'FENCE_EXPIRED'
    assert value['fences'][0]['processes'] == [{'status': 'PID_ABSENT', 'pid': 456}]
    assert value['listener']['count'] == 0
    assert value['raw_logs_read'] is False
    assert 'SECRET' not in json.dumps(value)


def test_process_projection_does_not_expose_command_line(run_ps):
    value = run_ps(r'''
function Get-CimInstance {param($ClassName,$Filter,$ErrorAction)
 [pscustomobject]@{CreationDate=[datetime]'2026-10-15T12:00:00Z';ParentProcessId=100;
 ExecutablePath='C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe';CommandLine='SECRET'}}
Get-OpDiagnosticProcess 123 'C:\expected\pipeline.json' 1792065601|ConvertTo-Json -Compress
''')
    assert value['status'] == 'PID_PRESENT'
    assert value['python_image_matches'] is True
    assert value['old_daemon_config_matches'] is False
    assert 'SECRET' not in json.dumps(value)


def test_diagnostic_has_fixed_scope_and_no_lifecycle_or_raw_log_reads():
    source = SCRIPT.read_text()
    assert 'R428Operational-20261015-a62bffb278044fffbaf21207a866ff81' in source
    assert "'stop-fence-*'" in source
    for forbidden in ('RegisterTask', '.Run(', '.Stop(', 'Start-Process', 'Stop-Process', 'Set-Acl', 'Get-Content', 'stdout.log', 'stderr.log', 'token_file'):
        assert forbidden not in source
    assert "'CreateNew','Write','Read'" in source
