import copy
import json
from types import SimpleNamespace

import pytest

from cochem_pipeline.native_acceptance_plan import build_plan
from cochem_pipeline.r6_native_acceptance import make_probe, validate_result, run_probes
from cochem_pipeline.routing import RoutingPolicy
from cochem_pipeline.config import load_config
from pipeline_tests.test_native_acceptance_plan import complete_candidate


def receipt(target):
    return dict(provider=target['provider'], requested_model=target['model'], requested_effort=target['reasoning_effort'],
        subscription_verified=True, exit_code=0, worker_slot=target['worker'], reported_model=target['model'],
        reported_effort=None, inference_policy={},
        native_reported_model=target['model']+'-'+target['reasoning_effort'] if target['provider']=='gemini' else None)


def test_every_probe_binds_to_exact_owner_catalog_without_fallback(tmp_path):
    raw = complete_candidate(tmp_path)
    policy = RoutingPolicy.from_dict(raw['routing'])
    for target in build_plan(raw)['targets']:
        node = make_probe(policy, target, 'a'*32)
        assert node['route']['model'] == target['model']
        assert node['route']['reasoning_effort'] == target['reasoning_effort']
        assert node['route']['policy_digest'] == policy.digest
        assert node['worker_slot'] == target['worker']
        result = validate_result(target, {'ready': True}, receipt(target))
        assert result['actual_effort_observed'] is False
        assert result['status'] == 'NATIVE_SELECTOR_ACCEPTED'


@pytest.mark.parametrize('mutation', ['output', 'subscription', 'identity', 'effort', 'slot', 'policy', 'slug'])
def test_inconsistent_provider_evidence_cannot_pass(tmp_path, mutation):
    target = build_plan(complete_candidate(tmp_path))['targets'][0]
    evidence, output = receipt(target), {'ready': True}
    if mutation == 'output': output = {'ready': 1}
    if mutation == 'subscription': evidence['subscription_verified'] = False
    if mutation == 'identity': evidence['reported_model'] = 'other'
    if mutation == 'effort': evidence['reported_effort'] = 'max'
    if mutation == 'slot': evidence['worker_slot'] = 'other'
    if mutation == 'policy': evidence.pop('inference_policy')
    if mutation == 'slug': evidence['native_reported_model'] = 'other'
    with pytest.raises(ValueError): validate_result(target, output, evidence)


@pytest.mark.parametrize('fail_at', [None, 2])
def test_sequential_series_preserves_partial_results_without_retry_or_prompt(tmp_path, fail_at):
    raw = complete_candidate(tmp_path)
    path = tmp_path/'candidate.json'; path.write_text(json.dumps(raw))
    config = load_config(path)
    targets = build_plan(raw)['targets']
    root = tmp_path/'evidence'; root.mkdir()
    calls = []
    class Runner:
        def __init__(self, cfg):
            assert cfg.private_root == root
            assert cfg.private_root != config.private_root
        def run(self, node, slot, context, heartbeat, **kwargs):
            index = len(calls)
            calls.append(index)
            assert heartbeat() and slot == targets[index]['worker']
            if index == fail_at: raise ValueError('fixture failure')
            return {'ready': True}, receipt(targets[index])
    ram = SimpleNamespace(workspace=lambda slot: SimpleNamespace(root=tmp_path,
        validate=lambda **kwargs: None))
    if fail_at is None:
        result = run_probes(config, raw, root, ram, runner_factory=Runner, clock=lambda: 100)
        assert result['count'] == len(calls) == 27
        assert result['actual_effort_unobserved'] == 27
        assert not result['coding_workflow_acceptance']
    else:
        with pytest.raises(ValueError):
            run_probes(config, raw, root, ram, runner_factory=Runner, clock=lambda: 100)
        assert calls == [0, 1, 2]
        assert (root/'target-00-verified.json').exists()
        held = json.loads((root/'native-held.json').read_text())
        assert held['completed'] == 2 and held['late_prompt'] is False
        assert not (root/'native-verified.json').exists()


def test_quota_exhaustion_preserves_other_provider_checks_and_never_attests_skipped_targets(tmp_path):
    from cochem_pipeline.failures import ProviderFailure
    raw = complete_candidate(tmp_path)
    path = tmp_path/'config.json'; path.write_text(json.dumps(raw))
    config = load_config(path)
    targets = build_plan(raw)['targets']
    root = tmp_path/'evidence'; root.mkdir()
    calls = []
    class Runner:
        def __init__(self, cfg): pass
        def run(self, node, *args, **kwargs):
            route = node['route']; calls.append(route['provider'])
            if route['provider'] == 'claude': raise ProviderFailure('quota')
            target = next(t for t in targets if all(t[k] == route[k] for k in ('provider','model','reasoning_effort')))
            return {'ready': True}, receipt(target)
    ram = SimpleNamespace(workspace=lambda slot: SimpleNamespace(root=tmp_path, validate=lambda **kwargs: None))
    result = run_probes(config, raw, root, ram, runner_factory=Runner, clock=lambda: 100)
    assert result['status'] == 'NATIVE_ACCEPTANCE_PARTIAL_AVAILABILITY'
    assert calls.count('claude') == 1 and calls.count('gemini') > 1 and calls.count('codex') > 1
    assert any(r['model']=='gemini-3.1-pro' and r['status']=='NATIVE_SELECTOR_ACCEPTED' for r in result['targets'])
    assert all(r['status'] != 'NATIVE_SELECTOR_ACCEPTED' for r in result['targets'] if r['provider']=='claude')
    assert result['accepted_count'] < 27 and result['activation_ready'] is False
