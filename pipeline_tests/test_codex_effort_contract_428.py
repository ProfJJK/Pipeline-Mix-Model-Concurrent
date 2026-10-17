"""Reviewed Codex effort contracts: fixtures only, never native vendor evidence.

The contract pins Codex's own ``-c model_reasoning_effort`` selector to an
exact executable digest and offline version, so the existing preflight records
the same effort evidence it records for Claude and Agy. Configs without Codex
contracts (the running r4) keep loading with the legacy unattested selector.
"""
import hashlib
import json

import pytest

from cochem_pipeline.failures import ProviderFailure
from cochem_pipeline.native_effort import effort_contract, effort_version_evidence, reported_profile
from cochem_pipeline.worker import NativeRunner, provider_command

MODEL = 'gpt-6.1-sol'


def codex_spec(tmp_path, effort='high', **changes):
    binary = tmp_path / 'codex.exe'
    binary.write_bytes(b'reviewed codex contract fixture, not executable')
    contract = dict(arguments=['-c', 'model_reasoning_effort=' + json.dumps(effort)],
        version_arguments=['--version'], executable_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        version='codex-cli 0.160.0', capability_reference='Protocol fixture, not native vendor evidence',
        thinking_enabled=None, native_metadata=None)
    contract.update(changes)
    return dict(executable=str(binary), model=MODEL,
                effort_contracts={f'{MODEL}:{effort}': contract}), contract


def test_configs_without_codex_contracts_keep_the_legacy_selector():
    assert effort_contract('codex', MODEL, 'high', {'executable': 'codex.exe', 'model': MODEL}) is None
    with pytest.raises(ValueError, match='outside the routed contract'):
        effort_contract('codex', MODEL, 'extended', {})


def test_reviewed_codex_contract_selects_the_same_argv_bytes(tmp_path):
    spec, contract = codex_spec(tmp_path)
    assert effort_contract('codex', MODEL, 'high', spec) == contract
    legacy = provider_command('codex', [spec['executable']], MODEL, 'ram-project', {}, 'high',
                              inference_only=True)
    reviewed = provider_command('codex', [spec['executable']], MODEL, 'ram-project', spec, 'high',
                                inference_only=True)
    assert reviewed == legacy
    assert reviewed[reviewed.index('model_reasoning_effort="high"') - 1] == '-c'


@pytest.mark.parametrize('mutation', ['missing', 'level', 'extra_flag', 'metadata', 'thinking',
                                      'digest', 'version_probe', 'provenance', 'shim', 'fields'])
def test_declared_codex_contracts_fail_closed(tmp_path, mutation):
    changes = {'level': dict(arguments=['-c', 'model_reasoning_effort="max"']),
               'extra_flag': dict(arguments=['-c', 'model_reasoning_effort="high"', '--profile', 'x']),
               'metadata': dict(native_metadata={'path': ['reasoning_effort'], 'value': 'high'}),
               'thinking': dict(thinking_enabled=True), 'digest': dict(executable_sha256='abc'),
               'version_probe': dict(version_arguments=['-V']), 'provenance': dict(capability_reference=' ')}
    spec, contract = codex_spec(tmp_path, **changes.get(mutation, {}))
    effort = 'high'
    if mutation == 'missing':
        effort = 'medium'
    elif mutation == 'shim':
        spec['executable'] = spec['executable'][:-4] + '.cmd'
    elif mutation == 'fields':
        contract['slug_effort'] = 'high'
    with pytest.raises(ValueError):
        effort_contract('codex', MODEL, effort, spec)
    with pytest.raises(ValueError):
        provider_command('codex', ['codex.exe'], MODEL, 'ram-project', spec, effort, inference_only=True)


def test_declared_codex_contract_holds_before_any_native_probe(tmp_path):
    spec, _ = codex_spec(tmp_path)
    with pytest.raises(ProviderFailure) as caught:
        NativeRunner(None)._inference_preflight({'route': {'model': MODEL}}, 'codex',
            ['must-not-launch'], spec, None, None, lambda: True, None, {}, 'medium')
    assert caught.value.category == 'compatibility'


def test_preflight_records_codex_version_evidence_before_policy_probes(tmp_path, monkeypatch):
    spec, contract = codex_spec(tmp_path)
    launched = []
    def probe(self, node, identity, argv, workspace, heartbeat, on_launch, launch_options, *, probe_kind, maximum=0):
        launched.append((probe_kind, argv))
        if probe_kind == 'verify_reviewed_effort_version':
            return 'codex-cli 0.160.0\n', {'probe': probe_kind}
        raise RuntimeError('stop after the effort evidence')
    monkeypatch.setattr(NativeRunner, '_policy_probe', probe)
    monkeypatch.setattr('cochem_pipeline.worker.check_native_integration', lambda provider, spec: None)
    runner = NativeRunner(None)
    with pytest.raises(RuntimeError, match='stop after'):
        runner._inference_preflight({'route': {'model': MODEL}}, 'codex', [spec['executable']], spec,
                                    None, None, lambda: True, None, {}, 'high')
    assert launched[0] == ('verify_reviewed_effort_version', [spec['executable'], '--version'])
    assert launched[1][0] == 'enumerate_mcp'
    evidence = effort_version_evidence(contract, 'codex-cli 0.160.0\n', contract['executable_sha256'],
                                       model=MODEL, effort='high')
    assert evidence['requested_profile'] == 'high' and evidence['model'] == MODEL
    assert evidence['executable_sha256'] == contract['executable_sha256']
    assert evidence['version'] == 'codex-cli 0.160.0'


def jsonl(*events):
    return '\n'.join(json.dumps(event) for event in events)


def test_codex_observation_may_confirm_never_contradict(tmp_path):
    spec, _ = codex_spec(tmp_path)
    silent = reported_profile('codex', jsonl({'type': 'thread.started', 'thread_id': 't'}),
                              model=MODEL, effort='high', spec=spec)
    assert silent == {'verified_profile': None, 'native_metadata_path': None, 'observed_native_value': None,
                      'reported_effort': None, 'observation_status': 'not_reported_by_reviewed_cli'}
    confirmed = reported_profile('codex', jsonl({'type': 'turn.started', 'reasoning_effort': 'high'}),
                                 model=MODEL, effort='high', spec=spec)
    assert confirmed['reported_effort'] == 'high' and confirmed['observation_status'] == 'reported_by_native_event'
    with pytest.raises(ValueError, match='contradicts'):
        reported_profile('codex', jsonl({'type': 'turn.started', 'reasoning_effort': 'low'}),
                         model=MODEL, effort='high', spec=spec)
    assert reported_profile('codex', '', model=MODEL, effort='high', spec={}) is None
