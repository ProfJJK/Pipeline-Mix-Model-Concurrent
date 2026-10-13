"""Owner-staged SYSTEM broker: six sequential Agy profile sign-ins, no inference.

This is account maintenance, independent of deployment. It does not stop or
start a daemon, open a pipeline database, reserve a compute job or change the
four-slot configuration. Every native operation obtains the installed worker's
exclusive profile reservation; a busy profile holds the batch. At most one
small authentication Job exists (512 MiB, 5% CPU, four child processes, E cores).
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import tempfile
import threading
import time
import traceback

PARENT = Path(r'C:\Program Files\CoChem')
PREFIX = 'AgySignIn427-'
SLOTS = tuple(f'slot{i}' for i in range(1, 7))
STATUS_ARGS = ['--output-format', 'json', 'models']
SIGN_OUT = frozenset({
    'Please sign in to view available models. Launch the CLI without arguments to sign in.',
    'Error: Please sign in to view available models. Launch the CLI without arguments to sign in.',
    'You are not logged into Antigravity.',
})
FETCHING = 'Fetching available models...'


def failure_metadata(error):
    # Source positions identify a failed check without leaking exception text,
    # provider output, accounts, URLs or codes.
    frames = traceback.extract_tb(error.__traceback__)[-6:]
    chain=[]
    current=error
    while current is not None and len(chain)<6:
        chain.append(dict(error_type=type(current).__name__,winerror=getattr(current,'winerror',None)))
        current=current.__cause__
    return dict(error_type=type(error).__name__, winerror=getattr(error, 'winerror', None), causes=chain,
        frames=[dict(file=Path(frame.filename).name, line=frame.lineno, function=frame.name) for frame in frames])


def classify_status(stdout, stderr, code):
    """Closed protocol for this fixed catalog command, never a model response."""
    if not isinstance(stdout, bytes) or not isinstance(stderr, bytes) or len(stdout)+len(stderr) > 65536:
        raise ValueError('Unbounded catalog output')
    out, err = stdout.decode('utf-8', 'replace'), stderr.decode('utf-8', 'replace')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate catalog key')
            result[key] = value
        return result
    try:
        envelope = json.loads(out, object_pairs_hook=pairs)
    except (ValueError, RecursionError):
        envelope = None
    command = envelope.get('command') if isinstance(envelope, dict) else None
    data = command.get('data') if isinstance(command, dict) else None
    models = data.get('models') if isinstance(data, dict) else None
    verified = (code == 0 and envelope is not None and envelope.get('status') == 'SUCCESS'
        and isinstance(command, dict) and command.get('name') == 'models'
        and isinstance(models, list) and bool(models)
        and all(isinstance(row, dict) and isinstance(row.get('id'), str) and isinstance(row.get('label'), str) for row in models)
        and any(row['id'].startswith('gemini-') for row in models)
        and all(line.strip() == FETCHING for line in err.splitlines() if line.strip()))
    lines = [line.strip() for text in (out, err) for line in text.splitlines() if line.strip()]
    logout = (code != 0 and bool(lines) and any(line in SIGN_OUT for line in lines)
              and all(line in SIGN_OUT or line == FETCHING for line in lines))
    return dict(authenticated=bool(verified), decision='VERIFIED' if verified else 'LOGIN_REQUIRED' if logout else 'UNKNOWN',
        exit_code=code, stdout_bytes=len(stdout), stderr_bytes=len(stderr),
        stdout_sha256=hashlib.sha256(stdout).hexdigest(), stderr_sha256=hashlib.sha256(stderr).hexdigest())


def write_new(path, value):
    # Publish only after the entire JSON is durable; readers never see a prefix.
    if path.exists():
        raise FileExistsError('Preserve an existing sign-in record')
    raw = json.dumps(value, sort_keys=True, indent=2).encode('utf-8')
    temporary = path.with_name(path.name+'.writing')
    with temporary.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.rename(path)  # Windows refuses an existing destination.


def status_probe(win, support, identity, spec, limits, native, root, stage):
    with tempfile.TemporaryFile('w+b', dir=root) as inp, tempfile.TemporaryFile('w+b', dir=root) as out, \
            tempfile.TemporaryFile('w+b', dir=root) as err:
        process = win.launch_worker(identity, [str(native), *STATUS_ARGS], spec['root'], inp, out, err, limits=limits)
        try:
            proof = support.observe_child(win, process, spec['sid'], native)
            until = time.monotonic()+30
            while process.poll() is None:
                if os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size > 65536:
                    raise ValueError('Catalog output exceeded its bound')
                if time.monotonic() >= until:
                    raise TimeoutError('Catalog status deadline expired')
                time.sleep(.1)
            code = process.poll()
        finally:
            process.close()  # Empty Job proof, profile unload, then identity release.
        out.seek(0); err.seek(0)
        stdout, stderr = out.read(65537), err.read(65537)
    result = classify_status(stdout, stderr, code)
    result.update(cleanup_verified=True, process=proof)
    if result['decision'] == 'UNKNOWN':
        # No account information is published; retain bounded unknown data privately.
        for name, raw in (('stdout', stdout), ('stderr', stderr)):
            with (root/f'{stage}-unknown.{name}').open('xb') as stream:
                stream.write(raw)
    write_new(root/f'{stage}-status.json', result)
    return result


def login_one(win, resources, support, legacy, terminal, bridge, identity, spec, root, nonce, deadline, limits):
    report = legacy.new_report(root.name, nonce, 'tui', win, support.digest_file(Path(__file__)))
    report.update(schema='cochem-agy-profile-terminal/1', slot=root.name, login_mode='terminal',
        code_write_completed=False, terminal_cleanup_verified=False, terminal_hold_reason=None,
        native_google_start_key_sent=False, terminal_query_replies=0)
    session = None
    failed_console = failed_reservation = None
    failed_worker_clean = False
    threads, channels = [], []
    stopped, events = threading.Event(), queue.Queue(maxsize=32)
    phase = 'terminal_launch'
    def ready(reader):
        thread = threading.Thread(target=legacy.pump, args=(reader, events, stopped), daemon=True)
        threads.append(thread); thread.start()
    try:
        if time.time() >= deadline:
            raise TimeoutError('Input window expired before login')
        # The same installed SID reservation used by normal jobs prevents a
        # live worker and account maintenance from accessing this profile together.
        session = terminal.launch_attended_agy(win, resources, identity, spec['root'], limits=limits, output_ready=ready)
        report['login_commands_executed'] = 1
        report['process'] = support.observe_child(win, session, spec['sid'], terminal.NATIVE)
        phase = 'terminal_input'
        legacy.LOGIN_SECONDS = min(600, max(1, deadline-time.time()))
        with (root/'operator.log').open('xb', buffering=0) as log:
            def prompt_ready(url):
                write_new(root/'prompt-ready.json', dict(schema='cochem-agy-code-prompt/1',
                    nonce=nonce, slot=root.name, url=url))
            output = bridge.TerminalOutput(legacy, log, report, terminal, on_prompt=prompt_ready)
            try:
                code = bridge.read_loop(legacy, terminal, session, events, output, root, nonce, win, report, channels)
            finally:
                output.finish()
        report['native_exit_code'] = code
        report['status'] = legacy.terminal_status(code, report)
    except BaseException as error:
        failed_console = getattr(error, 'console', None)
        failed_worker_clean = getattr(error, 'worker_cleanup_verified', False)
        failed_reservation = getattr(error, 'reservation', None)
        report['status'] = 'LOGIN_FAILED_OR_CANCELLED'
        report['failure'] = dict(phase=phase, **failure_metadata(error))
    finally:
        def drain():
            try:
                events.get(timeout=.02)
            except queue.Empty:
                pass
        try:
            if session is not None:
                session.close(drain)
                report['cleanup_verified'] = report['terminal_cleanup_verified'] = session.cleanup_verified
            elif failed_console is not None:
                if not failed_worker_clean:
                    raise terminal.TerminalCleanupError('Worker cleanup is unverified')
                failed_console.close(drain); failed_console.writer.close(); win._close(failed_reservation)
                report['cleanup_verified'] = report['terminal_cleanup_verified'] = True
            until = time.monotonic()+3
            while any(t.is_alive() for t in threads) and time.monotonic() < until:
                drain()
            stopped.set()
            for thread in threads:
                thread.join(timeout=1)
            if any(t.is_alive() for t in threads):
                raise terminal.TerminalCleanupError('Terminal reader did not end')
            if report['cleanup_verified']:
                for channel in channels:
                    channel.delete_after_verified_cleanup()
                report['input_file_deleted'] = bool(channels)
                # A packet can arrive between native exit and input.closed.
                # After proved cleanup remove that unread private packet as well.
                late = root/'input.once'
                if late.exists():
                    channel = legacy.ChannelFile(late, win)
                    try:
                        legacy.parse_packet(channel.raw, nonce)
                        channel.delete_after_verified_cleanup()
                    finally:
                        channel.close()
        except BaseException as error:
            report['status'] = 'LOGIN_CLEANUP_UNVERIFIED'
            report['cleanup_verified'] = False
            report['failure'] = dict(phase='terminal_cleanup', **failure_metadata(error))
        for channel in channels:
            channel.close()
        if not report['input_closed_marker_written']:
            legacy.close_input_window(root, nonce, report)
        report['finished_at_unix_ms'] = int(time.time()*1000)
        write_new(root/'login.json', report)
    return report


def sequence(root, nonce, deadline, status, login):
    """Small dependency-injected state machine: status/login/status, sequential."""
    rows = []
    for slot in SLOTS:
        row = dict(slot=slot, authenticated=False, cleanup_verified=False, login_requested=False)
        child = root/slot
        try:
            if (root/'cancel.request').exists():
                raise InterruptedError('Owner cancelled the batch')
            before = status(slot, child, 'before')
            row['before'] = before
            if before['decision'] == 'VERIFIED':
                row.update(authenticated=True, cleanup_verified=True, status='REUSED_SESSION')
            elif before['decision'] == 'LOGIN_REQUIRED':
                if (root/'cancel.request').exists():
                    raise InterruptedError('Owner cancelled the batch')
                if time.time() >= deadline:
                    raise TimeoutError('No new prompt after input deadline')
                write_new(child/'login-required.json', dict(slot=slot, nonce=nonce, decision='LOGIN_REQUIRED'))
                row['login_requested'] = True
                result = login(slot, child)
                row['login'] = {key: result.get(key) for key in ('status','native_exit_code',
                    'one_line_submitted','code_write_completed','input_file_deleted',
                    'terminal_cleanup_verified','native_google_start_key_sent','terminal_query_replies',
                    'native_output_bytes_before_input','pause_marker_seen','native_markers')}
                row['cleanup_verified'] = result['cleanup_verified']
                if not (result['cleanup_verified'] and result.get('terminal_cleanup_verified')
                        and result.get('one_line_submitted') and result.get('code_write_completed')
                        and result.get('input_file_deleted') and not result.get('pause_marker_seen')
                        and result['status'] in ('LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED', 'LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED')):
                    row['login_failure'] = result.get('failure')
                    row['reason'] = result.get('terminal_hold_reason')
                    raise ValueError('Native login did not complete')
                if (root/'cancel.request').exists():
                    raise InterruptedError('Owner cancelled the batch')
                after = status(slot, child, 'after')
                row['after'] = after
                if after['decision'] != 'VERIFIED':
                    raise ValueError('Native catalog did not verify sign-in')
                row.update(authenticated=True, cleanup_verified=True, status='SIGNED_IN_AND_VERIFIED')
            else:
                raise ValueError('Catalog status is unknown; do not request login')
        except BaseException as error:
            row.update(status='HELD', **failure_metadata(error))
        write_new(child/'result.json', row)
        rows.append(row)
        if not row['authenticated']:
            break  # No automatic retry and no later profile after a failure.
    return rows


def run(nonce, deadline):
    if not re.fullmatch('[a-f0-9]{32}', nonce) or nonce == '0'*32 or not time.time() < deadline <= time.time()+1200:
        raise ValueError('Invalid fresh session or input deadline')
    root = PARENT/(PREFIX+nonce)
    if Path(__file__).resolve() != root/'worker_agy_signin_batch.py':
        raise ValueError('Use only the protected staged broker')
    from cochem_pipeline import windows as win, resource_limits as resources
    win.require_system()
    win.validate_private_directory(root)
    # The owner manifest bound these five create-only copies before task Run.
    # Repeat the exact module hashes in SYSTEM before importing any helper.
    controls = json.loads((root/'helpers.json').read_text('utf-8-sig'))
    from importlib.util import module_from_spec, spec_from_file_location
    loaded = {}
    for name in ('worker_agy_terminal_bridge.py','worker_agy_login_bridge_r4_v1.py','worker_native_status_support.py','attended_agy_terminal.py'):
        path = root/name
        win.validate_code_path(path)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != controls[name]:
            raise ValueError('Protected helper bytes differ')
        module = module_from_spec(spec_from_file_location('signin_'+path.stem, path))
        exec(compile(raw, str(path), 'exec'), module.__dict__)
        loaded[name] = module
    bridge, legacy, support, terminal = (loaded[name] for name in (
        'worker_agy_terminal_bridge.py','worker_agy_login_bridge_r4_v1.py','worker_native_status_support.py','attended_agy_terminal.py'))
    support.validate_interpreter()
    if support.digest_file(Path(win.__file__)) != support.WINDOWS_SHA256:
        raise ValueError('Installed launch support differs')
    revision = support.verify_r4_runtime(win, support.INSTALL_RECEIPT_SHA256)
    layout, lh = support.protected_json(win, support.INSTALL/'windows-layout.json')
    config, ch = support.protected_json(win, support.INSTALL/'pipeline.json')
    if lh != support.LAYOUT_SHA256 or ch != support.CONFIG_SHA256 or set(layout['slots']) != set(SLOTS):
        raise ValueError('Six isolated profile bindings differ')
    if support.digest_file(terminal.NATIVE) != legacy.AGY_SHA256:
        raise ValueError('Native executable differs')
    win.validate_code_path(terminal.NATIVE)
    limits = resources.ResourceLimits(memory_limit_mb=512, cpu_rate_percent=5, max_processes=4, node_heap_mb=128)
    identities = {}
    for slot in SLOTS:
        spec = layout['slots'][slot]
        identity = win.WorkerIdentity(spec['identity'], spec['credential_target'])
        if (win._sid_text(win._account_sid(identity.name)) != spec['sid']
                or identity.name != config['workers'][slot]['name']
                or identity.credential_target != config['workers'][slot]['credential_target']
                or spec['root'] != config['slot_roots'][slot]):
            raise ValueError('Profile SID or mapping differs')
        win.validate_private_directory(root/slot)
        identities[slot] = identity
    C.set_last_error(0)
    lock = win._api()['kernel32'].CreateMutexW(None, False, 'Global\\CoChem427-AgySignInBroker')
    win._check(lock, 'Reserve single authentication broker')
    if C.get_last_error() == 183:
        win._close(lock)
        raise ValueError('Another authentication broker is active')
    try:
        write_new(root/'started.json', dict(schema='cochem-agy-signin-started/1', nonce=nonce, system_sid=win.SYSTEM_SID,
            revision=revision, limits=limits.as_dict()))
        rows = sequence(root, nonce, deadline,
            lambda slot, child, stage: status_probe(win, support, identities[slot], layout['slots'][slot], limits, terminal.NATIVE, child, stage),
            lambda slot, child: login_one(win, resources, support, legacy, terminal, bridge,
                identities[slot], layout['slots'][slot], child, nonce, deadline, limits))
        verified = len(rows) == 6 and all(row['authenticated'] and row['cleanup_verified'] for row in rows)
        write_new(root/'result.json', dict(schema='cochem-agy-signin-batch/1', nonce=nonce,
            status='ALL_SIX_AGY_PROFILES_VERIFIED' if verified else 'HELD', checks=rows,
            helper_sha256=support.digest_file(Path(__file__)), system_sid=win.SYSTEM_SID,
            native_model_jobs_executed=0, daemon_tasks_changed=False, credentials_copied=False, activation_ready=False))
        return 0 if verified else 2
    finally:
        win._close(lock)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--nonce', required=True)
    parser.add_argument('--deadline', required=True, type=float)
    args = parser.parse_args()
    try:
        return run(args.nonce, args.deadline)
    except BaseException as error:
        # Fixed failure metadata only, directly available to the owner's wrapper.
        record = dict(schema='cochem-agy-signin-batch/1', nonce=args.nonce, status='HELD',
            phase='broker_setup', **failure_metadata(error),
            native_model_jobs_executed=0, activation_ready=False)
        if re.fullmatch('[a-f0-9]{32}', args.nonce):
            root = PARENT/(PREFIX+args.nonce)
            if Path(__file__).resolve() == root/'worker_agy_signin_batch.py' and not (root/'result.json').exists():
                write_new(root/'result.json', record)
        print(json.dumps(record))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
