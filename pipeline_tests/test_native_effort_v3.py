"""Exact argument construction only; fixtures never launch a provider."""
import pytest
from pipeline_tests.test_native_effort import reviewed_fixture
from cochem_pipeline.native_effort import effort_contract
from cochem_pipeline.worker import provider_command, codex_policy_probe_command
from cochem_supervisor.runner import repair_command
from cochem_supervisor.probes import _reviewed_effort_contract


@pytest.mark.parametrize('effort', ['low', 'medium', 'high', 'xhigh', 'max'])
def test_claude_explicit_effort_requires_exact_reviewed_binding(tmp_path, effort):
    model, spec, contract = reviewed_fixture(tmp_path, effort=effort)
    contract['arguments'] = ['--effort', effort]
    contract['native_metadata']['value'] = effort
    argv = provider_command('claude', [spec['executable']], model, 'fixture', spec, effort, inference_only=True)
    assert argv[argv.index('--effort') + 1] == effort
    assert repair_command(spec, [spec['executable']], 'fixture') == argv
    assert _reviewed_effort_contract('claude', model, effort, spec) == contract
    contract['arguments'][1] = 'low' if effort != 'low' else 'high'
    with pytest.raises(ValueError):
        effort_contract('claude', model, effort, spec)


@pytest.mark.parametrize('effort', ['low', 'medium', 'high'])
def test_gemini_explicit_effort_cannot_be_remapped(tmp_path, effort):
    model, spec, contract = reviewed_fixture(tmp_path, provider='gemini', effort=effort)
    contract['arguments'] = ['--thinking-level', effort]
    contract['native_metadata']['value'] = effort
    assert effort_contract('gemini', model, effort, spec) == contract
    assert _reviewed_effort_contract('gemini', model, effort, spec) == contract
    contract['arguments'][1] = 'high' if effort != 'high' else 'low'
    with pytest.raises(ValueError):
        effort_contract('gemini', model, effort, spec)


@pytest.mark.parametrize('effort', ['xhigh', 'max'])
def test_codex_explicit_effort_reaches_both_probe_and_inference_argv(effort):
    probe = codex_policy_probe_command(['fixture'], 'auth', reasoning_effort=effort)
    argv = provider_command('codex', ['fixture'], 'gpt-6.1-sol', 'fixture', {}, effort, inference_only=True)
    assert f'model_reasoning_effort="{effort}"' in probe
    assert f'model_reasoning_effort="{effort}"' in argv


def test_explicit_claude_metadata_must_not_attest_different_effort(tmp_path):
    model, spec, contract = reviewed_fixture(tmp_path, effort='high')
    contract['arguments'] = ['--effort', 'high']
    with pytest.raises(ValueError):
        effort_contract('claude', model, 'high', spec)


@pytest.mark.parametrize('effort', ['low', 'medium', 'high'])
def test_agy_binding_accepts_explicit_effort_slug(effort):
    from pipeline_tests.test_agy_protocol import policy_spec
    from cochem_pipeline.agy_protocol import native_model_binding
    key = f'gemini-3.8-flash:{effort}'
    slug = f'gemini-3.8-flash-{effort}'
    spec = policy_spec({key: slug}, {key: {'arguments': ['--effort', effort]}})
    assert native_model_binding(spec, 'gemini-3.8-flash', effort) == dict(argv=slug, reports=slug)
