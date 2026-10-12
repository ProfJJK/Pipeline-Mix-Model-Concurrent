"""Inert Windows PowerShell functions; no tasks, services or providers execute."""
from pathlib import Path
import hashlib
import pytest
from pipeline_tests import test_install_r6_runtime as ps_fixture


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(ps_fixture,'SCRIPT',Path(__file__).parents[1]/'scripts/run_r7_launch.ps1')
    return ps_fixture.run_ps


def test_input_pin_holds_bytes_until_disposal_under_strict_mode(run_ps,tmp_path):
    p=tmp_path/'pinned.json';p.write_bytes(b'{"value":7}')
    body="""
$s=Open-R7Pin 'PATH' 'PIN' 11
try{
    $row=Read-R7Json $s;$blocked=$false
    try{$write=[IO.File]::Open('PATH','Open','Write','ReadWrite');$write.Dispose()}catch{$blocked=$true}
    @{value=$row.value;blocked=$blocked;position=$s.Position}|ConvertTo-Json -Compress
}finally{$s.Dispose()}
""".replace('PATH',str(p).replace("'","''")).replace('PIN',hashlib.sha256(p.read_bytes()).hexdigest())
    assert run_ps(body)==dict(value=7,blocked=True,position=0)


@pytest.mark.parametrize('pin,length',[('invalid',11),('a'*64,11),('',11)])
def test_pin_failure_precedes_execution(run_ps,tmp_path,pin,length):
    p=tmp_path/'input';p.write_bytes(b'{"value":7}')
    row=run_ps(f"$held=$false;try{{$null=Open-R7Pin '{p}' '{pin}' {length}}}catch{{$held=$true}};@{{held=$held}}|ConvertTo-Json -Compress")
    assert row['held']


def test_definition_projection_only_allows_actions_and_enabled_flags(run_ps):
    row=run_ps(r'''
$original='<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers><Settings><Enabled>true</Enabled><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><ExecutionTimeLimit>PT0S</ExecutionTimeLimit></Settings><Actions><Exec><Command>old</Command><Arguments>old</Arguments><WorkingDirectory>old</WorkingDirectory></Exec></Actions></Task>'
$updated=$original.Replace('<Enabled>true</Enabled>','<Enabled>false</Enabled>').Replace('>old<','>new<')
$bad=$updated.Replace('IgnoreNew','Parallel')
@{allowed=((Get-R7InvariantDefinition $original) -ceq (Get-R7InvariantDefinition $updated));
 denied=((Get-R7InvariantDefinition $original) -cne (Get-R7InvariantDefinition $bad))}|ConvertTo-Json -Compress
''')
    assert row==dict(allowed=True,denied=True)


def test_uncertain_migration_does_not_restore_or_start_any_controller(run_ps):
    row=run_ps(r'''
$script:events=[Collections.Generic.List[string]]::new()
function Assert-R7PortFree {$script:events.Add('port')}
function Invoke-R7Migration {$script:events.Add('migration');throw 'must not run'}
$held=$false;try{$null=Restore-R7BeforeStart $null $null '' '' '' $true $false}catch{$held=$true}
@{held=$held;events=@($script:events)}|ConvertTo-Json -Compress
''')
    assert row==dict(held=True,events=['port'])


def test_sanitized_status_has_no_provider_or_secret_output(run_ps):
    row=run_ps(r'''
$script:R7Sitting='C:\fixture\sitting';$script:targetRoot='C:\fixture\runtime'
function Write-R6InstallRecord {param($Name,$Value) $script:saved=$Value;$script:directory=$script:targetRoot}
Write-R7Status 'migration' 'HELD' @{error_type='ValueError';automatic_retry=$false}
@{record=$script:saved;directory=$script:directory;restored=$script:targetRoot}|ConvertTo-Json -Depth 6 -Compress
''')
    assert row['restored']==r'C:\fixture\runtime' and row['directory']==r'C:\fixture\sitting'
    assert row['record']['result']==dict(error_type='ValueError',automatic_retry=False)
    assert not row['record']['late_prompt'] and not row['record']['full_srs_acceptance']


def test_no_attended_commands_after_walkaway_boundary():
    script=(Path(__file__).parents[1]/'scripts/run_r7_launch.ps1').read_text()
    tail=script.split("Write-Host 'R6 prerequisites verified.")[1]
    assert 'Read-Host' not in tail and 'RunAs' not in tail and 'login' not in tail
    assert '-NonInteractive' in tail and 'Restore-R7BeforeStart' in tail
    assert 'if($stopped -and -not $startRequested)' in tail
    assert 'clear' not in tail.lower().split("$phase='catalog_publication'")[1]


def test_completed_r6_is_reused_without_running_recovery(run_ps):
    row=run_ps(r'''
function Get-R7CompletedR6 {param($Pin) [pscustomobject]@{status='completed'}}
function Open-R7Pin {throw 'recovery must not execute'}
Invoke-R7Prerequisite ([pscustomobject]@{expected_r6_candidate_sha256=('a'*64)}) 'C:\fixture' ([DateTime]::UtcNow)
@{reused=$true}|ConvertTo-Json -Compress
''')
    assert row==dict(reused=True)


def test_multiple_r6_completion_records_refuse_automatic_recovery(run_ps):
    row=run_ps(r'''
function Get-R7CompletedR6 {param($Pin) @('first','second')}
function Open-R7Pin {throw 'recovery must not execute'}
$held=$false;try{Invoke-R7Prerequisite ([pscustomobject]@{expected_r6_candidate_sha256=('a'*64)}) 'C:\fixture' ([DateTime]::UtcNow)}catch{$held=$true}
@{held=$held}|ConvertTo-Json -Compress
''')
    assert row==dict(held=True)


@pytest.mark.parametrize('fail',[False,True])
def test_awake_request_is_temporary_and_failure_precedes_deployment(run_ps,fail):
    # Fake native methods: this never makes an OS power request.
    row=run_ps(r'''
Add-Type -TypeDefinition @'
using System.Collections.Generic;
public static class CoChemR7Awake {
 public static List<uint> Calls = new List<uint>();
 public static uint GetCurrentThreadId() { return 7; }
 public static uint SetThreadExecutionState(uint flags) { Calls.Add(flags); return RETURN; }
}
'@
$held=$false;$lease=$null
try{$lease=Start-R7AwakeLease}catch{$held=$true}
if($null -ne $lease){Stop-R7AwakeLease $lease}
@{held=$held;calls=@([CoChemR7Awake]::Calls)}|ConvertTo-Json -Compress
'''.replace('RETURN','0' if fail else '2147483648'))
    assert row['held'] is fail
    assert row['calls']==([2147483649] if fail else [2147483649,2147483648])
