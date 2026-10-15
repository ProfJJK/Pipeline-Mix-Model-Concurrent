# Shared admission for controller verification

TASK_VERIFY performs artifact-integrity checks in one existing shared execution
seat. TASK_TEST captures coding_tests mode and the protected Docker policy in its
payload. It transfers a matching prepared container reservation before handoff,
counts that container and board lease once, and participates in the same FIFO,
current deployment bounds, cleanup barriers, capacity updates and orphan-reaping
attempt census as CODE_TEST. Neither kind creates a native model route.

Wrong kind/mode combinations hold before executor handoff. Without Docker,
TASK_TEST remains queued while TASK_VERIFY may use an available ordinary seat.
A full warm pool must drain before an artifact check can start; verification
does not create a fifth seat. Neither this change nor its tests starts Docker.

Integration requires the controller-kind/store changes in c968084 and the root
verification executor. Runtime startup/exception cleanup and elapsed bounds must
treat TASK_TEST like CODE_TEST; root owns those branches. Native/Docker physical
execution acceptance remains an owner-run deployment step, not this source suite.
