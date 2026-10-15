# 4.2.8 planning/execution wiring audit

Read-only source audit of baseline `c714854506c736431e6a0d5aaea2471aba8ab5ff`,
2026-10-15. This audit does not attest native host support or deployment. The
earlier implementation task list marks many tested libraries complete; those
library tests do not establish that the installed controller calls them.

## Blocking gaps

| Boundary | Source evidence | Result if planning is merely enabled |
| --- | --- | --- |
| Protected task catalog | `prepare_428_release.py:394` copies the old config and only changes runtime version/catalog activation/knowledge paths. It never sets `task_planning`. The checked-in routing candidate has `host_accepted=false`. `catalog_journal.publish_task_catalog()` has no production caller. | No protected host-accepted task catalog exists for `PlanningConfig.read_catalog()` to consume. |
| Native target admission | `routing_store.py:414` has a TASK_PLAN fallback using `PUBLISHER_OBSERVED` scores when no accepted task catalog exists. Conversely `worker.py:772` only checks the accepted task catalog when the legacy catalog schema is **not** v3; planning config requires v3. | Unaccepted profiles can pass queue admission, while newly accepted task-only targets can be rejected by the native worker. These branches need one consistent authority. |
| Physical execution | `microtask_board_428.py:298` creates `TASK_PLAN` nodes for implementation, assembly and final tests. `runtime.py:286`/`:314` enters `CodingCoordinator` only for `CODE_*`; TASK_PLAN uses the inference runner. `task_artifacts_428.compile_downstream_inputs()` and `stage_fragment_workspace()` have no production callers. | Fragment content can be returned in JSON, but it does not become a registered repository snapshot, independently executed test or integrated repository change. |
| Final test receipt | `task_release_428.py:101` defines `record_controller_test_receipt()`; production sources have no call. `verify_release_readiness()` returns `WAITING_FOR_CONTROLLER_TEST_VERIFICATION` at line 302 when no receipt exists. Tests call this port manually. | Every otherwise-finished microtask graph remains held. Never fix this by trusting the model's `passed=true`; connect an actual controller-owned test executor. |
| Quality accounting | `PlanningController.from_runtime()` constructs `TaskReleaseRuntime` at line 170, then the attempt ledger/runtime at lines 171–172. The release runtime constructs a board with no `attempt_ledger`; `MicrotaskBoardRuntime` sets both accounting fields to None. The controller only reconciles an outbox, and does not initiate pivot/dossier work. | The tested 10/20/30 lineage accounting and researched recovery are not connected to the default microtask executor. Normal board failures can hold without the intended pivot sequence. |
| Completion audits / repair | `CompletionAuditRuntime` is constructed at planning runtime line 189 but `enqueue_completion()` has no production caller. Repair verification callbacks at lines 186–187 return None. | No automatic spot-check is scheduled from a completed task; the independent repair authority is not operationally bound. Do not represent the constructor as a functioning repair system. |
| Cancellation | `PlanningController.cancel()` calls `board.snapshot()` at line 256. The board provides `board_status()`, not `snapshot()`, and exceptions are swallowed. | Cancelling the root can leave materialized microtask workflows active. |

## Existing useful foundations

The planning pump, immutable intent/route captures, cleanup-bound import, SRS
owner approval, three-channel research collector, microtask DAG, fragment path
checks, conflict descriptors, receipt-bound release gate and attempt accounting
are substantial existing libraries. They should be wired into the existing
shared Chapter 06 executor rather than replaced with a parallel worker pool.

The research runtime has production wiring: the controller enqueues requests,
`kick_research_worker()` collects bounded Internet and paper results off the
scheduler thread, and the local knowledge service supplies wiki RAG. The default
Internet adapter searches Wikipedia; it is not a general web search engine.

Simple execution verifies content digests and SRS/release-criterion coverage,
then stores deliverables in SQLite and sets the task COMPLETED. It validates
model-supplied verification statements rather than independently performing
arbitrary external work. This can support reviewed document/structured-data
generation; it cannot prove that a repository was changed, an exam compiled, a
video processed, or another system updated. Its completion evidence must state
that scope. Structured artifact publication and independent checks are needed
for the prepared useful-work acceptance requests as well.

`accept_428_native.py --mode accept` currently verifies bundle pins and prior R6
repair/replay evidence. Its result correctly leaves `full_srs_acceptance=false`.
The representative workflows and Argon targets appear in its plan output, but
that accept path does not execute those workflows or publish a task catalog.

## Minimal implementation slices

1. **Catalog authority:** a reviewed owner-side plan/probe/publication path binds
   accepted task profiles and exact binary/effort evidence. Persist and consume
   the accepted catalog using the existing atomic journal. Make routing and the
   native worker enforce the same active authority. Quota failures hold only
   unavailable routes; they cannot manufacture acceptance or lower floors.
2. **Execution adapters:** bind a task's registered project/current snapshot and
   a reviewed executor to its intended deliverable type. Reuse existing coding
   artifact application, Docker tests and Git integration for coding. Connect
   `task_artifacts_428` staging and dependency manifests with the current shared
   slots. Unsupported external work must hold before it can claim completion.
3. **Independent final verification:** generate receipts only from the actual
   artifact checker or container test execution, bound to the exact current
   assembly/final-test hashes and cleanup proof. Preserve stale/failed/partial
   receipts. Do not expose a public API that accepts model-authored test success.
4. **Recovery / cancellation / audits:** pass the same durable attempt runtime
   into the board and connect scheduler outcomes, researched dossier/pivot and
   completion events. Fix cancellation's method mismatch and propagate explicit
   cancellation failures. Bind repair callbacks to existing trusted supervisor
   authority before enabling automatic repair.
5. **Release composition:** only after the above are integrated, generate the
   protected planning config and fresh immutable owner launch package. Include
   exact task-catalog pins and actual executor capability checks. A config flag
   or passing isolated-library fixtures is insufficient release evidence.

## Required verification

- Construct `PlanningController.from_runtime()` in a fixture and drive an actual
  simple and decomposed request through registered board execution to terminal
  receipt without manually invoking the final-test receipt port.
- Verify task-only accepted routes reach the native route validator, while
  publisher-only/unaccepted routes never receive a reservation.
- Verify real source bytes and test receipts flow into assembly and release;
  wrong hashes, model-only success, stale SRS, missing tests and interrupted
  cleanup hold. Use in-process fake execution ports for source tests; actual
  SYSTEM/native/container acceptance remains owner-run.
- Trigger ten fenced quality failures through the default wired controller,
  then the researched pivot; repeat through the third boundary. Confirm quota
  waits do not spend quality counts and restarts do not reset lineage.
- Cancel a task with several materialized microtasks and show every active
  workflow receives cancellation. Verify audit enqueue and disposition from an
  actual completion event.
- Use the prepared existing quick-reference jobs for useful document acceptance,
  then an appropriate existing coding job after scope/ownership reconciliation.
  Do not treat successful document generation as proof of coding or specialist
  external workflows.
