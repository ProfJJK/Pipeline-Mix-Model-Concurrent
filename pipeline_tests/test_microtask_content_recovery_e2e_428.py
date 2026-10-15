"""Temporary physical artifacts and SQLite, with inert native/reviewer ports."""
import threading

from cochem_pipeline.content_review_428 import ContentReviewRuntime, review_contract
from cochem_pipeline.microtask_board_428 import MicrotaskBoardRuntime
from cochem_pipeline.task_artifact_runtime_428 import TaskArtifactRuntime
from pipeline_tests.test_planning_gateway_428 import accepted_receipt
from pipeline_tests.test_task_content_verification_e2e_428 import content_task


def commit_review(store, journal, args, accepted):
    review = ContentReviewRuntime(journal, store)
    review.ensure('content-task', **args)
    reviewer = store.claim('inert-reviewer', worker_slot='slot3', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    assert reviewer['payload']['planning_intent']['stage'] == 'CONTENT_REVIEW'
    output = review_contract(reviewer['payload'])
    output['accepted'] = accepted
    output['findings'] = [] if accepted else ['The numerical result is missing.']
    path, text = next(iter(reviewer['payload']['content_review']['artifacts'].items()))
    for item in output['requirements']:
        item.update(satisfied=accepted, artifact_path=path, excerpt=text,
                    assessment='Inspected exact staged content.')
    for item in output['criteria']:
        item.update(satisfied=accepted, assessment='Inspected the requirement.')
    store.clear_execution_quarantine(reviewer['job_id'], reviewer['attempt_id'], reviewer['fencing_token'])
    store.complete(reviewer['job_id'], reviewer['attempt_id'], reviewer['fencing_token'], output,
                   accepted_receipt(reviewer, output))
    review.ensure('content-task', **args)
    return reviewer


def test_content_rejection_repairs_assembly_twice_and_preserves_exact_producers(content_task):
    store, journal, artifacts, original, args, outcomes = content_task
    outcomes.reconcile_task('content-task')
    prior_final = original
    histories = []
    for generation in (1, 2):
        commit_review(store, journal, args, False)
        outcomes.reconcile_task('content-task')
        feedback = artifacts.retry_feedback('content-task', 'mt-4')
        assert feedback['retry_generation'] == generation
        assert feedback['producer_job_id'] == prior_final['job_id']
        # Recreate adapters to exercise reconstruction from durable evidence.
        artifacts = TaskArtifactRuntime(artifacts.runtime)
        board = MicrotaskBoardRuntime(journal, store, artifact_runtime=artifacts,
                                      attempt_ledger=outcomes.accounting)
        snapshot = board.materialize('content-task')
        before = {n['microtask_id']: n for n in snapshot['nodes']}
        assert before['mt-4']['status'] == 'WAITING_ON_DEPENDENCIES'
        assert board.materialize('content-task')['nodes'] == snapshot['nodes']
        for role in ('assembly', 'final_test'):
            producer = store.claim('inert-repair', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
            assert producer['payload']['microtask_node']['role'] == role
            assert producer['payload']['microtask_node']['physical_retry']['failed_checks'] == [feedback]
            if role == 'final_test':
                dep = producer['payload']['predecessor_outputs']['mt-3']
                assert dep['producer_job_id'] == assembly['job_id']
                assert dep['producer_attempt_id'] == assembly['attempt_id']
                assert dep['producer_fencing_token'] == assembly['fencing_token']
            output, receipt = artifacts.run(producer, 'slot1', '', lambda: True, lambda _: None,
                threading.Event(), on_native_start=lambda _: None, on_native_end=lambda: None)
            store.clear_execution_quarantine(producer['job_id'], producer['attempt_id'], producer['fencing_token'])
            store.complete(producer['job_id'], producer['attempt_id'], producer['fencing_token'], output, receipt)
            snapshot = board.materialize('content-task')
            if role == 'assembly':
                assembly = producer
        assert snapshot['all_completed']
        final = next(n for n in snapshot['nodes'] if n['role'] == 'final_test')
        producer = store.get(final['job_id'])
        assert producer['job_id'] != prior_final['job_id']
        artifacts.ensure_verification(producer, final['requirement_ids'])
        verifier = store.claim('inert-verifier', worker_slot='slot2', allowed_kinds=['TASK_VERIFY'], requires_cleanup=True)
        output, receipt, evidence = artifacts.run_verification(verifier, 'slot2', lambda: True, threading.Event())
        store.clear_execution_quarantine(verifier['job_id'], verifier['attempt_id'], verifier['fencing_token'])
        store.complete_task_verification(verifier['job_id'], verifier['attempt_id'], verifier['fencing_token'],
                                         output, receipt, evidence=evidence)
        physical = artifacts.ensure_verification(producer, final['requirement_ids'])
        args = dict(args, physical=physical,
                    producers=[n['job_id'] for n in snapshot['nodes'] if n['role'] in ('assembly', 'final_test')])
        outcomes.reconcile_task('content-task')
        assert outcomes.accounting.ledger.status(feedback['lineage_root'])['failures'] == generation
        histories.append(prior_final['job_id'])
        prior_final = producer
    commit_review(store, journal, args, True)
    outcomes.reconcile_task('content-task')
    assert artifacts.verification_outcome(prior_final)['status'] == 'VERIFIED'
    assert outcomes.accounting.ledger.status(feedback['lineage_root'])['failures'] == 2
    assert all(store.get(job_id)['status'] == 'COMPLETED' for job_id in histories)
    assert board.materialize('content-task')['all_completed']
