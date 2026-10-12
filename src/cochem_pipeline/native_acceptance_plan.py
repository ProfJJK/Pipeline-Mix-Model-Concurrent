"""Compile an R6 host-acceptance work list without executing native programs.

This is preparation, not a receipt validator or an authorization to launch.
The owner-run executor must verify the protected candidate and runtime again.
One model/effort probe covers only its assigned worker, never all six accounts.
"""
from __future__ import annotations

import hashlib
import json
import re

from .agy_agent_guard import require_agent_contract
from .config import validate_gemini_contract
from .native_effort import effort_contract
from .routing import RoutingPolicy
from .routing_catalog import default_catalog
from .worker import provider_command


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def build_plan(candidate):
    """Return deterministic sanitized preparation bound to a candidate's bytes-as-JSON.

The candidate digest uses canonical JSON, not the file byte hash. The installer
must additionally pin the exact staged file. No credential values, native stdout,
exception messages, or arbitrary provider fields enter the returned projection.
"""
    if not isinstance(candidate, dict):
        raise ValueError('Acceptance preparation requires a candidate object')
    candidate_hash = digest(candidate)
    routing = RoutingPolicy.from_dict(candidate.get('routing')).as_dict()
    if routing['policy_version'] != 3 or routing['catalog'] != default_catalog():
        raise ValueError('R6 acceptance preparation requires the exact approved owner catalog')
    workers, roots = candidate.get('workers'), candidate.get('slot_roots')
    if (type(candidate.get('max_execution_slots')) is not int
            or candidate['max_execution_slots'] != 4
            or not isinstance(workers, dict) or len(workers) != 6
            or not isinstance(roots, dict) or set(workers) != set(roots)
            or any(not isinstance(key, str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}', key)
                   for key in workers)):
        raise ValueError('R6 acceptance preserves four shared slots and six worker identities')
    names = []
    for identity in workers.values():
        if (not isinstance(identity, dict) or not isinstance(identity.get('name'), str)
                or not identity['name'].strip()):
            raise ValueError('Acceptance requires named worker identities')
        names.append(identity['name'].casefold())
    if len(set(names)) != 6:
        raise ValueError('Acceptance requires six distinct worker identities')
    providers = candidate.get('providers')
    if not isinstance(providers, dict) or any(
            not isinstance(providers.get(provider), dict) for provider in ('codex', 'claude', 'gemini')):
        raise ValueError('Acceptance requires all three provider specifications')

    targets = {}
    for tier in range(1, 11):
        for choice, target in enumerate(routing['tiers'][str(tier)], start=1):
            key = (target['provider'], target['model'], target['reasoning_effort'])
            if key not in targets:
                targets[key] = dict(target, route_positions=[])
            targets[key]['route_positions'].append(dict(tier=tier, choice=choice))
    identities = sorted(workers)
    for index, row in enumerate(targets.values()):
        provider, model, effort = row['provider'], row['model'], row['reasoning_effort']
        spec = providers[provider]
        row.update(worker=identities[index % len(identities)], acceptance_status='NOT_RUN',
                   actual_effort_verified=False, preparation_status='HELD',
                   command_template_sha256=None, effort_contract_sha256=None,
                   hold_code='REVIEWED_BINDING_REQUIRED')
        if 'integration_hold' in spec:
            # Leave validation of protected evidence to the native boundary.
            # Even a malformed hold cannot become a preparation-time release.
            row['hold_code'] = 'INTEGRATION_HOLD_PRESENT'
            continue
        try:
            contract = effort_contract(provider, model, effort, spec)
            if provider == 'gemini':
                validate_gemini_contract(spec)
                require_agent_contract(spec)
            argv = provider_command(provider, ['<protected-executable>'], model,
                '<disposable-acceptance-workspace>', spec, effort, inference_only=True)
        except (ValueError, KeyError, TypeError):
            # A partial review may prepare the other targets, but must not make
            # a missing selector silently disappear from the acceptance list.
            continue
        row.update(preparation_status='COMMAND_TEMPLATE_VALID', hold_code=None,
                   command_template_sha256=digest(argv),
                   effort_contract_sha256=digest(contract) if contract is not None else None)

    result = dict(schema='cochem-r6-native-acceptance-plan/1',
        candidate_sha256=candidate_hash, candidate_digest_format='canonical-json-sha256',
        routing_sha256=digest(routing), catalog_generation=routing['catalog']['generation'],
        targets=list(targets.values()),
        authentication_checks=[dict(worker=worker, provider=provider, status='NOT_RUN')
            for worker in identities for provider in ('codex', 'claude', 'gemini')],
        model_coverage='one_assigned_worker_per_distinct_model_and_effort',
        authentication_coverage='all_six_workers_all_three_providers',
        max_execution_slots=4, max_parallel_probes=1,
        interactive_stage='authentication_before_unattended_work',
        late_authentication_action='hold_without_prompt',
        required_host_evidence=['protected_runtime_and_candidate_pins',
            'native_binary_hash_and_version', 'subscription_authentication',
            'inference_only_policy', 'native_reported_model_identity',
            'effort_selector_acceptance_and_observation_status',
            'owned_process_tree_cleanup'],
        host_accepted=False, activation_ready=False,
        preparation_status=('BINDING_INPUTS_REQUIRED' if any(
            row['hold_code'] for row in targets.values()) else 'COMMAND_TEMPLATES_VALID'))
    result['plan_sha256'] = digest(result)
    return result
