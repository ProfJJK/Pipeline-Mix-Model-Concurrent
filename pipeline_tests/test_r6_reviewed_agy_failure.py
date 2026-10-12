"""Exact owner-observed failure admission, with all host boundaries inert."""
import json
from pathlib import Path

import pytest

from pipeline_tests import test_install_r6_runtime as ps_fixture

NONCE = '67d70b0983cc48e2abf7c561aca29f86'
RECEIPT_PIN = '882326a4f4b30ca527cf22faaf5c15f528a9eb40421bc5aa052a12bfd77e9ec0'
HELD_PIN = '52c9911858aa5b68b885e2c7f2c55402f52c91d810b2b4bd3529394f75fb24a8'


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(ps_fixture, 'SCRIPT', Path(__file__).parents[1]/'scripts/verify_r6_auth_recovery.ps1')
    return ps_fixture.run_ps


def fixture_receipts():
    receipt = dict(schema='cochem-interactive-agy-login/1', slot='slot1', nonce=NONCE,
        login_mode='print', status='LOGIN_COMMAND_FAILED', cleanup_verified=True, one_line_submitted=True,
        input_file_deleted=True, operator_cancelled=False, terminated_after_input=False,
        input_closed_marker_written=True, native_exit_code=1, login_commands_executed=1, model_jobs_executed=0,
        authentication_verified=False, activation_ready=False, secret_published=False,
        native_output_after_input_published=False, pause_marker_seen=False,
        native_markers={'after_input': {'authentication_failed_present': True}},
        helper_sha256='4074878f100ae59b804c95bd97b3280ccaa09f919ffaa365a3e2c6985045b8d9',
        support_sha256='45681477194d97b144e8ee4505d4364d73d58aaef19c8428c846df642c834839',
        native_executable_sha256='38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741',
        native_executable_sha256_after='38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741')
    held = dict(phase='DECISION', login_mode='print', receipt_sha256=RECEIPT_PIN,
        task_registered=True, run_requested=True, receipt_present=True, raw_provider_output_recorded=False,
        code_recorded=False, login_authorized=False, automatic_retry_allowed=False, requires_owner_review=True,
        task_after={'state': 3, 'instances': 0, 'last_task_result': 2}, input_cleanup={'input_present': False})
    return receipt, held


@pytest.mark.parametrize('mutation', ['', 'cleanup', 'native_result', 'bridge', 'native_hash', 'nonce',
    'published', 'model_job', 'input_closed', 'pause', 'held_phase', 'held_authorized', 'held_receipt',
    'input_left', 'task_running', 'task_instances', 'task_result', 'task_name', 'task_arguments',
    'task_acl', 'task_duration', 'helper_changed'])
def test_preserved_login_requires_exact_pins_cleanup_and_terminal_definition(run_ps, mutation):
    receipt, held = fixture_receipts()
    edits = {'cleanup': ('cleanup_verified', False), 'native_result': ('native_exit_code', 0),
        'bridge': ('helper_sha256', 'a'*64), 'native_hash': ('native_executable_sha256_after', 'a'*64),
        'nonce': ('nonce', 'a'*32), 'published': ('secret_published', True), 'model_job': ('model_jobs_executed', 1),
        'input_closed': ('input_closed_marker_written', False), 'pause': ('pause_marker_seen', True)}
    if mutation in edits:
        key, value = edits[mutation]; receipt[key] = value
    if mutation == 'held_phase': held['phase'] = 'WAIT'
    if mutation == 'held_authorized': held['login_authorized'] = True
    if mutation == 'held_receipt': held['receipt_sha256'] = 'a'*64
    phase = str(Path(__file__).parents[1]/'scripts/run_r6_system_phase.ps1').replace("'", "''")
    result = run_ps("$script:receipt='"+json.dumps(receipt)+"'|ConvertFrom-Json\n"+
        "$script:heldReceipt='"+json.dumps(held)+"'|ConvertFrom-Json\n"+r'''
$script:base='C:\fixture';$script:targetRoot='C:\fixture\r6';$script:events=[Collections.Generic.List[string]]::new()
function Read-R6RecoveryJson {param($Path,$Hash)
  if($Path -like '*\receipt.json'){
    if($Hash -cne 'RECEIPT_PIN'){throw 'receipt not pinned'};return $script:receipt}
  if($Path -like '*\session-held.json'){
    if($Hash -cne 'HELD_PIN'){throw 'held not pinned'};return $script:heldReceipt}
  throw 'unexpected read'}
function Get-R6ReviewedAgyTask {
  $root=Join-Path $script:base 'InteractiveAgy427-r4-slot1-NONCE'
  $arguments='-I -B "'+(Join-Path $root 'worker_agy_login_bridge_r4_v1.py')+'" --slot slot1 --nonce NONCE --login-mode print'
  $settings=[pscustomobject]@{MultipleInstances=2;RestartCount=0;AllowDemandStart=$true;ExecutionTimeLimit='PT15M';Enabled=$true}
  $action=[pscustomobject]@{Type=0;Path='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\Scripts\python.exe';Arguments=$arguments;WorkingDirectory=$root}
  $actions=[pscustomobject]@{Count=1;Action=$action};$actions|Add-Member ScriptMethod Item {param($Number) $this.Action}
  $definition=[pscustomobject]@{Settings=$settings;Principal=[pscustomobject]@{UserId='SYSTEM';LogonType=5;RunLevel=1};Actions=$actions;Triggers=[pscustomobject]@{Count=0}}
  $task=[pscustomobject]@{Name='CoChem-4.2.7-InteractiveAgy-r4-slot1-NONCE';Definition=$definition;Enabled=$true;
    Acl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)';State=3;LastTaskResult=2;LastRunTime=[DateTime]'2026-10-12'}
  if('MUTATION' -eq 'task_running'){$task.State=4}
  if('MUTATION' -eq 'task_result'){$task.LastTaskResult=0}
  if('MUTATION' -eq 'task_name'){$task.Name='other'}
  if('MUTATION' -eq 'task_arguments'){$action.Arguments='changed'}
  if('MUTATION' -eq 'task_acl'){$task.Acl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BU)'}
  if('MUTATION' -eq 'task_duration'){$settings.ExecutionTimeLimit='PT1M'}
  $task|Add-Member ScriptMethod GetInstances {param($Flags) @{Count=$(if('MUTATION' -eq 'task_instances'){1}else{0})}}
  $task|Add-Member ScriptMethod GetSecurityDescriptor {param($Mask) $this.Acl}
  return $task}
function Test-Path {param($LiteralPath) return ('MUTATION' -eq 'input_left')}
function Assert-ProtectedPath {param($Path)}
function Get-Item {param($LiteralPath) @{Length=100}}
function Open-VerifiedFile {param($Path,$Hash,$Length)
  if('MUTATION' -eq 'helper_changed'){throw 'helper changed'}
  $script:events.Add((Split-Path -Leaf $Path));[IO.MemoryStream]::new()}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('PHASE_PATH',[ref]$tokens,[ref]$errors)
$node=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Assert-R6PhaseTask'},$false))[0]
. ([scriptblock]::Create($node.Extent.Text))
$refused=$false;$message=''
try{Assert-R6ReviewedAgySession}catch{$refused=$true;$message=$_.Exception.Message}
@{refused=$refused;message=$message;events=@($script:events)}|ConvertTo-Json -Compress
'''.replace('RECEIPT_PIN', RECEIPT_PIN).replace('HELD_PIN', HELD_PIN).replace('NONCE', NONCE)
       .replace('MUTATION', mutation).replace('PHASE_PATH', phase))
    assert result['refused'] is bool(mutation), result
    if not mutation:
        assert result['events'] == ['worker_agy_login_bridge_r4_v1.py', 'worker_native_status_support.py']


@pytest.mark.parametrize('mutation', ['', 'none', 'extra_root', 'extra_task', 'wrong_root', 'wrong_task', 'wrong_path'])
def test_only_reviewed_session_is_allowed_and_unknown_sessions_hold(run_ps, mutation):
    result = run_ps(r'''
$script:base='C:\fixture'
function Get-ChildItem {param($LiteralPath,[switch]$Directory,$Filter)
  if($LiteralPath -cne $script:base -or $Filter -cne 'InteractiveAgy427-r4-slot1-*'){throw 'wrong census'}
  if('MUTATION' -eq 'none'){return}
  $name='InteractiveAgy427-r4-slot1-NONCE'
  [pscustomobject]@{Name=$(if('MUTATION' -eq 'wrong_root'){'other'}else{$name});
    FullName=$(if('MUTATION' -eq 'wrong_path'){'C:\elsewhere'}else{Join-Path $script:base $name})}
  if('MUTATION' -eq 'extra_root'){[pscustomobject]@{Name='other';FullName='C:\other'}}}
function Get-R6Slot1InteractiveTasks {
  if('MUTATION' -eq 'none'){return}
  [pscustomobject]@{Name=$(if('MUTATION' -eq 'wrong_task'){'other'}else{'CoChem-4.2.7-InteractiveAgy-r4-slot1-NONCE'})}
  if('MUTATION' -eq 'extra_task'){[pscustomobject]@{Name='other'}}}
$refused=$false
try{Assert-R6ReviewedInteractiveCensus $true}catch{$refused=$true}
$unreviewedRefused=$false
try{Assert-R6ReviewedInteractiveCensus $false}catch{$unreviewedRefused=$true}
@{refused=$refused;unreviewed=$unreviewedRefused}|ConvertTo-Json -Compress
'''.replace('NONCE', NONCE).replace('MUTATION', mutation))
    assert result['refused'] is bool(mutation)
    assert result['unreviewed'] is (mutation != 'none')


@pytest.mark.parametrize('mutation', ['', 'status', 'stream', 'helper', 'auth_task', 'held_phase',
    'cutover', 'restore_failed', 'restore_receipt', 'session'])
def test_latest_auth_hold_requires_signed_out_rows_restore_and_reviewed_session(run_ps, mutation):
    rows = [dict(worker=f'slot{i}', provider=p, authenticated=p != 'gemini', cleanup_verified=True,
        status='ATTENDED_LOGIN_REQUIRED' if p == 'gemini' else 'REUSE_VERIFIED_SESSION',
        exit_code=1 if p == 'gemini' else 0) for i in range(1, 7) for p in ('codex', 'claude', 'gemini')]
    for row in rows:
        if row['provider'] == 'gemini':
            row.update(reason='AGY_MODELS_EXPLICIT_SIGN_OUT', stdout_bytes=0, stderr_bytes=122,
                stdout_sha256='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
                stderr_sha256='148fc48c6aeaf4d5f5780d0e38fc39215de098c1537c57e09410d4dad9718a1d')
    if mutation == 'status': rows[2]['status'] = 'STATUS_UNVERIFIED'
    if mutation == 'stream': rows[2]['stderr_sha256'] = 'a'*64
    evidence = dict(phase='auth', status='PHASE_COMPLETED',
        manifest_sha256='bffcf617620320109a3ff1bcbdcc2e1d4918f9571721dc4642efeed4d0b7a2c4',
        candidate_sha256='a8b9b2052402f30860188721f986686c5a2f6785e563045edf295adae250f288',
        result=dict(schema='cochem-r6-authentication/1', status='ATTENDED_AUTH_REVIEW_REQUIRED',
            status_helper_sha256='a'*64 if mutation == 'helper' else '79b7029cd998f25c0a01300924bb3972f830f7783618ce3c99260b089510aaec',
            native_model_jobs_executed=0, credentials_copied=False, checks=rows))
    result = run_ps("$script:evidence='"+json.dumps(evidence)+"'|ConvertFrom-Json\n"+r'''
$script:base='C:\fixture';$script:events=[Collections.Generic.List[string]]::new()
$root=Join-Path $script:base 'R6Acceptance4.2.7-windows-20261012-v1-auth-f1b5e414c1b44a5fb3c7d7686dbc9ff8'
function Read-R6RecoveryJson {param($Path,$Hash)
  if($Path -like '*\result.json'){
    if($Hash -cne 'dc0af0b999e6e4a0cd72fed5b80fc05cfd30a85edf76d1ce659cc3b5b69aa5e0'){throw 'auth not pinned'}
    return $script:evidence}
  if($Path -like '*\r6-held.json'){
    if($Path -notlike '*87bf2f05e1254ea6b5e7de51018b830c*'){throw 'wrong sitting'}
    return @{status='HELD_PRESERVE_EVIDENCE';phase=$(if('MUTATION' -eq 'held_phase'){'auth'}else{'attended_gemini_slot1'});
      cutover_requested=('MUTATION' -eq 'cutover');recovery=@{ok=$true;restored=('MUTATION' -ne 'restore_failed');kind='base'}}}
  if($Path -like '*\start-receipt.json'){
    if($Hash -cne '978bad6cf2773df7151c21cca988e4ebd9a4549f9639976f920a9567d803528c' -or
       $Path -notlike '*r4-v5*'){throw 'restore not pinned'}
    return @{schema='cochem-warden-start/3';status='WARDEN_R4_RESTARTED_HEALTH_VERIFIED';target='r4';attempt='v5';
      task_name='CoChem-4.2.7-Warden';enabled_after=$true;task_state=4;running_instances=1;
      health_samples=$(if('MUTATION' -eq 'restore_receipt'){1}else{2});health=@{samples_stable=$true};
      exactly_one_start_requested=$true;automatic_retry_allowed=$false}}
  throw 'unexpected read'}
function Assert-R6ReviewedAuthTask {param($Root,$Name)
  if($Name -cne 'CoChem-4.2.7-R6Acceptance-auth-f1b5e414c1b44a5fb3c7d7686dbc9ff8' -or $Root -notlike '*auth-f1b5e414c1b44a5fb3c7d7686dbc9ff8'){throw 'wrong task'}
  if('MUTATION' -eq 'auth_task'){throw 'task changed'};$script:events.Add('auth_task')}
function Assert-R6ReviewedAgySession {
  if('MUTATION' -eq 'session'){throw 'session changed'};$script:events.Add('session')}
$refused=$false
try{Assert-R6ReviewedNativeLoginFailure $root}catch{$refused=$true}
@{refused=$refused;events=@($script:events)}|ConvertTo-Json -Compress
'''.replace('MUTATION', mutation))
    assert result['refused'] is bool(mutation)
    if not mutation: assert result['events'] == ['auth_task', 'session']
