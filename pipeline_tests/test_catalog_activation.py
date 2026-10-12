"""Pure R7 preparation fixtures: no native model, host or protected-state access."""
import hashlib
import json

import pytest

from cochem_pipeline.catalog_activation import compile_change, decode_proposal
from cochem_pipeline.routing import load_routing_policy


def inputs():
    current=load_routing_policy({'policy_version':3})
    catalog=current.as_dict()['catalog']
    catalog['generation']='fixture-generation-2'
    return current,catalog


def test_reorder_preserves_operational_policy_and_old_capture():
    current,catalog=inputs();before=current.as_dict()
    catalog['tiers']['4'].reverse()
    change=compile_change(current,catalog,expected_policy_digest=current.digest)
    assert change.policy.as_dict()['tiers']['4']==catalog['tiers']['4']
    for key,value in before.items():
        if key not in ('tiers','catalog'):assert change.policy.as_dict()[key]==value
    assert change.changed_targets==()
    assert change.control_target==('gemini','gemini-3.8-flash','low')
    assert current.as_dict()==before
    assert not change.as_dict()['activation_authorized']
    assert not change.as_dict()['native_acceptance_completed']


def test_new_target_is_probed_once_despite_multiple_positions_and_detaches_input():
    current,catalog=inputs()
    # A synthetic name is fixture data, never a future provider availability claim.
    for tier in ('5','6'):catalog['tiers'][tier][2]['model']='fixture-pro-next'
    change=compile_change(current,catalog,expected_policy_digest=current.digest)
    assert change.changed_targets==( ('gemini','fixture-pro-next','high'), )
    digest=change.digest;catalog['tiers']['6'][2]['model']='edited-after-compile'
    assert change.digest==digest
    detached=change.as_dict();detached['policy']['tiers']['6'].clear()
    assert change.digest==digest


@pytest.mark.parametrize('fault',['stale','same_generation','legacy','discard_cap'])
def test_unsafe_transitions_refused(fault):
    current,catalog=inputs();expected=current.digest
    if fault=='stale':expected='0'*64
    if fault=='same_generation':catalog['generation']=current.as_dict()['catalog']['generation']
    if fault=='legacy':current=load_routing_policy({'policy_version':2});expected=current.digest
    if fault=='discard_cap':
        raw=current.as_dict();raw['model_limits']['gemini:gemini-3.1-pro:high']=1
        current=load_routing_policy(raw);expected=current.digest
        for tier in ('5','6'):catalog['tiers'][tier][2]['model']='fixture-pro-next'
    with pytest.raises(ValueError):compile_change(current,catalog,expected_policy_digest=expected)


def test_strict_proposal_decoder_binds_current_state_and_exact_bytes():
    current,catalog=inputs()
    raw=dict(schema='cochem-catalog-change-request/1',previous_policy_digest=current.digest,catalog=catalog)
    data=json.dumps(raw).encode();pin=hashlib.sha256(data).hexdigest()
    assert decode_proposal(data,current,expected_sha256=pin).policy.as_dict()['catalog']==catalog
    with pytest.raises(ValueError):decode_proposal(data+b' ',current,expected_sha256=pin)
    duplicate=data[:-1]+b',"schema":"cochem-catalog-change-request/1"}'
    with pytest.raises(ValueError,match='Duplicate'):
        decode_proposal(duplicate,current,expected_sha256=hashlib.sha256(duplicate).hexdigest())


def test_unknown_controls_cannot_hide_in_proposal():
    current,catalog=inputs()
    data=json.dumps(dict(schema='cochem-catalog-change-request/1',previous_policy_digest=current.digest,
        catalog=catalog,max_execution_slots=100)).encode()
    with pytest.raises(ValueError,match='unexpected fields'):
        decode_proposal(data,current,expected_sha256=hashlib.sha256(data).hexdigest())
