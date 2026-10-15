"""Measure the Warden itself against its WARDEN_MEMORY_LIMIT_MB (200 MiB) / 7% polling budget.

The 200 MiB memory budget is the owner amendment of 2026-10-11 to S427-HOST-006
and S427-PERF-005 (repo-root 4.2.7_SRS.md): the earlier literal left under 10 MiB
of headroom over the ~40 MiB idle Python footprint, so harmless allocator
high-water paused admission.

The 7% CPU budget, measured over a rolling CPU_WINDOW_SECONDS (10 s) window, is
the owner amendment of 2026-10-14 (docs/4.2.8/OWNER_AMENDMENT_20261014_CPU.md).
The live 4.2.8 controller measured 3.9-6% while idle when each sample covered
only the ~1 s since the previous tick, so one bounded operation (hashing a
provider binary, serializing an operator view) zeroed admission capacity and
revoked the catalog control probe. The window measures sustained controller
load; it does not hide it. The hashed SRS text still states 5% until the
specification and knowledge manifest are re-ratified.

These are readiness/admission limits, not a promise that a Python allocation
cannot cross the boundary. Crossing it holds new work without killing the
controller and losing the diagnostic or entering an automatic restart loop.
A violation pauses admission on the same sample. After a resident-memory
violation or unavailable telemetry, reopening uses the host governor's
recovery hysteresis (HardwarePolicy recovery_seconds and recovery_samples),
so admission cannot flap around the memory budget. A CPU-only violation
(memory measured within budget) starts no hold: as in r4, the next fresh
ready sample reopens admission, so a short polling burst does not hold new
work for the whole recovery window.
"""
from __future__ import annotations

from collections import deque
import math
import threading
import time

import psutil

from .hardware_guard import HardwarePolicy

WARDEN_MEMORY_LIMIT_MB = 200
WARDEN_CPU_LIMIT_PERCENT = 7
CPU_WINDOW_SECONDS = 10.0


def assess_controller(measurements):
    """Pure budget verdict: ready only for rss_mb <= WARDEN_MEMORY_LIMIT_MB (200 MiB)
    and cpu_percent <= WARDEN_CPU_LIMIT_PERCENT (7%); missing telemetry is never ready."""
    reasons = []
    rss = measurements.get('rss_mb')
    cpu = measurements.get('cpu_percent')
    for name, value, maximum in (('resident memory',rss,WARDEN_MEMORY_LIMIT_MB),
                                 ('CPU utilization',cpu,WARDEN_CPU_LIMIT_PERCENT)):
        if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
            reasons.append('Warden '+name+' telemetry is unavailable')
        elif value > maximum:
            reasons.append('Warden '+name+' exceeds its strict '+str(maximum)+(' MiB' if name=='resident memory' else '%')+' budget')
    return {'ready':not reasons, 'strict_srs_ready':not reasons,
            'action':'pause_admission' if reasons else 'none', 'reasons':reasons,
            'memory_limit_mb':WARDEN_MEMORY_LIMIT_MB,'cpu_limit_percent':WARDEN_CPU_LIMIT_PERCENT,
            'measurements':measurements}


def _cpu_only_violation(measurements):
    """True only when resident memory is measured within WARDEN_MEMORY_LIMIT_MB and
    CPU utilization is measured above WARDEN_CPU_LIMIT_PERCENT; unavailable
    telemetry is never a CPU-only violation."""
    rss = measurements.get('rss_mb')
    cpu = measurements.get('cpu_percent')
    measured = all(type(value) in (int,float) and math.isfinite(value) and value >= 0 for value in (rss,cpu))
    return measured and rss <= WARDEN_MEMORY_LIMIT_MB and cpu > WARDEN_CPU_LIMIT_PERCENT


class CpuWindow:
    """Process CPU utilization over the most recent ``seconds`` of observations.

    ``add`` takes a monotonic timestamp and the process's cumulative user+system
    CPU seconds. The result is the CPU consumed since the oldest retained
    observation, divided by the elapsed wall time and the allowed logical CPUs.
    One observation older than the window is retained as its left edge, so the
    window always spans at least ``seconds`` once that much history exists.
    Cumulative CPU never decreases; a decrease or a non-advancing clock is
    reported as unavailable (None), never as idle.
    """
    def __init__(self, seconds=CPU_WINDOW_SECONDS):
        if type(seconds) not in (int,float) or not math.isfinite(seconds) or not 1 <= seconds <= 300:
            raise ValueError('CPU window must be a finite number of seconds from 1 to 300')
        self.seconds = float(seconds)
        self.samples = deque()

    def add(self, now, cpu_seconds, logical_processors):
        if (type(logical_processors) is not int or logical_processors < 1
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in (now,cpu_seconds))):
            return None, 0.
        if self.samples and (now <= self.samples[-1][0] or cpu_seconds < self.samples[-1][1]):
            self.samples.clear()
            self.samples.append((now,cpu_seconds))
            return None, 0.
        self.samples.append((now,cpu_seconds))
        while len(self.samples) > 2 and self.samples[1][0] <= now-self.seconds:
            self.samples.popleft()
        start, used = self.samples[0]
        elapsed = now-start
        if len(self.samples) < 2 or elapsed <= 0:
            return None, 0.
        return 100.*(cpu_seconds-used)/elapsed/logical_processors, elapsed


class ControllerMonitor:
    """Sample the Warden at most once per second and hold admission after a violation.

    ``ready`` is the literal budget verdict of the latest sample. A not-ready
    sample caused by resident memory or unavailable telemetry sets
    ``recovery_hold``, and any violation while held restarts it. The hold is
    released only once at least ``recovery_seconds`` have passed since the
    first healthy sample and at least ``recovery_samples`` consecutive fresh
    healthy samples were taken, as GovernorState does for host capacity. A
    CPU-only violation outside a hold pauses admission for that sample alone,
    as in r4; the next fresh ready sample reopens it. Admission uses
    ``admission_ready`` (ready and not held).
    """
    def __init__(self, recovery_seconds=HardwarePolicy.recovery_seconds,
                 recovery_samples=HardwarePolicy.recovery_samples, *, clock=time.monotonic, measure=None):
        if (type(recovery_seconds) not in (int,float) or not math.isfinite(recovery_seconds)
                or not 0 <= recovery_seconds <= 600):
            raise ValueError('recovery_seconds must be a finite number of seconds from 0 to 600')
        if type(recovery_samples) is not int or not 1 <= recovery_samples <= 1000:
            raise ValueError('recovery_samples must be an integer from 1 to 1000')
        self.recovery_seconds = recovery_seconds
        self.recovery_samples = recovery_samples
        self.process = psutil.Process()
        self._clock = clock
        self._measure = measure if measure is not None else self._measure_process
        self._cpu_window = CpuWindow()
        self._lock = threading.Lock()
        self.latest = None
        self.sampled_at = None
        self.recovery_hold = False
        self.healthy_since = None
        self.healthy_samples = 0

    @classmethod
    def from_policy(cls, policy=None, **kwargs):
        """Use the configured host governor recovery window (config.hardware)."""
        return cls(getattr(policy,'recovery_seconds',HardwarePolicy.recovery_seconds),
                   getattr(policy,'recovery_samples',HardwarePolicy.recovery_samples),**kwargs)

    def _measure_process(self):
        measured = {'pid':self.process.pid,'rss_mb':None,'private_mb':None,'cpu_percent':None,
                    'source':'psutil.Process.memory_info/cpu_times/cpu_affinity',
                    'cpu_scope':('process CPU over a rolling '+format(CPU_WINDOW_SECONDS,'g')
                                 +' s window divided by its actual allowed logical CPU count')}
        try:
            info = self.process.memory_info()
            measured['rss_mb'] = info.rss / 1048576
            private = getattr(info,'private',None)
            measured['private_mb'] = None if private is None else private / 1048576
            affinity = self.process.cpu_affinity()
            measured['allowed_logical_processors'] = affinity
            if not affinity:
                raise ValueError('Controller has no allowed logical CPUs')
            def used():
                times = self.process.cpu_times()
                return time.monotonic(), times.user+times.system
            if not self._cpu_window.samples:
                # First sample: a bounded 50 ms baseline, so startup work that
                # happened before monitoring began is not attributed to polling.
                self._cpu_window.add(*used(), len(affinity))
                time.sleep(.05)
            cpu, elapsed = self._cpu_window.add(*used(), len(affinity))
            measured['cpu_percent'] = cpu
            measured['cpu_window_seconds'] = elapsed
            if cpu is None:
                raise ValueError('Controller CPU window could not be measured')
        except (psutil.Error, OSError, ValueError, AttributeError) as exc:
            measured['error'] = type(exc).__name__
        return measured

    def sample(self, *, force=False):
        with self._lock:
            now = self._clock()
            if not force and self.latest is not None and now-self.sampled_at < 1:
                return self.latest
            assessed = assess_controller(self._measure())
            now = self._clock()
            if not assessed['ready']:
                # The pause is immediate. Memory or unavailable telemetry starts the
                # recovery hold and any violation while held restarts it; a CPU-only
                # violation outside a hold holds nothing beyond this sample.
                if self.recovery_hold or not _cpu_only_violation(assessed['measurements']):
                    self.recovery_hold, self.healthy_since, self.healthy_samples = True, None, 0
            elif self.recovery_hold:
                if self.healthy_since is None:
                    self.healthy_since = now
                self.healthy_samples += 1
                if (now-self.healthy_since >= self.recovery_seconds
                        and self.healthy_samples >= self.recovery_samples):
                    self.recovery_hold, self.healthy_since, self.healthy_samples = False, None, 0
            admission_ready = assessed['ready'] and not self.recovery_hold
            if admission_ready:
                admission_reasons = []
            elif not assessed['ready']:
                admission_reasons = list(assessed['reasons'])
            else:
                admission_reasons = ['Warden controller recovery hysteresis holds admission until '
                                     +format(self.recovery_seconds,'g')+' s and '+str(self.recovery_samples)
                                     +' consecutive healthy samples']
            self.latest = {**assessed,'action':'none' if admission_ready else 'pause_admission',
                'admission_ready':admission_ready,'recovery_hold':self.recovery_hold,
                'admission_reasons':admission_reasons,
                'recovery':{'seconds':self.recovery_seconds,'samples':self.recovery_samples,
                            'healthy_samples':self.healthy_samples,
                            'healthy_seconds':None if self.healthy_since is None else now-self.healthy_since},
                'checked_at':time.time()}
            self.sampled_at = now
            return self.latest
