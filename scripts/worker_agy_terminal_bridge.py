"""Fresh protected, SYSTEM-only terminal sign-in helper. Inert on import.

Uses exact pinned legacy channel/custody helpers without editing the R4 install
or old sessions. The terminal module is staged separately in this same root.
Only one native no-argument Agy session is launched. Model input is prohibited.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import re
import sys
import threading
import time

PARENT_NAME = 'worker_agy_login_bridge_r4_v1.py'
PARENT_PIN = '4074878f100ae59b804c95bd97b3280ccaa09f919ffaa365a3e2c6985045b8d9'
TERMINAL_NAME = 'attended_agy_terminal.py'
TERMINAL_PIN = 'bedff42652ca92031ef056ef9f21d584c502bc9f1227598b1098f83f808ebeda'
HELPER_NAME = 'worker_agy_terminal_bridge.py'
ROOT_PREFIX = 'InteractiveAgyTerminal427-r4-'
SESSION_PARENT = Path(r'C:\Program Files\CoChem')
STARTUP_SECONDS = 30
PROMPT_SECONDS = 60


def session_root(slot, nonce):
    if (slot not in tuple(f'slot{i}' for i in range(1, 7)) or not isinstance(nonce, str)
            or not re.fullmatch('[0-9a-f]{32}', nonce) or nonce == '0'*32):
        raise ValueError('A configured slot and fresh nonzero session nonce are required')
    return SESSION_PARENT / f'{ROOT_PREFIX}{slot}-{nonce}'


def pinned_module(root, name, pin):
    path = root / name
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin:
        raise ValueError('Protected terminal helper binding differs')
    module = importlib.util.module_from_spec(importlib.util.spec_from_file_location('attended_' + path.stem, path))
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


class TerminalOutput:
    """One ready consent screen, bounded redraw scanning, no secret publication."""
    def __init__(self, legacy, log, report, terminal=None):
        self.legacy, self.report = legacy, report
        self.output = legacy.SessionOutput(log, report)
        if terminal is None:
            from cochem_pipeline import attended_agy_terminal as terminal
        self.display = terminal.TerminalPublisher(legacy)
        self.output.before = terminal.TerminalPublisher(legacy)
        self.window = ''
        self.prompt_ready = False
        self.extra_markers = {}
        self.after_display = legacy.Publisher()
        self.after_window = ''
        self.native_auth_success = False

    def accept(self, data, submitted):
        display = ''
        if not submitted:
            display = self.display.feed(data)
            self.window = (self.window + display)[-16384:]
            markers = self.legacy.classify_markers(self.window, after_input=False)
            for name, seen in markers.items():
                self.extra_markers[name] = self.extra_markers.get(name, False) or seen
            frozen = self.prompt_ready
            url = re.search(r'https://accounts\.google\.com/', self.window, re.I)
            # Require order as well as marker presence: an earlier stale code
            # prompt must not unlock a later URL in this process's output.
            self.prompt_ready = self.prompt_ready or bool(url and re.search(
                r'(?:paste|enter) the authorization code|enter the redirect url',
                self.window[url.end():], re.I))
            if frozen:
                # Never exhaust the public log merely by repainting a ready
                # code field while the owner completes browser consent.
                self.output.total += len(data)
                self.report['native_output_bytes_before_input'] = self.output.total
            else:
                self.output.accept(data, False)
        else:
            self.window = ''
            self.output.accept(data, True)
            self.after_window = (self.after_window + self.after_display.feed(data))[-16384:]
            markers = self.legacy.classify_markers(self.after_window, after_input=True)
            self.native_auth_success = bool((markers.get('token_exchanged_present') or markers.get('authenticated_as_present'))
                and not any(markers.get(name) for name in (*self.legacy.PAUSE_MARKERS,
                    'authentication_failed_present', 'authentication_interrupted_present', 'auth_timed_out_present')))
        return display

    def finish(self):
        self.output.finish()
        for name, seen in self.extra_markers.items():
            self.report['native_markers']['before_input'][name] |= seen
        self.report['pause_marker_seen'] = self.legacy.pause_marker_seen(self.report['native_markers'])
        self.window = ''
        self.after_window = ''


def end_completed_native_session(legacy, session, output, win, report, elapsed):
    """End an idle TUI only after native success text AND stored-token metadata.

    This removes the unconditional two-minute pause between initial consent
    prompts. It never grants authentication: the subsequent native status
    probe remains mandatory. Slow exchanges retain the full existing timeout.
    No credential contents are opened or copied.
    """
    if elapsed < 5 or not output.native_auth_success:
        return None
    storage = legacy.observe_token_storage(win, session)
    if (storage.get('token_contents_read') is not False or not
            (storage.get('file_token_present') is True or storage.get('credential_manager_entry_present') is True)):
        return None
    code = session.poll()
    if code is None:
        report['terminated_after_input'] = True
        session.terminate()
        code = session.wait(timeout=legacy.TERMINATE_WAIT_SECONDS)
    return code


def consume_input(legacy, terminal, output, writer, root, nonce, win, report, channels):
    path = root / 'input.once'
    if report.get('one_line_submitted') or not path.exists():
        return False
    if not output.prompt_ready:
        raise ValueError('Code input requires a fresh native Google URL and code prompt')
    try:
        channel = legacy.ChannelFile(path, win)
    except OSError as error:
        if getattr(error, 'winerror', None) == 32:
            return False  # Owner is still completing exclusive packet creation.
        raise
    channels.append(channel)
    value = legacy.parse_packet(channel.raw, nonce)
    # This boundary applies even if the following write accepts only a prefix.
    report['one_line_submitted'] = True
    output.output.log.flush()
    terminal.submit_authorization_code(writer, value)
    report['code_write_completed'] = True
    del value
    return True


def read_loop(legacy, terminal, session, events, output, root, nonce, win, report, channels):
    started = time.monotonic()
    submitted_at = None
    consent = terminal.NativeGoogleConsent()
    replies = terminal.TerminalReplies()
    eof = False
    try:
        while True:
            now = time.monotonic()
            if not report['one_line_submitted']:
                if now - started >= STARTUP_SECONDS and report['native_output_bytes_before_input'] == 0:
                    report['terminal_hold_reason'] = 'NO_NATIVE_STARTUP_OUTPUT'
                    raise TimeoutError('Native terminal startup produced no output')
                if now - started >= PROMPT_SECONDS and not output.prompt_ready:
                    report['terminal_hold_reason'] = 'FRESH_GOOGLE_PROMPT_NOT_OBSERVED'
                    raise TimeoutError('The native Google consent prompt was not observed')
                if now - started >= legacy.LOGIN_SECONDS:
                    report['terminal_hold_reason'] = 'OWNER_INPUT_WINDOW_EXPIRED'
                    raise TimeoutError('Native terminal sign-in input window expired')
            cancel = root / 'cancel.request'
            if cancel.exists():
                try:
                    channel = legacy.ChannelFile(cancel, win)
                except OSError as error:
                    if getattr(error, 'winerror', None) == 32:
                        time.sleep(.05)
                        continue
                    raise
                channels.append(channel)
                legacy.parse_packet(channel.raw, nonce, cancel=True)
                report['operator_cancelled'] = True
                raise InterruptedError('Owner cancelled the terminal session')
            if submitted_at is None and consume_input(legacy, terminal, output, session.console.writer,
                                                       root, nonce, win, report, channels):
                submitted_at = time.monotonic()
            if submitted_at is not None and now - submitted_at >= legacy.POST_INPUT_SECONDS:
                code = session.poll()
                if code is None:
                    report['terminated_after_input'] = True
                    session.terminate()
                    code = session.wait(timeout=legacy.TERMINATE_WAIT_SECONDS)
                return code
            if submitted_at is not None:
                code = end_completed_native_session(legacy, session, output, win, report, now-submitted_at)
                if code is not None:
                    return code
            if not eof:
                try:
                    data = events.get(timeout=.1)
                    if data is None:
                        raise OSError('Native terminal output failed')
                    if data == legacy.EOF:
                        eof = True
                    else:
                        for reply in replies.feed(data):
                            if session.console.writer.write(reply) != len(reply):
                                raise OSError('Native terminal query response was incomplete')
                        display = output.accept(data, report['one_line_submitted'])
                        if not report['one_line_submitted']:
                            public_start = consent.before_input(display)
                            if public_start:
                                if session.console.writer.write(public_start) != len(public_start):
                                    raise OSError('Native Google selection was incomplete')
                                session.console.writer.flush()
                                report['native_google_start_key_sent'] = True
                        report['terminal_query_replies'] = replies.count
                        del data
                except queue.Empty:
                    pass
            else:
                time.sleep(.1)
            code = session.poll()
            if code is not None:
                return code
    finally:
        legacy.close_input_window(root, nonce, report)


def run(slot, nonce):
    root = session_root(slot, nonce)
    if Path(__file__).resolve() != root / HELPER_NAME:
        raise ValueError('Use only the fresh protected terminal session helper')
    from cochem_pipeline import windows as win
    from cochem_pipeline import resource_limits as resources
    from cochem_pipeline.ramdisk import ordinary_tree
    win.require_system()
    for path in (root, Path(__file__), root/PARENT_NAME, root/TERMINAL_NAME, root/'worker_native_status_support.py'):
        ordinary_tree(path)
        win.validate_code_path(path)
    win.validate_private_directory(root)
    legacy = pinned_module(root, PARENT_NAME, PARENT_PIN)
    terminal = pinned_module(root, TERMINAL_NAME, TERMINAL_PIN)
    support = legacy.load_support(root)
    report = legacy.new_report(slot, nonce, 'tui', win, support.digest_file(Path(__file__)))
    report.update(schema='cochem-interactive-agy-terminal-login/1', login_mode='terminal',
                  transport='CONPTY_MANUAL_GOOGLE', parent_bridge_sha256=PARENT_PIN,
                  terminal_module_sha256=TERMINAL_PIN, native_google_start_key_sent=False,
                  terminal_query_replies=0, terminal_cleanup_verified=False, terminal_hold_reason=None)
    report['code_write_completed'] = False
    phase = 'runtime_custody'
    session = None
    failed_console = None
    failed_worker_clean = False
    failed_reservation = None
    threads, channels = [], []
    stopped = threading.Event()
    events = queue.Queue(maxsize=32)
    with (root/'receipt.json').open('x', encoding='utf-8') as receipt:
        try:
            support.validate_interpreter()
            if (Path(support.INSTALL) != legacy.INSTALL or terminal.NATIVE != legacy.NATIVE
                    or support.digest_file(Path(win.__file__)) != support.WINDOWS_SHA256):
                raise ValueError('Installed attended runtime or launch custody changed')
            report['revision'] = support.verify_r4_runtime(win, support.INSTALL_RECEIPT_SHA256)
            report.update(runtime_root=str(legacy.INSTALL), install_receipt_sha256=support.INSTALL_RECEIPT_SHA256,
                          source_manifest_sha256=support.MANIFEST_SHA256, resource_limits_sha256=support.RESOURCE_SHA256)
            support.require_stopped(win)
            phase = 'layout'
            layout, layout_hash = support.protected_json(win, legacy.INSTALL/'windows-layout.json')
            config, config_hash = support.protected_json(win, legacy.INSTALL/'pipeline.json')
            if layout_hash != legacy.LAYOUT_SHA256 or config_hash != legacy.CONFIG_SHA256:
                raise ValueError('Attended layout/configuration binding changed')
            report.update(layout_sha256=layout_hash, config_sha256=config_hash)
            spec = layout['slots'][slot]
            identity = win.WorkerIdentity(spec['identity'], spec['credential_target'])
            sid = win._sid_text(win._account_sid(identity.name))
            if sid != spec['sid'] or Path(config['providers']['gemini']['executable']) != terminal.NATIVE:
                raise ValueError('Configured worker or Agy binding differs')
            phase = 'native_custody'
            ordinary_tree(terminal.NATIVE)
            win.validate_code_path(terminal.NATIVE)
            if support.digest_file(terminal.NATIVE) != legacy.AGY_SHA256:
                raise ValueError('The pinned Agy executable changed')
            report['native_executable_sha256'] = legacy.AGY_SHA256
            limits = resources.ResourceLimits.from_dict(config['execution_limits'])
            def output_ready(reader):
                thread = threading.Thread(target=legacy.pump, args=(reader, events, stopped), daemon=True)
                threads.append(thread)
                thread.start()
            phase = 'native_launch'
            session = terminal.launch_attended_agy(win, resources, identity, spec['root'], limits=limits,
                                                   output_ready=output_ready)
            report['login_commands_executed'] = 1
            report['process'] = support.observe_child(win, session, sid, terminal.NATIVE)
            phase = 'native_wait'
            with (root/'operator.log').open('xb', buffering=0) as log:
                output = TerminalOutput(legacy, log, report, terminal)
                try:
                    code = read_loop(legacy, terminal, session, events, output, root, nonce, win, report, channels)
                    # Native exit may leave a final frame queued. Preserve the
                    # before/after-input publication boundary while draining.
                    until = time.monotonic() + legacy.DRAIN_SECONDS
                    while time.monotonic() < until:
                        try:
                            data = events.get(timeout=.05)
                        except queue.Empty:
                            if not threads[0].is_alive():
                                break
                            continue
                        if data:
                            output.accept(data, report['one_line_submitted'])
                finally:
                    output.finish()
            phase = 'native_result'
            report['native_exit_code'] = code
            report['token_storage_observed'] = legacy.observe_token_storage(win, session)
            report['status'] = legacy.terminal_status(code, report)
            after = support.digest_file(terminal.NATIVE)
            report['native_executable_sha256_after'] = after
            if after != legacy.AGY_SHA256:
                raise ValueError('The native executable changed during sign-in')
        except BaseException as error:
            failed_console = getattr(error, 'console', None)
            failed_worker_clean = getattr(error, 'worker_cleanup_verified', False)
            failed_reservation = getattr(error, 'reservation', None)
            if getattr(error, 'native_command_started', False):
                report['login_commands_executed'] = 1
            report['status'] = legacy.STATUS_FAILED_OR_CANCELLED
            report['failure'] = support.safe_failure(error, phase)
        finally:
            def discard_frame():
                try:
                    events.get(timeout=.02)
                except queue.Empty:
                    pass
            try:
                if session is not None:
                    session.close(discard_frame)
                    report['cleanup_verified'] = session.cleanup_verified
                    report['terminal_cleanup_verified'] = session.cleanup_verified
                elif failed_console is not None:
                    if not failed_worker_clean:
                        raise terminal.TerminalCleanupError('Failed worker cleanup is unverified')
                    failed_console.close(discard_frame)
                    failed_console.writer.close()
                    win._close(failed_reservation)
                    report['cleanup_verified'] = report['terminal_cleanup_verified'] = True
                # Drain while the output pump is alive, before setting its stop
                # event; otherwise a full queue can deadlock terminal close.
                until = time.monotonic() + 3
                while any(thread.is_alive() for thread in threads) and time.monotonic() < until:
                    discard_frame()
                stopped.set()
                for thread in threads:
                    thread.join(timeout=1)
                if any(thread.is_alive() for thread in threads):
                    raise terminal.TerminalCleanupError('The terminal output pump did not end')
                if report['cleanup_verified']:
                    support.require_stopped(win)
                    for channel in channels:
                        channel.delete_after_verified_cleanup()
                    report['input_file_deleted'] = bool(channels)
            except BaseException as error:
                report['status'] = legacy.STATUS_CLEANUP_UNVERIFIED
                report['cleanup_verified'] = False
                report['failure'] = support.safe_failure(error, 'native_cleanup')
            for channel in channels:
                channel.close()
            legacy.close_input_window(root, nonce, report) if not report['input_closed_marker_written'] else None
            report['finished_at_unix_ms'] = int(time.time()*1000)
            json.dump(report, receipt, sort_keys=True, indent=2)
            receipt.flush()
            os.fsync(receipt.fileno())
    return 0 if report['status'] in legacy.ACCEPTED_STATUSES and report['cleanup_verified'] else 2


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('Invalid terminal bridge arguments')


def main(argv=None):
    parser = _Parser(add_help=False)
    parser.add_argument('--slot', required=True)
    parser.add_argument('--nonce', required=True)
    try:
        args = parser.parse_args(argv)
        session_root(args.slot, args.nonce)
        return run(args.slot, args.nonce)
    except BaseException as error:
        print(json.dumps({'status': 'PRE_RECEIPT_FAILURE', 'error_type': type(error).__name__}), file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
