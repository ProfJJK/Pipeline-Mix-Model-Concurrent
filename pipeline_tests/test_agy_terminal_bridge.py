"""Pure queue/channel transport fixtures; no Win32 console/provider is run."""
import importlib.util
import io
from pathlib import Path
import queue
from types import SimpleNamespace as NS

import pytest

from cochem_pipeline import attended_agy_terminal as terminal

PATH = Path(__file__).parents[1] / 'scripts/worker_agy_terminal_bridge.py'
PARENT = Path(__file__).parents[1] / 'docs/deployment/windows-deployment-next/worker_agy_login_bridge_r4_v1.py'


@pytest.fixture
def bridge():
    spec = importlib.util.spec_from_file_location('terminal_bridge_fixture', PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def legacy():
    spec = importlib.util.spec_from_file_location('legacy_bridge_fixture', PARENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_terminal_namespace_cannot_use_old_root_or_unknown_slot(bridge):
    nonce = '1'*32
    assert bridge.session_root('slot1', nonce).name == 'InteractiveAgyTerminal427-r4-slot1-' + nonce
    for slot, value in [('slot7', nonce), ('slot1', '0'*32), ('slot1', 'bad')]:
        with pytest.raises(ValueError):
            bridge.session_root(slot, value)


def test_output_freezes_ready_prompt_and_never_publishes_secret_echo(bridge, legacy):
    report = {'native_output_bytes_before_input': 0}
    log = io.BytesIO()
    output = bridge.TerminalOutput(legacy, log, report)
    output.accept(b'Fresh URL https://accounts.google.com/oauth?state=public\nPaste the authorization code below:\n', False)
    first = log.getvalue()
    assert output.prompt_ready
    for _ in range(100):
        output.accept(b'Please paste the authorization code below: redraw\n', False)
    assert log.getvalue() == first
    output.accept(b'PRIVATE-CODE\nSuccessfully exchanged authorization code\n', True)
    output.finish()
    assert b'PRIVATE-CODE' not in log.getvalue()
    assert report['native_markers']['after_input']['token_exchanged_present']
    assert report['native_markers']['before_input']['google_accounts_url_present']


def test_terminal_code_requires_this_sessions_url_and_prompt(bridge, legacy, monkeypatch, tmp_path):
    class FakeChannel:
        def __init__(self, path, win):
            self.raw = b'cochem-login-input/1\n' + b'1'*32 + b'\nPRIVATE-CODE\n'
    monkeypatch.setattr(legacy, 'ChannelFile', FakeChannel)
    (tmp_path/'input.once').write_bytes(b'irrelevant-fixture')
    report = {'one_line_submitted': False}
    writer = io.BytesIO()
    output = bridge.TerminalOutput(legacy, io.BytesIO(), report)
    with pytest.raises(ValueError, match='fresh native'):
        bridge.consume_input(legacy, terminal, output, writer, tmp_path, '1'*32, None, report, [])
    assert writer.getvalue() == b''
    assert not report['one_line_submitted']


def test_terminal_sets_secret_boundary_before_a_partial_write_failure(bridge, legacy, monkeypatch, tmp_path):
    class FakeChannel:
        def __init__(self, path, win):
            self.raw = b'cochem-login-input/1\n' + b'1'*32 + b'\nPRIVATE-CODE\n'
    monkeypatch.setattr(legacy, 'ChannelFile', FakeChannel)
    (tmp_path/'input.once').write_bytes(b'irrelevant-fixture')
    report = {'one_line_submitted': False}
    output = bridge.TerminalOutput(legacy, io.BytesIO(), report)
    output.accept(b'https://accounts.google.com/oauth\nPaste the authorization code below:\n', False)
    def fail(writer, value):
        assert report['one_line_submitted'] is True
        assert value == b'PRIVATE-CODE'
        raise OSError('synthetic short write')
    monkeypatch.setattr(terminal, 'submit_authorization_code', fail)
    with pytest.raises(OSError):
        bridge.consume_input(legacy, terminal, output, io.BytesIO(), tmp_path, '1'*32, None, report, [])
    assert report['one_line_submitted']


def test_prompt_without_this_sessions_google_url_never_unlocks_code(bridge, legacy):
    output = bridge.TerminalOutput(legacy, io.BytesIO(), {})
    output.accept(b'Enter the authorization code:\n', False)
    assert not output.prompt_ready


def test_a_prompt_before_the_google_url_cannot_unlock_code(bridge, legacy):
    output = bridge.TerminalOutput(legacy, io.BytesIO(), {})
    output.accept(b'Enter the authorization code:\nhttps://accounts.google.com/oauth\n', False)
    assert not output.prompt_ready
    output.accept(b'Paste the authorization code:\n', False)
    assert output.prompt_ready


@pytest.mark.parametrize('chunk_size', [1, 7, 4096])
def test_installed_131_prompt_with_footer_creates_one_ready_event(bridge, legacy, chunk_size):
    # Exact wording/row layout from the owner's failure, synthetic URL only.
    screen = (b'Open the URL below in your browser:\n' + b'-'*1024 +
        b'\nhttps://accounts.google.com/o/oauth2/auth?fixture=fresh\n' + b'-'*1024 +
        b'\nAfter authenticating, copy the code displayed in the browser and paste it below:\n'
        b'\nauthorization code...\n\nshift+up/down Navigate')
    ready = []
    output = bridge.TerminalOutput(legacy, io.BytesIO(), {}, on_prompt=ready.append)
    for at in range(0, len(screen), chunk_size):
        output.accept(screen[at:at+chunk_size], False)
    output.accept(screen, False)  # Native redraw is not a second prompt.
    assert output.prompt_ready
    assert ready == ['https://accounts.google.com/o/oauth2/auth?fixture=fresh']
    output.finish()
    assert output.report['native_markers']['before_input']['paste_prompt_present']


@pytest.mark.parametrize('screen', [
    'authorization code...\nhttps://accounts.google.com/oauth',
    'https://accounts.google.com/oauth\nshift+up/down Navigate',
    'https://accounts.google.com.evil/oauth\nPaste the authorization code:',
    'https://accounts.google.com/oauth\nAfter authenticating, copy the code displayed in the browser and paste it below:',
])
def test_footer_or_partial_or_foreign_prompt_does_not_open_input(bridge, screen):
    assert bridge.google_code_prompt(screen) is None


def test_cursor_addressed_native_menu_has_separate_rows_and_one_public_return(bridge, legacy):
    output = bridge.TerminalOutput(legacy, io.BytesIO(), {})
    display = output.accept(b'\x1b[1;1HSelect login method:\x1b[2;1H> 1. Google OAuth\x1b[3;1H  2. API key', False)
    consent = terminal.NativeGoogleConsent()
    assert consent.before_input(display) == b'\r'
    assert consent.before_input(display) == b''
    assert '\x1b' not in output.output.log.getvalue().decode()


def test_terminal_projection_preserves_a_split_cursor_sequence_and_utf8(legacy):
    publisher = terminal.TerminalPublisher(legacy)
    assert publisher.feed(b'\x1b[2;') == ''
    assert publisher.feed(b'1HGoogle \xe2\x9d') == '\nGoogle '
    assert publisher.feed(b'\xaf') == '❯'
    assert publisher.feed(b'\x1b[2;10H OAuth') == ' OAuth'


def test_suppressed_redraw_still_detects_provider_pause(bridge, legacy):
    output = bridge.TerminalOutput(legacy, io.BytesIO(), {})
    output.accept(b'https://accounts.google.com/oauth\nPaste the authorization code below:\n', False)
    output.accept(b'Error: rate limit exceeded\n', False)
    output.finish()
    assert output.report['pause_marker_seen']


def test_no_output_holds_after_thirty_seconds_and_closes_input(bridge, legacy, monkeypatch, tmp_path):
    times = iter([0., 31.])
    monkeypatch.setattr(bridge.time, 'monotonic', lambda: next(times))
    report = dict(one_line_submitted=False, native_output_bytes_before_input=0)
    output = bridge.TerminalOutput(legacy, io.BytesIO(), report)
    with pytest.raises(TimeoutError):
        bridge.read_loop(legacy, terminal, NS(), queue.Queue(), output, tmp_path, '1'*32, None, report, [])
    assert report['terminal_hold_reason'] == 'NO_NATIVE_STARTUP_OUTPUT'
    assert report['input_closed_marker_written']
    assert (tmp_path/'input.closed').read_bytes().endswith(b'1'*32 + b'\n')


def test_unknown_screen_holds_without_blind_key_or_browser_input(bridge, legacy, monkeypatch, tmp_path):
    times = iter([0., 61.])
    monkeypatch.setattr(bridge.time, 'monotonic', lambda: next(times))
    report = dict(one_line_submitted=False, native_output_bytes_before_input=1)
    output = bridge.TerminalOutput(legacy, io.BytesIO(), report)
    with pytest.raises(TimeoutError):
        bridge.read_loop(legacy, terminal, NS(), queue.Queue(), output, tmp_path, '1'*32, None, report, [])
    assert report['terminal_hold_reason'] == 'FRESH_GOOGLE_PROMPT_NOT_OBSERVED'
    assert report['input_closed_marker_written']


def test_short_private_packet_creation_race_waits_without_consuming_or_exposing_code(bridge, legacy, monkeypatch, tmp_path):
    def unavailable(*_):
        error = OSError('synthetic exclusive writer')
        error.winerror = 32
        raise error
    monkeypatch.setattr(legacy, 'ChannelFile', unavailable)
    (tmp_path/'input.once').write_bytes(b'fixture')
    report = dict(one_line_submitted=False)
    output = bridge.TerminalOutput(legacy, io.BytesIO(), report)
    output.accept(b'https://accounts.google.com/oauth\nPaste the authorization code below:\n', False)
    writer = io.BytesIO()
    assert bridge.consume_input(legacy, terminal, output, writer, tmp_path, '1'*32, None, report, []) is False
    assert not report['one_line_submitted']
    assert writer.getvalue() == b''


def test_terminal_module_pin_matches_exact_staged_source(bridge):
    import hashlib
    source = Path(__file__).parents[1]/'src/cochem_pipeline/attended_agy_terminal.py'
    assert bridge.TERMINAL_PIN == hashlib.sha256(source.read_bytes()).hexdigest()


@pytest.mark.parametrize('success,stored,elapsed,ended',[(False,True,10,False),(True,False,10,False),(True,True,2,False),(True,True,5,True)])
def test_idle_tui_ends_only_after_native_success_and_token_metadata_not_just_a_paste(bridge,legacy,monkeypatch,success,stored,elapsed,ended):
    events=[]
    monkeypatch.setattr(legacy,'observe_token_storage',lambda *_:dict(token_contents_read=False,file_token_present=stored,credential_manager_entry_present=False))
    session=NS(poll=lambda:None,terminate=lambda:events.append('owned-job-end'),wait=lambda **kw:0)
    report={}
    result=bridge.end_completed_native_session(legacy,session,NS(native_auth_success=success),None,report,elapsed)
    assert (result==0) is ended
    assert events==(['owned-job-end'] if ended else [])
    assert report.get('terminated_after_input',False) is ended


def test_after_code_success_text_remains_private_and_later_failure_prevents_early_end(bridge,legacy):
    log=io.BytesIO();output=bridge.TerminalOutput(legacy,log,{})
    output.accept(b'PRIVATE-CODE\nAuthenticated as fixture user\n',True)
    assert output.native_auth_success and not log.getvalue()
    output.accept(b'Error: authentication failed\n',True)
    assert not output.native_auth_success and not log.getvalue()
