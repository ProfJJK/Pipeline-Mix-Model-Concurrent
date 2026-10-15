"""Retry actual temporary snapshots with inert provider and engine ports."""
from copy import deepcopy
import hashlib
import threading
from types import SimpleNamespace

import pytest

from cochem_pipeline.planning_gateway import prompt_contract
from cochem_pipeline.task_execution_428 import SimpleTaskExecutionRuntime
from pipeline_tests.test_planning_gateway_428 import accepted_receipt
from pipeline_tests.test_task_execution_428 import simple_env
from pipeline_tests.test_task_verification_e2e_428 import _stage_proposal, outcome_runtime, verify_next


def reject(simple_env, tmp_path, monkeypatch, value):
    artifacts, host, producer, reqs, _ = _stage_proposal(simple_env, tmp_path, monkeypatch, value)
    outcomes = outcome_runtime(simple_env, artifacts, tmp_path)
    artifacts.ensure_verification(producer, reqs)
    while True:
        node, (output, receipt, evidence), _ = verify_next(artifacts, host.store, monkeypatch)
        host.store.clear_execution_quarantine(node['job_id'], node['attempt_id'], node['fencing_token'])
        host.store.complete_task_verification(node['job_id'], node['attempt_id'], node['fencing_token'],
                                             output, receipt, evidence=evidence)
        result = artifacts.ensure_verification(producer, reqs)
        if result['status'] == 'TASK_VERIFICATION_REJECTED':
            break
    return artifacts, host, producer, outcomes


@pytest.mark.parametrize('value', [0, 2])
def test_retry_waits_for_accounting_preserves_proposal_and_is_idempotent(simple_env, tmp_path, monkeypatch, value):
    artifacts, host, producer, outcomes = reject(simple_env, tmp_path, monkeypatch, value)
    _, execution, journal, store = simple_env
    assert execution.step_ready_task('task')['status'] == 'WAITING_FOR_FAILURE_ACCOUNTING'
    execution.attempt_accounting = outcomes.accounting
    assert execution.step_ready_task('task')['status'] == 'WAITING_FOR_FAILURE_ACCOUNTING'
    outcomes.reconcile_task('task')
    retry = execution.materialize('task')
    assert retry['job_id'] != producer['job_id']
    assert execution.materialize('task')['job_id'] == retry['job_id']
    context = retry['payload']['execution_context']
    assert context['sealed_test_paths'] == (['tests/test_bound.py'] if value == 2 else [])
    captured = retry['payload']['planning_intent']['physical_retry']
    assert captured['retry_generation'] == 1
    assert prompt_contract(retry['payload'])[2]['physical_retry'] == captured
    fresh = SimpleTaskExecutionRuntime(journal, store, artifact_runtime=artifacts,
                                      attempt_accounting=outcomes.accounting)
    assert fresh.materialize('task')['job_id'] == retry['job_id']
    node = store.claim('inert-retry', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    assert node['job_id'] == retry['job_id']
    output = deepcopy(producer['output'])
    for item in output['deliverables']:
        item['content'] = item['content'].replace(f'value = {value}', 'value = 1')
        item['sha256'] = hashlib.sha256(item['content'].encode()).hexdigest()
    host.runner = SimpleNamespace(run=lambda *a, **k: (deepcopy(output), accepted_receipt(node, output)))
    result, receipt = artifacts.run(node, 'slot1', '', lambda: True, lambda _: None, threading.Event(),
                                   on_native_start=lambda _: None, on_native_end=lambda: None)
    store.clear_execution_quarantine(node['job_id'], node['attempt_id'], node['fencing_token'])
    store.complete(node['job_id'], node['attempt_id'], node['fencing_token'], result, receipt)
    reqs = [r['id'] for r in node['payload']['planning_intent']['task']['document']['requirements']]
    artifacts.ensure_verification(store.get(node['job_id']), reqs)
    for _ in range(2):
        check, (out, rec, evidence), _ = verify_next(artifacts, store, monkeypatch)
        assert out['passed']
        store.clear_execution_quarantine(check['job_id'], check['attempt_id'], check['fencing_token'])
        store.complete_task_verification(check['job_id'], check['attempt_id'], check['fencing_token'],
                                         out, rec, evidence=evidence)
        artifacts.ensure_verification(store.get(node['job_id']), reqs)
    assert execution.step_ready_task('task')['status'] == 'EXECUTION_COMPLETED'
    outcomes.reconcile_task('task')
    assert outcomes.accounting.ledger.status('task')['failures'] == 1
    assert store.get(producer['job_id'])['status'] == 'COMPLETED'


def test_green_retry_cannot_weaken_sealed_tests(simple_env, tmp_path, monkeypatch):
    artifacts, host, producer, outcomes = reject(simple_env, tmp_path, monkeypatch, 2)
    outcomes.reconcile_task('task')
    execution, store = simple_env[1], simple_env[-1]
    execution.attempt_accounting = outcomes.accounting
    execution.materialize('task')
    node = store.claim('inert-retry', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    output = deepcopy(producer['output'])
    test = next(item for item in output['deliverables'] if item['name'].startswith('tests/'))
    test['content'] = test['content'].replace('value = 1', 'value = 2')
    test['sha256'] = hashlib.sha256(test['content'].encode()).hexdigest()
    host.runner = SimpleNamespace(run=lambda *a, **k: (output, accepted_receipt(node, output)))
    with pytest.raises(ValueError, match='protected tests'):
        artifacts.run(node, 'slot1', '', lambda: True, lambda _: None, threading.Event(),
                      on_native_start=lambda _: None, on_native_end=lambda: None)


def test_research_boundary_cannot_be_bypassed_by_new_retry_job(simple_env, tmp_path, monkeypatch):
    artifacts, host, producer, outcomes = reject(simple_env, tmp_path, monkeypatch, 2)
    outcomes.reconcile_task('task')
    ledger = outcomes.accounting.ledger
    for _ in range(9):
        lease = ledger.start('task', 'task', 'fixture-family')
        ledger.finish(lease, 'quality_failure', 'f' * 64)
    execution = simple_env[1]
    execution.attempt_accounting = outcomes.accounting
    assert execution.step_ready_task('task')['status'] == 'EXECUTION_LINEAGE_PIVOT_RESEARCH'
    with host.store._connection() as conn:
        assert conn.execute("SELECT count(*) FROM pipeline_jobs WHERE kind='TASK_PLAN' AND "
                            "json_extract(payload_json,'$.planning_intent.stage')='SIMPLE_EXECUTION'").fetchone()[0] == 1
