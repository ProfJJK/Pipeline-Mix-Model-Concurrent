"""Freeze the r5 stopped-runtime source: the installed r4 frozen tree plus the 13 reviewed repairs.

Derived from freeze-stopped-runtime-r4-source.py (de679d01...). Read-only against the protected r4
runtime and against the repository. Creates a fresh user-owned staging tree (default
C:\\Users\\ansac\\CoChem427\\stopped-runtime-r5-source) containing the 166 r4 source assets byte-for-byte,
except the 13 files of ARMY_ADDENDUM_20261011 A6, which are taken from ONE named commit of
ProfJJK/Pipeline-Mix-Model-Concurrent with `git show <commit>:<path>` and must equal the sha256 pinned
in the REPAIRS table below. Emits the cochem-stopped-runtime-source/1 manifest that
install-stopped-runtime-r5.ps1 consumes (r4 field names and row shape kept; r5 fields only added) and a
freeze receipt.

Rules (each one refuses; nothing is overwritten and a refusal before staging leaves no output):
- every REPAIRS pin is filled (no 'PIN-AFTER-COMMIT'); use --print-pins --commit <sha> to obtain them;
- the REPAIRS table is exactly the A6 path set with the A6 conventions (agy_protocol.py pure LF, the
  other twelve pure CRLF); README.md, pyproject.toml, uv.lock and src/cochem_pipeline/specification/*
  stay r4 bytes;
- the r4 manifest and the r4 installation receipt match their pins, and every r4 file matches its row;
- each committed blob is a regular file, its bytes equal its git object id, its sha256 equals its pin,
  its line endings are pure and equal the A6 convention (which must also be r4's convention), and it
  differs from the r4 bytes;
- the staged tree differs from r4 in exactly the 13 paths (added [] removed []), verified_unchanged is
  rows - 13 (153 of 166), and the staged bytes are re-verified from disk before the manifest is written.

The manifest is deterministic: captured_utc is the committer timestamp of the source commit, so the
same commit, base and paths always give the same manifest bytes and sha256 (printed in the receipt).

No runtime, task, database, credential, RAM disk or provider state is touched. Exit codes: 0 done,
1 refused (message on stderr), 2 usage error.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

R4_ROOT = Path(r"C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4")
R4_SOURCE = R4_ROOT / "source"
R4_MANIFEST = R4_ROOT / "source-manifest.json"
R4_MANIFEST_SHA256 = "1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189"
R4_INSTALL_RECEIPT = R4_ROOT / "install-after.json"
R4_INSTALL_RECEIPT_SHA256 = "629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502"
CONFIG_SHA256 = "135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c"
REPOSITORY = Path(r"C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent")
STAGE_ROOT = Path(r"C:\Users\ansac\CoChem427\stopped-runtime-r5-source")
TARGET_ROOT = r"C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5"
TARGET_ROOT_PATTERN = re.compile(r"^C:\\Program Files\\CoChem\\Pipeline4\.2\.7-windows-[0-9]{8}-r5$")
WORKSPACE = Path(__file__).resolve().parent
MANIFEST_OUT = WORKSPACE / "stopped-runtime-r5-source-manifest.json"
RECEIPT_OUT = WORKSPACE / "stopped-runtime-r5-freeze-receipt.json"
MANIFEST_SCHEMA = "cochem-stopped-runtime-source/1"
RECEIPT_SCHEMA = "cochem-stopped-runtime-freeze-receipt/2"

PLACEHOLDER = "PIN-AFTER-COMMIT"
# The 13 reviewed repairs of A6: (relative path, committed line-ending convention, sha256 of the
# committed blob). The Commander replaces each PIN-AFTER-COMMIT with the value --print-pins reports
# for the reviewed commit; nothing else in this table may change.
REPAIRS = (
    ("src/cochem_pipeline/__main__.py", "CRLF", "19f24fc7bcd4d6d0133386aff916efc3ceb6fb359d8604041ef17bdab931b1b3"),
    ("src/cochem_pipeline/agy_protocol.py", "LF", "eaf8d1f407c8792be1343c657afabcf370992df3f82cd9dfb7fe13cf9d41545e"),
    ("src/cochem_pipeline/coding.py", "CRLF", "0b97d7bdec4e5c4a1b8f3d1ca8a974f3205d838c6e275e3cc66c5c9826998174"),
    ("src/cochem_pipeline/config.py", "CRLF", "908e61267a6133379fad7b26b7452e03f1deb97f44f53eb9e26c07de8212bbd4"),
    ("src/cochem_pipeline/controller_guard.py", "CRLF", "e18304719af11e0dd5280d777c6157cc9bc873dd29b7dc15527d6b3667656eba"),
    ("src/cochem_pipeline/failures.py", "CRLF", "625f9c6e045f6a108be04a6a13767593db08ac960bb3839fade0a37e36c6edf5"),
    ("src/cochem_pipeline/knowledge.py", "CRLF", "1bf720ed5df342704552b3e0996ee1cdaebd8f9d7f26fc345b4e5a848e2d2f0f"),
    ("src/cochem_pipeline/operator_views.py", "CRLF", "8b6b51e9ef3879ad13f714ee44390fc4bb7e41cc9bf5c7cbdc589413f1efaf42"),
    ("src/cochem_pipeline/runtime.py", "CRLF", "946adaf95b1755138f0e7bf79576c8290569d7fb98851e8962e00ca73b40a208"),
    ("src/cochem_pipeline/service.py", "CRLF", "38ab9dc1853dc38b0ee824a1f80f5e4bea503ec2e821c7803b065baa501c5128"),
    ("src/cochem_pipeline/store.py", "CRLF", "b3604d227b23d2f3a68e0106b852ad672127089df68b0d512131455fa552d0a0"),
    ("src/cochem_pipeline/worker.py", "CRLF", "20a084071bfa172aa787d1a96168b8c541089823559e8f00518b164c16ae0f41"),
    ("src/cochem_supervisor/runner.py", "CRLF", "adc8ccf33841438f3104e64325ff84b7826c49db297c8bc3f02ebb55ad96cf31"),
)
# A6, independent of the table above: the changed set and its per-file convention.
A6_LF_PATHS = frozenset({"src/cochem_pipeline/agy_protocol.py"})
A6_PATHS = frozenset({
    "src/cochem_pipeline/__main__.py", "src/cochem_pipeline/agy_protocol.py", "src/cochem_pipeline/coding.py",
    "src/cochem_pipeline/config.py", "src/cochem_pipeline/controller_guard.py", "src/cochem_pipeline/failures.py",
    "src/cochem_pipeline/knowledge.py", "src/cochem_pipeline/operator_views.py", "src/cochem_pipeline/runtime.py",
    "src/cochem_pipeline/service.py", "src/cochem_pipeline/store.py", "src/cochem_pipeline/worker.py",
    "src/cochem_supervisor/runner.py",
})
PROTECTED_R4_FILES = ("README.md", "pyproject.toml", "uv.lock")
PROTECTED_R4_PREFIXES = ("src/cochem_pipeline/specification/",)
EXPECTED_BASE_ROWS = 166
EXPECTED_CHANGED = 13
ROOT_FILES = ("README.md", "pyproject.toml", "uv.lock")
SHA256_TEXT = re.compile(r"^[0-9a-f]{64}$")
COMMIT_TEXT = re.compile(r"^[0-9a-f]{7,64}$")
RESERVED_SEGMENT = re.compile(r"^(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)")
UNSAFE_CHARACTERS = re.compile(r'[\x00-\x1f<>:"|?*\\]')
REGULAR_BLOB_MODES = (b"100644", b"100755")
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024


class Refusal(Exception):
    """A precondition failed; the freeze stops with a message and exit code 1."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def line_endings(data: bytes) -> str:
    """Classify a file's line endings: LF, CRLF, MIXED, LONE-CR or NONE."""
    crlf = data.count(b"\r\n")
    if data.count(b"\r") != crlf:
        return "LONE-CR"
    lf = data.count(b"\n")
    if lf == 0:
        return "NONE"
    if crlf == 0:
        return "LF"
    return "CRLF" if crlf == lf else "MIXED"


def frozen_convention(data: bytes) -> str:
    """The r4 freeze rule: a file that holds any CRLF is a CRLF file (r4 itself may be mixed)."""
    return "CRLF" if b"\r\n" in data else "LF"


def describe_frozen(data: bytes) -> str:
    kind = line_endings(data)
    return "CRLF (mixed)" if kind == "MIXED" else kind


def eol_counts(data: bytes) -> dict:
    return {"crlf_lines": data.count(b"\r\n"), "lf_lines": data.count(b"\n")}


def safe_relative(relative: object) -> bool:
    """The installer's Get-RuntimeFiles path rule, so every staged row is installable."""
    if not isinstance(relative, str) or not relative or UNSAFE_CHARACTERS.search(relative):
        return False
    for segment in relative.split("/"):
        if segment in ("", ".", "..") or segment.endswith(".") or segment.endswith(" ") or RESERVED_SEGMENT.match(segment):
            return False
    if not relative.startswith("src/") and relative not in ROOT_FILES:
        return False
    if re.search(r"(^|/)(__pycache__|[^/]+\.egg-info)(/|$)|\.pyc$", relative):
        return False
    return True


def protected_r4_bytes(relative: str) -> bool:
    return relative in PROTECTED_R4_FILES or relative.startswith(PROTECTED_R4_PREFIXES)


def check_repairs_table() -> dict:
    """Return {relative: (convention, pin)} or refuse a table that is not exactly A6 with filled pins."""
    table = {}
    for entry in REPAIRS:
        if not isinstance(entry, tuple) or len(entry) != 3:
            raise Refusal("Malformed REPAIRS entry; each row is (relative, convention, sha256)")
        relative, convention, pin = entry
        if relative in table:
            raise Refusal(f"Duplicate REPAIRS path: {relative}")
        if protected_r4_bytes(relative):
            raise Refusal(f"{relative} must stay at r4 bytes; it can never be a reviewed repair")
        table[relative] = (convention, pin)
    if len(table) != EXPECTED_CHANGED or set(table) != A6_PATHS:
        extra = sorted(set(table) - A6_PATHS)
        missing = sorted(A6_PATHS - set(table))
        raise Refusal(f"REPAIRS must be exactly the 13 A6 paths; extra {extra}, missing {missing}")
    for relative, (convention, _pin) in table.items():
        expected = "LF" if relative in A6_LF_PATHS else "CRLF"
        if convention != expected:
            raise Refusal(f"REPAIRS convention for {relative} is {convention}; A6 requires pure {expected}")
    return table


def check_pins_filled(table: dict) -> None:
    unfilled = [relative for relative, (_c, pin) in table.items() if pin == PLACEHOLDER]
    if unfilled:
        raise Refusal(
            f"{len(unfilled)} REPAIRS pin(s) still read {PLACEHOLDER}; run --print-pins --commit <sha> "
            "and embed the reviewed values before freezing")
    for relative, (_c, pin) in table.items():
        if not isinstance(pin, str) or not SHA256_TEXT.fullmatch(pin):
            raise Refusal(f"REPAIRS pin for {relative} is not a lowercase sha256")


class Git:
    """Read-only access to one repository: rev-parse, ls-tree, show and cat-file only."""

    def __init__(self, executable: str, repository: Path):
        self.executable = executable
        self.repository = repository

    def run(self, arguments: list) -> bytes:
        # Ambient GIT_* variables (GIT_DIR, GIT_WORK_TREE, GIT_OBJECT_DIRECTORY, ...) could redirect the
        # read to another object store; they are dropped so --repo alone names the source.
        environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        command = [self.executable, "--no-pager", "--literal-pathspecs", "-C", str(self.repository), *arguments]
        try:
            completed = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                       env=environment, timeout=120, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise Refusal(f"git {arguments[0]} could not run: {error}") from None
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", "replace").strip()[:400]
            raise Refusal(f"git {arguments[0]} failed (exit {completed.returncode}): {detail}")
        return completed.stdout

    def resolve_commit(self, commit: str) -> str:
        full = self.run(["rev-parse", "--verify", "--quiet", commit + "^{commit}"]).decode("ascii", "replace").strip()
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", full) or not full.startswith(commit):
            raise Refusal(f"Commit {commit} does not resolve to one commit")
        return full

    def committer_utc(self, full: str) -> str:
        for line in self.run(["cat-file", "commit", full]).split(b"\n"):
            if not line:
                break
            if line.startswith(b"committer "):
                epoch = int(line.rsplit(b" ", 2)[1])
                return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).isoformat()
        raise Refusal(f"Commit {full} has no committer line")

    def blob(self, full: str, relative: str) -> bytes:
        listing = [item for item in self.run(["ls-tree", "-z", "--full-tree", full, "--", relative]).split(b"\0") if item]
        if not listing:
            raise Refusal(f"{relative} is missing from commit {full}")
        if len(listing) != 1 or b"\t" not in listing[0]:
            raise Refusal(f"{relative} does not name exactly one entry in commit {full}")
        meta, name = listing[0].split(b"\t", 1)
        fields = meta.split(b" ")
        if name.decode("utf-8", "replace") != relative or len(fields) != 3:
            raise Refusal(f"{relative} does not name exactly one entry in commit {full}")
        mode, kind, object_id = fields
        if kind != b"blob" or mode not in REGULAR_BLOB_MODES:
            raise Refusal(f"{relative} in commit {full} is not a regular file blob ({mode.decode()} {kind.decode()})")
        data = self.run(["show", f"{full}:{relative}"])
        header = b"blob " + str(len(data)).encode("ascii") + b"\0"
        algorithm = hashlib.sha256 if len(object_id) == 64 else hashlib.sha1
        if algorithm(header + data).hexdigest().encode("ascii") != object_id:
            raise Refusal(f"git show output for {relative} differs from blob {object_id.decode()}")
        if len(data) > MAX_FILE_BYTES:
            raise Refusal(f"{relative} in commit {full} exceeds 16 MiB")
        return data


def check_repair_blob(relative: str, convention: str, data: bytes) -> None:
    kind = line_endings(data)
    if kind == "MIXED":
        raise Refusal(f"{relative} carries mixed line endings; A6 requires pure {convention}")
    if kind == "LONE-CR":
        raise Refusal(f"{relative} carries a bare carriage return; A6 requires pure {convention}")
    if kind == "NONE":
        raise Refusal(f"{relative} has no line endings; A6 requires pure {convention}")
    if kind != convention:
        raise Refusal(f"{relative} line-ending convention is {kind}; A6 requires pure {convention}")


def read_pinned(path: Path, pin: str, label: str) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as error:
        raise Refusal(f"{label} is unreadable: {error}") from None
    if sha256(data) != pin:
        raise Refusal(f"{label} does not match its pinned digest {pin}")
    return data


def load_base(arguments) -> tuple:
    raw_manifest = read_pinned(Path(arguments.r4_manifest), arguments.r4_manifest_sha256, "r4 source manifest")
    try:
        r4 = json.loads(raw_manifest.decode("utf-8-sig"))
    except ValueError:
        raise Refusal("r4 source manifest is not JSON") from None
    rows = r4.get("files") if isinstance(r4, dict) else None
    if (not isinstance(rows, list) or r4.get("schema") != MANIFEST_SCHEMA or r4.get("complete_source_freeze") is not True
            or len(rows) != EXPECTED_BASE_ROWS):
        raise Refusal(f"Unexpected r4 manifest shape; expected {MANIFEST_SCHEMA} with {EXPECTED_BASE_ROWS} rows")
    seen = set()
    total = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"relative", "sha256", "length"}:
            raise Refusal("r4 manifest row is not {relative, sha256, length}")
        relative = row["relative"]
        if not safe_relative(relative) or relative.lower() in seen:
            raise Refusal(f"Unsafe, unexpected or duplicate r4 manifest path: {relative!r}")
        seen.add(relative.lower())
        if not isinstance(row["sha256"], str) or not SHA256_TEXT.fullmatch(row["sha256"]):
            raise Refusal(f"Invalid r4 manifest sha256 for {relative}")
        if type(row["length"]) is not int or not 0 <= row["length"] <= MAX_FILE_BYTES:
            raise Refusal(f"Invalid r4 manifest length for {relative}")
        total += row["length"]
    if total > MAX_TOTAL_BYTES:
        raise Refusal("r4 source snapshot exceeds 128 MiB")

    raw_receipt = read_pinned(Path(arguments.r4_install_receipt), arguments.r4_install_receipt_sha256, "r4 installation receipt")
    try:
        receipt = json.loads(raw_receipt.decode("utf-8-sig"))
    except ValueError:
        raise Refusal("r4 installation receipt is not JSON") from None
    if (not isinstance(receipt, dict) or receipt.get("mode") != "FRESH_STOPPED_RUNTIME_READY"
            or receipt.get("source_manifest_sha256") != arguments.r4_manifest_sha256
            or receipt.get("source_files") != len(rows) or receipt.get("configuration_sha256") != CONFIG_SHA256
            or receipt.get("configuration_unchanged") is not True):
        raise Refusal("r4 installation receipt does not bind the pinned r4 manifest and configuration")

    base = Path(arguments.r4_source)
    contents = {}
    for row in rows:
        relative = row["relative"]
        source = base.joinpath(*relative.split("/"))
        if source.is_symlink() or not source.is_file():
            raise Refusal(f"Installed r4 frozen source drifted from its manifest: {relative} is not a regular file")
        data = source.read_bytes()
        if sha256(data) != row["sha256"] or len(data) != row["length"]:
            raise Refusal(f"Installed r4 frozen source drifted from its manifest: {relative}")
        contents[relative] = data
    return rows, contents


def check_arguments(arguments) -> None:
    if not COMMIT_TEXT.fullmatch(arguments.commit or ""):
        raise Refusal("--commit must be a lowercase hexadecimal commit id (7-64 characters)")
    for name in ("r4_manifest_sha256", "r4_install_receipt_sha256"):
        if not SHA256_TEXT.fullmatch(getattr(arguments, name)):
            raise Refusal(f"--{name.replace('_', '-')} must be a lowercase sha256")
    if not TARGET_ROOT_PATTERN.fullmatch(arguments.target_root):
        raise Refusal(r"--target-root must be C:\Program Files\CoChem\Pipeline4.2.7-windows-<yyyymmdd>-r5")
    for name in ("output", "manifest_out", "receipt_out"):
        if not Path(getattr(arguments, name)).is_absolute():
            raise Refusal(f"--{name.replace('_', '-')} must be an absolute path")


def inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def print_pins(arguments) -> int:
    if not COMMIT_TEXT.fullmatch(arguments.commit or ""):
        raise Refusal("--commit must be a lowercase hexadecimal commit id (7-64 characters)")
    table = check_repairs_table()
    git = Git(arguments.git, Path(arguments.repo))
    full = git.resolve_commit(arguments.commit)
    lines = []
    failures = []
    for relative, (convention, _pin) in table.items():
        data = git.blob(full, relative)
        try:
            check_repair_blob(relative, convention, data)
        except Refusal as refusal:
            failures.append(str(refusal))
            continue
        lines.append(f"{sha256(data)}  {relative}")
    if failures:
        raise Refusal(f"Commit {full} cannot be pinned:\n" + "\n".join(failures))
    sys.stderr.write(f"commit {full}: 13 blobs pass the A6 line-ending rule\n")
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


def write_new(path: Path, data: bytes) -> None:
    with open(path, "xb") as handle:
        handle.write(data)


def freeze(arguments) -> int:
    table = check_repairs_table()
    check_pins_filled(table)
    check_arguments(arguments)
    stage = Path(arguments.output)
    manifest_out = Path(arguments.manifest_out)
    receipt_out = Path(arguments.receipt_out)
    repository = Path(arguments.repo)
    for path in (manifest_out, receipt_out):
        if path.exists():
            raise Refusal(f"Preserve existing output; refusing to overwrite {path}")
    if stage.exists():
        raise Refusal(f"Preserve existing staging tree; refusing to reuse {stage}")
    if inside(stage, repository) or inside(stage, Path(arguments.r4_source)):
        raise Refusal("The staging tree must lie outside the repository and the r4 frozen tree")

    rows, base = load_base(arguments)
    by_name = {row["relative"]: row for row in rows}
    for relative, (convention, _pin) in table.items():
        if relative not in by_name:
            raise Refusal(f"{relative} is not an r4 source asset; r5 adds no files")
        if frozen_convention(base[relative]) != convention:
            raise Refusal(f"r4 keeps {relative} as {frozen_convention(base[relative])}; A6 says {convention}")

    git = Git(arguments.git, repository)
    full = git.resolve_commit(arguments.commit)
    captured = git.committer_utc(full)
    repaired = {}
    for relative, (convention, pin) in table.items():
        data = git.blob(full, relative)
        if sha256(data) != pin:
            raise Refusal(f"{relative} in commit {full} is {sha256(data)}, not its reviewed pin {pin}")
        check_repair_blob(relative, convention, data)
        if data == base[relative]:
            raise Refusal(f"{relative} in commit {full} equals the r4 bytes; it is not a repair")
        repaired[relative] = data

    staged = {}
    out_rows = []
    for row in rows:
        relative = row["relative"]
        data = repaired.get(relative, base[relative])
        staged[relative] = data
        out_rows.append({"relative": relative, "sha256": sha256(data), "length": len(data)})
    changed = [new["relative"] for new, old in zip(out_rows, rows)
               if new["sha256"] != old["sha256"] or new["length"] != old["length"]]
    added = [row["relative"] for row in out_rows if row["relative"] not in by_name]
    removed = sorted(set(by_name) - {row["relative"] for row in out_rows})
    verified_unchanged = len(out_rows) - len(changed)
    if (set(changed) != set(table) or len(changed) != EXPECTED_CHANGED or added or removed
            or verified_unchanged != EXPECTED_BASE_ROWS - EXPECTED_CHANGED):
        raise Refusal("The r5 freeze must change exactly the 13 reviewed repairs and nothing else")
    for row, old in zip(out_rows, rows):
        if protected_r4_bytes(row["relative"]) and row != old:
            raise Refusal(f"{row['relative']} must stay at r4 bytes")

    stage.mkdir(parents=True, exist_ok=False)
    for relative, data in staged.items():
        destination = stage.joinpath(*relative.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_new(destination, data)
    # Re-verify the staged bytes from disk, and that the tree holds nothing else, before the manifest.
    for row in out_rows:
        data = stage.joinpath(*row["relative"].split("/")).read_bytes()
        if sha256(data) != row["sha256"] or len(data) != row["length"]:
            raise Refusal(f"Staged file does not match its manifest row: {row['relative']}")
    present = {path.relative_to(stage).as_posix() for path in stage.rglob("*") if not path.is_dir()}
    if present != set(staged):
        raise Refusal("The staging tree holds files outside its manifest")

    ordered_repairs = list(changed)  # r4 manifest row order
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "host": "AETHERDESK",
        "captured_utc": captured,
        "complete_source_freeze": True,
        "source_repository": str(stage),
        "target_root": arguments.target_root,
        "previous_source_manifest_sha256": arguments.r4_manifest_sha256,
        "previous_install_receipt_sha256": arguments.r4_install_receipt_sha256,
        "previous_manifest_entries": len(rows),
        "max_execution_slots": 4,
        "worker_identities": 6,
        "configuration_sha256": CONFIG_SHA256,
        "configuration_unchanged": True,
        "scope": (
            "Fresh code-only r5 revision: the installed r4 frozen tree plus the 13 reviewed repairs of "
            "ARMY_ADDENDUM_20261011 A6 (memory budget, chapter WBS, link count, failure diagnostics, Agy "
            "identity policy, reboot-safe daemon options), staged byte-for-byte from one commit with "
            "sha256 pins. README.md, pyproject.toml, uv.lock and src/cochem_pipeline/specification/* stay "
            "r4 bytes. Preserve r4 and all prior runtimes, accepted knowledge state, credentials, budgets, "
            "R drive and tasks. No worker, provisioning, task, database, RAM or daemon execution."
        ),
        "changes_from_previous_source": {"added": added, "removed": removed, "changed": changed},
        "captured_utc_basis": "committer timestamp of source_commit",
        "source_commit": full,
        "verified_unchanged": verified_unchanged,
        "reviewed_repairs": ordered_repairs,
        "reviewed_repairs_sha256": {relative: table[relative][1] for relative in ordered_repairs},
        "files": out_rows,
    }
    encoded = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    write_new(manifest_out, encoded)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "manifest_path": str(manifest_out),
        "manifest_sha256": sha256(encoded),
        "stage_root": str(stage),
        "base_source": str(arguments.r4_source),
        "files": len(out_rows),
        "unchanged_from_r4": verified_unchanged,
        "changed": changed,
        "source_commit": full,
        "repairs": [
            {
                "relative": relative,
                "repository_commit": full,
                "repository_sha256": table[relative][1],
                "staged_sha256": sha256(repaired[relative]),
                "staged_length": len(repaired[relative]),
                "line_endings": table[relative][0],
                "line_ending_counts": eol_counts(repaired[relative]),
                "frozen_tree_line_endings": describe_frozen(base[relative]),
                "frozen_tree_line_ending_counts": eol_counts(base[relative]),
                "r4_sha256": by_name[relative]["sha256"],
            }
            for relative in ordered_repairs
        ],
        "production_runtime_started": False,
        "production_state_opened": False,
    }
    text = json.dumps(receipt, indent=2) + "\n"
    write_new(receipt_out, text.encode("utf-8"))
    sys.stdout.write(text)
    return 0


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description="Freeze the r5 stopped-runtime source (r4 tree + 13 reviewed repairs).")
    parser.add_argument("--commit", required=True, help="reviewed commit of the repository holding the 13 repairs")
    parser.add_argument("--print-pins", action="store_true", help="print the 13 blob sha256 values of --commit and exit")
    parser.add_argument("--repo", default=str(REPOSITORY))
    parser.add_argument("--git", default="git")
    parser.add_argument("--r4-source", default=str(R4_SOURCE))
    parser.add_argument("--r4-manifest", default=str(R4_MANIFEST))
    parser.add_argument("--r4-manifest-sha256", default=R4_MANIFEST_SHA256)
    parser.add_argument("--r4-install-receipt", default=str(R4_INSTALL_RECEIPT))
    parser.add_argument("--r4-install-receipt-sha256", default=R4_INSTALL_RECEIPT_SHA256)
    parser.add_argument("--output", default=str(STAGE_ROOT))
    parser.add_argument("--manifest-out", default=str(MANIFEST_OUT))
    parser.add_argument("--receipt-out", default=str(RECEIPT_OUT))
    parser.add_argument("--target-root", default=TARGET_ROOT)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    arguments = parse_arguments(argv)
    try:
        return print_pins(arguments) if arguments.print_pins else freeze(arguments)
    except Refusal as refusal:
        sys.stderr.write(f"REFUSED: {refusal}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
