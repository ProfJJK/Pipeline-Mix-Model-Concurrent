"""4.2.8 native acceptance planner, front-loaded sign-in verifier, and replay guard (`P428-26`).

Engineering sessions may run `--mode plan` (the default) or call the pure verification
helpers in `pytest`. Physical host execution (`--mode accept --apply`) is reserved
exclusively for the owner-run sitting (`P428-28`).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlparse

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = next(
    (
        cand
        for cand in (_SCRIPT_DIR.parent, Path.cwd())
        if (cand / "src" / "cochem_pipeline").is_dir()
    ),
    _SCRIPT_DIR.parent,
)
for _p in (str(_SCRIPT_DIR), str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)

from cochem_pipeline.argon_catalog import (
    EFFORTS as ARGON_EFFORTS,
    MODEL as ARGON_MODEL,
    build_argon_owner_acceptance_spec,
    prepare_argon_candidate,
    verify_argon_probe_fixture,
)
from cochem_supervisor.repair_admission_428 import DEFAULT_REPAIR_PROFILES
try:
    from scripts.verify_prior_native_428 import (
        inventory_r5_r6_source_repairs,
        replay_saved_fable_failure,
        sanitize_replay_error,
    )
except ImportError:
    from verify_prior_native_428 import (  # type: ignore[no-redef]
        inventory_r5_r6_source_repairs,
        replay_saved_fable_failure,
        sanitize_replay_error,
    )


SCHEMA_PLAN = "cochem-428-native-acceptance-plan/1"
SCHEMA_RESULT = "cochem-428-native-acceptance/1"
INPUT_WINDOW_MINUTES = 20

WORKER_SLOTS: tuple[str, ...] = ("slot1", "slot2", "slot3", "slot4", "slot5")
PROVIDERS: tuple[str, ...] = ("codex", "claude", "gemini")
REQUIRED_WORKER_PROFILES: tuple[str, ...] = tuple(
    f"{slot}:{provider}" for slot in WORKER_SLOTS for provider in PROVIDERS
)
REQUIRED_REPAIR_PROFILES: tuple[str, ...] = (
    "repair_claude:claude",
    "repair_codex:codex",
    "repair_agy:gemini",
)
REPRESENTATIVE_WORKFLOWS: tuple[str, ...] = (
    "simple_approved_task",
    "multitype_wbs_dag",
    "research_grounded_planning",
    "owner_approved_high_tier",
    "recovery_10_20_30_cascade",
    "independent_repair_isolation",
)


class NativeAcceptanceHold(ValueError):
    """Deterministic hold raised when a 4.2.8 acceptance invariant fails."""

    def __init__(self, code: str, category: str = "protocol", detail: str = "") -> None:
        if not re.fullmatch(r"[A-Z0-9_]{3,64}", code):
            raise ValueError("Invalid acceptance hold code")
        self.code = code
        self.category = category
        self.detail = detail
        super().__init__(code)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return bool(stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400)


def check_front_loaded_input_window(
    started_utc: datetime,
    now_utc: datetime,
    *,
    max_minutes: int = INPUT_WINDOW_MINUTES,
    oauth_url: str | None = None,
    seen_oauth_urls: set[str] | None = None,
    dialog_id: str | None = None,
    seen_dialogs: set[str] | None = None,
) -> dict[str, Any]:
    """Verify that any owner prompt, fresh OAuth URL, or dialog occurs within the first 20 minutes."""
    if started_utc.tzinfo is None or now_utc.tzinfo is None:
        raise NativeAcceptanceHold("NAIVE_TIMESTAMP_REJECTED", "protocol")
    elapsed_seconds = (now_utc.astimezone(timezone.utc) - started_utc.astimezone(timezone.utc)).total_seconds()
    if elapsed_seconds < 0:
        raise NativeAcceptanceHold("CLOCK_SKEW_REJECTED", "protocol")
    limit_seconds = max_minutes * 60
    if elapsed_seconds > limit_seconds:
        raise NativeAcceptanceHold("INPUT_WINDOW_EXPIRED", "auth")

    validated_url: str | None = None
    if oauth_url is not None:
        if (
            not isinstance(oauth_url, str)
            or not oauth_url
            or len(oauth_url) > 2048
            or re.search(r"[\s\x00-\x1f]", oauth_url)
        ):
            raise NativeAcceptanceHold("INVALID_OAUTH_URL", "auth")
        parsed = urlparse(oauth_url)
        if parsed.scheme != "https" or not parsed.netloc or not parsed.query:
            raise NativeAcceptanceHold("INSECURE_OR_INCOMPLETE_OAUTH_URL", "auth")
        if seen_oauth_urls is not None:
            if oauth_url in seen_oauth_urls:
                raise NativeAcceptanceHold("STALE_OR_REPLAYED_OAUTH_URL", "auth")
            seen_oauth_urls.add(oauth_url)
        validated_url = hashlib.sha256(oauth_url.encode("utf-8")).hexdigest()

    validated_dialog: str | None = None
    if dialog_id is not None:
        if not isinstance(dialog_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{4,128}", dialog_id):
            raise NativeAcceptanceHold("INVALID_DIALOG_ID", "auth")
        if seen_dialogs is not None:
            if dialog_id in seen_dialogs:
                raise NativeAcceptanceHold("REPLAYED_OWNER_DIALOG", "auth")
            seen_dialogs.add(dialog_id)
        validated_dialog = dialog_id

    return {
        "schema": "cochem-428-input-window-check/1",
        "within_window": True,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "remaining_seconds": round(limit_seconds - elapsed_seconds, 3),
        "max_minutes": max_minutes,
        "late_prompt": False,
        "oauth_url_sha256": validated_url,
        "dialog_id": validated_dialog,
    }


def evaluate_profile_signin_plan(
    verified_profiles: Iterable[str],
    *,
    owner_secret_configured: bool = True,
) -> dict[str, Any]:
    """Determine which worker and dedicated repair profiles are reused vs need front-loaded sign-in."""
    verified_set = {str(item) for item in verified_profiles}
    unknown = sorted(
        verified_set - (set(REQUIRED_WORKER_PROFILES) | set(REQUIRED_REPAIR_PROFILES))
    )
    if unknown:
        raise NativeAcceptanceHold("UNKNOWN_PROFILE_IN_SIGNIN_STATE", "configuration")

    reused_workers = [p for p in REQUIRED_WORKER_PROFILES if p in verified_set]
    missing_workers = [p for p in REQUIRED_WORKER_PROFILES if p not in verified_set]
    reused_repairs = [p for p in REQUIRED_REPAIR_PROFILES if p in verified_set]
    missing_repairs = [p for p in REQUIRED_REPAIR_PROFILES if p not in verified_set]

    repair_accounts = {
        key: {
            "account_name": key,
            "provider": profile["provider"],
            "quota_pool": profile["quota_pool"],
            "consumes_worker_slot": False,
        }
        for key, profile in sorted(DEFAULT_REPAIR_PROFILES.items())
    }

    front_loaded_actions: list[str] = []
    if missing_workers:
        front_loaded_actions.append("worker_profile_signin")
    if missing_repairs:
        front_loaded_actions.append("dedicated_repair_profile_signin")
    if not owner_secret_configured:
        front_loaded_actions.append("owner_approval_secret_setup")

    return {
        "schema": "cochem-428-signin-plan/1",
        "reused_worker_profiles": reused_workers,
        "missing_worker_profiles": missing_workers,
        "reused_repair_profiles": reused_repairs,
        "missing_repair_profiles": missing_repairs,
        "repair_profile_isolation": repair_accounts,
        "owner_secret_configured": bool(owner_secret_configured),
        "front_loaded_actions": front_loaded_actions,
        "interactive_input_required": bool(front_loaded_actions),
        "input_window_minutes": INPUT_WINDOW_MINUTES,
        "late_prompts_allowed": False,
    }


def verify_acceptance_bundle_pins(
    manifest: Mapping[str, Any],
    bundle_dir: Path,
) -> dict[str, Any]:
    """Verify every file listed in launch-manifest.json is present, non-reparse, and matches its SHA-256."""
    bundle_dir = Path(bundle_dir)
    if not isinstance(manifest, Mapping) or manifest.get("schema") != "cochem-428-launch-package/1":
        raise NativeAcceptanceHold("INVALID_LAUNCH_MANIFEST_SCHEMA", "protocol")
    if manifest.get("version") != "4.2.8" or manifest.get("host") != "AETHERDESK":
        raise NativeAcceptanceHold("LAUNCH_MANIFEST_VERSION_OR_HOST_MISMATCH", "protocol")
    if manifest.get("late_prompts") is not False or manifest.get("input_window_minutes") != INPUT_WINDOW_MINUTES:
        raise NativeAcceptanceHold("LAUNCH_MANIFEST_INPUT_WINDOW_DRIFT", "protocol")

    files = manifest.get("files")
    if not isinstance(files, list) or not 8 <= len(files) <= 32:
        raise NativeAcceptanceHold("LAUNCH_MANIFEST_FILES_INVALID", "protocol")

    for parent in (bundle_dir, *bundle_dir.parents):
        if _is_reparse(parent):
            raise NativeAcceptanceHold("BUNDLE_ANCESTOR_REPARSE_REJECTED", "protocol")

    seen: set[str] = set()
    verified: list[dict[str, Any]] = []
    for entry in files:
        if not isinstance(entry, Mapping):
            raise NativeAcceptanceHold("LAUNCH_FILE_RECORD_INVALID", "protocol")
        name = str(entry.get("name", ""))
        expected_sha = str(entry.get("sha256", ""))
        expected_len = entry.get("length")
        if (
            not re.fullmatch(r"[A-Za-z0-9_.-]+", name)
            or name.casefold() in seen
            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha)
            or not isinstance(expected_len, int)
            or expected_len < 0
        ):
            raise NativeAcceptanceHold("LAUNCH_FILE_METADATA_INVALID", "protocol")
        seen.add(name.casefold())
        path = bundle_dir / name
        if _is_reparse(path) or not path.is_file():
            raise NativeAcceptanceHold("PACKAGE_FILE_MISSING_OR_REDIRECTED", "protocol", name)
        raw = path.read_bytes()
        if len(raw) != expected_len or _sha256_bytes(raw) != expected_sha:
            raise NativeAcceptanceHold("PACKAGE_TAMPER_DETECTED", "protocol", name)
        verified.append({"name": name, "sha256": expected_sha, "length": expected_len})

    required_names = {
        "install_428_runtime.ps1",
        "stage_aetherdesk_427_payloads.ps1",
        "pipeline.json",
        "install-manifest.json",
        "source-test-evidence.json",
        "routing-candidate.json",
        "proposal.json",
        "pointer.json",
    }
    if not required_names <= {row["name"] for row in verified}:
        raise NativeAcceptanceHold("REQUIRED_PACKAGE_FILE_MISSING", "protocol")

    return {
        "schema": "cochem-428-package-pin-verification/1",
        "verified_files": len(verified),
        "source_commit": manifest.get("source_commit"),
        "tamper_detected": False,
    }


def verify_prior_repairs_and_fable_replay(
    *,
    cochem_root: Path | None = None,
    protected_reader: Callable[[Path, str, int], bytes] | None = None,
    run_host_replay: bool = False,
) -> dict[str, Any]:
    """Verify canonical 4.2.8 source repairs and optionally replay the saved Fable target-23 hold."""
    source_inventory = inventory_r5_r6_source_repairs()
    if source_inventory.get("status") != "ALL_R5_R6_REPAIRS_IN_CANONICAL_SOURCE":
        raise NativeAcceptanceHold("CANONICAL_SOURCE_REPAIRS_INCOMPLETE", "code")

    if not run_host_replay:
        return {
            "schema": "cochem-428-prior-native-summary/1",
            "source_repairs": source_inventory,
            "host_replay_executed": False,
            "fable_target_23_policy": "QUOTA_429_BECOMES_AVAILABILITY_SKIP_ONLY",
        }

    kwargs: dict[str, Any] = {}
    if cochem_root is not None:
        kwargs["co_chem_root"] = cochem_root
    if protected_reader is not None:
        kwargs["reader"] = protected_reader
    try:
        replay = replay_saved_fable_failure(**kwargs)
    except Exception as exc:
        sanitized = sanitize_replay_error(exc)
        raise NativeAcceptanceHold(
            sanitized["code"],
            sanitized["category"],
        ) from exc

    if replay.get("status") not in {
        "REPLAY_QUOTA_PROVED_AVAILABILITY_ONLY",
        "SAVED_FABLE_QUOTA_SKIP_VERIFIED",
        "PRIOR_NATIVE_REPLAY_VERIFIED",
    }:
        raise NativeAcceptanceHold("FABLE_REPLAY_UNEXPECTED_STATUS", "protocol")

    return {
        "schema": "cochem-428-prior-native-summary/1",
        "source_repairs": source_inventory,
        "host_replay_executed": True,
        "replay_status": replay["status"],
        "completed_targets_verified": replay.get("preserved_completed_targets_count", 23),
        "target_23_disposition": replay.get("target", {}).get("target_status"),
    }


def evaluate_argon_acceptance(
    existing_spec: Mapping[str, Any],
    capture: Mapping[str, Any],
    *,
    probe_fixtures: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate Gemini 4 Argon (`low`, `medium`, `high`) catalog and optional probe results."""
    proposal = prepare_argon_candidate(dict(existing_spec), dict(capture))
    owner_spec = build_argon_owner_acceptance_spec(proposal)

    outcomes: dict[str, dict[str, Any]] = {}
    if probe_fixtures is not None:
        for effort in ARGON_EFFORTS:
            if effort not in probe_fixtures:
                continue
            fx = probe_fixtures[effort]
            outcome = verify_argon_probe_fixture(
                proposal,
                effort,
                raw_stdout=str(fx["raw_stdout"]),
                raw_stderr=str(fx.get("raw_stderr", "")),
                exit_code=int(fx.get("exit_code", 0)),
                binary_sha256=str(fx["binary_sha256"]),
                version_stdout=str(fx["version_stdout"]),
                cleanup_verified=bool(fx["cleanup_verified"]),
                use_agent_registry=bool(fx.get("use_agent_registry", False)),
                reservation_id=str(fx.get("reservation_id", f"argon-{effort}")),
                fencing_token=int(fx.get("fencing_token", 1)),
            )
            if outcome["status"] in {"COMPATIBILITY_HOLD", "PROBE_FAILED", "QUARANTINED_UNCLEAN"}:
                raise NativeAcceptanceHold(
                    f"ARGON_{effort.upper()}_{outcome['status']}",
                    str(outcome.get("category", "compatibility")),
                )
            outcomes[effort] = {
                "status": outcome["status"],
                "category": outcome.get("category"),
                "reason": outcome.get("reason"),
                "cleanup_verified": outcome["cleanup_verified"],
            }

    return {
        "schema": "cochem-428-argon-acceptance-evaluation/1",
        "model": ARGON_MODEL,
        "efforts": list(ARGON_EFFORTS),
        "proposal_sha256": owner_spec["proposal_sha256"],
        "planned_probes": len(owner_spec["probe_plan"]),
        "held_efforts": owner_spec["held_efforts"],
        "outcomes": outcomes,
        "host_accepted": False,
    }


def build_native_acceptance_plan(
    repository: Path,
    *,
    bundle_dir: Path | None = None,
    verified_profiles: Iterable[str] = REQUIRED_WORKER_PROFILES,
    owner_secret_configured: bool = True,
) -> dict[str, Any]:
    """Build the read-only 4.2.8 native acceptance plan without executing native providers."""
    repository = Path(repository)
    routing_cand_path = repository / "docs" / "4.2.8" / "routing-candidate.json"
    if not routing_cand_path.is_file() and bundle_dir is not None:
        cand_in_bundle = Path(bundle_dir) / "routing-candidate.json"
        if cand_in_bundle.is_file():
            routing_cand_path = cand_in_bundle
    validation_doc_path = repository / "docs" / "4.2.8" / "VALIDATION.md"
    if not validation_doc_path.is_file() and bundle_dir is not None:
        source_sibling = (
            Path(bundle_dir).parent
            / f"r428-source-{Path(bundle_dir).name.removeprefix('r428-bundle-')}"
            / "docs"
            / "4.2.8"
            / "VALIDATION.md"
        )
        if source_sibling.is_file():
            validation_doc_path = source_sibling
    if not routing_cand_path.is_file() or not validation_doc_path.is_file():
        raise NativeAcceptanceHold("MISSING_428_ROUTING_OR_VALIDATION_ARTIFACTS", "protocol")

    routing_cand = json.loads(routing_cand_path.read_text(encoding="utf-8"))
    if routing_cand.get("schema") not in {
        "cochem-task-routing/1",
        "cochem-task-routing-candidate/4.2.8",
    }:
        raise NativeAcceptanceHold("INVALID_ROUTING_CANDIDATE_SCHEMA", "protocol")

    signin_plan = evaluate_profile_signin_plan(
        verified_profiles,
        owner_secret_configured=owner_secret_configured,
    )
    prior_summary = verify_prior_repairs_and_fable_replay(run_host_replay=False)

    return {
        "schema": SCHEMA_PLAN,
        "status": "R428_NATIVE_ACCEPTANCE_READ_ONLY_PLAN",
        "version": "4.2.8",
        "host": "AETHERDESK",
        "shared_execution_slots": 4,
        "repair_consumes_worker_slot": False,
        "input_window_minutes": INPUT_WINDOW_MINUTES,
        "late_prompts": False,
        "signin_plan": signin_plan,
        "prior_native_repairs": prior_summary,
        "argon_targets": [f"{ARGON_MODEL}-{effort}" for effort in ARGON_EFFORTS],
        "representative_workflows": list(REPRESENTATIVE_WORKFLOWS),
        "routing_candidate_sha256": _sha256_bytes(routing_cand_path.read_bytes()),
        "validation_doc_sha256": _sha256_bytes(validation_doc_path.read_bytes()),
        "host_executed": False,
        "full_srs_acceptance": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("plan", "accept"),
        default="plan",
    )
    parser.add_argument(
        "--repository",
        type=Path,
        default=_REPO_ROOT,
    )
    parser.add_argument("--bundle-dir", type=Path)
    parser.add_argument("--launch-manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    if args.mode == "plan":
        plan = build_native_acceptance_plan(args.repository, bundle_dir=args.bundle_dir)
        if args.launch_manifest and args.bundle_dir:
            manifest = json.loads(args.launch_manifest.read_text(encoding="utf-8"))
            plan["bundle_pin_verification"] = verify_acceptance_bundle_pins(
                manifest, args.bundle_dir
            )
        rendered = json.dumps(plan, indent=2, sort_keys=True)
        if args.output:
            args.output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0

    if not args.apply:
        raise NativeAcceptanceHold("ACCEPT_REQUIRES_EXPLICIT_APPLY", "protocol")
    if os.environ.get("COMPUTERNAME") != "AETHERDESK":
        raise NativeAcceptanceHold("ACCEPT_REQUIRES_AETHERDESK_HOST", "protocol")

    if not (args.launch_manifest and args.bundle_dir):
        raise NativeAcceptanceHold("ACCEPT_REQUIRES_PINNED_LAUNCH_BUNDLE", "protocol")

    manifest = json.loads(args.launch_manifest.read_text(encoding="utf-8"))
    pin_check = verify_acceptance_bundle_pins(manifest, args.bundle_dir)
    prior = verify_prior_repairs_and_fable_replay(run_host_replay=True)
    result = {
        "schema": SCHEMA_RESULT,
        "status": "R428_PRE_CUTOVER_ACCEPTANCE_VERIFIED",
        "version": "4.2.8",
        "host": "AETHERDESK",
        "bundle_pin_verification": pin_check,
        "prior_native_repairs": prior,
        "late_prompts": False,
        "full_srs_acceptance": False,
    }
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
