# R6 Codex startup on the RAM workspace — 13 October

The received v2 diagnostic identifies target-02: Codex `gpt-6-luna`, Medium,
slot3. Target-00 (Agy Flash Low) and target-01 (Claude Haiku Medium) passed.
All 18 sessions, knowledge and custody passed before the native hold. R4 v10
was restored with health verified, but admission capacity was zero. R6 has not
activated. The spent `r6-launch-d6d336e` package must remain unchanged.

## Cause and evidence

The failed command emitted no stdout and exactly 40 stderr bytes. Its digest
matches the public Windows error `Error: Incorrect function. (os error 1)`
with a trailing LF:
`bf3b7cabd780d9bb2724f0fb4ba1bc0e72f016a6d5cffb6896ba2fceed61433c`.
This was identified by hashing standard Windows error messages, without
reading private provider text or launching a provider. The diagnostic verifies
that the original stderr and failure metadata have that same hash.

A read-only Win32 observation reproduces error 1 for
`GetFinalPathNameByHandleW` with DOS-volume flags on R:, while C: succeeds.
Opening the volume-root directory for metadata and closing its handle makes no
changes. NT-volume and volume-less forms succeed on R:; replacing the RAM drive
or changing its permissions is unnecessary for this repair.

The installed Codex binary hash was checked without executing it:
`fdda5fa3cf3fb3d000b876720742857676293e4315e4b045fae6f8bd7e866d1d`.
Its existing protected version evidence identifies 0.160.0. In the matching
[OpenAI exec source](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/exec/src/lib.rs),
the explicit `--cd` branch calls strict canonicalization before model startup;
without that option, it obtains the process current directory. The
[absolute-path implementation](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/utils/absolute-path/src/lib.rs)
propagates the strict canonicalization error, whereas obtaining the current
directory normalizes the existing path lexically. This source path and the
matching Windows error support the diagnosis; successful repaired provider
execution still requires the owner-run native acceptance.

Saved observations:

- `docs/evidence/r6-native-hold-v2-diagnostic-20261013.json`: original sanitized export.
- `docs/evidence/r6-codex-cwd-diagnosis-20261013.json`: API results, error fingerprint and binary binding.

## Narrow repair

`NativeRunner` removes only its generated `--cd` option and exact path argument
for Codex. The general MCP command builder retains its explicit-cwd contract.
The native worker already receives that directory through `CreateProcessAsUserW`.
The new helper rejects mismatched identity, another slot, a relative path,
parent traversal, ambiguous cwd options and a different argument value.

The Windows launcher continues to require a real `RamWorkspace` descriptor,
verify RAM volume identity, ownership, permissions and non-reparse ancestry,
and create the child suspended in its assigned directory under its isolated
identity and bounded Job Object. Sandbox, disabled host tools/MCP/hooks,
subscription mode, model, effort, prompt pipe and RAM cache locations remain
unchanged. A successful receipt records `workspace_selection=validated_process_cwd`.

For installed immutable R6 source 359ca92, the separately pinned custody helper
compiles the exact original worker bytes with this same narrow change. Tests
compare the canonical and supplemental helper ASTs, execute both complete
runner paths using fake in-process launches, and reject original-source drift.
Acceptance and protected startup load the same helper hash; activation also
requires the Codex workspace amendment marker. Installed files are not edited.

## Fresh owner continuation

The new mode `20261013-reviewed-codex-cwd-hold-r4-v10` binds all four latest
phase receipts, the target-02 hold with two completed targets, and R4 v10's
retarget, start intent and successful start receipt. Previous reviewed R6 roots
remain preserved and checked. Unknown later phases, active tasks or conflicting
evidence hold before the stop boundary.

The owner stop uses the exact verified R4 v10 action and a fresh stop namespace.
It does not use the previous interrupted-start override. The resulting lineage
passes into R6 activation or a pre-cutover R4 restoration. No automatic replay
of a held command is permitted.

No sign-in or other interactive prompt is planned. Existing sessions are
status-checked; a changed session holds without opening a login. Completed
knowledge is verified without rebuilding. Remaining native acceptance,
preview and cutover run unattended and can exceed 20 minutes. The machine
must remain awake. No reboot or manual continuation is planned.

All 26 retained model/effort targets are checked using the repaired runtime.
The two earlier successes remain historical evidence, not new attestations for
the changed helper. Gemini Pro remains retired, with tiers 5/6 backing off after
their approved Claude/Codex choices. Four shared slots, Chapter 06, credentials,
databases, old captures, repair budgets and R: remain preserved. R7 is separate.

## Verification

The final serialized Windows run passed **582 tests, with 2 skipped, in
75.23 seconds**. It covers the canonical and frozen-source Codex dispatch,
exact unchanged inference policy, cwd mismatch rejection, protected amendment
installation, Agy registry behavior, explicit efforts, all acceptance phases,
retirement, history/restore pins, one-shot stop/rollback sequencing, secret-free
failure projections and launch-package tamper rejection. No native provider,
daemon or real child-launch test was run. The two skips require Windows symlink
creation privileges that this ordinary process does not have.

The broader run also found old contract-test expectations predating the approved
XHigh/Max efforts and Agy registry metadata. Those expectations were updated to
the established interfaces while retaining unsupported-effort and identity
rejection assertions; production policy was not weakened.

Review checked the unchanged Windows launch boundary, exact-source amendment,
same acceptance/startup helper hash, known historical receipt coverage, R4 v10
normal stop lineage, no late prompts and preservation on failure. These source
tests are not deployed native or full SRS acceptance.
