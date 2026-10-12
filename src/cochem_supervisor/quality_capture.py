"""Frozen supervisor decoder for controller-captured quality routing metadata.

This checks capture consistency; it does not attest an OS process or replay the
source coding workflow's completed research/producer receipts.
"""
import copy
import re


def apply_captured_floor(score, quality, *, kind, leaf_index):
    fields = {'schema', 'floor', 'pivot_index', 'leaf_index', 'excluded_models',
              'producer_job_id', 'source_route_sha256', 'research_job_id', 'research_receipt_sha256'}
    if (kind not in ('CODE_EDIT', 'CODE_TEST_AUTHOR', 'CODE_REVIEW', 'CODE_RESEARCH')
            or not isinstance(quality, dict) or set(quality) != fields
            or quality['schema'] != 'cochem-quality-routing/1' or score.get('policy_version') != 2):
        raise ValueError('Invalid controller quality routing capture')
    for name, low, high in [('floor', 1, 10), ('pivot_index', 1, 3), ('leaf_index', 0, 1000000)]:
        if type(quality[name]) is not int or not low <= quality[name] <= high:
            raise ValueError('Invalid quality routing bound')
    if type(leaf_index) is not int or leaf_index != quality['leaf_index']:
        raise ValueError('Quality routing leaf differs from the dispatched task')
    for key in ('producer_job_id', 'research_job_id'):
        if not isinstance(quality[key], str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', quality[key]):
            raise ValueError('Invalid quality routing source job')
    for key in ('source_route_sha256', 'research_receipt_sha256'):
        if not isinstance(quality[key], str) or not re.fullmatch('[0-9a-f]{64}', quality[key]):
            raise ValueError('Invalid quality routing evidence digest')
    excluded = quality['excluded_models']
    if not isinstance(excluded, list) or not 1 <= len(excluded) <= quality['pivot_index']:
        raise ValueError('Invalid quality routing exclusions')
    identities = []
    for item in excluded:
        if (not isinstance(item, dict) or set(item) != {'provider', 'model'}
                or item['provider'] not in ('codex', 'claude', 'gemini')
                or not isinstance(item['model'], str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,199}', item['model'])):
            raise ValueError('Invalid quality routing model exclusion')
        identities.append((item['provider'], item['model']))
    if len(set(identities)) != len(identities):
        raise ValueError('Duplicate quality routing exclusion')
    result = copy.deepcopy(score)
    result['base_score'] = score['score']
    result['score'] = max(score['score'], quality['floor'])
    result['tier'] = str(result['score'])
    result['quality_routing'] = copy.deepcopy(quality)
    result['rationale'].append({'criterion': 'quality_pivot_floor', 'points': result['score'] - score['score']})
    return result
