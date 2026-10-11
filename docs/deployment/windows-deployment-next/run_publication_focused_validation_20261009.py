"""Bounded source-bound publication fixtures with short Windows scratch paths."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

HERE = Path(__file__).parent
REPOSITORY = Path(r"C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent")
VENV = HERE / "publication-validation-20261009-4723f9a40a664b9a943e7c6d80b0a8f2/venv"
RUN_ROOT = Path(r"C:\Users\ansac\Documents\Codex") / ("pubval-" + uuid.uuid4().hex[:12])
PIPELINE = (
    "config", "routing_policy", "routing_store", "runtime_routing", "route_preview",
    "knowledge", "knowledge_private_directories", "runtime_knowledge_authority",
    "cpu_temperature_probe", "resource_telemetry", "resource_limits", "controller_guard", "hardware_guard",
    "ramdisk", "ramdisk_adopted_subtree", "store", "lease_invariants", "worker_contract", "queue_launch",
    "runtime_monitor", "runtime_storage_holds", "native_effort", "native_evidence", "native_output_bounds",
    "inference_policy", "worker_inference_policy", "operations_policy", "document_governance",
    "windows_contract", "windows_setup_contracts", "windows_stopped_install_guard",
    "windows_payload_staging", "windows_native_payload_staging", "provider_failures", "provider_integration",
)
MCP = ("config", "router", "providers", "claude_subscription", "jobs")
SUPERVISOR = (
    "config", "state", "budget_upgrade", "legacy_budget_authority", "replay_budget",
    "task_control_policy", "heartbeat", "held_observation", "cleanup_reconciliation",
    "reconciliation", "monitor", "probes", "component_recovery", "process_observer",
    "repair_resources", "repair_job_board", "routing_upgrade",
)


def write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main():
    RUN_ROOT.mkdir()
    scratch = RUN_ROOT / "scratch"
    scratch.mkdir()
    permitted = {"systemroot", "windir", "systemdrive", "comspec", "pathext", "path", "localappdata", "appdata", "userprofile", "homedrive", "homepath", "number_of_processors", "os", "processor_architecture", "processor_identifier", "processor_level", "processor_revision", "programdata", "programfiles", "programfiles(x86)", "commonprogramfiles", "commonprogramfiles(x86)"}
    environment = {key: value for key, value in os.environ.items() if key.casefold() in permitted}
    environment.update(TEMP=str(scratch), TMP=str(scratch), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1", COCHEM_PUBLICATION_EVENTS=str(RUN_ROOT / "case-events-private.jsonl"))
    python = VENV / "Scripts/python.exe"
    plugin_binding = VENV / "Lib/site-packages/publication_events_root.pth"
    if plugin_binding.exists():
        assert plugin_binding.read_text(encoding="utf-8") == str(HERE) + "\n"
    else:
        with plugin_binding.open("x", encoding="utf-8") as stream:
            stream.write(str(HERE) + "\n")
    proof_code = "import importlib,json,pathlib,sys; source=pathlib.Path(sys.argv[1]).resolve(); modules={n:str(pathlib.Path(importlib.import_module(n).__file__).resolve()) for n in ('cochem_pipeline','cochem_mcp','cochem_supervisor')}; assert all(pathlib.Path(p).is_relative_to(source) for p in modules.values()); print(json.dumps({'isolated':bool(sys.flags.isolated),'source_modules':modules,'python':sys.version}))"
    proof = subprocess.run([str(python), "-I", "-c", proof_code, str(REPOSITORY / "src")], env=environment, capture_output=True, text=True, check=True, timeout=15)
    assert not proof.stderr
    binding = json.loads(proof.stdout)
    write_json(RUN_ROOT / "source-binding-proof.json", binding)
    targets = [*("pipeline_tests/test_" + item + ".py" for item in PIPELINE), *("mcp_tests/test_" + item + ".py" for item in MCP), *("supervisor_tests/test_" + item + ".py" for item in SUPERVISOR)]
    if len(sys.argv) > 1:
        targets = sys.argv[1:]
        assert all(target.startswith(("pipeline_tests/", "mcp_tests/", "supervisor_tests/")) and ".." not in target for target in targets)
    assert all((REPOSITORY / target.split("::", 1)[0]).is_file() for target in targets)
    report = RUN_ROOT / "publication-focused-windows-tests.xml"
    args = [str(python), "-I", "-m", "pytest", *targets, "-q", "--tb=short", "-p", "no:cacheprovider", "-p", "publication_pytest_events_20261009", "--basetemp=" + str(RUN_ROOT / "tests"), "--junitxml=" + str(report)]
    print(json.dumps({"status": "BOUNDED_FOCUSED_VALIDATION_STARTED", "run_root": str(RUN_ROOT), "files_selected": len(targets), "source_binding": binding}), flush=True)
    with (RUN_ROOT / "pytest-output-private.txt").open("x", encoding="utf-8") as output:
        process = subprocess.Popen(args, cwd=REPOSITORY, env=environment, stdout=output, stderr=subprocess.STDOUT, text=True)
        write_json(RUN_ROOT / "owned-test-launch.json", {"pid": process.pid, "arguments": args})
        bounded = False
        try:
            status = process.wait(timeout=240)
        except subprocess.TimeoutExpired:
            bounded = True
            process.kill()
            status = process.wait(timeout=10)
    counts = {}
    if report.is_file():
        root = ET.parse(report).getroot()
        counts = {name:sum(int(suite.attrib.get(name, "0")) for suite in root.iter("testsuite")) for name in ("tests", "failures", "errors", "skipped")}
    summary = {"schema": "cochem-publication-focused-windows-validation/1", "exit_code": status, "bounded_timeout": bounded, "source_binding": binding, "counts": counts, "run_root": str(RUN_ROOT), "arguments": args, "junit_sha256": hashlib.sha256(report.read_bytes()).hexdigest() if report.is_file() else None, "credential_environment_vars_inherited": False, "native_resource_acceptance_opt_in": False, "provider_model_jobs_started": False, "system_tasks_modified": False, "production_state_modified": False}
    write_json(RUN_ROOT / "validation-summary.json", summary)
    print(json.dumps(summary), flush=True)
    raise SystemExit(status if not bounded else 124)


if __name__ == "__main__":
    main()
