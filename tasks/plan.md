# 4.2.8 remaining implementation plan

Canonical task list: [tasks/todo.md](todo.md). Entry handoff:
[PIPELINE_4.2.8_AGENT_HANDOFF.md](../PIPELINE_4.2.8_AGENT_HANDOFF.md).
Implementation baseline: c33c7ea2a9d7c655b6998081080b4eae2273ee1b.
The owner delegates completion to a Gemini 4 source-engineering swarm and will
launch only after 4.2.8 is ready. This plan does not authorize host deployment.

## Architecture and integration boundaries

Keep existing Chapter 06 leases, actual native runner, four shared slots, RAM
identity, cleanup proof and immutable policy captures as execution authority.
New planning and repair libraries are not replacement worker pools.

| Boundary | Existing implementation | Contract to finish |
| --- | --- | --- |
| Intake | `service.py`, `planning_runtime.py` | MCP/CLI reaches 4.2.8; objective/project only, no caller-selected authority |
| Planning | `planning_journal.py`, `planning_gateway.py`, `workflow_428.py` | Versioned SRS and independently verified research/review/owner decisions |
| Research | `knowledge.py`, `planning_governance.py` provide reusable pieces | Real three-channel collection; persist actual bounded content and attach it to prompts |
| Approval | `apply_owner_approval()` is a trusted port only | Human interaction bound to exact document/version, distinct from shared agent bearer token |
| Materialization | `JobStore`, `CodingCoordinator`, existing artifact capture | Idempotent graph creation; exact predecessor artifacts; no READY-as-completion shortcut |
| Routing | `task_routing.py`, `routing_store.py`, `catalog_*` | Eligibility is intersection of capability, active catalog, exact native acceptance and live capacity |
| Failure | `AttemptLedger` plus existing routing failure counters | One fenced outcome, correct lineage, no double charging or budget reset |
| Audits/repair | `repair_queue_428.py`, existing supervisor modules | Actual independent audit and isolated direct repair, using trustworthy cross-process arbitration |
| Launch | R6/R7 source builders/launchers | Fresh 4.2.8 source/bundle/manifest and one owner sitting against actual host evidence |

Coordinator publishes explicit schemas before parallel consumers: research
request/receipt/content, approval request/decision/revision, task execution node,
artifact manifest, attempt outcome/dossier, repair reservation/result and release
manifest. For each specify size bounds, origin/trust, identity, idempotency key,
durability, cleanup requirement, errors/retries and backward compatibility.
Use canonical JSON/digests and transactions/outbox reconciliation; no cross-DB
"best effort" double writes that can silently admit a duplicate execution.

## Lanes and waves

| Lane | Tasks | Responsibility |
| --- | --- | --- |
| C — coordinator | 00, 01, 23, 24, 27 | Worktree tests, interfaces, shared-file hooks, integrated regression and review |
| R — routing | 02, 03 | Evidence gaps, five choices, protected catalog and live admission |
| N — native compatibility | 04, 05 | Argon contracts, R6 replay/compatibility preparation |
| Q — research | 06, 07, 08 | Evidence storage, internet/papers/wiki, prompt hydration |
| H — human interface | 09, 10 | Revision-bound approval; useful MCP/CLI/status views |
| E — execution | 11, 12, 13, 14 | Simple tasks, microtask graph, coding artifacts, assembly/final release |
| F — failure recovery | 15, 16, 17, 18 | Outcome ledger, dossiers, pivot/fracture, locked-task decisions |
| A — completion audit | 19 | Evidence-based spot checking and incident reporting |
| O — independent repair | 20, 21 | Separate supervisor, quota/slot ownership, direct repository repair |
| D — delivery | 22, 25, 26 | 4.2.8 migration/version, offline freeze, consolidated launch |
| Owner | 28 | Final elevated physical acceptance after source/package readiness |

Numbers above mean P428-NN. Start with 00/01. Then parallel independent lanes
R, N, Q, H and E only as capacity allows. F follows execution/outcome contracts;
A and O follow artifact/incident contracts. D can inspect old package structure
early but must freeze only after integrated commits/tests are complete.
Dependencies in todo.md are authoritative; do not infer readiness from a wave.

## Owner requirement coverage

| Requested behavior | Work items |
| --- | --- |
| Audited task-type/tier routing, five comparisons and explicit cost evidence | 02, 03 |
| Agy Gemini 4 Argon Low/Medium/High with exact native support | 04, 24, 28 |
| Automatic plan/architecture/SRS, research, different-model review and high-tier approval | 06–10, 23 |
| WBS with requirement-linked deliverables, audit metrics and release criteria | 12–14 |
| Individually classified microtasks, parallel fragments, assembly and final testing | 11–14, 23 |
| Ten-failure research/pivot/fracture and thirty-failure lock with owner options | 15–18 |
| Completion spot checks and independent tier-10 pipeline repair | 19–21 |
| Carry the R6 repairs forward; prepare one new 4.2.8 installation/launch | 05, 22, 24–28 |

On AETHERDESK, use at most four heavy activities total and one test/build holder.
The owner authorizes source parallelism; this does not authorize agent-created
native CLI swarms or lifecycle actions. Use independent hosts for more lanes.
The integrator reserves shared-file edits, merges one dependency chain at a time,
and records exact commits in the checklist. No simultaneous schema migrations.

## Specific integration problems to resolve

- `server.py` currently exposes the old `pipeline_submit`/`pipeline_code` paths;
  the new HTTP intake alone does not make normal clients use the new planner.
- Research currently carries source IDs/digests. Plans need the actual bounded,
  verified source content; a hash is not research context. Search outages cannot
  become `no_results`. The scheduler/health path must not wait on network calls.
- The shared controller bearer token is available to agents. Adding an approve
  endpoint protected only by that token would let a model impersonate the owner.
- The current routing admission rejects targets absent from its active catalog;
  the research matrix is not that catalog. `validate_gemini_route_bindings()` also
  rejects bindings not represented by active routes. Do not bypass either check.
- R7 source already has publication and shared-slot probe integration. Reuse and
  extend it rather than rebuilding from historical "not implemented" paragraphs.
- `AttemptLedger.start()` accepts a model identifier but does not itself validate
  the actual claimed complexity/profile. Bind it to scheduler evidence. Its one
  active attempt per lineage must not serialize all independent WBS children.
- Ordinary WBS microtasks are separate tasks with individual failure budgets;
  fracture descendants share the failed task's budget. Record both relationships.
  A fracture must permit useful lower-complexity fragments without quietly undoing
  the higher/different-model pivot requirement for the failed scope and assembly.
- Callback ports and booleans such as `host_accepted` are not evidence producers.
  Production adapters must verify genuine receipts before publishing those values.
- A repair commit alone does not heal an installed runtime. Define the complete
  tested repair-to-runtime transition within the owner's reviewed supervisor
  authority. Where that authority is absent, report an installation hold instead
  of bypassing protected state or claiming automatic repair succeeded.
- The root wheel/version still says 4.2.7. Version new source/artifacts coherently;
  do not globally rewrite old capture versions, canonical evidence or protected roots.

## Evidence and policy gaps

`docs/4.2.8/AUDIT.md` records complete observed breakdowns for 34/37 profiles,
missing Flash Low and Argon Low/Medium scores, one SCI-FORMAL tier-10 execution
gap, and 20 producer/reviewer gaps. Five displayed options do not imply five
eligible execution targets. Comparison cost is an evaluation proxy, not the
owner's subscription charge or remaining quota.

P428-02 must produce an explicit corrected routing proposal and exact unresolved
decisions, with source evidence and impact. Do not fabricate scores, conflate
DefaultFallback benchmark configurations with pinned native models, or silently
waive a floor to get green tests. If owner policy approval is necessary, present
the concrete delta before the launch sitting; do not repeat settled questions.

Likewise, configure real research access during preparation. Do not assume this
chat's web/Consensus tools are automatically available to the SYSTEM runtime.
Choose a supported search interface, document terms/configuration, keep credentials
private, and arrange any indispensable setup before unattended execution.

## Verification and the current harness trap

Use Python 3.12. On this host:
`C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\.venv\Scripts\python.exe`.
The current external `run_r6_source_tests.py` hardcodes the **-r6 checkout**.
Do not invoke it in another worktree and assume that worktree was tested.
P428-00 must produce a repository-local runner that prints/verifies the actual
checkout/commit and imports that checkout under isolated Python.

All local builds/tests must share
`C:\Users\ansac\CoChem427\heavy-run.lock`, using the reviewed serializer in
`docs/deployment/windows-deployment-next/serialize-heavy.py` as the starting point.
That serializer's timeout is **lock acquisition**, not child execution time;
the new runner also needs a bounded command timeout and owned-child cleanup.
No `pytest -n`; do not weaken or bypass the existing lock. Never kill by image/tree.

Previous source regression selection (472 tests before one additional test):

```text
pipeline_tests/test_planning_runtime_428.py
pipeline_tests/test_planning_gateway_428.py
pipeline_tests/test_planning_journal_428.py
pipeline_tests/test_workflow_428.py
pipeline_tests/test_task_routing_428.py
pipeline_tests/test_argon_catalog.py
pipeline_tests/test_repair_queue_428.py
pipeline_tests/test_routing_policy.py
pipeline_tests/test_routing_v3.py
pipeline_tests/test_routing_store.py
pipeline_tests/test_runtime_routing.py
pipeline_tests/test_config.py
-k "not real_process_cleanup" --tb=short
```

Separate selection: `pipeline_tests/test_service.py -k "not coding" --tb=short`
(54 passed). The added runtime maintenance test is in the planning-runtime file.
These are source/in-process fixtures. Keep real native/child/host tests excluded
unless their individual implementation is reviewed and they are explicitly in the
owner-run package. Do not assume names like `real` imply unsafe or safe: read them.

Every task below defines an outcome test. New test/module filenames are proposals,
not assertions they already exist. Gate each merged slice with focused tests, then
run integrated regression once new behavior warrants it. Record skips accurately.
Preserve CRLF/mixed endings in existing modules; avoid whole-file normalization.
For whitespace review use:
`git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`.

## Review checkpoints

1. After 00–05: real checkout tests, stable interfaces, evidence gaps explicit,
   route/native/retirement behavior defined; no new selector falsely activated.
2. After 06–14: simple task and researched/approved/decomposed task reach validated
   artifacts in controller fixtures, through the real APIs and board transitions.
3. After 15–21: availability, 10/20/30 failures, fracture, audit and independent
   repair paths recover across restart with four-slot accounting intact.
4. After 22–27: version/migrations, source regressions, immutable build and actual
   packaged read-only plan verified; one initial-input owner sitting reviewed.
5. After owner task 28: inspect real sanitized receipts; declare running/admitting/
   accepted only to the extent established by actual evidence.

Keep preparation, owner-run acceptance and deployment status separate. The final
handoff must include source commit, tests, wheel/bundle/manifest pins, known holds,
rollback boundary, readable status location, and one command. Never ask the owner
to launch old R6 as a separate preliminary experiment. A pre-cutover failure should
leave the previous runtime intact; a post-cutover failure uses the reviewed recovery
path, preserving all evidence without a late interactive prompt.
