# Pipeline 4.2.8 — Single Owner Launch Sheet (`P428-26`)

> [!IMPORTANT]
> **Read-Only Default vs Owner Sitting (`P428-28`)**
> Engineering sessions prepare and verify the immutable 4.2.8 package and its
> read-only plan (`-Apply` omitted). Only the owner (`AETHERDESK\ansac`) runs
> `-Apply` once in a 64-bit Administrator Windows PowerShell 5.1 window during
> `P428-28`.

---

## 1. What the Single Entry Point Does

The packaged entry point `run_428_launch.ps1` executes the complete 4.2.8
installation, pre-cutover native acceptance, SYSTEM database migration, catalog
authority publication, and Warden cutover in one sitting:

1. **Pin & Package Verification (`package`):**
   Opens `launch-manifest.json` (`cochem-428-launch-package/1`) and holds read-share
   handles on every reviewed package input (`install_428_runtime.ps1`,
   `stage_aetherdesk_427_payloads.ps1`, `accept_428_native.py`,
   `verify_prior_native_428.py`, `r6_custody_amendment.py`, `run_428_launch.ps1`,
   `pipeline.json`, `install-manifest.json`, `source-test-evidence.json`,
   `routing-candidate.json`, `proposal.json`, `pointer.json`) and every frozen
   source/wheel file so no bytes can be modified during the sitting.
2. **Front-Loaded Input Window (`front_loaded_input`, strictly $\le 20$ minutes):**
   - Verifies the existing completed baseline (`R6`/`R7` sitting receipt or the live `AETHERDESK` `R4` v11 running + `R6` stopped runtime + canonical target-23 `R6Acceptance4.2.7-windows-20261012-v1-native-47e4889af6284a9fad018142a14d5371` hold baseline) and reuses already
     verified worker profiles (`slot1`..`slot5` across `codex`, `claude`, `gemini`).
   - Front-loads any newly required dedicated repair-profile sign-ins
     (`repair_claude`, `repair_codex`, `repair_agy`) and owner approval broker
     secret confirmation (`cochem_pipeline.owner_approval_428`).
   - Enforces fresh HTTPS OAuth URLs and unique dialog IDs; rejects stale or
     replayed URLs and forbids any interactive prompt after the 20-minute window.
   - Prints the explicit walk-away boundary:
     `4.2.8 prerequisites and front-loaded inputs verified. You can walk away; all remaining stages are unattended.`
3. **Unattended Stopped Runtime Installation (`offline_install`):**
   Invokes `install_428_runtime.ps1 -Apply` with `-NonInteractive` to install the
   offline 4.2.8 wheel and locked runtime dependencies into
   `C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r4` using the protected
   toolchain (`Toolchain4.2.7-windows-20261006`), while preserving the earlier
   `Pipeline4.2.8-windows-20261014-r1`, `Pipeline4.2.8-windows-20261014-r2`, and
   `Pipeline4.2.8-windows-20261014-r3` roots untouched.
4. **Pre-Cutover Native Acceptance (`native_acceptance`):**
   Invokes `accept_428_native.py --mode accept --apply` under the new 4.2.8
   interpreter to verify canonical R5/R6 source repairs, replay the saved target-23
   (`claude-fable-5-1` High) HTTP 429 hold as a quota skip (`AVAILABILITY_WAIT`)
   rather than a code defect or fabricated acceptance (verifying protected Program Files
   ancestry, ACLs, link count, size bounds, and SHA-256 pins under Administrator or
   `SYSTEM`), and record sanitized pre-cutover acceptance evidence in the sitting directory.
5. **Controller Quiescence & Stop (`idle` $\rightarrow$ `stop`):**
   Confirms two consecutive idle observations of the live controller on
   `127.0.0.1:47824` (via `/health` routing counts on R4 or `/operator` on R6/R7/4.2.8), verifies process and parent process ownership (`S-1-5-18`),
   disables the logon trigger (or preserves 0-trigger R4 task state), stops `CoChem-4.2.7-Warden`, and verifies port `47824`
   is free.
6. **Versioned SYSTEM State Migration (`migration`):**
   Runs `cochem_pipeline.migration_428` as a one-shot `SYSTEM` scheduled task
   against `C:\ProgramData\CoChemPipeline427\private`, preserving a full pre-cutover
   snapshot + SHA-256 inventory and verifying row/hash preservation across all
   existing 4.2.7 tables before applying additive 4.2.8 tables, and validating the
   private receipt under `C:\Program Files\CoChem\Migration4.2.8-windows-20261014-v4`
   (or skipping repeat migration when recovering from the already-migrated `Pipeline4.2.8-windows-20261014-r3` baseline).
7. **Catalog Authority & Cutover (`cutover` $\rightarrow$ `catalog_publication`):**
   Copies `proposal.json` and atomically replaces `current-request.json` via
   `Set-428CatalogPointer` in `C:\Program Files\CoChem\RoutingCatalog4.2.8` (backing up
   any prior pointer for pre-start rollback), retargets `CoChem-4.2.7-Warden`
   to `C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r4`, starts the
   4.2.8 controller (which prewarms CLI binary digests and records `mark_cutover_428` on startup), verifies `SYSTEM` process identity and health, ensures and re-enables the
   `AETHERDESK\ansac` `PT1M` logon trigger, and waits for catalog publication (`PUBLISHED_IN_CALLER_TRANSACTION`
   or `ALREADY_PUBLISHED`).

---

## 2. Rollback & Evidence Preservation Boundaries

- **Failure before stopping the live controller (`package`, `front_loaded_input`, `offline_install`, `native_acceptance`, `idle`):**
  The existing controller remains running untouched. Partial 4.2.8 installation or
  sitting directories are preserved for inspection and never automatically deleted
  or reused.
- **Failure after stopping the live controller and before starting the new 4.2.8 controller (`migration`, `catalog_authority`, pre-start `cutover`):**
  `Restore-428BeforeStart` automatically runs `cochem_pipeline.migration_428 --rollback`
  (if migration ran in this sitting) to restore the byte-identical pre-cutover SQLite files,
  restores any previous `current-request.json` catalog pointer via `Restore-428CatalogPointer`,
  restores the original `CoChem-4.2.7-Warden` XML and SDDL, restarts the previous
  runtime, and verifies `SYSTEM` health (`PREVIOUS_RUNTIME_RESTORED_HEALTH_VERIFIED`).
  If migration completion itself is uncertain, the script holds in the stopped state
  and preserves all evidence rather than guessing.
- **Failure after starting the new 4.2.8 controller (`cutover` post-start, `catalog_publication`):**
  The script records `HELD_PRESERVE_POSSIBLY_RUNNING_STATE` in `r428-held.json` and
  `status-*.json` without mutating or deleting active databases.

---

## 3. Read-Only Plan vs Owner Execution Commands

- **Frozen source commit (`P428-SWARM` + Fable envelope replay + R4/r3 recovery, 7% / 10 s rolling CPU window, prewarmed CLI binary digests, and catalog probe lease stability):** `3dab7f2375121e0bdb82c13dc3b0add9d45179bb` (`3dab7f2`)
- **Immutable release bundle:** `C:\Users\ansac\CoChem427\r428-bundle-3dab7f2` (prior bundles `r428-bundle-49d65d4`, `r428-bundle-4a87f33`, `r428-bundle-4cc3460`, `r428-bundle-b862701`, `r428-bundle-491e4a3`, `r428-bundle-4ddf611`, `r428-bundle-ffe41ba`, and `r428-bundle-0b046c6` preserved intact)
- **Launch manifest SHA-256:** `ac43248ab659e8597df38820c65c318cfeb724c7b43105ce89c39424cb277383`
- **Install manifest SHA-256:** `fdf93bcbec72533eca5577b2bf5fded8da11dde38e71a13b79bd58af5ca40fa3`

### A. Read-Only Plan (Safe in Engineering / Non-Admin Sessions)

```powershell
& "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive `
  -File "C:\Users\ansac\CoChem427\r428-bundle-3dab7f2\run_428_launch.ps1" `
  -LaunchManifest "C:\Users\ansac\CoChem427\r428-bundle-3dab7f2\launch-manifest.json" `
  -LaunchManifestSha256 "ac43248ab659e8597df38820c65c318cfeb724c7b43105ce89c39424cb277383"
```

### B. Single Owner Sitting Command (`P428-28`, 64-bit Administrator Windows PowerShell 5.1 as `AETHERDESK\ansac`)

See `docs/4.2.8/RELEASE_REVIEW.md` for the complete independent release-package review and pin inventory.

```powershell
& "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile `
  -File "C:\Users\ansac\CoChem427\r428-bundle-3dab7f2\run_428_launch.ps1" `
  -LaunchManifest "C:\Users\ansac\CoChem427\r428-bundle-3dab7f2\launch-manifest.json" `
  -LaunchManifestSha256 "ac43248ab659e8597df38820c65c318cfeb724c7b43105ce89c39424cb277383" `
  -Apply
```

### C. Sanitized Status & Evidence Locations

- **Sanitized sitting status directory:**
  `C:\Program Files\CoChem\R428Sitting-windows-20261014-<guid>\status-*.json`
- **Completion / hold receipts:**
  - `C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r4\r428-complete.json`
  - `C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r4\r428-held.json`
- **Protected migration evidence & pre-cutover backup:**
  `C:\Program Files\CoChem\Migration4.2.8-windows-20261014-v3\migration-428.json` (initial `-r3` migration) or `C:\Program Files\CoChem\Migration4.2.8-windows-20261014-v4\migration-428.json`


