# r5 sitting v2 (2026-10-11 20:27) - diagnosis

Three read-only agents (workflow r5-sitting-repair-2, about 20:50-21:00 CDT) diagnosed the holds of the owner's
second sitting (`RUN_427_R5_SITTING.ps1 -Apply -Attempt v2`, log `r5-sitting-20261011-202738.log`).
The repair itself was still running when this file was written; the handoff
(`docs/WINDOWS_AGENT_HANDOFF_4.2.7_2026-10-11.md`) records its final result.

**Root cause in one line:** five scripts written on 2026-10-10/11 register their one-shot SYSTEM tasks with
flags 2 (TASK_CREATE) and then apply the exact two-ACE descriptor check from `register-stopped-warden-r3.ps1`.
On this host a flags-2 registration reads back unprotected with an extra principal FR ACE, so the check
always fails. The repair proven on 2026-10-09 is flags 18 (TASK_CREATE | TASK_DONT_ADD_PRINCIPAL_ACE).

## Inventory of every scheduled-task operation the sitting can reach (diag-registration)

The Commander's hypothesis holds for all three held calls. In each one the cause is RegisterTaskDefinition(..., flags 2, 'SYSTEM', $null, 5, 'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'), followed by an exact read-back of the descriptor.

**The validator.** Assert-RegisteredTaskAcl in W\register-stopped-warden-r3.ps1 lines 81-93 (pin eccc593f) reads RawSecurityDescriptor(GetSecurityDescriptor(7)). It requires:
- owner SY or BA
- the DACL Protected flag set
- exactly 2 ACEs, each AccessAllowed, AceFlags None, mask 2032127 (FA), SID SY or BA, no duplicates

It does not look at the group, the AI flag or the backing file.

**What this host returns.** The owner-observed SYSTEM task in pending-warden-recovery-v7-preparation-20261008.json had owner/group BA, an unprotected DACL and three ACEs: SY FA, BA FA and SY FR (1179785). That fails both the protection test and the count test. The first throw is exactly the logged text 'Registered task ownership/private DACL differs.'. The fixtures (task-scheduler-acl-roundtrip-...-final.json and convert16) show the same pattern: flags 2 gives the requested ACEs plus an appended principal FR ACE and no P flag, while flags 18 gives 'D:PAI' with exactly the requested ACEs.

**Flags 18 has already passed this exact validator on this host:**
- resume-pending-warden-r3-v7.ps1:125 registered the SYSTEM commissioning task with flags 18.
- Assert-FirstStartTask (commission-first-warden-r3-v5.ps1:46, exact validator) ran before the Run at line 132.
- commissioning.json exists (sha 4bf82adb, recorded in the 10-09 handoff) and the controller then ran.

**Why the r3 scripts passed.** The r3 status leaves (check-worker-native-auth-status-six-r3-v1..v4, lines 226-240) and the r3_v6 Claude login child also use flags 2, but they never read the descriptor back. The r4-v1/r5 leaves added the exact read-back without the flags-18 repair. Their pytest fixtures also return the requested SDDL verbatim, so they could never catch this.

**Backing file.** No validator reachable from the sitting reads C:\Windows\System32\Tasks\<name>. Only task-private-acl-v8.ps1 (pin f48d47e3, used by the 10-09 supervisor-observation installer and by the v7 recovery) does. It accepts the unprotected SY FA/BA FA/SY FR projection only if all of these hold:
- the task name matches ^CoChem-4.2.7-
- the backing file is an ordinary file of 1..131072 bytes and not a reparse point
- custody is held through Open-VerifiedFile
- Get-Acl shows owner SY or BA, a protected DACL and exactly SY FA + BA FA with no ACE flags

**Full inventory of scheduled-task operations reachable from RUN_427_R5_SITTING.ps1:**

1. The runner itself only reads, through Get-R5WardenState (lines 409-425, COM GetTask, Definition and GetInstances).
2. S1 install-stopped-runtime-r5.ps1 only reads (GetTask at :198 and :281). It was skipped in v2.
3. S2 stop-warden-r4.ps1 calls Stop(0) at :635 and Enabled=$false at :646. Its validators are the exact check at :345 and :367 plus a before/after SDDL string-equality check at :366. These passed today.
4. stop-warden-r5.ps1 (S2 from an r4-restore base, the S13 fallback and the R4-RESTORE kinds) calls Stop(0) at :1203 and Enabled=$false at :1215. Validators are at :849, :861 and :881. It runs on the same canonical Warden descriptor, so it passes.
5. **S3 status leaf FAILS** (12 observed). check-worker-native-auth-status-six-r4-v1.ps1:303 uses flags 2; the validator is at :289.
   - The S3 attended series and the S6 Gemini series (login-six-workers-status-first-r4-v1.ps1) run the same leaf for every slot, before and after login, so they fail too.
   - The S3 Claude login child (login_pipeline_worker_interactive_r3_v6.ps1:144, flags 2, Run at :145) has no descriptor check and does not fail.
   - The Codex InstallGuard child (login_pipeline_worker.ps1:83, read-only) uses Register-ScheduledTask with the default SD, then Start, Stop on timeout and Unregister in a finally. It has no validator and does not fail.
6. **S5 and S7 capture FAIL** (S5 observed). agy-status-capture-r4-v1.ps1:421 uses flags 2; the validator is at :186.
7. **The S6 agy login wrapper WOULD FAIL.** login_pipeline_worker_interactive_agy_r4_v1.ps1:486 uses flags 2; the validator is at :232.
8. **The S8 isolation evidence and -StageOnly runs WOULD FAIL.** agy-isolation-evidence-r4-v1.ps1:1173 uses flags 2; the validator is at :294.
9. S9: neither the builder nor the stager touches any task.
10. **The S10 preview FAILS** (observed). run-upgrade-preview-r5-v1.ps1:496 uses flags 2; the validator is at :273. The F3 second preview after a Gemini held rebuild would fail the same way.
11. S11 and the S13 fallback use retarget-warden-r5.ps1 -Target r5:
    - TASK_UPDATE flags 4 at :1266, keeping the live SDDL
    - Enabled=$true at :1408 and Run at :1410
    - a second flags-4 update at :1454 to enable the trigger
    - Enabled=$false at :1361 on a held start
    - validators: Assert-RetargetSource :856, Assert-RetargetedTask :922-923 (SDDL string equality plus the exact check), and the live-versus-captured SDDL check at :811
12. R4-RESTORE uses retarget-warden-r5 -Target r4 with the same calls. It passed today (WARDEN_R4_RESTARTED_HEALTH_VERIFIED), as did retarget-warden-r4.ps1:440 on 10-10. That shows flags 4 with an unchanged SYSTEM principal keeps the canonical descriptor.
13. S12 to S14 make controller calls only.
14. Files the sitting only imports as reviewed functions are never executed: register-stopped-warden-r3:155, check-worker-native-status-r3:202, check-worker-denials:111 and retarget-warden-r4:440.

The pinned Python helpers only read the four daemon tasks (require_stopped). The r5 runtime source does not touch tasks.

**Minimal fix.** Change the flags literal from 2 to 18 (TASK_CREATE | TASK_DONT_ADD_PRINCIPAL_ACE) in five calls:
- check-worker-native-auth-status-six-r4-v1.ps1:303
- agy-status-capture-r4-v1.ps1:421
- login_pipeline_worker_interactive_agy_r4_v1.ps1:486
- agy-isolation-evidence-r4-v1.ps1:1173
- run-upgrade-preview-r5-v1.ps1:496

Keep the exact validator, ASCII and the CRLF line endings that all of these files use. Then update the pins and tests:
- The leaf sha c0b5df80 is pinned at login-six-workers-status-first-r4-v1.ps1:72, login_pipeline_worker_interactive_agy_r4_v1.ps1:83, test_login_six_workers_status_first_r4_v1.py:43 and RUN:198.
- The agy wrapper sha da166c1d is pinned at login-six-workers-status-first-r4-v1.ps1:92, RUN:207 and test_login_six_workers_status_first_r4_v1.py:39.
- login-six-workers-status-first-r4-v1.ps1 then changes, so its pin 9cfc0a98 at RUN:200 changes.
- The capture, isolation and preview pins are 90d56123 (RUN:210), af773b1f (RUN:212) and 8f4c8064 (RUN:217).
- Regenerate RUN with refresh-r5-sitting-pins.py, then run --check.
- Change the fixture tests that assert flags==2: test_check_worker_native_auth_status_six_r4_v1.py:379, test_agy_status_capture_r4_v1.py:938 and :1117, test_agy_isolation_evidence_r4_v1.py:1915 and :2284, test_run_upgrade_preview_r5_v1.py:887 and :1336, test_login_pipeline_worker_interactive_agy_r4_v1.py:506.
- Add a fixture that returns the host projection for flags 2 and 'D:PAI' for flags 18.

Do not change register-stopped-warden-r3.ps1, retarget-warden-r5.ps1 or stop-warden-r4/r5. retarget-warden-r5's pin 991703ab is also imported by run-upgrade-preview-r5-v1.ps1:148.

The alternative, keeping flags 2 and switching the five imports to the task-private-acl-v8 validator with $Task.Name, is also host-proven, but it needs more edits.

**Residual risks:**
- The flags-18 evidence is from 10-08/09. If the read-back still differs, the fixed scripts fail closed at REGISTER with no Run, which is the same outcome as today.
- The S11 r5 update adds a logon trigger for AETHERDESK\ansac. That has never run on this host. If it ever changed the descriptor, both the restore and the stop of r5 would also refuse the Warden, and the restore would end blocked.

**Current state notes:**
- The 14 orphaned, enabled, never-run SYSTEM tasks have unique attempt names. They block nothing: the Claude and agy history censuses only look at InteractiveClaude/InteractiveAgy names. Removing them is an owner-only action.
- The next sitting needs a new -Attempt (v3), and its base source is now r4-restore v1.

### Items

- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\check-worker-native-auth-status-six-r4-v1.ps1** (303 (register); 289 (Assert-RegisteredTaskAcl in Assert-AuthStatusTaskDefinition, called at 362); import at 76/84; stage S3 (12 one-shot status checks, RUN:948); S3 attended login series and S6 Gemini series via login-six-workers-status-first-r4-v1.ps1 Invoke-StatusLeafProcess:264 (before + after per slot))
  - issue: Status leaf registers a SYSTEM task (LogonType 5, SDDL O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)) with TASK_CREATE only (flags 2). It then requires the exact protected two-ACE descriptor from Assert-RegisteredTaskAcl (register-stopped-warden-r3.ps1:81-93, pin eccc593f). On this host flags 2 reads back unprotected, with an extra SY FR (1179785) ACE, so it is held at REGISTER and the task is left registered, enabled and never run.
  - evidence: r5-sitting-20261011-202738.log:47-237 (12x 'held at task registration: Registered task ownership/private DACL differs.', thrown at :393); pending-warden-recovery-v7-preparation-20261008.json owner_reported_pending_task (unprotected SY FA, BA FA, SY FR) and its 'defect' field; the r3 leaves (check-worker-native-auth-status-six-r3-v*.ps1:226-240) also used flags 2 but never read back.
  - would_fail_on_host: YES (observed)
  - fix: Line 303: change the 3rd argument from 2 to 18 (TASK_CREATE|TASK_DONT_ADD_PRINCIPAL_ACE); keep the exact validator. Update the comment at 294 and the header line 17. Keep CRLF and ASCII. The new sha must replace c0b5df80 at login-six-workers-status-first-r4-v1.ps1:72, login_pipeline_worker_interactive_agy_r4_v1.ps1:83, test_login_six_workers_status_first_r4_v1.py:43 and RUN pin table:198 (via refresh-r5-sitting-pins.py). Change test_check_worker_native_auth_status_six_r4_v1.py:379 to flags==18.
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\agy-status-capture-r4-v1.ps1** (421 (register); 186 (Assert-RegisteredTaskAcl in Assert-CaptureTaskRegistration, called at 422); import at 489; stage S5 signed-out capture (RUN:984); S7 signed-in capture (RUN:1013))
  - issue: Same pattern: flags 2, SYSTEM, LogonType 5, private SDDL, then the exact two-ACE protected validator. It is held at REGISTRATION before Run, leaving capture-held.json and the never-run task. S5 failing holds Gemini (S6-S8 skipped). S7 would fail identically.
  - evidence: Log :242-252 ('The agy status capture is held at task registration: Registered task ownership/private DACL differs.', thrown at :462); same host projection evidence as above.
  - would_fail_on_host: YES (S5 observed; S7 would)
  - fix: Line 421: flags 2 -> 18. Update RUN pin 90d56123 (RUN:210) via refresh-r5-sitting-pins.py. Change test_agy_status_capture_r4_v1.py:938 (literal) and :1117 ('flags': 18).
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\run-upgrade-preview-r5-v1.ps1** (496 (register); 273 (Assert-RegisteredTaskAcl in Assert-PreviewTaskRegistration, called at 497); import at 145; stage S10 upgrade preview (RUN:1136), including the audit-F3 second preview after a Gemini held rebuild)
  - issue: flags 2 plus the exact validator. It is held at REGISTRATION, so S10 is a SERIES-STOP followed by R4-RESTORE and r5 can never deploy. This is the blocking failure of the sitting.
  - evidence: Log :559-572 and :632 ('The upgrade preview is held at task registration: Registered task ownership/private DACL differs.', thrown at :539).
  - would_fail_on_host: YES (observed; blocks r5)
  - fix: Line 496: flags 2 -> 18. Update RUN pin 8f4c8064 (RUN:217). Change test_run_upgrade_preview_r5_v1.py:887 (literal) and :1336 ('flags': 18). Leave its import pin of retarget-warden-r5.ps1 (991703ab, :148) unchanged; that file needs no change.
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\login_pipeline_worker_interactive_agy_r4_v1.ps1** (486 (register); 232 (Assert-RegisteredTaskAcl in Assert-AgyLoginTaskDefinition, called at 487); import at 84/102; leaf pin at 83; stage S6 Gemini attended login, the wrapper child of login-six-workers-status-first-r4-v1.ps1 Invoke-AgyBridgeLogin:358)
  - issue: flags 2 plus the exact validator, so the wrapper would be held at REGISTER once the status leaf is fixed. Side effect: it leaves an InteractiveAgy427-r4-<slot>-<nonce> root with session-held.json but no receipt.json, plus a never-run task. agy-session-history-r4-v1.ps1 Assert-ReviewedAgyHistory (:441-449, Get-Acl on receipt.json at :445) would then refuse every later Gemini login for that slot until a reviewed cleanup.
  - evidence: Same code pattern and validator pin eccc593f; host projection evidence above. Not reached in v2 because S5 held, so no InteractiveAgy root exists yet.
  - would_fail_on_host: YES (would fail and poison the agy history for that slot)
  - fix: Line 486: flags 2 -> 18. Line 83: replace the leaf pin c0b5df80 with the fixed leaf's new sha. The new wrapper sha must replace da166c1d at login-six-workers-status-first-r4-v1.ps1:92, RUN:207 and test_login_six_workers_status_first_r4_v1.py:39. Change test_login_pipeline_worker_interactive_agy_r4_v1.py:506 (fixture flags check). Must ship together with the leaf fix.
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\agy-isolation-evidence-r4-v1.ps1** (1173 (register, both modes); 294 (Assert-RegisteredTaskAcl in Assert-IsolationTaskRegistration, called at 1174); import at 1247; stage S8 evidence (-Slot slot1, RUN:1024) and S8 -StageOnly (RUN:1029))
  - issue: flags 2 plus the exact validator in both modes. It would be held at REGISTRATION (exit 1), so the runner holds Gemini at S8 and Gemini can never reach GEMINI_CONTRACT.
  - evidence: Same pattern and validator pin; host projection evidence above.
  - would_fail_on_host: YES (would)
  - fix: Line 1173: flags 2 -> 18. Update RUN pin af773b1f (RUN:212). Change test_agy_isolation_evidence_r4_v1.py:1915 (literal) and :2284 ('flags': 18).
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\login-six-workers-status-first-r4-v1.ps1** (72 (statusLeafHash), 92 (agyBridgeWrapperPin), 264 (runs the leaf); stage S3 attended (RUN:967) and S6 (RUN:999))
  - issue: It registers no task itself, but it runs the failing leaf for every slot and pins the leaf and the agy wrapper by sha. Fixing either file breaks this series until its pins are refreshed, and its own sha 9cfc0a98 (RUN:200) then changes.
  - evidence: Grep of the old shas in W top-level *.ps1/*.py: c0b5df80 appears only at RUN:198, this file:72, agy wrapper:83 and the test :43; da166c1d only at RUN:207, this file:92 and the test :39.
  - would_fail_on_host: YES (indirectly, via the leaf and wrapper)
  - fix: After fixing the leaf and the wrapper, update lines 72 and 92 to their new shas (keep CRLF). Then run refresh-r5-sitting-pins.py to refresh RUN:198/200/207/210/212/217, and check with --check. Update test_login_six_workers_status_first_r4_v1.py:39 and :43. Optionally add fixture cases in which flags 2 returns 'O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;SY)' (must hold) and flags 18 returns 'O:BAG:BAD:PAI(A;;FA;;;SY)(A;;FA;;;BA)' (must pass).
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\retarget-warden-r5.ps1** (1266 (TASK_UPDATE flags 4, $now.sddl, logon trigger Create(9) UserId AETHERDESK\ansac at 1261 for r5); 1454 (second flags-4 update enabling the trigger); 1408/1410 (Enabled=$true, Run); 1361 (Enabled=$false on a held start); validators 856 (Assert-RetargetSource), 922-923 (SDDL string equality + exact check), 811 (live SDDL equals the captured before.sddl); stage S11 -Target r5 (RUN:687), S13 Gemini fallback; R4-RESTORE -Target r4 (all kinds))
  - issue: Same-principal TASK_UPDATE (flags 4) keeps the canonical descriptor on this host. That is proven by retarget-warden-r4.ps1:440 on 10-10 and by today's R4-RESTORE through this script (:1266 + :1408/:1410 + Assert-RetargetedTask, WARDEN_R4_RESTARTED_HEALTH_VERIFIED). The -Target r5 variant also adds a user logon trigger, which has never run on this host. If that changed the descriptor, S11 would hold at MUTATION_READBACK. The r5-retarget-held restore (and stop-warden-r5 :849/:881) would then also refuse at the exact ACL check, leaving the Warden blocked on an r5 action.
  - evidence: launch-series-20261010-195717.log:264-301 (r4 retarget via flags 4 passed the exact check and SDDL equality); r5-sitting-20261011-202738.log:572-633 (restore via this script's flags-4 path passed); Task Scheduler documents the principal ACE only for the context principal, not for trigger users.
  - would_fail_on_host: NO for -Target r4 (proven); PLAUSIBLE low risk for -Target r5 (unexercised)
  - fix: No change for this defect. Do not modify the file: its pin 991703ab is also imported by run-upgrade-preview-r5-v1.ps1:148. If the owner wants proof before S11, an owner-run ordinary-user fixture of a flags-4 update that adds a logon trigger, in the style of test-task-scheduler-acl-roundtrip-r3-v1.ps1, would settle it. Agents must not register tasks.

## Real-host proof for the flags-18 repair (diag-proof)

VERDICT: PROVEN, with three caveats listed below. Evidence comes from this host, not from reasoning about the code. On 2026-10-09 at 02:16Z (10-08 21:16 CDT local), the owner's elevated run of resume-pending-warden-r3-v7.ps1 (sha a34a1bf0, pinned at run-pending-warden-setup-r3-v7.ps1:45) registered task CoChem-4.2.7-WardenCommissioning-r3-v1 with RegisterTaskDefinition(name, def, 18, 'SYSTEM', $null, 5, 'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)') at line 125. Line 126 then ran Assert-FirstStartTask, which calls Assert-RegisteredTaskAcl(GetSecurityDescriptor(7)). That validator was imported at line 161 from register-stopped-warden-r3.ps1 with pin eccc593f, which is the exact validator in the current W file (I re-hashed it: eccc593f36cb...). The check passed. The task was then enabled and Run($null) (line 132). It reached a terminal state, and Get-FirstStartResult (commission-first-warden-r3-v5.ps1:86) requires LastTaskResult 0 for status WARDEN_RUNNING_CONTROL_PLANE_VERIFIED, so the task exited with 0. These receipts are readable without elevation:
- C:\Program Files\CoChem\TaskAclRecovery4.2.7-windows-20261008-r3-v1\recovery-complete.json (sha 7a259289): status PENDING_REGISTRATION_RECOVERED_AND_COMMISSIONED, missing_commissioning_tasks_registered 1, commissioning_run_calls 1, commissioning_receipt_sha256 4bf82adb.
- recovery-intent.json (sha ba8103c5): registration_flags 18, setter_flags 16.
- C:\Program Files\CoChem\WardenCommissioning4.2.7-windows-20261007-r3-v1\commissioning-task.xml: written at resume line 129, after the guard passed. Principal UserId S-1-5-18, RunLevel HighestAvailable, RegistrationInfo/SecurityDescriptor O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA).
- commissioning.json (sha 4bf82adb): status WARDEN_RUNNING_CONTROL_PLANE_VERIFIED, system_sid S-1-5-18, controller and launcher token_sid S-1-5-18.

This is the only flags-18 SYSTEM registration ever made on this host. A Grep of every *.ps1/*.py in W and in the repo finds 18 only at resume-pending-warden-r3-v7.ps1:125 and its copies.

FLAG VALUES: confirmed from Windows Kits 10.0.26100.0 um\taskschd.h lines 779-788: TASK_VALIDATE_ONLY 0x1, TASK_CREATE 0x2, TASK_UPDATE 0x4, TASK_DISABLE 0x8, TASK_DONT_ADD_PRINCIPAL_ACE 0x10, TASK_IGNORE_REGISTRATION_TRIGGERS 0x20. So 18 = 0x12 = TASK_CREATE | TASK_DONT_ADD_PRINCIPAL_ACE. Create-only behaviour is kept and no update bit is added. On this host, 0x10 changed only the descriptor:
- Flags 2 appends a principal FR ACE (1179785) and drops the P bit.
- Flags 18 keeps exactly the requested ACEs, with P set and AI added.
The fixture shows every other field identical between create2 and create18 (enabled, state, logon_type, run_level, triggers, allow_demand_start, last_task_result). See task-scheduler-acl-roundtrip-r3-v1-bbd9bf8061764e6ba8cdefa47fb6a149-final.json, observations[0] vs [1]. Only the backing file under System32\Tasks differs (create18 file 'D:P', create2 file 'D:PAI'), and the validator never reads that file.

'AI' FLAG: tolerated. The validator tests only ControlFlags -band DiscretionaryAclProtected plus per-ACE AceFlags = None. AI is a control flag (0x400), and the ACE flags stay 0: the fixture shows control_flags 37892 = 0x9404 = SR|P|AI|DACL_PRESENT with ace flags 0. Proof on this host tonight: retarget-warden-r5.ps1 runs the same eccc593f Assert-RegisteredTaskAcl at line 856 (source) and line 923 (after TASK_UPDATE) on the Warden SYSTEM task. Its read-back is C:\Program Files\CoChem\WardenRetarget4.2.7-windows-20261011-r4-v1\warden-task-before.sddl and warden-task-after.sddl = 'O:BAG:BAD:PAI(A;;FA;;;SY)(A;;FA;;;BA)' (sha bcacae79, matching retarget-receipt task_sddl_before/after_sha256). The retarget passed, and the task was then Run, giving WARDEN_R4_RESTARTED_HEALTH_VERIFIED with pid 37840 owner SYSTEM.

BUILD DRIFT: none found.
- OS is 10.0.26300 in tonight's transcript header and in Win32_OperatingSystem (CurrentBuild 26300, UBR 9457).
- Windows PowerShell 5.1.26100.9444 appears in both the 10-09T01:55Z fixture JSON (powershell_version) and tonight's transcript (PSVersion 5.1.26100.9444).
- The Setup log's last 'Installed state' events are 2026-09-30 19:25 CDT (KB5126052, KB5121794). The only Setup events since are CBS Staged->Staged no-ops on 2026-10-08 between 09:03:41 and 09:03:49 CDT, which is before the flags-18 run.
- Since then WindowsUpdateClient shows only Defender signature updates.
- schedsvc.dll is 10.0.26100.8457.

CAVEATS:
1. The exact SDDL read back from the flags-18 SYSTEM task was never saved; resume v7 did not write it. It is known only to satisfy the validator: owner SY or BA, protected, exactly SY FA and BA FA, ACE flags 0. The closest saved elevated SYSTEM read-backs are 'O:BAG:BAD:PAI(A;;FA;;;SY)(A;;FA;;;BA)' (Warden after SetSecurityDescriptor 16) and, for comparison, the flags-2 original 'O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;SY)' (TaskAclRecovery...\original-warden.sddl). The ordinary-user flags-18 fixture read-back is 'D:PAI' with exactly the requested ACEs.
2. There is no recorded token SID for the commissioning helper process itself. "Runs as SYSTEM" for that task rests on its S-1-5-18 principal, LastTaskResult 0, and its writes into the SY/BA-only root. Direct token-SID proof exists for the Warden processes.
3. This is a single elevated sample (n=1).

OPERATIONAL NOTE: the 14 v2 tasks still exist. TASK_CREATE (2 or 18) fails on a name that already exists, so a rerun needs fresh attempt names. No commands with -Apply were run, nothing was written, and no task was touched; all evidence came from Read/Grep plus read-only hashes, version reads, registry reads and event-log reads.

### Items

- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\check-worker-native-auth-status-six-r4-v1.ps1** (303 (register), 289 (Assert-RegisteredTaskAcl), 294 (comment 'TASK_CREATE (2) only'); stage S3)
  - issue: The script registers its SYSTEM one-shot task with flags 2 (TASK_CREATE) and then reads the descriptor back through the exact eccc593f validator. On this host Task Scheduler stores a flags-2 registration unprotected and appends a SY FR ACE, so the first check (protected, exactly 2 ACEs) fails. All 12 held tasks tonight show this: phase REGISTER, reason 'Registered task ownership/private DACL differs.', task_state 3, last_task_result 267011.
  - evidence: C:\Program Files\CoChem\NativeAuthStatusSix4.2.7-windows-20261010-r4-v1-ea8225f6253040d3b41a9337df83b8a0-slot1-claude-before\status-held.json: phase REGISTER, reason 'Registered task ownership/private DACL differs.', task_registered true, run_requested false. The same flags-2 pattern held on 10-08: TaskAclRecovery4.2.7-windows-20261008-r3-v1\original-warden.sddl = 'O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;SY)'.
  - would_fail_on_host: yes - observed failing 12/12 on 2026-10-11 20:28-20:31
  - fix: Change flags 2 to 18 (TASK_CREATE|TASK_DONT_ADD_PRINCIPAL_ACE) and keep the exact validator unchanged. 18 is still create-only (taskschd.h: 0x10 adds no update semantics), so the comment's 'never replaced' guarantee still holds; update the comment to say 18. Use a fresh attempt ID, because the 12 tasks named ...-ea8225f6253040d3b41a9337df83b8a0-slotN-<provider>-before still exist and TASK_CREATE fails on an existing name. Update the runner pin c0b5df80 (RUN_427_R5_SITTING.ps1:198) and any other pins of this file's old sha.
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\agy-status-capture-r4-v1.ps1** (421 (register), 186 (Assert-RegisteredTaskAcl); stage S5 and S7)
  - issue: Same defect: it registers with flags 2 and $script:taskSddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)' (line 77), then runs the exact eccc593f validator. It was held at S5 tonight.
  - evidence: r5-sitting-20261011-202738.log lines 243-251: 'The agy status capture is held at task registration: Registered task ownership/private DACL differs.'
  - would_fail_on_host: yes - observed at S5
  - fix: Change flags 2 to 18 and keep the validator. The current capture task (AgyCapture...-57fbb476c49c4a3ba7be21b3065e53f4-slot1-signed-out) still exists, so use a fresh attempt. Update runner pin 90d56123 (RUN_427_R5_SITTING.ps1:210).
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\run-upgrade-preview-r5-v1.ps1** (496 (register), 273 (Assert-RegisteredTaskAcl), 101 (taskSddl); stage S10)
  - issue: Same defect: flags 2 followed by the exact validator. This stopped the series at S10.
  - evidence: C:\Program Files\CoChem\UpgradePreview4.2.7-windows-20261011-r5-v1-116bb5fd1bf045c88c1ba36dde4e6404\preview-held.json: phase REGISTRATION, reason 'Registered task ownership/private DACL differs.', task_registered true, run_requested false, task_state 3, last_task_result 267011.
  - would_fail_on_host: yes - observed at S10
  - fix: Change flags 2 to 18 and keep the validator. The attempt is generated per run (116bb5fd... still exists as a never-run task), so a new run gets a new name. Update runner pin 8f4c8064 (RUN_427_R5_SITTING.ps1:217).
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\agy-isolation-evidence-r4-v1.ps1** (1173 (register), 294 (Assert-RegisteredTaskAcl), 1247 (eccc593f import); stage S8 (skipped tonight))
  - issue: Latent instance of the same defect: flags 2 followed by the exact eccc593f validator. It was not reached tonight only because Gemini was held at S5.
  - evidence: Grep: RegisterTaskDefinition($script:taskName,$definition,2,'SYSTEM',$null,5,$script:taskSddl) at line 1173, and Assert-RegisteredTaskAcl ($Task.GetSecurityDescriptor(7)) at line 294.
  - would_fail_on_host: yes - same API path as the 3 scripts observed failing
  - fix: Change flags 2 to 18 and keep the validator. Update runner pin af773b1f (RUN_427_R5_SITTING.ps1:212).
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\login_pipeline_worker_interactive_agy_r4_v1.ps1** (486 (register), 232 (Assert-RegisteredTaskAcl), 102 (pinned import); stage S6 (skipped tonight))
  - issue: Latent instance of the same defect: flags 2 followed by the exact validator.
  - evidence: Grep: $Folder.RegisterTaskDefinition($script:taskName,(New-AgyLoginTaskDefinition ...),2,'SYSTEM',$null,5,$script:taskSddl) at line 486, and Assert-RegisteredTaskAcl ([string]$Task.GetSecurityDescriptor(7)) at line 232.
  - would_fail_on_host: yes - same API path
  - fix: Change flags 2 to 18 and keep the validator. Update runner pin da166c1d (RUN_427_R5_SITTING.ps1:207).
- **C:\Program Files\CoChem\TaskAclRecovery4.2.7-windows-20261008-r3-v1\recovery-complete.json** (n/a; stage PROOF (10-08 owner run))
  - issue: Main proof from this host. An elevated flags-18 SYSTEM registration with exactly the proposed arguments passed the exact eccc593f validator and was run on demand to a successful terminal result.
  - evidence: recovery-complete.json (sha 7a2592895e80, written 2026-10-09T02:17:20Z): status PENDING_REGISTRATION_RECOVERED_AND_COMMISSIONED, missing_commissioning_tasks_registered 1, commissioning_run_calls 1, commissioning_receipt_sha256 4bf82adb; intent_sha256 ba8103c5 = recovery-intent.json, which has registration_flags 18. Code path in resume-pending-warden-r3-v7.ps1 (sha a34a1bf0, the same as the W copy and the pin at run-pending-warden-setup-r3-v7.ps1:45): line 125 registers with flags 18; line 126 runs Assert-FirstStartTask, which calls Assert-RegisteredTaskAcl (imported at line 161 from register-stopped-warden-r3.ps1 with pin eccc593f, the current file's sha); line 129 writes commissioning-task.xml; line 132 sets Enabled=$true and calls Run($null); line 134 Assert-CompletedStatusTask; Get-FirstStartResult requires LastTaskResult 0 (commission-first-warden-r3-v5.ps1:86). recovery-complete.json is written only after all of these checks pass.
  - would_fail_on_host: no - passed on host 2026-10-09T02:16-02:17Z
  - fix: No change needed. Cite it as the precedent for the fix.
- **C:\Program Files\CoChem\WardenCommissioning4.2.7-windows-20261007-r3-v1\commissioning-task.xml** (4, 10-11; stage PROOF (principal, run as SYSTEM))
  - issue: Task XML of the flags-18 task, captured after the exact guard passed. Its principal is SYSTEM, and the run produced a SYSTEM-verified controller.
  - evidence: XML: <SecurityDescriptor>O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)</SecurityDescriptor>, <UserId>S-1-5-18</UserId>, <RunLevel>HighestAvailable</RunLevel>, Enabled false, ExecutionTimeLimit PT8M. commissioning.json (sha 4bf82adb): status WARDEN_RUNNING_CONTROL_PLANE_VERIFIED, system_sid S-1-5-18, controller.token_sid S-1-5-18, controller.launcher.token_sid S-1-5-18, started_at_unix_ms 1791512204739 (about 2026-10-09T02:16:44Z).
  - would_fail_on_host: no
  - fix: None. Caveat: the helper process's own token SID was not recorded. SYSTEM execution of the commissioning task rests on the S-1-5-18 principal, LastTaskResult 0, and its writes into a root restricted to SYSTEM and Administrators. Token-SID proof exists for the Warden launcher and controller.
- **C:\Program Files\CoChem\WardenRetarget4.2.7-windows-20261011-r4-v1\warden-task-before.sddl** (1; stage PROOF ('AI' tolerated, same build tonight))
  - issue: The exact SDDL of an elevated, protected two-ACE SYSTEM task read back on this host tonight, which passed the same eccc593f validator. It shows that the 'PAI' form ('D:PAI', auto-inherited flag set) is accepted.
  - evidence: File content 'O:BAG:BAD:PAI(A;;FA;;;SY)(A;;FA;;;BA)' (sha bcacae79e462, identical to warden-task-after.sddl and to retarget-receipt.json task_sddl_before/after_sha256, sddl_preserved true). It was validated by retarget-warden-r5.ps1:856 and :923 (Assert-RegisteredTaskAcl imported at :1595 with pin eccc593f), and the task was then Run: start-receipt.json gives WARDEN_R4_RESTARTED_HEALTH_VERIFIED, pid 37840, owner SYSTEM. The 10-10 r4 retarget root holds the same SDDL. The ordinary-user fixture shows control_flags 37892 (0x9404 = SR|P|AI|PRESENT) with ACE flags 0.
  - would_fail_on_host: no
  - fix: None. The validator checks only that DiscretionaryAclProtected is set; the AI control flag (0x400) is ignored, and AceFlags remain None.
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\task-scheduler-acl-roundtrip-r3-v1-bbd9bf8061764e6ba8cdefa47fb6a149-final.json** (observations[0] (flags 2) vs observations[1] (flags 18); stage PROOF (what 0x10 changes))
  - issue: Ordinary-user API fixture from this host (no SYSTEM task, never run). It isolates the effect of 0x10: only the service descriptor changes. Registration flags 2 append a principal FR ACE and drop the P bit; flags 18 keep exactly the requested ACEs, protected, with AI.
  - evidence: flags 2: service sddl 'D:(A;;FA;;;<user>)(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;<user>)', control_flags 32772, dacl_protected false, ace_count 4. Flags 18: 'D:PAI(A;;FA;;;<user>)(A;;FA;;;SY)(A;;FA;;;BA)', control_flags 37892, dacl_protected true, ace_count 3. Enabled, state, logon_type, run_level, triggers, allow_demand_start and last_task_result are identical. Backing-file ACL: create2 'D:PAI', create18 'D:P', not read by the validator. powershell_version 5.1.26100.9444, started_utc 2026-10-09T01:55:51Z. Flag constants: C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\um\taskschd.h:781-787 (TASK_CREATE 0x2, TASK_DONT_ADD_PRINCIPAL_ACE 0x10).
  - would_fail_on_host: no
  - fix: None. Note that this fixture alone does not prove SYSTEM or Run behaviour; the 10-08 elevated run above does.
- **HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion; Setup and System event logs; C:\WINDOWS\System32\schedsvc.dll** (n/a; stage BUILD DRIFT CHECK)
  - issue: Did Windows or PowerShell change between the 10-08/09 evidence and tonight? No.
  - evidence: CurrentBuild 26300, UBR 9457, DisplayVersion 26H2. Win32_OperatingSystem Version 10.0.26300, LastBootUpTime 2026-10-11 00:58 CDT. powershell.exe 5.1 reports PSVersion 5.1.26100.9444, the same as the 10-09 fixture JSON and tonight's transcript header (r5-sitting-20261011-202738.log lines 7-14). Setup log: last 'Installed state' events 2026-09-30 19:25 CDT (KB5126052, KB5121794; Get-HotFix newest is KB5121794, InstalledOn 2026-10-01); all 170 events on 2026-10-08 fall between 09:03:41 and 09:03:49 CDT and are Staged->Staged (CbsTask), before the 21:16 CDT flags-18 run; none since. WindowsUpdateClient since 10-07 shows only Defender KB2267602 signature installs. schedsvc.dll FileVersion 10.0.26100.8457.
  - would_fail_on_host: no
  - fix: None. A Dev-channel feature-flag rollout cannot be fully excluded, but tonight's results are consistent with the 10-08 behaviour: the flags-2 holds match the 10-08 flags-2 failure, and the 'PAI' Warden SDDL still validates.

## What the next attempt (v3) does from the current host state (diag-next-attempt)

I traced what `RUN_427_R5_SITTING.ps1 -Apply -Attempt v3` would do from the current host state, assuming the flags-18 registration fix lands. **v2 left nothing that hard-blocks v3.** Every per-attempt namespace is either the first free version number or a fresh 32-hex id. Nothing reads another sitting's `sitting-end.json`, and the 14 never-run tasks are only checked by their exact names. Two things are required before v3, and one decision is needed.

**How v3 runs from today's state** (B = `C:\Program Files\CoChem`)
- **S0:** sitting root `R5Sitting...-v3` is new; v1 and v2 both have `sitting-end.json`, so v3 is the next valid attempt. The Warden is detected as an r4 restore, attempt v1, running. The process check passes: the two SYSTEM python processes are the controller and its launcher, plus 16 MCP clients.
- **S1:** skipped, the r5 install verifies.
- **S2:** now `stop-warden-r5.ps1 -Apply -Attempt v1 -RetargetTarget r4 -RetargetAttempt v1`. `WardenStop4.2.7-windows-20261011-r5-v1` is free. Because the Warden is running, this ends it (idle proof, Task Scheduler End, disable) rather than v2's disable-only.
  - I ran the stop script's read-only plan (no -Apply, unelevated, through the lock). It bound the r4 restore start receipt (sha 2ddf02b6), verified the r4 runtime, found the Warden idle (31 queue rows: 15 BLOCKED, 16 COMPLETED, none in progress), and found no unrecognised processes. Its only hold was "task unreadable without elevation".
- **S3, S5, S10:** fresh hex ids, so no clash with v2's held roots or tasks.
- **S9:** the next free config folder is `WardenConfig...-r5-v2`; v1 is never reused. Held or Gemini bytes both stage there, and a held rebuild goes to v3.
- **S11:** `retarget-warden-r5.ps1 -Target r5 -Config <WardenConfig v2> -Attempt v1 -SourceAttempt v1 -StopAttempt v1`. I checked each field the retarget compares against the receipts on disk: they match and it is accepted.
- **R4-RESTORE:** from the base state this would be `-Target r4 -Attempt v2 -SourceAttempt v1 -StopAttempt <S2 attempt>`, using a fresh `queue-restart-20261011-r4-v2`. After an r5 start it would first run stop-warden-r5 with attempt v2.

**Required before v3**
1. **Fix scope:** S6 (`login_pipeline_worker_interactive_agy_r4_v1.ps1:486`) and S8 (`agy-isolation-evidence-r4-v1.ps1:1173`) have the same registration defect. If only the three v2 scripts are fixed, S5 will pass and the owner will be asked for six Google sign-ins. S6 then holds, leaving a slot1 login folder with a task and no `receipt.json`. The agy history check would then refuse every later slot1 Gemini login. Either fix those two sites too, or run v3 with `-Gemini skip`.
2. **Pin cascade:** the status leaf's hash (c0b5df80) is also pinned by `login-six-workers-status-first-r4-v1.ps1:72` and the agy login wrapper at line 83. That changes the wrapper's hash, pinned at `login-six-workers-status-first-r4-v1.ps1:92`, which changes login-six's hash in the runner. Missed pins stop the sitting at S0 or fail S3 re-login and S6. Leave `register-stopped-warden-r3.ps1` unchanged: eight scripts import it by hash.

**Hazards**
- **S2 is the first live End of a running controller.** It is safe if the owner submits nothing, otherwise a job sits PENDING and the stop refuses with nothing changed. If the stop holds after creating its folder, the restore is wrongly reported as "not stopped by this sitting".
- **S12 risk:** live r4 health shows the CPU budget exceeded (5.56%) and disk IOPS 4433 against a 4000 limit. r5 keeps the 5% CPU budget and S12 treats admission-ready as a hard 120 s gate, so a CPU-only pause could restore r4.
- **Cleanup is optional:** removing the 14 never-run tasks is not required; owner only, elevated, best after r5 is verified.
- **Log noise:** the two "TerminatingError" lines in the transcript are caught by the runner and harmless.

**Decision for the owner:** with the fix, Gemini is attempted by default, which means about 15 minutes of attended Google sign-ins at S6. Choose `-Gemini skip` or be present.

The S2 plan output is saved at `C:\Users\ansac\AppData\Local\Temp\claude\D----CoChem-GitHub-Repo\37810cc2-dc2b-49b8-bf45-25697101c0f0\scratchpad\stop-r5-plan.json`.

### Items

- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\login_pipeline_worker_interactive_agy_r4_v1.ps1** (486 (TASK_CREATE flags 2), 487 -> 232 (exact ACL readback); also 476 (session root created before registration), 468 (history check); stage S6 / S8 (Gemini path))
  - issue: Same registration defect as the three v2 failures, in a script v2 never reached. With only the three v2 scripts fixed, S5 passes and the owner does the six S6 Google sign-ins. The wrapper then creates C:\Program Files\CoChem\InteractiveAgy427-r4-slot1-<nonce> (:476), registers with flags 2 and throws 'Registered task ownership/private DACL differs' at :232. That leaves a never-run CoChem-4.2.7-InteractiveAgy-r4-slot1-<nonce> task and no receipt.json. From then on, every slot1 Gemini login runs Assert-ReviewedAgyHistory (:468, agy-session-history-r4-v1.ps1:414-446), which reads the missing receipt.json and refuses. Slot1 Gemini stays blocked until a reviewed recovery.
  - evidence: agy-session-history-r4-v1.ps1:441-446 binds every historical InteractiveAgy427-r4-<slot>-* folder to its task and reads <root>\receipt.json with Get-Acl and Read-R3Control. A folder held at REGISTER has no receipt. No InteractiveAgy427-r4-* folder exists today, so the risk is only created if v3 reaches S6 unfixed.
  - would_fail_on_host: yes, if v3 runs with -Gemini attempt (the default) and the fix covers only the three v2 scripts
  - fix: Apply the same flags-18 change (TASK_CREATE 0x2 | TASK_DONT_ADD_PRINCIPAL_ACE 0x10, exact validator kept) at login_pipeline_worker_interactive_agy_r4_v1.ps1:486, or run v3 with -Gemini skip. Required before any sitting reaches S6.
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\agy-isolation-evidence-r4-v1.ps1** (1173 (flags 2) -> 1174 -> 294 (Assert-RegisteredTaskAcl); stage S8 (Gemini path))
  - issue: S8 isolation evidence registers with flags 2 and reads the ACL back exactly, so it would hold the same way. Gemini would be marked held at S8 after the owner already did six attended sign-ins. Not fatal to the sitting: S9 rebuilds the held configuration. It also adds one more never-run SYSTEM task.
  - evidence: Search of the live child scripts: the only TASK_CREATE flags-2 sites with exact ACL readback are check-worker-native-auth-status-six-r4-v1.ps1:303, agy-status-capture-r4-v1.ps1:421, run-upgrade-preview-r5-v1.ps1:496, login_pipeline_worker_interactive_agy_r4_v1.ps1:486 and agy-isolation-evidence-r4-v1.ps1:1173. login_pipeline_worker_interactive_r3_v6.ps1:144 (Claude re-login) does not read the ACL back. retarget-warden-r5.ps1 uses TASK_UPDATE (flags 4), which preserved the SDDL in the v2 restore (sddl_preserved true).
  - would_fail_on_host: yes (Gemini held at S8) if Gemini gets that far and this site is not fixed
  - fix: Include agy-isolation-evidence-r4-v1.ps1:1173 in the flags-18 fix. Update the literal assertion at test_agy_isolation_evidence_r4_v1.py:1915 and the runner pin at RUN_427_R5_SITTING.ps1:212.
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\login-six-workers-status-first-r4-v1.ps1** (72 (statusLeafHash c0b5df80), 92 (agyBridgeWrapperPin da166c1d); login_pipeline_worker_interactive_agy_r4_v1.ps1:83 (leafFunctionsHash c0b5df80); RUN_427_R5_SITTING.ps1:198,200,207,210,212,217; stage S0 pin gate / S3 re-login / S6)
  - issue: Pin cascade from the fix. Fixing check-worker-native-auth-status-six-r4-v1.ps1 changes c0b5df80. That hash is imported by the agy login wrapper (:83, for Assert-R4InstalledBindings and Assert-VenvBinding) and pinned by login-six (:72). Updating the wrapper changes da166c1d, pinned at login-six :92, which changes login-six's hash 9cfc0a98 (runner :200). Missing any of these gives 'Reviewed function source changed' at S3 re-login or S6, or an S0 STOP for pin drift. Current hashes on disk still equal every pin (checked), so the cascade only starts when the fix lands.
  - evidence: Search of W for c0b5df80, da166c1d, 9cfc0a98, 90d56123, 8f4c8064 and af773b1f. Test pins: test_login_six_workers_status_first_r4_v1.py:39,43. Static literal asserts on the flags-2 call text: test_run_upgrade_preview_r5_v1.py:887, test_agy_status_capture_r4_v1.py:938, test_agy_isolation_evidence_r4_v1.py:1915.
  - would_fail_on_host: yes, if any link is missed
  - fix: After editing the five registration sites, update in order: leaf hash -> agy wrapper :83 -> login-six :72 and :92. Then run refresh-r5-sitting-pins.py and its --check, and update the test pins and literals. Do not change register-stopped-warden-r3.ps1: eccc593f is imported by stop-warden-r5:1383, retarget-warden-r5:1595, stop-warden-r4, run-upgrade-preview:145, agy-status-capture:489, agy-isolation:1247, the leaf (:76) and the agy wrapper.
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\RUN_427_R5_SITTING.ps1** (420 (source detection), 833-835 (base_source), 926-932 (r4-restore branch), 934-937 (refusal handling); stage S2 (from a running restored r4))
  - issue: No blocker; the behaviour is new and needs care. Base source is now the r4 restore v1 (queue-restart-20261011-r4-v1) and the Warden is running, so S2 is stop-warden-r5.ps1 -Apply -Attempt v1 -RetargetTarget r4 -RetargetAttempt v1. This ends a live controller (idle proof up to 120 s, Task Scheduler End, 90 s exit wait, disable) instead of v2's disable-only. The RUNNING End path has never run live on this host (no stop receipt with WARDEN_ENDED exists). Hazards: (a) any job an MCP client submits before S2 stays PENDING forever (admission is paused at capacity 0), the idle proof fails, the child says 'Nothing was changed' and the runner STOPs without restore at :936; r4 keeps running and v3 can be rerun. (b) If the controller survives End, stop-held.json (END_WAIT) is written and the task is NOT disabled.
  - evidence: I ran stop-warden-r5.ps1 -RetargetTarget r4 -RetargetAttempt v1 -Attempt v1 as a read-only plan, unelevated, through serialize-heavy.py; output in scratchpad\stop-r5-plan.json. start_binding START_RECEIPT (sha 2ddf02b6), runtime_verified true, idle true (31 queue rows: BLOCKED 15, COMPLETED 16, in_progress 0, uncleared 0), 16 clients, 0 unclassified, other daemons ABSENT. Only hold: task unreadable without elevation. A live process list shows exactly two SYSTEM python processes (2692 launcher, 37840 controller). WardenStop4.2.7-windows-20261011-r5-v1 does not exist.
  - would_fail_on_host: no under current conditions; it would refuse safely if work is submitted beforehand
  - fix: No code change. Tell the owner: submit nothing to the pipeline (MCP clients may stay open) between now and S2; S2 now takes about 3-4 min and briefly takes the pipeline down.
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\RUN_427_R5_SITTING.ps1** (927-929 and 938 (stop_attempt recorded only on success), 748 (Get-R5CutoverState), 1423-1424 (sitting-end.json); stage S2 failure -> R4-RESTORE classification)
  - issue: For an r4-restore base, the S2 stop attempt is stored in base_source.stop_attempt only after success. Any stop-warden-r5 hold after its folder exists (PREPARATION, END_WAIT, DISABLE) triggers -Restore. Get-R5CutoverState then returns 'blocked' with the text 'the restored r4 Warden was not stopped by this sitting', which is wrong: the stop was attempted and is held. sitting-end.json is written, so v3 is used up. The outcome is safe, because the retarget refuses a held stop (retarget-warden-r5.ps1:616), but the message points the owner the wrong way.
  - evidence: Code reading. r5_stop_held is only set by the r5 stop paths (:1195, :1283), not by S2.
  - would_fail_on_host: only if the S2 stop holds after creating its folder
  - fix: Optional, low priority. Record $script:R5.s2_stop_attempt=$stopAttempt before the child at :929. In Get-R5CutoverState, when base kind is r4-restore, s2_attempted is true and stop_attempt is absent, test B\WardenStop4.2.7-windows-20261011-r5-<s2_stop_attempt>\stop-held.json and return blocked with 'stop-warden-r5 <vK> is held (stop-held.json); r4 may still be running; owner/agent review'.
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\retarget-warden-r5.ps1** (RUN_427_R5_SITTING.ps1:1161-1167; retarget-warden-r5.ps1:865-877 (source selection), 679-714 (Assert-StartedSourceLineage), 610-634 (Assert-StopLineage); stage S11 cutover from the r4 restore)
  - issue: No blocker. The runner passes -Target r5 -Config <WardenConfig...-r5-v2\pipeline.json> -Attempt v1 (WardenRetarget4.2.7-windows-20261011-r5-v1, free) -SourceAttempt v1 (base_source.source_attempt from the :420 regex) -StopAttempt <S2 attempt, v1>. The retarget reads attempt v1 from the live action, selects source r4 and the WardenRetarget...-r4-v1 folder, takes the 'started' path, and checks the stop lineage against WardenStop...-r5-v1.
  - evidence: Read from B\WardenRetarget4.2.7-windows-20261011-r4-v1: retarget receipt (WARDEN_RETARGETED_TO_R4_NOT_STARTED, config_sha256 135cd9ec, trigger_enabled_after null, task_xml_after_sha256 e4db19f9 = task_xml_sha256); start receipt (WARDEN_R4_RESTARTED_HEALTH_VERIFIED, trigger_enabled_before/after null, task_xml_started_sha256 = task_xml_sha256 8e613f14, retarget_receipt_sha256 5e66280b, intent_sha256 008835b4); warden-task-after.xml and warden-task-started.xml present. The stop plan computed start_intent_sha256 008835b4, equal to the start receipt's intent_sha256. stop-warden-r5 writes trigger_enabled_after null for r4, which :631 requires. test_r5_sitting_flow.py:1032 covers the argument arithmetic with stubs.
  - would_fail_on_host: no
  - fix: None.
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\RUN_427_R5_SITTING.ps1** (1280-1292 (Invoke-R5Restore), 749 ('base' previous state with source and stop); stage R4-RESTORE from v3)
  - issue: No blocker. After S2 and before an r5 task update, the restore is retarget-warden-r5.ps1 -Target r4 -Attempt v2 -SourceAttempt v1 -StopAttempt <S2 attempt> -Apply -Start. WardenRetarget...-r4-v2 is free and queue-restart-20261011-r4-v2 is fresh (checked at retarget :1678). After an r5 start the restore first runs stop-warden-r5 -Attempt v2 (next free stop folder) -RetargetTarget r5 -RetargetAttempt v1, then retarget -Target r4 -Attempt v2 -SourceAttempt v1 -StopAttempt v2. The restored r4 will again be admission-paused, a known r4 defect.
  - evidence: Directory listing of B shows only WardenRetarget4.2.7-windows-20261011-r4-v1 and 20261010-r4-v1, and no WardenStop...20261011-r5-* or WardenRetarget...20261011-r5-*.
  - would_fail_on_host: no
  - fix: None.
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\RUN_427_R5_SITTING.ps1** (1075 (Get-R5FreeAttempt for the config folder), 562-564; stage-pipeline-config-r5-v1.ps1:455-476; stage S9 staging)
  - issue: No blocker. The runner never passes a fixed -Attempt v1: it picks the first free folder, which in v2 happened to be v1. In v3 it picks WardenConfig4.2.7-windows-20261011-r5-v2 (ABSENT) and STAGES there, for held bytes 135cd9ec or for different Gemini-enabled bytes. If staging or the preview of a Gemini configuration fails, the held rebuild goes to v3. Had v1 been reused: identical bytes give ALREADY_STAGED_IDENTICAL (accepted at :1083); different bytes are refused ('never overwritten').
  - evidence: The stager checks only its own target folder. retarget-warden-r5 accepts any WardenConfig...-r5-vN with its staging receipt.
  - would_fail_on_host: no
  - fix: None. WardenConfig...-r5-v1 stays as an orphan of v2.
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\check-worker-native-auth-status-six-r4-v1.ps1** (RUN_427_R5_SITTING.ps1:945, 983, 1130 (New-R5HexAttempt, a GUID); check-worker...:266-268; run-upgrade-preview-r5-v1.ps1:563-564; agy-status-capture-r4-v1.ps1:75-76; stage S3 / S5 / S7 / S8 / S10 namespaces and v2 leftovers)
  - issue: No collision. Every one-shot id is a fresh 32-hex GUID per call (S3 one per stage, S5-S8 one per sitting, S10 one per preview). Children only refuse when their own folder or task name exists, and the daemon checks cover only the four Warden/Supervisor tasks. The 14 never-run v2 tasks (12 NativeAuthStatusSix-...-ea8225f6..., AgyCapture-...-57fbb476..., UpgradePreview-...-116bb5fd...) and their held folders block nothing in v3. The only task census in the chain (agy-session-history-r4-v1.ps1:423-427) looks only at InteractiveAgy task names.
  - evidence: Search for GetTasks( across the live scripts: only agy-session-history-r4-v1.ps1:423.
  - would_fail_on_host: no
  - fix: Cleanup of the 14 tasks is OPTIONAL and owner-only (elevated). Not required for v3; best left as evidence until r5 is verified, then batched into the owner's admin series if wanted.
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\RUN_427_R5_SITTING.ps1** (228 (sitting root from -Attempt), 810-811, 819-824; stage S0 / v2 sitting-end.json)
  - issue: No blocker. S0 refuses only when the current attempt's own sitting-end.json, S11-intent, fallback-intent or restore-intent exists. R5Sitting4.2.7-windows-20261011-v1 and -v2 both have sitting-end.json, so -Attempt v3 is the next valid one and its folder does not exist. No child reads earlier sittings: a search for 'sitting-end' and 'R5Sitting4' finds only the runner, its tests and ps_toplevel_smoke.py.
  - evidence: Listing of R5Sitting...-v2: S00-S09 receipts, restore-intent-20261011-202738.json, sitting-end.json. -v1: S00, S01, restore-intent, sitting-end.json.
  - would_fail_on_host: no
  - fix: Owner runs `RUN_427_R5_SITTING.ps1 -Apply -Attempt v3` (never v1 or v2).
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\RUN_427_R5_SITTING.ps1** (178 (-Gemini default 'attempt'), 991-1007 (S6); stage S5-S8 attendance)
  - issue: Decision needed. In v2 the registration hold at S5 meant the owner was never asked for the six attended Google sign-ins. Once the fix lands, S5 can pass and S6 requires about 15 minutes of attendance, which conflicts with the owner's minimal-attendance preference.
  - evidence: v2 log line 25 shows 'Gemini: attempt'.
  - would_fail_on_host: not a failure; an attendance change
  - fix: Owner decides explicitly: pass -Gemini skip for an unattended sitting, or be present for S6. Only choose 'attempt' once the S6 and S8 sites are fixed too.
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\RUN_427_R5_SITTING.ps1** (1179-1185 (S12), 596 and 609-616 (admission_ready waited only 120 s), 1182 (Stop -Restore); stage S12 r5 health gate (observed live, not caused by v2))
  - issue: S12 STOPs and restores r4 unless components.warden_controller.admission_ready is true within 120 s. The live r4 controller is now paused for CPU (5.56% against its strict 5% budget), with rss 48 MiB below the 50 MiB limit. r5's controller_guard.py raises only the memory budget (200 MiB); the 5% CPU budget is unchanged. If r5 idles near 5% CPU like r4, S12 could fail on CPU alone and undo a good cutover. Disk IOPS 4433 against 4000 also pauses admission, but S13 only defers on that.
  - evidence: pipeline_health (read-only MCP): admission reasons 'Disk throughput or IOPS exceeds the admission pressure threshold' and 'Warden CPU utilization exceeds its strict 5% budget', controller cpu_percent 5.5625, rss_mb 48.4. r5 cochem_pipeline\controller_guard.py lines 1-15, 140: 'The CPU budget is unchanged'; a CPU-only violation sets ready false for that sample without a hold.
  - would_fail_on_host: possible; depends on r5's idle CPU
  - fix: Suggested runner change: when the only soft reason left after 120 s is admission_ready false and /health components.warden_controller.reasons is CPU-only, treat it like S13 (record DEFERRED, keep r5) instead of restoring. Or extend the S12 admission wait (e.g. 300 s, polled every 10 s or more).
- **C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next\RUN_427_R5_SITTING.ps1** (406 (Get-NetTCPConnection no-match), 504 (Get-R5JsonTail tries each column-0 '{'); stage transcript noise)
  - issue: Cosmetic. The v2 log shows 'PS>TerminatingError(Get-NetTCPConnection)' (port free) and 'TerminatingError(ConvertFrom-Json): Invalid JSON primitive' after each stager call. That happens because the stager prints a pretty JSON block and then a compact status line. Both errors are caught and the compact line parses. With r4 running, the port error will not appear in v3's S0.
  - evidence: v2 log lines 22, 347 and 445 are followed by correct handling (lines 23, 348, 446).
  - would_fail_on_host: no
  - fix: None required; tell the owner these lines are expected noise.
