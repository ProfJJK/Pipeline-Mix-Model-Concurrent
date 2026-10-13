# R6 continuation after the proved directory-custody defect

## 09:18 continuation hold and permission-boundary repair

The owner ran `r6-launch-bf5b5f6`. Its public sitting report under
`R6Sitting4.2.7-windows-20261012-40103f08e0e344a19ee1d64d0231b805`
records `UnauthorizedAccessException` (HResult -2147024891) in
`Assert-R6CustodyContinuationEvidence`, line 440. That line called `Test-Path`
against the private ProgramData knowledge state from the owner process. The
hold preceded R4 stop, any new SYSTEM phase and cutover. R4 v8 was running at
inspection. Preserve that package and evidence; do not rerun its command.

The corrected owner preflight verifies the pinned candidate and historical
receipt without opening the private state. It explicitly reports
`knowledge_state_verified=false` and
`knowledge_state_verification=REQUIRED_IN_SYSTEM_KNOWLEDGE_PHASE`. The existing
mandatory SYSTEM phase remains responsible for current directory ACLs,
generation, canonical authority, integrity and unchanged bytes. Missing or
inaccessible state is rejected before construction of the knowledge service;
no create, refresh, ownership or ACL repair is attempted.

Review also found a second defect before execution: the SYSTEM helper used
`r6_host_acceptance.read_bound`, whose validator only accepts protected code
under Program Files/Windows, for the ProgramData pointer and index. Those
reads now use the installed knowledge service's `_read_bytes(private=True)`
and `_ancestors` checks. The private reader enforces ACLs, ordinary files,
single file links, size bounds, opened-file identity and unchanged metadata.
The prior Program Files receipt still uses the original hash-bound code reader.
Canonical and frozen installed `knowledge.py` bytes match, SHA256
`1bf720ed5df342704552b3e0996ee1cdaebd8f9d7f26fc345b4e5a848e2d2f0f`.

Both permission errors were reproduced in regressions before their fixes.
The tests now deny owner access to private state and reject treating private
state as code. They also exercise the production private-file validator with
an explicit temporary ACL adapter, reject failed private ACL checks, and prove
missing/inaccessible state cannot reach service creation. Temporary SQLite
verification preserves file bytes and mtimes. These remain source/fixture
tests, not actual SYSTEM acceptance.

The remaining owner-side checks were reviewed: installation tree/interpreter,
receipt readers and activation index stay under Program Files; task inspection
uses the owner-admin scheduler interface. Private state reads stay in the
SYSTEM knowledge phase. Its successful receipt remains mandatory for cutover.

Final source/fixture verification for this correction: **300 passed in 76.45
seconds**, serialized under repository Python 3.12. Coverage includes both
permission regressions, unchanged Win32 directory sharing, knowledge/activation
interoperability, phase ordering, stop-on-failure, preservation and startup
amendment binding. No live provider command, SYSTEM task or daemon ran in these
tests. The earlier 297-test run below describes the previous package.

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

## Previous package (spent at 09:18)

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
Do not replay this package, earlier launch packages or the spent diagnostic.
Preserve all their files and receipts unchanged. Replacement package details
are recorded below after the frozen read-only plan passes.

## Replacement package after the 09:18 hold

**Update after the 09:34 owner run:** this replacement is spent. All 18 sign-ins,
knowledge and agent checks passed; native acceptance held. R4 v9 restoration
did not verify. Follow `R6_NATIVE_HOLD_2026-10-13.md`; do not replay the command
below or any earlier package. The following preparation details are historical.

Source checkpoint **7451831** supplies both permission-boundary fixes. Fresh
ordinary package: `C:\Users\ansac\CoChem427\r6-launch-7451831`, **499 pinned
inputs**. Launch manifest SHA256:
`dbfd6bdb36299c85d4c1f1af78724749ff45ef1b5b31157731802cae220c6435`.
The frozen entry point's read-only plan passed with exit0 in **7.136 seconds**.
It reports reuse of verified sessions and completed knowledge, no profile
restaging, the directory-custody amendment, 26 retained model targets and four
shared slots. It performs no privileged installation or host acceptance.

The owner command is in `RETURN_SETUP_R6_2026-10-13.txt` and the ordinary
deployment workspace's `RETURN_SETUP_R6.txt`. Start it once from Administrator
PowerShell, then walk away while the computer remains awake. No new sign-in
or later manual input is planned. Preserve and report any hold; do not replay
older packages. The previous immutably installed R6 and all failed packages
are preserved; this new supplemental helper is copied and hash-bound only
during the owner-run continuation. The engineer has not run Apply or changed
the Warden. R6 startup and actual SYSTEM/model acceptance remain unverified.
