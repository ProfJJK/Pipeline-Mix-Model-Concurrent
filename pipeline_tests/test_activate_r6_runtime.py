from pathlib import Path

import pytest

from pipeline_tests import test_install_r6_runtime as ps_fixture


@pytest.fixture
def run_ps(monkeypatch):
    monkeypatch.setattr(ps_fixture, 'SCRIPT', Path(__file__).parents[1]/'scripts/activate_r6_runtime.ps1')
    return ps_fixture.run_ps


def test_activation_rejects_missing_pins_before_import_or_host_action(run_ps):
    result=run_ps("""
$script:imported=$false
function Import-R6ActivationFunctions {$script:imported=$true;throw 'unexpected import'}
$refused=$false
try{Invoke-R6Activation 'wrong' ('b'*64) ('c'*64) ('d'*64) 'bad path' ('e'*64) 'v1' '' '' $true}catch{$refused=$true}
@{refused=$refused;imported=$script:imported}|ConvertTo-Json -Compress
""")
    assert result == dict(refused=True, imported=False)


def test_r6_context_names_r6_in_action_receipts_and_new_queue(run_ps):
    result=run_ps(r"""
$script:privateRoot='C:\fixture\private';$script:Attempt='v1'
function Get-R5Arguments {param($Config,$Queue,$Wait) '-I -B daemon '+$Config+' '+$Queue+' '+$Wait}
function Get-TriggerReceiptForm {param($Target) ,@(@{type='logon';target=$Target})}
$runtime=@{root='C:\fixture\r6';python='C:\fixture\r6\.venv\Scripts\python.exe';source_root='C:\fixture\r6\.venv\Lib';
install_after_path='C:\fixture\r6\install-after.json';install_after_sha256=('a'*64);revision_sha256=('b'*64);source_manifest_sha256=('c'*64)}
New-R6TargetContext $runtime ('d'*64)|ConvertTo-Json -Depth 8 -Compress
""")
    assert result['target']=='r6' and result['started_status']=='WARDEN_R6_RUNNING_HEALTH_VERIFIED'
    assert result['action']['arguments'].endswith(r'C:\fixture\private\queue-launch-r6 900')
    assert result['triggers'][0]['target']=='r6'


def test_index_rejects_duplicate_phases_before_private_receipt_access(run_ps):
    result=run_ps("""
function Test-Path {param($LiteralPath) $false}
function Assert-PrivateAcl {param($Path) throw 'private read must not happen for invalid index'}
$refused=$false
$index=@{schema='cochem-r6-acceptance-index/1';manifest_sha256=('a'*64);candidate_sha256=('b'*64);phases=@()}
try{Assert-R6AcceptanceIndex $index ('a'*64) ('b'*64)}catch{$refused=$true}
@{refused=$refused}|ConvertTo-Json -Compress
""")
    assert result['refused']


@pytest.mark.parametrize('pro_verified',[True,False])
def test_quota_limited_upper_tiers_do_not_block_verified_pro_but_pro_is_mandatory(run_ps,pro_verified):
    result=run_ps(r"""
function Test-Path {param($LiteralPath) $false}
function Assert-PrivateAcl {param($Path)}
function Test-ExactBool {param($Value,$Expected) ($Value -is [bool] -and $Value -eq $Expected)}
function Read-R3Control {param($Path,$Pin,$Bound) $Path}
function Read-R3Text {param($Path)
    $phase=($Path -split 'v1-')[1].Split('-')[0]
    $result=switch($phase){
        auth {@{status='ALL_SESSIONS_VERIFIED';checks=@(1..18|ForEach-Object {@{authenticated=$true}})}}
        agent {@{status='SIX_WORKER_AGENT_CUSTODY_VERIFIED'}}
        knowledge {@{status='NEW_KNOWLEDGE_AUTHORITY_VERIFIED'}}
        preview {@{identities=@();database=@{schema_changes=@();migration_executed=$false}}}
        native {
            $targets=@(1..26|ForEach-Object {@{status='NOT_PROBED_POOL_UNAVAILABLE'}})
            $targets+=@{status='PRO_STATUS';provider='gemini';model='gemini-3.1-pro';effort='high';route_positions=@(@{tier=5},@{tier=6})}
            @{status='NATIVE_ACCEPTANCE_PARTIAL_AVAILABILITY';targets=$targets}}
    }
    @{schema='cochem-r6-system-phase/1';phase=$phase;status='PHASE_COMPLETED';manifest_sha256=('a'*64);
      candidate_sha256=('b'*64);revision=@{verified=$true;source_sha256=('c'*64)};result=$result}|ConvertTo-Json -Depth 15 -Compress
}
$index=@{schema='cochem-r6-acceptance-index/1';manifest_sha256=('a'*64);candidate_sha256=('b'*64);
 phases=@('auth','agent','knowledge','native','preview'|ForEach-Object {@{phase=$_;receipt_sha256=('d'*64);
 receipt_path=('C:\Program Files\CoChem\R6Acceptance4.2.7-windows-20261012-v1-'+$_+'-'+('e'*32)+'\result.json')}})}
$accepted=$false
try{$null=Assert-R6AcceptanceIndex $index ('a'*64) ('b'*64);$accepted=$true}catch{}
@{accepted=$accepted}|ConvertTo-Json -Compress
""".replace('PRO_STATUS','NATIVE_SELECTOR_ACCEPTED' if pro_verified else 'PROVIDER_TEMPORARILY_UNAVAILABLE'))
    assert result['accepted'] is pro_verified


@pytest.mark.parametrize('fault',['none','hash','plan','target','count','replacement','probed','accepted_pro','protocol'])
def test_retirement_amendment_is_bound_to_original_plan_and_never_attests_pro(run_ps,fault):
    result=run_ps(r"""
function Test-Path {param($LiteralPath) $false}
function Assert-PrivateAcl {param($Path)}
function Test-ExactBool {param($Value,$Expected) ($Value -is [bool] -and $Value -eq $Expected)}
function Read-R3Control {param($Path,$Pin,$Bound) $Path}
function Read-R3Text {param($Path)
    $phase=($Path -split 'v1-')[1].Split('-')[0]
    $result=switch($phase){
        auth {@{status='ALL_SESSIONS_VERIFIED';checks=@(1..18|ForEach-Object {@{authenticated=$true}})}}
        agent {@{status='SIX_WORKER_AGENT_CUSTODY_VERIFIED'}}
        knowledge {@{status='NEW_KNOWLEDGE_AUTHORITY_VERIFIED'}}
        preview {@{identities=@();database=@{schema_changes=@();migration_executed=$false}}}
        native {
            $targets=@(1..26|ForEach-Object {@{status='NOT_PROBED_POOL_UNAVAILABLE';provider='codex';model='fixture-selector'}})
            $retirement=@{schema='cochem-owner-model-retirement/1';decision='owner-2026-10-12-pro-retired';
                helper_sha256=('f'*64);original_plan_sha256=('9'*64);retired_target=@{provider='gemini';model='gemini-3.1-pro';reasoning_effort='high'};
                retired_status='OWNER_RETIRED_MODEL_NOT_PROBED';retired_model_jobs_executed=0;replacement_selected=$false}
            switch('FAULT'){
                hash {$retirement.helper_sha256=('0'*64)}
                plan {$retirement.original_plan_sha256=('0'*64)}
                target {$retirement.retired_target.reasoning_effort='low'}
                count {$targets=$targets[0..24]}
                replacement {$retirement.replacement_selected=$true}
                probed {$retirement.retired_model_jobs_executed=1}
                accepted_pro {$targets[0]=@{provider='gemini';model='gemini-3.1-pro';status='NATIVE_SELECTOR_ACCEPTED';effort='high';route_positions=@(@{tier=5})}}
                protocol {$targets[0].status='PROVIDER_PROTOCOL_FAILED'}
            }
            @{status='NATIVE_ACCEPTANCE_PARTIAL_AVAILABILITY';targets=$targets;count=$targets.Count;owner_retirement=$retirement}}
    }
    @{schema='cochem-r6-system-phase/1';phase=$phase;status='PHASE_COMPLETED';manifest_sha256=('a'*64);native_plan_sha256=('9'*64);
      candidate_sha256=('b'*64);revision=@{verified=$true;source_sha256=('c'*64)};result=$result}|ConvertTo-Json -Depth 15 -Compress
}
$index=@{schema='cochem-r6-acceptance-index/1';manifest_sha256=('a'*64);candidate_sha256=('b'*64);
 phases=@('auth','agent','knowledge','native','preview'|ForEach-Object {@{phase=$_;receipt_sha256=('d'*64);
 receipt_path=('C:\Program Files\CoChem\R6Acceptance4.2.7-windows-20261012-v1-'+$_+'-'+('e'*32)+'\result.json')}})}
$accepted=$false
try{$null=Assert-R6AcceptanceIndex $index ('a'*64) ('b'*64) ('f'*64);$accepted=$true}catch{}
@{accepted=$accepted}|ConvertTo-Json -Compress
""".replace('FAULT',fault))
    assert result['accepted'] is (fault=='none')
