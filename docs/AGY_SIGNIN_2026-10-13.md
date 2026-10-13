# Standalone Agy sign-in for the six pipeline profiles

## Successful host run and owner preference

**The owner subsequently extended this preference to Codex and Claude as well
as Agy.** See [the shared sign-in standard](SIGN_IN_PREFERENCE_2026-10-13.md),
including the different direction of Codex's device code.

The owner ran `agy-signin-c4d4a66` and explicitly asked to retain this interaction
for future sign-ins, describing it as easy to use. The preferred
flow is **Copy URL -> open manually -> paste authorization code into the standard
masked Windows dialog with Ctrl+V -> Submit/Enter**. Process the six profiles in
sequence, verify each, and reuse sessions that are already authenticated. Retain
this user interface and implementation; do not return to browser auto-launch,
native TUI navigation or raw console-key collection. Signing in remains separate
from deployment. Future attempts obtain fresh native URLs and codes.

Actual owner-run result: **ALL_SIX_AGY_PROFILES_VERIFIED**. All six profiles report
`SIGNED_IN_AND_VERIFIED`, authenticated true, native post-login catalog decision
`VERIFIED` with exit code 0, submitted input deleted, and worker/terminal cleanup
verified. The native login sessions themselves ended with code 1; authentication
is established by the subsequent fresh status checks, not by treating that login
exit code as success. Setup before the profile sequence took **78.9 seconds**;
the transcript does not establish total user-input or end-to-end elapsed time.

The sanitized protected report was independently read without elevation:
`C:\Program Files\CoChem\AgySignIn427-6f2553e0f3e04a1598e64ffaad1d7255\status.json`.
SHA-256: `96e4d2a872ff64a265efde9f1d1dade42db73f9da85863befc93692ece7ccfff`.
It records zero native model jobs, no daemon-task changes, no copied credentials
and activation_ready false. This is real six-profile Agy authentication evidence;
it does not establish R6/R7 deployment or model/effort acceptance. No new sign-in
is required from the owner now. Preserve all successful and failed artifacts.

## Latest repair: native prompt wording and ordinary copy/paste

The owner ran `agy-signin-b048393`. Agy 1.3.1 successfully produced a fresh
Google URL, followed by **"After authenticating, copy the code displayed in
the browser and paste it below:"** and the **"authorization code..."** field.
The wrapper expected different words, never enabled input, discarded keys,
and expired at 60 seconds with `FRESH_GOOGLE_PROMPT_NOT_OBSERVED`.
The `shift+up/down Navigate` footer was native TUI output, not usable owner
controls. No code was submitted. The public receipt confirms worker and
terminal cleanup. This was a wrapper recognition defect, not a demonstrated
Google authorization failure.

Reviewed attempt: `AgySignIn427-29d5943c97954a7695d57c722e917cd2`.
Public `status.json` SHA-256:
`a2d3cf3bbaf19f6917ac3826f3fc4bc3774f9fc327e24419e2cf0cb0449ccfa0`.
The replacement verifies that exact receipt, ended task, private input-closed
marker receipt and cleanup before permitting a fresh namespace. It preserves
the old task, files and package. Other failed or active brokers still hold.

The native parser now recognizes the observed wording, including split output
and redraws. It emits one private, nonce/slot-bound `prompt-ready.json` only
after the fresh Google URL and code field are recognized. The owner interface
uses that signal instead of implementing a second prompt regex. A standard
Windows dialog provides a read-only selectable URL, an explicit **Copy URL**
button, a masked **PasswordBox** with ordinary paste/selection, **Submit** and
**Cancel**. There are no custom key handlers or raw console-key polling. The
browser still must be opened manually; neither opening the dialog nor copying
the URL opens a browser. Authorization codes go directly from SecurePassword
to the existing private packet writer, never to PowerShell history or logs.
Closing the dialog or its deadline cancels; a timer also closes it when the
native input window ends. Both boundaries are checked again before sending.

168 serialized source/inert Windows fixtures passed in 24.38 seconds; all 37
owner-interface fixtures passed again in 14.29 seconds after final styling.
They exercise the exact captured
prompt wording with synthetic URLs, bytewise chunking, stale/partial/foreign
prompts, one private readiness signal, actual WPF controls without showing a
window, expiry/closed-input refusal, preserved reviewed failure and one code/CR
through the real parser/read loop with an in-memory terminal. An offscreen
render verified that all dialog controls fit. These tests do not constitute
native Google sign-in acceptance. The owner run measured **96.3 seconds**
before profile sign-in, so the older 6.913-second read-only measurement below
must not be represented as end-to-end setup timing or a one-minute guarantee.

The replacement command/package are recorded in `AGY_SIGNIN_READY.txt` and
the deployment workspace's `SIGN_IN_AGY.txt`. Do not rerun b048393.

The owner requested a short, URL-only sign-in script independent of R6/R7
deployment. `scripts/signin_agy_profiles.ps1` stages one small SYSTEM broker
and handles the six existing Agy profiles sequentially. It prints each fresh
Google URL for manual opening, accepts one masked authorization code, and
verifies that profile with a new native catalog-status command. Already
authenticated profiles are reused. It does not open a browser or deploy R6/R7.

## Earlier deployment registration failure

The owner ran `r7-bundle-534e7fe`. Its new terminal task held in `register` with
`MethodInvocationException` and `run_requested=false`: Agy was never started.
The wrapper passed the task COM object to `Assert-RegisteredTaskAcl`, whose
parameter is an SDDL string. The constructor consequently rejected the object's
string representation. The regression reproduces this error using the actual
permissions validator; reading `Task.GetSecurityDescriptor(7)` fixes it.
This establishes the wrapper defect, not a failed Google authorization.

The owner's supplied result confirms successful R4 restoration as v7:
start receipt `449bff46b15018e1ff47e389c5765df49f86b4cee36e3b1c8778390568e4cf97`,
retarget receipt `80c50e6272940fe89bf53e2c01e9c38481ab6b1e32b7392d4c7946fed1c29d67`.
It reported zero admission capacity. R6 never activated and R7 never installed.
The 534e7fe deployment command is spent. Preserve all earlier roots/tasks.

## Authentication boundaries

This is a separate account-maintenance command. It leaves Warden running and
does not import deployment orchestration, stop services, open application
databases, modify repair budgets, or change the four shared execution slots.
Authentication uses one additional **non-inference** native Job at a time,
capped at 512 MiB, 5% CPU, four processes and verified efficiency cores. These
limits apply only to this broker's authentication/status children, not pipeline
configuration. Normal compute routing and capacity remain unchanged.

Every native operation uses the installed unprivileged worker token, existing
profile and the same exclusive SID reservation used by normal workers. A busy
profile is refused; it is never interrupted or logged out. The broker obtains
no arbitrary executable, arguments, environment, source code or model prompt
from the console. No credentials are copied between profiles. SYSTEM access is
necessary because the provisioned worker passwords are in SYSTEM Credential
Manager. The owner starts the prepared command in Administrator PowerShell.

One package verification and installed-code custody walk precedes the broker.
The native helper retains the prior ConPTY transport: a fixed manual-Google
environment hint, native Google menu selection only, a prompt following a fresh
Google URL, one code followed by **one CR**, input kept open during exchange,
and verified worker/console cleanup before a separate status command. The
[official Agy documentation](https://www.antigravity.google/docs/cli/install/)
describes the remote URL/code flow used by this transport. The helper does not
implement an OAuth client or exchange an authorization code itself.

Raw provider output after code submission is never published. Codes use a
private create-only input packet, removed after verified cleanup. Public status
contains only phase, fixed classifications, hashes, source locations and numeric
errors. It contains no code, URL, account identity, credential or document text.
Unknown catalog errors do not trigger login. Failed or cancelled sign-in stops
the sequence; there is no retry or automatic advance to another profile.

All prompts fall within 20 minutes of command start. Completion/cleanup may run
after the last input. Neither deployment nor any later attended phase follows.
On completion the owner can close the PowerShell window after the final result.
The task and receipts remain for subsequent R6/R7 evidence review. They do not
authorize re-running a spent deployment package.

## Testing and timing

141 serialized Windows/Python 3.12 source and inert PowerShell fixtures passed
in 15.60 seconds. They cover actual SDDL validation, task definition readback,
six sequential status/login/status transitions, existing-session reuse, unknown
status, cancellation/deadlines, fresh-URL gating, a pasted code containing Q,
one CR, short writes, secret suppression, Job/console cleanup and package pins.
The broker login test uses the real bridge read loop and output parser with an
in-memory terminal; it does not run Agy or create a Windows pseudoconsole.

A separate **actual read-only** run of the package imports, R4 bindings and
protected code-tree inspection finished in **6.913 seconds**. It inspected
15,014 runtime entries, 3,727 Python entries and six native-root entries,
verified the 166 frozen source files and 109 installed assets, and performed
zero task operations or provider commands. This measures the initial custody
checks, not SYSTEM startup, network latency or Google's six consent screens.
Total completion in one minute cannot be guaranteed before the owner run.

No agent-side Apply, elevation, native provider execution or host lifecycle
operation occurred. Actual Google authorization remains unverified until the
owner uses this command; fixture counts must not be presented as host success.

The reproducible package builder is `scripts/prepare_agy_signin.py`. Its fresh
output contains 16 pinned files plus the manifest. Final package location,
manifest digest and the owner command are recorded in `AGY_SIGNIN_READY.txt`
and the deployment workspace's `SIGN_IN_AGY.txt` after source commit.
