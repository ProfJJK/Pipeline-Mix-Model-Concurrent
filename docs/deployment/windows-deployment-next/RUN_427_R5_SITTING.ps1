#Requires -Version 5.1
<# ONE-SITTING r5 DEPLOYMENT of the CoChem 4.2.7 pipeline (owner, 64-bit Administrator Windows PowerShell 5.1 on AETHERDESK).
   Derived from RUN_427_LAUNCH_SERIES.ps1 rev 3 (stage functions driven by an inert harness, SERIES-STOP throws, rerun skips
   finished stages) and r5-army-specs\deploy-r5-sitting.json as amended by ARMY_ADDENDUM_20261011 (A1 Warden down, A2
   reboot-safe r5, A4 Gemini attempted by default, A5 no S4) and the final INTERFACES-CUTOVER / -ONBOARDING / -RUNTIME-BUILD /
   -CONFIG files. Without -Apply it prints a read-only plan (pin check, Warden state, Docker, the stage list) and changes nothing.

   USAGE  powershell.exe -NoProfile -ExecutionPolicy Bypass -File RUN_427_R5_SITTING.ps1 [-Apply] [-Attempt v1]
                         [-Gemini attempt|skip] [-EffortNullSlug gemini-3.8-flash-low] [-SkipFixProof]
   Attended parts: the six Google sign-ins (S6) and, only when a worker session is signed out, one Y/N question (S3).
   Gemini failures at S5-S10 and S13 degrade to "Gemini held" and never fail the sitting (a Gemini configuration that cannot be
   staged at S9 or previewed at S10 is replaced by the held configuration, staged to the next WardenConfig attempt, and S10
   runs once more; audit F3); Claude and Codex end up working on r5, or on r4 after an automatic R4-RESTORE.

   HARNESS CONTRACT (test_r5_sitting_flow.py / test_r5_sitting_static.py)
   - Top level: the param block, pure assignments ($script:Workspace, $script:Base, the pin table), function definitions and
     one guarded last statement. The harness dot-sources the functions from the AST, sets $script:Workspace, $script:Base,
     $script:Attempt, $script:Gemini, $script:EffortNullSlug, $script:Apply, $script:SkipFixProof and $script:Pins, calls
     Initialize-R5Paths (every path the sitting reads or writes is derived there from $script:Base / $script:Workspace) and
     stubs the wrappers below.
   - Pin table: the one hashtable script:Pins (file name in W -> sha256) between the PIN TABLE markers, written only by
     refresh-r5-sitting-pins.py (names resolve against the folder of this script). Assert-R5Pin <name> runs before every
     child, the builder and nothing else may start a W file. It returns {path; stream}: the file stays open behind a
     deny-write/delete handle (FileShare.Read) until the child exits, and the launchers dispose it in a finally (audit F6).
     Invoke-R5Control first opens the client config the same way and requires port 47824 ($script:ControlPort) and the pinned
     token file ($script:TokenFile), mirroring the cutover scripts' Assert-ClientConfig.
   - Stub-able wrappers: Invoke-R5Native (exe,args -> {code;text}; lowest launcher), Invoke-R5Child (Assert-R5Pin, then
     powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File), Invoke-R5Attended (Assert-R5Pin, then Start-Process
     -NoNewWindow -PassThru and WaitForExit in the same console; exit code), Invoke-R5Python (optional -PinName ->
     Assert-R5Pin; r5 interpreter),
     Invoke-R5Control (ControlClient through Invoke-R5Python; parsed object or $null), Read-R5YesNo, Request-R5Attention,
     Wait-R5Seconds, Get-R5Now, Assert-R5OwnerShell, Get-R5WardenState, Get-R5DockerInfo, Test-R5PackageIndex,
     Get-R5FreeDiskGB, Get-R5ListenerCount, Get-R5ProcessList, New-R5HexAttempt, Get-R5FileSha256. Read-R5Warden normalizes Get-R5WardenState
     (listening as a count or a boolean; running derived when absent). All waits go through Wait-R5Seconds (>= 10 s in S12/S13).
   - Records: Write-R5Record (CreateNew JSON under $script:SittingRoot), Write-R5Receipt <S01..S14> <status> (schema
     cochem-r5-sitting-stage/1 with the whole $script:R5 state), Read-R5Receipt. A rerun with the same -Attempt skips every
     stage whose receipt verifies and restores the state from the latest one. sitting-end.json (written after success or
     after any R4-RESTORE attempt) makes a rerun refuse; S11-intent.json / fallback-intent.json without the matching receipt
     (an interrupted window) also refuse.

   STAGES AND CHILD CALLS (W = this folder; B = C:\Program Files\CoChem; Gx = one fresh 32-hex Gemini attempt for S5-S8;
   vN = the first free namespace under B at call time; every child is launched only after Assert-R5Pin)
   S0  preconditions, no child: owner shell; Get-R5PinDrift empty; freeze receipt manifest_sha256 == pin of
       stopped-runtime-r5-source-manifest.json; sitting-end absent; Docker (Get-R5DockerInfo); Warden (Get-R5WardenState:
       first run needs source r4-v1 or r4-restore); runtime processes while S11 is not done (2026-10-11 17:22 fix: S2 held on
       processes no cutover script recognised): Get-R5ProcessList classified by Get-R5RuntimePresence exactly as the cutover
       scripts' Get-ControllerPresence (stop-warden-r4.ps1, stop-warden-r5.ps1, retarget-warden-r5.ps1: same patterns, same
       order, the union of their runtime roots); any unclassified rooted process, or a python process whose image and command
       line cannot be read (S0 runs elevated), -> STOP listing pid, parent and command line, nothing changed (they would hold
       the S2 stop, the S11 cutover and every rollback). GUI MCP clients (cochem_pipeline mcp ..., the reviewed cochem_mcp
       bridge form), controllers and the two observer recorders pass; free disk >= 5 GB; PyPI (Test-R5PackageIndex) while r5 is
       not installed. Earlier attempts (Get-R5EarlierSittings, 2026-10-11 v3 fix): every other R5Sitting4.2.7-windows-20261011-vK
       is reported with its sitting-end.json outcome and the held records left in the child roots it touched (state.
       touched_roots; v2 left 14 one-shot tasks registered but never run, a staged WardenConfig v1 and the r4 restore it
       started); they never stop S0, because every child of this attempt takes fresh 32-hex names and the next free vN
       namespaces. Only an attempt without sitting-end.json stops S0 (it may still run in another window; rerun that attempt).
       Writes S00-receipt.json once (base source = the Warden action found at the first run).
   S1  install-stopped-runtime-r5.ps1 -Manifest W\stopped-runtime-r5-source-manifest.json -ManifestSha256 <freeze sha>
       (plan: exit 0, mode READ_ONLY_PLAN, holds []) then the same + -Apply (exit 0, mode FRESH_STOPPED_RUNTIME_READY);
       gate B\Pipeline4.2.7-windows-20261011-r5\install-after.json: schema cochem-stopped-runtime-update/1, mode
       FRESH_STOPPED_RUNTIME_READY, source_manifest_sha256 == freeze sha, reviewed_repairs/_sha256 == the manifest's 13,
       verified_unchanged 153, tasks_changed 0, holds [], verification.r5_repairs_installed true, installed_repairs_verified
       true, runtime_bindings pyvenv_sha256 0c2b1a15... and venv_python_sha256 560b9ef7..., no install-held.json (audit F7,
       mirroring retarget-warden-r5.ps1 Assert-R5InstalledBindings). An existing install-after
       that passes the gate is accepted without running the installer. Receipt S01 (install_after_sha256).
       Failure (plan refused, holds, build held - install-held.json failed_stage is reported - or the gate): SERIES-STOP +
       R4-RESTORE from the state reached (Commander decision): r4-v1 today -> retarget-warden-r5.ps1 -Target r4 -Attempt vM
       -Apply -Start (pin-checked; Docker must answer), which brings the down Warden up on r4; 'none' when r4 still runs.
   S2  base source r4-v1 with an instance or Enabled: stop-warden-r4.ps1 -Apply -Attempt vN (B\WardenStop4.2.7-windows-
       20261010-r4-vN); exit 0 and status WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED or
       WARDEN_ALREADY_STOPPED_AND_DISABLED. It also runs for an enabled idle task (A1 today): the S3 and S5-S8 children refuse
       an enabled Warden task. r4-v1 disabled with 0 instances: skipped. Base source r4-restore vM: stop-warden-r5.ps1 -Apply
       -Attempt vK -RetargetTarget r4 -RetargetAttempt vM (WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED or
       WARDEN_ALREADY_STOPPED_CLEAN_NOOP; today's v3 base: the restored r4 runs, so this is the first live End - idle proof,
       End, exit wait, disable). Refused with "nothing was changed" while r4 runs: STOP, no restore, the attempt stays
       rerunnable; otherwise STOP + R4-RESTORE (s2_attempted and s2_stop_attempt are set before the child, so a stop held after
       its root exists is classified from WardenStop...-vK\stop-held.json: 'blocked' with that phase for a restored r4 base).
   S3  12 x check-worker-native-auth-status-six-r4-v1.ps1 -Slot slotN -Provider claude|codex -Stage before -Attempt <hex>
       -Apply, strictly sequential (claude slot1-6, codex slot1-6); exit 0 + decision REUSE_VERIFIED_SESSION or
       ATTENDED_LOGIN_REQUIRED, anything else HOLD (recorded). Any ATTENDED_LOGIN_REQUIRED: ONE Read-R5YesNo; Y -> per provider
       Invoke-R5Attended login-six-workers-status-first-r4-v1.ps1 -Provider claude|codex -Attempt <new hex> -Apply -Interactive
       (it re-checks every slot, runs the reviewed login child - Codex InstallGuard login_pipeline_worker.ps1 -InstallRoot r4,
       Claude login_pipeline_worker_interactive_r3_v6.ps1 - and the -Stage after check); verified = exit 0 and
       B\NativeAuthSix4.2.7-windows-20261011-r4-v1-<hex>-<provider>\series-complete.json all_slots_reuse_verified true.
       Decline or failure is recorded; S3 never stops the sitting.
   S4  recorded no-op (A5: NF-1 dropped).
   S5  Gemini attempt only: agy-status-capture-r4-v1.ps1 -Slot slot1 -Stage signed-out -Attempt Gx -Apply; exit 0, gate.passed
       true, decision COMPLETE and login_mode.mode print|tui, else Gemini held (S6-S8 skipped).
   S6  attended: Invoke-R5Attended login-six-workers-status-first-r4-v1.ps1 -Provider gemini -LoginMode <mode> -Attempt Gx
       -Apply -Interactive; exit 0 and B\NativeAuthSix4.2.7-windows-20261011-r4-v1-Gx-gemini\series-complete.json (status
       SIX_CONFIGURED_WORKERS_SUBSCRIPTION_AUTHENTICATION_VERIFIED, all_slots_reuse_verified true, selected_workers_verified 6);
       exit 20 = orderly pause -> Gemini held; any other result -> Gemini held.
   S7  agy-status-capture-r4-v1.ps1 -Slot slot1 -Stage signed-in -Attempt Gx -Apply; exit 0 + gate.passed, else held.
       capture root = JSON target_root.
   S8  agy-isolation-evidence-r4-v1.ps1 -Slot slot1 -EffortNullSlug <slug> -Attempt Gx -Apply, then
       agy-isolation-evidence-r4-v1.ps1 -StageOnly -Attempt Gx -Apply; each exit 0 = passed, 10 = held, other = held.
   S9  Invoke-R5Python -PinName build-pipeline-config-r5-candidate.py: <r5 python> -I -B W\build-pipeline-config-r5-candidate.py
       --commissioned B\Pipeline4.2.7-windows-20261009-r4\pipeline.json [--login-root <S6 root> --capture-root <S7 root>
       --isolation-root <S8 root> [--stage-root <S8 stage root, only if not <S8 root>-stage>]] --mode attempt|held
       --out-dir <sitting root>\S09-build-<stamp>-a; checks per INTERFACES-CONFIG (decision.commissioned_sha256 and
       commissioned_pin both == 135cd9ec, held iff candidate == those bytes); any failure -> ONE retry --mode held in
       ...-b; then stage-pipeline-config-r5-v1.ps1 -BuildDirectory <dir> -Attempt vC (last line status PLAN_OK) and the same
       + -Apply (STAGED or ALREADY_STAGED_IDENTICAL; staged_sha256 == decision.candidate_sha256; outcome == decision.outcome).
       A staging failure of a GEMINI_CONTRACT build: Gemini held, the builder runs --mode held in <sitting root>\S09-build-
       <stamp>-held (same checks) and the stager stages it to the next vC (audit F3). Builder failure twice, or a staging
       failure of a held build: STOP + R4-RESTORE.
   S10 run-upgrade-preview-r5-v1.ps1 -Attempt <hex> -CandidateSha256 <staged_sha256> -Candidate <staged_path> (plan, exit 0)
       then + -Apply; exit 0 and B\UpgradePreview4.2.7-windows-20261011-r5-v1-<hex>\preview-summary.json decision PASSED with
       top-level install_after_sha256 == the S1 sha. Failure with a GEMINI_CONTRACT configuration: Gemini held, the builder
       runs --mode held in <sitting root>\S10-build-<stamp>-held, the stager stages it to the next vC and S10 runs once more
       with the new staged_sha256/path (audit F3). Failure of a held configuration: STOP + R4-RESTORE.
   S11 Docker must answer (else STOP without restore: start Docker Desktop and rerun). S11-intent.json, then
       retarget-warden-r5.ps1 -Target r5 -Config <staged_path> -Attempt vR [-SourceAttempt vM -StopAttempt vK when the base
       source was r4-restore] -Apply -Start; exit 0, status WARDEN_R5_RUNNING_HEALTH_VERIFIED, and the start receipt (result
       receipt_path == B\WardenRetarget4.2.7-windows-20261011-r5-vR\start-receipt.json, bytes == receipt_sha256) records
       the two-phase start first (trigger_enabled_before false, trigger_enabled_after true, task_xml_started_sha256 ==
       task_xml_sha256), then install_after_sha256 == the S1 sha, config_sha256 == the S9 staged_sha256 and config_mode ==
       decision.outcome (audit F3). Failure: STOP + R4-RESTORE for the state reached: an F3 mismatch takes r5-started; a
       receipt without the two-phase start is 'blocked' (stop-warden-r5 refuses it). r5 counts as running (verified) only
       after these checks pass (audit F2).
   S12 Invoke-R5HealthCheck: Invoke-R5Control '/health' every >= 10 s for up to 120 s: service_identity SYSTEM, source_root ==
       r5 .venv\Lib, active [], quarantined_slots {}, routing.execution_quarantines [] (hard); knowledge.ready and
       authority_matches_capture true, components.warden_controller.admission_ready true (awaited). routing.holds is reported.
       Failure: STOP + R4-RESTORE (stop-warden-r5 first). One exception (Test-R5CpuOnlyPause, DIAG-NEXT 2026-10-11): when
       admission_ready is the only open item after 120 s, recovery_hold is false and every warden_controller.admission_reasons
       entry is the 5% CPU budget (r5 keeps r4's CPU budget; r4 also pauses on its 50 MiB memory budget), r5 is kept: receipt
       HEALTH_VERIFIED_ADMISSION_PAUSED_CPU, and S13 waits for admission and defers as below. The fallback check alike.
   S13 Wait-R5Admission: '/health' every 15 s until admission_capacity > 0 (host-governor pauses waited up to 600 s; still
       paused -> acceptance DEFERRED, r5 kept). Then ONE Invoke-R5Control '/preflight' @{workflow_id} and '/workflow/<id>'
       every 10 s up to 300 s; BLOCKED routing_operator_limit -> one resubmit with a new id. Gemini contract: route gemini,
       COMPLETED, reported_model == route model, native_reported_model == binding.reports, no integration_verification_hold;
       otherwise Invoke-R5GeminiFallback (fallback-intent.json; stop-warden-r5.ps1 -Apply -Attempt vK -RetargetTarget r5
       -RetargetAttempt vR; retarget-warden-r5.ps1 -Target r5 -Config B\WardenCommissioning4.2.7-windows-20261007-r3-v1\
       pipeline.json -Attempt vR2 -SourceAttempt vR -StopAttempt vK -Apply -Start; its start receipt must bind the S1
       install_after_sha256, config_sha256 == the commissioned 135cd9ec and the two-phase start; S12 check; preflight again;
       a failing fallback start restores r4 by the same state table with vN = vR2). Held/skip mode or after the fallback:
       COMPLETED on claude/codex passes; BLOCKED (routing_operator_limit twice) or TIMEOUT -> acceptance DEFERRED, r5 kept
       (audit F4: r4 shares the same quota); FAILED, a refused submission or another provider -> STOP + R4-RESTORE.
   S14 fix-proof tail (soft, unattended, skipped by -SkipFixProof or without a passed acceptance): Invoke-R5Control '/submit'
       (chapter_count 2) and '/coding/submit' (project windows-acceptance), polled every 15 s (planning <= 20 min, coding
       first CODE_PLAN <= 15 min), /health sampled for components.warden_controller.admission_ready (never the bare 'ready').
       Results are recorded; never a restore.
   R4-RESTORE  Invoke-R5Restore (Docker must answer first). Get-R5CutoverState classifies the r5 attempt vN reached (the S11
       attempt, or the fallback attempt) in this order; vM is a fresh WardenRetarget r4 namespace, vK a fresh WardenStop r5 one:
       none                 r4 never stopped and still running: no call.
       base r4-v1           no r5 task update happened: retarget-warden-r5.ps1 -Target r4 -Attempt vM -Apply -Start
       base r4-restore vB   retarget-warden-r5.ps1 -Target r4 -Attempt vM -SourceAttempt vB -StopAttempt vK(S2) -Apply -Start
       r5-retarget-held     (1) retarget-held.json MUTATION_READBACK (incl. a logon-trigger user readback mismatch), or
                            retarget-intent.json with no retarget receipt and no held record, decided by the live task action
                            read now (audit F1): == the intent's action_after -> retarget-warden-r5.ps1 -Target r4 -Attempt vM
                            -SourceAttempt vN -Apply -Start; == its action_before (the update never took effect; only when the
                            hold has no readable readback, readback_readable not true, or for an intent-only root) -> the
                            previous state's restore (from r4-v1: -Target r4 -Attempt vM -Apply -Start, NO -SourceAttempt);
                            anything else, or an unreadable task or intent -> blocked.
       r5-started           (5) start receipt that passes the two-phase checks (F3 mismatches land here):
                            stop-warden-r5.ps1 -Apply -Attempt vK -RetargetTarget r5 -RetargetAttempt vN, then
                            retarget-warden-r5.ps1 -Target r4 -Attempt vM -SourceAttempt vN -StopAttempt vK -Apply -Start
       r5-never-started     (2) start-held.json held_before_run true (C-F7: incl. a Run that threw with no instance, which also
                            records run_requested true), or a retarget receipt never started:
                            retarget-warden-r5.ps1 -Target r4 -Attempt vM -SourceAttempt vN -Apply -Start
       r5-start-interrupted (3) start-held.json with held_before_run false (every after-Run hold: interrupted, or held before
                            or after its health gate; the retarget records stop_recovery_allowed true for each and the stop
                            binds START_HELD_BEFORE_HEALTH_GATE / START_HELD_AFTER_HEALTH_GATE / START_INTERRUPTED_HELD), or
                            start-intent.json with neither start-held.json nor a start receipt (crashed):
                            stop-warden-r5.ps1 -Apply -Attempt vK -RetargetTarget r5 -RetargetAttempt vN -RecoverInterruptedStart,
                            then retarget-warden-r5.ps1 -Target r4 -Attempt vM -SourceAttempt vN -StopAttempt vK -Apply -Start
       r5-stopped           r5 vN already stopped by stop vK (the fallback stop): the retarget call only
       blocked              (4) no call; STOP, 'R4-RESTORE NOT DONE: no automatic restore: ...' for owner/agent review: a start
                            receipt that fails the two-phase checks ('the r5 vN start receipt does not record the two-phase
                            start (stop-warden-r5 would refuse it); owner/agent review'); a held stop-warden-r5 (stop-held.json;
                            no defined recovery), the S2 stop of a restored r4 included (Get-R5UnstoppedRestoreDetail names its
                            attempt and phase: r4 may still run, nothing was killed); an unreadable held record; a held/intent-
                            only retarget whose live action is neither the intended nor the previous one (or cannot be read).
       A retarget held in another phase (ROOT, PREPARATION, MUTATION_PREPARATION: the task update never ran) or a root without
       intent falls back to the previous state (base, or r5-stopped after the fallback stop). Gate: exit 0 and status
       WARDEN_R4_RESTARTED_HEALTH_VERIFIED.
   Final console block (Write-R5Outcome, 'OUTCOME (<phase>)'): Claude / Codex (n/6 verified, signed out, unclear); Gemini
   (ACTIVE / HELD - <stage>: <reason> / SKIPPED / CONFIGURED, NOT YET PROVEN only when r5 runs a verified GEMINI_CONTRACT
   config, else NOT DEPLOYED - the sitting ended before r5 ran the Gemini configuration); Warden (r5 RUNNING (health verified[;
   admission was paused at S12|fallback by the 5% Warden CPU budget alone]) on DONE; after a STOP the live task is read
   again (audit F2): r4 RESTORED, r5 not installed: <reason> [S1] | r4 RESTORED
   and running (r5 not deployed) | r5 RUNNING, NOT VERIFIED[ (rollback stop refused) | (no automatic rollback) | (rollback
   not done)] | r5 task registered but NOT RUNNING - ... | r4 still running (never stopped) | r4 RUNNING (not restored by this
   sitting) - ... | RUNNING an unrecognized task action - ... | pipeline DOWN as before this sitting [S1 restore failed] |
   DOWN as before this sitting (...) | DOWN - the agent reviews the log | UNKNOWN - the Warden task could not be read (...));
   Reboot (SAFE only on DONE with r5 verified; NOT VERIFIED - ... when a live r5 task was not verified; NOT reboot-safe (r4
   has no logon trigger)); Holds (S12 routing.holds count and kinds, reported not gated); Accept; FixProof; Held (every
   *held*.json in the child roots this sitting used, S1-S14); Log; Sitting root. #>
[CmdletBinding()]
param([ValidatePattern('^v[0-9]{1,3}$')][string]$Attempt='v1',[ValidateSet('attempt','skip')][string]$Gemini='attempt',
      [ValidateSet('gemini-3.8-flash-low','gemini-3.8-flash-medium','gemini-3.8-flash-high')][string]$EffortNullSlug='gemini-3.8-flash-low',
      [switch]$Apply,[switch]$SkipFixProof)
$ErrorActionPreference='Stop'
$script:Workspace=$PSScriptRoot
$script:Base='C:\Program Files\CoChem'
# ---- PIN TABLE (generated by refresh-r5-sitting-pins.py; edit only through it) ----
$script:Pins=@{
    'install-stopped-runtime-r5.ps1'='1f8041bcbab8252f52e5eb585d5fa66c8e9398c8d8bb901a5760a5503fd4e10a'
    'check-worker-denials.ps1'='1576882fe655d27894aa6f9da25a14ae4ddd08540c865d51cc43b26fa3dd6f9d'
    'stopped-runtime-r5-source-manifest.json'='5d8d337baebbc1e4ac29439d418333ab41c0999eb8c0ef8b02acee66850a3045'
    'stopped-runtime-r5-freeze-receipt.json'='5bdd2ad2fdd46ae4451b34a57641cf542b56e1ab83d379ce1048a5eb44b30ceb'
    'stop-warden-r4.ps1'='43fc386b1984447c1d5304a8297932c8f825735562b5dbc5dc3f23a211adbe7e'
    'stop-warden-r5.ps1'='b5920f379cee10eba101b87adb40b6a500d1bf5f29300f3e56a025182ee407a9'
    'retarget-warden-r5.ps1'='991703ab10b7bf280fb092ec984e79d1095379070857e7c2859d0a5ba0c0dee7'
    'backup-private-databases-r4.py'='f00ad064215d1a689f1355a18da9f159b16d45699507975de957a4cb832a0f8b'
    'check-worker-native-status-r3.ps1'='18f58ebb448d8a0c6329dd187d4a9a27fa9cbe942cd05e906bb7aabc67e787a7'
    'protected-code-inspection-v4.ps1'='5c01543cbb8b8d64b2b9f1bab4a13f87f8ff9e1ab3e82dfb6fc547144c77b95d'
    'register-stopped-warden-r3.ps1'='eccc593f36cbf488a54775b4343bcf3cf8b261b7cd81e5536fb7f2f18466a198'
    'retarget-warden-r4.ps1'='8ee6b412f6be176dfac7c2c1b2340f1973e08358c7d22da6d4515e79f0327a4e'
    'check-worker-native-auth-status-six-r4-v1.ps1'='34612ac49eb2e455076a01607634f21d4f0b284714ef07d5e614146a1a9a7a85'
    'worker-native-auth-status-six-r4-v1.py'='45681477194d97b144e8ee4505d4364d73d58aaef19c8428c846df642c834839'
    'login-six-workers-status-first-r4-v1.ps1'='953f49d3aa8e20b4adc7eb38d91346f2b421ced9e70732e6cd6c153f0f1cd15f'
    'login-six-workers-status-first-r3-v6.ps1'='9e45266bdccbaa7765245eb23091211b669c92504c374dd7ded6eab0699a4665'
    'login_pipeline_worker_interactive_r3_v6.ps1'='837f567c5cae00d30620e313d746df6acf98259c9ffa1ef43ebc217b7cf9c46d'
    'claude-session-history-v6.ps1'='36cac78f54d9a9370991df3a83bfdf36144e7e9f8ed2dabe4da3105e5edd4636'
    'claude-code-input-v6.ps1'='74c41bf1b118a62d2decae8d7d9c2ffeb2c19d977033435267f8155fac1f7bf9'
    'worker_claude_login_bridge_r3.py'='b5bbede85ceb099460c6d6634f09a361a9b6617740eb082ab8d3bf5931260c73'
    'worker-native-status-r3.py'='c3c3069f097040442777ea30a6296abc506783968e381611fce26e20c7c4aed5'
    'login_pipeline_worker_interactive_agy_r4_v1.ps1'='381fb8daec6999d16e75ab163f28d0dda6459b1b44f9695962cf43213cedcb60'
    'worker_agy_login_bridge_r4_v1.py'='4074878f100ae59b804c95bd97b3280ccaa09f919ffaa365a3e2c6985045b8d9'
    'agy-session-history-r4-v1.ps1'='4e86b712314e2a6a8ea9f13e1dfcc9e65dda4035d2895b8043fbf6ceed0424d4'
    'agy-status-capture-r4-v1.ps1'='03198a30d359e59339b95744d21b92964f38d7e996ddd74bf8d2315cddfe03fa'
    'agy_status_capture_r4_v1.py'='ce103aad0f9dae042677ec61c2b16eb5512e9a24f5fca65bc97f4570bb884038'
    'agy-isolation-evidence-r4-v1.ps1'='bd87ad3128e6d63e141c23aff15d7fe6b761c88aa6477bf48fe5232df800e326'
    'agy_isolation_evidence_r4_v1.py'='767f03af910fb137bd9a08ed82390f08878d802c45cfb9689eadb5ca44af8d60'
    'cochem-inference-only.agent.md'='5c0082d70d073263a56d748a46187008968c070d0efc7d5b7612c2fd61d11810'
    'build-pipeline-config-r5-candidate.py'='ab01d82486ec54ee8eefa17542d6b58d9811cb94a96a5ceef1f439f0599a19e8'
    'stage-pipeline-config-r5-v1.ps1'='1066f6c3d9fb5be6143075ddf72206af56f64a8240b7e49fc8f0625d32e3c993'
    'run-upgrade-preview-r5-v1.ps1'='98a8130a6757617d9b69def0e4d46d69421422a502e30ab8f2488522b50daa7f'
    'run_upgrade_preview_r5_v1.py'='71e0383272057ab7be59f339a9dcb0c57e74ac5329f46d575cc49cde62816051'
}
# ---- END PIN TABLE ----

# ================================================================== paths, output, stop
function Initialize-R5Paths {
    # Every path the sitting reads or writes derives from $script:Base or $script:Workspace (the harness redirects both).
    $script:Started=Get-R5Now;$script:Stamp=$script:Started.ToString('yyyyMMdd-HHmmss')
    $script:Log=Join-Path $script:Workspace ('r5-sitting-'+$script:Stamp+'.log')
    $script:PsExe=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $script:SittingRoot=Join-Path $script:Base ('R5Sitting4.2.7-windows-20261011-'+$script:Attempt)
    $script:R5Root=Join-Path $script:Base 'Pipeline4.2.7-windows-20261011-r5'
    $script:R5Python=Join-Path $script:R5Root '.venv\Scripts\python.exe';$script:R5SourceRoot=Join-Path $script:R5Root '.venv\Lib'
    $script:InstallAfter=Join-Path $script:R5Root 'install-after.json';$script:InstallHeld=Join-Path $script:R5Root 'install-held.json'
    $script:R4Root=Join-Path $script:Base 'Pipeline4.2.7-windows-20261009-r4';$script:R4SourceRoot=Join-Path $script:R4Root '.venv\Lib'
    $script:CommissionedR4Config=Join-Path $script:R4Root 'pipeline.json'
    $script:CommissioningConfig=Join-Path $script:Base 'WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json'
    # The commissioned configuration identity (Gemini held by integration_hold); not a W file pin, so it lives here.
    $script:CommissionedSha256='135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
    # The r5 venv bindings the cutover scripts pin (retarget-warden-r5.ps1 r5PyvenvPin / r5VenvPythonPin); not W file pins (F7).
    $script:R5PyvenvPin='0c2b1a15dcdfe67436882fcf0f8d567d79442bcac41f3b744153c17c21df727d'
    $script:R5VenvPythonPin='560b9ef7d856608ab8da02ded2dc8a1951ad1f424c382c0ec6a698874165a18e'
    # The only port and token file the owner-writable client config may name (the cutover scripts' Assert-ClientConfig, F6).
    $script:ControlPort=47824;$script:TokenFile='C:\Users\ansac\CoChem427\controller.token'
    $script:ClientConfig='C:\Users\ansac\CoChem427\pipeline-client-r3.json'
    # S0 runtime-process precheck: the classification of the cutover scripts' Get-ControllerPresence, literal for literal
    # (test_r5_sitting_static.py compares these with stop-warden-r4.ps1, stop-warden-r5.ps1 and retarget-warden-r5.ps1), over
    # the union of their runtime roots: every Pipeline4.2.7-windows-* root (stop-warden-r5 runtimePrefix; r3, r4 and r5 of the
    # other two lie under it) and the Toolchain interpreter (basePythonRoot).
    $script:RuntimeRoots=@((Join-Path $script:Base 'Pipeline4.2.7-windows-'),(Join-Path $script:Base 'Toolchain4.2.7-windows-20261006\Python312'))
    $script:ControllerPattern='cochem_pipeline\s+daemon\b|cochem_supervisor\b|provision-execution\b|cochem-supervisor\b|cochem-pipeline(\.exe)?"?\s+daemon\b'
    $script:ObserverPattern='\\SupervisorObservation4\.2\.7-windows-20261007-r3-v1\\held-supervisor-observation-r3-v1\.py"?\s+--observe\b|\\ResourceObservation4\.2\.7-windows-20261008-r3-v4\\package\\observe_resources\.py"?\s+--run-observer\b'
    $script:ClientPattern='cochem_pipeline\s+(mcp|health|status|submit|cancel|projects|code|code-status|code-cancel|code-resume|knowledge-\w+)\b'
    $script:BridgeClientPattern='^"[^"]+\\python\.exe" -m cochem_mcp --provider (codex|claude) --config C:\\Users\\ansac\\CoChem427\\bridge\.local\.json\z'
    $script:Manifest=Join-Path $script:Workspace 'stopped-runtime-r5-source-manifest.json'
    $script:FreezeReceipt=Join-Path $script:Workspace 'stopped-runtime-r5-freeze-receipt.json'
    $script:ExecutionImage='sha256:d9d3e8644b6fc407c7d5ee7151fcb22470d74b8c14a4e6ef8cf8e9acb62877a2'
    # Child namespaces (prefix + vN under $script:Base); dates are fixed inside each child.
    $script:NsStopR4='WardenStop4.2.7-windows-20261010-r4-';$script:NsStopR5='WardenStop4.2.7-windows-20261011-r5-'
    $script:NsRetargetR5='WardenRetarget4.2.7-windows-20261011-r5-';$script:NsRetargetR4='WardenRetarget4.2.7-windows-20261011-r4-'
    $script:NsConfig='WardenConfig4.2.7-windows-20261011-r5-'
    $script:ControlSnippet="import sys,json,base64;from cochem_pipeline.service import ControlClient;c=json.loads(open(sys.argv[1],encoding='utf-8-sig').read());d=None if sys.argv[3]=='-' else json.loads(base64.b64decode(sys.argv[3]).decode('utf-8'));r=ControlClient(int(c.get('port',47824)),c['token_file']).call(sys.argv[2],d);sys.stdout.write(json.dumps(r,ensure_ascii=True)+chr(10))"
    $script:R5LastControlError=''
    $script:R5Done=@{}
    $script:R5=[ordered]@{schema='cochem-r5-sitting-state/1';attempt=$script:Attempt;gemini=$(if($script:Gemini -ceq 'skip'){'skip'}else{'attempt'});gemini_reason=$null;
        effort_null_slug=$script:EffortNullSlug;manifest_sha256=$null;earlier_sittings=$null;warden_initial=$null;base_source=$null;s2=$null;s2_attempted=$false;s2_stop_attempt=$null;s2_done=$false;install_after_sha256=$null;
        sessions=$null;gemini_attempt=$null;login_mode=$null;s6_root=$null;s7_root=$null;s8_root=$null;s8_stage_root=$null;
        decision_outcome=$null;decision_mode=$null;chosen_bindings=$null;build_dir=$null;config_attempt=$null;staged_path=$null;staged_sha256=$null;
        preview_attempt=$null;r5_attempt=$null;r5_running=$false;r5_stopped=$null;r5_stop_held=$false;fallback=$false;
        acceptance=$null;preflight=$null;fix_proof=$null;restore=$null;restore_kind=$null;restore_ok=$null;restore_message=$null;
        routing_holds=$null;health_note=$null;touched_roots=@();stop_reason=$null;pending_restore=$false;current_stage=$null}
    $script:R5Initialized=$true
}

function Say {param([string]$Text,[string]$Color='')
    $line='['+(Get-R5Now).ToString('HH:mm:ss')+'] '+$Text
    if($Color){Write-Host $line -ForegroundColor $Color}else{Write-Host $line}}

function Stop-R5Series {param([string]$Reason,[switch]$Restore)
    # Every planned stop is 'SERIES-STOP: <reason>'; -Restore asks Invoke-R5Series to run Invoke-R5Restore first.
    if($Restore){$script:R5['pending_restore']=$true}
    throw ('SERIES-STOP: '+$Reason)}

# ================================================================== pins
function Get-R5FileSha256 {param([string]$Path,$Stream=$null)
    # sha256 of a file by path, or of an already open stream (Assert-R5Pin's deny-write handle; rewound afterwards).
    if($null -ne $Stream){
        $sha=[Security.Cryptography.SHA256]::Create()
        try{$digest=[BitConverter]::ToString($sha.ComputeHash($Stream)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
        $Stream.Position=0;return $digest}
    $file=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try{$sha=[Security.Cryptography.SHA256]::Create();try{[BitConverter]::ToString($sha.ComputeHash($file)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}}
    finally{$file.Dispose()}}

function Assert-R5Pin {param([string]$Name)
    # The single pin check: every child script, helper and the builder pass through here immediately before use. The file is
    # opened behind a deny-write/delete handle (FileShare.Read), hashed from that handle, and returned with the open handle:
    # the launcher disposes it only after the child has exited, so the bytes that run are the bytes verified (audit F6).
    if(-not $script:Pins.ContainsKey($Name)){Stop-R5Series ('No reviewed pin exists for '+$Name+'; nothing was started.')}
    $expected=[string]$script:Pins[$Name]
    if($expected -cnotmatch '^[a-f0-9]{64}$'){Stop-R5Series ('The pin of '+$Name+' is a placeholder ('+$expected+'); the agent must run refresh-r5-sitting-pins.py after the file exists.')}
    $path=Join-Path $script:Workspace $Name
    if(-not (Test-Path -LiteralPath $path -PathType Leaf)){Stop-R5Series ('Pinned file is missing: '+$path)}
    $stream=$null
    try{$stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)}
    catch{Stop-R5Series ('Pinned file cannot be held for verification: '+$path+' ('+$_.Exception.Message+')')}
    $actual=$null
    try{$actual=Get-R5FileSha256 -Stream $stream}catch{$stream.Dispose();throw}
    if($actual -cne $expected){$stream.Dispose();Stop-R5Series ('Pinned file changed since review: '+$Name+' (expected '+$expected+', found '+$actual+'). Nothing was started from it.')}
    [pscustomobject]@{path=$path;stream=$stream}}

function Get-R5PinDrift {
    # Names whose pin is a placeholder, whose file is missing or whose bytes differ (S0 and the plan; no stop here).
    $drift=@()
    foreach($name in @($script:Pins.Keys|Sort-Object)){
        $expected=[string]$script:Pins[$name];$path=Join-Path $script:Workspace $name
        if($expected -cnotmatch '^[a-f0-9]{64}$'){$drift+=($name+' (placeholder)');continue}
        if(-not (Test-Path -LiteralPath $path -PathType Leaf)){$drift+=($name+' (missing)');continue}
        try{if((Get-R5FileSha256 $path) -cne $expected){$drift+=($name+' (changed)')}}catch{$drift+=($name+' (unreadable)')}}
    if(-not $script:Pins.Count){$drift+='(empty pin table)'}
    $drift}

# ================================================================== launch wrappers
function Invoke-R5Native {param([string]$Executable,[string[]]$Arguments)
    # Judge native commands by exit code; PS 5.1 would otherwise turn stderr into errors. A launch failure is a result.
    $previous=$ErrorActionPreference;$previousEncoding=[Console]::OutputEncoding;$global:LASTEXITCODE=$null;$lines=@();$code=$null
    try{$ErrorActionPreference='Continue';try{[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)}catch{}
        $lines=@(& $Executable @Arguments 2>&1|ForEach-Object {[string]$_});$code=$global:LASTEXITCODE}
    catch{$code=$null;$lines=@('invoke failed: '+$_.Exception.Message)}
    finally{$ErrorActionPreference=$previous;try{[Console]::OutputEncoding=$previousEncoding}catch{}}
    [pscustomobject]@{code=$code;text=($lines -join "`n")}}

function Invoke-R5Child {param([string]$Label,[string]$Name,[string[]]$Arguments)
    # Unattended reviewed child: pin check first (its deny-write handle stays open until the child exits), then a separate
    # Windows PowerShell judged by its exit code.
    $pin=Assert-R5Pin $Name
    try{
        Say ('--- '+$Label)
        $result=Invoke-R5Native $script:PsExe (@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$pin.path)+@($Arguments))
    }finally{$pin.stream.Dispose()}
    if($result.text){Write-Host $result.text}
    $result}

function Invoke-R5Attended {param([string]$Name,[string[]]$Arguments)
    # Attended reviewed child: pin check first (handle held until the child exits), then the same console (never captured or
    # redirected); returns the exit code.
    $pin=Assert-R5Pin $Name
    try{
        $parts=@('-NoProfile','-ExecutionPolicy','Bypass','-File',$pin.path)+@($Arguments)
        $line=(@($parts|ForEach-Object {if($_ -match '[\s"]'){'"'+$_+'"'}else{$_}}) -join ' ')
        # Touch Handle before waiting so Windows PowerShell 5.1 keeps the exit code of a -NoNewWindow child.
        $process=Start-Process -FilePath $script:PsExe -ArgumentList $line -NoNewWindow -PassThru
        try{$null=$process.Handle}catch{};$process.WaitForExit()
        $code=[int]$process.ExitCode
    }finally{$pin.stream.Dispose()}
    $code}

function Invoke-R5Python {param([string[]]$Arguments,[string]$PinName='')
    # The installed r5 interpreter; a W script it runs is pin-checked first (-PinName) and held until the process exits.
    $pin=$null;if($PinName){$pin=Assert-R5Pin $PinName}
    try{Invoke-R5Native $script:R5Python $Arguments}finally{if($null -ne $pin){$pin.stream.Dispose()}}}

function Invoke-R5Control {param([string]$Operation,$Data=$null)
    # One ControlClient call (GET without data, POST with data) through the r5 interpreter; JSON travels base64-encoded
    # because Windows PowerShell 5.1 mangles embedded quotes in native arguments. Returns the parsed reply or $null.
    $encoded='-'
    if($null -ne $Data){$encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($Data|ConvertTo-Json -Compress -Depth 8)))}
    # Audit F6, mirroring the cutover scripts' Assert-ClientConfig: the owner-writable client config is trusted only for port
    # $script:ControlPort and token file $script:TokenFile, and is held behind a deny-write handle for the whole call.
    # Any doubt returns $null with the reason in $script:R5LastControlError; no ControlClient call is made.
    $config=$null
    try{$config=[IO.File]::Open($script:ClientConfig,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)}
    catch{$script:R5LastControlError=('the client config '+$script:ClientConfig+' cannot be read: '+$_.Exception.Message+'; no controller call was made');return $null}
    try{
        $value=$null
        try{$reader=[IO.StreamReader]::new($config,[Text.Encoding]::UTF8,$true,4096,$true);try{$value=$reader.ReadToEnd()|ConvertFrom-Json}finally{$reader.Dispose()}}catch{$value=$null}
        $port=Get-R5Member $value 'port'
        if($null -eq $value -or -not (($port -is [int] -or $port -is [long]) -and [long]$port -eq $script:ControlPort) -or [string](Get-R5Member $value 'token_file') -cne $script:TokenFile){
            $script:R5LastControlError=('the client config '+$script:ClientConfig+' must name port '+$script:ControlPort+' (a JSON integer) and token file '+$script:TokenFile+'; no controller call was made');return $null}
        $result=Invoke-R5Python @('-I','-B','-X','utf8','-c',$script:ControlSnippet,$script:ClientConfig,$Operation,$encoded)
    }finally{$config.Dispose()}
    if($result.code -ne 0){$script:R5LastControlError=('exit '+$result.code+': '+([string]$result.text).Trim());return $null}
    $value=Get-R5JsonTail $result.text
    if($null -eq $value){$script:R5LastControlError='the controller reply was not JSON'}
    $value}

function Read-R5YesNo {param([string]$Question)
    foreach($try in 1..3){$answer=([string](Read-Host ($Question+' [Y/N]'))).Trim()
        if($answer -match '^(?i:y|yes)$'){return $true};if($answer -match '^(?i:n|no)$'){return $false}}
    $false}

function Request-R5Attention {param([string]$Text)
    Write-Host '';Write-Host ('>>> YOUR ATTENTION: '+$Text) -ForegroundColor Yellow
    try{[Console]::Beep(880,250);[Console]::Beep(880,250)}catch{}}

function Wait-R5Seconds {param([int]$Seconds)Start-Sleep -Seconds $Seconds}
function Get-R5Now {Get-Date}
function New-R5HexAttempt {do{$value=[Guid]::NewGuid().ToString('N')}while($value -ceq ('0'*32));$value}

# ================================================================== host probes (read-only)
function Assert-R5OwnerShell {
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    if(-not [Security.Principal.WindowsPrincipal]::new($identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or $identity.Name -cne 'AETHERDESK\ansac' -or $env:COMPUTERNAME -cne 'AETHERDESK'){
        Stop-R5Series 'Run this in Windows PowerShell started with "Run as administrator" as AETHERDESK\ansac.'}
    if($PSVersionTable.PSEdition -ne 'Desktop' -or -not [Environment]::Is64BitProcess){Stop-R5Series 'Use 64-bit Windows PowerShell 5.1: the plain "Windows PowerShell" Start entry, not "(x86)" and not PowerShell 7.'}}

function Get-R5ListenerCount {param([int]$Port)
    # Fail closed: only the cmdlet's own no-match error means nothing listens; -1 = unknown.
    try{return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop).Count}
    catch{if($_.FullyQualifiedErrorId -like 'CmdletizationQuery_NotFound*'){return 0};return -1}}

function Get-R5WardenState {
    # Read-only COM view of CoChem-4.2.7-Warden (elevation needed); nothing is registered, run, ended or changed.
    $state=[ordered]@{readable=$false;enabled=$null;instances=$null;task_state=$null;source='unknown';source_attempt=$null;listening=$null;running=$null;error=$null;
        action_path=$null;action_arguments=$null;action_working_directory=$null}
    try{
        $service=New-Object -ComObject 'Schedule.Service';$service.Connect()
        $task=$service.GetFolder('\').GetTask('CoChem-4.2.7-Warden')
        $state['enabled']=[bool]$task.Enabled;$state.task_state=[int]$task.State;$state.instances=[int]$task.GetInstances(0).Count
        $action=$task.Definition.Actions.Item(1);$arguments=[string]$action.Arguments
        $state.action_path=[string]$action.Path;$state.action_arguments=$arguments;$state.action_working_directory=[string]$action.WorkingDirectory;$state.readable=$true
        if($arguments -match '--queue-launch-output-root'){$state.source='r5'}
        elseif($arguments -match 'queue-restart-20261011-r4-(v[0-9]{1,3})"'){$state.source='r4-restore';$state.source_attempt=$Matches[1]}
        elseif($arguments -match 'queue-retarget-20261010-r4-v1"' -and $arguments -match 'Pipeline4\.2\.7-windows-20261009-r4|WardenCommissioning4\.2\.7-windows-20261007-r3-v1'){$state.source='r4-v1'}
    }catch{$state.error=$_.Exception.Message}
    $state.listening=Get-R5ListenerCount 47824
    $state.running=(([int]$state.instances -gt 0) -or ([int]$state.listening -ne 0))
    [pscustomobject]$state}

function Read-R5Warden {
    # Get-R5WardenState normalized: listening as a count (-1 unknown; a boolean probe counts 0/1), running derived when absent.
    $raw=Get-R5WardenState
    $listening=Get-R5Member $raw 'listening'
    $count=$(if($null -eq $listening){0}elseif($listening -is [bool]){[int]$listening}else{[int]$listening})
    $instances=Get-R5Member $raw 'instances';$running=Get-R5Member $raw 'running'
    if($null -eq $running){$running=(([int]$instances -gt 0) -or ($count -ne 0))}
    [pscustomobject]@{readable=((Get-R5Member $raw 'readable') -eq $true);enabled=(Get-R5Member $raw 'enabled');instances=$instances;task_state=(Get-R5Member $raw 'task_state');
        source=[string](Get-R5Member $raw 'source');source_attempt=(Get-R5Member $raw 'source_attempt');listening=$count;running=[bool]$running;error=(Get-R5Member $raw 'error');
        action_path=(Get-R5Member $raw 'action_path');action_arguments=(Get-R5Member $raw 'action_arguments');action_working_directory=(Get-R5Member $raw 'action_working_directory')}}

function Test-R5LiveAction {param($Action,$Live)
    # An action object {execute, arguments, working_directory} (retarget-intent.json action_before/action_after) equals the live
    # task action, ordinal and exact, field by field (retarget-warden-r5.ps1 Test-ActionObjectEqualsLive).
    $execute=Get-R5Member $Action 'execute';$arguments=Get-R5Member $Action 'arguments';$directory=Get-R5Member $Action 'working_directory'
    ($execute -is [string]) -and ($arguments -is [string]) -and ($directory -is [string]) -and
    ([string]$Live.action_path -ceq $execute) -and ([string]$Live.action_arguments -ceq $arguments) -and ([string]$Live.action_working_directory -ceq $directory)}

function Get-R5DockerInfo {
    # The controller preflight reads these keys from `docker info` as JSON (containers.py); the r5 daemon waits up to 900 s for
    # the engine, but the restore and the retarget health gates need it answering now.
    $candidates=@('C:\Program Files\Docker\Docker\resources\bin\docker.exe');$onPath=Get-Command docker.exe -ErrorAction SilentlyContinue
    if($null -ne $onPath){$candidates+=@($onPath|ForEach-Object {[string]$_.Source})}
    $exe=$null;foreach($candidate in $candidates){if($candidate -and (Test-Path -LiteralPath $candidate)){$exe=$candidate;break}}
    if(-not $exe){return [pscustomobject]@{ok=$false;reason='docker.exe not found; Docker Desktop must be installed and running'}}
    $info=Invoke-R5Native $exe @('info','--format','{{json .}}');$json=$null
    if($info.code -eq 0){$line=@($info.text -split "`n"|Where-Object {$_.Trim().StartsWith('{')})|Select-Object -Last 1;try{if($line){$json=$line|ConvertFrom-Json}}catch{$json=$null}}
    if($null -eq $json){return [pscustomobject]@{ok=$false;reason=('docker info exit '+$info.code+': '+(Get-R5LastLine $info.text))}}
    $problems=@()
    foreach($field in @('OSType','MemoryLimit','SwapLimit','CpuCfsQuota','PidsLimit')){
        if($null -eq $json.PSObject.Properties[$field]){$problems+=($field+' missing');continue}
        $expected=$(if($field -eq 'OSType'){'linux'}else{$true});if(-not ($json.$field -eq $expected)){$problems+=($field+'='+[string]$json.$field)}}
    $options=$(if($null -ne $json.PSObject.Properties['SecurityOptions']){@($json.SecurityOptions)}else{@()})
    if(-not ($options|Where-Object {[string]$_ -match 'seccomp'})){$problems+='no seccomp security option'}
    $image=Invoke-R5Native $exe @('image','inspect',$script:ExecutionImage,'--format','{{.Id}} {{.Os}}')
    if($image.code -ne 0 -or ([string](@($image.text -split "`n"|Where-Object {$_.Trim()})|Select-Object -Last 1)).Trim() -cne ($script:ExecutionImage+' linux')){$problems+='the allowlisted execution image is missing'}
    if($problems.Count){return [pscustomobject]@{ok=$false;reason=('Docker engine does not meet the controller preflight: '+($problems -join ', '))}}
    [pscustomobject]@{ok=$true;reason='Docker engine and execution image: ok'}}

function Test-R5PackageIndex {
    try{[Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12}catch{}
    try{$response=Invoke-WebRequest -Uri 'https://pypi.org/simple/' -Method Head -UseBasicParsing -TimeoutSec 20 -ErrorAction Stop;return ([int]$response.StatusCode -eq 200)}catch{return $false}}

function Get-R5FreeDiskGB {param([string]$Path)
    try{[double]([IO.DriveInfo]::new([IO.Path]::GetPathRoot($Path)).AvailableFreeSpace)/1GB}catch{-1}}

function Get-R5ProcessList {
    # Read-only Win32_Process view (image path and command line), the same query the cutover scripts classify; complete only
    # in an elevated window, as S0 runs. A failed query throws (S0 then stops with nothing changed, as the cutover scripts hold).
    @(Get-CimInstance Win32_Process -ErrorAction Stop|ForEach-Object {
        [pscustomobject]@{pid=[int]$_.ProcessId;parent=[int]$_.ParentProcessId;name=[string]$_.Name;path=[string]$_.ExecutablePath;command=[string]$_.CommandLine}})}

function Get-R5RuntimePresence {param($Processes)
    # The cutover scripts' Get-ControllerPresence classification, in its order: controller-like command lines from any image,
    # then the two observer recorders, then GUI clients and unclassified processes among the rooted ones (image under
    # $script:RuntimeRoots), then python processes whose image and command line cannot be read. Pure: no host access.
    $controllers=@();$observers=@();$clients=@();$unclassified=@();$uninspectable=@()
    foreach($process in @($Processes|Where-Object {$null -ne $_})){
        $path=[string](Get-R5Member $process 'path');$command=[string](Get-R5Member $process 'command');$name=[string](Get-R5Member $process 'name')
        $rooted=$false;if($path){foreach($root in @($script:RuntimeRoots)){if($path.StartsWith($root,[StringComparison]::OrdinalIgnoreCase)){$rooted=$true;break}}}
        $entry=[pscustomobject]@{pid=(Get-R5Member $process 'pid');parent=(Get-R5Member $process 'parent');name=$name;path=$path;command=$command}
        if($command -match $script:ControllerPattern){$controllers+=$entry}
        elseif($command -match $script:ObserverPattern){$observers+=$entry}
        elseif($rooted -and ($command -match $script:ClientPattern -or $command -cmatch $script:BridgeClientPattern)){$clients+=$entry}
        elseif($rooted){$unclassified+=$entry}
        elseif(-not $path -and -not $command -and $name -match '^python(w)?\.exe$'){$uninspectable+=$entry}}
    [pscustomobject]@{controllers=$controllers;observers=$observers;clients=$clients;unclassified=$unclassified;uninspectable=$uninspectable}}

function Format-R5Process {param($Entry)
    # One process for the owner: pid, parent and what the cutover scripts saw (command line, else image, else unreadable).
    $what=$(if($Entry.command){[string]$Entry.command}elseif($Entry.path){[string]$Entry.path+' (no command line)'}else{[string]$Entry.name+' (image and command line unreadable)'})
    'pid '+[string]$Entry.pid+' (parent '+[string]$Entry.parent+'): '+$what}

# ================================================================== JSON and records
function Get-R5JsonTail {param([string]$Text)
    # Children print one JSON document last (the stager prints a pretty document, then a one-line status). Every column-0
    # brace is tried from the LAST one back: the result is the same document as trying from the first (a suffix holding two
    # documents never parses), but the usual case parses at once, so the v2 transcript's caught 'TerminatingError(ConvertFrom-
    # Json): Invalid JSON primitive' lines no longer appear.
    if(-not $Text){return $null}
    $starts=@([regex]::Matches($Text,'(?m)^\{')|ForEach-Object {$_.Index})
    for($index=$starts.Count-1;$index -ge 0;$index--){try{return ($Text.Substring($starts[$index])|ConvertFrom-Json)}catch{}}
    $null}

function Get-R5Member {param($Object,[string]$Path)
    # Dotted lookup that tolerates absent members under StrictMode (PSCustomObject or dictionary); $null when absent.
    # Arrays are unrolled like any PowerShell output: wrap the call in @() to count or iterate.
    $current=$Object
    foreach($part in $Path.Split('.')){
        if($null -eq $current){return $null}
        if($current -is [Collections.IDictionary]){if($current.Contains($part)){$current=$current[$part]}else{return $null};continue}
        if($current -is [Management.Automation.PSCustomObject]){$property=$current.PSObject.Properties[$part];if($null -eq $property){return $null};$current=$property.Value;continue}
        return $null}
    $current}

function Test-R5HasMember {param($Object,[string]$Path)
    # True when every segment of the dotted path exists (the value itself may be empty or $null).
    $current=$Object
    foreach($part in $Path.Split('.')){
        if($current -is [Collections.IDictionary]){if(-not $current.Contains($part)){return $false};$current=$current[$part];continue}
        if($current -is [Management.Automation.PSCustomObject]){$property=$current.PSObject.Properties[$part];if($null -eq $property){return $false};$current=$property.Value;continue}
        return $false}
    $true}

function Get-R5Prop {param($Object,[string]$Name)
    # One member whose name may contain dots or slashes (repair paths, binding keys).
    if($null -eq $Object){return $null}
    if($Object -is [Collections.IDictionary]){if($Object.Contains($Name)){return $Object[$Name]};return $null}
    if($Object -is [Management.Automation.PSCustomObject]){$property=$Object.PSObject.Properties[$Name];if($null -eq $property){return $null};return $property.Value}
    $null}

function Read-R5JsonFile {param([string]$Path)
    if(-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)){return $null}
    try{[IO.File]::ReadAllText($Path)|ConvertFrom-Json}catch{$null}}

function Write-R5Record {param([string]$Name,$Value)
    # CreateNew under the sitting root: a record is never overwritten.
    if(-not (Test-Path -LiteralPath $script:SittingRoot -PathType Container)){$null=New-Item -ItemType Directory -Path $script:SittingRoot -Force}
    $path=Join-Path $script:SittingRoot $Name
    $bytes=[Text.UTF8Encoding]::new($false).GetBytes(($Value|ConvertTo-Json -Depth 12))
    $stream=[IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try{$stream.Write($bytes,0,$bytes.Length);$stream.Flush()}finally{$stream.Dispose()}
    $path}

function Write-R5Receipt {param([string]$Stage,[string]$Status)
    $null=Write-R5Record ($Stage+'-receipt.json') ([ordered]@{schema='cochem-r5-sitting-stage/1';stage=$Stage;attempt=$script:Attempt;status=$Status;
        written_utc=[DateTime]::UtcNow.ToString('o');state=$script:R5})
    $script:R5Done[$Stage]=$true}

function Read-R5Receipt {param([string]$Stage)
    # $null when absent; a receipt that exists but does not verify stops the sitting (it is never overwritten).
    $path=Join-Path $script:SittingRoot ($Stage+'-receipt.json')
    if(-not (Test-Path -LiteralPath $path -PathType Leaf)){return $null}
    $value=Read-R5JsonFile $path
    if($null -eq $value -or (Get-R5Member $value 'schema') -cne 'cochem-r5-sitting-stage/1' -or (Get-R5Member $value 'stage') -cne $Stage -or
       (Get-R5Member $value 'attempt') -cne $script:Attempt -or $null -eq (Get-R5Member $value 'state')){
        Stop-R5Series ('The stage receipt '+$path+' does not verify; preserve it, the agent reviews it before any rerun.')}
    $value}

function Get-R5FreeAttempt {param([string]$Prefix)
    foreach($n in 1..999){$candidate='v'+$n;if(-not (Test-Path -LiteralPath (Join-Path $script:Base ($Prefix+$candidate)))){return $candidate}}
    Stop-R5Series ('No free attempt namespace under '+$Prefix)}

function Add-R5TouchedRoot {param([string]$Path)
    # Child roots this sitting started a child against; Write-R5Outcome lists any *held*.json found in them.
    if($Path -and @($script:R5.touched_roots) -notcontains $Path){$script:R5.touched_roots=@(@($script:R5.touched_roots|Where-Object {$_})+$Path)}}

function Get-R5HeldRecords {
    $found=@()
    foreach($root in @($script:R5.touched_roots|Where-Object {$_})){
        if(Test-Path -LiteralPath $root -PathType Container){$found+=@(Get-ChildItem -LiteralPath $root -Filter '*held*.json' -File -ErrorAction SilentlyContinue|ForEach-Object {$_.FullName})}}
    $found}

function Get-R5EarlierSittings {
    # Read-only view of the OTHER attempts of this sitting (R5Sitting4.2.7-windows-20261011-vK under $script:Base): whether each
    # ended (sitting-end.json), how, and the held records left in the child roots it touched (its state.touched_roots, only
    # those under $script:Base). A held record with task_registered true and run_requested false names a one-shot task that
    # was registered and never ran (v2: 14). A root this window cannot list (the plan runs unelevated) is counted, not guessed.
    $found=@();$items=@()
    try{$items=@(Get-ChildItem -LiteralPath $script:Base -Directory -Filter 'R5Sitting4.2.7-windows-20261011-v*' -ErrorAction Stop)}catch{$items=@()}
    foreach($item in $items){
        $name=[string]$item.Name
        if($name -cnotmatch '^R5Sitting4\.2\.7-windows-20261011-(v[0-9]{1,3})$'){continue}
        $attempt=$Matches[1]
        if($attempt -ceq $script:Attempt){continue}
        $root=Join-Path $script:Base $name;$endPath=Join-Path $root 'sitting-end.json'
        $ended=[bool](Test-Path -LiteralPath $endPath -PathType Leaf);$end=$(if($ended){Read-R5JsonFile $endPath}else{$null})
        $held=@();$neverRun=0;$unreadable=0
        foreach($touched in @(@(Get-R5Member $end 'state.touched_roots')|Where-Object {$_})){
            $path=[string]$touched
            if(-not $path.StartsWith($script:Base+'\',[StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $path -PathType Container)){continue}
            $records=@();try{$records=@(Get-ChildItem -LiteralPath $path -Filter '*held*.json' -File -ErrorAction Stop|ForEach-Object {[string]$_.FullName})}catch{$unreadable++;continue}
            foreach($record in $records){
                $held+=$record;$value=Read-R5JsonFile $record
                if((Get-R5Member $value 'task_registered') -eq $true -and (Get-R5Member $value 'run_requested') -eq $false){$neverRun++}}}
        $found+=[pscustomobject]@{attempt=$attempt;number=[int]$attempt.Substring(1);root=$root;ended=$ended;readable=($null -ne $end);
            outcome=[string](Get-R5Member $end 'outcome');stage=[string](Get-R5Member $end 'stage');restore_ok=(Get-R5Member $end 'restore_ok');
            staged_path=[string](Get-R5Member $end 'state.staged_path');held=@($held);never_run_tasks=$neverRun;unreadable_roots=$unreadable}}
    @($found|Sort-Object number)}

function Format-R5EarlierSitting {param($Sitting)
    # One plain line per earlier attempt for S0 and the plan.
    if(-not $Sitting.ended){return ('earlier sitting '+$Sitting.attempt+': started but never ended (no sitting-end.json in '+$Sitting.root+')')}
    $how=$(if(-not $Sitting.readable){'ended (its sitting-end.json is unreadable here)'}
           else{'ended '+$Sitting.outcome+$(if($Sitting.stage){' at '+$Sitting.stage}else{''})+$(if($Sitting.restore_ok -eq $true){' (r4 restored)'}elseif($Sitting.restore_ok -eq $false){' (R4-RESTORE not done)'}else{''})})
    $text='earlier sitting '+$Sitting.attempt+': '+$how+'; '+@($Sitting.held).Count+' held record(s) left in its child roots'
    if($Sitting.never_run_tasks){$text+=' ('+$Sitting.never_run_tasks+' name a one-shot task that was registered and never ran)'}
    if($Sitting.unreadable_roots){$text+='; '+$Sitting.unreadable_roots+' of its child roots can be listed only elevated'}
    if($Sitting.staged_path){$text+='; its staged configuration '+$Sitting.staged_path+' is not reused'}
    $text}

function Set-R5GeminiHeld {param([string]$Stage,[string]$Reason)
    if($script:R5.gemini -ceq 'skip'){return}
    $script:R5.gemini='held';$script:R5.gemini_reason=($Stage+': '+$Reason)
    Say ('Gemini HELD ('+$Stage+'): '+$Reason+'. The sitting continues; Claude and Codex are not affected.') 'Yellow'}

# ================================================================== controller helpers
function Get-R5Health {Invoke-R5Control '/health'}

function Test-R5HealthGate {param($Health,[string]$SourceRoot)
    # Hard: identity, root, no active work, no quarantined slot, no execution quarantine. Awaited: knowledge and admission_ready
    # (warden_controller.admission_ready, never the bare 'ready' field). routing.holds is reported only.
    $hard=@();$soft=@()
    if($null -eq $Health){return [pscustomobject]@{hard=@();soft=@('no /health answer');holds=0}}
    if((Get-R5Member $Health 'service_identity') -cne 'SYSTEM'){$hard+='service_identity is not SYSTEM'}
    if([string](Get-R5Member $Health 'source_root') -ine $SourceRoot){$hard+=('source_root is '+[string](Get-R5Member $Health 'source_root')+', expected '+$SourceRoot)}
    if(-not (Test-R5HasMember $Health 'active') -or @(Get-R5Member $Health 'active').Count){$hard+='active work is present (or no active list)'}
    $slots=Get-R5Member $Health 'quarantined_slots'
    if($slots -isnot [Management.Automation.PSCustomObject] -or @($slots.PSObject.Properties).Count){$hard+='quarantined slots are present (or no quarantined_slots object)'}
    if(-not (Test-R5HasMember $Health 'routing.execution_quarantines') -or @(Get-R5Member $Health 'routing.execution_quarantines').Count){$hard+='execution quarantines are present (or no routing.execution_quarantines list)'}
    if((Get-R5Member $Health 'knowledge.ready') -ne $true -or (Get-R5Member $Health 'knowledge.authority_matches_capture') -ne $true){$soft+='knowledge is not ready with authority_matches_capture true'}
    if((Get-R5Member $Health 'components.warden_controller.admission_ready') -ne $true){$soft+='components.warden_controller.admission_ready is not true'}
    $holds=Get-R5Member $Health 'routing.holds'
    [pscustomobject]@{hard=@($hard);soft=@($soft);holds=@($holds|Where-Object {$null -ne $_}).Count}}

function Test-R5CpuOnlyPause {param($Health)
    # DIAG-NEXT 2026-10-11 (S12): r5 keeps r4's 5% Warden CPU budget (controller_guard.py: a CPU-only violation, memory within
    # 200 MiB, pauses admission for that sample alone and starts no recovery hold). True only when that is the sole reason the
    # controller does not admit: recovery_hold false and every components.warden_controller.admission_reasons entry is the CPU
    # budget. Restoring r4 would not help: r4 has the same CPU budget and also pauses on its 50 MiB memory budget.
    $controller=Get-R5Member $Health 'components.warden_controller'
    if($null -eq $controller -or (Get-R5Member $controller 'recovery_hold') -ne $false){return $false}
    $reasons=@(@(Get-R5Member $controller 'admission_reasons')|Where-Object {$null -ne $_})
    [bool]($reasons.Count -and -not @($reasons|Where-Object {[string]$_ -cnotmatch '^Warden CPU utilization exceeds its strict [0-9]+% budget$'}).Count)}

function Set-R5RoutingHolds {param($Health)
    $kinds=@(@(Get-R5Member $Health 'routing.holds')|Where-Object {$null -ne $_}|ForEach-Object {[string](Get-R5Member $_ 'scope')+':'+[string](Get-R5Member $_ 'resource_key')+' ('+[string](Get-R5Member $_ 'reason')+')'})
    $script:R5.routing_holds=[ordered]@{count=$kinds.Count;kinds=$kinds}
    if($kinds.Count){Say ('NOTE: '+$kinds.Count+' routing hold(s) are active (observed provider failures; they expire on their own).')}}

function Invoke-R5HealthCheck {param([string]$Label)
    # S12 gate (also after the Gemini fallback): polls /health no faster than every 10 s for up to 120 s. cpu_paused: the hard
    # checks and knowledge passed and the only open item at the deadline is admission_ready, paused by the CPU budget alone.
    $deadline=(Get-R5Now).AddSeconds(120);$last='no /health answer';$health=$null;$cpuPaused=$false
    while($true){
        $health=Get-R5Health;$cpuPaused=$false
        if($null -eq $health){$last=('no /health answer: '+$script:R5LastControlError)}
        else{
            $gate=Test-R5HealthGate $health $script:R5SourceRoot
            if(@($gate.hard).Count){return [pscustomobject]@{ok=$false;reason=(@($gate.hard) -join '; ');health=$health;cpu_paused=$false}}
            if(-not @($gate.soft).Count){
                Set-R5RoutingHolds $health
                Say ($Label+': r5 health verified (SYSTEM, r5 root, idle, no quarantine, knowledge ready, warden_controller.admission_ready true)') 'Green'
                return [pscustomobject]@{ok=$true;reason='';health=$health;cpu_paused=$false}}
            $cpuPaused=((@($gate.soft).Count -eq 1) -and (@($gate.soft)[0] -ceq 'components.warden_controller.admission_ready is not true') -and (Test-R5CpuOnlyPause $health))
            $last=(@($gate.soft) -join '; ')}
        if((Get-R5Now) -ge $deadline){
            if($cpuPaused){Set-R5RoutingHolds $health}
            return [pscustomobject]@{ok=$false;reason=$last;health=$health;cpu_paused=$cpuPaused}}
        Wait-R5Seconds 10}}

function Wait-R5Admission {
    # Host-governor pauses (disk IOPS, CPU temperature) are waited out up to 10 minutes; polls every 15 s.
    $deadline=(Get-R5Now).AddSeconds(600);$reason='no /health answer'
    while($true){
        $health=Get-R5Health
        if($null -ne $health){
            $capacity=Get-R5Member $health 'admission_capacity'
            if(($capacity -is [int] -or $capacity -is [long] -or $capacity -is [double]) -and $capacity -gt 0){return [pscustomobject]@{ok=$true;capacity=$capacity;reason=''}}
            $reasons=@(Get-R5Member $health 'admission.reasons')+@(Get-R5Member $health 'hardware.reasons')
            $reason=('admission_capacity '+[string]$capacity+$(if(@($reasons|Where-Object {$_}).Count){' ('+((@($reasons|Where-Object {$_}|Select-Object -Unique)) -join '; ')+')'}else{''}))}
        else{$reason=('no /health answer: '+$script:R5LastControlError)}
        if((Get-R5Now) -ge $deadline){return [pscustomobject]@{ok=$false;capacity=0;reason=$reason}}
        Say ('waiting for admission capacity: '+$reason)
        Wait-R5Seconds 15}}

function Test-R5OperatorLimit {param($Workflow)
    $text=($Workflow|ConvertTo-Json -Depth 10 -Compress)
    $blocked=((Get-R5Member $Workflow 'status') -ceq 'BLOCKED') -or @(@(Get-R5Member $Workflow 'jobs')|Where-Object {(Get-R5Member $_ 'status') -ceq 'BLOCKED'}).Count
    [bool]($blocked -and $text -match 'routing_operator_limit')}

function Invoke-R5Preflight {param([bool]$ExpectGemini,[string]$Tag)
    # ONE preflight (POST /preflight), polled at most every 10 s for up to 300 s; one resubmit on routing_operator_limit.
    $result=[ordered]@{ok=$false;expect_gemini=$ExpectGemini;workflow_id=$null;status=$null;provider=$null;model=$null;effort=$null;reported_model=$null;native_reported_model=$null;resubmitted=$false;detail=''}
    foreach($n in 1..2){
        $id=('r5sit-'+$script:Attempt+'-'+$script:Stamp+'-'+$Tag+$n);$result.workflow_id=$id
        $submitted=Invoke-R5Control '/preflight' @{workflow_id=$id}
        if($null -eq $submitted){$result.detail=('the preflight was not accepted: '+$script:R5LastControlError);return [pscustomobject]$result}
        Say ('preflight '+$id+' submitted; polling every 10 s (up to 5 min)')
        $deadline=(Get-R5Now).AddSeconds(300);$workflow=$null;$blocked=$false;$status='TIMEOUT'
        while($true){
            Wait-R5Seconds 10
            $workflow=Invoke-R5Control ('/workflow/'+$id)
            if($null -ne $workflow){
                $current=[string](Get-R5Member $workflow 'status')
                if($current -ceq 'COMPLETED' -or $current -ceq 'FAILED'){$status=$current;break}
                if(Test-R5OperatorLimit $workflow){$blocked=$true;$status='BLOCKED';break}}
            if((Get-R5Now) -ge $deadline){break}}
        if($blocked -and $n -eq 1){$result.resubmitted=$true;Say 'preflight BLOCKED by routing_operator_limit; resubmitting once with a new id';continue}
        $job=@(@(Get-R5Member $workflow 'jobs')|Where-Object {(Get-R5Member $_ 'kind') -ceq 'PREFLIGHT_REQUEST'})|Select-Object -Last 1
        # /workflow/<id> jobs carry 'route' (store._get); operator views and receipts name it selected_route.
        $route=Get-R5Member $job 'route';if($null -eq $route){$route=Get-R5Member $job 'selected_route'};if($null -eq $route){$route=Get-R5Member $job 'receipt.selected_route'}
        $result.status=$status;$result.provider=[string](Get-R5Member $route 'provider');$result.model=[string](Get-R5Member $route 'model')
        $result.effort=Get-R5Member $route 'reasoning_effort';if($null -eq $result.effort){$result.effort=Get-R5Member $route 'effort'}
        $result.reported_model=Get-R5Member $job 'receipt.reported_model';$result.native_reported_model=Get-R5Member $job 'receipt.native_reported_model'
        $holdSeen=($null -ne $workflow -and (($workflow|ConvertTo-Json -Depth 10 -Compress) -match 'integration_verification_hold'))
        if($ExpectGemini){
            $binding=Get-R5Prop $script:R5.chosen_bindings $(if($result.effort){$result.model+':'+$result.effort}else{$result.model})
            $expected=$(if($binding -is [string]){$binding}else{Get-R5Member $binding 'reports'})
            $nativeOk=$(if($expected){[string]$result.native_reported_model -ceq [string]$expected}else{[bool]$result.native_reported_model})
            $result.ok=($status -ceq 'COMPLETED' -and $result.provider -ceq 'gemini' -and [string]$result.reported_model -ceq $result.model -and $nativeOk -and -not $holdSeen)
            if(-not $result.ok){$result.detail=('Gemini preflight: status '+$status+', route '+$result.provider+'/'+$result.model+', reported '+[string]$result.reported_model+
                ', native '+[string]$result.native_reported_model+' (expected '+[string]$expected+')'+$(if($holdSeen){', integration_verification_hold seen'}else{''}))}
        }else{
            $result.ok=($status -ceq 'COMPLETED' -and $result.provider -in @('claude','codex'))
            if(-not $result.ok){$result.detail=('preflight: status '+$status+', route '+$result.provider+'/'+$result.model+$(if($null -eq $workflow){', last error '+$script:R5LastControlError}else{''}))}}
        break}
    [pscustomobject]$result}

# ================================================================== cutover helpers
function Invoke-R5Retarget {param([string]$Target,[string]$Config,[string]$TargetAttempt,[string]$SourceAttempt='',[string]$StopAttempt='')
    # The documented Cutover calls (INTERFACES-CUTOVER): -Target r5 for S11 and the Gemini fallback, -Target r4 for R4-RESTORE.
    if($Target -ceq 'r5'){$arguments=@('-Target','r5')}elseif($Target -ceq 'r4'){$arguments=@('-Target','r4')}else{Stop-R5Series ('Unknown retarget target '+$Target)}
    if($Config){$arguments+=@('-Config',$Config)}
    $arguments+=@('-Attempt',$TargetAttempt)
    if($SourceAttempt){$arguments+=@('-SourceAttempt',$SourceAttempt)}
    if($StopAttempt){$arguments+=@('-StopAttempt',$StopAttempt)}
    $arguments+=@('-Apply','-Start')
    Add-R5TouchedRoot (Join-Path $script:Base ($(if($Target -ceq 'r5'){$script:NsRetargetR5}else{$script:NsRetargetR4})+$TargetAttempt))
    $run=Invoke-R5Child ('retarget-warden-r5.ps1 '+($arguments -join ' ')+' (waits up to 240 s for health)') 'retarget-warden-r5.ps1' $arguments
    $json=Get-R5JsonTail $run.text
    $expected=$(if($Target -ceq 'r5'){'WARDEN_R5_RUNNING_HEALTH_VERIFIED'}else{'WARDEN_R4_RESTARTED_HEALTH_VERIFIED'})
    $status=[string](Get-R5Member $json 'status')
    [pscustomobject]@{ok=($run.code -eq 0 -and $status -ceq $expected);code=$run.code;status=$status;json=$json;
        detail=$(if($run.code -eq 0 -and $status -ceq $expected){''}else{'exit '+$run.code+', status '+$status+': '+(Get-R5LastLine $run.text)})}}

function Test-R5TwoPhaseReceipt {param($Receipt)
    # Cutover C-F1/C-F5: an r5 start receipt records the two-phase start. stop-warden-r5.ps1 refuses a start receipt without it
    # (with and without -RecoverInterruptedStart), so such a receipt is a 'blocked' restore state. Returns '' or the reason.
    if($null -eq $Receipt){return 'the start receipt is unreadable'}
    if((Get-R5Member $Receipt 'trigger_enabled_before') -ne $false -or (Get-R5Member $Receipt 'trigger_enabled_after') -ne $true){
        return 'trigger_enabled_before false and trigger_enabled_after true are not recorded'}
    $xml=[string](Get-R5Member $Receipt 'task_xml_sha256')
    if($xml -cnotmatch '^[a-f0-9]{64}$' -or [string](Get-R5Member $Receipt 'task_xml_started_sha256') -cne $xml){
        return 'task_xml_started_sha256 differs from task_xml_sha256'}
    ''}

function Test-R5StartReceipt {param($Result,[string]$TargetAttempt,[string]$ConfigSha256)
    # Audit F3: the start receipt named by the retarget result (receipt_path at the expected Base-derived path, bytes equal to
    # receipt_sha256) must bind the S1 installation (install_after_sha256) and the configuration that was passed (config_sha256).
    # The two-phase start (Test-R5TwoPhaseReceipt) is checked first, so a receipt without it is classified 'blocked' and an F3
    # mismatch on a two-phase-valid receipt takes the documented after-Run restore. The fallback passes the commissioning copy, whose bytes are the commissioned 135cd9ec (retarget-warden-r5.ps1
    # Assert-R5Config maps exactly that sha to GEMINI_HELD_COMMISSIONED_BYTES; install-stopped-runtime-r5.ps1 opens the same path
    # pinned to it).
    # Returns '' when it binds, otherwise the reason.
    $expected=Join-Path (Join-Path $script:Base ($script:NsRetargetR5+$TargetAttempt)) 'start-receipt.json'
    $path=[string](Get-R5Member $Result.json 'receipt_path');$sha=[string](Get-R5Member $Result.json 'receipt_sha256')
    if($path -ine $expected){return ('the start receipt path is '+$path+', expected '+$expected)}
    if(-not (Test-Path -LiteralPath $expected -PathType Leaf)){return 'the start receipt is missing'}
    if($sha -cnotmatch '^[a-f0-9]{64}$' -or (Get-R5FileSha256 $expected) -cne $sha){return 'the start receipt bytes differ from receipt_sha256'}
    $receipt=Read-R5JsonFile $expected
    $twoPhase=Test-R5TwoPhaseReceipt $receipt
    if($twoPhase){return ('the start receipt does not record the two-phase start ('+$twoPhase+')')}
    if([string](Get-R5Member $receipt 'install_after_sha256') -cne [string]$script:R5.install_after_sha256){
        return ('the started runtime install_after_sha256 '+[string](Get-R5Member $receipt 'install_after_sha256')+' differs from the S1 installation '+[string]$script:R5.install_after_sha256)}
    if([string](Get-R5Member $receipt 'config_sha256') -cne $ConfigSha256){
        return ('the started config_sha256 '+[string](Get-R5Member $receipt 'config_sha256')+' differs from the configuration passed ('+$ConfigSha256+')')}
    ''}

function Invoke-R5StopR5 {param([string]$StopAttempt,[string]$RetargetTarget,[string]$RetargetAttempt,[switch]$RecoverInterruptedStart)
    $arguments=@('-Apply','-Attempt',$StopAttempt,'-RetargetTarget',$RetargetTarget,'-RetargetAttempt',$RetargetAttempt)
    # An interrupted, crashed or post-health-gate held start (no start receipt) is bound by -RecoverInterruptedStart.
    if($RecoverInterruptedStart){$arguments+=@('-RecoverInterruptedStart')}
    Add-R5TouchedRoot (Join-Path $script:Base ($script:NsStopR5+$StopAttempt))
    $run=Invoke-R5Child ('stop-warden-r5.ps1 '+($arguments -join ' ')+' (idle proof, End, disable)') 'stop-warden-r5.ps1' $arguments
    $json=Get-R5JsonTail $run.text;$status=[string](Get-R5Member $json 'status')
    $ok=($run.code -eq 0 -and $status -in @('WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED','WARDEN_ALREADY_STOPPED_CLEAN_NOOP'))
    $held=Test-Path -LiteralPath (Join-Path (Join-Path $script:Base ($script:NsStopR5+$StopAttempt)) 'stop-held.json')
    [pscustomobject]@{ok=$ok;code=$run.code;status=$status;held=[bool]$held;detail=$(if($ok){''}else{'exit '+$run.code+', status '+$status+': '+(Get-R5LastLine $run.text)})}}

function Get-R5LastLine {param([string]$Text)([string](@(([string]$Text) -split "`n"|Where-Object {$_.Trim()})|Select-Object -Last 1)).Trim()}

function Get-R5UnstoppedRestoreDetail {
    # The base is a restored r4 that this sitting has not stopped (base_source.stop_attempt is recorded only after S2 passed).
    # DIAG-NEXT 2026-10-11: say what happened to the S2 stop instead of 'not stopped by this sitting'. Every case is 'blocked':
    # a held stop has no defined recovery (retarget-warden-r5 refuses a held -StopAttempt) and r4 may still be running.
    $attempt=[string]$script:R5.s2_stop_attempt
    if(-not $script:R5.s2_attempted -or -not $attempt){return 'the restored r4 Warden was not stopped by this sitting (S2 did not run); r4 keeps whatever state it had'}
    $root=Join-Path $script:Base ($script:NsStopR5+$attempt);$heldPath=Join-Path $root 'stop-held.json'
    if(Test-Path -LiteralPath $heldPath -PathType Leaf){
        $held=Read-R5JsonFile $heldPath
        $phase=$(if($null -eq $held){'unknown (stop-held.json unreadable)'}else{[string](Get-R5Member $held 'phase')})
        return ('the S2 stop of the restored r4 (stop-warden-r5 '+$attempt+') is held at phase '+$phase+' ('+$heldPath+'); nothing was killed, r4 may still be running and its task may still be enabled; the owner/agent reviews it')}
    if(Test-Path -LiteralPath $root){return ('the S2 stop of the restored r4 (stop-warden-r5 '+$attempt+') did not complete and '+$root+' holds no stop-held.json; r4 may still be running; the owner/agent reviews it')}
    'the S2 stop of the restored r4 (stop-warden-r5 '+$attempt+') did not complete before creating its root; r4 keeps its state; the owner/agent reviews the log'}

function Get-R5CutoverState {
    # Chooses the exact Cutover call for the state reached, from this sitting's state and the child roots on disk.
    $warden=$script:R5.warden_initial;$base=$script:R5.base_source
    if(-not $script:R5.s2_done -and -not $script:R5.s2_attempted -and $null -ne $warden -and (Get-R5Member $warden 'running') -eq $true){return [pscustomobject]@{kind='none';source=$null;stop=$null;detail='r4 was never stopped and still runs'}}
    if($script:R5.r5_stop_held){return [pscustomobject]@{kind='blocked';source=$null;stop=$null;detail='stop-warden-r5 is held (stop-held.json); nothing was killed, the owner reviews it'}}
    $previous=$null
    if($null -ne $script:R5.r5_stopped){$previous=[pscustomobject]@{kind='r5-stopped';source=(Get-R5Member $script:R5.r5_stopped 'source_attempt');stop=(Get-R5Member $script:R5.r5_stopped 'stop_attempt');detail='r5 stopped and disabled'}}
    elseif($null -eq $base){$previous=[pscustomobject]@{kind='blocked';source=$null;stop=$null;detail='the Warden source of this sitting is unknown'}}
    elseif((Get-R5Member $base 'kind') -ceq 'r4-restore' -and -not (Get-R5Member $base 'stop_attempt')){$previous=[pscustomobject]@{kind='blocked';source=$null;stop=$null;detail=(Get-R5UnstoppedRestoreDetail)}}
    else{$previous=[pscustomobject]@{kind='base';source=(Get-R5Member $base 'source_attempt');stop=(Get-R5Member $base 'stop_attempt');detail=('Warden task on its '+(Get-R5Member $base 'kind')+' action')}}
    $attempt=$script:R5.r5_attempt
    if(-not $attempt){return $previous}
    if($null -ne $script:R5.r5_stopped -and (Get-R5Member $script:R5.r5_stopped 'source_attempt') -ceq $attempt){return $previous}
    $root=Join-Path $script:Base ($script:NsRetargetR5+$attempt)
    $has={param($Name)Test-Path -LiteralPath (Join-Path $root $Name)}
    # Binding classification order (deploy fix lead, INTERFACES-CUTOVER final):
    # 1. held retarget: retarget-held.json MUTATION_READBACK, or retarget-intent.json alone (no retarget receipt, no held record:
    #    interrupted between intent and receipt). A held record in another phase means the single TASK_UPDATE never ran (the
    #    retarget would refuse -SourceAttempt against the unchanged live action), so the previous state applies.
    if(-not (& $has 'retarget-receipt.json')){
        $why='';$readable=$false
        if(& $has 'retarget-held.json'){
            $held=Read-R5JsonFile (Join-Path $root 'retarget-held.json')
            if($null -eq $held){return [pscustomobject]@{kind='blocked';source=$attempt;stop=$null;detail=('the r5 '+$attempt+' retarget-held.json is unreadable; the owner/agent reviews it')}}
            if((Get-R5Member $held 'phase') -cne 'MUTATION_READBACK'){return $previous}
            $why='retarget held at its task update readback (MUTATION_READBACK)'
            $readable=((Get-R5Member $held 'readback_readable') -eq $true)}
        elseif(& $has 'retarget-intent.json'){$why='retarget interrupted before its retarget receipt (retarget-intent.json alone)';$readable=$false}
        else{return $previous}
        # Audit F1: the live task action, read now, decides whether the single TASK_UPDATE took effect.
        $intent=Read-R5JsonFile (Join-Path $root 'retarget-intent.json')
        if($null -eq $intent){return [pscustomobject]@{kind='blocked';source=$attempt;stop=$null;detail=('the r5 '+$attempt+' '+$why+' but its retarget-intent.json is unreadable; the owner/agent reviews it')}}
        $live=$null;try{$live=Read-R5Warden}catch{$live=$null}
        if($null -eq $live -or -not $live.readable){return [pscustomobject]@{kind='blocked';source=$attempt;stop=$null;detail=('the r5 '+$attempt+' '+$why+' and the live Warden task cannot be read; the owner/agent reviews it')}}
        if(Test-R5LiveAction (Get-R5Member $intent 'action_after') $live){
            return [pscustomobject]@{kind='r5-retarget-held';source=$attempt;stop=$null;detail=('r5 '+$attempt+' '+$why+'; the live action is the r5 action it intended')}}
        # A readable readback recorded the task after the update, so the previous action is no longer a valid explanation.
        if(-not $readable -and (Test-R5LiveAction (Get-R5Member $intent 'action_before') $live)){
            return [pscustomobject]@{kind=$previous.kind;source=$previous.source;stop=$previous.stop;detail=($previous.detail+'; the r5 '+$attempt+' task update never took effect (the live action is still the previous one)')}}
        return [pscustomobject]@{kind='blocked';source=$attempt;stop=$null;detail=('the r5 '+$attempt+' '+$why+' and the live Warden action is neither the one it intended nor the previous one; the owner/agent reviews it')}}
    # 5. a start receipt: two-phase-valid -> after-Run restore (F3 mismatches land here); otherwise blocked (stop-warden-r5 refuses it).
    if(& $has 'start-receipt.json'){
        $twoPhase=Test-R5TwoPhaseReceipt (Read-R5JsonFile (Join-Path $root 'start-receipt.json'))
        if($twoPhase){return [pscustomobject]@{kind='blocked';source=$attempt;stop=$null;detail=('the r5 '+$attempt+' start receipt does not record the two-phase start (stop-warden-r5 would refuse it); owner/agent review: '+$twoPhase)}}
        return [pscustomobject]@{kind='r5-started';source=$attempt;stop=$null;detail=('r5 '+$attempt+' started')}}
    # 2-3. a held start branches on held_before_run only (C-F7: a Run that threw with no instance has run_requested true AND
    #    held_before_run true). Every after-Run hold (held_before_run false: interrupted, held before or after its health gate)
    #    is recovered by stop-warden-r5 -RecoverInterruptedStart (R-F1: the retarget records stop_recovery_allowed true for
    #    every after-Run hold and the stop binds START_HELD_BEFORE_HEALTH_GATE).
    if(& $has 'start-held.json'){
        $held=Read-R5JsonFile (Join-Path $root 'start-held.json')
        if($null -eq $held){return [pscustomobject]@{kind='blocked';source=$attempt;stop=$null;detail=('the r5 '+$attempt+' start-held.json is unreadable; the owner/agent reviews it')}}
        if((Get-R5Member $held 'held_before_run') -eq $true){return [pscustomobject]@{kind='r5-never-started';source=$attempt;stop=$null;detail=('r5 '+$attempt+' start held before Run (held_before_run true)')}}
        return [pscustomobject]@{kind='r5-start-interrupted';source=$attempt;stop=$null;detail=('r5 '+$attempt+' start held after Run (start-held.json held_before_run false, stage '+[string](Get-R5Member $held 'stage')+', stop_recovery_allowed '+[string](Get-R5Member $held 'stop_recovery_allowed')+')')}}
    # 3. a crashed start: start-intent.json with neither start-held.json nor a start receipt.
    if(& $has 'start-intent.json'){return [pscustomobject]@{kind='r5-start-interrupted';source=$attempt;stop=$null;detail=('r5 '+$attempt+' start crashed with no record (start-intent.json alone)')}}
    # Retargeted (receipt) and never started.
    [pscustomobject]@{kind='r5-never-started';source=$attempt;stop=$null;detail=('r5 '+$attempt+' retargeted, never started')}}

# ================================================================== stages
function Invoke-R5Stage0 {
    Say 'S0: preconditions (nothing is changed by this stage)'
    Assert-R5OwnerShell
    $drift=@(Get-R5PinDrift)
    if($drift.Count){Stop-R5Series ('Reviewed files differ from the pin table: '+($drift -join ', ')+'. Nothing was changed; send the log to the agent.')}
    Say ('pins: '+$script:Pins.Count+' reviewed files verified')
    $freeze=Read-R5JsonFile $script:FreezeReceipt
    $manifestSha=[string](Get-R5Member $freeze 'manifest_sha256')
    if($manifestSha -cnotmatch '^[a-f0-9]{64}$' -or $manifestSha -cne [string]$script:Pins['stopped-runtime-r5-source-manifest.json']){
        Stop-R5Series 'The r5 freeze receipt does not name the pinned source manifest (stopped-runtime-r5-freeze-receipt.json manifest_sha256). Nothing was changed.'}
    if(Test-Path -LiteralPath (Join-Path $script:SittingRoot 'sitting-end.json')){
        Stop-R5Series ('Sitting attempt '+$script:Attempt+' has already ended (see '+(Join-Path $script:SittingRoot 'sitting-end.json')+'). Do not rerun it; the agent reviews and names the next -Attempt.')}
    # Rerun: verified stage receipts are skipped and the latest one restores the state.
    $latest=$null
    foreach($n in 0..14){$id='S'+$n.ToString('00');$receipt=Read-R5Receipt $id;if($null -ne $receipt){$script:R5Done[$id]=$true;$latest=$receipt}}
    if($null -ne $latest){
        foreach($property in $latest.state.PSObject.Properties){$script:R5[$property.Name]=$property.Value}
        $script:R5['pending_restore']=$false;$script:R5['current_stage']='S00'
        Say ('rerun of sitting attempt '+$script:Attempt+': '+(@($script:R5Done.Keys|Sort-Object) -join ', ')+' already done and verified')}
    if((Test-Path -LiteralPath (Join-Path $script:SittingRoot 'S11-intent.json')) -and -not $script:R5Done.ContainsKey('S11')){
        Stop-R5Series 'An earlier run of this attempt was interrupted during the r5 cutover (S11-intent.json without its receipt). Do not rerun; the agent reviews the Warden state.'}
    if((Test-Path -LiteralPath (Join-Path $script:SittingRoot 'fallback-intent.json')) -and -not $script:R5Done.ContainsKey('S13')){
        Stop-R5Series 'An earlier run of this attempt was interrupted during the Gemini fallback. Do not rerun; the agent reviews the Warden state.'}
    if(@(Get-ChildItem -LiteralPath $script:SittingRoot -Filter 'restore-intent-*.json' -ErrorAction SilentlyContinue).Count){
        Stop-R5Series 'An earlier run of this attempt started an R4-RESTORE that did not finish. Do not rerun; the agent reviews the Warden state.'}
    # Leftovers of the other attempts (v3 fix, 2026-10-11: v2 left 14 held one-shot roots whose tasks never ran, a staged
    # WardenConfig v1 and the r4 restore it started) are reported and never stop S0: this attempt's children take fresh
    # 32-hex names and the next free vN namespaces. An attempt that never ended may still run in another window: STOP.
    $earlier=@(Get-R5EarlierSittings)
    foreach($sitting in $earlier){Say (Format-R5EarlierSitting $sitting)}
    $open=@($earlier|Where-Object {-not $_.ended})
    if($open.Count){Stop-R5Series ('Sitting attempt '+(@($open|ForEach-Object {$_.attempt}) -join ', ')+' started on this host but never ended (no sitting-end.json): it may still be running in another window, or that window was closed early. Nothing was changed. If no other window runs it, run the same command with -Attempt '+$open[0].attempt+' instead (its finished stages are skipped); otherwise send this line to the agent.')}
    if($earlier.Count){Say 'leftovers of earlier sittings block nothing: this attempt uses fresh child names and the next free namespaces; keep them for the agent'}
    $script:R5.earlier_sittings=@($earlier|ForEach-Object {[ordered]@{attempt=$_.attempt;outcome=$_.outcome;stage=$_.stage;restore_ok=$_.restore_ok;held_records=@($_.held).Count;never_run_tasks=$_.never_run_tasks}})
    $docker=Get-R5DockerInfo
    if(-not $docker.ok){Stop-R5Series ('Docker Desktop engine is not answering as the controller needs it ('+$docker.reason+'). Start Docker Desktop, wait for "Engine running", stay signed in, then rerun. Nothing was changed.')}
    Say $docker.reason
    $warden=Read-R5Warden
    if(-not $warden.readable){Stop-R5Series ('The CoChem-4.2.7-Warden task could not be read ('+$warden.error+'). Use an elevated window; nothing was changed.')}
    if([int]$warden.listening -lt 0){Stop-R5Series 'The state of the controller port 127.0.0.1:47824 could not be established; nothing was changed.'}
    Say ('Warden task: source '+$warden.source+$(if($warden.source_attempt){' '+$warden.source_attempt}else{''})+', enabled '+$warden.enabled+', instances '+$warden.instances+', port 47824 listeners '+$warden.listening)
    if(-not $script:R5Done.ContainsKey('S02')){
        if($warden.source -notin @('r4-v1','r4-restore')){Stop-R5Series ('The Warden task does not run a reviewed r4 action (found source '+$warden.source+'); nothing was changed. The agent reviews it.')}
        if($null -ne $script:R5.base_source -and [string](Get-R5Member $script:R5.base_source 'kind') -cne $warden.source){Stop-R5Series 'The Warden task changed since the first run of this attempt; nothing was changed.'}
        if($null -eq $script:R5.base_source){$script:R5.warden_initial=$warden;$script:R5.base_source=[pscustomobject]@{kind=$warden.source;source_attempt=$warden.source_attempt;stop_attempt=$null}}
        if($warden.running){Say ('r4 is running now ('+$warden.source+$(if($warden.source_attempt){' '+$warden.source_attempt}else{''})+'); S2 stops it first and R4-RESTORE brings it back if r5 cannot take over')}
    }elseif(-not $script:R5Done.ContainsKey('S11')){
        if($warden.running -or $warden.enabled -eq $true){Stop-R5Series 'The Warden task is enabled or running again although this sitting stopped it (S2); nothing was changed. The agent reviews it.'}
    }elseif($warden.source -cne 'r5' -or -not $warden.running){
        Stop-R5Series 'The r5 Warden is not running. After a reboot it restarts itself 1-16 minutes after you sign in (it waits for Docker Desktop); wait, then rerun this same command.'}
    # 2026-10-11 17:22: S2 held on runtime processes no cutover script recognised. Every later cutover child (the S2 stop, the
    # S11 retarget and each rollback) holds on such a process, so the owner learns it here, before S1, with nothing changed.
    # Not needed once r5 runs (S11 done): then the processes under the r5 root are its own.
    if(-not $script:R5Done.ContainsKey('S11')){
        $presence=$null
        try{$presence=Get-R5RuntimePresence (Get-R5ProcessList)}
        catch{Stop-R5Series ('The process list could not be read ('+$_.Exception.Message+'); the cutover scripts would hold the same way. Nothing was changed.')}
        $blocking=@(@($presence.unclassified)+@($presence.uninspectable))
        if($blocking.Count){Stop-R5Series ('Runtime processes the cutover scripts do not recognise are running: '+(@($blocking|ForEach-Object {Format-R5Process $_}) -join '; ')+
            '. They would hold the Warden stop (S2), the r5 cutover and every rollback, as on 11 October at 17:22. Nothing was changed. Close the program that started them (or send this list to the agent), then rerun this same command.')}
        Say ('runtime processes: '+@($presence.clients).Count+' MCP client(s) recognised (Claude Desktop, Codex, Antigravity, Claude Code may stay open), '+
            @($presence.observers).Count+' observer recorder(s), '+@($presence.controllers).Count+' controller process(es); none unclassified')}
    $free=Get-R5FreeDiskGB $script:Base
    if(-not $script:R5Done.ContainsKey('S01') -and $free -ge 0 -and $free -lt 5){Stop-R5Series ('Only '+[Math]::Round($free,1)+' GB are free on the system drive; the r5 build needs at least 5 GB. Nothing was changed.')}
    if(-not $script:R5Done.ContainsKey('S01') -and -not (Test-Path -LiteralPath $script:InstallAfter)){
        if(-not (Test-R5PackageIndex)){Stop-R5Series 'PyPI (https://pypi.org/simple/) is not reachable; the r5 build downloads its locked wheels from it. Check the connection (and any VPN), then rerun. Nothing was changed.'}
        Say 'PyPI reachable'}
    $script:R5.manifest_sha256=$manifestSha
    Say ('Gemini: '+$(if($script:R5.gemini -ceq 'skip'){'skipped by -Gemini skip'}else{[string]$script:R5.gemini})+'; effort-null slug '+$script:R5.effort_null_slug)
    if(-not $script:R5Done.ContainsKey('S00')){Write-R5Receipt 'S00' 'PRECONDITIONS_VERIFIED'}}

function Test-R5InstallAfter {
    # S1 gate on the r5 installation receipt, bound to the pinned freeze manifest.
    if(-not (Test-Path -LiteralPath $script:InstallAfter -PathType Leaf)){return [pscustomobject]@{ok=$false;present=$false;reason='install-after.json is absent';sha256=$null}}
    $after=Read-R5JsonFile $script:InstallAfter;$manifest=Read-R5JsonFile $script:Manifest;$problems=@()
    if($null -eq $after){return [pscustomobject]@{ok=$false;present=$true;reason='install-after.json is not JSON';sha256=$null}}
    if((Get-R5Member $after 'schema') -cne 'cochem-stopped-runtime-update/1'){$problems+='schema'}
    if((Get-R5Member $after 'mode') -cne 'FRESH_STOPPED_RUNTIME_READY'){$problems+=('mode '+[string](Get-R5Member $after 'mode'))}
    if((Get-R5Member $after 'source_manifest_sha256') -cne $script:R5.manifest_sha256){$problems+='source_manifest_sha256 differs from the pinned manifest'}
    if((Get-R5Member $after 'verified_unchanged') -ne 153){$problems+=('verified_unchanged '+[string](Get-R5Member $after 'verified_unchanged'))}
    if((Get-R5Member $after 'tasks_changed') -ne 0){$problems+='tasks_changed is not 0'}
    if(@(Get-R5Member $after 'holds'|Where-Object {$null -ne $_}).Count){$problems+='holds are present'}
    if((Get-R5Member $after 'verification.r5_repairs_installed') -ne $true){$problems+='verification.r5_repairs_installed is not true'}
    # Audit F7, mirroring retarget-warden-r5.ps1 Assert-R5InstalledBindings: no held installation, every repair verified, and
    # the pinned venv bindings.
    if(Test-Path -LiteralPath $script:InstallHeld){$problems+='install-held.json is present'}
    if((Get-R5Member $after 'installed_repairs_verified') -ne $true){$problems+='installed_repairs_verified is not true'}
    if([string](Get-R5Member $after 'runtime_bindings.pyvenv_sha256') -cne $script:R5PyvenvPin){$problems+='runtime_bindings.pyvenv_sha256 is not the pinned pyvenv.cfg'}
    if([string](Get-R5Member $after 'runtime_bindings.venv_python_sha256') -cne $script:R5VenvPythonPin){$problems+='runtime_bindings.venv_python_sha256 is not the pinned venv launcher'}
    $wanted=@(Get-R5Member $manifest 'reviewed_repairs');$installed=@(Get-R5Member $after 'reviewed_repairs')
    if($wanted.Count -ne 13 -or $installed.Count -ne 13 -or @(Compare-Object -ReferenceObject $wanted -DifferenceObject $installed -CaseSensitive).Count){$problems+='reviewed_repairs differ from the 13 manifest repairs'}
    else{foreach($path in $wanted){
        $pin=[string](Get-R5Prop (Get-R5Member $manifest 'reviewed_repairs_sha256') $path)
        if($pin -cnotmatch '^[a-f0-9]{64}$' -or [string](Get-R5Prop (Get-R5Member $after 'reviewed_repairs_sha256') $path) -cne $pin){$problems+=('repair pin differs: '+$path)}}}
    if($problems.Count){return [pscustomobject]@{ok=$false;present=$true;reason=($problems -join ', ');sha256=$null}}
    [pscustomobject]@{ok=$true;present=$true;reason='';sha256=(Get-R5FileSha256 $script:InstallAfter)}}

function Invoke-R5Stage1 {
    Say 'S1: install the r5 runtime beside r4 (stopped; about 4 minutes, downloads the locked wheels; the Warden is not touched)'
    Add-R5TouchedRoot $script:R5Root
    $gate=Test-R5InstallAfter
    if($gate.ok){Say 'r5 is already installed and its install-after.json verifies; the installer is not run again'}
    else{
        if($gate.present -or (Test-Path -LiteralPath $script:R5Root)){
            $held=Read-R5JsonFile $script:InstallHeld
            Stop-R5Series ('The r5 root exists without a verified installation ('+$gate.reason+$(if($null -ne $held){'; install-held.json failed_stage '+[string](Get-R5Member $held 'failed_stage')}else{''})+'). Preserve it; the agent reviews it.') -Restore}
        $arguments=@('-Manifest',$script:Manifest,'-ManifestSha256',$script:R5.manifest_sha256)
        $plan=Invoke-R5Child 'install-stopped-runtime-r5.ps1 read-only plan' 'install-stopped-runtime-r5.ps1' $arguments
        $planJson=Get-R5JsonTail $plan.text
        if($plan.code -ne 0 -or (Get-R5Member $planJson 'mode') -cne 'READ_ONLY_PLAN'){Stop-R5Series ('The r5 installer plan did not run (exit '+$plan.code+'): '+(Get-R5LastLine $plan.text)) -Restore}
        $holds=@(Get-R5Member $planJson 'holds'|Where-Object {$null -ne $_})
        if($holds.Count){Stop-R5Series ('The r5 installer plan reports holds: '+($holds -join ' | ')) -Restore}
        $build=Invoke-R5Child 'install-stopped-runtime-r5.ps1 -Apply (a few minutes)' 'install-stopped-runtime-r5.ps1' ($arguments+@('-Apply'))
        $buildJson=Get-R5JsonTail $build.text
        if($build.code -ne 0 -or (Get-R5Member $buildJson 'mode') -cne 'FRESH_STOPPED_RUNTIME_READY'){
            $held=Read-R5JsonFile $script:InstallHeld
            Stop-R5Series ('The r5 build did not finish with FRESH_STOPPED_RUNTIME_READY (exit '+$build.code+$(if($null -ne $held){', failed_stage '+[string](Get-R5Member $held 'failed_stage')}else{''})+'): '+(Get-R5LastLine $build.text)) -Restore}
        $gate=Test-R5InstallAfter
        if(-not $gate.ok){Stop-R5Series ('The r5 install-after.json does not pass the S1 gate: '+$gate.reason) -Restore}
        Say 'r5 built and verified' 'Green'}
    $script:R5.install_after_sha256=$gate.sha256
    Write-R5Receipt 'S01' 'R5_INSTALLED'}

function Invoke-R5Stage2 {
    $base=$script:R5.base_source;$warden=$script:R5.warden_initial
    $kind=[string](Get-R5Member $base 'kind');$wasRunning=((Get-R5Member $warden 'running') -eq $true)
    if($kind -ceq 'r4-v1'){
        if((Get-R5Member $warden 'enabled') -ne $true -and -not $wasRunning){
            Say 'S2: skipped - the Warden task is already disabled with no instance (nothing to stop)'
            $script:R5.s2='SKIPPED_ALREADY_DISABLED';$script:R5.s2_done=$true;Write-R5Receipt 'S02' 'SKIPPED';return}
        $stopAttempt=Get-R5FreeAttempt $script:NsStopR4
        Say ('S2: stop-warden-r4 '+$(if($wasRunning){'(idle proof, Task Scheduler End, wait, disable; about 3 min)'}else{'(the task is idle but enabled: disable only, no End)'}))
        $script:R5.s2_attempted=$true;$script:R5.s2_stop_attempt=$stopAttempt;Add-R5TouchedRoot (Join-Path $script:Base ($script:NsStopR4+$stopAttempt))
        $run=Invoke-R5Child ('stop-warden-r4.ps1 -Apply -Attempt '+$stopAttempt) 'stop-warden-r4.ps1' @('-Apply','-Attempt',$stopAttempt)
        $json=Get-R5JsonTail $run.text;$status=[string](Get-R5Member $json 'status')
        $okStatuses=@('WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED','WARDEN_ALREADY_STOPPED_AND_DISABLED')
    }elseif($kind -ceq 'r4-restore'){
        $stopAttempt=Get-R5FreeAttempt $script:NsStopR5;$source=[string](Get-R5Member $base 'source_attempt')
        Say ('S2: stop the restored r4 Warden (stop-warden-r5 -RetargetTarget r4 -RetargetAttempt '+$source+$(if($wasRunning){'; it is running: idle proof, Task Scheduler End, wait, disable; about 3-4 min, submit no work meanwhile)'}else{')'}))
        $script:R5.s2_attempted=$true;$script:R5.s2_stop_attempt=$stopAttempt;Add-R5TouchedRoot (Join-Path $script:Base ($script:NsStopR5+$stopAttempt))
        $run=Invoke-R5Child ('stop-warden-r5.ps1 -Apply -Attempt '+$stopAttempt+' -RetargetTarget r4 -RetargetAttempt '+$source) 'stop-warden-r5.ps1' @('-Apply','-Attempt',$stopAttempt,'-RetargetTarget','r4','-RetargetAttempt',$source)
        $json=Get-R5JsonTail $run.text;$status=[string](Get-R5Member $json 'status')
        $okStatuses=@('WARDEN_ENDED_AND_DISABLED_UNCLEAN_SHUTDOWN_EXPECTED','WARDEN_ALREADY_STOPPED_CLEAN_NOOP')
    }else{Stop-R5Series ('S2: unknown Warden source '+$kind)}
    if($run.code -ne 0 -or $status -notin $okStatuses){
        $line=Get-R5LastLine $run.text
        if($wasRunning -and $run.text -match 'nothing was changed'){
            # Refused before its root existed: r4 was not touched (the outcome says 'never stopped') and the attempt stays rerunnable.
            $script:R5.s2='REFUSED_NOTHING_CHANGED';$script:R5.s2_attempted=$false
            Stop-R5Series ('S2: the Warden stop was refused before any change ('+$line+'). r4 keeps running; nothing was changed.')}
        Stop-R5Series ('S2: the Warden stop did not complete (exit '+$run.code+', status '+$status+'): '+$line) -Restore}
    if($kind -ceq 'r4-restore'){$script:R5.base_source=[pscustomobject]@{kind='r4-restore';source_attempt=(Get-R5Member $base 'source_attempt');stop_attempt=$stopAttempt}}
    $script:R5.s2=$status;$script:R5.s2_done=$true
    Say ('Warden stopped and disabled: '+$status) 'Green'
    Write-R5Receipt 'S02' $status}

function Invoke-R5Stage3 {
    Say 'S3: Claude and Codex session health on the six worker slots (12 one-shot checks, strictly one at a time; about 6 min)'
    $hex=New-R5HexAttempt;$rows=@()
    foreach($provider in @('claude','codex')){foreach($n in 1..6){$slot='slot'+$n
        Add-R5TouchedRoot (Join-Path $script:Base ('NativeAuthStatusSix4.2.7-windows-20261010-r4-v1-'+$hex+'-'+$slot+'-'+$provider+'-before'))
        $run=Invoke-R5Child ('session status '+$provider+' '+$slot) 'check-worker-native-auth-status-six-r4-v1.ps1' @('-Slot',$slot,'-Provider',$provider,'-Stage','before','-Attempt',$hex,'-Apply')
        $json=Get-R5JsonTail $run.text;$decision=[string](Get-R5Member $json 'decision')
        if($run.code -ne 0 -or $decision -notin @('REUSE_VERIFIED_SESSION','ATTENDED_LOGIN_REQUIRED')){$decision='HOLD'}
        $rows+=[pscustomobject]@{provider=$provider;slot=$slot;decision=$decision}}}
    $sessions=[ordered]@{status_attempt=$hex;rows=$rows}
    foreach($provider in @('claude','codex')){
        $mine=@($rows|Where-Object {$_.provider -ceq $provider})
        $sessions[$provider]=[ordered]@{verified=@($mine|Where-Object {$_.decision -ceq 'REUSE_VERIFIED_SESSION'}).Count;
            login_required=@($mine|Where-Object {$_.decision -ceq 'ATTENDED_LOGIN_REQUIRED'}|ForEach-Object {$_.slot});
            hold=@($mine|Where-Object {$_.decision -ceq 'HOLD'}|ForEach-Object {$_.slot});relogin='NOT_NEEDED'}}
    $needing=@(@('claude','codex')|Where-Object {@($sessions[$_].login_required).Count})
    if($needing.Count){
        $count=@($rows|Where-Object {$_.decision -ceq 'ATTENDED_LOGIN_REQUIRED'}).Count
        Request-R5Attention ([string]$count+' Claude/Codex worker session(s) are signed out: '+((@($rows|Where-Object {$_.decision -ceq 'ATTENDED_LOGIN_REQUIRED'}|ForEach-Object {$_.provider+' '+$_.slot})) -join ', '))
        $yes=Read-R5YesNo ('Sign them in now (about 4 minutes each, guided step by step)? N keeps them signed out; the sitting continues either way.')
        foreach($provider in $needing){
            if(-not $yes){$sessions[$provider].relogin='DECLINED';continue}
            $loginAttempt=New-R5HexAttempt;Add-R5TouchedRoot (Join-Path $script:Base ('NativeAuthSix4.2.7-windows-20261011-r4-v1-'+$loginAttempt+'-'+$provider))
            Say ('attended '+$provider+' sign-in series (it re-checks all six slots and signs in only the signed-out ones)')
            $code=Invoke-R5Attended 'login-six-workers-status-first-r4-v1.ps1' @('-Provider',$provider,'-Attempt',$loginAttempt,'-Apply','-Interactive')
            $complete=Read-R5JsonFile (Join-Path (Join-Path $script:Base ('NativeAuthSix4.2.7-windows-20261011-r4-v1-'+$loginAttempt+'-'+$provider)) 'series-complete.json')
            if($code -eq 0 -and (Get-R5Member $complete 'all_slots_reuse_verified') -eq $true){
                $sessions[$provider].relogin='VERIFIED';$sessions[$provider].verified=6;$sessions[$provider].login_required=@()}
            else{$sessions[$provider].relogin=('UNVERIFIED (exit '+$code+')')}}}
    $script:R5.sessions=$sessions
    foreach($provider in @('claude','codex')){Say ($provider+': '+$sessions[$provider].verified+'/6 sessions verified'+$(if(@($sessions[$provider].login_required).Count){'; signed out: '+(@($sessions[$provider].login_required) -join ', ')}else{''})+$(if(@($sessions[$provider].hold).Count){'; unclear (held): '+(@($sessions[$provider].hold) -join ', ')}else{''})+'; re-login '+$sessions[$provider].relogin)}
    Write-R5Receipt 'S03' 'SESSIONS_RECORDED'}

function Invoke-R5Stage4 {
    Say 'S4: not used (addendum A5: NF-1 dropped)'
    Write-R5Receipt 'S04' 'NOT_USED'}

function Invoke-R5Stage5 {
    if($script:R5.gemini -cne 'attempt'){Say ('S5: skipped (Gemini '+$script:R5.gemini+')');Write-R5Receipt 'S05' 'SKIPPED';return}
    Say 'S5: Gemini signed-out capture on slot1 (about 3 min; two OAuth URLs are minted and abandoned by design)'
    $hex=New-R5HexAttempt;$script:R5.gemini_attempt=$hex;Add-R5TouchedRoot (Join-Path $script:Base ('AgyCapture4.2.7-windows-20261010-r4-v1-'+$hex+'-slot1-signed-out'))
    $run=Invoke-R5Child 'agy-status-capture-r4-v1.ps1 signed-out' 'agy-status-capture-r4-v1.ps1' @('-Slot','slot1','-Stage','signed-out','-Attempt',$hex,'-Apply')
    $json=Get-R5JsonTail $run.text;$mode=[string](Get-R5Member $json 'login_mode.mode')
    if($run.code -eq 0 -and (Get-R5Member $json 'gate.passed') -eq $true -and (Get-R5Member $json 'decision') -ceq 'COMPLETE' -and $mode -in @('print','tui')){
        $script:R5.login_mode=$mode;Say ('signed-out capture verified; login mode '+$mode) 'Green'}
    else{Set-R5GeminiHeld 'S5' ('the signed-out capture did not establish a sign-in path (exit '+$run.code+', login mode '+$(if($mode){$mode}else{'unknown'})+')')}
    Write-R5Receipt 'S05' $(if($script:R5.gemini -ceq 'attempt'){'PASSED'}else{'GEMINI_HELD'})}

function Invoke-R5Stage6 {
    if($script:R5.gemini -cne 'attempt'){Say ('S6: skipped (Gemini '+$script:R5.gemini+')');Write-R5Receipt 'S06' 'SKIPPED';return}
    Request-R5Attention 'six Google sign-ins for the Gemini workers start now (about 2-3 minutes each).'
    Write-Host 'For each slot: type READY when asked; open the printed Google URL in YOUR browser; sign in and approve;'
    Write-Host 'copy the code Google shows; paste it at the masked prompt; press Enter. Escape cancels that slot.'
    Write-Host 'If Google asks to verify your identity, offers an appeal or reports a rate limit: press Escape.'
    Write-Host 'Gemini is then held and the sitting continues with Claude and Codex.'
    $hex=$script:R5.gemini_attempt;Add-R5TouchedRoot (Join-Path $script:Base ('NativeAuthSix4.2.7-windows-20261011-r4-v1-'+$hex+'-gemini'))
    $code=Invoke-R5Attended 'login-six-workers-status-first-r4-v1.ps1' @('-Provider','gemini','-LoginMode',$script:R5.login_mode,'-Attempt',$hex,'-Apply','-Interactive')
    $root=Join-Path $script:Base ('NativeAuthSix4.2.7-windows-20261011-r4-v1-'+$hex+'-gemini');$script:R5.s6_root=$root
    $complete=Read-R5JsonFile (Join-Path $root 'series-complete.json')
    if($code -eq 0 -and (Get-R5Member $complete 'status') -ceq 'SIX_CONFIGURED_WORKERS_SUBSCRIPTION_AUTHENTICATION_VERIFIED' -and
       (Get-R5Member $complete 'all_slots_reuse_verified') -eq $true -and (Get-R5Member $complete 'selected_workers_verified') -eq 6){
        Say 'six Gemini worker sign-ins verified' 'Green'}
    elseif($code -eq 20){Set-R5GeminiHeld 'S6' 'the sign-in series paused (owner Escape, identity verification, appeal or rate limit)'}
    else{Set-R5GeminiHeld 'S6' ('the sign-in series did not verify all six slots (exit '+$code+')')}
    Write-R5Receipt 'S06' $(if($script:R5.gemini -ceq 'attempt'){'PASSED'}else{'GEMINI_HELD'})}

function Invoke-R5Stage7 {
    if($script:R5.gemini -cne 'attempt'){Say ('S7: skipped (Gemini '+$script:R5.gemini+')');Write-R5Receipt 'S07' 'SKIPPED';return}
    Say 'S7: Gemini signed-in capture on slot1 (about 2 min)'
    Add-R5TouchedRoot (Join-Path $script:Base ('AgyCapture4.2.7-windows-20261010-r4-v1-'+$script:R5.gemini_attempt+'-slot1-signed-in'))
    $run=Invoke-R5Child 'agy-status-capture-r4-v1.ps1 signed-in' 'agy-status-capture-r4-v1.ps1' @('-Slot','slot1','-Stage','signed-in','-Attempt',$script:R5.gemini_attempt,'-Apply')
    $json=Get-R5JsonTail $run.text;$root=[string](Get-R5Member $json 'target_root')
    if($run.code -eq 0 -and (Get-R5Member $json 'gate.passed') -eq $true -and (Get-R5Member $json 'decision') -ceq 'COMPLETE' -and $root){$script:R5.s7_root=$root;Say 'signed-in capture verified' 'Green'}
    else{Set-R5GeminiHeld 'S7' ('the signed-in capture did not confirm the model catalog (exit '+$run.code+')')}
    Write-R5Receipt 'S07' $(if($script:R5.gemini -ceq 'attempt'){'PASSED'}else{'GEMINI_HELD'})}

function Invoke-R5Stage8 {
    if($script:R5.gemini -cne 'attempt'){Say ('S8: skipped (Gemini '+$script:R5.gemini+')');Write-R5Receipt 'S08' 'SKIPPED';return}
    Say 'S8: Gemini isolation evidence on slot1 (up to five bounded model answers) and agent staging on all six slots (about 5 min)'
    $isolationRoot=Join-Path $script:Base ('AgyIsolation4.2.7-windows-20261011-r4-v1-'+$script:R5.gemini_attempt)
    Add-R5TouchedRoot $isolationRoot;Add-R5TouchedRoot ($isolationRoot+'-stage')
    $run=Invoke-R5Child 'agy-isolation-evidence-r4-v1.ps1 evidence (G3)' 'agy-isolation-evidence-r4-v1.ps1' @('-Slot','slot1','-EffortNullSlug',$script:R5.effort_null_slug,'-Attempt',$script:R5.gemini_attempt,'-Apply')
    $json=Get-R5JsonTail $run.text;$root=[string](Get-R5Member $json 'target_root')
    if($run.code -ne 0 -or -not $root){Set-R5GeminiHeld 'S8' ('isolation evidence '+$(if($run.code -eq 10){'gate failed (exit 10)'}else{'refused or held (exit '+$run.code+')'}))}
    else{
        $script:R5.s8_root=$root
        $stage=Invoke-R5Child 'agy-isolation-evidence-r4-v1.ps1 -StageOnly (G4)' 'agy-isolation-evidence-r4-v1.ps1' @('-StageOnly','-Attempt',$script:R5.gemini_attempt,'-Apply')
        $stageJson=Get-R5JsonTail $stage.text;$stageRoot=[string](Get-R5Member $stageJson 'target_root')
        if($stage.code -ne 0 -or -not $stageRoot){Set-R5GeminiHeld 'S8' ('six-slot agent staging '+$(if($stage.code -eq 10){'gate failed (exit 10)'}else{'refused or held (exit '+$stage.code+')'}))}
        else{$script:R5.s8_stage_root=$stageRoot;Say 'isolation evidence and six-slot agent staging passed' 'Green'}}
    Write-R5Receipt 'S08' $(if($script:R5.gemini -ceq 'attempt'){'PASSED'}else{'GEMINI_HELD'})}

function Invoke-R5Build {param([string]$Mode,[string]$Directory)
    # One builder run through the installed r5 interpreter (pin-checked) plus every INTERFACES-CONFIG check.
    $arguments=@('-I','-B',(Join-Path $script:Workspace 'build-pipeline-config-r5-candidate.py'),'--commissioned',$script:CommissionedR4Config)
    if($Mode -ceq 'attempt'){
        $arguments+=@('--login-root',$script:R5.s6_root,'--capture-root',$script:R5.s7_root,'--isolation-root',$script:R5.s8_root)
        if($script:R5.s8_stage_root -and $script:R5.s8_stage_root -cne ($script:R5.s8_root+'-stage')){$arguments+=@('--stage-root',$script:R5.s8_stage_root)}}
    $arguments+=@('--mode',$Mode,'--out-dir',$Directory)
    Say ('--- build-pipeline-config-r5-candidate.py --mode '+$Mode+' --out-dir '+$Directory)
    $run=Invoke-R5Python $arguments -PinName 'build-pipeline-config-r5-candidate.py'
    if($run.text){Write-Host $run.text}
    $fail={param($Why)[pscustomobject]@{ok=$false;reason=$Why;decision=$null;directory=$Directory;mode=$Mode}}
    if($run.code -ne 0){return (& $fail ('builder exit '+$run.code+': '+(Get-R5LastLine $run.text)))}
    $decision=Read-R5JsonFile (Join-Path $Directory 'decision.json');$candidate=Join-Path $Directory 'pipeline.json'
    if($null -eq $decision -or (Get-R5Member $decision 'schema') -cne 'cochem-r5-config-decision/1'){return (& $fail 'decision.json is missing or not cochem-r5-config-decision/1')}
    if(-not (Test-Path -LiteralPath $candidate -PathType Leaf)){return (& $fail 'pipeline.json is missing')}
    $sha=Get-R5FileSha256 $candidate;$length=(Get-Item -LiteralPath $candidate).Length
    if($sha -cne [string](Get-R5Member $decision 'candidate_sha256') -or $length -ne (Get-R5Member $decision 'candidate_length')){return (& $fail 'pipeline.json differs from decision.candidate_sha256/candidate_length')}
    $commissioned=[string](Get-R5Member $decision 'commissioned_sha256')
    if($commissioned -cne $script:CommissionedSha256 -or [string](Get-R5Member $decision 'commissioned_pin') -cne $script:CommissionedSha256){return (& $fail 'decision.commissioned_sha256/commissioned_pin is not the commissioned configuration 135cd9ec')}
    if([string](Get-R5Member $decision 'builder.python') -ine $script:R5Python -or (Get-R5Member $decision 'builder.isolated_mode') -ne $true -or
       [string](Get-R5Member $decision 'builder.script_sha256') -cne [string]$script:Pins['build-pipeline-config-r5-candidate.py']){return (& $fail 'decision.builder is not the pinned builder in isolated mode under the r5 interpreter')}
    $outcome=[string](Get-R5Member $decision 'outcome')
    if($outcome -ceq 'GEMINI_HELD_COMMISSIONED_BYTES'){if($sha -cne $commissioned){return (& $fail 'a held outcome must be the commissioned bytes')}}
    elseif($outcome -ceq 'GEMINI_CONTRACT'){
        $gates=Get-R5Member $decision 'gates';$failed=@(@('G1','G2','G3','G4','G5','G6')|Where-Object {(Get-R5Member (Get-R5Prop $gates $_) 'pass') -ne $true})
        $bindings=Get-R5Member $decision 'chosen_bindings'
        if($Mode -cne 'attempt' -or (Get-R5Member $decision 'mode') -cne 'attempt' -or $failed.Count -or $null -ne (Get-R5Member $decision 'error') -or
           $null -eq $bindings -or -not @($bindings.PSObject.Properties).Count -or $sha -ceq $commissioned){return (& $fail 'a GEMINI_CONTRACT outcome without mode attempt, six passed gates, error null and bindings')}}
    else{return (& $fail ('unknown outcome '+$outcome))}
    [pscustomobject]@{ok=$true;reason='';decision=$decision;directory=$Directory;mode=$Mode}}

function Set-R5Decision {param($Build)
    $decision=$Build.decision
    $script:R5.decision_outcome=[string](Get-R5Member $decision 'outcome');$script:R5.decision_mode=[string](Get-R5Member $decision 'mode')
    $script:R5.build_dir=$Build.directory;$script:R5.chosen_bindings=Get-R5Member $decision 'chosen_bindings'}

function Invoke-R5StageConfig {param($Build)
    # Stager plan, then -Apply, of one verified build into the next free WardenConfig attempt vC. Returns the staged path and
    # sha256, or the S9 reason; the caller chooses the Gemini held path (F3) or R4-RESTORE.
    $decision=$Build.decision;$outcome=[string](Get-R5Member $decision 'outcome')
    $configAttempt=Get-R5FreeAttempt $script:NsConfig;$script:R5.config_attempt=$configAttempt;Add-R5TouchedRoot (Join-Path $script:Base ($script:NsConfig+$configAttempt))
    $arguments=@('-BuildDirectory',$Build.directory,'-Attempt',$configAttempt)
    $plan=Invoke-R5Child ('stage-pipeline-config-r5-v1.ps1 plan -Attempt '+$configAttempt) 'stage-pipeline-config-r5-v1.ps1' $arguments
    $planLine=Get-R5JsonTail $plan.text
    if($plan.code -ne 0 -or (Get-R5Member $planLine 'status') -cne 'PLAN_OK'){
        return [pscustomobject]@{ok=$false;reason=('S9: the staging plan was refused (exit '+$plan.code+'): '+[string](Get-R5Member $planLine 'reason'));staged_path=$null;staged_sha256=$null}}
    $staged=Invoke-R5Child ('stage-pipeline-config-r5-v1.ps1 -Apply -Attempt '+$configAttempt) 'stage-pipeline-config-r5-v1.ps1' ($arguments+@('-Apply'))
    $line=Get-R5JsonTail $staged.text;$status=[string](Get-R5Member $line 'status')
    if($staged.code -ne 0 -or $status -notin @('STAGED','ALREADY_STAGED_IDENTICAL')){
        return [pscustomobject]@{ok=$false;reason=('S9: configuration staging failed (exit '+$staged.code+', status '+$status+'): '+[string](Get-R5Member $line 'reason'));staged_path=$null;staged_sha256=$null}}
    $stagedSha=[string](Get-R5Member $line 'staged_sha256');$stagedPath=[string](Get-R5Member $line 'staged_path')
    if($stagedSha -cne [string](Get-R5Member $decision 'candidate_sha256') -or [string](Get-R5Member $line 'outcome') -cne $outcome -or -not $stagedPath){
        return [pscustomobject]@{ok=$false;reason='S9: the staged configuration does not match the builder decision (sha256 or outcome)';staged_path=$null;staged_sha256=$null}}
    [pscustomobject]@{ok=$true;reason='';staged_path=$stagedPath;staged_sha256=$stagedSha}}

function Invoke-R5HeldConfig {param([string]$Stage,[string]$Directory)
    # Audit F3 (A4): a Gemini contract configuration could not be staged or previewed. Rebuild in held mode in a fresh directory
    # (the same builder checks) and stage it to the next WardenConfig attempt; a failure here is a hard failure (R4-RESTORE).
    Say ($Stage+': rebuilding the held configuration (commissioned bytes) and staging it to the next WardenConfig attempt') 'Yellow'
    $build=Invoke-R5Build 'held' $Directory
    if(-not $build.ok){Stop-R5Series ($Stage+': the held-mode rebuild after the Gemini failure failed ('+$build.reason+')') -Restore}
    Set-R5Decision $build
    $staged=Invoke-R5StageConfig $build
    if(-not $staged.ok){Stop-R5Series ($staged.reason+' (held-mode retry after the Gemini failure)') -Restore}
    $script:R5.staged_path=$staged.staged_path;$script:R5.staged_sha256=$staged.staged_sha256
    Say ('held configuration staged: '+$staged.staged_path) 'Green'}

function Invoke-R5Stage9 {
    Say 'S9: gated r5 configuration build and staging (about 2 min)'
    $mode=$(if($script:R5.gemini -ceq 'attempt'){'attempt'}else{'held'})
    $build=Invoke-R5Build $mode (Join-Path $script:SittingRoot ('S09-build-'+$script:Stamp+'-a'))
    if(-not $build.ok){
        Say ('builder result refused ('+$build.reason+'); retrying once in forced held mode') 'Yellow'
        if($mode -ceq 'attempt'){Set-R5GeminiHeld 'S9' ('the builder failed ('+$build.reason+'); forced held mode')}
        $build=Invoke-R5Build 'held' (Join-Path $script:SittingRoot ('S09-build-'+$script:Stamp+'-b'))
        if(-not $build.ok){Stop-R5Series ('S9: the configuration builder failed twice (last: '+$build.reason+')') -Restore}}
    $decision=$build.decision;$outcome=[string](Get-R5Member $decision 'outcome')
    if($script:R5.gemini -ceq 'attempt' -and $outcome -ceq 'GEMINI_HELD_COMMISSIONED_BYTES'){
        $gates=Get-R5Member $decision 'gates'
        $failed=@(@('G1','G2','G3','G4','G5','G6')|Where-Object {(Get-R5Member (Get-R5Prop $gates $_) 'pass') -ne $true}|ForEach-Object {$_+' '+[string](Get-R5Member (Get-R5Prop $gates $_) 'reason')})
        Set-R5GeminiHeld 'S9' ('builder gates failed: '+$(if($failed.Count){$failed -join '; '}else{[string](Get-R5Member $decision 'error')}))}
    Set-R5Decision $build
    $staged=Invoke-R5StageConfig $build
    if(-not $staged.ok){
        if($script:R5.decision_outcome -ceq 'GEMINI_CONTRACT'){
            Set-R5GeminiHeld 'S9' ('the Gemini configuration could not be staged ('+$staged.reason+')')
            Invoke-R5HeldConfig 'S9' (Join-Path $script:SittingRoot ('S09-build-'+$script:Stamp+'-held'))}
        else{Stop-R5Series $staged.reason -Restore}}
    else{
        $script:R5.staged_path=$staged.staged_path;$script:R5.staged_sha256=$staged.staged_sha256
        Say ('configuration staged ('+$script:R5.decision_outcome+'): '+$staged.staged_path) 'Green'}
    Write-R5Receipt 'S09' ([string]$script:R5.decision_outcome)}

function Invoke-R5Preview {
    # One upgrade preview (plan, then -Apply) of the staged configuration. Returns ok or the S10 reason.
    $hex=New-R5HexAttempt;$script:R5.preview_attempt=$hex;Add-R5TouchedRoot (Join-Path $script:Base ('UpgradePreview4.2.7-windows-20261011-r5-v1-'+$hex))
    $arguments=@('-Attempt',$hex,'-CandidateSha256',$script:R5.staged_sha256,'-Candidate',$script:R5.staged_path)
    $plan=Invoke-R5Child 'run-upgrade-preview-r5-v1.ps1 read-only plan' 'run-upgrade-preview-r5-v1.ps1' $arguments
    $planJson=Get-R5JsonTail $plan.text;$holds=@(Get-R5Member $planJson 'holds'|Where-Object {$null -ne $_})
    if($plan.code -ne 0 -or $holds.Count){
        return [pscustomobject]@{ok=$false;reason=('S10: the upgrade preview plan was refused (exit '+$plan.code+'): '+$(if($holds.Count){$holds -join ' | '}else{Get-R5LastLine $plan.text}))}}
    $run=Invoke-R5Child 'run-upgrade-preview-r5-v1.ps1 -Apply' 'run-upgrade-preview-r5-v1.ps1' ($arguments+@('-Apply'))
    $summary=Read-R5JsonFile (Join-Path (Join-Path $script:Base ('UpgradePreview4.2.7-windows-20261011-r5-v1-'+$hex)) 'preview-summary.json')
    if($run.code -ne 0 -or (Get-R5Member $summary 'decision') -cne 'PASSED'){
        return [pscustomobject]@{ok=$false;reason=('S10: the upgrade preview gate did not pass (exit '+$run.code+', decision '+[string](Get-R5Member $summary 'decision')+'): '+(Get-R5LastLine $run.text))}}
    if([string](Get-R5Member $summary 'install_after_sha256') -cne [string]$script:R5.install_after_sha256){
        return [pscustomobject]@{ok=$false;reason=('S10: the upgrade preview bound another r5 installation (install_after_sha256 '+[string](Get-R5Member $summary 'install_after_sha256')+', S1 recorded '+[string]$script:R5.install_after_sha256+')')}}
    [pscustomobject]@{ok=$true;reason=''}}

function Invoke-R5Stage10 {
    Say 'S10: upgrade preview of r5 against the staged configuration (one-shot SYSTEM task; about 2 min)'
    $preview=Invoke-R5Preview
    if(-not $preview.ok){
        if($script:R5.decision_outcome -ceq 'GEMINI_CONTRACT'){
            Set-R5GeminiHeld 'S10' ('the upgrade preview of the Gemini configuration did not pass ('+$preview.reason+')')
            Invoke-R5HeldConfig 'S10' (Join-Path $script:SittingRoot ('S10-build-'+$script:Stamp+'-held'))
            $preview=Invoke-R5Preview
            if(-not $preview.ok){Stop-R5Series ($preview.reason+' (held-mode retry after the Gemini failure)') -Restore}}
        else{Stop-R5Series $preview.reason -Restore}}
    Say 'upgrade preview gate passed' 'Green'
    Write-R5Receipt 'S10' 'PASSED'}

function Invoke-R5Stage11 {
    Say 'S11: retarget the Warden to r5 and start it once (DB backup, task update with the logon trigger, single Run; about 5 min)'
    $docker=Get-R5DockerInfo
    if(-not $docker.ok){Stop-R5Series ('Docker Desktop engine is not answering ('+$docker.reason+'). The cutover needs the engine; nothing was changed by S11. Start Docker Desktop, then rerun this same command (finished stages are skipped).')}
    $attempt=Get-R5FreeAttempt $script:NsRetargetR5
    $base=$script:R5.base_source;$sourceAttempt='';$stopAttempt=''
    if((Get-R5Member $base 'kind') -ceq 'r4-restore'){$sourceAttempt=[string](Get-R5Member $base 'source_attempt');$stopAttempt=[string](Get-R5Member $base 'stop_attempt')}
    (Assert-R5Pin 'retarget-warden-r5.ps1').stream.Dispose()
    $null=Write-R5Record 'S11-intent.json' ([ordered]@{schema='cochem-r5-sitting-intent/1';stage='S11';r5_attempt=$attempt;config=$script:R5.staged_path;source_attempt=$sourceAttempt;stop_attempt=$stopAttempt;written_utc=[DateTime]::UtcNow.ToString('o')})
    $script:R5.r5_attempt=$attempt
    $result=Invoke-R5Retarget 'r5' $script:R5.staged_path $attempt $sourceAttempt $stopAttempt
    if(-not $result.ok){Stop-R5Series ('S11: the r5 retarget/start did not verify ('+$result.detail+')') -Restore}
    $binding=Test-R5StartReceipt $result $attempt ([string]$script:R5.staged_sha256)
    if($binding){Stop-R5Series ('S11: the r5 start receipt does not bind this sitting: '+$binding) -Restore}
    $receipt=Read-R5JsonFile (Join-Path (Join-Path $script:Base ($script:NsRetargetR5+$attempt)) 'start-receipt.json')
    if([string](Get-R5Member $receipt 'config_mode') -cne $script:R5.decision_outcome){
        Stop-R5Series ('S11: the started r5 configuration mode ('+[string](Get-R5Member $receipt 'config_mode')+') differs from the builder decision ('+$script:R5.decision_outcome+')') -Restore}
    # Audit F2: r5 counts as running (verified) only once its start receipt binds this sitting.
    $script:R5.r5_running=$true
    Say ('r5 Warden running ('+$attempt+'), health verified by the retarget script; logon trigger registered') 'Green'
    Write-R5Receipt 'S11' 'WARDEN_R5_RUNNING_HEALTH_VERIFIED'}

function Set-R5CpuPauseNote {param([string]$Label)
    $script:R5.health_note=('admission was paused at '+$Label+' by the 5% Warden CPU budget alone')
    Say ($Label+': r5 health verified except admission: the controller''s CPU sample exceeds its 5% budget (no memory or recovery hold; r4 has the same budget). r5 is kept; S13 waits up to 10 minutes for admission.') 'Yellow'}

function Invoke-R5Stage12 {
    Say 'S12: r5 health gate'
    $check=Invoke-R5HealthCheck 'S12'
    if(-not $check.ok -and $check.cpu_paused){Set-R5CpuPauseNote 'S12';Write-R5Receipt 'S12' 'HEALTH_VERIFIED_ADMISSION_PAUSED_CPU';return}
    if(-not $check.ok){Stop-R5Series ('S12: the r5 health gate failed: '+$check.reason) -Restore}
    # Explicit acceptance field (audit F1): warden_controller.admission_ready, never the bare 'ready'.
    if((Get-R5Member $check.health 'components.warden_controller.admission_ready') -ne $true){Stop-R5Series 'S12: components.warden_controller.admission_ready is not true' -Restore}
    Write-R5Receipt 'S12' 'HEALTH_VERIFIED'}

function Invoke-R5GeminiFallback {param([string]$Reason)
    # Gemini preflight failed on the contract config: stop r5, retarget r5 to the commissioning (held) config, re-check health.
    Set-R5GeminiHeld 'S13' $Reason
    Say 'Gemini fallback: stop r5, restart r5 on the held commissioning configuration (about 8 min, unattended)' 'Yellow'
    $null=Write-R5Record 'fallback-intent.json' ([ordered]@{schema='cochem-r5-sitting-intent/1';stage='S13-fallback';from_attempt=$script:R5.r5_attempt;reason=$Reason;written_utc=[DateTime]::UtcNow.ToString('o')})
    $script:R5.fallback=$true
    $previous=$script:R5.r5_attempt;$stopAttempt=Get-R5FreeAttempt $script:NsStopR5
    $stop=Invoke-R5StopR5 $stopAttempt 'r5' $previous
    if(-not $stop.ok){$script:R5.r5_stop_held=$stop.held;Stop-R5Series ('Gemini fallback: stop-warden-r5 did not complete ('+$stop.detail+')') -Restore}
    $script:R5.r5_running=$false;$script:R5.r5_stopped=[pscustomobject]@{source_attempt=$previous;stop_attempt=$stopAttempt}
    $attempt=Get-R5FreeAttempt $script:NsRetargetR5;$script:R5.r5_attempt=$attempt
    $result=Invoke-R5Retarget 'r5' $script:CommissioningConfig $attempt $previous $stopAttempt
    if(-not $result.ok){Stop-R5Series ('Gemini fallback: the r5 retarget to the commissioning configuration did not verify ('+$result.detail+')') -Restore}
    $script:R5.r5_stopped=$null;$script:R5.decision_outcome='GEMINI_HELD_COMMISSIONED_BYTES';$script:R5.staged_path=$script:CommissioningConfig
    $binding=Test-R5StartReceipt $result $attempt $script:CommissionedSha256
    if($binding){Stop-R5Series ('Gemini fallback: the r5 start receipt does not bind this sitting: '+$binding) -Restore}
    $script:R5.r5_running=$true
    $check=Invoke-R5HealthCheck 'fallback'
    if(-not $check.ok -and $check.cpu_paused){Set-R5CpuPauseNote 'fallback';return}
    if(-not $check.ok){Stop-R5Series ('Gemini fallback: the r5 health gate failed: '+$check.reason) -Restore}}

function Invoke-R5Stage13 {
    Say 'S13: acceptance - wait for admission, then ONE provider preflight through the r5 controller'
    $admission=Wait-R5Admission
    if(-not $admission.ok){
        $script:R5.acceptance=('DEFERRED: admission stayed closed for 10 minutes ('+$admission.reason+'); not an r5 failure, r5 keeps running')
        Say $script:R5.acceptance 'Yellow';Write-R5Receipt 'S13' 'DEFERRED';return}
    $expect=($script:R5.decision_outcome -ceq 'GEMINI_CONTRACT')
    $preflight=Invoke-R5Preflight $expect 'pf'
    if(-not $preflight.ok -and $expect){
        Invoke-R5GeminiFallback $preflight.detail
        $admission=Wait-R5Admission
        if(-not $admission.ok){$script:R5.acceptance=('DEFERRED after the Gemini fallback: '+$admission.reason);Say $script:R5.acceptance 'Yellow';Write-R5Receipt 'S13' 'DEFERRED';return}
        $preflight=Invoke-R5Preflight $false 'fb'}
    if(-not $preflight.ok){
        # Audit F4: a claude/codex preflight that ended BLOCKED (routing_operator_limit twice) or TIMEOUT is a quota or capacity
        # wait that r4 would share, not an r5 failure: acceptance is deferred and r5 kept. FAILED or another provider restores.
        if([string]$preflight.status -in @('BLOCKED','TIMEOUT')){
            $script:R5.preflight=$preflight
            $script:R5.acceptance=('DEFERRED: the acceptance preflight ended '+$preflight.status+' ('+$preflight.detail+'); not an r5 failure (r4 shares the same quota), r5 keeps running')
            Say $script:R5.acceptance 'Yellow';Write-R5Receipt 'S13' 'DEFERRED';return}
        Stop-R5Series ('S13: the acceptance preflight failed: '+$preflight.detail) -Restore}
    if($expect -and -not $script:R5.fallback){$script:R5.gemini='active';$script:R5.gemini_reason=$null}
    $script:R5.preflight=$preflight
    $script:R5.acceptance=('PASSED: preflight '+$preflight.workflow_id+' COMPLETED on '+$preflight.provider+'/'+$preflight.model)
    Say $script:R5.acceptance 'Green'
    Write-R5Receipt 'S13' 'PASSED'}

function Invoke-R5Stage14 {
    if($script:SkipFixProof){$script:R5.fix_proof='SKIPPED (-SkipFixProof)';Say 'S14: skipped by -SkipFixProof';Write-R5Receipt 'S14' 'SKIPPED';return}
    if(-not ([string]$script:R5.acceptance).StartsWith('PASSED')){$script:R5.fix_proof='SKIPPED (acceptance not passed)';Say 'S14: skipped (acceptance not passed)';Write-R5Receipt 'S14' 'SKIPPED';return}
    Say 'S14: fix-proof tail (unattended, up to 20 min; soft checks only, nothing here changes the deployment; you may leave)'
    $planId=('r5sit-'+$script:Attempt+'-'+$script:Stamp+'-plan');$codeId=('r5sit-'+$script:Attempt+'-'+$script:Stamp+'-code')
    $record=[ordered]@{planning='NOT_SUBMITTED';coding='NOT_SUBMITTED';planning_workflow=$planId;coding_workflow=$codeId;health_samples=0;controller_admission_ready_samples=0;error=$null}
    try{
        $plan=Invoke-R5Control '/submit' ([ordered]@{objective='r5 fix-proof: a two-chapter plan for checking chapter WBS reconciliation on the Windows pipeline';
            requirements=@('REQ-001: each chapter declares only the work packages it owns','REQ-002: the plan stays under two pages');chapter_count=2;workflow_id=$planId})
        if($null -ne $plan){$record.planning='RUNNING'}else{$record.planning=('NOT_ACCEPTED: '+$script:R5LastControlError)}
        $code=Invoke-R5Control '/coding/submit' ([ordered]@{project_id='windows-acceptance';objective='r5 fix-proof: add one short comment line to the README describing the acceptance project';
            requirements=@('REQ-001: change only README.md','REQ-002: keep the existing line endings');workflow_id=$codeId})
        if($null -ne $code){$record.coding='RUNNING'}else{$record.coding=('NOT_ACCEPTED: '+$script:R5LastControlError)}
        $planDeadline=(Get-R5Now).AddSeconds(1200);$codeDeadline=(Get-R5Now).AddSeconds(900)
        while($record.planning -ceq 'RUNNING' -or $record.coding -ceq 'RUNNING'){
            Wait-R5Seconds 15
            $health=Get-R5Health
            if($null -ne $health){$record.health_samples++;if((Get-R5Member $health 'components.warden_controller.admission_ready') -eq $true){$record.controller_admission_ready_samples++}}
            if($record.planning -ceq 'RUNNING'){
                $workflow=Invoke-R5Control ('/workflow/'+$planId);$status=[string](Get-R5Member $workflow 'status')
                $chapters=@(@(Get-R5Member $workflow 'jobs')|Where-Object {(Get-R5Member $_ 'kind') -ceq 'CHAPTER_DRAFT'})
                if($status -ceq 'COMPLETED'){$record.planning='PASSED: workflow COMPLETED'}
                elseif($chapters.Count -ge 2 -and -not @($chapters|Where-Object {(Get-R5Member $_ 'status') -cne 'COMPLETED'}).Count){$record.planning='PASSED: both chapter drafts COMPLETED'}
                elseif($status -in @('FAILED','BLOCKED')){$record.planning=('SOFT FAIL: workflow '+$status)}
                elseif((Get-R5Now) -ge $planDeadline){$record.planning=('SOFT FAIL: not finished within 20 min (status '+$status+')')}}
            if($record.coding -ceq 'RUNNING'){
                $workflow=Invoke-R5Control ('/coding/workflow/'+$codeId);$status=[string](Get-R5Member $workflow 'status')
                if(@(@(Get-R5Member $workflow 'jobs')|Where-Object {(Get-R5Member $_ 'kind') -ceq 'CODE_PLAN' -and (Get-R5Member $_ 'status') -ceq 'COMPLETED'}).Count){$record.coding='PASSED: first CODE_PLAN COMPLETED'}
                elseif($status -in @('FAILED','BLOCKED')){$record.coding=('SOFT FAIL: workflow '+$status)}
                elseif((Get-R5Now) -ge $codeDeadline){$record.coding=('SOFT FAIL: no CODE_PLAN within 15 min (status '+$status+')')}}}
    }catch{$record.error=$_.Exception.Message}
    $script:R5.fix_proof=$record
    Say ('fix-proof: planning '+$record.planning+'; coding '+$record.coding+'; warden_controller.admission_ready in '+$record.controller_admission_ready_samples+' of '+$record.health_samples+' samples')
    Write-R5Receipt 'S14' 'RECORDED'}

# ================================================================== R4-RESTORE
function Invoke-R5Restore {param([string]$Reason)
    # Chooses the exact Cutover call for the state reached; never kills, never retries a held child.
    $state=Get-R5CutoverState
    Say ('R4-RESTORE: state '+$state.kind+' ('+$state.detail+')') 'Yellow'
    $script:R5.restore_kind=$state.kind
    if($state.kind -ceq 'none'){return [pscustomobject]@{ok=$true;restored=$false;kind='none';message='nothing to restore: r4 was never stopped and keeps running'}}
    if($state.kind -ceq 'blocked'){return [pscustomobject]@{ok=$false;restored=$false;kind='blocked';message=('no automatic restore: '+$state.detail)}}
    $docker=Get-R5DockerInfo
    if(-not $docker.ok){return [pscustomobject]@{ok=$false;restored=$false;kind=$state.kind;message=('no automatic restore: Docker Desktop engine is not answering ('+$docker.reason+'); r4 cannot start without the engine; the agent prepares the restore.')}}
    $null=Write-R5Record ('restore-intent-'+$script:Stamp+'.json') ([ordered]@{schema='cochem-r5-sitting-intent/1';stage='R4-RESTORE';state=$state;reason=$Reason;written_utc=[DateTime]::UtcNow.ToString('o')})
    if($state.kind -ceq 'r5-started' -or $state.kind -ceq 'r5-start-interrupted'){
        $stopAttempt=Get-R5FreeAttempt $script:NsStopR5
        $stop=Invoke-R5StopR5 $stopAttempt 'r5' $state.source -RecoverInterruptedStart:($state.kind -ceq 'r5-start-interrupted')
        if(-not $stop.ok){$script:R5.r5_stop_held=$stop.held;return [pscustomobject]@{ok=$false;restored=$false;kind=$state.kind;message=('stop-warden-r5 did not complete ('+$stop.detail+'); nothing was killed')}}
        $script:R5.r5_running=$false;$script:R5.r5_stopped=[pscustomobject]@{source_attempt=$state.source;stop_attempt=$stopAttempt}
        $state=[pscustomobject]@{kind='r5-stopped';source=$state.source;stop=$stopAttempt;detail='r5 stopped by the restore'}}
    $attempt=Get-R5FreeAttempt $script:NsRetargetR4;$sourceAttempt='';$stopAttempt=''
    switch -CaseSensitive ($state.kind){
        'base'{if((Get-R5Member $script:R5.base_source 'kind') -ceq 'r4-restore'){$sourceAttempt=[string]$state.source;$stopAttempt=[string]$state.stop}}
        'r5-never-started'{$sourceAttempt=[string]$state.source}
        'r5-retarget-held'{$sourceAttempt=[string]$state.source}
        'r5-stopped'{$sourceAttempt=[string]$state.source;$stopAttempt=[string]$state.stop}}
    $result=Invoke-R5Retarget 'r4' '' $attempt $sourceAttempt $stopAttempt
    $script:R5.restore=[ordered]@{state=$state.kind;attempt=$attempt;source_attempt=$sourceAttempt;stop_attempt=$stopAttempt;status=$result.status}
    if(-not $result.ok){return [pscustomobject]@{ok=$false;restored=$false;kind=$state.kind;message=('the r4 restore did not verify ('+$result.detail+')')}}
    [pscustomobject]@{ok=$true;restored=$true;kind=$state.kind;message=('r4 restarted and health verified (WardenRetarget r4 '+$attempt+')')}}

# ================================================================== plan, outcome, series
function Show-R5Plan {
    Say 'READ-ONLY PLAN (no -Apply): nothing is changed, no child is started.'
    $owner=$true
    try{Assert-R5OwnerShell;Say 'shell: elevated 64-bit Windows PowerShell 5.1 as AETHERDESK\ansac'}catch{$owner=$false;Say ('shell: '+$_.Exception.Message.Replace('SERIES-STOP: ',''))}
    # The S0 runtime-process precheck, read-only; without elevation other accounts' python processes cannot be read.
    try{
        $presence=Get-R5RuntimePresence (Get-R5ProcessList)
        $blocking=@(@($presence.unclassified)+@($(if($owner){@($presence.uninspectable)}else{@()})))
        Say ('runtime processes: '+@($presence.clients).Count+' MCP client(s) recognised, '+@($presence.observers).Count+' observer recorder(s), '+@($presence.controllers).Count+' controller process(es)'+
            $(if($blocking.Count){'; S0 would STOP on: '+(@($blocking|ForEach-Object {Format-R5Process $_}) -join '; ')}else{'; none unclassified'})+
            $(if(-not $owner -and @($presence.uninspectable).Count){' ('+@($presence.uninspectable).Count+' python process(es) unreadable without elevation; S0 reads them elevated)'}else{''}))}
    catch{Say ('runtime processes: the process list could not be read ('+$_.Exception.Message+')')}
    $drift=@(Get-R5PinDrift)
    Say ('pins: '+$(if($drift.Count){'NOT READY - '+($drift -join ', ')}else{[string]$script:Pins.Count+' reviewed files match'}))
    $docker=Get-R5DockerInfo;Say ('docker: '+$docker.reason)
    $warden=Read-R5Warden
    if($warden.readable){
        Say ('Warden task: source '+$warden.source+$(if($warden.source_attempt){' '+$warden.source_attempt}else{''})+', enabled '+$warden.enabled+', instances '+$warden.instances+', port 47824 listeners '+$warden.listening)
        $s2=$(if($warden.source -ceq 'r4-v1' -and ($warden.running -or $warden.enabled)){'S2 runs stop-warden-r4 ('+$(if($warden.running){'End + disable'}else{'disable only'})+')'}
              elseif($warden.source -ceq 'r4-v1'){'S2 is skipped (already disabled, no instance)'}
              elseif($warden.source -ceq 'r4-restore'){'S2 runs stop-warden-r5 -RetargetTarget r4 -RetargetAttempt '+$warden.source_attempt+$(if($warden.running){' (r4 is running: idle proof, End, disable; it is stopped first)'}else{''})}
              else{'S0 would STOP: not a reviewed r4 action'})
        Say $s2}
    else{Say ('Warden task: unreadable here ('+$warden.error+'); run elevated to see it')}
    if(Test-Path -LiteralPath (Join-Path $script:SittingRoot 'sitting-end.json')){Say ('S0 would STOP: sitting attempt '+$script:Attempt+' has already ended; the agent names the next -Attempt')}
    $earlier=@(Get-R5EarlierSittings)
    foreach($sitting in $earlier){Say (Format-R5EarlierSitting $sitting)}
    $open=@($earlier|Where-Object {-not $_.ended})
    if($open.Count){Say ('S0 would STOP: sitting attempt '+(@($open|ForEach-Object {$_.attempt}) -join ', ')+' never ended (rerun that attempt instead)')}
    elseif($earlier.Count){Say 'leftovers of earlier sittings block nothing (fresh child names, next free namespaces)'}
    else{Say 'earlier sittings: none found here'}
    Say ('Gemini: '+$script:Gemini+'; effort-null slug '+$script:EffortNullSlug+'; fix-proof tail '+$(if($script:SkipFixProof){'skipped'}else{'included'}))
    Say ('sitting root: '+$script:SittingRoot)
    foreach($line in @('S0 preconditions','S1 install r5 (install-stopped-runtime-r5.ps1 plan, then -Apply)','S2 stop/disable the r4 Warden (conditional)',
        'S3 Claude/Codex session health x12 (one Y/N only if a slot is signed out)','S4 not used (A5)','S5 Gemini signed-out capture','S6 six Google sign-ins (attended)',
        'S7 Gemini signed-in capture','S8 Gemini isolation evidence + six-slot agent staging','S9 gated config build + staging','S10 upgrade preview',
        'S11 retarget the Warden to r5 + single start (logon trigger)','S12 r5 health gate (admission_ready)','S13 admission + one preflight (Gemini fallback if needed)',
        'S14 fix-proof tail (soft)','R4-RESTORE automatically on a hard failure after the Warden was stopped')){Write-Host ('  '+$line)}
    Say ('To run it: add -Apply to the same command line.')}

function Write-R5Outcome {param([string]$Phase)
    $s=$script:R5;$lines=@()
    foreach($provider in @('claude','codex')){
        $name=$(if($provider -ceq 'claude'){'Claude  '}else{'Codex   '})
        $row=Get-R5Member $s.sessions $provider
        if($null -eq $row){$lines+=($name+': sessions not checked in this sitting');continue}
        $out=([string](Get-R5Member $row 'verified')+'/6 worker sessions verified')
        $missing=@(Get-R5Member $row 'login_required'|Where-Object {$_});$held=@(Get-R5Member $row 'hold'|Where-Object {$_})
        if($missing.Count){$out+=('; signed out: '+($missing -join ', ')+' (jobs there wait until you sign them in)')}
        if($held.Count){$out+=('; status unclear: '+($held -join ', '))}
        $lines+=($name+': '+$out)}
    $verified=([bool]$s.r5_running -and $Phase -cne 'stopped')
    $gemini=switch -CaseSensitive ([string]$s.gemini){'active'{'ACTIVE - the acceptance preflight answered on Gemini'}'skip'{'SKIPPED (-Gemini skip); Gemini stays held'}
        'held'{'HELD - '+[string]$s.gemini_reason+' (the pipeline routes around Gemini)'}
        default{$(if($verified -and [string]$s.decision_outcome -ceq 'GEMINI_CONTRACT'){'CONFIGURED, NOT YET PROVEN (acceptance did not run)'}else{'NOT DEPLOYED - the sitting ended before r5 ran the Gemini configuration'})}}
    $lines+=('Gemini  : '+$gemini)
    $restored=($null -ne $s.restore -and [string](Get-R5Member $s.restore 'status') -ceq 'WARDEN_R4_RESTARTED_HEALTH_VERIFIED')
    $atS1=([string]$s.current_stage -ceq 'S01')
    # Audit F2: after a STOP the Warden line reports the live task, read now, not what the sitting hoped for.
    $live=$null
    if($Phase -ceq 'stopped'){try{$live=Read-R5Warden}catch{$live=$null}}
    $rollback=''
    if($null -ne $s.restore_ok -and -not $s.restore_ok){
        $message=[string]$s.restore_message
        $rollback=$(if($message.StartsWith('stop-warden-r5 did not complete')){' (rollback stop refused)'}elseif($message.StartsWith('no automatic restore')){' (no automatic rollback)'}else{' (rollback not done)'})}
    $warden=$(if($verified){'r5 RUNNING (health verified'+$(if($s.health_note){'; '+[string]$s.health_note}else{''})+')'}
              elseif($restored -and $atS1){'r4 RESTORED, r5 not installed: '+[string]$s.stop_reason}
              elseif($restored){'r4 RESTORED and running (r5 not deployed)'}
              elseif($Phase -ceq 'stopped' -and ($null -eq $live -or -not $live.readable)){'UNKNOWN - the Warden task could not be read ('+[string](Get-R5Member $live 'error')+'); the agent reviews the log'}
              elseif($null -ne $live -and $live.running -and $live.source -ceq 'r5'){'r5 RUNNING, NOT VERIFIED'+$rollback}
              elseif($null -ne $live -and $live.source -ceq 'r5'){'r5 task registered but NOT RUNNING - the agent reviews the log'}
              elseif($null -ne $live -and $live.running -and $live.source -in @('r4-v1','r4-restore')){$(if(-not $s.s2_attempted){'r4 still running (never stopped)'}else{'r4 RUNNING (not restored by this sitting) - the agent reviews the log'})}
              elseif($null -ne $live -and $live.running){'RUNNING an unrecognized task action - the agent reviews the log'}
              elseif($atS1 -and $null -ne $s.restore_ok -and -not $s.restore_ok){'pipeline DOWN as before this sitting'}
              elseif(-not $s.s2_done -and -not $s.s2_attempted){'DOWN as before this sitting (r4 was not running; this sitting did not touch the Warden)'}else{'DOWN - the agent reviews the log'})
    $lines+=('Warden  : '+$warden)
    $reboot=$(if($verified){'SAFE - logon trigger for AETHERDESK\ansac: after any reboot the pipeline restarts itself about 1-16 minutes after you sign in (it waits for Docker Desktop)'}
              elseif($null -ne $live -and $live.readable -and $live.source -ceq 'r5'){'NOT VERIFIED - this sitting did not verify the r5 task; its logon trigger may start it at the next sign-in; the agent reviews it'}
              else{'NOT reboot-safe (r4 has no logon trigger)'})
    $lines+=('Reboot  : '+$reboot)
    if($null -ne $s.routing_holds){$kinds=@(Get-R5Member $s.routing_holds 'kinds'|Where-Object {$_})
        $lines+=('Holds   : '+[string](Get-R5Member $s.routing_holds 'count')+' active routing hold(s)'+$(if($kinds.Count){': '+($kinds -join ', ')}else{''})+' (reported, not gated)')}
    if($null -ne $s.acceptance){$lines+=('Accept  : '+[string]$s.acceptance)}
    if($null -ne $s.fix_proof){$lines+=('FixProof: '+$(if($s.fix_proof -is [string]){$s.fix_proof}else{'planning '+[string](Get-R5Member $s.fix_proof 'planning')+'; coding '+[string](Get-R5Member $s.fix_proof 'coding')}))}
    $held=@(Get-R5HeldRecords)
    if($held.Count){$lines+=('Held    : '+($held -join '; '))}
    $lines+=('Log     : '+$script:Log)
    $lines+=('Sitting root: '+$script:SittingRoot)
    Write-Host '';Write-Host ('OUTCOME ('+$Phase+')') -ForegroundColor Cyan
    foreach($line in $lines){Write-Host ('  '+$line)}}

function Invoke-R5Series {
    $ErrorActionPreference='Stop';Set-StrictMode -Version Latest
    if(-not (Test-Path -LiteralPath 'variable:script:R5Initialized') -or -not $script:R5Initialized){Initialize-R5Paths}
    if(-not $script:Apply){Show-R5Plan;exit 0}
    try{Start-Transcript -Path $script:Log -Force|Out-Null}catch{}
    $outcome=1
    $stages=@(@{id='S01';run={Invoke-R5Stage1}},@{id='S02';run={Invoke-R5Stage2}},@{id='S03';run={Invoke-R5Stage3}},@{id='S04';run={Invoke-R5Stage4}},
              @{id='S05';run={Invoke-R5Stage5}},@{id='S06';run={Invoke-R5Stage6}},@{id='S07';run={Invoke-R5Stage7}},@{id='S08';run={Invoke-R5Stage8}},
              @{id='S09';run={Invoke-R5Stage9}},@{id='S10';run={Invoke-R5Stage10}},@{id='S11';run={Invoke-R5Stage11}},@{id='S12';run={Invoke-R5Stage12}},
              @{id='S13';run={Invoke-R5Stage13}},@{id='S14';run={Invoke-R5Stage14}})
    try{
        $script:R5.current_stage='S00'
        Invoke-R5Stage0
        foreach($stage in $stages){
            if($script:R5Done.ContainsKey($stage.id)){Say ($stage.id+': already done by this attempt (receipt verified); skipped');continue}
            $script:R5.current_stage=$stage.id
            & $stage.run
            if($stage.id -ceq 'S13'){Write-R5Outcome 'deployment complete; the fix-proof tail follows'}}
        $script:R5.current_stage='DONE'
        Write-R5Outcome 'final'
        Write-Host '';Write-Host 'DONE: the 4.2.7 pipeline runs on r5.' -ForegroundColor Green
        $null=Write-R5Record 'sitting-end.json' ([ordered]@{schema='cochem-r5-sitting-end/1';attempt=$script:Attempt;outcome='DEPLOYED';state=$script:R5;written_utc=[DateTime]::UtcNow.ToString('o')})
        $outcome=0
    }catch{
        $message=$_.Exception.Message
        $position=$(if($null -ne $_.InvocationInfo){[string]$_.InvocationInfo.PositionMessage}else{''})
        $planned=$message.StartsWith('SERIES-STOP: ')
        $reason=$(if($planned){$message.Substring(13)}else{'Unexpected error: '+$message+' at '+$position})
        $stageAt=[string]$script:R5.current_stage
        # An unexpected error from S1 on is a hard failure as well: restore r4 when the state allows it (never at S0).
        $restoreWanted=([bool]$script:R5['pending_restore'] -or (-not $planned -and $stageAt -notin @('S00','DONE')))
        $script:R5.stop_reason=$reason
        $restore=$null
        if($restoreWanted){
            try{$restore=Invoke-R5Restore $reason}catch{$restore=[pscustomobject]@{ok=$false;restored=$false;kind=[string]$script:R5.restore_kind;message=('the restore itself failed: '+$_.Exception.Message.Replace('SERIES-STOP: ',''))}}
            $script:R5.restore_ok=[bool]$restore.ok;$script:R5.restore_message=[string]$restore.message}
        Write-Host '';Write-Host ('STOP at '+$stageAt+': '+$reason) -ForegroundColor Red
        if($null -ne $restore){
            if($restore.ok){Write-Host ('R4-RESTORE: '+$restore.message) -ForegroundColor Yellow}
            else{Write-Host ('R4-RESTORE NOT DONE: '+$restore.message) -ForegroundColor Red}}
        try{Write-R5Outcome 'stopped'}catch{}
        Write-Host ('Log: '+$script:Log);Write-Host 'Send the log to the agent; do not start, stop or retarget anything by hand.'
        if($null -ne $restore -and [string]$restore.kind -cne 'none'){try{$null=Write-R5Record 'sitting-end.json' ([ordered]@{schema='cochem-r5-sitting-end/1';attempt=$script:Attempt;outcome='STOPPED';stage=$stageAt;reason=$reason;
            restore_ok=$restore.ok;restore_message=$restore.message;state=$script:R5;written_utc=[DateTime]::UtcNow.ToString('o')})}catch{}}
    }finally{try{Stop-Transcript|Out-Null}catch{}}
    exit $outcome}

# Invocation boundary: the harness loads the functions above from the AST without running this statement.
if($MyInvocation.InvocationName -ne '.'){Invoke-R5Series}
