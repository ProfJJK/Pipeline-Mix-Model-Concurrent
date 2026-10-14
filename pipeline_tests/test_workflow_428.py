"""Versioned workflow contracts, with no model launches or protected state."""
from copy import deepcopy
import pytest

from cochem_pipeline.workflow_428 import (
    new_task, accept_srs, approve_srs, accept_research, accept_review,
    accept_wbs, accept_microtasks, validate_research, AttemptLedger,
)
from cochem_pipeline.task_routing import digest


def document(complexity=4, tags=None):
    return dict(plan='Implement and verify the requested behavior', architecture='One bounded component',
        srs=[dict(id='S1', requirement_ids=['R1'], text='Return the exact requested output')],
        requirements=[dict(id='R1', text='Return the exact requested output')],
        assessment=dict(complexity=complexity, task_types=tags or ['COD-TERM'],
                        rationale='Local behavior with explicit acceptance'),
        release_criteria=['Independent test proves R1'], srs_tokens=100,
        evidence_and_instruction_tokens=100, output_reserve_tokens=100)


def research():
    return {kind: dict(query='Approach and failure causes', status='found',
                      receipt_sha256=digest(kind), sources=[dict(id=kind, sha256=digest(kind+'result'))])
            for kind in ('internet', 'wiki_rag', 'papers')}


def planned(level=4, tags=None, context=20000):
    return accept_srs(new_task('t1', 'Deliver R1'), document(level, tags),
                      planner_model='gpt-6.1-sol', flash_context_limit=context)


def test_low_model_estimates_cannot_bypass_context_decomposition():
    output=document(2)
    output.update(srs_tokens=0,evidence_and_instruction_tokens=0,output_reserve_tokens=0)
    state=accept_srs(new_task('t1','Deliver R1'),output,
        planner_model='gpt-6.1-sol',flash_context_limit=1000)
    assert state['fits_flash_context'] is False
    assert state['stage']=='PLAN_REVIEW' and state['needs_wbs']
    assert state['context_budget']['instructions']>=4096
    assert state['context_budget']['output']>=4096


def test_changing_producer_invalidates_previous_independent_review():
    state=planned(4)
    state=accept_research(state,research())
    state=accept_review(state,reviewer_model='claude-opus-5-5',reviewer_tier=5,
        effort='high',accepted=True,review_sha256=digest('review'))
    state['stage']='REVISING_SRS'
    revised=accept_srs(state,state['document'],planner_model='claude-opus-5-5',flash_context_limit=20000)
    assert revised['review'] is None and revised['stage']=='PLAN_REVIEW'


def test_small_single_type_goes_to_board_but_multiple_types_decompose():
    assert planned(3)['stage'] == 'READY'
    state = planned(2, ['COD-TERM','SCI-FORMAL'])
    assert state['stage'] == 'PLAN_REVIEW' and state['needs_wbs']
    assert state['approval_required'] is False


def test_oversized_low_task_gets_review_and_wbs():
    state = planned(2, context=200)
    assert state['stage'] == 'PLAN_REVIEW' and state['needs_wbs']
    assert state['review_tier'] == 3


def test_high_complexity_approval_binds_full_current_revision():
    state = planned(8)
    assert state['stage'] == 'OWNER_APPROVAL'
    with pytest.raises(ValueError):
        approve_srs(state, '0'*64, 'receipt')
    approved = approve_srs(state, state['srs_sha256'], 'owner-receipt-1')
    assert approved['stage'] == 'RESEARCH'
    changed = document(8)
    changed['architecture'] = 'Materially different storage design'
    revised = accept_srs(approved, changed, planner_model='gpt-6.1-sol', flash_context_limit=1000)
    assert revised['stage'] == 'OWNER_APPROVAL'
    assert revised['approval'] is None


def test_three_research_channels_required_and_unavailable_is_a_hold():
    state = planned(4)
    data = research()
    del data['papers']
    with pytest.raises(ValueError):
        accept_research(state, data)
    data = research()
    data['papers'].update(status='unavailable', sources=[])
    assert accept_research(state, data)['stage'] == 'RESEARCH_HOLD'
    data['papers'].update(status='no_results')
    assert accept_research(state, data)['stage'] == 'PLAN_REVIEW'


def test_review_uses_different_actual_model_and_next_tier():
    state = accept_research(planned(4), research())
    with pytest.raises(ValueError):
        accept_review(state, reviewer_model='gpt-6.1-sol', reviewer_tier=5,
                      effort='high', accepted=True, review_sha256=digest('review'))
    with pytest.raises(ValueError):
        accept_review(state, reviewer_model='claude-opus-5-5', reviewer_tier=4,
                      effort='max', accepted=True, review_sha256=digest('review'))
    state = accept_review(state, reviewer_model='claude-opus-5-5', reviewer_tier=5,
                          effort='high', accepted=True, review_sha256=digest('review'))
    assert state['stage'] == 'WBS'


def test_tier_ten_requires_maximum_review_effort():
    state = planned(10)
    state = approve_srs(state, state['srs_sha256'], 'owner-receipt-1')
    state = accept_research(state, research())
    with pytest.raises(ValueError):
        accept_review(state, reviewer_model='claude-opus-5-5', reviewer_tier=10,
                      effort='high', accepted=True, review_sha256=digest('review'))
    assert accept_review(state, reviewer_model='claude-opus-5-5', reviewer_tier=10,
        effort='max', accepted=True, review_sha256=digest('review'))['stage'] == 'WBS'


def ready_for_wbs():
    return accept_review(accept_research(planned(), research()),
        reviewer_model='claude-opus-5-5', reviewer_tier=5, effort='high',
        accepted=True, review_sha256=digest('review'))


def wbs():
    return [dict(id='W1', section_ids=['S1'], requirement_ids=['R1'],
                 deliverables=['source change'], audit_metrics=['unit test passes'],
                 release_criteria=['R1 proven'], depends_on=[])]


def microtasks():
    return [dict(id='M1', wbs_ids=['W1'], role='implementation', complexity=2,
        task_types=['COD-TERM'], deliverables=['source change'], audit_metrics=['unit test'],
        release_criteria=['R1 proven'], depends_on=[], prompt='Implement W1'),
        dict(id='M2', wbs_ids=['W1'], role='assembly', complexity=4,
        task_types=['COD-TERM','AGT-PROJ'], deliverables=['assembled source'], audit_metrics=['integration check'],
        release_criteria=['components agree'], depends_on=['M1'], prompt='Assemble W1'),
        dict(id='M3', wbs_ids=['W1'], role='final_test', complexity=4,
        task_types=['COD-TERM'], deliverables=['test report'], audit_metrics=['all requirements verified'],
        release_criteria=['R1 proven end to end'], depends_on=['M2'], prompt='Verify the assembled W1')]


def test_wbs_traceability_and_microtask_dag_include_assembly_and_tests():
    state = accept_wbs(ready_for_wbs(), wbs())
    result = accept_microtasks(state, microtasks())
    assert result['stage'] == 'MICROTASK_ASSESSMENT'
    assert result['microtasks'][1]['complexity'] == 4
    bad = microtasks()
    bad[0]['depends_on'] = ['M3']
    with pytest.raises(ValueError):
        accept_microtasks(state, bad)
    bad = wbs()
    bad[0]['section_ids'] = ['absent']
    with pytest.raises(ValueError):
        accept_wbs(ready_for_wbs(), bad)


def test_budget_survives_reopen_fracture_and_duplicate_completion(tmp_path):
    path = tmp_path / 'attempts.db'
    ledger = AttemptLedger(path)
    ledger.create('root')
    for number in range(10):
        lease = ledger.start('root', 'root', 'claude-opus-5-5')
        result = ledger.finish(lease, 'quality_failure', digest(str(number)))
        assert ledger.finish(lease, 'quality_failure', digest(str(number))) == result
    assert result['stage'] == 'PIVOT_RESEARCH'
    with pytest.raises(ValueError):
        ledger.start('root', 'child', 'gpt-6-astra')
    ledger = AttemptLedger(path)
    ledger.pivot('root', research(), dict(strategy='fracture', task_types=['COD-TERM'],
        complexity=5, rationale='Separate parser and IO', next_model='gpt-6-astra',
        children=['child-a','child-b']), digest('pivot'))
    assert ledger.status('child-a')['failures'] == 10
    for number in range(20):
        if number == 10:
            ledger.pivot('root', research(), dict(strategy='pivot', task_types=['COD-TERM'],
                complexity=6, rationale='Use a finite-state parser', next_model='claude-fable-5-1',
                children=[]), digest('pivot2'))
        lease = ledger.start('root', 'child-a', 'gpt-6-astra' if number < 10 else 'claude-fable-5-1')
        result = ledger.finish(lease, 'quality_failure', digest('more'+str(number)))
    assert result['stage'] == 'LOCKED' and result['failures'] == 30
    with pytest.raises(ValueError):
        ledger.start('root', 'child-b', 'gpt-6-astra')


def test_availability_never_consumes_quality_budget(tmp_path):
    ledger = AttemptLedger(tmp_path / 'attempts.db')
    ledger.create('root')
    lease = ledger.start('root', 'root', 'gpt-6-astra')
    result = ledger.finish(lease, 'availability', digest('quota'))
    assert result['failures'] == 0 and result['stage'] == 'READY'


def test_lineage_attempts_are_serial_and_stale_or_changed_receipts_rejected(tmp_path):
    ledger = AttemptLedger(tmp_path / 'attempts.db')
    ledger.create('root')
    lease = ledger.start('root', 'root', 'gpt-6-astra')
    with pytest.raises(ValueError):
        ledger.start('root', 'root', 'gpt-6-astra')
    ledger.finish(lease, 'quality_failure', digest('one'))
    with pytest.raises(ValueError):
        ledger.finish(lease, 'success', digest('two'))
