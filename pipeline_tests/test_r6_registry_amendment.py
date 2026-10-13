"""Frozen installed-source execution with inert inputs, never a provider launch."""
import ast
import copy
import inspect
from pathlib import Path

import pytest

from cochem_pipeline import agy_protocol, agy_tool_registry, worker
from scripts import r6_custody_amendment as amendment
from pipeline_tests.test_agy_tool_registry import spec, observation, raw
from pipeline_tests.test_worker_gemini_dispatch import harness, DIGEST, agy_stream, HIGH


def frozen():
    root = Path(__file__).parent / 'fixtures'
    return tuple((root / name).read_bytes() for name in ('r6_agy_protocol_359ca92.txt', 'r6_worker_359ca92.txt'))


def test_validator_matches_source_exactly():
    def tree(func):
        return ast.dump(ast.parse(inspect.getsource(func)), include_attributes=False)
    assert tree(amendment.validate_registry) == tree(agy_tool_registry.validate_registry)


@pytest.mark.parametrize('fault', ['', 'binary', 'agent', 'tool', 'model'])
def test_exact_installed_parser_repair_preserves_exception_identity(spec, monkeypatch, fault):
    original = agy_protocol.parse_stream
    rows = observation()
    if fault == 'binary': spec['inference_only']['executable_sha256'] = '0' * 64
    if fault == 'agent': rows[0]['init']['agent'] = 'other'
    if fault == 'tool': rows[1]['step_update']['tool_name'] = 'fixture'
    if fault == 'model': rows[0]['init']['model'] = 'other'
    parse_stream, parse_gemini, run = amendment.registry_modules(*frozen(), spec, agy_protocol, worker)
    assert agy_protocol.parse_stream is original  # compilation has no side effects
    monkeypatch.setattr(agy_protocol, 'parse_stream', parse_stream)
    kwargs = dict(native={'argv': 'gemini-3.8-flash-low', 'reports': 'gemini-3.8-flash-low'},
                  identity_policy=agy_protocol.IDENTITY_POLICY)
    if fault:
        with pytest.raises(agy_protocol.AgyIdentityError):
            parse_gemini(raw(rows), 'agy-stream-json', 'gemini-3.8-flash', **kwargs)
    else:
        result = parse_gemini(raw(rows), 'agy-stream-json', 'gemini-3.8-flash', **kwargs)
        assert result['tool_registry']['advertised_count'] == 60
        assert run.__globals__['parse_gemini'] is parse_gemini


@pytest.mark.parametrize('index', [0, 1])
def test_any_installed_source_change_holds(spec, index):
    inputs = list(frozen())
    inputs[index] += b'\n'
    with pytest.raises(ValueError, match='source binding'):
        amendment.registry_modules(*inputs, spec, agy_protocol, worker)


@pytest.mark.parametrize('fault', ['', 'path', 'protocol', 'worker', 'candidate', 'already_installed'])
def test_installation_publishes_callbacks_only_after_exact_binding(spec, monkeypatch, fault):
    import json
    from cochem_pipeline import windows
    base = amendment.ROOT / '.venv/Lib/site-packages/cochem_pipeline'
    monkeypatch.setattr(agy_protocol, '__file__', str(base / ('other.py' if fault == 'path' else 'agy_protocol.py')))
    monkeypatch.setattr(worker, '__file__', str(base / 'worker.py'))
    originals = (agy_protocol.parse_stream, worker.parse_gemini, worker.NativeRunner.run)
    monkeypatch.setattr(agy_protocol, 'parse_stream', originals[0])
    monkeypatch.setattr(worker, 'parse_gemini', originals[1])
    monkeypatch.setattr(worker.NativeRunner, 'run', originals[2])
    if fault == 'already_installed':
        monkeypatch.setattr(agy_protocol, '_r6_registry_amendment', 'fixture', raising=False)
    elif fault == 'candidate':
        spec['agent_definition']['bytes'] = 999
    protocol_raw, worker_raw = frozen()
    reads = []
    def read(win, path, expected, maximum):
        assert win is windows
        reads.append(path.name)
        if path.name == 'pipeline.json':
            assert path == amendment.ROOT / 'pipeline.json' and expected == amendment.CANDIDATE
            return json.dumps({'providers': {'gemini': spec}}).encode()
        if path.name == 'agy_protocol.py':
            assert expected == amendment.REGISTRY_PROTOCOL
            return protocol_raw + (b'\n' if fault == 'protocol' else b'')
        assert path.name == 'worker.py' and expected == amendment.REGISTRY_WORKER
        return worker_raw + (b'\n' if fault == 'worker' else b'')
    try:
        if fault:
            with pytest.raises(ValueError): amendment.install_registry(windows, read)
            assert (agy_protocol.parse_stream, worker.parse_gemini, worker.NativeRunner.run) == originals
        else:
            result = amendment.install_registry(windows, read)
            assert all(new is not old for new, old in zip(
                (agy_protocol.parse_stream, worker.parse_gemini, worker.NativeRunner.run), originals))
            assert result['agent_identity_required'] and result['actual_tool_steps_rejected']
            assert result['installed_files_modified'] is False
            assert reads == ['pipeline.json', 'agy_protocol.py', 'worker.py']
    finally:
        if not fault and hasattr(agy_protocol, '_r6_registry_amendment'):
            del agy_protocol._r6_registry_amendment


@pytest.mark.parametrize('installed', [False, True])
def test_complete_fake_dispatch_records_registry_without_executing_tools(tmp_path, monkeypatch, installed):
    import json
    rows = [json.loads(line) for line in agy_stream(HIGH).splitlines()]
    rows[0]['init'].update(agent='cochem-inference-only', tools=[f'tool_{i}' for i in range(60)])
    fake = harness(tmp_path, monkeypatch, inference=(raw(rows).encode(), b'', 0))
    fake.spec['agent_definition'].update(sha256=amendment.AGENT_SHA256, bytes=478)
    # Only fake executable identity is adapted; all guard/parser/receipt logic runs.
    monkeypatch.setattr(agy_tool_registry, 'BINARY_SHA256', DIGEST)
    monkeypatch.setattr(amendment, 'BINARY_SHA256', DIGEST)
    if installed:
        parse_stream, parse_gemini, run = amendment.registry_modules(*frozen(), fake.spec, agy_protocol, worker)
        monkeypatch.setattr(agy_protocol, 'parse_stream', parse_stream)
        monkeypatch.setattr(worker, 'parse_gemini', parse_gemini)
        monkeypatch.setattr(worker.NativeRunner, 'run', run)
    _, result = fake.run()
    assert result['inference_policy']['tool_registry']['advertised_count'] == 60
    assert result['inference_policy']['tool_registry']['agent_sha256'] == amendment.AGENT_SHA256
    assert len(fake.fake.launches) == 3
