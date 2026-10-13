"""Recorded failure shape with synthetic tool names; no native execution."""
import copy

import pytest

from cochem_pipeline.agy_protocol import AgyIdentityError, IDENTITY_POLICY, parse_stream
from cochem_pipeline.r6_candidate import propose
from cochem_pipeline.worker import parse_gemini
from pipeline_tests.test_agy_protocol import records, raw
from pipeline_tests.test_r6_candidate import base


@pytest.fixture
def spec(tmp_path):
    return propose(base(tmp_path))[0]['providers']['gemini']


def observation():
    rows = records()
    rows[0]['init'].update(agent='cochem-inference-only',
                          model='gemini-3.8-flash-low',
                          tools=[f'fixture_tool_{i}' for i in range(60)])
    return rows


def parse(rows, spec):
    return parse_gemini(raw(rows), 'agy-stream-json', 'gemini-3.8-flash',
                        native={'argv': 'gemini-3.8-flash-low', 'reports': 'gemini-3.8-flash-low'},
                        identity_policy=IDENTITY_POLICY, stderr='', inference_spec=spec)


def test_successful_sixty_tool_advertisement_is_not_a_grant_to_guarded_agent(spec):
    rows = observation()
    with pytest.raises(AgyIdentityError, match='empty native tool registry'):
        parse_stream(raw(rows), 'gemini-3.8-flash-low', identity_policy=IDENTITY_POLICY)
    result = parse(rows, spec)
    assert result['terminal_success'] and result['content'] == '{}'
    assert result['reported_model'] == 'gemini-3.8-flash'
    assert result['tool_registry']['scope'] == 'cli_builtin_runners'
    assert result['tool_registry']['advertised_count'] == 60
    assert result['tool_registry']['advertised_tools_are_agent_permissions'] is False


@pytest.mark.parametrize('field', ['binary', 'version', 'agent_hash', 'bytes', 'agent_arg', 'tools', 'mcp', 'hooks', 'subagents'])
def test_scope_exception_cannot_spread_to_unreviewed_bindings(spec, field):
    if field == 'binary': spec['inference_only']['executable_sha256'] = 'a' * 64
    if field == 'version': spec['inference_only']['version'] = '1.3.2'
    if field == 'agent_hash': spec['agent_definition']['sha256'] = 'a' * 64
    if field == 'bytes': spec['agent_definition']['bytes'] = 479
    if field == 'agent_arg': spec['inference_only']['arguments'][1] = 'other-agent'
    if field in ('tools', 'mcp', 'hooks', 'subagents'):
        spec['inference_only']['disables_' + field] = False
    with pytest.raises(AgyIdentityError): parse(observation(), spec)


@pytest.mark.parametrize('tools', [None, {}, 'all', ['same', 'same'], ['bad\nname'], [None],
                                  ['a' * 129], [f'tool_{i}' for i in range(257)]])
def test_malformed_registry_is_not_ignored(spec, tools):
    rows = observation()
    rows[0]['init']['tools'] = tools
    with pytest.raises(AgyIdentityError): parse(rows, spec)


@pytest.mark.parametrize('agent', [None, '', 'default', 'cochem-inference-only\n'])
def test_selected_agent_must_match_even_for_empty_advertisement(spec, agent):
    rows = observation()
    rows[0]['init'].update(agent=agent, tools=[])
    with pytest.raises(AgyIdentityError): parse(rows, spec)


@pytest.mark.parametrize('change', ['tool_name', 'tool_info', 'subagent_info', 'tool_step',
                                    'different_model', 'reroute', 'stderr'])
def test_actual_tools_agents_and_model_changes_still_fail(spec, change):
    rows = observation()
    if change in ('tool_name', 'tool_info', 'subagent_info'):
        rows[1]['step_update'][change] = {}
    elif change == 'tool_step': rows[1]['step_update']['step_type'] = 'tool'
    elif change == 'different_model': rows[-1]['result']['model'] = 'other-model'
    elif change == 'reroute': rows[-1]['result']['fallback'] = True
    if change == 'stderr':
        with pytest.raises(AgyIdentityError):
            parse_stream(raw(rows), 'gemini-3.8-flash-low', inference_spec=spec,
                         identity_policy=IDENTITY_POLICY, stderr='Model resolved via fallback')
    else:
        with pytest.raises(ValueError): parse(rows, spec)


def test_parser_preserves_inputs_and_does_not_export_tool_names(spec):
    rows = observation()
    before = copy.deepcopy((rows, spec))
    result = parse(rows, spec)
    assert (rows, spec) == before
    assert 'fixture_tool_' not in str(result)
