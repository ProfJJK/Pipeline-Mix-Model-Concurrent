"""Authenticated child pivot review with inert board models and real journal/ledger."""
import pytest

from cochem_pipeline.planning_pivots_428 import PlanningPivotRuntime
from pipeline_tests.test_microtask_board_428 import OWNER_SECRET
from pipeline_tests.test_planning_pivots_428 import env, fail_window, complete_review


def pending(env):
    old, boundary = fail_window(env)
    review = complete_review(env, complexity=8)
    env[-1].step('task')
    return old, boundary, review


def test_authenticated_owner_resumes_exact_child_pivot_without_new_parent_generation(env):
    store, journal, ledger, board, outcomes, bridge = env
    old, boundary, review = pending(env)
    before = journal.status('task')
    root = boundary['lineage_root']
    request = before['microtask_pivot_approvals'][root]
    assert request['review_job_id'] == review['job_id']
    assert request['assessment']['complexity'] == 8
    snapshot = board.materialize('task')
    child = next(n for n in snapshot['nodes'] if n['microtask_id'] == request['microtask_id'])
    assert child['status'] == 'HOLD_OWNER_APPROVAL'
    assert child['pending_pivot_approval'] == request
    assert bridge.step('task') == 1
    assert journal.status('task')['journal_version'] == before['journal_version']
    with pytest.raises(PermissionError):
        board.approve_child_microtask('task', request['microtask_id'], owner_token='model-generated-approval')
    assert ledger.status(root)['stage'] == 'PIVOT_RESEARCH'
    board.approve_child_microtask('task', request['microtask_id'], owner_token=OWNER_SECRET, notes='Reviewed changed scope')
    approved = journal.status('task')
    receipt = approved['microtask_pivot_approvals'][root]['owner_approval']
    assert receipt['request_sha256'] == request['request_sha256']
    assert approved['microtasks_sha256'] == before['microtasks_sha256']
    assert approved['microtasks'] == before['microtasks']
    bridge = PlanningPivotRuntime(journal, store, outcomes, bridge.pivot_runtime)
    bridge.step('task')
    assert outcomes.status('task')[-1]['status'] == 'PIVOT_READY_NEW_CAPTURE'
    assert ledger.status(root)['failures'] == 10
    assert ledger.status(root)['floor'] == 8
    board.pivot_context_provider = bridge.dispatch_context
    board.materialize('task')
    board.materialize('task')
    job = store.claim('inert-approved', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    assert job and job['job_id'] != old['job_id']
    assert job['payload']['planning_intent']['complexity'] == 8
    assert job['payload']['microtask_node']['attempt_lineage_id'] == root
    assert snapshot['plan_generation_sha256'] == board.board_status('task')['plan_generation_sha256']
    assert store.get(old['job_id'])['status'] == 'BLOCKED'


def test_owner_receipt_does_not_approve_changed_review_or_cancelled_task(env):
    store, journal, ledger, board, outcomes, bridge = env
    old, boundary, review = pending(env)
    root = boundary['lineage_root']
    request = journal.status('task')['microtask_pivot_approvals'][root]
    board.approve_child_microtask('task', request['microtask_id'], owner_token=OWNER_SECRET)
    altered = journal.request_microtask_pivot_approval('task', old['payload']['planning_intent'],
        lineage_root=root, boundary=10, review_job_id=review['job_id'], review_sha256='a' * 64,
        classification=dict(complexity=9, task_types=['COD-TERM'], rationale='New reviewed scope'))
    assert 'owner_approval' not in altered
    assert altered['request_sha256'] != request['request_sha256']
    journal.cancel('task')
    with pytest.raises(ValueError, match='stale scope'):
        board.approve_child_microtask('task', request['microtask_id'], owner_token=OWNER_SECRET)
    assert bridge.step('task') == 0
    assert ledger.status(root)['stage'] == 'PIVOT_RESEARCH'
