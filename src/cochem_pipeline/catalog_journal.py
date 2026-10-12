"""R7 durable generation publication primitives; caller owns the job-board transaction.

JobStore's opt-in catalog mode reads an explicitly initialized journal; it does
not initialize or publish one. No model execution, migration of old captures or
filesystem authority lives here. Production integration must obtain retained
SYSTEM authority and real shared-slot probe receipts before calling publish.
"""
from __future__ import annotations

import json
import time

from .catalog_activation import _json
from .catalog_authority import CatalogAuthority
from .routing import load_routing_policy


def _transaction(conn):
    if not conn.in_transaction:
        raise ValueError('Catalog publication requires the existing job-board write transaction')
    if conn.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise ValueError('Catalog journal requires foreign key enforcement')
    if conn.execute('PRAGMA synchronous').fetchone()[0] < 2:
        raise ValueError('Catalog journal requires durable FULL synchronous writes')


def initialize(conn, baseline):
    """Explicit owner migration only; never called implicitly during a read."""
    _transaction(conn)
    if baseline.as_dict()['policy_version'] != 3:
        raise ValueError('Catalog baseline must be a v3 policy')
    conn.execute('''CREATE TABLE IF NOT EXISTS pipeline_catalog_generations (
        policy_digest TEXT PRIMARY KEY, generation TEXT NOT NULL UNIQUE,
        policy_json TEXT NOT NULL CHECK(json_valid(policy_json)),
        previous_policy_digest TEXT REFERENCES pipeline_catalog_generations(policy_digest),
        request_id TEXT UNIQUE, plan_digest TEXT, pointer_sha256 TEXT, proposal_sha256 TEXT,
        proof_json TEXT NOT NULL CHECK(json_valid(proof_json)), committed_at REAL NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pipeline_catalog_active (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        policy_digest TEXT NOT NULL REFERENCES pipeline_catalog_generations(policy_digest))''')
    for operation in ('UPDATE','DELETE'):
        conn.execute(f'''CREATE TRIGGER IF NOT EXISTS pipeline_catalog_no_{operation.lower()}
            BEFORE {operation} ON pipeline_catalog_generations
            BEGIN SELECT RAISE(ABORT,'catalog generations are immutable'); END''')
    if conn.execute('SELECT 1 FROM pipeline_catalog_active').fetchone() is None:
        if conn.execute('SELECT 1 FROM pipeline_catalog_generations').fetchone() is not None:
            raise ValueError('Existing catalog history has no active pointer; preserve for review')
        conn.execute('''INSERT INTO pipeline_catalog_generations
            (policy_digest,generation,policy_json,proof_json,committed_at) VALUES(?,?,?,?,?)''',
            (baseline.digest,baseline.as_dict()['catalog']['generation'],_json(baseline.as_dict()),
             _json({'status':'INSTALLED_BASELINE_NOT_NEW_PROBE_EVIDENCE'}),time.time()))
        conn.execute('INSERT INTO pipeline_catalog_active VALUES(1,?)',(baseline.digest,))
    elif conn.execute('SELECT 1 FROM pipeline_catalog_generations WHERE policy_digest=?',
            (baseline.digest,)).fetchone() is None:
        raise ValueError('Installed baseline is absent from existing catalog history')


def active_policy(conn):
    row=conn.execute('''SELECT g.policy_digest,g.policy_json FROM pipeline_catalog_active a
        JOIN pipeline_catalog_generations g USING(policy_digest) WHERE a.singleton=1''').fetchone()
    if row is None:
        raise ValueError('No durably active catalog generation')
    policy=load_routing_policy(json.loads(row[1]))
    if policy.digest != row[0]:
        raise ValueError('Active catalog bytes differ from their digest')
    return policy


def _proof(authority, results):
    change=authority.change
    expected=set(change.changed_targets)|{change.control_target}
    if not isinstance(results,list) or len(results)!=len(expected):
        raise ValueError('Catalog probe evidence does not cover the exact plan')
    seen=set();sanitized=[]
    for result in results:
        if not isinstance(result,dict):raise ValueError('Invalid catalog probe evidence')
        key=tuple(result.get(field) for field in ('provider','model','reasoning_effort'))
        if (any(not isinstance(value,str) for value in key) or key not in expected or key in seen
                or result.get('status')!='NATIVE_SELECTOR_ACCEPTED'
                or result.get('cleanup_verified') is not True
                or result.get('plan_digest')!=change.digest
                or result.get('request_id')!=authority.request_id
                or not isinstance(result.get('reservation_id'),str) or not result['reservation_id']
                or type(result.get('fencing_token')) is not int or result['fencing_token']<1):
            raise ValueError('Catalog probe identity, cleanup or reservation binding differs')
        seen.add(key)
        sanitized.append({field:result[field] for field in ('provider','model','reasoning_effort',
            'status','cleanup_verified','plan_digest','request_id','reservation_id','fencing_token')})
    return sorted(sanitized,key=lambda row:(row['provider'],row['model'],row['reasoning_effort']))


def publish(conn, authority: CatalogAuthority, results):
    """CAS publication inside the SAME transaction as verified probe consumption.

    The integration layer must verify reservations against the job board; this
    routine checks binding/completeness only and never treats supplied IDs as a
    live lease proof. Duplicate completed requests return their historical digest
    without moving the active pointer backwards.
    """
    _transaction(conn)
    if not isinstance(authority,CatalogAuthority):raise ValueError('Retained catalog authority is required')
    proof=_proof(authority,results);change=authority.change
    prior=conn.execute('''SELECT policy_digest,plan_digest,pointer_sha256,proposal_sha256,proof_json
        FROM pipeline_catalog_generations WHERE request_id=?''',(authority.request_id,)).fetchone()
    if prior is not None:
        if tuple(prior)!=(change.policy.digest,change.digest,authority.pointer_sha256,
                authority.proposal_sha256,_json(proof)):
            raise ValueError('Catalog request ID was reused with different evidence')
        return {'status':'ALREADY_PUBLISHED','policy_digest':prior[0]}
    if active_policy(conn).digest!=change.previous_policy_digest:
        raise ValueError('Active catalog changed before publication; no implicit rebase')
    conn.execute('''INSERT INTO pipeline_catalog_generations VALUES(?,?,?,?,?,?,?,?,?,?)''',
        (change.policy.digest,change.policy.as_dict()['catalog']['generation'],_json(change.policy.as_dict()),
         change.previous_policy_digest,authority.request_id,change.digest,authority.pointer_sha256,
         authority.proposal_sha256,_json(proof),time.time()))
    updated=conn.execute('''UPDATE pipeline_catalog_active SET policy_digest=?
        WHERE singleton=1 AND policy_digest=?''',(change.policy.digest,change.previous_policy_digest))
    if updated.rowcount!=1:raise ValueError('Catalog generation compare-and-swap failed')
    return {'status':'PUBLISHED_IN_CALLER_TRANSACTION','policy_digest':change.policy.digest}
