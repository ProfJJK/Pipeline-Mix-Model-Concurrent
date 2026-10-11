"""Public protocol fixtures, not live Agy or Windows isolation evidence."""
import copy
import json

import pytest

from cochem_pipeline import agy_protocol
from cochem_pipeline.agy_protocol import encode_prompt, parse_stream, validate_arguments
from cochem_pipeline.agy_protocol import (IDENTITY_POLICY, AgyIdentityError, native_model_binding,
    require_serving_model_contract, validate_identity_policy, validate_model_bindings)
from cochem_pipeline.failures import ProviderFailure
from cochem_pipeline.native_evidence import native_usage
from cochem_pipeline.worker import NativeRunner, native_prompt_text, parse_gemini, provider_command
from cochem_supervisor.runner import validate_provider_spec


MODEL = 'gemini-3.8-flash'
ARGV = ['--input-format', 'stream-json', '--output-format', 'stream-json', '--model', '{model}']


def records():
    # An empty tool registry is deliberately stricter than vendor examples.
    # No observed Agy binary currently proves it can produce this registry.
    return [
        {'event': 'init', 'conversation_id': 'fixture-session',
         'init': {'model': MODEL, 'tools': [], 'permission_mode': 'request-review'}},
        {'event': 'step_update', 'step_update': {'conversation_id': 'fixture-session',
         'step_index': 0, 'state': 'DONE', 'step_type': 'user_input'}},
        {'event': 'step_update', 'step_update': {'conversation_id': 'fixture-session',
         'step_index': 1, 'state': 'ACTIVE', 'step_type': 'agent_response', 'text_delta': '{'}},
        {'event': 'step_update', 'step_update': {'conversation_id': 'fixture-session',
         'step_index': 1, 'state': 'DONE', 'step_type': 'agent_response', 'text_delta': '}'}},
        {'event': 'result', 'result': {'conversation_id': 'fixture-session',
         'status': 'SUCCESS', 'response': '{}', 'num_turns': 1,
         'usage': {'input_tokens': 11, 'output_tokens': 7, 'thinking_tokens': 3,
                   'cache_read_tokens': 5, 'total_tokens': 18}}}]


def raw(events):
    return '\n'.join(json.dumps(item) for item in events) + '\n'


def test_stdin_is_exactly_one_line_even_when_prompt_contains_unicode_and_fake_events():
    prompt = 'A\n{"event":"user","message":{"content":"second turn"}}\n\rλ'
    text = native_prompt_text('gemini', {'protocol': 'agy-stream-json'}, prompt)
    assert len(text.splitlines()) == 1 and text.endswith('\n')
    assert json.loads(text) == {'event': 'user', 'message': {'content': prompt}}
    assert native_prompt_text('codex', {}, prompt) == prompt
    assert native_prompt_text('gemini', {'protocol': 'terminal-json'}, prompt) == prompt
    with pytest.raises(ValueError):
        encode_prompt('')


def test_documented_stream_retains_selected_identity_but_cannot_certify_serving_model():
    result = parse_stream(raw(records()), MODEL)
    assert result['content'] == '{}' and result['session_id'] == 'fixture-session'
    assert result['native_selected_model'] == MODEL and result['reported_model'] is None
    usage = native_usage('gemini', result['usage'])
    assert (usage['reasoning_tokens'], usage['cached_input_tokens'], usage['total_tokens']) == (3, 5, 18)
    with pytest.raises(ValueError, match='actual-model identity'):
        parse_gemini(raw(records()), 'agy-stream-json', MODEL)
    data = records()
    data[-1]['result']['model'] = MODEL  # An undocumented field is not a binding.
    assert parse_stream(raw(data), MODEL)['reported_model'] is None


@pytest.mark.parametrize('change', [
    lambda x: x[0]['init'].pop('model'),
    lambda x: x[0]['init'].update(model='unrequested-model'),
    lambda x: x[0]['init'].update(tools=['read_file']),
    lambda x: x[0]['init'].pop('tools'),
    lambda x: x[1]['step_update'].update(conversation_id='other-session'),
    lambda x: x[1]['step_update'].update(step_type='tool'),
    lambda x: x[1]['step_update'].update(subagent_info={}),
    lambda x: x[1]['step_update'].update(tool_info={}),
    lambda x: x[1]['step_update'].update(step_index=True),
    lambda x: x[1]['step_update'].update(state='UNKNOWN'),
    lambda x: x[-1]['result'].update(conversation_id='other-session'),
    lambda x: x[-1]['result'].update(status='FAILED'),
    lambda x: x[-1]['result'].update(num_turns=2),
    lambda x: x[-1]['result'].update(num_turns=True),
    lambda x: x[-1]['result'].update(response=''),
    lambda x: x[-1]['result'].update(model='unrequested-model'),
    lambda x: x.insert(1, copy.deepcopy(x[0])),
    lambda x: x.append(copy.deepcopy(x[-1])),
])
def test_ambiguous_sessions_tools_agents_and_terminal_failure_cannot_pass(change):
    data = records()
    change(data)
    with pytest.raises(ValueError):
        parse_stream(raw(data), MODEL)


@pytest.mark.parametrize('text', ['{}', '[]\n[]', 'not JSON',
    '{"event":"init","event":"result"}\n{}', '{}\nNaN'])
def test_malformed_stream_rejected(text):
    with pytest.raises(ValueError):
        parse_stream(text, MODEL)


def test_unicode_native_answer_and_bounded_json_depth():
    data = records()
    data[-1]['result']['response'] = 'paragraph\u2028separator\u2029content'
    stream = '\n'.join(json.dumps(item, ensure_ascii=False) for item in data)
    assert parse_stream(stream, MODEL)['content'] == data[-1]['result']['response']
    with pytest.raises(ValueError, match='nesting depth'):
        parse_stream('[' * 2000 + '0' + ']' * 2000 + '\n{}', MODEL)


@pytest.mark.parametrize('suffix', [
    ['--input-format', 'stream-json'], ['--output-format=json'], ['--model=alias'],
    ['--prompt', 'argv prompt'], ['--continue'], ['--conversation', 'old-session'],
    ['--dangerously-skip-permissions'],
])
def test_transport_cannot_change_output_mode_or_smuggle_extra_prompts(suffix):
    validate_arguments(ARGV)
    with pytest.raises(ValueError):
        validate_arguments(ARGV + suffix)


def test_stream_identity_hold_precedes_native_probe_authentication_and_inference():
    spec = {'provider': 'gemini', 'model': MODEL, 'protocol': 'agy-stream-json'}
    with pytest.raises(ProviderFailure) as caught:
        NativeRunner(None)._inference_preflight({'route': {'model': MODEL}}, 'gemini',
            ['must-not-launch'], spec, None, None, lambda: True, None, {}, None)
    assert caught.value.category == 'compatibility'
    with pytest.raises(ValueError, match='actual-model identity'):
        provider_command('gemini', ['must-not-launch'], MODEL, 'workspace', spec)
    with pytest.raises(ValueError, match='actual-model identity'):
        validate_provider_spec(spec)


# Decision 3B: the reviewed 'reported-model-equality' identity policy.
LOW, HIGH, FAMILY = 'gemini-3.8-flash-low', 'gemini-3.8-flash-high', 'gemini-3.8-flash'
EXTENDED = MODEL + ':extended'
LEGACY_HOLD = 'Agy stream actual-model identity has no verified native contract'


def effort_contract(level='high'):
    return {'arguments': ['--effort', level], 'version_arguments': ['--version'],
            'executable_sha256': '0' * 64, 'version': '1.3.1',
            'capability_reference': 'fixture-receipt.json#' + '0' * 64,
            'native_metadata': None, 'thinking_enabled': None}


def policy_spec(bindings=None, contracts=None):
    spec = {'provider': 'gemini', 'model': 'gemini-3.1-pro-preview', 'protocol': 'agy-stream-json',
            'identity_policy': IDENTITY_POLICY,
            'model_bindings': {MODEL: LOW} if bindings is None else bindings}
    if contracts is not None:
        spec['effort_contracts'] = contracts
    return spec


def stream(model, change=None):
    data = records()
    data[0]['init']['model'] = model
    if change is not None:
        change(data)
    return raw(data)


def test_identity_policy_constant_and_error_type_are_stable():
    assert IDENTITY_POLICY == 'reported-model-equality'
    assert issubclass(AgyIdentityError, ValueError)
    assert validate_identity_policy({'protocol': 'agy-stream-json'}) is None
    assert validate_identity_policy({'protocol': 'gemini-json'}) is None
    assert validate_identity_policy(policy_spec()) == IDENTITY_POLICY


def test_both_model_binding_forms_are_accepted():
    spec = policy_spec({MODEL: LOW, EXTENDED: {'argv': FAMILY, 'reports': HIGH}},
                       {EXTENDED: effort_contract('high')})
    assert validate_model_bindings(spec) == {
        MODEL: {'argv': LOW, 'reports': LOW}, EXTENDED: {'argv': FAMILY, 'reports': HIGH}}
    assert require_serving_model_contract(spec) is None
    assert native_model_binding(spec, MODEL, None) == {'argv': LOW, 'reports': LOW}
    assert native_model_binding(spec, MODEL, 'extended') == {'argv': FAMILY, 'reports': HIGH}
    # A plain slug may bind an effort route, and a dict may bind a plain route.
    spec = policy_spec({MODEL: {'argv': FAMILY, 'reports': HIGH}, EXTENDED: HIGH},
                       {EXTENDED: effort_contract('high')})
    assert native_model_binding(spec, MODEL, None) == {'argv': FAMILY, 'reports': HIGH}
    assert native_model_binding(spec, MODEL, 'extended') == {'argv': HIGH, 'reports': HIGH}
    # Exactly 32 bindings are the upper bound.
    assert len(validate_model_bindings(policy_spec({f'm{i}': LOW for i in range(32)}))) == 32


@pytest.mark.parametrize('bindings, contracts', [
    ({MODEL: {'argv': LOW, 'reports': LOW, 'extra': LOW}}, None),
    ({MODEL: {'argv': LOW}}, None),
    ({MODEL: {'reports': LOW}}, None),
    ({MODEL: {}}, None),
    ({MODEL: 'Gemini-3.8-flash'}, None),
    ({MODEL: '{model}'}, None),
    ({MODEL: 'REPLACE_WITH_REVIEWED_SLUG'}, None),
    ({MODEL: ''}, None),
    ({MODEL: '-gemini'}, None),
    ({MODEL: 'gemini 3.8'}, None),
    ({MODEL: 'gemini/flash'}, None),
    ({MODEL: 'gemini-3.8-flash\n'}, None),
    ({MODEL: 'a' * 129}, None),
    ({MODEL: {'argv': LOW, 'reports': 'Gemini'}}, None),
    ({MODEL: {'argv': None, 'reports': LOW}}, None),
    ({MODEL: 7}, None),
    ({MODEL: None}, None),
    ({MODEL: [LOW]}, None),
    ({'': LOW}, None),
    ({':high': LOW}, None),
    ({MODEL + ':low': LOW}, None),
    ({MODEL + ':extended:high': LOW}, None),
    ({'-gemini': LOW}, None),
    ({'gemini 3.8': LOW}, None),
    ({'a' * 201: LOW}, None),
    ({EXTENDED: HIGH}, None),
    ({EXTENDED: HIGH}, {}),
    ({EXTENDED: HIGH}, {MODEL + ':high': effort_contract('high')}),
    ({EXTENDED: LOW}, {EXTENDED: effort_contract('high')}),
    ({EXTENDED: {'argv': LOW, 'reports': HIGH}}, {EXTENDED: effort_contract('high')}),
    ({EXTENDED: {'argv': FAMILY, 'reports': 'gemini-3.8-flash-medium'}}, {EXTENDED: effort_contract('high')}),
    ({MODEL: LOW}, {EXTENDED: effort_contract('high')}),
    ({MODEL: LOW}, []),
    ({}, None),
    ([MODEL, LOW], None),
    ({f'm{i}': LOW for i in range(33)}, None),
])
def test_invalid_model_bindings_are_rejected(bindings, contracts):
    spec = policy_spec(bindings, contracts)
    with pytest.raises(ValueError):
        validate_model_bindings(spec)
    with pytest.raises(ValueError):
        require_serving_model_contract(spec)


def test_policy_requires_bindings_and_bindings_require_policy():
    spec = policy_spec()
    del spec['model_bindings']
    with pytest.raises(ValueError, match='1 to 32'):
        validate_model_bindings(spec)
    with pytest.raises(ValueError):
        require_serving_model_contract(spec)
    for protocol in ('agy-stream-json', 'gemini-json', 'terminal-json'):
        unpoliced = {'provider': 'gemini', 'protocol': protocol, 'model_bindings': {MODEL: LOW}}
        with pytest.raises(ValueError, match='identity policy'):
            validate_model_bindings(unpoliced)
        with pytest.raises(ValueError):
            native_model_binding(unpoliced, MODEL, None)
        with pytest.raises(ValueError):
            require_serving_model_contract(unpoliced)
    for policy, protocol in (('reported-model', 'agy-stream-json'), (None, 'agy-stream-json'),
                             (IDENTITY_POLICY, 'gemini-json'), (IDENTITY_POLICY, 'terminal-json')):
        spec = policy_spec()
        spec.update(identity_policy=policy, protocol=protocol)
        for check in (validate_identity_policy, validate_model_bindings, require_serving_model_contract):
            with pytest.raises(ValueError, match='reported-model-equality'):
                check(spec)


def test_native_model_binding_without_reviewed_key_raises():
    spec = policy_spec({MODEL: LOW})
    for model, effort in ((MODEL, 'extended'), (MODEL, 'high'), ('gemini-3.1-pro-preview', 'high'),
                          ('gemini-3.1-pro-preview', None)):
        with pytest.raises(ValueError) as caught:
            native_model_binding(spec, model, effort)
        assert str(caught.value) == 'Gemini route has no reviewed native model binding'
    # Without the policy the routed id is passed through unchanged.
    for protocol in ('gemini-json', 'terminal-json', 'agy-stream-json'):
        assert native_model_binding({'protocol': protocol}, MODEL, 'extended') == {
            'argv': MODEL, 'reports': MODEL}
    assert validate_model_bindings({'protocol': 'gemini-json'}) == {}


def test_legacy_hold_message_is_byte_identical_without_policy():
    for spec in ({'protocol': 'agy-stream-json'},
                 {'provider': 'gemini', 'model': MODEL, 'protocol': 'agy-stream-json'}):
        with pytest.raises(ValueError) as caught:
            require_serving_model_contract(spec)
        assert type(caught.value) is ValueError
        assert str(caught.value) == LEGACY_HOLD
        assert caught.value.args == (LEGACY_HOLD,)
    for protocol in ('gemini-json', 'terminal-json', None):
        assert require_serving_model_contract({'protocol': protocol}) is None


def test_reported_name_not_argv_slug_is_the_identity_under_policy():
    binding = native_model_binding(policy_spec({MODEL: {'argv': FAMILY, 'reports': HIGH}}), MODEL, None)
    assert binding == {'argv': FAMILY, 'reports': HIGH}
    result = parse_stream(stream(binding['reports']), binding['reports'],
                          identity_policy=IDENTITY_POLICY, stderr='')
    assert result['reported_model'] == result['native_selected_model'] == HIGH
    assert result['content'] == '{}' and result['terminal_success'] is True
    assert result['usage']['total_tokens'] == 18
    with pytest.raises(AgyIdentityError):
        parse_stream(stream(binding['argv']), binding['reports'], identity_policy=IDENTITY_POLICY)
    # Without the policy the same stream is still not an identity receipt.
    assert parse_stream(stream(HIGH), HIGH)['reported_model'] is None


def test_missing_result_model_passes_and_matching_model_fields_pass():
    assert 'model' not in records()[-1]['result']
    assert parse_stream(stream(HIGH), HIGH, identity_policy=IDENTITY_POLICY)['reported_model'] == HIGH

    def agreeing(data):
        data[0]['init'].update(selected_model=HIGH, model_id=HIGH)
        data[0]['model'] = HIGH
        data[1]['step_update'].update(model=HIGH, selected_model=HIGH)
        data[-1]['result'].update(model=HIGH, model_id=HIGH, selected_model=HIGH)
    assert parse_stream(stream(HIGH, agreeing), HIGH,
                        identity_policy=IDENTITY_POLICY)['reported_model'] == HIGH


@pytest.mark.parametrize('change', [
    lambda x: x[0]['init'].update(model_id=FAMILY),
    lambda x: x[0]['init'].update(selected_model=FAMILY),
    lambda x: x[0].update(model=FAMILY),
    lambda x: x[0].update(model_id=FAMILY),
    lambda x: x[1].update(selected_model=FAMILY),
    lambda x: x[1]['step_update'].update(model_id=FAMILY),
    lambda x: x[2]['step_update'].update(selected_model=FAMILY),
    lambda x: x[2]['step_update'].update(model=FAMILY),
    lambda x: x[-1].update(model=FAMILY),
    lambda x: x[-1]['result'].update(model=FAMILY),
    lambda x: x[-1]['result'].update(model_id=FAMILY),
    lambda x: x[-1]['result'].update(selected_model=FAMILY),
    lambda x: x[-1]['result'].update(model_id=None),
    lambda x: x[0]['init'].pop('model'),
    lambda x: x[0]['init'].update(model=None),
])
def test_model_identity_disagreement_fails(change):
    with pytest.raises(AgyIdentityError):
        parse_stream(stream(HIGH, change), HIGH, identity_policy=IDENTITY_POLICY)
    with pytest.raises(AgyIdentityError):
        parse_stream(stream(HIGH, change), HIGH)


@pytest.mark.parametrize('change', [
    lambda x: x[0]['init'].update(deprecated_model_rerouting_info={'from': HIGH, 'to': 'gemini-2.5-flash'}),
    lambda x: x[-1]['result'].update(metadata={'routing': {'deprecated_model_rerouting_info': {'to': 'x'}}}),
    lambda x: x[0]['init'].update(is_fallback=True),
    lambda x: x[1]['step_update'].update(details=[{'serving': {'is_fallback': True}}]),
    lambda x: x[-1]['result']['usage'].update(is_fallback=True),
    lambda x: x[0].update(isFallback=True),
    lambda x: x[0]['init'].update(fallback_model='gemini-2.5-flash'),
    lambda x: x[-1]['result'].update(model_rerouted=True),
    lambda x: x[2]['step_update'].update(rerouting={'reason': 'capacity'}),
    lambda x: x[0]['init'].update(deprecatedModel='gemini-2.0'),
])
def test_fallback_and_reroute_members_fail_with_and_without_policy(change):
    with pytest.raises(AgyIdentityError, match='fallback or reroute'):
        parse_stream(stream(HIGH, change), HIGH, identity_policy=IDENTITY_POLICY)
    with pytest.raises(AgyIdentityError, match='fallback or reroute'):
        parse_stream(stream(HIGH, change), HIGH)


def test_falsy_fallback_members_pass():
    def benign(data):
        data[0]['init'].update(is_fallback=False, deprecated_model_rerouting_info={})
        data[1]['step_update'].update(details=[{'serving': {'is_fallback': False}}])
        data[-1]['result'].update(rerouted=None, fallback_reason='')
        data[-1]['result']['usage'].update(fallback_tokens=0)
    result = parse_stream(stream(HIGH, benign), HIGH, identity_policy=IDENTITY_POLICY)
    assert result['reported_model'] == HIGH
    assert parse_stream(stream(MODEL, benign), MODEL)['reported_model'] is None


@pytest.mark.parametrize('marker', [
    'AGY_ERROR:', 'is no longer available. Using', 'Model resolved via',
    'Restored session model', 'resolves to a different model',
])
def test_each_rerouting_stderr_marker_fails(marker):
    stderr = f'info: starting\nwarning: {marker} something else\n'
    with pytest.raises(AgyIdentityError, match='diagnostics'):
        parse_stream(stream(HIGH), HIGH, identity_policy=IDENTITY_POLICY, stderr=stderr)
    with pytest.raises(AgyIdentityError, match='diagnostics'):
        parse_stream(stream(MODEL), MODEL, stderr=stderr)
    # Without stderr the stream itself remains acceptable.
    assert parse_stream(stream(HIGH), HIGH, identity_policy=IDENTITY_POLICY)['reported_model'] == HIGH


def test_benign_or_absent_stderr_passes_and_bad_stderr_is_protocol():
    for stderr in (None, '', 'Loaded cached credentials.\n', 'agy_error: lowercase is not the marker'):
        assert parse_stream(stream(HIGH), HIGH, identity_policy=IDENTITY_POLICY,
                            stderr=stderr)['reported_model'] == HIGH
    for stderr in (b'AGY_ERROR: bytes', 7, 'x' * (8 * 1024 * 1024 + 1)):
        with pytest.raises(ValueError) as caught:
            parse_stream(stream(HIGH), HIGH, identity_policy=IDENTITY_POLICY, stderr=stderr)
        assert not isinstance(caught.value, AgyIdentityError)


def test_tool_registry_violations_are_identity_but_malformed_streams_are_protocol():
    for change in (lambda x: x[0]['init'].update(tools=['read_file']),
                   lambda x: x[0]['init'].pop('tools'),
                   lambda x: x[1]['step_update'].update(tool_name='run_shell'),
                   lambda x: x[1]['step_update'].update(tool_info={}),
                   lambda x: x[1]['step_update'].update(subagent_info={})):
        with pytest.raises(AgyIdentityError):
            parse_stream(stream(HIGH, change), HIGH, identity_policy=IDENTITY_POLICY)
    for change in (lambda x: x[1]['step_update'].update(conversation_id='other-session'),
                   lambda x: x[1]['step_update'].update(step_type='tool'),
                   lambda x: x[-1]['result'].update(status='FAILED'),
                   lambda x: x[-1]['result'].update(response=''),
                   lambda x: x[0].update(conversation_id=''),
                   lambda x: x.insert(1, copy.deepcopy(x[0]))):
        with pytest.raises(ValueError) as caught:
            parse_stream(stream(HIGH, change), HIGH, identity_policy=IDENTITY_POLICY)
        assert not isinstance(caught.value, AgyIdentityError)
    for text in ('{}', 'not JSON', '{}\nNaN'):
        with pytest.raises(ValueError) as caught:
            parse_stream(text, HIGH, identity_policy=IDENTITY_POLICY)
        assert not isinstance(caught.value, AgyIdentityError)


def test_unknown_identity_policy_is_rejected_by_the_parser():
    for policy in ('reported-model', 'REPORTED-MODEL-EQUALITY', ''):
        with pytest.raises(ValueError, match='identity policy') as caught:
            parse_stream(stream(HIGH), HIGH, identity_policy=policy)
        assert not isinstance(caught.value, AgyIdentityError)


# AG-2: the identity and reroute scan covers every event and nested record,
# every model spelling, and the A5 evidence tool's reroute fragments and
# stderr markers (agy_isolation_evidence_r4_v1.py). records()[0] is init,
# [1] a step and [-1] the result.
OTHER = 'gemini-2.5-flash'
REVIEWER_REJECTS = [
    pytest.param(lambda x: x[-1]['result'].update(model=OTHER), '', id='result.model'),
    pytest.param(lambda x: x[1]['step_update'].update(metadata={'model': OTHER}), '', id='step.metadata.model'),
    pytest.param(lambda x: x[-1]['result']['usage'].update(model=OTHER), '', id='result.usage.model'),
    pytest.param(lambda x: x[-1]['result']['usage'].update(models={OTHER: {'input': 5}}), '',
                 id='result.usage.models-keyed-by-other'),
    pytest.param(lambda x: x[-1]['result'].update(modelVersion=OTHER), '', id='result.modelVersion'),
    pytest.param(lambda x: x[-1]['result'].update(model_name=OTHER), '', id='result.model_name'),
    pytest.param(lambda x: x[0]['init'].update(model_version=OTHER), '', id='init.model_version'),
    pytest.param(lambda x: x[-1]['result'].update(used_non_gemini_model=True), '', id='used_non_gemini_model'),
    pytest.param(lambda x: x[-1]['result'].update(model_substituted=True), '', id='model_substituted'),
    pytest.param(lambda x: x[-1]['result'].update(downgraded_from=HIGH), '', id='downgraded_from'),
    pytest.param(lambda x: x[0]['init'].update(resolved_model=OTHER), '', id='init.resolved_model'),
    pytest.param(lambda x: x[-1]['result'].update(retry_model_capacity_exhausted=True), '',
                 id='retry_model_capacity_exhausted'),
    pytest.param(lambda x: x[-1]['result'].update(is_fallback=True), '', id='is_fallback'),
    pytest.param(None, f'Model ID {HIGH} not in local config, defaulting to CCPA\n', id='stderr-defaulting-to'),
    pytest.param(None, f'Restoring model "{OTHER}" after a one-shot /model turn\n', id='stderr-restoring-model'),
    pytest.param(None, 'AGY_ERROR: {"code":"x"}\n', id='stderr-agy-error'),
]
NESTED_REJECTS = [
    pytest.param(lambda x: x[0]['init'].update(ModelId=OTHER), '', id='ModelId'),
    pytest.param(lambda x: x[0]['init'].update(**{'model-name': OTHER}), '', id='model-name'),
    pytest.param(lambda x: x[0]['init'].update(selectedModel=OTHER), '', id='selectedModel'),
    pytest.param(lambda x: x[2]['step_update'].update(modelVersion=None), '', id='step.modelVersion-null'),
    pytest.param(lambda x: x[-1]['result'].update(meta={'serving': [{'model_id': OTHER}]}), '', id='deep-list'),
    pytest.param(lambda x: x[-1]['result'].update(resolvedModel=OTHER), '', id='resolvedModel'),
    # A5 lists every key containing 'resolved' as a reroute signal, so even an
    # agreeing resolved_model is rejected; resolved_model=None fails equality.
    pytest.param(lambda x: x[0]['init'].update(resolved_model=HIGH), '', id='resolved_model-agreeing'),
    pytest.param(lambda x: x[0]['init'].update(resolved_model=None), '', id='resolved_model-null'),
    pytest.param(lambda x: x[0]['init'].update(models={HIGH: {}, OTHER: {}}), '', id='models-extra-key'),
    pytest.param(lambda x: x[0]['init'].update(models=[OTHER]), '', id='models-list'),
    pytest.param(lambda x: x[0]['init'].update(models=OTHER), '', id='models-string'),
    pytest.param(lambda x: x[0]['init'].update(models=7), '', id='models-number'),
    pytest.param(lambda x: x[-1]['result'].update(usedNonGeminiModel=1), '', id='usedNonGeminiModel'),
    pytest.param(lambda x: x[-1]['result'].update(capacityExhausted=True), '', id='capacityExhausted'),
    pytest.param(lambda x: x[-1]['result'].update(deprecation_notice='retired soon'), '', id='deprecat'),
    pytest.param(lambda x: x[-1]['result'].update(substitution={'to': OTHER}), '', id='substitut'),
    pytest.param(lambda x: x[0]['init'].update(rerouted_to=OTHER), '', id='rerouted'),
    pytest.param(None, f'\x1b[1m{HIGH} is no longer\x1b[0m available. Using {OTHER}\n', id='stderr-ansi-split'),
]


@pytest.mark.parametrize('change, stderr', REVIEWER_REJECTS + NESTED_REJECTS)
def test_every_nested_identity_or_reroute_signal_is_an_identity_error(change, stderr):
    data = stream(HIGH, change)
    with pytest.raises(AgyIdentityError):
        parse_stream(data, HIGH, identity_policy=IDENTITY_POLICY, stderr=stderr)
    with pytest.raises(AgyIdentityError):  # the shared runner path, as the reviewer drove it
        parse_gemini(data, 'agy-stream-json', MODEL, native={'argv': HIGH, 'reports': HIGH},
                     identity_policy=IDENTITY_POLICY, stderr=stderr)
    # The scan is always on: without the policy the stream is still not accepted.
    with pytest.raises(AgyIdentityError):
        parse_stream(data, HIGH, stderr=stderr)


def test_reviewer_baseline_and_agreeing_or_falsy_nested_fields_pass():
    parsed = parse_gemini(stream(HIGH), 'agy-stream-json', MODEL, native={'argv': HIGH, 'reports': HIGH},
                          identity_policy=IDENTITY_POLICY, stderr='Loaded cached credentials.\n')
    assert (parsed['reported_model'], parsed['native_reported_model']) == (MODEL, HIGH)

    def agreeing(data):
        data[0]['init'].update(modelVersion=HIGH, model_name=HIGH, ModelId=HIGH, models={HIGH: {'tokens': 1}})
        data[1]['step_update'].update(metadata={'model': HIGH, 'model_id': HIGH})
        data[-1]['result']['usage'].update(model=HIGH, models={HIGH: {'input': 5}}, model_version=HIGH)
        data[-1]['result'].update(models={}, selected_model=HIGH)

    def falsy(data):
        data[0]['init'].update(models=None, resolved=False, unresolved_tools=[])
        data[-1]['result'].update(used_non_gemini_model=False, retry_model_capacity_exhausted=False,
                                  model_substituted=False, downgraded_from=None, deprecation_notice='')
        data[-1]['result']['usage'].update(capacity_exhausted=0, substitutions=[])
    for change in (agreeing, falsy):
        result = parse_stream(stream(HIGH, change), HIGH, identity_policy=IDENTITY_POLICY, stderr='')
        assert result['reported_model'] == HIGH and result['content'] == '{}'
        assert parse_stream(stream(HIGH, change), HIGH)['reported_model'] is None


# AG-3: tool-registry and subagent violations are their own identity subclass.
def test_tool_registry_violations_raise_their_own_identity_subclass():
    assert issubclass(agy_protocol.AgyToolRegistryError, AgyIdentityError)
    for change in (lambda x: x[0]['init'].update(tools=['read_file']),
                   lambda x: x[0]['init'].pop('tools'),
                   lambda x: x[0]['init'].update(tools=None),
                   lambda x: x[1]['step_update'].update(tool_name='run_shell'),
                   lambda x: x[1]['step_update'].update(tool_info={}),
                   lambda x: x[2]['step_update'].update(subagent_info={'name': 'helper'})):
        for policy in (IDENTITY_POLICY, None):
            with pytest.raises(agy_protocol.AgyToolRegistryError):
                parse_stream(stream(HIGH, change), HIGH, identity_policy=policy)
    for change, stderr in ((lambda x: x[0]['init'].update(model=FAMILY), ''),
                           (lambda x: x[-1]['result'].update(model_id=FAMILY), ''),
                           (lambda x: x[0]['init'].update(is_fallback=True), ''),
                           (None, 'Model resolved via alias table\n')):
        with pytest.raises(AgyIdentityError) as caught:
            parse_stream(stream(HIGH, change), HIGH, identity_policy=IDENTITY_POLICY, stderr=stderr)
        assert not isinstance(caught.value, agy_protocol.AgyToolRegistryError)
