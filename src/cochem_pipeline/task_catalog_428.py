"""Bind 4.2.8 task-routing profiles to protected live catalog authority (`P428-03`).

Chapter 06 admission only dispatches targets backed by the active protected
catalog generation and verified native selector acceptance receipts. Research
candidates (`host_accepted=False`) and profiles with missing benchmark scores
cannot be admitted. Retiring a target in a new catalog generation immediately
prevents new reservations while preserving historical job captures immutably.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import re
import time
from typing import Any

from .routing import RoutingPolicy, load_routing_policy
from .task_routing import TASK_TYPES, digest


_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_REQ32 = re.compile(r"[0-9a-f]{32}\Z")
_PROVIDERS = ("codex", "claude", "gemini")
# Typed, cleanly closed per-target probe failures that exclude only their own
# target under the reviewed partial-publication policy (never routable).
PROBE_FAILURE_CATEGORIES = frozenset({'auth', 'context', 'timeout', 'protocol', 'code', 'configuration',
                                      'compatibility', 'resource', 'output_format', 'validation'})
_NATIVE_FAILURE_FIELDS = {'exit_code', 'envelope_kind', 'claude_result_subtype', 'api_status'}


def _native_failure_facts(value):
    """Allowlisted typed facts copied from the protected failure metadata."""
    if value is None:
        return None
    if (not isinstance(value, dict) or not set(value) <= _NATIVE_FAILURE_FIELDS
            or any(value.get(key) is not None and (type(value[key]) is not int or not -2**31 <= value[key] < 2**32)
                   for key in ('exit_code', 'api_status'))
            or any(value.get(key) is not None and (not isinstance(value[key], str)
                   or not re.fullmatch(r'[a-z0-9_]{1,40}', value[key])) for key in ('envelope_kind', 'claude_result_subtype'))):
        raise ValueError('Native probe failure facts are outside their allowlist')
    return {key: value.get(key) for key in sorted(_NATIVE_FAILURE_FIELDS)}
_EXPLICITLY_RETIRED_TARGETS = frozenset({
    ("gemini", "gemini-3.1-pro", "high"),
    ("gemini", "gemini-3.1-pro", None),
})


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _target_tuple(entry: dict[str, Any]) -> tuple[str, str, str | None]:
    return (entry["provider"], entry["model"], entry.get("reasoning_effort") or entry.get("effort"))


def _target_key(provider: str, model: str, effort: str | None) -> str:
    return f"{provider}:{model}" + (f":{effort}" if effort is not None else "")


def validate_binary_bindings(binary_bindings: Any) -> dict[str, dict[str, str]]:
    if not isinstance(binary_bindings, dict) or set(binary_bindings) != set(_PROVIDERS):
        raise ValueError("Task catalog activation requires binary bindings for codex, claude and gemini")
    normalized: dict[str, dict[str, str]] = {}
    for provider in _PROVIDERS:
        spec = binary_bindings[provider]
        if not isinstance(spec, dict) or set(spec) != {"executable", "sha256", "version"}:
            raise ValueError(f"Binary binding for {provider} requires executable, sha256 and version")
        executable = spec["executable"]
        sha256 = spec["sha256"]
        version = spec["version"]
        if (not isinstance(executable, str) or not executable.strip() or "\x00" in executable
                or not isinstance(sha256, str) or not _HEX64.fullmatch(sha256)
                or not isinstance(version, str) or not version.strip() or "\x00" in version):
            raise ValueError(f"Invalid binary identity fields for {provider}")
        normalized[provider] = {
            "executable": executable,
            "sha256": sha256,
            "version": version,
        }
    return normalized


@dataclass(frozen=True)
class TaskCatalogBindingPlan:
    previous_policy_digest: str
    previous_task_catalog_sha256: str | None
    policy: RoutingPolicy
    candidate_catalog: dict[str, Any]
    binary_bindings: dict[str, dict[str, str]]
    selected_profile_ids: tuple[str, ...]
    required_targets: tuple[tuple[str, str, str], ...]
    retired_targets: tuple[tuple[str, str, str | None], ...]
    control_target: tuple[str, str, str]
    model_limits: dict[str, int | None]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "cochem-task-catalog-binding-plan/4.2.8",
            "previous_policy_digest": self.previous_policy_digest,
            "previous_task_catalog_sha256": self.previous_task_catalog_sha256,
            "candidate_policy_digest": self.policy.digest,
            "candidate_catalog_sha256": digest(self.candidate_catalog),
            "binary_bindings": deepcopy(self.binary_bindings),
            "selected_profile_ids": list(self.selected_profile_ids),
            "required_targets": [
                {"provider": p, "model": m, "reasoning_effort": e}
                for p, m, e in self.required_targets
            ],
            "retired_targets": [
                {"provider": p, "model": m, "reasoning_effort": e}
                for p, m, e in self.retired_targets
            ],
            "control_target": dict(zip(("provider", "model", "reasoning_effort"), self.control_target)),
            "model_limits": dict(self.model_limits),
            "activation_authorized": False,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.as_dict()).encode("utf-8")).hexdigest()


def compile_task_catalog_plan(
    current_policy: RoutingPolicy,
    raw_task_catalog: dict[str, Any],
    binary_bindings: dict[str, dict[str, str]],
    *,
    expected_policy_digest: str,
    previous_task_catalog: dict[str, Any] | None = None,
    candidate_profile_ids: list[str] | tuple[str, ...] | set[str] | None = None,
    retired_profile_ids: list[str] | tuple[str, ...] | set[str] = (),
    model_limits: dict[str, int | None] | None = None,
) -> TaskCatalogBindingPlan:
    """Prepare a 4.2.8 task-catalog binding plan under the current v3 policy."""
    if not isinstance(current_policy, RoutingPolicy) or current_policy.digest != expected_policy_digest:
        raise ValueError("Task catalog plan does not match the expected active policy digest")
    policy_raw = current_policy.as_dict()
    if policy_raw.get("policy_version") != 3:
        raise ValueError("Task catalog binding requires an active v3 routing policy")
    if (not isinstance(raw_task_catalog, dict)
            or raw_task_catalog.get("schema") != "cochem-task-routing/1"
            or raw_task_catalog.get("scores_verified") is not True
            or not isinstance(raw_task_catalog.get("models"), dict)
            or not isinstance(raw_task_catalog.get("task_types"), dict)
            or set(raw_task_catalog["task_types"]) != set(TASK_TYPES)):
        raise ValueError("Task catalog activation requires a publisher-verified 4.2.8 task catalog")

    validated_binaries = validate_binary_bindings(binary_bindings)
    models = raw_task_catalog["models"]
    retired_ids = set(retired_profile_ids)
    if any(pid not in models for pid in retired_ids):
        raise ValueError("Retired profile ID is unknown in task catalog")

    if candidate_profile_ids is None:
        selected_ids = sorted(
            pid for pid, m in models.items()
            if m.get("score_evidence") == "PUBLISHER_OBSERVED"
            and m.get("effort") is not None
            and pid not in retired_ids
        )
    else:
        if not candidate_profile_ids:
            raise ValueError("At least one candidate profile ID is required")
        selected_ids = sorted(set(candidate_profile_ids))
        for pid in selected_ids:
            if pid not in models:
                raise ValueError(f"Unknown candidate profile ID: {pid}")
            if pid in retired_ids:
                raise ValueError(f"Profile {pid} cannot be both selected and retired")
            model = models[pid]
            if (model.get("score_evidence") != "PUBLISHER_OBSERVED"
                    or model.get("effort") is None
                    or any(model.get("scores", {}).get(tag) is None for tag in TASK_TYPES)):
                raise ValueError(f"Profile {pid} lacks complete verified publisher benchmark scores")

    tier_targets = {
        (entry["provider"], entry["model"], entry["reasoning_effort"])
        for rows in policy_raw["tiers"].values()
        for entry in rows
    }
    selected_targets: set[tuple[str, str, str]] = set()
    for pid in selected_ids:
        model = models[pid]
        target = (model["provider"], model["model"], model["effort"])
        if target in _EXPLICITLY_RETIRED_TARGETS:
            raise ValueError(f"Explicitly retired target cannot be reactivated: {target}")
        selected_targets.add(target)

    retired_target_set: set[tuple[str, str, str | None]] = set(_EXPLICITLY_RETIRED_TARGETS)
    for pid in retired_ids:
        m = models[pid]
        retired_target_set.add((m["provider"], m["model"], m.get("effort")))

    prev_sha: str | None = None
    if previous_task_catalog is not None:
        if (not isinstance(previous_task_catalog, dict)
                or previous_task_catalog.get("schema") != "cochem-task-routing/1"
                or previous_task_catalog.get("host_accepted") is not True):
            raise ValueError("Previous task catalog must be a host-accepted 4.2.8 catalog")
        prev_sha = digest(previous_task_catalog)
        if previous_task_catalog.get("generation") == raw_task_catalog.get("generation"):
            raise ValueError("Task catalog update requires a new generation identifier")
        for entry in previous_task_catalog.get("accepted_targets", []):
            prev_target = (entry["provider"], entry["model"], entry.get("reasoning_effort"))
            if prev_target not in selected_targets and prev_target not in tier_targets:
                retired_target_set.add(prev_target)

    all_active_keys = {_target_key(p, m, e) for p, m, e in (tier_targets | selected_targets)}
    merged_limits = {key: policy_raw["model_limits"].get(key) for key in sorted(all_active_keys)}
    if model_limits is not None:
        if not isinstance(model_limits, dict) or set(model_limits) - all_active_keys:
            raise ValueError("Task catalog model_limits must reference active target keys")
        for key, limit in model_limits.items():
            if limit is not None and (type(limit) is not int or not 1 <= limit <= 1000000):
                raise ValueError(f"Invalid model concurrency cap for {key}")
            merged_limits[key] = limit
    for key, existing_limit in policy_raw["model_limits"].items():
        if existing_limit is not None and merged_limits.get(key) is None:
            raise ValueError(f"Task catalog plan cannot discard existing concurrency cap for {key}")

    control = (
        policy_raw["tiers"]["1"][0]["provider"],
        policy_raw["tiers"]["1"][0]["model"],
        policy_raw["tiers"]["1"][0]["reasoning_effort"],
    )
    # Tier membership alone is not evidence that the currently bound CLI binary
    # accepted this exact effort. A fresh task-catalog publication proves all
    # selected profiles, including identities already in the older tier catalog.
    required = tuple(sorted(selected_targets | {control}))
    return TaskCatalogBindingPlan(
        previous_policy_digest=current_policy.digest,
        previous_task_catalog_sha256=prev_sha,
        policy=current_policy,
        candidate_catalog=deepcopy(raw_task_catalog),
        binary_bindings=validated_binaries,
        selected_profile_ids=tuple(selected_ids),
        required_targets=required,
        retired_targets=tuple(sorted(retired_target_set, key=lambda item: (item[0], item[1], item[2] or ""))),
        control_target=control,
        model_limits=merged_limits,
    )


def activate_task_catalog(
    plan: TaskCatalogBindingPlan,
    native_receipts: list[dict[str, Any]],
    *,
    request_id: str,
    pointer_sha256: str,
    proposal_sha256: str,
    generation_override: str | None = None,
    unprobed_holds: list[dict[str, Any]] | None = None,
    allow_partial_publication: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Bind verified native probe receipts to produce an accepted 4.2.8 task catalog."""
    if not isinstance(plan, TaskCatalogBindingPlan):
        raise ValueError("TaskCatalogBindingPlan is required")
    if not isinstance(request_id, str) or not _REQ32.fullmatch(request_id):
        raise ValueError("Task catalog request_id must be 32 lowercase hex chars")
    if not isinstance(pointer_sha256, str) or not _HEX64.fullmatch(pointer_sha256):
        raise ValueError("Task catalog pointer_sha256 must be 64 lowercase hex chars")
    if not isinstance(proposal_sha256, str) or not _HEX64.fullmatch(proposal_sha256):
        raise ValueError("Task catalog proposal_sha256 must be 64 lowercase hex chars")

    expected = set(plan.required_targets) | {plan.control_target}
    if type(allow_partial_publication) is not bool:
        raise ValueError('Explicit task catalog partial publication policy required')
    holds = unprobed_holds or []
    if not isinstance(holds, list) or (holds and not allow_partial_publication):
        raise ValueError('Unprobed target holds require reviewed partial publication policy')
    if not isinstance(native_receipts, list) or len(native_receipts) + len(holds) != len(expected):
        raise ValueError("Task catalog native receipts must cover every required target exactly once")

    seen: set[tuple[str, str, str]] = set()
    verified_by_target: dict[tuple[str, str, str], dict[str, Any]] = {}
    sanitized_proofs: list[dict[str, Any]] = []
    for receipt in native_receipts:
        if not isinstance(receipt, dict):
            raise ValueError("Invalid native selector receipt")
        key = (receipt.get("provider"), receipt.get("model"), receipt.get("reasoning_effort"))
        if (any(not isinstance(v, str) or not v for v in key)
                or key not in expected
                or key in seen
                or receipt.get("status") not in ("NATIVE_SELECTOR_ACCEPTED", "AVAILABILITY_WAIT", "NATIVE_PROBE_FAILED")
                or receipt.get("cleanup_verified") is not True
                or receipt.get("plan_digest") != plan.digest
                or receipt.get("request_id") != request_id
                or not isinstance(receipt.get("reservation_id"), str) or not receipt["reservation_id"]
                or type(receipt.get("fencing_token")) is not int or receipt["fencing_token"] < 1):
            raise ValueError("Task catalog native receipt identity, cleanup or reservation binding differs")
        if (receipt['status'] == 'AVAILABILITY_WAIT'
                and (not allow_partial_publication or receipt.get('failure_category') not in ('quota', 'busy', 'provider'))):
            raise ValueError('Task catalog deferral requires typed provider availability evidence')
        if (receipt['status'] == 'NATIVE_PROBE_FAILED'
                and (not allow_partial_publication or receipt.get('failure_category') not in PROBE_FAILURE_CATEGORIES)):
            raise ValueError('Task catalog exclusion requires typed, cleaned native probe failure evidence')
        provider = key[0]
        expected_bin_sha = plan.binary_bindings[provider]["sha256"]
        if receipt.get("binary_sha256") != expected_bin_sha:
            raise ValueError(f"Native receipt binary_sha256 for {provider} does not match bound executable")
        seen.add(key)
        sanitized = {
            "provider": key[0],
            "model": key[1],
            "reasoning_effort": key[2],
            "binary_sha256": expected_bin_sha,
            "status": receipt['status'],
            "cleanup_verified": True,
            "plan_digest": plan.digest,
            "request_id": request_id,
            "reservation_id": receipt["reservation_id"],
            "fencing_token": receipt["fencing_token"],
        }
        if receipt['status'] == 'AVAILABILITY_WAIT':
            sanitized['failure_category'] = receipt['failure_category']
        if receipt['status'] == 'NATIVE_PROBE_FAILED':
            sanitized['failure_category'] = receipt['failure_category']
            sanitized['native_failure'] = _native_failure_facts(receipt.get('native_failure'))
        if 'execution_binding' in receipt:
            binding = receipt['execution_binding']
            if (not isinstance(binding,dict) or set(binding) != {
                    'provider_contract_sha256','agent_contract_sha256','worker_profiles_sha256'}
                    or any(not isinstance(binding.get(name),str) or not _HEX64.fullmatch(binding[name])
                           for name in ('provider_contract_sha256','worker_profiles_sha256'))
                    or (key[0]=='gemini' and (not isinstance(binding.get('agent_contract_sha256'),str)
                        or not _HEX64.fullmatch(binding['agent_contract_sha256'])))
                    or (key[0]!='gemini' and binding.get('agent_contract_sha256') is not None)):
                raise ValueError('Native receipt provider/agent/profile contract differs')
            sanitized['execution_binding'] = deepcopy(binding)
        verified_by_target[key] = sanitized
        sanitized_proofs.append(sanitized)

    # These are controller hold snapshots, never native success receipts. The
    # publication coordinator binds them to protected Chapter 06 hold rows.
    for hold in holds:
        key = (hold.get('provider'), hold.get('model'), hold.get('reasoning_effort'))
        scope = hold.get('scope')
        resources = {'model': ':'.join(key) if all(isinstance(v,str) for v in key) else None,
                     'provider': key[0],
                     'pool': plan.policy.as_dict()['provider_limits'].get(key[0],{}).get('quota_pool')}
        if (key not in expected or key in seen or hold.get('status') != 'AVAILABILITY_WAIT_UNTESTED'
                or hold.get('request_id') != request_id or hold.get('plan_digest') != plan.digest
                or hold.get('failure_category') not in ('quota','busy','provider')
                or scope not in resources or hold.get('resource_key') != resources[scope]
                or type(hold.get('until_at')) not in (int,float) or not math.isfinite(hold['until_at'])
                or type(hold.get('updated_at')) not in (int,float) or not math.isfinite(hold['updated_at'])
                or hold['until_at'] <= hold['updated_at']
                or hold.get('native_probe_executed') is not False):
            raise ValueError('Unprobed task catalog target lacks a bound availability hold')
        sanitized = {name: hold[name] for name in (
            'provider','model','reasoning_effort','status','request_id','plan_digest',
            'scope','resource_key','failure_category','until_at','updated_at','native_probe_executed')}
        seen.add(key)
        verified_by_target[key] = sanitized
        sanitized_proofs.append(sanitized)

    sanitized_proofs.sort(key=lambda r: (r["provider"], r["model"], r["reasoning_effort"]))
    catalog = deepcopy(plan.candidate_catalog)
    generation = generation_override or f"{catalog['generation']}-accepted-{request_id[:8]}"
    accepted_profile_ids: list[str] = []
    accepted_targets: set[tuple[str, str, str]] = set()
    retired_set = set(plan.retired_targets)

    for pid, model in sorted(catalog["models"].items()):
        target = (model["provider"], model["model"], model.get("effort"))
        if (pid in plan.selected_profile_ids and target not in retired_set
                and verified_by_target.get(target, {}).get('status') == 'NATIVE_SELECTOR_ACCEPTED'):
            proof = verified_by_target.get(target)
            bin_info = plan.binary_bindings[model["provider"]]
            model["native_acceptance"] = "ACCEPTED"
            model["accepted_binary_path"] = bin_info["executable"]
            model["accepted_binary_sha256"] = bin_info["sha256"]
            model["accepted_binary_version"] = bin_info["version"]
            model["accepted_receipt_sha256"] = digest(proof)
            if 'execution_binding' in proof:
                model['accepted_execution_binding'] = deepcopy(proof['execution_binding'])
            accepted_profile_ids.append(pid)
            accepted_targets.add(target)
        else:
            deferred = verified_by_target.get(target, {}).get('status') in (
                'AVAILABILITY_WAIT', 'AVAILABILITY_WAIT_UNTESTED')
            model["native_acceptance"] = ("RETIRED" if target in retired_set else
                                          "AVAILABILITY_WAIT" if deferred else "NOT_ACCEPTED")
            if deferred:
                model['availability_category'] = verified_by_target[target]['failure_category']
                model['availability_evidence'] = verified_by_target[target]['status']
            elif verified_by_target.get(target, {}).get('status') == 'NATIVE_PROBE_FAILED':
                model['native_probe_failure'] = verified_by_target[target]['failure_category']
    if not accepted_profile_ids:
        raise ValueError('Task catalog publication requires at least one accepted profile')

    for tag, spec in catalog["task_types"].items():
        for tier_str, row in spec["tiers"].items():
            row["choices"] = [
                pid for pid in row["choices"]
                if pid in accepted_profile_ids
                and catalog["models"][pid]["scores"][tag] is not None
                and catalog["models"][pid]["scores"][tag] >= row["floor"]
            ]
            if "ranked_options" in row:
                for opt in row["ranked_options"]:
                    opt["native_acceptance"] = catalog["models"][opt["model_id"]]["native_acceptance"]

    catalog.update(
        generation=generation,
        host_accepted=True,
        publication_policy=dict(allow_partial_publication=allow_partial_publication,
                                unprobed_held_targets=len(holds),
                                native_probe_failures=sum(1 for proof in sanitized_proofs
                                                          if proof['status'] == 'NATIVE_PROBE_FAILED')),
        policy_digest=plan.policy.digest,
        previous_task_catalog_sha256=plan.previous_task_catalog_sha256,
        request_id=request_id,
        plan_digest=plan.digest,
        pointer_sha256=pointer_sha256,
        proposal_sha256=proposal_sha256,
        binary_bindings=deepcopy(plan.binary_bindings),
        accepted_profile_ids=accepted_profile_ids,
        accepted_targets=[
            {
                "provider": p,
                "model": m,
                "reasoning_effort": e,
                "key": _target_key(p, m, e),
            }
            for p, m, e in sorted(accepted_targets)
        ],
        retired_targets=[
            {
                "provider": p,
                "model": m,
                "reasoning_effort": e,
                "key": _target_key(p, m, e),
            }
            for p, m, e in plan.retired_targets
        ],
        model_limits=dict(plan.model_limits),
    )
    return catalog, sanitized_proofs


def active_accepted_target_set(
    current_policy: dict[str, Any] | RoutingPolicy,
    task_catalog: dict[str, Any] | None = None,
) -> set[tuple[str, str, str | None]]:
    """Return the exact accepted (provider, model, effort) tuples for admission."""
    policy_raw = current_policy.as_dict() if hasattr(current_policy, "as_dict") else current_policy
    policy_digest = (
        current_policy.digest
        if hasattr(current_policy, "digest")
        else load_routing_policy(policy_raw).digest
    )
    tier_targets: set[tuple[str, str, str | None]] = {
        (entry["provider"], entry["model"], entry.get("reasoning_effort"))
        for rows in policy_raw["tiers"].values()
        for entry in rows
    }
    if task_catalog is None:
        return tier_targets - _EXPLICITLY_RETIRED_TARGETS
    if (not isinstance(task_catalog, dict)
            or task_catalog.get("schema") != "cochem-task-routing/1"
            or task_catalog.get("host_accepted") is not True):
        raise ValueError("Task catalog admission requires a host-accepted 4.2.8 catalog")
    bound_digest = task_catalog.get("policy_digest")
    if bound_digest is not None and bound_digest != policy_digest:
        raise ValueError("Active task catalog is stale relative to active routing policy digest")
    retired = set(_EXPLICITLY_RETIRED_TARGETS)
    for entry in task_catalog.get("retired_targets", []):
        retired.add((entry["provider"], entry["model"], entry.get("reasoning_effort")))
    unaccepted = {
        (m.get("provider"), m.get("model"), m.get("effort"))
        for m in task_catalog.get("models", {}).values()
        if m.get("native_acceptance") != "ACCEPTED"
    }
    accepted = set(tier_targets) - unaccepted
    for m in task_catalog.get("models", {}).values():
        if m.get("native_acceptance") == "ACCEPTED" and not m.get("retired") and m.get("effort") is not None:
            accepted.add((m.get("provider"), m.get("model"), m.get("effort")))
    for entry in task_catalog.get("accepted_targets", []):
        accepted.add((entry["provider"], entry["model"], entry.get("reasoning_effort")))
    return accepted - retired


def build_admission_policy_view(
    current_policy: dict[str, Any] | RoutingPolicy,
    task_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an admission policy dictionary uniting active v3 tiers and accepted 4.2.8 targets."""
    policy_raw = deepcopy(current_policy.as_dict() if hasattr(current_policy, "as_dict") else current_policy)
    if task_catalog is None:
        return policy_raw
    accepted = active_accepted_target_set(current_policy, task_catalog)
    extra_entries = [
        {"provider": p, "model": m, "reasoning_effort": e}
        for p, m, e in sorted(accepted, key=lambda item: (item[0], item[1], item[2] or ""))
    ]
    policy_raw["tiers"] = {
        tier: [
            entry for entry in rows
            if (entry["provider"], entry["model"], entry.get("reasoning_effort")) in accepted
        ] + [
            entry for entry in extra_entries
            if entry not in rows
        ]
        for tier, rows in policy_raw["tiers"].items()
    }
    task_limits = task_catalog.get("model_limits") or {}
    for key, limit in task_limits.items():
        if key not in policy_raw["model_limits"] or policy_raw["model_limits"][key] is None:
            policy_raw["model_limits"][key] = limit
    return policy_raw


def classify_target_status(
    target: dict[str, Any] | tuple[str, str, str | None],
    current_policy: dict[str, Any] | RoutingPolicy,
    task_catalog: dict[str, Any] | None = None,
) -> str | None:
    """Return None if target is active/accepted, 'retired_target', or 'unaccepted_target'."""
    if isinstance(target, dict):
        tup = (target["provider"], target["model"], target.get("reasoning_effort"))
    else:
        tup = (target[0], target[1], target[2])
    if tup in _EXPLICITLY_RETIRED_TARGETS:
        return "retired_target"
    if task_catalog is not None:
        retired = {
            (e["provider"], e["model"], e.get("reasoning_effort"))
            for e in task_catalog.get("retired_targets", [])
        }
        if tup in retired:
            return "retired_target"
        accepted = active_accepted_target_set(current_policy, task_catalog)
        if tup in accepted:
            return None
        for model in task_catalog.get("models", {}).values():
            if (model.get("provider"), model.get("model"), model.get("effort")) == tup:
                return "retired_target" if model.get("native_acceptance") == "RETIRED" else "unaccepted_target"
        return "retired_target"
    accepted_only_policy = active_accepted_target_set(current_policy, None)
    return None if tup in accepted_only_policy else "retired_target"


def task_catalog_authority(conn, job: dict[str, Any]) -> dict[str, Any]:
    """Bind a planning capture to protected history and return live authority.

    A publisher score or a job's ``host_accepted`` flag is not authorization.
    Old accepted captures remain valid records, while the current generation
    controls which exact targets may start now. The caller owns the read/write
    transaction so publication cannot split the history and active reads.
    """
    from .catalog_journal import active_task_catalog

    if conn is None or not conn.in_transaction:
        raise ValueError('Task catalog authority requires the caller transaction')
    captured = job.get('payload', {}).get('task_catalog')
    if (not isinstance(captured, dict) or captured.get('schema') != 'cochem-task-routing/1'
            or captured.get('host_accepted') is not True):
        raise ValueError('Planning capture is not an accepted task catalog')
    active = active_task_catalog(conn)
    if active is None:
        raise ValueError('No protected active task catalog is installed')
    captured_digest = digest(captured)
    row = conn.execute('''SELECT catalog_json, policy_digest FROM pipeline_task_catalog_generations
        WHERE catalog_sha256=?''', (captured_digest,)).fetchone()
    if row is None:
        raise ValueError('Planning catalog capture is absent from protected history')
    historical = json.loads(row[0])
    if (digest(historical) != captured_digest or historical != captured
            or historical.get('host_accepted') is not True
            or historical.get('policy_digest', row[1]) != row[1]):
        raise ValueError('Planning catalog capture differs from protected history')
    return active


def initialize_task_catalog_authority(store, planning_config) -> dict[str, Any]:
    """Adopt the exact protected installation baseline without replacing history."""
    from .catalog_journal import initialize_task_catalog, active_policy, active_task_catalog

    if not getattr(store, '_catalog_enabled', False):
        raise ValueError('Task planning requires protected catalog journal activation')
    installed = planning_config.read_catalog()
    with store._write() as conn:
        initialize_task_catalog(conn, installed)
        current = active_task_catalog(conn)
        if current is None:
            raise ValueError('Task catalog initialization produced no active authority')
        active_accepted_target_set(active_policy(conn), current)
        return current


def check_task_target_admission(
    conn,
    job: dict[str, Any],
    state: dict[str, Any],
    target: dict[str, Any],
    current_policy: dict[str, Any] | RoutingPolicy,
    *,
    task_catalog: dict[str, Any] | None = None,
    now: float | None = None,
) -> str | None:
    """Evaluate target eligibility and shared-slot/cap/pool admission without bypassing retirement."""
    from . import routing_store as routes

    observed = time.time() if now is None else now
    if job.get('kind') == 'TASK_PLAN':
        # The board journal, never this optional convenience argument, is the
        # planning admission authority. Pass the unmodified policy for its pin.
        policy = current_policy.as_dict() if isinstance(current_policy, RoutingPolicy) else current_policy
        return routes._candidate_unavailability(conn, job, state, target, policy, observed)
    status = classify_target_status(target, current_policy, task_catalog)
    if status is not None:
        return status
    admission_view = build_admission_policy_view(current_policy, task_catalog)
    return routes._candidate_unavailability(conn, job, state, target, admission_view, observed)
