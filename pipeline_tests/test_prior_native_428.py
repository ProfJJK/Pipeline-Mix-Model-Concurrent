"""Tests for R5/R6 source repair inventory and hash-bound Fable failure replay (`P428-05`)."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.verify_prior_native_428 import (
    AGENT_HOLD_REL,
    AUTH_HOLD_ROOT_NAME,
    COMPLETED_TARGETS,
    DEFAULT_PRIOR_NATIVE_BINDINGS,
    KNOWLEDGE_HOLD_ROOT_NAME,
    NATIVE_HOLD_ROOT_NAME,
    PriorNativeReplayError,
    R4_V11_ROOT_NAME,
    inventory_r5_r6_source_repairs,
    replay_saved_fable_failure,
    sanitize_replay_error,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_replay_fixture(
    tmp_path: Path,
    *,
    result_text: str = "API Error: Request failed with status code 429",
    is_error: bool = True,
) -> tuple[Path, dict[Path, bytes], dict[str, object]]:
    root = tmp_path / "CoChem"
    native_root = root / NATIVE_HOLD_ROOT_NAME
    files: dict[Path, bytes] = {}
    bindings: dict[str, object] = {}

    def put_json(rel_path: Path, payload: dict) -> str:
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        files[rel_path] = raw
        return _sha256(raw)

    bindings["auth_sha256"] = put_json(
        root / AUTH_HOLD_ROOT_NAME / "result.json",
        {"phase": "auth", "status": "PHASE_COMPLETED", "result": {"status": "ALL_SESSIONS_VERIFIED"}},
    )
    bindings["knowledge_sha256"] = put_json(
        root / KNOWLEDGE_HOLD_ROOT_NAME / "result.json",
        {
            "phase": "knowledge",
            "status": "PHASE_COMPLETED",
            "result": {"status": "EXISTING_KNOWLEDGE_AUTHORITY_VERIFIED"},
        },
    )
    bindings["agent_sha256"] = put_json(
        root / AGENT_HOLD_REL,
        {"phase": "agent", "status": "PHASE_COMPLETED", "result": {"status": "SIX_WORKER_AGENT_CUSTODY_VERIFIED"}},
    )
    bindings["r4_v11_start_sha256"] = put_json(
        root / R4_V11_ROOT_NAME / "start-receipt.json",
        {"schema": "cochem-warden-start/3", "status": "WARDEN_R4_RESTARTED_HEALTH_VERIFIED"},
    )
    bindings["held_sha256"] = put_json(
        native_root / "held.json",
        {"phase": "native", "status": "HELD_PRESERVE_PARTIAL", "category": "code"},
    )
    bindings["native_held_sha256"] = put_json(
        native_root / "native" / "native-held.json",
        {"phase": "target-23", "completed": 23, "status": "HELD_PRESERVE_PARTIAL"},
    )

    completed_bindings = []
    for item in COMPLETED_TARGETS:
        phase = item["phase"]
        digest = put_json(
            native_root / "native" / f"{phase}-verified.json",
            {
                "phase": phase,
                "status": "NATIVE_SELECTOR_ACCEPTED",
                "provider": item["provider"],
                "model": item["model"],
                "effort": item["effort"],
                "worker": item["worker"],
            },
        )
        row = dict(item)
        row["sha256"] = digest
        completed_bindings.append(row)
    bindings["completed_targets"] = tuple(completed_bindings)

    attempt_id = "a" * 32
    bindings["reservation_sha256"] = put_json(
        native_root / "native" / "target-23-reservation.json",
        {
            "schema": "cochem-r6-disposable-native-reservation/1",
            "node": {
                "attempt_id": attempt_id,
                "worker_slot": "slot1",
                "route": {
                    "provider": "claude",
                    "model": "claude-fable-5-1",
                    "reasoning_effort": "high",
                },
            },
        },
    )

    stdout_raw = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": is_error,
            "result": result_text,
        }
    ).encode("utf-8")
    stderr_raw = b""
    stdout_sha = _sha256(stdout_raw)
    stderr_sha = _sha256(stderr_raw)

    attempt_dir = native_root / "native" / "attempts" / attempt_id
    files[attempt_dir / "stdout.log"] = stdout_raw
    files[attempt_dir / "stderr.log"] = stderr_raw

    bindings["stdout_sha256"] = stdout_sha
    bindings["stderr_sha256"] = stderr_sha
    bindings["stdout_bytes"] = len(stdout_raw)
    bindings["stderr_bytes"] = len(stderr_raw)
    bindings["failure_metadata_sha256"] = put_json(
        attempt_dir / "failure.json",
        {
            "schema": "cochem-native-failure-metadata/1",
            "category": "code",
            "stdout_sha256": stdout_sha,
            "stderr_sha256": stderr_sha,
            "stdout_bytes": len(stdout_raw),
            "stderr_bytes": len(stderr_raw),
            "exit_code": 1,
            "started_at": 100,
            "finished_at": 102,
        },
    )
    return root, files, bindings


def test_r5_r6_repair_inventory_matches_canonical_source_and_diagnostic_evidence():
    inventory = inventory_r5_r6_source_repairs()
    assert inventory["status"] == "ALL_R5_R6_REPAIRS_IN_CANONICAL_SOURCE"
    assert inventory["old_package_modified"] is False
    assert inventory["export_diagnostic_rerun_required"] is False
    assert inventory["repairs"]["claude_failed_result_http_status"]["quota_429_verified"] is True
    assert inventory["repairs"]["agy_tool_registry_scope"]["scope"] == "cli_builtin_runners"
    assert inventory["repairs"]["agy_agent_directory_custody"]["directory_desired_access"] == 0x20001
    assert inventory["repairs"]["codex_ram_cwd_selection"]["workspace_selection"] == "validated_process_cwd"

    diag_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "evidence"
        / "r6-native-hold-v3-diagnostic-20261013.json"
    )
    diag = json.loads(diag_path.read_text(encoding="utf-8-sig"))
    assert DEFAULT_PRIOR_NATIVE_BINDINGS["stdout_sha256"] == diag["stream_hashes"]["stdout"]
    assert DEFAULT_PRIOR_NATIVE_BINDINGS["stderr_sha256"] == diag["stream_hashes"]["stderr"]
    assert DEFAULT_PRIOR_NATIVE_BINDINGS["failure_metadata_sha256"] == diag["native_failure"]["sha256"]
    assert DEFAULT_PRIOR_NATIVE_BINDINGS["reservation_sha256"] == diag["target"]["reservation_sha256"]
    assert len(DEFAULT_PRIOR_NATIVE_BINDINGS["completed_targets"]) == 23
    for pinned, observed in zip(
        DEFAULT_PRIOR_NATIVE_BINDINGS["completed_targets"],
        diag["completed_targets"],
        strict=True,
    ):
        assert pinned["phase"] == observed["phase"]
        assert pinned["provider"] == observed["provider"]
        assert pinned["model"] == observed["model"]
        assert pinned["effort"] == observed["effort"]
        assert pinned["worker"] == observed["worker"]
        assert pinned["sha256"] == observed["sha256"]


def test_replay_saved_fable_failure_proves_quota_skip_and_preserves_23_targets(tmp_path):
    root, files, bindings = _build_replay_fixture(tmp_path)
    original_files = deepcopy(files)

    def reader(path: Path, expected_sha256: str, max_bytes: int) -> bytes:
        if path not in files:
            raise FileNotFoundError(str(path))
        return files[path]

    replay = replay_saved_fable_failure(root, reader=reader, expected_bindings=bindings)
    assert replay["status"] == "REPLAY_QUOTA_PROVED_AVAILABILITY_ONLY"
    assert replay["cutover_precheck_passed"] is True
    assert replay["target"]["model"] == "claude-fable-5-1"
    assert replay["target"]["effort"] == "high"
    assert replay["target"]["selector_accepted"] is False
    assert replay["target"]["target_status"] == "PROVIDER_TEMPORARILY_UNAVAILABLE"
    assert replay["target"]["category"] == "quota"
    assert replay["target"]["api_status"] == 429
    assert replay["preserved_completed_targets_count"] == 23
    assert replay["continue_independent_providers"] is True
    assert replay["old_package_modified"] is False
    assert replay["raw_provider_output_published"] is False
    assert replay["export_diagnostic_rerun_required"] is False
    assert files == original_files


def test_replay_unknown_text_holds_without_proving_quota_or_allowing_cutover(tmp_path):
    root, files, bindings = _build_replay_fixture(
        tmp_path,
        result_text="Unhandled internal runtime trace 429 without anchored prefix",
    )

    def reader(path: Path, expected_sha256: str, max_bytes: int) -> bytes:
        return files[path]

    replay = replay_saved_fable_failure(root, reader=reader, expected_bindings=bindings)
    assert replay["status"] == "REPLAY_HELD_UNPROVED"
    assert replay["cutover_precheck_passed"] is False
    assert replay["target"]["selector_accepted"] is False
    assert replay["target"]["category"] == "code"
    assert replay["continue_independent_providers"] is False
    assert "Unhandled internal runtime trace" not in json.dumps(replay)


def test_replay_rejects_wrong_hash_missing_file_and_permission_error_with_sanitized_projection(tmp_path):
    root, files, bindings = _build_replay_fixture(tmp_path)

    # 1. Wrong hash (using default production bindings against synthetic fixture bytes)
    def reader_ok(path: Path, expected_sha256: str, max_bytes: int) -> bytes:
        return files[path]

    with pytest.raises(PriorNativeReplayError) as exc_hash:
        replay_saved_fable_failure(root, reader=reader_ok)
    assert exc_hash.value.code == "PROTECTED_READ_HASH_MISMATCH"
    proj_hash = sanitize_replay_error(exc_hash.value)
    assert proj_hash["code"] == "PROTECTED_READ_HASH_MISMATCH"
    assert proj_hash["raw_error_published"] is False
    assert proj_hash["raw_provider_output_published"] is False

    # 2. Permission denied
    def reader_perm(path: Path, expected_sha256: str, max_bytes: int) -> bytes:
        raise PermissionError("Secret host path C:\\Program Files\\CoChem denied for user")

    with pytest.raises(PriorNativeReplayError) as exc_perm:
        replay_saved_fable_failure(root, reader=reader_perm, expected_bindings=bindings)
    assert exc_perm.value.code == "PROTECTED_READ_PERMISSION_DENIED"
    proj_perm = sanitize_replay_error(exc_perm.value)
    assert proj_perm["code"] == "PROTECTED_READ_PERMISSION_DENIED"
    assert "Secret host path" not in json.dumps(proj_perm)

    # 3. Missing file
    def reader_missing(path: Path, expected_sha256: str, max_bytes: int) -> bytes:
        raise FileNotFoundError("Missing private log")

    with pytest.raises(PriorNativeReplayError) as exc_missing:
        replay_saved_fable_failure(root, reader=reader_missing, expected_bindings=bindings)
    assert exc_missing.value.code == "PROTECTED_READ_FILE_MISSING"
    proj_missing = sanitize_replay_error(exc_missing.value)
    assert proj_missing["code"] == "PROTECTED_READ_FILE_MISSING"
    assert "Missing private log" not in json.dumps(proj_missing)
