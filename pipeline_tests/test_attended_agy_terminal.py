"""Inert native-boundary tests: never creates a console or launches a child."""
import ctypes as C
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from cochem_pipeline import attended_agy_terminal as terminal


@pytest.fixture
def fake_launch(monkeypatch):
    from cochem_pipeline import windows as win
    events = []
    def note(name, result=True):
        def call(*_):
            events.append(name)
            return result
        return call
    kernel = NS(CreateMutexW=note('reserve', 41), CreateJobObjectW=note('job', 43),
                DeleteProcThreadAttributeList=note('delete-attributes'),
                UpdateProcThreadAttribute=note('attach-terminal'),
                AssignProcessToJobObject=note('assign'), ResumeThread=note('resume', 0))
    def initialize(buffer, count, flags, size):
        size._obj.value = 64
        return buffer is not None
    kernel.InitializeProcThreadAttributeList = initialize
    kernel.GetCurrentProcess = lambda: 11
    def duplicate(current, source, other, destination, access, inherit, options):
        assert (source, inherit, options) == (41, False, 2)
        destination._obj.value = 81
        events.append('retain-reservation')
        return True
    kernel.DuplicateHandle = duplicate
    def load(token, profile):
        events.append('profile')
        profile._obj.hProfile = 55
        return True
    def create(token, executable, command, process_acl, thread_acl, inherit, flags, environment, directory, startup, process):
        events.append('create')
        assert inherit is False
        assert flags == terminal.TERMINAL_PROCESS_FLAGS
        assert not startup._obj.StartupInfo.dwFlags
        assert executable == str(terminal.NATIVE) and command.value.strip('"') == executable
        assert 'SSH_CONNECTION=' + terminal.MANUAL_AUTH_SENTINEL in ''.join(environment)
        process._obj.hProcess = 61
        process._obj.hThread = 62
        process._obj.dwProcessId = 63
        return True
    api = dict(kernel32=kernel, userenv=NS(LoadUserProfileW=load), advapi32=NS(CreateProcessAsUserW=create))
    def cleanup(process, job, token, profile, reservation):
        events.append('failed-worker-cleanup')
        assert (job, token, profile.hProfile, reservation) == (43, 42, 55, 41)
    replacements = dict(require_system=note('system'), _enable_system_privileges=note('privileges'),
        validate_code_path=note('executable'), _account_sid=note('account', 'sid'), _sid_text=lambda sid: sid,
        _validate_worker_directory=note('directory'), _api=lambda: api, _worker_token=note('token', 42),
        _worker_environment=lambda *_a, **_k: C.create_unicode_buffer('USERPROFILE=worker\0PATH=C:\\Windows\0\0'),
        process_creation_filetime=note('creation', 134000000000000000), _close=lambda handle: events.append(('close', handle)),
        _cleanup_failed_launch=cleanup,
        WindowsProcess=lambda *args: NS(pid=args[4], args=args[5], close=note('worker-close')))
    for name, value in replacements.items():
        monkeypatch.setattr(win, name, value)
    console = NS(handle=C.c_void_p(71), release_client_ends=note('release-console-ends'),
                 close=note('console-close'), writer=NS(close=note('writer-close')))
    def factory(callback):
        events.append('console')
        callback('synthetic-reader')
        return console
    resources = NS(apply_job_limits=note('limits', {'verified': True}), launch_delay_seconds=lambda _: 0)
    return NS(win=win, api=api, console=console, factory=factory, events=events, resources=resources)


def test_suspended_terminal_child_is_job_owned_before_resume(fake_launch, tmp_path):
    fx = fake_launch
    readers = []
    session = terminal.launch_attended_agy(fx.win, fx.resources, NS(name='worker'), tmp_path,
        limits=object(), output_ready=readers.append, console_factory=fx.factory)
    assert session.pid == 63 and readers == ['synthetic-reader']
    assert fx.events.index('limits') < fx.events.index('console') < fx.events.index('create')
    assert fx.events.index('create') < fx.events.index('assign') < fx.events.index('creation') < fx.events.index('resume')
    assert fx.events.count(('close', 62)) == 1


@pytest.mark.parametrize('phase', ['assign', 'resume'])
def test_failed_native_start_retains_console_for_drained_teardown(fake_launch, tmp_path, phase):
    fx = fake_launch
    if phase == 'assign':
        fx.api['kernel32'].AssignProcessToJobObject = lambda *_: False
    else:
        fx.api['kernel32'].ResumeThread = lambda *_: 0xFFFFFFFF
    with pytest.raises(terminal.TerminalCleanupError) as caught:
        terminal.launch_attended_agy(fx.win, fx.resources, NS(name='worker'), tmp_path,
            limits=object(), output_ready=lambda _: None, console_factory=fx.factory)
    assert caught.value.worker_cleanup_verified is True
    assert caught.value.console is fx.console
    assert 'failed-worker-cleanup' in fx.events
    assert 'console-close' not in fx.events
    if phase == 'assign':
        assert 'resume' not in fx.events


def test_failed_launch_never_releases_terminal_when_worker_cleanup_is_uncertain(fake_launch, tmp_path, monkeypatch):
    fx = fake_launch
    fx.api['kernel32'].AssignProcessToJobObject = lambda *_: False
    def uncertain(*_):
        raise fx.win.WindowsCleanupError('synthetic active child')
    monkeypatch.setattr(fx.win, '_cleanup_failed_launch', uncertain)
    with pytest.raises(terminal.TerminalCleanupError) as caught:
        terminal.launch_attended_agy(fx.win, fx.resources, NS(name='worker'), tmp_path,
            limits=object(), output_ready=lambda _: None, console_factory=fx.factory)
    assert caught.value.console is fx.console
    assert not getattr(caught.value, 'worker_cleanup_verified', False)
    assert 'console-close' not in fx.events


def test_manual_transport_preserves_native_profile_and_clears_inherited_ssh():
    block = C.create_unicode_buffer('USERPROFILE=C:\\Users\\worker\0PATH=C:\\Windows\0SSH_TTY=other\0'
                                    'SSH_CLIENT=remote\0SSH_CONNECTION=remote\0\0')
    result = terminal.manual_auth_environment(block)
    entries = dict(part.split('=', 1) for part in ''.join(result).split('\0') if part)
    assert entries == {'USERPROFILE': r'C:\Users\worker', 'PATH': r'C:\Windows',
                       'SSH_CONNECTION': terminal.MANUAL_AUTH_SENTINEL}


@pytest.mark.parametrize('raw', ['BROKEN\0\0', 'PATH=a\0PATH=b\0\0', 'PATH=a', 'PATH=' + 'a'*1048577 + '\0\0'],
                         ids=['invalid-entry', 'duplicate-name', 'missing-terminator', 'oversize'])
def test_environment_rejects_unbounded_or_ambiguous_native_blocks(raw):
    with pytest.raises(ValueError):
        terminal.manual_auth_environment(C.create_unicode_buffer(raw))


def test_console_uses_real_terminal_attribute_and_no_standard_handle_inheritance():
    calls = []
    kernel = NS()
    def initialize(buffer, count, flags, size):
        size._obj.value = 64
        calls.append(('initialize', count))
        return buffer is not None
    kernel.InitializeProcThreadAttributeList = initialize
    kernel.DeleteProcThreadAttributeList = lambda _: calls.append(('delete',))
    kernel.UpdateProcThreadAttribute = lambda buf, flags, key, value, size, old, needed: (
        calls.append(('attribute', key, value, size)) or True)
    console = NS(handle=C.c_void_p(222))
    from cochem_pipeline import windows as win
    with terminal.terminal_startup(win, kernel, console) as startup:
        assert startup.StartupInfo.dwFlags == 0
        assert not startup.StartupInfo.hStdInput
        assert not startup.StartupInfo.hStdOutput
        assert not startup.StartupInfo.hStdError
        assert startup.lpAttributeList
    assert calls[2] == ('attribute', 0x20016, console.handle, C.sizeof(C.c_void_p))
    assert calls[-1] == ('delete',)
    assert not terminal.TERMINAL_PROCESS_FLAGS & (0x08000000 | 0x10 | 0x8)
    assert terminal.TERMINAL_PROCESS_FLAGS & (0x4 | 0x400 | 0x80000) == (0x4 | 0x400 | 0x80000)


def test_startup_releases_attribute_list_after_failed_update():
    calls = []
    def initialize(buf, count, flags, size):
        size._obj.value = 32
        return bool(buf)
    kernel = NS(InitializeProcThreadAttributeList=initialize,
                UpdateProcThreadAttribute=lambda *_: False,
                DeleteProcThreadAttributeList=lambda _: calls.append('deleted'))
    win = NS(SIZE_T=C.c_size_t, _check=lambda ok, _: ok or (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(RuntimeError):
        with terminal.terminal_startup(win, kernel, NS(handle=C.c_void_p(2))):
            pass
    assert calls == ['deleted']


def test_launch_requires_system_and_exact_auth_executable_before_native_creation(tmp_path):
    calls = []
    win = NS(require_system=lambda: calls.append('system'),
             _enable_system_privileges=lambda: calls.append('privileges'))
    with pytest.raises(ValueError):
        terminal.launch_attended_agy(win, NS(), NS(), tmp_path, limits=None)
    assert calls == ['system']


def test_closing_console_keeps_draining_and_retains_handle_on_failure(monkeypatch):
    calls = []
    console = terminal.PseudoConsole.__new__(terminal.PseudoConsole)
    console.handle = C.c_void_p(23)
    console._closing = None
    console._close_error = None
    console._kernel = NS(ClosePseudoConsole=lambda handle: calls.append(handle.value))
    console.release_client_ends = lambda: calls.append('client_ends')
    console.close(lambda: calls.append('drain'))
    assert console.handle is None
    assert 23 in calls
    # The same session is idempotent; it cannot close someone else's console.
    console.close(lambda: None)
    assert calls.count(23) == 1


def test_console_close_failure_is_not_terminal_proof():
    console = terminal.PseudoConsole.__new__(terminal.PseudoConsole)
    console.handle = C.c_void_p(23)
    console._closing = None
    console._close_error = None
    def fail(_):
        raise OSError('synthetic error')
    console._kernel = NS(ClosePseudoConsole=fail)
    console.release_client_ends = lambda: None
    with pytest.raises(terminal.TerminalCleanupError):
        console.close(lambda: None)
    assert console.handle.value == 23


def test_session_closes_worker_tree_before_terminal_and_marks_cleanup_after_both():
    calls = []
    worker = NS(close=lambda: calls.append('worker'), pid=12, args=['agy'],
                _token=44, poll=lambda: 0)
    console = NS(close=lambda drain: calls.append('terminal'), writer=NS(close=lambda: calls.append('writer')))
    session = terminal.AttendedSession(worker, console)
    session.close(lambda: calls.append('drain'))
    assert calls == ['worker', 'terminal', 'writer']
    assert session.cleanup_verified


def test_session_retains_terminal_and_identity_on_unverified_worker_cleanup():
    calls = []
    def fail():
        calls.append('worker')
        raise RuntimeError('cleanup uncertain')
    session = terminal.AttendedSession(NS(close=fail), NS(close=lambda _: calls.append('terminal')))
    with pytest.raises(RuntimeError):
        session.close(lambda: None)
    assert calls == ['worker']
    assert not session.cleanup_verified


def test_duplicate_identity_reservation_is_released_only_after_terminal_cleanup():
    calls = []
    session = terminal.AttendedSession(NS(close=lambda: calls.append('worker')),
        NS(close=lambda _: calls.append('terminal'), writer=NS(close=lambda: calls.append('writer'))),
        reservation_release=lambda: calls.append('reservation'))
    session.close(lambda: None)
    assert calls == ['worker', 'terminal', 'writer', 'reservation']
    session.close(lambda: None)
    assert calls.count('reservation') == 1


def test_failed_terminal_cleanup_retains_identity_reservation():
    calls = []
    def fail(_):
        raise terminal.TerminalCleanupError('synthetic failure')
    session = terminal.AttendedSession(NS(close=lambda: calls.append('worker')),
        NS(close=fail), reservation_release=lambda: calls.append('reservation'))
    with pytest.raises(terminal.TerminalCleanupError):
        session.close(lambda: None)
    assert calls == ['worker']
    assert not session.cleanup_verified


def test_terminal_queries_get_fixed_replies_across_split_frames():
    replies = terminal.TerminalReplies()
    assert replies.feed(b'\x1b[') == []
    assert replies.feed(b'6n') == [b'\x1b[1;1R']
    assert replies.feed(b'\x1b[c\x1b[>c\x1b[?u') == [b'\x1b[?1;2c', b'\x1b[>0;0;0c', b'\x1b[?0u']
    assert replies.feed(b'\x1b]11;?\x1b\\') == [b'\x1b]11;rgb:0000/0000/0000\x1b\\']


def test_terminal_replies_never_reflect_native_or_operator_text():
    replies = terminal.TerminalReplies()
    assert replies.feed(b'https://provider/?code=SECRET') == []
    assert replies.feed(b'\x1b]52;c;SECRET\x07\x1b[5n') == []
    assert replies.feed(b'x' * 100000) == []
    assert len(replies._tail) <= 32


def test_terminal_response_storm_is_bounded_without_logging_payload():
    replies = terminal.TerminalReplies()
    with pytest.raises(ValueError, match='bound'):
        for _ in range(130):
            replies.feed(b'\x1b[6n')


def test_terminal_code_submits_one_return_and_keeps_transport_open():
    import io
    writer = io.BytesIO()
    terminal.submit_authorization_code(writer, b'one-code')
    assert writer.getvalue() == b'one-code\r'
    assert not writer.closed


@pytest.mark.parametrize('value', [b'', b'a\nb', b'a\rb', b'a\0b', b'x'*2049, 'text'])
def test_terminal_code_rejects_delimiters_or_oversize_without_echo(value):
    import io
    writer = io.BytesIO()
    with pytest.raises(ValueError) as caught:
        terminal.submit_authorization_code(writer, value)
    assert writer.getvalue() == b''
    assert not isinstance(value, str) or value not in str(caught.value)


def test_google_start_is_one_fixed_return_only_for_the_selected_native_google_menu():
    consent = terminal.NativeGoogleConsent()
    assert consent.before_input('Select login method:\n> 1. Google OAuth\n  2. Other sign-in options') == b'\r'
    assert consent.before_input('Select login method:\n> 1. Google OAuth') == b''
    assert consent.google_start_sent


@pytest.mark.parametrize('display', ['> 1. Google OAuth', 'Select login method:\n> 1. API key',
    'Select login method:\n  1. Google OAuth\n> 2. Other sign-in options',
    'Select login method:\n> 1. Google Cloud ADC', 'https://accounts.google.com/o/oauth2/auth\n> 1. Google OAuth'])
def test_google_start_never_selects_an_unknown_billing_path_or_a_model_prompt(display):
    consent = terminal.NativeGoogleConsent()
    assert consent.before_input(display) == b''
    assert not consent.google_start_sent
