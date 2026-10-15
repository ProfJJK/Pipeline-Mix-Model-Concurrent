"""Durable bounded format correction accounting, using inert SQLite jobs."""
import pytest

from cochem_pipeline.output_contracts import invalid_json_output
from cochem_pipeline.store import JobStore
from pipeline_tests.test_routing_store import submitted, completion


def correction(store,node):
    feedback=invalid_json_output(node).as_feedback()
    return store.correct_output_format(node['job_id'],node['attempt_id'],node['fencing_token'],feedback)


def test_two_corrections_survive_restart_without_spending_failure_budget(tmp_path):
    store,workflow_id,job_id=submitted(tmp_path,max_attempts=3,max_dispatches=6)
    for expected in (1,2):
        node=store.claim('owner',worker_slot='slot1')
        assert correction(store,node) is True
        status=store.get(job_id)
        assert status['output_format_feedback']['correction_attempt']==expected
        assert status['routing']['dispatches']==expected
        assert status['routing']['failure_count']==0
        assert status['routing']['cursor']==0
        store.close()
        store=JobStore(store.path)
    third=store.claim('owner',worker_slot='slot1')
    assert third['output_format_feedback']['correction_attempt']==2
    assert correction(store,third) is None
    assert store.fail(job_id,third['attempt_id'],third['fencing_token'],'invalid output',retry=True,category='code')
    assert store.get(job_id)['routing']['failure_count']==1
    assert store.get(job_id)['routing']['dispatches']==3


def test_dispatch_limit_does_not_allow_correction(tmp_path):
    store,_,job_id=submitted(tmp_path,max_dispatches=1)
    node=store.claim('owner',worker_slot='slot1')
    assert correction(store,node) is None
    assert store.get(job_id)['routing']['dispatches']==1


def test_cleanup_and_fencing_precede_format_retry(tmp_path):
    store,_,job_id=submitted(tmp_path)
    node=store.claim('owner',worker_slot='slot1',requires_cleanup=True)
    with pytest.raises(ValueError,match='cleanup'):
        correction(store,node)
    store.clear_execution_quarantine(job_id,node['attempt_id'],node['fencing_token'])
    assert correction(store,node) is True
    assert correction(store,node) is False
    replacement=store.claim('owner',worker_slot='slot1')
    assert replacement['attempt_id']!=node['attempt_id']
    assert replacement['routing']['dispatches']==2


def test_good_output_can_finish_after_format_correction(tmp_path):
    store,_,job_id=submitted(tmp_path)
    first=store.claim('owner',worker_slot='slot1')
    assert correction(store,first)
    node=store.claim('owner',worker_slot='slot1')
    output,receipt=completion(node)
    result=store.complete(job_id,node['attempt_id'],node['fencing_token'],output,receipt)
    assert result['status']=='COMPLETED'
    assert result['routing']['failure_count']==0
