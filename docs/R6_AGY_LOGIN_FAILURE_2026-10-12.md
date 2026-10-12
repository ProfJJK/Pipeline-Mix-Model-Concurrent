# Actual attended Agy failure after the console correction

The owner ran `r7-bundle-e32949a` at 17:43:38 local on 2026-10-12. The
readable status records and owner transcript establish the following Windows
evidence; these are separate from source and fixture test results.

- Existing R6 installation verification completed. R4 restore v4 was stopped
  through the reviewed owner sequence.
- Six Codex and six Claude subscription sessions were reused. All six isolated
  Agy profiles returned the captured explicit sign-out status, with cleanup.
- Slot1 displayed the Google authorization URL and native code prompt. The
  console accepted one line and the bridge receipt confirmed it was fed to Agy.
  The earlier redirected-console defect is no longer the stopping boundary.
- Agy exited 1 with `authentication_failed_present`; bridge cleanup was verified.
  No later worker login was started. This does not establish an invalid code,
  a timeout, a provider outage, or a need to reset credentials.
- The sequence restored R4 v5 with SYSTEM process identity and health verified.
  Its health response reported zero admission capacity. This is not full pipeline
  acceptance. R6 was not activated and R7 installation/cutover was not attempted.

The failed sitting is
`C:\Program Files\CoChem\R6Sitting4.2.7-windows-20261012-87bf2f05e1254ea6b5e7de51018b830c`.
The preserved interactive session is
`C:\Program Files\CoChem\InteractiveAgy427-r4-slot1-67d70b0983cc48e2abf7c561aca29f86`.
R4 v5 start receipt SHA256 is
`978bad6cf2773df7151c21cca988e4ebd9a4549f9639976f920a9567d803528c`.
All earlier packages, tasks and receipts remain preserved. Do not repeat the
failed deployment command as an automatic recovery.

## Remaining evidence boundary

Windows denied the ordinary engineering process access to `session-held.json`.
Readable `status-*.json` records omit the native marker phases and timing.
The bridge intentionally never records raw native output after secret input;
discarded text cannot be reconstructed or claimed as reviewed evidence.

`scripts/inspect_r6_agy_failure.ps1` is a read-only owner diagnostic. It reads
only the exact session's two JSON receipts, bounded authentication metadata and
the R4 v5 start receipt. It writes one fresh allowlisted report in the ordinary
deployment workspace. It never opens `operator.log`, input packets, worker
profiles, credentials or databases, and never starts or changes a task/provider.
The report records fixed booleans/enums, timestamps, counts and evidence hashes;
unknown free text and secret-shaped values are excluded or refused.

The owner copy is
`windows-deployment-next\inspect-r6-agy-failure-20261012-v1.ps1` in the chat
workspace. SHA256:
`2b4215656f797eb14389a1a994cd60ea1072916fbd74a100f70d458cbe298701`.
The owner needs their administrator window only for reading the existing private
receipt. A report path suffices; no private log or authorization code is requested.

**10 serialized Windows source/inert PowerShell tests passed in 3.99 seconds.**
They verify allowlisting, exclusion of synthetic secrets/provider text, rejection
of malformed values/schema, and hashing on the same read handle. They do not
execute OAuth, native providers, deployment or host lifecycle actions.

The returned sanitized report and the owner's description of what the browser
returned are required before choosing a specific authentication repair and
reviewing the new preserved session for any owner-controlled continuation.
The delivered R7 package remains immutable; no replacement deployment is claimed
ready at this checkpoint.
