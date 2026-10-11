"""Recover reviewed source candidates from the exact private snapshot into a fresh clone."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

BACKUP = Path(r"C:\Users\ansac\source\repo-backups\Pipeline-Mix-Model-Concurrent-20261009\original-checkout")
DESTINATION = Path(r"C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent")
OUTPUT = Path(__file__).with_name("source-overlay-publication-20261009.json")
PRIVATE_PRESERVATION = BACKUP.parent / "exact-byte-manifest.json"


def listed(arguments: list[str]) -> list[str]:
    completed = subprocess.run(["git", "--no-optional-locks", "-C", str(BACKUP), "ls-files", "-z", *arguments], capture_output=True, check=True)
    return [value.decode("utf-8") for value in completed.stdout.split(b"\0") if value]


if OUTPUT.exists() or not PRIVATE_PRESERVATION.is_file() or not (DESTINATION / ".git").is_dir():
    raise RuntimeError("Require verified private snapshot and fresh clone; do not replay")
snapshot = json.loads(PRIVATE_PRESERVATION.read_text(encoding="utf-8"))["entries"]
tracked_rows = listed(["--stage"])
gitlinks = [row.split("\t", 1)[1] for row in tracked_rows if row.startswith("160000 ")]
tracked = [row.split("\t", 1)[1] for row in tracked_rows if not row.startswith("160000 ")]
untracked = listed(["--others", "--exclude-standard"])
selected = tracked + [item for item in untracked if not item.startswith("build/")]
entries = []
for relative in selected:
    source = BACKUP / relative
    if not source.is_file():
        raise RuntimeError("Tracked deletion requires explicit reconciliation")
    raw = source.read_bytes()
    pin = hashlib.sha256(raw).hexdigest()
    if pin != snapshot[relative]["sha256"]:
        raise RuntimeError("Private snapshot drifted")
    destination = DESTINATION / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != pin:
        raise RuntimeError("Overlay bytes differ")
    entries.append({"path": relative, "bytes": len(raw), "sha256": pin})
document = {"schema": "cochem-source-publication-overlay/1", "tracked_files": len(tracked),
            "unchanged_existing_gitlinks": gitlinks,
            "untracked_candidate_files": len(selected) - len(tracked),
            "excluded_generated_build_files": sum(item.startswith("build/") for item in untracked),
            "destination": str(DESTINATION), "entries": entries,
            "public_safety_review_still_required": True, "original_checkout_changed": False}
with OUTPUT.open("x", encoding="utf-8", newline="\n") as stream:
    json.dump(document, stream, indent=2, sort_keys=True)
    stream.write("\n")
print(json.dumps({key: document[key] for key in ("tracked_files", "untracked_candidate_files", "excluded_generated_build_files", "destination")}))
