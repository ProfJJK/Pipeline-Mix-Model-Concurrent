# R6 attended console recovery

The owner's `r7-bundle-2d63521` run verified the existing R6 installation,
stopped R4, reused all six Codex and all six Claude sessions, and recorded six
explicit Agy sign-outs. It held at `attended_gemini_slot1` before any browser URL
or authorization prompt appeared. The owner confirmed that no prompt appeared.
R4 restore v4 verified SYSTEM identity and health. R6 was not activated, and R7
was not installed or migrated. R4 health does not prove pipeline acceptance;
its reported admission capacity was zero.

## Reproduced cause and correction

`Invoke-R6LaunchMain` captured the whole sequence's success stream in an
assignment. Windows PowerShell consequently redirected nested native stdout.
The attended bridge requires a real inherited console and refused the redirected
child before creating any preserved login root or task. No sign-in was missed.

The sequence now writes its completion result to script state. Its caller runs
it without output capture. The console guard, child process boundary, absolute
input deadline and failure recovery remain in place. Noninteractive phases still
capture their private diagnostic output intentionally.

`pipeline_tests/fixtures/r6_console_handoff_probe.ps1` parses the actual main
call site and executes it against an inert substitute sequence. Its only child
prints console metadata. It imports no deployment functions and executes no
provider, login or lifecycle operation. Under a pseudo-console the failed package
returned child exit 97 (redirected output); the correction returned exit 0 with
`inherited_console_output_redirected=False`.

**124 serialized Windows source/inert PowerShell tests passed in 39.39 seconds.**
These tests include refusal of changed historical receipts, task definitions and
unreviewed login roots/tasks. They do not attest successful real OAuth or deployment.

## Reviewed previous state

The new recovery guard accepts only the exact additional auth attempt
`56126335ff314eb497cd409fd58e6b1e` and sitting
`04883067accd48e48ca6b097296f2d93`. It binds the existing candidate and manifest,
18 authentication decisions, helper hash, exact sign-out stream hashes, terminal
private SYSTEM task and the hash-bound R4 v4 start receipt
`4b20035cdcb90d9547dbe95a1302ba7574424877dedfa7ae0db1da4d5e849852`.
Any slot1 login root or matching scheduled task still requires review. Earlier
attempts and packages are preserved; this is not an automatic retry exemption.

## Additional owner change

During this repair the owner reported Gemini Pro 3.1 removed from Agy and approved
keeping tiers 5 and 6 at their existing Claude/Codex reasoning floor, with backoff
when both are unavailable. Deployment packaging must include that separate
versioned retirement change before another owner command is delivered.
