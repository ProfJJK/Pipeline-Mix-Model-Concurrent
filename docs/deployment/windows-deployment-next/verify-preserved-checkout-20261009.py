"""Verify a private local copy; do not print file contents or access deployment state."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys


def inventory(root: Path) -> dict[str, dict[str, int | str]]:
    result = {}
    for current, directories, files in os.walk(root, followlinks=False):
        for name in directories:
            directory = Path(current, name)
            if directory.is_symlink() or directory.is_junction():
                raise RuntimeError("Reparse directory requires separate preservation")
        for name in files:
            path = Path(current, name)
            if path.is_symlink():
                raise RuntimeError("Reparse file requires separate preservation")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            result[path.relative_to(root).as_posix()] = {
                "bytes": path.stat().st_size, "sha256": digest.hexdigest()
            }
    return result


source, copied, report = map(Path, sys.argv[1:])
source_entries = inventory(source)
copied_entries = inventory(copied)
if source_entries != copied_entries:
    raise RuntimeError("Private preservation copy differs; preserve every artifact and inspect")
document = {
    "schema": "cochem-private-checkout-preservation/1",
    "status": "ALL_CHECKOUT_FILES_BYTE_VERIFIED",
    "source": str(source), "backup": str(copied),
    "files": len(source_entries),
    "bytes": sum(int(item["bytes"]) for item in source_entries.values()),
    "entries": source_entries,
    "contains_private_local_state": True,
    "publish_this_manifest": False,
}
with report.open("x", encoding="utf-8", newline="\n") as stream:
    json.dump(document, stream, indent=2, sort_keys=True)
    stream.write("\n")
print(json.dumps({"status": document["status"], "files": document["files"], "bytes": document["bytes"]}))
