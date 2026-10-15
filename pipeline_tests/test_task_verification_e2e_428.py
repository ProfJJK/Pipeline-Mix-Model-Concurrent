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


@pytest.fixture
def staged(simple_env, tmp_path, monkeypatch):
    controller, _, journal, store = simple_env
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
    artifacts.prepare_task('task', 'fixture-project')
    document = _advance_to_ready(controller, 'task', tier=2)
    controller.test_clock[0] += 2; controller.step()
    node = store.claim('fixture', allowed_kinds=['TASK_PLAN'], worker_slot='slot1', requires_cleanup=True)
    names = requirement_test_names([item['id'] for item in document['requirements']])
    source = 'from pathlib import Path\n' + ''.join(
        f'def {name}():\n    assert (Path(__file__).parents[1] / "src/value.py").read_text() == "value = 1\\n"\n'
        for name in names.values())
    files = {'src/value.py': 'value = 1\n', 'tests/test_bound.py': source}
    output = dict(artifact_text='Concrete proposal',
        deliverables=[dict(name=p, content=text, sha256=hashlib.sha256(text.encode()).hexdigest())
                      for p, text in files.items()],
        requirement_evidence=[dict(requirement_id=key, deliverable_name='src/value.py',
                                   verification_evidence='Bound regression proposed') for key in names],
        release_criteria_results=[dict(criterion=c, passed=True, evidence='Proposal is ready for physical verification')
                                  for c in document['release_criteria']])
    runtime.runner = SimpleNamespace(run=lambda *a, **k: (deepcopy(output), accepted_receipt(node, output)))
    result, receipt = artifacts.run(node, 'slot1', '', lambda: True, lambda _: None, threading.Event(),
                                   on_native_start=lambda _: None, on_native_end=lambda: None)
    store.clear_execution_quarantine(node['job_id'], node['attempt_id'], node['fencing_token'])
    store.complete(node['job_id'], node['attempt_id'], node['fencing_token'], result, receipt)
    return artifacts, runtime, store.get(node['job_id']), sorted(names), spaces


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
