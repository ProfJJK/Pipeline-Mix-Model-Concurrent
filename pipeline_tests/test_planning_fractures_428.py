"""Inert fracture review/board captures; no provider or host lifecycle calls."""
from copy import deepcopy

import pytest

from cochem_pipeline.planning_fractures_428 import fracture_contract, validate_fracture_plan
from cochem_pipeline.planning_pivots_428 import PlanningPivotRuntime
from cochem_pipeline.planning_gateway import PlanningGateway
from pipeline_tests.test_planning_gateway_428 import accepted_receipt
from pipeline_tests.test_planning_pivots_428 import env, fail_window, complete_review


def finish_control(env, stage, *, accepted=True):
    store, journal, ledger, board, outcomes, bridge = env
    job = store.claim('inert-fracture', worker_slot='slot2', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    assert job is not None
    assert job['payload']['planning_intent']['stage'] == stage
    output = fracture_contract(job['payload'])
    if stage == 'FRACTURE_REVIEW' and not accepted:
        output.update(accepted=False, findings=['Fragment interface omits the required null case'])
    store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
    store.complete(job['job_id'], job['attempt_id'], job['fencing_token'], output, accepted_receipt(job, output))
    return store.get(job['job_id'])


def prepare_fracture(env):
    old, boundary = fail_window(env)
    complete_review(env, strategy='fracture')
    env[-1].step('task')
    plan = finish_control(env, 'FRACTURE_PLAN')
    env[-1].step('task')
    review = finish_control(env, 'FRACTURE_REVIEW')
    env[-1].step('task')
    return old, boundary, plan, review


def test_fracture_requires_review_then_preserves_failure_budget_on_restart(env):
    old, boundary, plan, review = prepare_fracture(env)
    store, journal, ledger, board, outcomes, bridge = env
    assert outcomes.status('task')[-1]['status'] == 'FRACTURE_READY_NEW_CAPTURE'
    state = ledger.status(boundary['lineage_root'])
    assert state['failures'] == 10 and state['floor'] == 5 and state['stage'] == 'READY'
    record = bridge.fractures.fracture_runtime.accepted_record(boundary['lineage_root'], 10)
    assert len(record['children']) == 4
    profiles = plan['payload']['task_catalog']['models']
    gateway = PlanningGateway(journal, store)
    assert profiles[gateway.model_result(plan['job_id'])['profile_id']]['family'] != profiles[gateway.model_result(review['job_id'])['profile_id']]['family']
    reopened = PlanningPivotRuntime(journal, store, outcomes, bridge.pivot_runtime)
    reopened.step('task')
    assert reopened.fractures.fracture_runtime.accepted_record(boundary['lineage_root'], 10) == record
    assert ledger.status(boundary['lineage_root'])['failures'] == 10
    assert store.get(old['job_id'])['status'] == 'BLOCKED'


def test_rejected_review_never_registers_fracture(env):
    old, boundary = fail_window(env)
    complete_review(env, strategy='fracture')
    env[-1].step('task')
    finish_control(env, 'FRACTURE_PLAN')
    env[-1].step('task')
    finish_control(env, 'FRACTURE_REVIEW', accepted=False)
    env[-1].step('task')
    assert env[4].status('task')[-1]['status'] == 'FRACTURE_REVIEW_REJECTED'
    assert env[2].status(boundary['lineage_root'])['stage'] == 'PIVOT_RESEARCH'
    assert env[-1].fractures.fracture_runtime.accepted_record(boundary['lineage_root'], 10) is None


def test_plan_rejects_scope_loss_and_duplicate_fragments(env):
    fail_window(env)
    complete_review(env, strategy='fracture')
    env[-1].step('task')
    job = env[0].claim('inert', worker_slot='slot2', allowed_kinds=['TASK_PLAN'])
    output = fracture_contract(job['payload'])
    broken = deepcopy(output)
    broken['children'][2]['release_criteria'] = ['An unrelated check']
    with pytest.raises(ValueError, match='preserve full scope'):
        validate_fracture_plan(job['payload'], broken)
    broken = deepcopy(output)
    broken['children'][1]['deliverables'] = broken['children'][0]['deliverables']
    with pytest.raises(ValueError, match='Duplicate'):
        validate_fracture_plan(job['payload'], broken)


def test_fracture_recovers_graph_commit_before_projection(env, monkeypatch):
    old, boundary = fail_window(env)
    complete_review(env, strategy='fracture')
    bridge = env[-1]
    bridge.step('task')
    finish_control(env, 'FRACTURE_PLAN')
    bridge.step('task')
    finish_control(env, 'FRACTURE_REVIEW')
    runtime = bridge.fractures.fracture_runtime
    original = runtime.execute_fracture
    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('interrupted after graph commit')
    monkeypatch.setattr(runtime, 'execute_fracture', crash)
    with pytest.raises(RuntimeError, match='interrupted'):
        bridge.step('task')
    monkeypatch.setattr(runtime, 'execute_fracture', original)
    bridge.step('task')
    assert env[2].status(boundary['lineage_root'])['failures'] == 10
    assert env[4].status('task')[-1]['status'] == 'FRACTURE_READY_NEW_CAPTURE'
