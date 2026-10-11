"""Inert harness for build-pipeline-config-r5-candidate.py (r5 sitting S9, CONFIG-BUILDER).

Fixture evidence is produced in tmp_path with the producing helpers' own pure functions, so the receipts have the
exact on-disk schemas: agy_isolation_evidence_r4_v1.py (new_report, new_stage_report, classify_run, run_checks,
write_replay, raw_digest, classify_probe, precheck_decision, listing_reasons, isolation_verdict, identity_verdict,
isolation_gate, staging_gate, bounded_receipt_text) and agy_status_capture_r4_v1.py (classify, capture_gate,
bounded_receipt_text). The PowerShell records (series-complete.json, *-summary.json, *-held.json) carry the keys of
New-SeriesCompleteRecord, New-CaptureSummary, New-IsolationSummary and New-StageSummary. The agy streams are
synthetic NDJSON consistent with agy_protocol.parse_stream. The repo venv (Python 3.12, editable install of the
working-tree r5 cochem_pipeline) stands in for the installed r5 interpreter.

Nothing here runs agy, claude, codex or gemini, touches the network, writes under Program Files or ProgramData, or
touches a scheduled task or service; the only child processes are the repo venv interpreter running the builder.
The real commissioned file is only read (hashed and copied into tmp_path). The fixture evidence roots live in tmp_path,
so the in-process runs replace the builder's check_root_custody (B-F1: roots directly under C:\\Program Files\\CoChem with
a protected ancestry) by a stub; the custody rule itself is tested against read-only ACL reads of C:\\Program Files and
tmp_path, and one CLI run keeps the real rule and must hold.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

W = Path(__file__).resolve().parent
BUILDER_PATH = W / 'build-pipeline-config-r5-candidate.py'
ISO_PATH = W / 'agy_isolation_evidence_r4_v1.py'
CAP_PATH = W / 'agy_status_capture_r4_v1.py'
REPO = Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent')
PY = REPO / '.venv' / 'Scripts' / 'python.exe'
COMMISSIONED = Path(r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\pipeline.json')
PIN = '135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
AGY = '38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741'
AGENT_SHA = '5c0082d70d073263a56d748a46187008968c070d0efc7d5b7612c2fd61d11810'
EXECUTABLE = r'C:\Program Files\CoChem\Native4.2.7-windows-20261006\agy.exe'
ATTEMPT = 'e' * 32
NONCE = 'f' * 32
SLOTS = [f'slot{n}' for n in range(1, 7)]
ARGS = ['--agent', 'cochem-inference-only', '--input-format', 'stream-json', '--output-format', 'stream-json',
        '--model', '{model}', '--disable-slash-commands']
GATES = ['G1', 'G2', 'G3', 'G4', 'G5', 'G6']
EMAIL = 'worker1@example.invalid'
ATTEMPT_RECORD_KEYS = ['login.series_complete', 'capture.receipt', 'capture.summary', 'isolation.receipt', 'isolation.summary',
                       'stage.receipt', 'stage.summary']


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


b = load('build_pipeline_config_r5_candidate', BUILDER_PATH)
iso = load('agy_isolation_evidence_r4_v1_builder_fixture', ISO_PATH)
cap = load('agy_status_capture_r4_v1_builder_fixture', CAP_PATH)


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope='session')
def commissioned_bytes():
    if not COMMISSIONED.is_file():
        pytest.skip('the commissioned r4 pipeline.json is not readable on this host')
    data = COMMISSIONED.read_bytes()
    assert sha(data) == PIN
    return data


# ---------------------------------------------------------------- canned agy outputs

USAGE = {'input_tokens': 11, 'output_tokens': 2, 'thinking_tokens': 0, 'cache_read_tokens': 0, 'total_tokens': 13}
CATALOG = ('gemini-3.8-flash-high', 'gemini-3.8-flash-medium', 'gemini-3.8-flash-low', 'gemini-3.7-flash-high',
           'gemini-3.7-flash-medium', 'gemini-3.7-flash-low', 'gemini-3.6-flash-high', 'gemini-3.6-flash-medium',
           'gemini-3.6-flash-low', 'gemini-3.1-pro-high', 'gemini-3.1-pro-low', 'claude-sonnet-4-6', 'gpt-oss-120b')
FETCH = b'Fetching available models...\n'
R1_STDERR = ('Headless auth: authenticated as "' + EMAIL + '"\n').encode()
R2_REJECT = (b'Error: invalid model selection (--model "gemini-3.8-flash-high" --effort "high"): '
             b'--model gemini-3.8-flash-high conflicts with --effort=high\n')
R3_REJECT = b'Error: --model gemini-3.8-flash requires --effort (available: low, medium, high)\n'
R4_STDOUT = (b'{"event":"result","result":{"conversation_id":"conv-4","status":"ERROR","response":"",'
             b'"error":"unknown model \\"gemini-3.1-pro-preview\\"","duration_seconds":0,"num_turns":0}}\n')
R4_STDERR = b'AGY_ERROR: {"code":"INVALID_ARGUMENT","message":"unknown model \\"gemini-3.1-pro-preview\\"","retryable":false}\n'


def envelope(name, data, status='SUCCESS'):
    value = {'conversation_id': '', 'status': status, 'response': '', 'duration_seconds': 0, 'num_turns': 0,
             'usage': {key: 0 for key in USAGE}, 'command': {'name': name, 'data': data}}
    return json.dumps(value, separators=(',', ':')).encode()


def models_envelope(catalog=CATALOG, status='SUCCESS'):
    return envelope('models', {'models': [{'id': slug, 'label': slug.upper()} for slug in catalog]}, status)


AGENTS_OK = envelope('agents', {'agents': ['cochem-inference-only']})
AGENTS_NONE = envelope('agents', {'agents': []})


def stream(model, session, *, tools=(), status='SUCCESS', num_turns=1, response='ready true'):
    init = {'cwd': r'C:\ProgramData\CoChemPipeline427\workers\slot1', 'tools': list(tools),
            'permission_mode': 'request-review', 'model': model, 'agent': 'cochem-inference-only'}
    events = [{'event': 'init', 'conversation_id': session, 'init': init},
              {'event': 'step_update', 'step_update': {'conversation_id': session, 'step_type': 'user_input', 'state': 'DONE', 'step_index': 0}},
              {'event': 'step_update', 'step_update': {'conversation_id': session, 'step_type': 'agent_response', 'state': 'DONE',
                                                       'step_index': 1, 'text_delta': response}},
              {'event': 'result', 'result': {'conversation_id': session, 'status': status, 'response': response,
                                             'duration_seconds': 1.25, 'num_turns': num_turns, 'usage': USAGE}}]
    return ''.join(json.dumps(event, separators=(',', ':')) + '\n' for event in events).encode()


def default_runs(slug):
    return {'R1': (stream('gemini-3.8-flash-high', 'conv-r1'), R1_STDERR, 0),
            'R5': (stream(slug, 'conv-r5'), b'', 0),
            'R2': (b'', R2_REJECT, 1),
            'R3': (stream('gemini-3.8-flash-high', 'conv-r3'), b'', 0),
            'R4': (R4_STDOUT, R4_STDERR, 3)}


# ---------------------------------------------------------------- evidence producers

def ps_json(path, value):
    """The PowerShell writers: ConvertTo-Json text, UTF-8 without BOM, CreateNew."""
    with open(path, 'xb') as handle:
        handle.write(json.dumps(value, indent=4).encode('utf-8'))


def make_login(base, *, rows_patch=None, record_patch=None, extra_files=()):
    root = base / f'NativeAuthSix4.2.7-windows-20261011-r4-v1-{ATTEMPT}-gemini'
    root.mkdir()
    rows = []
    for slot in SLOTS:
        before = {'decision': 'ATTENDED_LOGIN_REQUIRED', 'stage': 'before', 'receipt_path': f'C:\\x\\{slot}-before.json', 'receipt_sha256': 'b' * 64}
        after = {'decision': 'REUSE_VERIFIED_SESSION', 'stage': 'after', 'receipt_path': f'C:\\x\\{slot}-after.json', 'receipt_sha256': 'c' * 64}
        rows.append({'slot': slot, 'outcome': 'AUTHENTICATED_AFTER_LOGIN', 'before': before, 'after': after,
                     'final_decision': 'REUSE_VERIFIED_SESSION', 'reuse_verified': True, 'login_commands_executed': 1, 'bridge': None})
    if rows_patch:
        rows_patch(rows)
    record = {'schema': 'cochem-six-worker-status-first-result/1', 'attempt': ATTEMPT,
              'status': 'SIX_CONFIGURED_WORKERS_SUBSCRIPTION_AUTHENTICATION_VERIFIED', 'provider': 'gemini', 'nonce': NONCE,
              'runtime': {'root': r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4'}, 'configuration_applied': False,
              'selected_workers_verified': 6, 'other_accounts_preserved': True, 'login_commands_executed': 6,
              'existing_sessions_reused': 0, 'status_receipts': [{'slot': slot, 'status': 'AUTHENTICATED_AFTER_LOGIN'} for slot in SLOTS],
              'slots': rows, 'all_slots_reuse_verified': all(row['reuse_verified'] is True for row in rows),
              'login_mode': 'print', 'login_mode_binding': {'mode': 'print'}, 'model_jobs_executed': 0, 'serving_model_verified': False,
              'provider_account_identity_verified': False, 'activation_ready': False, 'completed_utc': '2026-10-11T20:00:00.0000000Z',
              'series_preserved': True}
    if record_patch:
        record_patch(record)
    ps_json(root / 'series-complete.json', record)
    for name in extra_files:
        ps_json(root / name, {'schema': 'cochem-six-worker-status-first-held/1'})
    return root


def capture_probe(raw, probe_id, stdout, stderr=b'', code=0):
    spec = cap.PROBES[probe_id]
    (raw / f'{probe_id}.stdout').write_bytes(stdout)
    (raw / f'{probe_id}.stderr').write_bytes(stderr)
    (raw / f'{probe_id}.stdin').write_bytes(b'')
    return {'id': probe_id, 'argv': [str(cap.EXECUTABLE), *spec['arguments']], 'stdin_mode': 'empty_file', 'bound_seconds': 30,
            'stdin_bytes_written': 0, 'raw_path': {'stdout': f'raw/{probe_id}.stdout', 'stderr': f'raw/{probe_id}.stderr'},
            'cleanup_verified': True, 'outcome': 'exited', 'exit_code': code, 'stdin_sha256': sha(b''),
            'stdout': {'bytes': len(stdout), 'sha256': sha(stdout)}, 'stderr': {'bytes': len(stderr), 'sha256': sha(stderr)},
            'classification': cap.classify(spec['kind'], stdout, stderr, 'exited', code, False)}


def make_capture(base, *, catalog=CATALOG, p2_status='SUCCESS', receipt_patch=None, summary_patch=None, extra_files=()):
    root = base / f'AgyCapture4.2.7-windows-20261010-r4-v1-{ATTEMPT}-slot1-signed-in'
    raw = root / 'raw'
    raw.mkdir(parents=True)
    table = ''.join(f'{slug}\t{slug.upper()}\n' for slug in catalog).encode()
    outputs = {'P1': (b'1.3.1\n', b''), 'P2': (models_envelope(catalog, p2_status), FETCH), 'P2b': (table, FETCH),
               'P7': (AGENTS_NONE, b''), 'P8': (b'', b''), 'P3': (b'gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n', b''),
               'P4': (b'Usage: 0 requests\n', b''), 'P5': (envelope('usage', {}), b'')}
    report = {'schema': 'cochem-agy-status-capture/1', 'attempt': ATTEMPT, 'nonce': NONCE, 'slot': 'slot1', 'stage': 'signed-in',
              'status': 'CAPTURE_COMPLETE', 'system_sid': 'S-1-5-18', 'helper_sha256': sha(CAP_PATH.read_bytes()),
              'runtime_root': str(cap.INSTALL), 'install_receipt_sha256': cap.INSTALL_RECEIPT_SHA256,
              'source_manifest_sha256': cap.MANIFEST_SHA256, 'config_sha256': PIN, 'native_executable': str(cap.EXECUTABLE),
              'native_executable_sha256_before': AGY, 'native_executable_sha256_after': AGY, 'native_version_at_pin': '1.3.1',
              'probes': [capture_probe(raw, probe_id, *outputs[probe_id]) for probe_id, _ in cap.STAGE_PROBES['signed-in']],
              'probes_skipped': [], 'worker_identity': 'CoChem422Worker1', 'profile_root': r'C:\Users\CoChem422Worker1',
              'runtime_custody_verified': True, 'require_stopped_before': True, 'require_stopped_after': True,
              'daemon_states_verified_before_and_after': True, 'cleanup_verified': True, 'native_model_jobs_executed': 0,
              'login_inputs_written': 0, 'stdin_bytes_written': 0, 'owner_credentials_read': False, 'token_files_opened': 0,
              'raw_output_published': False, 'oauth_urls_possibly_minted': 0, 'login_mode': None, 'pipeline_started': False}
    report['gate'] = cap.capture_gate('signed-in', report['status'], report['probes'], None)
    if receipt_patch:
        receipt_patch(report)
    text = cap.bounded_receipt_text(report).encode('ascii')
    (root / 'capture-receipt.json').write_bytes(text)
    summary = {'schema': 'cochem-agy-status-capture-result/1', 'status': report['status'], 'decision': 'COMPLETE', 'attempt': ATTEMPT,
               'slot': 'slot1', 'stage': 'signed-in', 'nonce': NONCE, 'target_root': str(root),
               'receipt_path': str(root / 'capture-receipt.json'), 'receipt_sha256': sha(text),
               'task_name': f'CoChem-4.2.7-AgyCapture-20261010-r4-v1-{ATTEMPT}-slot1-signed-in', 'last_task_result': 0,
               'task_preserved': True, 'gate': {'passed': report['gate']['passed'], 'reasons': report['gate']['reasons']},
               'series_stop': not report['gate']['passed'], 'failure': None, 'login_mode': None,
               'p2_status_helper_classification': 'LOGGED_IN', 'raw_output_location': str(raw), 'message': 'Signed-in capture verified.'}
    if summary_patch:
        summary_patch(summary)
    ps_json(root / 'capture-summary.json', summary)
    for name in extra_files:
        ps_json(root / name, {'schema': 'cochem-agy-status-capture-held/1'})
    return root


CLEAN_PROFILE_FLAGS = {'hooks_present': False, 'mcp_present': False, 'plugins_present': False, 'skills_present': False,
                       'rules_present': False, 'workflows_present': False}
CLEAN_WORKSPACE_FLAGS = {'hooks_present': False, 'mcp_present': False, 'plugins_present': False, 'skills_present': False}


def staged_records(identity, preexisting):
    return [{'path': f'C:\\Users\\{identity}\\' + '\\'.join(parts), 'relative': '/'.join(parts), 'sha256': AGENT_SHA,
             'bytes': iso.AGENT_BYTES, 'preexisting': preexisting, 'created_directories': [], 'acl_verified': True,
             'file_acl_sddl': iso.AGENT_FILE_SDDL.format(sid='S-1-5-21-1-2-3-1001'),
             'directory_acl_sddl': iso.AGENT_DIRECTORY_SDDL.format(sid='S-1-5-21-1-2-3-1001')}
            for parts in iso.AGENT_DESTINATION_PARTS]


def probe_record(raw, probe_id, arguments, kind, stdout, stderr=b'', code=0, prefix=''):
    names = {suffix: raw / f'{prefix}{probe_id}.{suffix}' for suffix in ('stdout', 'stderr', 'stdin')}
    names['stdout'].write_bytes(stdout)
    names['stderr'].write_bytes(stderr)
    names['stdin'].write_bytes(b'')
    return {'id': probe_id, 'argv': [str(iso.EXECUTABLE), *arguments], 'kind': kind, 'stdin_mode': 'empty_file',
            'bound_seconds': 30, 'output_limit_bytes': 65536, 'stdin_bytes_written': 0,
            'raw_path': {'stdout': f'raw/{prefix}{probe_id}.stdout', 'stderr': f'raw/{prefix}{probe_id}.stderr'},
            'cleanup_verified': True, 'phase_reached': 'precheck_result', 'stdin_sha256': sha(b''), 'outcome': 'exited',
            'exit_code': code, 'stdout': iso.raw_digest(names['stdout']), 'stderr': iso.raw_digest(names['stderr']),
            'classification': iso.classify_probe(kind, stdout, stderr, 'exited', code)}


def make_isolation(base, *, slug='gemini-3.8-flash-low', runs=None, profile_flags=None, receipt_patch=None,
                   summary_patch=None, replay_patch=None, extra_files=()):
    root = base / f'AgyIsolation4.2.7-windows-20261011-r4-v1-{ATTEMPT}'
    raw, replay = root / 'raw', root / 'replay'
    for path in (root, raw, replay):
        path.mkdir()
    matrix = iso.run_matrix(slug)
    report = iso.new_report('slot1', NONCE, ATTEMPT, sha(ISO_PATH.read_bytes()), 'S-1-5-18', slug)
    report.update(production_arguments_validated=True, runtime_custody_verified=True, require_stopped_before=True,
                  require_stopped_after=True, daemon_states_verified_before_and_after=True, native_executable_sha256_before=AGY,
                  native_executable_sha256_after=AGY, layout_sha256=iso.LAYOUT_SHA256, config_sha256=PIN,
                  worker_identity='CoChem422Worker1', profile_root=r'C:\Users\CoChem422Worker1',
                  slot_root=r'C:\ProgramData\CoChemPipeline427\workers\slot1', ram_workspace_root=r'R:\CoChem427-windows-20261007\slot1')
    report['agent'].update(staged=staged_records('CoChem422Worker1', False), shadows_found=[], verified_before_each_launch=True,
                           shadow_locations_checked=['.gemini/agents', '.gemini/config/agents'])
    flags = profile_flags or {}
    report['profiles'] = [{'slot': slot, 'identity': f'CoChem422Worker{n}', 'profile_present': True, 'paths': [],
                           'flags': dict(CLEAN_PROFILE_FLAGS, **flags.get(slot, {}))} for n, slot in enumerate(SLOTS, 1)]
    report['workspaces'] = [{'label': label, 'paths': [], 'flags': dict(CLEAN_WORKSPACE_FLAGS)} for label in ('slot_root', 'ram_workspace')]
    report['environment_attestation'] = {'variable_count': 40, 'flagged_names': [], 'flagged_names_expected': [],
                                         'flagged_names_absent': True, 'profile_binding_verified': True, 'values_recorded': False}
    precheck_outputs = {'PC1': (b'1.3.1\n', b''), 'PC2': (models_envelope(), FETCH), 'PC3': (AGENTS_OK, b''),
                        'PC4': (b'cochem-inference-only\n', b'')}
    report['precheck']['probes'] = [probe_record(raw, probe_id, arguments, kind, *precheck_outputs[probe_id])
                                    for probe_id, arguments, kind in iso.PRECHECK]
    report['precheck'].update(iso.precheck_decision(report['precheck']['probes'], []))
    outputs = default_runs(slug)
    outputs.update(runs or {})
    for index, (run_id, model, extra, _) in enumerate(matrix):
        stdout, stderr, code = outputs[run_id]
        paths = {name: raw / f'{run_id}.{name}' for name in ('stdout', 'stderr', 'stdin')}
        paths['stdout'].write_bytes(stdout)
        paths['stderr'].write_bytes(stderr)
        paths['stdin'].write_bytes(iso.PROMPT_LINE)
        record = {'id': run_id, 'requested_model': model, 'extra_arguments': list(extra), 'argv': iso.inference_argv(model, extra),
                  'stdin_mode': 'pipe_one_ndjson_line_then_eof', 'bound_seconds': 120, 'output_limit_bytes': 1048576,
                  'stdin_bytes_written': len(iso.PROMPT_LINE), 'prompt_delivered': True, 'stdin_write_error': None,
                  'raw_path': {name: f'raw/{run_id}.{name}' for name in ('stdout', 'stderr', 'stdin')}, 'cleanup_verified': True,
                  'stdin_sha256': iso.PROMPT_LINE_SHA256, 'outcome': 'exited', 'exit_code': code, 'terminated_by_bound': False,
                  'stdout': iso.raw_digest(paths['stdout']), 'stderr': iso.raw_digest(paths['stderr'])}
        record['classification'] = iso.classify_run(stdout, stderr, 'exited', code, model, None)
        # O-F1: the owned Job held agy's own tree only (job_process_accounting after TerminateJobObject).
        record['job_accounting'] = {'total_processes': 2, 'active_processes': 0, 'total_terminated_processes': 2,
                                    'expected_maximum': iso.JOB_EXPECTED_PROCESSES_MAXIMUM, 'queried_after_job_termination': True,
                                    'source': 'QueryInformationJobObject(JobObjectBasicAccountingInformation) on the owned Job'}
        record['checks'] = iso.run_checks(record, model)
        record['replay'] = iso.write_replay(replay, run_id, paths['stdout'], paths['stderr'])
        record['phase_reached'] = 'inference_result'
        report['runs'].append(record)
        if record['checks']['isolation_breach']:
            report['runs_skipped'] = [{'id': item[0], 'reason': 'ISOLATION_BREACH_STOP'} for item in matrix[index + 1:]]
            break
    iso.count_jobs(report)
    report['cleanup_verified'] = True
    report['status'] = 'EVIDENCE_COMPLETE'
    # O-F2: C:\ProgramData\Antigravity absent before and after the runs (programdata_antigravity_state ABSENT).
    absent_state = {'path': str(iso.PROGRAMDATA_ANTIGRAVITY), 'exists': False, 'state': 'ABSENT', 'entry_count': 0, 'entries': [],
                    'acl': None, 'clear': True}
    report['programdata_antigravity'] = {'path': str(iso.PROGRAMDATA_ANTIGRAVITY), 'before': dict(absent_state),
                                         'after': dict(absent_state), 'clear': True}
    report['isolation_verdict'] = iso.isolation_verdict(report['runs'], report['profiles'], report['workspaces'],
                                                        report['programdata_antigravity'])
    report['identity_verdict'] = iso.identity_verdict(report['runs'], matrix, slug, report.get('runs_skipped'))
    report['gate'] = iso.isolation_gate(report['status'], report['precheck'], report['runs'], report['isolation_verdict'])
    report['replay_streams'] = {item['id']: dict(item['replay'], requested_model=item['requested_model'],
                                                 extra_arguments=item['extra_arguments'], exit_code=item.get('exit_code'),
                                                 outcome=item.get('outcome'))
                                for item in report['runs'] if isinstance(item.get('replay'), dict)}
    if replay_patch:
        replay_patch(root, report)
    if receipt_patch:
        receipt_patch(report)
    text = iso.bounded_receipt_text(report).encode('ascii')
    (root / 'isolation-receipt.json').write_bytes(text)
    receipt_path = root / 'isolation-receipt.json'
    passed = report['gate']['passed'] is True
    summary = {'schema': 'cochem-agy-isolation-evidence-result/1', 'mode': 'evidence', 'status': report['status'],
               'decision': 'COMPLETE', 'attempt': ATTEMPT, 'slot': 'slot1', 'nonce': NONCE, 'target_root': str(root),
               'receipt_path': str(receipt_path), 'receipt_sha256': sha(text), 'gemini_gate': 'G3',
               'gemini_outcome': 'PASSED' if passed else 'HELD', 'exit_code': 0 if passed else 10,
               'capability_reference': f'{receipt_path}#{sha(text)}' if passed else None,
               'gate': {'passed': report['gate']['passed'], 'reasons': report['gate']['reasons']}, 'isolation_stop': False,
               'precheck': {'passed': report['precheck']['passed'], 'reasons': report['precheck']['reasons']},
               'isolation_verdict': report['isolation_verdict'], 'replay_root': str(replay), 'replay_streams': report['replay_streams'],
               'model_jobs_executed': report['model_jobs_executed'], 'answers_produced': report['answers_produced'],
               'raw_output_publication': 'never', 'message': 'Isolation evidence verified (G3 passed).'}
    if summary_patch:
        summary_patch(summary)
    ps_json(root / 'isolation-summary.json', summary)
    for name in extra_files:
        ps_json(root / name, {'schema': 'cochem-agy-isolation-evidence-held/1'})
    return root


def make_stage(base, *, slot_patch=None, receipt_patch=None, summary_patch=None, extra_files=()):
    root = base / f'AgyIsolation4.2.7-windows-20261011-r4-v1-{ATTEMPT}-stage'
    raw = root / 'raw'
    raw.mkdir(parents=True)
    report = iso.new_stage_report(NONCE, ATTEMPT, sha(ISO_PATH.read_bytes()), 'S-1-5-18')
    report.update(production_arguments_validated=True, runtime_custody_verified=True, require_stopped_before=True,
                  require_stopped_after=True, daemon_states_verified_before_and_after=True, native_executable_sha256_before=AGY,
                  native_executable_sha256_after=AGY, layout_sha256=iso.LAYOUT_SHA256, config_sha256=PIN)
    report['profiles'] = [{'slot': slot, 'identity': f'CoChem422Worker{n}', 'profile_present': True, 'paths': [],
                           'flags': dict(CLEAN_PROFILE_FLAGS)} for n, slot in enumerate(SLOTS, 1)]
    report['isolation_inventory_clear'] = True
    for n, slot in enumerate(SLOTS, 1):
        identity = f'CoChem422Worker{n}'
        entry = {'slot': slot, 'identity': identity, 'profile_root': f'C:\\Users\\{identity}',
                 'slot_root': f'C:\\ProgramData\\CoChemPipeline427\\workers\\{slot}', 'ram_workspace_root': f'R:\\CoChem427-windows-20261007\\{slot}',
                 'staged': staged_records(identity, slot == 'slot1'), 'shadow_locations_checked': [], 'shadows_found': [],
                 'staging_changes': None, 'probes': [], 'agent_sha256_after_listing': [AGENT_SHA] * 2, 'listing': None}
        listing = {'PC3': AGENTS_OK, 'PC4': b'cochem-inference-only\n'}
        if slot_patch:
            slot_patch(slot, entry, listing)
        for probe_id, arguments, kind in iso.STAGE_PROBES:
            entry['probes'].append(probe_record(raw, probe_id, arguments, kind, listing[probe_id], prefix=slot + '-'))
        reasons = iso.listing_reasons(entry['probes'])
        entry['listing'] = {'passed': not reasons, 'reasons': reasons}
        report['slots'].append(entry)
    report['cleanup_verified'] = True
    report['status'] = 'STAGING_COMPLETE'
    report['gate'] = iso.staging_gate(report['status'], report['slots'])
    if receipt_patch:
        receipt_patch(report)
    text = iso.bounded_receipt_text(report).encode('ascii')
    (root / 'stage-receipt.json').write_bytes(text)
    passed = report['gate']['passed'] is True
    summary = {'schema': 'cochem-agy-agent-staging-result/1', 'mode': 'stage', 'status': report['status'], 'decision': 'COMPLETE',
               'attempt': ATTEMPT, 'nonce': NONCE, 'target_root': str(root), 'receipt_path': str(root / 'stage-receipt.json'),
               'receipt_sha256': sha(text), 'gemini_gate': 'G4', 'gemini_outcome': 'PASSED' if passed else 'HELD',
               'exit_code': 0 if passed else 10, 'gate': {'passed': report['gate']['passed'], 'reasons': report['gate']['reasons']},
               'isolation_inventory_clear': True, 'model_jobs_executed': 0, 'message': 'Agent staging verified (G4 passed).'}
    if summary_patch:
        summary_patch(summary)
    ps_json(root / 'stage-summary.json', summary)
    for name in extra_files:
        ps_json(root / name, {'schema': 'cochem-agy-isolation-evidence-held/1'})
    return root


class World:
    def __init__(self, base, commissioned_bytes, *, login=None, capture=None, isolation=None, stage=None, commissioned=None):
        self.base = base
        base.mkdir(parents=True, exist_ok=True)
        (base / 'commissioned').mkdir()
        self.commissioned = base / 'commissioned' / 'pipeline.json'
        self.commissioned_bytes = commissioned if commissioned is not None else commissioned_bytes
        self.commissioned.write_bytes(self.commissioned_bytes)
        evidence = base / 'evidence'
        evidence.mkdir()
        self.login = make_login(evidence, **(login or {}))
        self.capture = make_capture(evidence, **(capture or {}))
        self.isolation = make_isolation(evidence, **(isolation or {}))
        self.stage = make_stage(evidence, **(stage or {}))

    def argv(self, out, mode='attempt', roots=True, extra=()):
        argv = ['--commissioned', str(self.commissioned), '--mode', mode, '--out-dir', str(out)]
        if roots:
            argv += ['--login-root', str(self.login), '--capture-root', str(self.capture), '--isolation-root', str(self.isolation)]
        return argv + list(extra)

    @property
    def capability_reference(self):
        receipt = self.isolation / 'isolation-receipt.json'
        return f'{receipt}#{sha(receipt.read_bytes())}'


class Outcome:
    def __init__(self, code, out):
        self.code, self.out = code, out

    @property
    def decision_bytes(self):
        return (self.out / 'decision.json').read_bytes()

    @property
    def decision(self):
        return json.loads(self.decision_bytes)

    @property
    def candidate(self):
        return (self.out / 'pipeline.json').read_bytes()


def no_processes(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('the builder must not start a process')
    monkeypatch.setattr(subprocess, 'Popen', refuse)
    monkeypatch.setattr(os, 'system', refuse)


def trust_fixture_roots(monkeypatch, calls=None):
    """The fixture roots live in tmp_path, not under C:\\Program Files\\CoChem: the custody check is replaced (recorded)."""
    def custody(root):
        if calls is not None:
            calls.append(root)
    monkeypatch.setattr(b, 'check_root_custody', custody)


def run_in_process(monkeypatch, world, out_name='out', **kwargs):
    out = world.base / out_name
    no_processes(monkeypatch)
    trust_fixture_roots(monkeypatch)
    code = b.main(world.argv(out, **kwargs))
    monkeypatch.undo()
    return Outcome(code, out)


def run_cli(argv, cwd):
    result = subprocess.run([str(PY), '-I', str(BUILDER_PATH), *argv], cwd=str(cwd), capture_output=True, timeout=180)
    return result


# The builder's own main() in a fresh isolated r5-stand-in interpreter, with only check_root_custody replaced (the
# fixture roots are temporary directories); everything else is the CLI path.
CUSTODY_STUB_DRIVER = ('import importlib.util, sys\n'
                       "spec = importlib.util.spec_from_file_location('build_pipeline_config_r5_candidate', sys.argv[1])\n"
                       'module = importlib.util.module_from_spec(spec)\n'
                       'spec.loader.exec_module(module)\n'
                       'module.check_root_custody = lambda root: None\n'
                       'raise SystemExit(module.main(sys.argv[2:]))\n')


def run_cli_trusting_fixture_roots(argv, cwd):
    return subprocess.run([str(PY), '-I', '-c', CUSTODY_STUB_DRIVER, str(BUILDER_PATH), *argv], cwd=str(cwd),
                          capture_output=True, timeout=180)


@pytest.fixture
def world(tmp_path, commissioned_bytes):
    return World(tmp_path / 'world', commissioned_bytes)


def gemini_suffix(commissioned):
    return commissioned[commissioned.index(b'\r\n  },\r\n  "timeout_seconds"'):]


def gemini_prefix(commissioned):
    return commissioned[:commissioned.index(b'"gemini": {') + len(b'"gemini": ')]


def assert_stager_invariants(outcome, commissioned, pin=PIN):
    raw = outcome.decision_bytes
    assert raw.isascii() and not raw.startswith(b'\xef\xbb\xbf') and raw.endswith(b'\n')
    decision = json.loads(raw)
    assert raw == (json.dumps(decision, ensure_ascii=True, sort_keys=True, indent=2) + '\n').encode('ascii'), 'deterministic sorted serialization'
    candidate = outcome.candidate
    required = {'schema', 'mode', 'outcome', 'gates', 'chosen_bindings', 'effort_contracts', 'error', 'candidate_file',
                'candidate_sha256', 'candidate_length', 'commissioned_path', 'commissioned_sha256', 'evidence', 'builder'}
    assert required <= set(decision)
    assert decision['schema'] == 'cochem-r5-config-decision/1' and decision['mode'] in ('attempt', 'held')
    assert decision['outcome'] in ('GEMINI_CONTRACT', 'GEMINI_HELD_COMMISSIONED_BYTES')
    assert sorted(decision['gates']) == GATES
    for gate in decision['gates'].values():
        assert set(gate) == {'pass', 'reason'} and type(gate['pass']) is bool and isinstance(gate['reason'], str) and gate['reason']
    assert decision['candidate_file'] == 'pipeline.json'
    assert decision['candidate_sha256'] == sha(candidate) and decision['candidate_length'] == len(candidate)
    assert decision['commissioned_sha256'] == sha(commissioned) == pin
    assert set(decision['builder']) >= {'script_sha256', 'python', 'cochem_pipeline_file', 'cochem_pipeline_version_or_sha'}
    assert decision['builder']['script_sha256'] == sha(BUILDER_PATH.read_bytes())
    assert isinstance(decision['evidence'], dict)
    for entry in decision['evidence'].values():
        assert sha(Path(entry['path']).read_bytes()) == entry['sha256']
    binding = decision['evidence_binding']
    assert binding is None or (set(binding) == {'passed', 'attempt', 'reasons', 'roots', 'records'} and binding['passed'] is (not binding['reasons']))
    if binding is not None and binding['passed'] is False:
        assert decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES'
        for gate in decision['gates'].values():
            assert gate['reason'].startswith('not evaluated: the evidence binding refused the roots (')
    if decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES':
        assert candidate == commissioned and decision['candidate_sha256'] == decision['commissioned_sha256'] == pin
        assert decision['chosen_bindings'] is None and decision['effort_contracts'] is None
    else:
        assert decision['mode'] == 'attempt' and decision['error'] is None
        assert binding['passed'] is True and binding['attempt'] == ATTEMPT
        assert all(gate['pass'] is True for gate in decision['gates'].values())
        assert isinstance(decision['chosen_bindings'], dict) and decision['chosen_bindings']
        assert candidate != commissioned and decision['candidate_sha256'] != pin
        old, new = json.loads(commissioned), json.loads(candidate)
        assert old['providers'].pop('gemini') != new['providers'].pop('gemini')
        assert old == new
    return decision


def gates_passed(decision):
    return {name: gate['pass'] for name, gate in decision['gates'].items()}


# ---------------------------------------------------------------- source, pins and the stand-in interpreter

def test_builder_and_harness_are_ascii_and_the_builder_compiles():
    for path in (BUILDER_PATH, Path(__file__)):
        assert path.read_bytes().isascii(), path
    compile(BUILDER_PATH.read_text(encoding='ascii'), str(BUILDER_PATH), 'exec')
    text = BUILDER_PATH.read_text(encoding='ascii')
    assert 'TEST-ONLY OVERRIDE' in text and 'import subprocess' not in text and 'os.system' not in text
    assert 'tempfile' not in text and not hasattr(b, 'tempfile'), 'B-F6: the G6 copy never goes to %TEMP%'
    assert b.COMMISSIONED_SHA256 == PIN and b.AGY_SHA256 == AGY and b.AGENT_SHA256 == AGENT_SHA
    assert list(b.ARGUMENTS) == ARGS == list(iso.PRODUCTION_ARGUMENTS)


def test_embedded_pins_match_the_files_on_disk_read_only(commissioned_bytes):
    assert sha(commissioned_bytes) == b.COMMISSIONED_SHA256
    agent = W / 'cochem-inference-only.agent.md'
    assert sha(agent.read_bytes()) == b.AGENT_SHA256 == iso.AGENT_SHA256
    assert b.AGY_SHA256 == iso.AGY_SHA256 == cap.AGY_SHA256 and b.AGY_VERSION == iso.AGY_VERSION
    held = json.loads(commissioned_bytes)['providers']['gemini']['integration_hold']
    assert held['executable_sha256'] == b.AGY_SHA256 and held['version'] == b.AGY_VERSION


def test_repo_venv_isolated_mode_imports_the_working_tree_r5_package(tmp_path):
    code = ('import json, cochem_pipeline, cochem_pipeline.agy_protocol as a, cochem_pipeline.config as c;'
            'print(json.dumps([cochem_pipeline.__file__, a.IDENTITY_POLICY, hasattr(c, "validate_gemini_route_bindings")]))')
    result = subprocess.run([str(PY), '-I', '-c', code], cwd=str(tmp_path), capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr
    location, policy, has_route_check = json.loads(result.stdout)
    assert Path(location).parent == REPO / 'src' / 'cochem_pipeline' and policy == 'reported-model-equality' and has_route_check


# ---------------------------------------------------------------- held mode

def test_held_mode_writes_the_commissioned_bytes_and_reads_no_evidence(tmp_path, commissioned_bytes, monkeypatch):
    world = World(tmp_path / 'world', commissioned_bytes)
    (world.isolation / 'isolation-receipt.json').write_bytes(b'{"broken": ')
    outcome = run_in_process(monkeypatch, world, mode='held')
    assert outcome.code == 0 and outcome.candidate == commissioned_bytes
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert decision['mode'] == 'held' and decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES' and decision['error'] is None
    assert decision['evidence'] == {} and decision['inputs']['evidence_read'] is False
    for gate in decision['gates'].values():
        assert gate == {'pass': False, 'reason': 'not evaluated: held mode requested'}
    assert sorted(path.name for path in outcome.out.iterdir()) == ['decision.json', 'pipeline.json']


def test_held_mode_cli_needs_only_commissioned_and_out_dir(tmp_path, commissioned_bytes):
    source = tmp_path / 'pipeline.json'
    source.write_bytes(commissioned_bytes)
    out = tmp_path / 'held-out'
    result = run_cli(['--commissioned', str(source), '--mode', 'held', '--out-dir', str(out)], tmp_path)
    assert result.returncode == 0, result.stderr
    line = json.loads(result.stdout)
    assert line['status'] == 'DECISION_WRITTEN' and line['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES' and line['candidate_sha256'] == PIN
    outcome = Outcome(0, out)
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert decision['builder']['isolated_mode'] is True and decision['builder']['python'].lower() == str(PY).lower()
    assert decision['inputs'] == {'login_root': None, 'capture_root': None, 'isolation_root': None, 'stage_root': None, 'evidence_read': False}


# ---------------------------------------------------------------- attempt mode, all gates green

def test_attempt_all_green_is_the_exact_gemini_contract(world, commissioned_bytes, monkeypatch):
    outcome = run_in_process(monkeypatch, world)
    assert outcome.code == 0
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert decision['outcome'] == 'GEMINI_CONTRACT' and gates_passed(decision) == {gate: True for gate in GATES}, decision['gates']
    reference = world.capability_reference
    contract = {'arguments': ['--effort', 'high'], 'version_arguments': ['--version'], 'executable_sha256': AGY, 'version': '1.3.1',
                'capability_reference': reference, 'native_metadata': None, 'thinking_enabled': None}
    expected = {
        'executable': EXECUTABLE, 'model': 'gemini-3.1-pro-preview', 'arguments': ARGS, 'protocol': 'agy-stream-json',
        'identity_policy': 'reported-model-equality',
        'subscription_probe': {'arguments': ['--output-format', 'json', 'models'], 'protocol': 'json-fields',
                               'expected': {'status': 'SUCCESS', 'command.name': 'models'}},
        'inference_only': {'arguments': ARGS, 'version_arguments': ['--version'], 'executable_sha256': AGY, 'version': '1.3.1',
                           'capability_reference': reference, 'disables_tools': True, 'disables_mcp': True, 'disables_hooks': True,
                           'disables_subagents': True, 'disables_model_fallback': True},
        'model_bindings': {'gemini-3.8-flash': 'gemini-3.8-flash-low',
                           'gemini-3.8-flash:extended': {'argv': 'gemini-3.8-flash', 'reports': 'gemini-3.8-flash-high'}},
        'effort_contracts': {'gemini-3.8-flash:extended': contract}}
    gemini = json.loads(outcome.candidate)['providers']['gemini']
    assert gemini == expected and list(gemini) == list(expected), 'exact values and the commissioned key order'
    assert 'integration_hold' not in gemini
    assert decision['chosen_bindings'] == expected['model_bindings'] and decision['effort_contracts'] == expected['effort_contracts']
    assert 'gemini-3.1-pro-preview:high' not in decision['chosen_bindings']
    assert decision['binding_selection']['gemini-3.1-pro-preview:high']['rule'] == 'UNBOUND_IN_R5_NO_PRO_EVIDENCE'
    assert decision['binding_selection']['gemini-3.8-flash']['rule'] == 'R5_OWNER_EFFORT_NULL_SLUG_PASSED'
    assert decision['binding_selection']['gemini-3.8-flash:extended']['rule'] == 'R3_FAMILY_WITH_EFFORT_HIGH_ECHO_PASSED'
    assert {item['path']: item['change'] for item in decision['changed_paths']} == {
        'providers.gemini.arguments': 'changed', 'providers.gemini.protocol': 'changed', 'providers.gemini.identity_policy': 'added',
        'providers.gemini.subscription_probe': 'changed', 'providers.gemini.inference_only': 'changed',
        'providers.gemini.model_bindings': 'added', 'providers.gemini.effort_contracts.gemini-3.8-flash:extended': 'added',
        'providers.gemini.integration_hold': 'removed'}
    assert sorted(decision['evidence']) == sorted([
        'login.series_complete', 'capture.receipt', 'capture.summary', 'capture.raw.P2.stdout', 'isolation.receipt',
        'isolation.summary', 'stage.receipt', 'stage.summary', 'isolation.replay.R1.stdout', 'isolation.replay.R1.stderr',
        'isolation.replay.R5.stdout', 'isolation.replay.R5.stderr', 'isolation.replay.R3.stdout', 'isolation.replay.R3.stderr'])
    assert EMAIL not in outcome.decision_bytes.decode('ascii') and 'REDACTED' not in outcome.decision_bytes.decode('ascii')
    assert decision['inputs']['stage_root'] == str(world.stage)
    binding = decision['evidence_binding']
    assert binding['passed'] is True and binding['attempt'] == ATTEMPT and binding['reasons'] == []
    assert binding['roots'] == {'login': {'path': str(world.login), 'namespace_attempt': ATTEMPT, 'custody': 'protected'},
                                'capture': {'path': str(world.capture), 'namespace_attempt': ATTEMPT, 'custody': 'protected'},
                                'isolation': {'path': str(world.isolation), 'namespace_attempt': ATTEMPT, 'custody': 'protected'},
                                'stage': {'path': str(world.stage), 'namespace_attempt': ATTEMPT, 'custody': 'protected'}}
    assert binding['records'] == {key: {'attempt': ATTEMPT, 'nonce': NONCE} for key in ATTEMPT_RECORD_KEYS}
    assert 'R3->gemini-3.8-flash:gemini-3.8-flash-high' in decision['gates']['G5']['reason']
    assert ('bound slugs gemini-3.8-flash-high, gemini-3.8-flash-low are in the signed-in catalog of 13 ids (R3 family argv'
            in decision['gates']['G2']['reason'])


def test_candidate_preserves_every_byte_outside_providers_gemini(world, commissioned_bytes, monkeypatch):
    candidate = run_in_process(monkeypatch, world).candidate
    prefix, suffix = gemini_prefix(commissioned_bytes), gemini_suffix(commissioned_bytes)
    assert candidate.startswith(prefix) and candidate.endswith(suffix)
    block = candidate[len(prefix):len(candidate) - len(suffix)]
    assert block.isascii() and block.count(b'\n') == block.count(b'\r\n'), 'the new block uses the CRLF convention'
    lines = block.split(b'\r\n')
    assert lines[0] == b'{' and lines[-1] == b'    }' and all(line.startswith(b'      ') for line in lines[1:-1])
    # retarget-warden-r5 Assert-R5Config: remove providers.gemini from both and compare compact JSON in document order.
    old, new = json.loads(commissioned_bytes), json.loads(candidate)
    old_gemini, new_gemini = old['providers'].pop('gemini'), new['providers'].pop('gemini')
    assert json.dumps(old, separators=(',', ':')) == json.dumps(new, separators=(',', ':'))
    assert json.dumps(old_gemini, separators=(',', ':')) != json.dumps(new_gemini, separators=(',', ':'))
    pairs = lambda data: json.loads(data, object_pairs_hook=list)  # noqa: E731 - order-preserving view
    old_pairs, new_pairs = pairs(commissioned_bytes), pairs(candidate)
    assert [key for key, _ in old_pairs] == [key for key, _ in new_pairs]
    assert [item for item in old_pairs if item[0] != 'providers'] == [item for item in new_pairs if item[0] != 'providers']
    tiers = lambda doc: dict(dict(doc)['routing'])['tiers']  # noqa: E731
    assert tiers(old_pairs) == tiers(new_pairs)
    # The r5 parser check retarget-warden-r5 runs (Invoke-R5ConfigParser), here in-process with the repo r5 package.
    from cochem_pipeline.config import load_config, validate_gemini_route_bindings
    path = world.base / 'candidate-check.json'
    path.write_bytes(candidate)
    loaded = load_config(str(path))
    assert len(loaded.workers) == 6 and loaded.max_execution_slots == 4 and loaded.knowledge.enabled
    assert validate_gemini_route_bindings(loaded.providers['gemini'], loaded.routing) == {
        'gemini-3.8-flash': {'argv': 'gemini-3.8-flash-low', 'reports': 'gemini-3.8-flash-low'},
        'gemini-3.8-flash:extended': {'argv': 'gemini-3.8-flash', 'reports': 'gemini-3.8-flash-high'}}


def test_replay_routes_through_the_r5_worker_identity(world, monkeypatch):
    from cochem_pipeline import worker
    calls = []
    real = worker.parse_gemini

    def spy(raw, protocol, requested_model, **kwargs):
        result = real(raw, protocol, requested_model, **kwargs)
        calls.append((requested_model, kwargs['native'], result['reported_model'], result['native_reported_model']))
        return result
    monkeypatch.setattr(worker, 'parse_gemini', spy)
    outcome = run_in_process(monkeypatch, world)
    assert outcome.decision['outcome'] == 'GEMINI_CONTRACT'
    assert calls == [
        ('gemini-3.8-flash', {'argv': 'gemini-3.8-flash-high', 'reports': 'gemini-3.8-flash-high'}, 'gemini-3.8-flash', 'gemini-3.8-flash-high'),
        ('gemini-3.8-flash', {'argv': 'gemini-3.8-flash-low', 'reports': 'gemini-3.8-flash-low'}, 'gemini-3.8-flash', 'gemini-3.8-flash-low'),
        ('gemini-3.8-flash', {'argv': 'gemini-3.8-flash', 'reports': 'gemini-3.8-flash-high'}, 'gemini-3.8-flash', 'gemini-3.8-flash-high')]


# ---------------------------------------------------------------- determinism

def test_decision_is_deterministic_in_process_and_through_the_cli(world, commissioned_bytes, monkeypatch, tmp_path):
    first = run_in_process(monkeypatch, world, out_name='one')
    second = run_in_process(monkeypatch, world, out_name='two')
    assert first.code == second.code == 0
    assert first.decision_bytes == second.decision_bytes and first.candidate == second.candidate
    cli = [run_cli_trusting_fixture_roots(world.argv(world.base / name), tmp_path) for name in ('cli-one', 'cli-two')]
    assert all(result.returncode == 0 for result in cli), [result.stderr for result in cli]
    outcomes = [Outcome(0, world.base / name) for name in ('cli-one', 'cli-two')]
    assert outcomes[0].decision_bytes == outcomes[1].decision_bytes and outcomes[0].candidate == outcomes[1].candidate
    assert outcomes[0].candidate == first.candidate, 'the CLI under -I builds the same candidate bytes'
    cli_decision, in_process = outcomes[0].decision, first.decision
    cli_decision.pop('builder'), in_process.pop('builder')
    assert cli_decision == in_process
    assert_stager_invariants(outcomes[0], commissioned_bytes)


# ---------------------------------------------------------------- every gate failing alone

def drop_catalog_slug(slug):
    return {'catalog': tuple(item for item in CATALOG if item != slug)}


def replay_stderr_marker(root, report):
    path = root / 'replay' / 'R1.stderr'
    data = path.read_bytes() + b'Model resolved via account default\n'
    path.write_bytes(data)
    report['replay_streams']['R1']['stderr'].update(bytes=len(data), sha256=sha(data))


def replay_identity_mismatch(root, report):
    path = root / 'replay' / 'R5.stdout'
    data = path.read_bytes().replace(b'"model":"gemini-3.8-flash-low"', b'"model":"gemini-3.8-flash-medium"')
    path.write_bytes(data)
    report['replay_streams']['R5']['stdout'].update(bytes=len(data), sha256=sha(data))


def slot4_listing_empty(slot, entry, listing):
    if slot == 'slot4':
        listing['PC3'] = AGENTS_NONE


def slot6_held(rows):
    rows[5].update(final_decision='HOLD', reuse_verified=False, after={'decision': 'HOLD', 'stage': 'after'})


ALONE = {
    'G1-slot6-not-reused': ('G1', {'login': {'rows_patch': slot6_held}}),
    'G2-owner-slug-not-in-catalog': ('G2', {'capture': drop_catalog_slug('gemini-3.8-flash-low')}),
    'G2-envelope-error': ('G2', {'capture': {'p2_status': 'ERROR'}}),
    'G3-hooks-in-a-profile': ('G3', {'isolation': {'profile_flags': {'slot3': {'hooks_present': True}}}}),
    'G3-environment-flagged': ('G3', {'isolation': {'receipt_patch': lambda report: report['environment_attestation'].update(
        flagged_names=['AGY_CLI_MODEL'], flagged_names_absent=False)}}),
    'G4-slot4-listing-empty': ('G4', {'stage': {'slot_patch': slot4_listing_empty}}),
    'G5-replay-stderr-marker': ('G5', {'isolation': {'replay_patch': replay_stderr_marker}}),
    'G5-replay-identity-mismatch': ('G5', {'isolation': {'replay_patch': replay_identity_mismatch}}),
}


@pytest.mark.parametrize('variant', sorted(ALONE))
def test_each_gate_failing_alone_degrades_to_the_commissioned_bytes(variant, tmp_path, commissioned_bytes, monkeypatch):
    gate, options = ALONE[variant]
    world = World(tmp_path / 'world', commissioned_bytes, **options)
    outcome = run_in_process(monkeypatch, world)
    assert outcome.code == 0 and outcome.candidate == commissioned_bytes
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES' and decision['error'] is None
    assert gates_passed(decision) == {name: name != gate for name in GATES}, decision['gates']
    assert not decision['gates'][gate]['reason'].startswith('not evaluated'), decision['gates'][gate]
    assert decision['proposed'] is not None and decision['proposed']['candidate_sha256'] != PIN, 'the evaluated candidate is still recorded'


def test_g6_fails_alone_when_the_r5_load_config_rejects_the_candidate(world, commissioned_bytes, monkeypatch):
    from cochem_pipeline import config

    def reject(filename):
        raise ValueError('rejected by the r5 parser')
    monkeypatch.setattr(config, 'load_config', reject)
    outcome = run_in_process(monkeypatch, world)
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert outcome.code == 0 and decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES' and decision['error'] is None
    assert gates_passed(decision) == {name: name != 'G6' for name in GATES}
    assert 'rejected by the r5 parser' in decision['gates']['G6']['reason']


def test_g6_requires_four_shared_slots_from_the_r5_parser(tmp_path, commissioned_bytes, monkeypatch):
    changed = commissioned_bytes.replace(b'"max_execution_slots": 4', b'"max_execution_slots": 3')
    assert changed != commissioned_bytes
    monkeypatch.setattr(b, 'COMMISSIONED_SHA256', sha(changed))
    world = World(tmp_path / 'world', commissioned_bytes, commissioned=changed)
    out = world.base / 'out'
    no_processes(monkeypatch)
    trust_fixture_roots(monkeypatch)
    code = b.main(world.argv(out))
    outcome = Outcome(code, out)
    decision = assert_stager_invariants(outcome, changed, pin=sha(changed))
    assert code == 0 and outcome.candidate == changed and decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES'
    assert gates_passed(decision) == {name: name != 'G6' for name in GATES}
    assert '3 shared slots, not 4' in decision['gates']['G6']['reason']


def test_g6_rejects_a_candidate_that_changes_bytes_outside_providers_gemini(world, commissioned_bytes, monkeypatch):
    real = b.render_candidate

    def widen(commissioned, gemini):
        return real(commissioned, gemini).replace(b'"lease_seconds": 1800', b'"lease_seconds": 1700')
    monkeypatch.setattr(b, 'render_candidate', widen)
    outcome = run_in_process(monkeypatch, world)
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES' and outcome.candidate == commissioned_bytes
    assert gates_passed(decision) == {name: name != 'G6' for name in GATES}
    reason = decision['gates']['G6']['reason']
    assert 'bytes outside the providers.gemini value differ' in reason and 'top-level lease_seconds changed' in reason
    assert 'retarget view' in reason


# ---------------------------------------------------------------- missing, corrupt or unparseable evidence

def remove(path):
    def apply(world):
        target = getattr(world, path[0]) / path[1] if path[1] else getattr(world, path[0])
        if target.is_dir():
            for child in sorted(target.rglob('*'), key=lambda item: len(item.parts), reverse=True):
                child.rmdir() if child.is_dir() else child.unlink()
            target.rmdir()
        else:
            target.unlink()
    return apply


def overwrite(attribute, name, data):
    def apply(world):
        (getattr(world, attribute) / name).write_bytes(data)
    return apply


def add_file(attribute, name):
    def apply(world):
        (getattr(world, attribute) / name).write_bytes(b'{"schema": "held"}')
    return apply


def duplicate_member(world):
    path = world.isolation / 'isolation-receipt.json'
    text = path.read_bytes()
    path.write_bytes(text.replace(b'{\n  "agent"', b'{\n  "status": "EVIDENCE_COMPLETE",\n  "agent"', 1))


def nan_constant(world):
    path = world.isolation / 'isolation-receipt.json'
    path.write_bytes(path.read_bytes().replace(b'"answers_produced": 3', b'"answers_produced": NaN', 1))


def wrong_capability_reference(world):
    path = world.isolation / 'isolation-summary.json'
    summary = json.loads(path.read_bytes())
    summary['capability_reference'] = summary['capability_reference'][:-64] + '0' * 64
    path.write_bytes(json.dumps(summary, indent=4).encode())


CORRUPT = {
    'login-root-missing': (remove(('login', None)), {'G1'}),
    'login-held-record-present': (add_file('login', 'series-held.json'), {'G1'}),
    'login-not-json': (overwrite('login', 'series-complete.json', b'\xff\xfe not json'), {'G1'}),
    'capture-receipt-truncated': (overwrite('capture', 'capture-receipt.json', b'{"schema": "cochem-agy-status-capture/1"'), {'G2'}),
    'capture-raw-p2-tampered': (overwrite('capture', 'raw/P2.stdout', models_envelope()[:-1] + b' }'), {'G2'}),
    'capture-held-record-present': (add_file('capture', 'capture-held.json'), {'G2'}),
    'isolation-receipt-duplicate-member': (duplicate_member, {'G2', 'G3', 'G5', 'G6'}),
    'isolation-receipt-nan': (nan_constant, {'G2', 'G3', 'G5', 'G6'}),
    'isolation-root-missing': (remove(('isolation', None)), {'G2', 'G3', 'G5', 'G6'}),
    'isolation-replay-missing': (remove(('isolation', 'replay/R5.stdout')), {'G5'}),
    'isolation-summary-wrong-reference': (wrong_capability_reference, {'G3'}),
    'isolation-held-record-present': (add_file('isolation', 'isolation-held.json'), {'G3'}),
    'stage-summary-missing': (remove(('stage', 'stage-summary.json')), {'G4'}),
    'stage-root-missing': (remove(('stage', None)), {'G4'}),
}


@pytest.mark.parametrize('variant', sorted(CORRUPT))
def test_missing_corrupt_or_unparseable_evidence_degrades_to_held(variant, world, commissioned_bytes, monkeypatch):
    mutate, failing = CORRUPT[variant]
    mutate(world)
    outcome = run_in_process(monkeypatch, world)
    assert outcome.code == 0 and outcome.candidate == commissioned_bytes
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES' and decision['error'] is None
    assert {name for name, passed in gates_passed(decision).items() if not passed} == failing, decision['gates']
    if failing == {'G2', 'G3', 'G5', 'G6'}:
        assert decision['gates']['G5']['reason'].startswith('not evaluated: the isolation evidence is unavailable')
        assert 'bound slugs not evaluated' in decision['gates']['G2']['reason']


# ---------------------------------------------------------------- builder exceptions

def test_an_exception_after_the_gates_is_recorded_held_and_exit_zero(world, commissioned_bytes, monkeypatch):
    def explode(commissioned, gemini):
        raise RuntimeError('renderer exploded')
    monkeypatch.setattr(b, 'render_candidate', explode)
    outcome = run_in_process(monkeypatch, world)
    assert outcome.code == 0 and outcome.candidate == commissioned_bytes
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert decision['error'] == 'RuntimeError: renderer exploded' and decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES'
    assert gates_passed(decision) == {'G1': True, 'G2': True, 'G3': True, 'G4': True, 'G5': True, 'G6': False}
    assert decision['gates']['G6']['reason'] == 'not evaluated: builder error before this gate (RuntimeError: renderer exploded)'


def test_an_exception_inside_a_gate_is_a_builder_error_not_a_gate_result(world, commissioned_bytes, monkeypatch):
    def explode(root, evidence):
        raise RuntimeError('login gate exploded')
    monkeypatch.setattr(b, 'gate_login', explode)
    outcome = run_in_process(monkeypatch, world)
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert outcome.code == 0 and decision['error'] == 'RuntimeError: login gate exploded'
    for gate in decision['gates'].values():
        assert gate == {'pass': False, 'reason': 'not evaluated: builder error before this gate (RuntimeError: login gate exploded)'}


def test_a_missing_r5_package_is_a_builder_error(world, commissioned_bytes, monkeypatch):
    def unavailable():
        raise ImportError('no r5 cochem_pipeline')
    monkeypatch.setattr(b, 'load_pipeline', unavailable)
    outcome = run_in_process(monkeypatch, world)
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert outcome.code == 0 and decision['error'] == 'ImportError: no r5 cochem_pipeline' and decision['evidence'] == {}
    assert all(gate['pass'] is False for gate in decision['gates'].values())


def test_an_unserializable_decision_still_writes_the_held_output(world, commissioned_bytes, monkeypatch):
    real = b.decide

    def broken(args, commissioned):
        decision, payload = real(args, commissioned)
        decision['proposed'] = {'bad': object()}
        return decision, payload
    monkeypatch.setattr(b, 'decide', broken)
    outcome = run_in_process(monkeypatch, world)
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert outcome.code == 0 and decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES'
    assert decision['error'].startswith('TypeError: Object of type object is not JSON serializable')


def test_a_write_failure_exits_five_and_leaves_no_commit_marker(world, monkeypatch):
    real = b.write_new

    def failing(path, data):
        if path.endswith('decision.json'):
            raise OSError('disk full')
        real(path, data)
    monkeypatch.setattr(b, 'write_new', failing)
    outcome = run_in_process(monkeypatch, world)
    assert outcome.code == 5 and (outcome.out / 'pipeline.json').exists() and not (outcome.out / 'decision.json').exists()


# ---------------------------------------------------------------- binding-selection rules

def contract_for(world, monkeypatch, **options):
    outcome = run_in_process(monkeypatch, World(world, COMMISSIONED.read_bytes(), **options))
    return outcome, outcome.decision


def test_rule_r5_failure_falls_back_to_the_r1_slug(tmp_path, commissioned_bytes, monkeypatch):
    mismatch = {'R5': (stream('gemini-3.8-flash-high', 'conv-r5'), b'', 0)}
    outcome, decision = contract_for(tmp_path / 'w', monkeypatch, isolation={'runs': mismatch})
    assert decision['outcome'] == 'GEMINI_CONTRACT', decision['gates']
    assert decision['chosen_bindings']['gemini-3.8-flash'] == 'gemini-3.8-flash-high'
    assert decision['binding_selection']['gemini-3.8-flash'] == {'rule': 'R1_PRIMARY_SLUG', 'run': 'R1',
                                                                'argv': 'gemini-3.8-flash-high', 'reports': 'gemini-3.8-flash-high'}
    assert 'R1->gemini-3.8-flash:gemini-3.8-flash-high' in decision['gates']['G5']['reason']


def test_rule_r5_rejected_by_the_cli_falls_back_to_the_r1_slug(tmp_path, commissioned_bytes, monkeypatch):
    rejected = {'R5': (b'', b'Error: unknown model "gemini-3.8-flash-low"\n', 1)}
    outcome, decision = contract_for(tmp_path / 'w', monkeypatch, isolation={'runs': rejected})
    assert decision['outcome'] == 'GEMINI_CONTRACT' and decision['chosen_bindings']['gemini-3.8-flash'] == 'gemini-3.8-flash-high'


@pytest.mark.parametrize('slug', ['gemini-3.8-flash-medium', 'gemini-3.8-flash-high'])
def test_rule_the_owner_declared_slug_binds_when_r5_passes(slug, tmp_path, commissioned_bytes, monkeypatch):
    outcome, decision = contract_for(tmp_path / 'w', monkeypatch, isolation={'slug': slug})
    assert decision['outcome'] == 'GEMINI_CONTRACT', decision['gates']
    assert decision['chosen_bindings']['gemini-3.8-flash'] == slug
    assert decision['binding_selection']['gemini-3.8-flash']['rule'] == 'R5_OWNER_EFFORT_NULL_SLUG_PASSED'


def test_rule_r2_wins_over_r3_when_both_pass(tmp_path, commissioned_bytes, monkeypatch):
    both = {'R2': (stream('gemini-3.8-flash-high', 'conv-r2'), b'', 0)}
    outcome, decision = contract_for(tmp_path / 'w', monkeypatch, isolation={'runs': both})
    assert decision['outcome'] == 'GEMINI_CONTRACT', decision['gates']
    assert decision['chosen_bindings']['gemini-3.8-flash:extended'] == 'gemini-3.8-flash-high'
    assert decision['binding_selection']['gemini-3.8-flash:extended']['rule'] == 'R2_SLUG_WITH_EFFORT_HIGH_PASSED'
    assert list(decision['effort_contracts']) == ['gemini-3.8-flash:extended']
    gemini = json.loads(outcome.candidate)['providers']['gemini']
    assert gemini['effort_contracts']['gemini-3.8-flash:extended']['arguments'] == ['--effort', 'high']


def test_rule_no_extended_evidence_leaves_the_route_unbound_without_a_contract(tmp_path, commissioned_bytes, monkeypatch):
    neither = {'R3': (b'', R3_REJECT, 1)}
    outcome, decision = contract_for(tmp_path / 'w', monkeypatch, isolation={'runs': neither})
    assert decision['outcome'] == 'GEMINI_CONTRACT', decision['gates']
    assert decision['chosen_bindings'] == {'gemini-3.8-flash': 'gemini-3.8-flash-low'} and decision['effort_contracts'] == {}
    assert decision['binding_selection']['gemini-3.8-flash:extended']['rule'] == 'UNBOUND_NO_PASSING_R2_OR_R3'
    assert json.loads(outcome.candidate)['providers']['gemini']['effort_contracts'] == {}


def test_rule_an_r3_echo_that_contradicts_high_leaves_the_route_unbound(tmp_path, commissioned_bytes, monkeypatch):
    medium = {'R3': (stream('gemini-3.8-flash-medium', 'conv-r3'), b'', 0)}
    outcome, decision = contract_for(tmp_path / 'w', monkeypatch, isolation={'runs': medium})
    assert decision['outcome'] == 'GEMINI_CONTRACT', decision['gates']
    assert 'gemini-3.8-flash:extended' not in decision['chosen_bindings'] and decision['effort_contracts'] == {}
    assert decision['binding_selection']['gemini-3.8-flash:extended']['rule'] == 'UNBOUND_R3_ECHO_NOT_A_HIGH_SLUG'


def test_rule_an_r3_family_echo_outside_the_catalog_holds_gemini_at_g2(tmp_path, commissioned_bytes, monkeypatch):
    family = {'R3': (stream('gemini-3.8-flash', 'conv-r3'), b'', 0)}
    outcome, decision = contract_for(tmp_path / 'w', monkeypatch, isolation={'runs': family})
    assert decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES' and outcome.candidate == commissioned_bytes
    assert gates_passed(decision) == {name: name != 'G2' for name in GATES}, decision['gates']
    assert 'reported slug gemini-3.8-flash is not in the signed-in catalog' in decision['gates']['G2']['reason']
    assert decision['proposed']['model_bindings']['gemini-3.8-flash:extended'] == 'gemini-3.8-flash'


def test_rule_r1_failing_holds_at_g3_whatever_r5_shows(tmp_path, commissioned_bytes, monkeypatch):
    tools = {'R1': (stream('gemini-3.8-flash-high', 'conv-r1', tools=['view_file']), b'', 0)}
    outcome, decision = contract_for(tmp_path / 'w', monkeypatch, isolation={'runs': tools})
    assert decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES' and outcome.candidate == commissioned_bytes
    assert decision['gates']['G3']['pass'] is False and 'R1_TOOLS_NOT_EMPTY' in decision['gates']['G3']['reason']
    assert 'disables_tools is not true' in decision['gates']['G3']['reason']
    assert decision['binding_selection']['gemini-3.8-flash']['rule'] == 'UNBOUND_NO_PASSING_R5_OR_R1'


def selection_receipt(runs, identity):
    return {'effort_null_slug': 'gemini-3.8-flash-low', 'runs': runs, 'identity_verdict': identity}


def run_row(run_id, model, extra=(), *, passes=True, echo=None, with_echo=None, code=0, breach=False):
    return {'id': run_id, 'requested_model': model, 'extra_arguments': list(extra), 'outcome': 'exited', 'exit_code': code,
            'checks': {'passes_contract': passes, 'passes_with_echo': passes if with_echo is None else with_echo, 'isolation_breach': breach},
            'classification': {'stream': {'init': {'model': echo or model}}}}


def test_select_bindings_unit_rules():
    effort = ('--effort', 'high')
    good = [run_row('R1', 'gemini-3.8-flash-high'), run_row('R5', 'gemini-3.8-flash-low'),
            run_row('R2', 'gemini-3.8-flash-high', effort, passes=False, code=1),
            run_row('R3', 'gemini-3.8-flash', effort, passes=False, with_echo=True, echo='gemini-3.8-flash-high')]
    identity = {'slug_form_passes_contract': True, 'slug_with_effort_passes_contract': False,
                'family_with_effort_passes_with_echo': True, 'family_with_effort_init_model': 'gemini-3.8-flash-high',
                'effort_null': {'slug': 'gemini-3.8-flash-low', 'run_id': 'R5', 'executed': True, 'passed': True,
                                'init_model': 'gemini-3.8-flash-low'}}
    selection = b.select_bindings(selection_receipt(good, identity), 'ref#' + 'a' * 64)
    assert selection.bindings == {'gemini-3.8-flash': 'gemini-3.8-flash-low',
                                  'gemini-3.8-flash:extended': {'argv': 'gemini-3.8-flash', 'reports': 'gemini-3.8-flash-high'}}
    assert selection.contracts['gemini-3.8-flash:extended']['capability_reference'] == 'ref#' + 'a' * 64
    assert list(selection.rules) == ['gemini-3.8-flash', 'gemini-3.8-flash:extended', 'gemini-3.1-pro-preview:high']
    # The identity verdict must agree with the run record before R5 binds the owner's slug.
    disagree = dict(identity, effort_null=dict(identity['effort_null'], passed=False))
    assert b.select_bindings(selection_receipt(good, disagree), 'r').bindings['gemini-3.8-flash'] == 'gemini-3.8-flash-high'
    # An undeclared owner slug is never bound, even when a run with it passed.
    odd = selection_receipt(good, identity)
    odd['effort_null_slug'] = 'gemini-3.7-flash-low'
    assert b.select_bindings(odd, 'r').rules['gemini-3.8-flash']['rule'] == 'R1_PRIMARY_SLUG'
    # Neither R5 nor R1 passing leaves the effort-null route unbound; an isolation breach disqualifies a run.
    broken = [run_row('R1', 'gemini-3.8-flash-high', passes=False), run_row('R5', 'gemini-3.8-flash-low', breach=True)]
    result = b.select_bindings(selection_receipt(broken, dict(identity, slug_form_passes_contract=False)), 'r')
    assert 'gemini-3.8-flash' not in result.bindings and result.rules['gemini-3.8-flash']['rule'] == 'UNBOUND_NO_PASSING_R5_OR_R1'
    # R2 wins whenever it passes; the pro tier is never bound.
    both = good[:2] + [run_row('R2', 'gemini-3.8-flash-high', effort), good[3]]
    result = b.select_bindings(selection_receipt(both, dict(identity, slug_with_effort_passes_contract=True)), 'r')
    assert result.bindings['gemini-3.8-flash:extended'] == 'gemini-3.8-flash-high'
    assert 'gemini-3.1-pro-preview:high' not in result.bindings and result.rules['gemini-3.1-pro-preview:high']['run'] is None
    # A malformed R3 echo (not a reviewed lowercase slug) leaves the extended route unbound.
    bad_echo = good[:3] + [run_row('R3', 'gemini-3.8-flash', effort, passes=False, with_echo=True, echo='OTHER')]
    result = b.select_bindings(selection_receipt(bad_echo, dict(identity, family_with_effort_init_model='OTHER')), 'r')
    assert result.rules['gemini-3.8-flash:extended']['rule'] == 'UNBOUND_R3_ECHO_NOT_A_HIGH_SLUG' and not result.contracts


# ---------------------------------------------------------------- refusals and exit codes

def test_out_dir_must_be_new_or_empty_and_nothing_is_overwritten(world, monkeypatch):
    out = world.base / 'busy'
    out.mkdir()
    (out / 'decision.json').write_bytes(b'sentinel')
    no_processes(monkeypatch)
    assert b.main(world.argv(out)) == 4
    assert (out / 'decision.json').read_bytes() == b'sentinel' and not (out / 'pipeline.json').exists()
    candidate_only = world.base / 'candidate-only'
    candidate_only.mkdir()
    (candidate_only / 'pipeline.json').write_bytes(b'sentinel')
    assert b.main(world.argv(candidate_only, mode='held')) == 4
    assert (candidate_only / 'pipeline.json').read_bytes() == b'sentinel' and not (candidate_only / 'decision.json').exists()
    a_file = world.base / 'a-file'
    a_file.write_bytes(b'x')
    assert b.main(world.argv(a_file, mode='held')) == 4
    empty = world.base / 'empty'
    empty.mkdir()
    assert b.main(world.argv(empty, mode='held')) == 0 and sorted(p.name for p in empty.iterdir()) == ['decision.json', 'pipeline.json']
    nested = world.base / 'new' / 'nested'
    assert b.main(world.argv(nested, mode='held')) == 0 and (nested / 'decision.json').exists()


def test_commissioned_refusals_exit_three_and_write_nothing(world, tmp_path, monkeypatch):
    no_processes(monkeypatch)
    tampered = world.base / 'tampered.json'
    tampered.write_bytes(world.commissioned_bytes + b' ')
    for mode in ('held', 'attempt'):
        out = world.base / f'refused-{mode}'
        argv = world.argv(out, mode=mode)
        argv[argv.index('--commissioned') + 1] = str(tampered)
        assert b.main(argv) == 3 and not out.exists()
    missing = world.argv(world.base / 'refused-missing', mode='held')
    missing[missing.index('--commissioned') + 1] = str(world.base / 'absent.json')
    assert b.main(missing) == 3 and not (world.base / 'refused-missing').exists()
    monkeypatch.undo()
    result = run_cli(['--commissioned', str(tampered), '--mode', 'held', '--out-dir', str(tmp_path / 'cli-refused')], tmp_path)
    assert result.returncode == 3 and not (tmp_path / 'cli-refused').exists()
    refusal = json.loads(result.stderr)
    assert refusal['status'] == 'REFUSED' and PIN in refusal['reason'] and result.stdout == b''


def test_usage_errors_exit_two(world, monkeypatch, capsys):
    no_processes(monkeypatch)
    out = world.base / 'usage'
    assert b.main(['--commissioned', str(world.commissioned), '--out-dir', str(out)]) == 2
    assert b.main(world.argv(out, mode='sometimes')) == 2
    assert b.main(world.argv(out, roots=False)) == 2
    assert b.main(world.argv(out, roots=False) + ['--login-root', str(world.login)]) == 2
    assert not out.exists()
    assert '--mode attempt requires --capture-root, --isolation-root' in capsys.readouterr().err


def test_an_explicit_stage_root_is_used_and_recorded(world, commissioned_bytes, monkeypatch):
    elsewhere = world.base / 'elsewhere'
    elsewhere.mkdir()
    moved = elsewhere / world.stage.name
    world.stage.rename(moved)
    outcome = run_in_process(monkeypatch, world)
    assert outcome.decision['gates']['G4']['pass'] is False and 'stage.receipt is missing' in outcome.decision['gates']['G4']['reason']
    assert outcome.decision['evidence_binding']['roots']['stage']['custody'] == 'absent'
    outcome = run_in_process(monkeypatch, world, out_name='explicit', extra=['--stage-root', str(moved)])
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert decision['outcome'] == 'GEMINI_CONTRACT' and decision['inputs']['stage_root'] == str(moved)
    assert decision['evidence']['stage.receipt']['path'] == str(moved / 'stage-receipt.json')
    # B-F1: an explicit stage root must still be the producer's namespace with the same attempt.
    renamed = world.base / 'elsewhere-stage'
    moved.rename(renamed)
    outcome = run_in_process(monkeypatch, world, out_name='renamed', extra=['--stage-root', str(renamed)])
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES' and outcome.candidate == commissioned_bytes
    assert "the stage root name 'elsewhere-stage' is not the producer namespace" in decision['evidence_binding']['reasons'][0]


# ---------------------------------------------------------------- evidence binding: one attempt, namespaces, custody (B-F1)

def _retag_stage(report):
    report['attempt'] = 'a' * 32
    report['nonce'] = 'b' * 32


def test_audit_repro_mismatched_attempts_across_g1_g4_are_refused_with_a_forced_held_decision(tmp_path, commissioned_bytes, monkeypatch):
    """Port of audit-build test_audit_build_repro.py: isolation evidence of world a combined with agent staging, login and
    capture evidence of world b whose staging receipt and summary carry another attempt. It used to yield GEMINI_CONTRACT."""
    a = World(tmp_path / 'a', commissioned_bytes)
    other = World(tmp_path / 'b', commissioned_bytes, stage={'receipt_patch': _retag_stage, 'summary_patch': _retag_stage})
    out = tmp_path / 'out'
    argv = ['--commissioned', str(a.commissioned), '--mode', 'attempt', '--out-dir', str(out),
            '--login-root', str(other.login), '--capture-root', str(other.capture), '--isolation-root', str(a.isolation),
            '--stage-root', str(other.stage)]
    no_processes(monkeypatch)
    trust_fixture_roots(monkeypatch)
    code = b.main(argv)
    monkeypatch.undo()
    outcome = Outcome(code, out)
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    stage_receipt = json.loads((other.stage / 'stage-receipt.json').read_bytes())
    iso_receipt = json.loads((a.isolation / 'isolation-receipt.json').read_bytes())
    assert code == 0 and stage_receipt['attempt'] != iso_receipt['attempt']
    assert decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES' and outcome.candidate == commissioned_bytes
    binding = decision['evidence_binding']
    assert binding['passed'] is False and binding['attempt'] is None
    assert binding['reasons'] == ['the evidence names more than one attempt: ' + '; '.join(
        [f'{name} root name {ATTEMPT}' for name in ('login', 'capture', 'isolation', 'stage')] +
        [f'{key} {"a" * 32 if key.startswith("stage.") else ATTEMPT}' for key in ATTEMPT_RECORD_KEYS])]
    assert binding['records']['stage.receipt'] == {'attempt': 'a' * 32, 'nonce': 'b' * 32}
    for gate in decision['gates'].values():
        assert gate['pass'] is False and gate['reason'] == 'not evaluated: the evidence binding refused the roots (' + binding['reasons'][0] + ')'
    assert decision['proposed'] is None and decision['binding_selection'] is None and decision['chosen_bindings'] is None


def _set_attempt(value):
    def patch(record):
        record['attempt'] = value
    return patch


def _drop_attempt(record):
    record.pop('attempt')


def _set_nonce(value):
    def patch(record):
        record['nonce'] = value
    return patch


OTHER = 'a' * 32
BINDING_RECORD_CASES = {
    'login-record-other-attempt': ({'login': {'record_patch': _set_attempt(OTHER)}}, 'the evidence names more than one attempt'),
    'capture-receipt-other-attempt': ({'capture': {'receipt_patch': _set_attempt(OTHER)}}, 'capture.receipt ' + OTHER),
    'capture-summary-other-attempt': ({'capture': {'summary_patch': _set_attempt(OTHER)}}, 'capture.summary ' + OTHER),
    'isolation-receipt-other-attempt': ({'isolation': {'receipt_patch': _set_attempt(OTHER)}}, 'isolation.receipt ' + OTHER),
    'isolation-summary-other-attempt': ({'isolation': {'summary_patch': _set_attempt(OTHER)}}, 'isolation.summary ' + OTHER),
    'stage-receipt-other-attempt': ({'stage': {'receipt_patch': _set_attempt(OTHER)}}, 'stage.receipt ' + OTHER),
    'stage-summary-other-attempt': ({'stage': {'summary_patch': _set_attempt(OTHER)}}, 'stage.summary ' + OTHER),
    'capture-receipt-without-attempt': ({'capture': {'receipt_patch': _drop_attempt}}, 'capture.receipt carries no lowercase 32-hex attempt'),
    'stage-summary-uppercase-attempt': ({'stage': {'summary_patch': _set_attempt(ATTEMPT.upper())}}, 'stage.summary carries no lowercase 32-hex attempt'),
    'isolation-summary-other-nonce': ({'isolation': {'summary_patch': _set_nonce('b' * 32)}}, 'the isolation receipt and summary do not carry one 32-hex nonce'),
    'capture-receipt-nonce-missing': ({'capture': {'receipt_patch': lambda report: report.pop('nonce')}},
                                      'the capture receipt and summary do not carry one 32-hex nonce'),
}


@pytest.mark.parametrize('variant', sorted(BINDING_RECORD_CASES))
def test_every_attempt_record_must_name_the_one_attempt_or_the_decision_is_forced_held(variant, tmp_path, commissioned_bytes, monkeypatch):
    options, fragment = BINDING_RECORD_CASES[variant]
    world = World(tmp_path / 'world', commissioned_bytes, **options)
    outcome = run_in_process(monkeypatch, world)
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert outcome.code == 0 and decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES' and outcome.candidate == commissioned_bytes
    binding = decision['evidence_binding']
    assert binding['passed'] is False and any(fragment in reason for reason in binding['reasons']), binding['reasons']
    assert decision['error'] is None and decision['proposed'] is None
    assert gates_passed(decision) == {name: False for name in GATES}


def _rename_root(world, attribute, name):
    target = getattr(world, attribute).with_name(name)
    getattr(world, attribute).rename(target)
    setattr(world, attribute, target)


BINDING_ROOT_CASES = {
    'login-root-of-the-claude-series': ('login', f'NativeAuthSix4.2.7-windows-20261011-r4-v1-{ATTEMPT}-claude', 'the login root name'),
    'login-root-of-another-attempt': ('login', f'NativeAuthSix4.2.7-windows-20261011-r4-v1-{OTHER}-gemini', 'login root name ' + OTHER),
    'capture-root-of-the-signed-out-stage': ('capture', f'AgyCapture4.2.7-windows-20261010-r4-v1-{ATTEMPT}-slot1-signed-out', 'the capture root name'),
    'capture-root-of-another-date': ('capture', f'AgyCapture4.2.7-windows-20261011-r4-v1-{ATTEMPT}-slot1-signed-in', 'the capture root name'),
    'isolation-root-of-another-sitting': ('isolation', f'AgyIsolation4.2.7-windows-20261012-r4-v1-{ATTEMPT}', 'the isolation root name'),
    'isolation-root-with-a-suffix': ('isolation', f'AgyIsolation4.2.7-windows-20261011-r4-v1-{ATTEMPT}-copy', 'the isolation root name'),
}


@pytest.mark.parametrize('variant', sorted(BINDING_ROOT_CASES))
def test_every_root_must_be_its_producer_namespace_with_the_one_attempt(variant, tmp_path, commissioned_bytes, monkeypatch):
    attribute, name, fragment = BINDING_ROOT_CASES[variant]
    world = World(tmp_path / 'world', commissioned_bytes)
    _rename_root(world, attribute, name)
    extra = ['--stage-root', str(world.stage)] if attribute == 'isolation' else []
    outcome = run_in_process(monkeypatch, world, extra=extra)
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES' and outcome.candidate == commissioned_bytes
    assert any(fragment in reason for reason in decision['evidence_binding']['reasons']), decision['evidence_binding']['reasons']
    assert gates_passed(decision) == {name: False for name in GATES}


def test_the_all_zero_preview_attempt_is_never_evidence(tmp_path, commissioned_bytes, monkeypatch):
    monkeypatch.setitem(globals(), 'ATTEMPT', '0' * 32)
    world = World(tmp_path / 'world', commissioned_bytes)
    outcome = run_in_process(monkeypatch, world)
    decision = json.loads(outcome.decision_bytes)
    assert outcome.candidate == commissioned_bytes and decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES'
    assert decision['evidence_binding']['reasons'] == ["the all-zero attempt is the producers' preview attempt, never evidence"]


def test_a_root_outside_protected_custody_forces_held_and_custody_runs_for_every_existing_root(world, commissioned_bytes, monkeypatch):
    calls = []

    def custody(root):
        calls.append(root)
        if root == str(world.isolation):
            raise b.GateFailure('untrusted owner S-1-5-21-1-2-3-1001 of ' + root)
    out = world.base / 'out'
    no_processes(monkeypatch)
    monkeypatch.setattr(b, 'check_root_custody', custody)
    code = b.main(world.argv(out))
    monkeypatch.undo()
    outcome = Outcome(code, out)
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert code == 0 and decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES' and outcome.candidate == commissioned_bytes
    assert calls == [str(world.login), str(world.capture), str(world.isolation), str(world.stage)]
    binding = decision['evidence_binding']
    assert binding['reasons'] == ['the isolation root is not in protected custody: untrusted owner S-1-5-21-1-2-3-1001 of ' + str(world.isolation)]
    assert binding['roots']['isolation']['custody'] == 'refused' and binding['roots']['login']['custody'] == 'protected'
    assert binding['attempt'] == ATTEMPT, 'the attempts agree; custody alone refuses'


def test_the_cli_with_the_real_custody_rule_holds_fixture_roots_outside_program_files(world, commissioned_bytes, tmp_path):
    out = world.base / 'cli-real-custody'
    result = run_cli(world.argv(out), tmp_path)
    assert result.returncode == 0, result.stderr
    outcome = Outcome(0, out)
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert decision['outcome'] == 'GEMINI_HELD_COMMISSIONED_BYTES' and outcome.candidate == commissioned_bytes
    binding = decision['evidence_binding']
    assert {name: entry['custody'] for name, entry in binding['roots'].items()} == {name: 'refused' for name in ('login', 'capture', 'isolation', 'stage')}
    for name, root in (('login', world.login), ('capture', world.capture), ('isolation', world.isolation), ('stage', world.stage)):
        assert f'the {name} root is not in protected custody: {root} is not directly under C:\\Program Files\\CoChem' in binding['reasons']
    assert decision['evidence'] and set(decision['evidence']) == set(ATTEMPT_RECORD_KEYS), 'only the attempt records were read'


def test_check_root_custody_requires_the_cochem_parent_before_any_acl_read(tmp_path, monkeypatch):
    def unread(path):
        raise AssertionError('no ACL read for a root outside C:\\Program Files\\CoChem')
    monkeypatch.setattr(b, 'protected_ancestry', unread)
    root = tmp_path / f'AgyIsolation4.2.7-windows-20261011-r4-v1-{ATTEMPT}'
    root.mkdir()
    with pytest.raises(b.GateFailure, match='is not directly under C:\\\\Program Files\\\\CoChem'):
        b.check_root_custody(str(root))
    seen = []
    monkeypatch.setattr(b, 'protected_ancestry', seen.append)
    b.check_root_custody('C:\\Program Files\\CoChem\\AgyIsolation4.2.7-windows-20261011-r4-v1-' + ATTEMPT)
    assert seen == ['C:\\Program Files\\CoChem\\AgyIsolation4.2.7-windows-20261011-r4-v1-' + ATTEMPT]


SYSTEM, ADMINS, USERS, OWNER_SID = 'S-1-5-18', 'S-1-5-32-544', 'S-1-5-32-545', 'S-1-5-21-1-2-3-1001'
INSTALLER = 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464'
CLEAN =[(0, 0, 0x1F01FF, SYSTEM), (0, 0, 0x1F01FF, ADMINS), (0, 0, 0x1200A9, USERS)]
ANCESTRY_CASES = {
    'clean': ({}, None),
    'program_files_owned_by_trustedinstaller': ({'top': (INSTALLER, CLEAN)}, None),
    'user_owner': ({'leaf': (OWNER_SID, CLEAN)}, 'untrusted owner ' + OWNER_SID),
    'users_may_write': ({'leaf': (ADMINS, CLEAN + [(0, 0, 0x2, USERS)])}, USERS + ' may write or replace'),
    'owner_may_delete': ({'leaf': (ADMINS, CLEAN + [(0, 0, 0x10000, OWNER_SID)])}, OWNER_SID + ' may write or replace'),
    'generic_write_callback_ace': ({'top': (INSTALLER, CLEAN + [(9, 0, 0x40000000, OWNER_SID)])}, OWNER_SID + ' may write or replace'),
    'inherit_only_writer_is_ignored': ({'leaf': (ADMINS, CLEAN + [(0, 0x08 | 0x03, 0x10000000, 'S-1-3-0')])}, None),
    'deny_entries_are_ignored': ({'leaf': (ADMINS, CLEAN + [(1, 0, 0x1F01FF, USERS)])}, None),
    'object_ace_is_refused': ({'leaf': (ADMINS, CLEAN + [(5, 0, None, None)])}, 'unexpected access entry type 5'),
}


@pytest.mark.parametrize('case', sorted(ANCESTRY_CASES))
def test_protected_ancestry_is_the_house_assert_protected_path_rule(case):
    if not Path(b.EVIDENCE_BASE).is_dir():
        pytest.skip('C:\\Program Files\\CoChem is absent on this host')
    overrides, expected = ANCESTRY_CASES[case]
    visited = []

    def reader(path):
        visited.append(path)
        level = 'leaf' if path == b.EVIDENCE_BASE else 'top'
        return overrides.get(level, (ADMINS if level == 'leaf' else INSTALLER, CLEAN))
    if expected is None:
        b.protected_ancestry(b.EVIDENCE_BASE, reader=reader)
        assert visited == [b.EVIDENCE_BASE, b.PROTECTED_TOP], 'the walk stops at C:\\Program Files'
    else:
        with pytest.raises(b.GateFailure, match=re.escape(expected)):
            b.protected_ancestry(b.EVIDENCE_BASE, reader=reader)


def test_the_real_acl_reader_accepts_cochem_and_refuses_a_user_directory(tmp_path):
    if not Path(b.EVIDENCE_BASE).is_dir():
        pytest.skip('C:\\Program Files\\CoChem is absent on this host')
    owner, entries = b.security_descriptor(b.PROTECTED_TOP)
    assert owner == INSTALLER and any(sid == USERS for _, _, _, sid in entries)
    b.protected_ancestry(b.EVIDENCE_BASE)
    with pytest.raises(b.GateFailure, match='untrusted owner'):
        b.protected_ancestry(str(tmp_path))


def test_the_root_namespaces_are_the_producers_namespaces():
    """The producers name their roots with these fixed dates and suffixes (read-only source checks)."""
    login = (W / 'login-six-workers-status-first-r4-v1.ps1').read_text(encoding='utf-8')
    capture = (W / 'agy-status-capture-r4-v1.ps1').read_text(encoding='utf-8')
    isolation = (W / 'agy-isolation-evidence-r4-v1.ps1').read_text(encoding='utf-8')
    assert "$script:seriesNamespaceDate='20261011'" in login
    assert "('NativeAuthSix4.2.7-windows-'+$script:seriesNamespaceDate+'-r4-v1-'+$Attempt+'-'+$Provider)" in login
    assert "$script:captureNamespaceDate='20261010'" in capture
    assert "('AgyCapture4.2.7-windows-'+$script:captureNamespaceDate+'-r4-v1-'+$Attempt+'-'+$Slot+'-'+$Stage)" in capture
    assert "$script:isolationNamespaceDate='20261011'" in isolation and "$suffix=$(if($Mode -ceq 'stage'){'-stage'}else{''})" in isolation
    assert "('AgyIsolation4.2.7-windows-'+$script:isolationNamespaceDate+'-r4-v1-'+$Attempt+$suffix)" in isolation
    assert str(iso.evidence_root('evidence', ATTEMPT)) == b.EVIDENCE_BASE + '\\AgyIsolation4.2.7-windows-20261011-r4-v1-' + ATTEMPT
    assert str(iso.evidence_root('stage', ATTEMPT)) == b.EVIDENCE_BASE + '\\AgyIsolation4.2.7-windows-20261011-r4-v1-' + ATTEMPT + '-stage'
    patterns = dict(b.ROOT_NAMESPACES)
    for name, root in (('login', f'NativeAuthSix4.2.7-windows-20261011-r4-v1-{ATTEMPT}-gemini'),
                       ('capture', f'AgyCapture4.2.7-windows-20261010-r4-v1-{ATTEMPT}-slot1-signed-in'),
                       ('isolation', f'AgyIsolation4.2.7-windows-20261011-r4-v1-{ATTEMPT}'),
                       ('stage', f'AgyIsolation4.2.7-windows-20261011-r4-v1-{ATTEMPT}-stage')):
        assert patterns[name].fullmatch(root).group(1) == ATTEMPT
    assert [key for _, key, _ in b.ATTEMPT_RECORDS] == ATTEMPT_RECORD_KEYS


def test_an_unreadable_attempt_record_is_left_to_its_gate_and_read_once(world, commissioned_bytes, monkeypatch):
    """The binding and the gates judge the same bytes: each evidence file is opened once even though both look at it."""
    (world.login / 'series-complete.json').write_bytes(b'{"attempt": ')
    opened = []
    real = b.read_regular

    def counting(path, maximum, label):
        opened.append(label)
        return real(path, maximum, label)
    monkeypatch.setattr(b, 'read_regular', counting)
    outcome = run_in_process(monkeypatch, world)
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert decision['evidence_binding']['passed'] is True and decision['evidence_binding']['records']['login.series_complete'] is None
    assert gates_passed(decision) == {name: name != 'G1' for name in GATES} and 'not valid JSON' in decision['gates']['G1']['reason']
    assert sorted(opened) == sorted(set(opened)), 'no evidence file is read twice'


# ---------------------------------------------------------------- G6 copy under --out-dir (B-F6)

def test_g6_reads_its_private_copy_inside_the_out_dir_and_never_uses_temp(world, commissioned_bytes, monkeypatch):
    from cochem_pipeline import config
    import tempfile
    seen = []
    real = config.load_config

    def spy(filename):
        seen.append((filename, Path(filename).read_bytes(), sorted(p.name for p in Path(filename).parent.iterdir())))
        return real(filename)

    def no_temp(*args, **kwargs):
        raise AssertionError('the builder must not use tempfile (%TEMP%)')
    monkeypatch.setattr(config, 'load_config', spy)
    for name in ('TemporaryDirectory', 'mkdtemp', 'mkstemp', 'NamedTemporaryFile', 'TemporaryFile'):
        monkeypatch.setattr(tempfile, name, no_temp)
    outcome = run_in_process(monkeypatch, world)
    decision = assert_stager_invariants(outcome, commissioned_bytes)
    assert decision['outcome'] == 'GEMINI_CONTRACT' and decision['gates']['G6']['pass'] is True
    assert len(seen) == 1
    filename, data, listing = seen[0]
    assert Path(filename) == outcome.out / 'g6-load-config-check' / 'pipeline.json' and listing == ['pipeline.json']
    assert data == outcome.candidate, 'G6 loads exactly the candidate bytes'
    assert sorted(p.name for p in outcome.out.iterdir()) == ['decision.json', 'pipeline.json'], 'the scratch copy is gone'


def test_g6_scratch_is_removed_when_load_config_raises(world, commissioned_bytes, monkeypatch):
    from cochem_pipeline import config
    seen = []

    def reject(filename):
        seen.append(Path(filename))
        raise ValueError('rejected by the r5 parser')
    monkeypatch.setattr(config, 'load_config', reject)
    outcome = run_in_process(monkeypatch, world)
    assert seen == [outcome.out / 'g6-load-config-check' / 'pipeline.json']
    assert outcome.decision['gates']['G6']['pass'] is False and 'rejected by the r5 parser' in outcome.decision['gates']['G6']['reason']
    assert sorted(p.name for p in outcome.out.iterdir()) == ['decision.json', 'pipeline.json']
