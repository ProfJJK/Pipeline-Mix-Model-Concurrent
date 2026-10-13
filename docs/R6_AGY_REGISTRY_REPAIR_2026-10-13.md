# R6 Agy registry repair and native continuation

## Confirmed cause

The owner's sanitized diagnostic from 15:42 UTC shows that the first native
probe returned exit 0, SUCCESS, the requested `gemini-3.8-flash-low`, one turn,
and no tool steps or model substitutions. Its `init.tools` advertised 60 names.
The installed parser rejected this as `agy_tool_registry`; it was not an
authentication failure. All 18 provider sessions, knowledge and six-worker
custody had already passed in that sitting.

Evidence is preserved in `docs/evidence/r6-native-hold-diagnostic-20261013.json`.
No raw response, tool names, account identifiers or credentials are published.
The spent launch `7451831` and all prior packages remain unchanged.

## Registry interpretation and its limits

Static inspection of the exact protected Agy 1.3.1 executable (SHA256
`38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741`)
traced Go `printmode.buildInitPayload` to `printmode.advertisedTools`.
The call passes a Boolean comparing the execution mode to `jetski`; the callee
enumerates a global runner map at RVA `0xb2184f0`, not the selected agent's
permission list. Function hashes and instruction anchors are reproducible with
`scripts/inspect_agy_registry_binary.py`, which reads bytes without executing
the provider. See `docs/evidence/agy-registry-static-review-20261013.json`.

This static finding explains the advertisement; it does not prove that a
selected agent's exclusion policy was enforced during a live request.
Google's [headless documentation](https://www.antigravity.google/docs/cli/headless/)
describes the initialization fields, including the selected agent when an
explicit agent is requested. The [agent documentation](https://www.antigravity.google/docs/subagents/)
documents tool allowlists and primary-agent selection. The
[CLI changelog](https://www.antigravity.google/docs/changelog?tab=cli)
documents `excludeDefaultComponents` and `inheritCustomizations` controls.
Those controls already exist in our protected inference-only definition.

The repair therefore requires all of these together:

- Exact reviewed executable hash/version and protected 478-byte agent hash
  `5c0082d70d073263a56d748a46187008968c070d0efc7d5b7612c2fd61d11810`.
- Existing path/ACL/content checks and retained handles for both agent locations.
- Explicit selection of `cochem-inference-only` in both arguments and `init.agent`.
- Bounded, valid advertised names, correct model/session, and successful terminal status.
- No tool steps, subagent activity, fallback, reroute or model replacement.

Other binary/agent pairs do not inherit the registry interpretation. Receipts
save the registry scope, count and binding hashes, not tool names. Native
acceptance still must pass on the host; an absent/mismatched selected-agent field
holds rather than being inferred from response text.

## Immutable installed R6

Canonical source has the corrected parser. The already installed R6 remains
source `359ca92`, with unchanged manifest and configuration. A separately pinned
`r6_custody_amendment.py` compiles only the exact original protocol and worker
bytes in memory. It preserves public exception identities and replaces only
the parser/runner callbacks required for registry interpretation and receipt
metadata. The existing directory-handle repair remains bound to this helper.
Installed files, ACLs and historical job captures are not rewritten.

Native acceptance and the protected daemon entry point use the identical
helper hash. Activation requires its explicit registry amendment receipt in
addition to existing custody evidence. Source-byte, agent, executable or
receipt mismatches hold before activation. A fixture executes the actual
frozen R6 functions through a fake in-process launcher; it does not launch Agy.

## Owner continuation

The new manifest mode `20261013-reviewed-native-hold-r4-v9` binds the completed
09:34 authentication, knowledge and custody receipts and the exact native hold.
Unknown later acceptance folders or active older tasks are refused. Existing
knowledge is verified in SYSTEM without rebuilding; no profiles are restaged.

R4 v9 has a retarget receipt and start intent but no completed start receipt or
held-start record. The diagnostic observed its task running. That is not a
verified restore or admission-ready pipeline. The continuation first checks
those exact hashes and then uses the released `stop-warden-r5` helper with
`RecoverInterruptedStart`, a fresh stop namespace, idle proof and the exact
R4 v9 task/process binding. It does not broadly kill processes or restart R4
to manufacture missing evidence. The resulting stop lineage is carried into
R6 activation or a pre-cutover R4 restoration. Recovery failures now retain
sanitized exception type and source positions instead of only `restored=false`.

The owner runs one fresh pinned Administrator command. No sign-in is planned;
the 18 existing sessions are status-checked and a changed session holds without
opening a prompt. After the initial launch the owner can walk away, leaving
the machine awake. Remaining acceptance may take longer than 20 minutes.
No late input, reboot or manual continuation is planned. A failure preserves
evidence; the command must not be replayed.

The 26 retained model/effort targets and four shared slots are unchanged.
Gemini Pro stays retired: tiers 5/6 retain Claude/Codex followed by backoff,
without substituting Flash below the approved reasoning floor. R7 remains
separate; old R7 packages cannot be reused against the amended R6 action.

## Review and verification

The engineer reviewed registry provenance, protected agent custody, exact-byte
amendment construction, receipt-to-startup binding, and the interrupted-start
stop/retarget lineage. No provider CLI, SYSTEM task, daemon, administrator
command or protected mutation was executed by the engineering session.
Source/fixture results and the fresh package's read-only plan are recorded
below when completed. They are not Windows deployment or full SRS acceptance.

The final combined serialized run passed **456 tests in 58.20 seconds** on
repository Python 3.12 and Windows PowerShell 5.1. It covers the captured failure
shape, actual frozen-source amendment, fake native dispatch and receipts,
unknown bindings/tool use rejection, held-history pins, R4 v9 stop sequencing,
startup acceptance binding, package integrity, retired routes, and sanitized
failure reporting. Real provider/child-launch tests were excluded.
