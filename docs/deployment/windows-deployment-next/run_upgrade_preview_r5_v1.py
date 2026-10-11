"""One read-only upgrade preview of the r5 runtime (r5 sitting stage S10, build-manifest step 14).

Standalone artifact copied by run-upgrade-preview-r5-v1.ps1 into a fresh SYSTEM/BA-only root
C:\\Program Files\\CoChem\\UpgradePreview4.2.7-windows-20261011-r5-v1-<attempt> and run once by a
one-shot SYSTEM task under the verified r5 interpreter (-I -B). Never import it from the checkout
for a real run. Derived from the house helper pattern of agy_status_capture_r4_v1.py (strict_json,
digest_file, safe_failure, exclusive receipt reservation, held evidence instead of retries).

The helper binds the r5 stopped runtime by content (install-after.json sha256 handed over by the
elevated wrapper, mode FRESH_STOPPED_RUNTIME_READY, the commissioned configuration 135cd9ec and the
venv interpreter sha256), binds the current (commissioned) and proposed (staged r5 candidate)
configurations by sha256, and then runs exactly one child:

    <r5 venv python> -I -B -X utf8 -m cochem_pipeline upgrade-preview
        --current-config <current> --proposed-config <proposed>

cochem_pipeline.upgrade_preview opens the job board read-only (mode=ro, query_only) and never
invokes a provider. The child's JSON is retained byte for byte as upgrade-preview.json and gated:
read_only true; native_models_executed false; no changed identity; no changed protected path other
than the expected configuration path swap (current -> proposed file); database.exists true;
database.schema_changes []; configuration_changes keys within ['providers'] ([] in held mode); and in enabled mode
(deploy audit B-F5) the per-provider digests of the two bound files (sha256 of each providers.<name> value as compact
document-order JSON, from the very bytes bound by sha256) differ for 'gemini' only.

Files written in the root, each created exclusively (never overwritten): upgrade-preview-receipt.json
(always, reserved first; an existing receipt refuses the run), upgrade-preview.stderr.txt,
upgrade-preview.json (valid JSON object output only), upgrade-preview.stdout-invalid.bin (malformed
output only) and upgrade-preview-held.json (any gate failure or error). Nothing is retried.
Exit codes: 0 gate passed, 3 gate failed (held), 4 preview failed (held), 5 refused before any
receipt (nothing written), 2 usage error.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

COCHEM = Path(r'C:\Program Files\CoChem')
NAMESPACE_DATE = '20261011'
DEFAULT_INSTALL_ROOT = COCHEM / 'Pipeline4.2.7-windows-20261011-r5'
DEFAULT_CURRENT = COCHEM / 'WardenCommissioning4.2.7-windows-20261007-r3-v1' / 'pipeline.json'
DEFAULT_PROPOSED = COCHEM / 'WardenConfig4.2.7-windows-20261011-r5-v1' / 'pipeline.json'
ROOT_PREFIX = 'UpgradePreview4.2.7-windows-' + NAMESPACE_DATE + '-r5-v1-'
INSTALL_ROOT_PATTERN = re.compile(r'Pipeline4\.2\.7-windows-[0-9]{8}-r5')
HELPER_NAME = 'run_upgrade_preview_r5_v1.py'

# The commissioned configuration (WardenCommissioning r3-v1 and its r4 reference copy).
CONFIG_SHA256 = '135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
INSTALL_SCHEMA = 'cochem-stopped-runtime-update/1'
INSTALL_MODE = 'FRESH_STOPPED_RUNTIME_READY'
MAIN_REPAIR = 'src/cochem_pipeline/__main__.py'
SYSTEM_SID = 'S-1-5-18'

PREVIEW_SCHEMA = 'cochem-upgrade-preview/1'
RECEIPT_SCHEMA = 'cochem-upgrade-preview-r5-receipt/1'
HELD_SCHEMA = 'cochem-upgrade-preview-r5-held/1'
RECEIPT_NAME = 'upgrade-preview-receipt.json'
HELD_NAME = 'upgrade-preview-held.json'
OUTPUT_NAME = 'upgrade-preview.json'
STDERR_NAME = 'upgrade-preview.stderr.txt'
INVALID_STDOUT_NAME = 'upgrade-preview.stdout-invalid.bin'

MODES = ('held', 'enabled')
ALLOWED_CONFIGURATION_KEYS = ('providers',)
ALLOWED_CHANGED_PROVIDERS = ('gemini',)
CHILD_TIMEOUT_SECONDS = 120          # the task runs under ExecutionTimeLimit PT3M
CONFIG_MAX_BYTES = 1024 * 1024       # the module's own configuration bound
CONTROL_MAX_BYTES = 1024 * 1024
OUTPUT_MAX_BYTES = 64 * 1024 * 1024
LISTED_MAXIMUM = 256

STATUS_PASSED = 'UPGRADE_PREVIEW_GATE_PASSED'
STATUS_GATE_FAILED = 'UPGRADE_PREVIEW_GATE_FAILED'
STATUS_FAILED = 'UPGRADE_PREVIEW_FAILED'
EXIT_PASSED, EXIT_GATE_FAILED, EXIT_FAILED, EXIT_REFUSED = 0, 3, 4, 5
EXIT_CODES = {STATUS_PASSED: EXIT_PASSED, STATUS_GATE_FAILED: EXIT_GATE_FAILED, STATUS_FAILED: EXIT_FAILED}

# Gate reasons in evaluation order (run-upgrade-preview-r5-v1.ps1 Get-PreviewGate uses the same list).
REASONS = ('PREVIEW_SCHEMA_INVALID', 'READ_ONLY_NOT_TRUE', 'NATIVE_MODELS_EXECUTED', 'CURRENT_BINDING_DIFFERS',
           'PROPOSED_BINDING_DIFFERS', 'IDENTITIES_MALFORMED', 'IDENTITIES_CHANGED', 'PROTECTED_PATHS_MALFORMED',
           'PROTECTED_PATHS_CHANGED', 'DATABASE_MALFORMED', 'DATABASE_NOT_PRESENT', 'SCHEMA_CHANGES_MALFORMED',
           'SCHEMA_CHANGES_PRESENT', 'MIGRATION_EXECUTED', 'CONFIGURATION_CHANGES_MALFORMED',
           'CONFIGURATION_CHANGES_OUTSIDE_PROVIDERS', 'CONFIGURATION_CHANGES_IN_HELD_MODE', 'PROVIDER_DIGESTS_MALFORMED',
           'PROVIDERS_CHANGED_OUTSIDE_GEMINI')
FAILURE_PHASES = ('install_binding', 'config_binding', 'preview_launch', 'preview_output', 'gate', 'output')
FAILURE_REASONS = ('INSTALL_BINDING_DIFFERS', 'CONFIG_BINDING_DIFFERS', 'PREVIEW_LAUNCH_FAILED', 'PREVIEW_TIMED_OUT',
                   'PREVIEW_EXIT_NONZERO', 'PREVIEW_OUTPUT_TOO_LARGE', 'PREVIEW_OUTPUT_MALFORMED',
                   'GATE_EVALUATION_FAILED', 'OUTPUT_WRITE_FAILED', 'UNEXPECTED_ERROR')
OWNER_OPTIONS = ('R4-RESTORE: retarget-warden-r5.ps1 -Target r4 -Apply -Start -Attempt <fresh> (r5 has not been started at S10)',
                 'OWNER_WAIVER: record an explicit owner waiver line in the series log and continue (manifest step 14 alternative)')
PREREQUISITE_KEYS = ('id', 'required', 'verified', 'detail', 'path')

HEX32 = re.compile(r'[a-f0-9]{32}')
HEX64 = re.compile(r'[a-f0-9]{64}')


class PreviewRefusal(Exception):
    """A classified refusal; its detail is a fixed text written by this helper, never native output."""

    def __init__(self, reason, detail):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Settings:
    attempt: str
    nonce: str
    install_root: Path
    install_after_sha256: str
    venv_python_sha256: str
    current: Path
    current_sha256: str
    proposed: Path
    proposed_sha256: str
    mode: str
    output: Path
    preview_base: Path = COCHEM
    commissioned_sha256: str = CONFIG_SHA256
    child_timeout: float = CHILD_TIMEOUT_SECONDS

    @property
    def root(self):
        return self.output.parent


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


def read_bounded(path, maximum):
    """Read a file once (no reparse point, bounded) and return its bytes and sha256."""
    path = Path(path)
    info = os.lstat(path)
    if getattr(info, 'st_file_attributes', 0) & 0x400 or not path.is_file():
        raise PreviewRefusal('INSTALL_BINDING_DIFFERS', 'A bound file is not an ordinary file')
    if info.st_size > maximum:
        raise ValueError('A bound file exceeds its size bound')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('A bound file grew beyond its size bound')
    return raw, hashlib.sha256(raw).hexdigest()


def digest_file(path, maximum=1024 * 1024 * 1024):
    path = Path(path)
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
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Reviewed file changed during hash capture')
    return digest.hexdigest()


def write_new(path, data):
    """Exclusive create (CreateNew): never overwrites; returns the sha256 of the bytes written."""
    with Path(path).open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def safe_failure(error, phase):
    kind = re.sub('[^A-Za-z0-9_]', '', type(error).__name__)[:80] or 'Exception'
    if isinstance(error, PreviewRefusal):
        reason, detail = error.reason, error.detail
    else:
        reason = {'install_binding': 'INSTALL_BINDING_DIFFERS', 'config_binding': 'CONFIG_BINDING_DIFFERS',
                  'preview_launch': 'PREVIEW_LAUNCH_FAILED', 'preview_output': 'PREVIEW_OUTPUT_MALFORMED',
                  'gate': 'GATE_EVALUATION_FAILED', 'output': 'OUTPUT_WRITE_FAILED'}.get(phase, 'UNEXPECTED_ERROR')
        detail = None
    return {'phase': phase if phase in FAILURE_PHASES else 'output',
            'reason': reason if reason in FAILURE_REASONS else 'UNEXPECTED_ERROR',
            'error_type': kind, 'detail': detail}


# ----- arguments -----

def build_parser():
    parser = argparse.ArgumentParser(description='One read-only r5 upgrade preview (S10); see the module docstring.')
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--nonce', required=True)
    parser.add_argument('--install-root', default=str(DEFAULT_INSTALL_ROOT))
    parser.add_argument('--install-after-sha256', required=True)
    parser.add_argument('--venv-python-sha256', required=True)
    parser.add_argument('--current', default=str(DEFAULT_CURRENT))
    parser.add_argument('--current-sha256', default=CONFIG_SHA256)
    parser.add_argument('--proposed', default=str(DEFAULT_PROPOSED))
    parser.add_argument('--proposed-sha256', required=True)
    parser.add_argument('--mode', choices=list(MODES), required=True)
    parser.add_argument('--output', default=None,
                        help='default: C:\\Program Files\\CoChem\\' + ROOT_PREFIX + '<attempt>\\' + OUTPUT_NAME)
    return parser


def settings_from_args(args):
    if not HEX32.fullmatch(args.attempt or '') or args.attempt == '0' * 32:
        raise PreviewRefusal('ARGUMENTS_INVALID', 'A nonzero lowercase 32-hex attempt is required')
    if not HEX32.fullmatch(args.nonce or ''):
        raise PreviewRefusal('ARGUMENTS_INVALID', 'A lowercase 32-hex one-shot nonce is required')
    for value in (args.install_after_sha256, args.venv_python_sha256, args.current_sha256, args.proposed_sha256):
        if not HEX64.fullmatch(value or ''):
            raise PreviewRefusal('ARGUMENTS_INVALID', 'Every content binding must be a lowercase sha256')
    if args.current_sha256 != CONFIG_SHA256:
        raise PreviewRefusal('ARGUMENTS_INVALID', 'The current configuration must be the commissioned 135cd9ec bytes')
    output = Path(args.output) if args.output else COCHEM / (ROOT_PREFIX + args.attempt) / OUTPUT_NAME
    paths = (Path(args.install_root), Path(args.current), Path(args.proposed), output)
    if any(not path.is_absolute() for path in paths) or output.name != OUTPUT_NAME:
        raise PreviewRefusal('ARGUMENTS_INVALID', 'Absolute paths and the upgrade-preview.json output name are required')
    return Settings(attempt=args.attempt, nonce=args.nonce, install_root=Path(args.install_root),
                    install_after_sha256=args.install_after_sha256, venv_python_sha256=args.venv_python_sha256,
                    current=Path(args.current), current_sha256=args.current_sha256, proposed=Path(args.proposed),
                    proposed_sha256=args.proposed_sha256, mode=args.mode, output=output)


# ----- trusted preflight (production only; before any receipt exists) -----

def require_system(settings):
    """The installed r5 cochem_pipeline.windows.require_system: the LocalSystem SID, not elevation."""
    from cochem_pipeline import windows as win
    site = (settings.install_root / '.venv' / 'Lib' / 'site-packages').resolve()
    if site not in Path(win.__file__).resolve().parents:
        raise PreviewRefusal('TRUSTED_PREFLIGHT', 'cochem_pipeline.windows is not the installed r5 package')
    win.require_system()


def trusted_preflight(settings, *, helper=None, executable=None, isolated=None, no_bytecode=None, system_check=None):
    helper = Path(__file__) if helper is None else Path(helper)
    executable = sys.executable if executable is None else executable
    isolated = bool(sys.flags.isolated) if isolated is None else isolated
    no_bytecode = bool(sys.dont_write_bytecode) if no_bytecode is None else no_bytecode
    root = settings.root
    python = settings.install_root / '.venv' / 'Scripts' / 'python.exe'
    if (root.parent != settings.preview_base or root.name != ROOT_PREFIX + settings.attempt
            or settings.output.name != OUTPUT_NAME):
        raise PreviewRefusal('TRUSTED_PREFLIGHT', 'Use only the reviewed UpgradePreview root of this attempt')
    if settings.install_root.parent != settings.preview_base or not INSTALL_ROOT_PATTERN.fullmatch(settings.install_root.name):
        raise PreviewRefusal('TRUSTED_PREFLIGHT', 'The install root is not an installed r5 runtime root')
    if helper.resolve() != (root / HELPER_NAME).resolve():
        raise PreviewRefusal('TRUSTED_PREFLIGHT', 'Use only the reviewed protected helper copy')
    if Path(executable).resolve() != python.resolve() or not isolated or not no_bytecode:
        raise PreviewRefusal('TRUSTED_PREFLIGHT', 'Use only the verified r5 interpreter with -I -B')
    (require_system if system_check is None else system_check)(settings)
    return {'system_sid': SYSTEM_SID, 'interpreter': str(python), 'isolated': True, 'dont_write_bytecode': True}


# ----- bindings -----

def verify_install(settings):
    """Content binding of the r5 stopped runtime (the subset of retarget-warden-r5 Assert-R5InstalledBindings
    the SYSTEM run re-checks; the elevated wrapper verified the full binding and holds the files open)."""
    after_path = settings.install_root / 'install-after.json'
    raw, digest = read_bounded(after_path, CONTROL_MAX_BYTES)
    if digest != settings.install_after_sha256:
        raise PreviewRefusal('INSTALL_BINDING_DIFFERS', 'install-after.json differs from the sha256 the wrapper bound')
    try:
        after = strict_json(raw.decode('utf-8-sig'))
    except (UnicodeError, ValueError):
        raise PreviewRefusal('INSTALL_BINDING_DIFFERS', 'install-after.json is not strict JSON') from None
    if not isinstance(after, dict):
        raise PreviewRefusal('INSTALL_BINDING_DIFFERS', 'install-after.json is not an object')
    expected = {'schema': INSTALL_SCHEMA, 'mode': INSTALL_MODE, 'target_root': str(settings.install_root),
                'configuration_sha256': settings.commissioned_sha256, 'configuration_unchanged': True,
                'tasks_changed': 0, 'pipeline_started': False, 'credentials_modified': False,
                'databases_modified': False, 'holds': []}
    if any(type(after.get(key)) is not type(value) or after.get(key) != value for key, value in expected.items()):
        raise PreviewRefusal('INSTALL_BINDING_DIFFERS', 'install-after.json is not the successful fresh r5 stopped runtime')
    verification = after.get('verification')
    if (not isinstance(verification, dict) or verification.get('no_system_or_model_execution') is not True
            or verification.get('configuration_parsed') is not True):
        raise PreviewRefusal('INSTALL_BINDING_DIFFERS', 'install-after.json verification flags differ')
    repairs, pins = after.get('reviewed_repairs'), after.get('reviewed_repairs_sha256')
    if (not isinstance(repairs, list) or not repairs or any(not isinstance(item, str) for item in repairs)
            or MAIN_REPAIR not in repairs or not isinstance(pins, dict) or set(pins) != set(repairs)
            or any(not isinstance(value, str) or not HEX64.fullmatch(value) for value in pins.values())):
        raise PreviewRefusal('INSTALL_BINDING_DIFFERS', 'install-after.json lacks the reviewed r5 repairs including __main__.py')
    bindings = after.get('runtime_bindings')
    if not isinstance(bindings, dict) or bindings.get('venv_python_sha256') != settings.venv_python_sha256:
        raise PreviewRefusal('INSTALL_BINDING_DIFFERS', 'The venv interpreter binding differs from the wrapper')
    python = settings.install_root / '.venv' / 'Scripts' / 'python.exe'
    if digest_file(python, 16 * 1024 * 1024) != settings.venv_python_sha256:
        raise PreviewRefusal('INSTALL_BINDING_DIFFERS', 'The r5 venv interpreter differs from its install binding')
    revision = verification.get('revision') if isinstance(verification.get('revision'), dict) else {}
    return {'install_root': str(settings.install_root), 'install_after_path': str(after_path),
            'install_after_sha256': digest, 'install_mode': after['mode'], 'venv_python': python,
            'venv_python_sha256': settings.venv_python_sha256,
            'source_manifest_sha256': after.get('source_manifest_sha256'),
            'revision_sha256': revision.get('source_sha256'), 'reviewed_repairs': list(repairs)}


def provider_digests(document):
    """{name: sha256} of each providers.<name> value as compact document-order JSON, or None without a providers object."""
    providers = document.get('providers') if isinstance(document, dict) else None
    if not isinstance(providers, dict):
        return None
    return {name: hashlib.sha256(json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('ascii')).hexdigest()
            for name, value in providers.items()}


def verify_config(path, expected_sha256):
    path = Path(path)
    try:
        raw, digest = read_bounded(path, CONFIG_MAX_BYTES)
    except PreviewRefusal:
        raise PreviewRefusal('CONFIG_BINDING_DIFFERS', 'A bound configuration is not an ordinary file') from None
    if digest != expected_sha256:
        raise PreviewRefusal('CONFIG_BINDING_DIFFERS', 'A configuration differs from its bound sha256')
    try:
        value = strict_json(raw.decode('utf-8-sig'))
    except (UnicodeError, ValueError):
        raise PreviewRefusal('CONFIG_BINDING_DIFFERS', 'A bound configuration is not strict JSON') from None
    if not isinstance(value, dict):
        raise PreviewRefusal('CONFIG_BINDING_DIFFERS', 'A bound configuration is not a JSON object')
    return {'path': str(path.absolute()), 'sha256': digest, 'length': len(raw), 'providers_sha256': provider_digests(value)}


def check_mode(settings, current, proposed):
    if current['sha256'] != settings.commissioned_sha256:
        raise PreviewRefusal('CONFIG_BINDING_DIFFERS', 'The current configuration is not the commissioned configuration')
    if settings.mode == 'held' and proposed['sha256'] != settings.commissioned_sha256:
        raise PreviewRefusal('CONFIG_BINDING_DIFFERS', 'Held mode requires the commissioned bytes as the candidate')
    if settings.mode == 'enabled' and proposed['sha256'] == settings.commissioned_sha256:
        raise PreviewRefusal('CONFIG_BINDING_DIFFERS', 'Enabled mode requires a candidate that differs from the commissioned bytes')


# ----- the preview child -----

def preview_command(python, current, proposed):
    return [str(python), '-I', '-B', '-X', 'utf8', '-m', 'cochem_pipeline', 'upgrade-preview',
            '--current-config', str(current), '--proposed-config', str(proposed)]


def launch(argv, cwd, timeout):
    """Run the one child with no stdin and captured output; on timeout it is ended (subprocess.run)."""
    started = time.monotonic()
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        completed = subprocess.run(argv, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, timeout=timeout, creationflags=flags, check=False)
    except subprocess.TimeoutExpired as exc:
        return {'exit_code': None, 'timed_out': True, 'stdout': exc.stdout or b'', 'stderr': exc.stderr or b'',
                'elapsed_ms': int((time.monotonic() - started) * 1000)}
    return {'exit_code': completed.returncode, 'timed_out': False, 'stdout': completed.stdout or b'',
            'stderr': completed.stderr or b'', 'elapsed_ms': int((time.monotonic() - started) * 1000)}


# ----- gate -----

def _change_entries(value):
    """The module's _changes list: objects with a string key and an exact boolean changed flag."""
    if not isinstance(value, list):
        return None
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get('key'), str) or type(item.get('changed')) is not bool:
            return None
    return value


def evaluate_gate(preview, mode, current, proposed):
    """S10 gate. current/proposed: {'path', 'sha256', 'providers_sha256'} as bound by this helper (verify_config)."""
    summary = {'identities_changed': [], 'protected_paths_changed': [], 'configuration_path_swap_accepted': False,
               'configuration_change_keys': [], 'schema_change_count': None, 'database_exists': None,
               'workflows_captured': None, 'providers_changed': []}
    if not isinstance(preview, dict) or preview.get('schema') != PREVIEW_SCHEMA:
        return {'passed': False, 'reasons': ['PREVIEW_SCHEMA_INVALID'], 'summary': summary}
    reasons = []
    if preview.get('read_only') is not True:
        reasons.append('READ_ONLY_NOT_TRUE')
    if preview.get('native_models_executed') is not False:
        reasons.append('NATIVE_MODELS_EXECUTED')
    for name, bound, code in (('current', current, 'CURRENT_BINDING_DIFFERS'), ('proposed', proposed, 'PROPOSED_BINDING_DIFFERS')):
        info = preview.get(name)
        if not isinstance(info, dict) or info.get('path') != bound['path'] or info.get('sha256') != bound['sha256']:
            reasons.append(code)
    identities = _change_entries(preview.get('identities'))
    if identities is None:
        reasons.append('IDENTITIES_MALFORMED')
    else:
        summary['identities_changed'] = [item['key'] for item in identities if item['changed']][:LISTED_MAXIMUM]
        if summary['identities_changed']:
            reasons.append('IDENTITIES_CHANGED')
    paths = _change_entries(preview.get('protected_paths'))
    if paths is None:
        reasons.append('PROTECTED_PATHS_MALFORMED')
    else:
        changed = []
        for item in paths:
            if not item['changed']:
                continue
            # The one expected difference: the configuration file itself moves from the commissioned copy to
            # the staged candidate path. Any other protected path change holds the sitting.
            if (item['key'] == 'configuration' and isinstance(item.get('before'), str) and item['before'] == current['path']
                    and isinstance(item.get('after'), str) and item['after'] == proposed['path']):
                summary['configuration_path_swap_accepted'] = True
                continue
            changed.append(item['key'])
        summary['protected_paths_changed'] = changed[:LISTED_MAXIMUM]
        if changed:
            reasons.append('PROTECTED_PATHS_CHANGED')
    database = preview.get('database')
    if not isinstance(database, dict):
        reasons.append('DATABASE_MALFORMED')
    else:
        summary['database_exists'] = database.get('exists')
        if database.get('exists') is not True:
            reasons.append('DATABASE_NOT_PRESENT')
        schema_changes = database.get('schema_changes')
        if not isinstance(schema_changes, list):
            reasons.append('SCHEMA_CHANGES_MALFORMED')
        else:
            summary['schema_change_count'] = len(schema_changes)
            if schema_changes:
                reasons.append('SCHEMA_CHANGES_PRESENT')
        if database.get('migration_executed') is not False:
            reasons.append('MIGRATION_EXECUTED')
        if isinstance(database.get('workflows'), list):
            summary['workflows_captured'] = len(database['workflows'])
    changes = preview.get('configuration_changes')
    if not isinstance(changes, list) or any(not isinstance(item, dict) or not isinstance(item.get('key'), str) for item in changes):
        reasons.append('CONFIGURATION_CHANGES_MALFORMED')
    else:
        keys = [item['key'] for item in changes]
        summary['configuration_change_keys'] = keys[:LISTED_MAXIMUM]
        if any(key not in ALLOWED_CONFIGURATION_KEYS for key in keys):
            reasons.append('CONFIGURATION_CHANGES_OUTSIDE_PROVIDERS')
        if mode == 'held' and keys:
            reasons.append('CONFIGURATION_CHANGES_IN_HELD_MODE')
    if mode == 'enabled':
        # Deploy audit B-F5: a 'providers' change key alone would let any provider change; the bound files themselves
        # may differ in providers.gemini only.
        before, after = current.get('providers_sha256'), proposed.get('providers_sha256')
        if not (_digest_map(before) and _digest_map(after)):
            reasons.append('PROVIDER_DIGESTS_MALFORMED')
        else:
            changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
            summary['providers_changed'] = changed[:LISTED_MAXIMUM]
            if any(name not in ALLOWED_CHANGED_PROVIDERS for name in changed):
                reasons.append('PROVIDERS_CHANGED_OUTSIDE_GEMINI')
    return {'passed': not reasons, 'reasons': reasons, 'summary': summary}


def _digest_map(value):
    return isinstance(value, dict) and all(isinstance(name, str) and isinstance(digest, str) and HEX64.fullmatch(digest)
                                           for name, digest in value.items())


def rollback_prerequisites(preview):
    """The preview's rollback prerequisites, for the owner sheet (allowlisted keys only)."""
    items = preview.get('rollback_prerequisites') if isinstance(preview, dict) else None
    if not isinstance(items, list):
        return None
    result = []
    for item in items[:16]:
        if isinstance(item, dict):
            result.append({key: item[key] for key in PREREQUISITE_KEYS
                           if key in item and isinstance(item[key], (str, bool, type(None)))})
    return result


# ----- run -----

def receipt_text(report):
    return json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2).encode('ascii')


def run(settings, *, preflight=None, launcher=None):
    """Bind, preview, gate and record exactly once. Raises before any write when refused."""
    trusted = (trusted_preflight if preflight is None else preflight)(settings)
    launcher = launch if launcher is None else launcher
    root = settings.root
    if not root.is_dir():
        raise PreviewRefusal('TRUSTED_PREFLIGHT', 'The preview root does not exist')
    report = {'schema': RECEIPT_SCHEMA, 'attempt': settings.attempt, 'nonce': settings.nonce, 'status': 'UNVERIFIED',
              'system_sid': trusted.get('system_sid'), 'helper_sha256': digest_file(Path(__file__)),
              'started_at_unix_ms': int(time.time() * 1000), 'install_root': str(settings.install_root),
              'install_after_path': None, 'install_after_sha256': None, 'install_mode': None, 'venv_python': None,
              'venv_python_sha256': None, 'source_manifest_sha256': None, 'revision_sha256': None, 'reviewed_repairs': None,
              'current': None, 'proposed': None, 'config_mode': settings.mode, 'commissioned_sha256': settings.commissioned_sha256,
              'command': None, 'child': None, 'stderr_path': None, 'preview_path': None, 'preview_sha256': None,
              'invalid_stdout_path': None, 'gate': None, 'summary': None, 'rollback_prerequisites': None,
              'failure': None, 'held_record_path': None, 'held_record_sha256': None,
              'child_timeout_seconds': settings.child_timeout, 'native_models_executed': False, 'tasks_changed': 0,
              'automatic_retry_allowed': False}
    # Reservation: an existing receipt refuses the run (FileExistsError) before anything else is written.
    with (root / RECEIPT_NAME).open('xb') as receipt:
        phase = 'install_binding'
        try:
            binding = verify_install(settings)
            report.update({key: (str(value) if isinstance(value, Path) else value) for key, value in binding.items()})
            phase = 'config_binding'
            current = verify_config(settings.current, settings.current_sha256)
            proposed = verify_config(settings.proposed, settings.proposed_sha256)
            report.update(current=current, proposed=proposed)
            check_mode(settings, current, proposed)
            phase = 'preview_launch'
            argv = preview_command(binding['venv_python'], settings.current, settings.proposed)
            report['command'] = list(argv)
            result = launcher(argv, root, settings.child_timeout)
            stdout, stderr = bytes(result.get('stdout') or b''), bytes(result.get('stderr') or b'')
            report['child'] = {'exit_code': result.get('exit_code'), 'timed_out': bool(result.get('timed_out')),
                               'elapsed_ms': result.get('elapsed_ms'), 'stdout_bytes': len(stdout),
                               'stdout_sha256': hashlib.sha256(stdout).hexdigest(), 'stderr_bytes': len(stderr),
                               'stderr_sha256': hashlib.sha256(stderr).hexdigest()}
            write_new(root / STDERR_NAME, stderr[:OUTPUT_MAX_BYTES])
            report['stderr_path'] = STDERR_NAME
            if result.get('timed_out'):
                raise PreviewRefusal('PREVIEW_TIMED_OUT', 'The upgrade preview did not finish within its bound')
            if result.get('exit_code') != 0:
                raise PreviewRefusal('PREVIEW_EXIT_NONZERO', 'The upgrade preview exited with a nonzero code')
            phase = 'preview_output'
            if len(stdout) > OUTPUT_MAX_BYTES:
                raise PreviewRefusal('PREVIEW_OUTPUT_TOO_LARGE', 'The upgrade preview output exceeds its bound')
            try:
                preview = strict_json(stdout.decode('utf-8'))
                if not isinstance(preview, dict):
                    raise ValueError('not an object')
            except (UnicodeError, ValueError, RecursionError):
                raise PreviewRefusal('PREVIEW_OUTPUT_MALFORMED', 'The upgrade preview output is not one strict JSON object') from None
            report['preview_sha256'] = write_new(settings.output, stdout)
            report['preview_path'] = OUTPUT_NAME
            # The module refuses a configuration that changes while it reads; the bindings are re-checked after it.
            if (verify_config(settings.current, settings.current_sha256) != current
                    or verify_config(settings.proposed, settings.proposed_sha256) != proposed):
                raise PreviewRefusal('CONFIG_BINDING_DIFFERS', 'A bound configuration changed during the preview')
            phase = 'gate'
            gate = evaluate_gate(preview, settings.mode, current, proposed)
            report['gate'] = {'passed': gate['passed'], 'reasons': gate['reasons'], 'mode': settings.mode}
            report['summary'] = gate['summary']
            report['rollback_prerequisites'] = rollback_prerequisites(preview)
            report['status'] = STATUS_PASSED if gate['passed'] else STATUS_GATE_FAILED
        except BaseException as exc:
            report['status'] = STATUS_FAILED
            report['failure'] = safe_failure(exc, phase)
            if (report['failure']['reason'] in ('PREVIEW_OUTPUT_MALFORMED', 'PREVIEW_OUTPUT_TOO_LARGE', 'PREVIEW_TIMED_OUT')
                    and report.get('child') and report['child']['stdout_bytes'] and report['preview_path'] is None):
                try:
                    write_new(root / INVALID_STDOUT_NAME, stdout[:OUTPUT_MAX_BYTES])
                    report['invalid_stdout_path'] = INVALID_STDOUT_NAME
                except BaseException:
                    report['invalid_stdout_path'] = None
        finally:
            if report['status'] != STATUS_PASSED:
                held = {'schema': HELD_SCHEMA, 'attempt': settings.attempt, 'nonce': settings.nonce,
                        'status': report['status'],
                        'phase': report['failure']['phase'] if report['failure'] else 'gate',
                        'reasons': (list(report['gate']['reasons']) if report['status'] == STATUS_GATE_FAILED
                                    else [report['failure']['reason']]),
                        'failure': report['failure'], 'receipt_path': RECEIPT_NAME, 'preview_path': report['preview_path'],
                        'preview_sha256': report['preview_sha256'], 'stderr_path': report['stderr_path'],
                        'install_after_sha256': report['install_after_sha256'],
                        'current_sha256': settings.current_sha256, 'proposed_sha256': settings.proposed_sha256,
                        'config_mode': settings.mode, 'automatic_retry_allowed': False, 'requires_owner_decision': True,
                        'owner_options': list(OWNER_OPTIONS), 'created_at_unix_ms': int(time.time() * 1000)}
                try:
                    report['held_record_sha256'] = write_new(root / HELD_NAME, receipt_text(held))
                    report['held_record_path'] = HELD_NAME
                except BaseException:
                    report['held_record_path'] = None
            report['finished_at_unix_ms'] = int(time.time() * 1000)
            receipt.write(receipt_text(report))
            receipt.flush()
            os.fsync(receipt.fileno())
    return EXIT_CODES[report['status']]


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return run(settings_from_args(args))
    except BaseException as exc:
        reason = 'RECEIPT_EXISTS' if isinstance(exc, FileExistsError) else getattr(exc, 'reason', 'TRUSTED_PREFLIGHT')
        kind = re.sub('[^A-Za-z0-9_]', '', type(exc).__name__)[:80] or 'Exception'
        print(json.dumps({'status': 'PRE_RECEIPT_REFUSED', 'reason': reason, 'error_type': kind}), file=sys.stderr)
        return EXIT_REFUSED


if __name__ == '__main__':
    raise SystemExit(main())
