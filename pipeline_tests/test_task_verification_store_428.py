"""Fenced controller verification storage. SQLite fixtures, no processes or Docker."""
from copy import deepcopy
import json
import sqlite3
import time

import pytest

from cochem_pipeline.coding import digest, manifest
from cochem_pipeline.coding_store import CODING_KINDS, CONTROLLER_KINDS
from cochem_pipeline.store import JobStore


def queued(tmp_path, kind='TASK_VERIFY', *, cleanup=False, files=None, payload_extra=None):
    store = JobStore(tmp_path / 'jobs.db')
    files = files or {'report.txt': b'Exact captured deliverable\n'}
    with store._write() as conn:
        snapshot = store._snapshot(conn, files)
        store._insert(conn, 'root', 'root', None, 'MACRO_PLANNING_REQUEST', 'IN_PROGRESS',
                      {'workflow_type': 'task_verification428'})
        payload = dict(schema='cochem-task-verification/4.2.8', task_id='task',
                       verification_key='a' * 64, source_snapshot_sha256=snapshot,
                       mode='artifact_integrity' if kind == 'TASK_VERIFY' else 'coding_tests')
        payload.update(payload_extra or {})
        store._insert(conn, 'verify', 'root', 'root', kind, 'PENDING', payload)
    node = store.claim('fixture', allowed_kinds=[kind], requires_cleanup=cleanup, worker_slot='slot1')
    return store, node, files


def completion(node, files):
    from cochem_pipeline.task_verification_428 import verify_artifact_evidence
    identity = {key: node[key] for key in ('job_id', 'attempt_id', 'fencing_token')}
    payload = node['payload']
    evidence = dict(identity, kind='artifact-integrity', observed_manifest=manifest(files),
                    cleanup_verified=True, verification_key=payload['verification_key'],
                    source_snapshot_sha256=payload['source_snapshot_sha256'])
    output = verify_artifact_evidence(payload, evidence, files)
    receipt = dict(identity, executor='task_verifier', output_sha256=digest(output), cleanup_verified=True)
    return output, receipt, evidence


def complete(store, node, output, receipt, evidence):
    return store.complete_task_verification(node['job_id'], node['attempt_id'], node['fencing_token'],
                                            output, receipt, evidence=evidence)


def test_verification_jobs_are_controller_only_and_not_coding_workflows():
    assert {'TASK_VERIFY', 'TASK_TEST'} <= set(CONTROLLER_KINDS)
    assert not {'TASK_VERIFY', 'TASK_TEST'} & set(CODING_KINDS)


def test_verification_needs_durable_attempt_evidence(tmp_path):
    store, node, files = queued(tmp_path)
    output, receipt, evidence = completion(node, files)
    with pytest.raises(ValueError, match='durable'):
        complete(store, node, output, receipt, evidence)
    store.record_coding_attempt_evidence(node, evidence)
    accepted = complete(store, node, output, receipt, evidence)
    assert accepted['status'] == 'COMPLETED'
    assert accepted['output']['verification_kind'] == 'artifact_integrity'
    assert accepted['output']['verified_requirements'] == []
    assert accepted['routing'] is None
    assert store.get('root')['status'] == 'COMPLETED'


def test_durable_check_survives_restart_and_never_replays_a_completed_lease(tmp_path):
    store, node, files = queued(tmp_path)
    output, receipt, evidence = completion(node, files)
    store.record_coding_attempt_evidence(node, evidence)
    store.close()
    store = JobStore(store.path)
    assert complete(store, node, output, receipt, evidence)['status'] == 'COMPLETED'
    with pytest.raises(ValueError, match='Stale'):
        complete(store, node, output, receipt, evidence)
    with store._connection() as conn:
        assert conn.execute('SELECT count(*) FROM pipeline_outputs').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM coding_evidence').fetchone()[0] == 1


@pytest.mark.parametrize('changed', ['job_id', 'attempt_id', 'fencing_token', 'executor',
                                    'output_sha256', 'cleanup_verified'])
def test_receipt_must_bind_exact_controller_attempt(tmp_path, changed):
    store, node, files = queued(tmp_path)
    output, receipt, evidence = completion(node, files)
    store.record_coding_attempt_evidence(node, evidence)
    receipt[changed] = False if changed == 'cleanup_verified' else 'wrong'
    with pytest.raises(ValueError, match='exact controller attempt'):
        complete(store, node, output, receipt, evidence)
    assert store.get(node['job_id'])['status'] == 'IN_PROGRESS'


@pytest.mark.parametrize('changed', ['job_id', 'attempt_id', 'fencing_token',
                                    'verification_key', 'source_snapshot_sha256'])
def test_evidence_must_bind_exact_target_source_and_attempt(tmp_path, changed):
    store, node, files = queued(tmp_path)
    output, receipt, evidence = completion(node, files)
    evidence[changed] = 'wrong'
    store.record_coding_attempt_evidence(node, evidence)
    with pytest.raises(ValueError, match='exact'):
        complete(store, node, output, receipt, evidence)


def test_cleanup_fence_remains_even_when_evidence_claims_cleanup(tmp_path):
    store, node, files = queued(tmp_path, cleanup=True)
    output, receipt, evidence = completion(node, files)
    store.record_coding_attempt_evidence(node, evidence)
    with pytest.raises(ValueError, match='cleanup'):
        complete(store, node, output, receipt, evidence)
    assert not store.claim('another', allowed_kinds=['TASK_VERIFY'])
    store.clear_execution_quarantine(node['job_id'], node['attempt_id'], node['fencing_token'])
    assert complete(store, node, output, receipt, evidence)['status'] == 'COMPLETED'


def test_cancelled_or_expired_lease_cannot_publish_even_recorded_evidence(tmp_path, monkeypatch):
    store, node, files = queued(tmp_path)
    output, receipt, evidence = completion(node, files)
    store.record_coding_attempt_evidence(node, evidence)
    with monkeypatch.context() as patch:
        patch.setattr(time, 'time', lambda: node['lease_expires_at'] + 1)
        with pytest.raises(ValueError, match='Stale'):
            complete(store, node, output, receipt, evidence)
    store.cancel_workflow(node['workflow_id'])
    with pytest.raises(ValueError, match='Stale'):
        complete(store, node, output, receipt, evidence)
    assert store.get(node['job_id'])['status'] == 'FAILED'


def test_changed_evidence_cannot_replace_the_durable_record(tmp_path):
    store, node, files = queued(tmp_path)
    output, receipt, evidence = completion(node, files)
    store.record_coding_attempt_evidence(node, evidence)
    evidence['extra'] = 'unrecorded observation'
    with pytest.raises(ValueError, match='durable'):
        complete(store, node, output, receipt, evidence)
    with pytest.raises(sqlite3.IntegrityError):
        store.record_coding_attempt_evidence(node, evidence)


def test_model_claim_cannot_upgrade_integrity_to_semantic_acceptance(tmp_path):
    store, node, files = queued(tmp_path)
    output, receipt, evidence = completion(node, files)
    store.record_coding_attempt_evidence(node, evidence)
    output['verified_requirements'] = ['requirement-1']
    receipt['output_sha256'] = digest(output)
    with pytest.raises(ValueError, match='independently validated'):
        complete(store, node, output, receipt, evidence)
    with pytest.raises(ValueError):
        store.complete(node['job_id'], node['attempt_id'], node['fencing_token'], output, receipt)
    with pytest.raises(ValueError, match='Not a coding'):
        store.complete_coding(node['job_id'], node['attempt_id'], node['fencing_token'],
                              output, receipt, evidence=evidence)


@pytest.mark.parametrize('category', ['resource', 'quota', 'auth', 'busy', 'provider', 'backlog'])
def test_controller_availability_preserves_failure_budget_and_waits(tmp_path, category):
    store, node, _ = queued(tmp_path)
    assert store.fail(node['job_id'], node['attempt_id'], node['fencing_token'], 'unavailable',
                      retry=True, category=category, retry_after_seconds=60)
    with store._connection() as conn:
        row = conn.execute('SELECT * FROM coding_controller_retries').fetchone()
        assert row['failures'] == 0
        assert row['next_eligible_at'] >= time.time() + 55
    assert store.get(node['job_id'])['attempts'] == 1
    assert store.get(node['job_id'])['status'] == 'PENDING_RETRY'
    assert store.claim('fixture', allowed_kinds=['TASK_VERIFY']) is None


def test_controller_failures_still_exhaust_the_existing_budget(tmp_path):
    store, node, _ = queued(tmp_path)
    for expected in (1, 2, 3):
        assert store.fail(node['job_id'], node['attempt_id'], node['fencing_token'], 'physical check failed',
                          retry=True, category='code')
        with store._connection() as conn:
            assert conn.execute('SELECT failures FROM coding_controller_retries').fetchone()[0] == expected
        if expected < 3:
            node = store.claim('fixture', allowed_kinds=['TASK_VERIFY'])
    assert store.get(node['job_id'])['status'] == 'BLOCKED'


def test_old_schema_migration_preserves_rows_policy_and_foreign_keys(tmp_path, monkeypatch):
    import cochem_pipeline.store as store_module
    current = store_module.SCHEMA
    with monkeypatch.context() as patch:
        patch.setattr(store_module, 'SCHEMA', current.replace(",'TASK_VERIFY','TASK_TEST'", ''))
        store = JobStore(tmp_path / 'jobs.db')
        submitted = store.submit('Preserve this task', ['retain exact inputs'], workflow_id='older')
        original = json.dumps(store.get('older')['payload'], sort_keys=True)
        store.close()
    store = JobStore(store.path)
    assert json.dumps(store.get('older')['payload'], sort_keys=True) == original
    with store._connection() as conn:
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='pipeline_jobs'").fetchone()[0]
        assert "'TASK_VERIFY'" in sql and "'TASK_TEST'" in sql


def task_test(tmp_path, phase, *, successful=True):
    from cochem_pipeline.container_policy import DockerPolicy
    from cochem_pipeline.task_verification_428 import requirement_test_names, verify_task_test_evidence
    names = requirement_test_names(['requirement-1'])
    name = names['requirement-1']
    path = 'tests/test_requirements.py'
    files = {path: f'def {name}():\n    assert 1 == 2\n'.encode()}
    image = 'sha256:' + 'd' * 64
    policy = DockerPolicy.from_dict(dict(enabled=True, image=image, allowed_images=[image],
                                        commands=[dict(name='unit', argv=['python', '-m', 'pytest', '-q'])]))
    identity = dict(path=path, file_sha256=manifest(files)[path], class_name='tests.test_requirements')
    payload_extra = dict(test_phase=phase, docker=policy.as_dict(), requirement_test_names=names,
                         expected_test_identities={name: identity}, microtask_id=None)
    store, node, files = queued(tmp_path, 'TASK_TEST', files=files, payload_extra=payload_extra)
    index = {path: dict(sha256=identity['file_sha256'], size=len(files[path]), executable=False)}
    case = dict(name=name, class_name=identity['class_name'], status='failed' if phase == 'red' else 'passed')
    if phase == 'red' and successful:
        case['assertion_failure'] = dict(phase='call', exception_type='AssertionError', path=path,
                                        line=2, source_sha256=identity['file_sha256'])
    evidence = {key: node[key] for key in ('job_id', 'attempt_id', 'fencing_token')}
    evidence.update(kind='docker-test-execution', image_id=image, policy_sha256=policy.digest,
                    source_verified=True, cleanup_verified=True,
                    source=dict(files=index, sha256=digest(index)),
                    verification_key=node['payload']['verification_key'],
                    source_snapshot_sha256=node['payload']['source_snapshot_sha256'],
                    passed=phase == 'green' and successful,
                    failure_category='tests_failed' if phase == 'red' or not successful else None,
                    commands=[dict(exit_code=1 if phase == 'red' else 0,
                                   junit=dict(errors=0, failures=1 if phase == 'red' else 0),
                                   junit_cases=[case])])
    output = verify_task_test_evidence(node['payload'], evidence, files)
    receipt = {key: node[key] for key in ('job_id', 'attempt_id', 'fencing_token')}
    receipt.update(executor='task_verifier', cleanup_verified=True, output_sha256=digest(output))
    return store, node, files, output, receipt, evidence


@pytest.mark.parametrize('phase', ['red', 'green'])
def test_docker_result_is_revalidated_from_durable_bound_source(tmp_path, phase):
    store, node, files, output, receipt, evidence = task_test(tmp_path, phase)
    store.record_coding_attempt_evidence(node, evidence)
    if phase == 'red':
        assert evidence['passed'] is False
    result = complete(store, node, output, receipt, evidence)
    assert result['status'] == 'COMPLETED'
    assert result['output']['status'] == 'VERIFIED'
    assert result['output']['passed'] is True
    assert result['output']['verified_requirements'] == ['requirement-1']


@pytest.mark.parametrize('phase', ['red', 'green'])
def test_rejected_physical_result_is_a_recorded_failure_not_a_model_success(tmp_path, phase):
    store, node, files, output, receipt, evidence = task_test(tmp_path, phase, successful=False)
    store.record_coding_attempt_evidence(node, evidence)
    assert output['status'] == 'REJECTED'
    forged = dict(output, status='VERIFIED', passed=True, verified_requirements=['requirement-1'])
    with pytest.raises(ValueError, match='independently validated'):
        complete(store, node, forged, dict(receipt, output_sha256=digest(forged)), evidence)
    result = complete(store, node, output, receipt, evidence)
    assert result['output']['status'] == 'REJECTED'
    assert result['output']['passed'] is False
    assert result['output']['verified_requirements'] == []


@pytest.mark.parametrize('change', ['source', 'cleanup', 'image', 'snapshot'])
def test_bound_but_invalid_docker_observation_still_rejects(tmp_path, change):
    store, node, files, output, receipt, evidence = task_test(tmp_path, 'green')
    if change == 'source':
        evidence['source']['files'] = {}
    elif change == 'cleanup':
        evidence['cleanup_verified'] = False
    elif change == 'image':
        evidence['image_id'] = 'sha256:' + 'e' * 64
    else:
        evidence['source_snapshot_sha256'] = 'e' * 64
    store.record_coding_attempt_evidence(node, evidence)
    with pytest.raises(ValueError):
        complete(store, node, output, receipt, evidence)
