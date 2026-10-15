"""Actual temporary file/snapshot/SQLite fracture flow; native ports are inert."""
import hashlib
import json
import threading
from types import SimpleNamespace
import pytest

from cochem_pipeline.content_review_428 import review_contract
from cochem_pipeline.task_artifact_runtime_428 import TaskArtifactRuntime
from pipeline_tests.test_planning_gateway_428 import accepted_receipt
from pipeline_tests.test_planning_pivots_428 import env, complete_review
from pipeline_tests.test_planning_fractures_428 import prepare_fracture, attach_board, finish_control


def install_artifact_port(env, tmp_path):
    store, journal, ledger, board, outcomes, bridge = env
    spaces = []
    def workspace(_):
        root = tmp_path / ('fracture-space-' + str(len(spaces)))
        root.mkdir(); spaces.append(root)
        return SimpleNamespace(root=root, identity='inert', validate=lambda **_: None)
    def model(job, *_args, **_kwargs):
        node = job['payload']['microtask_node']
        files = []
        for path in node['deliverables']:
            text = '# Produced ' + path + ' by ' + node['microtask_id'] + '\n'
            files.append(dict(name=path, content=text, sha256=hashlib.sha256(text.encode()).hexdigest()))
        output = dict(artifact_text='Proposal for ' + node['microtask_id'], deliverables=files,
            requirement_evidence=[dict(requirement_id=req, deliverable_name=files[0]['name'],
                verification_evidence='Bound proposed content') for req in node['requirement_ids']],
            release_criteria_results=[dict(criterion=value, passed=True, evidence='Awaiting controller proof')
                                     for value in node['release_criteria']])
        return output, accepted_receipt(job, output)
    host = SimpleNamespace(store=store, coding=None, ramdisk=SimpleNamespace(workspace=workspace),
        config=SimpleNamespace(lease_seconds=30), runner=SimpleNamespace(run=model))
    artifacts = TaskArtifactRuntime(host)
    artifacts.prepare_task('task', None)
    host.task_planning = SimpleNamespace(store=store, journal=journal,
        fracture_runtime=bridge.fractures.fracture_runtime, attempt_runtime=outcomes.accounting)
    board.artifact_runtime = artifacts
    outcomes.artifact_runtime = artifacts
    return artifacts


def execute_one(store, artifacts, *, reject_review=False, job=None):
    job = job or store.claim('inert-physical-fracture', worker_slot='slot1',
                      allowed_kinds=['TASK_PLAN', 'TASK_VERIFY'], requires_cleanup=True)
    assert job is not None
    if job['kind'] == 'TASK_VERIFY':
        output, receipt, evidence = artifacts.run_verification(job, 'slot1', lambda: True, threading.Event())
        store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
        store.complete_task_verification(job['job_id'], job['attempt_id'], job['fencing_token'],
                                         output, receipt, evidence=evidence)
    else:
        if job['payload']['planning_intent']['stage'] == 'CONTENT_REVIEW':
            output = review_contract(job['payload'])
            output.update(accepted=not reject_review, findings=['Required content missing'] if reject_review else [])
            path, text = next(iter(job['payload']['content_review']['artifacts'].items()))
            for item in output['requirements']:
                item.update(satisfied=not reject_review, artifact_path=path, excerpt=text, assessment='Inspected exact content')
            for item in output['criteria']:
                item.update(satisfied=not reject_review, assessment='Inspected exact content')
            receipt = accepted_receipt(job, output)
        else:
            assert job['payload']['planning_intent']['stage'] == 'MICROTASK_EXECUTION'
            output, receipt = artifacts.run(job, 'slot1', '', lambda: True, lambda _: None, threading.Event(),
                                           on_native_start=lambda _: None, on_native_end=lambda: None)
        store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
        store.complete(job['job_id'], job['attempt_id'], job['fencing_token'], output, receipt)
    return job


def fracture_after_physical_predecessors(env, artifacts, failed_id, *, failure_count=10):
    store, _, ledger, board, outcomes, bridge = env
    failures = 0
    while failures < failure_count:
        outcomes.reconcile_task('task')
        board.materialize('task')
        job = store.claim('inert-fracture-boundary', worker_slot='slot1',
                          allowed_kinds=['TASK_PLAN', 'TASK_VERIFY'], requires_cleanup=True)
        assert job is not None
        if job['payload'].get('microtask_node', {}).get('microtask_id') != failed_id:
            execute_one(store, artifacts, job=job)
            continue
        store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
        store.fail(job['job_id'], job['attempt_id'], job['fencing_token'],
                   'Inert failed original scope', retry=True, category='code')
        failures += 1
    outcomes.reconcile_task('task')
    boundary = outcomes.status('task')[-1]
    request = json.loads(outcomes.research_runtime.queue_status(boundary['research_id'])['intent_json'])
    evidence = outcomes.research_runtime.evidence_store
    for channel in ('internet', 'wiki_rag', 'papers'):
        evidence.record_channel(boundary['research_id'], channel, query=request['query'], status='no_results', sources=[])
    evidence.publish(boundary['research_id'])
    outcomes.reconcile_task('task')
    complete_review(env, strategy='fracture')
    bridge.step('task')
    finish_control(env, 'FRACTURE_PLAN')
    bridge.step('task')
    finish_control(env, 'FRACTURE_REVIEW')
    bridge.step('task')
    attach_board(env)
    return job, boundary


def finish_physical_task(env, artifacts, *, reject_first_review=False):
    from cochem_pipeline.task_release_428 import TaskReleaseRuntime
    store, journal, _, board, outcomes, _ = env
    release = TaskReleaseRuntime(journal, store, board=board, artifact_runtime=artifacts)
    rejected = False
    jobs = []
    for _ in range(40):
        outcomes.reconcile_task('task')
        status = release.step_microtask_task('task')
        if status['status'] == 'EXECUTION_COMPLETED':
            return release, jobs
        job = store.claim('inert-fracture-finish', worker_slot='slot1',
                          allowed_kinds=['TASK_PLAN', 'TASK_VERIFY'], requires_cleanup=True)
        assert job is not None, status
        reject = (reject_first_review and not rejected
                  and job['payload'].get('planning_intent', {}).get('stage') == 'CONTENT_REVIEW')
        execute_one(store, artifacts, reject_review=reject, job=job)
        rejected |= reject
        jobs.append(job)
    raise AssertionError('Bounded inert task did not reach release')


def test_full_fracture_board_waits_for_physical_review_before_downstream(env, tmp_path):
    artifacts = install_artifact_port(env, tmp_path)
    old, boundary, _, _ = prepare_fracture(env)
    attach_board(env)
    store, _, ledger, board, outcomes, _ = env
    original_id = old['payload']['microtask_node']['microtask_id']
    saw_review = False
    for _ in range(16):
        outcomes.reconcile_task('task')
        status = board.materialize('task')
        original = next(node for node in status['nodes'] if node['microtask_id'] == original_id)
        if original['status'] == 'COMPLETED':
            break
        downstream = next(node for node in status['nodes'] if node['microtask_id'] == 'mt-2')
        assert downstream['job_id'] is None
        job = execute_one(store, artifacts)
        saw_review |= job['payload'].get('planning_intent', {}).get('stage') == 'CONTENT_REVIEW'
    assert original['status'] == 'COMPLETED' and saw_review
    assert original['output']['fracture_join_id']
    assert artifacts.verification_outcome(store.get(original['job_id']))['status'] == 'VERIFIED'
    assert ledger.status(boundary['lineage_root'])['failures'] == 10
    assert store.get(old['job_id'])['status'] == 'BLOCKED'


def test_fractured_scope_inherits_exact_physical_predecessors_through_parent_release(env, tmp_path):
    artifacts = install_artifact_port(env, tmp_path)
    original, boundary = fracture_after_physical_predecessors(env, artifacts, 'mt-2')
    assert set(original['payload']['predecessor_outputs']) == {'mt-1'}
    release, jobs = finish_physical_task(env, artifacts)
    children = [job for job in jobs if job['payload'].get('microtask_node', {}).get('fracture_context')]
    assert children and all('mt-1' in job['payload']['predecessor_outputs'] for job in children)
    assert release.get_release('task')
    assert env[2].status(boundary['lineage_root'])['failures'] == 10
    assert env[0].get(original['job_id'])['status'] == 'BLOCKED'


def test_failed_original_final_test_fractures_without_giving_assembly_its_test_paths(env, tmp_path):
    artifacts = install_artifact_port(env, tmp_path)
    original, boundary = fracture_after_physical_predecessors(env, artifacts, 'mt-4')
    release, jobs = finish_physical_task(env, artifacts)
    children = [job for job in jobs if job['payload'].get('microtask_node', {}).get('fracture_context')]
    assembly = next(job for job in children if job['payload']['microtask_node']['role'] == 'assembly')
    final = next(job for job in children if job['payload']['microtask_node']['role'] == 'final_test')
    test_paths = set(original['payload']['microtask_node']['deliverables'])
    assert not test_paths.intersection(assembly['payload']['microtask_node']['deliverables'])
    assert test_paths <= set(final['payload']['microtask_node']['deliverables'])
    assert release.get_release('task')
    assert env[2].status(boundary['lineage_root'])['failures'] == 10


@pytest.mark.parametrize('complete_sibling_first', [True, False])
def test_nested_physical_alias_advances_old_registered_child_without_rewriting_attempts(env, tmp_path, monkeypatch, complete_sibling_first):
    import time
    from cochem_pipeline import routing_store
    route_offset = [0]
    monkeypatch.setattr(routing_store, 'time', SimpleNamespace(time=lambda: time.time() + route_offset[0]))
    artifacts = install_artifact_port(env, tmp_path)
    _, first, _, _ = prepare_fracture(env)
    attach_board(env)
    store, _, ledger, board, outcomes, _ = env
    start = board.materialize('task')
    child = next(row for row in start['nodes'] if row['lineage_kind'] == 'FAILURE_FRACTURE'
                 and row['role'] == 'implementation')
    remaining = 10
    if complete_sibling_first:
        first_attempt = store.claim('inert-nested-first', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
        assert first_attempt['payload']['microtask_node']['microtask_id'] == child['microtask_id']
        execute_one(store, artifacts)
        store.clear_execution_quarantine(first_attempt['job_id'], first_attempt['attempt_id'], first_attempt['fencing_token'])
        store.fail(first_attempt['job_id'], first_attempt['attempt_id'], first_attempt['fencing_token'],
                   'Inert nested scope failure', retry=True, category='code')
        remaining = 9
    failed, second = fracture_after_physical_predecessors(env, artifacts, child['microtask_id'], failure_count=remaining)
    assert first['lineage_root'] == second['lineage_root']
    assert ledger.status(first['lineage_root'])['failures'] == 20
    for _ in range(20):
        outcomes.reconcile_task('task')
        status = board.materialize('task')
        projected = next(row for row in status['nodes'] if row['microtask_id'] == child['microtask_id'])
        if projected['status'] == 'COMPLETED':
            break
        job = store.claim('inert-nested-fracture', worker_slot='slot1',
                          allowed_kinds=['TASK_PLAN', 'TASK_VERIFY'], requires_cleanup=True)
        if job is None:
            route_offset[0] += 2  # Advance the bounded research availability wait, never a quality attempt.
            job = store.claim('inert-nested-fracture', worker_slot='slot1',
                              allowed_kinds=['TASK_PLAN', 'TASK_VERIFY'], requires_cleanup=True)
        assert job is not None, '\n'.join(str((n['microtask_id'], n['status'], n.get('reason'),
            store.get(n['job_id']).get('error') if n.get('job_id') else None)) for n in status['nodes'])
        execute_one(store, artifacts, job=job)
    assert projected['status'] == 'COMPLETED'
    assert projected['output']['fracture_join_id']
    assert board.fracture_runtime.get_fracture_child(child['microtask_id'])['status'] == 'COMPLETED'
    assert ledger.status(first['lineage_root'])['failures'] == 20
    assert store.get(failed['job_id'])['status'] == 'BLOCKED'
    again = board.materialize('task')
    assert next(row for row in again['nodes'] if row['microtask_id'] == child['microtask_id'])['output'] == projected['output']
