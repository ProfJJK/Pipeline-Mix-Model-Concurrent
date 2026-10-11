"""Measure the Warden itself against its WARDEN_MEMORY_LIMIT_MB (200 MiB) / 5% polling budget.

The 200 MiB memory budget is the owner amendment of 2026-10-11 to S427-HOST-006
and S427-PERF-005 (repo-root 4.2.7_SRS.md): the earlier literal left under 10 MiB
of headroom over the ~40 MiB idle Python footprint, so harmless allocator
high-water paused admission. The CPU budget is unchanged.

These are readiness/admission limits, not a promise that a Python allocation
cannot cross the boundary. Crossing it holds new work without killing the
controller and losing the diagnostic or entering an automatic restart loop.
A violation pauses admission on the same sample. Reopening uses the host
governor's recovery hysteresis (HardwarePolicy recovery_seconds and
recovery_samples), so admission cannot flap around the budget.
"""
from __future__ import annotations

import math
import threading
import time

import psutil

from .hardware_guard import HardwarePolicy

WARDEN_MEMORY_LIMIT_MB = 200
WARDEN_CPU_LIMIT_PERCENT = 5


def assess_controller(measurements):
    """Pure budget verdict: ready only for rss_mb <= WARDEN_MEMORY_LIMIT_MB (200 MiB)
    and cpu_percent <= WARDEN_CPU_LIMIT_PERCENT (5%); missing telemetry is never ready."""
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


class ControllerMonitor:
    """Sample the Warden at most once per second and hold admission after a violation.

    ``ready`` is the literal budget verdict of the latest sample. Any not-ready
    sample sets ``recovery_hold``. The hold is released only once at least
    ``recovery_seconds`` have passed since the first healthy sample and at
    least ``recovery_samples`` consecutive fresh healthy samples were taken,
    as GovernorState does for host capacity. Admission uses
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
                    'source':'psutil.Process.memory_info/cpu_percent/cpu_affinity',
                    'cpu_scope':'process CPU divided by its actual allowed logical CPU count'}
        try:
            info = self.process.memory_info()
            measured['rss_mb'] = info.rss / 1048576
            private = getattr(info,'private',None)
            measured['private_mb'] = None if private is None else private / 1048576
            affinity = self.process.cpu_affinity()
            measured['allowed_logical_processors'] = affinity
            if not affinity:
                raise ValueError('Controller has no allowed logical CPUs')
            # Subsequent samples include all work since the previous tick;
            # measuring only another idle sleep would conceal controller CPU.
            measured['cpu_percent'] = self.process.cpu_percent(
                interval=.05 if self.latest is None else None)/len(affinity)
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
                # The pause is immediate and any violation restarts recovery.
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
