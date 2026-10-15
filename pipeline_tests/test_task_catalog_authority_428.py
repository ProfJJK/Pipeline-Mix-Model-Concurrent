"""Protected-board authority regressions with temporary SQLite only."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from cochem_pipeline import routing_store as routes
from cochem_pipeline.catalog_journal import initialize
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.store import JobStore
from cochem_pipeline.task_catalog_428 import initialize_task_catalog_authority, task_catalog_authority
from cochem_pipeline.task_routing import digest
from cochem_pipeline.worker import NativeRunner
from pipeline_tests.task_catalog_fixtures import accepted_catalog_fixture, accepted_planning_store


ARGON = dict(provider='gemini', model='gemini-4-argon', reasoning_effort='high',
             key='gemini:gemini-4-argon:high', quota_pool='gemini')


@pytest.fixture
def board(tmp_path):
    store, catalog = accepted_planning_store(tmp_path / 'jobs.db')
    runner = NativeRunner(SimpleNamespace(routing=load_routing_policy(store.routing_policy),
                                         catalog_activation=True, job_db=store.path))
    job = dict(kind='TASK_PLAN', job_id='captured-task', created_at=1,
               payload={'task_catalog': catalog})
    yield store, catalog, runner, job
    store.close()


def availability(store, job, target=ARGON):
    state = dict(policy=store.routing_policy, score_details={})
    with store._write() as conn:
        return routes._candidate_unavailability(conn, job, state, target,
                                                store._current_routing_policy(conn), 100.)


def test_v3_accepted_new_target_admitted_by_scheduler_and_native_dispatch(board):
    store, catalog, runner, job = board
    assert not runner.config.routing.is_enabled(ARGON)
    assert availability(store, job) is None
    assert runner._is_route_target_enabled(job, ARGON)
    with store._write() as conn:
        assert task_catalog_authority(conn, job) == catalog


@pytest.mark.parametrize('mutation', ['publisher', 'flag', 'limits', 'generation', 'missing'])
def test_payload_cannot_forge_host_acceptance_or_replace_protected_capture(board, mutation):
    store, catalog, runner, job = board
    altered = deepcopy(catalog)
    if mutation == 'publisher':
        altered['host_accepted'] = False
    elif mutation == 'flag':
        altered['host_accepted'] = True
        altered['accepted_targets'].append(dict(provider='codex', model='invented-model', reasoning_effort='max'))
    elif mutation == 'limits':
        altered['model_limits'][ARGON['key']] = 100
    elif mutation == 'generation':
        altered['generation'] += '-forged'
    else:
        altered = None
    job['payload']['task_catalog'] = altered
    assert availability(store, job) == 'task_catalog_unverified'
    assert not runner._is_route_target_enabled(job, ARGON)


def test_missing_active_authority_never_falls_back_to_capture_or_legacy_tiers(board):
    store, catalog, runner, job = board
    with store._write() as conn:
        conn.execute('DELETE FROM pipeline_task_catalog_active')
    assert availability(store, job) == 'task_catalog_unverified'
    assert not runner._is_route_target_enabled(job, ARGON)
    legacy = runner.config.routing.candidates(1, 'CHAPTER_DRAFT')[0]
    assert not runner._is_route_target_enabled(job, legacy)
    assert runner._is_route_target_enabled({'kind': 'CHAPTER_DRAFT'}, legacy)


def test_old_accepted_capture_survives_new_generation_but_retirement_takes_effect(board):
    store, catalog, runner, job = board
    original = deepcopy(job)
    later = deepcopy(catalog)
    later['generation'] += '-next'
    later['retired_targets'].append(dict(provider='gemini', model='gemini-4-argon', reasoning_effort='high'))
    # This fixture simulates the already verified atomic owner publication.
    # Production generation writes are confined to catalog_journal publication.
    with store._write() as conn:
        row = conn.execute('SELECT * FROM pipeline_task_catalog_generations').fetchone()
        columns = [item[1] for item in conn.execute('PRAGMA table_info(pipeline_task_catalog_generations)')]
        values = dict(zip(columns, row))
        import json
        values.update(catalog_sha256=digest(later), generation=later['generation'],
                      catalog_json=json.dumps(later), request_id='d' * 32,
                      previous_catalog_sha256=digest(catalog))
        conn.execute('INSERT INTO pipeline_task_catalog_generations VALUES('+','.join('?' for _ in columns)+')',
                     [values[key] for key in columns])
        conn.execute('UPDATE pipeline_task_catalog_active SET catalog_sha256=?', (digest(later),))
        assert task_catalog_authority(conn, job) == later
    assert availability(store, job) == 'retired_target'
    assert not runner._is_route_target_enabled(job, ARGON)
    sonnet = dict(provider='claude', model='claude-sonnet-5-5', reasoning_effort='max',
                  key='claude:claude-sonnet-5-5:max', quota_pool='claude')
    assert availability(store, job, sonnet) is None
    assert runner._is_route_target_enabled(job, sonnet)
    assert job == original
    config = SimpleNamespace(read_catalog=lambda: deepcopy(catalog))
    assert initialize_task_catalog_authority(store, config) == later


def test_catalog_init_reads_protected_config_and_refuses_unrelated_baseline(board):
    store, catalog, runner, job = board
    calls = []
    config = SimpleNamespace(read_catalog=lambda: calls.append(True) or deepcopy(catalog))
    assert initialize_task_catalog_authority(store, config) == catalog
    assert calls == [True]
    altered = deepcopy(catalog)
    altered['generation'] += '-unrelated'
    with pytest.raises(ValueError, match='absent from task catalog history'):
        initialize_task_catalog_authority(store, SimpleNamespace(read_catalog=lambda: altered))
    store._catalog_enabled = False
    with pytest.raises(ValueError, match='journal activation'):
        initialize_task_catalog_authority(store, config)
    assert len(calls) == 1


def test_acceptance_checks_require_coherent_transaction(board):
    store, catalog, runner, job = board
    with store._connection() as conn:
        with pytest.raises(ValueError, match='caller transaction'):
            task_catalog_authority(conn, job)


def test_worker_read_does_not_create_missing_board(tmp_path):
    path = tmp_path / 'never-created.db'
    runner = NativeRunner(SimpleNamespace(routing=load_routing_policy({'policy_version': 3}),
                                         catalog_activation=True, job_db=path))
    assert not runner._is_route_target_enabled(dict(kind='TASK_PLAN', payload={}), ARGON)
    assert not path.exists()


def test_first_runtime_adoption_uses_exact_protected_catalog(tmp_path):
    policy = load_routing_policy({'policy_version': 3})
    path = tmp_path / 'board.db'
    store = JobStore(path, routing_policy=policy)
    with store._connection() as conn:
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('BEGIN IMMEDIATE')
        initialize(conn, policy)
        conn.commit()
    store.close()
    store = JobStore(path, routing_policy=policy, catalog_enabled=True)
    try:
        catalog = accepted_catalog_fixture(policy)
        spec = SimpleNamespace(read_catalog=lambda: deepcopy(catalog))
        assert initialize_task_catalog_authority(store, spec) == catalog
        job = dict(kind='TASK_PLAN', payload={'task_catalog': catalog})
        with store._write() as conn:
            assert task_catalog_authority(conn, job) == catalog
        assert initialize_task_catalog_authority(store, spec) == catalog
    finally:
        store.close()
