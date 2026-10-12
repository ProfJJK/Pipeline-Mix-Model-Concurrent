"""Acceptance preparation only: no CLI, task, credential or process access."""
import copy
import json

import pytest

from cochem_pipeline.native_acceptance_plan import build_plan
from cochem_pipeline.routing import RoutingPolicy
from pipeline_tests.test_config import config_document
from pipeline_tests.test_native_effort import reviewed_fixture
from pipeline_tests.test_agy_slug_effort import fixture as agy_fixture
from cochem_pipeline.agy_agent_guard import RELATIVES


def candidate(tmp_path):
    raw = config_document(tmp_path)
    raw.update(routing=RoutingPolicy.from_dict({'policy_version': 3}).as_dict(), max_execution_slots=4)
    return raw


def test_plan_covers_thirty_routes_without_repeating_identical_model_efforts(tmp_path):
    raw = candidate(tmp_path)
    before = copy.deepcopy(raw)
    plan = build_plan(raw)
    assert raw == before
    assert len(plan['targets']) == 27
    assert sum(len(row['route_positions']) for row in plan['targets']) == 30
    assert len(plan['authentication_checks']) == 18
    assert len({row['worker'] for row in plan['targets']}) == 6
    pro = [row for row in plan['targets'] if row['model'] == 'gemini-3.1-pro']
    assert len(pro) == 1
    assert pro[0]['route_positions'] == [{'tier': 5, 'choice': 3}, {'tier': 6, 'choice': 3}]
    assert plan['max_parallel_probes'] == 1
    assert plan['max_execution_slots'] == 4
    assert plan['host_accepted'] is False
    assert plan['activation_ready'] is False
    assert plan['interactive_stage'] == 'authentication_before_unattended_work'
    assert plan['late_authentication_action'] == 'hold_without_prompt'


def test_missing_contracts_are_visible_holds_not_guessed_flags(tmp_path):
    plan = build_plan(candidate(tmp_path))
    assert plan['preparation_status'] == 'BINDING_INPUTS_REQUIRED'
    for row in plan['targets']:
        assert row['acceptance_status'] == 'NOT_RUN'
        assert row['actual_effort_verified'] is False
        if row['provider'] != 'codex':
            assert row['preparation_status'] == 'HELD'
            assert row['command_template_sha256'] is None


def test_plan_is_deterministic_and_bound_to_the_entire_candidate(tmp_path):
    raw = candidate(tmp_path)
    first = build_plan(raw)
    assert first == build_plan(raw)
    raw['rules'] = [{'fixture': 'changes config binding without being a model selector'}]
    second = build_plan(raw)
    assert first['candidate_sha256'] != second['candidate_sha256']
    assert first['plan_sha256'] != second['plan_sha256']


def test_public_plan_omits_credentials_and_raw_provider_config(tmp_path):
    raw = candidate(tmp_path)
    raw['workers']['slot-0']['credential_target'] = 'PRIVATE_TARGET_DO_NOT_PUBLISH'
    raw['providers']['claude']['private_fixture'] = 'PRIVATE_PROVIDER_DO_NOT_PUBLISH'
    text = json.dumps(build_plan(raw))
    assert 'PRIVATE_TARGET_DO_NOT_PUBLISH' not in text
    assert 'PRIVATE_PROVIDER_DO_NOT_PUBLISH' not in text
    assert 'fixture-authenticated' not in text


def complete_candidate(tmp_path):
    raw = candidate(tmp_path)
    _, claude, claude_contract = reviewed_fixture(tmp_path, effort='high')
    _, gemini, gemini_contract = agy_fixture(tmp_path, 'high')
    claude['effort_contracts'] = {}
    gemini.update(effort_contracts={}, model_bindings={}, agent_definition=dict(
        name='cochem-inference-only', sha256='a' * 64, bytes=478, relative_paths=list(RELATIVES)))
    for entries in raw['routing']['tiers'].values():
        for entry in entries:
            provider, model, effort = (entry[key] for key in ('provider', 'model', 'reasoning_effort'))
            if provider == 'claude':
                contract = copy.deepcopy(claude_contract)
                contract.update(arguments=['--effort', effort], native_metadata=None)
                claude['effort_contracts'][model + ':' + effort] = contract
            if provider == 'gemini':
                contract = copy.deepcopy(gemini_contract)
                contract['slug_effort'] = effort
                gemini['effort_contracts'][model + ':' + effort] = contract
                gemini['model_bindings'][model + ':' + effort] = model + '-' + effort
    raw['providers'].update(claude=claude, gemini=gemini)
    return raw


def test_all_reviewed_templates_are_prepared_but_never_become_host_acceptance(tmp_path):
    plan = build_plan(complete_candidate(tmp_path))
    assert plan['preparation_status'] == 'COMMAND_TEMPLATES_VALID'
    assert all(row['command_template_sha256'] and row['hold_code'] is None for row in plan['targets'])
    assert all(row['acceptance_status'] == 'NOT_RUN' for row in plan['targets'])
    assert all(row['actual_effort_verified'] is False for row in plan['targets'])
    assert plan['host_accepted'] is False
    assert plan['activation_ready'] is False


def test_one_invalid_binding_does_not_erase_target_or_hold_other_models(tmp_path):
    raw = complete_candidate(tmp_path)
    raw['providers']['claude']['effort_contracts']['claude-fable-5-1:max']['arguments'] = ['--effort', 'high']
    plan = build_plan(raw)
    held = [row for row in plan['targets'] if row['hold_code']]
    assert [(row['model'], row['reasoning_effort']) for row in held] == [('claude-fable-5-1', 'max')]
    assert len(plan['targets']) == 27
    assert plan['preparation_status'] == 'BINDING_INPUTS_REQUIRED'


def test_missing_agent_guard_holds_all_four_gemini_bindings(tmp_path):
    raw = complete_candidate(tmp_path)
    del raw['providers']['gemini']['agent_definition']
    held = [row for row in build_plan(raw)['targets'] if row['hold_code']]
    assert len(held) == 4
    assert all(row['provider'] == 'gemini' for row in held)


def test_existing_integration_hold_never_reads_its_private_evidence(tmp_path, monkeypatch):
    raw = complete_candidate(tmp_path)
    raw['providers']['codex']['integration_hold'] = {'evidence_path': 'PRIVATE_DO_NOT_READ'}
    def no_read(*args, **kwargs):
        raise AssertionError('Preparation must not read external hold evidence')
    # Other providers also pass through integration_hold; restrict this sentinel
    # to the one with external evidence.
    monkeypatch.setattr('cochem_pipeline.provider_integration.integration_hold',
        lambda provider, spec: no_read() if 'integration_hold' in spec else None)
    plan = build_plan(raw)
    held = [row for row in plan['targets'] if row['hold_code']]
    assert len(held) == 11
    assert all(row['hold_code'] == 'INTEGRATION_HOLD_PRESENT' for row in held)


@pytest.mark.parametrize('mutation', ['slots', 'identities', 'version', 'matrix', 'nonfinite'])
def test_wrong_owner_invariants_are_rejected(tmp_path, mutation):
    raw = candidate(tmp_path)
    if mutation == 'slots': raw['max_execution_slots'] = 6
    if mutation == 'identities': raw['workers'].pop('slot-0')
    if mutation == 'version': raw['routing'] = {'policy_version': 2}
    if mutation == 'matrix':
        raw['routing']['catalog']['tiers']['6'][2]['model'] = 'gemini-4-fictional'
        raw['routing']['tiers']['6'][2]['model'] = 'gemini-4-fictional'
    if mutation == 'nonfinite': raw['private_fixture'] = float('nan')
    with pytest.raises(ValueError):
        build_plan(raw)
