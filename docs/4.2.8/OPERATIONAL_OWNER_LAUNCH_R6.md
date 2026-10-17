# Owner launch: r6 fresh install from the running r4 (`a55f55f`)

The only current owner command is in
[RETURN_SETUP_428_OPERATIONAL_R6_a55f55f.txt](../deployment/windows-deployment-next/RETURN_SETUP_428_OPERATIONAL_R6_a55f55f.txt).
It is one-use. The release itself is described in
[OPERATIONAL_RELEASE_R6.md](OPERATIONAL_RELEASE_R6.md).

## Package

**Commit:** `a55f55f13871eedfe255a8d5aad9f23bb0fc16ac`, branch
`fix/428-operational-repair`.

**Directories under `C:\Users\ansac\CoChem427`:**

| Item | Directory | Pin |
| --- | --- | --- |
| Launch package | `r428-op-launch-a55f55f` | `launch-manifest.json` `736957a3731970c5f2f564242eb76cc24d3db0a95289d5abcfcceac4a1fe314b` |
| Payload | `r428-op-payload-a55f55f` | 470 install rows; install manifest `0e4380ef…`; bootstrap `18250dca…` |
| Request | `r428-op-catalog-a55f55f` | Request `82aff819436849d38fcb1d158d222096`, sha `9d667382…` |
| Codex manifest | `r428-op-codex-a55f55f` | `codex-integration.json` `5e617d56…`, runtime root r6 |
| Source tests | `r428-op-tests-a55f55f` | PASSED, 1,278 tests; report `2e1e33f7…` |

**Request:**
- previous policy `c8444fe2…`, no prior task catalog, partial publication
  allowed;
- 28 targets: 10 Claude, 15 Codex and 3 Gemini, with control target
  `gemini-3.8-flash:low`.

**Other inputs:**
- Source freeze `r428-op-source-a55f55f`: 361 files, manifest `98bc87c1…`.
- Wheel `r428-op-build-a55f55f`: sha `389d44fc…`, 227 files.

**Target:** `C:\Program Files\CoChem\Pipeline4.2.8-windows-20261017-r6`,
revision `windows-20261017-428-v6`. Previous runtime: r4, config `daaa4b6a…`,
install manifest `fdf93bcb…`.

Read-only plans, captured in the tests directory:
- launcher: `READ_ONLY_PLAN_VERIFIED`, 470 payload files, request on
  `c8444fe2…`;
- installer: `READ_ONLY_PLAN`, 470 files to the r6 root.

`r428-op-*-784d684` was built from the first r6 commit and superseded after
the second review round, before delivery. It must never be run.

## Sitting phases and hold semantics

| Phase | Host change | A hold here |
| --- | --- | --- |
| Preconditions | None. All read-only: r4 bounded health; r4's published policy equals the request's; R:/Docker; Codex managed files | r4 keeps running |
| Offline install | New r6 root | r6 root spent; r4 keeps running |
| Codex preflight | Live `config.toml` capture; plan only | As above |
| Admission fence | Writer fence READY. Checks the request against the board's live policy and task catalog | Fence settled; r4 judged and restored if it ended |
| Stop previous | r4 trigger disabled, stopped, task disabled | Fence settled; r4 restored with verified health |
| Catalog acceptance | 28 native probes; publication with candidate validation inside the transaction | NOT_COMMITTED: r4 restored. COMMITTED or unknown: held |
| Cutover / verify / enable trigger | Warden task to r6; health with planning ENABLED/CONNECTED | Held; no automatic rollback |
| Codex integration | Codex MCP table to the r6 venv (live re-capture) | Held; r6 keeps running |

## After success

1. Quit and reopen Codex and Claude.
2. Read-only verification:
   - controller identity and version;
   - task planning ENABLED with execution materialization CONNECTED;
   - catalog coverage (`all_routes_usable` and holds);
   - the Codex MCP command pointing at the r6 venv.
3. Submit the three approved jobs once, with `scripts/submit_428_selected_work.py`
   and the permanent ledger.
4. Verify their artifacts and terminal receipts.
