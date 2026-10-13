"""Inert review of owner-only recovery: no host task or process is changed."""
from pathlib import Path

import pytest

from pipeline_tests import test_install_r6_runtime as ps_fixture


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(ps_fixture, 'SCRIPT', Path(__file__).parents[1] / 'scripts/restore_r4_after_agy_tui.ps1')
    return ps_fixture.run_ps


RECEIPT = r'''
$r=@{schema='cochem-interactive-agy-login/1';slot='slot1';nonce='43804e7a8d44457aa9810305923c219f';
 login_mode='tui';status='LOGIN_FAILED_OR_CANCELLED';cleanup_verified=$true;one_line_submitted=$false;
 input_closed_marker_written=$true;login_commands_executed=1;model_jobs_executed=0;authentication_verified=$false;
 activation_ready=$false;secret_published=$false;native_output_after_input_published=$false;
 native_output_bytes_before_input=0;native_output_published_bytes_before_input=0;
 helper_sha256='4074878f100ae59b804c95bd97b3280ccaa09f919ffaa365a3e2c6985045b8d9';
 support_sha256='45681477194d97b144e8ee4505d4364d73d58aaef19c8428c846df642c834839';
 native_executable_sha256='38f30c7dd1ed808f5cf98fe2014de3d30903035a4f0df02d3eb72a9ff8993741';
 failure=@{phase='native_wait';error_type='TimeoutError'}}
'''


def test_exact_zero_output_terminal_bridge_is_reviewed_without_authentication(run_ps):
    result = run_ps(RECEIPT + "Assert-R4TuiReceipt $r; @{reviewed=$true}|ConvertTo-Json -Compress")
    assert result['reviewed']


@pytest.mark.parametrize('change', [
    '$r.cleanup_verified=$false', "$r.nonce=('a'*32)", '$r.one_line_submitted=$true',
    '$r.native_output_bytes_before_input=1', "$r.failure.error_type='WindowsIsolationError'",
    '$r.model_jobs_executed=1', '$r.secret_published=$true',
])
def test_other_or_uncontained_bridge_states_hold(run_ps, change):
    result = run_ps(RECEIPT + change + r'''
$held=$false;try{Assert-R4TuiReceipt $r}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
''')
    assert result['held']


def test_restore_arguments_bind_the_stopped_r4_v5_and_fresh_v6(run_ps):
    result = run_ps("@{args=@(Get-R4TuiRestoreArguments)}|ConvertTo-Json -Compress")
    assert result['args'] == ['-Target', 'r4', '-Attempt', 'v6', '-SourceAttempt', 'v5', '-StopAttempt', 'v5', '-Apply', '-Start']


def test_foreground_session_lock_blocks_a_second_launch(run_ps):
    result = run_ps(r'''
$probe=@{owned=$false}
$blocked=$false;try{Assert-R4TuiRecoveryLock $probe.owned}catch{$blocked=$true}
@{blocked=$blocked;owned=$probe.owned}|ConvertTo-Json -Compress
''')
    assert result['blocked'] is True
    assert result['owned'] is False


def test_default_plan_is_non_executing_and_has_no_sign_in(run_ps):
    result = run_ps("Get-R4TuiRecoveryPlan|ConvertTo-Json -Compress")
    assert result['mode'] == 'READ_ONLY_PLAN'
    assert result['provider_commands_executed'] == 0
    assert result['deployment_attempted'] is False


TASK = r'''
$root='C:\fixture\login'
$action=[pscustomobject]@{Type=0;Path='C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4\.venv\Scripts\python.exe';
 Arguments='-I -B "C:\fixture\login\worker_agy_login_bridge_r4_v1.py" --slot slot1 --nonce 43804e7a8d44457aa9810305923c219f --login-mode tui';WorkingDirectory=$root}
$definition=[pscustomobject]@{Actions=@($action);Triggers=@();Principal=[pscustomobject]@{UserId='SYSTEM';LogonType=5;RunLevel=1}}
$task=[pscustomobject]@{Name='CoChem-4.2.7-InteractiveAgy-r4-slot1-43804e7a8d44457aa9810305923c219f';State=3;LastTaskResult=2;Definition=$definition}
$task|Add-Member -MemberType ScriptMethod -Name GetInstances -Value {param($flags) @()}
'''


def test_exact_terminal_task_definition_passes(run_ps):
    result = run_ps(TASK + "Assert-R4TuiTask $task $root; @{verified=$true}|ConvertTo-Json -Compress")
    assert result['verified'] is True


@pytest.mark.parametrize('change', [
    '$task.State=4', '$task.LastTaskResult=0', "$task.Name='different'",
    "$action.Arguments+=' --different'", "$action.Path='C:\\ordinary\\python.exe'",
    "$definition.Principal.UserId='AETHERDESK\\ansac'", '$definition.Triggers=@(@{})',
    "$task|Add-Member -Force -MemberType ScriptMethod -Name GetInstances -Value {param($flags) @('active')}",
])
def test_running_or_changed_tasks_do_not_authorize_restoration(run_ps, change):
    result = run_ps(TASK + change + r'''
$held=$false;try{Assert-R4TuiTask $task $root}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
''')
    assert result['held'] is True

