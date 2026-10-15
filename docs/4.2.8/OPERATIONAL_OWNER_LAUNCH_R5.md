# Fresh operational r5 owner launch

This is source preparation for one owner-run launch. It does not attest Windows
deployment, current quota, provider support, or useful-job completion. Existing
r4/runtime bundles and all R6 recovery packages remain unchanged.

`prepare_operational_release_428.py` produces the offline r5 payload.
`prepare_task_catalog_428.py` produces its exact-source acceptance request.
`prepare_operational_launch_428.py` binds both into a fresh directory, including
the committed `run_operational_428_launch.ps1`, fixed reviewed helper bytes, and
optionally the exact-source scoped Codex integration manifest. A different source,
bootstrap, previous r4 pin, input file, or integration identity is rejected.
An integrator must independently review and pin the resulting launch manifest.

The default PowerShell command verifies an offline read-only plan. Only the
owner's explicit `-Apply` reaches these stages:

1. Verify the pinned current 4.2.8 r4 configuration/install manifest, protected
   code/interpreter, exact Warden task ACL/action/invariants and SYSTEM health.
2. Install the fresh r5 payload offline while the old runtime continues running.
   Executed installer scripts are staged under the protected sitting first.
   Verify the Codex integration's current target hashes and transformations
   without writing them, so existing configuration drift is found before stop.
3. Run a bounded SYSTEM admission fence against the exact configured board.
   `BEGIN IMMEDIATE` prevents a competing claim between the idle check and stop.
   Active leaves, leases, route reservations, uncleared containment, and catalog
   probes must be absent. Pending jobs and unclaimed workflow roots are allowed.
   The fence changes no logical database rows or schema. A nonce-bound READY
   receipt expires after 240 seconds; a matching release file releases the lock.
4. Retain native identities and health before acquiring the fence, then recheck
   the exact task and fence without requesting HTTP health while writers are
   blocked. The old runtime's five-second writer timeout can make health wait or
   end its exact task; an ended task is accepted only with unchanged last-run
   identity and exit of both retained native processes after this fence's READY
   timestamp. An earlier or uncertain exit holds. Disable its logon trigger,
   stop that exact Warden, verify process/port exit, then verify fence release.
5. Run the protected catalog acceptance module once through the fresh runtime,
   preserving shared seats, all resource guards, actual native receipts, quota
   holds, and cleanup. No ordinary jobs or sign-in prompts run in this phase.
6. After a bound successful terminal receipt and native exit, retarget the Warden
   to the final protected configuration written by acceptance. The installed
   bootstrap configuration is deliberately not the daemon's final configuration.
   Verify SYSTEM source identity, task instance, planning execution connectivity,
   and nonzero guarded admission before restoring the original logon trigger.
7. If included, apply only the scoped Codex integration update as the owner.
   Recheck its prior-byte pins to preserve edits made since preflight. A failure keeps the new
   runtime and reports the integration hold; a fresh Codex session is required.

All input is front-loaded at UAC. The script contains no planned authentication,
prompt, restart, or continuation command. The catalog phase can run up to two
hours; the idle drain can wait thirty minutes. These are unattended bounds, not
a promise about runtime or provider availability.

Fresh status files under the protected sitting are readable and sanitized.
Original task XML, full baseline evidence, child outputs, and final phase files
are in its private child directory. No task, old capture, database, or partial
package is deleted. A failed launch is spent and is never retried automatically.

Restoration is conservative. Before acceptance, a verified stopped old runtime
can be restored. After acceptance starts, restoration requires a terminal
`NOT_COMMITTED` receipt, resource closure, catalog-probe cleanup, a fresh writer
fence, unchanged catalog pointers, and exact old task/configuration checks.
Missing receipts, uncertain native exit, committed publication, or any attempted
cutover preserve a stopped/running hold for review. There is no database rollback.

The fixture tests use temporary SQLite boards and inert PowerShell function ports.
They check that claims block during the fence, expired unreconciled leases block
stopping, pending backlog survives, queued tasks are not mistaken for completion,
empty JSON quarantine objects are idle, and post-publication failures never
restart the old runtime. Host ACL/process/task/provider acceptance remains for
the reviewed owner launch.
