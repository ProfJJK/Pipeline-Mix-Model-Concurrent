"""Independent repair admission fixtures; no repair agent or host mutation."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from cochem_pipeline.repair_queue_428 import RepairQueue, sample_completion, repair_paths
from cochem_pipeline.task_routing import digest


@pytest.fixture
def setup(tmp_path):
    catalog = json.loads((Path(__file__).parents[1]/'docs/4.2.8/routing-candidate.json').read_text(encoding='utf-8'))
    reservations, commits = {}, {}
    profiles = {'repair_claude':dict(provider='claude', quota_pool='anthropic'),
                'repair_codex':dict(provider='codex', quota_pool='openai'),
                'repair_agy':dict(provider='gemini', quota_pool='google')}
    queue = RepairQueue(tmp_path/'independent-repair.sqlite', catalog, profiles=profiles,
        normal_profile_ids={'slot1','slot2','slot3','slot4','slot5','slot6'},
        verify_reservation=reservations.get, verify_commit=lambda c,t: commits.get(c))
    request = queue.report('fault','Controller invariant violated',digest('event'),
                           source_kind='invariant_failure',task_types=['GEN-DEFAULT'])
    return queue, request, reservations, commits


def reserve(setup, incident='fault'):
    queue, request, reservations, _ = setup
    model_id = request['target_profiles'][0]
    provider = queue.catalog['models'][model_id]['provider']
    profile_id, profile = next((k,v) for k,v in queue.profiles.items() if v['provider']==provider)
    reservations['reservation'] = dict(active=True,dedicated_profile=profile_id,model_id=model_id,
        quota_pool=profile['quota_pool'],purpose='pipeline_repair',shared_capacity=4,slot=0,native_accepted=True)
    return queue.claim(incident, profile_id, model_id, 'reservation')


def test_durable_queue_is_independent_and_only_targets_tier_ten(setup):
    queue, request, _, _ = setup
    assert request['complexity']==10 and request['normal_jobboard_required'] is False
    assert request['administrator_actions_authorized'] is False
    assert request['target_profiles']
    for key in request['target_profiles']:
        assert queue.catalog['models'][key]['effort'] in ('max','high')
    assert any(queue.priority_waiting(x) for x in ('anthropic','openai','google'))
    assert not queue.priority_waiting('unrelated')


def test_no_normal_worker_identity_or_unaccepted_model_can_repair(setup):
    queue, request, reservations, _ = setup
    with pytest.raises(ValueError,match='dedicated'):
        queue.claim('fault','slot1',request['target_profiles'][0],'missing')
    execution=reserve(setup)
    assert execution['lease']
    with pytest.raises(ValueError,match='not queued'):
        queue.claim('fault',execution['profile_id'],execution['model_id'],'reservation')


def test_parallel_repairs_do_not_create_a_fifth_execution_slot(setup):
    queue, _, _, _ = setup
    reserve(setup)
    queue.report('fault2','Another controller fault',digest('event2'),source_kind='native_fault',task_types=['GEN-DEFAULT'])
    with pytest.raises(ValueError,match='Another repair'):
        reserve(setup,'fault2')


def test_repair_requires_verified_git_commit_tests_and_matching_cleanup(setup):
    queue, _, _, commits = setup
    execution=reserve(setup)
    commit='a'*40
    with pytest.raises(ValueError,match='independently'):
        queue.record_commit(execution['lease'],commit,digest('tests'))
    commits[commit]=dict(commit_sha=commit,tests_passed=True,working_tree_clean=True,
        cleanup_verified=True,test_evidence_sha256=digest('tests'),
        changed_paths=['src/cochem_pipeline/worker.py','pipeline_tests/test_worker.py'],
        reservation_id='reservation')
    result=queue.record_commit(execution['lease'],commit,digest('tests'))
    assert result['commit_sha']==commit and result['deployment_performed'] is False


@pytest.mark.parametrize('path',['../secrets.json','C:/Program Files/file.py','.claude/settings.json',
    'AGENTS.md','src/../credentials.json','src/.hidden.json','src\\worker.py','src/AGENTS.md'])
def test_repair_path_boundary(path):
    with pytest.raises(ValueError):
        repair_paths([path])


def test_same_incident_cannot_rewrite_history_or_reset_queue(setup):
    queue, request, _, _ = setup
    assert queue.report('fault','Controller invariant violated',digest('event'),
        source_kind='invariant_failure',task_types=['GEN-DEFAULT'])==request
    with pytest.raises(ValueError,match='immutable'):
        queue.report('fault','New request using old identity',digest('other'),
                     source_kind='invariant_failure',task_types=['GEN-DEFAULT'])


def test_spotcheck_sampling_is_stable_bounded_and_explicit():
    assert not sample_completion('job',digest('out'),sample_basis_points=0)
    assert sample_completion('job',digest('out'),sample_basis_points=10000)
    assert sample_completion('job',digest('out'),sample_basis_points=1000)==sample_completion('job',digest('out'),sample_basis_points=1000)
    with pytest.raises(ValueError):
        sample_completion('job',digest('out'),sample_basis_points=True)
