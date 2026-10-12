# R7 owner deployment package

## Current replacement: attended console repair and owner Pro retirement

Use the updated `docs/deployment/windows-deployment-next/RETURN_SETUP_R7.txt`.
It names fresh source `e32949a24302622d528538afa5d57cd9107cef5a` and immutable
bundle `C:\Users\ansac\CoChem427\r7-bundle-e32949a`. The owner has not run it.
Earlier packages, failed attempts and installed R6 remain unchanged.

The last `2d63521` attempt held before any Agy prompt because the sequence caller
captured native console output. That was reproduced and repaired; the owner did
not miss a sign-in. R4 restore v4 verified SYSTEM/native health. Twelve existing
Codex/Claude sessions were reused, six Agy profiles explicitly reported signed
out, and no R6 activation or R7 install/cutover was attempted. See
[console evidence and repair](R6_CONSOLE_RECOVERY_2026-10-12.md).

The owner then withdrew Gemini Pro and approved existing Claude/Codex choices
plus backoff at tiers 5 and 6. This package includes the separately reviewed
[retirement amendment](R6_PRO_RETIREMENT_2026-10-12.md) and
[readable matrix](routing/4.2.7-routing-v4.owner-matrix.md). The R6 one-shot native
check probes 26 remaining targets and explicitly records Pro unprobed. R7
publishes `owner-2026-10-12-pro-retired`; old captures and the installed R6
configuration are not rewritten. R6 is temporarily its original runtime until
R7 publication; a pre-cutover hold does not pretend retirement was activated.

| Fresh artifact | Binding |
| --- | --- |
| Source freeze | `r7-source-e32949a`, 198 files, 6,718,490 bytes |
| Source manifest SHA256 | `6ef293902b607e7c7584d3d7e3fa32b219d6d9e71bc715fc20210c3e012d3e5b` |
| Verified application wheel | `r7-build-e32949a`, 1,103,364 bytes, 178 files |
| Wheel SHA256 | `0cdc264effedc76b9cd9838c1a64da25b7bc44ff2492e6455335b5052111e528` |
| Owner bundle | `r7-bundle-e32949a`, 307 installer inputs |
| Launch manifest SHA256 | `c74e7fc163c9637c033bc26891af0a995f7338979b78afa9daeeab46517cb72f` |
| Copied R6 prerequisite | 481 pinned inputs; manifest `918f47ca273d51bbbd36c0378efb73ef5903c1321359ae2095d9604c11f4bf95` |
| R7 install manifest SHA256 | `269069c6f4c60fac33143e2a15dc115b3033cc723ba25086f16502cb8e57d327` |

Compared with the failed `2d63521` prerequisite, 476 of its 480 inputs remain
byte-identical and verified. Four reviewed scripts change; the one pinned
retirement helper is added. The 106 locked Windows/Python 3.12 runtime wheels
are reused after input binding checks. This new wheel contains the two-choice
catalog parser/routing change and is deliberately different from the old wheel.

The final retirement/routing/catalog selection passed **365 source/inert tests**,
with two real-process tests deselected, in 26.75 seconds. The final launch,
authentication, runner, migration and controller fixture selection passed
**143 tests** in 31.05 seconds. The selections overlap and are not a distinct-test
total. All three actual packaged **read-only** plans passed. One nested installer
plan first failed to autoload Windows' security module in the test environment;
the direct ordinary-account module import and actual installer plan passed.
No production package change or elevation was needed for that diagnosis.

The final packaged production call site passed the pseudo-console regression:
`inherited_console_output_redirected=False`, child exit 0. Its child reads only
console metadata and imports no deployment/provider functions. The preserved
failed call site returned exit 97. Sanitized source/package evidence is saved in
`docs/deployment/windows-deployment-next/R7_E32949A_PACKAGE_EVIDENCE.json`.

All planned active input remains in the first 20 minutes. Existing sessions are
reused, any requested six Agy logins occur at the beginning, and the green
walk-away message precedes native acceptance and installation. No timing promise
for provider authorizations follows from fixtures. Later failures hold and
preserve evidence without asking for input. No Apply, SYSTEM/native deployment
acceptance or full SRS acceptance was run by engineering.

The sections below are historical; their commands and previous claims about
Gemini Pro retention or byte-identical application wheels are superseded.

## Historical replacement: persisted R4 receipt repair

The owner ran `r7-bundle-c3080c9`. Its R6 verification failed on an invented
`started` field before stopping R4 or running providers. The error is confirmed
by the owner's private-log excerpt and reproduced using the production receipt
writer. See [the failure, repair and evidence](R6_RESTORE_RECEIPT_RECOVERY_2026-10-12.md).

The current owner sheet is `docs/deployment/windows-deployment-next/RETURN_SETUP_R7.txt`.
It points to source `2d63521cb2d4c4084c81f9fce75de615c5d33c8d` and immutable bundle
`C:\Users\ansac\CoChem427\r7-bundle-2d63521`, with launch manifest SHA256
`196d4e71658b427d3c832f4d4a929209ba35075277acaf7087da87497c6367ee`.
Only the recovery receipt verifier differs among the 480 prerequisite inputs
from the failed package. **109 source/inert tests passed** and all three actual
packaged read-only plans passed in 9.98 seconds. The application wheel remains
byte-identical; repaired host acceptance is still pending owner execution.

All subsequent package descriptions below are historical and their commands
are superseded. The initial 20-minute input window and unattended continuation
remain unchanged.

## Replacement after the owner's R6 prerequisite hold

The owner ran the earlier package below. R6 authentication held because the
status checker omitted the native `Error: ` sign-out prefix; R4 restore v3 was
health verified and no R7 installation or cutover was attempted. See
[the exact Windows evidence and repair](R6_AGY_PREFIX_RECOVERY_2026-10-12.md).

Use the updated `docs/deployment/windows-deployment-next/RETURN_SETUP_R7.txt`.
Replacement source is `c3080c9631b58252a31cc3fe38da9f131e4f7787`;
fresh bundle is `C:\Users\ansac\CoChem427\r7-bundle-c3080c9`, with 307 installer
inputs and all 480 copied R6 prerequisite inputs. Only the two reviewed recovery
helpers and the inherited-deadline launch entry differ from the original R6
recovery. Prior immutable staging roots remain untouched.

Replacement launch manifest SHA256:
`7f68c8b54a7d10df8b725ee2efc8321941d59ee10b41586c6c2a99dbb0c29f40`.
Source manifest SHA256:
`107d9943b30d7c7c4194459685ca524e4bf8d717f8a9d75dfbe1c60cb09b2736`.
The verified application wheel remains byte-identical:
`8bb9c33b35228df23bc23fb5f4b4b0f1aae61d6a3a657c63a3bd660dbb636c1d`.
All three replacement packaged read-only plans passed in 9.37 seconds; 93 focused
source/inert PowerShell tests passed. These are not repaired host acceptance.

The six isolated Agy profiles require browser sign-in. Existing Codex/Claude
sessions are reused; all requested input remains inside the initial 20-minute
window. No timing guarantee for six provider authorizations is inferred from
source tests. A closed input window holds rather than prompting later.

The sections below preserve the initial package record and its earlier tests;
its command is superseded.

R7 coding and non-administrator preparation are complete. Source commit:
`70af5692399068814bc115af802ff7baec13e8a7`. The initial source/runtime integration
is `b9ba102`; `70af569` adds the temporary thread-scoped awake request for this
unattended owner sitting. All earlier R6 and R7 staging folders remain unchanged.

The owner has one command in
`windows-deployment-next/RETURN_SETUP_R7.txt`. The versioned copy is in
`docs/deployment/windows-deployment-next/RETURN_SETUP_R7.txt`. It front-loads UAC
and any necessary R6 authentication, clamps that recovery to the outer sitting's
first 20 minutes, then requests no more input. Total unattended time can be much
longer; no total-runtime promise is made from source tests. The owner can leave
after the green walk-away message and keep using the workstation normally.

## Exact offline inputs

| Artifact | Local path / binding |
| --- | --- |
| Source freeze | `C:\Users\ansac\CoChem427\r7-source-70af569`, 198 files, 6,717,431 bytes |
| Source manifest SHA256 | `7db5f8cdf3c84f10db7eb7e787d87c7207488a25ee78aa974b6c53bd66afe98e` |
| Application build | `C:\Users\ansac\CoChem427\r7-build-70af569` |
| Verified wheel SHA256 | `8bb9c33b35228df23bc23fb5f4b4b0f1aae61d6a3a657c63a3bd660dbb636c1d` |
| Owner bundle | `C:\Users\ansac\CoChem427\r7-bundle-70af569`, 307 installer inputs |
| Launch manifest SHA256 | `91ed05ee223f1ab2f867b492095a07d135248098bc5ce07a9727ac7acee5f435` |
| Planned installed runtime | `C:\Program Files\CoChem\Pipeline4.2.7-windows-20261012-r7-v1` |
| Preserved DB backup/evidence | `C:\ProgramData\CoChemPipeline427\private\r7-migration-20261012-v1` |
| Protected catalog authority | `C:\Program Files\CoChem\RoutingCatalog4.2.7` |

The bundle includes the already verified 106 Windows/Python 3.12 dependency
wheels. No installation download or build is deferred to the owner sitting.
Its `r6-prerequisite` child contains all 480 verified recovery inputs copied
from `r6-auth-recovery-eb982cb`. Only the copied launch entry changes, to inherit
the outer input deadline. The delivered original recovery remains immutable.
If completed R6 already exists, no recovery or repeated sign-in is invoked.

## Transaction and recovery

Before the R7 stop, the entry requires completed R6 acceptance and matching
configuration, protected code/interpreter, SYSTEM health, the exact running task
and private task ACL. It installs R7 stopped, waits for idle work and native
cleanup, and holds both existing controller/launcher identities against PID
reuse. Task edits preserve the original security descriptor and every definition
field outside the reviewed action/enabled flags. R: and its task are not edited.

The SYSTEM migration takes a full backup and proves that all original tables and
rows remain unchanged. Initial protected authority preserves the exact matrix
and changes only generation identity. The R7 Warden uses one existing native
selector as its control probe, within the four shared slots and existing provider
limits. Successful cleanup and publication must bind the expected request and
candidate policy digest. New submissions adopt the published generation; old
captures remain intact. The feature has no HTTP activation endpoint.

Before any R7 start, a failed transaction can restore the database and original
R6 task only when migration completion and unchanged original records are proved.
An uncertain migration or requested R7 start preserves possibly running state
instead of resetting it. No failed request is automatically repeated. Backup,
tasks, prior roots and native captures remain available for review.

Readable sanitized status files are printed under a fresh `R7Sitting...` folder.
Private model logs and migration data stay private. The temporary awake request
does not change a power plan and is released in `finally` or process exit.

## Verified evidence and remaining host work

The complete serialized Windows/Python 3.12 selection passed **330 tests**, with
one protected SYSTEM-metrics skip and two real-process cleanup deselections, in
48.52 seconds. After adding wakefulness, the final owner-package selection passed
**16 tests** in 6.09 seconds, including two additional fake-native cases. The
runtime wheel stayed byte-identical after that script-only change.

Actual packaged R7, copied R6 prerequisite and stopped R7 installer **read-only
plans all passed**, combined 9.00 seconds. Their output recorded four slots,
27 R6 native targets, 307 R7 installer inputs and no late prompts. This measures
package checking only; it is not an attended deployment timing measurement.

Review occurred in this one engineering session using failure-path fixtures and
the actual final packaged plans; no second engineering session/subagent ran.
No Apply, elevation, task/lifecycle action, power request, provider execution or
protected database write was performed by engineering. Linux results do not
satisfy these Windows gates. The latest readable host report still records the
first R6 recovery failure at 14:13 UTC, before R4 stop; corrected R6 recovery and
R7 deployment are not yet attested. Owner execution remains necessary.
