import copy
import json

import pytest

from cochem_pipeline.r6_candidate import BINARIES, NATIVE, ROOT, from_commissioned_bytes, propose
from pipeline_tests.test_config import config_document


def base(tmp_path):
    raw = config_document(tmp_path)
    raw['max_execution_slots'] = 4
    raw['knowledge'] = dict(enabled=True, source_root='OLD', wiki_root='OLD', manifest_path='OLD', state_root='OLD')
    for provider, (filename, _, _) in BINARIES.items():
        raw['providers'][provider]['executable'] = str(NATIVE / filename)
    raw['providers']['gemini']['integration_hold'] = {'private_fixture': 'original hold retained'}
    return raw


def test_proposal_preserves_all_unrelated_policy_and_original_hold(tmp_path):
    raw = base(tmp_path)
    before = copy.deepcopy(raw)
    candidate, plan = propose(raw)
    assert raw == before
    for key in raw.keys() - {'routing', 'providers', 'knowledge'}:
        assert candidate[key] == raw[key]
    assert candidate['providers']['codex'] == raw['providers']['codex']
    assert 'integration_hold' not in candidate['providers']['gemini']
    assert plan['activation_ready'] is False and plan['host_accepted'] is False
    assert plan['preparation_status'] == 'COMMAND_TEMPLATES_VALID'
    assert len(plan['targets']) == 27
    assert all(t['actual_effort_verified'] is False for t in plan['targets'])
    assert 'original hold retained' not in json.dumps(plan)
    assert candidate['knowledge']['source_root'].startswith(str(ROOT))


def test_exact_efforts_and_pro_high_are_retained_without_aliases(tmp_path):
    candidate, _ = propose(base(tmp_path))
    pro = candidate['routing']['tiers']['6'][2]
    assert pro == dict(provider='gemini', model='gemini-3.1-pro', reasoning_effort='high')
    spec = candidate['providers']['gemini']
    assert spec['model_bindings']['gemini-3.1-pro:high'] == 'gemini-3.1-pro-high'
    assert spec['effort_contracts']['gemini-3.1-pro:high']['arguments'] == []
    for contract in candidate['providers']['claude']['effort_contracts'].values():
        assert contract['native_metadata'] is None
        assert contract['arguments'][0] == '--effort'


@pytest.mark.parametrize('mutation', ['slots', 'workers', 'binary', 'hold', 'knowledge'])
def test_changed_foundation_is_not_silently_repaired(tmp_path, mutation):
    raw = base(tmp_path)
    if mutation == 'slots': raw['max_execution_slots'] = 6
    if mutation == 'workers': raw['workers'].pop(next(iter(raw['workers'])))
    if mutation == 'binary': raw['providers']['claude']['executable'] = 'C:\\other.exe'
    if mutation == 'hold': raw['providers']['codex']['integration_hold'] = {}
    if mutation == 'knowledge': raw['knowledge']['enabled'] = False
    with pytest.raises(ValueError):
        propose(raw)


def test_production_entry_requires_exact_commissioned_bytes():
    with pytest.raises(ValueError, match='reviewed base'):
        from_commissioned_bytes(b'{}')
