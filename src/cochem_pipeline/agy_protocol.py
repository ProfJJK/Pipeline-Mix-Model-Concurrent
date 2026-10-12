"""Agy's documented NDJSON transport and its reviewed model identity policy.

Without a policy the init event reports the selected model, not a server
attestation of which model served the request, so every agy-stream-json spec
stays held. The reviewed 'reported-model-equality' policy (decision 3B) treats
the model name the CLI echoes in its init event, and every member anywhere in
any event that spells a model, as the identity: any mismatch, absence,
fallback or reroute field, or rerouting diagnostic is a hard AgyIdentityError.
A reviewed model_bindings table maps each routed (model, effort) to the CLI
argv slug and the name the CLI reports. Authentication and inference isolation
remain separate required deployment evidence; this module cannot supply them.
"""
from __future__ import annotations

import json
import re


PROTOCOL = 'agy-stream-json'
IDENTITY_POLICY = 'reported-model-equality'

_SLUG = re.compile(r'^[a-z0-9][a-z0-9.-]{0,127}$')
_BINDING_KEY = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}(:(extended|low|medium|high))?$')
_MAX_BINDINGS = 32
_SLUG_EFFORT = re.compile(r'-(low|medium|high)$')
# Member names are compared casefolded with separators removed, so that
# model_id, modelId and model-id are one spelling. Every model member must equal
# the reviewed reported name, and a 'models' collection may name only it.
_MODEL_KEYS = frozenset(('model', 'selectedmodel', 'modelid', 'modelname', 'modelversion', 'resolvedmodel'))
_MODELS_KEY = 'models'
# The A5 evidence tool's reroute fragments (agy_isolation_evidence_r4_v1.py
# REROUTE_KEY_FRAGMENTS) plus two reroute members named in the agy binary. A
# truthy member is a reroute; A5 lists any key containing 'resolved', so even
# an agreeing resolved_model is rejected.
_REROUTE_KEY_PARTS = ('rerout', 'fallback', 'deprecat', 'resolved', 'substitut', 'downgrad',
                      'usednongeminimodel', 'capacityexhausted')
# The A5 tool's STDERR_MARKERS plus the agy one-shot model restore notice.
_STDERR_MARKERS = ('AGY_ERROR:', 'is no longer available. Using', 'Model resolved via',
                   'Restored session model', 'resolves to a different model', 'defaulting to',
                   'Restoring model')
_STDERR_LIMIT = 8 * 1024 * 1024
_ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]')


class AgyIdentityError(ValueError):
    """Native output contradicts the reviewed identity, reroute or tool registry.

    Callers classify this as a compatibility failure (model hold and reroute),
    never as a protocol failure that counts against the job.
    """


class AgyToolRegistryError(AgyIdentityError):
    """Native output reports a tool registry, tool step or subagent.

    Still a compatibility failure; the subclass only lets callers record the
    distinct 'agy_tool_registry' failure envelope.
    """


def validate_identity_policy(spec):
    """Return IDENTITY_POLICY when declared, None when absent; reject anything else."""
    if 'identity_policy' not in spec:
        return None
    if spec['identity_policy'] != IDENTITY_POLICY or spec.get('protocol') != PROTOCOL:
        raise ValueError('Agy identity policy must be reported-model-equality '
                         'on the agy-stream-json protocol')
    return IDENTITY_POLICY


def require_serving_model_contract(spec):
    """Keep unsupported identity semantics held before any native dispatch."""
    if validate_identity_policy(spec) is None and spec.get('protocol') == PROTOCOL:
        raise ValueError('Agy stream actual-model identity has no verified native contract')
    validate_model_bindings(spec)


def validate_model_bindings(spec):
    """Return {routed key: {'argv': slug, 'reports': slug}} from the reviewed table.

    A value is either one slug (argv and reports are the same) or a mapping with
    exactly 'argv' and 'reports'. Bindings are required under the identity
    policy and rejected without it, where the result is always empty.
    """
    if validate_identity_policy(spec) is None:
        if 'model_bindings' in spec:
            raise ValueError('Agy model bindings require the reported-model-equality identity policy')
        return {}
    table = spec.get('model_bindings')
    if not isinstance(table, dict) or not 1 <= len(table) <= _MAX_BINDINGS:
        raise ValueError('Agy identity policy requires 1 to 32 reviewed model bindings')
    contracts = spec.get('effort_contracts', {})
    if not isinstance(contracts, dict):
        raise ValueError('Agy effort contracts must be a reviewed mapping')
    bindings = {}
    for key, value in table.items():
        if not isinstance(key, str) or not _BINDING_KEY.fullmatch(key):
            raise ValueError('Agy model binding key must be a routed model '
                             'with an optional :extended, :low, :medium or :high profile')
        if isinstance(value, str):
            argv = reports = value
        elif isinstance(value, dict) and set(value) == {'argv', 'reports'}:
            argv, reports = value['argv'], value['reports']
        else:
            raise ValueError('Agy model binding must be a slug or exactly {argv, reports}')
        if any(not isinstance(slug, str) or not _SLUG.fullmatch(slug) for slug in (argv, reports)):
            raise ValueError('Agy model binding slugs must be reviewed lowercase CLI model names')
        if ':' in key:
            contract = contracts.get(key)
            if not isinstance(contract, dict):
                raise ValueError('Agy effort model binding requires a reviewed effort contract')
            arguments = contract.get('arguments')
            if isinstance(arguments, list) and len(arguments) == 2 and arguments[0] == '--effort':
                for slug in (argv, reports):
                    suffix = _SLUG_EFFORT.search(slug)
                    if suffix and suffix.group(1) != arguments[1]:
                        raise ValueError('Agy model binding slug contradicts its reviewed --effort level')
        bindings[key] = {'argv': argv, 'reports': reports}
    if any(key not in bindings for key in contracts):
        raise ValueError('Every Agy effort contract requires a reviewed model binding')
    return bindings


def native_model_binding(spec, model, effort):
    """Map a routed model/effort to its reviewed CLI argv slug and reported name."""
    bindings = validate_model_bindings(spec)
    if validate_identity_policy(spec) is None:
        return {'argv': model, 'reports': model}
    binding = bindings.get(model if effort is None else f'{model}:{effort}')
    if binding is None:
        raise ValueError('Gemini route has no reviewed native model binding')
    return dict(binding)


def validate_arguments(arguments):
    """Bind a one-prompt stdin transport without conversation/argv prompt reuse."""
    if (not isinstance(arguments, list) or not 1 <= len(arguments) <= 64
            or any(not isinstance(arg, str) or '\0' in arg or len(arg) > 8192 for arg in arguments)):
        raise ValueError('Agy stream transport requires bounded argv strings')
    for flag, value in (('--input-format', 'stream-json'),
                        ('--output-format', 'stream-json'), ('--model', '{model}')):
        if (arguments.count(flag) != 1 or arguments.index(flag) + 1 >= len(arguments)
                or arguments[arguments.index(flag) + 1] != value
                or any(arg.startswith(flag + '=') for arg in arguments)):
            raise ValueError('Agy stream transport requires exact input/output format and model selectors')
    forbidden = {'-p', '--print', '--prompt', '-i', '--prompt-interactive',
                 '-c', '--continue', '--conversation', '--dangerously-skip-permissions'}
    if any(arg.split('=', 1)[0] in forbidden for arg in arguments):
        raise ValueError('Agy stream transport must receive one fresh prompt only through stdin')


def encode_prompt(prompt):
    # JSON escaping makes embedded newlines and user-looking events data, not
    # additional turns. The owned pipe closes after this one line is delivered.
    if not isinstance(prompt, str) or not prompt:
        raise ValueError('Agy requires one nonempty controller prompt')
    return json.dumps({'event': 'user', 'message': {'content': prompt}},
                      ensure_ascii=False, separators=(',', ':')) + '\n'


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate Agy native JSON member')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Invalid Agy native JSON constant')
    def bound_depth(value, depth=0):
        if depth > 32:
            raise ValueError('Agy native JSON exceeds the supported nesting depth')
        if isinstance(value, dict):
            for child in value.values():
                bound_depth(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                bound_depth(child, depth + 1)
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        bound_depth(value)
        return value
    except RecursionError as exc:
        raise ValueError('Agy native JSON exceeds the supported nesting depth') from exc


def _member(key):
    # One spelling per member name: casefolded, separators removed.
    return ''.join(char for char in key.casefold() if char.isalnum()) if isinstance(key, str) else ''


def _reject_reroute(value):
    # Always on: a truthy fallback/reroute/substitution member anywhere in the
    # native records means the CLI did not serve the selected model as-is.
    if isinstance(value, dict):
        for key, child in value.items():
            if child and any(part in _member(key) for part in _REROUTE_KEY_PARTS):
                raise AgyIdentityError('Agy stream reports a model fallback or reroute')
            _reject_reroute(child)
    elif isinstance(value, list):
        for child in value:
            _reject_reroute(child)


def _names_only(value, expected_model):
    # A 'models' mapping is keyed only by the reviewed name; a list or a single
    # name must be that name; an empty or null member names no model.
    if isinstance(value, dict):
        names = list(value)
    elif isinstance(value, list):
        names = value
    elif isinstance(value, str):
        names = [value]
    else:
        return not value
    return all(name == expected_model for name in names)


def _require_model_identity(value, expected_model):
    # Always on and recursive: every member spelling a model, in any event or
    # nested record, must equal the reviewed reported name.
    if isinstance(value, dict):
        for key, child in value.items():
            member = _member(key)
            if ((member in _MODEL_KEYS and child != expected_model)
                    or (member == _MODELS_KEY and not _names_only(child, expected_model))):
                raise AgyIdentityError('Agy stream reports a model other than the reviewed binding')
            _require_model_identity(child, expected_model)
    elif isinstance(value, list):
        for child in value:
            _require_model_identity(child, expected_model)


def require_clean_diagnostics(stderr):
    """Reject Agy diagnostics that report a model error, fallback or reroute.

    ``stderr`` is the decoded native error stream. Terminal styling is removed
    before the marker scan, as the A5 evidence tool does. Raises ValueError for
    an unbounded or non-text stream and AgyIdentityError for any marker; no
    diagnostic text is copied into either exception.
    """
    if not isinstance(stderr, str) or len(stderr) > _STDERR_LIMIT:
        raise ValueError('Agy native diagnostics exceed their bounded contract')
    text = _ANSI.sub('', stderr) if '\x1b' in stderr else stderr
    if any(marker in text for marker in _STDERR_MARKERS):
        raise AgyIdentityError('Agy diagnostics report a model error, fallback or reroute')


def parse_stream(raw, expected_model, *, identity_policy=None, stderr=None):
    """Validate one native conversation; never infer identity from answer prose."""
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > 8 * 1024 * 1024:
        raise ValueError('Agy native output exceeds its bounded stream contract')
    if not isinstance(expected_model, str) or not expected_model.strip():
        raise ValueError('Agy requires an exact selected model')
    if identity_policy is not None and identity_policy != IDENTITY_POLICY:
        raise ValueError('Unsupported Agy identity policy')
    if stderr is not None:
        require_clean_diagnostics(stderr)
    # NDJSON delimiters are LF; Unicode paragraph separators inside JSON text
    # are content and must not split an otherwise valid native record.
    lines = [line for line in raw.split('\n') if line.strip()]
    if not 2 <= len(lines) <= 32768:
        raise ValueError('Agy must report one bounded native conversation')
    events = [_json(line) for line in lines]
    _reject_reroute(events)
    if (any(not isinstance(event, dict) for event in events)
            or events[0].get('event') != 'init' or events[-1].get('event') != 'result'):
        raise ValueError('Agy stream requires initial and terminal native events')
    _require_model_identity(events, expected_model)
    first, terminal = events[0], events[-1].get('result')
    init = first.get('init')
    session = first.get('conversation_id')
    if (not isinstance(session, str) or not 0 < len(session.strip()) <= 512
            or any(ord(char) < 32 for char in session) or not isinstance(init, dict)):
        raise ValueError('Agy native selected model and session must match the controller request')
    if init.get('model') != expected_model:
        raise AgyIdentityError('Agy native selected model and session must match the controller request')
    if init.get('tools') != []:
        raise AgyToolRegistryError('Agy stream did not attest an empty native tool registry')
    for event in events[1:-1]:
        step = event.get('step_update')
        if event.get('event') != 'step_update' or not isinstance(step, dict):
            raise ValueError('Agy stream contains unverified steps, tools, agents or model identity')
        if any(key in step for key in ('tool_name', 'tool_info', 'subagent_info')):
            raise AgyToolRegistryError('Agy stream contains unverified steps, tools, agents or model identity')
        if 'model' in step and step['model'] != expected_model:
            raise AgyIdentityError('Agy stream contains unverified steps, tools, agents or model identity')
        if (step.get('conversation_id') != session
                or step.get('step_type') not in ('user_input', 'agent_response', 'checkpoint')
                or step.get('state') not in ('ACTIVE', 'DONE')
                or type(step.get('step_index')) is not int or step['step_index'] < 0):
            raise ValueError('Agy stream contains unverified steps, tools, agents or model identity')
    if (not isinstance(terminal, dict) or terminal.get('conversation_id') != session
            or terminal.get('status') != 'SUCCESS'
            or type(terminal.get('num_turns')) is not int or terminal['num_turns'] != 1
            or terminal.get('error') or terminal.get('permission_denials')
            or not isinstance(terminal.get('response'), str) or not terminal['response'].strip()):
        raise ValueError('Agy must report one successful result for the same native conversation')
    if 'model' in terminal and terminal['model'] != expected_model:
        raise AgyIdentityError('Agy must report one successful result for the same native conversation')
    # Without the reviewed policy init.model is configuration metadata only and
    # the caller must retain its hold. Under the policy init.model, checked
    # above to equal the binding's reported name, is the identity receipt; a
    # result without a model member is the documented CLI shape, not a failure.
    return {'content': terminal['response'], 'session_id': session,
            'native_selected_model': init['model'],
            'reported_model': init['model'] if identity_policy == IDENTITY_POLICY else None,
            'terminal_success': True,
            'usage': terminal.get('usage') if isinstance(terminal.get('usage'), dict) else {}}
