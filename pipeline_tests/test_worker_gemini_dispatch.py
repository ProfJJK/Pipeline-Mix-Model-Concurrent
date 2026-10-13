"""NativeRunner.run with an in-process fake launcher; no native CLI, login or isolation.

The fake launcher writes scripted bytes into the controller-owned output files
and returns an already-exited process object. Every stream here is a protocol
fixture, not evidence that Agy, Claude or Codex behave this way on the host.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from types import SimpleNamespace

import pytest

from cochem_pipeline import agy_protocol, worker
from cochem_pipeline.agy_agent_guard import RELATIVES
from cochem_pipeline.agy_protocol import IDENTITY_POLICY, AgyIdentityError, require_serving_model_contract
from cochem_pipeline.failures import ProviderFailure
from cochem_pipeline.routing import load_routing_policy, tier_for_score
from cochem_pipeline.store import JobStore, output_digest
from cochem_pipeline.worker import (NATIVE_FAILURE_KEYS, NATIVE_FAILURE_SCHEMA, NATIVE_OUTPUT_LIMIT_BYTES,
    NativeRunner, check_native_integration, gemini_binary_digest, native_failure_metadata, provider_command,
    validate_gemini_version, write_native_failure_metadata)


ROUTED = 'gemini-3.8-flash'
HIGH = 'gemini-3.8-flash-high'
PRO = 'gemini-3.1-pro-preview'
VERSION = '1.3.1'
BINARY = b'agy dispatch fixture binary, never executed'
DIGEST = hashlib.sha256(BINARY).hexdigest()
AGY_ARGV = ['--agent', 'cochem-inference-only', '--input-format', 'stream-json',
            '--output-format', 'stream-json', '--model', '{model}', '--disable-slash-commands']
AUTH_ARGV = ['--output-format', 'json', 'models']
AUTH_OK = json.dumps({'status': 'SUCCESS', 'command': {'name': 'models'}}).encode()
ATTEMPT = '0123456789abcdef0123456789abcdef'
# Distinctive diagnostic text: no six-character run of it may reach failure.json.
STDERR = b'FATAL zq9 SECRET-TOKEN-91c4 C:\\Users\\worker7\\AppData leaked-path-segment\n'


def agy_stream(reported, response='{"ready":true}', status='SUCCESS'):
    events = [{'event': 'init', 'conversation_id': 'native-agy-session', 'init': {'model': reported, 'tools': []}},
              {'event': 'step_update', 'step_update': {'conversation_id': 'native-agy-session', 'step_index': 0,
                                                       'state': 'DONE', 'step_type': 'user_input'}},
              {'event': 'result', 'result': {'conversation_id': 'native-agy-session', 'status': status,
                                             'response': response, 'num_turns': 1,
                                             'usage': {'input_tokens': 5, 'output_tokens': 3}}}]
    return ('\n'.join(json.dumps(event) for event in events) + '\n').encode()


def extended_contract():
    return {'arguments': ['--effort', 'high'], 'version_arguments': ['--version'], 'executable_sha256': DIGEST,
            'version': VERSION, 'capability_reference': 'fixture-isolation-receipt.json#' + '0' * 64,
            'native_metadata': None, 'thinking_enabled': None}


def gemini_spec(binary, bindings, contracts=None):
    spec = {'provider': 'gemini', 'model': PRO, 'executable': str(binary),
            'protocol': 'agy-stream-json', 'identity_policy': IDENTITY_POLICY, 'model_bindings': bindings,
            'arguments': list(AGY_ARGV),
            'agent_definition': {'name': 'cochem-inference-only', 'sha256': '0' * 64,
                                 'bytes': 1, 'relative_paths': list(RELATIVES)},
            'subscription_probe': {'arguments': list(AUTH_ARGV), 'protocol': 'json-fields',
                                   'expected': {'status': 'SUCCESS', 'command.name': 'models'}},
            'inference_only': {'arguments': list(AGY_ARGV), 'version_arguments': ['--version'],
                               'executable_sha256': DIGEST, 'version': VERSION,
                               'capability_reference': 'fixture-isolation-receipt.json#' + '0' * 64,
                               'disables_tools': True, 'disables_mcp': True, 'disables_hooks': True,
                               'disables_subagents': True, 'disables_model_fallback': True}}
    if contracts is not None:
        spec['effort_contracts'] = contracts
    return spec


class FakeProcess:
    """An already-exited child; production uses WindowsProcess Job Objects."""
    def __init__(self, pid, code):
        self.pid, self.code, self.closed = pid, code, False
        self.docker_denial_evidence = {'fixture': 'docker denial not verified by this test'}
        self.creation_time, self.creation_time_filetime = 1.5, 15000000

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        return self.code

    def close(self):
        self.closed = True


class FakeLauncher:
    """Answer the version and status probes; script the single inference."""
    def __init__(self, inference=(b'', b'', 0), *, version=VERSION, auth=AUTH_OK, on_inference=None):
        self.inference, self.version, self.auth, self.on_inference = inference, version, auth, on_inference
        self.launches, self.processes = [], []

    def __call__(self, identity, argv, workspace, stdin, out, err, **options):
        assert options['worker_slot'] == 'slot1' and 'ramdisk_workspace' in options
        self.launches.append(list(argv))
        if argv[1:] == ['--version']:
            stdout, stderr, code = (self.version + '\n').encode(), b'', 0
        elif argv[1:] == AUTH_ARGV:
            stdout, stderr, code = self.auth, b'', 0
        else:
            if self.on_inference is not None:
                self.on_inference(argv)
            stdout, stderr, code = self.inference
        out.write(stdout)
        err.write(stderr)
        out.flush()
        err.flush()
        self.processes.append(FakeProcess(4100 + len(self.launches), code))
        return self.processes[-1]


@contextmanager
def fake_prompt_input(prompt):
    # The named-pipe transport has its own tests; nothing is delivered here.
    yield SimpleNamespace(reader=None, start=lambda: None, verify_delivered=lambda: None)


def harness(tmp_path, monkeypatch, *, kind='PREFLIGHT_REQUEST', score=1, payload=None,
            bindings=None, contracts=None, **launcher):
    binary = tmp_path / 'agy.exe'
    binary.write_bytes(BINARY)
    spec = gemini_spec(binary, {ROUTED: HIGH} if bindings is None else bindings, contracts)
    policy = load_routing_policy()
    candidates = policy.candidates(score, kind)
    index = next(position for position, target in enumerate(candidates) if target.provider == 'gemini')
    route = {**candidates[index].as_dict(), 'score': score, 'tier': tier_for_score(score),
             'policy_digest': policy.digest, 'candidate_index': index, 'cycle': 1,
             'reservation_id': 'fixture-reservation', 'attempt_id': ATTEMPT, 'fencing_token': 1,
             'worker_slot': 'slot1'}
    node = {'job_id': 'fixture-job', 'workflow_id': 'fixture-workflow', 'kind': kind,
            'payload': {} if payload is None else payload, 'attempt_id': ATTEMPT, 'fencing_token': 1,
            'worker_slot': 'slot1', 'routing_policy': policy.as_dict(), 'route': route}
    scratch, workspace = tmp_path / 'scratch', tmp_path / 'workspace'
    scratch.mkdir()
    workspace.mkdir()
    config = SimpleNamespace(routing=policy, providers={'gemini': spec}, private_root=tmp_path / 'private',
                             workers={'slot1': {'name': 'cochemworker1', 'credential_target': 'fixture-target'}},
                             slot_roots={}, timeout_seconds=60, lease_seconds=30)
    runner = NativeRunner(config)
    fake = FakeLauncher(**launcher)
    monkeypatch.setattr(runner, '_launch_worker', fake)
    monkeypatch.setattr(worker, 'native_prompt_input', fake_prompt_input)
    ramdisk = SimpleNamespace(environment=lambda: {}, scratch=str(scratch))

    def run():
        return runner.run(node, 'slot1', '', lambda: True, workspace=workspace, ramdisk_workspace=ramdisk)
    return SimpleNamespace(run=run, fake=fake, spec=spec, node=node, binary=binary, route=route,
                           log_dir=config.private_root / 'attempts' / ATTEMPT)


def inference_argv(binary, slug, *extra):
    return [str(binary), *(slug if arg == '{model}' else arg for arg in AGY_ARGV), *extra]


def failure_metadata(log_dir):
    text = (log_dir / 'failure.json').read_text(encoding='utf-8')
    return text, json.loads(text)


# --- G2: bound dispatch, routed identity and fail-closed classification ---

@pytest.mark.parametrize('binding, slug', [(HIGH, HIGH), ({'argv': ROUTED, 'reports': HIGH}, ROUTED)])
def test_bound_agy_route_dispatches_reviewed_slug_and_receipts_routed_identity(tmp_path, monkeypatch, binding, slug):
    h = harness(tmp_path, monkeypatch, bindings={ROUTED: binding}, inference=(agy_stream(HIGH), b'', 0))
    output, receipt = h.run()
    assert output == {'ready': True}
    exe = str(h.binary)
    assert h.fake.launches == [[exe, '--version'], [exe, *AUTH_ARGV], inference_argv(h.binary, slug)]
    assert h.fake.launches[-1].count(slug) == 1 and '{model}' not in h.fake.launches[-1]
    assert all(process.closed for process in h.fake.processes)
    assert receipt['selected_route']['provider'] == 'gemini'
    assert receipt['requested_model'] == receipt['reported_model'] == ROUTED
    assert receipt['native_reported_model'] == HIGH
    assert receipt['native_selected_model'] == slug
    assert receipt['model_identity'] == {'policy': IDENTITY_POLICY, 'argv': slug, 'reports': HIGH}
    assert receipt['inference_policy']['identity_policy'] == IDENTITY_POLICY
    assert receipt['inference_policy']['native_model'] == {'argv': slug, 'reports': HIGH}
    assert receipt['inference_policy']['version'] == VERSION
    assert 'wbs_reconciliation' not in receipt  # Non-chapter output passes through unchanged.
    assert receipt['output_sha256'] == output_digest(output)
    JobStore._receipt(output, receipt)
    assert json.loads((h.log_dir / 'receipt.json').read_text(encoding='utf-8')) == receipt
    assert not (h.log_dir / 'failure.json').exists()


def test_extended_route_binds_effort_contract_and_argv_slug(tmp_path, monkeypatch):
    key = ROUTED + ':extended'
    h = harness(tmp_path, monkeypatch, score=4, bindings={key: {'argv': ROUTED, 'reports': HIGH}},
                contracts={key: extended_contract()}, inference=(agy_stream(HIGH), b'', 0))
    output, receipt = h.run()
    exe = str(h.binary)
    assert h.route['reasoning_effort'] == 'extended'
    assert h.fake.launches == [[exe, '--version'], [exe, '--version'], [exe, *AUTH_ARGV],
                               inference_argv(h.binary, ROUTED, '--effort', 'high')]
    assert receipt['requested_effort'] == 'extended' and receipt['reported_effort'] is None
    assert receipt['reported_model'] == ROUTED and receipt['native_reported_model'] == HIGH
    assert receipt['model_identity'] == {'policy': IDENTITY_POLICY, 'argv': ROUTED, 'reports': HIGH}
    assert receipt['inference_policy']['reasoning_effort']['observation_status'] == 'not_reported_by_reviewed_cli'


@pytest.mark.parametrize('score, bindings, contracts', [
    (1, {ROUTED + ':extended': HIGH}, {ROUTED + ':extended': extended_contract()}),  # effort-null route unbound
    (7, {ROUTED: HIGH}, None),  # the pro tier stays unbound in r5
])
def test_unbound_gemini_target_is_compatibility_before_any_launch(tmp_path, monkeypatch, score, bindings, contracts):
    h = harness(tmp_path, monkeypatch, score=score, bindings=bindings, contracts=contracts,
                inference=(agy_stream(HIGH), b'', 0))
    with pytest.raises(ProviderFailure) as caught:
        h.run()
    assert caught.value.category == 'compatibility' and caught.value.hold_scope == 'model'
    assert str(caught.value.__cause__) == 'Gemini route has no reviewed native model binding'
    assert h.fake.launches == []
    assert not (h.log_dir / 'failure.json').exists() and not (h.log_dir / 'receipt.json').exists()


@pytest.mark.parametrize('stream_model, stderr', [
    (ROUTED, b''),  # the argv slug echoed instead of the reviewed reported name
    ('gemini-2.5-flash', b''),
    (HIGH, f'{HIGH} is no longer available. Using gemini-2.5-flash\n'.encode()),
])
def test_identity_error_after_launch_is_compatibility_not_protocol(tmp_path, monkeypatch, stream_model, stderr):
    h = harness(tmp_path, monkeypatch, bindings={ROUTED: {'argv': ROUTED, 'reports': HIGH}},
                inference=(agy_stream(stream_model), stderr, 0))
    with pytest.raises(ProviderFailure) as caught:
        h.run()
    assert caught.value.category == 'compatibility' and caught.value.hold_scope == 'model'
    assert isinstance(caught.value.__cause__, AgyIdentityError)
    assert len(h.fake.launches) == 3
    _, metadata = failure_metadata(h.log_dir)
    assert metadata['category'] == 'compatibility' and metadata['envelope_kind'] == 'agy_identity'
    assert metadata['exit_code'] == 0 and metadata['stderr_bytes'] == len(stderr)
    assert not (h.log_dir / 'receipt.json').exists()


@pytest.mark.parametrize('stdout, envelope', [
    (b'not a native stream\n', 'none'),
    (b'{}\n{}\n', 'none'),
    (agy_stream(HIGH, status='FAILED'), 'gemini_error'),
])
def test_malformed_stream_after_launch_is_protocol(tmp_path, monkeypatch, stdout, envelope):
    h = harness(tmp_path, monkeypatch, inference=(stdout, b'', 0))
    with pytest.raises(ProviderFailure) as caught:
        h.run()
    assert caught.value.category == 'protocol'
    assert not isinstance(caught.value.__cause__, AgyIdentityError)
    _, metadata = failure_metadata(h.log_dir)
    assert metadata['category'] == 'protocol' and metadata['envelope_kind'] == envelope
    assert metadata['stdout_sha256'] == hashlib.sha256(stdout).hexdigest()


def test_complete_contract_passes_every_prelaunch_gate_without_a_launch(tmp_path):
    binary = tmp_path / 'agy.exe'
    binary.write_bytes(BINARY)
    spec = gemini_spec(binary, {ROUTED: HIGH})
    check_native_integration('gemini', spec)
    require_serving_model_contract(spec)
    argv = provider_command('gemini', [str(binary)], ROUTED, 'ram-project', spec, inference_only=True)
    assert argv == inference_argv(binary, HIGH)
    digest = gemini_binary_digest(spec)
    assert digest == DIGEST
    assert validate_gemini_version(spec, VERSION + '\n', digest)['model_fallback_disabled'] is True


def test_policy_does_not_bypass_binary_digest_gate(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, inference=(agy_stream(HIGH), b'', 0))
    h.binary.write_bytes(BINARY + b' replaced')
    with pytest.raises(ProviderFailure) as caught:
        h.run()
    assert caught.value.category == 'compatibility'
    assert h.fake.launches == []


def test_policy_does_not_bypass_version_gate(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, version='1.3.2', inference=(agy_stream(HIGH), b'', 0))
    with pytest.raises(ProviderFailure) as caught:
        h.run()
    assert caught.value.category == 'compatibility'
    assert h.fake.launches == [[str(h.binary), '--version']]


def test_policy_does_not_bypass_subscription_probe_gate(tmp_path, monkeypatch):
    failed = json.dumps({'status': 'FAILED', 'command': {'name': 'models'}}).encode()
    h = harness(tmp_path, monkeypatch, auth=failed, inference=(agy_stream(HIGH), b'', 0))
    with pytest.raises(ProviderFailure) as caught:
        h.run()
    assert caught.value.category == 'auth'
    assert h.fake.launches == [[str(h.binary), '--version'], [str(h.binary), *AUTH_ARGV]]
    assert not (h.log_dir / 'failure.json').exists()


# --- W2: controller restoration of chapter WBS declarations ---

def test_drifted_chapter_draft_is_restored_before_its_receipt_digest(tmp_path, monkeypatch):
    declared = [{'id': 'storage-1', 'description': 'Store evidence', 'requirements': ['REQ-2'], 'dependencies': []}]
    payload = {'chapter_id': 'storage', 'chapter_index': 1, 'title': 'Storage', 'requirements': ['REQ-2'],
               'wbs_tasks_defined': declared, 'objective': 'Write the storage chapter'}
    drifted = {'chapter_id': 'storage', 'requirements_traced': ['REQ-2'],
               'wbs_tasks_defined': [{'id': 'storage-1', 'description': 'Store the evidence', 'requirements': ['REQ-2']},
                                     {'id': 'storage-index', 'description': 'Index evidence', 'requirements': ['REQ-2']}],
               'artifact_uri': 'db://fixture-workflow/storage', 'artifact_text': '# Storage'}
    h = harness(tmp_path, monkeypatch, kind='CHAPTER_DRAFT', payload=payload,
                inference=(agy_stream(HIGH, json.dumps(drifted)), b'', 0))
    output, receipt = h.run()
    assert output['wbs_tasks_defined'] == [declared[0], drifted['wbs_tasks_defined'][1]]
    assert {key: value for key, value in output.items() if key != 'wbs_tasks_defined'} == {
        key: value for key, value in drifted.items() if key != 'wbs_tasks_defined'}
    assert receipt['output_sha256'] == output_digest(output) != output_digest(drifted)
    assert receipt['wbs_reconciliation'] == {
        'schema': 'cochem-chapter-wbs-reconciliation/1', 'model_output_sha256': output_digest(drifted),
        'declared_task_ids': ['storage-1'], 'restored_omitted_ids': [],
        'restored_rewritten_ids': ['storage-1'], 'additional_task_ids': ['storage-index']}
    assert list(receipt).index('usage') < list(receipt).index('wbs_reconciliation')
    JobStore._receipt(output, receipt)
    assert h.node['payload']['wbs_tasks_defined'] == declared
    assert json.loads((h.log_dir / 'receipt.json').read_text(encoding='utf-8'))['wbs_reconciliation'] == \
        receipt['wbs_reconciliation']


# --- N2: protected failure metadata for failed native attempts ---

def test_nonzero_exit_with_empty_stdout_writes_only_allowlisted_failure_metadata(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, inference=(b'', STDERR, 1))
    with pytest.raises(ProviderFailure) as caught:
        h.run()
    assert caught.value.category == 'code'
    text, metadata = failure_metadata(h.log_dir)
    assert set(metadata) == NATIVE_FAILURE_KEYS
    assert {key: metadata[key] for key in NATIVE_FAILURE_KEYS - {'started_at', 'finished_at'}} == {
        'schema': NATIVE_FAILURE_SCHEMA, 'category': 'code', 'exit_code': 1,
        'stdout_bytes': 0, 'stdout_sha256': hashlib.sha256(b'').hexdigest(),
        'stderr_bytes': len(STDERR), 'stderr_sha256': hashlib.sha256(STDERR).hexdigest(),
        'envelope_kind': 'none', 'claude_result_subtype': None, 'api_status': None}
    assert isinstance(metadata['started_at'], float) and metadata['started_at'] <= metadata['finished_at']
    diagnostic = STDERR.decode()
    assert not any(diagnostic[index:index + 6] in text for index in range(len(diagnostic) - 5))
    assert not (h.log_dir / 'receipt.json').exists()
    assert (h.log_dir / 'stderr.log').read_bytes() == STDERR  # raw text stays only in the protected log


def test_output_budget_failure_records_sizes_without_reading_the_overflow(tmp_path, monkeypatch):
    oversized = b'x' * (NATIVE_OUTPUT_LIMIT_BYTES + 1)
    h = harness(tmp_path, monkeypatch, inference=(oversized, b'', 0))
    with pytest.raises(ProviderFailure) as caught:
        h.run()
    assert caught.value.category == 'resource'
    _, metadata = failure_metadata(h.log_dir)
    assert metadata['category'] == 'resource' and metadata['exit_code'] is None
    assert (metadata['stdout_bytes'], metadata['stdout_sha256']) == (NATIVE_OUTPUT_LIMIT_BYTES + 1, None)
    assert (metadata['stderr_bytes'], metadata['stderr_sha256']) == (0, None)
    assert metadata['envelope_kind'] == 'none'


def test_attempt_directory_and_failure_metadata_are_never_reused(tmp_path, monkeypatch):
    h = harness(tmp_path, monkeypatch, inference=(agy_stream(HIGH), b'', 0))
    h.log_dir.mkdir(parents=True)
    with pytest.raises(FileExistsError):
        h.run()
    assert h.fake.launches == []

    second = tmp_path / 'second'
    second.mkdir()
    sentinel = b'{"pre-existing": true}'
    h = harness(second, monkeypatch, inference=(b'', STDERR, 1),
                on_inference=lambda argv: (h.log_dir / 'failure.json').write_bytes(sentinel))
    with pytest.raises(ProviderFailure) as caught:
        h.run()
    # Exclusive creation never replaces an entry, and diagnostics never mask the routed category.
    assert caught.value.category == 'code'
    assert (h.log_dir / 'failure.json').read_bytes() == sentinel
    metadata = native_failure_metadata('gemini', 'code', 1, b'', b'', started_at=1.0, finished_at=2.0)
    with pytest.raises(FileExistsError):
        write_native_failure_metadata(h.log_dir, metadata)
    with pytest.raises(ValueError):
        write_native_failure_metadata(tmp_path, {**metadata, 'stderr_text': 'leak'})
    assert not (tmp_path / 'failure.json').exists()


SECRET = 'SECRET-MSG-zq9'


@pytest.mark.parametrize('provider, stdout, expected', [
    ('claude', {'type': 'result', 'subtype': 'success', 'is_error': True, 'session_id': 's',
                'result': f'API Error: 529 {{"type":"error","error":{{"message":"{SECRET}"}}}}'},
     ('claude_result_is_error', 'success', 529)),
    ('claude', {'type': 'result', 'subtype': 'success', 'is_error': True,
                'result': f'Failed to authenticate. API Error: 401 {SECRET}'},
     ('claude_result_is_error', 'success', 401)),
    ('claude', {'type': 'result', 'subtype': 'error_during_execution', 'result': SECRET},
     ('claude_result_is_error', 'error_during_execution', None)),
    ('claude', {'type': 'result', 'subtype': f'error_{SECRET}', 'is_error': True, 'result': SECRET},
     ('claude_result_is_error', None, None)),
    ('claude', {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': f'API Error: 401 {SECRET}'},
     ('none', 'success', None)),
    ('claude', {'type': 'error', 'error': {'type': 'rate_limit_error', 'message': SECRET}},
     ('claude_error_record', None, None)),
    ('codex', {'type': 'turn.failed', 'error': {'message': SECRET}}, ('codex_turn_failed', None, None)),
    ('codex', {'type': 'error', 'message': SECRET}, ('codex_turn_failed', None, None)),
    ('gemini', {'error': {'code': 429, 'message': SECRET}}, ('gemini_error', None, None)),
    ('gemini', {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': SECRET}, ('none', None, None)),
])
def test_failure_envelope_is_classified_without_raw_text(provider, stdout, expected):
    raw = json.dumps(stdout).encode()
    metadata = native_failure_metadata(provider, 'code', 1, raw, SECRET.encode(), started_at=1.0, finished_at=2.0)
    assert set(metadata) == NATIVE_FAILURE_KEYS
    assert (metadata['envelope_kind'], metadata['claude_result_subtype'], metadata['api_status']) == expected
    assert (metadata['stdout_bytes'], metadata['stdout_sha256']) == (len(raw), hashlib.sha256(raw).hexdigest())
    rendered = json.dumps(metadata)
    assert SECRET not in rendered and 'zq9' not in rendered
    identity = native_failure_metadata(provider, 'compatibility', 0, raw, b'', started_at=1.0, finished_at=2.0,
                                       agy_identity=True)
    assert identity['envelope_kind'] == 'agy_identity'


def changed_stream(change):
    events = [json.loads(line) for line in agy_stream(HIGH).decode().splitlines()]
    change(events)
    return ('\n'.join(json.dumps(event) for event in events) + '\n').encode()


# --- AG-1: agy's 'AGY_ERROR: {...}' stderr line with a nonzero exit (3 per the agy changelog) ---

AGY_SECRET = 'SECRET-AGY-zq9'
AGY_UNKNOWN = ('AGY_ERROR: {"code":"MODEL_NOT_FOUND","message":"model %s not found %s"}\n'
               % (HIGH, AGY_SECRET)).encode()
AGY_QUOTA = ('AGY_ERROR: {"error":{"code":429,"status":"RESOURCE_EXHAUSTED",'
             '"message":"MODEL_CAPACITY_EXHAUSTED %s"}}\n' % AGY_SECRET).encode()
ERROR_RESULT = changed_stream(lambda events: (events.pop(1), events[-1]['result'].update(
    status='ERROR', error={'message': 'unknown model ' + AGY_SECRET}, num_turns=0)))


def assert_no_agy_text(text):
    for raw in (AGY_SECRET, 'not found', 'CAPACITY', 'MODEL_', 'AGY_ERROR', 'unknown model', 'defaulting'):
        assert raw not in text


@pytest.mark.parametrize('stdout, stderr, code, category, scope, envelope', [
    pytest.param(b'', AGY_UNKNOWN, 3, 'compatibility', 'model', 'agy_error', id='unknown-model-exit3'),
    pytest.param(ERROR_RESULT, AGY_UNKNOWN, 3, 'compatibility', 'model', 'gemini_error', id='error-result-exit3'),
    pytest.param(b'', AGY_UNKNOWN, 1, 'compatibility', 'model', 'agy_error', id='unknown-model-exit1'),
    pytest.param(b'', AGY_QUOTA, 3, 'quota', 'pool', 'agy_error', id='quota-exit3'),
    pytest.param(b'', b'\x1b[31m' + AGY_QUOTA.rstrip(b'\n') + b'\x1b[0m\r\n', 3, 'quota', 'pool', 'agy_error',
                 id='ansi-quota-exit3'),
    pytest.param(b'', b'AGY_ERROR: {"error":{"code":503,"status":"UNAVAILABLE"}}\n', 3, 'busy', 'model',
                 'agy_error', id='busy-exit3'),
])
def test_typed_agy_error_line_classifies_the_nonzero_exit(tmp_path, monkeypatch, stdout, stderr, code,
                                                          category, scope, envelope):
    h = harness(tmp_path, monkeypatch, inference=(stdout, stderr, code))
    with pytest.raises(ProviderFailure) as caught:
        h.run()
    assert (caught.value.category, caught.value.hold_scope) == (category, scope)
    assert caught.value.args == (caught.value.summary,)
    assert len(h.fake.launches) == 3
    text, metadata = failure_metadata(h.log_dir)
    assert set(metadata) == NATIVE_FAILURE_KEYS
    assert (metadata['category'], metadata['exit_code'], metadata['envelope_kind']) == (category, code, envelope)
    assert metadata['stderr_sha256'] == hashlib.sha256(stderr).hexdigest()
    assert_no_agy_text(text)
    assert_no_agy_text(str(caught.value))
    assert not (h.log_dir / 'receipt.json').exists()


@pytest.mark.parametrize('stdout, stderr, code', [
    pytest.param(b'', b'AGY_ERROR: {"code":"x","message":"' + AGY_SECRET.encode() + b'"}\n', 3, id='untyped'),
    pytest.param(b'', b'AGY_ERROR: requested model unavailable ' + AGY_SECRET.encode() + b'\n', 3, id='prose'),
    pytest.param(b'', b'AGY_ERROR: {"code":"INVALID_ARGUMENT","message":"invalid model selection"}\n', 3,
                 id='argument-error'),
    pytest.param(b'', b'AGY_ERROR: {"error":{"code":429},"pad":"' + b'x' * 70000 + b'"}\n', 3, id='oversized'),
    pytest.param(b'', b'warning: ' + AGY_QUOTA, 3, id='prefix-not-at-line-start'),
    pytest.param(ERROR_RESULT, b'AGY_ERROR: {"code":"x"}\n', 3, id='error-result-untyped'),
    pytest.param(agy_stream(HIGH), f'{HIGH} is no longer available. Using gemini-2.5-flash\n'.encode(), 2,
                 id='reroute-marker-exit2'),
    pytest.param(b'', f'Model ID {HIGH} not in local config, defaulting to CCPA\n'.encode(), 3,
                 id='defaulting-to-exit3'),
])
def test_untyped_agy_error_or_reroute_diagnostic_on_nonzero_exit_is_compatibility(tmp_path, monkeypatch,
                                                                                   stdout, stderr, code):
    h = harness(tmp_path, monkeypatch, inference=(stdout, stderr, code))
    with pytest.raises(ProviderFailure) as caught:
        h.run()
    assert (caught.value.category, caught.value.hold_scope) == ('compatibility', 'model')
    assert isinstance(caught.value.__cause__, AgyIdentityError)
    text, metadata = failure_metadata(h.log_dir)
    assert (metadata['category'], metadata['exit_code'], metadata['envelope_kind']) == (
        'compatibility', code, 'agy_identity')
    assert_no_agy_text(text)
    assert_no_agy_text(str(caught.value))
    assert not (h.log_dir / 'receipt.json').exists()


def test_nonzero_exit_without_agy_diagnostics_stays_code(tmp_path, monkeypatch):
    for index, stderr in enumerate((STDERR, b'Loaded cached credentials.\nagy_error: lowercase is not agy\n')):
        root = tmp_path / str(index)
        root.mkdir()
        h = harness(root, monkeypatch, inference=(agy_stream(HIGH), stderr, 3))
        with pytest.raises(ProviderFailure) as caught:
            h.run()
        assert caught.value.category == 'code' and caught.value.hold_scope is None
        _, metadata = failure_metadata(h.log_dir)
        assert (metadata['category'], metadata['envelope_kind']) == ('code', 'none')


# --- AG-2 end to end: nested identity and reroute fields are model holds, not receipts ---

@pytest.mark.parametrize('change', [
    lambda events: events[-1]['result']['usage'].update(model='gemini-2.5-flash'),
    lambda events: events[-1]['result'].update(used_non_gemini_model=True),
    lambda events: events[1]['step_update'].update(metadata={'model': 'gemini-2.5-flash'}),
    lambda events: events[0]['init'].update(resolved_model='gemini-2.5-flash'),
])
def test_nested_identity_contradiction_after_launch_is_compatibility(tmp_path, monkeypatch, change):
    h = harness(tmp_path, monkeypatch, inference=(changed_stream(change), b'', 0))
    with pytest.raises(ProviderFailure) as caught:
        h.run()
    assert (caught.value.category, caught.value.hold_scope) == ('compatibility', 'model')
    assert isinstance(caught.value.__cause__, AgyIdentityError)
    assert not isinstance(caught.value.__cause__, agy_protocol.AgyToolRegistryError)
    _, metadata = failure_metadata(h.log_dir)
    assert metadata['envelope_kind'] == 'agy_identity'
    assert not (h.log_dir / 'receipt.json').exists()


# --- AG-3: tool-registry and subagent violations have their own envelope kind ---

@pytest.mark.parametrize('change', [
    lambda events: events[0]['init'].update(tools=['read_file']),
    lambda events: events[0]['init'].pop('tools'),
    lambda events: events[1]['step_update'].update(tool_name='run_shell'),
    lambda events: events[1]['step_update'].update(subagent_info={'name': 'helper'}),
])
def test_tool_registry_violation_after_launch_has_its_own_envelope(tmp_path, monkeypatch, change):
    h = harness(tmp_path, monkeypatch, inference=(changed_stream(change), b'', 0))
    with pytest.raises(ProviderFailure) as caught:
        h.run()
    assert (caught.value.category, caught.value.hold_scope) == ('compatibility', 'model')
    assert isinstance(caught.value.__cause__, agy_protocol.AgyToolRegistryError)
    text, metadata = failure_metadata(h.log_dir)
    assert (metadata['category'], metadata['envelope_kind']) == ('compatibility', 'agy_tool_registry')
    assert 'read_file' not in text and 'run_shell' not in text and 'helper' not in text
    assert not (h.log_dir / 'receipt.json').exists()


def test_agy_envelope_kinds_are_allowlisted():
    for value, expected in ((True, 'agy_identity'), ('agy_identity', 'agy_identity'),
                            ('agy_tool_registry', 'agy_tool_registry'), (SECRET, 'agy_identity'),
                            (False, 'none'), (None, 'none')):
        metadata = native_failure_metadata('gemini', 'compatibility', 0, b'', b'', started_at=1.0,
                                           finished_at=2.0, agy_identity=value)
        assert metadata['envelope_kind'] == expected
    line = b'AGY_ERROR: {"code":"x"}\n'
    assert native_failure_metadata('gemini', 'code', 3, b'', line, started_at=1.0,
                                   finished_at=2.0)['envelope_kind'] == 'agy_error'
    for provider in ('codex', 'claude'):
        assert native_failure_metadata(provider, 'code', 3, b'', line, started_at=1.0,
                                       finished_at=2.0)['envelope_kind'] == 'none'


def test_unread_streams_record_sizes_only():
    metadata = native_failure_metadata('claude', 'resource', None, None, None, started_at=1.0, finished_at=2.0,
                                       stream_sizes=(9, 4))
    assert (metadata['stdout_bytes'], metadata['stdout_sha256'], metadata['stderr_bytes'],
            metadata['stderr_sha256']) == (9, None, 4, None)
    assert (metadata['exit_code'], metadata['envelope_kind']) == (None, 'none')
    assert native_failure_metadata('claude', 'code', True, None, None, started_at=1.0,
                                   finished_at=2.0)['exit_code'] is None
