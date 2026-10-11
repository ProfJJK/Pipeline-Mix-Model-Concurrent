"""Preserve publication test metadata; never operate production state."""
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


repo = Path(r"C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent")
stage = Path(__file__).parent
backup = Path(r"C:\Users\ansac\source\repo-backups\Pipeline-Mix-Model-Concurrent-20261009\original-checkout")
destination = repo / "docs/evidence/windows-2026-10-09/source-publication"
assert not destination.exists(), "Preserve existing publication evidence; do not overwrite."
focused = Path(r"C:\Users\ansac\Documents\Codex\pubval-5afd58b5208d")
canonical = stage / "publication-validation-20261009-4723f9a40a664b9a943e7c6d80b0a8f2"
source_paths = load(stage / "unchanged-line-ending-reconciliation-20261009.json")["actual_changed_tracked_files_preserved"]
assert len(source_paths) == 86
source_proof = []
for relative in source_paths:
    original, published = backup / relative, repo / relative
    assert sha(original) == sha(published), relative
    source_proof.append({"path": relative, "sha256": sha(published), "bytes": published.stat().st_size})
module_pin = sha(repo / "src/cochem_pipeline/resource_telemetry.py")
assert module_pin == "ad5ada81f1cc3ff683d4e43c706383594a4ab256dd1f3d62675f6a8a2f4d0e8a"
manifest_path = repo / "docs/evidence/windows-2026-10-09/continuation/continuation-manifest.json"
manifest = load(manifest_path)
assert sha(manifest_path) == "0fd58229e1621b6288ce0ed18723aea8566d5eb63a4298437799d3d6b17b8236"
for entry in manifest["files"]:
    assert sha(manifest_path.parent / entry["path"]) == entry["published_sha256"], entry["path"]
summary = load(focused / "validation-summary.json")
assert summary["counts"] == {"errors": 0, "failures": 0, "skipped": 91, "tests": 1902}
assert summary["exit_code"] == 0
junit = focused / "publication-focused-windows-tests.xml"
assert sha(junit) == "98692b11be1788e13050af0e2736038b103b5e77674609ef90854db7fd38fefe"
suite = ET.parse(junit).getroot()
assert sum(int(x.attrib.get("failures", 0)) for x in suite.findall("testsuite")) == 0
destination.mkdir(parents=True)
artifact_rows = []
for source, name in (
    (junit, "publication-focused-windows-tests.xml"),
    (focused / "validation-summary.json", "focused-validation-summary.json"),
    (focused / "source-binding-proof.json", "source-binding-proof.json"),
    (canonical / "validation-summary.json", "incomplete-canonical-validation-summary.json"),
):
    target = destination / name
    shutil.copyfile(source, target)
    assert sha(source) == sha(target)
    artifact_rows.append({"path": name, "bytes": target.stat().st_size, "sha256": sha(target)})
source_proof_path = destination / "preserved-modified-source.json"
source_proof_path.write_text(json.dumps({"schema": "cochem-preserved-modified-source/1", "files": source_proof}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
artifact_rows.append({"path": source_proof_path.name, "bytes": source_proof_path.stat().st_size, "sha256": sha(source_proof_path)})
report = {
    "schema": "cochem-source-publication-windows-validation/1",
    "date": "2026-10-09",
    "platform": "Windows AETHERDESK, actual workstation execution",
    "repository": str(repo),
    "remote": "https://github.com/ProfJJK/Pipeline-Mix-Model-Concurrent.git",
    "branch": "master",
    "focused_regression": {"selected_test_files": 57, "passed": 1811, "skipped": 91, "failed": 0, "errors": 0, "tests": 1902, "seconds": 100.58, "exit_code": 0, "source_binding": summary["source_binding"]},
    "canonical_full_suite": {
        "status": "INCOMPLETE",
        "exit_code": 124,
        "complete_results_available": False,
        "stalled_fixture": "pipeline_tests/test_service.py::test_actual_pipeline_mcp_session_creates_and_cancels_real_dag",
        "earlier_failure_markers_observed": True,
        "notes": "No full-suite success is claimed. Only the owned test harness and its verified direct pytest child were stopped; production processes were preserved. Focused regression excludes the stalled MCP integration fixture."
    },
    "preservation": {"exact_original_modified_files": 86, "continuation_manifest_files_verified": len(manifest["files"]), "continuation_manifest_sha256": sha(manifest_path), "resource_telemetry_module_sha256": module_pin, "telemetry_leak_repair_implemented": False, "complete_private_checkout_backup_verified": True, "all_local_git_history_bundle_verified": True},
    "scope": {"linux_results_used": False, "system_acceptance_opt_ins_enabled": False, "provider_model_jobs_executed": False, "production_tasks_modified": False, "production_runtime_changed": False, "credentials_modified": False, "databases_modified": False, "repair_budgets_modified": False, "ram_drive_modified": False, "full_srs_acceptance": False},
    "artifacts": artifact_rows,
    "interpretation": "Source publication validation only. Skipped protected Windows/Docker/symlink/POSIX checks are not acceptance passes. The installed r3 pipeline, running observers and remaining deployment holds are unchanged."
}
(destination / "validation.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps({"status": "PUBLICATION_EVIDENCE_READY", "files": len(artifact_rows) + 1, "passed": 1811, "skipped": 91, "continuation_files_verified": len(manifest["files"]), "modified_source_files_byte_verified": len(source_proof), "destination": str(destination)}, sort_keys=True))
