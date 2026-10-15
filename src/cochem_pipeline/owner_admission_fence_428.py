"""Bounded owner-only SQLite admission fence; never changes logical database rows.

BEGIN IMMEDIATE excludes competing claim transactions while the owner verifies
and stops the exact old Warden. Pending backlog is allowed. No expired lease is
treated as proof that a native process or containment has disappeared.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time

from . import windows
from .catalog_authority import _WindowsCustody
from .config import load_config
from .owner_task_catalog_428 import retained_path, pinned_bytes, write_fresh, write_start_record
from .routing import _strict_json


class BusyAdmission(RuntimeError):
    pass


def assert_quiescent(conn):
    """Called only after obtaining the writer fence, with no schema migration."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required = {'pipeline_jobs', 'pipeline_route_reservations', 'pipeline_execution_cleanup'}
    if not required <= tables:
        raise ValueError('Existing board lacks reviewed admission accounting tables')
    checks = {
        'active_leaves': "SELECT count(*) FROM pipeline_jobs WHERE status='IN_PROGRESS' "
                         "AND kind NOT IN ('MACRO_PLANNING_REQUEST','CODE_REQUEST')",
        'active_leases': 'SELECT count(*) FROM pipeline_jobs WHERE lease_owner IS NOT NULL OR lease_expires_at IS NOT NULL',
        'native_reservations': 'SELECT count(*) FROM pipeline_route_reservations WHERE released_at IS NULL',
        'uncleared_containment': 'SELECT count(*) FROM pipeline_execution_cleanup WHERE cleared_at IS NULL',
    }
    if 'pipeline_catalog_probes' in tables:
        checks['catalog_probes'] = 'SELECT count(*) FROM pipeline_catalog_probes WHERE cleanup_at IS NULL'
    counts = {name: conn.execute(sql).fetchone()[0] for name, sql in checks.items()}
    if any(counts.values()):
        raise BusyAdmission('Execution accounting is not quiescent')
    return counts


def catalog_identity(conn):
    """Snapshot only; absence is explicit and never initializes authority."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    policy = catalog = None
    if 'pipeline_catalog_active' in tables:
        rows = conn.execute('SELECT policy_digest FROM pipeline_catalog_active WHERE singleton=1').fetchall()
        if len(rows) != 1: raise ValueError('Active policy pointer is missing or ambiguous')
        policy = rows[0][0]
    if 'pipeline_task_catalog_active' in tables:
        rows = conn.execute('SELECT catalog_sha256 FROM pipeline_task_catalog_active WHERE singleton=1').fetchall()
        if len(rows) > 1: raise ValueError('Active task catalog pointer is ambiguous')
        catalog = rows[0][0] if rows else None
    return dict(active_policy_sha256=policy, active_catalog_sha256=catalog)


@contextmanager
def admission_fence(database, *, timeout=.2, include_catalog=False):
    """Reusable in-process seam; only reads and transaction control are permitted."""
    path = Path(database).absolute()
    conn = sqlite3.connect(path.as_uri()+'?mode=rw', uri=True, timeout=timeout, isolation_level=None)
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_TRANSACTION}
    conn.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
    try:
        conn.execute('BEGIN IMMEDIATE')
        counts = assert_quiescent(conn)
        yield dict(counts=counts, catalog=catalog_identity(conn)) if include_catalog else counts
    finally:
        if conn.in_transaction:
            conn.rollback()
        conn.close()


@contextmanager
def retained_database(database):
    """Retain the mutable private board without denying SQLite read/write sharing."""
    backend, handles = _WindowsCustody(windows), []
    try:
        for parent in reversed(database.parents):
            handles.append(backend.acquire(parent, True))
            backend.inspect(parent, True)
        windows.validate_private_directory(database.parent)
        api = windows._api()
        handle = api['kernel32'].CreateFileW(str(database), 0x80000000, 3, None, 3, 0x02200000, None)
        if handle in (None, 0, ctypes.c_void_p(-1).value):
            raise windows.WindowsIsolationError('Existing board custody could not be retained')
        handles.append(handle)
        backend.inspect(database, False)
        windows.validate_private_path(database)
        yield
    finally:
        for handle in reversed(handles):
            backend.release(handle)


def release_matches(path, *, nonce, ready_sha256, request_sha256):
    with retained_path(path) as custody:
        size = custody.inspect(path, False)
        if not 1 <= size <= 4096:
            raise ValueError('Invalid admission fence release size')
        value = _strict_json(custody.read(path, size+1).decode('utf-8-sig'))
    return value == dict(schema='cochem-owner-admission-release/4.2.8', nonce=nonce,
                         ready_sha256=ready_sha256, request_sha256=request_sha256)


def run(config_path, config_sha256, output_root, nonce, request_sha256, *, wait_seconds=1800, hold_seconds=240):
    windows.require_system()
    windows.validate_code_path(Path(__file__))
    windows.validate_code_path(Path(sys.executable))
    if (not re.fullmatch('[a-f0-9]{32}', nonce) or not re.fullmatch('[a-f0-9]{64}', request_sha256)
            or type(wait_seconds) is not int or not 1 <= wait_seconds <= 3600
            or type(hold_seconds) is not int or not 30 <= hold_seconds <= 300):
        raise ValueError('Invalid bounded admission fence identity')
    config_path, output_root = Path(config_path), Path(output_root)
    with ExitStack() as stack:
        config_custody = stack.enter_context(retained_path(config_path))
        pinned_bytes(config_custody, config_path, config_sha256)
        stack.enter_context(retained_path(output_root, directory=True))
        windows.validate_private_directory(output_root)
        if any(output_root.iterdir()):
            raise ValueError('Admission fence requires a fresh private output directory')
        config = load_config(config_path)
        database = config.job_db
        stack.enter_context(retained_database(database))
        base = dict(schema='cochem-owner-admission-fence/4.2.8', nonce=nonce,
                    config_sha256=config_sha256, request_sha256=request_sha256,
                    database_path=str(database), pid=os.getpid(), database_rows_modified=0)
        write_fresh(output_root/'started.json', dict(base, status='WAITING_FOR_IDLE'))
        deadline = time.monotonic()+wait_seconds
        released, ready_pin = False, None
        try:
            while True:
                try:
                    with admission_fence(database, include_catalog=True) as snapshot:
                        now = time.time()
                        raw = write_start_record(output_root/'ready.json', dict(base, status='WRITER_FENCE_HELD',
                            counts=snapshot['counts'], catalog=snapshot['catalog'], ready_at=now, expires_at=now+hold_seconds))
                        ready_pin = hashlib.sha256(raw).hexdigest()
                        expires = time.monotonic()+hold_seconds
                        while time.monotonic() < expires:
                            release = output_root/'release.json'
                            if release.exists():
                                if not release_matches(release, nonce=nonce, ready_sha256=ready_pin,
                                                       request_sha256=request_sha256):
                                    raise ValueError('Admission fence release binding differs')
                                released = True
                                break
                            time.sleep(.1)
                        break
                except BusyAdmission:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Existing native work did not drain within the bound')
                    time.sleep(1)
                except sqlite3.OperationalError as exc:
                    if 'locked' not in str(exc).lower() or time.monotonic() >= deadline or ready_pin is not None:
                        raise
                    time.sleep(.2)
            result = dict(base, status='LOCK_RELEASED' if released else 'FENCE_EXPIRED',
                          ready_sha256=ready_pin, released=released, lock_released=True)
            write_fresh(output_root/'result.json', result)
            return result
        except BaseException as exc:
            write_fresh(output_root/'held.json', dict(base, status='FENCE_HELD_PRESERVE_EVIDENCE',
                error_type=type(exc).__name__, ready_sha256=ready_pin, released=False, lock_released=True))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('config','config-sha256','output-root','nonce','request-sha256'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--wait-seconds', type=int, default=1800)
    parser.add_argument('--hold-seconds', type=int, default=240)
    args = parser.parse_args()
    try:
        result = run(args.config, args.config_sha256, args.output_root, args.nonce, args.request_sha256,
                     wait_seconds=args.wait_seconds, hold_seconds=args.hold_seconds)
        print(json.dumps(result))
        return 0 if result['released'] else 2
    except BaseException as exc:
        print(json.dumps(dict(status='ADMISSION_FENCE_HELD', error_type=type(exc).__name__, automatic_retry=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
