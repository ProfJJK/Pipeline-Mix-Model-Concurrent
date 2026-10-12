"""Actual PowerShell 5.1, in-process fake Task Scheduler and temp receipts only."""
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parents[1]
MIRROR = ROOT/'docs/deployment/windows-deployment-next'


@pytest.fixture
def legacy(monkeypatch):
    monkeypatch.syspath_prepend(str(MIRROR))
    spec = importlib.util.spec_from_file_location('r6_core_fixture', MIRROR/'test_retarget_warden_r5.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SCRIPT = ROOT/'scripts/r6_retarget_core.ps1'
    return module


@pytest.mark.parametrize('case', [
    'backup_mismatch','controller_appears_before_mutation','port_busy_before_mutation',
    'task_changes_during_preparation','readback_denied','xml_outside_changed',
    'register_leaves_enabled','receipt_collision',
])
def test_inherited_retarget_preserves_failure_boundaries(legacy, tmp_path, case):
    legacy.test_retarget_mutation_path_is_driven_with_fixtures(tmp_path, case)


@pytest.mark.parametrize('health,expect_held', [('healthy',False),('not_ready',True)])
def test_r6_target_uses_two_phase_start_and_disables_on_failure(legacy, tmp_path, health, expect_held):
    # Use the released inert harness. Only context.target changes to r6; its
    # fake task actions remain synthetic paths and never touch the host.
    root=tmp_path/'cutover';root.mkdir()
    script = '@("A","A")' if health=='healthy' else '@("A","N","N")'
    body = legacy.FIXTURE + legacy.ENV_STUBS + legacy.HEALTH_FIXTURE
    body += f"$script:Target='r5';$script:targetRoot='{legacy.ps(root)}';$script:healthScript={script};$script:proofFails=$false;"
    body += legacy.START_BODY.replace('__LIVE__','$over').replace('__SDDL__',legacy.SDDL).replace('__PRE__','').replace('__POST__','')
    body += r"""
$context.target='r6';$context.started_status='WARDEN_R6_RUNNING_HEALTH_VERIFIED'
$failed=$false;$message='';$result=$null
try{$result=Invoke-StartOnce $folder $context $binding}catch{$failed=$true;$message=$_.Exception.Message}
@{failed=$failed;message=$message;events=@($script:events);result=$result;enabled=$script:taskEnabled;
  triggers=@($script:triggerItems|ForEach-Object {$_.Enabled});runs=$script:runCalls;
  held=(Test-Path (Join-Path $script:targetRoot 'start-held.json'))}|ConvertTo-Json -Depth 8 -Compress
"""
    data=legacy.run(tmp_path,body,timeout=30)
    assert data['failed'] is expect_held, data
    assert 'end' not in data['events']
    assert data['runs']==1
    if expect_held:
        assert data['held'] and not data['enabled']
    else:
        assert data['result']['target']=='r6'
        assert data['result']['status']=='WARDEN_R6_RUNNING_HEALTH_VERIFIED'
        assert data['triggers']==[True]
