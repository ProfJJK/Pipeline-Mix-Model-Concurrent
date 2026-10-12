"""Controller-owned quality pivots, separate from availability routing."""
import pytest
from cochem_pipeline import routing


def pivot(previous=None, *, score=6, model='claude-sonnet-5-5', provider='claude', index=1):
    from cochem_pipeline.quality_routing import next_quality_pivot
    return next_quality_pivot(previous, route={'score': score, 'provider': provider, 'model': model},
                              leaf_index=0, pivot_index=index, producer_job_id='producer',
                              research_job_id='research', research_receipt_sha256='a' * 64)


def test_pivot_increases_tier_and_survives_input_mutation():
    from cochem_pipeline.quality_routing import apply_quality_floor
    first = pivot()
    assert first['floor'] == 7
    low = routing.score_task('CODE_EDIT', {'objective': 'fix'}, scoring_version=2)
    adjusted = apply_quality_floor(low, first)
    assert adjusted['score'] == 7 and adjusted['tier'] == '7'
    assert adjusted['base_score'] == 1
    assert low['score'] == 1
    from cochem_supervisor.quality_capture import apply_captured_floor
    assert apply_captured_floor(low, first, kind='CODE_EDIT', leaf_index=0) == adjusted
    with pytest.raises(ValueError):
        apply_captured_floor(low, first, kind='CODE_EDIT', leaf_index=1)
    second = pivot(first, score=7, model='gpt-6.1-sol', provider='codex', index=2)
    assert second['floor'] == 8
    assert first['floor'] == 7


def test_tier10_uses_bounded_distinct_models_and_never_invents_tier11():
    first = pivot(score=9, model='claude-opus-5-5')
    second = pivot(first, score=10, model='claude-fable-5-1', index=2)
    third = pivot(second, score=10, model='gpt-6-astra', provider='codex', index=3)
    assert first['floor'] == second['floor'] == third['floor'] == 10
    assert len(third['excluded_models']) == 3
    with pytest.raises(ValueError):
        pivot(third, score=10, index=4)


def test_pivot_cannot_reduce_floor_or_cross_leaf():
    first = pivot(score=8)
    with pytest.raises(ValueError):
        pivot(first, score=3, index=2)
    from cochem_pipeline.quality_routing import next_quality_pivot
    with pytest.raises(ValueError):
        next_quality_pivot(first, route={'score': 9, 'provider': 'claude', 'model': 'claude-opus-5-5'},
                           leaf_index=1, pivot_index=2, producer_job_id='p', research_job_id='r',
                           research_receipt_sha256='a' * 64)


def test_storage_floor_survives_restart_and_review_exclusion_is_separate(tmp_path):
    from cochem_pipeline.store import JobStore
    from cochem_pipeline import routing_store as routes
    from cochem_pipeline.quality_routing import next_quality_pivot
    policy = routing.load_routing_policy({'policy_version': 3})
    store = JobStore(tmp_path / 'quality.db', routing_policy=policy)
    quality = pivot(score=6, model='claude-opus-5-5')
    # Explicit storage fixture: no native completion or physical Git claim.
    with store._write() as conn:
        store._insert(conn, 'root', 'root', None, 'CODE_REQUEST', 'IN_PROGRESS', {})
        routes.capture_workflow(conn, 'root', policy)
        for kind in ('CODE_EDIT', 'CODE_REVIEW'):
            store._insert(conn, kind, 'root', 'root', kind, 'PENDING',
                          {'objective': 'format', 'leaf_index': 0,
                           'producer': {'provider': 'codex', 'model': 'gpt-6.1-sol'}}, quality_routing=quality)
        edit = store._get(conn, 'CODE_EDIT')
        state = routes.get_state(conn, 'CODE_EDIT')
        assert state['score_details']['score'] == 7
        assert routes._candidate_unavailability(conn, edit, state, state['candidates'][0], None, 0) == 'quality_pivot_previous_model'
        review = store._get(conn, 'CODE_REVIEW')
        review_state = routes.get_state(conn, 'CODE_REVIEW')
        assert routes._candidate_unavailability(conn, review, review_state, review_state['candidates'][0], None, 0) is None
        assert routes._candidate_unavailability(conn, review, review_state, review_state['candidates'][1], None, 0) == 'asymmetric_review'
    restored = JobStore(store.path, routing_policy=policy).get('CODE_EDIT')
    assert restored['routing']['score_details']['quality_routing'] == quality
    assert restored['routing']['dispatches'] == 0


def test_model_payload_cannot_assign_itself_a_quality_floor(tmp_path):
    from cochem_pipeline.store import JobStore
    from cochem_pipeline import routing_store as routes
    policy = routing.load_routing_policy({'policy_version': 3})
    store = JobStore(tmp_path / 'untrusted.db', routing_policy=policy)
    with store._write() as conn:
        store._insert(conn, 'root', 'root', None, 'CODE_REQUEST', 'IN_PROGRESS', {})
        routes.capture_workflow(conn, 'root', policy)
        store._insert(conn, 'edit', 'root', 'root', 'CODE_EDIT', 'PENDING',
                      {'objective': 'format', 'leaf_index': 0, 'quality_routing': pivot(score=9)})
        assert routes.get_state(conn, 'edit')['score_details']['score'] == 1
