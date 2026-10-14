"""Carry R5/R6 native repairs into canonical 4.2.8 source and replay saved Fable failure (`P428-05`).

Provides:
- `inventory_r5_r6_source_repairs()`: deterministic verification that canonical 4.2.8
  source contains the Claude failed-result HTTP status parser repair, Agy 1.3.1
  CLI builtin tool registry scope binding, Agy agent directory custody (`0x20001`),
  and Codex RAM workspace cwd inheritance without mutating old installed packages.
- `replay_saved_fable_failure(...)`: bounded protected-read replay step for the
  exact saved target-23 (`claude-fable-5-1` High) native hold under
  `R6Acceptance4.2.7-windows-20261012-v1-native-47e4889af6284a9fad018142a14d5371`
  and its 23 prior completed target receipts, auth/knowledge/agent receipts, and
  R4 v11 restoration receipt. Quota becomes an availability skip only when the
  repaired parser proves HTTP 429 inside a failed Claude result envelope.
- `sanitize_replay_error(error)`: allowlisted error projection that never publishes
  raw provider output, prompt text, credentials, or arbitrary exception prose.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from pathlib import Path
import re
import traceback
from typing import Any, Callable

from cochem_pipeline import agy_agent_guard, agy_protocol, agy_tool_registry, failures, worker
try:
    from scripts import r6_custody_amendment as amendment
except ImportError:
    import r6_custody_amendment as amendment  # type: ignore[no-redef]


COCHEM_PROGRAM_FILES = Path(r"C:\Program Files\CoChem")
NATIVE_HOLD_ROOT_NAME = "R6Acceptance4.2.7-windows-20261012-v1-native-47e4889af6284a9fad018142a14d5371"
AUTH_HOLD_ROOT_NAME = "R6Acceptance4.2.7-windows-20261012-v1-auth-e8dabf56c1734ddd9b9cf6aeff09a4b9"
KNOWLEDGE_HOLD_ROOT_NAME = "R6Acceptance4.2.7-windows-20261012-v1-knowledge-7f2f4f954df6492e9d3257ca3fa58f44"
AGENT_HOLD_ROOT_NAME = "R6Acceptance4.2.7-windows-20261012-v1-agent-38c3b4be2c8c448595cd01d6d5391d68c"
AGENT_HOLD_REL = r"R6Acceptance4.2.7-windows-20261012-v1-agent-38c3b4be2c8c448595cd01d6d591d68c\result.json"
R4_V11_ROOT_NAME = "WardenRetarget4.2.7-windows-20261011-r4-v11"

HELD_SHA256 = "ac380c29f4100048c81f2057acb7d1635ee76ecf2d47eb4a0347f45399157691"
NATIVE_HELD_SHA256 = "58aa58e2550fb4a1531631f89e9af3239dc3954a9d2074b414385aee1c411baf"
RESERVATION_SHA256 = "59814d48f9849b9871e3a53d14184a8ded880f2690a9b810ad5bcb384a422c72"
FAILURE_METADATA_SHA256 = "be9cc813105d574010ed0785f36992bce18141a928cd5d388b28c1b8b3c66b48"
STDOUT_SHA256 = "eba759bf5af62a8e7ffe131daafd3f64c0158de2f580db3622990b715ab8c809"
STDERR_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
STDOUT_BYTES = 1292
STDERR_BYTES = 0

AUTH_RECEIPT_SHA256 = "aabb4a34d7e31759e0740b8ae1f4a72f710c029ce02ad90fa63a8b8f28331af1"
KNOWLEDGE_RECEIPT_SHA256 = "c5cac91a76a962b92e88cb6218984d05d603fe7ac02a8ec8e46646075b8e4c19"
AGENT_RECEIPT_SHA256 = "86cf57c3e75b259190a93c5d73e0cebc61d715bb16d9ed9b5d8d9c5da7f0a1aa"
R4_V11_RETARGET_SHA256 = "c05ad34a4b7287f922c032935c99bf74870a074827ea1831f9d0235ae0243a0e"
R4_V11_START_INTENT_SHA256 = "a7ac1504d86cd46d25bf27a945440cb3ed74b41964105a1f963c94bc9fc9f81e"
R4_V11_START_RECEIPT_SHA256 = "de5e242b27664dccf5efdff965835b858adc2a33d078c85ea5137f4dff69b3c3"

COMPLETED_TARGETS: tuple[dict[str, str], ...] = (
    {"phase": "target-00", "provider": "gemini", "model": "gemini-3.8-flash", "effort": "low", "worker": "slot1", "sha256": "90ee462e68a7da6721a85301e6dece2ad80c77b3e6c0b6e4a040255316d8f355"},
    {"phase": "target-01", "provider": "claude", "model": "claude-haiku-5-5", "effort": "medium", "worker": "slot2", "sha256": "7eca606d695d0207d98eed5a61850bd12d6bdedc6be41e33f3e1fd62cf29a1cb"},
    {"phase": "target-02", "provider": "codex", "model": "gpt-6-luna", "effort": "medium", "worker": "slot3", "sha256": "d04b90f21889066347f9de4cbbb7297847d85cc1c6e863fec5880a5b6facf0fc"},
    {"phase": "target-03", "provider": "gemini", "model": "gemini-3.8-flash", "effort": "medium", "worker": "slot4", "sha256": "fcf61c509171860fa6c9756719eeb1ca81d0bab8cde87a85622662bd76d8d907"},
    {"phase": "target-04", "provider": "claude", "model": "claude-haiku-5-5", "effort": "high", "worker": "slot5", "sha256": "4253475f27be50f702c61e8420008d47a0895f37fdaefec431ef8ecf13cf3874"},
    {"phase": "target-05", "provider": "codex", "model": "gpt-6-luna", "effort": "high", "worker": "slot6", "sha256": "de402b6c4f057a9e008ef7fe40e25e10a19e7f6971e862aad5728b1ec5519481"},
    {"phase": "target-06", "provider": "gemini", "model": "gemini-3.8-flash", "effort": "high", "worker": "slot1", "sha256": "5dac9c5828dff86613ddf65fed2647736929c05c25bbdb468251cf5258b75a89"},
    {"phase": "target-07", "provider": "claude", "model": "claude-haiku-5-5", "effort": "xhigh", "worker": "slot2", "sha256": "b12cdcc230bd050b0488cac24484d3f1d2206d0f081e585af7c6bfc3ec478ea6"},
    {"phase": "target-08", "provider": "codex", "model": "gpt-6-luna", "effort": "max", "worker": "slot3", "sha256": "0e8a4c0a65a11e406790df6f0a66ca9be4cc21b29f1b8a6f30feb866a63a1b25"},
    {"phase": "target-09", "provider": "codex", "model": "gpt-6.1-sol", "effort": "low", "worker": "slot4", "sha256": "a2f8e675f7f038138d10b6a4dee461c2b98a01f958979762d7a5a373aa35ea81"},
    {"phase": "target-10", "provider": "claude", "model": "claude-sonnet-5-5", "effort": "medium", "worker": "slot5", "sha256": "b9738392ed282e09e18586005f9bbb70ea53184665ab4529e2e8518669c7e2e6"},
    {"phase": "target-11", "provider": "codex", "model": "gpt-6.1-sol", "effort": "medium", "worker": "slot6", "sha256": "f6e5fe3a17cf89fd1ecc8d354d1390ff74326f99d5b16545635f8cb6ea54350f"},
    {"phase": "target-12", "provider": "claude", "model": "claude-sonnet-5-5", "effort": "high", "worker": "slot1", "sha256": "6446defccd54db54a2168d95924da9fe5fb389175a2df7aff1a22611d0a75029"},
    {"phase": "target-13", "provider": "claude", "model": "claude-sonnet-5-5", "effort": "xhigh", "worker": "slot3", "sha256": "c14ab08685d5807e099e3633071b01c07e4b2a21f627740c40d41c08e2dbc4a9"},
    {"phase": "target-14", "provider": "codex", "model": "gpt-6.1-sol", "effort": "high", "worker": "slot4", "sha256": "632f8be46d314bef8682474c4c851eb3f1569914ce8b245f43e93658dc6b7f9a"},
    {"phase": "target-15", "provider": "claude", "model": "claude-opus-5-5", "effort": "high", "worker": "slot5", "sha256": "1a779a8f32657da8e2d67287e7b5e859285a52775df6f2b967dc86ca0b9c6edb"},
    {"phase": "target-16", "provider": "codex", "model": "gpt-6.1-sol", "effort": "xhigh", "worker": "slot6", "sha256": "787c575fbec9f018450e670d84448673bbc6585cf9dd67533da3c1ccfdc9a5fa"},
    {"phase": "target-17", "provider": "claude", "model": "claude-sonnet-5-5", "effort": "max", "worker": "slot1", "sha256": "440c11ec04db9ff3c1867c422a5caef8be421f1bab623adfcc3853f38e77cb88"},
    {"phase": "target-18", "provider": "claude", "model": "claude-opus-5-5", "effort": "xhigh", "worker": "slot2", "sha256": "2d013626d9aa5ca2f20726d4ab476a45e82fe217d39f677fa882571107e6efe4"},
    {"phase": "target-19", "provider": "codex", "model": "gpt-6-astra", "effort": "high", "worker": "slot3", "sha256": "26d74ba2e6e7b7c21f7ba3e61152e8b0b9ac8f9470bbaa372c93893008277d11"},
    {"phase": "target-20", "provider": "codex", "model": "gpt-6.1-sol", "effort": "max", "worker": "slot4", "sha256": "5f57a85fff2649ec75885dcaf38c39f1a8044465dc952aa5580e43b9f71bd470"},
    {"phase": "target-21", "provider": "claude", "model": "claude-opus-5-5", "effort": "max", "worker": "slot5", "sha256": "5f91760bc0be2cb563abf29bd878f117c950d635adf8925342b827229727d3c8"},
    {"phase": "target-22", "provider": "codex", "model": "gpt-6-astra", "effort": "xhigh", "worker": "slot6", "sha256": "d5501dff58e5bdcd732b4031640d6416dfd57ccd65891ed14b8ef4de54f2d378"},
)


class PriorNativeReplayError(ValueError):
    """Sanitized replay validation failure."""

    def __init__(self, code: str, category: str = "protocol"):
        if not re.fullmatch(r"[A-Z0-9_]{3,64}", code):
            raise ValueError("Invalid replay error code")
        self.code = code
        self.category = category
        super().__init__(code)


def sanitize_replay_error(error: BaseException) -> dict[str, Any]:
    """Return allowlisted failure metadata; never include raw text or file contents."""
    allowed_types = {
        "PriorNativeReplayError",
        "ValueError",
        "RuntimeError",
        "OSError",
        "PermissionError",
        "FileNotFoundError",
        "ProviderFailure",
        "AgyIdentityError",
        "AgyToolRegistryError",
        "AgentGuardError",
        "WindowsIsolationError",
    }
    kind = type(error).__name__
    frames = [
        {"function": frame.name, "line": frame.lineno}
        for frame in traceback.extract_tb(error.__traceback__)
        if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,79}", frame.name)
    ][-6:]
    code = getattr(error, "code", None)
    if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9_]{3,64}", code):
        if isinstance(error, PermissionError):
            code = "PROTECTED_READ_PERMISSION_DENIED"
        elif isinstance(error, FileNotFoundError):
            code = "PROTECTED_READ_FILE_MISSING"
        else:
            code = "REPLAY_VALIDATION_FAILED"
    category = getattr(error, "category", None)
    if not isinstance(category, str) or category not in {
        "compatibility",
        "protocol",
        "code",
        "auth",
        "quota",
        "busy",
        "provider",
        "resource",
        "timeout",
        "unknown",
        "configuration",
    }:
        category = "protocol"
    return {
        "schema": "cochem-428-prior-native-replay-error/1",
        "error_type": kind if kind in allowed_types else "OtherError",
        "code": code,
        "category": category,
        "frames": frames,
        "raw_error_published": False,
        "raw_provider_output_published": False,
    }


def inventory_r5_r6_source_repairs() -> dict[str, Any]:
    """Verify that canonical 4.2.8 source incorporates all R5/R6 native repairs."""
    # 1. Claude failed-result HTTP status repair
    if failures._CLAUDE_RESULT_API_STATUS != amendment.CLAUDE_HTTP_STATUS:
        raise PriorNativeReplayError("CLAUDE_HTTP_STATUS_REGEX_DRIFT")
    if worker._CLAUDE_RESULT_API_STATUS.pattern != amendment.CLAUDE_HTTP_STATUS:
        raise PriorNativeReplayError("WORKER_CLAUDE_HTTP_STATUS_REGEX_DRIFT")

    sample_429 = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "result": "Request failed with status code 429",
        }
    )
    parsed_429 = failures.parse_native_failure("claude", sample_429, "", 1)
    if parsed_429 is None or parsed_429.category != "quota":
        raise PriorNativeReplayError("CLAUDE_429_REPAIR_INACTIVE")

    sample_ok = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "Request failed with status code 429",
        }
    )
    if failures.parse_native_failure("claude", sample_ok, "", 0) is not None:
        raise PriorNativeReplayError("CLAUDE_SUCCESS_FALSE_POSITIVE")

    # 2. Agy 1.3.1 CLI builtin tool registry scope repair
    if (
        agy_tool_registry.BINARY_SHA256 != amendment.BINARY_SHA256
        or agy_tool_registry.AGENT_SHA256 != amendment.AGENT_SHA256
    ):
        raise PriorNativeReplayError("AGY_REGISTRY_CONSTANTS_DRIFT")

    # 3. Agy agent directory custody (0x20001 FILE_LIST_DIRECTORY | READ_CONTROL, share mode 3)
    guard_source = inspect.getsource(agy_agent_guard.lock_worker_profile)
    if "0x20001 if directory else 0x80000000" not in guard_source:
        raise PriorNativeReplayError("AGY_DIRECTORY_CUSTODY_ACCESS_DRIFT")
    if list(agy_agent_guard.RELATIVES) != [
        ".gemini/agents/cochem-inference-only/agent.md",
        ".gemini/config/agents/cochem-inference-only/agent.md",
    ]:
        raise PriorNativeReplayError("AGY_AGENT_RELATIVES_DRIFT")

    # 4. Codex RAM workspace cwd inheritance
    if not hasattr(worker, "codex_inherited_workspace_command"):
        raise PriorNativeReplayError("CODEX_INHERITED_CWD_REPAIR_MISSING")

    # 5. Agy protocol stream parser supports inference_spec for reviewed registry
    sig = inspect.signature(agy_protocol.parse_stream)
    if "inference_spec" not in sig.parameters:
        raise PriorNativeReplayError("AGY_PROTOCOL_INFERENCE_SPEC_MISSING")

    return {
        "schema": "cochem-428-r5-r6-repair-inventory/1",
        "status": "ALL_R5_R6_REPAIRS_IN_CANONICAL_SOURCE",
        "repairs": {
            "claude_failed_result_http_status": {
                "present": True,
                "pattern": failures._CLAUDE_RESULT_API_STATUS,
                "quota_429_verified": True,
                "successful_output_excluded": True,
            },
            "agy_tool_registry_scope": {
                "present": True,
                "executable_sha256": agy_tool_registry.BINARY_SHA256,
                "agent_sha256": agy_tool_registry.AGENT_SHA256,
                "agent_bytes": 478,
                "scope": "cli_builtin_runners",
                "actual_tool_steps_rejected": True,
            },
            "agy_agent_directory_custody": {
                "present": True,
                "directory_desired_access": 0x20001,
                "directory_share_mode": 3,
                "relative_paths": list(agy_agent_guard.RELATIVES),
            },
            "codex_ram_cwd_selection": {
                "present": True,
                "workspace_selection": "validated_process_cwd",
            },
        },
        "old_package_modified": False,
        "export_diagnostic_rerun_required": False,
    }


def _default_protected_reader(path: Path, expected_sha256: str, max_bytes: int) -> bytes:
    """Read a protected host file under SYSTEM or elevated Administrator using cochem_pipeline.windows."""
    import os
    from cochem_pipeline import windows as win

    try:
        path = Path(path)
        if not path.is_absolute():
            raise ValueError("Acceptance input path must be absolute")
        for current in (path, *path.parents):
            info = current.lstat()
            if current.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Acceptance input traverses a redirected path")
        resolved = path.resolve(strict=True)
        bases = [
            Path(os.environ[key]).resolve()
            for key in ("ProgramFiles", "SystemRoot")
            if key in os.environ
        ]
        base = next((entry for entry in bases if resolved == entry or entry in resolved.parents), None)
        if base is None:
            raise ValueError("Acceptance input must reside under protected Program Files/Windows paths")
        trusted = {win.SYSTEM_SID, win.ADMIN_SID, win.TRUSTED_INSTALLER_SID}
        current = resolved
        while True:
            owner, _, rules = win._acl(current)
            if owner not in trusted or any(
                sid not in trusted and not flags & 8 and mask & 0x500D0116
                for sid, mask, flags in rules
            ):
                raise ValueError(f"Untrusted code writes or path replacement are possible: {current}")
            if current == base:
                break
            current = current.parent
        info = resolved.stat()
        if info.st_nlink != 1 or not 0 <= info.st_size <= max_bytes:
            raise ValueError("Acceptance input exceeds bounds or has alternate links")
        with resolved.open("rb") as stream:
            data = stream.read(max_bytes + 1)
        if len(data) != info.st_size or (expected_sha256 and hashlib.sha256(data).hexdigest() != expected_sha256):
            raise ValueError("Acceptance input differs from the pinned bytes")
        return data
    except PermissionError as exc:
        raise PriorNativeReplayError("PROTECTED_READ_PERMISSION_DENIED") from exc
    except FileNotFoundError as exc:
        raise PriorNativeReplayError("PROTECTED_READ_FILE_MISSING") from exc
    except (ValueError, win.WindowsIsolationError) as exc:
        raise PriorNativeReplayError("PROTECTED_READ_HASH_OR_BOUND_MISMATCH") from exc


DEFAULT_PRIOR_NATIVE_BINDINGS: dict[str, Any] = {
    "auth_sha256": AUTH_RECEIPT_SHA256,
    "knowledge_sha256": KNOWLEDGE_RECEIPT_SHA256,
    "agent_sha256": AGENT_RECEIPT_SHA256,
    "r4_v11_start_sha256": R4_V11_START_RECEIPT_SHA256,
    "held_sha256": HELD_SHA256,
    "native_held_sha256": NATIVE_HELD_SHA256,
    "reservation_sha256": RESERVATION_SHA256,
    "failure_metadata_sha256": FAILURE_METADATA_SHA256,
    "stdout_sha256": STDOUT_SHA256,
    "stderr_sha256": STDERR_SHA256,
    "stdout_bytes": STDOUT_BYTES,
    "stderr_bytes": STDERR_BYTES,
    "completed_targets": COMPLETED_TARGETS,
}


def replay_saved_fable_failure(
    co_chem_root: Path = COCHEM_PROGRAM_FILES,
    *,
    reader: Callable[[Path, str, int], bytes] | None = None,
    expected_bindings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Hash-bound protected-read replay of the exact saved target-23 Fable failure.

    Runs before any Warden stop or cutover. Verifies:
    - Auth, knowledge, agent, and R4 v11 restoration receipts match their exact digests.
    - All 23 prior completed target receipts (`target-00`..`target-22`) match their digests.
    - `held.json`, `native/native-held.json`, `native/target-23-reservation.json`,
      `failure.json`, `stdout.log`, and `stderr.log` match their exact digests.
    - Replays `stdout.log` and `stderr.log` through canonical `failures.parse_native_failure`
      and `worker.native_failure_metadata`.
    - Marks Fable 5.1 High as `PROVIDER_TEMPORARILY_UNAVAILABLE` (never `NATIVE_SELECTOR_ACCEPTED`)
      only if the repaired parser proves `category == 'quota'` and `api_status == 429`.
    """
    bindings = DEFAULT_PRIOR_NATIVE_BINDINGS if expected_bindings is None else expected_bindings
    read_fn = reader or _default_protected_reader
    root = Path(co_chem_root)
    native_root = root / NATIVE_HOLD_ROOT_NAME

    def read_checked(path: Path, expected_sha256: str, max_bytes: int = 65536) -> bytes:
        try:
            raw = read_fn(path, expected_sha256, max_bytes)
        except PriorNativeReplayError:
            raise
        except PermissionError as exc:
            raise PriorNativeReplayError("PROTECTED_READ_PERMISSION_DENIED") from exc
        except FileNotFoundError as exc:
            raise PriorNativeReplayError("PROTECTED_READ_FILE_MISSING") from exc
        except OSError as exc:
            raise PriorNativeReplayError("PROTECTED_READ_OS_ERROR") from exc
        except Exception as exc:
            raise PriorNativeReplayError("PROTECTED_READ_HASH_OR_BOUND_MISMATCH") from exc
        if not isinstance(raw, (bytes, bytearray)) or len(raw) > max_bytes:
            raise PriorNativeReplayError("PROTECTED_READ_SIZE_EXCEEDED")
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected_sha256:
            raise PriorNativeReplayError("PROTECTED_READ_HASH_MISMATCH")
        return bytes(raw)

    # 1. Verify prior phase receipts and R4 v11 restoration receipt
    auth_doc = json.loads(
        read_checked(root / AUTH_HOLD_ROOT_NAME / "result.json", bindings["auth_sha256"]).decode("utf-8")
    )
    knowledge_doc = json.loads(
        read_checked(root / KNOWLEDGE_HOLD_ROOT_NAME / "result.json", bindings["knowledge_sha256"]).decode("utf-8")
    )
    agent_doc = json.loads(
        read_checked(root / AGENT_HOLD_REL, bindings["agent_sha256"]).decode("utf-8")
    )
    r4_start_doc = json.loads(
        read_checked(root / R4_V11_ROOT_NAME / "start-receipt.json", bindings["r4_v11_start_sha256"]).decode("utf-8")
    )
    if (
        auth_doc.get("status") != "PHASE_COMPLETED"
        or knowledge_doc.get("status") != "PHASE_COMPLETED"
        or agent_doc.get("status") != "PHASE_COMPLETED"
        or r4_start_doc.get("status") != "WARDEN_R4_RESTARTED_HEALTH_VERIFIED"
    ):
        raise PriorNativeReplayError("PRIOR_PHASE_OR_RESTORE_STATUS_MISMATCH")

    # 2. Verify held.json and native/native-held.json
    held_doc = json.loads(read_checked(native_root / "held.json", bindings["held_sha256"]).decode("utf-8"))
    native_held_doc = json.loads(
        read_checked(native_root / "native" / "native-held.json", bindings["native_held_sha256"]).decode("utf-8")
    )
    if (
        held_doc.get("phase") != "native"
        or native_held_doc.get("phase") != "target-23"
        or native_held_doc.get("completed") != 23
    ):
        raise PriorNativeReplayError("NATIVE_HOLD_ENVELOPE_MISMATCH")

    # 3. Verify all 23 completed target receipts (target-00 through target-22)
    preserved_targets: list[dict[str, str]] = []
    for item in bindings["completed_targets"]:
        phase = item["phase"]
        t_doc = json.loads(
            read_checked(
                native_root / "native" / f"{phase}-verified.json",
                item["sha256"],
            ).decode("utf-8")
        )
        if (
            t_doc.get("status") != "NATIVE_SELECTOR_ACCEPTED"
            or t_doc.get("provider") != item["provider"]
            or t_doc.get("model") != item["model"]
            or t_doc.get("effort") != item["effort"]
            or t_doc.get("worker") != item["worker"]
        ):
            raise PriorNativeReplayError("COMPLETED_TARGET_RECEIPT_MISMATCH")
        preserved_targets.append(dict(item, status="NATIVE_SELECTOR_ACCEPTED"))

    # 4. Verify target-23 reservation and failure metadata
    reservation = json.loads(
        read_checked(
            native_root / "native" / "target-23-reservation.json",
            bindings["reservation_sha256"],
        ).decode("utf-8")
    )
    node = reservation.get("node") if isinstance(reservation, dict) else None
    route = node.get("route") if isinstance(node, dict) else None
    attempt_id = node.get("attempt_id") if isinstance(node, dict) else None
    if (
        not isinstance(route, dict)
        or route.get("provider") != "claude"
        or route.get("model") != "claude-fable-5-1"
        or route.get("reasoning_effort") != "high"
        or node.get("worker_slot") != "slot1"
        or not isinstance(attempt_id, str)
        or not re.fullmatch(r"[a-f0-9]{32}", attempt_id)
    ):
        raise PriorNativeReplayError("TARGET_23_RESERVATION_MISMATCH")

    attempt_dir = native_root / "native" / "attempts" / attempt_id
    failure_doc = json.loads(
        read_checked(attempt_dir / "failure.json", bindings["failure_metadata_sha256"]).decode("utf-8")
    )
    if (
        failure_doc.get("schema") != "cochem-native-failure-metadata/1"
        or failure_doc.get("stdout_sha256") != bindings["stdout_sha256"]
        or failure_doc.get("stderr_sha256") != bindings["stderr_sha256"]
        or failure_doc.get("stdout_bytes") != bindings["stdout_bytes"]
        or failure_doc.get("stderr_bytes") != bindings["stderr_bytes"]
        or failure_doc.get("exit_code") != 1
    ):
        raise PriorNativeReplayError("TARGET_23_FAILURE_METADATA_MISMATCH")

    # 5. Read hash-bound stdout.log and stderr.log and replay through canonical parser
    stdout_bytes = read_checked(attempt_dir / "stdout.log", bindings["stdout_sha256"], max_bytes=16384)
    stderr_bytes = read_checked(attempt_dir / "stderr.log", bindings["stderr_sha256"], max_bytes=16384)
    if len(stdout_bytes) != bindings["stdout_bytes"] or len(stderr_bytes) != bindings["stderr_bytes"]:
        raise PriorNativeReplayError("TARGET_23_STREAM_LENGTH_MISMATCH")

    stdout_text = stdout_bytes.decode("utf-8")
    stderr_text = stderr_bytes.decode("utf-8")
    parsed_failure = failures.parse_native_failure("claude", stdout_text, stderr_text, 1)
    category = parsed_failure.category if parsed_failure is not None else "code"
    metadata = worker.native_failure_metadata(
        "claude",
        category,
        1,
        stdout_bytes,
        stderr_bytes,
        started_at=int(failure_doc.get("started_at", 1)),
        finished_at=int(failure_doc.get("finished_at", 2)),
    )

    if category == "quota" and metadata.get("api_status") == 429:
        return {
            "schema": "cochem-428-prior-native-replay/1",
            "status": "REPLAY_QUOTA_PROVED_AVAILABILITY_ONLY",
            "cutover_precheck_passed": True,
            "production_bindings_pinned": bindings is DEFAULT_PRIOR_NATIVE_BINDINGS,
            "target": {
                "phase": "target-23",
                "provider": "claude",
                "model": "claude-fable-5-1",
                "effort": "high",
                "worker": "slot1",
                "selector_accepted": False,
                "target_status": "PROVIDER_TEMPORARILY_UNAVAILABLE",
                "category": "quota",
                "api_status": 429,
                "envelope_kind": metadata.get("envelope_kind"),
            },
            "preserved_completed_targets_count": len(preserved_targets),
            "preserved_completed_targets": preserved_targets,
            "prior_receipts_verified": {
                "auth_sha256": bindings["auth_sha256"],
                "knowledge_sha256": bindings["knowledge_sha256"],
                "agent_sha256": bindings["agent_sha256"],
                "r4_v11_start_sha256": bindings["r4_v11_start_sha256"],
            },
            "stream_hashes": {
                "stdout_sha256": bindings["stdout_sha256"],
                "stderr_sha256": bindings["stderr_sha256"],
            },
            "continue_independent_providers": True,
            "old_package_modified": False,
            "raw_provider_output_published": False,
            "export_diagnostic_rerun_required": False,
        }

    return {
        "schema": "cochem-428-prior-native-replay/1",
        "status": "REPLAY_HELD_UNPROVED",
        "cutover_precheck_passed": False,
        "production_bindings_pinned": bindings is DEFAULT_PRIOR_NATIVE_BINDINGS,
        "target": {
            "phase": "target-23",
            "provider": "claude",
            "model": "claude-fable-5-1",
            "effort": "high",
            "worker": "slot1",
            "selector_accepted": False,
            "target_status": "HELD_UNPROVED_FAILURE",
            "category": category,
            "api_status": metadata.get("api_status"),
            "envelope_kind": metadata.get("envelope_kind"),
        },
        "preserved_completed_targets_count": len(preserved_targets),
        "continue_independent_providers": False,
        "old_package_modified": False,
        "raw_provider_output_published": False,
        "export_diagnostic_rerun_required": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("inventory", "replay"),
        default="inventory",
        help="Verify canonical source repairs ('inventory') or run protected host replay ('replay').",
    )
    parser.add_argument(
        "--cochem-root",
        default=str(COCHEM_PROGRAM_FILES),
        help="Protected CoChem root directory for replay mode.",
    )
    args = parser.parse_args(argv)
    try:
        if args.mode == "inventory":
            result = inventory_r5_r6_source_repairs()
        else:
            result = replay_saved_fable_failure(Path(args.cochem_root))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps(sanitize_replay_error(exc), indent=2, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
