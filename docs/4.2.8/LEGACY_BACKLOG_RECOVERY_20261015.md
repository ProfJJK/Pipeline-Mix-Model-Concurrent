# Legacy backlog recovery and useful-work acceptance

The recovery tooling prepares exact work lists and immutable source evidence.
It does not delete a legacy row, submit a job, change the live controller or
claim that an imported task completed. Installation and import remain separate.

`scripts/prepare_428_backlog.py` accepts a SHA256-pinned source specification and
a new private destination. It uses the existing SQLite online-backup utility,
which includes committed WAL state without copying a changing DB/WAL/SHM trio.
Each database is consistent individually; there is no cross-database snapshot
claim. Original databases and earlier snapshots remain unchanged.

`src/cochem_pipeline/backlog_recovery_428.py` inventories the hash-verified bytes
in memory, with explicit source roles, physical-table/primary-key validation,
payload/time/row bounds, and closed-snapshot checks. The report contains exact
row identities and hashes, original attempt metadata and source references;
payload text remains in the private whole-database archive. Do not commit those
archives, generated reports or the submission ledger to Git.

The recovery plan separates:

- Exact owner-selected deletion candidates, with backup pins, individual row
  hashes and projected before/after counts. Its operation is explicitly
  `ARCHIVE_AND_REVIEW_ONLY`. There is no deletion executor in this package.
- Queue candidates with missing-input, path/stage-reconciliation or specialist
  handoff holds. Completed and undecided categories are preserved. Temporary
  fixture rows are excluded.
- Reviewed candidate requests with actual input hashes, initial deliverable
  formatting/checks, preserved history and deterministic target/stage task IDs.
  Duplicate source rows become aliases. Conflicting requests for the same
  target/stage are held rather than silently picked.

The local `SubmissionLedger` commits a reservation before the caller sends its
request. A repeated reservation cannot send again: it returns
`RECONCILIATION_REQUIRED` until the exact controller identity and receipt are
recorded. This closes the local retry loop but is not a claim of distributed
exactly-once delivery. After a timeout/crash, reconcile the deterministic task ID
with the controller; never treat a lost response as permission to POST again.
Every input digest is rechecked before reservation. Normal Chapter 06 execution,
quota, attempt and approval authority still applies.

## Verified dry-run inventory

Private review root on this host:
`C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\backlog-preparation-20261015\review-v1`.

The five readable legacy databases produced 4,086 rows across seven tables:

| Disposition | Rows |
| --- | ---: |
| Deletion review, archived and unchanged | 610 |
| Queue review | 605 |
| Preserve completed | 1,744 |
| Preserve undecided | 1,125 |
| Exclude temporary fixtures | 2 |

The 610 deletion candidates are scout audit 450, manual assembly 76, manual
compile 1, library research 7, SRS 75 and SRS generation 1. All seven library
research IDs are listed separately in the private deletion manifest.

The 605 queue candidates are CHEM103 exam jobs 219, CHEM311 evidence jobs 123,
improvement 102, research registry targets 103, quick references 30, evaluations
7 and consensus extracts 21. These are raw candidate counts, not distinct new
workflows: the improvement/registry rows require target/stage reconciliation.
Exam and YouTube ownership is preserved. The current protected live job database
was not opened, and these counts are not a live-board completeness claim.

Snapshot manifest SHA256:
`69a1b301c99f4888e040fd28a4ad2782e511f22ff698c90b38d028410493e014`.
Inventory file SHA256:
`926ffe11b97548f265f9bfcc40d05419d1ce0c545d6095408d306c2fed5a862e`.
Initial recovery-plan file SHA256:
`7cfc113712ab6dfb0b3fab374eeb6ca0808c33228b3b36013b5a37fa49bcd88d`.

## Three useful acceptance candidates prepared

Three existing quick-reference jobs now have local captured inputs and initial
JSON/Markdown deliverable contracts: `quickref_Ssulfo-2016-Salazar_0`,
`quickref_Ssulfo-2019-Chevallier_0`, and `quickref_Ssulfo-2012-Bermdez_0`.
Their original payloads named missing paths under `_Research/vdw_topics`.
Unique exact chunk basenames exist under `_Research/Topics`; those bytes were
copied into the private local review package with hashes. Original Drive files
were only read. No active worktree or generated output is in Google Drive.

The captured excerpts contain citations and an unsupported legacy relevance
claim, not full-paper evidence. The prepared tasks require that limitation to
be stated and the unsupported claim to be flagged. The current quick-reference
table does not mention the three source stems; its digest and that observation
are recorded. This is preliminary source deduplication: the controller's current
board must still be checked for existing corresponding workflow identities.

The selected requests are `READY_FOR_REVIEWED_INTAKE`, not submitted. They test
useful artifact generation after the reviewed installation; they do not by
themselves prove coding, research, approval, exam compilation or external side
effects. Before accepting completion, verify the terminal receipt, parse the
actual JSON/Markdown artifacts and independently check every declared condition.

Prepared selection file `useful-work-selection.json` SHA256:
`68790ffc1bfa2e9be6c8c520aefa983c8cd92126f54c1c9ffd5ff03b66ad3474`.
Resolved recovery-plan SHA256:
`f5b8f7b3c521ae2c0f7f9a0a8768bd0bc3cd856226603cef9b5d48f367b5163b`.
Path-remap evidence SHA256:
`3c137b2b90d893d67ca1faf784acc06da7410b6d68af55298de0779165cb9d19`.

## Verification and remaining integration

Serialized source checks: `39 passed` across
`test_backlog_recovery_428.py`, `test_legacy_snapshot.py` and
`test_legacy_history.py`. Tests cover live committed WAL in temporary databases,
changed pins, exact selectors, retained attempt history, fixture exclusions,
missing/changed inputs, output path traversal, semantic duplicates/conflicts,
specialist ownership holds, failed/duplicate receipt transitions, prepared
package hashes, and the crash-after-reservation no-resubmit behavior. These are
source/fixture checks, not installed-host acceptance.

Remaining execution work is explicit: integrate a reviewed transport using the
existing authenticated intake, reconcile live duplicates, recover missing
consensus sources, map research targets and completed stages, and consume the
exam agent's finished ownership/pilot handoff. No exam/YouTube agent settings or
files were changed. The separately approved deletion list remains preserved in
its archive until its exact transactional executor is reviewed; do not run
ad-hoc SQL against the original source databases.
