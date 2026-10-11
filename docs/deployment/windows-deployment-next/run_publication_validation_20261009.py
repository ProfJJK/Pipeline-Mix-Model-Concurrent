"""Canonical Windows fixture validation of the fresh publication checkout.

Only this workspace receives venv, scratch, logs and reports. Child processes
receive an allowlisted environment without provider tokens or credential vars.
This does not run live deployment, providers, model jobs or SYSTEM tasks.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

REPOSITORY = Path(r"C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent")
BASE_PYTHON = Path(r"C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe")
DEPENDENCIES = Path(r"C:\Users\ansac\AppData\Local\CoChem\staging\windows-427-20261006\venv\Lib\site-packages")
RUN_ROOT = Path(__file__).parent / ("publication-validation-20261009-" + uuid.uuid4().hex)


def write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main():
    assert REPOSITORY.is_dir() and BASE_PYTHON.is_file() and DEPENDENCIES.is_dir()
    RUN_ROOT.mkdir()
    scratch = RUN_ROOT / "scratch"
    scratch.mkdir()
    permitted = {"systemroot", "windir", "systemdrive", "comspec", "pathext", "path", "localappdata", "appdata", "userprofile", "homedrive", "homepath", "number_of_processors", "os", "processor_architecture", "processor_identifier", "processor_level", "processor_revision", "programdata", "programfiles", "programfiles(x86)", "commonprogramfiles", "commonprogramfiles(x86)"}
    environment = {key: value for key, value in os.environ.items() if key.casefold() in permitted}
    environment.update(TEMP=str(scratch), TMP=str(scratch), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1")
    venv = RUN_ROOT / "venv"
    create = subprocess.run([str(BASE_PYTHON), "-I", "-m", "venv", "--without-pip", str(venv)], capture_output=True, text=True, env=environment, check=True, timeout=45)
    assert not create.stderr
    python = venv / "Scripts/python.exe"
    source = REPOSITORY / "src"
    dependency_paths = [source, DEPENDENCIES, *(DEPENDENCIES / name for name in ("win32", "win32/lib", "pythonwin"))]
    assert all(path.is_dir() for path in dependency_paths)
    (venv / "Lib/site-packages/publication_source_and_unchanged_dependencies.pth").write_text("\n".join(str(path) for path in dependency_paths) + "\nimport pywin32_bootstrap\n", encoding="utf-8")
    proof_code = """
import importlib, importlib.metadata, json, pathlib, sys, pywintypes
source=pathlib.Path(sys.argv[1]).resolve()
modules={name:str(pathlib.Path(importlib.import_module(name).__file__).resolve()) for name in ('cochem_pipeline','cochem_mcp','cochem_supervisor')}
assert all(pathlib.Path(path).is_relative_to(source) for path in modules.values()), modules
assert sys.flags.isolated == 1
print(json.dumps({'isolated':True,'python':sys.version,'prefix':sys.prefix,'source_modules':modules,'dependencies':{name:importlib.metadata.version(name) for name in ('pytest','psutil','watchdog','pydantic','mcp','fastmcp','numpy')}}))
"""
    proof = subprocess.run([str(python), "-I", "-c", proof_code, str(source)], env=environment, capture_output=True, text=True, check=True, timeout=15)
    assert not proof.stderr
    proof_value = json.loads(proof.stdout)
    write_json(RUN_ROOT / "source-binding-proof.json", proof_value)
    print(json.dumps({"status": "SOURCE_BOUND_CANONICAL_TESTS_STARTING", "run_root": str(RUN_ROOT), "venv": str(venv), "proof": proof_value, "credential_environment_vars_inherited": False}), flush=True)
    report = RUN_ROOT / "publication-canonical-windows-tests.xml"
    arguments = [str(python), "-I", "-m", "pytest", "pipeline_tests", "mcp_tests", "supervisor_tests", "-q", "-p", "no:cacheprovider", "--basetemp=" + str(RUN_ROOT / "pytest-scratch"), "--junitxml=" + str(report)]
    with (RUN_ROOT / "pytest-output-private.txt").open("x", encoding="utf-8", newline="\n") as output:
        result = subprocess.run(arguments, cwd=REPOSITORY, env=environment, stdout=output, stderr=subprocess.STDOUT, text=True, timeout=900)
    counts = {}
    if report.is_file():
        root = ET.parse(report).getroot()
        counts = {name:sum(int(suite.attrib.get(name, "0")) for suite in root.iter("testsuite")) for name in ("tests", "failures", "errors", "skipped")}
    summary = {"schema": "cochem-publication-canonical-windows-validation/1", "exit_code": result.returncode, "repository": str(REPOSITORY), "run_root": str(RUN_ROOT), "venv": str(venv), "source_binding": proof_value, "arguments": arguments, "credential_environment_vars_inherited": False, "native_resource_acceptance_opt_in": False, "provider_model_jobs_started": False, "system_tasks_modified": False, "production_state_modified": False, "counts": counts, "junit_sha256": hashlib.sha256(report.read_bytes()).hexdigest() if report.is_file() else None}
    write_json(RUN_ROOT / "validation-summary.json", summary)
    print(json.dumps(summary), flush=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
