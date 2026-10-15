# Pipeline 4.2.8 — Independent Release-Package Review & Handover (`P428-27`)

> [!IMPORTANT]
> **Engineering Scope vs Owner Physical Acceptance (`P428-28`)**
> This document records the non-administrator independent review of the immutable
> Pipeline 4.2.8 release package (`C:\Users\ansac\CoChem427\r428-bundle-3dab7f2`; prior bundles `r428-bundle-49d65d4`, `r428-bundle-4a87f33`, `r428-bundle-4cc3460`, `r428-bundle-b862701`, `r428-bundle-491e4a3`, `r428-bundle-4ddf611`, `r428-bundle-ffe41ba`, and `r428-bundle-0b046c6` and prior sittings/roots `R428Sitting-windows-20261014-17cc6d671d8645ca92f3b8a718599726` / `Pipeline4.2.8-windows-20261014-r1`, `R428Sitting-windows-20261014-7fa83ea403cb45228db9a3e632c49f12` / `Pipeline4.2.8-windows-20261014-r2`, and `R428Sitting-windows-20261014-b36dc44751d84713b273f5a3aaac459b` / `Pipeline4.2.8-windows-20261014-r3` preserved intact).
> Engineering sessions have executed source tests, synthetic fault/recovery
> suites, offline wheel/bundle builds, and read-only package plans only.
> **No `-Apply` invocation, Administrator elevation, `SYSTEM` scheduled-task
> mutation, protected database write, or live provider/OAuth acceptance (`P428-28`)
> has been executed by engineering sessions.**

---

## 1. Frozen Release Lineage & Cryptographic Pins

| Artifact | Path / Identifier | Count / Size | SHA-256 / Digest |
| :--- | :--- | :--- | :--- |
| **Source commit (`P428-SWARM` + r4/v4 repairs & 7% CPU amendment)** | `feature/4.2.8-task-routing` | `3dab7f2` | `3dab7f2375121e0bdb82c13dc3b0add9d45179bb` |
| **Frozen source tree** | `C:\Users\ansac\CoChem427\r428-source-3dab7f2` | 255 files / 9,055,526 B | `589f15c4f1fcf1117798bc61cb6e07baf75dfdf6fc74823bb364382907b9e15c` |
| **Offline application wheel** | `C:\Users\ansac\CoChem427\r428-build-3dab7f2\dist\cochem-4.2.8-py3-none-any.whl` | 207 entries / 1,260,920 B | `57be788a2a28ad5ff9f7823a1879946d41d449aee95b72026afcaf385a996724` |
| **Build backend receipt** | `C:\Users\ansac\CoChem427\r6-build-backend-20261012-v2\receipt.json` | 4 backend wheels | `27ce4c8d60f5173f3f9326ce5b8dc76a56eb2bcf87b8c57d19e12d6c809ae53d` |
| **Toolchain `uv.exe`** | `C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\uv\uv.exe` | 57,540,184 B | `2019cdf564cb8f749262f5f021cedc75a99abb1c6081227ca340bbcda972611d` |
| **Immutable owner bundle** | `C:\Users\ansac\CoChem427\r428-bundle-3dab7f2` | 364 installer inputs | Revision `windows-20261014-428-v4` |
| **Launch manifest** | `C:\Users\ansac\CoChem427\r428-bundle-3dab7f2\launch-manifest.json` | 3,020 B (12 files) | `ac43248ab659e8597df38820c65c318cfeb724c7b43105ce89c39424cb277383` |
| **Install manifest** | `C:\Users\ansac\CoChem427\r428-bundle-3dab7f2\install-manifest.json` | 108,468 B (364 files) | `fdf93bcbec72533eca5577b2bf5fded8da11dde38e71a13b79bd58af5ca40fa3` |
| **Candidate `pipeline.json`** | `C:\Users\ansac\CoChem427\r428-bundle-3dab7f2\pipeline.json` | 26,902 B | `daaa4b6a8c15aa49ed39af48c087bfe2fcfefdcbae14520b298d46287414509a` |
| **Routing candidate** | `C:\Users\ansac\CoChem427\r428-bundle-3dab7f2\routing-candidate.json` | 331,800 B | `e53f8e84e5be5dc0972f8abd5f226b27dc62be948121d1e90aeb41f74b3fbc25` |
| **Catalog proposal** | `C:\Users\ansac\CoChem427\r428-bundle-3dab7f2\proposal.json` | 4,038 B | `2588890b30d91902642cb400843d47d16795392bcbb9e20fcf7102566d073afc` |
| **Catalog pointer** | `C:\Users\ansac\CoChem427\r428-bundle-3dab7f2\pointer.json` | 194 B | `679d54d58b46272ab8a021818390ab18f4361783635ffff67659c781a91988a2` |
| **Source test evidence** | `C:\Users\ansac\CoChem427\r428-bundle-3dab7f2\source-test-evidence.json` | 377 B | `4a1a9596fdeceddd56197e6c08449656de5c3b17b2b5d282f2835ecc1e13a47e` |

### Reviewed Launch Package Files (`launch-manifest.json`)

| Package File | Bytes | SHA-256 |
| :--- | ---: | :--- |
| `install_428_runtime.ps1` | 18,484 | `ac92b6ad90cd036ef47dca05b2486230882385634a38a233f4f298d01f52938e` |
| `stage_aetherdesk_427_payloads.ps1` | 12,591 | `0300b82731c0fddb9fad3e2ddb6a20b8368cfa91faf7aceb821752c65b5f6e0b` |
| `accept_428_native.py` | 19,866 | `defd6953f92d78e337d3588016b23b92962879e6e62eefe1226bd320d40d0012` |
| `verify_prior_native_428.py` | 27,637 | `aebc26591aab2c985a39547c6342b2e13baea03677597f923821150f04c7bb22` |
| `r6_custody_amendment.py` | 19,279 | `5663791041822c2492f572638d75b045de40fd6a751e9d7f0710ec29cb0b4284` |
| `run_428_launch.ps1` | 49,231 | `e4ac275f8bc32e41c6503e0c04472139dce10930768fbfcada3e3d1e5fcd9dcd` |
| `pipeline.json` | 26,902 | `daaa4b6a8c15aa49ed39af48c087bfe2fcfefdcbae14520b298d46287414509a` |
| `install-manifest.json` | 108,468 | `fdf93bcbec72533eca5577b2bf5fded8da11dde38e71a13b79bd58af5ca40fa3` |
| `source-test-evidence.json` | 377 | `4a1a9596fdeceddd56197e6c08449656de5c3b17b2b5d282f2835ecc1e13a47e` |
| `routing-candidate.json` | 331,800 | `e53f8e84e5be5dc0972f8abd5f226b27dc62be948121d1e90aeb41f74b3fbc25` |
| `proposal.json` | 4,038 | `2588890b30d91902642cb400843d47d16795392bcbb9e20fcf7102566d073afc` |
| `pointer.json` | 194 | `679d54d58b46272ab8a021818390ab18f4361783635ffff67659c781a91988a2` |

---

## 2. Read-Only Plan Verification on the Frozen Bundle

All three read-only plans were executed directly against the frozen bundle
`C:\Users\ansac\CoChem427\r428-bundle-3dab7f2` without `-Apply`:

1. **Owner Launch Read-Only Plan (`run_428_launch.ps1`):**
   - Verified `launch-manifest.json` (`ac43248ab659e8597df38820c65c318cfeb724c7b43105ce89c39424cb277383`),
     all 12 package files, `install-manifest.json`
     (`fdf93bcbec72533eca5577b2bf5fded8da11dde38e71a13b79bd58af5ca40fa3`), and all
     364 installer inputs (255 frozen source files, 106 locked runtime wheels,
     application wheel, candidate `pipeline.json`, and `source-test-evidence.json`)
     with read-share file locks and reparse-point traversal guards.
   - Output: `status = "R428_LAUNCH_READ_ONLY_PLAN"`, `revision = "windows-20261014-428-v4"`, `payload_files = 364`,
     `maximum_shared_slots = 4`, `repair_profiles = ["repair_claude", "repair_codex", "repair_agy"]`,
     `repair_consumes_worker_slot = false`, `input_window_minutes = 20`,
     `late_prompts = false`, `host_executed = false`.
2. **Stopped Runtime Installer Read-Only Plan (`install_428_runtime.ps1`):**
   - Verified target root `C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r4`,
     all 364 source/wheel hashes and lengths, and strict path/ACL invariants.
   - Output: `status = "READ_ONLY_PLAN"`, `revision = "windows-20261014-428-v4"`, `files = 364`, `activation_ready = false`.
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
| `package`, `front_loaded_input`, `preconditions`, `offline_install`, `native_acceptance`, `idle` | Existing `4.2.7` or `-r3` controller still running or post-reboot stopped (`$stopRequested = $false`) | `rollback = "NOT_REQUIRED"`. Live `CoChem-4.2.7-Warden` task and database are untouched; any partial `Pipeline4.2.8-*` or `R428Sitting-*` evidence is preserved. |
| `migration` (task still running or exit uncertain) | Stopped (`$stopped = $true`, `$migrationRequested = $true`, `$migrated = $false`) | `Restore-428BeforeStart` refuses to guess (`Migration completion is uncertain; preserve the stopped state`) and records `HELD_PRESERVE_STOPPED_OR_RUNNING_STATE` with all task/migration evidence intact. |
| `migration` completed or skipped (`$recovery428`), failure before `$startRequested = $true` | Stopped (`$stopped = $true`, `$startRequested = $false`) | `Restore-428BeforeStart` executes `cochem_pipeline.migration_428 --rollback` as `SYSTEM` (if migration ran in this sitting), restores any prior `current-request.json` catalog pointer via `Restore-428CatalogPointer`, restores original `CoChem-4.2.7-Warden` XML + SDDL, and either preserves the stopped post-reboot R4 state (`PREVIOUS_STOPPED_RUNTIME_RESTORED_VERIFIED`) or restarts the previous runtime and verifies `SYSTEM` health (`PREVIOUS_RUNTIME_RESTORED_HEALTH_VERIFIED`). |
| Post-start `cutover` or `catalog_publication` | New `4.2.8` controller started (`$startRequested = $true`) | Records `HELD_PRESERVE_POSSIBLY_RUNNING_STATE` in `r428-held.json` and `status-*.json` without stopping or deleting active state. |

---

## 5. Single Owner Command (`P428-28`)

Run **once** in a 64-bit Administrator Windows PowerShell 5.1 (`Desktop` edition)
window as `AETHERDESK\ansac`:

```powershell
& "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile `
  -File "C:\Users\ansac\CoChem427\r428-bundle-3dab7f2\run_428_launch.ps1" `
  -LaunchManifest "C:\Users\ansac\CoChem427\r428-bundle-3dab7f2\launch-manifest.json" `
  -LaunchManifestSha256 "ac43248ab659e8597df38820c65c318cfeb724c7b43105ce89c39424cb277383" `
  -Apply
```

---

## 6. Verified Owner Sitting Completion (`P428-28`)

- **Sitting Directory:** `C:\Program Files\CoChem\R428Sitting-windows-20261014-9bc847c534af4e56b0f9238ead81de8a`
- **Final Sanitized Status Receipt:** `C:\Program Files\CoChem\R428Sitting-windows-20261014-9bc847c534af4e56b0f9238ead81de8a\status-20261015T0137470586569-aa402a6c5239432c81c560b03ff29691.json` (`2026-10-15T01:37:47.0586569Z`)
- **Runtime Completion Receipt:** `C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r4\r428-complete.json`
  - `status`: `R428_RUNNING_CATALOG_PUBLICATION_VERIFIED`
  - `version`: `4.2.8`
  - `source_commit`: `3dab7f2375121e0bdb82c13dc3b0add9d45179bb`
  - `launch_manifest_sha256`: `ac43248ab659e8597df38820c65c318cfeb724c7b43105ce89c39424cb277383`
  - `request_id`: `b8ef27858d2242d0931071f0ed2eaacd`
  - `native_control_probe_verified`: `true`
  - `backup_preserved`: `true`
  - `late_prompt`: `false`
- **Live `pipeline_health` Verification (`127.0.0.1:47824`):**
  - `service_identity`: `SYSTEM`
  - `pid`: `24424`, `instance_id`: `65bb2e91a4df42e197a198508a7b5fee`
  - `source_root`: `C:\Program Files\CoChem\Pipeline4.2.8-windows-20261014-r4\.venv\Lib`
  - `admission_capacity`: `4` (`hardware.state = "normal"`, `warden_controller.state = "healthy"`, `cpu_limit_percent = 7`, `cpu_window_seconds = 10.141`)
  - `catalog_activation`: `{"status": "ALREADY_PUBLISHED", "request_id": "b8ef27858d2242d0931071f0ed2eaacd", "policy_digest": "c8444fe2fd46b0f53edeaefc677ef7ff698c3e11cb83348a70255026a81da43d"}`



