"""Fenced delivery with real SQLite/files and an inert Git plumbing port.

These tests exercise the full verified producer chain; no Git process, container,
provider, or owner repository mutation occurs.
"""
from copy import deepcopy
from contextlib import contextmanager
import hashlib
from pathlib import Path
import threading

import pytest

from cochem_pipeline.coding import digest
from cochem_pipeline.task_artifact_delivery_428 import TaskArtifactDeliveryRuntime
from pipeline_tests.test_task_execution_428 import simple_env
from pipeline_tests.test_task_verification_e2e_428 import _stage_proposal, verify_next


class InertGit:
    integrations = []
    stages = []
    private_ref = None
    crash_after_cas = False
    cas_count = 0

    def __init__(self, root, **kwargs):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def stage(self, baseline, files, *, workflow_id, chunk_id, **kwargs):
        self.stages.append((baseline, deepcopy(files)))
        repository = self.root / workflow_id
        repository.mkdir(exist_ok=True)
        patch = repository / 'verified.patch'
        data = b'inert binary patch fixture\n' + digest({p: hashlib.sha256(b).hexdigest() for p, b in files.items()}).encode()
        if not patch.exists():
            patch.write_bytes(data)
        return dict(status='STAGED', baseline_commit=baseline.commit, parent_commit=baseline.commit,
            result_commit='c' * 40, tree='d' * 40, snapshot_sha256=digest({'fixture': True}),
            staging_repository=str(repository), patch_path=str(patch), patch_sha256=hashlib.sha256(data).hexdigest(),
            workflow_id=workflow_id, chunk_id=chunk_id, repository=baseline.repository, branch=baseline.branch)

    def integrate(self, baseline, staged, *, auto_integrate, cas_guard):
        cls = type(self)
        cls.integrations.append((baseline.repository, auto_integrate))
        if cls.private_ref == staged['result_commit']:
            with cas_guard():
                return dict(staged, status='INTEGRATED', reason='already_integrated')
        if not auto_integrate:
            return dict(staged, status='READY_TO_INTEGRATE', reason='operator_review')
        with cas_guard():
            cls.private_ref = staged['result_commit']
            cls.cas_count += 1
            if cls.crash_after_cas:
                cls.crash_after_cas = False
                raise RuntimeError('interrupted after private CAS')
        return dict(staged, status='INTEGRATED', reason='cas')


class RegistryPort:
    def __init__(self, project, original):
        self.project, self.original = project, original
        self.checks = 0
        self.fail_at = None

    def delivery_provenance(self, project_id):
        assert project_id == self.project.project_id
        return dict(prepared_project=self.project.as_dict(),
                    preparation=dict(source_repository=str(self.original)))

    def verify_delivery_source(self, project_id):
        self.checks += 1
        if self.fail_at == self.checks:
            raise ValueError('source changed')
        return dict(status='SOURCE_CAPTURE_MATCHES')


@pytest.fixture
def verified(simple_env, tmp_path, monkeypatch):
    artifacts, runtime, producer, requirements, _ = _stage_proposal(
        simple_env, tmp_path, monkeypatch, auto_integrate=True)
    artifacts.ensure_verification(producer, requirements)
    for _ in ('red', 'green'):
        node, (output, receipt, evidence), _ = verify_next(artifacts, runtime.store, monkeypatch)
        runtime.store.clear_execution_quarantine(node['job_id'], node['attempt_id'], node['fencing_token'])
        runtime.store.complete_task_verification(node['job_id'], node['attempt_id'], node['fencing_token'],
                                                 output, receipt, evidence=evidence)
        artifacts.ensure_verification(producer, requirements)
    runtime.task_artifacts = artifacts
    port = type('PrivateInertGit', (InertGit,), dict(integrations=[], stages=[], private_ref=None,
                                                    crash_after_cas=False, cas_count=0))
    monkeypatch.setattr('cochem_pipeline.coding_git.GitStager', port)
    delivery = TaskArtifactDeliveryRuntime(runtime)
    original = tmp_path / 'owner-original'
    original.mkdir()
    (original / 'owned.txt').write_bytes(b'preserve this unrelated work\n')
    return delivery, runtime, producer, port, original


def claim(delivery, runtime, producer):
    pending = delivery.enqueue(producer['job_id'])
    node = runtime.store.claim('delivery-worker', allowed_kinds=['TASK_DELIVER'], worker_slot='slot3', requires_cleanup=True)
    assert node is not None and pending['job_id'] == node['job_id']
    return node


def publish(delivery, runtime, node, result):
    runtime.store.clear_execution_quarantine(node['job_id'], node['attempt_id'], node['fencing_token'])
    return delivery.complete(node, *result)


def test_static_project_auto_flag_cannot_write_registered_repository(verified):
    delivery, runtime, producer, git, original = verified
    node = claim(delivery, runtime, producer)
    result = delivery.run(node, lambda: True, threading.Event())
    assert result[0]['status'] == 'EXPORTED_FOR_REVIEW'
    assert result[0]['integration_policy'] == 'EXPORT_FOR_REVIEW'
    assert git.integrations == []
    assert Path(result[0]['patch_path']).is_file()
    assert (original / 'owned.txt').read_bytes() == b'preserve this unrelated work\n'
    output = publish(delivery, runtime, node, result)
    assert runtime.store.get(node['workflow_id'])['status'] == 'COMPLETED'
    assert TaskArtifactDeliveryRuntime(runtime).enqueue(producer['job_id']) == output
    with runtime.store._connection() as conn:
        assert conn.execute('SELECT count(*) FROM task428_delivery_results').fetchone()[0] == 1


def test_simple_task_waits_for_export_before_reporting_completion(verified, simple_env):
    delivery, runtime, producer, git, original = verified
    execution = simple_env[1]
    execution.delivery_runtime = delivery
    pending = execution.step_ready_task('task')
    assert pending['status'] == 'WAITING_FOR_TASK_DELIVERY'
    assert simple_env[2].status('task')['stage'] == 'READY'
    assert execution.get_artifact('task') is None
    node = claim(delivery, runtime, producer)
    result = delivery.run(node, lambda: True, threading.Event())
    publish(delivery, runtime, node, result)
    assert execution.step_ready_task('task')['status'] == 'EXECUTION_COMPLETED'
    artifact = execution.get_artifact('task')
    assert artifact['delivery']['patch_sha256'] == result[0]['patch_sha256']
    assert artifact['delivery']['status'] == 'EXPORTED_FOR_REVIEW'
    assert artifact['delivery']['original_checkout_modified'] is False


def test_cancellation_fences_pending_delivery_workflow(verified):
    delivery, runtime, producer, _, _ = verified
    pending = delivery.enqueue(producer['job_id'])
    runtime.task_artifacts.cancel_task('task')
    job = runtime.store.get(pending['job_id'])
    assert job['status'] == 'FAILED'
    assert runtime.store.claim('inert', allowed_kinds=['TASK_DELIVER'], worker_slot='slot2') is None
    assert delivery.enqueue(producer['job_id'])['status'] == 'TASK_DELIVERY_CANCELLED'


def use_private_registry(runtime, original):
    registry = RegistryPort(runtime.coding.projects()['fixture-project'], original)
    runtime.coding.registry = registry
    return registry


def test_auto_integration_requires_proven_prepared_repository_and_two_source_checks(verified):
    delivery, runtime, producer, git, original = verified
    registry = use_private_registry(runtime, original)
    node = claim(delivery, runtime, producer)
    result = delivery.run(node, lambda: True, threading.Event())
    assert result[0]['status'] == 'INTEGRATED_ISOLATED_REPOSITORY'
    assert result[0]['original_repository_integration'] == 'NOT_ATTEMPTED'
    assert registry.checks == 2 and git.cas_count == 1
    assert git.integrations[0][0] != str(original)
    assert (original / 'owned.txt').read_bytes() == b'preserve this unrelated work\n'
    publish(delivery, runtime, node, result)


@pytest.mark.parametrize('fail_at', [1, 2])
def test_source_changed_keeps_review_export_without_cas(verified, fail_at):
    delivery, runtime, producer, git, original = verified
    registry = use_private_registry(runtime, original)
    registry.fail_at = fail_at
    node = claim(delivery, runtime, producer)
    result = delivery.run(node, lambda: True, threading.Event())
    assert result[0]['status'] == 'EXPORTED_FOR_REVIEW'
    assert result[0]['source_check']['status'] == 'SOURCE_CHANGED_OR_UNVERIFIED'
    assert git.private_ref is None and git.cas_count == 0
    publish(delivery, runtime, node, result)


def test_interrupted_private_cas_reconciles_same_immutable_patch_without_second_write(verified):
    delivery, runtime, producer, git, original = verified
    registry = use_private_registry(runtime, original)
    node = claim(delivery, runtime, producer)
    git.crash_after_cas = True
    with pytest.raises(RuntimeError, match='interrupted'):
        delivery.run(node, lambda: True, threading.Event())
    assert git.cas_count == 1
    # The original may change after the already completed private CAS. Recovery
    # acknowledges that exact existing ref but must not perform another write.
    registry.fail_at = registry.checks + 1
    result = TaskArtifactDeliveryRuntime(runtime).run(node, lambda: True, threading.Event())
    assert result[0]['status'] == 'INTEGRATED_ISOLATED_REPOSITORY'
    assert git.cas_count == 1 and git.integrations[-1][1] is False
    publish(delivery, runtime, node, result)


def test_completion_requires_cleanup_and_exact_persisted_controller_evidence(verified):
    delivery, runtime, producer, _, _ = verified
    node = claim(delivery, runtime, producer)
    result = delivery.run(node, lambda: True, threading.Event())
    with pytest.raises(ValueError, match='cleanup'):
        delivery.complete(node, *result)
    runtime.store.clear_execution_quarantine(node['job_id'], node['attempt_id'], node['fencing_token'])
    forged = deepcopy(result)
    forged[2]['cleanup_verified'] = False
    with pytest.raises(ValueError, match='receipt'):
        delivery.complete(node, *forged)
    publish(delivery, runtime, node, result)


@pytest.mark.parametrize('mutation', ['stale', 'cancelled', 'patch'])
def test_stale_cancelled_or_tampered_delivery_cannot_publish(verified, mutation):
    delivery, runtime, producer, _, _ = verified
    node = claim(delivery, runtime, producer)
    result = delivery.run(node, lambda: True, threading.Event())
    runtime.store.clear_execution_quarantine(node['job_id'], node['attempt_id'], node['fencing_token'])
    if mutation == 'stale':
        node = dict(node, fencing_token=node['fencing_token'] + 1)
    elif mutation == 'cancelled':
        runtime.task_artifacts.cancel_task('task')
    else:
        Path(result[0]['patch_path']).write_bytes(b'changed patch')
    with pytest.raises(ValueError):
        delivery.complete(node, *result)
    with runtime.store._connection() as conn:
        assert not conn.execute('SELECT 1 FROM task428_delivery_results').fetchone()
    assert Path(result[0]['patch_path']).exists()


def test_verified_bool_cannot_replace_committed_red_green_proof(simple_env, tmp_path, monkeypatch):
    artifacts, runtime, producer, _, _ = _stage_proposal(simple_env, tmp_path, monkeypatch)
    runtime.task_artifacts = artifacts
    with pytest.raises(ValueError, match='RED/GREEN'):
        TaskArtifactDeliveryRuntime(runtime).enqueue(producer['job_id'])


def test_content_deliverable_never_queues_git_delivery(simple_env, tmp_path, monkeypatch):
    artifacts, runtime, producer, _, _ = _stage_proposal(simple_env, tmp_path, monkeypatch, 'content')
    runtime.task_artifacts = artifacts
    assert TaskArtifactDeliveryRuntime(runtime).enqueue(producer['job_id'])['status'] == 'NOT_APPLICABLE'
    with runtime.store._connection() as conn:
        assert not conn.execute("SELECT 1 FROM pipeline_jobs WHERE kind='TASK_DELIVER'").fetchone()


@pytest.mark.parametrize('condition,expected', [('clear', 'INTEGRATED'),
    ('branch_changed', 'READY_TO_INTEGRATE'), ('checked_out', 'READY_TO_INTEGRATE')])
def test_actual_stager_keeps_cas_scope_and_concurrency_checks_with_inert_git_port(tmp_path, monkeypatch, condition, expected):
    from cochem_pipeline import coding_git as git
    repository = tmp_path / 'private-prepared'
    repository.mkdir()
    files = {'src/a.py': b'a = 1\n'}
    modes = {'src/a.py': '100644'}
    blobs = {path: hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
             for path, content in files.items()}
    snapshot = git.RepositorySnapshot(str(repository), 'prepared-input', 'refs/heads/prepared-input',
        'a' * 40, files, modes, blobs, git.snapshot_digest(files, modes))
    monkeypatch.setattr(git, '_trusted_git_executable', lambda _: 'inert')
    monkeypatch.setattr(git, '_repository', lambda path: path)
    monkeypatch.setattr(git, '_metadata', lambda _: None)
    monkeypatch.setattr(git, '_copy_objects', lambda *args: None)
    monkeypatch.setattr(git, '_current_commit', lambda *args: 'e' * 40 if condition == 'branch_changed' else snapshot.commit)
    monkeypatch.setattr(git, '_checked_out', lambda *args: ['held-checkout'] if condition == 'checked_out' else [])
    stager = git.GitStager(tmp_path / 'staging', git_executable='inert')
    staging = stager._staging(snapshot, 'workflow')
    staging.mkdir()
    output_ref = 'refs/cochem/coding/' + hashlib.sha256(b'workflow').hexdigest() + '/' + hashlib.sha256(b'chunk').hexdigest()
    receipt = dict(staging_repository=str(staging), repository=str(repository), branch=snapshot.branch,
        baseline_commit=snapshot.commit, result_commit='c' * 40, tree='d' * 40,
        parent_commit=snapshot.commit, snapshot_sha256='f' * 64, max_changed_lines=None,
        workflow_id='workflow', chunk_id='chunk', output_ref=output_ref)
    calls = []
    def plumbing(repo, *args, **kwargs):
        calls.append((repo, args))
        if args == ('rev-parse', '--verify', output_ref):
            return b'c' * 40
        if args == ('rev-parse', 'c' * 40 + '^{tree}'):
            return b'd' * 40
        if args == ('rev-parse', 'c' * 40 + '^'):
            return b'a' * 40
        if args == ('cat-file', 'commit', 'c' * 40):
            return b'commit\nMax-Changed-Lines: unbounded\nSnapshot-SHA256: ' + b'f' * 64 + b'\n'
        if args == ('rev-parse', '--path-format=absolute', '--git-common-dir'):
            return str(repository).encode()
        if args[:1] == ('rev-list',):
            return b'c' * 40
        if args[:1] in [('check-ref-format',), ('merge-base',), ('update-ref',)]:
            return b''
        raise AssertionError((repo, args))
    monkeypatch.setattr(git, '_git', plumbing)
    monkeypatch.setattr(stager, '_verify_patch', lambda *args: None)
    guards = []
    @contextmanager
    def guard():
        guards.append(True)
        yield
    assert stager.integrate(snapshot, receipt, auto_integrate=True, cas_guard=guard)['status'] == expected
    branch_updates = [(repo, args) for repo, args in calls if args[:2] == ('update-ref', snapshot.ref)]
    assert len(branch_updates) == len(guards) == (condition == 'clear')
    if branch_updates:
        assert branch_updates[0] == (repository, ('update-ref', snapshot.ref, 'c' * 40, snapshot.commit))
