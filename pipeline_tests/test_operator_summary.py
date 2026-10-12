"""Loopback-only operator response contracts; no provider or host execution."""
import asyncio
import json

from pipeline_tests.test_service import endpoint, request


def test_summary_preserves_acceptance_counts_and_full_evidence_access(endpoint):
    full = endpoint.client.call('/operator')
    summary = endpoint.client.call('/operator?view=summary')
    assert summary['acceptance']['counts'] == full['acceptance']['counts']
    assert summary['acceptance']['all_verified'] == full['acceptance']['all_verified']
    assert summary['acceptance']['details_omitted'] is True
    assert 'requirements' not in summary['acceptance']
    assert 'requirements' in full['acceptance']
    assert len(json.dumps(summary['acceptance'])) < len(json.dumps(full['acceptance'])) / 2
    assert request(endpoint, 'GET', '/operator?view=summary')[0] == 401
    for query in ('view=unknown', 'view=summary&view=full', 'after_event_id=0&after_event_id=1'):
        assert request(endpoint, 'GET', '/operator?' + query, authorization='Bearer ' + endpoint.token)[0] == 400


def test_mcp_defaults_to_summary_and_can_request_full_evidence(endpoint):
    from mcp.shared.memory import create_connected_server_and_client_session
    from cochem_pipeline.server import create_server

    async def scenario():
        async with create_connected_server_and_client_session(create_server(endpoint.client)) as client:
            summary = await client.call_tool('pipeline_operator_view', {})
            assert not summary.isError
            assert summary.structuredContent['acceptance']['details_omitted']
            full = await client.call_tool('pipeline_operator_view', {'view': 'full', 'after_event_id': 0})
            assert not full.isError
            assert 'requirements' in full.structuredContent['acceptance']
    asyncio.run(scenario())
