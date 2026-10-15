"""Real temporary artifact custody and SQLite; inert native model ports only."""
from copy import deepcopy
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest

from cochem_pipeline.attempt_runtime_428 import AttemptAccountingRuntime
from cochem_pipeline.content_review_428 import ContentReviewRuntime, review_contract
from cochem_pipeline.microtask_board_428 import MicrotaskBoardRuntime
from cochem_pipeline.planning_outcomes_428 import PlanningOutcomeRuntime
from cochem_pipeline.task_artifact_runtime_428 import TaskArtifactRuntime
from cochem_pipeline.workflow_428 import AttemptLedger
from pipeline_tests.test_microtask_board_428 import _make_store_and_journal, _advance_task_to_reassessed_ready
from pipeline_tests.test_planning_gateway_428 import accepted_receipt


@pytest.fixture
def content_task(tmp_path):
    store, journal, broker = _make_store_and_journal(tmp_path)
    task_id = 'content-task'
    _advance_task_to_reassessed_ready(journal, task_id=task_id)
    spaces = []
    def workspace(_):
        root = tmp_path / ('slot-' + str(len(spaces))); root.mkdir(); spaces.append(root)
        return SimpleNamespace(root=root, identity='fixture', validate=lambda **_: None)
    def model(node, *_args, **_kwargs):
        micro = node['payload']['microtask_node']
        deliverables = []
        for path in micro['deliverables']:
            text = '# Captured fixture content for ' + micro['microtask_id'] + '\n'
            deliverables.append(dict(name=path, content=text, sha256=hashlib.sha256(text.encode()).hexdigest()))
        output = dict(artifact_text='Fixture proposal', deliverables=deliverables,
            requirement_evidence=[dict(requirement_id=req, deliverable_name=deliverables[0]['name'],
                verification_evidence='Proposed fixture content') for req in micro['requirement_ids']],
            release_criteria_results=[dict(criterion=c, passed=True, evidence='Proposal awaits controller review')
                                      for c in micro['release_criteria']])
        return output, accepted_receipt(node, output)
    host = SimpleNamespace(store=store, coding=None, ramdisk=SimpleNamespace(workspace=workspace),
                           config=SimpleNamespace(lease_seconds=30), runner=SimpleNamespace(run=model))
    artifacts = TaskArtifactRuntime(host)
    artifacts.prepare_task(task_id, None)
    board = MicrotaskBoardRuntime(journal, store, owner_broker=broker, artifact_runtime=artifacts)
    for _ in range(8):
        snap = board.materialize(task_id)
        if snap['all_completed']:
            break
        node = store.claim('inert-fixture', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
        assert node is not None
        output, receipt = artifacts.run(node, 'slot1', '', lambda: True, lambda _: None, threading.Event(),
                                       on_native_start=lambda _: None, on_native_end=lambda: None)
        store.clear_execution_quarantine(node['job_id'], node['attempt_id'], node['fencing_token'])
        store.complete(node['job_id'], node['attempt_id'], node['fencing_token'], output, receipt)
    assert snap['all_completed']
    final = next(item for item in snap['nodes'] if item['role'] == 'final_test')
    producer = store.get(final['job_id'])
    artifacts.ensure_verification(producer, final['requirement_ids'])
    node = store.claim('inert-fixture', worker_slot='slot2', allowed_kinds=['TASK_VERIFY'], requires_cleanup=True)
    output, receipt, evidence = artifacts.run_verification(node, 'slot2', lambda: True, threading.Event())
    store.clear_execution_quarantine(node['job_id'], node['attempt_id'], node['fencing_token'])
    store.complete_task_verification(node['job_id'], node['attempt_id'], node['fencing_token'],
                                     output, receipt, evidence=evidence)
    physical = artifacts.ensure_verification(producer, final['requirement_ids'])
    with journal._write() as conn:
        state = json.loads(journal._read(conn, task_id)['state_json'])
    args = dict(state=state, generation=snap['plan_generation_sha256'], physical=physical,
                producers=[item['job_id'] for item in snap['nodes'] if item['role'] in ('assembly', 'final_test')])
    outcomes = PlanningOutcomeRuntime(journal, store,
        AttemptAccountingRuntime(AttemptLedger(tmp_path / 'outcomes.db'), store=store), artifact_runtime=artifacts)
    yield store, journal, artifacts, producer, args, outcomes
    store.close()


@pytest.mark.parametrize('accepted', [False, True])
def test_independent_content_verdict_charges_producer_and_never_penalizes_reviewer(content_task, accepted):
    store, journal, artifacts, producer, args, outcomes = content_task
    assert artifacts.verification_outcome(producer)['status'] == 'WAITING_FOR_INDEPENDENT_CONTENT_VERIFICATION'
    assert outcomes.reconcile_task('content-task') == 3
    review = ContentReviewRuntime(journal, store)
    review.ensure('content-task', **args)
    assert artifacts.retry_feedback('content-task', 'mt-4') is None
    reviewer = store.claim('inert-reviewer', worker_slot='slot3', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    output = review_contract(reviewer['payload'])
    output['accepted'] = accepted
    output['findings'] = [] if accepted else ['The supplied content omits the required numerical result.']
    path, text = next(iter(reviewer['payload']['content_review']['artifacts'].items()))
    for item in output['requirements']:
        item.update(satisfied=accepted, artifact_path=path, excerpt=text,
                    assessment='The claimed result is present.' if accepted else 'Required numerical result is missing.')
    for item in output['criteria']:
        item.update(satisfied=accepted, assessment='Inspected the final content.')
    store.clear_execution_quarantine(reviewer['job_id'], reviewer['attempt_id'], reviewer['fencing_token'])
    store.complete(reviewer['job_id'], reviewer['attempt_id'], reviewer['fencing_token'], output,
                   accepted_receipt(reviewer, output))
    review.ensure('content-task', **args)
    proof = artifacts.verification_outcome(producer)
    assert proof['status'] == ('VERIFIED' if accepted else 'REJECTED')
    assert proof['verification_scope'] == 'content_integrity_and_independent_model_review'
    assert outcomes.reconcile_task('content-task') == 2
    assert outcomes.reconcile_task('content-task') == 0
    lineage = producer['payload']['microtask_node']['attempt_lineage_id']
    assert outcomes.accounting.ledger.status(lineage)['failures'] == int(not accepted)
    with outcomes.accounting.ledger._write() as conn:
        assert conn.execute('SELECT staged_outcome FROM attempt428_outbox WHERE job_id=?',
                            (reviewer['job_id'],)).fetchone()[0] == 'success'
    feedback = artifacts.retry_feedback('content-task', 'mt-4')
    if accepted:
        assert feedback is None
    else:
        assert feedback['retry_generation'] == 1
        assert feedback['lineage_root'] == lineage
        assert feedback['failure']['category'] == 'content_review'
        assert feedback['failure']['findings'] == output['findings']
        assert artifacts.retry_feedback('content-task', 'mt-4') == feedback
        assert TaskArtifactRuntime(artifacts.runtime).retry_feedback('content-task', 'mt-4') == feedback


def test_review_receipt_cannot_be_substituted_for_different_physical_snapshot(content_task, monkeypatch):
    store, journal, artifacts, producer, args, outcomes = content_task
    physical = artifacts._committed_verification(args['physical']['job_id'])
    changed = dict(accepted=True, producer_job_id=producer['job_id'],
        producer_output_sha256=physical['producer_output_sha256'], physical_job_id=physical['verification_job_id'],
        source_snapshot_sha256='0' * 64)
    monkeypatch.setattr(ContentReviewRuntime, 'committed_result', lambda *_: deepcopy(changed))
    with pytest.raises(ValueError, match='physical producer'):
        artifacts.verification_outcome(producer)
