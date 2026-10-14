"""4.2.8 task-type policy compiler and pure selection rules.

This module prepares decisions, not native dispatch authority. Owner-supplied
benchmark values remain explicitly unverified until a reviewed evidence catalog
replaces them. Installed CLI acceptance and Chapter 06 reservations are separate.
No source formula, model text or URL is executed.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re

TASK_TYPES = {
    'AGT-PROJ': 'Repository-wide projects, orchestration and multi-step synthesis',
    'AGT-DELIV': 'Professional artifact creation and presentation',
    'AGT-AUTO': 'Tool and service workflow automation',
    'COD-TERM': 'Software implementation and terminal-based diagnosis',
    'COD-SCI': 'Scientific computing and numerical implementation',
    'SCI-FRONT': 'Advanced scientific research and reasoning',
    'SCI-FORMAL': 'Formal, mathematical and physics reasoning',
    'GEN-FACT': 'Factual research and source-grounded answers',
    'GEN-DOC': 'Document interpretation and grounded extraction',
    'GEN-LCR': 'Long-context integration and reasoning',
    'GEN-DEFAULT': 'General tasks with no more specific category',
}
_FAMILIES = {
    'luna': ('codex', 'gpt-6-luna'), 'sol': ('codex', 'gpt-6.1-sol'),
    'astra': ('codex', 'gpt-6-astra'), 'haiku': ('claude', 'claude-haiku-5-5'),
    'sonnet': ('claude', 'claude-sonnet-5-5'), 'opus': ('claude', 'claude-opus-5-5'),
    'fable': ('claude', 'claude-fable-5-1'), 'flash38': ('gemini', 'gemini-3.8-flash'),
    'argon': ('gemini', 'gemini-4-argon'),
}
_VENDORS = {'codex': 'OpenAI', 'claude': 'Anthropic', 'gemini': 'Google'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer in {low}..{high}')
    return value


def _number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    return value


def validate_task_tags(tags):
    if (not isinstance(tags, list) or not 1 <= len(tags) <= 10
            or any(not isinstance(tag, str) or tag not in TASK_TYPES for tag in tags)
            or len(set(tags)) != len(tags)
            or ('GEN-DEFAULT' in tags and len(tags) != 1)):
        raise ValueError('Task tags require distinct known types; general is exclusive')
    return sorted(tags)


def _identity(model_id):
    if model_id == 'flash35-lite':
        return dict(provider='gemini', model='gemini-3.5-flash-lite',
                    family='gemini-3.5-flash-lite', effort=None)
    try:
        prefix, effort = model_id.rsplit('-', 1)
        provider, model = _FAMILIES[prefix]
    except (ValueError, KeyError, AttributeError) as exc:
        raise ValueError('Unknown model identity in owner matrix') from exc
    effort = 'medium' if effort == 'med' else effort
    if effort not in ('low', 'medium', 'high', 'xhigh', 'max') or (
            provider == 'gemini' and effort not in ('low', 'medium', 'high')):
        raise ValueError('Unsupported candidate model effort')
    return dict(provider=provider, model=model, family=model, effort=effort)


def _validate_owner(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get('models'), dict):
        raise ValueError('Owner matrix must contain models')
    models = raw['models']
    if not 1 <= len(models) <= 100:
        raise ValueError('Model catalog is unbounded')
    for model_id, model in models.items():
        identity = _identity(model_id)
        if not isinstance(model, dict) or model.get('provider') != _VENDORS[identity['provider']]:
            raise ValueError('Model provider differs from explicit identity')
        if not isinstance(model.get('scores'), dict) or set(model['scores']) != set(TASK_TYPES):
            raise ValueError('Each model requires all task-type scores')
        for tag, score in model['scores'].items():
            _number(score, 'Benchmark score')
            low, high = (-100, 100) if tag == 'GEN-FACT' else (
                (0, 10000) if tag in ('AGT-PROJ', 'AGT-DELIV') else (0, 100))
            if not low <= score <= high:
                raise ValueError('Benchmark score is outside its native scale')
        if _number(model.get('costPerTask'), 'Reference cost') < 0:
            raise ValueError('Reference cost cannot be negative')
    matrix = raw.get('taskRoutingMatrix')
    if not isinstance(matrix, dict) or set(matrix) != set(TASK_TYPES):
        raise ValueError('Matrix requires all eleven task types')
    for tag, spec in matrix.items():
        tiers = spec.get('tiers') if isinstance(spec, dict) else None
        if not isinstance(tiers, dict) or set(tiers) != {str(i) for i in range(1, 11)}:
            raise ValueError('Task type requires all ten tiers')
        last_floor = -math.inf
        for tier in range(1, 11):
            row = tiers[str(tier)]
            if not isinstance(row, dict) or set(row) != {'floor', 'choices', 'auditor', 'degradedSlots'}:
                raise ValueError('Invalid owner routing row')
            floor = _number(row['floor'], 'Reasoning floor')
            if floor < last_floor:
                raise ValueError('Task-type floors must not decrease with complexity')
            last_floor = floor
            choices = row['choices']
            if (not isinstance(choices, list) or not 1 <= len(choices) <= 5
                    or any(not isinstance(x, str) or x not in models for x in choices)
                    or len(set(choices)) != len(choices) or row['auditor'] not in models
                    or not isinstance(row['degradedSlots'], list)
                    or any(x not in choices for x in row['degradedSlots'])):
                raise ValueError('Routing references unknown or duplicate models')
    return models, matrix


def audit_owner_matrix(raw):
    models, matrix = _validate_owner(raw)
    findings = []
    for tag, spec in matrix.items():
        for tier_text, row in spec['tiers'].items():
            tier = int(tier_text)
            def finding(code, model_id, **extra):
                findings.append(dict(task_type=tag, tier=tier, code=code,
                                     model_id=model_id, **extra))
            for model_id in row['choices']:
                score = models[model_id]['scores'][tag]
                if score < row['floor']:
                    finding('BELOW_FLOOR_MARKED' if model_id in row['degradedSlots']
                            else 'BELOW_FLOOR_UNMARKED', model_id, score=score, floor=row['floor'])
            reviewer = row['auditor']
            next_floor = spec['tiers'][str(min(10, tier + 1))]['floor']
            if models[reviewer]['scores'][tag] < next_floor:
                finding('REVIEWER_BELOW_NEXT_TIER', reviewer, floor=next_floor,
                        score=models[reviewer]['scores'][tag])
            if any(_identity(x)['family'] == _identity(reviewer)['family'] for x in row['choices']):
                finding('REVIEWER_CAN_BE_PRODUCER', reviewer)
            families = [_identity(x)['family'] for x in row['choices']]
            if len(set(families)) != len(families):
                finding('FALLBACK_REPEATS_UNDERLYING_MODEL', None)
    return dict(schema='cochem-task-routing-audit/1', source_sha256=digest(raw),
        model_count=len(models), row_count=sum(len(x['tiers']) for x in matrix.values()),
        findings=findings, source_provenance='owner_supplied_benchmark_claims',
        benchmark_scores_verified=False, activation_ready=False,
        policy_conflicts=['per-failure escalation conflicts with ten-cycle quality pivot',
            'API benchmark cost is not subscription quota usage',
            'fixed auditor can equal actual fallback producer',
            'weighted composite scores cannot replace individual task-type floors',
            'full-jitter label conflicts with additive-jitter formula'])


def compile_matrix(raw, observations=None):
    """Produce a conservative, versioned candidate without attesting its scores."""
    models, matrix = _validate_owner(raw)
    result = dict(schema='cochem-task-routing/1', generation='4.2.8-owner-20261013-audited-v1',
        source_sha256=digest(raw), scores_verified=False, host_accepted=False,
        cost_policy='reference_only_not_subscription_quota', models={}, task_types={})
    for model_id, model in models.items():
        result['models'][model_id] = dict(_identity(model_id), name=model['name'],
            scores=deepcopy(model['scores']), reference_cost_per_task=model['costPerTask'],
            score_evidence='OWNER_INPUT_NOT_INDEPENDENTLY_VERIFIED',
            native_acceptance='NOT_RUN', context_limit=None)
    for tag, spec in matrix.items():
        tiers = {}
        for tier, row in spec['tiers'].items():
            seen, choices = set(), []
            for model_id in row['choices']:
                family = result['models'][model_id]['family']
                if models[model_id]['scores'][tag] >= row['floor'] and family not in seen:
                    seen.add(family)
                    choices.append(model_id)
            tiers[tier] = dict(floor=row['floor'], choices=choices)
        result['task_types'][tag] = dict(description=TASK_TYPES[tag],
            benchmark=spec['benchmark'], tiers=tiers)
    if observations is not None:
        _apply_observations(result, raw, observations)
    return result


def _apply_observations(catalog, raw, observations):
    """Use actual publisher values, without interpolating missing effort levels."""
    if (not isinstance(observations, dict)
            or observations.get('schema') != 'cochem-task-benchmark-observations/1'
            or not isinstance(observations.get('models'), dict)):
        raise ValueError('Invalid benchmark observation snapshot')
    available = set()
    for key, model in catalog['models'].items():
        source = observations['models'].get(key)
        if source is None:
            model.update(scores={tag: None for tag in TASK_TYPES},
                         score_evidence='MISSING_PUBLISHED_EFFORT_RESULT')
            continue
        if (source.get('family') != model['family'] or source.get('effort') != model['effort']
                or source.get('estimated') is not False or not isinstance(source.get('url'), str)
                or not source['url'].startswith('https://artificialanalysis.ai/models/')
                or not isinstance(source.get('scores'), dict) or set(source['scores']) != set(TASK_TYPES)):
            raise ValueError('Benchmark observation identity, estimate or provenance differs')
        for tag, score in source['scores'].items():
            _number(score, 'Published benchmark score')
            low, high = (-100, 100) if tag == 'GEN-FACT' else (
                (0, 10000) if tag in ('AGT-PROJ', 'AGT-DELIV') else (0, 100))
            if not low <= score <= high:
                raise ValueError('Published score is outside its native scale')
        if (not isinstance(source.get('page_sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', source['page_sha256'])
                or not isinstance(source.get('name'), str) or not source['name'].strip()):
            raise ValueError('Published score requires a page digest and configuration name')
        _integer(source.get('context_limit'), 1, 10**9, 'Published context window')
        if source.get('cost_per_task') is not None and _number(source['cost_per_task'], 'Cost') < 0:
            raise ValueError('Published reference cost cannot be negative')
        model.update(scores=deepcopy(source['scores']), score_evidence='PUBLISHER_OBSERVED',
            evidence_url=source['url'], evidence_page_sha256=source['page_sha256'],
            observed_configuration=source['name'], context_limit=source['context_limit'],
            reference_cost_per_task=source.get('cost_per_task'))
        available.add(key)
    # Keep the owner's primary/fallback order where supported. Fill removed
    # entries from measured alternatives, lowest reference evaluation cost first.
    # Cost is an explicit proxy, not a claim about this account's quota charge.
    def cost(key):
        value = catalog['models'][key]['reference_cost_per_task']
        return (math.inf if value is None else value, key)
    for tag, spec in catalog['task_types'].items():
        for tier, row in spec['tiers'].items():
            ordered = list(dict.fromkeys(raw['taskRoutingMatrix'][tag]['tiers'][tier]['choices']
                                         + sorted(available, key=cost)))
            choices, seen = [], set()
            for key in ordered:
                model = catalog['models'][key]
                if key not in available or model['family'] in seen or model['scores'][tag] < row['floor']:
                    continue
                seen.add(model['family'])
                choices.append(key)
                if len(choices) == 5:
                    break
            row['choices'] = choices
    catalog.update(generation='4.2.8-publisher-observed-20261013-v1',
        scores_verified=True, missing_score_models=sorted(set(catalog['models']) - available),
        observations_sha256=digest(observations))


def independent_review_calibration(catalog):
    """Separate proposal: cap floors at the second-best measured max-effort family.

    Benchmark scores are routing heuristics, not proof of task success. This
    preserves monotonicity and makes two-family review feasible for each single
    task type. Multi-type intersections may still hold; never average them away.
    This returns a new candidate and an explicit change log, not live authority.
    """
    if catalog.get('scores_verified') is not True:
        raise ValueError('Calibration requires publisher observations')
    result = deepcopy(catalog)
    changes = []
    for tag, spec in result['task_types'].items():
        maxima = {}
        for model in result['models'].values():
            maximum = 'high' if model['provider'] == 'gemini' else 'max'
            score = model['scores'][tag]
            if model['effort'] == maximum and score is not None:
                maxima[model['family']] = max(score, maxima.get(model['family'], -math.inf))
        if len(maxima) < 2:
            raise ValueError('Two measured maximum-effort families are required')
        ceiling = sorted(maxima.values(), reverse=True)[1]
        for tier, row in spec['tiers'].items():
            old = row['floor']
            row['floor'] = min(old, ceiling)
            if old != row['floor']:
                changes.append(dict(task_type=tag, tier=int(tier), old_floor=old,
                                    proposed_floor=row['floor'], reason='two_maximum_effort_model_families'))
            ordered = row['choices'] + list(result['models'])
            seen, choices = set(), []
            for key in ordered:
                model = result['models'][key]
                if (model['scores'][tag] is not None and model['scores'][tag] >= row['floor']
                        and model['family'] not in seen):
                    seen.add(model['family'])
                    choices.append(key)
            row['choices'] = choices[:5]
    result.update(generation='4.2.8-independent-review-calibration-20261013-v1',
                  prior_catalog_sha256=digest(catalog), calibration_changes=changes,
                  activation_ready=False)
    return result


def select_candidates(catalog, tags, complexity, *, available_ids=None, exclude_families=()):
    """Return ordered eligible IDs. Empty means backoff/hold, never lower a floor.

    ``available_ids`` is supplied by a controller's verified availability view;
    omitting it produces a planning projection only. This function launches nothing.
    """
    tags = validate_task_tags(tags)
    tier = str(_integer(complexity, 1, 10, 'Complexity'))
    ordered = []
    for tag in tags:
        ordered.extend(catalog['task_types'][tag]['tiers'][tier]['choices'])
    result, seen = [], set()
    for model_id in ordered:
        model = catalog['models'][model_id]
        if (model_id in seen or model['family'] in exclude_families
                or (available_ids is not None and model_id not in available_ids)):
            continue
        if all(model['scores'][tag] is not None and
               model['scores'][tag] >= catalog['task_types'][tag]['tiers'][tier]['floor'] for tag in tags):
            seen.add(model_id)
            result.append(model_id)
    return result


def five_model_options(catalog, tags, complexity):
    """Five comparison slots, with explicit eligibility rather than fake scores.

    Tiers 1-7: least reference cost among profiles clearing every floor, then
    performance. Tiers 8-10: strongest measured performance, then cost. Tier 10
    admits only maximum-effort profiles. Missing benchmark results are excluded.
    The PDF permits effort variants in slots 4/5; underlying-model independence
    is enforced separately for reviews and pivots. This is API-evaluation cost,
    never this owner's subscription charge or a promised quota exchange rate.
    """
    tags = validate_task_tags(tags)
    tier = str(_integer(complexity, 1, 10, 'Complexity'))
    models = catalog['models']
    measured = {key: value for key, value in models.items()
                if all(value['scores'][tag] is not None for tag in tags)}
    if len(measured) < 5:
        raise ValueError('Five measured profiles are required for a comparison table')
    ranges = {tag: (min(m['scores'][tag] for m in measured.values()),
                    max(m['scores'][tag] for m in measured.values())) for tag in tags}
    options = []
    for key, model in measured.items():
        failures = [tag for tag in tags if model['scores'][tag] < catalog['task_types'][tag]['tiers'][tier]['floor']]
        maximum = 'high' if model['provider'] == 'gemini' else 'max'
        if complexity == 10 and model['effort'] != maximum:
            continue
        performance = min((model['scores'][tag] - ranges[tag][0]) /
                          max(1e-12, ranges[tag][1] - ranges[tag][0]) for tag in tags)
        cost = model['reference_cost_per_task']
        options.append(dict(model_id=key, model=model['model'], effort=model['effort'],
            scores={tag: model['scores'][tag] for tag in tags}, reference_cost_per_task=cost,
            performance_rank_value=performance, meets_floor=not failures,
            held_task_types=failures, native_acceptance=model['native_acceptance']))
    def order(option):
        cost = option['reference_cost_per_task']
        cost = math.inf if cost is None else cost
        performance = -option['performance_rank_value']
        # Below-floor alternatives are always ordered by performance so the
        # comparison shows the closest alternatives, not cheap weak substitutes.
        rank = (cost, performance) if complexity <= 7 and option['meets_floor'] else (performance, cost)
        return (not option['meets_floor'], *rank, option['model_id'])
    selected = sorted(options, key=order)[:5]
    if len(selected) != 5:
        raise ValueError('Five eligible effort profiles are required for comparison')
    return selected


def with_five_model_rows(catalog):
    result = deepcopy(catalog)
    for tag, spec in result['task_types'].items():
        for tier, row in spec['tiers'].items():
            row['ranked_options'] = five_model_options(result, [tag], int(tier))
            row['choices'] = [x['model_id'] for x in row['ranked_options']]
    result.update(generation='4.2.8-five-options-20261013-v1',
        ranking_policy='tiers_1_7_cost_then_performance__tiers_8_10_performance_then_cost',
        below_floor_policy='visible_comparison_only_never_dispatch', activation_ready=False)
    return result


def select_reviewers(catalog, tags, complexity, producer_id, *, available_ids=None):
    tags = validate_task_tags(tags)
    _integer(complexity, 1, 10, 'Complexity')
    producer = catalog['models'][producer_id]
    tier = min(10, complexity + 1)
    # Prefer the higher-tier order. Remaining qualifying families can close a
    # reviewer gap, but never by substituting an effort of the producing model.
    initial = select_candidates(catalog, tags, tier)
    ordered = list(dict.fromkeys(initial + list(catalog['models'])))
    result, seen = [], {producer['family']}
    for model_id in ordered:
        model = catalog['models'][model_id]
        maximum = 'high' if model['provider'] == 'gemini' else 'max'
        if model['family'] in seen or (complexity == 10 and model['effort'] != maximum):
            continue
        if available_ids is not None and model_id not in available_ids:
            continue
        if all(model['scores'][tag] is not None and
               model['scores'][tag] >= catalog['task_types'][tag]['tiers'][str(tier)]['floor'] for tag in tags):
            seen.add(model['family'])
            result.append(model_id)
    # Different model is mandatory; a different provider is preferred when it
    # can meet the same floor. Provider diversity never overrides capability.
    return sorted(result, key=lambda key: catalog['models'][key]['provider'] == producer['provider'])


def backoff_seconds(round_index, *, random_fraction, base=5, maximum=300):
    _integer(round_index, 0, 10**9, 'Availability round')
    for value in (random_fraction, base, maximum):
        _number(value, 'Backoff input')
    if not 0 <= random_fraction <= 1 or not 0 < base <= maximum <= 86400:
        raise ValueError('Invalid full-jitter backoff bounds')
    return random_fraction * min(maximum, base * 2 ** min(round_index, 30))


def context_fits(srs_tokens, evidence_and_instruction_tokens, output_reserve_tokens, context_limit):
    for value in (srs_tokens, evidence_and_instruction_tokens, output_reserve_tokens):
        _integer(value, 0, 10**9, 'Context token count')
    if context_limit is None:
        return False
    _integer(context_limit, 1, 10**9, 'Verified context limit')
    return srs_tokens + evidence_and_instruction_tokens + output_reserve_tokens <= context_limit


def select_pivot_candidates(catalog, tags, complexity, failed_model_ids, *, available_ids=None):
    """Select higher/different underlying models after a 10-failure quality threshold.

    Changing effort on a failed underlying model family never qualifies as a
    pivot. Candidates must clear the current tier floor (preferring next-tier
    choices first), belong to a distinct family from all failed models, and obey
    tier-10 maximum-effort rules. Quota/availability filtering (`available_ids`)
    remains separate from benchmark capability scores.
    """
    tags = validate_task_tags(tags)
    _integer(complexity, 1, 10, 'Complexity')
    if (not isinstance(failed_model_ids, (list, tuple, set))
            or not failed_model_ids
            or any(not isinstance(mid, str) or mid not in catalog['models'] for mid in failed_model_ids)):
        raise ValueError('Pivot selection requires at least one known failed model ID')
    excluded_families = {catalog['models'][mid]['family'] for mid in failed_model_ids}
    next_tier = min(10, complexity + 1)
    ordered = list(dict.fromkeys(
        select_candidates(catalog, tags, next_tier, exclude_families=excluded_families)
        + select_candidates(catalog, tags, complexity, exclude_families=excluded_families)
        + list(catalog['models'])
    ))
    result, seen_families = [], set(excluded_families)
    for model_id in ordered:
        model = catalog['models'][model_id]
        maximum = 'high' if model['provider'] == 'gemini' else 'max'
        if model['family'] in seen_families or (complexity == 10 and model['effort'] != maximum):
            continue
        if available_ids is not None and model_id not in available_ids:
            continue
        if all(model['scores'][tag] is not None and
               model['scores'][tag] >= catalog['task_types'][tag]['tiers'][str(complexity)]['floor']
               for tag in tags):
            seen_families.add(model['family'])
            result.append(model_id)
    return result


def build_gap_resolution_packet(owner_raw, observations):
    """Compile a reproducible decision packet for all documented 4.2.8 routing gaps."""
    uncalibrated_base = compile_matrix(owner_raw, observations)
    uncalibrated = with_five_model_rows(uncalibrated_base)
    calibrated_base = independent_review_calibration(uncalibrated_base)
    calibrated = with_five_model_rows(calibrated_base)

    missing_profiles = []
    default_fallback_profiles = []
    for model_id, model in sorted(uncalibrated['models'].items()):
        if model['score_evidence'] == 'MISSING_PUBLISHED_EFFORT_RESULT':
            missing_profiles.append(dict(
                model_id=model_id,
                family=model['family'],
                provider=model['provider'],
                effort=model['effort'],
                score_evidence=model['score_evidence'],
                resolution='hold_from_benchmark_floor_routing_until_publisher_capture',
            ))
        else:
            obs_name = model.get('observed_configuration') or ''
            if 'DefaultFallback' in obs_name or 'Fallback' in obs_name:
                default_fallback_profiles.append(dict(
                    model_id=model_id,
                    observed_configuration=obs_name,
                    evidence_url=model.get('evidence_url'),
                    native_pinning_rule='requires_separate_host_cli_acceptance_receipt',
                ))

    execution_gaps = []
    reviewer_gaps = []
    for tag, spec in uncalibrated['task_types'].items():
        for tier_str, row in spec['tiers'].items():
            tier = int(tier_str)
            eligible = select_candidates(uncalibrated, [tag], tier)
            if not eligible:
                execution_gaps.append(dict(
                    task_type=tag,
                    tier=tier,
                    supplied_floor=row['floor'],
                    ranked_comparison=[
                        dict(model_id=opt['model_id'], score=opt['scores'][tag],
                             meets_floor=opt['meets_floor'])
                        for opt in row['ranked_options']
                    ],
                    calibrated_floor=calibrated['task_types'][tag]['tiers'][tier_str]['floor'],
                    calibrated_eligible=select_candidates(calibrated, [tag], tier),
                ))
            for producer in eligible:
                reviewers = select_reviewers(uncalibrated, [tag], tier, producer)
                if not reviewers:
                    review_tier = str(min(10, tier + 1))
                    reviewer_gaps.append(dict(
                        task_type=tag,
                        tier=tier,
                        producer=producer,
                        producer_family=uncalibrated['models'][producer]['family'],
                        review_tier=int(review_tier),
                        supplied_review_floor=spec['tiers'][review_tier]['floor'],
                        calibrated_review_floor=calibrated['task_types'][tag]['tiers'][review_tier]['floor'],
                        calibrated_reviewers=select_reviewers(calibrated, [tag], tier, producer),
                    ))

    for tag, spec in calibrated['task_types'].items():
        for tier_str, row in spec['tiers'].items():
            orig_floor = uncalibrated['task_types'][tag]['tiers'][tier_str]['floor']
            row['uncalibrated_floor'] = orig_floor
            row['floor_changed'] = (row['floor'] != orig_floor)

    return dict(
        schema='cochem-task-routing-decision-packet/1',
        generation='4.2.8-gap-resolution-packet-20261013-v1',
        source_sha256=uncalibrated['source_sha256'],
        observations_sha256=uncalibrated['observations_sha256'],
        uncalibrated_catalog_sha256=digest(uncalibrated),
        calibrated_proposal_sha256=digest(calibrated),
        missing_effort_profiles=missing_profiles,
        default_fallback_profiles=default_fallback_profiles,
        uncalibrated_execution_gaps=execution_gaps,
        uncalibrated_reviewer_gaps=reviewer_gaps,
        calibration_changes=calibrated_base['calibration_changes'],
        calibrated_proposal=calibrated,
        default_runtime_policy='hold_strict_supplied_floors',
        owner_decisions=[
            dict(
                decision_id='routing-floor-policy-428',
                default_choice='hold_strict_supplied_floors',
                options=[
                    dict(
                        option_id='hold_strict_supplied_floors',
                        summary='Keep all 110 owner-supplied floors unchanged; hold SCI-FORMAL tier 10 and the 20 single-family tier 9-10 review combinations when reached.',
                        activates_calibrated_floors=False,
                    ),
                    dict(
                        option_id='adopt_two_family_calibration',
                        summary='Apply the 11 documented floor adjustments capping single-tag floors at the second-highest measured max-effort family so all 110 rows have >=2 independent families.',
                        activates_calibrated_floors=True,
                    ),
                ],
            ),
        ],
    )
