"""Interpret the CLI-wide registry reported by the reviewed Agy 1.3.1 build.

Its printmode.advertisedTools reads the global runner map, not the selected
agent's capability list. Tool exclusion is bound to the protected agent file;
the stream must still identify that agent and contain no tool/agent steps.
This exception is deliberately unavailable to other binaries or agent files.
"""
import re

from .agy_agent_guard import require_agent_contract


BINARY_SHA256 = '38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741'
AGENT_SHA256 = '5c0082d70d073263a56d748a46187008968c070d0efc7d5b7612c2fd61d11810'


def validate_registry(init, spec):
    """Return metadata, never treat advertised tool names as granted powers."""
    contract = require_agent_contract(spec)
    native = spec['inference_only']
    if (native['executable_sha256'] != BINARY_SHA256 or native['version'] != '1.3.1'
            or contract['sha256'] != AGENT_SHA256 or contract['bytes'] != 478):
        raise ValueError('CLI registry interpretation requires the exact reviewed Agy build and agent')
    if init.get('agent') != contract['name']:
        raise ValueError('Agy did not select the protected inference-only agent')
    names = init.get('tools')
    if (not isinstance(names, list) or len(names) > 256
            or any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_./:-]{1,128}', name)
                   for name in names)
            or len(set(names)) != len(names)):
        raise ValueError('Agy CLI registry is malformed or unbounded')
    return dict(schema='cochem-agy-cli-registry/1', scope='cli_builtin_runners',
                advertised_count=len(names), advertised_tools_are_agent_permissions=False,
                agent=contract['name'], agent_sha256=contract['sha256'],
                executable_sha256=BINARY_SHA256)
