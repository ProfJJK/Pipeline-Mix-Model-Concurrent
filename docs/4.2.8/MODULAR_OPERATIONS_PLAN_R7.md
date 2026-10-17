# r7: modular operations plan (2026-10-17)

Owner decision: modularize first. One thin elevated switch tomorrow morning;
everything else runs inside the live pipeline or in user space, so fixes,
upgrades and model changes no longer need an Administrator sitting.

This is the implementation plan for the next session (Opus). Facts here were
read from the code at `7d34b12`; file:line references are to that commit.

## 1. Why nine sittings held

| Sitting | Held on | Root cause class |
| --- | --- | --- |
| 865a29b | Fence task could not be released; r4 ended | Launcher vs Task Scheduler |
| 01f782a | Codex/Claude MCP bridges counted as foreign processes | Launcher check too strict |
| 4eabf2e | Held observer process not recognized | Launcher check too strict |
| 490bf2e | Wrong ACL rule for the observer task | Launcher check too strict |
| 90c9c1d | Recycled PID looked like a leftover fence | Launcher pinned to a moment |
| 7a5e785 | Reboot restarted r4; package expected it stopped | Package pinned to a moment |
| ab900e9 | Launcher read its own task through a stale COM object | Launcher vs Task Scheduler |
| d5d6094 | Request prepared for the baseline policy, not the board's | Package pinned to a moment |
| a55f55f | One model (Haiku high) failed one probe; all 28 held | All-or-nothing acceptance |

None was the pipeline failing to do its job. Every one came from running
install, stop, 28 live model probes, cutover and client setup as **one
elevated, one-shot, non-resumable transaction** whose checks compared the host
against snapshots. That structure is what changes.

## 2. Principle: elevation for authority, never for execution

On this host the UAC prompt is the only thing that separates the owner at the
keyboard from agents running as the owner's account. So:

- **Elevated, and stays elevated (seconds, not sittings):**
  1. Switching the `CoChem-4.2.7-Warden` SYSTEM task to a new code root and
     starting it (workers need `LogonUserW`/`CreateProcessAsUserW`,
     `windows.py:312,1038`; the service must be SYSTEM).
  2. Writing code or native CLIs under `C:\Program Files\CoChem` (workers may
     only execute ACL-protected code, `validate_code_path`).
  3. Granting authority the SYSTEM service will act on (a task-catalog
     request, a routing proposal, a native-binding approval): one copy of a
     reviewed file into a protected inbox.
- **Never elevated (in-service or user space):** model acceptance probes,
  excluding or re-probing a model, enabling task planning, Codex/Claude client
  setup, diagnostics, progress and all day-to-day operation.

Precedent already in the code: r4 published its own routing catalog
**in-service** on 2026-10-14. `CatalogController` (`catalog_runtime.py`) polls
the protected pointer `C:\Program Files\CoChem\RoutingCatalog4.2.8` every 30 s,
probes one target at a time through the shared seats
(`runtime.tick` → `catalog.step`, `runtime.py:557-560`), and publishes. The
task catalog gets the same treatment.

## 3. Target architecture

### M1. Thin switch (elevated, rerunnable, self-rolling-back)

`scripts/switch_428_runtime.ps1`, extracted from the proven parts of
`run_operational_428_launch.ps1` (the preconditions, `Start-OpFence`,
`Stop-OpRetainedTask`, `Release-OpFence`, `Restore-OpPrevious`, `Wait-OpHealth`,
one-shot identity, and the installer call ran correctly on the host tonight).

Phases: `preconditions → install_or_reuse → fence → stop_previous →
release_fence → repoint → start → verify_health`. That is all.
- No catalog phase, no Codex step, no candidate config rewrite.
- `install_or_reuse`: an existing root that verifies against the install
  manifest (`install-after.json`, tree check, interpreter pin) is reused. A
  root is never "spent".
- Health verification is the r4 health contract (`Assert-428Health` with
  planning not required): the new runtime starts in exactly the mode r4 runs
  in today (`catalog_activation=true`, no `task_planning`).
- **Automatic rollback**: if the new runtime does not verify within its bound,
  the script repoints the task to the previous root, starts it, and verifies
  (`Restore-OpPrevious` semantics, host-proven twice).
- Idempotent: pasting the same command again after a hold is always safe.
  Nothing is pinned to PIDs, task XML snapshots, Codex file hashes or the
  board's policy; only the security invariants stay (SYSTEM principal,
  logon type, run level, SDDL, protected ACLs).

### M2. In-service task-catalog acceptance

New `TaskCatalogController` (module `task_catalog_runtime_428.py`), modelled on
`CatalogController` and stepped from `runtime.tick` next to it.
- Reads a protected request from the runtime root's authority inbox
  (`<root>\authority\task-catalog\current-request.json` + pinned request file),
  installed with the payload, so the morning switch needs no extra step.
- Uses the pieces that exist today: `require_probe_readiness`,
  `probe_authority`, `probe_node`, `record_result`, `record_failure`,
  `defer_held_target`, `publish`, `probe_outcomes`, `outcome_summary`
  (`task_catalog_acceptance_428.py`). One target per step, reserved through
  `admission.reserve_catalog` with `catalog_slots.PROBE_LEASE_SECONDS`,
  executed on the runtime pool like `CatalogController._execute`.
- Per-target exclusion (`7d34b12`) applies. Excluded and deferred targets are
  re-probed on a backoff schedule (first after 1 h, then 6 h, then daily)
  under a fresh request generation, so a flaky model heals itself.
- Publishes when every target is resolved. Progress, per-target status and
  typed failure facts appear in `/health` → `task_catalog_acceptance`
  (readable through the `pipeline_health` MCP tool, no elevation).

### M3. Dynamic task-planning enablement

`Runtime` derives task planning from the board instead of a static config:
- each tick, if `catalog_journal.active_task_catalog` is present and no
  planning stack exists, build it (`initialize_task_catalog_authority`,
  `TaskArtifactRuntime`, `TaskArtifactDeliveryRuntime`,
  `PlanningController.from_runtime`), exactly what `runtime.py:120-214` does at
  construction today;
- `config.task_planning` becomes an optional override (its only runtime input
  is `flash_context_limit`; default it);
- health reports `task_planning` ENABLED/CONNECTED without a restart;
- if the active catalog is superseded, the stack is rebuilt from the new one.

`enabled_candidate` and the candidate `pipeline.json` rewrite are no longer on
the path; the configuration never changes after the switch.

### M4. Authority inbox (one elevated copy per authority change)

`<root>\authority\` (Administrators write, SYSTEM read) with one subfolder per
authority kind: `task-catalog`, `routing` (today's `RoutingCatalog4.2.8`
pointer moves here in a later release; r7 keeps reading the existing path),
`native-bindings`. A tiny `scripts/approve_428.ps1` copies one reviewed file
into the inbox, verifies its hash, and exits: a UAC prompt and a few seconds.
The service validates the file, executes with retries, and reports.

### M5. Native CLI refresh (Claude/Codex/Agy update every few days)

Provider contracts pin `executable_sha256` and `--version` output
(`native_effort.py`). A CLI update therefore invalidates contracts. The
modular path:
1. elevated copy of the new CLI into a new protected `Native…` folder;
2. user-space `scripts/prepare_native_bindings_428.py` rehashes, captures
   `--version`, regenerates the Codex/Claude/Agy contracts (the functions
   already exist: `route_active_policy`, `codex_effort_contracts`) and writes
   a reviewed proposal;
3. one `approve_428.ps1` drop; the service re-accepts the affected targets
   in-service (M2) and publishes a new generation.

For r7 only steps 2 and 3's file formats are specified; the in-service
binding switch is the first post-launch module (needs no sitting: M1 is cheap).

### M6. Client integration in user space

`scripts/integrate_clients_428.py` (no elevation): resolves the running
runtime root from `/health` → `source_root`, then verifies/applies/rolls back
the Codex MCP table, the managed `AGENTS.md` section, the skill and metadata
(`codex_integration_428.py` already does the patching), and the Claude
Desktop/Code MCP entries. Idempotent; run after any switch.

### M7. Built-in diagnostics

The per-target outcome record (`7d34b12`) and the service's
`task_catalog_acceptance` health block replace separate elevated diagnostic
scripts: category, exit code, envelope kind and API status per probe, never
raw text. `inspect_catalog_probes_428.ps1` stays for archaeology only.

### M8. Upgrades

A code release is a bundle plus one M1 switch (10–20 min, self-rolling-back).
The previous root stays installed, so "roll back" is the same switch pointed
at it. Everything else in a release (catalog, contracts, client configs,
knowledge) flows through M2–M6 without a sitting.

## 4. Tomorrow morning

One paste in Administrator Windows PowerShell:

```
switch_428_runtime.ps1 -LaunchManifest ... -LaunchManifestSha256 ... -Apply
```

Expected: 10–20 minutes. Install (5 min, proven), fence and stop (seconds,
proven), start and health (up to the 900 s Docker wait). Result
`R428_SWITCH_VERIFIED`, or an automatic rollback to r4 with
`R428_SWITCH_ROLLED_BACK` and the typed cause. Either way r4 or r7 is serving
when it ends; the same command can be pasted again after a fix.

Then, with no further elevation:
- the service runs the 28 probes in the background (progress in
  `pipeline_health`), excludes what fails, publishes, and enables planning;
- I run `integrate_clients_428.py` (or you do; it is a normal command);
- I submit the three approved jobs through MCP and verify their artifacts.

## 5. Work packages for the implementing session

Order matters; each package has tests and a reviewer pass. Reuse the
real-Runtime harness (`pipeline_tests/catalog_e2e_428/`) for every proof.

| WP | Scope | Files | Done when |
| --- | --- | --- | --- |
| 0 | Baseline | — | HEAD `7d34b12`, tree clean, job-flow e2e module landed (see §6) |
| 1 | M2 TaskCatalogController | new `src/cochem_pipeline/task_catalog_runtime_428.py`; `runtime.py` (construct, step in `tick`, health block, close); `catalog_authority.py`-style inbox reader for `<root>\authority\task-catalog` | e2e: service boots in r4 mode, ticks drive all 28 targets, one injected failure is excluded, publication happens in-service; replay is a no-op; health shows progress |
| 2 | M3 dynamic enablement | `runtime.py`, `planning_runtime.py` (config optional), health | e2e: after in-service publication, further ticks construct planning; health ENABLED/CONNECTED; a coding job and a file task complete (job-flow module) |
| 3 | M1 switch script | new `scripts/switch_428_runtime.ps1` (extract from the launcher, do not rewrite proven functions); `install_operational_428_runtime.ps1` reuse-verified-root option; `prepare_operational_launch_428.py` packages the inbox + switch | inert PS tests: phase order, hold at each phase → previous keeps running or is restored, failed health → rollback, rerun after hold is a no-op install; installer read-only plan on an existing verified root |
| 4 | M4 inbox in payload | `prepare_operational_release_428.py` adds `authority/task-catalog/*` rows; `approve_428.ps1` | package tests; inbox pinned in install manifest |
| 5 | M6 client integration | new `scripts/integrate_clients_428.py` (+ Claude MCP entries) | user-space tests; verify/apply/rollback; idempotent |
| 6 | M7 health diagnostics | `runtime.py` health, `operator_views.py` | per-target typed facts in health, redaction tests |
| 7 | Reviews + regression | — | lens review + adversarial verification; broad regression green; focused evidence recorded |
| 8 | Package + owner sheet | build chain as for a55f55f; `RETURN_SETUP_428_SWITCH_R7_<sha>.txt` | read-only plans, independent package review, one command |

Time boxes for a 9-hour session: WP1–2 ≈ 2.5 h, WP3–4 ≈ 2 h, WP5–6 ≈ 1 h,
WP7 ≈ 1.5 h, WP8 ≈ 1 h, buffer 1 h. If time runs short, WP5 and WP6 are
post-launch modules (they need no sitting); WP1–4 and WP7–8 are not optional.

Constraints that stay: repository Python 3.12, serialized tests only, no host
lifecycle or provider launches from agents, no JobStore migrations, r4's
config must still load in the fence one-shots, every publication needs exact
evidence or a typed exclusion.

## 6. Proof strategy

- **Real-Runtime offline e2e** (existing harness): extend
  `test_catalog_phase_e2e_428.py` with the in-service path (WP1–2) and keep the
  owner-phase tests as a regression of the shared functions.
- **Job flows**: `pipeline_tests/test_r6_job_flows_e2e_428.py` (in progress
  tonight) must prove on the r7 configuration that a coding job edits a
  registered repository and a task delivers generated files. Any defect it
  finds is fixed before packaging: the launched pipeline must do real work.
- **Switch script**: inert PowerShell tests per phase and hold, plus the
  packaged read-only plan.
- **Reviews**: a lens review with adversarial verification over the whole
  change, and an independent package review of the built bundle.

Source and package checks are not deployment acceptance. New on the host
tomorrow: the r7 service process itself (constructor path host-proven on
10-16; daemon loop is r4's code) and the 28 live probes (now in-service and
non-blocking).

## 7. Honest limits

- The UAC prompt stays for the switch and for authority drops. There is no
  secure way around it that keeps agents from granting themselves authority.
- The Haiku-high failure cause is still unknown; r7 excludes it, reports its
  typed facts in health, and re-probes it later.
- M5's in-service binding switch and the routing inbox move are the first
  post-launch modules, not part of tomorrow's switch.
