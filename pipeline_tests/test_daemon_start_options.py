"""Reboot-safe daemon start options (r5 addendum A2, requirement R1).

--queue-launch-output-root names a fresh child per start and --docker-wait-seconds
waits for the Docker preflight before Runtime exists. Everything here is
in-process: tmp_path directories, a fake clock, a fake Docker engine, and fake
Runtime/ControlServer/QueueLaunchObserver/Windows modules. No SYSTEM token,
Docker engine, scheduled task or real Runtime is touched.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import gc
import logging
import os
from pathlib import Path
import re
import signal
import sys
import threading
import types
from types import SimpleNamespace
import weakref

import pytest

from cochem_pipeline import __main__ as main_module
from cochem_pipeline import containers, crash, service
from pipeline_tests.windows_test_context import create_optional_symlink

LOGGER = 'cochem_pipeline.__main__'
ENGINE_DOWN = ('Docker inspection failed: error during connect: open //./pipe/docker_engine: '
               'The system cannot find the file specified.')
OUTSIDE = 'must lie inside the configured private_root'
REPARSE = 'must not be or pass through a reparse point'
MOMENT = datetime(2026, 10, 11, 0, 57, 3, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeEngine:
    """Docker engine that fails the first ``failures`` preflights (None: always)."""

    def __init__(self, events):
        self.events = events
        self.failures = 0
        self.preflights = 0
        self.constructed = []
        self.references = []
        self.construction_error = None

    def runner_class(self):
        engine = self

        class FakeDockerRunner:
            def __init__(self, policy, state_root, *, trusted_operator=None, host_boot_id=None):
                engine.events.append('runner')
                if engine.construction_error is not None:
                    raise engine.construction_error
                engine.constructed.append({'policy': policy, 'state_root': state_root,
                                           'trusted_operator': trusted_operator, 'host_boot_id': host_boot_id})
                engine.references.append(weakref.ref(self))

            def preflight(self):
                engine.preflights += 1
                engine.events.append('preflight')
                if engine.failures is None or engine.preflights <= engine.failures:
                    raise containers.ContainerError(ENGINE_DOWN)
                return {'ready': True}

        return FakeDockerRunner


@pytest.fixture
def harness(tmp_path, monkeypatch):
    private = tmp_path / 'private'
    private.mkdir()
    token = tmp_path / 'token.txt'
    token.write_text('test-token\n', encoding='utf-8')
    state = SimpleNamespace(tmp=tmp_path, private=private, events=[], runtimes=[], servers=[],
                            observers=[], crashes=[], clock=FakeClock())
    state.config = SimpleNamespace(private_root=private, token_file=token, operator_name='owner',
                                   workers={}, docker=SimpleNamespace(enabled=True))
    state.engine = FakeEngine(state.events)
    monkeypatch.setattr(containers, 'DockerRunner', state.engine.runner_class())
    monkeypatch.setattr(main_module, '_monotonic', state.clock.monotonic)
    monkeypatch.setattr(main_module, '_sleep', state.clock.sleep)

    class FakeRuntime:
        def __init__(self, config):
            gc.collect()
            self.probe_runners_alive = sum(ref() is not None for ref in state.engine.references)
            state.events.append('runtime')
            state.runtimes.append(self)
            self.config = config
            self.stop_event = threading.Event()
            self.runs = 0
            if config.docker.enabled:
                # Mirrors runtime.py: the same runner, then the same preflight.
                containers.DockerRunner(config.docker, config.private_root / 'containers',
                                        trusted_operator=config.operator_name).preflight()

        def run(self):
            self.runs += 1

    class FakeServer:
        def __init__(self, runtime, token_text):
            self.token_text = token_text
            self.closed = threading.Event()
            state.servers.append(self)

        def serve_forever(self):
            self.closed.wait(10)

        def shutdown(self):
            self.closed.set()

        def server_close(self):
            pass

    class FakeObserver:
        def __init__(self, runtime, output):
            self.runtime, self.output = runtime, Path(output)
            state.observers.append(self)

        def __enter__(self):
            # The real observer refuses a pre-existing directory the same way.
            self.output.mkdir(exist_ok=False)
            return self

        def __exit__(self, *_):
            return False

    @contextmanager
    def fake_lock(path):
        yield

    fake_runtime = types.ModuleType('cochem_pipeline.runtime')
    fake_runtime.Runtime = FakeRuntime
    fake_windows = types.ModuleType('cochem_pipeline.windows')
    fake_windows.WorkerIdentity = lambda **values: values
    fake_windows.require_system = lambda: None
    fake_windows.validate_private_directory = lambda path: None
    fake_windows.validate_controller_token = lambda *args, **kwargs: None
    fake_queue = types.ModuleType('cochem_pipeline.queue_launch')
    fake_queue.QueueLaunchObserver = FakeObserver
    monkeypatch.setitem(sys.modules, 'cochem_pipeline.runtime', fake_runtime)
    monkeypatch.setitem(sys.modules, 'cochem_pipeline.windows', fake_windows)
    monkeypatch.setitem(sys.modules, 'cochem_pipeline.queue_launch', fake_queue)
    monkeypatch.setattr(service, 'ControlServer', FakeServer)
    monkeypatch.setattr(crash, 'record_crash',
                        lambda root, error, category='code': state.crashes.append((error, category)))
    monkeypatch.setattr(main_module, 'load_config', lambda filename: state.config)
    monkeypatch.setattr(main_module, 'service_lock', fake_lock)
    monkeypatch.setattr(main_module, 'RotatingFileHandler', lambda *args, **kwargs: logging.NullHandler())
    monkeypatch.setattr(signal, 'signal', lambda *args: None)
    root_logger = logging.getLogger()
    before = list(root_logger.handlers)
    yield state
    for handler in list(root_logger.handlers):
        if handler not in before:
            root_logger.removeHandler(handler)
            handler.close()


def _warnings(caplog):
    return [record.getMessage() for record in caplog.records
            if record.name == LOGGER and record.levelno == logging.WARNING]


def _run_main(monkeypatch, *argv):
    calls = []
    monkeypatch.setattr(main_module, 'daemon', lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(logging, 'basicConfig', lambda **kwargs: None)
    monkeypatch.setattr(sys, 'argv', ['cochem_pipeline', *argv])
    main_module.main()
    return calls


# --- command line -----------------------------------------------------------

def test_daemon_defaults_keep_todays_call(monkeypatch):
    assert _run_main(monkeypatch, 'daemon', '--config', 'pipeline.json') == [
        (('pipeline.json',), {'queue_launch_output': None, 'queue_launch_output_root': None,
                              'docker_wait_seconds': 0})]


def test_r5_task_action_arguments_parse(monkeypatch):
    calls = _run_main(monkeypatch, 'daemon', '--config', r'D:\staged\pipeline.json',
                      '--queue-launch-output-root', r'D:\private\queue-launch-r5', '--docker-wait-seconds', '900')
    assert calls == [((r'D:\staged\pipeline.json',), {'queue_launch_output': None,
                      'queue_launch_output_root': r'D:\private\queue-launch-r5', 'docker_wait_seconds': 900})]
    legacy = _run_main(monkeypatch, 'daemon', '--config', 'c.json', '--queue-launch-output', r'D:\private\q-v1')
    assert legacy == [(('c.json',), {'queue_launch_output': r'D:\private\q-v1', 'queue_launch_output_root': None,
                                     'docker_wait_seconds': 0})]


def test_queue_launch_output_options_are_mutually_exclusive(monkeypatch, capsys):
    with pytest.raises(SystemExit) as raised:
        _run_main(monkeypatch, 'daemon', '--config', 'c.json', '--queue-launch-output', 'a',
                  '--queue-launch-output-root', 'b')
    assert raised.value.code == 2
    assert ('argument --queue-launch-output-root: not allowed with argument --queue-launch-output'
            in capsys.readouterr().err)


def test_daemon_refuses_both_queue_options_before_any_work(harness):
    with pytest.raises(ValueError, match='--queue-launch-output and --queue-launch-output-root are mutually exclusive'):
        main_module.daemon('c.json', queue_launch_output=harness.private / 'a',
                           queue_launch_output_root=harness.private / 'b')
    assert harness.events == [] and harness.crashes == [] and list(harness.private.iterdir()) == []


@pytest.mark.parametrize('value', ['-1', 'soon', '1.5'])
def test_docker_wait_seconds_must_be_a_non_negative_whole_number(monkeypatch, capsys, value):
    with pytest.raises(SystemExit) as raised:
        _run_main(monkeypatch, 'daemon', '--config', 'c.json', '--docker-wait-seconds', value)
    assert raised.value.code == 2
    assert (f"argument --docker-wait-seconds: must be a whole number of seconds >= 0, got '{value}'"
            in capsys.readouterr().err)


@pytest.mark.parametrize('value', [-5, True, 1.5])
def test_daemon_refuses_an_invalid_wait_before_any_work(harness, value):
    with pytest.raises(ValueError, match='--docker-wait-seconds must be a whole number of seconds >= 0'):
        main_module.daemon('c.json', docker_wait_seconds=value)
    assert harness.events == [] and harness.crashes == []


# --- queue launch output root -----------------------------------------------

def test_child_is_named_utc_stamp_dash_pid_and_root_is_created(tmp_path):
    private = tmp_path / 'private'
    private.mkdir()
    root = private / 'queue-launch-r5'
    child = main_module.queue_launch_output_child(root, private, now=MOMENT, pid=20664)
    assert child == root / '20261011T005703Z-20664'
    assert root.is_dir() and not child.exists()
    plus_two = MOMENT.astimezone(timezone(timedelta(hours=2)))
    assert main_module.queue_launch_output_child(root, private, now=plus_two, pid=7).name == '20261011T005703Z-7'
    nested = private / 'evidence' / 'queue-launch-r5'
    assert main_module.queue_launch_output_child(nested, private, now=MOMENT, pid=7) == nested / '20261011T005703Z-7'
    assert nested.is_dir()
    default = main_module.queue_launch_output_child(root, private)
    assert default.parent == root
    assert re.fullmatch(r'\d{8}T\d{6}Z-%d' % os.getpid(), default.name)


def test_child_is_fresh_per_start_and_an_existing_child_is_refused(tmp_path):
    private = tmp_path / 'private'
    private.mkdir()
    root = private / 'queue-launch-r5'
    first = main_module.queue_launch_output_child(root, private, now=MOMENT, pid=100)
    assert first != main_module.queue_launch_output_child(root, private, now=MOMENT, pid=101)
    assert first != main_module.queue_launch_output_child(root, private, now=MOMENT + timedelta(seconds=1), pid=100)
    first.mkdir()
    (first / 'report.json').write_text('{}', encoding='utf-8')
    with pytest.raises(FileExistsError, match='Queue launch evidence directory already exists'):
        main_module.queue_launch_output_child(root, private, now=MOMENT, pid=100)
    assert (first / 'report.json').read_text(encoding='utf-8') == '{}'


@pytest.mark.parametrize('relative', ['elsewhere/queue', '.', 'private', 'private/../sibling'])
def test_root_outside_private_root_is_refused(tmp_path, relative):
    private = tmp_path / 'private'
    private.mkdir()
    root = tmp_path / relative
    with pytest.raises(ValueError, match=OUTSIDE):
        main_module.queue_launch_output_child(root, private, now=MOMENT, pid=1)
    assert not (tmp_path / 'elsewhere').exists() and not (tmp_path / 'sibling').exists()
    assert list(private.iterdir()) == []


def test_root_that_is_a_file_is_refused(tmp_path):
    private = tmp_path / 'private'
    private.mkdir()
    (private / 'queue-launch-r5').write_text('not a directory', encoding='utf-8')
    with pytest.raises(FileExistsError):
        main_module.queue_launch_output_child(private / 'queue-launch-r5', private, now=MOMENT, pid=1)


@pytest.mark.skipif(os.name != 'nt', reason='Junctions are a Windows reparse point')
@pytest.mark.parametrize('layout', ['root', 'ancestor', 'outside'])
def test_reparse_root_or_ancestor_is_refused(tmp_path, layout):
    import _winapi
    private = tmp_path / 'private'
    inside, outside = private / 'real', tmp_path / 'outside'
    inside.mkdir(parents=True)
    outside.mkdir()
    junction = private / 'link'
    _winapi.CreateJunction(str(outside if layout == 'outside' else inside), str(junction))
    try:
        root = junction / 'queue' if layout == 'ancestor' else junction
        with pytest.raises(ValueError, match=REPARSE):
            main_module.queue_launch_output_child(root, private, now=MOMENT, pid=1)
        assert list(inside.iterdir()) == [] and list(outside.iterdir()) == []
    finally:
        os.rmdir(junction)


def test_symbolic_link_root_is_refused(tmp_path):
    private = tmp_path / 'private'
    target = private / 'real'
    target.mkdir(parents=True)
    create_optional_symlink(private / 'link', target, directory=True)
    try:
        with pytest.raises(ValueError, match=REPARSE):
            main_module.queue_launch_output_child(private / 'link', private, now=MOMENT, pid=1)
        assert list(target.iterdir()) == []
    finally:
        if os.name == 'nt':
            os.rmdir(private / 'link')  # removes only the directory link
        else:
            (private / 'link').unlink()


def test_daemon_passes_a_fresh_child_to_the_observer_on_every_start(harness, monkeypatch):
    moments = iter([MOMENT, MOMENT + timedelta(seconds=61)])
    monkeypatch.setattr(main_module, '_utcnow', lambda: next(moments))
    root = harness.private / 'queue-launch-r5'
    for _ in range(2):
        main_module.daemon('c.json', queue_launch_output_root=root)
    expected = [root / f'20261011T005703Z-{os.getpid()}', root / f'20261011T005804Z-{os.getpid()}']
    assert [observer.output for observer in harness.observers] == expected
    assert all(path.is_dir() for path in expected)
    assert [runtime.runs for runtime in harness.runtimes] == [1, 1]
    assert harness.crashes == []


def test_daemon_legacy_queue_output_is_passed_unchanged(harness):
    output = harness.private / 'queue-retarget-r4-v2'
    main_module.daemon('c.json', queue_launch_output=output)
    assert [observer.output for observer in harness.observers] == [output] and output.is_dir()
    assert [runtime.runs for runtime in harness.runtimes] == [1]


def test_daemon_refuses_an_outside_root_before_waiting_or_constructing_runtime(harness):
    with pytest.raises(ValueError, match=OUTSIDE) as raised:
        main_module.daemon('c.json', queue_launch_output_root=harness.tmp / 'elsewhere', docker_wait_seconds=900)
    assert harness.events == [] and harness.runtimes == [] and harness.observers == []
    assert harness.crashes == [(raised.value, 'code')]
    assert not (harness.tmp / 'elsewhere').exists()


# --- Docker wait --------------------------------------------------------------

@pytest.mark.parametrize('failures,sleeps', [(0, []), (1, [5]), (3, [5, 10, 20])])
def test_wait_succeeds_after_k_failures(harness, caplog, failures, sleeps):
    caplog.set_level(logging.INFO, logger=LOGGER)
    harness.engine.failures = failures
    assert main_module.wait_for_docker(harness.config, 900) is True
    assert harness.engine.preflights == failures + 1
    assert harness.clock.sleeps == sleeps
    assert harness.engine.constructed == [{'policy': harness.config.docker, 'state_root': harness.private / 'containers',
                                           'trusted_operator': 'owner', 'host_boot_id': None}]
    elapsed = [0, 5, 15, 35]
    assert _warnings(caplog) == [
        f'Docker engine not ready: preflight try {index + 1} failed after {elapsed[index]} of 900 s '
        f'(retrying in {sleeps[index]} s): ContainerError: {ENGINE_DOWN}' for index in range(failures)]
    gc.collect()
    assert all(ref() is None for ref in harness.engine.references)


def test_wait_backoff_doubles_to_30_seconds_and_never_sleeps_past_the_deadline(harness, caplog):
    harness.engine.failures = None
    assert main_module.wait_for_docker(harness.config, 120) is False
    assert harness.clock.sleeps == [5, 10, 20, 30, 30, 25]
    assert harness.clock.now == 1120.0 and harness.engine.preflights == 7
    messages = _warnings(caplog)
    assert len(messages) == 7
    assert messages[-1] == ('Docker engine not ready: preflight try 7 failed after 120 of 120 s '
                            '(giving up; Runtime starts as without --docker-wait-seconds): '
                            f'ContainerError: {ENGINE_DOWN}')


def test_wait_is_skipped_when_docker_is_disabled(harness, caplog):
    harness.config.docker.enabled = False
    assert main_module.wait_for_docker(harness.config, 900) is False
    assert harness.events == [] and harness.clock.sleeps == [] and _warnings(caplog) == []


def test_runner_preparation_failure_leaves_the_failure_to_runtime(harness, caplog):
    harness.engine.construction_error = containers.ContainerError('state root is not ordinary')
    assert main_module.wait_for_docker(harness.config, 900) is False
    assert harness.engine.preflights == 0 and harness.clock.sleeps == []
    assert _warnings(caplog) == ['Docker wait skipped: the Docker runner could not be prepared '
                                 '(ContainerError: state root is not ordinary); '
                                 'Runtime starts as without --docker-wait-seconds']


def test_daemon_waits_before_constructing_runtime_exactly_once(harness, caplog):
    harness.engine.failures = 2
    main_module.daemon('c.json', docker_wait_seconds=900)
    assert harness.events == ['runner', 'preflight', 'preflight', 'preflight', 'runtime', 'runner', 'preflight']
    assert len(harness.runtimes) == 1 and harness.runtimes[0].runs == 1
    assert harness.runtimes[0].probe_runners_alive == 0
    assert harness.clock.sleeps == [5, 10] and harness.crashes == []
    assert len(_warnings(caplog)) == 2


def test_wait_timeout_fails_exactly_as_today(harness, caplog):
    harness.engine.failures = None
    with pytest.raises(containers.ContainerError) as today:
        main_module.daemon('c.json')
    assert harness.events == ['runtime', 'runner', 'preflight']
    today_crashes = list(harness.crashes)
    harness.events.clear()
    harness.crashes.clear()
    harness.runtimes.clear()
    with pytest.raises(containers.ContainerError) as waited:
        main_module.daemon('c.json', docker_wait_seconds=60)
    assert (type(waited.value), str(waited.value)) == (type(today.value), str(today.value)) == (
        containers.ContainerError, ENGINE_DOWN)
    assert today_crashes == [(today.value, 'code')] and harness.crashes == [(waited.value, 'code')]
    assert harness.events == ['runner'] + ['preflight'] * 5 + ['runtime', 'runner', 'preflight']
    assert len(harness.runtimes) == 1 and harness.runtimes[0].runs == 0
    assert harness.clock.sleeps == [5, 10, 20, 25] and harness.servers == []
    assert _warnings(caplog)[-1].startswith('Docker engine not ready: preflight try 5 failed after 60 of 60 s (giving up')


def test_zero_wait_never_calls_the_wait_path(harness, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('the Docker wait path must not run when N == 0')
    monkeypatch.setattr(main_module, 'wait_for_docker', forbidden)
    monkeypatch.setattr(main_module, '_monotonic', forbidden)
    monkeypatch.setattr(main_module, '_sleep', forbidden)
    main_module.daemon('c.json')
    main_module.daemon('c.json', docker_wait_seconds=0)
    assert harness.events == ['runtime', 'runner', 'preflight'] * 2
    assert [runtime.runs for runtime in harness.runtimes] == [1, 1] and harness.crashes == []
