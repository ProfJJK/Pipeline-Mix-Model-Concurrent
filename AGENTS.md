# Agent rules for this workstation (AETHERDESK) — read before running anything

**Why these rules exist.** On 2026-10-09 at 18:48 this machine bug-checked (Windows stop code 0x21
QUOTA_UNDERFLOW in `nt!PspReturnQuota`, roughly 32 GiB of commit quota returned by one process)
with an agent session open (idle at that moment; the stop code is a kernel fault, see the
post-mortem in the pipeline repository). Windows here is a pre-release Dev-channel build (26300)
running WSL2 + Docker Desktop, Hyper-V (VM `CoChem-Golden-Baker`, switch `CoChem-Quarantine-Switch`)
and an 8 GiB ImDisk RAM disk on R:. Large memory teardowns and process storms can take the whole
host down, and earlier BSODs (September 2026) came from agentic swarm spawn storms. Agents therefore
keep a small footprint and never touch host lifecycle. A PreToolUse hook in `.claude/settings.json`
(`.claude/hooks/cochem_host_guard.py`) enforces the hard rules for Claude Code's shell, file and
MCP tools; Codex and Antigravity agents must follow them by reading this file.

## Never — enforced by the hook
- Start, stop, restart or reconfigure WSL (shutdown, terminate, unregister, import/export),
  Docker (compose down/up, stop, kill, rm, prune, Docker Desktop), Hyper-V VMs (every `*-VM*`
  cmdlet except `Get-VM*`), ImDisk / volumes / diskpart, Windows services, scheduled tasks, or the
  machine itself, directly or through `Start-Process`, `Invoke-Expression` or `cmd /c`.
- Launch the legacy swarm daemons or any script under `D:\__CoChem\__agentic\v4.x`:
  `start_pipeline.bat`, `cochem_startup.vbs`, `pythonw -m cochem.*`, `watchdog_sre.py`,
  `worker_daemon`, `cochem_master_loop*`, `task_work_loop.py`, `cochem_ha_daemon_watchdog`.
- Start, provision or switch the live 4.2.7 controller/warden/supervisor (`cochem_pipeline daemon`,
  `provision-execution`, `cochem_supervisor daemon/once/recover/resume`, any deployment `.ps1`
  with `-Apply`). Those run as SYSTEM from scheduled tasks and only the owner starts them, through
  one reviewed Administrator series.
- Run more than four heavy processes at once (`pytest -n` or `--numprocesses` above 4, `xargs -P`
  above 4, `ForEach-Object -Parallel` without `-ThrottleLimit` 4 or less, `make -j` above 4).
- Kill processes by image name or tree (`taskkill /IM`, `/T`, `Stop-Process -Name`,
  `Get-Process x | Stop-Process`, `pkill`); kill a specific PID you own instead.
- Elevate (`-Verb RunAs`, `sudo`, `runas`, `psexec -s`), edit HKLM, `bcdedit`, install software,
  or write, copy over or delete `~/.wslconfig`, Docker settings, the Startup folder,
  `C:\Program Files\*`, `C:\ProgramData\CoChemPipeline427\*`, `.claude/settings*.json`,
  `.claude/hooks/*` or the guard off-switch.
- Spawn headless agent CLIs (`claude -p`, `codex exec`, `codex --full-auto`, `gemini --yolo`, `agy`).

## Never — rule only, not detectable by a hook
- Run a second Claude / Codex / Antigravity session doing pipeline work on this host at the same
  time as another one. One live engineering session per host, except for the owner-managed
  4.2.8 source-engineering swarm explicitly authorized below.
- Have several agents or subagents each run a test suite or build at the same time.

## Owner-authorized 4.2.8 source-engineering handoff
The owner's latest instruction delegates remaining 4.2.8 coding, testing and release
preparation to an owner-managed Gemini 4 swarm. Use isolated worktrees outside Google
Drive and one integrator for shared files and merges. Keep at most four heavy activities
in total on AETHERDESK, and serialize all test suites/builds using the same host lock.
Additional lanes can run on separate hosts. This scoped source-work exception does not
authorize agents to spawn native/headless CLIs, bypass hooks, run deployment or SYSTEM
probes, elevate, or change protected state or host lifecycle. Only the owner runs the
reviewed final deployment command once 4.2.8 is ready. Start with
[PIPELINE_4.2.8_AGENT_HANDOFF.md](PIPELINE_4.2.8_AGENT_HANDOFF.md),
[tasks/plan.md](tasks/plan.md) and [tasks/todo.md](tasks/todo.md).

The hook scans whole command texts (heredoc bodies included) and the command- and path-like
fields of MCP tool calls. If a harmless command is denied only because it *mentions* a blocked
pattern (for example writing documentation), use the Write / Edit / Read tools for that file.
It fails closed on internal errors. The owner can switch it off by creating
`%USERPROFILE%\.claude\cochem-host-guard.off`; agents never create or mention that file.
Blocked attempts are logged in `%USERPROFILE%\.claude\cochem-host-guard.log`. The hook's
behavioural tests live in the pipeline repository (`pipeline_tests/test_cochem_host_guard.py`).

## Always
- Use the pipeline's own interpreter: `C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\.venv\Scripts\python.exe`
  (Python 3.12, created with `uv sync --frozen --extra dev --extra mcp`). Never the global
  `C:\Python314` for pipeline code — its user site has ~17 `.pth` shims that shadow modules such
  as `scripts`. (The guard hook itself runs under the `py -3` launcher; that is fine.)
- Wrap long commands in `timeout` and keep test runs single-process (`-p no:cacheprovider`, no `-n`).
- Before running any test whose name says actual / real / live / physical, read it. It must be
  in-process only (loopback HTTP, temp SQLite, in-memory MCP). Skip it otherwise.
- Stop at the UAC boundary: prepare and independently review scripts, then hand the owner one
  consolidated Administrator PowerShell series. Never ask the owner to repeat approvals already
  granted (see `docs/WINDOWS_AGENT_HANDOFF_4.2.7_2026-10-09.md` in the pipeline repo).
- If the machine crashes again, the owner can analyze `C:\WINDOWS\Minidump\*.dmp` with WinDbg
  (`!analyze -v`).

## Owner-approved Codex, Claude and Agy sign-in experience
2026-10-13: the owner explicitly extended the successful `agy-signin-c4d4a66`
interaction format to **Codex, Claude and Agy**. Use the standard Windows
dialog with a selectable fresh URL, **Copy URL**, a masked field supporting normal
Ctrl+V, and **Submit**/Enter. The owner opens the URL manually. Handle profiles
sequentially, verify authentication after each, and skip already verified sessions.
Do not revert to automatic browser launching, native TUI navigation, raw console
key capture, or deployment as a prerequisite for signing in. Preserve the existing
isolation/cleanup checks. See `docs/AGY_SIGNIN_2026-10-13.md` for the successful
six-profile host receipt and the reusable implementation. Fresh attempts always
need their own URL/code; never reuse prior OAuth links or codes.
Respect each provider's protocol: Codex device codes are entered in the browser;
only show a masked callback-code field when the provider actually requires one.
This is the preferred interface, not a claim that all three adapters have been
implemented or accepted on this host. Reuse verified sessions before asking for input.

## Current handoff
The owner has now run `r428-op-launch-865a29b`; it is spent. Its r5 installation
and Codex preflight completed, but admission fencing held before catalog
acceptance or cutover. The received diagnostic proves an expired, unreleased
fence and an ended r4 Warden (unchanged definition, exit 1, no instances or
listener). Do not claim the previous runtime is healthy or rerun the installer.
Read `docs/4.2.8/OPERATIONAL_FENCE_HOLD_20261015.md`. The owner also ran the
`r428-op-recovery-01f782a` continuation; it is spent. It held in preconditions
at the process inventory check, which omitted the existing reviewed legacy
Codex/Claude `cochem_mcp` bridges. No new fence/task change/cutover was reached.
See `docs/4.2.8/evidence/operational-recovery-01f782a-hold.json`. The corrected
launcher at `4eabf2e` passed 233 source/inert tests; its fresh packaged read-only
plan passed, but the owner has now run that package too; it is spent. It held
in preconditions on PID 9612, the existing held supervisor observer. The public
command hash exactly matches the old documented observation-only invocation;
see `docs/4.2.8/evidence/operational-recovery-4eabf2e-hold.json`. No new fence,
task mutation or cutover occurred. The correction at `490bf2e` passed 273
serialized source/inert tests. The actual protected observer files and public
heartbeat passed the final read-only verifier (120 immutable files including
109 application files); task/native identity checks remain owner-only. The
fresh packaged read-only plan passed, but the owner has now run `490bf2e` too;
it is spent. It held at the observer task ACL call before mutations. The
verifier incorrectly applied Warden-only ACL rules instead of the original
observer's v8 Scheduler projection/private task backing-file proof. Read
`docs/4.2.8/evidence/operational-recovery-490bf2e-hold.json`. The observer-only
ACL correction at `90c9c1d` passed 315 source/inert tests with real descriptor
parsing and retained backing-file proof. The actual packaged read-only plan
passed. Use only the new owner command in
`docs/4.2.8/OPERATIONAL_OBSERVER_ACL_RECOVERY_20261015.md`; all earlier commands
are spent. Actual protected task/native and deployment acceptance remain pending.
Do not rerun old commands, close clients or the observer, repeat sign-in, or
submit jobs before verified recovery. Source/package proof is not deployment.

2026-10-15: the owner-approved seven-part operational repair is integrated on
`fix/428-operational-repair` in the separate local
`C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent-428-repair` checkout.
The final source/inert regression at `aa7706e` passed 973 tests, with one skip
and eight documented exclusions. Read `docs/4.2.8/PROGRESS.md`, `VALIDATION.md`
and `OPERATIONAL_OWNER_LAUNCH_R5.md` (all under `docs/4.2.8`). The final immutable
package and owner command are recorded separately in
`docs/4.2.8/OPERATIONAL_R5_DELIVERY_20261015.md` after package verification.
Only the owner executes Apply. Do not replay old R5/R6/R7/4.2.8 commands.
Source tests do not attest native acceptance, deployment or useful-job completion.
Completion-audit dispatch and independent repair callbacks remain unconfigured;
strict catalog coverage holds must not be weakened. Preserve other specialist
integrations, all old packages and existing work. The following handoff is historical.

## Historical handoff
4.2.8 coding is handed over at implementation baseline
`c33c7ea2a9d7c655b6998081080b4eae2273ee1b` on `feature/4.2.8-task-routing`.
The root handoff and task list above are the current remaining-work authority.
Planning source is integrated, but execution materialization, research/approval/repair
adapters and the fresh 4.2.8 release package remain incomplete. No 4.2.8 launch command
exists yet. The following R6 notes describe preserved host evidence, not instructions
to repeat an old launch.

The v3 native diagnostic is now received: target-23 is Claude Fable 5.1 High,
with a failed result and HTTP 429 indicator. The owner reports likely exhausted
Fable quota. The additional HTTP-client status prefix is repaired in source and
the exact-source amendment; 255 inert regression tests passed. Raw host text
remains private, so the next reviewed continuation must validate the pinned
failure before a stop/cutover. No replacement launch package has been delivered
for this change. Read docs/R6_NATIVE_LATEST_2026-10-13.md. R4 v11 is the last
verified restoration, admission capacity zero; do not repeat sign-ins/export.
The following earlier handoff records its state before that diagnostic arrived.

2026-10-13 18:26: `r6-launch-d19b42c` has run and is spent. All 18 sessions,
knowledge and agent checks passed; native acceptance held with ProviderFailure
category `code` (worker frame 1023). R4 v11 restoration returned verified health,
with admission capacity zero. No R6 cutover occurred. The public report does not
identify the failed native target. Read `docs/R6_NATIVE_LATEST_2026-10-13.md`.
The new v3 diagnostic reads this exact attempt; never replay d19b42c or request
sign-ins again. Independent 4.2.8 source work is on `feature/4.2.8-task-routing`;
see `docs/4.2.8/IMPLEMENTATION_PLAN.md`. It is not deployed. Earlier notes below
are historical and do not authorize running an old setup command.

2026-10-13 v2 diagnostic received: native target-02 was Codex Luna Medium,
slot3. Agy Flash Low and Claude Haiku Medium passed. Its 40-byte stderr hash
exactly matches Windows error 1, reproduced by the DOS final-path query on R:.
Codex 0.160.0 strictly canonicalizes explicit --cd before inference; the repair
uses the same validated process cwd without that redundant option. Read
`docs/R6_CODEX_RAM_CWD_REPAIR_2026-10-13.md`. Source and immutable-runtime helper
are repaired together; the fresh continuation binds verified R4 v10. Do not
replay d6d336e, request new sign-ins, or rerun the completed diagnostic. Only the
owner executes a delivered Apply command. The following notes are historical.

2026-10-13 11:37 run: `r6-launch-d6d336e` is now spent. All 18 sessions,
knowledge and agent checks passed again. Native acceptance held at frozen
worker.py:1033 with ProviderFailure category `code`: an unclassified nonzero
native exit, before response validation. The provider/target/reason are not
yet established. R4 restoration v10 returned verified health; admission capacity
was zero, so do not claim work admission. Read `docs/R6_NATIVE_EXIT_2026-10-13.md`.
The read-only v2 diagnostic targets this exact attempt and is the only pending
owner action. Do not replay deployment, repeat sign-ins or weaken validation.
The following paragraphs are historical preparation and earlier outcomes.

2026-10-13 native diagnostic received: first Agy inference succeeded, with no
tool steps, but its global CLI registry advertisement triggered our parser.
Read `docs/R6_AGY_REGISTRY_REPAIR_2026-10-13.md`. The repair is exact-binary/agent
bound, with identical supplemental acceptance/startup code for immutable R6.
The fresh continuation binds native hold and interrupted R4 v9 evidence; do not
replay 7451831, request sign-ins again, or treat R4 v9 as a verified restoration.
Only the owner may run the new pinned command. No Apply is authorized to agents.
The following paragraphs record the preceding history.

2026-10-13 09:34 attempt: `r6-launch-7451831` has now run and is spent.
All 18 sign-ins, knowledge and agent acceptance passed; native acceptance held
at Agy response compatibility. R4 restore v9 did not verify, although a read-only
health observation found R4 responding. Do not replay deployment or sign-ins.
Read `docs/R6_NATIVE_HOLD_2026-10-13.md` for the exact evidence and prepared
read-only diagnostic. Preserve every protected task/root and running process.
The continuation notes below describe the earlier preparation, not current readiness.

2026-10-13: Agy sign-in succeeded for all six profiles. R6 continuation is prepared
in `docs/R6_SIGNED_IN_CONTINUATION_2026-10-13.md`; only the owner runs its fresh
Administrator command. The 07:33 attempt verified all 18 provider sessions and
completed new R6 knowledge, then held at agent acceptance with ValueError.
R4 v8 is the last verified restoration; do not replay c7a9241, rebuild the
completed knowledge or claim R6 startup. Read
`docs/R6_AGENT_DIAGNOSTIC_2026-10-13.md` for the focused diagnostic and evidence.
The diagnostic is now completed: READ_CONTROL-only directory handles did not
enforce delete sharing. Read `docs/R6_CUSTODY_REPAIR_2026-10-13.md` for the
proved repair and explicit continuation reusing completed knowledge/sign-ins.
Only the owner runs the fresh pinned continuation. Old R7 bundles must not
be used against its amended R6 startup action.
The 09:18 run of bf5b5f6 held before stopping R4: its owner preflight tried to
inspect SYSTEM-private knowledge. Replacement source 7451831 keeps that check
in SYSTEM and uses the installed private-state reader, not a code-path reader.
300 source/fixture tests and the frozen read-only plan passed. The fresh owner
package is `C:\Users\ansac\CoChem427\r6-launch-7451831`; see the custody repair
document for its manifest pin. Do not rerun bf5b5f6 or assume the replacement
has run. R4 v8 remains the last observed running source.
Codex/Claude/Agy share the sign-in
preference above. The following 12 October handoff is historical context.

2026-10-12: the Claude Code session has released all locks to the takeover agent; see
`docs/AGENT_RELEASE_NOTICE_2026-10-12.md`.
Start with `docs/WINDOWS_AGENT_HANDOFF_4.2.7_2026-10-11.md` (branch `feature/r5-gemini-and-runtime-fixes`):
the Warden is down, r5 is installed but not activated, and the owner's sitting rerun is the next step.
The routing-tier redesign is left open for the next agent. A mirror of the deployment workspace is in
`docs/deployment/windows-deployment-next/`.

## Where things are
| Thing | Path |
| --- | --- |
| Pipeline 4.2.7 source (GitHub ProfJJK/Pipeline-Mix-Model-Concurrent) | `C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent` |
| Installed protected runtimes (owner/admin only) | r4 (last active) `C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4`; r5 (installed, not activated) `...\Pipeline4.2.7-windows-20261011-r5`; r3 `...\Pipeline4.2.7-windows-20261007-r3` |
| Runtime client config used by every GUI's MCP entry | `C:\Users\ansac\CoChem427\pipeline-client-r3.json` |
| Deployment engineering workspace (installers, freezes, owner sheets) | `C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next` |
| Legacy agentic swarm trees (retired 2026-10-10; never start or restore) | `D:\__CoChem\__agentic\v4.1.2`, `D:\__CoChem\__agentic\v4.2.0` |
| Workspace folder (untracked inside the `D:\__CoChem` git repo) | `D:\__CoChem\GitHub-Repo` |
| Owner's hardening notes from earlier BSODs | `D:\__CoChem\PRIORITY-PIPELINE-*.md` |
