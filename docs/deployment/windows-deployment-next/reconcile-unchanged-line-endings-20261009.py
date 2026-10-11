"""Keep real local changes; restore unchanged tracked files from the fresh Git tree."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

BACKUP = Path(r"C:\Users\ansac\source\repo-backups\Pipeline-Mix-Model-Concurrent-20261009\original-checkout")
CLONE = Path(r"C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent")
OUTPUT = Path(__file__).with_name("unchanged-line-ending-reconciliation-20261009.json")


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "--no-optional-locks", "-C", str(root), *args], capture_output=True, check=True).stdout


if OUTPUT.exists():
    raise RuntimeError("Reconciliation already recorded; inspect instead of replaying")
changed = {value.decode("utf-8") for value in git(BACKUP, "diff", "--name-only", "-z", "HEAD").split(b"\0") if value}
if len(changed) != 86:
    raise RuntimeError("Original change inventory differs")
preserved_changes = {relative: (CLONE / relative).read_bytes() for relative in changed}
restored = []
for raw in git(BACKUP, "ls-files", "--stage", "-z").split(b"\0"):
    if not raw:
        continue
    metadata, relative = raw.decode("utf-8").split("\t", 1)
    if metadata.startswith("160000 ") or relative in changed:
        continue
    destination = CLONE / relative
    expected = git(CLONE, "cat-file", "blob", "HEAD:" + relative)
    if destination.read_bytes() != expected:
        destination.write_bytes(expected)
        restored.append(relative)
if any((CLONE / relative).read_bytes() != original for relative, original in preserved_changes.items()):
    raise RuntimeError("A real local change was altered")
with OUTPUT.open("x", encoding="utf-8", newline="\n") as stream:
    json.dump({"schema": "cochem-unchanged-line-ending-reconciliation/1",
               "restored_unchanged_tracked_files": restored,
               "actual_changed_tracked_files_preserved": sorted(changed),
               "original_checkout_or_backup_changed": False}, stream, indent=2, sort_keys=True)
    stream.write("\n")
print(json.dumps({"restored_unchanged_files": len(restored), "actual_local_changes_preserved": len(changed)}))
