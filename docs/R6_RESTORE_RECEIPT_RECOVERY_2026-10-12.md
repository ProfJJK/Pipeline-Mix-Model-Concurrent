# Persisted R4 receipt repair for the R6/R7 owner sitting

## Actual Windows failure

The owner ran `r7-bundle-c3080c9`. The R6 prerequisite stopped in
`verify_existing_installation`, before controller quiescence or provider commands.
The owner read the private child log, which reported:

```text
The property 'started' cannot be found on this object. Verify that the property exists.
```

The failed sitting is
`C:\Program Files\CoChem\R6Sitting4.2.7-windows-20261012-a019727bdc404fa99f4c81718564d44a`.
Its readable status records match the owner output: no cutover was requested.
The preflight verified the running R4 restore v3; this failure did not stop it.
R6 authentication, R6 activation and all R7 installation/migration/start phases
were not attempted in this sitting. Its files and earlier packages are preserved.

## Repair and engineering evidence

The recovery guard incorrectly expected `started` in the persisted R4 start
receipt. The actual `Invoke-StartOnce` writer emits `cochem-warden-start/3`, with
task state, running-instance count, stable health samples and exactly-one-start
evidence instead. The repaired guard validates those actual fields. The same
protected file/hash binding and exact previous task/ACL checks remain required.
This does not relax a safety boundary or change an installed receipt.

A regression executes the production writer's pure receipt-construction
expressions, without invoking its lifecycle function. It reproduced the exact
missing-property error before the repair. The final serialized Windows/Python
3.12 source and inert PowerShell selection passed **109 tests in 36.70 seconds**.
It includes changed-receipt refusals and the actual task-definition guard with
changed action, duration, ACL, state and task-result cases. No native provider,
scheduled-task lifecycle operation, elevation or protected installation write
was performed by engineering.

All three actual packaged read-only plans passed in **9.98 seconds**. The new
R6 prerequisite still has 480 pinned inputs; only
`verify_r6_auth_recovery.ps1` differs from the failed `c3080c9` package. The R7
runtime wheel is byte-identical to the previously tested wheel. These checks
are source/package evidence, not repaired SYSTEM/provider deployment acceptance.

## Fresh owner package

- Source checkpoint: `2d63521cb2d4c4084c81f9fce75de615c5d33c8d`.
- Fresh bundle: `C:\Users\ansac\CoChem427\r7-bundle-2d63521`.
- Launch manifest SHA256:
  `196d4e71658b427d3c832f4d4a929209ba35075277acaf7087da87497c6367ee`.
- Source freeze: `C:\Users\ansac\CoChem427\r7-source-2d63521`, 198 files.
- Source manifest SHA256:
  `2e7cd246b3a99e5f3c0ce7145b948f67899d02d87fd74a9afb989e9e4d7ab727`.
- Verified wheel SHA256:
  `8bb9c33b35228df23bc23fb5f4b4b0f1aae61d6a3a657c63a3bd660dbb636c1d`.
- Installer inputs: 307; copied R6 prerequisite inputs: 480.

Use the current `docs/deployment/windows-deployment-next/RETURN_SETUP_R7.txt`.
The one command first reuses the completed installed R6 and checks subscription
sessions; it does not reinstall R6 or copy credentials. Necessary Agy browser
sign-ins remain at the attended beginning, inside the outer 20-minute input
window. After the green walk-away message, all planned work is unattended.
Total runtime can be longer; no later prompt, reboot or continuation is planned.
A closed authentication window holds with preserved evidence.

The exact owner matrix, Gemini Pro High at tier 6, four shared slots, Chapter 06,
R:, sign-ins, original databases/captures and repair budgets remain unchanged.
Actual R6/R7 activation remains owner-run work; full SRS acceptance is not claimed.
