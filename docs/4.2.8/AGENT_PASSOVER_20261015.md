# Pipeline 4.2.8 operational recovery: agent passover

## Start here

The owner is changing agents because of quota, not cancelling the work. Read the
PowerShell result appended to the new agent's prompt **before deciding the next
action**. At this handoff, the result of the latest `90c9c1d` recovery has not
been received. The previous packages are spent. No agent has executed Apply.

The immediate objective is to finish the approved operational recovery, verify
Codex submission access, and demonstrate actual successful useful jobs. Direct
local pipeline maintenance is authorized and exempt from `pipeline_code`.
Do not restart the original R6/R7 project or repeat the resolved design questions.

| Item | Current authority |
|---|---|
| Repository | `https://github.com/ProfJJK/Pipeline-Mix-Model-Concurrent.git` |
| Active checkout | `C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent-428-repair` |
| Branch | `fix/428-operational-repair` |
| Delivery/documentation baseline before this handoff | `714d560b35a475df382b2943317575ab41a4e14c` |
| Tested recovery launcher source | `90c9c1df400ed831c1bbb82683d05e4eaaba8847` |
| Unchanged installed payload source | `865a29b113a8b59c822f6aa4d921a45c18407fe5` |
| Deployment workspace, called `W` below | `C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next` |
| Required Python 3.12 | `C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\.venv\Scripts\python.exe` |

Inspect Git status before edits and preserve all later changes, untracked files
and local commits. The handoff itself is in a later documentation commit; do not
reset to the baseline above. Work outside Google Drive. Do not switch the other
agents' checkouts or modify their exam, YouTube or Antigravity integrations.

Read [AGENTS.md](../../AGENTS.md), this document, then the
[latest package and repair explanation](OPERATIONAL_OBSERVER_ACL_RECOVERY_20261015.md).
Older owner-command pages are historical even if their bodies still contain a
command. The older root handoff and R6/R7 instructions are not current launch
instructions. This handoff supersedes their operational status, not their
preserved evidence.

## Latest owner package: result pending

Immutable directory:
`C:\Users\ansac\CoChem427\r428-op-recovery-90c9c1d`

| Pin | Value |
|---|---|
| Launch manifest SHA256 | `a0cb076c2bfa31600d60de1c4969372601af5ac64a44bdc0b67390445d1f22a2` |
| Packaged launcher SHA256 | `5b8c49821dba41c2fcab3abdcb302d22a89b1da6574c2e08a26ddab2c889de4f` |
| Recovery contract SHA256 | `1bac767ec41a6b03361a3f9248571ad1bf212307f277222d1a27374686ceddfd` |
| Source-test evidence SHA256 | `1cb888e697b91917240f89d8ac01f4e09c3eb1726dd105da21bfbdc7ba51f243` |
| Recovery ID | `09bc46790fa14c2cbf85450f158550fe` |

Expected sanitized report directory:
`C:\Program Files\CoChem\R428OperationalRecovery-20261015-a62bffb278044fffbaf21207a866ff81-09bc46790fa14c2cbf85450f158550fe`

The owner already has the pinned command in
`W\RETURN_SETUP_428_OPERATIONAL_RECOVERY_90c9c1d.txt`, mirrored in
[the tracked owner sheet](../deployment/windows-deployment-next/RETURN_SETUP_428_OPERATIONAL_RECOVERY_90c9c1d.txt).
Do not resend it as a fresh command without reconciling the appended result and
one-use claim. Once started, it is spent, regardless of the outcome.

The package reuses the installed 4.2.8 operational r5 payload and existing
sign-ins. It does not install the old 4.2.7 R5 revision. No sign-in, browser,
choice, reboot or later manual continuation is planned. The owner's limit is
20 minutes of active input at the beginning; unattended execution may take
longer. Do not invent a duration guarantee.

## Handle the appended PowerShell result

### If it reports success

Expected terminal status is `R428_OPERATIONAL_RUNNING_VERIFIED`. Match the actual
manifest, recovery ID, runtime source and receipt; a copied command or partial
log is not success evidence. Then:

1. Read sanitized final status and verify current controller identity against
   the successful receipt: version, instance ID, PID, process start time and
   installed source root. Check `task_planning.status=ENABLED`,
   `task_planning.execution_materialization=CONNECTED`, and no trip errors. Running does not
   imply all routes are usable or that useful jobs have completed.
2. Inspect catalog acceptance/coverage holds and preserved quota/backoff state.
   Do not lower reasoning floors, invent selectors or resubmit jobs to evade a
   wait. Examine `codex_integration_status` and
   `codex_session_refresh_required`. New MCP tools/global rules require a
   refreshed Codex session; never claim an unavailable tool was called.
3. Use the `codex-pipeline` skill at
   `C:\Users\ansac\.agents\skills\codex-pipeline\SKILL.md` and the
   `cochem-pipeline` MCP server for pipeline health, configured projects and
   submission/completion inspection. Select the project registered for the
   intended repository, never the `windows-acceptance` fixture. Read
   [the integration audit](CODEX_INTEGRATION_20261015.md).
4. Continue the already-authorized, once-only useful-work acceptance below.
   Check existing IDs and the permanent ledger first. An intake acknowledgement
   is not proof of execution or completion. Verify final receipts and actual
   requested artifacts, with their assertions, hashes and tests.

### If it holds or fails

Preserve the package, reports, receipts, tasks and running processes. Read the
new public sanitized `status-*.json` and the pasted result. Capture phase,
substage, frames, process rejection, observer proof, publication state, fence
cleanup and rollback. Do not assume the old runtime is healthy, or blindly
restore r4 after an uncertain publication. Do not repeat Apply, reinstall,
stop the observer, close MCP clients or ask for another sign-in.

Reproduce the actual failing boundary in source. Check the original installer
and host-shaped inputs rather than mocking the failing validator away. Use
available sanitized evidence first. Only if required details remain private and
unreadable should a new bounded, reviewed, read-only export be prepared for the
owner. Avoid another round of owner commands for information already present.
Never expose raw provider output, credentials, OAuth links or codes.

After a verified source repair, create a **fresh** immutable recovery package
and recovery ID, retaining the original installed-runtime evidence and one-use
guards. Update recovery authority only when supported by the new receipt.
Do not turn a continuation into an unreviewed reinstall or mutate any delivered
package. Only the owner executes the new reviewed Administrator command.

### If output is partial or absent

If still running, inspect new bounded sanitized status only; do not start a
second attempt or interrupt it. If no result was appended, continue independent
source/context review and obtain the result before a dependent action. Elapsed
time does not prove success or authorize retry. Do not poll unchanged remote or
host state repeatedly.

## What went wrong and what the latest change fixes

| Spent package | Verified outcome |
|---|---|
| `r428-op-launch-865a29b` | Installation and Codex preflight completed; admission fencing held. Diagnostic proved an expired unreleased fence and an ended r4 Warden, with no instances/listener. No catalog acceptance or cutover. |
| `r428-op-recovery-01f782a` | Preconditions rejected process inventory; source omitted existing legacy Codex/Claude `cochem_mcp` bridges. Exact rejected PID was not recorded. No new fence/task change/cutover. |
| `r428-op-recovery-4eabf2e` | Rejected PID 9612 as `PROTECTED_PYTHON`. Exact command hash identifies the historical observation-only supervisor. No new mutation/cutover. |
| `r428-op-recovery-490bf2e` | Immutable observer files/records passed, then parent PID 3132 failed `Assert-OpObserverTask` at its call to the Warden-specific `Assert-428TaskAcl`. No new mutation/cutover. |

The observer's original installer uses `task-private-acl-v8.ps1`, whose supported
Scheduler service-descriptor projection requires independent protected task
backing-file proof. The new verifier had incorrectly used the stricter,
different Warden policy. Earlier fixtures substituted a no-op for this ACL
boundary, so the 273-test run missed the compatibility regression.

`90c9c1d` adds observer-only `Assert-OpObserverTaskAcl` for the exact historical
task. It retains v8-equivalent service-descriptor checks, a fixed task backing
path, exact retained file identity/non-reparse ancestry/single-link proof, and
the protected SYSTEM/Administrators full-control backing ACL. The temporary
read handle prevents replacement during verification and closes in `finally`.
Wrong names, unsafe grants and missing custody still reject. Common Warden
rules are unchanged; the verifier makes no ACL or task changes.

The exact live descriptor and backing ACL remain unread by the ordinary process;
the owner run establishes those facts. Do not claim the live representation was
proven by source tests or preemptively weaken the check if another hold occurs.

Historical observer identity, for locating evidence only:

- Task: `CoChem-4.2.7-HeldSupervisorObservation-20261007-r3-v1`.
- Root: `C:\Program Files\CoChem\SupervisorObservation4.2.7-windows-20261007-r3-v1`.
- Staging: `C:\Program Files\CoChem\Supervisor4.2.7-windows-20261007-staging-v1`.
- Recorded child/parent PIDs: 9612/3132. PID alone is never identity authority.
- Child command SHA256: `65cc7f13e318c4f9dbd794c7699251ba223b813024a8d831f216216d45645f3c`.
- Parent command SHA256: `424a4b8d2f45222469cd07875d0c9cefcd86d0d5092af74e822b33bc818f2119`.

The read-only file verifier previously checked 120 immutable files, including
109 installed application files, plus a fresh public heartbeat. Paid repairs,
component recovery, Warden actuation and full acceptance were all disabled in
that observation evidence. Preserve it; do not whitelist arbitrary Python.

## Verification already completed

At exact launcher source `90c9c1d`, **315 serialized source/inert tests passed in
78.13 seconds**, no skips or deselections. Fixtures now exercise real Windows
descriptor parsing and retained temporary file streams, including negative
ACL/name/custody cases. Independent source/package review found no blocker.
The actual packaged Windows PowerShell 5.1 read-only plan returned
`READ_ONLY_PLAN_VERIFIED`; Apply was not run by the agent.

Preparation and independent review rehashed 15 direct package files and 406
original external installation inputs, totaling 130,560,536 bytes. The original
runtime payload, common Warden helpers and protected-evidence contract remain
unchanged. The one-use guard is intact. Keep the external input directories.

Evidence: [tracked directory](evidence/operational-recovery-90c9c1d/), with exact
original bytes in `C:\Users\ansac\CoChem427\r428-op-recovery-tests-90c9c1d`.
Tracked text logs use LF; manifest pins refer to original local/package bytes.
The earlier integrated source regression at `aa7706e` passed 973 tests, one skip
and eight documented exclusions; see [VALIDATION.md](VALIDATION.md).
Neither run proves protected/native acceptance, deployment, universal route
availability or useful-job success.

The focused eleven modules are `pipeline_tests/test_` plus:

```text
operational_launch_428.py
operational_fence_cleanup_428.py
operational_recovery_428.py
operational_recovery_package_428.py
operational_fence_diagnostic_428.py
operational_process_roles_428.py
operational_observer_roles_428.py
operational_observer_acl_428.py
operational_release_428.py
owner_admission_fence_428.py
owner_task_catalog_428.py
```

Run appropriate changed-boundary tests using the required Python and
`-I scripts/run_source_tests_428.py --timeout-seconds 180 --lock-timeout-seconds 60 -- <test paths> -q --tb=short`.
The wrapper uses `W\serialize-heavy.py` and the shared
`C:\Users\ansac\CoChem427\heavy-run.lock`. Serialize all suites/builds. Do not
run native, real process cleanup, provider or host-lifecycle tests. Inert
PowerShell fixtures, loopback HTTP and temporary SQLite are permitted. No test
rerun is needed merely for this documentation handoff.

Key repair/package entry points:

- `scripts/run_operational_428_launch.ps1`: recovery preconditions, exact process
  roles, observer proof, fence/transaction and final sanitized result.
- `scripts/prepare_operational_recovery_428.py`: exact committed launcher,
  original package and external-input verification, fresh recovery ID, pinned
  source-test evidence, fresh destination. Inspect its CLI/schema before use.
- `docs/deployment/windows-deployment-next/task-private-acl-v8.ps1` and
  `install-held-supervisor-observation-r3-v3.ps1`: original observer authority.

If another package is necessary, commit the tested launcher, bind source-test
evidence to that full commit, use the preparer with a new ordinary destination,
independently rehash/review all inputs, and run only its read-only plan. Preserve
old packages. Deliver one fresh owner sheet with the manifest pin and report
location; never claim host success from package preparation.

## Useful-work acceptance and remaining scope

Read [selected useful-work intake](SELECTED_USEFUL_WORK_INTAKE_20261015.md) and
[legacy recovery](LEGACY_BACKLOG_RECOVERY_20261015.md). Three quick-reference
jobs are prepared, **not submitted by this repair session**:
`quickref_Ssulfo-2016-Salazar_0`, `quickref_Ssulfo-2019-Chevallier_0`, and
`quickref_Ssulfo-2012-Bermdez_0`.

Private preparation:
`C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\backlog-preparation-20261015\review-v1`

- `useful-work-selection.json` SHA256:
  `68790ffc1bfa2e9be6c8c520aefa983c8cd92126f54c1c9ffd5ff03b66ad3474`.
- `resolved-recovery-plan.json` SHA256:
  `f5b8f7b3c521ae2c0f7f9a0a8768bd0bc3cd856226603cef9b5d48f367b5163b`.
- Permanent ledger: `review-v1\selected-submission-ledger.db`. Inspect and keep
  it if present; never switch/delete it to force resubmission.

`scripts/submit_428_selected_work.py` is the reviewed separate intake client,
defaulting to inspection only. After verified deployment it needs an actual
receipt-matched controller binding and existing client-config hash. Follow the
skill/MCP workflow for live health, projects and completion; preserve this
selection's durable ledger and deterministic IDs for any submission path.
Do not expose the client token or copy credentials into a report.

The approved `--submit` path reserves before its single POST, reconciles by
exact-ID GET on timeout, and never retries POST automatically. Authenticated
transport and current-board deduplication still need live verification. Use a
fresh evidence destination but the same permanent ledger. The three exact IDs
are in the selected-work document; check them before submitting. No bulk import
of the 605 review candidates or deletion of the 610 archive-review rows is
authorized by this acceptance exercise. Keep all original databases/captures.
Inputs are cited excerpts, not full papers; final assertions must respect that
limit. Verify the requested JSON and Markdown deliverables, not just job status.

The seven owner-approved operational repairs are described in
[the amendment](OWNER_AMENDMENT_20261015_OPERATIONAL_REPAIR.md),
[progress](PROGRESS.md), [launch design](OPERATIONAL_OWNER_LAUNCH_R5.md) and
[original delivery](OPERATIONAL_R5_DELIVERY_20261015.md). Source includes CPU
admission units/transient-pressure recovery, isolated repository preparation,
upfront output contracts and bounded format corrections, preserved backlog and
submission ledger, scoped Codex integration, and connected planning/execution.
Their source implementation is not a claim that this recovery has activated them.

Known remaining limits must stay visible:

- Strict benchmark/reasoning floors can leave task-type/tier combinations or
  different-family review without an eligible route. Keep explicit holds.
- Completion-audit dispatch and independent repair callbacks are **unconfigured**;
  fixture implementations are not operational self-healing.
- Gemini quota exhaustion is expected; preserve availability/backoff, repair and
  dispatch budgets. Do not assume a new selector, effort or quota is available.
- Gemini Pro was removed; the owner approved keeping the reasoning floor and
  using existing Claude/Codex choices with backoff at tiers 5/6. Do not restore
  the superseded Pro requirement from older heartbeat instructions.
- For 4.2.8, only complexity 8-10 requires owner SRS approval; lower multi-type
  tasks get WBS decomposition. Tier-10 review uses a different tier-10 model at
  maximum effort. Separate consequence-risk floors were not adopted.

## Non-negotiable host and interaction boundaries

Follow repository AGENTS.md. Agents do not elevate, run Apply, change protected
runtime state, perform task/service/WSL/Docker/Hyper-V/R: lifecycle actions,
launch native/headless providers or kill process trees. Do not stop existing
observers/clients or clean preserved evidence. Keep four shared slots, Chapter 06
routing, credentials, databases, prior job captures and repair budgets intact.
Do not reactivate historical automations or message other threads as part of
this handoff. The user will start the new agent by pasting the saved prompt.

Use ordinary source edits, serialized inert tests, independent review, commits
and non-forced pushes for authorized repairs. Preserve all local work. Prepare
concrete owner-only changes before requesting any necessary administrative step;
do not ask again for already-granted design or source-maintenance permission.

If sign-in ever truly becomes necessary, the approved common Codex/Claude/Agy
interface is a fresh selectable URL, Copy URL and a normal masked Ctrl+V/Submit
dialog where the provider requires a callback. The owner opens the browser;
profiles are sequential and verified sessions are reused. No automatic browser,
TUI navigation or raw console key controls. Codex device codes belong in the
browser. **The current operational recovery plans no new sign-in.**

Report verified source work separately from actual host results. The owner has
already spent hours on failed launch/diagnostic rounds: minimize further input,
identify actual causes from evidence, and do not turn a held attempt into a
claim that the pipeline is working.
