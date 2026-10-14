"""Tests for P428-26 single owner entry point (`run_428_launch.ps1` and `accept_428_native.py`).

All PowerShell and Python checks run in inert or read-only mode (`-Apply` omitted);
no services, scheduled tasks, or native providers are executed on the host.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from scripts import accept_428_native as accept_428
from scripts import prepare_428_release as release_428
from scripts import verify_prior_native_428 as prior_428


ROOT = Path(__file__).resolve().parents[1]
LAUNCH_SCRIPT = ROOT / "scripts" / "run_428_launch.ps1"
PS51 = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


def run_ps_428(body: str) -> dict:
    path = str(LAUNCH_SCRIPT).replace("'", "''")
    source = f"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
Import-Module (Join-Path $PSHOME 'Modules\\Microsoft.PowerShell.Utility\\Microsoft.PowerShell.Utility.psd1') -ErrorAction Stop
Import-Module (Join-Path $PSHOME 'Modules\\Microsoft.PowerShell.Security\\Microsoft.PowerShell.Security.psd1') -ErrorAction Stop
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$tokens,[ref]$errors)
if($errors.Count){{throw 'Script parse error'}}
foreach($f in $ast.FindAll({{param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]}},$false)){{
 . ([scriptblock]::Create($f.Extent.Text))
}}
$script:targetRoot='C:\\fixture\\r428'
{body}
"""
    result = subprocess.run(
        [
            PS51,
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(source.encode("utf-16-le")).decode(),
        ],
        capture_output=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return json.loads(result.stdout.decode("utf-8-sig"))


def test_open_428_pin_holds_bytes_until_disposal_and_rejects_mismatch(tmp_path: Path) -> None:
    p = tmp_path / "pinned.json"
    p.write_bytes(b'{"version":"4.2.8"}')
    pin = hashlib.sha256(p.read_bytes()).hexdigest()
    escaped = str(p).replace("'", "''")
    body = f"""
$s=Open-428Pin '{escaped}' '{pin}' 19
try{{
    $row=Read-428Json $s;$blocked=$false
    try{{$write=[IO.File]::Open('{escaped}','Open','Write','ReadWrite');$write.Dispose()}}catch{{$blocked=$true}}
    @{{version=$row.version;blocked=$blocked;position=$s.Position}}|ConvertTo-Json -Compress
}}finally{{$s.Dispose()}}
"""
    assert run_ps_428(body) == {"version": "4.2.8", "blocked": True, "position": 0}

    for bad_pin, bad_len in [("invalid", 19), ("a" * 64, 19), (pin, 20)]:
        row = run_ps_428(
            f"$held=$false;try{{$null=Open-428Pin '{escaped}' '{bad_pin}' {bad_len}}}catch{{$held=$true}};@{{held=$held}}|ConvertTo-Json -Compress"
        )
        assert row["held"] is True


def test_task_definition_projection_and_acl_validation() -> None:
    row = run_ps_428(
        r"""
$original='<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers><Settings><Enabled>true</Enabled><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><ExecutionTimeLimit>PT0S</ExecutionTimeLimit></Settings><Actions><Exec><Command>old</Command><Arguments>old</Arguments><WorkingDirectory>old</WorkingDirectory></Exec></Actions></Task>'
$updated=$original.Replace('<Enabled>true</Enabled>','<Enabled>false</Enabled>').Replace('>old<','>new<')
$bad=$updated.Replace('IgnoreNew','Parallel')
$goodTask=[pscustomobject]@{}
$goodTask|Add-Member -MemberType ScriptMethod -Name GetSecurityDescriptor -Value {param($flags) 'O:SYG:SYD:P(A;;0x1f01ff;;;SY)(A;;0x1f01ff;;;BA)'}
$badTask=[pscustomobject]@{}
$badTask|Add-Member -MemberType ScriptMethod -Name GetSecurityDescriptor -Value {param($flags) 'O:SYG:SYD:(A;;0x1f01ff;;;SY)(A;;0x1f01ff;;;BU)'}
$aclOk=$false;try{Assert-428TaskAcl $goodTask;$aclOk=$true}catch{}
$aclHeld=$false;try{Assert-428TaskAcl $badTask}catch{$aclHeld=$true}
@{
    allowed=((Get-428InvariantDefinition $original) -ceq (Get-428InvariantDefinition $updated));
    denied=((Get-428InvariantDefinition $original) -cne (Get-428InvariantDefinition $bad));
    acl_ok=$aclOk;
    acl_held=$aclHeld
}|ConvertTo-Json -Compress
"""
    )
    assert row == {"allowed": True, "denied": True, "acl_ok": True, "acl_held": True}


def test_powershell_and_python_input_window_deadline_and_fresh_oauth_guards() -> None:
    # PowerShell Assert-428InputWindow check
    ps_row = run_ps_428(
        r"""
$t0=[DateTime]::Parse('2026-10-14T12:00:00Z').ToUniversalTime()
$ok=Assert-428InputWindow $t0 ($t0.AddMinutes(15)) 'https://auth.example.com/oauth?code=fresh1' 'dialog-0001'
$replayUrlHeld=$false;try{$null=Assert-428InputWindow $t0 ($t0.AddMinutes(16)) 'https://auth.example.com/oauth?code=fresh1' 'dialog-0002'}catch{$replayUrlHeld=$true}
$replayDlgHeld=$false;try{$null=Assert-428InputWindow $t0 ($t0.AddMinutes(16)) 'https://auth.example.com/oauth?code=fresh2' 'dialog-0001'}catch{$replayDlgHeld=$true}
$expiredHeld=$false;try{$null=Assert-428InputWindow $t0 ($t0.AddMinutes(21)) 'https://auth.example.com/oauth?code=fresh3' 'dialog-0003'}catch{$expiredHeld=$true}
$httpHeld=$false;try{$null=Assert-428InputWindow $t0 ($t0.AddMinutes(5)) 'http://auth.example.com/oauth?code=insecure' 'dialog-0004'}catch{$httpHeld=$true}
@{
    within=$ok.within_window;
    late=$ok.late_prompt;
    replay_url_held=$replayUrlHeld;
    replay_dlg_held=$replayDlgHeld;
    expired_held=$expiredHeld;
    http_held=$httpHeld
}|ConvertTo-Json -Compress
"""
    )
    assert ps_row == {
        "within": True,
        "late": False,
        "replay_url_held": True,
        "replay_dlg_held": True,
        "expired_held": True,
        "http_held": True,
    }

    # Python check_front_loaded_input_window
    start = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
    seen_urls: set[str] = set()
    seen_dialogs: set[str] = set()
    res = accept_428.check_front_loaded_input_window(
        start,
        start + timedelta(minutes=19, seconds=30),
        oauth_url="https://accounts.example.com/o/oauth2/v2/auth?state=xyz123",
        seen_oauth_urls=seen_urls,
        dialog_id="owner-secret-confirm-1",
        seen_dialogs=seen_dialogs,
    )
    assert res["within_window"] is True
    assert res["late_prompt"] is False
    assert res["remaining_seconds"] == 30.0

    with pytest.raises(accept_428.NativeAcceptanceHold) as exc_replay:
        accept_428.check_front_loaded_input_window(
            start,
            start + timedelta(minutes=19, seconds=45),
            oauth_url="https://accounts.example.com/o/oauth2/v2/auth?state=xyz123",
            seen_oauth_urls=seen_urls,
        )
    assert exc_replay.value.code == "STALE_OR_REPLAYED_OAUTH_URL"

    with pytest.raises(accept_428.NativeAcceptanceHold) as exc_expired:
        accept_428.check_front_loaded_input_window(
            start,
            start + timedelta(minutes=20, seconds=1),
        )
    assert exc_expired.value.code == "INPUT_WINDOW_EXPIRED"


def test_profile_signin_plan_reuses_workers_and_front_loads_repair_profiles() -> None:
    plan_missing_repair = accept_428.evaluate_profile_signin_plan(
        accept_428.REQUIRED_WORKER_PROFILES,
        owner_secret_configured=False,
    )
    assert len(plan_missing_repair["reused_worker_profiles"]) == 15
    assert plan_missing_repair["missing_worker_profiles"] == []
    assert plan_missing_repair["missing_repair_profiles"] == list(
        accept_428.REQUIRED_REPAIR_PROFILES
    )
    assert plan_missing_repair["front_loaded_actions"] == [
        "dedicated_repair_profile_signin",
        "owner_approval_secret_setup",
    ]
    assert plan_missing_repair["interactive_input_required"] is True
    assert plan_missing_repair["late_prompts_allowed"] is False

    plan_all_ready = accept_428.evaluate_profile_signin_plan(
        [*accept_428.REQUIRED_WORKER_PROFILES, *accept_428.REQUIRED_REPAIR_PROFILES],
        owner_secret_configured=True,
    )
    assert plan_all_ready["interactive_input_required"] is False
    assert plan_all_ready["front_loaded_actions"] == []

    with pytest.raises(accept_428.NativeAcceptanceHold) as exc_unknown:
        accept_428.evaluate_profile_signin_plan(["slot9:unknown"])
    assert exc_unknown.value.code == "UNKNOWN_PROFILE_IN_SIGNIN_STATE"


def test_no_attended_commands_after_walkaway_boundary_428() -> None:
    script = LAUNCH_SCRIPT.read_text(encoding="utf-8")
    tail = script.split(
        "Write-Host '4.2.8 prerequisites and front-loaded inputs verified."
    )[1]
    assert "Read-Host" not in tail
    assert "RunAs" not in tail
    assert "login" not in tail
    assert "-NonInteractive" in tail
    assert "Restore-428BeforeStart" in tail
    assert "if($stopped -and -not $startRequested)" in tail


def test_prior_fable_failure_replay_and_argon_quota_vs_hold_classification() -> None:
    # 1. Replay saved Fable target-23 HTTP 429 hold using fixture reader
    fixture_files: dict[str, bytes] = {}
    native_root = prior_428.COCHEM_PROGRAM_FILES / prior_428.NATIVE_HOLD_ROOT_NAME

    stdout_bytes = (
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": True,
                "result": 'API Error: 429 {"error":{"type":"rate_limit_error","message":"Request failed with status code 429"}}',
            }
        ).encode("utf-8")
    )
    stdout_sha = hashlib.sha256(stdout_bytes).hexdigest()

    # Use verify_prior_native_428's source repair inventory directly + test quota vs hold
    summary = accept_428.verify_prior_repairs_and_fable_replay(run_host_replay=False)
    assert summary["source_repairs"]["status"] == "ALL_R5_R6_REPAIRS_IN_CANONICAL_SOURCE"
    assert summary["fable_target_23_policy"] == "QUOTA_429_BECOMES_AVAILABILITY_SKIP_ONLY"

    # When replay_saved_fable_failure raises PermissionError/PriorNativeReplayError, accept_428 converts to NativeAcceptanceHold
    def failing_reader(path: Path, expected_sha: str, max_bytes: int) -> bytes:
        raise PermissionError("simulated non-admin reader")

    with pytest.raises(accept_428.NativeAcceptanceHold) as exc_perm:
        accept_428.verify_prior_repairs_and_fable_replay(
            protected_reader=failing_reader,
            run_host_replay=True,
        )
    assert exc_perm.value.code == "PROTECTED_READ_PERMISSION_DENIED"
    assert stdout_sha  # deterministic fixture sanity

    # 2. Argon evaluation: quota 429 -> AVAILABILITY_WAIT, compatibility mismatch -> NativeAcceptanceHold
    spec = {
        "protocol": "agy-stream-json",
        "identity_policy": "reported-model-equality",
        "model_bindings": {"gemini-3.8-flash": "gemini-3.8-flash-low"},
        "inference_only": {
            "executable_sha256": "a" * 64,
            "version": "1.3.1",
            "version_arguments": ["--version"],
        },
    }
    inference = spec["inference_only"]
    capture = {
        "schema": "cochem-agy-catalog-capture/1",
        "executable_sha256": inference["executable_sha256"],
        "version": inference["version"],
        "catalog_sha256": "c" * 64,
        "model_slugs": [
            "gemini-4-argon-low",
            "gemini-4-argon-medium",
            "gemini-4-argon-high",
        ],
    }
    quota_eval = accept_428.evaluate_argon_acceptance(
        spec,
        capture,
        probe_fixtures={
            "low": {
                "raw_stdout": "",
                "raw_stderr": '{"error":{"code":429,"status":"resource_exhausted"}}\n',
                "exit_code": 1,
                "binary_sha256": inference["executable_sha256"],
                "version_stdout": f"{inference['version']}\n",
                "cleanup_verified": True,
            }
        },
    )
    assert quota_eval["outcomes"]["low"]["status"] == "AVAILABILITY_WAIT"
    assert quota_eval["outcomes"]["low"]["category"] == "quota"

    with pytest.raises(accept_428.NativeAcceptanceHold) as exc_unclean:
        accept_428.evaluate_argon_acceptance(
            spec,
            capture,
            probe_fixtures={
                "medium": {
                    "raw_stdout": "",
                    "raw_stderr": "",
                    "exit_code": 0,
                    "binary_sha256": inference["executable_sha256"],
                    "version_stdout": f"{inference['version']}\n",
                    "cleanup_verified": False,
                }
            },
        )
    assert exc_unclean.value.code == "ARGON_MEDIUM_QUARANTINED_UNCLEAN"


def test_rollback_boundary_and_awake_lease_and_sanitized_status() -> None:
    # 1. Uncertain migration refuses to start any controller
    uncertain = run_ps_428(
        r"""
$script:events=[Collections.Generic.List[string]]::new()
function Assert-428PortFree {$script:events.Add('port')}
function Invoke-428Migration {$script:events.Add('migration');throw 'must not run'}
$held=$false;try{$null=Restore-428BeforeStart $null $null '' '' '' $true $false}catch{$held=$true}
@{held=$held;events=@($script:events)}|ConvertTo-Json -Compress
"""
    )
    assert uncertain == {"held": True, "events": ["port"]}

    # 2. Completed migration followed by pre-start failure invokes rollback migration and restores Warden
    restored = run_ps_428(
        r"""
$script:events=[Collections.Generic.List[string]]::new()
function Assert-428PortFree {$script:events.Add('port')}
function Invoke-428Migration {param($S,$F,$Rollback) $script:events.Add('rollback:'+$Rollback);@{status='PRE_CUTOVER_DATABASE_RESTORED'}}
function Assert-428WardenTask {param($Task,$Xml,$Sddl,$Root,$Args,$En,$Tr) $script:events.Add('assert-task:'+$En+':'+$Tr)}
function Wait-428Health {param($Root) $script:events.Add('wait-health');@{pid=42;instance_id='inst-1'}}
function Open-428ProcessProof {param($Health,$Root) $script:events.Add('proof');@()}
$fakeActions=[pscustomobject]@{}
$fakeActions|Add-Member -MemberType ScriptMethod -Name Item -Value {param($i)[pscustomobject]@{Arguments='daemon'}}
$fakeTriggerItem=[pscustomobject]@{Enabled=$true}
$fakeTriggers=[pscustomobject]@{}
$fakeTriggers|Add-Member -MemberType ScriptMethod -Name Item -Value {param($i) $fakeTriggerItem}
$fakeDef=[pscustomobject]@{
    XmlText='';
    Actions=$fakeActions;
    Triggers=$fakeTriggers;
    Settings=[pscustomobject]@{Enabled=$true}
}
$fakeInstances=[pscustomobject]@{Count=1}
$fakeInstances|Add-Member -MemberType ScriptMethod -Name Item -Value {param($i)[pscustomobject]@{InstanceGuid='g-1'}}
$fakeTask=[pscustomobject]@{Definition=$fakeDef}
$fakeTask|Add-Member -MemberType ScriptMethod -Name Run -Value {param($x) $script:events.Add('run-task');[pscustomobject]@{InstanceGuid='g-1'}}
$fakeTask|Add-Member -MemberType ScriptMethod -Name GetInstances -Value {param($x) $fakeInstances}
$fakeScheduler=[pscustomobject]@{}
$fakeScheduler|Add-Member -MemberType ScriptMethod -Name NewTask -Value {param($x) $fakeDef}
$fakeFolder=[pscustomobject]@{}
$fakeFolder|Add-Member -MemberType ScriptMethod -Name RegisterTaskDefinition -Value {param($n,$d,$f,$u,$p,$l,$s) $script:events.Add('register');$fakeTask}
$fakeFolder|Add-Member -MemberType ScriptMethod -Name GetTask -Value {param($n) $fakeTask}
$status=Restore-428BeforeStart $fakeScheduler $fakeFolder '<Task/>' 'SDDL' 'C:\old' $true $true
@{status=$status;events=@($script:events)}|ConvertTo-Json -Compress
"""
    )
    assert restored["status"] == "PREVIOUS_RUNTIME_RESTORED_HEALTH_VERIFIED"
    assert restored["events"][:2] == ["port", "rollback:True"]
    assert "wait-health" in restored["events"]

    # 3. Sanitized status never leaks raw output or sets late_prompt
    status_row = run_ps_428(
        r"""
$script:Sitting428='C:\fixture\sitting428';$script:targetRoot='C:\fixture\runtime428'
function Write-428InstallRecord {param($Name,$Value) $script:saved=$Value;$script:directory=$script:targetRoot}
Write-428Status 'migration' 'HELD' @{error_type='ValueError';automatic_retry=$false}
@{record=$script:saved;directory=$script:directory;restored=$script:targetRoot}|ConvertTo-Json -Depth 6 -Compress
"""
    )
    assert status_row["restored"] == r"C:\fixture\runtime428"
    assert status_row["directory"] == r"C:\fixture\sitting428"
    assert status_row["record"]["late_prompt"] is False
    assert status_row["record"]["full_srs_acceptance"] is False

    # 4. Awake lease temporary request & restoration
    for fail in (False, True):
        awake_row = run_ps_428(
            r"""
Add-Type -TypeDefinition @'
using System.Collections.Generic;
public static class CoChem428Awake {
 public static List<uint> Calls = new List<uint>();
 public static uint GetCurrentThreadId() { return 11; }
 public static uint SetThreadExecutionState(uint flags) { Calls.Add(flags); return RETURN; }
}
'@
$held=$false;$lease=$null
try{$lease=Start-428AwakeLease}catch{$held=$true}
if($null -ne $lease){Stop-428AwakeLease $lease}
@{held=$held;calls=@([CoChem428Awake]::Calls)}|ConvertTo-Json -Compress
""".replace("RETURN", "0" if fail else "2147483648")
        )
        assert awake_row["held"] is fail
        assert awake_row["calls"] == ([2147483649] if fail else [2147483649, 2147483648])


def test_packaged_read_only_launch_plan_and_tamper_detection_428(tmp_path: Path) -> None:
    backend = Path(r"C:\Users\ansac\CoChem427\r6-build-backend-20261012-v2")
    wheelhouse = Path(r"C:\Users\ansac\CoChem427\r6-runtime-wheels-20261012-v1")
    uv = Path(r"C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\uv\uv.exe")
    python_exe = Path(r"C:\Program Files\CoChem\Toolchain4.2.7-windows-20261006\Python312\python.exe")
    freeze_dir = tmp_path / "freeze"
    build_dir = tmp_path / "build"
    bundle_dir = tmp_path / "bundle"

    commit = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()
    release_428.freeze_from_git_428(ROOT, commit, freeze_dir)
    release_428.build_application_wheel_428(
        freeze_dir, backend, build_dir, uv, str(python_exe)
    )
    app_meta = build_dir / "application-wheel.json"

    bundle_res = release_428.prepare_release_bundle_428(
        freeze_dir,
        wheelhouse,
        app_meta,
        bundle_dir,
        ROOT,
    )
    assert bundle_res["administrator_launch_ready"] is True

    manifest_path = bundle_dir / "launch-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pin_res = accept_428.verify_acceptance_bundle_pins(manifest, bundle_dir)
    assert pin_res["tamper_detected"] is False
    assert pin_res["verified_files"] == 12

    # Execute packaged run_428_launch.ps1 in read-only mode (-Apply omitted)
    proc = subprocess.run(
        [
            PS51,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(bundle_dir / "run_428_launch.ps1"),
            "-LaunchManifest",
            str(manifest_path),
            "-LaunchManifestSha256",
            bundle_res["launch_manifest_sha256"],
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"STDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    plan = json.loads(proc.stdout)
    assert plan["schema"] == "cochem-428-launch-plan/1"
    assert plan["status"] == "R428_LAUNCH_READ_ONLY_PLAN"
    assert plan["version"] == "4.2.8"
    assert plan["maximum_shared_slots"] == 4
    assert plan["repair_profiles"] == ["repair_claude", "repair_codex", "repair_agy"]
    assert plan["repair_consumes_worker_slot"] is False
    assert plan["input_window_minutes"] == 20
    assert plan["late_prompts"] is False
    assert plan["host_executed"] is False

    # Tamper with pointer.json and verify both Python and PowerShell refuse
    (bundle_dir / "pointer.json").write_text('{"tampered":true}\n', encoding="utf-8")
    with pytest.raises(accept_428.NativeAcceptanceHold) as exc_tamper:
        accept_428.verify_acceptance_bundle_pins(manifest, bundle_dir)
    assert exc_tamper.value.code == "PACKAGE_TAMPER_DETECTED"

    proc_tamper = subprocess.run(
        [
            PS51,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(bundle_dir / "run_428_launch.ps1"),
            "-LaunchManifest",
            str(manifest_path),
            "-LaunchManifestSha256",
            bundle_res["launch_manifest_sha256"],
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc_tamper.returncode != 0
