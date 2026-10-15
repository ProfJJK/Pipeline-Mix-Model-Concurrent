"""Actual temp-file/SQLite flow with inert native and Docker ports.

The engine port executes the trusted fixture assertion in this Python process;
it is not native/container acceptance and never starts a child or touches Git.
"""
from copy import deepcopy
import hashlib
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from cochem_pipeline.coding import CodingProject, digest, manifest, read_workspace
from cochem_pipeline.container_policy import DockerPolicy
from cochem_pipeline.task_artifact_runtime_428 import TaskArtifactRuntime
from cochem_pipeline.task_verification_428 import requirement_test_names
from pipeline_tests.test_container_policy import enabled
from pipeline_tests.test_planning_gateway_428 import accepted_receipt
from pipeline_tests.test_task_execution_428 import simple_env, _advance_to_ready


def _stage_proposal(simple_env, tmp_path, monkeypatch, proposed_value=1):
    controller, execution, journal, store = simple_env
    project = CodingProject.from_dict('fixture-project', dict(repository=str(tmp_path / 'repo'),
        branch='main', allowed_paths=['src'], test_paths=['tests']))
    baseline = {'src/value.py': b'value = 0\n'}
    snap = SimpleNamespace(files=baseline, modes={'src/value.py': '100644'},
                           as_dict=lambda: {'fixture': 'no Git execution'})
    monkeypatch.setattr('cochem_pipeline.coding_git.capture_repository', lambda *a, **k: snap)
    spaces = []
    def workspace(_):
        root = tmp_path / ('slot-' + str(len(spaces))); root.mkdir(); spaces.append(root)
        return SimpleNamespace(root=root, identity='fixture', validate=lambda **_: None)
    runtime = SimpleNamespace(store=store, boot_id=None,
        coding=SimpleNamespace(projects=lambda: {'fixture-project': project}),
        ramdisk=SimpleNamespace(workspace=workspace),
        config=SimpleNamespace(git_executable='unused', docker=DockerPolicy.from_dict(enabled()),
                               private_root=tmp_path, operator_name='fixture', lease_seconds=30))
    artifacts = TaskArtifactRuntime(runtime)
    artifacts.prepare_task('task', None if proposed_value == 'content' else 'fixture-project')
    execution.artifact_runtime = artifacts
    document = _advance_to_ready(controller, 'task', tier=2)
    controller.test_clock[0] += 2; controller.step()
    node = store.claim('fixture', allowed_kinds=['TASK_PLAN'], worker_slot='slot1', requires_cleanup=True)
    names = requirement_test_names([item['id'] for item in document['requirements']])
    source = 'from pathlib import Path\n' + ''.join(
        f'def {name}():\n    assert (Path(__file__).parents[1] / "src/value.py").read_text() == "value = 1\\n"\n'
        for name in names.values())
    if proposed_value == 0:
        source = source.replace('value = 1', 'value = 0')
    files = {'src/value.py': f'value = {proposed_value}\n', 'tests/test_bound.py': source}
    if proposed_value == 'missing_tests':
        files = {'src/value.py': 'value = 1\n'}
    elif proposed_value == 'content':
        files = {'report.md': 'A bounded content deliverable.\n'}
    output = dict(artifact_text='Concrete proposal',
        deliverables=[dict(name=p, content=text, sha256=hashlib.sha256(text.encode()).hexdigest())
                      for p, text in files.items()],
        requirement_evidence=[dict(requirement_id=key, deliverable_name=next(iter(files)),
                                   verification_evidence='Bound regression proposed') for key in names],
        release_criteria_results=[dict(criterion=c, passed=True, evidence='Proposal is ready for physical verification')
                                  for c in document['release_criteria']])
    runtime.runner = SimpleNamespace(run=lambda *a, **k: (deepcopy(output), accepted_receipt(node, output)))
    result, receipt = artifacts.run(node, 'slot1', '', lambda: True, lambda _: None, threading.Event(),
                                   on_native_start=lambda _: None, on_native_end=lambda: None)
    store.clear_execution_quarantine(node['job_id'], node['attempt_id'], node['fencing_token'])
    store.complete(node['job_id'], node['attempt_id'], node['fencing_token'], result, receipt)
    return artifacts, runtime, store.get(node['job_id']), sorted(names), spaces


@pytest.fixture
def staged(simple_env, tmp_path, monkeypatch, request):
    return _stage_proposal(simple_env, tmp_path, monkeypatch, getattr(request, 'param', 1))


def test_missing_requirement_tests_fail_before_producer_publication(simple_env, tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        _stage_proposal(simple_env, tmp_path, monkeypatch, 'missing_tests')
    store = simple_env[-1]
    with store._connection() as conn:
        assert not conn.execute('SELECT 1 FROM task428_fragment_attempts').fetchone()
        assert not conn.execute("SELECT 1 FROM pipeline_outputs o JOIN pipeline_jobs j USING(job_id) "
            "WHERE json_extract(j.payload_json,'$.planning_intent.stage')='SIMPLE_EXECUTION'").fetchone()


class FixtureEngine:
    """Replace only the process/engine port; consume the physically staged files."""
    executed = []
    cleanup = True
    cancel_after = False
    def __init__(self, policy, *args, **kwargs):
        self.policy = policy

    def run(self, workspace, *, job_id, attempt_id, cancel_event, source_modes=None, **kwargs):
        files = read_workspace(workspace)
        index = {p: dict(sha256=sha, size=len(files[p]), executable=(source_modes or {}).get(p) == '100755')
                 for p, sha in manifest(files).items()}
        cases = []
        path = 'tests/test_bound.py'
        scope = {'__file__': str(workspace / path)}
        exec(compile(files[path], str(workspace / path), 'exec'), scope)
        for name, function in sorted(scope.items()):
            if not name.startswith('test_requirement_'):
                continue
            case = dict(name=name, class_name='tests.test_bound', status='passed')
            try:
                function()
            except AssertionError as error:
                tb = error.__traceback__
                while tb.tb_next is not None:
                    tb = tb.tb_next
                case.update(status='failed', assertion_failure=dict(phase='call', exception_type='AssertionError',
                    path=path, source_sha256=manifest(files)[path], line=tb.tb_lineno))
            cases.append(case)
        failed = sum(case['status'] == 'failed' for case in cases)
        self.executed.append((job_id, manifest(files), failed))
        if self.cancel_after:
            cancel_event.set()
        return dict(kind='docker-test-execution', job_id=job_id, attempt_id=attempt_id,
            image_id=self.policy.image, policy_sha256=self.policy.digest,
            source=dict(files=index, sha256=digest(index)), source_verified=True,
            cleanup_verified=self.cleanup, passed=not failed,
            failure_category='tests_failed' if failed else None,
            commands=[dict(name='unit', exit_code=1 if failed else 0, junit_cases=cases,
                           junit=dict(tests=len(cases), failures=failed, errors=0))])


def verify_next(artifacts, store, monkeypatch, **engine_changes):
    engine = type('BoundFixtureEngine', (FixtureEngine,), dict(executed=[], **engine_changes))
    monkeypatch.setattr('cochem_pipeline.containers.DockerRunner', engine)
    node = store.claim('fixture', allowed_kinds=['TASK_TEST'], worker_slot='slot2', requires_cleanup=True)
    assert node is not None
    result = artifacts.run_verification(node, 'slot2', lambda: True, threading.Event(), container_reservation='fixture')
    return node, result, engine


def test_staging_red_then_green_to_durable_controller_completion(staged, monkeypatch):
    artifacts, runtime, producer, requirements, _ = staged
    store = runtime.store
    first = artifacts.ensure_verification(producer, requirements)
    assert artifacts.ensure_verification(producer, requirements) == first
    for phase in ('red', 'green'):
        node, (output, receipt, evidence), engine = verify_next(artifacts, store, monkeypatch)
        assert node['payload']['test_phase'] == phase
        assert output['passed'] is True
        assert bool(engine.executed[0][2]) == (phase == 'red')
        store.clear_execution_quarantine(node['job_id'], node['attempt_id'], node['fencing_token'])
        store.complete_task_verification(node['job_id'], node['attempt_id'], node['fencing_token'],
                                         output, receipt, evidence=evidence)
        checkpoint = artifacts.ensure_verification(producer, requirements)
    assert checkpoint['status'] == 'VERIFIED'
    assert checkpoint['integration_status'] == 'REVIEW_REQUIRED'
    with store._connection() as conn:
        assert conn.execute("SELECT count(*) FROM pipeline_jobs WHERE kind='TASK_TEST'").fetchone()[0] == 2
        assert conn.execute('SELECT count(*) FROM coding_attempt_evidence').fetchone()[0] == 2
    reopened = TaskArtifactRuntime(runtime)
    assert reopened.ensure_verification(producer, requirements) == checkpoint


def test_task_cancellation_fences_claim_and_preserves_cleanup_barrier(staged, monkeypatch):
    artifacts, runtime, producer, requirements, _ = staged
    first = artifacts.ensure_verification(producer, requirements)
    node, (output, receipt, evidence), _ = verify_next(artifacts, runtime.store, monkeypatch)
    artifacts.cancel_task('task')
    with pytest.raises(ValueError):
        runtime.store.complete_task_verification(node['job_id'], node['attempt_id'], node['fencing_token'],
                                                 output, receipt, evidence=evidence)
    with runtime.store._connection() as conn:
        assert conn.execute('SELECT cleared_at FROM pipeline_execution_cleanup WHERE job_id=?',
                            (node['job_id'],)).fetchone()[0] is None
        assert conn.execute('SELECT count(*) FROM coding_attempt_evidence').fetchone()[0] == 1
    assert runtime.store.get(first['job_id'])['status'] == 'FAILED'
    assert runtime.store.get(producer['job_id'])['status'] == 'COMPLETED'
    reopened = TaskArtifactRuntime(runtime)
    assert reopened.ensure_verification(producer, requirements)['status'] == 'TASK_VERIFICATION_CANCELLED'
    assert reopened.cancel_task('task')['status'] == 'TASK_VERIFICATION_CANCELLED'
    with runtime.store._connection() as conn:
        assert conn.execute("SELECT count(*) FROM pipeline_jobs WHERE kind='TASK_TEST'").fetchone()[0] == 1


def test_cancel_tombstone_precedes_fallible_workflow_cancellation(staged, monkeypatch):
    artifacts, runtime, producer, requirements, _ = staged
    first = artifacts.ensure_verification(producer, requirements)
    original = runtime.store.cancel_workflow
    monkeypatch.setattr(runtime.store, 'cancel_workflow', lambda *_: (_ for _ in ()).throw(OSError('interrupted')))
    with pytest.raises(OSError):
        artifacts.cancel_task('task')
    assert artifacts.ensure_verification(producer, requirements)['status'] == 'TASK_VERIFICATION_CANCELLED'
    monkeypatch.setattr(runtime.store, 'cancel_workflow', original)
    TaskArtifactRuntime(runtime).cancel_task('task')
    assert runtime.store.get(first['job_id'])['status'] == 'FAILED'
    with pytest.raises(sqlite3.IntegrityError, match='immutable'):
        with runtime.store._write() as conn:
            conn.execute('DELETE FROM task428_cancelled_tasks')


def test_cancel_before_first_verification_never_materializes_a_child(staged):
    artifacts, runtime, producer, requirements, _ = staged
    artifacts.cancel_task('task')
    assert artifacts.ensure_verification(producer, requirements)['status'] == 'TASK_VERIFICATION_CANCELLED'
    with runtime.store._connection() as conn:
        assert not conn.execute("SELECT 1 FROM pipeline_jobs WHERE kind IN ('TASK_VERIFY','TASK_TEST')").fetchone()


def outcome_runtime(simple_env, artifacts, tmp_path):
    from cochem_pipeline.attempt_runtime_428 import AttemptAccountingRuntime
    from cochem_pipeline.planning_outcomes_428 import PlanningOutcomeRuntime
    from cochem_pipeline.workflow_428 import AttemptLedger
    _, _, journal, store = simple_env
    accounting = AttemptAccountingRuntime(AttemptLedger(tmp_path / 'outcomes.db'), store=store)
    return PlanningOutcomeRuntime(journal, store, accounting, artifact_runtime=artifacts)


@pytest.mark.parametrize('staged', [0, 2], indirect=True)
def test_rejected_physical_check_charges_original_producer_once_with_restart_feedback(
        staged, simple_env, monkeypatch, tmp_path):
    artifacts, runtime, producer, requirements, _ = staged
    outcomes = outcome_runtime(simple_env, artifacts, tmp_path)
    # Planning completion is observable now; producer success must wait for its
    # controller-owned evidence even though the model supplied valid JSON.
    assert outcomes.reconcile_task('task') == 1
    assert artifacts.retry_feedback('task') is None
    with outcomes.accounting.ledger._write() as conn:
        assert not conn.execute('SELECT 1 FROM attempt428_outbox WHERE job_id=?', (producer['job_id'],)).fetchone()
    while True:
        node, (output, receipt, evidence), engine = verify_next(artifacts, runtime.store, monkeypatch)
        runtime.store.clear_execution_quarantine(node['job_id'], node['attempt_id'], node['fencing_token'])
        runtime.store.complete_task_verification(node['job_id'], node['attempt_id'], node['fencing_token'],
                                                 output, receipt, evidence=evidence)
        if output['status'] == 'REJECTED':
            break
        assert outcomes.reconcile_task('task') == 0
    proof = artifacts.verification_outcome(producer)
    assert proof['status'] == 'REJECTED'
    assert proof['producer_job_id'] == producer['job_id']
    assert proof['producer_attempt_id'] == producer['attempt_id']
    assert proof['verification_job_id'] == node['job_id']
    assert outcomes.reconcile_task('task') == 1
    assert outcomes.reconcile_task('task') == 0
    assert outcomes.accounting.ledger.status('task')['failures'] == 1
    with outcomes.accounting.ledger._write() as conn:
        rows = conn.execute('SELECT * FROM attempt428_outbox WHERE job_id=?', (producer['job_id'],)).fetchall()
        assert len(rows) == 1 and rows[0]['staged_outcome'] == 'quality_failure'
        assert rows[0]['attempt_id'] == producer['attempt_id']
    feedback = artifacts.retry_feedback('task')
    assert feedback['retry_generation'] == 1
    assert feedback['lineage_root'] == 'task'
    assert feedback['producer_job_id'] == producer['job_id']
    assert feedback['verification_job_id'] == node['job_id']
    assert feedback['failure']['reason'] in ('BASELINE_ASSERTION_NOT_PROVEN', 'REQUIREMENT_TESTS_NOT_PASSED')
    assert feedback['failure']['evidence_sha256'] == digest(evidence)
    assert TaskArtifactRuntime(runtime).retry_feedback('task') == feedback
    assert outcome_runtime(simple_env, artifacts, tmp_path).reconcile_task('task') == 0
    assert artifacts.retry_feedback('task', 'unrelated-microtask') is None
    # An identical duplicate controller observation cannot invent a second
    # model attempt or a new generation.
    with runtime.store._write() as conn:
        runtime.store._insert(conn, 'duplicate-root', 'duplicate-root', None, 'MACRO_PLANNING_REQUEST',
            'IN_PROGRESS', {'workflow_type': 'task_verification428', 'task_id': 'task'})
        runtime.store._insert(conn, 'duplicate-check', 'duplicate-root', 'duplicate-root', 'TASK_TEST',
                              'PENDING', node['payload'])
    duplicate, (dup_output, dup_receipt, dup_evidence), _ = verify_next(artifacts, runtime.store, monkeypatch)
    runtime.store.clear_execution_quarantine(duplicate['job_id'], duplicate['attempt_id'], duplicate['fencing_token'])
    runtime.store.complete_task_verification(duplicate['job_id'], duplicate['attempt_id'], duplicate['fencing_token'],
                                             dup_output, dup_receipt, evidence=dup_evidence)
    assert artifacts.retry_feedback('task') == feedback


def test_verified_physical_checks_commit_only_one_original_success(staged, simple_env, monkeypatch, tmp_path):
    artifacts, runtime, producer, requirements, _ = staged
    outcomes = outcome_runtime(simple_env, artifacts, tmp_path)
    assert outcomes.reconcile_task('task') == 1
    for phase in ('red', 'green'):
        node, (output, receipt, evidence), _ = verify_next(artifacts, runtime.store, monkeypatch)
        runtime.store.clear_execution_quarantine(node['job_id'], node['attempt_id'], node['fencing_token'])
        runtime.store.complete_task_verification(node['job_id'], node['attempt_id'], node['fencing_token'],
                                                 output, receipt, evidence=evidence)
        assert outcomes.reconcile_task('task') == (0 if phase == 'red' else 1)
    assert outcomes.reconcile_task('task') == 0
    with outcomes.accounting.ledger._write() as conn:
        rows = conn.execute('SELECT * FROM attempt428_outbox WHERE job_id=?', (producer['job_id'],)).fetchall()
        assert len(rows) == 1 and rows[0]['staged_outcome'] == 'success'
    assert artifacts.retry_feedback('task') is None


@pytest.mark.parametrize('staged', ['content'], indirect=True)
def test_low_tier_content_keeps_owner_single_model_integrity_only_scope(staged):
    artifacts, runtime, producer, requirements, _ = staged
    artifacts.ensure_verification(producer, requirements)
    node = runtime.store.claim('fixture', allowed_kinds=['TASK_VERIFY'], worker_slot='slot2', requires_cleanup=True)
    output, receipt, evidence = artifacts.run_verification(node, 'slot2', lambda: True, threading.Event())
    runtime.store.clear_execution_quarantine(node['job_id'], node['attempt_id'], node['fencing_token'])
    runtime.store.complete_task_verification(node['job_id'], node['attempt_id'], node['fencing_token'],
                                             output, receipt, evidence=evidence)
    proof = artifacts.verification_outcome(producer)
    assert proof['status'] == 'VERIFIED'
    assert proof['verification_scope'] == 'content_integrity'
    assert 'content_review' not in proof
    assert output['verified_requirements'] == []


def test_cancelled_verification_never_becomes_a_quality_failure(staged, simple_env, tmp_path):
    artifacts, runtime, producer, requirements, _ = staged
    outcomes = outcome_runtime(simple_env, artifacts, tmp_path)
    assert outcomes.reconcile_task('task') == 1
    artifacts.cancel_task('task')
    assert outcomes.reconcile_task('task') == 1
    with outcomes.accounting.ledger._write() as conn:
        assert not conn.execute('SELECT 1 FROM attempt428_outbox WHERE job_id=?', (producer['job_id'],)).fetchone()
    assert artifacts.retry_feedback('task') is None


@pytest.mark.parametrize('cancel,cleanup', [(True, True), (False, False)])
def test_late_cancel_or_failed_cleanup_preserves_physical_attempt_without_acceptance(staged, monkeypatch, cancel, cleanup):
    from cochem_pipeline.worker import ExecutionRevokedError, WorkerCleanupError
    artifacts, runtime, producer, requirements, _ = staged
    artifacts.ensure_verification(producer, requirements)
    with pytest.raises(ExecutionRevokedError if cancel else WorkerCleanupError):
        verify_next(artifacts, runtime.store, monkeypatch, cancel_after=cancel, cleanup=cleanup)
    with runtime.store._connection() as conn:
        assert conn.execute('SELECT count(*) FROM coding_attempt_evidence').fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM pipeline_outputs o JOIN pipeline_jobs j USING(job_id) WHERE j.kind='TASK_TEST'").fetchone()[0] == 0


@pytest.mark.parametrize('table', ['task428_source_captures', 'task428_fragment_attempts'])
def test_source_and_staged_attempt_captures_are_immutable(staged, table):
    artifacts, runtime, producer, requirements, _ = staged
    with pytest.raises(sqlite3.IntegrityError, match='immutable'):
        with runtime.store._write() as conn:
            conn.execute('DELETE FROM ' + table)


def test_caller_cannot_rebind_a_verified_producer_snapshot_to_another_intent(staged):
    artifacts, runtime, producer, requirements, _ = staged
    expected = artifacts.ensure_verification(producer, requirements)
    rewritten = deepcopy(producer)
    rewritten['payload']['planning_intent']['task_id'] = 'different-task'
    rewritten['output']['artifact_text'] = 'Different proposal'
    assert artifacts.ensure_verification(rewritten, requirements) == expected


@pytest.mark.parametrize('mode', ['missing', 'extra'])
def test_verification_scope_must_match_the_immutable_producer_requirements(staged, mode):
    artifacts, runtime, producer, requirements, _ = staged
    changed = requirements[:-1] if mode == 'missing' else [*requirements, 'unassigned-requirement']
    with pytest.raises(ValueError, match='requirement'):
        artifacts.ensure_verification(producer, changed)
    with runtime.store._connection() as conn:
        assert not conn.execute("SELECT 1 FROM pipeline_jobs WHERE kind='TASK_TEST'").fetchone()


@pytest.mark.parametrize('changed', ['extra_predecessor', 'missing_predecessor', 'wrong_hash'])
def test_unassigned_or_rewritten_dependencies_never_enter_workspace(staged, changed):
    artifacts, runtime, producer, requirements, _ = staged
    downstream = deepcopy(producer)
    intent = downstream['payload']['planning_intent']
    intent.update(stage='MICROTASK_EXECUTION', plan_generation_sha256='a' * 64,
                  predecessor_artifact_hashes={'first': 'b' * 64})
    downstream['payload'].update(microtask_node=dict(depends_on=['first']),
        predecessor_outputs={'first': {'artifact_sha256': 'b' * 64}},
        predecessor_artifact_hashes={'first': 'b' * 64})
    if changed == 'extra_predecessor':
        downstream['payload']['predecessor_outputs']['unassigned'] = {'artifact_sha256': 'c' * 64}
    elif changed == 'missing_predecessor':
        downstream['payload']['predecessor_outputs'] = {}
    else:
        downstream['payload']['predecessor_outputs']['first']['artifact_sha256'] = 'c' * 64
    with pytest.raises(ValueError, match='assigned predecessor'):
        artifacts._inputs(downstream)


@pytest.mark.parametrize('failure', ['capacity', 'cleanup'])
def test_engine_exception_keeps_the_existing_resource_and_cleanup_classifications(staged, monkeypatch, failure):
    from cochem_pipeline.containers import ContainerCapacityError, ContainerCleanupError
    from cochem_pipeline.worker import ProviderFailure, WorkerCleanupError
    artifacts, runtime, producer, requirements, _ = staged
    artifacts.ensure_verification(producer, requirements)
    class FailedEngine(FixtureEngine):
        def run(self, *args, **kwargs):
            raise (ContainerCapacityError if failure == 'capacity' else ContainerCleanupError)('fixture')
    monkeypatch.setattr('cochem_pipeline.containers.DockerRunner', FailedEngine)
    node = runtime.store.claim('fixture', allowed_kinds=['TASK_TEST'], worker_slot='slot2', requires_cleanup=True)
    with pytest.raises(ProviderFailure if failure == 'capacity' else WorkerCleanupError) as raised:
        artifacts.run_verification(node, 'slot2', lambda: True, threading.Event())
    if failure == 'capacity':
        assert raised.value.category == 'resource'
