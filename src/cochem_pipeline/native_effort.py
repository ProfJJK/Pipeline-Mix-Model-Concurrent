"""Reviewed native bindings for provider-specific reasoning profiles.

``extended`` is a pipeline profile, not an invented vendor CLI effort. A
protected per-model contract must explicitly bind it to real native arguments
and, when the CLI exposes it, native output metadata. Explicitly unavailable
metadata remains unverified; the requested profile is never reported as fact.
No bindings are supplied by default. Missing or
changed capabilities stop before authentication/inference and allow normal
job-board compatibility spillover. Protocol fixtures are not host evidence.
Codex contracts bind its ``-c model_reasoning_effort`` selector to an exact
binary/version; they are optional only for configs that declare none.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat
import threading


_FIELDS = {'arguments', 'version_arguments', 'executable_sha256', 'version',
           'capability_reference', 'native_metadata', 'thinking_enabled'}
_NATIVE_FIELDS = {'reasoning_effort', 'model_reasoning_effort', 'thinking_level',
                  'thinking_mode', 'thinking_enabled', 'effort', 'thinking', 'metadata'}
_FORBIDDEN_PATHS = {'result', 'response', 'content', 'text', 'message', 'messages', 'parts'}
_PROTECTED_FLAGS = {'--model', '--tools', '--allowedTools', '--allowed-tools',
                    '--mcp-config', '--strict-mcp-config', '--settings',
                    '--setting-sources', '--permission-mode', '--output-format',
                    '--dangerously-skip-permissions', '--disable-slash-commands',
                    '--bare', '--prompt', '-p', '--include-directories', '--extensions'}
_PROTECTED_FLAGS |= {'--yolo', '--approval-mode', '--sandbox', '-s', '--config', '-c',
                     '--allowed-mcp-server-names', '--allowed-tools', '--resume', '--continue',
                     '--agent', '--agents', '--mcp', '--extension', '-e'}


def _argv(value, name):
    if (not isinstance(value, list) or not value or len(value) > 32
            or any(not isinstance(item, str) or not item or len(item) > 2048
                   or any(ord(char) < 32 for char in item) for item in value)):
        raise ValueError(f'Native reasoning effort {name} must be a bounded argv array')
    return list(value)


def _codex_contract(model, effort, spec):
    """Codex selects effort with its own config override, which no other
    provider contract may use. Without reviewed Codex contracts the legacy
    unattested selector remains (older protected configs still load); once a
    protected spec declares them, every routed model/effort needs its own."""
    contracts = spec.get('effort_contracts') if isinstance(spec, dict) else None
    if contracts is None:
        return None
    contract = contracts.get(f'{model}:{effort}') if isinstance(contracts, dict) else None
    if not isinstance(contract, dict) or set(contract) != _FIELDS:
        raise ValueError('Native reasoning effort requires an exact reviewed model/profile contract')
    if (not isinstance(contract['executable_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', contract['executable_sha256'])):
        raise ValueError('Native reasoning effort requires the exact executable digest')
    for field in ('version', 'capability_reference'):
        if (not isinstance(contract[field], str) or not contract[field].strip()
                or len(contract[field]) > 2048):
            raise ValueError('Native reasoning effort requires version and capability provenance')
    if contract['version_arguments'] != ['--version']:
        raise ValueError('Native reasoning effort version probe must use the offline --version selector')
    if contract['arguments'] != ['-c', 'model_reasoning_effort=' + json.dumps(effort)]:
        raise ValueError('Codex reasoning effort must select exactly the routed native level')
    if contract['thinking_enabled'] is not None or contract['native_metadata'] is not None:
        # Native Codex events are read separately and may only contradict.
        raise ValueError('Codex reasoning effort has no reviewed output metadata binding')
    if str(spec.get('executable', '')).lower().endswith(('.cmd', '.bat')):
        raise ValueError('Codex reasoning effort requires the native executable, not a shim')
    return contract


def effort_contract(provider, model, effort, spec):
    """Return an exact reviewed binding; never infer one from a display label."""
    if effort is None:
        return None
    if provider == 'codex':
        if effort not in ('low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
            raise ValueError('Native Codex reasoning effort is outside the routed contract')
        return _codex_contract(model, effort, spec)
    if ((provider == 'claude' and effort not in ('low', 'medium', 'high', 'xhigh', 'max', 'extended'))
            or (provider == 'gemini' and effort not in ('low', 'medium', 'high', 'extended'))
            or provider not in ('claude', 'gemini')):
        raise ValueError('Unsupported provider reasoning effort profile')
    contracts = spec.get('effort_contracts', {}) if isinstance(spec, dict) else {}
    contract = contracts.get(f'{model}:{effort}') if isinstance(contracts, dict) else None
    slug_encoded = isinstance(contract, dict) and 'slug_effort' in contract
    if not isinstance(contract, dict) or set(contract) != (_FIELDS | {'slug_effort'} if slug_encoded else _FIELDS):
        raise ValueError('Native reasoning effort requires an exact reviewed model/profile contract')
    if slug_encoded and (provider != 'gemini' or spec.get('protocol') != 'agy-stream-json'
            or spec.get('identity_policy') != 'reported-model-equality'
            or effort not in ('low', 'medium', 'high') or contract['slug_effort'] != effort
            or contract['arguments'] != [] or contract['native_metadata'] is not None):
        raise ValueError('Slug effort requires an explicit Agy identity binding without an extra effort flag')
    if (not isinstance(contract['executable_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', contract['executable_sha256'])):
        raise ValueError('Native reasoning effort requires the exact executable digest')
    for field in ('version', 'capability_reference'):
        if (not isinstance(contract[field], str) or not contract[field].strip()
                or len(contract[field]) > 2048):
            raise ValueError('Native reasoning effort requires version and capability provenance')
    args = [] if slug_encoded else _argv(contract['arguments'], 'arguments')
    _argv(contract['version_arguments'], 'version arguments')
    if contract['version_arguments'] != ['--version']:
        raise ValueError('Native reasoning effort version probe must use the offline --version selector')
    if any(item.split('=', 1)[0] in _PROTECTED_FLAGS or '{' in item or '}' in item for item in args):
        raise ValueError('Native reasoning effort arguments cannot override model or inference policy')
    if provider == 'claude':
        # These are documented --effort levels, not inferred aliases for
        # Extended. The protected contract must select and attest one explicitly.
        if (len(args) != 2 or args[0] != '--effort'
                or args[1] not in ('low', 'medium', 'high', 'xhigh', 'max')
                or contract['thinking_enabled'] is not True):
            raise ValueError('Claude Extended requires reviewed native effort and enabled thinking')
        if effort != 'extended' and args[1] != effort:
            raise ValueError('Explicit Claude effort must match the native selector exactly')
    else:
        # These are the only eligible thinking-only selector shapes. They are
        # not assumed Agy capabilities: an exact reviewed binary contract is
        # still mandatory. Never accept arbitrary flags or configuration files
        # that could enable tools, change the selected model or start a prompt.
        if not slug_encoded and (len(args) != 2 or not (
                (args[0] == '--thinking-level' and args[1] in
                 ('minimal', 'low', 'medium', 'high', 'MINIMAL', 'LOW', 'MEDIUM', 'HIGH'))
                or (args[0] == '--effort' and args[1] in ('low', 'medium', 'high', 'xhigh', 'max'))
                or (args[0] == '--thinking-budget' and re.fullmatch('[0-9]{1,6}', args[1])
                    and 1 <= int(args[1]) <= 131072))):
            raise ValueError('Agy reasoning effort requires a bounded reviewed thinking-only selector')
        if not slug_encoded and effort != 'extended' and args not in (['--thinking-level', effort], ['--thinking-level', effort.upper()], ['--effort', effort]):
            raise ValueError('Agy explicit effort must select the same native level; no alias is allowed')
        if slug_encoded:
            from .agy_protocol import native_model_binding
            binding = native_model_binding(spec, model, effort)
            if any(not value.endswith('-' + effort) for value in binding.values()):
                raise ValueError('Agy selected and reported model names must encode the exact effort')
        inference = spec.get('inference_only', {})
        if contract['thinking_enabled'] is not None or any(
                contract[field] != inference.get(field)
                for field in ('executable_sha256', 'version', 'version_arguments')):
            raise ValueError('Agy effort and inference-only contracts must identify the same native binary/version')
    metadata = contract['native_metadata']
    if provider == 'gemini' and spec.get('protocol') == 'agy-stream-json' and metadata is not None:
        raise ValueError('Agy stream has no verified native effort observation binding')
    if metadata is None:
        # An installed CLI may support selecting effort without returning it.
        # This proves only the reviewed invocation, never the actual effort.
        return contract
    if not isinstance(metadata, dict) or set(metadata) != {'path', 'value'}:
        raise ValueError('Native reasoning effort requires an explicit output metadata binding')
    path = metadata['path']
    if (not isinstance(path, list) or not 1 <= len(path) <= 4
            or any(not isinstance(part, str) or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}', part)
                   or part.casefold() in _FORBIDDEN_PATHS for part in path)
            or path[0] not in _NATIVE_FIELDS):
        raise ValueError('Native reasoning effort cannot use generated content as evidence')
    if type(metadata['value']) not in (str, bool, int) or (
            isinstance(metadata['value'], str) and not 0 < len(metadata['value']) <= 128) or (
            type(metadata['value']) is int and not -(2 ** 63) <= metadata['value'] < 2 ** 63):
        raise ValueError('Native reasoning effort metadata value must be a bounded native scalar')
    if effort != 'extended' and (
            path[-1] not in {'reasoning_effort', 'model_reasoning_effort', 'thinking_level', 'effort'}
            or metadata['value'] not in (effort, effort.upper())):
        raise ValueError(f'Explicit effort metadata must attest the native {effort} effort level')
    return contract


_DIGEST_LOCK = threading.Lock()
_DIGEST_CACHE: dict[tuple, str] = {}


def _file_identity(path, metadata):
    return (str(path), metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns,
            metadata.st_ino, metadata.st_dev)


def verified_executable_sha256(path, maximum=1073741824):
    """SHA-256 of a regular executable, computed once per physical file identity.

    The digest is reused only while the path's size, modification time, creation
    time, file index and volume are unchanged; any replacement or rewrite is
    hashed again. Reviewed executables live under ACL-protected Program Files
    roots that only SYSTEM/Administrators can write, and every dispatch still
    runs the native version probe. Hashing a provider binary (claude.exe is
    235 MB) inside the controller on every dispatch exceeded the Warden's own
    CPU budget and revoked the 4.2.8 catalog control probe.
    """
    path = Path(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
        raise ValueError('Native executable is missing or exceeds its size bound')
    key = _file_identity(path, before)
    with _DIGEST_LOCK:
        cached = _DIGEST_CACHE.get(key)
    if cached is not None:
        return cached
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1048576):
            digest.update(chunk)
    if key != _file_identity(path, path.stat()):
        raise ValueError('Native executable changed while it was being verified')
    actual = digest.hexdigest()
    with _DIGEST_LOCK:
        # Bounded: a handful of reviewed provider executables per controller.
        if len(_DIGEST_CACHE) >= 64:
            _DIGEST_CACHE.clear()
        _DIGEST_CACHE[key] = actual
    return actual


def prewarm_executable_digests(providers):
    """Verify each configured provider executable once, before admission opens.

    Returns {provider: sha256 or None}. A failure is not fatal here: the
    dispatch-time contract check still refuses a missing or mismatched binary.
    """
    result = {}
    for name, spec in sorted((providers or {}).items()):
        executable = spec.get('executable') if isinstance(spec, dict) else None
        if not isinstance(executable, str) or not Path(executable).is_absolute():
            continue
        try:
            result[name] = verified_executable_sha256(executable)
        except (OSError, ValueError):
            result[name] = None
    return result


def effort_binary_digest(spec, contract):
    """Pin reviewed effort semantics to a regular, nonredirected executable."""
    path = Path(spec['executable'])
    if not path.is_absolute():
        raise ValueError('Native reasoning effort requires an absolute executable')
    for current in (path, *path.parents):
        metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Native reasoning effort executable cannot traverse redirected paths')
    try:
        actual = verified_executable_sha256(path)
    except ValueError as exc:
        raise ValueError('Native reasoning effort executable is missing, oversized or changed during validation') from exc
    if actual != contract['executable_sha256']:
        raise ValueError('Native executable does not match the reviewed reasoning effort contract')
    return actual


def effort_version_evidence(contract, stdout, digest, *, model, effort):
    if (digest != contract['executable_sha256'] or not isinstance(stdout, str)
            or stdout.strip() != contract['version']):
        raise ValueError('Native version does not match the reviewed reasoning effort contract')
    return {'requested_profile': effort, 'model': model, 'executable_sha256': digest,
            'version': contract['version'], 'capability_reference': contract['capability_reference'],
            'contract_sha256': hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(',', ':'),
                ensure_ascii=False, allow_nan=False).encode()).hexdigest(),
            'native_metadata': contract['native_metadata']}


def reported_profile(provider, raw, *, model, effort, spec):
    """Bind an observed native field to a reviewed profile, excluding answer text."""
    contract = effort_contract(provider, model, effort, spec)
    if contract is None:
        return None
    if provider == 'codex':
        # The reviewed selector is attested by the version-pinned invocation;
        # a native event may confirm the level, never contradict it.
        from .worker import native_reported_effort
        observed = native_reported_effort('codex', raw)
        if observed is not None and observed != effort:
            raise ValueError('Native Codex output contradicts the reviewed reasoning effort')
        return {'verified_profile': effort if observed is not None else None,
                'native_metadata_path': None, 'observed_native_value': observed,
                'reported_effort': observed,
                'observation_status': ('reported_by_native_event' if observed is not None
                                       else 'not_reported_by_reviewed_cli')}
    if contract['native_metadata'] is None:
        return {'verified_profile': None, 'native_metadata_path': None,
                'observed_native_value': None, 'reported_effort': None,
                'observation_status': 'not_reported_by_reviewed_cli'}
    from .worker import strict_json
    event = strict_json(raw)
    if not isinstance(event, dict):
        raise ValueError('Native reasoning effort metadata envelope is missing')
    if provider == 'claude' and event.get('type') != 'result':
        raise ValueError('Claude reasoning effort requires a native terminal result')
    if provider == 'gemini' and spec.get('protocol') == 'terminal-json' and event.get('type') != 'result':
        raise ValueError('Agy reasoning effort requires a native terminal result')
    expected = contract['native_metadata']
    current = event
    for part in expected['path']:
        if not isinstance(current, dict) or part not in current:
            raise ValueError('Native output did not attest the reviewed reasoning effort')
        current = current[part]
    if type(current) is not type(expected['value']) or current != expected['value']:
        raise ValueError('Native output contradicts the reviewed reasoning effort')
    # Preserve the actual native value. For example, a reviewed Extended ->
    # max binding does not make the CLI report the string "extended".
    return {'verified_profile': effort, 'native_metadata_path': expected['path'],
            'observed_native_value': current,
            'reported_effort': current if isinstance(current, str) and current == effort else None}
