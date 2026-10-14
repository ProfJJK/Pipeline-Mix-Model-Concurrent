# Latest R6 native hold: 18:26 owner run

The owner executed `r6-launch-d19b42c`. That immutable package is spent.
Authentication reused all 18 sessions; knowledge and agent phases completed.
Native acceptance held with `ProviderFailure`, category `code`, at the amended
worker's frame 1023. That category does not identify a provider or prove the
previous Codex cwd repair failed. Do not infer a new root cause from the frame.

R4 restoration v11 returned `WARDEN_R4_RESTARTED_HEALTH_VERIFIED`; its receipt
SHA256 is `de5e242b27664dccf5efdff965835b858adc2a33d078c85ea5137f4dff69b3c3`.
Admission capacity was zero. R6 was never activated and no R7 cutover occurred.

The exact native root is
`C:\Program Files\CoChem\R6Acceptance4.2.7-windows-20261012-v1-native-47e4889af6284a9fad018142a14d5371`.
The ordinary engineering process cannot read its private records. The new
`scripts/inspect_r6_native_hold_v3.ps1` reads only this attempt's existing failure,
completed-target summaries and the R4 v11 restoration metadata. It exports
allowlisted diagnostic indicators and hashes, never credentials, sign-in URLs,
generated text or raw native output. It runs no providers or tasks and changes
no protected state. Forty inert PowerShell fixture tests passed.

## Diagnostic received and quota repair

The owner completed the export at 2026-10-14 00:36 UTC. Its preserved sanitized
copy is `docs/evidence/r6-native-hold-v3-diagnostic-20261013.json`. Do not request
another run of that diagnostic. Target-23 is Claude Fable 5.1 High, slot1.
The output has a failed Claude result (`is_error: true`), exit 1, and an HTTP
429 indicator. Output hashes match the private failure metadata. There are
23 earlier recorded target outcomes; the previously failing Codex Luna Medium
check passed. The owner reports likely exhausted Fable quota.

Quota exhaustion is consistent with these observations, but a generic HTTP
429 indicator cannot distinguish subscription exhaustion from temporary rate
limiting. It also cannot establish the exact failed-result text. Ordinary
access to the raw record is still denied. No quota reset time is known.

Read-only inspection of the installed Claude executable found the HTTP-client
format `Request failed with status code N`. The current parser recognizes only
the `API Error: N` form. The source repair accepts the additional anchored
HTTP-client prefix (including its `API Error:` wrapper), exclusively inside a
failed Claude result. Successful answers, tool output, embedded HTTP mentions
and malformed status numbers remain data. Metadata records the numeric status
without publishing error text. A separately pinned amendment applies the same
repair to exact original R6 failure-module bytes in memory, retaining the
installed exception class; no protected installed file is changed.

The serialized regression run passed **255 tests** in 1.62 seconds, covering
canonical/frozen parsing, source drift rejection, exception identity, native
dispatch doubles, Agy/Codex repairs and continued independent-provider probes
when quota is unavailable. These fixtures are not a replay of the inaccessible
host result. The next reviewed continuation must verify that exact preserved
result against the repaired parser before changing the running Warden.

The existing acceptance runner already records typed quota as unavailable and
continues independent providers without attesting the skipped selector. Runtime
availability uses the approved fallback/backoff path, not a quality-failure
cycle. Generic 429 does not identify the quota pool's finer model scope.

**No replacement deployment package is delivered by this source change.**
Do not rerun d19b42c, repeat sign-in, or claim R6 activation. Preserve every old
receipt and completed check. Independent 4.2.8 source work continues.
