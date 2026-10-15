"""In-process SQLite fencing; no tasks, processes, protected state, or providers."""
import sqlite3
import pytest
from cochem_pipeline.owner_admission_fence_428 import admission_fence, BusyAdmission


@pytest.fixture
def board(tmp_path):
    path = tmp_path/'board.db'
    with sqlite3.connect(path) as conn:
        conn.executescript('''CREATE TABLE pipeline_jobs (kind TEXT,status TEXT,lease_owner TEXT,lease_expires_at REAL);
            CREATE TABLE pipeline_route_reservations (released_at REAL);
            CREATE TABLE pipeline_execution_cleanup (cleared_at REAL);
            CREATE TABLE pipeline_catalog_probes (cleanup_at REAL);
            INSERT INTO pipeline_jobs VALUES ('MACRO_PLANNING_REQUEST','IN_PROGRESS',NULL,NULL);
            INSERT INTO pipeline_jobs VALUES ('TASK_PLAN','PENDING',NULL,NULL);''')
    return path


def test_claim_writer_blocked_until_owner_releases_without_mutating_database(board):
    before = board.read_bytes()
    writer = sqlite3.connect(board, timeout=.01, isolation_level=None)
    with admission_fence(board) as counts:
        assert not any(counts.values())
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            writer.execute('BEGIN IMMEDIATE')
        assert writer.execute("SELECT count(*) FROM pipeline_jobs WHERE status='PENDING'").fetchone()[0] == 1
    assert board.read_bytes() == before
    writer.execute('BEGIN IMMEDIATE')
    writer.execute("UPDATE pipeline_jobs SET status='IN_PROGRESS' WHERE kind='TASK_PLAN'")
    writer.commit()
    writer.close()


@pytest.mark.parametrize('sql',[
    "UPDATE pipeline_jobs SET status='IN_PROGRESS' WHERE kind='TASK_PLAN'",
    "UPDATE pipeline_jobs SET lease_owner='old' WHERE kind='TASK_PLAN'",
    "UPDATE pipeline_jobs SET lease_expires_at=1 WHERE kind='TASK_PLAN'",
    'INSERT INTO pipeline_route_reservations VALUES(NULL)',
    'INSERT INTO pipeline_execution_cleanup VALUES(NULL)',
    'INSERT INTO pipeline_catalog_probes VALUES(NULL)',
])
def test_active_or_expired_unreconciled_native_state_refuses_and_releases_lock(board, sql):
    with sqlite3.connect(board) as conn:
        conn.execute(sql)
    with pytest.raises(BusyAdmission):
        with admission_fence(board):
            pytest.fail('Active native accounting admitted a stop')
    with sqlite3.connect(board, timeout=.01) as conn:
        conn.execute('BEGIN IMMEDIATE')


def test_missing_schema_never_migrates_or_treats_absence_as_idle(board):
    with sqlite3.connect(board) as conn:
        conn.execute('DROP TABLE pipeline_execution_cleanup')
    with pytest.raises(ValueError, match='accounting tables'):
        with admission_fence(board): pass


def test_exception_releases_fence(board):
    with pytest.raises(RuntimeError):
        with admission_fence(board): raise RuntimeError('owner disconnected')
    with sqlite3.connect(board, timeout=.01) as conn:
        conn.execute('BEGIN IMMEDIATE')


def test_missing_board_is_never_created(tmp_path):
    path = tmp_path/'missing.db'
    with pytest.raises(sqlite3.OperationalError):
        with admission_fence(path): pass
    assert not path.exists()
