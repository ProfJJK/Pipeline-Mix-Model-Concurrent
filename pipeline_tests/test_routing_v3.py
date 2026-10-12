"""Owner matrix and capture compatibility; no native processes or live state."""
import copy

import pytest

from cochem_pipeline.routing import load_routing_policy, validate_selected_route, score_task


EXPECTED = [
    [('gemini', 'gemini-3.8-flash', 'low'), ('claude', 'claude-haiku-5-5', 'medium'), ('codex', 'gpt-6-luna', 'medium')],
    [('gemini', 'gemini-3.8-flash', 'medium'), ('claude', 'claude-haiku-5-5', 'high'), ('codex', 'gpt-6-luna', 'high')],
    [('gemini', 'gemini-3.8-flash', 'high'), ('claude', 'claude-haiku-5-5', 'xhigh'), ('codex', 'gpt-6-luna', 'max')],
    [('codex', 'gpt-6.1-sol', 'low'), ('claude', 'claude-sonnet-5-5', 'medium'), ('gemini', 'gemini-3.8-flash', 'high')],
    [('codex', 'gpt-6.1-sol', 'medium'), ('claude', 'claude-sonnet-5-5', 'high'), ('gemini', 'gemini-3.1-pro', 'high')],
    [('claude', 'claude-sonnet-5-5', 'xhigh'), ('codex', 'gpt-6.1-sol', 'high'), ('gemini', 'gemini-3.1-pro', 'high')],
    [('claude', 'claude-opus-5-5', 'high'), ('codex', 'gpt-6.1-sol', 'xhigh'), ('claude', 'claude-sonnet-5-5', 'max')],
    [('claude', 'claude-opus-5-5', 'xhigh'), ('codex', 'gpt-6-astra', 'high'), ('codex', 'gpt-6.1-sol', 'max')],
    [('claude', 'claude-opus-5-5', 'max'), ('codex', 'gpt-6-astra', 'xhigh'), ('claude', 'claude-fable-5-1', 'high')],
    [('claude', 'claude-fable-5-1', 'max'), ('codex', 'gpt-6-astra', 'max'), ('claude', 'claude-opus-5-5', 'max')],
]


@pytest.mark.parametrize('score', range(1, 11))
def test_exact_owner_matrix_all_tiers_and_target_visibility(score):
    policy = load_routing_policy({'policy_version': 3})
    targets = policy.candidates(score, 'CODE_EDIT')
    assert [(t.provider, t.model, t.reasoning_effort) for t in targets] == EXPECTED[score - 1]
    assert all(policy.is_enabled(t) for t in targets)
    assert all(t.quota_pool == t.provider for t in targets)
    for index, target in enumerate(targets):
        route = dict(target.as_dict(), score=score, tier=str(score), kind='CODE_EDIT',
                     policy_digest=policy.digest, candidate_index=index)
        assert validate_selected_route(policy, route) == target


@pytest.mark.parametrize('version,digest', [
    (1, '77054d615daa19c2ef0283f6f40f4e549042763bb0c1452068051d48652507e1'),
    (2, '69f2d3754eedbc2b0804dd354bbdbbbed8d80ebc2d28a2c14dc98174e9613538'),
])
def test_historical_default_digest_unchanged(version, digest):
    assert load_routing_policy({'policy_version': version}).digest == digest


def test_capture_is_detached_from_input_and_embeds_catalog():
    policy = load_routing_policy({'policy_version': 3})
    capture = policy.as_dict()
    assert capture['catalog']['generation'] == 'owner-2026-10-11'
    recovered = load_routing_policy(copy.deepcopy(capture))
    capture['catalog']['tiers']['6'][2]['model'] = 'changed-model'
    assert recovered.digest == policy.digest
    assert recovered.candidates(6)[2].model == 'gemini-3.1-pro'


def test_old_capture_never_reads_a_new_default_catalog(monkeypatch):
    policy = load_routing_policy({'policy_version': 3})
    def unavailable():
        raise AssertionError('A captured policy must not reload the catalog')
    monkeypatch.setattr('cochem_pipeline.routing.default_catalog', unavailable)
    assert load_routing_policy(policy.as_dict()).digest == policy.digest


def test_supervisor_independently_decodes_complete_v3_capture():
    from cochem_supervisor.probes import configured_routing_policy, configured_tiers
    policy = load_routing_policy({'policy_version': 3})
    assert configured_routing_policy(policy.as_dict()) == policy.as_dict()
    assert configured_tiers(policy.as_dict()) == {str(i): row for i, row in enumerate(EXPECTED, 1)}


def test_new_configuration_can_explicitly_opt_into_v3_without_rewriting_v2():
    from cochem_pipeline.routing import load_current_routing_policy
    from cochem_supervisor.probes import configured_current_routing_policy
    selected = load_current_routing_policy({'policy_version': 3})
    assert configured_current_routing_policy(selected.as_dict()) == selected.as_dict()
    assert load_current_routing_policy({'policy_version': 2}).as_dict()['policy_version'] == 2


@pytest.mark.parametrize('kind', ['CODE_EDIT', 'CODE_TEST_AUTHOR', 'CODE_REVIEW'])
def test_v2_scoring_reaches_small_coding_tiers_without_changing_old_scores(kind):
    from cochem_supervisor.probes import score_routing_task
    for expected, payload in [(1, {'objective': 'Format a heading'}),
                              (2, {'objective': 'Format headings', 'requirements': ['A', 'B', 'C', 'D']})]:
        score = score_task(kind, payload, scoring_version=2)
        assert score['score'] == expected and score['tier'] == str(expected)
        assert score == score_routing_task(kind, payload, scoring_version=2)
        assert score_task(kind, payload)['score'] == expected + 2


def test_v3_store_captures_exact_tier_and_survives_reload(tmp_path):
    from cochem_pipeline.store import JobStore
    policy = load_routing_policy({'policy_version': 3})
    store = JobStore(tmp_path / 'test.db', routing_policy=policy)
    store.submit('Write a small note', ['REQ-1'], 1)
    job = store.claim('fixture', worker_slot='slot1')
    assert job['route']['tier'] == str(job['route']['score'])
    assert job['routing']['score_details']['policy_version'] == 2
    validate_selected_route(policy, job['route'], kind=job['kind'])
    assert JobStore(store.path, routing_policy=policy).get(job['job_id'])['route'] == job['route']


@pytest.mark.parametrize('mutation', ['effort', 'duplicate', 'missing', 'order'])
def test_catalog_and_routes_fail_closed(mutation):
    capture = load_routing_policy({'policy_version': 3}).as_dict()
    if mutation == 'effort':
        capture['catalog']['tiers']['1'][0]['reasoning_effort'] = 'ultra'
    elif mutation == 'duplicate':
        capture['catalog']['tiers']['1'][1] = dict(capture['catalog']['tiers']['1'][0], reasoning_effort='medium')
    elif mutation == 'missing':
        del capture['catalog']['tiers']['6']
    else:
        capture['tiers']['6'].reverse()
    with pytest.raises(ValueError):
        load_routing_policy(capture)
