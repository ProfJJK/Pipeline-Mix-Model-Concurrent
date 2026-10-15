"""In-memory MCP preparation transport, not Git or native execution."""
import asyncio

from mcp.shared.memory import create_connected_server_and_client_session
from cochem_pipeline.server import create_server


def test_project_preparation_uses_explicit_scoped_endpoint_without_submitting_jobs():
    class Client:
        def __init__(self):
            self.calls = []
        def call(self, path, payload=None):
            self.calls.append((path, payload))
            return {'project_id': payload['project_id'], 'original_checkout_modified': False}
        def close(self):
            pass
    transport = Client()
    async def scenario():
        async with create_connected_server_and_client_session(create_server(transport)) as client:
            result = await client.call_tool('pipeline_project_prepare', dict(project_id='report-tool-snapshot-1',
                repository=r'C:\Users\owner\source\repos\report-tool', branch='main',
                allowed_paths=['src'], test_paths=['tests'], context_paths=['README.md']))
            assert not result.isError
            assert result.structuredContent['original_checkout_modified'] is False
    asyncio.run(scenario())
    assert transport.calls == [('/coding/prepare', {'project_id': 'report-tool-snapshot-1', 'registration': {
        'repository': r'C:\Users\owner\source\repos\report-tool', 'branch': 'main',
        'allowed_paths': ['src'], 'test_paths': ['tests'], 'context_paths': ['README.md']}})]
