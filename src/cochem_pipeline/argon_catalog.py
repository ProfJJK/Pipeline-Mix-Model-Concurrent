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
