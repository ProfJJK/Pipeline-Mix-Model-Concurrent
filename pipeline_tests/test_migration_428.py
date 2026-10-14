"""Tests for versioned 4.2.8 configuration and database migration (P428-22)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

import cochem
import cochem_mcp
import cochem_pipeline
import cochem_supervisor
from cochem_pipeline.catalog_journal import initialize as initialize_catalog_journal
from cochem_pipeline.catalog_slots import initialize as initialize_catalog_slots
from cochem_pipeline.config import PipelineConfig, load_config
from cochem_pipeline.migration_428 import (
    IncompatibleSchemaHoldError,
    MIGRATION_SCHEMA_VERSION,
    PostCutoverRollbackForbiddenError,
    RUNTIME_VERSION_428,
    detect_source_state,
    mark_cutover_428,
    migrate_428,
    rollback_428,
    snapshot,
    verify_historical_policy_replay,
    verify_version_alignment,
)
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.store import JobStore
from pipeline_tests.test_config import config_document, write_config


def _create_r4_board(db_path: Path) -> tuple[list[str], str]:
    policy_v2 = load_routing_policy({'policy_version': 2})
    store = JobStore(db_path, routing_policy=policy_v2)
    wf = store.submit('Historical R4 Objective', ['REQ-R4-01'], 1)
    wf_id = wf['workflow_id']
    store.close()
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE pipeline_jobs SET status = 'FAILED' WHERE workflow_id = ?", (wf_id,))
        conn.execute('CREATE TABLE owner_budget (account TEXT PRIMARY KEY, remaining INTEGER NOT NULL)')
        conn.execute("INSERT INTO owner_budget VALUES ('primary', 72)")
        conn.execute(
            'INSERT INTO pipeline_execution_cleanup('
            'job_id, attempt_id, fencing_token, worker_slot, pid, reason, quarantined, '
            'created_at, cleared_at, boot_id, observed_boot_id, containment_id, owner_containment_id'
            ') VALUES (?, ?, 1, ?, 1234, ?, 0, 100.0, 105.0, 1, 1, ?, ?)',
            (wf_id, 'att-r4-1', 'slot-0', 'completed cleanup', 'a' * 32, 'b' * 32),
        )
        return snapshot(conn)


def _create_r6_board(db_path: Path) -> tuple[list[str], str]:
    _create_r4_board(db_path)
    policy_v3 = load_routing_policy({'policy_version': 3})
    store = JobStore(db_path, routing_policy=policy_v3)
    wf = store.submit('Historical R6 Objective', ['REQ-R6-01'], 1)
    wf_id = wf['workflow_id']
    store.close()
    with sqlite3.connect(db_path) as conn:
        root_payload = conn.execute(
            'SELECT payload_json FROM pipeline_jobs WHERE job_id = ?', (wf_id,)
        ).fetchone()[0]
        conn.execute(
            'INSERT INTO pipeline_execution_owner_stops('
            'job_id, attempt_id, fencing_token, containment_id, boot_id, verified_at'
            ') VALUES (?, ?, 1, ?, 1, 200.0)',
            (wf_id, 'att-r6-1', 'c' * 32),
        )
        syn_id = conn.execute(
            "SELECT job_id FROM pipeline_jobs WHERE workflow_id = ? AND kind = 'SYNTHESIS'",
            (wf_id,),
        ).fetchone()[0]
        conn.execute("UPDATE pipeline_jobs SET status = 'PENDING' WHERE job_id = ?", (syn_id,))
        cands = json.dumps([{'provider': 'claude', 'model': 'claude-opus-5-5', 'reasoning_effort': 'max'}])
        conn.execute(
            'INSERT INTO pipeline_routing_jobs('
            'job_id, policy_json, score_json, candidates_json, state, created_at'
            ') VALUES (?, ?, ?, ?, ?, 200.0)',
            (syn_id, json.dumps(policy_v3.as_dict()), '{"score":10}', cands, 'READY'),
        )
        conn.execute(
            'INSERT INTO pipeline_routing_amendments('
            'job_id, previous_candidates_sha256, candidates_json, specification, reason, created_at'
            ') VALUES (?, ?, ?, ?, ?, 201.0)',
            (syn_id, hashlib.sha256(cands.encode('utf-8')).hexdigest(), cands, 'COCHEM-4.2.7', 'R6 review'),
        )
        conn.execute("UPDATE pipeline_jobs SET status = 'FAILED' WHERE workflow_id = ?", (wf_id,))
        return snapshot(conn)


def _create_r7_board(db_path: Path) -> tuple[list[str], str]:
    _create_r6_board(db_path)
    baseline = load_routing_policy({'policy_version': 3})
    with sqlite3.connect(db_path, isolation_level=None) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('BEGIN IMMEDIATE')
        initialize_catalog_journal(conn, baseline)
        initialize_catalog_slots(conn)
        conn.commit()
        return snapshot(conn)


def test_version_alignment_across_packages_pyproject_and_config(tmp_path: Path):
    assert cochem.__version__ == '4.2.8'
    assert cochem_pipeline.__version__ == '4.2.8'
    assert cochem_mcp.__version__ == '4.2.8'
    assert cochem_supervisor.__version__ == '4.2.8'

    raw = config_document(tmp_path, slots=4)
    raw['routing'] = {'policy_version': 3}
    cfg = load_config(write_config(tmp_path, raw))
    assert cfg.runtime_version == '4.2.8'

    alignment = verify_version_alignment(cfg)
    assert alignment['status'] == 'VERSION_ALIGNMENT_VERIFIED'
    assert alignment['version'] == RUNTIME_VERSION_428

    # Legacy 4.2.7 config still loads cleanly for historical inspection, but disagrees with 4.2.8 alignment check
    raw['runtime_version'] = '4.2.7'
    cfg_427 = load_config(write_config(tmp_path, raw))
    assert cfg_427.runtime_version == '4.2.7'
    with pytest.raises(ValueError, match='4.2.8'):
        verify_version_alignment(cfg_427)

    # Unknown runtime_version fails closed
    raw['runtime_version'] = '4.2.9'
    with pytest.raises(ValueError, match='runtime_version'):
        load_config(write_config(tmp_path, raw))


@pytest.mark.parametrize('builder,expected_state', [
    (_create_r4_board, 'R4'),
    (_create_r6_board, 'R6'),
    (_create_r7_board, 'R7'),
])
def test_migrate_r4_r6_and_r7_fixtures_preserves_rows_hashes_and_replays_old_policies(
    tmp_path: Path,
    builder,
    expected_state: str,
):
    db_path = tmp_path / f'board-{expected_state}.db'
    backup_path = tmp_path / f'backup-{expected_state}.db'
    ev_dir = tmp_path / f'evidence-{expected_state}'
    orig_tables, orig_digest = builder(db_path)

    with sqlite3.connect(db_path) as conn:
        assert detect_source_state(conn) == expected_state

    baseline = load_routing_policy({'policy_version': 3})
    catalog = {
        'schema': 'cochem-task-routing/1',
        'host_accepted': True,
        'profiles': {
            'luna-low': {'host_accepted': True},
            'argon-high': {'host_accepted': False},
        },
    }
    receipt = migrate_428(
        db_path,
        backup_path,
        baseline,
        task_catalog=catalog,
        known_slots={'slot-0', 'slot-1', 'slot-2', 'slot-3'},
        evidence_dir=ev_dir,
        now=1700000000.0,
    )
    assert receipt['status'] == 'MIGRATION_428_VERIFIED'
    assert receipt['schema'] == MIGRATION_SCHEMA_VERSION
    assert receipt['source_state'] == expected_state
    assert receipt['original_digest'] == orig_digest
    assert receipt['original_rows_preserved'] is True
    assert receipt['idempotent'] is False
    assert (ev_dir / 'migration-428.json').is_file()

    # Verify original tables and historical 4.2.7 policy captures were not globally rewritten
    with sqlite3.connect(db_path) as conn:
        assert detect_source_state(conn) == '4.2.8'
        assert snapshot(conn, orig_tables)[1] == orig_digest
        replay = verify_historical_policy_replay(conn)
        assert replay['historical_427_preserved'] is True
        if expected_state in ('R6', 'R7'):
            assert replay['amendments_verified'] == 1

    # Idempotent re-invocation verifies state and returns idempotent=True without mutating backup
    second = migrate_428(
        db_path,
        backup_path,
        baseline,
        task_catalog=catalog,
        known_slots={'slot-0', 'slot-1', 'slot-2', 'slot-3'},
    )
    assert second['status'] == 'MIGRATION_428_VERIFIED'
    assert second['idempotent'] is True
    assert second['original_digest'] == orig_digest


def test_rollback_before_cutover_restores_exact_pre_migration_database(tmp_path: Path):
    db_path = tmp_path / 'board.db'
    backup_path = tmp_path / 'backup.db'
    orig_tables, orig_digest = _create_r6_board(db_path)
    baseline = load_routing_policy({'policy_version': 3})

    receipt = migrate_428(db_path, backup_path, baseline, known_slots={'slot-0'})
    restored = rollback_428(db_path, backup_path, receipt)
    assert restored['status'] == 'PRE_CUTOVER_DATABASE_RESTORED'
    assert restored['backup_preserved'] is True
    assert backup_path.is_file()

    with sqlite3.connect(db_path) as conn:
        assert detect_source_state(conn) == 'R6'
        assert snapshot(conn, orig_tables)[1] == orig_digest
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name LIKE 'pipeline_428_%'"
        ).fetchall()


def test_rollback_after_cutover_or_row_mutation_is_refused_and_holds_safely(tmp_path: Path):
    db_path = tmp_path / 'board.db'
    backup_path = tmp_path / 'backup.db'
    ev_dir = tmp_path / 'evidence'
    _create_r6_board(db_path)
    baseline = load_routing_policy({'policy_version': 3})

    receipt = migrate_428(db_path, backup_path, baseline, known_slots={'slot-0'})
    cutover = mark_cutover_428(db_path, now=1700000100.0)
    assert cutover['cutover_completed'] is True

    with pytest.raises(PostCutoverRollbackForbiddenError, match='after 4.2.8 cutover'):
        rollback_428(db_path, backup_path, receipt, evidence_dir=ev_dir)
    held = json.loads((ev_dir / 'rollback-held.json').read_text(encoding='utf-8'))
    assert held['status'] == 'ROLLBACK_HELD_PRESERVE_EVIDENCE'
    assert backup_path.is_file()

    # Also test pre-cutover mutation of original rows refuses rollback
    db2 = tmp_path / 'board2.db'
    bk2 = tmp_path / 'backup2.db'
    _create_r4_board(db2)
    receipt2 = migrate_428(db2, bk2, baseline, known_slots={'slot-0'})
    with sqlite3.connect(db2) as conn:
        conn.execute('UPDATE owner_budget SET remaining = 70')
    with pytest.raises(PostCutoverRollbackForbiddenError, match='Original rows changed'):
        rollback_428(db2, bk2, receipt2)


def test_migration_refuses_live_jobs_unresolved_cleanup_and_unknown_slot_ownership(tmp_path: Path):
    baseline = load_routing_policy({'policy_version': 3})

    # 1. Unknown slot ownership on cleanup record is refused without deleting the cleanup record
    db_path = tmp_path / 'unknown-slot.db'
    backup_path = tmp_path / 'unknown-slot-backup.db'
    _create_r4_board(db_path)
    with pytest.raises(ValueError, match='unknown worker_slot ownership'):
        migrate_428(db_path, backup_path, baseline, known_slots={'slot-1', 'slot-2'})
    assert not backup_path.exists()
    with sqlite3.connect(db_path) as conn:
        count = conn.execute('SELECT count(*) FROM pipeline_execution_cleanup').fetchone()[0]
        assert count == 1

    # 2. Unresolved (cleared_at IS NULL) cleanup record is refused
    with sqlite3.connect(db_path) as conn:
        wf_id = conn.execute('SELECT job_id FROM pipeline_jobs LIMIT 1').fetchone()[0]
        conn.execute(
            'INSERT INTO pipeline_execution_cleanup('
            'job_id, attempt_id, fencing_token, worker_slot, pid, reason, quarantined, '
            'created_at, cleared_at, boot_id, observed_boot_id, containment_id, owner_containment_id'
            ') VALUES (?, ?, 2, ?, 4321, ?, 0, 110.0, NULL, 1, 1, ?, ?)',
            (wf_id, 'att-unres', 'slot-0', 'still running', 'a' * 32, 'b' * 32),
        )
    with pytest.raises(ValueError, match='cleanup remains unresolved'):
        migrate_428(db_path, backup_path, baseline, known_slots={'slot-0'})


def test_partial_migration_and_incompatible_schema_hold_with_evidence(tmp_path: Path):
    baseline = load_routing_policy({'policy_version': 3})

    # 1. Partial R7 catalog tables (only pipeline_catalog_generations/active without pipeline_catalog_probes)
    db_partial = tmp_path / 'partial-r7.db'
    bk_partial = tmp_path / 'partial-r7-backup.db'
    ev_partial = tmp_path / 'ev-partial'
    _create_r4_board(db_partial)
    with sqlite3.connect(db_partial, isolation_level=None) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('BEGIN IMMEDIATE')
        initialize_catalog_journal(conn, baseline)
        conn.commit()
    with pytest.raises(IncompatibleSchemaHoldError, match='Partial R7 catalog schema'):
        migrate_428(db_partial, bk_partial, baseline, known_slots={'slot-0'}, evidence_dir=ev_partial)
    held = json.loads((ev_partial / 'migration-held.json').read_text(encoding='utf-8'))
    assert held['status'] == 'MIGRATION_HELD_INCOMPATIBLE_SCHEMA'
    assert not bk_partial.exists()

    # 2. Missing core table column / incompatible schema
    db_incompat = tmp_path / 'incompat.db'
    bk_incompat = tmp_path / 'incompat-backup.db'
    ev_incompat = tmp_path / 'ev-incompat'
    with sqlite3.connect(db_incompat) as conn:
        conn.execute('CREATE TABLE pipeline_jobs (job_id TEXT PRIMARY KEY)')
    with pytest.raises(IncompatibleSchemaHoldError, match='Incompatible schema'):
        migrate_428(db_incompat, bk_incompat, baseline, evidence_dir=ev_incompat)
    held2 = json.loads((ev_incompat / 'migration-held.json').read_text(encoding='utf-8'))
    assert held2['status'] == 'MIGRATION_HELD_INCOMPATIBLE_SCHEMA'


def test_migration_428_cli_entrypoint_and_rollback_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from contextlib import nullcontext
    from cochem_pipeline import __main__ as main_mod
    from cochem_pipeline import migration_428 as mig_mod
    from cochem_pipeline import windows as win

    monkeypatch.setattr(win, 'require_system', lambda: None)
    monkeypatch.setattr(win, 'validate_code_path', lambda p: None)
    monkeypatch.setattr(win, 'validate_private_directory', lambda p: None)
    monkeypatch.setattr(main_mod, 'service_lock', lambda p: nullcontext())

    cand_root = tmp_path / 'Pipeline4.2.8-windows-20261014-r2'
    (cand_root / 'source' / 'docs' / '4.2.8').mkdir(parents=True)
    (cand_root / 'source' / 'pyproject.toml').write_text('version = "4.2.8"\n', encoding='utf-8')
    (cand_root / 'source' / 'docs' / '4.2.8' / 'routing-candidate.json').write_text(
        json.dumps(
            {
                'schema': 'cochem-task-routing/1',
                'models': {
                    'luna-low': {'host_accepted': True},
                    'argon-high': {'host_accepted': False},
                },
            }
        ),
        encoding='utf-8',
    )

    raw_cfg = config_document(tmp_path, slots=4)
    raw_cfg['routing'] = {'policy_version': 3}
    cfg_path = write_config(cand_root, raw_cfg)
    cfg = load_config(cfg_path)
    cfg.job_db.parent.mkdir(parents=True, exist_ok=True)
    orig_tables, orig_digest = _create_r4_board(cfg.job_db)

    ev_dir = tmp_path / 'migration-428-ev'
    ev_dir.mkdir(parents=True)

    rc = mig_mod.main(
        [
            '--state-root',
            str(cfg.job_db.parent),
            '--evidence-root',
            str(ev_dir),
            '--candidate-config',
            str(cfg_path),
        ]
    )
    assert rc == 0
    receipt = json.loads((ev_dir / 'migration-428.json').read_text(encoding='utf-8'))
    assert receipt['status'] == 'MIGRATION_428_VERIFIED'
    assert receipt['original_digest'] == orig_digest
    assert (ev_dir / 'job-board-before.db').is_file()

    with sqlite3.connect(cfg.job_db) as conn:
        accepted = json.loads(
            conn.execute('SELECT accepted_profiles_json FROM pipeline_428_task_catalog_bindings').fetchone()[0]
        )
        assert accepted == ['luna-low']

    # Rollback via CLI writes rollback-428.json and restores pre-migration board
    rc_rb = mig_mod.main(
        [
            '--state-root',
            str(cfg.job_db.parent),
            '--evidence-root',
            str(ev_dir),
            '--candidate-config',
            str(cfg_path),
            '--rollback',
        ]
    )
    assert rc_rb == 0
    rb_receipt = json.loads((ev_dir / 'rollback-428.json').read_text(encoding='utf-8'))
    assert rb_receipt['status'] == 'PRE_CUTOVER_DATABASE_RESTORED'
    assert rb_receipt['backup_preserved'] is True
    with sqlite3.connect(cfg.job_db) as conn:
        assert detect_source_state(conn) == 'R4'
        assert snapshot(conn, orig_tables)[1] == orig_digest

    bad_ev = tmp_path / 'migration-428-bad-state-root'
    bad_ev.mkdir(parents=True)
    with pytest.raises(ValueError, match='disagrees with candidate config job_db parent'):
        mig_mod.main(
            [
                '--state-root',
                str(tmp_path / 'wrong-state'),
                '--evidence-root',
                str(bad_ev),
                '--candidate-config',
                str(cfg_path),
            ]
        )
    assert (bad_ev / 'migration-held.json').is_file()
