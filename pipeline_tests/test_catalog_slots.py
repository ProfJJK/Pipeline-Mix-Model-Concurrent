"""Temporary SQLite capacity tests; no providers or native processes."""
import sqlite3
from dataclasses import replace

import pytest

from cochem_pipeline import catalog_slots as slots
from cochem_pipeline.catalog_journal import active_policy
from cochem_pipeline.store import JobStore
from pipeline_tests.test_catalog_store import setup
from pipeline_tests.test_catalog_journal import change


def prepared(tmp_path):
    path,baseline=setup(tmp_path)
    store=JobStore(path,routing_policy=baseline,catalog_enabled=True)
    with store._write() as conn:slots.initialize(conn)
    return store,baseline,change(baseline,2)[0]


def reserve(conn,authority,**kwargs):
    return slots.reserve(conn,authority,authority.change.control_target,worker_slot='slot6',
        containment_id='c'*32,boot_id=123,**kwargs)


def test_probe_and_jobs_share_capacity_in_both_directions(tmp_path):
    store,baseline,authority=prepared(tmp_path)
    with store._write() as conn:token=reserve(conn,authority,max_workers=1)
    assert token
    assert store.claim('owner',max_workers=1) is None
    with store._write() as conn:slots.finish(conn,token,cleanup_verified=True,accepted=True)
    assert store.claim('owner',max_workers=1)
    next_authority=change(baseline,3)[0]
    with store._write() as conn:assert reserve(conn,next_authority,max_workers=1) is None
    store.close()


def test_lease_expiry_does_not_free_capacity_or_allow_publication(tmp_path,monkeypatch):
    store,baseline,authority=prepared(tmp_path)
    with store._write() as conn:token=reserve(conn,authority,lease_seconds=1)
    monkeypatch.setattr(slots.time,'time',lambda:1e12)
    with store._write() as conn:
        assert slots.occupancy(conn)==1
        assert not slots.finish(conn,token,cleanup_verified=False,accepted=True)
        assert slots.occupancy(conn)==1
        slots.finish(conn,token,cleanup_verified=True,accepted=True)
        assert slots.occupancy(conn)==0
    with pytest.raises(ValueError),store._write() as conn:slots.publish(conn,authority)
    with store._connection() as conn:assert active_policy(conn).digest==baseline.digest
    store.close()


def test_fenced_cleanup_and_atomic_publication(tmp_path):
    store,baseline,authority=prepared(tmp_path)
    with store._write() as conn:token=reserve(conn,authority)
    with pytest.raises(ValueError,match='identity'),store._write() as conn:
        slots.finish(conn,dict(token,fencing_token=token['fencing_token']+1),cleanup_verified=True,accepted=True)
    with pytest.raises(ValueError,match='cleanup'),store._write() as conn:slots.publish(conn,authority)
    with store._write() as conn:slots.finish(conn,token,cleanup_verified=True,accepted=True)
    with pytest.raises(RuntimeError),store._write() as conn:
        slots.publish(conn,authority)
        raise RuntimeError('simulated transaction failure')
    with store._connection() as conn:
        assert active_policy(conn).digest==baseline.digest
        assert conn.execute('SELECT consumed_at FROM pipeline_catalog_probes').fetchone()[0] is None
    with store._write() as conn:assert slots.publish(conn,authority)['status']=='PUBLISHED_IN_CALLER_TRANSACTION'
    with store._write() as conn:assert slots.publish(conn,authority)['status']=='ALREADY_PUBLISHED'
    with store._connection() as conn:assert active_policy(conn).digest==authority.change.policy.digest
    store.close()


def test_restart_preserves_occupied_slot_and_no_automatic_retry(tmp_path):
    store,baseline,authority=prepared(tmp_path)
    with store._write() as conn:reserve(conn,authority)
    path=store.path;store.close()
    store=JobStore(path,routing_policy=baseline,catalog_enabled=True)
    assert store.claim('new-owner',max_workers=1) is None
    assert store.claim('new-owner',max_workers=4,worker_slot='slot6') is None
    with pytest.raises(ValueError,match='automatic retry'),store._write() as conn:reserve(conn,authority)
    store.close()


def test_four_shared_slots_and_worker_collision(tmp_path):
    store,baseline,authority=prepared(tmp_path)
    with store._write() as conn:
        for number in range(1,5):
            proposal=change(baseline,number+10)[0]
            assert slots.reserve(conn,proposal,proposal.change.control_target,
                worker_slot=f'slot{number}',containment_id=f'{number:032x}',boot_id=123)
        assert slots.occupancy(conn)==4
        assert reserve(conn,authority) is None
    assert store.claim('owner',max_workers=4) is None
    store.close()


@pytest.mark.parametrize('fault',['pointer','proposal','failed'])
def test_wrong_authority_or_failed_outcome_cannot_publish(tmp_path,fault):
    store,baseline,authority=prepared(tmp_path)
    with store._write() as conn:
        token=reserve(conn,authority)
        slots.finish(conn,token,cleanup_verified=True,accepted=fault!='failed')
    if fault=='pointer':authority=replace(authority,pointer_sha256='f'*64)
    if fault=='proposal':authority=replace(authority,proposal_sha256='f'*64)
    with pytest.raises(ValueError),store._write() as conn:slots.publish(conn,authority)
    with store._connection() as conn:assert active_policy(conn).digest==baseline.digest
    store.close()


def test_reservation_history_and_completed_result_cannot_be_rewritten(tmp_path):
    store,baseline,authority=prepared(tmp_path)
    with store._write() as conn:
        token=reserve(conn,authority)
        slots.finish(conn,token,cleanup_verified=True,accepted=True)
    for statement in ("UPDATE pipeline_catalog_probes SET worker_slot='slot1'",
                      'UPDATE pipeline_catalog_probes SET cleanup_at=NULL',
                      'DELETE FROM pipeline_catalog_probes'):
        with pytest.raises(sqlite3.IntegrityError),store._write() as conn:conn.execute(statement)
    store.close()
