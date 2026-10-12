# R6 Agy status prefix repair and reviewed R7 continuation

## Actual Windows evidence

The owner ran `r7-bundle-70af569`. Its R6 prerequisite verified the completed
R6 installation, stopped R4, and rechecked 18 subscription sessions. All six
Codex and six Claude sessions passed with cleanup verified. All six Agy checks
exited 1 with empty stdout and identical 122-byte stderr SHA256:
`148fc48c6aeaf4d5f5780d0e38fc39215de098c1537c57e09410d4dad9718a1d`.

Reconstructing the following exact UTF-8 bytes, including both LF endings,
produces that reported length and hash:

```text
Fetching available models...
Error: Please sign in to view available models. Launch the CLI without arguments to sign in.
```

The recovery checker recognized the second line without its `Error: ` prefix,
but omitted this native form. It therefore reported `STATUS_UNVERIFIED` instead
of offering attended login. This is a source defect. These isolated worker
profiles need Agy subscription sign-in; it does not establish that the owner's
regular Agy profile is unavailable or signed out.

The preserved status reports under
`C:\Program Files\CoChem\R6Sitting4.2.7-windows-20261012-d31408eed013418a8e64c9a4b8d6734b`
confirm an authentication hold without R6 cutover. Owner output confirms R4
restore v3 with native SYSTEM process/socket and knowledge health verified.
Start receipt SHA256:
`3e32dc204f9003c709a758f9025610204b4596cfaa67ac31be379bd7a94a067b`.
Its controller admission-ready state was false; this is not full deployment
acceptance. R7 installation, migration and start were not attempted.

## Replacement behavior

The exact prefixed status line is now an allowed explicit sign-out response.
Additional unknown error text still holds; exit 1 alone never authorizes login.
Future unresolved Agy output is saved create-only in the private SYSTEM phase
root, with no arbitrary output added to public status records.

The existing failed recovery root is preserved. A fresh owner run may pass it
only after verifying its exact 18-session inventory, six stream fingerprints,
original helper identity, pre-cutover hold, hash-bound R4 restoration and terminal
one-shot task with the original protected definition/ACL. Every other previous
recovery root remains a hold. Later acceptance/index state also still blocks
repeat preparation. No attempt is automatically retried or reset.

New R7 packaging copies the immutable corrected earlier R6 recovery and replaces
only its two reviewed recovery helpers; the copied launch entry still inherits
the outer absolute 20-minute input deadline. All other recovery inputs and all
delivered prior packages remain unchanged. No R6 reinstall is requested.
Successful Codex/Claude sessions are reused. Only verified Agy logout can invoke
the existing attended login bridge for that worker. All prompts remain at the
beginning; a closed deadline holds without later input.

## Engineering verification

**93 serialized Windows/Python 3.12 source and inert PowerShell tests passed in
43.88 seconds.** Coverage includes the exact owner fingerprint reproduction,
ambiguous-prefix refusals, private create-only evidence, reviewed prior-task
terminal checks, prerequisite-before-stop ordering, unchanged inputs/repinning,
login deadline clamping, and the R6/R7 launch failure boundaries. The reproduction
failed before the fix. Earlier R7 runtime verification remains 330 source tests;
runtime logic and the approved routing matrix are unchanged by this repair.

No engineering Apply, elevation, native CLI/model execution, task/lifecycle
operation or protected-state write was performed. Source tests do not establish
Windows SYSTEM acceptance. Actual repaired authentication, the 27 native target
checks, R6 activation and R7 publication remain owner-run deployment work.
