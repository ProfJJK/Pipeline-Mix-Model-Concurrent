# Pipeline 4.2.8 — Independent Release-Package Review & Handover (`P428-27`)

> [!IMPORTANT]
> **Engineering Scope vs Owner Physical Acceptance (`P428-28`)**
> This document records the non-administrator independent review of the immutable
> Pipeline 4.2.8 release package (`C:\Users\ansac\CoChem427\r428-bundle-491e4a3`; prior bundles `r428-bundle-4cc3460` and `r428-bundle-b862701` and prior sitting/root `R428Sitting-windows-20261014-17cc6d671d8645ca92f3b8a718599726` / `Pipeline4.2.8-windows-20261014-r1` preserved intact).
> Engineering sessions have executed source tests, synthetic fault/recovery
> suites, offline wheel/bundle builds, and read-only package plans only.
> **No `-Apply` invocation, Administrator elevation, `SYSTEM` scheduled-task
> mutation, protected database write, or live provider/OAuth acceptance (`P428-28`)
> has been executed by engineering sessions.**

---

## 1. Frozen Release Lineage & Cryptographic Pins

| Artifact | Path / Identifier | Count / Size | SHA-256 / Digest |
| :--- | :--- | :--- | :--- |
| **Source commit (`P428-26` / `P428-28` fix)** | `feature/4.2.8-task-routing` | `491e4a3` | `491e4a37c253aea038b2aa3a579b506ab3ed3c18` |
| **Frozen source tree** | `C:\Users\ansac\CoChem427\r428-source-491e4a3` | 253 files / 8,967,083 B | `ac17f29b8a1b5ad565575cf7d52ee31da22734e4a4a1eb6cbc4715e2ee2e3c45` |
| **Offline application wheel** | `C:\Users\ansac\CoChem427\r428-build-491e4a3\dist\cochem-4.2.8-py3-none-any.whl` | 206 entries / 1,245,390 B | `bec73ad2a86cc3c61ac9d7e1e74104b5a53dc0f983cc9c8fb8ec3654910cb4e6` |
| **Build backend receipt** | `C:\Users\ansac\CoChem427\r6-build-backend-20261012-v2\receipt.json` | 4 backend wheels | `27ce4c8d60f5173f3f9326ce5b8dc76a56eb2bcf87b8c57d19e12d6c809ae53d` |
| **Toolchain `uv.exe`** | `C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\uv\uv.exe` | 57,540,184 B | `2019cdf564cb8f749262f5f021cedc75a99abb1c6081227ca340bbcda972611d` |
| **Immutable owner bundle** | `C:\Users\ansac\CoChem427\r428-bundle-491e4a3` | 362 installer inputs | Revision `windows-20261014-428-v2` |
| **Launch manifest** | `C:\Users\ansac\CoChem427\r428-bundle-491e4a3\launch-manifest.json` | 3,020 B (12 files) | `c9713b51ea48bb82d1ee7d11f8640ed3859b9dd49fe75d4297cfd9d4bd22cd1f` |
| **Install manifest** | `C:\Users\ansac\CoChem427\r428-bundle-491e4a3\install-manifest.json` | 107,865 B (362 files) | `0d45ffe310e6392979979125c24b1bfe5fa007409767dce028156085f5c39e8a` |
| **Candidate `pipeline.json`** | `C:\Users\ansac\CoChem427\r428-bundle-491e4a3\pipeline.json` | 26,902 B | `ff77d5e5713a5390a41fd384d78899f01f2b4d93d3931605759a1bad18420a1f` |
| **Routing candidate** | `C:\Users\ansac\CoChem427\r428-bundle-491e4a3\routing-candidate.json` | 331,800 B | `e53f8e84e5be5dc0972f8abd5f226b27dc62be948121d1e90aeb41f74b3fbc25` |
| **Catalog proposal** | `C:\Users\ansac\CoChem427\r428-bundle-491e4a3\proposal.json` | 4,038 B | `2588890b30d91902642cb400843d47d16795392bcbb9e20fcf7102566d073afc` |
| **Catalog pointer** | `C:\Users\ansac\CoChem427\r428-bundle-491e4a3\pointer.json` | 194 B | `1a7f87d3b230dcf930d414a08c75dbeaa92054266545cc2e29b95a28be738a30` |
| **Source test evidence** | `C:\Users\ansac\CoChem427\r428-bundle-491e4a3\source-test-evidence.json` | 377 B | `53cc8a0464081df94ad4494ee185887dc2410d5fb21630bc52d7a1badf032ca0` |

### Reviewed Launch Package Files (`launch-manifest.json`)

| Package File | Bytes | SHA-256 |
| :--- | ---: | :--- |
| `install_428_runtime.ps1` | 18,484 | `208652452b3af0c5f9662b00cd0b7086410ab66514393eac155436ece7f61e0d` |
| `stage_aetherdesk_427_payloads.ps1` | 12,591 | `0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b` |
| `accept_428_native.py` | 19,866 | `defd6953f92d78e337d3588016b23b92962879e6e62eefe1226bd320d40d0012` |
| `verify_prior_native_428.py` | 27,638 | `c309a9826553b7a662e90a008e70c7e9e4819c8138983f2673c737898eb3c07e` |
| `r6_custody_amendment.py` | 19,279 | `5663791041822c2492f572638d75b045de40fd6a751e9d7f0710ec29cb0b4284` |
| `run_428_launch.ps1` | 41,168 | `78f55860e084c36011523103e8005ab8931b95f29956290e4630e354c32ebada` |
| `pipeline.json` | 26,902 | `ff77d5e5713a5390a41fd384d78899f01f2b4d93d3931605759a1bad18420a1f` |
| `install-manifest.json` | 107,865 | `0d45ffe310e6392979979125c24b1bfe5fa007409767dce028156085f5c39e8a` |
| `source-test-evidence.json` | 377 | `53cc8a0464081df94ad4494ee185887dc2410d5fb21630bc52d7a1badf032ca0` |
| `routing-candidate.json` | 331,800 | `e53f8e84e5be5dc0972f8abd5f226b27dc62be948121d1e90aeb41f74b3fbc25` |
| `proposal.json` | 4,038 | `2588890b30d91902642cb400843d47d16795392bcbb9e20fcf7102566d073afc` |
| `pointer.json` | 194 | `1a7f87d3b230dcf930d414a08c75dbeaa92054266545cc2e29b95a28be738a30` |

---

## 2. Read-Only Plan Verification on the Frozen Bundle

All three read-only plans were executed directly against the frozen bundle
`C:\Users\ansac\CoChem427\r428-bundle-491e4a3` without `-Apply`:

1. **Owner Launch Read-Only Plan (`run_428_launch.ps1`):**
   - Verified `launch-manifest.json` (`c9713b51ea48bb82d1ee7d11f8640ed3859b9dd49fe75d4297cfd9d4bd22cd1f`),
     all 12 package files, `install-manifest.json`
     (`0d45ffe310e6392979979125c24b1bfe5fa007409767dce028156085f5c39e8a`), and all
     362 installer inputs (253 frozen source files, 106 locked runtime wheels,
     application wheel, candidate `pipeline.json`, and `source-test-evidence.json`)
     with read-share file locks and reparse-point traversal guards.
   - Output: `status = "R428_LAUNCH_READ_ONLY_PLAN"`, `revision = "windows-20261014-428-v2"`, `payload_files = 362`,
     `maximum_shared_slots = 4`, `repair_profiles = ["repair_claude", "repair_codex", "repair_agy"]`,
     `repair_consumes_worker_slot = false`, `input_window_minutes = 20`,
     `late_prompts = false`, `host_executed = false`.
2. **Stopped Runtime Installer Read-Only Plan (`install_428_runtime.ps1`):**
   - Verified target root `C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r2`,
     all 362 source/wheel hashes and lengths, and strict path/ACL invariants.
   - Output: `status = "READ_ONLY_PLAN"`, `revision = "windows-20261014-428-v2"`, `files = 362`, `activation_ready = false`.
3. **Native Acceptance Read-Only Plan (`accept_428_native.py --mode plan`):**
   - Verified `bundle_pin_verification.verified_files = 12`, `tamper_detected = false`,
     `prior_native_repairs.source_repairs.status = "ALL_R5_R6_REPAIRS_IN_CANONICAL_SOURCE"`,
     `fable_target_23_policy = "QUOTA_429_BECOMES_AVAILABILITY_SKIP_ONLY"`,
     `argon_targets = ["gemini-4-argon-low", "gemini-4-argon-medium", "gemini-4-argon-high"]`,
     and `signin_plan` reusing the 15 worker profiles (`slot1`..`slot5` $\times$ 3 providers)
     while isolating `repair_claude`, `repair_codex`, and `repair_agy` outside the
     4 shared worker slots.

---

## 3. Front-Loaded 20-Minute Input Budget & Walk-Away Boundary Review

- **Reuse of Verified Worker Profiles:** Existing verified worker sessions
  (`slot1`..`slot5` across `codex`, `claude`, `gemini`) are preserved and never
  re-prompted when healthy.
- **Dedicated Repair Profiles:** Only the three isolated repair profiles
  (`repair_claude`, `repair_codex`, `repair_agy`) and owner approval secret setup
  are eligible for interactive attention during `front_loaded_input`.
- **Hard 20-Minute Cutoff (`Assert-428InputWindow`):**
  - Rejects negative clock skew (`elapsed < 0`) and any interactive request after
    `1200` seconds (`elapsed > 1200`).
  - Validates HTTPS OAuth URLs, rejects whitespace/control characters, and blocks
    stale or replayed OAuth URLs and dialog identifiers via session hash sets.
- **Walk-Away Boundary:** Once `front_loaded_input` and `preconditions` complete,
  `run_428_launch.ps1` prints:
  `4.2.8 prerequisites and front-loaded inputs verified. You can walk away; all remaining stages are unattended.`
  Every subsequent child process (`install_428_runtime.ps1`, `accept_428_native.py`,
  and the `SYSTEM` migration task) runs non-interactively with bounded timeouts.
  A thread-affinitized `SetThreadExecutionState(CONTINUOUS | SYSTEM_REQUIRED)`
  lease prevents idle sleep during the sitting and is restored in `finally` without
  mutating the Windows power plan.

---

## 4. Rollback & Evidence Preservation Verification

| Failure Phase | Controller State | Rollback / Preservation Action |
| :--- | :--- | :--- |
| `package`, `front_loaded_input`, `preconditions`, `offline_install`, `native_acceptance`, `idle` | Existing `4.2.7` controller still running (`$stopRequested = $false`) | `rollback = "NOT_REQUIRED"`. Live `CoChem-4.2.7-Warden` task and database are untouched; any partial `Pipeline4.2.8-*` or `R428Sitting-*` evidence is preserved. |
| `migration` (task still running or exit uncertain) | Stopped (`$stopped = $true`, `$migrationRequested = $true`, `$migrated = $false`) | `Restore-428BeforeStart` refuses to guess (`Migration completion is uncertain; preserve the stopped state`) and records `HELD_PRESERVE_STOPPED_OR_RUNNING_STATE` with all task/migration evidence intact. |
| `migration` completed, failure before `$startRequested = $true` | Stopped (`$stopped = $true`, `$migrated = $true`, `$startRequested = $false`) | `Restore-428BeforeStart` executes `cochem_pipeline.migration_428 --rollback` as `SYSTEM`, verifies `PRE_CUTOVER_DATABASE_RESTORED`, restores original `CoChem-4.2.7-Warden` XML + SDDL, restarts previous runtime, and verifies `SYSTEM` health (`PREVIOUS_RUNTIME_RESTORED_HEALTH_VERIFIED`). |
| Post-start `cutover` or `catalog_publication` | New `4.2.8` controller started (`$startRequested = $true`) | Records `HELD_PRESERVE_POSSIBLY_RUNNING_STATE` in `r428-held.json` and `status-*.json` without stopping or deleting active state. |

---

## 5. Single Owner Command (`P428-28`)

Run **once** in a 64-bit Administrator Windows PowerShell 5.1 (`Desktop` edition)
window as `AETHERDESK\ansac`:

```powershell
& "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile `
  -File "C:\Users\ansac\CoChem427\r428-bundle-491e4a3\run_428_launch.ps1" `
  -LaunchManifest "C:\Users\ansac\CoChem427\r428-bundle-491e4a3\launch-manifest.json" `
  -LaunchManifestSha256 "c9713b51ea48bb82d1ee7d11f8640ed3859b9dd49fe75d4297cfd9d4bd22cd1f" `
  -Apply
```
