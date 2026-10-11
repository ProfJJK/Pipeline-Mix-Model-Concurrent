"""Native protocol parser fixtures; no live provider or subscription assertions."""
import json

import pytest

from cochem_pipeline.failures import ProviderFailure, parse_native_failure


@pytest.mark.parametrize(('provider','record','category','scope'), [
    ('codex', {'type':'turn.failed','error':{'code':'rate_limit_exceeded'}}, 'quota','pool'),
    ('codex', {'type':'error','message':"You've hit your usage limit. Try again later."}, 'quota','pool'),
    ('codex', {'type':'turn.failed','error':{'message':'Your input exceeds the context window of this model.'}}, 'context',None),
    ('claude', {'type':'result','subtype':'error_during_execution','is_error':True,'errors':["You've hit your limit · resets later"]}, 'quota','pool'),
    ('claude', {'type':'error','error':{'type':'authentication_error'}}, 'auth','pool'),
    ('claude', {'type':'result','subtype':'error_during_execution','is_error':True,'errors':[{'code':'overloaded_error'}]}, 'busy','model'),
    ('gemini', {'error':{'code':429,'status':'RESOURCE_EXHAUSTED'}}, 'quota','pool'),
    ('gemini', {'error':{'code':401}}, 'auth','pool'),
    ('gemini', {'error':{'code':503}}, 'busy','model'),
    ('gemini', {'error':{'code':502}}, 'provider','model'),
    ('codex', {'type':'turn.failed','error':{'code':'invalid_argument'}}, 'protocol',None),
    ('codex', {'type':'turn.failed','error':{'code':'request_timeout'}}, 'timeout',None),
    ('claude', {'type':'error','error':{'code':'connection_timeout'}}, 'timeout',None),
    ('gemini', {'error':{'code':408}}, 'timeout',None),
    ('gemini', {'error':{'status':'DEADLINE_EXCEEDED'}}, 'timeout',None),
])
def test_recognized_native_failure_envelopes(provider,record,category,scope):
    failure = parse_native_failure(provider,json.dumps(record),'',1)
    assert isinstance(failure,ProviderFailure)
    assert failure.category == category
    assert failure.hold_scope == scope
    assert record.get('message','DO NOT COPY RAW ERRORS') not in str(failure)


@pytest.mark.parametrize(('provider','record'), [
    ('codex', {'type':'item.completed','item':{'type':'agent_message','text':"You've hit your usage limit. 429 authentication_error"}}),
    ('codex', {'type':'item.completed','item':{'type':'command_execution','output':'{"type":"error","code":429}'}}),
    ('claude', {'type':'result','subtype':'success','is_error':False,'result':"You've hit your limit · resets later"}),
    ('claude', {'type':'assistant','message':{'content':[{'type':'text','text':'authentication_error'}]}}),
    ('gemini', {'response':'{"error":{"code":429}}','session_id':'fixture-session'}),
])
def test_generated_answers_and_tool_output_cannot_create_provider_holds(provider,record):
    assert parse_native_failure(provider,json.dumps(record),'',0) is None


@pytest.mark.parametrize('text', [
    "You've hit your usage limit.", 'Please log in',
    'Assistant says: {"type":"error","code":429}',
    'rate_limit_exceeded', '429 Authentication failed',
])
def test_unstructured_stderr_does_not_establish_availability(text):
    assert parse_native_failure('codex','',text,1) is None


def test_known_diagnostic_requires_anchor_inside_native_failure_envelope():
    data = {'type':'error','message':'The document says: You have hit your usage limit.'}
    assert parse_native_failure('codex',json.dumps(data),'',1).category == 'code'


def test_native_error_json_line_survives_unrelated_cli_warning():
    stderr = 'WARNING: optional shell integration unavailable\n'+json.dumps({'type':'error','error':{'status':429}})+'\n'
    assert parse_native_failure('codex','',stderr,1).category == 'quota'


def test_typed_cause_wins_over_native_diagnostic_text():
    data = {'type':'error','error':{'code':'authentication_error','message':"You've hit your usage limit."}}
    assert parse_native_failure('codex',json.dumps(data),'',1).category == 'auth'


@pytest.mark.parametrize(('hint','expected'), [(60,60.0),('12.5',12.5),(-7,0.0),(999999,86400.0),
                                               (True,None),('NaN',None),('Infinity',None),({},None)])
def test_retry_after_is_numeric_finite_and_bounded(hint,expected):
    record = {'type':'error','error':{'code':429,'retry_after_seconds':hint}}
    assert parse_native_failure('codex',json.dumps(record),'',1).retry_after_seconds == expected


def test_retry_info_duration_and_retry_after_header_are_supported():
    record = {'error':{'status':'RESOURCE_EXHAUSTED','headers':{'Retry-After':'17'},
                       'details':[{'@type':'type.googleapis.com/google.rpc.RetryInfo','retryDelay':'35.5s'}]}}
    assert parse_native_failure('gemini',json.dumps(record),'',1).retry_after_seconds == 35.5


def test_native_failed_terminal_remains_failure_on_zero_exit():
    data = {'type':'result','subtype':'error_during_execution','is_error':True,'errors':[{'type':'authentication_error'}]}
    assert parse_native_failure('claude',json.dumps(data),'',0).category == 'auth'


def test_context_failure_is_job_local_not_a_shared_provider_hold():
    failure = ProviderFailure('context')
    assert failure.hold_scope is None
    with pytest.raises(ValueError,match='globally'):
        ProviderFailure('context',hold_scope='pool')


def test_timeout_does_not_claim_provider_availability_or_allow_global_holds():
    failure = ProviderFailure('timeout')
    assert failure.hold_scope is None
    with pytest.raises(ValueError,match='globally'):
        ProviderFailure('timeout',hold_scope='pool')
    answer = {'type':'item.completed','item':{'type':'agent_message','text':'request_timeout'}}
    assert parse_native_failure('codex',json.dumps(answer),'',0) is None


def test_plain_native_messages_outside_allowlist_remain_execution_failures():
    failure = parse_native_failure('codex',json.dumps({'type':'turn.failed','error':{'message':'Internal tool diagnostic with private details'}}),'',1)
    assert failure.category == 'code'
    assert 'private details' not in str(failure)


@pytest.mark.parametrize('provider,record', [
    ('codex', {'type': 'turn.failed', 'error': {'code': 'model_not_found'}}),
    ('claude', {'type': 'error', 'error': {'type': 'unsupported_model'}}),
    ('gemini', {'error': {'code': 'model_not_available'}}),
])
def test_exact_native_unavailable_model_code_allows_canonical_fallback(provider, record):
    failure = parse_native_failure(provider, json.dumps(record), '', 1)
    assert failure.category == 'compatibility' and failure.hold_scope == 'model'
    assert 'model_not_available' not in str(failure)


def _claude_failed_result(text, **changes):
    return {'type':'result','subtype':'success','is_error':True,'result':text,**changes}


@pytest.mark.parametrize(('text','category','scope'), [
    ('Failed to authenticate. API Error: 401 {"type":"error","error":{"type":"authentication_error"}}', 'auth','pool'),
    ('API Error: 401 {"type":"error","error":{"message":"OAuth token has expired."}}', 'auth','pool'),
    ('Invalid API key · Please run /login', 'auth','pool'),
    ('OAuth token has expired. Please obtain a new token or refresh your existing token.', 'auth','pool'),
    ('Failed to authenticate', 'auth','pool'),
    ('Please run /login', 'auth','pool'),
    ('API Error: 429 {"type":"error","error":{"type":"rate_limit_error"}}', 'quota','pool'),
    ('  api error:429 rate limited', 'quota','pool'),
    ('API Error: 529 {"type":"error","error":{"type":"overloaded_error"}}', 'busy','model'),
    ('API Error: 503 Service Unavailable', 'busy','model'),
    ('API Error: 500 {"type":"error","error":{"type":"api_error"}}', 'provider','model'),
    ('API Error: 502 Bad Gateway', 'provider','model'),
    ('API Error: 504 Gateway Timeout', 'provider','model'),
    ('API Error: 408 Request Timeout', 'timeout',None),
    ('API Error: 400 {"type":"error","error":{"type":"invalid_request_error"}}', 'code',None),
    ('Prompt is too long', 'context',None),
    ("You've hit your limit · resets later", 'quota','pool'),
])
def test_claude_failed_result_text_maps_anchored_api_status_and_diagnostics(text,category,scope):
    failure = parse_native_failure('claude',json.dumps(_claude_failed_result(text)),'',1)
    assert isinstance(failure,ProviderFailure)
    assert failure.category == category
    assert failure.hold_scope == scope
    assert text.strip() not in str(failure)
    assert text.strip()[:12] not in str(failure)


def test_claude_error_subtype_result_without_is_error_is_a_failed_envelope():
    record = {'type':'result','subtype':'error_during_execution','result':'API Error: 401 {"type":"error"}'}
    failure = parse_native_failure('claude',json.dumps(record),'',1)
    assert (failure.category,failure.hold_scope) == ('auth','pool')


@pytest.mark.parametrize('text', [
    # A leading API status decides alone: an unmapped status is not re-read as auth text.
    'Failed to authenticate. API Error: 403 {"type":"error","error":{"type":"permission_error"}}',
    'API Error: 404 {"type":"error","error":{"type":"not_found_error"}}',
    'Request failed. API Error: 401',
    'The model wrote: Invalid API key',
    'Invalid API keys are rotated weekly',
    'API Error: 4011 unexpected',
    'API Error 401',
    'API Error: \u0664\u0660\u0661',
    ' '*4096 + 'API Error: 401',
    'Internal tool diagnostic with private details',
])
def test_claude_failed_result_text_requires_a_leading_anchored_diagnostic(text):
    failure = parse_native_failure('claude',json.dumps(_claude_failed_result(text)),'',1)
    assert failure.category == 'code' and failure.hold_scope is None
    assert text.strip() not in str(failure)


def test_claude_failed_result_non_text_result_keeps_execution_fallback():
    record = _claude_failed_result({'text':'API Error: 401'})
    assert parse_native_failure('claude',json.dumps(record),'',1).category == 'code'


@pytest.mark.parametrize('record', [
    {'type':'result','subtype':'success','is_error':False,'result':'API Error: 401 {"type":"error"}'},
    {'type':'result','subtype':'success','is_error':False,'result':'Invalid API key · Please run /login'},
    {'type':'result','subtype':'success','is_error':False,'result':'OAuth token has expired.'},
    {'type':'result','subtype':'success','result':'API Error: 429 rate limited'},
    {'type':'assistant','message':{'content':[{'type':'text','text':'API Error: 401 {"type":"error"}'}]}},
    {'type':'assistant','message':{'content':[{'type':'text','text':'Invalid API key · Please run /login'}]}},
    {'type':'user','message':{'content':[{'type':'tool_result','is_error':True,'content':'API Error: 529 overloaded'}]}},
    {'type':'user','message':{'content':[{'type':'tool_result','is_error':True,'content':'Failed to authenticate'}]}},
])
def test_claude_answers_and_tool_content_never_classify_from_text(record):
    assert parse_native_failure('claude',json.dumps(record),'',0) is None
    assert parse_native_failure('claude',json.dumps(record),'',1) is None


@pytest.mark.parametrize('is_error', [False, 0, 'true', None])
def test_claude_result_text_without_literal_is_error_true_stays_data(is_error):
    # The error_* subtype still makes this a failed envelope, but its text is not read.
    record = {'type':'result','subtype':'error_max_turns','is_error':is_error,'result':'API Error: 401 {"type":"error"}'}
    assert parse_native_failure('claude',json.dumps(record),'',1).category == 'code'


def test_claude_typed_codes_and_error_messages_win_over_result_text():
    typed = _claude_failed_result('API Error: 401',subtype='error_during_execution',errors=[{'type':'overloaded_error'}])
    assert parse_native_failure('claude',json.dumps(typed),'',1).category == 'busy'
    listed = _claude_failed_result('API Error: 401',subtype='error_during_execution',errors=["You've hit your limit · resets later"])
    assert parse_native_failure('claude',json.dumps(listed),'',1).category == 'quota'


def test_claude_result_status_honours_retry_hint_from_failed_envelope():
    record = _claude_failed_result('API Error: 429 rate limited',retry_after_seconds=45)
    failure = parse_native_failure('claude',json.dumps(record),'',1)
    assert (failure.category,failure.retry_after_seconds) == ('quota',45.0)


@pytest.mark.parametrize(('provider','record'), [
    ('codex', {'type':'error','message':'Opaque native failure','result':'API Error: 401'}),
    ('codex', {'type':'turn.failed','error':{'message':'Opaque native failure'},'result':'Invalid API key'}),
    ('gemini', {'type':'result','is_error':True,'error':{'message':'Opaque native failure'},'result':'API Error: 401'}),
])
def test_result_text_reclassification_is_claude_only(provider,record):
    assert parse_native_failure(provider,json.dumps(record),'',1).category == 'code'
