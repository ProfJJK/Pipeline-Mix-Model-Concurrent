# Owner-approved operational repair — 2026-10-15

The owner approved all seven recommendations in the Codex conversation on
2026-10-15, including the following additions: provide the required format with
the task before its first attempt; use existing useful jobs as acceptance tests
where they can also complete real work. This supersedes unresolved choices in
the recovered Antigravity handoff b69388bf-08c1-4c61-a09e-db8086870542.

## Adopted policy

1. Controller CPU: one E-core equivalent is the initial new-admission threshold,
   measured over the existing ten-second window. 0.5 core is an optimization
   target, not a second admission gate. With eight allowed processors, the
   threshold equals 12.5% in the legacy normalized display. Preserve the 200 MiB
   controller memory limit and all emergency protections.
2. Brief CPU/disk congestion prevents additional starts without killing existing
   work. Healthy samples reopen admission promptly after a transient condition.
   Memory/commit/temperature/missing required telemetry and sustained critical
   conditions retain protective behavior. Four shared execution slots remain.
   Never subtract percentages with different CPU scopes. Every reduction has a
   reason; total host load remains a safety signal.
3. Coding submission prepares/registers an isolated repository automatically
   under configured trusted roots. Working repositories are outside Google Drive
   and other synchronized locations. Preserve task-relevant uncommitted changes
   in an exact snapshot and check for concurrent changes before integration.
   Never route production work to windows-acceptance or commit unrelated files.
4. A shared output contract supplies initial prompts, deterministic handoff forms
   and validation. The preparation step fills known identities, allowed paths,
   upstream hashes and deliverable requirements. Up to two corrective attempts
   may repair formatting before normal failure escalation. Every dispatch still
   spends its overall dispatch/time/quota budget. Never invent missing content,
   IDs, paths or evidence, and never weaken semantic acceptance.
5. Recover the owner's selected legacy work through consistent snapshots, exact
   manifests, deterministic deduplication and a durable submission ledger.
   Preserve the selected deletion archive; do not infer choices for other
   categories. Missing/ambiguous inputs remain explicit holds. Keep imports
   separate from installation and preserve original evidence databases.
6. Audit and version reproducible integration templates, MCP definitions, skills,
   rules and agent definitions with exact source commits in the release manifest.
   Do not commit credentials, personal config wholesale, live databases or WAL/SHM.
7. Enable and test the actual intended 4.2.8 planning/research/review/approval/
   execution path. Document-generation success is not proof of external work.
   Prefer existing suitable jobs as useful acceptance workloads with duplicate
   detection, exact deliverable checks, and preserved exam/YouTube ownership.

## Work boundaries

Direct repository maintenance is authorized. Other agents own Antigravity/exam/
YouTube changes; preserve their files and use their verified outputs. No agent
elevation, protected writes, native headless CLIs, live lifecycle changes, or
deployment Apply is authorized. Only the owner runs the reviewed installation.
All planned user input is at the beginning, at most twenty active minutes; total
unattended runtime may be longer. Late failures save evidence rather than prompt.

Engineering uses isolated local worktrees, a single integrator and serialized
tests/builds through the host lock. The installed r4 runtime and delivered bundles
remain immutable. Source verification and actual host acceptance are distinct.

## Repair sequence and evidence

- [x] Repository registration and acceptance-fixture boundary: source and fixtures.
- [x] Initial output contracts, handoff forms and bounded correction accounting.
- [x] CPU units, transient admission recovery and explicit pressure reasons.
- [x] Connected 4.2.8 planning configuration and execution source/fixture coverage.
- [x] Legacy inventory, useful-work acceptance plan, snapshots and import ledger.
- [x] Sanitized integration templates and owner-launch implementation.
- [ ] Final immutable package and packaged read-only verification.
- [ ] Owner-run protected installation, native catalog acceptance and cutover.
- [ ] Refreshed Codex MCP submission and verified useful-job deliverables.

Baseline: c714854506c736431e6a0d5aaea2471aba8ab5ff. Add implementation commits,
focused/regression test evidence and remaining host acceptance requirements as
each slice completes. No checkbox is satisfied by a proposal alone.
