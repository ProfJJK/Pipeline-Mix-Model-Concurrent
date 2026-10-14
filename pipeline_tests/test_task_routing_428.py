"""Controller policy tests; no native programs or host changes."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from cochem_pipeline.task_routing import (
    audit_owner_matrix, build_gap_resolution_packet, compile_matrix,
    select_candidates, select_pivot_candidates, select_reviewers,
    backoff_seconds, context_fits, validate_task_tags,
    independent_review_calibration,
    with_five_model_rows, five_model_options,
)

SOURCE = Path(__file__).parents[1] / 'docs/4.2.8/references/owner-model-matrix.json'


@pytest.fixture
def owner():
    return json.loads(SOURCE.read_text(encoding='utf-8-sig'))


def test_audit_reports_unmarked_floor_failures_and_self_review(owner):
    report = audit_owner_matrix(owner)
    assert any(x['task_type'] == 'AGT-PROJ' and x['tier'] == 9 and
               x['model_id'] == 'fable-max' and x['code'] == 'BELOW_FLOOR_UNMARKED'
               for x in report['findings'])
    assert any(x['code'] == 'REVIEWER_CAN_BE_PRODUCER' for x in report['findings'])
    assert report['activation_ready'] is False


def test_compiler_preserves_floor_without_degraded_escape(owner):
    catalog = compile_matrix(owner)
    ids = select_candidates(catalog, ['AGT-PROJ'], 9)
    assert ids
    assert 'argon-high' not in ids and 'astra-max' not in ids and 'fable-max' not in ids
    assert len({catalog['models'][x]['family'] for x in ids}) == len(ids)
    assert select_candidates(catalog, ['AGT-PROJ'], 9, available_ids={'argon-high'}) == []


def test_unverified_source_is_never_native_acceptance(owner):
    catalog = compile_matrix(owner)
    assert catalog['host_accepted'] is False
    assert catalog['scores_verified'] is False
    assert select_candidates(catalog, ['GEN-DEFAULT'], 1, available_ids=set()) == []


def test_multi_tag_floor_is_intersection_not_weighted_average(owner):
    catalog = compile_matrix(owner)
    for model_id in select_candidates(catalog, ['COD-TERM', 'SCI-FORMAL'], 6):
        for tag in ('COD-TERM', 'SCI-FORMAL'):
            assert catalog['models'][model_id]['scores'][tag] >= catalog['task_types'][tag]['tiers']['6']['floor']


def test_reviewer_differs_from_actual_fallback_family_and_steps_up(owner):
    catalog = compile_matrix(owner)
    for producer in select_candidates(catalog, ['GEN-DEFAULT'], 4):
        for reviewer in select_reviewers(catalog, ['GEN-DEFAULT'], 4, producer):
            assert catalog['models'][producer]['family'] != catalog['models'][reviewer]['family']
            assert catalog['models'][reviewer]['scores']['GEN-DEFAULT'] >= catalog['task_types']['GEN-DEFAULT']['tiers']['5']['floor']


def test_tier_ten_review_maximum_effort_or_explicit_gap(owner):
    catalog = compile_matrix(owner)
    for model_id in select_reviewers(catalog, ['GEN-DEFAULT'], 10, 'opus-max'):
        assert catalog['models'][model_id]['effort'] in ('max', 'high')
        assert catalog['models'][model_id]['family'] != 'claude-opus-5-5'
    # Supplied AGT-PROJ floor has only one qualifying family. Never invent a reviewer.
    assert select_reviewers(catalog, ['AGT-PROJ'], 10, 'opus-max') == []


@pytest.mark.parametrize('tags', [[], ['FAKE'], ['GEN-DEFAULT','COD-TERM'], ['COD-TERM','COD-TERM'], 'COD-TERM'])
def test_invalid_tags_are_rejected(tags):
    with pytest.raises(ValueError):
        validate_task_tags(tags)


def test_full_jitter_is_bounded_and_not_a_quality_escalation():
    assert backoff_seconds(0, random_fraction=0.5) == 2.5
    assert backoff_seconds(3, random_fraction=1) == 40
    assert backoff_seconds(10**8, random_fraction=1) == 300
    assert backoff_seconds(3, random_fraction=0) == 0
    with pytest.raises(ValueError):
        backoff_seconds(True, random_fraction=0.5)


def test_context_budget_counts_research_instructions_and_output():
    assert context_fits(100, 200, 50, 400)
    assert not context_fits(100, 200, 101, 400)
    assert not context_fits(100, 0, 0, None)


def test_invalid_numbers_and_unknown_model_references_are_not_coerced(owner):
    bad = deepcopy(owner)
    bad['models']['luna-low']['scores']['GEN-DEFAULT'] = float('nan')
    with pytest.raises(ValueError):
        compile_matrix(bad)


def observed():
    return json.loads((SOURCE.parents[1] / 'benchmark-observations.json').read_text(encoding='utf-8'))


def test_observed_profiles_replace_claims_without_interpolation(owner):
    catalog = compile_matrix(owner, observed())
    assert catalog['scores_verified'] and not catalog['host_accepted']
    assert catalog['models']['argon-low']['scores']['GEN-DEFAULT'] is None
    assert catalog['models']['argon-med']['scores']['GEN-DEFAULT'] is None
    assert catalog['models']['opus-max']['scores'] != owner['models']['opus-max']['scores']


@pytest.mark.parametrize('field,value', [('page_sha256','bad'), ('context_limit',True),
                                      ('cost_per_task',-1), ('estimated',True)])
def test_observation_provenance_and_numeric_bounds(owner, field, value):
    evidence = observed()
    evidence['models']['opus-max'][field] = value
    with pytest.raises(ValueError):
        compile_matrix(owner, evidence)


def test_calibration_is_explicit_separate_and_all_single_tags_can_be_reviewed(owner):
    original = compile_matrix(owner, observed())
    before = deepcopy(original)
    revised = independent_review_calibration(original)
    assert original == before
    assert revised['calibration_changes'] and revised['activation_ready'] is False
    for tag, spec in revised['task_types'].items():
        assert sorted(x['floor'] for x in spec['tiers'].values()) == [x['floor'] for x in spec['tiers'].values()]
        for tier in range(1, 11):
            choices = select_candidates(revised, [tag], tier)
            assert choices
            for choice in choices:
                assert select_reviewers(revised, [tag], tier, choice), (tag, tier, choice)
    bad = deepcopy(owner)
    bad['taskRoutingMatrix']['GEN-DEFAULT']['tiers']['1']['choices'][0] = 'invented'
    with pytest.raises(ValueError):
        compile_matrix(bad)


def test_all_110_rows_have_five_ranked_slots_with_visible_scores_and_cost(owner):
    result = with_five_model_rows(compile_matrix(owner, observed()))
    count = 0
    for tag, spec in result['task_types'].items():
        for tier, row in spec['tiers'].items():
            assert len(row['choices']) == len(row['ranked_options']) == 5
            assert len(set(row['choices'])) == 5
            assert row['floor'] == owner['taskRoutingMatrix'][tag]['tiers'][tier]['floor']
            for option in row['ranked_options']:
                assert tag in option['scores'] and 'reference_cost_per_task' in option
                assert option['meets_floor'] == (option['scores'][tag] >= row['floor'])
            eligible = select_candidates(result, [tag], int(tier))
            assert eligible == [x['model_id'] for x in row['ranked_options'] if x['meets_floor']]
            count += 1
    assert count == 110


def test_highest_tier_comparison_uses_max_effort_and_performance_order(owner):
    catalog = compile_matrix(owner, observed())
    for tag in catalog['task_types']:
        options = five_model_options(catalog, [tag], 10)
        for option in options:
            assert option['effort'] in ('max', 'high')
        assert [x['scores'][tag] for x in options] == sorted(
            [x['scores'][tag] for x in options], reverse=True)


def test_pivot_selection_excludes_same_family_effort_variants_and_respects_quota(owner):
    catalog = with_five_model_rows(compile_matrix(owner, observed()))
    pivots = select_pivot_candidates(catalog, ['COD-TERM'], 8, ['opus-xhigh'])
    assert pivots
    for model_id in pivots:
        assert catalog['models'][model_id]['family'] != 'claude-opus-5-5'
        assert catalog['models'][model_id]['scores']['COD-TERM'] >= catalog['task_types']['COD-TERM']['tiers']['8']['floor']
    assert select_pivot_candidates(catalog, ['COD-TERM'], 8, ['opus-xhigh'], available_ids={'opus-max'}) == []
    assert select_pivot_candidates(catalog, ['COD-TERM'], 8, ['opus-xhigh'], available_ids={'sonnet-max'}) == ['sonnet-max']
    with pytest.raises(ValueError):
        select_pivot_candidates(catalog, ['COD-TERM'], 8, [])
    with pytest.raises(ValueError):
        select_pivot_candidates(catalog, ['COD-TERM'], 8, ['unknown-model'])


def test_gap_resolution_packet_matches_preserved_artifact_and_exposes_floor_deltas(owner):
    packet = build_gap_resolution_packet(owner, observed())
    saved = json.loads((SOURCE.parents[1] / 'routing-decision-packet.json').read_text(encoding='utf-8'))
    assert packet == saved
    assert [m['model_id'] for m in packet['missing_effort_profiles']] == ['argon-low', 'argon-med', 'flash38-low']
    assert len(packet['uncalibrated_execution_gaps']) == 1
    assert packet['uncalibrated_execution_gaps'][0]['task_type'] == 'SCI-FORMAL'
    assert packet['uncalibrated_execution_gaps'][0]['tier'] == 10
    assert packet['uncalibrated_execution_gaps'][0]['calibrated_eligible']
    assert len(packet['uncalibrated_reviewer_gaps']) == 20
    for gap in packet['uncalibrated_reviewer_gaps']:
        assert gap['calibrated_reviewers']
    changed_rows = [
        (tag, int(tier), row['uncalibrated_floor'], row['floor'])
        for tag, spec in packet['calibrated_proposal']['task_types'].items()
        for tier, row in spec['tiers'].items()
        if row['floor_changed']
    ]
    assert len(changed_rows) == len(packet['calibration_changes']) == 7
    assert packet['default_runtime_policy'] == 'hold_strict_supplied_floors'

