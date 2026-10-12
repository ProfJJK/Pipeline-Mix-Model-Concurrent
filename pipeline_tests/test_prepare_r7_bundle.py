"""Verify immutable derivation from the delivered R6 config/installer."""
from pathlib import Path
import copy
import sys
import pytest

SCRIPTS=Path(__file__).parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
import prepare_r7_bundle as builder


def test_candidate_only_enables_catalog_and_keeps_exact_owner_matrix():
    raw=builder.PREVIOUS.read_bytes()
    import json
    before=json.loads(raw);candidate,change=builder.candidate_from_previous(raw)
    expected=copy.deepcopy(before);expected['catalog_activation']=True
    assert candidate==expected
    assert not change.changed_targets
    assert change.previous_policy_digest!=change.policy.digest
    assert candidate['routing']['catalog']['tiers']==change.policy.as_dict()['catalog']['tiers']


def test_candidate_refuses_changed_previous_bytes():
    with pytest.raises(ValueError,match='differs'):builder.candidate_from_previous(b'{}')


def test_stopped_installer_derivation_changes_only_two_revision_sites():
    before=(SCRIPTS/'install_r6_runtime.ps1').read_bytes()
    after=builder.derive_installer(before)
    assert after.replace(b'windows-20261012-r7-v1',b'windows-20261012-r6-v1')==before
    assert after.count(b'windows-20261012-r7-v1')==2
    with pytest.raises(ValueError):builder.derive_installer(before+b'windows-20261012-r6-v1')


def test_prerequisite_recovery_is_unchanged_except_explicit_inherited_input_deadline():
    raw=builder.RECOVERY.joinpath('run_r6_launch.ps1').read_bytes()
    result=builder.derive_recovery_entry(raw)
    assert b'[string]$OwnerInputDeadlineUtc' in result
    assert b'if($outer -lt $script:R6InputDeadline)' in result
    assert b"The owner-input window is already closed" in result
    assert builder.sha(builder.RECOVERY.joinpath('launch-manifest.json').read_bytes())==builder.RECOVERY_PIN
    with pytest.raises(ValueError):builder.derive_recovery_entry(raw+b'$script:R6InputDeadline=[DateTime]::UtcNow.AddMinutes(20)')


def test_fresh_recovery_repins_only_two_reviewed_helpers_and_deadline(tmp_path):
    import json
    destination = tmp_path/'recovery'
    result = builder.prepare_recovery(destination, Path(__file__).parents[1])
    before=json.loads(builder.RECOVERY.joinpath('launch-manifest.json').read_text())
    after=json.loads(destination.joinpath('launch-manifest.json').read_text())
    changed=[]
    for old,new in zip(before['scripts'],after['scripts'],strict=True):
        assert old['name']==new['name']
        payload=destination.joinpath(new['name']).read_bytes()
        assert builder.sha(payload)==new['sha256'] and len(payload)==new['length']
        if old!=new:changed.append(old['name'])
    assert set(changed)=={'run_r6_launch.ps1','r6_auth_recovery.py','verify_r6_auth_recovery.ps1'}
    assert result['reviewed_prefix_recovery']
    assert builder.sha(builder.RECOVERY.joinpath('launch-manifest.json').read_bytes())==builder.RECOVERY_PIN
