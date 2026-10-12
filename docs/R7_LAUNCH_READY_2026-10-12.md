# R7 owner deployment package

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
