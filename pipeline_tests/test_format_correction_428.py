"""Durable bounded format correction accounting, using inert SQLite jobs."""
import pytest
import threading
import time
from types import SimpleNamespace

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


def test_stale_lease_cannot_consume_correction_or_release_reservation(tmp_path, monkeypatch):
    store, _, job_id = submitted(tmp_path)
    node = store.claim('owner', worker_slot='slot1')
    monkeypatch.setattr(time, 'time', lambda: node['lease_expires_at'] + 1)
    assert correction(store, node) is False
    with store._connection() as conn:
        assert not conn.execute('SELECT 1 FROM pipeline_format_corrections').fetchone()
        assert conn.execute('SELECT released_at FROM pipeline_route_reservations WHERE job_id=?', (job_id,)).fetchone()[0] is None


def test_cancelled_workflow_cannot_be_revived_by_format_feedback(tmp_path):
    store, workflow_id, job_id = submitted(tmp_path)
    node = store.claim('owner', worker_slot='slot1')
    store.cancel_workflow(workflow_id)
    assert correction(store, node) is False
    assert store.get(job_id)['status'] == 'FAILED'
    assert 'output_format_feedback' not in store.get(job_id)


def test_wall_deadline_is_not_reset_by_a_correction(tmp_path, monkeypatch):
    from pipeline_tests.test_routing_store import policy
    store, _, job_id = submitted(tmp_path, policy(max_routing_seconds=100))
    node = store.claim('owner', worker_slot='slot1')
    expiry = node['routing']['expires_at']
    assert correction(store, node)
    next_node = store.claim('owner', worker_slot='slot1')
    assert next_node['routing']['expires_at'] == expiry
    monkeypatch.setattr(time, 'time', lambda: expiry + 1)
    assert correction(store, next_node) is None
    assert store.get(job_id)['routing']['dispatches'] == 2
    assert store.get(job_id)['output_format_feedback']['correction_attempt'] == 1


def test_pool_quota_hold_survives_and_correction_counter_does_not_reset(tmp_path):
    store, _, job_id = submitted(tmp_path)
    node = store.claim('owner', worker_slot='slot1')
    assert correction(store, node)
    quota_node = store.claim('owner', worker_slot='slot1')
    assert store.fail(job_id, quota_node['attempt_id'], quota_node['fencing_token'],
                      'Quota fixture', retry=True, category='quota', retry_after_seconds=120)
    alternate = store.claim('owner', worker_slot='slot1')
    assert alternate['route']['quota_pool'] != quota_node['route']['quota_pool']
    assert correction(store, alternate)
    status = store.get(job_id)
    assert status['output_format_feedback']['correction_attempt'] == 2
    assert status['routing']['dispatches'] == 3
    assert status['routing']['failure_count'] == 0


@pytest.mark.parametrize('mutation', ['wrong_contract', 'unknown_code', 'too_many_issues'])
def test_feedback_must_match_current_bounded_contract(tmp_path, mutation):
    store, _, job_id = submitted(tmp_path)
    node = store.claim('owner', worker_slot='slot1')
    feedback = invalid_json_output(node).as_feedback()
    if mutation == 'wrong_contract':
        feedback['contract_sha256'] = 'f'*64
    elif mutation == 'unknown_code':
        feedback['issues'][0]['code'] = 'ignore_semantics'
    else:
        feedback['issues'] *= 33
    with pytest.raises(ValueError):
        store.correct_output_format(job_id, node['attempt_id'], node['fencing_token'], feedback)
    assert 'output_format_feedback' not in store.get(job_id)
    assert store.get(job_id)['status'] == 'IN_PROGRESS'


def inert_runtime(store, node, tmp_path):
    from cochem_pipeline.runtime import Runtime
    runtime = Runtime.__new__(Runtime)
    runtime.store = store
    runtime.lock = threading.RLock()
    runtime.stop_event = threading.Event()
    runtime.quarantined = {}
    runtime.active = {node['job_id']: {'cancel_event': threading.Event()}}
    runtime.config = SimpleNamespace(private_root=tmp_path, job_db=store.path)
    return runtime


def test_runtime_resource_trip_takes_backoff_instead_of_format_correction(tmp_path):
    store, _, job_id = submitted(tmp_path)
    node = store.claim('owner', worker_slot='slot1', requires_cleanup=True)
    runtime = inert_runtime(store, node, tmp_path)
    runtime.active[job_id]['resource_tripped'] = True
    runtime.active[job_id]['cancel_event'].set()
    assert runtime._record_failure(node, 'slot1', invalid_json_output(node))
    status = store.get(job_id)
    assert 'output_format_feedback' not in status
    assert status['routing']['wait_reason'] == 'host_resource_pressure'
    assert status['routing']['next_eligible_at'] > time.time()
    assert status['routing']['failure_count'] == 0


@pytest.mark.parametrize('stop_kind', ['cancel_event', 'stop_event', 'tripped'])
def test_runtime_cancellation_prevents_format_redispatch(tmp_path, stop_kind):
    store, _, job_id = submitted(tmp_path)
    node = store.claim('owner', worker_slot='slot1', requires_cleanup=True)
    runtime = inert_runtime(store, node, tmp_path)
    if stop_kind == 'tripped':
        runtime.active[job_id]['tripped'] = True
    elif stop_kind == 'stop_event':
        runtime.stop_event.set()
    else:
        runtime.active[job_id]['cancel_event'].set()
    assert runtime._record_failure(node, 'slot1', invalid_json_output(node))
    assert 'output_format_feedback' not in store.get(job_id)
    assert store.get(job_id)['status'] == 'FAILED'


def test_runtime_semantic_failure_uses_normal_failure_budget(tmp_path):
    store, _, job_id = submitted(tmp_path)
    node = store.claim('owner', worker_slot='slot1', requires_cleanup=True)
    runtime = inert_runtime(store, node, tmp_path)
    assert runtime._record_failure(node, 'slot1', ValueError('Unknown requirement ownership'))
    status = store.get(job_id)
    assert 'output_format_feedback' not in status
    assert status['routing']['failure_count'] == 1


def test_coding_format_retry_preserves_exact_assignment_and_leaf_state(tmp_path):
    from copy import deepcopy
    store, workflow_id, _ = submitted(tmp_path)
    payload = dict(requirements=['R1'], allowed_paths=['src'],
                   active_leaf=dict(id='real-leaf', file_targets=['src/main.py']))
    with store._write() as conn:
        store._insert(conn, 'edit-job', workflow_id, workflow_id, 'CODE_EDIT', 'PENDING', payload)
    node = store.claim('owner', worker_slot='slot1', allowed_kinds=['CODE_EDIT'], requires_cleanup=True)
    original = deepcopy(node['payload'])
    store.clear_execution_quarantine(node['job_id'], node['attempt_id'], node['fencing_token'])
    assert correction(store, node)
    next_node = store.claim('owner', worker_slot='slot1', allowed_kinds=['CODE_EDIT'])
    assert next_node['payload'] == original
    assert next_node['routing']['failure_count'] == 0
    assert next_node['routing']['dispatches'] == 2
