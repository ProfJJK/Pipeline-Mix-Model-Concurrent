from pathlib import Path

import pytest

from pipeline_tests import test_install_r6_runtime as ps_fixture


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(ps_fixture, 'SCRIPT', Path(__file__).parents[1]/'scripts/run_r6_system_phase.ps1')
    return ps_fixture.run_ps


@pytest.mark.parametrize('mutation', ['', 'duration', 'principal', 'enabled', 'arguments', 'triggers', 'acl', 'restarts'])
def test_system_phase_validates_semantic_duration_and_exact_task_boundary(run_ps, mutation):
    result = run_ps(r"""
$settings=[pscustomobject]@{MultipleInstances=2;RestartCount=0;AllowDemandStart=$true;ExecutionTimeLimit='PT1H5M';Enabled=$false}
$principal=[pscustomobject]@{UserId='SYSTEM';LogonType=5;RunLevel=1}
$action=[pscustomobject]@{Type=0;Path='C:\protected\python.exe';Arguments='-I -B fixture';WorkingDirectory='C:\protected'}
$actions=[pscustomobject]@{Count=1;Action=$action}
$actions|Add-Member ScriptMethod Item {param($number) $this.Action}
$definition=[pscustomobject]@{Settings=$settings;Principal=$principal;Actions=$actions;Triggers=[pscustomobject]@{Count=0}}
$task=[pscustomobject]@{Definition=$definition;Enabled=$false;Acl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'}
$task|Add-Member ScriptMethod GetSecurityDescriptor {param($mask) $this.Acl}
""" + {
        '': '', 'duration': "$settings.ExecutionTimeLimit='PT1M'",
        'principal': "$principal.UserId='ansac'", 'enabled': '$task.Enabled=$true',
        'arguments': "$action.Arguments='different'", 'triggers': '$definition.Triggers.Count=1',
        'acl': "$task.Acl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BU)'", 'restarts': '$settings.RestartCount=1',
    }[mutation] + r"""
$held=$false
try{Assert-R6PhaseTask $task 'C:\protected\python.exe' '-I -B fixture' 'C:\protected' 3900 $false}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
""")
    assert result['held'] is bool(mutation)


def test_phase_requires_pins_before_any_host_action(run_ps):
    data = run_ps("""
$script:called=$false
function Import-R6PhaseInstaller {$script:called=$true;throw 'must not reach imports'}
$held=$false
try{Invoke-R6PhaseMain 'native' 'invalid' ('b'*64) ('c'*64) ('a'*32) $true}catch{$held=$true}
@{held=$held;called=$script:called}|ConvertTo-Json -Compress
""")
    assert data == dict(held=True, called=False)


@pytest.mark.parametrize('state,ran,receipt,expected', [
    (3, True, True, 'True'), (3, True, False, 'held'),
    (3, False, False, 'False'), (4, True, True, 'False'), (2, True, False, 'False'),
])
def test_fast_completion_and_receiptless_exit_do_not_wait_for_full_timeout(run_ps, state, ran, receipt, expected):
    result = run_ps(r"""
$now=[DateTime]::UtcNow
$task=[pscustomobject]@{State=STATE;LastRunTime=$now.AddSeconds(OFFSET)}
$task|Add-Member ScriptMethod GetInstances {param($flags) @()}
function Test-Path {param($LiteralPath) RECEIPT}
try{$answer=[string](Test-R6PhaseFinished $task 'C:\fixture' $now)}catch{$answer='held'}
@{answer=$answer}|ConvertTo-Json -Compress
""".replace('STATE', str(state)).replace('OFFSET', '-1' if ran else '-100')
        .replace('RECEIPT', '$true' if receipt else '$false'))
    assert result['answer'] == expected
