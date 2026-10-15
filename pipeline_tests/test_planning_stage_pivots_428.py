"""Planning-stage and simple promotion tests use SQLite and inert receipts only."""
import json

import pytest

from cochem_pipeline.attempt_runtime_428 import AttemptAccountingRuntime
from cochem_pipeline.failure_dossier_428 import FailureDossierStore
from cochem_pipeline.pivot_runtime_428 import PivotRuntime
from cochem_pipeline.planning_gateway import PlanningGateway, validate_stage_output
from cochem_pipeline.planning_outcomes_428 import PlanningOutcomeRuntime
from cochem_pipeline.planning_pivots_428 import PlanningPivotRuntime
from cochem_pipeline.research_evidence_428 import ResearchEvidenceStore
from cochem_pipeline.research_runtime_428 import ResearchRuntime
from cochem_pipeline.task_execution_428 import SimpleTaskExecutionRuntime
from cochem_pipeline.workflow_428 import AttemptLedger
from pipeline_tests.test_planning_runtime_428 import pump, finish_model
from pipeline_tests.test_planning_gateway_428 import accepted_receipt
from pipeline_tests.test_workflow_428 import document


def setup_bridge(pump, tmp_path):
    ledger = AttemptLedger(tmp_path/'attempts.db')
    accountant = AttemptAccountingRuntime(ledger, store=pump.store)
    research = ResearchRuntime(ResearchEvidenceStore(tmp_path/'research.db'), None)
    outcomes = PlanningOutcomeRuntime(pump.journal, pump.store, accountant, research_runtime=research,
                                     dossier_store=FailureDossierStore(ledger))
    runtime = PivotRuntime(ledger, pump.journal.catalog, dossier_store=outcomes.dossier_store)
    return ledger, outcomes, PlanningPivotRuntime(pump.journal, pump.store, outcomes, runtime)


def boundary(pump, outcomes):
    for _ in range(10):
        job = pump.store.claim('inert', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
        assert job
        pump.store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
        pump.store.fail(job['job_id'], job['attempt_id'], job['fencing_token'], 'inert check failed', retry=True, category='code')
    outcomes.reconcile_task('task')
    record = outcomes.status('task')[-1]
    intent = json.loads(outcomes.research_runtime.queue_status(record['research_id'])['intent_json'])
    evidence = outcomes.research_runtime.evidence_store
    for channel in ('internet', 'wiki_rag', 'papers'):
        evidence.record_channel(record['research_id'], channel, query=intent['query'], status='no_results', sources=[])
    evidence.publish(record['research_id'])
    outcomes.reconcile_task('task')
    return job, record


def review(pump, bridge, complexity=2):
    bridge.step('task')
    job = pump.store.claim('inert-review', worker_slot='slot2', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    assert job and job['payload']['planning_intent']['stage'] == 'PIVOT_REVIEW'
    output = dict(strategy='pivot', assessment=dict(complexity=complexity, task_types=['GEN-DEFAULT'],
        rationale='Reevaluate exact failed requirements'), root_cause_synthesis='Earlier plan omitted a required boundary',
        hypotheses=['Missing requirement mapping'], approach='Map each supplied requirement explicitly before implementation',
        fracture_reason='')
    pump.store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
    pump.store.complete(job['job_id'], job['attempt_id'], job['fencing_token'], output, accepted_receipt(job, output))
    bridge.step('task')
    return job


def test_srs_pivot_new_generation_retains_floor_and_lineage(pump, tmp_path):
    ledger, outcomes, bridge = setup_bridge(pump, tmp_path)
    old = pump.gateway.submit('task')
    _, record = boundary(pump, outcomes)
    review(pump, bridge)
    job = pump.gateway.submit('task')
    assert job['job_id'] != old['job_id']
    assert job['payload']['planning_intent']['complexity'] == 5
    assert outcomes.lineage_for_job('task', job['payload']) == record['lineage_root']
    assert ledger.status(record['lineage_root'])['failures'] == 10
    claimed = pump.store.claim('inert-next', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    with pytest.raises(ValueError, match='retained pivot reasoning floor'):
        validate_stage_output(claimed['payload'], document(2), claimed['route'])
    output = document(5)
    pump.store.clear_execution_quarantine(claimed['job_id'], claimed['attempt_id'], claimed['fencing_token'])
    pump.store.complete(claimed['job_id'], claimed['attempt_id'], claimed['fencing_token'], output,
                        accepted_receipt(claimed, output))
    pump.journal.apply_model_result('task', pump.journal.status('task')['journal_version'], claimed['job_id'])
    assert pump.journal.status('task')['stage'] == 'RESEARCH'


@pytest.mark.parametrize('new_complexity, expected', [(2, 'READY'), (4, 'REVISING_SRS'), (8, 'REVISING_SRS')])
def test_simple_pivot_promotes_scope_without_resetting_lineage(pump, tmp_path, new_complexity, expected):
    finish_model(pump, document(2))
    ledger, outcomes, bridge = setup_bridge(pump, tmp_path)
    execution = SimpleTaskExecutionRuntime(pump.journal, pump.store)
    old = execution.materialize('task')
    _, record = boundary(pump, outcomes)
    review(pump, bridge, complexity=new_complexity)
    state = pump.journal.status('task')
    assert state['stage'] == expected
    assert state['pivot_reasoning_floor'] == max(3, new_complexity)
    assert ledger.status('task')['failures'] == 10
    assert pump.store.get(old['job_id'])['status'] == 'BLOCKED'
    if expected == 'REVISING_SRS':
        job = pump.gateway.submit('task')
        assert outcomes.lineage_for_job('task', job['payload']) == 'task'
        assert job['payload']['planning_intent']['complexity'] == new_complexity
        if new_complexity == 8:
            claim = pump.store.claim('inert-next', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
            output = document(8)
            pump.store.clear_execution_quarantine(claim['job_id'], claim['attempt_id'], claim['fencing_token'])
            pump.store.complete(claim['job_id'], claim['attempt_id'], claim['fencing_token'], output, accepted_receipt(claim, output))
            pump.journal.apply_model_result('task', state['journal_version'], claim['job_id'])
            assert pump.journal.status('task')['stage'] == 'OWNER_APPROVAL'
            assert pump.journal.status('task')['approval'] is None
