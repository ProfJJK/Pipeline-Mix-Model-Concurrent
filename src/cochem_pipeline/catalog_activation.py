"""R7 catalog-change preparation, without host authority or activation side effects.

This module is not exposed through the controller API. A parsed proposal alone
does not authorize activation: the Warden's protected-pointer, slot reservation,
native evidence and atomic durable publication still have to bind this plan.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .routing import RoutingPolicy, load_routing_policy
from .routing_catalog import validate_catalog


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _identity(entry):
    return entry['provider'], entry['model'], entry['reasoning_effort']


@dataclass(frozen=True)
class CatalogChange:
    previous_policy_digest: str
    policy: RoutingPolicy
    changed_targets: tuple[tuple[str, str, str], ...]
    control_target: tuple[str, str, str]

    def as_dict(self):
        return dict(schema='cochem-catalog-change-plan/1',
            previous_policy_digest=self.previous_policy_digest,
            candidate_policy_digest=self.policy.digest, policy=self.policy.as_dict(),
            changed_targets=[dict(zip(('provider', 'model', 'reasoning_effort'), value))
                for value in self.changed_targets],
            control_target=dict(zip(('provider', 'model', 'reasoning_effort'), self.control_target)),
            activation_authorized=False, native_acceptance_completed=False)

    @property
    def digest(self):
        return hashlib.sha256(_json(self.as_dict()).encode('utf-8')).hexdigest()


def compile_change(current: RoutingPolicy, proposed_catalog, *, expected_policy_digest: str) -> CatalogChange:
    """Prepare a generation transition while retaining operational budgets/caps.

    Caller-supplied expected state prevents silently rebasing a stale proposal.
    Existing job captures are never inputs to a mutation. Even changes involving
    only candidate order require a fresh generation and a control probe.
    """
    if not isinstance(current, RoutingPolicy) or current.digest != expected_policy_digest:
        raise ValueError('Catalog proposal does not name the current policy digest')
    raw = current.as_dict()
    if raw['policy_version'] != 3:
        raise ValueError('Hot catalog changes require an already installed v3 runtime')
    catalog = validate_catalog(proposed_catalog)
    if catalog['generation'] == raw['catalog']['generation']:
        raise ValueError('A catalog change needs a new immutable generation')
    old_targets = {_identity(entry) for rows in raw['tiers'].values() for entry in rows}
    new_targets = {_identity(entry) for rows in catalog['tiers'].values() for entry in rows}
    # Route-specific non-null limits cannot disappear as a side effect of retiring
    # a model. Their replacement policy needs a separately reviewed config change.
    new_keys = {':'.join(value) for value in new_targets}
    for key, value in raw['model_limits'].items():
        if key not in new_keys and value is not None:
            raise ValueError('Catalog change would discard an explicit model concurrency cap')
    raw['model_limits'] = {key: value for key, value in raw['model_limits'].items() if key in new_keys}
    raw['catalog'], raw['tiers'] = catalog, catalog['tiers']
    candidate = load_routing_policy(raw)
    control = _identity(current.as_dict()['tiers']['1'][0])
    return CatalogChange(current.digest, candidate, tuple(sorted(new_targets - old_targets)), control)


def decode_proposal(data: bytes, current: RoutingPolicy, *, expected_sha256: str) -> CatalogChange:
    """Bounded strict decoder; its hash is an input binding, not authority proof."""
    if not isinstance(data, bytes) or not 1 <= len(data) <= 1024 * 1024:
        raise ValueError('Catalog proposal exceeds its byte bound')
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError('Catalog proposal bytes differ from the protected pointer')
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate catalog proposal field')
            result[key] = value
        return result
    def reject_constant(value):
        raise ValueError('Nonfinite proposal value')
    raw = json.loads(data.decode('utf-8'), object_pairs_hook=unique, parse_constant=reject_constant)
    if not isinstance(raw, dict) or set(raw) != {'schema', 'previous_policy_digest', 'catalog'}:
        raise ValueError('Catalog proposal has unexpected fields')
    if raw['schema'] != 'cochem-catalog-change-request/1':
        raise ValueError('Unsupported catalog proposal schema')
    return compile_change(current, raw['catalog'], expected_policy_digest=raw['previous_policy_digest'])


def compile_task_catalog_change(
    current: RoutingPolicy,
    raw_task_catalog,
    binary_bindings,
    *,
    expected_policy_digest: str,
    previous_task_catalog=None,
    candidate_profile_ids=None,
    retired_profile_ids=(),
    model_limits=None,
):
    """Prepare a 4.2.8 task-matrix catalog binding plan under the current v3 policy."""
    from .task_catalog_428 import compile_task_catalog_plan

    return compile_task_catalog_plan(
        current,
        raw_task_catalog,
        binary_bindings,
        expected_policy_digest=expected_policy_digest,
        previous_task_catalog=previous_task_catalog,
        candidate_profile_ids=candidate_profile_ids,
        retired_profile_ids=retired_profile_ids,
        model_limits=model_limits,
    )

