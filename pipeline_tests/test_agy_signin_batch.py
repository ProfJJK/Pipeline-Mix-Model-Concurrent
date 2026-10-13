"""Auth-only broker fixtures. No scheduled task, logon, native CLI or model runs."""
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def batch():
    return load('worker_agy_signin_batch')


@pytest.fixture
def slots(tmp_path):
    for i in range(1, 7):
        (tmp_path/f'slot{i}').mkdir()
    return tmp_path


@pytest.mark.parametrize('code,out,err,expected', [
    (0,b'{"status":"SUCCESS","command":{"name":"models","data":{"models":[{"id":"gemini-3.8-flash-low","label":"Flash"}]}}}',b'Fetching available models...\n','VERIFIED'),
    (1,b'',b'Fetching available models...\nError: Please sign in to view available models. Launch the CLI without arguments to sign in.\n','LOGIN_REQUIRED'),
    (1,b'',b'network refused; not logged in','UNKNOWN'),
    (1,b'',b'You are not logged into Antigravity.\nunknown error','UNKNOWN'),
    (0,b'{"status":"SUCCESS","status":"SUCCESS"}',b'','UNKNOWN'),
    (0,b'{"status":"SUCCESS","command":{"name":"models","data":{"models":[{"id":"claude-other","label":"Other"}]}}}',b'','UNKNOWN'),
    (0,b'{"status":"SUCCESS","command":{"name":"models","data":{"models":[{"id":"gemini-flash","label":"Flash"}]}}}',b'Error: denied','UNKNOWN'),
])
def test_fixed_status_protocol(batch, code, out, err, expected):
    value = batch.classify_status(out, err, code)
    assert value['decision'] == expected
    assert 'label' not in json.dumps(value) and 'network refused' not in json.dumps(value)


def accepted_login():
    return dict(status='LOGIN_SESSION_ENDED_AFTER_INPUT_STATUS_REQUIRED', cleanup_verified=True,
        terminal_cleanup_verified=True, one_line_submitted=True, code_write_completed=True,
        input_file_deleted=True, pause_marker_seen=False)


def test_six_sequential_urls_and_fresh_post_login_status(batch, slots):
    events = []
    def status(slot, root, stage):
        events.append((slot, stage))
        return dict(decision='LOGIN_REQUIRED' if stage == 'before' else 'VERIFIED')
    def login(slot, root):
        decision = json.loads((root/'login-required.json').read_text())
        assert decision == dict(slot=slot, nonce='a'*32, decision='LOGIN_REQUIRED')
        events.append((slot,'login'))
        return accepted_login()
    results = batch.sequence(slots, 'a'*32, float('inf'), status, login)
    assert events == [(f'slot{i}', stage) for i in range(1,7) for stage in ('before','login','after')]
    assert len(results) == 6 and all(row['authenticated'] for row in results)


def test_existing_sessions_are_reused_without_url_or_code(batch, slots):
    def unexpected(*args):
        raise AssertionError('No login permitted')
    results = batch.sequence(slots, 'a'*32, float('inf'), lambda *args: dict(decision='VERIFIED'), unexpected)
    assert all(row['status']=='REUSED_SESSION' and not row['login_requested'] for row in results)
    assert not list(slots.rglob('login-required.json'))


@pytest.mark.parametrize('bad', ['UNKNOWN','timeout','cleanup','pause','no-code','post-status','cancel','deadline'])
def test_first_failure_stops_without_retry_or_later_login(batch, slots, bad):
    events=[]
    def status(slot, root, stage):
        events.append((slot,stage))
        if bad=='timeout':
            raise TimeoutError('PRIVATE-DIAGNOSTIC')
        return dict(decision='UNKNOWN' if bad=='UNKNOWN' else 'LOGIN_REQUIRED' if stage=='before' or bad=='post-status' else 'VERIFIED')
    def login(slot, root):
        events.append((slot,'login'))
        result=accepted_login()
        if bad=='cleanup': result['cleanup_verified']=False
        if bad=='pause': result['pause_marker_seen']=True
        if bad=='no-code': result['one_line_submitted']=False
        if bad=='cancel': (slots/'cancel.request').write_text('cancel-fixture')
        return result
    results=batch.sequence(slots,'a'*32,0 if bad=='deadline' else float('inf'),status,login)
    assert len(results)==1 and results[0]['status']=='HELD'
    assert all(slot=='slot1' for slot,stage in events)
    assert 'PRIVATE-DIAGNOSTIC' not in json.dumps(results)
    if bad in ('UNKNOWN','timeout','deadline'):
        assert not (slots/'slot1/login-required.json').exists()


def test_global_cancel_before_first_status_prevents_all_native_commands(batch, slots):
    (slots/'cancel.request').write_text('cancel-fixture')
    def unexpected(*args): raise AssertionError('Native command after cancellation')
    results=batch.sequence(slots,'a'*32,float('inf'),unexpected,unexpected)
    assert results[0]['error_type']=='InterruptedError'


def test_native_status_uses_exact_argv_limits_and_empty_job_cleanup(batch, tmp_path):
    calls=[]
    process=NS(poll=lambda: 1,close=lambda: calls.append('closed'))
    def launch(identity,argv,cwd,inp,out,err,*,limits):
        calls.append((identity,argv,cwd,limits))
        err.write(b'You are not logged into Antigravity.\n');err.flush()
        return process
    win=NS(launch_worker=launch)
    support=NS(observe_child=lambda *args:dict(token_matches_selected_worker=True))
    value=batch.status_probe(win,support,'isolated',dict(root='profile',sid='sid'),'bounded',Path('agy.exe'),tmp_path,'before')
    assert calls[0]==('isolated',['agy.exe','--output-format','json','models'],'profile','bounded')
    assert calls[-1]=='closed' and value['cleanup_verified'] and value['decision']=='LOGIN_REQUIRED'


def test_status_failure_still_closes_owned_job(batch, tmp_path):
    calls=[]
    process=NS(poll=lambda:None,close=lambda:calls.append('closed'))
    def observe(*args): raise ValueError('bad process identity')
    win=NS(launch_worker=lambda *args,**kwargs:process)
    with pytest.raises(ValueError):
        batch.status_probe(win,NS(observe_child=observe),'id',dict(root='p',sid='s'),'limits',Path('agy'),tmp_path,'before')
    assert calls==['closed']


def test_report_publication_is_complete_and_create_only(batch,tmp_path):
    path=tmp_path/'status.json'
    batch.write_new(path,dict(complete=True))
    assert json.loads(path.read_text())==dict(complete=True)
    with pytest.raises(OSError): batch.write_new(path,dict(replaced=True))
    assert json.loads(path.read_text())==dict(complete=True)


def test_auth_only_source_has_no_daemon_database_or_deployment_actions():
    source=(ROOT/'scripts/worker_agy_signin_batch.py').read_text()
    for forbidden in ('require_stopped(', 'JobStore(', 'sqlite3.', 'cochem_pipeline daemon', 'requests.', 'webbrowser.'):
        assert forbidden not in source
    assert 'memory_limit_mb=512, cpu_rate_percent=5, max_processes=4' in source
    assert "win.launch_worker(identity, [str(native), *STATUS_ARGS]" in source


def test_package_is_self_contained_pinned_and_cannot_overwrite(tmp_path):
    prepare=load('prepare_agy_signin')
    target=tmp_path/'package'
    result=prepare.prepare(target)
    manifest=json.loads((target/'manifest.json').read_text())
    assert result['files']==16 and len(manifest['files'])==16
    for row in manifest['files']:
        raw=(target/row['relative']).read_bytes()
        assert len(raw)==row['length'] and prepare.hashlib.sha256(raw).hexdigest()==row['sha256']
    with pytest.raises(ValueError,match='Preserve'): prepare.prepare(target)


@pytest.mark.parametrize('short_write',[False,True])
def test_broker_terminal_path_from_fresh_url_to_private_code_and_cleanup(batch,tmp_path,monkeypatch,short_write):
    # Real bridge parser/read loop, queue pump and publication boundary, with an
    # in-memory native terminal and a fixture-only private packet boundary.
    bridge=load('worker_agy_terminal_bridge')
    spec=importlib.util.spec_from_file_location('fixture_parent',ROOT/'docs/deployment/windows-deployment-next/worker_agy_login_bridge_r4_v1.py')
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    from cochem_pipeline import attended_agy_terminal as terminal
    nonce='a'*32;root=tmp_path/'slot1';root.mkdir()
    calls=[];finished=[False]
    class Writer(io.BytesIO):
        def write(self,value):
            calls.append(value);finished[0]=True
            if short_write:return 2
            return super().write(value)
    writer=Writer()
    class Session:
        cleanup_verified=False
        console=NS(writer=writer)
        def poll(self): return 0 if finished[0] else None
        def close(self,drain): self.cleanup_verified=True;calls.append('cleanup')
    def launch(*args,output_ready,**kwargs):
        output_ready(io.BytesIO(b'https://accounts.google.com/o/oauth2/auth?fixture=fresh\n'
            b'After authenticating, copy the code displayed in the browser and paste it below:\n\nauthorization code...\nshift+up/down Navigate'))
        return Session()
    monkeypatch.setattr(terminal,'launch_attended_agy',launch)
    original=bridge.TerminalOutput.accept
    def owner_paste(self,data,submitted):
        display=original(self,data,submitted)
        path=root/'input.once'
        if self.prompt_ready and not submitted and not path.exists():
            path.write_bytes(b'cochem-login-input/1\n'+nonce.encode()+b'\nPRIVATE-CODE\n')
        return display
    monkeypatch.setattr(bridge.TerminalOutput,'accept',owner_paste)
    class Channel:
        def __init__(self,path,win): self.path=path;self.raw=path.read_bytes()
        def delete_after_verified_cleanup(self): self.path.unlink()
        def close(self):pass
    monkeypatch.setattr(legacy,'ChannelFile',Channel)
    win=NS(SYSTEM_SID='S-1-5-18')
    support=NS(digest_file=lambda path:'a'*64,observe_child=lambda *args:dict(token_sid='worker'),
        safe_failure=lambda error,phase:dict(error_type=type(error).__name__,phase=phase,winerror=None))
    result=batch.login_one(win,None,support,legacy,terminal,bridge,'identity',dict(root='profile',sid='worker'),
        root,nonce,batch.time.time()+30,'limits')
    assert result['one_line_submitted'] and result['cleanup_verified'] and result['input_file_deleted']
    assert calls==[b'PRIVATE-CODE\r','cleanup']
    assert not (root/'input.once').exists()
    assert b'PRIVATE-CODE' not in (root/'operator.log').read_bytes()
    assert 'PRIVATE-CODE' not in (root/'login.json').read_text()
    prompt=json.loads((root/'prompt-ready.json').read_text())
    assert prompt==dict(schema='cochem-agy-code-prompt/1',slot='slot1',nonce=nonce,
                       url='https://accounts.google.com/o/oauth2/auth?fixture=fresh')
    if short_write:
        assert result['status']=='LOGIN_FAILED_OR_CANCELLED' and not result['code_write_completed']
    else:
        assert result['status']=='LOGIN_COMMAND_EXITED_ZERO_STATUS_REQUIRED' and result['code_write_completed']
