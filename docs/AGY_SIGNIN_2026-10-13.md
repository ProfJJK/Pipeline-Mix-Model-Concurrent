# Standalone Agy sign-in for the six pipeline profiles

The owner requested a short, URL-only sign-in script independent of R6/R7
deployment. `scripts/signin_agy_profiles.ps1` stages one small SYSTEM broker
and handles the six existing Agy profiles sequentially. It prints each fresh
Google URL for manual opening, accepts one masked authorization code, and
verifies that profile with a new native catalog-status command. Already
authenticated profiles are reused. It does not open a browser or deploy R6/R7.

## Why the latest run failed

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
