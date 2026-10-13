# R6 continuation after the proved directory-custody defect

The owner-run diagnostic completed. Its ordinary-readable report is
`C:\Program Files\CoChem\R6AgentDiagnostic427-45da557a0e364dac95d42e2ae2f9a4fc\status.json`,
SHA256 `c124feb02e72f061109624993cb0538ef0ebe30431a3c2eeff39f659ca3b7f0c`.
Installation binding and read-only RAM inspection passed. Slot1 retained all
nine guard handles but its eleven access results stayed
`[0,0,0,5,5,0,0,5,5,5,5]` during custody. The unchanged production verifier
rejected replacement access. Tokens, handles and SID reservation closed.
No later worker was tested. This is diagnostic evidence, not acceptance.

## Cause and repair

Directory handles requested READ_CONTROL alone (`0x20000`). That metadata-only
access does not participate in Windows read/write/delete sharing enforcement.
Adding FILE_LIST_DIRECTORY (`0x20001` combined) makes the retained directory
handles enforce their existing omission of FILE_SHARE_DELETE. File handle
access and sharing, ACLs, all eleven acceptance requests and cleanup checks
are unchanged. Microsoft's [sharing algorithm documentation](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wdm/nf-wdm-iochecklinkshareaccess)
describes the distinction for opens without read/write/delete access.

A regression using real Win32 handles on pytest-owned temporary directories
failed with the old access mask. With the repair, all eleven probes return
sharing violation while held, then return to their original access results
after release. Readers continue working. It runs in one process, without
SYSTEM, worker profiles, provider children, ACL changes or task operations.
The same test covers the canonical source and the frozen-R6 amendment.

The installed R6 remains immutable source `359ca92`. The separate protected
`r6_custody_amendment.py` accepts only its original guard module hash
`d86c90750dc2112ce8ff1bc9a4937898eb35cadbf4362050b04381e2138e6591` and compiles
exactly that one literal change in memory. The repaired source hash is
`6d8cce1fb2896a489c522f79c639256b9b296b8a92db6edc4f006f2105d1e9bf`.
The original wheel's guard bytes were checked identical to the regression
fixture. The amendment preserves the installed AgentGuardError class identity
because NativeRunner catches that class explicitly.

Agent acceptance, native acceptance and the scheduled startup action all bind
the same amendment hash. Activation rejects missing or different repair
evidence, different access/share masks or modified ACL/installation claims.
The protected startup entry point verifies both supplemental files before
calling the daemon. It also retains the approved Gemini Pro retirement:
tiers5/6 use their existing Claude/Codex choices, then back off.

## Reviewed continuation, not a replay

The new manifest opts into `20261013-reviewed-agent-hold-r4-v8`.
It uses a separate history verifier; the old first-auth-hold verifier is not
relaxed. It binds the diagnostic, the successful 18-session receipt, the
completed knowledge receipt, the original agent failure and R4 v8 restoration.
Unknown later acceptance roots and active acceptance/login tasks cause a hold.
The released preflight and stop logic still establish the current task/process
lineage. All previous tasks, files and receipts are preserved.

The owner command performs these steps without interactive sign-in:

1. Inspect current state and verify the exact completed installation/history.
2. Stop R4 through the released transaction and recheck existing sessions.
3. Preserve profile staging and reverify the existing knowledge generation,
   canonical authority and SQLite integrity using immutable read connections.
   Verify pointer/index bytes unchanged across the check; never call refresh.
4. Run all six original worker-custody checks with the repaired guard, then
   remaining native selector acceptance and upgrade preview.
5. Bind the results to the same protected startup amendment and start R6 only
   through the reviewed cutover/health transaction.

There are no planned URLs, code-entry dialogs, late prompts, reboot or manual
continuation commands. A changed session holds without initiating sign-in.
The owner can walk away after launching the single command. Total unattended
duration depends on provider acceptance and startup; no short completion time
is promised. Before the cutover boundary, a hold uses the reviewed restoration
of R4 in a fresh namespace. After task mutation, preserve state and report;
there is no guessed rollback or automatic second attempt.

Future amendment failures export bounded exception types and function/line
metadata into readable sitting status; raw provider text and private paths
stay private. The parser handles PowerShell error text after the JSON report.

## Evidence boundaries

Source, inert PowerShell transaction tests, temporary SQLite and in-process
Win32 sharing tests establish the repair and its binding. They do not establish
six-worker SYSTEM acceptance, model selector support, R6 startup or full SRS
acceptance. Those remain the owner-run command's work. The last verified
restoration is R4 v8, whose admission capacity was zero.

The final selected regression run passed **297 tests in 80.12 seconds** under
the serialized repository Python 3.12 harness. It includes the real temporary
directory sharing regression for both implementations, original acceptance
criteria, exact-history refusal, installed-module exception compatibility,
Python knowledge-result/PowerShell activation interoperability, startup pins,
retirement routing, failure projection, task boundaries and rollback fixtures.
No live model, SYSTEM task or daemon was executed by the engineer.

Keep R7 separate. Older R7 bundles expect the old R6 daemon action and cannot
be reused after this amended R6 startup. A future R7 package must bind the new
R6 source action and include the canonical directory fix; do not reuse its
spent R6 prerequisite recovery.

## Delivered package

Repair source checkpoint: `bf5b5f6` on `feature/r6-routing-pivots`.
Fresh ordinary package: `C:\Users\ansac\CoChem427\r6-launch-bf5b5f6`.
It pins **499 inputs**; launch manifest SHA256:
`621b520f38cc5454e12a0b33092ffe6959a05041b028efe79e95f523d866811f`.
The package retains installed source_commit `359ca92` deliberately; the
supplemental repair is bound separately rather than misidentifying the installed
release. Its assembly receipt remains a preparation record, not host acceptance.

The actual frozen PowerShell entry point completed its **read-only** plan in
8.476 seconds with exit0, 26 retained model targets, four shared slots,
`directory_custody_amendment=true`, `reuse_completed_knowledge=true`,
`profile_restaging=false` and `later_prompts=false`. That timing excludes
privileged checks and unattended provider acceptance.

The engineer reviewed the hash/copy/action chain and source/receipt consumers.
No Apply was invoked. The owner command is in
[RETURN_SETUP_R6_2026-10-13.txt](RETURN_SETUP_R6_2026-10-13.txt), mirrored as
`windows-deployment-next\RETURN_SETUP_R6.txt` in the deployment workspace.
Do not replay earlier launch packages or the spent diagnostic. Preserve this
package unchanged and read the new sanitized sitting status after owner execution.
