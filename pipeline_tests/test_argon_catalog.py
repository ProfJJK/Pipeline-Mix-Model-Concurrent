"""Offline exact-selector preparation; no Agy process or authentication."""
from copy import deepcopy
import pytest

from cochem_pipeline.argon_catalog import prepare_argon_candidate
from cochem_pipeline.agy_protocol import native_model_binding


def inputs():
    spec = dict(protocol='agy-stream-json', identity_policy='reported-model-equality',
        model_bindings={'gemini-3.8-flash': 'gemini-3.8-flash-low'},
        inference_only=dict(executable_sha256='a'*64, version='1.3.1', version_arguments=['--version']))
    capture = dict(schema='cochem-agy-catalog-capture/1', executable_sha256='a'*64,
        version='1.3.1', catalog_sha256='b'*64,
        model_slugs=['gemini-4-argon-'+e for e in ('low','medium','high')])
    return spec, capture


def test_three_exact_efforts_prepare_without_claiming_acceptance():
    spec, capture = inputs()
    original = deepcopy(spec)
    result = prepare_argon_candidate(spec, capture)
    assert spec == original and len(result['probes']) == 3
    assert not result['activation_ready'] and result['provider_commands_executed'] == 0
    for effort in ('low','medium','high'):
        assert native_model_binding(result['native_spec'], 'gemini-4-argon', effort) == {
            'argv': 'gemini-4-argon-'+effort, 'reports': 'gemini-4-argon-'+effort}


def test_missing_low_does_not_borrow_high_or_invent_a_selector():
    spec, capture = inputs()
    capture['model_slugs'].remove('gemini-4-argon-low')
    result = prepare_argon_candidate(spec, capture)
    assert len(result['probes']) == 2
    assert result['holds'][0]['effort'] == 'low'
    with pytest.raises(ValueError):
        native_model_binding(result['native_spec'], 'gemini-4-argon', 'low')


@pytest.mark.parametrize('field,value', [('version','different'), ('executable_sha256','c'*64),
    ('catalog_sha256','bad'), ('model_slugs',['gemini-4-argon-high','gemini-4-argon-high'])])
def test_unbound_or_ambiguous_catalog_rejected(field, value):
    spec, capture = inputs()
    capture[field] = value
    with pytest.raises(ValueError):
        prepare_argon_candidate(spec, capture)
