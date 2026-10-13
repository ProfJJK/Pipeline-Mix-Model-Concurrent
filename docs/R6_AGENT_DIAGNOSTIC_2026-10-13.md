# R6 agent acceptance hold after the 07:33 run

The owner ran immutable `r6-launch-c7a9241`. Sitting
`53b47af9480c4db181e71a79f18a3cad` verified the existing installation,
all six Codex, six Claude and six Agy sessions, completed agent staging and
the new R6 knowledge phase, then held in the `agent` acceptance phase.
No R6 cutover occurred. R4 restoration v8 reported
`WARDEN_R4_RESTARTED_HEALTH_VERIFIED`; its controller still reported admission
capacity zero. This is not full pipeline acceptance.

R4 v8 start receipt SHA-256:
`3cd7e7f1826acc141f7e7144f03c062e32162d5be0a7b6282d82aba3db13fbc4`.
Retarget receipt SHA-256:
`1fefb772f34463218d62211715e8c45e961fee21d5070544514f63309712c666`.

## Observed failure and diagnostic gap

The owner read the private agent-phase error and receipts. The Python receipt
records `ValueError`, category null, but no failed substage, exception text,
source position or handle results. The PowerShell wrapper records only its
own generic `RuntimeException`. Those records cannot identify the root cause.
The SYSTEM action did not retain a separate Python exception log.

The installed guard normally wraps its internal failures as `AgentGuardError`
with category `compatibility`. A plain ValueError could come from installation
binding, read-only RAM inspection or the acceptance test's access assertions.
No particular failure or permission repair is assumed. The ordinary frozen
candidate's agent contract was verified without native execution; that alone
does not establish the installed native boundary.

Preserve these exact private receipts, under `C:\Program Files\CoChem`:

- Agent: `R6Acceptance4.2.7-windows-20261012-v1-agent-0269bb0c420b488bbb4874841be21ea0\held.json`.
- Auth: `R6Acceptance4.2.7-windows-20261012-v1-auth-9e0a79eaef0d4c2eb749842913ce38ec\result.json`.
- Knowledge: `R6Acceptance4.2.7-windows-20261012-v1-knowledge-47776d31bd0e4773be318bde56f5be0a\result.json`.

All bind manifest
`bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4`
and candidate
`a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288`.
The installed runtime remains immutable source `359ca92`.

## Focused diagnostic

`scripts/inspect_r6_agent_custody.ps1` validates a five-file pinned package,
protected installed code and interpreter, and creates one fresh on-demand
SYSTEM task. It acquires the owner-maintenance mutexes and refuses active
acceptance/login tasks. It never changes any daemon task. The owner needs
Administrator PowerShell to create this protected diagnostic task and access
its existing private prerequisites; the engineering session does not run Apply.

The helper reads the preserved receipts, binds the installed revision, repeats
only the original read-only RAM inspection, and wraps the actual installed
`verify_worker` and `WindowsChecks`. Before each worker it holds the same
SID-scoped lifetime reservation as normal pipeline jobs. It captures stages,
numeric Win32 results, cleanup-call completion and allowlisted failure metadata.
It stops at the first failed check or cleanup. No acceptance decision is altered.
No provider, sign-in, model job, knowledge refresh, database migration, profile
write or ACL change is performed. R4 stays running. Successful diagnostic capture
is not successful acceptance, even when its process exits zero.

Access-result indices follow the unchanged production request order:

| Index | Path relative to worker profile | Requested access |
| --- | --- | --- |
| 0 | Profile directory itself | DELETE |
| 1 | `.gemini` | DELETE |
| 2 | `.gemini/agents` | DELETE |
| 3 | `.gemini/agents/cochem-inference-only` | DELETE |
| 4 | `.gemini/agents/cochem-inference-only/agent.md` | DELETE |
| 5 | `.gemini/config` | DELETE |
| 6 | `.gemini/config/agents` | DELETE |
| 7 | `.gemini/config/agents/cochem-inference-only` | DELETE |
| 8 | `.gemini/config/agents/cochem-inference-only/agent.md` | DELETE |
| 9, 10 | The two agent files respectively | GENERIC_WRITE |

The diagnostic opens/closes these handles without issuing writes/deletes.
The report contains no account identifiers, credential data, document text,
raw provider output or raw exception strings. Only the new sanitized
`status.json` is readable by ordinary users; existing permissions remain intact.
A pinned fresh namespace prevents replay of this same command. Failures preserve
the task, helper and receipts; there is no automatic retry or cleanup.

## Validation and continuation boundary

72 serialized Python 3.12 / Windows PowerShell source and inert fixture tests
passed in 14.72 seconds. They cover before/during/after failures, token/guard
cleanup paths, exclusive reservations, sequential execution, package tampering,
actual diagnostic-writer/PowerShell-reader integration, exact task settings and
fast completion. No physical worker checks or task lifecycle operations were
performed by the engineer. Host capture remains pending.

After the diagnostic, repair the proved cause and build a fresh continuation
that binds these completed auth/knowledge receipts and R4 v8. The old recovery
verifier deliberately refuses existing knowledge; do not weaken that history
check or replay `fresh_knowledge`. Native selector acceptance, preview and R6
cutover remain outstanding. Keep R7 separate and do not claim it deployed.
