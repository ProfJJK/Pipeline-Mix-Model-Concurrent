"""Prepare fresh 4.2.8 offline source freeze, application wheel, and installation bundle (`P428-25`).

Reuses reviewed R6 build helpers (`prepare_r6_install_bundle.read_pinned`,
`prepare_r6_install_bundle.relative`, `prepare_r6_launch_package.read_regular`)
while pinning 4.2.8 version metadata (`cochem-4.2.8-py3-none-any.whl`,
`windows-20261014-428-v1`), binding `docs/4.2.8/VALIDATION.md` and
`docs/4.2.8/routing-candidate.json`, and refusing any stale hardcoded R6
recovery bundle or unreviewed source file. Never installs, elevates, or
executes host acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile
import uuid
import zipfile

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
for _p in (str(SCRIPTS_DIR), str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)

from cochem_pipeline.catalog_activation import compile_change
from cochem_pipeline.config import load_config
from cochem_pipeline.migration_428 import verify_version_alignment
from cochem_pipeline.routing import load_routing_policy
from cochem_pipeline.routing_catalog import retire_owner_gemini_pro
from prepare_r6_install_bundle import read_pinned, relative
from prepare_r6_launch_package import read_regular


MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES = 4096, 16 * 1024**2, 128 * 1024**2
ROOT_FILES = {"README.md", "pyproject.toml", "uv.lock"}
REQUIRED_ARCHIVE_FILES = ROOT_FILES | {
    "src/cochem_pipeline/__main__.py",
    "src/cochem_pipeline/specification/routing_catalog_v3.json",
    "knowledge/v4.1.2_manifest.json",
    "docs/4.2.8/routing-candidate.json",
    "docs/4.2.8/routing-decision-packet.json",
    "docs/4.2.8/VALIDATION.md",
}

PREVIOUS = Path(r"C:\Users\ansac\CoChem427\r6-bundle-359ca92\pipeline.json")
PREVIOUS_PIN = "a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288"
OLD_R6_ROOT = r"C:\Program Files\CoChem\Pipeline4.2.7-windows-20261012-r6-v1"
OLD_R6_KNOWLEDGE_STATE = r"C:\ProgramData\CoChemPipeline427\private\knowledge-windows-20261012-r6-v1"
TARGET_ROOT_428 = r"C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r1"
KNOWLEDGE_STATE_428 = r"C:\ProgramData\CoChemPipeline427\private\knowledge-windows-20261014-428-v1"
REVISION_428 = "windows-20261014-428-v1"
WHEEL_NAME_428 = "cochem-4.2.8-py3-none-any.whl"
DIST_INFO_428 = "cochem-4.2.8.dist-info"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _assert_fresh_destination(destination: Path) -> Path:
    destination = Path(destination).absolute()
    if (
        destination.exists()
        or not destination.is_absolute()
        or not destination.parent.is_dir()
        or any("gdrive" in p.casefold() or "google drive" in p.casefold() for p in destination.parts)
    ):
        raise ValueError("A fresh ordinary destination outside Google Drive is required")
    for path in (destination, destination.parent, *destination.parent.parents):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Destination must not traverse a redirected path")
    return destination


def validate_name_428(name: str, *, allow_parent_dir: bool = False) -> None:
    parts = PurePosixPath(name).parts
    allowed_subtree = (
        parts[:1] in (("src",), ("knowledge",))
        or (len(parts) >= 2 and parts[:2] == ("docs", "4.2.8"))
        or (allow_parent_dir and parts == ("docs",))
        or name in ROOT_FILES
    )
    if (
        not parts
        or name.startswith("/")
        or "\\" in name
        or re.search(r'[\x00-\x1f<>:"|?*]', name)
        or any(
            part in ("", ".", "..")
            or part.endswith((".", " "))
            or re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part)
            for part in name.split("/")
        )
        or not allowed_subtree
    ):
        raise ValueError(f"Source archive contains an unsafe or unexpected path: {name}")


def inspect_archive_428(raw: bytes) -> dict[str, bytes]:
    if not 512 <= len(raw) <= MAX_TOTAL_BYTES:
        raise ValueError("Source archive exceeds its byte bound")
    files: dict[str, bytes] = {}
    folded: set[str] = set()
    total = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for entry in archive:
            name = entry.name.rstrip("/")
            validate_name_428(name, allow_parent_dir=entry.isdir())
            if entry.isdir():
                continue
            if not entry.isfile() or name.casefold() in folded:
                raise ValueError("Source archive contains a link, duplicate or special file")
            if not 0 <= entry.size <= MAX_FILE_BYTES or len(files) >= MAX_FILES:
                raise ValueError("Source archive file exceeds its bound")
            total += entry.size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("Source files exceed their total byte bound")
            stream = archive.extractfile(entry)
            if stream is None:
                raise ValueError("Source archive member stream is unavailable")
            data = stream.read(MAX_FILE_BYTES + 1)
            if len(data) != entry.size:
                raise ValueError("Source archive member is incomplete")
            files[name] = data
            folded.add(name.casefold())
    if not REQUIRED_ARCHIVE_FILES <= files.keys():
        missing = sorted(REQUIRED_ARCHIVE_FILES - files.keys())
        raise ValueError(f"Source archive omits required 4.2.8 runtime, knowledge, or validation assets: {missing}")
    if b'version = "4.2.8"' not in files["pyproject.toml"]:
        raise ValueError("Frozen pyproject.toml does not declare version 4.2.8")
    return files


def freeze_source_428(files: dict[str, bytes], destination: Path, commit: str) -> dict:
    destination = _assert_fresh_destination(destination)
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Freeze requires a full committed Git revision")
    if not 1 <= len(files) <= MAX_FILES or len({name.casefold() for name in files}) != len(files):
        raise ValueError("Source inventory has invalid count or duplicate names")
    for name, data in files.items():
        validate_name_428(name)
        if not isinstance(data, bytes) or len(data) > MAX_FILE_BYTES:
            raise ValueError("Source inventory contains an invalid file")
    if sum(map(len, files.values())) > MAX_TOTAL_BYTES:
        raise ValueError("Source inventory exceeds its total byte bound")
    if not REQUIRED_ARCHIVE_FILES <= files.keys():
        raise ValueError("Source inventory omits required 4.2.8 assets")

    rows = [
        dict(relative=name, length=len(data), sha256=sha(data))
        for name, data in sorted(files.items())
    ]
    manifest = dict(
        schema="cochem-428-source-preparation/1",
        version="4.2.8",
        commit=commit,
        files=rows,
        payload_bytes=sum(row["length"] for row in rows),
        install_ready=False,
        deployment_accepted=False,
    )
    payload = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    destination.mkdir(parents=False, exist_ok=False)
    for row in rows:
        target = destination / row["relative"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(files[row["relative"]])
        if sha(target.read_bytes()) != row["sha256"]:
            raise ValueError("Frozen source changed after writing; preserve the partial root")
    with (destination / "source-preparation.json").open("xb") as stream:
        stream.write(payload)
    return dict(
        schema="cochem-428-source-preparation-result/1",
        version="4.2.8",
        commit=commit,
        destination=str(destination),
        files=len(rows),
        payload_bytes=manifest["payload_bytes"],
        manifest_sha256=sha(payload),
        install_ready=False,
        deployment_accepted=False,
    )


def freeze_from_git_428(repository: Path, commit: str, destination: Path) -> dict:
    repository = Path(repository).absolute()
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("commit must be a full 40-character Git revision")
    archive = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "archive",
            "--format=tar",
            commit,
            "--",
            *sorted(ROOT_FILES),
            "src",
            "knowledge",
            "docs/4.2.8",
        ],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout
    return freeze_source_428(inspect_archive_428(archive), destination, commit)


def verify_wheel_428(path: Path, source: Path) -> dict:
    """Every packaged 4.2.8 source/asset must match; extra or wrong-version files refuse."""
    source = Path(source)
    expected = {
        p.relative_to(source / "src").as_posix(): p.read_bytes()
        for p in (source / "src").rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.relative_to(source / "src").parts[0].startswith("cochem")
        and len(p.relative_to(source / "src").parts) > 1
        and p.suffix in {".py", ".md", ".json", ".xml", ".typed"}
    }
    actual: dict[str, bytes] = {}
    saw_dist_info = False
    with zipfile.ZipFile(path) as wheel:
        seen: set[str] = set()
        total = 0
        for entry in wheel.infolist():
            name = entry.filename
            parts = PurePosixPath(name).parts
            total += entry.file_size
            if (
                name.casefold() in seen
                or name.startswith("/")
                or "\\" in name
                or any(p in ("", ".", "..") for p in name.split("/"))
                or entry.file_size > 16 * 1024**2
                or total > 128 * 1024**2
            ):
                raise ValueError("Unsafe, duplicate or oversized application wheel entry")
            seen.add(name.casefold())
            if len(parts) > 1 and parts[0].endswith(".dist-info"):
                if parts[0] != DIST_INFO_428:
                    raise ValueError(f"Unexpected wheel package identity: {parts[0]}")
                saw_dist_info = True
                continue
            if not parts or not parts[0].startswith("cochem"):
                raise ValueError("Unexpected application wheel payload")
            actual[name] = wheel.read(entry)
    if not saw_dist_info or not expected or actual != expected:
        raise ValueError("Application wheel does not exactly match frozen 4.2.8 source/assets")
    return dict(
        files=len(actual),
        sha256=sha(Path(path).read_bytes()),
        size=Path(path).stat().st_size,
    )


def build_application_wheel_428(
    freeze: Path,
    backend: Path,
    destination: Path,
    uv: Path,
    python: str,
) -> dict:
    freeze, backend, uv = map(Path, (freeze, backend, uv))
    destination = _assert_fresh_destination(destination)
    manifest = json.loads((freeze / "source-preparation.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "cochem-428-source-preparation/1" or manifest.get("version") != "4.2.8":
        raise ValueError("Build needs a verified 4.2.8 source freeze")
    payload: dict[str, bytes] = {}
    for row in manifest["files"]:
        name = row["relative"]
        validate_name_428(name)
        data = (freeze / name).read_bytes()
        if sha(data) != row["sha256"] or len(data) != row["length"]:
            raise ValueError("Frozen source bytes changed")
        payload[name] = data
    controls = json.loads((backend / "backend-verified.json").read_text(encoding="utf-8"))
    if controls.get("schema") != "cochem-r6-build-backend-preparation/1":
        raise ValueError("Unknown backend preparation")
    for row in controls["files"]:
        if Path(row["filename"]).name != row["filename"]:
            raise ValueError("Invalid backend filename")
        data = (backend / row["filename"]).read_bytes()
        if sha(data) != row["sha256"] or len(data) != row["size"]:
            raise ValueError("Backend wheel changed")
    constraints = backend / "build-constraints.txt"
    if sha(constraints.read_bytes()) != controls["constraints_sha256"]:
        raise ValueError("Backend constraints changed")

    destination.mkdir()
    source = destination / "source"
    source.mkdir()
    for name, data in payload.items():
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("UV_", "PIP_", "PYTHON")) and k != "VIRTUAL_ENV"
    }
    env["SOURCE_DATE_EPOCH"] = "1791763200"
    command = [
        str(uv),
        "--no-config",
        "--no-cache",
        "--offline",
        "build",
        str(source),
        "--wheel",
        "--no-index",
        "--find-links",
        str(backend),
        "--build-constraints",
        str(constraints),
        "--require-hashes",
        "--python",
        str(python),
        "--no-python-downloads",
        "--link-mode",
        "copy",
        "--out-dir",
        str(destination / "dist"),
        "--no-create-gitignore",
    ]
    try:
        with (
            (destination / "build.stdout.log").open("xb") as out,
            (destination / "build.stderr.log").open("xb") as err,
        ):
            subprocess.run(command, check=True, timeout=180, env=env, stdout=out, stderr=err)
        wheels = list((destination / "dist").iterdir())
        if len(wheels) != 1 or wheels[0].name != WHEEL_NAME_428:
            raise ValueError("Build did not produce exactly cochem-4.2.8-py3-none-any.whl")
        result = dict(
            schema="cochem-428-application-wheel/1",
            status="APPLICATION_WHEEL_VERIFIED",
            version="4.2.8",
            source_commit=manifest["commit"],
            source_manifest_sha256=sha((freeze / "source-preparation.json").read_bytes()),
            backend_receipt_sha256=sha((backend / "backend-verified.json").read_bytes()),
            uv_sha256=sha(uv.read_bytes()),
            wheel=str(wheels[0]),
            **verify_wheel_428(wheels[0], freeze),
            application_installed=False,
            deployment_accepted=False,
        )
        (destination / "application-wheel.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        return result
    except Exception as exc:
        (destination / "build-held.json").write_text(
            json.dumps(
                dict(
                    status="HELD_PRESERVE_PARTIAL",
                    error_type=type(exc).__name__,
                    deployment_accepted=False,
                ),
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        raise


def _verify_pyproject_matches_wheelhouse(pyproject_bytes: bytes, wheelhouse_pyproject_sha256: str) -> None:
    if b'version = "4.2.8"' not in pyproject_bytes:
        raise ValueError("pyproject.toml does not declare version = '4.2.8'")
    if sha(pyproject_bytes) == wheelhouse_pyproject_sha256:
        return
    normalized = pyproject_bytes.replace(b'version = "4.2.8"', b'version = "4.2.7"', 1)
    if sha(normalized) != wheelhouse_pyproject_sha256:
        raise ValueError("pyproject.toml dependency definition differs from locked wheelhouse")


def candidate_from_previous_428(
    previous_bytes: bytes,
    *,
    expected_previous_pin: str = PREVIOUS_PIN,
) -> tuple[dict, object]:
    if sha(previous_bytes) != expected_previous_pin:
        raise ValueError("Previously installed R6/R7 configuration differs from expected pin")
    candidate = json.loads(previous_bytes.decode("utf-8"))
    candidate["runtime_version"] = "4.2.8"
    candidate["catalog_activation"] = True
    if "knowledge" in candidate and isinstance(candidate["knowledge"], dict):
        for key in ("source_root", "wiki_root", "manifest_path"):
            if key in candidate["knowledge"] and isinstance(candidate["knowledge"][key], str):
                candidate["knowledge"][key] = candidate["knowledge"][key].replace(
                    OLD_R6_ROOT, TARGET_ROOT_428
                )
        if "state_root" in candidate["knowledge"]:
            candidate["knowledge"]["state_root"] = KNOWLEDGE_STATE_428
    policy = load_routing_policy(candidate["routing"])
    catalog = retire_owner_gemini_pro(policy.as_dict()["catalog"])
    change = compile_change(policy, catalog, expected_policy_digest=policy.digest)
    return candidate, change


def prepare_release_bundle_428(
    freeze: Path,
    wheelhouse: Path,
    application: Path,
    destination: Path,
    repository: Path,
    *,
    previous_config: Path = PREVIOUS,
    expected_previous_pin: str = PREVIOUS_PIN,
) -> dict:
    freeze, wheelhouse, application, repository, previous_config = map(
        Path, (freeze, wheelhouse, application, repository, previous_config)
    )
    destination = _assert_fresh_destination(destination)

    source = json.loads((freeze / "source-preparation.json").read_text(encoding="utf-8"))
    wheels = json.loads((wheelhouse / "wheelhouse-verified.json").read_text(encoding="utf-8"))
    app = json.loads(application.read_text(encoding="utf-8"))

    pyproject_bytes = (freeze / "pyproject.toml").read_bytes()
    lock_bytes = (freeze / "uv.lock").read_bytes()
    if (
        source.get("schema") != "cochem-428-source-preparation/1"
        or source.get("version") != "4.2.8"
        or not re.fullmatch(r"[a-f0-9]{40}", str(source.get("commit", "")))
        or wheels.get("status") != "LOCKED_RUNTIME_WHEELS_VERIFIED"
        or app.get("status") != "APPLICATION_WHEEL_VERIFIED"
        or app.get("version") != "4.2.8"
        or app.get("source_commit") != source["commit"]
        or wheels.get("lock_sha256") != sha(lock_bytes)
        or app.get("source_manifest_sha256") != sha((freeze / "source-preparation.json").read_bytes())
    ):
        raise ValueError("Offline 4.2.8 payloads bind different source or dependency sets")
    _verify_pyproject_matches_wheelhouse(pyproject_bytes, wheels["pyproject_sha256"])

    verified = verify_wheel_428(Path(app["wheel"]), freeze)
    if any(verified[k] != app[k] for k in ("sha256", "size", "files")):
        raise ValueError("Application 4.2.8 wheel changed after build")

    validation_doc = freeze / "docs/4.2.8/VALIDATION.md"
    routing_cand_doc = freeze / "docs/4.2.8/routing-candidate.json"
    if not validation_doc.is_file() or not routing_cand_doc.is_file():
        raise ValueError("Frozen source is missing required 4.2.8 validation or routing candidate artifacts")
    validation_sha = sha(validation_doc.read_bytes())
    routing_cand_bytes = routing_cand_doc.read_bytes()
    routing_cand_sha = sha(routing_cand_bytes)

    previous_bytes = read_regular(previous_config)
    candidate, change = candidate_from_previous_428(
        previous_bytes, expected_previous_pin=expected_previous_pin
    )
    proposal = dict(
        schema="cochem-catalog-change-request/1",
        previous_policy_digest=change.previous_policy_digest,
        catalog=change.policy.as_dict()["catalog"],
    )

    files: list[dict] = []
    requirements: list[str] = []
    seen: set[str] = set()

    def write(name: str, value: bytes | dict) -> bytes:
        raw = (
            value
            if isinstance(value, bytes)
            else (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        )
        with (destination / name).open("xb") as out:
            out.write(raw)
        return raw

    def add(name: str, path: Path, pin: str, size: int) -> None:
        relative(name)
        if name.casefold() in seen:
            raise ValueError(f"Duplicate bundle payload: {name}")
        seen.add(name.casefold())
        read_pinned(path, pin, size)
        files.append(
            dict(
                relative=name,
                source=str(Path(path).absolute()),
                sha256=pin,
                length=size,
            )
        )

    for row in source["files"]:
        add("source/" + row["relative"], freeze / row["relative"], row["sha256"], row["length"])

    for row in wheels["files"]:
        relative(row["filename"])
        if (
            "/" in row["filename"]
            or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", row["name"])
            or not re.fullmatch(r"[A-Za-z0-9.+!-]+", row["version"])
        ):
            raise ValueError("Invalid locked wheel identity")
        add("wheels/" + row["filename"], wheelhouse / row["filename"], row["sha256"], row["size"])
        requirements.append(f"{row['name']}=={row['version']} --hash=sha256:{row['sha256']}")

    add("wheels/" + WHEEL_NAME_428, Path(app["wheel"]), app["sha256"], app["size"])
    requirements.append(f"cochem==4.2.8 --hash=sha256:{app['sha256']}")

    installer_bytes = read_regular(repository / "scripts/install_428_runtime.ps1")
    stage_helper_bytes = read_regular(repository / "scripts/stage_aetherdesk_427_payloads.ps1")

    destination.mkdir()
    try:
        raw_cfg = write("pipeline.json", candidate)
        parsed_cfg = load_config(destination / "pipeline.json")
        alignment = verify_version_alignment(parsed_cfg)
        if parsed_cfg.max_execution_slots != 4 or alignment["status"] != "VERSION_ALIGNMENT_VERIFIED":
            raise ValueError("Parsed 4.2.8 candidate configuration failed slot or version alignment")
        add("pipeline.json", destination / "pipeline.json", sha(raw_cfg), len(raw_cfg))

        raw_req = write("runtime-requirements.txt", ("\n".join(requirements) + "\n").encode("utf-8"))
        add("wheels/runtime-requirements.txt", destination / "runtime-requirements.txt", sha(raw_req), len(raw_req))

        source_test_evidence = dict(
            schema="cochem-428-source-test-evidence/1",
            version="4.2.8",
            source_commit=source["commit"],
            validation_doc_sha256=validation_sha,
            routing_candidate_sha256=routing_cand_sha,
            runner="scripts/run_source_tests_428.py",
        )
        evidence_bytes = write("source-test-evidence.json", source_test_evidence)
        evidence_hash = sha(evidence_bytes)

        manifest = dict(
            schema="cochem-428-install-bundle/1",
            host="AETHERDESK",
            revision=REVISION_428,
            version="4.2.8",
            source_commit=source["commit"],
            source_test_evidence_sha256=evidence_hash,
            files=files,
            activation_ready=False,
        )
        manifest_hash = sha(write("install-manifest.json", manifest))
        proposal_bytes = write("proposal.json", proposal)
        proposal_hash = sha(proposal_bytes)
        pointer = dict(
            schema="cochem-catalog-authority-pointer/1",
            request_id=uuid.uuid4().hex,
            proposal_sha256=proposal_hash,
        )
        write("pointer.json", pointer)
        write("routing-candidate.json", routing_cand_bytes)
        write("install_428_runtime.ps1", installer_bytes)
        write("stage_aetherdesk_427_payloads.ps1", stage_helper_bytes)

        optional_launch_scripts: list[str] = []
        for opt_name in (
            "accept_428_native.py",
            "verify_prior_native_428.py",
            "r6_custody_amendment.py",
            "run_428_launch.ps1",
        ):
            opt_path = repository / "scripts" / opt_name
            if opt_path.is_file():
                write(opt_name, read_regular(opt_path))
                optional_launch_scripts.append(opt_name)

        package_file_names = [
            "install_428_runtime.ps1",
            "stage_aetherdesk_427_payloads.ps1",
            *optional_launch_scripts,
            "pipeline.json",
            "install-manifest.json",
            "source-test-evidence.json",
            "routing-candidate.json",
            "proposal.json",
            "pointer.json",
        ]
        package_files = []
        for name in package_file_names:
            raw_item = (destination / name).read_bytes()
            package_files.append(dict(name=name, sha256=sha(raw_item), length=len(raw_item)))

        launch = dict(
            schema="cochem-428-launch-package/1",
            host="AETHERDESK",
            version="4.2.8",
            revision=REVISION_428,
            files=package_files,
            install_manifest_sha256=manifest_hash,
            candidate_sha256=sha((destination / "pipeline.json").read_bytes()),
            source_test_evidence_sha256=evidence_hash,
            routing_candidate_sha256=routing_cand_sha,
            expected_previous_candidate_sha256=expected_previous_pin,
            proposal_sha256=proposal_hash,
            request_id=pointer["request_id"],
            baseline_policy_digest=change.previous_policy_digest,
            catalog_policy_digest=change.policy.digest,
            stale_recovery_included=False,
            source_commit=source["commit"],
            input_window_minutes=20,
            late_prompts=False,
        )
        launch_pin = sha(write("launch-manifest.json", launch))
        result = dict(
            schema="cochem-428-package-preparation/1",
            status="R428_OFFLINE_PACKAGE_PREPARED",
            version="4.2.8",
            revision=REVISION_428,
            install_manifest_sha256=manifest_hash,
            launch_manifest_sha256=launch_pin,
            source_test_evidence_sha256=evidence_hash,
            routing_candidate_sha256=routing_cand_sha,
            payload_files=len(files),
            source_commit=source["commit"],
            catalog_plan_digest=change.digest,
            stale_recovery_included=False,
            installation_inputs_ready=True,
            administrator_launch_ready=("run_428_launch.ps1" in optional_launch_scripts),
            host_acceptance_executed=False,
            activation_ready=False,
        )
        write("package-prepared.json", result)
        return result
    except Exception as exc:
        try:
            write(
                "package-held.json",
                dict(
                    status="HELD_PRESERVE_PARTIAL",
                    error_type=type(exc).__name__,
                    activation_ready=False,
                ),
            )
        except Exception:
            pass
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("freeze", "build", "bundle", "all"),
        default="bundle",
    )
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--commit")
    parser.add_argument("--freeze", type=Path)
    parser.add_argument(
        "--backend",
        type=Path,
        default=Path(r"C:\Users\ansac\CoChem427\r6-build-backend-20261012-v2"),
    )
    parser.add_argument(
        "--wheelhouse",
        type=Path,
        default=Path(r"C:\Users\ansac\CoChem427\r6-runtime-wheels-20261012-v1"),
    )
    parser.add_argument("--application", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument(
        "--uv",
        type=Path,
        default=Path(r"C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\uv\uv.exe"),
    )
    parser.add_argument(
        "--python",
        default=r"C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe",
    )
    args = parser.parse_args()

    if args.mode == "freeze":
        if not args.commit:
            parser.error("--commit is required for --mode freeze")
        print(json.dumps(freeze_from_git_428(args.repository, args.commit, args.destination), indent=2))
    elif args.mode == "build":
        if not args.freeze:
            parser.error("--freeze is required for --mode build")
        print(
            json.dumps(
                build_application_wheel_428(
                    args.freeze, args.backend, args.destination, args.uv, args.python
                ),
                indent=2,
            )
        )
    elif args.mode == "bundle":
        if not (args.freeze and args.application):
            parser.error("--freeze and --application are required for --mode bundle")
        print(
            json.dumps(
                prepare_release_bundle_428(
                    args.freeze,
                    args.wheelhouse,
                    args.application,
                    args.destination,
                    args.repository,
                ),
                indent=2,
            )
        )
    else:
        ref = args.commit or "HEAD"
        commit = subprocess.run(
            ["git", "-C", str(args.repository), "rev-parse", "--verify", f"{ref}^{{commit}}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.strip()
        short = commit[:7]
        root_parent = args.destination.parent
        freeze_dir = args.freeze or (root_parent / f"r428-source-{short}")
        build_dir = root_parent / f"r428-build-{short}"
        freeze_res = freeze_from_git_428(args.repository, commit, freeze_dir)
        build_res = build_application_wheel_428(
            freeze_dir, args.backend, build_dir, args.uv, args.python
        )
        bundle_res = prepare_release_bundle_428(
            freeze_dir,
            args.wheelhouse,
            build_dir / "application-wheel.json",
            args.destination,
            args.repository,
        )
        print(
            json.dumps(
                dict(
                    freeze=freeze_res,
                    build=build_res,
                    bundle=bundle_res,
                ),
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
