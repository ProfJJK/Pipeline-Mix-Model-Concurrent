"""Inert HTTP-client error fixtures; not a claim of host quota acceptance."""
import json
from pathlib import Path

import pytest

from cochem_pipeline import failures, worker, agy_protocol
from scripts import r6_custody_amendment as amendment
from pipeline_tests.test_r6_registry_amendment import frozen


def repaired():
    raw = (Path(__file__).parent / 'fixtures/r6_failures_359ca92.txt').read_bytes()
    return amendment.failure_module(raw, failures)


@pytest.mark.parametrize('status,category', [(429, 'quota'), (503, 'busy'), (500, 'provider'), (400, 'code')])
@pytest.mark.parametrize('prefix', ['', 'API Error: '])
def test_frozen_and_source_parser_agree_without_changing_exception_identity(status, category, prefix):
    text = prefix + f'Request failed with status code {status}'
    raw = json.dumps(dict(type='result', subtype='success', is_error=True, result=text))
    parsers = [failures.parse_native_failure, repaired().parse_native_failure]
    for parse in parsers:
        result = parse('claude', raw, '', 1)
        assert type(result) is failures.ProviderFailure
        assert result.category == category
        assert text not in str(result)
    evidence = worker.native_failure_metadata('claude', category, 1, raw.encode(), b'',
                                             started_at=1, finished_at=2)
    assert evidence['api_status'] == status
    assert evidence['envelope_kind'] == 'claude_result_is_error'


def test_frozen_callback_uses_reviewed_parser_and_known_source():
    parse = repaired().parse_native_failure
    _, _, run = amendment.registry_modules(*frozen(), {}, agy_protocol, worker, failure_parser=parse)
    assert run.__globals__['parse_native_failure'] is parse
    assert failures._CLAUDE_RESULT_API_STATUS == amendment.CLAUDE_HTTP_STATUS
    assert worker._CLAUDE_RESULT_API_STATUS.pattern == amendment.CLAUDE_HTTP_STATUS
    raw = (Path(__file__).parent / 'fixtures/r6_failures_359ca92.txt').read_bytes()
    with pytest.raises(ValueError, match='source binding'):
        amendment.failure_module(raw + b'\n', failures)


@pytest.mark.parametrize('result', [
    'Response text: Request failed with status code 429',
    'Request failed with status code 4290',
    'Request failed with status code 429x',
    'Request failed with status code \u0664\u0662\u0669',
    'HTTP 429 appears in the task data',
])
def test_similar_text_does_not_classify(result):
    raw = json.dumps(dict(type='result', subtype='success', is_error=True, result=result))
    assert repaired().parse_native_failure('claude', raw, '', 1).category == 'code'


def test_successful_model_output_cannot_trigger_hold():
    raw = json.dumps(dict(type='result', subtype='success', is_error=False,
                          result='Request failed with status code 429'))
    assert repaired().parse_native_failure('claude', raw, '', 1) is None
