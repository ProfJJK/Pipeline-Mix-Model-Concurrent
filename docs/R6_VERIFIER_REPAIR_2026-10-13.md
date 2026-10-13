# R6 verification repair after the 07:14 owner attempt

The owner ran `r6-launch-2571003` at 07:14 on 13 October. The attempt
`7239742a842546319b094d50ffe61b73` held during `verify_existing_installation`,
before the R4 stop or R6 cutover. Its initial inspection verified the R4 v7
task enabled, one running instance and one port listener. Preserve this attempt
and its immutable package; do not replay that command.

## Reproduced defect

`Assert-R6VerifiedSignInRows` accessed `row.login.cleanup_verified`. The actual
`worker_agy_signin_batch.sequence` writer puts that value on `row.cleanup_verified`
and omits it from the nested login projection. Windows PowerShell StrictMode
therefore throws `PropertyNotFoundException` on a successful report.

Both the unchanged owner public report (SHA-256
`96e4d2a872ff64a265efde9f1d1dade42db73f9da85863befc93692ece7ccfff`)
and the actual production receipt writer with inert status/login functions
reproduced that exception before the correction. The previous fabricated
fixture incorrectly included the nonexistent nested field and missed the defect.
The private log of this attempt remains inaccessible to the ordinary engineering
process; no claim is made to have read it or excluded every other host failure.

The verifier now checks cleanup at the writer's actual location. It still requires
all six authenticated profiles, fresh successful post-login status, worker and
terminal cleanup, input-file removal, code submission, and the original protected
receipt/task bindings. No authentication, task or isolation gate was disabled.
Missing or false cleanup evidence still holds. No sign-in is repeated.

## Diagnostic improvement

Verification failure now exits nonzero with a structured metadata record after
the private error. The launcher validates and projects exception type, numeric
HRESULT, source function and line into its terminal result and readable status.
Raw exception text, paths from stack traces, provider output, account identifiers,
authorization URLs and codes remain excluded. Unknown malformed metadata is
discarded; the original private log is retained. This applies to the read-only
installation verifier; it does not claim to sanitize arbitrary provider failures.

## Validation and boundary

The serialized Python 3.12 / Windows PowerShell selection passed **233 tests in
60.40 seconds**. Two regression tests failed with the original implementation
and pass with the correction: one uses the production writer, the other reads
the unchanged actual public six-profile receipt. Additional tests reject
incorrect cleanup/authentication evidence, validate metadata redaction and
exercise the real verifier's nonzero exit before any host access.

Source and inert fixture tests do not establish SYSTEM deployment acceptance.
The engineering process has not run Apply, a provider, a daemon or any task
lifecycle action. The replacement launch continues to use immutable installed
R6 source `359ca92`, the reviewed R4 v7 recovery and the prior Pro-retirement
startup amendment. It remains R6-only, with no planned late input or sign-in.
