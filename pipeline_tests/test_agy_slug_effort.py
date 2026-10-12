"""Selector-shape fixtures, not evidence that an installed Agy supports them."""
import copy

import pytest

from cochem_pipeline.agy_protocol import validate_model_bindings
from cochem_pipeline.native_effort import effort_contract
from cochem_pipeline.worker import provider_command
from cochem_supervisor.probes import _reviewed_effort_contract
from pipeline_tests.test_native_effort import reviewed_fixture


def fixture(tmp_path, effort):
    model, spec, contract = reviewed_fixture(tmp_path, 'gemini', effort)
    spec.update(protocol='agy-stream-json', identity_policy='reported-model-equality',
                model_bindings={f'{model}:{effort}': f'gemini-3.1-pro-{effort}'})
    arguments = ['--agent', 'cochem-inference-only', '--input-format', 'stream-json',
                 '--output-format', 'stream-json', '--model', '{model}', '--disable-slash-commands']
    spec['arguments'] = arguments
    spec['inference_only']['arguments'] = arguments
    contract.update(arguments=[], slug_effort=effort, native_metadata=None)
    return model, spec, contract


@pytest.mark.parametrize('effort', ['low', 'medium', 'high'])
def test_explicit_effort_may_be_encoded_in_both_reviewed_model_slugs(tmp_path, effort):
    model, spec, contract = fixture(tmp_path, effort)
    assert effort_contract('gemini', model, effort, spec) == contract
    assert _reviewed_effort_contract('gemini', model, effort, spec) == contract
    argv = provider_command('gemini', ['fixture'], model, 'workspace', spec, effort, inference_only=True)
    assert argv[argv.index('--model') + 1] == f'gemini-3.1-pro-{effort}'
    assert '--effort' not in argv and '--thinking-level' not in argv


@pytest.mark.parametrize('mutation', [
    'wrong_effort', 'flag_and_slug', 'missing_suffix', 'reported_suffix', 'missing_binding',
    'missing_policy', 'wrong_protocol', 'unknown_field', 'missing_slug_field', 'extended',
])
def test_unreviewed_or_contradictory_slug_effort_is_rejected_independently(tmp_path, mutation):
    model, spec, contract = fixture(tmp_path, 'high')
    effort = 'high'
    if mutation == 'wrong_effort': contract['slug_effort'] = 'low'
    if mutation == 'flag_and_slug': contract['arguments'] = ['--effort', 'high']
    if mutation == 'missing_suffix': spec['model_bindings'][model + ':high'] = 'gemini-3.1-pro'
    if mutation == 'reported_suffix':
        spec['model_bindings'][model + ':high'] = dict(argv='gemini-3.1-pro-high', reports='gemini-3.1-pro-low')
    if mutation == 'missing_binding': spec['model_bindings'] = {}
    if mutation == 'missing_policy': spec.pop('identity_policy')
    if mutation == 'wrong_protocol': spec['protocol'] = 'terminal-json'
    if mutation == 'unknown_field': contract['allow_alias'] = True
    if mutation == 'missing_slug_field': contract.pop('slug_effort')
    if mutation == 'extended':
        effort = 'extended'
        spec['effort_contracts'] = {model + ':extended': contract}
        spec['model_bindings'] = {model + ':extended': 'gemini-3.1-pro-high'}
    for validator in (effort_contract, _reviewed_effort_contract):
        with pytest.raises(ValueError):
            validator('gemini', model, effort, copy.deepcopy(spec))


def test_binding_validator_rejects_contradictory_encoded_effort(tmp_path):
    _, spec, contract = fixture(tmp_path, 'high')
    contract['slug_effort'] = 'low'
    with pytest.raises(ValueError):
        validate_model_bindings(spec)
