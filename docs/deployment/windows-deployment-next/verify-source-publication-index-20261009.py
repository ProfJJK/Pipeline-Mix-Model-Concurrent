"""Check that Git will publish exact source/evidence bytes from the new checkout."""
import json
from pathlib import Path
import subprocess

repo = Path(r"C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent")

def git(*args, input=None):
    return subprocess.run(["git", *args], cwd=repo, input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout

entries = []
gitlinks = []
for row in git("ls-files", "-s", "-z").split(b"\0"):
    if not row:
        continue
    meta, path = row.split(b"\t", 1)
    mode, digest, stage = meta.split()
    assert stage == b"0", "Unmerged Git index"
    record = {"path": path.decode("utf-8"), "git_object": digest.decode("ascii"), "mode": mode.decode("ascii")}
    (gitlinks if mode == b"160000" else entries).append(record)
names = [json.dumps(str(repo / row["path"]).replace("\\", "/"), ensure_ascii=False) for row in entries]
actual = git("hash-object", "--no-filters", "--stdin-paths", input=("\n".join(names) + "\n").encode("utf-8")).decode("ascii").splitlines()
assert len(actual) == len(entries)
for row, digest in zip(entries, actual):
    assert row["git_object"] == digest, row["path"]
tree = git("write-tree").decode("ascii").strip()
report = {"schema": "cochem-exact-publication-index/1", "repository": str(repo), "status": "EXACT_WORKING_BYTES_MATCH_STAGED_GIT_TREE", "regular_files_verified": len(entries), "unchanged_existing_gitlinks": gitlinks, "staged_tree": tree, "files": entries}
target = Path(__file__).with_name("exact-publication-index-20261009.json")
assert not target.exists(), "Preserve existing result"
target.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": report["status"], "regular_files_verified": len(entries), "gitlinks": len(gitlinks), "tree": tree, "receipt": str(target)}, sort_keys=True))
