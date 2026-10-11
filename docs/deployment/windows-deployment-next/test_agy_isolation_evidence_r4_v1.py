"""Tests for agy_isolation_evidence_r4_v1.py and agy-isolation-evidence-r4-v1.ps1 (build-manifest step 6; r5 sitting S8,
config-builder gates G3/G4/G5).

Inert by construction: no SYSTEM API, no task, no agy/claude/codex/gemini launch, no network, no ACL change and no write
outside pytest's tmp directories. The helper runs end to end with every Windows boundary replaced: fake processes stand in
for agy with canned stream-json/json outputs, the six worker profiles, slot roots, RAM workspace and ProgramData folder are
tmp directories (the workspace ancestor walk is bounded to the tmp world), the ACL application and the protected folder
creation are recorded (the intended SDDL is asserted and a fake ACL reader serves it back), the Job accounting is canned,
and a fake clock makes the bounds instant. The receipts it writes are fed to the wrapper's own functions, dot-sourced from
its AST into a throwaway powershell.exe and driven with COM stubs. Plan-by-default and -Apply gating are exercised at
function level only; the whole script is started only with arguments that fail parameter binding. One test (O-F3) applies
the reviewed DACL templates, with the current user standing in for the worker, to its own tmp folders to prove the
auditor's parent-rename case is refused, then restores them.
"""
import ctypes as C
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

import ps_toplevel_smoke as smoke

ROOT = Path(__file__).parent
PY = ROOT / 'agy_isolation_evidence_r4_v1.py'
SCRIPT = ROOT / 'agy-isolation-evidence-r4-v1.ps1'
AGENT = ROOT / 'cochem-inference-only.agent.md'
V22 = ROOT / 'retarget-warden-r4.ps1'
V22_SHA256 = '8ee6b412f6be176dfac7c2c1b2340f1973e08358c7d22da6d4515e79f0327a4e'
REGISTER = ROOT / 'register-stopped-warden-r3.ps1'
CHECK_R3 = ROOT / 'check-worker-native-status-r3.ps1'
INSPECTION = ROOT / 'protected-code-inspection-v4.ps1'
COPY_HELPER = Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent\scripts\stage_aetherdesk_427_payloads.ps1')
COCHEM = Path(r'C:\Program Files\CoChem')
R4 = COCHEM / 'Pipeline4.2.7-windows-20261009-r4'
R4_SITE = R4 / '.venv' / 'Lib' / 'site-packages' / 'cochem_pipeline'
PS = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
ATTEMPT = 'c' * 32
NONCE = 'd' * 32
EMAIL = 'private@example.invalid'
SECRET_TOKEN = 'ya29.SECRETACCESSTOKEN0123456789'
SECRET_REFRESH = '1//0SECRETREFRESH0123456789abc'
SECRET_URL = 'https://oauth2.googleapis.com/token?client_secret=SECRETCLIENT'
SECRETS = ('SECRET', EMAIL, 'ya29.', '1//0SECRET', 'oauth2.googleapis.com', 'SECRET-TOKEN-VALUE')
USAGE = {'input_tokens': 11, 'output_tokens': 2, 'thinking_tokens': 0, 'cache_read_tokens': 0, 'total_tokens': 13}
SID_NAMES = {'SY': 'S-1-5-18', 'BA': 'S-1-5-32-544', 'BU': 'S-1-5-32-545'}
SLOTS = [f'slot{i}' for i in range(1, 7)]
IDENTITIES = [f'CoChem422Worker{i}' for i in range(1, 7)]


def load():
    spec = importlib.util.spec_from_file_location('agy_isolation_evidence_r4_v1', PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = load()


def r4_protocol():
    path = R4_SITE / 'agy_protocol.py'
    if not path.exists():
        pytest.skip('the installed r4 agy_protocol is not readable on this host')
    spec = importlib.util.spec_from_file_location('r4_agy_protocol_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- canned agy outputs

def envelope(name, data, status='SUCCESS'):
    value = {'conversation_id': '', 'status': status, 'response': '', 'duration_seconds': 0, 'num_turns': 0,
             'usage': {key: 0 for key in USAGE}, 'command': {'name': name, 'data': data}}
    return json.dumps(value, separators=(',', ':')).encode()


MODELS = envelope('models', {'models': [{'id': slug, 'label': slug} for slug in (
    'gemini-3.8-flash-high', 'gemini-3.8-flash-medium', 'gemini-3.8-flash-low', 'gemini-3.1-pro-high', 'gemini-3.1-pro-low')]})
AGENTS_OK = envelope('agents', {'agents': ['cochem-inference-only']})
AGENTS_NONE = envelope('agents', {'agents': []})
FETCH = b'Fetching available models...\n'


def steps(session, model=None, extra=None):
    rows = [{'conversation_id': session, 'step_type': 'user_input', 'state': 'DONE', 'step_index': 0},
            {'conversation_id': session, 'step_type': 'agent_response', 'state': 'DONE', 'step_index': 1, 'text_delta': 'ready true'}]
    if model is not None:
        for row in rows:
            row['model'] = model
    for row in extra or ():
        rows.insert(1, dict(row, conversation_id=session))
    return rows


def stream(model='gemini-3.8-flash-high', agent='cochem-inference-only', tools=(), step_rows=None, status='SUCCESS',
           num_turns=1, response='ready true', include_model=True, result_extra=None, session='conv-1', error=None, extra_steps=None):
    init = {'cwd': r'C:\ProgramData\CoChemPipeline427\workers\slot1', 'tools': list(tools), 'permission_mode': 'request-review'}
    if include_model:
        init['model'] = model
    if agent is not None:
        init['agent'] = agent
    events = [{'event': 'init', 'conversation_id': session, 'init': init}]
    for step in (step_rows if step_rows is not None else steps(session, extra=extra_steps)):
        events.append({'event': 'step_update', 'step_update': step})
    result = {'conversation_id': session, 'status': status, 'response': response, 'duration_seconds': 1.25,
              'num_turns': num_turns, 'usage': USAGE}
    if error is not None:
        result['error'] = error
    result.update(result_extra or {})
    events.append({'event': 'result', 'result': result})
    return ''.join(json.dumps(event, separators=(',', ':')) + '\n' for event in events).encode()


R2_REJECT = (b'Error: invalid model selection (--model "gemini-3.8-flash-high" --effort "high"): '
             b'--model gemini-3.8-flash-high conflicts with --effort=high\n')
R4_STDOUT = (b'{"event":"result","result":{"conversation_id":"conv-4","status":"ERROR","response":"",'
             b'"error":"unknown model \\"gemini-3.1-pro-preview\\"","duration_seconds":0,"num_turns":0}}\n')
R4_STDERR = b'AGY_ERROR: {"code":"INVALID_ARGUMENT","message":"unknown model \\"gemini-3.1-pro-preview\\"","retryable":false}\n'
R1_STDERR = ('Headless auth: authenticated as "' + EMAIL + '"\n').encode()
# RG-2: agy 1.3.x logs model resolution as INFO lines in ~/.gemini/antigravity-cli/log/cli-*.log, not on stderr.
LOG_DIR = '.gemini/antigravity-cli/log/'
BENIGN_LOG = (b'2026-10-11T15:00:00Z INFO Model resolved via default: gemini-3.8-flash-high user=SECRET-LOG-VALUE\n'
              b'2026-10-11T15:00:00Z INFO model gemini-3.8-flash-high not in local config, defaulting to CCPA\n'
              b'2026-10-11T15:00:01Z INFO Model resolved via default: gemini-3.8-flash-high\n')
FALLBACK_LOG = BENIGN_LOG + b'2026-10-11T15:00:02Z INFO Restoring model gemini-3.8-flash-high for SECRET-LOG-VALUE\n'
R5_STDERR = ('debug: refreshed ' + SECRET_TOKEN + ' via ' + SECRET_URL + ' with ' + SECRET_REFRESH + '\n').encode()


def run_args(model, extra=()):
    return ('--agent', 'cochem-inference-only', '--input-format', 'stream-json', '--output-format', 'stream-json',
            '--model', model, '--disable-slash-commands', *extra)


def evidence_scripts(slug='gemini-3.8-flash-low'):
    return {
        ('--version',): {'stdout': b'1.3.1\n', 'code': 0},
        ('--output-format', 'json', 'models'): {'stdout': MODELS, 'stderr': FETCH, 'code': 0},
        ('--output-format', 'json', 'agents'): {'stdout': AGENTS_OK, 'code': 0},
        ('agents',): {'stdout': b'cochem-inference-only\n', 'code': 0},
        run_args('gemini-3.8-flash-high'): {'stdout': stream(session='conv-r1'), 'stderr': R1_STDERR, 'code': 0,
                                            'writes': {'.gemini/antigravity-cli/brain/conv-r1/summary.txt': b'ready true'}},
        run_args(slug): {'stdout': stream(model=slug, session='conv-r5'), 'stderr': R5_STDERR, 'code': 0},
        run_args('gemini-3.8-flash-high', ('--effort', 'high')): {'stderr': R2_REJECT, 'code': 1},
        run_args('gemini-3.8-flash', ('--effort', 'high')): {'stdout': stream(model='gemini-3.8-flash-high', session='conv-r3'), 'code': 0},
        run_args('gemini-3.1-pro-preview'): {'stdout': R4_STDOUT, 'stderr': R4_STDERR, 'code': 3},
    }


# ---------------------------------------------------------------- fakes

class FakeTime:
    """Instant clock: sleep advances monotonic time, so 30/120 s bounds run in milliseconds."""
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def time(self):
        return 1760000000.0 + self.now


def job_accounting(total=2):
    """The real job_process_accounting shape; 2 = agy.exe plus its console host (the expected tree)."""
    return {'total_processes': total, 'active_processes': 0, 'total_terminated_processes': total, 'expected_maximum': 2,
            'queried_after_job_termination': True, 'source': 'fixture'}


class FakeProcess:
    def __init__(self, script, stdin, output, errors, profile, identity, argv):
        self.script, self.profile, self.identity, self.argv = script, profile, identity, argv
        self.closed, self.polls = False, 0
        self.resource_limits_evidence = {'fixture': True}
        self.accounting = job_accounting(script.get('processes', 2))
        self.stdin_fd = os.dup(stdin.fileno())
        self.pid, self.creation_time_filetime = 4242, 1
        output.write(script.get('stdout', b''))
        output.flush()
        errors.write(script.get('stderr', b''))
        errors.flush()
        for relative, data in script.get('writes', {}).items():
            path = profile / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        if script.get('make_programdata'):
            # A worker-token child creating %PROGRAMDATA%\Antigravity\admin_settings.json during a run.
            folder = profile.parent.parent / 'ProgramData' / 'Antigravity'
            folder.mkdir(exist_ok=True)
            (folder / 'admin_settings.json').write_bytes(b'{}')

    def poll(self):
        self.polls += 1
        return self.script.get('code') if self.polls > self.script.get('delay_polls', 0) else None

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def attestation(profile):
    return {'pid': 4242, 'creation_time_filetime': 1, 'token_sid': 'S-1-5-21-fixture', 'token_matches_selected_worker': True,
            'image_matches_reviewed_executable': True, 'owned_job_membership_verified': True, 'image_query_format': 'win32',
            'profile_directory_sha256': hashlib.sha256(str(profile).casefold().encode()).hexdigest(), 'source': 'fixture'}


def parse_sddl(sddl):
    match = re.fullmatch(r'O:(\w+)G:(\w+)D:(P?)((?:\([^)]*\))+)', sddl)
    assert match, sddl
    rules = []
    for ace in re.findall(r'\(([^)]*)\)', match.group(4)):
        kind, flags, rights, _, _, sid = ace.split(';')
        assert kind == 'A'
        rules.append((SID_NAMES.get(sid, sid), 0x1F01FF if rights == 'FA' else int(rights, 16), {'': 0, 'OICI': 3}[flags]))
    return SID_NAMES[match.group(1)], match.group(3) == 'P', rules


class FakeAcl:
    """Records the SDDL the helper would apply and serves it back to verify_agent_acl; nothing touches a real ACL."""
    def __init__(self):
        self.applied, self.store = [], {}

    def apply(self, win, path, sddl):
        self.applied.append((str(path), sddl))
        self.store[str(path)] = parse_sddl(sddl)

    def read(self, path):
        # An unrecorded path looks like an inherited, worker-writable ACL: verification must refuse it.
        return self.store.get(str(path), ('S-1-5-32-544', False, [('S-1-5-32-544', 0x1F01FF, 3)]))


def make_world(base):
    """Six tmp worker profiles, six tmp slot roots, a tmp private root and the r4 layout/config redirected to them."""
    if not (R4 / 'pipeline.json').exists():
        pytest.skip('the r4 runtime configuration is not readable on this host')
    users, workers, private = base / 'Users', base / 'workers', base / 'private'
    for identity in IDENTITIES:
        cli = users / identity / '.gemini' / 'antigravity-cli'
        cli.mkdir(parents=True)
        (cli / 'cli.log').write_bytes(b'existing log\n')
        (cli / 'antigravity-oauth-token').write_bytes(b'SECRET-TOKEN-VALUE')
    for slot in SLOTS:
        (workers / slot).mkdir(parents=True)
    private.mkdir()
    (base / 'ProgramData').mkdir()
    config = json.loads((R4 / 'pipeline.json').read_bytes())
    layout = json.loads((R4 / 'windows-layout.json').read_bytes())
    config['private_root'] = layout['private_root'] = str(private)
    config['ramdisk'] = dict(config.get('ramdisk') or {}, enabled=False)
    for slot in SLOTS:
        layout['slots'][slot]['root'] = config['slot_roots'][slot] = str(workers / slot)
    # The RAM workspace root is deliberately NOT created: its ancestors are inventoried even before admission.
    return SimpleNamespace(base=base, users=users, workers=workers, private=private, config=config, layout=layout,
                           ram=base / 'R' / 'CoChem427-windows-20261007', programdata=base / 'ProgramData' / 'Antigravity')


def patch_module(module, monkey, world, protected, acl, launched, stops, scripts_for):
    """Replace every Windows/system boundary of the helper with an inert fixture."""
    from cochem_pipeline import windows as win
    from cochem_pipeline import ramdisk
    import cochem_pipeline
    protocol = r4_protocol()
    monkey.setitem(sys.modules, 'cochem_pipeline.agy_protocol', protocol)
    monkey.setattr(cochem_pipeline, 'agy_protocol', protocol, raising=False)
    monkey.setattr(module, 'EVIDENCE_BASE', protected)
    monkey.setattr(module, 'PROFILE_PARENT', world.users)
    monkey.setattr(module, 'current_executable', lambda: module.PYTHON)
    monkey.setattr(module, 'validate_interpreter', lambda: None)
    monkey.setattr(module, 'verify_r4_runtime', lambda *a: {'verified': True, 'files': 109, 'source_sha256': module.REVISION_SHA256})
    monkey.setattr(module, 'protected_json', lambda _, p: (world.layout, module.LAYOUT_SHA256) if p.name == 'windows-layout.json'
                   else (world.config, module.CONFIG_SHA256))
    original = module.digest_file

    def digest(path, maximum=1024 * 1024 * 1024):
        if Path(path) == Path(win.__file__):
            return module.WINDOWS_SHA256
        if Path(path) == module.EXECUTABLE:
            return module.AGY_SHA256
        return original(Path(path), maximum)
    monkey.setattr(module, 'digest_file', digest)
    for name in ('require_system', 'validate_code_path', 'validate_private_directory', '_validate_control_ancestors',
                 '_validate_boundary', '_enable_system_privileges'):
        monkey.setattr(win, name, lambda *a, **k: None)
    monkey.setattr(ramdisk, 'ordinary_tree', lambda *a: None)
    monkey.setattr(win, '_api', lambda: {'kernel32': SimpleNamespace(CreateMutexW=lambda *a: 17)})
    monkey.setattr(win, '_check', lambda value, *a: value)
    monkey.setattr(win, '_close', lambda *a: None)
    sids = {row['identity']: row['sid'] for row in world.layout['slots'].values()}
    monkey.setattr(win, '_account_sid', lambda name: sids[name])
    monkey.setattr(win, '_sid_text', lambda value: value)
    monkey.setattr(win, '_layout_paths', lambda p, *a: (p, {}))
    monkey.setattr(win, '_layout_boundaries', lambda *a: [world.private / 'boundary'])
    monkey.setattr(win, '_acl', acl.read)
    monkey.setattr(module, 'apply_sddl', acl.apply)
    monkey.setattr(module, 'require_stopped', lambda *a: stops.append('require_stopped'))
    monkey.setattr(module, 'observe_child', lambda win_, process, sid, exe: attestation(process.profile))
    monkey.setattr(module, 'attest_environment', lambda win_, identity, sid, limits, profile: module.environment_names(
        f'=C:=C:\\\x00HOME={profile}\x00USERPROFILE={profile}\x00APPDATA={profile}\\AppData\\Roaming\x00'
        f'LOCALAPPDATA={profile}\\AppData\\Local\x00PATH=C:\\Windows\\System32\x00COCHEM_JOB=fixture\x00', profile))
    monkey.setattr(module, 'time', FakeTime())
    monkey.setattr(module, 'job_process_accounting', lambda win_, process: dict(process.accounting))
    monkey.setattr(module, 'PROGRAMDATA_ANTIGRAVITY', world.programdata)
    monkey.setattr(module, 'create_protected_directory', lambda win_, path, sddl: (Path(path).mkdir(), acl.apply(win_, path, sddl)))
    monkey.setattr(module, 'ram_workspace_root', lambda config, slot: world.ram / slot)
    # The real walk up to the drive root is unit-tested on its own; here it stops at the tmp world (hermetic).
    real_ancestors, floor = module.workspace_ancestors, str(world.base).casefold()
    monkey.setattr(module, 'workspace_ancestors', lambda root: [p for p in real_ancestors(root) if str(p).casefold().startswith(floor)])

    def launch_worker(identity, argv, cwd, stdin, output, errors, limits=None):
        script = scripts_for(identity.name)[tuple(argv[1:])]
        process = FakeProcess(script, stdin, output, errors, world.users / identity.name, identity.name, argv)
        launched.append(SimpleNamespace(argv=argv, cwd=cwd, identity=identity.name, process=process, limits=limits))
        return process
    monkey.setattr(win, 'launch_worker', launch_worker)


def produce(base, monkey, mode='evidence', slug='gemini-3.8-flash-low', scripts=None, stage_scripts=None, deadline=None,
            prestage=False, before=None):
    """Run the real helper once in a tmp world; return the receipt, the root, the launches and the recorded ACLs."""
    module = load()
    world = make_world(base)
    protected = base / 'protected'
    protected.mkdir()
    root = protected / (f'{module.ROOT_PREFIX}{ATTEMPT}' + ('-stage' if mode == 'stage' else ''))
    root.mkdir()
    copied = root / module.HELPER_NAME
    copied.write_bytes(PY.read_bytes())
    (root / module.AGENT_FILE_NAME).write_bytes(AGENT.read_bytes())
    monkey.setattr(module, '__file__', str(copied))
    acl, launched, stops = FakeAcl(), [], []
    default = scripts or evidence_scripts(slug)

    def scripts_for(identity):
        if stage_scripts is not None and identity in stage_scripts:
            return stage_scripts[identity]
        return default
    patch_module(module, monkey, world, protected, acl, launched, stops, scripts_for)
    if deadline is not None:
        monkey.setattr(module, 'DEADLINE_SECONDS', deadline)
    from cochem_pipeline import windows as win
    if prestage:
        sid = world.layout['slots']['slot1']['sid']
        module.stage_agent(win, root / module.AGENT_FILE_NAME, world.users / 'CoChem422Worker1', sid)
    world.acl = acl
    if before is not None:
        before(world)
    if mode == 'stage':
        code = module.run('stage', None, NONCE, ATTEMPT)
    else:
        code = module.run('evidence', 'slot1', NONCE, ATTEMPT, slug)
    stdin = []
    for item in launched:
        data = b''
        while chunk := os.read(item.process.stdin_fd, 4096):
            data += chunk
        os.close(item.process.stdin_fd)
        stdin.append(data)
    name = module.RECEIPT_NAMES[mode]
    text = (root / name).read_text(encoding='ascii')
    return SimpleNamespace(module=module, root=root, world=world, code=code, launched=launched, stdin=stdin, stops=stops,
                           acl=acl, receipt=json.loads(text), receipt_text=text, mode=mode, slug=slug)


def tampered_agent_scripts():
    scripts = evidence_scripts()
    scripts[('--output-format', 'json', 'models')] = dict(
        scripts[('--output-format', 'json', 'models')], writes={'.gemini/agents/cochem-inference-only/agent.md': b'tampered\n'})
    return scripts


def variant(**changes):
    scripts = evidence_scripts()
    for key, value in changes.items():
        scripts[{'r1': run_args('gemini-3.8-flash-high'), 'r5': run_args('gemini-3.8-flash-low'),
                 'r2': run_args('gemini-3.8-flash-high', ('--effort', 'high')),
                 'pc3': ('--output-format', 'json', 'agents'), 'pc4': ('agents',)}[key]] = value
    return scripts


def protected_programdata(world):
    """Pre-create the tmp ProgramData\\Antigravity as exactly the stage-mode folder (empty, the reviewed SDDL)."""
    world.programdata.mkdir()
    world.acl.store[str(world.programdata)] = parse_sddl(m.PROGRAMDATA_ANTIGRAVITY_SDDL)


def user_configs(world, identity, files):
    config = world.users / identity / '.gemini' / 'config'
    config.mkdir(parents=True)
    for name, data in files.items():
        (config / name).write_bytes(data)


def programdata_with_settings(world):
    world.programdata.mkdir()
    (world.programdata / 'admin_settings.json').write_bytes(b'{"gateway":"https://gateway.invalid"}')


@pytest.fixture(scope='module')
def produced(tmp_path_factory):
    """Real helper receipts for the PowerShell fixtures and the end-to-end assertions."""
    base = tmp_path_factory.mktemp('agy-isolation')
    cases = {
        'pass': dict(),
        'medium': dict(slug='gemini-3.8-flash-medium', scripts=evidence_scripts('gemini-3.8-flash-medium')),
        'tools': dict(scripts=variant(r1={'stdout': stream(tools=('view_file',), session='conv-r1'), 'code': 0})),
        'marker': dict(scripts=variant(r1={'stdout': stream(session='conv-r1'), 'stderr': b'Model resolved via fallback table\n', 'code': 0})),
        'r5_mismatch': dict(scripts=variant(r5={'stdout': stream(model='gemini-3.8-flash-high', session='conv-r5'), 'code': 0})),
        'precheck': dict(scripts=variant(pc3={'stdout': AGENTS_NONE, 'code': 0}, pc4={'stdout': b'', 'code': 0})),
        'failed': dict(scripts=tampered_agent_scripts()),
        'deadline': dict(scripts=variant(r1={'stdout': b'', 'code': None}), deadline=300),
        'inventory': dict(before=lambda world: (
            (world.users / 'CoChem422Worker3' / '.gemini' / 'config').mkdir(parents=True),
            (world.users / 'CoChem422Worker3' / '.gemini' / 'config' / 'mcp_config.json').write_bytes(b'{"mcpServers":{}}'))),
        'stage': dict(mode='stage', prestage=True),
        'stage_missing': dict(mode='stage', stage_scripts={'CoChem422Worker4': variant(pc3={'stdout': AGENTS_NONE, 'code': 0},
                                                                                         pc4={'stdout': b'', 'code': 0})}),
        'stage_shadow': dict(mode='stage', before=lambda world: (
            (world.users / 'CoChem422Worker2' / '.gemini' / '.agents').mkdir(parents=True),
            (world.users / 'CoChem422Worker2' / '.gemini' / '.agents' / 'cochem-inference-only.agent.md').write_bytes(b'shadow\n'))),
        'stage_conflict': dict(mode='stage', before=lambda world: (
            (world.users / 'CoChem422Worker3' / '.gemini' / 'agents' / 'cochem-inference-only').mkdir(parents=True),
            (world.users / 'CoChem422Worker3' / '.gemini' / 'agents' / 'cochem-inference-only' / 'agent.md').write_bytes(b'other\n'))),
        # O-F4: R1 passes after 100 s; the deadline guard then skips R5, R2, R3, R4.
        'deadline_after_r1': dict(scripts=variant(r1={'stdout': stream(session='conv-r1'), 'code': 0, 'delay_polls': 2000}), deadline=300),
        # O-F1: a process beyond agy's own tree in a run's Job.
        'r1_extra_process': dict(scripts=variant(r1={'stdout': stream(session='conv-r1'), 'code': 0, 'processes': 3})),
        'r2_extra_process': dict(scripts=variant(r2={'stderr': R2_REJECT, 'code': 1, 'processes': 4})),
        # O-F1: an alternative workspace folder in an ancestor of the (not yet existing) RAM workspace root.
        'workspace_chain': dict(before=lambda world: ((world.base / 'R' / '_agent').mkdir(parents=True),
                                                      (world.base / 'R' / '_agent' / 'mcp_config.json').write_bytes(b'{"mcpServers":{}}'))),
        # O-F1 + the Commander's content rule: ~/.gemini/config/config.json declaring plugins and an MCP server holds G3 with a
        # named reason; one that declares nothing (as a sign-in may write it) is present-but-clear.
        'profile_config': dict(before=lambda world: user_configs(world, 'CoChem422Worker5', {
            'config.json': b'{"plugins":{"x":{"enabled":true}},"mcpServers":{"local":{"command":"SECRET-CONFIG-VALUE"}}}'})),
        'profile_config_clear': dict(before=lambda world: (user_configs(world, 'CoChem422Worker5', {
            'config.json': b'{"chat":{"history":"SECRET-CONFIG-VALUE"},"userSettings":{"theme":"dark"},"plugins":{},"enableAgents":false,'
                           b'"sidecars":{}}',
            'skills.json': b'{}', 'plugins.json': b'{"plugins":[]}'}),
            (world.users / 'CoChem422Worker5' / '.gemini' / 'config' / 'sidecars').mkdir())),
        # RG-3: the auditor's sidecar case: a sidecar folder entry plus an enabled "sidecars" config key.
        'profile_sidecar': dict(before=lambda world: (user_configs(world, 'CoChem422Worker3', {
            'config.json': b'{"sidecars":{"evil":{"enabled":true,"projectId":"p"}}}'}),
            (world.users / 'CoChem422Worker3' / '.gemini' / 'config' / 'sidecars' / 'evil').mkdir(parents=True),
            (world.users / 'CoChem422Worker3' / '.gemini' / 'config' / 'sidecars' / 'evil' / 'sidecar.json').write_bytes(b'{"command":"cmd.exe"}'))),
        # RG-2: the per-run cli-*.log files: normal resolution lines are counted only; a true fallback phrase holds G3.
        'log_benign': dict(scripts=variant(r1={'stdout': stream(session='conv-r1'), 'code': 0,
                                               'writes': {LOG_DIR + 'cli-r1.log': BENIGN_LOG}})),
        'log_fallback': dict(scripts=variant(r1={'stdout': stream(session='conv-r1'), 'code': 0, 'writes': {LOG_DIR + 'cli-r1.log': BENIGN_LOG}},
                                             r5={'stdout': stream(model='gemini-3.8-flash-low', session='conv-r5'), 'code': 0,
                                                 'writes': {LOG_DIR + 'cli-r5.log': FALLBACK_LOG}})),
        # O-F2 (G3): ProgramData\Antigravity present with content, created during a run, or the protected empty folder.
        'programdata_present': dict(before=programdata_with_settings),
        'programdata_during_run': dict(scripts=variant(r5={'stdout': stream(model='gemini-3.8-flash-low', session='conv-r5'), 'code': 0,
                                                           'make_programdata': True})),
        'programdata_protected': dict(before=protected_programdata),
        # O-F2 (G4): content or a weaker ACL is refused; the protected empty folder is reused.
        'stage_programdata_content': dict(mode='stage', before=programdata_with_settings),
        'stage_programdata_weak': dict(mode='stage', before=lambda world: world.programdata.mkdir()),
        'stage_programdata_protected': dict(mode='stage', before=protected_programdata),
    }
    result = {}
    for name, kwargs in cases.items():
        with pytest.MonkeyPatch.context() as monkey:
            result[name] = produce(base / name, monkey, **kwargs)
    return result


# ---------------------------------------------------------------- tables, pins, files

def test_both_files_are_ascii_and_the_helper_compiles():
    for path in (PY, SCRIPT, AGENT, Path(__file__)):
        data = path.read_bytes()
        assert data.isascii(), path
        assert b'\r' not in data, f'{path.name}: the workspace convention (every sibling and reviewed import) is pure LF'
    compile(PY.read_text(encoding='ascii'), str(PY), 'exec')


def test_run_matrix_order_slugs_and_effort_null_parameter():
    assert m.RUN_IDS == ('R1', 'R5', 'R2', 'R3', 'R4') and m.MAX_MODEL_JOBS == 5
    assert m.DEFAULT_EFFORT_NULL_SLUG == 'gemini-3.8-flash-low'
    assert m.EFFORT_NULL_SLUGS == ('gemini-3.8-flash-low', 'gemini-3.8-flash-medium', 'gemini-3.8-flash-high')
    assert [(r, model, extra) for r, model, extra, _ in m.run_matrix()] == [
        ('R1', 'gemini-3.8-flash-high', ()), ('R5', 'gemini-3.8-flash-low', ()), ('R2', 'gemini-3.8-flash-high', ('--effort', 'high')),
        ('R3', 'gemini-3.8-flash', ('--effort', 'high')), ('R4', 'gemini-3.1-pro-preview', ())]
    assert m.run_matrix('gemini-3.8-flash-medium')[1][1] == 'gemini-3.8-flash-medium'
    for bad in ('gemini-3.1-pro-high', 'gemini-3.8-flash', 'gemini-3.8-flash-low ', ''):
        with pytest.raises(ValueError):
            m.run_matrix(bad)
    assert m.PRECHECK == (('PC1', ('--version',), 'version'), ('PC2', ('--output-format', 'json', 'models'), 'models_json'),
                          ('PC3', ('--output-format', 'json', 'agents'), 'agents_json'), ('PC4', ('agents',), 'agents_text'))
    assert m.STAGE_PROBES == m.PRECHECK[2:] and m.STAGE_SLOTS == tuple(SLOTS) and m.SLOTS == ('slot1',)
    assert m.ROOT_PREFIX == 'AgyIsolation4.2.7-windows-20261011-r4-v1-' and m.STAGE_ROOT_SUFFIX == '-stage'
    assert m.RECEIPT_NAMES == {'evidence': 'isolation-receipt.json', 'stage': 'stage-receipt.json'}


def test_deadline_budget_keeps_the_receipt_inside_pt10m():
    assert (m.RUN_SECONDS, m.RUN_OUTPUT, m.PROBE_SECONDS, m.PROBE_OUTPUT) == (120, 1048576, 30, 65536)
    assert m.DEADLINE_SECONDS + m.POST_LOOP_SECONDS <= m.TASK_LIMIT_SECONDS == 600
    assert m.LAUNCH_OVERHEAD_SECONDS >= 45 + 10, 'the launch-boundary require_stopped has a 45 s PowerShell timeout'
    worst = (len(m.PRECHECK) * (m.LAUNCH_OVERHEAD_SECONDS + m.PROBE_SECONDS + m.CLEANUP_MARGIN_SECONDS)
             + len(m.RUN_IDS) * (m.LAUNCH_OVERHEAD_SECONDS + m.RUN_SECONDS + m.CLEANUP_MARGIN_SECONDS))
    assert worst > m.DEADLINE_SECONDS, 'the deadline guard is needed and is what keeps the receipt written'


def test_agent_definition_pin_frontmatter_and_destinations():
    raw = AGENT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == m.AGENT_SHA256 and len(raw) == m.AGENT_BYTES == 478
    assert m.AGENT_SHA256 == '5c0082d70d073263a56d748a46187008968c070d0efc7d5b7612c2fd61d11810'
    frontmatter = m.validate_agent_definition(raw)
    assert frontmatter == {'name': 'cochem-inference-only', 'description': 'CoChem inference-only primary agent', 'tools': '[]',
                           'mainAgent': 'true', 'subagent': 'false', 'model': 'inherit',
                           'commandExecutionPolicy': '"off"', 'inheritCustomizations': 'false', 'inheritMcp': 'false',
                           'excludeDefaultComponents': 'true', 'mcpServers': '[]', 'skills': '[]', 'plugins': '[]',
                           'rules': '[]', 'agents': '[]'}
    assert m.AGENT_DESTINATION_PARTS == (('.gemini', 'agents', 'cochem-inference-only', 'agent.md'),
                                         ('.gemini', 'config', 'agents', 'cochem-inference-only', 'agent.md'))
    for bad in (raw.replace(b'tools: []', b'tools: [view_file]'), raw.replace(b'\n', b'\r\n'), raw + b'# second\n', b''):
        with pytest.raises(ValueError):
            m.validate_agent_definition(bad)


def frontmatter_of(data):
    """Independent parse of a staged definition's frontmatter (key: value lines between the two '---' fences)."""
    lines = data.decode('ascii').split('\n')
    assert lines[0] == '---'
    end = lines.index('---', 1)
    pairs = [line.split(': ', 1) for line in lines[1:end]]
    keys = [key for key, _ in pairs]
    assert len(keys) == len(set(keys)), 'no duplicated frontmatter key'
    return dict(pairs)


def test_staged_agent_frontmatter_has_no_hidden_key_and_keeps_the_isolation_keys(produced):
    """Commander amendment: 'hidden' is gone everywhere it is staged; the isolation keys are unchanged; listing stays strict."""
    required = {'tools': '[]', 'subagent': 'false', 'mainAgent': 'true', 'commandExecutionPolicy': '"off"'}
    on_disk = frontmatter_of(AGENT.read_bytes())
    assert 'hidden' not in on_disk and b'hidden' not in AGENT.read_bytes()
    assert {key: on_disk[key] for key in required} == required
    assert 'hidden' not in dict(m.AGENT_FRONTMATTER) and {key: dict(m.AGENT_FRONTMATTER)[key] for key in required} == required
    stage = produced['stage']
    for identity in IDENTITIES:
        for parts in m.AGENT_DESTINATION_PARTS:
            staged = (stage.world.users / identity).joinpath(*parts).read_bytes()
            assert hashlib.sha256(staged).hexdigest() == m.AGENT_SHA256 and staged == AGENT.read_bytes(), (identity, parts)
            value = frontmatter_of(staged)
            assert 'hidden' not in value and {key: value[key] for key in required} == required, (identity, parts)
    for run in (stage, produced['pass']):
        assert 'hidden' not in run.receipt['agent']['frontmatter']
        assert {key: run.receipt['agent']['frontmatter'][key] for key in required} == required
    # The previous definition (with 'hidden: true') can no longer be validated or staged.
    old = AGENT.read_bytes().replace(b'subagent: false\n', b'subagent: false\nhidden: true\n')
    with pytest.raises(ValueError, match='frontmatter'):
        m.validate_agent_definition(old)
    # The listing gate stays strict: every slot must list exactly the protected agent.
    assert stage.receipt['gate']['passed'] and all(e['listing'] == {'passed': True, 'reasons': []} for e in stage.receipt['slots'])
    assert all(p['classification']['agents'] == ['cochem-inference-only'] for e in stage.receipt['slots'] for p in e['probes'])
    assert m.listing_reasons([{'id': 'PC3', 'outcome': 'exited', 'exit_code': 0, 'classification': {
        'agents': [], 'agents_count': 0, 'agents_unlisted': 0, 'status_value': 'SUCCESS', 'command_name': 'agents'}}]) == [
        'AGENTS_JSON_LISTING_FAILED', 'AGENTS_TEXT_LISTING_FAILED'], 'an agent missing from a listing fails that slot'


def test_module_pins_equal_the_files_on_disk():
    if not R4.exists():
        pytest.skip('r4 runtime absent')
    pairs = {R4 / 'install-after.json': m.INSTALL_RECEIPT_SHA256, R4 / 'source-manifest.json': m.MANIFEST_SHA256,
             R4 / 'pipeline.json': m.CONFIG_SHA256, R4 / 'windows-layout.json': m.LAYOUT_SHA256,
             R4 / '.venv' / 'Scripts' / 'python.exe': m.PYTHON_SHA256, R4 / '.venv' / 'pyvenv.cfg': m.VENV_CONFIG_SHA256,
             R4_SITE / 'windows.py': m.WINDOWS_SHA256, R4_SITE / 'resource_limits.py': m.RESOURCE_SHA256,
             R4_SITE / 'resource_telemetry.py': m.REPAIR_SHA256, m.BASE_PYTHON: m.BASE_PYTHON_SHA256, m.EXECUTABLE: m.AGY_SHA256}
    for path, pin in pairs.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == pin, path


def test_inference_argv_is_the_production_argv_without_forbidden_flags():
    protocol = r4_protocol()
    protocol.validate_arguments(list(m.PRODUCTION_ARGUMENTS))
    assert m.PROMPT_LINE == protocol.encode_prompt(m.PROMPT).encode() and len(m.PROMPT_LINE) == 72
    assert m.PROMPT_LINE_SHA256 == '383e4810ee804f34f037081155a02cf68a4d9a4f099c8577afe0a57597569bfb'
    forbidden = {'-p', '--print', '--prompt', '-i', '--prompt-interactive', '-c', '--continue', '--conversation',
                 '--dangerously-skip-permissions', '--print-timeout', '--project', '--log-file'}
    assert forbidden <= m.FORBIDDEN_FLAGS
    for run_id, model, extra, _ in m.run_matrix('gemini-3.8-flash-medium'):
        argv = m.inference_argv(model, extra)
        assert argv == [str(m.EXECUTABLE), *run_args(model, extra)], run_id
        assert not {arg.split('=', 1)[0] for arg in argv} & m.FORBIDDEN_FLAGS
    base = [str(m.EXECUTABLE), *run_args('gemini-3.8-flash-high')]
    for bad in (base + ['-p', 'x'], base + ['--print-timeout', '90s'], base + ['--effort', 'low'], base[:-1],
                base[:1] + ['--project', 'x'] + base[1:], ['agy.exe'] + base[1:], base + ['--log-file=x']):
        with pytest.raises(ValueError):
            m.assert_inference_argv(bad)


# ---------------------------------------------------------------- stream classification and the R1 contract

def classify(stdout, stderr=b'', code=0, model='gemini-3.8-flash-high', outcome='exited', processes=2):
    record = {'outcome': outcome, 'exit_code': code if outcome == 'exited' else 'terminated', 'requested_model': model,
              'job_accounting': job_accounting(processes)}
    record['classification'] = m.classify_run(stdout, stderr, outcome, record['exit_code'], model, r4_protocol())
    record['checks'] = m.run_checks(record, model)
    return record


FAILURE_TABLE = {
    'pass': (dict(), [], True),
    'tools_not_empty': (dict(stdout=stream(tools=('view_file', 'manage_task'))), ['tools_empty'], False),
    'tools_missing': (dict(stdout=stream().replace(b'"tools":[],', b'')), ['tools_empty'], False),
    'wrong_agent': (dict(stdout=stream(agent='cochem-audit')), ['agent_matches'], False),
    'agent_absent': (dict(stdout=stream(agent=None)), ['agent_matches'], False),
    'model_mismatch': (dict(stdout=stream(model='gemini-3.8-flash-low')), ['model_matches'], False),
    'model_missing_without_model_flag': (dict(stdout=stream(include_model=False)), ['model_matches'], False),
    'tool_step': (dict(stdout=stream(extra_steps=[{'step_type': 'tool', 'tool_name': 'view_file', 'tool_info': {'path': 'x'},
                                                   'state': 'DONE', 'step_index': 1}])),
                  ['no_tool_steps', 'only_allowed_step_types'], False),
    'tool_name_on_response': (dict(stdout=stream(extra_steps=[{'step_type': 'agent_response', 'tool_name': 'run_command',
                                                               'state': 'DONE', 'step_index': 1}])), ['no_tool_steps'], False),
    'subagent_step': (dict(stdout=stream(extra_steps=[{'step_type': 'agent_response', 'subagent_info': {'name': 'helper'},
                                                       'state': 'DONE', 'step_index': 1}])), ['no_subagent_steps'], False),
    'num_turns_two': (dict(stdout=stream(num_turns=2)), ['num_turns_one'], False),
    'result_error': (dict(stdout=stream(status='ERROR', error='quota exhausted'), code=1), ['exited_zero', 'result_success'], False),
    'result_model_mismatch': (dict(stdout=stream(result_extra={'model': 'gemini-3.8-flash-low'})), ['result_model_absent_or_equal'], False),
    'step_model_mismatch': (dict(stdout=stream(step_rows=steps('conv-1', model='gemini-3.8-flash-low'))), ['step_models_match'], False),
    'session_mismatch': (dict(stdout=stream(result_extra={'conversation_id': 'other'})), ['stream_well_formed'], False),
    'malformed_line': (dict(stdout=stream() + b'{not json SECRET-MALFORMED\n'), ['stream_well_formed'], False),
    'exit_nonzero': (dict(code=2), ['exited_zero'], False),
}
for _marker in m.STDERR_MARKERS:
    FAILURE_TABLE['marker:' + _marker] = (dict(stderr=('note: ' + _marker + ' x\n').encode()), ['no_stderr_markers'], False)


@pytest.mark.parametrize('name', sorted(FAILURE_TABLE))
def test_r1_contract_table(name):
    kwargs, failing, passes = FAILURE_TABLE[name]
    record = classify(kwargs.get('stdout', stream()), kwargs.get('stderr', b''), kwargs.get('code', 0))
    checks = record['checks']
    assert sorted(key for key, _ in m.RUN_CHECK_REASONS if checks[key] is not True) == sorted(failing), checks
    assert checks['passes_contract'] is passes
    gate = m.isolation_gate('EVIDENCE_COMPLETE', {'passed': True, 'reasons': []}, [dict(record, id='R1')])
    assert gate['passed'] is passes
    assert gate['reasons'] == [reason for key, reason in m.RUN_CHECK_REASONS if key in failing]
    dumped = json.dumps(record)
    assert 'SECRET' not in dumped and 'ready true' not in dumped, 'answers are reduced to a digest, malformed lines never echoed'


def test_timeout_and_output_bound_are_recorded_not_raised():
    timed = classify(stream()[:40], outcome='timed_out_terminated')
    assert timed['classification']['timed_out'] and not timed['checks']['exited_zero'] and not timed['checks']['passes_contract']
    big = classify(stream() + b' ' * (m.RUN_OUTPUT + 1))
    assert big['classification']['output_bound_exceeded'] and not big['checks']['stream_well_formed']
    assert big['classification']['stream']['lines'] == 0, 'an oversize stream is not parsed at all'


def test_error_text_and_agy_error_lines_are_sanitized():
    record = classify(stream(status='ERROR', error='denied for ' + EMAIL + ' see ' + SECRET_URL), code=1)
    assert record['classification']['stream']['result']['error_text'] is None
    assert record['classification']['stream']['result']['error_withheld_reason'] == 'unsafe_content'
    lines = m.agy_error_lines('AGY_ERROR: {"code":"UNAVAILABLE","message":"no access for ' + EMAIL + '","retryable":true}\nAGY_ERROR: [1]\n')
    assert lines == [{'parsed': True, 'keys': ['code', 'message', 'retryable'], 'fields': {'code': 'UNAVAILABLE', 'message': None, 'retryable': True}},
                     {'parsed': False, 'keys': [], 'fields': {}}]
    assert m.error_templates(R2_REJECT.decode(), 'unknown model "gemini-3.1-pro-preview"') == [
        'invalid_model_selection', 'model_conflicts_with_effort', 'unknown_model']


def test_echo_form_passes_for_the_family_id_only_with_a_consistent_echo():
    echo = classify(stream(model='gemini-3.8-flash-high'), model='gemini-3.8-flash')
    assert echo['checks']['model_matches'] is False and echo['checks']['passes_contract'] is False
    assert echo['checks']['echo_consistent'] is True and echo['checks']['passes_with_echo'] is True
    broken = classify(stream(model='gemini-3.8-flash-high', step_rows=steps('conv-1', model='gemini-3.8-flash-low')), model='gemini-3.8-flash')
    assert broken['checks']['echo_consistent'] is False and broken['checks']['passes_with_echo'] is False
    absent = classify(stream(include_model=False), model='gemini-3.8-flash')
    assert absent['checks']['passes_with_echo'] is False


def run_row(run_id, record):
    return dict(record, id=run_id, extra_arguments=[])


def test_identity_verdict_effort_null_echo_and_reroute_scan():
    matrix = m.run_matrix('gemini-3.8-flash-low')
    runs = [run_row('R1', classify(stream())), run_row('R5', classify(stream(model='gemini-3.8-flash-low'), model='gemini-3.8-flash-low')),
            run_row('R2', classify(b'', R2_REJECT, 1)), run_row('R3', classify(stream(), model='gemini-3.8-flash')),
            run_row('R4', classify(R4_STDOUT, R4_STDERR, 3, model='gemini-3.1-pro-preview'))]
    verdict = m.identity_verdict(runs, matrix, 'gemini-3.8-flash-low')
    assert verdict['effort_null'] == {'slug': 'gemini-3.8-flash-low', 'run_id': 'R5', 'executed': True, 'passed': True, 'init_model': 'gemini-3.8-flash-low'}
    assert verdict['slug_form_accepted'] and verdict['slug_form_passes_contract']
    assert verdict['slug_with_effort_accepted'] is False and verdict['slug_with_effort_init_model'] is None
    assert verdict['family_with_effort_accepted'] and verdict['family_with_effort_passes_with_echo']
    assert verdict['family_with_effort_init_model'] == 'gemini-3.8-flash-high'
    assert verdict['unknown_model_rejected'] and verdict['unknown_model_exit_code'] == 3
    assert verdict['unknown_model_error_templates'] == ['unknown_model']
    assert verdict['reroute_scan_clean'] is True, "R4's expected AGY_ERROR line is not an accepted run"
    runs[1] = run_row('R5', classify(stream(model='gemini-3.8-flash-high'), model='gemini-3.8-flash-low'))
    assert m.identity_verdict(runs, matrix, 'gemini-3.8-flash-low')['effort_null']['passed'] is False
    runs[0] = run_row('R1', classify(stream(), b'Restored session model to gemini-3.8-flash-low\n'))
    assert m.identity_verdict(runs, matrix, 'gemini-3.8-flash-low')['reroute_scan_clean'] is False
    missing = m.identity_verdict([], matrix, 'gemini-3.8-flash-low')
    assert missing['effort_null']['executed'] is False and missing['reroute_scan_clean'] is False


def test_isolation_gate_breach_anywhere_in_the_matrix_fails_it():
    good = run_row('R1', classify(stream()))
    breach = run_row('R5', classify(stream(tools=('view_file',)), model='gemini-3.8-flash-low'))
    gate = m.isolation_gate('EVIDENCE_COMPLETE', {'passed': True, 'reasons': []}, [good, breach])
    assert gate == {'passed': False, 'reasons': ['ISOLATION_BREACH_IN_MATRIX']}
    assert m.isolation_gate('EVIDENCE_INCOMPLETE', {'passed': True, 'reasons': []}, [good]) == {'passed': False, 'reasons': ['EVIDENCE_NOT_COMPLETE']}
    assert m.isolation_gate('EVIDENCE_PRECHECK_REFUSED', {'passed': False, 'reasons': ['AGENTS_PRECHECK_FAILED']}, []) == {
        'passed': False, 'reasons': ['AGENTS_PRECHECK_FAILED']}
    assert m.isolation_gate('EVIDENCE_COMPLETE', {'passed': True, 'reasons': []}, []) == {'passed': False, 'reasons': ['R1_NOT_RUN']}
    clear = dict(dict.fromkeys(m.INVENTORY_KEYS, True), programdata_antigravity_clear=True)
    assert m.isolation_gate('EVIDENCE_COMPLETE', {'passed': True, 'reasons': []}, [good], clear) == {'passed': True, 'reasons': []}
    for key in m.INVENTORY_KEYS:
        assert m.isolation_gate('EVIDENCE_COMPLETE', {'passed': True, 'reasons': []}, [good], dict(clear, **{key: False})) == {
            'passed': False, 'reasons': ['PROFILE_INVENTORY_NOT_CLEAR']}, key
    # O-F2: C:\ProgramData\Antigravity not absent / not the protected empty folder holds G3 with its own reason.
    assert m.isolation_gate('EVIDENCE_COMPLETE', {'passed': True, 'reasons': []}, [good], dict(clear, programdata_antigravity_clear=False)) == {
        'passed': False, 'reasons': ['PROGRAMDATA_ANTIGRAVITY_NOT_CLEAR']}
    # O-F1: a process beyond agy's own tree, in R1 or anywhere in the matrix, holds G3 with a named reason.
    extra_r1 = run_row('R1', classify(stream(), processes=3))
    assert extra_r1['checks']['job_processes_within_tree'] is False and extra_r1['checks']['isolation_breach'] is True
    assert extra_r1['checks']['passes_contract'] is True, 'the identity contract itself is unchanged'
    assert m.isolation_gate('EVIDENCE_COMPLETE', {'passed': True, 'reasons': []}, [extra_r1], clear) == {
        'passed': False, 'reasons': ['JOB_PROCESSES_BEYOND_AGY_TREE']}
    extra_r2 = run_row('R2', classify(b'', R2_REJECT, 1, processes=5))
    assert m.isolation_gate('EVIDENCE_COMPLETE', {'passed': True, 'reasons': []}, [good, extra_r2], clear) == {
        'passed': False, 'reasons': ['ISOLATION_BREACH_IN_MATRIX', 'JOB_PROCESSES_BEYOND_AGY_TREE']}
    for total in (0, None, True, '2'):
        record = classify(stream())
        record['job_accounting'] = dict(record['job_accounting'], total_processes=total)
        assert m.run_checks(record, 'gemini-3.8-flash-high')['job_processes_within_tree'] is False, total
    missing = classify(stream())
    del missing['job_accounting']
    assert m.run_checks(missing, 'gemini-3.8-flash-high')['isolation_breach'] is True, 'missing accounting fails closed'
    assert m.run_checks(classify(stream(), processes=1), 'gemini-3.8-flash-high')['job_processes_within_tree'] is True


def test_isolation_verdict_disables_follow_the_inventory():
    r1 = run_row('R1', classify(stream()))
    clean = {'hooks_present': False, 'mcp_present': False, 'plugins_present': False, 'skills_present': False}
    profiles = [{'flags': dict(clean)} for _ in range(6)]
    workspaces = [{'label': 'slot_root', 'flags': dict(clean)}, {'label': 'ram_workspace', 'flags': dict(clean)}]
    programdata = {'clear': True}
    verdict = m.isolation_verdict([r1], profiles, workspaces, programdata)
    assert {k: verdict[k] for k in ('disables_tools', 'disables_mcp', 'disables_hooks', 'disables_subagents')} == dict.fromkeys(
        ('disables_tools', 'disables_mcp', 'disables_hooks', 'disables_subagents'), True)
    assert verdict['model_fallback_basis'] == 'UNKNOWN' and 'disables_model_fallback' not in verdict
    assert verdict['process_accounting_clean'] is True and verdict['programdata_antigravity_clear'] is True
    # O-F1/O-F2: disables_hooks/disables_mcp need the extended inventory clear AND clean process accounting.
    for runs, data in (([run_row('R1', classify(stream(), processes=3))], programdata), ([r1], {'clear': False}), ([r1], None)):
        verdict = m.isolation_verdict(runs, profiles, workspaces, data)
        assert not verdict['disables_mcp'] and not verdict['disables_hooks'] and verdict['disables_subagents'], (runs, data)
    profiles[3]['flags']['plugins_present'] = True
    verdict = m.isolation_verdict([r1], profiles, workspaces, programdata)
    assert not verdict['disables_mcp'] and not verdict['disables_hooks'] and verdict['disables_tools'] and verdict['disables_subagents']
    assert not m.isolation_verdict([r1], profiles[:5], workspaces, programdata)['hooks_absent'], 'six profiles are required'


def test_listing_probe_rules():
    def probe(agents, code=0, status='SUCCESS', name='agents', outcome='exited', unlisted=0):
        return {'id': 'PC3', 'outcome': outcome, 'exit_code': code, 'classification': {
            'agents': agents, 'agents_count': len(agents), 'agents_unlisted': unlisted, 'status_value': status, 'command_name': name}}
    assert m.agents_probe_ok(probe(['cochem-inference-only']), True)
    for bad in (probe([]), probe(['cochem-inference-only', 'cochem-audit']), probe(['cochem-inference-only'], code=1),
                probe(['cochem-inference-only'], status='ERROR'), probe(['cochem-inference-only'], name='models'),
                probe(['cochem-inference-only'], outcome='timed_out_terminated', code='terminated'), probe(['cochem-inference-only'], code=True)):
        assert not m.agents_probe_ok(bad, True)
    text = probe(['cochem-inference-only'], status=None, name=None)
    assert m.agents_probe_ok(text, False) and not m.agents_probe_ok(text, True)
    assert m.listing_reasons([]) == ['AGENTS_JSON_LISTING_FAILED', 'AGENTS_TEXT_LISTING_FAILED']
    value = m.classify_probe('agents_json', AGENTS_OK, b'', 'exited', 0)
    assert value['command_name'] == 'agents' and value['status_value'] == 'SUCCESS' and value['agents'] == ['cochem-inference-only']


# ---------------------------------------------------------------- secrets: env names, inventory, raw scan and replay copies

def test_environment_attestation_records_names_never_values(tmp_path):
    profile = tmp_path / 'CoChem422Worker1'
    block = (f'HOME={profile}\x00USERPROFILE={profile}\x00APPDATA={profile}\\AppData\\Roaming\x00LOCALAPPDATA={profile}\\AppData\\Local\x00'
             f'AGY_ACCOUNT={EMAIL}\x00GOOGLE_API_KEY=SECRETKEY\x00XDG_CONFIG_HOME=C:\\x\x00PATH=C:\\Windows\x00=C:=C:\\\x00')
    value = m.environment_names(block, profile)
    assert value['flagged_names'] == ['AGY_ACCOUNT', 'GOOGLE_API_KEY', 'XDG_CONFIG_HOME'] and value['flagged_names_absent'] is False
    assert value['profile_binding_verified'] is True and value['values_recorded'] is False and value['variable_count'] == 8
    assert EMAIL not in json.dumps(value) and 'SECRETKEY' not in json.dumps(value)


def test_environment_attestation_builds_the_block_as_system_without_a_process(tmp_path):
    profile = tmp_path / 'CoChem422Worker1'
    calls = []
    kernel = SimpleNamespace(CreateMutexW=lambda *a: calls.append(('mutex', a[2])) or 23)
    userenv = SimpleNamespace(LoadUserProfileW=lambda token, info: calls.append('load') or 1,
                              UnloadUserProfile=lambda token, handle: calls.append('unload') or 1)

    def environment(token, overrides, limits=None):
        calls.append(('environment', overrides, limits))
        return C.create_unicode_buffer(f'HOME={profile}\x00USERPROFILE={profile}\x00GEMINI_X=1\x00\x00')
    from cochem_pipeline import windows as real
    win = SimpleNamespace(_api=lambda: {'kernel32': kernel, 'userenv': userenv}, _check=lambda v, *a: v, _close=lambda *a: calls.append('close'),
                          _worker_token=lambda identity: calls.append('token') or 99, _PROFILEINFOW=real._PROFILEINFOW,
                          _worker_environment=environment)

    def load_profile(token, info):
        info._obj.hProfile = 7
        calls.append('load')
        return 1
    userenv.LoadUserProfileW = load_profile
    value = m.attest_environment(win, SimpleNamespace(name='CoChem422Worker1'), 'S-1-5-21-1', 'limits', profile)
    assert value['flagged_names'] == ['GEMINI_X'] and value['values_recorded'] is False
    assert calls == [('mutex', 'Global\\CoChemPipeline422-S-1-5-21-1'), 'token', 'load', ('environment', None, 'limits'), 'unload', 'close', 'close']


def test_inventory_never_opens_token_files(tmp_path, monkeypatch):
    profile = tmp_path / 'CoChem422Worker1'
    cli = profile / '.gemini' / 'antigravity-cli'
    cli.mkdir(parents=True)
    (cli / 'antigravity-oauth-token').write_bytes(b'SECRET-TOKEN-VALUE')
    (cli / 'cli.log').write_bytes(b'log ' + EMAIL.encode())
    (profile / '.gemini' / 'config' / 'plugins' / 'firebase').mkdir(parents=True)
    opened = []
    real = m.open_for_hash
    monkeypatch.setattr(m, 'open_for_hash', lambda path: opened.append(str(path)) or real(path))
    rows = {row['path']: row for row in m.inventory_path(profile, '.gemini/antigravity-cli')['entries']}
    assert rows['antigravity-oauth-token'] == {'path': 'antigravity-oauth-token', 'kind': 'file', 'size': 18, 'sha256': None, 'token_file': True}
    assert not any('token' in path.casefold() for path in opened) and len(opened) == 1
    profiles = m.six_profile_inventory({'slot1': {'identity': 'CoChem422Worker1'}}, tmp_path)
    assert profiles[0]['flags']['plugins_present'] and profiles[0]['flags']['mcp_present'] and profiles[0]['flags']['hooks_present']
    token = next(row for row in profiles[0]['paths'] if row['path'] == '.gemini/antigravity-cli/antigravity-oauth-token')
    assert token['token_file'] is True and token['sha256'] is None
    dumped = json.dumps(profiles)
    assert 'SECRET' not in dumped and EMAIL not in dumped


def test_redaction_removes_account_and_credential_shapes_and_keeps_json_valid():
    line = json.dumps({'event': 'result', 'result': {'response': 'mail ' + EMAIL, 'note': SECRET_URL, 'access_token': 'SECRETVALUE1',
                                                     'debug': 'Bearer abcdefghijklmnop ' + SECRET_TOKEN + ' ' + SECRET_REFRESH}}).encode() + b'\n'
    redacted, counts = m.redact(line)
    text = redacted.decode()
    for secret in SECRETS + ('SECRETVALUE1', 'abcdefghijklmnop'):
        assert secret not in text, secret
    assert json.loads(text)['result']['response'] == 'mail REDACTED_EMAIL'
    assert set(counts) == {'email', 'url', 'secret_field', 'bearer', 'google_access_token', 'google_refresh_token'}
    assert m.sensitive_scan(redacted) == [] and m.sensitive_scan(line) == sorted(counts)
    clean = stream()
    assert m.redact(clean) == (clean, {}), 'a clean model stream is replayed byte for byte'


def test_write_replay_is_create_new_and_bounded(tmp_path):
    raw, replay = tmp_path / 'raw', tmp_path / 'replay'
    raw.mkdir()
    replay.mkdir()
    (raw / 'R1.stdout').write_bytes(stream())
    (raw / 'R1.stderr').write_bytes(R1_STDERR)
    value = m.write_replay(replay, 'R1', raw / 'R1.stdout', raw / 'R1.stderr')
    assert value['available'] is True and value['stdout']['path'] == 'replay/R1.stdout' and value['stderr']['redactions'] == {'email': 1}
    assert (replay / 'R1.stdout').read_bytes() == stream() and EMAIL.encode() not in (replay / 'R1.stderr').read_bytes()
    assert value['stderr']['sha256'] == hashlib.sha256((replay / 'R1.stderr').read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        m.write_replay(replay, 'R1', raw / 'R1.stdout', raw / 'R1.stderr')
    (raw / 'R2.stdout').write_bytes(b'x' * (m.RUN_OUTPUT + 1))
    (raw / 'R2.stderr').write_bytes(b'')
    assert m.write_replay(replay, 'R2', raw / 'R2.stdout', raw / 'R2.stderr') == {'available': False, 'reason': 'raw_stream_over_bound'}
    assert not (replay / 'R2.stdout').exists()
    # A credential-looking field is redacted once and the redacted copy is clean (no false 'redaction_incomplete').
    (raw / 'R3.stdout').write_bytes(stream())
    (raw / 'R3.stderr').write_bytes(b'debug {"refresh_token":"abcdef123456","api_key": "SECRETKEY99"}\n')
    value = m.write_replay(replay, 'R3', raw / 'R3.stdout', raw / 'R3.stderr')
    assert value['available'] is True and value['stderr']['redactions'] == {'secret_field': 2}
    assert (replay / 'R3.stderr').read_bytes() == b'debug {"refresh_token":"REDACTED_VALUE","api_key": "REDACTED_VALUE"}\n'


# ---------------------------------------------------------------- launches: image fallback, bounds, stdin, phases

def test_image_attestation_fallback_table(tmp_path):
    exe = tmp_path / 'agy.exe'
    exe.write_bytes(b'MZ')
    device = lambda: r'\Device\HarddiskVolume3\fixture\agy.exe'
    calls = []

    def query(answers):
        def inner(flags):
            calls.append(flags)
            return answers[flags]
        return inner
    assert m.attest_image(query({0: str(exe)}), lambda ms: False, exe, device) == 'win32'
    with pytest.raises(ValueError, match='differs'):
        m.attest_image(query({0: str(tmp_path / 'other.exe')}), lambda ms: True, exe, device)
    waits = []
    assert m.attest_image(query({0: None, 1: device()}), lambda ms: waits.append(ms) or True, exe, device) == 'native_after_exit'
    assert waits == [m.EXIT_SETTLE_MILLISECONDS], 'any query failure (error 5 during teardown or 31 after exit) waits on the owned handle'
    calls.clear()
    with pytest.raises(ValueError, match='image failed'):
        m.attest_image(query({0: None, 1: device()}), lambda ms: False, exe, device)
    assert calls == [0], 'a still-running child is never attested by the native form'
    with pytest.raises(ValueError):
        m.attest_image(query({0: None, 1: None}), lambda ms: True, exe, device)
    with pytest.raises(ValueError, match='differs'):
        m.attest_image(query({0: None, 1: r'\Device\HarddiskVolume3\other.exe'}), lambda ms: True, exe, device)


def launch_harness(tmp_path, monkeypatch, script, matches=True):
    module = load()
    monkeypatch.setattr(module, 'time', FakeTime())
    calls, launched = [], []
    monkeypatch.setattr(module, 'require_stopped', lambda *a: calls.append('require_stopped'))
    profile = tmp_path / 'profile'
    monkeypatch.setattr(module, 'observe_child', lambda *a: attestation(profile if matches else tmp_path / 'other'))
    monkeypatch.setattr(module, 'verify_staged_agent', lambda *a: [module.AGENT_SHA256, module.AGENT_SHA256])
    monkeypatch.setattr(module, 'job_process_accounting', lambda win_, process: calls.append('accounting') or dict(process.accounting))

    def launch_worker(identity, argv, cwd, stdin, output, errors, limits=None):
        calls.append('launch')
        process = FakeProcess(script, stdin, output, errors, profile, 'CoChem422Worker1', argv)
        launched.append(process)
        return process
    raw = tmp_path / 'raw'
    raw.mkdir()
    return module, SimpleNamespace(launch_worker=launch_worker), raw, hashlib.sha256(str(profile).casefold().encode()).hexdigest(), calls, launched


def drain(process):
    data = b''
    while chunk := os.read(process.stdin_fd, 4096):
        data += chunk
    os.close(process.stdin_fd)
    return data


def test_inference_delivers_one_ndjson_line_then_eof(tmp_path, monkeypatch):
    module, win, raw, sha, calls, launched = launch_harness(tmp_path, monkeypatch, {'stdout': stream(), 'code': 0})
    replay = tmp_path / 'replay'
    replay.mkdir()
    record = module.run_inference(win, 'identity', 'R1', 'gemini-3.8-flash-high', (), str(tmp_path), raw, None, 'S', sha,
                                  [], r4_protocol(), {}, replay)
    assert drain(launched[0]) == module.PROMPT_LINE, 'exactly the one reviewed line, then EOF'
    assert calls == ['require_stopped', 'launch', 'accounting'] and launched[0].closed and record['cleanup_verified'] is True
    assert record['job_accounting']['total_processes'] == 2 and record['checks']['job_processes_within_tree'] is True
    assert record['prompt_delivered'] and record['stdin_bytes_written'] == 72 and record['phase_reached'] == 'inference_result'
    assert record['checks']['passes_contract'] and record['classification']['agy_protocol_parse_stream']['accepted'] is True
    assert record['replay']['available'] and (raw / 'R1.stdin').read_bytes() == module.PROMPT_LINE


def test_inference_timeout_terminates_the_fake_process(tmp_path, monkeypatch):
    module, win, raw, sha, calls, launched = launch_harness(tmp_path, monkeypatch, {'stdout': stream()[:30], 'code': None})
    record = module.run_inference(win, 'identity', 'R1', 'gemini-3.8-flash-high', (), str(tmp_path), raw, None, 'S', sha, [], None, {})
    drain(launched[0])
    assert record['outcome'] == 'timed_out_terminated' and record['exit_code'] == 'terminated' and record['terminated_by_bound'] is True
    assert launched[0].closed and 120000 <= record['elapsed_ms'] <= 120200 and launched[0].polls >= 2400
    assert not record['checks']['passes_contract']


def test_probe_output_bound_and_profile_mismatch(tmp_path, monkeypatch):
    module, win, raw, sha, calls, launched = launch_harness(tmp_path, monkeypatch, {'stdout': b'y' * 70000, 'code': None})
    record = module.run_probe(win, 'identity', 'PC2', ('--output-format', 'json', 'models'), 'models_json', str(tmp_path), raw, None, 'S', sha, {})
    drain(launched[0])
    assert record['outcome'] == 'output_bound_terminated' and record['classification']['status_helper_classification'] == 'HOLD'
    assert record['stdout']['bytes'] == 70000 and record['stdin_sha256'] == hashlib.sha256(b'').hexdigest()
    other = tmp_path / 'b'
    other.mkdir()
    module, win, raw, sha, calls, launched = launch_harness(other, monkeypatch, {'stdout': b'1.3.1\n', 'code': 0}, matches=False)
    record = {}
    with pytest.raises(ValueError, match='profile'):
        module.run_probe(win, 'identity', 'PC1', ('--version',), 'version', str(other), raw, None, 'S', sha, record, prefix='slot2-')
    drain(launched[0])
    assert launched[0].closed and record['cleanup_verified'] is False and record['phase_reached'] == 'native_attestation'
    assert record['raw_path'] == {'stdout': 'raw/slot2-PC1.stdout', 'stderr': 'raw/slot2-PC1.stderr'}


def test_launch_boundary_rechecks_the_daemons_every_time(monkeypatch):
    order = []
    monkeypatch.setattr(m, 'require_stopped', lambda win: order.append('require_stopped'))
    win = SimpleNamespace(launch_worker=lambda *a, **k: order.append(('launch', k['limits'])) or 'process')
    assert m.launch_native_process(win, 'id', ['a'], 'cwd', 'i', 'o', 'e', 'limits') == 'process'
    assert order == ['require_stopped', ('launch', 'limits')]


# ---------------------------------------------------------------- staging and ACL

def test_staging_writes_both_locations_with_the_intended_acl(tmp_path, monkeypatch):
    acl = FakeAcl()
    from cochem_pipeline import windows as win
    monkeypatch.setattr(m, 'apply_sddl', acl.apply)
    monkeypatch.setattr(win, '_acl', acl.read)
    profile = tmp_path / 'CoChem422Worker5'
    profile.mkdir()
    sid = 'S-1-5-21-1-2-3-1005'
    records = m.stage_agent(win, AGENT, profile, sid)
    expected = [(str(profile / '.gemini' / 'agents' / 'cochem-inference-only'), f'O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;{sid})'),
                (str(profile / '.gemini' / 'agents' / 'cochem-inference-only' / 'agent.md'), f'O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;0x120089;;;{sid})'),
                (str(profile / '.gemini' / 'config' / 'agents' / 'cochem-inference-only'), f'O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;{sid})'),
                (str(profile / '.gemini' / 'config' / 'agents' / 'cochem-inference-only' / 'agent.md'), f'O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;0x120089;;;{sid})')]
    assert acl.applied == expected, 'only the leaf directories and the files get the protected ACL'
    assert [r['relative'] for r in records] == ['.gemini/agents/cochem-inference-only/agent.md', '.gemini/config/agents/cochem-inference-only/agent.md']
    for record in records:
        assert Path(record['path']).read_bytes() == AGENT.read_bytes() and record['sha256'] == m.AGENT_SHA256 and record['preexisting'] is False
    assert parse_sddl(expected[1][1]) == ('S-1-5-18', True, [('S-1-5-18', 0x1F01FF, 0), ('S-1-5-32-544', 0x1F01FF, 0), (sid, 0x120089, 0)])
    again = m.stage_agent(win, AGENT, profile, sid)
    assert [r['preexisting'] for r in again] == [True, True] and len(acl.applied) == 4, 'identical bytes are reused, never rewritten'
    (profile / '.gemini' / 'config' / 'agents' / 'cochem-inference-only' / 'agent.md').write_bytes(b'tampered\n')
    with pytest.raises(ValueError, match='different agent definition'):
        m.stage_agent(win, AGENT, profile, sid)
    with pytest.raises(ValueError, match='changed before launch'):
        m.verify_staged_agent(win, records, sid)
    other = tmp_path / 'CoChem422Worker6'
    (other / '.gemini' / 'agents' / 'cochem-inference-only').mkdir(parents=True)
    with pytest.raises(ValueError, match='ACL'):
        m.stage_agent(win, AGENT, other, sid)


def test_shadow_check_finds_same_name_definitions(tmp_path):
    profile = tmp_path / 'p'
    (profile / '.gemini' / '.agents').mkdir(parents=True)
    (profile / '.gemini' / '.agents' / 'cochem-inference-only.agent.md').write_bytes(b'x')
    (profile / '.gemini' / 'config' / 'plugins' / 'firebase' / 'agents').mkdir(parents=True)
    (profile / '.gemini' / 'config' / 'plugins' / 'firebase' / 'agents' / 'cochem-inference-only.md').write_bytes(b'x')
    workspace = tmp_path / 'ws'
    (workspace / '.agents' / 'agents' / 'cochem-inference-only').mkdir(parents=True)
    checked, found = m.shadow_check(profile, (('slot_root', workspace), ('ram_workspace', None)))
    assert sorted(item['reason'] for item in found) == ['same_name'] * 3 and len(checked) >= 6


# ---------------------------------------------------------------- O-F1: every documented customization location

FLAG_KEYS = ('hooks_present', 'mcp_present', 'plugins_present', 'skills_present')


def bounded_ancestors(monkeypatch, floor):
    real = m.workspace_ancestors
    monkeypatch.setattr(m, 'workspace_ancestors', lambda root: [p for p in real(root) if str(p).startswith(str(floor))])


def test_workspace_ancestors_reach_the_drive_root():
    assert [str(p) for p in m.workspace_ancestors(Path(r'C:\ProgramData\CoChemPipeline427\workers\slot1'))] == [
        r'C:\ProgramData\CoChemPipeline427\workers', r'C:\ProgramData\CoChemPipeline427', r'C:\ProgramData', 'C:\\']
    assert [str(p) for p in m.workspace_ancestors(Path(r'R:\CoChem427-windows-20261007\slot1'))] == [r'R:\CoChem427-windows-20261007', 'R:\\']
    for bad in ('slot1', r'\CoChem427\slot1'):
        with pytest.raises(ValueError):
            m.workspace_ancestors(Path(bad))
    if (R4 / 'pipeline.json').exists():
        config = json.loads((R4 / 'pipeline.json').read_bytes())
        assert str(m.ram_workspace_root(config, 'slot1')) == r'R:\CoChem427-windows-20261007\slot1', 'the production cwd chain'
    assert m.WORKSPACE_PATHS[:4] == ('.agents/hooks.json', '.agents/mcp_config.json', '.agents/skills', '.agents/agents')
    assert len(m.WORKSPACE_PATHS) == 18 and m.WORKSPACE_PATHS[-2:] == ('skills.json', 'plugins.json')
    assert {path.split('/')[0] for path in m.WORKSPACE_PATHS[:16]} == {'.agents', '.agent', '_agents', '_agent'}


def test_workspace_inventory_covers_alternative_folders_declared_configs_and_ancestors(tmp_path, monkeypatch):
    """The auditor's repro 1: each documented location alone flips the workspace flags; ancestors are walked."""
    def world(name):
        slot_root = tmp_path / name / 'workers' / 'slot1'
        slot_root.mkdir(parents=True)
        return slot_root
    unbounded = world('real-walk')
    (unbounded / '.agent').mkdir()
    (unbounded / '.agent' / 'hooks.json').write_bytes(b'{"hooks":{}}')
    real = m.workspace_inventory('slot_root', unbounded)
    assert real['flags']['hooks_present'] is True and real['ancestors'][-1]['directory'] == tmp_path.anchor, 'the real walk ends at the drive root'
    bounded_ancestors(monkeypatch, tmp_path)
    clean = m.workspace_inventory('slot_root', world('clean'))
    assert clean['flags'] == dict.fromkeys(FLAG_KEYS, False) and clean['root_present'] is True
    assert [row['path'] for row in clean['paths']] == list(m.WORKSPACE_PATHS)
    assert [item['directory'] for item in clean['ancestors']] == [str(tmp_path / 'clean' / 'workers'), str(tmp_path / 'clean'), str(tmp_path)]
    every = set(FLAG_KEYS)
    for name, relative, expected in (('dot_agent', '.agent/hooks.json', {'hooks_present'}), ('underscore_agents', '_agents/mcp_config.json', {'mcp_present'}),
                                     ('underscore_agent', '_agent/skills/x/SKILL.md', {'skills_present'}), ('skills_json', 'skills.json', {'skills_present'}),
                                     ('plugins_json', 'plugins.json', every), ('dot_agents', '.agents/mcp_config.json', {'mcp_present'})):
        slot_root = world(name)
        target = slot_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'{}')
        assert {key for key in FLAG_KEYS if m.workspace_inventory('slot_root', slot_root)['flags'][key]} == expected, name
        ancestor = world(name + '-ancestor')
        target = ancestor.parent / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'{}')
        record = m.workspace_inventory('slot_root', ancestor)
        assert {key for key in FLAG_KEYS if record['flags'][key]} == expected, name + ' in an ancestor'
        assert all(not row['exists'] for row in record['paths']), 'the root itself is clean; the ancestor carries it'
    # The RAM workspace root before admission: missing, yet its ancestors are inventoried.
    ram = tmp_path / 'R' / 'CoChem427-windows-20261007' / 'slot1'
    (tmp_path / 'R' / '_agent').mkdir(parents=True)
    (tmp_path / 'R' / '_agent' / 'hooks.json').write_bytes(b'{}')
    record = m.workspace_inventory('ram_workspace', ram)
    assert record['root_present'] is False and record['flags']['hooks_present'] is True
    assert [item['directory'] for item in record['ancestors']] == [str(ram.parent), str(tmp_path / 'R'), str(tmp_path)]
    verdict = m.isolation_verdict([], [{'flags': dict.fromkeys(FLAG_KEYS, False)}] * 6, [record], {'clear': True})
    assert verdict['hooks_absent'] is False and verdict['disables_hooks'] is False


DECLARED_CASES = (
    # name, bytes, status, reason, top_level_keys, matching_keys, flagged_keys. The Commander's six first.
    ('empty_object', b'{}', 'CLEAR', None, [], [], []),
    ('settings_only', b'{"theme":"dark","userSettings":{"fontSize":12,"endpoint":"SECRET-CONFIG-VALUE"}}', 'CLEAR', None,
     ['theme', 'userSettings'], [], []),
    ('plugins_empty', b'{"plugins":{}}', 'CLEAR', None, ['plugins'], ['plugins'], []),
    ('plugins_entry', b'{"plugins":{"firebase":{"enabled":true}}}', 'FLAGGED', 'CUSTOMIZATION_KEYS', ['plugins'], ['plugins'], ['plugins']),
    ('mcp_servers_entry', b'{"mcpServers":{"local":{"command":"SECRET-CONFIG-VALUE"}}}', 'FLAGGED', 'CUSTOMIZATION_KEYS',
     ['mcpServers'], ['mcpServers'], ['mcpServers']),
    ('unparseable', b'{"plugins": ', 'FLAGGED', 'UNPARSEABLE', [], [], []),
    # Further edges.
    ('oversize', b'{"a":"' + b'x' * (256 * 1024) + b'"}', 'FLAGGED', 'OVER_SIZE_BOUND', [], [], []),
    ('top_level_array', b'[{"plugins":{}}]', 'FLAGGED', 'NOT_AN_OBJECT', [], [], []),
    ('duplicate_key', b'{"theme":"a","plugins":{},"plugins":{"x":1}}', 'FLAGGED', 'DUPLICATE_KEY', [], [], []),
    ('nested_under_plain_parent', b'{"chat":{"settings":[{"agentMode":"auto"}]}}', 'FLAGGED', 'CUSTOMIZATION_KEYS',
     ['chat'], ['agentMode'], ['agentMode']),
    ('key_true', b'{"enableAgents":true}', 'FLAGGED', 'CUSTOMIZATION_KEYS', ['enableAgents'], ['enableAgents'], ['enableAgents']),
    ('matching_keys_without_content', b'{"enableAgents":false,"hooks":null,"skillLimit":3,"mcp":"","agents":[],"Plugins":{}}', 'CLEAR', None,
     sorted(['enableAgents', 'hooks', 'skillLimit', 'mcp', 'agents', 'Plugins']), sorted(['enableAgents', 'hooks', 'skillLimit', 'mcp', 'agents', 'Plugins']), []),
    ('blank_string', b'{"skillPath":" "}', 'FLAGGED', 'CUSTOMIZATION_KEYS', ['skillPath'], ['skillPath'], ['skillPath']),
    ('nonfinite', b'{"limit":NaN}', 'FLAGGED', 'UNPARSEABLE', [], [], []),
    ('too_deep', b'{"a":' * 70 + b'1' + b'}' * 70, 'FLAGGED', 'TOO_DEEP', [], [], []),
    ('not_utf8', b'{"a":"\xff"}', 'FLAGGED', 'NOT_UTF8', [], [], []),
    # Choice: a leading UTF-8 BOM is stripped and the content is inspected like any other.
    ('bom_clear', b'\xef\xbb\xbf{"theme":"dark"}', 'CLEAR', None, ['theme'], [], []),
    ('bom_flagged', b'\xef\xbb\xbf{"hooks":{"x":1}}', 'FLAGGED', 'CUSTOMIZATION_KEYS', ['hooks'], ['hooks'], ['hooks']),
    ('unsafe_key_name', b'{"agent@example.com":"x"}', 'FLAGGED', 'CUSTOMIZATION_KEYS', ['OTHER'], ['OTHER'], ['OTHER']),
    # RG-3: background sidecars are a customization key too.
    ('sidecars_entry', b'{"sidecars":{"evil":{"enabled":true,"projectId":"p"}}}', 'FLAGGED', 'CUSTOMIZATION_KEYS',
     ['sidecars'], ['sidecars'], ['sidecars']),
    ('sidecars_empty', b'{"sidecars":{}}', 'CLEAR', None, ['sidecars'], ['sidecars'], []),
)


@pytest.mark.parametrize('case', DECLARED_CASES, ids=[case[0] for case in DECLARED_CASES])
def test_declared_user_configuration_inspection_table(case):
    """The Commander's rule: present-but-clear unless strict-JSON parsing fails or a customization key has content."""
    name, data, status, reason, top, matching, flagged = case
    record = m.inspect_declared_config(data)
    assert (record['status'], record['reason']) == (status, reason), name
    assert (record['top_level_keys'], record['matching_keys'], record['flagged_keys']) == (top, matching, flagged), name
    assert record['bytes'] == len(data)
    dumped = json.dumps(record)
    for value in ('SECRET', 'dark', 'auto', 'firebase', 'local', 'example.com', 'fontSize', 'enabled', 'evil', 'projectId'):
        assert value not in dumped, (name, value)
    assert m.DECLARED_CONFIG_MAXIMUM == 256 * 1024 and m.DECLARED_CONFIG_FRAGMENTS == ('plugin', 'mcp', 'hook', 'skill', 'agent', 'sidecar')


def test_sidecars_are_a_hooks_class_location(tmp_path):
    """RG-3: agy starts background sidecars from <config>/sidecars/: any entry there (or an enabled "sidecars" key) holds."""
    assert '.gemini/config/sidecars' in m.PROFILE_PATHS and '.gemini/config/sidecars' in m.HOOK_PATHS
    side = tmp_path / 'sidecar-profile'
    (side / '.gemini' / 'config' / 'sidecars' / 'evil').mkdir(parents=True)
    (side / '.gemini' / 'config' / 'sidecars' / 'evil' / 'sidecar.json').write_bytes(b'{"command":"cmd.exe"}')
    (side / '.gemini' / 'config' / 'config.json').write_bytes(b'{"sidecars":{"evil":{"enabled":true,"projectId":"p"}}}')
    rows = m.profile_inventory_rows(side)
    assert all(m.inventory_flags(rows)[key] for key in FLAG_KEYS), "the auditor's case holds"
    assert m.flagged_profile_configs([{'slot': 'slot1', 'paths': rows}]) == ['slot1:.gemini/config/config.json:sidecars']
    only_folder = tmp_path / 'folder-only'
    (only_folder / '.gemini' / 'config' / 'sidecars' / 'evil').mkdir(parents=True)
    flags = m.inventory_flags(m.profile_inventory_rows(only_folder))
    assert flags['hooks_present'] is True and flags['plugins_present'] is False, 'any entry in sidecars/ is a hooks-class hit'
    clear = tmp_path / 'clear'
    (clear / '.gemini' / 'config' / 'sidecars').mkdir(parents=True)
    (clear / '.gemini' / 'config' / 'config.json').write_bytes(b'{"sidecars":{}}')
    rows = m.profile_inventory_rows(clear)
    assert not any(m.inventory_flags(rows)[key] for key in FLAG_KEYS), 'an empty sidecars folder and "sidecars":{} stay clear'
    assert m.flagged_profile_configs([{'slot': 'slot1', 'paths': rows}]) == []


def test_run_log_scan_flags_only_the_true_fallback_phrases(tmp_path):
    """RG-2: only the log files a run created are read (bounded, never published); normal resolution lines are counted."""
    assert m.LOG_FALLBACK_PHRASES == ('is no longer available. Using', 'Restored session model', 'resolves to a different model',
                                      'Restoring model')
    assert m.LOG_BENIGN_PHRASES == ('Model resolved via default', 'not in local config, defaulting to CCPA')
    profile = tmp_path / 'CoChem422Worker1'
    log = profile / '.gemini' / 'antigravity-cli' / 'log'
    log.mkdir(parents=True)

    def changes(*names, other=()):
        return {'new_files': [{'path': LOG_DIR + name, 'size': 1, 'token_file': False} for name in names]
                + [{'path': path, 'size': 1, 'token_file': False} for path in other],
                'changed_files': [], 'removed_files': [], 'new_directories': []}
    none = m.scan_run_logs(profile, changes(other=('.gemini/antigravity-cli/brain/conv/summary.txt',)))
    assert none['log_scanned'] is False and none['fallback_found'] is False and none['files'] == [], 'no log: recorded, never a hold'
    assert none['fallback_phrases'] == dict.fromkeys(m.LOG_FALLBACK_PHRASES, 0) and none['benign_phrases'] == dict.fromkeys(m.LOG_BENIGN_PHRASES, 0)
    (log / 'cli-a.log').write_bytes(BENIGN_LOG * 300)
    benign = m.scan_run_logs(profile, changes('cli-a.log'))
    assert benign['log_scanned'] is True and benign['fallback_found'] is False
    assert benign['benign_phrases'] == {'Model resolved via default': 600, 'not in local config, defaulting to CCPA': 300}
    assert benign['files'] == [{'path': LOG_DIR + 'cli-a.log', 'bytes': len(BENIGN_LOG) * 300, 'sha256': hashlib.sha256(BENIGN_LOG * 300).hexdigest(),
                                'truncated': False}]
    for phrase in m.LOG_FALLBACK_PHRASES:
        (log / 'cli-b.log').write_bytes(BENIGN_LOG + b'INFO gemini-3.8-flash ' + phrase.encode() + b' gemini-3.8-flash-high\n')
        hit = m.scan_run_logs(profile, changes('cli-a.log', 'cli-b.log'))
        assert hit['fallback_found'] is True and hit['fallback_phrases'][phrase] == 1 and len(hit['files']) == 2, phrase
    (log / 'cli-old.log').write_bytes(FALLBACK_LOG)
    assert m.scan_run_logs(profile, changes('cli-a.log'))['fallback_found'] is False, 'a log the run did not create is not read'
    (log / 'cli-big.log').write_bytes(b'x' * (m.LOG_SCAN_MAXIMUM + 10) + b'Restoring model')
    big = m.scan_run_logs(profile, changes('cli-big.log'))
    assert big['files'][0]['truncated'] is True and big['files'][0]['bytes'] == m.LOG_SCAN_MAXIMUM and big['log_scanned'] is True
    dumped = json.dumps([none, benign, hit, big])
    assert 'SECRET' not in dumped and 'INFO' not in dumped and '2026-10-11' not in dumped, 'counts, sizes and digests only'
    # A flagged phrase in an accepted run's log clears reroute_scan_clean and holds G3 with a named reason.
    r1 = run_row('R1', classify(stream()))
    r1['log_scan'] = hit
    verdict = m.identity_verdict([r1], m.run_matrix(), 'gemini-3.8-flash-low')
    assert verdict['reroute_scan_clean'] is False and verdict['runs']['R1']['log_fallback_found'] is True
    assert m.isolation_gate('EVIDENCE_COMPLETE', {'passed': True, 'reasons': []}, [r1]) == {'passed': False, 'reasons': ['MODEL_FALLBACK_LOGGED']}
    r1['log_scan'] = benign
    assert m.identity_verdict([r1], m.run_matrix(), 'gemini-3.8-flash-low')['reroute_scan_clean'] is True
    assert m.isolation_gate('EVIDENCE_COMPLETE', {'passed': True, 'reasons': []}, [r1])['passed'] is True


def test_profile_inventory_inspects_the_declared_user_configurations(tmp_path):
    """Present-but-clear user configurations keep the six-profile flags clear; a flagged one names its file and keys."""
    assert m.PROFILE_PATHS[-3:] == m.DECLARED_CONFIG_PATHS == ('.gemini/config/config.json', '.gemini/config/skills.json',
                                                               '.gemini/config/plugins.json')
    profile = tmp_path / 'CoChem422Worker1'
    config = profile / '.gemini' / 'config'
    config.mkdir(parents=True)
    (config / 'config.json').write_bytes(b'{"chat":{"history":"SECRET-CONFIG-VALUE"},"userSettings":{"theme":"dark"},"plugins":{}}')
    (config / 'skills.json').write_bytes(b'{}')
    (config / 'plugins.json').write_bytes(b'{"plugins":[]}')
    rows = m.profile_inventory_rows(profile)
    by = {row['path']: row for row in rows}
    for relative in m.DECLARED_CONFIG_PATHS:
        row = by[relative]
        assert row['exists'] is True and row['kind'] == 'file', 'the file stays recorded as present'
        assert row['declared_config']['status'] == 'CLEAR' and row['declared_config']['sha256'] == row['sha256'], relative
    assert not any(m.inventory_flags(rows)[key] for key in FLAG_KEYS) and m.flagged_profile_configs([{'slot': 'slot1', 'paths': rows}]) == []
    assert 'SECRET' not in json.dumps(rows) and 'dark' not in json.dumps(rows)
    assert all('declared_config' not in row for row in rows if row['path'] not in m.DECLARED_CONFIG_PATHS)
    (config / 'config.json').write_bytes(b'{"mcpServers":{"x":{"command":"SECRET-CONFIG-VALUE"}},"plugins":{}}')
    (config / 'skills.json').write_bytes(b'[]')
    rows = m.profile_inventory_rows(profile)
    assert all(m.inventory_flags(rows)[key] for key in FLAG_KEYS)
    assert m.flagged_profile_configs([{'slot': 'slot1', 'paths': rows}]) == [
        'slot1:.gemini/config/config.json:mcpServers', 'slot1:.gemini/config/skills.json:NOT_AN_OBJECT']
    (config / 'config.json').write_bytes(b'{}')
    rows = m.profile_inventory_rows(profile)
    assert {key for key in FLAG_KEYS if m.inventory_flags(rows)[key]} == {'skills_present'}, 'skills.json maps to skills only'
    (config / 'skills.json').write_bytes(b'{}')
    os.link(config / 'plugins.json', tmp_path / 'hardlinked.json')
    rows = m.profile_inventory_rows(profile)
    assert m.flagged_profile_configs([{'slot': 'slot1', 'paths': rows}]) == ['slot1:.gemini/config/plugins.json:HARDLINKED']
    (tmp_path / 'hardlinked.json').unlink()
    other = tmp_path / 'CoChem422Worker2'
    (other / '.gemini' / 'config' / 'config.json').mkdir(parents=True)
    (other / '.gemini' / 'config' / 'config.json' / 'x').write_bytes(b'{}')
    assert m.flagged_profile_configs([{'slot': 'slot2', 'paths': m.profile_inventory_rows(other)}]) == ['slot2:.gemini/config/config.json:dir']
    # The gate names the file and its keys; workspace files stay 'present = flagged' whatever their content.
    good = run_row('R1', classify(stream()))
    rows = m.profile_inventory_rows(profile)
    (config / 'config.json').write_bytes(b'{"hooks":{"PreRun":[{"command":"x"}]}}')
    flagged_rows = m.profile_inventory_rows(profile)
    clean_ws = {'label': 'slot_root', 'flags': dict.fromkeys(FLAG_KEYS, False)}
    for paths, expected in ((rows, []), (flagged_rows, ['PROFILE_INVENTORY_NOT_CLEAR', 'PROFILE_CONFIG_FLAGGED:slot1:.gemini/config/config.json:hooks'])):
        profiles = [{'slot': 'slot1', 'flags': m.inventory_flags(paths), 'paths': paths}] + [{'flags': dict.fromkeys(FLAG_KEYS, False)}] * 5
        verdict = m.isolation_verdict([good], profiles, [clean_ws], {'clear': True})
        assert m.isolation_gate('EVIDENCE_COMPLETE', {'passed': True, 'reasons': []}, [good], verdict)['reasons'] == expected
        assert verdict['disables_hooks'] is (not expected) and verdict['disables_mcp'] is (not expected)
    workspace = tmp_path / 'ws' / 'slot1'
    (workspace / '.agents').mkdir(parents=True)
    (workspace / '.agents' / 'mcp_config.json').write_bytes(b'{}')
    assert m.workspace_inventory('slot_root', workspace)['flags']['mcp_present'] is True, 'an empty workspace mcp_config.json still counts'


def test_shadow_check_covers_alternative_folders_and_ancestors(tmp_path, monkeypatch):
    bounded_ancestors(monkeypatch, tmp_path)
    profile = tmp_path / 'p'
    profile.mkdir()
    slot = tmp_path / 'workers' / 'slot1'
    (slot / '.agent' / 'agents' / 'cochem-inference-only').mkdir(parents=True)
    ram = tmp_path / 'R' / 'CoChem427-windows-20261007' / 'slot1'
    (tmp_path / 'R' / '_agent').mkdir(parents=True)
    (tmp_path / 'R' / '_agent' / 'cochem-inference-only.agent.md').write_bytes(b'x')
    checked, found = m.shadow_check(profile, (('slot_root', slot), ('ram_workspace', ram)))
    assert sorted(item['path'] for item in found) == sorted([str(slot / '.agent' / 'agents' / 'cochem-inference-only'),
                                                             str(tmp_path / 'R' / '_agent' / 'cochem-inference-only.agent.md')])
    assert str(tmp_path / 'workers' / '_agents' / 'agents') in checked and str(ram / '_agent') in checked


def test_job_process_accounting_reads_the_owned_job_after_termination():
    from cochem_pipeline import windows as real
    calls = []

    def query(job, information_class, buffer, size, returned):
        calls.append(('query', job, information_class, size))
        buffer._obj.TotalProcesses, buffer._obj.ActiveProcesses, buffer._obj.TotalTerminatedProcesses = 3, 0, 3
        return 1
    win = SimpleNamespace(_BASIC_ACCOUNTING=real._BASIC_ACCOUNTING, _check=lambda value, *a: value,
                          _api=lambda: {'kernel32': SimpleNamespace(QueryInformationJobObject=query)})
    process = SimpleNamespace(_job=77, terminate=lambda: calls.append('terminate'))
    value = m.job_process_accounting(win, process)
    assert calls == ['terminate', ('query', 77, 1, C.sizeof(real._BASIC_ACCOUNTING))], 'TerminateJobObject first, so the count is final'
    assert (value['total_processes'], value['active_processes'], value['expected_maximum'], value['queried_after_job_termination']) == (3, 0, 2, True)
    record = classify(stream())
    record['job_accounting'] = value
    checks = m.run_checks(record, 'gemini-3.8-flash-high')
    assert checks['job_processes_within_tree'] is False and checks['isolation_breach'] is True and m.JOB_EXPECTED_PROCESSES_MAXIMUM == 2


# ---------------------------------------------------------------- O-F2: C:\ProgramData\Antigravity

def test_programdata_sddl_grants_users_read_and_execute_only():
    assert m.PROGRAMDATA_ANTIGRAVITY == Path(r'C:\ProgramData\Antigravity')
    assert m.PROGRAMDATA_ANTIGRAVITY_SDDL == 'O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)'
    owner, protected, rules = parse_sddl(m.PROGRAMDATA_ANTIGRAVITY_SDDL)
    assert owner == 'S-1-5-18' and protected is True
    assert sorted(rules) == sorted([('S-1-5-18', 0x1F01FF, 3), ('S-1-5-32-544', 0x1F01FF, 3), ('S-1-5-32-545', 0x1200A9, 3)])
    users = dict((sid, mask) for sid, mask, _ in rules)['S-1-5-32-545']
    # FILE_ADD_FILE, FILE_ADD_SUBDIRECTORY, FILE_WRITE_EA, FILE_DELETE_CHILD, FILE_WRITE_ATTRIBUTES, DELETE, WRITE_DAC, WRITE_OWNER, GENERIC_*.
    assert users & (0x2 | 0x4 | 0x10 | 0x40 | 0x100 | 0x10000 | 0x40000 | 0x80000 | 0x10000000 | 0x40000000) == 0
    assert users & 0x1 and users & 0x20, 'list and traverse: agy can see that admin_settings.json is absent'
    from cochem_pipeline import windows as win
    for sddl in (m.PROGRAMDATA_ANTIGRAVITY_SDDL, m.AGENT_PARENT_DIRECTORY_SDDL.format(sid='S-1-5-21-1-2-3-1001'),
                 m.AGENT_DIRECTORY_SDDL.format(sid='S-1-5-21-1-2-3-1001'), m.AGENT_FILE_SDDL.format(sid='S-1-5-21-1-2-3-1001')):
        descriptor = win.HANDLE()
        assert win._api()['advapi32'].ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, C.byref(descriptor), None), sddl
        win._api()['kernel32'].LocalFree(descriptor)


def test_programdata_state_table(tmp_path, monkeypatch):
    from cochem_pipeline import windows as win
    acl = FakeAcl()
    monkeypatch.setattr(win, '_acl', acl.read)
    path = tmp_path / 'Antigravity'

    def state():
        return m.programdata_antigravity_state(win, path)
    assert state() == {'path': str(path), 'exists': False, 'state': 'ABSENT', 'entry_count': 0, 'entries': [], 'acl': None, 'clear': True}
    path.mkdir()
    assert (state()['state'], state()['clear']) == ('WEAK_ACL', False), 'an inherited ProgramData ACL lets Users create files'
    acl.store[str(path)] = parse_sddl(m.PROGRAMDATA_ANTIGRAVITY_SDDL)
    value = state()
    assert (value['state'], value['clear'], value['acl']['owner'], value['acl']['protected']) == ('PROTECTED_EMPTY', True, 'S-1-5-18', True)
    for weaker in ('O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1301bf;;;BU)', 'O:SYG:SYD:(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)',
                   'O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)',
                   'O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)(A;OICI;FA;;;S-1-5-21-9)'):
        acl.store[str(path)] = parse_sddl(weaker)
        assert state()['state'] == 'WEAK_ACL', weaker
    acl.store[str(path)] = parse_sddl(m.PROGRAMDATA_ANTIGRAVITY_SDDL)
    (path / 'admin_settings.json').write_bytes(b'{}')
    value = state()
    assert (value['state'], value['clear'], value['entry_count'], value['entries']) == ('NOT_EMPTY', False, 1, ['admin_settings.json'])
    other = tmp_path / 'AntigravityFile'
    other.write_bytes(b'x')
    assert m.programdata_antigravity_state(win, other)['state'] == 'NOT_DIRECTORY'
    empty = tmp_path / 'AntigravityEmpty'
    empty.mkdir()

    def broken(_):
        raise win.WindowsIsolationError('Unexpected ACL entry')
    monkeypatch.setattr(win, '_acl', broken)
    assert m.programdata_antigravity_state(win, empty)['state'] == 'ACL_UNVERIFIABLE'
    assert set(m.PROGRAMDATA_CLEAR_STATES) == {'ABSENT', 'PROTECTED_EMPTY'}


def test_protect_programdata_creates_once_and_never_changes_an_existing_folder(tmp_path, monkeypatch):
    from cochem_pipeline import windows as win
    acl, created = FakeAcl(), []
    monkeypatch.setattr(win, '_acl', acl.read)
    monkeypatch.setattr(m, 'apply_sddl', acl.apply)
    monkeypatch.setattr(m, 'create_protected_directory', lambda win_, path, sddl: (created.append((str(path), sddl)), Path(path).mkdir(),
                                                                                   acl.apply(win_, path, sddl)))
    path = tmp_path / 'ProgramData' / 'Antigravity'
    path.parent.mkdir()
    record = m.protect_programdata_antigravity(win, path)
    assert created == [(str(path), m.PROGRAMDATA_ANTIGRAVITY_SDDL)] and record['created'] is True and record['clear'] is True
    assert (record['before']['state'], record['state'], record['current']['state']) == ('ABSENT', 'PROTECTED_EMPTY', 'PROTECTED_EMPTY')
    again = m.protect_programdata_antigravity(win, path)
    assert again['created'] is False and again['state'] == 'PROTECTED_EMPTY' and again['clear'] is True and len(created) == 1
    (path / 'admin_settings.json').write_bytes(b'{"gateway":"x"}')
    applied = len(acl.applied)
    refused = m.protect_programdata_antigravity(win, path)
    assert (refused['state'], refused['clear'], refused['created']) == ('NOT_EMPTY', False, False)
    assert len(acl.applied) == applied and (path / 'admin_settings.json').read_bytes() == b'{"gateway":"x"}', 'nothing existing is changed'
    weak = tmp_path / 'Other' / 'Antigravity'
    weak.mkdir(parents=True)
    assert m.protect_programdata_antigravity(win, weak)['state'] == 'WEAK_ACL' and len(acl.applied) == applied


# ---------------------------------------------------------------- O-F3: the parent folders of the staged agent

def test_stage_agent_protects_the_parent_folders_in_stage_mode(tmp_path, monkeypatch):
    acl = FakeAcl()
    from cochem_pipeline import windows as win
    monkeypatch.setattr(m, 'apply_sddl', acl.apply)
    monkeypatch.setattr(win, '_acl', acl.read)
    profile = tmp_path / 'CoChem422Worker2'
    (profile / '.gemini' / 'agents').mkdir(parents=True)  # pre-existing parent with the inherited worker full control
    sid = 'S-1-5-21-1-2-3-1002'
    parent = f'O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;{sid})'
    leaf, file_sddl = parent, f'O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;0x120089;;;{sid})'
    records = m.stage_agent(win, AGENT, profile, sid, protect_parents=True)
    assert [(Path(path).relative_to(profile).as_posix(), sddl) for path, sddl in acl.applied] == [
        ('.gemini/agents', parent), ('.gemini/agents/cochem-inference-only', leaf), ('.gemini/agents/cochem-inference-only/agent.md', file_sddl),
        ('.gemini/config/agents', parent), ('.gemini/config/agents/cochem-inference-only', leaf),
        ('.gemini/config/agents/cochem-inference-only/agent.md', file_sddl)], 'each parent is protected before its leaf is created'
    assert [(r['parent_relative'], r['parent_path'], r['parent_acl_applied'], r['parent_acl_verified'], r['parent_acl_sddl']) for r in records] == [
        ('.gemini/agents', str(profile / '.gemini' / 'agents'), True, True, parent),
        ('.gemini/config/agents', str(profile / '.gemini' / 'config' / 'agents'), True, True, parent)]
    assert m.AGENT_PARENT_RELATIVES == ('.gemini/agents', '.gemini/config/agents')
    again = m.stage_agent(win, AGENT, profile, sid, protect_parents=True)
    assert [r['parent_acl_applied'] for r in again] == [False, False] and len(acl.applied) == 6, 'a protected parent is reused'
    assert m.verify_staged_agent(win, records, sid) == [m.AGENT_SHA256] * 2
    # A renamed-and-replaced tree carries inherited ACLs: the parent or the leaf folder check refuses the launch.
    for path in (profile / '.gemini' / 'agents', profile / '.gemini' / 'config' / 'agents' / 'cochem-inference-only'):
        saved = acl.store.pop(str(path))
        with pytest.raises(ValueError, match='ACL'):
            m.verify_staged_agent(win, records, sid)
        acl.store[str(path)] = saved
    other = tmp_path / 'CoChem422Worker1'
    other.mkdir()
    evidence = m.stage_agent(win, AGENT, other, sid)
    assert all('parent_path' not in record for record in evidence), 'the evidence mode leaves the parents to the stage mode'


def current_user_sid():
    from cochem_pipeline import windows as win
    api = win._api()
    token = win.HANDLE()
    assert api['advapi32'].OpenProcessToken(api['kernel32'].GetCurrentProcess(), 0x8, C.byref(token))
    try:
        user = win._SID_AND_ATTRIBUTES.from_buffer(win._token_info(token, 1))
        return win._sid_text(user.Sid)
    finally:
        win._close(token)


def set_dacl(path, dacl, protected):
    from cochem_pipeline import windows as win
    api = win._api()
    descriptor = win.HANDLE()
    assert api['advapi32'].ConvertStringSecurityDescriptorToSecurityDescriptorW(dacl, 1, C.byref(descriptor), None), C.get_last_error()
    try:
        # DACL_SECURITY_INFORMATION with PROTECTED_ or UNPROTECTED_DACL_SECURITY_INFORMATION; the owner stays the current user.
        assert api['advapi32'].SetFileSecurityW(str(path), (0x80000004 if protected else 0x20000004), descriptor), C.get_last_error()
    finally:
        api['kernel32'].LocalFree(descriptor)


def test_protected_parent_refuses_the_auditor_rename_and_replace_case(tmp_path):
    """acl_parent_rename_repro.ps1 on tmp folders, with the current (non-elevated) user standing in for the worker: the reviewed
    leaf/file DACLs alone still allow renaming the leaf through the parent's delete-child; the O-F3 parent DACL refuses it."""
    if os.name != 'nt':
        pytest.skip('Windows ACL semantics')
    if C.windll.shell32.IsUserAnAdmin():
        pytest.skip('an elevated token holds BUILTIN\\Administrators full control, which may rename by design')
    me = current_user_sid()

    def dacl(template):
        return 'D:' + template.format(sid=me).split('D:', 1)[1]
    results = {}
    for case, protect in (('auditor', False), ('fixed', True)):
        parent = tmp_path / case / 'agents'
        leaf = parent / 'cochem-inference-only'
        leaf.mkdir(parents=True)
        (leaf / 'agent.md').write_bytes(AGENT.read_bytes())
        touched = [leaf / 'agent.md', leaf] + ([parent] if protect else [])
        try:
            set_dacl(leaf / 'agent.md', dacl(m.AGENT_FILE_SDDL), True)
            set_dacl(leaf, dacl(m.AGENT_DIRECTORY_SDDL), True)
            if protect:
                set_dacl(parent, dacl(m.AGENT_PARENT_DIRECTORY_SDDL), True)
            outcome = {}
            for name, action in (('write_agent_file', lambda: (leaf / 'agent.md').open('ab').close()),
                                 ('create_in_leaf', lambda: (leaf / 'other.md').write_bytes(b'x')),
                                 ('plant_sibling', lambda: (parent / 'planted').mkdir()),
                                 ('rename_leaf', lambda: os.rename(leaf, parent / 'moved-aside'))):
                try:
                    action()
                    outcome[name] = 'ALLOWED'
                except PermissionError:
                    outcome[name] = 'DENIED'
            results[case] = outcome
            if outcome['rename_leaf'] == 'ALLOWED':
                os.rename(parent / 'moved-aside', leaf)
        finally:
            for path in touched:
                set_dacl(path, f'D:(A;;FA;;;{me})' if path.name == 'agent.md' else f'D:(A;OICI;FA;;;{me})', False)
    assert results['auditor'] == {'write_agent_file': 'DENIED', 'create_in_leaf': 'DENIED', 'plant_sibling': 'ALLOWED', 'rename_leaf': 'ALLOWED'}
    assert results['fixed'] == {'write_agent_file': 'DENIED', 'create_in_leaf': 'DENIED', 'plant_sibling': 'DENIED', 'rename_leaf': 'DENIED'}


# ---------------------------------------------------------------- end-to-end helper runs

def test_full_evidence_run_passes_with_r5_and_replay_streams(produced):
    run = produced['pass']
    receipt = run.receipt
    assert run.code == 0 and receipt['status'] == 'EVIDENCE_COMPLETE' and receipt['gate'] == {'passed': True, 'reasons': []}
    assert receipt['schema'] == 'cochem-agy-isolation-evidence/1' and receipt['mode'] == 'evidence' and receipt['gemini_gate'] == 'G3'
    assert receipt['effort_null_slug'] == 'gemini-3.8-flash-low' and [r['id'] for r in receipt['runs']] == ['R1', 'R5', 'R2', 'R3', 'R4']
    assert [item.argv[1:] for item in run.launched] == [list(a) for _, a, _ in m.PRECHECK] + [
        list(run_args(model, extra)) for _, model, extra, _ in m.run_matrix('gemini-3.8-flash-low')]
    assert all(item.identity == 'CoChem422Worker1' and item.cwd == str(run.world.workers / 'slot1') for item in run.launched)
    assert run.stops == ['require_stopped'] * (1 + 9 + 1), 'before, at every launch boundary, after'
    assert run.stdin[:4] == [b''] * 4 and run.stdin[4:] == [m.PROMPT_LINE] * 5
    assert receipt['model_jobs_executed'] == 5 and receipt['answers_produced'] == 3
    iv = receipt['identity_verdict']
    assert iv['effort_null'] == {'slug': 'gemini-3.8-flash-low', 'run_id': 'R5', 'executed': True, 'passed': True, 'init_model': 'gemini-3.8-flash-low'}
    assert iv['slug_form_passes_contract'] and not iv['slug_with_effort_accepted'] and iv['family_with_effort_passes_with_echo']
    assert iv['family_with_effort_init_model'] == 'gemini-3.8-flash-high' and iv['unknown_model_rejected'] and iv['reroute_scan_clean']
    v = receipt['isolation_verdict']
    assert all(v[k] is True for k in ('disables_tools', 'disables_mcp', 'disables_hooks', 'disables_subagents', 'tools_empty', 'hooks_absent'))
    assert v['model_fallback_basis'] == 'UNKNOWN'
    assert receipt['agent']['verified_before_each_launch'] and len(receipt['agent']['staged']) == 2 and receipt['agent']['shadows_found'] == []
    assert receipt['environment_attestation']['flagged_names'] == [] and receipt['environment_attestation']['profile_binding_verified']
    assert receipt['runs'][0]['profile_changes']['new_files'] == [{'path': '.gemini/antigravity-cli/brain/conv-r1/summary.txt', 'size': 10, 'token_file': False}]
    assert sorted(receipt['replay_streams']) == ['R1', 'R2', 'R3', 'R4', 'R5']
    for run_id, entry in receipt['replay_streams'].items():
        assert entry['available'] is True and entry['requested_model'] == next(r['requested_model'] for r in receipt['runs'] if r['id'] == run_id)
        for stream_name in ('stdout', 'stderr'):
            data = (run.root / entry[stream_name]['path']).read_bytes()
            assert hashlib.sha256(data).hexdigest() == entry[stream_name]['sha256'] and m.sensitive_scan(data) == []
            for secret in SECRETS:
                assert secret.encode() not in data, (run_id, stream_name, secret)
    assert (run.root / 'replay' / 'R1.stdout').read_bytes() == (run.root / 'raw' / 'R1.stdout').read_bytes()
    assert EMAIL.encode() in (run.root / 'raw' / 'R1.stderr').read_bytes(), 'the raw capture stays private and complete'
    assert receipt['raw_sensitive_patterns_found'] == ['email', 'google_access_token', 'google_refresh_token', 'url']
    assert receipt['runs'][1]['replay']['stderr']['redactions'] == {'url': 1, 'google_access_token': 1, 'google_refresh_token': 1}
    assert receipt['raw_output_publication'] == 'never' and receipt['token_files_opened'] == 0 and receipt['login_inputs_written'] == 0
    for secret in SECRETS:
        assert secret not in run.receipt_text, secret
    assert len(run.receipt_text.encode()) <= m.RECEIPT_MAX_BYTES and receipt['helper_sha256'] == hashlib.sha256(PY.read_bytes()).hexdigest()


def test_effort_null_parameter_drives_r5(produced):
    receipt = produced['medium'].receipt
    assert receipt['gate']['passed'] and receipt['runs'][1]['requested_model'] == 'gemini-3.8-flash-medium'
    assert receipt['identity_verdict']['effort_null'] == {'slug': 'gemini-3.8-flash-medium', 'run_id': 'R5', 'executed': True,
                                                          'passed': True, 'init_model': 'gemini-3.8-flash-medium'}
    mismatch = produced['r5_mismatch'].receipt
    assert mismatch['gate']['passed'] is True, 'R5 decides the binding only; it does not hold G3'
    assert mismatch['identity_verdict']['effort_null']['passed'] is False
    assert mismatch['identity_verdict']['effort_null']['init_model'] == 'gemini-3.8-flash-high'


def test_full_run_failure_modes_degrade_to_held_records(produced):
    tools = produced['tools']
    assert tools.code == 0 and tools.receipt['status'] == 'EVIDENCE_COMPLETE'
    assert tools.receipt['gate'] == {'passed': False, 'reasons': ['R1_TOOLS_NOT_EMPTY']}
    assert tools.receipt['runs_skipped'] == [{'id': i, 'reason': 'ISOLATION_BREACH_STOP'} for i in ('R5', 'R2', 'R3', 'R4')]
    assert tools.receipt['model_jobs_executed'] == 1 and tools.receipt['isolation_verdict']['disables_tools'] is False
    marker = produced['marker'].receipt
    assert marker['gate'] == {'passed': False, 'reasons': ['R1_STDERR_MARKERS']} and marker['identity_verdict']['reroute_scan_clean'] is False
    pre = produced['precheck']
    assert pre.code == 0 and pre.receipt['status'] == 'EVIDENCE_PRECHECK_REFUSED' and pre.receipt['model_jobs_executed'] == 0
    assert pre.receipt['gate'] == {'passed': False, 'reasons': ['AGENTS_PRECHECK_FAILED']} and len(pre.launched) == 4
    assert pre.receipt['runs_skipped'] == [{'id': i, 'reason': 'PRECHECK_REFUSED'} for i in m.RUN_IDS] and pre.receipt['replay_streams'] == {}
    failed = produced['failed']
    assert failed.code == 2 and failed.receipt['status'] == 'EVIDENCE_FAILED' and failed.receipt['failure_kind'] == 'verification_failed'
    assert failed.receipt['failure'] == {'phase': 'agent_verification', 'error_type': 'ValueError', 'winerror': None}
    assert [p['id'] for p in failed.receipt['precheck']['probes']] == ['PC1', 'PC2'] and failed.receipt['runs'] == []
    assert failed.receipt['gate'] == {'passed': False, 'reasons': ['EVIDENCE_NOT_COMPLETE']} and failed.receipt['operator_review_required']
    inventory = produced['inventory'].receipt
    assert inventory['status'] == 'EVIDENCE_COMPLETE' and inventory['gate'] == {'passed': False, 'reasons': ['PROFILE_INVENTORY_NOT_CLEAR']}
    assert inventory['isolation_verdict']['mcp_absent'] is False and inventory['isolation_verdict']['disables_mcp'] is False
    assert inventory['profiles'][2]['flags']['mcp_present'] is True and inventory['identity_verdict']['slug_form_passes_contract'] is True
    late = produced['deadline']
    assert late.code == 2 and late.receipt['status'] == 'EVIDENCE_INCOMPLETE'
    assert [r['id'] for r in late.receipt['runs']] == ['R1'] and late.receipt['runs'][0]['outcome'] == 'timed_out_terminated'
    assert late.receipt['runs_skipped'] == [{'id': i, 'reason': 'DEADLINE'} for i in ('R5', 'R2', 'R3', 'R4')]
    assert late.receipt['require_stopped_after'] is True and late.launched[4].process.closed


def test_stage_mode_stages_six_profiles_and_passes_the_listing_gate(produced):
    run = produced['stage']
    receipt = run.receipt
    assert run.code == 0 and receipt['status'] == 'STAGING_COMPLETE' and receipt['schema'] == 'cochem-agy-agent-staging/1'
    assert receipt['gate']['passed'] is True and receipt['gate']['reasons'] == [] and receipt['gemini_gate'] == 'G4'
    assert [e['slot'] for e in receipt['slots']] == SLOTS and receipt['model_jobs_executed'] == 0
    assert [(item.identity, item.argv[1:]) for item in run.launched] == [(i, list(a)) for i in IDENTITIES for _, a, _ in m.STAGE_PROBES]
    assert all(item.cwd == str(run.world.workers / f'slot{n}') for n in range(1, 7) for item in run.launched if item.identity.endswith(str(n)))
    assert run.stdin == [b''] * 12
    sids = {row['identity']: row['sid'] for row in run.world.layout['slots'].values()}
    applied = {path: sddl for path, sddl in run.acl.applied}
    for entry, identity in zip(receipt['slots'], IDENTITIES):
        profile = run.world.users / identity
        for record in entry['staged']:
            assert (profile / record['relative']).read_bytes() == AGENT.read_bytes()
            assert record['file_acl_sddl'] == f'O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;0x120089;;;{sids[identity]})'
            assert applied[record['path']] == record['file_acl_sddl'] or (identity == 'CoChem422Worker1' and record['preexisting'])
        assert entry['listing'] == {'passed': True, 'reasons': []} and entry['agent_sha256_after_listing'] == [m.AGENT_SHA256] * 2
        assert [p['raw_path']['stdout'] for p in entry['probes']] == [f'raw/{entry["slot"]}-PC3.stdout', f'raw/{entry["slot"]}-PC4.stdout']
    assert [r['preexisting'] for r in receipt['slots'][0]['staged']] == [True, True], 'slot1 staged by the evidence run is reused'
    assert receipt['isolation_inventory_clear'] is True and len(receipt['profiles']) == 6
    for secret in SECRETS:
        assert secret not in run.receipt_text


def test_stage_listing_gate_fails_for_one_slot_missing_the_agent(produced):
    receipt = produced['stage_missing'].receipt
    assert produced['stage_missing'].code == 0 and receipt['status'] == 'STAGING_COMPLETE'
    assert receipt['gate']['passed'] is False
    assert receipt['gate']['reasons'] == ['slot4:AGENTS_JSON_LISTING_FAILED', 'slot4:AGENTS_TEXT_LISTING_FAILED']
    assert receipt['gate']['slots']['slot4'] == {'passed': False, 'reasons': ['AGENTS_JSON_LISTING_FAILED', 'AGENTS_TEXT_LISTING_FAILED']}
    assert all(receipt['gate']['slots'][s]['passed'] for s in SLOTS if s != 'slot4')
    shadow = produced['stage_shadow'].receipt
    assert shadow['gate']['reasons'] == ['slot2:AGENT_SHADOW_FOUND']
    conflict = produced['stage_conflict']
    assert conflict.code == 2 and conflict.receipt['status'] == 'STAGING_FAILED' and conflict.receipt['failure_slot'] == 'slot3'
    assert conflict.receipt['failure']['phase'] == 'agent_staging' and conflict.receipt['gate']['reasons'] == ['STAGING_NOT_COMPLETE']
    assert (conflict.world.users / 'CoChem422Worker3' / '.gemini' / 'agents' / 'cochem-inference-only' / 'agent.md').read_bytes() == b'other\n'


def load_builder():
    path = ROOT / 'build-pipeline-config-r5-candidate.py'
    if not path.exists():
        pytest.skip('the r5 config builder is not in this workspace')
    spec = importlib.util.spec_from_file_location('config_builder_for_isolation_tests', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deadline_after_a_passing_r1_keeps_the_evidence_complete(produced):
    """O-F4: the deadline guard skipped R5, R2, R3 and R4 after R1 passed: complete, gate on R1, skipped runs unbound."""
    run = produced['deadline_after_r1']
    r = run.receipt
    assert run.code == 0 and r['status'] == 'EVIDENCE_COMPLETE' and r['gate'] == {'passed': True, 'reasons': []}
    assert [x['id'] for x in r['runs']] == ['R1'] and r['runs'][0]['checks']['passes_contract'] and r['runs'][0]['elapsed_ms'] >= 99000
    assert r['runs_skipped'] == [{'id': i, 'reason': 'DEADLINE'} for i in ('R5', 'R2', 'R3', 'R4')]
    assert r['model_jobs_executed'] == 1 and r['answers_produced'] == 1 and sorted(r['replay_streams']) == ['R1']
    iv = r['identity_verdict']
    assert iv['effort_null'] == {'slug': 'gemini-3.8-flash-low', 'run_id': 'R5', 'executed': False, 'passed': False, 'init_model': None}
    for run_id, model, extra, _ in m.run_matrix('gemini-3.8-flash-low')[1:]:
        assert iv['runs'][run_id] == {'executed': False, 'requested_model': model, 'extra_arguments': list(extra), 'accepted': False,
                                      'passes_contract': False, 'passes_with_echo': False, 'skipped_reason': 'DEADLINE'}, run_id
    assert iv['slug_form_passes_contract'] and iv['reroute_scan_clean'] and not iv['slug_with_effort_accepted'] and not iv['unknown_model_rejected']
    assert all(r['isolation_verdict'][key] is True for key in ('disables_tools', 'disables_mcp', 'disables_hooks', 'disables_subagents'))
    builder = load_builder()
    selection = builder.select_bindings(r, 'reference')
    assert selection.rules[builder.FLASH]['rule'] == builder.RULE_R1 and selection.bindings == {builder.FLASH: 'gemini-3.8-flash-high'}
    assert selection.rules[builder.FLASH_EXTENDED]['rule'] == builder.RULE_UNBOUND_EXTENDED and selection.contracts == {}
    # An R1 that did not pass keeps the old rule: the deadline skip leaves the evidence incomplete.
    late = produced['deadline'].receipt
    assert late['status'] == 'EVIDENCE_INCOMPLETE' and late['gate'] == {'passed': False, 'reasons': ['EVIDENCE_NOT_COMPLETE']}


def test_a_process_beyond_agys_own_tree_fails_g3(produced):
    """O-F1: the owned Job's TotalProcesses above agy.exe + its console host is a named G3 failure and an isolation stop."""
    r1 = produced['r1_extra_process'].receipt
    assert r1['status'] == 'EVIDENCE_COMPLETE' and r1['gate'] == {'passed': False, 'reasons': ['JOB_PROCESSES_BEYOND_AGY_TREE']}
    assert r1['runs'][0]['job_accounting']['total_processes'] == 3 and r1['runs'][0]['checks']['isolation_breach'] is True
    assert r1['runs_skipped'] == [{'id': i, 'reason': 'ISOLATION_BREACH_STOP'} for i in ('R5', 'R2', 'R3', 'R4')]
    v = r1['isolation_verdict']
    assert v['process_accounting_clean'] is False and v['disables_hooks'] is False and v['disables_mcp'] is False and v['disables_tools'] is True
    r2 = produced['r2_extra_process'].receipt
    assert r2['gate'] == {'passed': False, 'reasons': ['ISOLATION_BREACH_IN_MATRIX', 'JOB_PROCESSES_BEYOND_AGY_TREE']}
    assert [x['id'] for x in r2['runs']] == ['R1', 'R5', 'R2'] and r2['runs_skipped'] == [{'id': i, 'reason': 'ISOLATION_BREACH_STOP'} for i in ('R3', 'R4')]
    passing = produced['pass'].receipt
    assert all(item['job_accounting']['total_processes'] == 2 for item in passing['precheck']['probes'] + passing['runs'])
    assert passing['isolation_verdict']['process_accounting_clean'] is True and passing['job_expected_processes_maximum'] == 2


def test_extended_inventory_holds_g3(produced):
    """O-F1: an alternative workspace folder above the (not yet existing) RAM root, and a profile config.json, each hold G3."""
    chain = produced['workspace_chain']
    r = chain.receipt
    assert r['gate'] == {'passed': False, 'reasons': ['PROFILE_INVENTORY_NOT_CLEAR']} and r['isolation_verdict']['disables_mcp'] is False
    ram = next(w for w in r['workspaces'] if w['label'] == 'ram_workspace')
    assert ram['root'] == str(chain.world.ram / 'slot1') and ram['root_present'] is False and ram['flags']['mcp_present'] is True
    assert [a['directory'] for a in ram['ancestors']] == [str(chain.world.ram), str(chain.world.base / 'R'), str(chain.world.base)]
    slot = next(w for w in r['workspaces'] if w['label'] == 'slot_root')
    assert [a['directory'] for a in slot['ancestors']] == [str(chain.world.workers), str(chain.world.base)]
    profile = produced['profile_config']
    assert profile.receipt['gate'] == {'passed': False, 'reasons': [
        'PROFILE_INVENTORY_NOT_CLEAR', 'PROFILE_CONFIG_FLAGGED:slot5:.gemini/config/config.json:mcpServers,plugins']}
    assert profile.receipt['profiles'][4]['flags']['plugins_present'] is True and profile.receipt['isolation_verdict']['plugins_absent'] is False
    assert profile.receipt['isolation_verdict']['profile_configs_flagged'] == ['slot5:.gemini/config/config.json:mcpServers,plugins']
    row = next(row for row in profile.receipt['profiles'][4]['paths'] if row['path'] == '.gemini/config/config.json')
    assert row['declared_config']['flagged_keys'] == ['mcpServers', 'plugins'] and row['declared_config']['status'] == 'FLAGGED'
    clear = produced['profile_config_clear']
    assert clear.code == 0 and clear.receipt['gate'] == {'passed': True, 'reasons': []}, 'present-but-clear configurations do not hold G3'
    assert all(clear.receipt['isolation_verdict'][key] is True for key in ('disables_hooks', 'disables_mcp', 'plugins_absent', 'skills_absent'))
    assert clear.receipt['isolation_verdict']['profile_configs_flagged'] == []
    rows = {row['path']: row for row in clear.receipt['profiles'][4]['paths']}
    assert [(rows[p]['exists'], rows[p]['declared_config']['status']) for p in m.DECLARED_CONFIG_PATHS] == [(True, 'CLEAR')] * 3
    assert rows['.gemini/config/config.json']['declared_config']['top_level_keys'] == ['chat', 'enableAgents', 'plugins', 'sidecars', 'userSettings']
    for run in (profile, clear):
        assert 'SECRET' not in run.receipt_text and 'history' not in run.receipt_text and '"dark"' not in run.receipt_text, 'key names only'
    clean = produced['pass'].receipt
    assert all(not any(w['flags'].values()) for w in clean['workspaces']) and len(clean['workspaces'][0]['paths']) == 18


def test_sidecars_and_run_logs_end_to_end(produced):
    """RG-3: the auditor's sidecar case holds G3. RG-2: only a true fallback phrase in a run's own cli-*.log holds G3."""
    side = produced['profile_sidecar'].receipt
    assert side['gate'] == {'passed': False, 'reasons': ['PROFILE_INVENTORY_NOT_CLEAR', 'PROFILE_CONFIG_FLAGGED:slot3:.gemini/config/config.json:sidecars']}
    assert side['profiles'][2]['flags']['hooks_present'] is True and side['isolation_verdict']['disables_hooks'] is False
    clear = produced['profile_config_clear'].receipt
    sidecars = next(row for row in clear['profiles'][4]['paths'] if row['path'] == '.gemini/config/sidecars')
    assert sidecars['exists'] is True and sidecars['entry_count'] == 0 and clear['gate']['passed'] is True, 'an empty sidecars folder is clear'
    benign = produced['log_benign'].receipt
    assert benign['gate'] == {'passed': True, 'reasons': []} and benign['identity_verdict']['reroute_scan_clean'] is True
    scan = benign['runs'][0]['log_scan']
    assert scan['log_scanned'] is True and scan['fallback_found'] is False and [f['path'] for f in scan['files']] == [LOG_DIR + 'cli-r1.log']
    assert scan['benign_phrases'] == {'Model resolved via default': 2, 'not in local config, defaulting to CCPA': 1}
    assert all(run['log_scan']['log_scanned'] is False for run in benign['runs'][1:]), 'runs without a new log are recorded, not held'
    fallback = produced['log_fallback'].receipt
    assert fallback['status'] == 'EVIDENCE_COMPLETE' and fallback['gate'] == {'passed': False, 'reasons': ['MODEL_FALLBACK_LOGGED']}
    assert fallback['identity_verdict']['reroute_scan_clean'] is False and fallback['identity_verdict']['runs']['R5']['log_fallback_found'] is True
    assert fallback['runs'][1]['log_scan']['fallback_phrases']['Restoring model'] == 1
    assert produced['pass'].receipt['runs'][0]['log_scan']['log_scanned'] is False
    for run in (produced['log_benign'], produced['log_fallback']):
        assert 'SECRET' not in run.receipt_text and 'INFO' not in run.receipt_text, 'the log text is never copied into the receipt'


def test_programdata_antigravity_holds_g3_unless_absent_or_protected_empty(produced):
    """O-F2 (G3): read-only before and after the runs; never created by the evidence mode."""
    clean = produced['pass']
    assert clean.receipt['programdata_antigravity']['before']['state'] == 'ABSENT' and clean.receipt['programdata_antigravity']['clear'] is True
    assert not clean.world.programdata.exists(), 'the evidence mode never creates the folder'
    present = produced['programdata_present'].receipt
    assert present['gate'] == {'passed': False, 'reasons': ['PROGRAMDATA_ANTIGRAVITY_NOT_CLEAR']}
    assert present['programdata_antigravity']['before']['entries'] == ['admin_settings.json']
    assert present['isolation_verdict']['programdata_antigravity_clear'] is False and present['isolation_verdict']['disables_hooks'] is False
    during = produced['programdata_during_run'].receipt
    assert during['programdata_antigravity']['before']['state'] == 'ABSENT' and during['programdata_antigravity']['after']['state'] == 'NOT_EMPTY'
    assert during['gate'] == {'passed': False, 'reasons': ['PROGRAMDATA_ANTIGRAVITY_NOT_CLEAR']}
    protected = produced['programdata_protected'].receipt
    assert protected['gate'] == {'passed': True, 'reasons': []}
    assert protected['programdata_antigravity']['before']['state'] == protected['programdata_antigravity']['after']['state'] == 'PROTECTED_EMPTY'


def test_stage_mode_creates_the_protected_programdata_folder_or_refuses(produced):
    """O-F2 (G4): created with the reviewed SDDL when absent, reused when exactly that folder, refused otherwise."""
    stage = produced['stage']
    guard = stage.receipt['programdata_antigravity']
    assert guard['created'] is True and guard['state'] == 'PROTECTED_EMPTY' and guard['clear'] is True and guard['sddl'] == m.PROGRAMDATA_ANTIGRAVITY_SDDL
    assert guard['before']['state'] == 'ABSENT' and guard['after_listing']['state'] == 'PROTECTED_EMPTY'
    assert [sddl for path, sddl in stage.acl.applied if path == str(stage.world.programdata)] == [m.PROGRAMDATA_ANTIGRAVITY_SDDL] * 2
    assert stage.world.programdata.is_dir() and list(stage.world.programdata.iterdir()) == []
    reused = produced['stage_programdata_protected']
    assert reused.receipt['status'] == 'STAGING_COMPLETE' and reused.receipt['gate']['passed'] is True
    assert reused.receipt['programdata_antigravity']['created'] is False and reused.receipt['programdata_antigravity']['state'] == 'PROTECTED_EMPTY'
    for name, state in (('stage_programdata_content', 'NOT_EMPTY'), ('stage_programdata_weak', 'WEAK_ACL')):
        refused = produced[name]
        r = refused.receipt
        assert refused.code == 2 and r['status'] == 'STAGING_FAILED' and r['gate']['reasons'] == ['STAGING_NOT_COMPLETE'], name
        assert r['failure'] == {'phase': 'programdata_guard', 'error_type': 'ValueError', 'winerror': None}, name
        assert r['programdata_antigravity']['state'] == state and r['programdata_antigravity']['created'] is False, name
        assert refused.launched == [] and r['slots'] == [] and refused.acl.applied == [], 'nothing staged, launched or changed: ' + name
    assert (produced['stage_programdata_content'].world.programdata / 'admin_settings.json').read_bytes().startswith(b'{"gateway"')


def test_stage_mode_records_and_verifies_the_protected_parents(produced):
    """O-F3: every slot's .gemini/agents and .gemini/config/agents carry the protected parent ACL, recorded per destination."""
    stage = produced['stage']
    sids = {row['identity']: row['sid'] for row in stage.world.layout['slots'].values()}
    applied = {path: sddl for path, sddl in stage.acl.applied}
    for entry, identity in zip(stage.receipt['slots'], IDENTITIES):
        expected = f'O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;{sids[identity]})'
        for record, relative in zip(entry['staged'], m.AGENT_PARENT_RELATIVES):
            assert record['parent_relative'] == relative and record['parent_acl_verified'] is True and record['parent_acl_sddl'] == expected
            assert record['parent_path'] == str((stage.world.users / identity).joinpath(*relative.split('/')))
            assert applied[record['parent_path']] == expected, (identity, relative)
    assert stage.receipt['agent']['parent_destinations'] == ['.gemini/agents', '.gemini/config/agents']
    assert all('parent_path' not in record for record in produced['pass'].receipt['agent']['staged']), 'evidence mode: leaf only'


def test_receipts_are_create_new_and_never_overwritten(tmp_path, monkeypatch):
    run = produce(tmp_path, monkeypatch, scripts=variant(pc3={'stdout': AGENTS_NONE, 'code': 0}))
    before = (run.root / 'isolation-receipt.json').read_bytes()
    with pytest.raises(FileExistsError):
        run.module.run('evidence', 'slot1', NONCE, ATTEMPT, 'gemini-3.8-flash-low')
    assert (run.root / 'isolation-receipt.json').read_bytes() == before


def test_run_and_main_refuse_wrong_arguments_before_any_receipt():
    for args in (('other', 'slot1', NONCE, ATTEMPT), ('evidence', 'slot2', NONCE, ATTEMPT), ('evidence', 'slot1', NONCE, '0' * 32),
                 ('evidence', 'slot1', 'x', ATTEMPT), ('stage', 'slot1', NONCE, ATTEMPT), ('evidence', 'slot1', NONCE, 'C' * 32)):
        with pytest.raises(ValueError):
            m.run(*args)
    with pytest.raises(ValueError):
        m.run('evidence', 'slot1', NONCE, ATTEMPT, 'gemini-3.1-pro-high')
    with pytest.raises(ValueError):
        m.run('stage', None, NONCE, ATTEMPT, 'gemini-3.8-flash-medium')
    for argv in (['--mode', 'evidence', '--slot', 'slot1', '--nonce', NONCE, '--attempt', ATTEMPT],
                 ['--mode', 'stage', '--slot', 'slot1', '--nonce', NONCE, '--attempt', ATTEMPT],
                 ['--mode', 'stage', '--effort-null-slug', 'gemini-3.8-flash-low', '--nonce', NONCE, '--attempt', ATTEMPT],
                 ['--mode', 'evidence', '--slot', 'slot1', '--effort-null-slug', 'gemini-3.1-pro-high', '--nonce', NONCE, '--attempt', ATTEMPT],
                 ['--mode', 'evidence', '--slot', 'slot1', '--effort-null-slug', 'gemini-3.8-flash-low', '--nonce', 'zz', '--attempt', ATTEMPT]):
        with pytest.raises(SystemExit) as exit_info:
            m.main(argv)
        assert exit_info.value.code == 2


def test_bounded_receipt_text_handles_stage_receipts():
    entries = [{'path': 'p' * 300 + str(i), 'kind': 'file', 'size': 1, 'sha256': 'a' * 64} for i in range(3000)]
    report = {'slots': [{'staging_changes': {'new_files': entries, 'changed_files': [], 'removed_files': [], 'new_directories': []}}],
              'profiles': [{'paths': [{'entries': list(entries)}]}]}
    text = m.bounded_receipt_text(report)
    assert len(text.encode()) <= m.RECEIPT_MAX_BYTES and json.loads(text)['inventory_changes_omitted_for_receipt_bound'] is True


# ---------------------------------------------------------------- PowerShell wrapper (dot-sourced; stubs only)

def psq(value):
    return str(value).replace("'", "''")


PRELUDE = r'''$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;
foreach($m in @('Microsoft.PowerShell.Utility','Microsoft.PowerShell.Security')){Import-Module (Join-Path $PSHOME "Modules\$m\$m.psd1")};
function Get-AstFunctionTexts {param([string]$Path,[string[]]$Names)
  $t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$t,[ref]$e);if($e.Count){throw ($e|Out-String)}
  foreach($f in $a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)){if($null -eq $Names -or $Names -contains $f.Name){$f.Extent.Text}}}
foreach($x in Get-AstFunctionTexts 'SCRIPTPATH' $null){. ([scriptblock]::Create($x))}
foreach($x in Get-AstFunctionTexts 'V22PATH' @('Test-ExactBool','Test-ExactInt')){. ([scriptblock]::Create($x))}
foreach($x in Get-AstFunctionTexts 'REGPATH' @('Assert-RegisteredTaskAcl')){. ([scriptblock]::Create($x))}
foreach($x in Get-AstFunctionTexts 'CHECKPATH' @('Read-R3Text')){. ([scriptblock]::Create($x))}
$held=[Collections.Generic.List[IO.FileStream]]::new();$script:admin=$false
function Read-R3Control {param([string]$Path,[string]$Hash='',[long]$Maximum=16777216)
  $item=Get-Item -LiteralPath $Path -Force;if($item.Length -gt $Maximum){throw 'Bounded r3 control length differs.'}
  $actual=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant();if($Hash -and $actual -cne $Hash){throw ('Source digest changed: '+$Path)}
  $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);$held.Add($stream);[pscustomobject]@{Stream=$stream;Sha256=$actual;Length=$item.Length}}
function Invoke-Case {param([string]$Name,[scriptblock]$Body)
  try{$value=& $Body;'CASE '+([pscustomobject]@{case=$Name;ok=$true;value=$value}|ConvertTo-Json -Depth 12 -Compress)}
  catch{'CASE '+([pscustomobject]@{case=$Name;ok=$false;error=$_.Exception.Message}|ConvertTo-Json -Depth 12 -Compress)}}
$script:ancestorFloor=$null
${function:Get-RealAncestorDirectories}=${function:Get-AncestorDirectories}
function Get-AncestorDirectories {param([string]$Path)
  foreach($d in @(Get-RealAncestorDirectories $Path)){if($null -eq $script:ancestorFloor -or $d.StartsWith($script:ancestorFloor,[StringComparison]::OrdinalIgnoreCase)){$d}}}
function Use-World {param([string]$Mode,[string]$Slug,[string]$Users,[string]$Workers,[string]$Floor,[string]$Ram,[string]$ProgramData)
  Set-IsolationConstants $Mode $(if($Mode -ceq 'stage'){''}else{'slot1'}) 'ATTEMPTVALUE' 'WORKSPACEVALUE' $Slug
  $script:profileParent=$Users;$script:slotRootBase=$Workers
  if($Floor){$script:ancestorFloor=$Floor;$script:ramWorkspaceRoot=$Ram;$script:programDataAntigravity=$ProgramData}}
function Get-Pins {[ordered]@{install_receipt_sha256=$script:r4InstallPin;source_manifest_sha256=$script:r4ManifestPin;revision_sha256=$script:r4RevisionPin;configuration_sha256=$script:configPin;layout_sha256=$script:r4LayoutPin}}
'''.replace('SCRIPTPATH', psq(SCRIPT)).replace('V22PATH', psq(V22)).replace('REGPATH', psq(REGISTER)).replace('CHECKPATH', psq(CHECK_R3)) \
   .replace('ATTEMPTVALUE', ATTEMPT).replace('WORKSPACEVALUE', psq(ROOT))


def run_ps(body, timeout=300):
    result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-Command', PRELUDE + body], capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    cases = {}
    for line in result.stdout.splitlines():
        if line.startswith('CASE '):
            value = json.loads(line[5:])
            cases[value['case']] = value
    return cases, result


def world_args(run):
    w = run.world
    return f"'{psq(w.users)}' '{psq(w.workers)}' '{psq(w.base)}' '{psq(w.ram / 'slot1')}' '{psq(w.programdata)}'"


def ast_summary():
    body = (r'''$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile('SCRIPTFILE',[ref]$t,[ref]$e)
      $names=@($a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)|ForEach-Object {$_.Name})
      $top=@($a.EndBlock.Statements|Where-Object {$_ -isnot [Management.Automation.Language.FunctionDefinitionAst]}|ForEach-Object {$_.Extent.Text})
      $params=@($a.ParamBlock.Parameters|ForEach-Object {[ordered]@{name=$_.Name.VariablePath.UserPath;default=$(if($_.DefaultValue){$_.DefaultValue.Extent.Text}else{$null});
        attributes=@($_.Attributes|ForEach-Object {$_.Extent.Text})}})
      $v=[Management.Automation.Language.Parser]::ParseFile('V22FILE',[ref]$t,[ref]$e)
      $mine=$a.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Import-ReviewedFunctions'},$true)[0].Extent.Text
      $theirs=$v.FindAll({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Import-ReviewedFunctions'},$true)[0].Extent.Text
      'CASE '+([pscustomobject]@{case='ast';ok=$true;value=[ordered]@{errors=$e.Count;names=$names;top=$top;params=$params;import_identical=($mine -ceq $theirs)}}|ConvertTo-Json -Depth 6 -Compress)''')
    body = body.replace('SCRIPTFILE', psq(SCRIPT)).replace('V22FILE', psq(V22))
    result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-Command', body], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    line = next(line for line in result.stdout.splitlines() if line.startswith('CASE '))
    return json.loads(line[5:])['value']


def test_wrapper_parses_under_windows_powershell_51_and_has_one_invocation():
    value = ast_summary()
    assert value['errors'] == 0
    assert value['names'] == ['Import-ReviewedFunctions', 'Set-IsolationConstants', 'Get-AncestorDirectories', 'Get-WorkerProfileRoot', 'Get-SlotRoot',
                              'Get-AgentDestinations',
                              'Get-ExpectedPrecheck', 'Get-ExpectedStageProbes', 'Get-ExpectedRuns', 'Get-IsolationTaskArguments', 'New-IsolationNonce',
                              'Get-SeriesDaemonTaskStates', 'Get-TaskPresence', 'Assert-IsolationRuntimePins', 'New-IsolationTaskDefinition',
                              'Assert-IsolationTaskRegistration', 'Wait-IsolationTaskInstance', 'Assert-CompletedIsolationTask', 'Test-StringList',
                              'Test-SameStrings', 'Test-HasProperty', 'Test-SensitiveText', 'Assert-RawStream', 'Assert-ReplayStreams',
                              'Assert-ProcessAttestation', 'Assert-JobAccounting', 'Assert-LogScan', 'Assert-LaunchOutcome', 'Assert-PrecheckRecord',
                              'Test-AgentsProbe',
                              'Get-ListingReasons', 'Get-PrecheckDecision', 'Get-RunChecks', 'Assert-RunRecord', 'Test-InventoryPresent', 'Get-InventoryFlags',
                              'Assert-InventoryRecords', 'Assert-DeclaredConfig', 'Get-FlaggedProfileConfigs', 'Test-ProgramDataState',
                              'Assert-EvidenceProgramData', 'Assert-StageProgramData',
                              'Get-IsolationVerdict', 'Get-IsolationGate', 'Get-IdentityExpectation',
                              'Assert-IsolationFailureMetadata', 'Assert-StagedAgentRecords', 'Assert-ReceiptIdentity', 'Assert-ReceiptCustody',
                              'Assert-IsolationReceipt', 'Get-StagingGate', 'Assert-StageReceipt', 'New-IsolationSummary', 'New-StageSummary',
                              'New-IsolationHeldRecord', 'Invoke-AgyIsolation', 'Exit-IsolationProcess', 'Write-IsolationOutcome',
                              'Assert-IsolationHost', 'Get-OwnerContext', 'Get-IsolationHelperTexts', 'Get-TaskSchedulerFolder', 'Test-IsolationFile',
                              'Get-WorkerProfilePresence', 'Get-IsolationPlanState', 'Invoke-AgyIsolationMain']
    assert value['top'] == ["Invoke-AgyIsolationMain -Mode $(if($StageOnly){'stage'}else{'evidence'}) -Slot $Slot -Attempt $Attempt "
                            "-EffortNullSlug $EffortNullSlug -ApplyRequested ([bool]$Apply) -Workspace $PSScriptRoot"]
    params = {p['name']: p for p in value['params']}
    assert list(params) == ['Slot', 'EffortNullSlug', 'StageOnly', 'Attempt', 'Apply']
    assert params['EffortNullSlug']['default'] == "'gemini-3.8-flash-low'"
    # No [ValidateSet] on -Slot / -EffortNullSlug (2026-10-11 r5 sitting): Invoke-AgyIsolationMain is the only gate.
    assert params['EffortNullSlug']['attributes'] == ["[Parameter(ParameterSetName='Evidence')]", '[string]']
    assert "[Parameter(Mandatory=$true,ParameterSetName='Stage')]" in params['StageOnly']['attributes']
    assert params['Slot']['attributes'] == ["[Parameter(Mandatory=$true,ParameterSetName='Evidence')]", '[string]']
    assert params['Attempt']['default'] == "'00000000000000000000000000000000'" and params['Apply']['default'] is None
    assert value['import_identical'] is True and hashlib.sha256(V22.read_bytes()).hexdigest() == V22_SHA256


def test_wrapper_pins_equal_the_files_on_disk_and_no_forbidden_operation():
    text = SCRIPT.read_text(encoding='ascii')
    assert f"$script:helperPin='{hashlib.sha256(PY.read_bytes()).hexdigest()}'" in text, 'the helper pin is the file on disk'
    assert f"$script:agentPin='{hashlib.sha256(AGENT.read_bytes()).hexdigest()}'" in text
    for path, needle in ((COPY_HELPER, "$copyHelper '"), (CHECK_R3, "'check-worker-native-status-r3.ps1') '"),
                         (REGISTER, "'register-stopped-warden-r3.ps1') '"), (INSPECTION, "'protected-code-inspection-v4.ps1') '"),
                         (V22, "'retarget-warden-r4.ps1') '")):
        assert needle + hashlib.sha256(path.read_bytes()).hexdigest() + "'" in text, path
    for pin in (m.INSTALL_RECEIPT_SHA256, m.MANIFEST_SHA256, m.REVISION_SHA256, m.LAYOUT_SHA256, m.WINDOWS_SHA256, m.RESOURCE_SHA256,
                m.PRESERVED_DENIAL_SHA256, m.AGY_SHA256, m.CONFIG_SHA256, m.REPAIR_SHA256, m.PROMPT_LINE_SHA256):
        assert f"'{pin}'" in text, pin
    for needle in ("$script:taskSddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'", "$script:taskTimeLimit='PT10M'", "$script:isolationNamespaceDate='20261011'",
                   "RegisterTaskDefinition($script:taskName,$definition,2,'SYSTEM',$null,5,$script:taskSddl)", "$script:taskWaitSeconds=595",
                   "Write-RegistrationControl (Join-Path $script:targetRoot $script:summaryName)",
                   "Write-RegistrationControl (Join-Path $script:targetRoot $script:heldName)"):
        assert needle in text, needle
    assert text.count('.Run($null)') == 1 and text.count('RegisterTaskDefinition(') == 1 and text.count('exit $Code') == 1
    for forbidden in ('Stop-ScheduledTask', 'Disable-ScheduledTask', 'Register-ScheduledTask', 'Unregister-ScheduledTask', 'Start-ScheduledTask',
                      'schtasks', 'Start-Process', 'Stop-Process', 'taskkill', 'Remove-Item', 'DeleteTask', 'Stop-Service', '.Stop(', '.Kill(',
                      'Invoke-Expression', '.Enabled=$false', 'RunAs', 'Set-Content', 'Out-File', 'icacls', 'Set-Acl', 'wsl', 'docker'):
        assert forbidden not in text, forbidden
    helper = PY.read_text(encoding='ascii')
    for forbidden in ('subprocess', 'CredRead', 'shutil', 'unlink', 'rmtree', 'os.remove', 'TerminateProcess', 'icacls', 'urllib', 'socket'):
        assert forbidden not in helper, forbidden
    assert helper.count('win.launch_worker(') == 1 and "'Global\\\\CoChem427-NativeStatusSetup'" in helper
    for create_new in ("(root / RECEIPT_NAMES[mode]).open('x', encoding='ascii')", "path.open('xb')", "target.open('xb')", "stdin_path.open('xb')"):
        assert create_new in helper, create_new


def test_python_and_powershell_tables_agree():
    body = r'''foreach($slug in @('gemini-3.8-flash-low','gemini-3.8-flash-medium','gemini-3.8-flash-high')){
        Set-IsolationConstants 'evidence' 'slot1' ('c'*32) 'X' $slug
        Invoke-Case $slug {@(Get-ExpectedRuns|ForEach-Object {[ordered]@{id=$_.id;model=$_.model;extra=@($_.extra);argv=@($_.argv)}})}}
      Invoke-Case 'precheck' {@(Get-ExpectedPrecheck|ForEach-Object {[ordered]@{id=$_.id;arguments=@($_.arguments);kind=$_.kind}})}
      Invoke-Case 'stage' {@(Get-ExpectedStageProbes|ForEach-Object {[ordered]@{id=$_.id;arguments=@($_.arguments);kind=$_.kind}})}
      Invoke-Case 'constants' {[ordered]@{markers=$script:stderrMarkers;forbidden=$script:forbiddenFlags;sensitive=$script:sensitiveNames;phases=$script:failurePhases;
        reasons=@($script:runCheckReasons.Keys|ForEach-Object {,@($_,$script:runCheckReasons[$_])});echo=$script:echoExempt;jobs=$script:maxModelJobs;deadline=$script:deadlineSeconds;
        args=(Get-IsolationTaskArguments 'D:\h.py' ('e'*32));profile_paths=$script:profilePaths;workspace_paths=$script:workspacePaths;
        job_maximum=$script:jobProcessMaximum;programdata=$script:programDataAntigravity;programdata_sddl=$script:programDataSddl;
        programdata_states=$script:programDataStates;parent_template=$script:parentSddlTemplate;parents=$script:agentParentRelatives;
        ram=$script:ramWorkspaceRoot;slot_chain=@(Get-AncestorDirectories (Get-SlotRoot 'slot1'));ram_chain=@(Get-AncestorDirectories $script:ramWorkspaceRoot);
        isolation_reasons=$script:isolationReasons;declared=$script:declaredConfigPaths;declared_reasons=$script:declaredConfigReasons;
        fragments=$script:declaredConfigFragments;log_fallback=$script:logFallbackPhrases;log_benign=$script:logBenignPhrases;
        log_pattern=$script:logPathPattern;log_maximum=$script:logScanMaximum;log_files=$script:logScanFiles}}
      Set-IsolationConstants 'stage' '' ('c'*32) 'X' ''
      Invoke-Case 'stage_names' {[ordered]@{root=$script:targetRoot;task=$script:taskName;receipt=$script:receiptName;args=(Get-IsolationTaskArguments 'D:\h.py' ('e'*32))}}'''
    cases, _ = run_ps(body)
    for slug in m.EFFORT_NULL_SLUGS:
        assert cases[slug]['value'] == [{'id': r, 'model': model, 'extra': list(extra), 'argv': m.inference_argv(model, extra)}
                                        for r, model, extra, _ in m.run_matrix(slug)]
    assert cases['precheck']['value'] == [{'id': i, 'arguments': list(a), 'kind': k} for i, a, k in m.PRECHECK]
    assert cases['stage']['value'] == [{'id': i, 'arguments': list(a), 'kind': k} for i, a, k in m.STAGE_PROBES]
    c = cases['constants']['value']
    assert c['markers'] == list(m.STDERR_MARKERS) and set(c['forbidden']) == set(m.FORBIDDEN_FLAGS)
    assert c['sensitive'] == list(m.SENSITIVE_NAMES) and c['phases'] == list(m.FAILURE_PHASES)
    assert c['reasons'] == [list(pair) for pair in m.RUN_CHECK_REASONS] and c['echo'] == list(m.ECHO_EXEMPT_CHECKS)
    assert c['jobs'] == m.MAX_MODEL_JOBS and c['deadline'] == m.DEADLINE_SECONDS
    assert c['args'] == f'-I -B "D:\\h.py" --mode evidence --slot slot1 --effort-null-slug gemini-3.8-flash-high --nonce {"e" * 32} --attempt {"c" * 32}'
    assert c['profile_paths'] == list(m.PROFILE_PATHS) and c['workspace_paths'] == list(m.WORKSPACE_PATHS)
    assert c['job_maximum'] == m.JOB_EXPECTED_PROCESSES_MAXIMUM and c['programdata'] == str(m.PROGRAMDATA_ANTIGRAVITY)
    assert c['programdata_sddl'] == m.PROGRAMDATA_ANTIGRAVITY_SDDL and c['programdata_states'] == list(m.PROGRAMDATA_STATES)
    assert c['parent_template'] == m.AGENT_PARENT_DIRECTORY_SDDL and c['parents'] == list(m.AGENT_PARENT_RELATIVES)
    assert c['slot_chain'] == [str(p) for p in m.workspace_ancestors(Path(r'C:\ProgramData\CoChemPipeline427\workers\slot1'))]
    assert c['ram'] == r'R:\CoChem427-windows-20261007\slot1'
    assert c['ram_chain'] == [str(p) for p in m.workspace_ancestors(Path(c['ram']))] == [r'R:\CoChem427-windows-20261007', 'R:\\']
    assert 'JOB_PROCESSES_BEYOND_AGY_TREE' in c['isolation_reasons'] and 'JOB_PROCESSES_BEYOND_AGY_TREE' in m.REASONS
    assert c['declared'] == list(m.DECLARED_CONFIG_PATHS) and c['declared_reasons'] == list(m.DECLARED_CONFIG_REASONS)
    assert c['fragments'] == list(m.DECLARED_CONFIG_FRAGMENTS) and m.PROFILE_CONFIG_REASON_PREFIX == 'PROFILE_CONFIG_FLAGGED:'
    assert c['log_fallback'] == list(m.LOG_FALLBACK_PHRASES) and c['log_benign'] == list(m.LOG_BENIGN_PHRASES)
    assert c['log_pattern'] == '^' + m.LOG_PATH_PATTERN.pattern + '$' and c['log_maximum'] == m.LOG_SCAN_MAXIMUM and c['log_files'] == m.LOG_SCAN_FILES
    s = cases['stage_names']['value']
    assert s == {'root': str(COCHEM / f'AgyIsolation4.2.7-windows-20261011-r4-v1-{"c" * 32}-stage'),
                 'task': f'CoChem-4.2.7-AgyIsolation-20261011-r4-v1-{"c" * 32}-stage', 'receipt': 'stage-receipt.json',
                 'args': f'-I -B "D:\\h.py" --mode stage --nonce {"e" * 32} --attempt {"c" * 32}'}


def test_powershell_run_checks_mirror_python(tmp_path):
    rows = []
    for name in sorted(FAILURE_TABLE):
        kwargs, _, _ = FAILURE_TABLE[name]
        record = classify(kwargs.get('stdout', stream()), kwargs.get('stderr', b''), kwargs.get('code', 0))
        rows.append({'name': name, 'record': record, 'expected': record['checks']})
    for name, model, data in (('echo', 'gemini-3.8-flash', stream()), ('echo_absent', 'gemini-3.8-flash', stream(include_model=False))):
        record = classify(data, model=model)
        rows.append({'name': name, 'record': record, 'expected': record['checks']})
    path = tmp_path / 'rows.json'
    path.write_text(json.dumps(rows), encoding='ascii')
    body = f'''Set-IsolationConstants 'evidence' 'slot1' ('c'*32) 'X' 'gemini-3.8-flash-low'
      foreach($row in (Get-Content -Raw -LiteralPath '{psq(path)}'|ConvertFrom-Json)){{Invoke-Case $row.name {{Get-RunChecks $row.record}}}}'''
    cases, _ = run_ps(body)
    for row in rows:
        assert cases[row['name']]['ok'], cases[row['name']]
        assert cases[row['name']]['value'] == row['expected'], row['name']


def receipt_body(run, slug='gemini-3.8-flash-low'):
    mode = run.mode
    return (f"Use-World '{mode}' '{slug if mode == 'evidence' else ''}' {world_args(run)};$pins=Get-Pins;$task=[pscustomobject]@{{LastTaskResult=0}};"
            f"$root='{psq(run.root)}';function Get-R {{Get-Content -Raw -LiteralPath '{psq(run.root / run.module.RECEIPT_NAMES[mode])}'|ConvertFrom-Json}};")


def test_wrapper_verifies_evidence_receipts_and_refuses_tampering(produced, tmp_path):
    ok = produced['pass']
    copy = tmp_path / 'tampered'
    shutil.copytree(ok.root, copy)
    with open(copy / 'replay' / 'R1.stdout', 'ab') as handle:
        handle.write(b'x')
    leaked = tmp_path / 'leaked'
    shutil.copytree(ok.root, leaked)
    (leaked / 'replay' / 'R1.stderr').write_bytes(('authenticated as ' + EMAIL + '\n').encode())
    leaked_sha = hashlib.sha256((leaked / 'replay' / 'R1.stderr').read_bytes()).hexdigest()
    rawcopy = tmp_path / 'raw'
    shutil.copytree(ok.root, rawcopy)
    with open(rawcopy / 'raw' / 'R5.stderr', 'ab') as handle:
        handle.write(b'x')
    verify = "$v=Assert-IsolationReceipt $r $task $pins 'NONCE' $root;[ordered]@{decision=$v.decision;passed=$v.gate.passed;reasons=@($v.gate.reasons);r5=$v.identity.effort_null_passed}"
    cases_text = {
        'ok': '$r=Get-R;' + verify,
        'helper_sha': "$r=Get-R;$r.helper_sha256=('0'*64);" + verify,
        'nonce': "$r=Get-R;$v=Assert-IsolationReceipt $r $task $pins ('e'*32) $root",
        'planned': "$r=Get-R;$r.runs_planned[1].requested_model='gemini-3.8-flash-high';" + verify,
        'order': "$r=Get-R;$p=@($r.runs);$x=$p[1];$p[1]=$p[2];$p[2]=$x;$r.runs=$p;" + verify,
        'argv': "$r=Get-R;$r.runs[0].argv[2]='--print';" + verify,
        'check': "$r=Get-R;$r.runs[0].checks.tools_empty=$false;" + verify,
        'gate': "$r=Get-R;$r.gate.passed=$false;" + verify,
        'effort_null': "$r=Get-R;$r.identity_verdict.effort_null.passed=$false;" + verify,
        'echo': "$r=Get-R;$r.identity_verdict.family_with_effort_passes_with_echo=$false;" + verify,
        'disables': "$r=Get-R;$r.isolation_verdict.disables_mcp=$false;" + verify,
        'jobs': "$r=Get-R;$r.model_jobs_executed=4;" + verify,
        'sensitive': "$r=Get-R;$r.raw_sensitive_patterns_found=@();" + verify,
        'sddl': "$r=Get-R;$r.agent.staged[0].file_acl_sddl='O:SYG:SYD:(A;;FA;;;WD)';" + verify,
        'last_result': "$r=Get-R;$task=[pscustomobject]@{LastTaskResult=2};" + verify,
        'replay_tamper': f"$r=Get-R;$root='{psq(copy)}';" + verify,
        'raw_tamper': f"$r=Get-R;$root='{psq(rawcopy)}';" + verify,
        'replay_secret': (f"$r=Get-R;$root='{psq(leaked)}';$r.runs[0].replay.stderr.sha256='{leaked_sha}';"
                          f"$r.runs[0].replay.stderr.bytes={(leaked / 'replay' / 'R1.stderr').stat().st_size};"
                          f"$r.replay_streams.R1.stderr.sha256='{leaked_sha}';" + verify),
        'ancestors': "$r=Get-R;$r.workspaces[1].ancestors=@($r.workspaces[1].ancestors[0]);" + verify,
        'ram_root': "$r=Get-R;$r.workspaces[1].root='R:\\Other\\slot1';" + verify,
        'ancestor_flag': "$r=Get-R;$r.workspaces[0].ancestors[0].paths[16]=[pscustomobject]@{path='skills.json';exists=$true;kind='file';size=2;sha256=$null};" + verify,
        'job': "$r=Get-R;$r.runs[0].job_accounting.total_processes=3;" + verify,
        'job_missing': "$r=Get-R;$r.runs[2].PSObject.Properties.Remove('job_accounting');" + verify,
        'probe_job': "$r=Get-R;$r.precheck.probes[0].job_accounting.queried_after_job_termination=$false;" + verify,
        'programdata': "$r=Get-R;$r.programdata_antigravity.before.state='NOT_EMPTY';" + verify,
        'programdata_clear': "$r=Get-R;$r.programdata_antigravity.clear=$false;" + verify,
        'verdict_accounting': "$r=Get-R;$r.isolation_verdict.process_accounting_clean=$false;" + verify,
        # Last: it switches the wrapper constants to another effort-null slug.
        'slug': "Use-World 'evidence' 'gemini-3.8-flash-medium' " + world_args(ok) + ";$r=Get-R;" + verify,
    }
    body = receipt_body(ok) + '\n'.join(f"Invoke-Case '{name}' {{{text}}}" for name, text in cases_text.items()).replace('NONCE', NONCE)
    body += '\nforeach($s in $held){$s.Dispose()}'
    cases, _ = run_ps(body)
    # A second powershell.exe keeps each -Command below the 32767-character command-line limit.
    body = ''
    for name in ('tools', 'marker', 'precheck', 'medium', 'r5_mismatch', 'inventory', 'deadline_after_r1', 'r1_extra_process', 'r2_extra_process',
                 'workspace_chain', 'profile_config', 'programdata_present', 'programdata_during_run', 'programdata_protected'):
        run = produced[name]
        body += '\n' + receipt_body(run, run.slug) + f"Invoke-Case '{name}' {{$r=Get-R;{verify.replace('NONCE', NONCE)}}}"
    late = produced['deadline_after_r1']
    body += ('\n' + receipt_body(late) + '\n'.join(f"Invoke-Case '{name}' {{$r=Get-R;{text}{verify.replace('NONCE', NONCE)}}}" for name, text in (
        ('deadline_reason', "$r.runs_skipped[0].reason='ISOLATION_BREACH_STOP';"),
        ('deadline_row', "$r.identity_verdict.runs.R5.passes_contract=$true;"),
        ('deadline_r1_failed', "$r.runs[0].classification.stream.result.num_turns=2;$r.runs[0].checks.num_turns_one=$false;"
                               "$r.runs[0].checks.passes_contract=$false;$r.runs[0].checks.passes_with_echo=$false;"))))
    for name, result in (('failed', 2), ('deadline', 2)):
        run = produced[name]
        body += ('\n' + receipt_body(run) + f"$task=[pscustomobject]@{{LastTaskResult={result}}};"
                 f"Invoke-Case '{name}' {{$r=Get-R;$v=Assert-IsolationReceipt $r $task $pins '{NONCE}' $root;[ordered]@{{decision=$v.decision;passed=$v.gate.passed;phase=$(if($null -ne $v.failure){{$v.failure.phase}}else{{$null}})}}}}")
    body += '\nforeach($s in $held){$s.Dispose()}'
    more, _ = run_ps(body)
    cases.update(more)
    # Third batch: the declared user configurations (Commander's content rule).
    row = "$x=@($r.profiles[4].paths|Where-Object {$_.path -ceq '.gemini/config/config.json'})[0];"
    flagged, clear = produced['profile_config'], produced['profile_config_clear']
    body = '\n' + receipt_body(clear) + f"Invoke-Case 'profile_config_clear' {{$r=Get-R;{verify.replace('NONCE', NONCE)}}}"
    body += '\n' + '\n'.join(f"Invoke-Case '{name}' {{$r=Get-R;{row}{text}{verify.replace('NONCE', NONCE)}}}" for name, text in (
        ('config_value', "$x.declared_config.top_level_keys=@('chat','https://SECRET-CONFIG-VALUE');"),
        ('config_sha', "$x.declared_config.sha256=('0'*64);"),
        ('config_matching', "$x.declared_config.matching_keys=@('chat','plugins');"),
        ('config_missing', "$x.PSObject.Properties.Remove('declared_config');")))
    body += '\n' + receipt_body(flagged) + '\n'.join(f"Invoke-Case '{name}' {{$r=Get-R;{row}{text}{verify.replace('NONCE', NONCE)}}}" for name, text in (
        ('config_status', "$x.declared_config.status='CLEAR';"),
        ('config_list', "$r.isolation_verdict.profile_configs_flagged=@();"),
        ('config_reason', "$x.declared_config.reason='UNPARSEABLE';")))
    # RG-2 / RG-3 receipts and tampering.
    for name in ('profile_sidecar', 'log_benign', 'log_fallback'):
        body += '\n' + receipt_body(produced[name]) + f"Invoke-Case '{name}' {{$r=Get-R;{verify.replace('NONCE', NONCE)}}}"
    body += '\n' + receipt_body(produced['log_benign']) + '\n'.join(f"Invoke-Case '{name}' {{$r=Get-R;{text}{verify.replace('NONCE', NONCE)}}}" for name, text in (
        ('log_dropped', "$s=$r.runs[0].log_scan;$s.files=@();$s.log_scanned=$false;$s.benign_phrases.'Model resolved via default'=0;"
                        "$s.benign_phrases.'not in local config, defaulting to CCPA'=0;"),
        ('log_phrase', "$r.runs[0].log_scan.fallback_phrases|Add-Member NoteProperty 'Model resolved via default' 0;"),
        ('log_counts', "$r.runs[0].log_scan.fallback_phrases.'Restoring model'=1;")))
    body += '\n' + receipt_body(produced['log_fallback']) + '\n'.join(f"Invoke-Case '{name}' {{$r=Get-R;{text}{verify.replace('NONCE', NONCE)}}}" for name, text in (
        ('log_identity', "$r.identity_verdict.runs.R5.log_fallback_found=$false;"),
        ('log_reroute', "$r.identity_verdict.reroute_scan_clean=$true;")))
    body += '\nforeach($s in $held){$s.Dispose()}'
    more, _ = run_ps(body)
    cases.update(more)
    assert cases['profile_config_clear']['value'] == {'decision': 'COMPLETE', 'passed': True, 'reasons': [], 'r5': True}
    assert cases['profile_sidecar']['value'] == {'decision': 'COMPLETE', 'passed': False, 'r5': True, 'reasons': [
        'PROFILE_INVENTORY_NOT_CLEAR', 'PROFILE_CONFIG_FLAGGED:slot3:.gemini/config/config.json:sidecars']}
    assert cases['log_benign']['value'] == {'decision': 'COMPLETE', 'passed': True, 'reasons': [], 'r5': True}
    assert cases['log_fallback']['value'] == {'decision': 'COMPLETE', 'passed': False, 'reasons': ['MODEL_FALLBACK_LOGGED'], 'r5': True}
    for case, needle in (('log_dropped', 'does not cover exactly the log files this run created'), ('log_phrase', 'differ from the reviewed phrases'),
                         ('log_counts', 'summary contradicts its counts'), ('log_identity', 'identity verdict log scan for R5 contradicts'),
                         ('log_reroute', 'reroute_scan_clean contradicts')):
        assert cases[case]['ok'] is False and needle in cases[case]['error'], (case, cases[case])
    for case, needle in (('config_value', 'something other than key names'), ('config_sha', 'CLEAR inspection contradicts'),
                         ('config_matching', 'not a customization key'), ('config_missing', 'was not inspected'),
                         ('config_status', 'CLEAR inspection contradicts'), ('config_list', 'profile_configs_flagged contradicts'),
                         ('config_reason', 'FLAGGED inspection contradicts')):
        assert cases[case]['ok'] is False and needle in cases[case]['error'], (case, cases[case])
    assert cases['ok']['ok'], cases['ok']
    assert cases['ok']['value'] == {'decision': 'COMPLETE', 'passed': True, 'reasons': [], 'r5': True}
    expected = {'helper_sha': 'identity/runtime binding differs', 'nonce': 'identity/runtime binding differs', 'slug': 'identity/runtime binding differs',
                'planned': 'planned run matrix differs', 'order': 'run order differs', 'argv': 'argv differs', 'check': 'contradicts the retained classification',
                'gate': 'gate contradicts', 'effort_null': 'effort_null contradicts', 'echo': 'family_with_effort_passes_with_echo contradicts',
                'disables': 'disables_mcp contradicts', 'jobs': 'model job or answer count', 'sensitive': 'raw sensitive-pattern summary',
                'sddl': 'staged agent evidence differs', 'last_result': 'configuration/result binding', 'replay_tamper': 'Source digest changed',
                'raw_tamper': 'Source digest changed', 'replay_secret': 'still carries account- or credential-looking text',
                'ancestors': 'does not cover every ancestor directory', 'ram_root': 'is not the reviewed workspace root',
                'ancestor_flag': 'flag skills_present contradicts', 'job': 'job_processes_within_tree contradicts the retained classification',
                'job_missing': 'carries no Job process accounting', 'probe_job': 'Job process accounting is invalid',
                'programdata': 'contradicts its NOT_EMPTY state', 'programdata_clear': 'summary contradicts its inventories',
                'verdict_accounting': 'process_accounting_clean contradicts', 'deadline_reason': 'skipped runs contradict',
                'deadline_row': 'must be executed false and passed false', 'deadline_r1_failed': 'without an isolation breach or a passing R1'}
    for case, needle in expected.items():
        assert cases[case]['ok'] is False and needle in cases[case]['error'], (case, cases[case])
    assert cases['deadline_after_r1']['value'] == {'decision': 'COMPLETE', 'passed': True, 'reasons': [], 'r5': False}
    assert cases['r1_extra_process']['value'] == {'decision': 'COMPLETE', 'passed': False, 'reasons': ['JOB_PROCESSES_BEYOND_AGY_TREE'], 'r5': False}
    assert cases['r2_extra_process']['value'] == {'decision': 'COMPLETE', 'passed': False,
                                                  'reasons': ['ISOLATION_BREACH_IN_MATRIX', 'JOB_PROCESSES_BEYOND_AGY_TREE'], 'r5': True}
    assert cases['workspace_chain']['value'] == {'decision': 'COMPLETE', 'passed': False, 'reasons': ['PROFILE_INVENTORY_NOT_CLEAR'], 'r5': True}
    assert cases['profile_config']['value'] == {'decision': 'COMPLETE', 'passed': False, 'r5': True, 'reasons': [
        'PROFILE_INVENTORY_NOT_CLEAR', 'PROFILE_CONFIG_FLAGGED:slot5:.gemini/config/config.json:mcpServers,plugins']}
    for name in ('programdata_present', 'programdata_during_run'):
        assert cases[name]['value'] == {'decision': 'COMPLETE', 'passed': False, 'reasons': ['PROGRAMDATA_ANTIGRAVITY_NOT_CLEAR'], 'r5': True}, name
    assert cases['programdata_protected']['value'] == {'decision': 'COMPLETE', 'passed': True, 'reasons': [], 'r5': True}
    assert cases['tools']['value'] == {'decision': 'COMPLETE', 'passed': False, 'reasons': ['R1_TOOLS_NOT_EMPTY'], 'r5': False}
    assert cases['marker']['value']['reasons'] == ['R1_STDERR_MARKERS']
    assert cases['precheck']['value'] == {'decision': 'PRECHECK_REFUSED', 'passed': False, 'reasons': ['AGENTS_PRECHECK_FAILED'], 'r5': False}
    assert cases['medium']['value'] == {'decision': 'COMPLETE', 'passed': True, 'reasons': [], 'r5': True}
    assert cases['r5_mismatch']['value'] == {'decision': 'COMPLETE', 'passed': True, 'reasons': [], 'r5': False}
    assert cases['inventory']['value'] == {'decision': 'COMPLETE', 'passed': False, 'reasons': ['PROFILE_INVENTORY_NOT_CLEAR'], 'r5': True}
    assert cases['failed']['value'] == {'decision': 'FAILED', 'passed': False, 'phase': 'agent_verification'}
    assert cases['deadline']['value'] == {'decision': 'INCOMPLETE', 'passed': False, 'phase': None}


def test_wrapper_verifies_stage_receipts_and_refuses_tampering(produced):
    ok, missing, shadow, conflict = produced['stage'], produced['stage_missing'], produced['stage_shadow'], produced['stage_conflict']
    verify = f"$v=Assert-StageReceipt $r $task $pins '{NONCE}' $root;[ordered]@{{decision=$v.decision;passed=$v.gate.passed;reasons=@($v.gate.reasons)}}"
    cases_text = {
        'ok': '$r=Get-R;' + verify,
        'sha': f"$r=Get-R;$r.slots[2].staged[1].sha256=('0'*64);" + verify,
        'listing': "$r=Get-R;$r.slots[4].listing.passed=$false;" + verify,
        'agents': "$r=Get-R;$r.slots[1].probes[0].classification.agents=@('cochem-audit');" + verify,
        'gate': "$r=Get-R;$r.gate.passed=$false;" + verify,
        'jobs': "$r=Get-R;$r.model_jobs_executed=1;" + verify,
        'six': "$r=Get-R;$r.slots=@($r.slots[0..4]);" + verify,
        'dir_sddl': "$r=Get-R;$r.slots[0].staged[0].directory_acl_sddl='O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;S-1-5-21-9)';" + verify,
        'inventory': "$r=Get-R;$r.isolation_inventory_clear=$false;" + verify,
        'parent_sddl': "$r=Get-R;$r.slots[2].staged[0].parent_acl_sddl='O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;S-1-5-21-9)';" + verify,
        'parent_missing': "$r=Get-R;$r.slots[3].staged[1].PSObject.Properties.Remove('parent_path');" + verify,
        'parent_path': "$r=Get-R;$r.slots[4].staged[1].parent_path=$r.slots[4].staged[0].parent_path;" + verify,
        'parent_template': "$r=Get-R;$r.agent.parent_destinations=@('.gemini/agents');" + verify,
        'programdata_sddl': "$r=Get-R;$r.programdata_antigravity.sddl='O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1301bf;;;BU)';" + verify,
        'programdata_acl': "$r=Get-R;$r.programdata_antigravity.after_listing.acl.rules[2][1]=1245631;" + verify,
        'programdata_created': "$r=Get-R;$r.programdata_antigravity.created=$false;" + verify,
        'programdata_after': "$r=Get-R;$r.programdata_antigravity.after_listing.state='NOT_EMPTY';$r.programdata_antigravity.after_listing.entry_count=1;"
                             "$r.programdata_antigravity.after_listing.clear=$false;" + verify,
    }
    body = receipt_body(ok) + '\n'.join(f"Invoke-Case '{name}' {{{text}}}" for name, text in cases_text.items())
    for name, run in (('missing', missing), ('shadow', shadow), ('programdata_reused', produced['stage_programdata_protected'])):
        body += '\n' + receipt_body(run) + f"Invoke-Case '{name}' {{$r=Get-R;{verify}}}"
    for name, run in (('conflict', conflict), ('programdata_content', produced['stage_programdata_content']),
                      ('programdata_weak', produced['stage_programdata_weak'])):
        body += ('\n' + receipt_body(run) + "$task=[pscustomobject]@{LastTaskResult=2};"
                 f"Invoke-Case '{name}' {{$r=Get-R;$v=Assert-StageReceipt $r $task $pins '{NONCE}' $root;[ordered]@{{decision=$v.decision;phase=$v.failure.phase;reasons=@($v.gate.reasons)}}}}")
    body += '\nforeach($s in $held){$s.Dispose()}'
    cases, _ = run_ps(body)
    assert cases['ok']['ok'], cases['ok']
    assert cases['ok']['value'] == {'decision': 'COMPLETE', 'passed': True, 'reasons': []}
    expected = {'sha': 'staged agent evidence differs', 'listing': 'listing decision contradicts', 'agents': 'listing decision contradicts',
                'gate': 'staging gate contradicts', 'jobs': 'Out-of-scope execution', 'six': 'all six slots',
                'dir_sddl': 'directory ACL differs', 'inventory': 'inventory summary contradicts',
                'parent_sddl': 'slot3: the parent folder .gemini/agents ACL differs', 'parent_missing': 'slot4: the parent folder .gemini/config/agents is not recorded',
                'parent_path': 'slot5: the parent folder .gemini/config/agents ACL differs', 'parent_template': 'parent protection differs',
                'programdata_sddl': 'does not record the protected', 'programdata_acl': 'not the protected empty folder (SYSTEM/BA full, Users read and execute)',
                'programdata_created': 'created although it existed, or not created although it was absent',
                'programdata_after': 'is not the protected empty folder'}
    for case, needle in expected.items():
        assert cases[case]['ok'] is False and needle in cases[case]['error'], (case, cases[case])
    assert cases['missing']['value'] == {'decision': 'COMPLETE', 'passed': False,
                                         'reasons': ['slot4:AGENTS_JSON_LISTING_FAILED', 'slot4:AGENTS_TEXT_LISTING_FAILED']}
    assert cases['shadow']['value']['reasons'] == ['slot2:AGENT_SHADOW_FOUND']
    assert cases['programdata_reused']['value'] == {'decision': 'COMPLETE', 'passed': True, 'reasons': []}
    assert cases['conflict']['value'] == {'decision': 'FAILED', 'phase': 'agent_staging', 'reasons': ['STAGING_NOT_COMPLETE']}
    for name in ('programdata_content', 'programdata_weak'):
        assert cases[name]['value'] == {'decision': 'FAILED', 'phase': 'programdata_guard', 'reasons': ['STAGING_NOT_COMPLETE']}, name


APPLY_FIXTURE = r'''
  $script:registered=@();$script:runs=0;$script:task=$null
  function New-PrivateDirectory {param($Path) if(Test-Path -LiteralPath $Path){throw ('Private directory already exists; preserve it: '+$Path)};$null=[IO.Directory]::CreateDirectory($Path);if($script:fx.SecureFails){throw 'Untrusted protected owner: simulated'}}
  function Copy-VerifiedPayload {param($File) if((Get-FileHash -LiteralPath $File.source -Algorithm SHA256).Hash.ToLowerInvariant() -cne $File.sha256){throw 'Source digest changed'};[IO.File]::Copy($File.source,$File.destination)}
  function Open-VerifiedFile {param($Path,$Sha256,$Length) if((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Sha256){throw 'Source digest changed'};$s=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);return ,$s}
  function Assert-CodeTreeOnce {param($Path) 7}
  function Write-RegistrationControl {param($Path,$Text) if(Test-Path -LiteralPath $Path){throw ('control exists: '+$Path)};[IO.File]::WriteAllText($Path,$Text);(Get-FileHash -LiteralPath $Path).Hash.ToLowerInvariant()}
  function New-IsolationNonce {'NONCEVALUE'}
  function New-FixtureScheduler {
    $scheduler=[pscustomobject]@{}
    $scheduler|Add-Member ScriptMethod NewTask {param($f)
      $actions=[pscustomobject]@{Count=0;list=[Collections.ArrayList]::new()}
      $actions|Add-Member ScriptMethod Create {param($t) $a=[pscustomobject]@{Type=$t;Path=$null;Arguments=$null;WorkingDirectory=$null};$null=$this.list.Add($a);$this.Count=$this.list.Count;$a}
      $actions|Add-Member ScriptMethod Item {param($i) $this.list[$i-1]}
      [pscustomobject]@{RegistrationInfo=[pscustomobject]@{Description=$null};Principal=[pscustomobject]@{UserId=$null;LogonType=$null;RunLevel=$null};
        Settings=[pscustomobject]@{Enabled=$null;AllowDemandStart=$null;MultipleInstances=$null;ExecutionTimeLimit=$null;RestartCount=$null};Triggers=[pscustomobject]@{Count=0};Actions=$actions}}
    $scheduler}
  function New-FixtureFolder {
    $folder=[pscustomobject]@{}
    $folder|Add-Member ScriptMethod GetTask {param($name) if($null -ne $script:task -and $name -ceq $script:taskName){return $script:task};throw [Runtime.InteropServices.COMException]::new('absent',-2147024894)}
    $folder|Add-Member ScriptMethod RegisterTaskDefinition {param($name,$def,$flags,$user,$pw,$logon,$sddl)
      $script:registered+=[pscustomobject]@{name=$name;flags=$flags;user=$user;logon=$logon;sddl=$sddl;arguments=$def.Actions.Item(1).Arguments;limit=$def.Settings.ExecutionTimeLimit}
      $script:task=[pscustomobject]@{Enabled=$def.Settings.Enabled;State=3;LastTaskResult=267011;Definition=$def;Xml='<Task>fixture</Task>';Instances=0}
      $script:task|Add-Member ScriptMethod GetInstances {param($n)[pscustomobject]@{Count=$script:task.Instances}}
      $script:task|Add-Member ScriptMethod GetSecurityDescriptor {param($n)$script:fx.Sddl}
      $script:task|Add-Member ScriptMethod Run {param($a)
        $script:runs++
        if($script:fx.CopyReceipt){foreach($f in Get-ChildItem -LiteralPath $script:fixtureSource -Recurse -File){
          $rel=$f.FullName.Substring($script:fixtureSource.Length).TrimStart('\');if($rel -cin @('agy_isolation_evidence_r4_v1.py','cochem-inference-only.agent.md')){continue}
          $dst=Join-Path $script:targetRoot $rel;$null=[IO.Directory]::CreateDirectory((Split-Path -Parent $dst));[IO.File]::Copy($f.FullName,$dst)}}
        $script:task.LastTaskResult=$script:fx.LastTaskResult;$i=[pscustomobject]@{State=4};$i|Add-Member ScriptMethod Refresh {if($script:fx.RefreshEnds){$this.State=3}};$i}
      $script:task}
    $folder}
  function Invoke-ApplyCase {param([string]$Name,[string]$Mode,[string]$Slug,[string]$Source,[string]$Users,[string]$Workers,[string]$Floor,[string]$Ram,
      [string]$ProgramData,[hashtable]$Fx,[switch]$PreCreate,[int]$Wait=595)
    Use-World $Mode $Slug $Users $Workers $Floor $Ram $ProgramData;$script:taskWaitSeconds=$Wait
    $script:targetRoot=Join-Path 'TMPROOT' $Name
    if($script:targetRoot -like 'C:\Program Files*'){throw 'fixture roots must be temporary'}
    $script:registered=@();$script:runs=0;$script:task=$null;$script:fixtureSource=$Source
    $script:fx=@{Sddl='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)';LastTaskResult=0;CopyReceipt=$true;RefreshEnds=$true;SecureFails=$false};foreach($k in $Fx.Keys){$script:fx[$k]=$Fx[$k]}
    if($PreCreate){$null=[IO.Directory]::CreateDirectory($script:targetRoot)}
    $result=[ordered]@{ok=$true;error=$null;summary=$null}
    try{$s=Invoke-AgyIsolation (New-FixtureScheduler) (New-FixtureFolder) (Get-Pins) ((Get-Item -LiteralPath $script:helperSource).Length) ((Get-Item -LiteralPath $script:agentSource).Length)
        $result.summary=[ordered]@{status=$s.status;decision=$s.decision;passed=$s.gate.passed;reasons=@($s.gate.reasons);outcome=$s.gemini_outcome;exit_code=$s.exit_code;
          message=$s.message;capability=$(if($s.Contains('capability_reference')){$s.capability_reference}else{$null});effort_null=$(if($s.Contains('effort_null')){$s.effort_null}else{$null});
          receipt_sha=$s.receipt_sha256;replay=$(if($s.Contains('replay_streams')){@($s.replay_streams.PSObject.Properties|ForEach-Object {$_.Name})}else{$null})}}
    catch{$result.ok=$false;$result.error=$_.Exception.Message}
    foreach($s in $held){$s.Dispose()};$held.Clear()
    $files=@();if(Test-Path -LiteralPath $script:targetRoot){$files=@(Get-ChildItem -LiteralPath $script:targetRoot -File|ForEach-Object {$_.Name}|Sort-Object)}
    $heldRecord=$null;$heldPath=Join-Path $script:targetRoot $script:heldName;if(Test-Path -LiteralPath $heldPath){$heldRecord=Get-Content -Raw -LiteralPath $heldPath|ConvertFrom-Json}
    $summaryRecord=$null;$summaryPath=Join-Path $script:targetRoot $script:summaryName;if(Test-Path -LiteralPath $summaryPath){$summaryRecord=Get-Content -Raw -LiteralPath $summaryPath|ConvertFrom-Json}
    $result.files=$files;$result.registered=@($script:registered);$result.runs=$script:runs;$result.held=$heldRecord;$result.summary_file=$summaryRecord
    'CASE '+([pscustomobject]@{case=$Name;ok=$true;value=$result}|ConvertTo-Json -Depth 12 -Compress)}
'''


def apply_case(name, run, extra='@{}', switches=''):
    slug = run.slug if run.mode == 'evidence' else ''
    return f"Invoke-ApplyCase '{name}' '{run.mode}' '{slug}' '{psq(run.root)}' {world_args(run)} {extra} {switches}"


def test_wrapper_apply_path_is_driven_with_fixtures(produced, tmp_path):
    p, tools, pre, failed, stage, missing = (produced[n] for n in ('pass', 'tools', 'precheck', 'failed', 'stage', 'stage_missing'))
    fixture = APPLY_FIXTURE.replace('TMPROOT', psq(tmp_path)).replace('NONCEVALUE', NONCE)
    calls = [apply_case('pass', p), apply_case('isolation_stop', tools), apply_case('precheck', pre),
             apply_case('helper_failed', failed, '@{LastTaskResult=2}'), apply_case('no_receipt', p, '@{CopyReceipt=$false;LastTaskResult=3}'),
             apply_case('acl', p, "@{Sddl='O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;BU)'}"), apply_case('root_exists', p, '@{}', '-PreCreate'),
             apply_case('root_secure', p, '@{SecureFails=$true}'), apply_case('wait_timeout', p, '@{RefreshEnds=$false;CopyReceipt=$false}', '-Wait 1'),
             apply_case('stage_pass', stage), apply_case('stage_missing', missing),
             apply_case('deadline_after_r1', produced['deadline_after_r1']), apply_case('job_stop', produced['r1_extra_process']),
             apply_case('stage_programdata_refused', produced['stage_programdata_content'], '@{LastTaskResult=2}')]
    cases, _ = run_ps(fixture + '\n'.join(calls))
    v = {name: case['value'] for name, case in cases.items()}
    root = tmp_path / 'pass'
    args = f'-I -B "{root / m.HELPER_NAME}" --mode evidence --slot slot1 --effort-null-slug gemini-3.8-flash-low --nonce {NONCE} --attempt {ATTEMPT}'
    assert v['pass']['ok'], v['pass']
    s = v['pass']['summary']
    assert s['passed'] is True and s['outcome'] == 'PASSED' and s['exit_code'] == 0 and s['message'].startswith('Isolation evidence verified (G3 passed)')
    assert s['capability'] == str(root / 'isolation-receipt.json') + '#' + s['receipt_sha'] and s['replay'] == ['R1', 'R2', 'R3', 'R4', 'R5']
    assert s['effort_null'] == {'slug': 'gemini-3.8-flash-low', 'run_id': 'R5', 'executed': True, 'passed': True, 'init_model': 'gemini-3.8-flash-low'}
    assert v['pass']['registered'] == [{'name': f'CoChem-4.2.7-AgyIsolation-20261011-r4-v1-{ATTEMPT}', 'flags': 2, 'user': 'SYSTEM', 'logon': 5,
                                        'sddl': 'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)', 'arguments': args, 'limit': 'PT10M'}]
    assert v['pass']['runs'] == 1 and v['pass']['held'] is None
    assert v['pass']['files'] == sorted(['agy_isolation_evidence_r4_v1.py', 'cochem-inference-only.agent.md', 'isolation-intent.json',
                                         'isolation-receipt.json', 'isolation-summary.json', 'isolation-task.xml'])
    summary_text = json.dumps(v['pass']['summary_file'])
    for secret in SECRETS:
        assert secret not in summary_text
    assert v['pass']['summary_file']['capability_reference'] == s['capability'] and v['pass']['summary_file']['gemini_gate'] == 'G3'
    for name, reasons in (('isolation_stop', ['R1_TOOLS_NOT_EMPTY']), ('precheck', ['AGENTS_PRECHECK_FAILED'])):
        assert v[name]['ok'] and v[name]['summary']['outcome'] == 'HELD' and v[name]['summary']['exit_code'] == 10, v[name]
        assert v[name]['summary']['reasons'] == reasons and v[name]['summary']['capability'] is None
        assert v[name]['summary']['message'].startswith('GEMINI-HELD (G3')
        assert v[name]['held']['phase'] == 'GATE' and v[name]['held']['gemini_outcome'] == 'HELD' and v[name]['held']['requires_reviewed_recovery'] is False
    assert 'Decision 4' in v['isolation_stop']['summary']['message']
    assert v['helper_failed']['ok'] is False and v['helper_failed']['error'].startswith('GEMINI-HELD (G3): the isolation helper reported EVIDENCE_FAILED')
    assert v['helper_failed']['held']['phase'] == 'HELPER' and v['helper_failed']['held']['helper_failure']['phase'] == 'agent_verification'
    assert 'isolation-summary.json' in v['helper_failed']['files']
    assert v['no_receipt']['ok'] is False and 'left no receipt (LastTaskResult 3)' in v['no_receipt']['error'] and v['no_receipt']['held']['phase'] == 'RECEIPT'
    assert v['acl']['ok'] is False and 'held at task registration' in v['acl']['error'] and v['acl']['runs'] == 0
    assert v['acl']['held']['task_registered'] is True and v['acl']['held']['run_requested'] is False
    assert v['root_exists']['ok'] is False and 'held before any change' in v['root_exists']['error'] and v['root_exists']['files'] == []
    assert v['root_exists']['registered'] == [] and v['root_exists']['held'] is None
    assert v['root_secure']['ok'] is False and 'could not be secured' in v['root_secure']['error'] and v['root_secure']['runs'] == 0
    assert v['root_secure']['held']['phase'] == 'ROOT' and v['root_secure']['files'] == ['isolation-held.json']
    assert v['wait_timeout']['ok'] is False and 'did not end cleanly' in v['wait_timeout']['error'] and v['wait_timeout']['held']['phase'] == 'WAIT'
    stage_args = f'-I -B "{tmp_path / "stage_pass" / m.HELPER_NAME}" --mode stage --nonce {NONCE} --attempt {ATTEMPT}'
    assert v['stage_pass']['ok'] and v['stage_pass']['summary']['outcome'] == 'PASSED' and v['stage_pass']['summary']['exit_code'] == 0, v['stage_pass']
    assert v['stage_pass']['registered'][0]['name'] == f'CoChem-4.2.7-AgyIsolation-20261011-r4-v1-{ATTEMPT}-stage'
    assert v['stage_pass']['registered'][0]['arguments'] == stage_args
    assert v['stage_pass']['files'] == sorted(['agy_isolation_evidence_r4_v1.py', 'cochem-inference-only.agent.md', 'stage-intent.json',
                                               'stage-receipt.json', 'stage-summary.json', 'stage-task.xml'])
    slots = v['stage_pass']['summary_file']['slots']
    assert [x['slot'] for x in slots] == SLOTS and all(x['passed'] and x['agents_json'] == ['cochem-inference-only'] for x in slots)
    assert v['stage_missing']['ok'] and v['stage_missing']['summary']['outcome'] == 'HELD' and v['stage_missing']['summary']['exit_code'] == 10
    assert v['stage_missing']['held']['phase'] == 'GATE' and v['stage_missing']['summary']['message'].startswith('GEMINI-HELD (G4)')
    # O-F1/O-F2/O-F3/O-F4 in the summaries.
    assert v['pass']['summary_file']['programdata_antigravity'] == {'path': str(p.world.programdata), 'clear': True, 'before': 'ABSENT', 'after': 'ABSENT'}
    assert v['pass']['summary_file']['deadline_skipped_runs'] == [] and v['pass']['summary_file']['job_expected_processes_maximum'] == 2
    assert all(run['job_total_processes'] == 2 and run['job_processes_within_tree'] is True for run in v['pass']['summary_file']['runs'])
    stage_summary = v['stage_pass']['summary_file']
    assert stage_summary['programdata_antigravity'] == {'path': str(stage.world.programdata), 'sddl': m.PROGRAMDATA_ANTIGRAVITY_SDDL,
                                                        'state': 'PROTECTED_EMPTY', 'created': True, 'verified': True}
    assert all(len(x['protected_parents']) == 2 for x in slots) and 'both parent folders protected' in stage_summary['message']
    late = v['deadline_after_r1']
    assert late['ok'] and late['summary']['outcome'] == 'PASSED' and late['summary']['exit_code'] == 0, late
    assert sorted(late['summary_file']['replay_streams']) == ['R1']
    assert 'skipped by the deadline guard after R1 passed (left unbound): R5, R2, R3, R4' in late['summary']['message']
    assert late['summary']['effort_null']['executed'] is False and late['summary_file']['deadline_skipped_runs'] == ['R5', 'R2', 'R3', 'R4']
    stop = v['job_stop']
    assert stop['ok'] and stop['summary']['outcome'] == 'HELD' and stop['summary']['exit_code'] == 10 and stop['held']['phase'] == 'GATE'
    assert stop['summary']['reasons'] == ['JOB_PROCESSES_BEYOND_AGY_TREE'] and stop['summary']['message'].startswith('GEMINI-HELD (G3, Decision 4)')
    refused = v['stage_programdata_refused']
    assert refused['ok'] is False and refused['error'].startswith('GEMINI-HELD (G4): the isolation helper reported STAGING_FAILED'), refused
    assert refused['held']['phase'] == 'HELPER' and refused['held']['helper_failure']['phase'] == 'programdata_guard'
    assert 'NOT_EMPTY (preserved for review)' in refused['summary_file']['message'] and refused['summary_file']['programdata_antigravity']['verified'] is False


def test_write_outcome_exit_codes():
    body = r'''Set-IsolationConstants 'evidence' 'slot1' ('c'*32) 'X' 'gemini-3.8-flash-low'
      function Exit-IsolationProcess {param([int]$Code) throw ('EXIT '+$Code)}
      $pass=[ordered]@{decision='COMPLETE';gemini_outcome='PASSED';gate=[ordered]@{passed=$true;reasons=@()};message='Isolation evidence verified'}
      $heldSummary=[ordered]@{decision='COMPLETE';gemini_outcome='HELD';gate=[ordered]@{passed=$false;reasons=@('R1_STDERR_MARKERS')};message='GEMINI-HELD (G3): x'}
      $odd=[ordered]@{decision='COMPLETE';gemini_outcome='PASSED';gate=[ordered]@{passed='true';reasons=@()};message='odd'}
      $refused=[ordered]@{decision='PRECHECK_REFUSED';gemini_outcome='HELD';gate=[ordered]@{passed=$false;reasons=@('AGENTS_PRECHECK_FAILED')};message='GEMINI-HELD'}
      Invoke-Case 'pass' {(Write-IsolationOutcome $pass|ConvertFrom-Json).message}
      Invoke-Case 'held' {Write-IsolationOutcome $heldSummary 6>$null}
      Invoke-Case 'odd' {Write-IsolationOutcome $odd 6>$null}
      Invoke-Case 'refused' {Write-IsolationOutcome $refused 6>$null}'''
    cases, result = run_ps(body)
    assert cases['pass'] == {'case': 'pass', 'ok': True, 'value': 'Isolation evidence verified'}
    for case in ('held', 'odd', 'refused'):
        assert cases[case]['ok'] is False and cases[case]['error'] == 'EXIT 10', case


PLAN_FIXTURE = r'''
  function Assert-R4InstalledBindings {if($script:fx.RuntimeFails){throw 'simulated r4 binding'};[pscustomobject]@{install_receipt_sha256=$script:r4InstallPin;revision_sha256=$script:r4RevisionPin;source_manifest_sha256=$script:r4ManifestPin}}
  function Assert-IsolationRuntimePins {param($Runtime)Get-Pins}
  function Open-VerifiedFile {param($Path,$Sha256,$Length) $target=$Path;if($Path -like 'C:\Program Files*'){$target='STANDIN'};if($Path -notlike 'C:\Program Files*' -and (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Sha256){throw 'Source digest changed'};$s=[IO.File]::Open($target,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);return ,$s}
  function Assert-ProtectedPath {param($Path)}
  function Test-IsolationFile {param($Path)$true}
  function Get-TaskSchedulerFolder {
    $folder=[pscustomobject]@{};$folder|Add-Member ScriptMethod GetTask {param($name)
      if($name -ceq 'CoChem-4.2.7-Warden'){$t=[pscustomobject]@{Enabled=$script:fx.WardenEnabled;State=1};$t|Add-Member ScriptMethod GetInstances {param($n)[pscustomobject]@{Count=0}};return $t}
      throw [Runtime.InteropServices.COMException]::new('absent',-2147024894)}
    [pscustomobject]@{scheduler='fixture';folder=$folder}}
  function Get-WorkerProfilePresence {foreach($name in $script:workerIdentities){[ordered]@{identity=$name;profile_root=(Get-WorkerProfileRoot $name);present=($name -cne $script:fx.MissingProfile)}}}
  function Invoke-PlanCase {param([string]$Name,[string]$Mode,[string]$Slug,[hashtable]$Fx,[bool]$Admin)
    Set-IsolationConstants $Mode $(if($Mode -ceq 'stage'){''}else{'slot1'}) ('c'*32) 'WORKSPACE' $Slug
    $script:fx=@{RuntimeFails=$false;WardenEnabled=$false;MissingProfile=''};foreach($k in $Fx.Keys){$script:fx[$k]=$Fx[$k]}
    try{$state=Get-IsolationPlanState ([pscustomobject]@{name='AETHERDESK\ansac';admin=$Admin})
      'CASE '+([pscustomobject]@{case=$Name;ok=$true;value=[ordered]@{plan=$state.plan;holds=@($state.holds)}}|ConvertTo-Json -Depth 8 -Compress)}
    catch{'CASE '+([pscustomobject]@{case=$Name;ok=$false;error=$_.Exception.Message}|ConvertTo-Json -Compress)}
    foreach($s in $held){$s.Dispose()};$held.Clear()}
'''


def test_plan_state_is_read_only_and_reports_holds(tmp_path):
    standin = tmp_path / 'standin.bin'
    standin.write_bytes(b'MZ')
    before = sorted(p.name for p in COCHEM.iterdir()) if COCHEM.exists() else []
    fixture = PLAN_FIXTURE.replace('STANDIN', psq(standin)).replace('WORKSPACE', psq(ROOT))
    calls = ["Invoke-PlanCase 'evidence' 'evidence' 'gemini-3.8-flash-low' @{} $true",
             "Invoke-PlanCase 'stage' 'stage' '' @{} $true",
             "Invoke-PlanCase 'warden_enabled' 'evidence' 'gemini-3.8-flash-medium' @{WardenEnabled=$true} $true",
             "Invoke-PlanCase 'profile_missing' 'stage' '' @{MissingProfile='CoChem422Worker5'} $true",
             "Invoke-PlanCase 'profile_missing_unelevated' 'stage' '' @{MissingProfile='CoChem422Worker5'} $false",
             "Invoke-PlanCase 'runtime' 'evidence' 'gemini-3.8-flash-low' @{RuntimeFails=$true} $true"]
    cases, _ = run_ps(fixture + '\n'.join(calls))
    plan = cases['evidence']['value']['plan']
    assert cases['evidence']['value']['holds'] == []
    assert plan['schema'] == 'cochem-agy-isolation-evidence-plan/1' and plan['mode'] == 'READ_ONLY_PLAN' and plan['evidence_mode'] == 'evidence'
    assert plan['gemini_gate'] == 'G3' and plan['effort_null_slug'] == 'gemini-3.8-flash-low' and plan['helper_verified'] is True and plan['agent_verified'] is True
    assert plan['target_root'] == str(COCHEM / f'AgyIsolation4.2.7-windows-20261011-r4-v1-{"c" * 32}') and plan['task_presence'] == 'ABSENT'
    assert [r['id'] for r in plan['runs']] == ['R1', 'R5', 'R2', 'R3', 'R4'] and plan['runs'][1]['requested_model'] == 'gemini-3.8-flash-low'
    assert plan['model_jobs_planned_maximum'] == 5 and plan['exit_codes'] == {'passed': 0, 'gemini_held': 10, 'refused_or_held_by_error': 1}
    assert plan['task_action']['arguments'].endswith('--mode evidence --slot slot1 --effort-null-slug gemini-3.8-flash-low --nonce <nonce> --attempt ' + 'c' * 32)
    assert plan['files_created'] == 0 and plan['tasks_changed'] == 0 and plan['native_commands_executed'] == 0
    stage = cases['stage']['value']['plan']
    assert stage['evidence_mode'] == 'stage' and stage['gemini_gate'] == 'G4' and stage['runs'] == [] and stage['model_jobs_planned_maximum'] == 0
    assert stage['stage_slots'] == SLOTS and len(stage['agent_destinations']) == 12 and stage['target_root'].endswith('-stage')
    assert stage['agent_destinations'][9] == r'C:\Users\CoChem422Worker5\.gemini\config\agents\cochem-inference-only\agent.md'
    assert stage['agent_parent_protection'] == ['.gemini/agents', '.gemini/config/agents'] and plan['agent_parent_protection'] == []
    for value, needle in ((stage, 'creates it as the protected empty folder'), (plan, 'inventoried read-only')):
        assert value['programdata_antigravity']['path'] == r'C:\ProgramData\Antigravity' and needle in value['programdata_antigravity']['action']
        assert value['programdata_antigravity']['sddl'] == m.PROGRAMDATA_ANTIGRAVITY_SDDL
    assert plan['job_expected_processes_maximum'] == 2 and stage['job_expected_processes_maximum'] is None
    assert any('Protected daemons must remain stopped' in h for h in cases['warden_enabled']['value']['holds'])
    assert cases['profile_missing']['value']['holds'] == [r'A worker profile directory is not present: C:\Users\CoChem422Worker5']
    assert cases['profile_missing_unelevated']['value']['holds'] == []
    assert any('r4 runtime is not the reviewed build' in h for h in cases['runtime']['value']['holds'])
    assert (sorted(p.name for p in COCHEM.iterdir()) if COCHEM.exists() else []) == before, 'the plan creates nothing'


MAIN_FIXTURE = r'''
  $script:invoked=0
  function Get-OwnerContext {[pscustomobject]@{name=$script:owner;admin=$script:isAdmin}}
  function Get-IsolationHelperTexts {param($Workspace) @()}
  function Initialize-FileIdentity {}
  function Get-IsolationPlanState {param($Owner)[pscustomobject]@{plan=[ordered]@{mode='READ_ONLY_PLAN';evidence_mode=$script:Mode;slug=$script:effortNullSlug};holds=$script:planHolds;pins=$null;helper_length=1;agent_length=1;scheduler=$null;folder=$null}}
  function Invoke-AgyIsolation {param($Scheduler,$Folder,$Pins,$HelperLength,$AgentLength) $script:invoked++;[ordered]@{decision='COMPLETE';gemini_outcome='PASSED';gate=[ordered]@{passed=$true;reasons=@()};message='fixture'}}
  function Exit-IsolationProcess {param([int]$Code) throw ('EXIT '+$Code)}
  function Invoke-MainCase {param([string]$Name,[string]$Mode,[string]$Slot,[string]$Attempt,[string]$Slug,[bool]$Apply,[bool]$Admin,[string]$Owner='AETHERDESK\ansac',[string[]]$Holds=@())
    $script:isAdmin=$Admin;$script:owner=$Owner;$script:planHolds=$Holds;$script:invoked=0
    try{$out=Invoke-AgyIsolationMain -Mode $Mode -Slot $Slot -Attempt $Attempt -EffortNullSlug $Slug -ApplyRequested $Apply -Workspace 'WORKSPACE'
      'CASE '+([pscustomobject]@{case=$Name;ok=$true;value=[ordered]@{out=(@($out) -join "`n");invoked=$script:invoked}}|ConvertTo-Json -Depth 6 -Compress)}
    catch{'CASE '+([pscustomobject]@{case=$Name;ok=$false;error=$_.Exception.Message;invoked=$script:invoked}|ConvertTo-Json -Compress)}}
'''


def test_main_gates_plan_and_apply_at_function_level():
    fixture = MAIN_FIXTURE.replace('WORKSPACE', psq(ROOT))
    a = ATTEMPT
    calls = [f"Invoke-MainCase 'plan' 'evidence' 'slot1' '{a}' 'gemini-3.8-flash-low' $false $false",
             f"Invoke-MainCase 'plan_zero' 'stage' '' ('0'*32) 'gemini-3.8-flash-low' $false $false",
             f"Invoke-MainCase 'apply_unelevated' 'evidence' 'slot1' '{a}' 'gemini-3.8-flash-low' $true $false",
             f"Invoke-MainCase 'apply_other_owner' 'evidence' 'slot1' '{a}' 'gemini-3.8-flash-low' $true $true 'AETHERDESK\\other'",
             f"Invoke-MainCase 'apply_holds' 'stage' '' '{a}' '' $true $true 'AETHERDESK\\ansac' @('a daemon is enabled')",
             f"Invoke-MainCase 'apply_ok' 'evidence' 'slot1' '{a}' 'gemini-3.8-flash-medium' $true $true",
             f"Invoke-MainCase 'apply_zero' 'evidence' 'slot1' ('0'*32) 'gemini-3.8-flash-low' $true $true",
             f"Invoke-MainCase 'upper' 'evidence' 'slot1' ('C'*32) 'gemini-3.8-flash-low' $false $true",
             f"Invoke-MainCase 'slot2' 'evidence' 'slot2' '{a}' 'gemini-3.8-flash-low' $false $true",
             f"Invoke-MainCase 'stage_slot' 'stage' 'slot1' '{a}' '' $false $true",
             f"Invoke-MainCase 'slug' 'evidence' 'slot1' '{a}' 'gemini-3.1-pro-high' $false $true",
             f"Invoke-MainCase 'mode' 'login' 'slot1' '{a}' 'gemini-3.8-flash-low' $false $true"]
    cases, _ = run_ps(fixture + '\n'.join(calls))
    assert cases['plan']['ok'] and cases['plan']['value']['invoked'] == 0 and json.loads(cases['plan']['value']['out'])['mode'] == 'READ_ONLY_PLAN'
    assert cases['plan_zero']['ok'] and json.loads(cases['plan_zero']['value']['out'])['evidence_mode'] == 'stage', 'the all-zero attempt is the preview'
    assert cases['apply_unelevated'] == {'case': 'apply_unelevated', 'ok': False, 'invoked': 0,
                                         'error': '-Apply requires the owner in Administrator Windows PowerShell; nothing was changed.'}
    assert cases['apply_other_owner']['ok'] is False and cases['apply_other_owner']['invoked'] == 0
    assert cases['apply_holds']['ok'] is False and 'held. Nothing was changed: a daemon is enabled' in cases['apply_holds']['error']
    assert cases['apply_holds']['invoked'] == 0
    assert cases['apply_ok']['ok'] and cases['apply_ok']['value']['invoked'] == 1 and json.loads(cases['apply_ok']['value']['out'])['message'] == 'fixture'
    for case, needle in (('apply_zero', 'lowercase 32-hex -Attempt'), ('upper', 'lowercase 32-hex -Attempt'), ('slot2', 'Only -Slot slot1'),
                         ('stage_slot', 'takes no -Slot'), ('slug', 'EffortNullSlug must be'), ('mode', 'modes are reviewed')):
        assert cases[case]['ok'] is False and needle in cases[case]['error'] and cases[case]['invoked'] == 0, case


def test_parameter_binding_refuses_invalid_arguments_before_any_code_runs():
    """The whole script is started only with arguments that cannot bind; nothing reaches the plan or -Apply.
    An out-of-set -Slot or -EffortNullSlug now binds and is refused by the main function instead; that is exercised only
    under ps_toplevel_smoke (stubbed host) in test_toplevel_slot_or_slug_outside_the_reviewed_set_is_refused_before_any_host_command."""
    before = sorted(p.name for p in COCHEM.iterdir()) if COCHEM.exists() else []
    for flags, needle in ((['-Slot', 'slot1', '-Attempt', 'xyz'], 'Attempt'), (['-StageOnly', '-Slot', 'slot1'], 'Parameter set'),
                          (['-StageOnly', '-EffortNullSlug', 'gemini-3.8-flash-low'], 'Parameter set')):
        result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-File', str(SCRIPT), *flags], capture_output=True, text=True, timeout=120)
        assert result.returncode != 0 and needle in result.stderr, (flags, result.stderr)
        assert 'READ_ONLY_PLAN' not in result.stdout
    assert (sorted(p.name for p in COCHEM.iterdir()) if COCHEM.exists() else []) == before


# ------------------------------------------------------------------- top level, plan mode only (ps_toplevel_smoke.py)
# The wrapper fixtures above dot-source single functions, so the real param block never ran with a sitting argument
# vector. That hid the 2026-10-11 17:22 class here: in -StageOnly mode Invoke-AgyIsolationMain passes Slot='' and
# EffortNullSlug='' to Set-IsolationConstants, whose $script:Slot / $script:effortNullSlug ARE the [ValidateSet] script
# parameters (names are case-insensitive), so every S8 G4 call threw ValidationMetadataException before any change.
# These tests run the REAL script top level with the host stubbed; the helper refuses -Apply, so each documented sitting
# call runs with -Apply removed (its plan).

PLAN_SCHEMA = 'cochem-agy-isolation-evidence-plan/1'
SLUGS = ['gemini-3.8-flash-low', 'gemini-3.8-flash-medium', 'gemini-3.8-flash-high']
SITTING_CALLS = (
    # RUN_427_R5_SITTING.ps1 S8 G3 (the sitting's -EffortNullSlug is one of its own three-value set) and S8 G4.
    [pytest.param('evidence', ['-Slot', 'slot1', '-EffortNullSlug', slug, '-Attempt', ATTEMPT], id='S8-G3-' + slug) for slug in SLUGS]
    + [pytest.param('stage', ['-StageOnly', '-Attempt', ATTEMPT], id='S8-G4-stage')])


def validated_parameter_assignments(script):
    """Assignments that write a [Validate*] script parameter variable: $script:/$global:<name> anywhere (functions run in
    the script's scope), or a bare <name> at the top level; names compare case-insensitively, as PowerShell does."""
    code = ("$t=$null;$e=$null;$a=[Management.Automation.Language.Parser]::ParseFile('" + psq(script) + "',[ref]$t,[ref]$e);if($e.Count){throw $e[0]};"
            "$v=@{};foreach($p in @($a.ParamBlock.Parameters)){if(@($p.Attributes|Where-Object{$_.TypeName.Name -like 'Validate*'}).Count){$v[$p.Name.VariablePath.UserPath.ToLowerInvariant()]=1}};"
            "$hits=@(foreach($n in $a.FindAll({param($x)$x -is [Management.Automation.Language.AssignmentStatementAst]},$true)){"
            "$targets=@($n.Left);if($n.Left -is [Management.Automation.Language.ArrayLiteralAst]){$targets=@($n.Left.Elements)};"
            "foreach($l in $targets){if($l -is [Management.Automation.Language.ConvertExpressionAst]){$l=$l.Child};if($l -isnot [Management.Automation.Language.VariableExpressionAst]){continue};"
            "$name=($l.VariablePath.UserPath -replace '^(script|global|local|private):','').ToLowerInvariant();"
            "$f=$n.Parent;while($null -ne $f -and $f -isnot [Management.Automation.Language.FunctionDefinitionAst]){$f=$f.Parent};"
            "if($v.ContainsKey($name) -and ($l.VariablePath.IsScript -or $l.VariablePath.IsGlobal -or $null -eq $f)){$l.Extent.Text+'='+$n.Right.Extent.Text}}});"
            "$sv=@($a.FindAll({param($x)$x -is [Management.Automation.Language.CommandAst] -and $x.GetCommandName() -in @('Set-Variable','New-Variable','sv','nv')},$true)).Count;"
            "'RESULT '+(@{validated=@($v.Keys|Sort-Object);hits=@($hits|Sort-Object);set_variable=$sv}|ConvertTo-Json -Compress)")
    result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-Command', code], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(next(line for line in result.stdout.splitlines() if line.startswith('RESULT '))[len('RESULT '):])


def test_no_assignment_writes_a_validated_parameter_variable():
    value = validated_parameter_assignments(SCRIPT)
    # -Slot and -EffortNullSlug carry no [ValidateSet]: Invoke-AgyIsolationMain enforces slot1 and the three slugs
    # case-sensitively and forces '' for both in -StageOnly mode.
    assert value['validated'] == ['attempt']
    # The remaining write carries the -Attempt Invoke-AgyIsolationMain has already checked (lowercase 32-hex, -cnotmatch).
    assert value['hits'] == ['$script:Attempt=$Attempt'] and value['set_variable'] == 0


@pytest.mark.parametrize('invocation', ['file', 'command'])
@pytest.mark.parametrize('mode,args', SITTING_CALLS)
def test_toplevel_plan_for_each_documented_sitting_call(mode, args, invocation):
    result = smoke.run_toplevel(SCRIPT, args, invocation=invocation)
    assert smoke.plan_mode_outcome(result, plan_schema=PLAN_SCHEMA) == 'plan', result.describe()
    plan = result.plan
    stage = mode == 'stage'
    assert plan['evidence_mode'] == mode and plan['gemini_gate'] == ('G4' if stage else 'G3') and plan['attempt'] == ATTEMPT
    assert plan['slot'] == (None if stage else 'slot1') and plan['effort_null_slug'] == (None if stage else args[3])
    root = str(COCHEM / ('AgyIsolation4.2.7-windows-20261011-r4-v1-' + ATTEMPT + ('-stage' if stage else '')))
    assert plan['target_root'] == root and plan['receipt_name'] == ('stage-receipt.json' if stage else 'isolation-receipt.json')
    assert plan['model_jobs_planned_maximum'] == (0 if stage else 5) and plan['stage_slots'] == (SLOTS if stage else [])
    assert plan['native_commands_executed'] == 0 and plan['tasks_changed'] == 0 and isinstance(plan['holds'], list)


@pytest.mark.parametrize('args,message', [
    (['-Slot', 'slot2', '-Attempt', ATTEMPT], 'Only -Slot slot1 is reviewed. Nothing was changed.'),
    (['-Slot', 'slot1', '-EffortNullSlug', 'gemini-3.1-pro-high', '-Attempt', ATTEMPT],
     'The -EffortNullSlug must be gemini-3.8-flash-low, -medium or -high. Nothing was changed.'),
    (['-Slot', 'slot1', '-EffortNullSlug', 'Gemini-3.8-Flash-Low', '-Attempt', ATTEMPT],
     'The -EffortNullSlug must be gemini-3.8-flash-low, -medium or -high. Nothing was changed.'),
], ids=['slot2', 'other-slug', 'slug-case'])
def test_toplevel_slot_or_slug_outside_the_reviewed_set_is_refused_before_any_host_command(args, message):
    # Without a [ValidateSet] the main function's own checks are the gate (case-sensitive, as before for the slug).
    result = smoke.run_toplevel(SCRIPT, args)
    assert smoke.plan_mode_outcome(result) == 'refusal', result.describe()
    assert result.error.message == message and not result.trace, result.describe()


def test_toplevel_upper_case_slot_is_lowercased_as_before():
    result = smoke.run_toplevel(SCRIPT, ['-Slot', 'SLOT1', '-Attempt', ATTEMPT], invocation='command')
    assert smoke.plan_mode_outcome(result, plan_schema=PLAN_SCHEMA) == 'plan', result.describe()
    assert result.plan['slot'] == 'slot1' and result.plan['effort_null_slug'] == 'gemini-3.8-flash-low'
