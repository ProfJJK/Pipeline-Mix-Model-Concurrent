"""Board projection/identity recovery with inert verifier feedback and real ledger fences."""
from types import SimpleNamespace

import pytest

from cochem_pipeline.task_routing import digest
from pipeline_tests.test_planning_pivots_428 import env
from pipeline_tests.test_microtask_board_428 import _complete_claimed_job_for_node


def completed(env):
    store, journal, ledger, board, outcomes, bridge = env
    for _ in range(4):
        snapshot = board.materialize('task')
        job = store.claim('inert-producer', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
        assert job
        _complete_claimed_job_for_node(store, job, job['payload']['microtask_node'])
    snapshot = board.materialize('task')
    assert all(n['status'] == 'COMPLETED' for n in snapshot['nodes'])
    for node in snapshot['nodes']:
        producer = store.get(node['job_id'])
        assert node['output']['producer_job_id'] == producer['job_id']
        assert node['output']['producer_attempt_id'] == producer['attempt_id']
        assert node['output']['producer_fencing_token'] == producer['fencing_token']
    return {n['microtask_id']: n for n in snapshot['nodes']}


def feedback(env, nodes, phase='green', account=True):
    store, journal, ledger, board, outcomes, bridge = env
    producer = store.get(nodes['mt-4']['job_id'])
    root = producer['payload']['microtask_node']['attempt_lineage_id']
    item = dict(retry_generation=1, producer_job_id=producer['job_id'], verification_job_id='verify-fixture',
        lineage_root=root, failure=dict(schema='cochem-task-verification-feedback/4.2.8',
            category='physical_verification', test_phase=phase, reason='REQUIREMENT_TESTS_NOT_PASSED',
            tests=[dict(name='test_requirement_req3', status='failed')], evidence_sha256=digest('verifier-evidence')))
    if account:
        profile = producer['payload']['task_catalog']['models'][producer['payload']['planning_intent']['candidate_profiles'][0]]
        outcomes.accounting.start_board_attempt(producer['job_id'], producer['attempt_id'], producer['fencing_token'],
            lineage_root=root, member_id=root, model_family=profile['family'], complexity=5)
        outcomes.accounting.record_board_outcome(producer['job_id'], producer['attempt_id'], producer['fencing_token'],
            category='quality_failure', evidence_sha256=digest(item))
    board.artifact_runtime = SimpleNamespace(
        retry_feedback=lambda task_id, microtask_id: item if microtask_id == 'mt-4' else None,
        execution_context=lambda payload: {})
    return item


def test_green_failure_regenerates_assembly_then_test_once_preserving_prior_jobs(env):
    store, journal, ledger, board, outcomes, bridge = env
    before = completed(env)
    item = feedback(env, before)
    after = {n['microtask_id']: n for n in board.materialize('task')['nodes']}
    for key in ('mt-1', 'mt-2'):
        assert after[key]['job_id'] == before[key]['job_id'] and after[key]['status'] == 'COMPLETED'
    assert after['mt-3']['job_id'] != before['mt-3']['job_id']
    assert after['mt-4']['status'] == 'WAITING_ON_DEPENDENCIES'
    repair = store.get(after['mt-3']['job_id'])
    micro = repair['payload']['microtask_node']
    assert set(micro['deliverables']) == {'hamiltonian.py', 'davidson.py', 'solver.py'}
    assert micro['physical_retry']['failed_checks'] == [item]
    assert micro['physical_retry']['sealed_test_producer_ids'] == [before['mt-4']['job_id']]
    assert board.materialize('task')['nodes'] == list(after.values())
    claimed = store.claim('inert-repair', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    _complete_claimed_job_for_node(store, claimed, claimed['payload']['microtask_node'])
    next_nodes = {n['microtask_id']: n for n in board.materialize('task')['nodes']}
    assert next_nodes['mt-4']['job_id'] != before['mt-4']['job_id']
    assert next_nodes['mt-4']['status'] == 'DISPATCHED'
    final_payload = store.get(next_nodes['mt-4']['job_id'])['payload']
    assert final_payload['predecessor_outputs']['mt-3']['producer_job_id'] == repair['job_id']
    assert store.get(before['mt-4']['job_id'])['status'] == 'COMPLETED'
    assert ledger.status(item['lineage_root'])['failures'] == 1


def test_red_failure_regenerates_only_final_test(env):
    store, journal, ledger, board, outcomes, bridge = env
    before = completed(env)
    feedback(env, before, phase='red')
    after = {n['microtask_id']: n for n in board.materialize('task')['nodes']}
    assert after['mt-3']['job_id'] == before['mt-3']['job_id']
    assert after['mt-4']['job_id'] != before['mt-4']['job_id']
    job = store.get(after['mt-4']['job_id'])
    assert job['payload']['microtask_node']['physical_retry']['sealed_test_producer_ids'] == []


def test_unaccounted_failure_cannot_create_retry_generation(env):
    before = completed(env)
    feedback(env, before, account=False)
    after = {n['microtask_id']: n for n in env[3].materialize('task')['nodes']}
    assert {key: n['job_id'] for key, n in after.items()} == {key: n['job_id'] for key, n in before.items()}


def test_tenth_failure_holds_recovery_until_researched_pivot(env):
    before = completed(env)
    root = 'task.mt.mt-4'
    ledger = env[2]
    for n in range(9):
        lease = ledger.start(root, root, 'gpt-6.1-sol')
        ledger.finish(lease, 'quality_failure', digest(n))
    item = feedback(env, before)
    assert ledger.status(root)['stage'] == 'PIVOT_RESEARCH'
    after = {n['microtask_id']: n for n in env[3].materialize('task')['nodes']}
    assert after['mt-3']['job_id'] == before['mt-3']['job_id']
    assert after['mt-4']['job_id'] == before['mt-4']['job_id']
