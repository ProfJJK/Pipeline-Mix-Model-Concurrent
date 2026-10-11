"""Slot1 discovery capture of agy 1.3.1 under the worker token (build-manifest step 2).

Standalone artifact copied by agy-status-capture-r4-v1.ps1 into a fresh SYSTEM/BA-only root
C:\\Program Files\\CoChem\\AgyCapture4.2.7-windows-20261010-r4-v1-<attempt>-slot1-<stage> and run
once by a one-shot SYSTEM task under the pinned r4 interpreter (-I -B). Never import it from
the checkout for a real run. Derived from worker-native-auth-status-six-r3-v3.py (sha256
7efa8d27...: strict_json, digest_file, protected_json, require_stopped, observe_child,
bounded_wait, safe_failure, validate_interpreter, run skeleton) and the stdin pipe pattern of
worker_claude_login_bridge_r3.py (sha256 b5bbede8...).

Each probe is one launch_worker call (cwd = slot root, Job limits from execution_limits,
stdout/stderr to private files under <root>\\raw, 30 s, 64 KiB combined). P3/P6 in the
signed-out stage get a stdin PIPE that is held open for a 20 s window and is NEVER written;
the process is then ended through its owned Job (process.close). Raw output stays in the
SYSTEM/BA root (it may hold the account email once signed in); the receipt carries only
byte counts, sha256 digests and allowlisted classifications (URL hosts only, never a path or
query). No model inference, login input, credential read or token-file open ever occurs.
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
from urllib.parse import urlsplit

COCHEM = Path(r'C:\Program Files\CoChem')
CAPTURE_BASE = COCHEM
INSTALL = COCHEM / 'Pipeline4.2.7-windows-20261009-r4'
PREVIOUS_INSTALL = COCHEM / 'Pipeline4.2.7-windows-20261007-r3'
NATIVE = COCHEM / 'Native4.2.7-windows-20261006'
EXECUTABLE = NATIVE / 'agy.exe'
PYTHON = INSTALL / '.venv' / 'Scripts' / 'python.exe'
BASE_PYTHON = COCHEM / 'Toolchain4.2.7-windows-20261006' / 'Python312' / 'python.exe'
PROFILE_PARENT = Path(r'C:\Users')
HELPER_NAME = 'agy_status_capture_r4_v1.py'
ROOT_PREFIX = 'AgyCapture4.2.7-windows-20261010-r4-v1-'

INSTALL_RECEIPT_SHA256 = '629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502'
MANIFEST_SHA256 = '1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189'
REVISION_SHA256 = '38a99c3fc160558c9f170b5da0b28d815f2172e7338b6849f993fdc57e9abb5e'
WINDOWS_SHA256 = 'ca07b3bba2b22d0eb095c1f05b9a6c0969207bf7d8b25741adbaee184f4618ba'
RESOURCE_SHA256 = 'de7fac91e32cef2f854bd53487037352bbc0915f95aaf987ee8a4a543317915f'
CONFIG_SHA256 = '135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
LAYOUT_SHA256 = '8430fdf1109c63c4a89479f03da8a465dfebf5566c7791c64f868202170672c4'
PYTHON_SHA256 = '560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'
VENV_CONFIG_SHA256 = '0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d'
BASE_PYTHON_SHA256 = 'd8e3f0adf246db00358c0c4ed349cf714898178f9558fb0e944f79f5c07f8eaa'
REPAIR_RELATIVE = 'src/cochem_pipeline/resource_telemetry.py'
REPAIR_SHA256 = 'e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc'
PREVIOUS_INSTALL_RECEIPT_SHA256 = '3b613128192ac44a0a3d9c4b4476fb4c47541edb7563541b9bbf18f84f9a90f6'
PREVIOUS_MANIFEST_SHA256 = '6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1'
PRESERVED_DENIAL_SHA256 = '691c70560436f948464c529b9d2d6a3e33ce240749642af86ca79c748791461d'
AGY_SHA256 = '38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741'
AGY_VERSION = '1.3.1'

SLOTS = ('slot1',)
STAGES = ('signed-out', 'signed-in')
DAEMON_TASK_NAMES = ('CoChem-4.2.7-Warden', 'CoChem-4.2.7-Supervisor',
                     'CoChem-4.2.2-Warden', 'CoChem-4.2.3-Supervisor')
PROBE_SECONDS = 30
WINDOW_SECONDS = 20
MAX_OUTPUT = 65536
POLL_SECONDS = 0.05
RAW_FILE_MAXIMUM = 16 * 1024 * 1024
# The task runs under ExecutionTimeLimit PT5M. A probe starts only while its worst case (bound
# plus the Job close/unload allowance) still fits before this helper deadline, so the receipt is
# always written; a skipped probe makes the capture CAPTURE_INCOMPLETE (a verification failure).
CAPTURE_DEADLINE_SECONDS = 250
PROBE_CLEANUP_MARGIN_SECONDS = 25
INVENTORY_HASH_LIMIT = 1024 * 1024
MAX_TREE_ENTRIES = 400
MAX_TREE_DEPTH = 16
RECEIPT_MAX_BYTES = 1024 * 1024
INVENTORY_TREES = (('.gemini', ('.gemini',)), ('AppData/Local/agy', ('AppData', 'Local', 'agy')))

# Probe table (manifest step 2). The executable is always argv[0]; argument lists are literal.
PROBES = {
    'P1': {'arguments': ('--version',), 'kind': 'version'},
    'P2': {'arguments': ('--output-format', 'json', 'models'), 'kind': 'models_json'},
    'P2b': {'arguments': ('models',), 'kind': 'models_text'},
    'P3': {'arguments': ('-p', '/model'), 'kind': 'print_model'},
    'P4': {'arguments': ('-p', '/usage'), 'kind': 'print_text'},
    'P5': {'arguments': ('--output-format', 'json', '-p', '/usage'), 'kind': 'print_json'},
    'P6': {'arguments': (), 'kind': 'bare'},
    'P7': {'arguments': ('--output-format', 'json', 'agents'), 'kind': 'agents_json'},
    'P8': {'arguments': ('agents',), 'kind': 'agents_text'},
}
EMPTY, PIPE = 'empty_file', 'held_open_pipe'
STAGE_PROBES = {
    'signed-out': (('P1', EMPTY), ('P2', EMPTY), ('P2b', EMPTY), ('P3', PIPE), ('P4', EMPTY),
                   ('P5', EMPTY), ('P6', PIPE), ('P7', EMPTY), ('P8', EMPTY)),
    'signed-in': (('P1', EMPTY), ('P2', EMPTY), ('P2b', EMPTY), ('P7', EMPTY), ('P8', EMPTY),
                  ('P3', EMPTY), ('P4', EMPTY), ('P5', EMPTY)),
}
OUTCOMES = ('exited', 'timed_out_terminated', 'window_elapsed_terminated', 'output_bound_terminated')

# Allowlisted exact strings (binary strings and captures cited in the build manifest).
SIGN_IN_LINE = 'Please sign in to view available models. Launch the CLI without arguments to sign in.'
SIGN_IN_PREDICATE_TEXT = 'Please sign in to view available models'
AUTH_REQUIRED_TEXT = 'authentication required'
NOT_LOGGED_IN_LINE = 'You are not logged into Antigravity.'
NO_CONTROLLING_TERMINAL_TEXT = 'no controlling terminal'
WAITING_TEXT = 'Waiting for authentication'
FETCHING_LINE = 'Fetching available models...'
EXACT_LINE_FALLBACK = 'gemini-3.8-flash-high\tGemini 3.8 Flash (High)'
PASTE_PROMPT_PATTERN = re.compile(r'(?i)(paste|enter) the authorization code|Enter the redirect URL')
URL_PATTERN = re.compile(r'https://[^ ]+')
SIGN_IN_URL_HOST = 'accounts.google.com'  # the only URL host that counts as sign-in evidence for the login mode
ANSI_PATTERN = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]')
HOST_PATTERN = re.compile(r'[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*')
SLUG_PATTERN = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}')
MODEL_ROW_PATTERN = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}\t[^\t\r\n]{1,128}')
AGENT_NAME_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')
ENVELOPE_KEY_PATTERN = re.compile(r'[a-z_]{1,40}')
STATUS_VALUES = ('SUCCESS', 'ERROR', 'CANCELED', 'INTERRUPTED', 'INVALID', 'WAITING', 'RUNNING')
COMMAND_NAMES = ('models', 'agents')
MAX_HOSTS = 8
MAX_LISTED = 64
FAILURE_PHASES = ('trusted_preflight', 'reservation', 'runtime_custody', 'layout', 'boundaries',
                  'native_custody', 'daemon_precheck', 'inventory_before', 'native_launch',
                  'native_attestation', 'native_wait', 'native_cleanup', 'native_result',
                  'inventory_after', 'daemon_postcheck', 'login_mode')
REASONS = ('CAPTURE_NOT_COMPLETE', 'P2_NOT_RUN', 'P2_NOT_COMPLETED_WITHIN_BOUND',
           'P2_NOT_LOGGED_OUT_UNDER_STATUS_PREDICATE', 'LOGIN_MODE_NONE', 'P2_EXIT_NOT_ZERO',
           'P2_STATUS_NOT_SUCCESS', 'P2_COMMAND_NOT_MODELS', 'P2_NO_GEMINI_ROW')


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON field')
            result[key] = value
        return result
    def reject_constant(_):
        raise ValueError('Nonfinite JSON value')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)


def digest_file(path, maximum=1024 * 1024 * 1024):
    before = path.stat()
    if before.st_size > maximum:
        raise ValueError('Reviewed file exceeds its size bound')
    digest = hashlib.sha256()
    count = 0
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            count += len(chunk)
            if count > maximum:
                raise ValueError('Reviewed file grew beyond its size bound')
            digest.update(chunk)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('Reviewed file changed during hash capture')
    return digest.hexdigest()


def protected_json(win, path):
    win.validate_code_path(path)
    from cochem_pipeline.ramdisk import ordinary_tree
    ordinary_tree(path)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('Protected configuration exceeds its byte bound')
    raw = path.read_bytes()
    if len(raw) > 1024 * 1024:
        raise ValueError('Protected configuration exceeds its byte bound')
    value = strict_json(raw.decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('Protected configuration requires an object')
    return value, hashlib.sha256(raw).hexdigest()


def current_executable():
    return Path(sys.executable).resolve()


def validate_interpreter():
    if (current_executable() != PYTHON or Path(sys.base_prefix).resolve() != BASE_PYTHON.parent
            or Path(sys._base_executable).resolve() != BASE_PYTHON
            or sys.version_info[:3] != (3, 12, 13) or not sys.flags.isolated or not sys.dont_write_bytecode
            or digest_file(INSTALL / '.venv' / 'pyvenv.cfg') != VENV_CONFIG_SHA256):
        raise ValueError('Protected isolated interpreter binding changed')


def verify_r4_source(value, read):
    if (value.get('schema') != 'cochem-stopped-runtime-source/1' or value.get('target_root') != str(INSTALL)
            or value.get('complete_source_freeze') is not True or not isinstance(value.get('files'), list)
            or len(value['files']) != 166
            or value.get('changes_from_previous_source') != {'added': [], 'removed': [], 'changed': [REPAIR_RELATIVE]}):
        raise ValueError('Frozen r4 source inventory differs')
    seen = set()
    for row in value['files']:
        key = row.get('relative')
        if (not isinstance(key, str) or '\\' in key or ':' in key or key.startswith('/')
                or any(part in ('', '.', '..') for part in key.split('/')) or key.casefold() in seen
                or not (key.startswith('src/') or key in ('README.md', 'pyproject.toml', 'uv.lock'))
                or not re.fullmatch('[a-f0-9]{64}', str(row.get('sha256')))
                or type(row.get('length')) is not int or not 0 <= row['length'] <= 16777216):
            raise ValueError('Unsafe frozen r4 source record')
        if key == REPAIR_RELATIVE and row['sha256'] != REPAIR_SHA256:
            raise ValueError('Frozen r4 repair differs from its pin')
        seen.add(key.casefold())
        read(INSTALL / 'source' / key, row['sha256'], row['length'])
    if not {'pyproject.toml', 'uv.lock', 'readme.md', REPAIR_RELATIVE} <= seen:
        raise ValueError('Project controls missing from r4 manifest')


def verified_source(win, path, pin, length):
    win.validate_code_path(path)
    if path.stat().st_size != length or digest_file(path) != pin:
        raise ValueError('Frozen source bytes differ')


def check_install_after(installed):
    """The r4 install-after.json bindings, with the real key names printed on disk."""
    expected = {'schema': 'cochem-stopped-runtime-update/1', 'mode': 'FRESH_STOPPED_RUNTIME_READY',
                'target_root': str(INSTALL), 'previous_runtime_root': str(PREVIOUS_INSTALL),
                'previous_install_receipt_sha256': PREVIOUS_INSTALL_RECEIPT_SHA256,
                'previous_source_manifest_sha256': PREVIOUS_MANIFEST_SHA256,
                'source_manifest_sha256': MANIFEST_SHA256, 'source_files': 166,
                'reviewed_repair': REPAIR_RELATIVE, 'reviewed_repair_sha256': REPAIR_SHA256,
                'configuration_sha256': CONFIG_SHA256, 'configuration_unchanged': True, 'only_config_change': None,
                'preserved_denial_receipt_sha256': PRESERVED_DENIAL_SHA256,
                'preserved_denial_task_terminal_check_deferred': False, 'preserved_worker_cleanup_verified': False,
                'accounts_provisioned': 0, 'tasks_changed': 0, 'credentials_modified': False,
                'databases_modified': False, 'ram_modified': False, 'pipeline_started': False,
                'activation_ready': False}
    if any(type(installed.get(k)) is not type(v) or installed.get(k) != v for k, v in expected.items()) or installed.get('holds') != []:
        raise ValueError('Complete stopped r4 installation binding missing')
    verification = installed.get('verification')
    bindings = installed.get('runtime_bindings')
    if (not isinstance(verification, dict) or verification.get('configuration_parsed') is not True
            or verification.get('telemetry_repair_installed') is not True
            or verification.get('no_system_or_model_execution') is not True
            or not isinstance(bindings, dict) or bindings.get('pyvenv_sha256') != VENV_CONFIG_SHA256
            or bindings.get('venv_python_sha256') != PYTHON_SHA256 or bindings.get('base_python_sha256') != BASE_PYTHON_SHA256
            or bindings.get('base_root') != str(BASE_PYTHON.parent)
            or not isinstance(verification.get('revision'), dict)
            or verification['revision'].get('source_sha256') != REVISION_SHA256):
        raise ValueError('r4 verification/runtime binding differs')
    return verification


def verify_r4_runtime(win, install_receipt_sha256=INSTALL_RECEIPT_SHA256):
    """Bind the reviewed r4 stopped runtime before comparing the installed package revision."""
    from cochem_pipeline.deployment_revision import verify_installed_revision
    from cochem_pipeline import resource_limits
    for pin in (RESOURCE_SHA256, MANIFEST_SHA256, install_receipt_sha256, VENV_CONFIG_SHA256, REVISION_SHA256, REPAIR_SHA256):
        if not re.fullmatch('[a-f0-9]{64}', pin):
            raise ValueError('Actual reviewed r4 bindings are not frozen')
    if (Path(sys.base_prefix).resolve() != BASE_PYTHON.parent or Path(sys._base_executable).resolve() != BASE_PYTHON
            or sys.version_info[:3] != (3, 12, 13) or not sys.flags.isolated or not sys.dont_write_bytecode):
        raise ValueError('Exact isolated protected Python binding differs')
    site = INSTALL / '.venv' / 'Lib' / 'site-packages'
    for path, pin in ((PYTHON, PYTHON_SHA256), (INSTALL / '.venv' / 'pyvenv.cfg', VENV_CONFIG_SHA256),
                      (Path(resource_limits.__file__), RESOURCE_SHA256), (BASE_PYTHON, BASE_PYTHON_SHA256),
                      (site / 'cochem_pipeline' / 'resource_telemetry.py', REPAIR_SHA256)):
        win.validate_code_path(path)
        if digest_file(path) != pin:
            raise ValueError('Pinned r4 runtime control differs')
    installed, digest = protected_json(win, INSTALL / 'install-after.json')
    if digest != install_receipt_sha256:
        raise ValueError('Actual r4 receipt pin differs')
    verification = check_install_after(installed)
    manifest, digest = protected_json(win, INSTALL / 'source-manifest.json')
    if digest != MANIFEST_SHA256:
        raise ValueError('Frozen r4 manifest pin differs')
    verify_r4_source(manifest, lambda path, pin, length: verified_source(win, path, pin, length))
    revision = verify_installed_revision(INSTALL / 'source', site, INSTALL / 'source')
    if (revision.get('verified') is not True or revision.get('files') != 109
            or revision.get('source_sha256') != REVISION_SHA256
            or revision != verification.get('revision')):
        raise ValueError('Actual installed r4 revision differs from pinned receipt/source')
    return revision


def require_stopped(win):
    # Do not alter tasks, accept unknown scheduler errors, or inspect legacy tasks.
    win._powershell(r"""
        $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect();$folder=$scheduler.GetFolder('\');
        foreach ($name in $data) {
            $task=$null;
            try {$task=$folder.GetTask($name)} catch {
                $missing=$false;$exception=$_.Exception;
                while ($null -ne $exception) {if ($exception.HResult -eq -2147024894) {$missing=$true;break};$exception=$exception.InnerException}
                if (-not $missing) {throw 'Cannot establish task state.'}
            }
            if ($null -ne $task -and ($task.Enabled -or $task.State -notin @(1,3) -or $task.GetInstances(0).Count -ne 0)) {throw 'Protected daemons must remain stopped and disabled.'}
        }
    """, list(DAEMON_TASK_NAMES))


def launch_probe_process(win, identity, argv, cwd, stdin, output, errors, limits):
    # Recheck the four daemon task names at every launch boundary. No task is changed here.
    require_stopped(win)
    return win.launch_worker(identity, argv, cwd, stdin, output, errors, limits=limits)


def native_device_path(win, path):
    """NT device form of a local drive path (QueryDosDeviceW), used only after the child exited."""
    text = str(path)
    if not re.fullmatch(r'[A-Za-z]:\\.+', text):
        raise ValueError('Native executable path must be a local drive path')
    query = win._api()['kernel32'].QueryDosDeviceW
    query.argtypes = [win.LPWSTR, win.LPWSTR, win.DWORD]
    query.restype = win.DWORD
    buffer = C.create_unicode_buffer(1024)
    win._check(query(text[:2], buffer, 1024), 'Resolve executable drive device')
    return buffer.value + text[2:]


EXIT_SETTLE_MILLISECONDS = 5000


def observe_child(win, process, expected_sid, executable):
    """Observe the actual child token/image/job through the owned process handle.

    The r3-v3 body, plus one fallback: the Win32 image name of an EXITED process is not
    available (QueryFullProcessImageNameW fails with ERROR_GEN_FAILURE 31, verified on this
    host) and agy --version exits in about 0.07 s, so only after the process has exited the
    native (NT device) image name of the same owned handle is compared instead. While a fast
    child is tearing down, the same query fails with ERROR_ACCESS_DENIED 5 for about 0.4 ms
    before the handle is signaled (wave-1 verifier, reproduced on this host). For error 5 or 31
    the owned handle is therefore waited on for at most EXIT_SETTLE_MILLISECONDS: only a
    signaled handle with an exit code is compared in the native form; any other error, a
    timeout or a wait failure fails the attestation.
    """
    api = win._api()
    token = win.HANDLE()
    win._check(api['advapi32'].OpenProcessToken(process._process, 0x8, C.byref(token)), 'Open owned status-process token')
    try:
        user = win._SID_AND_ATTRIBUTES.from_buffer(win._token_info(token, 1))
        sid = win._sid_text(user.Sid)
        if sid != expected_sid or sid in {win.SYSTEM_SID, win.ADMIN_SID}:
            raise ValueError('Observed status process has the wrong identity')
        count = win.DWORD()
        api['userenv'].GetUserProfileDirectoryW(token, None, C.byref(count))
        if not 1 <= count.value <= 32768:
            raise ValueError('Observed profile path has an invalid bound')
        profile = C.create_unicode_buffer(count.value)
        win._check(api['userenv'].GetUserProfileDirectoryW(token, profile, C.byref(count)), 'Observe worker token profile')
        query = api['kernel32'].QueryFullProcessImageNameW
        query.argtypes = [win.HANDLE, win.DWORD, win.LPWSTR, C.POINTER(win.DWORD)]
        query.restype = win.BOOL
        size = win.DWORD(32768)
        image = C.create_unicode_buffer(size.value)
        if query(process._process, 0, image, C.byref(size)):
            if Path(image.value).resolve() != executable.resolve():
                raise ValueError('Observed status process image differs from the reviewed executable')
            image_format = 'win32'
        else:
            error = C.get_last_error()
            if error not in (5, 31):
                raise ValueError('Observe native process image failed')
            wait = api['kernel32'].WaitForSingleObject
            wait.argtypes = [win.HANDLE, win.DWORD]
            wait.restype = win.DWORD
            # WAIT_OBJECT_0 (0) only; WAIT_TIMEOUT 0x102 and WAIT_FAILED fail closed.
            if wait(process._process, EXIT_SETTLE_MILLISECONDS) != 0 or process.poll() is None:
                raise ValueError('Observe native process image failed')
            size = win.DWORD(32768)
            image = C.create_unicode_buffer(size.value)
            win._check(query(process._process, 1, image, C.byref(size)), 'Observe exited native process image')
            if image.value.casefold() != native_device_path(win, executable.resolve()).casefold():
                raise ValueError('Observed status process image differs from the reviewed executable')
            image_format = 'native_after_exit'
        in_job = win.BOOL()
        check_job = api['kernel32'].IsProcessInJob
        check_job.argtypes = [win.HANDLE, win.HANDLE, C.POINTER(win.BOOL)]
        check_job.restype = win.BOOL
        win._check(check_job(process._process, process._job, C.byref(in_job)), 'Observe owned Job membership')
        if not in_job.value:
            raise ValueError('Status process is not in its owned Job Object')
        return {'pid': process.pid, 'creation_time_filetime': process.creation_time_filetime,
                'token_sid': sid, 'token_matches_selected_worker': True,
                'image_matches_reviewed_executable': True, 'owned_job_membership_verified': True,
                'image_query_format': image_format,
                'profile_directory_sha256': hashlib.sha256(profile.value.casefold().encode()).hexdigest(),
                'source': 'owned_windows_process_handle_and_child_token'}
    finally:
        win._close(token)


def wait_probe(process, output, errors, seconds, window):
    """bounded_wait (r3-v3) that records instead of raising: the capture's purpose is evidence."""
    deadline = time.monotonic() + seconds
    while True:
        if os.fstat(output.fileno()).st_size + os.fstat(errors.fileno()).st_size > MAX_OUTPUT:
            return 'output_bound_terminated', None
        code = process.poll()
        if code is not None:
            return 'exited', code
        if time.monotonic() >= deadline:
            return ('window_elapsed_terminated' if window else 'timed_out_terminated'), None
        time.sleep(POLL_SECONDS)


def safe_failure(error, phase):
    kind = re.sub('[^A-Za-z0-9_]', '', type(error).__name__)[:80] or 'Exception'
    code, current = None, error
    for _ in range(5):
        value = getattr(current, 'winerror', None)
        if type(value) is int and 0 <= value <= 0xFFFFFFFF:
            code = value
            break
        current = current.__cause__ or current.__context__
        if current is None:
            break
    return {'phase': phase if phase in FAILURE_PHASES else 'trusted_preflight', 'error_type': kind, 'winerror': code}


# ----- classification (allowlisted fields only; raw text never leaves these functions) -----

def strip_ansi(text):
    return ANSI_PATTERN.sub('', text)


def url_hosts(text):
    """Hosts of https:// URLs; the path, query, fragment and userinfo are never returned."""
    hosts = []
    for line in text.splitlines():
        for match in URL_PATTERN.finditer(line):
            try:
                host = urlsplit(match.group(0)).hostname
            except ValueError:
                host = None
            if not isinstance(host, str) or len(host) > 253 or not HOST_PATTERN.fullmatch(host):
                host = 'unparsed'
            if host not in hosts and len(hosts) < MAX_HOSTS:
                hosts.append(host)
    return hosts


def allow(value, allowed):
    if not isinstance(value, str):
        return None
    return value if value in allowed else 'OTHER'


def parse_envelope(text):
    try:
        value = strict_json(text)
    except (ValueError, TypeError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def envelope_command(envelope):
    command = envelope.get('command') if isinstance(envelope, dict) else None
    return command if isinstance(command, dict) else None


def envelope_list(envelope, key):
    command = envelope_command(envelope)
    data = command.get('data') if command else None
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, list) else None


def success_models_envelope(envelope):
    """status SUCCESS, command.name models, non-empty {id,label} list with a gemini- id."""
    command = envelope_command(envelope)
    models = envelope_list(envelope, 'models')
    if envelope is None or envelope.get('status') != 'SUCCESS' or command is None or command.get('name') != 'models' or not models:
        return False
    if any(not isinstance(row, dict) or not isinstance(row.get('id'), str) or not isinstance(row.get('label'), str) for row in models):
        return False
    return any(row['id'].startswith('gemini-') for row in models)


def only_fetching_stderr(err):
    return all(line.strip() == FETCHING_LINE for line in err.splitlines() if line.strip())


def status_helper_predicate(stdout, stderr, exit_code, completed):
    """The r4 status helper's gemini predicate (build manifest step 3): LOGGED_IN | LOGGED_OUT | HOLD."""
    if not completed or type(exit_code) is not int or not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
        return 'HOLD'
    if len(stdout) + len(stderr) > MAX_OUTPUT:
        return 'HOLD'
    try:
        out, err = stdout.decode('utf-8', 'strict'), stderr.decode('utf-8', 'strict')
    except UnicodeError:
        return 'HOLD'
    envelope = parse_envelope(out)
    if exit_code == 0 and success_models_envelope(envelope) and only_fetching_stderr(err):
        return 'LOGGED_IN'
    text = out + '\n' + err
    if (exit_code != 0 or any(marker in text for marker in (SIGN_IN_PREDICATE_TEXT, AUTH_REQUIRED_TEXT, NOT_LOGGED_IN_LINE))
            or (envelope is not None and envelope.get('status') != 'SUCCESS')):
        return 'LOGGED_OUT'
    return 'HOLD'


def listed_names(values, pattern):
    names = [value for value in values if isinstance(value, str) and pattern.fullmatch(value)]
    return names[:MAX_LISTED], len(values) - len(names)


def classify(kind, stdout, stderr, outcome, exit_code, window):
    """Allowlisted booleans/enums/counts only. No raw line, URL path/query or account text."""
    oversize = len(stdout) + len(stderr) > MAX_OUTPUT
    try:
        out, err = stdout.decode('utf-8', 'strict'), stderr.decode('utf-8', 'strict')
        utf8 = True
    except UnicodeError:
        out, err = stdout.decode('utf-8', 'replace'), stderr.decode('utf-8', 'replace')
        utf8 = False
    text = strip_ansi(out + '\n' + err)
    hosts = url_hosts(text)
    result = {
        'timed_out': outcome == 'timed_out_terminated',
        'output_bound_exceeded': oversize or outcome == 'output_bound_terminated',
        'utf8_valid': utf8, 'stdout_empty': not stdout, 'stderr_empty': not stderr,
        'sign_in_line_present': SIGN_IN_LINE in text,
        'auth_required_present': AUTH_REQUIRED_TEXT in text,
        'not_logged_in_present': NOT_LOGGED_IN_LINE in text,
        'no_controlling_terminal_present': NO_CONTROLLING_TERMINAL_TEXT in text,
        'waiting_line_present': WAITING_TEXT in text,
        'paste_prompt_present': bool(PASTE_PROMPT_PATTERN.search(text)),
        'url_present': bool(hosts), 'url_hosts': hosts,
    }
    if window:
        result['window_seconds'] = WINDOW_SECONDS
        result['exited_before_window'] = outcome == 'exited'
        result['exit_code_before_window'] = exit_code if outcome == 'exited' else None
    usable = utf8 and not oversize
    lines = strip_ansi(out).splitlines() if usable else []
    if kind == 'version':
        result['version_matches'] = exit_code == 0 and usable and out.strip() == AGY_VERSION
        result['version_stdout_exact'] = stdout == (AGY_VERSION + '\n').encode()
    elif kind in ('models_json', 'agents_json', 'print_json'):
        envelope = parse_envelope(out) if usable else None
        command = envelope_command(envelope)
        result['json_envelope_parsed'] = envelope is not None
        result['status_value'] = allow(envelope.get('status'), STATUS_VALUES) if envelope else None
        result['command_name'] = allow(command.get('name'), COMMAND_NAMES) if command else None
        result['envelope_keys'] = sorted(key for key in envelope if ENVELOPE_KEY_PATTERN.fullmatch(key))[:20] if envelope else []
        if kind == 'models_json':
            models = envelope_list(envelope, 'models')
            ids = [row.get('id') for row in models if isinstance(row, dict)] if models is not None else []
            result['models_count'] = len(models) if models is not None else None
            result['gemini_row_present'] = any(isinstance(i, str) and i.startswith('gemini-') for i in ids)
            result['model_ids'], result['model_ids_unlisted'] = listed_names(ids, SLUG_PATTERN)
            result['stderr_only_fetching_line'] = usable and only_fetching_stderr(err)
            result['status_helper_classification'] = status_helper_predicate(stdout, stderr, exit_code, outcome == 'exited')
        elif kind == 'agents_json':
            agents = envelope_list(envelope, 'agents')
            result['agents_count'] = len(agents) if agents is not None else None
            result['agents'], result['agents_unlisted'] = listed_names(agents or [], AGENT_NAME_PATTERN)
    elif kind == 'models_text':
        rows = [line for line in lines if MODEL_ROW_PATTERN.fullmatch(line)]
        result['models_rows'] = len(rows)
        result['gemini_row_present'] = any(row.startswith('gemini-') for row in rows)
        result['exact_line_fallback_present'] = EXACT_LINE_FALLBACK in lines
        result['stderr_only_fetching_line'] = usable and only_fetching_stderr(err)
    elif kind == 'agents_text':
        values = [line.strip() for line in lines if line.strip()]
        result['agents_count'] = len(values)
        result['agents'], result['agents_unlisted'] = listed_names(values, AGENT_NAME_PATTERN)
    elif kind in ('print_model', 'print_text', 'bare'):
        result['stdout_lines'] = len(lines)
        if kind == 'print_model':
            result['model_record_present'] = any(MODEL_ROW_PATTERN.fullmatch(line) and line.startswith('gemini-') for line in lines)
    return result


def login_mode_decision(p3, p6):
    """print if P3 shows an https://accounts.google.com/ URL or a paste prompt without 'no controlling terminal';
    else tui if P6 does; else none. A URL on any other host (a docs or help link) is not sign-in evidence."""
    def shows(value):
        if not isinstance(value, dict):
            return False
        hosts = value.get('url_hosts')
        sign_in_url = value.get('url_present') is True and isinstance(hosts, list) and SIGN_IN_URL_HOST in hosts
        return (sign_in_url or value.get('paste_prompt_present') is True) and value.get('no_controlling_terminal_present') is False
    if shows(p3):
        return 'print', 'P3'
    if shows(p6):
        return 'tui', 'P6'
    return 'none', None


def capture_gate(stage, status, probes, login_mode):
    """The orchestrator gate of the sitting outline (S1-A2 signed-out, S1-A4 signed-in)."""
    if status != 'CAPTURE_COMPLETE':
        return {'stage': stage, 'passed': False, 'reasons': ['CAPTURE_NOT_COMPLETE']}
    reasons = []
    p2 = next((probe for probe in probes if probe.get('id') == 'P2'), None)
    if p2 is None:
        reasons.append('P2_NOT_RUN')
    elif stage == 'signed-out':
        value = p2['classification']
        if p2['outcome'] != 'exited' or value['timed_out'] is not False:
            reasons.append('P2_NOT_COMPLETED_WITHIN_BOUND')
        if value['status_helper_classification'] != 'LOGGED_OUT':
            reasons.append('P2_NOT_LOGGED_OUT_UNDER_STATUS_PREDICATE')
        if login_mode not in ('print', 'tui'):
            reasons.append('LOGIN_MODE_NONE')
    else:
        value = p2['classification']
        if type(p2['exit_code']) is not int or p2['exit_code'] != 0:
            reasons.append('P2_EXIT_NOT_ZERO')
        if value['status_value'] != 'SUCCESS':
            reasons.append('P2_STATUS_NOT_SUCCESS')
        if value['command_name'] != 'models':
            reasons.append('P2_COMMAND_NOT_MODELS')
        if value['gemini_row_present'] is not True:
            reasons.append('P2_NO_GEMINI_ROW')
    return {'stage': stage, 'passed': not reasons, 'reasons': reasons}


# ----- worker-profile inventory (token files: existence and size only, never opened) -----

def is_reparse(info):
    return bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def token_like(relative):
    return any('token' in part.casefold() for part in relative.split('/'))


def open_for_hash(path):
    # The only place the inventory opens a file. Token-like paths never reach it.
    return open(path, 'rb')


def hash_inventory_file(path):
    with open_for_hash(path) as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > INVENTORY_HASH_LIMIT:
            return None, 'over_1_mib'
        digest, count = hashlib.sha256(), 0
        while chunk := stream.read(65536):
            count += len(chunk)
            if count > INVENTORY_HASH_LIMIT:
                return None, 'over_1_mib'
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or count != after.st_size:
        return None, 'changed_during_hash'
    return digest.hexdigest(), None


def inventory_tree(root):
    try:
        info = os.lstat(root)
    except FileNotFoundError:
        return {'exists': False, 'reparse_point': False, 'entries': [], 'entry_count': 0, 'truncated': False}
    if is_reparse(info) or not stat.S_ISDIR(info.st_mode):
        return {'exists': True, 'reparse_point': is_reparse(info), 'directory': stat.S_ISDIR(info.st_mode),
                'entries': [], 'entry_count': 0, 'truncated': False}
    entries, truncated, stack = [], False, [(str(root), '', 0)]
    while stack and not truncated:
        directory, prefix, depth = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                children = sorted(iterator, key=lambda item: item.name)
        except OSError as error:
            entries.append({'path': prefix.rstrip('/') or '.', 'kind': 'unreadable_directory', 'error': type(error).__name__})
            continue
        for entry in children:
            if len(entries) >= MAX_TREE_ENTRIES:
                truncated = True
                break
            relative = prefix + entry.name
            try:
                item = os.lstat(entry.path)
            except OSError as error:
                entries.append({'path': relative, 'kind': 'unreadable', 'error': type(error).__name__})
                continue
            if is_reparse(item):
                entries.append({'path': relative, 'kind': 'reparse_point'})
            elif stat.S_ISDIR(item.st_mode):
                row = {'path': relative, 'kind': 'dir'}
                if depth + 1 < MAX_TREE_DEPTH:
                    stack.append((entry.path, relative + '/', depth + 1))
                else:
                    row['not_descended'] = 'depth_bound'
                entries.append(row)
            else:
                row = {'path': relative, 'kind': 'file', 'size': item.st_size, 'sha256': None}
                if token_like(relative):
                    row['token_file'] = True
                elif item.st_nlink != 1:
                    row['hash_skipped'] = 'hardlink'
                elif item.st_size > INVENTORY_HASH_LIMIT:
                    row['hash_skipped'] = 'over_1_mib'
                else:
                    try:
                        row['sha256'], reason = hash_inventory_file(entry.path)
                    except OSError as error:
                        row['sha256'], reason = None, 'unreadable_' + type(error).__name__
                    if reason:
                        row['hash_skipped'] = reason
                entries.append(row)
    entries.sort(key=lambda row: row['path'])
    return {'exists': True, 'reparse_point': False, 'entries': entries, 'entry_count': len(entries), 'truncated': truncated}


def profile_inventory(profile):
    return {'profile_root': str(profile), 'captured_at_unix_ms': int(time.time() * 1000),
            'trees': {label: inventory_tree(profile.joinpath(*parts)) for label, parts in INVENTORY_TREES}}


def inventory_changes(before, after):
    def rows(snapshot, kind):
        return {label + '/' + row['path']: row for label, tree in snapshot['trees'].items()
                for row in tree['entries'] if row['kind'] == kind}
    old, new = rows(before, 'file'), rows(after, 'file')
    new_files = [{'path': key, 'size': new[key]['size'], 'token_file': new[key].get('token_file', False)}
                 for key in sorted(set(new) - set(old))]
    changed = [key for key in sorted(set(new) & set(old))
               if (new[key]['size'], new[key]['sha256']) != (old[key]['size'], old[key]['sha256'])]
    removed = sorted(set(old) - set(new))
    directories = sorted(set(rows(after, 'dir')) - set(rows(before, 'dir')))
    return {'new_files': new_files, 'changed_files': changed, 'removed_files': removed, 'new_directories': directories}


# ----- one probe -----

def raw_digest(path):
    return {'bytes': path.stat().st_size, 'sha256': digest_file(path, RAW_FILE_MAXIMUM)}


def run_probe(win, identity, probe_id, stdin_mode, cwd, raw, limits, expected_sid, profile_sha256, record):
    """One bounded launch. A held-open pipe is NEVER written; the Job ends it after the window."""
    spec = PROBES[probe_id]
    argv = [str(EXECUTABLE), *spec['arguments']]
    window = stdin_mode == PIPE
    bound = WINDOW_SECONDS if window else PROBE_SECONDS
    stdout_path, stderr_path = raw / (probe_id + '.stdout'), raw / (probe_id + '.stderr')
    record.update(id=probe_id, argv=argv, stdin_mode=stdin_mode, bound_seconds=bound, stdin_bytes_written=0,
                  raw_path={'stdout': 'raw/' + stdout_path.name, 'stderr': 'raw/' + stderr_path.name},
                  cleanup_verified=False)
    writer = None
    with stdout_path.open('xb') as output, stderr_path.open('xb') as errors:
        try:
            if window:
                read_end, writer = os.pipe()
                stdin = os.fdopen(read_end, 'rb', buffering=0)
            else:
                stdin_path = raw / (probe_id + '.stdin')
                stdin_path.open('xb').close()
                record['stdin_sha256'] = digest_file(stdin_path, 0)
                stdin = stdin_path.open('rb')
            with stdin:
                process = launch_probe_process(win, identity, argv, cwd, stdin, output, errors, limits)
            started = time.monotonic()
            with process:
                record['process'] = observe_child(win, process, expected_sid, EXECUTABLE)
                record['process']['native_resource_limits'] = process.resource_limits_evidence
                record['process']['profile_matches_inventory_root'] = record['process']['profile_directory_sha256'] == profile_sha256
                if not record['process']['profile_matches_inventory_root']:
                    raise ValueError('Observed worker profile differs from the inventoried profile')
                outcome, code = wait_probe(process, output, errors, bound, window)
                record['elapsed_ms'] = int((time.monotonic() - started) * 1000)
            # Leaving the block closed the owned Job: descendants ended, profile unloaded.
            record['cleanup_verified'] = True
        finally:
            if writer is not None:
                os.close(writer)  # Closed only after the Job ended the child; nothing was ever written.
    record['outcome'] = outcome
    record['exit_code'] = code if outcome == 'exited' else 'terminated'
    record['stdout'], record['stderr'] = raw_digest(stdout_path), raw_digest(stderr_path)
    with stdout_path.open('rb') as handle:
        stdout = handle.read(MAX_OUTPUT + 1)
    with stderr_path.open('rb') as handle:
        stderr = handle.read(MAX_OUTPUT + 1)
    record['classification'] = classify(spec['kind'], stdout, stderr, outcome, record['exit_code'], window)
    del stdout, stderr
    return record


# ----- receipt -----

def bounded_receipt_text(report):
    text = json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2)
    if len(text.encode('ascii')) <= RECEIPT_MAX_BYTES:
        return text
    for key in ('profile_inventory_before', 'profile_inventory_after'):
        snapshot = report.get(key)
        if isinstance(snapshot, dict):
            for tree in snapshot.get('trees', {}).values():
                tree['entries'] = []
                tree['entries_omitted_for_receipt_bound'] = True
    report['inventory_entries_omitted_for_receipt_bound'] = True
    text = json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2)
    if len(text.encode('ascii')) > RECEIPT_MAX_BYTES:
        for key in ('new_files', 'changed_files', 'removed_files', 'new_directories'):
            report[key] = []
        report['inventory_changes_omitted_for_receipt_bound'] = True
        text = json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2)
    return text


def write_login_mode(root, report, p3, p6):
    mode, decided_by = login_mode_decision(p3['classification'], p6['classification'])
    keys = ('url_present', 'url_hosts', 'paste_prompt_present', 'waiting_line_present',
            'no_controlling_terminal_present', 'not_logged_in_present', 'auth_required_present',
            'exited_before_window', 'exit_code_before_window')
    evidence = {probe['id']: {'argv': probe['argv'], 'stdin_mode': probe['stdin_mode'], 'outcome': probe['outcome'],
                              'exit_code': probe['exit_code'], 'stdout_sha256': probe['stdout']['sha256'],
                              'stderr_sha256': probe['stderr']['sha256'],
                              'classification': {key: probe['classification'][key] for key in keys}}
                for probe in (p3, p6)}
    value = {'schema': 'cochem-agy-login-mode/1', 'attempt': report['attempt'], 'nonce': report['nonce'],
             'slot': report['slot'], 'stage': report['stage'], 'mode': mode, 'decided_by': decided_by,
             'rule': ('print if P3 shows an https://accounts.google.com/ URL (url_hosts) or paste_prompt_present and not '
                      'no_controlling_terminal_present; else tui if P6 does; else none'),
             'evidence': evidence,
             'evidence_sha256': hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2).encode('ascii')
    path = root / 'login-mode.json'
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {'mode': mode, 'decided_by': decided_by, 'path': path.name, 'sha256': hashlib.sha256(raw).hexdigest(),
            'evidence_sha256': value['evidence_sha256']}


def run(slot, stage, nonce, attempt):
    if not re.fullmatch(r'[a-f0-9]{32}', str(attempt)) or attempt == '0' * 32:
        raise ValueError('A nonzero lowercase 32-hex explicit attempt is required')
    if not re.fullmatch(r'[a-f0-9]{32}', str(nonce)) or slot not in SLOTS or stage not in STAGES:
        raise ValueError('Only slot1, the two capture stages and a 32-hex nonce are permitted')
    from cochem_pipeline import windows as win
    from cochem_pipeline.resource_limits import ResourceLimits
    from cochem_pipeline.ramdisk import ordinary_tree
    win.require_system()
    root = CAPTURE_BASE / f'{ROOT_PREFIX}{attempt}-{slot}-{stage}'
    if Path(__file__).resolve() != root / HELPER_NAME or current_executable() != PYTHON:
        raise ValueError('Use only the reviewed protected helper and installed interpreter')
    for path in (root, Path(__file__), PYTHON, Path(win.__file__)):
        ordinary_tree(path)
        win.validate_code_path(path)
    win.validate_private_directory(root)
    plan = STAGE_PROBES[stage]
    report = {'schema': 'cochem-agy-status-capture/1', 'attempt': attempt, 'nonce': nonce, 'slot': slot, 'stage': stage,
              'status': 'UNVERIFIED', 'system_sid': win.SYSTEM_SID, 'started_at_unix_ms': int(time.time() * 1000),
              'helper_sha256': digest_file(Path(__file__)), 'runtime_root': str(INSTALL),
              'install_receipt_sha256': INSTALL_RECEIPT_SHA256, 'source_manifest_sha256': MANIFEST_SHA256,
              'resource_limits_sha256': RESOURCE_SHA256, 'windows_runtime_sha256': WINDOWS_SHA256,
              'layout_sha256': None, 'config_sha256': None, 'revision': None,
              'native_executable': str(EXECUTABLE), 'native_executable_sha256_before': None,
              'native_executable_sha256_after': None, 'native_version_at_pin': AGY_VERSION,
              'probe_timeout_seconds': PROBE_SECONDS, 'window_seconds': WINDOW_SECONDS, 'output_limit_bytes': MAX_OUTPUT,
              'deadline_seconds': CAPTURE_DEADLINE_SECONDS,
              'probes_planned': [{'id': probe_id, 'stdin_mode': mode} for probe_id, mode in plan],
              'probes': [], 'probes_skipped': [], 'worker_identity': None, 'profile_root': None,
              'runtime_custody_verified': False, 'require_stopped_before': False, 'require_stopped_after': False,
              'daemon_states_verified_before_and_after': False, 'cleanup_verified': False,
              'native_model_jobs_executed': 0, 'login_inputs_written': 0, 'stdin_bytes_written': 0,
              'owner_credentials_read': False, 'token_files_opened': 0, 'raw_output_published': False,
              'raw_output_access': 'SYSTEM and BUILTIN\\Administrators only (inherited from the private capture root)',
              'oauth_urls_possibly_minted': 0, 'login_mode': None,
              'profile_inventory_before': None, 'profile_inventory_after': None,
              'new_files': [], 'changed_files': [], 'removed_files': [], 'new_directories': [],
              'gate': None, 'pipeline_started': False}
    with (root / 'capture-receipt.json').open('x', encoding='ascii') as receipt:
        phase, lock, deadline = 'reservation', None, time.monotonic() + CAPTURE_DEADLINE_SECONDS
        try:
            C.set_last_error(0)
            lock = win._api()['kernel32'].CreateMutexW(None, False, 'Global\\CoChem427-NativeStatusSetup')
            win._check(lock, 'Reserve exclusive native status check')
            if C.get_last_error() == 183:
                raise ValueError('Another native status check owns the reservation')
            phase = 'runtime_custody'
            validate_interpreter()
            if digest_file(Path(win.__file__)) != WINDOWS_SHA256:
                raise ValueError('Installed Windows launch implementation differs from the reviewed pin')
            report['revision'] = verify_r4_runtime(win, INSTALL_RECEIPT_SHA256)
            phase = 'layout'
            layout, layout_hash = protected_json(win, INSTALL / 'windows-layout.json')
            config, config_hash = protected_json(win, INSTALL / 'pipeline.json')
            if layout_hash != LAYOUT_SHA256 or config_hash != CONFIG_SHA256:
                raise ValueError('Exact r4 layout/configuration binding differs')
            expected_slots = {f'slot{i}' for i in range(1, 7)}
            if (set(layout['slots']) != expected_slots or set(config['workers']) != expected_slots
                    or set(config['slot_roots']) != expected_slots or config.get('max_execution_slots') != 4
                    or layout['private_root'] != config['private_root']
                    or layout['operator_name'] != config['operator_name']):
                raise ValueError('Protected layout differs from the reviewed six-identity/four-slot configuration')
            for key in expected_slots:
                row = layout['slots'][key]
                worker = config['workers'][key]
                if (row['identity'] != worker['name'] or row['credential_target'] != worker['credential_target']
                        or row['root'] != config['slot_roots'][key]
                        or worker['name'] != 'CoChem422Worker' + key[4:]
                        or worker['credential_target'] != 'CoChem422/' + key):
                    raise ValueError('Installed identity mapping differs between layout and configuration')
            spec = layout['slots'][slot]
            identity = win.WorkerIdentity(spec['identity'], spec['credential_target'])
            expected_sid = win._sid_text(win._account_sid(identity.name))
            if expected_sid != spec['sid']:
                raise ValueError('Provisioned worker SID changed')
            report['worker_identity'] = identity.name
            phase = 'boundaries'
            private = Path(config['private_root'])
            ordinary_tree(private)
            win.validate_private_directory(private)
            identities = {key: win.WorkerIdentity(row['name'], row['credential_target'])
                          for key, row in config['workers'].items()}
            private, roots = win._layout_paths(private, config['slot_roots'], identities)
            boundaries = win._layout_boundaries(private, roots)
            win._validate_control_ancestors(boundaries[0].parent)
            worker_sids = [win._sid_text(win._account_sid(value.name)) for value in identities.values()]
            for boundary in boundaries:
                win._validate_boundary(boundary, worker_sids)
            phase = 'native_custody'
            if Path(config['providers']['gemini']['executable']) != EXECUTABLE:
                raise ValueError('Protected provider path differs from the reviewed native executable')
            ordinary_tree(EXECUTABLE)
            win.validate_code_path(EXECUTABLE)
            before = digest_file(EXECUTABLE)
            if before != AGY_SHA256:
                raise ValueError('Native executable differs from the reviewed agy pin')
            report.update(layout_sha256=layout_hash, config_sha256=config_hash,
                          native_executable_sha256_before=before, runtime_custody_verified=True)
            limits = ResourceLimits.from_dict(config['execution_limits'])
            raw = root / 'raw'
            raw.mkdir()
            win.validate_private_directory(raw)
            phase = 'daemon_precheck'
            require_stopped(win)
            report['require_stopped_before'] = True
            phase = 'inventory_before'
            profile = PROFILE_PARENT / identity.name
            info = os.lstat(profile)
            if is_reparse(info) or not stat.S_ISDIR(info.st_mode):
                raise ValueError('Worker profile directory is not an ordinary directory')
            report['profile_root'] = str(profile)
            profile_sha256 = hashlib.sha256(str(profile).casefold().encode()).hexdigest()
            report['profile_inventory_before'] = profile_inventory(profile)
            for index, (probe_id, stdin_mode) in enumerate(plan):
                bound = WINDOW_SECONDS if stdin_mode == PIPE else PROBE_SECONDS
                if time.monotonic() + bound + PROBE_CLEANUP_MARGIN_SECONDS > deadline:
                    report['probes_skipped'] = [item for item, _ in plan[index:]]
                    break
                phase = 'native_launch'
                record = {}
                report['probes'].append(record)
                run_probe(win, identity, probe_id, stdin_mode, spec['root'], raw, limits, expected_sid, profile_sha256, record)
                phase = 'native_result'
                if probe_id == 'P1' and record['classification']['version_matches'] is not True:
                    raise ValueError('The pinned agy did not report the reviewed version')
            report['cleanup_verified'] = all(probe.get('cleanup_verified') is True for probe in report['probes'])
            phase = 'inventory_after'
            report['profile_inventory_after'] = profile_inventory(profile)
            report.update(inventory_changes(report['profile_inventory_before'], report['profile_inventory_after']))
            phase = 'native_custody'
            after = digest_file(EXECUTABLE)
            report['native_executable_sha256_after'] = after
            if after != before:
                raise ValueError('Native executable changed during the capture')
            phase = 'daemon_postcheck'
            require_stopped(win)
            report['require_stopped_after'] = True
            report['daemon_states_verified_before_and_after'] = True
            complete = not report['probes_skipped'] and len(report['probes']) == len(plan) and report['cleanup_verified']
            phase = 'login_mode'
            if stage == 'signed-out' and complete:
                found = {probe['id']: probe for probe in report['probes']}
                report['login_mode'] = write_login_mode(root, report, found['P3'], found['P6'])
            report['status'] = 'CAPTURE_COMPLETE' if complete else 'CAPTURE_INCOMPLETE'
        except BaseException as exc:
            report['status'] = 'CAPTURE_FAILED'
            # Exception messages may contain native output; disclose a fixed classification only.
            report['failure_kind'] = ('cleanup_unverified' if isinstance(exc, win.WindowsCleanupError)
                                      else 'timeout' if isinstance(exc, TimeoutError) else 'verification_failed')
            report['operator_review_required'] = True
            report['failure'] = safe_failure(exc, 'native_cleanup' if isinstance(exc, win.WindowsCleanupError) else phase)
            report['cleanup_verified'] = False
            if report['profile_inventory_before'] is not None and report['profile_inventory_after'] is None:
                try:  # Read-only evidence of what the probes that did run left behind.
                    report['profile_inventory_after'] = profile_inventory(PROFILE_PARENT / report['worker_identity'])
                    report.update(inventory_changes(report['profile_inventory_before'], report['profile_inventory_after']))
                except BaseException as error:
                    report['profile_inventory_after_error'] = re.sub('[^A-Za-z0-9_]', '', type(error).__name__)[:80]
        finally:
            if lock:
                win._close(lock)
            report['oauth_urls_possibly_minted'] = sum(
                1 for probe in report['probes']
                if isinstance(probe.get('classification'), dict) and probe['classification'].get('url_present') is True)
            try:
                mode = report['login_mode']['mode'] if isinstance(report['login_mode'], dict) else None
                report['gate'] = capture_gate(stage, report['status'], report['probes'], mode)
            except BaseException:
                report['gate'] = {'stage': stage, 'passed': False, 'reasons': ['CAPTURE_NOT_COMPLETE']}
            report['finished_at_unix_ms'] = int(time.time() * 1000)
            receipt.write(bounded_receipt_text(report))
            receipt.flush()
            os.fsync(receipt.fileno())
    return 0 if report['status'] == 'CAPTURE_COMPLETE' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--slot', choices=list(SLOTS), required=True)
    parser.add_argument('--stage', choices=list(STAGES), required=True)
    parser.add_argument('--nonce', required=True)
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{32}', args.nonce):
        parser.error('A 32-hex one-shot receipt nonce is required')
    try:
        return run(args.slot, args.stage, args.nonce, args.attempt)
    except BaseException as exc:
        print(json.dumps({'status': 'PRE_RECEIPT_FAILURE', 'failure': safe_failure(exc, 'trusted_preflight')}), file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
