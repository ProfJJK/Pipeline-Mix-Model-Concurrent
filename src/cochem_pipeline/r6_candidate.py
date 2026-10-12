"""Prepare the owner's R6 configuration without activating or attesting it.

The explicit native selectors below are proposals for the protected acceptance
run. They are never evidence that a subscription accepted a model or effort.
The commissioned configuration remains byte-for-byte untouched.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import PureWindowsPath

from .agy_agent_guard import RELATIVES
from .native_acceptance_plan import build_plan
from .routing import RoutingPolicy
from .worker import strict_json


BASE_SHA256 = '135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
ROOT = PureWindowsPath(r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261012-r6-v1')
NATIVE = PureWindowsPath(r'C:\Program Files\CoChem\Native4.2.7-windows-20261006')
BINARIES = {
    'codex': ('codex.exe', 'fdda5fa3cf3fb3d000b876720742857676293e4315e4b045fae6f8bd7e866d1d', 'codex-cli 0.160.0'),
    'claude': ('claude.exe', '0e4195524b73eb77efbdf3e2b36de5322a29f0ca575dfd2d9b4f946b1d425469', '2.1.280 (Claude Code)'),
    'gemini': ('agy.exe', '38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741', '1.3.1'),
}
PROPOSAL_REFERENCE = 'R6 owner matrix 2026-10-11; proposed explicit selectors; native acceptance required'
AGY_ARGS = ['--agent', 'cochem-inference-only', '--input-format', 'stream-json',
            '--output-format', 'stream-json', '--model', '{model}', '--disable-slash-commands']


def propose(base):
    """Pure transformation, also usable with fixture inputs; no file/CLI access."""
    candidate = copy.deepcopy(base)
    if candidate.get('max_execution_slots') != 4 or len(candidate.get('workers', {})) != 6:
        raise ValueError('R6 requires the existing four shared slots and six identities')
    providers = candidate['providers']
    for provider, (filename, _, _) in BINARIES.items():
        if PureWindowsPath(providers[provider]['executable']) != NATIVE / filename:
            raise ValueError('R6 proposal must preserve the reviewed native executable')
        if provider != 'gemini' and 'integration_hold' in providers[provider]:
            raise ValueError('An additional integration hold needs explicit review')
    candidate['routing'] = RoutingPolicy.from_dict({'policy_version': 3}).as_dict()
    gemini = providers['gemini']
    # This is a separate proposal, not an update/release of the installed hold.
    gemini.pop('integration_hold', None)
    gemini.update(protocol='agy-stream-json', identity_policy='reported-model-equality',
        arguments=list(AGY_ARGS), model_bindings={}, effort_contracts={},
        subscription_probe={'arguments': ['--output-format', 'json', 'models'],
            'protocol': 'json-fields', 'expected': {'status': 'SUCCESS', 'command.name': 'models'}},
        agent_definition={'name': 'cochem-inference-only', 'bytes': 478,
            'sha256': '5c0082d70d073263a56d748a46187008968c070d0efc7d5b7612c2fd61d11810',
            'relative_paths': list(RELATIVES)})
    gemini['inference_only'] = dict(arguments=list(AGY_ARGS), version_arguments=['--version'],
        executable_sha256=BINARIES['gemini'][1], version=BINARIES['gemini'][2],
        capability_reference=PROPOSAL_REFERENCE, disables_tools=True, disables_mcp=True,
        disables_hooks=True, disables_subagents=True, disables_model_fallback=True)
    providers['claude']['effort_contracts'] = {}
    for rows in candidate['routing']['tiers'].values():
        for row in rows:
            provider, model, effort = (row[k] for k in ('provider', 'model', 'reasoning_effort'))
            if provider == 'codex':
                continue
            contract = dict(arguments=['--effort', effort] if provider == 'claude' else [],
                version_arguments=['--version'], executable_sha256=BINARIES[provider][1],
                version=BINARIES[provider][2], capability_reference=PROPOSAL_REFERENCE,
                native_metadata=None, thinking_enabled=True if provider == 'claude' else None)
            if provider == 'gemini':
                contract['slug_effort'] = effort
                gemini['model_bindings'][f'{model}:{effort}'] = f'{model}-{effort}'
            providers[provider]['effort_contracts'][f'{model}:{effort}'] = contract
    knowledge = candidate['knowledge']
    if knowledge.get('enabled') is not True:
        raise ValueError('R6 preserves enabled private knowledge')
    corpus = ROOT / 'source' / 'knowledge'
    knowledge.update(source_root=str(corpus / '.sources'), wiki_root=str(corpus / 'wiki'),
        manifest_path=str(corpus / 'v4.1.2_manifest.json'),
        state_root=str(PureWindowsPath(candidate['private_root']) / 'knowledge-windows-20261012-r6-v1'))
    # No credentials, project registrations, budgets, RAM or control state edits.
    if any(candidate[k] != base[k] for k in base.keys() - {'routing', 'providers', 'knowledge'}):
        raise ValueError('R6 proposal changed an unrelated setting')
    plan = build_plan(candidate)
    if plan['preparation_status'] != 'COMMAND_TEMPLATES_VALID':
        raise ValueError('R6 proposal does not compile all approved native targets')
    return candidate, plan


def from_commissioned_bytes(raw):
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != BASE_SHA256:
        raise ValueError('Commissioned configuration does not match the reviewed base')
    return propose(strict_json(raw.decode('utf-8-sig')))
