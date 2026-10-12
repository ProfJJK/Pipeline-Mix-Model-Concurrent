"""R7 transaction fixtures use only temporary ordinary SQLite files."""
import sqlite3

import pytest

from cochem_pipeline.catalog_activation import compile_change
from cochem_pipeline.catalog_authority import CatalogAuthority
from cochem_pipeline.catalog_journal import initialize,active_policy,publish
from cochem_pipeline.routing import load_routing_policy


def connection(path):
    conn=sqlite3.connect(path,isolation_level=None)
    conn.execute('PRAGMA foreign_keys=ON');conn.execute('PRAGMA synchronous=FULL')
    return conn


def change(current,number):
    catalog=current.as_dict()['catalog'];catalog['generation']=f'fixture-generation-{number}'
    catalog['tiers']['4'].reverse()
    plan=compile_change(current,catalog,expected_policy_digest=current.digest)
    authority=CatalogAuthority(f'{number:032x}','a'*64,'b'*64,plan)
    proof=[dict(zip(('provider','model','reasoning_effort'),plan.control_target))]
    proof[0].update(status='NATIVE_SELECTOR_ACCEPTED',cleanup_verified=True,plan_digest=plan.digest,
        request_id=authority.request_id,reservation_id='fixture-reservation',fencing_token=1)
    return authority,proof


def setup(tmp_path):
    conn=connection(tmp_path/'board.db');baseline=load_routing_policy({'policy_version':3})
    conn.execute('BEGIN IMMEDIATE');initialize(conn,baseline);conn.commit()
    return conn,baseline


def test_publish_is_atomic_durable_and_preserves_history(tmp_path):
    conn,baseline=setup(tmp_path);authority,proof=change(baseline,2)
    conn.execute('BEGIN IMMEDIATE');publish(conn,authority,proof)
    observer=connection(tmp_path/'board.db')
    assert active_policy(observer).digest==baseline.digest
    conn.commit()
    assert active_policy(observer).digest==authority.change.policy.digest
    assert conn.execute('SELECT count(*) FROM pipeline_catalog_generations').fetchone()[0]==2
    with pytest.raises(sqlite3.IntegrityError):conn.execute('DELETE FROM pipeline_catalog_generations')
    observer.close();conn.close()
    with connection(tmp_path/'board.db') as reopened:
        assert active_policy(reopened).digest==authority.change.policy.digest


def test_rollback_leaves_no_partial_generation(tmp_path):
    conn,baseline=setup(tmp_path);authority,proof=change(baseline,2)
    conn.execute('BEGIN IMMEDIATE');publish(conn,authority,proof);conn.rollback()
    assert active_policy(conn).digest==baseline.digest
    assert conn.execute('SELECT count(*) FROM pipeline_catalog_generations').fetchone()[0]==1
    conn.close()


def test_replay_cannot_restore_old_generation(tmp_path):
    conn,baseline=setup(tmp_path);first,proof1=change(baseline,2)
    conn.execute('BEGIN IMMEDIATE');publish(conn,first,proof1);conn.commit()
    second,proof2=change(first.change.policy,3)
    conn.execute('BEGIN IMMEDIATE');publish(conn,second,proof2);conn.commit()
    conn.execute('BEGIN IMMEDIATE')
    assert publish(conn,first,proof1)['status']=='ALREADY_PUBLISHED'
    conn.commit();assert active_policy(conn).digest==second.change.policy.digest
    stale,stale_proof=change(baseline,4)
    conn.execute('BEGIN IMMEDIATE')
    with pytest.raises(ValueError,match='no implicit rebase'):publish(conn,stale,stale_proof)
    conn.rollback();conn.close()


@pytest.mark.parametrize('fault',['cleanup','missing','wrong_plan','duplicate','no_transaction','weak_sync'])
def test_incomplete_or_unbound_publication_refused(tmp_path,fault):
    conn,baseline=setup(tmp_path);authority,proof=change(baseline,2)
    if fault=='cleanup':proof[0]['cleanup_verified']=False
    if fault=='missing':proof=[]
    if fault=='wrong_plan':proof[0]['plan_digest']='0'*64
    if fault=='duplicate':proof*=2
    if fault=='weak_sync':conn.execute('PRAGMA synchronous=NORMAL')
    if fault!='no_transaction':conn.execute('BEGIN IMMEDIATE')
    with pytest.raises(ValueError):publish(conn,authority,proof)
    conn.rollback();assert active_policy(conn).digest==baseline.digest;conn.close()


def test_reinitialize_preserves_active_generation_and_rejects_unrelated_baseline(tmp_path):
    conn,baseline=setup(tmp_path);authority,proof=change(baseline,2)
    conn.execute('BEGIN IMMEDIATE');publish(conn,authority,proof);conn.commit()
    conn.execute('BEGIN IMMEDIATE');initialize(conn,baseline);conn.commit()
    assert active_policy(conn).digest==authority.change.policy.digest
    unrelated,_=change(baseline,99);conn.execute('BEGIN IMMEDIATE')
    with pytest.raises(ValueError,match='baseline is absent'):initialize(conn,unrelated.change.policy)
    conn.rollback();conn.close()
