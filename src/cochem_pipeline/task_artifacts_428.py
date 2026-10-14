"""Stage code and non-code fragment artifacts safely (`P428-13`).

Guarantees:
- Only assigned dependency outputs (`node['depends_on']`) and registered project
  baselines enter a downstream workspace; unrelated sibling artifacts are excluded.
- All deliverable paths are validated against path traversal, secret/VCS/cache
  names, protected test configuration files, and NTFS symlinks/reparse points.
- Registered coding projects enforce disjoint `allowed_paths` vs `test_paths`
  ownership by role (`implementation`/`assembly` vs `final_test`) and reject
  `windows-acceptance` as a production project.
- Stale parent/predecessor artifacts (mismatched `plan_generation_sha256` or
  tampered deliverable `sha256`) are rejected.
- Concurrent fragment edits to the same path are never silently overwritten:
  divergent sibling edits are surfaced as explicit conflict descriptors for
  `assembly` integration, and concurrent owner edits on the baseline are refused.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import stat
import time
from typing import Any

from .coding import (
    CodingProject,
    digest,
    manifest,
    materialize,
    read_workspace,
    safe_path,
    validate_production_coding_project,
    validate_project_files,
    within,
)
from .workflow_428 import _id, _sha, _text


PROTECTED_TEST_CONFIG_NAMES = frozenset(
    {
        "conftest.py",
        "pytest.ini",
        "tox.ini",
        "setup.cfg",
        "pyproject.toml",
        "setup.py",
    }
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_fragment_deliverables(
    node: dict[str, Any],
    deliverables: list[dict[str, Any]],
    *,
    project: CodingProject | None = None,
    baseline_files: dict[str, bytes] | None = None,
    current_owner_files: dict[str, bytes] | None = None,
) -> dict[str, bytes]:
    """Validate fragment deliverables for path safety, hashes, project ownership, and owner changes."""
    if not isinstance(node, dict):
        raise ValueError("Fragment node descriptor must be a dict")
    role = node.get("role")
    if role not in ("implementation", "assembly", "final_test", "orchestration"):
        raise ValueError(f"Unsupported microtask role for artifact staging: {role}")

    if project is not None:
        validate_production_coding_project(project)

    if not isinstance(deliverables, list) or not 1 <= len(deliverables) <= 50:
        raise ValueError("Fragment staging requires 1..50 deliverables")

    declared = {safe_path(p) for p in (node.get("deliverables") or [])}
    files_by_path: dict[str, bytes] = {}

    for item in deliverables:
        if not isinstance(item, dict) or not {"name", "content", "sha256"} <= set(item):
            raise ValueError("Deliverable entry requires name, content, and sha256")
        rel_path = safe_path(item["name"])
        if rel_path in files_by_path:
            raise ValueError(f"Duplicate deliverable path in fragment output: {rel_path}")
        if declared and rel_path not in declared:
            raise ValueError(f"Fragment emitted undeclared deliverable path: {rel_path}")

        content_str = _text(item["content"], "Deliverable content", 200000)
        content_bytes = content_str.encode("utf-8")
        expected_sha = _sha(item["sha256"])
        if _sha256_bytes(content_bytes) != expected_sha:
            raise ValueError(f"Deliverable {rel_path} sha256 mismatch")

        if project is not None:
            if Path(rel_path).name in PROTECTED_TEST_CONFIG_NAMES:
                raise ValueError(f"Fragment deliverable may not modify protected test configuration: {rel_path}")
            if role in ("implementation", "assembly"):
                if not within(rel_path, project.allowed_paths) or within(rel_path, project.test_paths):
                    raise ValueError(
                        f"Role '{role}' deliverable '{rel_path}' is outside project allowed_paths"
                    )
            elif role == "final_test":
                if not within(rel_path, project.test_paths) or within(rel_path, project.allowed_paths):
                    raise ValueError(
                        f"Role 'final_test' deliverable '{rel_path}' must reside within project test_paths"
                    )

        if baseline_files is not None and current_owner_files is not None:
            base_val = baseline_files.get(rel_path)
            owner_val = current_owner_files.get(rel_path)
            if base_val != owner_val:
                raise ValueError(
                    f"Deliverable '{rel_path}' conflicts with an unintegrated owner change since baseline capture"
                )

        files_by_path[rel_path] = content_bytes

    validate_project_files(files_by_path)
    if declared and (declared - files_by_path.keys()):
        raise ValueError("Fragment output is missing declared deliverables")
    return files_by_path


def collect_assigned_dependencies(
    node: dict[str, Any],
    board_snapshot: dict[str, Any],
    *,
    expected_generation_sha256: str | None = None,
) -> list[dict[str, Any]]:
    """Return only the completed, generation-matched dependency records listed in `node['depends_on']`."""
    if not isinstance(board_snapshot, dict) or board_snapshot.get("schema") != "cochem-microtask-board/4.2.8":
        raise ValueError("Expected a valid 4.2.8 microtask board snapshot")
    gen_sha = _sha(board_snapshot.get("plan_generation_sha256"))
    if expected_generation_sha256 is not None and _sha(expected_generation_sha256) != gen_sha:
        raise ValueError("Stale parent/board generation does not match expected plan_generation_sha256")
    if node.get("plan_generation_sha256") and _sha(node["plan_generation_sha256"]) != gen_sha:
        raise ValueError("Node plan_generation_sha256 is stale relative to the board snapshot")

    nodes_by_id = {n["microtask_id"]: n for n in (board_snapshot.get("nodes") or [])}
    assigned_ids = list(node.get("depends_on") or [])
    assigned_records: list[dict[str, Any]] = []

    for dep_id in sorted(assigned_ids):
        _id(dep_id)
        if dep_id not in nodes_by_id:
            raise ValueError(f"Assigned dependency '{dep_id}' is missing from the current plan generation")
        dep_node = nodes_by_id[dep_id]
        if dep_node.get("status") != "COMPLETED" or not isinstance(dep_node.get("output"), dict):
            raise ValueError(f"Assigned dependency '{dep_id}' is not COMPLETED with verified output")
        output = dep_node["output"]
        art_text = output.get("artifact_text", "")
        art_sha = hashlib.sha256(art_text.encode("utf-8")).hexdigest()
        if dep_node.get("artifact_sha256") != art_sha or output.get("artifact_sha256") != art_sha:
            raise ValueError(f"Assigned dependency '{dep_id}' has a stale or tampered artifact_sha256")
        assigned_records.append(dep_node)

    return assigned_records


def compile_downstream_inputs(
    node: dict[str, Any],
    board_snapshot: dict[str, Any],
    *,
    project: CodingProject | None = None,
    baseline_files: dict[str, bytes] | None = None,
    current_owner_files: dict[str, bytes] | None = None,
    expected_generation_sha256: str | None = None,
) -> dict[str, Any]:
    """Compile a deterministic, conflict-aware input workspace packet for `node`."""
    if project is not None:
        validate_production_coding_project(project)

    clean_baseline: dict[str, bytes] = {}
    if baseline_files is not None:
        for k, v in baseline_files.items():
            if not isinstance(v, (bytes, bytearray)):
                raise ValueError(f"Baseline file '{k}' must be bytes")
            clean_baseline[safe_path(k)] = bytes(v)
        validate_project_files(clean_baseline)

    clean_owner: dict[str, bytes] | None = None
    if current_owner_files is not None:
        clean_owner = {safe_path(k): bytes(v) for k, v in current_owner_files.items()}

    assigned_deps = collect_assigned_dependencies(
        node,
        board_snapshot,
        expected_generation_sha256=expected_generation_sha256,
    )

    per_dep_files: dict[str, dict[str, bytes]] = {}
    writers_by_path: dict[str, list[tuple[str, bytes, str]]] = {}

    for dep in assigned_deps:
        dep_id = dep["microtask_id"]
        delivs = dep["output"]["deliverables"]
        validated_files = validate_fragment_deliverables(
            dep,
            delivs,
            project=project,
            baseline_files=clean_baseline if baseline_files is not None else None,
            current_owner_files=clean_owner,
        )
        per_dep_files[dep_id] = validated_files
        for path, data in sorted(validated_files.items()):
            # Record every predecessor that produced or modified `path`
            if clean_baseline.get(path) != data or path not in clean_baseline:
                writers_by_path.setdefault(path, []).append((dep_id, data, _sha256_bytes(data)))

    workspace_files: dict[str, bytes] = dict(clean_baseline)
    conflicts: list[dict[str, Any]] = []

    for path in sorted(writers_by_path):
        entries = writers_by_path[path]
        distinct_shas = {sha for _, _, sha in entries}
        if len(distinct_shas) == 1:
            # Either a single writer or identical convergent content
            workspace_files[path] = entries[-1][1]
        else:
            # Conflicting sibling edits: never overwrite one sibling with another!
            if node.get("role") != "assembly":
                raise ValueError(
                    f"Conflicting sibling edits on '{path}' cannot enter role '{node.get('role')}' "
                    "without prior assembly resolution"
                )
            sibling_records = []
            for dep_id, data, sha in entries:
                conflict_stage_path = safe_path(f"conflicts_428/{dep_id}/{path}")
                workspace_files[conflict_stage_path] = data
                sibling_records.append(
                    {
                        "microtask_id": dep_id,
                        "sha256": sha,
                        "staged_conflict_path": conflict_stage_path,
                    }
                )
            base_bytes = clean_baseline.get(path)
            conflicts.append(
                {
                    "path": path,
                    "baseline_sha256": _sha256_bytes(base_bytes) if base_bytes is not None else None,
                    "siblings": sibling_records,
                }
            )

    validate_project_files(workspace_files)
    ws_manifest = manifest(workspace_files)
    dep_summary = [
        {
            "microtask_id": d["microtask_id"],
            "artifact_sha256": d["artifact_sha256"],
            "deliverable_hashes": {
                p: _sha256_bytes(b) for p, b in sorted(per_dep_files[d["microtask_id"]].items())
            },
        }
        for d in assigned_deps
    ]
    baseline_sha = digest(manifest(clean_baseline))
    assembly_input_sha256 = digest(
        {
            "task_id": board_snapshot["task_id"],
            "microtask_id": node["microtask_id"],
            "plan_generation_sha256": board_snapshot["plan_generation_sha256"],
            "baseline_snapshot_sha256": baseline_sha,
            "dependencies": dep_summary,
            "workspace_manifest": ws_manifest,
            "conflicts": conflicts,
        }
    )

    return {
        "schema": "cochem-task-artifact-staging/4.2.8",
        "task_id": board_snapshot["task_id"],
        "microtask_id": node["microtask_id"],
        "role": node["role"],
        "plan_generation_sha256": board_snapshot["plan_generation_sha256"],
        "baseline_snapshot_sha256": baseline_sha,
        "assigned_dependencies": [d["microtask_id"] for d in assigned_deps],
        "dependency_Provenance": dep_summary,
        "workspace_files": workspace_files,
        "workspace_manifest": ws_manifest,
        "conflicts": conflicts,
        "requires_conflict_integration": bool(conflicts),
        "assembly_input_sha256": assembly_input_sha256,
    }


def stage_fragment_workspace(workspace_root: Path, packet: dict[str, Any]) -> dict[str, Any]:
    """Materialize a validated downstream packet into `workspace_root` and verify physical files."""
    if not isinstance(packet, dict) or packet.get("schema") != "cochem-task-artifact-staging/4.2.8":
        raise ValueError("Expected a valid 4.2.8 artifact staging packet")
    workspace_root = Path(workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)
    materialize(workspace_root, packet["workspace_files"])
    observed = read_workspace(workspace_root)
    observed_manifest = manifest(observed)
    if observed_manifest != packet["workspace_manifest"]:
        raise ValueError("Materialized workspace manifest does not match expected staging packet")
    return {
        "workspace_root": str(workspace_root),
        "workspace_manifest": observed_manifest,
        "assembly_input_sha256": packet["assembly_input_sha256"],
        "staged_file_count": len(observed_manifest),
        "verified": True,
    }


def cleanup_fragment_workspace(workspace_root: Path, *, clock=time.time) -> dict[str, Any]:
    """Safely remove staged workspace contents without following symlinks/reparse points and verify emptiness."""
    workspace_root = Path(workspace_root)
    cleaned_files = 0
    if workspace_root.exists():
        meta = os.lstat(workspace_root)
        if stat.S_ISLNK(meta.st_mode) or getattr(meta, "st_file_attributes", 0) & 0x400:
            raise ValueError("Refusing to clean a workspace root that is a symlink or reparse point")
        for child in list(workspace_root.iterdir()):
            cmeta = os.lstat(child)
            if stat.S_ISLNK(cmeta.st_mode) or getattr(cmeta, "st_file_attributes", 0) & 0x400:
                os.unlink(child)
                cleaned_files += 1
            elif stat.S_ISDIR(cmeta.st_mode):
                for root_dir, dirs, files in os.walk(child, topdown=False, followlinks=False):
                    for fname in files:
                        fpath = Path(root_dir) / fname
                        fmeta = os.lstat(fpath)
                        if stat.S_ISLNK(fmeta.st_mode) or getattr(fmeta, "st_file_attributes", 0) & 0x400:
                            os.unlink(fpath)
                        else:
                            fpath.unlink()
                        cleaned_files += 1
                    for dname in dirs:
                        dpath = Path(root_dir) / dname
                        dmeta = os.lstat(dpath)
                        if stat.S_ISLNK(dmeta.st_mode) or getattr(dmeta, "st_file_attributes", 0) & 0x400:
                            os.rmdir(dpath)
                        else:
                            dpath.rmdir()
                child.rmdir()
            else:
                child.unlink()
                cleaned_files += 1

        if any(workspace_root.iterdir()):
            raise ValueError("Workspace cleanup failed: residual entries remain")

    return {
        "workspace_root": str(workspace_root),
        "cleaned_files": cleaned_files,
        "verified_empty": True,
        "cleaned_at": float(clock()),
    }
