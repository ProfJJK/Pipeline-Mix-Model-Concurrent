"""Inert policy regressions for the 2026-10-15 admission amendment.

All pressures are supplied fixtures, not native acceptance evidence. No provider,
system probe, service, process launch or host configuration is used here.
"""
from copy import deepcopy
from types import SimpleNamespace
import threading

import pytest

from cochem_pipeline import resource_telemetry
from cochem_pipeline.controller_guard import assess_controller
from cochem_pipeline.hardware_guard import GovernorState, HardwarePolicy, assess_resources
from pipeline_tests.test_hardware_guard import policy_case


@pytest.mark.parametrize('processors', [1, 4, 8, 16, 32])
@pytest.mark.parametrize('cores,ready', [(0.5, True), (0.8, True), (1.0, True), (1.001, False)])
def test_controller_budget_is_one_core_regardless_of_affinity_denominator(processors, cores, ready):
    result = assess_controller({'rss_mb': 80, 'cpu_percent': 100 * cores / processors,
                                'allowed_logical_processors': list(range(processors))})
    assert result['ready'] is ready
    assert result['cpu_core_equivalents'] == pytest.approx(cores)
    assert result['cpu_limit_percent'] == pytest.approx(100 / processors)
    assert result['cpu_limit_core_equivalents'] == 1
    assert result['cpu_target_core_equivalents'] == 0.5
    assert result['action'] != 'terminate_active'


@pytest.mark.parametrize('affinity', [None, [], [0, 0], [True], [-1], 'eight'])
def test_controller_percentage_without_valid_denominator_is_unavailable(affinity):
    result = assess_controller({'rss_mb': 80, 'cpu_percent': 1,
                                'allowed_logical_processors': affinity})
    assert result['ready'] is False
    assert result['cpu_core_equivalents'] is None
    assert result['reasons'] == ['Warden CPU utilization telemetry is unavailable']


@pytest.mark.parametrize('explicit', [None, False, float('nan'), -1, 0.1])
def test_conflicting_or_invalid_core_evidence_cannot_lower_the_gate(explicit):
    result = assess_controller({'rss_mb': 80, 'cpu_percent': 20, 'cpu_core_equivalents': explicit,
                                'allowed_logical_processors': list(range(8))})
    assert result['ready'] is False
    assert result['cpu_core_equivalents'] is None


def warmed_governor():
    policy = HardwarePolicy(recovery_seconds=2, recovery_samples=2, ramp_up_step=1)
    governor = GovernorState()
    healthy = assess_resources(policy_case(), policy)
    for second in range(9):
        governor.apply(healthy, policy, second)
    assert governor.capacity == 4
    return governor, policy, healthy


@pytest.mark.parametrize('pressure', ['cpu_pause', 'cpu_throttle', 'disk'])
def test_transient_cpu_and_disk_restore_previous_capacity_on_first_healthy_sample(pressure):
    governor, policy, healthy = warmed_governor()
    measured = policy_case()
    if pressure == 'disk':
        measured['disks']['io']['total_iops'] = 5000
    else:
        measured['cpu']['percent'] = 96 if pressure == 'cpu_pause' else 60
    decision = assess_resources(measured, policy)
    assert decision['transient_pressure'] is True
    assert decision['recovery_required'] is False
    paused = governor.apply(decision, policy, 9)
    assert paused['capacity'] == (2 if pressure == 'cpu_throttle' else 0)
    assert paused['action'] != 'terminate_active'
    assert paused['reasons']
    assert governor.apply(decision, policy, 10)['capacity'] == paused['capacity']
    restored = governor.apply(healthy, policy, 11)
    assert restored['capacity'] == 4
    assert restored['action'] == 'none'
    assert restored['transient_recovery_capacity'] is None


def test_consecutive_transient_reductions_preserve_the_established_plateau():
    governor, policy, healthy = warmed_governor()
    cpu = policy_case(); cpu['cpu']['percent'] = 60
    disk = policy_case(); disk['disks']['io']['total_mb_s'] = 121
    assert governor.apply(assess_resources(cpu, policy), policy, 9)['capacity'] == 2
    assert governor.apply(assess_resources(disk, policy), policy, 10)['capacity'] == 0
    assert governor.apply(assess_resources(cpu, policy), policy, 11)['capacity'] == 2
    assert governor.apply(healthy, policy, 12)['capacity'] == 4


@pytest.mark.parametrize('protective', ['memory', 'commit', 'temperature', 'missing_cpu', 'missing_io', 'sustained_cpu'])
def test_protective_pressure_invalidates_transient_resume_and_keeps_recovery(protective):
    governor, policy, healthy = warmed_governor()
    disk = policy_case(); disk['disks']['io']['total_iops'] = 5000
    assert governor.apply(assess_resources(disk, policy), policy, 9)['capacity'] == 0
    measured = policy_case()
    if protective == 'memory': measured['memory']['available_mb'] = 2000
    elif protective == 'commit': measured['commit']['free_mb'] = 1000
    elif protective == 'temperature': measured['cpu']['temperature_celsius'] = 90
    elif protective == 'missing_cpu': measured['cpu']['available'] = False
    elif protective == 'missing_io': measured['disks']['io']['available'] = False
    else: measured['cpu']['percent'] = 100
    decision = assess_resources(measured, policy)
    held = governor.apply(decision, policy, 10)
    if protective == 'sustained_cpu':
        assert held['action'] == 'pause_admission'
        held = governor.apply(decision, policy, 15)
        assert held['action'] == 'terminate_active'
    else:
        assert held['action'] == 'pause_admission'
    assert held['transient_recovery_capacity'] is None
    assert governor.apply(healthy, policy, 16)['capacity'] == 0
    assert governor.apply(healthy, policy, 18)['capacity'] == 1


def test_transient_at_startup_does_not_invent_previously_accepted_capacity():
    governor = GovernorState()
    policy = HardwarePolicy(recovery_seconds=2, recovery_samples=2)
    cpu = policy_case(); cpu['cpu']['percent'] = 96
    held = governor.apply(assess_resources(cpu, policy), policy, 0)
    assert held['capacity'] == 0 and held['transient_recovery_capacity'] is None
    healthy = assess_resources(policy_case(), policy)
    assert governor.apply(healthy, policy, 1)['capacity'] == 0
    assert governor.apply(healthy, policy, 3)['capacity'] == 1


@pytest.mark.parametrize('mutation', [
    ('cpu', 'percent', 40), ('cpu', 'count', 2), ('cpu', 'physical_count', 2),
    ('memory', 'available_mb', 15000), ('commit', 'free_mb', 6500)])
def test_every_partial_capacity_reduction_has_a_reason(mutation):
    section, field, value = mutation
    measured = policy_case(); measured[section][field] = value
    decision = assess_resources(measured, HardwarePolicy())
    assert 0 < decision['capacity'] < 4
    assert decision['reasons']


def test_telemetry_labels_host_percent_separately_from_affinity_seat_count(monkeypatch):
    monkeypatch.setattr(resource_telemetry.psutil, 'cpu_count', lambda logical=True: 32 if logical else 24)
    monkeypatch.setattr(resource_telemetry.psutil, 'Process', lambda: SimpleNamespace(cpu_affinity=lambda: list(range(24, 32))))
    monkeypatch.setattr(resource_telemetry.psutil, 'cpu_percent', lambda interval: 25.0)
    cpu = resource_telemetry._cpu(.05)
    assert cpu['available'] is True
    assert cpu['count'] == 8 and cpu['host_logical_count'] == 32
    assert cpu['percent'] == 25.0
    assert cpu['utilization_scope'] == 'host_all_logical_processors'
    assert cpu['capacity_scope'] == 'process_affinity'
    measured = policy_case(); measured['cpu'] = {**measured['cpu'], **cpu}
    measured['cpu'].update(temperature_available=True, temperature_celsius=50)
    assert assess_resources(measured, HardwarePolicy())['capacity'] == 4


def test_high_host_load_still_blocks_when_affinity_count_is_small(monkeypatch):
    monkeypatch.setattr(resource_telemetry.psutil, 'cpu_count', lambda logical=True: 32 if logical else 24)
    monkeypatch.setattr(resource_telemetry.psutil, 'Process', lambda: SimpleNamespace(cpu_affinity=lambda: [24, 25]))
    monkeypatch.setattr(resource_telemetry.psutil, 'cpu_percent', lambda interval: 96.0)
    measured = deepcopy(policy_case())
    measured['cpu'].update(resource_telemetry._cpu(.05), temperature_available=True, temperature_celsius=50)
    decision = assess_resources(measured, HardwarePolicy())
    assert decision['capacity'] == 0 and decision['action'] == 'pause_admission'
    assert any('Host CPU' in reason for reason in decision['reasons'])


@pytest.mark.parametrize('pressure', ['controller_cpu', 'host_cpu', 'disk', 'critical_memory'])
def test_runtime_admission_pause_preserves_active_work_and_emergency_still_terminates(pressure):
    from pipeline_tests.test_controller_guard import fake_monitor, tick_runtime, CPU_SPIKE

    monitor, at = fake_monitor()
    runtime, telemetry = tick_runtime(monitor)
    measured = policy_case()
    if pressure == 'controller_cpu': at(0, CPU_SPIKE)
    elif pressure == 'host_cpu': measured['cpu']['percent'] = 96
    elif pressure == 'disk': measured['disks']['io']['total_iops'] = 5000
    else: measured['memory']['available_mb'] = 100
    decision = assess_resources(measured, HardwarePolicy())
    runtime.guard = SimpleNamespace(evaluate=lambda: decision)
    runtime._terminate_fenced_attempts = lambda: None  # Admission-only boundary, no lease stimulus.
    cancelled = threading.Event()
    runtime.active = {'existing': {'slot': 'slot1', 'cancel_event': cancelled,
                                  'node': {'job_id': 'existing', 'attempt_id': 'attempt', 'fencing_token': 1}}}
    terminated, failed, capacities = [], [], []
    runtime.runner = SimpleNamespace(terminate=terminated.append)
    runtime.store.fail = lambda *args, **kwargs: failed.append((args, kwargs))
    runtime.admission = SimpleNamespace(update_capacity=capacities.append)
    runtime.tick()
    assert capacities == [0]
    assert list(runtime.active) == ['existing']
    if pressure == 'critical_memory':
        assert cancelled.is_set() and terminated == ['existing'] and len(failed) == 1
        assert telemetry[-1]['action'] == 'terminate_active'
    else:
        assert not cancelled.is_set() and terminated == [] and failed == []
        assert telemetry[-1]['action'] == 'pause_admission'


def test_owner_acceptance_tick_samples_guards_without_admitting_existing_jobs():
    from pipeline_tests.test_controller_guard import fake_monitor, tick_runtime
    monitor, _ = fake_monitor()
    runtime, telemetry = tick_runtime(monitor)
    capacities, maintenance = [], []
    runtime.admission = SimpleNamespace(update_capacity=capacities.append)
    runtime._container_maintenance = maintenance.append
    def forbidden(*args, **kwargs):
        raise AssertionError('Owner acceptance must not dispatch normal work or poll another catalog')
    runtime.catalog = SimpleNamespace(step=forbidden)
    runtime._planning_maintenance = forbidden
    runtime.store.claim = forbidden
    runtime.tick(admit_jobs=False, catalog_poll=False)
    assert capacities == [4] and maintenance == [4]
    assert telemetry[-1]['capacity'] == 4
    assert runtime.last_capacity == 4 and runtime.active == {}
