"""Default lifecycle connections; in-process SQLite and inert provider receipts only."""
from types import SimpleNamespace

import pytest

from cochem_pipeline.completion_audit_428 import CompletionAuditRuntime
from cochem_pipeline.planning_runtime import PlanningController
from pipeline_tests.test_planning_runtime_428 import pump, poll
from pipeline_tests.test_task_execution_428 import simple_env, _advance_to_ready, _valid_execution_output
from pipeline_tests.test_planning_gateway_428 import accepted_receipt


def test_default_runtime_shares_real_microtask_accountant(pump, tmp_path):
    config = SimpleNamespace(private_root=tmp_path, token_file=None,
        task_planning=SimpleNamespace(read_catalog=lambda: pump.journal.catalog, flash_context_limit=100000))
    controller = PlanningController.from_runtime(SimpleNamespace(config=config, store=pump.store))
    assert controller.release_runtime.board.attempt_accounting is controller.attempt_runtime
    assert controller.release_runtime.board.attempt_ledger is controller.attempt_ledger
    with pytest.raises(RuntimeError, match='authority is not configured'):
        controller.repair_queue.verify_reservation({})
    with pytest.raises(RuntimeError, match='authority is not configured'):
        controller.repair_queue.verify_commit('commit', 'tests')


def test_prepare_project_snapshot_precedes_journal_submission(pump):
    observations = []
    def prepare(task_id, project_id):
        observations.append((task_id, project_id, pump.journal.has_task(task_id)))
    pump.artifact_runtime = SimpleNamespace(prepare_task=prepare)
    pump.submit('Bounded artifact task', 'prepared', project_id='actual-repository')
    assert observations == [('prepared', 'actual-repository', False)]


def test_failed_snapshot_prevents_intake(pump):
    def denied(*args):
        raise ValueError('Snapshot differs')
    pump.artifact_runtime = SimpleNamespace(prepare_task=denied)
    with pytest.raises(ValueError, match='Snapshot differs'):
        pump.submit('Bounded artifact task', 'prepared', project_id='actual-repository')
    assert not pump.journal.has_task('prepared')


def test_cancellation_uses_board_status_and_cancels_batch_only_jobs(pump):
    poll(pump)
    job = pump.gateway.submit('task')
    pump.release_runtime = SimpleNamespace(board=SimpleNamespace(board_status=lambda _task: {
        'nodes': [], 'batches': [{'job_id': job['job_id']}]}))
    # Root progress may no longer name a microtask/batch; board IDs remain authoritative.
    pump._record('task', pump.journal.status('task')['journal_version'], 'WAITING_ON_DEPENDENCIES')
    result = pump.cancel('task')
    assert result['controller']['status'] == 'CANCELLED'
    assert pump.store.get(job['job_id'])['status'] == 'FAILED'


def test_failed_cancellation_is_durable_and_reconciles_after_restart(pump, monkeypatch):
    poll(pump)
    original = pump.store.cancel_workflow
    def interrupted(_workflow):
        raise OSError('private failure')
    monkeypatch.setattr(pump.store, 'cancel_workflow', interrupted)
    result = pump.cancel('task')
    assert result['controller']['status'] == 'CANCELLATION_PENDING'
    monkeypatch.setattr(pump.store, 'cancel_workflow', original)
    reopened = PlanningController(pump.journal, pump.store, clock=lambda: 1000.)
    reopened.step()
    assert reopened.task_status('task')['controller']['status'] == 'CANCELLED'
    with pump.journal._write() as conn:
        assert conn.execute('SELECT count(*) FROM planning428_cancel_targets WHERE done=0').fetchone()[0] == 0


def test_completed_simple_task_enqueues_once_without_claiming_audit_pass(simple_env, tmp_path):
    controller, execution, journal, store = simple_env
    doc = _advance_to_ready(controller)
    job = execution.materialize('task-simple-01')
    claimed = store.claim('inert-worker', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    assert claimed['job_id'] == job['job_id']
    output = _valid_execution_output(doc)
    store.clear_execution_quarantine(job['job_id'], claimed['attempt_id'], claimed['fencing_token'])
    store.complete(job['job_id'], claimed['attempt_id'], claimed['fencing_token'], output, accepted_receipt(claimed, output))
    execution.step_ready_task('task-simple-01')
    audit = CompletionAuditRuntime(tmp_path/'audit.db', journal.catalog, None, sample_basis_points=10000)
    controller.audit_runtime = audit
    assert controller._enqueue_completion_audits('task-simple-01') == 'ENQUEUED'
    controller._enqueue_completion_audits('task-simple-01')
    projection = controller.task_status('task-simple-01')['completion_audit']
    assert len(projection) == 1
    assert projection[0]['status'] == 'QUEUED'
    record = audit.get_spotcheck(projection[0]['audit_key'])
    assert record['disposition'] is None
    with audit._write() as conn:
        assert conn.execute('SELECT count(*) FROM audit428_spotchecks').fetchone()[0] == 1
