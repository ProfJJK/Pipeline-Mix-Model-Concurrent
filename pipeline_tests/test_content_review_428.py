"""Content release review with temporary SQLite and inert model receipts only."""
from copy import deepcopy
import json

import pytest

from cochem_pipeline.content_review_428 import ContentReviewRuntime, review_contract, validate_content_review
from cochem_pipeline.task_routing import digest
from cochem_pipeline.task_release_428 import TaskReleaseRuntime
from cochem_pipeline.worker import node_prompt
from pipeline_tests.test_task_release_428 import _claim_and_complete_all_ready
from pipeline_tests.test_microtask_board_428 import _make_store_and_journal, _advance_task_to_reassessed_ready
from pipeline_tests.test_task_verification_store_428 import completion
from pipeline_tests.test_planning_gateway_428 import accepted_receipt


def prepared(tmp_path, *, include_deliverables=True):
    store, journal, broker = _make_store_and_journal(tmp_path)
    task_id = 'content-task'
    _advance_task_to_reassessed_ready(journal, task_id=task_id)
    release = TaskReleaseRuntime(journal, store, owner_broker=broker)
    for _ in range(3):
        snap = _claim_and_complete_all_ready(store, release.board, task_id)
    assert snap['all_completed']
    with journal._write() as conn:
        state = json.loads(journal._read(conn, task_id)['state_json'])
    # Physical verification fixture uses actual immutable bytes and fenced
    # controller evidence; separate runtime E2E tests exercise RAM staging.
    files = ({item['name']: item['content'].encode('utf-8')
              for node in snap['nodes'] for item in node['output']['deliverables']}
             if include_deliverables else {})
    files['report.md'] = b'Captured complete report\n'
    with store._write() as conn:
        snapshot = store._snapshot(conn, files)
        store._insert(conn, 'integrity-root', 'integrity-root', None, 'MACRO_PLANNING_REQUEST', 'IN_PROGRESS',
                      dict(workflow_type='task_verification428'))
        payload = dict(schema='cochem-task-verification/4.2.8', task_id=task_id,
                       verification_key='a' * 64, source_snapshot_sha256=snapshot, mode='artifact_integrity',
                       producer_job_id=next(n['job_id'] for n in snap['nodes'] if n['role'] == 'final_test'))
        store._insert(conn, 'integrity-job', 'integrity-root', 'integrity-root', 'TASK_VERIFY', 'PENDING', payload)
    node = store.claim('fixture', allowed_kinds=['TASK_VERIFY'], requires_cleanup=True, worker_slot='slot1')
    output, receipt, evidence = completion(node, files)
    store.record_coding_attempt_evidence(node, evidence)
    store.clear_execution_quarantine(node['job_id'], node['attempt_id'], node['fencing_token'])
    store.complete_task_verification(node['job_id'], node['attempt_id'], node['fencing_token'],
                                     output, receipt, evidence=evidence)
    physical = dict(status='VERIFIED', job_id=node['job_id'], output=output, source_snapshot_sha256=snapshot)
    args = dict(state=state, generation=snap['plan_generation_sha256'],
                producers=[n['job_id'] for n in snap['nodes'] if n['role'] in ('assembly', 'final_test')],
                physical=physical)
    return store, journal, release, args


def accepted_output(payload):
    output = review_contract(payload)
    output.update(accepted=True, findings=[])
    for item in output['requirements']:
        item.update(satisfied=True, artifact_path='report.md', excerpt='Captured complete report')
    for item in output['criteria']:
        item['satisfied'] = True
    return output


def test_review_queues_once_uses_different_family_and_includes_artifacts(tmp_path):
    store, journal, release, args = prepared(tmp_path)
    review = ContentReviewRuntime(journal, store)
    waiting = review.ensure('content-task', **args)
    assert waiting['status'] == 'WAITING_FOR_INDEPENDENT_CONTENT_REVIEW'
    assert ContentReviewRuntime(journal, store).ensure('content-task', **args) == waiting
    job = store.get(waiting['job_id'])
    assert 'Captured complete report' in node_prompt(job, '')
    assert 'external actions' in node_prompt(job, '')
    intent = job['payload']['planning_intent']
    binding = job['payload']['content_review']
    assert intent['complexity'] == 9
    for key in intent['candidate_profiles']:
        assert job['payload']['task_catalog']['models'][key]['family'] not in binding['producer_families']
    claimed = store.claim('fixture', allowed_kinds=['TASK_PLAN'], requires_cleanup=True, worker_slot='slot1')
    assert claimed['job_id'] == job['job_id']
    output = accepted_output(claimed['payload'])
    store.clear_execution_quarantine(claimed['job_id'], claimed['attempt_id'], claimed['fencing_token'])
    store.complete(claimed['job_id'], claimed['attempt_id'], claimed['fencing_token'], output,
                   accepted_receipt(claimed, output))
    result = ContentReviewRuntime(journal, store).ensure('content-task', **args)
    assert result['status'] == 'VERIFIED'
    assert result['evidence']['kind'] == 'independent_model_content_review'
    assert result['evidence']['external_actions_verified'] is False
    assert result['evidence']['code_tests_executed'] is False
    proof = review.committed_result(store, args['producers'][-1])
    assert proof['accepted'] is True
    assert proof['review_job_id'] == job['job_id']
    store.close()


@pytest.mark.parametrize('change', ['quote', 'missing', 'binding', 'self_review', 'criterion', 'findings'])
def test_content_review_rejects_unbound_or_inconsistent_claims(tmp_path, change):
    store, journal, release, args = prepared(tmp_path)
    result = ContentReviewRuntime(journal, store).ensure('content-task', **args)
    job = store.get(result['job_id'])
    payload = deepcopy(job['payload'])
    model = deepcopy(payload['task_catalog']['models'][payload['planning_intent']['candidate_profiles'][0]])
    output = accepted_output(payload)
    if change == 'quote':
        output['requirements'][0]['excerpt'] = 'fabricated content'
    elif change == 'missing':
        output['requirements'].pop()
    elif change == 'binding':
        output['review_binding_sha256'] = 'f' * 64
    elif change == 'self_review':
        model['family'] = payload['content_review']['producer_families'][0]
    elif change == 'criterion':
        output['criteria'][0]['satisfied'] = False
    else:
        output['findings'] = ['Unresolved incorrect statement']
    with pytest.raises(ValueError):
        validate_content_review(payload, output, model)
    store.close()


def test_rejected_review_is_a_valid_result_not_a_success_or_format_retry(tmp_path):
    store, journal, release, args = prepared(tmp_path)
    review = ContentReviewRuntime(journal, store)
    job_id = review.ensure('content-task', **args)['job_id']
    claimed = store.claim('fixture', allowed_kinds=['TASK_PLAN'], requires_cleanup=True, worker_slot='slot1')
    output = review_contract(claimed['payload'])
    store.clear_execution_quarantine(claimed['job_id'], claimed['attempt_id'], claimed['fencing_token'])
    store.complete(claimed['job_id'], claimed['attempt_id'], claimed['fencing_token'], output,
                   accepted_receipt(claimed, output))
    assert review.ensure('content-task', **args)['status'] == 'CONTENT_REVIEW_REJECTED'
    assert store.get(job_id)['status'] == 'COMPLETED'
    assert review.committed_result(store, args['producers'][-1])['accepted'] is False
    assert journal.status('content-task')['stage'] == 'MICROTASKS_READY'
    store.close()


@pytest.mark.parametrize('include_deliverables', [True, False])
def test_content_release_retains_review_without_inventing_controller_tests(tmp_path, include_deliverables):
    from types import SimpleNamespace
    store, journal, release, args = prepared(tmp_path, include_deliverables=include_deliverables)
    release.artifact_runtime = SimpleNamespace(ensure_verification=lambda *_: args['physical'])
    waiting = release.step_microtask_task('content-task')
    assert waiting['status'] == 'WAITING_FOR_INDEPENDENT_CONTENT_REVIEW'
    assert journal.status('content-task')['stage'] != 'COMPLETED'
    claimed = store.claim('fixture', allowed_kinds=['TASK_PLAN'], requires_cleanup=True, worker_slot='slot1')
    output = accepted_output(claimed['payload'])
    store.clear_execution_quarantine(claimed['job_id'], claimed['attempt_id'], claimed['fencing_token'])
    store.complete(claimed['job_id'], claimed['attempt_id'], claimed['fencing_token'], output,
                   accepted_receipt(claimed, output))
    result = release.step_microtask_task('content-task')
    if not include_deliverables:
        assert result['status'] == 'DELIVERABLE_NOT_IN_FINAL_SNAPSHOT'
        assert release.get_release('content-task') is None
        store.close()
        return
    assert result['status'] == 'EXECUTION_COMPLETED'
    saved = release.get_release('content-task')
    assert saved['verification_scope'] == 'content_integrity_and_independent_model_review'
    assert saved['controller_test_receipts'] == []
    assert saved['independent_content_reviews'][0]['code_tests_executed'] is False
    assert saved['physical_verification'][0]['job_id'] == 'integrity-job'
    assert saved['original_repository_integration'] == 'NOT_APPLICABLE'
    with journal._write() as conn:
        assert conn.execute('SELECT count(*) FROM task428_test_receipts').fetchone()[0] == 0
    store.close()
