"""Prepare Gemini 4 Argon bindings from captured Agy catalog evidence.

No provider is executed here. A catalog listing is not inference acceptance;
the protected deployment must still verify the selected and reported model,
effort invocation, containment, authentication and cleanup for each profile.
"""
from copy import deepcopy
import re

from .agy_protocol import validate_model_bindings
from .native_effort import effort_contract
from .task_routing import digest


MODEL = 'gemini-4-argon'
EFFORTS = ('low', 'medium', 'high')
REFERENCE = 'https://www.agy.dev/docs/cli/headless/'


def prepare_argon_candidate(existing_spec, capture):
    """Return a candidate only; do not infer missing slugs or alter old captures."""
    if (not isinstance(capture, dict) or set(capture) != {
            'schema', 'executable_sha256', 'version', 'catalog_sha256', 'model_slugs'}
            or capture['schema'] != 'cochem-agy-catalog-capture/1'):
        raise ValueError('Argon requires an exact captured CLI catalog')
    for key in ('executable_sha256', 'catalog_sha256'):
        if not isinstance(capture[key], str) or not re.fullmatch('[0-9a-f]{64}', capture[key]):
            raise ValueError('Catalog and executable require SHA256 bindings')
    slugs = capture['model_slugs']
    if (not isinstance(slugs, list) or not 1 <= len(slugs) <= 200
            or any(not isinstance(x, str) or not re.fullmatch('[a-z0-9][a-z0-9.-]{0,127}', x) for x in slugs)
            or len(set(slugs)) != len(slugs)):
        raise ValueError('Catalog slugs must be explicit, bounded and unique')
    spec = deepcopy(existing_spec)
    validate_model_bindings(spec)
    inference = spec.get('inference_only', {})
    if (capture['executable_sha256'] != inference.get('executable_sha256')
            or capture['version'] != inference.get('version')):
        raise ValueError('Catalog does not belong to the reviewed inference binary/version')
    probes, held = [], []
    for effort in EFFORTS:
        key, slug = f'{MODEL}:{effort}', f'{MODEL}-{effort}'
        if slug not in slugs:
            held.append(dict(model=MODEL, effort=effort, reason='NOT_IN_CAPTURED_CLI_CATALOG'))
            continue
        contract = dict(arguments=[], slug_effort=effort,
            executable_sha256=capture['executable_sha256'], version=capture['version'],
            version_arguments=deepcopy(inference['version_arguments']), capability_reference=REFERENCE,
            native_metadata=None, thinking_enabled=None)
        if key in spec.get('model_bindings', {}) and (
                spec['model_bindings'][key] != {'argv': slug, 'reports': slug}
                or spec.get('effort_contracts', {}).get(key) != contract):
            raise ValueError('Existing Argon binding differs; prepare a new reviewed catalog generation')
        spec.setdefault('model_bindings', {})[key] = dict(argv=slug, reports=slug)
        spec.setdefault('effort_contracts', {})[key] = contract
        effort_contract('gemini', MODEL, effort, spec)
        probes.append(dict(provider='gemini', model=MODEL, effort=effort, argv_slug=slug,
            reported_slug=slug, native_effort_observation='UNAVAILABLE',
            acceptance='REQUIRED', catalog_sha256=capture['catalog_sha256']))
    validate_model_bindings(spec)
    return dict(schema='cochem-argon-binding-proposal/1', input_spec_sha256=digest(existing_spec),
        capture_sha256=digest(capture), native_spec=spec, probes=probes, holds=held,
        activation_ready=False, provider_commands_executed=0)


def build_argon_owner_acceptance_spec(proposal: dict) -> dict:
    """Build the owner-run P428-28 acceptance specification from a prepared Argon proposal.

    This specification never marks a target host_accepted; physical CLI invocation
    and protected receipt publication belong exclusively to owner task P428-28.
    """
    if (not isinstance(proposal, dict)
            or proposal.get('schema') != 'cochem-argon-binding-proposal/1'
            or not isinstance(proposal.get('native_spec'), dict)
            or not isinstance(proposal.get('probes'), list)
            or not isinstance(proposal.get('holds'), list)):
        raise ValueError('Invalid Argon binding proposal')
    native_spec = proposal['native_spec']
    validate_model_bindings(native_spec)
    inference = native_spec.get('inference_only', {})
    from .agy_protocol import encode_prompt

    probe_plan = []
    for probe in proposal['probes']:
        effort = probe['effort']
        if effort not in EFFORTS:
            raise ValueError('Unsupported Argon probe effort')
        contract = effort_contract('gemini', MODEL, effort, native_spec)
        probe_plan.append(dict(
            provider='gemini',
            model=MODEL,
            reasoning_effort=effort,
            argv_slug=probe['argv_slug'],
            expected_reported_model=probe['reported_slug'],
            stdin_payload=encode_prompt(f'COCHEM_ARGON_ACCEPTANCE_PROBE:{MODEL}:{effort}'),
            executable_sha256=contract['executable_sha256'],
            expected_version=contract['version'],
            version_arguments=list(contract['version_arguments']),
            require_clean_diagnostics=True,
            forbid_tool_steps=True,
            require_process_cleanup=True,
            catalog_sha256=probe['catalog_sha256'],
        ))
    return dict(
        schema='cochem-argon-owner-acceptance-spec/4.2.8',
        proposal_sha256=digest(proposal),
        executable_sha256=inference.get('executable_sha256'),
        version=inference.get('version'),
        probe_plan=probe_plan,
        held_efforts=deepcopy(proposal['holds']),
        source_fixture_only=True,
        host_accepted=False,
        owner_acceptance_task='P428-28',
    )


def verify_argon_probe_fixture(
    proposal: dict,
    effort: str,
    *,
    raw_stdout: str,
    raw_stderr: str = '',
    exit_code: int = 0,
    binary_sha256: str,
    version_stdout: str,
    cleanup_verified: bool,
    use_agent_registry: bool = False,
    reservation_id: str = 'fixture-res-1',
    fencing_token: int = 1,
) -> dict:
    """Validate captured Agy protocol output for Argon Low/Medium/High without executing a CLI."""
    if not isinstance(proposal, dict) or proposal.get('schema') != 'cochem-argon-binding-proposal/1':
        raise ValueError('Argon probe verification requires a valid binding proposal')
    if not isinstance(effort, str) or effort not in EFFORTS:
        raise ValueError('Unsupported Argon reasoning effort level')
    if type(cleanup_verified) is not bool:
        raise ValueError('Explicit boolean cleanup_verified is required')
    if not isinstance(reservation_id, str) or not reservation_id or type(fencing_token) is not int or fencing_token < 1:
        raise ValueError('Argon probe verification requires valid reservation and fencing identity')

    native_spec = proposal['native_spec']
    key = f'{MODEL}:{effort}'
    if key not in native_spec.get('model_bindings', {}):
        return dict(
            schema='cochem-argon-protocol-verification/4.2.8',
            status='UNAVAILABLE_HELD',
            reason='NOT_IN_CAPTURED_CLI_CATALOG',
            provider='gemini',
            model=MODEL,
            reasoning_effort=effort,
            cleanup_verified=cleanup_verified,
            source_fixture_only=True,
            host_accepted=False,
        )

    contract = effort_contract('gemini', MODEL, effort, native_spec)
    from .native_effort import effort_version_evidence, reported_profile
    version_evidence = effort_version_evidence(
        contract, version_stdout, binary_sha256, model=MODEL, effort=effort
    )

    if not cleanup_verified:
        return dict(
            schema='cochem-argon-protocol-verification/4.2.8',
            status='QUARANTINED_UNCLEAN',
            reason='CLEANUP_UNVERIFIED',
            provider='gemini',
            model=MODEL,
            reasoning_effort=effort,
            cleanup_verified=False,
            source_fixture_only=True,
            host_accepted=False,
        )

    from .agy_protocol import (
        AgyIdentityError,
        AgyToolRegistryError,
        IDENTITY_POLICY,
        native_model_binding,
        parse_stream,
    )
    from .failures import parse_native_failure

    if exit_code != 0:
        failure = parse_native_failure('gemini', raw_stdout, raw_stderr, exit_code)
        category = failure.category if failure is not None else 'code'
        reason = failure.summary if failure is not None else 'Native CLI execution failed; protected logs require diagnosis'
        if category in ('auth', 'quota', 'busy', 'resource'):
            return dict(
                schema='cochem-argon-protocol-verification/4.2.8',
                status='AVAILABILITY_WAIT',
                category=category,
                reason=reason,
                provider='gemini',
                model=MODEL,
                reasoning_effort=effort,
                cleanup_verified=True,
                source_fixture_only=True,
                host_accepted=False,
            )
        return dict(
            schema='cochem-argon-protocol-verification/4.2.8',
            status='PROBE_FAILED',
            category=category,
            reason=reason,
            provider='gemini',
            model=MODEL,
            reasoning_effort=effort,
            cleanup_verified=True,
            source_fixture_only=True,
            host_accepted=False,
        )

    binding = native_model_binding(native_spec, MODEL, effort)
    try:
        parsed = parse_stream(
            raw_stdout,
            binding['reports'],
            identity_policy=IDENTITY_POLICY,
            stderr=raw_stderr,
            inference_spec=native_spec if use_agent_registry else None,
        )
    except AgyToolRegistryError as exc:
        return dict(
            schema='cochem-argon-protocol-verification/4.2.8',
            status='COMPATIBILITY_HOLD',
            category='compatibility',
            reason='AGY_TOOL_REGISTRY_VIOLATION',
            detail=str(exc),
            provider='gemini',
            model=MODEL,
            reasoning_effort=effort,
            cleanup_verified=True,
            source_fixture_only=True,
            host_accepted=False,
        )
    except AgyIdentityError as exc:
        return dict(
            schema='cochem-argon-protocol-verification/4.2.8',
            status='COMPATIBILITY_HOLD',
            category='compatibility',
            reason='AGY_IDENTITY_OR_FALLBACK_VIOLATION',
            detail=str(exc),
            provider='gemini',
            model=MODEL,
            reasoning_effort=effort,
            cleanup_verified=True,
            source_fixture_only=True,
            host_accepted=False,
        )

    effort_obs = reported_profile(
        'gemini', raw_stdout.splitlines()[-1], model=MODEL, effort=effort, spec=native_spec
    )
    return dict(
        schema='cochem-argon-protocol-verification/4.2.8',
        status='PROTOCOL_VERIFIED',
        provider='gemini',
        model=MODEL,
        reasoning_effort=effort,
        argv_slug=binding['argv'],
        reported_model=parsed['reported_model'],
        session_id=parsed['session_id'],
        binary_sha256=binary_sha256,
        version=version_evidence['version'],
        effort_observation=effort_obs,
        tool_registry=parsed['tool_registry'],
        cleanup_verified=True,
        reservation_id=reservation_id,
        fencing_token=fencing_token,
        source_fixture_only=True,
        host_accepted=False,
    )

