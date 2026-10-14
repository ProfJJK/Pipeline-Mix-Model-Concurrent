"""In-process journal/authority fixtures. No provider or native execution."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from cochem_pipeline.planning_journal import PlanningJournal
from cochem_pipeline.task_routing import digest
from pipeline_tests.test_workflow_428 import document, research, wbs, microtasks


@pytest.fixture
def board(tmp_path):
    catalog = json.loads((Path(__file__).parents[1]/'docs/4.2.8/routing-candidate.json').read_text(encoding='utf-8'))
    results, searches, approvals = {}, {}, {}
    journal = PlanningJournal(tmp_path/'board.sqlite', catalog,
        model_result=results.get, search_result=searches.get, owner_receipt=approvals.get,
        flash_context_limit=100000)
    journal.create('task', 'Implement and prove the required output')
    return journal, results, searches, approvals


def complete(board, output, *, profile=None, job=None):
    journal, results, _, _ = board
    intent = journal.intent('task')
    assert intent['action'] == 'model_stage'
    job = job or 'job'+str(intent['version'])
    results[job] = dict(job_id=job, intent_sha256=digest(intent),
        profile_id=profile or intent['candidate_profiles'][0], status='COMPLETED',
        cleanup_verified=True, output=output)
    return journal.apply_model_result('task', intent['version'], job)


def searched(board):
    journal, _, searches, _ = board
    intent = journal.intent('task')
    searches['search1'] = dict(intent_sha256=digest(intent), channels=research())
    return journal.apply_research('task', intent['version'], 'search1')


def review():
    return dict(accepted=True, findings=['Requirements are covered'], suggestions=[], clarifications=[])


def test_simple_task_ready_without_inventing_a_native_lease(board):
    state = complete(board, document(2))
    assert state['stage'] == 'READY'
    intent = board[0].intent('task')
    assert intent['action'] == 'jobboard_submission' and intent['execution_authorized'] is False


def test_high_task_requires_separate_human_authority_before_research(board):
    journal, results, _, approvals = board
    state = complete(board, document(8))
    assert state['stage'] == 'OWNER_APPROVAL'
    assert journal.intent('task')['action'] == 'owner_review'
    approvals['owner'] = dict(task_id='task', srs_sha256=state['srs_sha256'],
                              decision='approved', actor_kind='agent')
    with pytest.raises(ValueError, match='human-owner'):
        journal.apply_owner_approval('task', state['journal_version'], 'owner')
    approvals['owner']['actor_kind'] = 'human_owner'
    state = journal.apply_owner_approval('task', state['journal_version'], 'owner')
    assert state['stage'] == 'RESEARCH'


def test_lower_multi_type_has_no_human_gate(board):
    state = complete(board, document(2, ['COD-TERM','SCI-FORMAL']))
    assert state['stage'] == 'PLAN_REVIEW'
    assert board[0].intent('task')['complexity'] == 3
    assert state['approval_required'] is False


def test_complete_planning_chain_and_reassessment_are_durable(board):
    journal = board[0]
    complete(board, document(4))
    searched(board)
    plan_intent = journal.intent('task')
    producer = plan_intent['task']['planner_profile']
    assert all(journal.catalog['models'][x]['family'] != journal.catalog['models'][producer]['family']
               for x in plan_intent['candidate_profiles'])
    complete(board, review())
    complete(board, {'wbs':wbs()})
    complete(board, {'microtasks':microtasks()})
    state = complete(board, {'assessments':[dict(id=x['id'], complexity=x['complexity'],
        task_types=x['task_types'], rationale='Assessed the actual microtask deliverable') for x in microtasks()]})
    assert state['stage'] == 'MICROTASKS_READY'
    reopened = PlanningJournal(journal.path, journal.catalog)
    assert reopened.status('task') == state
    assert reopened.intent('task')['execution_authorized'] is False


def test_completion_is_idempotent_but_cannot_rebind_or_rewrite_evidence(board):
    journal, results, _, _ = board
    state = complete(board, document(2), job='one')
    assert journal.apply_model_result('task', 0, 'one') == state
    journal.create('other', 'Another objective')
    with pytest.raises(ValueError, match='rebound'):
        journal.apply_model_result('other', 0, 'one')
    results['one']['output'] = document(8)
    with pytest.raises(ValueError, match='rewritten'):
        journal.apply_model_result('task', 0, 'one')


def test_changed_global_catalog_does_not_rewrite_captured_workflow(board):
    journal = board[0]
    old = journal.intent('task')
    changed = deepcopy(journal.catalog)
    changed['generation'] = 'future'
    reopened = PlanningJournal(journal.path, changed)
    assert reopened.intent('task') == old


@pytest.mark.parametrize('field,value', [('intent_sha256','a'*64), ('profile_id','invented'),
                                      ('cleanup_verified',False), ('status','IN_PROGRESS')])
def test_unmatched_result_never_advances_planning(board, field, value):
    journal, results, _, _ = board
    intent = journal.intent('task')
    results['bad'] = dict(job_id='bad', intent_sha256=digest(intent),
        profile_id=intent['candidate_profiles'][0], cleanup_verified=True,
        status='COMPLETED', output=document(2))
    results['bad'][field] = value
    with pytest.raises(ValueError):
        journal.apply_model_result('task', 0, 'bad')
    assert journal.status('task')['stage'] == 'SRS'


def test_missing_research_port_cannot_be_replaced_by_model_citations(board):
    journal = board[0]
    complete(board, document(4))
    reopened = PlanningJournal(journal.path, journal.catalog)
    with pytest.raises(ValueError, match='port'):
        reopened.apply_research('task', 1, 'invented')
