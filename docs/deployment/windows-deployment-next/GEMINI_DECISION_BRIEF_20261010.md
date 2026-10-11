# Gemini in the 4.2.7 pipeline: the decisions, with options

AETHERDESK, 10 October 2026. Written for the owner. Facts come from four read-only readers over the
pipeline source, the installed CLI, the login series receipts and the vendor documentation; nothing here
is a guess, and the one unknown that matters is marked as such.

## What is true today

- The pipeline runs on the repaired r4 runtime. Claude and Codex serve every routing tier. A Gemini
  candidate is refused at dispatch in about two seconds and the job continues on the next candidate;
  the refusal costs no quota and is remembered for five minutes per model.
- The refusal is not a credential problem. The Gemini provider carries an integration hold whose three
  findings name capabilities the installed Antigravity CLI (agy 1.3.1) does not expose:
  1. AGY-AUTH: no command reports whether a worker identity is signed in (no auth, status or whoami
     subcommand; the usage and model reports carry no account field).
  2. AGY-ISOLATION: no documented way to prove the CLI runs with tools, MCP servers, hooks, subagents
     and model fallback disabled inside an isolated worker.
  3. AGY-IDENTITY: the CLI's result envelope names no serving model, and the pipeline's third parser
     is blocked in source until such a receipt exists.
- Removing the hold makes the configuration loader demand the matching contract fields (headless
  argument list, per-worker authentication probe, inference-only attestation). I verified on a scratch
  copy that deleting the hold alone makes the daemon refuse to start.
- The vendor's current documentation (checked today) still lists no sign-in status command; headless
  mode uses cached credentials and, when none exist in a non-interactive environment, exits with an
  authentication error instead of hanging. That exit behaviour is the only machine-checkable
  authentication signal available, and it costs one small inference per check.

## Decision 1: what to do about Gemini at all

### Option 1A: keep the hold (status quo)
- Means: nothing changes; Claude and Codex keep serving; Gemini stays a declared but held provider.
- Pros: zero owner time, zero risk, zero quota spend, fully consistent with the pipeline's safety
  contract and the accepted launch evidence.
- Cons: the Gemini subscription is unused by the pipeline; every tier 1-3 job spends about two seconds
  on a Gemini refusal once per five-minute window.
- Risks: none.
- Cost: none.

### Option 1B: enable Gemini with the installed CLI (three-phase program)
- Means: six attended sign-ins (one per worker slot), an evidence run, a relaxed identity contract
  (Decision 3), a source change, a new runtime revision, a new configuration, a controlled stop and
  restart of the Warden, one acceptance preflight.
- Pros: Gemini models become real routing candidates (a cheap flash model for small jobs, the pro
  model for hard ones); the Gemini subscription earns its keep; the design work transfers to any future
  CLI version.
- Cons: about 50 minutes of your time (six OAuth consents are unavoidable), several days of agent work
  with two review rounds, and a relaxation of the pipeline's trust boundary (Decision 3).
- Risks:
  - Technical, unknown: whether the CLI's bare interactive sign-in prints its URL-plus-code path when
    launched without a terminal under a worker token. The program starts with a five-minute discovery
    step on slot 1 and stops with evidence if it does not. If it does not, there is no login path with
    this CLI version and the program ends there.
  - Isolation evidence may be unobtainable with 1.3.1 (the only candidate mechanism is labelled
    research-only in the existing evidence), which would stop the program after Phase B.
  - A contract that validates but does not match live CLI behaviour converts a free hold into paid,
    failing Gemini dispatches; mitigated by the acceptance preflight before any real work.
  - The Warden stop is a Task Scheduler End (the daemon has no external graceful stop); safe only when
    proven idle, which the scripts check.
- Cost: owner about 50 minutes; agent days; success probability roughly even, dominated by the two
  unknowns above.

### Option 1C: defer until a newer CLI exposes the missing surfaces
- Means: keep the hold; re-run the capability evidence when a CLI release adds a sign-in status
  command, documented headless isolation flags and a serving-model field.
- Pros: no trust relaxation; the pipeline's design intent is honoured; nothing to run now.
- Cons: vendor timeline is unknown; the current changelog shows error-message improvements only.
- Risks: it may never ship; you carry the unused subscription meanwhile.
- Cost: none now; a smaller version of 1B later (the login series and evidence run would still be
  needed, the source change might not).

## Decision 2 (only under 1B): run the sign-in series while the Warden is up?

### Option 2A: Warden stays up; the series proves each slot idle before using it
- Means: the new scripts check that no job is active and take the same per-slot mutex the controller
  takes, then run the login under that slot's worker token; you do not submit work during the sitting.
- Pros: no pipeline downtime, no extra restart machinery, the sitting stays short.
- Cons: a new precondition that no earlier series used; needs its own review.
- Risks: if a job were dispatched to a slot during its login, the controller's launch would fail and
  could quarantine that slot (a reviewed recovery, not data loss). Nothing submits jobs on its own; the
  observers only record. The scripts refuse to start a slot while any job is active.

### Option 2B: stop the Warden first, as every earlier series required
- Means: Task Scheduler End when idle, run the series with the daemons disabled, then restart through
  a new reviewed attempt of the retarget mechanism (a fresh queue directory is required, so this is a
  new script variant, not a rerun).
- Pros: identical preconditions to the proven Claude and Codex series; no slot contention at all.
- Cons: pipeline downtime for the whole sitting; two extra reviewed scripts; the hard stop.
- Risks: the End terminates the process tree; acceptable only when idle, which must be checked by hand
  or script.

Recommendation: 2A.

## Decision 3 (only under 1B): what counts as proof of the serving model?

### Option 3A: strict attestation (the current contract)
- Means: require a serving-model receipt from the CLI. The CLI has none.
- Result: identical to Option 1C; Gemini stays held.

### Option 3B: accept "requested model equals the model the CLI reports; anything else fails"
- Means: a source change teaches the pipeline the CLI's envelope and treats the model name the CLI
  echoes in its init or result as the identity; any mismatch, absence or service rerouting text is a
  hard failure, as the pipeline already does for Claude's terminal output.
- Pros: the only path that enables Gemini with this CLI; consistent with how the other two providers are
  judged in practice; still fails closed on anything unexpected.
- Cons: weaker than an attestation; relies on the CLI being truthful about the model it used.
- Risks: a silent substitution by the service (a lesser model answering under the requested name) would
  be invisible; acceptance evidence for Gemini-served jobs is correspondingly weaker.

### Option 3C: 3B plus compensating limits
- Means: as 3B, and restrict Gemini to tier 1-3 (small, cheap jobs) until a quarter's worth of
  receipts shows stable behaviour; log the reported model and token usage on every job; keep the pro
  model out of routing until then.
- Pros: limits blast radius while gathering evidence; easy to widen later by configuration.
- Cons: Gemini pro stays unused for now.
- Risks: as 3B, confined to small jobs.

Recommendation: 3C if you choose 1B.

## Decision 4 (contingent): if Phase B shows tools cannot be fully disabled
The pipeline's reference allows read-only tools under strict permissions. You would then choose
between accepting read-only tools inside the isolated worker (the worker already runs under a
stripped token, job object limits, a per-slot root and a filtered environment) or stopping at that
point. I will bring you the measured evidence before asking.

## My recommendation
If the Gemini subscription matters to you, choose 1B with 2A and 3C, and let me build the whole
program before any sitting; the first five minutes of that sitting answer the biggest unknown. If it
does not matter, choose 1A; the hold is free and the pipeline is complete without it. I would not
choose 1C by itself: nothing in the vendor's current direction suggests the missing surfaces are coming.

## Sources for the vendor facts
- [Headless mode, Antigravity CLI docs](https://antigravity.google/docs/cli/headless/)
- [Antigravity changelog](https://antigravity.google/docs/changelog/)
- [Antigravity CLI releases](https://github.com/google-antigravity/antigravity-cli/releases)
- [Third-party notes on the missing login-status command](https://github.com/yanokamay-org/maiestro/issues/185)
