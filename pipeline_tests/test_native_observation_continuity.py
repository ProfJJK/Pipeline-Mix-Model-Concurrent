"""Disposable clock/process fixtures, not physical SYSTEM or 48-hour evidence."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from cochem_pipeline import controller_guard
from cochem_pipeline import performance_acceptance as perf
from cochem_pipeline import windows as win
from cochem_pipeline.controller_guard import WARDEN_CPU_LIMIT_CORES, WARDEN_MEMORY_LIMIT_MB


class Clock:
    def __init__(self):
        self.wall = 1000000.0
        self.mono = 0.0
        self.sleeps = 0
        self.after_sleep = lambda clock: None

    def sleep(self, seconds):
        self.wall += seconds
        self.mono += seconds
        self.sleeps += 1
        self.after_sleep(self)


@pytest.fixture
def observation(monkeypatch, tmp_path):
    """Only the explicit native boundaries are replaced; real observer/file I/O."""
    clock = Clock()
    current = SimpleNamespace(created=900000.0, sequence=0, after_handles=lambda: None, rss_mb=8, cpu=1.0,
                              cpu_seconds=0.0, cpu_read_at=0.0, affinity=[0, 1])
    heartbeat = tmp_path / 'heartbeat.json'
    heap_path = tmp_path / 'heap.json'
    output = tmp_path / 'observation'

    class Process:
        def __init__(self, pid):
            self.pid = pid
            # Match psutil create_time caching: a fresh Process is necessary
            # to detect reuse after the observer selected its initial object.
            self.created = current.created

        def username(self):
            return r'NT AUTHORITY\SYSTEM'

        def exe(self):
            return str(tmp_path / 'fixture-only-python.exe')

        def create_time(self):
            return self.created

        def cpu_times(self):
            current.cpu_seconds += (clock.mono-current.cpu_read_at)*current.cpu/100
            current.cpu_read_at = clock.mono
            return SimpleNamespace(user=current.cpu_seconds, system=0.0)

        def num_handles(self):
            current.after_handles()
            return 12

        def memory_info(self):
            return SimpleNamespace(rss=current.rss_mb*1048576)

        def cpu_affinity(self):
            return current.affinity

    original_read = perf._read_object

    def read(path, maximum=1048576):
        if path == heartbeat:
            current.sequence += 1
            return {'pid':1234, 'instance_id':'fixture-instance',
                    'sequence':current.sequence, 'timestamp':clock.wall}
        return original_read(path, maximum)

    def publish_heap():
        heap_path.write_text(json.dumps({'pid':1234,
            'process_created_at':900000.0, 'measured_at':clock.wall,
            'used_bytes':140, 'allocation_limit_bytes':1000,
            'source':'synthetic-fixture-NOT-native-evidence'}), encoding='utf-8')

    clock.after_sleep = lambda clock: publish_heap()
    publish_heap()
    monkeypatch.setattr(perf.psutil, 'Process', Process)
    monkeypatch.setattr(perf.time, 'time', lambda: clock.wall)
    monkeypatch.setattr(perf.time, 'monotonic', lambda: clock.mono)
    monkeypatch.setattr(perf.time, 'sleep', clock.sleep)
    monkeypatch.setattr(perf, '_read_object', read)
    monkeypatch.setattr(perf, '_supervisor_timing', lambda *args: {
        'monitor_passed':True, 'recovery_passed':True})
    for name in ('require_system','validate_private_path','validate_private_directory','validate_code_path'):
        monkeypatch.setattr(win, name, lambda *args: None)

    def run(duration=1, interval=1, heap=True):
        return perf.observe_native(heartbeat, output, duration_seconds=duration,
            interval_seconds=interval, desktop_heap_report=heap_path if heap else None)

    return SimpleNamespace(clock=clock, current=current, run=run, output=output,
                           heap_path=heap_path, publish_heap=publish_heap, read=read)


def test_short_observation_retains_actual_measurement_fields_without_48h_claim(observation):
    result = observation.run()
    row = json.loads((observation.output / 'native-samples.jsonl').read_text())
    assert result['passed'] is False and result['continuous_48h_complete'] is False
    assert result['continuity']['passed'] is True
    assert row['process_created_at'] == 900000.0
    assert row['instance_id'] == 'fixture-instance'
    assert row['desktop_heap'] == {
        'available':True, 'passed':True, 'percent':14.0,
        'used_bytes':140, 'allocation_limit_bytes':1000,
        'measured_at':1000001.0, 'pid':1234, 'process_created_at':900000.0,
        'source':'synthetic-fixture-NOT-native-evidence',
        'measurement_scope':'external native diagnostic; this harness does not generate used-byte evidence'}


def test_synthetic_complete_run_requires_all_17280_fresh_samples(observation, monkeypatch):
    # Fast disposable simulation, never labelled actual elapsed Windows proof.
    template = json.loads(observation.heap_path.read_text())
    observation.clock.after_sleep = lambda clock: None

    def read(path, maximum=1048576):
        if path == observation.heap_path:
            return dict(template, measured_at=observation.clock.wall)
        return observation.read(path, maximum)

    monkeypatch.setattr(perf, '_read_object', read)
    result = observation.run(duration=172800, interval=10)
    assert result['passed'] is True
    assert result['sample_count'] == 17280
    assert result['continuous_48h_complete'] is True
    assert result['continuity']['maximum_monotonic_gap_seconds'] == 10
    assert result['continuity']['last_observed_elapsed_seconds'] == 172800


@pytest.mark.parametrize('sleep_number', [1, 2])
def test_fresh_heap_after_48h_sleep_cannot_certify_continuity(observation, sleep_number):
    def after_sleep(clock):
        if clock.sleeps == sleep_number:
            clock.wall += 172800
            clock.mono += 172800
        observation.publish_heap()
    observation.clock.after_sleep = after_sleep
    result = observation.run(duration=172800)
    assert result['elapsed_seconds'] >= 172800
    assert result['continuous_48h_complete'] is False
    assert result['passed'] is False
    assert result['sample_count'] == sleep_number-1
    if sleep_number == 1:
        assert result['desktop_heap'] == {'available':False, 'passed':False}
    assert 'Continuous observation lost' in result['error']


@pytest.mark.parametrize('wall_delta,mono_delta', [(20,0),(0,20),(-2,0),(0,-2)])
def test_either_clock_gap_or_reversal_holds_without_counting_sample(observation, wall_delta, mono_delta):
    def after_sleep(clock):
        clock.wall += wall_delta
        clock.mono += mono_delta
        observation.publish_heap()
    observation.clock.after_sleep = after_sleep
    result = observation.run()
    assert result['passed'] is False and result['sample_count'] == 0
    assert result['continuity']['passed'] is False


def test_native_read_delay_is_included_in_gap(observation):
    observation.current.after_handles = lambda: observation.clock.sleep(11)
    result = observation.run()
    assert result['sample_count'] == 0 and result['passed'] is False
    assert result['continuity']['maximum_monotonic_gap_seconds'] == 12


def test_heap_read_delay_is_included_in_gap(observation, monkeypatch):
    def delayed(path, maximum=1048576):
        value = observation.read(path, maximum)
        if path == observation.heap_path:
            observation.clock.sleep(11)
        return value
    monkeypatch.setattr(perf, '_read_object', delayed)
    result = observation.run()
    assert result['sample_count'] == 0
    assert 'Continuous observation lost' in result['error']


def test_heap_age_checked_after_file_read(observation, monkeypatch):
    def delayed(path, maximum=1048576):
        value = observation.read(path, maximum)
        if path == observation.heap_path:
            value['measured_at'] -= 9
            observation.clock.sleep(2)
        return value
    monkeypatch.setattr(perf, '_read_object', delayed)
    result = observation.run()
    assert result['sample_count'] == 0 and result['passed'] is False
    assert 'became stale' in result['error']


@pytest.mark.parametrize('when', ['before', 'during'])
def test_cached_process_creation_cannot_hide_pid_reuse(observation, when):
    def restart():
        observation.current.created += 1
    if when == 'before':
        observation.clock.after_sleep = lambda clock: restart()
    else:
        observation.current.after_handles = restart
    result = observation.run()
    assert result['sample_count'] == 0 and result['passed'] is False
    assert 'Warden restarted' in result['error']


@pytest.mark.parametrize('rss_mb,cpu,passed', [
    # Process CPU 100% is one core, irrespective of affinity count.
    (WARDEN_MEMORY_LIMIT_MB, 100*WARDEN_CPU_LIMIT_CORES, True),
    (51, 1.0, True),  # Above the superseded 50 MiB literal, inside the owner-amended budget.
    (WARDEN_MEMORY_LIMIT_MB+1, 1.0, False),
    (8, 100*WARDEN_CPU_LIMIT_CORES+.2, False)])
def test_controller_verdict_uses_the_warden_budget_constants(observation, rss_mb, cpu, passed):
    observation.current.rss_mb, observation.current.cpu = rss_mb, cpu
    result = observation.run()
    assert result['sample_count'] == 1
    assert (result['controller']['maximum_rss_mb'], result['controller']['maximum_cpu_percent']) == (rss_mb, cpu/2)
    assert result['controller']['passed'] is passed
    # The harness reads the Warden's own budget, not a copied literal.
    assert result['controller']['maximum_cpu_core_equivalents'] == pytest.approx(cpu/100)
    assert (perf.WARDEN_MEMORY_LIMIT_MB, perf.WARDEN_CPU_LIMIT_CORES) == (
        controller_guard.WARDEN_MEMORY_LIMIT_MB, controller_guard.WARDEN_CPU_LIMIT_CORES)


@pytest.mark.parametrize('processors', [2, 8, 32])
def test_observer_core_budget_does_not_change_with_affinity(observation, processors):
    observation.current.affinity = list(range(processors))
    observation.current.cpu = 100.0
    result = observation.run()
    row = json.loads((observation.output/'native-samples.jsonl').read_text())
    assert result['controller']['passed'] is True
    assert result['controller']['maximum_cpu_core_equivalents'] == 1
    assert row['cpu_percent'] == pytest.approx(100/processors)
    assert row['cpu_limit_percent'] == pytest.approx(100/processors)
    assert row['allowed_logical_processors'] == list(range(processors))


def test_observer_uses_the_rolling_window_for_a_short_cpu_burst(observation):
    observation.current.cpu = 50.0
    def after_sleep(clock):
        observation.current.cpu = 200.0 if clock.sleeps == 11 else 50.0
        observation.publish_heap()
    observation.clock.after_sleep = after_sleep
    result = observation.run(duration=12)
    rows = [json.loads(line) for line in (observation.output/'native-samples.jsonl').read_text().splitlines()]
    assert rows[10]['cpu_window_seconds'] == 10
    assert rows[10]['cpu_core_equivalents'] == pytest.approx(.65)
    assert result['controller']['maximum_cpu_core_equivalents'] == pytest.approx(.65)
    assert result['controller']['passed'] is True


def test_observer_refuses_missing_affinity_evidence(observation):
    observation.current.affinity = []
    result = observation.run()
    assert result['passed'] is False and result['sample_count'] == 0
    assert 'Controller rolling CPU measurement is unavailable' in result['error']


def test_missing_heap_source_stays_explicit(observation):
    result = observation.run(heap=False)
    row = json.loads((observation.output / 'native-samples.jsonl').read_text())
    assert result['desktop_heap'] == {'available':False, 'passed':False}
    assert row['desktop_heap']['available'] is False
    assert 'used_bytes' not in row['desktop_heap']


@pytest.mark.parametrize('field,value', [('used_bytes',150),('used_bytes',151)])
def test_exact_15_percent_or_higher_never_passes(tmp_path, field, value):
    path = tmp_path/'heap.json'
    data = {'pid':1234,'process_created_at':900.0,'measured_at':1000.0,
            'used_bytes':140,'allocation_limit_bytes':1000,'source':'fixture'}
    data[field] = value
    path.write_text(json.dumps(data))
    assert perf.desktop_heap_evidence(path,pid=1234,created_at=900.0,now=1000.0)['passed'] is False


@pytest.mark.parametrize('field,value', [
    ('pid',True),('pid',1235),('process_created_at',901.0),
    ('measured_at',989.9),('measured_at',1000.1),('used_bytes',float('nan')),
    ('used_bytes',True),('allocation_limit_bytes',0),('source','')])
def test_bad_native_measurement_is_refused(tmp_path, field, value):
    path = tmp_path/'heap.json'
    data = {'pid':1234,'process_created_at':900.0,'measured_at':1000.0,
            'used_bytes':140,'allocation_limit_bytes':1000,'source':'fixture'}
    data[field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        perf.desktop_heap_evidence(path,pid=1234,created_at=900.0,now=1000.0)
