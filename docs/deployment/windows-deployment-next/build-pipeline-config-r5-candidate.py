"""Gated, deterministic r5 pipeline.json candidate builder (r5 sitting S9; build-manifest step 13).

Run ONLY with the installed r5 interpreter in isolated mode, so every gate uses the r5 cochem_pipeline:

  "C:\\Program Files\\CoChem\\Pipeline4.2.7-windows-20261011-r5\\.venv\\Scripts\\python.exe" -I
      build-pipeline-config-r5-candidate.py --commissioned <pipeline.json> --login-root <dir>
      --capture-root <dir> --isolation-root <dir> --mode attempt|held --out-dir <dir> [--stage-root <dir>]

Evidence binding (deploy audit B-F1), checked before any gate: the four producer roots carry ONE attempt. Each root name
is its producer's namespace with that attempt (NativeAuthSix4.2.7-windows-20261011-r4-v1-<a>-gemini,
AgyCapture4.2.7-windows-20261010-r4-v1-<a>-slot1-signed-in, AgyIsolation4.2.7-windows-20261011-r4-v1-<a> and its '-stage'
twin); the login series record, the capture, isolation and stage receipts and summaries all name the same nonzero 32-hex
attempt; each receipt and its summary carry one nonce; and each existing root lies directly under
C:\\Program Files\\CoChem with a protected ancestry up to C:\\Program Files (no link or reparse point, owner SYSTEM,
Administrators or TrustedInstaller, no write or replace right for any other SID: the house Assert-ProtectedPath rule).
A record that cannot be read is left to its gate, which then fails. Any binding refusal forces the held decision: every
gate reads 'not evaluated: the evidence binding refused the roots (<reasons>)' and decision.json evidence_binding records
the roots, the attempts read and the reasons.

Decision (ARMY_ADDENDUM_20261011 A4: Gemini is attempted; any gate failure degrades to held):
  G1 the six-slot gemini sign-in series ended with every slot REUSE_VERIFIED_SESSION;
  G2 the signed-in agy capture shows the SUCCESS 'models' envelope and every bound slug is in its catalog;
  G3 the A5 isolation evidence: verified receipt, R1 meets the 3B identity contract, disables_tools/mcp/hooks/
     subagents verdicts true, reroute scan clean, no isolation breach anywhere in the matrix;
  G4 the six-slot agent staging: every slot holds the pinned agent at both locations and lists exactly it;
  G5 the redacted A5 replay streams parse through the r5 worker.parse_gemini with reported_model == the routed
     canonical id and native_reported_model == binding.reports, and the r5 provider_command rebuilds the
     A5-evidenced argv for every bound route;
  G6 the r5 load_config accepts the candidate (validate_gemini_route_bindings runs because Gemini is no longer
     held): six workers, four slots, knowledge enabled; an order-preserving structural diff and a byte diff prove
     that only providers.gemini changed, routing.tiers unchanged (the retarget-warden-r5 Assert-R5Config view).
  All six pass -> GEMINI_CONTRACT: the commissioned bytes with ONLY the providers.gemini value replaced (same
  indentation and line-ending convention). Held mode, any gate failure or any builder exception ->
  GEMINI_HELD_COMMISSIONED_BYTES: the commissioned bytes byte for byte.

Outputs in --out-dir (must not exist or be empty; files are created exclusively, never overwritten):
  pipeline.json first, decision.json (schema cochem-r5-config-decision/1, ASCII, sorted keys) last as the commit marker.
Exit codes: 0 a valid decision was written (enabled or held); 2 bad command-line usage; 3 the commissioned file
is unreadable or differs from the 135cd9ec pin; 4 the out-dir is unusable (not a directory, a link, or not empty);
5 an output file could not be created or written. One JSON result line (schema cochem-r5-config-decision-result/1)
is printed: on stdout for 0, on stderr for 3/4/5 and a missing attempt-mode root (argparse prints its own usage text).

In --mode held the evidence roots are optional and never read. --stage-root defaults to '<isolation-root>-stage',
the root agy-isolation-evidence-r4-v1.ps1 -StageOnly uses for the same -Attempt; an explicit --stage-root must carry
the same attempt in the same namespace.

TEST-ONLY OVERRIDE: an in-process harness may monkeypatch the module constant COMMISSIONED_SHA256 (and replace
check_root_custody, because its fixture roots live in a temporary directory). There is deliberately no command-line flag
or environment variable that changes the commissioned pin or the custody rule.
Standard library (ctypes reads security descriptors, read only) plus the imported r5 cochem_pipeline only; no process is
started and nothing is written outside --out-dir. The G6 load_config check reads a private copy of the candidate in the
transient subdirectory --out-dir\\g6-load-config-check (created exclusively, removed before pipeline.json is written;
deploy audit B-F6: never %TEMP%).
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import sys
from types import SimpleNamespace

SCHEMA = 'cochem-r5-config-decision/1'
RESULT_SCHEMA = 'cochem-r5-config-decision-result/1'
OUTCOME_CONTRACT = 'GEMINI_CONTRACT'
OUTCOME_HELD = 'GEMINI_HELD_COMMISSIONED_BYTES'
MODES = ('attempt', 'held')
GATES = ('G1', 'G2', 'G3', 'G4', 'G5', 'G6')
CANDIDATE_FILE = 'pipeline.json'
DECISION_FILE = 'decision.json'
EXIT_DECISION, EXIT_USAGE, EXIT_COMMISSIONED, EXIT_OUT_DIR, EXIT_WRITE = 0, 2, 3, 4, 5

# C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\pipeline.json (Gemini held by integration_hold).
COMMISSIONED_SHA256 = '135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
COMMISSIONED_MAX_BYTES = 1024 * 1024
JSON_MAX_BYTES = 4 * 1024 * 1024
STREAM_MAX_BYTES = 16 * 1024 * 1024
REASON_MAX = 2000

# ----- the reviewed native contract (deploy-config-builder config_changes; resolved_cli_facts) -----
AGY_SHA256 = '38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741'
AGY_VERSION = '1.3.1'
AGENT_NAME = 'cochem-inference-only'
# The reviewed agent definition pinned by agy_isolation_evidence_r4_v1.py AGENT_SHA256 (478 bytes, re-pinned on
# 2026-10-11 from the spec's earlier bb2e66d7...); the A5 receipts must report exactly this digest.
AGENT_SHA256 = '5c0082d70d073263a56d748a46187008968c070d0efc7d5b7612c2fd61d11810'
AGENT_RELATIVES = ('.gemini/agents/cochem-inference-only/agent.md', '.gemini/config/agents/cochem-inference-only/agent.md')
PROTOCOL = 'agy-stream-json'
IDENTITY_POLICY = 'reported-model-equality'
ARGUMENTS = ('--agent', AGENT_NAME, '--input-format', 'stream-json', '--output-format', 'stream-json',
             '--model', '{model}', '--disable-slash-commands')
SUBSCRIPTION_PROBE = {'arguments': ['--output-format', 'json', 'models'], 'protocol': 'json-fields',
                      'expected': {'status': 'SUCCESS', 'command.name': 'models'}}
VERSION_ARGUMENTS = ('--version',)
EFFORT_ARGUMENTS = ('--effort', 'high')
DISABLES = ('disables_tools', 'disables_mcp', 'disables_hooks', 'disables_subagents')

# ----- routed Gemini targets (routing.tiers stay unchanged) and the binding rules -----
FLASH = 'gemini-3.8-flash'                   # tiers 1-3, effort null
FLASH_EXTENDED = 'gemini-3.8-flash:extended'  # tiers 4-6
PRO_HIGH = 'gemini-3.1-pro-preview:high'      # tiers 7-9: unbound in r5
PRIMARY_SLUG = 'gemini-3.8-flash-high'        # the R1-evidenced slug
EFFORT_NULL_SLUGS = ('gemini-3.8-flash-low', 'gemini-3.8-flash-medium', 'gemini-3.8-flash-high')
BINDING_SLUG = re.compile(r'[a-z0-9][a-z0-9.-]{0,127}')  # agy_protocol._SLUG
SLUG_EFFORT = re.compile(r'-(low|medium|high)$')         # agy_protocol._SLUG_EFFORT
RULE_R5 = 'R5_OWNER_EFFORT_NULL_SLUG_PASSED'
RULE_R1 = 'R1_PRIMARY_SLUG'
RULE_R2 = 'R2_SLUG_WITH_EFFORT_HIGH_PASSED'
RULE_R3 = 'R3_FAMILY_WITH_EFFORT_HIGH_ECHO_PASSED'
RULE_UNBOUND_FLASH = 'UNBOUND_NO_PASSING_R5_OR_R1'
RULE_UNBOUND_EXTENDED = 'UNBOUND_NO_PASSING_R2_OR_R3'
RULE_UNBOUND_R3_ECHO = 'UNBOUND_R3_ECHO_NOT_A_HIGH_SLUG'
RULE_UNBOUND_PRO = 'UNBOUND_IN_R5_NO_PRO_EVIDENCE'
RUN_CHECKS = ('exited_zero', 'init_present', 'stream_well_formed', 'tools_empty', 'agent_matches', 'model_matches',
              'no_tool_steps', 'no_subagent_steps', 'only_allowed_step_types', 'step_models_match', 'result_success',
              'num_turns_one', 'result_model_absent_or_equal', 'no_stderr_markers')
SLOTS = tuple(f'slot{number}' for number in range(1, 7))

# ----- evidence files, exactly as the producing scripts lay them out -----
LOGIN_COMPLETE = 'series-complete.json'      # login-six-workers-status-first-r4-v1.ps1 -Provider gemini
LOGIN_STOPS = ('series-held.json', 'series-paused.json')
CAPTURE_RECEIPT = 'capture-receipt.json'     # agy_status_capture_r4_v1.py, stage signed-in
CAPTURE_SUMMARY = 'capture-summary.json'     # agy-status-capture-r4-v1.ps1
CAPTURE_HELD = 'capture-held.json'
CAPTURE_P2_STDOUT = 'raw/P2.stdout'
ISOLATION_RECEIPT = 'isolation-receipt.json'  # agy_isolation_evidence_r4_v1.py --mode evidence
ISOLATION_SUMMARY = 'isolation-summary.json'  # agy-isolation-evidence-r4-v1.ps1 -Slot slot1
ISOLATION_HELD = 'isolation-held.json'
STAGE_RECEIPT = 'stage-receipt.json'          # agy_isolation_evidence_r4_v1.py --mode stage
STAGE_SUMMARY = 'stage-summary.json'          # agy-isolation-evidence-r4-v1.ps1 -StageOnly
STAGE_HELD = 'stage-held.json'
STAGE_ROOT_SUFFIX = '-stage'
PIPELINE_MODULES = ('__init__.py', 'agy_protocol.py', 'config.py', 'worker.py', 'native_effort.py',
                    'inference_policy.py', 'provider_integration.py', 'routing.py')
G6_SCRATCH = 'g6-load-config-check'

# ----- evidence binding (deploy audit B-F1): one attempt, the producers' namespaces, protected custody -----
# The producers' fixed namespaces (login-six-workers-status-first-r4-v1.ps1 seriesNamespaceDate 20261011,
# agy-status-capture-r4-v1.ps1 captureNamespaceDate 20261010, agy-isolation-evidence-r4-v1.ps1 isolationNamespaceDate
# 20261011, all under C:\Program Files\CoChem); the harness compares these with the producers' sources.
EVIDENCE_BASE = 'C:\\Program Files\\CoChem'
PROTECTED_TOP = 'C:\\Program Files'
ROOT_NAMESPACES = (
    ('login', re.compile(r'NativeAuthSix4\.2\.7-windows-20261011-r4-v1-([a-f0-9]{32})-gemini')),
    ('capture', re.compile(r'AgyCapture4\.2\.7-windows-20261010-r4-v1-([a-f0-9]{32})-slot1-signed-in')),
    ('isolation', re.compile(r'AgyIsolation4\.2\.7-windows-20261011-r4-v1-([a-f0-9]{32})')),
    ('stage', re.compile(r'AgyIsolation4\.2\.7-windows-20261011-r4-v1-([a-f0-9]{32})-stage')),
)
ATTEMPT_RECORDS = (
    ('login', 'login.series_complete', LOGIN_COMPLETE),
    ('capture', 'capture.receipt', CAPTURE_RECEIPT), ('capture', 'capture.summary', CAPTURE_SUMMARY),
    ('isolation', 'isolation.receipt', ISOLATION_RECEIPT), ('isolation', 'isolation.summary', ISOLATION_SUMMARY),
    ('stage', 'stage.receipt', STAGE_RECEIPT), ('stage', 'stage.summary', STAGE_SUMMARY),
)
HEX32 = re.compile(r'[a-f0-9]{32}')
ZERO_ATTEMPT = '0' * 32
# The house Assert-ProtectedPath rule (scripts/stage_aetherdesk_427_payloads.ps1): trusted owners and writers are SYSTEM,
# Administrators and TrustedInstaller; any other SID with one of these rights on a non-inherit-only allow entry may write
# or replace the path (GENERIC_ALL|GENERIC_WRITE|WRITE_OWNER|WRITE_DAC|DELETE|WRITE_ATTRIBUTES|WRITE_EA|APPEND|WRITE_DATA).
TRUSTED_SIDS = frozenset(('S-1-5-18', 'S-1-5-32-544', 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464'))
WRITE_OR_REPLACE_MASK = 0x500D0116
INHERIT_ONLY_ACE = 0x08
ALLOW_ACE_TYPES = (0x0, 0x9)   # ACCESS_ALLOWED_ACE and ACCESS_ALLOWED_CALLBACK_ACE (Mask at +4, SID at +8)
DENY_ACE_TYPES = (0x1, 0xA)    # deny entries only remove rights


class Refusal(Exception):
    """Even the held output cannot be produced; the process exits non-zero."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class GateFailure(Exception):
    """Evidence does not satisfy a gate; the outcome degrades to held (never a builder error)."""


# Data-shaped errors inside a gate are gate failures; anything else (for example RuntimeError) is a builder error.
GATE_ERRORS = (GateFailure, ValueError, TypeError, KeyError, IndexError, AttributeError, OSError, UnicodeError,
               RecursionError)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def bounded(text):
    text = str(text)
    return text if len(text) <= REASON_MAX else text[:REASON_MAX - 3] + '...'


def describe(error):
    if isinstance(error, GateFailure):
        return bounded(error)
    return bounded(f'{type(error).__name__}: {error}')


def dig(value, *path):
    for key in path:
        if isinstance(key, int):
            if not isinstance(value, list) or not -len(value) <= key < len(value):
                return None
        elif not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def exact_int(value, expected):
    return type(value) is int and value == expected


class Checks:
    """Collects every failed expectation of one gate so decision.json names them all."""

    def __init__(self):
        self.failures = []

    def expect(self, condition, message):
        if not condition:
            self.failures.append(message)
        return bool(condition)

    def done(self):
        if self.failures:
            raise GateFailure('; '.join(self.failures))


def strict_json(data, label):
    try:
        text = data.decode('utf-8-sig')
    except UnicodeError as exc:
        raise GateFailure(f'{label} is not UTF-8 text') from exc

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise GateFailure(f'{label} has a duplicate JSON member {key!r}')
            result[key] = value
        return result

    def constant(name):
        raise GateFailure(f'{label} has a non-finite JSON constant {name}')
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, RecursionError) as exc:
        raise GateFailure(f'{label} is not valid JSON: {exc}') from exc


def read_regular(path, maximum, label):
    try:
        info = os.lstat(path)
    except FileNotFoundError as exc:
        raise GateFailure(f'{label} is missing: {path}') from exc
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise GateFailure(f'{label} is a link or reparse point: {path}')
    if not stat.S_ISREG(info.st_mode):
        raise GateFailure(f'{label} is not a regular file: {path}')
    with open(path, 'rb') as handle:
        data = handle.read(maximum + 1)
    if len(data) > maximum:
        raise GateFailure(f'{label} exceeds its {maximum}-byte bound: {path}')
    return data


class Evidence:
    """Every evidence file is read once; its digest is recorded and the same bytes are parsed. A later read of the same
    key (the evidence binding reads the attempt records before their gates do) returns those bytes or repeats the first
    failure, so a binding and a gate can never judge different bytes."""

    def __init__(self):
        self.files = {}
        self._reads = {}

    def read(self, key, path, maximum=JSON_MAX_BYTES):
        earlier = self._reads.get(key)
        if earlier is not None:
            if earlier[0] != path:
                raise RuntimeError(f'{key} was first read from {earlier[0]}, not {path}')
            if earlier[1] is not None:
                raise earlier[1]
            return earlier[2], earlier[3]
        try:
            data = read_regular(path, maximum, key)
        except GATE_ERRORS as exc:
            self._reads[key] = (path, exc, None, None)
            raise
        digest = sha256_bytes(data)
        self._reads[key] = (path, None, data, digest)
        self.files[key] = {'path': path, 'sha256': digest, 'bytes': len(data)}
        return data, digest

    def json(self, key, path):
        data, digest = self.read(key, path)
        return strict_json(data, key), digest


def absent(checks, root, name):
    checks.expect(not os.path.lexists(os.path.join(root, name)), f'{name} is present in {root}')


# ----- evidence binding (B-F1) -----

def security_descriptor(path):
    """(owner SID, [(ace type, ace flags, access mask or None, SID or None)]) of one file or directory: a read-only
    GetNamedSecurityInfoW of the owner and the DACL."""
    import ctypes
    from ctypes import wintypes
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    pointer = ctypes.POINTER(ctypes.c_void_p)
    get_named = advapi.GetNamedSecurityInfoW
    get_named.restype, get_named.argtypes = wintypes.DWORD, [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, pointer, pointer,
                                                              pointer, pointer, pointer]
    acl_information = advapi.GetAclInformation
    acl_information.restype, acl_information.argtypes = wintypes.BOOL, [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_int]
    get_ace = advapi.GetAce
    get_ace.restype, get_ace.argtypes = wintypes.BOOL, [ctypes.c_void_p, wintypes.DWORD, pointer]
    sid_to_text = advapi.ConvertSidToStringSidW
    sid_to_text.restype, sid_to_text.argtypes = wintypes.BOOL, [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    local_free = kernel.LocalFree
    local_free.restype, local_free.argtypes = ctypes.c_void_p, [ctypes.c_void_p]

    class AclSize(ctypes.Structure):
        _fields_ = [('AceCount', wintypes.DWORD), ('AclBytesInUse', wintypes.DWORD), ('AclBytesFree', wintypes.DWORD)]

    def sid_text(sid):
        text = wintypes.LPWSTR()
        if not sid or not sid_to_text(sid, ctypes.byref(text)):
            raise GateFailure(f'cannot read a SID in the security descriptor of {path} (Windows error {ctypes.get_last_error()})')
        try:
            return text.value
        finally:
            local_free(ctypes.cast(text, ctypes.c_void_p))

    owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    status = get_named(path, 1, 0x1 | 0x4, ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor))
    if status:
        raise GateFailure(f'cannot read the security descriptor of {path} (Windows error {status})')
    try:
        if not dacl.value:
            raise GateFailure(f'{path} has a null DACL, which lets every user write it')
        size = AclSize()
        if not acl_information(dacl, ctypes.byref(size), ctypes.sizeof(size), 2):
            raise GateFailure(f'cannot read the DACL of {path} (Windows error {ctypes.get_last_error()})')
        entries = []
        for index in range(size.AceCount):
            ace = ctypes.c_void_p()
            if not get_ace(dacl, index, ctypes.byref(ace)):
                raise GateFailure(f'cannot read an access entry of {path} (Windows error {ctypes.get_last_error()})')
            kind, flags = ctypes.c_ubyte.from_address(ace.value).value, ctypes.c_ubyte.from_address(ace.value + 1).value
            if kind in ALLOW_ACE_TYPES or kind in DENY_ACE_TYPES:
                entries.append((kind, flags, wintypes.DWORD.from_address(ace.value + 4).value, sid_text(ace.value + 8)))
            else:
                entries.append((kind, flags, None, None))
        return sid_text(owner.value), entries
    finally:
        local_free(descriptor)


def protected_ancestry(path, reader=None):
    """The house Assert-ProtectedPath rule, from path up to and including C:\\Program Files: no link or reparse point,
    a trusted owner, and no allow entry (not inherit-only) that gives another SID a write or replace right."""
    reader = security_descriptor if reader is None else reader
    current = os.path.abspath(path)
    top = os.path.normcase(PROTECTED_TOP)
    while True:
        info = os.lstat(current)
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise GateFailure(f'the protected ancestry contains a link or reparse point: {current}')
        owner, entries = reader(current)
        if owner not in TRUSTED_SIDS:
            raise GateFailure(f'untrusted owner {owner} of {current}')
        for kind, flags, mask, sid in entries:
            if kind in DENY_ACE_TYPES or flags & INHERIT_ONLY_ACE:
                continue
            if kind not in ALLOW_ACE_TYPES:
                raise GateFailure(f'unexpected access entry type {kind} on {current}')
            if sid not in TRUSTED_SIDS and mask & WRITE_OR_REPLACE_MASK:
                raise GateFailure(f'{sid} may write or replace {current}')
        if os.path.normcase(current) == top:
            return
        parent = os.path.dirname(current)
        if parent == current:
            raise GateFailure(f'the ancestry of {path} does not reach {PROTECTED_TOP}')
        current = parent


def check_root_custody(root):
    """A producer root lies directly under C:\\Program Files\\CoChem with a protected ancestry (raises GateFailure)."""
    if os.path.normcase(os.path.dirname(os.path.abspath(root))) != os.path.normcase(EVIDENCE_BASE):
        raise GateFailure(f'{root} is not directly under {EVIDENCE_BASE}')
    protected_ancestry(root)


def bind_evidence(roots, evidence):
    """B-F1: one attempt across the four producer roots and their seven attempt records, each root in its producer's
    namespace and in protected custody, one nonce per receipt and summary. A record that cannot be read is left to its
    gate (which then fails); everything that can be read must agree."""
    reasons, sources = [], []
    binding = {'passed': False, 'attempt': None, 'reasons': reasons, 'roots': {}, 'records': {}}
    for name, pattern in ROOT_NAMESPACES:
        root = roots[name]
        match = pattern.fullmatch(os.path.basename(root))
        entry = {'path': root, 'namespace_attempt': match.group(1) if match else None, 'custody': 'absent'}
        binding['roots'][name] = entry
        if match:
            sources.append((f'{name} root name', match.group(1)))
        else:
            reasons.append(f'the {name} root name {os.path.basename(root)!r} is not the producer namespace {pattern.pattern}')
        if not os.path.lexists(root):
            continue
        try:
            check_root_custody(root)
        except GATE_ERRORS as exc:
            entry['custody'] = 'refused'
            reasons.append(f'the {name} root is not in protected custody: {describe(exc)}')
        else:
            entry['custody'] = 'protected'
    nonces = {}
    for name, key, filename in ATTEMPT_RECORDS:
        try:
            value, _ = evidence.json(key, os.path.join(roots[name], filename))
        except GATE_ERRORS:
            binding['records'][key] = None
            continue
        attempt, nonce = dig(value, 'attempt'), dig(value, 'nonce')
        binding['records'][key] = {'attempt': attempt if isinstance(attempt, str) else None,
                                   'nonce': nonce if isinstance(nonce, str) else None}
        if isinstance(attempt, str) and HEX32.fullmatch(attempt):
            sources.append((key, attempt))
        else:
            reasons.append(f'{key} carries no lowercase 32-hex attempt')
        if name != 'login':
            nonces.setdefault(name, []).append(nonce)
    distinct = sorted({value for _, value in sources})
    if len(distinct) > 1:
        reasons.append('the evidence names more than one attempt: ' + '; '.join(f'{source} {value}' for source, value in sources))
    elif distinct == [ZERO_ATTEMPT]:
        reasons.append('the all-zero attempt is the producers\' preview attempt, never evidence')
    for name, values in nonces.items():
        if len(values) == 2 and not (isinstance(values[0], str) and HEX32.fullmatch(values[0]) and values[0] == values[1]):
            reasons.append(f'the {name} receipt and summary do not carry one 32-hex nonce')
    binding['attempt'] = distinct[0] if len(distinct) == 1 else None
    binding['passed'] = not reasons
    return binding


# ----- G1: six-slot sign-in series -----

def gate_login(root, evidence):
    series, digest = evidence.json('login.series_complete', os.path.join(root, LOGIN_COMPLETE))
    c = Checks()
    for name in LOGIN_STOPS:
        absent(c, root, name)
    c.expect(dig(series, 'schema') == 'cochem-six-worker-status-first-result/1',
             'series-complete.json schema is not cochem-six-worker-status-first-result/1')
    c.expect(dig(series, 'provider') == 'gemini', 'the sign-in series is not the gemini provider series')
    c.expect(dig(series, 'status') == 'SIX_CONFIGURED_WORKERS_SUBSCRIPTION_AUTHENTICATION_VERIFIED',
             'series status is not SIX_CONFIGURED_WORKERS_SUBSCRIPTION_AUTHENTICATION_VERIFIED')
    c.expect(dig(series, 'all_slots_reuse_verified') is True, 'all_slots_reuse_verified is not true')
    c.expect(exact_int(dig(series, 'selected_workers_verified'), 6), 'selected_workers_verified is not 6')
    rows = dig(series, 'slots')
    if c.expect(isinstance(rows, list) and len(rows) == 6, 'slots is not a list of six rows'):
        by = {row['slot']: row for row in rows if isinstance(row, dict) and isinstance(row.get('slot'), str)}
        c.expect(set(by) == set(SLOTS), 'slots does not list slot1..slot6 exactly once')
        for slot in SLOTS:
            row = by.get(slot)
            c.expect(dig(row, 'final_decision') == 'REUSE_VERIFIED_SESSION' and dig(row, 'reuse_verified') is True,
                     f'{slot} did not end REUSE_VERIFIED_SESSION')
    c.done()
    return f'six slots REUSE_VERIFIED_SESSION (series-complete.json sha256 {digest})'


# ----- G2: signed-in capture (envelope part; the slug part runs after binding selection) -----

def load_capture(root, evidence):
    receipt, receipt_sha = evidence.json('capture.receipt', os.path.join(root, CAPTURE_RECEIPT))
    summary, _ = evidence.json('capture.summary', os.path.join(root, CAPTURE_SUMMARY))
    c = Checks()
    absent(c, root, CAPTURE_HELD)
    c.expect(dig(receipt, 'schema') == 'cochem-agy-status-capture/1', 'capture receipt schema is not cochem-agy-status-capture/1')
    c.expect(dig(receipt, 'slot') == 'slot1' and dig(receipt, 'stage') == 'signed-in', 'capture receipt is not the slot1 signed-in stage')
    c.expect(dig(receipt, 'status') == 'CAPTURE_COMPLETE', 'capture status is not CAPTURE_COMPLETE')
    c.expect(dig(receipt, 'gate', 'passed') is True and dig(receipt, 'gate', 'reasons') == [], 'capture gate did not pass')
    c.expect(dig(receipt, 'native_executable_sha256_before') == AGY_SHA256 and dig(receipt, 'native_executable_sha256_after') == AGY_SHA256,
             'capture does not bind the pinned agy.exe')
    c.expect(dig(receipt, 'native_version_at_pin') == AGY_VERSION, 'capture does not bind agy 1.3.1')
    probes = dig(receipt, 'probes')
    found = [probe for probe in probes if dig(probe, 'id') == 'P2'] if isinstance(probes, list) else []
    catalog = []
    if c.expect(len(found) == 1, 'capture receipt does not carry exactly one P2 probe'):
        p2 = found[0]
        c.expect(dig(p2, 'outcome') == 'exited' and exact_int(dig(p2, 'exit_code'), 0), 'P2 did not exit 0')
        c.expect(dig(p2, 'classification', 'status_value') == 'SUCCESS', 'P2 envelope status is not SUCCESS')
        c.expect(dig(p2, 'classification', 'command_name') == 'models', "P2 envelope command.name is not 'models'")
        c.expect(dig(p2, 'classification', 'gemini_row_present') is True, 'P2 lists no gemini- model')
        listed = dig(p2, 'classification', 'model_ids')
        c.expect(isinstance(listed, list), 'P2 classification has no model_ids list')
        if c.expect(dig(p2, 'raw_path', 'stdout') == CAPTURE_P2_STDOUT, 'P2 raw stdout is not raw/P2.stdout'):
            raw, raw_sha = evidence.read('capture.raw.P2.stdout', os.path.join(root, 'raw', 'P2.stdout'), STREAM_MAX_BYTES)
            c.expect(raw_sha == dig(p2, 'stdout', 'sha256'), 'raw/P2.stdout differs from the digest in the capture receipt')
            envelope = strict_json(raw, 'capture.raw.P2.stdout')
            models = dig(envelope, 'command', 'data', 'models')
            c.expect(dig(envelope, 'status') == 'SUCCESS' and dig(envelope, 'command', 'name') == 'models',
                     'raw P2 envelope is not status SUCCESS with command.name models')
            if c.expect(isinstance(models, list) and models and all(
                    isinstance(row, dict) and isinstance(row.get('id'), str) and isinstance(row.get('label'), str) for row in models),
                    'raw P2 envelope has no {id, label} model list'):
                catalog = sorted({row['id'] for row in models})
                c.expect(any(slug.startswith('gemini-') for slug in catalog), 'the signed-in catalog has no gemini- id')
                c.expect(isinstance(listed, list) and set(item for item in listed if isinstance(item, str)) <= set(catalog),
                         'the receipt model_ids are not drawn from the raw catalog')
    c.expect(dig(summary, 'schema') == 'cochem-agy-status-capture-result/1', 'capture summary schema is not cochem-agy-status-capture-result/1')
    c.expect(dig(summary, 'decision') == 'COMPLETE' and dig(summary, 'gate', 'passed') is True and dig(summary, 'series_stop') is False,
             'capture summary is not COMPLETE with a passed gate')
    c.expect(dig(summary, 'stage') == 'signed-in' and dig(summary, 'slot') == 'slot1', 'capture summary is not slot1 signed-in')
    c.expect(dig(summary, 'receipt_sha256') == receipt_sha, 'capture summary does not bind this capture receipt')
    c.done()
    return SimpleNamespace(catalog=catalog, receipt_sha256=receipt_sha)


def gate_catalog(capture, selection):
    c = Checks()
    for key, rule in selection.rules.items():
        if rule['run'] is None:
            continue
        c.expect(rule['reports'] in capture.catalog, f"{key}: reported slug {rule['reports']} is not in the signed-in catalog")
        # The R3 family form binds the family id as argv by rule; the catalog never lists a family id.
        if not (rule['rule'] == RULE_R3 and rule['argv'] == FLASH):
            c.expect(rule['argv'] in capture.catalog, f"{key}: argv slug {rule['argv']} is not in the signed-in catalog")
    c.done()
    listed = sorted({rule[part] for rule in selection.rules.values() if rule['run'] for part in ('argv', 'reports')
                     if not (part == 'argv' and rule['rule'] == RULE_R3 and rule['argv'] == FLASH)})
    family = ' (R3 family argv gemini-3.8-flash evidenced by the accepted R3 run)' if any(
        rule['rule'] == RULE_R3 for rule in selection.rules.values()) else ''
    return (f"SUCCESS models envelope (capture receipt sha256 {capture.receipt_sha256}); bound slugs "
            f"{', '.join(listed)} are in the signed-in catalog of {len(capture.catalog)} ids{family}")


# ----- G3: A5 isolation evidence -----

def load_isolation(root, evidence):
    receipt_path = os.path.join(root, ISOLATION_RECEIPT)
    receipt, digest = evidence.json('isolation.receipt', receipt_path)
    if not isinstance(receipt, dict):
        raise GateFailure('isolation receipt is not a JSON object')
    return SimpleNamespace(root=root, receipt=receipt, receipt_path=receipt_path, receipt_sha256=digest,
                           capability_reference=f'{receipt_path}#{digest}')


def evidenced_argv(executable, model, extra=()):
    return [executable, *(model if arg == '{model}' else arg for arg in ARGUMENTS), *extra]


def gate_isolation(iso, evidence, executable):
    receipt, root = iso.receipt, iso.root
    summary, _ = evidence.json('isolation.summary', os.path.join(root, ISOLATION_SUMMARY))
    c = Checks()
    absent(c, root, ISOLATION_HELD)
    c.expect(receipt.get('schema') == 'cochem-agy-isolation-evidence/1' and receipt.get('mode') == 'evidence',
             'isolation receipt is not cochem-agy-isolation-evidence/1 evidence mode')
    c.expect(receipt.get('slot') == 'slot1' and receipt.get('gemini_gate') == 'G3', 'isolation receipt is not the slot1 G3 evidence')
    c.expect(receipt.get('status') == 'EVIDENCE_COMPLETE', 'isolation status is not EVIDENCE_COMPLETE')
    c.expect(dig(receipt, 'gate', 'passed') is True and dig(receipt, 'gate', 'reasons') == [],
             f"isolation gate did not pass: {dig(receipt, 'gate', 'reasons')}")
    c.expect(dig(receipt, 'precheck', 'passed') is True, 'isolation pre-check did not pass')
    c.expect(receipt.get('native_executable_sha256_before') == AGY_SHA256 and receipt.get('native_executable_sha256_after') == AGY_SHA256,
             'isolation evidence does not bind the pinned agy.exe')
    c.expect(receipt.get('native_version_at_pin') == AGY_VERSION, 'isolation evidence does not bind agy 1.3.1')
    c.expect(receipt.get('production_argument_template') == list(ARGUMENTS) and receipt.get('production_arguments_validated') is True,
             'isolation evidence did not validate the production argument template')
    for key in ('cleanup_verified', 'runtime_custody_verified', 'daemon_states_verified_before_and_after'):
        c.expect(receipt.get(key) is True, f'isolation receipt {key} is not true')
    c.expect(dig(receipt, 'agent', 'source_sha256') == AGENT_SHA256, 'isolation evidence did not stage the pinned agent')
    c.expect(dig(receipt, 'agent', 'shadows_found') == [] and dig(receipt, 'agent', 'verified_before_each_launch') is True,
             'the staged agent was shadowed or not re-verified before each launch')
    c.expect(dig(receipt, 'environment_attestation', 'flagged_names') == [], 'the worker environment carries flagged agy/gemini variables')
    runs = receipt.get('runs')
    runs = runs if isinstance(runs, list) else []
    r1 = [run for run in runs if dig(run, 'id') == 'R1']
    if c.expect(len(r1) == 1, 'isolation receipt does not carry exactly one R1 run'):
        run = r1[0]
        c.expect(run.get('requested_model') == PRIMARY_SLUG and run.get('extra_arguments') == [], f'R1 did not request {PRIMARY_SLUG}')
        c.expect(run.get('argv') == evidenced_argv(executable, PRIMARY_SLUG),
                 'R1 argv is not the production argv of the commissioned agy.exe')
        c.expect(run.get('outcome') == 'exited' and exact_int(run.get('exit_code'), 0), 'R1 did not exit 0')
        failed = [name for name in RUN_CHECKS if dig(run, 'checks', name) is not True]
        c.expect(not failed, f"R1 failed checks: {', '.join(failed)}")
        c.expect(dig(run, 'checks', 'passes_contract') is True and dig(run, 'checks', 'accepted') is True,
                 'R1 does not pass the 3B identity contract')
        init = dig(run, 'classification', 'stream', 'init')
        c.expect(dig(init, 'model') == PRIMARY_SLUG and dig(init, 'agent') == AGENT_NAME and exact_int(dig(init, 'tools_count'), 0),
                 'R1 init is not model gemini-3.8-flash-high, agent cochem-inference-only, tools []')
        result = dig(run, 'classification', 'stream', 'result')
        c.expect(dig(result, 'status') == 'SUCCESS' and exact_int(dig(result, 'num_turns'), 1), 'R1 result is not SUCCESS in one turn')
    breached = [dig(run, 'id') for run in runs if dig(run, 'checks', 'isolation_breach') is not False and dig(run, 'checks') is not None]
    c.expect(not breached, f'isolation breach in runs {breached}')
    verdict = receipt.get('isolation_verdict')
    for key in DISABLES:
        c.expect(dig(verdict, key) is True, f'isolation_verdict.{key} is not true')
    c.expect(exact_int(dig(verdict, 'profiles_considered'), 6), 'isolation_verdict did not consider six worker profiles')
    identity = receipt.get('identity_verdict')
    c.expect(dig(identity, 'primary_model') == PRIMARY_SLUG, 'identity_verdict primary model differs')
    c.expect(dig(identity, 'slug_form_accepted') is True and dig(identity, 'slug_form_passes_contract') is True,
             'identity_verdict: the slug form did not pass')
    c.expect(dig(identity, 'reroute_scan_clean') is True, 'identity_verdict: the reroute scan is not clean')
    c.expect(dig(summary, 'schema') == 'cochem-agy-isolation-evidence-result/1',
             'isolation summary schema is not cochem-agy-isolation-evidence-result/1')
    c.expect(dig(summary, 'decision') == 'COMPLETE' and dig(summary, 'gemini_outcome') == 'PASSED',
             'isolation summary is not COMPLETE/PASSED')
    c.expect(dig(summary, 'receipt_sha256') == iso.receipt_sha256, 'isolation summary does not bind this receipt')
    reference = dig(summary, 'capability_reference')
    path, _, digest = reference.rpartition('#') if isinstance(reference, str) else ('', '', '')
    c.expect(digest == iso.receipt_sha256 and os.path.normcase(os.path.normpath(path)) == os.path.normcase(iso.receipt_path),
             'isolation summary capability_reference does not name this receipt')
    c.done()
    basis = dig(verdict, 'model_fallback_basis')
    return (f'R1 meets the 3B contract; disables_tools/mcp/hooks/subagents true; reroute scan clean; '
            f'model_fallback_basis {basis} (3B rule applied); receipt sha256 {iso.receipt_sha256}')


# ----- G4: six-slot agent staging -----

def gate_stage(root, evidence):
    receipt, digest = evidence.json('stage.receipt', os.path.join(root, STAGE_RECEIPT))
    summary, _ = evidence.json('stage.summary', os.path.join(root, STAGE_SUMMARY))
    c = Checks()
    absent(c, root, STAGE_HELD)
    c.expect(dig(receipt, 'schema') == 'cochem-agy-agent-staging/1' and dig(receipt, 'mode') == 'stage'
             and dig(receipt, 'gemini_gate') == 'G4', 'stage receipt is not cochem-agy-agent-staging/1 G4')
    c.expect(dig(receipt, 'status') == 'STAGING_COMPLETE', 'staging status is not STAGING_COMPLETE')
    c.expect(dig(receipt, 'gate', 'passed') is True and dig(receipt, 'gate', 'reasons') == [],
             f"staging gate did not pass: {dig(receipt, 'gate', 'reasons')}")
    c.expect(dig(receipt, 'agent', 'source_sha256') == AGENT_SHA256, 'staging did not use the pinned agent')
    c.expect(dig(receipt, 'native_executable_sha256_before') == AGY_SHA256 and dig(receipt, 'native_executable_sha256_after') == AGY_SHA256,
             'staging does not bind the pinned agy.exe')
    c.expect(dig(receipt, 'cleanup_verified') is True, 'staging cleanup is not verified')
    c.expect(dig(receipt, 'slots_skipped') == [], 'staging skipped slots')
    c.expect(dig(receipt, 'isolation_inventory_clear') is True, 'the six-profile inventory is not clear of hooks, MCP, plugins and skills')
    slots = dig(receipt, 'slots')
    entries = {entry['slot']: entry for entry in slots if isinstance(entry, dict) and isinstance(entry.get('slot'), str)} \
        if isinstance(slots, list) else {}
    c.expect(isinstance(slots, list) and len(slots) == 6 and set(entries) == set(SLOTS), 'staging does not list slot1..slot6 exactly once')
    for slot in SLOTS:
        entry = entries.get(slot)
        c.expect(dig(receipt, 'gate', 'slots', slot, 'passed') is True, f'{slot}: staging gate did not pass')
        staged = dig(entry, 'staged')
        c.expect(isinstance(staged, list) and len(staged) == 2 and all(
            dig(record, 'relative') == relative and dig(record, 'sha256') == AGENT_SHA256 and dig(record, 'acl_verified') is True
            for record, relative in zip(staged, AGENT_RELATIVES)), f'{slot}: the pinned agent is not staged at both locations')
        c.expect(dig(entry, 'agent_sha256_after_listing') == [AGENT_SHA256] * 2, f'{slot}: agent digest after listing differs')
        c.expect(dig(entry, 'shadows_found') == [], f'{slot}: a same-name agent shadow was found')
        c.expect(dig(entry, 'listing', 'passed') is True, f'{slot}: the agent listing did not pass')
        probes = {dig(probe, 'id'): probe for probe in (dig(entry, 'probes') or []) if isinstance(dig(probe, 'id'), str)}
        for probe_id, json_form in (('PC3', True), ('PC4', False)):
            probe = probes.get(probe_id)
            ok = (dig(probe, 'outcome') == 'exited' and exact_int(dig(probe, 'exit_code'), 0)
                  and dig(probe, 'classification', 'agents') == [AGENT_NAME]
                  and exact_int(dig(probe, 'classification', 'agents_count'), 1)
                  and exact_int(dig(probe, 'classification', 'agents_unlisted'), 0))
            if json_form:
                ok = ok and dig(probe, 'classification', 'status_value') == 'SUCCESS' and dig(probe, 'classification', 'command_name') == 'agents'
            c.expect(ok, f'{slot}: {probe_id} does not list exactly {AGENT_NAME}')
    c.expect(dig(summary, 'schema') == 'cochem-agy-agent-staging-result/1', 'stage summary schema is not cochem-agy-agent-staging-result/1')
    c.expect(dig(summary, 'decision') == 'COMPLETE' and dig(summary, 'gemini_outcome') == 'PASSED', 'stage summary is not COMPLETE/PASSED')
    c.expect(dig(summary, 'receipt_sha256') == digest, 'stage summary does not bind this stage receipt')
    c.done()
    return f'six slots stage {AGENT_NAME} at both locations and list exactly it (stage receipt sha256 {digest})'


# ----- binding selection (deploy-config-builder config_changes, 'GEMINI model_bindings') -----

def passes_contract(run, model, extra):
    return (isinstance(run, dict) and run.get('requested_model') == model and run.get('extra_arguments') == list(extra)
            and run.get('outcome') == 'exited' and exact_int(run.get('exit_code'), 0)
            and dig(run, 'checks', 'passes_contract') is True and dig(run, 'checks', 'isolation_breach') is False
            and dig(run, 'classification', 'stream', 'init', 'model') == model)


def effort_contract_entry(capability_reference):
    return {'arguments': list(EFFORT_ARGUMENTS), 'version_arguments': list(VERSION_ARGUMENTS), 'executable_sha256': AGY_SHA256,
            'version': AGY_VERSION, 'capability_reference': capability_reference, 'native_metadata': None, 'thinking_enabled': None}


def select_bindings(receipt, capability_reference):
    """Deterministic model_bindings and effort_contracts from the A5 receipt (rule order is the precedence)."""
    runs = {}
    for run in receipt.get('runs') or []:
        if isinstance(run, dict) and isinstance(run.get('id'), str) and run['id'] not in runs:
            runs[run['id']] = run
    identity = receipt.get('identity_verdict') if isinstance(receipt.get('identity_verdict'), dict) else {}
    bindings, contracts, rules = {}, {}, {}

    def bind(key, rule, run_id, argv, reports):
        bindings[key] = argv if argv == reports else {'argv': argv, 'reports': reports}
        rules[key] = {'rule': rule, 'run': run_id, 'argv': argv, 'reports': reports}
    # Tiers 1-3 (effort null): the owner's pre-declared slug only if R5 passed with it, else the R1 slug.
    owner = receipt.get('effort_null_slug')
    effort_null = identity.get('effort_null') if isinstance(identity.get('effort_null'), dict) else {}
    if (owner in EFFORT_NULL_SLUGS and passes_contract(runs.get('R5'), owner, ()) and effort_null.get('slug') == owner
            and effort_null.get('executed') is True and effort_null.get('passed') is True and effort_null.get('init_model') == owner):
        bind(FLASH, RULE_R5, 'R5', owner, owner)
    elif passes_contract(runs.get('R1'), PRIMARY_SLUG, ()) and identity.get('slug_form_passes_contract') is True:
        bind(FLASH, RULE_R1, 'R1', PRIMARY_SLUG, PRIMARY_SLUG)
    else:
        rules[FLASH] = {'rule': RULE_UNBOUND_FLASH, 'run': None, 'argv': None, 'reports': None}
    # Tiers 4-6 (extended): R2 slug + --effort high first, then R3 family + --effort high with its init.model echo.
    r3 = runs.get('R3')
    echo = identity.get('family_with_effort_init_model')
    if passes_contract(runs.get('R2'), PRIMARY_SLUG, EFFORT_ARGUMENTS) and identity.get('slug_with_effort_passes_contract') is True:
        bind(FLASH_EXTENDED, RULE_R2, 'R2', PRIMARY_SLUG, PRIMARY_SLUG)
    elif (isinstance(r3, dict) and r3.get('requested_model') == FLASH and r3.get('extra_arguments') == list(EFFORT_ARGUMENTS)
          and r3.get('outcome') == 'exited' and exact_int(r3.get('exit_code'), 0)
          and dig(r3, 'checks', 'passes_with_echo') is True and dig(r3, 'checks', 'isolation_breach') is False
          and identity.get('family_with_effort_passes_with_echo') is True):
        suffix = SLUG_EFFORT.search(echo) if isinstance(echo, str) else None
        if (isinstance(echo, str) and BINDING_SLUG.fullmatch(echo) and dig(r3, 'classification', 'stream', 'init', 'model') == echo
                and (suffix is None or suffix.group(1) == EFFORT_ARGUMENTS[1])):
            bind(FLASH_EXTENDED, RULE_R3, 'R3', FLASH, echo)
        else:
            # agy_protocol rejects a reported slug that contradicts its --effort level; the route spills instead.
            rules[FLASH_EXTENDED] = {'rule': RULE_UNBOUND_R3_ECHO, 'run': None, 'argv': None, 'reports': None}
    else:
        rules[FLASH_EXTENDED] = {'rule': RULE_UNBOUND_EXTENDED, 'run': None, 'argv': None, 'reports': None}
    if FLASH_EXTENDED in bindings:
        contracts[FLASH_EXTENDED] = effort_contract_entry(capability_reference)
    rules[PRO_HIGH] = {'rule': RULE_UNBOUND_PRO, 'run': None, 'argv': None, 'reports': None}
    return SimpleNamespace(bindings=bindings, contracts=contracts, rules=rules)


# ----- the candidate gemini object and its byte-preserving rendering -----

def inference_only_entry(capability_reference):
    entry = {'arguments': list(ARGUMENTS), 'version_arguments': list(VERSION_ARGUMENTS), 'executable_sha256': AGY_SHA256,
             'version': AGY_VERSION, 'capability_reference': capability_reference}
    # disables_* from the A5 verdict and six-profile inventory (G3, G4); disables_model_fallback on the 3B basis:
    # the identity policy, the clean reroute scan (G3) and the passing replay (G5); A5 reports its basis UNKNOWN.
    entry.update({key: True for key in DISABLES})
    entry['disables_model_fallback'] = True
    return entry


def build_gemini(commissioned_gemini, selection, capability_reference):
    """The commissioned providers.gemini with only the reviewed contract applied; key order preserved."""
    replacements = {'arguments': list(ARGUMENTS), 'protocol': PROTOCOL, 'identity_policy': IDENTITY_POLICY,
                    'subscription_probe': copy.deepcopy(SUBSCRIPTION_PROBE),
                    'inference_only': inference_only_entry(capability_reference),
                    'model_bindings': copy.deepcopy(selection.bindings), 'effort_contracts': copy.deepcopy(selection.contracts)}
    gemini = {}
    for key, value in commissioned_gemini.items():
        if key == 'integration_hold':
            continue
        if key == 'protocol':
            gemini['protocol'] = replacements['protocol']
            gemini['identity_policy'] = replacements['identity_policy']
        elif key == 'effort_contracts':
            gemini['model_bindings'] = replacements['model_bindings']
            gemini['effort_contracts'] = replacements['effort_contracts']
        else:
            gemini[key] = replacements.get(key, copy.deepcopy(value))
    for key in ('arguments', 'protocol', 'identity_policy', 'subscription_probe', 'inference_only', 'model_bindings', 'effort_contracts'):
        gemini.setdefault(key, replacements[key])
    return gemini


def value_span(text, path):
    """Character span of the JSON value at the object-key path (the first, and in a strict document only, member)."""
    decoder = json.JSONDecoder()

    def skip(index):
        while index < len(text) and text[index] in ' \t\r\n':
            index += 1
        return index
    index = skip(1 if text.startswith('\ufeff') else 0)
    for depth, wanted in enumerate(path):
        if index >= len(text) or text[index] != '{':
            raise ValueError(f"{'.'.join(path[:depth]) or 'document'} is not a JSON object")
        index = skip(index + 1)
        while True:
            if index >= len(text) or text[index] != '"':
                raise ValueError(f"{'.'.join(path[:depth + 1])} is not present")
            name, index = json.decoder.scanstring(text, index + 1)
            index = skip(index)
            if text[index] != ':':
                raise ValueError('malformed JSON member')
            index = skip(index + 1)
            if name == wanted:
                break
            _, index = decoder.raw_decode(text, index)
            index = skip(index)
            if index < len(text) and text[index] == ',':
                index = skip(index + 1)
                continue
            raise ValueError(f"{'.'.join(path[:depth + 1])} is not present")
    _, end = decoder.raw_decode(text, index)
    return index, end


def gemini_byte_span(data):
    text = data.decode('utf-8')
    start, end = value_span(text, ('providers', 'gemini'))
    return len(text[:start].encode('utf-8')), len(text[:end].encode('utf-8')), text, start


def render_candidate(commissioned, gemini):
    """Commissioned bytes with only the providers.gemini value replaced, in the file's own layout."""
    start, end, text, char_start = gemini_byte_span(commissioned)
    line = text[text.rfind('\n', 0, char_start) + 1:char_start]
    indent = len(line) - len(line.lstrip(' '))
    crlf = commissioned.count(b'\r\n')
    newline = '\r\n' if crlf >= commissioned.count(b'\n') - crlf else '\n'
    lines = json.dumps(gemini, indent=2, ensure_ascii=True, separators=(',', ': '), allow_nan=False).split('\n')
    rendered = (newline + ' ' * indent).join(lines).encode('ascii')
    return commissioned[:start] + rendered + commissioned[end:]


class Ordered(list):
    """A JSON object as its ordered (key, value) pairs, so equality is key-order sensitive."""

    def get(self, key):
        for name, value in self:
            if name == key:
                return value
        return None

    def names(self):
        return [name for name, _ in self]


def ordered_load(data):
    return json.loads(data.decode('utf-8-sig'), object_pairs_hook=Ordered)


def retarget_view(data):
    """Assert-R5Config: both documents without providers.gemini, compared as compact JSON in document order."""
    value = strict_json(data, 'candidate view')
    value['providers'].pop('gemini', None)
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def changed_paths(old, new, prefix='providers.gemini'):
    result = []
    for key in [*old, *(name for name in new if name not in old)]:
        path = f'{prefix}.{key}'
        if key not in new:
            result.append({'path': path, 'change': 'removed'})
        elif key not in old:
            result.append({'path': path, 'change': 'added'})
        elif isinstance(old[key], dict) and isinstance(new[key], dict):
            result.extend(changed_paths(old[key], new[key], path))
        elif old[key] != new[key] or type(old[key]) is not type(new[key]):
            result.append({'path': path, 'change': 'changed'})
    return result


# ----- G5: replay through the r5 worker; G6: r5 load_config and the structural diff -----

def replay_agent_and_reroute_checks(text):
    """Recompute acceptance-only predicates from replay, not receipt booleans.

    The production parser below independently validates model identity, empty
    tools, permitted steps, session consistency and the successful single turn.
    A5 additionally requires this reviewed agent and no reroute member at all
    (including a false/null member); neither can be inferred from its summary.
    """
    records = [strict_json(line.encode('utf-8'), 'replay event') for line in text.split('\n') if line.strip()]
    init = dig(records[0], 'init') if records else None
    stack = list(records)
    no_reroute_members = True
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                if any(part in key.casefold() for part in ('reroute', 'fallback', 'deprecat', 'resolved', 'substitut', 'downgrad')):
                    no_reroute_members = False
                stack.append(child)
        elif isinstance(value, list):
            stack.extend(value)
    return dig(init, 'agent') == AGENT_NAME, no_reroute_members


def gate_replay(iso, evidence, selection, gemini, pipeline):
    receipt = iso.receipt
    runs = {run['id']: run for run in receipt.get('runs') or [] if isinstance(run, dict) and isinstance(run.get('id'), str)}
    streams = receipt.get('replay_streams') if isinstance(receipt.get('replay_streams'), dict) else {}
    plan = []
    for key, rule in selection.rules.items():
        if rule['run'] is not None:
            model, _, effort = key.partition(':')
            plan.append((rule['run'], key, model, effort or None,
                         pipeline.agy_protocol.native_model_binding(gemini, model, effort or None)))
    if all(item[0] != 'R1' for item in plan):
        plan.insert(0, ('R1', 'R1 primary acceptance', FLASH, None, {'argv': PRIMARY_SLUG, 'reports': PRIMARY_SLUG}))
    c = Checks()
    replayed = []
    for run_id, label, model, effort, native in plan:
        entry = streams.get(run_id)
        if not c.expect(dig(entry, 'available') is True, f'{label}: no available replay stream for {run_id}'):
            continue
        texts = {}
        for name in ('stdout', 'stderr'):
            relative = f'replay/{run_id}.{name}'
            c.expect(dig(entry, name, 'path') == relative, f'{label}: {run_id} {name} replay is not {relative}')
            data, digest = evidence.read(f'isolation.replay.{run_id}.{name}', os.path.join(iso.root, 'replay', f'{run_id}.{name}'),
                                         STREAM_MAX_BYTES)
            c.expect(digest == dig(entry, name, 'sha256'), f'{label}: {relative} differs from its receipt digest')
            texts[name] = data.decode('utf-8')
        try:
            parsed = pipeline.worker.parse_gemini(texts['stdout'], PROTOCOL, model, native=native,
                                                  identity_policy=IDENTITY_POLICY, stderr=texts['stderr'])
        except ValueError as exc:
            c.expect(False, f'{label}: r5 parse_gemini rejected the {run_id} replay ({describe(exc)})')
            continue
        agent_matches, no_reroute_members = replay_agent_and_reroute_checks(texts['stdout'])
        c.expect(agent_matches, f'{label}: raw replay does not name the reviewed inference-only agent')
        c.expect(no_reroute_members, f'{label}: raw replay contains a reroute member')
        run = runs.get(run_id)
        c.expect(dig(run, 'outcome') == 'exited' and type(dig(run, 'exit_code')) is int
                 and dig(run, 'exit_code') == 0, f'{label}: native run did not exit zero')
        c.expect(parsed.get('reported_model') == model, f"{label}: reported_model {parsed.get('reported_model')!r} is not {model}")
        c.expect(parsed.get('native_reported_model') == native['reports'],
                 f"{label}: native_reported_model {parsed.get('native_reported_model')!r} is not {native['reports']}")
        c.expect(parsed.get('native_selected_model') == native['argv'] and parsed.get('identity_policy') == IDENTITY_POLICY
                 and parsed.get('terminal_success') is True, f'{label}: parse_gemini did not bind the reviewed identity')
        if label != 'R1 primary acceptance':
            try:
                argv = pipeline.worker.provider_command('gemini', [gemini['executable']], model, 'C:\\unused-workspace', gemini,
                                                        effort, inference_only=True)
            except ValueError as exc:
                c.expect(False, f'{label}: r5 provider_command refused the binding ({describe(exc)})')
            else:
                c.expect(argv == dig(runs.get(run_id), 'argv'),
                         f'{label}: r5 dispatch argv differs from the A5-evidenced {run_id} argv')
        replayed.append(f'{run_id}->{model}:{native["reports"]}')
    c.done()
    return f"r5 parse_gemini replay passed for {', '.join(replayed)}"


def load_candidate_copy(candidate, out_dir, pipeline):
    """The r5 load_config on a private copy of the candidate in --out-dir\\g6-load-config-check (deploy audit B-F6: never
    %TEMP%). The subdirectory and the copy are created exclusively and removed again before the outputs are written."""
    scratch = os.path.join(os.path.abspath(out_dir), G6_SCRATCH)
    os.mkdir(scratch)
    path = os.path.join(scratch, CANDIDATE_FILE)
    try:
        write_new(path, candidate)
        return pipeline.config.load_config(path)
    finally:
        if os.path.lexists(path):
            os.remove(path)
        os.rmdir(scratch)


def gate_candidate(commissioned, candidate, gemini, selection, pipeline, out_dir):
    c = Checks()
    old_start, old_end = gemini_byte_span(commissioned)[:2]
    new_start, new_end = gemini_byte_span(candidate)[:2]
    c.expect(candidate[:new_start] == commissioned[:old_start] and candidate[new_end:] == commissioned[old_end:],
             'bytes outside the providers.gemini value differ from the commissioned file')
    strict_json(candidate, 'candidate')
    old, new = ordered_load(commissioned), ordered_load(candidate)
    c.expect(old.names() == new.names(), 'top-level key order differs')
    for name in old.names():
        if name != 'providers':
            c.expect(old.get(name) == new.get(name), f'top-level {name} changed')
    old_providers, new_providers = old.get('providers'), new.get('providers')
    c.expect(old_providers.names() == new_providers.names(), 'providers key order differs')
    for name in old_providers.names():
        if name != 'gemini':
            c.expect(old_providers.get(name) == new_providers.get(name), f'providers.{name} changed')
    c.expect(old_providers.get('gemini') != new_providers.get('gemini'), 'providers.gemini did not change')
    c.expect(old.get('routing').get('tiers') == new.get('routing').get('tiers'), 'routing.tiers changed')
    c.expect(retarget_view(commissioned) == retarget_view(candidate), 'the retarget view without providers.gemini differs')
    commissioned_gemini = strict_json(commissioned, 'commissioned')['providers']['gemini']
    hold = commissioned_gemini.get('integration_hold')
    c.expect(dig(hold, 'executable_sha256') == AGY_SHA256 and dig(hold, 'version') == AGY_VERSION,
             'the commissioned hold binds another agy binary or version')
    c.expect(strict_json(candidate, 'candidate')['providers']['gemini'] == gemini, 'the rendered providers.gemini differs from the built object')
    expected = {key: {'argv': rule['argv'], 'reports': rule['reports']} for key, rule in selection.rules.items() if rule['run']}
    try:
        loaded = load_candidate_copy(candidate, out_dir, pipeline)
        spec = loaded.providers['gemini']
        c.expect(len(loaded.workers) == 6, f'r5 load_config found {len(loaded.workers)} worker identities, not 6')
        c.expect(loaded.max_execution_slots == 4, f'r5 load_config found {loaded.max_execution_slots} shared slots, not 4')
        c.expect(bool(loaded.knowledge.enabled) is True, 'r5 load_config found knowledge disabled')
        c.expect('integration_hold' not in spec and pipeline.provider_integration.integration_hold('gemini', spec) is None,
                 'the candidate still holds Gemini')
        c.expect(pipeline.agy_protocol.validate_identity_policy(spec) == IDENTITY_POLICY, 'the identity policy did not validate')
        c.expect(pipeline.inference_policy.gemini_inference_arguments(spec) == list(ARGUMENTS), 'inference-only arguments differ')
        c.expect(pipeline.config.validate_gemini_route_bindings(spec, loaded.routing) == expected,
                 'validate_gemini_route_bindings does not return exactly the chosen bindings')
        reference = pipeline.routing.load_current_routing_policy(strict_json(commissioned, 'commissioned')['routing'])
        c.expect(loaded.routing.as_dict() == reference.as_dict(), 'the loaded routing policy differs from the commissioned one')
    except GATE_ERRORS as exc:
        c.expect(False, f'r5 load_config rejected the candidate ({describe(exc)})')
    c.done()
    return (f"r5 load_config accepts the candidate (6 workers, 4 slots, knowledge enabled, bindings "
            f"{', '.join(sorted(expected))}); only providers.gemini changed; routing.tiers unchanged")


# ----- orchestration -----

def load_pipeline():
    from cochem_pipeline import agy_protocol, config, inference_policy, provider_integration, routing, worker
    if (getattr(agy_protocol, 'IDENTITY_POLICY', None) != IDENTITY_POLICY
            or not hasattr(config, 'validate_gemini_route_bindings') or not hasattr(agy_protocol, 'native_model_binding')):
        raise RuntimeError('the imported cochem_pipeline is not the r5 package with the reviewed identity policy')
    return SimpleNamespace(agy_protocol=agy_protocol, config=config, inference_policy=inference_policy,
                           provider_integration=provider_integration, routing=routing, worker=worker)


def builder_info():
    info = {'name': os.path.basename(__file__), 'script_sha256': None, 'python': sys.executable,
            'python_version': '.'.join(str(part) for part in sys.version_info[:3]), 'isolated_mode': bool(sys.flags.isolated),
            'cochem_pipeline_file': None, 'cochem_pipeline_version_or_sha': None, 'cochem_pipeline_modules_sha256': {},
            'import_error': None}
    try:
        with open(__file__, 'rb') as handle:
            info['script_sha256'] = sha256_bytes(handle.read())
    except OSError as exc:
        info['import_error'] = describe(exc)
    try:
        import cochem_pipeline
        info['cochem_pipeline_file'] = cochem_pipeline.__file__
        info['cochem_pipeline_version_or_sha'] = str(getattr(cochem_pipeline, '__version__', None))
        base = os.path.dirname(cochem_pipeline.__file__)
        for name in PIPELINE_MODULES:
            with open(os.path.join(base, name), 'rb') as handle:
                info['cochem_pipeline_modules_sha256'][name] = sha256_bytes(handle.read())
    except Exception as exc:  # recorded only; held output never depends on the package
        info['import_error'] = describe(exc)
    return info


def evaluate(args, commissioned, decision, state):
    """Attempt mode: evaluate every gate it can; returns the candidate bytes when all six pass."""
    gates = decision['gates']
    evidence = Evidence()
    state['evidence'] = evidence

    def record(name, outcome):
        passed, reason = outcome
        gates[name] = {'pass': bool(passed), 'reason': bounded(reason)}

    def attempt(function, *arguments):
        try:
            return True, function(*arguments)
        except GATE_ERRORS as exc:
            return False, describe(exc)

    pipeline = load_pipeline()
    commissioned_doc = strict_json(commissioned, 'commissioned')
    commissioned_gemini = commissioned_doc['providers']['gemini']
    if not isinstance(commissioned_gemini, dict) or 'integration_hold' not in commissioned_gemini:
        raise RuntimeError('the commissioned providers.gemini is not the held r4 specification')
    executable = commissioned_gemini['executable']
    binding = bind_evidence({'login': args.login_root, 'capture': args.capture_root, 'isolation': args.isolation_root,
                             'stage': args.stage_root}, evidence)
    decision['evidence_binding'] = binding
    if not binding['passed']:
        refused = bounded('not evaluated: the evidence binding refused the roots (' + '; '.join(binding['reasons']) + ')')
        for name in GATES:
            gates[name] = {'pass': False, 'reason': refused}
        return None
    record('G1', attempt(gate_login, args.login_root, evidence))
    capture_ok, capture = attempt(load_capture, args.capture_root, evidence)
    iso_ok, iso = attempt(load_isolation, args.isolation_root, evidence)
    record('G3', attempt(gate_isolation, iso, evidence, executable) if iso_ok else (False, iso))
    record('G4', attempt(gate_stage, args.stage_root, evidence))
    selection = select_bindings(iso.receipt, iso.capability_reference) if iso_ok else None
    if selection is not None:
        decision['binding_selection'] = copy.deepcopy(selection.rules)
    if selection is not None and not selection.bindings:
        missing = 'not evaluated: the isolation evidence evidences no Gemini binding'
    elif selection is None:
        missing = f'not evaluated: the isolation evidence is unavailable ({iso})'
    else:
        missing = None
    if not capture_ok:
        record('G2', (False, capture))
    elif missing:
        record('G2', (False, f'SUCCESS models envelope verified; bound slugs {missing}'))
    else:
        record('G2', attempt(gate_catalog, capture, selection))
    if missing:
        record('G5', (False, missing))
        record('G6', (False, missing))
        return None
    gemini = build_gemini(commissioned_gemini, selection, iso.capability_reference)
    record('G5', attempt(gate_replay, iso, evidence, selection, gemini, pipeline))
    candidate = render_candidate(commissioned, gemini)
    paths = changed_paths(commissioned_gemini, gemini)
    decision['proposed'] = {'model_bindings': copy.deepcopy(selection.bindings), 'effort_contracts': copy.deepcopy(selection.contracts),
                            'candidate_sha256': sha256_bytes(candidate), 'candidate_length': len(candidate), 'changed_paths': paths}
    record('G6', attempt(gate_candidate, commissioned, candidate, gemini, selection, pipeline, args.out_dir))
    if all(gates[name]['pass'] for name in GATES):
        state['selection'] = selection
        state['changed_paths'] = paths
        return candidate
    return None


def new_decision(args, commissioned):
    digest = sha256_bytes(commissioned)
    placeholder = 'not evaluated: held mode requested' if args.mode == 'held' else 'not evaluated'
    return {
        'schema': SCHEMA, 'mode': args.mode, 'outcome': OUTCOME_HELD,
        'gates': {name: {'pass': False, 'reason': placeholder} for name in GATES},
        'chosen_bindings': None, 'effort_contracts': None, 'binding_selection': None, 'proposed': None, 'changed_paths': [],
        'error': None, 'candidate_file': CANDIDATE_FILE, 'candidate_sha256': digest, 'candidate_length': len(commissioned),
        'commissioned_path': args.commissioned, 'commissioned_sha256': digest, 'commissioned_length': len(commissioned),
        'commissioned_pin': COMMISSIONED_SHA256, 'evidence': {}, 'evidence_binding': None,
        'inputs': {'login_root': args.login_root, 'capture_root': args.capture_root, 'isolation_root': args.isolation_root,
                   'stage_root': args.stage_root, 'evidence_read': args.mode == 'attempt'},
        'builder': builder_info()}


def decide(args, commissioned):
    """Never raises: any failure degrades to the held decision with the commissioned bytes."""
    decision = new_decision(args, commissioned)
    if args.mode == 'held':
        return decision, commissioned
    state = {}
    candidate = None
    try:
        candidate = evaluate(args, commissioned, decision, state)
    except Exception as exc:
        decision['error'] = describe(exc)
        for gate in decision['gates'].values():
            if gate['reason'] == 'not evaluated':
                gate['reason'] = bounded(f"not evaluated: builder error before this gate ({decision['error']})")
        candidate = None
    if state.get('evidence') is not None:
        decision['evidence'] = copy.deepcopy(state['evidence'].files)
    if candidate is None or decision['error'] is not None:
        return decision, commissioned
    digest = sha256_bytes(candidate)
    if digest == sha256_bytes(commissioned) or not state.get('changed_paths') or not state['selection'].bindings:
        decision['error'] = 'InvariantError: a contract candidate must differ from the commissioned bytes under providers.gemini'
        return decision, commissioned
    decision.update(outcome=OUTCOME_CONTRACT, chosen_bindings=copy.deepcopy(state['selection'].bindings),
                    effort_contracts=copy.deepcopy(state['selection'].contracts), changed_paths=state['changed_paths'],
                    candidate_sha256=digest, candidate_length=len(candidate))
    return decision, candidate


def serialize(decision):
    return (json.dumps(decision, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('ascii')


def read_commissioned(path):
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise Refusal(EXIT_COMMISSIONED, f'the commissioned file is unreadable: {describe(exc)}') from exc
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400 or not stat.S_ISREG(info.st_mode):
        raise Refusal(EXIT_COMMISSIONED, 'the commissioned file is not an ordinary file')
    try:
        with open(path, 'rb') as handle:
            data = handle.read(COMMISSIONED_MAX_BYTES + 1)
    except OSError as exc:
        raise Refusal(EXIT_COMMISSIONED, f'the commissioned file is unreadable: {describe(exc)}') from exc
    if len(data) > COMMISSIONED_MAX_BYTES:
        raise Refusal(EXIT_COMMISSIONED, 'the commissioned file exceeds its size bound')
    digest = sha256_bytes(data)
    if digest != COMMISSIONED_SHA256:
        raise Refusal(EXIT_COMMISSIONED, f'the commissioned file sha256 {digest} differs from the pin {COMMISSIONED_SHA256}')
    return data


def prepare_out_dir(path):
    try:
        if os.path.lexists(path):
            info = os.lstat(path)
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400 or not stat.S_ISDIR(info.st_mode):
                raise Refusal(EXIT_OUT_DIR, f'--out-dir is not an ordinary directory: {path}')
            entries = os.listdir(path)
            if entries:
                raise Refusal(EXIT_OUT_DIR, f'--out-dir is not empty ({len(entries)} entries); nothing is overwritten: {path}')
        else:
            os.makedirs(path)
    except OSError as exc:
        raise Refusal(EXIT_OUT_DIR, f'--out-dir cannot be prepared: {describe(exc)}') from exc


def write_new(path, data):
    with open(path, 'xb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def emit(stream, value):
    stream.write(json.dumps(value, ensure_ascii=True, sort_keys=True) + '\n')
    stream.flush()


def build_parser():
    parser = argparse.ArgumentParser(description='Gated r5 pipeline.json candidate builder (S9).')
    parser.add_argument('--commissioned', required=True)
    parser.add_argument('--login-root')
    parser.add_argument('--capture-root')
    parser.add_argument('--isolation-root')
    parser.add_argument('--stage-root')
    parser.add_argument('--mode', required=True, choices=MODES)
    parser.add_argument('--out-dir', required=True)
    return parser


def main(argv=None):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    if args.mode == 'attempt':
        missing = [flag for flag, value in (('--login-root', args.login_root), ('--capture-root', args.capture_root),
                                            ('--isolation-root', args.isolation_root)) if not value]
        if missing:
            emit(sys.stderr, {'schema': RESULT_SCHEMA, 'status': 'USAGE', 'exit_code': EXIT_USAGE,
                              'reason': '--mode attempt requires ' + ', '.join(missing)})
            return EXIT_USAGE
        args.login_root, args.capture_root, args.isolation_root = (
            os.path.abspath(value) for value in (args.login_root, args.capture_root, args.isolation_root))
        args.stage_root = os.path.abspath(args.stage_root) if args.stage_root else args.isolation_root + STAGE_ROOT_SUFFIX
    try:
        commissioned = read_commissioned(args.commissioned)
        prepare_out_dir(args.out_dir)
    except Refusal as exc:
        emit(sys.stderr, {'schema': RESULT_SCHEMA, 'status': 'REFUSED', 'exit_code': exc.code, 'reason': bounded(exc)})
        return exc.code
    decision, payload = decide(args, commissioned)
    try:
        body = serialize(decision)
    except Exception as exc:  # degrade to a minimal held decision rather than fail the sitting
        decision, payload = new_decision(args, commissioned), commissioned
        decision['error'] = describe(exc)
        body = serialize(decision)
    try:
        write_new(os.path.join(args.out_dir, CANDIDATE_FILE), payload)
        write_new(os.path.join(args.out_dir, DECISION_FILE), body)
    except OSError as exc:
        emit(sys.stderr, {'schema': RESULT_SCHEMA, 'status': 'WRITE_FAILED', 'exit_code': EXIT_WRITE, 'reason': describe(exc)})
        return EXIT_WRITE
    emit(sys.stdout, {'schema': RESULT_SCHEMA, 'status': 'DECISION_WRITTEN', 'exit_code': EXIT_DECISION, 'mode': decision['mode'],
                      'outcome': decision['outcome'], 'candidate_sha256': decision['candidate_sha256'],
                      'decision_sha256': sha256_bytes(body), 'out_dir': args.out_dir})
    return EXIT_DECISION


if __name__ == '__main__':
    raise SystemExit(main())
