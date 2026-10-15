"""Owner-phase protocol with temporary files/SQLite and inert runtime ports.

No Windows ACL, provider, process, container, or deployment acceptance is claimed.
"""
import hashlib
import json
from pathlib import Path
import stat
import threading
import time
from types import SimpleNamespace

import pytest

from cochem_pipeline import owner_task_catalog_428 as owner
from cochem_pipeline import task_catalog_acceptance_428 as acceptance
from cochem_pipeline.planning_runtime import PlanningConfig
from pipeline_tests.test_task_catalog_acceptance_428 import (
    environment, raw_task_catalog, binary_bindings, finish_all, PINS,
)


@pytest.fixture(autouse=True)
def no_children(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('Child processes prohibited'))


@pytest.fixture
def phase_env(environment, tmp_path, monkeypatch):
    store, request, raw_request = environment
    held = []
    checked = []
    class Custody:
        def __init__(self, _): pass
        def acquire(self, path, directory):
            handle = (Path(path), directory)
            held.append(handle)
            return handle
        def inspect(self, path, directory):
            info = path.lstat()
            assert not stat.S_ISLNK(info.st_mode)
            assert stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
            return info.st_size
        def read(self, path, maximum): return path.read_bytes()[:maximum]
        def validate(self, path): checked.append(path)
        def release(self, handle): held.remove(handle)
    monkeypatch.setattr(owner, '_WindowsCustody', Custody)
    monkeypatch.setattr(acceptance, '_WindowsCustody', Custody)
    monkeypatch.setattr(owner.windows, 'require_system', lambda: None)
    monkeypatch.setattr(owner.windows, 'validate_code_path', lambda path: checked.append(Path(path)))
    monkeypatch.setattr(acceptance, 'execution_bindings', lambda p, w: PINS)
    source = tmp_path / 'inputs'
    source.mkdir()
    output = tmp_path / 'output'
    output.mkdir()
    bootstrap = source / 'bootstrap.json'
    bootstrap.write_bytes(acceptance.encoded(dict(routing=request.plan.policy.as_dict(),
        max_execution_slots=4, catalog_activation=True, task_planning=None, providers={}, workers={})))
    request_path = source / 'request.json'
    request_path.write_bytes(acceptance.encoded(raw_request))
    loads = []
    def load(path):
        data = json.loads(Path(path).read_bytes())
        loads.append(Path(path))
        return SimpleNamespace(task_planning=PlanningConfig.from_dict(data['task_planning']),
            catalog_activation=data['catalog_activation'], max_execution_slots=data['max_execution_slots'])
    monkeypatch.setattr(owner, 'load_config', load)
    runtime = SimpleNamespace(store=store, stop_event=threading.Event(), last_admission_action=None,
        ticks=[], closed=0, tick_failure=None)
    def tick(**kwargs):
        assert kwargs == dict(admit_jobs=False, catalog_poll=False)
        runtime.ticks.append(kwargs)
        if runtime.tick_failure:
            raise runtime.tick_failure
    def close():
        assert (request_path, False) in held, 'Request custody must cover error cleanup as well'
        runtime.closed += 1
        runtime.stop_event.set()
    runtime.tick, runtime.close = tick, close
    def factory(config):
        assert config.task_planning is None and config.catalog_activation
        runtime.config = config
        return runtime
    calls = []
    def publish(rt, proposal):
        calls.append(proposal)
        assert rt is runtime and (request_path, False) in held
        if len(calls) == 1:
            finish_all(store, proposal)
        with store._write() as conn:
            result = acceptance.publish(conn, proposal)
            coverage = acceptance.coverage(result['catalog'], conn=conn)
        return dict(result, catalog_published=True, coverage=coverage,
            all_routes_usable=all(row['status'] == 'AVAILABLE' for row in coverage),
            coverage_holds=sum(row['status'] != 'AVAILABLE' for row in coverage))
    monkeypatch.setattr(owner, 'run_acceptance', publish)
    args = [bootstrap, hashlib.sha256(bootstrap.read_bytes()).hexdigest(), request_path,
            hashlib.sha256(request_path.read_bytes()).hexdigest(), output]
    return SimpleNamespace(store=store, request=request, args=args, runtime=runtime, factory=factory,
                           held=held, checked=checked, calls=calls, loads=loads, publish=publish)


def invoke(env, **kwargs):
    return owner.run_owner_phase(*env.args, runtime_factory=env.factory, poll_seconds=.01, **kwargs)


def test_owner_phase_publishes_exact_new_files_and_validates_normal_loader(phase_env):
    env = phase_env
    result = invoke(env)
    started = json.loads((env.args[-1] / 'phase-started.json').read_bytes())
    assert started['pid'] == owner.os.getpid()
    assert type(started['started_at']) is float and started['started_at'] > 0
    assert result['status'] == 'TASK_CATALOG_CANDIDATE_READY'
    assert result['cleanup_verified'] is True
    assert result['publication_state'] == 'COMMITTED'
    assert result['catalog_published'] is True and result['cutover_requested'] is False
    assert result['ordinary_jobs_dispatched'] is False and result['sign_in_attempted'] is False
    configuration = Path(result['configuration_path'])
    catalog = Path(result['catalog_path'])
    for path, pin in ((configuration, 'configuration_sha256'), (catalog, 'catalog_sha256')):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == result[pin]
    assert json.loads(configuration.read_bytes())['task_planning']['catalog_sha256'] == result['catalog_sha256']
    assert env.loads == [env.args[0], configuration]
    assert env.runtime.closed == 1 and not env.held
    assert env.runtime.ticks and len(env.calls) == 1
    assert json.loads((env.args[-1] / 'result.json').read_bytes()) == result


def test_shared_admission_wait_reuses_request_without_prompt_or_ordinary_dispatch(phase_env, monkeypatch):
    env = phase_env
    waits = []
    def wait_first(rt, request):
        waits.append(request.request_id)
        if len(waits) == 1:
            return dict(status='WAITING_ADMISSION')
        return env.publish(rt, request)
    monkeypatch.setattr(owner, 'run_acceptance', wait_first)
    assert invoke(env)['status'] == 'TASK_CATALOG_CANDIDATE_READY'
    assert waits == [env.request.request_id] * 2
    assert len(env.calls) == 1 and env.runtime.closed == 1


@pytest.mark.parametrize('fault', ['guard', 'exception', 'cancel', 'deadline'])
def test_guard_cancel_and_deadline_hold_without_candidate_or_secret_details(phase_env, monkeypatch, fault):
    env = phase_env
    def failed(rt, request):
        if fault == 'guard':
            rt.last_admission_action = 'terminate_active'
        elif fault == 'exception':
            rt.tick_failure = ValueError('secret-provider-payload')
        elif fault == 'cancel':
            rt.stop_event.set()
        else:
            monkeypatch.setattr(owner.time, 'monotonic', lambda: 10**12)
        # The acceptance port is synchronous. Its real native implementation
        # checks runtime.stop_event through its existing heartbeat.
        assert rt.stop_event.wait(1)
        raise RuntimeError('secret-provider-payload')
    monkeypatch.setattr(owner, 'run_acceptance', failed)
    result = invoke(env, timeout_seconds=1)
    assert result['status'] == 'TASK_CATALOG_HELD_PRESERVE_EVIDENCE'
    assert result['cleanup_verified'] is False and result['runtime_resources_closed'] is True
    assert result['catalog_published'] is False and result['automatic_retry'] is False
    assert result['publication_state'] == 'NOT_COMMITTED'
    assert 'secret-provider-payload' not in json.dumps(result)
    assert not (env.args[-1] / 'pipeline.json').exists()
    assert env.runtime.closed == 1 and not env.held


def test_existing_outputs_or_bad_pin_never_start_runtime(phase_env):
    env = phase_env
    env.args[1] = 'f' * 64
    result = invoke(env)
    assert result['phase'] == 'preconditions' and env.runtime.closed == 0
    with pytest.raises(ValueError, match='fresh and empty'):
        invoke(env)
    assert not env.calls


def test_failed_candidate_validation_preserves_published_catalog_and_files(phase_env, monkeypatch):
    env = phase_env
    original = owner.load_config
    def reject_candidate(path):
        if Path(path).name == 'pipeline.json':
            raise ValueError('private-config-detail')
        return original(path)
    monkeypatch.setattr(owner, 'load_config', reject_candidate)
    result = invoke(env)
    assert result['status'] == 'TASK_CATALOG_HELD_PRESERVE_EVIDENCE'
    assert result['catalog_published'] is True and result['phase'] == 'candidate_validation'
    assert (env.args[-1] / 'pipeline.json').exists() and (env.args[-1] / 'accepted-catalog.json').exists()
    assert env.runtime.closed == 1 and not env.held


def test_committed_publication_replays_into_new_output_root_without_probing_again(phase_env, monkeypatch, tmp_path):
    env = phase_env
    assert invoke(env)['status'] == 'TASK_CATALOG_CANDIDATE_READY'
    env.runtime.stop_event.clear()
    output = tmp_path / 'continuation-output'
    output.mkdir()
    env.args[-1] = output
    result = invoke(env)
    assert result['status'] == 'TASK_CATALOG_CANDIDATE_READY'
    assert len(env.calls) == 2 and env.calls[0] == env.calls[1]
    with env.store._connection() as conn:
        assert conn.execute('SELECT count(*) FROM pipeline_task_probe_evidence').fetchone()[0] == len(env.request.plan.required_targets)


def test_system_boundary_precedes_files_or_runtime(phase_env, monkeypatch):
    monkeypatch.setattr(owner.windows, 'require_system', lambda: (_ for _ in ()).throw(PermissionError('SYSTEM only')))
    with pytest.raises(PermissionError):
        invoke(phase_env)
    assert not list(phase_env.args[-1].iterdir()) and not phase_env.calls


def test_shutdown_failure_is_not_retried_or_claimed_clean(phase_env):
    env = phase_env
    closes = []
    def failed_close():
        assert (env.args[2], False) in env.held
        closes.append(True)
        raise RuntimeError('private cleanup detail')
    env.runtime.close = failed_close
    result = invoke(env)
    assert closes == [True]
    assert result['status'] == 'TASK_CATALOG_HELD_PRESERVE_EVIDENCE'
    assert result['phase'] == 'resource_drain'
    assert result['catalog_published'] is True and result['runtime_resources_closed'] is False
    assert result['cleanup_verified'] is False and not env.held


def test_expired_synchronous_probe_cannot_write_candidate_after_publication(phase_env, monkeypatch):
    env = phase_env
    def expired(rt, request):
        result = env.publish(rt, request)
        monkeypatch.setattr(owner.time, 'monotonic', lambda: 10**12)
        return result
    monkeypatch.setattr(owner, 'run_acceptance', expired)
    result = invoke(env)
    assert result['status'] == 'TASK_CATALOG_HELD_PRESERVE_EVIDENCE'
    assert result['catalog_published'] is True
    assert not (env.args[-1] / 'pipeline.json').exists()


def test_request_pin_mismatch_stops_before_acceptance_and_preserves_input(phase_env):
    env = phase_env
    original = env.args[2].read_bytes()
    env.args[3] = 'f' * 64
    result = invoke(env)
    assert result['status'] == 'TASK_CATALOG_HELD_PRESERVE_EVIDENCE'
    assert not env.calls and env.args[2].read_bytes() == original
    assert env.runtime.closed == 1 and not env.held


def test_exception_after_publication_never_claims_safe_old_catalog_restoration(phase_env, monkeypatch):
    env = phase_env
    def commit_then_fail(rt, request):
        env.publish(rt, request)
        raise RuntimeError('failed after durable catalog transaction')
    monkeypatch.setattr(owner, 'run_acceptance', commit_then_fail)
    result = invoke(env)
    assert result['status'] == 'TASK_CATALOG_HELD_PRESERVE_EVIDENCE'
    assert result['publication_state'] == 'COMMITTED' and result['catalog_published'] is True
    assert result['publication_proof']['committed_catalog_sha256']
    assert not (env.args[-1] / 'pipeline.json').exists()


def test_unreadable_publication_journal_is_unknown_not_safe_to_restore(phase_env, monkeypatch):
    env = phase_env
    monkeypatch.setattr(owner, 'publication_snapshot', lambda *args: dict(
        state='UNKNOWN', catalog_probe_cleanup_verified=False))
    result = invoke(env)
    assert result['status'] == 'TASK_CATALOG_HELD_PRESERVE_EVIDENCE'
    assert result['publication_state'] == 'UNKNOWN'
    assert not (env.args[-1] / 'result.json').exists()


@pytest.mark.parametrize('changed', [False, True])
def test_start_gate_binds_acknowledgment_before_runtime_creation(phase_env, monkeypatch, changed):
    env = phase_env
    original = owner.write_fresh
    def observed_write(path, record):
        raw = original(path, record)
        if path.name == 'phase-started.json':
            assert env.runtime.closed == 0 and not env.calls and not env.loads
            ack = dict(schema='cochem-owner-task-catalog-start-ack/4.2.8',
                start_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), pid=record['pid'],
                bootstrap_sha256=record['bootstrap_sha256'], request_sha256=record['request_sha256'])
            if changed:
                ack['pid'] += 1
            original(path.parent / 'phase-start-ack.json', ack)
        return raw
    monkeypatch.setattr(owner, 'write_fresh', observed_write)
    result = invoke(env, start_gate=True)
    assert result['status'] == ('TASK_CATALOG_HELD_PRESERVE_EVIDENCE' if changed else 'TASK_CATALOG_CANDIDATE_READY')
    if changed:
        assert not env.calls and not env.loads and env.runtime.closed == 0
        assert result['phase'] == 'process_custody'
        assert result['publication_state'] == 'UNKNOWN'


def test_missing_start_ack_has_a_bounded_wait_without_runtime(phase_env, monkeypatch):
    env = phase_env
    path = env.args[-1] / 'phase-started.json'
    record = dict(pid=123, bootstrap_sha256=env.args[1], request_sha256=env.args[3])
    owner.write_fresh(path, record)
    moments = iter([0, 91])
    monkeypatch.setattr(owner.time, 'monotonic', lambda: next(moments))
    with pytest.raises(TimeoutError, match='acknowledgment'):
        owner.wait_start_gate(env.args[-1], path, record)
    assert not env.calls and not env.loads
