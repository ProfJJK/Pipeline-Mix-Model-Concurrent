"""Two-Staged Concurrency, Conflict-Colored Provider Batching, and Intra-Slot Agent Swarm (`P428-SWARM`).

Implements:
- Layer-2 OS Execution Slots (`slot1`..`slot4`, 6 GiB RAM, 4096 MiB V8 heap, 96 processes per slot)
  paired with Layer-1 Intra-Slot Native Subagent Swarms (`claude` up to 20 agents / depth 3,
  `codex` up to 20 agents / depth 2, `gemini`/Agy up to 64 agents / depth 2).
- Conflict-Colored Wave Packing:
  - Case B (Disjoint Files): Ready microtasks with zero dependency overlap and strictly disjoint
    file footprints (`files(M_i) ∩ files(M_j) == ∅`) pack by provider family up to `max_agents_per_slot`,
    where each subagent executes at its microtask's exact routed `(model, reasoning_effort)` tier.
  - Case C (Shared / Overlapping Files): At most 1 representative task from any overlapping file
    group is admitted and locks its file footprint globally across all 4 slots in `microtask428_file_locks`;
    all other tasks touching those files are held in `WAITING_ON_FILE_LOCK` (`job_id=None`) until the
    active holder completes and releases the lock.
- Partial-Batch Per-Microtask Commit & Failure Isolation:
  - In a batch of `N` microtasks where `k` succeed and `N - k` fail, the `k` valid microtasks
    commit `COMPLETED` immediately and release their file locks, while only the `N - k` failed
    microtasks record individual `AttemptLedger` quality failures (10/20/30 accounting) and re-queue.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping

from .task_routing import digest, five_model_options
from .workflow_428 import _id, _text


MAX_OS_SLOTS = 4

PROVIDER_SWARM_PROFILES: dict[str, dict[str, Any]] = {
    "claude": {
        "provider": "claude",
        "max_agents_per_slot": 20,
        "max_nesting_depth": 3,
        "max_slots": MAX_OS_SLOTS,
        "max_total_agents": 20 * MAX_OS_SLOTS,
    },
    "codex": {
        "provider": "codex",
        "max_agents_per_slot": 20,
        "max_nesting_depth": 2,
        "max_slots": MAX_OS_SLOTS,
        "max_total_agents": 20 * MAX_OS_SLOTS,
    },
    "gemini": {
        "provider": "gemini",
        "max_agents_per_slot": 64,
        "max_nesting_depth": 2,
        "max_slots": MAX_OS_SLOTS,
        "max_total_agents": 64 * MAX_OS_SLOTS,
    },
}


def normalize_provider_family(provider: str) -> str:
    """Normalize provider identifier (`claude`, `codex`, `gemini` / `agy`)."""
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError("Provider family must be a non-empty string")
    cleaned = provider.strip().lower()
    alias_map = {
        "agy": "gemini",
        "google": "gemini",
        "openai": "codex",
        "anthropic": "claude",
    }
    cleaned = alias_map.get(cleaned, cleaned)
    if cleaned not in PROVIDER_SWARM_PROFILES:
        raise ValueError(f"Unsupported swarm provider family: {provider}")
    return cleaned


def get_provider_swarm_profile(provider: str) -> dict[str, Any]:
    """Return the per-slot swarm agent and nesting cap profile for `provider`."""
    family = normalize_provider_family(provider)
    return deepcopy(PROVIDER_SWARM_PROFILES[family])


def normalize_file_target(path: str) -> str:
    """Normalize a deliverable or file target path for cross-slot lock comparison."""
    raw = _text(path, "Microtask file target", 512).strip().replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if raw.startswith("/") or ":" in raw:
        raise ValueError(f"Invalid microtask file target path: {path}")
    raw = re.sub(r"/+", "/", raw).rstrip("/")
    parts = [part for part in raw.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in raw.split("/")):
        raise ValueError(f"Invalid microtask file target path: {path}")
    return "/".join(parts)


def extract_microtask_files(node: Mapping[str, Any]) -> list[str]:
    """Extract sorted, deduplicated normalized file targets from a microtask node."""
    if not isinstance(node, Mapping):
        raise ValueError("Microtask node must be a mapping")
    collected: set[str] = set()
    for field in ("deliverables", "file_targets", "shared_files"):
        items = node.get(field)
        if items is None:
            continue
        if not isinstance(items, (list, tuple, set)):
            raise ValueError(f"Microtask field {field} must be a sequence of file paths")
        for item in items:
            collected.add(normalize_file_target(item))
    if not collected:
        raise ValueError(
            f"Microtask {node.get('microtask_id') or node.get('id')} must declare at least one file target or deliverable"
        )
    return sorted(collected)


def resolve_microtask_route_tier(
    node: Mapping[str, Any],
    catalog: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve the candidate profiles and primary `(provider, model, reasoning_effort)` tier for `node`."""
    mt_id = str(node.get("microtask_id") or node.get("id") or "")
    _id(mt_id)
    effective_complexity = max(
        int(node["complexity"]),
        int(node.get("effective_complexity") or node["complexity"]),
    )
    options = five_model_options(dict(catalog), list(node["task_types"]), effective_complexity)
    candidates = [opt["model_id"] for opt in options if opt["meets_floor"]]
    if not candidates:
        raise ValueError(f"No eligible profiles meet the floor for microtask {mt_id}")
    models_map = catalog.get("models") or {}
    explicit_primary = node.get("routed_profile_id")
    pivot_model = node.get("pivot_model")
    if isinstance(pivot_model, str) and pivot_model:
        eligible = []
        for cid in dict.fromkeys(candidates + list(models_map)):
            spec = models_map[cid]
            if pivot_model not in (cid, spec.get('model'), spec.get('family')):
                continue
            if not all(spec.get('scores', {}).get(tag) is not None
                       and spec['scores'][tag] >= catalog['task_types'][tag]['tiers'][str(effective_complexity)]['floor']
                       for tag in node['task_types']):
                continue
            if effective_complexity == 10 and spec['effort'] != ('high' if spec['provider'] == 'gemini' else 'max'):
                continue
            eligible.append(cid)
        if not eligible:
            raise ValueError('Pivot profile does not meet the captured reasoning floor')
        # The first post-pivot attempt must use the committed different family.
        # Availability waits do not silently spend that attempt on another route.
        explicit_primary = eligible[0]
        candidates = [explicit_primary]
    if isinstance(explicit_primary, str) and explicit_primary in models_map:
        primary_id = explicit_primary
        if primary_id not in candidates:
            candidates = [primary_id, *candidates]
        else:
            candidates = [primary_id, *[c for c in candidates if c != primary_id]]
    else:
        primary_id = candidates[0]
    if primary_id not in models_map:
        raise ValueError(f"Primary candidate profile {primary_id} not found in catalog")
    primary_spec = models_map[primary_id]
    provider_family = normalize_provider_family(primary_spec["provider"])
    same_provider_candidates = [
        cid
        for cid in candidates
        if normalize_provider_family(models_map[cid]["provider"]) == provider_family
    ]
    return {
        "microtask_id": mt_id,
        "candidate_profiles": candidates,
        "provider_candidate_profiles": same_provider_candidates or [primary_id],
        "routed_profile_id": primary_id,
        "provider_family": provider_family,
        "model": primary_spec["model"],
        "family": primary_spec.get("family", primary_spec["model"]),
        "reasoning_effort": primary_spec["effort"],
        "swarm_profile": get_provider_swarm_profile(provider_family),
    }


def pack_conflict_colored_wave(
    ready_nodes: list[dict[str, Any]],
    catalog: Mapping[str, Any],
    *,
    active_locked_files: Mapping[str, str] | set[str] | None = None,
    task_id: str = "task428",
    plan_generation_sha256: str = "0" * 64,
    batch_seq_offset: int = 0,
) -> dict[str, Any]:
    """Pack dependency-ready microtasks into conflict-free provider slot batches (Case B vs. Case C).

    - Case B (Disjoint Files): Ready tasks with disjoint file footprints pack by provider family
      (`claude` up to 20, `codex` up to 20, `gemini`/Agy up to 64 per slot batch). Overflow tasks
      for a provider automatically open another slot batch.
    - Case C (Shared / Overlapping Files): At most 1 task from any overlapping file group is admitted
      into the wave and locks its file footprint in `locked_files`; any other ready task whose file
      footprint intersects `locked_files` is held in `WAITING_ON_FILE_LOCK` (`job_id=None`).
    """
    locked_by_file: dict[str, str] = {}
    if isinstance(active_locked_files, Mapping):
        for fpath, owner in active_locked_files.items():
            locked_by_file[normalize_file_target(str(fpath))] = str(owner)
    elif isinstance(active_locked_files, (set, list, tuple)):
        for fpath in active_locked_files:
            locked_by_file[normalize_file_target(str(fpath))] = "__active_lock__"

    admitted_nodes: list[dict[str, Any]] = []
    waiting_on_lock_nodes: list[dict[str, Any]] = []
    batches_by_provider: dict[str, list[dict[str, Any]]] = {
        "claude": [],
        "codex": [],
        "gemini": [],
    }
    all_batches: list[dict[str, Any]] = []

    for raw_node in ready_nodes:
        node = deepcopy(raw_node)
        mt_id = str(node.get("microtask_id") or node.get("id"))
        node["microtask_id"] = mt_id
        files = extract_microtask_files(node)
        route_info = resolve_microtask_route_tier(node, catalog)
        provider_family = route_info["provider_family"]
        swarm_prof = route_info["swarm_profile"]

        conflicting_files = sorted(
            f for f in files if f in locked_by_file and locked_by_file[f] != mt_id
        )
        if conflicting_files:
            blocking_holders = sorted({locked_by_file[f] for f in conflicting_files})
            held_node = {
                **node,
                "status": "WAITING_ON_FILE_LOCK",
                "job_id": None,
                "batch_id": None,
                "provider_family": provider_family,
                "subagent_index": None,
                "routed_profile_id": route_info["routed_profile_id"],
                "routed_model": route_info["model"],
                "routed_effort": route_info["reasoning_effort"],
                "candidate_profiles": route_info["candidate_profiles"],
                "swarm_profile": swarm_prof,
                "file_footprint": files,
                "locked_files": [],
                "blocking_files": conflicting_files,
                "blocking_microtask_ids": blocking_holders,
            }
            waiting_on_lock_nodes.append(held_node)
            continue

        # Admit into wave and lock all files in this microtask's footprint globally
        for f in files:
            locked_by_file[f] = mt_id

        cap = int(swarm_prof["max_agents_per_slot"])
        target_batch: dict[str, Any] | None = None
        for candidate_batch in batches_by_provider[provider_family]:
            if len(candidate_batch["microtask_ids"]) < cap:
                target_batch = candidate_batch
                break

        if target_batch is None:
            batch_seq = int(batch_seq_offset) + len(all_batches) + 1
            slot_index = ((batch_seq - 1) % MAX_OS_SLOTS) + 1
            slot_id = f"slot{slot_index}"
            batch_identity = digest(
                {
                    "task_id": task_id,
                    "plan_generation_sha256": plan_generation_sha256,
                    "provider_family": provider_family,
                    "batch_seq": batch_seq,
                    "first_microtask_id": mt_id,
                }
            )
            batch_id = f"swbatch428-{provider_family}-s{slot_index}-{batch_identity[:20]}"
            target_batch = {
                "batch_id": batch_id,
                "task_id": task_id,
                "plan_generation_sha256": plan_generation_sha256,
                "provider_family": provider_family,
                "slot_index": slot_index,
                "slot_id": slot_id,
                "max_agents_per_slot": cap,
                "max_nesting_depth": int(swarm_prof["max_nesting_depth"]),
                "microtask_ids": [],
                "subagents": [],
                "locked_files": [],
                "candidate_profiles": list(route_info["provider_candidate_profiles"]),
                "complexity": int(node["complexity"]),
                "task_types": list(node["task_types"]),
            }
            batches_by_provider[provider_family].append(target_batch)
            all_batches.append(target_batch)

        subagent_index = len(target_batch["microtask_ids"]) + 1
        subagent_entry = {
            "subagent_index": subagent_index,
            "microtask_id": mt_id,
            "attempt_lineage_id": node.get("attempt_lineage_id", f"{task_id}.mt.{mt_id}"),
            "role": node["role"],
            "complexity": int(node["complexity"]),
            "task_types": list(node["task_types"]),
            "routed_profile_id": route_info["routed_profile_id"],
            "candidate_profiles": list(route_info["candidate_profiles"]),
            "provider_family": provider_family,
            "model": route_info["model"],
            "family": route_info["family"],
            "pivot_model": node.get("pivot_model"),
            "reasoning_effort": route_info["reasoning_effort"],
            "max_nesting_depth": int(swarm_prof["max_nesting_depth"]),
            "deliverables": list(node["deliverables"]),
            "requirement_ids": list(node.get("requirement_ids") or []),
            "release_criteria": list(node.get("release_criteria") or []),
            "locked_files": files,
        }
        target_batch["microtask_ids"].append(mt_id)
        target_batch["subagents"].append(subagent_entry)
        target_batch["locked_files"] = sorted(set(target_batch["locked_files"]) | set(files))
        if int(node["complexity"]) > target_batch["complexity"]:
            target_batch["complexity"] = int(node["complexity"])
            target_batch["candidate_profiles"] = list(route_info["provider_candidate_profiles"])
        for t_tag in node["task_types"]:
            if t_tag not in target_batch["task_types"]:
                target_batch["task_types"].append(t_tag)

        admitted_node = {
            **node,
            "status": "DISPATCHED",
            "batch_id": target_batch["batch_id"],
            "slot_id": target_batch["slot_id"],
            "provider_family": provider_family,
            "subagent_index": subagent_index,
            "routed_profile_id": route_info["routed_profile_id"],
            "routed_model": route_info["model"],
            "routed_effort": route_info["reasoning_effort"],
            "candidate_profiles": route_info["candidate_profiles"],
            "swarm_profile": swarm_prof,
            "file_footprint": files,
            "locked_files": files,
            "blocking_files": [],
            "blocking_microtask_ids": [],
        }
        admitted_nodes.append(admitted_node)

    return {
        "admitted_nodes": admitted_nodes,
        "waiting_on_lock_nodes": waiting_on_lock_nodes,
        "batches": all_batches,
        "locked_files": dict(sorted(locked_by_file.items())),
    }


def normalize_swarm_batch_outputs(output: Mapping[str, Any] | list[Any]) -> dict[str, Any]:
    """Normalize a mapping or list of per-microtask subagent outputs into `{microtask_id: output}`."""
    if isinstance(output, Mapping):
        raw = output.get("subagent_outputs") if "subagent_outputs" in output else output
    elif isinstance(output, list):
        raw = output
    else:
        raise ValueError("Swarm batch output must be a JSON object or list of subagent outputs")

    if isinstance(raw, Mapping):
        if not raw:
            raise ValueError("Swarm batch output requires a non-empty subagent_outputs mapping")
        return dict(raw)

    if isinstance(raw, list):
        if not raw:
            raise ValueError("Swarm batch output requires a non-empty subagent_outputs list")
        normalized: dict[str, Any] = {}
        for item in raw:
            if not isinstance(item, Mapping):
                raise ValueError("Each subagent output list entry must be a mapping")
            mt_id = item.get("microtask_id") or item.get("id")
            if not isinstance(mt_id, str) or not mt_id.strip():
                raise ValueError("Each subagent output list entry requires microtask_id")
            if mt_id in normalized:
                raise ValueError(f"Duplicate microtask_id in swarm batch output list: {mt_id}")
            if "output" in item:
                normalized[mt_id] = item["output"]
            else:
                normalized[mt_id] = {k: v for k, v in item.items() if k not in ("microtask_id", "id")}
        return normalized

    raise ValueError("Swarm batch output requires a non-empty subagent_outputs mapping or list")


def validate_swarm_batch_stage_output(
    batch_descriptor: Mapping[str, Any],
    output: Mapping[str, Any] | list[Any],
    *,
    allow_partial_failures: bool = False,
) -> dict[str, Any]:
    """Validate the outer `MICROTASK_SWARM_BATCH` stage envelope before per-microtask commit."""
    if not isinstance(batch_descriptor, Mapping):
        raise ValueError("Swarm batch descriptor is required")
    expected_ids = set(batch_descriptor.get("microtask_ids") or [])
    if not expected_ids:
        raise ValueError("Swarm batch descriptor has no microtask_ids")

    raw_map = normalize_swarm_batch_outputs(output)
    unknown = set(raw_map.keys()) - expected_ids
    if unknown:
        raise ValueError(f"Swarm batch output contains unknown microtask IDs: {sorted(unknown)}")
    if not allow_partial_failures:
        for mt_id, mt_out in raw_map.items():
            if not isinstance(mt_out, Mapping):
                raise ValueError(f"Subagent output for {mt_id} must be a mapping")
    return {
        "batch_id": batch_descriptor.get("batch_id"),
        "provider_family": batch_descriptor.get("provider_family"),
        "subagent_outputs": dict(raw_map),
    }


class SwarmBatchRuntime:
    """High-level coordinator for Two-Staged Concurrency + Provider Batching + Intra-Slot Agent Swarms."""

    def __init__(
        self,
        journal,
        store,
        *,
        owner_broker=None,
        attempt_ledger=None,
        clock=None,
    ):
        from .microtask_board_428 import MicrotaskBoardRuntime
        import time

        self.board = MicrotaskBoardRuntime(
            journal,
            store,
            owner_broker=owner_broker,
            attempt_ledger=attempt_ledger,
            clock=clock or time.time,
            swarm_batch_mode=True,
        )

    @property
    def journal(self):
        return self.board.journal

    @property
    def store(self):
        return self.board.store

    @property
    def attempt_ledger(self):
        return self.board.attempt_ledger

    def materialize(self, task_id: str) -> dict[str, Any]:
        return self.board.dispatch_swarm_batches(task_id)

    def dispatch_batches(self, task_id: str) -> dict[str, Any]:
        return self.board.dispatch_swarm_batches(task_id)

    def complete_batch(
        self,
        task_id: str,
        batch_id: str,
        subagent_outputs: Mapping[str, Any] | list[Any],
    ) -> dict[str, Any]:
        return self.board.complete_swarm_batch(task_id, batch_id, subagent_outputs)

    def board_status(self, task_id: str) -> dict[str, Any]:
        return self.board.board_status(task_id)

    def active_file_locks(self, task_id: str | None = None) -> list[dict[str, Any]]:
        return self.board.active_file_locks(task_id)
