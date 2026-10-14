"""Tests for `P428-25`: Offline source, application and installation freeze (`prepare_428_release.py`, `install_428_runtime.ps1`)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
spec = importlib.util.spec_from_file_location("prepare_428_release", SCRIPTS / "prepare_428_release.py")
release_428 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(release_428)


@pytest.mark.parametrize(
    "mutation",
    ["", "changed", "extra", "duplicate", "escape", "missing", "wrong_version"],
)
def test_wheel_428_must_preserve_exact_source_assets_and_428_dist_info(tmp_path: Path, mutation: str) -> None:
    source = tmp_path / "src/cochem_pipeline"
    source.mkdir(parents=True)
    (source / "__init__.py").write_bytes(b"__version__ = '4.2.8'\n")
    (source / "policy.json").write_bytes(b"{}")
    wheel = tmp_path / "cochem-4.2.8-py3-none-any.whl"
    dist_info = "cochem-4.2.7.dist-info" if mutation == "wrong_version" else "cochem-4.2.8.dist-info"
    with zipfile.ZipFile(wheel, "w") as out:
        out.writestr(
            "cochem_pipeline/__init__.py",
            b"changed" if mutation == "changed" else b"__version__ = '4.2.8'\n",
        )
        if mutation != "missing":
            out.writestr("cochem_pipeline/policy.json", b"{}")
        out.writestr(f"{dist_info}/METADATA", b"Name: cochem\nVersion: 4.2.8\n")
        if mutation == "extra":
            out.writestr("cochem_pipeline/extra.py", b"")
        if mutation == "duplicate":
            out.writestr("COCHEM_PIPELINE/POLICY.JSON", b"{}")
        if mutation == "escape":
            out.writestr("../escape.py", b"")
    if mutation:
        with pytest.raises(ValueError):
            release_428.verify_wheel_428(wheel, tmp_path)
    else:
        verified = release_428.verify_wheel_428(wheel, tmp_path)
        assert verified["files"] == 2


def _make_bundle_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    freeze = tmp_path / "freeze"
    wheels = tmp_path / "wheels"
    dest = tmp_path / "bundle"
    freeze.mkdir()
    wheels.mkdir()

    files_map = {
        "README.md": b"# CoChem 4.2.8\n",
        "pyproject.toml": b'[project]\nname = "cochem"\nversion = "4.2.8"\n',
        "uv.lock": b"version = 1\n",
        "src/cochem_pipeline/__main__.py": b"print('4.2.8')\n",
        "src/cochem_pipeline/specification/routing_catalog_v3.json": b"{}\n",
        "knowledge/v4.1.2_manifest.json": b"{}\n",
        "docs/4.2.8/routing-candidate.json": (ROOT / "docs/4.2.8/routing-candidate.json").read_bytes(),
        "docs/4.2.8/routing-decision-packet.json": (ROOT / "docs/4.2.8/routing-decision-packet.json").read_bytes(),
        "docs/4.2.8/VALIDATION.md": (ROOT / "docs/4.2.8/VALIDATION.md").read_bytes(),
    }
    source_rows = []
    for rel_name, data in sorted(files_map.items()):
        target = freeze / rel_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        source_rows.append(dict(relative=rel_name, sha256=release_428.sha(data), length=len(data)))

    source_manifest = dict(
        schema="cochem-428-source-preparation/1",
        version="4.2.8",
        commit="a" * 40,
        files=source_rows,
        payload_bytes=sum(r["length"] for r in source_rows),
    )
    (freeze / "source-preparation.json").write_text(json.dumps(source_manifest), encoding="utf-8")

    dep_wheel = wheels / "fixture-1.0-py3-none-any.whl"
    dep_wheel.write_bytes(b"dependency-wheel")
    (wheels / "wheelhouse-verified.json").write_text(
        json.dumps(
            dict(
                status="LOCKED_RUNTIME_WHEELS_VERIFIED",
                lock_sha256=release_428.sha(files_map["uv.lock"]),
                pyproject_sha256=release_428.sha(files_map["pyproject.toml"]),
                files=[
                    dict(
                        name="fixture",
                        version="1.0",
                        filename=dep_wheel.name,
                        sha256=release_428.sha(dep_wheel.read_bytes()),
                        size=dep_wheel.stat().st_size,
                    )
                ],
            )
        ),
        encoding="utf-8",
    )

    app_wheel = tmp_path / "cochem-4.2.8-py3-none-any.whl"
    with zipfile.ZipFile(app_wheel, "w") as zf:
        zf.writestr("cochem_pipeline/__main__.py", files_map["src/cochem_pipeline/__main__.py"])
        zf.writestr(
            "cochem_pipeline/specification/routing_catalog_v3.json",
            files_map["src/cochem_pipeline/specification/routing_catalog_v3.json"],
        )
        zf.writestr("cochem-4.2.8.dist-info/METADATA", b"Name: cochem\nVersion: 4.2.8\n")
    app_record = dict(
        schema="cochem-428-application-wheel/1",
        status="APPLICATION_WHEEL_VERIFIED",
        version="4.2.8",
        source_commit="a" * 40,
        source_manifest_sha256=release_428.sha((freeze / "source-preparation.json").read_bytes()),
        wheel=str(app_wheel),
        sha256=release_428.sha(app_wheel.read_bytes()),
        size=app_wheel.stat().st_size,
        files=2,
    )
    app_json = tmp_path / "application-wheel.json"
    app_json.write_text(json.dumps(app_record), encoding="utf-8")

    prev_cfg = tmp_path / "prev-pipeline.json"
    prev_bytes = b'{"runtime_version":"4.2.7","routing":{"policy_version":3}}'
    prev_cfg.write_bytes(prev_bytes)
    prev_pin = release_428.sha(prev_bytes)

    fake_change = SimpleNamespace(
        previous_policy_digest="b" * 64,
        policy=SimpleNamespace(
            as_dict=lambda: {"catalog": {"models": []}},
            digest="c" * 64,
        ),
        digest="d" * 64,
    )
    monkeypatch.setattr(
        release_428,
        "candidate_from_previous_428",
        lambda raw, *, expected_previous_pin=prev_pin: (
            release_428.sha(raw) == expected_previous_pin
            or (_ for _ in ()).throw(ValueError("Previous pin mismatch"))
        )
        and ({"runtime_version": "4.2.8", "max_execution_slots": 4}, fake_change),
    )
    monkeypatch.setattr(
        release_428,
        "load_config",
        lambda _: SimpleNamespace(max_execution_slots=4, runtime_version="4.2.8"),
    )
    monkeypatch.setattr(
        release_428,
        "verify_version_alignment",
        lambda _: {"status": "VERSION_ALIGNMENT_VERIFIED", "version": "4.2.8"},
    )
    return dict(
        freeze=freeze,
        wheelhouse=wheels,
        application=app_json,
        destination=dest,
        repository=ROOT,
        previous_config=prev_cfg,
        expected_previous_pin=prev_pin,
    )


@pytest.mark.parametrize(
    "mutation",
    ["source", "wheel", "commit", "lock", "missing_validation", "previous_pin"],
)
def test_tampered_or_missing_offline_inputs_refuse_bundle_428(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    args = _make_bundle_fixture(tmp_path, monkeypatch)
    if mutation == "source":
        (args["freeze"] / "README.md").write_bytes(b"tampered")
    elif mutation == "wheel":
        next(args["wheelhouse"].glob("*.whl")).write_bytes(b"tampered")
    elif mutation == "commit":
        row = json.loads(args["application"].read_text(encoding="utf-8"))
        row["source_commit"] = "f" * 40
        args["application"].write_text(json.dumps(row), encoding="utf-8")
    elif mutation == "lock":
        (args["freeze"] / "uv.lock").write_bytes(b"tampered-lock")
    elif mutation == "missing_validation":
        (args["freeze"] / "docs/4.2.8/VALIDATION.md").unlink()
    elif mutation == "previous_pin":
        args["previous_config"].write_bytes(b'{"tampered":true}')
    with pytest.raises(ValueError):
        release_428.prepare_release_bundle_428(**args)


def test_real_offline_application_build_and_read_only_installer_plan_428(tmp_path: Path) -> None:
    backend = Path(r"C:\Users\ansac\CoChem427\r6-build-backend-20261012-v2")
    wheelhouse = Path(r"C:\Users\ansac\CoChem427\r6-runtime-wheels-20261012-v1")
    uv = Path(r"C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\uv\uv.exe")
    python_exe = Path(r"C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe")
    ps51 = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")

    commit = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()

    freeze_dir = tmp_path / "freeze428"
    build_dir = tmp_path / "build428"
    bundle_dir = tmp_path / "bundle428"

    freeze_res = release_428.freeze_from_git_428(ROOT, commit, freeze_dir)
    assert freeze_res["version"] == "4.2.8"
    assert freeze_res["commit"] == commit

    build_res = release_428.build_application_wheel_428(
        freeze_dir, backend, build_dir, uv, str(python_exe)
    )
    assert build_res["status"] == "APPLICATION_WHEEL_VERIFIED"
    assert build_res["version"] == "4.2.8"
    assert Path(build_res["wheel"]).name == "cochem-4.2.8-py3-none-any.whl"

    bundle_res = release_428.prepare_release_bundle_428(
        freeze_dir,
        wheelhouse,
        build_dir / "application-wheel.json",
        bundle_dir,
        ROOT,
    )
    assert bundle_res["status"] == "R428_OFFLINE_PACKAGE_PREPARED"
    assert bundle_res["version"] == "4.2.8"
    assert bundle_res["stale_recovery_included"] is False
    assert bundle_res["host_acceptance_executed"] is False
    assert bundle_res["activation_ready"] is False
    assert not (bundle_dir / "r6-prerequisite").exists()

    reqs = (bundle_dir / "runtime-requirements.txt").read_text(encoding="utf-8")
    assert f"cochem==4.2.8 --hash=sha256:{build_res['sha256']}" in reqs

    # Execute packaged install_428_runtime.ps1 in read-only mode (-Apply omitted)
    proc = subprocess.run(
        [
            str(ps51),
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(bundle_dir / "install_428_runtime.ps1"),
            "-Manifest",
            str(bundle_dir / "install-manifest.json"),
            "-ManifestSha256",
            bundle_res["install_manifest_sha256"],
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"STDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    plan = json.loads(proc.stdout)
    assert plan["schema"] == "cochem-428-offline-install/1"
    assert plan["status"] == "READ_ONLY_PLAN"
    assert plan["version"] == "4.2.8"
    assert plan["revision"] == "windows-20261014-428-v1"
    assert plan["source_commit"] == commit
    assert plan["files"] == bundle_res["payload_files"]
    assert plan["activation_ready"] is False
    assert not Path(plan["target_root"]).exists()
