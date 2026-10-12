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

## Returned diagnostic and source repair

The owner returned the sanitized diagnostic at 23:05:50 UTC. It verifies one
submitted line, closed/deleted input, terminal native/task failure and cleanup.
Neither reviewed token-storage location contained a credential after this
attempt; token contents were not read. The native process ran for **62.08 seconds**.
The owner confirms that Google returned an authorization code and that this was
the value entered into the masked prompt.

Read-only inspection of the compiled Go function
`google3/third_party/jetski/cli/printmode/printmode.waitForAuth` found a
`time.Now().Add(60 seconds)` deadline in both the protected Agy executable and
the newer executable in the owner's ordinary installation. The protected file
SHA256 is `38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741`;
the ordinary file SHA256 is
`fbbfb3f15c7628252c5e12765683c688ba05ee122b853cadeb0bbfd4e13ca25b`.
Neither executable was run. No version label is inferred from these files.

This makes the print-mode deadline a strong suspect, rather than proving the
precise provider failure. The generic authentication-failure marker is not an
explicit timeout marker. Updating the executable alone retains this deadline.

`r6_attended_agy.ps1` now selects the existing bridge's `tui` login mode for
browser authorization. This uses its reviewed no-argument Agy launch and CRLF
input protocol. It retains the absolute initial 20-minute input cutoff, owned
process cleanup and status-first checks. Only a fresh successful native status
check establishes authentication; pasted input and token presence do not.
Actual SYSTEM/worker authorization through this mode still requires owner-run
host acceptance.

The recovery verifier admits only the exact hash-bound failed session above,
its terminal SYSTEM task, pinned helper bytes, absent input packet and verified
R4 v5 restoration. It does not execute or modify the old session. Unknown roots,
extra tasks, running instances, changed receipts and later acceptance phases
continue to hold. A separate final inventory check reconciles the older
pre-login console hold with this one reviewed later session.

The fresh R7 package builder explicitly overlays the repaired attended helper
into its R6 prerequisite copy. Earlier delivered packages remain unchanged.

Final ordinary Windows/Python 3.12 verification passed **461 distinct tests**:
408 Agy bridge/history/status, diagnostic, recovery and bundle fixtures in
105.84 seconds, followed by 53 launch, migration and authentication fixtures in
11.20 seconds. Both selections ran through the serialized source-test harness.
The earlier restricted-sandbox file/handle failures passed with ordinary account
filesystem access; no production boundary was weakened. These tests use inert
host/provider boundaries and temporary files/databases. They do not execute
SYSTEM tasks, providers, OAuth, deployment or machine lifecycle operations.

## Private-evidence boundary

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

The diagnostic contains no authorization code, raw after-input provider text or
credential values. That discarded text cannot be reconstructed. The returned
diagnostic and owner's description now support the bounded repair above; they
do not prove successful OAuth or R6/R7 deployment. The failed delivered R7 package
remains immutable. Replacement package identity and verification are recorded
separately in the launch-ready handoff.
