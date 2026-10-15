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


def generation(env, name, *, cap=0, seconds=0, member=None, complexity=None, first_family=None, aggregate=None):
    payload = deepcopy(env['original']['payload'])
    intent = payload['planning_intent']
    intent['physical_retry'] = name
    if member:
        intent['attempt_lineage_id'] = member
    if complexity:
        intent['complexity'] = complexity
    if aggregate:
        intent['task']['fracture_promotion'] = {'lineage_root': aggregate}
    if first_family:
        intent['candidate_profiles'] = [key for key, model in payload['task_catalog']['models'].items()
                                        if model['family'] == first_family][:1]
    base = env['original']['routing']['policy'] | {'max_dispatches': cap, 'max_routing_seconds': seconds}
    policy = scoped_policy(base, intent, payload['task_catalog'])
    job_id, root_id = 'job-'+name, 'flow-'+name
    with env['store']._write() as conn:
        budget = capture_lineage_budget(conn, job_id, payload, policy,
            attempt_ledger=env['ledger'], now=env['clock'][0], aggregate_lineage_root=aggregate)
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


@pytest.mark.parametrize('boundary', [10, 20])
def test_promotion_controls_share_dispatch_and_time_without_resuming_quality(env, boundary):
    first, initial = generation(env, 'before-promotion', cap=30, seconds=100)
    spend(env, first['job_id'], boundary)
    with env['ledger']._write() as conn:
        state = env['ledger']._read(conn, env['root'])
        state.update(stage='PIVOT_RESEARCH', failures=boundary, research_due=True)
        env['ledger']._save(conn, state)
    env['ledger'].create('control', 4)
    env['clock'][0] += 20
    control, budget = generation(env, 'control-a', cap=40, seconds=1000, member='control', aggregate=env['root'])
    assert budget.max_dispatches == 30-boundary and budget.expires_at == initial.expires_at
    with env['store']._write() as conn:
        assert lineage_unavailability(conn, first['job_id'], env['clock'][0]) == 'quality_research_pending'
        assert lineage_unavailability(conn, control['job_id'], env['clock'][0]) is None
    spend(env, control['job_id'], 2)
    env['ledger'] = AttemptLedger(env['ledger'].path)
    next_job, later = generation(env, 'control-b', member='control', aggregate=env['root'])
    assert later.max_dispatches == 28-boundary and later.expires_at == initial.expires_at
    assert env['ledger'].status(env['root'])['failures'] == boundary
    spend(env, next_job['job_id'], 28-boundary)
    with env['store']._write() as conn:
        assert lineage_unavailability(conn, control['job_id'], env['clock'][0]) == 'lineage_dispatch_budget_exhausted'
        with pytest.raises(LineageBudgetHold, match='dispatch_budget'):
            routes.reserve(conn, control, {}, 'slot1')
    assert env['ledger'].status('control')['failures'] == 0


def test_control_parent_requires_due_boundary_and_cannot_rebind(env):
    env['ledger'].create('control', 4)
    with pytest.raises(LineageBudgetHold, match='parent_not_due'):
        generation(env, 'too-early', member='control', aggregate=env['root'])
    quality_failures(env, 10)
    generation(env, 'bound', member='control', aggregate=env['root'])
    env['ledger'].create('other', 4)
    with pytest.raises(LineageBudgetHold, match='parent_changed'):
        generation(env, 'rebound', member='control', aggregate='other')


@pytest.mark.parametrize('stage,failures', [('READY',10), ('LOCKED',30)])
def test_queued_promotion_controls_stop_when_original_boundary_closes(env, stage, failures):
    quality_failures(env, 10)
    env['ledger'].create('control', 4)
    job, _ = generation(env, 'bound', member='control', aggregate=env['root'])
    with env['ledger']._write() as conn:
        state = env['ledger']._read(conn, env['root'])
        state.update(stage=stage, failures=failures, research_due=stage=='LOCKED')
        env['ledger']._save(conn, state)
    with env['store']._write() as conn:
        assert lineage_unavailability(conn, job['job_id'], env['clock'][0]) == 'quality_research_or_lock_required'
    with pytest.raises(LineageBudgetHold, match='parent_not_due'):
        generation(env, 'late', member='control', aggregate=env['root'])


@pytest.mark.parametrize('stage,failures', [('PIVOT_RESEARCH',10),('PIVOT_RESEARCH',20),('LOCKED',30)])
def test_queued_sibling_rechecks_live_quality_boundary_without_spending(env,stage,failures):
    first, _ = generation(env, 'queued-a', cap=50)
    second, _ = generation(env, 'queued-b', cap=50)
    with env['ledger']._write() as conn:
        state = env['ledger']._read(conn, env['root'])
        state.update(stage=stage, failures=failures, research_due=True)
        env['ledger']._save(conn, state)
    with env['store']._write() as conn:
        reason = 'quality_research_pending' if stage == 'PIVOT_RESEARCH' else 'quality_research_or_lock_required'
        assert routes.preview_next_route(conn, second)['state'] == reason
        with pytest.raises(LineageBudgetHold, match=reason):
            routes.reserve(conn, second, {}, 'slot2')
        assert routes.select(conn, second) == (None, True)
    assert env['store'].get(first['job_id'])['routing']['dispatches'] == 0
    assert env['store'].get(second['job_id'])['routing']['dispatches'] == 0
    saved = env['store'].get(second['job_id'])
    assert saved['status'] == ('PENDING' if stage == 'PIVOT_RESEARCH' else 'BLOCKED')
    assert saved['routing']['state'] == ('WAITING' if stage == 'PIVOT_RESEARCH' else 'BLOCKED')


@pytest.mark.parametrize('boundary', [10, 20])
def test_research_parking_survives_restart_then_rechecks_retained_floor(env, boundary):
    sibling, _ = generation(env, 'parked', cap=50)
    with env['ledger']._write() as conn:
        state = env['ledger']._read(conn, env['root'])
        state.update(stage='PIVOT_RESEARCH', failures=boundary, research_due=True)
        env['ledger']._save(conn, state)
    with env['store']._write() as conn:
        assert routes.select(conn, sibling) == (None, True)
    env['ledger'] = AttemptLedger(env['ledger'].path)
    env['clock'][0] += 2
    with env['ledger']._write() as conn:
        state = env['ledger']._read(conn, env['root'])
        state.update(stage='READY', research_due=False,
                     floor=sibling['payload']['planning_intent']['complexity'] + 1)
        env['ledger']._save(conn, state)
    with env['store']._write() as conn:
        assert routes.preview_next_route(conn, sibling)['state'] == 'retained_reasoning_floor'
        assert routes.select(conn, sibling) == (None, True)
    saved = env['store'].get(sibling['job_id'])
    assert saved['status'] == 'BLOCKED'
    assert saved['routing']['wait_reason'] == 'retained_reasoning_floor'
    assert saved['routing']['dispatches'] == saved['routing']['failure_count'] == 0
    assert env['ledger'].status(env['root'])['failures'] == boundary


def test_live_quality_snapshot_prevents_boundary_commit_during_reservation(env):
    job, _ = generation(env, 'fenced')
    writer = sqlite3.connect(env['ledger'].path, timeout=.01)
    with env['store']._write() as conn:
        assert lineage_unavailability(conn, job['job_id'], env['clock'][0]) is None
        with pytest.raises(sqlite3.OperationalError,match='locked'):
            writer.execute('BEGIN IMMEDIATE')
            writer.execute('UPDATE task428_lineages SET state_json=state_json')
            writer.commit()
        writer.rollback()
    writer.execute('BEGIN IMMEDIATE')
    writer.execute('UPDATE task428_lineages SET state_json=state_json')
    writer.commit(); writer.close()


def test_live_quality_gate_preserves_read_only_preview(env):
    job, _ = generation(env, 'query-only')
    with env['store']._connection() as conn:
        conn.execute('PRAGMA query_only=ON')
        assert lineage_unavailability(conn, job['job_id'], env['clock'][0]) is None


def test_queued_siblings_cannot_overrun_tenth_failure_while_outcome_is_in_flight(env):
    generation(env, 'window-a', cap=50)
    second, _ = generation(env, 'window-b', cap=50)
    quality_failures(env, 9)
    first = env['store'].claim('fixture', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    assert first is not None
    assert env['store'].claim('fixture', worker_slot='slot2', allowed_kinds=['TASK_PLAN'], requires_cleanup=True) is None
    pending = env['store'].get(second['job_id'])
    assert pending['status'] == 'PENDING'
    assert pending['routing']['wait_reason'] == 'quality_window_in_flight'
    with env['store']._connection() as conn:
        assert conn.execute('SELECT count(*) FROM pipeline_route_reservations').fetchone()[0] == 1
    assert env['ledger'].status(env['root'])['failures'] == 9
    env['store'].clear_execution_quarantine(first['job_id'],first['attempt_id'],first['fencing_token'])
    env['store'].fail(first['job_id'],first['attempt_id'],first['fencing_token'],'quota',category='quota')
    env['clock'][0] += 2
    with env['store']._connection() as conn:
        assert lineage_unavailability(conn, second['job_id'], env['clock'][0]) is None


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


@pytest.fixture
def compiled_fracture(env):
    from cochem_pipeline.fracture_runtime_428 import FractureRuntime
    with env['ledger']._write() as conn:
        state = env['ledger']._read(conn, env['root'])
        state['floor'] = 5
        env['ledger']._save(conn, state)
    quality_failures(env, 10)
    runtime = FractureRuntime(env['ledger'], env['original']['payload']['task_catalog'])
    runtime.dossier_store.record_dossier(env['root'], 10, research_channels=research(),
        root_cause_synthesis='Split the failed component', hypotheses=['Smaller implementation units'])
    children = [dict(id=name, role='implementation', complexity=2, task_types=['COD-TERM'],
        rationale='Narrow implementation fragment', requirement_ids=[req], deliverables=[name+'.py'],
        release_criteria=['Focused checks pass'], depends_on=[])
        for name, req in [('fragment-a','R1'),('fragment-b','R2')]]
    children.append(dict(id='assembly', role='assembly', complexity=6, task_types=['COD-TERM'],
        rationale='Assemble and verify both fragments', requirement_ids=['R1','R2'],
        deliverables=['fragment-a.py','fragment-b.py'], release_criteria=['Combined checks pass'],
        depends_on=['fragment-a','fragment-b']))
    result = runtime.execute_fracture(env['root'],
        failed_scope=dict(scope_id='failed-component',requirement_ids=['R1','R2'],
                          deliverables=['fragment-a.py','fragment-b.py']), children=children,
        review=dict(reviewer_model='claude-opus-5-5',reviewer_tier=6,effort='high',accepted=True,
                    review_sha256=digest('independent-review')))
    child = next(row for row in result['children'] if row['child_id']=='fragment-a')
    payload = deepcopy(env['original']['payload'])
    payload['planning_intent'].update(stage='MICROTASK_EXECUTION',microtask_id=child['child_id'],
        complexity=child['complexity'],task_types=child['task_types'],
        candidate_profiles=[child['selected_profile_id']])
    payload['microtask_node'] = dict(lineage_kind='FAILURE_FRACTURE',attempt_lineage_id=child['child_id'],
        **{key:child[key] for key in ('role','complexity','task_types','requirement_ids','deliverables','depends_on')},
        fracture_context=dict(fracture_id=child['fracture_id'], graph_sha256=child['graph_sha256'],
            dossier_sha256=child['dossier_sha256'],lineage_root=env['root'],failed_microtask_id=child['failed_scope_id']))
    return env, payload


def test_compiled_fragment_keeps_its_lower_tier_and_inherits_shared_remainder(compiled_fracture):
    env, payload = compiled_fracture
    policy = scoped_policy(env['original']['routing']['policy'],payload['planning_intent'],payload['task_catalog'])
    with env['store']._write() as conn:
        budget = capture_lineage_budget(conn, 'compiled-fragment',payload,policy,attempt_ledger=env['ledger'])
    assert budget.lineage_root == env['root'] and budget.max_attempts == 10
    assert env['ledger'].status(env['root'])['floor'] == 6
    assert env['ledger'].status(env['root'])['failures'] == 10


@pytest.mark.parametrize('mutation',['unregistered','classification','tags','profile','scope','context','graph','approval','status'])
def test_forged_or_held_fragment_cannot_lower_root_floor(compiled_fracture, mutation):
    env, payload = compiled_fracture
    node, intent = payload['microtask_node'], payload['planning_intent']
    if mutation=='unregistered':
        env['ledger'].create('fake-child',1)
        node['attempt_lineage_id']='fake-child'
    if mutation=='classification': intent['complexity']=1
    if mutation=='tags': intent['task_types']=['SCI-FORMAL']
    if mutation=='profile': intent['candidate_profiles']=env['original']['payload']['planning_intent']['candidate_profiles']
    if mutation=='scope': node['deliverables']=['unreviewed.py']
    if mutation=='context': node['fracture_context']['graph_sha256']='f'*64
    if mutation in ('graph','approval','status'):
        with env['ledger']._write() as conn:
            column,value = {'graph':('node_json','{}'),'approval':('needs_owner_approval',1),
                            'status':('status','FRACTURED_OBSOLETE')}[mutation]
            conn.execute(f'UPDATE task428_fracture_nodes SET {column}=? WHERE child_id=?',(value,'fragment-a'))
    policy = scoped_policy(env['original']['routing']['policy'],intent,payload['task_catalog'])
    with pytest.raises(LineageBudgetHold, match='compiled_fracture'):
        with env['store']._write() as conn:
            capture_lineage_budget(conn, 'forged-fragment',payload,policy,attempt_ledger=env['ledger'])
