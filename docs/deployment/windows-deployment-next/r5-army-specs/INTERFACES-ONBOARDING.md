# Onboarding interfaces for RUN_427_R5_SITTING.ps1 (final, 2026-10-11)

Harnesses (each run alone through serialize-heavy.py, after the onboarding audit fix wave): bridge 177, wrapper 74,
history 24, driver 86, status leaf 51, capture 83, isolation 108 passed (after final-review RG-2/RG-3). Config builder
against the final isolation: 89 passed.

## Pins for the S0 table (final after FIX-ONBOARD; the sitting takes them from refresh-r5-sitting-pins.py)
- cochem-inference-only.agent.md 5c0082d70d073263a56d748a46187008968c070d0efc7d5b7612c2fd61d11810 (478 bytes, no 'hidden' key)
- agy-status-capture-r4-v1.ps1 90d5612347748563e05437bb173f05289c669c530d266f109f4ff668077c0f2a
- agy_status_capture_r4_v1.py ce103aad0f9dae042677ec61c2b16eb5512e9a24f5fca65bc97f4570bb884038
- check-worker-native-auth-status-six-r4-v1.ps1 (status leaf) c0b5df803a339a7dbbbd59727ea59a75dc4722d474f4bb05852d5cdc8778e265
- worker-native-auth-status-six-r4-v1.py (helper, unchanged) 45681477194d97b144e8ee4505d4364d73d58aaef19c8428c846df642c834839
- login-six-workers-status-first-r4-v1.ps1 f4fedd50925dbe8bd0bdb509c449f5085209d3eab665c5917573998ffcd981c4
- login_pipeline_worker_interactive_agy_r4_v1.ps1 da166c1dbdb047e93692eeb47abf3d315dbe797cf9040d34b440d9649626014a
- worker_agy_login_bridge_r4_v1.py 4074878f100ae59b804c95bd97b3280ccaa09f919ffaa365a3e2c6985045b8d9
- agy-session-history-r4-v1.ps1 4e86b712314e2a6a8ea9f13e1dfcc9e65dda4035d2895b8043fbf6ceed0424d4
- agy_isolation_evidence_r4_v1.py 767f03af910fb137bd9a08ed82390f08878d802c45cfb9689eadb5ca44af8d60
- agy-isolation-evidence-r4-v1.ps1 b837f0f42c4cea9293231d58c6930c3a20b41ba53ba3695db0eff2ea2db17070
- S8 also scans each R run's newly created agy cli log for true fallback phrases (MODEL_FALLBACK_LOGGED holds G3) and
  inventories ~/.gemini/config/sidecars (RG-2, RG-3).

## Behaviour changes from the onboarding audit fix wave (exit codes unchanged)
- S5/S7 capture: login-mode URL evidence only for https://accounts.google.com/ (a paste prompt still counts alone);
  capture-held.json gains root_verified.
- S6 sign-in: input refused after the bridge's 600 s window (closed marker) or task end; an unconsumed input.once is
  deleted; the code prompt appears only after an accounts.google.com URL; an output-bound stop is the reviewed class
  TERMINAL_OUTPUT_BOUND_NATIVE_LOGIN_CLEANUP_VERIFIED (slot not blocked). The status leaf ends HOLD with task result 2
  and prints COCHEM_NATIVE_AUTH_STATUS_RESULT.
- S8 isolation: -StageOnly also creates an empty C:\ProgramData\Antigravity (SYSTEM/BA full, Users read+traverse) and
  protects .gemini\agents and .gemini\config\agents in each worker profile; G3 holds unless that ProgramData folder is
  absent or exactly the protected empty one; job process accounting per run (more than agy + console host holds G3);
  inventory covers every documented agy customization location and every ancestor of the slot and RAM roots; profile
  config files are judged by content (plugins/mcp/hooks/skills/agents keys with non-empty values hold G3). A deadline
  skip after a passing R1 keeps EVIDENCE_COMPLETE.

## S5 / S7 capture (slot1)
agy-status-capture-r4-v1.ps1 signed-out then signed-in; signed-out root
C:\Program Files\CoChem\AgyCapture4.2.7-windows-20261010-r4-v1-<attempt>-slot1-signed-out\login-mode.json decides
print | tui | none (none = Gemini held). Read the capture script for its exact parameters and exit codes.

## S6 sign-in (attended, owner console, do not capture output)
powershell.exe -NoProfile -File W\login-six-workers-status-first-r4-v1.ps1 -Provider gemini -LoginMode <print|tui>
  -Attempt <32-hex nonzero, same as the capture> -Apply -Interactive
Exit 0 = series complete; 20 = orderly pause (series-paused.json); other = refused or held (series-held.json).
Series root C:\Program Files\CoChem\NativeAuthSix4.2.7-windows-20261011-r4-v1-<attempt>-gemini\series-complete.json
(schema cochem-six-worker-status-first-result/1, status SIX_CONFIGURED_WORKERS_SUBSCRIPTION_AUTHENTICATION_VERIFIED,
all_slots_reuse_verified true, selected_workers_verified 6). One slot can take up to ~15 min; the driver has no timeout.

## S8 isolation evidence (two SYSTEM tasks, either order)
1. W\agy-isolation-evidence-r4-v1.ps1 -Slot slot1 -EffortNullSlug gemini-3.8-flash-low -Attempt <32-hex> -Apply   (G3)
2. W\agy-isolation-evidence-r4-v1.ps1 -StageOnly -Attempt <32-hex> -Apply                                      (G4)
Exit 0 = gate passed; 10 = Gemini held (held record); 1 = refused or held by error.
Roots C:\Program Files\CoChem\AgyIsolation4.2.7-windows-20261011-r4-v1-<attempt>[-stage].
Builder inputs: isolation-receipt.json, isolation-summary.json (capability_reference), replay\R1..R5.stdout/.stderr,
stage-receipt.json, stage-summary.json; *-held.json must be absent.

## SESS-12 (S3) claude/codex session health
check-worker-native-auth-status-six-r4-v1.ps1 -Slot -Provider claude|codex -Stage before -Attempt -Apply, strictly sequential.
