"""Record exact public continuation bytes and any explicit credential redactions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
ROOT = Path(r"C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\docs\evidence\windows-2026-10-09\continuation")
DESTINATION = ROOT / "continuation-manifest.json"
if DESTINATION.exists():
    raise RuntimeError("Continuation manifest already exists")
copy_report = json.loads((WORKSPACE / "continuation-publication-copy-20261009.json").read_text())
originals = {entry["path"]: entry["original_sha256"] for entry in copy_report["files"]}
entries = []
for path in sorted(ROOT.rglob("*")):
    if not path.is_file():
        continue
    relative = path.relative_to(ROOT).as_posix()
    raw = path.read_bytes()
    pin = hashlib.sha256(raw).hexdigest()
    original = originals.get(relative)
    entry = {"path": relative, "bytes": len(raw), "published_sha256": pin,
             "original_sha256": original, "disposition": "ADDED_PUBLICATION_DOCUMENT" if original is None else "ORIGINAL_BYTES_PRESERVED"}
    if original is not None and original != pin:
        audit = json.loads(path.with_name(path.name + ".redaction-audit.json").read_text())
        if audit["original_sha256"] != original or audit["redacted_sha256"] != pin:
            raise RuntimeError("Unexplained continuation byte change")
        entry["disposition"] = "CREDENTIAL_FRAGMENT_REDACTED_PUBLIC_COPY"
    entries.append(entry)
if set(originals) - {entry["path"] for entry in entries}:
    raise RuntimeError("Continuation source candidate missing")
document = {"schema": "cochem-public-continuation-manifest/1", "files": entries,
            "copied_source_candidate_paths": len(originals), "published_files_excluding_this_manifest": len(entries),
            "original_private_workspace_preserved": True, "production_runtime_changed": False,
            "model_workflows_submitted": 0, "full_srs_acceptance": False,
            "usage": "Frozen historical source and evidence; do not automatically rerun archived setup commands."}
with DESTINATION.open("x", encoding="utf-8", newline="\n") as stream:
    json.dump(document, stream, indent=2, sort_keys=True)
    stream.write("\n")
print(json.dumps({"source_candidate_paths": len(originals), "manifest_pinned_files": len(entries),
                  "changed_public_copies": sum(entry["disposition"] == "CREDENTIAL_FRAGMENT_REDACTED_PUBLIC_COPY" for entry in entries)}))
