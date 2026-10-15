"""Whole-task promotion using only temporary journals and inert board receipts."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from cochem_pipeline.attempt_runtime_428 import AttemptAccountingRuntime
from cochem_pipeline.failure_dossier_428 import FailureDossierStore
from cochem_pipeline.fracture_promotion_428 import begin_promotion
from cochem_pipeline.microtask_board_428 import MicrotaskBoardRuntime
from cochem_pipeline.pivot_runtime_428 import PivotRuntime
from cochem_pipeline.planning_fractures_428 import fracture_contract
from cochem_pipeline.planning_gateway import PlanningGateway
from cochem_pipeline.planning_journal import PlanningJournal
from cochem_pipeline.planning_outcomes_428 import PlanningOutcomeRuntime
from cochem_pipeline.planning_pivots_428 import PlanningPivotRuntime
from cochem_pipeline.research_evidence_428 import ResearchEvidenceStore
from cochem_pipeline.research_runtime_428 import ResearchRuntime
from cochem_pipeline.task_execution_428 import SimpleTaskExecutionRuntime
from cochem_pipeline.task_routing import digest
from cochem_pipeline.workflow_428 import AttemptLedger
from pipeline_tests.task_catalog_fixtures import accepted_planning_store
from pipeline_tests.test_planning_gateway_428 import accepted_receipt
from pipeline_tests.test_workflow_428 import document, research, wbs


@pytest.fixture
def env(tmp_path):
    store, catalog = accepted_planning_store(tmp_path/'jobs.db')
    journal = PlanningJournal(tmp_path/'planning.db', catalog, flash_context_limit=100000)
    ledger = AttemptLedger(tmp_path/'attempts.db')
    accounting = AttemptAccountingRuntime(ledger, store=store)
    gateway = PlanningGateway(journal, store, attempt_accounting=accounting)
    journal.model_result = gateway.model_result
    research_runtime = ResearchRuntime(ResearchEvidenceStore(tmp_path/'research.db'), None)
    outcomes = PlanningOutcomeRuntime(journal, store, accounting, research_runtime=research_runtime,
                                     dossier_store=FailureDossierStore(ledger))
    pivot = PivotRuntime(ledger, catalog, dossier_store=outcomes.dossier_store)
    bridge = PlanningPivotRuntime(journal, store, outcomes, pivot)
    board = MicrotaskBoardRuntime(journal, store, attempt_ledger=accounting)
    board.fracture_planning = bridge.fractures
    board.fracture_runtime = bridge.fractures.fracture_runtime
    journal.create('task', 'Produce the exact requested output')
    yield SimpleNamespace(store=store, journal=journal, ledger=ledger, accounting=accounting,
        gateway=gateway, outcomes=outcomes, bridge=bridge, board=board)
    store.close()


def finish(env, stage, output=None, *, import_result=False):
    job = env.store.claim('inert-promotion', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    assert job is not None, env.store.routing_status()
    assert job['payload']['planning_intent']['stage'] == stage
    if output is None:
        output = fracture_contract(job['payload'])
    env.store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
    env.store.complete(job['job_id'], job['attempt_id'], job['fencing_token'], output, accepted_receipt(job, output))
    env.outcomes.reconcile_task('task')
    if import_result:
        env.journal.apply_model_result('task', env.journal.status('task')['journal_version'], job['job_id'])
    return env.store.get(job['job_id'])


def promote(env, stage='SIMPLE_EXECUTION', *, classification=3):
    env.gateway.submit('task')
    if stage == 'SIMPLE_EXECUTION':
        finish(env, 'SRS', document(2), import_result=True)
        execution = SimpleTaskExecutionRuntime(env.journal, env.store, attempt_accounting=env.accounting)
        execution.materialize('task')
    for _ in range(10):
        job = env.store.claim('inert-failure', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
        assert job is not None
        assert job['payload']['planning_intent']['stage'] == stage
        env.store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
        env.store.fail(job['job_id'], job['attempt_id'], job['fencing_token'], 'Required behavior failed', retry=True, category='code')
        env.outcomes.reconcile_task('task')
    boundary = env.outcomes.status('task')[-1]
    request = json.loads(env.outcomes.research_runtime.queue_status(boundary['research_id'])['intent_json'])
    evidence = env.outcomes.research_runtime.evidence_store
    for channel in ('internet', 'wiki_rag', 'papers'):
        evidence.record_channel(boundary['research_id'], channel, query=request['query'], status='no_results', sources=[])
    evidence.publish(boundary['research_id'])
    env.outcomes.reconcile_task('task')
    env.bridge.step('task')
    review = finish(env, 'PIVOT_REVIEW', dict(strategy='fracture',
        assessment=dict(complexity=classification, task_types=['COD-TERM'], rationale='Decompose reviewed scope'),
        root_cause_synthesis='Repeated failure of required behavior', hypotheses=['Interface coupling'],
        approach='Create narrow parts with explicit assembly', fracture_reason='Split tightly coupled deliverable'))
    env.bridge.step('task')
    return env.store.get(job['job_id']), boundary, review


def finish_srs_gates(env):
    tier = env.journal.status('task')['fracture_promotion']['minimum_complexity']
    env.gateway.submit('task')
    finish(env, 'REVISING_SRS', document(tier), import_result=True)
    state = env.journal.status('task')
    if state['stage'] == 'OWNER_APPROVAL':
        env.journal.owner_receipt = lambda _: dict(task_id='task', srs_sha256=state['srs_sha256'],
            actor_kind='human_owner', decision='approved')
        env.journal.apply_owner_approval('task', state['journal_version'], 'owner-fixture')
    intent = env.journal.intent('task')
    assert intent['action'] == 'controller_research'
    env.journal.search_result = lambda _: dict(intent_sha256=digest(intent), channels=research())
    env.journal.apply_research('task', env.journal.status('task')['journal_version'], 'research-fixture')
    env.gateway.submit('task')
    finish(env, 'PLAN_REVIEW', dict(accepted=True, findings=[], suggestions=[], clarifications=[]), import_result=True)
    env.gateway.submit('task')
    finish(env, 'WBS', dict(wbs=wbs()), import_result=True)
    assert env.journal.status('task')['stage'] == 'FRACTURE_PROMOTION_READY'


@pytest.mark.parametrize('stage', ['SIMPLE_EXECUTION', 'SRS'])
def test_whole_failure_passes_srs_gates_then_uses_only_registered_shared_root(env, stage):
    old, boundary, _ = promote(env, stage)
    assert env.journal.status('task')['stage'] == 'REVISING_SRS'
    assert env.outcomes.status('task')[-1]['status'] == 'WAITING_FOR_FRACTURE_PROMOTION'
    assert env.ledger.status(boundary['lineage_root'])['failures'] == 10
    assert 'microtask_node' not in old['payload']
    finish_srs_gates(env)
    env.bridge.step('task')
    plan = finish(env, 'FRACTURE_PLAN')
    scope = plan['payload']['planning_intent']['task']['fracture_scope']
    assert scope['deliverables'] == sorted({path for row in wbs() for path in row['deliverables']})
    env.bridge.step('task')
    finish(env, 'FRACTURE_REVIEW')
    env.bridge.step('task')
    state = env.journal.status('task')
    assert state['stage'] == 'MICROTASKS_READY'
    assert env.ledger.status(boundary['lineage_root'])['failures'] == 10
    assert env.ledger.status(boundary['lineage_root'])['stage'] == 'READY'
    generation, nodes, _, _, _ = env.board._compile('task')
    assert len(nodes) == 4 and all(node['lineage_kind'] == 'FAILURE_FRACTURE' for node in nodes)
    assert all('fracture_join' not in node for node in nodes)
    assert all(env.ledger.status(node['attempt_lineage_id'])['root'] == boundary['lineage_root'] for node in nodes)
    status = env.board.materialize('task')
    assert sum(node['status'] == 'DISPATCHED' for node in status['nodes']) == 2
    assert env.store.get(old['job_id'])['status'] == 'BLOCKED'
    reopened = PlanningPivotRuntime(env.journal, env.store, env.outcomes, env.bridge.pivot_runtime)
    reopened.step('task')
    assert env.board._compile('task')[0] == generation
    assert env.ledger.status(boundary['lineage_root'])['failures'] == 10


def test_promoted_high_complexity_needs_owner_approval_without_reset(env):
    _, boundary, _ = promote(env, classification=8)
    env.gateway.submit('task')
    finish(env, 'REVISING_SRS', document(8), import_result=True)
    env.bridge.step('task')
    assert env.journal.intent('task')['action'] == 'owner_review'
    assert env.ledger.status(boundary['lineage_root'])['stage'] == 'PIVOT_RESEARCH'
    assert env.store.claim('inert', worker_slot='slot1', allowed_kinds=['TASK_PLAN']) is None


@pytest.mark.parametrize('mutation', ['requirement', 'criterion', 'floor'])
def test_srs_revision_cannot_drop_original_scope_or_floor(env, mutation):
    promote(env)
    env.gateway.submit('task')
    output = document(3)
    if mutation == 'requirement': output['requirements'][0]['text'] = 'Different requirement'
    if mutation == 'criterion': output['release_criteria'] = ['Different criterion']
    if mutation == 'floor': output['assessment']['complexity'] = 1
    with pytest.raises(ValueError, match='requirement|floor'):
        finish(env, 'REVISING_SRS', output)


def test_cancellation_during_promotion_never_creates_fracture(env):
    _, boundary, _ = promote(env)
    env.journal.cancel('task')
    env.bridge.step('task')
    assert env.bridge.fractures.fracture_runtime.accepted_record(boundary['lineage_root'], 10) is None
    assert env.ledger.status(boundary['lineage_root'])['stage'] == 'PIVOT_RESEARCH'


def test_whole_promotion_recovers_graph_commit_before_journal_projection(env, monkeypatch):
    _, boundary, _ = promote(env)
    finish_srs_gates(env)
    env.bridge.step('task')
    finish(env, 'FRACTURE_PLAN')
    env.bridge.step('task')
    finish(env, 'FRACTURE_REVIEW')
    runtime = env.bridge.fractures.fracture_runtime
    original = runtime.execute_fracture
    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('Crash after durable graph commit')
    monkeypatch.setattr(runtime, 'execute_fracture', interrupted)
    with pytest.raises(RuntimeError, match='durable graph'):
        env.bridge.step('task')
    assert env.journal.status('task')['stage'] == 'FRACTURE_PROMOTION_READY'
    monkeypatch.setattr(runtime, 'execute_fracture', original)
    env.bridge.step('task')
    assert env.journal.status('task')['stage'] == 'MICROTASKS_READY'
    assert len(env.board._compile('task')[1]) == 4
    assert env.ledger.status(boundary['lineage_root'])['failures'] == 10
    with env.journal._write() as conn:
        row = env.journal._read(conn, 'task')
        state = json.loads(row['state_json'])
        state['microtasks'][0]['deliverables'] = ['forged.txt']
        state['microtasks_sha256'] = digest(state['microtasks'])
        conn.execute('UPDATE planning428_tasks SET state_json=? WHERE task_id=?', (json.dumps(state), 'task'))
    with pytest.raises(ValueError, match='registered task capture'):
        env.board.materialize('task')
