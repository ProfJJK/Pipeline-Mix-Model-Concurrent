# Reviewed Gemini Pro retirement and deployment amendment

The owner reported Gemini Pro 3.1 removed from their Agy account, then explicitly
approved retaining the existing Claude/Codex choices at tiers 5 and 6 and backing
off when both are exhausted. The versioned [readable matrix](routing/4.2.7-routing-v4.owner-matrix.md)
and [catalog](routing/4.2.7-routing-v4.owner-catalog.json) record that decision.
No Flash substitute, inferred benchmark ranking or future selector is added.

## Immutable historical and installed state

Schema-1 catalogs and previous captures retain three candidates and their exact
digests. Schema-2 accepts two or three distinct underlying models per tier. The
new generation removes only Pro High at tiers 5 and 6; the other eight rows and
every surviving selector/effort stay identical. Existing budgets, backoff rules,
provider limits and four shared slots are retained. Retiring a model with an
explicit concurrency cap still requires a separately reviewed policy change.

R7 publishes the new generation through its existing protected authority and
transactional journal. New jobs capture it. Historical jobs keep their original
authority; current admission filters the retired target before a reservation,
and resets to their first surviving choice after backoff without spending a task
failure budget. The historical default catalog remains available for decoding.

## Exact installed R6 native acceptance amendment

The installed R6 source/configuration and earlier delivered packages remain
unchanged. Its original native acceptance plan has 27 unique selector/effort
targets and explicitly required Pro High. A fresh pinned one-shot helper applies
the owner amendment only to the exact installed manifest and candidate. It
validates the original plan digest and Pro's exact two positions, omits that one
retired target, and probes the remaining 26 through the installed production
runner. It records `OWNER_RETIRED_MODEL_NOT_PROBED`, zero retired-model jobs and
no replacement. It cannot manufacture a native acceptance result.

The phase wrapper copies the hash-bound helper into a new private protected
one-shot output root. SYSTEM identity, installed interpreter, full installed
manifest/revision, original candidate and RAM custody checks still run. The
helper changes callbacks only in that process and restores them on success or
failure. Activation requires the exact pinned helper hash, retirement decision,
original plan binding, 26 target results and absence of Pro; protocol/identity
failures still hold. An older package without this amendment still requires all
27 targets and native Pro acceptance.

R6 remains the temporary original runtime between its successful prerequisite
activation and R7 cutover; the new retirement generation becomes dispatch
authority when R7 publishes it. This amendment does not rewrite that installed
R6 configuration or claim a completed R7 deployment. The sitting waits for idle
R6 and verified cleanup before migration. If R7 holds before cutover, preserved
R6 retains its original matrix rather than pretending the new catalog was applied.

## Console recovery and owner sitting

The same fresh package includes the [reproduced console repair](R6_CONSOLE_RECOVERY_2026-10-12.md).
The previous attempt held before an Agy URL or prompt, not because the owner
missed one. The reviewed previous-state guard binds the exact 18 authentication
decisions, explicit Agy sign-out stream hashes, terminal private task and R4 v4
restore receipt. Existing Codex/Claude sessions are reused. The owner must perform
any requested six Agy browser authorizations inside the initial 20-minute window.
No planned late input, restart or continuation is requested. A missed/expired
window holds with preserved evidence and restores the reviewed prior runtime
where safely proven; it does not prompt later or automatically retry.

Source fixtures are ordinary Windows/Python 3.12 and inert PowerShell, not actual
SYSTEM/OAuth/model acceptance. Packaging and final source-test evidence are
recorded in `R7_LAUNCH_READY_2026-10-12.md` after the fresh package is prepared.
