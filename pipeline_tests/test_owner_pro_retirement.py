"""Owner-withdrawn model preparation; all providers and host actions are inert."""
import copy
import hashlib
from pathlib import Path
import sys

import pytest

from cochem_pipeline.catalog_activation import compile_change
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.routing_catalog import default_catalog, retire_owner_gemini_pro, validate_catalog
from cochem_pipeline.native_acceptance_plan import build_plan, digest
from pipeline_tests.test_native_acceptance_plan import complete_candidate

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
import r6_native_retirement as helper


def test_retirement_preserves_old_capture_and_only_removes_pro_at_five_and_six():
    before=default_catalog();saved=copy.deepcopy(before)
    catalog=retire_owner_gemini_pro(before)
    assert before==saved
    assert catalog['schema']=='cochem-routing-catalog/2'
    current=load_routing_policy({'policy_version':3,'catalog':before})
    change=compile_change(current,catalog,expected_policy_digest=current.digest)
    assert change.changed_targets==()
    for tier in range(1,11):
        assert catalog['tiers'][str(tier)]==before['tiers'][str(tier)][:2 if tier in (5,6) else 3]
    assert not change.policy.is_enabled(current.candidates(5)[2])
    assert len(change.policy.candidates(5))==len(change.policy.candidates(6))==2
    assert current.as_dict()['catalog']==before
    for key,value in current.as_dict().items():
        if key not in ('catalog','tiers','model_limits'):assert change.policy.as_dict()[key]==value


def test_published_owner_catalog_document_matches_the_approved_retirement():
    import json
    path=Path(__file__).parents[1]/'docs/routing/4.2.7-routing-v4.owner-catalog.json'
    assert json.loads(path.read_text())==retire_owner_gemini_pro(default_catalog())


@pytest.mark.parametrize('mutation',['old_two','empty','one','four','duplicate','unknown_schema'])
def test_versioned_catalog_does_not_enable_arbitrary_missing_or_duplicate_floor(mutation):
    catalog=retire_owner_gemini_pro(default_catalog())
    if mutation=='old_two':catalog['schema']='cochem-routing-catalog/1'
    if mutation=='empty':catalog['tiers']['5']=[]
    if mutation=='one':catalog['tiers']['5'].pop()
    if mutation=='four':catalog['tiers']['1'].append(copy.deepcopy(catalog['tiers']['1'][0]))
    if mutation=='duplicate':catalog['tiers']['5'][1]=copy.deepcopy(catalog['tiers']['5'][0])
    if mutation=='unknown_schema':catalog['schema']='cochem-routing-catalog/3'
    with pytest.raises(ValueError):validate_catalog(catalog)


def test_native_retirement_filters_one_target_and_keeps_all_remaining_exact_assignments(tmp_path):
    original=build_plan(complete_candidate(tmp_path));saved=copy.deepcopy(original)
    filtered=helper.retire_plan(original)
    assert original==saved
    assert len(filtered['targets'])==26
    assert filtered['targets']==[row for row in original['targets'] if row['model']!='gemini-3.1-pro']
    assert filtered['owner_retirement']['original_plan_sha256']==original['plan_sha256']
    assert filtered['owner_retirement']['retired_model_jobs_executed']==0
    assert filtered['owner_retirement']['replacement_selected'] is False
    assert filtered['plan_sha256']==digest({k:v for k,v in filtered.items() if k!='plan_sha256'})


@pytest.mark.parametrize('mutation',['count','position','effort','provider','template','capacity'])
def test_native_retirement_refuses_a_changed_plan(tmp_path,mutation):
    plan=build_plan(complete_candidate(tmp_path))
    pro=next(row for row in plan['targets'] if row['model']=='gemini-3.1-pro')
    if mutation=='count':plan['targets'].pop()
    if mutation=='position':pro['route_positions'][0]['tier']=4
    if mutation=='effort':pro['reasoning_effort']='medium'
    if mutation=='provider':pro['provider']='codex'
    if mutation=='template':plan['preparation_status']='BINDING_INPUTS_REQUIRED'
    if mutation=='capacity':plan['max_execution_slots']=6
    with pytest.raises(ValueError):helper.retire_plan(plan)


def test_one_shot_amendment_restores_callbacks_and_never_changes_installed_candidate(tmp_path,monkeypatch):
    from cochem_pipeline import r6_native_acceptance as native, r6_host_acceptance as host
    raw=complete_candidate(tmp_path);saved=copy.deepcopy(raw);events=[]
    def original_run(*args,**kwargs):
        plan=native.build_plan(raw);events.append(plan)
        return dict(count=26,targets=plan['targets'])
    def host_run(phase,output,manifest,candidate):
        assert phase=='native' and manifest==helper.MANIFEST and candidate==helper.CANDIDATE
        value=native.run_probes(None,None,None,None)
        assert value['owner_retirement']['helper_sha256']==hashlib.sha256(Path(helper.__file__).read_bytes()).hexdigest()
    monkeypatch.setattr(native,'run_probes',original_run)
    monkeypatch.setattr(host,'run',host_run)
    monkeypatch.setattr(sys,'argv',['helper','--output',str(tmp_path),'--manifest-hash',helper.MANIFEST,'--candidate-hash',helper.CANDIDATE])
    original_plan=native.build_plan
    helper.main()
    assert native.run_probes is original_run and native.build_plan is original_plan
    assert len(events)==1 and raw==saved


def test_one_shot_failure_restores_callbacks_without_continuing(tmp_path,monkeypatch):
    from cochem_pipeline import r6_native_acceptance as native, r6_host_acceptance as host
    original_plan, original_run = native.build_plan, native.run_probes
    def host_run(*args):
        assert native.build_plan is not original_plan
        raise ValueError('fixture SYSTEM custody refusal')
    monkeypatch.setattr(host,'run',host_run)
    monkeypatch.setattr(sys,'argv',['helper','--output',str(tmp_path),'--manifest-hash',helper.MANIFEST,'--candidate-hash',helper.CANDIDATE])
    with pytest.raises(ValueError,match='custody refusal'):helper.main()
    assert native.build_plan is original_plan and native.run_probes is original_run


@pytest.mark.parametrize('tier', [5, 6])
@pytest.mark.parametrize('historical_capture', [False, True])
def test_medium_tiers_back_off_after_two_choices_and_preserve_historical_authority(tmp_path,tier,historical_capture):
    import time
    from cochem_pipeline.store import JobStore
    from pipeline_tests.test_routing_store import fail
    original=load_routing_policy({'policy_version':3,'backoff_base_seconds':.025,
        'backoff_max_seconds':.05,'backoff_jitter_fraction':0,'failure_cooldowns':{'quota':0}})
    revised=compile_change(original,retire_owner_gemini_pro(default_catalog()),expected_policy_digest=original.digest).policy
    captured=original if historical_capture else revised
    store=JobStore(tmp_path/'routing.db',routing_policy=captured)
    workflow=store.submit('Document schema',[f'REQ-{i}' for i in range(4 if tier==5 else 12)],1)
    job_id=next(row['job_id'] for row in workflow['jobs'] if row['kind']=='MANIFEST_GENERATOR')
    assert store.get(job_id)['routing']['score_details']['score']==tier
    snapshot=store.get(job_id)['routing_policy']
    store.close()
    reopened=JobStore(tmp_path/'routing.db',routing_policy=revised)
    for index in range(2):
        node=reopened.claim('fixture-owner',worker_slot='slot1')
        assert node['job_id']==job_id and node['route']['candidate_index']==index
        assert node['route']['model']!='gemini-3.1-pro'
        assert fail(reopened,node,'quota')
    assert reopened.claim('exhausted-choices',worker_slot='slot1') is None
    waiting=reopened.get(job_id)
    assert waiting['routing']['state']=='WAITING' and waiting['routing']['cycle']==1
    assert waiting['routing']['dispatches']==2 and waiting['routing']['failure_count']==0
    assert waiting['routing_policy']==snapshot
    assert len(waiting['routing']['candidates'])==(3 if historical_capture else 2)
    time.sleep(.04)
    next_cycle=reopened.claim('after-backoff',worker_slot='slot1')
    assert next_cycle['route']['candidate_index']==0 and next_cycle['route']['cycle']==1
    assert next_cycle['route']['policy_digest']==captured.digest
    assert next_cycle['route']['admission_policy_digest']==revised.digest
    reopened.close()
