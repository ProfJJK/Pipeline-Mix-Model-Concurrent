"""Inert fixtures for worker-native-auth-status-six-r4-v1.py (build-manifest step 3).

No native provider, SYSTEM, task or login call runs. The r4 receipts under Program Files are
only read. The helper's run() is driven end to end with the Windows primitives monkeypatched
(pattern of test_status_first_native_six_r3_v1.py lines 70-121): real parser, real bounded
temporary output files and a real one-shot receipt in a temporary root.
"""
from contextlib import contextmanager
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

W = Path(__file__).parent
PY = W / 'worker-native-auth-status-six-r4-v1.py'
R3V3 = W / 'worker-native-auth-status-six-r3-v3.py'
R3V3_SHA256 = '7efa8d272fcd96701157e381036f7e4ec763551857f4c57091d7bf61977fcfc1'
STATUS_R3 = W / 'worker-native-status-r3.py'
CAPTURE = W / 'agy_status_capture_r4_v1.py'
R4 = Path(r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4')
R3 = Path(r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r3')
AGY = Path(r'C:\Program Files\CoChem\Native4.2.7-windows-20261006\agy.exe')
ATTEMPT = '0123456789abcdef0123456789abcdef'
NONCE = 'a' * 32


def module(path, name=None):
    spec = importlib.util.spec_from_file_location(name or path.stem.replace('-', '_'), path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


status = module(PY)
previous = module(R3V3, 'previous_status_r3_v3')

# The 18-row catalog of the captured owner-account listing (SCR\captures\models_json_pre.stdout.txt).
ROWS = [('gemini-3.8-flash-high', 'Gemini 3.8 Flash (High)'), ('gemini-3.8-flash-medium', 'Gemini 3.8 Flash (Medium)'),
        ('gemini-3.8-flash-low', 'Gemini 3.8 Flash (Low)'), ('gemini-3.7-flash-high', 'Gemini 3.7 Flash (High)'),
        ('gemini-3.7-flash-medium', 'Gemini 3.7 Flash (Medium)'), ('gemini-3.7-flash-low', 'Gemini 3.7 Flash (Low)'),
        ('gemini-3.6-flash-high', 'Gemini 3.6 Flash (High)'), ('gemini-3.6-flash-medium', 'Gemini 3.6 Flash (Medium)'),
        ('gemini-3.6-flash-low', 'Gemini 3.6 Flash (Low)'), ('gemini-3.1-pro-high', 'Gemini 3.1 Pro (High)'),
        ('gemini-3.1-pro-low', 'Gemini 3.1 Pro (Low)'), ('claude-opus-5-5-low', 'Claude Opus 5.5 (Low)'),
        ('claude-opus-5-5-medium', 'Claude Opus 5.5 (Medium)'), ('claude-opus-5-5-high', 'Claude Opus 5.5 (High)'),
        ('claude-sonnet-5-5-low', 'Claude Sonnet 5.5 (Low)'), ('claude-sonnet-5-5-medium', 'Claude Sonnet 5.5 (Medium)'),
        ('claude-sonnet-5-5-high', 'Claude Sonnet 5.5 (High)'), ('gpt-oss-120b-medium', 'GPT-OSS 120B (Medium)')]
FETCH = b'Fetching available models...\n'
SIGN_IN = b'Please sign in to view available models. Launch the CLI without arguments to sign in.\n'
EMAIL = 'owner.private@example.invalid'


def envelope(status_value='SUCCESS', rows=ROWS, name='models', models_key='models'):
    value = {'conversation_id': '', 'status': status_value, 'response': ''.join(f'{a}\t{b}\n' for a, b in rows),
             'duration_seconds': 0, 'num_turns': 0,
             'usage': {'input_tokens': 0, 'output_tokens': 0, 'thinking_tokens': 0, 'cache_read_tokens': 0, 'total_tokens': 0},
             'command': {'name': name, 'data': {models_key: [{'id': a, 'label': b} for a, b in rows]}}}
    return (json.dumps(value, separators=(',', ':'), ensure_ascii=False) + '\n').encode()


CAPTURED = envelope()


def test_captured_envelope_fixture_is_byte_exact():
    """The fixture reproduces the 2269-byte signed-in capture (sha256 1613d351..., re-hashed)."""
    assert len(CAPTURED) == 2269
    assert hashlib.sha256(CAPTURED).hexdigest() == '1613d351fed8acd4db9342a3386585edcb7664b52c6294f637b69821919cd81d'
    assert hashlib.sha256(FETCH).hexdigest() == '53f588bc9a928f4a66908deacaca57dddc7e7ce177a0cc3586b5a501be26e1e8'


GEMINI_TABLE = [
    ('captured_signed_in', CAPTURED, FETCH, 0, 'REUSE_VERIFIED_SESSION'),
    ('captured_signed_in_without_fetch_line', CAPTURED, b'', 0, 'REUSE_VERIFIED_SESSION'),
    ('captured_signed_in_crlf_fetch_line', CAPTURED, b'Fetching available models...\r\n', 0, 'REUSE_VERIFIED_SESSION'),
    ('envelope_status_error_exit0', envelope('ERROR'), FETCH, 0, 'ATTENDED_LOGIN_REQUIRED'),
    ('envelope_status_error_exit1', envelope('ERROR'), FETCH, 1, 'ATTENDED_LOGIN_REQUIRED'),
    ('envelope_status_error_no_models', envelope('ERROR', rows=[]), b'', 0, 'ATTENDED_LOGIN_REQUIRED'),
    ('sign_in_line_stdout_exit0', SIGN_IN, b'', 0, 'ATTENDED_LOGIN_REQUIRED'),
    ('sign_in_line_stdout_exit1', SIGN_IN, b'', 1, 'ATTENDED_LOGIN_REQUIRED'),
    ('sign_in_line_stdout_exit2', SIGN_IN, b'', 2, 'ATTENDED_LOGIN_REQUIRED'),
    ('sign_in_line_stderr_exit0', b'', FETCH + SIGN_IN, 0, 'ATTENDED_LOGIN_REQUIRED'),
    ('sign_in_line_stderr_exit1', b'', SIGN_IN, 1, 'ATTENDED_LOGIN_REQUIRED'),
    ('authentication_required_exit1', b'', b"Error: authentication required. Run 'agy' to log in.\n", 1, 'ATTENDED_LOGIN_REQUIRED'),
    ('not_logged_into_antigravity_exit0', b'You are not logged into Antigravity.\n', b'', 0, 'ATTENDED_LOGIN_REQUIRED'),
    ('nonzero_exit_without_output', b'', b'', 1, 'ATTENDED_LOGIN_REQUIRED'),
    ('nonzero_exit_with_success_envelope', CAPTURED, FETCH, 1, 'ATTENDED_LOGIN_REQUIRED'),
    ('exit0_empty_stdout', b'', FETCH, 0, 'HOLD'),
    ('exit0_empty_everything', b'', b'', 0, 'HOLD'),
    ('email_looking_extra_stderr_line', CAPTURED, FETCH + (EMAIL + '\n').encode(), 0, 'HOLD'),
    ('stderr_other_than_fetch_line', CAPTURED, b'Fetching available models...\nA newer version is available.\n', 0, 'HOLD'),
    ('signed_in_table_without_gemini_row', envelope(rows=ROWS[11:]), FETCH, 0, 'HOLD'),
    ('signed_in_table_gemini_only_in_label', envelope(rows=[('claude-opus-5-5-low', 'gemini-like label')]), FETCH, 0, 'HOLD'),
    ('empty_model_list', envelope(rows=[]), FETCH, 0, 'HOLD'),
    ('wrong_command_name', envelope(name='agents'), FETCH, 0, 'HOLD'),
    ('models_under_wrong_key', envelope(models_key='agents'), FETCH, 0, 'HOLD'),
    ('row_without_label', CAPTURED.replace(b',"label":"Gemini 3.8 Flash (High)"', b''), FETCH, 0, 'HOLD'),
    ('row_label_not_string', CAPTURED.replace(b'"Gemini 3.8 Flash (High)"', b'7'), FETCH, 0, 'HOLD'),
    ('duplicate_json_field', CAPTURED.replace(b'{"conversation_id":""', b'{"conversation_id":"","conversation_id":""'), FETCH, 0, 'HOLD'),
    ('plain_text_table_not_json', b''.join(f'{a}\t{b}\n'.encode() for a, b in ROWS), FETCH, 0, 'HOLD'),
    ('json_array_not_object', b'[]\n', FETCH, 0, 'HOLD'),
    ('nonfinite_json', b'{"status":NaN}\n', FETCH, 0, 'HOLD'),
    ('oversize_success', CAPTURED + b' ' * (65536 - len(CAPTURED) - len(FETCH) + 1), FETCH, 0, 'HOLD'),
    ('oversize_sign_in_nonzero_exit', SIGN_IN * 800, b'', 1, 'HOLD'),
    ('non_utf8_nonzero_exit', b'\xff\xfe', b'', 1, 'HOLD'),
    ('exit_code_not_int', CAPTURED, FETCH, None, 'HOLD'),
    ('exit_code_bool', CAPTURED, FETCH, True, 'HOLD'),
    ('stdout_not_bytes', CAPTURED.decode(), FETCH, 0, 'HOLD'),
]


@pytest.mark.parametrize('case,stdout,stderr,code,expected', GEMINI_TABLE, ids=[row[0] for row in GEMINI_TABLE])
def test_gemini_parse_status_allowlist_table(case, stdout, stderr, code, expected):
    result = status.parse_status('gemini', stdout, stderr, code)
    assert status.authentication_decision(result) == expected, result
    assert set(result) == {'protocol_valid', 'logged_in', 'auth_kind', 'native_subscription_authentication_verified',
                           'subscription_type', 'plan_entitlement_verified', 'provider_account_identity_verified'}
    assert result['subscription_type'] == 'unreported' and result['plan_entitlement_verified'] is False
    assert result['provider_account_identity_verified'] is False
    if expected == 'REUSE_VERIFIED_SESSION':
        assert result == {'protocol_valid': True, 'logged_in': True, 'auth_kind': 'google',
                          'native_subscription_authentication_verified': True, 'subscription_type': 'unreported',
                          'plan_entitlement_verified': False, 'provider_account_identity_verified': False}
    elif expected == 'ATTENDED_LOGIN_REQUIRED':
        assert result['protocol_valid'] is True and result['logged_in'] is False and result['auth_kind'] == 'none'
        assert result['native_subscription_authentication_verified'] is False
    else:
        assert result['logged_in'] is False and result['native_subscription_authentication_verified'] is False
    # Never persists a line: no provider text reaches the classification.
    text = json.dumps(result)
    for fragment in (EMAIL, 'example.invalid', 'Please sign in', 'gemini-3', 'Fetching', 'Antigravity', 'newer version'):
        assert fragment not in text


def test_gemini_predicate_agrees_with_the_capture_helper_table():
    """The capture's P2 gate uses the same predicate (build-manifest step 2 predicate constants)."""
    if not CAPTURE.exists():
        pytest.skip('agy_status_capture_r4_v1.py is not present in this workspace')
    capture = module(CAPTURE, 'agy_status_capture_r4_v1_for_status_test')
    assert capture.SIGN_IN_PREDICATE_TEXT in status.GEMINI_SIGNED_OUT_MARKERS
    assert capture.AUTH_REQUIRED_TEXT in status.GEMINI_SIGNED_OUT_MARKERS
    assert capture.NOT_LOGGED_IN_LINE in status.GEMINI_SIGNED_OUT_MARKERS
    assert capture.FETCHING_LINE == status.GEMINI_FETCH_LINE and capture.MAX_OUTPUT == status.MAX_OUTPUT
    assert capture.AGY_SHA256 == status.CONTRACTS['gemini']['sha256'] and capture.AGY_VERSION == status.CONTRACTS['gemini']['version_at_pin']
    mapping = {'LOGGED_IN': 'REUSE_VERIFIED_SESSION', 'LOGGED_OUT': 'ATTENDED_LOGIN_REQUIRED', 'HOLD': 'HOLD'}
    for case, stdout, stderr, code, expected in GEMINI_TABLE:
        if not isinstance(stdout, bytes):
            continue
        assert mapping[capture.status_helper_predicate(stdout, stderr, code, True)] == expected, case
    assert capture.status_helper_predicate(CAPTURED, FETCH, 0, False) == 'HOLD'  # a timeout never classifies


@pytest.mark.parametrize('mutation', [
    {'protocol_valid': False}, {'logged_in': 1}, {'native_subscription_authentication_verified': 1},
    {'auth_kind': 'Google'}, {'auth_kind': 'none'}, {'logged_in': False}, {'protocol_valid': 'true'}])
def test_google_decision_requires_exact_verified_fields(mutation):
    value = status.parse_status('gemini', CAPTURED, FETCH, 0)
    assert status.authentication_decision(value) == 'REUSE_VERIFIED_SESSION'
    value.update(mutation)
    assert status.authentication_decision(value) == 'HOLD'


def test_authentication_decision_accepts_exactly_the_three_reviewed_kinds():
    base = {'protocol_valid': True, 'logged_in': True, 'native_subscription_authentication_verified': True}
    for kind in ('chatgpt', 'claude.ai', 'google'):
        assert status.authentication_decision(dict(base, auth_kind=kind)) == 'REUSE_VERIFIED_SESSION'
    for kind in ('none', 'api_key', 'oauth_token', 'gemini', 'agy', None):
        assert status.authentication_decision(dict(base, auth_kind=kind)) == 'HOLD'
    out = {'protocol_valid': True, 'logged_in': False, 'native_subscription_authentication_verified': False, 'auth_kind': 'none'}
    assert status.authentication_decision(out) == 'ATTENDED_LOGIN_REQUIRED'
    assert status.authentication_decision(None) == 'HOLD' and status.authentication_decision([]) == 'HOLD'
    with pytest.raises(ValueError):
        status.parse_status('openai', b'', b'', 0)


CODEX_CLAUDE_TABLE = [
    ('codex', b'Logged in using ChatGPT', b'', 0), ('codex', b'Not logged in', b'', 1), ('codex', b'Logged in using ChatGPT', b'', 1),
    ('codex', b'Logged in using an API key', b'', 0), ('codex', b'', b'Not logged in\n', 2), ('codex', b'\xff', b'', 0),
    ('claude', json.dumps({'loggedIn': True, 'authMethod': 'claude.ai', 'apiProvider': 'firstParty', 'subscriptionType': 'max'}).encode(), b'', 0),
    ('claude', json.dumps({'loggedIn': False, 'authMethod': 'none'}).encode(), b'', 1),
    ('claude', json.dumps({'loggedIn': True, 'authMethod': 'api_key'}).encode(), b'', 0),
    ('claude', json.dumps({'loggedIn': True, 'authMethod': 'claude.ai', 'apiProvider': 'firstParty', 'subscriptionType': 'pro'}).encode(), b'warning\n', 0),
    ('claude', json.dumps({'loggedIn': True, 'authMethod': 'claude.ai', 'apiProvider': 'firstParty', 'subscriptionType': None}).encode(), b'', 0),
    ('claude', b'{"loggedIn":true,"loggedIn":true}', b'', 0), ('claude', b'not json', b'', 1), ('claude', b'x' * 70000, b'', 0)]


@pytest.mark.parametrize('provider,stdout,stderr,code', CODEX_CLAUDE_TABLE, ids=[f'{row[0]}-{index}' for index, row in enumerate(CODEX_CLAUDE_TABLE)])
def test_codex_and_claude_classification_is_unchanged_from_r3_v3(provider, stdout, stderr, code):
    assert status.parse_status(provider, stdout, stderr, code) == previous.parse_status(provider, stdout, stderr, code)
    old = previous.authentication_decision(previous.parse_status(provider, stdout, stderr, code))
    assert status.authentication_decision(status.parse_status(provider, stdout, stderr, code)) == old


def function_nodes(path):
    text = path.read_text(encoding='utf-8')
    return text, {node.name: node for node in ast.parse(text).body if isinstance(node, ast.FunctionDef)}


# The only differences run() may carry relative to r3-v3: r4 namespace/helper name, r4 runtime binding,
# r4 wording of one message, and the provider -> executable map (agy.exe for gemini).
RUN_SUBSTITUTIONS = (
    ("f'NativeAuthStatusSix4.2.7-windows-20261008-r3-v3-{attempt}-{slot}-{provider}-{stage}'", "f'{ROOT_PREFIX}{attempt}-{slot}-{provider}-{stage}'"),
    ("root / 'worker-native-auth-status-six-r3-v3.py'", 'root / HELPER_NAME'),
    ('verify_r3_runtime(win, INSTALL_RECEIPT_SHA256)', 'verify_r4_runtime(win, INSTALL_RECEIPT_SHA256)'),
    ("'Exact r3 layout/configuration binding differs'", "'Exact r4 layout/configuration binding differs'"),
    ("NATIVE / (provider + '.exe')", 'NATIVE / NATIVE_EXECUTABLES[provider]'),
)


def test_unchanged_functions_are_byte_identical_to_r3_v3():
    assert hashlib.sha256(R3V3.read_bytes()).hexdigest() == R3V3_SHA256, 'the reviewed predecessor changed'
    old_text, old = function_nodes(R3V3)
    new_text, new = function_nodes(PY)
    changed = {'parse_status', 'authentication_decision', 'verify_r3_runtime', 'run'}
    for name, node in old.items():
        if name in changed:
            continue
        assert name in new, name
        assert ast.dump(new[name]) == ast.dump(node), name
        assert ast.get_source_segment(new_text, new[name]) == ast.get_source_segment(old_text, node), name
    assert 'verify_r3_runtime' not in new and 'verify_r4_runtime' in new
    assert set(new) - set(old) == {'verify_r4_runtime'}
    # run(): exactly the enumerated substitutions, each applied once, and nothing else.
    run_old = ast.get_source_segment(old_text, old['run'])
    for before, after in RUN_SUBSTITUTIONS:
        assert run_old.count(before) == 1, before
        run_old = run_old.replace(before, after)
    assert run_old == ast.get_source_segment(new_text, new['run'])
    # authentication_decision: only the accepted kind tuple gains 'google'.
    decision_old = ast.get_source_segment(old_text, old['authentication_decision']).replace("('chatgpt','claude.ai')", "('chatgpt','claude.ai','google')")
    assert decision_old == ast.get_source_segment(new_text, new['authentication_decision'])


def top_level_names(path):
    names = set()
    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
    return names


def test_support_module_symbols_cover_the_bridge_and_status_r3_surface():
    names = top_level_names(PY)
    bridge = {'digest_file', 'validate_interpreter', 'WINDOWS_SHA256', 'verify_r4_runtime', 'INSTALL_RECEIPT_SHA256', 'MANIFEST_SHA256',
              'RESOURCE_SHA256', 'require_stopped', 'protected_json', 'CONTRACTS', 'observe_child', 'safe_failure',
              'launch_status_process', 'bounded_wait', 'authentication_decision'}
    assert bridge <= names
    assert (top_level_names(R3V3) - {'verify_r3_runtime'}) | {'verify_r4_runtime'} <= names
    if STATUS_R3.exists():
        assert (top_level_names(STATUS_R3) - {'verify_r3_runtime'}) | {'verify_r4_runtime'} <= names


def test_contract_constants_and_namespace():
    assert status.CONTRACTS['gemini'] == {'sha256': '38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741',
                                          'version_at_pin': '1.3.1', 'arguments': ['--output-format', 'json', 'models']}
    assert status.CONTRACTS['gemini']['arguments'].index('--output-format') < status.CONTRACTS['gemini']['arguments'].index('models')
    for provider in ('codex', 'claude'):
        assert status.CONTRACTS[provider] == previous.CONTRACTS[provider]
    assert status.NATIVE_EXECUTABLES == {'codex': 'codex.exe', 'claude': 'claude.exe', 'gemini': 'agy.exe'}
    assert status.INSTALL == R4 and status.PYTHON == R4 / '.venv/Scripts/python.exe' and status.PREVIOUS_INSTALL == R3
    assert status.ROOT_PREFIX == 'NativeAuthStatusSix4.2.7-windows-20261010-r4-v1-' and status.HELPER_NAME == PY.name
    assert status.DAEMON_TASK_NAMES == ('CoChem-4.2.7-Warden', 'CoChem-4.2.7-Supervisor', 'CoChem-4.2.2-Warden', 'CoChem-4.2.3-Supervisor')
    assert status.STATUS_SECONDS == 30 and status.MAX_OUTPUT == 65536
    for name in ('WINDOWS_SHA256', 'RESOURCE_SHA256', 'CONFIG_SHA256', 'LAYOUT_SHA256', 'PYTHON_SHA256', 'VENV_CONFIG_SHA256',
                 'ORIGINAL_FAILED_SHA256', 'BASE_PYTHON'):
        assert getattr(status, name) == getattr(previous, name), name
    for name in ('INSTALL_RECEIPT_SHA256', 'MANIFEST_SHA256', 'REVISION_SHA256'):
        assert getattr(status, name) != getattr(previous, name), name
    assert status.PREVIOUS_INSTALL_RECEIPT_SHA256 == previous.INSTALL_RECEIPT_SHA256
    assert status.PREVIOUS_MANIFEST_SHA256 == previous.MANIFEST_SHA256
    assert 'r3' not in status.ROOT_PREFIX and 'NativeAuthStatusSix4.2.7-windows-20261008-r3-v3' not in PY.read_text(encoding='utf-8').split('def run(')[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.skipif(not (R4 / 'install-after.json').exists(), reason='the r4 runtime is not installed on this host')
def test_module_pins_equal_the_on_disk_r4_receipts_read_only():
    installed = json.loads((R4 / 'install-after.json').read_bytes())
    assert sha(R4 / 'install-after.json') == status.INSTALL_RECEIPT_SHA256
    assert sha(R4 / 'source-manifest.json') == status.MANIFEST_SHA256 == installed['source_manifest_sha256']
    assert sha(R4 / 'pipeline.json') == status.CONFIG_SHA256 == installed['configuration_sha256']
    assert sha(R4 / 'windows-layout.json') == status.LAYOUT_SHA256
    assert sha(R4 / '.venv/Scripts/python.exe') == status.PYTHON_SHA256 == installed['runtime_bindings']['venv_python_sha256']
    assert sha(R4 / '.venv/pyvenv.cfg') == status.VENV_CONFIG_SHA256 == installed['runtime_bindings']['pyvenv_sha256']
    assert sha(status.BASE_PYTHON) == status.BASE_PYTHON_SHA256 == installed['runtime_bindings']['base_python_sha256']
    assert str(status.BASE_PYTHON.parent) == installed['runtime_bindings']['base_root']
    assert sha(R4 / '.venv/Lib/site-packages/cochem_pipeline/windows.py') == status.WINDOWS_SHA256
    assert sha(R4 / '.venv/Lib/site-packages/cochem_pipeline/resource_limits.py') == status.RESOURCE_SHA256
    assert sha(R4 / '.venv/Lib/site-packages/cochem_pipeline/resource_telemetry.py') == status.REPAIR_SHA256 == installed['reviewed_repair_sha256']
    assert installed['verification']['revision']['source_sha256'] == status.REVISION_SHA256
    assert installed['previous_install_receipt_sha256'] == status.PREVIOUS_INSTALL_RECEIPT_SHA256
    assert installed['previous_source_manifest_sha256'] == status.PREVIOUS_MANIFEST_SHA256
    assert installed['previous_runtime_root'] == str(status.PREVIOUS_INSTALL) and installed['target_root'] == str(status.INSTALL)
    assert installed['reviewed_repair'] == status.REPAIR_RELATIVE and installed['preserved_denial_receipt_sha256'] == status.ORIGINAL_FAILED_SHA256
    config = json.loads((R4 / 'pipeline.json').read_bytes())
    for provider, name in status.NATIVE_EXECUTABLES.items():
        assert Path(config['providers'][provider]['executable']) == status.NATIVE / name
    if AGY.exists():
        assert sha(AGY) == status.CONTRACTS['gemini']['sha256']


@pytest.fixture
def r4_bound(monkeypatch):
    """verify_r4_runtime against the real r4 files, with only interpreter identity and ACL custody stubbed."""
    if not (R4 / 'install-after.json').exists():
        pytest.skip('the r4 runtime is not installed on this host')
    from cochem_pipeline import ramdisk, resource_limits
    m = module(PY, 'status_r4_bound')
    installed_revision = module(R4 / '.venv/Lib/site-packages/cochem_pipeline/deployment_revision.py', 'installed_deployment_revision_r4')
    monkeypatch.setitem(sys.modules, 'cochem_pipeline.deployment_revision', installed_revision)
    monkeypatch.setattr(resource_limits, '__file__', str(R4 / '.venv/Lib/site-packages/cochem_pipeline/resource_limits.py'))
    monkeypatch.setattr(ramdisk, 'ordinary_tree', lambda *a: None)
    monkeypatch.setattr(m, 'sys', SimpleNamespace(base_prefix=str(m.BASE_PYTHON.parent), _base_executable=str(m.BASE_PYTHON),
                                                  version_info=(3, 12, 13), flags=SimpleNamespace(isolated=1), dont_write_bytecode=True))
    win = SimpleNamespace(validate_code_path=lambda path: None)
    return m, win


def test_verify_r4_runtime_binds_the_real_r4_receipts_read_only(r4_bound):
    m, win = r4_bound
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in R4.iterdir() if p.is_file()}
    revision = m.verify_r4_runtime(win, m.INSTALL_RECEIPT_SHA256)
    assert revision['verified'] is True and revision['files'] == 109 and revision['source_sha256'] == m.REVISION_SHA256
    assert {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in R4.iterdir() if p.is_file()} == before


@pytest.mark.parametrize('change', ['r3_root', 'receipt_pin', 'repair_pin', 'previous_manifest'])
def test_verify_r4_runtime_refuses_other_bindings(r4_bound, monkeypatch, change):
    m, win = r4_bound
    pin = m.INSTALL_RECEIPT_SHA256
    if change == 'r3_root':
        if not (R3 / 'install-after.json').exists():
            pytest.skip('the r3 runtime is not installed on this host')
        monkeypatch.setattr(m, 'INSTALL', R3)
        monkeypatch.setattr(m, 'PYTHON', R3 / '.venv/Scripts/python.exe')
    if change == 'receipt_pin':
        pin = '0' * 64
    if change == 'repair_pin':
        monkeypatch.setattr(m, 'REPAIR_SHA256', 'f' * 64)
    if change == 'previous_manifest':
        monkeypatch.setattr(m, 'PREVIOUS_MANIFEST_SHA256', 'e' * 64)
    with pytest.raises(ValueError):
        m.verify_r4_runtime(win, pin)


def run_fixture(tmp_path, monkeypatch, provider, stdout, stderr, exit_code, stage='before', poll=None, seconds=None, root_name=None):
    """Actual helper run, real bounded temporary output and receipt writes; native custody/launch simulated."""
    if not (R4 / 'pipeline.json').exists():
        pytest.skip('the r4 runtime is not installed on this host')
    from cochem_pipeline import windows as win
    from cochem_pipeline import ramdisk
    m = module(PY, f'status_run_{provider}_{stage}')
    base = tmp_path / 'protected-fixture'
    base.mkdir()
    root = base / (root_name or f'{m.ROOT_PREFIX}{ATTEMPT}-slot1-{provider}-{stage}')
    root.mkdir()
    copied = root / PY.name
    copied.write_bytes(PY.read_bytes())
    private = tmp_path / 'private'
    private.mkdir()
    config = json.loads((R4 / 'pipeline.json').read_bytes())
    layout = json.loads((R4 / 'windows-layout.json').read_bytes())
    config['private_root'] = layout['private_root'] = str(private)
    original_path = Path
    monkeypatch.setattr(m, 'Path', lambda x: base if str(x) == r'C:\Program Files\CoChem' else original_path(x))
    monkeypatch.setattr(m, '__file__', str(copied))
    monkeypatch.setattr(m, 'sys', SimpleNamespace(executable=str(m.PYTHON)))
    monkeypatch.setattr(m, 'validate_interpreter', lambda: None)
    monkeypatch.setattr(m, 'verify_r4_runtime', lambda *a: {'verified': True, 'source_sha256': m.REVISION_SHA256})
    monkeypatch.setattr(m, 'protected_json', lambda _, p: (layout, m.LAYOUT_SHA256) if p.name == 'windows-layout.json' else (config, m.CONFIG_SHA256))
    if seconds is not None:
        monkeypatch.setattr(m, 'STATUS_SECONDS', seconds)

    def digest(p):
        if p == Path(win.__file__):
            return m.WINDOWS_SHA256
        if p.name == m.NATIVE_EXECUTABLES[provider]:
            return m.CONTRACTS[provider]['sha256']
        return hashlib.sha256(p.read_bytes()).hexdigest()
    monkeypatch.setattr(m, 'digest_file', digest)
    for name in ('require_system', 'validate_code_path', 'validate_private_directory', '_validate_control_ancestors', '_validate_boundary'):
        monkeypatch.setattr(win, name, lambda *a, **kw: None)
    monkeypatch.setattr(ramdisk, 'ordinary_tree', lambda *a: None)
    monkeypatch.setattr(win, '_api', lambda: {'kernel32': SimpleNamespace(CreateMutexW=lambda *a: 17)})
    monkeypatch.setattr(win, '_check', lambda value, *a: value)
    monkeypatch.setattr(win, '_close', lambda *a: None)
    monkeypatch.setattr(win, '_account_sid', lambda *a: layout['slots']['slot1']['sid'])
    monkeypatch.setattr(win, '_sid_text', lambda x: x)
    monkeypatch.setattr(win, '_layout_paths', lambda p, *a: (p, {}))
    monkeypatch.setattr(win, '_layout_boundaries', lambda *a: [tmp_path / 'boundary'])
    stopped = []
    monkeypatch.setattr(m, 'require_stopped', lambda *a: stopped.append(True))
    calls = []

    @contextmanager
    def launch(_win, identity, argv, cwd, empty, output, errors, limits, report):
        calls.append({'argv': argv, 'cwd': cwd, 'identity': identity.name, 'stdin_empty': empty.tell() == 0 and empty.read() == b''})
        output.write(stdout)
        output.flush()
        errors.write(stderr)
        errors.flush()
        yield SimpleNamespace(resource_limits_evidence={'fixture': True}, poll=poll or (lambda: exit_code))
    monkeypatch.setattr(m, 'launch_status_process', launch)
    monkeypatch.setattr(m, 'observe_child', lambda *a: {'token_matches_selected_worker': True, 'image_matches_reviewed_executable': True,
                                                        'owned_job_membership_verified': True})
    return m, root, calls, stopped, layout


@pytest.mark.parametrize('stage', ['before', 'after'])
@pytest.mark.parametrize('kind', ['reuse', 'missing', 'error_envelope', 'empty', 'email', 'oversize', 'timeout'])
def test_full_gemini_run_writes_one_receipt_with_one_native_command(tmp_path, monkeypatch, stage, kind):
    stdout, stderr, code, poll, seconds = {
        'reuse': (CAPTURED, FETCH, 0, None, None),
        'missing': (b'', SIGN_IN, 1, None, None),
        'error_envelope': (envelope('ERROR'), FETCH, 0, None, None),
        'empty': (b'', FETCH, 0, None, None),
        'email': (CAPTURED, FETCH + (EMAIL + '\n').encode(), 0, None, None),
        'oversize': (CAPTURED * 30, FETCH, 0, None, None),
        'timeout': (b'', FETCH, None, (lambda: None), 0.3)}[kind]
    m, root, calls, stopped, layout = run_fixture(tmp_path, monkeypatch, 'gemini', stdout, stderr, code, stage, poll, seconds)
    result = m.run('slot1', 'gemini', NONCE, stage, ATTEMPT)
    raw = (root / 'worker-native-status.json').read_text(encoding='utf-8')
    report = json.loads(raw)
    expected = {'reuse': 'REUSE_VERIFIED_SESSION', 'missing': 'ATTENDED_LOGIN_REQUIRED', 'error_envelope': 'ATTENDED_LOGIN_REQUIRED'}.get(kind, 'HOLD')
    assert report['decision'] == expected and result == (2 if expected == 'HOLD' else 0)
    assert calls == [{'argv': [str(m.NATIVE / 'agy.exe'), '--output-format', 'json', 'models'], 'cwd': layout['slots']['slot1']['root'],
                      'identity': layout['slots']['slot1']['identity'], 'stdin_empty': True}]
    assert report['provider'] == 'gemini' and report['stage'] == stage and report['attempt'] == ATTEMPT and report['nonce'] == NONCE
    assert report['runtime_root'] == str(R4) and report['install_receipt_sha256'] == m.INSTALL_RECEIPT_SHA256
    assert report['native_version_at_reviewed_pin'] == '1.3.1' and report['native_status_commands_executed'] == 1
    assert report['native_model_jobs_executed'] == 0 and report['login_commands_executed'] == 0
    assert report['raw_status_published'] is False and report['provider_account_identity_verified'] is False
    assert report['helper_sha256'] == hashlib.sha256(PY.read_bytes()).hexdigest()
    for fragment in (EMAIL, 'example.invalid', 'Please sign in', 'gemini-3', 'Fetching'):
        assert fragment not in raw
    if kind in ('reuse', 'missing', 'error_envelope', 'empty', 'email'):
        assert report['status'] == ('NATIVE_SUBSCRIPTION_AUTHENTICATION_VERIFIED' if kind == 'reuse' else 'AUTHENTICATION_NOT_VERIFIED')
        assert report['cleanup_verified'] is True and report['daemon_states_verified_before_and_after'] is True and len(stopped) == 1
        assert report['native_executable_sha256_before'] == report['native_executable_sha256_after'] == m.CONTRACTS['gemini']['sha256']
        assert report['native_exit_code'] == code and report['output_bytes'] == {'stdout': len(stdout), 'stderr': len(stderr)}
        assert report['authentication']['auth_kind'] == {'reuse': 'google', 'missing': 'none', 'error_envelope': 'none'}.get(kind, 'unverified')
    else:
        assert report['status'] == 'STATUS_CHECK_FAILED' and report['operator_review_required'] is True
        assert report['failure_kind'] == ('timeout' if kind == 'timeout' else 'verification_failed')
        assert report['failure']['phase'] == 'native_wait' and 'authentication' not in report


@pytest.mark.parametrize('provider,stdout,code,expected', [
    ('codex', b'Logged in using ChatGPT', 0, 'REUSE_VERIFIED_SESSION'), ('codex', b'Not logged in', 1, 'ATTENDED_LOGIN_REQUIRED'),
    ('claude', json.dumps({'loggedIn': True, 'authMethod': 'claude.ai', 'apiProvider': 'firstParty', 'subscriptionType': 'max'}).encode(), 0, 'REUSE_VERIFIED_SESSION')])
def test_full_run_keeps_the_codex_and_claude_contracts(tmp_path, monkeypatch, provider, stdout, code, expected):
    m, root, calls, stopped, layout = run_fixture(tmp_path, monkeypatch, provider, stdout, b'', code)
    assert m.run('slot1', provider, NONCE, 'before', ATTEMPT) == 0
    report = json.loads((root / 'worker-native-status.json').read_bytes())
    assert report['decision'] == expected and calls[0]['argv'] == [str(m.NATIVE / (provider + '.exe')), *m.CONTRACTS[provider]['arguments']]


def test_r3_root_name_is_refused_before_any_receipt(tmp_path, monkeypatch):
    r3_name = f'NativeAuthStatusSix4.2.7-windows-20261008-r3-v3-{ATTEMPT}-slot1-gemini-before'
    m, root, calls, stopped, layout = run_fixture(tmp_path, monkeypatch, 'gemini', CAPTURED, FETCH, 0, root_name=r3_name)
    with pytest.raises(ValueError, match='reviewed protected helper'):
        m.run('slot1', 'gemini', NONCE, 'before', ATTEMPT)
    assert calls == [] and stopped == [] and not (root / 'worker-native-status.json').exists()
    expected_root = root.parent / f'{m.ROOT_PREFIX}{ATTEMPT}-slot1-gemini-before'
    assert not expected_root.exists()


@pytest.mark.parametrize('attempt,slot,stage', [('0' * 32, 'slot1', 'before'), ('A' * 32, 'slot1', 'before'), (ATTEMPT, 'slot7', 'before'), (ATTEMPT, 'slot1', 'during')])
def test_run_refuses_unreviewed_arguments_before_importing_windows(attempt, slot, stage):
    with pytest.raises(ValueError):
        status.run(slot, 'gemini', NONCE, stage, attempt)


def test_main_accepts_gemini_and_never_prints_raw_failures(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['helper', '--slot', 'slot1', '--provider', 'gemini', '--nonce', NONCE, '--stage', 'before', '--attempt', ATTEMPT])
    m = module(PY, 'status_main')
    monkeypatch.setattr(m, 'run', lambda *a: (_ for _ in ()).throw(RuntimeError(EMAIL)))
    assert m.main() == 3
    err = capsys.readouterr().err
    assert json.loads(err)['status'] == 'PRE_RECEIPT_FAILURE' and EMAIL not in err
