"""Owner-run SYSTEM catalog migration with a preserved full SQLite backup."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import os

from .catalog_journal import initialize
from .catalog_slots import initialize as initialize_slots

ROOT=Path(r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261012-r7-v1')
EVIDENCE=Path(r'C:\ProgramData\CoChemPipeline427\private\r7-migration-20261012-v1')


def snapshot(conn, tables=None):
    names=tables or [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    h=hashlib.sha256()
    for name in names:
        quoted='"'+name.replace('"','""')+'"'
        schema=conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone()
        if schema is None:raise ValueError('An original table disappeared')
        h.update(json.dumps([name,schema[0]],ensure_ascii=False).encode())
        columns=[r[1] for r in conn.execute('PRAGMA table_info('+quoted+')')]
        order=','.join('"'+c.replace('"','""')+'"' for c in columns)
        for row in conn.execute('SELECT * FROM '+quoted+' ORDER BY '+order):
            payload=repr(tuple(row)).encode()
            h.update(len(payload).to_bytes(8,'big'));h.update(payload)
    return names,h.hexdigest()


def migrate(db, backup, baseline):
    db,backup=Path(db),Path(backup)
    if not db.is_file() or backup.exists():raise ValueError('Existing board and fresh backup required')
    with sqlite3.connect(db.resolve().as_uri()+'?mode=rw',uri=True,timeout=5,isolation_level=None) as conn:
        conn.execute('PRAGMA foreign_keys=ON');conn.execute('PRAGMA synchronous=FULL')
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'pipeline_catalog_%'").fetchone():
            raise ValueError('Catalog migration already exists; preserve it')
        if conn.execute("SELECT 1 FROM pipeline_jobs WHERE status IN ('IN_PROGRESS','PENDING','PENDING_RETRY')").fetchone():
            raise ValueError('Job board is not idle')
        if conn.execute('SELECT 1 FROM pipeline_execution_cleanup WHERE cleared_at IS NULL').fetchone():
            raise ValueError('Native cleanup remains unresolved')
        if conn.execute('SELECT 1 FROM pipeline_route_reservations WHERE released_at IS NULL').fetchone():
            raise ValueError('Routing reservation remains active')
        if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Job board integrity failed')
        tables,before=snapshot(conn)
        with backup.open('xb'):pass
        with sqlite3.connect(backup) as saved:conn.backup(saved)
        with sqlite3.connect(backup) as saved:
            if snapshot(saved,tables)[1]!=before:raise ValueError('Backup differs from source')
        conn.execute('BEGIN IMMEDIATE')
        try:
            if snapshot(conn,tables)[1]!=before:raise ValueError('Board changed during backup')
            initialize(conn,baseline);initialize_slots(conn)
            if snapshot(conn,tables)[1]!=before:raise ValueError('Migration altered original rows')
            conn.commit()
        except BaseException:conn.rollback();raise
    return dict(status='CATALOG_MIGRATION_VERIFIED',original_tables=tables,original_digest=before,
        baseline_digest=baseline.digest,original_rows_preserved=True,backup_preserved=True)


def rollback(db,backup,receipt):
    """Only before any R7 controller start; the caller must hold warden.lock."""
    if not Path(db).is_file() or not Path(backup).is_file():raise ValueError('Preserved database and backup required')
    with sqlite3.connect(Path(backup).resolve().as_uri()+'?mode=ro',uri=True) as saved:
        if snapshot(saved,receipt['original_tables'])[1]!=receipt['original_digest']:
            raise ValueError('Preserved backup differs')
        with sqlite3.connect(Path(db).resolve().as_uri()+'?mode=rw',uri=True) as live:
            if snapshot(live,receipt['original_tables'])[1]!=receipt['original_digest']:
                raise ValueError('Original rows changed; automatic rollback is forbidden')
            saved.backup(live)
    return {'status':'PRE_CUTOVER_DATABASE_RESTORED','backup_preserved':True}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    from .windows import require_system,validate_code_path,validate_private_directory
    from .config import load_config
    from .__main__ import service_lock
    require_system();validate_code_path(ROOT);validate_code_path(ROOT/'pipeline.json')
    validate_private_directory(EVIDENCE)
    config=load_config(ROOT/'pipeline.json');validate_private_directory(config.private_root)
    receipt=EVIDENCE/'migration.json'
    try:
        with service_lock(config.private_root/'warden.lock'):
            if args.rollback:
                result=rollback(config.job_db,EVIDENCE/'job-board-before.db',json.loads(receipt.read_text()))
                target=EVIDENCE/'rollback.json'
            else:
                if receipt.exists():raise ValueError('Preserve earlier migration receipt')
                result=migrate(config.job_db,EVIDENCE/'job-board-before.db',config.routing)
                target=receipt
            with target.open('x',encoding='utf-8') as out:
                json.dump(result,out,indent=2);out.flush();os.fsync(out.fileno())
    except Exception as exc:
        target=EVIDENCE/('rollback-held.json' if args.rollback else 'migration-held.json')
        if not target.exists():
            with target.open('x',encoding='utf-8') as out:
                json.dump(dict(status='MIGRATION_HELD_PRESERVE_EVIDENCE',error_type=type(exc).__name__,automatic_retry=False),out)
                out.flush();os.fsync(out.fileno())
        raise


if __name__=='__main__':main()
