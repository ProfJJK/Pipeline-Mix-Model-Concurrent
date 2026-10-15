"""Receipt-backed accounting with real SQLite stores; no native child processes."""
import json

import pytest

from cochem_pipeline.attempt_runtime_428 import AttemptAccountingRuntime
from cochem_pipeline.failure_dossier_428 import FailureDossierStore
from cochem_pipeline.planning_outcomes_428 import PlanningOutcomeRuntime
from cochem_pipeline.output_contracts import prepare_output_contract
from cochem_pipeline.research_evidence_428 import ResearchEvidenceStore
from cochem_pipeline.research_runtime_428 import ResearchRuntime
from cochem_pipeline.task_routing import digest
from cochem_pipeline.workflow_428 import AttemptLedger
from pipeline_tests.test_planning_runtime_428 import pump, poll
from pipeline_tests.test_planning_gateway_428 import accepted_receipt
from pipeline_tests.test_workflow_428 import document


@pytest.fixture
def outcomes(pump, tmp_path):
    ledger = AttemptLedger(tmp_path/'attempts.db')
    accounting = AttemptAccountingRuntime(ledger, store=pump.store)
    research = ResearchRuntime(ResearchEvidenceStore(tmp_path/'research.db'), None)
    runtime = PlanningOutcomeRuntime(pump.journal, pump.store, accounting,
        research_runtime=research, dossier_store=FailureDossierStore(ledger))
    return pump, runtime


def claim(pump):
    poll(pump)
    job = pump.store.claim('inert-test', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    assert job is not None
    return job


def fail(pump, job, category='code', cleanup=True):
    if cleanup:
        pump.store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
    pump.store.fail(job['job_id'], job['attempt_id'], job['fencing_token'], 'inert verification failed',
                    retry=True, category=category)


def test_records_all_missed_native_attempts_once_after_restart(outcomes):
    pump, runtime = outcomes
    for _ in range(3):
        job = claim(pump)
        fail(pump, job)
    assert runtime.reconcile_task('task') == 3
    root = runtime.lineage_for_job('task', job['payload'])
    assert runtime.accounting.ledger.status(root)['failures'] == 3
    reopened = PlanningOutcomeRuntime(pump.journal, pump.store, runtime.accounting)
    assert reopened.reconcile_task('task') == 0
    assert runtime.accounting.ledger.status(root)['failures'] == 3


@pytest.mark.parametrize('category', ['auth', 'quota', 'resource', 'provider', 'compatibility'])
def test_availability_never_consumes_quality_budget(outcomes, category):
    pump, runtime = outcomes
    job = claim(pump)
    fail(pump, job, category)
    assert runtime.reconcile_task('task') == 1
    root = runtime.lineage_for_job('task', job['payload'])
    assert runtime.accounting.ledger.status(root)['failures'] == 0
    with runtime.accounting.ledger._write() as conn:
        assert conn.execute('SELECT staged_outcome FROM attempt428_outbox').fetchone()[0] == 'availability'


def test_format_correction_preserves_zero_quality_without_faking_availability(outcomes):
    pump, runtime = outcomes
    job = claim(pump)
    pump.store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
    assert pump.store.correct_output_format(job['job_id'], job['attempt_id'], job['fencing_token'], {
        'schema': 'cochem-output-format-feedback/1', 'contract_sha256': prepare_output_contract(job)['contract_sha256'],
        'issues': [{'path': '$.result', 'code': 'missing_field'}]})
    assert runtime.reconcile_task('task') == 1
    with runtime.accounting.ledger._write() as conn:
        assert conn.execute('SELECT count(*) FROM task428_attempts').fetchone()[0] == 0
    with pump.journal._write() as conn:
        assert conn.execute('SELECT disposition FROM planning428_observed_outcomes').fetchone()[0] == 'FORMAT_CORRECTION_NOT_QUALITY'


def test_no_count_before_cleanup_then_idempotent_charge(outcomes):
    pump, runtime = outcomes
    job = claim(pump)
    fail(pump, job, cleanup=False)
    assert runtime.reconcile_task('task') == 0
    pump.store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
    assert runtime.reconcile_task('task') == 1
    assert runtime.reconcile_task('task') == 0


def test_completion_requires_exact_native_receipt_and_creates_success(outcomes):
    pump, runtime = outcomes
    job = claim(pump)
    output = document(2)
    pump.store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
    pump.store.complete(job['job_id'], job['attempt_id'], job['fencing_token'], output, accepted_receipt(job, output))
    assert runtime.reconcile_task('task') == 1
    with runtime.accounting.ledger._write() as conn:
        assert conn.execute('SELECT staged_outcome FROM attempt428_outbox').fetchone()[0] == 'success'


def test_tenth_failure_schedules_fresh_research_and_keeps_boundary_held(outcomes):
    pump, runtime = outcomes
    for _ in range(10):
        job = claim(pump)
        fail(pump, job)
    assert runtime.reconcile_task('task') == 10
    boundary = runtime.status('task')[0]
    assert boundary['boundary'] == 10
    assert boundary['status'] == 'WAITING_FOR_FAILURE_RESEARCH'
    assert boundary['research_id']
    root = boundary['lineage_root']
    assert runtime.accounting.ledger.status(root)['stage'] == 'PIVOT_RESEARCH'
    evidence_store = runtime.research_runtime.evidence_store
    req = json.loads(runtime.research_runtime.queue_status(boundary['research_id'])['intent_json'])
    for channel in ('internet', 'wiki_rag', 'papers'):
        evidence_store.record_channel(boundary['research_id'], channel, query=req['query'],
                                      status='no_results', sources=[])
    evidence_store.publish(boundary['research_id'])
    runtime.reconcile_task('task')
    boundary = runtime.status('task')[0]
    assert boundary['status'] == 'WAITING_FOR_PIVOT_REVIEW'
    dossier = runtime.dossier_store.get_dossier(root, 10)
    assert len(dossier['failure_records']) == 10
    assert dossier['research_complete'] is True
    assert runtime.accounting.ledger.status(root)['stage'] == 'PIVOT_RESEARCH'
    with pytest.raises(ValueError, match='held'):
        runtime.accounting.ledger.start(root, root, 'another-model')


def test_recovers_crash_between_ledger_start_and_outbox_insert(outcomes):
    pump, runtime = outcomes
    job = claim(pump)
    fail(pump, job)
    root = runtime.lineage_for_job('task', job['payload'])
    runtime.accounting.ensure_lineage(root, complexity=job['payload']['planning_intent']['complexity'])
    catalog = job['payload']['task_catalog']['models']
    profile = next(v for v in catalog.values() if v['model'] == job['route']['model'] and v['effort'] == job['route']['reasoning_effort'])
    fkey = runtime.accounting._fence_key(job['job_id'], job['attempt_id'], job['fencing_token'])
    runtime.accounting.ledger.start(root, root, profile['family'],
        lease_id='board428-' + digest({'fence_key': fkey})[:40])
    assert runtime.reconcile_task('task') == 1
    assert runtime.accounting.ledger.status(root)['failures'] == 1
    with runtime.accounting.ledger._write() as conn:
        assert conn.execute('SELECT count(*) FROM task428_attempts').fetchone()[0] == 1


def test_unknown_release_is_visible_hold_not_assumed_code_failure(outcomes):
    pump, runtime = outcomes
    job = claim(pump)
    pump.store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
    pump.store.cancel_workflow(job['workflow_id'], error='Unknown infrastructure interruption')
    assert runtime.reconcile_task('task') == 1
    with pump.journal._write() as conn:
        assert conn.execute('SELECT disposition FROM planning428_observed_outcomes').fetchone()[0] == 'UNCLASSIFIED_RELEASE_HOLD'
    assert len(runtime.unresolved_releases('task')) == 1


def test_bounded_poll_reconciles_remainder_without_losing_attempts(outcomes):
    pump, runtime = outcomes
    for _ in range(3):
        job = claim(pump)
        fail(pump, job)
    assert runtime.reconcile_task('task', limit=1) == 1
    assert runtime.reconcile_task('task', limit=1) == 1
    assert runtime.reconcile_task('task', limit=1) == 1
    assert runtime.reconcile_task('task', limit=1) == 0


def test_swarm_aggregate_is_not_charged_again():
    assert PlanningOutcomeRuntime.lineage_for_job('task', {
        'planning_intent': {'task_id': 'task', 'stage': 'MICROTASK_SWARM_BATCH'}}) is None
