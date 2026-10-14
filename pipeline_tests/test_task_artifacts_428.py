"""Tests for `P428-13`: Stage code and non-code fragment artifacts safely (`task_artifacts_428.py`)."""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest

from cochem_pipeline.coding import CodingProject, validate_production_coding_project
from cochem_pipeline.task_artifacts_428 import (
    cleanup_fragment_workspace,
    collect_assigned_dependencies,
    compile_downstream_inputs,
    stage_fragment_workspace,
    validate_fragment_deliverables,
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_project(tmp_path: Path, project_id: str = "quantum-solver-prod") -> CodingProject:
    return CodingProject.from_dict(
        project_id,
        {
            "repository": str(tmp_path / "repo"),
            "branch": "main",
            "allowed_paths": ["src/solver", "docs"],
            "test_paths": ["tests"],
        },
    )


def _deliv(name: str, content: str) -> dict[str, str]:
    return {"name": name, "content": content, "sha256": _sha256_text(content)}


def _completed_node(
    microtask_id: str,
    role: str,
    deliverables: list[dict[str, str]],
    *,
    depends_on: list[str] | None = None,
    gen_sha: str = "a" * 64,
) -> dict:
    art_text = f"Artifact for {microtask_id}"
    art_sha = _sha256_text(art_text)
    return {
        "microtask_id": microtask_id,
        "role": role,
        "plan_generation_sha256": gen_sha,
        "deliverables": [d["name"] for d in deliverables],
        "depends_on": list(depends_on or []),
        "status": "COMPLETED",
        "artifact_sha256": art_sha,
        "output": {
            "artifact_text": art_text,
            "artifact_sha256": art_sha,
            "deliverables": deliverables,
        },
    }


def test_windows_acceptance_rejected_as_production_project(tmp_path: Path) -> None:
    acc_proj = _make_project(tmp_path, project_id="windows-acceptance")
    with pytest.raises(ValueError, match="windows-acceptance is an acceptance fixture"):
        validate_production_coding_project(acc_proj)

    node = {"microtask_id": "mt-1", "role": "implementation", "deliverables": ["src/solver/core.py"]}
    with pytest.raises(ValueError, match="windows-acceptance"):
        validate_fragment_deliverables(
            node,
            [_deliv("src/solver/core.py", "x = 1\n")],
            project=acc_proj,
        )


def test_only_assigned_dependencies_and_baseline_enter_workspace(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    gen_sha = "1" * 64
    mt1 = _completed_node("mt-1", "implementation", [_deliv("src/solver/hamiltonian.py", "def h(): return 1\n")], gen_sha=gen_sha)
    mt2 = _completed_node("mt-2", "implementation", [_deliv("docs/design.md", "# Design\n")], gen_sha=gen_sha)
    mt_unassigned = _completed_node("mt-unassigned", "implementation", [_deliv("src/solver/secret_extra.py", "extra = 2\n")], gen_sha=gen_sha)

    # Assembly node depends ONLY on mt-1 and mt-2, NOT mt-unassigned
    mt_asm = {
        "microtask_id": "mt-asm",
        "role": "assembly",
        "plan_generation_sha256": gen_sha,
        "depends_on": ["mt-2", "mt-1"],
        "deliverables": ["src/solver/ pipeline.py"],
    }
    board_snapshot = {
        "schema": "cochem-microtask-board/4.2.8",
        "task_id": "task428-art-1",
        "plan_generation_sha256": gen_sha,
        "nodes": [mt1, mt2, mt_unassigned],
    }
    baseline = {"src/solver/__init__.py": b"# baseline init\n"}

    packet1 = compile_downstream_inputs(
        mt_asm,
        board_snapshot,
        project=project,
        baseline_files=baseline,
        expected_generation_sha256=gen_sha,
    )
    packet2 = compile_downstream_inputs(
        mt_asm,
        board_snapshot,
        project=project,
        baseline_files=baseline,
        expected_generation_sha256=gen_sha,
    )
    # Deterministic assembly_input_sha256 and exact assigned dependencies
    assert packet1["assembly_input_sha256"] == packet2["assembly_input_sha256"]
    assert packet1["assigned_dependencies"] == ["mt-1", "mt-2"]
    assert set(packet1["workspace_files"]) == {
        "src/solver/__init__.py",
        "src/solver/hamiltonian.py",
        "docs/design.md",
    }
    assert "src/solver/secret_extra.py" not in packet1["workspace_files"]
    assert packet1["requires_conflict_integration"] is False

    # Stage into physical workspace and verify cleanup
    ws_root = tmp_path / "workspace"
    staged = stage_fragment_workspace(ws_root, packet1)
    assert staged["verified"] is True
    assert staged["staged_file_count"] == 3
    assert (ws_root / "src/solver/hamiltonian.py").read_text(encoding="utf-8") == "def h(): return 1\n"

    cleaned = cleanup_fragment_workspace(ws_root)
    assert cleaned["verified_empty"] is True
    assert cleaned["cleaned_files"] == 3
    assert list(ws_root.iterdir()) == []


def test_traversal_secrets_protected_configs_and_reparse_points_rejected(tmp_path: Path) -> None:
    project = _make_project(tmp_path)

    # Path traversal rejected
    for bad_path in ("../outside.py", "src/solver/../../etc/passwd", "/abs/path.py", "C:/win.py", ".git/config"):
        with pytest.raises(ValueError):
            validate_fragment_deliverables(
                {"microtask_id": "mt-bad", "role": "implementation", "deliverables": [bad_path]},
                [_deliv(bad_path, "bad\n")],
                project=project,
            )

    # Secret / key file rejected
    with pytest.raises(ValueError, match="Credential, VCS, and cache material is forbidden"):
        validate_fragment_deliverables(
            {"microtask_id": "mt-sec", "role": "implementation", "deliverables": ["src/solver/private.pem"]},
            [_deliv("src/solver/private.pem", "secret\n")],
            project=project,
        )

    # Protected test config rejected
    with pytest.raises(ValueError, match="protected test configuration"):
        validate_fragment_deliverables(
            {"microtask_id": "mt-cfg", "role": "final_test", "deliverables": ["tests/conftest.py"]},
            [_deliv("tests/conftest.py", "import pytest\n")],
            project=project,
        )

    # Role path ownership: implementation cannot write to test_paths; final_test cannot write to allowed_paths
    with pytest.raises(ValueError, match="outside project allowed_paths"):
        validate_fragment_deliverables(
            {"microtask_id": "mt-impl", "role": "implementation", "deliverables": ["tests/test_unit.py"]},
            [_deliv("tests/test_unit.py", "def test_x(): pass\n")],
            project=project,
        )
    with pytest.raises(ValueError, match="must reside within project test_paths"):
        validate_fragment_deliverables(
            {"microtask_id": "mt-test", "role": "final_test", "deliverables": ["src/solver/core.py"]},
            [_deliv("src/solver/core.py", "x = 1\n")],
            project=project,
        )

    # NTFS junction / reparse point inside staged workspace is rejected by read_workspace
    ws_reparse = tmp_path / "ws_reparse"
    ws_reparse.mkdir(parents=True, exist_ok=True)
    outside_target = tmp_path / "outside_dir"
    outside_target.mkdir(parents=True, exist_ok=True)
    junction_path = ws_reparse / "junction_link"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction_path), str(outside_target)],
        check=True,
        capture_output=True,
    )
    from cochem_pipeline.coding import read_workspace

    with pytest.raises(ValueError, match="symbolic link or reparse point"):
        read_workspace(ws_reparse)

    # Cleanup safely removes the junction without deleting outside_target contents
    (outside_target / "keep.txt").write_text("safe", encoding="utf-8")
    cleaned = cleanup_fragment_workspace(ws_reparse)
    assert cleaned["verified_empty"] is True
    assert (outside_target / "keep.txt").read_text(encoding="utf-8") == "safe"


def test_stale_parent_artifact_and_tampered_hashes_rejected(tmp_path: Path) -> None:
    gen_current = "2" * 64
    gen_stale = "1" * 64
    mt1 = _completed_node("mt-1", "implementation", [_deliv("src/solver/a.py", "a = 1\n")], gen_sha=gen_current)
    board_snapshot = {
        "schema": "cochem-microtask-board/4.2.8",
        "task_id": "task428-stale",
        "plan_generation_sha256": gen_current,
        "nodes": [mt1],
    }
    asm_stale = {
        "microtask_id": "mt-asm",
        "role": "assembly",
        "plan_generation_sha256": gen_stale,
        "depends_on": ["mt-1"],
    }
    with pytest.raises(ValueError, match="stale"):
        collect_assigned_dependencies(asm_stale, board_snapshot)

    # Tampered artifact_sha256 on predecessor is rejected
    mt1_tampered = dict(mt1, artifact_sha256="f" * 64)
    board_tampered = dict(board_snapshot, nodes=[mt1_tampered])
    asm_current = dict(asm_stale, plan_generation_sha256=gen_current)
    with pytest.raises(ValueError, match="stale or tampered artifact_sha256"):
        collect_assigned_dependencies(asm_current, board_tampered)


def test_concurrent_conflicting_fragments_and_owner_edit_protection(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    gen_sha = "3" * 64
    baseline = {"src/solver/shared.py": b" VERSION = 0\n"}

    # Two concurrent implementation fragments edit the same file differently
    mt_a = _completed_node(
        "mt-a",
        "implementation",
        [_deliv("src/solver/shared.py", "VERSION = 1\nFEATURE_A = True\n")],
        gen_sha=gen_sha,
    )
    mt_b = _completed_node(
        "mt-b",
        "implementation",
        [_deliv("src/solver/shared.py", "VERSION = 2\nFEATURE_B = True\n")],
        gen_sha=gen_sha,
    )
    board_snapshot = {
        "schema": "cochem-microtask-board/4.2.8",
        "task_id": "task428-conflict",
        "plan_generation_sha256": gen_sha,
        "nodes": [mt_a, mt_b],
    }

    # A non-assembly node is forbidden from consuming unresolved sibling conflicts
    mt_test = {
        "microtask_id": "mt-test",
        "role": "final_test",
        "plan_generation_sha256": gen_sha,
        "depends_on": ["mt-a", "mt-b"],
    }
    with pytest.raises(ValueError, match="Conflicting sibling edits"):
        compile_downstream_inputs(mt_test, board_snapshot, project=project, baseline_files=baseline)

    # An assembly node receives explicit conflict descriptors and both sibling files without overwriting!
    mt_asm = {
        "microtask_id": "mt-asm",
        "role": "assembly",
        "plan_generation_sha256": gen_sha,
        "depends_on": ["mt-a", "mt-b"],
    }
    packet = compile_downstream_inputs(mt_asm, board_snapshot, project=project, baseline_files=baseline)
    assert packet["requires_conflict_integration"] is True
    assert len(packet["conflicts"]) == 1
    conflict = packet["conflicts"][0]
    assert conflict["path"] == "src/solver/shared.py"
    assert [s["microtask_id"] for s in conflict["siblings"]] == ["mt-a", "mt-b"]
    # Baseline remains at src/solver/shared.py while both sibling versions are staged under conflicts_428/
    assert packet["workspace_files"]["src/solver/shared.py"] == b" VERSION = 0\n"
    assert packet["workspace_files"]["conflicts_428/mt-a/src/solver/shared.py"] == b"VERSION = 1\nFEATURE_A = True\n"
    assert packet["workspace_files"]["conflicts_428/mt-b/src/solver/shared.py"] == b"VERSION = 2\nFEATURE_B = True\n"

    # Concurrent owner modification to src/solver/shared.py is refused so fragments never overwrite owner edits
    owner_modified = {"src/solver/shared.py": b"# Owner hotfix\nVERSION = 99\n"}
    with pytest.raises(ValueError, match="conflicts with an unintegrated owner change"):
        compile_downstream_inputs(
            mt_asm,
            board_snapshot,
            project=project,
            baseline_files=baseline,
            current_owner_files=owner_modified,
        )
