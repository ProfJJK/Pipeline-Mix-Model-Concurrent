"""Explicit human Antigravity (agy 1.3.1) Google sign-in for ONE worker slot (build-manifest step 4).

Standalone helper copied, with its hash-pinned support module, into a fresh protected session root
C:\\Program Files\\CoChem\\InteractiveAgy427-r4-<slot>-<nonce> by login_pipeline_worker_interactive_agy_r4_v1.ps1
and run once as SYSTEM by the one-shot task CoChem-4.2.7-InteractiveAgy-r4-<slot>-<nonce>. It never runs from
the checkout, never dispatches a model request and never reads a token or credential value.

Derived from worker_claude_login_bridge_r3.py (sha256 b5bbede8...): the private one-line channel, the
bounded output pump, feed-once, cancellation and verified cleanup are kept. The agy differences:
  * argv by the login mode decided by the signed-out capture (login-mode.json, agy-status-capture-r4-v1):
    print -> [agy.exe, '-p', '/model'] (prompt in argv so stdin stays free for the code; read-only slash
    command, no inference); tui -> [agy.exe]; any other value is refused before a receipt exists;
  * the one fed line ends in LF (print) or CRLF (tui: a bubbletea TUI submits on CR only, LF is ctrl+j);
  * native output is published to operator.log only before the line is fed, and only as display-safe text
    (escape sequences and control characters removed); nothing after the feed is ever written anywhere. The
    pre-input bound counts the published (sanitized) bytes, so redraw escapes never exhaust it; the raw stream
    is bounded by the LOGIN_SECONDS window. Display text beyond MAX_OUTPUT stops the session with
    NativeOutputBoundError (a reviewed terminal class of the history script);
  * the bridge writes input.closed (bound to the nonce) before it leaves its read loop on any path; the wrapper
    refuses input once it exists, and nothing is read from input.once after the LOGIN_SECONDS window;
  * after the feed the bridge waits at most POST_INPUT_SECONDS: exit 0 -> LOGIN_COMMAND_EXITED_ZERO_STATUS_
    REQUIRED; still running (an interactive TUI) -> the owned Job is terminated and the status is
    LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED; non-zero -> LOGIN_COMMAND_FAILED with a sanitized phase.
    The separate reviewed status check (worker-native-auth-status-six-r4-v1.py, stage after) is the authority;
  * fixed failure, success and rate-limit/verification markers are scanned for allowlisted booleans only, on
    case-folded text in which '-' and '_' read as spaces. After the feed the phrase markers all contain a space;
    the rate-limit marker is the same expression in both phases, and its short alternatives are anchored ('rate
    limit' at a word start, '429' only as a delimited whole word), so a pasted code is never a practical oracle;
  * token storage is observed by existence and size (antigravity-oauth-token) and by Credential Manager
    target names under the worker token (a count only); no token, name or e-mail is recorded.
Exit codes: 0 accepted terminal status with verified cleanup; 2 receipt written with any other status;
3 no receipt (argument, root or custody failure before the receipt was created).
"""
from __future__ import annotations

import argparse
import codecs
import ctypes as C
from ctypes import wintypes as W
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import re
import stat
import sys
import threading
import time

SUPPORT_SHA256 = '45681477194d97b144e8ee4505d4364d73d58aaef19c8428c846df642c834839'
MAX_INPUT = 2048
MAX_OUTPUT = 131072
LOGIN_SECONDS = 600
POST_INPUT_SECONDS = 120
TERMINATE_WAIT_SECONDS = 30
DRAIN_SECONDS = 2.0
CREDENTIAL_SECONDS = 10.0
INSTALL = Path(r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4')
NATIVE = Path(r'C:\Program Files\CoChem\Native4.2.7-windows-20261006\agy.exe')
SESSION_PARENT = Path(r'C:\Program Files\CoChem')
ROOT_PREFIX = 'InteractiveAgy427-r4-'
HELPER_NAME = 'worker_agy_login_bridge_r4_v1.py'
SUPPORT_NAME = 'worker_native_status_support.py'
LAYOUT_SHA256 = '8430fdf1109c63c4a89479f03da8a465dfebf5566c7791c64f868202170672c4'
CONFIG_SHA256 = '135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
AGY_SHA256 = '38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741'
SLOTS = tuple(f'slot{index}' for index in range(1, 7))
LOGIN_ARGUMENTS = {'print': ('-p', '/model'), 'tui': ()}
# A line reader (print mode) takes LF; a bubbletea TUI submits only on CR (LF is ctrl+j), and a Go line reader
# trims the CR, so the TUI mode feeds CRLF. Either way exactly one line is fed, then EOF.
LINE_ENDINGS = {'print': b'\n', 'tui': b'\r\n'}
STATUS_EXITED_ZERO = 'LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED'
STATUS_SESSION_ENDED = 'LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED'
STATUS_FAILED = 'LOGIN_COMMAND_FAILED'
STATUS_FAILED_OR_CANCELLED = 'LOGIN_FAILED_OR_CANCELLED'
STATUS_CLEANUP_UNVERIFIED = 'CLEANUP_UNVERIFIED'
ACCEPTED_STATUSES = (STATUS_EXITED_ZERO, STATUS_SESSION_ENDED)
TOKEN_FILE_PARTS = ('.gemini', 'antigravity-cli', 'antigravity-oauth-token')
CREDENTIAL_NAME_FRAGMENTS = ('jetski', 'antigravity')
ERROR_NOT_FOUND = 1168
EOF = b''
CLOSED_NAME = 'input.closed'
CLOSED_PREFIX = b'cochem-login-input-closed/1\n'

# Before the feed the text is published anyway, so plain regular expressions are allowed.
BEFORE_PATTERNS = {
    'url_present': r'https://',
    'google_accounts_url_present': r'https://accounts\.google\.com/',
    'paste_prompt_present': r'(?:paste|enter) the authorization code|enter the redirect url',
    'waiting_line_present': r'waiting for authentication',
    'token_exchanged_present': r'successfully exchanged authorization code',
    'authenticated_as_present': r'authenticated as ',
    'authentication_required_present': r'authentication required',
    'no_controlling_terminal_present': r'no controlling terminal',
    'authentication_interrupted_present': r'authentication interrupted',
    'auth_timed_out_present': r'auth timed out',
    'authorization_code_empty_present': r'authorization code cannot be empty',
    'no_authorization_code_received_present': r'no authorization code received',
    'authentication_failed_present': r'error: authentication failed',
    'rate_limit_present': r'\brate ?limit|too many requests|resource exhausted|quota exceeded|try again later|(?<![^\s(\["])429(?![^\s.,;:!?)\]"])',
    'verification_present': r'\bverify\b|identity verification|account verification|verification required',
    'appeal_present': r'\bappeal\b',
    'unusual_activity_present': r'unusual activity',
}
# After the feed: plain phrases only, every one containing a space (a pasted code or URL has none).
AFTER_PHRASES = {
    'paste_prompt_present': ('paste the authorization code', 'enter the authorization code', 'enter the redirect url'),
    'waiting_line_present': ('waiting for authentication',),
    'token_exchanged_present': ('successfully exchanged authorization code',),
    'authenticated_as_present': ('authenticated as ',),
    'authentication_required_present': ('authentication required',),
    'no_controlling_terminal_present': ('no controlling terminal',),
    'authentication_interrupted_present': ('authentication interrupted',),
    'auth_timed_out_present': ('auth timed out',),
    'authorization_code_empty_present': ('authorization code cannot be empty',),
    'no_authorization_code_received_present': ('no authorization code received',),
    'authentication_failed_present': ('error: authentication failed',),
    'verification_present': ('verify it', 'verify your', 'identity verification', 'account verification',
                             'verification required'),
    'appeal_present': ('submit an appeal', 'appeal the', 'appeal this', 'appeal your'),
    'unusual_activity_present': ('unusual activity',),
}
# Matched after the feed with the same BEFORE_PATTERNS expression, so the pause never depends on the phase (rate
# limit, ratelimit, rate-limited, RESOURCE_EXHAUSTED, quota exceeded, try again later, 429 Too Many Requests).
SHARED_MARKERS = ('rate_limit_present',)
PAUSE_MARKERS = ('rate_limit_present', 'verification_present', 'appeal_present', 'unusual_activity_present')
TOKEN_STORAGE_NOT_RUN = {
    'file_check': 'not_run', 'file_token_present': None, 'file_token_bytes': None, 'file_token_regular': None,
    'credential_manager_check': 'not_run', 'credential_manager_entry_present': None,
    'credential_manager_matching_entries': None, 'token_contents_read': False,
}

_OSC8 = re.compile(r'\x1b\]8;[^;\x07\x1b]*;([^\x07\x1b]*)(?:\x07|\x1b\\)')
_ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\^_]')
_CSI_COMPLETE = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
_OSC_COMPLETE = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)')
_UNSAFE = re.compile('[\x00-\x08\x0b-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]')
_WHITESPACE = re.compile(r'\s+')
_MARKER_SEPARATORS = re.compile('[-_]')


class NativeOutputBoundError(ValueError):
    """Display text before the feed exceeded MAX_OUTPUT; the receipt names this type (a reviewed terminal class)."""


def login_argv(mode):
    """The reviewed mode -> argv table; anything else (including 'none') is refused."""
    if not isinstance(mode, str) or mode not in LOGIN_ARGUMENTS:
        raise ValueError('Only the reviewed print and tui login modes are supported')
    return [str(NATIVE), *LOGIN_ARGUMENTS[mode]]


def session_root(slot, nonce):
    if slot not in SLOTS or not isinstance(nonce, str) or not re.fullmatch('[0-9a-f]{32}', nonce) or nonce == '0' * 32:
        raise ValueError('A configured slot and a fresh nonzero 32-hex nonce are required')
    return SESSION_PARENT / f'{ROOT_PREFIX}{slot}-{nonce}'


def parse_packet(raw, nonce, *, cancel=False):
    """No value from the private channel appears in exception messages."""
    prefix = b'cochem-login-input/1\n' + nonce.encode('ascii') + b'\n'
    if not isinstance(raw, bytes) or len(raw) > len(prefix) + MAX_INPUT + 1 or not raw.startswith(prefix):
        raise ValueError('Private input binding or size differs')
    line = raw[len(prefix):]
    if not line.endswith(b'\n') or not 1 <= len(line) - 1 <= MAX_INPUT:
        raise ValueError('Exactly one bounded input line is required')
    value = line[:-1]
    if any(char in value for char in (b'\r', b'\n', b'\0')):
        raise ValueError('Input contains a forbidden line delimiter')
    value.decode('utf-8', 'strict')
    if cancel and value != b'CANCEL':
        raise ValueError('Cancellation marker differs')
    return value


class ChannelFile:
    """Held, no-write/no-delete-share single-link channel; optional handle delete (unchanged from r3).

    Files are opened with OPEN_REPARSE_POINT, then checked through the same handle. No pathname reopen is
    used for bytes, identity, hash or deletion. The root and this file must pass the private ACL validator.
    """
    def __init__(self, path, win):
        win.validate_private_path(path)
        self.path, self.handle = Path(path), None
        self.api = C.WinDLL('kernel32', use_last_error=True)
        self.api.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
        self.api.CreateFileW.restype = W.HANDLE
        self.api.CloseHandle.argtypes = [W.HANDLE]; self.api.CloseHandle.restype = W.BOOL
        self.api.ReadFile.argtypes = [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]
        self.api.ReadFile.restype = W.BOOL
        self.api.GetFinalPathNameByHandleW.argtypes = [W.HANDLE, W.LPWSTR, W.DWORD, W.DWORD]
        self.api.GetFinalPathNameByHandleW.restype = W.DWORD
        self.api.SetFileInformationByHandle.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]
        self.api.SetFileInformationByHandle.restype = W.BOOL
        self.handle = self.api.CreateFileW(str(path), 0x80010000, 1, None, 3, 0x00200000, None)
        if self.handle == C.c_void_p(-1).value:
            self.handle = None
            raise C.WinError(C.get_last_error())
        try:
            class Info(C.Structure):
                _fields_ = [('attributes', W.DWORD), ('created', W.FILETIME), ('accessed', W.FILETIME),
                            ('written', W.FILETIME), ('volume', W.DWORD), ('high', W.DWORD),
                            ('low', W.DWORD), ('links', W.DWORD), ('index_high', W.DWORD), ('index_low', W.DWORD)]
            info = Info()
            self.api.GetFileInformationByHandle.argtypes = [W.HANDLE, C.POINTER(Info)]
            self.api.GetFileInformationByHandle.restype = W.BOOL
            if not self.api.GetFileInformationByHandle(self.handle, C.byref(info)):
                raise C.WinError(C.get_last_error())
            size = info.high << 32 | info.low
            if info.attributes & (0x400 | 0x10) or info.links != 1 or not 1 <= size <= MAX_INPUT + 128:
                raise ValueError('Private input must be a bounded ordinary single-link file')
            buffer = C.create_unicode_buffer(32768)
            count = self.api.GetFinalPathNameByHandleW(self.handle, buffer, len(buffer), 0)
            expected = '\\\\?\\' + str(self.path.absolute())
            if not 0 < count < len(buffer) or buffer.value.casefold() != expected.casefold():
                raise ValueError('Private input final handle path differs')
            data = C.create_string_buffer(size + 1); read = W.DWORD()
            if not self.api.ReadFile(self.handle, data, size + 1, C.byref(read), None):
                raise C.WinError(C.get_last_error())
            if read.value != size:
                raise ValueError('Private input size changed')
            self.raw = data.raw[:read.value]
            # In-memory binding only. Never persist it: a receipt must not expose a code oracle.
            self._sha256 = hashlib.sha256(self.raw).digest()
            C.memset(C.addressof(data), 0, len(data))
        except BaseException:
            self.close()
            raise

    def delete_after_verified_cleanup(self):
        if not self.handle:
            raise ValueError('Input handle is not held')
        delete = C.c_ubyte(1)  # FILE_DISPOSITION_INFO.DeleteFile is BOOLEAN.
        if not self.api.SetFileInformationByHandle(self.handle, 4, C.byref(delete), C.sizeof(delete)):
            raise C.WinError(C.get_last_error())
        self.close()

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle); self.handle = None
        self.raw = b''; self._sha256 = b''


def _incomplete_escape_start(text):
    """Index of a trailing escape sequence that is not yet complete, else -1."""
    osc = text.rfind('\x1b]')
    if osc >= 0 and not _OSC_COMPLETE.match(text, osc) and len(text) - osc <= 4096:
        return osc  # An operating-system command (for example a hyperlink) still waits for its terminator.
    cut = text.rfind('\x1b')
    if cut < 0:
        return -1
    tail = text[cut:]
    if len(tail) > 4096:
        return -1  # Not a sequence; the control filter removes the ESC itself.
    if tail == '\x1b':
        return cut
    if tail.startswith('\x1b['):
        return -1 if _CSI_COMPLETE.match(tail) else cut
    if tail.startswith('\x1b]'):
        return -1 if _OSC_COMPLETE.match(tail) else cut
    return -1


def sanitize_text(text):
    """Display-safe text: hyperlink targets kept visible, escapes, controls and bidi overrides removed."""
    text = _OSC8.sub(lambda match: (' ' + match.group(1) + ' ') if match.group(1) else '', text)
    text = _ANSI.sub('', text)
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return _UNSAFE.sub('', text)


class Publisher:
    """Incremental UTF-8 decoding plus sanitizing that never splits a character or an escape sequence."""
    def __init__(self):
        self._decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self._pending = ''

    def feed(self, data, final=False):
        text = self._pending + self._decoder.decode(data, final)
        self._pending = ''
        if not final:
            cut = _incomplete_escape_start(text)
            if cut >= 0:
                text, self._pending = text[:cut], text[cut:]
        return sanitize_text(text)


def classify_markers(text, *, after_input):
    """Allowlisted booleans only; the text itself is never returned or stored."""
    text = _MARKER_SEPARATORS.sub(' ', text)  # rate-limited, RESOURCE_EXHAUSTED, too_many_requests
    folded = _WHITESPACE.sub(' ', text).casefold()
    if after_input:
        markers = {name: any(phrase in folded for phrase in phrases) for name, phrases in AFTER_PHRASES.items()}
        markers.update((name, re.search(BEFORE_PATTERNS[name], folded) is not None) for name in SHARED_MARKERS)
        return markers
    return {name: re.search(pattern, folded) is not None for name, pattern in BEFORE_PATTERNS.items()}


def pause_marker_seen(markers):
    if not isinstance(markers, dict):
        return False
    return any(bool(markers.get(phase, {}).get(name)) for phase in ('before_input', 'after_input')
               for name in PAUSE_MARKERS)


class SessionOutput:
    """Publishes sanitized text until the feed; afterwards retains a bounded copy for marker scanning only."""
    def __init__(self, log, report):
        self.log, self.report = log, report
        self.total = 0
        self.published = 0
        self.retained_after = 0
        self.before, self.after = Publisher(), Publisher()
        self.before_text, self.after_text = [], []

    def accept(self, data, submitted):
        self.total += len(data)
        if not submitted:
            # Raw bytes (escapes included) are counted, not bounded: the LOGIN_SECONDS window bounds them.
            self.report['native_output_bytes_before_input'] = self.total
            text = self.before.feed(data)
            if text:
                encoded = text.encode('utf-8')
                if self.published + len(encoded) > MAX_OUTPUT:
                    self.report['native_output_bound_reached_before_input'] = True
                    raise NativeOutputBoundError('Sanitized native output exceeded its bound before input')
                self.log.write(encoded)
                self.log.flush()
                self.published += len(encoded)
                self.report['native_output_published_bytes_before_input'] = self.published
                self.before_text.append(text)
        elif self.retained_after + len(data) <= MAX_OUTPUT:
            # Never published; drained so the child cannot block while persisting its token.
            self.retained_after += len(data)
            self.after_text.append(self.after.feed(data))
        else:
            self.report['native_output_bound_reached_after_input'] = True

    def finish(self):
        self.report['native_markers'] = {
            'before_input': classify_markers(''.join(self.before_text), after_input=False),
            'after_input': classify_markers(''.join(self.after_text), after_input=True)}
        self.report['pause_marker_seen'] = pause_marker_seen(self.report['native_markers'])
        self.before_text.clear()
        self.after_text.clear()


def _offer(events, item, stopped):
    while not stopped.is_set():
        try:
            events.put(item, timeout=.1)
            return
        except queue.Full:
            pass


def pump(stream, events, stopped):
    """Bounded memory only. Never write raw provider output to disk. EOF is signalled by an empty chunk."""
    marker = EOF
    try:
        while not stopped.is_set():
            data = stream.read(4096)
            if not data:
                break
            _offer(events, data, stopped)
    except (OSError, ValueError):
        marker = None
    finally:
        stream.close()
    if not stopped.is_set():
        _offer(events, marker, stopped)


def feed_once(stream, value, ending=b'\n'):
    # The reviewed packet is at most 2048 bytes; the anonymous pipe has at least the Win32 default
    # 4096-byte buffer. One bounded line, flush, EOF.
    try:
        if ending not in (b'\n', b'\r\n'):
            raise ValueError('Only the reviewed line endings are fed')
        line = value + ending
        if stream.write(line) != len(line):
            raise OSError('Native input channel accepted an incomplete line')
        stream.flush()
    finally:
        stream.close()


def _take(events, output, submitted):
    """Read one queued chunk. Returns True at EOF."""
    data = events.get(timeout=.1)
    if data is None:
        raise OSError('Native output channel failed')
    if data == EOF:
        return True
    output.accept(data, submitted)
    del data
    return False


def close_input_window(root, nonce, report):
    """input.closed, created new and bound to the nonce: the wrapper writes no input once it exists.

    A failure is recorded (False), never raised: it must not mask how the read loop ended. The wrapper also
    deletes an unconsumed input.once after the task has ended, so a missing marker leaves no code behind.
    """
    try:
        with (Path(root) / CLOSED_NAME).open('xb') as stream:
            stream.write(CLOSED_PREFIX + nonce.encode('ascii') + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
        report['input_closed_marker_written'] = True
    except (OSError, ValueError):
        report['input_closed_marker_written'] = False


def _interactive(process, writer, events, output, root, nonce, win, report, channels):
    try:
        return _read_loop(process, writer, events, output, root, nonce, win, report, channels)
    finally:
        # Every exit (exit code, post-input end, deadline, cancellation, output bound, error) closes input first.
        close_input_window(root, nonce, report)


def _read_loop(process, writer, events, output, root, nonce, win, report, channels):
    deadline = time.monotonic() + LOGIN_SECONDS
    submitted_at = None
    eof = False
    while True:
        now = time.monotonic()
        if submitted_at is None and now >= deadline:
            raise TimeoutError('Interactive login deadline expired')
        cancel = root / 'cancel.request'
        if cancel.exists():
            try:
                channel = ChannelFile(cancel, win)
            except OSError as error:
                if error.winerror == 32:
                    time.sleep(.05); continue
                raise
            channels.append(channel)
            parse_packet(channel.raw, nonce, cancel=True)
            report['operator_cancelled'] = True
            raise InterruptedError('Operator requested cancellation')
        input_path = root / 'input.once'
        if submitted_at is None and input_path.exists():
            try:
                channel = ChannelFile(input_path, win)
            except OSError as error:
                if error.winerror == 32:  # Owner is still finishing exclusive creation.
                    time.sleep(.05); continue
                raise
            channels.append(channel)
            value = parse_packet(channel.raw, nonce)
            report['one_line_submitted'] = True
            # Stop publishing ALL native text before the secret reaches stdin.
            output.log.flush()
            feed_once(writer, value, LINE_ENDINGS.get(report.get('login_mode'), b'\n'))
            del value
            submitted_at = time.monotonic()
            now = submitted_at
        if submitted_at is not None and now - submitted_at >= POST_INPUT_SECONDS:
            code = process.poll()
            if code is None:
                # An interactive TUI may keep running after sign-in: end it through the owned Job.
                report['terminated_after_input'] = True
                process.terminate()
                code = process.wait(timeout=TERMINATE_WAIT_SECONDS)
            return code, eof
        if not eof:
            try:
                eof = _take(events, output, submitted_at is not None)
            except queue.Empty:
                pass
        else:
            time.sleep(.1)
        code = process.poll()
        if code is not None:
            return code, eof


def _drain(events, output, submitted, eof):
    """After exit, publish (before input) or classify (after input) what the pipe still holds."""
    deadline = time.monotonic() + DRAIN_SECONDS
    while not eof and time.monotonic() < deadline:
        try:
            eof = _take(events, output, submitted)
        except queue.Empty:
            pass


def run_loop(process, writer, events, log, root, nonce, win, report, channels):
    output = SessionOutput(log, report)
    try:
        code, eof = _interactive(process, writer, events, output, root, nonce, win, report, channels)
        _drain(events, output, bool(report.get('one_line_submitted')), eof)
        return code
    finally:
        output.finish()


def load_support(root):
    path = root / SUPPORT_NAME
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SUPPORT_SHA256:
        raise ValueError('Reviewed login support changed')
    module = importlib.util.module_from_spec(importlib.util.spec_from_file_location('agy_login_support', path))
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def runtime_modules():
    from cochem_pipeline import windows as win
    from cochem_pipeline.resource_limits import ResourceLimits
    from cochem_pipeline.ramdisk import ordinary_tree
    return win, ResourceLimits, ordinary_tree


def token_profile_directory(win, token):
    api = win._api()
    count = win.DWORD()
    api['userenv'].GetUserProfileDirectoryW(token, None, C.byref(count))
    if not 1 <= count.value <= 32768:
        raise ValueError('Worker profile path has an invalid bound')
    buffer = C.create_unicode_buffer(count.value)
    win._check(api['userenv'].GetUserProfileDirectoryW(token, buffer, C.byref(count)), 'Read worker token profile')
    return Path(buffer.value)


def file_token_observation(profile):
    """Existence, size and kind of the agy file-token fallback; the file is never opened."""
    path = Path(profile).joinpath(*TOKEN_FILE_PARTS)
    result = {'file_check': 'ok', 'file_token_present': False, 'file_token_bytes': None, 'file_token_regular': None}
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return result
    except OSError:
        return {'file_check': 'failed', 'file_token_present': None, 'file_token_bytes': None, 'file_token_regular': None}
    regular = stat.S_ISREG(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400
    result.update(file_token_present=True, file_token_bytes=int(info.st_size), file_token_regular=bool(regular))
    return result


class _CredentialPrefix(C.Structure):
    # Only the leading fields of CREDENTIALW: the blob fields are never reachable through this view.
    _fields_ = [('Flags', W.DWORD), ('Type', W.DWORD), ('TargetName', W.LPWSTR)]


class CredentialApi:
    def __init__(self):
        advapi = C.WinDLL('advapi32', use_last_error=True)
        self.impersonate = advapi.ImpersonateLoggedOnUser
        self.impersonate.argtypes, self.impersonate.restype = [W.HANDLE], W.BOOL
        self.revert = advapi.RevertToSelf
        self.revert.argtypes, self.revert.restype = [], W.BOOL
        self.enumerate = advapi.CredEnumerateW
        self.enumerate.argtypes = [W.LPCWSTR, W.DWORD, C.POINTER(W.DWORD), C.POINTER(C.c_void_p)]
        self.enumerate.restype = W.BOOL
        self.free = advapi.CredFree
        self.free.argtypes, self.free.restype = [C.c_void_p], None

    @staticmethod
    def last_error():
        return C.get_last_error()

    @staticmethod
    def target_names(pointer, count):
        array = C.cast(pointer, C.POINTER(C.POINTER(_CredentialPrefix)))
        for index in range(count):
            yield array[index].contents.TargetName


def count_matching_credentials(token, api):
    """Names only, under the worker token: how many Credential Manager targets name the agy store."""
    failed = {'credential_manager_check': 'failed', 'credential_manager_entry_present': None,
              'credential_manager_matching_entries': None}
    if not api.impersonate(token):
        return failed
    result = dict(failed)
    try:
        count, pointer = W.DWORD(), C.c_void_p()
        if not api.enumerate(None, 0, C.byref(count), C.byref(pointer)):
            if api.last_error() != ERROR_NOT_FOUND:
                return result
            matched = 0
        else:
            try:
                matched = sum(1 for name in api.target_names(pointer, count.value)
                              if name and any(fragment in name.casefold() for fragment in CREDENTIAL_NAME_FRAGMENTS))
            finally:
                api.free(pointer)
        result.update(credential_manager_check='ok', credential_manager_entry_present=matched > 0,
                      credential_manager_matching_entries=matched)
        return result
    finally:
        if not api.revert():
            # The dedicated thread ends here; its impersonation ends with it. Report as unverified.
            result.update(failed)


def credential_observation(token, api_factory=CredentialApi, timeout=None):
    """Runs on a dedicated thread so impersonation can never leak into the bridge's own thread."""
    box = {}

    def body():
        try:
            box['value'] = count_matching_credentials(token, api_factory())
        except BaseException:
            box['value'] = None
    thread = threading.Thread(target=body, name='agy-credential-names', daemon=True)
    thread.start()
    thread.join(CREDENTIAL_SECONDS if timeout is None else timeout)
    if thread.is_alive():
        return {'credential_manager_check': 'timed_out', 'credential_manager_entry_present': None,
                'credential_manager_matching_entries': None}
    value = box.get('value')
    if not isinstance(value, dict):
        return {'credential_manager_check': 'failed', 'credential_manager_entry_present': None,
                'credential_manager_matching_entries': None}
    return value


def observe_token_storage(win, process):
    value = dict(TOKEN_STORAGE_NOT_RUN)
    token = getattr(process, '_token', None)
    try:
        value.update(file_token_observation(token_profile_directory(win, token)))
    except Exception:
        value['file_check'] = 'failed'
    try:
        value.update(credential_observation(token))
    except Exception:
        value['credential_manager_check'] = 'failed'
    value['token_contents_read'] = False
    return value


def terminal_status(code, report):
    if report.get('terminated_after_input'):
        return STATUS_SESSION_ENDED
    return STATUS_EXITED_ZERO if code == 0 else STATUS_FAILED


def cleanup_session(process, writer, stopped, threads, channels, report, postcheck):
    """Delete only consumed private channel files after actual terminal proof."""
    if process is not None:
        process.close()
        report['cleanup_verified'] = True
    if writer is not None:
        writer.close()
    stopped.set()
    for thread in threads:
        thread.join(timeout=3)
    if any(thread.is_alive() for thread in threads):
        raise RuntimeError('Native output reader did not terminate')
    if process is not None and report['cleanup_verified']:
        postcheck()
        for channel in channels:
            channel.delete_after_verified_cleanup()
        report['input_file_deleted'] = bool(channels)


def new_report(slot, nonce, mode, win, helper_sha256):
    return {'schema': 'cochem-interactive-agy-login/1', 'slot': slot, 'nonce': nonce, 'login_mode': mode,
            'native_arguments': list(LOGIN_ARGUMENTS[mode]), 'system_sid': win.SYSTEM_SID,
            'helper_sha256': helper_sha256, 'support_sha256': SUPPORT_SHA256,
            'status': 'UNVERIFIED', 'cleanup_verified': False, 'one_line_submitted': False,
            'input_file_deleted': False, 'operator_cancelled': False, 'terminated_after_input': False,
            'login_commands_executed': 0, 'model_jobs_executed': 0, 'authentication_verified': False,
            'activation_ready': False, 'secret_published': False, 'native_output_after_input_published': False,
            'native_output_bytes_before_input': 0, 'native_output_bound_reached_after_input': False,
            'native_output_published_bytes_before_input': 0, 'native_output_bound_reached_before_input': False,
            'input_closed_marker_written': False,
            'pause_marker_seen': False, 'native_markers': None, 'token_storage_observed': dict(TOKEN_STORAGE_NOT_RUN),
            'started_at_unix_ms': int(time.time() * 1000)}


def run(slot, nonce, mode):
    argv = login_argv(mode)
    root = session_root(slot, nonce)
    win, resource_limits, ordinary_tree = runtime_modules()
    win.require_system()
    if Path(__file__).resolve() != root / HELPER_NAME:
        raise ValueError('Use only the fresh protected session helper')
    for path in (root, Path(__file__), root / SUPPORT_NAME):
        ordinary_tree(path); win.validate_code_path(path)
    win.validate_private_directory(root)
    support = load_support(root)
    report = new_report(slot, nonce, mode, win, support.digest_file(Path(__file__)))
    channels = []; process = None; writer = None; stopped = threading.Event(); threads = []
    phase = 'runtime_custody'
    with (root / 'receipt.json').open('x', encoding='utf-8') as receipt:
        try:
            support.validate_interpreter()
            if Path(support.INSTALL) != INSTALL or Path(support.NATIVE) / 'agy.exe' != NATIVE:
                raise ValueError('Reviewed support module names another runtime')
            if support.digest_file(Path(win.__file__)) != support.WINDOWS_SHA256:
                raise ValueError('Installed Windows launch implementation changed')
            report['revision'] = support.verify_r4_runtime(win, support.INSTALL_RECEIPT_SHA256)
            report.update(runtime_root=str(INSTALL), install_receipt_sha256=support.INSTALL_RECEIPT_SHA256,
                          source_manifest_sha256=support.MANIFEST_SHA256, resource_limits_sha256=support.RESOURCE_SHA256)
            support.require_stopped(win)
            phase = 'layout'
            layout, layout_hash = support.protected_json(win, INSTALL / 'windows-layout.json')
            config, config_hash = support.protected_json(win, INSTALL / 'pipeline.json')
            if (layout_hash != LAYOUT_SHA256 or config_hash != CONFIG_SHA256
                    or layout_hash != support.LAYOUT_SHA256 or config_hash != support.CONFIG_SHA256):
                raise ValueError('Installed layout/config binding changed')
            report.update(layout_sha256=layout_hash, config_sha256=config_hash)
            spec = layout['slots'][slot]
            identity = win.WorkerIdentity(spec['identity'], spec['credential_target'])
            sid = win._sid_text(win._account_sid(identity.name))
            if sid != spec['sid']:
                raise ValueError('Installed account SID changed')
            if Path(config['providers']['gemini']['executable']) != NATIVE:
                raise ValueError('Protected gemini provider path differs from the reviewed agy executable')
            phase = 'native_custody'
            ordinary_tree(NATIVE); win.validate_code_path(NATIVE)
            before = support.digest_file(NATIVE)
            if before != support.CONTRACTS['gemini']['sha256'] or before != AGY_SHA256:
                raise ValueError('Reviewed native agy executable changed')
            report['native_executable_sha256'] = before
            limits = resource_limits.from_dict(config['execution_limits'])
            events = queue.Queue(maxsize=32)
            stdin_read, stdin_write = os.pipe(); out_read, out_write = os.pipe()
            writer = os.fdopen(stdin_write, 'wb', buffering=0)
            output_reader = os.fdopen(out_read, 'rb', buffering=0)
            thread = threading.Thread(target=pump, args=(output_reader, events, stopped), daemon=True)
            threads.append(thread); thread.start()
            phase = 'native_launch'
            with os.fdopen(stdin_read, 'rb', buffering=0) as stdin, os.fdopen(out_write, 'wb', buffering=0) as output:
                # Never login_worker/login_gemini_worker: they feed stdin from an empty file.
                process = win.launch_worker(identity, argv, spec['root'], stdin, output, output, limits=limits)
            report['login_commands_executed'] = 1
            phase = 'native_attestation'
            report['process'] = support.observe_child(win, process, sid, NATIVE)
            phase = 'native_wait'
            with (root / 'operator.log').open('xb', buffering=0) as log:
                code = run_loop(process, writer, events, log, root, nonce, win, report, channels)
            phase = 'native_result'
            report['native_exit_code'] = code
            # Before cleanup: the worker token and profile are still loaded by the owned process.
            report['token_storage_observed'] = observe_token_storage(win, process)
            report['status'] = terminal_status(code, report)
            if report['status'] == STATUS_FAILED:
                report['login_failure'] = {'phase': 'native_result' if report['one_line_submitted'] else 'native_wait',
                                           'error_type': 'NativeLoginExitNonZero', 'winerror': None}
            after = support.digest_file(NATIVE)
            report['native_executable_sha256_after'] = after
            if after != before:
                raise ValueError('Native agy executable changed during the login')
        except BaseException as error:
            report['status'] = STATUS_FAILED_OR_CANCELLED
            report['failure'] = support.safe_failure(error, phase)
        finally:
            phase = 'native_cleanup'
            try:
                cleanup_session(process, writer, stopped, threads, channels, report, lambda: support.require_stopped(win))
            except BaseException as error:
                report['status'] = STATUS_CLEANUP_UNVERIFIED
                report['cleanup_verified'] = False
                report['failure'] = support.safe_failure(error, phase)
            for channel in channels:
                channel.close()  # Failed cleanup preserves the private file.
            report['pause_marker_seen'] = pause_marker_seen(report.get('native_markers'))
            report['finished_at_unix_ms'] = int(time.time() * 1000)
            json.dump(report, receipt, ensure_ascii=True, sort_keys=True, indent=2)
            receipt.flush(); os.fsync(receipt.fileno())
    return 0 if report['status'] in ACCEPTED_STATUSES and report['cleanup_verified'] else 2


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('Invalid bridge arguments')


def main(argv=None):
    parser = _Parser(description='Interactive agy login bridge (r4-v1)', add_help=False)
    parser.add_argument('--slot', required=True)
    parser.add_argument('--nonce', required=True)
    parser.add_argument('--login-mode', required=True, dest='login_mode')
    try:
        args = parser.parse_args(argv)
        session_root(args.slot, args.nonce)
        login_argv(args.login_mode)
        return run(args.slot, args.nonce, args.login_mode)
    except BaseException as error:
        # No native/error message or input material reaches public stderr.
        print(json.dumps({'status': 'PRE_RECEIPT_FAILURE', 'error_type': type(error).__name__}), file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
