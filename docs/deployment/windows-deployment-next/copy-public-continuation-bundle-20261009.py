"""Copy reviewed continuation text/source candidates without caches or runtime data."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil

SOURCE = Path(__file__).resolve().parent
DESTINATION = Path(r"C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\docs\evidence\windows-2026-10-09\continuation")
INVENTORY = SOURCE / "portable-continuation-inventory-20261009.json"
REPORT = SOURCE / "continuation-publication-copy-20261009.json"
EXCLUDE = re.compile(r"^(?:agent-handoff-|prepare-agent-handoff-|publish-agent-handoff-|preserve-and-clone-|verify-preserved-checkout-|overlay-publication-source-|source-overlay-publication-|publication-stage-inventory-|git-config-before-repository-rename-)")

if DESTINATION.exists() or REPORT.exists():
    raise RuntimeError("Publication bundle exists; inspect instead of replaying")
selected = []
excluded = []
inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
for entry in inventory["entries"]:
    relative = entry["path"]
    if EXCLUDE.match(relative):
        excluded.append(relative)
        continue
    source = SOURCE / relative
    raw = source.read_bytes()
    if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise RuntimeError("Reviewed continuation source drifted")
    destination = DESTINATION / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if destination.read_bytes() != raw:
        raise RuntimeError("Copied continuation bytes differ")
    selected.append({"path": relative, "bytes": len(raw), "original_sha256": entry["sha256"]})
for name in ("portable-continuation-audit-20261009.md", "prepare_publication_redactions_20261009.py"):
    raw = (SOURCE / name).read_bytes()
    (DESTINATION / name).write_bytes(raw)
    selected.append({"path": name, "bytes": len(raw), "original_sha256": hashlib.sha256(raw).hexdigest()})
root_wrappers = (
    "check_resume_fresh_identities.ps1", "probe_agy_status.py", "resume_stopped_pipeline.ps1",
    "stage_pipeline_config.ps1", "test_resume_stopped_pipeline.py", "test_stage_pipeline_config.py",
    "test_stopped_verifier_custody.py", "verify_stopped_pipeline.ps1",
)
for name in root_wrappers:
    raw = (SOURCE.parent / name).read_bytes()
    destination = DESTINATION / "owner-wrappers" / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    selected.append({"path": "owner-wrappers/" + name, "bytes": len(raw), "original_sha256": hashlib.sha256(raw).hexdigest()})
with REPORT.open("x", encoding="utf-8", newline="\n") as stream:
    json.dump({"schema": "cochem-public-continuation-copy/1", "files": selected,
               "excluded_publication_scratch": excluded, "original_workspace_changed": False,
               "historical_report_redactions_still_required": True}, stream, indent=2, sort_keys=True)
    stream.write("\n")
print(json.dumps({"copied_continuation_files": len(selected), "excluded_publication_scratch": len(excluded),
                  "destination": str(DESTINATION)}))
