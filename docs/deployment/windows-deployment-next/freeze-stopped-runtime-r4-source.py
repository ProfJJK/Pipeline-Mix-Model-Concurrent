"""Freeze the r4 stopped-runtime source: the installed r3 frozen tree plus one reviewed repair.

Read-only against the protected r3 runtime. Creates a fresh user-owned staging tree under
C:\\Users\\ansac\\CoChem427 containing the 166 r3 source assets byte-for-byte, except
src/cochem_pipeline/resource_telemetry.py, which carries the reviewed Warden telemetry
leak repair (commit 5d592f9 in ProfJJK/Pipeline-Mix-Model-Concurrent) staged byte-for-byte
(both trees keep that file in CRLF). Emits the cochem-stopped-runtime-source/1 manifest the
install-stopped-runtime-r4.ps1 installer consumes, and a freeze receipt.

No runtime, task, database, credential, RAM disk or provider state is touched.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import shutil
import sys
from pathlib import Path

R3_ROOT = Path(r"C:\Program Files\CoChem\Pipeline4.2.7-windows-20261007-r3")
R3_SOURCE = R3_ROOT / "source"
R3_MANIFEST = R3_ROOT / "source-manifest.json"
R3_MANIFEST_SHA256 = "6c33a1434df2e5c3c32697bda5f828fe010f366550beeedde65636de982bbcd1"
R3_INSTALL_RECEIPT_SHA256 = "3b613128192ac44a0a3d9c4b4476fb4c47541edb7563541b9bbf18f84f9a90f6"
CONFIG_SHA256 = "135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c"
REPAIR_RELATIVE = "src/cochem_pipeline/resource_telemetry.py"
REPAIR_SOURCE = Path(r"C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent") / REPAIR_RELATIVE
REPAIR_SOURCE_SHA256 = "e140f8048e2d82b2c1accdfbd8c5d67c1e434b5058e2141b5028c31f0a802afc"
STAGE_ROOT = Path(r"C:\Users\ansac\CoChem427\stopped-runtime-r4-source")
TARGET_ROOT = r"C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4"
WORKSPACE = Path(__file__).resolve().parent
MANIFEST_OUT = WORKSPACE / "stopped-runtime-r4-source-manifest.json"
RECEIPT_OUT = WORKSPACE / "stopped-runtime-r4-freeze-receipt.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    for path in (MANIFEST_OUT, RECEIPT_OUT):
        if path.exists():
            raise SystemExit(f"Preserve existing output; refusing to overwrite {path}")
    if STAGE_ROOT.exists():
        raise SystemExit(f"Preserve existing staging tree; refusing to reuse {STAGE_ROOT}")
    raw_manifest = R3_MANIFEST.read_bytes()
    if sha256(raw_manifest) != R3_MANIFEST_SHA256:
        raise SystemExit("Installed r3 source manifest does not match its pinned digest")
    r3 = json.loads(raw_manifest.decode("utf-8-sig"))
    if r3["schema"] != "cochem-stopped-runtime-source/1" or len(r3["files"]) != 166:
        raise SystemExit("Unexpected r3 manifest shape")
    repaired = REPAIR_SOURCE.read_bytes()
    if sha256(repaired) != REPAIR_SOURCE_SHA256:
        raise SystemExit("Reviewed repair source changed since the committed revision 5d592f9")
    frozen_original = (R3_SOURCE / REPAIR_RELATIVE).read_bytes()
    uses_crlf = b"\r\n" in frozen_original
    # The frozen r3 tree and the repository both keep this file in CRLF; the repair is
    # staged byte-for-byte, so its digest equals the committed repository digest.
    if (b"\r\n" in repaired) != uses_crlf:
        raise SystemExit("Repair line-ending convention differs from the frozen r3 file; refusing to stage")
    if uses_crlf and repaired.count(b"\r\n") != repaired.count(b"\n"):
        raise SystemExit("Repair carries mixed line endings; refusing to stage")
    # Record both files' line-ending counts so a reviewer can separate EOL normalisation
    # from the semantic repair in the raw byte diff (the r3 file itself is mixed).
    eol_counts = {
        "r3_crlf_lines": frozen_original.count(b"\r\n"), "r3_lf_lines": frozen_original.count(b"\n"),
        "repair_crlf_lines": repaired.count(b"\r\n"), "repair_lf_lines": repaired.count(b"\n"),
    }

    STAGE_ROOT.mkdir(parents=True, exist_ok=False)
    rows = []
    changed = []
    verified_unchanged = 0
    for row in r3["files"]:
        relative = row["relative"]
        source = R3_SOURCE / relative
        data = source.read_bytes()
        if sha256(data) != row["sha256"] or len(data) != row["length"]:
            raise SystemExit(f"Installed r3 frozen source drifted from its manifest: {relative}")
        destination = STAGE_ROOT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if relative == REPAIR_RELATIVE:
            destination.write_bytes(repaired)
            changed.append(relative)
            rows.append({"relative": relative, "sha256": sha256(repaired), "length": len(repaired)})
        else:
            shutil.copyfile(source, destination)
            verified_unchanged += 1
            rows.append({"relative": relative, "sha256": row["sha256"], "length": row["length"]})
    if changed != [REPAIR_RELATIVE] or verified_unchanged != 165:
        raise SystemExit("The r4 freeze must change exactly the reviewed telemetry file")
    # Re-verify the staged bytes from disk before publishing the manifest.
    for row in rows:
        data = (STAGE_ROOT / row["relative"]).read_bytes()
        if sha256(data) != row["sha256"] or len(data) != row["length"]:
            raise SystemExit(f"Staged file does not match its manifest row: {row['relative']}")

    manifest = {
        "schema": "cochem-stopped-runtime-source/1",
        "host": "AETHERDESK",
        "captured_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "complete_source_freeze": True,
        "source_repository": str(STAGE_ROOT),
        "target_root": TARGET_ROOT,
        "previous_source_manifest_sha256": R3_MANIFEST_SHA256,
        "previous_install_receipt_sha256": R3_INSTALL_RECEIPT_SHA256,
        "previous_manifest_entries": 166,
        "max_execution_slots": 4,
        "worker_identities": 6,
        "configuration_sha256": CONFIG_SHA256,
        "configuration_unchanged": True,
        "scope": (
            "Fresh code-only r4 revision with the reviewed Warden telemetry leak repair "
            "(module-scope PERFORMANCE_INFORMATION, cached GetPerformanceInfo binding). "
            "Preserve r3 and all prior runtimes, accepted knowledge state, failed worker task/receipt, "
            "credentials, budgets, R drive and startup task. No worker, provisioning, task, database, "
            "RAM or daemon execution."
        ),
        "changes_from_previous_source": {"added": [], "removed": [], "changed": changed},
        "files": rows,
    }
    encoded = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    MANIFEST_OUT.write_bytes(encoded)
    repaired_row = next(row for row in rows if row["relative"] == REPAIR_RELATIVE)
    receipt = {
        "schema": "cochem-stopped-runtime-freeze-receipt/1",
        "manifest_path": str(MANIFEST_OUT),
        "manifest_sha256": sha256(encoded),
        "stage_root": str(STAGE_ROOT),
        "files": len(rows),
        "unchanged_from_r3": verified_unchanged,
        "changed": changed,
        "repair": {
            "relative": REPAIR_RELATIVE,
            "repository_commit": "5d592f9",
            "repository_sha256": REPAIR_SOURCE_SHA256,
            "staged_sha256": repaired_row["sha256"],
            "staged_length": repaired_row["length"],
            "frozen_tree_line_endings": "CRLF (mixed)" if uses_crlf and frozen_original.count(b"\r\n") != frozen_original.count(b"\n") else ("CRLF" if uses_crlf else "LF"),
            "line_ending_counts": eol_counts,
            "r3_sha256": next(row["sha256"] for row in r3["files"] if row["relative"] == REPAIR_RELATIVE),
        },
        "production_runtime_started": False,
        "production_state_opened": False,
    }
    RECEIPT_OUT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
