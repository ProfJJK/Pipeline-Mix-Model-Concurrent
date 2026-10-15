"""Inert acceptance receipts and SQLite CAS; never provider/host acceptance."""
from copy import deepcopy
from dataclasses import replace
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from cochem_pipeline import catalog_slots, catalog_journal
from cochem_pipeline.admission import JointAdmission
from cochem_pipeline.failures import ProviderFailure
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.store import JobStore
from cochem_pipeline.task_catalog_acceptance_428 import (
    prepare_request, decode_request, encoded, initialize, probe_authority, probe_node,
    record_result, publish, enabled_candidate, coverage,
    defer_held_target, run_acceptance, execution_bindings,
)
from pipeline_tests.test_task_catalog_428 import raw_task_catalog, binary_bindings


PINS={name:dict(provider_contract_sha256=str(index)*64,
              worker_profiles_sha256='f'*64,
              agent_contract_sha256='e'*64 if name=='gemini' else None)
      for index,name in enumerate(('codex','claude','gemini'),1)}


@pytest.fixture(autouse=True)
def no_children(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:pytest.fail('No child process is allowed'))


@pytest.fixture
def environment(tmp_path, raw_task_catalog, binary_bindings):
    policy=load_routing_policy({'policy_version':3})
    raw=prepare_request(policy,raw_task_catalog,binary_bindings,request_id='1'*32,
        execution_bindings=PINS,candidate_profile_ids=['argon-high','sonnet-max','luna-med'])
    data=encoded(raw)
    request=decode_request(data,policy,None,expected_sha256=hashlib.sha256(data).hexdigest())
    store=JobStore(tmp_path/'board.db',routing_policy=policy)
    with store._connection() as conn:
        conn.execute('PRAGMA synchronous=FULL');conn.execute('BEGIN IMMEDIATE')
        catalog_journal.initialize(conn,policy)
        initialize(conn)
        conn.commit()
    store.close()
    store=JobStore(store.path,routing_policy=policy,catalog_enabled=True)
    yield store,request,raw
    store.close()


def reserve(store,request,target):
    with store._write() as conn:
        return catalog_slots.reserve(conn,probe_authority(request,target),target,
            worker_slot='slot1',containment_id='c'*32,boot_id=123)


def receipt_for(request,target,token):
    node,details=probe_node(request,target,token)
    output={'ready':True}
    binding=request.plan.binary_bindings[target[0]]
    receipt=dict(provider=target[0],requested_model=target[1],requested_effort=target[2],
        reported_model=target[1],reported_effort=target[2],subscription_verified=True,exit_code=0,
        worker_slot=token['worker_slot'],execution_kind='native_cli',
        process_identity_source='owned_windows_process_handle',route_reservation_id=token['reservation_id'],
        output_sha256=hashlib.sha256(encoded(output)).hexdigest(),
        inference_policy=dict(reasoning_effort=dict(requested_profile=target[2],model=target[1],
            executable_sha256=binding['sha256'],version=binding['version'])))
    receipt.update({key:node[key] for key in ('job_id','workflow_id','attempt_id','fencing_token')})
    if target[0]=='gemini':receipt['native_reported_model']=target[1]+'-'+target[2]
    return output,receipt


def finish_all(store,request,defer=None):
    for target in request.plan.required_targets:
        token=reserve(store,request,target)
        output,receipt=receipt_for(request,target,token)
        with store._write() as conn:
            record_result(conn,request,target,token,output=output,receipt=receipt,
                binary_sha256=request.plan.binary_bindings[target[0]]['sha256'],cleanup_verified=True,
                availability=ProviderFailure('quota') if target==defer else None)


def test_publication_requires_exact_durable_native_evidence_and_is_atomic(environment,tmp_path,monkeypatch):
    from cochem_pipeline import task_catalog_acceptance_428 as module
    monkeypatch.setattr(module,'execution_bindings',lambda p,w:PINS)
    store,request,raw=environment
    with pytest.raises(ValueError,match='missing'),store._write() as conn:publish(conn,request)
    finish_all(store,request)
    with pytest.raises(RuntimeError),store._write() as conn:
        publish(conn,request)
        raise RuntimeError('inert transaction rollback')
    with store._connection() as conn:
        assert catalog_journal.active_task_catalog(conn) is None
        assert conn.execute('SELECT count(*) FROM pipeline_catalog_probes WHERE consumed_at IS NOT NULL').fetchone()[0]==0
    with store._write() as conn:
        result=publish(conn,request)
        raw_catalog=encoded(result['catalog'])
        config=enabled_candidate(conn,request,{'routing':request.plan.policy.as_dict(),'unchanged':'keep','max_execution_slots':4},
            catalog_path=tmp_path/'accepted.json',catalog_bytes=raw_catalog)
        assert config['task_planning']['catalog_sha256']==hashlib.sha256(raw_catalog).hexdigest()
        assert config['unchanged']=='keep'
    with store._write() as conn:assert publish(conn,request)['status']=='ALREADY_PUBLISHED'


@pytest.mark.parametrize('fault',['binary','effort','version','fence','slug','output','process'])
def test_native_receipt_must_bind_binary_effort_and_owned_process(environment,fault):
    store,request,_=environment
    target=('gemini','gemini-4-argon','high')
    token=reserve(store,request,target)
    output,receipt=receipt_for(request,target,token)
    binary=request.plan.binary_bindings['gemini']['sha256']
    if fault=='binary':binary='f'*64
    elif fault=='effort':receipt['requested_effort']='low'
    elif fault=='version':receipt['inference_policy']['reasoning_effort']['version']='unreviewed'
    elif fault=='fence':receipt['fencing_token']+=1
    elif fault=='slug':receipt['native_reported_model']='different-model-high'
    elif fault=='output':output={'ready':False}
    else:receipt['process_identity_source']='model-asserted'
    with pytest.raises(ValueError),store._write() as conn:
        record_result(conn,request,target,token,output=output,receipt=receipt,
                      binary_sha256=binary,cleanup_verified=True)
    with store._connection() as conn:
        assert catalog_slots.occupancy(conn)==1
        assert conn.execute('SELECT count(*) FROM pipeline_task_probe_evidence').fetchone()[0]==0


def test_quota_deferral_keeps_five_ranked_options_and_original_floors(environment):
    store,request,raw=environment
    request=partial_request(request,raw)
    deferred=('claude','claude-sonnet-5-5','max')
    finish_all(store,request,defer=deferred)
    with store._write() as conn:catalog=publish(conn,request)['catalog']
    assert catalog['models']['sonnet-max']['native_acceptance']=='AVAILABILITY_WAIT'
    assert 'sonnet-max' not in catalog['accepted_profile_ids']
    for tag,spec in catalog['task_types'].items():
        for tier,row in spec['tiers'].items():
            before=raw['catalog']['task_types'][tag]['tiers'][tier]
            assert row['floor']==before['floor']
            assert [item['model_id'] for item in row['ranked_options']]==[item['model_id'] for item in before['ranked_options']]
            assert len(row['ranked_options'])==5
            assert 'sonnet-max' not in row['choices']
    assert any(row['status']=='HELD_COVERAGE' for row in coverage(catalog))


@pytest.mark.parametrize('category',['auth','configuration','code','compatibility','timeout'])
def test_non_availability_failures_never_become_accepted_or_deferred(environment,category):
    store,request,_=environment
    target=request.plan.control_target
    token=reserve(store,request,target)
    with pytest.raises(ValueError,match='typed temporary'),store._write() as conn:
        record_result(conn,request,target,token,binary_sha256=request.plan.binary_bindings[target[0]]['sha256'],
                      cleanup_verified=True,availability=ProviderFailure(category))


def test_cleanup_unknown_never_releases_shared_seat_or_publishes(environment):
    store,request,_=environment
    target=request.plan.control_target
    token=reserve(store,request,target)
    with store._write() as conn:
        result=record_result(conn,request,target,token,binary_sha256=request.plan.binary_bindings[target[0]]['sha256'],
                             cleanup_verified=False)
        assert result['status']=='CLEANUP_UNVERIFIED'
        assert catalog_slots.occupancy(conn)==1
    with pytest.raises(ValueError),store._write() as conn:publish(conn,request)


def test_proposal_pin_and_active_generation_must_match(environment):
    store,request,raw=environment
    wrong=deepcopy(raw);wrong['activation_authorized']=True
    data=encoded(wrong)
    with pytest.raises(ValueError,match='claims its own authority'):
        decode_request(data,request.plan.policy,None,expected_sha256=hashlib.sha256(data).hexdigest())
    with pytest.raises(ValueError,match='reviewed pin'):
        decode_request(encoded(raw),request.plan.policy,None,expected_sha256='f'*64)
    finish_all(store,request)
    with pytest.raises(ValueError),store._write() as conn:publish(conn,replace(request,proposal_sha256='f'*64))


def test_configuration_cannot_enable_before_publication(environment,tmp_path):
    store,request,_=environment
    with pytest.raises(ValueError,match='before exact catalog'),store._write() as conn:
        enabled_candidate(conn,request,{'routing':request.plan.policy.as_dict()},
                          catalog_path=tmp_path/'x.json',catalog_bytes=b'{}')


def test_existing_tier_targets_also_require_fresh_exact_binary_evidence(environment):
    _,request,_=environment
    assert ('codex','gpt-6-luna','medium') in request.plan.required_targets
    assert len(request.plan.required_targets)==len(set(request.plan.required_targets))


def partial_request(request,raw):
    proposal=prepare_request(request.plan.policy,raw['catalog'],raw['binary_bindings'],
        request_id=request.request_id,execution_bindings=PINS,
        candidate_profile_ids=['argon-high','sonnet-max','opus-max','luna-med'],allow_partial_publication=True)
    data=encoded(proposal)
    return decode_request(data,request.plan.policy,None,expected_sha256=hashlib.sha256(data).hexdigest())


def test_partial_publication_uses_actual_pool_hold_without_fake_native_receipts(environment):
    store,request,raw=environment
    request=partial_request(request,raw)
    failed=('claude','claude-opus-5-5','max')
    skipped=('claude','claude-sonnet-5-5','max')
    for target in request.plan.required_targets:
        with store._write() as conn:
            if defer_held_target(conn,request,target):
                assert target==skipped
                continue
        token=reserve(store,request,target)
        output,receipt=receipt_for(request,target,token)
        with store._write() as conn:
            record_result(conn,request,target,token,output=output,receipt=receipt,
                binary_sha256=request.plan.binary_bindings[target[0]]['sha256'],cleanup_verified=True,
                availability=ProviderFailure('quota',120) if target==failed else None)
    with store._write() as conn:
        result=publish(conn,request)
        assert catalog_slots.occupancy(conn)==0
        assert conn.execute('SELECT count(*) FROM pipeline_catalog_probes').fetchone()[0]==len(request.plan.required_targets)-1
        assert conn.execute('SELECT count(*) FROM pipeline_task_catalog_holds').fetchone()[0]==1
    catalog=result['catalog']
    assert catalog['models']['sonnet-max']['availability_evidence']=='AVAILABILITY_WAIT_UNTESTED'
    assert catalog['models']['opus-max']['availability_evidence']=='AVAILABILITY_WAIT'
    assert 'sonnet-max' not in catalog['accepted_profile_ids']
    assert 'opus-max' not in catalog['accepted_profile_ids']
    assert catalog['models']['luna-med']['native_acceptance']=='ACCEPTED'
    assert any(row['status']=='HELD_COVERAGE' for row in coverage(catalog))
    with store._write() as conn:assert publish(conn,request)['status']=='ALREADY_PUBLISHED'


def test_partial_policy_is_explicit_and_auth_holds_do_not_become_availability(environment):
    from cochem_pipeline.routing_store import set_hold
    store,request,raw=environment
    target=request.plan.control_target
    pool=request.plan.policy.as_dict()['provider_limits'][target[0]]['quota_pool']
    with store._write() as conn:
        set_hold(conn,'pool',pool,600,'quota')
        assert defer_held_target(conn,request,target) is False
        set_hold(conn,'pool',pool,600,'auth')
        assert defer_held_target(conn,partial_request(request,raw),target) is False
        assert conn.execute('SELECT count(*) FROM pipeline_task_catalog_holds').fetchone()[0]==0


@dataclass
class InertConfig:
    providers: dict
    workers: dict
    routing: object
    timeout_seconds: int = 60


def inert_runtime(store,request,tmp_path,monkeypatch,*,failure=None):
    from cochem_pipeline import windows, native_effort, worker, runtime, task_catalog_acceptance_428 as module
    monkeypatch.setattr(windows,'require_system',lambda:None)
    monkeypatch.setattr(module,'execution_bindings',lambda p,w:request.execution_bindings)
    binaries=request.plan.binary_bindings
    monkeypatch.setattr(native_effort,'verified_executable_sha256',
        lambda path:next(x['sha256'] for x in binaries.values() if x['executable']==path))
    workers={f'slot{i}':dict(name=f'inert-worker-{i}') for i in range(1,7)}
    calls=[];clears=[]
    class Runner:
        def __init__(self,config):self.config=config
        def run(self,node,slot,context,heartbeat,**kwargs):
            assert heartbeat() and context==''
            target=tuple(node['route'][key] for key in ('provider','model','reasoning_effort'))
            calls.append(target)
            if failure and target[0]=='claude':raise failure
            token=dict(worker_slot=slot,reservation_id=node['route']['reservation_id'],fencing_token=node['fencing_token'])
            output,receipt=receipt_for(request,target,token)
            receipt['worker_account']=workers[slot]['name']
            return output,receipt
    monkeypatch.setattr(worker,'NativeRunner',Runner)
    monkeypatch.setattr(runtime,'clear_ram_workspace',lambda descriptor:clears.append(descriptor.root))
    descriptor=SimpleNamespace(root=tmp_path,validate=lambda **k:None)
    rt=SimpleNamespace(store=store,config=InertConfig(
        {p:dict(executable=x['executable']) for p,x in binaries.items()},workers,request.plan.policy),
        ramdisk=SimpleNamespace(workspace=lambda slot:descriptor),stop_event=threading.Event(),
        boot_id=123,catalog_containment_id='a'*32,admission=JointAdmission(store,None,4))
    return rt,calls,clears


def test_coordinator_uses_shared_seats_skips_verified_pool_hold_and_reports_coverage(environment,tmp_path,monkeypatch):
    store,request,raw=environment
    request=partial_request(request,raw)
    rt,calls,clears=inert_runtime(store,request,tmp_path,monkeypatch,failure=ProviderFailure('quota',120))
    result=run_acceptance(rt,request)
    assert result['catalog_published'] is True and result['all_routes_usable'] is False
    assert result['coverage_holds']>0
    assert sum(target[0]=='claude' for target in calls)==1
    assert len(clears)==len(calls)
    with store._connection() as conn:assert catalog_slots.occupancy(conn)==0
    replay=run_acceptance(rt,request)
    assert replay['status']=='ALREADY_PUBLISHED'
    assert len(clears)==len(calls)


@pytest.mark.parametrize('fault',['cleanup','configuration','unknown'])
def test_coordinator_failure_never_publishes_or_retries(environment,tmp_path,monkeypatch,fault):
    from cochem_pipeline.worker import WorkerCleanupError
    store,request,_=environment
    failure={'cleanup':WorkerCleanupError('inert cleanup failure'),
             'configuration':ProviderFailure('configuration'),'unknown':RuntimeError('inert unknown')}[fault]
    rt,calls,clears=inert_runtime(store,request,tmp_path,monkeypatch,failure=failure)
    with pytest.raises(type(failure)):run_acceptance(rt,request)
    assert len(calls)==1
    with store._connection() as conn:
        assert catalog_journal.active_task_catalog(conn) is None
        assert catalog_slots.occupancy(conn)==(0 if fault=='configuration' else 1)


def test_coordinator_requires_system_before_any_work(environment,monkeypatch):
    from cochem_pipeline import windows
    monkeypatch.setattr(windows,'require_system',lambda:(_ for _ in ()).throw(ValueError('not SYSTEM')))
    with pytest.raises(ValueError,match='not SYSTEM'):run_acceptance(None,environment[1])


def valid_providers(binary_bindings):
    from cochem_pipeline.agy_agent_guard import RELATIVES
    providers={name:dict(executable=spec['executable']) for name,spec in binary_bindings.items()}
    providers['gemini'].update(
        agent_definition=dict(name='cochem-inference-only',sha256='a'*64,bytes=10,relative_paths=list(RELATIVES)),
        inference_only=dict(arguments=['--agent','cochem-inference-only'],version_arguments=['--version'],
            executable_sha256=binary_bindings['gemini']['sha256'],version=binary_bindings['gemini']['version'],
            capability_reference='inert test evidence',disables_tools=True,disables_mcp=True,
            disables_hooks=True,disables_subagents=True,disables_model_fallback=True))
    return providers


def test_exact_worker_and_agent_contracts_are_pinned(binary_bindings):
    providers=valid_providers(binary_bindings)
    workers={f'slot{i}':dict(name=f'inert-{i}') for i in range(1,7)}
    baseline=execution_bindings(providers,workers)
    workers['slot1']['name']='different-inert-profile'
    assert execution_bindings(providers,workers)!=baseline
    providers['gemini']['agent_definition']['sha256']='b'*64
    assert execution_bindings(providers,workers)['gemini']['agent_contract_sha256']!=baseline['gemini']['agent_contract_sha256']


def test_fresh_preparer_pins_bytes_and_never_overwrites(tmp_path,raw_task_catalog,binary_bindings,monkeypatch):
    import importlib
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    helper=importlib.import_module('prepare_task_catalog_428')
    config=dict(routing=load_routing_policy({'policy_version':3}).as_dict(),max_execution_slots=4,
                providers=valid_providers(binary_bindings),workers={f'slot{i}':dict(name=f'inert-{i}') for i in range(1,7)})
    destination=tmp_path/'fresh'
    result=helper.prepare_task_catalog_release(destination,configuration=config,catalog=raw_task_catalog,
        binary_bindings=binary_bindings,request_id='c'*32,source_commit='d'*40,allow_partial_publication=True)
    data=(destination/'task-catalog-request.json').read_bytes()
    assert hashlib.sha256(data).hexdigest()==result['request_sha256']
    assert result['native_probes_executed']==0 and result['planning_enabled'] is False
    assert json.loads(data)['allow_partial_publication'] is True
    with pytest.raises(ValueError,match='fresh ordinary'):
        helper.prepare_task_catalog_release(destination,configuration=config,catalog=raw_task_catalog,
            binary_bindings=binary_bindings,request_id='c'*32,source_commit='d'*40)
    assert (destination/'task-catalog-request.json').read_bytes()==data


def test_windows_custody_directory_handles_participate_in_sharing_checks():
    from cochem_pipeline.catalog_authority import _WindowsCustody
    calls=[]
    kernel=SimpleNamespace(CreateFileW=lambda *args:(calls.append(args),123)[1])
    backend=_WindowsCustody(SimpleNamespace(_api=lambda:{'kernel32':kernel}))
    assert backend.acquire(Path('inert-directory'),True)==123
    assert calls[0][1]==0x20001 and calls[0][2]==3  # read/write share, no DELETE.


def test_release_selection_preserves_unaccepted_rankings(tmp_path,raw_task_catalog,binary_bindings,monkeypatch):
    import importlib
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    helper=importlib.import_module('prepare_task_catalog_428')
    config=dict(routing=load_routing_policy({'policy_version':3}).as_dict(),max_execution_slots=4,
                providers=valid_providers(binary_bindings),workers={f'slot{i}':dict(name=f'inert-{i}') for i in range(1,7)})
    destination=tmp_path/'selected'
    result=helper.prepare_task_catalog_release(destination,configuration=config,catalog=raw_task_catalog,
        binary_bindings=binary_bindings,request_id='c'*32,source_commit='d'*40,
        allow_partial_publication=True,candidate_profile_ids=['sonnet-max','luna-med'])
    request=json.loads((destination/'task-catalog-request.json').read_bytes())
    assert set(request['candidate_profile_ids'])=={'sonnet-max','luna-med'}
    assert result['candidate_profile_ids']==request['candidate_profile_ids']
    assert request['catalog']==raw_task_catalog
    assert request['activation_authorized'] is False
    assert result['native_probes_executed']==0


def test_partial_publication_is_not_implicit_after_actual_quota_failure(environment):
    store,request,_=environment
    finish_all(store,request,defer=('claude','claude-sonnet-5-5','max'))
    with pytest.raises(ValueError,match='deferral requires'),store._write() as conn:
        publish(conn,request)
    with store._connection() as conn:assert catalog_journal.active_task_catalog(conn) is None


def test_all_quota_blocked_never_publishes_an_empty_catalog(environment):
    from cochem_pipeline.routing_store import set_hold
    store,request,raw=environment
    request=partial_request(request,raw)
    # One actual cleaned native quota result; all remaining targets are genuine
    # scoped hold observations, without any fabricated native success.
    target=request.plan.required_targets[0]
    token=reserve(store,request,target)
    with store._write() as conn:
        record_result(conn,request,target,token,
            binary_sha256=request.plan.binary_bindings[target[0]]['sha256'],cleanup_verified=True,
            availability=ProviderFailure('quota',120))
        for pool in request.plan.policy.as_dict()['quota_pool_limits']:
            set_hold(conn,'pool',pool,120,'quota')
        for other in request.plan.required_targets[1:]:assert defer_held_target(conn,request,other)
    with pytest.raises(ValueError,match='at least one accepted'),store._write() as conn:publish(conn,request)
    with store._connection() as conn:assert catalog_journal.active_task_catalog(conn) is None


def test_expired_or_modified_controller_hold_blocks_new_publication(environment):
    from cochem_pipeline.routing_store import set_hold
    store,request,raw=environment
    request=partial_request(request,raw)
    skipped=('claude','claude-sonnet-5-5','max')
    for target in request.plan.required_targets:
        if target==skipped:
            with store._write() as conn:
                set_hold(conn,'model',':'.join(target),120,'busy')
                assert defer_held_target(conn,request,target)
            continue
        token=reserve(store,request,target);output,receipt=receipt_for(request,target,token)
        with store._write() as conn:
            record_result(conn,request,target,token,output=output,receipt=receipt,
                binary_sha256=request.plan.binary_bindings[target[0]]['sha256'],cleanup_verified=True)
    with store._write() as conn:
        conn.execute('UPDATE pipeline_route_holds SET until_at=0')
    with pytest.raises(ValueError,match='no longer current'),store._write() as conn:publish(conn,request)


def test_configuration_drift_cannot_enable_after_publication(environment,tmp_path):
    store,request,_=environment
    finish_all(store,request)
    with store._write() as conn:
        result=publish(conn,request)
        with pytest.raises(ValueError,match='provider/profile'):
            enabled_candidate(conn,request,dict(routing=request.plan.policy.as_dict(),max_execution_slots=3),
                              catalog_path=tmp_path/'catalog.json',catalog_bytes=encoded(result['catalog']))
