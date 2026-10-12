"""Ordinary temporary database migration and rollback, never SYSTEM main."""
import sqlite3
import pytest
from cochem_pipeline.r7_migration import migrate,rollback,snapshot
from cochem_pipeline.store import JobStore
from cochem_pipeline.routing import load_routing_policy


def test_preserves_original_tables_and_rollback_backup(tmp_path):
    db=tmp_path/'board.db';backup=tmp_path/'before.db';baseline=load_routing_policy({'policy_version':3})
    store=JobStore(db,routing_policy=baseline);store.close()
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE owner_budget (remaining INTEGER)');conn.execute('INSERT INTO owner_budget VALUES(72)')
        tables,before=snapshot(conn)
    result=migrate(db,backup,baseline)
    with sqlite3.connect(db) as conn:assert snapshot(conn,tables)[1]==before
    with pytest.raises(ValueError):migrate(db,backup,baseline)
    assert rollback(db,backup,result)['status']=='PRE_CUTOVER_DATABASE_RESTORED'
    with sqlite3.connect(db) as conn:
        assert snapshot(conn,tables)[1]==before
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'pipeline_catalog_%'").fetchone()
    assert backup.exists()


def test_busy_board_and_changed_original_rows_refuse_mutation(tmp_path):
    db=tmp_path/'board.db';backup=tmp_path/'before.db';baseline=load_routing_policy({'policy_version':3})
    store=JobStore(db,routing_policy=baseline)
    store.submit('Busy',['Keep work'],1)
    with pytest.raises(ValueError,match='idle'):migrate(db,backup,baseline)
    assert not backup.exists();store.close()


def test_rollback_refuses_new_activity_and_preserves_backup(tmp_path):
    db=tmp_path/'board.db';backup=tmp_path/'before.db';baseline=load_routing_policy({'policy_version':3})
    store=JobStore(db,routing_policy=baseline);store.close()
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE owner_budget (remaining INTEGER)');conn.execute('INSERT INTO owner_budget VALUES(72)')
    receipt=migrate(db,backup,baseline)
    with sqlite3.connect(db) as conn:conn.execute('UPDATE owner_budget SET remaining=71')
    with pytest.raises(ValueError,match='changed'):rollback(db,backup,receipt)
    with sqlite3.connect(db) as conn:assert conn.execute('SELECT remaining FROM owner_budget').fetchone()[0]==71
    assert backup.exists()


def test_missing_backup_never_creates_an_empty_database(tmp_path):
    db=tmp_path/'missing.db';backup=tmp_path/'missing-backup.db'
    with pytest.raises(ValueError):rollback(db,backup,{})
    assert not db.exists() and not backup.exists()
