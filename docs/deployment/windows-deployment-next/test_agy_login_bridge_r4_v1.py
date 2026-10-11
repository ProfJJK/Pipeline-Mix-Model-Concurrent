"""Inert harness for worker_agy_login_bridge_r4_v1.py (Gemini build-manifest step 4).

No native CLI, scheduled task, worker account, worker profile, credential store or network is used. Every system
boundary is a fake: cochem_pipeline.windows, the support module's custody functions and launch_worker. The fake
child is a thread that writes synthetic agy transcripts into the bridge's real anonymous pipes and reads the one fed
line, so the real run(), run_loop, ChannelFile, feed_once, pump and cleanup produce the receipts that the PowerShell
harnesses then classify. Only synthetic, non-secret fixture values are used.
"""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

W = Path(__file__).resolve().parent
BRIDGE_PATH = W / 'worker_agy_login_bridge_r4_v1.py'
SUPPORT_PATH = W / 'worker-native-auth-status-six-r4-v1.py'
WRAPPER = W / 'login_pipeline_worker_interactive_agy_r4_v1.ps1'
HISTORY = W / 'agy-session-history-r4-v1.ps1'
PS = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bridge = load('agy_login_bridge_under_test', BRIDGE_PATH)
support_reference = load('agy_login_support_reference', SUPPORT_PATH)

NONCE = '0123456789abcdef' * 2
SLOT = 'slot3'
SID = 'S-1-5-21-1111111111-2222222222-3333333333-1003'
CODE = b'4/0Fixture-Code_PpQq-synthetic'
EMAIL = 'fixture-owner@example.invalid'
WINDOWS_FILE = r'C:\fixture\cochem_pipeline\windows.py'
REVISION = {'schema': 'cochem-installed-revision/1', 'source_sha256': support_reference.REVISION_SHA256, 'files': 109,
            'acceptance_files': 0, 'acceptance_sha256': None, 'verified': True, 'read_only': True}
TOKEN_OBSERVED = {'file_check': 'ok', 'file_token_present': True, 'file_token_bytes': 1676, 'file_token_regular': True,
                  'credential_manager_check': 'ok', 'credential_manager_entry_present': False,
                  'credential_manager_matching_entries': 0, 'token_contents_read': False}
URL = b'https://accounts.google.com/o/oauth2/auth?client_id=fixture&redirect_uri=https%3A%2F%2Fantigravity.google%2Foauth-callback'
PRINT_PROMPT = [('out', b'Starting OAuth authentication flow\r\nPlease visit the following URL to authorize the application:\r\n' + URL + b'\r\n'),
                ('out', b'Or, paste the authorization code here and press Enter: ')]
TUI_PROMPT = [('out', b'\x1b[2J\x1b[1mSign in to Antigravity\x1b[0m\r\n\x1b]8;;' + URL + b'\x1b\\Open the sign-in page\x1b]8;;\x1b\\\r\n'),
              ('out', b'\x1b[36mEnter the authorization code:\x1b[0m ')]
SCRIPTS = {
    'print_ok': PRINT_PROMPT + [('readline', None),
                                ('out', b'Successfully exchanged authorization code for token\nPrint mode: authenticated as ' + EMAIL.encode() + b'\n'),
                                ('out', b'gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n'), ('exit', 0)],
    'print_echo': PRINT_PROMPT + [('readline', None), ('echo', None), ('out', b'Successfully exchanged authorization code for token\n'), ('exit', 0)],
    'tui_hang': TUI_PROMPT + [('readline', None), ('out', b'\x1b[32mSuccessfully authenticated as ' + EMAIL.encode() + b'.\x1b[0m\r\n'), ('hang', None)],
    'fail_fast': [('out', b'Print mode: not logged in and no controlling terminal; cannot complete interactive login\n'),
                  ('out', b"Error: authentication required. Run 'agy' to log in.\n"), ('exit', 1)],
    'fail_after': PRINT_PROMPT + [('readline', None), ('out', b'Error: authentication failed: invalid_grant\n'), ('exit', 1)],
    'rate_limited': PRINT_PROMPT + [('readline', None), ('out', b'Error: authentication failed: 429 Too Many Requests\n'), ('exit', 1)],
    'wait_code': PRINT_PROMPT + [('readline', None), ('exit', 0)],
    'wait_code_tui': TUI_PROMPT + [('readline', None), ('exit', 0)],
    'verify_wait': [('out', b'Google needs to verify it is you before continuing.\n')] + PRINT_PROMPT + [('readline', None), ('exit', 0)],
    'callback': [('out', b'Authentication required. Please visit the URL to log in:\n' + URL + b'\nWaiting for authentication (timeout 60s)...\n'),
                 ('sleep', .3), ('out', b'Successfully authenticated as ' + EMAIL.encode() + b'.\n'), ('exit', 0)],
    # O-F7: plain display text (not redraw escapes) beyond the sanitized pre-input bound.
    'flood': PRINT_PROMPT + [('flood', (b'Waiting for authentication (timeout 60s)...\r\n', 6000)), ('readline', None), ('exit', 0)],
}
SCENARIOS = {
    'print_exit_zero': dict(mode='print', script='print_ok', action='submit'),
    'print_echo': dict(mode='print', script='print_echo', action='submit'),
    'tui_terminated': dict(mode='tui', script='tui_hang', action='submit', post_input=.6),
    'fail_before_input': dict(mode='print', script='fail_fast', action=None),
    'fail_after_input': dict(mode='print', script='fail_after', action='submit'),
    'rate_limited': dict(mode='print', script='rate_limited', action='submit'),
    'cancelled': dict(mode='print', script='wait_code', action='cancel'),
    'timed_out': dict(mode='tui', script='wait_code_tui', action=None, login_seconds=.8),
    'verify_cancelled': dict(mode='print', script='verify_wait', action='cancel'),
    'callback_exit_zero': dict(mode='print', script='callback', action=None),
    'native_custody_failure': dict(mode='print', script='print_ok', action=None, agy_before='0' * 64),
    'agy_changed_after': dict(mode='print', script='print_ok', action='submit', agy_after='1' * 64),
    'cleanup_unverified': dict(mode='print', script='print_ok', action='submit', close_raises=True),
    'output_bound': dict(mode='print', script='flood', action=None),
}


class FakeProcess:
    """A thread standing in for agy: writes transcripts to the real pipe, reads the one fed line."""
    def __init__(self, script, stdin, stdout, close_raises=False):
        self._in, self._out = os.dup(stdin.fileno()), os.dup(stdout.fileno())
        self.pid, self.creation_time_filetime, self._token = 4242, 133500000000000000, 'fixture-token'
        self.returncode, self.terminated, self.closed, self.received = None, False, False, None
        self.close_raises = close_raises
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(list(script),), daemon=True)
        self._thread.start()

    def _run(self, script):
        try:
            for kind, value in script:
                if self._stop.is_set():
                    break
                if kind == 'out':
                    os.write(self._out, value)
                elif kind == 'readline':
                    data = b''
                    while not data.endswith(b'\n'):
                        chunk = os.read(self._in, 1)
                        if not chunk:
                            break
                        data += chunk
                    self.received = data
                elif kind == 'echo':
                    os.write(self._out, self.received or b'')
                elif kind == 'flood':
                    chunk, count = value
                    for _ in range(count):
                        if self._stop.is_set():
                            break
                        try:
                            os.write(self._out, chunk)
                        except OSError:  # The bridge stopped reading and closed its end.
                            break
                elif kind == 'sleep':
                    time.sleep(value)
                elif kind == 'hang':
                    self._stop.wait(30)
                elif kind == 'exit':
                    if self.returncode is None:
                        self.returncode = value
                    return
            if self.returncode is None:
                self.returncode = 1 if self.terminated else 0
        finally:
            os.close(self._out)
            os.close(self._in)

    def poll(self):
        return None if self._thread.is_alive() else self.returncode

    def terminate(self):
        self.terminated = True
        if self.returncode is None:
            self.returncode = 1
        self._stop.set()

    def wait(self, timeout=None):
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise subprocess.TimeoutExpired('agy', timeout)
        return self.returncode

    def close(self):
        if self._thread.is_alive():
            self.terminate()
        self._thread.join(.5)
        if self.close_raises:
            raise RuntimeError('synthetic unverified Job cleanup')
        self.closed = True


class FakeEnvironment:
    def __init__(self, script, *, agy_before=None, agy_after=None, close_raises=False):
        self.script, self.close_raises = script, close_raises
        self.agy = [agy_before or bridge.AGY_SHA256, agy_after or bridge.AGY_SHA256]
        self.launches, self.require_stopped_calls, self.processes = [], 0, []
        self.win = SimpleNamespace(**{
            '__file__': WINDOWS_FILE, 'SYSTEM_SID': 'S-1-5-18',
            'require_system': lambda: None, 'validate_code_path': lambda path: None,
            'validate_private_directory': lambda path: None, 'validate_private_path': lambda path: None,
            'WorkerIdentity': lambda name, target: SimpleNamespace(name=name, credential_target=target),
            '_account_sid': lambda name: name, '_sid_text': lambda value: SID, 'launch_worker': self.launch_worker})
        self.support = SimpleNamespace(
            INSTALL=support_reference.INSTALL, NATIVE=support_reference.NATIVE, WINDOWS_SHA256=support_reference.WINDOWS_SHA256,
            INSTALL_RECEIPT_SHA256=support_reference.INSTALL_RECEIPT_SHA256, MANIFEST_SHA256=support_reference.MANIFEST_SHA256,
            RESOURCE_SHA256=support_reference.RESOURCE_SHA256, LAYOUT_SHA256=support_reference.LAYOUT_SHA256,
            CONFIG_SHA256=support_reference.CONFIG_SHA256, CONTRACTS=support_reference.CONTRACTS,
            safe_failure=support_reference.safe_failure, digest_file=self.digest_file, validate_interpreter=lambda: None,
            verify_r4_runtime=lambda win, pin: dict(REVISION), require_stopped=self.require_stopped,
            protected_json=self.protected_json, observe_child=self.observe_child)

    def digest_file(self, path):
        if Path(path) == bridge.NATIVE:
            return self.agy.pop(0) if len(self.agy) > 1 else self.agy[0]
        if str(path) == WINDOWS_FILE:
            return support_reference.WINDOWS_SHA256
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def require_stopped(self, win):
        self.require_stopped_calls += 1

    def protected_json(self, win, path):
        if Path(path).name == 'windows-layout.json':
            return ({'slots': {SLOT: {'identity': 'CoChem422Worker3', 'credential_target': 'CoChem422/slot3', 'sid': SID,
                                      'root': r'C:\fixture\slot3'}}}, support_reference.LAYOUT_SHA256)
        return ({'providers': {'gemini': {'executable': str(bridge.NATIVE)}}, 'execution_limits': {}}, support_reference.CONFIG_SHA256)

    def observe_child(self, win, process, sid, executable):
        return {'pid': process.pid, 'creation_time_filetime': process.creation_time_filetime, 'token_sid': sid,
                'token_matches_selected_worker': True, 'image_matches_reviewed_executable': True,
                'owned_job_membership_verified': True, 'profile_directory_sha256': 'c' * 64,
                'source': 'owned_windows_process_handle_and_child_token'}

    def launch_worker(self, identity, argv, cwd, stdin, stdout, stderr, limits=None):
        self.launches.append({'argv': list(argv), 'cwd': cwd, 'same_output': stdout is stderr, 'limits': limits})
        process = FakeProcess(SCRIPTS[self.script], stdin, stdout, self.close_raises)
        self.processes.append(process)
        return process


@contextlib.contextmanager
def patched(**values):
    saved = {name: getattr(bridge, name) for name in values}
    try:
        for name, value in values.items():
            setattr(bridge, name, value)
        yield
    finally:
        for name, value in saved.items():
            setattr(bridge, name, value)


def session_root(base):
    root = Path(base) / f'{bridge.ROOT_PREFIX}{SLOT}-{NONCE}'
    root.mkdir(parents=True)
    shutil.copyfile(BRIDGE_PATH, root / bridge.HELPER_NAME)
    shutil.copyfile(SUPPORT_PATH, root / bridge.SUPPORT_NAME)
    return root


def packet(value=CODE, nonce=NONCE):
    return b'cochem-login-input/1\n' + nonce.encode() + b'\n' + value + b'\n'


def wait_for(predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(.05)
    return False


def prompt_visible(root):
    log = root / 'operator.log'
    return log.exists() and re.search(r'(?i)(paste|enter) the authorization code', log.read_text('utf-8', 'replace')) is not None


def generate(base, name):
    """Run the real bridge run() for one scenario; returns (exit code, receipt dict, root, environment)."""
    scenario = SCENARIOS[name]
    root = session_root(base)
    env = FakeEnvironment(scenario['script'], agy_before=scenario.get('agy_before'), agy_after=scenario.get('agy_after'),
                          close_raises=scenario.get('close_raises', False))
    outcome = {}
    with patched(SESSION_PARENT=Path(base), __file__=str(root / bridge.HELPER_NAME),
                 runtime_modules=lambda: (env.win, SimpleNamespace(from_dict=lambda value: 'fixture-limits'), lambda path, **kw: None),
                 load_support=lambda path: env.support, observe_token_storage=lambda win, process: dict(TOKEN_OBSERVED),
                 POST_INPUT_SECONDS=scenario.get('post_input', 5), LOGIN_SECONDS=scenario.get('login_seconds', 20),
                 DRAIN_SECONDS=.5, CREDENTIAL_SECONDS=1.0):
        thread = threading.Thread(target=lambda: outcome.update(code=bridge.run(SLOT, NONCE, scenario['mode'])), daemon=True)
        thread.start()
        if scenario['action'] is not None:
            assert wait_for(lambda: prompt_visible(root)), 'fixture prompt never reached operator.log'
            target = root / ('input.once' if scenario['action'] == 'submit' else 'cancel.request')
            with target.open('xb') as stream:
                stream.write(packet() if scenario['action'] == 'submit' else packet(b'CANCEL'))
        thread.join(40)
        assert not thread.is_alive(), 'bridge run did not finish'
    receipt = json.loads((root / 'receipt.json').read_text(encoding='utf-8'))
    return outcome['code'], receipt, root, env


_CACHE = {}


def receipts(base):
    """All scenario receipts generated once per process (also used by the PowerShell harnesses)."""
    if not _CACHE:
        for name in SCENARIOS:
            folder = Path(base) / name
            folder.mkdir(parents=True, exist_ok=True)
            code, receipt, root, env = generate(folder, name)
            _CACHE[name] = {'code': code, 'receipt': receipt, 'root': root, 'env': env,
                            'text': (root / 'receipt.json').read_text(encoding='utf-8'),
                            'log': (root / 'operator.log').read_bytes() if (root / 'operator.log').exists() else b''}
    return _CACHE


@pytest.fixture(scope='module')
def generated(tmp_path_factory):
    return receipts(tmp_path_factory.mktemp('agy-bridge-receipts'))


def q(value):
    return "'" + str(value).replace("'", "''") + "'"


def ps_functions(path):
    """Dot-source every function definition of a script from its AST without running any top-level statement."""
    return ("$__tokens=$null;$__errors=$null;$__ast=[Management.Automation.Language.Parser]::ParseFile(" + q(path) + ",[ref]$__tokens,[ref]$__errors);"
            "if($__errors.Count){throw ($__errors|Out-String)};"
            "foreach($__f in $__ast.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){. ([scriptblock]::Create($__f.Extent.Text))};\n")


def ps_run(body, timeout=120):
    prefix = ("$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';Set-StrictMode -Version Latest;"
              "Import-Module (Join-Path $PSHOME 'Modules\\Microsoft.PowerShell.Utility\\Microsoft.PowerShell.Utility.psd1');"
              "Import-Module (Join-Path $PSHOME 'Modules\\Microsoft.PowerShell.Security\\Microsoft.PowerShell.Security.psd1');\n")
    encoded = base64.b64encode((prefix + body).encode('utf-16le')).decode()
    result = subprocess.run([PS, '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


# ----- mode -> argv table and argument handling -----

def test_mode_argv_table_is_exact():
    assert bridge.login_argv('print') == [str(bridge.NATIVE), '-p', '/model']
    assert bridge.login_argv('tui') == [str(bridge.NATIVE)]
    assert bridge.NATIVE == Path(r'C:\Program Files\CoChem\Native4.2.7-windows-20261006\agy.exe')


@pytest.mark.parametrize('mode', ['none', '', 'PRINT', 'Tui', 'print ', None, 'login', '--login'])
def test_any_other_mode_is_refused(mode):
    with pytest.raises(ValueError):
        bridge.login_argv(mode)


@pytest.mark.parametrize('argv', [
    ['--slot', 'slot3', '--nonce', NONCE, '--login-mode', 'none'],
    ['--slot', 'slot3', '--nonce', NONCE],
    ['--slot', 'slot7', '--nonce', NONCE, '--login-mode', 'print'],
    ['--slot', 'slot3', '--nonce', NONCE.upper(), '--login-mode', 'print'],
    ['--slot', 'slot3', '--nonce', '0' * 32, '--login-mode', 'print'],
    ['--slot', 'slot3', '--nonce', NONCE, '--login-mode', 'print', '--extra'],
])
def test_invalid_arguments_exit_3_without_receipt_or_runtime(argv, capsys, monkeypatch):
    monkeypatch.setattr(bridge, 'runtime_modules', lambda: pytest.fail('runtime must not be reached'))
    assert bridge.main(argv) == 3
    error = json.loads(capsys.readouterr().err)
    assert error == {'status': 'PRE_RECEIPT_FAILURE', 'error_type': 'ValueError'}


def test_pre_receipt_failure_exit_3_names_only_the_error_type(capsys, monkeypatch):
    def broken():
        raise RuntimeError('synthetic secret-bearing message ' + CODE.decode())
    monkeypatch.setattr(bridge, 'runtime_modules', broken)
    assert bridge.main(['--slot', SLOT, '--nonce', NONCE, '--login-mode', 'tui']) == 3
    text = capsys.readouterr().err
    assert json.loads(text) == {'status': 'PRE_RECEIPT_FAILURE', 'error_type': 'RuntimeError'}
    assert CODE.decode() not in text


def test_session_root_and_constants():
    assert bridge.session_root(SLOT, NONCE) == Path(r'C:\Program Files\CoChem') / f'InteractiveAgy427-r4-{SLOT}-{NONCE}'
    assert (bridge.MAX_INPUT, bridge.MAX_OUTPUT, bridge.LOGIN_SECONDS, bridge.POST_INPUT_SECONDS) == (2048, 131072, 600, 120)
    assert bridge.INSTALL == Path(r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4')
    assert bridge.ACCEPTED_STATUSES == ('LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED', 'LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED')


# ----- private channel (from test_claude_login_bridge_r3.py) -----

@pytest.mark.parametrize('code', [b'fixture-code', b'x' * 2048, 'fixture-\u8a66'.encode()])
def test_packet_exact_bound_and_utf8(code):
    assert bridge.parse_packet(packet(code), NONCE) == code


@pytest.mark.parametrize('raw', [b'', packet(b''), packet(b'x' * 2049), packet(b'a\nb'), packet(b'a\rb'), packet(b'a\0b'),
                                 packet(b'\xff'), packet(nonce='b' * 32), packet()[:-1], packet() + b'\n'])
def test_packet_refuses_unbound_or_multiline_values_without_echo(raw):
    with pytest.raises((ValueError, UnicodeError)) as error:
        bridge.parse_packet(raw, NONCE)
    assert CODE.decode() not in str(error.value)


def test_cancel_exact_value_only():
    assert bridge.parse_packet(packet(b'CANCEL'), NONCE, cancel=True) == b'CANCEL'
    with pytest.raises(ValueError):
        bridge.parse_packet(packet(), NONCE, cancel=True)


def test_channel_file_reads_single_link_and_deletes_only_after_request(tmp_path):
    path = tmp_path / 'input.once'; path.write_bytes(packet())
    checked = []
    item = bridge.ChannelFile(path, SimpleNamespace(validate_private_path=lambda p: checked.append(p)))
    assert checked == [path] and item.raw == packet() and path.exists()
    with pytest.raises(PermissionError):
        path.write_bytes(b'replaced')
    with pytest.raises(PermissionError):
        path.unlink()
    item.delete_after_verified_cleanup()
    assert not path.exists() and item.raw == b''


def test_channel_file_failed_cleanup_preserves_file(tmp_path):
    path = tmp_path / 'input.once'; path.write_bytes(packet())
    item = bridge.ChannelFile(path, SimpleNamespace(validate_private_path=lambda p: None))
    item.close()
    assert path.read_bytes() == packet()


def test_channel_file_rejects_hardlinks(tmp_path):
    path = tmp_path / 'input.once'; path.write_bytes(packet())
    os.link(path, tmp_path / 'second')
    with pytest.raises(ValueError, match='single-link'):
        bridge.ChannelFile(path, SimpleNamespace(validate_private_path=lambda p: None))


class Writer(io.BytesIO):
    def close(self):
        self.captured = self.getvalue()
        super().close()


def test_feed_is_one_line_flushed_then_closed():
    stream = Writer(); bridge.feed_once(stream, b'synthetic-code')
    assert stream.closed and stream.captured == b'synthetic-code\n'


def test_feed_line_endings_are_mode_bound_and_closed_after_use():
    assert bridge.LINE_ENDINGS == {'print': b'\n', 'tui': b'\r\n'} and set(bridge.LINE_ENDINGS) == set(bridge.LOGIN_ARGUMENTS)
    stream = Writer(); bridge.feed_once(stream, b'synthetic-code', b'\r\n')
    assert stream.closed and stream.captured == b'synthetic-code\r\n'
    stream = Writer()
    with pytest.raises(ValueError, match='line endings'):
        bridge.feed_once(stream, b'synthetic-code', b'\r')
    assert stream.closed and stream.captured == b''


def test_partial_stdin_write_fails_without_retry_and_closes():
    class ShortWriter(Writer):
        def write(self, value):
            return super().write(value[:3])
    stream = ShortWriter()
    with pytest.raises(OSError, match='incomplete line'):
        bridge.feed_once(stream, b'synthetic-code')
    assert stream.closed and stream.captured == b'syn'


def test_actual_windows_anonymous_pipe_accepts_maximum_line_without_reader():
    r, w = os.pipe()
    try:
        bridge.feed_once(os.fdopen(w, 'wb', buffering=0), b'x' * 2048)
        assert os.read(r, 4096) == b'x' * 2048 + b'\n'
    finally:
        os.close(r)


# ----- display-safe publication and marker classification -----

def test_publisher_strips_escapes_and_keeps_hyperlink_targets():
    raw = b'\x1b[1mSign in\x1b[0m\r\n\x1b]8;;https://accounts.google.com/x\x1b\\Open\x1b]8;;\x1b\\\x07\x1b]0;title\x07 done' + '\u009b'.encode()
    text = bridge.Publisher().feed(raw, final=True)
    assert text == 'Sign in\n https://accounts.google.com/x Open done'


@pytest.mark.parametrize('split', range(1, 40))
def test_publisher_never_splits_an_escape_or_a_character(split):
    raw = 'A\x1b[38;5;196mB\x1b]8;;https://accounts.google.com/a\x07L\x1b]8;;\x07 \u8a66 \u202eend'.encode()
    publisher = bridge.Publisher()
    text = publisher.feed(raw[:split]) + publisher.feed(raw[split:]) + publisher.feed(b'', final=True)
    assert text == 'AB https://accounts.google.com/a L \u8a66 end'


def test_after_input_phrases_all_contain_a_space_and_never_match_a_code():
    for name, phrases in bridge.AFTER_PHRASES.items():
        assert phrases and all(' ' in phrase and phrase == phrase.casefold() for phrase in phrases), name
    assert bridge.SHARED_MARKERS == ('rate_limit_present',) and not set(bridge.SHARED_MARKERS) & set(bridge.AFTER_PHRASES)
    assert set(bridge.AFTER_PHRASES) | set(bridge.SHARED_MARKERS) == set(bridge.BEFORE_PATTERNS) - {'url_present', 'google_accounts_url_present'}
    import random
    rng = random.Random(4207)
    alphabet = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/.:?&=%'
    for _ in range(300):
        code = ''.join(rng.choice(alphabet) for _ in range(rng.randint(8, 400)))
        code += 'verifyappealratelimittoomanyrequests429resourceexhausted'
        assert not any(bridge.classify_markers(code, after_input=True).values())
    # Google authorization codes: '4/0' and URL-safe base64. '429' and 'ratelimit' glued to code characters are never
    # markers. (Residual, accepted: '-'/'_' read as spaces, so a fragment delimited by them that is exactly '429' or
    # starts with 'ratelimit' would match - about 4e-7 per random code, and only towards an orderly pause.)
    alnum = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    for _ in range(2000):
        code = '4/0' + ''.join(rng.choice(alnum + '-_') for _ in range(rng.randint(40, 120)))
        position = rng.randint(3, len(code))
        token = rng.choice(('429', '4290', '1429', 'ratelimit', 'ratelimited'))
        code = code[:position] + rng.choice(alnum) + token + rng.choice(alnum) + code[position:]
        assert not bridge.classify_markers(code, after_input=True)['rate_limit_present'], code


# O-F8: '-' and '_' read as spaces; the rate-limit marker is one expression shared by both phases.
RATE_LIMIT_TEXTS = ['Error: RESOURCE_EXHAUSTED: per-user quota', 'oauth2: 429 ratelimit', 'rate-limited, retry in 60s',
                    'HTTP 429 (Too Many Requests)', 'Rate_Limit exceeded', 'Quota-Exceeded for this project',
                    'status 429.', 'error: 429', 'Error: (429)', 'resource-exhausted', 'X-RateLimit-Remaining: 0', 'please try-again later',
                    'too_many_requests', 'ratelimited by the server']
NO_RATE_LIMIT_TEXTS = ['Verifying token signature', 'Successfully exchanged authorization code for token', '4290 bytes',
                       '1429 items', 'v4.29', 'https://accounts.google.com/o/oauth2/auth?state=a429b&port=4290', 'callback /429/x',
                       'https://example.invalid/cb?error=429&x=1', 'http://localhost:429/callback',
                       'generated limits', 'quota ok', 'resource exhaust', 'accurately limited']


@pytest.mark.parametrize('text', RATE_LIMIT_TEXTS)
def test_rate_limit_spellings_pause_identically_before_and_after_input(text):
    before = bridge.classify_markers(text, after_input=False)
    after = bridge.classify_markers(text, after_input=True)
    assert before['rate_limit_present'] is True and after['rate_limit_present'] is True, text


@pytest.mark.parametrize('text', NO_RATE_LIMIT_TEXTS)
def test_rate_limit_marker_ignores_codes_ports_and_ordinary_numbers_in_both_phases(text):
    before = bridge.classify_markers(text, after_input=False)
    after = bridge.classify_markers(text, after_input=True)
    assert before['rate_limit_present'] is False and after['rate_limit_present'] is False, text


def test_rate_limit_marker_sets_are_identical_over_a_mixed_corpus():
    import random
    rng = random.Random(4208)
    words = ['rate', 'limit', 'ratelimit', 'too', 'many', 'requests', 'resource', 'exhausted', 'quota', 'exceeded', 'try', 'again',
             'later', '429', '4290', 'oauth2:', '(429)', 'code', 'http', 'error', 'x', 'please']
    separators = [' ', '-', '_', '  ', '\n', '\t', ': ']
    for _ in range(3000):
        text = ''.join(rng.choice(words) + rng.choice(separators) for _ in range(rng.randint(1, 8)))
        assert (bridge.classify_markers(text, after_input=False)['rate_limit_present']
                == bridge.classify_markers(text, after_input=True)['rate_limit_present']), text
    assert "'rate_limit_present': r'" in BRIDGE_PATH.read_text() and "'" not in bridge.BEFORE_PATTERNS['rate_limit_present']


def test_markers_cover_success_failure_and_pause_texts():
    before = bridge.classify_markers('Please visit https://accounts.google.com/o/oauth2/auth?x\nOr, PASTE the  authorization\ncode here', after_input=False)
    assert before['url_present'] and before['google_accounts_url_present'] and before['paste_prompt_present']
    assert not before['rate_limit_present'] and not before['verification_present']
    assert bridge.classify_markers('Print mode: not logged in and no controlling terminal', after_input=False)['no_controlling_terminal_present']
    assert bridge.classify_markers('Google needs to verify it is you', after_input=False)['verification_present']
    assert not bridge.classify_markers('Verifying token signature', after_input=False)['verification_present']
    after = bridge.classify_markers('Error: authentication failed: 429 Too Many Requests', after_input=True)
    assert after['authentication_failed_present'] and after['rate_limit_present']
    assert bridge.classify_markers('Successfully exchanged authorization code for token', after_input=True)['token_exchanged_present']
    assert bridge.pause_marker_seen({'before_input': {'appeal_present': True}, 'after_input': {}})
    assert not bridge.pause_marker_seen(None) and not bridge.pause_marker_seen({'before_input': {}, 'after_input': {'token_exchanged_present': True}})


def test_session_output_bounds_publication_and_never_publishes_after_input():
    log, report = io.BytesIO(), {}
    output = bridge.SessionOutput(log, report)
    output.accept(b'visible\n', submitted=False)
    output.accept(CODE + b'\nafter text\n', submitted=True)
    output.accept(b'x' * (bridge.MAX_OUTPUT + 5), submitted=True)
    output.finish()
    assert log.getvalue() == b'visible\n'
    assert report['native_output_bytes_before_input'] == 8 and report['native_output_bound_reached_after_input'] is True
    assert report['native_output_published_bytes_before_input'] == 8 and report.get('native_output_bound_reached_before_input') is not True
    assert set(report['native_markers']) == {'before_input', 'after_input'} and report['pause_marker_seen'] is False
    assert CODE.decode() not in json.dumps(report)
    bounded_report = {}
    bounded = bridge.SessionOutput(io.BytesIO(), bounded_report)
    with pytest.raises(bridge.NativeOutputBoundError, match='output exceeded'):
        bounded.accept(b'x' * (bridge.MAX_OUTPUT + 1), submitted=False)
    assert bounded.log.getvalue() == b'' and bounded_report['native_output_bound_reached_before_input'] is True
    assert issubclass(bridge.NativeOutputBoundError, ValueError)


# O-F7: the auditor's redraw frame (onboard_repros.py): 110 raw bytes, of which only the display text is published.
REDRAW_FRAME = ('\x1b[2K\r\x1b[38;5;212m' + chr(0x280B) + '\x1b[0m Waiting for authentication (timeout 60s)... '
                '\x1b[2mPaste the authorization code:\x1b[0m \x1b[1A').encode('utf-8')


def test_preinput_bound_counts_published_display_bytes_not_redraw_escapes():
    log, report = io.BytesIO(), {}
    output = bridge.SessionOutput(log, report)
    published_frame = len(bridge.sanitize_text(REDRAW_FRAME.decode('utf-8')).encode('utf-8'))
    assert len(REDRAW_FRAME) == 110 and published_frame < 85
    frames = bridge.MAX_OUTPUT // len(REDRAW_FRAME) + 200      # beyond the old raw-byte bound (1191 frames)
    for _ in range(frames):
        output.accept(REDRAW_FRAME, submitted=False)
    assert report['native_output_bytes_before_input'] == frames * len(REDRAW_FRAME) > bridge.MAX_OUTPUT
    assert report['native_output_published_bytes_before_input'] == len(log.getvalue()) <= bridge.MAX_OUTPUT
    assert report.get('native_output_bound_reached_before_input') is not True
    with pytest.raises(bridge.NativeOutputBoundError):
        while True:
            output.accept(REDRAW_FRAME, submitted=False)
    # Nothing beyond the bound is published, and the stop never splits a published frame.
    assert len(log.getvalue()) <= bridge.MAX_OUTPUT and report['native_output_bound_reached_before_input'] is True
    assert report['native_output_published_bytes_before_input'] == len(log.getvalue())
    assert len(log.getvalue()) % published_frame == 0 and b'\x1b' not in log.getvalue()


def test_escape_only_redraws_are_bounded_by_the_login_window_not_by_bytes(tmp_path, monkeypatch, fast):
    events = queue.Queue()
    for _ in range(200):
        events.put(b'\x1b[2K\x1b[1A\x1b[?25l\x1b[?25h' * 160)
    monkeypatch.setattr(bridge, 'LOGIN_SECONDS', .4)
    log, report = io.BytesIO(), {}
    with pytest.raises(TimeoutError):
        bridge.run_loop(Process([None]), Writer(), events, log, tmp_path, NONCE, None, report, [])
    assert report['native_output_bytes_before_input'] > bridge.MAX_OUTPUT and log.getvalue() == b''
    assert report.get('native_output_published_bytes_before_input', 0) == 0
    assert report.get('native_output_bound_reached_before_input') is not True and report['input_closed_marker_written'] is True


def test_pump_signals_eof_and_failure():
    events, stopped = queue.Queue(), threading.Event()
    bridge.pump(io.BytesIO(b'abc'), events, stopped)
    assert [events.get_nowait(), events.get_nowait()] == [b'abc', bridge.EOF]

    class Broken(io.BytesIO):
        def read(self, size=-1):
            raise OSError('synthetic broken pipe')
    events = queue.Queue()
    bridge.pump(Broken(), events, threading.Event())
    assert events.get_nowait() is None


# ----- run_loop with fake processes (from test_claude_login_bridge_r3.py, plus the post-input rules) -----

class Process:
    def __init__(self, codes=(0,)):
        self.codes, self.terminated, self.waited = list(codes), False, None

    def poll(self):
        return self.codes.pop(0) if len(self.codes) > 1 else self.codes[0]

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.waited = timeout
        return 1


@pytest.fixture()
def fast(monkeypatch):
    monkeypatch.setattr(bridge, 'DRAIN_SECONDS', 0)


def test_native_echo_after_submission_never_reaches_log(tmp_path, monkeypatch, fast):
    (tmp_path / 'input.once').write_bytes(packet(b'echo-me'))
    monkeypatch.setattr(bridge, 'ChannelFile', lambda path, win: SimpleNamespace(raw=path.read_bytes()))
    events = queue.Queue(); events.put(b'echo-me\n')
    log, writer, report = io.BytesIO(), Writer(), {}
    result = bridge.run_loop(Process([0]), writer, events, log, tmp_path, NONCE, None, report, [])
    assert result == 0 and writer.captured == b'echo-me\n' and log.getvalue() == b''
    assert report['one_line_submitted'] is True and 'echo-me' not in json.dumps(report)


def test_preinput_browser_instructions_are_published_sanitized(tmp_path, fast):
    events = queue.Queue(); events.put(b'\x1b[1mVisit\x1b[0m ' + URL + b'\r\n')
    log, writer, report = io.BytesIO(), Writer(), {}
    assert bridge.run_loop(Process([0]), writer, events, log, tmp_path, NONCE, None, report, []) == 0
    assert log.getvalue() == b'Visit ' + URL + b'\n' and not writer.closed
    assert report['native_markers']['before_input']['google_accounts_url_present'] is True
    writer.close()


def test_cancel_never_feeds_provider(tmp_path, monkeypatch, fast):
    (tmp_path / 'cancel.request').write_bytes(packet(b'CANCEL'))
    (tmp_path / 'input.once').write_bytes(packet())
    monkeypatch.setattr(bridge, 'ChannelFile', lambda path, win: SimpleNamespace(raw=path.read_bytes()))
    writer, report = Writer(), {}
    with pytest.raises(InterruptedError):
        bridge.run_loop(None, writer, queue.Queue(), io.BytesIO(), tmp_path, NONCE, None, report, [])
    assert writer.getvalue() == b'' and report['operator_cancelled'] is True and 'one_line_submitted' not in report


def test_login_deadline_expires_without_waiting_for_native(tmp_path, monkeypatch):
    clock = iter([0, 601]); monkeypatch.setattr(bridge.time, 'monotonic', lambda: next(clock))
    with pytest.raises(TimeoutError):
        bridge.run_loop(None, Writer(), queue.Queue(), io.BytesIO(), tmp_path, NONCE, None, {}, [])


def test_output_limit_fails_before_log_publication(tmp_path):
    events = queue.Queue(); events.put(b'x' * (bridge.MAX_OUTPUT + 1)); log = io.BytesIO()
    with pytest.raises(ValueError, match='output exceeded'):
        bridge.run_loop(None, Writer(), events, log, tmp_path, NONCE, None, {}, [])
    assert log.getvalue() == b''


def test_post_input_timeout_terminates_the_still_running_session(tmp_path, monkeypatch, fast):
    (tmp_path / 'input.once').write_bytes(packet())
    monkeypatch.setattr(bridge, 'ChannelFile', lambda path, win: SimpleNamespace(raw=path.read_bytes()))
    monkeypatch.setattr(bridge, 'POST_INPUT_SECONDS', .3)
    process, report = Process([None]), {}
    assert bridge.run_loop(process, Writer(), queue.Queue(), io.BytesIO(), tmp_path, NONCE, None, report, []) == 1
    assert process.terminated and process.waited == bridge.TERMINATE_WAIT_SECONDS and report['terminated_after_input'] is True
    assert bridge.terminal_status(1, report) == 'LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED'


CLOSED_PACKET = b'cochem-login-input-closed/1\n' + NONCE.encode() + b'\n'


@pytest.mark.parametrize('exit_path', ['deadline', 'cancel', 'native_exit', 'post_input', 'output_bound'])
def test_read_loop_always_leaves_the_closed_marker_before_it_returns(tmp_path, monkeypatch, fast, exit_path):
    """O-F6: the wrapper refuses input once input.closed exists; the bridge writes it on every exit from its read loop."""
    monkeypatch.setattr(bridge, 'ChannelFile', lambda path, win: SimpleNamespace(raw=path.read_bytes()))
    events, process, report, expected = queue.Queue(), Process([None]), {}, None
    if exit_path == 'deadline':
        monkeypatch.setattr(bridge, 'LOGIN_SECONDS', .2); expected = TimeoutError
    elif exit_path == 'cancel':
        (tmp_path / 'cancel.request').write_bytes(packet(b'CANCEL')); expected = InterruptedError
    elif exit_path == 'native_exit':
        process = Process([0])
    elif exit_path == 'post_input':
        (tmp_path / 'input.once').write_bytes(packet()); monkeypatch.setattr(bridge, 'POST_INPUT_SECONDS', .2)
    else:
        events.put(b'x' * (bridge.MAX_OUTPUT + 1)); expected = bridge.NativeOutputBoundError
    if expected is None:
        bridge.run_loop(process, Writer(), events, io.BytesIO(), tmp_path, NONCE, None, report, [])
    else:
        with pytest.raises(expected):
            bridge.run_loop(process, Writer(), events, io.BytesIO(), tmp_path, NONCE, None, report, [])
    assert (tmp_path / 'input.closed').read_bytes() == CLOSED_PACKET and report['input_closed_marker_written'] is True


def test_input_arriving_after_the_login_window_is_never_consumed(tmp_path, monkeypatch, fast):
    clock = iter([0, 601]); monkeypatch.setattr(bridge.time, 'monotonic', lambda: next(clock))
    (tmp_path / 'input.once').write_bytes(packet())
    monkeypatch.setattr(bridge, 'ChannelFile', lambda path, win: pytest.fail('a late input must not be opened'))
    writer, report = Writer(), {}
    with pytest.raises(TimeoutError):
        bridge.run_loop(None, writer, queue.Queue(), io.BytesIO(), tmp_path, NONCE, None, report, [])
    assert writer.getvalue() == b'' and 'one_line_submitted' not in report and (tmp_path / 'input.closed').exists()


def test_closed_marker_failure_is_recorded_without_masking_the_loop_result(tmp_path, monkeypatch, fast):
    (tmp_path / 'input.closed').write_bytes(b'pre-existing')
    report = {}
    assert bridge.run_loop(Process([0]), Writer(), queue.Queue(), io.BytesIO(), tmp_path, NONCE, None, report, []) == 0
    assert report['input_closed_marker_written'] is False and (tmp_path / 'input.closed').read_bytes() == b'pre-existing'


def test_terminal_status_table():
    assert bridge.terminal_status(0, {}) == 'LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED'
    assert bridge.terminal_status(1, {}) == 'LOGIN_COMMAND_FAILED'
    assert bridge.terminal_status(0, {'terminated_after_input': True}) == 'LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED'


@pytest.mark.parametrize('fault', ['job', 'reader', 'daemon', 'none'])
def test_channel_deletion_requires_terminal_job_and_reader_proof(fault):
    events = []

    def close():
        events.append('job-proof')
        if fault == 'job':
            raise RuntimeError('synthetic unverified cleanup')

    def postcheck():
        events.append('daemon-proof')
        if fault == 'daemon':
            raise RuntimeError('synthetic daemon uncertainty')
    channel = SimpleNamespace(delete_after_verified_cleanup=lambda: events.append('delete'))
    thread = SimpleNamespace(join=lambda timeout: events.append('reader-join'), is_alive=lambda: fault == 'reader')
    report = {'cleanup_verified': False, 'input_file_deleted': False}
    if fault != 'none':
        with pytest.raises(RuntimeError):
            bridge.cleanup_session(SimpleNamespace(close=close), Writer(), threading.Event(), [thread], [channel], report, postcheck)
        assert 'delete' not in events
    else:
        bridge.cleanup_session(SimpleNamespace(close=close), Writer(), threading.Event(), [thread], [channel], report, postcheck)
        assert events == ['job-proof', 'reader-join', 'daemon-proof', 'delete']
        assert report == {'cleanup_verified': True, 'input_file_deleted': True}


# ----- token-storage observation (existence/size and Credential Manager names only) -----

def test_token_profile_directory_reads_the_worker_token_profile_with_a_bound():
    import ctypes
    path = r'C:\Users\CoChem422Worker3'

    def get(token, buffer, count, size=len(path) + 1):
        assert token == 'worker-token'
        count._obj.value = size
        if buffer is None:
            return 0
        buffer.value = path
        return 1
    win = SimpleNamespace(DWORD=ctypes.c_uint32, _api=lambda: {'userenv': SimpleNamespace(GetUserProfileDirectoryW=get)},
                          _check=lambda value, operation: value)
    assert bridge.token_profile_directory(win, 'worker-token') == Path(path)
    win._api = lambda: {'userenv': SimpleNamespace(GetUserProfileDirectoryW=lambda t, b, c: get(t, b, c, size=0))}
    with pytest.raises(ValueError, match='invalid bound'):
        bridge.token_profile_directory(win, 'worker-token')


def test_file_token_observation_existence_and_size_only(tmp_path):
    assert bridge.file_token_observation(tmp_path) == {'file_check': 'ok', 'file_token_present': False,
                                                       'file_token_bytes': None, 'file_token_regular': None}
    token = tmp_path.joinpath(*bridge.TOKEN_FILE_PARTS); token.parent.mkdir(parents=True); token.write_bytes(b't' * 1676)
    assert bridge.file_token_observation(tmp_path) == {'file_check': 'ok', 'file_token_present': True,
                                                       'file_token_bytes': 1676, 'file_token_regular': True}
    token.unlink(); token.mkdir()
    assert bridge.file_token_observation(tmp_path)['file_token_regular'] is False


class CredentialApi:
    def __init__(self, names=(), impersonate=True, enumerate_ok=True, error=0, revert=True):
        self.names, self.ok, self.enum_ok, self.error, self.revert_ok = list(names), impersonate, enumerate_ok, error, revert
        self.calls = []

    def impersonate(self, token):
        self.calls.append(('impersonate', token)); return self.ok

    def enumerate(self, target, flags, count, pointer):
        self.calls.append(('enumerate', target, flags))
        if not self.enum_ok:
            return False
        count._obj.value = len(self.names)
        return True

    def last_error(self):
        return self.error

    def target_names(self, pointer, count):
        assert count == len(self.names)
        return iter(self.names)

    def free(self, pointer):
        self.calls.append(('free',))

    def revert(self):
        self.calls.append(('revert',)); return self.revert_ok


def test_credential_names_are_counted_under_impersonation_and_always_reverted():
    api = CredentialApi(['jetski-standalone-oauth-token:' + EMAIL, 'Antigravity/other', 'unrelated', None])
    result = bridge.count_matching_credentials('worker-token', api)
    assert result == {'credential_manager_check': 'ok', 'credential_manager_entry_present': True, 'credential_manager_matching_entries': 2}
    assert api.calls == [('impersonate', 'worker-token'), ('enumerate', None, 0), ('free',), ('revert',)]
    assert EMAIL not in json.dumps(result)
    empty = CredentialApi(enumerate_ok=False, error=bridge.ERROR_NOT_FOUND)
    assert bridge.count_matching_credentials('t', empty)['credential_manager_matching_entries'] == 0 and ('revert',) in empty.calls
    failed = CredentialApi(enumerate_ok=False, error=5)
    assert bridge.count_matching_credentials('t', failed)['credential_manager_check'] == 'failed' and ('revert',) in failed.calls
    assert bridge.count_matching_credentials('t', CredentialApi(impersonate=False))['credential_manager_check'] == 'failed'
    unreverted = CredentialApi(['jetski'], revert=False)
    assert bridge.count_matching_credentials('t', unreverted) == {'credential_manager_check': 'failed', 'credential_manager_entry_present': None,
                                                                  'credential_manager_matching_entries': None}


def test_credential_observation_runs_on_a_dedicated_thread_with_a_bound():
    seen = []
    result = bridge.credential_observation('t', api_factory=lambda: seen.append(threading.current_thread().name) or CredentialApi(['jetski']))
    assert result['credential_manager_entry_present'] is True and seen == ['agy-credential-names']
    blocked = threading.Event()

    class Slow(CredentialApi):
        def impersonate(self, token):
            blocked.wait(5); return False
    assert bridge.credential_observation('t', api_factory=Slow, timeout=.2)['credential_manager_check'] == 'timed_out'
    blocked.set()

    def broken():
        raise OSError('synthetic')
    assert bridge.credential_observation('t', api_factory=broken)['credential_manager_check'] == 'failed'


def test_observe_token_storage_combines_both_checks_without_reading_contents(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, 'token_profile_directory', lambda win, token: tmp_path)
    monkeypatch.setattr(bridge, 'credential_observation', lambda token: {'credential_manager_check': 'ok', 'credential_manager_entry_present': False,
                                                                         'credential_manager_matching_entries': 0})
    value = bridge.observe_token_storage(None, SimpleNamespace(_token='t'))
    assert value == {'file_check': 'ok', 'file_token_present': False, 'file_token_bytes': None, 'file_token_regular': None,
                     'credential_manager_check': 'ok', 'credential_manager_entry_present': False,
                     'credential_manager_matching_entries': 0, 'token_contents_read': False}
    monkeypatch.setattr(bridge, 'token_profile_directory', lambda win, token: (_ for _ in ()).throw(OSError('x')))
    assert bridge.observe_token_storage(None, SimpleNamespace(_token='t'))['file_check'] == 'failed'


def test_load_support_requires_the_pinned_module(tmp_path):
    shutil.copyfile(SUPPORT_PATH, tmp_path / bridge.SUPPORT_NAME)
    module = bridge.load_support(tmp_path)
    assert module.CONTRACTS['gemini']['sha256'] == bridge.AGY_SHA256 and module.INSTALL == bridge.INSTALL
    (tmp_path / bridge.SUPPORT_NAME).write_bytes(SUPPORT_PATH.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='support changed'):
        bridge.load_support(tmp_path)


# ----- the real run() end to end against fakes -----

RECEIPT_KEYS = {'schema', 'slot', 'nonce', 'login_mode', 'native_arguments', 'system_sid', 'helper_sha256', 'support_sha256', 'status',
                'cleanup_verified', 'one_line_submitted', 'input_file_deleted', 'operator_cancelled', 'terminated_after_input',
                'login_commands_executed', 'model_jobs_executed', 'authentication_verified', 'activation_ready', 'secret_published',
                'native_output_after_input_published', 'native_output_bytes_before_input', 'native_output_bound_reached_after_input',
                'pause_marker_seen', 'native_markers', 'token_storage_observed',
                'started_at_unix_ms', 'finished_at_unix_ms', 'revision', 'runtime_root', 'install_receipt_sha256',
                'source_manifest_sha256', 'resource_limits_sha256', 'layout_sha256', 'config_sha256',
                # Added by the onboarding fix wave (O-F6, O-F7); every earlier field keeps its name and meaning.
                'input_closed_marker_written', 'native_output_published_bytes_before_input', 'native_output_bound_reached_before_input'}


def test_print_mode_end_to_end_exit_zero(generated):
    item = generated['print_exit_zero']; receipt = item['receipt']
    assert item['code'] == 0 and receipt['status'] == 'LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED'
    assert item['env'].launches == [{'argv': [str(bridge.NATIVE), '-p', '/model'], 'cwd': r'C:\fixture\slot3', 'same_output': True,
                                     'limits': 'fixture-limits'}]
    assert RECEIPT_KEYS <= set(receipt) and set(receipt) - RECEIPT_KEYS == {
        'native_executable_sha256', 'native_executable_sha256_after', 'process', 'native_exit_code'}
    assert receipt['cleanup_verified'] and receipt['one_line_submitted'] and receipt['input_file_deleted']
    assert receipt['login_commands_executed'] == 1 and receipt['model_jobs_executed'] == 0 and receipt['native_exit_code'] == 0
    assert receipt['helper_sha256'] == hashlib.sha256(BRIDGE_PATH.read_bytes()).hexdigest()
    assert receipt['support_sha256'] == bridge.SUPPORT_SHA256 == hashlib.sha256(SUPPORT_PATH.read_bytes()).hexdigest()
    assert receipt['native_markers']['after_input']['token_exchanged_present'] and receipt['native_markers']['after_input']['authenticated_as_present']
    assert receipt['native_markers']['before_input']['paste_prompt_present'] and not receipt['pause_marker_seen']
    assert receipt['token_storage_observed'] == TOKEN_OBSERVED and receipt['native_arguments'] == ['-p', '/model']
    assert item['env'].processes[0].received == CODE + b'\n' and item['env'].require_stopped_calls == 2
    assert not (item['root'] / 'input.once').exists()
    assert receipt['input_closed_marker_written'] is True and (item['root'] / 'input.closed').read_bytes() == CLOSED_PACKET
    assert receipt['native_output_published_bytes_before_input'] == len(item['log']) and receipt['native_output_bound_reached_before_input'] is False


@pytest.mark.parametrize('name', [name for name in SCENARIOS if name != 'native_custody_failure'])
def test_every_launched_session_leaves_the_closed_marker(generated, name):
    item = generated[name]
    assert item['receipt']['input_closed_marker_written'] is True and (item['root'] / 'input.closed').read_bytes() == CLOSED_PACKET


def test_output_bound_stop_is_a_distinct_cleaned_up_failure(generated):
    """O-F7: plain display text beyond the sanitized bound stops the session with its own error type."""
    item = generated['output_bound']; receipt = item['receipt']
    assert item['code'] == 2 and receipt['status'] == 'LOGIN_FAILED_OR_CANCELLED' and receipt['cleanup_verified'] is True
    assert receipt['failure'] == {'phase': 'native_wait', 'error_type': 'NativeOutputBoundError', 'winerror': None}
    assert receipt['native_output_bound_reached_before_input'] is True and not receipt['one_line_submitted']
    assert receipt['native_output_published_bytes_before_input'] == len(item['log']) <= bridge.MAX_OUTPUT
    assert receipt['native_output_bytes_before_input'] >= receipt['native_output_published_bytes_before_input']
    assert 'native_exit_code' not in receipt and 'native_executable_sha256_after' not in receipt
    assert receipt['token_storage_observed']['file_check'] == 'not_run' and receipt['input_closed_marker_written'] is True
    assert receipt['native_markers']['before_input']['waiting_line_present'] and not receipt['pause_marker_seen']


@pytest.mark.parametrize('name', list(SCENARIOS))
def test_no_code_email_or_url_in_any_receipt_and_no_code_or_post_input_text_in_operator_log(generated, name):
    item = generated[name]
    for secret in (CODE.decode(), EMAIL, 'https://', 'invalid_grant', 'Too Many Requests'):
        assert secret not in item['text']
    assert CODE not in item['log'] and b'Successfully exchanged' not in item['log'] and b'invalid_grant' not in item['log']
    assert b'\x1b' not in item['log'] and b'\r' not in item['log']
    assert item['receipt']['secret_published'] is False and item['receipt']['native_output_after_input_published'] is False


def test_echoed_code_after_input_is_never_published(generated):
    item = generated['print_echo']
    assert item['code'] == 0 and CODE not in item['log'] and CODE.decode() not in item['text']
    assert item['log'].endswith(b'Or, paste the authorization code here and press Enter: ')


def test_tui_session_still_running_after_input_is_terminated_and_status_required(generated):
    item = generated['tui_terminated']; receipt = item['receipt']
    assert item['code'] == 0 and receipt['status'] == 'LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED'
    assert receipt['terminated_after_input'] is True and receipt['native_exit_code'] == 1 and receipt['native_arguments'] == []
    assert item['env'].launches[0]['argv'] == [str(bridge.NATIVE)] and item['env'].processes[0].terminated
    assert item['env'].processes[0].received == CODE + b'\r\n'
    assert b'Enter the authorization code:' in item['log'] and b'https://accounts.google.com/o/oauth2/auth' in item['log']


def test_nonzero_exit_before_input_is_login_command_failed_phase_native_wait(generated):
    item = generated['fail_before_input']; receipt = item['receipt']
    assert item['code'] == 2 and receipt['status'] == 'LOGIN_COMMAND_FAILED' and receipt['native_exit_code'] == 1
    assert receipt['login_failure'] == {'phase': 'native_wait', 'error_type': 'NativeLoginExitNonZero', 'winerror': None}
    assert receipt['native_markers']['before_input']['no_controlling_terminal_present'] and not receipt['one_line_submitted']
    assert b'no controlling terminal' in item['log']


def test_nonzero_exit_after_input_is_login_command_failed_phase_native_result(generated):
    receipt = generated['fail_after_input']['receipt']
    assert receipt['status'] == 'LOGIN_COMMAND_FAILED' and receipt['login_failure']['phase'] == 'native_result'
    assert receipt['native_markers']['after_input']['authentication_failed_present'] and not receipt['pause_marker_seen']


def test_rate_limit_after_input_sets_the_pause_flag_without_recording_text(generated):
    receipt = generated['rate_limited']['receipt']
    assert receipt['status'] == 'LOGIN_COMMAND_FAILED' and receipt['pause_marker_seen'] is True
    assert receipt['native_markers']['after_input']['rate_limit_present'] is True


def test_cancel_and_deadline_receipts(generated):
    cancelled = generated['cancelled']['receipt']
    assert generated['cancelled']['code'] == 2 and cancelled['status'] == 'LOGIN_FAILED_OR_CANCELLED'
    assert cancelled['failure'] == {'phase': 'native_wait', 'error_type': 'InterruptedError', 'winerror': None}
    assert cancelled['operator_cancelled'] and cancelled['input_file_deleted'] and 'native_exit_code' not in cancelled
    assert generated['cancelled']['env'].processes[0].received in (b'', None)
    timed_out = generated['timed_out']['receipt']
    assert timed_out['failure']['error_type'] == 'TimeoutError' and not timed_out['input_file_deleted'] and 'native_exit_code' not in timed_out
    verify = generated['verify_cancelled']['receipt']
    assert verify['pause_marker_seen'] is True and verify['native_markers']['before_input']['verification_present']


def test_callback_flow_exits_zero_without_input_and_keeps_email_out_of_the_receipt(generated):
    item = generated['callback_exit_zero']; receipt = item['receipt']
    assert item['code'] == 0 and receipt['status'] == 'LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED' and not receipt['one_line_submitted']
    assert EMAIL.encode() in item['log'] and EMAIL not in item['text']  # shown once to the owner, never recorded
    assert receipt['native_markers']['before_input']['waiting_line_present']


def test_custody_failures_and_unverified_cleanup(generated):
    custody = generated['native_custody_failure']
    assert custody['code'] == 2 and custody['env'].launches == [] and custody['receipt']['login_commands_executed'] == 0
    assert custody['receipt']['failure'] == {'phase': 'native_custody', 'error_type': 'ValueError', 'winerror': None}
    assert custody['receipt']['native_markers'] is None and not custody['receipt']['cleanup_verified']
    assert custody['receipt']['input_closed_marker_written'] is False and not (custody['root'] / 'input.closed').exists()
    changed = generated['agy_changed_after']['receipt']
    assert changed['status'] == 'LOGIN_FAILED_OR_CANCELLED' and changed['failure']['phase'] == 'native_result'
    assert changed['native_executable_sha256_after'] == '1' * 64
    unverified = generated['cleanup_unverified']
    assert unverified['code'] == 2 and unverified['receipt']['status'] == 'CLEANUP_UNVERIFIED'
    assert unverified['receipt']['failure']['phase'] == 'native_cleanup' and (unverified['root'] / 'input.once').exists()


def test_receipt_is_created_new_and_never_replaced(tmp_path):
    root = session_root(tmp_path)
    (root / 'receipt.json').write_text('{}')
    env = FakeEnvironment('print_ok')
    with patched(SESSION_PARENT=tmp_path, __file__=str(root / bridge.HELPER_NAME),
                 runtime_modules=lambda: (env.win, SimpleNamespace(from_dict=lambda value: None), lambda path, **kw: None),
                 load_support=lambda path: env.support):
        with pytest.raises(FileExistsError):
            bridge.run(SLOT, NONCE, 'print')
    assert (root / 'receipt.json').read_text() == '{}' and env.launches == []


def test_bridge_refuses_a_helper_outside_its_fresh_session_root(tmp_path):
    root = session_root(tmp_path)
    env = FakeEnvironment('print_ok')
    with patched(SESSION_PARENT=tmp_path, __file__=str(tmp_path / bridge.HELPER_NAME),
                 runtime_modules=lambda: (env.win, None, lambda path, **kw: None), load_support=lambda path: env.support):
        with pytest.raises(ValueError, match='fresh protected session'):
            bridge.run(SLOT, NONCE, 'print')
    assert not (root / 'receipt.json').exists()


# ----- pins and source hygiene -----

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_bridge_support_pin_matches_disk_and_wrapper_and_history_pin_the_bridge():
    assert bridge.SUPPORT_SHA256 == digest(SUPPORT_PATH) == '45681477194d97b144e8ee4505d4364d73d58aaef19c8428c846df642c834839'
    wrapper, history = WRAPPER.read_text(), HISTORY.read_text()
    assert f"$script:bridgeHash='{digest(BRIDGE_PATH)}'" in wrapper
    assert f"bridge='{digest(BRIDGE_PATH)}'" in history
    assert f"$script:historyHash='{digest(HISTORY)}'" in wrapper
    assert f"$script:supportHash='{bridge.SUPPORT_SHA256}'" in wrapper and f"support='{bridge.SUPPORT_SHA256}'" in history
    assert support_reference.CONTRACTS['gemini'] == {'sha256': bridge.AGY_SHA256, 'version_at_pin': '1.3.1',
                                                     'arguments': ['--output-format', 'json', 'models']}


def test_sources_are_ascii_and_bridge_never_uses_the_supervisor_login_path():
    for path in (BRIDGE_PATH, WRAPPER, HISTORY):
        path.read_bytes().decode('ascii')
    text = BRIDGE_PATH.read_text()
    code_only = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))
    assert 'login_worker(' not in code_only and 'gemini_login_argv' not in code_only and 'login_gemini_worker(' not in code_only
    assert 'launch_worker(identity, argv, spec[\'root\'], stdin, output, output, limits=limits)' in text
    assert 'CredentialBlob' not in text and 'CredRead' not in text
