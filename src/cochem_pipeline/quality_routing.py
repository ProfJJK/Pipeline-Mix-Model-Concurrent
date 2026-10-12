"""Quality escalation captured by the controller after accepted research.

These functions do not consume or reset execution budgets. Callers must bind
the source route and research receipt to completed jobs before creating a pivot.
Availability backoff never calls this module.
"""
import copy
import hashlib
import json
import re


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid quality routing integer')
    return value


def validate_quality(raw):
    fields = {'schema', 'floor', 'pivot_index', 'leaf_index', 'excluded_models',
              'producer_job_id', 'source_route_sha256', 'research_job_id', 'research_receipt_sha256'}
    if not isinstance(raw, dict) or set(raw) != fields or raw['schema'] != 'cochem-quality-routing/1':
        raise ValueError('Invalid controller quality routing capture')
    _integer(raw['floor'], 1, 10)
    _integer(raw['pivot_index'], 1, 3)
    _integer(raw['leaf_index'], 0, 1000000)
    for field in ('producer_job_id', 'research_job_id'):
        if not isinstance(raw[field], str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', raw[field]):
            raise ValueError('Quality routing requires literal completed job IDs')
    for field in ('source_route_sha256', 'research_receipt_sha256'):
        if not isinstance(raw[field], str) or not re.fullmatch('[0-9a-f]{64}', raw[field]):
            raise ValueError('Quality routing requires immutable evidence digests')
    excluded = raw['excluded_models']
    if not isinstance(excluded, list) or not 1 <= len(excluded) <= raw['pivot_index']:
        raise ValueError('Quality routing exclusions must be bounded by pivots')
    identities = set()
    for item in excluded:
        if (not isinstance(item, dict) or set(item) != {'provider', 'model'}
                or item['provider'] not in ('codex', 'claude', 'gemini')
                or not isinstance(item['model'], str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,199}', item['model'])):
            raise ValueError('Invalid excluded producing model')
        identities.add((item['provider'], item['model']))
    if len(identities) != len(excluded):
        raise ValueError('Duplicate producing model exclusion')
    return copy.deepcopy(raw)


def next_quality_pivot(previous, *, route, leaf_index, pivot_index, producer_job_id,
                       research_job_id, research_receipt_sha256):
    score = _integer(route.get('score'), 1, 10)
    _integer(pivot_index, 1, 3)
    old = validate_quality(previous) if previous is not None else None
    if old is not None and (old['leaf_index'] != leaf_index or score < old['floor']
                            or pivot_index <= old['pivot_index']):
        raise ValueError('Quality pivot cannot change leaf, lower the floor or reset its budget')
    # A prior research escalation may consume a pivot while holding execution.
    # The caller's durable pivot budget remains authoritative; never reset it.
    excluded = old['excluded_models'] if old and old['floor'] == 10 else []
    producer = dict(provider=route.get('provider'), model=route.get('model'))
    if producer not in excluded:
        excluded.append(producer)
    return validate_quality(dict(schema='cochem-quality-routing/1', floor=min(10, score + 1),
        pivot_index=pivot_index, leaf_index=leaf_index, excluded_models=excluded,
        producer_job_id=producer_job_id, research_job_id=research_job_id,
        research_receipt_sha256=research_receipt_sha256,
        source_route_sha256=hashlib.sha256(json.dumps(route, sort_keys=True, separators=(',', ':'),
            ensure_ascii=False, allow_nan=False).encode()).hexdigest()))


def apply_quality_floor(score, quality):
    quality = validate_quality(quality)
    if score.get('policy_version') != 2:
        raise ValueError('Quality escalation requires explicitly versioned granular scoring')
    result = copy.deepcopy(score)
    result['base_score'] = score['score']
    result['score'] = max(score['score'], quality['floor'])
    result['tier'] = str(result['score'])
    result['quality_routing'] = quality
    result['rationale'].append(dict(criterion='quality_pivot_floor', points=result['score'] - score['score']))
    return result
