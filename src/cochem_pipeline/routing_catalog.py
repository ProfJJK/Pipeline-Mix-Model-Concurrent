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
    if raw['schema'] != 'cochem-routing-catalog/1':
        raise ValueError('Unsupported routing catalog schema')
    generation = raw['generation']
    if not isinstance(generation, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', generation):
        raise ValueError('Invalid routing catalog generation')
    tiers = raw['tiers']
    if not isinstance(tiers, Mapping) or set(tiers) != set(TIER_SIZES):
        raise ValueError('Routing catalog requires all ten exact tiers')
    normalized = {}
    for tier, count in TIER_SIZES.items():
        entries = tiers[tier]
        if not isinstance(entries, list) or len(entries) != count:
            raise ValueError('Each tier requires three ordered candidates')
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
            identity = (provider, model)
            if identity in identities:
                raise ValueError('Fallbacks must use distinct underlying models, not different efforts')
            identities.add(identity)
            candidates.append(dict(provider=provider, model=model, reasoning_effort=effort))
        normalized[tier] = candidates
    return dict(schema=raw['schema'], generation=generation, tiers=normalized)


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
