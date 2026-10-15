"""Shared verification seats/pool bookkeeping; no Docker or native execution."""
import pytest

from cochem_pipeline.admission import JointAdmission, _NATIVE_KINDS
from cochem_pipeline.containers import DockerRunner
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline import routing_store
from cochem_pipeline.store import JobStore
from pipeline_tests.test_containers import policy, prepared_metadata


@pytest.fixture(autouse=True)
def prohibit_engine_execution(monkeypatch):
    from cochem_pipeline import containers
    def forbidden(*args, **kwargs):
        raise AssertionError('This suite must not start any engine/provider command')
    monkeypatch.setattr(containers.subprocess, 'Popen', forbidden)


def stage(store, kind, identifier, docker=None, mode=None):
    payload = dict(mode=mode or ('coding_tests' if kind == 'TASK_TEST' else 'artifact_integrity'),
                   verification_key='a' * 64, source_snapshot_sha256='b' * 64)
    if docker is not None:
        payload['docker'] = docker.as_dict()
    with store._write() as conn:
        store._insert(conn, identifier, identifier, None, 'MACRO_PLANNING_REQUEST', 'IN_PROGRESS', {})
        routing_store.capture_workflow(conn, identifier, store.routing_policy)
        store._insert(conn, identifier+'-verify', identifier, identifier, kind, 'PENDING', payload)
        routing_store.ensure_job(conn, identifier+'-verify')
    return identifier+'-verify'


@pytest.fixture
def store(tmp_path):
    board = JobStore(tmp_path/'board.db', routing_policy=load_routing_policy({'policy_version': 3}))
    yield board
    board.close()


@pytest.mark.parametrize('kind', ['TASK_VERIFY', 'TASK_DELIVER'])
def test_artifact_integrity_uses_four_shared_seats_without_docker_or_model_route(store, kind):
    admission = JointAdmission(store, None, capacity=4)
    for index in range(5):
        stage(store, kind, f'artifact-{index}')
    results = [admission.claim('owner', worker_slot=f'slot{i}') for i in range(1, 6)]
    assert all(result is not None for result in results[:4])
    assert results[-1] is None
    assert admission._native_active() == 4
    assert 'TASK_VERIFY' in _NATIVE_KINDS and 'TASK_TEST' not in _NATIVE_KINDS
    for node, reservation in results[:4]:
        assert node['kind'] == kind and reservation is None
        assert node.get('route') is None and node.get('routing') is None
        with store._write() as conn:
            preview = routing_store.preview_next_route(conn, node)
            assert preview['state'] == 'not_model_job'
    assert store.execution_quarantines() == []


def test_coding_verification_cannot_claim_without_docker(store):
    identifier = stage(store, 'TASK_TEST', 'code', policy())
    admission = JointAdmission(store, None, capacity=4)
    assert admission.claim('owner', worker_slot='slot1') is None
    assert store.get(identifier)['status'] == 'PENDING'


def test_coding_verification_transfers_exact_warm_profile_and_counts_once(store, tmp_path):
    docker = DockerRunner(policy(), tmp_path/'containers')
    admission = JointAdmission(store, docker, capacity=4)
    warm = prepared_metadata(docker)
    identifier = stage(store, 'TASK_TEST', 'code', docker.policy)
    node, reservation = admission.claim('owner', worker_slot='slot1')
    assert node['job_id'] == identifier and node['route'] is None
    assert reservation['lease'] == warm['lease']
    assert reservation['attempt_id'] == node['attempt_id']
    assert reservation['job_id'] == identifier
    assert docker.census()['owned'] == docker.census()['active'] == 1
    assert admission._native_active() == 0
    with store._write() as conn:
        assert routing_store.preview_next_route(conn, node)['state'] == 'not_model_job'


@pytest.mark.parametrize('kind,mode', [('TASK_TEST','artifact_integrity'), ('TASK_VERIFY','coding_tests')])
def test_kind_mode_mismatch_holds_before_any_executor_handoff(store, tmp_path, kind, mode):
    docker = DockerRunner(policy(), tmp_path/'containers')
    identifier = stage(store, kind, 'malformed', docker.policy, mode)
    admission = JointAdmission(store, docker, capacity=4)
    assert admission.claim('owner', worker_slot='slot1') is None
    assert store.get(identifier)['status'] == 'BLOCKED'
    assert docker.census()['owned'] == 0
    assert store.execution_quarantines() == []


def test_captured_task_docker_bounds_and_incompatible_warm_profiles_fail_closed(store, tmp_path):
    captured = policy()
    smaller = policy(memory_mb=2048, tmpfs_mb=1024)
    docker = DockerRunner(smaller, tmp_path/'containers')
    identifier = stage(store, 'TASK_TEST', 'bounds', captured)
    admission = JointAdmission(store, docker, capacity=4)
    assert admission.claim('owner', worker_slot='slot1') is None
    assert store.get(identifier)['status'] == 'BLOCKED'
    assert docker.census()['owned'] == 0


def test_pending_task_test_joins_preparation_fifo_without_starting_engine(store, tmp_path):
    docker = DockerRunner(policy(), tmp_path/'containers')
    identifier = stage(store, 'TASK_TEST', 'pending', docker.policy)
    admission = JointAdmission(store, docker, capacity=4)
    assert admission.claim('owner', worker_slot='slot1') is None
    assert store.get(identifier)['status'] == 'PENDING_RETRY'
    assert docker.preparation_requests()[0]['job_id'] == identifier
    assert docker.census()['owned'] == 0
    assert store.execution_quarantines() == []


def test_maintenance_preserves_task_test_active_attempt_for_reaping(store, tmp_path, monkeypatch):
    docker = DockerRunner(policy(), tmp_path/'containers')
    admission = JointAdmission(store, docker, capacity=4)
    prepared_metadata(docker)
    stage(store, 'TASK_TEST', 'code', docker.policy)
    node, _ = admission.claim('owner', worker_slot='slot1')
    seen = []
    monkeypatch.setattr(docker, 'reap_orphans', lambda **kw: seen.append(kw['active_attempt_ids']()))
    monkeypatch.setattr(docker, 'prepare_pool', lambda **kw: {'census':docker.census()})
    admission.maintenance()
    assert seen == [{node['attempt_id']}]


def test_artifact_integrity_waits_for_drain_of_full_warm_pool(store, tmp_path):
    docker = DockerRunner(policy(), tmp_path/'containers')
    admission = JointAdmission(store, docker, capacity=4)
    for _ in range(4):
        prepared_metadata(docker)
    identifier = stage(store, 'TASK_VERIFY', 'artifact')
    assert admission.claim('owner', worker_slot='slot1') is None
    assert store.get(identifier)['status'] == 'PENDING'
    assert admission._drain_target == 3


@pytest.mark.parametrize('kind', ['TASK_VERIFY', 'TASK_DELIVER'])
def test_mixed_task_tests_and_artifact_checks_share_the_same_four_seats(store, tmp_path, kind):
    docker = DockerRunner(policy(), tmp_path/'containers')
    admission = JointAdmission(store, docker, capacity=4)
    for index in range(3):
        prepared_metadata(docker)
        stage(store, 'TASK_TEST', f'code-{index}', docker.policy)
    stage(store, kind, 'artifact')
    stage(store, 'TASK_VERIFY', 'overflow')
    results = [admission.claim('owner', worker_slot=f'slot{i}') for i in range(1, 5)]
    assert all(result is not None for result in results)
    assert [node['kind'] for node, _ in results].count('TASK_TEST') == 3
    assert [node['kind'] for node, _ in results].count(kind) == 1
    assert admission._native_active() + docker.census()['owned'] == 4
    assert admission.claim('owner', worker_slot='slot5') is None
