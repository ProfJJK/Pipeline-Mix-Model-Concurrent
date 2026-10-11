"""Real controller measurements, recovery hysteresis and separate native scheduling acceptance."""
import itertools
import json
import os
import subprocess
import sys
import threading
from types import SimpleNamespace

import psutil
import pytest

from cochem_pipeline.controller_guard import (WARDEN_CPU_LIMIT_PERCENT, WARDEN_MEMORY_LIMIT_MB,
                                              ControllerMonitor, assess_controller)
from cochem_pipeline.hardware_guard import HardwarePolicy
from cochem_pipeline.resource_limits import ResourceLimits, ResourcePolicyError, controller_limits

# Explicit sample fixtures for the fake sampler; they are not live measurements.
OVER = {'rss_mb':WARDEN_MEMORY_LIMIT_MB+1,'cpu_percent':1}
HEALTHY = {'rss_mb':40,'cpu_percent':1}
CPU_SPIKE = {'rss_mb':40,'cpu_percent':WARDEN_CPU_LIMIT_PERCENT+1}


@pytest.mark.parametrize('rss,cpu,ready',[(WARDEN_MEMORY_LIMIT_MB,WARDEN_CPU_LIMIT_PERCENT,True),
                                        (WARDEN_MEMORY_LIMIT_MB+.001,0,False),(1,WARDEN_CPU_LIMIT_PERCENT+.001,False),
                                        (None,1,False),(1,None,False),(float('nan'),0,False)])
def test_strict_warden_budgets_never_report_ready_for_missing_or_excess_measurements(rss,cpu,ready):
    result=assess_controller({'rss_mb':rss,'cpu_percent':cpu})
    assert result['ready'] is ready
    assert result['strict_srs_ready'] is ready
    assert result['action']==('none' if ready else 'pause_admission')


def test_owner_amended_warden_memory_budget_is_200_mib_and_cpu_stays_5_percent():
    assert (WARDEN_MEMORY_LIMIT_MB,WARDEN_CPU_LIMIT_PERCENT)==(200,5)
    result=assess_controller({'rss_mb':WARDEN_MEMORY_LIMIT_MB+1,'cpu_percent':0})
    assert result['reasons']==['Warden resident memory exceeds its strict 200 MiB budget']
    assert (result['memory_limit_mb'],result['cpu_limit_percent'])==(WARDEN_MEMORY_LIMIT_MB,WARDEN_CPU_LIMIT_PERCENT)
    # Allocator high-water just above the former literal no longer closes admission.
    assert assess_controller({'rss_mb':54,'cpu_percent':1})['ready'] is True


def test_monitor_reports_actual_current_process_and_bounded_scope():
    monitor=ControllerMonitor()
    measured=monitor.sample(force=True)
    assert measured['measurements']['pid']==os.getpid()
    assert measured['measurements']['rss_mb']>0
    assert measured['measurements']['allowed_logical_processors']==psutil.Process().cpu_affinity()
    assert measured['measurements']['cpu_percent']>=0
    assert monitor.sample() is measured
    assert measured['ready']==(measured['measurements']['rss_mb']<=WARDEN_MEMORY_LIMIT_MB
                               and measured['measurements']['cpu_percent']<=WARDEN_CPU_LIMIT_PERCENT)
    # A first sample is never held by an earlier violation.
    assert measured['admission_ready'] is measured['ready']


def test_full_runtime_import_has_a_measured_idle_budget_in_fresh_process():
    result=subprocess.run([sys.executable,'-I','-c',
        'import cochem_pipeline.runtime; from cochem_pipeline.controller_guard import ControllerMonitor; '
        'import json; print(json.dumps(ControllerMonitor().sample(force=True)))'],
        capture_output=True,text=True,timeout=15,check=True)
    observed=json.loads(result.stdout)
    assert observed['measurements']['rss_mb']>0
    assert observed['ready']==(observed['measurements']['rss_mb']<=WARDEN_MEMORY_LIMIT_MB
                              and observed['measurements']['cpu_percent']<=WARDEN_CPU_LIMIT_PERCENT)


def fake_monitor(**policy):
    """A monitor driven by an explicit fake clock and sampler, not by psutil."""
    clock=SimpleNamespace(now=1000.)
    reading={'value':HEALTHY}
    monitor=ControllerMonitor(**policy,clock=lambda: clock.now,measure=lambda: dict(reading['value']))

    def at(seconds,value):
        clock.now=1000.+seconds
        reading['value']=value
        return monitor.sample()
    return monitor,at


def test_violation_pauses_on_the_same_sample_and_recovery_needs_ten_seconds_and_three_samples():
    monitor,at=fake_monitor()
    assert at(0,HEALTHY)['admission_ready'] is True
    paused=at(1,OVER)
    assert (paused['ready'],paused['admission_ready'],paused['recovery_hold'])==(False,False,True)
    assert paused['action']=='pause_admission'
    assert paused['admission_reasons']==paused['reasons']
    for second in (2,3):
        held=at(second,HEALTHY)
        assert (held['ready'],held['admission_ready'],held['recovery_hold'])==(True,False,True)
        assert held['strict_srs_ready'] is True and held['action']=='pause_admission'
        assert 'recovery hysteresis' in held['admission_reasons'][0]
    # Three samples are reached, but not ten healthy seconds since the first one (t=2).
    for second in range(4,12):
        assert at(second,HEALTHY)['admission_ready'] is False
    released=at(12,HEALTHY)
    assert (released['admission_ready'],released['recovery_hold'],released['action'])==(True,False,'none')
    assert released['admission_reasons']==[]


def test_recovery_needs_three_consecutive_samples_even_after_ten_seconds():
    monitor,at=fake_monitor()
    at(0,OVER)
    assert at(5,HEALTHY)['admission_ready'] is False
    held=at(20,HEALTHY)
    assert held['admission_ready'] is False and held['recovery']['healthy_samples']==2
    assert held['recovery']['healthy_seconds']==15
    assert at(21,HEALTHY)['admission_ready'] is True


@pytest.mark.parametrize('third,released',[(15,True),(14.9,False)])
def test_release_happens_exactly_at_ten_seconds_and_three_samples(third,released):
    monitor,at=fake_monitor()
    at(0,OVER)
    assert at(5,HEALTHY)['admission_ready'] is False
    assert at(10,HEALTHY)['admission_ready'] is False
    assert at(third,HEALTHY)['admission_ready'] is released
    assert at(16,HEALTHY)['admission_ready'] is True


@pytest.mark.parametrize('violation',[{'rss_mb':40,'cpu_percent':WARDEN_CPU_LIMIT_PERCENT+1},
                                      {'rss_mb':None,'cpu_percent':1},OVER])
def test_any_violation_during_recovery_restarts_the_window(violation):
    monitor,at=fake_monitor()
    at(0,OVER)
    for second in range(1,10):
        at(second,HEALTHY)
    assert at(10,violation)['recovery_hold'] is True
    for second in range(11,21):
        assert at(second,HEALTHY)['admission_ready'] is False
    assert at(21,HEALTHY)['admission_ready'] is True


def test_cpu_only_spike_pauses_on_the_same_sample_and_reopens_on_the_next_ready_sample():
    # r4 parity: an over-budget CPU sample with resident memory measured within
    # budget closes admission at once but starts no recovery hold.
    monitor,at=fake_monitor()
    assert at(0,HEALTHY)['admission_ready'] is True
    paused=at(1,CPU_SPIKE)
    assert (paused['ready'],paused['admission_ready'],paused['recovery_hold'])==(False,False,False)
    assert paused['action']=='pause_admission'
    assert paused['admission_reasons']==paused['reasons']==['Warden CPU utilization exceeds its strict 5% budget']
    # A cached read inside the one-second window is the same paused sample.
    assert at(1.5,HEALTHY) is paused
    reopened=at(2,HEALTHY)
    assert (reopened['ready'],reopened['admission_ready'],reopened['recovery_hold'],reopened['action'])==(
        True,True,False,'none')
    assert reopened['admission_reasons']==[]
    assert (reopened['recovery']['healthy_samples'],reopened['recovery']['healthy_seconds'])==(0,None)


def test_consecutive_cpu_only_spikes_stay_paused_and_reopen_on_the_first_ready_sample():
    monitor,at=fake_monitor()
    for second in range(5):
        spiked=at(second,CPU_SPIKE)
        assert (spiked['admission_ready'],spiked['recovery_hold'])==(False,False)
    assert at(5,HEALTHY)['admission_ready'] is True


@pytest.mark.parametrize('violation',[{'rss_mb':WARDEN_MEMORY_LIMIT_MB+1,'cpu_percent':WARDEN_CPU_LIMIT_PERCENT+1},
                                      {'rss_mb':None,'cpu_percent':WARDEN_CPU_LIMIT_PERCENT+1},
                                      {'rss_mb':40,'cpu_percent':None},{'rss_mb':40,'cpu_percent':float('nan')}])
def test_cpu_violation_with_memory_violation_or_unavailable_telemetry_starts_the_full_hold(violation):
    monitor,at=fake_monitor()
    assert at(0,violation)['recovery_hold'] is True
    for second in range(1,11):
        assert at(second,HEALTHY)['admission_ready'] is False
    assert at(11,HEALTHY)['admission_ready'] is True


@pytest.mark.parametrize('violation',[OVER,{'rss_mb':None,'cpu_percent':1},{'rss_mb':40,'cpu_percent':None},
                                      {'rss_mb':WARDEN_MEMORY_LIMIT_MB+1,'cpu_percent':WARDEN_CPU_LIMIT_PERCENT+1}])
def test_memory_violation_during_a_cpu_pause_starts_the_full_hold_from_that_violation(violation):
    monitor,at=fake_monitor()
    at(0,HEALTHY)
    assert at(1,CPU_SPIKE)['admission_ready'] is False
    held=at(2,violation)
    assert (held['admission_ready'],held['recovery_hold'])==(False,True)
    # Ten healthy seconds from the first healthy sample (t=3) and three samples.
    for second in range(3,13):
        assert at(second,HEALTHY)['admission_ready'] is False
    released=at(13,HEALTHY)
    assert (released['admission_ready'],released['recovery_hold'])==(True,False)
    # After the full hold releases, a later CPU-only spike is again a one-sample pause.
    assert at(14,CPU_SPIKE)['recovery_hold'] is False
    assert at(15,HEALTHY)['admission_ready'] is True


def test_cached_reads_within_one_second_are_not_counted_as_fresh_samples():
    monitor,at=fake_monitor(recovery_seconds=0,recovery_samples=3)
    at(0,OVER)
    first=at(1,HEALTHY)
    for offset in (.1,.5,.99):
        assert at(1+offset,HEALTHY) is first
    assert first['recovery']['healthy_samples']==1
    assert at(2,HEALTHY)['admission_ready'] is False
    assert at(3,HEALTHY)['admission_ready'] is True


def test_monitor_takes_its_recovery_window_from_the_configured_hardware_policy():
    defaults=(HardwarePolicy().recovery_seconds,HardwarePolicy().recovery_samples)
    assert defaults==(10,3)
    for monitor in (ControllerMonitor(),ControllerMonitor.from_policy(None),
                    ControllerMonitor.from_policy(SimpleNamespace())):
        assert (monitor.recovery_seconds,monitor.recovery_samples)==defaults
    configured=ControllerMonitor.from_policy(HardwarePolicy(recovery_seconds=20.,recovery_samples=5))
    assert (configured.recovery_seconds,configured.recovery_samples)==(20.,5)


@pytest.mark.parametrize('policy',[{'recovery_seconds':-1},{'recovery_seconds':float('inf')},
                                   {'recovery_seconds':601},{'recovery_seconds':True},{'recovery_samples':0},
                                   {'recovery_samples':2.},{'recovery_samples':True}])
def test_invalid_recovery_window_is_refused(policy):
    with pytest.raises(ValueError):
        ControllerMonitor(**policy)


def test_runtime_constructs_its_monitor_from_config_hardware(tmp_path,monkeypatch):
    from cochem_pipeline import resource_limits, windows
    from cochem_pipeline.runtime import Runtime

    class StopAfterMonitor(Exception):
        pass

    def stop(*args,**kwargs):
        raise StopAfterMonitor

    # Explicit construction boundary: no SYSTEM check, no scheduling change to
    # this test process, and construction stops before any layout or service.
    monkeypatch.setattr(windows,'require_system',lambda: None)
    monkeypatch.setattr(windows,'validate_code_path',lambda path: None)
    monkeypatch.setattr(windows,'validate_layout',stop)
    monkeypatch.setattr(resource_limits,'controller_limits',lambda limits,apply: {'fixture':True})
    runtime=Runtime.__new__(Runtime)
    config=SimpleNamespace(execution_limits=ResourceLimits(),workers={},private_root=tmp_path,slot_roots={},
                           hardware=HardwarePolicy(recovery_seconds=20.,recovery_samples=5))
    with pytest.raises(StopAfterMonitor):
        Runtime.__init__(runtime,config)
    assert (runtime.controller_monitor.recovery_seconds,runtime.controller_monitor.recovery_samples)==(20.,5)


def tick_runtime(monitor):
    from cochem_pipeline.runtime import Runtime
    runtime=Runtime.__new__(Runtime)
    telemetry=[]
    runtime.store=SimpleNamespace(event_batch=lambda cursor: [],active_jobs=lambda: [],reap_expired=lambda: [],
                                  set_transition_telemetry=telemetry.append)
    runtime.oracle=SimpleNamespace(drain=lambda: [])
    # Explicit admission stimulus only: this is not a physical hardware probe.
    runtime.guard=SimpleNamespace(evaluate=lambda: {'capacity':4,'state':'normal','action':'none','reasons':[]})
    runtime.controller_monitor=monitor
    runtime.controller_scheduling={'fixture':True}
    runtime.config=SimpleNamespace(slot_roots={},lease_seconds=60)
    runtime.components,runtime.active,runtime.quarantined={},{},{}
    runtime.lock=threading.RLock()
    runtime._context_drain_lock=threading.Lock()
    runtime.event_cursor=0
    return runtime,telemetry


def test_runtime_tick_never_admits_while_the_controller_flaps_and_reopens_only_after_hysteresis():
    clock=SimpleNamespace(now=1000.)
    feed={'readings':itertools.cycle([OVER,HEALTHY])}
    monitor=ControllerMonitor(clock=lambda: clock.now,measure=lambda: dict(next(feed['readings'])))
    runtime,telemetry=tick_runtime(monitor)

    def tick(step):
        # The runtime ticks every 0.1 s; the monitor takes one fresh sample per second.
        clock.now=1000+step/10
        runtime.tick()
        return runtime.last_capacity,runtime.components['warden_controller']

    states=set()
    for step in range(300):
        capacity,component=tick(step)
        assert capacity==0
        assert telemetry[-1]['capacity']==0 and telemetry[-1]['action']=='pause_admission'
        assert telemetry[-1]['controller']['admission_ready'] is False
        states.add(component['state'])
        if component['state']=='recovering':
            assert component['ready'] is True
            assert any('recovery hysteresis' in reason for reason in telemetry[-1]['reasons'])
    assert states=={'resource_pressure','recovering'}

    # One more violation at t=30, then only healthy samples: release needs ten
    # healthy seconds from t=31 and at least three samples, so it opens at t=41.
    feed['readings']=itertools.chain([OVER],itertools.repeat(HEALTHY))
    for step in range(300,410):
        assert tick(step)[0]==0
    capacity,component=tick(410)
    assert capacity==4 and component['state']=='healthy' and component['admission_ready'] is True
    assert 'controller' not in telemetry[-1]
    for step in range(411,420):
        assert tick(step)[0]==4

    # The pause stays immediate: the first over-budget sample closes admission on its own tick.
    feed['readings']=itertools.repeat(OVER)
    capacity,component=tick(420)
    assert capacity==0 and component['state']=='resource_pressure'
    assert telemetry[-1]['reasons']==['Warden resident memory exceeds its strict 200 MiB budget']


def test_runtime_tick_closes_on_a_cpu_only_spike_and_reopens_on_the_next_fresh_sample():
    clock=SimpleNamespace(now=1000.)
    readings=itertools.chain([HEALTHY,CPU_SPIKE],itertools.repeat(HEALTHY))
    monitor=ControllerMonitor(clock=lambda: clock.now,measure=lambda: dict(next(readings)))
    runtime,telemetry=tick_runtime(monitor)

    def tick(step):
        # The runtime ticks every 0.1 s; the monitor takes one fresh sample per second.
        clock.now=1000+step/10
        runtime.tick()
        return runtime.last_capacity,runtime.components['warden_controller']

    for step in range(10):
        assert tick(step)[0]==4
    # The spike closes admission on its own tick and for the cached rest of that second.
    for step in range(10,20):
        capacity,component=tick(step)
        assert capacity==0 and component['state']=='resource_pressure'
        assert telemetry[-1]['reasons']==['Warden CPU utilization exceeds its strict 5% budget']
    capacity,component=tick(20)
    assert capacity==4 and component['state']=='healthy' and component['recovery_hold'] is False
    assert 'controller' not in telemetry[-1]


def test_native_controller_policy_cannot_be_claimed_on_linux():
    if os.name=='nt':
        pytest.skip('Unsupported-host refusal is a Linux contract')
    with pytest.raises(ResourcePolicyError,match='requires Windows'):
        controller_limits(ResourceLimits(),apply=True)


@pytest.mark.skipif(os.name!='nt' or os.environ.get('COCHEM_RUN_NATIVE_RESOURCE_TESTS')!='1',
                   reason='Actual Warden priority/affinity requires native Windows resource acceptance')
def test_actual_native_controller_priority_and_efficiency_affinity():
    result=subprocess.run([sys.executable,'-I','-c',
        'import json; from cochem_pipeline.resource_limits import ResourceLimits,controller_limits; '
        'controller_limits(ResourceLimits(),apply=True); '
        'print(json.dumps(controller_limits(ResourceLimits())))'],
        capture_output=True,text=True,timeout=15,check=True,creationflags=0x08000200)
    evidence=json.loads(result.stdout)
    assert evidence['controller_policy_verified'] is True
    assert evidence['topology_verified'] is True
    assert set(evidence['observed_logical_processors'])==set(evidence['logical_processors'])
