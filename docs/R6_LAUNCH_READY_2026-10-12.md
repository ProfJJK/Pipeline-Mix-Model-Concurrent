# R6 owner launch package — 12 October 2026

**Current command, 13 October:** [R6 startup after successful sign-in](RETURN_SETUP_R6_2026-10-13.txt).
This reuses the installation below, verifies R4 v7 and all sessions, and applies
the separately bound Pro retirement at startup. Earlier commands are historical.

**Update: the owner ran this package. Installation completed; authentication
held and R4 was restored. Do not rerun the fresh-install command below. Use
[the separate authentication recovery](R6_AUTH_RECOVERY_2026-10-12.md).**

The owner command is in [RETURN_SETUP_R6.txt](deployment/windows-deployment-next/RETURN_SETUP_R6.txt).
It installs R6 with the released R5 repairs; it does not require a separate R5 sitting.
Source commit: `359ca92e57b2d74eb407b258cf53123d80ef1467`.

| Artifact | Location / SHA256 |
| --- | --- |
| Frozen source, 192 files | `C:\Users\ansac\CoChem427\r6-source-359ca92` |
| Source manifest | `6c9f251f480062f8e9acb828329be9c83fe6d5d2e25a1d0c8723046c157dc3e1` |
| Application wheel, 172 package files | `C:\Users\ansac\CoChem427\r6-build-359ca92\dist\cochem-4.2.7-py3-none-any.whl` |
| Wheel SHA256 | `d294ea29677b4c44c4cebd36f3cd8feb82b27812923781a5a73481a3ef9d5300` |
| Install bundle, 301 files / 127,279,313 bytes | `C:\Users\ansac\CoChem427\r6-bundle-359ca92` |
| Install manifest | `bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4` |
| Candidate | `a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288` |
| Launch package, 476 pinned inputs | `C:\Users\ansac\CoChem427\r6-launch-359ca92` |
| Launch manifest | `155481b2c980c210517d46b4fb0eb73079563bc2b410cecbf9d98758d2d61283` |

## Verified preparation

- Serialized Windows/Python 3.12 source and inert PowerShell fixture selection:
  **413 passed in 48.56 seconds**. Overlaps earlier selections; do not add counts.
- The actual packaged `run_r6_launch.ps1` ran without Apply and returned
  `R6_LAUNCH_PLAN`, four shared slots, 27 targets, no later prompts, host execution false.
- The actual packaged installer ran without Apply and returned `READ_ONLY_PLAN`
  after verifying all 301 payloads and the protected Python/uv executable pins.
- Offline application build matched every frozen package module/asset. Runtime
  dependencies are 106 locked Windows/Python 3.12 wheels; no privileged download
  or source build is needed during the owner's sitting.
- Code review plus separate failure-path fixtures covered helper import scope,
  pinned-file drift, private receipt binding, partial quota availability, mandatory
  Gemini Pro High, sequential phase stopping, and disabled-first activation.
  No independent reviewer session was launched under the one-session host rule.

The packager's `launch-prepared.json` intentionally says
`reviewed_for_owner_execution=false`: assembling files alone is not review. This
document records the subsequent review and actual read-only entry-point checks.
Neither preparation receipt attests deployment or native acceptance.

## Scope and remaining host evidence

Only the owner runs Apply. All planned interaction is at the start, bounded to
20 minutes; long checks/cutover are unattended. An unexpected prior runtime or
missing/ambiguous authentication produces an early hold. The last confirmed
predecessor was R4/R4-restore; ordinary task inspection was denied, so the elevated
preflight must verify the current state. No claim is made that it remains unchanged.

SYSTEM agent custody, native selector behavior, database preview, process/socket
identity, and R6 health remain actual Windows acceptance to be collected by the
owner command. Existing Linux results are historical and do not satisfy those.
Provider quota exhaustion is recorded without claiming an unprobed route passed;
unsupported protocol or contradictory identity holds activation. Gemini Pro High
must pass. Full SRS acceptance and coding workflow acceptance are not claimed.

R7 protected hot catalog activation and any new consequence-risk floor are outside
this completed R5/R6 launch package and remain pending; the latter has no adopted
threshold policy. No daemon, task, protected state, credential, R: setting or
original database was changed by the preparation session. Commits are local,
not yet published to origin.
