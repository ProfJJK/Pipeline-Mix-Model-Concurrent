"""Real board/journal/HTTP boundaries; all model results are inert fixtures."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import MethodType

import pytest

from cochem_pipeline.planning_journal import PlanningJournal
from cochem_pipeline.planning_runtime import PlanningConfig, PlanningController
from cochem_pipeline.runtime import Runtime
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.store import JobStore
from cochem_pipeline.task_routing import digest
from pipeline_tests.test_config import config_document, write_config
from pipeline_tests.test_planning_gateway_428 import accepted_receipt
from pipeline_tests.test_service import endpoint, request
from pipeline_tests.test_workflow_428 import document, research, wbs, microtasks
from pipeline_tests.task_catalog_fixtures import accepted_planning_store


@pytest.fixture
def pump(tmp_path):
    store, catalog = accepted_planning_store(tmp_path/'jobs.db')
    journal = PlanningJournal(tmp_path/'planning.db', catalog, flash_context_limit=100000)
    clock = [100.]
    controller = PlanningController(journal, store, clock=lambda: clock[0])
    controller.test_clock = clock
    controller.submit('Produce the specified deliverable', 'task')
    yield controller
    store.close()


def poll(pump):
    pump.test_clock[0] += 2
    pump.step()


def finish_model(pump, output):
    poll(pump)
    job = pump.store.claim('inert-test', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    assert job is not None, (pump.task_status('task')['controller'], pump.store.routing_status())
    pump.store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
    pump.store.complete(job['job_id'], job['attempt_id'], job['fencing_token'], output, accepted_receipt(job, output))
    poll(pump)
    return pump.journal.status('task')


def test_pump_submits_once_and_imports_after_restart(pump):
    poll(pump)
    poll(pump)
    job = pump.store.claim('inert-test', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    output = document(2)
    pump.store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
    pump.store.complete(job['job_id'], job['attempt_id'], job['fencing_token'], output, accepted_receipt(job, output))
    reopened = PlanningController(PlanningJournal(pump.journal.path, pump.journal.catalog), pump.store,
                                  clock=lambda: 200.)
    reopened.step()
    assert reopened.journal.status('task')['stage'] == 'READY'
    reopened.step()
    status = reopened.task_status('task')
    assert status['controller']['status'] == 'PLAN_READY_EXECUTION_PENDING'
    assert status['deliverable_completed'] is False
    with pump.store._connection() as conn:
        assert conn.execute("SELECT count(*) FROM pipeline_jobs WHERE kind='TASK_PLAN'").fetchone()[0] == 1


def test_completed_board_record_without_cleanup_does_not_advance(pump):
    poll(pump)
    job = pump.store.claim('inert-test', worker_slot='slot1', allowed_kinds=['TASK_PLAN'])
    output = document(2)
    pump.store.complete(job['job_id'], job['attempt_id'], job['fencing_token'], output, accepted_receipt(job, output))
    poll(pump)
    status = pump.task_status('task')
    assert status['task']['stage'] == 'SRS'
    assert status['controller']['status'] == 'WAITING_FOR_NATIVE_CLEANUP'


def test_pump_progresses_whole_planning_chain_using_separate_research_evidence(pump):
    finish_model(pump, document(4))
    poll(pump)
    status = pump.task_status('task')
    assert status['controller']['status'] == 'WAITING_FOR_RESEARCH'
    assert status['task']['stage'] == 'RESEARCH'
    search_id = status['controller']['research_id']
    intent = pump.journal.intent('task')
    receipts = {search_id: dict(intent_sha256=digest(intent), channels=research())}
    pump.journal.search_result = receipts.get
    pump.test_clock[0] += 31
    pump.step()
    assert pump.journal.status('task')['stage'] == 'PLAN_REVIEW'
    finish_model(pump, dict(accepted=True, findings=[], suggestions=[], clarifications=[]))
    finish_model(pump, {'wbs': wbs()})
    finish_model(pump, {'microtasks': microtasks()})
    state = finish_model(pump, {'assessments': [dict(id=row['id'], complexity=row['complexity'],
        task_types=row['task_types'], rationale='Actual deliverable reviewed') for row in microtasks()]})
    assert state['stage'] == 'MICROTASKS_READY'
    assert len(state['accepted_planning_jobs']) == 5
    assert not pump.task_status('task')['deliverable_completed']


def test_owner_gate_survives_polls_and_does_not_emit_a_model_job(pump):
    finish_model(pump, document(8))
    poll(pump)
    assert pump.task_status('task')['controller']['status'] == 'WAITING_FOR_OWNER_APPROVAL'
    pump.test_clock[0] += 31
    pump.step()
    assert pump.journal.status('task')['approval'] is None
    assert pump.store.claim('inert-test', worker_slot='slot1', allowed_kinds=['TASK_PLAN']) is None


def test_quota_does_not_duplicate_planning_job_or_consume_quality_budget(pump):
    poll(pump)
    job = pump.store.claim('inert-test', worker_slot='slot1', allowed_kinds=['TASK_PLAN'], requires_cleanup=True)
    pump.store.clear_execution_quarantine(job['job_id'], job['attempt_id'], job['fencing_token'])
    pump.store.fail(job['job_id'], job['attempt_id'], job['fencing_token'], 'quota fixture',
                    retry=True, category='quota', retry_after_seconds=60)
    poll(pump)
    saved = pump.store.get(job['job_id'])
    assert saved['routing']['failure_count'] == 0
    assert pump.task_status('task')['controller']['job_id'] == job['job_id']


def test_failed_job_stays_held_without_fresh_retry_budget(pump):
    poll(pump)
    job = pump.store.claim('inert-test', worker_slot='slot1', allowed_kinds=['TASK_PLAN'])
    pump.store.fail(job['job_id'], job['attempt_id'], job['fencing_token'], 'fixture stop', retry=False)
    poll(pump)
    assert pump.task_status('task')['controller']['status'] == 'PLANNING_JOB_HELD'
    pump.test_clock[0] += 61
    pump.step()
    with pump.store._connection() as conn:
        assert conn.execute("SELECT count(*) FROM pipeline_jobs WHERE kind='TASK_PLAN'").fetchone()[0] == 1


def test_bounded_rotation_and_error_isolation(pump, monkeypatch):
    pump.submit('Second objective', 'second')
    original = pump.gateway.submit
    def broken(task_id):
        if task_id == 'second':
            raise ValueError('Private raw provider output must not be exposed')
        return original(task_id)
    monkeypatch.setattr(pump.gateway, 'submit', broken)
    assert pump.step(1) == 1
    assert pump.step(1) == 1
    assert pump.task_status('second')['controller']['status'] == 'PLANNING_ERROR'
    assert 'Private' not in json.dumps(pump.task_status('second'))
    assert pump.task_status('task')['controller']['status'] == 'WAITING_FOR_BOARD'
    assert pump.step() == 0
    for limit in (True, 0, 33):
        with pytest.raises(ValueError):
            pump.step(limit)


def test_scheduler_reports_planning_error_without_interrupting_other_work(pump, monkeypatch):
    runtime = Runtime.__new__(Runtime)
    runtime.task_planning, runtime.components = pump, {}
    monkeypatch.setattr(pump, 'step', lambda: (_ for _ in ()).throw(OSError('private storage')))
    runtime._planning_maintenance()
    assert runtime.components['task_planning']['state'] == 'held'
    assert runtime.components['task_planning']['error_type'] == 'OSError'


def test_runtime_maintenance_connects_planning_to_existing_board(pump):
    runtime = Runtime.__new__(Runtime)
    runtime.task_planning, runtime.components = pump, {}
    runtime._planning_maintenance()
    assert pump.task_status('task')['controller']['status'] == 'WAITING_FOR_BOARD'
    evidence = runtime.components['task_planning']['evidence']
    assert evidence['tasks'] == 1 and evidence['states'] == {'WAITING_FOR_BOARD':1}
    assert evidence['execution_materialization'] == 'NOT_CONNECTED'
    assert not pump.store.active_jobs()


def test_intake_api_is_authenticated_and_cannot_set_route_or_grant_approval(endpoint, pump):
    runtime = endpoint.controller
    runtime.task_planning = pump
    runtime.submit_task = MethodType(Runtime.submit_task, runtime)
    runtime.task_status = MethodType(Runtime.task_status, runtime)
    auth = 'Bearer ' + endpoint.token
    assert request(endpoint, 'POST', '/tasks/submit', {'objective':'Unauthorized'})[0] == 401
    assert request(endpoint, 'GET', '/tasks/status/task')[0] == 401
    code, response = request(endpoint, 'POST', '/tasks/submit',
        {'objective':'User objective', 'task_id':'http-task'}, authorization=auth)
    assert code == 202 and response['task']['stage'] == 'SRS'
    assert request(endpoint, 'GET', '/tasks/status/http-task', authorization=auth)[0] == 200
    for field in ('complexity', 'catalog', 'model', 'approved', 'actor_kind'):
        assert request(endpoint, 'POST', '/tasks/submit',
            {'objective':'Wrong authority', field:True}, authorization=auth)[0] == 400
    assert request(endpoint, 'POST', '/tasks/approve', {'task_id':'task'}, authorization=auth)[0] == 404


def test_planning_defaults_off_and_requires_four_slots_and_v3(tmp_path):
    from cochem_pipeline.config import load_config
    raw = config_document(tmp_path)
    assert load_config(write_config(tmp_path, raw)).task_planning is None
    raw['task_planning'] = dict(catalog_file=str(tmp_path/'accepted.json'), catalog_sha256='a'*64)
    raw['routing'] = {'policy_version':3}
    assert load_config(write_config(tmp_path, raw)).task_planning.catalog_sha256 == 'a'*64
    for change in ({'routing':{'policy_version':2}}, {'max_execution_slots':3}):
        with pytest.raises(ValueError, match='four shared'):
            load_config(write_config(tmp_path, raw | change))


def test_candidate_cannot_activate_and_exact_file_pin_is_required(tmp_path, monkeypatch, pump):
    from cochem_pipeline import windows
    checked = []
    monkeypatch.setattr(windows, 'validate_code_path', checked.append)
    path = tmp_path/'catalog.json'
    candidate = deepcopy(pump.journal.catalog)
    candidate['host_accepted'] = False
    path.write_bytes(json.dumps(candidate).encode())
    config = PlanningConfig(path, hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match='host-accepted'):
        config.read_catalog()
    candidate['host_accepted'] = True  # Explicit inert protected-installation fixture.
    path.write_bytes(json.dumps(candidate).encode())
    with pytest.raises(ValueError, match='installation pin'):
        config.read_catalog()
    config = PlanningConfig(path, hashlib.sha256(path.read_bytes()).hexdigest())
    assert config.read_catalog()['host_accepted'] is True
    assert checked == [path, path, path]


@pytest.mark.parametrize('value', [False, {}, {'catalog_file':'relative', 'catalog_sha256':'a'*64},
    {'catalog_file':'C:/accepted.json', 'catalog_sha256':'x'},
    {'catalog_file':'C:/accepted.json', 'catalog_sha256':'a'*64, 'flash_context_limit':True}])
def test_invalid_planning_configuration_fails_closed(value):
    with pytest.raises(ValueError):
        PlanningConfig.from_dict(value)
