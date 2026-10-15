"""Controller/SQLite integration only; no provider or child process launches."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from cochem_pipeline.planning_gateway import PlanningGateway, scoped_policy
from cochem_pipeline.planning_journal import PlanningJournal
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.store import JobStore, output_digest
from cochem_pipeline.worker import node_prompt
from pipeline_tests.test_workflow_428 import document
from pipeline_tests.task_catalog_fixtures import accepted_planning_store


@pytest.fixture
def gateway(tmp_path):
    store, catalog = accepted_planning_store(tmp_path/'jobs.db')
    journal = PlanningJournal(tmp_path/'planning.db', catalog, flash_context_limit=100000)
    journal.create('task', 'Write a small useful note')
    bridge = PlanningGateway(journal, store)
    journal.model_result = bridge.model_result
    yield bridge
    store.close()


def accepted_receipt(node, output):
    route=node['route']
    return dict(provider=route['provider'], requested_model=route['model'],
        requested_effort=route['reasoning_effort'], selected_route=route,
        route_reservation_id=route['reservation_id'], attempt_id=node['attempt_id'],
        fencing_token=node['fencing_token'], worker_slot=node['worker_slot'],
        job_id=node['job_id'], workflow_id=node['workflow_id'],pid=1,exit_code=0,
        session_id='inert-fixture',output_sha256=output_digest(output))


def test_planning_intent_captures_assessed_tier_on_existing_board(gateway):
    job=gateway.submit('task')
    assert gateway.submit('task')['job_id']==job['job_id']
    assert job['kind']=='TASK_PLAN'
    assert job['routing']['score_details']['score']==4
    assert 1<=len(job['routing']['candidates'])<=5
    prompt=node_prompt(job,'')
    assert 'Concrete implementation plan' in prompt
    assert 'task_catalog' not in prompt and 'candidate_profiles' not in prompt
    claimed=gateway.store.claim('fixture',worker_slot='slot1',allowed_kinds=['TASK_PLAN'])
    assert claimed['route']['score']==4
    output=document(2)
    result=gateway.store.complete(claimed['job_id'],claimed['attempt_id'],claimed['fencing_token'],
                                  output,accepted_receipt(claimed,output))
    assert result['status']=='COMPLETED'
    assert gateway.store.workflow(job['workflow_id'])['status']=='COMPLETED'
    # A bare successful output is not enough for importing into the planner.
    assert gateway.model_result(job['job_id']) is None


def test_invalid_stage_output_cannot_be_committed(gateway):
    gateway.submit('task')
    job=gateway.store.claim('fixture',worker_slot='slot1',allowed_kinds=['TASK_PLAN'])
    with pytest.raises(ValueError):
        gateway.store.complete(job['job_id'],job['attempt_id'],job['fencing_token'],
                               {'ready':True},accepted_receipt(job,{'ready':True}))
    assert gateway.store.get(job['job_id'])['status']=='IN_PROGRESS'


def test_stale_or_rewritten_intent_cannot_change_existing_job(gateway):
    job=gateway.submit('task')
    intent=deepcopy(job['payload']['planning_intent'])
    intent['catalog_sha256']='0'*64
    with pytest.raises(ValueError):
        scoped_policy(gateway.store.routing_policy,intent,job['payload']['task_catalog'])


def test_scoped_catalog_rejects_cross_tier_candidate_substitution(gateway):
    policy=scoped_policy(load_routing_policy(gateway.store.routing_policy),
                         gateway.journal.intent('task'), gateway.journal.catalog)
    policy['catalog']['tiers']['10']=list(reversed(policy['catalog']['tiers']['10']))
    with pytest.raises(ValueError):
        load_routing_policy(policy)


def test_journal_import_waits_for_exact_cleanup_evidence(gateway):
    gateway.submit('task')
    job=gateway.store.claim('fixture',worker_slot='slot1',allowed_kinds=['TASK_PLAN'],requires_cleanup=True)
    output=document(2)
    gateway.store.clear_execution_quarantine(job['job_id'],job['attempt_id'],job['fencing_token'])
    gateway.store.complete(job['job_id'],job['attempt_id'],job['fencing_token'],output,accepted_receipt(job,output))
    state=gateway.journal.apply_model_result('task',0,job['job_id'])
    assert state['stage']=='READY'
    assert len(state['accepted_planning_jobs'])==1
    assert gateway.journal.apply_model_result('task',0,job['job_id'])==state


def test_existing_schema_migration_preserves_captured_jobs_and_policy(tmp_path,monkeypatch):
    from cochem_pipeline import store as store_module
    path=tmp_path/'legacy.db'
    with monkeypatch.context() as patch:
        patch.setattr(store_module,'SCHEMA',store_module.SCHEMA.replace(",'TASK_PLAN'))", "))"))
        legacy=JobStore(path,routing_policy=load_routing_policy({'policy_version':3}))
        old=legacy.submit('Preserve a previous workflow',['R1'],1)
        legacy.close()
    current=JobStore(path,routing_policy=load_routing_policy({'policy_version':3}))
    try:
        saved=current.workflow(old['workflow_id'])
        assert saved['jobs']==old['jobs']
        with current._connection() as conn:
            sql=conn.execute("SELECT sql FROM sqlite_master WHERE name='pipeline_jobs'").fetchone()[0]
            assert "'TASK_PLAN'" in sql
            assert not conn.execute('PRAGMA foreign_key_check').fetchall()
    finally:
        current.close()
