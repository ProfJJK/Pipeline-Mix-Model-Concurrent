# Operational r5 delivery — 15 October 2026

The seven owner-approved source repairs are implemented and packaged. **Only the
owner runs the Administrator command below.** This delivery does not claim that
native acceptance, cutover, refreshed Codex MCP submission or useful-job completion
has occurred. The installed runtime was not changed by the engineering session.

## One owner command

Paste this once into 64-bit Administrator Windows PowerShell 5.1. All dependencies
and the application wheel are already built locally. Existing sign-ins are reused;
there are no planned later sign-in prompts, restarts, or continuation commands.
Leave the computer and PowerShell running. The input window is at the beginning;
idle drain and native checks can continue unattended for considerably longer.

```powershell
C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -File "C:\Users\ansac\CoChem427\r428-op-launch-865a29b\run_operational_428_launch.ps1" -LaunchManifest "C:\Users\ansac\CoChem427\r428-op-launch-865a29b\launch-manifest.json" -LaunchManifestSha256 49481181faa25f4b8762b85013bece21afb3f58b3f9b8e7417237fa3dacfc75c -Apply
```

The matching local owner sheet is
`W\RETURN_SETUP_428_OPERATIONAL_R5_865a29b.txt`, where
`W=C:\Users\ansac\Documents\Codex\2026-10-06\the-github-repository-is-located-at\windows-deployment-next`.
A tracked identical copy is in `docs/deployment/windows-deployment-next/`.

Success is `R428_OPERATIONAL_RUNNING_VERIFIED`. Any other result preserves evidence;
return the sanitized final status instead of replaying the command. The launch
checks the saved r4 identity against the real host before changing it. Restoration
is allowed only under the reviewed pre-publication/clean-exit conditions documented
in [OPERATIONAL_OWNER_LAUNCH_R5.md](OPERATIONAL_OWNER_LAUNCH_R5.md).

## Exact prepared release

| Item | Evidence |
|---|---|
| Source commit | `865a29b113a8b59c822f6aa4d921a45c18407fe5` |
| Tested code commit | `aa7706e78abd7ab0d7eaec30e5c8f2858d51665c`; subsequent source checkpoint changes documentation only |
| Source freeze | `C:\Users\ansac\CoChem427\r428-op-source-865a29b`; 297 files |
| Application wheel | `r428-op-build-865a29b\dist\cochem-4.2.8-py3-none-any.whl`; 227 verified source/assets; SHA256 `12206a12c03c59f6cb5cf1a55c5d9baa2ed16bcd2885db6e597ca6cebedee240` |
| Offline payload | `r428-op-payload-865a29b`; 406 pinned install inputs |
| Install manifest | `775de3a3c0edc9e8355d451728f370089ffce09a5f73c9b745c0d019912787d9` |
| Launch directory | `C:\Users\ansac\CoChem427\r428-op-launch-865a29b`; 12 direct pinned launch inputs |
| Launch manifest | `49481181faa25f4b8762b85013bece21afb3f58b3f9b8e7417237fa3dacfc75c` |
| Catalog request | `8ca37638b5dbe15b877c7505dc2acbabac5f6e9b962b6b90101e5cc268aa814f` |
| Fresh target | `C:\Program Files\CoChem\Pipeline4.2.8-windows-20261015-r5` |

All `r428-op-*-865a29b` and the existing verified wheelhouse directories must remain
in place because the install manifest references their exact local files. Nothing
was downloaded during the offline build. Original runtime packages, databases,
credentials, quotas, repair budgets, R: and four shared slots are preserved.

The 27-profile allowlist is the exact reviewed set in
[OPERATIONAL_CATALOG_CANDIDATE_20261015.json](OPERATIONAL_CATALOG_CANDIDATE_20261015.json).
Partial publication is explicitly enabled: quota-held/unaccepted profiles remain
unavailable and strict capability/reviewer floors stay in force. Five ranked
comparison models per row do not mean five natively accepted available models.
The default Flash Low control check is separate from ordinary accepted profile
selection. No new Argon native selector or effort support is invented here.

## Verification and limits

The final integrated sweep passed **973 tests, 1 skipped, 8 deselected in 281.64s**.
See [VALIDATION.md](VALIDATION.md) for exact exclusions, including six historical
error-message-only assertions that are not claimed as passing. Independent source
review found no remaining owner-launch or package-coherence blocker.

Both actual packaged scripts ran without Apply under the shared test/build lock:
`READ_ONLY_PLAN_VERIFIED` from the launcher and `READ_ONLY_PLAN` from the installer,
both exit 0. Every direct launch input and external install input was rehashed and
size-checked. A separate reviewer independently verified all 12 launch pins,
406 installation inputs (130,560,536 bytes), 297 frozen source files, the canonical
request/agent bindings and all four current Codex target hashes. No package blocker
was found. The ordinary verification record is
`C:\Users\ansac\CoChem427\r428-op-verification-865a29b.json`.
The Codex export captured and validated current transformations. Its executable
preflight intentionally requires the new installed interpreter, so that check
runs after offline installation and before stopping r4; an early non-admin call
correctly refused the not-yet-created runtime and changed nothing.

The first worker prompt now contains the exact output schema and controller-filled
handoff form used by validation. [OUTPUT_CONTRACTS_20261015.md](OUTPUT_CONTRACTS_20261015.md)
and `scripts/prepare_job_handoff.py` describe reusable offline preparation. Format
corrections do not reset semantic, dispatch, time or quota budgets.

The three selected existing quick-reference jobs are prepared with pinned inputs,
embedded source excerpts and a permanent duplicate-protection ledger. They have
not been submitted. After successful owner deployment, verify the new controller
identity and use [SELECTED_USEFUL_WORK_INTAKE_20261015.md](SELECTED_USEFUL_WORK_INTAKE_20261015.md)
to submit them once and check actual deliverables. Their content limitations and
normal high-tier owner approval gates remain explicit.

The scoped Codex integration updates only its CoChem MCP entry, managed global
rules, skill and agent metadata. The current session does not dynamically gain
MCP tools; refresh Codex after successful completion. Other specialist integrations
are unchanged. Automatic completion-audit dispatch and isolated repair callbacks
remain unconfigured; this release must not be described as accepted autonomous
self-healing or universal task/model coverage.
