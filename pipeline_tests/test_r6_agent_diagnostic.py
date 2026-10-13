"""Inert adapters around the real acceptance decision; no SYSTEM/native calls."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import diagnose_r6_agent_custody as diagnostic
from cochem_pipeline.r6_agent_acceptance import verify_worker
from pipeline_tests.test_r6_agent_acceptance import Checks
from pipeline_tests import test_install_r6_runtime as ps_fixture


@pytest.fixture
def config(monkeypatch):
    from cochem_pipeline import agy_agent_guard
    monkeypatch.setattr(agy_agent_guard, 'require_agent_contract', lambda spec: {})
    return SimpleNamespace(providers={'gemini': {}}, max_execution_slots=4,
        workers={f'slot{i}': {'name': f'fixture{i}'} for i in range(1, 7)})


def test_baseline_denial_captures_exact_original_decision_and_stops_before_guard(config):
    class Denied(Checks):
        def check(self, token, requests):
            return [5] * len(requests)
    api = Denied()
    closed = []
    rows = diagnostic.observe(config, api, lambda identity: SimpleNamespace(close=lambda: closed.append(True)), verify_worker)
    assert len(rows) == 1 and rows[0]['stage'] == 'before'
    assert rows[0]['failure']['reason'] == 'PROFILE_DELETE_CONTROL_DENIED'
    assert rows[0]['observations'][0]['codes'] == [5] * 11
    assert rows[0]['handle_cleanup_observed'] and not rows[0]['check_passed']
    assert api.closed and not api.released and closed == [True]


@pytest.mark.parametrize('problem,reason,stage', [
    ('missing', 'BASELINE_PATH_OR_CONTENTION', 'before'),
    ('allowed', 'CUSTODY_ACCESS_NOT_DENIED', 'during'),
    ('cleanup', 'BASELINE_NOT_RESTORED', 'after'),
    ('exception', 'UNCLASSIFIED', 'during'),
    ('guard', 'UNCLASSIFIED', 'guard_acquire'),
])
def test_original_failures_remain_failures_with_stage_and_cleanup(config, problem, reason, stage):
    api = Checks(problem)
    rows = diagnostic.observe(config, api, lambda identity: SimpleNamespace(close=lambda: None), verify_worker)
    row = rows[0]
    assert len(rows) == 1 and not row['check_passed']
    assert row['failure']['reason'] == reason and row['stage'] == stage
    assert row['handle_cleanup_observed'] and api.closed
    if problem in ('allowed', 'cleanup', 'exception'):
        assert api.released and row['guard_closed']


def test_six_checks_are_sequential_and_use_production_verifier(config):
    active, order = [], []
    api = Checks()
    def reserve(identity):
        assert not active
        active.append(identity['name'])
        order.append(identity['name'])
        api.calls = 0
        return SimpleNamespace(close=lambda: active.pop())
    rows = diagnostic.observe(config, api, reserve, verify_worker)
    assert len(rows) == 6 and not active
    assert order == [f'fixture{i}' for i in range(1, 7)]
    assert all(row['check_passed'] and row['handle_cleanup_observed'] for row in rows)
    assert all([x['stage'] for x in row['observations']] == ['before', 'during', 'after'] for row in rows)


def test_busy_identity_never_reads_credentials_or_touches_guard(config):
    def busy(identity):
        raise RuntimeError('Sensitive path or account must not be published')
    rows = diagnostic.observe(config, object(), busy, verify_worker)
    assert len(rows) == 1 and rows[0]['stage'] == 'reservation'
    assert not rows[0]['reservation_acquired'] and not rows[0]['handle_cleanup_observed']
    assert 'Sensitive' not in json.dumps(rows)


def test_reservation_cleanup_error_stops_later_workers_even_after_pass(config):
    def failed_close():
        raise OSError('Private cleanup detail')
    rows = diagnostic.observe(config, Checks(), lambda identity: SimpleNamespace(close=failed_close), verify_worker)
    assert len(rows) == 1 and rows[0]['check_passed']
    assert not rows[0]['handle_cleanup_observed']
    assert rows[0]['cleanup_failure']['error_type'] == 'OSError'
    assert 'Private' not in json.dumps(rows)


def test_guard_cleanup_error_is_reported_without_accepting_cleanup(config):
    class GuardCloseFails(Checks):
        def release(self):
            raise OSError('private')
    rows = diagnostic.observe(config, GuardCloseFails(), lambda identity: SimpleNamespace(close=lambda: None), verify_worker)
    assert len(rows) == 1 and not rows[0]['check_passed']
    assert not rows[0]['guard_closed'] and not rows[0]['handle_cleanup_observed']


@pytest.mark.parametrize('phase', ['agent', 'auth', 'knowledge'])
def test_prior_receipts_are_bound_and_only_hash_and_status_are_projected(phase):
    def read(win, path, **kwargs):
        selected = next(k for k, relative in diagnostic.PRIOR.items() if path == diagnostic.BASE / relative)
        return json.dumps(dict(schema='cochem-r6-system-phase/1', phase=selected,
            status='HELD_PRESERVE_PARTIAL' if selected == 'agent' else 'PHASE_COMPLETED',
            manifest_sha256=diagnostic.MANIFEST, candidate_sha256=diagnostic.CANDIDATE,
            result={'private': 'never publish me'})).encode()
    evidence = diagnostic.prior_evidence(None, read)
    assert set(evidence[phase]) == {'sha256', 'status'}
    assert evidence[phase]['sha256'] == hashlib.sha256(read(None, diagnostic.BASE / diagnostic.PRIOR[phase])).hexdigest()
    assert 'private' not in json.dumps(evidence)
    def wrong(win, path, **kwargs):
        value = json.loads(read(win, path))
        if value['phase'] == phase:
            value['candidate_sha256'] = 'f' * 64
        return json.dumps(value).encode()
    with pytest.raises(ValueError):
        diagnostic.prior_evidence(None, wrong)


def test_failure_never_publishes_raw_exception_or_unknown_type():
    class private_account_name(Exception):
        pass
    record = diagnostic.failure(private_account_name('secret URL code and path'))
    assert record['error_type'] == 'OtherError'
    assert 'secret' not in json.dumps(record) and 'private_account' not in json.dumps(record)


@pytest.mark.parametrize('exists', [False, True])
def test_same_sid_reservation_refuses_overlap_and_closes_only_its_handle(monkeypatch, exists):
    calls = []
    def create(security, owned, name):
        calls.append(('create', name))
        return 123
    def close(handle):
        calls.append(('close', handle))
        return True
    kernel = SimpleNamespace(CreateMutexW=create, CloseHandle=close)
    win = SimpleNamespace(_sid_text=lambda value: value, _account_sid=lambda value: 'S-fixture',
        _api=lambda: {'kernel32': kernel}, _check=lambda value, label: value, _close=close)
    monkeypatch.setattr(diagnostic.C, 'set_last_error', lambda value: None)
    monkeypatch.setattr(diagnostic.C, 'get_last_error', lambda: 183 if exists else 0)
    if exists:
        with pytest.raises(RuntimeError):
            diagnostic.Reservation(win, {'name': 'fixture'})
    else:
        lease = diagnostic.Reservation(win, {'name': 'fixture'})
        lease.close()
        lease.close()
    assert calls == [('create', 'Global\\CoChemPipeline422-S-fixture'), ('close', 123)]


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(ps_fixture, 'SCRIPT', Path(__file__).parents[1]/'scripts/inspect_r6_agent_custody.ps1')
    return ps_fixture.run_ps


def test_ps_plan_stops_before_installed_code_tasks_or_profiles(run_ps):
    result = run_ps("""
function Open-AgentDiagnosticPackage {return @{pins=@{a=1;b=2;c=3;d=4;e=5}}}
function Get-AgentDiagnosticDefinitions {throw 'must not import host functions in read-only plan'}
Invoke-AgentDiagnostic 'C:\\fixture' ('a'*64) $false
""")
    assert result['status'] == 'READ_ONLY_PACKAGE_VERIFIED' and result['files'] == 5
    assert result['provider_commands'] == result['sign_ins'] == 0


@pytest.mark.parametrize('name,state,instances,blocked', [
    ('CoChem-4.2.7-Warden', 4, 1, False),
    ('CoChem-4.2.7-R6Acceptance-agent-old', 3, 0, False),
    ('CoChem-4.2.7-R6Acceptance-agent-old', 4, 1, True),
    ('CoChem-4.2.7-R6AgentDiagnostic-old', 2, 0, True),
    ('CoChem-4.2.7-AgySignIn-old', 4, 1, True),
])
def test_diagnostic_leaves_warden_running_but_refuses_concurrent_maintenance(run_ps, name, state, instances, blocked):
    result = run_ps(f"""
$task=[pscustomobject]@{{Name='{name}';State={state};Instances={instances}}}
$task|Add-Member ScriptMethod GetInstances {{param($flags) if($this.Instances){{@('instance')}}else{{@()}}}}
$folder=[pscustomobject]@{{task=$task}}
$folder|Add-Member ScriptMethod GetTasks {{param($flags) @($this.task)}}
$held=$false
try{{Assert-AgentDiagnosticIdle $folder}}catch{{$held=$true}}
@{{held=$held}}|ConvertTo-Json -Compress
""")
    assert result['held'] is blocked


def test_ps_error_projection_has_only_numeric_and_allowlisted_metadata(run_ps):
    record = run_ps("""
try{throw 'private URL and code'}catch{Get-AgentDiagnosticFailure $_ 'copy'|ConvertTo-Json -Compress}
""")
    assert record['phase'] == 'copy' and record['raw_error_published'] is False
    assert 'private URL' not in json.dumps(record)


@pytest.mark.parametrize('mutation', ['duplicate', 'traversal', 'missing', 'length', 'hash'])
def test_package_rejects_unbound_helpers_before_host_work(tmp_path, run_ps, mutation):
    names = ['inspect_r6_agent_custody.ps1', 'diagnose_r6_agent_custody.py', 'run_r6_system_phase.ps1',
             'install_r6_runtime.ps1', 'stage_aetherdesk_427_payloads.ps1']
    rows = []
    for name in names:
        raw = b'# fixture'
        (tmp_path/name).write_bytes(raw)
        rows.append(dict(name=name, sha256=hashlib.sha256(raw).hexdigest(), length=len(raw)))
    if mutation == 'duplicate': rows[-1] = rows[0]
    if mutation == 'traversal': rows[-1]['name'] = '../escape'
    if mutation == 'missing': rows.pop()
    if mutation == 'length': rows[-1]['length'] += 1
    if mutation == 'hash': rows[-1]['sha256'] = 'f' * 64
    raw = json.dumps(dict(schema='cochem-r6-agent-diagnostic-package/1', host='AETHERDESK', nonce='a'*32, files=rows)).encode()
    (tmp_path/'manifest.json').write_bytes(raw)
    record = run_ps(f"""
$streams=[Collections.Generic.List[IO.FileStream]]::new();$held=$false
try{{$null=Open-AgentDiagnosticPackage '{str(tmp_path).replace("'", "''")}' '{hashlib.sha256(raw).hexdigest()}' $streams}}catch{{$held=$true}}
finally{{foreach($s in $streams){{$s.Dispose()}}}}
@{{held=$held}}|ConvertTo-Json -Compress
""")
    assert record['held']


@pytest.fixture
def produced_report(tmp_path, monkeypatch, config):
    """Actual diagnostic writer, injected native seams, real acceptance verifier."""
    from cochem_pipeline import windows, r6_host_acceptance, r6_agent_acceptance, ramdisk
    base = tmp_path/'protected'
    root = base/('R6AgentDiagnostic427-'+'a'*32)
    root.mkdir(parents=True)
    monkeypatch.setattr(diagnostic, '__file__', str(root/'diagnose_r6_agent_custody.py'))
    monkeypatch.setattr(diagnostic, 'BASE', base)
    monkeypatch.setattr(windows, 'require_system', lambda: None)
    monkeypatch.setattr(windows, 'validate_private_directory', lambda value: None)
    monkeypatch.setattr(r6_host_acceptance, 'bind_installation', lambda *args: (config, {}, {}, {}))
    monkeypatch.setattr(r6_host_acceptance, 'read_bound', lambda win, path, **kwargs: path.read_bytes())
    monkeypatch.setattr(r6_agent_acceptance, 'WindowsChecks', lambda: Checks('missing'))
    config.ramdisk, config.private_root = object(), object()
    monkeypatch.setattr(windows, 'WorkerIdentity', lambda **identity: identity)
    monkeypatch.setattr(ramdisk, 'RamdiskManager', lambda *args: SimpleNamespace(inspect=lambda: None))
    monkeypatch.setattr(diagnostic, 'Reservation', lambda win, identity: SimpleNamespace(close=lambda: None))
    for phase, relative in diagnostic.PRIOR.items():
        path = base/relative
        path.parent.mkdir()
        path.write_text(json.dumps(dict(schema='cochem-r6-system-phase/1', phase=phase,
            status='HELD_PRESERVE_PARTIAL' if phase == 'agent' else 'PHASE_COMPLETED',
            manifest_sha256=diagnostic.MANIFEST, candidate_sha256=diagnostic.CANDIDATE)))
    assert diagnostic.main() == 0
    return root


def test_real_writer_saves_failed_check_as_diagnostic_not_acceptance(produced_report):
    record = json.loads((produced_report/'result.json').read_text())
    assert record['status'] == 'DIAGNOSTIC_CAPTURED' and record['activation_ready'] is False
    assert record['ram_inspection_passed'] is True
    assert record['workers'][0]['failure']['reason'] == 'BASELINE_PATH_OR_CONTENTION'
    assert record['workers'][0]['observations'][0]['codes'][-1] == 2
    with pytest.raises(ValueError, match='Preserve existing diagnostic'):
        diagnostic.main()


@pytest.mark.parametrize('mutation', ['', 'manifest', 'task_exit', 'activation', 'provider'])
def test_ps_consumer_uses_actual_report_and_one_fast_finished_task(produced_report, run_ps, mutation):
    path = produced_report/'result.json'
    report = json.loads(path.read_text())
    if mutation == 'manifest': report['manifest_sha256'] = 'f'*64
    if mutation == 'activation': report['activation_ready'] = True
    if mutation == 'provider': report['provider_commands_executed'] = 1
    path.write_text(json.dumps(report))
    body = r"""
function Assert-ProtectedPath {param($Path)}
function Start-Sleep {param($Milliseconds)}
function Assert-R6PhaseTask {
 param($Task,$Executable,$Arguments,$Directory,$Seconds,$Enabled)
 if($Seconds -ne 600 -or $Task.Enabled -ne $Enabled){throw 'incorrect task boundary'}
 if($Arguments -notlike '-I -B *diagnose_r6_agent_custody.py*'){throw 'unexpected action'}
}
function Test-R6PhaseFinished {param($Task,$Root,$RequestedAt) return $true}
$action=[pscustomobject]@{Path='';Arguments='';WorkingDirectory=''}
$actions=[pscustomobject]@{Action=$action}
$actions|Add-Member ScriptMethod Create {param($type) $this.Action}
$definition=[pscustomobject]@{RegistrationInfo=@{};Principal=@{};Settings=@{};Actions=$actions}
$scheduler=[pscustomobject]@{Definition=$definition}
$scheduler|Add-Member ScriptMethod NewTask {param($flags) $this.Definition}
$task=[pscustomobject]@{Name='CoChem-4.2.7-R6AgentDiagnostic-fixture';Enabled=$false;State=3;LastTaskResult=EXIT;Runs=0}
$task|Add-Member ScriptMethod Run {param($parameters) $this.Runs+=1;return $null}
$task|Add-Member ScriptMethod GetInstances {param($flags) @()}
$folder=[pscustomobject]@{Task=$task;Registrations=0}
$folder|Add-Member ScriptMethod RegisterTaskDefinition {
 param($Name,$Definition,$Flags,$User,$Password,$LogonType,$Acl)
 if($Flags -ne 18 -or $User -cne 'SYSTEM' -or $LogonType -ne 5 -or $Acl -cne 'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'){throw 'registration changed'}
 $this.Registrations+=1;return $this.Task
}
$folder|Add-Member ScriptMethod GetTask {param($name) $this.Task}
$folder|Add-Member ScriptMethod GetTasks {param($flags) @($this.Task)}
$held=$false;$result=$null
try{$result=Invoke-AgentDiagnosticTask $scheduler $folder 'ROOT' 'CoChem-4.2.7-R6AgentDiagnostic-fixture'}catch{$held=$true}
@{held=$held;runs=$task.Runs;registrations=$folder.Registrations;report=$result}|ConvertTo-Json -Depth 14 -Compress
""".replace('EXIT', '2' if mutation == 'task_exit' else '0').replace('ROOT', str(produced_report).replace("'", "''"))
    result = run_ps(body)
    assert result['held'] is bool(mutation)
    assert result['runs'] == result['registrations'] == 1
    if not mutation:
        assert result['report'] == report


def test_contract_in_delivered_candidate_is_valid_without_native_execution():
    from cochem_pipeline.agy_agent_guard import require_agent_contract
    candidate = Path(r'C:\Users\ansac\CoChem427\r6-bundle-359ca92\pipeline.json')
    if not candidate.exists():
        pytest.skip('The immutable owner package is a host-only fixture')
    raw = candidate.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == diagnostic.CANDIDATE
    value = json.loads(raw.decode('utf-8-sig'))
    contract = require_agent_contract(value['providers']['gemini'])
    assert contract['name'] == 'cochem-inference-only'
