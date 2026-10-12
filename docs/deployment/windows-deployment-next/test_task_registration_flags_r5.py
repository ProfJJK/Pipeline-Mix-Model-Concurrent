r"""Registration flags of every sitting-reachable one-shot SYSTEM task (r5 sitting v3 repair, 2026-10-11).

The r5 sitting v2 (r5-sitting-20261011-202738.log) held all 14 one-shot SYSTEM registrations (12 S3 status checks, the
S5 agy capture, the S10 upgrade preview) at the exact Assert-RegisteredTaskAcl read-back (register-stopped-warden-r3.ps1,
sha256 eccc593f...): with TASK_CREATE alone (flags 2) this host's Task Scheduler stores the task DACL unprotected with an
appended (A;;FR;;;SY) principal ACE. The repair proven on this host on 2026-10-08 (resume-pending-warden-r3-v7.ps1:125,
TaskAclRecovery4.2.7-windows-20261008-r3-v1) is flags 18 = TASK_CREATE | TASK_DONT_ADD_PRINCIPAL_ACE with the exact
validator kept; the five scripts that read back with that validator now register through $script:taskRegistrationFlags=18.

Static and inert: scripts are only parsed (PowerShell AST; nothing is run), the fixture host model
(task_scheduler_host_projection.py) is checked against the recorded host evidence, and the real validator is dot-sourced
from the AST of its pinned file. No task is registered, read or changed.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

import pytest

import task_scheduler_host_projection as hostacl

W = Path(__file__).parent
PS = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
RUNNER = 'RUN_427_R5_SITTING.ps1'
REGISTER = W / 'register-stopped-warden-r3.ps1'
REGISTER_SHA256 = 'eccc593f36cbf488a54775b4343bcf3cf8b261b7cd81e5536fb7f2f18466a198'
ROUND_TRIP = W / 'task-scheduler-acl-roundtrip-r3-v1-bbd9bf8061764e6ba8cdefa47fb6a149-final.json'
PENDING_V7 = W / 'pending-warden-recovery-v7-preparation-20261008.json'
COCHEM = Path(r'C:\Program Files\CoChem')
ORIGINAL_WARDEN_SDDL = COCHEM / 'TaskAclRecovery4.2.7-windows-20261008-r3-v1' / 'original-warden.sddl'
RECOVERY_INTENT = COCHEM / 'TaskAclRecovery4.2.7-windows-20261008-r3-v1' / 'recovery-intent.json'
RETARGET_BEFORE_SDDL = COCHEM / 'WardenRetarget4.2.7-windows-20261011-r4-v1' / 'warden-task-before.sddl'
TASKSCHD_H = Path(r'C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\um\taskschd.h')

# The create-only registrations that read the descriptor back with the exact validator (sitting stage in the comment).
REPAIRED = {
    'check-worker-native-auth-status-six-r4-v1.ps1',    # S3 status checks; S3 attended and S6 series via login-six
    'agy-status-capture-r4-v1.ps1',                     # S5 signed-out, S7 signed-in
    'login_pipeline_worker_interactive_agy_r4_v1.ps1',  # S6 Gemini sign-in
    'agy-isolation-evidence-r4-v1.ps1',                 # S8 evidence and -StageOnly
    'run-upgrade-preview-r5-v1.ps1',                    # S10 (and the F3 second preview)
}
# TASK_UPDATE (4) of the existing Warden task with its own captured SDDL: preserved on this host (2026-10-10 r4 retarget,
# 2026-10-11 R4-RESTORE through retarget-warden-r5 -Target r4); not a create, so no principal ACE question.
TASK_UPDATE_SITES = {'retarget-warden-r5.ps1': 2, 'retarget-warden-r4.ps1': 1}
# Files the sitting only imports reviewed definitions from (by hash); their own registration function is never run.
IMPORT_ONLY = {'register-stopped-warden-r3.ps1': 'Invoke-StoppedWardenRegistration'}
# Registrations without any exact read-back (out of scope of this repair; no validator to hold them).
NO_EXACT_READ_BACK = {'check-worker-denials.ps1', 'check-worker-native-status-r3.ps1', 'login_pipeline_worker_interactive_r3_v6.ps1'}


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PINS = load(W / 'refresh-r5-sitting-pins.py', 'refresh_r5_sitting_pins_for_flags')
REACHABLE = sorted({name for name in PINS.PIN_NAMES if name.endswith('.ps1')} | {RUNNER})


def psq(value):
    return str(value).replace("'", "''")


def ps(code, timeout=180):
    prefix = ("$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;"
              "foreach($m in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME \"Modules\\$m\\$m.psd1\")};")
    result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-Command', prefix + code], capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line for line in result.stdout.splitlines() if line.startswith('RESULT ')]
    assert lines, result.stdout + result.stderr
    return json.loads(lines[-1][len('RESULT '):])


def scan(names):
    """Every RegisterTaskDefinition call of each file (arguments, enclosing function), its exact-validator calls and the
    assignments of the flags constant, read from the PowerShell AST."""
    listing = ','.join(f"'{psq(name)}'" for name in names)
    code = (f"$out=@();foreach($name in @({listing})){{$path=Join-Path '{psq(W)}' $name;$t=$null;$e=$null;"
            "$a=[Management.Automation.Language.Parser]::ParseFile($path,[ref]$t,[ref]$e);if($e.Count){throw ('parse failure: '+$name)};"
            "$sites=@(foreach($c in $a.FindAll({param($n)$n -is [Management.Automation.Language.InvokeMemberExpressionAst] -and $n.Member.Extent.Text -ceq 'RegisterTaskDefinition'},$true)){"
            "$f=$c.Parent;while($null -ne $f -and $f -isnot [Management.Automation.Language.FunctionDefinitionAst]){$f=$f.Parent};"
            "[ordered]@{line=$c.Extent.StartLineNumber;arguments=@($c.Arguments|ForEach-Object{$_.Extent.Text});function=$(if($null -ne $f){$f.Name}else{$null})}});"
            "$validator=@($a.FindAll({param($n)$n -is [Management.Automation.Language.CommandAst] -and $n.GetCommandName() -ceq 'Assert-RegisteredTaskAcl'},$true)).Count;"
            "$assign=@($a.FindAll({param($n)$n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -ceq '" + hostacl.FLAGS_CONSTANT + "'},$true)|ForEach-Object{$_.Right.Extent.Text});"
            "$out+=[ordered]@{name=$name;sites=$sites;validator_calls=$validator;assignments=$assign}};"
            "'RESULT '+(ConvertTo-Json @($out) -Depth 6 -Compress)")
    return {row['name']: row for row in ps(code)}


def test_every_reachable_create_registration_read_back_exactly_uses_the_flags_18_constant():
    """Static guard: in every W script the sitting starts or loads (refresh-r5-sitting-pins.py PIN_NAMES plus the runner),
    each RegisterTaskDefinition in a file that reads the descriptor back with the exact Assert-RegisteredTaskAcl is either a
    create through $script:taskRegistrationFlags (assigned exactly once, to 18), a TASK_UPDATE (4) of the existing Warden
    task, or inside a definition the sitting never imports or runs."""
    assert {name for name in REPAIRED | set(TASK_UPDATE_SITES) | set(IMPORT_ONLY) | NO_EXACT_READ_BACK} <= set(REACHABLE)
    texts = {name: (W / name).read_text(encoding='utf-8') for name in REACHABLE}
    files = scan(REACHABLE)
    using, updates, unvalidated = set(), {}, set()
    for name, row in files.items():
        if not row['sites']:
            assert row['assignments'] == [], name
            continue
        if row['validator_calls'] == 0:
            unvalidated.add(name)
            assert all(site['arguments'][2] != hostacl.FLAGS_CONSTANT for site in row['sites']), name
            continue
        for site in row['sites']:
            arguments = site['arguments']
            assert len(arguments) == 7 and arguments[3] == "'SYSTEM'" and arguments[4] == '$null' and arguments[5] == '5', (name, site)
            if arguments[2] == hostacl.FLAGS_CONSTANT:
                using.add(name)
            elif arguments[2] == '4':
                updates[name] = updates.get(name, 0) + 1
            else:
                # A create with other flags is allowed only inside an import-only file's own registration function.
                assert IMPORT_ONLY.get(name) == site['function'], (name, site)
                for other, text in texts.items():
                    if other != name:
                        assert site['function'] not in text, (other, site['function'])
    assert using == REPAIRED, using ^ REPAIRED
    assert updates == TASK_UPDATE_SITES and unvalidated == NO_EXACT_READ_BACK
    for name in REPAIRED:
        row = files[name]
        assert len(row['sites']) == 1 and row['validator_calls'] >= 1, name
        assert row['assignments'] == [str(hostacl.TASK_CREATE_WITHOUT_PRINCIPAL_ACE)], (name, row['assignments'])
        assert '(0x2) | TASK_DONT_ADD_PRINCIPAL_ACE (0x10)' in texts[name] and 'resume-pending-warden-r3-v7.ps1:125' in texts[name], name
        assert ",2,'SYSTEM'" not in texts[name] and texts[name].isascii(), name


def test_import_only_registration_file_is_never_launched_by_the_sitting():
    """register-stopped-warden-r3.ps1 keeps its historical flags-2 registration (eight scripts import its validator by
    hash); every sitting reference to it is an import of reviewed definitions or the runner's pin-table entry."""
    assert hashlib.sha256(REGISTER.read_bytes()).hexdigest() == REGISTER_SHA256
    pin_line = re.compile(r"^\s*'register-stopped-warden-r3\.ps1'='[0-9a-f]{64}'\s*$")
    for name in REACHABLE:
        if name == REGISTER.name:
            continue
        for line in (W / name).read_text(encoding='utf-8').splitlines():
            if 'register-stopped-warden-r3.ps1' in line:
                assert ('Import-ReviewedFunctions' in line or '$script:registrationFunctions=' in line or pin_line.match(line)), (name, line)
                assert 'Invoke-StoppedWardenRegistration' not in line and '-File' not in line, (name, line)


def test_flags_18_is_create_only_per_taskschd_h():
    flags = hostacl.TASK_CREATE_WITHOUT_PRINCIPAL_ACE
    assert flags == 18 == 0x12 and flags & hostacl.TASK_CREATE and flags & hostacl.TASK_DONT_ADD_PRINCIPAL_ACE
    assert not flags & hostacl.TASK_UPDATE and not flags & 0x1, 'no TASK_UPDATE (an existing task is never replaced), no TASK_VALIDATE_ONLY'
    if not TASKSCHD_H.exists():
        pytest.skip('Windows SDK header not installed')
    text = TASKSCHD_H.read_text(encoding='ascii', errors='replace')
    values = {name: int(value, 16) for name, value in re.findall(r'\b(TASK_[A-Z_]+)\s*=\s*0x([0-9a-fA-F]+)\s*,', text)}
    assert values['TASK_CREATE'] == hostacl.TASK_CREATE and values['TASK_UPDATE'] == hostacl.TASK_UPDATE
    assert values['TASK_DONT_ADD_PRINCIPAL_ACE'] == hostacl.TASK_DONT_ADD_PRINCIPAL_ACE


def test_host_model_reproduces_the_recorded_round_trip_and_the_system_evidence():
    """The fixture model equals what this host recorded: the ordinary-user round trip (flags 2 and 18, 2026-10-09T01:55Z)
    and, for SYSTEM tasks, the owner-observed flags-2 projection (2026-10-08) and the protected Warden read-back."""
    assert hostacl.host_projection(2, hostacl.PRIVATE_TASK_SDDL) == hostacl.HOST_SDDL_AFTER_FLAGS_2
    assert hostacl.host_projection(18, hostacl.PRIVATE_TASK_SDDL) == hostacl.HOST_SDDL_AFTER_FLAGS_18
    aces = re.findall(r'\(A;;(FA|FR);;;(SY|BA)\)', hostacl.HOST_SDDL_AFTER_FLAGS_2)
    rights = {'FA': 2032127, 'FR': 1179785}
    sids = {'SY': 'S-1-5-18', 'BA': 'S-1-5-32-544'}
    pending = json.loads(PENDING_V7.read_text(encoding='utf-8'))
    observed = pending['owner_reported_pending_task']
    assert observed['owner_sid'] == observed['group_sid'] == 'S-1-5-32-544' and observed['service_dacl_protected'] is False
    assert [(a['sid'], a['mask']) for a in observed['service_aces']] == [(sids[s], rights[r]) for r, s in aces]
    data = json.loads(ROUND_TRIP.read_text(encoding='utf-8-sig'))
    requested = data['requested_descriptor']['sddl']
    rows = [o for o in data['observations'] if o['stage'] == 'registration']
    assert sorted(o['registration_flags'] for o in rows) == [2, 18]
    cases = []
    for row in rows:
        actual = row['task']['service_descriptor']['sddl']
        assert hostacl.host_projection(row['registration_flags'], requested, data['current_user_sid']) == actual
        cases.append((row['registration_flags'], requested, data['current_user_sid'], actual))
    cases += [(2, hostacl.PRIVATE_TASK_SDDL, 'SYSTEM', hostacl.HOST_SDDL_AFTER_FLAGS_2), (18, hostacl.PRIVATE_TASK_SDDL, 'SYSTEM', hostacl.HOST_SDDL_AFTER_FLAGS_18)]
    rows_ps = ','.join(f"@({f},'{psq(s)}','{psq(u)}')" for f, s, u, _ in cases)
    value = ps(hostacl.PS_FUNCTION + f"$r=@(foreach($c in @({rows_ps})){{Get-HostTaskSddlProjection $c[0] $c[1] $c[2]}});'RESULT '+(ConvertTo-Json @($r) -Compress)")
    assert value == [expected for *_, expected in cases], 'the PowerShell model and the Python mirror agree with the evidence'
    for path, expected in ((ORIGINAL_WARDEN_SDDL, hostacl.HOST_SDDL_AFTER_FLAGS_2), (RETARGET_BEFORE_SDDL, hostacl.HOST_SDDL_AFTER_FLAGS_18)):
        try:
            text = path.read_text(encoding='utf-8-sig').strip()
        except OSError:
            continue
        assert text == expected, path
    try:
        intent = json.loads(RECOVERY_INTENT.read_text(encoding='utf-8-sig'))
    except OSError:
        return
    assert intent['registration_flags'] == hostacl.TASK_CREATE_WITHOUT_PRINCIPAL_ACE


def test_exact_validator_holds_the_flags_2_read_back_and_accepts_flags_18():
    """The reviewed Assert-RegisteredTaskAcl (unchanged, pin eccc593f) against the modelled read-backs: flags 2 gives the
    exact v2 hold reason, flags 18 passes (the D:PAI auto-inherit control flag is not an ACE flag)."""
    assert hashlib.sha256(REGISTER.read_bytes()).hexdigest() == REGISTER_SHA256
    code = (f"$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile('{psq(REGISTER)}',[ref]$t,[ref]$e);if($e.Count){{throw 'parse'}};"
            "$f=@($a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Assert-RegisteredTaskAcl'},$true));"
            "if($f.Count -ne 1){throw 'count'};. ([scriptblock]::Create($f[0].Extent.Text));" + hostacl.PS_FUNCTION +
            f"$out=[ordered]@{{}};foreach($flags in @({hostacl.TASK_CREATE},{hostacl.TASK_CREATE_WITHOUT_PRINCIPAL_ACE})){{"
            f"$sddl=Get-HostTaskSddlProjection $flags '{hostacl.PRIVATE_TASK_SDDL}' 'SYSTEM';$m='ACCEPTED';try{{Assert-RegisteredTaskAcl $sddl}}catch{{$m=$_.Exception.Message}};"
            "$out[[string]$flags]=@{sddl=$sddl;outcome=$m}};'RESULT '+($out|ConvertTo-Json -Compress)")
    value = ps(code)
    assert value['2'] == {'sddl': hostacl.HOST_SDDL_AFTER_FLAGS_2, 'outcome': hostacl.HELD_ACL_REASON}
    assert value['18'] == {'sddl': hostacl.HOST_SDDL_AFTER_FLAGS_18, 'outcome': 'ACCEPTED'}
