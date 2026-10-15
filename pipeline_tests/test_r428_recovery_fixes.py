"""R428 recovery fixes: rolling controller CPU window, identity-cached executable
digests, and catalog probe revocation semantics. Real objects only (no mocks)."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from cochem_pipeline.catalog_runtime import CatalogController
from cochem_pipeline.controller_guard import (CPU_WINDOW_SECONDS, WARDEN_CPU_LIMIT_PERCENT,
                                              ControllerMonitor, CpuWindow, assess_controller)
from cochem_pipeline import native_effort


def _feed(window, seconds_per_second, *, start=0., cpu=0., logical=8):
    """Feed one observation per second; return the last windowed percentage."""
    now, used, result = start, cpu, None
    for burn in seconds_per_second:
        now += 1.
        used += burn
        result = window.add(now, used, logical)
    return result, now, used


def test_window_amortizes_one_binary_hash_that_a_one_second_sample_would_flag():
    # Idle controller: 4% of 8 logical CPUs = 0.32 CPU-seconds per second.
    idle = .32
    window = CpuWindow(CPU_WINDOW_SECONDS)
    (baseline, _), now, used = _feed(window, [0.] + [idle]*10)
    assert baseline == pytest.approx(4.0)
    # A 235 MB hash burns about one full core for 1.5 s inside the controller.
    (spiked, elapsed), now, used = _feed(window, [idle+1.5], start=now, cpu=used)
    one_second_sample = 100.*(idle+1.5)/1./8
    assert one_second_sample > WARDEN_CPU_LIMIT_PERCENT          # the old per-tick verdict paused admission
    assert spiked <= WARDEN_CPU_LIMIT_PERCENT                    # the window does not
    assert elapsed >= CPU_WINDOW_SECONDS
    assert assess_controller({'allowed_logical_processors': list(range(8)), 'rss_mb': 50, 'cpu_percent': spiked})['ready'] is True


def test_window_still_flags_sustained_controller_load():
    window = CpuWindow(CPU_WINDOW_SECONDS)
    (busy, _), *_ = _feed(window, [0.] + [1.2]*12)               # 1.2 cores (15% of 8 CPUs), sustained
    assert busy == pytest.approx(15.0)
    verdict = assess_controller({'allowed_logical_processors': list(range(8)), 'rss_mb': 50, 'cpu_percent': busy})
    assert verdict['ready'] is False
    assert verdict['reasons'] == ['Warden CPU utilization exceeds its strict 1 core-equivalent budget']


def test_window_reports_unavailable_never_idle_on_clock_or_counter_regression():
    window = CpuWindow(10)
    assert window.add(1., 5., 8) == (None, 0.)                   # a single point has no rate
    assert window.add(2., 5.1, 8)[0] == pytest.approx(1.25)
    assert window.add(2., 5.2, 8) == (None, 0.)                  # clock did not advance
    assert window.add(3., 1.0, 8) == (None, 0.)                  # cumulative CPU decreased
    assert window.add(4., 1.08, 8)[0] == pytest.approx(1.0)      # restarts from the new point
    assert window.add(5., 1.1, 0) == (None, 0.)
    with pytest.raises(ValueError):
        CpuWindow(0.5)


def test_window_keeps_one_left_edge_older_than_the_window():
    window = CpuWindow(10)
    for second in range(30):
        window.add(float(second), second*.08, 8)
    assert window.samples[0][0] <= 29.-10
    assert window.samples[1][0] > 29.-10


def test_live_controller_measurement_uses_the_window():
    monitor = ControllerMonitor(recovery_seconds=0, recovery_samples=1)
    first = monitor._measure_process()
    assert first['cpu_percent'] is not None and first['cpu_percent'] >= 0
    assert 'rolling 10 s window' in first['cpu_scope']
    assert first['cpu_window_seconds'] > 0
    time.sleep(.05)
    second = monitor._measure_process()
    assert second['cpu_window_seconds'] > first['cpu_window_seconds']


def test_executable_digest_is_cached_per_file_identity_and_rehashed_on_change(tmp_path: Path):
    binary = tmp_path / 'provider.exe'
    binary.write_bytes(b'reviewed-binary-v1' * 1000)
    expected = hashlib.sha256(binary.read_bytes()).hexdigest()
    assert native_effort.verified_executable_sha256(binary) == expected
    key = native_effort._file_identity(binary, binary.stat())
    assert native_effort._DIGEST_CACHE[key] == expected
    assert native_effort.verified_executable_sha256(binary) == expected

    binary.write_bytes(b'replaced-binary-v2' * 1001)
    stat = binary.stat()
    os.utime(binary, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
    replaced = hashlib.sha256(binary.read_bytes()).hexdigest()
    assert native_effort.verified_executable_sha256(binary) == replaced != expected


def test_effort_digest_still_refuses_a_binary_that_differs_from_its_contract(tmp_path: Path):
    binary = tmp_path / 'claude.exe'
    binary.write_bytes(b'not-the-reviewed-binary')
    with pytest.raises(ValueError, match='does not match the reviewed reasoning effort contract'):
        native_effort.effort_binary_digest({'executable': str(binary)}, {'executable_sha256': 'a'*64})
    good = hashlib.sha256(binary.read_bytes()).hexdigest()
    assert native_effort.effort_binary_digest({'executable': str(binary)}, {'executable_sha256': good}) == good


def test_prewarm_verifies_absolute_configured_executables_only(tmp_path: Path):
    present = tmp_path / 'codex.exe'
    present.write_bytes(b'codex')
    result = native_effort.prewarm_executable_digests({
        'codex': {'executable': str(present)},
        'claude': {'executable': str(tmp_path / 'missing.exe')},
        'gemini': {'executable': 'relative\\agy.exe'},
    })
    assert result == {'codex': hashlib.sha256(b'codex').hexdigest(), 'claude': None}


class _ProbeStore:
    def __init__(self):
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        self.db.execute('CREATE TABLE pipeline_catalog_probes(reservation_id TEXT, lease_expires_at REAL, cleanup_at REAL)')

    @contextmanager
    def _connection(self):
        yield self.db


@pytest.mark.parametrize(('action', 'stopping', 'lease_offset', 'cleaned', 'valid'), [
    ('pause_admission', False, 60, None, True),     # the R428 failure: a pause must not revoke
    ('none', False, 60, None, True),
    (None, False, 60, None, True),
    ('terminate_active', False, 60, None, False),   # critical pressure revokes
    ('none', True, 60, None, False),                # shutdown revokes
    ('none', False, -1, None, False),               # expired lease revokes
    ('none', False, 60, 1.0, False),                # finished cleanup revokes
])
def test_catalog_probe_is_revoked_only_by_critical_pressure_shutdown_or_lease(action, stopping, lease_offset, cleaned, valid):
    store = _ProbeStore()
    store.db.execute('INSERT INTO pipeline_catalog_probes VALUES(?,?,?)', ('r1', time.time()+lease_offset, cleaned))
    stop = threading.Event()
    if stopping:
        stop.set()
    runtime = SimpleNamespace(stop_event=stop, last_admission_action=action, last_capacity=0, store=store)
    controller = CatalogController(runtime, reader=None)
    assert controller._probe_lease_valid('r1') is valid
    assert controller._probe_lease_valid('unknown') is False
