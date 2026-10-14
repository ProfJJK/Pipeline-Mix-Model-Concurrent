"""Versioned routing data. Validation does not prove native CLI availability."""
from collections.abc import Mapping
import json
from pathlib import Path
import re


EFFORTS = {
    'codex': {'low', 'medium', 'high', 'xhigh', 'max'},
    'claude': {'low', 'medium', 'high', 'xhigh', 'max'},
    'gemini': {'low', 'medium', 'high'},
}
TIER_SIZES = {str(tier): 3 for tier in range(1, 11)}


def validate_catalog(raw):
    if not isinstance(raw, Mapping) or set(raw) != {'schema', 'generation', 'tiers'}:
        raise ValueError('Routing catalog requires schema, generation and tiers')
    if raw['schema'] not in ('cochem-routing-catalog/1', 'cochem-routing-catalog/2', 'cochem-routing-catalog/3'):
        raise ValueError('Unsupported routing catalog schema')
    generation = raw['generation']
    if not isinstance(generation, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', generation):
        raise ValueError('Invalid routing catalog generation')
    scoped = raw['schema'] == 'cochem-routing-catalog/3'
    if scoped and not re.fullmatch(r'planning428-[a-f0-9]{32}', generation):
        raise ValueError('Scoped planning catalog requires a captured intent generation')
    tiers = raw['tiers']
    if not isinstance(tiers, Mapping) or set(tiers) != set(TIER_SIZES):
        raise ValueError('Routing catalog requires all ten exact tiers')
    normalized = {}
    for tier, count in TIER_SIZES.items():
        entries = tiers[tier]
        allowed = (count,) if raw['schema'] == 'cochem-routing-catalog/1' else (2, 3)
        if scoped:
            allowed = (1, 2, 3, 4, 5)
        if not isinstance(entries, list) or len(entries) not in allowed:
            raise ValueError('Each tier requires its versioned two or three ordered candidates')
        candidates, identities = [], set()
        for entry in entries:
            if not isinstance(entry, Mapping) or set(entry) != {'provider', 'model', 'reasoning_effort'}:
                raise ValueError('Catalog entries require explicit provider, model and effort')
            provider, model, effort = (entry[key] for key in ('provider', 'model', 'reasoning_effort'))
            if not isinstance(provider, str) or provider not in EFFORTS:
                raise ValueError('Unknown catalog provider')
            if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,199}', model):
                raise ValueError('Invalid explicit model identifier')
            if not isinstance(effort, str) or effort not in EFFORTS[provider]:
                raise ValueError('Unsupported explicit catalog reasoning effort')
            identity = (provider, model, effort) if scoped else (provider, model)
            if identity in identities:
                raise ValueError('Fallbacks must use distinct underlying models, not different efforts')
            identities.add(identity)
            candidates.append(dict(provider=provider, model=model, reasoning_effort=effort))
        normalized[tier] = candidates
    if scoped and any(value != normalized['1'] for value in normalized.values()):
        raise ValueError('Scoped planning catalog must preserve the same eligible candidates')
    return dict(schema=raw['schema'], generation=generation, tiers=normalized)


def retire_owner_gemini_pro(catalog):
    """Owner's 2026-10-12 withdrawal; preserve the two surviving reasoning floors.

    This produces a new generation. It never edits a captured policy or assumes
    Flash High is a substitute for Pro High at the medium tiers.
    """
    value = validate_catalog(catalog)
    if value != default_catalog():
        raise ValueError('Retirement must start from the exact approved owner catalog')
    withdrawn = dict(provider='gemini', model='gemini-3.1-pro', reasoning_effort='high')
    for tier in ('5', '6'):
        if value['tiers'][tier][-1] != withdrawn:
            raise ValueError('The owner-reviewed Pro fallback differs')
        value['tiers'][tier].pop()
    value.update(schema='cochem-routing-catalog/2', generation='owner-2026-10-12-pro-retired')
    return validate_catalog(value)


def default_catalog():
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate routing catalog field')
            result[key] = value
        return result
    path = Path(__file__).parent / 'specification' / 'routing_catalog_v3.json'
    return validate_catalog(json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique))
