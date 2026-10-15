"""One-shot protected task-catalog acceptance; never a daemon or public endpoint.

The owner wrapper supplies a protected bootstrap, pinned request, and fresh
protected output directory. This module starts no service, HTTP listener, login,
or ordinary job. Native probes use the existing Runtime admission and cleanup.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager, nullcontext
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import threading
import time

from . import catalog_journal, catalog_slots, windows
from .catalog_authority import _WindowsCustody
from .config import load_config
from .routing import _strict_json
from .task_catalog_acceptance_428 import encoded, enabled_candidate, protected_request, run_acceptance
from .task_routing import digest


@contextmanager
def retained_path(path, *, directory=False):
    """Retain each ancestor plus the reviewed leaf against replacement."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Owner phase requires absolute, non-traversing protected paths')
    backend, handles = _WindowsCustody(windows), []
    try:
        for ancestor in reversed(path.parents):
            handles.append(backend.acquire(ancestor, True))
            backend.inspect(ancestor, True)
        handles.append(backend.acquire(path, directory))
        backend.inspect(path, directory)
        backend.validate(path)
        yield backend
    finally:
        for handle in reversed(handles):
            backend.release(handle)


def pinned_bytes(backend, path, sha256):
    if not isinstance(sha256, str) or not re.fullmatch('[0-9a-f]{64}', sha256):
        raise ValueError('Reviewed SHA256 pin required')
    size = backend.inspect(path, False)
    if not 1 <= size <= 4 * 1024 * 1024:
        raise ValueError('Owner input is outside its bounded size')
    data = backend.read(path, size + 1)
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError('Owner input differs from reviewed bytes')
    return data


def write_fresh(path, value):
    """No overwrite, redirect, or partial-file reuse; failure retains evidence."""
    data = encoded(value)
    with Path(path).open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    windows.validate_code_path(path)
    with retained_path(path) as backend:
        pinned_bytes(backend, Path(path), hashlib.sha256(data).hexdigest())
    return data


def _preceding_authority(store, raw_request, request_sha256):
    with store._write() as conn:
        policy = catalog_journal.active_policy(conn)
        previous = catalog_journal.active_task_catalog(conn)
        # A prior process may have committed publication and then failed to
        # write its candidate. Only exact published request pins permit replay.
        if previous is not None and previous.get('request_id') == raw_request.get('request_id'):
            if (previous.get('proposal_sha256') != request_sha256
                    or previous.get('plan_digest') != raw_request.get('plan_digest')):
                raise ValueError('Published catalog does not match this pinned request')
            prior_sha = previous.get('previous_task_catalog_sha256')
            if prior_sha is None:
                previous = None
            else:
                row = conn.execute('SELECT catalog_json FROM pipeline_task_catalog_generations WHERE catalog_sha256=?',
                                   (prior_sha,)).fetchone()
                if row is None:
                    raise ValueError('Published catalog preceding authority is missing')
                previous = _strict_json(row[0])
        return policy, previous


def publication_snapshot(store, request_sha256, baseline):
    """Conservative rollback signal from the durable board, never local progress.

    A caller receiving no final receipt must assume UNKNOWN. In particular a
    committed publication followed by a coverage/file failure is still COMMITTED.
    """
    try:
        with store._connection() as conn:
            conn.execute('BEGIN')
            policy = catalog_journal.active_policy(conn).digest
            active = catalog_journal.active_task_catalog(conn)
            active_sha = digest(active) if active is not None else None
            row = None
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pipeline_task_catalog_generations'").fetchone():
                row = conn.execute('SELECT catalog_sha256 FROM pipeline_task_catalog_generations WHERE proposal_sha256=?',
                                   (request_sha256,)).fetchone()
            state = ('COMMITTED' if row else 'NOT_COMMITTED'
                     if baseline == (policy, active_sha) else 'UNKNOWN')
            return dict(state=state, active_policy_sha256=policy, active_catalog_sha256=active_sha,
                committed_catalog_sha256=row[0] if row else None,
                catalog_probe_cleanup_verified=catalog_slots.occupancy(conn) == 0)
    except BaseException:
        return dict(state='UNKNOWN', catalog_probe_cleanup_verified=False)


def run_owner_phase(bootstrap_config, bootstrap_sha256, request_path, request_sha256,
                    output_root, *, timeout_seconds=7200, poll_seconds=1,
                    flash_context_limit=None, runtime_factory=None):
    """The SYSTEM-only API. runtime_factory is an in-process test seam only."""
    windows.require_system()
    windows.validate_code_path(Path(__file__))
    windows.validate_code_path(Path(sys.executable))
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 1 <= timeout_seconds <= 14400 or type(poll_seconds) not in (int, float)
            or not math.isfinite(poll_seconds) or not .01 <= poll_seconds <= 5):
        raise ValueError('Owner phase deadline/poll intervals are outside their bounds')
    bootstrap_config, request_path, output_root = map(Path, (bootstrap_config, request_path, output_root))
    if output_root in (bootstrap_config.parent, request_path.parent):
        raise ValueError('Owner outputs require a separate fresh protected directory')
    started = time.monotonic()
    runtime = None
    monitor = None
    monitor_stop = threading.Event()
    monitor_failures = []
    phase, published, result, error, closed = 'preconditions', False, None, None, False
    close_started = False
    baseline = None
    with ExitStack() as lifetime, retained_path(output_root, directory=True), retained_path(bootstrap_config) as input_custody:
        if any(output_root.iterdir()):
            raise ValueError('Owner output directory must be fresh and empty')
        # Exclusive creation also fences a concurrent invocation using this root.
        write_fresh(output_root / 'phase-started.json', dict(schema='cochem-owner-task-catalog-start/4.2.8',
            bootstrap_sha256=bootstrap_sha256, request_sha256=request_sha256))
        try:
            raw = _strict_json(pinned_bytes(input_custody, bootstrap_config, bootstrap_sha256).decode('utf-8-sig'))
            config = load_config(str(bootstrap_config))
            if (raw.get('task_planning') is not None or getattr(config, 'task_planning', None) is not None
                    or raw.get('catalog_activation') is not True or config.catalog_activation is not True
                    or config.max_execution_slots != 4 or raw.get('max_execution_slots') != 4):
                raise ValueError('Bootstrap must disable planning and enable the four shared catalog seats')
            if runtime_factory is None:
                from .runtime import Runtime
                runtime_factory = Runtime
            phase = 'runtime_bootstrap'
            runtime = runtime_factory(config)
            # ExitStack retains the request even when a probe raises, until the
            # finally block has drained this runtime's owned resources.
            with nullcontext(lifetime.enter_context(retained_path(request_path))) as request_custody:
                request_data = pinned_bytes(request_custody, request_path, request_sha256)
                with runtime.store._write() as conn:
                    active = catalog_journal.active_task_catalog(conn)
                    baseline = (catalog_journal.active_policy(conn).digest, digest(active) if active is not None else None)
                policy, previous = _preceding_authority(runtime.store, _strict_json(request_data.decode('utf-8')), request_sha256)
                with nullcontext(lifetime.enter_context(protected_request(
                        request_path, request_sha256, policy, previous))) as request:
                    def require_active():
                        if time.monotonic() - started >= timeout_seconds:
                            runtime.stop_event.set()
                            raise TimeoutError('Acceptance deadline elapsed')
                        if runtime.stop_event.is_set() or monitor_failures:
                            raise RuntimeError('Acceptance was cancelled')

                    def monitor_tick():
                        require_active()
                        runtime.tick(admit_jobs=False, catalog_poll=False)
                        if getattr(runtime, 'last_admission_action', None) == 'terminate_active':
                            raise RuntimeError('Critical resource guard revoked acceptance')

                    def supervise():
                        try:
                            while not monitor_stop.wait(poll_seconds):
                                monitor_tick()
                        except BaseException as exc:
                            monitor_failures.append(type(exc).__name__)
                            runtime.stop_event.set()

                    phase = 'catalog_acceptance'
                    monitor_tick()
                    monitor = threading.Thread(target=supervise, name='task-catalog-guard', daemon=True)
                    monitor.start()
                    while True:
                        require_active()
                        acceptance = run_acceptance(runtime, request)
                        if acceptance.get('status') != 'WAITING_ADMISSION':
                            break
                        if runtime.stop_event.wait(poll_seconds):
                            raise RuntimeError('Acceptance cancelled while waiting for admission')
                    published = acceptance.get('catalog_published') is True
                    require_active()
                    if not published:
                        raise RuntimeError('Exact task catalog publication was not completed')
                    phase = 'candidate_files'
                    catalog_path = output_root / 'accepted-catalog.json'
                    catalog_bytes = write_fresh(catalog_path, acceptance['catalog'])
                    with retained_path(catalog_path), runtime.store._write() as conn:
                        candidate = enabled_candidate(conn, request, raw, catalog_path=catalog_path,
                            catalog_bytes=catalog_bytes, flash_context_limit=flash_context_limit)
                    candidate_path = output_root / 'pipeline.json'
                    candidate_bytes = write_fresh(candidate_path, candidate)
                    phase = 'candidate_validation'
                    with retained_path(catalog_path), retained_path(candidate_path):
                        validated = load_config(str(candidate_path))
                        if (validated.task_planning is None or validated.catalog_activation is not True
                                or validated.task_planning.read_catalog() != acceptance['catalog']
                                or validated.task_planning.catalog_sha256 != hashlib.sha256(catalog_bytes).hexdigest()):
                            raise ValueError('Protected candidate loader did not retain exact accepted catalog')
                    require_active()
                    result = dict(schema='cochem-owner-task-catalog-result/4.2.8',
                        status='TASK_CATALOG_CANDIDATE_READY', request_id=request.request_id,
                        request_sha256=request_sha256, bootstrap_sha256=bootstrap_sha256,
                        catalog_path=str(catalog_path), catalog_sha256=hashlib.sha256(catalog_bytes).hexdigest(),
                        configuration_path=str(candidate_path), configuration_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
                        catalog_published=True, cutover_requested=False, ordinary_jobs_dispatched=False,
                        sign_in_attempted=False, late_prompt=False, coverage=acceptance['coverage'],
                        all_routes_usable=acceptance['all_routes_usable'], coverage_holds=acceptance['coverage_holds'])
                    # Request, bootstrap and output custody cover resource drain.
                    phase = 'resource_drain'
                    monitor_stop.set()
                    monitor.join(timeout=30)
                    if monitor.is_alive():
                        raise RuntimeError('Acceptance monitor did not drain')
                    if monitor_failures or runtime.stop_event.is_set():
                        raise RuntimeError('Acceptance was revoked during final validation')
                    close_started = True
                    runtime.close()
                    closed = True
        except BaseException as exc:
            error = exc
        finally:
            monitor_stop.set()
            if runtime is not None:
                runtime.stop_event.set()
            if monitor is not None:
                monitor.join(timeout=30)
            if runtime is not None and not close_started and (monitor is None or not monitor.is_alive()):
                try:
                    close_started = True
                    runtime.close()
                    closed = True
                except BaseException as exc:
                    error = error or exc
        publication = (publication_snapshot(runtime.store, request_sha256, baseline) if runtime is not None
                       else dict(state='UNKNOWN', catalog_probe_cleanup_verified=False))
        if error is not None or not closed:
            result = dict(schema='cochem-owner-task-catalog-result/4.2.8',
                status='TASK_CATALOG_HELD_PRESERVE_EVIDENCE', phase=phase,
                error_type=type(error).__name__ if error else 'ResourceDrainUnverified',
                monitor_error_types=monitor_failures, cleanup_verified=False, runtime_resources_closed=closed,
                request_sha256=request_sha256, bootstrap_sha256=bootstrap_sha256,
                publication_state=publication['state'], publication_proof=publication,
                catalog_published=publication['state'] == 'COMMITTED', cutover_requested=False, automatic_retry=False,
                ordinary_jobs_dispatched=False, sign_in_attempted=False, late_prompt=False)
            write_fresh(output_root / 'held.json', result)
        else:
            result['cleanup_verified'] = True
            result.update(publication_state=publication['state'], publication_proof=publication,
                          runtime_resources_closed=True)
            if publication['state'] != 'COMMITTED' or publication.get('catalog_probe_cleanup_verified') is not True:
                result.update(status='TASK_CATALOG_HELD_PRESERVE_EVIDENCE', cleanup_verified=False,
                              phase='publication_recheck', automatic_retry=False)
                write_fresh(output_root / 'held.json', result)
                return result
            write_fresh(output_root / 'result.json', result)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bootstrap-config', 'bootstrap-sha256', 'request', 'request-sha256', 'output-root'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--timeout-seconds', type=float, default=7200)
    parser.add_argument('--poll-seconds', type=float, default=1)
    parser.add_argument('--flash-context-limit', type=int)
    args = parser.parse_args(argv)
    try:
        result = run_owner_phase(args.bootstrap_config, args.bootstrap_sha256, args.request,
            args.request_sha256, args.output_root, timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds, flash_context_limit=args.flash_context_limit)
    except BaseException as exc:
        result = dict(schema='cochem-owner-task-catalog-result/4.2.8', status='TASK_CATALOG_PRECONDITION_HELD',
            error_type=type(exc).__name__, cutover_requested=False, automatic_retry=False, late_prompt=False)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'TASK_CATALOG_CANDIDATE_READY' else 2


if __name__ == '__main__':
    raise SystemExit(main())
