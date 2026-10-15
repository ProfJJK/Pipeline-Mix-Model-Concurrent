"""In-process board/research/pivot lifecycle, with no provider execution."""
import json

import pytest

from cochem_pipeline.attempt_runtime_428 import AttemptAccountingRuntime
from cochem_pipeline.failure_dossier_428 import FailureDossierStore
from cochem_pipeline.microtask_board_428 import MicrotaskBoardRuntime
from cochem_pipeline.pivot_runtime_428 import PivotRuntime
from cochem_pipeline.planning_gateway import prompt_contract
from cochem_pipeline.planning_outcomes_428 import PlanningOutcomeRuntime
from cochem_pipeline.planning_pivots_428 import PlanningPivotRuntime
from cochem_pipeline.research_evidence_428 import ResearchEvidenceStore
from cochem_pipeline.research_runtime_428 import ResearchRuntime
from cochem_pipeline.workflow_428 import AttemptLedger
from pipeline_tests.test_microtask_board_428 import _make_store_and_journal, _advance_task_to_reassessed_ready
from pipeline_tests.test_planning_gateway_428 import accepted_receipt


@pytest.fixture
def env(tmp_path):
    store, journal, broker = _make_store_and_journal(tmp_path)
    _advance_task_to_reassessed_ready(journal, task_id='task', include_second_independent_fragment=False)
    ledger = AttemptLedger(tmp_path/'attempts.db')
    accounting = AttemptAccountingRuntime(ledger, store=store)
    board = MicrotaskBoardRuntime(journal, store, owner_broker=broker, attempt_ledger=accounting)
    research = ResearchRuntime(ResearchEvidenceStore(tmp_path/'research.db'), None)
    outcomes = PlanningOutcomeRuntime(journal, store, accounting, research_runtime=research,
        dossier_store=FailureDossierStore(ledger))
    with journal._write() as conn:
        catalog = json.loads(journal._read(conn, 'task')['catalog_json'])
    pivots = PivotRuntime(ledger, catalog, dossier_store=outcomes.dossier_store)
    bridge = PlanningPivotRuntime(journal, store, outcomes, pivots)
    board.pivot_context_provider = bridge.dispatch_context
    return store, journal, ledger, board, outcomes, bridge


def fail_window(env):
    store, journal, ledger, board, outcomes, bridge = env
    board.materialize('task')
    board.materialize('task')
    jobs = []
    for _ in range(10):
        job = store.claim('inert-test', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
        assert job is not None
        assert job['payload']['planning_intent']['stage'] == 'MICROTASK_EXECUTION'
        jobs.append(job)
        store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
        store.fail(job['job_id'], job['attempt_id'], job['fencing_token'], 'inert verification failed', retry=True, category='code')
    assert outcomes.reconcile_task('task') >= 10
    boundary = outcomes.status('task')[-1]
    request = json.loads(outcomes.research_runtime.queue_status(boundary['research_id'])['intent_json'])
    evidence = outcomes.research_runtime.evidence_store
    for channel in ('internet', 'wiki_rag', 'papers'):
        evidence.record_channel(boundary['research_id'], channel, query=request['query'], status='no_results', sources=[])
    evidence.publish(boundary['research_id'])
    outcomes.reconcile_task('task')
    return jobs[-1], outcomes.status('task')[-1]


def complete_review(env, *, strategy='pivot', complexity=2):
    store, journal, ledger, board, outcomes, bridge = env
    bridge.step('task')
    job = store.claim('inert-review', worker_slot='slot2', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    assert job is not None
    assert job['payload']['planning_intent']['stage'] == 'PIVOT_REVIEW'
    output = dict(strategy=strategy, assessment=dict(complexity=complexity, task_types=['COD-TERM'],
        rationale='Reassessed bounded parser implementation'), root_cause_synthesis='Parser fails the empty input contract',
        hypotheses=['Empty input branch is missing'], approach='Add an explicit empty-input branch before tokenization',
        fracture_reason='Split lexer and parser with a verified interface' if strategy == 'fracture' else '')
    store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
    store.complete(job['job_id'], job['attempt_id'], job['fencing_token'], output, accepted_receipt(job, output))
    return store.get(job['job_id'])


def test_pivot_creates_new_capture_with_dossier_exact_profile_and_unchanged_budget(env):
    store, journal, ledger, board, outcomes, bridge = env
    old, boundary = fail_window(env)
    review = complete_review(env)
    bridge.step('task')
    root = boundary['lineage_root']
    state = ledger.status(root)
    assert state['failures'] == 10 and state['floor'] == 5
    assert len(state['pivots']) == 1
    board.materialize('task')
    board.materialize('task')
    job = store.claim('inert-new', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    assert job and job['job_id'] != old['job_id']
    assert store.get(old['job_id'])['status'] == 'BLOCKED'
    payload = job['payload']
    assert payload['planning_intent']['complexity'] == 5
    assert len(payload['planning_intent']['candidate_profiles']) == 1
    profile = payload['task_catalog']['models'][payload['planning_intent']['candidate_profiles'][0]]
    assert profile['family'] != state['last_model']
    assert profile['family'] == state['next_model']
    _, _, task = prompt_contract(payload)
    assert task['microtask_node']['pivot_context']['approach'] == review['output']['approach']
    assert task['microtask_node']['pivot_context']['failure_dossier']['boundary'] == 10
    outcomes.reconcile_task('task')
    assert ledger.status(root)['failures'] == 10


def test_fracture_is_explicit_hold_and_never_dispatches_unreviewed_children(env):
    store, journal, ledger, board, outcomes, bridge = env
    old, boundary = fail_window(env)
    complete_review(env, strategy='fracture')
    bridge.step('task')
    assert outcomes.status('task')[-1]['status'] == 'FRACTURE_PLAN_REQUIRED'
    assert ledger.status(boundary['lineage_root'])['stage'] == 'PIVOT_RESEARCH'
    board.materialize('task')
    assert store.claim('inert', worker_slot='slot1', allowed_kinds=['TASK_PLAN']) is None


def test_newly_high_tier_pivot_does_not_bypass_child_owner_approval(env):
    store, journal, ledger, board, outcomes, bridge = env
    old, boundary = fail_window(env)
    complete_review(env, complexity=8)
    bridge.step('task')
    assert outcomes.status('task')[-1]['status'] == 'PIVOT_OWNER_APPROVAL_REQUIRED'
    assert ledger.status(boundary['lineage_root'])['stage'] == 'PIVOT_RESEARCH'
    assert ledger.status(boundary['lineage_root'])['failures'] == 10


def test_pivot_review_availability_does_not_consume_original_lineage(env):
    store, journal, ledger, board, outcomes, bridge = env
    old, boundary = fail_window(env)
    bridge.step('task')
    job = store.claim('inert-review', worker_slot='slot2', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
    store.fail(job['job_id'], job['attempt_id'], job['fencing_token'], 'quota unavailable', retry=True, category='quota')
    outcomes.reconcile_task('task')
    assert ledger.status(boundary['lineage_root'])['failures'] == 10
    assert ledger.status(boundary['lineage_root'])['stage'] == 'PIVOT_RESEARCH'


def test_cancelled_task_cannot_create_pivot_review(env):
    store, journal, ledger, board, outcomes, bridge = env
    fail_window(env)
    journal.cancel('task')
    assert bridge.step('task') == 0
    assert bridge.cancellation_targets('task') == []


def test_unmeasured_pivot_family_cannot_bypass_reasoning_floor(env):
    from cochem_pipeline.swarm_batch_428 import resolve_microtask_route_tier
    store, journal, ledger, board, outcomes, bridge = env
    catalog = journal.catalog
    with pytest.raises(ValueError, match='reasoning floor'):
        resolve_microtask_route_tier(dict(microtask_id='mt-1', complexity=4, effective_complexity=6,
            task_types=['COD-TERM'], pivot_model='gemini-3.8-flash'), catalog)


def test_completed_review_is_idempotent_after_bridge_restart(env):
    store, journal, ledger, board, outcomes, bridge = env
    old, boundary = fail_window(env)
    complete_review(env)
    bridge.step('task')
    reopened = PlanningPivotRuntime(journal, store, outcomes, bridge.pivot_runtime)
    reopened.step('task')
    assert len(ledger.status(boundary['lineage_root'])['pivots']) == 1
    assert len(reopened.cancellation_targets('task')) == 1


def test_recovers_ledger_commit_before_pivot_record(env, monkeypatch):
    store, journal, ledger, board, outcomes, bridge = env
    old, boundary = fail_window(env)
    complete_review(env)
    original = ledger.pivot
    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('simulated interruption after ledger commit')
    monkeypatch.setattr(ledger, 'pivot', crash)
    with pytest.raises(RuntimeError, match='simulated interruption'):
        bridge.step('task')
    monkeypatch.setattr(ledger, 'pivot', original)
    bridge.step('task')
    assert outcomes.status('task')[-1]['status'] == 'PIVOT_READY_NEW_CAPTURE'
    assert len(ledger.status(boundary['lineage_root'])['pivots']) == 1


def test_all_three_windows_keep_counts_and_thirty_locks(env):
    store, journal, ledger, board, outcomes, bridge = env
    old_ids = []
    for number in (10, 20, 30):
        old, boundary = fail_window(env)
        old_ids.append(old['job_id'])
        assert boundary['boundary'] == number
        if number < 30:
            complete_review(env)
            bridge.step('task')
        else:
            assert boundary['status'] == 'LOCKED_AWAITING_OWNER'
            assert bridge.step('task') == 0
    assert len(set(old_ids)) == 3
    state = ledger.status(boundary['lineage_root'])
    assert state['failures'] == 30 and state['stage'] == 'LOCKED'
    assert len(state['pivots']) == 2
    board.materialize('task')
    assert store.claim('inert', worker_slot='slot1', allowed_kinds=['TASK_PLAN']) is None
