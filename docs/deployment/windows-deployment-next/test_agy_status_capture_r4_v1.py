"""Tests for build-manifest step 2: agy_status_capture_r4_v1.py and agy-status-capture-r4-v1.ps1.

Inert: no SYSTEM API, no task, no agy launch and no write under Program Files. The Python helper
runs end to end with the Windows launch boundary replaced by fake processes (a fake clock makes
the 20 s windows and 30 s bounds instant); the receipts it writes are then fed to the wrapper's
own functions, dot-sourced from its AST into a throwaway powershell.exe and driven with COM
stubs. One test observes a real, harmless sort.exe child through observe_child (running and
exited). Two whole-script runs exercise the unelevated read-only plans, which must create
nothing; the -Apply refusal is exercised through the dot-sourced main function only. The tests at the end run the
documented sitting calls' plans through ps_toplevel_smoke.py (stubbed host).
"""
import ctypes as C
import hashlib
import importlib.util
import json
import msvcrt
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

import ps_toplevel_smoke as smoke

ROOT = Path(__file__).parent
PY = ROOT / 'agy_status_capture_r4_v1.py'
SCRIPT = ROOT / 'agy-status-capture-r4-v1.ps1'
V22 = ROOT / 'retarget-warden-r4.ps1'
V22_SHA256 = '8ee6b412f6be176dfac7c2c1b2340f1973e08358c7d22da6d4515e79f0327a4e'
REGISTER = ROOT / 'register-stopped-warden-r3.ps1'
CHECK_R3 = ROOT / 'check-worker-native-status-r3.ps1'
COPY_HELPER = Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1')
INSPECTION = ROOT / 'protected-code-inspection-v4.ps1'
COCHEM = Path(r'C:\Program Files\CoChem')
R4 = COCHEM / 'Pipeline4.2.7-windows-20261009-r4'
PS = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
CAPTURES = Path(r'C:\Users\ansac\AppData\Local\Temp\claude\D----CoChem-GitHub-Repo\37810cc2-dc2b-49b8-bf45-25697101c0f0\scratchpad\gemini-design\captures')
ATTEMPT = 'c' * 32
NONCE = 'd' * 32
EMAIL = b'private@example.invalid'
FETCH = b'Fetching available models...\n'
SIGN_IN = b'Please sign in to view available models. Launch the CLI without arguments to sign in.\n'
MODELS = [('gemini-3.8-flash-high', 'Gemini 3.8 Flash (High)'), ('gemini-3.8-flash-medium', 'Gemini 3.8 Flash (Medium)'),
          ('gemini-3.8-flash-low', 'Gemini 3.8 Flash (Low)'), ('gemini-3.7-flash-high', 'Gemini 3.7 Flash (High)'),
          ('gemini-3.7-flash-medium', 'Gemini 3.7 Flash (Medium)'), ('gemini-3.7-flash-low', 'Gemini 3.7 Flash (Low)'),
          ('gemini-3.6-flash-high', 'Gemini 3.6 Flash (High)'), ('gemini-3.6-flash-medium', 'Gemini 3.6 Flash (Medium)'),
          ('gemini-3.6-flash-low', 'Gemini 3.6 Flash (Low)'), ('gemini-3.1-pro-high', 'Gemini 3.1 Pro (High)'),
          ('gemini-3.1-pro-low', 'Gemini 3.1 Pro (Low)'), ('claude-opus-5-5-low', 'Claude Opus 5.5 (Low)'),
          ('claude-opus-5-5-medium', 'Claude Opus 5.5 (Medium)'), ('claude-opus-5-5-high', 'Claude Opus 5.5 (High)'),
          ('claude-sonnet-5-5-low', 'Claude Sonnet 5.5 (Low)'), ('claude-sonnet-5-5-medium', 'Claude Sonnet 5.5 (Medium)'),
          ('claude-sonnet-5-5-high', 'Claude Sonnet 5.5 (High)'), ('gpt-oss-120b-medium', 'GPT-OSS 120B (Medium)')]
USAGE = {'input_tokens': 0, 'output_tokens': 0, 'thinking_tokens': 0, 'cache_read_tokens': 0, 'total_tokens': 0}


def load():
    spec = importlib.util.spec_from_file_location('agy_status_capture_r4_v1', PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = load()


def envelope(name, data, status='SUCCESS', response=''):
    value = {'conversation_id': '', 'status': status, 'response': response, 'duration_seconds': 0, 'num_turns': 0,
             'usage': USAGE, 'command': {'name': name, 'data': data}}
    return json.dumps(value, separators=(',', ':')).encode()


SUCCESS_MODELS = envelope('models', {'models': [{'id': i, 'label': label} for i, label in MODELS]},
                          response=''.join(f'{i}\t{label}\n' for i, label in MODELS))
ERROR_ENVELOPE = b'{"conversation_id":"","status":"ERROR","response":"","error":"authentication required","duration_seconds":0,"num_turns":0}\n'
URL_LINES = (b'Starting OAuth authentication flow\nPlease visit the following URL to authorize the application:\n'
             b'\x1b[1mhttps://accounts.google.com/o/oauth2/auth?client_id=SECRETCLIENT&redirect_uri=https%3A%2F%2Fantigravity.google%2Foauth-callback&state=SECRETSTATE\x1b[0m\n'
             b'Or, paste the authorization code here and press Enter:\n')
NO_TERMINAL = b"Print mode: not logged in and no controlling terminal; cannot complete interactive login\nError: authentication required. Run 'agy' to log in.\n"
DOCS_LINK = b"Error: authentication required. Run 'agy' to log in. See https://antigravity.google/docs/cli for help.\n"


# ---------------------------------------------------------------- fakes

class FakeTime:
    """Instant clock: sleep advances monotonic time, so 20/30 s bounds run in milliseconds."""
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def time(self):
        return 1760000000.0 + self.now


def pipe_state(fd):
    kernel32 = C.WinDLL('kernel32', use_last_error=True)
    peek = kernel32.PeekNamedPipe
    peek.argtypes = [C.c_void_p, C.c_void_p, C.c_uint32, C.c_void_p, C.POINTER(C.c_uint32), C.c_void_p]
    peek.restype = C.c_int32
    available = C.c_uint32()
    if peek(msvcrt.get_osfhandle(fd), None, 0, None, C.byref(available), None):
        return ('open', available.value)
    return ('closed', C.get_last_error())


class FakeProcess:
    def __init__(self, script, stdin, output, errors, profile):
        self.script, self.closed, self.polls, self.pipe_states = script, False, 0, []
        self.resource_limits_evidence = {'fixture': True}
        self.stdin_fd = os.dup(stdin.fileno())
        output.write(script.get('stdout', b''))
        output.flush()
        errors.write(script.get('stderr', b''))
        errors.flush()
        for relative, data in script.get('writes', {}).items():
            path = profile / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def poll(self):
        self.polls += 1
        if self.polls == 2:
            self.pipe_states.append(pipe_state(self.stdin_fd))
        return self.script.get('code')

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def launcher(scripts, profile, launched):
    def launch(win, identity, argv, cwd, stdin, output, errors, limits):
        process = FakeProcess(scripts[tuple(argv[1:])], stdin, output, errors, profile)
        launched.append(SimpleNamespace(argv=argv, cwd=cwd, process=process, limits=limits))
        return process
    return launch


def attestation(profile):
    return {'pid': 4242, 'creation_time_filetime': 1, 'token_sid': 'S-1-5-21-fixture', 'token_matches_selected_worker': True,
            'image_matches_reviewed_executable': True, 'owned_job_membership_verified': True, 'image_query_format': 'win32',
            'profile_directory_sha256': hashlib.sha256(str(profile).casefold().encode()).hexdigest(), 'source': 'fixture'}


def signed_out_scripts(variant='print'):
    scripts = {
        ('--version',): {'stdout': b'1.3.1\n', 'code': 0},
        ('--output-format', 'json', 'models'): {'stderr': FETCH + SIGN_IN, 'code': 1,
                                                'writes': {'.gemini/antigravity-cli/installation_id': b'fixture-installation'}},
        ('models',): {'stdout': SIGN_IN, 'stderr': FETCH, 'code': 1},
        ('-p', '/model'): {'stderr': URL_LINES, 'code': None},
        ('-p', '/usage'): {'stderr': b"Error: authentication required. Run 'agy' to log in.\n", 'code': 1},
        ('--output-format', 'json', '-p', '/usage'): {'stdout': ERROR_ENVELOPE, 'code': 1},
        (): {'stdout': b'\x1b[?25l\x1b[2J Select login method:\r\n ' + EMAIL + b'\r\n', 'code': None},
        ('--output-format', 'json', 'agents'): {'stdout': envelope('agents', {'agents': []}), 'code': 0},
        ('agents',): {'stdout': b'', 'code': 0},
    }
    if variant in ('none', 'tui'):
        scripts[('-p', '/model')] = {'stderr': NO_TERMINAL, 'code': 1}
    if variant == 'none':
        scripts[()] = {'stderr': b'bubbletea: error restoring console: The handle is invalid.\n', 'code': 1}
    if variant == 'tui':
        scripts[()] = {'stdout': b'\x1b[2J' + URL_LINES.replace(b'\n', b'\r\n'), 'code': None}
    if variant == 'version':
        scripts[('--version',)] = {'stdout': b'1.3.2\n', 'code': 0}
    if variant == 'docs':
        # The wave-1 failure scenario: P3 fails fast with a docs link (no 'no controlling terminal' phrase), P6 likewise.
        scripts[('-p', '/model')] = {'stderr': DOCS_LINK, 'code': 1}
        scripts[()] = {'stderr': b'bubbletea: error restoring console. See https://antigravity.google/docs/troubleshooting\n', 'code': 1}
    return scripts


def signed_in_scripts():
    return {
        ('--version',): {'stdout': b'1.3.1\n', 'code': 0},
        ('--output-format', 'json', 'models'): {'stdout': SUCCESS_MODELS, 'stderr': FETCH, 'code': 0},
        ('models',): {'stdout': ''.join(f'{i}\t{label}\n' for i, label in MODELS).encode(), 'stderr': FETCH, 'code': 0},
        ('--output-format', 'json', 'agents'): {'stdout': envelope('agents', {'agents': ['cochem-audit', 'flutter_a11y_agent']}), 'code': 0},
        ('agents',): {'stdout': b'cochem-audit\nflutter_a11y_agent\n', 'code': 0},
        ('-p', '/model'): {'stdout': b'gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n', 'code': 0},
        ('-p', '/usage'): {'stdout': b'Account: ' + EMAIL + b'\nPlan usage: 0%\n', 'code': 0},
        ('--output-format', 'json', '-p', '/usage'): {'stdout': envelope('usage', {}), 'code': 0},
    }


def produce(base, stage, scripts, monkey, deadline=None):
    """Run the real helper once with the Windows launch boundary replaced by fakes."""
    from cochem_pipeline import windows as win
    from cochem_pipeline import ramdisk
    if not (R4 / 'pipeline.json').exists():
        pytest.skip('the r4 runtime configuration is not readable on this host')
    module = load()
    capture_base = base / 'protected'
    capture_base.mkdir(parents=True)
    root = capture_base / f'{module.ROOT_PREFIX}{ATTEMPT}-slot1-{stage}'
    root.mkdir()
    copied = root / module.HELPER_NAME
    copied.write_bytes(PY.read_bytes())
    users = base / 'Users'
    profile = users / 'CoChem422Worker1'
    (profile / '.gemini' / 'antigravity-cli').mkdir(parents=True)
    (profile / '.gemini' / 'antigravity-cli' / 'cli.log').write_bytes(b'existing log\n')
    if stage == 'signed-in':
        (profile / '.gemini' / 'antigravity-cli' / 'antigravity-oauth-token').write_bytes(b'SECRET-TOKEN-VALUE')
    config = json.loads((R4 / 'pipeline.json').read_bytes())
    layout = json.loads((R4 / 'windows-layout.json').read_bytes())
    private = base / 'private'
    private.mkdir()
    config['private_root'] = layout['private_root'] = str(private)
    monkey.setattr(module, 'CAPTURE_BASE', capture_base)
    monkey.setattr(module, 'PROFILE_PARENT', users)
    monkey.setattr(module, '__file__', str(copied))
    monkey.setattr(module, 'current_executable', lambda: module.PYTHON)
    monkey.setattr(module, 'validate_interpreter', lambda: None)
    monkey.setattr(module, 'verify_r4_runtime', lambda *a: {'verified': True, 'files': 109, 'source_sha256': module.REVISION_SHA256})
    monkey.setattr(module, 'protected_json', lambda _, p: (layout, module.LAYOUT_SHA256) if p.name == 'windows-layout.json' else (config, module.CONFIG_SHA256))
    original = module.digest_file

    def digest(path, maximum=1024 * 1024 * 1024):
        if Path(path) == Path(win.__file__):
            return module.WINDOWS_SHA256
        if Path(path) == module.EXECUTABLE:
            return module.AGY_SHA256
        return original(Path(path), maximum)
    monkey.setattr(module, 'digest_file', digest)
    for name in ('require_system', 'validate_code_path', 'validate_private_directory', '_validate_control_ancestors', '_validate_boundary'):
        monkey.setattr(win, name, lambda *a, **k: None)
    monkey.setattr(ramdisk, 'ordinary_tree', lambda *a: None)
    monkey.setattr(win, '_api', lambda: {'kernel32': SimpleNamespace(CreateMutexW=lambda *a: 17)})
    monkey.setattr(win, '_check', lambda value, *a: value)
    monkey.setattr(win, '_close', lambda *a: None)
    monkey.setattr(win, '_account_sid', lambda *a: layout['slots']['slot1']['sid'])
    monkey.setattr(win, '_sid_text', lambda x: x)
    monkey.setattr(win, '_layout_paths', lambda p, *a: (p, {}))
    monkey.setattr(win, '_layout_boundaries', lambda *a: [base / 'boundary'])
    stops = []
    monkey.setattr(module, 'require_stopped', lambda *a: stops.append('stop'))
    monkey.setattr(module, 'observe_child', lambda *a: attestation(profile))
    monkey.setattr(module, 'time', FakeTime())
    if deadline is not None:
        monkey.setattr(module, 'CAPTURE_DEADLINE_SECONDS', deadline)
    launched = []
    monkey.setattr(module, 'launch_probe_process', launcher(scripts, profile, launched))
    code = module.run('slot1', stage, NONCE, ATTEMPT)
    for item in launched:
        os.close(item.process.stdin_fd)
    receipt_text = (root / 'capture-receipt.json').read_text(encoding='ascii')
    return SimpleNamespace(module=module, root=root, profile=profile, code=code, launched=launched, stops=stops,
                           receipt=json.loads(receipt_text), receipt_text=receipt_text, layout=layout)


@pytest.fixture(scope='module')
def produced(tmp_path_factory):
    """Real helper receipts for the PowerShell fixtures (signed-out print/none/tui, signed-in, failed)."""
    base = tmp_path_factory.mktemp('agy-capture')
    result = {}
    for name, stage, scripts in (('print', 'signed-out', signed_out_scripts('print')), ('none', 'signed-out', signed_out_scripts('none')),
                                 ('tui', 'signed-out', signed_out_scripts('tui')), ('signed_in', 'signed-in', signed_in_scripts()),
                                 ('failed', 'signed-out', signed_out_scripts('version')), ('docs', 'signed-out', signed_out_scripts('docs'))):
        with pytest.MonkeyPatch.context() as monkey:
            result[name] = produce(base / name, stage, scripts, monkey)
    return result


# ---------------------------------------------------------------- probe table, pins

def test_probe_table_order_and_stdin_modes():
    assert [(probe, mode) for probe, mode in m.STAGE_PROBES['signed-out']] == [
        ('P1', 'empty_file'), ('P2', 'empty_file'), ('P2b', 'empty_file'), ('P3', 'held_open_pipe'), ('P4', 'empty_file'),
        ('P5', 'empty_file'), ('P6', 'held_open_pipe'), ('P7', 'empty_file'), ('P8', 'empty_file')]
    assert list(m.STAGE_PROBES['signed-in']) == [('P1', 'empty_file'), ('P2', 'empty_file'), ('P2b', 'empty_file'), ('P7', 'empty_file'),
                                                 ('P8', 'empty_file'), ('P3', 'empty_file'), ('P4', 'empty_file'), ('P5', 'empty_file')]
    assert {k: v['arguments'] for k, v in m.PROBES.items()} == {
        'P1': ('--version',), 'P2': ('--output-format', 'json', 'models'), 'P2b': ('models',), 'P3': ('-p', '/model'),
        'P4': ('-p', '/usage'), 'P5': ('--output-format', 'json', '-p', '/usage'), 'P6': (), 'P7': ('--output-format', 'json', 'agents'),
        'P8': ('agents',)}
    assert m.EXECUTABLE == Path(r'C:\Program Files\CoChem\Native4.2.7-windows-20261006\agy.exe')
    assert (m.PROBE_SECONDS, m.WINDOW_SECONDS, m.MAX_OUTPUT) == (30, 20, 65536)
    assert m.ROOT_PREFIX == 'AgyCapture4.2.7-windows-20261010-r4-v1-' and m.SLOTS == ('slot1',)
    assert m.DAEMON_TASK_NAMES == ('CoChem-4.2.7-Warden', 'CoChem-4.2.7-Supervisor', 'CoChem-4.2.2-Warden', 'CoChem-4.2.3-Supervisor')
    # The worst case of every probe plus its close allowance fits the helper deadline, inside the PT5M task limit.
    worst = sum((m.WINDOW_SECONDS if mode == m.PIPE else m.PROBE_SECONDS) + m.PROBE_CLEANUP_MARGIN_SECONDS for _, mode in m.STAGE_PROBES['signed-in'])
    assert m.CAPTURE_DEADLINE_SECONDS + 45 <= 300 and worst > m.CAPTURE_DEADLINE_SECONDS, 'the deadline guard is needed and leaves the receipt time'


def test_module_pins_equal_the_files_on_disk():
    pairs = {R4 / 'install-after.json': m.INSTALL_RECEIPT_SHA256, R4 / 'source-manifest.json': m.MANIFEST_SHA256,
             R4 / 'pipeline.json': m.CONFIG_SHA256, R4 / 'windows-layout.json': m.LAYOUT_SHA256,
             R4 / '.venv' / 'Scripts' / 'python.exe': m.PYTHON_SHA256, R4 / '.venv' / 'pyvenv.cfg': m.VENV_CONFIG_SHA256,
             R4 / '.venv' / 'Lib' / 'site-packages' / 'cochem_pipeline' / 'windows.py': m.WINDOWS_SHA256,
             R4 / '.venv' / 'Lib' / 'site-packages' / 'cochem_pipeline' / 'resource_limits.py': m.RESOURCE_SHA256,
             R4 / '.venv' / 'Lib' / 'site-packages' / 'cochem_pipeline' / 'resource_telemetry.py': m.REPAIR_SHA256,
             m.BASE_PYTHON: m.BASE_PYTHON_SHA256, m.EXECUTABLE: m.AGY_SHA256}
    if not R4.exists():
        pytest.skip('r4 runtime absent')
    for path, pin in pairs.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == pin, path


def test_install_after_and_manifest_bindings_accept_the_real_r4_receipts():
    if not R4.exists():
        pytest.skip('r4 runtime absent')
    installed = json.loads((R4 / 'install-after.json').read_bytes().decode('utf-8-sig'))
    assert m.check_install_after(installed)['revision']['source_sha256'] == m.REVISION_SHA256
    for key, value in (('preserved_denial_receipt_sha256', '0' * 64), ('previous_install_receipt_sha256', '0' * 64), ('source_files', 165),
                       ('reviewed_repair_sha256', '0' * 64), ('mode', 'OTHER'), ('configuration_unchanged', 1)):
        bad = json.loads(json.dumps(installed))
        bad[key] = value
        with pytest.raises(ValueError):
            m.check_install_after(bad)
    manifest = json.loads((R4 / 'source-manifest.json').read_bytes().decode('utf-8-sig'))
    reads = []
    m.verify_r4_source(manifest, lambda path, pin, length: reads.append(path))
    assert len(reads) == 166 and all(m.INSTALL / 'source' in path.parents for path in reads)
    bad = json.loads(json.dumps(manifest))
    bad['changes_from_previous_source']['changed'] = []
    with pytest.raises(ValueError):
        m.verify_r4_source(bad, lambda *a: None)


# ---------------------------------------------------------------- classification

def test_signed_in_envelope_classifies_logged_in_and_lists_only_slugs():
    value = m.classify('models_json', SUCCESS_MODELS, FETCH, 'exited', 0, False)
    assert value['json_envelope_parsed'] and value['status_value'] == 'SUCCESS' and value['command_name'] == 'models'
    assert value['models_count'] == 18 and value['gemini_row_present'] and value['stderr_only_fetching_line']
    assert value['status_helper_classification'] == 'LOGGED_IN' and value['model_ids'][0] == 'gemini-3.8-flash-high'
    assert not value['url_present'] and not value['sign_in_line_present'] and value['envelope_keys'] == sorted(json.loads(SUCCESS_MODELS))
    text = m.classify('models_text', ''.join(f'{i}\t{label}\n' for i, label in MODELS).encode(), FETCH, 'exited', 0, False)
    assert text['models_rows'] == 18 and text['gemini_row_present'] and text['exact_line_fallback_present']


def test_captured_owner_envelope_classifies_logged_in_when_present():
    stdout = CAPTURES / 'models_json_pre.stdout.txt'
    if not stdout.exists() or hashlib.sha256(stdout.read_bytes()).hexdigest() != '1613d351fed8acd4db9342a3386585edcb7664b52c6294f637b69821919cd81d':
        pytest.skip('the 2269-byte owner capture is not available')
    stderr = (CAPTURES / 'models_json_pre.stderr.txt').read_bytes()
    value = m.classify('models_json', stdout.read_bytes(), stderr, 'exited', 0, False)
    assert value['status_helper_classification'] == 'LOGGED_IN' and value['models_count'] == 18 and value['gemini_row_present']


@pytest.mark.parametrize('stdout,stderr,code,completed,expected', [
    (SUCCESS_MODELS, FETCH, 0, True, 'LOGGED_IN'),
    (SUCCESS_MODELS, b'', 0, True, 'LOGGED_IN'),
    (ERROR_ENVELOPE, b'', 1, True, 'LOGGED_OUT'),
    (ERROR_ENVELOPE, b'', 0, True, 'LOGGED_OUT'),
    (b'', SIGN_IN, 0, True, 'LOGGED_OUT'),
    (SIGN_IN, b'', 1, True, 'LOGGED_OUT'),
    (b'', SIGN_IN, 2, True, 'LOGGED_OUT'),
    (b'', b"Error: authentication required. Run 'agy' to log in.\n", 0, True, 'LOGGED_OUT'),
    (b'', b'You are not logged into Antigravity.\n', 0, True, 'LOGGED_OUT'),
    (b'', b'', 0, True, 'HOLD'),
    (SUCCESS_MODELS, FETCH + EMAIL + b'\n', 0, True, 'HOLD'),
    (envelope('models', {'models': [{'id': 'claude-opus-5-5-high', 'label': 'x'}]}), FETCH, 0, True, 'HOLD'),
    (b'x' * 70000, b'', 0, True, 'HOLD'),
    (SUCCESS_MODELS, FETCH, 0, False, 'HOLD'),
    (b'\xff\xfe', b'', 1, True, 'HOLD'),
    (SUCCESS_MODELS, FETCH, 'terminated', True, 'HOLD'),
], ids=['success', 'success-empty-stderr', 'error-envelope-exit1', 'error-envelope-exit0', 'sign-in-stderr-exit0', 'sign-in-stdout-exit1',
        'sign-in-exit2', 'auth-required', 'not-logged-in', 'empty-exit0', 'extra-stderr-line', 'no-gemini-id', 'oversize', 'timeout',
        'undecodable', 'terminated'])
def test_status_helper_predicate_table(stdout, stderr, code, completed, expected):
    assert m.status_helper_predicate(stdout, stderr, code, completed) == expected


def test_url_host_extraction_never_stores_path_query_or_userinfo():
    text = (URL_LINES + b'https://user:SECRETPASS@Example.COM:8443/x?y=SECRETQ\nhttp://localhost:4567/auth/callback\n'
            b'https://bad_host!/x?SECRETBAD\n')
    value = m.classify('bare', b'', text, 'window_elapsed_terminated', 'terminated', True)
    assert value['url_present'] and value['url_hosts'] == ['accounts.google.com', 'example.com', 'unparsed']
    dumped = json.dumps(value)
    for secret in ('SECRET', 'oauth2', 'client_id', 'localhost', 'callback', 'antigravity.google', '8443'):
        assert secret not in dumped
    assert value['paste_prompt_present'] and value['window_seconds'] == 20 and value['exited_before_window'] is False
    assert value['exit_code_before_window'] is None
    many = b''.join(b'https://h%d.example/q?SECRET\n' % i for i in range(20))
    assert len(m.classify('bare', many, b'', 'exited', 0, False)['url_hosts']) == m.MAX_HOSTS


@pytest.mark.parametrize('line,key,expected', [
    (b'Or, paste the authorization code here and press Enter:', 'paste_prompt_present', True),
    (b'Enter the authorization code:', 'paste_prompt_present', True),
    (b'Paste the authorization code below:', 'paste_prompt_present', True),
    (b'Enter the redirect URL (if redirect failed):', 'paste_prompt_present', True),
    (b'Successfully exchanged authorization code for token', 'paste_prompt_present', False),
    (b'Waiting for authentication (timeout 60s)...', 'waiting_line_present', True),
    (b'Print mode: not logged in and no controlling terminal; cannot complete interactive login', 'no_controlling_terminal_present', True),
    (b'You are not logged into Antigravity.', 'not_logged_in_present', True),
    (b"Error: authentication required. Run 'agy' to log in.", 'auth_required_present', True),
    (b'Authentication required. Please visit the URL to log in:', 'auth_required_present', False),
    (SIGN_IN.strip(), 'sign_in_line_present', True),
    (b'Please sign in to view available models.', 'sign_in_line_present', False),
])
def test_allowlisted_marker_strings(line, key, expected):
    for stream in ('stdout', 'stderr'):
        args = (line + b'\n', b'') if stream == 'stdout' else (b'', line + b'\n')
        value = m.classify('print_text', *args, 'exited', 1, False)
        assert value[key] is expected, (line, stream)
        assert line.decode() not in json.dumps(value)


def test_json_envelope_with_error_status_and_agents_lists():
    value = m.classify('print_json', ERROR_ENVELOPE, b'', 'exited', 1, False)
    assert value['json_envelope_parsed'] and value['status_value'] == 'ERROR' and value['command_name'] is None
    assert 'error' in value['envelope_keys'] and 'authentication required' not in json.dumps(value['envelope_keys'])
    odd = m.classify('print_json', b'{"status":"weird text"}', b'', 'exited', 0, False)
    assert odd['status_value'] == 'OTHER'
    agents = m.classify('agents_json', envelope('agents', {'agents': ['cochem-audit', 'has space', 'x' * 80]}), b'', 'exited', 0, False)
    assert agents['agents'] == ['cochem-audit'] and agents['agents_unlisted'] == 2 and agents['agents_count'] == 3
    plain = m.classify('agents_text', b'cochem-audit\nflutter_a11y_agent\n' + EMAIL + b'\n', b'', 'exited', 0, False)
    assert plain['agents'] == ['cochem-audit', 'flutter_a11y_agent'] and plain['agents_unlisted'] == 1
    assert EMAIL.decode() not in json.dumps(plain)
    version = m.classify('version', b'1.3.1\n', b'', 'exited', 0, False)
    assert version['version_matches'] and version['version_stdout_exact']
    assert not m.classify('version', b'1.3.2\n', b'', 'exited', 0, False)['version_matches']


GOOGLE = {'url_present': True, 'url_hosts': ['accounts.google.com']}
DOCS = {'url_present': True, 'url_hosts': ['antigravity.google']}
LOGIN_MODE_CASES = [
    (GOOGLE, {}, ('print', 'P3')),
    ({'paste_prompt_present': True}, GOOGLE, ('print', 'P3')),
    (dict(GOOGLE, no_controlling_terminal_present=True), GOOGLE, ('tui', 'P6')),
    ({}, {'paste_prompt_present': True}, ('tui', 'P6')),
    ({'no_controlling_terminal_present': True}, {}, ('none', None)),
    ({}, dict(GOOGLE, no_controlling_terminal_present=True), ('none', None)),
    ({'url_present': 1, 'url_hosts': ['accounts.google.com']}, {'paste_prompt_present': 'yes'}, ('none', None)),
    # Wave-1 low: only an https://accounts.google.com/ URL is sign-in evidence; a docs or help link on any other host is not.
    (DOCS, {}, ('none', None)),
    (DOCS, GOOGLE, ('tui', 'P6')),
    (DOCS, DOCS, ('none', None)),
    ({'url_present': True, 'url_hosts': ['antigravity.google', 'accounts.google.com']}, {}, ('print', 'P3')),
    ({'url_present': True, 'url_hosts': ['accounts.google.com.example.invalid']}, {}, ('none', None)),
    ({'url_present': True, 'url_hosts': ['unparsed']}, {}, ('none', None)),
    ({'url_present': True, 'url_hosts': ['ACCOUNTS.GOOGLE.COM']}, {}, ('none', None)),
    ({'url_present': False, 'url_hosts': ['accounts.google.com']}, {}, ('none', None)),
    (dict(DOCS, paste_prompt_present=True), {}, ('print', 'P3')),
]


def full_classification(value):
    base = {'url_present': False, 'url_hosts': [], 'paste_prompt_present': False, 'no_controlling_terminal_present': False}
    base.update(value)
    return base


@pytest.mark.parametrize('p3,p6,expected', LOGIN_MODE_CASES)
def test_login_mode_decision_table(p3, p6, expected):
    assert m.login_mode_decision(full_classification(p3), full_classification(p6)) == expected
    assert m.login_mode_decision(None, None) == ('none', None)
    assert m.login_mode_decision({'url_present': True, 'no_controlling_terminal_present': False}, None) == ('none', None), 'no url_hosts is no host'


def test_capture_gate_table():
    def p2(outcome='exited', code=1, timed=False, status='LOGGED_OUT', value='ERROR', name=None, gemini=False):
        return [{'id': 'P2', 'outcome': outcome, 'exit_code': code, 'classification': {
            'timed_out': timed, 'status_helper_classification': status, 'status_value': value, 'command_name': name, 'gemini_row_present': gemini}}]
    assert m.capture_gate('signed-out', 'CAPTURE_COMPLETE', p2(), 'print') == {'stage': 'signed-out', 'passed': True, 'reasons': []}
    assert m.capture_gate('signed-out', 'CAPTURE_COMPLETE', p2(), 'none')['reasons'] == ['LOGIN_MODE_NONE']
    assert m.capture_gate('signed-out', 'CAPTURE_COMPLETE', p2(outcome='timed_out_terminated', code='terminated', timed=True, status='HOLD'), 'tui')['reasons'] == [
        'P2_NOT_COMPLETED_WITHIN_BOUND', 'P2_NOT_LOGGED_OUT_UNDER_STATUS_PREDICATE']
    assert m.capture_gate('signed-out', 'CAPTURE_INCOMPLETE', p2(), 'print')['reasons'] == ['CAPTURE_NOT_COMPLETE']
    assert m.capture_gate('signed-in', 'CAPTURE_COMPLETE', p2(code=0, status='LOGGED_IN', value='SUCCESS', name='models', gemini=True), None)['passed']
    assert m.capture_gate('signed-in', 'CAPTURE_COMPLETE', p2(), None)['reasons'] == ['P2_EXIT_NOT_ZERO', 'P2_STATUS_NOT_SUCCESS', 'P2_COMMAND_NOT_MODELS', 'P2_NO_GEMINI_ROW']
    assert set(m.capture_gate('signed-in', 'CAPTURE_COMPLETE', [], None)['reasons']) <= set(m.REASONS)


# ---------------------------------------------------------------- one probe: pipe window, timeout, bound

def probe_harness(tmp_path, monkeypatch, script, profile_matches=True):
    module = load()
    monkeypatch.setattr(module, 'time', FakeTime())
    calls = []
    monkeypatch.setattr(module, 'require_stopped', lambda *a: calls.append('require_stopped'))
    profile = tmp_path / 'profile'
    attest = attestation(profile if profile_matches else tmp_path / 'other')
    monkeypatch.setattr(module, 'observe_child', lambda *a: dict(attest))
    launched = []

    def launch_worker(identity, argv, cwd, stdin, output, errors, limits=None):
        calls.append('launch')
        process = FakeProcess(script, stdin, output, errors, profile)
        launched.append(process)
        return process
    raw = tmp_path / 'raw'
    raw.mkdir()
    win = SimpleNamespace(launch_worker=launch_worker)
    sha = hashlib.sha256(str(profile).casefold().encode()).hexdigest()
    return module, win, raw, sha, calls, launched


def test_window_path_ends_the_fake_process_without_feeding_input(tmp_path, monkeypatch):
    module, win, raw, sha, calls, launched = probe_harness(tmp_path, monkeypatch, {'stderr': URL_LINES, 'code': None})
    record = {}
    module.run_probe(win, 'identity', 'P3', module.PIPE, str(tmp_path), raw, None, 'S-1-5-21-fixture', sha, record)
    process = launched[0]
    try:
        assert calls == ['require_stopped', 'launch'], 'the daemon check runs at the launch boundary'
        assert process.pipe_states[0] == ('open', 0), 'the stdin pipe is held open and empty during the window'
        assert pipe_state(process.stdin_fd) == ('closed', 109), 'after the Job close the writer is closed and nothing was ever written'
        assert process.closed and process.polls >= 400
    finally:
        os.close(process.stdin_fd)
    assert record['outcome'] == 'window_elapsed_terminated' and record['exit_code'] == 'terminated' and record['stdin_bytes_written'] == 0
    assert record['bound_seconds'] == 20 and 20000 <= record['elapsed_ms'] <= 20200 and record['cleanup_verified'] is True
    assert record['stdin_mode'] == 'held_open_pipe' and 'stdin_sha256' not in record
    value = record['classification']
    assert value['url_present'] and value['paste_prompt_present'] and value['exited_before_window'] is False and value['url_hosts'] == ['accounts.google.com']
    assert record['stderr'] == {'bytes': len(URL_LINES), 'sha256': hashlib.sha256(URL_LINES).hexdigest()}
    assert (raw / 'P3.stderr').read_bytes() == URL_LINES and record['raw_path'] == {'stdout': 'raw/P3.stdout', 'stderr': 'raw/P3.stderr'}
    assert 'SECRET' not in json.dumps(record)


def test_window_probe_that_exits_first_records_its_code(tmp_path, monkeypatch):
    module, win, raw, sha, calls, launched = probe_harness(tmp_path, monkeypatch, {'stderr': NO_TERMINAL, 'code': 1})
    record = module.run_probe(win, 'identity', 'P3', module.PIPE, str(tmp_path), raw, None, 'S', sha, {})
    os.close(launched[0].stdin_fd)
    assert record['outcome'] == 'exited' and record['exit_code'] == 1 and launched[0].closed
    value = record['classification']
    assert value['exited_before_window'] is True and value['exit_code_before_window'] == 1
    assert value['no_controlling_terminal_present'] and value['auth_required_present'] and not value['url_present']


def test_empty_file_probe_timeout_and_output_bound(tmp_path, monkeypatch):
    module, win, raw, sha, calls, launched = probe_harness(tmp_path, monkeypatch, {'stderr': FETCH, 'code': None})
    record = module.run_probe(win, 'identity', 'P2', module.EMPTY, str(tmp_path), raw, None, 'S', sha, {})
    assert record['outcome'] == 'timed_out_terminated' and record['exit_code'] == 'terminated' and 30000 <= record['elapsed_ms'] <= 30200
    assert record['stdin_sha256'] == hashlib.sha256(b'').hexdigest() and (raw / 'P2.stdin').read_bytes() == b''
    assert os.read(launched[0].stdin_fd, 10) == b'' and launched[0].closed
    os.close(launched[0].stdin_fd)
    assert record['classification']['timed_out'] and record['classification']['status_helper_classification'] == 'HOLD'
    second = tmp_path / 'b'
    second.mkdir()
    module, win, raw2, sha, calls, launched = probe_harness(second, monkeypatch, {'stdout': b'y' * 70000, 'code': None})
    record = module.run_probe(win, 'identity', 'P2b', module.EMPTY, str(tmp_path), raw2, None, 'S', sha, {})
    os.close(launched[0].stdin_fd)
    assert record['outcome'] == 'output_bound_terminated' and record['classification']['output_bound_exceeded'] and record['stdout']['bytes'] == 70000


def test_profile_mismatch_stops_the_probe_and_closes_the_job(tmp_path, monkeypatch):
    module, win, raw, sha, calls, launched = probe_harness(tmp_path, monkeypatch, {'stdout': b'1.3.1\n', 'code': 0}, profile_matches=False)
    record = {}
    with pytest.raises(ValueError, match='profile'):
        module.run_probe(win, 'identity', 'P1', module.EMPTY, str(tmp_path), raw, None, 'S', sha, record)
    os.close(launched[0].stdin_fd)
    assert launched[0].closed and record['cleanup_verified'] is False and 'outcome' not in record


def test_launch_boundary_checks_daemons_before_every_launch(monkeypatch):
    module = load()
    order = []
    monkeypatch.setattr(module, 'require_stopped', lambda win: order.append('require_stopped'))
    win = SimpleNamespace(launch_worker=lambda *a, **k: order.append(('launch', k['limits'])) or 'process')
    assert module.launch_probe_process(win, 'id', ['a'], 'cwd', 'i', 'o', 'e', 'limits') == 'process'
    assert order == ['require_stopped', ('launch', 'limits')]


# ---------------------------------------------------------------- inventory

def test_inventory_never_opens_token_files_and_reports_new_files(tmp_path, monkeypatch):
    module = load()
    profile = tmp_path / 'CoChem422Worker1'
    cli = profile / '.gemini' / 'antigravity-cli'
    cli.mkdir(parents=True)
    (cli / 'antigravity-oauth-token').write_bytes(b'SECRET-TOKEN-VALUE')
    (cli / 'cli.log').write_bytes(b'log ' + EMAIL)
    (cli / 'big.bin').write_bytes(b'z' * (module.INVENTORY_HASH_LIMIT + 1))
    (cli / 'tokens').mkdir()
    (cli / 'tokens' / 'cache.json').write_bytes(b'SECRET-IN-TOKEN-DIR')
    opened = []
    real_open = module.open_for_hash
    monkeypatch.setattr(module, 'open_for_hash', lambda path: opened.append(str(path)) or real_open(path))
    before = module.profile_inventory(profile)
    rows = {row['path']: row for row in before['trees']['.gemini']['entries']}
    token = rows['antigravity-cli/antigravity-oauth-token']
    assert token == {'path': 'antigravity-cli/antigravity-oauth-token', 'kind': 'file', 'size': 18, 'sha256': None, 'token_file': True}
    assert rows['antigravity-cli/tokens/cache.json']['token_file'] is True and rows['antigravity-cli/tokens/cache.json']['sha256'] is None
    assert rows['antigravity-cli/big.bin']['hash_skipped'] == 'over_1_mib' and rows['antigravity-cli/big.bin']['sha256'] is None
    assert rows['antigravity-cli/cli.log']['sha256'] == hashlib.sha256(b'log ' + EMAIL).hexdigest()
    assert not any('token' in path.casefold() for path in opened) and len(opened) == 1
    assert before['trees']['AppData/Local/agy'] == {'exists': False, 'reparse_point': False, 'entries': [], 'entry_count': 0, 'truncated': False}
    dumped = json.dumps(before)
    assert 'SECRET' not in dumped and EMAIL.decode() not in dumped
    (cli / 'installation_id').write_bytes(b'id')
    (cli / 'cli.log').write_bytes(b'log grew')
    (profile / 'AppData' / 'Local' / 'agy' / 'bin').mkdir(parents=True)
    (profile / 'AppData' / 'Local' / 'agy' / 'bin' / 'agy.exe').write_bytes(b'MZ')
    after = module.profile_inventory(profile)
    changes = module.inventory_changes(before, after)
    assert changes['new_files'] == [{'path': '.gemini/antigravity-cli/installation_id', 'size': 2, 'token_file': False},
                                    {'path': 'AppData/Local/agy/bin/agy.exe', 'size': 2, 'token_file': False}]
    assert changes['changed_files'] == ['.gemini/antigravity-cli/cli.log'] and changes['removed_files'] == []
    assert changes['new_directories'] == ['AppData/Local/agy/bin']


def test_inventory_bounds_entries_and_skips_reparse_points(tmp_path, monkeypatch):
    module = load()
    monkeypatch.setattr(module, 'MAX_TREE_ENTRIES', 5)
    tree = tmp_path / '.gemini'
    tree.mkdir()
    for i in range(9):
        (tree / f'f{i}').write_bytes(b'x')
    value = module.inventory_tree(tree)
    assert value['truncated'] is True and value['entry_count'] == 5
    import _winapi
    target = tmp_path / 'elsewhere'
    target.mkdir()
    (target / 'secret.txt').write_bytes(b'outside')
    holder = tmp_path / 'j'
    holder.mkdir()
    _winapi.CreateJunction(str(target), str(holder / 'link'))
    assert module.inventory_tree(holder)['entries'] == [{'path': 'link', 'kind': 'reparse_point'}], 'a junction is listed, never followed'
    assert module.inventory_tree(holder / 'link')['reparse_point'] is True and module.inventory_tree(holder / 'link')['entries'] == []


def test_receipt_text_stays_within_its_bound():
    entries = [{'path': 'p' * 300 + str(i), 'kind': 'file', 'size': 1, 'sha256': 'a' * 64} for i in range(3000)]
    report = {'profile_inventory_before': {'trees': {'.gemini': {'entries': entries}}},
              'profile_inventory_after': {'trees': {'.gemini': {'entries': list(entries)}}}, 'new_files': [], 'probes': []}
    text = m.bounded_receipt_text(report)
    assert len(text.encode()) <= m.RECEIPT_MAX_BYTES and json.loads(text)['inventory_entries_omitted_for_receipt_bound'] is True


# ---------------------------------------------------------------- full helper runs

def test_full_signed_out_run_writes_receipt_login_mode_and_raw_files(produced):
    run = produced['print']
    receipt = run.receipt
    assert run.code == 0 and receipt['status'] == 'CAPTURE_COMPLETE' and receipt['schema'] == 'cochem-agy-status-capture/1'
    assert [p['id'] for p in receipt['probes']] == ['P1', 'P2', 'P2b', 'P3', 'P4', 'P5', 'P6', 'P7', 'P8']
    assert [item.argv for item in run.launched] == [[str(m.EXECUTABLE), *m.PROBES[p]['arguments']] for p, _ in m.STAGE_PROBES['signed-out']]
    assert all(item.cwd == run.layout['slots']['slot1']['root'] for item in run.launched) and all(item.limits is not None for item in run.launched)
    assert run.stops == ['stop', 'stop'] and receipt['require_stopped_before'] and receipt['require_stopped_after']
    assert receipt['helper_sha256'] == hashlib.sha256(PY.read_bytes()).hexdigest() and receipt['native_executable_sha256_after'] == m.AGY_SHA256
    by = {p['id']: p for p in receipt['probes']}
    assert by['P2']['classification']['status_helper_classification'] == 'LOGGED_OUT' and by['P2']['outcome'] == 'exited'
    assert by['P3']['outcome'] == 'window_elapsed_terminated' and by['P6']['outcome'] == 'window_elapsed_terminated'
    assert by['P3']['classification']['url_hosts'] == ['accounts.google.com'] and receipt['oauth_urls_possibly_minted'] == 1
    assert receipt['login_mode']['mode'] == 'print' and receipt['login_mode']['decided_by'] == 'P3'
    raw = (run.root / 'login-mode.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == receipt['login_mode']['sha256']
    mode = json.loads(raw)
    assert mode['mode'] == 'print' and set(mode['evidence']) == {'P3', 'P6'} and mode['evidence']['P3']['stderr_sha256'] == by['P3']['stderr']['sha256']
    assert receipt['gate'] == {'stage': 'signed-out', 'passed': True, 'reasons': []}
    assert receipt['new_files'] == [{'path': '.gemini/antigravity-cli/installation_id', 'size': 20, 'token_file': False}]
    for probe in receipt['probes']:
        for stream in ('stdout', 'stderr'):
            data = (run.root / probe['raw_path'][stream]).read_bytes()
            assert hashlib.sha256(data).hexdigest() == probe[stream]['sha256'] and len(data) == probe[stream]['bytes']
    assert EMAIL in (run.root / 'raw' / 'P6.stdout').read_bytes(), 'raw output stays in the private root'
    for text in (run.receipt_text, raw.decode()):
        for secret in ('SECRET', EMAIL.decode(), 'oauth2/auth', 'Select login method'):
            assert secret not in text
    assert len(run.receipt_text.encode()) <= m.RECEIPT_MAX_BYTES and receipt['token_files_opened'] == 0
    assert receipt['native_model_jobs_executed'] == receipt['login_inputs_written'] == receipt['stdin_bytes_written'] == 0


def test_signed_out_variants_decide_none_and_tui(produced):
    none, tui = produced['none'].receipt, produced['tui'].receipt
    assert none['status'] == 'CAPTURE_COMPLETE' and none['login_mode']['mode'] == 'none' and none['login_mode']['decided_by'] is None
    assert none['gate'] == {'stage': 'signed-out', 'passed': False, 'reasons': ['LOGIN_MODE_NONE']}
    p3 = next(p for p in none['probes'] if p['id'] == 'P3')
    assert p3['outcome'] == 'exited' and p3['classification']['exited_before_window'] and p3['classification']['no_controlling_terminal_present']
    assert tui['login_mode']['mode'] == 'tui' and tui['login_mode']['decided_by'] == 'P6' and tui['gate']['passed']


def test_docs_link_is_not_sign_in_evidence(produced):
    """Wave-1 low (helper ~576): P3 and P6 fail fast printing only a docs link on another https host. Neither counts as
    sign-in evidence, so the login mode is none and the signed-out gate stops the series (LOGIN_MODE_NONE)."""
    run = produced['docs']
    receipt = run.receipt
    assert run.code == 0 and receipt['status'] == 'CAPTURE_COMPLETE'
    by = {p['id']: p for p in receipt['probes']}
    for probe in ('P3', 'P6'):
        value = by[probe]['classification']
        assert by[probe]['outcome'] == 'exited' and value['url_present'] is True and value['url_hosts'] == ['antigravity.google']
        assert value['no_controlling_terminal_present'] is False and value['paste_prompt_present'] is False
    assert receipt['login_mode']['mode'] == 'none' and receipt['login_mode']['decided_by'] is None
    assert receipt['gate'] == {'stage': 'signed-out', 'passed': False, 'reasons': ['LOGIN_MODE_NONE']}
    assert receipt['oauth_urls_possibly_minted'] == 2, 'the conservative minted-URL count still counts every https URL'
    mode = json.loads((run.root / 'login-mode.json').read_bytes())
    assert mode['mode'] == 'none' and 'https://accounts.google.com/' in mode['rule']
    assert mode['evidence']['P3']['classification']['url_hosts'] == ['antigravity.google']


def test_full_signed_in_run_confirms_the_logged_in_shape(produced):
    run = produced['signed_in']
    receipt = run.receipt
    assert run.code == 0 and receipt['status'] == 'CAPTURE_COMPLETE' and receipt['login_mode'] is None
    assert not (run.root / 'login-mode.json').exists()
    assert [p['id'] for p in receipt['probes']] == ['P1', 'P2', 'P2b', 'P7', 'P8', 'P3', 'P4', 'P5']
    assert all(p['stdin_mode'] == 'empty_file' for p in receipt['probes'])
    by = {p['id']: p for p in receipt['probes']}
    assert by['P2']['classification']['status_helper_classification'] == 'LOGGED_IN' and by['P3']['classification']['model_record_present']
    assert by['P7']['classification']['agents'] == ['cochem-audit', 'flutter_a11y_agent']
    assert receipt['gate'] == {'stage': 'signed-in', 'passed': True, 'reasons': []}
    tokens = [row for row in receipt['profile_inventory_after']['trees']['.gemini']['entries'] if row.get('token_file')]
    assert tokens == [{'path': 'antigravity-cli/antigravity-oauth-token', 'kind': 'file', 'size': 18, 'sha256': None, 'token_file': True}]
    assert 'SECRET' not in run.receipt_text and EMAIL.decode() not in run.receipt_text


def test_version_mismatch_stops_before_any_sign_in_probe(produced):
    run = produced['failed']
    receipt = run.receipt
    assert run.code == 2 and receipt['status'] == 'CAPTURE_FAILED' and [p['id'] for p in receipt['probes']] == ['P1']
    assert receipt['failure'] == {'phase': 'native_result', 'error_type': 'ValueError', 'winerror': None}
    assert receipt['gate'] == {'stage': 'signed-out', 'passed': False, 'reasons': ['CAPTURE_NOT_COMPLETE']}
    assert receipt['login_mode'] is None and not (run.root / 'login-mode.json').exists() and receipt['profile_inventory_after'] is not None
    assert receipt['cleanup_verified'] is False and receipt['oauth_urls_possibly_minted'] == 0


def test_deadline_guard_skips_probes_and_marks_the_capture_incomplete(tmp_path, monkeypatch):
    run = produce(tmp_path, 'signed-out', signed_out_scripts('print'), monkeypatch, deadline=60)
    receipt = run.receipt
    assert run.code == 2 and receipt['status'] == 'CAPTURE_INCOMPLETE'
    assert [p['id'] for p in receipt['probes']] == ['P1', 'P2', 'P2b', 'P3'] and receipt['probes_skipped'] == ['P4', 'P5', 'P6', 'P7', 'P8']
    assert receipt['gate']['reasons'] == ['CAPTURE_NOT_COMPLETE'] and receipt['login_mode'] is None and receipt['require_stopped_after'] is True


def test_run_refuses_wrong_arguments_before_any_receipt():
    for args in (('slot2', 'signed-out', NONCE, ATTEMPT), ('slot1', 'before', NONCE, ATTEMPT), ('slot1', 'signed-out', NONCE, '0' * 32),
                 ('slot1', 'signed-out', 'x', ATTEMPT)):
        with pytest.raises(ValueError):
            m.run(*args)


def test_observe_child_attests_a_running_and_an_exited_real_child():
    from cochem_pipeline import windows as win
    api = win._api()
    token = win.HANDLE()
    win._check(api['advapi32'].OpenProcessToken(api['kernel32'].GetCurrentProcess(), 0x8, C.byref(token)), 'own token')
    try:
        sid = win._sid_text(win._SID_AND_ATTRIBUTES.from_buffer(win._token_info(token, 1)).Sid)
    finally:
        win._close(token)
    sort = Path(os.environ['SystemRoot']) / 'System32' / 'sort.exe'
    child = subprocess.Popen([str(sort)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    job = api['kernel32'].CreateJobObjectW(None, None)
    try:
        win._check(api['kernel32'].AssignProcessToJobObject(job, int(child._handle)), 'assign fixture child')
        fake = SimpleNamespace(_process=int(child._handle), _job=job, pid=child.pid, creation_time_filetime=1, poll=child.poll)
        live = m.observe_child(win, fake, sid, sort)
        child.stdin.close()
        child.wait(timeout=30)
        exited = m.observe_child(win, fake, sid, sort)
        assert live['image_query_format'] == 'win32' and exited['image_query_format'] == 'native_after_exit'
        assert exited['token_matches_selected_worker'] and exited['owned_job_membership_verified']
        with pytest.raises(ValueError, match='image differs'):
            m.observe_child(win, fake, sid, Path(os.environ['SystemRoot']) / 'System32' / 'find.exe')
        with pytest.raises(ValueError, match='wrong identity'):
            m.observe_child(win, fake, 'S-1-5-21-0-0-0-1', sort)
    finally:
        if child.poll() is None:
            child.stdin.close()
            child.wait(timeout=30)
        win._close(job)


# ---------------------------------------------------------------- observe_child exit fallback (inert: fake Windows API, no process)

def fake_observe(tmp_path, error, wait_result, exited_before=False, exits_on_wait=True):
    """A fake win/api for observe_child: the Win32 image query fails with `error`; WaitForSingleObject returns `wait_result`."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    exe = tmp_path / 'agy.exe'
    exe.write_bytes(b'MZ')
    device = r'\Device\HarddiskVolume3' + str(exe.resolve())[2:]
    calls, state = [], {'exited': exited_before}

    def profile_directory(token, buffer, size):
        if buffer is None:
            size._obj.value = 64
            return 0
        buffer.value = r'C:\Users\CoChem422Worker1'
        return 1

    def query(handle, flags, image, size):
        calls.append(('query', flags))
        if flags == 0:
            C.set_last_error(error)
            return 0
        image.value = device
        return 1

    def wait(handle, milliseconds):
        calls.append(('wait', handle, milliseconds))
        if wait_result == 0 and exits_on_wait:
            state['exited'] = True
        return wait_result

    def in_job(process, job, result):
        result._obj.value = 1
        return 1

    def dos_device(drive, buffer, size):
        buffer.value = r'\Device\HarddiskVolume3'
        return len(buffer.value) + 2

    class SidAndAttributes:
        @staticmethod
        def from_buffer(buffer):
            return SimpleNamespace(Sid='S-1-5-21-fixture')
    api = {'advapi32': SimpleNamespace(OpenProcessToken=lambda *a: 1), 'userenv': SimpleNamespace(GetUserProfileDirectoryW=profile_directory),
           'kernel32': SimpleNamespace(QueryFullProcessImageNameW=query, WaitForSingleObject=wait, IsProcessInJob=in_job, QueryDosDeviceW=dos_device)}
    win = SimpleNamespace(_api=lambda: api, HANDLE=C.c_void_p, DWORD=C.c_uint32, LPWSTR=C.c_wchar_p, BOOL=C.c_int32,
                          _check=lambda value, *a: value, _close=lambda *a: None, _token_info=lambda token, kind: b'',
                          _SID_AND_ATTRIBUTES=SidAndAttributes, _sid_text=lambda sid: sid, SYSTEM_SID='S-1-5-18', ADMIN_SID='S-1-5-32-544')
    process = SimpleNamespace(_process=11, _job=12, pid=4242, creation_time_filetime=1, poll=lambda: 0 if state['exited'] else None)
    return win, process, exe, calls, state


def test_observe_child_waits_out_the_error_5_teardown_window(tmp_path):
    win, process, exe, calls, state = fake_observe(tmp_path, 5, 0)
    assert process.poll() is None, 'the child is still tearing down when the Win32 query fails with error 5'
    value = m.observe_child(win, process, 'S-1-5-21-fixture', exe)
    assert value['image_query_format'] == 'native_after_exit' and value['image_matches_reviewed_executable'] is True
    assert calls == [('query', 0), ('wait', 11, m.EXIT_SETTLE_MILLISECONDS), ('query', 1)], 'one bounded wait on the owned handle'
    assert m.EXIT_SETTLE_MILLISECONDS == 5000
    api = win._api()['kernel32']
    assert api.WaitForSingleObject.argtypes == [C.c_void_p, C.c_uint32] and api.WaitForSingleObject.restype is C.c_uint32


def test_observe_child_error_5_without_a_signaled_handle_fails_closed(tmp_path):
    for wait_result in (0x102, 0xFFFFFFFF):
        win, process, exe, calls, _ = fake_observe(tmp_path / str(wait_result), 5, wait_result)
        with pytest.raises(ValueError, match='Observe native process image failed'):
            m.observe_child(win, process, 'S-1-5-21-fixture', exe)
        assert calls == [('query', 0), ('wait', 11, 5000)], 'no native-form comparison without a signaled handle'
    win, process, exe, calls, _ = fake_observe(tmp_path / 'nopoll', 5, 0, exits_on_wait=False)
    with pytest.raises(ValueError, match='Observe native process image failed'):
        m.observe_child(win, process, 'S-1-5-21-fixture', exe)
    assert ('query', 1) not in calls, 'poll() must also report an exit code after the wait'


def test_observe_child_error_31_after_exit_is_unchanged(tmp_path):
    win, process, exe, calls, _ = fake_observe(tmp_path, 31, 0, exited_before=True)
    assert m.observe_child(win, process, 'S-1-5-21-fixture', exe)['image_query_format'] == 'native_after_exit'
    assert calls == [('query', 0), ('wait', 11, 5000), ('query', 1)]


def test_observe_child_other_errors_raise_without_waiting(tmp_path):
    for error in (2, 6, 87, 0):
        win, process, exe, calls, _ = fake_observe(tmp_path / str(error), error, 0, exited_before=True)
        with pytest.raises(ValueError, match='Observe native process image failed'):
            m.observe_child(win, process, 'S-1-5-21-fixture', exe)
        assert calls == [('query', 0)], f'error {error} raises without WaitForSingleObject'


# ---------------------------------------------------------------- PowerShell wrapper

def psq(value):
    return str(value).replace("'", "''")


PRELUDE = r'''$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;
foreach($m in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$m\$m.psd1")};
function Get-AstFunctionTexts {param([string]$Path,[string[]]$Names)
  $t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$t,[ref]$e);if($e.Count){throw ($e|Out-String)}
  foreach($f in $a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){if($null -eq $Names -or $Names -contains $f.Name){$f.Extent.Text}}}
foreach($x in Get-AstFunctionTexts 'SCRIPTPATH' $null){. ([scriptblock]::Create($x))}
foreach($x in Get-AstFunctionTexts 'V22PATH' @('Test-ExactBool','Test-ExactInt')){. ([scriptblock]::Create($x))}
foreach($x in Get-AstFunctionTexts 'REGPATH' @('Assert-RegisteredTaskAcl')){. ([scriptblock]::Create($x))}
foreach($x in Get-AstFunctionTexts 'CHECKPATH' @('Read-R3Text')){. ([scriptblock]::Create($x))}
$held=[Collections.Generic.List[IO.FileStream]]::new();$script:admin=$false
function Read-R3Control {param([string]$Path,[string]$Hash='',[long]$Maximum=16777216)
  $item=Get-Item -LiteralPath $Path -Force;if($item.Length -gt $Maximum){throw 'Bounded r3 control length differs.'}
  $actual=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant();if($Hash -and $actual -cne $Hash){throw ('Source digest changed: '+$Path)}
  $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);$held.Add($stream);[pscustomobject]@{Stream=$stream;Sha256=$actual;Length=$item.Length}}
function Invoke-Case {param([string]$Name,[scriptblock]$Body)
  try{$value=& $Body;'CASE '+([pscustomobject]@{case=$Name;ok=$true;value=$value}|ConvertTo-Json -Depth 10 -Compress)}
  catch{'CASE '+([pscustomobject]@{case=$Name;ok=$false;error=$_.Exception.Message}|ConvertTo-Json -Depth 10 -Compress)}}
'''.replace('SCRIPTPATH', psq(SCRIPT)).replace('V22PATH', psq(V22)).replace('REGPATH', psq(REGISTER)).replace('CHECKPATH', psq(CHECK_R3))


def run_ps(body, timeout=240):
    result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-Command', PRELUDE + body], capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, result.stdout + result.stderr
    cases = {}
    for line in result.stdout.splitlines():
        if line.startswith('CASE '):
            value = json.loads(line[5:])
            cases[value['case']] = value
    return cases, result


def constants(stage, profile):
    return (f"Set-CaptureConstants 'slot1' '{stage}' '{ATTEMPT}' '{psq(ROOT)}';$script:workerProfile='{psq(profile)}';"
            "$pins=[ordered]@{install_receipt_sha256=$script:r4InstallPin;source_manifest_sha256=$script:r4ManifestPin;revision_sha256=$script:r4RevisionPin;"
            "configuration_sha256=$script:configPin;layout_sha256=$script:r4LayoutPin};")


def ast_summary():
    body = rf'''$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile('{psq(SCRIPT)}',[ref]$t,[ref]$e)
      $names=@($a.FindAll({{param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]}},$true)|ForEach-Object {{$_.Name}})
      $top=@($a.EndBlock.Statements|Where-Object {{$_ -isnot [Management.Automation.Language.FunctionDefinitionAst]}}|ForEach-Object {{$_.Extent.Text}})
      $params=@($a.ParamBlock.Parameters|ForEach-Object {{[ordered]@{{name=$_.Name.VariablePath.UserPath;default=$(if($_.DefaultValue){{$_.DefaultValue.Extent.Text}}else{{$null}})}}}})
      $v=[Management.Automation.Language.Parser]::ParseFile('{psq(V22)}',[ref]$t,[ref]$e)
      $mine=$a.FindAll({{param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Import-ReviewedFunctions'}},$true)[0].Extent.Text
      $theirs=$v.FindAll({{param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Import-ReviewedFunctions'}},$true)[0].Extent.Text
      'CASE '+([pscustomobject]@{{case='ast';ok=$true;value=[ordered]@{{errors=$e.Count;names=$names;top=$top;params=$params;import_identical=($mine -ceq $theirs)}}}}|ConvertTo-Json -Depth 6 -Compress)'''
    return run_ps(body)[0]['ast']['value']


def test_wrapper_parses_declares_the_functions_and_one_invocation():
    value = ast_summary()
    assert value['errors'] == 0
    assert value['names'] == ['Import-ReviewedFunctions', 'Set-CaptureConstants', 'Get-ExpectedProbes', 'Get-CaptureTaskArguments', 'New-CaptureNonce',
                              'Get-SeriesDaemonTaskStates', 'Get-TaskPresence', 'Assert-CaptureRuntimePins', 'New-CaptureTaskDefinition',
                              'Assert-CaptureTaskRegistration', 'Wait-CaptureTaskInstance', 'Assert-CompletedCaptureTask', 'Test-StringList',
                              'Assert-ProbeClassification', 'Assert-ProbeRecord', 'Get-LoginModeDecision', 'Get-CaptureGate', 'Assert-CaptureFailureMetadata',
                              'Assert-CaptureReceipt', 'New-CaptureSummary', 'Invoke-AgyCapture', 'Write-CaptureOutcome', 'Invoke-AgyCaptureMain']
    assert value['top'] == ['Invoke-AgyCaptureMain -Slot $Slot -Stage $Stage -Attempt $Attempt -ApplyRequested ([bool]$Apply) -Workspace $PSScriptRoot']
    assert value['params'] == [{'name': 'Slot', 'default': None}, {'name': 'Stage', 'default': None},
                               {'name': 'Attempt', 'default': "'00000000000000000000000000000000'"}, {'name': 'Apply', 'default': None}]
    assert value['import_identical'] is True and hashlib.sha256(V22.read_bytes()).hexdigest() == V22_SHA256
    assert SCRIPT.read_bytes().isascii() and PY.read_bytes().isascii()


def test_wrapper_pins_and_forbidden_operations():
    text = SCRIPT.read_text(encoding='utf-8')
    assert f"$script:helperPin='{hashlib.sha256(PY.read_bytes()).hexdigest()}'" in text, 'the helper pin is the file on disk'
    for path, needle in ((COPY_HELPER, "$copyHelper '"), (CHECK_R3, "'check-worker-native-status-r3.ps1') '"), (REGISTER, "'register-stopped-warden-r3.ps1') '"),
                         (INSPECTION, "'protected-code-inspection-v4.ps1') '"), (V22, "'retarget-warden-r4.ps1') '")):
        assert needle + hashlib.sha256(path.read_bytes()).hexdigest() + "'" in text, path
    for pin in (m.INSTALL_RECEIPT_SHA256, m.MANIFEST_SHA256, m.REVISION_SHA256, m.LAYOUT_SHA256, m.WINDOWS_SHA256, m.RESOURCE_SHA256,
                m.PRESERVED_DENIAL_SHA256, m.AGY_SHA256, m.CONFIG_SHA256, m.REPAIR_SHA256):
        assert f"'{pin}'" in text, pin
    for needle in ("$script:taskSddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'", "$script:taskTimeLimit='PT5M'", "$script:captureNamespaceDate='20261010'",
                   "RegisterTaskDefinition($script:taskName,$definition,2,'SYSTEM',$null,5,$script:taskSddl)", "$script:taskWaitSeconds=295"):
        assert needle in text, needle
    assert text.count('.Run($null)') == 1 and text.count('RegisterTaskDefinition(') == 1
    for forbidden in ('Stop-ScheduledTask', 'Disable-ScheduledTask', 'Register-ScheduledTask', 'Unregister-ScheduledTask', 'Start-ScheduledTask', 'schtasks',
                      'Start-Process', 'Stop-Process', 'taskkill', 'Remove-Item', 'DeleteTask', 'Stop-Service', '.Stop(', '.Kill(', 'Invoke-Expression',
                      '.Enabled=$false', 'RunAs', 'Set-Content', 'Out-File'):
        assert forbidden not in text, forbidden
    helper = PY.read_text(encoding='utf-8')
    for forbidden in ('subprocess', 'CredRead', 'shutil', 'unlink', 'rmtree', 'os.remove', '.write(value', 'TerminateProcess'):
        assert forbidden not in helper, forbidden
    assert helper.count('win.launch_worker(') == 1 and "'Global\\\\CoChem427-NativeStatusSetup'" in helper


def test_python_and_powershell_probe_tables_agree():
    body = "foreach($stage in @('signed-out','signed-in')){Set-CaptureConstants 'slot1' $stage ('c'*32) 'X';Invoke-Case $stage {@(Get-ExpectedProbes $stage|ForEach-Object {[ordered]@{id=$_.id;stdin_mode=$_.stdin_mode;arguments=@($_.arguments);bound=$_.bound_seconds}})}}"
    cases, _ = run_ps(body)
    for stage in ('signed-out', 'signed-in'):
        expected = [{'id': p, 'stdin_mode': mode, 'arguments': list(m.PROBES[p]['arguments']), 'bound': 20 if mode == m.PIPE else 30}
                    for p, mode in m.STAGE_PROBES[stage]]
        assert cases[stage]['value'] == expected


def test_python_and_powershell_login_mode_decisions_agree(tmp_path):
    """Get-LoginModeDecision mirrors login_mode_decision, including the accounts.google.com-only URL rule."""
    rows = tmp_path / 'rows.json'
    rows.write_text(json.dumps([[full_classification(p3), full_classification(p6)] for p3, p6, _ in LOGIN_MODE_CASES]))
    body = (f"$rows=Get-Content -Raw -LiteralPath '{psq(rows)}'|ConvertFrom-Json;$i=0\n"
            "foreach($row in $rows){Invoke-Case ([string]$i) {$d=Get-LoginModeDecision $row[0] $row[1];[ordered]@{mode=$d.mode;by=$d.decided_by}};$i++}")
    cases, _ = run_ps(body)
    assert len(cases) == len(LOGIN_MODE_CASES)
    for i, (p3, p6, expected) in enumerate(LOGIN_MODE_CASES):
        assert cases[str(i)]['ok'], cases[str(i)]
        assert (cases[str(i)]['value']['mode'], cases[str(i)]['value']['by']) == expected == m.login_mode_decision(full_classification(p3), full_classification(p6)), i


def test_wrapper_receipt_validation_accepts_helper_receipts_and_refuses_tampering(produced, tmp_path):
    so, none, si, failed, docs = produced['print'], produced['none'], produced['signed_in'], produced['failed'], produced['docs']
    tampered = tmp_path / 'tampered'
    shutil.copytree(so.root, tampered)
    with open(tampered / 'raw' / 'P3.stderr', 'ab') as stream:
        stream.write(b'x')
    rp = lambda run: psq(run.root / 'capture-receipt.json')
    body = constants('signed-out', so.profile) + f'''
      $task=[pscustomobject]@{{LastTaskResult=0}};$root='{psq(so.root)}'
      function Get-R {{Get-Content -Raw -LiteralPath '{rp(so)}'|ConvertFrom-Json}}
      Invoke-Case 'ok' {{$v=Assert-CaptureReceipt (Get-R) $task $pins '{NONCE}' $root;[ordered]@{{decision=$v.decision;passed=$v.gate.passed;reasons=@($v.gate.reasons);mode=$v.login_mode.mode;by=$v.login_mode.decided_by}}}}
      Invoke-Case 'helper_sha' {{$r=Get-R;$r.helper_sha256=('0'*64);Assert-CaptureReceipt $r $task $pins '{NONCE}' $root}}
      Invoke-Case 'nonce' {{Assert-CaptureReceipt (Get-R) $task $pins ('e'*32) $root}}
      Invoke-Case 'argv' {{$r=Get-R;$r.probes[3].argv[1]='--print';Assert-CaptureReceipt $r $task $pins '{NONCE}' $root}}
      Invoke-Case 'order' {{$r=Get-R;$p=@($r.probes);$x=$p[3];$p[3]=$p[4];$p[4]=$x;$r.probes=$p;Assert-CaptureReceipt $r $task $pins '{NONCE}' $root}}
      Invoke-Case 'login_mode' {{$r=Get-R;$r.login_mode.mode='tui';Assert-CaptureReceipt $r $task $pins '{NONCE}' $root}}
      Invoke-Case 'gate' {{$r=Get-R;$r.gate.passed=$false;Assert-CaptureReceipt $r $task $pins '{NONCE}' $root}}
      Invoke-Case 'url_path' {{$r=Get-R;$r.probes[3].classification.url_hosts=@('accounts.google.com/o/oauth2/auth');Assert-CaptureReceipt $r $task $pins '{NONCE}' $root}}
      Invoke-Case 'stdin_written' {{$r=Get-R;$r.probes[3].stdin_bytes_written=1;Assert-CaptureReceipt $r $task $pins '{NONCE}' $root}}
      Invoke-Case 'model_jobs' {{$r=Get-R;$r.native_model_jobs_executed=1;Assert-CaptureReceipt $r $task $pins '{NONCE}' $root}}
      Invoke-Case 'minted' {{$r=Get-R;$r.oauth_urls_possibly_minted=0;Assert-CaptureReceipt $r $task $pins '{NONCE}' $root}}
      Invoke-Case 'exit_type' {{$r=Get-R;$r.probes[3].exit_code=0;Assert-CaptureReceipt $r $task $pins '{NONCE}' $root}}
      Invoke-Case 'attest' {{$r=Get-R;$r.probes[0].process.owned_job_membership_verified=$false;Assert-CaptureReceipt $r $task $pins '{NONCE}' $root}}
      Invoke-Case 'last_result' {{Assert-CaptureReceipt (Get-R) ([pscustomobject]@{{LastTaskResult=2}}) $pins '{NONCE}' $root}}
      Invoke-Case 'raw_tamper' {{Assert-CaptureReceipt (Get-R) $task $pins '{NONCE}' '{psq(tampered)}'}}
      Invoke-Case 'none' {{$script:workerProfile='{psq(none.profile)}';$v=Assert-CaptureReceipt (Get-Content -Raw -LiteralPath '{rp(none)}'|ConvertFrom-Json) $task $pins '{NONCE}' '{psq(none.root)}';[ordered]@{{decision=$v.decision;passed=$v.gate.passed;reasons=@($v.gate.reasons);mode=$v.login_mode.mode}}}}
      Invoke-Case 'docs' {{$script:workerProfile='{psq(docs.profile)}';$v=Assert-CaptureReceipt (Get-Content -Raw -LiteralPath '{rp(docs)}'|ConvertFrom-Json) $task $pins '{NONCE}' '{psq(docs.root)}';[ordered]@{{decision=$v.decision;passed=$v.gate.passed;reasons=@($v.gate.reasons);mode=$v.login_mode.mode}}}}
      Invoke-Case 'docs_claims_print' {{$r=Get-Content -Raw -LiteralPath '{rp(docs)}'|ConvertFrom-Json;$r.login_mode.mode='print';$r.login_mode.decided_by='P3';Assert-CaptureReceipt $r $task $pins '{NONCE}' '{psq(docs.root)}'}}
      Invoke-Case 'failed' {{$v=Assert-CaptureReceipt (Get-Content -Raw -LiteralPath '{rp(failed)}'|ConvertFrom-Json) ([pscustomobject]@{{LastTaskResult=2}}) $pins '{NONCE}' '{psq(failed.root)}';[ordered]@{{decision=$v.decision;phase=$v.failure.phase;passed=$v.gate.passed}}}}
      {constants('signed-in', si.profile)}
      Invoke-Case 'signed_in' {{$v=Assert-CaptureReceipt (Get-Content -Raw -LiteralPath '{rp(si)}'|ConvertFrom-Json) $task $pins '{NONCE}' '{psq(si.root)}';[ordered]@{{decision=$v.decision;passed=$v.gate.passed;mode=$v.login_mode}}}}
      Invoke-Case 'signed_in_stage_mismatch' {{Set-CaptureConstants 'slot1' 'signed-out' '{ATTEMPT}' 'X';Assert-CaptureReceipt (Get-Content -Raw -LiteralPath '{rp(si)}'|ConvertFrom-Json) $task $pins '{NONCE}' '{psq(si.root)}'}}
      foreach($s in $held){{$s.Dispose()}}'''
    cases, _ = run_ps(body)
    assert cases['ok']['ok'], cases['ok']
    assert cases['ok']['value'] == {'decision': 'COMPLETE', 'passed': True, 'reasons': [], 'mode': 'print', 'by': 'P3'}
    expected_errors = {'helper_sha': 'identity/runtime binding differs', 'nonce': 'identity/runtime binding differs', 'argv': 'argv differs',
                       'order': 'probe order differs', 'login_mode': 'login-mode decision contradicts', 'gate': 'gate contradicts',
                       'url_path': 'host-only list', 'stdin_written': 'bound, stdin or cleanup', 'model_jobs': 'Out-of-scope execution',
                       'minted': 'minted-URL count', 'exit_type': 'exit code is invalid', 'attest': 'process attestation',
                       'last_result': 'configuration/result binding', 'raw_tamper': 'Source digest changed', 'signed_in_stage_mismatch': 'binding differs',
                       'docs_claims_print': 'login-mode decision contradicts'}
    for case, needle in expected_errors.items():
        assert cases[case]['ok'] is False and needle in cases[case]['error'], (case, cases[case])
    assert cases['none']['value'] == {'decision': 'COMPLETE', 'passed': False, 'reasons': ['LOGIN_MODE_NONE'], 'mode': 'none'}
    assert cases['docs']['value'] == {'decision': 'COMPLETE', 'passed': False, 'reasons': ['LOGIN_MODE_NONE'], 'mode': 'none'}
    assert cases['failed']['value'] == {'decision': 'FAILED', 'phase': 'native_result', 'passed': False}
    assert cases['signed_in']['value'] == {'decision': 'COMPLETE', 'passed': True, 'mode': None}


APPLY_FIXTURE = r'''
  $script:registered=@();$script:runs=0;$script:task=$null
  $script:fx=@{Sddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)';LastTaskResult=0;CopyReceipt=$true;RefreshEnds=$true;RootFails='';HeldFails=$false}
  function New-PrivateDirectory {param($Path) if(Test-Path -LiteralPath $Path){throw ('Private directory already exists; preserve it: '+$Path)}
    if($script:fx.RootFails -cne 'before'){$null=[IO.Directory]::CreateDirectory($Path)}
    if($script:fx.RootFails){throw ('Private backup path grants access beyond SYSTEM/Administrators: '+$Path)}}
  function Copy-VerifiedPayload {param($File) if((Get-FileHash -LiteralPath $File.source -Algorithm SHA256).Hash.ToLowerInvariant() -cne $File.sha256){throw 'Source digest changed'};[IO.File]::Copy($File.source,$File.destination)}
  function Open-VerifiedFile {param($Path,$Sha256,$Length) if((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Sha256){throw 'Source digest changed'};$s=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);return ,$s}
  function Assert-CodeTreeOnce {param($Path) 7}
  function Write-RegistrationControl {param($Path,$Text) if(Test-Path -LiteralPath $Path){throw ('control exists: '+$Path)};if($script:fx.HeldFails -and $Path.EndsWith('capture-held.json')){throw 'Untrusted protected owner of the held record parent.'};[IO.File]::WriteAllText($Path,$Text);(Get-FileHash -LiteralPath $Path).Hash.ToLowerInvariant()}
  function New-CaptureNonce {'NONCEVALUE'}
  function New-FixtureScheduler {
    $scheduler=[pscustomobject]@{}
    $scheduler|Add-Member ScriptMethod NewTask {param($f)
      $actions=[pscustomobject]@{Count=0;list=[Collections.ArrayList]::new()}
      $actions|Add-Member ScriptMethod Create {param($t) $a=[pscustomobject]@{Type=$t;Path=$null;Arguments=$null;WorkingDirectory=$null};$null=$this.list.Add($a);$this.Count=$this.list.Count;$a}
      $actions|Add-Member ScriptMethod Item {param($i) $this.list[$i-1]}
      [pscustomobject]@{RegistrationInfo=[pscustomobject]@{Description=$null};Principal=[pscustomobject]@{UserId=$null;LogonType=$null;RunLevel=$null};
        Settings=[pscustomobject]@{Enabled=$null;AllowDemandStart=$null;MultipleInstances=$null;ExecutionTimeLimit=$null;RestartCount=$null};Triggers=[pscustomobject]@{Count=0};Actions=$actions}}
    $scheduler}
  function New-FixtureFolder {
    $folder=[pscustomobject]@{}
    $folder|Add-Member ScriptMethod GetTask {param($name) if($null -ne $script:task -and $name -ceq $script:taskName){return $script:task};throw [Runtime.InteropServices.COMException]::new('absent',-2147024894)}
    $folder|Add-Member ScriptMethod RegisterTaskDefinition {param($name,$def,$flags,$user,$pw,$logon,$sddl)
      $script:registered+=[pscustomobject]@{name=$name;flags=$flags;user=$user;logon=$logon;sddl=$sddl;arguments=$def.Actions.Item(1).Arguments;limit=$def.Settings.ExecutionTimeLimit}
      $script:task=[pscustomobject]@{Enabled=$def.Settings.Enabled;State=3;LastTaskResult=267011;Definition=$def;Xml='<Task>fixture</Task>';Instances=0}
      $script:task|Add-Member ScriptMethod GetInstances {param($n)[pscustomobject]@{Count=$script:task.Instances}}
      $script:task|Add-Member ScriptMethod GetSecurityDescriptor {param($n)$script:fx.Sddl}
      $script:task|Add-Member ScriptMethod Run {param($a)
        $script:runs++
        if($script:fx.CopyReceipt){foreach($f in Get-ChildItem -LiteralPath $script:fixtureSource -Recurse -File){
          $rel=$f.FullName.Substring($script:fixtureSource.Length).TrimStart('\');if($rel -ceq 'agy_status_capture_r4_v1.py'){continue}
          $dst=Join-Path $script:targetRoot $rel;$null=[IO.Directory]::CreateDirectory((Split-Path -Parent $dst));[IO.File]::Copy($f.FullName,$dst)}}
        $script:task.LastTaskResult=$script:fx.LastTaskResult;$i=[pscustomobject]@{State=4};$i|Add-Member ScriptMethod Refresh {if($script:fx.RefreshEnds){$this.State=3}};$i}
      $script:task}
    $folder}
  function Invoke-ApplyCase {param([string]$Name,[string]$Stage,[string]$Source,[string]$Profile,[hashtable]$Fx,[switch]$PreCreate,[int]$Wait=295)
    Set-CaptureConstants 'slot1' $Stage 'ATTEMPTVALUE' 'WORKSPACE';$script:workerProfile=$Profile;$script:taskWaitSeconds=$Wait
    $script:targetRoot=Join-Path 'TMPROOT' $Name
    if($script:targetRoot -like 'C:\Program Files*'){throw 'fixture roots must be temporary'}
    $script:registered=@();$script:runs=0;$script:task=$null;$script:fixtureSource=$Source
    $script:fx=@{Sddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)';LastTaskResult=0;CopyReceipt=$true;RefreshEnds=$true;RootFails='';HeldFails=$false};foreach($k in $Fx.Keys){$script:fx[$k]=$Fx[$k]}
    if($PreCreate){$null=[IO.Directory]::CreateDirectory($script:targetRoot)}
    $pins=[ordered]@{install_receipt_sha256=$script:r4InstallPin;source_manifest_sha256=$script:r4ManifestPin;revision_sha256=$script:r4RevisionPin;configuration_sha256=$script:configPin;layout_sha256=$script:r4LayoutPin}
    $result=[ordered]@{ok=$true;error=$null;summary=$null}
    try{$s=Invoke-AgyCapture (New-FixtureScheduler) (New-FixtureFolder) $pins ((Get-Item -LiteralPath $script:helperSource).Length)
        $result.summary=[ordered]@{status=$s.status;decision=$s.decision;passed=$s.gate.passed;reasons=@($s.gate.reasons);series_stop=$s.series_stop;message=$s.message;mode=$(if($null -ne $s.login_mode){$s.login_mode.mode}else{$null});new_files=@($s.new_files);minted=$s.oauth_urls_possibly_minted;p2=$s.p2_status_helper_classification}}
    catch{$result.ok=$false;$result.error=$_.Exception.Message}
    foreach($s in $held){$s.Dispose()};$held.Clear()
    $files=@();if(Test-Path -LiteralPath $script:targetRoot){$files=@(Get-ChildItem -LiteralPath $script:targetRoot -File|ForEach-Object {$_.Name}|Sort-Object)}
    $heldRecord=$null;$heldPath=Join-Path $script:targetRoot 'capture-held.json';if(Test-Path -LiteralPath $heldPath){$heldRecord=Get-Content -Raw -LiteralPath $heldPath|ConvertFrom-Json}
    $result.files=$files;$result.registered=@($script:registered);$result.runs=$script:runs;$result.held=$heldRecord;$result.root_exists=[bool](Test-Path -LiteralPath $script:targetRoot)
    'CASE '+([pscustomobject]@{case=$Name;ok=$true;value=$result}|ConvertTo-Json -Depth 10 -Compress)}
'''


def test_wrapper_apply_path_is_driven_with_fixtures(produced, tmp_path):
    so, none, si, failed = produced['print'], produced['none'], produced['signed_in'], produced['failed']
    fixture = APPLY_FIXTURE.replace('ATTEMPTVALUE', ATTEMPT).replace('WORKSPACE', psq(ROOT)).replace('TMPROOT', psq(tmp_path)).replace('NONCEVALUE', NONCE)
    calls = [f"Invoke-ApplyCase 'pass' 'signed-out' '{psq(so.root)}' '{psq(so.profile)}' @{{}}",
             f"Invoke-ApplyCase 'gate_fail' 'signed-out' '{psq(none.root)}' '{psq(none.profile)}' @{{}}",
             f"Invoke-ApplyCase 'signed_in' 'signed-in' '{psq(si.root)}' '{psq(si.profile)}' @{{}}",
             f"Invoke-ApplyCase 'no_receipt' 'signed-out' '{psq(so.root)}' '{psq(so.profile)}' @{{CopyReceipt=$false;LastTaskResult=3}}",
             f"Invoke-ApplyCase 'helper_failed' 'signed-out' '{psq(failed.root)}' '{psq(failed.profile)}' @{{LastTaskResult=2}}",
             f"Invoke-ApplyCase 'acl' 'signed-out' '{psq(so.root)}' '{psq(so.profile)}' @{{Sddl='O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;BU)'}}",
             f"Invoke-ApplyCase 'root_exists' 'signed-out' '{psq(so.root)}' '{psq(so.profile)}' @{{}} -PreCreate",
             f"Invoke-ApplyCase 'wait_timeout' 'signed-out' '{psq(so.root)}' '{psq(so.profile)}' @{{RefreshEnds=$false;CopyReceipt=$false}} -Wait 1",
             f"Invoke-ApplyCase 'root_acl' 'signed-out' '{psq(so.root)}' '{psq(so.profile)}' @{{RootFails='after'}}",
             f"Invoke-ApplyCase 'root_unwritable' 'signed-out' '{psq(so.root)}' '{psq(so.profile)}' @{{RootFails='after';HeldFails=$true}}",
             f"Invoke-ApplyCase 'root_refused' 'signed-out' '{psq(so.root)}' '{psq(so.profile)}' @{{RootFails='before'}}"]
    cases, _ = run_ps(fixture + '\n'.join(calls))
    v = {name: case['value'] for name, case in cases.items()}
    # Wave-1 low (wrapper ~401): New-PrivateDirectory runs inside the held-record guard (phase PREPARATION).
    for name in ('root_acl', 'root_unwritable'):
        root = tmp_path / name
        reason = f'Private backup path grants access beyond SYSTEM/Administrators: {root}'
        assert v[name]['ok'] is False and v[name]['root_exists'] is True and v[name]['registered'] == [] and v[name]['runs'] == 0, v[name]
        assert v[name]['error'].startswith(f'The agy status capture is held before any task exists: {reason}. Preserve {root} and review capture-held.json'), v[name]
    held = v['root_acl']['held']
    assert v['root_acl']['files'] == ['capture-held.json'] and held['phase'] == 'PREPARATION' and held['reason'] == f'Private backup path grants access beyond SYSTEM/Administrators: {tmp_path / "root_acl"}'
    assert held['root_preserved'] is True and held['root_verified'] is False and held['task_registered'] is False and held['run_requested'] is False
    assert held['intent_sha256'] is None and held['nonce'] is None and held['receipt_present'] is False and held['automatic_retry_allowed'] is False
    assert v['root_unwritable']['held'] is None and v['root_unwritable']['files'] == []
    assert v['root_unwritable']['error'].endswith(' The held record could not be written: Untrusted protected owner of the held record parent.')
    refused = v['root_refused']
    assert refused['ok'] is False and refused['root_exists'] is False and refused['held'] is None and refused['registered'] == [] and refused['runs'] == 0
    assert refused['error'] == f'The agy status capture is held before any change: Private backup path grants access beyond SYSTEM/Administrators: {tmp_path / "root_refused"}. Nothing was changed.'
    for name in ('no_receipt', 'helper_failed', 'acl', 'wait_timeout'):
        assert v[name]['held']['root_verified'] is True and v[name]['held']['root_preserved'] is True, name
    expected_args = f'-I -B "{tmp_path / "pass" / m.HELPER_NAME}" --slot slot1 --stage signed-out --nonce {NONCE} --attempt {ATTEMPT}'
    assert v['pass']['ok'], v['pass']
    assert v['pass']['summary']['passed'] is True and v['pass']['summary']['series_stop'] is False and v['pass']['summary']['mode'] == 'print'
    assert v['pass']['summary']['new_files'] == ['.gemini/antigravity-cli/installation_id'] and v['pass']['summary']['minted'] == 1
    assert v['pass']['summary']['message'].startswith('Signed-out capture verified') and v['pass']['summary']['p2'] == 'LOGGED_OUT'
    assert v['pass']['registered'] == [{'name': f'CoChem-4.2.7-AgyCapture-20261010-r4-v1-{ATTEMPT}-slot1-signed-out', 'flags': 2, 'user': 'SYSTEM', 'logon': 5,
                                        'sddl': 'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)', 'arguments': expected_args, 'limit': 'PT5M'}]
    assert v['pass']['runs'] == 1 and v['pass']['held'] is None
    assert v['pass']['files'] == sorted(['agy_status_capture_r4_v1.py', 'capture-intent.json', 'capture-receipt.json', 'capture-summary.json',
                                         'capture-task.xml', 'login-mode.json'])
    assert v['gate_fail']['ok'] and v['gate_fail']['summary']['passed'] is False and v['gate_fail']['summary']['series_stop'] is True
    assert v['gate_fail']['summary']['reasons'] == ['LOGIN_MODE_NONE'] and v['gate_fail']['summary']['message'].startswith('SERIES-STOP: sign-in path unreachable')
    assert v['signed_in']['ok'] and v['signed_in']['summary']['passed'] and v['signed_in']['summary']['mode'] is None
    assert v['no_receipt']['ok'] is False and 'left no receipt (LastTaskResult 3)' in v['no_receipt']['error']
    assert v['no_receipt']['held']['phase'] == 'RECEIPT' and v['no_receipt']['held']['run_requested'] is True and v['no_receipt']['runs'] == 1
    assert v['helper_failed']['ok'] is False and v['helper_failed']['error'].startswith('SERIES-STOP: the capture helper reported CAPTURE_FAILED')
    assert v['helper_failed']['held']['phase'] == 'HELPER' and v['helper_failed']['held']['helper_failure']['phase'] == 'native_result'
    assert 'capture-summary.json' in v['helper_failed']['files']
    assert v['acl']['ok'] is False and 'held at task registration' in v['acl']['error'] and v['acl']['runs'] == 0
    assert v['acl']['held']['task_registered'] is True and v['acl']['held']['run_requested'] is False
    assert v['root_exists']['ok'] is False and 'held before any change' in v['root_exists']['error'] and 'Nothing was changed' in v['root_exists']['error']
    assert v['root_exists']['registered'] == [] and v['root_exists']['held'] is None and v['root_exists']['files'] == []
    assert v['wait_timeout']['ok'] is False and 'did not end cleanly' in v['wait_timeout']['error'] and v['wait_timeout']['held']['phase'] == 'WAIT'


def test_wrapper_output_gates_on_the_summary():
    body = r'''$pass=[ordered]@{decision='COMPLETE';gate=[ordered]@{passed=$true;reasons=@()};message='Signed-out capture verified'}
      $stop=[ordered]@{decision='COMPLETE';gate=[ordered]@{passed=$false;reasons=@('LOGIN_MODE_NONE')};message='SERIES-STOP: sign-in path unreachable (LOGIN_MODE_NONE); evidence in X.'}
      $failed=[ordered]@{decision='FAILED';gate=[ordered]@{passed=$true;reasons=@()};message='SERIES-STOP: the capture did not complete'}
      $odd=[ordered]@{decision='COMPLETE';gate=[ordered]@{passed='true';reasons=@()};message='SERIES-STOP: odd'}
      Invoke-Case 'pass' {(Write-CaptureOutcome $pass|ConvertFrom-Json).message}
      Invoke-Case 'stop' {Write-CaptureOutcome $stop 6>$null}
      Invoke-Case 'failed' {Write-CaptureOutcome $failed 6>$null}
      Invoke-Case 'odd' {Write-CaptureOutcome $odd 6>$null}'''
    cases, result = run_ps(body)
    assert cases['pass'] == {'case': 'pass', 'ok': True, 'value': 'Signed-out capture verified'}
    assert cases['stop']['ok'] is False and cases['stop']['error'].startswith('SERIES-STOP: sign-in path unreachable')
    assert cases['failed']['ok'] is False and cases['odd']['ok'] is False, 'only an exact boolean pass on a COMPLETE decision prints success'


def test_daemon_states_and_task_presence_are_exact_or_deferred():
    body = r'''Set-CaptureConstants 'slot1' 'signed-out' ('c'*32) 'X'
      $folder=[pscustomobject]@{};$folder|Add-Member ScriptMethod GetTask {param($name)
        switch($name){
          'CoChem-4.2.7-Warden'{$t=[pscustomobject]@{Enabled=$script:enabled;State=3};$t|Add-Member ScriptMethod GetInstances {param($n)[pscustomobject]@{Count=0}};return $t}
          'CoChem-4.2.7-Supervisor'{throw [Runtime.InteropServices.COMException]::new('denied',-2147024891)}
          'odd'{throw [Runtime.InteropServices.COMException]::new('odd',-2147467259)}
          default{throw [Runtime.InteropServices.COMException]::new('absent',-2147024894)}}}
      $script:enabled=$true;Invoke-Case 'enabled' {@(Get-SeriesDaemonTaskStates $folder|ForEach-Object {$_.name+'='+$_.state})}
      $script:enabled=$false;Invoke-Case 'disabled' {@(Get-SeriesDaemonTaskStates $folder|ForEach-Object {$_.name+'='+$_.state})}
      Invoke-Case 'presence' {@((Get-TaskPresence $folder 'missing'),(Get-TaskPresence $folder 'CoChem-4.2.7-Warden'),(Get-TaskPresence $folder 'CoChem-4.2.7-Supervisor'))}
      Invoke-Case 'odd' {Get-TaskPresence $folder 'odd'}'''
    cases, _ = run_ps(body)
    assert cases['enabled']['value'] == ['CoChem-4.2.7-Warden=ACTIVE', 'CoChem-4.2.7-Supervisor=ACCESS_DENIED_DEFERRED', 'CoChem-4.2.2-Warden=ABSENT', 'CoChem-4.2.3-Supervisor=ABSENT']
    assert cases['disabled']['value'][0] == 'CoChem-4.2.7-Warden=STOPPED_DISABLED'
    assert cases['presence']['value'] == ['ABSENT', 'PRESENT', 'PRESENT_UNREADABLE']
    assert cases['odd']['ok'] is False and 'unknown' in cases['odd']['error']


def test_nonadmin_apply_and_invalid_arguments_refuse_before_any_change():
    before = sorted(p.name for p in COCHEM.iterdir()) if COCHEM.exists() else []
    body = f'''$me=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
      if($me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){{'CASE {{"case":"elevated","ok":true}}';return}}
      Invoke-Case 'owner' {{Invoke-AgyCaptureMain -Slot 'slot1' -Stage 'signed-out' -Attempt '{ATTEMPT}' -ApplyRequested $true -Workspace '{psq(ROOT)}'}}
      Invoke-Case 'zero' {{Invoke-AgyCaptureMain -Slot 'slot1' -Stage 'signed-in' -Attempt ('0'*32) -ApplyRequested $true -Workspace '{psq(ROOT)}'}}
      Invoke-Case 'stage' {{Invoke-AgyCaptureMain -Slot 'slot1' -Stage 'before' -Attempt '{ATTEMPT}' -ApplyRequested $false -Workspace '{psq(ROOT)}'}}
      Invoke-Case 'slot' {{Invoke-AgyCaptureMain -Slot 'slot2' -Stage 'signed-out' -Attempt '{ATTEMPT}' -ApplyRequested $false -Workspace '{psq(ROOT)}'}}
      Invoke-Case 'upper' {{Invoke-AgyCaptureMain -Slot 'slot1' -Stage 'signed-out' -Attempt ('C'*32) -ApplyRequested $false -Workspace '{psq(ROOT)}'}}'''
    cases, _ = run_ps(body)
    if 'elevated' in cases:
        pytest.skip('this test must run unelevated')
    assert cases['owner']['ok'] is False and cases['owner']['error'] == '-Apply requires the owner in Administrator Windows PowerShell; nothing was changed.'
    for case in ('zero', 'upper'):
        assert cases[case]['ok'] is False and 'lowercase 32-hex -Attempt' in cases[case]['error']
    for case in ('stage', 'slot'):
        assert cases[case]['ok'] is False and 'Only -Slot slot1' in cases[case]['error']
    for flags, text in ((['-Slot', 'slot2', '-Stage', 'signed-out'], 'Slot'), (['-Slot', 'slot1', '-Stage', 'before'], 'Stage'),
                        (['-Slot', 'slot1', '-Stage', 'signed-out', '-Attempt', 'xyz'], 'Attempt')):
        result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-File', str(SCRIPT), *flags], capture_output=True, text=True, timeout=120)
        assert result.returncode != 0 and text in result.stderr, (flags, result.stderr)
    assert (sorted(p.name for p in COCHEM.iterdir()) if COCHEM.exists() else []) == before


@pytest.mark.parametrize('stage', ['signed-out', 'signed-in'])
def test_read_only_plan_reports_the_capture_and_creates_nothing(stage):
    root = COCHEM / f'AgyCapture4.2.7-windows-20261010-r4-v1-{"0" * 32}-slot1-{stage}'
    before = sorted(p.name for p in COCHEM.iterdir())
    result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-File', str(SCRIPT), '-Slot', 'slot1', '-Stage', stage],
                            capture_output=True, text=True, timeout=280)
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert sorted(p.name for p in COCHEM.iterdir()) == before and not root.exists(), 'the plan creates nothing'
    assert plan['schema'] == 'cochem-agy-status-capture-plan/1' and plan['mode'] == 'READ_ONLY_PLAN' and plan['stage'] == stage
    assert plan['target_root'] == str(root) and plan['task_name'] == f'CoChem-4.2.7-AgyCapture-20261010-r4-v1-{"0" * 32}-slot1-{stage}'
    assert plan['task_presence'] == 'ABSENT' and plan['task_execution_time_limit'] == 'PT5M' and plan['helper_verified'] is True
    assert plan['helper_sha256'] == hashlib.sha256(PY.read_bytes()).hexdigest()
    assert [p['id'] for p in plan['probes']] == [p for p, _ in m.STAGE_PROBES[stage]]
    assert plan['oauth_urls_minted_expected'] == (2 if stage == 'signed-out' else 0)
    assert plan['tasks_changed'] == 0 and plan['native_commands_executed'] == 0 and plan['login_inputs_written'] == 0
    if R4.exists():
        assert plan['r4_runtime_verified'] is True and plan['native_verified'] is True
        assert plan['r4_bindings']['install_receipt_sha256'] == m.INSTALL_RECEIPT_SHA256 and plan['r4_bindings']['revision_sha256'] == m.REVISION_SHA256
    assert plan['task_action']['path'] == str(R4 / '.venv' / 'Scripts' / 'python.exe')
    assert plan['task_action']['arguments'] == f'-I -B "{root / m.HELPER_NAME}" --slot slot1 --stage {stage} --nonce <nonce> --attempt {"0" * 32}'
    names = [row['name'] for row in plan['daemon_tasks']]
    assert names == list(m.DAEMON_TASK_NAMES)


# ------------------------------------------------------------------- top level, plan mode only (ps_toplevel_smoke.py)
# The fixtures above dot-source single functions; these run the REAL script top level (real param block and binding,
# the 2026-10-11 17:22 failure class) with the host stubbed. The helper refuses -Apply, so each documented sitting call
# (RUN_427_R5_SITTING.ps1 S5 signed-out, S7 signed-in) runs as its plan.

SMOKE_PLAN_SCHEMA = 'cochem-agy-status-capture-plan/1'


def validated_parameter_assignments(script):
    """Assignments that write a [Validate*] script parameter variable: $script:/$global:<name> anywhere (functions run in
    the script's scope), or a bare <name> at the top level; names compare case-insensitively, as PowerShell does."""
    code = ("$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile('" + psq(script) + "',[ref]$t,[ref]$e);if($e.Count){throw $e[0]};"
            "$v=@{};foreach($p in @($a.ParamBlock.Parameters)){if(@($p.Attributes|Where-Object{$_.TypeName.Name -like 'Validate*'}).Count){$v[$p.Name.VariablePath.UserPath.ToLowerInvariant()]=1}};"
            "$hits=@(foreach($n in $a.FindAll({param($x)$x -is [Management.Automation.Language.AssignmentStatementAst]},$true)){"
            "$targets=@($n.Left);if($n.Left -is [Management.Automation.Language.ArrayLiteralAst]){$targets=@($n.Left.Elements)};"
            "foreach($l in $targets){if($l -is [Management.Automation.Language.ConvertExpressionAst]){$l=$l.Child};if($l -isnot [Management.Automation.Language.VariableExpressionAst]){continue};"
            "$name=($l.VariablePath.UserPath -replace '^(script|global|local|private):','').ToLowerInvariant();"
            "$f=$n.Parent;while($null -ne $f -and $f -isnot [Management.Automation.Language.FunctionDefinitionAst]){$f=$f.Parent};"
            "if($v.ContainsKey($name) -and ($l.VariablePath.IsScript -or $l.VariablePath.IsGlobal -or $null -eq $f)){$l.Extent.Text+'='+$n.Right.Extent.Text}}});"
            "$sv=@($a.FindAll({param($x)$x -is [Management.Automation.Language.CommandAst] -and $x.GetCommandName() -in @('Set-Variable','New-Variable','sv','nv')},$true)).Count;"
            "'RESULT '+(@{validated=@($v.Keys|Sort-Object);hits=@($hits|Sort-Object);set_variable=$sv}|ConvertTo-Json -Compress)")
    result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-Command', code], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(next(line for line in result.stdout.splitlines() if line.startswith('RESULT '))[len('RESULT '):])


def test_validated_parameter_variables_are_written_only_with_checked_values():
    value = validated_parameter_assignments(SCRIPT)
    assert value['validated'] == ['attempt', 'slot', 'stage'] and value['set_variable'] == 0
    # Set-CaptureConstants runs after Invoke-AgyCaptureMain checked each value: a lowercase 32-hex -Attempt (-cnotmatch),
    # -Slot lowercased and -ceq slot1, -Stage lowercased and -cin signed-out|signed-in. A new write must be reviewed the same way.
    assert value['hits'] == ['$script:Attempt=$Attempt', '$script:Slot=$Slot', '$script:Stage=$Stage']


@pytest.mark.parametrize('invocation', ['file', 'command'])
@pytest.mark.parametrize('stage', ['signed-out', 'signed-in'], ids=['S5-signed-out', 'S7-signed-in'])
def test_toplevel_plan_for_each_documented_sitting_call(stage, invocation):
    result = smoke.run_toplevel(SCRIPT, ['-Slot', 'slot1', '-Stage', stage, '-Attempt', ATTEMPT], invocation=invocation)
    assert smoke.plan_mode_outcome(result, plan_schema=SMOKE_PLAN_SCHEMA) == 'plan', result.describe()
    plan = result.plan
    assert (plan['attempt'], plan['slot'], plan['stage']) == (ATTEMPT, 'slot1', stage)
    assert plan['target_root'] == str(COCHEM / ('AgyCapture4.2.7-windows-20261010-r4-v1-' + ATTEMPT + '-slot1-' + stage))
    assert plan['native_commands_executed'] == 0 and plan['native_model_jobs_executed'] == 0 and isinstance(plan['holds'], list)
