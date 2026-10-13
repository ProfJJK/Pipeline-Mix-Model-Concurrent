"""Codex RAM cwd regression with in-process launch doubles only."""
import ast
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cochem_pipeline import agy_protocol, worker
from scripts import r6_custody_amendment as amendment
from pipeline_tests.test_r6_registry_amendment import frozen
from pipeline_tests.test_worker_gemini_dispatch import FakeProcess, fake_prompt_input


def test_amendment_workspace_function_is_identical_to_canonical_source():
    def tree(function):
        return ast.dump(ast.parse(inspect.getsource(function)), include_attributes=False)
    assert tree(worker.codex_inherited_workspace_command) == tree(amendment.codex_inherited_workspace_command)


@pytest.mark.parametrize('fault', ['', 'missing_descriptor', 'identity', 'outside', 'relative',
                                  'parent', 'missing_cd', 'duplicate_cd', 'different_cd', 'alias', 'inline'])
def test_only_exact_assigned_cwd_option_is_removed(tmp_path, fault):
    directory = tmp_path / 'slot3' / 'job'
    descriptor = SimpleNamespace(root=tmp_path / 'slot3', identity='worker3')
    argv = worker.provider_command('codex', ['codex.exe'], 'gpt-6-luna', str(directory), {},
                                   'medium', inference_only=True, mcp_names=['example'])
    original = list(argv)
    if fault == 'missing_descriptor': descriptor = None
    elif fault == 'identity': descriptor.identity = 'worker4'
    elif fault == 'outside': descriptor.root = tmp_path / 'slot4'
    elif fault == 'relative': directory = Path('slot3/job')
    elif fault == 'parent': directory = directory / '..' / 'sibling'
    elif fault == 'missing_cd': argv.remove('--cd')
    elif fault == 'duplicate_cd': argv += ['--cd', str(directory)]
    elif fault == 'different_cd': argv[argv.index('--cd') + 1] = 'other'
    elif fault == 'alias': argv += ['-C', 'other']
    elif fault == 'inline': argv += ['--cd=other']
    if fault:
        with pytest.raises(ValueError):
            worker.codex_inherited_workspace_command(argv, directory, descriptor, 'worker3')
    else:
        result = worker.codex_inherited_workspace_command(argv, directory, descriptor, 'worker3')
        index = original.index('--cd')
        assert result == original[:index] + original[index + 2:]
        assert argv == original  # keep the general command builder's contract
        assert not directory.exists()  # no path creation or canonicalization


@pytest.mark.parametrize('installed', [False, True])
def test_complete_codex_dispatch_inherits_exact_cwd_and_preserves_policy(tmp_path, monkeypatch, installed):
    directory = tmp_path / 'slot3'
    directory.mkdir()
    descriptor = SimpleNamespace(root=directory, identity='worker3')
    config = SimpleNamespace(providers={'codex': {'executable': 'fixture-codex.exe'}},
        workers={'slot3': {'name': 'worker3', 'credential_target': 'fixture'}},
        private_root=tmp_path / 'private', timeout_seconds=60, lease_seconds=30)
    route = dict(provider='codex', model='gpt-6-luna', reasoning_effort='medium', reservation_id='reservation')
    node = dict(kind='PREFLIGHT_REQUEST', payload={}, job_id='job', workflow_id='workflow',
                attempt_id='a'*32, fencing_token=1, worker_slot='slot3')
    runner = worker.NativeRunner(config)
    monkeypatch.setattr(runner, 'route', lambda node: route)
    monkeypatch.setattr(runner, '_inference_preflight', lambda *args: (('fixture-server',), {'mode': 'inference-only'}))
    monkeypatch.setattr(worker, 'executable_prefix', lambda *args: ['fixture-codex.exe'])
    monkeypatch.setattr(worker, 'native_prompt_input', fake_prompt_input)
    if installed:
        _, _, run = amendment.registry_modules(*frozen(), {}, agy_protocol, worker)
        monkeypatch.setattr(worker.NativeRunner, 'run', run)
    calls = []
    def launch(identity, argv, cwd, source, out, err, **options):
        assert cwd == directory and identity.name == descriptor.identity
        assert options['ramdisk_workspace'] is descriptor and options['worker_slot'] == 'slot3'
        calls.append(list(argv))
        if 'exec' not in argv:
            assert argv[-2:] == ['login', 'status']
            out.write(b'Logged in using ChatGPT\n')
        else:
            expected = worker.provider_command('codex', ['fixture-codex.exe'], 'gpt-6-luna', str(directory), {},
                'medium', inference_only=True, mcp_names=('fixture-server',))
            at = expected.index('--cd')
            assert argv == expected[:at] + expected[at + 2:]
            for row in [dict(type='thread.started', thread_id='fixture-session'),
                        dict(type='item.completed', item=dict(type='agent_message', text='{"ready":true}')),
                        dict(type='turn.completed', usage=dict(input_tokens=1, output_tokens=1))]:
                out.write((json.dumps(row) + '\n').encode())
        out.flush()
        return FakeProcess(4100 + len(calls), 0)
    monkeypatch.setattr(runner, '_launch_worker', launch)
    output, receipt = runner.run(node, 'slot3', '', lambda: True, workspace=directory, ramdisk_workspace=descriptor)
    assert output == {'ready': True}
    assert len(calls) == 2
    assert receipt['inference_policy']['workspace_selection'] == 'validated_process_cwd'
    assert receipt['requested_model'] == 'gpt-6-luna' and receipt['requested_effort'] == 'medium'


def test_report_error_fingerprint_matches_public_windows_error_exactly():
    diagnostic = json.loads((Path(__file__).parents[1] /
        'docs/evidence/r6-native-hold-v2-diagnostic-20261013.json').read_text(encoding='utf-8-sig'))
    error = b'Error: Incorrect function. (os error 1)\n'
    failure = diagnostic['native_failure']['projection']
    assert len(error) == failure['stderr_bytes'] == 40
    assert hashlib.sha256(error).hexdigest() == failure['stderr_sha256']
    assert diagnostic['stream_hashes_match_failure'] is True
