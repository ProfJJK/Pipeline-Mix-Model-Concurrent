# Native terminal repair after the zero-output Agy attempt

The owner's exact R4 v6 recovery succeeded. The restored SYSTEM controller
passed process identity and health checks, but reported zero admission capacity.
R6 activation and R7 installation/cutover remain unverified. The b274974
deployment and the separate R4 recovery commands are spent; preserve both.

The failed native TUI used anonymous pipes and CREATE_NO_WINDOW. It emitted
zero bytes, received no code and timed out after 601.436 seconds. That evidence
does not identify a Google rejection. The new implementation supplies an owned
Windows pseudoconsole and selects the native manual Google consent path. It
does not implement an OAuth client, exchange tokens itself or copy credentials.
Actual native authorization remains an owner-run host acceptance requirement.

## Sources and implementation

[Microsoft's pseudoconsole documentation](https://learn.microsoft.com/en-us/windows/console/creating-a-pseudoconsole-session)
requires attaching HPCON through the startup attribute and draining output
during teardown. `attended_agy_terminal.py` creates the console before its child,
starts the output pump first, uses the HPCON value in the startup attribute and
keeps draining while ClosePseudoConsole finishes. Both worker and console cleanup
must pass before releasing the retained worker identity reservation.

[Google's installation/authentication documentation](https://www.antigravity.google/docs/cli/install/)
describes native browser authentication and manual URL/code authentication in
remote sessions. Static inspection of the exact pinned Agy binary also finds
its SSH environment checks and selected Google OAuth menu. The attended-only
launcher sets one fixed transport hint in the existing sanitized worker
environment; it opens no SSH connection and accepts no operator environment
override. Normal job launch is unchanged. This explains the implementation
choice; it does not establish that transport was the sole cause of the failure.

The native child is created suspended under the selected isolated worker token,
assigned to the existing limited Job before resume, and verified by image,
token, process creation time and Job membership. There is no shell, arbitrary
argv, inference prompt or API-key fallback. Only the native selected Google
menu can receive one public Return; unknown screens receive no navigation.
Terminal capability queries have fixed bounded responses; clipboard commands
and arbitrary terminal controls are never relayed to the operator console.

The owner sees only the fresh URL from this native process. Input stays locked
until that URL precedes its authorization-code prompt. Earlier keys are
discarded except Escape. The code is masked, submitted once with one terminal
Return, and never persisted in output. The terminal input remains open during
the native exchange. After native success text and token-presence metadata,
the owned idle TUI can end; this is not authentication proof. A separate fresh
native status check must verify the session before deployment continues.

Startup without output holds after 30 seconds; an unrecognized consent screen
holds after 60 seconds. Slow exchanges retain the existing post-input bound.
Every requested code must fit the outer sitting's original 20-minute deadline.
No late prompt, automatic retry, reset of sign-ins or reboot is introduced.

## Historical state and failure reports

The recovery verifier binds the exact zero-output task/receipt, absent input,
unchanged helpers, reviewed stop v5 and the independently verified v6 retarget
and start receipts. An absent outer completion record is never treated as
rollback. Unknown additional attempts or changed evidence hold for review.
Earlier source, tasks, receipts and immutable packages remain unchanged.

New terminal tasks use a separate protected namespace. Private receipts retain
the full custody evidence. Each owner sitting also gets a readable sanitized
projection containing only bounded phase/reason enums, receipt digest and
cleanup flags. It excludes provider output, URLs, codes and free exception
text. A failed terminal session is preserved and is not automatically repeated.

## Verification and limits

Two disjoint serialized ordinary Windows/Python 3.12 selections passed
**501 source/inert tests**: 246 transport, recovery and package tests (four
protected-host skips), and 255 routing, catalog, migration, launch and native
acceptance fixtures. No real-process cleanup tests were executed. The fixtures
inject native APIs and temporary stores; they do not create a pseudoconsole,
run Agy, elevate, edit protected state or start/stop a task.

The final immutable package is `r7-bundle-534e7fe`. Its 308 installer inputs and
484 prerequisite inputs passed hash/size verification. Four packaged read-only
plans passed in 2.969 seconds, and the actual packaged call site passed its
metadata-only console probe. Bindings and delivery evidence are recorded in
`R7_LAUNCH_READY_2026-10-12.md`. Those plans are not SYSTEM, native OAuth,
model or full SRS acceptance. R4 v6 recovery is the latest actual host evidence.
