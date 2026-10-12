r"""Realistic Task Scheduler read-back of a task's security descriptor for the inert PS5.1 fixtures (r5 sitting v3 repair).

Before 2026-10-11 every fixture that modelled ITaskFolder.RegisterTaskDefinition + IRegisteredTask.GetSecurityDescriptor
returned the SDDL the caller requested, verbatim. On AETHERDESK the service does not: the r5 sitting v2
(r5-sitting-20261011-202738.log) held all 14 one-shot SYSTEM registrations (12 status checks, the agy capture, the upgrade
preview) with 'Registered task ownership/private DACL differs.' from the exact validator Assert-RegisteredTaskAcl
(register-stopped-warden-r3.ps1, sha256 eccc593f...), and no fixture could see it. The fixtures now ask this model.

Host evidence (Windows 10.0.26300, Windows PowerShell 5.1.26100.9444, schedsvc.dll 10.0.26100.8457), flag values from
taskschd.h (TASK_CREATE 0x2, TASK_UPDATE 0x4, TASK_DONT_ADD_PRINCIPAL_ACE 0x10):
  * TASK_CREATE without 0x10 (flags 2): the requested owner and group, the DACL without its P (protected) flag, and an
    appended (A;;FR;;;<principal>) ACE (FR = 0x120089 = 1179785) for the task principal. SYSTEM:
    C:\Program Files\CoChem\TaskAclRecovery4.2.7-windows-20261008-r3-v1\original-warden.sddl
    = 'O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;SY)' and pending-warden-recovery-v7-preparation-20261008.json
    (owner-observed SYSTEM task: SY FA, BA FA, SY FR, unprotected); ordinary user: observations[0] of
    task-scheduler-acl-roundtrip-r3-v1-bbd9bf8061764e6ba8cdefa47fb6a149-final.json.
  * TASK_CREATE | TASK_DONT_ADD_PRINCIPAL_ACE (flags 18): exactly the requested ACEs, as 'D:PAI'. Ordinary user:
    observations[1] of the same round trip; SYSTEM: the elevated registration of resume-pending-warden-r3-v7.ps1:125 on
    2026-10-09T02:16Z (TaskAclRecovery4.2.7-windows-20261008-r3-v1\recovery-intent.json registration_flags 18) passed the
    exact validator and ran; the 'PAI' form 'O:BAG:BAD:PAI(A;;FA;;;SY)(A;;FA;;;BA)' passed it again on 2026-10-11
    (WardenRetarget4.2.7-windows-20261011-r4-v1\warden-task-before.sddl).
TASK_UPDATE (4) re-registrations of an existing task with its captured SDDL keep that SDDL on this host (retarget-warden-r4
on 2026-10-10, retarget-warden-r5 -Target r4 on 2026-10-11); the retarget fixtures keep their own stubs and are not
modelled here.

Use PS_FUNCTION in a fixture's PowerShell text and call Get-HostTaskSddlProjection $flags $sddl $user from the
RegisterTaskDefinition stub; GetSecurityDescriptor returns its result. host_projection() is the Python mirror.
"""
import re

TASK_CREATE = 0x2
TASK_UPDATE = 0x4
TASK_DONT_ADD_PRINCIPAL_ACE = 0x10
# The reviewed one-shot registration flags (create-only, no principal ACE): 18.
TASK_CREATE_WITHOUT_PRINCIPAL_ACE = TASK_CREATE | TASK_DONT_ADD_PRINCIPAL_ACE
PRIVATE_TASK_SDDL = 'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'
HOST_SDDL_AFTER_FLAGS_2 = 'O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;SY)'
HOST_SDDL_AFTER_FLAGS_18 = 'O:BAG:BAD:PAI(A;;FA;;;SY)(A;;FA;;;BA)'
HELD_ACL_REASON = 'Registered task ownership/private DACL differs.'
FLAGS_CONSTANT = '$script:taskRegistrationFlags'

_REQUESTED = re.compile(r'O:(?P<o>[A-Z]{2}|S-1-[0-9-]+)G:(?P<g>[A-Z]{2}|S-1-[0-9-]+)D:(?P<f>[A-Z]*)(?P<a>(?:\([^()]*\))+)')

PS_FUNCTION = r'''
function Get-HostTaskSddlProjection {
  # Fixture model of the AETHERDESK Task Scheduler read-back (task_scheduler_host_projection.py): without
  # TASK_DONT_ADD_PRINCIPAL_ACE (0x10) the DACL loses its protection and gains (A;;FR;;;<principal>); with 0x10 it keeps
  # exactly the requested ACEs as D:PAI.
  param($Flags,[string]$Sddl,[string]$User)
  if($Sddl -cnotmatch '^O:(?<o>[A-Z]{2}|S-1-[0-9-]+)G:(?<g>[A-Z]{2}|S-1-[0-9-]+)D:(?<f>[A-Z]*)(?<a>(\([^()]*\))+)$'){throw ('Unmodelled requested task SDDL: '+$Sddl)}
  $owner=$Matches['o'];$group=$Matches['g'];$aces=$Matches['a']
  if(([long]$Flags -band 0x10) -ne 0){return ('O:'+$owner+'G:'+$group+'D:PAI'+$aces)}
  if($User -ceq 'SYSTEM' -or $User -ceq 'S-1-5-18'){$principal='SY'}
  elseif($User -cmatch '^S-1-5-21-[0-9]+(-[0-9]+)+$'){$principal=$User}
  else{throw ('Unmodelled task principal: '+$User)}
  'O:'+$owner+'G:'+$group+'D:'+$aces+'(A;;FR;;;'+$principal+')'
}
'''


def host_projection(flags, sddl, user='SYSTEM'):
    """Python mirror of Get-HostTaskSddlProjection."""
    match = _REQUESTED.fullmatch(sddl)
    if not match:
        raise ValueError(f'unmodelled requested task SDDL: {sddl}')
    head = f"O:{match.group('o')}G:{match.group('g')}D:"
    if int(flags or 0) & TASK_DONT_ADD_PRINCIPAL_ACE:
        return head + 'PAI' + match.group('a')
    if user in ('SYSTEM', 'S-1-5-18'):
        principal = 'SY'
    elif re.fullmatch(r'S-1-5-21-[0-9]+(-[0-9]+)+', user or ''):
        principal = user
    else:
        raise ValueError(f'unmodelled task principal: {user}')
    return head + match.group('a') + f'(A;;FR;;;{principal})'
