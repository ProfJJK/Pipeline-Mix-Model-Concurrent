import importlib.util
import json
import hashlib
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('auth_recovery', Path(__file__).parents[1]/'scripts/r6_auth_recovery.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_captured_agy_signed_out_line_is_status_only_logout():
    line = 'Please sign in to view available models. Launch the CLI without arguments to sign in.'
    result = module.classify_agy_status('', line, 1)
    assert result['status'] == 'ATTENDED_LOGIN_REQUIRED'
    assert result['reason'] == 'AGY_MODELS_EXPLICIT_SIGN_OUT'


def test_owner_reported_122_byte_error_is_exact_signed_out_protocol():
    raw = (b'Fetching available models...\n'
        b'Error: Please sign in to view available models. Launch the CLI without arguments to sign in.\n')
    assert len(raw) == 122
    assert hashlib.sha256(raw).hexdigest() == '148fc48c6aeaf4d5f5780d0e38fc39215de098c1537c57e09410d4dad9718a1d'
    result = module.classify_agy_status('', raw.decode(), 1)
    assert result['status'] == 'ATTENDED_LOGIN_REQUIRED'
    assert result['diagnostic_hint'] == 'Subscription authentication failed'


@pytest.mark.parametrize('suffix', [' secret', '\nPermission denied', '\nAGY_ERROR: {"code":"rate_limit_exceeded"}'])
def test_prefixed_signout_with_extra_failure_stays_unverified(suffix):
    text = 'Error: Please sign in to view available models. Launch the CLI without arguments to sign in.' + suffix
    assert module.classify_agy_status('', text, 1)['status'] == 'STATUS_UNVERIFIED'


def test_unknown_status_evidence_is_private_bounded_and_never_overwritten(tmp_path, monkeypatch):
    import cochem_pipeline.windows as win
    checks = []
    monkeypatch.setattr(win, 'validate_private_directory', lambda root: checks.append(root))
    module.preserve_unknown_status(tmp_path, 'slot1', b'', b'private diagnostic')
    assert (tmp_path/'agy-slot1-unknown.stderr').read_bytes() == b'private diagnostic'
    with pytest.raises(FileExistsError):
        module.preserve_unknown_status(tmp_path, 'slot1', b'', b'changed')
    with pytest.raises(ValueError):
        module.preserve_unknown_status(tmp_path, '../bad', b'', b'')
    with pytest.raises(ValueError):
        module.preserve_unknown_status(tmp_path, 'slot2', b'x'*65537, b'')
    assert checks == [tmp_path]*4


@pytest.mark.parametrize('text', ['', 'network failed', 'Please sign in to view available models secret-extra',
    '{"result":"Please sign in to view available models"}', 'Error: access denied: secret@example.com'])
def test_unknown_exit_is_never_treated_as_logout_and_diagnostics_do_not_leak(text):
    result = module.classify_agy_status('', text, 1)
    assert result['status'] == 'STATUS_UNVERIFIED'
    assert 'secret' not in json.dumps(result)
    assert text == '' or text not in json.dumps(result)


@pytest.mark.parametrize('models,expected', [([], False), ([{'id':'other', 'label':'Other'}],False),
    ([{'id':'gemini-fixture', 'label':'Fixture'}],True), ([{'id':'gemini-fixture'}],False)])
def test_success_requires_gemini_catalog_rows(models, expected):
    text=json.dumps({'status':'SUCCESS','command':{'name':'models','data':{'models':models}}})
    assert module.classify_agy_status(text,'Fetching available models...',0)['authenticated'] is expected


def test_typed_quota_does_not_trigger_login():
    value=module.classify_agy_status('', 'AGY_ERROR: {"code":"rate_limit_exceeded"}',1)
    assert value['status']=='STATUS_UNVERIFIED' and value['failure_category']=='quota'


def test_plaintext_login_marker_with_other_error_is_ambiguous():
    text='Please sign in to view available models. Launch the CLI without arguments to sign in.\nPermission denied'
    assert module.classify_agy_status('',text,1)['status']=='STATUS_UNVERIFIED'


def test_full_status_pass_reuses_twelve_sessions_and_never_runs_inference(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    import cochem_pipeline.worker as worker
    import cochem_pipeline.windows as win
    calls=[]
    class Runner:
        def _launch_worker(self, identity, argv, cwd, inp, out, err, **kwargs):
            provider=argv[0];calls.append((kwargs['worker_slot'],argv))
            if provider=='codex':out.write(b'Logged in using ChatGPT\n')
            elif provider=='claude':out.write(b'{"loggedIn":true,"authMethod":"claude.ai","apiProvider":"firstParty"}')
            else:err.write(next(iter(sorted(module.SIGN_OUT))).encode())
            return provider
        def _managed(self,*args):return nullcontext()
        def _wait(self,process,*args,**kwargs):return int(process=='gemini')
    monkeypatch.setattr(worker,'NativeRunner',lambda _:Runner())
    monkeypatch.setattr(win,'WorkerIdentity',lambda **kw:kw)
    descriptor=SimpleNamespace(root=tmp_path,scratch=tmp_path,environment=lambda:None)
    config=SimpleNamespace(workers={f'slot{i}':{} for i in range(1,7)},execution_limits=None,
        providers={p:dict(executable=p,subscription_probe={'arguments':['--output-format','json','models']})
            for p in ('codex','claude','gemini')})
    result=module.auth_checks(config,SimpleNamespace(workspace=lambda _:descriptor),tmp_path)
    assert len(calls)==18 and sum(row['authenticated'] for row in result['checks'])==12
    assert all(row['status']=='ATTENDED_LOGIN_REQUIRED' for row in result['checks'] if row['provider']=='gemini')
    assert all(argv==['gemini','--output-format','json','models'] for _,argv in calls if argv[0]=='gemini')
    assert result['native_model_jobs_executed']==0 and not list(tmp_path.iterdir())
