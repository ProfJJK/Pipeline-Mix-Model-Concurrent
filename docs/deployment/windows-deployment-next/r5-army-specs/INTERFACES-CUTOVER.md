# Cutover interfaces for RUN_427_R5_SITTING.ps1 (final, 2026-10-11; audit fix wave C-F1..C-F8, re-audit R-F1/R-F3/R-F4)

Files (LF, ASCII; pin by sha256, never convert line endings):
- retarget-warden-r5.ps1 991703ab10b7bf280fb092ec984e79d1095379070857e7c2859d0a5ba0c0dee7 (sitting repair 2026-10-11 evening:
  no Validate* on the parameter variables, $held renamed in the lineage checks, Antigravity bridge = client; harness 530 passed;
  was 97403e81)
- stop-warden-r5.ps1 b5920f379cee10eba101b87adb40b6a500d1bf5f29300f3e56a025182ee407a9 (sitting repair: Read-StartReceipt $held trap,
  bridge = client; harness 570 passed; adds -RecoverInterruptedStart; was 6e519927)
- stop-warden-r4.ps1 43fc386b1984447c1d5304a8297932c8f825735562b5dbc5dc3f23a211adbe7e (sitting repair: bridge = client; was bd54cb81)
Both: exit 0 = plan or success result; exit 1 = refusal or held (terminating error). Without -Apply only a plan.
Results: cochem-warden-retarget-result/3, cochem-warden-start-result/3, cochem-warden-stop-result/2 (status, receipt_path, receipt_sha256).
Roots: WardenRetarget4.2.7-windows-20261011-<r5|r4>-<Attempt>; every stop: WardenStop4.2.7-windows-20261011-r5-<Attempt>.
Date 20261011 is fixed in both scripts. Attempt namespaces are never reused.

Source states (all need 0 instances, port 47824 free, no worker/controller). No new parameter selects them: the live action
picks r4-v1, an r5 attempt or an r4 restore attempt (-SourceAttempt), and the evidence in that attempt's root picks the state.
- r4-v1 (NOW; no attempt params).
- r5-retarget-receipt / r4-restore-retarget-receipt (-SourceAttempt only): retargeted, never started, or held before Run
  (start-held.json held_before_run true, incl. a Run that threw with no instance, C-F7); task and logon trigger disabled.
- r5-retarget-held / r4-restore-retarget-held (-SourceAttempt only, -Target r4 ONLY): the TASK_UPDATE was held at its readback
  (retarget-held.json MUTATION_READBACK: readback disabled, 0 instances, live XML sha == readback sha, live action ==
  retarget-intent.json action_after) or interrupted/crashed before retarget-receipt.json (intent only; live XML is exactly the
  intended one: action, description, disabled task and trigger, SDDL and before-XML outside the retarget fields).
- r5-receipt / r4-restore-receipt (both): started (start receipt, warden-task-started.xml), then stopped by stop-warden-r5.
- r5-start-held / r4-restore-start-held (both): a start with start-intent.json that ran but wrote no start receipt (interrupted,
  crashed, or held after Run before or after its health gate; start-held.json held_before_run false), then stopped by
  stop-warden-r5 -RecoverInterruptedStart.
Every started or stopped source's live XML equals its own warden-task-after.xml (whose Description names the attempt) outside
the task and trigger Enabled flags (C-F5).

Two-phase start (crash-safe): every TASK_UPDATE registers the task DISABLED and the r5 logon trigger DISABLED
(retarget-receipt trigger_enabled_after false; r4 null). -Start enables the task, Runs once, waits for the health gate
(r5 admission_ready; r4 records warden_controller.ready but does not gate on it, C-F6), reads back and proves the process;
only then (r5) a second TASK_UPDATE enables the logon trigger, is read back (trigger enabled, same instance, SDDL equal, XML
equal outside the Enabled flags), warden-task-started.xml is written, and start-receipt.json is written last (task_xml_sha256 ==
task_xml_started_sha256, trigger_enabled_before false, trigger_enabled_after true; r4 both null). A crash before that leaves
at most a task whose trigger is disabled. -Start, -StartOnly and -Apply -Start continuing an attempt only start the task THAT
attempt registered: the live XML must equal the attempt's digest-bound warden-task-after.xml outside the Enabled flags, and its
Description must name the attempt (R-F3).

Held or interrupted start: the task is disabled again (best effort, never End) and start-held.json (cochem-warden-start-held/3)
records interrupted (true only from the Ctrl+C/closed-console finally, C-F1a), stage (BEFORE_RUN | RUN | HEALTH_WAIT |
POST_START_READBACK | TRIGGER_ENABLE | RECEIPT), health_gate_passed, stop_recovery_allowed (= not held_before_run, or interrupted;
R-F1), run_requested, run_exception, held_before_run, trigger_enable_requested, trigger_enabled_after (as read back),
receipt_written false. Once start-receipt.json exists the interruption finally writes nothing (R-F4).

Stop receipt fields this retarget binds (FIXD-STOP): start_binding START_RECEIPT | START_INTERRUPTED_HELD |
START_HELD_AFTER_HEALTH_GATE | START_HELD_BEFORE_HEALTH_GATE | START_CRASHED_NO_RECORD, start_receipt_sha256, retarget_receipt_sha256, start_intent_sha256,
start_held_sha256, source_task_xml_after_sha256, trigger_enabled_after (live; r4 null), task_xml_after_sha256 (live).

## Calls (run from W, owner, elevated 64-bit WinPS 5.1; check exit 0 and receipt status)
- S11 cutover from r4-v1:
  .\retarget-warden-r5.ps1 -Target r5 -Config "C:\Program Files\CoChem\WardenConfig4.2.7-windows-20261011-r5-v1\pipeline.json" -Attempt v1 -Apply -Start
  expect start-receipt status WARDEN_R5_RUNNING_HEALTH_VERIFIED and trigger_enabled_after true
- Gemini fallback after r5 v1 started:
  .\stop-warden-r5.ps1 -Apply -Attempt v1 -RetargetTarget r5 -RetargetAttempt v1
  .\retarget-warden-r5.ps1 -Target r5 -Config "C:\Program Files\CoChem\WardenCommissioning4.2.7-windows-20261007-r3-v1\pipeline.json" -Attempt v2 -SourceAttempt v1 -StopAttempt v1 -Apply -Start
- R4-RESTORE:
  if S11 never applied:      .\retarget-warden-r5.ps1 -Target r4 -Attempt v1 -Apply -Start
  r5 v1 never started/held before Run: .\retarget-warden-r5.ps1 -Target r4 -Attempt v1 -SourceAttempt v1 -Apply -Start
  r5 vN held at its task update (retarget-held.json MUTATION_READBACK) or interrupted before its retarget receipt:
                             .\retarget-warden-r5.ps1 -Target r4 -Attempt vM -SourceAttempt vN -Apply -Start
  after r5 vN started:       .\stop-warden-r5.ps1 -Apply -Attempt vK -RetargetTarget r5 -RetargetAttempt vN
                             .\retarget-warden-r5.ps1 -Target r4 -Attempt vM -SourceAttempt vN -StopAttempt vK -Apply -Start
  r5 vN start held or interrupted after Run, or crashed (no start receipt; start-held.json held_before_run false and
  stop_recovery_allowed true, or start-intent.json alone), e.g. an S11 knowledge-not-ready or quarantine hold:
                             .\stop-warden-r5.ps1 -Apply -Attempt vK -RetargetTarget r5 -RetargetAttempt vN -RecoverInterruptedStart
                             .\retarget-warden-r5.ps1 -Target r4 -Attempt vM -SourceAttempt vN -StopAttempt vK -Apply -Start
  expect WARDEN_R4_RESTARTED_HEALTH_VERIFIED
- r5 retry with another config from a never-started r5 v1:
  .\retarget-warden-r5.ps1 -Target r5 -Config "<cfg>" -Attempt v2 -SourceAttempt v1 -Apply -Start
- Restored r4 back to r5 later: stop -RetargetTarget r4 -RetargetAttempt vM (add -RecoverInterruptedStart for an interrupted r4
  start), then retarget -Target r5 -SourceAttempt vM -StopAttempt vK2; an r4 restore retargeted but never started goes back to
  r5 directly with -Target r5 -SourceAttempt vM (C-F3).

## Sitting rules from Cutover flags
- Run S11 only when `docker info` already answers: the retarget health gate waits 240 s, the daemon may wait 900 s.
- Only a hold before Run (start-held.json held_before_run true) avoids the stop: recover it with -SourceAttempt alone (the
  retarget-receipt states). Every hold after Run (held_before_run false: health gate timeout or hard gate, process proof,
  readback, trigger enable, receipt), every interruption after Run and every crash uses stop-warden-r5 -RecoverInterruptedStart,
  then -SourceAttempt with -StopAttempt (R-F1). The task is always left disabled; nothing is ended by the held start.
- The logon-trigger user readback is compared by SID (AETHERDESK\ansac, its SID or another spelling of it pass); a real
  mismatch holds after the update (retarget-held.json MUTATION_READBACK) -> R4-RESTORE from that attempt (-Target r4
  -SourceAttempt vN, source r5-retarget-held; the recorded readback binds the live task).
- The r5 runtime must carry the reviewed freeze (source-manifest sha 5d8d337b..., its 13 repair digests, pyvenv.cfg 0c2b1a15...,
  venv launcher 560b9ef7...), no install-held.json, and install-after r5_repairs_installed / installed_repairs_verified true with
  verified_unchanged 153 (C-F4). A staged config needs its cochem-config-only-staging/2 staging receipt naming its sha beside it
  and no staging-held-*.json (C-F8).
- After any reboot, stop-warden-r5 refuses as not idle for up to ~16 min (1-min trigger delay + Docker wait).
- Health gate uses warden_controller.admission_ready for r5 (audit F1); never the bare 'ready' field for acceptance traces.
