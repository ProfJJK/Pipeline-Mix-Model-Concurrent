# Admission repair source evidence — 2026-10-15

Implements the CPU/admission portion of the owner operational amendment. The
controller now compares CPU seconds per elapsed second with one core, over its
existing rolling ten-second window. The measured affinity denominator is required
for percentage records; eight processors display a 12.5% limit. A half-core target
is reported without becoming another gate. The 200 MiB memory limit is unchanged.

Host CPU remains host-wide telemetry. The sample now labels both the host CPU
denominator and the process-affinity count used to constrain worker capacity. No
controller/pool percentage is subtracted from host CPU.

Brief CPU or disk throughput/IOPS pressure closes new admission and remembers the
previously established capacity. The first healthy sample restores that capacity.
Startup and further capacity increases still use the existing gradual recovery.
Memory, commit, thermal, missing required telemetry and sustained-critical trips
discard fast recovery; emergency termination remains intact. Every reduced raw
capacity now has an explanatory reason. A simultaneous protective limit remains
conservative and uses the original recovery window.

## Verification

All runs used Python 3.12 and `scripts/run_source_tests_428.py`, which serialized
execution through the shared host lock and verified imports from this worktree.

- Controller plus new inert policy tests: 86 passed, 1 unsupported-host test
  skipped, 2 native/child-launch tests deliberately deselected.
- Existing pure hardware-policy selection: 63 passed, 25 host-probe cases
  deliberately deselected.
- Rolling CPU window selection: 5 passed, 10 unrelated cases deselected.
- Final new-policy file after adding runtime-boundary checks: 53 passed. This
  overlaps the first run; counts are not additive unique-test totals.

Runtime-boundary fixtures verify CPU/disk pauses leave existing jobs and their
cancellation flags untouched, while critical memory still fails and terminates
the affected work. These are source tests, not deployed host acceptance.

The sustained observer also uses `CpuWindow` and `assess_controller`, records the
actual affinity, rolling duration and core equivalents, and reports the same
one-core limit. Its 34 disposable clock/process/receipt tests passed, including
unchanged continuity, PID-reuse, missing-heap, and sample-gap safeguards. A burst
test verifies the observer uses the ten-second window, not a one-tick reading.

The installed runtime and all delivered packages remain unchanged. These source
tests do not establish new physical SYSTEM or 48-hour acceptance evidence.
