"""In-process coordinator tests with real SQLite and controlled futures."""
from concurrent.futures import Future
from contextlib import contextmanager
from types import SimpleNamespace

from cochem_pipeline.catalog_runtime import CatalogController
from cochem_pipeline.admission import JointAdmission
from cochem_pipeline.catalog_journal import active_policy
from pipeline_tests.test_catalog_slots import prepared


def coordinator(tmp_path):
    store,baseline,authority=prepared(tmp_path)
    futures=[];custody=[]
    def submit(*args):
        f=Future();futures.append(f);return f
    @contextmanager
    def reader(policy,resolver):
        assert resolver(baseline.digest).digest==baseline.digest
        custody.append('held')
        try:yield authority
        finally:custody.append('closed')
    runtime=SimpleNamespace(store=store,admission=JointAdmission(store,None,capacity=4),
        ramdisk=object(),pool=SimpleNamespace(submit=submit),containment_id='c'*32,boot_id=123)
    control=CatalogController(runtime,reader)
    return control,store,baseline,authority,futures,custody


def test_publishes_only_after_fenced_completion_and_replay_never_runs_models(tmp_path):
    c,store,baseline,authority,futures,custody=coordinator(tmp_path)
    c.step(['slot6'],4)
    assert custody==['held'] and len(futures)==1
    with store._connection() as conn:assert active_policy(conn).digest==baseline.digest
    futures[0].set_result((True,True));c.step(['slot6'],4)
    assert c.status['status']=='PUBLISHED_IN_CALLER_TRANSACTION'
    assert custody==['held','closed']
    c.last_poll=0;c.step(['slot6'],4)
    assert c.status['status']=='ALREADY_PUBLISHED' and len(futures)==1
    store.close()


def test_unknown_cleanup_holds_slot_without_repeating_request(tmp_path):
    from cochem_pipeline.catalog_slots import occupancy
    c,store,baseline,authority,futures,custody=coordinator(tmp_path)
    c.step(['slot6'],4);futures[0].set_exception(RuntimeError('unknown failure'))
    c.step(['slot6'],4)
    assert c.status['status']=='HELD' and custody[-1]=='closed'
    with store._connection() as conn:
        assert occupancy(conn)==1 and active_policy(conn).digest==baseline.digest
    c.last_poll=0;c.step(['slot6'],4)
    assert len(futures)==1
    store.close()


def test_hardware_pause_prevents_probe_launch(tmp_path):
    c,store,baseline,authority,futures,custody=coordinator(tmp_path)
    c.step(['slot6'],0)
    assert not futures
    c.close();store.close()


def test_docker_warm_capacity_must_drain_before_native_probe(tmp_path):
    c,store,baseline,authority,futures,custody=coordinator(tmp_path)
    capacities=[]
    docker=SimpleNamespace(census=lambda:{'quarantined':False,'owned':4},set_capacity=capacities.append)
    c.runtime.admission.docker=docker
    c.step(['slot6'],4)
    assert not futures and c.runtime.admission.maintenance_requested.is_set()
    docker.census=lambda:{'quarantined':False,'owned':3}
    c.step(['slot6'],4)
    assert len(futures)==1 and capacities[-1]==3
    futures[0].set_result((False,True));c.step(['slot6'],4);store.close()


def test_shutdown_preserves_completed_probe_and_restart_publishes_without_reexecution(tmp_path):
    c,store,baseline,authority,futures,custody=coordinator(tmp_path)
    c.step(['slot6'],4);futures[0].set_result((True,True));c.close()
    restarted=CatalogController(c.runtime,c.reader)
    restarted.step(['slot6'],4)
    assert restarted.status['status']=='PUBLISHED_IN_CALLER_TRANSACTION'
    assert len(futures)==1
    store.close()


def test_new_protected_request_is_published_without_restarting_coordinator(tmp_path):
    from pipeline_tests.test_catalog_journal import change
    c,store,baseline,first,futures,custody=coordinator(tmp_path)
    c.step(['slot6'],4);futures[0].set_result((True,True));c.step(['slot6'],4)
    second=change(first.change.policy,3)[0]
    @contextmanager
    def reader(policy,resolver):
        assert policy.digest==first.change.policy.digest
        yield second
    c.reader=reader;c.last_poll=0
    c.step(['slot6'],4);assert len(futures)==2
    futures[1].set_result((True,True));c.step(['slot6'],4)
    assert c.status['policy_digest']==second.change.policy.digest
    with store._connection() as conn:assert active_policy(conn).digest==second.change.policy.digest
    c.close();store.close()


def test_scheduled_task_probe_owns_nonce_without_supervisor_launch_environment(tmp_path):
    c,store,baseline,authority,futures,custody=coordinator(tmp_path)
    c.runtime.containment_id=None
    c.step(['slot6'],4)
    assert len(futures)==1 and len(c.reservation['containment_id'])==32
    futures[0].set_result((False,True));c.step(['slot6'],4);store.close()


def test_executor_preserves_bound_native_evidence_after_cleanup(tmp_path,monkeypatch):
    import json
    import threading
    from dataclasses import dataclass
    from cochem_pipeline import worker,runtime as runtime_module
    c,store,baseline,authority,futures,custody=coordinator(tmp_path)
    c.step(['slot6'],4)
    private=tmp_path/'private'
    @dataclass
    class Config:
        routing:object=baseline
        timeout_seconds:int=120
        private_root:object=private
        workers:object=None
    c.runtime.config=Config(workers={'slot6':{'name':'fixture-worker'}})
    c.runtime.stop_event=threading.Event();c.runtime.last_capacity=4
    descriptor=SimpleNamespace(root=tmp_path,validate=lambda **kwargs:None)
    c.runtime.ramdisk=SimpleNamespace(workspace=lambda slot:descriptor)
    def execute(node,*args,**kwargs):
        assert kwargs.get('heartbeat',args[2])()  # controlled ordinary DB lease
        directory=private/'attempts'/node['attempt_id'];directory.mkdir(parents=True)
        receipt=dict(provider='gemini',requested_model='gemini-3.8-flash',requested_effort='low',
            reported_model='gemini-3.8-flash',native_reported_model='gemini-3.8-flash-low',
            reported_effort='low',worker_slot='slot6',subscription_verified=True,exit_code=0,inference_policy={})
        return {'ready':True},receipt
    monkeypatch.setattr(worker,'NativeRunner',lambda config:SimpleNamespace(run=execute))
    monkeypatch.setattr(runtime_module,'clear_ram_workspace',lambda descriptor:None)
    assert c._execute(authority.change.control_target,'slot6',c.reservation)==(True,True)
    evidence=json.loads((private/'attempts'/c.reservation['reservation_id']/'catalog-evidence.json').read_text())
    assert evidence['plan_digest']==authority.change.digest
    assert evidence['reservation']==c.reservation and evidence['cleanup_verified']
    assert len(evidence['output_sha256'])==64 and len(evidence['receipt_sha256'])==64
    futures[0].set_result((True,True));c.step(['slot6'],4);store.close()
