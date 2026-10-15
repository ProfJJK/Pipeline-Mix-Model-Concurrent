# Fresh operational repair release: installed 4.2.8 r4 to r5

`scripts/prepare_operational_release_428.py` prepares a new offline bootstrap
payload for `C:\Program Files\CoChem\Pipeline4.2.8-windows-20261015-r5`, revision
`windows-20261015-428-v5`. It does not launch or install anything. The existing
R6-derived preparer and every delivered bundle remain unchanged.

The saved baseline is `C:\Users\ansac\CoChem427\r428-bundle-3dab7f2`:

| Binding | SHA-256 / revision |
| --- | --- |
| Source | `3dab7f2375121e0bdb82c13dc3b0add9d45179bb` |
| Launch manifest | `ac43248ab659e8597df38820c65c318cfeb724c7b43105ce89c39424cb277383` |
| Install manifest | `fdf93bcbec72533eca5577b2bf5fded8da11dde38e71a13b79bd58af5ca40fa3` |
| Candidate | `daaa4b6a8c15aa49ed39af48c087bfe2fcfefdcbae14520b298d46287414509a` |

These are verified saved ordinary files. The consolidated owner entry point
must separately verify the running r4 task, protected configuration/install
receipts and exact source before stopping it. Saved bundle pins alone are not
evidence of current host equality.

## Integrator workflow

1. Commit the complete source and reviewed scripts. Reuse the generic
   `freeze_from_git_428` and `build_application_wheel_428` helpers for that exact
   commit, with existing pinned offline build/backend wheels. Serialize any
   build through the host heavy-run lock.
2. Call `prepare_operational_release_428(freeze, wheelhouse, application_receipt,
   fresh_destination, repository, coding_registration={"source_roots":
   ["C:\\Users\\ansac\\source\\repos"]})`.
3. The fresh directory includes `pipeline.json`, the pinned install manifest,
   `install_operational_428_runtime.ps1`, its reviewed copy helper, and
   `operational-release.json`. Freeze these into the enclosing owner package.
   It deliberately includes no old launch command, R6 recovery, or catalog
   proposal that claims native acceptance.
4. The new installer uses the existing reviewed copy/ACL/offline-install
   operations with literal fresh r5 constants. Existing targets and partial
   roots are refused; they are never overwritten or deleted. Only the owner
   invokes its Apply phase from the consolidated entry point.
5. The installed bootstrap has `task_planning=null`, `catalog_activation=true`.
   The owner-controlled SYSTEM acceptance phase uses normal shared-slot and
   resource guards, publishes accepted catalog authority atomically, and writes
   a new protected enabled configuration only after publication. The preparer
   does not attest that this has happened or provide that owner entry point.

All worker identities, credentials, existing project definitions, private
databases, knowledge state, RAM settings, provider contracts and routing budgets
are preserved. Only knowledge source paths move to the exact fresh runtime;
an explicit reviewed coding-registration root is added without replacing the
exam/YouTube/acceptance project definitions.

## Argon contract audit

The saved r4 configuration has Flash 3.8 Low/Medium/High and historical Pro 3.1
effort contracts; it has no Argon 4 contract. The source
`argon_catalog.prepare_argon_candidate` can produce candidate bindings from a
real exact-binary/version `cochem-agy-catalog-capture/1` listing. Benchmark
ratings and source fixture acceptance specs cannot supply that evidence.
No real Argon catalog-capture JSON was found in repository source/docs evidence
during this audit. The enclosing acceptance preparation must obtain legitimate
capture evidence or keep those ranked options NOT_ACCEPTED. Partial publication
must preserve all five ranked options, genuine available route coverage and
the reviewer-family/reasoning requirements.

Verification: 29 inert release preparation/source tests passed; the real build
and installer execution test was excluded. The source tests verify tampered
payload refusal, preserved configuration, fixed fresh target, explicit local
registration, no stale launcher inclusion and preserved failure evidence.
They do not establish native or deployment acceptance.
