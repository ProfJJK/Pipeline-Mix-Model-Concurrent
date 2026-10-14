"""Versioned 4.2.8 configuration and SQLite database migration (P428-22).

Preserves all 4.2.7 jobs, outputs, artifacts, routing policy captures, amendments,
cleanup proofs, and budgets without global rewriting. Supports migrating from
R4, R6, or R7-source database states with a verified pre-cutover rollback
boundary, idempotent re-verification, and explicit holds on incompatible or
partially migrated schemas.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Iterable

import cochem
import cochem_mcp
import cochem_pipeline
import cochem_supervisor
from .catalog_journal import initialize as initialize_catalog_journal
from .catalog_slots import initialize as initialize_catalog_slots
from .routing import RoutingPolicy, load_routing_policy

MIGRATION_SCHEMA_VERSION = 'cochem-4.2.8-migration/1'
RUNTIME_VERSION_428 = '4.2.8'

CORE_REQUIRED_TABLES: dict[str, set[str]] = {
    'pipeline_jobs': {'job_id', 'workflow_id', 'kind', 'status', 'payload_json', 'fencing_token', 'attempts'},
    'pipeline_outputs': {'job_id', 'attempt_id', 'fencing_token', 'output_json', 'receipt_json', 'output_sha256'},
    'pipeline_artifacts': {'job_id', 'workflow_id', 'chapter_id', 'artifact_uri', 'artifact_text', 'sha256'},
    'pipeline_events': {'id', 'workflow_id', 'job_id', 'timestamp', 'event', 'details_json'},
    'pipeline_routing_workflows': {'workflow_id', 'policy_json'},
    'pipeline_routing_jobs': {'job_id', 'policy_json', 'score_json', 'candidates_json', 'state'},
    'pipeline_routing_amendments': {'job_id', 'previous_candidates_sha256', 'candidates_json', 'specification'},
    'pipeline_route_reservations': {'reservation_id', 'job_id', 'attempt_id', 'fencing_token', 'provider', 'model'},
    'pipeline_route_holds': {'scope', 'resource_key', 'until_at', 'reason'},
    'pipeline_execution_cleanup': {'job_id', 'attempt_id', 'fencing_token', 'worker_slot', 'quarantined', 'cleared_at'},
    'pipeline_execution_owner_stops': {'job_id', 'attempt_id', 'fencing_token', 'containment_id', 'boot_id'},
}

R7_CATALOG_TABLES = frozenset({
    'pipeline_catalog_generations',
    'pipeline_catalog_active',
    'pipeline_catalog_probes',
})

MIGRATION_428_TABLES = frozenset({
    'pipeline_428_migration_state',
    'pipeline_428_task_catalog_bindings',
})

SCHEMA_428_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS pipeline_428_migration_state (
        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
        schema_version TEXT NOT NULL CHECK(schema_version = 'cochem-4.2.8-migration/1'),
        runtime_version TEXT NOT NULL CHECK(runtime_version = '4.2.8'),
        source_state TEXT NOT NULL CHECK(source_state IN ('R4', 'R6', 'R7')),
        original_tables_json TEXT NOT NULL CHECK(json_valid(original_tables_json)),
        original_digest TEXT NOT NULL CHECK(length(original_digest) = 64),
        baseline_digest TEXT NOT NULL CHECK(length(baseline_digest) = 64),
        task_catalog_sha256 TEXT CHECK(task_catalog_sha256 IS NULL OR length(task_catalog_sha256) = 64),
        migrated_at REAL NOT NULL,
        cutover_completed INTEGER NOT NULL DEFAULT 0 CHECK(cutover_completed IN (0, 1)),
        cutover_at REAL
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS pipeline_428_migration_immutable
    BEFORE UPDATE OF singleton, schema_version, runtime_version, source_state,
                     original_tables_json, original_digest, baseline_digest,
                     task_catalog_sha256, migrated_at
    ON pipeline_428_migration_state
    BEGIN
        SELECT RAISE(ABORT, '4.2.8 migration baseline metadata is immutable');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS pipeline_428_migration_cutover_monotonic
    BEFORE UPDATE OF cutover_completed ON pipeline_428_migration_state
    WHEN OLD.cutover_completed = 1 AND NEW.cutover_completed != 1
    BEGIN
        SELECT RAISE(ABORT, '4.2.8 cutover completion cannot be cleared in-place');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS pipeline_428_migration_no_delete
    BEFORE DELETE ON pipeline_428_migration_state
    BEGIN
        SELECT RAISE(ABORT, '4.2.8 migration state cannot be deleted');
    END
    """,
    """
    CREATE TABLE IF NOT EXISTS pipeline_428_task_catalog_bindings (
        catalog_sha256 TEXT PRIMARY KEY CHECK(length(catalog_sha256) = 64),
        schema_name TEXT NOT NULL CHECK(schema_name = 'cochem-task-routing/1'),
        accepted_profiles_json TEXT NOT NULL CHECK(json_valid(accepted_profiles_json)),
        recorded_at REAL NOT NULL
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS pipeline_428_task_catalog_no_update
    BEFORE UPDATE ON pipeline_428_task_catalog_bindings
    BEGIN
        SELECT RAISE(ABORT, '4.2.8 task catalog bindings are immutable');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS pipeline_428_task_catalog_no_delete
    BEFORE DELETE ON pipeline_428_task_catalog_bindings
    BEGIN
        SELECT RAISE(ABORT, '4.2.8 task catalog bindings cannot be deleted');
    END
    """,
)


class IncompatibleSchemaHoldError(ValueError):
    """Raised when the database schema is partial, corrupt, or incompatible with 4.2.8."""


class PostCutoverRollbackForbiddenError(ValueError):
    """Raised when an automatic database overwrite rollback is attempted after cutover or mutation."""


def _write_hold_receipt(evidence_dir: Path | None, filename: str, payload: dict[str, Any]) -> None:
    if evidence_dir is None:
        return
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    target = evidence_dir / filename
    if not target.exists():
        with target.open('x', encoding='utf-8') as out:
            json.dump(payload, out, indent=2, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())


def verify_version_alignment(config: Any = None, *, pyproject_path: Path | None = None) -> dict[str, Any]:
    """Verify that wheel/pyproject, runtime packages, and PipelineConfig versions agree on 4.2.8."""
    versions = {
        'cochem': getattr(cochem, '__version__', None),
        'cochem_pipeline': getattr(cochem_pipeline, '__version__', None),
        'cochem_mcp': getattr(cochem_mcp, '__version__', None),
        'cochem_supervisor': getattr(cochem_supervisor, '__version__', None),
    }
    if any(v != RUNTIME_VERSION_428 for v in versions.values()):
        raise ValueError(f'Package versions do not all equal {RUNTIME_VERSION_428}: {versions}')
    if config is not None:
        cfg_version = getattr(config, 'runtime_version', None)
        if cfg_version != RUNTIME_VERSION_428:
            raise ValueError(f'PipelineConfig.runtime_version is {cfg_version!r}, expected {RUNTIME_VERSION_428!r}')
        versions['config'] = cfg_version
    if pyproject_path is None:
        candidate = Path(__file__).resolve().parents[2] / 'pyproject.toml'
        if candidate.is_file():
            pyproject_path = candidate
    if pyproject_path is not None:
        raw = Path(pyproject_path).read_text(encoding='utf-8')
        match = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', raw)
        if match is None or match.group(1) != RUNTIME_VERSION_428:
            raise ValueError(
                f'pyproject.toml version {match.group(1) if match else None!r} does not match {RUNTIME_VERSION_428!r}'
            )
        versions['pyproject'] = match.group(1)
    return {'status': 'VERSION_ALIGNMENT_VERIFIED', 'version': RUNTIME_VERSION_428, 'components': versions}


def snapshot(conn: sqlite3.Connection, tables: Iterable[str] | None = None) -> tuple[list[str], str]:
    """Compute a deterministic SHA-256 over table schemas and ordered row contents."""
    names = list(tables) if tables is not None else [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    h = hashlib.sha256()
    for name in names:
        quoted = '"' + name.replace('"', '""') + '"'
        schema = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
        if schema is None:
            raise ValueError(f'Original table disappeared: {name}')
        h.update(json.dumps([name, schema[0]], ensure_ascii=False).encode('utf-8'))
        columns = [r[1] for r in conn.execute('PRAGMA table_info(' + quoted + ')')]
        order = ','.join('"' + c.replace('"', '""') + '"' for c in columns)
        for row in conn.execute('SELECT * FROM ' + quoted + ' ORDER BY ' + order):
            payload = repr(tuple(row)).encode('utf-8')
            h.update(len(payload).to_bytes(8, 'big'))
            h.update(payload)
    return names, h.hexdigest()


def detect_source_state(conn: sqlite3.Connection) -> str:
    """Classify the installed SQLite board state as R4, R6, R7, or 4.2.8, or fail closed."""
    existing_tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    for req_table, req_cols in CORE_REQUIRED_TABLES.items():
        if req_table not in existing_tables:
            raise IncompatibleSchemaHoldError(f'Incompatible schema: missing core table {req_table}')
        quoted = '"' + req_table.replace('"', '""') + '"'
        actual_cols = {r[1] for r in conn.execute('PRAGMA table_info(' + quoted + ')')}
        missing_cols = req_cols - actual_cols
        if missing_cols:
            raise IncompatibleSchemaHoldError(
                f'Incompatible schema: table {req_table} missing columns {sorted(missing_cols)}'
            )

    present_catalog = existing_tables & R7_CATALOG_TABLES
    if present_catalog and present_catalog != R7_CATALOG_TABLES:
        raise IncompatibleSchemaHoldError(
            f'Partial R7 catalog schema detected: present={sorted(present_catalog)}, '
            f'missing={sorted(R7_CATALOG_TABLES - present_catalog)}'
        )

    any_other_catalog = {t for t in existing_tables if t.startswith('pipeline_catalog_')} - R7_CATALOG_TABLES
    if any_other_catalog:
        raise IncompatibleSchemaHoldError(f'Unknown catalog tables present: {sorted(any_other_catalog)}')

    present_428 = {t for t in existing_tables if t.startswith('pipeline_428_')}
    if present_428:
        if present_428 != MIGRATION_428_TABLES:
            raise IncompatibleSchemaHoldError(
                f'Partial or unknown 4.2.8 migration tables detected: {sorted(present_428)}'
            )
        row = conn.execute(
            'SELECT schema_version, runtime_version, source_state FROM pipeline_428_migration_state WHERE singleton = 1'
        ).fetchone()
        if row is None or row[0] != MIGRATION_SCHEMA_VERSION or row[1] != RUNTIME_VERSION_428:
            raise IncompatibleSchemaHoldError('Missing or incompatible pipeline_428_migration_state singleton row')
        if present_catalog != R7_CATALOG_TABLES:
            raise IncompatibleSchemaHoldError('4.2.8 migration state exists without R7 catalog tables')
        return '4.2.8'

    if present_catalog == R7_CATALOG_TABLES:
        state_row = conn.execute('SELECT policy_digest FROM pipeline_catalog_active WHERE singleton = 1').fetchone()
        if state_row is None:
            raise IncompatibleSchemaHoldError('R7 pipeline_catalog_active table has no singleton row')
        return 'R7'

    has_r6_activity = (
        conn.execute('SELECT 1 FROM pipeline_execution_owner_stops LIMIT 1').fetchone() is not None
        or conn.execute('SELECT 1 FROM pipeline_routing_amendments LIMIT 1').fetchone() is not None
    )
    return 'R6' if has_r6_activity else 'R4'


def verify_historical_policy_replay(conn: sqlite3.Connection) -> dict[str, Any]:
    """Verify that all historical 4.2.7 routing captures and amendments replay without mutation."""
    wf_rows = conn.execute('SELECT workflow_id, policy_json FROM pipeline_routing_workflows ORDER BY workflow_id').fetchall()
    for wf_id, policy_json in wf_rows:
        raw_policy = json.loads(policy_json)
        if not isinstance(raw_policy, dict) or raw_policy.get('policy_version') not in (2, 3):
            raise IncompatibleSchemaHoldError(f'Workflow {wf_id} has unsupported historical policy_version')
        replayed = load_routing_policy(raw_policy)
        if replayed.as_dict()['policy_version'] != raw_policy['policy_version']:
            raise IncompatibleSchemaHoldError(f'Workflow {wf_id} policy failed exact version replay')

    job_rows = conn.execute(
        'SELECT job_id, policy_json, score_json, candidates_json FROM pipeline_routing_jobs ORDER BY job_id'
    ).fetchall()
    for job_id, policy_json, score_json, candidates_json in job_rows:
        raw_policy = json.loads(policy_json)
        raw_score = json.loads(score_json)
        raw_candidates = json.loads(candidates_json)
        if not isinstance(raw_policy, dict) or raw_policy.get('policy_version') not in (2, 3):
            raise IncompatibleSchemaHoldError(f'Job {job_id} has unsupported historical policy_version')
        load_routing_policy(raw_policy)
        if not isinstance(raw_score, dict) or not isinstance(raw_candidates, list) or not raw_candidates:
            raise IncompatibleSchemaHoldError(f'Job {job_id} has malformed routing score or candidate capture')

    amend_rows = conn.execute(
        'SELECT job_id, specification, candidates_json FROM pipeline_routing_amendments ORDER BY job_id'
    ).fetchall()
    for job_id, specification, candidates_json in amend_rows:
        if specification != 'COCHEM-4.2.7':
            raise IncompatibleSchemaHoldError(
                f'Historical amendment on {job_id} had specification rewritten to {specification!r}'
            )
        if not isinstance(json.loads(candidates_json), list):
            raise IncompatibleSchemaHoldError(f'Historical amendment on {job_id} has invalid candidates_json')

    return {
        'workflows_verified': len(wf_rows),
        'jobs_verified': len(job_rows),
        'amendments_verified': len(amend_rows),
        'historical_427_preserved': True,
    }


def verify_cleanup_and_idle_state(
    conn: sqlite3.Connection,
    *,
    known_slots: Iterable[str] | None = None,
) -> None:
    """Refuse active jobs, active route reservations, or unresolved/unknown cleanup ownership."""
    if conn.execute(
        "SELECT 1 FROM pipeline_jobs WHERE status IN ('IN_PROGRESS', 'PENDING', 'PENDING_RETRY') LIMIT 1"
    ).fetchone():
        raise ValueError('Job board is not idle')
    if conn.execute('SELECT 1 FROM pipeline_route_reservations WHERE released_at IS NULL LIMIT 1').fetchone():
        raise ValueError('Routing reservation remains active')
    if conn.execute(
        'SELECT 1 FROM pipeline_execution_cleanup WHERE cleared_at IS NULL OR quarantined != 0 LIMIT 1'
    ).fetchone():
        raise ValueError('Native cleanup remains unresolved or quarantined')

    allowed_slots = set(known_slots) if known_slots is not None else None
    for (slot,) in conn.execute('SELECT worker_slot FROM pipeline_execution_cleanup'):
        if not isinstance(slot, str) or not slot.strip():
            raise ValueError('Execution cleanup record has missing or unknown worker_slot ownership')
        if allowed_slots is not None and slot not in allowed_slots:
            raise ValueError(f'Execution cleanup record has unknown worker_slot ownership: {slot}')


def migrate_428(
    db: Path | str,
    backup: Path | str,
    baseline: RoutingPolicy,
    *,
    task_catalog: dict[str, Any] | None = None,
    known_slots: Iterable[str] | None = None,
    evidence_dir: Path | str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Migrate an installed R4, R6, or R7-source SQLite board to 4.2.8 or re-verify idempotently."""
    db_path, backup_path = Path(db), Path(backup)
    ev_dir = Path(evidence_dir) if evidence_dir is not None else None
    if not db_path.is_file():
        raise ValueError('Existing job_board.db is required for 4.2.8 migration')
    if not isinstance(baseline, RoutingPolicy) or baseline.as_dict().get('policy_version') != 3:
        raise ValueError('4.2.8 migration requires a v3 RoutingPolicy baseline')

    catalog_sha256: str | None = None
    accepted_profiles: list[str] = []
    if task_catalog is not None:
        if not isinstance(task_catalog, dict) or task_catalog.get('schema') != 'cochem-task-routing/1':
            raise ValueError('task_catalog must be a cochem-task-routing/1 mapping')
        raw_catalog = json.dumps(task_catalog, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        catalog_sha256 = hashlib.sha256(raw_catalog).hexdigest()
        profiles = task_catalog.get('profiles') or task_catalog.get('models') or {}
        if isinstance(profiles, dict):
            accepted_profiles = sorted(
                pid for pid, pdata in profiles.items()
                if isinstance(pdata, dict) and pdata.get('host_accepted') is True
            )

    timestamp = float(time.time() if now is None else now)

    try:
        with sqlite3.connect(db_path.resolve().as_uri() + '?mode=rw', uri=True, timeout=5, isolation_level=None) as conn:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('PRAGMA synchronous=FULL')
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise IncompatibleSchemaHoldError('SQLite integrity_check failed on job_board.db')

            source_state = detect_source_state(conn)
            verify_cleanup_and_idle_state(conn, known_slots=known_slots)
            replay_summary = verify_historical_policy_replay(conn)

            if source_state == '4.2.8':
                row = conn.execute(
                    'SELECT source_state, original_tables_json, original_digest, baseline_digest, '
                    'task_catalog_sha256, cutover_completed FROM pipeline_428_migration_state WHERE singleton = 1'
                ).fetchone()
                orig_tables = json.loads(row[1])
                orig_digest = row[2]
                recorded_baseline = row[3]
                recorded_catalog = row[4]
                cutover_completed = bool(row[5])
                if recorded_baseline != baseline.digest:
                    raise IncompatibleSchemaHoldError('Existing 4.2.8 migration has a different routing baseline digest')
                if catalog_sha256 is not None and recorded_catalog not in (None, catalog_sha256):
                    raise IncompatibleSchemaHoldError('Existing 4.2.8 migration has a different task_catalog_sha256')
                if not backup_path.is_file():
                    raise ValueError('Idempotent 4.2.8 migration check requires the preserved backup database')
                with sqlite3.connect(backup_path.resolve().as_uri() + '?mode=ro', uri=True) as saved:
                    if snapshot(saved, orig_tables)[1] != orig_digest:
                        raise ValueError('Preserved backup database does not match recorded original_digest')
                if not cutover_completed and snapshot(conn, orig_tables)[1] != orig_digest:
                    raise ValueError('Pre-cutover 4.2.8 board modified original rows')
                return {
                    'schema': MIGRATION_SCHEMA_VERSION,
                    'status': 'MIGRATION_428_VERIFIED',
                    'runtime_version': RUNTIME_VERSION_428,
                    'source_state': row[0],
                    'original_tables': orig_tables,
                    'original_digest': orig_digest,
                    'baseline_digest': recorded_baseline,
                    'task_catalog_sha256': recorded_catalog,
                    'historical_replay': replay_summary,
                    'original_rows_preserved': True,
                    'backup_preserved': True,
                    'cutover_completed': cutover_completed,
                    'idempotent': True,
                }

            if backup_path.exists():
                raise ValueError('Fresh backup path required before first 4.2.8 migration')

            original_tables, before_digest = snapshot(conn)
            with backup_path.open('xb'):
                pass
            with sqlite3.connect(backup_path) as saved:
                conn.backup(saved)
            with sqlite3.connect(backup_path) as saved:
                if snapshot(saved, original_tables)[1] != before_digest:
                    raise ValueError('Backup differs from source database')

            conn.execute('BEGIN IMMEDIATE')
            try:
                if snapshot(conn, original_tables)[1] != before_digest:
                    raise ValueError('Database changed during backup')
                if source_state in ('R4', 'R6'):
                    initialize_catalog_journal(conn, baseline)
                    initialize_catalog_slots(conn)
                else:
                    gen_row = conn.execute(
                        'SELECT policy_digest FROM pipeline_catalog_generations LIMIT 1'
                    ).fetchone()
                    if gen_row is None:
                        raise IncompatibleSchemaHoldError('R7 catalog table missing baseline generation')

                for stmt in SCHEMA_428_STATEMENTS:
                    conn.execute(stmt)
                conn.execute(
                    'INSERT INTO pipeline_428_migration_state('
                    'singleton, schema_version, runtime_version, source_state, '
                    'original_tables_json, original_digest, baseline_digest, '
                    'task_catalog_sha256, migrated_at, cutover_completed, cutover_at'
                    ') VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)',
                    (
                        MIGRATION_SCHEMA_VERSION,
                        RUNTIME_VERSION_428,
                        source_state,
                        json.dumps(original_tables),
                        before_digest,
                        baseline.digest,
                        catalog_sha256,
                        timestamp,
                    ),
                )
                if catalog_sha256 is not None:
                    conn.execute(
                        'INSERT INTO pipeline_428_task_catalog_bindings('
                        'catalog_sha256, schema_name, accepted_profiles_json, recorded_at'
                        ') VALUES (?, ?, ?, ?)',
                        (catalog_sha256, 'cochem-task-routing/1', json.dumps(accepted_profiles), timestamp),
                    )
                if snapshot(conn, original_tables)[1] != before_digest:
                    raise ValueError('4.2.8 migration altered original table rows or schemas')
                verify_historical_policy_replay(conn)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
    except IncompatibleSchemaHoldError as exc:
        _write_hold_receipt(
            ev_dir,
            'migration-held.json',
            {
                'schema': MIGRATION_SCHEMA_VERSION,
                'status': 'MIGRATION_HELD_INCOMPATIBLE_SCHEMA',
                'error_type': type(exc).__name__,
                'reason': str(exc),
                'automatic_retry': False,
            },
        )
        raise
    except Exception as exc:
        _write_hold_receipt(
            ev_dir,
            'migration-held.json',
            {
                'schema': MIGRATION_SCHEMA_VERSION,
                'status': 'MIGRATION_HELD_PRESERVE_EVIDENCE',
                'error_type': type(exc).__name__,
                'reason': str(exc),
                'automatic_retry': False,
            },
        )
        raise

    result = {
        'schema': MIGRATION_SCHEMA_VERSION,
        'status': 'MIGRATION_428_VERIFIED',
        'runtime_version': RUNTIME_VERSION_428,
        'source_state': source_state,
        'original_tables': original_tables,
        'original_digest': before_digest,
        'baseline_digest': baseline.digest,
        'task_catalog_sha256': catalog_sha256,
        'historical_replay': replay_summary,
        'original_rows_preserved': True,
        'backup_preserved': True,
        'cutover_completed': False,
        'idempotent': False,
    }
    if ev_dir is not None:
        ev_dir.mkdir(parents=True, exist_ok=True)
        receipt_file = ev_dir / 'migration-428.json'
        if not receipt_file.exists():
            with receipt_file.open('x', encoding='utf-8') as out:
                json.dump(result, out, indent=2, sort_keys=True)
                out.flush()
                os.fsync(out.fileno())
    return result


def mark_cutover_428(db: Path | str, *, now: float | None = None) -> dict[str, Any]:
    """Record that 4.2.8 runtime cutover has occurred, closing automatic DB overwrite rollback."""
    db_path = Path(db)
    if not db_path.is_file():
        raise ValueError('Database file required to mark 4.2.8 cutover')
    timestamp = float(time.time() if now is None else now)
    with sqlite3.connect(db_path.resolve().as_uri() + '?mode=rw', uri=True, timeout=5, isolation_level=None) as conn:
        conn.execute('BEGIN IMMEDIATE')
        try:
            row = conn.execute(
                'SELECT cutover_completed FROM pipeline_428_migration_state WHERE singleton = 1'
            ).fetchone()
            if row is None:
                raise ValueError('4.2.8 migration state not found')
            conn.execute(
                'UPDATE pipeline_428_migration_state SET cutover_completed = 1, cutover_at = COALESCE(cutover_at, ?) '
                'WHERE singleton = 1',
                (timestamp,),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return {'status': 'CUTOVER_428_RECORDED', 'cutover_completed': True, 'cutover_at': timestamp}


def rollback_428(
    db: Path | str,
    backup: Path | str,
    receipt: dict[str, Any],
    *,
    evidence_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Restore the pre-migration SQLite backup only before cutover and before any row mutation."""
    db_path, backup_path = Path(db), Path(backup)
    ev_dir = Path(evidence_dir) if evidence_dir is not None else None
    if not db_path.is_file() or not backup_path.is_file():
        raise ValueError('Preserved database and backup required')
    if not isinstance(receipt, dict) or 'original_tables' not in receipt or 'original_digest' not in receipt:
        raise ValueError('Valid 4.2.8 migration receipt required for rollback')

    try:
        with sqlite3.connect(backup_path.resolve().as_uri() + '?mode=ro', uri=True) as saved:
            if snapshot(saved, receipt['original_tables'])[1] != receipt['original_digest']:
                raise ValueError('Preserved backup differs from receipt original_digest')
            with sqlite3.connect(db_path.resolve().as_uri() + '?mode=rw', uri=True) as live:
                mig_row = live.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='pipeline_428_migration_state'"
                ).fetchone()
                if mig_row is not None:
                    state_row = live.execute(
                        'SELECT cutover_completed FROM pipeline_428_migration_state WHERE singleton = 1'
                    ).fetchone()
                    if state_row is not None and state_row[0] == 1:
                        raise PostCutoverRollbackForbiddenError(
                            'Automatic database rollback is forbidden after 4.2.8 cutover; preserve post-cutover state'
                        )
                if snapshot(live, receipt['original_tables'])[1] != receipt['original_digest']:
                    raise PostCutoverRollbackForbiddenError(
                        'Original rows changed after migration; automatic rollback is forbidden'
                    )
                saved.backup(live)
                if snapshot(live, receipt['original_tables'])[1] != receipt['original_digest']:
                    raise ValueError('Restored database failed original_digest verification')
    except Exception as exc:
        _write_hold_receipt(
            ev_dir,
            'rollback-held.json',
            {
                'schema': MIGRATION_SCHEMA_VERSION,
                'status': 'ROLLBACK_HELD_PRESERVE_EVIDENCE',
                'error_type': type(exc).__name__,
                'reason': str(exc),
                'automatic_retry': False,
            },
        )
        raise

    result = {
        'schema': MIGRATION_SCHEMA_VERSION,
        'status': 'PRE_CUTOVER_DATABASE_RESTORED',
        'source_state': receipt.get('source_state'),
        'backup_preserved': True,
    }
    if ev_dir is not None:
        ev_dir.mkdir(parents=True, exist_ok=True)
        rollback_file = ev_dir / 'rollback-428.json'
        if not rollback_file.exists():
            with rollback_file.open('x', encoding='utf-8') as out:
                json.dump(result, out, indent=2, sort_keys=True)
                out.flush()
                os.fsync(out.fileno())
    return result


def main(argv: list[str] | None = None) -> int:
    """SYSTEM CLI entrypoint for 4.2.8 migration and pre-cutover rollback."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root', type=Path)
    parser.add_argument('--evidence-root', type=Path, required=True)
    parser.add_argument('--candidate-config', type=Path, required=True)
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args(argv)

    from . import windows as win
    from .__main__ import service_lock
    from .config import load_config

    evidence_dir = Path(args.evidence_root)
    candidate_config = Path(args.candidate_config)
    candidate_root = candidate_config.parent

    try:
        win.require_system()
        win.validate_code_path(candidate_root)
        win.validate_code_path(candidate_config)
        win.validate_private_directory(evidence_dir)
        config = load_config(candidate_config)
        pyproject = candidate_root / 'source' / 'pyproject.toml'
        verify_version_alignment(
            config,
            pyproject_path=pyproject if pyproject.is_file() else None,
        )
        win.validate_private_directory(config.private_root)

        task_catalog: dict[str, Any] | None = None
        routing_cand_path = candidate_root / 'source' / 'docs' / '4.2.8' / 'routing-candidate.json'
        if routing_cand_path.is_file():
            win.validate_code_path(routing_cand_path)
            task_catalog = json.loads(routing_cand_path.read_text(encoding='utf-8'))

        receipt_path = evidence_dir / 'migration-428.json'
        backup_path = evidence_dir / 'job-board-before.db'
        with service_lock(config.private_root / 'warden.lock'):
            if args.rollback:
                receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                rollback_428(config.job_db, backup_path, receipt, evidence_dir=evidence_dir)
            else:
                if receipt_path.exists():
                    raise ValueError('Preserve earlier 4.2.8 migration receipt')
                migrate_428(
                    config.job_db,
                    backup_path,
                    config.routing,
                    task_catalog=task_catalog,
                    known_slots=set(config.slot_roots),
                    evidence_dir=evidence_dir,
                )
        return 0
    except Exception as exc:
        _write_hold_receipt(
            evidence_dir,
            'rollback-held.json' if args.rollback else 'migration-held.json',
            {
                'schema': MIGRATION_SCHEMA_VERSION,
                'status': (
                    'ROLLBACK_HELD_PRESERVE_EVIDENCE'
                    if args.rollback
                    else 'MIGRATION_HELD_PRESERVE_EVIDENCE'
                ),
                'error_type': type(exc).__name__,
                'reason': str(exc),
                'automatic_retry': False,
            },
        )
        raise


if __name__ == '__main__':
    raise SystemExit(main())
