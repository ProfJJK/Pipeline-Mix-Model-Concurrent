"""Durable shared-capacity accounting for R7 probes; no provider execution.

Only the SYSTEM integration may reserve or attest cleanup. Lease expiry never
frees capacity: after a crash, the native containment must be reconciled first.
Publication consumes completed evidence in the caller's job-board transaction.
"""
from __future__ import annotations

import json
import time
import uuid

from . import catalog_journal as journal
from .catalog_activation import _json
from .catalog_authority import CatalogAuthority


def initialize(conn):
    """Explicit migration, separate from ordinary JobStore construction."""
    journal._transaction(conn)
    conn.execute('''CREATE TABLE IF NOT EXISTS pipeline_catalog_probes (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        reservation_id TEXT NOT NULL UNIQUE, request_id TEXT NOT NULL,
        plan_digest TEXT NOT NULL, pointer_sha256 TEXT NOT NULL,
        proposal_sha256 TEXT NOT NULL, target_json TEXT NOT NULL,
        worker_slot TEXT NOT NULL, containment_id TEXT NOT NULL,
        boot_id INTEGER NOT NULL, lease_expires_at REAL NOT NULL,
        reserved_at REAL NOT NULL, cleanup_at REAL, result_json TEXT,
        consumed_at REAL, UNIQUE(request_id,target_json))''')
    conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS pipeline_catalog_worker_busy
        ON pipeline_catalog_probes(worker_slot) WHERE cleanup_at IS NULL''')
    conn.execute('''CREATE TRIGGER IF NOT EXISTS pipeline_catalog_probe_identity
        BEFORE UPDATE OF sequence,reservation_id,request_id,plan_digest,pointer_sha256,
        proposal_sha256,target_json,worker_slot,containment_id,boot_id,reserved_at
        ON pipeline_catalog_probes
        BEGIN SELECT RAISE(ABORT,'catalog probe identity is immutable'); END''')
    conn.execute('''CREATE TRIGGER IF NOT EXISTS pipeline_catalog_probe_history
        BEFORE DELETE ON pipeline_catalog_probes
        BEGIN SELECT RAISE(ABORT,'catalog probe history is immutable'); END''')
    conn.execute('''CREATE TRIGGER IF NOT EXISTS pipeline_catalog_probe_final
        BEFORE UPDATE OF cleanup_at,result_json ON pipeline_catalog_probes
        WHEN OLD.cleanup_at IS NOT NULL
        BEGIN SELECT RAISE(ABORT,'catalog probe outcome is immutable'); END''')


def occupancy(conn, worker_slot=None):
    """Available before explicit migration, so legacy JobStore is unchanged."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pipeline_catalog_probes'").fetchone() is None:
        return 0
    if worker_slot is None:
        return conn.execute('SELECT count(*) FROM pipeline_catalog_probes WHERE cleanup_at IS NULL').fetchone()[0]
    return conn.execute('''SELECT count(*) FROM pipeline_catalog_probes
        WHERE cleanup_at IS NULL AND worker_slot=?''',(worker_slot,)).fetchone()[0]


def reserve(conn, authority, target, *, worker_slot, containment_id, boot_id,
            lease_seconds=1800, max_workers=4):
    """Account for capacity only; target/provider admission is still required.

    This is intentionally not a dispatch API. A returned reservation never proves
    credentials, selector support, native containment or permission to execute.
    """
    journal._transaction(conn)
    if not isinstance(authority,CatalogAuthority):raise ValueError('Catalog authority required')
    if (type(max_workers) is not int or not 1<=max_workers<=4
            or worker_slot not in {f'slot{i}' for i in range(1,7)}
            or type(boot_id) is not int or boot_id<1
            or not isinstance(containment_id,str) or len(containment_id)!=32
            or any(c not in '0123456789abcdef' for c in containment_id)
            or type(lease_seconds) not in (int,float) or not 0<lease_seconds<=1800):
        raise ValueError('Invalid catalog capacity reservation')
    target=tuple(target)
    if target not in set(authority.change.changed_targets)|{authority.change.control_target}:
        raise ValueError('Target is outside protected change plan')
    if journal.active_policy(conn).digest!=authority.change.previous_policy_digest:
        raise ValueError('Catalog plan is stale')
    encoded=_json(list(target))
    if conn.execute('SELECT 1 FROM pipeline_catalog_probes WHERE request_id=? AND target_json=?',
                    (authority.request_id,encoded)).fetchone() is not None:
        raise ValueError('Probe already recorded; no automatic retry')
    # Cleanup quarantine occupies capacity even if the job lease was reaped.
    from .routing_store import cleanup_barriers
    if cleanup_barriers(conn):return None
    active=conn.execute("SELECT count(*) FROM pipeline_jobs WHERE status='IN_PROGRESS' AND kind NOT IN ('MACRO_PLANNING_REQUEST','CODE_REQUEST')").fetchone()[0]
    if active+occupancy(conn)>=max_workers or occupancy(conn,worker_slot):return None
    if conn.execute('''SELECT 1 FROM pipeline_jobs j JOIN pipeline_worker_ownership w USING(job_id)
        WHERE j.status='IN_PROGRESS' AND w.slot=?''',(worker_slot,)).fetchone():return None
    if conn.execute('''SELECT 1 FROM pipeline_route_reservations
        WHERE released_at IS NULL AND worker_slot=?''',(worker_slot,)).fetchone():return None
    now=time.time();identity=uuid.uuid4().hex
    cursor=conn.execute('''INSERT INTO pipeline_catalog_probes
        (reservation_id,request_id,plan_digest,pointer_sha256,proposal_sha256,target_json,
         worker_slot,containment_id,boot_id,lease_expires_at,reserved_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
        (identity,authority.request_id,authority.change.digest,authority.pointer_sha256,
         authority.proposal_sha256,encoded,worker_slot,containment_id,boot_id,now+lease_seconds,now))
    return {'reservation_id':identity,'fencing_token':cursor.lastrowid,
            'worker_slot':worker_slot,'containment_id':containment_id,'boot_id':boot_id}


def finish(conn, reservation, *, cleanup_verified, accepted):
    """Trusted integration attests native closure; never called by worker output."""
    journal._transaction(conn)
    if type(cleanup_verified) is not bool or type(accepted) is not bool:
        raise ValueError('Explicit probe outcome required')
    row=conn.execute('''SELECT sequence,worker_slot,containment_id,boot_id,lease_expires_at,
        cleanup_at,request_id,plan_digest,target_json FROM pipeline_catalog_probes
        WHERE reservation_id=?''',(reservation['reservation_id'],)).fetchone()
    if row is None or tuple(row[:4])!=tuple(reservation.get(k) for k in
            ('fencing_token','worker_slot','containment_id','boot_id')):
        raise ValueError('Probe cleanup identity differs')
    if row[5] is not None:raise ValueError('Probe already completed')
    if not cleanup_verified:return False
    now=time.time()
    result=dict(zip(('provider','model','reasoning_effort'),json.loads(row[8])))
    result.update(status='NATIVE_SELECTOR_ACCEPTED' if accepted and row[4]>now else 'PROBE_HELD',
        cleanup_verified=True,request_id=row[6],plan_digest=row[7],
        reservation_id=reservation['reservation_id'],fencing_token=row[0])
    conn.execute('UPDATE pipeline_catalog_probes SET cleanup_at=?,result_json=? WHERE reservation_id=?',
        (now,_json(result),reservation['reservation_id']))
    return True


def publish(conn, authority):
    """Consume only this authority's durable, fenced, cleaned results atomically."""
    journal._transaction(conn)
    rows=conn.execute('''SELECT plan_digest,pointer_sha256,proposal_sha256,result_json,
        cleanup_at,consumed_at FROM pipeline_catalog_probes WHERE request_id=?''',
        (authority.request_id,)).fetchall()
    if not rows or any(tuple(row[:3])!=(authority.change.digest,authority.pointer_sha256,
            authority.proposal_sha256) or row[4] is None or row[3] is None for row in rows):
        raise ValueError('Missing or unbound durable probe cleanup')
    result=journal.publish(conn,authority,[json.loads(row[3]) for row in rows])
    conn.execute('UPDATE pipeline_catalog_probes SET consumed_at=coalesce(consumed_at,?) WHERE request_id=?',
        (time.time(),authority.request_id))
    return result
