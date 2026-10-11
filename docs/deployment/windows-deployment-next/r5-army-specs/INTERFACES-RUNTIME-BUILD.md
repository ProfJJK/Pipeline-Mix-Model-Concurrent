# Runtime-build interfaces for RUN_427_R5_SITTING.ps1 (2026-10-11)

Files: freeze-stopped-runtime-r5-source.py bd660fac (117 tests), install-stopped-runtime-r5.ps1 32675aae (185 + 2 skips
until the real freeze), run-upgrade-preview-r5-v1.ps1 c09fd990 + run_upgrade_preview_r5_v1.py 71e03832 (98 tests; audit
fix wave: pins retarget-warden-r5.ps1 3ca1f9a6 and imports Assert-StagingReceipt / Read-JsonControl from it).
NOTE: the audit fix wave changes 5 of the 13 frozen source files, so the freeze REPAIRS table and the installer's 13-pin
table will be refilled from the FIX commit (--print-pins) by the Commander, and these file shas will change. Use the
pin generator; never hard-code these shas elsewhere.

## Before the sitting (Commander, not elevated)
PY -I -B freeze-stopped-runtime-r5-source.py --commit <final r5 commit>
-> stage C:\Users\ansac\CoChem427\stopped-runtime-r5-source, manifest W\stopped-runtime-r5-source-manifest.json,
   receipt W\stopped-runtime-r5-freeze-receipt.json (manifest_sha256 = the installer's -ManifestSha256; pin it in S0).

## S1 install (child form: powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File)
"$W\install-stopped-runtime-r5.ps1" -Manifest "$W\stopped-runtime-r5-source-manifest.json" -ManifestSha256 <sha>          (plan; holds must be [])
"$W\install-stopped-runtime-r5.ps1" -Manifest "$W\stopped-runtime-r5-source-manifest.json" -ManifestSha256 <sha> -Apply
Gate: exit 0; C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5\install-after.json mode FRESH_STOPPED_RUNTIME_READY,
reviewed_repairs == the 13 pinned paths/shas, verified_unchanged 153 (NOT 154), tasks_changed 0, holds [],
verification.r5_repairs_installed true. Record its sha for S10/S11. Failure: read install-held.json (failed_stage); stop; r4 untouched.
r5 interpreter: C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5\.venv\Scripts\python.exe

## S10 upgrade preview
"$W\run-upgrade-preview-r5-v1.ps1" -Attempt <fresh 32 hex> -CandidateSha256 <staging receipt staged_sha256> [-Candidate <staged path if not -r5-v1>]   (plan)
same + -Apply
Gate: exit 0 and <UpgradePreview root>\preview-summary.json decision PASSED. Root
C:\Program Files\CoChem\UpgradePreview4.2.7-windows-20261011-r5-v1-<attempt>. Failure prints COCHEM_UPGRADE_PREVIEW_RESULT {json}
and a message starting 'SERIES-STOP (S10)' -> R4-RESTORE (or an owner waiver line).
Gate semantics (Commander-approved, pending deploy audit): 'no entry has changed=true' except the configuration path moving
from the bound current to the bound candidate path; schema_changes from database.schema_changes. In enabled mode the gate
hashes providers.* per provider from the two bound files (providers_changed) and allows only 'gemini' to differ (B-F5).
