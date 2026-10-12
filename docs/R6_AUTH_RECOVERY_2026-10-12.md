# R6 authentication recovery — 12 October 2026

Use [RETURN_SETUP_R6_AUTH_RECOVERY.txt](deployment/windows-deployment-next/RETURN_SETUP_R6_AUTH_RECOVERY.txt).
Do not rerun the original fresh-install command. Its completed installation and
all original source/build/bundle/launch artifacts remain unchanged.

## Corrected recovery package — supersedes the first recovery command

The owner ran the first recovery at 09:13 local time. It failed before the
controlled stop in `verify_existing_installation`: an AST-imported PowerShell
helper had an empty `$PSScriptRoot`, producing
`ParameterArgumentValidationErrorEmptyStringNotAllowed`. Preconditions had
confirmed R4 restore v2 running; this attempt did not reach authentication or
R6 cutover. The original package and evidence remain preserved.

Corrected source: `eb982cb`. Package:
`C:\Users\ansac\CoChem427\r6-auth-recovery-eb982cb`, with 480 pinned inputs.
Launch manifest SHA256:
`bc1cb7b2c1ac4eac872cfde38b57f382cdef24388a9902f9899020bd10dfbf58`.

The repair passes the package directory explicitly across the AST-import boundary.
86 focused source/fixture tests passed in 36.55 seconds, including a reproduction
of the empty-path error, the actual helper import chain, and complete verification
with inert filesystem/task boundaries. Negative fixtures reject partial installs,
wrong bindings, failed restoration and unexpected later acceptance/recovery state.
The actual packaged read-only launch plan passed in 7.18 seconds. These tests do
not attest SYSTEM deployment or provider acceptance. The updated owner sheet above
contains the replacement command; do not repeat the `3a15ff4` command.

The following sections record the original recovery design and evidence.

## Actual Windows evidence supplied by the owner

The first R6 sitting installed source `359ca92e57b2d74eb407b258cf53123d80ef1467`,
then held in authentication before agent staging, knowledge creation, native
model acceptance or R6 cutover. All six Codex and all six Claude profiles
returned `REUSE_VERIFIED_SESSION`, exit 0. All six Agy/Gemini profiles returned
`STATUS_UNVERIFIED`, exit 1, with cleanup verified. No model jobs were executed.

Original protected auth root:
`C:\Program Files\CoChem\R6Acceptance4.2.7-windows-20261012-v1-auth-3579f2f48a4a479087399688e3eb020f`.
Original sitting root:
`C:\Program Files\CoChem\R6Sitting4.2.7-windows-20261012-fd8b4d855c6942aba8373f196a7161b4`.

The owner output confirms automatic R4 restore v2 with process/socket identity,
controller and knowledge health verified. Its start receipt SHA256 is
`bc5d266a442c4cd99c2a994b9c0f3da02ad1d43cc06dbcc0713c1a2b3053b09c`.
This is the last confirmed host state; the recovery preflight checks it afresh.

The original checker discarded raw status text. Exit 1 alone does not establish
logout, session expiry, permission failure or network failure. Source review
found that R6 omitted the earlier captured plain-text Agy sign-out protocol;
that gap is repaired in the separate status helper, but is not yet proven to
be the cause of this host failure. No instruction to sign in follows from the
old inconclusive records alone.

## Recovery package and behavior

Recovery source commit: `3a15ff4` (runtime source stays `359ca92`).
Package: `C:\Users\ansac\CoChem427\r6-auth-recovery-3a15ff4`.
479 inputs are pinned and held against writes/deletion during execution.
Launch manifest SHA256:
`cb9b000950e78b2e1bea364c3af3e3511ac2c93e89c0035afced01b1dce7faa2`.

Before the controlled stop, read-only recovery checks bind the completed R6
install, exact candidate, original 18 status results, successful R4 restoration
and absence of later R6 acceptance/index state. A previous recovery attempt
causes a hold rather than an automatic repeat. No installer is invoked.

A fresh private SYSTEM phase receives the pinned standalone status helper.
It uses the unchanged installed R6 binding, worker identity, resource, RAM,
Docker-denial and cleanup code. The helper recognizes the exact captured Agy
sign-out text only in the fixed non-inference models command. Unknown failures
remain unknown. Success requires an actual Gemini catalog row and the reviewed
success envelope. Provider-generated answers never enter this status parser.

All 18 sessions are rechecked. Codex/Claude sign-ins are reused; they are not
copied or reset. Only an explicit Agy logout can invoke the reviewed attended
login bridge, under the same absolute 20-minute input cutoff. The command then
continues the existing R6 staged acceptance/cutover sequence. It requests no
late input. Unresolved early checks preserve evidence and invoke the released
R4 recovery; a requested R6 cutover preserves possibly running state instead
of guessing a rollback. No installed runtime modules are patched.

Fixed authentication reasons are printed and saved in readable `status-*.json`
reports, excluding arbitrary provider messages, credentials and account data.
The complete private phase receipt includes the standalone helper hash.

## Verification and limits

Serialized Windows/Python 3.12 source and inert PowerShell fixtures:
**227 passed in 43.38 seconds**. Coverage includes exact status classification,
18-session traversal, unknown-error refusal, sanitized public results,
preflight-before-stop ordering, no reinstall, first-failure stopping, task
definitions, attended deadlines and existing activation evidence checks.

The actual packaged entry point ran without Apply in 8.62 seconds and returned
`R6_LAUNCH_PLAN` with four slots, 27 targets and no late prompts. This only
measures package validation, not the owner's whole sitting. No SYSTEM/native
recovery or R6 activation has been executed by this engineering session.
Earlier Linux results do not satisfy Windows host acceptance.

Review was performed in this engineering session with separate failure-path
fixtures; no independent agent session was launched under the host rule.
The preparer's `reviewed_for_owner_execution=false` records assembly alone;
this document records the subsequent review and packaged read-only check.

R7 source changes remain separate and are not introduced by this recovery.
Four shared slots, Chapter 06, Gemini Pro High at tier 6, R:, credentials,
original databases/captures and repair budgets remain unchanged policies.
