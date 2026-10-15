"""In-process SQLite/quality-ledger budgets; no native commands or children."""
from copy import deepcopy
import sqlite3

import pytest

from cochem_pipeline import routing_store as routes
from cochem_pipeline.attempt_runtime_428 import AttemptAccountingRuntime
from cochem_pipeline.planning_budgets_428 import (
    LineageBudgetHold, capture_lineage_budget, lineage_unavailability,
)
from cochem_pipeline.planning_gateway import scoped_policy
from cochem_pipeline.planning_outcomes_428 import PlanningOutcomeRuntime
from cochem_pipeline.task_routing import digest
from cochem_pipeline.workflow_428 import AttemptLedger
from pipeline_tests.test_planning_runtime_428 import pump, poll
from pipeline_tests.test_workflow_428 import research


@pytest.fixture
def env(pump, tmp_path, monkeypatch):
    clock = [1000.]
    monkeypatch.setattr(routes.time, 'time', lambda: clock[0])
    poll(pump)
    with pump.store._connection() as conn:
        row = conn.execute("SELECT job_id FROM pipeline_jobs WHERE kind='TASK_PLAN'").fetchone()
    original = pump.store.get(row[0])
    ledger = AttemptLedger(tmp_path/'budget-attempts.db')
    root = PlanningOutcomeRuntime.lineage_for_job('task', original['payload'])
    ledger.create(root, original['payload']['planning_intent']['complexity'])
    return dict(store=pump.store, original=original, ledger=ledger, root=root, clock=clock)


def generation(env, name, *, cap=0, seconds=0, member=None, complexity=None, first_family=None):
    payload = deepcopy(env['original']['payload'])
    intent = payload['planning_intent']
    intent['physical_retry'] = name
    if member:
        intent['attempt_lineage_id'] = member
    if complexity:
        intent['complexity'] = complexity
    if first_family:
        intent['candidate_profiles'] = [key for key, model in payload['task_catalog']['models'].items()
                                        if model['family'] == first_family][:1]
    base = env['original']['routing']['policy'] | {'max_dispatches': cap, 'max_routing_seconds': seconds}
    policy = scoped_policy(base, intent, payload['task_catalog'])
    job_id, root_id = 'job-'+name, 'flow-'+name
    with env['store']._write() as conn:
        budget = capture_lineage_budget(conn, job_id, payload, policy,
            attempt_ledger=env['ledger'], now=env['clock'][0])
        env['store']._insert(conn, root_id, root_id, None, 'MACRO_PLANNING_REQUEST', 'IN_PROGRESS', {})
        routes.capture_workflow(conn, root_id, policy, max_dispatches=budget.max_dispatches)
        env['store']._insert(conn, job_id, root_id, root_id, 'TASK_PLAN', 'PENDING', payload,
                             max_attempts=budget.max_attempts)
    return env['store'].get(job_id), budget


def spend(env, job_id, count=1):
    # This fixture represents actual reservations already charged by the board.
    with env['store']._write() as conn:
        conn.execute('UPDATE pipeline_routing_jobs SET dispatches=dispatches+? WHERE job_id=?',
                     (count, job_id))


def quality_failures(env, count, model='old-model'):
    for _ in range(count):
        lease = env['ledger'].start(env['root'], env['root'], model)
        env['ledger'].finish(lease, 'quality_failure', digest(lease))


def test_new_physical_generation_keeps_total_dispatch_and_oldest_expiry(env):
    first, one = generation(env, 'one', cap=12, seconds=100)
    spend(env, first['job_id'], 4)
    env['clock'][0] += 30
    second, two = generation(env, 'two', cap=12, seconds=100)
    assert (two.max_dispatches, two.dispatches_before, two.total_dispatch_limit) == (8, 4, 12)
    assert two.expires_at == one.expires_at == 1100
    assert second['routing']['expires_at'] == 1100
    assert env['store'].get(first['job_id'])['routing']['max_dispatches'] == 12
    assert env['store'].get(first['job_id'])['routing']['created_at'] == 1000
    spend(env, second['job_id'], 3)
    third, three = generation(env, 'three', cap=12, seconds=100)
    assert (three.max_dispatches, three.total_dispatch_limit) == (5, 12)
    assert third['routing']['max_dispatches'] == 5


def test_legacy_dispatches_are_adopted_without_rewriting_old_capture(env):
    original = env['original']
    spend(env, original['job_id'], 3)
    with env['store']._connection() as conn:
        before = dict(conn.execute('SELECT * FROM pipeline_routing_jobs WHERE job_id=?',
                                  (original['job_id'],)).fetchone())
    _, budget = generation(env, 'adopt', cap=8, seconds=60)
    assert budget.max_dispatches == 5
    assert budget.expires_at == 1060
    with env['store']._connection() as conn:
        assert dict(conn.execute('SELECT * FROM pipeline_routing_jobs WHERE job_id=?',
                                (original['job_id'],)).fetchone()) == before


def test_zero_is_unlimited_but_cannot_remove_prior_finite_limit(env):
    first, budget = generation(env, 'unlimited')
    assert budget.max_dispatches is None and budget.expires_at is None
    spend(env, first['job_id'], 100)
    _, second = generation(env, 'still-unlimited')
    assert second.max_dispatches is None and second.dispatches_before == 100
    _, finite = generation(env, 'finite', cap=105, seconds=100)
    assert finite.max_dispatches == 5
    _, retained = generation(env, 'unlimited-again')
    assert retained.max_dispatches == 5 and retained.expires_at == finite.expires_at


def test_quality_window_is_remaining_and_format_dispatches_do_not_spend_quality(env):
    first, _ = generation(env, 'format', cap=50)
    spend(env, first['job_id'], 2)
    quality_failures(env, 9)
    job, budget = generation(env, 'retry', cap=50)
    assert budget.max_attempts == job['max_attempts'] == 1
    assert budget.max_dispatches == 48
    assert env['ledger'].status(env['root'])['failures'] == 9


def test_research_gate_and_completed_pivot_do_not_refresh_limits(env):
    first, _ = generation(env, 'before-pivot', cap=25, seconds=120)
    spend(env, first['job_id'], 10)
    quality_failures(env, 10)
    with pytest.raises(LineageBudgetHold, match='quality_research_or_lock_required'):
        generation(env, 'illegal-skip', cap=25)
    family = next(iter(env['original']['payload']['task_catalog']['models'].values()))['family']
    env['ledger'].pivot(env['root'], research(), dict(strategy='pivot', task_types=['COD-TERM'],
        complexity=2, rationale='Different approach', next_model=family, children=[]), digest('pivot'))
    _, budget = generation(env, 'after-pivot', cap=25, complexity=10, first_family=family)
    assert budget.max_attempts == 10 and budget.max_dispatches == 15
    assert budget.expires_at == 1120


@pytest.mark.parametrize('stage,due,failures', [('LOCKED',False,30), ('READY',True,10), ('PIVOT_RESEARCH',True,20)])
def test_no_new_generation_can_skip_research_or_lock(env, stage, due, failures):
    with env['ledger']._write() as conn:
        state = env['ledger']._read(conn, env['root'])
        state.update(stage=stage, research_due=due, failures=failures)
        env['ledger']._save(conn, state)
    with pytest.raises(LineageBudgetHold, match='quality_research_or_lock_required'):
        generation(env, 'blocked')
    with env['store']._connection() as conn:
        assert conn.execute("SELECT 1 FROM pipeline_jobs WHERE job_id='job-blocked'").fetchone() is None


def test_active_quality_attempt_and_lowered_reasoning_floor_are_held(env):
    lease = env['ledger'].start(env['root'], env['root'], 'active-model')
    with pytest.raises(LineageBudgetHold, match='quality_attempt_still_active'):
        generation(env, 'active')
    env['ledger'].finish(lease, 'success', digest('finished'))
    with env['ledger']._write() as conn:
        state = env['ledger']._read(conn, env['root'])
        state['floor'] = 8
        env['ledger']._save(conn, state)
    with pytest.raises(LineageBudgetHold, match='retained_reasoning_floor'):
        generation(env, 'lowered', complexity=2)


def test_poll_capture_is_idempotent_and_sidecar_is_immutable(env):
    job, budget = generation(env, 'same', cap=12, seconds=50)
    quality_failures(env, 1)
    env['clock'][0] += 20
    with env['store']._write() as conn:
        replay = capture_lineage_budget(conn, job['job_id'], job['payload'], job['routing']['policy'],
                                       attempt_ledger=env['ledger'])
        assert replay == budget
        with pytest.raises(sqlite3.IntegrityError, match='immutable'):
            conn.execute('UPDATE planning428_budget_captures SET expires_at=999999')
        changed = deepcopy(job['payload'])
        changed['planning_intent']['physical_retry'] = 'forged'
        with pytest.raises(ValueError, match='different immutable input'):
            capture_lineage_budget(conn, job['job_id'], changed, job['routing']['policy'],
                                   attempt_ledger=env['ledger'])


def test_expired_and_exhausted_generations_hold_without_zero_becoming_unlimited(env):
    job, _ = generation(env, 'finite', cap=2, seconds=60)
    spend(env, job['job_id'], 2)
    with pytest.raises(LineageBudgetHold, match='lineage_dispatch_budget_exhausted'):
        generation(env, 'over', cap=2)
    env['clock'][0] += 61
    with env['store']._connection() as conn:
        assert lineage_unavailability(conn, job['job_id'], env['clock'][0]) == 'lineage_routing_time_exhausted'
    # A distinct independent lineage still uses its own budget and deadline.
    env['ledger'].create('independent', 1)
    _, independent = generation(env, 'independent', member='independent', cap=2, seconds=60)
    assert independent.max_dispatches == 2 and independent.expires_at == 1121


def test_fracture_siblings_share_live_aggregate_guard(env):
    # Registered fracture membership is authoritative; unrelated WBS members
    # do not match merely because their task_id or prompt matches.
    with env['ledger']._write() as conn:
        conn.executemany('INSERT INTO task428_members VALUES(?,?)',
                         [('child-a', env['root']), ('child-b', env['root'])])
    first, _ = generation(env, 'child-a', member='child-a', cap=2)
    second, _ = generation(env, 'child-b', member='child-b', cap=2)
    spend(env, first['job_id'], 2)
    with env['store']._write() as conn:
        assert routes.preview_next_route(conn, second)['state'] == 'lineage_dispatch_budget_exhausted'
        assert routes.select(conn, second)[0] == {'exhausted': 'Lineage dispatch budget exhausted'}
        with pytest.raises(LineageBudgetHold, match='lineage_dispatch_budget_exhausted'):
            routes.reserve(conn, second, {}, 'slot1')
    assert env['store'].get(second['job_id'])['routing']['dispatches'] == 0


def test_insertion_rejects_reset_quality_or_dispatch_budget(env):
    payload = deepcopy(env['original']['payload'])
    policy = env['original']['routing']['policy']
    quality_failures(env, 9)
    with pytest.raises(ValueError, match='differs from its controller budget'):
        with env['store']._write() as conn:
            capture_lineage_budget(conn, 'invalid', payload, policy, attempt_ledger=env['ledger'])
            env['store']._insert(conn, 'root-invalid', 'root-invalid', None,
                                 'MACRO_PLANNING_REQUEST', 'IN_PROGRESS', {})
            routes.capture_workflow(conn, 'root-invalid', policy)
            env['store']._insert(conn, 'invalid', 'root-invalid', 'root-invalid',
                                 'TASK_PLAN', 'PENDING', payload, max_attempts=10)
    with env['store']._connection() as conn:
        assert conn.execute("SELECT 1 FROM pipeline_jobs WHERE job_id='invalid'").fetchone() is None


def test_expired_capture_cannot_be_refreshed_by_new_generation(env):
    job, _ = generation(env, 'time-bounded', seconds=10)
    env['clock'][0] += 11
    with pytest.raises(LineageBudgetHold, match='lineage_routing_time_exhausted'):
        generation(env, 'no-fresh-clock', seconds=999)
    with env['store']._connection() as conn:
        conn.execute('PRAGMA query_only=ON')
        assert routes.preview_next_route(conn, job)['state'] == 'lineage_routing_time_exhausted'


def test_missing_lineage_is_a_hold_not_a_new_budget(env):
    with pytest.raises(LineageBudgetHold, match='attempt_lineage_not_initialized'):
        generation(env, 'unregistered', member='unknown')


def test_new_capture_and_failed_insert_rollback_as_one_board_transaction(env):
    payload, policy = env['original']['payload'], env['original']['routing']['policy']
    with pytest.raises(RuntimeError, match='simulated insertion failure'):
        with env['store']._write() as conn:
            capture_lineage_budget(conn, 'rolled-back', payload, policy, attempt_ledger=env['ledger'])
            raise RuntimeError('simulated insertion failure')
    with env['store']._connection() as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='planning428_budget_captures'").fetchone() is None


def test_actual_claims_charge_aggregate_budget_without_native_processes(env):
    # All three generations are queued before any actual board dispatch.
    generation(env, 'first-claim', cap=2)
    generation(env, 'second-claim', cap=2)
    generation(env, 'third-claim', cap=2)
    claimed = []
    for index in range(3):
        job = env['store'].claim('fixture', worker_slot='slot'+str(index + 1),
                                  allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
        if job:
            claimed.append(job)
    assert len(claimed) == 2
    with env['store']._connection() as conn:
        assert conn.execute('SELECT count(*) FROM pipeline_route_reservations').fetchone()[0] == 2
        assert lineage_unavailability(conn, 'job-third-claim', 1000) == 'lineage_dispatch_budget_exhausted'
