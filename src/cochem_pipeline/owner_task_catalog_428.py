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
from .task_catalog_acceptance_428 import (encoded, enabled_candidate, outcome_summary, probe_outcomes,
                                          protected_request, run_acceptance)
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


def _board_state(conn, request_sha256, baseline):
    conn.execute('BEGIN')
    try:
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
    finally:
        conn.rollback()


@contextmanager
def read_only_board(job_db):
    """A query-only connection that cannot migrate, lock out, or write the board."""
    import sqlite3
    conn = sqlite3.connect(Path(job_db).resolve().as_uri() + '?mode=ro', uri=True,
                           timeout=5.0, isolation_level=None)
    try:
        conn.execute('PRAGMA busy_timeout=5000')
        conn.execute('PRAGMA query_only=ON')
        yield conn
    finally:
        conn.close()


def board_baseline(job_db):
    """Active policy/task-catalog identity read before any runtime touches the board."""
    with read_only_board(job_db) as conn:
        conn.execute('BEGIN')
        try:
            active = catalog_journal.active_task_catalog(conn)
            return (catalog_journal.active_policy(conn).digest, digest(active) if active is not None else None)
        finally:
            conn.rollback()


def publication_snapshot(store, request_sha256, baseline, *, job_db=None):
    """Conservative rollback signal from the durable board, never local progress.

    A caller receiving no final receipt must assume UNKNOWN. In particular a
    committed publication followed by a coverage/file failure is still COMMITTED.
    Without a constructed runtime the board is read through a query-only
    connection, so a failed construction can still prove nothing was published.
    """
    try:
        if store is not None:
            with store._connection() as conn:
                return _board_state(conn, request_sha256, baseline)
        if job_db is not None:
            with read_only_board(job_db) as conn:
                return _board_state(conn, request_sha256, baseline)
    except BaseException:
        pass
    return dict(state='UNKNOWN', catalog_probe_cleanup_verified=False)


def outcome_snapshot(store, job_db, request_id):
    """Per-target probe outcomes for the owner result, also after a hold."""
    if not isinstance(request_id, str) or not re.fullmatch('[0-9a-f]{32}', request_id):
        return None
    try:
        context = store._connection() if store is not None else read_only_board(job_db) if job_db is not None else None
        if context is None:
            return None
        with context as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'pipeline_catalog_probes', 'pipeline_task_probe_evidence', 'pipeline_task_catalog_holds'} <= tables:
                return []
            return probe_outcomes(conn, request_id)
    except BaseException:
        return None


def wait_start_gate(output_root, started_path, started_record, *, timeout_seconds=90):
    """Let the owner retain exact process handles before this phase can exit."""
    acknowledgement = output_root / 'phase-start-ack.json'
    deadline = time.monotonic() + timeout_seconds
    expected = dict(schema='cochem-owner-task-catalog-start-ack/4.2.8',
        start_sha256=hashlib.sha256(started_path.read_bytes()).hexdigest(), pid=started_record['pid'],
        bootstrap_sha256=started_record['bootstrap_sha256'], request_sha256=started_record['request_sha256'],
        nonce=started_record['nonce'])
    while not acknowledgement.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError('Owner process custody acknowledgment was not received')
        time.sleep(.05)
    with retained_path(acknowledgement) as custody:
        raw = custody.read(acknowledgement, 16384)
        if _strict_json(raw.decode('utf-8-sig')) != expected:
            raise ValueError('Owner process custody acknowledgment differs from this phase')


def write_start_record(path, record):
    # Publish only complete bytes: the launcher polls for the final name.
    # Windows rename refuses an existing destination in this fresh held root.
    pending = path.with_suffix('.pending')
    raw = write_fresh(pending, record)
    pending.rename(path)
    return raw


def run_owner_phase(bootstrap_config, bootstrap_sha256, request_path, request_sha256,
                    output_root, *, timeout_seconds=7200, poll_seconds=1,
                    flash_context_limit=None, runtime_factory=None, start_gate=False, start_nonce=None):
    """The SYSTEM-only API. runtime_factory is an in-process test seam only.

    The candidate files are written and validated inside the publication
    transaction, so every failure before COMMIT leaves the board unchanged.
    After COMMIT only runtime closure and the result record remain.
    """
    if type(start_gate) is not bool:
        raise ValueError('Owner start gate must be boolean')
    if (start_gate and (not isinstance(start_nonce, str) or not re.fullmatch('[0-9a-f]{32}', start_nonce))
            or not start_gate and start_nonce is not None):
        raise ValueError('A gated start requires its fresh owner nonce')
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
    job_db = None
    monitor = None
    monitor_stop = threading.Event()
    monitor_failures = []
    phase, result, error, closed = 'preconditions', None, None, False
    close_started = False
    baseline = None
    report_request_id = None
    with ExitStack() as lifetime, retained_path(output_root, directory=True), retained_path(bootstrap_config) as input_custody:
        if any(output_root.iterdir()):
            raise ValueError('Owner output directory must be fresh and empty')
        # Exclusive creation also fences a concurrent invocation using this root.
        started_path = output_root / 'phase-started.json'
        started_record = dict(schema='cochem-owner-task-catalog-start/4.2.8',
            bootstrap_sha256=bootstrap_sha256, request_sha256=request_sha256,
            pid=os.getpid(), started_at=time.time(), nonce=start_nonce)
        write_start_record(started_path, started_record)
        try:
            if start_gate:
                phase = 'process_custody'
                wait_start_gate(output_root, started_path, started_record)
            phase = 'preconditions'
            raw = _strict_json(pinned_bytes(input_custody, bootstrap_config, bootstrap_sha256).decode('utf-8-sig'))
            # The reviewed bytes name the board. Read it before the bootstrap is
            # even parsed, and before any runtime migration, quarantine or probe:
            # a refused bootstrap or failed construction must still prove that
            # nothing was published, so the launcher may restore r4.
            private_root = raw.get('private_root') if isinstance(raw, dict) else None
            if not isinstance(private_root, str) or not Path(private_root).is_absolute():
                raise ValueError('Bootstrap must name an absolute private board root')
            job_db = Path(private_root) / 'job_board.db'
            phase = 'board_baseline'
            baseline = board_baseline(job_db)
            phase = 'preconditions'
            config = load_config(str(bootstrap_config))
            if Path(config.job_db) != job_db:
                raise ValueError('Loaded bootstrap names a different board')
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
                report_request_id = _strict_json(request_data.decode('utf-8')).get('request_id')
                with runtime.store._write() as conn:
                    active = catalog_journal.active_task_catalog(conn)
                    if (catalog_journal.active_policy(conn).digest,
                            digest(active) if active is not None else None) != baseline:
                        raise ValueError('Board catalog authority changed while the runtime started')
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

                    def stop_monitor():
                        # Every probe is closed; no guard tick may race or revoke
                        # the publication transaction once it opens.
                        nonlocal phase
                        phase = 'publication_guard'
                        monitor_stop.set()
                        monitor.join(timeout=30)
                        if monitor.is_alive():
                            raise RuntimeError('Acceptance monitor did not drain before publication')
                        require_active()
                        if getattr(runtime, 'last_admission_action', None) == 'terminate_active':
                            raise RuntimeError('Critical resource guard revoked acceptance')
                        # Drain the slow Docker work that close() would otherwise do
                        # first after COMMIT; a failure here still rolls back.
                        maintenance = getattr(runtime, '_maintenance_thread', None)
                        if maintenance is not None:
                            maintenance.join(timeout=120)
                            if maintenance.is_alive():
                                raise RuntimeError('Controller maintenance has not drained before publication')
                        if getattr(runtime, 'docker', None) is not None:
                            runtime.docker.reap_orphans(active_attempt_ids=set(), include_warm=False)
                        phase = 'publication'

                    def finalize(conn, acceptance):
                        # Inside the publication transaction: any failure here
                        # rolls the catalog back, so nothing is half-enabled.
                        nonlocal phase
                        phase = 'candidate_files'
                        catalog_path = output_root / 'accepted-catalog.json'
                        catalog_bytes = write_fresh(catalog_path, acceptance['catalog'])
                        with retained_path(catalog_path):
                            candidate = enabled_candidate(conn, request, raw, catalog_path=catalog_path,
                                catalog_bytes=catalog_bytes, flash_context_limit=flash_context_limit)
                        candidate_path = output_root / 'pipeline.json'
                        candidate_bytes = write_fresh(candidate_path, candidate)
                        phase = 'candidate_validation'
                        with retained_path(catalog_path), retained_path(candidate_path):
                            validated = load_config(str(candidate_path))
                            if (validated.task_planning is None or validated.catalog_activation is not True
                                    or validated.task_planning.read_catalog() != acceptance['catalog']
                                    or validated.task_planning.catalog_sha256 != hashlib.sha256(catalog_bytes).hexdigest()
                                    or validated.routing.digest != request.plan.policy.digest):
                                raise ValueError('Protected candidate loader did not retain exact accepted catalog')
                        require_active()
                        phase = 'publication_commit'
                        return dict(catalog_path=str(catalog_path),
                                    catalog_sha256=hashlib.sha256(catalog_bytes).hexdigest(),
                                    configuration_path=str(candidate_path),
                                    configuration_sha256=hashlib.sha256(candidate_bytes).hexdigest())

                    phase = 'catalog_acceptance'
                    monitor_tick()
                    monitor = threading.Thread(target=supervise, name='task-catalog-guard', daemon=True)
                    monitor.start()
                    while True:
                        require_active()
                        acceptance = run_acceptance(runtime, request, before_publish=stop_monitor, finalize=finalize)
                        if acceptance.get('status') != 'WAITING_ADMISSION':
                            break
                        if runtime.stop_event.wait(poll_seconds):
                            raise RuntimeError('Acceptance cancelled while waiting for admission')
                    if acceptance.get('catalog_published') is not True:
                        raise RuntimeError('Exact task catalog publication was not completed')
                    files = acceptance['finalized']
                    result = dict(schema='cochem-owner-task-catalog-result/4.2.8',
                        status='TASK_CATALOG_CANDIDATE_READY', request_id=request.request_id,
                        request_sha256=request_sha256, bootstrap_sha256=bootstrap_sha256,
                        catalog_path=files['catalog_path'], catalog_sha256=files['catalog_sha256'],
                        configuration_path=files['configuration_path'], configuration_sha256=files['configuration_sha256'],
                        catalog_published=True, cutover_requested=False, ordinary_jobs_dispatched=False,
                        sign_in_attempted=False, late_prompt=False, coverage=acceptance['coverage'],
                        all_routes_usable=acceptance['all_routes_usable'], coverage_holds=acceptance['coverage_holds'],
                        probe_outcomes=acceptance.get('probe_outcomes'))
                    # Request, bootstrap and output custody cover resource drain.
                    phase = 'resource_drain'
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
            if runtime is None:
                # Construction failed or never began: no runtime resource can
                # outlive this process; publication is judged from the board.
                closed = True
        publication = publication_snapshot(runtime.store if runtime is not None else None,
                                           request_sha256, baseline, job_db=job_db)
        outcomes = outcome_snapshot(runtime.store if runtime is not None else None, job_db, report_request_id)
        if error is not None or not closed:
            result = dict(schema='cochem-owner-task-catalog-result/4.2.8',
                status='TASK_CATALOG_HELD_PRESERVE_EVIDENCE', phase=phase,
                error_type=type(error).__name__ if error else 'ResourceDrainUnverified',
                failure=sanitized_failure(error) if error else None,
                monitor_error_types=monitor_failures, cleanup_verified=False, runtime_resources_closed=closed,
                runtime_constructed=runtime is not None,
                request_sha256=request_sha256, bootstrap_sha256=bootstrap_sha256,
                publication_state=publication['state'], publication_proof=publication,
                catalog_published=publication['state'] == 'COMMITTED', cutover_requested=False, automatic_retry=False,
                ordinary_jobs_dispatched=False, sign_in_attempted=False, late_prompt=False, probe_outcomes=outcomes,
                probe_summary=outcome_summary(outcomes))
            write_fresh(output_root / 'held.json', result)
        else:
            result['cleanup_verified'] = True
            result.update(publication_state=publication['state'], publication_proof=publication,
                          runtime_resources_closed=True, runtime_constructed=True,
                          probe_outcomes=outcomes if outcomes is not None else result.get('probe_outcomes'))
            result['probe_summary'] = outcome_summary(result['probe_outcomes'])
            if publication['state'] != 'COMMITTED' or publication.get('catalog_probe_cleanup_verified') is not True:
                result.update(status='TASK_CATALOG_HELD_PRESERVE_EVIDENCE', cleanup_verified=False,
                              phase='publication_recheck', automatic_retry=False)
                write_fresh(output_root / 'held.json', result)
                return result
            write_fresh(output_root / 'result.json', result)
        return result


def sanitized_failure(error):
    """Publish code locations and reviewed target identity, never raw error text."""
    from .crash import crash_envelope
    envelope = crash_envelope(error, getattr(error, 'category', 'code'))
    result = dict(error_type=envelope['exception_type'], category=envelope['category'],
                  frames=[dict(function=frame['function'], line=frame['lineno'])
                          for frame in envelope['frames'][-8:]])
    target = getattr(error, 'catalog_target', None)
    if (isinstance(target, dict) and set(target) == {'provider', 'model', 'effort'}
            and target['provider'] in {'codex', 'claude', 'gemini'}
            and isinstance(target['model'], str) and re.fullmatch('[A-Za-z0-9_.:-]{1,128}', target['model'])
            and target['effort'] in {'low', 'medium', 'high', 'xhigh', 'max', None}):
        result['target'] = dict(target)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bootstrap-config', 'bootstrap-sha256', 'request', 'request-sha256', 'output-root'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--timeout-seconds', type=float, default=7200)
    parser.add_argument('--poll-seconds', type=float, default=1)
    parser.add_argument('--flash-context-limit', type=int)
    parser.add_argument('--start-gate', action='store_true')
    parser.add_argument('--start-nonce')
    args = parser.parse_args(argv)
    try:
        result = run_owner_phase(args.bootstrap_config, args.bootstrap_sha256, args.request,
            args.request_sha256, args.output_root, timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds, flash_context_limit=args.flash_context_limit,
            start_gate=args.start_gate, start_nonce=args.start_nonce)
    except BaseException as exc:
        result = dict(schema='cochem-owner-task-catalog-result/4.2.8', status='TASK_CATALOG_PRECONDITION_HELD',
            error_type=type(exc).__name__, failure=sanitized_failure(exc),
            cutover_requested=False, automatic_retry=False, late_prompt=False)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'TASK_CATALOG_CANDIDATE_READY' else 2


if __name__ == '__main__':
    raise SystemExit(main())
