# Corrected operational release: running 4.2.8 r4 to r6

r6 replaces the spent r5 installation path. The installed r5 runtime (`865a29b`)
cannot complete the owner catalog phase on any package
([blockers](CATALOG_ACCEPTANCE_BLOCKERS_20261016.md)). r6 installs to a new root,
`C:\Program Files\CoChem\Pipeline4.2.8-windows-20261017-r6`, revision
`windows-20261017-428-v6`. r5 stays installed and spent; nothing reuses it.

## Runtime fixes (`src/cochem_pipeline`)

**The three blocking defects**
- **Probe containment.** `run_acceptance` reserves probe seats with
  `runtime.catalog.containment_id`, which `CatalogController` creates for every
  `catalog_activation` runtime. The Warden environment ID is absent in the
  one-shot phase, and the old attribute never existed.
- **Codex effort evidence.**
  - `native_effort.effort_contract` accepts reviewed Codex contracts. Each one
    binds the existing `-c model_reasoning_effort="<level>"` selector, byte for
    byte, to the exact `codex.exe` digest and its `--version` output.
  - With contracts present, the worker preflight runs the version probe and
    records `inference_policy.reasoning_effort`, as it does for Claude and Agy.
  - Native Codex events may confirm the level but never contradict it.
  - Configs without Codex contracts, such as the running r4, load and behave
    byte-identically.
- **Bootstrap routing.**
  - The r6 bootstrap routes the board-active policy `c8444fe2…`, rebuilt from
    the pinned r4 bundle.
  - The retired `gemini-3.1-pro:high` is removed from both the Agy
    `model_bindings` and `effort_contracts`.
  - `enabled_candidate`'s check therefore holds.

**Latent defects found by the 2026-10-16 review and fixed**
- **Readiness before any seat.** `require_probe_readiness` and
  `require_target_contracts` refuse before any paid probe if any of these is
  missing or wrong: bootstrap routing, seats, RAM staging, containment, an
  executable, or a target's contract against its binary binding.
- **Probe lease.** `catalog_slots.PROBE_LEASE_SECONDS = 600`, used by both
  catalog paths. The worst Codex sequence is now 210 s, against the old 180 s
  lease.
- **Cleanup classification** follows the Runtime's own dispatch contract. Only
  a failed managed close (`WorkerCleanupError`) or a RAM-clear failure leaves a
  seat unverified. Timeouts, revocation and invalid output are cleaned, failed
  probes, so the launcher can restore r4.
- **Deferred hold snapshots** are historical evidence. A target deferred on a
  live quota/busy/provider hold publishes as `AVAILABILITY_WAIT` and is never
  routable without a later native acceptance. Expiry no longer makes the
  request unpublishable.
- **Publication is all or nothing.** These steps all run inside the
  publication transaction, so any failure rolls back to `NOT_COMMITTED`:
  - writing `accepted-catalog.json`;
  - `enabled_candidate`;
  - writing the candidate `pipeline.json`;
  - the real `load_config` on the candidate;
  - the deadline check.

  The guard monitor and Docker maintenance are drained before the transaction
  opens. After COMMIT only `runtime.close()` and `result.json` remain.
- **Board baseline first.** The owner phase reads the board through a
  query-only SQLite connection, named by the pinned bootstrap bytes, before
  parsing the bootstrap or constructing the Runtime. A refused bootstrap or a
  failed construction still proves `NOT_COMMITTED` with closed resources, so
  the launcher's restore authority holds.

## Owner launcher (`scripts/run_operational_428_launch.ps1`, fresh mode)

A fresh sitting now starts from the exact running r4 with the semantics that
the hardened running-r4 recovery proved on the host.

**Holds after the fence is READY.** A hold settles the fence and judges r4
(`Test-OpPreviousRunning`):
- r4 is restored with verified health when it ended on its writer timeout;
- `NOT_REQUIRED` is reported only when r4 provably kept serving.

The 2026-10-15 fresh hold had reported `NOT_REQUIRED` and left no Warden.

**Before the r6 root is created.** These checks all run read-only:
- a bounded two-reading r4 health wait;
- if r4 reports `ALREADY_PUBLISHED`, its published policy must match the
  request's;
- the R:/Docker dependencies of the catalog runtime;
- the pinned Codex rule, skill and metadata files.

**Codex.** `config.toml` is re-captured live before the Codex plan and again
before apply, as in recovery. The r6 manifest must carry the Codex
integration.

**Identity checks.**
- The fresh manifest must be the r6 release for `c8444fe2…`.
- The packaged installer's root must equal the launcher's.
- The payload must carry a PASSED serialized source-test report for its exact
  commit (`scripts/record_source_tests_428.py`).

The spent r5 recovery path keeps its reviewed semantics and r5 constants.

## Preparation (`scripts/`)

**`prepare_operational_release_428.py --release r6`:**
- `active_routing_policy` (pinned rebuild);
- `route_active_policy`, which removes only `gemini-3.1-pro:high` and adds 15
  Codex contracts: 11 routed and 4 catalog-only;
- `read_source_test_evidence`, which needs the report beside the evidence;
- `require_committed_tree`: the working tree must equal the packaged commit.

**`prepare_task_catalog_428.py`:**
- `--expected-policy-digest` is required;
- `require_target_contracts` runs before anything is written;
- this checkout's source must be the one imported, and the packaged tree must
  be committed.

**`prepare_operational_launch_428.py`.** An r6 package must have:
- a request on `c8444fe2…` with a null previous task catalog;
- PASSED source tests;
- a Codex integration bound to the r6 root.

**`prepare_codex_integration_manifest.py --update-from-export`** writes the
scoped Codex update manifest from a committed export.

**Binding to the packaged commit (second review round):**
- `require_committed_tree` refuses:
  - working-tree differences and untracked files;
  - assume-unchanged or skip-worktree index flags;
  - ignored non-cache files.
- The evidence recorder checks the whole tree, so root `pytest.ini` and
  `conftest.py` are covered.
- The release preparer must run from, and import, the packaged checkout.
- The catalog that sizes the Codex contracts and request targets must equal
  the packaged commit's `docs/4.2.8/routing-candidate.json`.
- The Codex templates must equal the commit's.
- The fresh launcher compares the pinned request's own previous policy and
  task catalog with the reviewed values.
- The source-test evidence must cover `REQUIRED_SOURCE_TEST_MODULES`.

## Pre-existing failures found and fixed in the same release

A broad 87-module regression found four failures that predate this work: they
fail identically at `aa7706e`. They were never in the 973-test sweep, because
their modules had not changed since `c714854`.

- **Three tests in `test_acceptance_428.py` were stale.** Their fixture
  planned against the raw, unaccepted routing candidate. `a47e825` deliberately
  bound planning dispatch to accepted catalog history, so they now use the
  accepted-store fixture. Newer suites already covered the same flow.
- **`test_worker_gemini_dispatch.py` found a real, narrow regression from
  `95287db`.** The CHAPTER_DRAFT output contract required every key of the
  first declared WBS task on every model-written task, before reconciliation
  could restore the declared ones. Keys beyond `id/description/requirements`
  are now optional per item; their types are still checked. Manifests with
  only the three base keys keep the same contract hash.

## Offline proof

`pipeline_tests/test_catalog_phase_e2e_428.py` (20 tests, about 15 s) runs the
owner phase against the real stack and fakes only the provider process
launch and a fixed list of host adapters (ACL, layout, RAM disk, Docker
boundary, hardware guard).

**What runs for real:**
- `Runtime`, `JobStore`/SQLite board;
- `run_acceptance`, `NativeRunner`, preflight, receipts;
- `record_result`, `publish`;
- `enabled_candidate`, `load_config`.

**What it proves:**
- All 28 targets are accepted: 10 Claude, 15 Codex and 3 Gemini. That is 142
  launches, with exact binary, version and effort evidence for every provider.
- Replay publishes with zero launches.
- `Runtime(load_config(candidate))` reaches task planning ENABLED with
  execution materialization CONNECTED and admission 4. This is what the
  launcher's `verify_running` requires.
- **Failure scenarios:** quota deferral with expiry, invalid output, a slow
  Codex sequence past 180 s, Runtime construction failure, a refused
  bootstrap, candidate failure inside publication, and a close failure after
  COMMIT.
- **The 865a29b behaviours fail as they did on the host:** the missing
  attribute, the Codex evidence rejection, the baseline bootstrap, and the
  retained Pro binding.

These are source tests: they do not attest native sign-ins, CLI output on the
host, Docker, ImDisk or deployment.

## Build recipe (integrator, serialized under the heavy-run lock)

1. Commit everything.
2. Run `scripts/record_source_tests_428.py` for the focused modules, which
   must include `REQUIRED_SOURCE_TEST_MODULES`. It writes
   `source-test-evidence.json` and `source-tests.log`.
3. Freeze the commit:
   `scripts/prepare_428_release.py --mode freeze --commit <sha>`.
4. Build the wheel: `--mode build`.
5. Prepare the payload:
   `scripts/prepare_operational_release_428.py --release r6 …`, with the
   2026-10-15 native binary bindings (rehashed unchanged on 2026-10-16),
   `docs/4.2.8/routing-candidate.json` and the source-test evidence.
6. Prepare the request:
   `scripts/prepare_task_catalog_428.py --expected-policy-digest c8444fe2…`,
   with a fresh request ID and the reviewed 27 candidate profiles.
7. Export the Codex templates, then build the update manifest
   (`--update-from-export`, runtime root = the r6 root).
8. Prepare the launch package:
   `scripts/prepare_operational_launch_428.py --codex-integration …`.
9. Run an independent rehash and the packaged read-only plans of the launcher
   and the installer.

## Residual risks the owner run can still meet

- **A failure at or after cutover leaves neither runtime serving.** The causes
  are an r6 service that never reaches ENABLED/CONNECTED health within 1200 s,
  or a `runtime.close()` failure after COMMIT. The launcher holds and preserves
  evidence; r4 restoration after a published task catalog is not automated.
  The offline candidate-boot proof makes the first unlikely. The pre-commit
  Docker drain makes the second unlikely.
- **Codex `--version` has never run on this host as a worker identity.** A
  failure there is a pre-COMMIT hold: r4 is restored and the sitting is spent.
- **Per-slot sign-ins and native answer time are host facts.** An auth failure
  or a preflight answer slower than 60 s is a pre-COMMIT hold with r4
  restored. Paid probes already run are spent, and the request ID cannot be
  reused.
