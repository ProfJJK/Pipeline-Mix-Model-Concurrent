# R6 continuation after successful six-profile sign-in

**Owner command:** [RETURN_SETUP_R6_2026-10-13.txt](RETURN_SETUP_R6_2026-10-13.txt).
Frozen launcher `C:\Users\ansac\CoChem427\r6-launch-2571003` has 494 pinned inputs.
Launch manifest SHA-256:
`c087cf5adc962e76a288a323f7bd5a541351f2806eca0a3a40527220a15dbd7f`.
Launch tooling is source `2571003fe0f8c47461f55a1142d606f117cb318a`;
the immutable installed R6 stays source `359ca92`.

The owner requested R6 startup after all six Agy profiles passed fresh native
status checks. The original R6 runtime `359ca92` is already installed. This
continuation reuses it and does not install R7 or repeat sign-in.

The entry point binds the reviewed R4 restore v7 and the preserved terminal
registration failure `920c3ba4a0aa4c1094eaf4ce3319eba4` (never run). It also binds
the successful six-profile report `6f2553e0f3e04a1598e64ffaad1d7255`, its private
broker result, terminal task state and cleanup. Earlier artifacts are preserved.
Unknown or active attempts still stop preparation before R4 is stopped.

After preconditions it performs the controlled R4 stop, checks all 18 provider
sessions once, and runs the existing agent custody, knowledge, native selector
and migration-preview phases. A changed session produces a recorded hold and
R4 restoration; this command cannot reopen the retired terminal sign-in flow.
When authentication passes it announces that the owner can walk away. There
are no planned later prompts, downloads, restarts or continuation commands.
Only verified acceptance permits the one-shot R6 task transaction and health
check. Failures before that transaction restore R4; failures after a possible
R6 start preserve the running process and evidence for review.

## Retired Gemini Pro on the immutable R6 runtime

The original R6 configuration and captured policies still contain Pro High.
The earlier native acceptance amendment omitted its probe but did not remove
it from live dispatch. That was insufficient for an R6-only launch.

This package adds an explicit protected startup amendment,
`r6_retirement_guard.py`. Its hash and protected path are recorded in the Warden
task action and start receipt. It runs with the exact R6 interpreter/configuration
and removes only Gemini Pro identities from `RoutingPolicy.candidates` for the
life of that controller process. It also rejects retired identities in the
store's candidate-availability check, before reservation or attempt accounting.
Pre-R6 captures retain their original indices; their withdrawn candidates are
skipped at admission. The installed production `is_enabled` check
therefore also rejects a retired target captured by an earlier job. Every
surviving target, effort, order, capacity and backoff rule stays unchanged.
Tiers 5/6 have their existing two Claude/Codex choices, then back off; Flash is
not substituted. The amendment is applied on every task start, including logon.

This is a separately bound startup amendment, not a rewritten installed wheel,
changed historical policy digest or R7 hot catalog activation. The immutable
configuration/captures still describe the original catalog; the effective
retirement is identified by the task's additional guard binding. Future R7
cutover tooling must recognize this supplemented R6 task action explicitly,
rather than assume it uses the original `-m cochem_pipeline` action.

Four shared slots, six worker identities, Chapter 06 routing, original databases,
captures, credentials, R: and repair budgets are retained. The source/fixture
tests and packaged read-only plan are not SYSTEM deployment acceptance. Only
the owner's resulting R6 start and health receipts can establish deployment.

## Preparation validation

The serialized Windows/Python 3.12 selection passed **215 tests in 53.35 seconds**.
It covers the launch sequence, preserved recovery history, post-login status,
native retirement evidence, old policy indices, exact protected task action,
copy bytes/collision preservation, phase settings and package drift. The policy
filter is also exercised against the original frozen R6 routing source.
No provider, scheduled task, service or live daemon was started by these tests.
The actual frozen entry point ran without Apply in **7.00 seconds**, verified
all package inputs and returned `R6_LAUNCH_PLAN`, 26 targets, four slots,
`reuse_verified_sessions=true`, `runtime_retirement_guard=true`, and no later
prompts. No SYSTEM acceptance or startup was performed by the engineering agent.
