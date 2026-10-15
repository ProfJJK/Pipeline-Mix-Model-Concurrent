# Owner Amendment 2026-10-14 — Warden CPU Budget (S427-HOST-006 / S427-PERF-005)

**Decision (owner, 2026-10-14):** the Warden's own CPU admission budget is
**7%** of its allowed logical CPUs, measured over a **rolling 10-second window**
(`controller_guard.WARDEN_CPU_LIMIT_PERCENT = 7`, `CPU_WINDOW_SECONDS = 10.0`).
The 200 MiB memory budget (owner amendment 2026-10-11) is unchanged.

## Evidence

- Sitting `R428Sitting-windows-20261014-b36dc44751d84713b273f5a3aaac459b` held at
  `catalog_publication` (00:43:30Z). The live 4.2.8 controller (PID 10476,
  `Pipeline4.2.8-windows-20261014-r3`) reported, through its read-only operator
  view, `capacity=0 state=paused` with the reason
  `Warden CPU utilization exceeds its strict 5% budget`. Host CPU was 5.9%,
  commit 35 GB free, 45 °C, and no disk or memory reasons were present.
- Idle controller CPU measured 3.9%–6% when each sample covered only the ~1 s
  since the previous tick. One bounded in-process operation (hashing the 235 MB
  `claude.exe` before a probe, or serializing a 648 KB operator view) exceeded
  5% for that sample and set admission capacity to 0.
- The catalog probe heartbeat treated capacity 0 as revocation, so the first
  native control probe stopped itself and the catalog became `HELD` with no
  automatic retry.

## Change set (source commit recorded in `RELEASE_REVIEW.md`)

1. `catalog_runtime._probe_lease_valid`: an admitted probe is revoked only by
   shutdown, the governor's critical `terminate_active`, or a cleaned/expired
   reservation — the same rule ordinary jobs already follow. A pause only blocks
   new work.
2. `native_effort.verified_executable_sha256`: provider binaries are hashed once
   per physical file identity (path, size, mtime, creation time, file index,
   volume) and pre-verified at controller startup, before admission opens.
   Any change to the file causes a fresh hash; every dispatch still runs the
   native version probe.
3. `controller_guard.CpuWindow`: the budget verdict uses a rolling 10 s window;
   sustained load (for example 10%) still pauses admission.
4. `run_428_launch.ps1`: cutover proves identity; catalog publication tolerates
   transient admission pauses and HTTP failures until its 30-minute deadline but
   holds on any controller restart or catalog `HELD`.
5. Recovery sitting: the live 4.2.8 `-r3` runtime is a recognized baseline. A
   fresh `-r4` runtime is installed, no migration or database rollback runs, and
   only the protected catalog pointer is replaced with a fresh reviewed request
   ID (the previous pointer is preserved byte-for-byte in the sitting directory
   and restored on any pre-start failure).

## Outstanding

The hashed specification texts (`src/cochem_pipeline/specification/4.2.7_SRS.md`,
`requirements_4.2.7.json`, `acceptance_4.2.7.json`, and the knowledge corpus
copies) still state `200 MiB/5%`. They are bound into the canonical authority
digest and the ratified knowledge manifest; editing them without re-ratifying
that manifest would hold knowledge readiness and pause admission. Re-ratify
them together in a reviewed specification revision.
