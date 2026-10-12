# Pipeline 4.2.7 takeover plan — 2026-10-11

Status: **full release confirmed at `1c71fc062b775e9a5c6508c848c4d4616534cc1a`;
direct local pipeline maintenance authorized; R6 implementation underway**. See
[current progress](R6_PROGRESS_2026-10-12.md). Historical inspection notes below
are retained as history, not current blockers. This plan records the owner's latest
instructions and supersedes conflicting agent-authored routing proposals.

## Owner decisions now settled

- Implement the owner's exact ten-tier matrix in
  [the approved candidate](routing/4.2.7-routing-v3.owner-candidate.json).
  **Retain Gemini 3.1 Pro High at tier 6.** Native subscription exhaustion is
  the owner's stated reason; do not ask this question again.
- Cover all authorized work that can be completed without elevation across
  R5 repairs, R6 revisions, the matrix/pivot changes and the reported R7 items.
- Consolidate the required Administrator PowerShell work into **at most
  20 minutes of active input at the start**, followed by unattended execution.
  The owner's latest clarification permits longer total runtime. There must
  be no planned later prompts, OAuth approvals or manual continuation commands.
- Keep four shared slots, all model jobs on Chapter 06 routing, existing
  credentials/sign-ins, databases, repair ledgers, old job captures and the
  existing 8 GiB R: drive and startup mechanism.
- Support later model-catalog upgrades without recurring source-wide edits.
  The owner's expectation of a later Gemini release is planning context,
  not a verified date, model selector or capability claim.

## Takeover trigger and checkout preservation

Repository: `C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent`.
Remote: `https://github.com/ProfJJK/Pipeline-Mix-Model-Concurrent.git`.
Branch baseline: `feature/r5-gemini-and-runtime-fixes`.
Observed remote/local HEAD:
`e5597063e0b58df666b04cc823fa96009b200c10`.

A fetch on 11 October confirmed that this branch has no local/remote divergence.
The existing published handoff is final for its earlier snapshot, but it is
**not sufficient for the newest takeover**: the live deployment workspace's
`RUN_427_R5_SITTING.ps1` was modified at 21:37:17 America/Chicago, after the
published handoff commit at 20:23:29. Read-only inspection also found newer
starting-state/recovery edits. Do not assume that the Warden is down, r4 is
unchanged, or any earlier task lineage is still current.

The deployment engineering workspace is:
`C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next`.

A thread heartbeat checks every ten minutes. Interim handoff commit `e1ad166`
releases source/R6/R7 work; the owner directly authorized starting it while R5
finishes. Do not wait for final R5 completion to pursue that independent scope.
The R5 sitting scripts and mirror remain reserved until the other agent's
banner says "r5 sitting repair COMPLETE". Its newer uncommitted handoff remains
source material, not permission to replace the owner's exact matrix or timing.
Continue non-admin implementation and preparation until the package is ready.

At the 2026-10-12 04:00 UTC check, origin and the local checkout both contained
final handoff `f9164656f539cb6bf368a3ea4257b90e959ac84a`, headed "r5 sitting
repair COMPLETE". A bounded read-only comparison verified all **509 manifest
entries in both W and the repository mirror**, with no missing files or hash
differences. This supersedes the earlier reservation on R5 files. No elevated
acceptance was performed. The coding connector still lists only the fixture;
the owner's workflow-scope clarification is pending.

Before updating the working tree, preserve the local tip and all local files,
including untracked approved-matrix/research documents. Prefer a fast-forward
when possible; otherwise integrate on an isolated checkout or branch without
resetting local commits. Never clean, force-reset or overwrite files to make
a pull succeed. Do not move work into Google Drive. The unrelated untracked
root scripts/legacy JSON are not part of this release and must not be staged.

## Work inventory to reconcile with the incoming handoff

| Area | Known work | Treatment |
| --- | --- | --- |
| R5 source | Link-count, chapter reconciliation, Gemini identity/errors, Warden memory/admission and reboot-safe startup fixes | Preserve the arriving fixes; do not reimplement already completed work |
| R5 deployment | Six PowerShell binding/scope faults, bridge process classification, real entry-point/child-binding smoke tests | Carry forward latest reviewed runner and pins; current W is newer than published mirror |
| Routing v3 | Ten exact tiers, three distinct underlying models per row, explicit efforts, same-provider alternatives | Implement approved owner matrix; old v1/v2 captures remain decodable |
| Scoring | Low coding tiers currently unreachable due blanket +2; independent scoring duplicated | Version scorer changes explicitly; keep deterministic controller authority |
| Native bindings | Codex/Claude new effort combinations, all-target scans and independent validation | Match actual installed client contracts; no silent Extended/Ultra remapping |
| Pivots | Persistent effective tier, actual-producer model exclusion, higher-tier selection, tier-10 ceiling | Keep quality pivots separate from availability retries and independent-review selection |
| Quota/review | Multiple native Claude/Codex models share their account pool | Skip exhausted pools, preserve model and stricter provider separation where required |
| Catalog updates | Versioned, validated model/effort catalog and upgrade path | Pin each running job's catalog generation; do not change historical receipts |
| Evidence integrity | RG-4 protected agent parent path; RG-5 raw-stream replay checks | Inspect arriving fixes; repair remaining source and staged verification |
| Status/error handling | AGY_ERROR classification, short-lived status process image attestation | Repair source and regression tests where still open |
| SRS/knowledge | Packaged 50 MiB text versus approved 200 MiB Warden budget | Reconcile canonical/package/ledger text without rewriting historic evidence |
| Operator output | Large response/body and clearer resulting-state reporting | Improve without inventing another launch gate |
| Other possible R6 gaps | RG-2 appended logs, truthful outcome after refused rollback | Verify current code before labeling them open |
| R7 | Reported scope not yet present as a released specification | Resolve from incoming handoff; record actual work rather than invent a release |

Current reference:
[11 October handoff](WINDOWS_AGENT_HANDOFF_4.2.7_2026-10-11.md), especially
sections 5, 7, 8 and 9.

The old R6 design, R6A scope, scope-v2 and v3 research are proposal inputs.
Their four-band tables, Pro at 7–9, Agy partner defaults, arbitrary per-model
slot caps and hidden task-type routing do not override the owner's new table.

The only release-R7 references found so far are
`R6_DESIGN_20261011.md` lines 350–353 and 784–787: draft restart-free
catalog activation by the SYSTEM Warden through a protected pointer, free-slot
probe and atomic swap. No separate R7 implementation/runner/handoff was found.
The owner has asked for all actual R7 items; reconcile this draft with the
incoming scope. Do not silently turn every old optional batch/canary/sentinel
proposal into a prerequisite for deployment.

## Cycle-budget boundary

The user approved the matrix and requested pivot revisions. The established
pivot direction is upward, with a different underlying model, retaining that
tier as a minimum for the same coding leaf.

Current execution permits ten total quality cycles per leaf and at most three
pivots. The earlier ten-per-strategy / forty-total proposal has not been
explicitly settled. Do not silently expand existing or future budgets merely
because the model matrix is approved. Implement compatible escalation first;
isolate any changed future-workflow cycle contract as a named policy decision.
Supervisor paid-call/day/cooldown ledgers are separate and remain intact.

Tier 10 has three distinct models. A same-tier ceiling exception must use the
captured row and exclude already-tried producing model identities, while
honoring the existing permitted switch/pivot allowance. It must never fabricate
a higher tier or reset a spent ledger.

## Finish before asking the owner to sit down

1. Reconcile incoming commit, host-state handoff, mirror, manifests and receipts.
2. Complete source, configuration, migration and deployment-script revisions.
   Use the repository interpreter. Serialize heavy tests/builds and respect the
   four-process bound; no headless agent CLI launches or protected mutation.
3. Run meaningful unit/integration tests and true PowerShell 5.1 top-level
   entry-point/child-binding checks with safe fixtures. Review failures and
   critical code paths independently.
4. Prepare **one combined final runtime**, not sequential R5/R6/R7 installs.
   Pre-download and hash-pin an offline wheelhouse/package in an ordinary
   folder. The old installer uses `uv sync --no-cache`; warming a cache alone
   does not remove network work. Never blindly relocate a development venv.
5. Build/parse the candidate config, freeze the source and dependencies,
   generate manifests, refresh child pins and review cutover/recovery paths.
6. Reuse authentication and containment evidence only when its binary/profile/
   invocation/ACL bindings remain valid. Do not repeat successful sign-ins or
   signed-out discovery by default. Changed contracts require actual evidence;
   source tests cannot stand in for protected worker checks.
7. Prepare read-only post-install reports accessible to this chat without
   exposing tokens or requiring the user to paste private files.
8. Measure the planned elevated sequence and recovery bounds. Deliver one
   command and a short expected-outcome sheet only when the package is ready.

## Twenty-minute initial interaction, then unattended execution

The owner clarified the requirement after the interim handoff: **at most 1200
seconds of active input at the start**, not a total-runtime deadline. This
supersedes every earlier elapsed-time interpretation, including the interim
handoff's copied wording. Do not impose an artificial 20-minute install cutoff.

Front-load elevation, required account authorizations and all choices. Reuse
verified sign-ins; any required browser interaction must occur in this initial
phase. Pre-download/build ordinary payloads where possible. Validate remaining
prerequisites before announcing that the owner can leave.

After a durable unattended-ready checkpoint, installation, cutover, bounded
health checks, model acceptance and observation can take as long as their
documented limits require. The initial command must continue without further
owner input; status must be available in a sanitized durable report. Clearly
distinguish installation, activation and full acceptance outcomes.

Later failures must preserve artifacts and emit a precise held report, without
waiting on an invisible prompt, resetting budgets or automatically retrying
non-idempotent work. Use receipt-bound recovery and enough time for recovery
after mutation; no global timeout may kill a cutover. Reboots or required new
authorizations must be detected before the owner leaves, rather than planned
as a second sitting. Exceptional failures may still need future intervention;
do not promise otherwise or call a held run complete.

Measure the initial interaction path separately from unattended runtime.
An aggregate estimate such as "15 minutes attended" is insufficient if those
minutes are scattered across an 80-minute run. All planned input must fit in
the initial window. If fresh OAuth cannot meet it, identify that conflict
before offering the owner an executable package.

## Implementation tool path

The owner settled this scope on 12 October: **Pipeline repairs use direct local
repository work.** No connector registration or pipeline submission is needed
to maintain the pipeline. The old broadly scoped MCP instruction was disabled
in the desktop configuration (with a backup), and the owner reopened the app.
The source fix restricts MCP instructions to work explicitly submitted through
that pipeline. Keep the installed connector disabled until its revised source
is deployed. Do not direct repository work to the windows-acceptance fixture.

## Verification record and communication

This preparation fetched Git refs, read source/docs and saved owner decisions.
No runtime, task/service, credential, database, repair-budget or R: change was
made. Repository source-test claims, actual Windows acceptance, historical Linux
results and running deployment evidence must remain separately labeled.

Heartbeat: `pipeline-4-2-7-takeover-and-completion`, active every ten minutes
on this thread. Notify only on confirmed takeover, material required user input,
or a complete reviewed administrator package. Pause it when all non-admin work
and the package are delivered. The owner need not repeat the matrix decision
or manually check GitHub for the other agent's push.

