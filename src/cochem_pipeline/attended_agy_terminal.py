"""Owned ConPTY transport for one attended Agy OAuth session, never inference.

This module is inert on import. The bridge must pin it in a fresh protected
session and validate its installed Windows support before calling launch.
It reuses that support's token, private-directory, identity reservation, Job
limits, suspended launch, creation-time evidence and verified cleanup.
It never opens or copies a token, calls an OAuth endpoint or permits arbitrary
environment overrides. Native Agy remains responsible for sign-in/storage.

Protocol sources:
https://learn.microsoft.com/en-us/windows/console/creating-a-pseudoconsole-session
https://www.antigravity.google/docs/cli/install/
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import subprocess
import re
import threading
import time
import codecs


NATIVE = Path(r'C:\Program Files\CoChem\Native4.2.7-windows-20261006\agy.exe')
# An explicit, fixed transport hint to select the native CLI's manual remote
# consent path. No SSH connection is opened; this is not an authentication
# identity or an inherited operator value. The compiled pinned CLI checks the
# presence of SSH_CLIENT/SSH_TTY/SSH_CONNECTION before opening a local browser.
MANUAL_AUTH_SENTINEL = '127.0.0.1 0 127.0.0.1 0'
ENV_LIMIT = 1024 * 1024
TERMINAL_PROCESS_FLAGS = 0x4 | 0x400 | 0x80000 | 0x200 | 0x4000
CLOSE_SECONDS = 10.0


class TerminalCleanupError(RuntimeError):
    """Console ownership is not released; preserve/quarantine this session."""


class TerminalReplies:
    """Fixed terminal capability replies, never reflect output or code bytes.

    A TUI can query its terminal before rendering. A pipe relay is not a
    terminal emulator. ConPTY transports these queries to the host, which must
    service them. Unsupported clipboard/other OSC commands get no response.
    Retained partial input is only a prefix of one fixed query, never arbitrary
    native text. The response count bounds a malfunctioning query loop.
    """
    _replies = {
        b'\x1b[6n': b'\x1b[1;1R',
        b'\x1b[c': b'\x1b[?1;2c',
        b'\x1b[0c': b'\x1b[?1;2c',
        b'\x1b[>c': b'\x1b[>0;0;0c',
        b'\x1b[>0c': b'\x1b[>0;0;0c',
        b'\x1b[?u': b'\x1b[?0u',
        b'\x1b]10;?\x1b\\': b'\x1b]10;rgb:ffff/ffff/ffff\x1b\\',
        b'\x1b]11;?\x1b\\': b'\x1b]11;rgb:0000/0000/0000\x1b\\',
        b'\x1b]10;?\x07': b'\x1b]10;rgb:ffff/ffff/ffff\x07',
        b'\x1b]11;?\x07': b'\x1b]11;rgb:0000/0000/0000\x07',
    }
    _pattern = re.compile(b'|'.join(re.escape(key) for key in sorted(_replies, key=len, reverse=True)))

    def __init__(self):
        self._tail = b''
        self.count = 0

    def feed(self, data):
        raw = self._tail + data
        result = [self._replies[match.group()] for match in self._pattern.finditer(raw)]
        self.count += len(result)
        if self.count > 128:
            raise ValueError('Native terminal query response bound exceeded')
        partial = [key[:length] for key in self._replies for length in range(1, len(key))
                   if raw.endswith(key[:length])]
        self._tail = max(partial, key=len) if partial else b''
        return result


class TerminalPublisher:
    """Display-only projection of cursor-addressed rows, never execute VT.

    The retained publisher strips controls. Preserve explicit row changes as
    line boundaries before that stripping, so menu rows/prompt text cannot be
    accidentally concatenated. No screen contents survive the input boundary.
    """
    _vertical = re.compile(r'\x1b\[([0-9;]*)([ABEFHfd])')

    def __init__(self, legacy):
        self.legacy = legacy
        self.decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self.pending = ''
        self.row = None

    def feed(self, data, final=False):
        text = self.pending + self.decoder.decode(data, final)
        self.pending = ''
        if not final:
            cut = self.legacy._incomplete_escape_start(text)
            if cut >= 0:
                text, self.pending = text[:cut], text[cut:]
        def row_change(match):
            parameters, command = match.groups()
            if command in 'Hfd':
                row = int(parameters.split(';')[0] or '1')
                changed = self.row != row
                self.row = row
                return '\n' if changed else ''
            self.row = None
            return '\n'
        return self.legacy.sanitize_text(self._vertical.sub(row_change, text))


class NativeGoogleConsent:
    """One public Return to the native selected Google OAuth login menu.

    Both menu text and the selected label must be observed from pinned Agy.
    These strings exist in its compiled AuthModel. No key is sent for an API
    key, ADC/Cloud, an unselected option, or an unknown screen. Once a consent
    URL exists this helper cannot send navigation or a model prompt.
    """
    def __init__(self):
        self.google_start_sent = False
        self._window = ''

    def before_input(self, display):
        if self.google_start_sent:
            return b''
        self._window = (self._window + display)[-16384:]
        if 'https://accounts.google.com/' in self._window:
            return b''
        if ('Select login method:' in self._window
                and re.search(r'(?:^|\n)\s*[>❯›]\s*[1-9]\.\s*Google OAuth\s*(?:\n|$)', self._window)):
            self.google_start_sent = True
            self._window = ''
            return b'\r'
        return b''


def submit_authorization_code(writer, value):
    """One bounded secret, one terminal Return; no EOF until token persistence.

    A CRLF would deliver TWO keys to a TUI. Closing its input pipe immediately
    can end the terminal before the native code exchange/storage completes.
    The bridge disables all output publication BEFORE calling this function.
    """
    if (not isinstance(value, bytes) or not 1 <= len(value) <= 2048
            or any(char < 32 or char == 127 for char in value)):
        raise ValueError('Authorization input must be one bounded plain line')
    value.decode('utf-8', 'strict')
    line = value + b'\r'
    if writer.write(line) != len(line):
        raise OSError('Native terminal accepted incomplete authorization input')
    writer.flush()


def manual_auth_environment(native_block):
    """Preserve the already-sanitized native worker block; set one fixed hint.

    This deliberately does not extend launch_worker's metadata override API.
    Ordinary jobs cannot use it to override profile/PATH/authentication keys.
    """
    if not isinstance(native_block, C.Array) or len(native_block) > ENV_LIMIT:
        raise ValueError('The native worker environment is not bounded')
    raw = ''.join(native_block)
    if not raw.endswith('\0\0') or '\0\0' in raw.rstrip('\0'):
        raise ValueError('The native environment is not a double-NUL block')
    entries = {}
    for item in raw.rstrip('\0').split('\0'):
        if '=' not in item or item.startswith('='):
            raise ValueError('The native environment contains an invalid entry')
        key, value = item.split('=', 1)
        key = key.upper()
        if not key or key in entries:
            raise ValueError('The native environment contains ambiguous names')
        entries[key] = value
    for key in ('SSH_CLIENT', 'SSH_TTY', 'SSH_CONNECTION'):
        entries.pop(key, None)
    entries['SSH_CONNECTION'] = MANUAL_AUTH_SENTINEL
    return C.create_unicode_buffer('\0'.join(f'{key}={value}' for key, value in sorted(entries.items())) + '\0\0')


class _COORD(C.Structure):
    _fields_ = [('X', W.SHORT), ('Y', W.SHORT)]


def _console_api():
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.CreatePseudoConsole.argtypes = [_COORD, W.HANDLE, W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
    kernel.CreatePseudoConsole.restype = C.c_long  # HRESULT; not a BOOL/last-error return.
    kernel.ClosePseudoConsole.argtypes = [W.HANDLE]
    kernel.ClosePseudoConsole.restype = None
    return kernel


class PseudoConsole:
    """One small terminal; pipes non-inheritable, separately serviced by bridge.

    The bridge starts its output pump in output_ready BEFORE console creation.
    The child inherits no raw stdin/output handles. The HPCON startup attribute
    grants the terminal attachment. Caller must keep draining until close ends.
    """

    def __init__(self, output_ready):
        self.handle = None
        self._closing = None
        self._close_error = None
        self._client = []
        self.writer = self.reader = None
        self._kernel = _console_api()
        descriptors = self._client
        try:
            input_read, input_write = os.pipe()
            descriptors.extend((input_read, input_write))
            output_read, output_write = os.pipe()
            descriptors.extend((output_read, output_write))
            self.writer = os.fdopen(input_write, 'wb', buffering=0)
            descriptors.remove(input_write)
            self.reader = os.fdopen(output_read, 'rb', buffering=0)
            descriptors.remove(output_read)
            self._client = descriptors
            output_ready(self.reader)
            import msvcrt
            handle = W.HANDLE()
            status = self._kernel.CreatePseudoConsole(
                _COORD(1024, 40), msvcrt.get_osfhandle(input_read), msvcrt.get_osfhandle(output_write),
                0, C.byref(handle))  # Never inherit cursor: no teardown cursor-query dependency.
            if status < 0:
                raise OSError('Native terminal creation failed (HRESULT)')
            self.handle = handle
        except BaseException:
            self.release_client_ends()
            if self.writer is not None:
                self.writer.close()
            # The reader belongs to the output pump once output_ready succeeds.
            if self.reader is not None and self.handle is None:
                self.reader.close()
            raise

    def release_client_ends(self):
        for descriptor in self._client:
            os.close(descriptor)
        self._client.clear()

    def close(self, drain):
        """Keep draining while ClosePseudoConsole can emit its final frame.

        Closing is bounded without pretending that a timeout proved cleanup.
        On timeout/error retain the HPCON/session, and do not allow a retry.
        """
        if self.handle is None:
            return
        self.release_client_ends()
        if self._closing is None:
            def close_native():
                try:
                    self._kernel.ClosePseudoConsole(self.handle)
                except BaseException as error:
                    self._close_error = error
            self._closing = threading.Thread(target=close_native, name='attended-console-close', daemon=True)
            self._closing.start()
        deadline = time.monotonic() + CLOSE_SECONDS
        while self._closing.is_alive() and time.monotonic() < deadline:
            drain()
            self._closing.join(timeout=.02)
        if self._closing.is_alive() or self._close_error is not None:
            raise TerminalCleanupError('Native terminal cleanup is unverified; preserve the session')
        self.handle = None


@contextmanager
def terminal_startup(win, kernel, console):
    """No handle allowlist/stdhandle redirection: attach only the owned HPCON."""
    size = win.SIZE_T()
    kernel.InitializeProcThreadAttributeList(None, 1, 0, C.byref(size))
    if not 0 < size.value <= 65536:
        raise ValueError('Native terminal startup allocation is unbounded')
    attributes = C.create_string_buffer(size.value)
    win._check(kernel.InitializeProcThreadAttributeList(attributes, 1, 0, C.byref(size)),
               'Initialize terminal startup attributes')
    try:
        # Microsoft's API takes the HPCON value here, not byref(HPCON).
        win._check(kernel.UpdateProcThreadAttribute(attributes, 0, 0x20016, console.handle,
                                                    C.sizeof(W.HANDLE), None, None), 'Attach owned terminal')
        startup = win._STARTUPINFOEXW()
        startup.StartupInfo.cb = C.sizeof(startup)
        startup.lpAttributeList = C.addressof(attributes)
        yield startup
    finally:
        kernel.DeleteProcThreadAttributeList(attributes)


class AttendedSession:
    """Separate proof of worker tree/profile cleanup and terminal teardown."""

    def __init__(self, worker, console, *, reservation_release=None):
        self.worker, self.console = worker, console
        self._reservation_release = reservation_release
        self.cleanup_verified = False

    def __getattr__(self, name):
        return getattr(self.worker, name)

    def close(self, drain):
        if self.cleanup_verified:
            return
        self.worker.close()  # Includes empty-Job proof before unloading profile/reservation.
        self.console.close(drain)
        self.console.writer.close()
        if self._reservation_release is not None:
            self._reservation_release()
            self._reservation_release = None
        self.cleanup_verified = True


def launch_attended_agy(win, resources, identity, cwd, *, limits, output_ready=None, console_factory=PseudoConsole):
    """SYSTEM-only, exact no-argument Agy sign-in under one reserved worker.

    The caller validates pinned native/helper bytes before entry and after exit.
    There is no arbitrary argv, shell, model prompt, code or environment input.
    output_ready owns the reader and must drain it throughout terminal teardown.
    """
    win.require_system()
    if limits is None or not callable(output_ready):
        raise ValueError('Attended terminal requires reviewed limits and an output pump')
    win._enable_system_privileges()
    win.validate_code_path(NATIVE)
    directory = Path(cwd).resolve(strict=True)
    sid = win._sid_text(win._account_sid(identity.name))
    win._validate_worker_directory(directory, sid)
    api = win._api()
    C.set_last_error(0)
    slot_lock = api['kernel32'].CreateMutexW(None, False, 'Global\\CoChemPipeline422-' + sid)
    win._check(slot_lock, 'Reserve exclusive attended identity')
    if C.get_last_error() == 183:
        win._close(slot_lock)
        raise win.WindowsIsolationError('This identity already has a supervised process')
    try:
        token = win._worker_token(identity)
    except BaseException:
        win._close(slot_lock)
        raise
    profile = win._PROFILEINFOW(dwSize=C.sizeof(win._PROFILEINFOW), dwFlags=1, lpUserName=identity.name)
    job, process, console = None, win._PROCESS_INFORMATION(), None
    reservation = W.HANDLE()
    native_started = False
    try:
        # Retain the same named reservation object through terminal teardown.
        # WindowsProcess.close legitimately releases its original handle after
        # worker/profile cleanup; this non-inheritable duplicate prevents an
        # identity reuse gap if ClosePseudoConsole later fails or times out.
        current = api['kernel32'].GetCurrentProcess()
        win._check(api['kernel32'].DuplicateHandle(current, slot_lock, current, C.byref(reservation),
                                                   0, False, 2), 'Retain attended identity through terminal close')
        win._check(api['userenv'].LoadUserProfileW(token, C.byref(profile)), 'Load attended worker profile')
        environment = manual_auth_environment(win._worker_environment(token, None, limits=limits))
        job = win._check(api['kernel32'].CreateJobObjectW(None, None), 'Create attended worker Job')
        evidence = resources.apply_job_limits(job, limits)
        time.sleep(resources.launch_delay_seconds(limits))
        console = console_factory(output_ready)
        with win._SPAWN_LOCK, terminal_startup(win, api['kernel32'], console) as startup:
            command = C.create_unicode_buffer(subprocess.list2cmdline([str(NATIVE)]))
            win._check(api['advapi32'].CreateProcessAsUserW(
                token, str(NATIVE), command, None, None, False, TERMINAL_PROCESS_FLAGS,
                environment, str(directory), C.byref(startup), C.byref(process)), 'Create suspended attended worker')
            win._check(api['kernel32'].AssignProcessToJobObject(job, process.hProcess), 'Own attended worker before resume')
            created = win.process_creation_filetime(process.hProcess)
            if api['kernel32'].ResumeThread(process.hThread) == 0xFFFFFFFF:
                raise win.WindowsIsolationError('Could not resume attended worker')
            native_started = True
        console.release_client_ends()
        win._close(process.hThread)
        process.hThread = None
        return AttendedSession(win.WindowsProcess(process.hProcess, job, token, profile.hProfile,
                                                  process.dwProcessId, [str(NATIVE)], slot_lock,
                                                  evidence, created), console,
                               reservation_release=lambda: win._close(reservation))
    except BaseException as launch_error:
        # Empty-job/profile proof must succeed before releasing terminal or
        # allowing this identity to be reused. Caller drains/closes the console
        # through the retained failure evidence if native teardown cannot prove exit.
        try:
            win._cleanup_failed_launch(process, job, token, profile, slot_lock)
        except BaseException as cleanup_error:
            failure = TerminalCleanupError('Attended launch cleanup is unverified; quarantine this session')
            failure.console = console
            failure.reservation = reservation
            failure.native_command_started = native_started
            raise failure from cleanup_error
        if console is not None:
            failure = TerminalCleanupError('Failed launch requires owned terminal teardown')
            failure.console = console
            failure.reservation = reservation
            failure.native_command_started = native_started
            failure.worker_cleanup_verified = True
            raise failure from launch_error
        win._close(reservation)
        raise
